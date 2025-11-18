import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


# Gemini API 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

try:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL = genai.GenerativeModel("gemini-2.0-flash-exp")
    print("✅ Gemini API 설정 완료")
except ImportError:
    print("⚠️ google-generativeai 설치 필요: pip install google-generativeai")
    GEMINI_MODEL = None
except Exception as e:  # pragma: no cover - 초기 설정 예외 로깅
    print(f"⚠️ Gemini API 설정 오류: {e}")
    GEMINI_MODEL = None


# Prompt Injection 공격 패턴
INJECTION_PATTERNS = [
    r"이전\s*(지시|명령|프롬프트|instruction)",
    r"(무시|ignore|forget|disregard)",
    r"시스템\s*프롬프트",
    r"system\s*prompt",
    r"너는\s*(이제|지금부터)",
    r"you\s*are\s*now",
    r"역할\s*변경",
    r"pretend\s*to\s*be",
]

# 허용/차단 키워드
ALLOWED_KEYWORDS = [
    "음식점",
    "식당",
    "맛집",
    "카페",
    "할인",
    "쿠폰",
    "추천",
    "위치",
    "근처",
    "주변",
    "디저트",
    "치킨",
    "한식",
    "중식",
    "분식",
    "양식",
    "일식",
    "회",
    "초밥",
    "족발",
    "보쌈",
    "고기",
    "구이",
    "도시락",
    "죽",
    "찜",
    "탕",
    "샐러드",
    "아시안",
    "버거",
    "피자",
    "파스타",
    "술집",
    "저녁",
    "점심",
]

BLOCKED_KEYWORDS = [
    "코딩",
    "프로그래밍",
    "정치",
    "주식",
    "의료",
    "법률",
    "파이썬",
    "자바",
    "javascript",
    "투자",
    "진료",
    "변호사",
]


@dataclass
class ValidationResult:
    """검증 결과"""

    is_valid: bool
    message: str
    filtered_query: Optional[str] = None
    user_profile: Optional[Dict[str, Any]] = None


