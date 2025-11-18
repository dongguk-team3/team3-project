# services/discount_service.py
"""
할인 조회 비즈니스 로직.

이 파일은 "할인 서버의 머리" 역할을 한다.
- 어떤 DB 테이블에서 무엇을 가져올지
- 어떤 구조의 JSON으로 돌려줄지
- 사용자 프로필과 할인 조건을 어떻게 매칭할지

를 담당하고,
MCP 서버(discount_server.py)는 이 서비스를 그냥 불러서 결과만 전달하는 역할을 한다.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, time

from db.connection import fetch, fetchrow


class DiscountService:
    """
    할인 정보를 조회하는 서비스 클래스.
    """

    # -------------------------------
    # 1. 외부에서 직접 호출되는 메서드
    # -------------------------------
    async def get_discounts_for_stores(
        self,
        user_profile: Dict[str, Any],
        store_names: List[str],
    ) -> Dict[str, Any]:
        """
        사용자 프로필 + 매장명 리스트를 받아서,
        매장별 할인 정보 결과(JSON dict)를 리턴한다.

        store_names 예:
        - "스타벅스 동국대점"
        - "이디야커피 충무로역점"
        """

        try:
            normalized_profile = self._normalize_user_profile(user_profile)
            now = datetime.now()

            results: List[Dict[str, Any]] = []

            for store_str in store_names:
                store_result = await self._process_single_store(
                    store_str=store_str,
                    user_profile=normalized_profile,
                    now=now,
                )
                results.append(store_result)

            return {
                "success": True,
                "message": "할인 정보 조회 완료",
                "total": len(results),
                "results": results,
            }

        except Exception as e:
            # 여기서 예외를 잡아서 에러 JSON으로 감싸주면,
            # 바깥 MCP 쪽에서는 항상 "JSON 구조"를 기대할 수 있음
            return {
                "success": False,
                "error": f"할인 정보 조회 중 오류 발생: {e}"
            }

    # -------------------------------
    # 2. 사용자 프로필 정규화
    # -------------------------------
    def _normalize_user_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        사용자 프로필을 비교하기 쉽게 대문자/공백 제거 등 정리.

        입력 예:
        {
          "userId": "user123",
          "telco": "SKT",
          "memberships": ["CJ ONE", "해피포인트"],
          "cards": ["신한카드 YOLO Tasty"],
          "affiliations": ["동국대학교"]
        }
        """
        telco = profile.get("telco") or profile.get("telecom")

        memberships = profile.get("memberships") or []
        cards = profile.get("cards") or []
        affiliations = profile.get("affiliations") or []

        return {
            "userId": profile.get("userId"),
            "telco": telco.strip().upper() if telco else None,
            "memberships": [m.strip().upper() for m in memberships],
            "cards": [c.strip().upper() for c in cards],
            "affiliations": [a.strip().upper() for a in affiliations],
        }

    # -------------------------------
    # 3. 매장 하나 처리
    # -------------------------------
    async def _process_single_store(
        self,
        store_str: str,
        user_profile: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        """
        매장 문자열 하나("브랜드 지점명")를 처리해서
        최종 JSON 구조 하나(merchant + discounts)를 만들어낸다.
        """
        brand_name, branch_name = self._split_store_name(store_str)

        # 1) 브랜드 + 지점 조회
        brand_row, branch_row = await self._find_brand_and_branch(
            brand_name=brand_name,
            branch_name=branch_name,
        )

        # 1-1) 브랜드 자체를 못 찾은 경우
        if brand_row is None:
            return {
                "inputStoreName": store_str,
                "matched": False,
                "reason": "해당 브랜드를 찾을 수 없습니다.",
                "merchant": {
                    "brand": None,
                    "branch": None,
                },
                "discounts": [],
            }

        # 1-2) 브랜드는 있으나, 지점명을 줬는데 그 지점이 없는 경우
        if branch_name and branch_row is None:
            brand_info = {
                "brandId": brand_row["brand_id"],
                "brandName": brand_row["brand_name"],
                "brandOwner": brand_row["brand_owner"],
            }
            return {
                "inputStoreName": store_str,
                "matched": False,
                "reason": "해당 지점을 찾을 수 없습니다. (브랜드는 존재함)",
                "merchant": {
                    "brand": brand_info,
                    "branch": None,
                },
                "discounts": [],
            }

        # 1-3) 정상 매칭
        brand_info = {
            "brandId": brand_row["brand_id"],
            "brandName": brand_row["brand_name"],
            "brandOwner": brand_row["brand_owner"],
        }
        branch_info: Optional[Dict[str, Any]] = None
        branch_id: Optional[int] = None

        if branch_row is not None:
            branch_id = branch_row["branch_id"]
            branch_info = {
                "branchId": branch_row["branch_id"],
                "branchName": branch_row["branch_name"],
            }

        # 2) 현재 시점에 적용 가능한 할인 프로그램 조회
        discounts_raw = await self._find_applicable_discounts(
            brand_id=brand_row["brand_id"],
            branch_id=branch_id,
            now=now,
        )

        # 3) 각 할인 행을 JSON 구조로 변환
        discounts_list: List[Dict[str, Any]] = []
        for d in discounts_raw:
            entry = await self._build_discount_entry(
                discount_row=d,
                user_profile=user_profile,
            )
            discounts_list.append(entry)

        return {
            "inputStoreName": store_str,
            "matched": True,
            "reason": None,
            "merchant": {
                "brand": brand_info,
                "branch": branch_info,
            },
            "discounts": discounts_list,
        }

    # -------------------------------
    # 4. "브랜드 지점명" 문자열 파싱
    # -------------------------------
    def _split_store_name(self, store_str: str) -> Tuple[str, Optional[str]]:
        """
        "스타벅스 동국대점" → ("스타벅스", "동국대점")
        "이디야커피 충무로역점" → ("이디야커피", "충무로역점")
        공백이 없으면 → ("스타벅스", None)
        """
        store_str = store_str.strip()
        if " " not in store_str:
            return store_str, None
        brand_part, branch_part = store_str.split(" ", 1)
        return brand_part.strip(), branch_part.strip()

    # -------------------------------
    # 5. 브랜드 + 지점 DB 조회
    # -------------------------------
    async def _find_brand_and_branch(
        self,
        brand_name: str,
        branch_name: Optional[str],
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        brand, brand_branch 테이블에서 브랜드와 지점을 조회한다.
        """
        brand_row = await fetchrow(
            """
            SELECT brand_id, brand_name, brand_owner
            FROM brand
            WHERE brand_name = $1
            """,
            brand_name,
        )
        if brand_row is None:
            return None, None

        if branch_name is None:
            return brand_row, None

        branch_row = await fetchrow(
            """
            SELECT branch_id, brand_id, branch_name
            FROM brand_branch
            WHERE brand_id = $1
              AND branch_name = $2
            """,
            brand_row["brand_id"],
            branch_name,
        )
        return brand_row, branch_row

    # -------------------------------
    # 6. 할인 프로그램 조회
    # -------------------------------
    async def _find_applicable_discounts(
        self,
        brand_id: int,
        branch_id: Optional[int],
        now: datetime,
    ) -> List[Any]:
        """
        특정 브랜드/지점에 대해 현재 시점에 유효한 할인 프로그램을 모두 조회한다.

        체크하는 것:
        - is_active
        - 날짜(valid_from / valid_to)
        - 요일(dow_mask)
        - 시간(time_from / time_to)
        - brand / branch 대상 지정
        """
        today = now.date()
        isodow = now.isoweekday()  # 월=1 … 일=7
        current_time: time = now.time()

        rows = await fetch(
            """
            SELECT
              dp.*,
              p.provider_name,
              p.provider_type
            FROM discount_program dp
            JOIN discount_provider p
              ON p.provider_id = dp.provider_id
            LEFT JOIN discount_applicable_brand dab
              ON dab.discount_id = dp.discount_id
            LEFT JOIN discount_applicable_branch dabr
              ON dabr.discount_id = dp.discount_id
            WHERE dp.is_active
              AND (dp.valid_from IS NULL OR dp.valid_from <= $3)
              AND (dp.valid_to   IS NULL OR dp.valid_to   >= $3)
              AND (
                -- 브랜드 지정
                (dab.brand_id = $1 AND (dab.is_excluded = FALSE OR dab.is_excluded IS NULL))
                OR
                -- 지점 지정
                ($2::BIGINT IS NOT NULL AND dabr.branch_id = $2)
                OR
                -- 아무 대상도 지정되지 않은 경우(전 브랜드/전 지점)
                (dab.discount_id IS NULL AND dabr.discount_id IS NULL)
              )
              AND (
                dp.dow_mask IS NULL
                OR ( (dp.dow_mask & (1 << ($4 - 1))) <> 0 )
              )
              AND (
                dp.time_from IS NULL OR dp.time_to IS NULL
                OR ($5 BETWEEN dp.time_from AND dp.time_to)
              )
            ORDER BY p.provider_type, dp.discount_name
            """,
            brand_id,
            branch_id,
            today,
            isodow,
            current_time,
        )
        return rows

    # -------------------------------
    # 7. 할인 한 건을 JSON으로 변환
    # -------------------------------
    async def _build_discount_entry(
        self,
        discount_row: Any,
        user_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        discount_program + discount_provider 조인 결과 한 행을
        최종 JSON 구조 하나로 변환한다.
        """
        discount_id = discount_row["discount_id"]
        provider_type = discount_row["provider_type"]
        provider_name = discount_row["provider_name"]

        # shape: 할인 형태
        shape: Dict[str, Any] = {
            "kind": discount_row["discount_type"],           # 'PERCENT' | 'AMOUNT' | 'PER_UNIT'
            "amount": float(discount_row["discount_amount"]),
            "maxAmount": float(discount_row["max_amount"]) if discount_row["max_amount"] is not None else None,
            "unitRule": None,
        }

        # PER_UNIT인 경우 unitRule 추가
        if discount_row["discount_type"] == "PER_UNIT":
            per_unit = await fetchrow(
                """
                SELECT unit_amount, per_unit_value, max_discount_amount
                FROM discount_per_unit_rule
                WHERE discount_id = $1
                """,
                discount_id,
            )
            if per_unit:
                shape["unitRule"] = {
                    "unitAmount": float(per_unit["unit_amount"]),
                    "perUnitValue": float(per_unit["per_unit_value"]),
                    "maxDiscountAmount": float(per_unit["max_discount_amount"])
                    if per_unit["max_discount_amount"] is not None
                    else None,
                }

        # constraints: 제한 조건들
        constraints: Dict[str, Any] = {
            "validFrom": discount_row["valid_from"].isoformat() if discount_row["valid_from"] else None,
            "validTo": discount_row["valid_to"].isoformat() if discount_row["valid_to"] else None,
            "dayOfWeekMask": int(discount_row["dow_mask"]) if discount_row["dow_mask"] is not None else None,
            "timeFrom": discount_row["time_from"].isoformat() if discount_row["time_from"] else None,
            "timeTo": discount_row["time_to"].isoformat() if discount_row["time_to"] else None,
            "channelLimit": discount_row["channel_limit"],
            "requiredLevel": discount_row["required_level"],
            "qualification": discount_row["qualification"],
            "applicationMenu": discount_row["application_menu"],
        }

        # requiredConditions: 어떤 조건이 필요한지 (별도 테이블들에서 조회)
        required = await self._load_required_conditions(discount_id)

        # 사용자가 실제로 사용할 수 있는지 여부 (boolean)
        is_applicable = self._is_discount_applicable_to_user(
            user_profile=user_profile,
            required=required,
        )

        return {
            "discountId": discount_id,
            "discountName": discount_row["discount_name"],
            "providerType": provider_type,
            "providerName": provider_name,
            "shape": shape,
            "constraints": constraints,
            "requiredConditions": required,
            "appliedByUserProfile": is_applicable,
            "isDiscount": bool(discount_row.get("is_discount", True)),
        }

    # -------------------------------
    # 8. 할인 조건 매핑 로딩
    # -------------------------------
    async def _load_required_conditions(self, discount_id: int) -> Dict[str, Any]:
        """
        discount_required_* 테이블에서 이 할인에 필요한
        결제수단/통신사/멤버십/단체 정보를 모두 읽어온다.
        ID는 노출하지 않고 이름만 JSON으로 담는다.
        """
        # 결제수단
        payments = await fetch(
            """
            SELECT pp.payment_name
            FROM discount_required_payment d
            JOIN payment_product pp ON pp.payment_id = d.payment_id
            WHERE d.discount_id = $1
            """,
            discount_id,
        )
        payments_list = [
            {"paymentName": r["payment_name"]}
            for r in payments
        ]

        # 통신사
        telcos = await fetch(
            """
            SELECT t.telco_name, t.telco_app_name
            FROM discount_required_telco d
            JOIN telco_provider_detail t ON t.provider_id = d.telco_id
            WHERE d.discount_id = $1
            """,
            discount_id,
        )
        telcos_list = [
            {
                "telcoName": r["telco_name"],
                "telcoAppName": r["telco_app_name"],
            }
            for r in telcos
        ]

        # 멤버십
        memberships = await fetch(
            """
            SELECT m.membership_name
            FROM discount_required_membership d
            JOIN membership_provider_detail m ON m.provider_id = d.membership_id
            WHERE d.discount_id = $1
            """,
            discount_id,
        )
        memberships_list = [
            {"membershipName": r["membership_name"]}
            for r in memberships
        ]

        # 소속/단체
        affiliations = await fetch(
            """
            SELECT a.organization_name
            FROM discount_required_affiliation d
            JOIN affiliation_provider_detail a ON a.provider_id = d.affiliation_id
            WHERE d.discount_id = $1
            """,
            discount_id,
        )
        affiliations_list = [
            {"organizationName": r["organization_name"]}
            for r in affiliations
        ]

        return {
            "payments": payments_list,
            "telcos": telcos_list,
            "memberships": memberships_list,
            "affiliations": affiliations_list,
        }

    # -------------------------------
    # 9. 사용자 프로필로 이 할인을 쓸 수 있는지 판단
    # -------------------------------
    def _is_discount_applicable_to_user(
        self,
        user_profile: Dict[str, Any],
        required: Dict[str, Any],
    ) -> bool:
        """
        requiredConditions와 user_profile을 비교해서
        이 사용자가 이 할인을 "실제로 쓸 수 있는지" 여부를 판단한다.

        규칙(간단 버전):
        - requiredConditions가 전부 비어있으면: 누구나 사용 가능 → True
        - 그 외:
          - 통신사/멤버십/결제수단/소속 중 하나라도 사용자 프로필과 매칭되면 True
          - 아무 것도 안 맞으면 False
        """
        payments = required.get("payments", [])
        telcos = required.get("telcos", [])
        memberships = required.get("memberships", [])
        affiliations = required.get("affiliations", [])

        # 1) 아무 조건도 없는 할인 → 모두 사용 가능하다고 본다.
        if not payments and not telcos and not memberships and not affiliations:
            return True

        # 2) 통신사 매칭
        user_telco = user_profile.get("telco")
        if user_telco and telcos:
            for t in telcos:
                if user_telco == t["telcoName"].strip().upper():
                    return True

        # 3) 멤버십 매칭
        user_members = user_profile.get("memberships", [])
        if user_members and memberships:
            for m in memberships:
                name_upper = m["membershipName"].strip().upper()
                if name_upper in user_members:
                    return True

        # 4) 결제수단(카드) 매칭
        user_cards = user_profile.get("cards", [])
        if user_cards and payments:
            for p in payments:
                pay_upper = p["paymentName"].strip().upper()
                if pay_upper in user_cards:
                    return True

        # 5) 소속/단체 매칭
        user_affs = user_profile.get("affiliations", [])
        if user_affs and affiliations:
            for a in affiliations:
                org_upper = a["organizationName"].strip().upper()
                if org_upper in user_affs:
                    return True

        # 아무 조건도 안 맞았으면 False
        return False
