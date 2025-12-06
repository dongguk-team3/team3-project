"""
Location Module - 위치 기반 데이터 처리 모듈
nearby_reviews.py와 연동하여 위치 기반 상점 및 리뷰 데이터를 처리합니다.
"""

import json
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List
import aiohttp

# Location Server (네이버 지오코딩) 통합 준비
LOCATION_SERVER_PATHS = [
    Path("/opt/conda/envs/team/OSS/mcp-server/Location_server"),
    Path(__file__).resolve().parent / "Location_server",
    Path(__file__).resolve().parent.parent / "Location_server",
]

for _path in LOCATION_SERVER_PATHS:
    if _path.exists() and str(_path) not in sys.path:
        sys.path.append(str(_path))

try:
    from location_server_config import (
        NAVER_SEARCH_CLIENT_ID,
        NAVER_SEARCH_CLIENT_SECRET,
    )
    from query_to_naver import (
        NaverPlaceAPIClient,
        geocode_location,
    )
    NAVER_GEO_AVAILABLE = True
except Exception as geo_exc:
    NAVER_GEO_AVAILABLE = False
    NaverPlaceAPIClient = None  # type: ignore
    geocode_location = None  # type: ignore
    NAVER_SEARCH_CLIENT_ID = None  # type: ignore
    NAVER_SEARCH_CLIENT_SECRET = None  # type: ignore
    print(f"⚠️  네이버 지오코딩 모듈 로드 실패: {geo_exc}")

# nearby_reviews.py 출력 형식과 동일한 기본 샘플 (파일이 없을 때 사용)
DEFAULT_NEARBY_SAMPLE = {
    "stores": [
        "장충동커피",
        "기브온 카페인바",
        "포우즈",
        "스트릿 그릭요거트 카페",
        "로이터 커피 셸터",
        "프릳츠 장충점",
        "커피드니로",
        "미드템포",
        "포미스커피",
        "하우스 커피 앤 디저트",
    ],
    "reviews": {
        "장충동커피": [
            "생각없이 방문했는데 커피 퀄리티가 너무 좋와서 놀랐네요 따듯한 아메리카노 샷 추가 추천합니다",
            "굿",
            "테이크전문 커피숍인데 가성비 좋네요",
        ],
        "기브온 카페인바": [
            "생레몬 구겔호프 상큼하니 맛있어요!\\n카페 오는 길 남산타워가 환상입니다...",
            "커피는 물론이고 디저트가 아주 훌륭합니다 특히 비스코티는 중독적이네요.. 또 먹으러 가겠습니다",
            "매장 입장과 동시에 고소한 커피 향이 솔솔~~\\n커피 향도 너무 좋고 진하고 요기 요기 충무로 필동 원탑 커피 맛집입니다👌🏻🩷",
        ],
        "포우즈": [
            "굿",
            "굿",
            "루프탑카페. 날씨좋을때 가면 좋음",
        ],
        "스트릿 그릭요거트 카페": [
            "그릭요거트 땡겨서 먹으러왔는데 다른 데에 비해 가성비가 좋아요 사장님도 친절하셔서 좋아요💫",
            "가게 너무 귀엽고 무화과 요거트 너무 맛있어요",
            "고즈넉한 분위기의 맛있는 요거트집이에요. 무화과볼 처돌이로써 이곳 무화과 진짜 신선하고요",
        ],
        "로이터 커피 셸터": [
            "필동로를 따라 걷다보면 3층의 넓은 카페입니다!! 뷰도 아늑하고 커피도 맛있어서 풀만족합니다",
            "카페보단,갤러리나 스튜디오 느낌의 공간",
            "좋아요",
        ],
        "프릳츠 장충점": [
            "아내와 연애 시절 추억이 있던 프릳츠.",
            "드디어 원두랑 드립 라인업 맞춰놨네…",
            "카페의 고즈넉한 분위기와 음악이 커피의 맛과 향에  더 취하게 하는 기억에 남을 곳입니다",
        ],
        "커피드니로": [
            "배우..아니 사장님 진짜로 커피에 진심이시군요...",
            "태인호 배우님의 팬으로 남양주에서 찾아갔는데 커피 맛집이네요.",
            "커피는드니로배우는태인호",
        ],
        "미드템포": [
            "분위기가 좋고 음료도 다 맛있어요!!",
            "학교 근처여서 들려봤는데 너무 좋고 라떼도 너무너무 맛있었어요!!",
            "분위기도 너무 좋고 동국대 제휴 할인도 됩니다!",
        ],
        "포미스커피": [
            "쿠키가 다양하고 너무 맛있어요~!! 묵직함",
            "👍🏻👍🏻👍🏻말차쿠키 단골",
            "충무로역에서 동국대 후문 인근 카페입니다.",
        ],
        "하우스 커피 앤 디저트": [
            "소금빵이랑 기본 휘낭시에 샀는데 휘낭시에에서 마늘빵맛 나요 ㅠㅠ",
            "한국적이고 어릴때 먹던 수정과 생각나는 맛이예요",
            "가을만끽하기 좋은 동국대 인근 숲속 위치~~",
        ],
    },
}


