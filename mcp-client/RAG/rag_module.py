"""
RAG 모듈 (전면 개편)
입력: process(user_query, recommendations, reviews, user_profile=None, top_k, session_id)
출력: 유사도 순 Top-K 스토어 + LLM 컨텍스트 문자열
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import time

from collections import Counter

# 사용 환경의 site-packages 보장
TEAM_SITE_PACKAGES = "/opt/conda/envs/team/lib/python3.11/site-packages"
if TEAM_SITE_PACKAGES not in sys.path:
    sys.path.append(TEAM_SITE_PACKAGES)

# Chroma telemetry 비활성화 (불필요한 이벤트/경고 방지)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "false")

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except Exception:
    chromadb = None
    Settings = None
    _CHROMA_AVAILABLE = False

try:
    import google.generativeai as genai
    _GEMINI_AVAILABLE = True
except Exception:
    genai = None
    _GEMINI_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass


EMBED_MODEL_NAME = "models/text-embedding-004"


def _sanitize_session_id(raw_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw_id)
    cleaned = cleaned.strip("-._") or "session_default"
    if len(cleaned) < 3:
        cleaned = f"session_{cleaned}"
    return cleaned[:63]


ALLOWED_USER_CATEGORIES = {"가성비", "혼밥", "모임", "분위기"}


def _clean_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_object_string_like(value: Any) -> Any:
    """DiscountServer의 '@{...}' 형태 문자열을 dict로 단순 파싱한다."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("@{") and text.endswith("}")):
        return value
    inner = text[2:-1].strip()
    if not inner:
        return {}
    parsed: Dict[str, Any] = {}
    for part in inner.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, raw = part.split("=", 1)
        k = k.strip()
        raw = raw.strip()
        if raw in ("", None):
            val: Any = None
        elif raw == "System.Object[]":
            val = []
        elif raw.lower() in {"true", "false"}:
            val = raw.lower() == "true"
        else:
            num = _clean_number(raw)
            val = num if num is not None else raw
        parsed[k] = val
    return parsed


def _extract_benefit_info(benefit: Dict[str, Any]) -> Dict[str, Any]:
    """shape.kind 기반으로 혜택 정보를 정규화."""
    shape_raw = benefit.get("shape") or {}
    if isinstance(shape_raw, str):
        shape_raw = _parse_object_string_like(shape_raw)
    shape = shape_raw if isinstance(shape_raw, dict) else {}
    unit_rule_raw = shape.get("unitRule") or shape.get("unit_rule") or {}
    if isinstance(unit_rule_raw, str):
        unit_rule_raw = _parse_object_string_like(unit_rule_raw)
    unit_rule = unit_rule_raw if isinstance(unit_rule_raw, dict) else {}
    kind = shape.get("kind") or benefit.get("type") or benefit.get("providerType")

    name = benefit.get("discountName") or benefit.get("benefit_id") or benefit.get("description")
    provider = benefit.get("providerName")

    rate = _clean_number(shape.get("amount")) if kind == "PERCENT" else _clean_number(benefit.get("discount_rate"))
    if rate is None and kind == "PERCENT":
        rate = _clean_number(benefit.get("discount_rate"))

    amount = None
    if kind in ("AMOUNT", None):
        amount = _clean_number(shape.get("amount"))
    if amount is None:
        amount = _clean_number(benefit.get("discount_amount"))

    per_unit = None
    unit_amount = None
    if kind == "PER_UNIT":
        per_unit = _clean_number(unit_rule.get("perUnitValue"))
        unit_amount = _clean_number(unit_rule.get("unitAmount"))

    max_amount = _clean_number(unit_rule.get("maxDiscountAmount") or shape.get("maxAmount"))

    return {
        "name": name,
        "provider": provider,
        "type": kind or benefit.get("type") or benefit.get("providerType"),
        "kind": kind,
        "rate": rate,
        "amount": amount,
        "per_unit": per_unit,
        "unit_amount": unit_amount,
        "max_amount": max_amount,
        "description": benefit.get("description") or name or "",
        "provider_type": benefit.get("providerType") or benefit.get("type"),
    }


def _score_benefit(info: Dict[str, Any]) -> float:
    rate = info.get("rate") or 0.0
    amount = info.get("amount") or 0.0
    per_unit = info.get("per_unit") or 0.0
    score = 0.0
    if rate:
        score = max(score, rate)
    if amount:
        score = max(score, amount / 1000.0)
    if per_unit:
        score = max(score, per_unit)
    return score


