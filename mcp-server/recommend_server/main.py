"""
추천/할인율 계산 서버 - MVP 버전
Stateless 계산 엔진: 할인 정보를 받아서 계산, 필터링, 정렬
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from models import RecommendationRequest, RecommendationResponse
from recommender import generate_recommendations
from config import SERVER_HOST, SERVER_PORT

# FastAPI 앱 생성
app = FastAPI(
    title="추천/할인율 계산 서버 (MVP)",
    description="할인 정보를 받아서 계산, 필터링, 정렬하는 Stateless 추천 엔진",
    version="1.0.0-mvp"
)

# 시작 시 메시지
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 초기화"""
    print("\n" + "="*60)
    print("🚀 추천 서버 MVP 시작")
    print("="*60)
    print("📌 역할: 할인 계산 + 필터링 + 정렬")
    print("📌 모드: Stateless 계산 엔진")
    print("📌 API: POST /recommend")
    print("="*60 + "\n")

# CORS 설정 (필요시)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 배포 시에는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """서버 상태 확인"""
    return {
        "service": "추천/할인율 계산 서버",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {
        "status": "healthy",
        "version": "1.0.0-mvp",
        "mode": "stateless",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/recommend", response_model=RecommendationResponse)
async def recommend_discounts(request: RecommendationRequest):
    """
    할인 추천 API
    
    입력으로 받은 할인 정보를 분석하여:
    1. 사용자 프로필에 맞는 할인 필터링
    2. 시간/요일/채널 제약조건 검증
    3. 할인액 계산
    4. 추천 순서로 정렬
    
    Returns:
        추천된 할인 정보 (적용 가능/불가능 분리)
    """
    try:
        # 입력 검증
        if not request.results or len(request.results) == 0:
            return RecommendationResponse(
                success=True,
                message="조회된 매장이 없습니다",
                total=0,
                recommendations=[],
                requestedAt=datetime.now(),
                channel=request.channel,
                orderAmount=request.orderAmount or 15000
            )
        
        # 추천 생성
        response = generate_recommendations(request)
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"추천 처리 중 오류 발생: {str(e)}"
        )


@app.post("/calculate", response_model=RecommendationResponse)
async def calculate_discounts(request: RecommendationRequest):
    """
    할인 계산 API (recommend와 동일하지만 명시적인 이름)
    
    Returns:
        계산된 할인 정보
    """
    return await recommend_discounts(request)



# 서버 실행 시 사용 (개발용)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=True
    )


