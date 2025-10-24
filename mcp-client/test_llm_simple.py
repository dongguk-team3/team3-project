"""
간단한 LLM 테스트
"""

import asyncio
from mcp_client import LLMEngine

async def test():
    engine = LLMEngine()
    
    print("=" * 60)
    print("🤖 LLM 엔진 간단 테스트")
    print("=" * 60)
    
    # 테스트 1: 정상 질문
    print("\n[테스트 1] 강남역 근처 음식점 추천해줘")
    result = await engine.process_query(
        user_query="강남역 근처 음식점 추천해줘",
        latitude=37.5665,
        longitude=126.9780
    )
    
    print(f"\n✅ 응답:")
    print(result["response"])
    
    print(f"\n📊 MCP 결과:")
    if "location" in result.get("mcp_results", {}):
        stores = result["mcp_results"]["location"].get("stores", [])
        print(f"  - 검색된 상점: {len(stores)}개")
        if stores:
            print(f"  - 첫 번째 상점: {stores[0].get('name', '?')}")
    
    # 테스트 2: 차단되어야 하는 질문
    print("\n" + "=" * 60)
    print("\n[테스트 2] 파이썬 코드 작성해줘 (차단되어야 함)")
    result2 = await engine.process_query(
        user_query="파이썬 코드 작성해줘",
        latitude=37.5665,
        longitude=126.9780
    )
    
    print(f"\n{'✅' if not result2['success'] else '❌'} 응답:")
    print(result2["response"])
    
    print("\n" + "=" * 60)

asyncio.run(test())

