"""
MCP Client MVP - 위치 기반 할인 서비스
REST API 서버 + MCP Client + LLM 통합

실행 모드:
1. API 서버 모드: python mcp_client.py --mode api

"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import Optional, Dict, Any, List
import json
import sys
import os
import subprocess
import tempfile
from pathlib import Path
import argparse
import aiohttp

# RAG 통합
from RAG.rag_module import RAGPipeline
from chat_filter_pipeline import ChatFilterPipeline
from llm_responder import call_openai_llm
# Location Module 통합
from location_module import LocationModule

# Location Server (네이버 지오코딩) 통합 준비
LOCATION_SERVER_PATHS = [
    Path("/Users/goyuji/mcp-server/Location_server"),
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


# FastAPI 관련 (API 모드에서만 사용)
try:
    from fastapi import FastAPI, HTTPException, Depends, Header, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, HTMLResponse
    from pydantic import BaseModel
    from fastapi.security import APIKeyHeader
    import uvicorn
    import json
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("⚠️  FastAPI가 설치되지 않았습니다. API 모드를 사용하려면 'pip install fastapi uvicorn' 실행")

# OpenAI 통합
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None
    print("⚠️  OpenAI가 설치되지 않았습니다. LLM 기능을 사용하려면 'pip install openai' 실행")


# API 키 (팀원들과 공유할 비밀 키)
API_KEY = os.getenv("API_KEY", "OSS_TEAM_SECRET_KEY_2025")



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

# OpenAI API 키 로드
def load_openai_api_key():
    """OPENAI_API.txt 파일에서 API 키 로드"""
    try:
        key_file = os.path.join(os.path.dirname(__file__), "OPENAI_API.txt")
        with open(key_file, 'r') as f:
            key = f.read().strip()
            if key and key != "YOUR_API_KEY_HERE":
                return key
    except FileNotFoundError:
        pass
    
    # 환경 변수에서 시도
    return os.getenv("OPENAI_API_KEY", None)

# OpenAI API 설정
OPENAI_API_KEY = load_openai_api_key()
OPENAI_CLIENT = None

if OPENAI_API_KEY and OPENAI_AVAILABLE:
    try:
        OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)
        print(f"✅ OpenAI API 키 로드 완료")
    except Exception as e:
        print(f"⚠️  OpenAI 클라이언트 초기화 실패: {e}")
else:
    print(f"⚠️  OpenAI API 키가 설정되지 않았습니다.")




# ==================== MCP Server 클래스들 ====================

class LocationServer:
    """위치 기반 상점 검색 서버"""
    
    def __init__(self):
        """초기화"""
        self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Location_server/location_server.py"
    
    async def search_stores(
        self, 
        latitude: float, 
        longitude: float, 
        place_type: str,
        radius: int = 1000,
        max_stores: int = 10,
        reviews_per_store: int = 3
    ) -> Dict[str, Any]:
        """
        상점 검색 (MCP Server 호출)
        
        Args:
            latitude: 위도
            longitude: 경도
            place_type: 장소 유형 (예: "카페", "중식집", "일식집", "맛집", "음식점")
            radius: 검색 반경(m), 기본값 1000
            max_stores: 최대 검색할 매장 수, 기본값 10
            reviews_per_store: 각 매장당 수집할 리뷰 수, 기본값 3
        
        Returns:
            검색 결과 딕셔너리 (stores, reviews 포함)
        """
        # 절대 경로로 변환
        import os
        server_path_abs = os.path.abspath(self.server_path)
        server_dir = os.path.dirname(server_path_abs)
        
        server_params = StdioServerParameters(
            command="python",
            args=[server_path_abs],
            env=None,
            cwd=server_dir  # 작업 디렉토리 설정
        )
        
        try:
            from mcp.client.stdio import stdio_client
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # search_fnb_with_reviews 도구 호출
                    result = await session.call_tool(
                        "search_fnb_with_reviews",
                        {
                            "latitude": latitude,
                            "longitude": longitude,
                            "category": place_type,
                            "radius": radius,
                            "max_stores": max_stores,
                            "reviews_per_store": reviews_per_store
                        }
                    )
                    
                    # 결과 파싱
                    if result.content and len(result.content) > 0:
                        response_text = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                        
                        # 빈 문자열 체크
                        if not response_text or not response_text.strip():
                            print("   ⚠️ LocationServer에서 빈 응답 받음")
                            return {"stores": [], "reviews": {}, "error": "빈 응답"}
                        
                        try:
                            parsed_result = json.loads(response_text)
                            print(f"   ✅ LocationServer 응답: {parsed_result.get('message', 'N/A')}")
                            print(f"   📍 가게 수: {parsed_result.get('total_stores', 0)}개")
                            print(f"   💬 리뷰 수: {parsed_result.get('total_reviews', 0)}개")
                            return parsed_result
                        except json.JSONDecodeError as e:
                            print(f"   ⚠️ JSON 파싱 오류: {e}")
                            print(f"   응답 내용 (처음 200자): {response_text[:200]}")
                            return {"stores": [], "reviews": {}, "error": f"JSON 파싱 오류: {str(e)}"}
                    
                    print("   ⚠️ LocationServer에서 빈 응답 받음")
                    return {"stores": [], "reviews": {}, "error": "결과 없음"}
                    
        except Exception as e:
            print(f"   ❌ LocationServer 통신 오류: {e}")
            import traceback
            traceback.print_exc()
            return {
                "stores": [],
                "reviews": {},
                "error": f"LocationServer 통신 오류: {str(e)}",
                "details": str(e)
            }
    


class DiscountServer:
    """할인 정보 수집 서버 (Discount_MAP_server MCP)"""
    
    def __init__(self):
        """초기화"""
        # 네 Discount_MAP_server MCP 진입점
        self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Discount_MAP_server/discount_server.py"
        self.is_implemented = True
    
    async def get_discounts(
        self,
        stores: List[str],
        user_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Discount_MAP MCP 서버 호출해서 매장별 할인 정보 가져오기.
        
        Args:
            stores: 가게 이름 리스트 (Location 단계 결과)
            user_profile: 사용자 프로필 (통신사, 멤버십, 카드 등)
        
        Returns (예시):
            {
              "success": bool,
              "message": str,
              "discounts_by_store": { store_name: [ {discount...}, ... ] },
              ... (discount_server가 더 넣어준 필드들)
            }
        """
        if not self.is_implemented:
            return {
                "success": False,
                "message": "DiscountServer가 아직 구현되지 않았습니다.",
                "discounts_by_store": {},
            }
        
        if not stores:
            return {
                "success": True,
                "message": "입력 매장이 없어 할인 조회를 건너뜁니다.",
                "discounts_by_store": {},
            }
        
        # 절대 경로로 변환
        server_path_abs = os.path.abspath(self.server_path)
        server_dir = os.path.dirname(server_path_abs)
        
        server_params = StdioServerParameters(
            command="python",          # 서버 실행 명령
            args=[server_path_abs],    # discount_server.py
            env=None,
            cwd=server_dir,            # 작업 디렉터리
        )
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    #  서버 쪽 함수 시그니처가 (userProfile, stores)이므로
                    payload = {
                        "userProfile": user_profile,
                        "stores": stores,
                    }
                    
                    # 서버의 tool 이름: "get_discounts_for_stores"
                    result = await session.call_tool(
                        "get_discounts_for_stores",
                        payload,
                    )
                    
                    if not result.content:
                        return {
                            "success": False,
                            "message": "DiscountServer에서 빈 응답을 받았습니다.",
                            "discounts_by_store": {},
                        }
                    
                    response_text = getattr(result.content[0], "text", None) or str(result.content[0])
                    
                    if not response_text.strip():
                        return {
                            "success": False,
                            "message": "DiscountServer 응답이 비어 있습니다.",
                            "discounts_by_store": {},
                        }
                    
                    try:
                        parsed = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        print(f"[DiscountServer] JSON 파싱 오류: {e}")
                        print(f"  응답 앞 200자: {response_text[:200]}")
                        return {
                            "success": False,
                            "message": f"DiscountServer JSON 파싱 오류: {e}",
                            "discounts_by_store": {},
                            "raw_response": response_text,
                        }
                    
                    # DiscountService가 어떤 키를 넣어주든 받아서 넘겨주기
                    discounts_by_store = parsed.get("discounts_by_store", {})
                    
                    return {
                        "success": parsed.get("success", True),
                        "message": parsed.get("message", "할인 정보 조회 성공"),
                        "discounts_by_store": discounts_by_store,
                        "raw_response": parsed,
                    }
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"DiscountServer 통신 오류: {e}",
                "discounts_by_store": {},
                "error": str(e),
            }

