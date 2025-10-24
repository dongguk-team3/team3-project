"""
OpenAI + RAG 통합 테스트
"""

import asyncio
import sys

# RAG 모듈 테스트
print("=" * 60)
print("1️⃣ RAG 모듈 테스트")
print("=" * 60)

from rag_module import RAGPipeline

rag = RAGPipeline(use_openai_embeddings=False)

# Mock MCP 결과
mcp_results = {
    "location": {
        "stores": [
            {"id": "001", "name": "맛있는집", "address": "강남역 근처", "distance": 100, "category": "한식"},
            {"id": "002", "name": "카페A", "address": "강남역", "distance": 200, "category": "카페"}
        ]
    }
}

user_query = "강남역 근처 맛집 추천해줘"
rag_result = rag.process(user_query, mcp_results, top_k=2)

print(f"\n[사용자 질문] {user_query}")
print(f"\n[벡터 DB 생성]")
print(f"  - {rag_result['create_result']['message']}")
print(f"  - 문서 수: {rag_result['create_result']['total_documents']}")
print(f"\n[벡터 검색]")
print(f"  - {rag_result['search_result']['message']}")
print(f"  - 검색된 문서: {len(rag_result['search_result']['results'])}개")
print(f"\n[LLM 컨텍스트]")
print(rag_result['llm_context'])

# LLM 엔진 테스트
print("\n" + "=" * 60)
print("2️⃣ LLM 엔진 테스트")
print("=" * 60)

from mcp_client import LLMEngine, OPENAI_API_KEY, OPENAI_AVAILABLE

async def test_llm_engine():
    engine = LLMEngine()
    
    print(f"\n[OpenAI 상태]")
    print(f"  - 라이브러리 설치: {OPENAI_AVAILABLE}")
    print(f"  - API 키 설정: {'✅ 설정됨' if OPENAI_API_KEY else '❌ 미설정'}")
    print(f"  - 사용 가능: {'✅ 가능' if engine.openai_available else '❌ 불가능'}")
    
    # 테스트 질문
    test_query = "강남역 근처 카페 추천해줘"
    print(f"\n[테스트 질문] {test_query}")
    print(f"[처리 중...]")
    
    result = await engine.process_query(
        user_query=test_query,
        latitude=37.5665,
        longitude=126.9780,
        user_id="test_user"
    )
    
    if result["success"]:
        print(f"\n✅ 성공")
        print(f"\n[LLM 응답]")
        print(result["response"])
        
        print(f"\n[RAG 결과]")
        print(f"  - {result['rag_result']['create_result']['message']}")
        print(f"  - {result['rag_result']['search_result']['message']}")
    else:
        print(f"\n❌ 실패: {result['error']}")

asyncio.run(test_llm_engine())

print("\n" + "=" * 60)
print("테스트 완료")
print("=" * 60)

