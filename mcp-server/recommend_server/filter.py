"""
할인 필터링 로직
사용자 프로필, 시간, 요일, 채널 제약 조건을 검증합니다.
"""
from datetime import datetime
from typing import Optional, Tuple
from models import Discount, Constraints, AppliedByUserProfile


def is_applicable_by_user_profile(discount: Discount) -> bool:
    """
    사용자 프로필 기준으로 적용 가능한지 확인
    
    appliedByUserProfile에 하나라도 값이 있으면 적용 가능한 것으로 판단
    """
    if discount.appliedByUserProfile is None:
        return False
    
    profile = discount.appliedByUserProfile
    
    # 매칭된 통신사, 카드, 멤버십 중 하나라도 있으면 적용 가능
    has_match = (
        profile.matchedTelco is not None or
        profile.matchedCard is not None or
        profile.matchedMembership is not None
    )
    
    return has_match


def check_constraints(
    discount: Discount,
    channel: str,
    order_amount: int,
    current_time: Optional[datetime] = None
) -> Tuple[bool, Optional[str]]:
    """
    제약 조건을 확인하여 현재 적용 가능한지 검증
    
    Args:
        discount: 할인 정보
        channel: 결제 채널 (OFFLINE, ONLINE 등)
        order_amount: 주문 금액
        current_time: 현재 시각 (None이면 datetime.now() 사용)
        
    Returns:
        (적용_가능_여부, 불가_사유)
    """
    if discount.constraints is None:
        return True, None
    
    constraints = discount.constraints
    
    if current_time is None:
        current_time = datetime.now()
    
    # 채널 제약 확인
    if constraints.channels is not None and len(constraints.channels) > 0:
        if channel not in constraints.channels:
            return False, f"채널 불일치 (가능: {', '.join(constraints.channels)})"
    
    # 요일 제약 확인
    if constraints.dayOfWeekMask is not None and len(constraints.dayOfWeekMask) > 0:
        current_day = _get_day_of_week(current_time)
        if current_day not in constraints.dayOfWeekMask:
            return False, f"요일 제한 (가능: {', '.join(constraints.dayOfWeekMask)})"
    
    # 시간대 제약 확인
    if constraints.timeSlot is not None:
        if not _is_within_time_slot(current_time, constraints.timeSlot):
            start = constraints.timeSlot.get("start", "")
            end = constraints.timeSlot.get("end", "")
            return False, f"시간 제한 ({start}~{end})"
    
    # 최소 주문 금액 확인
    if constraints.minOrderAmount is not None:
        if order_amount < constraints.minOrderAmount:
            return False, f"최소 주문 금액 미달 (최소: {constraints.minOrderAmount:,}원)"
    
    # 최대 주문 금액 확인
    if constraints.maxOrderAmount is not None:
        if order_amount > constraints.maxOrderAmount:
            return False, f"최대 주문 금액 초과 (최대: {constraints.maxOrderAmount:,}원)"
    
    return True, None


def _get_day_of_week(dt: datetime) -> str:
    """
    datetime을 요일 문자열로 변환
    
    Returns:
        "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"
    """
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    return days[dt.weekday()]


def _is_within_time_slot(current_time: datetime, time_slot: dict) -> bool:
    """
    현재 시각이 시간대 범위 내인지 확인
    
    Args:
        current_time: 현재 시각
        time_slot: {"start": "10:00", "end": "17:00"}
        
    Returns:
        범위 내 여부
    """
    start_str = time_slot.get("start")
    end_str = time_slot.get("end")
    
    if start_str is None or end_str is None:
        return True
    
    try:
        # 현재 시간을 분 단위로 변환
        current_minutes = current_time.hour * 60 + current_time.minute
        
        # 시작/종료 시간을 분 단위로 변환
        start_hour, start_min = map(int, start_str.split(":"))
        start_minutes = start_hour * 60 + start_min
        
        end_hour, end_min = map(int, end_str.split(":"))
        end_minutes = end_hour * 60 + end_min
        
        # 범위 내 확인
        return start_minutes <= current_minutes <= end_minutes
    except:
        # 파싱 실패 시 제약 없는 것으로 처리
        return True


