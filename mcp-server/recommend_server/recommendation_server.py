"""
추천/할인 계산 MCP 서버 진입점

역할:
- MCP 프로토콜로 stdin/stdout에서 요청을 받는다.
- 도구(tool)로 calculate_recommendations를 노출한다.
- 내부적으로 recommender 모듈을 호출해서 할인 계산/정렬을 수행하고,
  결과를 JSON 문자열로 돌려준다.
"""

import asyncio
import json
from typing import Dict, Any, List

from mcp.server import Server
from mcp.server.stdio import stdio_server

from models import RecommendationRequest
from recommender import generate_recommendations
from integration import get_location_based_recommendations

# MCP 서버 인스턴스
server = Server("RecommendationMCPServer")


@server.tool(
    name="calculate_recommendations",
    description=(
        "매장별 할인 정보를 받아서 사용자에게 적용 가능한 할인을 계산, 필터링, 정렬하여 반환합니다. "
        "입력으로 매장 목록과 각 매장의 할인 정보를 받고, "
        "출력으로 적용 가능한 할인(applicableDiscounts)과 기타 할인(otherDiscounts)을 금액 순으로 정렬하여 반환합니다."
    )
)
async def calculate_recommendations(
    results: List[Dict[str, Any]],
    channel: str = "OFFLINE",
    orderAmount: int = 15000,
) -> str:
    """
    MCP Client 쪽에서 호출하는 도구 함수.
    
    파라미터:
    - results: [
        {
          "target": {"externalBranchId": "...", "matchedBranchId": 123},
          "merchant": {"merchantId": 101, "merchantName": "스타벅스"},
          "discounts": [
            {
              "discountId": 9001,
              "discountName": "T 멤버십 할인",
              "provider": {"providerName": "SKT", "providerType": "TELCO"},
              "shape": {"kind": "PER_UNIT", "params": {...}},
              "constraints": {...},
              "appliedByUserProfile": {...}
            }
          ]
        }
      ]
    - channel: 결제 채널 ("OFFLINE" 또는 "ONLINE")
    - orderAmount: 주문 금액 (기본값: 15000원)
    
    반환:
    - JSON 문자열 (RecommendationResponse를 json으로 직렬화한 값)
    """
    # Pydantic 모델로 변환하여 검증
    try:
        request = RecommendationRequest(
            results=results,
            channel=channel,
            orderAmount=orderAmount
        )
        
        # 추천 계산 실행
        response = generate_recommendations(request)
        
        # JSON 문자열로 반환
        return json.dumps(
            response.model_dump(mode='json'),
            ensure_ascii=False,
            indent=2
        )
    
    except Exception as e:
        # 에러 발생 시 에러 메시지 반환
        error_response = {
            "success": False,
            "message": f"추천 계산 중 오류 발생: {str(e)}",
            "recommendations": [],
            "total": 0
        }
        return json.dumps(error_response, ensure_ascii=False)


@server.tool(
    name="recommend_from_location",
    description=(
        "사용자 위치(위도/경도)를 기반으로 근처 매장을 검색하고, "
        "각 매장의 할인 정보를 조회하여 적용 가능한 할인을 계산 및 정렬하여 반환합니다. "
        "위치 정보(거리, 주소 등)가 추가된 추천 결과를 제공합니다."
    )
)
async def recommend_from_location(
    latitude: float,
    longitude: float,
    userProfile: Dict[str, Any] = None,
    category: str = "음식점",
    radius: int = 1000,
    channel: str = "OFFLINE",
    orderAmount: int = 15000,
    storeTypeFilter: str = "ALL",
) -> str:
    """
    위치 기반 할인 추천 통합 도구.
    
    파라미터:
    - latitude: 사용자 위치의 위도
    - longitude: 사용자 위치의 경도
    - userProfile: 사용자 프로필 (선택)
      {
        "userId": "user123",
        "telco": "SKT",
        "memberships": ["CJ ONE"],
        "cards": ["신한카드 YOLO Tasty"],
        "affiliations": []
      }
    - category: 검색할 카테고리 (기본: "음식점")
    - radius: 검색 반경 (미터, 기본: 1000)
    - channel: 결제 채널 ("OFFLINE" 또는 "ONLINE", 기본: "OFFLINE")
    - orderAmount: 주문 금액 (기본: 15000원)
    - storeTypeFilter: 매장 타입 필터 ("ALL", "FRANCHISE", "INDEPENDENT", 기본: "ALL")
    
    반환:
    - JSON 문자열 (위치 정보가 포함된 추천 결과)
    
    처리 플로우:
    1. Location_server 호출 → 근처 매장 검색
    2. Discount_MAP_server 호출 → 매장별 할인 정보 조회
    3. 추천 엔진 실행 → 할인 계산/필터링/정렬
    4. 매장 타입 필터링 적용
    5. 위치 정보 추가 → 최종 결과 반환
    """
    try:
        result = await get_location_based_recommendations(
            latitude=latitude,
            longitude=longitude,
            user_profile=userProfile,
            category=category,
            radius=radius,
            channel=channel,
            order_amount=orderAmount,
            store_type_filter=storeTypeFilter
        )
        
        return json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    
    except Exception as e:
        error_response = {
            "success": False,
            "message": f"위치 기반 추천 중 오류 발생: {str(e)}",
            "recommendations": [],
            "total": 0
        }
        return json.dumps(error_response, ensure_ascii=False)


async def main() -> None:
    """
    서버 실행 진입점.
    
    1) stdio 기반 MCP 서버 실행
    2) 요청 대기 및 처리
    """
    print("🚀 추천 계산 MCP 서버 시작", flush=True)
    print("📌 Tool: calculate_recommendations", flush=True)
    print("📌 통신: stdin/stdout (MCP Protocol)", flush=True)
    print("="*60, flush=True)
    
    async with stdio_server() as (read, write):
        await server.run(read, write)


if __name__ == "__main__":
    asyncio.run(main())


