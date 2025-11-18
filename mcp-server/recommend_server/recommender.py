"""
추천 로직
할인을 필터링하고 계산하여 추천 순서로 정렬합니다.
"""
from datetime import datetime
from typing import List, Optional
from models import (
    BranchResult, 
    Discount, 
    CalculatedDiscount, 
    RecommendedBranch,
    RecommendationRequest,
    RecommendationResponse,
    MerchantDetail,
    Brand,
    Branch
)
from calculator import calculate_discount, calculate_discount_rate
from filter import is_applicable_by_user_profile, check_constraints


DEFAULT_ORDER_AMOUNT = 15000  # 기본 가상 결제 금액


def generate_recommendations(
    request: RecommendationRequest,
    current_time: Optional[datetime] = None
) -> RecommendationResponse:
    """
    추천 결과를 생성합니다.
    
    Args:
        request: 추천 요청
        current_time: 현재 시각 (None이면 datetime.now() 사용)
        
    Returns:
        추천 응답
    """
    if current_time is None:
        current_time = datetime.now()
    
    # 주문 금액 결정
    order_amount = request.orderAmount if request.orderAmount else DEFAULT_ORDER_AMOUNT
    
    # 매장 타입 필터
    store_type_filter = request.storeTypeFilter if hasattr(request, 'storeTypeFilter') else "ALL"
    
    # 각 매장별로 처리
    recommendations: List[RecommendedBranch] = []
    
    for branch_result in request.results:
        recommended = _process_branch(
            branch_result=branch_result,
            channel=request.channel,
            order_amount=order_amount,
            current_time=current_time,
            store_type_filter=store_type_filter
        )
        
        # 매장 타입 필터링 적용
        if store_type_filter != "ALL":
            from utils import determine_store_type
            merchant_dict = {
                'brand': recommended.merchant.brand.model_dump() if recommended.merchant.brand else None,
                'branch': recommended.merchant.branch.model_dump() if recommended.merchant.branch else None,
                'storeType': recommended.merchant.storeType
            }
            store_type = determine_store_type(merchant_dict)
            
            if store_type != store_type_filter:
                continue  # 필터 조건에 맞지 않으면 스킵
        
        recommendations.append(recommended)
    
    # 최대 할인 금액 기준으로 매장 정렬
    recommendations.sort(key=lambda x: x.bestDiscountAmount, reverse=True)
    
    return RecommendationResponse(
        success=True,
        message="추천 조회 완료",
        total=len(recommendations),
        recommendations=recommendations,
        requestedAt=current_time,
        channel=request.channel,
        orderAmount=order_amount
    )


def _process_branch(
    branch_result: BranchResult,
    channel: str,
    order_amount: int,
    current_time: datetime,
    store_type_filter: str = "ALL"
) -> RecommendedBranch:
    """
    매장별 할인 정보를 처리합니다.
    
    1. 사용자 프로필로 1차 필터링
    2. 제약조건으로 2차 필터링
    3. 할인액 계산
    4. 정렬
    5. 매장 타입 결정
    """
    applicable_discounts: List[CalculatedDiscount] = []
    other_discounts: List[CalculatedDiscount] = []
    
    for discount in branch_result.discounts:
        # 1차 필터: 사용자 프로필 매칭 확인
        is_user_applicable = is_applicable_by_user_profile(discount)
        
        if is_user_applicable:
            # 2차 필터: 제약조건 확인
            is_constraint_ok, reason = check_constraints(
                discount=discount,
                channel=channel,
                order_amount=order_amount,
                current_time=current_time
            )
            
            # 할인액 계산
            discount_amount = calculate_discount(discount.shape, order_amount)
            discount_rate = calculate_discount_rate(discount_amount, order_amount)
            
            calculated = CalculatedDiscount(
                discountId=discount.discountId,
                discountName=discount.discountName,
                provider=discount.provider,
                shape=discount.shape,
                calculatedAmount=discount_amount,
                discountRate=discount_rate,
                isApplicable=is_constraint_ok,
                reasonIfNotApplicable=reason,
                requiredConditions=discount.requiredConditions if hasattr(discount, 'requiredConditions') else None,
                canBeCombined=discount.canBeCombined if hasattr(discount, 'canBeCombined') else True
            )
            
            if is_constraint_ok:
                applicable_discounts.append(calculated)
            else:
                other_discounts.append(calculated)
        else:
            # 사용자 프로필과 매칭되지 않는 할인
            discount_amount = calculate_discount(discount.shape, order_amount)
            discount_rate = calculate_discount_rate(discount_amount, order_amount)
            
            calculated = CalculatedDiscount(
                discountId=discount.discountId,
                discountName=discount.discountName,
                provider=discount.provider,
                shape=discount.shape,
                calculatedAmount=discount_amount,
                discountRate=discount_rate,
                isApplicable=False,
                reasonIfNotApplicable="사용자 프로필과 매칭되지 않음",
                requiredConditions=discount.requiredConditions if hasattr(discount, 'requiredConditions') else None,
                canBeCombined=discount.canBeCombined if hasattr(discount, 'canBeCombined') else True
            )
            other_discounts.append(calculated)
    
    # 적용 가능 할인: 할인액 높은 순으로 정렬
    applicable_discounts.sort(key=lambda x: x.calculatedAmount, reverse=True)
    
    # 기타 할인: 할인액 높은 순으로 정렬
    other_discounts.sort(key=lambda x: x.calculatedAmount, reverse=True)
    
    # 최대 할인 금액 계산
    best_discount_amount = 0
    if applicable_discounts:
        best_discount_amount = applicable_discounts[0].calculatedAmount
    
    # 매장 타입 결정
    from utils import determine_store_type
    
    # isFranchise 필드가 있으면 사용, 없으면 브랜드 이름으로 판단
    is_franchise = True
    if hasattr(branch_result.merchant, 'isFranchise'):
        is_franchise = branch_result.merchant.isFranchise
    else:
        # 브랜드 이름으로 판단
        merchant_dict = {
            'brand': {
                'brandName': branch_result.merchant.merchantName
            }
        }
        store_type = determine_store_type(merchant_dict)
        is_franchise = (store_type == "FRANCHISE")
    
    # Merchant를 MerchantDetail로 변환
    merchant_detail = MerchantDetail(
        brand=Brand(
            brandId=branch_result.merchant.merchantId,
            brandName=branch_result.merchant.merchantName,
            brandOwner=None,
            isFranchise=is_franchise
        ),
        branch=None,
        storeType="FRANCHISE" if is_franchise else "INDEPENDENT"
    )
    
    return RecommendedBranch(
        inputStoreName=branch_result.merchant.merchantName,
        matched=True,
        matchReason=None,
        target=branch_result.target,
        merchant=merchant_detail,
        applicableDiscounts=applicable_discounts,
        otherDiscounts=other_discounts,
        bestDiscountAmount=best_discount_amount
    )


