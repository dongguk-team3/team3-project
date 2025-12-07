# lguplus_membership.py

import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

BASE_URL = "https://www.lguplus.com"
DETAIL_API_URL = f"{BASE_URL}/uhdc/fo/prdv/mebfjnco/v1/jnco/{{jnco_id}}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/benefit-membership",
    "X-Menu-Url": "/benefit-membership",
    "X-User-Agent-Type": "PC",
}


def normalize_html_text(text: Optional[str]) -> str:
    """<br> 같은 태그를 줄바꿈으로 치환하고 양쪽 공백을 정리한다."""
    if not text:
        return ""
    return (
        text.replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("&nbsp;", " ")
        .strip()
    )


async def fetch_vip_page_html(client: httpx.AsyncClient) -> str:
    """VIP 콕 섹션이 포함된 멤버십 페이지 HTML을 가져온다."""
    url = f"{BASE_URL}/benefit-membership"
    resp = await client.get(url, headers=HEADERS, timeout=10.0)
    resp.raise_for_status()
    return resp.text


def parse_vip_summary(html: str) -> Dict[str, Any]:
    """
    VIP 콕 상단 요약 영역 파싱.
    - 제목 (h3.h3-type)
    - 대상 (div.grade > p.tit / p.txt)
    - 이용 안내 bullets
    - QR 안내 텍스트
    """
    soup = BeautifulSoup(html, "lxml")

    # 제목
    title_el = soup.find("h3", class_="h3-type")
    vip_title = title_el.get_text(strip=True) if title_el else None

    # 대상
    target_box = soup.select_one("div.benefit-info div.grade")
    target = None
    if target_box:
        txt = target_box.find("p", class_="txt")
        target = txt.get_text(strip=True) if txt else None

    # 이용 안내 + QR
    usage_box = soup.select_one("div.benefit-info div.info ul.c-bullet-type-circle")
    usage_lines: List[str] = []
    qr_lines: List[str] = []

    if usage_box:
        for li in usage_box.find_all("li"):
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            # class="no_dot" 인 항목들은 QR 관련 안내이므로 분리
            if "no_dot" in (li.get("class") or []):
                qr_lines.append(text)
            else:
                usage_lines.append(text)

    return {
        "vipTitle": vip_title,
        "target": target,
        "usageGuide": "\n".join(usage_lines) if usage_lines else None,
        "qrInfo": "\n".join(qr_lines) if qr_lines else None,
    }


async def fetch_affiliate_detail(
    client: httpx.AsyncClient,
    jnco_id: str,
) -> Dict[str, Any]:
    """
    /uhdc/fo/prdv/mebfjnco/v1/jnco/{jnco_id} 상세 JSON을 가져와서
    우리가 ETL에 쓸만한 필드만 깔끔하게 정리한다.
    """
    url = DETAIL_API_URL.format(jnco_id=jnco_id)
    resp = await client.get(url, headers=HEADERS, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()

    brand_name = data.get("urcMbspJncoNm", "")
    category_name = data.get("urcMbspCatgNm", "")  # 예: VIP콕
    benefit_summary = normalize_html_text(data.get("jncoBnftThumCntn"))
    benefit_detail = normalize_html_text(data.get("jncoBnftDetlCntn"))
    intro = normalize_html_text(data.get("jncoItduCntn"))
    extra_intro = normalize_html_text(data.get("jncoDetlItduCntn"))
    restrictions = normalize_html_text(data.get("rstnMttrCntn"))
    usage_guide = normalize_html_text(data.get("urcBnftTadvMthdCntn"))
    homepage = (data.get("jncoHmpgUrl") or "").strip()
    shop_url = (data.get("jncoShopUrl") or "").strip()
    grade = (data.get("jncoTadvGrdDetlDscr") or "").strip()
    tel = (data.get("repTlno") or "").strip()
    point_desc = normalize_html_text(data.get("dducPntDscr"))

    img_path = data.get("pcImgeUrl") or ""
    if img_path.startswith("/"):
        image_url = BASE_URL + img_path
    else:
        image_url = img_path

    return {
        "brandName": brand_name,
        "categoryName": category_name,     # "VIP콕" 등
        "benefitSummary": benefit_summary, # 한 줄 요약
        "benefitDetail": benefit_detail,   # VIP콕 내 통합 월 1회 등
        "intro": intro,                    # 브랜드 한 줄 소개
        "usageGuide": usage_guide,         # 이용 방법 + 꼭 확인하세요
        "homepage": homepage,
        "grade": grade,                    # VVIP/VIP
    }


async def fetch_lguplus_membership_for_targets() -> Dict[str, Any]:
    """
    LG U+ 멤버십에서
    - VIP 콕 요약 (한 번)
    - 스타벅스 / 할리스 / 쉐이크쉑 상세 (각각 jncoId 지정)
    를 묶어 JSON으로 반환.
    """
    TARGET_BRANDS: Dict[str, str] = {
        "스타벅스": "711169",
        "할리스": "375",
        "쉐이크쉑": "711116",
    }

    async with httpx.AsyncClient() as client:
        # 1) VIP 콕 상단 요약
        html = await fetch_vip_page_html(client)
        vip_summary = parse_vip_summary(html)

        # 2) 각 제휴사 상세 API 호출
        details: Dict[str, Any] = {}
        for brand_name, jnco_id in TARGET_BRANDS.items():
            detail = await fetch_affiliate_detail(client, jnco_id)
            details[brand_name] = detail

    return {
        "vipSummary": vip_summary,
        "brands": details,
    }


# 모듈 테스트용 진입점
if __name__ == "__main__":
    import asyncio
    import json

    async def _test():
        result = await fetch_lguplus_membership_for_targets()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        with open("lguplus_brands.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    asyncio.run(_test())