class RecommendationServer:
    """추천 알고리즘 서버 (추후 구현 예정)"""
    
    def __init__(self):
        """초기화"""
        # TODO: 실제 추천 MCP 서버 경로 설정
        self.server_path = "실제 파일 경로로 바꿀 것."
        # 예시: self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Recommendation_server/recommendation_server.py"
        self.is_implemented = False
    




# ============================================================
# LLM 통합 레이어
# ============================================================

class LLMEngine:
    """LLM 엔진 (OpenAI + RAG)"""
    
    def __init__(self):
        """
        초기화
        """
        self.chat_filter_pipeline = ChatFilterPipeline()  # chat.py 통합
        self.rag_pipeline = RAGPipeline()
        self.location_server = LocationServer()
        self.discount_server = DiscountServer()
        self.recommendation_server = RecommendationServer()
        self.location_module = LocationModule()
        
        # OpenAI 사용 가능 여부 확인
        self.openai_available = OPENAI_AVAILABLE and OPENAI_API_KEY and OPENAI_CLIENT
        self.openai_client = OPENAI_CLIENT

    
    async def process_query(
        self,
        user_query: str,
        latitude: float,
        longitude: float,
        user_id: str, 
        user_profile: Dict[str, Any] = None,
        mode: List[int] = None,
    ) -> Dict[str, Any]:
        """
        사용자 질문 처리 (수정된 아키텍처)
        
        아키텍처 흐름:
        1. Prompt Filter
        2. LocationServer
        3. DiscountServer 
        4. RecommendationServer 
        5. RAG
        6. OpenAI LLM
        
        Args:
            user_query: 사용자 질문
            latitude: 위도
            longitude: 경도
            user_id: 사용자 ID (필수!)
        
        Returns:
            LLM 응답
        """
        print("\n" + "="*60)
        print(f"🎯 LLM 쿼리 처리 시작")
        print(f"   사용자: {user_id}")
        print(f"   질문: {user_query}")
        print(f"   위치: ({latitude}, {longitude})")
        
        # 프로필 정보 요약 출력
        if user_profile:
            profile_parts = []
            if user_profile.get("telco"):
                profile_parts.append(f"통신사: {user_profile.get('telco')}")
            if user_profile.get("memberships"):
                profile_parts.append(f"멤버십: {', '.join(user_profile.get('memberships', []))}")
            if user_profile.get("cards"):
                profile_parts.append(f"카드: {', '.join(user_profile.get('cards', []))}")
            if user_profile.get("categories"):
                profile_parts.append(f"선호카테고리: {', '.join(user_profile.get('categories', []))}")
            if profile_parts:
                print(f"   프로필(user_profile): {', '.join(profile_parts)}")
            else:
                print(f"   프로필(user_profile): (빈 프로필)")
        else:
            print(f"   프로필(user_profile): None")
        
        print("="*60)
        
        if mode is None:
            print(" 처리 모드 지정 필요.")
            return {
                "success": False,
                "response": "mode가 지정되지 않았습니다.",
                "mcp_results": {},
                "error": "MODE_NOT_SPECIFIED",
            }        
        ################################################ 1. Prompt Filtering 도메인 제한 및 지도 검색 키워드 추출
        
        print(f"\n[1/6] 🛡️  ChatFilterPipeline 실행 중...")
        
        # User Profile 생성 (user_id 기반 기본값)
        base_user_profile = {
            "userId": user_id,
            "telco": "SKT",  # TODO: 실제 사용자 데이터로 대체
            "memberships": [],
            "cards": [],
            "affiliations": []
        }
        # 외부에서 전달된 user_profile이 있으면 기본값과 병합
        if user_profile:
            provided_profile = {
                key: value for key, value in user_profile.items()
                if value is not None
            }
            base_user_profile.update(provided_profile)
        # 서버가 받은 user_id를 강제 주입해 일관성 유지
        base_user_profile["userId"] = user_id
        user_profile = base_user_profile
        
        
        # ChatFilterPipeline 실행
        filter_result = self.chat_filter_pipeline.process(
            user_query=user_query,
            user_profile=user_profile
        )
        
        if not filter_result["success"]:
            print(f"❌ ChatFilterPipeline 거부: {filter_result['message']}")
            return {
                "success": False,
                "error": filter_result.get("error", "validation_failed"),
                "response": filter_result["message"],
                "mcp_results": {}
            }
        
        print(f"✅ ChatFilterPipeline 통과")
        print(f"   키워드: {filter_result['keywords']}")
        print(f"   MCP Ready: {filter_result['mcp_ready']}")
        
        # 결과 저장
        keywords = filter_result["keywords"]
        extracted_user_profile = filter_result["user_profile"]
        
        # mode[0] and not mode[1]: Prompt Filter까지만 실행
        if mode[0] and not mode[1]:
            return {
                "success": True,
                "response": "ChatFilterPipeline 완료",
                "keywords": keywords,
                "user_profile": extracted_user_profile,
                "mcp_ready": filter_result["mcp_ready"],
                "mcp_results": {
                    "step": "chat_filter_pipeline",
                    "keywords": keywords,
                    "user_profile": extracted_user_profile
                },
                "error": None,
            }
        
        ##### output 다음 단계로 전달할 변수들
        place_type_value = keywords.get("place_type")
        if isinstance(place_type_value, list):
            place_type = place_type_value[0] if place_type_value else "음식점"
        else:
            place_type = place_type_value or "음식점"

        resolved_latitude, resolved_longitude = await self._determine_coordinates(
            location_value=keywords.get("location"),
            fallback_lat=latitude,
            fallback_lon=longitude,
        )
        location = resolved_latitude, resolved_longitude
        attributes = keywords.get("attributes", [])
        user_profile = extracted_user_profile
        
        # 변수 초기화 (mode에 따라 정의되지 않을 수 있으므로)
        stores = []
        reviews = {}
        discounts_by_store = {}
        recommendations = {}
        mcp_results = {}
        
        
        
        ################################################ 2. LocationServer
        print(f"\n[2/6] 📍 LocationServer 호출 중...")
        
        
        ## input: location, place_type
        location_payload = self.location_module.prepare_location_stage(
                latitude=latitude,
                longitude=longitude,
                place_type=place_type or "음식점",
                attributes=attributes,
            )
        stores = location_payload.get("stores", [])
        reviews = location_payload.get("reviews", {})
        mcp_results = {
            "step": "location_server",
            "stores": stores,
            "reviews": reviews,
            "meta": location_payload.get("meta"),
        }
        if mode[1] and not mode[2]:
            return {
                "success": location_payload.get("success", False),
                "response": location_payload.get("message", "LocationServer 완료"),
                "stores": stores,
                "reviews": reviews,
                "mcp_results": mcp_results,
                "error": location_payload.get("error"),
            }
            
         
            ## 위와 같은 구현을 할 건데 다음 모드로 넘어갈 결과값을 구현하면 됨.
        
        ### output 다음 단계로 전달할 변수들
        # stores: 가게 이름 리스트 (LocationServer에서 할당됨)
        # reviews: 가게 리뷰 리스트 (LocationServer에서 할당됨)
                
        
        ################################################
        
        # 3. DiscountServer (LocationServer 결과 + 사용자 프로필 사용)
        ## input : stores, user_profile
        ################################################ 3. DiscountServer
        print(f"\n[3/6] 💰 DiscountServer 호출 중...")
        discounts_by_store: Dict[str, Any] = {}

        if mode[2] and not mode[3]:
            discount_result = await self.discount_server.get_discounts(
                stores=stores,
                user_profile=user_profile,
            )
            discounts_by_store = discount_result.get("discounts_by_store", {})

            # mode[2] == True이고 mode[3] == False면 여기까지가 목표이므로 바로 반환
            if not mode[3]:
                return {
                    "success": discount_result.get("success", False),
                    "response": discount_result.get("message", ""),
                    "stores": stores,
                    "reviews": reviews,
                    "discounts_by_store": discounts_by_store,
                    "mcp_results": {
                        **mcp_results,
                        "discounts_by_store": discounts_by_store,
                    },
                    "error": discount_result.get("error"),
                }

            # 여기서부터는 RecommendationServer / RAG / LLM 이어지는 로직...
            # (나중에 만들 때 discounts_by_store 넘겨주면 됨)
            mcp_results["discount"] = {
                "message": discount_result.get("message"),
                "discounts_by_store": discounts_by_store,
                "raw": discount_result.get("raw_response"),
            }
        
        # 4. RecommendationServer (할인율 순, 거리 순 등 정렬 결과 만들기)
        print(f"\n[4/6] 🎯 RecommendationServer 호출 중...")
        if mode[3] and not mode[4]:
            recommendation_result = await self.recommendation_server.get_recommendations(
                user_id=user_id,
                stores=stores,
                discounts=discounts_by_store,
            )

            
            ### not mode[4] 이라는 소리는 RAG까지의 넘어갈 필요가 없다는 것이므로 여기서 종료.
            return 
        else:
            pass
            ## 위와 같은 구현을 할 건데 다음 모드로 넘어갈 결과값을 구현하면 됨.
        
        ### output 다음 단계로 전달할 변수들
        ### recommendations: 추천 결과 리스트 (할인율 순, 거리순)
        # 아래는 예시 데이터 구조 
        #   recommendations = {
        #     "by_discount": {
            #     "store_list": [
            #         {
            #             "store_id": "s1",
            #             "name": "맘스터치",
            #             "distance_meters": 200,
            #             "all_benefits": [
            #                 {
            #                     "discountName": "신메뉴 출시 20% 할인",
            #                     "providerType": "STORE",
            #                     "providerName": "맘스터치",
            #                     "shape": {"kind": "PERCENT", "amount": 20.0, "maxAmount": None},
            #                 },
            #                 {
            #                     "discountName": "멤버십 적립 5000원",
            #                     "providerType": "MEMBERSHIP",
            #                     "providerName": "MPOINT",
            #                     "shape": {"kind": "AMOUNT", "amount": 5000.0, "maxAmount": None},
            #                 },
            #             ],
            #             "rank": 1,
            #         },
            #         {
            #             "store_id": "s2",
            #             "name": "은화수식당",
            #             "distance_meters": 350,
            #             "all_benefits": [
            #                 {
            #                     "discountName": "CJ ONE 10% 할인",
            #                     "providerType": "MEMBERSHIP",
            #                     "providerName": "CJ ONE",
            #                     "shape": {"kind": "PERCENT", "amount": 10.0, "maxAmount": None},
            #                 },
            #                 {
            #                     "discountName": "리뷰작성시 음료증정",
            #                     "providerType": "STORE",
            #                     "providerName": "은화수식당",
            #                     "shape": {"kind": "AMOUNT", "amount": 0.0, "maxAmount": None},
            #                 },
            #             ],
            #             "rank": 2,
            #         },
            #         {
            #             "store_id": "s3",
            #             "name": "중국성",
            #             "distance_meters": 180,
            #             "all_benefits": [
            #                 {
            #                     "discountName": "T멤버십 1000원당 150원 할인",
            #                     "providerType": "TELCO",
            #                     "providerName": "SKT",
            #                     "shape": {
            #                         "kind": "PER_UNIT",
            #                         "amount": 0.0,
            #                         "maxAmount": 3000.0,
            #                         "unitRule": {"unitAmount": 1000.0, "perUnitValue": 150.0, "maxDiscountAmount": 3000.0},
            #                     },
            #                 }
            #             ],
            #             "rank": 3,
            #         },
            #     ]
            # },
            # "by_distance": {
            #     "store_list": [
            #         {"store_id": "s3", "name": "중국성", "distance_meters": 180, "rank": 1},
            #         {"store_id": "s1", "name": "맘스터치", "distance_meters": 200, "rank": 2},
            #         {"store_id": "s2", "name": "은화수식당", "distance_meters": 350, "rank": 3},
            #     ]
            # },
        # }
        
        
        ## recomendation server의 output
        recommendations = recommendations
        
        
        
        ####### 아래는 RAG용 이니까 신경 X ##########
        # RAG (벡터 DB 생성 및 검색) - 스텁
        if mode[4]:
            print(f"\n[6/6] 🔍 RAG 처리 중...")
           
            rag_result = self.rag_pipeline.process(
                user_query=user_query,
                recommendations=recommendations,
                top_k=3,
                session_id=user_id,
                user_profile=user_profile,
                reviews=reviews
            )

            discount_summary = rag_result.get("discount_summary")

            # [4단계] OpenAI LLM 호출 (실제 구현)
            print(f"\n🤖 OpenAI LLM 호출 중...")
            if self.openai_available:
                response = await call_openai_llm(
                    openai_client=self.openai_client,
                    user_query=user_query,
                    llm_context=rag_result["llm_context"],
                    filter_result=filter_result,
                )
                print(f"✅ LLM 응답 생성 완료")
            else:
                response = rag_result.get("fallback_answer", "LLM 응답을 생성할 수 없습니다.")

            if discount_summary:
                response = f"{response}\n\n[할인 요약]\n{discount_summary}"

            print("\n" + "="*60)
            print(f"✅ 쿼리 처리 완료")
            print("="*60 + "\n")

            return {
                "success": True,
                "query": user_query,
                "response": response,
                "mcp_results": mcp_results,
                "rag_result": rag_result,
                "discount_summary": discount_summary,
            }
        
    
    


