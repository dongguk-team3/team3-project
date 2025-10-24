"""
새로운 아키텍처 테스트 스크립트
2025-10-12: user_id 필수, 모든 서버 항상 호출
"""

import asyncio
import sys
import os

# mcp_client를 import하기 위한 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import LLMEngine


async def test_new_architecture():
    """새로운 아키텍처 테스트"""
    print("="*80)
    print("🧪 새로운 아키텍처 테스트 시작")
    print("="*80)
    
    # LLM 엔진 초기화
    llm_engine = LLMEngine()
    
    # 테스트 케이스
    test_cases = [
        {
            "name": "기본 추천 요청",
            "query": "강남역 근처 맛집 추천해줘",
            "user_id": "test_user_001",
            "latitude": 37.4979,
            "longitude": 127.0276
        },
        {
            "name": "할인 강조 요청",
            "query": "할인 많이 받을 수 있는 카페 알려줘",
            "user_id": "test_user_002",
            "latitude": 37.5665,
            "longitude": 126.9780
        },
        {
            "name": "카테고리 지정 요청",
            "query": "일식집 추천해줘",
            "user_id": "test_user_003",
            "latitude": 37.5172,
            "longitude": 127.0473
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n\n{'='*80}")
        print(f"테스트 {i}/{len(test_cases)}: {test_case['name']}")
        print(f"{'='*80}\n")
        
        try:
            result = await llm_engine.process_query(
                user_query=test_case["query"],
                latitude=test_case["latitude"],
                longitude=test_case["longitude"],
                user_id=test_case["user_id"],
                context=None
            )
            
            if result["success"]:
                print("\n✅ 테스트 성공!")
                print(f"\n📝 최종 응답:")
                print("-"*80)
                print(result["response"])
                print("-"*80)
                
                # MCP 결과 요약
                print(f"\n📊 MCP Servers 결과 요약:")
                
                # Pattern
                pattern = result["mcp_results"].get("pattern", {})
                if pattern:
                    profile = pattern.get("profile", {})
                    prefs = pattern.get("preferences", {})
                    print(f"  [Pattern] 통신사: {profile.get('telecom')}, "
                          f"선호: {prefs.get('preferred_categories', [])[:2]}")
                
                # Location
                location = result["mcp_results"].get("location", {})
                stores_count = len(location.get("stores", []))
                print(f"  [Location] 검색된 상점: {stores_count}개")
                
                # Discount
                discount = result["mcp_results"].get("discount", {})
                discounts_count = len(discount.get("discounts_by_store", {}))
                print(f"  [Discount] 할인 분석: {discounts_count}개 가게")
                
                # Recommendation
                recommendation = result["mcp_results"].get("recommendation", {})
                recs = recommendation.get("recommendations", [])
                print(f"  [Recommendation] Top-{len(recs)} 추천 생성")
                
                if recs:
                    top1 = recs[0]
                    print(f"    → 1순위: {top1['store']['name']} "
                          f"(점수: {top1['score']:.2f})")
                
            else:
                print(f"\n❌ 테스트 실패: {result.get('error')}")
        
        except Exception as e:
            print(f"\n❌ 예외 발생: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n\n{'='*80}")
    print("✅ 모든 테스트 완료!")
    print(f"{'='*80}")


async def test_missing_user_id():
    """user_id 누락 시 에러 확인"""
    print("\n\n" + "="*80)
    print("🧪 user_id 필수 검증 테스트")
    print("="*80)
    
    llm_engine = LLMEngine()
    
    try:
        # user_id 없이 호출 시도 (에러 발생해야 함)
        result = await llm_engine.process_query(
            user_query="맛집 추천해줘",
            latitude=37.5665,
            longitude=126.9780,
            user_id=None,  # ← 에러 발생!
            context=None
        )
        
        print("❌ user_id가 None인데도 통과됨! (버그)")
        
    except TypeError as e:
        print(f"✅ 예상대로 TypeError 발생: {e}")
        print("   → user_id는 필수 파라미터입니다.")
    
    except Exception as e:
        print(f"⚠️  예상치 못한 에러: {e}")


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║      🧪 새로운 아키텍처 테스트                              ║
    ║                                                              ║
    ║      변경 사항:                                              ║
    ║      - user_id 필수화                                        ║
    ║      - 모든 MCP Server 항상 호출                             ║
    ║      - 순차적 데이터 파이프라인                              ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    # 테스트 실행
    asyncio.run(test_new_architecture())
    
    # user_id 검증 테스트
    # asyncio.run(test_missing_user_id())  # 필요 시 주석 해제
    
    print("\n✅ 모든 테스트 시퀀스 완료!\n")



