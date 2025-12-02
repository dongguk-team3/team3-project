"""
LLM 응답 생성 모듈

입력: 사용자 질의, RAG 컨텍스트, 필터 결과
출력: OpenAI ChatCompletion 기반 자연어 응답 문자열

note: user_profile 정보는 컨텍스트에 포함하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


async def call_openai_llm(
    openai_client,
    user_query: str,
    llm_context: str,
    filter_result: Optional[Dict[str, Any]],
) -> str:
    """OpenAI ChatCompletion 호출

    llm_context는 rag_module에서 완성한 컨텍스트+지침 문자열을 그대로 전달한다.

    Args:
        openai_client: OpenAI 클라이언트 인스턴스
        user_query: 사용자 질문
        llm_context: RAG로 생성된 컨텍스트
        filter_result: Prompt Filter 결과

    Returns:
        모델 응답 텍스트
    """
    keywords = filter_result.get("keywords") if filter_result else None
    keyword_text = ""
    if keywords:
        place = keywords.get("place_type")
        attributes = ", ".join(keywords.get("attributes", []))
        location = keywords.get("location")
        keyword_text = f"\n키워드: 장소={place}, 속성={attributes}, 지역={location}"

    system_content = (llm_context or "").strip() + (keyword_text or "")
    if not system_content:
        system_content = "제공된 컨텍스트가 없습니다. 답변을 생성할 수 없습니다."

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_query},
    ]

    try:
        response = openai_client.chat.completions.create(
            model="gpt-5.1-chat-latest",
            messages=messages,
            # 최신 gpt-5.1 계열은 temperature 커스텀을 허용하지 않음(기본=1)
            temperature=1,
            # gpt-4.1/5.1 계열은 max_tokens 대신 max_completion_tokens를 사용
            max_completion_tokens=800,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        return response.choices[0].message.content
    except Exception as e:
        error_message = str(e)
        if "rate_limit" in error_message.lower():
            return "⚠️ 일시적으로 요청이 많아 처리할 수 없습니다. 잠시 후 다시 시도해주세요."
        if "invalid_api_key" in error_message.lower():
            return "⚠️ API 키가 유효하지 않습니다. 관리자에게 문의해주세요."
        if "insufficient_quota" in error_message.lower():
            return "⚠️ API 사용량이 초과되었습니다. 관리자에게 문의해주세요."
        return f"⚠️ 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.\n(오류: {error_message})"