class InputValidator:
    """입력 검증 클래스 (Prompt Injection 방어)"""

    @staticmethod
    def sanitize_input(query: str) -> str:
        """입력 정규화 (특수문자 제거, 길이 제한)"""
        query = query.strip()

        if len(query) > 500:
            query = query[:500]

        return query

    @staticmethod
    def check_injection(query: str) -> bool:
        """Prompt Injection 공격 탐지"""
        query_lower = query.lower()

        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return True

        return False

    @staticmethod
    def check_keywords(query: str) -> Tuple[bool, str]:
        """키워드 기반 검증"""
        query_lower = query.lower()

        for blocked in BLOCKED_KEYWORDS:
            if blocked in query_lower:
                return False, f"'{blocked}' 관련 질문은 지원하지 않습니다. 음식점이나 카페 추천을 요청해주세요."

        if len(query) < 20:
            return True, "OK"

        has_allowed_keyword = any(keyword in query_lower for keyword in ALLOWED_KEYWORDS)
        if not has_allowed_keyword:
            return False, "음식점, 카페, 할인 관련 질문만 가능합니다. 예: '강남역 근처 맛집 추천'"

        return True, "OK"

    @staticmethod
    def validate_user_profile(user_profile: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """User Profile 검증"""
        if not user_profile:
            return True, "OK"

        required_fields = ["userId", "telco"]
        for field in required_fields:
            if field not in user_profile:
                return False, f"유저 프로필에 '{field}' 필드가 필요합니다."

        return True, "OK"

    @classmethod
    def validate(cls, query: str, user_profile: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """전체 검증 파이프라인 (query + user_profile)"""
        query = cls.sanitize_input(query)

        if not query:
            return ValidationResult(is_valid=False, message="질문을 입력해주세요.")

        if cls.check_injection(query):
            return ValidationResult(
                is_valid=False,
                message="올바르지 않은 요청입니다. 음식점이나 카페 추천을 요청해주세요.",
            )

        is_valid, message = cls.check_keywords(query)
        if not is_valid:
            return ValidationResult(is_valid=False, message=message)

        profile_valid, profile_message = cls.validate_user_profile(user_profile)
        if not profile_valid:
            return ValidationResult(is_valid=False, message=profile_message)

        return ValidationResult(
            is_valid=True,
            message="OK",
            filtered_query=query,
            user_profile=user_profile,
        )


class KeywordExtractor:
    """키워드 추출 클래스 (Gemini + 규칙 기반)"""

    def __init__(self):
        self.gemini_model = GEMINI_MODEL

    def extract(self, query: str) -> Dict[str, Any]:
        """키워드 추출 메인 함수"""
        if self.gemini_model:
            try:
                keywords = self._extract_with_gemini(query)
                if keywords.get("place_type"):
                    return keywords
            except Exception as e:  # pragma: no cover - API 실패 시 백업 사용
                print(f"⚠️ Gemini 추출 실패, 규칙 기반으로 대체: {e}")

        return self._extract_with_rules(query)

    def _extract_with_gemini(self, query: str) -> Dict[str, Any]:
        """Gemini API를 이용한 키워드 추출"""
        prompt = f"""다음 질문에서 키워드를 추출하세요:
"{query}"

응답 형식 (JSON만):
{{"attributes": ["형용사1"], "place_type": "장소", "location": "지역"}}
"""
        response = self.gemini_model.generate_content(prompt)

        json_match = re.search(r'\{[^}]*"place_type"[^}]*\}', response.text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        return {"attributes": [], "place_type": None, "location": None}

    def _extract_with_rules(self, text: str) -> Dict[str, Any]:
        """규칙 기반 키워드 추출"""
        return _extract_keywords_fallback(text)


def _extract_keywords_fallback(text: str) -> Dict[str, Any]:
    """규칙 기반 키워드 추출"""
    attribute_patterns = {
        "맛있는": [r"맛있는", r"맛집", r"잘하는"],
        "분위기좋은": [r"분위기\s*좋은", r"분위기\s*있는", r"분위기"],
        "가성비좋은": [r"가성비\s*좋은", r"저렴한", r"싼", r"가성비"],
        "조용한": [r"조용한", r"한적한"],
        "깨끗한": [r"깨끗한", r"청결한"],
        "신선한": [r"신선한", r"싱싱한"],
        "뜨끈한": [r"뜨끈한", r"따뜻한", r"뜨거운"],
        "특별한날": [r"특별한\s*날", r"기념일", r"데이트"],
        "회식": [r"회식", r"단체"],
        "1인분주문가능": [r"1인분", r"혼자", r"혼밥"],
        "포장": [r"포장", r"테이크\s*아웃"],
        "배달": [r"배달", r"주문"],
        "숨겨진": [r"숨겨진", r"소문난", r"로컬", r"개인"],
        "신규": [r"신규", r"새로\s*생긴", r"오픈", r"뉴"],
        "야식": [r"야식", r"밤에", r"저녁"],
        "다회용기": [r"다회용기", r"친환경", r"용기"],
        "괜찮은": [r"괜찮은", r"좋은"],
        "부모님": [r"부모님", r"어른", r"모시고"],
        "애견동반": [r"강아지", r"애견", r"반려견"],
        "야외": [r"야외", r"테라스", r"루프탑"],
        "반찬": [r"반찬", r"밑반찬"],
        "아침": [r"아침", r"일찍"],
    }

    place_patterns = {
        "카페/디저트": [r"카페/디저트", r"카페\s*디저트"],
        "일식/돈까스": [r"일식/돈까스", r"일식.*돈까스", r"돈까스"],
        "피자/양식": [r"피자/양식", r"피자.*양식", r"피자", r"파스타"],
        "회/초밥": [r"회/초밥", r"(?<!다)회(?!식)", r"초밥", r"스시", r"사시미", r"횟집"],
        "족발/보쌈": [r"족발/보쌈", r"족발", r"보쌈"],
        "고기/구이": [r"고기/구이", r"고기", r"구이", r"삼겹살", r"갈비", r"소고기"],
        "도시락/죽": [r"도시락/죽", r"도시락", r"죽"],
        "찜/탕": [r"찜/탕", r"찜", r"탕", r"찌개", r"국물", r"전골", r"찜닭"],
        "카페": [r"카페", r"커피\s*숍"],
        "디저트": [r"디저트", r"케이크", r"빵"],
        "치킨": [r"치킨", r"닭", r"맥주"],
        "한식": [r"한식", r"백반", r"한정식"],
        "중식": [r"중식", r"중국집", r"짜장", r"짬뽕"],
        "분식": [r"분식", r"떡볶이", r"김밥"],
        "양식": [r"양식", r"이탈리안"],
        "일식": [r"일식", r"일본", r"이자카야"],
        "샐러드": [r"샐러드", r"샌드위치"],
        "아시안": [r"아시안", r"퓨전", r"태국", r"베트남", r"쌀국수"],
        "패스트푸드": [r"버거", r"햄버거"],
        "프랜차이즈": [r"프랜차이즈", r"체인"],
        "술집": [r"술집", r"바", r"주점"],
        "맛집": [r"맛집"],
    }

    attributes = []
    for attr, patterns in attribute_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                attributes.append(attr)
                break

    place_type = None
    for place, patterns in place_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                place_type = place
                break
        if place_type:
            break

    if not place_type:
        if re.search(r"식당|음식점|레스토랑", text):
            place_type = "맛집"
        elif re.search(r"야식", text):
            place_type = "맛집"
        elif re.search(r"뭐\s*먹", text):
            place_type = "맛집"

    if re.search(r"프랜차이즈\s*말고|체인\s*말고|유명한.*말고", text):
        if "숨겨진" not in attributes:
            attributes.append("숨겨진")

    location = None
    location_patterns = [
        r"강남역?",
        r"홍대",
        r"연남동",
        r"성수동",
        r"신촌",
        r"광화문",
        r"이태원",
        r"삼성역?",
        r"여의도",
        r"압구정",
        r"청담",
        r"건대",
        r"신림",
        r"노원",
        r"강북",
        r"서울역",
        r"종로",
        r"명동",
        r"동대문",
        r"잠실",
        r"송파",
        r"영등포",
        r"구로",
        r"가산",
        r"목동",
        r"마포",
        r"강남구",
        r"서초구",
        r"송파구",
        r"강동구",
        r"성북구",
        r"종로구",
        r"중구",
        r"마포구",
        r"용산구",
        r"영등포구",
        r"관악구",
        r"동작구",
        r"수원",
        r"용인",
        r"성남",
        r"분당",
        r"판교",
        r"안양",
        r"부천",
        r"고양",
        r"일산",
        r"파주",
        r"김포",
        r"평택",
        r"화성",
        r"광명",
        r"부산",
        r"해운대",
        r"광안리",
        r"서면",
        r"남포동",
        r"대구",
        r"인천",
        r"광주",
        r"대전",
        r"울산",
        r"세종",
        r"제주도?",
        r"제주시",
        r"서귀포",
        r"이\s*근처",
        r"이\s*동네",
        r"여기",
        r"이\s*근방",
    ]

    for pattern in location_patterns:
        match = re.search(pattern, text)
        if match:
            location = match.group(0).strip()
            break

    return {
        "attributes": attributes,
        "place_type": place_type,
        "location": location,
    }


class ChatFilterPipeline:
    """
    채팅 필터 파이프라인 (prompt_filter.py 패턴)

    [1단계] Input Validation (보안)
    [2단계] Keyword Extraction (키워드 추출)
    [3단계] MCP Response Formatting (응답 포맷)
    """

    def __init__(self):
        self.validator = InputValidator()
        self.keyword_extractor = KeywordExtractor()

    def process(self, user_query: str, user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        validation_result = self.validator.validate(user_query, user_profile)

        if not validation_result.is_valid:
            return {
                "success": False,
                "message": validation_result.message,
                "error": "validation_failed",
                "keywords": None,
                "user_profile": None,
                "mcp_ready": False,
            }

        keywords = self.keyword_extractor.extract(validation_result.filtered_query)

        has_place_type = keywords.get("place_type") is not None

        return {
            "success": True,
            "message": "OK",
            "keywords": keywords,
            "user_profile": validation_result.user_profile,
            "mcp_ready": has_place_type,
        }

