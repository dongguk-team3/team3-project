"""
리뷰 크롤러 (선택적 사용)

⚠️ 경고:
- 웹 크롤링은 해당 사이트의 이용약관을 위반할 수 있습니다.
- 법적 문제가 발생할 수 있으므로 개인 학습/연구 목적으로만 사용하세요.
- 실제 서비스에는 공식 API를 사용하거나 Mock 데이터를 사용하세요.

이 모듈은 교육 목적으로만 제공되며, 실제 사용을 권장하지 않습니다.
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import random
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReviewCrawler:
    """리뷰 크롤러 (교육 목적)"""
    
    def __init__(self, use_mock: bool = True, headless: bool = True):
        """
        Args:
            use_mock: True면 Mock 데이터 사용, False면 실제 크롤링 시도
        """
        self.use_mock = use_mock
        self.headless = headless
        
        if not use_mock:
            logger.warning("⚠️ 실제 크롤링 모드는 법적 문제가 있을 수 있습니다!")
            logger.warning("⚠️ 개인 학습/연구 목적으로만 사용하세요.")
    
    async def crawl_kakao_reviews(
        self, 
        place_url: str, 
        max_reviews: int = 5
    ) -> List[Dict[str, Any]]:
        """
        카카오맵 place_url에서 리뷰 크롤링
        
        ⚠️ 주의: 카카오맵은 공식 API로 리뷰를 제공하지 않으므로,
        이 기능은 사용하지 않는 것을 권장합니다.
        
        Args:
            place_url: 카카오맵 장소 URL
            max_reviews: 최대 크롤링할 리뷰 수
        
        Returns:
            리뷰 리스트
        """
        
        if self.use_mock:
            logger.info("Mock 모드: 크롤링 대신 Mock 데이터 반환")
            return await self._generate_mock_reviews(max_reviews)
        
        # 실제 크롤링은 구현하지 않음 (법적 문제)
        logger.error("❌ 실제 크롤링은 지원하지 않습니다.")
        logger.info("💡 대신 Mock 데이터를 사용하세요.")
        return []
    
    async def crawl_naver_reviews(
        self,
        place_name: str,
        place_address: str,
        max_reviews: int = 5,
        place_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        네이버 플레이스에서 리뷰 크롤링
        
        ⚠️ 주의: 네이버 이용약관을 위반할 수 있습니다.
        공식 API 사용을 권장합니다.
        
        Args:
            place_name: 장소 이름
            place_address: 장소 주소
            max_reviews: 최대 크롤링할 리뷰 수
        
        Returns:
            리뷰 리스트
        """
        
        if self.use_mock:
            logger.info("Mock 모드: 크롤링 대신 Mock 데이터 반환")
            return await self._generate_mock_reviews(max_reviews)
        
        if not place_id:
            logger.warning("⚠️ 네이버 place_id가 없어 리뷰를 가져올 수 없습니다.")
            return []
        
        try:
            fetcher = NaverReviewFetcher(headless=self.headless)
            reviews = await fetcher.fetch_reviews_async(place_id, max_reviews)
            if reviews:
                logger.info(f"✅ 네이버 리뷰 {len(reviews)}개 수집 완료 (place_id={place_id})")
            else:
                logger.warning(f"⚠️ 네이버 리뷰가 없습니다. place_id={place_id}")
            return reviews
        except Exception as exc:
            logger.error(f"❌ 네이버 리뷰 수집 실패: {exc}")
        return []
    
    async def _generate_mock_reviews(self, count: int) -> List[Dict[str, Any]]:
        """
        Mock 리뷰 생성 (개발/테스트용)
        
        Args:
            count: 생성할 리뷰 수
        
        Returns:
            리뷰 리스트
        """
        from review_generator import ReviewGenerator
        
        generator = ReviewGenerator()
        
        # 임시 가게 정보
        mock_store = {
            "id": "temp",
            "name": "테스트 매장",
            "category": "음식점",
            "rating": 4.0
        }
        
        reviews = generator.generate_reviews(mock_store, count=count)
        
        logger.info(f"✅ Mock 리뷰 {count}개 생성 완료")
        
        return reviews
    
    async def get_place_reviews(
        self,
        store_info: Dict[str, Any],
        max_reviews: int = 5,
        source: str = "kakao"
    ) -> List[Dict[str, Any]]:
        """
        통합 리뷰 수집 인터페이스
        
        Args:
            store_info: 매장 정보
            max_reviews: 최대 리뷰 수
            source: 리뷰 소스 ("kakao", "naver", "mock")
        
        Returns:
            리뷰 리스트
        """
        
        if source == "mock" or self.use_mock:
            return await self._generate_mock_reviews(max_reviews)
        
        elif source == "kakao":
            place_url = store_info.get("place_url", "")
            if place_url:
                return await self.crawl_kakao_reviews(place_url, max_reviews)
            else:
                logger.warning("⚠️ place_url이 없어서 Mock 데이터 반환")
                return await self._generate_mock_reviews(max_reviews)
        
        elif source == "naver":
            place_name = store_info.get("name", "")
            place_address = store_info.get("address", "")
            place_id = store_info.get("naver_place_id")
            return await self.crawl_naver_reviews(
                place_name, 
                place_address, 
                max_reviews,
                place_id=place_id,
            )
        
        else:
            logger.error(f"❌ 알 수 없는 소스: {source}")
            return []


