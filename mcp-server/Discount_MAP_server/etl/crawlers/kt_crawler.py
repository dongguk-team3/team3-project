from __future__ import annotations
from typing import List, Dict, Optional
import asyncio
import httpx
from bs4 import BeautifulSoup


BASE_URL = "https://m.membership.kt.com"
LIST_API_URL = f"{BASE_URL}/discount/partner/s_PartnerListHtml.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Origin": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
}


# ---------------------------------------
# Helpers
# ---------------------------------------
def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return " ".join(text.split())


# ---------------------------------------
# 페이지 1개 요청(fetch)
# ---------------------------------------
async def _fetch_page(
    client: httpx.AsyncClient,
    dae_code: str,
    page: int,
) -> str:
    """
    KT 멤버십 제휴 브랜드 HTML fragment (특정 페이지)를 가져온다.
    """
    data = {
        "daeCode": dae_code,
        "pageNo": str(page),
        "searchName": "",
        "jungCode": "",
    }

    headers = {
        **HEADERS,
        "Referer": f"{BASE_URL}/discount/partner/s_PartnerList.do?daeCode={dae_code}",
    }

    resp = await client.post(LIST_API_URL, data=data, headers=headers, timeout=10.0)
    resp.raise_for_status()

    # KT는 HTML fragment를 text로 반환
    if resp.encoding is None:
        resp.encoding = resp.apparent_encoding

    return resp.text


# ---------------------------------------
# HTML → 브랜드 데이터 파싱(parse)
# ---------------------------------------
def _parse_partners(html: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html, "lxml")
    partners: List[Dict[str, Optional[str]]] = []

    # li[data-jungcode] 가 브랜드 1개에 해당
    for li in soup.find_all("li", attrs={"data-jungcode": True}):
        name_tag = li.find("strong", class_="sec-cont-tit")
        benefit_tag = li.find("span", class_="sec-cont-list")

        if not name_tag or not benefit_tag:
            continue

        brand_name = _clean_text(name_tag.get_text(strip=True))
        summary = _clean_text(benefit_tag.get_text(" ", strip=True))

        # 상세 정보
        detail_box = li.find("div", class_="view-detail-box")
        usage: Optional[str] = None
        guide: Optional[str] = None
        contact: Optional[str] = None

        if detail_box:
            for li_detail in detail_box.select("ul.discount-detail > li"):
                title_tag = li_detail.find("span", class_="tit")
                text_tag = li_detail.find("p", class_="text")

                if not title_tag or not text_tag:
                    continue

                title = _clean_text(title_tag.get_text(strip=True))
                text = _clean_text(text_tag.get_text(" ", strip=True))

                if title == "이용횟수":
                    usage = text
                elif title == "이용안내":
                    guide = text
                elif title == "연락처":
                    contact = text

        partners.append({
            "brandName": brand_name,
            "summary": summary,
            "usageLimit": usage,
            "guide": guide,
            "contact": contact,
        })

    return partners


# ---------------------------------------
# PUBLIC: 전체 페이지 수집 함수
# ---------------------------------------
async def fetch_kt_partners_all(
    dae_code: str = "C21",
    max_pages: int = 50,
) -> List[Dict[str, Optional[str]]]:
    """
    외부에서 import해서 사용하는 KT 멤버십 크롤러 메인 함수.

    page=1 ~ n 까지 자동으로 요청(더보기와 동일)
    항목이 없는 페이지가 나오면 중단하고 지금까지 모은 모든 정보를 반환.
    """
    all_data: List[Dict[str, Optional[str]]] = []

    async with httpx.AsyncClient() as client:
        for page in range(1, max_pages + 1):
            html = await _fetch_page(client, dae_code, page)
            parsed = _parse_partners(html)

            # 더 이상 아이템이 없으면 종료
            if not parsed:
                break

            all_data.extend(parsed)

    return all_data


# ---------------------------------------
# Optional: CLI 테스트
# ---------------------------------------
if __name__ == "__main__":
    import json

    data = asyncio.run(fetch_kt_partners_all("C21"))
    print(f"총 {len(data)}개 수집됨")
    print(json.dumps(data[:5], ensure_ascii=False, indent=2))