# recommendation_server.py (새로운 우선순위 로직 버전)

def calculate_personalized_recommendations(stores_data, user_profile):
    """
    사용자 프로필을 기반으로 우선순위 규칙에 따라 가게를 추천하는 함수
    """
    if not stores_data:
        return []

    user_benefits = set(user_profile.get('cards', [])) | {user_profile.get('telecom')} | set(user_profile.get('memberships', []))
    usage_frequency = user_profile.get('usage_frequency', {})

    group_A = []  # 사용자가 혜택을 받을 수 있는 가게 그룹
    group_B = []  # 사용자가 혜택을 받을 수 없는 가게 그룹

    # 1단계: 가게 그룹 나누기
    for store in stores_data:
        usable_discounts = [
            d for d in store.get('discounts', []) if d['name'] in user_benefits
        ]

        if usable_discounts:
            # 받을 수 있는 혜택 중 가장 좋은 혜택(대표 혜택)을 찾음
            best_user_benefit = max(usable_discounts, key=lambda d: d['rate'])
            store['representative_benefit'] = best_user_benefit
            group_A.append(store)
        else:
            if store.get('discounts'):
                # 받을 수 없지만, 가게가 제공하는 가장 좋은 혜택을 대표로 설정
                store['representative_benefit'] = max(store.get('discounts', []), key=lambda d: d['rate'])
            else: # 할인 정보가 아예 없는 가게
                store['representative_benefit'] = {'name': '할인 없음', 'rate': 0}
            group_B.append(store)

    # 2단계: A그룹 내부 정렬 (할인율 -> 사용빈도 -> 거리)
    # lambda x: (우선순위1, 우선순위2, ...) 와 같이 튜플을 사용하면 다중 조건으로 정렬 가능
    # - (마이너스)를 붙이면 내림차순(높은게 먼저) 정렬이 됨
    group_A.sort(key=lambda s: (
        -s['representative_benefit']['rate'],  # 1. 할인율 높은 순
        -usage_frequency.get(s['representative_benefit']['name'], 0), # 2. 사용빈도 높은 순
        s['distance']  # 3. 거리 가까운 순
    ))

    # 3단계: B그룹 내부 정렬 (할인율 -> 거리)
    group_B.sort(key=lambda s: (
        -s['representative_benefit']['rate'], # 1. 할인율 높은 순
        s['distance'] # 2. 거리 가까운 순
    ))

    # 4단계: 최종 결과 합치기
    final_recommendations = group_A + group_B
    return final_recommendations

# --- 테스트를 위한 예제 데이터 ---
if __name__ == "__main__":
    
    # [입력 데이터 1] 사용자 프로필 정의
    # 'usage_frequency'는 가상의 사용 빈도 점수입니다. 높을수록 자주 쓴다는 의미.
    sample_user_profile = {
        'cards': ['신한카드', '현대카드'],
        'telecom': 'SKT',
        'memberships': ['CJ ONE'],
        'usage_frequency': {
            'SKT': 10,
            '신한카드': 8,
            '현대카드': 3,
            'CJ ONE': 5,
            'KT': 0 # 사용자가 안쓰는 항목은 점수가 0
        }
    }

    # [입력 데이터 2] 가게 목록 정의
    # 이제 각 가게는 'discounts' 라는 리스트를 가집니다.
    sample_stores = [
        {'id': 1, 'name': 'A식당', 'distance': 200, 'rating': 4.5, 'discounts': [
            {'name': 'SKT', 'rate': 15}, 
            {'name': '신한카드', 'rate': 10}
        ]},
        {'id': 2, 'name': 'B카페', 'distance': 800, 'rating': 4.8, 'discounts': [
            {'name': '현대카드', 'rate': 20}
        ]},
        {'id': 3, 'name': 'C레스토랑', 'distance': 500, 'rating': 4.0, 'discounts': [
            {'name': 'KT', 'rate': 25} # 사용자는 없지만 할인율이 가장 높음
        ]},
        {'id': 4, 'name': 'D분식', 'distance': 250, 'rating': 4.9, 'discounts': [
            {'name': '신한카드', 'rate': 20} # B카페와 할인율이 같음
        ]},
    ]

    # 함수를 실행하고 결과를 확인합니다.
    results = calculate_personalized_recommendations(sample_stores, sample_user_profile)

    print("👑 사용자 맞춤 추천 순위 결과:")
    print("-" * 50)
    for i, store in enumerate(results):
        benefit = store['representative_benefit']
        print(f"{i+1}위: {store['name']} (거리: {store['distance']}m)")
        print(f"   ㄴ 추천 혜택: {benefit['name']} ({benefit['rate']}% 할인)")