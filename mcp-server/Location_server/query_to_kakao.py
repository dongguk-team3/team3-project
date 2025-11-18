"""LLM으로 추출한 장소/형용사 정보를 카카오맵 로컬 검색과 연결하는 스크립트."""

import asyncio
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

import aiohttp

from location_server_config import (
    KAKAO_REST_API_KEY,
    KAKAO_LOCAL_SEARCH_URL,
    KAKAO_ADDRESS_SEARCH_URL,
    NAVER_SEARCH_CLIENT_ID,
    NAVER_SEARCH_CLIENT_SECRET,
)
from review_crawler import ReviewCrawler, NaverPlaceAPIClient

DEFAULT_COORDS: Tuple[float, float] = (37.5665, 126.9780)
DEFAULT_RADIUS = 1500
MAX_RESULTS = 15
REVIEWS_PER_STORE = 3


@dataclass
class QueryIntent:
    original_query: str
    place_type: str
    attributes: List[str]
    location: Optional[str]


PLACE_TYPE_MAPPING: Dict[str, Dict[str, Optional[str]]] = {
    "카페": {"category_code": "CE7", "keyword": "카페"},
    "카페/디저트": {"category_code": "CE7", "keyword": "디저트 카페"},
    "맛집": {"category_code": "FD6", "keyword": "맛집"},
    "한식": {"category_code": "FD6", "keyword": "한식"},
    "피자/양식": {"category_code": "FD6", "keyword": "양식"},
    "찜/탕": {"category_code": "FD6", "keyword": "찜"},
    "도시락/죽": {"category_code": "FD6", "keyword": "도시락"},
    "일식/돈까스": {"category_code": "FD6", "keyword": "돈까스"},
    "치킨": {"category_code": "FD6", "keyword": "치킨"},
    "회/초밥": {"category_code": "FD6", "keyword": "초밥"},
    "일식": {"category_code": "FD6", "keyword": "이자카야"},
    "분식": {"category_code": "FD6", "keyword": "분식"},
    "족발/보쌈": {"category_code": "FD6", "keyword": "족발"},
    "중식": {"category_code": "FD6", "keyword": "중식"},
    "고기/구이": {"category_code": "FD6", "keyword": "고기 구이"},
    "샐러드": {"category_code": "FD6", "keyword": "샐러드"},
    "패스트푸드": {"category_code": "FD6", "keyword": "버거"},
    "아시안": {"category_code": "FD6", "keyword": "아시안"},
    "술집": {"category_code": "FD6", "keyword": "술집"},
}


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
    "가성비좋은": "가성비 좋은",
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


def attribute_keywords(attributes: List[str]) -> str:
    words = [ATTRIBUTE_KEYWORDS.get(attr, "") for attr in attributes]
    return " ".join(word for word in words if word)


def map_place_type(place_type: str) -> Tuple[str, str]:
    mapping = PLACE_TYPE_MAPPING.get(place_type)
    if mapping:
        return mapping["category_code"] or "FD6", mapping["keyword"] or place_type
    return "FD6", place_type


async def geocode(session: aiohttp.ClientSession, location: str) -> Tuple[float, float]:
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}

    # 1차: 키워드 검색으로 장소 좌표 추정
    place_params = {"query": location, "size": 1}
    async with session.get(
        KAKAO_LOCAL_SEARCH_URL,
        headers=headers,
        params=place_params,
    ) as response:
        if response.status == 200:
            data = await response.json()
            documents = data.get("documents", [])
            if documents:
                doc = documents[0]
                return float(doc["y"]), float(doc["x"])

    # 2차: 주소 검색으로 좌표 조회
    address_params = {"query": location}
    async with session.get(
        KAKAO_ADDRESS_SEARCH_URL,
        headers=headers,
        params=address_params,
    ) as response:
        if response.status == 200:
            data = await response.json()
            documents = data.get("documents", [])
            if documents:
                doc = documents[0]
                return float(doc["y"]), float(doc["x"])

    return DEFAULT_COORDS


