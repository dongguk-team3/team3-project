from typing import Any, Dict, List
import json

import httpx
from bs4 import BeautifulSoup
import asyncio

BASE_URL = "https://www.cjone.com"


async def _fetch_numbers(cat_cd: int = 2) -> dict:
    """
    getBrandList.do 에서 cat_cd 카테고리의 브랜드 리스트 JSON을 가져온다.
    """
    url = "https://www.cjone.com/cjmweb/point-card/getBrandList.do"

    data = {
        "coopco_cd": "",
        "brnd_cd": "",
        "mcht_no": "",
        "cat_cd": f"{cat_cd:02d}",  # 서버는 "02" 같은 문자열을 기대
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cjone.com/cjmweb/point-card/brand.do",
        "Origin": "https://www.cjone.com",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(url, data=data, headers=headers, timeout=10.0)
        res.raise_for_status()
        return res.json()


def _parse_brand_list(obj_json: dict, cat_cd: int = 2) -> List[Dict[str, Any]]:
    """
    getBrandList.do에서 받아온 JSON(obj_json) 하나를
    우리가 필요한 필드만 남겨서 정리한다.
    """
    brand_list = obj_json.get("brandList", [])

    results: List[Dict[str, Any]] = []

    for item in brand_list:
        cat_name = item.get("code_name")
        coopco_cd = item.get("coopco_cd")
        brnd_cd = item.get("brnd_cd")
        mcht_no = item.get("mcht_no")
        brand_name = item.get("brnd_nm")
        benefit = item.get("brnd_bnf_sum")

        results.append(
            {
                "cat_cd": f"{cat_cd:02d}",  # 카테고리 코드 (문자열 "02" 형태)
                "cat_name": cat_name,       # 예: "외식"
                "coopco_cd": coopco_cd,
                "brnd_cd": brnd_cd,
                "mcht_no": mcht_no,
                "brand_name": brand_name,
                "benefit": benefit,
            }
        )

    return results


async def _fetch_detail_html(
    client: httpx.AsyncClient,
    coopco_cd: str,
    brnd_cd: str,
    mcht_no: str,
    cat_cd: int = 2,
) -> str:
    """
    제휴 브랜드 상세 페이지 HTML을 가져오는 내부 함수.
    예: https://www.cjone.com/cjmweb/point-card/brand/detail.do?coopco_cd=7620&brnd_cd=6201&mcht_no=6201&cat_cd=02
    """
    url = "https://www.cjone.com/cjmweb/point-card/brand/detail.do"

    params = {
        "coopco_cd": coopco_cd,
        "brnd_cd": brnd_cd,
        "mcht_no": mcht_no,
        "cat_cd": f"{cat_cd:02d}",
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cjone.com/cjmweb/point-card/brand.do",
        "Origin": "https://www.cjone.com",
    }

    res = await client.get(url, params=params, headers=headers, timeout=10.0)
    res.raise_for_status()
    return res.text


def _parse_detail_html(html: str) -> Dict[str, Any]:
    """
    상세 페이지 HTML에서 '필요한 정보만' 골라내는 함수.

      - 상세 제목(브랜드명)
      - 상세 설명 텍스트 블록
      - point_benefit 영역의 각 dl(title + li 리스트)
    """
    soup = BeautifulSoup(html, "html.parser")

    # 상단 큰 타이틀/설명 (cont_header 영역)
    title_tag = soup.select_one(".cont_header .h1_tit")
    desc_tag = soup.select_one(".cont_header .h_desc")

    detail_title = title_tag.get_text(strip=True) if title_tag else None
    detail_desc = desc_tag.get_text(" ", strip=True) if desc_tag else None

    # 우리가 원하는 핵심: point_benefit 안의 .cont 블록
    cont = soup.select_one(".detail_sec.point_benefit .answer_wrap .cont")

    benefit_sections: List[Dict[str, Any]] = []

    if cont:
        for dl in cont.select("dl"):
            dt = dl.select_one("dt")
            dd = dl.select_one("dd")

            section_title = dt.get_text(" ", strip=True) if dt else None

            items: List[str] = []
            if dd:
                for li in dd.select("li"):
                    text = li.get_text(" ", strip=True)
                    if text:
                        items.append(text)

            if section_title or items:
                benefit_sections.append(
                    {
                        "title": section_title,
                        "items": items,
                    }
                )

    return {
        "detail_title": detail_title,
        "detail_desc": detail_desc,
        "benefit_sections": benefit_sections,
    }


async def fetch_cjone_partners(cat_cd: int = 2) -> List[Dict[str, Any]]:
    """
    외부에서 import 해서 사용하는 메인 함수.

    1) getBrandList.do 로 cat_cd 리스트를 가져오고
    2) 각 항목마다 상세 페이지(detail.do)를 호출해서 HTML을 가져온 뒤
    3) 상세 정보(detail_html 파싱 결과)만 리스트로 반환한다.
    """
    # 1단계: 리스트 JSON 가져오기
    raw_json = await _fetch_numbers(cat_cd=cat_cd)
    base_list = _parse_brand_list(raw_json, cat_cd=cat_cd)

    if not base_list:
        # brandList 자체가 비었으면 그냥 빈 리스트 반환
        return []

    # 2단계: 각 브랜드에 대해 상세 페이지 병렬 요청
    async with httpx.AsyncClient() as client:
        tasks = []
        for base in base_list:
            coopco_cd = base["coopco_cd"]
            brnd_cd = base["brnd_cd"]
            mcht_no = base["mcht_no"]

            tasks.append(
                _fetch_detail_html(
                    client,
                    coopco_cd=coopco_cd,
                    brnd_cd=brnd_cd,
                    mcht_no=mcht_no,
                    cat_cd=cat_cd,
                )
            )

        detail_html_list = await asyncio.gather(*tasks)

    # 3단계: detail HTML → detail JSON 으로만 변환해서 반환
    result: List[Dict[str, Any]] = []
    for html in detail_html_list:
        detail_info = _parse_detail_html(html)
        result.append(detail_info)

    return result


async def main():
    data = await fetch_cjone_partners()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
