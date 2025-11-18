"""
사용자 앱에서 전달된 쿼리와 MCP 서버(위치/할인/추천/리뷰) 결과를 기반으로
LLM이 참고할 수 있는 컨텍스트를 생성하는 RAG 파이프라인.

1) RecommendationServer 이후 생성된 결과를 세션 단위 in-memory vector store에 저장
2) 사용자 질문과의 유사도를 계산해 Top-K 후보를 선택
3) LLM이 그대로 사용할 수 있는 컨텍스트 / 백업 응답을 생성

실제 배포 시에는 VectorDBManager 부분만 chromadb/FAISS 등으로 교체하면 된다.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _to_lower(text: Optional[str]) -> str:
    return text.lower() if isinstance(text, str) else ""


@dataclass
class Document:
    """벡터 인덱스에 저장되는 단일 문서"""

    id: str
    text: str
    metadata: Dict[str, Any]
    tokens: Counter


class VectorDBManager:
    """
    간단한 in-memory vector store.
    실제 모델 적용 시 해당 클래스를 교체하면 나머지 파이프라인은 그대로 재사용 가능하다.
    """

    def __init__(self, use_openai_embeddings: bool = False):
        self.use_openai = use_openai_embeddings
        self.collections: Dict[str, List[Document]] = {}

    # ------------------------------------------------------------------ #
    # 데이터 적재
    # ------------------------------------------------------------------ #
    def create_from_mcp_results(
        self,
        mcp_results: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RecommendationServer까지의 결과를 세션 단위로 저장.
        """
        sid = session_id or "default"
        documents = self._build_documents(mcp_results, sid)
        self.collections[sid] = documents

        breakdown = Counter(doc.metadata.get("source_type", "unknown") for doc in documents)
        return {
            "message": "✅ RAG 문서 생성 완료",
            "session_id": sid,
            "total_documents": len(documents),
            "source_breakdown": dict(breakdown),
        }

    def _build_documents(self, mcp_results: Dict[str, Any], session_id: str) -> List[Document]:
        location_payload = mcp_results.get("location_server", {}) or {}
        stores = location_payload.get("stores", []) or []
        reviews_map = self._normalize_reviews(location_payload.get("reviews"))

        recommendation_payload = (
            (mcp_results.get("recommendation_server") or {}).get("recommendations") or {}
        )
        recommendation_map = self._build_recommendation_lookup(recommendation_payload)

        documents: List[Document] = []

        for idx, store in enumerate(stores):
            store_id = (
                store.get("id")
                or store.get("store_id")
                or store.get("place_id")
                or f"store-{idx}"
            )
            doc_id = f"{session_id}_{store_id}_{idx}"

            review_text = self._review_snippet(store, reviews_map.get(store_id))
            rank_info = recommendation_map.get(store_id, {})

            document_text = self._compose_store_document(store, review_text, rank_info)
            metadata = {
                "source_type": "store",
                "store_id": store_id,
                "store_name": store.get("name") or store.get("place_name"),
                "category": store.get("category") or store.get("category_name"),
                "distance": store.get("distance"),
                "best_discount": rank_info.get("representative_benefit"),
                "discount_rank": rank_info.get("discount_rank"),
                "distance_rank": rank_info.get("distance_rank"),
                "rank_reason": rank_info.get("reason"),
                "review_highlight": review_text,
            }

            documents.append(
                Document(
                    id=doc_id,
                    text=document_text,
                    metadata=metadata,
                    tokens=Counter(self._tokenize(document_text)),
                )
            )

        return documents

    def _compose_store_document(
        self,
        store: Dict[str, Any],
        review_text: str,
        rank_info: Dict[str, Any],
    ) -> str:
        name = store.get("name") or store.get("place_name") or "이름 미상"
        category = store.get("category") or store.get("category_name") or ""
        distance = store.get("distance")
        address = store.get("address") or store.get("road_address_name") or store.get("address_name")
        chunks = [f"{name} ({category})"]

        if address:
            chunks.append(f"주소: {address}")
        if distance is not None:
            chunks.append(f"현재 위치에서 {distance}m 거리")
        if rank_info.get("discount_rank"):
            chunks.append(f"할인 우선순위 {rank_info['discount_rank']}위")
        if rank_info.get("distance_rank"):
            chunks.append(f"거리 우선순위 {rank_info['distance_rank']}위")
        benefit = rank_info.get("representative_benefit")
        if benefit and benefit.get("name"):
            rate_text = f"{benefit.get('rate')}%" if benefit.get("rate") else ""
            chunks.append(f"{benefit['name']} 혜택 {rate_text} 대상")
        if rank_info.get("reason"):
            chunks.append(rank_info["reason"])
        if review_text:
            chunks.append(review_text)

        return ". ".join(chunks)

    def _review_snippet(
        self,
        store_payload: Dict[str, Any],
        extra_reviews: Optional[Dict[str, Any]],
    ) -> str:
        reviews = []

        if isinstance(store_payload.get("reviews"), list):
            reviews.extend(store_payload["reviews"])

        if isinstance(extra_reviews, dict):
            highlight = extra_reviews.get("highlight") or extra_reviews.get("summary")
            if highlight:
                return f"리뷰 요약: {highlight}"
            reviews.extend(extra_reviews.get("reviews") or [])
        elif isinstance(extra_reviews, list):
            reviews.extend(extra_reviews)

        if not reviews:
            return ""

        sample = reviews[0]
        author = sample.get("author") or "익명"
        content = sample.get("content") or sample.get("text") or ""
        rating = sample.get("rating")
        prefix = f"{author} ({rating}★)" if rating else author
        return f"{prefix} 후기: {content[:150]}{'...' if len(content) > 150 else ''}"

    def _normalize_reviews(self, reviews_payload: Any) -> Dict[str, Any]:
        if isinstance(reviews_payload, dict):
            return reviews_payload
        return {}

    def _build_recommendation_lookup(self, payload: Any) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = defaultdict(dict)
        if not isinstance(payload, dict):
            return lookup

        for key, records in payload.items():
            if not isinstance(records, list):
                continue
            key_lower = key.lower()
            if "discount" in key_lower:
                rank_field = "discount_rank"
            elif "distance" in key_lower:
                rank_field = "distance_rank"
            else:
                rank_field = f"{key}_rank"

            for rank, record in enumerate(records, start=1):
                store_id = self._extract_store_id(record)
                if not store_id:
                    continue
                entry = lookup[store_id]
                entry[rank_field] = rank

                benefit = record.get("representative_benefit") or record.get("benefit")
                if benefit:
                    entry.setdefault("representative_benefit", benefit)

                reason = record.get("reason")
                if reason:
                    entry.setdefault("reason", reason)

        return lookup

    def _extract_store_id(self, record: Dict[str, Any]) -> Optional[str]:
        if isinstance(record.get("store"), dict):
            store = record["store"]
        else:
            store = record

        for key in ("store_id", "id", "place_id"):
            if store.get(key):
                return str(store[key])
        return None

    # ------------------------------------------------------------------ #
    # 검색
    # ------------------------------------------------------------------ #
    def search(
        self,
        user_query: str,
        top_k: int = 3,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        sid = session_id or "default"
        documents = self.collections.get(sid, [])
        if not documents:
            return {"message": "⚠️ 세션 문서를 찾을 수 없습니다.", "results": []}

        query_tokens = Counter(self._tokenize(user_query))
        q_norm = self._norm(query_tokens)

        scored: List[Dict[str, Any]] = []
        for doc in documents:
            similarity = self._cosine_similarity(query_tokens, q_norm, doc.tokens)
            similarity += self._rank_bonus(doc.metadata)
            scored.append(
                {
                    "doc_id": doc.id,
                    "document": doc.text,
                    "similarity": round(similarity, 4),
                    "metadata": doc.metadata,
                }
            )

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        return {
            "message": "✅ 벡터 검색 완료",
            "total_documents": len(documents),
            "query": user_query,
            "results": scored[:top_k],
        }

    def _cosine_similarity(self, query_tokens: Counter, q_norm: float, doc_tokens: Counter) -> float:
        if q_norm == 0:
            return 0.0
        dot = sum(query_tokens[token] * doc_tokens.get(token, 0) for token in query_tokens)
        doc_norm = self._norm(doc_tokens)
        if doc_norm == 0:
            return 0.0
        return dot / (q_norm * doc_norm)

    def _norm(self, tokens: Counter) -> float:
        return math.sqrt(sum(value * value for value in tokens.values()))

    def _rank_bonus(self, metadata: Dict[str, Any]) -> float:
        bonus = 0.0
        if metadata.get("discount_rank"):
            bonus += max(0.0, 0.15 / metadata["discount_rank"])
        if metadata.get("distance_rank"):
            bonus += max(0.0, 0.1 / metadata["distance_rank"])
        return bonus

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[0-9A-Za-z가-힣]+", _to_lower(text))

    # ------------------------------------------------------------------ #
    # 세션 정리
    # ------------------------------------------------------------------ #
    def clear_session(self, session_id: str):
        self.collections.pop(session_id, None)


class RAGPipeline:
    """
    VectorDBManager를 사용해 LLM 컨텍스트 및 백업 응답을 만들어내는 파이프라인.
    """

    def __init__(self, use_openai_embeddings: bool = False):
        self.vector_db = VectorDBManager(use_openai_embeddings)

    def process(
        self,
        user_query: str,
        mcp_results: Dict[str, Any],
        top_k: int = 3,
        session_id: Optional[str] = None,
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session_id = session_id or "default"
        create_result = self.vector_db.create_from_mcp_results(mcp_results, session_id)
        search_result = self.vector_db.search(user_query, top_k, session_id)
        llm_context = self._build_llm_context(user_query, search_result, user_profile)
        fallback_answer = self._build_fallback_answer(user_query, search_result, user_profile)

        return {
            "create_result": create_result,
            "search_result": search_result,
            "llm_context": llm_context,
            "fallback_answer": fallback_answer,
        }

    def _build_llm_context(
        self,
        user_query: str,
        search_result: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]],
    ) -> str:
        results = search_result.get("results") or []
        if not results:
            return f"사용자 요청: {user_query}\n검색된 매장이 없습니다."

        profile_lines: List[str] = []
        if user_profile:
            telco = user_profile.get("telco") or user_profile.get("telecom")
            cards = ", ".join(user_profile.get("cards", []))
            memberships = ", ".join(user_profile.get("memberships", []))
            if telco:
                profile_lines.append(f"- 통신사: {telco}")
            if cards:
                profile_lines.append(f"- 카드: {cards}")
            if memberships:
                profile_lines.append(f"- 멤버십: {memberships}")

        lines = [
            "당신은 위치 기반 맛집/카페 추천 비서입니다.",
            f"사용자 요청: {user_query}",
        ]
        if profile_lines:
            lines.append("사용자 프로필:")
            lines.extend(profile_lines)

        lines.append("\n검색된 후보:")
        for idx, result in enumerate(results, start=1):
            meta = result["metadata"]
            discount = meta.get("best_discount")
            discount_text = (
                f"{discount.get('name')} {discount.get('rate')}% 혜택 가능"
                if isinstance(discount, dict) and discount.get("name")
                else "적용 가능한 할인 없음"
            )
            review_highlight = meta.get("review_highlight") or ""
            lines.append(
                f"{idx}. {meta.get('store_name')} – {discount_text}, 거리 {meta.get('distance', 'N/A')}m. {review_highlight}"
            )

        lines.append(
            "\n지침: 위 후보만을 근거로, 사용자가 실제로 받을 수 있는 할인과 분위기를 강조하여 답변하세요. "
            "추가 정보가 없으면 '정보가 없습니다'라고 답하세요."
        )

        return "\n".join(lines)

    def _build_fallback_answer(
        self,
        user_query: str,
        search_result: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]],
    ) -> str:
        results = search_result.get("results") or []
        if not results:
            return f"'{user_query}'에 대한 추천 정보를 찾지 못했습니다. 다른 위치나 조건으로 다시 요청해 주세요."

        lines = [f"{user_query}에 대한 추천 결과입니다:"]
        for idx, result in enumerate(results, start=1):
            meta = result["metadata"]
            discount = meta.get("best_discount")
            discount_text = (
                f"{discount['name']} {discount.get('rate', '')}% 혜택"
                if isinstance(discount, dict) and discount.get("name")
                else "할인 정보 없음"
            )
            review_highlight = meta.get("review_highlight") or "분위기가 양호한 것으로 확인되었습니다."
            distance = meta.get("distance")
            lines.append(
                f"{idx}. {meta.get('store_name')} (약 {distance or 'N/A'}m) – {discount_text}. {review_highlight}"
            )

        if user_profile:
            lines.append("사용자 프로필에 맞는 혜택 순으로 정렬했습니다.")

        return "\n".join(lines)


