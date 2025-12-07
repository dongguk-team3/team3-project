#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, sys, random
from typing import Any, Dict, List, Optional, Tuple
import requests
from playwright.sync_api import sync_playwright, Page

M_URL = "https://m.place.naver.com/restaurant/{place_id}/review/visitor?reviewSort=recent"
PC_URL = "https://pcmap.place.naver.com/restaurant/{place_id}/review/visitor"
SMART_AROUND_URL = "https://map.naver.com/p/api/smart-around/places"

def _normalize_place_type(place_type: Optional[str]) -> Optional[str]:
    """사용자 입력 place_type을 네이버 카테고리 문자열에 맞게 단순 정규화."""
    if not place_type:
        return None
    pt = place_type.strip()
    if pt == "맛집":
        return "음식점"
    if pt.endswith("집") and len(pt) > 1:
        return pt[:-1]
    return pt

# 브라우저 안에서 fetch로 GraphQL을 직접 호출 (쿠키/토큰/Origin 자동세팅)
INPAGE_FETCH = r"""
async ({ placeId, size }) => {
  const tries = 4;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  async function callOnce(businessType) {
    const payload = {
      operationName: "getVisitorReviews",
      query: `
        query getVisitorReviews($input: VisitorReviewsInput) {
          visitorReviews(input: $input) {
            total
            items {
              id
              body
              translatedText
              created
              votedKeywords { displayName }
            }
          }
        }`,
      variables: {
        input: {
          businessId: String(placeId),
          businessType,
          includeContent: true,
          includeReceiptPhotos: true,
          page: 1,
          size: size,
          sort: "recent",
          cidList: ["220036","220037","220053"]
        }
      }
    };

    const res = await fetch("https://pcmap-api.place.naver.com/place/graphql", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload)
    });

    if (res.status === 429) {
      const ra = res.headers.get("retry-after");
      const waitMs = ra ? Math.min(15000, Math.max(1500, Number(ra) * 1000)) : 2000;
      return { status: 429, waitMs };
    }

    if (!res.ok) {
      return { status: res.status, err: await res.text() };
    }

    const data = await res.json();
    if (data && data.data && data.data.visitorReviews) {
      const items = data.data.visitorReviews.items || [];
      const rows = items.map(it => ({
        review_text: (it.body || it.translatedText || "").trim(),
        tag: (it.votedKeywords || []).map(k => k.displayName).filter(Boolean)
      })).filter(r => r.review_text);
      return { status: 200, rows };
    }
    return { status: 200, rows: [] };
  }

  for (let attempt = 1; attempt <= tries; attempt++) {
    for (const bt of ["restaurant", "place"]) {
      const r = await callOnce(bt);
      if (r.status === 200 && r.rows && r.rows.length > 0) {
        return r.rows.slice(0, size);
      }
      if (r.status === 429) {
        await sleep(r.waitMs || attempt * 1000);
      }
    }
    await sleep(attempt * 1000);
  }
  return [];
}
"""

def fetch_inpage(page: Page, place_id: str, size: int) -> List[Dict[str, Any]]:
    return page.evaluate(INPAGE_FETCH, dict(placeId=place_id, size=size))

# -------------------------
# 1. 위/경도 기준 주변 가게 검색
# -------------------------

def get_places_around(
                      lat: float,
                      lon: float,
                      radius_m: int = 1000,
                      limit: int = 60,
                      offset: Optional[int] = None,
                      place_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    smart-around/places 엔드포인트를 이용해서
    (lat, lon) 주변 가게 목록을 가져온 뒤,
    distance <= radius_m 및 place_type이 매칭되는 것만 필터링한다.

    주의: searchCoord는 '경도;위도' 형식이다.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.6,en;q=0.4",
        "referer": "https://map.naver.com/p?c=15.00,0,0,0,dh",
    }

    params = {
        "searchCoord": f"{lon};{lat}",  # 경도;위도
        "limit": limit,
        "sortType": "RECOMMEND",
        "offset": offset or 0,
        # 필요하면 code, timeCode, boundary 등 추가
    }

    r = requests.get(SMART_AROUND_URL, headers=headers, params=params, timeout=5)
    r.raise_for_status()
    data = r.json()

    items = ((data.get("result") or {}).get("list")) or []
    places: List[Dict[str, Any]] = []
    place_type = _normalize_place_type(place_type)
    
    for it in items:
        dist_raw = it.get("distance")
        try:
            dist_m = float(dist_raw) * 1000.0  # API 단위 km → m 변환
        except (TypeError, ValueError):
            continue
        if dist_m > radius_m:
            continue

        category_joined = ",".join(it.get("category") or [])
        category_name = it.get("categoryName", "") or ""
        if place_type and (place_type not in category_name and place_type not in category_joined):
            continue
        
        places.append(
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "distance": dist_m,
                "category": category_joined,
                "categoryName": category_name,
                "address": it.get("address"),
                "roadAddress": it.get("roadAddress"),
                "x": it.get("x"),
                "y": it.get("y"),
            }
        )
        

    return places

# -------------------------
# 2. 단일 place_id에 대해 리뷰 수집
# -------------------------

def fetch_reviews_for_place(page: Page,
                            place_id: str,
                            count: int) -> List[Dict[str, Any]]:
    """기존 코드 재사용: PC뷰 → 실패시 모바일 폴백."""
    urls = [
        PC_URL.format(place_id=place_id),
        M_URL.format(place_id=place_id),
    ]

    for url in urls:
        page.goto(url, wait_until="domcontentloaded")
        for _ in range(2):
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(200)

        rows = fetch_inpage(page, place_id, max(1, count))
        if rows:
            return rows

    return []  # 리뷰를 못가져온 경우

