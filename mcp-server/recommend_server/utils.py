"""
유틸리티 함수들

통신사 정규화, 카테고리 매핑 등
"""
from typing import Optional, List, Dict, Any


def normalize_telco(telco: Optional[str]) -> Optional[str]:
    """
    통신사 이름 정규화
    
    다양한 형태의 통신사 이름을 표준 형식으로 변환
    
    Args:
        telco: 입력 통신사 이름
        
    Returns:
        정규화된 통신사 이름 (SKT, KT, LG U+)
        
    Examples:
        >>> normalize_telco("LG 유플러스")
        'LG U+'
        >>> normalize_telco("LG유플러스")
        'LG U+'
        >>> normalize_telco("에스케이티")
        'SKT'
    """
    if not telco:
        return None
    
    # 소문자 변환 및 공백 제거
    normalized = telco.strip().upper()
    
    # 통신사별 매핑 (정확한 매칭 우선)
    exact_mapping = {
        # SKT 변형들
        "SKT": "SKT",
        "SK텔레콤": "SKT",
        "SK 텔레콤": "SKT",
        "에스케이티": "SKT",
        "에스케이텔레콤": "SKT",
        
        # KT 변형들
        "KT": "KT",
        "케이티": "KT",
        "케이티텔레콤": "KT",
        
        # LG U+ 변형들
        "LG U+": "LG U+",
        "LG U PLUS": "LG U+",
        "LGU+": "LG U+",
        "LG유플러스": "LG U+",
        "LG 유플러스": "LG U+",
        "엘지유플러스": "LG U+",
        "엘지 유플러스": "LG U+",
    }
    
    # 1단계: 정확히 일치하는 경우
    if normalized in exact_mapping:
        return exact_mapping[normalized]
    
    # 2단계: 부분 일치 (긴 것부터 매칭)
    partial_patterns = [
        ("SK텔레콤", "SKT"),
        ("에스케이텔레콤", "SKT"),
        ("에스케이티", "SKT"),
        ("케이티텔레콤", "KT"),
        ("케이티", "KT"),
        ("LG유플러스", "LG U+"),
        ("LG 유플러스", "LG U+"),
        ("엘지유플러스", "LG U+"),
        ("엘지 유플러스", "LG U+"),
        ("SKT", "SKT"),
        ("LG", "LG U+"),
        ("KT", "KT"),
    ]
    
    for pattern, result in partial_patterns:
        if pattern in normalized:
            return result
    
    # 매핑되지 않으면 원본 반환
    return telco


def normalize_membership(membership: str) -> str:
    """
    멤버십 이름 정규화
    
    Args:
        membership: 입력 멤버십 이름
        
    Returns:
        정규화된 멤버십 이름
        
    Examples:
        >>> normalize_membership("해피포인트")
        'HAPPY POINT'
        >>> normalize_membership("CJ ONE")
        'CJ ONE'
    """
    if not membership:
        return membership
    
    normalized = membership.strip().upper()
    
    membership_mapping = {
        "해피포인트": "HAPPY POINT",
        "HAPPY POINT": "HAPPY POINT",
        "해피 포인트": "HAPPY POINT",
        
        "CJ ONE": "CJ ONE",
        "CJONE": "CJ ONE",
        "씨제이원": "CJ ONE",
        
        "L.POINT": "L.POINT",
        "LPOINT": "L.POINT",
        "L포인트": "L.POINT",
        "엘포인트": "L.POINT",
        
        "OK캐쉬백": "OK CASHBAG",
        "OKCASHBAG": "OK CASHBAG",
        
        "신세계포인트": "SHINSEGAE POINT",
        "신세계 포인트": "SHINSEGAE POINT",
    }
    
    return membership_mapping.get(normalized, membership)


def normalize_card(card: str) -> str:
    """
    카드 이름 정규화
    
    Args:
        card: 입력 카드 이름
        
    Returns:
        정규화된 카드 이름
    """
    if not card:
        return card
    
    # 카드사 추출 로직
    normalized = card.strip().upper()
    
    # 주요 카드사 키워드
    card_companies = {
        "신한": "SHINHAN",
        "SHINHAN": "SHINHAN",
        "우리": "WOORI",
        "WOORI": "WOORI",
        "KB": "KB",
        "국민": "KB",
        "NH": "NH",
        "농협": "NH",
        "하나": "HANA",
        "HANA": "HANA",
        "삼성": "SAMSUNG",
        "SAMSUNG": "SAMSUNG",
        "현대": "HYUNDAI",
        "HYUNDAI": "HYUNDAI",
        "롯데": "LOTTE",
        "LOTTE": "LOTTE",
        "씨티": "CITI",
        "CITI": "CITI",
        "BC": "BC",
    }
    
    # 원본 반환 (카드 상품명 그대로 유지)
    return card


