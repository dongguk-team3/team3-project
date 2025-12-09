"""
추천 엔진 모듈
할인 계산 및 추천 순서 결정
"""
import json
import math
from typing import Dict, Any, List, Optional

from sqlalchemy import null
from sympy import false, true


class RecommendationEngine:
    """추천 엔진 - 할인 계산 및 정렬"""
    
    def __init__(self):
        self.base_amount = 12000  # 기준 금액 12,000원 고정
    
    def process_recommendations(
        self, 
        stores: List[str], 
        discounts_by_store: Dict[str, Any], 
        user_profile: Dict[str, Any],
        user_latitude: Optional[float] = None,
        user_longitude: Optional[float] = None,
        stores_detail: Optional[List[Dict[str, Any]]] = None,
        distances: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        추천 처리 메인 함수
        
        Args:
            stores: 매장 이름 리스트
            discounts_by_store: 매장별 할인 정보
            user_profile: 사용자 프로필
            user_latitude: 사용자 위도 (거리 계산용)
            user_longitude: 사용자 경도 (거리 계산용)
            stores_detail: 매장 상세 정보 리스트 (좌표 포함, 거리 계산용)
            distances: LocationServer에서 전달한 매장별 거리 정보 (store_name -> meters)
            
        Returns:
            추천 결과 (2가지 정렬: 개인화, 거리순)
        """
        # DiscountServer 응답 래퍼 형태({"discounts_by_store": {...}} 또는 {"discount": {...}})와
        # 기존 형태({매장명: 할인정보})를 모두 지원하도록 정규화
        discounts_by_store = self._normalize_discount_payload(discounts_by_store)
        return {
            "by_discount": {
                "personalized": self._calculate_personalized_discounts(
                    stores, discounts_by_store, user_profile, stores_detail, user_latitude, user_longitude, distances
                ),
                "by_distance": self._calculate_by_distance(
                    stores, discounts_by_store, distances
                ),
            }
        }

    def _normalize_discount_payload(self, discounts_payload: Any) -> Dict[str, Any]:
        """
        할인 데이터 입력 형태를 통합한다.
        지원 형태:
          1) {매장명: {discounts: [...]}} (기존)
          2) {"discounts_by_store": {...}} (DiscountServer 응답)
          3) {"discount": {"discounts_by_store": {...}}} (상위 결과에 래핑된 형태)
        """
        if not isinstance(discounts_payload, dict):
            return {}

        # 2) {"discounts_by_store": {...}}
        inner = discounts_payload.get("discounts_by_store")
        if isinstance(inner, dict):
            return inner

        # 3) {"discount": {"discounts_by_store": {...}}}
        wrapped = discounts_payload.get("discount")
        if isinstance(wrapped, dict):
            nested = wrapped.get("discounts_by_store")
            if isinstance(nested, dict):
                return nested

        # 1) 이미 {매장명: 할인정보} 형태인지 휴리스틱으로 확인
        store_like_entries = {
            key: data
            for key, data in discounts_payload.items()
            if isinstance(data, dict) and (
                "discounts" in data or "merchant" in data or "matched" in data
            )
        }
        if store_like_entries:
            return store_like_entries

        return {}
    
    def _prepare_store_base_data(
        self,
        stores: List[str],
        discounts_by_store: Dict[str, Any],
        stores_detail: Optional[List[Dict[str, Any]]],
        user_latitude: Optional[float],
        user_longitude: Optional[float],
        distances: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        매장 기본 데이터 준비 (할인 정보, 거리 정보 포함)
        
        Returns:
            매장 기본 데이터 리스트
        """
        base_data = []
        
        # 매장 상세 정보 딕셔너리 생성 (빠른 조회용)
        stores_dict = {}
        if stores_detail:
            stores_dict = {store.get("title") or store.get("name", ""): store for store in stores_detail}
        
        # 매장별 할인 정보 및 거리 계산
        for idx, store_name in enumerate(stores):
            store_data = discounts_by_store.get(store_name)
            store_discounts = self._extract_discounts_list(store_data)
            
            # 할인이 없는 매장은 제외
            if not store_discounts:
                continue
            
            # discount 객체 저장
            all_benefits = []
            max_discount_amount = 0
            
            for discount in store_discounts:
                # 문자열로 넘어온 필드를 파싱해 정규화
                normalized_discount = self._normalize_discount(discount)
                
                # discount 객체 그대로 추가 (추가 변환 없이)
                all_benefits.append(normalized_discount)
                
                # 순위 정렬을 위해 할인 금액 계산 (내부 계산용)
                discount_amount = self._calculate_discount_amount(normalized_discount)
                if discount_amount > max_discount_amount:
                    max_discount_amount = discount_amount
            
            # 거리 계산
            distance_meters = None
            store_detail = stores_dict.get(store_name)
            
            # LocationServer에서 전달된 거리(distances)가 우선
            if distances and store_name in distances:
                try:
                    distance_meters = float(distances.get(store_name))
                except (TypeError, ValueError):
                    distance_meters = None
            # 없으면 좌표로 계산
            if distance_meters is None and store_detail and user_latitude is not None and user_longitude is not None:
                try:
                    raw_lat = store_detail.get("mapy") or store_detail.get("latitude")
                    raw_lon = store_detail.get("mapx") or store_detail.get("longitude")
                    
                    if raw_lat is not None and raw_lon is not None:
                        store_lat = float(raw_lat)
                        store_lon = float(raw_lon)
                        
                        # 네이버 정수형 좌표 변환
                        if store_lat > 1000:
                            if store_lat / 1000000 < 100:
                                store_lat /= 1000000
                            elif store_lat / 10000000 < 100:
                                store_lat /= 10000000
                        if store_lon > 1000:
                            if store_lon / 1000000 < 200:
                                store_lon /= 1000000
                            elif store_lon / 10000000 < 200:
                                store_lon /= 10000000
                        
                        distance_meters = round(self._calculate_distance(user_latitude, user_longitude, store_lat, store_lon), 2)
                except (ValueError, TypeError):
                    pass
            
            # store_id 생성 (stores_detail에서 가져오거나 인덱스 기반)
            store_id = None
            if store_detail and store_detail.get("id"):
                store_id = store_detail.get("id")
            else:
                # store_id가 없으면 인덱스 기반 생성 (s1, s2, ...)
                store_id = f"s{idx + 1}"
            
            base_data.append({
                "store_id": store_id,
                "name": store_name,
                "distance_meters": distance_meters,
                "all_benefits": all_benefits,
                "store_detail": store_detail
            })
        
        return base_data
    
    def _calculate_personalized_discounts(
        self,
        stores: List[str],
        discounts_by_store: Dict[str, Any],
        user_profile: Dict[str, Any],
        stores_detail: Optional[List[Dict[str, Any]]],
        user_latitude: Optional[float],
        user_longitude: Optional[float],
        distances: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        프로필과 맞는 할인 순 정렬 (개인화)
        - 사용자 프로필과 매칭되는 할인이 있는 매장만
        - 프로필과 맞는 할인 금액 큰 순으로 정렬
        """
        base_data = self._prepare_store_base_data(stores, discounts_by_store, stores_detail, user_latitude, user_longitude, distances)
        
        user_telco = user_profile.get("telco")
        user_cards = user_profile.get("cards", [])
        user_memberships = user_profile.get("memberships", [])
        
        results = []
        
        for store_data in base_data:
            all_benefits = store_data["all_benefits"]
            
            # 프로필과 맞는 할인만 필터링
            applicable_benefits = []
            max_applicable_discount = 0
            
            for discount in all_benefits:
                if self._is_user_applicable(discount, user_telco, user_cards, user_memberships):
                    applicable_benefits.append(discount)
                    discount_amount = self._calculate_discount_amount(discount)
                    if discount_amount > max_applicable_discount:
                        max_applicable_discount = discount_amount
            
            # 프로필과 맞는 할인이 없는 매장은 제외
            if not applicable_benefits:
                continue
            
            results.append({
                "store_id": store_data["store_id"],
                "name": store_data["name"],
                "distance_meters": store_data["distance_meters"],
                "all_benefits": applicable_benefits,  # 프로필과 맞는 할인만
                "rank": 0
            })
        
        # 프로필과 맞는 할인 금액 큰 순으로 정렬
        results.sort(key=lambda x: (
            -max([self._calculate_discount_amount(d) for d in x["all_benefits"]], default=0),
            x["distance_meters"] if x["distance_meters"] is not None else float('inf')
        ))
        
        # 상위 3개로 제한 후 순위 설정
        results = results[:3]
        for i, result in enumerate(results):
            result["rank"] = i + 1
        
        return {
            "store_list": results
        }
    
    def _calculate_by_distance(
        self,
        stores: List[str],
        discounts_by_store: Dict[str, Any],
        distances: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        거리순 정렬
        - 거리 가까운 순으로 정렬
        - 할인 여부와 무관하게 LocationServer 거리값만 사용
        """
        results = []

        for idx, store_name in enumerate(stores):
            distance_val = None
            if distances and store_name in distances:
                try:
                    distance_val = float(distances.get(store_name))
                except (TypeError, ValueError):
                    distance_val = None

            # 할인 정보가 있으면 파싱해서 넣고, 없어도 빈 리스트 유지
            store_data = discounts_by_store.get(store_name) if isinstance(discounts_by_store, dict) else {}
            store_discounts = self._extract_discounts_list(store_data)
            all_benefits = [self._normalize_discount(d) for d in store_discounts] if store_discounts else []

            results.append({
                "store_id": f"s{idx + 1}",
                "name": store_name,
                "distance_meters": distance_val,
                "all_benefits": all_benefits,
                "rank": 0
            })
        
        # 거리 가까운 순으로 정렬 (None은 맨 뒤로)
        results.sort(key=lambda x: (
            x["distance_meters"] is None,
            x["distance_meters"] if x["distance_meters"] is not None else float('inf')
        ))
        
        # 상위 3개로 제한 후 순위 설정
        results = results[:3]
        for i, result in enumerate(results):
            result["rank"] = i + 1
        
        return {
            "store_list": results
        }
    
    def _extract_discounts_list(self, store_data: Any) -> List[Dict[str, Any]]:
        """
        매장별 할인 데이터에서 할인 리스트 추출
        딕셔너리 형식 또는 리스트 형식 모두 지원
        
        Args:
            store_data: 할인 데이터 (딕셔너리 또는 리스트)
                - 딕셔너리: {"discounts": [...], "matched": ..., ...}
                - 리스트: [...]
        
        Returns:
            할인 리스트 (항상 리스트 반환)
        """
        if isinstance(store_data, dict):
            # 딕셔너리 형식: {"discounts": [...]}
            raw = store_data.get("discounts", [])
        elif isinstance(store_data, list):
            # 리스트 형식: [...]
            raw = store_data
        else:
            return []

        # 할인 항목이 문자열(C# ToString())로 올 수 있으므로 파싱 시도
        parsed_list = []
        if isinstance(raw, str):
            # 단일 문자열이면 파싱 후 리스트로 래핑
            parsed = self._parse_object_string(raw)
            if isinstance(parsed, dict):
                parsed_list = [parsed]
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    parsed = self._parse_object_string(item)
                    if isinstance(parsed, dict):
                        parsed_list.append(parsed)
                else:
                    parsed_list.append(item)

        return parsed_list

    def _parse_object_string(self, value: Any) -> Any:
        """
        DiscountServer가 C# 객체의 ToString() 형태로 반환한 값을 파싱한다.
        예: "@{kind=PERCENT; amount=20.0; maxAmount=100000.0; unitRule=}"
        """
        if not isinstance(value, str):
            return value
        
        text = value.strip()
        if not (text.startswith("@{") and text.endswith("}")):
            return value

        # 중첩된 @{ ... } 구조를 고려해 세미콜론을 depth 0 기준으로 분리
        inner = text[2:-1].strip()
        if not inner:
            return {}

        parts: List[str] = []
        buf: List[str] = []
        depth = 0
        for ch in inner:
            if ch == "@" and buf[-1:] == ["{"]:
                # 이미 '{' 를 넣은 상태라면 깊이를 올리고 계속
                depth += 1
            if ch == "{":
                depth += 1
            if ch == "}":
                depth = max(depth - 1, 0)

            if ch == ";" and depth == 0:
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
            else:
                buf.append(ch)
        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)

        parsed: Dict[str, Any] = {}
        for part in parts:
            if "=" not in part:
                continue
            key, raw_val = part.split("=", 1)
            key = key.strip()
            raw_val = raw_val.strip()

            # 중첩 객체
            if raw_val.startswith("@{") and raw_val.endswith("}"):
                val: Any = self._parse_object_string(raw_val)
            elif raw_val in ("", None):
                val = None
            elif raw_val == "System.Object[]":
                val = []
            elif raw_val.lower() in {"true", "false"}:
                val = raw_val.lower() == "true"
            else:
                try:
                    num = float(raw_val)
                    val = int(num) if num.is_integer() else num
                except ValueError:
                    val = raw_val
            parsed[key] = val

        return parsed

    def _normalize_discount(self, discount: Dict[str, Any]) -> Dict[str, Any]:
        """
        C# 문자열 필드(shape/constraints/requiredConditions)를 파싱해 딕셔너리로 변환한다.
        """
        if isinstance(discount, str):
            # 전체 할인 객체가 문자열로 넘어온 경우 파싱 시도
            parsed = self._parse_object_string(discount)
            if isinstance(parsed, dict):
                discount = parsed
            else:
                return discount
        elif not isinstance(discount, dict):
            return discount
        
        normalized = dict(discount)
        
        # shape, constraints, requiredConditions를 문자열에서 파싱
        for key in ("shape", "constraints", "requiredConditions"):
            if key in normalized:
                normalized[key] = self._parse_object_string(normalized[key])
        
        # requiredConditions 보정: 리스트가 없으면 빈 리스트로 세팅
        req = normalized.get("requiredConditions")
        if isinstance(req, dict):
            for cond_key in ("payments", "telcos", "memberships", "affiliations"):
                val = req.get(cond_key)
                if val in (None, "System.Object[]"):
                    req[cond_key] = []
                elif not isinstance(val, list):
                    req[cond_key] = [val]
            normalized["requiredConditions"] = req
        elif req == "System.Object[]":
            normalized["requiredConditions"] = {
                "payments": [],
                "telcos": [],
                "memberships": [],
                "affiliations": []
            }
        
        # shape.unitRule도 동일 포맷일 수 있으므로 추가 파싱
        shape = normalized.get("shape")
        if isinstance(shape, dict) and "unitRule" in shape:
            shape["unitRule"] = self._parse_object_string(shape.get("unitRule"))
            normalized["shape"] = shape

        # appliedByUserProfile / isDiscount가 문자열인 경우 bool로 보정
        for flag_key in ("appliedByUserProfile", "isDiscount"):
            if isinstance(normalized.get(flag_key), str):
                normalized[flag_key] = normalized[flag_key].lower() == "true"
        
        return normalized
    
    def _is_user_applicable(
        self, 
        discount: Dict[str, Any], 
        user_telco: str, 
        user_cards: List[str], 
        user_memberships: List[str]
    ) -> bool:
        """
        사용자가 해당 할인을 받을 수 있는지 확인
        
        DiscountServer가 이미 매칭한 경우 appliedByUserProfile 필드를 우선 확인
        """
        # 1. appliedByUserProfile 필드 확인 (DiscountServer가 이미 매칭한 경우)
        applied_by_profile = discount.get("appliedByUserProfile")
        if applied_by_profile is True:
            # DiscountServer가 이미 사용자 프로필과 매칭했다고 판단
            return True
        
        # 2. appliedByUserProfile이 없거나 False인 경우, 기존 로직 사용
        provider_type = discount.get("providerType")
        provider_name = discount.get("providerName")
        
        if provider_type == "TELCO":
            # 통신사명 정규화 (예: "KT" vs "KT 멤버십")
            if user_telco:
                # 통신사명 일치 확인 (부분 일치도 고려)
                return user_telco.upper() == provider_name.upper() or provider_name.upper() in user_telco.upper()
        elif provider_type == "CARD" or provider_type == "PAYMENT":
            # 카드명 정규화 및 비교
            if user_cards:
                # 카드명을 대문자로 변환하여 비교
                user_cards_upper = [card.upper() for card in user_cards]
                provider_upper = provider_name.upper() if provider_name else ""
                # 카드명 일치 또는 부분 일치 확인
                return any(provider_upper in card or card in provider_upper for card in user_cards_upper)
        elif provider_type == "MEMBERSHIP":
            # 멤버십명 정규화 및 비교
            if user_memberships:
                user_memberships_upper = [mem.upper() for mem in user_memberships]
                provider_upper = provider_name.upper() if provider_name else ""
                return any(provider_upper in mem or mem in provider_upper for mem in user_memberships_upper)
        elif provider_type == "STORE":
            return True  # 매장 할인은 누구나 가능
        
        return False
    
    def _calculate_discount_amount(self, discount: Dict[str, Any]) -> int:
        """
        할인 금액 계산 (12,000원 기준)
        
        Discount_MAP_server 반환 구조에 맞춤:
        - shape.kind: "PERCENT", "AMOUNT", "PER_UNIT"
        - shape.amount: 할인 금액/퍼센트
        - shape.maxAmount: 최대 할인 금액
        - shape.unitRule: 단위별 할인 규칙
        """
        # shape 객체 접근
        shape = discount.get("shape", {})
        # shape가 문자열로 남아있다면 파싱 시도
        if isinstance(shape, str):
            parsed_shape = self._parse_object_string(shape)
            if isinstance(parsed_shape, dict):
                shape = parsed_shape
            else:
                return 0
        if not shape:
            return 0
        
        discount_type = shape.get("kind")
        
        if discount_type == "PERCENT":
            # 퍼센트 할인
            percent = shape.get("amount", 0)
            max_amount = shape.get("maxAmount")
            
            discount_amount = int(self.base_amount * (percent / 100))
            
            # 최대 할인 금액 제한
            if max_amount is not None:
                discount_amount = min(discount_amount, int(max_amount))
                
            return discount_amount
            
        elif discount_type == "AMOUNT":
            # 정액 할인
            return int(shape.get("amount", 0))
            
        elif discount_type == "PER_UNIT":
            # 단위별 할인 (예: 1000원당 150원)
            unit_rule = shape.get("unitRule", {})
            if unit_rule is None or not unit_rule:
                return 0
                
            unit_amount = unit_rule.get("unitAmount", 1000)
            per_unit_value = unit_rule.get("perUnitValue", 0)
            max_discount = unit_rule.get("maxDiscountAmount")
            
            units = self.base_amount // unit_amount
            discount_amount = int(units * per_unit_value)
            
            # 최대 할인 금액 제한
            if max_discount is not None:
                discount_amount = min(discount_amount, int(max_discount))
                
            return discount_amount
        
        return 0
    
    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        두 좌표 사이의 거리를 미터(m) 단위로 계산 (하버사인 공식)
        
        Args:
            lat1: 첫 번째 위치의 위도
            lon1: 첫 번째 위치의 경도
            lat2: 두 번째 위치의 위도
            lon2: 두 번째 위치의 경도
            
        Returns:
            거리 (미터)
        """
        R = 6371000  # 지구 반지름 (미터)
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c


def main():
    """
    샘플 입력 데이터를 사용하여 RecommendationEngine.process_recommendations를 실행하는 엔트리.
    실제 서비스 인풋과 동일한 형태를 그대로 흘려보내며, 중간 base_data 상태도 출력한다.
    """
    sample_input = {
        "user_id": "test123",
        "stores": ['카페 평화', '카페앤', '도넛하우스 남이섬점', '파머스 카트', '스노우까페', '마스터커피 가평점', '호두이야기', '햇살드는카페', '별그랑베이커리카페 남이섬점', '스타벅스 남이섬점'],
        "discount":  {
                                         "message":  "할인 정보 조회 완료",
                                         "discounts_by_store":  {
                                                                    "스타벅스 남이섬점":  {
                                                                                      "matched":  true,
                                                                                      "reason":  "해당 지점을 찾을 수 없습니다. (브랜드 기준 할인만 조회했습니다.)",
                                                                                      "merchant":  {
                                                                                                       "brand":  {
                                                                                                                     "brandId":  1,
                                                                                                                     "brandName":  "스타벅스",
                                                                                                                     "brandOwner":  null
                                                                                                                 },
                                                                                                       "branch":  null
                                                                                                   },
                                                                                      "discounts":  [
                                                                                                        {
                                                                                                            "discountName":  "NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인",
                                                                                                            "providerType":  "PAYMENT",
                                                                                                            "providerName":  "우리카드",
                                                                                                            "shape":  "@{kind=PERCENT; amount=20.0; maxAmount=100000.0; unitRule=}",
                                                                                                            "constraints":  "@{validFrom=; validTo=; dayOfWeekMask=; timeFrom=; timeTo=; channelLimit=; requiredLevel=; qualification=전월 국내가맹점 이용액 30만원 이상 시 제공. 탐앤탐스, 스타벅스 20% 청구할인 (통합 일 1회, 월 2회, 월 최대 5천원). 커피 브랜드의 상품권·선불카드 구입/충전, 타 가맹점 명의 매장, 백화점/대형마트·미군부대 내 매장 제외.; applicationMenu=커피전문점(탐앤탐스, 스타벅스)}",
                                                                                                            "requiredConditions":  "@{payments=System.Object[]; telcos=System.Object[]; memberships=System.Object[]; affiliations=System.Object[]}",
                                                                                                            "appliedByUserProfile":  false,
                                                                                                            "isDiscount":  true
                                                                                                        },
                                                                                                        {
                                                                                                            "discountName":  "[VVIP]아메리카노(T) 한잔 무료 OR\n[VIP]더블 사이즈업 무료",
                                                                                                            "providerType":  "TELCO",
                                                                                                            "providerName":  "LG U+",
                                                                                                            "shape":  "@{kind=AMOUNT; amount=0.0; maxAmount=; unitRule=}",
                                                                                                            "constraints":  "@{validFrom=; validTo=; dayOfWeekMask=; timeFrom=; timeTo=; channelLimit=; requiredLevel=VVIP/VIP; qualification=VIP콕 내 제휴사 통합 월 1회\n결제 시 직원에게 멤버십 카드 제시\n\n\n\n■ 유의 사항\n\n※ 아메리카노(T)\n\n- 아메리카노 Tall 사이즈 (HOT/ICED) 선택 가능 또는 4,700원 할인\n\n※ 더블 사이즈업\n\n- 수령을 원하는 사이즈로 주문 시, 더블 사이즈업 혜택 적용 (1,400원 한정)\n\n* Venti 사이즈 주문 시, Tall 사이즈 가격으로 결제 / Grande 사이즈 주문 시, Short 사이즈 가격(Short 사이즈가 있는 음료 한정)으로 결제\n\n* 1,400원 더블 사이즈업 한정하여 적용 가능하며, 더블 사이즈업 1,600원 음료의 경우 1,400원 할인으로 적용\n\n- 파트너 직접 주문(POS) 주문 시 혜택 적용 가능하며, 사이렌오더 및 딜리버스에서는 사용 불가\n\n- 일부 공항 매장, 미군부대 매장, 일부 입점 매장 사용 불가\n\n- 일부 이벤트와 중복 적용 불가\n\n- 문의: 스타벅스 고객센터(1522-3232, 오전 9시-오후 6시, 연중무휴); applicationMenu=}",
                                                                                                            "requiredConditions":  "@{payments=System.Object[]; telcos=System.Object[]; memberships=System.Object[]; affiliations=System.Object[]}",
                                                                                                            "appliedByUserProfile":  false,
                                                                                                            "isDiscount":  true
                                                                                                        },
                                                                                                        {
                                                                                                            "discountName":  "전등급 [상시]사이즈업 [OTTX스타벅스] 아메리카노(Tall) 1잔 무료 VVIP [VVIP생일] 생일 조각케이크＋아메리카노 2잔 무료 [V/VIP 초이스] 아메리카노 Short 무료 또는 4,000원 할인 VIP [V/VIP 초이스] 아메리카노 Short 무료 또는 4,000원 할인",
                                                                                                            "providerType":  "TELCO",
                                                                                                            "providerName":  "KT",
                                                                                                            "shape":  "@{kind=AMOUNT; amount=4000.0; maxAmount=; unitRule=}",
                                                                                                            "constraints":  "@{validFrom=; validTo=; dayOfWeekMask=; timeFrom=; timeTo=; channelLimit=; requiredLevel=; qualification=상세내용 참조\n※ 해당 제휴사 혜택(쿠폰 다운로드)은 KT멤버십 앱에서만 이용 가능합니다. [V/VIP 초이스혜택] ▶대상: VVIP/VIP - 혜택: 아메리카노 Short 무료 또는 4,000원 할인 - 이용횟수: VVIP/VIP 초이스 통합 월 1회(VVIP 최대 연 12회, VIP 최대 연 6회) ※ 당월 다른 제휴사로 VVIP/VIP 초이스혜택을 이미 사용한 경우, 중복 이용 불가 [상시혜택] ▶대상: KT멤버십 전등급 - 혜택: 음료 사이즈업(제조음료 1개에 한해 적용 가능) - 이용횟수: 월 1회 ※ 유의사항 - 일부 매장 제외 - 아메리카노 short 사이즈 상품은 아이스 미제공 - 타 쿠폰 및 이용권과의 중복 적용은 불가 - 하나의 결제 기준 VIP 무료커피 혜택과 사이즈업 혜택 동시 이용 불가 ex. VIP 무료커피 주문 다른 음료 사이즈업 적용 - VVIP/VIP 초이스혜택은 해당 월 다른 제휴사로 VVIP/VIP 초이스혜택 사용시, 이용 불가 [VVIP초이스 생일혜택] ▶대상: VVIP - 기간 : ~ 2025년 12월 31일 - 이용월 : 생일 당월 한정 - 혜택: 생일 조각케이크 아메리카노 2잔 무료 - 이용횟수: 연 1회 ※ 본 혜택은 매월 선착순 1만명 제공 ※ 당월 다른 제휴사로 VVIP초이스 혜택을 이미 사용한 경우, 중복 이용 불가 ※ 멤버십 앱 메인 페이지 생일배너 클릭 → 이벤트 페이지 내 쿠폰 다운로드/확인 → 쿠폰 모두 다운로드 후 스타벅스APP에 개별 등록 후 사용 가능 ※ 상세내용은 대상자 생일당월 KT 멤버십 앱 \u003e 이벤트페이지에서 확인 가능 [OTT 스타벅스 이벤트] ▶대상: KT OTT구독 \u0027유튜브프리미엄 스타벅스\u0027, \u0027티빙 스타벅스\u0027, \u0027디즈니플러스 스타벅스\u0027 가입/이용 고객 - 혜택: 아메리카노(Tall) 1잔 무료(익월 말일까지 스타벅스 앱에 등록 후 이용 가능) - 이용횟수: 기간 내 1회 사용 가능 - 이용방법 : • 스타벅스 앱에 쿠폰 등록 후 이용 가능 • 스타벅스 앱에서 사이렌 오더 주문 시 이용 가능 ※ 쿠폰 발급 후 미사용 시에도 취소 및 환불, 이용 횟수 복원 불가 ※ 자세한 내용은 이벤트 페이지에서 확인 가능; applicationMenu=}",
                                                                                                            "requiredConditions":  "@{payments=System.Object[]; telcos=System.Object[]; memberships=System.Object[]; affiliations=System.Object[]}",
                                                                                                            "appliedByUserProfile":  true,
                                                                                                            "isDiscount":  true
                                                                                                        }
                                                                                                    ]
                                                                                  }
                                                                },
                                         "raw":  {
                                                     "success":  true,
                                                     "message":  "할인 정보 조회 완료",
                                                     "total":  10,
                                                     "results":  [
                                                                     {
                                                                         "inputStoreName":  "카페 평화",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "스노우까페",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "파머스 카트",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "마스터커피 가평점",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "호두이야기",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "별그랑베이커리카페 남이섬점",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "햇살드는카페",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "스타벅스 남이섬점",
                                                                         "matched":  true,
                                                                         "reason":  "해당 지점을 찾을 수 없습니다. (브랜드 기준 할인만 조회했습니다.)",
                                                                         "merchant":  {
                                                                                          "brand":  "@{brandId=1; brandName=스타벅스; brandOwner=}",
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [
                                                                                           "@{discountName=NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인; providerType=PAYMENT; providerName=우리카드; shape=; constraints=; requiredConditions=; appliedByUserProfile=False; isDiscount=True}",
                                                                                           "@{discountName=[VVIP]아메리카노(T) 한잔 무료 OR\n[VIP]더블 사이즈업 무료; providerType=TELCO; providerName=LG U+; shape=; constraints=; requiredConditions=; appliedByUserProfile=False; isDiscount=True}",
                                                                                           "@{discountName=전등급 [상시]사이즈업 [OTTX스타벅스] 아메리카노(Tall) 1잔 무료 VVIP [VVIP생일] 생일 조각케이크＋아메리카노 2잔 무료 [V/VIP 초이스] 아메리카노 Short 무료 또는 4,000원 할인 VIP [V/VIP 초이스] 아메리카노 Short 무료 또는 4,000원 할인; providerType=TELCO; providerName=KT; shape=; constraints=; requiredConditions=; appliedByUserProfile=True; isDiscount=True}"    
                                                                                        ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "에이치앤디남이섬점",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     },
                                                                     {
                                                                         "inputStoreName":  "카페앤",
                                                                         "matched":  false,
                                                                         "reason":  "해당 브랜드를 찾을 수 없습니다.",
                                                                         "merchant":  {
                                                                                          "brand":  null,
                                                                                          "branch":  null
                                                                                      },
                                                                         "discounts":  [

                                                                                       ]
                                                                     }
                                                                 ]
                                                 }
                                     },
        "user_profile": {
            "categories": [
                "모임",
                "분위기"
            ],
            "telco": "KT",
            "memberships": [
                "해피포인트"
            ],
            "cards": [
                "현대카드"
            ]
        },
        "user_latitude": 37.8065,
        "user_longitude": 127.5252,
        "stores_detail": None
    }

    engine = RecommendationEngine()

    print("\n=== RecommendationEngine sample debug ===")
    print(f"user_id: {sample_input['user_id']}")
    print(f"매장 수: {len(sample_input['stores'])}")
    print(f"할인 데이터 키 목록: {list(sample_input['discounts_by_store'].keys())}")
    
    missing_discounts = [
        store for store in sample_input["stores"]
        if store not in sample_input["discounts_by_store"]
    ]
    if missing_discounts:
        print("⚠️  할인 데이터가 연결되지 않은 매장:", ", ".join(missing_discounts))
    else:
        print("✅ 모든 매장에 대해 할인 데이터가 연결되었습니다.")

    try:
        base_data = engine._prepare_store_base_data(
            sample_input["stores"],
            sample_input["discounts_by_store"],
            sample_input["stores_detail"],
            sample_input["user_latitude"],
            sample_input["user_longitude"]
        )
        print(f"base_data 빌드 완료: {len(base_data)}개 매장")
    except Exception as exc:
        base_data = []
        print(f"base_data 준비 중 오류 발생: {exc}")
    
    try:
        recommendations = engine.process_recommendations(
            stores=sample_input["stores"],
            discounts_by_store=sample_input["discounts_by_store"],
            user_profile=sample_input["user_profile"],
            user_latitude=sample_input["user_latitude"],
            user_longitude=sample_input["user_longitude"],
            stores_detail=sample_input["stores_detail"]
        )
        print("\n추천 결과 JSON:")
        print(json.dumps(recommendations, ensure_ascii=False, indent=2))
    except Exception as exc:
        print("\nprocess_recommendations 실행 중 오류:")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()