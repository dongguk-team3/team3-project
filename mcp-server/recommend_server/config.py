"""
환경 설정
"""
import os

# PostgreSQL Database Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/discount_map"
)

# 기본 주문 금액 (사용자가 금액을 지정하지 않았을 때)
DEFAULT_ORDER_AMOUNT = 15000

# 서버 설정
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

