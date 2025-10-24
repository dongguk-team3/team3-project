"""
카카오맵 Location Server API 키 및 설정 관리
실제 키 값은 환경변수나 이 파일에 직접 입력
"""

import os
from dotenv import load_dotenv

# .env 파일이 있으면 로드
load_dotenv()

# 카카오 API 키
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "93270974719a36f5e6a22843a6fdd90d")
KAKAO_NATIVE_APP_KEY = os.getenv("KAKAO_NATIVE_APP_KEY", "db27d6b0e7d3478e23cff9234ecaaf87")
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "9cf6952dc735c95d0c047a49ad7ff33a")
KAKAO_ADMIN_KEY = os.getenv("KAKAO_ADMIN_KEY", "9583dbd06952cd91bac206714e949875")

# API 키 검증
def validate_api_keys():
    """API 키가 설정되어 있는지 확인"""
    if not KAKAO_REST_API_KEY:
        print("⚠️  경고: KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        print("   환경변수를 설정하거나 location_server_config.py에 직접 입력하세요.")
        return False
    return True

# 카카오맵 API 엔드포인트
KAKAO_API_BASE_URL = "https://dapi.kakao.com"
KAKAO_LOCAL_SEARCH_URL = f"{KAKAO_API_BASE_URL}/v2/local/search/keyword.json"
KAKAO_CATEGORY_SEARCH_URL = f"{KAKAO_API_BASE_URL}/v2/local/search/category.json"
KAKAO_ADDRESS_SEARCH_URL = f"{KAKAO_API_BASE_URL}/v2/local/search/address.json"
KAKAO_COORD_TO_ADDRESS_URL = f"{KAKAO_API_BASE_URL}/v2/local/geo/coord2address.json"

if __name__ == "__main__":
    print("=== 카카오 Location Server API 설정 확인 ===")
    print(f"REST API Key 설정됨: {'✅' if KAKAO_REST_API_KEY else '❌'}")
    print(f"Native App Key 설정됨: {'✅' if KAKAO_NATIVE_APP_KEY else '❌'}")
    print(f"JavaScript Key 설정됨: {'✅' if KAKAO_JAVASCRIPT_KEY else '❌'}")
    print(f"Admin Key 설정됨: {'✅' if KAKAO_ADMIN_KEY else '❌'}")

