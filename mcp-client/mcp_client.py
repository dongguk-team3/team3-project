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
import argparse

# RAG 통합
from RAG.rag_module import RAGPipeline
from chat_filter_pipeline import ChatFilterPipeline


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

# 접근 제어 설정 로드
def load_access_config():
    """config.json에서 접근 제어 설정 로드"""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config
    except FileNotFoundError:
        # 기본 설정
        return {
            "allowed_ips": ["127.0.0.1", "localhost", "::1"],
            "allowed_ports": [8000, 8001, 8002, 8080, 3000, 5000],
            "developer_mode": True,
            "enable_ip_whitelist": False,
            "enable_port_whitelist": False,
            "default_host": "0.0.0.0",
            "default_port": 8000
        }
    except Exception as e:
        print(f"⚠️  설정 파일 로드 실패: {e}")
        return {
            "allowed_ips": ["127.0.0.1", "localhost", "::1"],
            "allowed_ports": [8000, 8001, 8002, 8080, 3000, 5000],
            "developer_mode": True,
            "enable_ip_whitelist": False,
            "enable_port_whitelist": False,
            "default_host": "0.0.0.0",
            "default_port": 8000
        }

ACCESS_CONFIG = load_access_config()

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
        self.server_path = "실제 파일 경로로 바꿀 것."
        # 예시: self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Location_server/location_server.py" ## 실제 파일 경로로 바꿀 것.
    
    # async def search_stores(self, latitude: float, longitude: float, query: str) -> Dict[str, Any]:
    #     """
    #     상점 검색 (MCP Server 호출)
        
    #     Args:
    #         latitude: 위도
    #         longitude: 경도
    #         query: 검색 쿼리 (예: "음식점", "카페")
        
    #     Returns:
    #         검색 결과 딕셔너리
    #     """
    #     server_params = StdioServerParameters(
    #         command="python",
    #         args=[self.server_path],
    #         env={"PYTHONPATH": "/opt/conda/envs/team/lib/python3.11/site-packages"}
    #     )
        
    #     try:
    #         async with stdio_client(server_params) as (read, write):
    #             async with ClientSession(read, write) as session:
    #                 await session.initialize()
                    
    #                 # search_nearby_stores 도구 호출
    #                 result = await session.call_tool(
    #                     "search_nearby_stores",
    #                     {
    #                         "latitude": latitude,
    #                         "longitude": longitude,
    #                         "category": query
    #                     }
    #                 )
                    
    #                 # 결과 파싱
    #                 if result.content and len(result.content) > 0:
    #                     response_text = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
    #                     parsed_result = json.loads(response_text)
    #                     print(f"   MCP 서버 응답: {parsed_result.get('message', 'N/A')}")
    #                     print(f"   가게 수: {len(parsed_result.get('stores', []))}개")
    #                     return parsed_result
                    
    #                 print("   ⚠️ MCP 서버에서 빈 응답 받음")
    #                 return {"stores": [], "error": "결과 없음"}
                    
    #     except Exception as e:
    #         print(f"   ❌ MCP 통신 오류: {e}")
    #         return {
    #             "stores": [],
    #             "error": f"MCP 서버 통신 오류: {str(e)}",
    #             "details": str(e)
    #         }
    
    # ## 디버깅용 함수
    # async def test_connection(self, server_params: StdioServerParameters):
    #     """MCP 서버 연결 테스트"""
    #     print("=" * 60)
    #     print("🚀 MCP Client MVP 테스트 시작")
    #     print("=" * 60)
        
    #     try:
    #         print(f"🔌 MCP 서버에 연결 중...")
            
    #         # stdio_client로 서버와 연결
    #         async with stdio_client(server_params) as (read, write):
    #             async with ClientSession(read, write) as session:
    #                 # 세션 초기화
    #                 init_result = await session.initialize()
    #                 print(f"✅ MCP 서버 연결 성공!")
                    
    #                 # 서버 정보 출력
    #                 print(f"\n📋 서버 정보:")
    #                 print(f"  - 서버 이름: {init_result.serverInfo.name}")
    #                 print(f"  - 프로토콜 버전: {init_result.protocolVersion}")
                    
    #                 # 사용 가능한 도구 목록 조회
    #                 print(f"\n🔧 사용 가능한 도구 목록:")
    #                 tools_list = await session.list_tools()
                    
    #                 if not tools_list.tools:
    #                     print("  도구가 없습니다.")
    #                     return
                    
    #                 for i, tool in enumerate(tools_list.tools, 1):
    #                     print(f"  {i}. {tool.name}")
    #                     if hasattr(tool, 'description') and tool.description:
    #                         print(f"     설명: {tool.description}")
    #                     if hasattr(tool, 'inputSchema'):
    #                         print(f"     파라미터: {tool.inputSchema}")
                    
    #                 # 첫 번째 도구 테스트 실행
    #                 if tools_list.tools:
    #                     first_tool = tools_list.tools[0]
    #                     print(f"\n🧪 테스트 도구 실행: {first_tool.name}")
                        
    #                     # 도구에 따라 적절한 파라미터 설정
    #                     test_args = self._get_test_arguments(first_tool.name)
                        
    #                     if test_args is not None:
    #                         print(f"   파라미터: {json.dumps(test_args, ensure_ascii=False, indent=2)}")
                            
    #                         try:
    #                             result = await session.call_tool(first_tool.name, test_args)
    #                             print(f"✅ 도구 실행 성공!")
    #                             print(f"   결과:")
    #                             for content in result.content:
    #                                 if hasattr(content, 'text'):
    #                                     print(f"   {content.text}")
    #                                 else:
    #                                     print(f"   {content}")
    #                         except Exception as e:
    #                             print(f"⚠️  도구 실행 중 오류: {str(e)}")
    #                     else:
    #                         print(f"   (이 도구는 필수 파라미터가 필요하여 스킵합니다)")
                    
    #                 print("\n" + "=" * 60)
    #                 print("✅ MCP Client MVP 테스트 완료!")
    #                 print("=" * 60)
            
    #     except Exception as e:
    #         print(f"\n❌ 오류 발생: {str(e)}")
    #         import traceback
    #         traceback.print_exc()
    
    # ## 디버깅용 함수
    # def _get_test_arguments(self, tool_name: str) -> Optional[dict]:
    #     """도구별 테스트 파라미터 반환"""
    #     # 자체 위치 서버 도구들
    #     if tool_name == "search_nearby_stores":
    #         return {
    #             "latitude": 37.5665,   # 서울 시청 위도
    #             "longitude": 126.9780, # 서울 시청 경도
    #             "category": "음식점"
    #         }
        
    #     if tool_name == "get_store_info":
    #         return {
    #             "store_id": "store_001"
    #         }
        
    #     # 기본적으로 빈 딕셔너리 반환
    #     return {}


