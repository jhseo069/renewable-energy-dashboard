"""
국회 오픈 API 연동 스크립트 — 해상풍력 관련 법안 추적
========================================================
Layer 3 (Execution) — 결정론적 Python 스크립트

현재 상태: API 키 미보유 → Mock 데이터로 선행 개발 완료
전환 방법: .env에 ASSEMBLY_API_KEY=<발급받은 키> 설정 시 자동으로 실서버 전환

API 발급처: https://open.assembly.go.kr/portal/main.do (무료, 최대 1,000건/일)
API 엔드포인트: https://open.assembly.go.kr/portal/openapi/TVBPMBILL11
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── 국회 API 설정 ──────────────────────────────────────────────────────
# os.getenv 사용 이유: .env에 키를 넣으면 코드 변경 없이 실서버 전환 가능
ASSEMBLY_API_KEY = os.getenv("ASSEMBLY_API_KEY", "")
ASSEMBLY_API_BASE = "https://open.assembly.go.kr/portal/openapi"


def _get_api_key() -> str:
    """ASSEMBLY_API_KEY: os.getenv 우선, 실패 시 st.secrets 폴백."""
    key = ASSEMBLY_API_KEY
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("ASSEMBLY_API_KEY", "")
        except Exception:
            pass
    return key

# 추적 대상 법안 검색 키워드 — API SEARCH_WORD 파라미터로 사용
# 신재생에너지 사업개발(인허가·정책·기술기준) 직접 관련 법안만 모니터링
BILL_KEYWORDS = [
    # ── 에너지·발전 직접 관련 ──────────────────────────────────────────
    "신재생에너지",       # 신재생에너지법 전반
    "재생에너지",         # 재생에너지 관련 특별법
    "해상풍력",           # 해상풍력발전 특별법·지원법
    "육상풍력",           # 육상풍력 입지 관련
    "태양광",             # 태양광 발전 관련
    "집적화단지",         # 해상풍력 집적화단지 조성
    "분산에너지",         # 분산에너지 활성화 특별법
    "전기사업법",         # 발전사업허가·전력시장 기반법
    "계획입지",           # 재생에너지 계획입지 제도
    "에너지저장장치",     # ESS 관련 법제
    "발전사업",           # 발전사업허가 관련 법안
    "RPS",               # 신재생에너지 공급의무화
    "재생에너지공급",     # 재생에너지 공급 인증서
    # ── 토지·입지 인허가 (육상·해상 공통) ────────────────────────────
    "농지법",             # 태양광·풍력 농지전용 허가
    "산지관리법",         # 육상풍력 산지전용·산림형질변경
    "공유수면",           # 해상풍력 공유수면 점용·사용 허가
    "국토계획",           # 국토의 계획 및 이용에 관한 법률(국계법)
    "개발행위허가",       # 발전시설 개발행위 허가
    "도시계획",           # 발전시설 용도지역 변경
    "용도지역",           # 발전부지 용도지역 관련
    # ── 환경·생태 인허가 ─────────────────────────────────────────────
    "환경영향평가",       # 발전단지 환경영향평가
    "생태계보전",         # 생태계보전부담금·자연환경보전
    "자연환경보전",       # 자연환경보전법 관련
    "소음진동",           # 풍력터빈 소음 기준
    # ── 기후·정책 거시 환경 ─────────────────────────────────────────
    "탄소중립",           # 탄소중립기본법·2050 탄소중립
    "기후위기",           # 기후위기 대응 관련 법안
    "온실가스",           # 온실가스 감축 의무화
    "에너지전환",         # 에너지전환 정책 관련
    "탄소배출권",         # 배출권거래제 관련
    # ── 어업·주민수용성 (해상풍력 핵심) ─────────────────────────────
    "어업인",             # 해상풍력 어업인 협의·보상
    "수산업법",           # 어업권 보상 관련
    "주민수용성",         # 발전사업 주민 동의·이익공유
    "이익공유",           # 재생에너지 주민 이익공유제
]

# 허용 소관위원회 — 신재생사업개발과 직접 관련 있는 위원회만 수집
# 부분 문자열 매칭으로 위원회명 변경에 유연하게 대응
ALLOWED_COMMITTEES = [
    "산업통상자원",   # 산업통상자원중소벤처기업위원회
    "농림축산",       # 농림축산식품해양수산위원회
    "기후에너지",     # 기후에너지환경노동위원회
    "기후위기",       # 기후위기특별위원회
    "탄소중립",       # 탄소중립기후위기특별위원회
    "환경노동",       # 환경노동위원회 (환경영향평가 등)
]

# 법안 제목 키워드 필터 — 위원회 필터 통과 후 2차 필터로 사용
# 위원회는 신재생 이외에도 많은 법안을 다루므로 제목에 아래 키워드 중
# 하나라도 포함된 법안만 최종 수집 (경제자유구역·조선·중소기업 등 무관 법안 차단)
TITLE_KEYWORDS = frozenset([
    # 에너지·발전 직접 관련
    "신재생에너지", "재생에너지", "해상풍력", "육상풍력", "풍력", "태양광", "태양에너지",
    "집적화단지", "분산에너지", "전기사업", "발전사업", "발전소",
    "에너지저장", "계획입지", "RPS", "REC",
    # 수소
    "수소에너지", "수소경제", "수소발전",
    # 해상풍력 인허가 핵심 (공유수면은 해상풍력과 직결)
    "공유수면",
    # 환경 인허가 — 발전단지 환경영향평가
    "환경영향평가",
    # 기후·정책 거시 환경
    "탄소중립", "기후위기", "온실가스", "에너지전환", "탄소배출권",
    # 어업·주민수용성 (해상풍력 핵심) — "어업인"만으로는 농어업인 관련 법안이 혼입되므로 구체화
    "어업인 보상", "어업인 협의", "어업피해", "주민수용성", "이익공유",
])

# 법안 처리 상태 코드 → 한국어 매핑
# 국회 API의 PROC_RESULT_CD 값이 숫자 코드라 그대로 쓰면 가독성이 떨어짐
BILL_STATUS_MAP = {
    "원안가결": "원안가결",
    "수정가결": "수정가결",
    "부결": "부결",
    "대안반영폐기": "대안반영폐기",
    "임기만료폐기": "임기만료폐기",
    "": "심사중",  # 빈값이면 아직 처리 안 된 것
}


def _make_mock_bills() -> list[dict]:
    """
    API 키 없을 때 반환할 Mock 법안 데이터.
    실제 발의됐거나 예상되는 법안 형태로 작성 — 개발·테스트 목적.
    is_mock=True 로 마킹해 UI에서 '[API 연동 전]' 배지 표시 가능.
    """
    return [
        {
            "bill_id": "MOCK-2026-001",
            "title": "해상풍력발전 지원 및 집적화단지 조성에 관한 특별법안",
            "proposer": "김○○ 의원 외 12인",
            "committee": "산업통상자원중소벤처기업위원회",
            "status": "소위심사",
            "propose_date": "2026-01-15",
            "link": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_MOCK001",
            "is_mock": True,
        },
        {
            "bill_id": "MOCK-2026-002",
            "title": "신재생에너지 계획입지 제도 도입을 위한 전기사업법 일부개정법률안",
            "proposer": "정부 제출",
            "committee": "산업통상자원중소벤처기업위원회",
            "status": "본회의 부의",
            "propose_date": "2026-02-10",
            "link": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_MOCK002",
            "is_mock": True,
        },
        {
            "bill_id": "MOCK-2026-003",
            "title": "분산에너지 활성화 특별법 일부개정법률안",
            "proposer": "이○○ 의원 외 8인",
            "committee": "산업통상자원중소벤처기업위원회",
            "status": "심사중",
            "propose_date": "2026-02-25",
            "link": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_MOCK003",
            "is_mock": True,
        },
        {
            "bill_id": "MOCK-2026-004",
            "title": "해상풍력 어업인 협의·보상 절차 간소화를 위한 공유수면 관리 및 매립에 관한 법률 일부개정법률안",
            "proposer": "박○○ 의원 외 5인",
            "committee": "농림축산식품해양수산위원회",
            "status": "심사중",
            "propose_date": "2026-03-01",
            "link": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_MOCK004",
            "is_mock": True,
        },
    ]


def _fetch_raw_page(page_index: int, api_key: str) -> tuple[list[dict], int]:
    """
    국회 API 단일 페이지 원시 행(row) 목록과 전체 건수를 반환.

    주의: SEARCH_WORD 파라미터는 법안명 검색을 하지 않음 (실측 확인).
    해당 파라미터 사용 시 '신재생에너지' 검색어에도 전체 법안이 반환되며
    1페이지 결과가 건강보험법·약사법 등 무관 법안으로 채워짐 → 사용 안 함.

    Returns:
        (rows, total_count) — rows: 행 목록, total_count: 전체 건수(헤더 기준)
    """
    response = requests.get(
        f"{ASSEMBLY_API_BASE}/TVBPMBILL11",
        params={
            "KEY":    api_key,
            "Type":   "json",
            "pIndex": page_index,
            "pSize":  100,
            "AGE":    22,   # 제22대 국회 (2024.05.30~) 고정
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    # API 레벨 에러 감지 (인증 오류, 파라미터 오류 등)
    # 정상 응답: {"TVBPMBILL11": [...]} / 에러: {"RESULT": {...}}
    if "RESULT" in data and "TVBPMBILL11" not in data:
        result = data["RESULT"]
        code = result.get("CODE", "")
        msg  = result.get("MESSAGE", "")
        print(f"[국회 API] 에러 응답 (코드: {code}): {msg}")
        return [], 0

    api_section = data.get("TVBPMBILL11", [])

    # 헤더(api_section[0])에서 전체 건수 추출
    # 응답 구조: [{"head": [{"list_total_count": "16878"}, {"RESULT": {...}}]}, {"row": [...]}]
    total_count = 0
    if api_section:
        head_list = api_section[0].get("head", [])
        if head_list:
            total_count = int(head_list[0].get("list_total_count", 0))

    rows = api_section[1].get("row", []) if len(api_section) > 1 else []
    return rows, total_count


def _normalize_propose_date(raw: str) -> str:
    """PROPOSE_DT 원시값을 YYYY-MM-DD 형식으로 정규화.
    국회 API는 YYYYMMDD 또는 YYYY.MM.DD 형식으로 반환하는 경우가 있음."""
    if not raw:
        return raw
    # YYYYMMDD (하이픈 없음)
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    # YYYY.MM.DD
    if len(raw) == 10 and raw[4] == "." and raw[7] == ".":
        return raw.replace(".", "-")
    return raw


def fetch_all_bills() -> list[dict]:
    """
    국회 오픈 API에서 최신 법안을 페이지별로 수집하고 제목 키워드로 필터링.

    API 키가 없거나 오류 발생 시 Mock 데이터를 자동 반환합니다.

    설계 변경 이력:
    - 2026-03-09: SEARCH_WORD 제거, 페이지 루프로 전환, LINK_URL 필드 수정
    - 2026-04-17: 마지막 N페이지 스캔으로 수정 (Bug fix)
      국회 API는 오름차순(오래된 법안 먼저) 반환 — pages 1~10은 2024년 5~6월 법안만 포함.
      전체 건수를 먼저 조회한 뒤 마지막 MAX_PAGES 페이지를 스캔해야 최신 법안 수집 가능.

    Returns:
        [{bill_id, title, proposer, committee, status,
          propose_date, link, is_mock}, ...]
    """
    api_key = _get_api_key()
    if not api_key:
        print("[국회 API] ASSEMBLY_API_KEY 미설정 → Mock 데이터 반환")
        return _make_mock_bills()

    try:
        PAGE_SIZE = 100
        MAX_PAGES = 10  # 최대 스캔 페이지 수 (1000건)

        # 1단계: 1페이지 호출로 전체 건수 파악
        first_rows, total_count = _fetch_raw_page(1, api_key)
        if total_count == 0 and not first_rows:
            print("[국회 API] 전체 건수 0 → Mock 반환")
            return _make_mock_bills()

        # 전체 페이지 수 계산 후 마지막 MAX_PAGES 페이지 범위 결정
        # 예: 총 16,900건 → 169페이지, start_page=160
        total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
        start_page  = max(1, total_pages - MAX_PAGES + 1)
        print(f"[국회 API] 전체 {total_count}건 ({total_pages}페이지) — pages {start_page}~{total_pages} 스캔")

        seen_bill_ids: set[str] = set()
        all_bills: list[dict] = []

        def _process_rows(rows: list[dict]) -> None:
            for row in rows:
                title = row.get("BILL_NAME", "") or ""
                if not any(kw in title for kw in TITLE_KEYWORDS):
                    continue
                bill_id = row.get("BILL_ID", "")
                if bill_id in seen_bill_ids:
                    continue
                seen_bill_ids.add(bill_id)
                raw_status = row.get("PROC_RESULT_CD", "")
                all_bills.append({
                    "bill_id":      bill_id,
                    "title":        title,
                    "proposer":     row.get("PROPOSER", ""),
                    "committee":    row.get("CURR_COMMITTEE") or "",
                    "status":       BILL_STATUS_MAP.get(raw_status, raw_status or "심사중"),
                    "propose_date": _normalize_propose_date(row.get("PROPOSE_DT", "")),
                    "link":         row.get("LINK_URL", ""),
                    "is_mock":      False,
                })

        # 1페이지 결과 처리
        _process_rows(first_rows)

        # start_page가 1이면 이미 처리했으므로 2페이지부터, 아니면 start_page부터
        scan_start = max(2, start_page) if start_page == 1 else start_page
        for page in range(scan_start, total_pages + 1):
            rows, _ = _fetch_raw_page(page, api_key)
            if not rows:
                break
            _process_rows(rows)

        if not all_bills:
            print(f"[국회 API] 스캔 완료 — 필터 통과 법안 0건 → Mock 반환")
            return _make_mock_bills()

        # 발의일 기준 최신순 정렬
        all_bills.sort(key=lambda x: x.get("propose_date", ""), reverse=True)
        print(f"[국회 API] 수집 완료: {len(all_bills)}건")
        return all_bills

    except Exception as e:
        print(f"[국회 API] 수집 실패: {e} → Mock 데이터 반환")
        return _make_mock_bills()


# ── 단독 실행 시 테스트 ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("국회 법안 수집 테스트 (ASSEMBLY_API_KEY 미설정 시 Mock 반환)")
    print("=" * 60)

    bills = fetch_all_bills()
    print(f"\n수집된 법안 수: {len(bills)}건\n")

    for i, bill in enumerate(bills, 1):
        mock_mark = " [MOCK]" if bill["is_mock"] else ""
        print(f"[{i}] {bill['propose_date']} | {bill['committee']}{mock_mark}")
        print(f"     법안명: {bill['title'][:60]}...")
        print(f"     발의자: {bill['proposer']} | 상태: {bill['status']}")
        print()
