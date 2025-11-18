"""LLM 추출 정보를 네이버 지역 검색 및 리뷰 크롤링과 연결하는 스크립트."""

import asyncio
import importlib.util
import json
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from location_server_config import (
    NAVER_SEARCH_CLIENT_ID,
    NAVER_SEARCH_CLIENT_SECRET,
    NAVER_APP_CLIENT_ID,
    NAVER_APP_CLIENT_SECRET,
    NAVER_GEOCODE_URL,
)
from review_crawler import ReviewCrawler, NaverPlaceAPIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_RESULTS = 5
REVIEWS_PER_STORE = 3


@dataclass
class QueryIntent:
    original_query: str
    place_type: str
    attributes: List[str]
    location: Optional[str]


ATTRIBUTE_KEYWORDS: Dict[str, str] = {
    "맛있는": "맛있는",
    "야식": "야식",
    "분위기좋은": "분위기 좋은",
    "괜찮은": "괜찮은",
    "1인분주문가능": "1인분",
    "배달": "배달",
    "신규": "신규",
    "회식": "회식",
    "부모님": "부모님 모시기",
    "가성비좋은": "가성비",
    "뜨끈한": "뜨끈한",
    "특별한날": "특별한 날",
    "아침": "아침",
    "숨겨진": "숨겨진",
    "반찬": "반찬",
    "포장": "포장",
    "다회용기": "다회용기",
    "야외": "야외 테라스",
    "애견동반": "애견동반",
}

PLACE_TYPE_MAPPING: Dict[str, str] = {
    "카페": "카페",
    "카페/디저트": "디저트 카페",
    "맛집": "맛집",
    "한식": "한식",
    "피자/양식": "양식",
    "찜/탕": "찜",
    "도시락/죽": "도시락",
    "일식/돈까스": "돈까스",
    "치킨": "치킨",
    "회/초밥": "초밥",
    "일식": "이자카야",
    "분식": "분식",
    "족발/보쌈": "족발",
    "중식": "중식",
    "고기/구이": "고기 구이",
    "샐러드": "샐러드",
    "패스트푸드": "버거",
    "아시안": "아시안",
    "술집": "술집",
}


def attribute_keywords(attributes: List[str]) -> str:
    words = [ATTRIBUTE_KEYWORDS.get(attr, "") for attr in attributes]
    return " ".join(word for word in words if word)


def map_place_type(place_type: str) -> str:
    return PLACE_TYPE_MAPPING.get(place_type, place_type)


def resolve_search_terms(intent: QueryIntent) -> Tuple[str, str]:
    place_keyword = map_place_type(intent.place_type)
    parts: List[str] = []
    if intent.location:
        parts.append(intent.location)
    if place_keyword:
        parts.append(place_keyword)
    attr = attribute_keywords(intent.attributes)
    if attr:
        parts.append(attr)
    if not parts:
        parts.append(intent.original_query)
    search_keyword = " ".join(parts)
    return search_keyword, place_keyword


