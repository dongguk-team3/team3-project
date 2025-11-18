"""
데이터 모델 정의
입력/출력 JSON 구조를 Pydantic 모델로 정의합니다.
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================
# 사용자 프로필 모델 (DB 기반)
# ============================================

class UserProfile(BaseModel):
    """사용자 프로필 정보"""
    # 통신사 정보
    telco: Optional[str] = Field(default=None, description="통신사: SKT, KT, LG U+")
    
    # 결제수단 정보 (카드사 코드 리스트)
    cards: Optional[List[str]] = Field(default=None, description="보유 카드 회사 코드 리스트 (예: ['SHINHAN', 'WOORI'])")
    
    # 멤버십 정보 (멤버십 이름 리스트)
    memberships: Optional[List[str]] = Field(default=None, description="가입한 멤버십 리스트 (예: ['CJ ONE', 'L.POINT'])")


class LocationRequest(BaseModel):
    """위치 기반 추천 요청"""
    latitude: float = Field(description="위도")
    longitude: float = Field(description="경도")
    radiusKm: float = Field(default=1.0, description="검색 반경 (km)")
    channel: str = Field(default="OFFLINE", description="결제 채널: OFFLINE 또는 ONLINE")
    orderAmount: Optional[int] = Field(default=None, description="실제 결제 금액 (없으면 15000원으로 가정)")
    userProfile: Optional[UserProfile] = Field(default=None, description="사용자 프로필")
    storeTypeFilter: Optional[Literal["ALL", "FRANCHISE", "INDEPENDENT"]] = Field(
        default="ALL",
        description="매장 타입 필터: ALL(전체), FRANCHISE(프랜차이즈만), INDEPENDENT(자영업만)"
    )


# ============================================
# 입력 데이터 모델 (기존 방식 - 하위 호환성)
# ============================================

class Target(BaseModel):
    """매장 타겟 정보"""
    externalBranchId: str
    matchedBranchId: int


class Brand(BaseModel):
    """브랜드 정보"""
    brandId: int
    brandName: str
    brandOwner: Optional[str] = None
    isFranchise: bool = Field(default=True, description="프랜차이즈 여부 (True: 프랜차이즈, False: 자영업)")


class Branch(BaseModel):
    """지점 정보"""
    branchId: int
    branchName: str


class Merchant(BaseModel):
    """가맹점 정보 (하위 호환용)"""
    merchantId: int
    merchantName: str
    isFranchise: bool = Field(default=True, description="프랜차이즈 여부")


class MerchantDetail(BaseModel):
    """가맹점 상세 정보 (브랜드 + 지점)"""
    brand: Optional[Brand] = None
    branch: Optional[Branch] = None
    storeType: Literal["FRANCHISE", "INDEPENDENT"] = Field(
        default="FRANCHISE",
        description="매장 타입: FRANCHISE(프랜차이즈) 또는 INDEPENDENT(자영업)"
    )


class Provider(BaseModel):
    """할인 제공자 정보"""
    providerName: str
    providerType: str  # TELCO, CARD, MEMBERSHIP, PAYMENT, AFFILIATION, BRAND


class ShapeParams(BaseModel):
    """할인 형태별 파라미터"""
    # PERCENT 타입
    percent: Optional[float] = None
    
    # AMOUNT 타입
    amount: Optional[int] = None
    
    # PER_UNIT 타입
    unitAmount: Optional[int] = None
    amountPerUnit: Optional[int] = None
    
    # 공통
    maxDiscountAmt: Optional[int] = None


class Shape(BaseModel):
    """할인 형태"""
    kind: Literal["PERCENT", "AMOUNT", "PER_UNIT"]
    params: ShapeParams


class Constraints(BaseModel):
    """할인 제약 조건"""
    channels: Optional[List[str]] = None  # ["OFFLINE", "ONLINE"]
    dayOfWeekMask: Optional[List[str]] = None  # ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    timeSlot: Optional[Dict[str, str]] = None  # {"start": "10:00", "end": "17:00"}
    minOrderAmount: Optional[int] = None
    maxOrderAmount: Optional[int] = None


class RequiredCondition(BaseModel):
    """필수 조건 단일 항목"""
    name: str


class RequiredConditions(BaseModel):
    """할인 적용을 위해 필요한 조건들"""
    payments: List[RequiredCondition] = Field(default_factory=list, description="필요한 결제수단")
    telcos: List[RequiredCondition] = Field(default_factory=list, description="필요한 통신사")
    memberships: List[RequiredCondition] = Field(default_factory=list, description="필요한 멤버십")
    affiliations: List[RequiredCondition] = Field(default_factory=list, description="필요한 단체/소속")


class AppliedByUserProfile(BaseModel):
    """사용자 프로필 매칭 정보"""
    matchedTelco: Optional[str] = None
    matchedCard: Optional[str] = None
    matchedMembership: Optional[str] = None


class Discount(BaseModel):
    """할인 정보"""
    discountId: int
    discountName: str
    provider: Provider
    shape: Shape
    constraints: Optional[Constraints] = None
    requiredConditions: Optional[RequiredConditions] = None
    appliedByUserProfile: Optional[AppliedByUserProfile] = None
    canBeCombined: bool = Field(default=True, description="다른 할인과 중복 적용 가능 여부")


class BranchResult(BaseModel):
    """매장별 결과"""
    target: Target
    merchant: Merchant
    discounts: List[Discount]


class RecommendationRequest(BaseModel):
    """추천 요청 입력"""
    results: List[BranchResult]
    channel: str = Field(default="OFFLINE", description="결제 채널: OFFLINE 또는 ONLINE")
    orderAmount: Optional[int] = Field(default=None, description="실제 결제 금액 (없으면 15000원으로 가정)")
    storeTypeFilter: Optional[Literal["ALL", "FRANCHISE", "INDEPENDENT"]] = Field(
        default="ALL",
        description="매장 타입 필터: ALL(전체), FRANCHISE(프랜차이즈만), INDEPENDENT(자영업만)"
    )


# ============================================
# 출력 데이터 모델
# ============================================

class CalculatedDiscount(BaseModel):
    """계산된 할인 정보"""
    discountId: int
    discountName: str
    provider: Provider
    shape: Shape
    calculatedAmount: int = Field(description="계산된 할인 금액")
    discountRate: float = Field(description="할인율 (백분율)")
    isApplicable: bool = Field(description="현재 적용 가능 여부")
    reasonIfNotApplicable: Optional[str] = Field(default=None, description="적용 불가 사유")
    requiredConditions: Optional[RequiredConditions] = Field(default=None, description="필요한 조건들")
    canBeCombined: bool = Field(default=True, description="다른 할인과 중복 적용 가능 여부")


class RecommendedBranch(BaseModel):
    """추천된 매장"""
    inputStoreName: Optional[str] = Field(default=None, description="사용자가 입력한 매장명")
    matched: bool = Field(default=True, description="브랜드/지점 매칭 성공 여부")
    matchReason: Optional[str] = Field(default=None, description="매칭 실패 시 이유")
    target: Target
    merchant: MerchantDetail
    applicableDiscounts: List[CalculatedDiscount] = Field(description="적용 가능한 할인 목록 (금액 높은 순)")
    otherDiscounts: List[CalculatedDiscount] = Field(description="적용 불가능한 할인 목록")
    bestDiscountAmount: int = Field(description="최대 할인 금액")


class RecommendationResponse(BaseModel):
    """추천 응답"""
    success: bool = Field(description="요청 처리 성공 여부")
    message: str = Field(description="응답 메시지")
    total: int = Field(description="조회된 매장 개수")
    recommendations: List[RecommendedBranch]
    requestedAt: datetime = Field(default_factory=datetime.now)
    channel: str
    orderAmount: int
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "success": True,
                "message": "추천 조회 완료",
                "total": 1,
                "recommendations": [],
                "requestedAt": "2025-11-05T00:00:00",
                "channel": "OFFLINE",
                "orderAmount": 15000
            }]
        }
    }