class LocationModule:
    """위치 기반 데이터 처리 모듈"""
    
    def __init__(self):
        """초기화"""
        self._nearby_reviews_data: Optional[Dict[str, Any]] = None
        self._nearby_reviews_source: Optional[str] = None
        self._nearby_reviews_script: Optional[Path] = self._locate_nearby_reviews_script()
        self._location_cache: Dict[str, Dict[str, Any]] = {}
        self._naver_client = None
        
        if NAVER_GEO_AVAILABLE and NAVER_SEARCH_CLIENT_ID and NAVER_SEARCH_CLIENT_SECRET:
            try:
                self._naver_client = NaverPlaceAPIClient(
                    client_id=NAVER_SEARCH_CLIENT_ID,
                    client_secret=NAVER_SEARCH_CLIENT_SECRET,
                )
            except Exception as exc:
                print(f"⚠️  네이버 클라이언트 초기화 실패: {exc}")
                self._naver_client = None
    
    def prepare_location_stage(
        self,
        *,
        latitude: float,
        longitude: float,
        place_type: str,
        attributes: List[str],
    ) -> Dict[str, Any]:
        """
        nearby_reviews.py가 생성하는 JSON 구조를 참고해
        stores / reviews 데이터를 구성한다.
        """
        dataset = self.build_location_dataset(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type,
            attributes=attributes,
        )
        stores = dataset.get("stores", [])
        reviews = dataset.get("reviews", {})
        distances = dataset.get("distances", {})
        locations = dataset.get("locations", {})

        if not stores:
            return {
                "success": False,
                "message": "LocationServer 데이터를 불러오지 못했습니다.",
                "stores": [],
                "reviews": {},
                "error": "LOCATION_DATA_NOT_FOUND",
                "meta": {
                    "source": self._nearby_reviews_source,
                    "place_type": place_type,
                    "attributes": attributes,
                    "coordinates": {"lat": latitude, "lon": longitude},
                },
            }

        stores = stores[:10]
        normalized_reviews = {
            store: reviews.get(store, [])[:5]
            for store in stores
        }

        return {
            "success": True,
            "message": "LocationServer 완료",
            "stores": stores,
            "reviews": normalized_reviews,
            "distances": distances,
            "locations": locations,
            "meta": {
                "source": dataset.get("meta", {}).get("source", self._nearby_reviews_source),
                "place_type": place_type,
                "attributes": attributes,
                "coordinates": {"lat": latitude, "lon": longitude},
            },
        }

    def load_nearby_reviews_dataset(self) -> Dict[str, Any]:
        """nearby_reviews.py 출력(JSON) 경로를 탐색하여 로드"""
        if self._nearby_reviews_data is not None:
            return self._nearby_reviews_data

        candidates: List[Path] = []
        base_dir = Path(__file__).resolve().parent
        candidates.append(base_dir / "nearby_reviews.json")
        candidates.append(base_dir / "data" / "nearby_reviews.json")
        candidates.append(base_dir / "location_test" / "nearbytest.json")
        candidates.append(base_dir.parent / "mcp-client" / "location_test" / "nearbytest.json")

        for candidate in candidates:
            if candidate.exists():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        self._nearby_reviews_data = json.load(f)
                        self._nearby_reviews_source = str(candidate)
                        return self._nearby_reviews_data
                except Exception as exc:
                    print(f"⚠️  nearby_reviews 데이터 로드 실패 ({candidate}): {exc}")

        self._nearby_reviews_data = DEFAULT_NEARBY_SAMPLE
        self._nearby_reviews_source = "embedded_default"
        return self._nearby_reviews_data

    def locate_nearby_reviews_script(self) -> Optional[Path]:
        """nearby_reviews.py 스크립트 경로 탐색"""
        base_dir = Path(__file__).resolve().parent
        candidates = [
            base_dir / "location_test" / "nearby_reviews.py",
            base_dir / "nearby_reviews.py",
            base_dir.parent / "location_test" / "nearby_reviews.py",
            Path("/opt/conda/envs/team/OSS/mcp-client/location_test/nearby_reviews.py"),
            Path("/opt/conda/envs/team/OSS/mcp-server/Location_server/nearby_reviews.py"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _locate_nearby_reviews_script(self) -> Optional[Path]:
        """내부 메서드: nearby_reviews.py 스크립트 경로 탐색"""
        return self.locate_nearby_reviews_script()

    def build_location_dataset(
        self,
        *,
        latitude: float,
        longitude: float,
        place_type: str,
        attributes: List[str],
    ) -> Dict[str, Any]:
        """위치 기반 데이터셋 구축"""
        cache_key = f"{round(latitude,4)}:{round(longitude,4)}:{place_type}"
        if cache_key in self._location_cache:
            return self._location_cache[cache_key]

        dataset = self.run_nearby_reviews_script(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type,
        )

        if dataset is None:
            fallback = self.load_nearby_reviews_dataset()
            dataset = {
                "stores": fallback.get("stores", []),
                "reviews": fallback.get("reviews", {}),
                "meta": {
                    "source": fallback.get("meta", {}).get("source", self._nearby_reviews_source),
                    "fallback": True,
                },
            }

        self._location_cache[cache_key] = dataset
        return dataset

    def run_nearby_reviews_script(
        self,
        *,
        latitude: float,
        longitude: float,
        place_type: str,
    ) -> Optional[Dict[str, Any]]:
        """nearby_reviews.py 스크립트 실행"""
        script = self._nearby_reviews_script
        if script is None:
            print("⚠️ nearby_reviews.py 스크립트를 찾을 수 없습니다.")
            return None

        tmp_file: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_file = Path(tmp.name)

            cmd = [
                sys.executable,
                str(script),
                "--lat",
                str(latitude),
                "--lon",
                str(longitude),
                "--place-type",
                place_type or "음식점",
                "--radius",
                "1000",
                "--places",
                "10",
                "--reviews-per-place",
                "3",
                "--out",
                str(tmp_file),
                "--headless",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                print(f"❌ nearby_reviews 실행 실패(code={result.returncode}): {result.stderr}")
                return None

            with open(tmp_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            dataset = {
                "stores": data.get("stores", []),
                "reviews": data.get("reviews", {}),
                "distances": data.get("distances", {}),
                "locations": data.get("locations", {}),
                "meta": {
                    "source": f"{script} (generated)",
                    "stdout": result.stdout.strip(),
                },
            }
        
            self._nearby_reviews_source = dataset["meta"]["source"]
            return dataset
        except Exception as exc:
            print(f"⚠️ nearby_reviews 실행 중 오류: {exc}")
            return None
        finally:
            if tmp_file and tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    async def determine_coordinates(
        self,
        *,
        location_value: Optional[Any],
        fallback_lat: float,
        fallback_lon: float,
    ) -> tuple[float, float]:
        """쿼리에서 추출된 location 문자열을 네이버 지오코딩으로 좌표화"""
        if location_value is None:
            return fallback_lat, fallback_lon

        if isinstance(location_value, list):
            location_text = location_value[0] if location_value else None
        else:
            location_text = location_value

        if not location_text:
            return fallback_lat, fallback_lon

        if not (NAVER_GEO_AVAILABLE and geocode_location and self._naver_client):
            return fallback_lat, fallback_lon

        try:
            async with aiohttp.ClientSession() as session:
                coords = await geocode_location(
                    session,
                    location_text,
                    naver_client=self._naver_client,
                )
            if coords:
                lat, lon = coords
                return lat, lon
        except Exception as exc:
            print(f"⚠️ 위치 지오코딩 실패({location_text}): {exc}")

        return fallback_lat, fallback_lon


async def main():
    """테스트용 main 함수 - 임의의 입력값으로 location 모듈 테스트"""
    import asyncio
    
    print("=" * 60)
    print("📍 Location Module 테스트")
    print("=" * 60)
    
    # LocationModule 인스턴스 생성
    location_module = LocationModule()
    
    # 테스트용 입력값 설정
    latitude = 37.4981 # 충무로역
    longitude = 127.0283  # 충무로역
    place_type = "중식집"
    attributes = ["분위기 좋은"]
    
    print(f"\n📌 입력 파라미터:")
    print(f"  - 위도(latitude): {latitude}")
    print(f"  - 경도(longitude): {longitude}")
    print(f"  - 장소 타입(place_type): {place_type}")
    print(f"  - 속성(attributes): {attributes}")
    
    # 1. 좌표 결정 테스트 (지오코딩)
    print(f"\n[1/2] 🗺️  좌표 결정 테스트...")
    test_location = "강남역"
    resolved_lat, resolved_lon = await location_module.determine_coordinates(
        location_value=test_location,
        fallback_lat=latitude,
        fallback_lon=longitude,
    )
    print(f"  입력 위치: {test_location}")
    print(f"  결정된 좌표: ({resolved_lat}, {resolved_lon})")
    
    # 2. Location Stage 준비 테스트
    print(f"\n[2/2] 🏪 Location Stage 준비 테스트...")
    print(f"  위도: {latitude}, 경도: {longitude}")
    print(f"  장소 타입: {place_type}")
    print(f"  속성: {attributes}")
    
    result = location_module.prepare_location_stage(
        latitude=latitude,
        longitude=longitude,
        place_type=place_type,
        attributes=attributes,
    )
    
    # 결과 출력
    print(f"\n✅ 결과:")
    print(f"  - 성공 여부: {result.get('success', False)}")
    print(f"  - 메시지: {result.get('message', 'N/A')}")
    
    if result.get('success'):
        stores = result.get('stores', [])
        reviews = result.get('reviews', {})
        meta = result.get('meta', {})
        
        print(f"\n📊 데이터 통계:")
        print(f"  - 발견된 가게 수: {len(stores)}개")
        print(f"  - 리뷰가 있는 가게 수: {len(reviews)}개")
        print(f"  - 데이터 소스: {meta.get('source', 'N/A')}")
        print(f"  - 좌표: {meta.get('coordinates', {})}")
        
        if stores:
            print(f"\n🏪 발견된 가게 목록 (최대 10개):")
            for i, store in enumerate(stores[:10], 1):
                print(f"  {i}. {store}")
                store_reviews = reviews.get(store, [])
                if store_reviews:
                    print(f"     리뷰 수: {len(store_reviews)}개")
                    print(f"     첫 번째 리뷰: {store_reviews[0][:50]}...")
                    
            output_path = Path("location_module_output.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n💾 결과를 '{output_path}' 파일에 저장했습니다.")
        else:
            print(f"\n⚠️  가게를 찾지 못했습니다.")
    else:
        error = result.get('error', 'N/A')
        print(f"  - 오류: {error}")
    
    print("\n" + "=" * 60)
    print("테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
