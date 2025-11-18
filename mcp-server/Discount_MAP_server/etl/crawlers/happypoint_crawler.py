from typing import Any, Dict, List
import re
import json
import asyncio
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.happypointcard.com"
LIST_URL = f"{BASE_URL}/page/presentation/brand.spc"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": LIST_URL,
}


def extract_percent(text: str) -> List[float]:
    """
    텍스트에서 '숫자%' + '적립' 패턴을 찾아 리스트로 반환.
    예) '0.5% 적립, 2% 추가적립' → [0.5, 2.0]
    """
    if not text:
        return []
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*적립", text)
    return [float(m) for m in matches]


def clean_space(s: str | None) -> str | None:
    """불필요한 공백/개행 제거"""
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()


def parse_brand_cards(html: str) -> List[Dict[str, Any]]:
    """
    HTML 내 brand-intro-list 영역을 파싱해 브랜드별 정보 추출.

    반환: List[{
        "brandName": str | None,
        "description": str | None,
        "accrualPercents": List[float],
        "link": str | None,
        "rawSnippet": str,
    }]
    """
    soup = BeautifulSoup(html, "lxml")

    root = soup.select_one(".brand-intro-list")
    if not root:
        raise RuntimeError("'.brand-intro-list' 컨테이너를 찾지 못했습니다. 셀렉터 확인 필요.")

    items: List[Dict[str, Any]] = []
    # li만 돌면 충분해서 이렇게 단순하게 가도 됨
    for card in root.select("li"):
        # 1️⃣ 브랜드명
        name_tag = (
            card.select_one(".brand-title")           # <a class="brand-title ...">, <div class="brand-title">
            or card.select_one(".brand-name")         # 혹시 모바일/다른 페이지에서 쓸 수도 있어서 남겨둠
            or card.select_one(".brand-link")         # 방어용
            or card.select_one("a[title]")            # a 태그 title 있는 경우
            or card.select_one("strong")
            or card.select_one("h3, h4")
        )

        brand_name = None
        if name_tag:
            brand_name = clean_space(name_tag.get_text(" ", strip=True))
        else:
            # 그래도 못 찾으면 img alt를 fallback으로 사용
            img_tag = card.select_one("img[alt]")
            if img_tag and img_tag.get("alt"):
                brand_name = clean_space(img_tag["alt"])

        # 2️⃣ 설명(요약문)
        desc_tag = (
            card.select_one(".brand-sub")             # 실제로 여기 사용 중
            or card.select_one(".brand-desc")
            or card.select_one(".txt, .desc, p")
        )
        description = clean_space(desc_tag.get_text(" ", strip=True)) if desc_tag else None

        # 3️⃣ 링크 (브랜드 상세페이지 등)
        link_tag = card.select_one("a.brand-title, a.brand-link, a[href]")
        link = urljoin(BASE_URL, link_tag["href"]) if link_tag and link_tag.get("href") else None

        # 4️⃣ 적립률
        full_text = clean_space(card.get_text(" ", strip=True) or "")
        accrual_percents = extract_percent(full_text)

        # 결과 저장
        if brand_name or description or link:
            items.append(
                {
                    "brandName": brand_name,
                    "description": description,
                    "accrualPercents": accrual_percents,
                    "link": link,
                    "rawSnippet": (full_text[:300] + "...") if len(full_text) > 300 else full_text,
                }
            )

    return items



async def _fetch_html(url: str) -> str:
    """페이지 HTML을 비동기로 가져오기 (내부용)"""
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if resp.encoding is None:
            resp.encoding = resp.apparent_encoding
        return resp.text


async def fetch_happypoint_brands() -> Dict[str, Any]:
    """
    외부에서 import해서 쓰는 메인 함수.

    반환 형식:
    {
      "source": LIST_URL,
      "count": int,
      "brands": [ {...}, {...}, ... ]
    }
    """
    html = await _fetch_html(LIST_URL)
    items = parse_brand_cards(html)

    return {
        "source": LIST_URL,
        "count": len(items),
        "brands": items,
    }


def fetch_happypoint_brands_sync() -> Dict[str, Any]:
    """
    동기 환경에서 사용 가능한 wrapper.

    예)
        from happypoint_crawler import fetch_happypoint_brands_sync
        data = fetch_happypoint_brands_sync()
    """
    return asyncio.run(fetch_happypoint_brands())


if __name__ == "__main__":
    # 테스트/디버깅용 실행부
    data = fetch_happypoint_brands_sync()
    print(f"총 수집 브랜드: {data['count']}개")
    for it in data["brands"][:10]:
        print(" -", it["brandName"], "| 적립률:", it["accrualPercents"])

    with open("happypoint_brands.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ 저장 완료: happypoint_brands.json")
