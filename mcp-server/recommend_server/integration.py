"""
MCP 서버 간 통신 통합 모듈

Location_server, Discount_MAP_server와 통신하여
위치 기반 매장 검색 → 할인 조회 → 추천 계산 파이프라인 구성
"""
import json
from typing import Dict, Any, List, Optional
import subprocess
import asyncio
import os
from utils import (
    normalize_telco,
    normalize_membership,
    map_category_to_search_term,
    extract_user_preferences,
    sort_recommendations_by_preference,
    validate_user_profile
)

# 실제 MCP 통신 사용 여부 (환경 변수로 제어)
USE_REAL_MCP = os.getenv("USE_REAL_MCP", "false").lower() == "true"

if USE_REAL_MCP:
    from mcp_client import LocationMCPClient, DiscountMCPClient


class LocationServiceClient:
    """Location_server MCP 클라이언트"""
    
    @staticmethod
    async def search_nearby_stores(
        latitude: float,
        longitude: float,
        category: str = "음식점",
        radius: int = 1000
    ) -> Dict[str, Any]:
        """
        위치 기반으로 근처 매장 검색
        
        Args:
            latitude: 위도
            longitude: 경도
            category: 검색 카테고리
            radius: 검색 반경(미터)
            
        Returns:
            {
                "query": {...},
                "total_count": 10,
                "stores": [
                    {
                        "id": "...",
                        "name": "스타벅스 동국대점",
                        "category": "음식점 > 카페",
                        "distance": 150,
                        "address": "서울 중구 필동로1길 30",
                        ...
                    }
                ]
            }
        """
        print(f"[Integration] Location_server 호출 중... (lat={latitude}, lon={longitude})")
        
        if USE_REAL_MCP:
            # 실제 MCP 클라이언트 사용
            try:
                async with LocationMCPClient() as client:
                    result = await client.search_nearby_stores(
                        latitude=latitude,
                        longitude=longitude,
                        category=category,
                        radius=radius
                    )
                    print(f"[Integration] ✅ 실제 MCP 응답 수신: {len(result.get('stores', []))}개 매장")
                    return result
            except Exception as e:
                print(f"[Integration] ⚠️ MCP 호출 실패, 더미 데이터 사용: {e}")
                # Fallback to dummy data
        
        # 더미 데이터 반환 (개발/테스트용)
        print(f"[Integration] ℹ️ 더미 데이터 사용 (USE_REAL_MCP={USE_REAL_MCP})")
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "category": category,
                "radius": radius
            },
            "total_count": 3,
            "stores": [
                {
                    "id": "1",
                    "name": "스타벅스 동국대점",
                    "category": "음식점 > 카페",
                    "distance": 150,
                    "address": "서울 중구 필동로1길 30",
                    "phone": "02-2277-1234",
                    "latitude": latitude + 0.001,
                    "longitude": longitude + 0.001,
                    "rating": 4.3
                },
                {
                    "id": "2",
                    "name": "이디야커피 충무로역점",
                    "category": "음식점 > 카페",
                    "distance": 200,
                    "address": "서울 중구 퇴계로 100",
                    "phone": "02-2266-5678",
                    "latitude": latitude + 0.002,
                    "longitude": longitude + 0.002,
                    "rating": 4.1
                }
            ],
            "message": "✅ 위치 기반 매장 검색 완료 (더미 데이터)"
        }