class NaverPlaceAPIClient:
    """
    네이버 플레이스 검색 API 클라이언트 (공식 API 사용)
    
    이것이 권장되는 방법입니다!
    """
    
    def __init__(self, client_id: str, client_secret: str):
        """
        Args:
            client_id: 네이버 API 클라이언트 ID
            client_secret: 네이버 API 클라이언트 시크릿
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_url = "https://openapi.naver.com/v1/search/local.json"
    
    async def search_place(
        self, 
        query: str, 
        display: int = 5,
        lat: Optional[float] = None,
        lng: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        네이버 지역 검색 API로 장소 검색 (좌표 활용 가능)
        
        Args:
            query: 검색 쿼리
            display: 검색 결과 개수 (최대 5)
            lat: 위도 (선택사항, 좌표 기반 검색 시 사용)
            lng: 경도 (선택사항, 좌표 기반 검색 시 사용)
        
        Returns:
            검색 결과 리스트
        """
        
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret
        }
        
        params = {
            "query": query,
            "display": min(display, 5)
        }
        
        # 좌표가 제공되면 검색 범위 지정 (네이버 API는 좌표 기반 검색 지원)
        if lat is not None and lng is not None:
            # 네이버 지역 검색 API는 좌표를 직접 파라미터로 받지 않지만,
            # 검색 쿼리에 지역 정보가 포함되어 있으면 해당 지역 중심으로 검색됨
            # 좌표 정보는 로깅용으로만 사용
            logger.info(f"📍 좌표 기반 검색: ({lat}, {lng})")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    headers=headers,
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("items", [])
                        logger.info(f"✅ 네이버 검색 성공: '{query}' -> {len(items)}개 결과")
                        return items
                    else:
                        text = await response.text()
                        logger.error(f"❌ API 호출 실패 ({response.status}): {text}")
                        return []
        
        except Exception as e:
            logger.error(f"❌ 오류 발생: {e}")
            return []


