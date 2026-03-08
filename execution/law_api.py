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


def fetch_assembly_bills(keyword: str = "해상풍력") -> list[dict]:
    """
    국회 오픈 API로 키워드 관련 법안을 검색합니다.
    API 키가 없거나 오류 발생 시 Mock 데이터를 자동 반환합니다.

    Args:
        keyword: 검색 키워드 (기본값: '해상풍력')

    Returns:
        [{bill_id, title, proposer, committee, status,
          propose_date, link, is_mock}, ...]
    """
    # API 키가 없으면 즉시 Mock 반환 — 키 없이 API 호출하면 오류만 나므로 조기 차단
    if not ASSEMBLY_API_KEY:
        print(f"[국회 API] ASSEMBLY_API_KEY 미설정 → Mock 데이터 반환 (키워드: {keyword})")
        return _make_mock_bills()

    try:
        # 국회 오픈 API: 법률안 목록 조회 (TVBPMBILL11)
        # AGE=22: 제22대 국회 (2024.05.30~) 법안만 조회
        # pIndex: 페이지 번호 (1부터 시작), pSize: 페이지당 결과 수 (최대 100)
        response = requests.get(
            f"{ASSEMBLY_API_BASE}/TVBPMBILL11",
            params={
                "KEY":         ASSEMBLY_API_KEY,
                "Type":        "json",
                "pIndex":      1,
                "pSize":       100,
                "AGE":         22,          # 제22대 국회 고정
                "SEARCH_WORD": keyword,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        # API 최상위 RESULT 키 감지 — 인증 오류, 파라미터 오류 등 API 레벨 에러
        # 정상 응답은 {"TVBPMBILL11": [...]} 구조이며, 에러는 {"RESULT": {...}} 구조
        if "RESULT" in data and "TVBPMBILL11" not in data:
            result = data["RESULT"]
            code = result.get("CODE", "")
            msg  = result.get("MESSAGE", "")
            print(f"[국회 API] 에러 응답 (코드: {code}): {msg} → Mock 데이터 반환")
            return _make_mock_bills()

        # 국회 API 응답 구조: {"TVBPMBILL11": [{"head": [...]}, {"row": [...]}]}
        # 두 번째 요소의 "row" 키가 실제 법안 목록
        api_section = data.get("TVBPMBILL11", [])
        rows = api_section[1].get("row", []) if len(api_section) > 1 else []

        bills: list[dict] = []
        for row in rows:
            committee = row.get("CURR_COMMITTEE", "")

            # 소관위원회 필터 — ALLOWED_COMMITTEES 목록의 키워드를 하나라도 포함해야 통과
            # 위원회명이 완전 일치하지 않아도 부분 포함으로 유연하게 매칭
            if not any(kw in committee for kw in ALLOWED_COMMITTEES):
                continue

            raw_status = row.get("PROC_RESULT_CD", "")
            bills.append({
                "bill_id":      row.get("BILL_ID", ""),
                "title":        row.get("BILL_NAME", ""),
                "proposer":     row.get("PROPOSER", ""),
                "committee":    committee,
                # 상태 코드를 읽기 쉬운 한국어로 변환
                "status":       BILL_STATUS_MAP.get(raw_status, raw_status or "심사중"),
                "propose_date": row.get("PROPOSE_DT", ""),
                "link":         row.get("DETAIL_LINK", ""),
                "is_mock":      False,
            })

        return bills

    except Exception as e:
        # 네트워크 오류, API 스펙 변경 등 예외 상황 → Mock으로 graceful 처리
        print(f"[국회 API] 수집 실패: {e} → Mock 데이터 반환")
        return _make_mock_bills()


def fetch_all_bills() -> list[dict]:
    """
    BILL_KEYWORDS에 등록된 모든 키워드로 법안을 수집하고 중복 제거 후 반환.
    키워드가 여러 개이므로 같은 법안이 중복 수집될 수 있어 bill_id로 중복 제거.
    """
    seen_bill_ids: set[str] = set()
    all_bills: list[dict] = []

    for keyword in BILL_KEYWORDS:
        bills = fetch_assembly_bills(keyword=keyword)
        for bill in bills:
            bill_id = bill["bill_id"]
            # Mock 데이터는 bill_id가 고정이므로 첫 번째만 포함
            if bill_id not in seen_bill_ids:
                seen_bill_ids.add(bill_id)
                all_bills.append(bill)

    # 발의일 기준 최신순 정렬
    all_bills.sort(key=lambda x: x.get("propose_date", ""), reverse=True)
    return all_bills


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
