"""
PostgreSQL 연결을 관리하는 모듈.

역할:
- 애플리케이션 시작 시 asyncpg 커넥션 풀(pool)을 한 번만 만들어 둔다.
- 다른 모듈에서 간단히 fetch()/fetchrow()/execute()로 쿼리만 날리면 되게 도와준다.

주의:
- 이 모듈 자체는 아무 쿼리도 알지 못한다. 오직 "연결"만 관리한다.
"""

import os
from typing import Optional, Any, List

import asyncpg

try:
    # .env 파일에서 자동으로 DB_USER 등 불러오기
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# 전역 커넥션 풀 객체 (초기에는 None)
_pool: Optional[asyncpg.Pool] = None


def _get_db_config() -> dict:
    """
    환경변수에서 DB 접속 정보를 읽는다.
    없으면 기본값 사용.
    """
    return {
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
        "database": os.getenv("DB_NAME", "discountdb"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "min_size": int(os.getenv("DB_POOL_MIN", "1")),
        "max_size": int(os.getenv("DB_POOL_MAX", "5")),
    }


async def init_db_pool() -> None:
    """
    서버 시작 시 한 번만 호출해서 커넥션 풀을 만든다.
    이미 만들어졌다면 아무 것도 안 함.
    """
    global _pool
    if _pool is not None:
        return

    cfg = _get_db_config()
    _pool = await asyncpg.create_pool(
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        host=cfg["host"],
        port=cfg["port"],
        min_size=cfg["min_size"],
        max_size=cfg["max_size"],
    )
    print(f"[DB] 커넥션 풀 초기화 완료: {cfg['host']}:{cfg['port']}/{cfg['database']}")


async def close_db_pool() -> None:
    """
    서버 종료 시 커넥션 풀을 닫는다.
    (꼭 필수는 아니지만, 정석적인 마무리)
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        

async def fetch(query: str, *args: Any) -> List[asyncpg.Record]:
    """
    여러 행을 가져오는 SELECT 쿼리용.
    예) rows = await fetch("SELECT * FROM brand WHERE brand_name=$1", "스타벅스")
    """
    if _pool is None:
        raise RuntimeError("DB 커넥션 풀이 없습니다. init_db_pool()을 먼저 호출해야 합니다.")
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> Optional[asyncpg.Record]:
    """
    한 행만 가져오는 SELECT 쿼리용.
    없으면 None 리턴.
    """
    if _pool is None:
        raise RuntimeError("DB 커넥션 풀이 없습니다. init_db_pool()을 먼저 호출해야 합니다.")
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute(query: str, *args: Any) -> str:
    """
    INSERT / UPDATE / DELETE 등 결과 행이 필요 없는 쿼리용.
    반환값은 asyncpg가 주는 상태 문자열 (예: 'INSERT 0 1')
    """
    if _pool is None:
        raise RuntimeError("DB 커넥션 풀이 없습니다. init_db_pool()을 먼저 호출해야 합니다.")
    async with _pool.acquire() as conn:
        return await conn.execute(query, *args)


def is_db_pool_initialized() -> bool:
    """
    현재 커넥션 풀이 초기화되어 있는지 여부.
    - True  : 이미 init_db_pool()이 한 번이라도 호출됨
    - False : 아직 아무도 풀을 만든 적 없음
    """
    return _pool is not None