class DiscountServer:
    """할인 정보 수집 서버 (추후 구현 예정)"""
    
    def __init__(self):
        """초기화"""
        # TODO: 실제 할인 정보 MCP 서버 경로 설정
        self.server_path = "실제 파일 경로로 바꿀 것."
        # 예시: self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Discount_MAP_server/discount_server.py"
        self.is_implemented = False
    
    # async def get_discounts(
    #     self, 
    #     stores: List[Dict], 
    #     user_profile: Dict[str, Any]
    # ) -> Dict[str, Any]:
    #     """
    #     여러 가게의 할인 정보 일괄 조회 (사용자 프로필 기반)
        
    #     Args:
    #         stores: 가게 목록 (LocationServer 결과)
    #         user_profile: 사용자 프로필 (PatternAnalysisServer 결과)
    #             - telecom: 통신사
    #             - cards: 보유 카드 목록
    #             - memberships: 멤버십 목록
        
    #     Returns:
    #         가게별 할인 정보 딕셔너리
    #     """
    #     if not self.is_implemented:
    #         # TODO: 실제 MCP 서버 구현 후 제거
    #         # Mock 데이터: 각 가게별 할인 정보 생성
    #         discounts_by_store = {}
            
    #         for store in stores[:5]:  # 상위 5개만 Mock
    #             store_id = store.get("id", "unknown")
    #             store_name = store.get("name", "알 수 없음")
                
    #             # Mock 할인 생성
    #             mock_discounts = []
                
    #             # 통신사 할인 (Mock)
    #             telecom = user_profile.get("telecom", "")
    #             if telecom in ["SKT", "KT", "LG U+"]:
    #                 mock_discounts.append({
    #                     "type": "telecom",
    #                     "provider": telecom,
    #                     "rate": 20,
    #                     "description": f"{telecom} 통신사 제휴 20% 할인"
    #                 })
                
    #             # 카드 할인 (Mock)
    #             cards = user_profile.get("cards", {})
    #             primary_card = cards.get("primary", "")
    #             if primary_card:
    #                 mock_discounts.append({
    #                     "type": "card",
    #                     "provider": primary_card,
    #                     "rate": 10,
    #                     "description": f"{primary_card} 10% 즉시할인"
    #                 })
                
    #             # 최대 할인율 계산
    #             max_discount = max([d["rate"] for d in mock_discounts], default=0)
                
    #             discounts_by_store[store_id] = {
    #                 "store_id": store_id,
    #                 "store_name": store_name,
    #                 "discounts": mock_discounts,
    #                 "max_discount": max_discount,
    #                 "best_payment": mock_discounts[0] if mock_discounts else None
    #             }
            
    #         return {
    #             "message": "⚠️ 할인 정보 서버는 아직 구현되지 않았습니다 (Mock 데이터).",
    #             "discounts_by_store": discounts_by_store,
    #             "total_stores_analyzed": len(discounts_by_store)
    #         }
        
    #     # TODO: 실제 MCP 서버 호출 로직 구현
    #     pass