def _best_benefit(all_benefits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """혜택 리스트에서 가장 가치 있는 혜택 선택 (shape.kind == 할인 DB 양식 지원)."""
    best: Dict[str, Any] = {}
    best_score = -1.0

    for benefit in all_benefits or []:
        info = _extract_benefit_info(benefit)
        score = _score_benefit(info)
        if score > best_score:
            best_score = score
            best = info

    if best:
        return best
    if all_benefits:
        return _extract_benefit_info(all_benefits[0])
    return {}


def _flatten_reviews(store_key: str, reviews_payload: Dict[str, Any]) -> List[str]:
    if not isinstance(reviews_payload, dict):
        return []
    if "reviews" in reviews_payload and isinstance(reviews_payload.get("reviews"), dict):
        reviews_payload = reviews_payload.get("reviews") or {}
    raw = reviews_payload.get(store_key) or reviews_payload.get(str(store_key))
    if isinstance(raw, list):
        return [str(r) for r in raw if r is not None]
    if isinstance(raw, str):
        return [raw]
    return []


def _review_snippet(store_key: str, store_name: str, reviews_payload: Dict[str, Any]) -> str:
    reviews = _flatten_reviews(store_key, reviews_payload)
    if not reviews:
        return ""
    joined = " / ".join(reviews[:3])
    snippet = joined[:300]
    return f"리뷰: {snippet}{'...' if len(joined) > len(snippet) else ''}"


def _format_discount_text(
    kind: Optional[str],
    rate: Optional[float],
    amount: Optional[float],
    per_unit: Optional[float],
    unit_amount: Optional[float],
    max_amount: Optional[float],
    fallback: str,
) -> str:
    """할인 정보를 자연어 문자열로 변환."""
    kind_upper = kind.upper() if isinstance(kind, str) else None
    if kind_upper == "PERCENT" and rate is not None:
        return f"{int(rate)}% 혜택"
    if kind_upper == "PER_UNIT" and per_unit is not None and unit_amount is not None:
        text = f"{int(unit_amount)}원당 {int(per_unit)}원 할인"
        if max_amount is not None and max_amount > 0:
            text += f" (최대 {int(max_amount)}원)"
        return text
    if amount is not None and amount > 0:
        return f"{int(amount)}원 혜택"
    return fallback


def _derive_discount_hint(best_benefit: Dict[str, Any]) -> str:
    if not best_benefit or not best_benefit.get("name"):
        return ""
    provider = best_benefit.get("provider") or ""
    ptype = (best_benefit.get("provider_type") or best_benefit.get("kind") or best_benefit.get("type") or "").upper()
    if ptype in {"TELCO", "TELECOM"}:
        return f"{provider or '통신사'} 앱/멤버십 인증 시 적용"
    if ptype in {"CARD", "CREDIT_CARD", "PAYMENT", "BANK"}:
        return f"{provider or '카드사'} 결제 시 자동/청구 할인"
    if ptype in {"MEMBERSHIP", "POINT", "LOYALTY"}:
        return f"{provider or '멤버십'} 적립/멤버십 제시 후 적용"
    if ptype in {"STORE", "EVENT", "MERCHANT"}:
        return "매장 자체 프로모션, 직원 안내 후 적용"
    return "결제 전 혜택 조건을 매장/앱에서 확인 후 적용"


def _normalize_recommendations_for_rag(
    recommendations: Dict[str, Any],
    stores: List[Any],
    reviews: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    RecommendationServer 결과가 비어 있을 때 location 결과를 RAG 입력 형태로 보정.
    - stores: 이름 리스트 또는 매장 dict 리스트
    - reviews: {이름: [리뷰]} 형태
    반환: (recommendations 구조, 리뷰 매핑)
    """
    recos = recommendations.copy() if isinstance(recommendations, dict) else {}

    def ensure_store_list(block: Any) -> List[Dict[str, Any]]:
        if isinstance(block, dict):
            if block.get("store_list"):
                return block["store_list"]
            # 중첩된 경우 우선순위: by_distance → personalized
            for key in ("by_distance", "personalized"):
                if isinstance(block.get(key), dict) and block[key].get("store_list"):
                    return block[key]["store_list"]
        return []

    by_discount_list = ensure_store_list(recos.get("by_discount"))
    by_distance_list = ensure_store_list(recos.get("by_distance"))

    # 둘 다 비어 있으면 fallback: Location stores로 최소 구조 생성
    if not by_discount_list and not by_distance_list:
        store_list: List[Dict[str, Any]] = []
        review_map = reviews.copy() if isinstance(reviews, dict) else {}
        for idx, store in enumerate(stores or [], 1):
            if isinstance(store, dict):
                name = store.get("name") or store.get("place_name") or f"store_{idx}"
                distance = store.get("distance_meters") or store.get("distance")
            else:
                name = str(store)
                distance = None

            store_list.append(
                {
                    "name": name,
                    "distance_meters": distance,
                    "rank": idx,
                    "all_benefits": [],
                }
            )
            if name in review_map:
                review_map[name] = review_map[name]
        recos = {
            "by_discount": {"store_list": store_list},
            "by_distance": {"store_list": store_list},
        }
        return recos, review_map

    # 부분만 비어 있는 경우 채워 넣기
    if not by_discount_list and by_distance_list:
        recos["by_discount"] = {"store_list": by_distance_list}
    elif by_discount_list and not by_distance_list:
        recos["by_distance"] = {"store_list": by_discount_list}
    else:
        recos["by_discount"] = {"store_list": by_discount_list}
        recos["by_distance"] = {"store_list": by_distance_list}

    return recos, reviews or {}


@dataclass
class Document:
    id: str
    text: str
    metadata: Dict[str, Any]


class VectorDBManager:
    """Chroma + Gemini 임베딩 전용 벡터 스토어."""

    def __init__(self, model_name: str = EMBED_MODEL_NAME):
        self._chroma_client = None
        self.model_name = model_name
        self.rerank_model_name = os.getenv("GEMINI_RERANK_MODEL", "gemini-2.5-flash")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")

        if not _CHROMA_AVAILABLE or not Settings:
            raise RuntimeError("chromadb 패키지가 필요합니다. 설치 후 다시 시도하세요.")

        try:
            chroma_path = Path(__file__).resolve().parent / ".chroma_db"
            chroma_path.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        except Exception as e:
            raise RuntimeError(f"Chroma PersistentClient 초기화 실패: {e}") from e

        if not _GEMINI_AVAILABLE:
            raise RuntimeError("google-generativeai 패키지가 필요합니다. 설치 후 다시 시도하세요.")
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. .env 또는 환경변수에 추가하세요.")

        try:
            genai.configure(api_key=self.gemini_api_key)
        except Exception as e:
            raise RuntimeError(f"Gemini 구성 실패: {e}") from e

    # ----------------------- 데이터 적재 -----------------------
    def create_from_inputs(
        self,
        recommendations: Dict[str, Any],
        reviews: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        sid = _sanitize_session_id(session_id)
        documents = self._build_documents(recommendations, reviews, sid)
        if not documents:
            return {
                "message": "⚠️ RAG 문서를 생성할 데이터가 없습니다.",
                "session_id": sid,
                "total_documents": 0,
                "backend": "chroma",
                "skipped": True,
            }
        if not self._chroma_client:
            raise RuntimeError("Chroma 클라이언트를 초기화하지 못했습니다. chromadb 설치를 확인하세요.")
        self._upsert_chroma(sid, documents)

        return {
            "message": "✅ RAG 문서 생성 완료",
            "session_id": sid,
            "total_documents": len(documents),
            "backend": "chroma",
        }

    def _build_documents(
        self,
        recommendations: Dict[str, Any],
        reviews: Dict[str, Any],
        session_id: str,
    ) -> List[Document]:
        candidates, rank_map = self._collect_candidates(recommendations)
        documents: List[Document] = []

        used_ids: set[str] = set()

        for idx, store in enumerate(candidates):
            store_key = str(store.get("name") or store.get("store_id") or store.get("id") or f"store_{idx}")
            used_ids.add(store_key)

            rank_info = rank_map.get(store_key, {})
            best_benefit = _best_benefit(store.get("all_benefits") or [])
            review_text = _review_snippet(store_key, store.get("name", ""), reviews)

            doc_text = self._compose_store_text(store, rank_info, best_benefit, review_text)
            meta = self._build_metadata(store, rank_info, best_benefit, review_text)

            documents.append(
                Document(
                    id=f"{session_id}_{store_key}",
                    text=doc_text,
                    metadata=meta,
                )
            )

        review_only_stores = self._collect_review_only_stores(reviews, used_ids, limit=20)
        for store in review_only_stores:
            store_key = store["store_name"]
            review_text = _review_snippet(store_key, store.get("name", ""), reviews)
            doc_text = self._compose_store_text(store, {}, {}, review_text)
            meta = self._build_metadata(store, {}, {}, review_text)

            documents.append(
                Document(
                    id=f"{session_id}_{store_key}",
                    text=doc_text,
                    metadata=meta,
                )
            )

        return documents

    def _collect_candidates(
        self, recommendations: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        bucketed: Dict[str, List[Dict[str, Any]]] = {}
        for bucket in ["by_discount", "by_distance"]:
            payload = recommendations.get(bucket) or {}
            store_list = payload.get("store_list") or payload or []
            if isinstance(store_list, dict):
                store_list = store_list.get("store_list") or []
            store_list = self._sort_store_list(store_list if isinstance(store_list, list) else [])
            bucketed[bucket] = store_list

        rank_map = self._build_rank_map(bucketed)

        merged: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for bucket in ["by_discount", "by_distance"]:
            for store in bucketed.get(bucket, []):
                store_key = str(
                    store.get("name")
                    or store.get("store_id")
                    or store.get("id")
                    or store.get("store", {}).get("store_id")
                    or ""
                )
                if not store_key or store_key in seen_ids:
                    continue
                merged.append(store)
                seen_ids.add(store_key)
                if len(merged) >= 6:
                    break
            if len(merged) >= 6:
                break

        return merged, rank_map

    def _sort_store_list(self, stores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(stores, list):
            return []
        if stores and isinstance(stores[0], dict) and "rank" in stores[0]:
            return sorted(stores, key=lambda x: x.get("rank", 1e9))
        return list(stores)

    def _build_rank_map(self, bucketed: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        rank_map: Dict[str, Dict[str, Any]] = {}
        for bucket, records in bucketed.items():
            for idx, record in enumerate(records, start=1):
                store_key = str(
                    record.get("name")
                    or record.get("store_id")
                    or record.get("id")
                    or record.get("store", {}).get("store_id", "")
                )
                if not store_key:
                    continue
                entry = rank_map.setdefault(store_key, {})
                rank_value = record.get("rank")
                rank_to_use = rank_value if isinstance(rank_value, (int, float)) else idx
                if bucket == "by_discount":
                    entry["discount_rank"] = rank_to_use
                if bucket == "by_distance":
                    entry["distance_rank"] = rank_to_use
                if record.get("representative_benefit") and "representative_benefit" not in entry:
                    entry["representative_benefit"] = record.get("representative_benefit")
                if record.get("reason") and "reason" not in entry:
                    entry["reason"] = record.get("reason")

        return rank_map

    def _collect_review_only_stores(
        self,
        reviews: Dict[str, Any],
        used_ids: set[str],
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        if not isinstance(reviews, dict):
            return []
        if "reviews" in reviews and isinstance(reviews.get("reviews"), dict):
            reviews = reviews.get("reviews") or {}
        extras: List[Dict[str, Any]] = []
        for store_name in reviews.keys():
            name = str(store_name)
            if name in used_ids:
                continue
            extras.append({"store_name": name, "name": name, "all_benefits": [], "distance_meters": None})
            if len(extras) >= limit:
                break
        return extras

    def _compose_store_text(
        self,
        store: Dict[str, Any],
        rank_info: Dict[str, Any],
        best_benefit: Dict[str, Any],
        review_text: str,
    ) -> str:
        name = store.get("name") or "이름 미상"
        dist = store.get("distance_meters") or store.get("distance")
        parts = [f"{name}"]
        if dist is not None:
            dist_value = int(dist) if isinstance(dist, (int, float)) else dist
            parts.append(f"거리 {dist_value}m")
        if rank_info.get("discount_rank"):
            parts.append(f"할인 순위 {rank_info['discount_rank']}위")
        if rank_info.get("distance_rank"):
            parts.append(f"거리 순위 {rank_info['distance_rank']}위")
        if best_benefit:
            discount_text = _format_discount_text(
                best_benefit.get("kind") or best_benefit.get("type"),
                best_benefit.get("rate"),
                best_benefit.get("amount"),
                best_benefit.get("per_unit"),
                best_benefit.get("unit_amount"),
                best_benefit.get("max_amount"),
                best_benefit.get("description") or "혜택",
            )
            if discount_text:
                parts.append(discount_text)
        if review_text:
            parts.append(review_text)
        return ". ".join(parts)

    def _build_metadata(
        self,
        store: Dict[str, Any],
        rank_info: Dict[str, Any],
        best_benefit: Dict[str, Any],
        review_text: str,
    ) -> Dict[str, Any]:
        meta = {
            "source_type": "store",
            "store_name": store.get("name"),
            "distance": store.get("distance_meters") or store.get("distance"),
            "discount_rank": rank_info.get("discount_rank"),
            "distance_rank": rank_info.get("distance_rank"),
            "best_discount_name": best_benefit.get("name"),
            "best_discount_provider": best_benefit.get("provider"),
            "best_discount_type": best_benefit.get("kind") or best_benefit.get("type"),
            "best_discount_rate": best_benefit.get("rate"),
            "best_discount_amount": best_benefit.get("amount"),
            "best_discount_per_unit": best_benefit.get("per_unit"),
            "best_discount_unit_amount": best_benefit.get("unit_amount"),
            "best_discount_max": best_benefit.get("max_amount"),
            "discount_hint": _derive_discount_hint(best_benefit),
            "discount_raw_description": best_benefit.get("description"),
            "review_text": review_text,
        }
        # Chroma 메타데이터는 primitive만 허용
        return {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}

    # ----------------------- 검색 -----------------------
    def search(
        self,
        user_query: str,
        top_k: int,
        session_id: str,
        user_profile: Optional[Dict[str, Any]] = None,
        user_categories: Optional[List[str]] = None,
        query_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        sid = _sanitize_session_id(session_id)
        if not self._chroma_client:
            raise RuntimeError("Chroma 클라이언트를 초기화하지 못했습니다. chromadb 설치를 확인하세요.")
        return self._search_chroma(sid, user_query, top_k, user_profile, user_categories, query_text=query_text or user_query)

    # ----------------------- 내부 Chroma -----------------------
    def _upsert_chroma(self, session_id: str, documents: List[Document]):
        try:
            self._chroma_client.delete_collection(session_id)
        except Exception:
            pass

        try:
            collection = self._chroma_client.get_or_create_collection(name=session_id)
        except KeyError:
            # 손상된 메타/구성으로 인한 오류 시 리셋 후 재시도
            self._chroma_client.reset()
            collection = self._chroma_client.get_or_create_collection(name=session_id)

        embeddings = self._embed_texts([doc.text for doc in documents])
        metadatas = [doc.metadata for doc in documents]
        ids = [doc.id for doc in documents]
        documents_text = [doc.text for doc in documents]

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents_text,
            metadatas=metadatas,
        )

    def _search_chroma(
        self,
        session_id: str,
        user_query: str,
        top_k: int,
        user_profile: Optional[Dict[str, Any]] = None,
        user_categories: Optional[List[str]] = None,
        query_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            collection = self._chroma_client.get_collection(session_id)
        except Exception:
            return {"message": "⚠️ 세션 문서를 찾을 수 없습니다.", "results": []}

        query_embedding = self._embed_texts([user_query])
        results = collection.query(query_embeddings=query_embedding)

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []
        ids = results.get("ids", [[]])[0]

        packaged = []
        for i, doc_text in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            raw_similarity = 1 - distances[i] if distances and i < len(distances) else 0.0
            raw_similarity = max(raw_similarity, 0.0)
            if query_text:
                meta = dict(meta)
                meta["query_text"] = query_text
     
            score = self._compute_score(raw_similarity, meta, user_profile, user_categories)
            packaged.append(
                {
                    "doc_id": ids[i] if i < len(ids) else f"{session_id}_{i}",
                    "document": doc_text,
                    "score": round(score, 4),
                    "raw_similarity": round(raw_similarity, 4),
                    "metadata": meta,
                }
            )

        packaged.sort(key=lambda x: x["score"], reverse=True)
        packaged = self._apply_diversity_gate(packaged, top_k)
        return {
            "message": "✅ 벡터 검색 완료 (chroma)",
            "query": user_query,
            "results": packaged,
        }

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for text in texts:
            try:
                resp = genai.embed_content(model=self.model_name, content=text)
                embeddings.append(resp["embedding"])
            except Exception as e:
                raise RuntimeError(f"Gemini 임베딩 생성 실패: {e}") from e
        return embeddings

    def _review_relevance_bonus(
        self, query_text: Optional[str], review_text: Optional[str]
    ) -> Tuple[float, float]:
        """쿼리-리뷰 관련성 보너스: LLM 스코어 기반."""
        if not query_text or not review_text:
            print("쿼리 또는 리뷰 텍스트가 없습니다.\n")
            return 0.0, 0.0
        
        # llm_review_score = self._llm_similarity_score(query_text, review_text)
        # if llm_review_score >= 0.45:
        #     return 0.12, llm_review_score
        # if llm_review_score >= 0.35:
        #     return 0.08, llm_review_score
        # if llm_review_score >= 0.25:
        #     return 0.05, llm_review_score
        # if llm_review_score >= 0.15:
        #     return 0.03, llm_review_score
        # return 0.0, llm_review_score

        naive_cosine_score= self._naive_cosine_similarity_score(query_text, review_text)
        if naive_cosine_score >= 0.85:
            return 0.3, naive_cosine_score
        if naive_cosine_score >= 0.80:
            return 0.25, naive_cosine_score
        if naive_cosine_score >= 0.75:
            return 0.2, naive_cosine_score
        if naive_cosine_score >= 0.7:
            return 0.15, naive_cosine_score
        return 0.0, naive_cosine_score

    def _category_relevance_bonus(self, categories: List[str], review_text: Optional[str]) -> float:
        """카테고리-리뷰 LLM 스코어 기반 보너스."""
        if not categories or not review_text:
            return 0.0
        cat_text = ", ".join(categories)
        
        # llm_score = self._llm_similarity_score(cat_text, review_text)
        # if llm_score >= 0.6:
        #     return 0.07
        # if llm_score >= 0.5:
        #     return 0.05
        # if llm_score >= 0.4:
        #     return 0.03
        # return 0.0
    
        naive_cosine_score= self._naive_cosine_similarity_score(cat_text, review_text)
        return naive_cosine_score

    ## 해당 구현은 시간이 너무 오래걸리는 문제로 인해 폐기.
    # def _llm_similarity_score(self, query_text: str, review_text: str) -> float:
    #     """Gemini 생성 모델로 쿼리-리뷰 관련도를 0~1 점수로 요청."""
    #     if not query_text or not review_text:
    #         return 0.0
    #     try:

    #         model = genai.GenerativeModel(self.rerank_model_name or "gemini-2.5-flash")
          
    #         prompt = (
    #             "다음 사용자 요청과 리뷰가 얼마나 잘 맞는지 0~1 사이 소수로만 출력하세요.\n"
    #             "0은 전혀 무관, 1은 매우 강하게 관련. 한 줄에 숫자만 출력.\n"
    #             f"사용자 요청: {query_text}\n"
    #             f"리뷰: {review_text[:600]}"
    #         )
            
    #         resp = model.generate_content(
    #             contents=prompt,
    #             generation_config=genai.types.GenerationConfig(
    #                 temperature=0,
    #             ),
    #         )
    #         text = (resp.text or "").strip()
    #         match = re.search(r"([01](?:\.\d+)?|0?\.\d+)", text)
    #         if not match:
    #             return 0.0
    #         val = float(match.group(1))
    #         return min(max(val, 0.0), 1.0)
    #     except Exception:
    #         return 0.0

    def _naive_cosine_similarity_score(self, text_a: str, text_b: str) -> float:
        """임베딩 기반 코사인 유사도 (LLM 호출 없이 빠른 대안)."""
        if not text_a or not text_b:
            return 0.0
        try:
            vecs = self._embed_texts([text_a, text_b])
            if len(vecs) != 2:
                return 0.0
            v1, v2 = vecs
            dot = sum(a * b for a, b in zip(v1, v2))
            norm1 = sum(a * a for a in v1) ** 0.5
            norm2 = sum(b * b for b in v2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)
        except Exception:
            return 0.0

    def _compute_score(
        self,
        base_similarity: float,
        meta: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]],
        user_categories: Optional[List[str]],
    ) -> float:
        score = base_similarity  # 쿼리-전체 문서 유사도 기반 기본 점수
        discount_rank = meta.get("discount_rank")
        distance_rank = meta.get("distance_rank")
        if isinstance(discount_rank, (int, float)) and discount_rank > 0:
            score += 0.1 / discount_rank
            print(f"할인 순위 기반 보너스 추가: {0.1 / discount_rank}\n")
        if isinstance(distance_rank, (int, float)) and distance_rank > 0:
            score += 0.05 / distance_rank
            print(f"거리 순위 기반 보너스 추가: {0.05 / distance_rank}\n")

        # 할인 혜택 존재 여부 + 강도 반영
        rate = meta.get("best_discount_rate")
        amount = meta.get("best_discount_amount")
        per_unit = meta.get("best_discount_per_unit")
        unit_amt = meta.get("best_discount_unit_amount")
        if meta.get("best_discount_name"):
            score += 0.03
            print("할인 혜택 존재로 기본 보너스 0.03 추가.\n")
        if isinstance(rate, (int, float)):
            score += min(rate * 0.05, 0.15)
            print(f"할인율 기반 보너스 추가: {min(rate * 0.05, 0.15)}\n")
        elif isinstance(amount, (int, float)):
            score += min(amount / 150000, 0.15)
            print(f"할인액 기반 보너스 추가: {min(amount / 150000, 0.15)}\n")
        if isinstance(per_unit, (int, float)) and isinstance(unit_amt, (int, float)):
            score += 0.04
            print("단위 할인 기반 보너스 추가: 0.04\n")

        # 사용자 프로필과 혜택 매칭 (통신사/카드/멤버십 포함)
        if user_profile:
            tokens = []
            for key in ["telco", "telecom"]:
                val = user_profile.get(key)
                if val:
                    tokens.append(str(val).lower())
            tokens += [str(x).lower() for x in user_profile.get("cards", [])]
            tokens += [str(x).lower() for x in user_profile.get("memberships", [])]

            benefit_name = str(meta.get("best_discount_name") or "").lower()
            if benefit_name and any(tok in benefit_name for tok in tokens):
                score += 0.04
                print("사용자 프로필과 혜택 매칭으로 보너스 0.04 추가.\n")

        # 선호 카테고리와 리뷰 매칭 가중치 (임베딩 기반 보너스)
        if user_categories:
            cat_bonus = self._category_relevance_bonus(user_categories, meta.get("review_text"))
            score += cat_bonus

        # LLM 임베딩 + 생성 모델 기반 리뷰 관련성 보너스 (임계치 방식)
        review_bonus, llm_review_score = self._review_relevance_bonus(
            meta.get("query_text"), meta.get("review_text")
        )
        score += review_bonus
        meta["llm_review_score"] = llm_review_score
        
        meta["user_categories"] = user_categories or []
        return max(score, 0.0)

    def _apply_diversity_gate(self, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """상위 K에 리뷰 기반 후보가 최소 1개 포함되도록 보장."""
        if not results:
            return results
        top_slice = results[:top_k]
        # 이미 할인 없는 리뷰-only 후보가 있으면 그대로 반환
        if any(
            (r.get("metadata") or {}).get("review_text")
            and not (r.get("metadata") or {}).get("best_discount_name")
            for r in top_slice
        ):
            return results

        # 리뷰만 있고 할인 정보가 없는 후보를 찾아 올린다
        review_candidates = [
            r
            for r in results
            if (r.get("metadata") or {}).get("review_text") and not (r.get("metadata") or {}).get("best_discount_name")
        ]
        if not review_candidates:
            return results

        best_review = review_candidates[0]
        if best_review in top_slice:
            return results

        # top_k 안에 리뷰 후보를 끼워 넣은 뒤 top_k 구간은 점수로 재정렬
        remaining = [r for r in results if r is not best_review]
        promoted = remaining[: max(top_k - 1, 0)] + [best_review]
        promoted.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        tail = remaining[max(top_k - 1, 0) :]
        return promoted + tail

    # ----------------------- 정리 -----------------------
    def clear_session(self, session_id: str):
        sid = _sanitize_session_id(session_id)
        if self._chroma_client:
            try:
                self._chroma_client.delete_collection(sid)
            except Exception:
                pass


class RAGPipeline:
    """추천 결과 + 리뷰를 벡터화해 LLM 컨텍스트를 만드는 파이프라인."""

    def __init__(self):
        self.vector_db = VectorDBManager()

    def process(
        self,
        user_query: str,
        recommendations: Dict[str, Any],
        reviews: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        top_k: int = 3,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_id = session_id or "default"

        categories = (user_profile or {}).get("categories")
        filtered_categories = [c for c in (categories or []) if c in ALLOWED_USER_CATEGORIES]

        # recommendations/reviews 보정
        recommendations, reviews = _normalize_recommendations_for_rag(
            recommendations, [], reviews
        )
        
        create_result = self.vector_db.create_from_inputs(
            recommendations=recommendations,
            reviews=reviews,
            session_id=session_id,
        )

        search_result = self.vector_db.search(
            user_query,
            top_k,
            session_id,
            user_profile=user_profile,
            user_categories=filtered_categories,
            query_text=user_query,
        )

        llm_context = self._build_llm_context(
            user_query=user_query,
            search_result=search_result,
            user_categories=filtered_categories,
            top_k=top_k,
        )

        fallback_answer = self._build_fallback_answer(
            user_query=user_query,
            search_result=search_result,
        )

        discount_summary = self._build_discount_summary(search_result.get("results") or [])
        top_stores = [self._summarize_result(r) for r in (search_result.get("results") or [])]

        return {
            "create_result": create_result,
            "search_result": search_result,
            "llm_context": llm_context,
            "fallback_answer": fallback_answer,
            "discount_summary": discount_summary,
            "top_stores": top_stores[:top_k],
        }

    def mp_process(
        self,
        user_query: str,
        recommendations: Dict[str, Any],
        reviews: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        top_k: int = 3,
        session_id: Optional[str] = None,
        workers: int = 3,
    ) -> Dict[str, Any]:
        """멀티프로세싱 래퍼: 동일 작업을 다른 프로세스에서 단일 실행."""
        if not self.mp_runner:
            raise RuntimeError("mp_rag_process 모듈을 불러오지 못했습니다.")
        return self.mp_runner(
            user_query=user_query,
            recommendations=recommendations,
            reviews=reviews,
            user_profile=user_profile,
            top_k=top_k,
            session_id=session_id,
            workers=workers,
        )

    # ----------------------- 컨텍스트 -----------------------
    def _build_llm_context(
        self,
        user_query: str,
        search_result: Dict[str, Any],
        user_categories: Optional[List[str]],
        top_k: int,
    ) -> str:
        results = (search_result.get("results") or [])[:top_k]
        if not results:
            return f"사용자 요청: {user_query}\n검색된 매장이 없습니다."

        lines = ["당신은 위치 기반 맛집/카페 추천 비서입니다.", f"사용자 요청: {user_query}"]
        if user_categories:
            lines.append(f"선호 카테고리: {', '.join(user_categories)}")

        lines.append("\n검색된 후보:")
        for idx, result in enumerate(results, start=1):
            meta = result.get("metadata", {})
            discount_text = self._describe_discount(meta, default="혜택 정보 없음")
            review_text = meta.get("review_text") or ""
            distance = meta.get("distance")
            hint = meta.get("discount_hint")
            hint_text = f" 혜택 받는 방법: {hint}" if hint else ""
            llm_sim = meta.get("llm_review_score")
            raw_text = f" (리뷰-요청 관련도={llm_sim})" if llm_sim is not None else ""
            user_categories = meta.get("user_categories") or []
            if user_categories:
                raw_text += f" (사용자 선호 카테고리: {', '.join(user_categories)})"
            lines.append(
                f"{idx}. {meta.get('store_name')} – {discount_text}, 거리 {distance or 'N/A'}m{raw_text}. {review_text}{hint_text}"
            )

        lines.append(
            "\n지침: 위 후보만을 근거로, 리뷰 내용과 사용자 요청의 매칭을 최우선으로 고려하고, 그 다음으로 할인/거리 순으로 판단하세요. "
            "리뷰-요청 관련도 값이 높을수록 리뷰-사용자 요청 매칭이 잘 된 후보입니다. 정보가 없으면 '정보가 없습니다'라고 답변하세요."
            "사용자 카테고리 항목은 비어있지 않을경우 반드시 반영하세요. 카테고리에 들어올 수 있는 종류는 모임, 분위기, 가성비, 혼밥 입니다."
            "아래 예시처럼 순위제시 까지만 작성."
            "불필요한 추가 멘트 금지."
            "\n 예시1. : 사용자 쿼리: 강남역 주변 프랜차이즈 카페좀 추천해줘 대답: 강남역 근처 **프랜차이즈 카페** 중에서,"
                "사용자 카테고리에 의한 선호 항목인 **가성비 · 분위기** 기준으로 리뷰 내용과 관련도 우선 고려해 추천드립니다"

                "\n1. **던킨 원더스 강남**"
                "\n- 프랜차이즈: 맞음"
                "\n- 분위기: 매장 밝고 넓으며 항상 환한 분위기라는 리뷰"
                "\n- 가성비: 비교적 부담 없는 가격대"
                "\n- 총평: 편하게 쉬기 좋고 분위기도 무난해요. 커피보다 공간·도넛 위주 이용 시 추천."

                "\n2. **팀홀튼 강남역 대륭타워점**"
                "\n- 프랜차이즈: 맞음"
                "\n- 가성비: 스몰 커피 3,800원 등 저렴하다는 리뷰"
                "\n- 분위기: 좌석 간격 넓지만 전체적으로는 다소 시끄럽다는 의견"
                "\n- 총평: 가격 대비 무난하게 머물기 좋음. 조용한 분위기는 덜하지만 가성비 중시라면 추천."      
                "\n3. **The November 라운지 강남역(KG타워점)**"
                "\n- 프랜차이즈: 체인점"
                "\n- 분위기: 라운지형 카페로 분위기 좋다는 리뷰"
                "\n- 가성비: 일반적인 카페 가격대 (특별한 할인 정보 없음 → 정보가 없습니다)"
                "\n- 총평: 분위기 좋은 체인 카페를 원하면 적합."
                
            "\n 예시2. : 사용자 쿼리: 충무로역 주변 분위기 좋은 카페좀 추천해줘"
                "사용자 카테고리에 의한 선호 항목인 **모임 · 분위기** 기준으로 리뷰 내용과 관련도 우선 고려해 추천드립니다"

                "\n1. 카페차 충무로점"
                "\n- 리뷰에 분위기 좋다는 언급이 가장 많음"
                "\n- 매장이 넓고 쾌적하다는 평가"
                "\n- 커피·디저트 맛도 괜찮다는 후기 다수"

                "\n2. 섬광"
                "\n- 통유리 채광 + 힙한 인테리어로 분위기 좋다는 의견"
                "\n- 디저트 맛있다는 후기 많음"
                "\n- 음료 양은 다소 적다는 평가도 있음"

                "\n3. 온더플랜커피랩"
                "\n- 테이블 간격 넓고 편안한 분위기"
                "\n- 커피 맛 좋고 베이커리 종류 다양"
                "\n- 작업/대화 모두 하기 좋은 공간이라는 리뷰"
        )
        
        return "\n".join(lines)

    def _build_fallback_answer(
        self,
        user_query: str,
        search_result: Dict[str, Any],
    ) -> str:
        results = search_result.get("results") or []
        if not results:
            return f"'{user_query}'에 대한 추천 정보를 찾지 못했습니다. 다른 위치나 조건으로 다시 요청해 주세요."

        lines = [f"{user_query}에 대한 추천 결과입니다:"]
        for idx, result in enumerate(results, start=1):
            meta = result.get("metadata", {})
            discount_text = self._describe_discount(meta, default="할인 정보 없음")
            review_text = meta.get("review_text") or "리뷰 정보 없음"
            distance = meta.get("distance")
            hint = meta.get("discount_hint")
            hint_text = f" (혜택 받는 방법: {hint})" if hint else ""
            lines.append(
                f"{idx}. {meta.get('store_name')} (약 {distance or 'N/A'}m) – {discount_text}{hint_text}. {review_text}"
            )

        return "\n".join(lines)

    def _describe_discount(self, meta: Dict[str, Any], default: str = "할인 정보 없음") -> str:
        raw = meta.get("discount_raw_description")
        if raw:
            return raw
        return _format_discount_text(
            meta.get("best_discount_type"),
            meta.get("best_discount_rate"),
            meta.get("best_discount_amount"),
            meta.get("best_discount_per_unit"),
            meta.get("best_discount_unit_amount"),
            meta.get("best_discount_max"),
            meta.get("best_discount_name") or default,
        )

    def _build_discount_summary(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return ""

        lines = []
        for idx, item in enumerate(results, start=1):
            meta = item.get("metadata", {})
            name = meta.get("store_name") or "가게"
            distance = meta.get("distance")
            discount_text = self._describe_discount(meta, default="할인 정보 없음")
            dist_text = f", 거리 {distance}m" if distance is not None else ""
            lines.append(f"{idx}. {name}: {discount_text}{dist_text}")

        return "\n".join(lines)

    def _summarize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        meta = result.get("metadata", {})
        return {
            "store_name": meta.get("store_name"),
            "distance": meta.get("distance"),
            "discount_rank": meta.get("discount_rank"),
            "distance_rank": meta.get("distance_rank"),
            "discount_name": meta.get("best_discount_name"),
            "discount_rate": meta.get("best_discount_rate"),
            "discount_amount": meta.get("best_discount_amount"),
            "discount_per_unit": meta.get("best_discount_per_unit"),
            "discount_unit_amount": meta.get("best_discount_unit_amount"),
            "discount_max": meta.get("best_discount_max"),
            "review": meta.get("review_text"),
            "score": result.get("score"),
            "raw_similarity": result.get("raw_similarity"),
        }


    
# ==================== 사용 예시 ====================
if __name__ == "__main__":
    rag = RAGPipeline()

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
                "과일 프렌치토스트 촉촉하니 맛있었어요. 빵 사이에 크림치즈가 있어서 더 맛났습니다. 과일도 많구요. 추가한 바닐라 아이스크림에는 시나몬 뿌려져서 좋았어요.\n\n음료는 양이 좀 적긴 합니다. 그래도 디저트가 만족스러워서 좋았습니다.",
                "🍌 바나나 푸딩 맛잇음 \n통유리라서 채광이 좋음\n내주 인테리어 힙하다",
                "과일 파르페 맛있어용!! 요거트 아이스크림 느낌임\n가격이 사악하지만\n그리고 가게가 무슨 5층에 있는데 엘베가 없어서 좀 고생했서여 ㅠㅠ\n\n근데 엄청 느좋이여요~~ 남친이랑 오면 좋을 듯..",
                "디저트류가 너무 잘나오고 사진찍기 좋아요❤️\n와인도 맛있었는데 너무 만족스러워서 재방문했어요\n엘리베이터 없는 5층만 제외하면 완벽해요!",
            ],
            "온더플랜커피랩": [
                "커피맛잇구 분위기 좋아용 ㅎㅎ 빵도 종류 많네여",
                "노트북, 카공 테이블이 일반석과 구분되어 있어 편하게 작업하기 좋은 공간\n커피 원두 향도 좋고 베이커리도 은근히 많은 편\n(일요일 저녁에 가서 일부는 없었음)\n밤 늦게까지 영업하고 충무로역 바로 앞이라 접근성도 좋고 모임 장소로도 손색이 없을 듯",
                "커피는 정말 맛있었어요~\n\n직원분들이 넘 무뚝뚝하셔서ㅡㅡ;;\n마치 좀비 같았어요~~\n고객 서비스 부분만 살짝 개선됐음~~좋겠습니다~~^^",
                "커피맛 좋으나 소금빵은 너무 딱딱해서 ㅠ 먹기 힘들어요",
                "* 충무로역 근처 커피맛 좋은 로스팅카페 '온더플랜커피랩'\n\n반층 올라간 1층인데, 층고가 높아서 통창으로 바깥을 보는뷰가 시원하다. 공간이 넓고 자리도 많고, 커피맛도 좋은곳. 크림을 잘 밸런싱한 콥라떼가 시그니처인데 크림이 꽤 양이 많아서 아래 커피를 함께 마실려면 한잔 던지듯 쭈욱 먹어야한다 ^^",
            ],
            "설빙 충무로점": [
                "초코브라우니 설빙 달달하이 입에 촥촥 감기네요\n특히 알바생 키가 아담하고 친절해서 빙수의 풍미를 더욱 끌어올려주네요 ㅎㅎ",
                "불친절 인사및. 말한마디 안함",
                "생블루베리가 올려진 순수요거블루베리설빙. 오랜만에\n먹어도 맛있네요 :)",
                "설빙 좋아요!",
                "맛나요",
            ],
            "올데이크레페 동국대점": [
                "크레페 너무 맛있어요 딸기 치즈케이크 크레페 완전 추천!!! 하나만 먹어도 배불러용!",
                "데이트코스로 딱이에용❤",
                "처음 방문했는데 크레페가 푸짐하고 맛있어요! 늦게까지 열어서 좋네요~ 종류가 다양하고 토핑도 많아서 조합이 맛나요!",
                "크레페집 생겨서 너무 좋아요 딸바 맛있어요!!",
                "이거먹으러 1km 걸어왓어요🤍🤍\n너무 맛잇습니다아 ㅎㅎ 다들 크레퍼 먹으러 오세요!!",
            ],
        }
    }

    profile = {"telco": "SKT", "cards": ["신한"], "memberships": ["CJ ONE"], "categories": ["가성비", "분위기"]}
    start_time = time.time()
    output = rag.process(
        user_query="충무로역에서 분위기 좋은 맛집 추천해줘",
        recommendations=sample_recommendations,
        reviews=sample_reviews,
        user_profile=profile,
        top_k=3,
        session_id="demo",
    )

    print(json.dumps(output["search_result"], ensure_ascii=False, indent=2))
    print("\n--- LLM Context ---\n", output["llm_context"])
    
    # if rag.mp_runner:
    #     mp_output = rag.mp_process(
    #         user_query="충무로역에서 분위기 좋은 맛집 추천해줘",
    #         recommendations=sample_recommendations,
    #         reviews=sample_reviews,
    #         user_profile=profile,
    #         top_k=3,
    #         session_id="demo-mp",
    #     )
    #     print("\n--- MP Search Result ---\n", json.dumps(mp_output["search_result"], ensure_ascii=False, indent=2))
    end_time = time.time()
    print(f"processing time: {end_time - start_time} seconds")
