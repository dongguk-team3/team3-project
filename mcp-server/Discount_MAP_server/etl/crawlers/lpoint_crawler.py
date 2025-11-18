# lpoint_fnb_crawler.py

import re
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.lpoint.com"
LIST_URL = f"{BASE_URL}/app/useplace/LHUI100100.do"
DETAIL_URL = f"{BASE_URL}/app/useplace/LHUI100101.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Referer": LIST_URL,
}


# ---------------------------
# 1) 리스트 HTML 파싱
# ---------------------------

def parse_fnb_list(html: str) -> List[Dict[str, str]]:
    """
    외식 탭(LHUI100100.do, ctgId=2) HTML에서
    #useList 내부 가맹점 목록을 파싱한다.
    - brandName
    - benefitSummary
    - popObjId
    - copUnitC (onclick 안에 있는 코드)
    """
    soup = BeautifulSoup(html, "lxml")

    use_list = soup.find("div", id="useList")
    if not use_list:
        return []

    affiliates: List[Dict[str, str]] = []

    for a in use_list.select("a.btn-list"):
        pop_obj_id = a.get("id") or ""

        brand_el = a.find("div", class_="brand")
        brand_name = brand_el.get_text(strip=True) if brand_el else ""

        benefit_el = a.find("div", class_="benefit")
        benefit = benefit_el.get_text(strip=True) if benefit_el else ""

        onclick = a.get("onclick") or ""
        # fnDetail(this.id,'0012396');return false;
        m = re.search(r"fnDetail\(this\.id,'([^']+)'\)", onclick)
        cop_unit_c = m.group(1) if m else ""

        affiliates.append(
            {
                "brandName": brand_name,
                "benefitSummary": benefit,
                "popObjId": pop_obj_id,
                "copUnitC": cop_unit_c,
            }
        )

    return affiliates


# ---------------------------
# 2) 상세 팝업 HTML 파싱
# ---------------------------

def parse_detail_html(content_html: str) -> Dict[str, Optional[str]]:
    """
    LHUI100101.do 의 Content(HTML 조각)를 파싱한다.
    - 로고 이미지, 아이콘 박스는 무시
    - name, bnfit, status, '상세내용' 블록 텍스트만 추출
    """
    soup = BeautifulSoup(content_html, "lxml")

    # 상단 브랜드 영역
    brand_name: Optional[str] = None
    benefit_title: Optional[str] = None

    details_box = soup.select_one(".affiliate-guide .brand-area .details")
    if details_box:
        name_el = details_box.find("div", class_="name")
        bnfit_el = details_box.find("div", class_="bnfit")

        brand_name = name_el.get_text(strip=True) if name_el else None
        benefit_title = bnfit_el.get_text(strip=True) if bnfit_el else None

    # 상태 (예: L.PAY 오프라인)
    status_el = soup.select_one(".affiliate-guide .infomation-area .status-rec")
    status_text = status_el.get_text(strip=True) if status_el else None

    # '상세내용' 블록
    detail_text: Optional[str] = None
    text_wrap = soup.select_one(".affiliate-guide .infomation-area .text-wrap")
    if text_wrap:
        for list_div in text_wrap.select("div.list"):
            title_el = list_div.find("p", class_="tit")
            title = title_el.get_text(strip=True) if title_el else ""
            if "상세내용" in title:
                # 상단 제목("상세내용") 제외하고 나머지 텍스트만 모은다.
                raw_text = list_div.get_text("\n", strip=True)
                lines = [line for line in raw_text.split("\n") if line and line != title]
                detail_text = "\n".join(lines) if lines else None
                break

    return {
        "brandName": brand_name,
        "benefitTitle": benefit_title,
        "status": status_text,
        "detailText": detail_text,
    }


# ---------------------------
# 3) HTTP 호출 (외식 탭 + 상세)
# ---------------------------

async def fetch_fnb_list_html(client: httpx.AsyncClient) -> str:
    """
    외식(ctgId=2) 탭의 사용처 리스트 HTML을 가져온다.
    form1 의 hidden 필드 기반:
      - bultFdC=98
      - ctgId=2    (외식)
      - pageNo=1
    """
    params = {
        "bultFdC": "98",
        "ctgId": "2",   # 외식
        "pageNo": "1",
    }
    resp = await client.get(LIST_URL, params=params, headers=HEADERS, timeout=10.0)
    resp.raise_for_status()
    return resp.text


async def fetch_detail_json(
    client: httpx.AsyncClient,
    pop_obj_id: str,
    cop_unit_c: str,
) -> Dict[str, Any]:
    """
    LHUI100101.do 를 호출해서 JSON 응답을 받고,
    그 중 Content(HTML 조각)를 파싱한다.
    """
    data = {
        "popObjId": pop_obj_id,
        "copUnitC": cop_unit_c,
    }

    detail_headers = {
        **HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    resp = await client.post(
        DETAIL_URL,
        data=data,
        headers=detail_headers,
        timeout=10.0,
    )
    resp.raise_for_status()

    # 응답은 JSON 문자열( Status + Content ) 형태
    payload = resp.json()
    status = payload.get("Status", {})
    if status.get("code") != 0:
        # 에러면 raw를 그대로 넘겨서 나중에 디버깅 가능하도록
        return {
            "raw": payload,
            "parsed": None,
        }

    content_html = payload.get("Content", "") or ""
    parsed = parse_detail_html(content_html)

    return {
        "raw": payload,
        "parsed": parsed,
    }


# ---------------------------
# 4) 통합 호출 함수
# ---------------------------

async def fetch_lpoint_fnb_affiliates() -> Dict[str, Any]:
    """
    L.POINT 사용처 안내 - 외식 탭에 대해
    1) 리스트(LHUI100100.do, ctgId=2)에서 가맹점/코드(popObjId, copUnitC) 파싱
    2) 각 가맹점에 대해 상세(LHUI100101.do) 호출 & 파싱
    을 모두 수행하고 JSON 형태로 반환한다.
    """
    async with httpx.AsyncClient() as client:
        list_html = await fetch_fnb_list_html(client)
        base_affiliates = parse_fnb_list(list_html)

        result_affiliates: List[Dict[str, Any]] = []

        for item in base_affiliates:
            detail = await fetch_detail_json(
                client,
                pop_obj_id=item["popObjId"],
                cop_unit_c=item["copUnitC"],
            )

            result_affiliates.append(detail["parsed"])

    return {
        "category": "외식",
        "totalCount": len(result_affiliates),
        "affiliates": result_affiliates,
    }


# ---------------------------
# 5) 단독 실행 테스트
# ---------------------------

if __name__ == "__main__":
    import asyncio
    import json

    async def _test():
        data = await fetch_lpoint_fnb_affiliates()
        print(json.dumps(data, ensure_ascii=False, indent=2))

    asyncio.run(_test())
