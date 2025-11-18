"""
리뷰 생성기 (Mock Data Generator)

네이버 맵 크롤링의 합법적 대안으로, 현실적인 mock 리뷰 데이터를 생성합니다.
개발 및 테스트 환경에서 RAG 시스템을 위한 데이터를 제공합니다.

특징:
- 카테고리별 맞춤 리뷰 생성
- 평점 분포를 고려한 현실적인 데이터
- 시간대별 리뷰 분포
- 다양한 리뷰 스타일 (긍정, 부정, 중립)
"""

import random
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReviewGenerator:
    """현실적인 mock 리뷰 생성기"""
    
    # 한국 이름 풀
    SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권", "황", "안", "송", "류", "홍"]
    GIVEN_NAMES = ["민준", "서연", "도윤", "서준", "예준", "하준", "지민", "은우", "시우", "준서", "유진", "지훈", "민서", "수빈", "지우", "현우", "지안", "정민", "승우", "은서"]
    
    # 카테고리별 리뷰 템플릿
    REVIEW_TEMPLATES = {
        "카페": {
            "positive": [
                "커피 맛이 정말 좋아요! 원두 품질이 느껴집니다. 분위기도 아늑하고 좋네요.",
                "조용해서 작업하기 딱 좋은 곳이에요. 와이파이도 빠르고 콘센트도 많습니다.",
                "디저트가 맛있어요! 특히 케이크가 촉촉하고 달지 않아서 좋았습니다.",
                "직원분들이 친절하시고 인테리어가 예뻐서 사진 찍기 좋아요. 재방문 의사 100%",
                "커피 맛도 좋고 가격도 합리적이에요. 근처에 이런 카페가 있어서 다행이네요.",
                "넓고 쾌적해서 회의하기 좋았어요. 음료 맛도 준수합니다.",
                "분위기가 차분해서 책 읽기 좋아요. 조명도 적당하고 음악도 좋습니다.",
                "라떼 아트가 예쁘고 맛도 부드러워요. 원두 선택도 다양해서 좋습니다.",
            ],
            "neutral": [
                "평범한 카페예요. 나쁘지 않은데 특별하지도 않아요.",
                "커피 맛은 괜찮은데 가격이 조금 비싼 편이에요.",
                "붐비는 시간대에는 자리 잡기 어려워요. 조용히 있고 싶으면 평일 오전 추천.",
                "커피 맛은 그럭저럭인데 디저트는 별로였어요.",
            ],
            "negative": [
                "직원 태도가 불친절했어요. 커피 맛도 그냥 그래요.",
                "너무 시끄러워서 대화하기 힘들었어요. 음악 소리를 좀 줄이면 좋겠어요.",
                "가격에 비해 양이 너무 적어요. 커피 맛도 평범합니다.",
            ]
        },
        "한식": {
            "positive": [
                "집밥 같은 정갈한 맛이에요. 반찬도 많이 나오고 다 맛있습니다!",
                "사장님이 정말 친절하세요. 음식도 푸짐하고 맛있어요. 강추!",
                "된장찌개가 진짜 깊은 맛이 나요. 한번 가면 계속 생각나는 맛입니다.",
                "반찬이 정말 맛있어요. 특히 김치가 적당히 익어서 좋았습니다.",
                "가격 대비 양이 푸짐해요. 든든하게 먹을 수 있어서 좋습니다.",
                "전통 한식당 느낌이 물씬 나요. 음식이 정성스럽게 나옵니다.",
                "밑반찬도 계속 리필해주시고 친절해요. 음식 맛도 훌륭합니다!",
                "깔끔하고 맛있어요. 점심시간에 직장인들이 많이 찾는 이유를 알겠네요.",
            ],
            "neutral": [
                "평범한 한식당이에요. 나쁘지는 않은데 특별한 맛은 아니에요.",
                "양은 많은데 간이 좀 센 편이에요.",
                "점심시간에는 대기가 있어요. 미리 가는 게 좋을 것 같아요.",
            ],
            "negative": [
                "음식이 너무 짜요. 건강에 좋지 않을 것 같아요.",
                "가격이 비싼 편인데 맛은 그냥 그래요.",
            ]
        },
        "일식": {
            "positive": [
                "회가 정말 신선해요! 사시미 두께도 적당하고 맛있습니다.",
                "스시 맛이 일품이에요. 밥알과 생선의 조화가 좋아요.",
                "가격이 합리적인데 맛있어요. 런치세트 추천합니다!",
                "정갈하고 깔끔해요. 일본 현지 느낌이 나는 것 같아요.",
                "초밥 하나하나에 정성이 느껴져요. 사장님이 직접 만드시는데 솜씨가 대단합니다.",
                "우동 육수가 진짜 맛있어요. 면발도 쫄깃하고 좋습니다.",
                "모듬초밥 구성이 알차요. 신선하고 맛있어서 만족스러웠습니다.",
            ],
            "neutral": [
                "평범한 일식집이에요. 나쁘지 않지만 특별하지도 않아요.",
                "가격이 조금 비싼 편이에요. 맛은 괜찮습니다.",
            ],
            "negative": [
                "회 신선도가 떨어지는 것 같아요. 실망스러웠어요.",
                "가성비가 좋지 않아요. 다시 가기는 글쎄요.",
            ]
        },
        "중식": {
            "positive": [
                "짜장면 맛이 정말 좋아요! 면발도 쫄깃하고 짜장 소스가 고소해요.",
                "탕수육이 바삭바삭해요. 소스도 새콤달콤하니 맛있습니다!",
                "배달도 빠르고 음식도 따뜻하게 왔어요. 맛도 최고!",
                "양이 정말 많아요. 가성비 훌륭합니다!",
                "짬뽕이 얼큰하고 시원해요. 해물도 많이 들어있어요.",
                "깔끔한 중식당이에요. 음식도 맛있고 서비스도 좋습니다.",
            ],
            "neutral": [
                "평범한 중식당 맛이에요. 나쁘지는 않아요.",
                "배달 시간이 좀 걸렸어요. 맛은 괜찮습니다.",
            ],
            "negative": [
                "짜장면이 너무 달아요. 제 입맛에는 안 맞네요.",
                "탕수육이 눅눅했어요. 바로 튀긴 게 아닌 것 같아요.",
            ]
        },
        "양식": {
            "positive": [
                "파스타가 정말 맛있어요! 면이 알단테로 완벽해요.",
                "스테이크가 부드럽고 육즙이 살아있어요. 소스도 훌륭합니다!",
                "분위기가 로맨틱해서 데이트하기 좋아요. 음식도 맛있습니다.",
                "리조또 맛이 일품이에요. 크리미하면서도 느끼하지 않아요.",
                "플레이팅이 예쁘고 맛도 좋아요. 특별한 날 오기 좋습니다.",
                "피자 도우가 얇고 바삭해요. 토핑도 신선하고 맛있습니다!",
            ],
            "neutral": [
                "맛은 괜찮은데 가격이 비싼 편이에요.",
                "음식 나오는 시간이 좀 오래 걸렸어요.",
            ],
            "negative": [
                "가격 대비 양이 너무 적어요. 배부르게 먹기 힘들어요.",
                "파스타가 너무 짜요. 소금을 좀 줄이면 좋겠어요.",
            ]
        },
        "default": {
            "positive": [
                "음식이 맛있어요! 재방문 의사 있습니다.",
                "분위기 좋고 서비스도 친절해요. 추천합니다!",
                "가성비가 좋아요. 양도 푸짐하고 맛도 좋습니다.",
                "깔끔하고 맛있어요. 근처에 있어서 자주 올 것 같아요.",
                "음식이 빨리 나와요. 맛도 훌륭합니다!",
            ],
            "neutral": [
                "평범해요. 나쁘지는 않은데 특별하지도 않아요.",
                "가격이 좀 비싼 편이에요.",
            ],
            "negative": [
                "별로였어요. 다시 가고 싶지 않네요.",
                "서비스가 좀 아쉬워요.",
            ]
        }
    }
    
    def __init__(self, data_dir: str = "./data/generated_reviews"):
        """
        Args:
            data_dir: 생성된 리뷰 데이터 저장 디렉토리
        """
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
    
    def generate_name(self) -> str:
        """랜덤 한국 이름 생성"""
        surname = random.choice(self.SURNAMES)
        given_name = random.choice(self.GIVEN_NAMES)
        
        # 일부는 익명 처리
        if random.random() < 0.3:
            return f"{surname}*{given_name[0]}"
        else:
            return f"{surname}{given_name}"
    
    def generate_rating(self, store_rating: float) -> float:
        """
        가게 평점을 고려한 개별 리뷰 평점 생성
        
        Args:
            store_rating: 가게 전체 평점 (0-5)
        
        Returns:
            리뷰 평점 (1-5)
        """
        # 가게 평점 근처에서 정규분포로 생성
        rating = random.gauss(store_rating, 0.5)
        
        # 1-5 범위로 제한
        rating = max(1.0, min(5.0, rating))
        
        # 0.5 단위로 반올림
        rating = round(rating * 2) / 2
        
        return rating
    
    def get_review_sentiment(self, rating: float) -> str:
        """
        평점에 따른 감정 분류
        
        Args:
            rating: 리뷰 평점
        
        Returns:
            'positive', 'neutral', 'negative'
        """
        if rating >= 4.0:
            return "positive"
        elif rating >= 3.0:
            return "neutral"
        else:
            return "negative"
    
    def generate_review_content(self, category: str, rating: float) -> str:
        """
        카테고리와 평점에 맞는 리뷰 내용 생성
        
        Args:
            category: 가게 카테고리
            rating: 리뷰 평점
        
        Returns:
            리뷰 텍스트
        """
        sentiment = self.get_review_sentiment(rating)
        
        # 카테고리에서 키워드 추출
        category_key = "default"
        for key in self.REVIEW_TEMPLATES.keys():
            if key in category:
                category_key = key
                break
        
        # 해당 카테고리 & 감정의 템플릿 선택
        templates = self.REVIEW_TEMPLATES.get(category_key, {}).get(sentiment, [])
        
        if not templates:
            templates = self.REVIEW_TEMPLATES["default"][sentiment]
        
        return random.choice(templates)
    
    def generate_date(self, days_ago_max: int = 365) -> str:
        """
        랜덤 날짜 생성 (최근 N일 이내)
        
        Args:
            days_ago_max: 최대 며칠 전까지
        
        Returns:
            날짜 문자열
        """
        days_ago = random.randint(0, days_ago_max)
        date = datetime.now() - timedelta(days=days_ago)
        
        # 날짜 형식: "N일 전", "N주 전", "N개월 전"
        if days_ago == 0:
            return "오늘"
        elif days_ago == 1:
            return "1일 전"
        elif days_ago < 7:
            return f"{days_ago}일 전"
        elif days_ago < 30:
            weeks = days_ago // 7
            return f"{weeks}주 전"
        elif days_ago < 365:
            months = days_ago // 30
            return f"{months}개월 전"
        else:
            years = days_ago // 365
            return f"{years}년 전"
    
    def generate_reviews(
        self, 
        store_info: Dict[str, Any], 
        count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        특정 가게에 대한 리뷰 생성
        
        Args:
            store_info: 가게 정보 (id, name, category, rating 등)
            count: 생성할 리뷰 수 (기본 5개)
        
        Returns:
            리뷰 리스트
        """
        logger.info(f"📝 리뷰 생성 중: {store_info.get('name', 'Unknown')} ({count}개)")
        
        reviews = []
        store_rating = store_info.get('rating', 4.0)
        category = store_info.get('category', '음식점')
        
        for i in range(count):
            rating = self.generate_rating(store_rating)
            
            review = {
                "id": f"gen_{store_info.get('id', 'unknown')}_{i}",
                "author": self.generate_name(),
                "rating": rating,
                "content": self.generate_review_content(category, rating),
                "date": self.generate_date(),
                "helpful_count": random.randint(0, 100),
                "visit_count": random.choice(["첫 방문", "재방문", "단골"]),
                "generated": True,  # Mock 데이터임을 표시
                "generated_at": datetime.now().isoformat()
            }
            
            reviews.append(review)
        
        logger.info(f"✅ 리뷰 {count}개 생성 완료")
        
        return reviews
    
    def generate_stores_with_reviews(
        self,
        stores: List[Dict[str, Any]],
        reviews_per_store: int = 5
    ) -> Dict[str, Any]:
        """
        여러 가게에 대한 리뷰 생성
        
        Args:
            stores: 가게 정보 리스트 (LocationServer에서 받은 결과)
            reviews_per_store: 가게당 리뷰 수 (기본 5개)
        
        Returns:
            전체 결과 (가게 + 리뷰)
        """
        logger.info("=" * 60)
        logger.info(f"🚀 Mock 리뷰 생성 시작: {len(stores)}개 가게")
        logger.info(f"   각 가게당 {reviews_per_store}개 리뷰")
        logger.info("=" * 60)
        
        enriched_stores = []
        
        for idx, store in enumerate(stores, 1):
            logger.info(f"\n[{idx}/{len(stores)}] 🏪 {store.get('name', 'Unknown')}")
            
            # 리뷰 생성
            reviews = self.generate_reviews(store, count=reviews_per_store)
            
            # 가게 정보에 리뷰 추가
            enriched_store = store.copy()
            enriched_store['reviews'] = reviews
            enriched_store['collected_review_count'] = len(reviews)
            enriched_store['review_summary'] = self._create_review_summary(reviews)
            
            enriched_stores.append(enriched_store)
        
        result = {
            "stores": enriched_stores,
            "total_stores": len(enriched_stores),
            "total_reviews": sum(len(s.get('reviews', [])) for s in enriched_stores),
            "generated_at": datetime.now().isoformat(),
            "status": "success",
            "data_type": "mock"  # Mock 데이터임을 명시
        }
        
        logger.info("=" * 60)
        logger.info(f"✅ Mock 리뷰 생성 완료!")
        logger.info(f"   가게: {result['total_stores']}개")
        logger.info(f"   리뷰: {result['total_reviews']}개")
        logger.info("=" * 60)
        
        return result
    
    def _create_review_summary(self, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        리뷰 요약 통계 생성
        
        Args:
            reviews: 리뷰 리스트
        
        Returns:
            요약 통계
        """
        if not reviews:
            return {}
        
        ratings = [r['rating'] for r in reviews]
        
        return {
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "total_count": len(reviews),
            "rating_distribution": {
                "5": sum(1 for r in ratings if r >= 4.5),
                "4": sum(1 for r in ratings if 3.5 <= r < 4.5),
                "3": sum(1 for r in ratings if 2.5 <= r < 3.5),
                "2": sum(1 for r in ratings if 1.5 <= r < 2.5),
                "1": sum(1 for r in ratings if r < 1.5),
            }
        }
    
    def save_to_json(self, data: Dict[str, Any], filename: Optional[str] = None):
        """
        데이터를 JSON 파일로 저장
        
        Args:
            data: 저장할 데이터
            filename: 파일명 (없으면 자동 생성)
        """
        try:
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"mock_reviews_{timestamp}.json"
            
            filepath = os.path.join(self.data_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 JSON 저장 완료: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ JSON 저장 실패: {e}")


def main():
    """테스트 메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mock 리뷰 생성기")
    parser.add_argument("--stores", type=int, default=10, help="가게 수")
    parser.add_argument("--reviews", type=int, default=5, help="가게당 리뷰 수 (기본: 5)")
    
    args = parser.parse_args()
    
    # Mock 가게 데이터 (실제로는 LocationServer에서 가져옴)
    mock_stores = [
        {"id": f"store_{i}", "name": f"테스트 가게 {i}", "category": random.choice(["카페", "한식", "일식"]), "rating": round(random.uniform(3.5, 5.0), 1)}
        for i in range(args.stores)
    ]
    
    # 리뷰 생성
    generator = ReviewGenerator()
    result = generator.generate_stores_with_reviews(
        stores=mock_stores,
        reviews_per_store=args.reviews
    )
    
    # 저장
    generator.save_to_json(result)
    
    # 결과 출력
    print("\n" + "=" * 60)
    print("📊 생성 결과")
    print("=" * 60)
    print(f"가게 수: {result['total_stores']}개")
    print(f"총 리뷰: {result['total_reviews']}개")
    print("\n🏆 샘플 리뷰:")
    if result['stores'] and result['stores'][0]['reviews']:
        sample_review = result['stores'][0]['reviews'][0]
        print(f"  작성자: {sample_review['author']}")
        print(f"  평점: ⭐{sample_review['rating']}")
        print(f"  내용: {sample_review['content']}")


if __name__ == "__main__":
    main()