async def load_test_queries() -> Tuple[List[str], Any]:
    project_root = Path(__file__).resolve().parents[2]
    test_module_path = project_root / ".vscode" / "android_discount_app" / "test_real_user_queries.py"

    spec = importlib.util.spec_from_file_location("test_real_user_queries", test_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("test_real_user_queries.py 모듈을 로드할 수 없습니다.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]

    queries = getattr(module, "test_queries", None)
    extractor = getattr(module, "_extract_keywords_fallback", None)
    if not queries or not extractor:
        raise RuntimeError("테스트 쿼리 또는 키워드 추출 함수를 찾을 수 없습니다.")

    return queries, extractor


def extract_place_id(link: str) -> Optional[str]:
    match = re.search(r"/place/(\d+)", link)
    if match:
        return match.group(1)
    match = re.search(r"placeId=(\d+)", link)
    if match:
        return match.group(1)
    return None


async def search_places(
    naver_client: NaverPlaceAPIClient,
    intent: QueryIntent,
    center: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    """네이버 지역 검색 API로 장소 검색 (실제 데이터만 사용, mock 폴백 제거)"""
    search_keyword, place_keyword = resolve_search_terms(intent)
    
    # 네이버 검색 API 호출 (좌표가 있으면 활용)
    documents = await naver_client.search_place(
        search_keyword, 
        display=DEFAULT_RESULTS,
        lat=center[0] if center else None,
        lng=center[1] if center else None,
    )

    # 실제 리뷰만 사용 (mock 폴백 제거)
    crawler_real = ReviewCrawler(use_mock=False)

    stores: List[Dict[str, Any]] = []
    for item in documents:
        link = item.get("link", "")
        place_id = extract_place_id(link)

        store = {
            "id": place_id or item.get("title"),
            "name": re.sub(r"<.*?>", "", item.get("title", "")),
            "category": item.get("category"),
            "address": item.get("address"),
            "road_address": item.get("roadAddress"),
            "phone": item.get("telephone"),
            "place_url": link,
            "mapx": item.get("mapx"),
            "mapy": item.get("mapy"),
            "naver_place_id": place_id,
            "searched_keyword": search_keyword,
            "matched_place_keyword": place_keyword,
        }

        # 실제 리뷰만 수집 (mock 폴백 제거)
        reviews: List[Dict[str, Any]] = []
        if place_id:
            reviews = await crawler_real.get_place_reviews(
                store_info=store,
                max_reviews=REVIEWS_PER_STORE,
                source="naver",
            )
            if reviews:
                logger.info(f"✅ {store['name']}: 실제 리뷰 {len(reviews)}개 수집 완료")
            else:
                logger.warning(f"⚠️ {store['name']}: 리뷰를 가져올 수 없습니다 (place_id={place_id})")
        else:
            logger.warning(f"⚠️ {store['name']}: place_id가 없어 리뷰를 가져올 수 없습니다")

        store["reviews"] = reviews  # 리뷰가 없어도 빈 리스트로 저장
        stores.append(store)

    result: Dict[str, Any] = {
        "intent": {
            "original_query": intent.original_query,
            "place_type": intent.place_type,
            "attributes": intent.attributes,
            "location": intent.location,
            "search_keyword": search_keyword,
        },
        "total_count": len(stores),
        "stores": stores,
    }

    # 지오코딩 결과가 있으면 center 값 추가
    if center:
        result["center"] = {"latitude": center[0], "longitude": center[1]}
    else:
        result["center"] = None

    return result


async def geocode_location(session: aiohttp.ClientSession, location: str) -> Optional[Tuple[float, float]]:
    """위치 문자열을 네이버 지도 지오코딩 API로 위·경도 좌표로 변환"""
    if not (NAVER_APP_CLIENT_ID and NAVER_APP_CLIENT_SECRET):
        logger.warning("네이버 지도 앱 키가 없어 지오코딩을 건너뜁니다.")
        return None

    if not location or not location.strip():
        logger.warning("⚠️ 위치 문자열이 비어있습니다.")
        return None

    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_APP_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_APP_CLIENT_SECRET,
    }
    params = {"query": location.strip()}

    try:
        async with session.get(NAVER_GEOCODE_URL, headers=headers, params=params) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("❌ 네이버 지오코딩 실패(%s): %s", response.status, text)
                return None
            data = await response.json()
    except Exception as exc:
        logger.error("❌ 네이버 지오코딩 오류: %s", exc)
        return None

    addresses = data.get("addresses") or []
    if not addresses:
        logger.warning("⚠️ 지오코딩 결과가 없습니다. location=%s", location)
        return None

    first = addresses[0]
    try:
        latitude = float(first.get("y"))
        longitude = float(first.get("x"))
        logger.info(f"✅ 지오코딩 성공: {location} -> ({latitude}, {longitude})")
        return latitude, longitude
    except (TypeError, ValueError):
        logger.error("❌ 지오코딩 좌표 변환 실패: %s", first)
        return None
    

async def process_queries() -> List[Dict[str, Any]]:
    if not (NAVER_SEARCH_CLIENT_ID and NAVER_SEARCH_CLIENT_SECRET):
        raise RuntimeError("NAVER_SEARCH_CLIENT_ID/SECRET가 설정되어 있지 않습니다.")

    queries, extractor = await load_test_queries()
    intents: List[QueryIntent] = []
    for q in queries:
        keywords = extractor(q)
        intents.append(
            QueryIntent(
                original_query=q,
                place_type=keywords.get("place_type") or "맛집",
                attributes=keywords.get("attributes") or [],
                location=keywords.get("location"),
            )
        )

    naver_client = NaverPlaceAPIClient(
        client_id=NAVER_SEARCH_CLIENT_ID,
        client_secret=NAVER_SEARCH_CLIENT_SECRET,
    )

    results: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession() as session:
        for intent in intents:
            center: Optional[Tuple[float, float]] = None
            if intent.location:
                center = await geocode_location(session, intent.location)
                
            try:
                result = await search_places(naver_client, intent, center=center)
                results.append(result)
                
            except Exception as exc:
                logger.error("❌ 검색 처리 실패: %s", exc)
                results.append(
                    {
                        "intent": {
                            "original_query": intent.original_query,
                            "error": str(exc),
                        }
                    }
                )

    return results


def main() -> None:
    results = asyncio.run(process_queries())
    output_path = Path(__file__).with_name("query_results.json")
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 결과를 {output_path} 파일로 저장했습니다.")


if __name__ == "__main__":
    main()
