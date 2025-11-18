# etl/llm_normalizer.py
"""
LLM 기반 할인 정보 정규화 모듈.

역할:
- 각 crawler가 뱉은 raw JSON(사이트별 구조 제각각)을
  discountdb에 적재하기 좋은 "공통 스키마"로 변환한다.
- OpenAI LLM(gpt-4.1-mini 등)을 이용해서 자연어 설명을 해석 → 구조화.

중요:
- 이제 canBeCombined 대신 isDiscount(boolean)를 사용한다.
  - true  = 실제 결제 금액을 깎아주는 "할인"
  - false = 포인트/마일리지 등 "적립" 위주의 혜택
"""

from typing import Any, Dict, List

import os
import json

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
        with open(key_file, "r") as f:
            key = f.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass

    raise RuntimeError("OpenAI API 키가 없습니다. OPENAI_API_KEY 환경변수 또는 OPENAI_API.txt를 설정하세요.")


class LLMNormalizer:
    """
    LLM으로 raw 할인 데이터를 정규화하는 클래스.

    사용 예:
        normalizer = LLMNormalizer()
        normalized = await normalizer.normalize_records("KT_TELCO", raw_records)
    """

    def __init__(self, model: str = "gpt-4.1-mini"):
        api_key = load_openai_api_key()
        self.client = OpenAI(api_key=api_key)
        self.model = model
    
    @staticmethod
    def _cleanup_llm_json(text: str) -> str:
        """
        LLM이 ```json ... ``` 형태나 ``` ... ``` 로 감싸서 줄 때,
        코드블록 마크다운을 제거해서 순수 JSON 문자열만 남긴다.
        """
        if text is None:
            return ""

        s = text.strip()

        # ```json ... ``` 또는 ``` ... ``` 처리
        if s.startswith("```"):
            lines = s.splitlines()

            # 첫 줄이 ``` 또는 ```json 이면 제거
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]

            # 마지막 줄에 ``` 가 있으면 제거
            while lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]

            s = "\n".join(lines).strip()

        return s

    async def normalize_records(
        self,
        source: str,
        raw_records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        여러 raw 레코드를 받아서 LLM으로 한 번에 정규화.

        - source: "KT_TELCO", "HAPPYPOINT", "LPOINT" 같이 어디서 온 데이터인지 표시
        - raw_records: crawler가 만든 dict 리스트
        """
        if not raw_records:
            return []

        prompt = self._build_prompt(source, raw_records)

        # OpenAI ChatCompletion 호출 (비동기처럼 사용하지만, 실제 SDK는 sync라서
        # async context에서는 별도 thread executor를 쓰는 게 정석이지만,
        # 여기선 간단히 sync 호출을 감싼다고 가정)
        response = await self._call_llm(prompt)
        cleaned = self._cleanup_llm_json(response)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            preview = cleaned[:200].replace("\n", " ")
            raise RuntimeError(f"LLM 응답을 JSON으로 파싱할 수 없습니다: {preview}...") from e

        # 응답은 {"normalized": [...]} 형태라고 가정
        normalized = data.get("normalized", [])
        if not isinstance(normalized, list):
            raise RuntimeError("LLM 응답의 'normalized'가 리스트가 아닙니다.")
        return normalized

    async def normalize(self, source: str, raw: Any) -> List[Dict[str, Any]]:
        """
        run_etl.py에서 쓰기 좋은 얇은 래퍼.

        - raw가 리스트면 그대로 normalize_records에 넘기고,
        - raw가 dict면, 안에서 적당히 리스트를 뽑아서 넘긴다.
          (예: {"brands": [...]} → brands 리스트)
        """

        # 1) source별로 raw → records(list[dict])로 풀어주기
        if source == "happypoint":
            # {"source": ..., "count": n, "brands": [...]}
            records = (raw or {}).get("brands", [])
        elif source == "kt":
            # 이미 list[dict]
            records = raw or []
        elif source == "skt":
            records = raw or []
        elif source == "lguplus":
            # {"vipSummary": {...}, "brands": {"스타벅스": {...}, ...}}
            brands = (raw or {}).get("brands", {}) or {}
            # 브랜드별 dict만 뽑아서 리스트로
            records = list(brands.values())
        elif source == "lpoint":
            # {"category": ..., "totalCount": n, "affiliates": [...]}
            records = (raw or {}).get("affiliates", [])
        elif source == "cjone":
            # 이미 list[dict]
            records = raw or []
        elif source == "bccard":
            # 이미 list[dict]
            records = raw or []
        elif source == "hyundaicard":
            # {"coffee_bakery": [...], "dining": [...]}
            rb = raw or {}
            records = (rb.get("coffee_bakery") or []) + (rb.get("dining") or [])
        else:
            raise ValueError(f"지원하지 않는 source: {source}")

        if not records:
            # 정규화할 게 없으면 빈 리스트
            return []

        # 2) 공통 로직으로 넘기기
        try:
            return await self.normalize_records(source, records)
            
        except Exception as e:
            
            # 여기서 반드시 as e 로 받아야 함
            raise RuntimeError(f"{source} 정규화 중 오류: {e}") from e


    def _build_prompt(self, source: str, raw_records: List[Dict[str, Any]]) -> str:
        """
        LLM에게 줄 system+user용 프롬프트를 하나의 문자열로 생성.
        JSON 모드가 아니라 text+JSON 혼합이라고 가정.
        """

        example_schema = {
            "providerType": "TELCO | PAYMENT | MEMBERSHIP | AFFILIATION | BRAND",
            "providerName": "예: 'KT 멤버십', '신한카드', 'CJ ONE'",
            "discountName": "사람이 이해하기 쉬운 짧은 이름 (예: 'KT 파리바게뜨 상시 할인')",
            "discountType": "PERCENT | AMOUNT | PER_UNIT",
            "discountAmount": "숫자. PERCENT면 %값(10은 10%), AMOUNT/ PER_UNIT이면 원 단위 금액.",
            "maxAmount": "숫자 또는 null. 1회 최대 할인 가능 금액(원). 없으면 null.",
            "isDiscount": "boolean. true=결제 금액이 실제로 줄어드는 할인, false=포인트나 적립 위주 혜택",
            "requiredLevel": "등급 정보 문자열 또는 null. 예: 'VVIP/VIP/GOLD/일반'",
            "validFrom": "YYYY-MM-DD 문자열 또는 null",
            "validTo": "YYYY-MM-DD 문자열 또는 null",
            "dowMask": "0~127 사이 정수 또는 null. 월=0, 화=1, ..., 일=6 비트마스크.",
            "timeFrom": "HH:MM:SS 또는 null",
            "timeTo": "HH:MM:SS 또는 null",
            "channelLimit": "예: 'OFFLINE', 'APP', 'DELIVERY' 등 또는 null",
            "qualification": "문장 형태의 이용 조건 설명 또는 null",
            "applicationMenu": "적용 메뉴 설명 문자열 또는 null",
            "unitRule": {
                "unitAmount": "PER_UNIT일 때만. 예: 1000 (1000원당)",
                "perUnitValue": "PER_UNIT일 때만. 예: 100 (100원 할인)",
                "maxDiscountAmount": "PER_UNIT일 때 전체 한도. 없으면 null"
            },
            "requiredConditions": {
                "payments": [
                    {"paymentName": "카드나 결제수단 이름"}
                ],
                "telcos": [
                    {"telcoName": "SKT | KT | LG U+", "telcoAppName": "앱 이름 또는 null"}
                ],
                "memberships": [
                    {"membershipName": "CJ ONE, L.POINT, 해피포인트 등"}
                ],
                "affiliations": [
                    {"organizationName": "회사/학교 이름"}
                ]
            }
        }

        return f"""
너는 한국어 할인/적립 혜택 설명을 구조화된 JSON으로 정리하는 어시스턴트다.

[중요한 규칙]

1. 아래 "타겟 스키마"에 맞춰서만 JSON을 생성해라.
2. 각 입력 레코드마다 하나의 정규화된 객체를 만들어서
   최종적으로는 다음 형식의 JSON 문자열만 출력해라:

{{
  "normalized": [
    {{ ... }},
    {{ ... }}
  ]
}}

3. 특히 다음 필드는 정확히 채워야 한다:
   - providerType: "TELCO", "PAYMENT", "MEMBERSHIP", "AFFILIATION", "BRAND" 중 하나
   - providerName: 입력에 나오는 통신사/카드사/멤버십 이름
   - discountName: 사람이 이해하기 쉬운 짧은 혜택 이름
   - discountType:
       * 퍼센트 할인 위주면 "PERCENT"
       * 정액(예: 2,000원 할인) 위주면 "AMOUNT"
       * "1,000원당 150원 할인"처럼 단위당 혜택이면 "PER_UNIT"
   - discountAmount:
       * PERCENT: % 숫자 (예: 30% → 30.0)
       * AMOUNT: 원 단위 금액 (예: 2,000원 → 2000.0)
       * PER_UNIT: 보통 perUnitValue와 동일한 값을 넣어라 (예: 1,000원당 150원 → 150.0)
   - isDiscount (중요):
       * 실제 결제 금액이 줄어드는 혜택이면 true
         (예: 30% 할인, 2,000원 할인, 1,000원당 150원 할인)
       * 포인트 적립, 마일리지 적립이 중심이면 false
         (예: 2,000P 적립, 해피포인트 0.1% 적립)
       * 할인과 적립이 동시에 설명되어 있으면, "실제 결제 금액을 줄이는 혜택이 있는지"를 기준으로 판단해라.
   - maxAmount: 1회 최대 할인 가능 금액. 텍스트에 "최대 20,000원 할인" 등 있으면 해당 숫자.
   - unitRule: discountType이 "PER_UNIT"일 때만 채워라.
       * unitAmount: 기준 금액 (예: 1,000원당 → 1000.0)
       * perUnitValue: 단위당 혜택 금액 (예: 150원 할인 → 150.0)
       * maxDiscountAmount: 전체 최대 할인 한도. 없으면 null.

4. 텍스트에 명확히 안 나오는 정보는 추측하지 마라.
   - 없으면 null 또는 빈 배열([])로 두어라.

5. requiredConditions:
   - 이 혜택을 받기 위해 특정 카드/통신사/멤버십/소속이 필요하면 그 이름을 채워라.
   - 예: KT 멤버십 전등급 → telcos에 {{ "telcoName": "KT", "telcoAppName": "KT 멤버십" }}
   - 카드 이용 실적 조건은 qualification 문자열에 자연어로 정리해라.

[타겟 스키마 예시]

{json.dumps(example_schema, ensure_ascii=False, indent=2)}

[입력 메타 정보]
- source: "{source}"

[입력 raw_records]
아래는 raw_records 배열이다. 이 전체를 보고 정규화된 normalized 배열을 만들어라.

{json.dumps(raw_records, ensure_ascii=False, indent=2)}

반드시 JSON만 출력해라. 설명 문장은 쓰지 마라.
"""

    async def _call_llm(self, prompt: str) -> str:
        """
        OpenAI ChatCompletion 호출.

        지금은 간단하게 messages 하나로 보내고,
        model은 __init__에서 설정한 값 사용.
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "너는 한국어 할인/적립 혜택 정보를 구조화된 JSON으로 정리하는 어시스턴트다."
                },
                {
                    "role": "user",
                    "content": prompt
                },
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()
