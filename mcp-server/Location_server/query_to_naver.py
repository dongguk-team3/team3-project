import asyncio
import importlib.util
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

# location_server_config.py 파일이 같은 폴더에 있어야 합니다.
from location_server_config import (
    NAVER_SEARCH_CLIENT_ID,
    NAVER_SEARCH_CLIENT_SECRET,
    NAVER_APP_CLIENT_ID,
    NAVER_APP_CLIENT_SECRET,
    NAVER_GEOCODE_URL,
)

# review_crawler.py 파일이 같은 폴더에 있어야 합니다.
from review_crawler import ReviewCrawler, NaverPlaceAPIClient

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s: %(message)s',
    stream=sys.stderr,
    force=True
)
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
    # 현재 파일 위치에서 부모 폴더를 찾기 위한 기준 경로 설정
    project_root = Path(__file__).resolve().parents[2]
    
    # test_real_user_queries.py 파일 경로 설정
    test_module_path = project_root / ".vscode" / "android_discount_app" / "test_real_user_queries.py"
    
    # test_real_user_queries.py 파일이 있으면 사용
    if test_module_path.exists():
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
    
    # 파일이 없으면 query_results.json에서 쿼리를 읽고 chat_filter_pipeline에서 extractor 가져오기
    logger.info("test_real_user_queries.py를 찾을 수 없어 query_results.json을 사용합니다.")
    
    # query_results.json에서 쿼리 추출 (query_to_naver.py와 같은 폴더에 있다고 가정)
    results_path = Path(__file__).with_name("query_results.json")
    if not results_path.exists():
        raise FileNotFoundError(f"query_results.json 파일을 찾을 수 없습니다: {results_path}")
    
    with open(results_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    
    # query_results.json의 각 항목에서 original_query 추출
    queries = [result.get("intent", {}).get("original_query") for result in results if result.get("intent", {}).get("original_query")]
    if not queries:
        raise RuntimeError("query_results.json에서 쿼리를 찾을 수 없습니다.")
    
    # chat_filter_pipeline.py에서 extractor 가져오기
    # 프로젝트 구조를 가정하여, 'Location_server'의 부모 폴더(project_root.parents[1])의 형제 폴더인 'mcp-client'에 있다고 추정
    pipeline_path = project_root.parents[1] / "mcp-client" / "chat_filter_pipeline.py"
    if not pipeline_path.exists():
        # 만약 경로가 달랐다면, 현재 파일의 부모의 부모 폴더로 다시 시도
        pipeline_path = project_root / "mcp-client" / "chat_filter_pipeline.py"
        if not pipeline_path.exists():
            raise FileNotFoundError(f"chat_filter_pipeline.py 파일을 찾을 수 없습니다: {pipeline_path}")
    
    logger.info(f"✅ chat_filter_pipeline.py 로드 경로: {pipeline_path}")
    
    spec = importlib.util.spec_from_file_location("chat_filter_pipeline", pipeline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("chat_filter_pipeline.py 모듈을 로드할 수 없습니다.")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    
    extractor = getattr(module, "_extract_keywords_fallback", None)
    if not extractor:
        raise RuntimeError("chat_filter_pipeline.py에서 _extract_keywords_fallback 함수를 찾을 수 없습니다.")
    
    logger.info(f"✅ query_results.json에서 {len(queries)}개의 쿼리를 로드했습니다.")
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
    '''
    "네이버 지역 검색 API로 장소 검색"
    '''
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
                logger.info(f"{store['name']}: 실제 리뷰 {len(reviews)}개 수집 완료")
        
        store["reviews"] = reviews  # 리뷰가 없어도 빈 리스트로 저장
        stores.append(store)
    
    # nearby_reviews.py 형식으로 변환
    stores_list = []
    reviews_dict = {}
    
    for store in stores:
        store_name = store.get("name", "")
        if store_name:
            stores_list.append(store_name)
            # 리뷰 텍스트만 추출
            review_texts = [
                review.get("review_text", review.get("content", review.get("text", ""))).strip()
                for review in store.get("reviews", [])
                if review.get("review_text", review.get("content", review.get("text", ""))).strip()
            ]
            if review_texts:
                reviews_dict[store_name] = review_texts
    
    result: Dict[str, Any] = {
        "intent": {
            "original_query": intent.original_query,
            "place_type": intent.place_type,
            "attributes": intent.attributes,
            "location": intent.location,
            "search_keyword": search_keyword,
        },
        "total_count": len(stores_list),
        "stores": stores_list,
        "reviews": reviews_dict,
    }
    
    # 지오코딩 결과가 있으면 center 값 추가
    if center:
        result["center"] = {"latitude": center[0], "longitude": center[1]}
    else:
        result["center"] = None
    
    return result


async def _try_geocode(session: aiohttp.ClientSession, location: str) -> Optional[Tuple[float, float]]:
    """단일 위치 문자열로 지오코딩 API를 통한 지오코딩 시도"""
    if not (NAVER_APP_CLIENT_ID and NAVER_APP_CLIENT_SECRET):
        return None
    
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_APP_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_APP_CLIENT_SECRET,
    }
    params = {"query": location}
    
    try:
        async with session.get(NAVER_GEOCODE_URL, headers=headers, params=params) as response:
            if response.status != 200:
                return None
            data = await response.json()
    except Exception:
        return None
    
    addresses = data.get("addresses") or []
    if not addresses:
        return None
    
    first = addresses[0]
    try:
        latitude = float(first.get("y"))
        longitude = float(first.get("x"))
        return latitude, longitude
    except (TypeError, ValueError):
        return None


async def _geocode_via_search_api(
    session: aiohttp.ClientSession,
    naver_client: NaverPlaceAPIClient,
    location: str
) -> Optional[Tuple[float, float]]:
    """네이버 지역 검색 API를 사용하여 위치를 검색하고 위도/경도를 추출"""
    try:
        # 네이버 지역 검색 API로 위치 검색
        documents = await naver_client.search_place(
            location,
            display=5,  # 여러 결과 중 최적의 것을 선택
        )
        
        if not documents:
            return None
        
        # 검색 결과에서 주소 추출 후 지오코딩 시도
        for result in documents:
            # roadAddress 또는 address 추출
            address = result.get("roadAddress") or result.get("address")
            if address:
                # 주소로 지오코딩 API 호출
                coords = await _try_geocode(session, address)
                if coords:
                    logger.debug(f"검색 API 결과로 지오코딩 성공: {location} -> {address} -> {coords}")
                    return coords
        
        return None
    except Exception as e:
        logger.debug(f"검색 API를 통한 지오코딩 실패: {location}, {e}")
        return None


async def geocode_location(
    session: aiohttp.ClientSession,
    location: str,
    naver_client: Optional[NaverPlaceAPIClient] = None
) -> Optional[Tuple[float, float]]:
    """위치 문자열을 네이버 지도 지오코딩 API 또는 검색 API로 위·경도 좌표로 변환
    
    1. 먼저 지오코딩 API로 원본 위치명 직접 시도
    2. 실패 시 네이버 지역 검색 API로 위치를 검색하여 주소 추출 후 지오코딩
    """
    if not location or not location.strip():
        logger.warning("위치 문자열이 비어있습니다.")
        return None
    
    # '이 근처'와 같은 상대 주소는 지오코딩 API가 처리할 수 없으므로 건너뜁니다.
    if location.strip() in ["이 근처", "여기", "근처"]:
        logger.warning(f"상대적인 위치 문자열은 지오코딩을 건너뜁니다: {location}")
        return None
    
    location = location.strip()

    # 1단계: 지오코딩 API로 원본 위치명 직접 시도
    if NAVER_APP_CLIENT_ID and NAVER_APP_CLIENT_SECRET:
        result = await _try_geocode(session, location)
        if result:
            logger.info(f"지오코딩 성공: {location} -> {result}")
            return result
    
    # 2단계: 지오코딩 API 실패 시 네이버 지역 검색 API로 시도
    if naver_client:
        result = await _geocode_via_search_api(session, naver_client, location)
        if result:
            logger.info(f"지오코딩 성공 (검색 API 사용): {location} -> {result}")
            return result
    
        logger.warning(f"지오코딩 결과가 없습니다. location={location}")
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
                center = await geocode_location(session, intent.location, naver_client=naver_client)
            
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
    print("🚀 query_to_naver.py 실행 시작", flush=True)
    logger.info("🚀 query_to_naver.py 실행 시작")
    
    try:
        results = asyncio.run(process_queries())
        output_path = Path(__file__).with_name("query_results.json")
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ 결과를 {output_path} 파일로 저장했습니다.", flush=True)
        logger.info(f"✅ 결과를 {output_path} 파일로 저장했습니다.")
    except Exception as e:
        print(f"❌ 오류 발생: {e}", flush=True, file=sys.stderr)
        logger.exception("❌ 오류 발생")
        raise


if __name__ == "__main__":
    main()
