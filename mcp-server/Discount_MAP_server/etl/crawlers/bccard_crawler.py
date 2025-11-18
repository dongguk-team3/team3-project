from typing import Any, Dict, List
import asyncio

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://vip.bccard.com/app/vip/ContentsLinkActn.do"
DEFAULT_PGM_IDS = ["vip0142", "vip0143", "vip0144"]


async def _fetch_vip_page_html(
    client: httpx.AsyncClient,
    pgm_id: str,
) -> str:
    """
    BLISS.7 관련 개별 서비스 페이지 HTML을 가져오는 함수.
    예: https://vip.bccard.com/app/vip/ContentsLinkActn.do?pgm_id=vip0142
    """
    params = {"pgm_id": pgm_id}

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://vip.bccard.com/app/vip/ContentsLinkActn.do?pgm_id=vip0170",
        "Origin": "https://vip.bccard.com",
    }

    res = await client.get(BASE_URL, params=params, headers=headers, timeout=10.0)
    res.raise_for_status()
    return res.text


def _extract_section_items_from_anchor_img(
    soup: BeautifulSoup,
    section_alt: str,
) -> List[str]:
    """
    alt 텍스트(예: '이용안내', '유의사항')를 가진 <img> 태그를 기준으로
    주변 영역에서 <li> 텍스트들을 추출한다.
    """
    img = soup.find("img", alt=section_alt)
    if not img:
        return []

    candidates = []
    parent = img.parent
    for _ in range(5):
        if not parent:
            break
        candidates.append(parent)
        parent = parent.parent

    items: List[str] = []
    for cand in candidates:
        for li in cand.find_all("li"):
            text = li.get_text(" ", strip=True)
            if text:
                items.append(text)
        if items:
            break

    return items


def _collect_items_from_block(block) -> List[str]:
    """
    어떤 블록 요소 안에서 table 또는 ul > li를 찾아
    사람이 읽기 좋은 한 줄짜리 텍스트로 정리.
    """
    items: List[str] = []

    # 1) table 우선
    table = block.find("table")
    if table:
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                items.append(" | ".join(cells))

    # 2) ul > li
    if not items:
        for ul in block.find_all("ul"):
            for li in ul.find_all("li"):
                text = li.get_text(" ", strip=True)
                if text:
                    items.append(text)

    return items


def _extract_service_locations(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    '서비스 제공 레스토랑', '서비스 제공 지점' 등
    실제 서비스 제공 매장/지점을 설명하는 블록에서 정보를 추출.

    반환 형식:
    [
      {
        "title": "서비스 제공 레스토랑",
        "items": ["OOO 호텔 레스토랑 ...", "OOO 브런치 ...", ...]
      },
      {
        "title": "서비스 제공 지점",
        "items": ["서울역점 ...", "인천공항점 ...", ...]
      }
    ]
    """
    target_keywords = [
        "서비스 제공 레스토랑",
        "서비스 제공 지점",
        "서비스가 제공되는 레스토랑",
        "서비스 제공 매장",
    ]

    results: List[Dict[str, Any]] = []
    seen_blocks = set()

    for kw in target_keywords:
        # 1) img alt 에 kw 포함
        for img in soup.find_all("img", alt=lambda x: x and kw in x):
            parent = img.parent
            for _ in range(5):
                if not parent:
                    break
                block = parent
                parent = parent.parent

                block_id = id(block)
                if block_id in seen_blocks:
                    continue

                items = _collect_items_from_block(block)
                if items:
                    results.append(
                        {
                            "title": kw,
                            "items": items,
                        }
                    )
                    seen_blocks.add(block_id)
                    break  # 이 kw에 대해 이 블록은 처리 완료

        # 2) 텍스트 노드에 kw 포함
        for node in soup.find_all(string=lambda s: s and kw in s):
            elem = node.parent
            parent = elem
            for _ in range(5):
                if not parent:
                    break
                block = parent
                parent = parent.parent

                block_id = id(block)
                if block_id in seen_blocks:
                    continue

                items = _collect_items_from_block(block)
                if items:
                    results.append(
                        {
                            "title": kw,
                            "items": items,
                        }
                    )
                    seen_blocks.add(block_id)
                    break

    return results


def _parse_vip_page(html: str, pgm_id: str) -> Dict[str, Any]:
    """
    VIP BLISS 서비스 페이지 HTML에서 필요한 정보만 파싱.

    - card_name: 'BLISS.7 카드' (고정)
    - pgm_id: vip0142 / vip0143 / vip0144
    - page_title: <title> 내용
    - breadcrumb: 상단 위치 정보 (ex. '카드서비스 > BLISS > Dining & Wine > F&B 적립')
    - sections: 이용안내 / 유의사항 등 텍스트
    - service_locations: 서비스 제공 레스토랑/지점 정보
    """
    soup = BeautifulSoup(html, "html.parser")

    # <title> 태그에서 페이지 제목
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else None

    # 상단 위치 (breadcrumb)
    breadcrumb = None
    loc = soup.select_one(".location ul")
    if loc:
        crumbs = [li.get_text(" ", strip=True) for li in loc.select("li")]
        crumbs = [c for c in crumbs if c]
        if crumbs:
            breadcrumb = " > ".join(crumbs)

    # '이용안내', '유의사항' 섹션
    sections: List[Dict[str, Any]] = []
    for section_title in ["이용안내", "유의사항"]:
        items = _extract_section_items_from_anchor_img(soup, section_title)
        if items:
            sections.append(
                {
                    "title": section_title,
                    "items": items,
                }
            )

    # 서비스 제공 레스토랑 / 서비스 제공 지점 섹션
    service_locations = _extract_service_locations(soup)

    return {
        "card_name": "BLISS.7 카드",
        "pgm_id": pgm_id,
        "page_title": page_title,
        "breadcrumb": breadcrumb,
        "sections": sections,
        "service_locations": service_locations,
    }


async def fetch_bliss7_vip_services(
    pgm_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    - 기본: vip0142 / vip0143 / vip0144 세 페이지 크롤링
    - 각 페이지에서 이용안내/유의사항 + 서비스 제공 레스토랑/지점 정보를 JSON으로 구조화
    """
    if pgm_ids is None:
        pgm_ids = DEFAULT_PGM_IDS

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_vip_page_html(client, pgm_id=pgm_id)
            for pgm_id in pgm_ids
        ]
        html_list = await asyncio.gather(*tasks)

    results: List[Dict[str, Any]] = []
    for pgm_id, html in zip(pgm_ids, html_list):
        parsed = _parse_vip_page(html, pgm_id=pgm_id)
        results.append(parsed)

    return results


def fetch_bliss7_vip_services_sync(
    pgm_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    return asyncio.run(fetch_bliss7_vip_services(pgm_ids))


if __name__ == "__main__":
    import json

    data = fetch_bliss7_vip_services_sync()
    print(json.dumps(data, ensure_ascii=False, indent=2))
