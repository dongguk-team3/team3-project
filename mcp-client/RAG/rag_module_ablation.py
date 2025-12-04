"""
RAG Ablation helper

기존 RAGPipeline을 그대로 활용하되, ablation 실험을 위해
- 재랭킹을 끈 버전(no_rerank)
- LLM 컨텍스트 조립을 생략한 버전(no_context)
을 손쉽게 생성하기 위한 유틸을 제공합니다.

본 파일은 프로덕션 로직(rag_module.py)을 건드리지 않고
별도의 ablation 파이프라인을 생성하는 데만 사용하세요.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from RAG.rag_module import RAGPipeline


def create_ablation_pipeline(variant: str = "baseline") -> RAGPipeline:
    """
    ablation variant에 맞는 RAGPipeline을 생성해 반환합니다.

    Args:
        variant: "baseline" | "no_rerank" | "no_context"
    """
    pipeline = RAGPipeline()

    if variant == "no_rerank":
        # 하이브리드 재랭킹을 끄고 벡터 유사도(raw)만 사용
        def _compute_score_no_rerank(
            self,
            base_similarity: float,
            meta: Dict[str, Any],
            user_profile: Optional[Dict[str, Any]],
            user_categories: Optional[List[str]],
        ) -> float:
            return base_similarity

        pipeline.vector_db._compute_score = _compute_score_no_rerank.__get__(
            pipeline.vector_db, pipeline.vector_db.__class__
        )

    elif variant == "no_context":
        # LLM 컨텍스트를 조립하지 않고 간단한 텍스트만 전달
        def _build_llm_context_stub(
            self,
            user_query: str,
            search_result: Dict[str, Any],
            user_categories: Optional[List[str]],
            top_k: int,
        ) -> str:
            results = search_result.get("results", [])
            return "\n".join(
                [
                    f"사용자 요청: {user_query}",
                    f"컨텍스트 생략 (ablation; 후보 {len(results)}개)",
                ]
            )

        pipeline._build_llm_context = _build_llm_context_stub.__get__(
            pipeline, pipeline.__class__
        )

    elif variant == "baseline":
        # 아무 패치 없이 그대로 사용
        pass
    else:
        raise ValueError(f"Unknown ablation variant: {variant}")

    return pipeline


__all__ = ["create_ablation_pipeline"]
