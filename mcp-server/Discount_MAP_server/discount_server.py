# discount_server.py
"""
할인 정보 MCP 서버 진입점.

역할:
- MCP 프로토콜로 stdin/stdout에서 요청을 받는다.
- tools/list, tools/call 요청에 응답해
  get_discounts_for_stores 라는 도구를 노출한다.
"""

import asyncio
import json
from typing import Dict, Any, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types  # Tool, TextContent 등 스키마 타입

from db.connection import init_db_pool, close_db_pool, is_db_pool_initialized
from services.discount_service import DiscountService


# MCP 서버 인스턴스
server = Server("DiscountMCPServer")

# 비즈니스 로직 서비스
discount_service = DiscountService()


# -------------------------------------------------------.
# 1) 내부 비즈니스 함수 (예전 @server.tool 이 달려 있던 함수)
# -------------------------------------------------------
async def get_discounts_for_stores(
    userProfile: Dict[str, Any],
    stores: List[str],
) -> Dict[str, Any]:
    """
    실제로 DiscountService 를 호출하는 내부 함수.
    (MCP tools/call 핸들러에서 이 함수를 호출한다.)
    """
    result_dict = await discount_service.get_discounts_for_stores(
        user_profile=userProfile,
        store_names=stores,
    )
    return result_dict


# -------------------------------------------------------
# 2) tools/list 핸들러: 사용 가능한 도구 목록 정의
# -------------------------------------------------------
@server.list_tools()
async def list_tools() -> List[types.Tool]:
    """
    MCP 클라이언트에게 노출할 도구 목록.
    여기서 정의한 name 이 tools/call 의 name 과 매칭된다.
    """
    return [
        types.Tool(
            name="get_discounts_for_stores",
            description=(
                "사용자 프로필과 매장 이름 목록을 받아 "
                "매장별 할인 정보를 JSON 문자열로 반환합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "userProfile": {
                        "type": "object",
                        "description": (
                            "사용자 프로필 정보. "
                            "{ userId, telco, memberships[], cards[], affiliations[] } 형태"
                        ),
                    },
                    "stores": {
                        "type": "array",
                        "description": "매장 이름 문자열 배열",
                        "items": {"type": "string"},
                    },
                },
                "required": ["userProfile", "stores"],
            },
            # outputSchema 는 생략 가능 (텍스트 하나 반환으로 충분하면)
        )
    ]


# -------------------------------------------------------
# 3) tools/call 핸들러: 실제 도구 호출 처리
# -------------------------------------------------------
@server.call_tool()
async def call_tool(
    name: str,
    arguments: Dict[str, Any],
) -> List[types.TextContent]:

    # -----------------------------------------------------
    # 🔥 DB 풀 자동 관리 로직 (중요)
    # -----------------------------------------------------
    created_pool_here = False
    if not is_db_pool_initialized():
        await init_db_pool()
        created_pool_here = True

    try:
        # -------------------------------------------------
        # 1) 툴 라우팅
        # -------------------------------------------------
        if name == "get_discounts_for_stores":
            user_profile = arguments.get("userProfile", {})
            stores = arguments.get("stores", [])

            result_dict = await get_discounts_for_stores(
                userProfile=user_profile,
                stores=stores,
            )

            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result_dict, ensure_ascii=False),
                )
            ]

        # -------------------------------------------------
        # 2) 라우팅 실패
        # -------------------------------------------------
        raise ValueError(f"Unknown tool name: {name}")

    finally:
        # -------------------------------------------------
        # 🔥 자동 관리: 여기서 만든 풀만 닫기
        # -------------------------------------------------
        if created_pool_here:
            await close_db_pool()


# -------------------------------------------------------
# 4) 서버 실행 진입점: stdio 기반 MCP 서버로 실행
# -------------------------------------------------------
async def main() -> None:
    """
    서버 실행 진입점.

    1) DB 커넥션 풀 초기화
    2) stdio 기반 MCP 서버 실행
    3) 종료 시 DB 커넥션 풀 정리
    """
    await init_db_pool()
    try:
        async with stdio_server() as (read, write):
            # initialization options 포함해서 run 호출하는 패턴이 많이 쓰인다.
            await server.run(
                read,
                write,
                server.create_initialization_options(),
            )
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
