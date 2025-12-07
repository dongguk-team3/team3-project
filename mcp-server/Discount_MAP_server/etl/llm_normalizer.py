# etl/llm_normalizer.py
from __future__ import annotations

import os
import json
import asyncio
from datetime import date
from typing import Any, Dict, List, Optional
import re

from openai import OpenAI


def load_openai_api_key() -> str:
    """
    1순위: 환경 변수 OPENAI_API_KEY
    2순위: 프로젝트 루트에 있는 OPENAI_API.txt 파일
    """
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key.strip()

    try:
        here = os.path.dirname(__file__)
        key_file = os.path.join(here, "..", "OPENAI_API.txt")
        with open(key_file, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass

    raise RuntimeError("OPENAI_API_KEY not found in env or OPENAI_API.txt")


class LLMNormalizer:
    """
    각 제휴사 크롤러가 뱉은 raw JSON을
    discount_program 중심의 공통 스키마로 정규화하는 클래스.

    - output 레코드는 DiscountDBLoader._load_single_discount 의 rec 형태를 따른다.
    - 여기서는 "데이터를 새로 만들지 않고", raw 안에 존재하는 정보만을 LLM으로 구조화한다.
    """

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self.model = model
        api_key = load_openai_api_key()
        self.client = OpenAI(api_key=api_key)

    # ---------------- Public API ----------------

    async def normalize(self, source: str, raw: Any) -> List[Dict[str, Any]]:
        """
        source: 'happypoint' | 'kt' | 'skt' | 'lguplus' | 'lpoint' | 'cjone' | 'bccard' | 'hyundaicard'
        raw   : 각 크롤러의 결과(JSON-serializable)
        """
        source = source.lower()

        # 1) 완전 구조화된 규칙 기반 (LLM 안 씀)
        if source == "happypoint":
            return self._normalize_happypoint_structured(raw)

        if source == "hyundaicard":
            return self._normalize_hyundaicard_structured(raw)

        # 2) 통신 3사: 규칙 기반 처리 (LLM 제거)
        if source == "kt":
            return self._normalize_kt_structured(raw)

        if source == "skt":
            return self._normalize_skt_structured(raw)

        if source == "lguplus":
            return self._normalize_lguplus_structured(raw)

        # 3) 나머지 (LPOINT / CJONE / BCCARD 등)는 LLM 기반 generic 처리 유지
        if source == "lpoint":
            return await self._normalize_generic_with_llm(
                source="lpoint",
                provider_meta={
                    "providerType": "MEMBERSHIP",
                    "providerName": "L.POINT",
                    "membershipName": "L.POINT",
                },
                items=self._prepare_lpoint_items(raw),
            )
        if source == "cjone":
            return await self._normalize_generic_with_llm(
                source="cjone",
                provider_meta={
                    "providerType": "MEMBERSHIP",
                    "providerName": "CJ ONE",
                    "membershipName": "CJ ONE",
                },
                items=self._prepare_cjone_items(raw),
            )
        if source == "bccard":
            return await self._normalize_generic_with_llm(
                source="bccard",
                provider_meta={
                    "providerType": "PAYMENT",
                    "providerName": "BC카드",
                    "cardCompanyCode": "BC",
                    "paymentName": "BLISS.7 카드",
                    "paymentCompany": "BC카드",
                },
                items=self._prepare_simple_items_with_brand(raw, brand_key="store"),
            )

        # 4) 알 수 없는 소스는 그대로 LLM에 던지는 fallback
        return await self._normalize_generic_with_llm(
            source=source,
            provider_meta={
                "providerType": "BRAND",
                "providerName": source,
            },
            items=[{"brandName": None, "rawText": json.dumps(raw, ensure_ascii=False)}],
        )

    # ---------------- Structured normalizers (rule-based) ----------------

    def _normalize_happypoint_structured(self, raw: Any) -> List[Dict[str, Any]]:
        """
        happypoint_crawler.fetch_happypoint_brands() 결과:

        {
          "source": "...",
          "count": 20,
          "brands": [
            {
              "brandName": "...",
              "description": "...",
              "accrualPercents": [5.0],
              "link": "...",
              "rawSnippet": "..."
            },
            ...
          ]
        }

        → 전부 "적립" 프로그램으로 변환 (isDiscount = False)
        """
        brands = (raw or {}).get("brands") or []
        programs: List[Dict[str, Any]] = []

        for b in brands:
            brand_name = (b.get("brandName") or "").strip()
            if not brand_name:
                continue

            accrual_percents = b.get("accrualPercents") or []
            percent = None
            if accrual_percents:
                try:
                    percent = float(accrual_percents[0])
                except (TypeError, ValueError):
                    percent = None

            discount_name = f"{brand_name} 포인트 적립"

            rec: Dict[str, Any] = {
                "providerType": "MEMBERSHIP",
                "providerName": "해피포인트",
                "membershipName": "해피포인트",
                "discountName": discount_name,
                "discountType": "PERCENT",
                "discountAmount": percent or 0.0,
                "maxAmount": None,
                "maxUsageCnt": None,
                "requiredLevel": None,
                "validFrom": None,
                "validTo": None,
                "dowMask": None,
                "timeFrom": None,
                "timeTo": None,
                "channelLimit": None,
                "qualification": None,
                "applicationMenu": None,
                "isDiscount": False,
                "unitRule": None,
                "requiredConditions": {
                    "payments": [],
                    "telcos": [],
                    "memberships": [
                        {"membershipName": "해피포인트"},
                    ],
                    "affiliations": [],
                },
                "merchant": {
                    "brand": {
                        "brandName": brand_name,
                        "brandOwner": None,
                    },
                    "branch": {},
                },
            }
            programs.append(rec)

        return programs

    def _normalize_hyundaicard_structured(self, raw: Any) -> List[Dict[str, Any]]:
        """
        hyundaicard_crawler.fetch_hyundaicard_mpoints() 결과를
        'M' 카드 하나의 PAYMENT 혜택으로 변환.
        """
        programs: List[Dict[str, Any]] = []

        def parse_date(d: Optional[str]) -> Optional[str]:
            """
            '2025.11.05' 같은 문자열을 '2025-11-05' 형식의 문자열로 변환.
            실제 DATE 타입으로 바꾸는 건 DiscountDBLoader에서 처리.
            """
            if not d:
                return None
            d = d.strip()
            parts = d.split(".")
            if len(parts) != 3:
                return None

            y, m, day = parts
            try:
                return date(int(y), int(m), int(day))
            except ValueError:
                return None

        def make_program(item: Dict[str, Any], category: str) -> Dict[str, Any]:
            import re

            name = (item.get("name") or "").strip()
            subtitle = (item.get("subtitle") or "").strip()
            category_name = (item.get("category_name") or category or "").strip()
            period = item.get("period") or {}
            start = parse_date(period.get("start"))
            end = parse_date(period.get("end"))

            discount_type = "PERCENT"
            discount_amount: float = 0.0
            is_discount = True

            m = re.search(r"(\d+(?:\.\d+)?)\s*%", subtitle)
            if m:
                discount_type = "PERCENT"
                discount_amount = float(m.group(1))
            else:
                digits = re.findall(r"\d+", subtitle)
                if digits:
                    discount_type = "AMOUNT"
                    discount_amount = float(digits[0])
                else:
                    discount_type = "AMOUNT"
                    discount_amount = 0.0

            discount_name = f"{name} M포인트 사용"

            rec: Dict[str, Any] = {
                "providerType": "PAYMENT",
                "providerName": "현대카드",
                "cardCompanyCode": "HYUNDAI",
                "paymentName": "M",
                "paymentCompany": "현대카드",
                "discountName": discount_name,
                "discountType": discount_type,
                "discountAmount": discount_amount,
                "maxAmount": None,
                "maxUsageCnt": None,
                "requiredLevel": None,
                "validFrom": start,
                "validTo": end,
                "dowMask": None,
                "timeFrom": None,
                "timeTo": None,
                "channelLimit": None,
                "qualification": subtitle or None,
                "applicationMenu": category_name or None,
                "isDiscount": is_discount,
                "unitRule": None,
                "requiredConditions": {
                    "payments": [
                        {"paymentName": "M"},
                    ],
                    "telcos": [],
                    "memberships": [],
                    "affiliations": [],
                },
                "merchant": {
                    "brand": {
                        "brandName": name,
                        "brandOwner": None,
                    },
                    "branch": {},
                },
            }
            return rec

        for category, items in (raw or {}).items():
            if not isinstance(items, list):
                continue
            for it in items:
                programs.append(make_program(it, category))

        return programs

    # ---------- New: KT / SKT / LGU+ 규칙 기반 정규화 ----------

    def _normalize_kt_structured(self, raw: Any) -> List[Dict[str, Any]]:
        """
        KT 크롤러 결과(항상 아래 형식의 list 라고 가정):

        [
          {
            "brandName": "SFG",
            "summary": "...",      # → discountName
            "usageLimit": "...",   # → maxUsageCnt (월 N회 파싱)
            "guide": "...",        # → qualification
            "contact": "..."
          },
          ...
        ]
        """
        programs: List[Dict[str, Any]] = []

        for entry in raw or []:
            if not isinstance(entry, dict):
                continue

            brand_name = (entry.get("brandName") or "").strip()
            if not brand_name:
                continue

            summary = (entry.get("summary") or "").strip()
            usage_limit = (entry.get("usageLimit") or "").strip()
            guide = (entry.get("guide") or "").strip()

            discount_type, discount_amount, unit_rule = self._parse_discount_with_unit(summary)
            max_cnt = self._parse_max_usage_from_usagelimit(usage_limit)

            qual_parts: List[str] = []
            if usage_limit:
                qual_parts.append(usage_limit)
            if guide:
                qual_parts.append(guide)
            qualification = "\n".join(qual_parts) or None

            rec: Dict[str, Any] = {
                "providerType": "TELCO",
                "providerName": "KT",
                "telcoName": "KT",
                "telcoAppName": "KT 멤버십",
                "discountName": summary or f"{brand_name} 제휴 혜택",
                "discountType": discount_type,
                "discountAmount": discount_amount,
                "maxAmount": None,
                "maxUsageCnt": max_cnt,
                "requiredLevel": None,
                "validFrom": None,
                "validTo": None,
                "dowMask": None,
                "timeFrom": None,
                "timeTo": None,
                "channelLimit": None,
                "qualification": qualification,
                "applicationMenu": None,
                "isDiscount": True,  # KT 크롤러는 전부 할인 혜택이라고 가정
                "unitRule": unit_rule if discount_type == "PER_UNIT" else None,
                "requiredConditions": {
                    "payments": [],
                    "telcos": [{"telcoName": "KT"}],
                    "memberships": [],
                    "affiliations": [],
                },
                "merchant": {
                    "brand": {
                        "brandName": brand_name,
                        "brandOwner": None,
                    },
                    "branch": {},
                },
            }
            programs.append(rec)

        return programs

    def _normalize_skt_structured(self, raw: Any) -> List[Dict[str, Any]]:
        """
        SKT 크롤러 결과:

        [
          {
            "brandId": "1053",
            "brandName": "파리바게뜨",
            "categoryId": "53",
            "categoryName": "베이커리",
            "benefits": [
              {
                "variantType": "할인형" | "적립형",
                "membershipLevels": ["VIP", "GOLD"],
                "description": "천원당 100원 할인 ..."
              },
              ...
            ],
            "notes": [ "문장1", "문장2", ... ]
          },
          ...
        ]

        매 benefit 당 discount 하나 생성
        """
        programs: List[Dict[str, Any]] = []

        for brand_info in raw or []:
            if not isinstance(brand_info, dict):
                continue

            brand_name = (brand_info.get("brandName") or "").strip()
            if not brand_name:
                continue

            category_name = (brand_info.get("categoryName") or "").strip() or None
            notes_list = brand_info.get("notes") or []
            notes_text = "\n".join(str(n).strip() for n in notes_list if str(n).strip()) or None

            benefits = brand_info.get("benefits") or []
            for benefit in benefits:
                if not isinstance(benefit, dict):
                    continue

                variant_type = (benefit.get("variantType") or "").strip()
                levels = benefit.get("membershipLevels") or []
                levels_str = "/".join(str(l).strip() for l in levels if str(l).strip()) or None
                desc = (benefit.get("description") or "").strip()
                if not desc:
                    continue

                discount_type, discount_amount, unit_rule = self._parse_discount_with_unit(desc)
                max_cnt = self._parse_max_usage_from_usagelimit(notes_text)

                is_discount = True
                if "적립형" in variant_type:
                    is_discount = False
                elif "할인형" in variant_type:
                    is_discount = True

                rec: Dict[str, Any] = {
                    "providerType": "TELCO",
                    "providerName": "SKT",
                    "telcoName": "SKT",
                    "telcoAppName": "T 멤버십",
                    "discountName": desc,
                    "discountType": discount_type,
                    "discountAmount": discount_amount,
                    "maxAmount": None,
                    "maxUsageCnt": max_cnt,
                    "requiredLevel": levels_str,
                    "validFrom": None,
                    "validTo": None,
                    "dowMask": None,
                    "timeFrom": None,
                    "timeTo": None,
                    "channelLimit": None,
                    "qualification": notes_text,
                    "applicationMenu": None,
                    "isDiscount": is_discount,
                    "unitRule": unit_rule if discount_type == "PER_UNIT" else None,
                    "requiredConditions": {
                        "payments": [],
                        "telcos": [{"telcoName": "SKT"}],
                        "memberships": [],
                        "affiliations": [],
                    },
                    "merchant": {
                        "brand": {
                            "brandName": brand_name,
                            "brandOwner": None,
                        },
                        "branch": {},
                    },
                }
                programs.append(rec)

        return programs

    def _normalize_lguplus_structured(self, raw: Any) -> List[Dict[str, Any]]:
        """
        lguplus 크롤러 결과 (VIP 콕 반환):

        {
          "vipSummary": {...},
          "brands": {
            "스타벅스": {
              "brandName": "스타벅스",
              "benefitSummary": "...",
              "benefitDetail": "...",
              "usageGuide": "...",
              "grade": "VVIP/VIP",
              ...
            },
            ...
          }
        }
        """
        programs: List[Dict[str, Any]] = []
        if not isinstance(raw, dict):
            return programs

        brands = raw.get("brands") or {}
        if not isinstance(brands, dict):
            return programs

        for brand_key, info in brands.items():
            if not isinstance(info, dict):
                continue

            brand_name = (info.get("brandName") or brand_key or "").strip()
            if not brand_name:
                continue

            benefit_summary = (info.get("benefitSummary") or "").strip()
            benefit_detail = (info.get("benefitDetail") or "").strip()
            usage_guide = (info.get("usageGuide") or "").strip()
            grade = (info.get("grade") or "").strip() or None
            intro = (info.get("intro") or "").strip()

            discount_type, discount_amount, unit_rule = self._parse_discount_with_unit(benefit_summary)
            max_cnt = self._parse_max_usage_from_usagelimit(benefit_detail)

            qual_parts: List[str] = []
            if benefit_detail:
                qual_parts.append(benefit_detail)
            if usage_guide:
                qual_parts.append(usage_guide)
            qualification = "\n".join(qual_parts) or None

            rec: Dict[str, Any] = {
                "providerType": "TELCO",
                "providerName": "LG U+",
                "telcoName": "LG U+",
                "telcoAppName": "U+ 멤버십",
                "discountName": benefit_summary or f"{brand_name} VIP 콕 혜택",
                "discountType": discount_type,
                "discountAmount": discount_amount,
                "maxAmount": None,
                "maxUsageCnt": max_cnt,
                "requiredLevel": grade,
                "validFrom": None,
                "validTo": None,
                "dowMask": None,
                "timeFrom": None,
                "timeTo": None,
                "channelLimit": None,
                "qualification": qualification,
                "applicationMenu": None,
                "isDiscount": True,
                "unitRule": unit_rule if discount_type == "PER_UNIT" else None,
                "requiredConditions": {
                    "payments": [],
                    "telcos": [{"telcoName": "LG U+"}],
                    "memberships": [],
                    "affiliations": [],
                },
                "merchant": {
                    "brand": {
                        "brandName": brand_name,
                        "brandOwner": None,
                    },
                    "branch": {},
                },
            }
            programs.append(rec)

        return programs

    # ---------------- Item preparation helpers (LLM용 – KT/SKT/LGU+는 사용 안 함) ----------------

    def _prepare_simple_items_with_brand(self, raw: Any, brand_key: str) -> List[Dict[str, Any]]:
        """
        단순히 brandKey 하나만 있는 구조(bccard 등)를 위한 헬퍼.
        """
        items: List[Dict[str, Any]] = []
        for entry in raw or []:
            brand = (entry.get(brand_key) or "").strip() or None
            raw_text = json.dumps(entry, ensure_ascii=False)
            items.append(
                {
                    "brandName": brand,
                    "rawText": raw_text,
                }
            )
        return items

    def _prepare_lpoint_items(self, raw: Any) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not isinstance(raw, dict):
            return items

        affiliates = raw.get("affiliates") or []
        for aff in affiliates:
            brand = (aff.get("brandName") or "").strip() or None

            benefit_title = (aff.get("benefitTitle") or "").strip()
            detail_text = (aff.get("detailText") or "").strip()
            status = (aff.get("status") or "").strip()

            chunks = []
            if benefit_title:
                chunks.append(f"[benefitTitle] {benefit_title}")
            if detail_text:
                chunks.append(f"[detailText] {detail_text}")
            if status:
                chunks.append(f"[status] {status}")

            raw_text = "\n".join(chunks) or json.dumps(aff, ensure_ascii=False)

            items.append(
                {
                    "brandName": brand,
                    "rawText": raw_text,
                    # ✅ 나중에 override에서 쓰려고 원본도 같이 실어 줌
                    "benefitTitle": benefit_title,
                    "status": status,
                }
            )
        return items

    def _extract_channel_limit_from_status(self, status: str) -> Optional[str]:
        """
        LPOINT status 문구에서 온라인/오프라인 제약을 간단히 요약해서 반환.

        예시 매핑 (대략적인 규칙):
        - "온라인", "모바일", "앱" 만 있으면 → "온라인 전용"
        - "오프라인", "매장" 만 있으면 → "오프라인 전용"
        - 온라인/오프라인 둘 다 있으면 → "온라인/오프라인"
        - 못 찾으면 None
        """
        if not status:
            return None

        s = status.replace(" ", "").lower()

        has_online = any(k in s for k in ["온라인", "모바일", "app", "앱"])
        has_offline = any(k in s for k in ["오프라인", "매장"])

        if has_online and not has_offline:
            return "ONLINE"
        if has_offline and not has_online:
            return "OFFLINE"
        if has_online and has_offline:
            return "ONLINE/OFFLINE"

        return None



    def _prepare_cjone_items(self, raw: Any) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for entry in raw or []:
            brand = (entry.get("detail_title") or "").strip() or None
            chunks = []
            desc = entry.get("detail_desc")
            if desc:
                chunks.append(desc)
            sections = entry.get("benefit_sections") or []
            for sec in sections:
                title = sec.get("title")
                for item in sec.get("items") or []:
                    if title:
                        chunks.append(f"[{title}] {item}")
                    else:
                        chunks.append(item)
            raw_text = "\n".join(chunks)
            items.append(
                {
                    "brandName": brand,
                    "rawText": raw_text,
                }
            )
        return items

    # ---------------- Generic LLM-based normalizer ----------------

    async def _normalize_generic_with_llm(
        self,
        source: str,
        provider_meta: Dict[str, Any],
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        programs: List[Dict[str, Any]] = []
        for item in items:
            brand_name: Optional[str] = item.get("brandName")
            raw_text: str = item.get("rawText") or ""

            if not raw_text.strip():
                continue

            llm_input = {
                "source": source,
                "providerMeta": provider_meta,
                "brandName": brand_name,
                "rawText": raw_text,
            }

            try:
                obj = await self._call_llm_for_programs(llm_input)
            except Exception as e:  # noqa: BLE001
                print(f"[LLMNormalizer] {source}({brand_name}) 정규화 중 예외: {e}")
                continue

            recs = obj.get("programs") if isinstance(obj, dict) else None
            if not isinstance(recs, list):
                continue

            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                self._merge_provider_meta(rec, provider_meta, brand_name)
                self._apply_item_overrides(source, rec, item)
                self._fill_defaults(rec)
                programs.append(rec)

        return programs

    async def _call_llm_for_programs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = """
너는 카드/통신사/멤버십 할인 정보를 PostgreSQL에 넣기 위한 JSON으로 정규화하는 도우미야.

반드시 아래 규칙을 지켜.

1. 절대 새로운 정보를 상상하거나 만들어내지 마.
   - rawText 안에 "명시적으로 쓰여 있는 내용"만 사용해.
   - 문맥상 추론이 애매하면, 그 필드는 null 로 두고 전체 텍스트를 qualification 에 남겨.

2. 출력 형식
   - 항상 JSON object 하나만 반환하고, 그 안에 programs 배열을 넣어.
   - 예시:
     {
       "programs": [
         {
           "discountName": "...",
           "discountType": "PERCENT" | "AMOUNT" | "PER_UNIT",
           "discountAmount": 10,
           "maxAmount": null,
           "maxUsageCnt": null,
           "requiredLevel": null,
           "validFrom": null,
           "validTo": null,
           "dowMask": null,
           "timeFrom": null,
           "timeTo": null,
           "channelLimit": null,
           "qualification": "...",
           "applicationMenu": null,
           "isDiscount": true,
           "unitRule": null,
           "requiredConditions": {
             "payments": [],
             "telcos": [],
             "memberships": [],
             "affiliations": []
           },
           "merchant": {
             "brand": {
               "brandName": null,
               "brandOwner": null
             },
             "branch": {}
           }
         }
       ]
     }

3. 각 필드 채우는 법 (모호하면 null):
   - discountName:
     - 혜택 이름/요약 문구를 그대로 사용.
   - discountType / discountAmount:
     - "10% 할인" 등 퍼센트가 명시되면: discountType = "PERCENT", discountAmount = 10 (실수/정수 상관 없음).
     - "2,000원 할인", "4천원 할인" 등 금액이 명시되면: discountType = "AMOUNT", discountAmount = 2000.
     - 정확한 수치가 없으면: discountAmount = 0 으로 두고, 구체 설명은 qualification 에 넣어.
   - maxAmount:
     - "최대 2만원 할인"처럼 '최대 할인 금액' 이 명확히 적혀 있을 때만 채워.
     - 아니면 null.
   - maxUsageCnt:
     - "월 1회", "1일 1회", "월 2회" 같은 사용 횟수가 있을 때만 정수로 채워.
     - 단, 기간(1일/1달)은 rawText 에 그대로 두고, 여기에는 그냥 횟수만 넣어도 됨.
   - requiredLevel:
     - "VIP/GOLD/SILVER" 같은 '등급' 문구가 있으면 그대로 사용.
   - validFrom / validTo:
     - rawText 에서 '~까지', '기간' 등이 명확히 표기된 경우에만 사용.
     - 날짜 포맷이 애매하면 null 로 두고 qualification 에 텍스트만 남겨.
   - dowMask, timeFrom, timeTo, channelLimit:
     - 요일/시간/온라인전용/오프라인전용 같은 제약이 rawText 에 정확히 적혀 있을 때만 요약해서 쓰고, 아니면 null.
   - qualification:
     - 사용 조건, 유의사항, 제약 사항을 사람 읽기 좋은 한국어로 한 문단으로 요약해.
     - 단, 원문에 없는 내용은 절대 추가하지 말 것.
   - applicationMenu:
     - "커피", "음료", "피자", "버거", "제조음료", "싱글레귤러" 같은 혜택 적용 대상이 명확하면 짧게 요약.
   - isDiscount:
     - '할인형', '할인', '무료' 등 "가격이 줄어드는" 혜택이면 true.
     - '적립형', '포인트 적립' 등 포인트를 주는 혜택이면 false.
     - 둘다 섞여 있으면, 해당 program 이 무엇을 설명하는지 보고 결정. 애매하면 true 로 두고 qualification 에 상세를 남겨.
   - unitRule:
     - discountType 이 "PER_UNIT" 인 경우에만 사용 (예: "1,000원당 100원 할인" 처럼 단위당 혜택).
     - 이 경우가 아니면 null.

4. requiredConditions:
   - 이 필드는 외부에서 providerMeta 로 채워질 수 있으므로,
     여기서는 기본 구조만 유지해.
   - payments, telcos, memberships, affiliations 는 배열만 유지하고 안을 마음대로 채우지 마.
   - rawText 에 특정 카드/통신사/멤버십 이름이 있어도, 이 필드는 건드리지 말고 qualification 에만 적어.

5. merchant:
   - brand.brandName 은 호출 시 이미 채워질 수 있으니 여기서 새로 만들지 마.
   - brandOwner, branch 는 모르면 null / {} 로 둬.

6. 절대 하지 말아야 할 것:
   - rawText 에 없는 "월 1회", "최대 1만원" 등을 상상해서 넣기.
   - 구체적인 숫자가 없는 문구를 임의의 숫자로 해석하기.
   - 출력 최상위에 programs 말고 다른 키를 추가하기.
        """

        user_content = json.dumps(payload, ensure_ascii=False)

        def _call() -> str:
            resp = self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
            )
            return resp.choices[0].message.content

        content = await asyncio.to_thread(_call)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"programs": []}

    # ---------------- post-process helpers ----------------

    def _merge_provider_meta(
        self,
        rec: Dict[str, Any],
        provider_meta: Dict[str, Any],
        brand_name: Optional[str],
    ) -> None:
        rec.setdefault("providerType", provider_meta.get("providerType"))
        rec.setdefault("providerName", provider_meta.get("providerName"))

        for key in ("cardCompanyCode", "paymentName", "paymentCompany"):
            if key in provider_meta:
                rec.setdefault(key, provider_meta[key])

        for key in ("membershipName", "telcoName", "telcoAppName"):
            if key in provider_meta:
                rec.setdefault(key, provider_meta[key])

        merchant = rec.get("merchant") or {}
        brand_info = merchant.get("brand") or {}
        branch_info = merchant.get("branch") or {}

        if brand_name and not brand_info.get("brandName"):
            brand_info["brandName"] = brand_name

        brand_info.setdefault("brandOwner", None)
        branch_info.setdefault("branchName", branch_info.get("branchName"))

        rec["merchant"] = {
            "brand": brand_info,
            "branch": branch_info,
        }

        rc = rec.get("requiredConditions") or {}
        rc.setdefault("payments", [])
        rc.setdefault("telcos", [])
        rc.setdefault("memberships", [])
        rc.setdefault("affiliations", [])

        if provider_meta.get("providerType") == "TELCO":
            telco_name = provider_meta.get("telcoName")
            if telco_name and not rc["telcos"]:
                rc["telcos"] = [{"telcoName": telco_name}]
        if provider_meta.get("providerType") == "MEMBERSHIP":
            membership_name = provider_meta.get("membershipName")
            if membership_name and not rc["memberships"]:
                rc["memberships"] = [{"membershipName": membership_name}]
        if provider_meta.get("providerType") == "PAYMENT":
            payment_name = provider_meta.get("paymentName")
            if payment_name and not rc["payments"]:
                rc["payments"] = [{"paymentName": payment_name}]

        rec["requiredConditions"] = rc
    
    def _parse_discount_from_text(self, text: Optional[str]) -> Tuple[str, float]:
        """
        일반적인 할인/적립 문장에서 discountType, discountAmount 를 추출한다.

        - 퍼센트가 있으면: ("PERCENT", 퍼센트값)
        예) "10% 할인", "5.5% 적립"
        - 금액(원)이 있으면: ("AMOUNT", 금액)
        예) "2,000원 할인", "3000원 캐시백", "1만원 할인 쿠폰", "5천원 상품권"
        - 아무 것도 못 찾으면: ("AMOUNT", 0.0)
        """
        if not text:
            return "AMOUNT", 0.0

        s = str(text)

        # 1) 퍼센트 패턴: 10%, 5.5 %
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                val = 0.0
            return "PERCENT", val

        # --------------------------
        # 2) 금액(원) 패턴 (혜택 위주)
        #    - 1만원 할인 쿠폰
        #    - 5천원 할인
        #    - 10,000원 상품권
        # --------------------------
        benefit_suffix = r"(?:할인|쿠폰|상품권|적립|캐시백)"

        # 2-1) x만원 할인/쿠폰/상품권/적립/캐시백
        m = re.search(r"(\d+)\s*만\s*원?\s*" + benefit_suffix, s)
        if m:
            try:
                amount = int(m.group(1)) * 10000
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # 2-2) x천원 할인/쿠폰/상품권/적립/캐시백
        m = re.search(r"(\d+)\s*천\s*원?\s*" + benefit_suffix, s)
        if m:
            try:
                amount = int(m.group(1)) * 1000
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # 2-3) 숫자원 + 혜택 키워드 (예: 6,500원 할인 쿠폰, 5000원 상품권)
        m = re.search(r"(\d[\d,]*)\s*원\s*" + benefit_suffix, s)
        if m:
            try:
                amount = int(m.group(1).replace(",", ""))
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # --------------------------
        # 3) fallback: 맥락 상관없이 아무 금액이나 (조건 금액까지 포함될 수 있음)
        #    기존 너 로직을 그대로 살려둔다.
        # --------------------------

        # 3-1) 1,000원 / 2000원 같은 패턴
        m = re.search(r"(\d[\d,]*)\s*원", s)
        if m:
            try:
                amount = int(m.group(1).replace(",", ""))
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # 3-2) '2천원', '3천원' 같은 표현
        m = re.search(r"(\d+)\s*천원", s)
        if m:
            try:
                amount = int(m.group(1)) * 1000
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # 3-3) '1만원' 같은 표현 (마지막 보정용)
        m = re.search(r"(\d+)\s*만원", s)
        if m:
            try:
                amount = int(m.group(1)) * 10000
                return "AMOUNT", float(amount)
            except ValueError:
                pass

        # 그 외에는 숫자가 있어도 애매하면 0으로 본다.
        return "AMOUNT", 0.0


    def _parse_discount_with_unit(self, text: str):
        """
        1) 우선 '당' 기반 unitRule을 시도
        2) 성공하면 discountType='PER_UNIT', discountAmount=perUnitValue
        3) 실패하면 기존 퍼센트/정액 파싱으로 fallback
        """
        unit_rule = self._parse_unit_rule(text)

        if unit_rule:
            discount_type = "PER_UNIT"
            discount_amount = float(unit_rule["perUnitValue"])
            return discount_type, discount_amount, unit_rule

        # fallback: 기존 일반 할인 파서
        discount_type, discount_amount = self._parse_discount_from_text(text)
        return discount_type, discount_amount, None


    def _parse_unit_rule(self, text: str) -> Optional[Dict[str, Any]]:
        """
        '천원당 100원 할인', '1000원당 150P 적립', '2천원당 200원(최대600원)' 등에서
        unitAmount / perUnitValue / maxDiscountAmount 를 추출한다.
        """
        if not text or "당" not in text:
            return None

        s = str(text)

        # -------------------------
        # 1) '당'을 기준으로 앞뒤 split
        # -------------------------
        left, right = s.split("당", 1)
        left = left.strip()
        right = right.strip()

        # -------------------------
        # 2) unitAmount (카운트 기준)
        #    ex) 천원, 1천원, 2천원, 1,000원 등
        # -------------------------
        unit_amount = None

        # '천원' 패턴
        m = re.search(r'(\d*)\s*천원', left)
        if m:
            num = m.group(1)
            if num == "" or num is None:
                unit_amount = 1000
            else:
                try:
                    unit_amount = int(num) * 1000
                except:
                    unit_amount = 1000

        # 일반 금액 패턴: 1,000원 / 2000원
        if unit_amount is None:
            m = re.search(r'(\d[\d,]*)\s*원', left)
            if m:
                try:
                    unit_amount = int(m.group(1).replace(",", ""))
                except:
                    unit_amount = None

        if unit_amount is None:
            return None

        # -------------------------
        # 3) perUnitValue (혜택 금액)
        #    ex) 100원, 150P
        # -------------------------
        m = re.search(r'(\d[\d,]*)\s*(원|P)', right)
        if not m:
            return None

        val = int(m.group(1).replace(",", ""))
        unit = m.group(2)

        # perUnitValue는 숫자만
        per_unit_value = val

        # -------------------------
        # 4) maxDiscountAmount (옵션)
        #    ex) 최대 300원, 최대300P, (최대 600원)
        # -------------------------
        m = re.search(r'최대\s*(\d[\d,]*)\s*(원|P)', s)
        if m:
            max_val = int(m.group(1).replace(",", ""))
            max_discount_amount = max_val
        else:
            max_discount_amount = None

        return {
            "unitAmount": str(unit_amount),
            "perUnitValue": str(per_unit_value),
            "maxDiscountAmount": str(max_discount_amount) if max_discount_amount else None,
        }


    def _parse_max_usage_from_usagelimit(self, text: Optional[str]) -> Optional[int]:
        """
        'VIP콕 내 제휴사 통합 월 1회, 연 12회 가능' 같은 문장에서
        '월 N회' 부분만 뽑아서 정수로 반환. 없으면 None.
        """
        if not text:
            return None

        import re

        m = re.search(r"월\s*(\d+)\s*회?", str(text))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None

        return None

    def _apply_item_overrides(
        self,
        source: str,
        rec: Dict[str, Any],
        item: Dict[str, Any],
    ) -> None:
        """
        LLM이 애매하게 뽑은 필드를, 크롤러가 넘긴 구조화 정보로 덮어씌우는 후처리.
        KT/SKT/LGU+는 이제 규칙 기반으로 처리하므로 여기에서는 신경 안 씀.
        """

        # KT / SKT / LGU+ 는 structured path에서 처리하므로 여기서는 패스
        if source in {"kt", "skt", "lguplus"}:
            return

        # ✅ LPOINT 전용 override
        if source == "lpoint":
            # 1) status → channelLimit
            status = (item.get("status") or "").strip()
            if status:
                ch = self._extract_channel_limit_from_status(status)
                if ch:
                    rec["channelLimit"] = ch

            # 2) benefitTitle 에 %가 있으면 → discountType/discountAmount 보정
            benefit_title = (item.get("benefitTitle") or "").strip()
            if benefit_title and "%" in benefit_title:
                dt, da = self._parse_discount_from_text(benefit_title)

                if dt == "PERCENT":
                    # LLM이 discountAmount를 못 채웠거나, 엉뚱하게 채운 경우 덮어쓰기
                    if (
                        rec.get("discountAmount") in (None, 0, 0.0)
                        or rec.get("discountType") != "PERCENT"
                    ):
                        rec["discountType"] = dt
                        rec["discountAmount"] = da

            return
        
        if source == "cjone":
            # 1) discountName에 %가 있으면 우선적으로 사용
            name = (rec.get("discountName") or "").strip()
            text_for_percent = name

            # 그래도 없다면 qualification에서도 한 번 더 시도
            if "%" not in text_for_percent:
                qual = (rec.get("qualification") or "").strip()
                if "%" in qual:
                    text_for_percent = qual

            if "%" in text_for_percent:
                dt, da = self._parse_discount_from_text(text_for_percent)
                if dt == "PERCENT":
                    # LLM이 0으로 두었거나 타입을 AMOUNT로 둔 경우 덮어쓰기
                    if (
                        rec.get("discountAmount") in (None, 0, 0.0)
                        or rec.get("discountType") != "PERCENT"
                    ):
                        rec["discountType"] = dt
                        rec["discountAmount"] = da

            return

        return


    def _fill_defaults(self, rec: Dict[str, Any]) -> None:
        """
        LLM 이 비워놨을 수 있는 필드들에 대해 최소한의 기본값을 채운다.
        (DB NOT NULL + CHECK 제약을 만족하도록 방어적으로 처리)
        """
        # discountType 정규화
        dt_raw = rec.get("discountType")
        dt = (dt_raw or "").strip().upper() if isinstance(dt_raw, str) else ""
        if dt not in {"PERCENT", "AMOUNT", "PER_UNIT"}:
            dt = "AMOUNT"
        rec["discountType"] = dt

        # discountAmount
        if rec.get("discountAmount") is None:
            rec["discountAmount"] = 0.0

        rec.setdefault("maxAmount", None)
        rec.setdefault("maxUsageCnt", None)
        rec.setdefault("requiredLevel", None)
        rec.setdefault("validFrom", None)
        rec.setdefault("validTo", None)
        rec.setdefault("dowMask", None)
        rec.setdefault("timeFrom", None)
        rec.setdefault("timeTo", None)
        rec.setdefault("channelLimit", None)
        rec.setdefault("qualification", None)
        rec.setdefault("applicationMenu", None)
        rec.setdefault("isDiscount", True)

        if rec["discountType"] == "PER_UNIT":
            rec.setdefault("unitRule", None)
        else:
            rec.pop("unitRule", None)

        merchant = rec.get("merchant") or {}
        rec.setdefault("merchant", merchant)