class NaverReviewFetcher:
    """Playwright를 이용해 네이버 플레이스 리뷰를 수집"""

    PC_URL = "https://pcmap.place.naver.com/restaurant/{place_id}/review/visitor"
    M_URL = "https://m.place.naver.com/restaurant/{place_id}/review/visitor?reviewSort=recent"

    INPAGE_FETCH = r"""
    async ({ placeId, size }) => {
      const tries = 4;
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      async function callOnce(businessType) {
        const payload = {
          operationName: "getVisitorReviews",
          query: `
            query getVisitorReviews($input: VisitorReviewsInput) {
              visitorReviews(input: $input) {
                total
                items {
                  id
                  body
                  translatedText
                  created
                  votedKeywords {
                    displayName
                  }
                }
              }
            }`,
          variables: {
            input: {
              businessId: String(placeId),
              businessType,
              includeContent: true,
              includeReceiptPhotos: true,
              page: 1,
              size: size,
              sort: "recent",
              cidList: ["220036","220037","220053"]
            }
          }
        };

        const res = await fetch("https://pcmap-api.place.naver.com/place/graphql", {
          method: "POST",
          headers: { "content-type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload)
        });

        if (res.status === 429) {
          const ra = res.headers.get("retry-after");
          const waitMs = ra ? Math.min(15000, Math.max(1500, Number(ra) * 1000)) : 2000;
          return { status: 429, waitMs };
        }

        if (!res.ok) {
          return { status: res.status, err: await res.text() };
        }

        const data = await res.json();
        if (data && data.data && data.data.visitorReviews) {
          const items = data.data.visitorReviews.items || [];
          const rows = items.map(it => ({
            review_text: (it.body || it.translatedText || "").trim(),
            tag: (it.votedKeywords || []).map(k => k.displayName).filter(Boolean)
          })).filter(r => r.review_text);
          return { status: 200, rows };
        }
        return { status: 200, rows: [] };
      }

      for (let attempt = 1; attempt <= tries; attempt++) {
        for (const bt of ["restaurant", "place"]) {
          const r = await callOnce(bt);
          if (r.status === 200 && r.rows && r.rows.length > 0) {
            return r.rows.slice(0, size);
          }
          if (r.status === 429) {
            await sleep(r.waitMs || attempt * 1000);
          }
        }
        await sleep(attempt * 1000);
      }
      return [];
    }
    """

    def __init__(self, headless: bool = True):
        self.headless = headless

    def _fetch_reviews(self, place_id: str, size: int) -> List[Dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("❌ Playwright가 설치되어 있지 않습니다. 'pip install playwright' 실행 후 'playwright install'을 수행하세요.")
            return []

        rows: List[Dict[str, Any]] = []
        urls = [self.PC_URL.format(place_id=place_id), self.M_URL.format(place_id=place_id)]

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            context = browser.new_context(
                locale="ko-KR",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1300, "height": 1000},
            )
            page = context.new_page()
            try:
                for url in urls:
                    page.goto(url, wait_until="domcontentloaded")
                    for _ in range(2):
                        page.mouse.wheel(0, 1200)
                        page.wait_for_timeout(250)
                    rows = page.evaluate(self.INPAGE_FETCH, dict(placeId=place_id, size=max(1, size)))
                    if rows:
                        break
            finally:
                context.close()
                browser.close()

        return rows

    async def fetch_reviews_async(self, place_id: str, size: int = 3) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_reviews, place_id, size)


# 사용 예시
async def example_usage():
    """사용 예시"""
    
    print("=" * 80)
    print("리뷰 크롤러 사용 예시")
    print("=" * 80)
    
    # Mock 모드 (권장)
    print("\n1. Mock 모드 (권장)")
    crawler = ReviewCrawler(use_mock=True)
    
    mock_store = {
        "id": "12345",
        "name": "테스트 식당",
        "category": "음식점 > 한식",
        "place_url": "https://place.map.kakao.com/12345",
        "address": "서울특별시 강남구...",
        "rating": 4.2
    }
    
    reviews = await crawler.get_place_reviews(
        store_info=mock_store,
        max_reviews=5,
        source="mock"
    )
    
    print(f"수집된 리뷰: {len(reviews)}개")
    for idx, review in enumerate(reviews, 1):
        print(f"\n[{idx}] {review['author']} (⭐{review['rating']})")
        print(f"    {review['content']}")
    
    # 네이버 공식 API 사용 (권장)
    print("\n\n2. 네이버 공식 API 사용 (권장)")
    print("⚠️ 네이버 개발자 센터에서 API 키를 발급받으세요:")
    print("   https://developers.naver.com/")
    
    # API 키가 있다면:
    # naver_client = NaverPlaceAPIClient(
    #     client_id="your_client_id",
    #     client_secret="your_client_secret"
    # )
    # results = await naver_client.search_place("강남역 맛집", display=5)
    # print(f"검색 결과: {len(results)}개")


if __name__ == "__main__":
    asyncio.run(example_usage())



