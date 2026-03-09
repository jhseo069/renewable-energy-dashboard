"""
유관기관 공지사항 크롤러
========================
Layer 3 (Execution) — 결정론적 Python 스크립트

대상 기관:
  - KPX  (전력거래소)      : SMP·입찰공고·출력제어 공지
  - KEMCO (한국에너지공단) : RPS·REC·보조금 공고
  - KEPCO (한국전력공사)   : 계통 연계·약관·접속 공지

실패 처리 원칙:
  - 403 Forbidden, 타임아웃, HTML 파싱 오류 → 즉시 Mock 반환
  - 재시도 루프 금지 (Cloud 타임아웃 방지)
  - 기관별 독립 try/except (한 기관 실패가 다른 기관에 영향 없음)
"""

import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ── 공통 브라우저 위장 헤더 ────────────────────────────────────────────
# 공공기관 웹서버는 봇 요청을 차단하므로 일반 브라우저와 동일한 헤더 전송
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.google.co.kr/",
    "Connection":      "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── 기관별 크롤링 설정 ────────────────────────────────────────────────
_AGENCY_CONFIG = {
    "kpx": {
        "org":     "KPX (전력거래소)",
        "base":    "https://www.kpx.or.kr",
        # 공지사항 게시판 (정적 HTML 목록)
        "url":     "https://www.kpx.or.kr/www/selectBbsNttList.do?key=102&bbsNo=3",
        "category": "공지사항",
    },
    "kemco": {
        "org":     "한국에너지공단",
        "base":    "https://www.kemco.or.kr",
        # 공공데이터·공지사항 게시판
        "url":     "https://www.kemco.or.kr/web/kem_home_new/info/publicNotice/list.do",
        "category": "공지사항",
    },
    "kepco": {
        "org":     "한전 (KEPCO)",
        "base":    "https://home.kepco.co.kr",
        # 공지사항 게시판
        "url":     "https://home.kepco.co.kr/kepco/KO/ntcf/1/list.do",
        "category": "공지사항",
    },
}