# ============================================================
# REST API 서버 모드 (FastAPI)
# ============================================================

# Pydantic 모델 (API 요청/응답)
if FASTAPI_AVAILABLE:
    class RecommendRequest(BaseModel):
        """LLM 기반 추천 요청 모델"""
        query: str
        latitude: float
        longitude: float
        user_id: str  # 필수로 변경!
        context: Optional[Dict[str, Any]] = None
        user_profile: Optional[Dict[str, Any]] = None
        
        class Config:
            json_schema_extra = {
                "example": {
                "query": "강남역 근처 맛집 추천해줘",
                "latitude": 37.5665,
                "longitude": 126.9780,
                "user_id": "user123",
                "user_profile": {
                    "telco": "SKT",
                    "memberships": ["VIP"],
                    "cards": ["T-Lounge"],
                    "categories": [
                    "가성비",
                    "모임",
                    "혼밥",
                    "분위기"
                    ]
                },
                
            }
        }
    
    class RecommendResponse(BaseModel):
        """LLM 기반 추천 응답 모델"""
        success: bool
        query: str
        response: str
        mcp_results: Optional[Dict[str, Any]] = None
        error: Optional[str] = None


# 전역 인스턴스
location_server = LocationServer()
llm_engine = LLMEngine()

# FastAPI 앱 생성
if FASTAPI_AVAILABLE:
    app = FastAPI(
        title="위치 기반 할인 서비스 API",
        description="Flutter 앱과 MCP Server를 연결하는 REST API",
        version="1.0.0",
        # 보안: Swagger 문서 비활성화 (외부 노출 방지)
        docs_url=None,  # /docs 비활성화
        redoc_url=None  # /redoc 비활성화
    )
    
    # CORS 설정 (모바일 앱 지원)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 모든 origin 허용 (모바일 5G, WiFi 등)
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
    )
    
   
    
    # API 키 검증 함수 (주요 보안 수단)
    async def verify_api_key(x_api_key: str = Header(None)):
        """API 키 검증 (보호된 엔드포인트용)"""
        if not x_api_key:
            raise HTTPException(
                status_code=401,
                detail="API 키가 필요합니다. Header에 X-API-Key를 포함하세요."
            )
        
        if x_api_key != API_KEY:
            raise HTTPException(
                status_code=403,
                detail="유효하지 않은 API 키입니다"
            )
        return x_api_key
    
    @app.get("/ping")
    async def ping():
        """
        초간단 연결 확인 (PowerShell ping과 유사)
        
        팀원들이 가장 먼저 테스트해야 할 엔드포인트
        최소한의 응답만 반환하여 빠르게 확인
        """
        return {"pong": True}
    
    
    @app.post("/api/recommend", response_model=RecommendResponse)
    async def recommend_with_llm(
        request: RecommendRequest,
        api_key: str = Depends(verify_api_key)
    ):
        """
        LLM 기반 개인화 추천 API (API 키 필요)
        
        1. Prompt Filter
        2. LocationServer
        3. DiscountServer 
        4. RecommendationServer 
        5. RAG
        6. OpenAI LLM
        
        **필수 파라미터**:
        - user_id: 사용자 ID (개인화를 위해 필수!)
        - query: 자연어 질문
        - latitude, longitude: 현재 위치
        
        Header: X-API-Key: OSS_TEAM_SECRET_KEY_2025
        
        Args:
            request: 추천 요청 (질문, 위도, 경도, 사용자ID 등)
        
        Returns:
            LLM 응답
        
        Example:
            {
                "query": "강남역 근처 맛집 추천해줘. 할인 많이 받을 수 있는 곳으로",
                "latitude": 37.5665,
                "longitude": 126.9780,
                "user_id": "user123"
            }
        """
        try:
            ## mode 별로 구현 되는 단계의 깊이가 다르게 설정함.
            # mode = {prompt,location,discount,recommendation,rag}
            # mode = [1,0,0,0,0]  # prompt filter 까지만
            # mode = [1,1,0,0,0]  # location server 까지만
            # mode = [1,1,1,0,0]  # discount server 까지만
            # mode = [1,1,1,1,0]  # recommendation server 까지만
            # mode = [1,1,1,1,1]  # rag 까지 모두
            
            # 기본 위치 설정 (서울 시청)
            latitude = request.latitude if request.latitude is not None else 37.5665
            longitude = request.longitude if request.longitude is not None else 126.9780
            
            result = await llm_engine.process_query(
                user_query=request.query,
                latitude=latitude,
                longitude=longitude,
                user_id=request.user_id,
                user_profile=request.user_profile, ## user_profile 넘겨받는 부분 추가
                mode=[1,1,0,0,0]  # location server까지 실행
            )
            
            if not result["success"]:
                return RecommendResponse(
                    success=False,
                    query=request.query,
                    response=result["response"],
                    error=result.get("error")
                )
            
            return RecommendResponse(
                success=True,
                query=request.query,
                response=result["response"],
                mcp_results=result.get("mcp_results")
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"서버 오류: {str(e)}"
            )



