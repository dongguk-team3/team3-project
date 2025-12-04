"""
RAG Ablation Runner

- baseline: 현재 rag_module 구현 그대로
- no_rerank: _compute_score를 raw similarity 그대로 사용 (재랭킹 없음)
- no_context: LLM 컨텍스트 조립 생략
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from RAG.rag_module_ablation import create_ablation_pipeline


# 샘플 데이터 (store_id 없이 이름 기반)
sample_recommendations = {
    "by_discount": {
        "store_list": [
            {
                "name": "맘스터치",
                "distance_meters": 200,
                "all_benefits": [
                    {
                        "discountName": "신메뉴 출시 20% 할인",
                        "providerType": "STORE",
                        "providerName": "맘스터치",
                        "shape": {"kind": "PERCENT", "amount": 20.0, "maxAmount": None},
                    },
                    {
                        "discountName": "멤버십 적립 5000원",
                        "providerType": "MEMBERSHIP",
                        "providerName": "MPOINT",
                        "shape": {"kind": "AMOUNT", "amount": 5000.0, "maxAmount": None},
                    },
                ],
                "rank": 1,
            },
            {
                "name": "은화수식당",
                "distance_meters": 350,
                "all_benefits": [
                    {
                        "discountName": "CJ ONE 10% 할인",
                        "providerType": "MEMBERSHIP",
                        "providerName": "CJ ONE",
                        "shape": {"kind": "PERCENT", "amount": 10.0, "maxAmount": None},
                    },
                    {
                        "discountName": "리뷰작성시 음료증정",
                        "providerType": "STORE",
                        "providerName": "은화수식당",
                        "shape": {"kind": "AMOUNT", "amount": 0.0, "maxAmount": None},
                    },
                ],
                "rank": 2,
            },
            {
                "name": "중국성",
                "distance_meters": 180,
                "all_benefits": [
                    {
                        "discountName": "T멤버십 1000원당 150원 할인",
                        "providerType": "TELCO",
                        "providerName": "SKT",
                        "shape": {
                            "kind": "PER_UNIT",
                            "amount": 0.0,
                            "maxAmount": 3000.0,
                            "unitRule": {"unitAmount": 1000.0, "perUnitValue": 150.0, "maxDiscountAmount": 3000.0},
                        },
                    }
                ],
                "rank": 3,
            },
        ]
    },
    "by_distance": {
        "store_list": [
            {"name": "중국성", "distance_meters": 180, "rank": 1},
            {"name": "맘스터치", "distance_meters": 200, "rank": 2},
            {"name": "은화수식당", "distance_meters": 350, "rank": 3},
        ]
    },
}

sample_reviews = {
    "reviews": {
        "섬광": [
            "인스타 맛집이에요 그냥",
            "과일 프렌치토스트 촉촉하니 맛있었어요. 빵 사이에 크림치즈가 있어서 더 맛났습니다.",
        ],
        "온더플랜커피랩": [
            "커피맛잇구 분위기 좋아용 ㅎㅎ 빵도 종류 많네여",
            "노트북, 카공 테이블이 일반석과 구분되어 있어 편하게 작업하기 좋은 공간",
        ],
        "설빙 충무로점": [
            "초코브라우니 설빙 달달하이 입에 촥촥 감기네요",
        ],
        "올데이크레페 동국대점": [
            "크레페 너무 맛있어요 딸기 치즈케이크 크레페 완전 추천!!!",
        ],
    }
}

profile = {"telco": "SKT", "cards": ["신한"], "memberships": ["CJ ONE"], "categories": ["가성비", "분위기"]}
user_query = "충무로역에서 분위기 좋은 맛집 추천해줘"


def run_baseline() -> Dict[str, Any]:
    rag = create_ablation_pipeline("baseline")
    return rag.process(
        user_query=user_query,
        recommendations=sample_recommendations,
        reviews=sample_reviews,
        user_profile=profile,
        top_k=3,
        session_id="demo-baseline",
    )


def run_no_rerank() -> Dict[str, Any]:
    rag = create_ablation_pipeline("no_rerank")
    return rag.process(
        user_query=user_query,
        recommendations=sample_recommendations,
        reviews=sample_reviews,
        user_profile=profile,
        top_k=3,
        session_id="demo-no-rerank",
    )


def run_no_context() -> Dict[str, Any]:
    rag = create_ablation_pipeline("no_context")
    return rag.process(
        user_query=user_query,
        recommendations=sample_recommendations,
        reviews=sample_reviews,
        user_profile=profile,
        top_k=3,
        session_id="demo-no-context",
    )


if __name__ == "__main__":
    outputs = {
        "baseline": run_baseline(),
        "no_rerank": run_no_rerank(),
        "no_context": run_no_context(),
    }
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