# ==================== 사용 예시 ====================
if __name__ == "__main__":
    rag = RAGPipeline()
    mock_results = {
        "location": {
            "stores": [
                {"id": "store-1", "name": "A카페", "category": "카페", "address": "충무로 1길", "distance": 120},
                {"id": "store-2", "name": "B카페", "category": "카페", "address": "충무로 2길", "distance": 260},
            ]
        },
        "reviews": {
            "store-1": {
                "store_name": "A카페",
                "highlight": "조용한 좌석과 로스팅 향으로 유명",
                "reviews": [{"author": "민준", "content": "조용해서 작업하기 좋아요", "rating": 4.8}],
            }
        },
        "discount": {
            "discounts_by_store": {
                "store-1": {
                    "discounts": [
                        {"name": "신한카드", "rate": 20},
                        {"name": "SKT", "rate": 10},
                    ]
                }
            }
        },
        "recommendation": {
            "by_discount": [
                {"store": {"store_id": "store-1"}, "representative_benefit": {"name": "신한카드", "rate": 20}}
            ],
            "by_distance": [
                {"store": {"store_id": "store-1"}},
                {"store": {"store_id": "store-2"}},
            ],
        },
    }
    profile = {"userId": "user123", "telco": "SKT", "cards": ["신한카드"]}
    output = rag.process("충무로역에서 분위기 좋은 카페 추천해줘", mock_results, session_id="demo", user_profile=profile)
    print(json.dumps(output["search_result"], ensure_ascii=False, indent=2))
    print("\n--- Context ---\n", output["llm_context"])
