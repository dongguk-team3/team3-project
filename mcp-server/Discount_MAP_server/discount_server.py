#MCP 진입점
# discount_server.py
"""
할인 정보 MCP 서버 진입점.

역할:
- MCP 프로토콜로 stdin/stdout에서 요청을 받는다.
- 도구(tool)로 get_discounts_for_stores를 노출한다.
- 내부적으로 DiscountService를 호출해서 실제 할인 정보를 가져오고,
  결과를 JSON 문자열로 돌려준다.
"""

import asyncio
import json
from typing import Dict, Any, List

from mcp.server import Server          # 사용 중인 MCP 라이브러리에 맞게 import 경로 확인
from mcp.server.stdio import stdio_server

from db.connection import init_db_pool, close_db_pool
from services.discount_service import DiscountService


# MCP 서버 인스턴스 (이름은 알아보기 쉽게 아무거나)
server = Server("DiscountMCPServer")

# 비즈니스 로직 담당 서비스 인스턴스
discount_service = DiscountService()


@server.tool(
    name="get_discounts_for_stores",
    description="사용자 프로필과 매장 이름 목록을 받아 매장별 할인 정보를 JSON으로 반환합니다."
)
async def get_discounts_for_stores(
    userProfile: Dict[str, Any],
    stores: List[str],
) -> str:
    """
    MCP Client 쪽에서 호출하는 도구 함수.

    파라미터:
    - userProfile: { userId, telco, memberships[], cards[], affiliations[] }
    - stores: ["스타벅스 동국대점", "이디야커피 충무로역점", ...]

    반환:
    - JSON 문자열 (DiscountService 결과 딕셔너리를 json.dumps 한 값)
    """
    result_dict = await discount_service.get_discounts_for_stores(
        user_profile=userProfile,
        store_names=stores,
    )
    return json.dumps(result_dict, ensure_ascii=False)


async def main() -> None:
    """
    서버 실행 진입점.

    1) DB 커넥션 풀 초기화
    2) stdio 기반 MCP 서버 실행
    3) (종료 시) 커넥션 풀 정리
    """
    await init_db_pool()

    async with stdio_server() as (read, write):
        await server.run(read, write)

    await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
