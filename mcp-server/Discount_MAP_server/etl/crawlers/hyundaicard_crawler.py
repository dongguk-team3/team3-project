# hyundaicard_crawler.py
import json
from curl_cffi import requests


BASE_URL = "https://www.hyundaicard.com"


def _normalize(item: dict) -> dict:
    img_base = item.get("imgFilePathCn") or ""
    if img_base and not img_base.startswith("http"):
        img_base = BASE_URL + img_base

    def join_img(base, name):
        if not name:
            return None
        return f"{base}/{name}"

    return {
        "name": item.get("cntnTitl"),
        "subtitle": item.get("cntnSubTitl"),
        "keywords": (item.get("srchKwrdCn") or "").split(","),
        "category_name": item.get("cntnCtgrClvlNm"),
        "period": {
            "start": item.get("bltnSrtDt"),
            "end": item.get("bltnEndDt"),
        },
    }


def fetch_hyundaicard_mpoints() -> dict:
    url = "https://www.hyundaicard.com/cpp/eu/apiCPPEU0101_02.hc"

    payload = {
        "beginRows": "0",
        "endRows": "0",
        "totalRows": "0",
        "mappCodeList": ""
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.hyundaicard.com",
        "Referer": "https://www.hyundaicard.com/cpp/eu/CPPEU0101_01.hc",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
    }

    # 여기서 Curl 기반 요청 → SSL 100% 우회 가능
    resp = requests.post(
        url,
        data=payload,
        headers=headers,
        impersonate="chrome",   # 크롬 브라우저 TLS 완전 모방
        timeout=10
    )
    raw = resp.json()

    items = raw.get("bdy", {}).get("resultMap", {}).get("cppeu0101_02voList", []) or []

    coffee_bakery = []
    dining = []

    for item in items:
        cate = item.get("cntnCtgrClvl")
        if cate == "01":
            coffee_bakery.append(_normalize(item))
        elif cate == "02":
            dining.append(_normalize(item))

    return {
        "coffee_bakery": coffee_bakery,
        "dining": dining,
    }

if __name__ == "__main__":
    data = fetch_hyundaicard_mpoints()

    with open("hyundaicard_mpoints.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✔ 저장 완료 → hyundaicard_mpoints.json")