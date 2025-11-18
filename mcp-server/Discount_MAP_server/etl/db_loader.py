# etl/db_loader.py
"""
정규화된 할인 JSON을 discountdb(PostgreSQL)에 적재하는 모듈.

주의: 이제 discount_program 테이블에는
- can_be_combined 컬럼이 없고
- is_discount BOOLEAN 컬럼만 있다고 가정한다.
"""

from typing import Any, Dict, List, Optional

from db.connection import fetchrow, fetch, execute


class DiscountDBLoader:
    """
    정규화된 할인 레코드들을 받아서 discountdb에 넣는 클래스.
    """

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
        provider_type = rec["providerType"]       # 'TELCO', 'PAYMENT', ...
        provider_name = rec["providerName"].strip()
        discount_name = rec["discountName"].strip()

        provider_id = await self._get_or_create_provider(provider_type, provider_name)
        discount_id = await self._upsert_discount_program(provider_id, rec)

        if rec.get("discountType") == "PER_UNIT" and rec.get("unitRule"):
            await self._upsert_per_unit_rule(discount_id, rec["unitRule"])

        req = rec.get("requiredConditions") or {}
        await self._apply_required_conditions(discount_id, req)

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

    # ---------------- discount_program (여기가 제일 중요) ----------------

    async def _upsert_discount_program(self, provider_id: int, rec: Dict[str, Any]) -> int:
        """
        discount_program에 (provider_id, discount_name)을 기준으로
        이미 있으면 UPDATE, 없으면 INSERT.

        🔴 변경사항:
        - can_be_combined → is_discount (BOOLEAN)
        - 정규화 JSON에서 rec["isDiscount"]를 읽어서 저장
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
            "time_from": rec.get("timeFrom"),
            "time_to": rec.get("timeTo"),
            "channel_limit": rec.get("channelLimit"),
            "qualification": rec.get("qualification"),
            "application_menu": rec.get("applicationMenu"),
            # ✅ 새 컬럼: is_discount (정규화 JSON의 isDiscount 사용, 기본값 True)
            "is_discount": bool(rec.get("isDiscount", True)),
        }

        if existing:
            discount_id = existing["discount_id"]
            # ✅ UPDATE 시에도 is_discount 갱신
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
            # ✅ INSERT 시에도 is_discount 넣기
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

    # ---------------- 이하 그대로 (PER_UNIT, requiredConditions, helper들) ----------------

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