class DiscountServiceClient:
    """Discount_MAP_server MCP 클라이언트"""
    
    @staticmethod
    async def get_discounts_for_stores(
        user_profile: Dict[str, Any],
        store_names: List[str]
    ) -> Dict[str, Any]:
        """
        매장별 할인 정보 조회
        
        Args:
            user_profile: {
                "userId": "user123",
                "telco": "SKT",
                "memberships": ["CJ ONE"],
                "cards": ["신한카드 YOLO Tasty"],
                "affiliations": []
            }
            store_names: ["스타벅스 동국대점", "이디야커피 충무로역점"]
            
        Returns:
            {
                "success": True,
                "message": "할인 정보 조회 완료",
                "total": 2,
                "results": [
                    {
                        "inputStoreName": "스타벅스 동국대점",
                        "matched": True,
                        "merchant": {
                            "brand": {"brandId": 1, "brandName": "스타벅스", ...},
                            "branch": {"branchId": 10, "branchName": "동국대점"}
                        },
                        "discounts": [...]
                    }
                ]
            }
        """
        print(f"[Integration] Discount_MAP_server 호출 중... (stores={len(store_names)}개)")
        
        if USE_REAL_MCP:
            # 실제 MCP 클라이언트 사용
            try:
                async with DiscountMCPClient() as client:
                    result = await client.get_discounts_for_stores(
                        user_profile=user_profile,
                        stores=store_names
                    )
                    print(f"[Integration] ✅ 실제 MCP 응답 수신: {result.get('total', 0)}개 매장")
                    return result
            except Exception as e:
                print(f"[Integration] ⚠️ MCP 호출 실패, 더미 데이터 사용: {e}")
                # Fallback to dummy data
        
        # 더미 데이터 반환 (개발/테스트용)
        print(f"[Integration] ℹ️ 더미 데이터 사용 (USE_REAL_MCP={USE_REAL_MCP})")
        return {
            "success": True,
            "message": "할인 정보 조회 완료 (더미 데이터)",
            "total": len(store_names),
            "results": [
                {
                    "inputStoreName": store_name,
                    "matched": True,
                    "merchant": {
                        "brand": {
                            "brandId": idx + 1,
                            "brandName": store_name.split()[0] if " " in store_name else store_name,
                            "brandOwner": None
                        },
                        "branch": {
                            "branchId": (idx + 1) * 10,
                            "branchName": store_name.split()[1] if " " in store_name else None
                        } if " " in store_name else None
                    },
                    "discounts": []
                }
                for idx, store_name in enumerate(store_names)
            ]
        }


