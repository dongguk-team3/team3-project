"""
할인액 계산 로직
PERCENT, AMOUNT, PER_UNIT 타입별로 실제 할인 금액을 계산합니다.
"""
import math
from models import Shape, ShapeParams


def calculate_discount(shape: Shape, order_amount: int) -> int:
    """
    할인 형태에 따라 실제 할인 금액을 계산합니다.
    
    Args:
        shape: 할인 형태 정보
        order_amount: 주문 금액
        
    Returns:
        계산된 할인 금액 (원)
    """
    if shape.kind == "PERCENT":
        return _calculate_percent_discount(shape.params, order_amount)
    elif shape.kind == "AMOUNT":
        return _calculate_amount_discount(shape.params, order_amount)
    elif shape.kind == "PER_UNIT":
        return _calculate_per_unit_discount(shape.params, order_amount)
    else:
        return 0


def _calculate_percent_discount(params: ShapeParams, order_amount: int) -> int:
    """
    퍼센트 할인 계산
    예: 10% 할인, 최대 3,000원
    """
    if params.percent is None:
        return 0
    
    # 퍼센트 할인 계산
    discount = int(order_amount * (params.percent / 100))
    
    # 최대 할인 금액 제한
    if params.maxDiscountAmt is not None:
        discount = min(discount, params.maxDiscountAmt)
    
    # 주문 금액을 초과할 수 없음
    discount = min(discount, order_amount)
    
    return discount


def _calculate_amount_discount(params: ShapeParams, order_amount: int) -> int:
    """
    정액 할인 계산
    예: 1,000원 할인
    """
    if params.amount is None:
        return 0
    
    # 주문 금액보다 클 수 없음
    return min(params.amount, order_amount)


def _calculate_per_unit_discount(params: ShapeParams, order_amount: int) -> int:
    """
    단위당 할인 계산
    예: 1,000원당 150원 할인, 최대 3,000원
    """
    if params.unitAmount is None or params.amountPerUnit is None:
        return 0
    
    # 단위 개수 계산 (내림)
    units = math.floor(order_amount / params.unitAmount)
    
    # 할인 금액 계산
    discount = units * params.amountPerUnit
    
    # 최대 할인 금액 제한
    if params.maxDiscountAmt is not None:
        discount = min(discount, params.maxDiscountAmt)
    
    # 주문 금액을 초과할 수 없음
    discount = min(discount, order_amount)
    
    return discount


def calculate_discount_rate(discount_amount: int, order_amount: int) -> float:
    """
    할인율 계산 (백분율)
    
    Args:
        discount_amount: 할인 금액
        order_amount: 주문 금액
        
    Returns:
        할인율 (예: 15.5)
    """
    if order_amount == 0:
        return 0.0
    
    return round((discount_amount / order_amount) * 100, 2)