async def search_places(
    session: aiohttp.ClientSession,
    intent: QueryIntent,
    radius: int = DEFAULT_RADIUS,
) -> Dict[str, Any]:
    category_code, keyword_base = map_place_type(intent.place_type)
    attr_kw = attribute_keywords(intent.attributes)
    keyword = " ".join(filter(None, [attr_kw, keyword_base])) or keyword_base

    latitude, longitude = DEFAULT_COORDS
    if intent.location:
        latitude, longitude = await geocode(session, intent.location)

    async def request_places(query: str) -> List[Dict[str, Any]]:
        params = {
            "query": query,
            "category_group_code": category_code,
            "size": MAX_RESULTS,
            "radius": radius,
            "x": longitude,
            "y": latitude,
            "sort": "distance",
        }
        async with session.get(
            KAKAO_LOCAL_SEARCH_URL,
            headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
            params=params,
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(f"카카오 검색 실패({response.status}): {text}")
            data = await response.json()
            return data.get("documents", [])

    # 우선순위대로 검색: (속성+카테고리) → (카테고리만) → (지역+카테고리)
    used_keyword = keyword
    documents = await request_places(keyword)
    if not documents:
        used_keyword = keyword_base
        documents = await request_places(keyword_base)
    if not documents and intent.location:
        used_keyword = f"{intent.location} {keyword_base}"
        documents = await request_places(used_keyword)

    naver_available = bool(NAVER_SEARCH_CLIENT_ID and NAVER_SEARCH_CLIENT_SECRET)
    naver_client: Optional[NaverPlaceAPIClient] = None
    if naver_available:
        naver_client = NaverPlaceAPIClient(
            client_id=NAVER_SEARCH_CLIENT_ID,
            client_secret=NAVER_SEARCH_CLIENT_SECRET,
        )

    crawler_real = ReviewCrawler(use_mock=not naver_available)
    crawler_mock = ReviewCrawler(use_mock=True)
    stores: List[Dict[str, Any]] = []
    for doc in documents:
        store = {
            "id": doc.get("id"),
            "name": doc.get("place_name"),
            "category": doc.get("category_name"),
            "distance": int(doc.get("distance", 0)),
            "address": doc.get("address_name"),
            "road_address": doc.get("road_address_name"),
            "phone": doc.get("phone"),
            "place_url": doc.get("place_url"),
            "latitude": float(doc.get("y")),
            "longitude": float(doc.get("x")),
        }

        reviews: List[Dict[str, Any]] = []

        if naver_available and naver_client and not crawler_real.use_mock:
            naver_place_id = await find_naver_place_id(
                naver_client,
                store_name=store["name"],
                road_address=store.get("road_address"),
                address=store.get("address"),
            )
            if naver_place_id:
                store["naver_place_id"] = naver_place_id
                reviews = await crawler_real.get_place_reviews(
                    store_info=store,
                    max_reviews=REVIEWS_PER_STORE,
                    source="naver",
                )

        if not reviews:
            reviews = await crawler_mock.get_place_reviews(
                store_info=store,
                max_reviews=REVIEWS_PER_STORE,
                source="mock",
            )

        store["reviews"] = reviews
        stores.append(store)

    return {
        "intent": {
            "original_query": intent.original_query,
            "place_type": intent.place_type,
            "attributes": intent.attributes,
            "location": intent.location,
            "search_keyword": used_keyword,
            "category_code": category_code,
        },
        "center": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "total_count": len(stores),
        "stores": stores,
    }


async def find_naver_place_id(
    naver_client: NaverPlaceAPIClient,
    store_name: str,
    road_address: Optional[str],
    address: Optional[str],
) -> Optional[str]:
    """네이버 지역 검색 API를 이용해 place_id 추출"""
    search_query = store_name
    if road_address:
        search_query += f" {road_address}"
    elif address:
        search_query += f" {address}"

    results = await naver_client.search_place(search_query, display=5)
    for item in results:
        link = item.get("link", "")
        match = re.search(r"/place/(\d+)", link)
        if match:
            return match.group(1)
        match = re.search(r"placeId=(\d+)", link)
        if match:
            return match.group(1)
    return None


async def process_queries() -> List[Dict[str, Any]]:
    if not KAKAO_REST_API_KEY:
        raise RuntimeError("KAKAO_REST_API_KEY가 설정되어 있지 않습니다.")

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

    results: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession() as session:
        for intent in intents:
            try:
                result = await search_places(session, intent)
                results.append(result)
            except Exception as exc:
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

