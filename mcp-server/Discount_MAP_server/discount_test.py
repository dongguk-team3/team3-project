# discount_test.py
import asyncio
import json
from pathlib import Path

import discount_server
from mcp import types


OUTPUT_DIR = Path("tests/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    # 1) mock user_profile / stores 준비
    user_profile = {
        "userId": "user123",
        "telco": "SKT",
        "memberships": ["CJ ONE", "해피포인트"],
        "cards": ["신한카드 YOLO Tasty"],
        "affiliations": ["동국대학교"],
    }
    stores = [
        "스타벅스 동국대점",
        "이디야커피 충무로역점",
    ]

    # 2) discount_server의 MCP tool(call_tool) 직접 호출
    #    ⚠️ init_db_pool/close_db_pool는 여기서 호출할 필요 없음
    #       -> call_tool 안에서 이미 lazy init/close 처리함
    contents = await discount_server.call_tool(
        name="get_discounts_for_stores",
        arguments={
            "userProfile": user_profile,
            "stores": stores,
        },
    )

    if not contents:
        raise RuntimeError("call_tool이 비어 있는 리스트를 반환했습니다.")

    content = contents[0]

    # 타입 체크 (디버깅용)
    if not isinstance(content, types.TextContent):
        raise TypeError(f"예상과 다른 타입 반환: {type(content)}")

    # 3) JSON 파싱
    result = json.loads(content.text)

    # 4) 결과를 파일로 저장
    out_path = OUTPUT_DIR / "discount_result.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] JSON 결과가 저장되었습니다: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