def map_category_to_search_term(category: str) -> str:
    """
    사용자 카테고리를 검색어로 매핑
    
    실제 장소 타입(카페, 음식점 등)은 그대로 전달하고,
    선호도 키워드(분위기, 가성비, 모임)는 기본 카테고리로 변환
    (나중에 리뷰 크롤링으로 필터링 예정)
    
    Args:
        category: 사용자 입력 카테고리
        
    Returns:
        Location_server 검색어
        
    Examples:
        >>> map_category_to_search_term("카페")
        '카페'
        >>> map_category_to_search_term("음식점")
        '음식점'
        >>> map_category_to_search_term("분위기")  # 선호도 키워드
        '음식점'  # 기본 카테고리로 (리뷰 필터링은 추후)
    """
    # 실제 장소 타입 카테고리 (그대로 전달)
    valid_categories = [
        "카페", "음식점", "레스토랑", 
        "한식", "일식", "중식", "양식", "분식",
        "치킨", "피자", "버거", "디저트",
        "술집", "바", "펍"
    ]
    
    normalized = category.strip()
    
    # 실제 카테고리면 그대로 반환
    if normalized in valid_categories:
        return normalized
    
    # 선호도 키워드는 기본 카테고리로 변환 (향후 리뷰 기반 필터링)
    preference_mapping = {
        # 선호도 키워드 → 기본 카테고리
        "본위기": "음식점",  # 분위기 좋은 곳 (리뷰에서 필터링 예정)
        "분위기": "음식점",
        "가성비": "음식점",  # 가성비 좋은 곳 (리뷰에서 필터링 예정)
        "모임": "음식점",    # 모임 좋은 곳 (리뷰에서 필터링 예정)
        "회식": "음식점",
        "총합": "음식점",    # 전체
        "전체": "음식점",
    }
    
    return preference_mapping.get(normalized, "음식점")  # 기본값: 음식점


