from __future__ import annotations
from typing import Any, Dict, List
import asyncio
import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://sktmembership.tworld.co.kr"
LIST_URL = f"{BASE_URL}/mps/pc-bff/benefitbrand/list-tab2.do"
DETAIL_URL = f"{BASE_URL}/mps/pc-bff/benefitbrand/detail.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
}

# 관심있는 EAT 4개 카테고리
TARGET_CATEGORY_IDS = {"53", "54", "55", "56"}  # 베이커리, 외식, 카페/아이스크림, 피자/치킨


# ------------------------------
#  Helpers
# ------------------------------
def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


# ------------------------------
# LIST PAGE (list-tab2.do)
# ------------------------------
async def _fetch_list_html(client: httpx.AsyncClient) -> str:
    resp = await client.get(LIST_URL)
    resp.raise_for_status()
    if resp.encoding is None:
        resp.encoding = resp.apparent_encoding
    return resp.text


def _parse_brand_list(html: str) -> List[Dict[str, Any]]:
    """
    list-tab2.do에서 EAT 4개 카테고리 브랜드 목록만 추출
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    for cate_box in soup.select(".category-list .cate-box"):
        cate_top = cate_box.select_one(".cate-top")
        if not cate_top:
            continue

        category_id = cate_top.get("data-id", "").strip()
        category_name = _clean_text(cate_top.get("data-text", ""))

        if category_id not in TARGET_CATEGORY_IDS:
            continue

        for a in cate_box.select(".list-dash a.benefit-box"):
            brand_id = a.get("data-id", "").strip()
            brand_name = _clean_text(a.get_text())
            if brand_id:
                results.append({
                    "brandId": brand_id,
                    "brandName": brand_name,
                    "categoryId": category_id,
                    "categoryName": category_name,
                })

    return results


async def fetch_brand_list(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    html = await _fetch_list_html(client)
    return _parse_brand_list(html)


# ------------------------------
# DETAIL PAGE (detail.do)
# ------------------------------
def _parse_membership_levels(badge_span) -> List[str]:
    level_map = {"V": "VIP", "G": "GOLD", "S": "SILVER", "L": "LITE"}
    levels = []
    for tag in badge_span.select("i.badge-circle"):
        blind = tag.select_one("span.blind")
        if blind:
            c = blind.get_text(strip=True)
            if c in level_map:
                levels.append(level_map[c])
    return list(dict.fromkeys(levels))


def _parse_benefits(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    benefits = []
    detail_list = soup.select_one(".brand-detail .detail-list")
    if not detail_list:
        return benefits

    # dt == 혜택
    benefit_dl = None
    for dl in detail_list.select("dl"):
        dt = dl.find("dt")
        if dt and _clean_text(dt.get_text()) == "혜택":
            benefit_dl = dl
            break

    if not benefit_dl:
        return benefits

    for bnf in benefit_dl.select("dl.dl-bnf"):
        variant_type = _clean_text(bnf.find("dt").get_text()) if bnf.find("dt") else ""

        for info in bnf.select("dd div.info"):
            badge_span = info.select_one(".badge-list")
            levels = _parse_membership_levels(badge_span) if badge_span else []

            # 텍스트만 추출
            clone = BeautifulSoup(str(info), "lxml")
            for b in clone.select(".badge-list"):
                b.decompose()
            desc = _clean_text(clone.get_text())

            if desc:
                benefits.append({
                    "variantType": variant_type,
                    "membershipLevels": levels,
                    "description": desc,
                })

    return benefits


def _parse_notes(soup: BeautifulSoup) -> List[str]:
    detail_list = soup.select_one(".brand-detail .detail-list")
    if not detail_list:
        return []

    notes_dl = None
    for dl in detail_list.select("dl"):
        dt = dl.find("dt")
        if dt and "유의사항" in _clean_text(dt.get_text()):
            notes_dl = dl
            break

    if not notes_dl:
        return []

    return [_clean_text(li.get_text()) for li in notes_dl.select(".list-dot li")]


async def _fetch_detail_html(client: httpx.AsyncClient, brand_id: str) -> str:
    resp = await client.get(DETAIL_URL, params={"brandId": brand_id})
    resp.raise_for_status()
    if resp.encoding is None:
        resp.encoding = resp.apparent_encoding
    return resp.text


def _parse_brand_detail(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    brand_id = soup.select_one("#brandId").get("value", "") if soup.select_one("#brandId") else ""
    brand_name = soup.select_one("#brandName").get("value", "") if soup.select_one("#brandName") else ""
    category_id = soup.select_one("#categoryMid").get("value", "") if soup.select_one("#categoryMid") else ""
    category_name = soup.select_one("#categoryMname").get("value", "") if soup.select_one("#categoryMname") else ""

    return {
        "brandId": brand_id,
        "brandName": brand_name,
        "categoryId": category_id,
        "categoryName": category_name,
        "benefits": _parse_benefits(soup),
        "notes": _parse_notes(soup),
    }


async def fetch_brand_detail(client: httpx.AsyncClient, brand_id: str) -> Dict[str, Any]:
    html = await _fetch_detail_html(client, brand_id)
    return _parse_brand_detail(html)


# ------------------------------
# PUBLIC MAIN FUNCTION → other files import here
# ------------------------------
async def fetch_skt_eat_benefits() -> List[Dict[str, Any]]:
    """
    외부에서 import하여 바로 사용 가능한 최종 함수.
    EAT 4개 카테고리 베이커리/외식/카페/피자&치킨 전체 브랜드의:
    - 혜택
    - 유의사항
    을 포함한 JSON 리스트를 반환한다.
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        brands_basic = await fetch_brand_list(client)

        # detail 병렬 요청
        tasks = [
            fetch_brand_detail(client, b["brandId"])
            for b in brands_basic
        ]
        return await asyncio.gather(*tasks)


# ------------------------------
# Optional: local test
# ------------------------------
if __name__ == "__main__":
    import json
    data = asyncio.run(fetch_skt_eat_benefits())
    print(json.dumps(data, ensure_ascii=False, indent=2))
