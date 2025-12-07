"""
위치 기반 MCP Server
카카오맵 API 연동
"""

import asyncio
import sys
import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import aiohttp
import json

# location_server_config.py에서 네이버 설정 로드
from location_server_config import (
    NAVER_SEARCH_CLIENT_ID,
    NAVER_SEARCH_CLIENT_SECRET,
)

# query_to_naver.py에서 네이버 API 클라이언트 로드
from query_to_naver import (
    NaverPlaceAPIClient,
    QueryIntent,
    search_places,
    geocode_location,
)

# review_generator.py에서 리뷰 생성기 로드
from review_generator import ReviewGenerator


# MCP 서버 인스턴스 생성
app = Server("location-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 도구 목록 반환"""
    return [
        Tool(
            name="search_nearby_stores",
            description="주변 상점 검색 (테스트용 - 나중에 카카오맵 API 연동)",
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "위도"
                    },
                    "longitude": {
                        "type": "number",
                        "description": "경도"
                    },
                    "category": {
                        "type": "string",
                        "description": "카테고리 (예: 음식점, 카페)",
                        "default": "음식점"
                    }
                },
                "required": ["latitude", "longitude"]
            }
        ),
        Tool(
            name="search_fnb_with_reviews",
            description="사용자 위치 기반으로 근처 F&B 매장을 검색하고 각 매장의 리뷰 정보를 수집합니다",
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "사용자 위치의 위도"
                    },
                    "longitude": {
                        "type": "number",
                        "description": "사용자 위치의 경도"
                    },
                    "category": {
                        "type": "string",
                        "description": "검색할 F&B 카테고리 (예: 음식점, 카페, 레스토랑, 한식, 일식, 중식, 양식)",
                        "default": "음식점"
                    },
                    "radius": {
                        "type": "number",
                        "description": "검색 반경 (미터 단위, 기본 1000m)",
                        "default": 1000
                    },
                    "max_stores": {
                        "type": "number",
                        "description": "최대 검색할 매장 수 (기본 10개)",
                        "default": 10
                    },
                    "reviews_per_store": {
                        "type": "number",
                        "description": "각 매장당 수집할 리뷰 수 (기본 5개)",
                        "default": 5
                    }
                },
                "required": ["latitude", "longitude"]
            }
        ),
        Tool(
            name="get_store_info",
            description="특정 상점의 상세 정보 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "string",
                        "description": "상점 ID"
                    }
                },
                "required": ["store_id"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """도구 실행"""
    
    # 네이버 API 키 확인
    if not (NAVER_SEARCH_CLIENT_ID and NAVER_SEARCH_CLIENT_SECRET):
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "❌ NAVER_SEARCH_CLIENT_ID/SECRET가 설정되지 않았습니다.",
                "message": "location_server_config.py에서 API 키를 설정하세요."
            }, ensure_ascii=False, indent=2)
        )]
    
    if name == "search_nearby_stores":
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        category = arguments.get("category", "음식점")
        
        # 네이버 API를 사용하여 주변 매장 검색
        try:
            # 네이버 클라이언트 생성
            naver_client = NaverPlaceAPIClient(
                client_id=NAVER_SEARCH_CLIENT_ID,
                client_secret=NAVER_SEARCH_CLIENT_SECRET,
            )
            
            # QueryIntent 생성
            intent = QueryIntent(
                original_query=f"{category} 검색",
                place_type=category,
                attributes=[],
                location=None
            )
            
            # 지오코딩 (위도/경도가 있으면 사용)
            center = (lat, lon) if lat and lon else None
            
            # 네이버 API로 검색
            async with aiohttp.ClientSession() as session:
                result = await search_places(
                    naver_client=naver_client,
                    intent=intent,
                    center=center
                )
                        
                        # 결과 변환
            stores_list = result.get("stores", [])
            
            final_result = {
                            "query": {
                                "latitude": lat,
                                "longitude": lon,
                                "category": category
                            },
                "total_count": len(stores_list),
                "stores": stores_list,
                "message": "✅ 네이버 API로 주변 매장 검색 완료"
                        }
                        
                        return [TextContent(
                            type="text",
                text=json.dumps(final_result, ensure_ascii=False, indent=2)
                        )]
                        
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"❌ 오류 발생: {str(e)}"
                }, ensure_ascii=False, indent=2)
            )]
    
    elif name == "search_fnb_with_reviews":
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        category = arguments.get("category", "음식점")
        radius = arguments.get("radius", 1000)
        max_stores = arguments.get("max_stores", 10)
        reviews_per_store = arguments.get("reviews_per_store", 5)
        
        # 네이버 API를 사용하여 F&B 매장 검색
        try:
            # 네이버 클라이언트 생성
            naver_client = NaverPlaceAPIClient(
                client_id=NAVER_SEARCH_CLIENT_ID,
                client_secret=NAVER_SEARCH_CLIENT_SECRET,
            )
            
            # QueryIntent 생성
            intent = QueryIntent(
                original_query=f"{category} 검색",
                place_type=category,
                attributes=[],
                location=None
            )
            
            # 지오코딩 (위도/경도가 있으면 사용)
            center = (lat, lon) if lat and lon else None
            
            # 네이버 API로 검색
            async with aiohttp.ClientSession() as session:
                result = await search_places(
                    naver_client=naver_client,
                    intent=intent,
                    center=center
                )
                        
            # nearby_reviews.py 형식으로 변환 (이미 search_places에서 변환됨)
            stores_list = result.get("stores", [])
            reviews_dict = result.get("reviews", {})
                        
            # 최종 결과 구성
            final_result = {
                            "query": {
                                "latitude": lat,
                                "longitude": lon,
                                "category": category,
                                "radius": radius
                            },
                "total_stores": len(stores_list),
                "total_reviews": sum(len(r) for r in reviews_dict.values()),
                "stores": stores_list,
                "reviews": reviews_dict,
                "message": "✅ 네이버 API로 F&B 매장 검색 및 리뷰 수집 완료"
                        }
                        
            print(f"[DEBUG] 완료: {final_result['total_stores']}개 매장, {final_result['total_reviews']}개 리뷰", file=sys.stderr)
                        
                        return [TextContent(
                            type="text",
                text=json.dumps(final_result, ensure_ascii=False, indent=2)
                        )]
                        
        except Exception as e:
            import traceback
            error_msg = f"❌ 오류 발생: {str(e)}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": error_msg,
                    "traceback": traceback.format_exc()
                }, ensure_ascii=False, indent=2)
            )]
    
    elif name == "get_store_info":
        store_id = arguments.get("store_id")
        
        # 카카오맵 API로는 상세 정보를 store_id만으로 조회할 수 없음
        # 대신 place_url을 통해 웹페이지로 이동하거나
        # 별도의 할인 정보 DB를 구축해야 함
        
        result = {
            "store_id": store_id,
            "message": "ℹ️  카카오맵 API는 ID로 직접 조회를 지원하지 않습니다.",
            "suggestion": "search_nearby_stores로 검색 후 place_url을 사용하거나, 별도 할인 정보 DB 연동이 필요합니다.",
            "next_steps": [
                "1. 할인 정보 수집 MCP 서버 개발",
                "2. 자체 DB에 store_id와 할인 정보 매핑"
            ]
        }
        
        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]
    
    else:
        return [TextContent(
            type="text",
            text=f"❌ 알 수 없는 도구: {name}"
        )]


async def main():
    """서버 실행"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

