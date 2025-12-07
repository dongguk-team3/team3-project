# etl/run_etl.py

"""
ETL 엔트리포인트

1) 각 제휴사 크롤러를 돌려서 raw JSON/HTML 파싱 결과 수집
2) LLMNormalizer로 정규화 (discount_program 중심 JSON 구조)
3) DiscountDBLoader로 PostgreSQL discountdb에 upsert

실행 방법:
    cd /opt/conda/envs/team/OSS/mcp-server/Discount_MAP_server
    python -m etl.run_etl
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from datetime import date, datetime 

# 크롤러들
from etl.crawlers.happypoint_crawler import fetch_happypoint_brands
from etl.crawlers.kt_crawler import fetch_kt_partners_all
from etl.crawlers.skt_crawler import fetch_skt_eat_benefits
from etl.crawlers.lguplus_crawler import fetch_lguplus_membership_for_targets
from etl.crawlers.lpoint_crawler import fetch_lpoint_fnb_affiliates
from etl.crawlers.cjone_crawler import fetch_cjone_partners
from etl.crawlers.bccard_crawler import fetch_bliss7_vip_services
from etl.crawlers.hyundaicard_crawler import fetch_hyundaicard_mpoints

# LLM 정규화 + DB 로더
from etl.llm_normalizer import LLMNormalizer
from etl.db_loader import DiscountDBLoader

# DB 커넥션 풀
from db.connection import init_db_pool, close_db_pool

# 프로젝트 루트 (/Discount_MAP_server)
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

MERCHANT_DISCOUNT_JSON_PATH = os.getenv(
    "MERCHANT_DISCOUNT_JSON_PATH",
    os.path.join(ROOT_DIR, "db", "merchant_discount", "merchant_discount.json"),
)


# ---------------------------------------------------
# 1. 원본(raw) 수집
# ---------------------------------------------------
async def collect_raw_from_sources() -> Dict[str, Any]:
    """
    모든 제휴사 크롤러를 호출해서 raw 데이터를 모아온다.

    반환 예:
    {
      "happypoint": {...},
      "kt": [...],
      "skt": [...],
      "lguplus": {...},
      "lpoint": {...},
      "cjone": [...],
      "bccard": [...],
      "hyundaicard": {...},
    }
    """

    # 1) 비동기 크롤러들 한 번에 병렬 실행
    async_results = await asyncio.gather(
        fetch_happypoint_brands(),                # happypoint
        fetch_kt_partners_all("C21"),             # KT 멤버십 (외식/푸드 카테고리 코드 예시)
        fetch_skt_eat_benefits(),                 # SKT 멤버십 EAT 카테고리
        fetch_lguplus_membership_for_targets(),   # LG U+ VIP 콕 주요 제휴사
        fetch_lpoint_fnb_affiliates(),            # L.POINT 외식 사용처
        fetch_cjone_partners(),                   # CJ ONE 외식 카테고리
        fetch_bliss7_vip_services(),              # BC카드 BLISS.7 VIP 서비스 (async 버전)
        return_exceptions=True,
    )

    (
        hp_raw,
        kt_raw,
        skt_raw,
        lgu_raw,
        lp_raw,
        cj_raw,
        bc_raw,
    ) = async_results

    def _unwrap(result: Any, source_name: str) -> Optional[Any]:
        if isinstance(result, Exception):
            print(f"[ETL] ⚠ {source_name} 크롤링 중 예외 발생: {result}")
            return None
        return result

    hp_raw = _unwrap(hp_raw, "happypoint")
    kt_raw = _unwrap(kt_raw, "kt")
    skt_raw = _unwrap(skt_raw, "skt")
    lgu_raw = _unwrap(lgu_raw, "lguplus")
    lp_raw = _unwrap(lp_raw, "lpoint")
    cj_raw = _unwrap(cj_raw, "cjone")
    bc_raw = _unwrap(bc_raw, "bccard")

    # 2) 동기 크롤러 (현대카드) – 그냥 호출해도 됨 (curl_cffi 기반)
    print("[ETL] 동기 크롤러 호출 시작... (hyundaicard)")
    try:
        hy_raw = fetch_hyundaicard_mpoints()
    except Exception as e:  # noqa: BLE001
        print(f"[ETL] ⚠ hyundaicard 크롤링 중 예외 발생: {e}")
        hy_raw = None

    return {
        "happypoint": hp_raw,
        "kt": kt_raw,
        "skt": skt_raw,
        "lguplus": lgu_raw,
        "lpoint": lp_raw,
        "cjone": cj_raw,
        "bccard": bc_raw,
        "hyundaicard": hy_raw,
    }

def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _to_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        # "2025-04-07", "2025-04-07T00:00:00" 둘 다 대응
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            print(f"[ETL] ⚠ 날짜 파싱 실패: {value!r}")
            return None

    return None



def load_merchant_discount_programs() -> Dict[str, List[Dict[str, Any]]]:
    """
    db/merchant_discount/merchant_discount.json 을 읽어서
    DiscountDBLoader에 바로 넘길 수 있는 형태로 리턴.

    반환 예:
        { "merchant_discount": [ {...}, {...}, ... ] }
    """
    path = MERCHANT_DISCOUNT_JSON_PATH

    if not os.path.exists(path):
        print(f"[ETL] merchant_discount.json({path})이 없어 스킵합니다.")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ETL] ⚠ merchant_discount.json 로딩 중 예외 발생: {e}")
        return {}

    if not isinstance(data, list):
        print("[ETL] ⚠ merchant_discount.json 최상위 구조가 list가 아니라서 스킵합니다.")
        return {}

    normalized: List[Dict[str, Any]] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        # 원본 보존 위해 얕은 복사
        p = dict(item)

        # 숫자/문자열 타입 통일
        p["discountAmount"] = _to_float(p.get("discountAmount"))
        p["maxAmount"] = _to_float(p.get("maxAmount"))
        p["maxUsageCnt"] = _to_int(p.get("maxUsageCnt"))
        p["dowMask"] = _to_int(p.get("dowMask"))

        # ✅ 날짜 문자열 → datetime.date 로 변환
        p["validFrom"] = _to_date(p.get("validFrom"))
        p["validTo"] = _to_date(p.get("validTo"))

        normalized.append(p)

    print(f"[ETL] merchant_discount.json 에서 {len(normalized)}건 로드했습니다.")
    return {"merchant_discount": normalized}


# ---------------------------------------------------
# 2. 메인 실행 흐름
# ---------------------------------------------------
async def main() -> None:
    print("[ETL] DB 커넥션 풀 초기화...")
    await init_db_pool()

    try:
        # 1) RAW 수집
        print("[ETL] 비동기 크롤러 호출 시작...")
        raw_by_source = await collect_raw_from_sources()
        print("[ETL] 비동기 크롤러 호출 완료.")

        # 2) LLM 정규화 준비
        print("[ETL] LLM 정규화 시작...")
        normalizer = LLMNormalizer()       # 내부에서 OPENAI_API_KEY 사용
        normalized_all: Dict[str, List[Dict[str, Any]]] = {}

        for source, raw in raw_by_source.items():
            if raw is None:
                print(f"[ETL] {source}: raw 데이터가 없어 스킵합니다.")
                continue

            try:
                # LLMNormalizer.normalize(source, raw) 라고 가정
                programs = await normalizer.normalize(source=source, raw=raw)
                normalized_all[source] = programs
                print(f"[ETL] {source}: 정규화 완료 ({len(programs)} 건)")
            except Exception as e:
                
                print(f"[ETL] ⚠ {source} 정규화 중 예외 발생: {e}")

        # ✅ 여기서 merchant_discount.json 끼워 넣기
        merchant_sources = load_merchant_discount_programs()
        for source, programs in merchant_sources.items():
            if not programs:
                continue

            existing = normalized_all.get(source, [])
            normalized_all[source] = (existing or []) + programs
            print(f"[ETL] {source}: merchant_discount.json에서 {len(programs)}건 병합 완료.")

        try:
            with open("normalized_all.json", "w", encoding="utf-8") as f:
                json.dump(normalized_all, f, ensure_ascii=False, indent=2, default=str)
            print("[ETL] 정규화 전체 결과를 normalized_all.json 파일로 저장했습니다.")
        except Exception as e:
            print(f"[ETL] ⚠ normalized_all.json 저장 중 오류 발생: {e}")

        # 3) DB 적재
        print("[ETL] DB 적재 시작...")
        loader = DiscountDBLoader()

        for source, programs in normalized_all.items():
            if not programs:
                print(f"[ETL] {source}: 정규화된 프로그램이 없어 스킵합니다.")
                continue

            try:
                result = await loader.load_discounts(programs)
                print(f"[ETL] {source}: DB 적재 완료 (성공 {result['success']} / 실패 {result['failed']})")
                if result["errors"]:
                    for msg in result["errors"]:
                        print(f"[ETL]   - {msg}")
            except Exception as e:  # noqa: BLE001
                print(f"[ETL] ⚠ {source} DB 적재 중 예외 발생: {e}")

        print("[ETL] DB 적재 완료.")

    finally:
        print("[ETL] DB 커넥션 풀 종료...")
        await close_db_pool()
        print("[ETL] 종료 완료.")


if __name__ == "__main__":
    asyncio.run(main())