# ============================================================
# 메인 함수
# ============================================================

def main():
    """메인 진입점"""
    parser = argparse.ArgumentParser(description="위치 기반 할인 서비스 MCP Client")
    parser.add_argument(
        "--mode",
        choices=["api", "test"],
        default="test",
        help="실행 모드: api (REST API 서버) 또는 test (테스트)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="API 서버 호스트 (기본: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API 서버 포트 (기본: 8000)"
    )
    
    args = parser.parse_args()
    
    if args.mode == "api":
        if not FASTAPI_AVAILABLE:
            print("❌ FastAPI가 설치되지 않았습니다.")
            print("   실행: pip install fastapi uvicorn pydantic")
            sys.exit(1)
        
       
        
        public_ip = "115.68.232.165"  # 실제 리눅스 서버 공인 IP
        print("🚀 REST API 서버 시작...")
        print(f"   바인드 주소: {args.host}")
        print(f"\n📱 Flutter 앱 접속 주소:")
        print(f"   ▶ http://{public_ip}/api/recommend")
        print(f"\n🔧 개발자 테스트 엔드포인트:")
        print(f"   ▶ GET  http://localhost:{args.port}/ping")
        print(f"   ▶ GET  http://localhost:{args.port}/api/health")
        print(f"   ▶ GET  http://localhost:{args.port}/api/test")
        print(f"\n💡 참고:")
        print(f"   - Flutter 앱은 /api/recommend 엔드포인트만 사용")
        print(f"   - user_id는 필수 파라미터입니다")
        print(f"   - API 문서(Swagger)는 보안상 비활성화되어 있습니다")
        print("\n" + "=" * 60)
        
        uvicorn.run(app, host=args.host, port=args.port)
    


if __name__ == "__main__":
    main()