class DataTransformer:
    """서버 간 데이터 형식 변환"""
    
    @staticmethod
    def location_to_store_names(location_response: Dict[str, Any]) -> List[str]:
        """
        Location_server 응답에서 매장명 추출
        
        Args:
            location_response: Location_server의 응답
            
        Returns:
            ["스타벅스 동국대점", "이디야커피 충무로역점"]
        """
        stores = location_response.get("stores", [])
        return [store.get("name") for store in stores if store.get("name")]
    
    @staticmethod
    def discount_to_recommendation_request(
        discount_response: Dict[str, Any],
        channel: str = "OFFLINE",
        order_amount: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Discount_MAP_server 응답을 추천 서버 입력 형식으로 변환
        
        Args:
            discount_response: Discount_MAP_server의 응답
            channel: 결제 채널
            order_amount: 주문 금액
            
        Returns:
            RecommendationRequest 형식의 딕셔너리
        """
        results = discount_response.get("results", [])
        
        # Discount_MAP_server 응답을 recommend_server 형식으로 변환
        transformed_results = []
        
        for result in results:
            merchant = result.get("merchant", {})
            brand = merchant.get("brand", {})
            branch = merchant.get("branch")
            
            # target 정보 구성
            target = {
                "externalBranchId": result.get("inputStoreName", ""),
                "matchedBranchId": branch.get("branchId") if branch else brand.get("brandId", 0)
            }
            
            # merchant 정보 구성 (간소화된 형태)
            merchant_info = {
                "merchantId": brand.get("brandId", 0),
                "merchantName": brand.get("brandName", "")
            }
            
            # discounts 변환
            discounts = DataTransformer._transform_discounts(result.get("discounts", []))
            
            transformed_results.append({
                "target": target,
                "merchant": merchant_info,
                "discounts": discounts
            })
        
        return {
            "results": transformed_results,
            "channel": channel,
            "orderAmount": order_amount
        }
    
    @staticmethod
    def _transform_discounts(discounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Discount_MAP_server의 할인 정보를 recommend_server 형식으로 변환
        
        Discount_MAP 형식:
        {
            "discountId": 1,
            "discountName": "T 멤버십 할인",
            "providerType": "TELCO",
            "providerName": "SKT",
            "shape": {
                "kind": "PERCENT",
                "amount": 10,
                "maxAmount": 3000,
                "unitRule": {...}
            },
            "appliedByUserProfile": True/False
        }
        
        recommend_server 형식:
        {
            "discountId": 1,
            "discountName": "T 멤버십 할인",
            "provider": {
                "providerName": "SKT",
                "providerType": "TELCO"
            },
            "shape": {
                "kind": "PERCENT",
                "params": {
                    "percent": 10,
                    "maxDiscountAmt": 3000
                }
            },
            "appliedByUserProfile": {
                "matchedTelco": "SKT"
            }
        }
        """
        transformed = []
        
        for discount in discounts:
            shape = discount.get("shape", {})
            shape_kind = shape.get("kind")
            
            # params 구성
            params = {}
            if shape_kind == "PERCENT":
                params["percent"] = shape.get("amount")
                params["maxDiscountAmt"] = shape.get("maxAmount")
            elif shape_kind == "AMOUNT":
                params["amount"] = int(shape.get("amount", 0))
            elif shape_kind == "PER_UNIT":
                unit_rule = shape.get("unitRule", {})
                params["unitAmount"] = unit_rule.get("unitAmount")
                params["amountPerUnit"] = unit_rule.get("perUnitValue")
                params["maxDiscountAmt"] = unit_rule.get("maxDiscountAmount")
            
            # appliedByUserProfile 변환
            applied_profile = None
            if discount.get("appliedByUserProfile"):
                provider_type = discount.get("providerType")
                provider_name = discount.get("providerName")
                
                applied_profile = {
                    "matchedTelco": provider_name if provider_type == "TELCO" else None,
                    "matchedCard": provider_name if provider_type == "PAYMENT" else None,
                    "matchedMembership": provider_name if provider_type == "MEMBERSHIP" else None
                }
            
            transformed.append({
                "discountId": discount.get("discountId"),
                "discountName": discount.get("discountName"),
                "provider": {
                    "providerName": discount.get("providerName", ""),
                    "providerType": discount.get("providerType", "")
                },
                "shape": {
                    "kind": shape_kind,
                    "params": params
                },
                "constraints": discount.get("constraints"),
                "requiredConditions": discount.get("requiredConditions"),
                "appliedByUserProfile": applied_profile,
                "canBeCombined": discount.get("canBeCombined", True)
            })
        
        return transformed
    
    @staticmethod
    def enrich_recommendations_with_location(
        recommendations: Dict[str, Any],
        location_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        추천 결과에 위치 정보 추가
        
        Args:
            recommendations: 추천 서버 응답
            location_response: Location_server 응답
            
        Returns:
            위치 정보가 추가된 추천 결과
        """
        # 매장명을 키로 하는 위치 정보 맵 생성
        location_map = {
            store.get("name"): store
            for store in location_response.get("stores", [])
        }
        
        # 각 추천 결과에 위치 정보 추가
        enriched = recommendations.copy()
        for rec in enriched.get("recommendations", []):
            store_name = rec.get("inputStoreName")
            if store_name and store_name in location_map:
                loc = location_map[store_name]
                rec["location"] = {
                    "address": loc.get("address"),
                    "roadAddress": loc.get("road_address"),
                    "distance": loc.get("distance"),
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                    "phone": loc.get("phone"),
                    "rating": loc.get("rating")
                }
        
        return enriched


async def get_location_based_recommendations(
    latitude: float,
    longitude: float,
    user_profile: Optional[Dict[str, Any]] = None,
    category: str = "음식점",
    radius: int = 1000,
    channel: str = "OFFLINE",
    order_amount: Optional[int] = None,
    store_type_filter: str = "ALL"
) -> Dict[str, Any]:
    """
    위치 기반 할인 추천 통합 파이프라인
    
    1. Location_server에서 근처 매장 검색
    2. Discount_MAP_server에서 할인 정보 조회
    3. 추천 엔진으로 계산/정렬
    4. 위치 정보 추가하여 반환
    
    Args:
        latitude: 위도
        longitude: 경도
        user_profile: 사용자 프로필 (없으면 기본값)
        category: 검색 카테고리
        radius: 검색 반경
        channel: 결제 채널
        order_amount: 주문 금액
        store_type_filter: 매장 타입 필터 ("ALL", "FRANCHISE", "INDEPENDENT")
        
    Returns:
        위치 정보가 포함된 추천 결과
    """
    # 기본 사용자 프로필 설정
    if user_profile is None:
        user_profile = {
            "userId": "anonymous",
            "telco": None,
            "memberships": [],
            "cards": [],
            "affiliations": []
        }
    
    # 사용자 프로필 검증
    is_valid, error_msg = validate_user_profile(user_profile)
    if not is_valid:
        return {
            "success": False,
            "message": f"프로필 검증 실패: {error_msg}",
            "total": 0,
            "recommendations": []
        }
    
    # 프로필 정규화
    if user_profile.get("telco"):
        user_profile["telco"] = normalize_telco(user_profile["telco"])
    
    if user_profile.get("memberships"):
        user_profile["memberships"] = [
            normalize_membership(m) for m in user_profile["memberships"]
        ]
    
    # 카테고리를 검색어로 매핑
    search_term = map_category_to_search_term(category)
    
    # 사용자 선호도 추출
    preferences = extract_user_preferences(category, user_profile)
    
    try:
        # Step 1: 위치 기반 매장 검색
        location_client = LocationServiceClient()
        location_response = await location_client.search_nearby_stores(
            latitude=latitude,
            longitude=longitude,
            category=search_term,  # 매핑된 검색어 사용
            radius=radius
        )
        
        # Step 2: 매장명 추출
        store_names = DataTransformer.location_to_store_names(location_response)
        
        if not store_names:
            return {
                "success": False,
                "message": "근처에 매장을 찾을 수 없습니다",
                "total": 0,
                "recommendations": []
            }
        
        # Step 3: 할인 정보 조회
        discount_client = DiscountServiceClient()
        discount_response = await discount_client.get_discounts_for_stores(
            user_profile=user_profile,
            store_names=store_names
        )
        
        # Step 4: 추천 요청 형식으로 변환
        from models import RecommendationRequest
        from recommender import generate_recommendations
        
        request_dict = DataTransformer.discount_to_recommendation_request(
            discount_response=discount_response,
            channel=channel,
            order_amount=order_amount
        )
        
        # 매장 타입 필터 추가
        request_dict['storeTypeFilter'] = store_type_filter
        
        request = RecommendationRequest(**request_dict)
        
        # Step 5: 추천 계산
        recommendations = generate_recommendations(request)
        
        # Step 6: 위치 정보 추가
        result = DataTransformer.enrich_recommendations_with_location(
            recommendations=recommendations.model_dump(mode='json'),
            location_response=location_response
        )
        
        # Step 7: 사용자 선호도 기반 재정렬
        if result.get('recommendations'):
            result['recommendations'] = sort_recommendations_by_preference(
                recommendations=result['recommendations'],
                preferences=preferences
            )
        
        # 메타 정보 추가
        result['metadata'] = {
            "original_category": category,
            "search_term": search_term,
            "preferences": preferences,
            "user_profile_normalized": {
                "telco": user_profile.get("telco"),
                "memberships_count": len(user_profile.get("memberships", [])),
                "cards_count": len(user_profile.get("cards", []))
            }
        }
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "message": f"위치 기반 추천 중 오류 발생: {str(e)}",
            "total": 0,
            "recommendations": []
        }

