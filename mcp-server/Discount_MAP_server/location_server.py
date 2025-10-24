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

# location_server_config.py에서 카카오맵 설정 로드
from location_server_config import (
    KAKAO_REST_API_KEY,
    KAKAO_LOCAL_SEARCH_URL,
    KAKAO_CATEGORY_SEARCH_URL,
    validate_api_keys
)


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
    
    # API 키 확인
    if not KAKAO_REST_API_KEY:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "❌ KAKAO_REST_API_KEY가 설정되지 않았습니다.",
                "message": "config.py에서 API 키를 설정하세요."
            }, ensure_ascii=False, indent=2)
        )]
    
    if name == "search_nearby_stores":
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        category = arguments.get("category", "음식점")
        
        # 카카오맵 API 호출
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"
                }
                params = {
                    "query": category,
                    "x": lon,  # 경도
                    "y": lat,  # 위도
                    "radius": 1000,  # 1km 반경
                    "size": 15  # 최대 15개
                }
                
                async with session.get(
                    KAKAO_LOCAL_SEARCH_URL,
                    headers=headers,
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # 디버깅: API 응답 확인
                        import sys
                        print(f"[DEBUG] 카카오맵 API 응답: {len(data.get('documents', []))}개 문서", file=sys.stderr)
                        print(f"[DEBUG] Meta: {data.get('meta', {})}", file=sys.stderr)
                        
                        # 결과 변환
                        stores = []
                        for doc in data.get("documents", []):
                            stores.append({
                                "id": doc.get("id"),
                                "name": doc.get("place_name"),
                                "category": doc.get("category_name"),
                                "distance": int(doc.get("distance", 0)),
                                "address": doc.get("address_name"),
                                "road_address": doc.get("road_address_name"),
                                "phone": doc.get("phone"),
                                "place_url": doc.get("place_url"),
                                "latitude": float(doc.get("y")),
                                "longitude": float(doc.get("x"))
                            })
                        
                        result = {
                            "query": {
                                "latitude": lat,
                                "longitude": lon,
                                "category": category
                            },
                            "total_count": data.get("meta", {}).get("total_count", 0),
                            "stores": stores,
                            "message": "✅ 카카오맵 API 실제 데이터"
                        }
                        
                        return [TextContent(
                            type="text",
                            text=json.dumps(result, ensure_ascii=False, indent=2)
                        )]
                    else:
                        error_text = await response.text()
                        return [TextContent(
                            type="text",
                            text=json.dumps({
                                "error": f"❌ API 호출 실패: {response.status}",
                                "details": error_text
                            }, ensure_ascii=False, indent=2)
                        )]
                        
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"❌ 오류 발생: {str(e)}"
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