# -------------------------
# 3. 메인: 위/경도 → 가게 10개 샘플 → 리뷰 크롤
# -------------------------

def main(location: Optional[Tuple[float, float]] = None, place_type: Optional[str] = None, 
         radius: int = 1000, places: int = 10, reviews_per_place: int = 3,
         out: str = "nearby_reviews.json", headless: bool = False):
    """
    메인 함수: 위치와 장소 유형을 받아 리뷰를 수집합니다.
    
    Args:
        location: (위도, 경도) 튜플
        place_type: 장소 유형 (예: "카페", "중식집", "일식집", "맛집", "음식점")
        radius: 검색 반경(m), 기본값 1000
        places: 무작위로 뽑을 가게 수, 기본값 10
        reviews_per_place: 가게당 리뷰 수, 기본값 3
        out: 출력 파일명, 기본값 "nearby_reviews.json"
        headless: 헤드리스 모드, 기본값 False
    """
    # CLI 모드 지원 (기존 방식)
    if location is None or place_type is None:
        ap = argparse.ArgumentParser()
        ap.add_argument("--lat", type=float)
        ap.add_argument("--lon", type=float)
        ap.add_argument("--location", type=str, help="위도,경도 형식 (예: 37.0,126.99)")
        ap.add_argument("--place-type", type=str, default="음식점", help="장소 유형 (예: 카페, 중식집)")
        ap.add_argument("--radius", type=int, default=1000, help="검색 반경(m)")
        ap.add_argument("--places", type=int, default=10, help="무작위로 뽑을 가게 수")
        ap.add_argument("--reviews-per-place", type=int, default=3)
        ap.add_argument("--out", default="nearby_reviews.json")
        ap.add_argument("--headless", action="store_true")
        args = ap.parse_args()
        
        # location 파싱
        if args.lat and args.lon:
            location = (args.lat, args.lon)
        elif args.location:
            try:
                lat, lon = map(float, args.location.split(","))
                location = (lat, lon)
            except ValueError:
                print("[ERROR] --location 형식이 잘못되었습니다. '위도,경도' 형식이어야 합니다.")
                sys.exit(1)
        else:
            print("[ERROR] --lat/--lon 또는 --location이 필요합니다.")
            sys.exit(1)
        
        place_type = args.place_type or place_type
        radius = args.radius
        places = args.places
        reviews_per_place = args.reviews_per_place
        out = args.out
        headless = args.headless
    
    lat, lon = location

    # 1) 주변 가게 검색 (누적 + 중복 제거)
    candidate_places: List[Dict[str, Any]] = []
    seen_ids = set()
    offset = 0
    page_limit = 60  # 요청당 크기 조절(과도한 대기 방지)
    max_pages = 10  # 네트워크 대기 시간 상한

    for _ in range(max_pages):
        if len(candidate_places) >= places:
            break

        batch = get_places_around(
            lat=lat,
            lon=lon,
            radius_m=radius,
            limit=page_limit,
            offset=offset,
            place_type=place_type,
        )
        if not batch:
            break

        for place in batch:
            pid = place.get("id")
            if pid is not None and pid in seen_ids:
                continue
            candidate_places.append(place)
            if pid is not None:
                seen_ids.add(pid)
            if len(candidate_places) >= places:
                break

        offset += page_limit

    if not candidate_places:
        if place_type:
            print(f"[WARN] place_type='{place_type}', radius={radius}m 안에서 가게를 찾지 못함")
        else:
            print(f"[WARN] radius={radius}m 안에서 가게를 찾지 못함")
        

    # 3) 무작위로 places개 샘플링
    if len(candidate_places) > places:
        selected = random.sample(candidate_places, places)
    else:
        selected = candidate_places

    results: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        ctx = browser.new_context(
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1300, "height": 1000},
        )
        page = ctx.new_page()

        for place in selected:
            pid = str(place["id"])
            distance = place.get("distance", 0.0)
            latitude = place.get("y")
            longitude = place.get("x")
            reviews = fetch_reviews_for_place(page, pid, reviews_per_place)
     
            results.append(
                {
                    "place": place,
                    "reviews": reviews,
                    "distance": distance,
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )

        ctx.close()
        browser.close()

    # 결과를 새로운 형식으로 변환
    stores = []
    reviews_dict = {}
    distance_dict = {}
    location_dict = {}
    
    
    for item in results:
        place_name = item["place"].get("name", "")
        if place_name:
            stores.append(place_name)
            # 리뷰 텍스트만 추출
            review_texts = [
                review.get("review_text", "").strip()
                for review in item.get("reviews", [])
                if review.get("review_text", "").strip()
            ]
            if review_texts:
                reviews_dict[place_name] = review_texts

            distance_dict[place_name] = round(item.get("distance", 0.0), 3)
            location_dict[place_name] = {"latitude": round(float(item.get("latitude", 0.0)), 4), "longitude": round(float(item.get("longitude", 0.0)), 4)}  
        
    output = {
        "stores": stores,
        "reviews": reviews_dict,
        "distances": distance_dict,
        "locations": location_dict,
    }
    
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(
        f"[OK] location=({lat},{lon}), place_type={place_type}, "
        f"places={len(selected)}, saved={out}"
    )

if __name__ == "__main__":
    main()
# python nearby_reviews.py \
#   --lat 37.0 \
#   --lon 126.99 \
#   --radius 1000 \
#   --places 10 \
#   --reviews-per-place 3 \
#   --out nearby_reviews.json \
#   --headless
