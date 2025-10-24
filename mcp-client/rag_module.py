"""
RAG (Retrieval-Augmented Generation) 모듈
MCP Server 결과를 벡터 DB에 저장하고 유사도 검색을 수행합니다.
"""

import json
from typing import List, Dict, Any, Optional


class VectorDBManager:
    """
    벡터 DB 관리 클래스 (추후 구현 예정)
    
    TODO: 실제 구현 시 chromadb 또는 FAISS 사용
    - pip install chromadb
    - pip install sentence-transformers
    """
    
    def __init__(self, use_openai_embeddings: bool = False):
        """
        초기화
        
        Args:
            use_openai_embeddings: OpenAI Embeddings 사용 여부
                - True: OpenAI API (유료, 고품질)
                - False: sentence-transformers (무료, 로컬)
        """
        self.use_openai = use_openai_embeddings
        self.is_implemented = False
        
        # TODO: 실제 벡터 DB 초기화
        # if use_openai_embeddings:
        #     import openai
        #     self.embedder = openai.Embedding
        # else:
        #     from sentence_transformers import SentenceTransformer
        #     self.embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        # 
        # import chromadb
        # self.db = chromadb.Client()
        # self.collection = self.db.create_collection("mcp_results")
        
        print("⚠️  벡터 DB는 아직 구현되지 않았습니다 (스텁 모드)")
    
    def create_from_mcp_results(
        self, 
        mcp_results: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        MCP Server 결과를 벡터 DB에 저장
        
        Args:
            mcp_results: MCP Server 호출 결과
            session_id: 세션 ID (임시 DB용)
        
        Returns:
            저장 결과
        """
        if not self.is_implemented:
            # TODO: 실제 구현 제거
            return self._mock_create(mcp_results)
        
        # TODO: 실제 벡터 DB 저장 로직
        # documents = []
        # metadatas = []
        # 
        # # Location 결과 변환
        # if 'location' in mcp_results:
        #     for store in mcp_results['location'].get('stores', []):
        #         doc = f"""
        #         이름: {store['name']}
        #         주소: {store['address']}
        #         거리: {store['distance']}m
        #         카테고리: {store['category']}
        #         """
        #         documents.append(doc)
        #         metadatas.append({"type": "location", "store_id": store['id']})
        # 
        # # Discount 결과 변환
        # if 'discount' in mcp_results:
        #     for discount in mcp_results['discount'].get('discounts', []):
        #         doc = f"할인: {discount['name']}, {discount['discount_rate']}%"
        #         documents.append(doc)
        #         metadatas.append({"type": "discount"})
        # 
        # # 임베딩 생성
        # embeddings = self.embedder.encode(documents)
        # 
        # # 벡터 DB 저장
        # self.collection.add(
        #     documents=documents,
        #     embeddings=embeddings,
        #     metadatas=metadatas,
        #     ids=[f"{session_id}_{i}" for i in range(len(documents))]
        # )
        
        pass
    
    def search(
        self, 
        user_query: str, 
        top_k: int = 3,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        사용자 질문과 유사한 정보 검색 (RAG)
        
        Args:
            user_query: 사용자 질문
            top_k: 반환할 결과 개수
            session_id: 세션 ID
        
        Returns:
            검색된 문서 및 메타데이터
        """
        if not self.is_implemented:
            # TODO: 실제 구현 제거
            return self._mock_search(user_query, top_k)
        
        # TODO: 실제 벡터 검색 로직
        # # 질문 임베딩
        # query_embedding = self.embedder.encode([user_query])
        # 
        # # 유사도 검색
        # results = self.collection.query(
        #     query_embeddings=query_embedding,
        #     n_results=top_k,
        #     where={"session_id": session_id} if session_id else None
        # )
        # 
        # return {
        #     "documents": results['documents'][0],
        #     "metadatas": results['metadatas'][0],
        #     "distances": results['distances'][0]
        # }
        
        pass
    
    def clear_session(self, session_id: str):
        """
        세션 종료 시 임시 벡터 DB 삭제
        
        Args:
            session_id: 세션 ID
        """
        if not self.is_implemented:
            return
        
        # TODO: 실제 구현
        # self.collection.delete(where={"session_id": session_id})
        pass
    
    # ==================== 스텁 (Mock) 메서드 ====================
    
    def _mock_create(self, mcp_results: Dict[str, Any]) -> Dict[str, Any]:
        """벡터 DB 생성 스텁"""
        total_docs = 0
        
        if 'location' in mcp_results:
            total_docs += len(mcp_results['location'].get('stores', []))
        
        if 'discount' in mcp_results:
            total_docs += len(mcp_results['discount'].get('mock_data', {}).get('discounts', []))
        
        return {
            "message": "✅ 벡터 DB 생성 완료 (Mock)",
            "total_documents": total_docs,
            "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2 (예정)"
        }
    
    def _mock_search(self, user_query: str, top_k: int) -> Dict[str, Any]:
        """벡터 검색 스텁"""
        # 간단한 키워드 기반 필터링 (실제 임베딩 검색 아님)
        return {
            "message": "✅ 벡터 검색 완료 (Mock)",
            "query": user_query,
            "top_k": top_k,
            "results": [
                {
                    "document": "상점 A: 강남역 근처, 100m",
                    "similarity": 0.95,
                    "metadata": {"type": "location", "store_id": "001"}
                },
                {
                    "document": "할인: 신한카드 10% 할인",
                    "similarity": 0.88,
                    "metadata": {"type": "discount"}
                }
            ][:top_k]
        }


class RAGPipeline:
    """
    RAG 파이프라인
    MCP 결과 → 벡터 DB → 검색 → LLM 컨텍스트 생성
    """
    
    def __init__(self, use_openai_embeddings: bool = False):
        """초기화"""
        self.vector_db = VectorDBManager(use_openai_embeddings)
    
    def process(
        self,
        user_query: str,
        mcp_results: Dict[str, Any],
        top_k: int = 3,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RAG 전체 파이프라인 실행
        
        Args:
            user_query: 사용자 질문
            mcp_results: MCP Server 호출 결과
            top_k: 검색할 결과 개수
            session_id: 세션 ID
        
        Returns:
            LLM에게 전달할 컨텍스트
        """
        # [1단계] MCP 결과를 벡터 DB에 저장
        create_result = self.vector_db.create_from_mcp_results(
            mcp_results,
            session_id
        )
        
        # [2단계] 사용자 질문과 유사한 정보 검색
        search_result = self.vector_db.search(
            user_query,
            top_k,
            session_id
        )
        
        # [3단계] LLM용 컨텍스트 생성
        context = self._build_llm_context(search_result)
        
        return {
            "create_result": create_result,
            "search_result": search_result,
            "llm_context": context
        }
    
    def _build_llm_context(self, search_result: Dict[str, Any]) -> str:
        """
        검색 결과를 LLM용 컨텍스트로 변환
        
        Args:
            search_result: 벡터 검색 결과
        
        Returns:
            LLM에게 전달할 문자열
        """
        if not search_result.get('results'):
            return "검색된 정보가 없습니다."
        
        context = "다음 정보만 사용해서 답변하세요:\n\n"
        
        for i, result in enumerate(search_result['results'], 1):
            context += f"{i}. {result['document']}\n"
            context += f"   (유사도: {result['similarity']:.2f})\n\n"
        
        context += "\n⚠️ 위 정보에 없는 내용은 '정보가 없습니다'라고 답변하세요."
        
        return context


# ==================== 사용 예시 ====================

if __name__ == "__main__":
    # RAG 파이프라인 초기화
    rag = RAGPipeline(use_openai_embeddings=False)
    
    # Mock MCP 결과
    mcp_results = {
        "location": {
            "stores": [
                {"id": "001", "name": "맛있는집", "address": "강남역 근처", "distance": 100, "category": "한식"},
                {"id": "002", "name": "카페A", "address": "강남역", "distance": 200, "category": "카페"}
            ]
        },
        "discount": {
            "mock_data": {
                "discounts": [
                    {"name": "신한카드 10% 할인", "discount_rate": 10}
                ]
            }
        }
    }
    
    # 사용자 질문
    user_query = "강남역 근처 맛집 추천해줘"
    
    # RAG 처리
    result = rag.process(user_query, mcp_results, top_k=3)
    
    print("=" * 60)
    print("RAG 파이프라인 테스트")
    print("=" * 60)
    print(f"\n[사용자 질문] {user_query}")
    print(f"\n[벡터 DB 생성]")
    print(json.dumps(result['create_result'], ensure_ascii=False, indent=2))
    print(f"\n[벡터 검색 결과]")
    print(json.dumps(result['search_result'], ensure_ascii=False, indent=2))
    print(f"\n[LLM 컨텍스트]")
    print(result['llm_context'])
    print("=" * 60)