def extract_user_preferences(category: str, user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    카테고리와 프로필에서 사용자 선호도 추출
    
    선호도 키워드(분위기, 가성비, 모임)를 인식하여 정렬 가중치 설정
    나중에는 리뷰 크롤링 데이터로 필터링할 예정
    
    Args:
        category: 카테고리 또는 선호도 키워드
        user_profile: 사용자 프로필
        
    Returns:
        선호도 딕셔너리
        
    Examples:
        >>> extract_user_preferences("가성비")
        {'value_oriented': True, 'discount_priority': 'high'}
        >>> extract_user_preferences("분위기")
        {'atmosphere_oriented': True, 'discount_priority': 'medium'}
    """
    preferences = {
        "category": category,
        "value_oriented": False,        # 가성비 중시 → 할인액 가중치 ↑
        "atmosphere_oriented": False,   # 분위기 중시 → 평점 가중치 ↑ (향후 리뷰 필터)
        "group_oriented": False,        # 모임 중시 → 거리 가중치 ↑ (향후 리뷰 필터)
        "discount_priority": "medium"
    }
    
    # 선호도 키워드 인식 (향후 리뷰 기반 필터링으로 확장)
    if category in ["가성비", "저렴", "합리적"]:
        preferences["value_oriented"] = True
        preferences["discount_priority"] = "high"
    elif category in ["본위기", "분위기"]:
        preferences["atmosphere_oriented"] = True
        preferences["discount_priority"] = "medium"
        # TODO: 리뷰에서 "분위기", "인테리어", "조용한" 등 키워드 필터링
    elif category in ["모임", "회식", "단체"]:
        preferences["group_oriented"] = True
        preferences["discount_priority"] = "medium"
        # TODO: 리뷰에서 "단체", "모임", "넓은" 등 키워드 필터링
    elif category in ["총합", "전체"]:
        preferences["discount_priority"] = "high"
    
    # 프로필 기반 추가 분석
    if user_profile:
        # 보유 멤버십/카드 개수로 할인 민감도 추정
        memberships = user_profile.get("memberships", [])
        cards = user_profile.get("cards", [])
        
        if len(memberships) + len(cards) >= 3:
            preferences["discount_priority"] = "very_high"
    
    return preferences


def sort_recommendations_by_preference(
    recommendations: List[Dict[str, Any]],
    preferences: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    사용자 선호도에 따라 추천 결과 정렬
    
    Args:
        recommendations: 추천 결과 리스트
        preferences: 선호도 정보
        
    Returns:
        정렬된 추천 결과
    """
    if not recommendations:
        return recommendations
    
    # 복사본 생성
    sorted_recs = recommendations.copy()
    
    # 선호도에 따른 가중치 계산
    for rec in sorted_recs:
        score = 0.0
        
        # 기본 점수: 할인액
        discount = rec.get('bestDiscountAmount', 0)
        score += discount * 1.0
        
        # 위치 정보
        location = rec.get('location', {})
        distance = location.get('distance', 1000)
        rating = location.get('rating', 3.5)
        
        # 선호도 기반 가중치 적용
        if preferences.get('value_oriented'):
            # 가성비 중시: 할인액 비중 ↑
            score += discount * 0.5
            
        if preferences.get('atmosphere_oriented'):
            # 분위기 중시: 평점 비중 ↑
            score += rating * 1000
            
        if preferences.get('group_oriented'):
            # 모임 중시: 거리 비중 ↑ (가까운 곳 선호)
            score -= distance * 0.5
        
        # 거리 패널티 (멀수록 점수 감소)
        score -= distance * 0.1
        
        # 평점 보너스
        score += rating * 500
        
        rec['_sort_score'] = score
    
    # 점수 기준 정렬
    sorted_recs.sort(key=lambda x: x.get('_sort_score', 0), reverse=True)
    
    # 임시 점수 필드 제거
    for rec in sorted_recs:
        rec.pop('_sort_score', None)
    
    return sorted_recs


def validate_user_profile(profile: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    사용자 프로필 검증
    
    Args:
        profile: 사용자 프로필
        
    Returns:
        (유효성, 에러 메시지)
    """
    if not profile:
        return True, None  # 프로필 없어도 OK
    
    # 필수 필드 체크 (선택 사항)
    # userId는 선택적
    
    # 통신사 검증
    telco = profile.get('telco')
    if telco:
        normalized = normalize_telco(telco)
        if normalized not in ['SKT', 'KT', 'LG U+', None]:
            return False, f"알 수 없는 통신사: {telco}"
    
    # 멤버십/카드는 리스트여야 함
    memberships = profile.get('memberships')
    if memberships is not None and not isinstance(memberships, list):
        return False, "memberships는 리스트여야 합니다"
    
    cards = profile.get('cards')
    if cards is not None and not isinstance(cards, list):
        return False, "cards는 리스트여야 합니다"
    
    return True, None


def determine_store_type(merchant: Dict[str, Any]) -> str:
    """
    매장 데이터에서 가게 타입을 결정합니다.
    
    Args:
        merchant: 매장 정보 (brand, branch 등 포함)
        
    Returns:
        "FRANCHISE" 또는 "INDEPENDENT"
        
    로직:
    1. brand가 있고 isFranchise가 명시되어 있으면 그대로 사용
    2. brand가 없으면 자영업으로 판단
    3. 알려진 프랜차이즈 리스트와 매칭
    """
    # 명시적으로 storeType이 있으면 사용
    if 'storeType' in merchant:
        return merchant['storeType']
    
    brand = merchant.get('brand')
    
    # Brand가 없으면 자영업
    if not brand:
        return "INDEPENDENT"
    
    # Brand에 isFranchise 필드가 있으면 사용
    if isinstance(brand, dict) and 'isFranchise' in brand:
        return "FRANCHISE" if brand['isFranchise'] else "INDEPENDENT"
    
    # Brand 이름으로 판단 (알려진 프랜차이즈 리스트)
    brand_name = brand.get('brandName', '') if isinstance(brand, dict) else str(brand)
    
    # 알려진 프랜차이즈 브랜드 (향후 DB에서 관리)
    known_franchises = [
        "스타벅스", "STARBUCKS", "이디야", "EDIYA",
        "맥도날드", "MCDONALDS", "버거킹", "BURGER KING",
        "롯데리아", "LOTTERIA", "KFC", "파리바게뜨",
        "뚜레쥬르", "투썸플레이스", "A TWOSOME PLACE",
        "CGV", "롯데시네마", "메가박스", "GS25", "CU", "세븐일레븐"
    ]
    
    brand_upper = brand_name.upper()
    for franchise in known_franchises:
        if franchise.upper() in brand_upper or brand_upper in franchise.upper():
            return "FRANCHISE"
    
    # 기본값: 프랜차이즈 (현재 시드 데이터가 대부분 프랜차이즈이므로)
    return "FRANCHISE"


def filter_by_store_type(
    recommendations: List[Dict[str, Any]],
    store_type_filter: str = "ALL"
) -> List[Dict[str, Any]]:
    """
    매장 타입으로 필터링합니다.
    
    Args:
        recommendations: 추천 결과 리스트
        store_type_filter: "ALL", "FRANCHISE", "INDEPENDENT"
        
    Returns:
        필터링된 추천 결과
    """
    if store_type_filter == "ALL":
        return recommendations
    
    filtered = []
    for rec in recommendations:
        merchant = rec.get('merchant', {})
        store_type = determine_store_type(merchant)
        
        if store_type == store_type_filter:
            filtered.append(rec)
    
    return filtered

