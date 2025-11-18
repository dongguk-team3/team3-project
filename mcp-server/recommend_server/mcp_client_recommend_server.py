"""
MCP 클라이언트 구현

다른 MCP 서버(Location_server, Discount_MAP_server)와 통신하는 클라이언트
"""
import asyncio
import json
import sys
from typing import Dict, Any, Optional, List
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    """기본 MCP 클라이언트"""
    
    def __init__(self, server_script_path: str, server_name: str = "mcp-server"):
        """
        Args:
            server_script_path: MCP 서버 스크립트 경로 (예: "/path/to/location_server.py")
            server_name: 서버 이름 (로깅용)
        """
        self.server_script_path = server_script_path
        self.server_name = server_name
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
    
    async def connect(self):
        """MCP 서버에 연결"""
        # stdio 기반 서버 파라미터 설정
        server_params = StdioServerParameters(
            command="python",
            args=[self.server_script_path],
            env=None
        )
        
        # stdio 클라이언트 생성
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        
        read, write = stdio_transport
        
        # ClientSession 생성 및 초기화
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        
        await self.session.initialize()
        
        print(f"[MCP Client] {self.server_name} 연결 완료", file=sys.stderr)
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        MCP Tool 호출
        
        Args:
            tool_name: Tool 이름
            arguments: Tool 인자
            
        Returns:
            Tool 실행 결과
        """
        if not self.session:
            raise RuntimeError("MCP 서버에 연결되지 않았습니다. connect()를 먼저 호출하세요.")
        
        print(f"[MCP Client] Calling tool: {tool_name}", file=sys.stderr)
        print(f"[MCP Client] Arguments: {json.dumps(arguments, ensure_ascii=False)}", file=sys.stderr)
        
        # Tool 호출
        result = await self.session.call_tool(tool_name, arguments)
        
        print(f"[MCP Client] Result received from {tool_name}", file=sys.stderr)
        
        return result
    
    async def list_tools(self) -> List[Any]:
        """사용 가능한 Tool 목록 조회"""
        if not self.session:
            raise RuntimeError("MCP 서버에 연결되지 않았습니다.")
        
        result = await self.session.list_tools()
        return result.tools
    
    async def close(self):
        """연결 종료"""
        await self.exit_stack.aclose()
        print(f"[MCP Client] {self.server_name} 연결 종료", file=sys.stderr)


class LocationMCPClient:
    """Location_server MCP 클라이언트"""
    
    def __init__(self, server_path: str = "/opt/conda/envs/team/OSS/mcp-server/Location_server/location_server.py"):
        self.server_path = server_path
        self.client: Optional[MCPClient] = None
    
    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        self.client = MCPClient(self.server_path, "Location_server")
        await self.client.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self.client:
            await self.client.close()
    
    async def search_nearby_stores(
        self,
        latitude: float,
        longitude: float,
        category: str = "음식점",
        radius: int = 1000
    ) -> Dict[str, Any]:
        """
        근처 매장 검색
        
        Args:
            latitude: 위도
            longitude: 경도
            category: 카테고리
            radius: 반경(미터)
            
        Returns:
            매장 검색 결과
        """
        if not self.client:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다.")
        
        result = await self.client.call_tool(
            "search_nearby_stores",
            {
                "latitude": latitude,
                "longitude": longitude,
                "category": category
            }
        )
        
        # MCP Tool 결과는 content 리스트로 반환됨
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                # JSON 문자열을 파싱
                return json.loads(content.text)
        
        return {"stores": [], "total_count": 0}
    
    async def search_fnb_with_reviews(
        self,
        latitude: float,
        longitude: float,
        category: str = "음식점",
        radius: int = 1000,
        max_stores: int = 10,
        reviews_per_store: int = 5
    ) -> Dict[str, Any]:
        """
        F&B 매장 검색 (리뷰 포함)
        
        Args:
            latitude: 위도
            longitude: 경도
            category: 카테고리
            radius: 반경(미터)
            max_stores: 최대 매장 수
            reviews_per_store: 매장당 리뷰 수
            
        Returns:
            매장 + 리뷰 검색 결과
        """
        if not self.client:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다.")
        
        result = await self.client.call_tool(
            "search_fnb_with_reviews",
            {
                "latitude": latitude,
                "longitude": longitude,
                "category": category,
                "radius": radius,
                "max_stores": max_stores,
                "reviews_per_store": reviews_per_store
            }
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        return {"stores": [], "total_stores": 0}


class DiscountMCPClient:
    """Discount_MAP_server MCP 클라이언트"""
    
    def __init__(self, server_path: str = "/opt/conda/envs/team/OSS/mcp-server/Discount_MAP_server/discount_server.py"):
        self.server_path = server_path
        self.client: Optional[MCPClient] = None
    
    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        self.client = MCPClient(self.server_path, "Discount_MAP_server")
        await self.client.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self.client:
            await self.client.close()
    
    async def get_discounts_for_stores(
        self,
        user_profile: Dict[str, Any],
        stores: List[str]
    ) -> Dict[str, Any]:
        """
        매장별 할인 정보 조회
        
        Args:
            user_profile: 사용자 프로필
                {
                    "userId": "user123",
                    "telco": "SKT",
                    "memberships": ["CJ ONE"],
                    "cards": ["신한카드"],
                    "affiliations": []
                }
            stores: 매장명 리스트
                ["스타벅스 동국대점", "이디야커피 충무로역점"]
                
        Returns:
            할인 정보 결과
        """
        if not self.client:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다.")
        
        result = await self.client.call_tool(
            "get_discounts_for_stores",
            {
                "userProfile": user_profile,
                "stores": stores
            }
        )
        
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)
        
        return {
            "success": False,
            "message": "할인 정보 조회 실패",
            "results": []
        }


# ============================================
# 간편 사용 함수들
# ============================================

async def search_nearby_stores(
    latitude: float,
    longitude: float,
    category: str = "음식점",
    radius: int = 1000
) -> Dict[str, Any]:
    """Location_server를 통해 근처 매장 검색 (간편 함수)"""
    async with LocationMCPClient() as client:
        return await client.search_nearby_stores(latitude, longitude, category, radius)


async def get_discounts_for_stores(
    user_profile: Dict[str, Any],
    stores: List[str]
) -> Dict[str, Any]:
    """Discount_MAP_server를 통해 할인 정보 조회 (간편 함수)"""
    async with DiscountMCPClient() as client:
        return await client.get_discounts_for_stores(user_profile, stores)


# ============================================
# 테스트 코드
# ============================================

async def test_location_client():
    """Location MCP Client 테스트"""
    print("\n" + "="*60)
    print("🧪 Location MCP Client 테스트")
    print("="*60)
    
    try:
        async with LocationMCPClient() as client:
            # 도구 목록 확인
            tools = await client.client.list_tools()
            print(f"\n사용 가능한 도구: {len(tools)}개")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # 매장 검색
            result = await client.search_nearby_stores(
                latitude=37.5582,
                longitude=126.9983,
                category="카페"
            )
            
            print(f"\n검색 결과:")
            print(f"  총 매장 수: {result.get('total_count', 0)}")
            if result.get('stores'):
                print(f"  첫 번째 매장: {result['stores'][0].get('name')}")
            
            return result
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_discount_client():
    """Discount MCP Client 테스트"""
    print("\n" + "="*60)
    print("🧪 Discount MCP Client 테스트")
    print("="*60)
    
    try:
        async with DiscountMCPClient() as client:
            # 도구 목록 확인
            tools = await client.client.list_tools()
            print(f"\n사용 가능한 도구: {len(tools)}개")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # 할인 정보 조회
            result = await client.get_discounts_for_stores(
                user_profile={
                    "userId": "test_user",
                    "telco": "SKT",
                    "memberships": ["CJ ONE"],
                    "cards": ["신한카드"],
                    "affiliations": []
                },
                stores=["스타벅스 동국대점", "이디야커피 충무로역점"]
            )
            
            print(f"\n할인 조회 결과:")
            print(f"  성공: {result.get('success')}")
            print(f"  총 매장: {result.get('total', 0)}")
            if result.get('results'):
                print(f"  첫 번째 매장: {result['results'][0].get('inputStoreName')}")
            
            return result
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_integration():
    """통합 테스트: Location → Discount"""
    print("\n" + "="*60)
    print("🧪 통합 테스트: Location → Discount")
    print("="*60)
    
    try:
        # 1. 위치 기반 매장 검색
        print("\n1️⃣ 근처 매장 검색...")
        location_result = await search_nearby_stores(
            latitude=37.5582,
            longitude=126.9983,
            category="카페"
        )
        
        stores = location_result.get('stores', [])
        store_names = [store.get('name') for store in stores if store.get('name')]
        
        print(f"   ✅ {len(store_names)}개 매장 발견")
        for name in store_names[:3]:
            print(f"      - {name}")
        
        if not store_names:
            print("   ⚠️  검색된 매장 없음")
            return
        
        # 2. 할인 정보 조회
        print("\n2️⃣ 할인 정보 조회...")
        discount_result = await get_discounts_for_stores(
            user_profile={
                "userId": "test_user",
                "telco": "SKT",
                "memberships": ["CJ ONE"],
                "cards": ["신한카드 YOLO Tasty"],
                "affiliations": []
            },
            stores=store_names
        )
        
        print(f"   ✅ 할인 조회 완료")
        print(f"   성공: {discount_result.get('success')}")
        print(f"   결과 수: {len(discount_result.get('results', []))}")
        
        return {
            "location": location_result,
            "discount": discount_result
        }
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """메인 테스트 함수"""
    print("\n🚀 MCP Client 테스트 시작\n")
    
    # 1. Location Client 테스트
    await test_location_client()
    
    # 2. Discount Client 테스트
    await test_discount_client()
    
    # 3. 통합 테스트
    await test_integration()
    
    print("\n✅ 모든 테스트 완료\n")


if __name__ == "__main__":
    asyncio.run(main())












