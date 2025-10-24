"""
keywords.txt에 추가된 키워드 테스트
"""

from prompt_filter import LLMPipeline

# 파이프라인 초기화
pipeline = LLMPipeline()

# 새로 추가된 키워드 테스트
test_cases = [
    # 음식 카테고리 (새로 추가됨)
    ("삼겹살 맛집 추천해줘", True),
    ("곱창 집 어디 좋아?", True),
    ("떡볶이 먹고 싶어", True),
    ("라면 맛있는 곳", True),
    ("파스타 맛집", True),
    
    # 위치 관련 (새로 추가됨)
    ("강남구 음식점", True),
    ("역삼동 근처", True),
    
    # 할인 관련 (새로 추가됨)
    ("기프티콘 사용 가능한 곳", True),
    ("캐시백 받을 수 있어?", True),
    
    # 기타 (새로 추가됨)
    ("데이트하기 좋은 카페", True),
    ("회식 장소 추천", True),
    ("예약 가능한 식당", True),
    ("주차 가능한 음식점", True),
    
    # 차단 키워드 (새로 추가됨)
    ("비트코인 투자 어때?", False),
    ("도박 사이트 추천", False),
    ("의사 선생님 추천해줘", False),
    ("파이썬 개발 어떻게 해?", False),
    
    # 기존 테스트
    ("강남역 맛집", True),
    ("정치 뉴스 알려줘", False),
]

print("=" * 60)
print("keywords.txt 키워드 테스트")
print("=" * 60)

passed = 0
failed = 0

for query, expected_success in test_cases:
    result = pipeline.process(query)
    actual_success = result["success"]
    
    if actual_success == expected_success:
        status = "✅ PASS"
        passed += 1
    else:
        status = "❌ FAIL"
        failed += 1
    
    print(f"\n{status} | {query}")
    if actual_success:
        print(f"  → 검증 통과")
    else:
        print(f"  → 차단: {result['message']}")

print("\n" + "=" * 60)
print(f"테스트 결과: {passed}개 성공, {failed}개 실패")
print("=" * 60)

