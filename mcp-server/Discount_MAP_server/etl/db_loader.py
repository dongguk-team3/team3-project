from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, time

from db.connection import fetchrow, fetch, execute


class DiscountDBLoader:
    """
    정규화된 할인 레코드들을 받아서 discountdb에 넣는 클래스.
    """
    @staticmethod
    def _to_time(value: Any) -> Optional[time]:
        """
        문자열 / datetime / time / None 을 받아서
        datetime.time 또는 None 으로 변환한다.
        """
        if value is None or value == "":
            
            return None

        if isinstance(value, time):
            return value

        if isinstance(value, datetime):
            return value.time()

        if isinstance(value, str):
            # "HH:MM:SS" 또는 "HH:MM" 형식을 가정
            try:
                # 소수점(밀리초)이 붙어도 앞부분만 사용
                base = value.split(".")[0]
                return time.fromisoformat(base)
            except ValueError:
                print(f"[ETL] ⚠ time 파싱 실패: {value!r}")
                return None

        # 그 외 타입은 처리하지 않고 None
        return None

    async def load_discounts(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        success_count = 0
        fail_count = 0
        errors: List[str] = []

        for idx, rec in enumerate(records, start=1):
            try:
                await self._load_single_discount(rec)
                success_count += 1
            except Exception as e:
                fail_count += 1
                errors.append(f"[{idx}] {rec.get('discountName','<no name>')}: {e}")

        return {
            "total": len(records),
            "success": success_count,
            "failed": fail_count,
            "errors": errors,
        }

    async def _load_single_discount(self, rec: Dict[str, Any]) -> None:
        """
        한 개의 정규화된 할인 레코드를 받아서
        - 브랜드/지점 upsert
        - discount_provider + provider_detail upsert
        - discount_program upsert (+ PER_UNIT rule)
        - requiredConditions 매핑
        - discount_applicable_brand / discount_applicable_branch 매핑
        까지 한 번에 처리한다.
        """
        provider_type = rec["providerType"]       # 'TELCO', 'PAYMENT', 'MEMBERSHIP', 'AFFILIATION', ...
        provider_name = rec["providerName"].strip()
        discount_name = rec["discountName"].strip()

        # 1) 브랜드 / 지점 upsert → brand_id, branch_id 반환 (없으면 None)
        brand_id, branch_id = await self._upsert_brand_and_branch(rec)

        # 2) 프로바이더 upsert
        provider_id = await self._get_or_create_provider(provider_type, provider_name)

        # 2-1) 프로바이더 타입별 detail 테이블 upsert
        await self._upsert_provider_detail(provider_type, provider_id, rec)

        # 3) 할인 프로그램 upsert
        discount_id = await self._upsert_discount_program(provider_id, rec)

        # 4) PER_UNIT 규칙이 있을 경우 discount_per_unit_rule upsert
        if rec.get("discountType") == "PER_UNIT" and rec.get("unitRule"):
            await self._upsert_per_unit_rule(discount_id, rec["unitRule"])

        # 5) requiredConditions 매핑 (결제수단/통신사/멤버십/소속)
        req = rec.get("requiredConditions") or {}
        await self._apply_required_conditions(discount_id, req)

        # 6) 브랜드/지점 적용 매핑
        await self._link_discount_to_brand_branch(discount_id, brand_id, branch_id)

    # ---------------- 브랜드 / 지점 ----------------

    async def _upsert_brand_and_branch(self, rec: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
        """
        rec 안의 merchant.brand / merchant.branch 정보를 보고
        brand / brand_branch 를 upsert 한다.

        반환: (brand_id, branch_id)
        둘 중 없으면 None
        """
        merchant = rec.get("merchant") or {}

        brand_info = merchant.get("brand") or {}
        branch_info = merchant.get("branch") or {}

        # brandName/Owner는 merchant.brand 기준, 없으면 top-level fallback
        brand_name = brand_info.get("brandName") or rec.get("brandName")
        brand_owner = brand_info.get("brandOwner") or rec.get("brandOwner")

        if not brand_name:
            # 브랜드 정보가 아예 없으면 아무 것도 안 만든다.
            return None, None

        # 1) brand upsert
        row = await fetchrow(
            """
            SELECT brand_id
            FROM brand
            WHERE brand_name = $1
              AND COALESCE(brand_owner, '') = COALESCE($2, '')
            """,
            brand_name,
            brand_owner,
        )
        if row:
            brand_id = row["brand_id"]
        else:
            row = await fetchrow(
                """
                INSERT INTO brand (brand_name, brand_owner)
                VALUES ($1, $2)
                RETURNING brand_id
                """,
                brand_name,
                brand_owner,
            )
            brand_id = row["brand_id"]

        # 2) branch upsert
        # branchName은 merchant.branch 기준, 없으면 top-level fallback
        branch_name_raw = branch_info.get("branchName") or rec.get("branchName")
        if not branch_name_raw:
            # 지점 정보가 없으면 branch는 만들지 않는다.
            return brand_id, None

        # branchName 이 list 인 케이스 (예: ["동국대후문", "충무필동"])
        if isinstance(branch_name_raw, list):
            branch_name = str(branch_name_raw[0])
            print(f"[INFO] branchName 리스트 감지, 첫 번째 지점만 사용: {branch_name_raw} -> {branch_name}")
        else:
            branch_name = str(branch_name_raw)

        lat = branch_info.get("latitude")
        lon = branch_info.get("longitude")

        # 먼저 기존 브랜치가 있는지 확인 (좌표 없어도 찾을 수 있게)
        row = await fetchrow(
            """
            SELECT branch_id, latitude, longitude
            FROM brand_branch
            WHERE brand_id = $1
              AND branch_name = $2
            """,
            brand_id,
            branch_name,
        )

        if row:
            branch_id = row["branch_id"]

            # 새 좌표가 들어왔으면 업데이트
            if lat is not None or lon is not None:
                await execute(
                    """
                    UPDATE brand_branch
                    SET latitude = $2,
                        longitude = $3
                    WHERE branch_id = $1
                    """,
                    branch_id,
                    lat,
                    lon,
                )

            return brand_id, branch_id

        # 2-2) branch 신규 생성 (🔥 좌표 없어도 NULL로 생성)
        print(f"[INFO] branch 신규 생성 (좌표 NULL 허용): brand={brand_name}, branch={branch_name}")

        row = await fetchrow(
            """
            INSERT INTO brand_branch (
              brand_id,
              branch_name,
              latitude,
              longitude,
              is_active
            )
            VALUES ($1,$2,$3,$4,TRUE)
            RETURNING branch_id
            """,
            brand_id,
            branch_name,
            lat,
            lon,
        )

        return brand_id, row["branch_id"]


    async def _link_discount_to_brand_branch(
        self,
        discount_id: int,
        brand_id: Optional[int],
        branch_id: Optional[int],
    ) -> None:
        """
        discount_applicable_brand / discount_applicable_branch 테이블에
        이 할인 프로그램이 어떤 브랜드/지점에 적용되는지 매핑을 upsert 한다.
        """
        if brand_id is not None:
            await execute(
                """
                INSERT INTO discount_applicable_brand (discount_id, brand_id, is_excluded)
                VALUES ($1,$2,FALSE)
                ON CONFLICT (discount_id, brand_id) DO NOTHING
                """,
                discount_id,
                brand_id,
            )

        if branch_id is not None:
            await execute(
                """
                INSERT INTO discount_applicable_branch (discount_id, branch_id)
                VALUES ($1,$2)
                ON CONFLICT (discount_id, branch_id) DO NOTHING
                """,
                discount_id,
                branch_id,
            )

    # ---------------- provider ----------------

    async def _get_or_create_provider(self, provider_type: str, provider_name: str) -> int:
        row = await fetchrow(
            """
            SELECT provider_id
            FROM discount_provider
            WHERE provider_type = $1
              AND provider_name = $2
            """,
            provider_type,
            provider_name,
        )
        if row:
            return row["provider_id"]

        row = await fetchrow(
            """
            INSERT INTO discount_provider (provider_name, provider_type, is_active)
            VALUES ($1, $2, TRUE)
            RETURNING provider_id
            """,
            provider_name,
            provider_type,
        )
        return row["provider_id"]

    async def _upsert_provider_detail(self, provider_type: str, provider_id: int, rec: Dict[str, Any]) -> None:
        """
        provider_type 에 따라 detail 테이블들을 upsert 한다.
        - PAYMENT     → payment_provider_detail + payment_product
        - MEMBERSHIP  → membership_provider_detail
        - TELCO       → telco_provider_detail
        - AFFILIATION → affiliation_provider_detail
        """
        if provider_type == "PAYMENT":
            await self._upsert_payment_provider_detail_and_product(provider_id, rec)
        elif provider_type == "MEMBERSHIP":
            await self._upsert_membership_provider_detail(provider_id, rec)
        elif provider_type == "TELCO":
            await self._upsert_telco_provider_detail(provider_id, rec)
        elif provider_type == "AFFILIATION":
            await self._upsert_affiliation_provider_detail(provider_id, rec)
        else:
            # BRAND 등 다른 타입은 별도 detail 테이블이 없으니 스킵
            return

    async def _upsert_payment_provider_detail_and_product(
        self,
        provider_id: int,
        rec: Dict[str, Any],
    ) -> None:
        """
        카드사 크롤러(bccard, hyundaicard)용:
        - payment_provider_detail (card_company_code)
        - payment_product (개별 카드 상품)
        upsert 처리.
        """
        # 카드사 코드 (예: 'KB', 'SHINHAN', 'BC', ...)
        card_company_code = rec.get("cardCompanyCode") or rec.get("providerCode")

        if card_company_code:
            row = await fetchrow(
                """
                SELECT provider_id
                FROM payment_provider_detail
                WHERE provider_id = $1
                """,
                provider_id,
            )
            if row:
                await execute(
                    """
                    UPDATE payment_provider_detail
                    SET card_company_code = $2
                    WHERE provider_id = $1
                    """,
                    provider_id,
                    card_company_code,
                )
            else:
                await execute(
                    """
                    INSERT INTO payment_provider_detail (provider_id, card_company_code)
                    VALUES ($1,$2)
                    """,
                    provider_id,
                    card_company_code,
                )

        # 개별 카드 상품 (예: "더모아카드", "BLISS.7 카드" 등)
        payment_name = rec.get("paymentName")
        payment_company = rec.get("paymentCompany")

        if payment_name:
            row = await fetchrow(
                """
                SELECT payment_id
                FROM payment_product
                WHERE provider_id = $1
                  AND payment_name = $2
                """,
                provider_id,
                payment_name,
            )
            if row:
                # 회사명이 바뀌었으면 업데이트
                if payment_company:
                    await execute(
                        """
                        UPDATE payment_product
                        SET payment_company = $3
                        WHERE provider_id = $1
                          AND payment_name = $2
                        """,
                        provider_id,
                        payment_name,
                        payment_company,
                    )
            else:
                await execute(
                    """
                    INSERT INTO payment_product (provider_id, payment_name, payment_company)
                    VALUES ($1,$2,$3)
                    """,
                    provider_id,
                    payment_name,
                    payment_company,
                )

    async def _upsert_membership_provider_detail(self, provider_id: int, rec: Dict[str, Any]) -> None:
        """
        멤버십 크롤러(cjone, happypoint, lpoint)용:
        membership_provider_detail upsert.
        """
        membership_name = rec.get("membershipName") or rec.get("providerName")
        membership_level_required = rec.get("membershipLevelRequired") or rec.get("requiredLevel")

        if not membership_name:
            return

        row = await fetchrow(
            """
            SELECT provider_id
            FROM membership_provider_detail
            WHERE provider_id = $1
            """,
            provider_id,
        )
        if row:
            await execute(
                """
                UPDATE membership_provider_detail
                SET membership_name = $2,
                    membership_level_required = $3
                WHERE provider_id = $1
                """,
                provider_id,
                membership_name,
                membership_level_required,
            )
        else:
            await execute(
                """
                INSERT INTO membership_provider_detail (
                  provider_id,
                  membership_name,
                  membership_level_required
                )
                VALUES ($1,$2,$3)
                """,
                provider_id,
                membership_name,
                membership_level_required,
            )

    async def _upsert_telco_provider_detail(self, provider_id: int, rec: Dict[str, Any]) -> None:
        """
        통신사 크롤러(kt, lguplus, skt)용:
        telco_provider_detail upsert.
        """
        # telco_name: 'SKT', 'KT', 'LG U+'
        telco_name = rec.get("telcoName") or rec.get("providerName")
        # 앱 이름: 'T 멤버십', 'KT 멤버십', 'U+ 멤버스' 등
        telco_app_name = rec.get("telcoAppName") or rec.get("telcoMembershipName")
        membership_level_required = rec.get("membershipLevelRequired") or rec.get("requiredLevel")

        if not telco_name or not telco_app_name:
            # 둘 중 하나라도 없으면 detail은 만들지 않음
            return

        row = await fetchrow(
            """
            SELECT provider_id
            FROM telco_provider_detail
            WHERE provider_id = $1
            """,
            provider_id,
        )
        if row:
            await execute(
                """
                UPDATE telco_provider_detail
                SET membership_level_required = $2,
                    telco_name = $3,
                    telco_app_name = $4
                WHERE provider_id = $1
                """,
                provider_id,
                membership_level_required,
                telco_name,
                telco_app_name,
            )
        else:
            await execute(
                """
                INSERT INTO telco_provider_detail (
                  provider_id,
                  membership_level_required,
                  telco_name,
                  telco_app_name
                )
                VALUES ($1,$2,$3,$4)
                """,
                provider_id,
                membership_level_required,
                telco_name,
                telco_app_name,
            )

    async def _upsert_affiliation_provider_detail(self, provider_id: int, rec: Dict[str, Any]) -> None:
        """
        AFFILIATION 타입(동국대학교 등)용:
        affiliation_provider_detail upsert.
        """
        organization_name = rec.get("organizationName") or rec.get("providerName")
        eligibility_rule = rec.get("eligibilityRule") or rec.get("qualification")

        if not organization_name:
            return

        row = await fetchrow(
            """
            SELECT provider_id
            FROM affiliation_provider_detail
            WHERE provider_id = $1
            """,
            provider_id,
        )
        if row:
            await execute(
                """
                UPDATE affiliation_provider_detail
                SET organization_name = $2,
                    eligibility_rule = $3
                WHERE provider_id = $1
                """,
                provider_id,
                organization_name,
                eligibility_rule,
            )
        else:
            await execute(
                """
                INSERT INTO affiliation_provider_detail (
                  provider_id,
                  organization_name,
                  eligibility_rule
                )
                VALUES ($1,$2,$3)
                """,
                provider_id,
                organization_name,
                eligibility_rule,
            )

    # ---------------- discount_program (기존 + is_discount) ----------------

    async def _upsert_discount_program(self, provider_id: int, rec: Dict[str, Any]) -> int:
        """
        discount_program에 (provider_id, discount_name)을 기준으로
        이미 있으면 UPDATE, 없으면 INSERT.
        """
        discount_name = rec["discountName"].strip()

        existing = await fetchrow(
            """
            SELECT discount_id
            FROM discount_program
            WHERE provider_id = $1
              AND discount_name = $2
            """,
            provider_id,
            discount_name,
        )

        time_from = self._to_time(rec.get("timeFrom"))
        time_to = self._to_time(rec.get("timeTo"))

        params = {
            "provider_id": provider_id,
            "discount_name": discount_name,
            "discount_type": rec["discountType"],
            "discount_amount": rec.get("discountAmount", 0) or 0,
            "max_amount": rec.get("maxAmount"),
            "required_level": rec.get("requiredLevel"),
            "valid_from": rec.get("validFrom"),
            "valid_to": rec.get("validTo"),
            "dow_mask": rec.get("dowMask"),
            "time_from": time_from,
            "time_to": time_to,
            "channel_limit": rec.get("channelLimit"),
            "qualification": rec.get("qualification"),
            "application_menu": rec.get("applicationMenu"),
            "is_discount": bool(rec.get("isDiscount", True)),
        }

        if existing:
            discount_id = existing["discount_id"]
            await execute(
                """
                UPDATE discount_program
                SET discount_type    = $2,
                    discount_amount  = $3,
                    max_amount       = $4,
                    required_level   = $5,
                    valid_from       = $6,
                    valid_to         = $7,
                    dow_mask         = $8,
                    time_from        = $9,
                    time_to          = $10,
                    channel_limit    = $11,
                    qualification    = $12,
                    application_menu = $13,
                    is_discount      = $14,
                    is_active        = TRUE
                WHERE discount_id    = $1
                """,
                discount_id,
                params["discount_type"],
                params["discount_amount"],
                params["max_amount"],
                params["required_level"],
                params["valid_from"],
                params["valid_to"],
                params["dow_mask"],
                params["time_from"],
                params["time_to"],
                params["channel_limit"],
                params["qualification"],
                params["application_menu"],
                params["is_discount"],
            )
            return discount_id
        else:
            row = await fetchrow(
                """
                INSERT INTO discount_program (
                  provider_id,
                  discount_name,
                  discount_type,
                  discount_amount,
                  max_amount,
                  required_level,
                  valid_from,
                  valid_to,
                  dow_mask,
                  time_from,
                  time_to,
                  channel_limit,
                  qualification,
                  application_menu,
                  is_discount,
                  is_active
                )
                VALUES (
                  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,TRUE
                )
                RETURNING discount_id
                """,
                params["provider_id"],
                params["discount_name"],
                params["discount_type"],
                params["discount_amount"],
                params["max_amount"],
                params["required_level"],
                params["valid_from"],
                params["valid_to"],
                params["dow_mask"],
                params["time_from"],
                params["time_to"],
                params["channel_limit"],
                params["qualification"],
                params["application_menu"],
                params["is_discount"],
            )
            return row["discount_id"]

    # ---------------- PER_UNIT, requiredConditions, helper들 (기존 유지) ----------------

    async def _upsert_per_unit_rule(self, discount_id: int, unit_rule: Dict[str, Any]) -> None:
        existing = await fetchrow(
            """
            SELECT discount_id
            FROM discount_per_unit_rule
            WHERE discount_id = $1
            """,
            discount_id,
        )

        unit_amount = unit_rule.get("unitAmount")
        per_unit_value = unit_rule.get("perUnitValue")
        max_discount_amount = unit_rule.get("maxDiscountAmount")

        if existing:
            await execute(
                """
                UPDATE discount_per_unit_rule
                SET unit_amount         = $2,
                    per_unit_value      = $3,
                    max_discount_amount = $4
                WHERE discount_id       = $1
                """,
                discount_id,
                unit_amount,
                per_unit_value,
                max_discount_amount,
            )
        else:
            await execute(
                """
                INSERT INTO discount_per_unit_rule (
                  discount_id,
                  unit_amount,
                  per_unit_value,
                  max_discount_amount
                )
                VALUES ($1,$2,$3,$4)
                """,
                discount_id,
                unit_amount,
                per_unit_value,
                max_discount_amount,
            )

    async def _apply_required_conditions(self, discount_id: int, req: Dict[str, Any]) -> None:
        payments = req.get("payments") or []
        telcos = req.get("telcos") or []
        memberships = req.get("memberships") or []
        affiliations = req.get("affiliations") or []

        for p in payments:
            name = p.get("paymentName")
            if not name:
                continue
            payment_id = await self._find_payment_product(name)
            if payment_id is None:
                print(f"[WARN] payment_product 없음: {name}")
                continue
            await execute(
                """
                INSERT INTO discount_required_payment (discount_id, payment_id)
                VALUES ($1,$2)
                ON CONFLICT (discount_id, payment_id) DO NOTHING
                """,
                discount_id,
                payment_id,
            )

        for t in telcos:
            telco_name = t.get("telcoName")
            if not telco_name:
                continue
            telco_id = await self._find_telco_provider(telco_name)
            if telco_id is None:
                print(f"[WARN] telco_provider_detail 없음: {telco_name}")
                continue
            await execute(
                """
                INSERT INTO discount_required_telco (discount_id, telco_id)
                VALUES ($1,$2)
                ON CONFLICT (discount_id, telco_id) DO NOTHING
                """,
                discount_id,
                telco_id,
            )

        for m in memberships:
            mname = m.get("membershipName")
            if not mname:
                continue
            membership_id = await self._find_membership_provider(mname)
            if membership_id is None:
                print(f"[WARN] membership_provider_detail 없음: {mname}")
                continue
            await execute(
                """
                INSERT INTO discount_required_membership (discount_id, membership_id)
                VALUES ($1,$2)
                ON CONFLICT (discount_id, membership_id) DO NOTHING
                """,
                discount_id,
                membership_id,
            )

        for a in affiliations:
            oname = a.get("organizationName")
            if not oname:
                continue
            affiliation_id = await self._find_affiliation_provider(oname)
            if affiliation_id is None:
                print(f"[WARN] affiliation_provider_detail 없음: {oname}")
                continue
            await execute(
                """
                INSERT INTO discount_required_affiliation (discount_id, affiliation_id)
                VALUES ($1,$2)
                ON CONFLICT (discount_id, affiliation_id) DO NOTHING
                """,
                discount_id,
                affiliation_id,
            )

    async def _find_payment_product(self, payment_name: str) -> Optional[int]:
        row = await fetchrow(
            """
            SELECT payment_id
            FROM payment_product
            WHERE payment_name = $1
            """,
            payment_name,
        )
        return row["payment_id"] if row else None

    async def _find_telco_provider(self, telco_name: str) -> Optional[int]:
        row = await fetchrow(
            """
            SELECT provider_id
            FROM telco_provider_detail
            WHERE telco_name = $1
            """,
            telco_name,
        )
        return row["provider_id"] if row else None

    async def _find_membership_provider(self, membership_name: str) -> Optional[int]:
        row = await fetchrow(
            """
            SELECT provider_id
            FROM membership_provider_detail
            WHERE membership_name = $1
            """,
            membership_name,
        )
        return row["provider_id"] if row else None

    async def _find_affiliation_provider(self, organization_name: str) -> Optional[int]:
        row = await fetchrow(
            """
            SELECT provider_id
            FROM affiliation_provider_detail
            WHERE organization_name = $1
            """,
            organization_name,
        )
        return row["provider_id"] if row else None