# ── Mock 데이터 ──────────────────────────────────────────────────────
# 크롤링 실패(403, 타임아웃, 파싱 오류) 시 반환할 현실감 있는 샘플 데이터.
# 실제 각 기관에서 발생 가능한 공지 형태로 작성.
_MOCK_NOTICES: dict[str, list[dict]] = {
    "kpx": [
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "2026년 3월 계통한계가격(SMP) 산정 결과 공표",
            "date": "2026-03-05", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "재생에너지 입찰시장 2026년 4월 입찰 일정 공고",
            "date": "2026-03-04", "link": "https://www.kpx.or.kr",
            "category": "입찰공고", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "출력제어 사전통보 절차 개선 시행 안내 (2026.04.01~)",
            "date": "2026-03-01", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "전력시장 운영규칙 일부 개정 공고 (제2026-3호)",
            "date": "2026-02-25", "link": "https://www.kpx.or.kr",
            "category": "규정개정", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "2026년 2월 재생에너지 공급인증서(REC) 거래량 집계 결과",
            "date": "2026-02-20", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
    "kemco": [
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "2026년도 신재생에너지 공급의무화(RPS) 의무공급량 고시 안내",
            "date": "2026-03-06", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "태양광 설비 REC 발급 기준 개정 안내 (2026.04.01 시행)",
            "date": "2026-03-03", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "해상풍력 발전량 인증 신청 접수 (2026년 1분기)",
            "date": "2026-02-28", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "2026년 신재생에너지 설비 보급사업 공모 공고",
            "date": "2026-02-24", "link": "https://www.kemco.or.kr",
            "category": "공모공고", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "ESS 연계 태양광 발전 REC 가중치 변경 설명회 개최 안내",
            "date": "2026-02-18", "link": "https://www.kemco.or.kr",
            "category": "설명회", "is_mock": True,
        },
    ],
    "kepco": [
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "분산형전원 배전망 계통 연계 기술기준 개정 공고",
            "date": "2026-03-04", "link": "https://home.kepco.co.kr",
            "category": "기술기준", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "전기공급약관 시행세칙 제21차 개정 시행 안내",
            "date": "2026-03-01", "link": "https://home.kepco.co.kr",
            "category": "약관개정", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "신재생에너지 발전사업자 계통 접속 신청 2026년 1분기 결과",
            "date": "2026-02-27", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "해상풍력 해저케이블 연계 공사비 분담 기준 개정 안내",
            "date": "2026-02-21", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "345kV 이상 송전망 접속 신청 처리 절차 안내",
            "date": "2026-02-15", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
}


def _parse_date(text: str) -> str:
    """
    다양한 날짜 형식을 YYYY-MM-DD로 표준화.
    파싱 실패 시 today 반환 (최신 순 정렬 유지용).
    """
    text = text.strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y년%m월%d일", "%Y. %m. %d."):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # 파싱 불가 시 오늘 날짜 반환 (위로 올라오도록 최신 처리)
    return datetime.today().strftime("%Y-%m-%d")


def _fetch_kpx_notices() -> list[dict]:
    """
    전력거래소(KPX) 공지사항 크롤링.
    실패(403, 타임아웃, 파싱 오류) 시 Mock 즉시 반환.

    KPX 공지 게시판 HTML 구조:
      <table class="board_list"> → <tbody> → <tr> 행들
      각 행: [번호] [제목(<a>)] [날짜] [작성자] [조회수]
    """
    cfg = _AGENCY_CONFIG["kpx"]
    try:
        resp = requests.get(cfg["url"], headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        notices: list[dict] = []

        # KPX 게시판 테이블: class에 "board" 또는 "list" 포함하는 table 시도
        table = (
            soup.find("table", class_=lambda c: c and "board" in c)
            or soup.find("table", class_=lambda c: c and "list" in c)
            or soup.find("table")
        )
        if not table:
            print("[KPX] 테이블 요소 미발견 → Mock 반환")
            return _MOCK_NOTICES["kpx"]

        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            # 제목은 <a> 태그가 있는 열에서 추출
            title_td = next((td for td in cols if td.find("a")), None)
            if not title_td:
                continue

            a_tag = title_td.find("a")
            title = a_tag.get_text(strip=True)
            href  = a_tag.get("href", "")
            link  = (cfg["base"] + href) if href.startswith("/") else (href or cfg["base"])

            # 날짜: 보통 제목 다음 열 또는 마지막에서 두 번째 열
            date_text = cols[-2].get_text(strip=True) if len(cols) >= 4 else cols[-1].get_text(strip=True)
            date = _parse_date(date_text)

            if title:
                notices.append({
                    "org":      cfg["org"],
                    "org_key":  "kpx",
                    "title":    title,
                    "date":     date,
                    "link":     link,
                    "category": cfg["category"],
                    "is_mock":  False,
                })

        if not notices:
            print("[KPX] 파싱된 공지 0건 → Mock 반환")
            return _MOCK_NOTICES["kpx"]

        print(f"[KPX] 실데이터 수집 완료: {len(notices)}건")
        return notices[:10]  # 최신 10건만

    except Exception as e:
        print(f"[KPX] 수집 실패: {e} → Mock 반환")
        return _MOCK_NOTICES["kpx"]


def _fetch_kemco_notices() -> list[dict]:
    """
    한국에너지공단(KEMCO) 공지사항 크롤링.
    실패 시 Mock 즉시 반환.

    KEMCO 공지 게시판 HTML 구조:
      <table> → <tbody> → <tr> 행들
      각 행: [번호] [분류] [제목(<a>)] [등록일] [조회수]
    """
    cfg = _AGENCY_CONFIG["kemco"]
    try:
        resp = requests.get(cfg["url"], headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        notices: list[dict] = []

        # KEMCO 게시판 테이블
        table = (
            soup.find("table", class_=lambda c: c and ("board" in c or "list" in c or "notice" in c))
            or soup.find("table")
        )
        if not table:
            print("[KEMCO] 테이블 요소 미발견 → Mock 반환")
            return _MOCK_NOTICES["kemco"]

        tbody = table.find("tbody") or table
        rows  = tbody.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            title_td = next((td for td in cols if td.find("a")), None)
            if not title_td:
                continue

            a_tag  = title_td.find("a")
            title  = a_tag.get_text(strip=True)
            href   = a_tag.get("href", "")
            link   = (cfg["base"] + href) if href.startswith("/") else (href or cfg["base"])

            # 날짜 열: 보통 마지막에서 두 번째
            date_text = cols[-2].get_text(strip=True) if len(cols) >= 4 else cols[-1].get_text(strip=True)
            date = _parse_date(date_text)

            # 분류(카테고리) 열: 제목 이전 열에서 추출 시도
            title_idx = cols.index(title_td)
            category = cfg["category"]
            if title_idx > 0:
                cat_text = cols[title_idx - 1].get_text(strip=True)
                if cat_text and len(cat_text) < 15:  # 너무 긴 텍스트는 카테고리 아님
                    category = cat_text

            if title:
                notices.append({
                    "org":      cfg["org"],
                    "org_key":  "kemco",
                    "title":    title,
                    "date":     date,
                    "link":     link,
                    "category": category,
                    "is_mock":  False,
                })

        if not notices:
            print("[KEMCO] 파싱된 공지 0건 → Mock 반환")
            return _MOCK_NOTICES["kemco"]

        print(f"[KEMCO] 실데이터 수집 완료: {len(notices)}건")
        return notices[:10]

    except Exception as e:
        print(f"[KEMCO] 수집 실패: {e} → Mock 반환")
        return _MOCK_NOTICES["kemco"]


def _fetch_kepco_notices() -> list[dict]:
    """
    한국전력공사(KEPCO) 공지사항 크롤링.
    실패 시 Mock 즉시 반환.

    KEPCO 공지 게시판 HTML 구조:
      <table> → <tbody> → <tr> 행들
    """
    cfg = _AGENCY_CONFIG["kepco"]
    try:
        resp = requests.get(cfg["url"], headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        notices: list[dict] = []

        table = (
            soup.find("table", class_=lambda c: c and ("board" in c or "list" in c))
            or soup.find("table")
        )
        if not table:
            print("[KEPCO] 테이블 요소 미발견 → Mock 반환")
            return _MOCK_NOTICES["kepco"]

        tbody = table.find("tbody") or table
        rows  = tbody.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            title_td = next((td for td in cols if td.find("a")), None)
            if not title_td:
                continue

            a_tag = title_td.find("a")
            title = a_tag.get_text(strip=True)
            href  = a_tag.get("href", "")
            link  = (cfg["base"] + href) if href.startswith("/") else (href or cfg["base"])

            date_text = cols[-2].get_text(strip=True) if len(cols) >= 4 else cols[-1].get_text(strip=True)
            date = _parse_date(date_text)

            if title:
                notices.append({
                    "org":      cfg["org"],
                    "org_key":  "kepco",
                    "title":    title,
                    "date":     date,
                    "link":     link,
                    "category": cfg["category"],
                    "is_mock":  False,
                })

        if not notices:
            print("[KEPCO] 파싱된 공지 0건 → Mock 반환")
            return _MOCK_NOTICES["kepco"]

        print(f"[KEPCO] 실데이터 수집 완료: {len(notices)}건")
        return notices[:10]

    except Exception as e:
        print(f"[KEPCO] 수집 실패: {e} → Mock 반환")
        return _MOCK_NOTICES["kepco"]


def fetch_all_notices() -> list[dict]:
    """
    전체 유관기관 공지사항을 수집하여 날짜순 정렬 후 반환.
    각 기관은 독립적으로 실행 — 한 기관 실패가 다른 기관에 영향 없음.

    Returns:
        [{org, org_key, title, date, link, category, is_mock}, ...]
        날짜 내림차순 정렬 (최신 공지 먼저)
    """
    all_notices: list[dict] = []

    # 기관별 독립 수집 — 실패해도 다음 기관 계속 진행
    for fetcher in [_fetch_kpx_notices, _fetch_kemco_notices, _fetch_kepco_notices]:
        try:
            all_notices.extend(fetcher())
        except Exception as e:
            # 최외곽 예외 처리 (이중 안전망)
            print(f"[공지 크롤러] 예상치 못한 오류: {e}")

    # 날짜 내림차순 정렬 (최신 공지 먼저)
    all_notices.sort(key=lambda x: x.get("date", ""), reverse=True)
    return all_notices


# ── 단독 실행 시 테스트 ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("유관기관 공지사항 크롤링 테스트")
    print("실패 기관은 즉시 Mock 데이터로 대체됩니다.")
    print("=" * 60)

    notices = fetch_all_notices()
    print(f"\n수집된 공지 수: {len(notices)}건\n")

    for i, n in enumerate(notices, 1):
        mock_mark = " [MOCK]" if n["is_mock"] else " [실데이터]"
        print(f"[{i}] {n['date']} | {n['org']}{mock_mark}")
        print(f"     [{n['category']}] {n['title'][:60]}")
        print()