class RecommendationServer:
    """추천 알고리즘 서버 (추후 구현 예정)"""
    
    def __init__(self):
        """초기화"""
        # TODO: 실제 추천 MCP 서버 경로 설정
        self.server_path = "실제 파일 경로로 바꿀 것."
        # 예시: self.server_path = "/opt/conda/envs/team/OSS/mcp-server/Recommendation_server/recommendation_server.py"
        self.is_implemented = False
    
    # async def get_recommendations(
    #     self, 
    #     user_id: str,
    #     user_profile: Dict[str, Any],
    #     user_preferences: Dict[str, Any],
    #     stores: List[Dict],
    #     discounts: Dict[str, Any],
    #     context: Dict = None
    # ) -> Dict[str, Any]:
    #     """
    #     사용자 맞춤 추천 생성 (모든 MCP Server 결과 종합)
        
    #     Args:
    #         user_id: 사용자 ID
    #         user_profile: 사용자 프로필 (통신사, 카드 등)
    #         user_preferences: 사용자 선호도 (선호 카테고리, 평균 예산 등)
    #         stores: 상점 목록 (LocationServer)
    #         discounts: 할인 정보 (DiscountServer)
    #         context: 컨텍스트 정보 (시간, 날씨 등)
        
    #     Returns:
    #         추천 결과 딕셔너리 (순위별 점수 포함)
    #     """
    #     if not self.is_implemented:
    #         # TODO: 실제 MCP 서버 구현 후 제거
    #         # Mock: 하이브리드 추천 알고리즘 시뮬레이션
            
    #         discounts_data = discounts.get("discounts_by_store", {})
    #         preferred_categories = user_preferences.get("preferred_categories", [])
    #         avg_budget = user_preferences.get("avg_budget", 15000)
            
    #         scored_stores = []
            
    #         for store in stores:
    #             store_id = store.get("id", "")
    #             store_name = store.get("name", "알 수 없음")
    #             category = store.get("category_name", "")
    #             distance = store.get("distance", 999999)
                
    #             # 하이브리드 점수 계산 (Mock)
    #             score = 0.0
    #             breakdown = {}
                
    #             # [1] Content-Based Filtering (40%)
    #             content_score = 0.0
    #             # A. 카테고리 매칭 (25점)
    #             if any(cat in category for cat in preferred_categories):
    #                 content_score += 0.25
    #             # B. 거리 점수 (15점) - 가까울수록 높음
    #             distance_score = max(0, 1 - (distance / 1000)) * 0.15
    #             content_score += distance_score
                
    #             breakdown["content_based"] = content_score * 0.4
    #             score += content_score * 0.4
                
    #             # [2] Collaborative Filtering (30%) - Mock: 랜덤
    #             collab_score = 0.15  # Mock: 평균 점수
    #             breakdown["collaborative"] = collab_score * 0.3
    #             score += collab_score * 0.3
                
    #             # [3] Discount Optimization (30%)
    #             discount_info = discounts_data.get(store_id, {})
    #             max_discount = discount_info.get("max_discount", 0)
    #             discount_score = min(max_discount / 30, 1.0) * 0.3
    #             breakdown["discount"] = discount_score
    #             score += discount_score
                
    #             # 추천 이유 생성
    #             reasons = []
    #             if any(cat in category for cat in preferred_categories):
    #                 reasons.append(f"선호하시는 {category} 카테고리")
    #             if max_discount > 0:
    #                 best_payment = discount_info.get("best_payment", {})
    #                 provider = best_payment.get("provider", "") if best_payment else ""
    #                 reasons.append(f"{provider} {max_discount}% 할인")
    #             if distance < 300:
    #                 reasons.append(f"가까운 거리 ({distance}m)")
                
    #             scored_stores.append({
    #                 "rank": 0,  # 나중에 정렬 후 설정
    #                 "store": store,
    #                 "score": round(score, 2),
    #                 "score_breakdown": breakdown,
    #                 "discount_info": discount_info,
    #                 "recommendation_reason": ", ".join(reasons) if reasons else "주변 인기 매장"
    #             })
            
    #         # 점수순 정렬
    #         scored_stores.sort(key=lambda x: x["score"], reverse=True)
            
    #         # 순위 부여
    #         for idx, item in enumerate(scored_stores, 1):
    #             item["rank"] = idx
            
    #         return {
    #             "message": "⚠️ 추천 알고리즘 서버는 아직 구현되지 않았습니다 (Mock 알고리즘).",
    #             "recommendations": scored_stores[:10],
    #             "total_candidates": len(stores),
    #             "algorithm": "HybridRecommender (Mock)",
    #             "weights": {
    #                 "content_based": 0.4,
    #                 "collaborative": 0.3,
    #                 "discount": 0.3
    #             }
    #         }
        
    #     # TODO: 실제 MCP 서버 호출 로직 구현
    #     pass




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
        self.rag_pipeline = RAGPipeline(use_openai_embeddings=False)
        self.location_server = LocationServer()
        self.discount_server = DiscountServer()
        self.recommendation_server = RecommendationServer()
        
        # OpenAI 사용 가능 여부 확인
        self.openai_available = OPENAI_AVAILABLE and OPENAI_API_KEY and OPENAI_CLIENT
        self.openai_client = OPENAI_CLIENT
    
    async def process_query(
        self,
        user_query: str,
        latitude: float,
        longitude: float,
        user_id: str,  # 필수로 변경!
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
        
        ################################## MCP 결과를 단계별로 누적하여 RAG 및 LLM 단계에서 재사용
        mcp_results: Dict[str, Any] = {
            "user_query": user_query,
            "user_profile": user_profile,
        }
        
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
        
        # 다음 단계로 전달할 변수들
        place_type = keywords.get("place_type")
        location = keywords.get("location")
        attributes = keywords.get("attributes", [])
        ## extracted_user_profile를 할인 db에서 사용하면 됨.
        user_profile = extracted_user_profile
        
        
        
        ################################################ 2. LocationServer
        print(f"\n[2/6] 📍 LocationServer 호출 중...")
        if mode[1] and not mode[2]:
            
            ## location과 query_keywords는 Prompt Filter 결과에서 추출된 것을 사용.
            ## 가게 리스트를 만들어서 반환.    
            
            ### not mode[2] 이라는 소리는 Discount server까지의 넘어갈 필요가 없다는 것이므로 여기서 종료.
            return 
        else:
            pass
            ## 위와 같은 구현을 할 건데 다음 모드로 넘어갈 결과값을 구현하면 됨.
        
        ## output
        ## stores: 가게 리스트
        ## reviews: 가게 리뷰 리스트 (추후 RAG용)
        mcp_results["location_server"] = {
            "stores": stores,
            "reviews": reviews
        }
        
       
        
        
        # 3. DiscountServer (LocationServer 결과 + 사용자 프로필 사용)
        print(f"\n[3/6] 💰 DiscountServer 호출 중...")
        if mode[2] and not mode[3]:
            
            discount_result = await self.discount_server.get_discounts(
                stores=stores,
                user_profile=user_profile
            )
        
            ### not mode[3] 이라는 소리는 Recommendation server까지의 넘어갈 필요가 없다는 것이므로 여기서 종료.
            return 
        else:
            pass
            ## 위와 같은 구현을 할 건데 다음 모드로 넘어갈 결과값을 구현하면 됨.
            
        ## output
        ## discounts_by_store: 가게별 할인 정보
        
        
        
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
        
        ### output
        ### recommendations: 추천 결과 리스트 (할인율 순, 거리순)
        mcp_results["recommendation_server"] = {
            "recommendations": recommendation_result
        }
        
        
        ####### 아래는 RAG용 이니까 신경 X ##########
        # RAG (벡터 DB 생성 및 검색) - 스텁
        if mode[4]:
            print(f"\n[6/6] 🔍 RAG 처리 중...")
            rag_result = self.rag_pipeline.process(
                user_query=user_query,
                mcp_results=mcp_results,
                top_k=3,
                session_id=user_id,
                user_profile=user_profile
            )
            print(f"✅ RAG 처리 완료 (스텁 모드)")
            
            # [4단계] OpenAI LLM 호출 (실제 구현)
            print(f"\n🤖 OpenAI LLM 호출 중...")
            if self.openai_available:
                response = await self._call_openai_llm(
                    user_query=user_query,
                    llm_context=rag_result["llm_context"],
                    filter_result=filter_result,
                    user_profile=user_profile
                )
                print(f"✅ LLM 응답 생성 완료")
            else:
                response = rag_result.get("fallback_answer", "LLM 응답을 생성할 수 없습니다.")
            
            print("\n" + "="*60)
            print(f"✅ 쿼리 처리 완료")
            print("="*60 + "\n")
            
            return {
                "success": True,
                "query": user_query,
                "response": response,
                "mcp_results": mcp_results,
                "rag_result": rag_result
            }
        
    
    async def _call_openai_llm(
        self,
        user_query: str,
        llm_context: str,
        filter_result: Optional[Dict[str, Any]],
        user_profile: Dict[str, Any]
    ) -> str:
        """
        OpenAI LLM 호출 (OpenAI 공식 문서 기준)
        
        Args:
            user_query: 사용자 질문
            llm_context: RAG로 생성된 컨텍스트
            filter_result: Prompt Filter 결과
        
        Returns:
            LLM 생성 응답
        """
        try:
            keywords = filter_result.get("keywords") if filter_result else None
            keyword_text = ""
            if keywords:
                place = keywords.get("place_type")
                attributes = ", ".join(keywords.get("attributes", []))
                location = keywords.get("location")
                keyword_text = f"키워드: 장소={place}, 속성={attributes}, 지역={location}"
            
            profile_desc = []
            telco = user_profile.get("telco")
            cards = ", ".join(user_profile.get("cards", []))
            memberships = ", ".join(user_profile.get("memberships", []))
            if telco:
                profile_desc.append(f"통신사 {telco}")
            if cards:
                profile_desc.append(f"카드 {cards}")
            if memberships:
                profile_desc.append(f"멤버십 {memberships}")
            profile_text = ", ".join(profile_desc)
            
            system_message = (
                "당신은 위치 기반 맛집/카페 추천 비서입니다. "
                "사용자가 실제로 받을 수 있는 할인 혜택과 리뷰 분위기를 우선적으로 안내하세요. "
                "제공된 컨텍스트 밖의 정보는 추측하지 마세요."
            )
            if profile_text:
                system_message += f" 사용자 프로필: {profile_text}."
            if keyword_text:
                system_message += f" {keyword_text}."
            
            messages = [
                {"role": "system", "content": system_message},
                {
                    "role": "system",
                    "content": f"""[검색된 정보]
{llm_context}

[지침]
- 위 검색된 정보를 우선적으로 활용하여 답변하세요.
- 정보에 없는 내용은 추측하지 말고 "정보가 없습니다"라고 답변하세요.
- 할인 정보가 있다면 명확하게 강조하세요.
- 거리 정보가 있다면 함께 안내하세요.
- 친근하고 도움이 되는 톤으로 작성하세요.""",
                },
            ]
            if filter_result:
                messages.append(
                    {
                        "role": "system",
                        "content": f"추가 참조: {json.dumps(filter_result, ensure_ascii=False)}",
                    }
                )
            
            # 3. User Message: 사용자 질문
            messages.append({
                "role": "user",
                "content": user_query
            })
            
            # OpenAI API 호출 (공식 문서 기준)
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo-1106",  # 최신 모델 (JSON mode 지원)
                messages=messages,
                temperature=0.7,  # 창의성 (0.0 ~ 2.0)
                max_tokens=800,   # 최대 토큰 수
                top_p=1.0,        # Nucleus sampling
                frequency_penalty=0.0,  # 반복 감소
                presence_penalty=0.0,   # 주제 다양성
                # response_format={"type": "text"}  # 또는 "json_object"
            )
            
            # 응답 추출
            assistant_message = response.choices[0].message.content
            
            # 토큰 사용량 로깅
            usage = response.usage
            print(f"💰 토큰 사용량: 입력 {usage.prompt_tokens}, 출력 {usage.completion_tokens}, 총 {usage.total_tokens}")
            
            return assistant_message
            
        except Exception as e:
            # 상세한 에러 처리
            error_type = type(e).__name__
            error_message = str(e)
            
            print(f"❌ OpenAI API 오류 [{error_type}]: {error_message}")
            
            # 사용자 친화적 에러 메시지
            if "rate_limit" in error_message.lower():
                return "⚠️ 일시적으로 요청이 많아 처리할 수 없습니다. 잠시 후 다시 시도해주세요."
            elif "invalid_api_key" in error_message.lower():
                return "⚠️ API 키가 유효하지 않습니다. 관리자에게 문의해주세요."
            elif "insufficient_quota" in error_message.lower():
                return "⚠️ API 사용량이 초과되었습니다. 관리자에게 문의해주세요."
            else:
                return f"⚠️ 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.\n(오류: {error_type})"
    
        
        return response


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
                    "cards": ["T-Lounge"]
                }
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
    
    # IP/포트 기반 접근 제어 미들웨어
    @app.middleware("http")
    async def access_control_middleware(request: Request, call_next):
        """IP/포트 기반 접근 제어"""
        # 개발자 모드가 활성화되어 있으면 모든 접근 허용
        if ACCESS_CONFIG.get("developer_mode", True):
            response = await call_next(request)
            return response
        
        # 클라이언트 IP 추출
        client_ip = request.client.host if request.client else "unknown"
        
        # IP 화이트리스트 체크
        if ACCESS_CONFIG.get("enable_ip_whitelist", False):
            allowed_ips = ACCESS_CONFIG.get("allowed_ips", [])
            if client_ip not in allowed_ips and "localhost" not in client_ip:
                return HTTPException(
                    status_code=403,
                    detail=f"접근이 거부되었습니다. 허용된 IP: {', '.join(allowed_ips)}"
                )
        
        # 포트 체크는 서버 시작 시점에만 가능하므로 여기서는 로깅만
        response = await call_next(request)
        return response
    
    # 정적 파일 서빙 (웹 UI)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # 웹 UI 라우트
    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        """웹 UI 홈페이지"""
        ui_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        if os.path.exists(ui_path):
            return FileResponse(ui_path)
        else:
            return HTMLResponse("""
            <html>
                <head><title>위치 기반 할인 서비스</title></head>
                <body>
                    <h1>위치 기반 할인 서비스 API</h1>
                    <p>웹 UI 파일을 찾을 수 없습니다. static/index.html 파일을 확인하세요.</p>
                    <p>API 엔드포인트: <a href="/ping">/ping</a></p>
                </body>
            </html>
            """)
    
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
            result = await llm_engine.process_query(
                user_query=request.query,
                latitude=request.latitude,
                longitude=request.longitude,
                user_id=request.user_id,
                user_profile=request.user_profile, ## user_profile 넘겨받는 부분 추가
                mode=[1,0,0,0,0]  # prompt filter 까지만 테스트
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
        default="145.0.0.0",
        help="API 서버 호스트 (기본: 145.0.0.0)"
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
