"""
유관기관 공지사항 크롤러
========================
Layer 3 (Execution) — 결정론적 Python 스크립트

대상 기관:
  - KPX   (전력거래소)      : SMP·입찰공고·출력제어 공지
  - KEMCO (한국에너지공단)  : RPS·REC·보조금 공고
  - KEPCO (한국전력공사)    : 계통 연계·약관·접속 공지
  - 전기위원회              : 발전사업 허가·심의 결과
  - 신안군청                : 해상풍력 고시·공고·이익공유
  - 전남도청                : 해상풍력 단지 지정·인허가 공고

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
        "url":     "https://www.kpx.or.kr/menu.es?mid=a11201000000",
        "category": "공지사항",
    },
    "kemco": {
        "org":     "한국에너지공단",
        "base":    "https://www.kemco.or.kr",
        "url":     "https://www.kemco.or.kr/web/kem_home_new/info/news/notice/kem_list.asp",
        "category": "공지사항",
    },
    "kepco": {
        "org":     "한전 (KEPCO)",
        "base":    "https://home.kepco.co.kr",
        "url":     "https://home.kepco.co.kr/kepco/KR/ntcob/list.do?menuCd=FN3107&boardCd=BRD_000269",
        "category": "공지사항",
    },
    "eleccom": {
        "org":     "전기위원회",
        "base":    "https://www.korec.go.kr",
        # 구 도메인(electricitycommission.go.kr) → korec.go.kr 로 이전됨 (2025~)
        "url":     "https://www.korec.go.kr/notice/selectNoticeList.do",
        "category": "공지사항",
    },
    "shinan": {
        "org":     "신안군청",
        "base":    "https://www.shinan.go.kr",
        "url":     "https://www.shinan.go.kr/home/www/openinfo/participation_07/participation_07_02",
        "category": "고시공고",
    },
    "jeonnam": {
        "org":     "전남도청",
        "base":    "https://www.jeonnam.go.kr",
        "url":     "https://www.jeonnam.go.kr/M7124/boardList.do?menuId=jeonnam0201000000",
        "category": "고시공고",
    },
}

# ── Mock 데이터 ──────────────────────────────────────────────────────
# 크롤링 실패(403, 타임아웃, URL 오류) 시 표시하는 예시(placeholder) 데이터.
#
# ⚠️  주의 — 아래 내용은 실존하지 않는 가상의 예시입니다 ⚠️
#  - 모든 제목에 "[예시]" 접두사 부여
#  - 문서 번호·날짜는 임의 값 (실제 공문과 무관)
#  - 링크는 각 기관 공식 사이트 메인 → 실제 공지는 해당 사이트에서 직접 확인
_MOCK_NOTICES: dict[str, list[dict]] = {
    "kpx": [
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "[예시] 계통한계가격(SMP) 산정 결과 공표",
            "date": "——", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "[예시] 재생에너지 입찰시장 입찰 일정 공고",
            "date": "——", "link": "https://www.kpx.or.kr",
            "category": "입찰공고", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "[예시] 출력제어 사전통보 절차 관련 안내",
            "date": "——", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "[예시] 전력시장 운영규칙 개정 공고",
            "date": "——", "link": "https://www.kpx.or.kr",
            "category": "규정개정", "is_mock": True,
        },
        {
            "org": "KPX (전력거래소)", "org_key": "kpx",
            "title": "[예시] 재생에너지 공급인증서(REC) 거래량 집계 결과",
            "date": "——", "link": "https://www.kpx.or.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
    "kemco": [
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "[예시] 신재생에너지 공급의무화(RPS) 의무공급량 안내",
            "date": "——", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "[예시] 태양광 설비 REC 발급 기준 개정 안내",
            "date": "——", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "[예시] 해상풍력 발전량 인증 신청 접수 안내",
            "date": "——", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "[예시] 신재생에너지 설비 보급사업 공모 공고",
            "date": "——", "link": "https://www.kemco.or.kr",
            "category": "공모공고", "is_mock": True,
        },
        {
            "org": "한국에너지공단", "org_key": "kemco",
            "title": "[예시] ESS 연계 태양광 발전 REC 가중치 변경 안내",
            "date": "——", "link": "https://www.kemco.or.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
    "kepco": [
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "[예시] 분산형전원 계통 연계 기술기준 관련 공고",
            "date": "——", "link": "https://home.kepco.co.kr",
            "category": "기술기준", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "[예시] 전기공급약관 시행세칙 개정 안내",
            "date": "——", "link": "https://home.kepco.co.kr",
            "category": "약관개정", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "[예시] 신재생에너지 발전사업자 계통 접속 신청 결과",
            "date": "——", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "[예시] 해상풍력 계통 연계 공사비 분담 기준 안내",
            "date": "——", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "한전 (KEPCO)", "org_key": "kepco",
            "title": "[예시] 송전망 접속 신청 처리 절차 안내",
            "date": "——", "link": "https://home.kepco.co.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
    "eleccom": [
        {
            "org": "전기위원회", "org_key": "eleccom",
            "title": "[예시] 해상풍력 발전사업 허가 심의 결과 공표",
            "date": "——", "link": "https://www.electricitycommission.go.kr",
            "category": "허가심의", "is_mock": True,
        },
        {
            "org": "전기위원회", "org_key": "eleccom",
            "title": "[예시] 재생에너지 발전사업 허가 신청 일정 공고",
            "date": "——", "link": "https://www.electricitycommission.go.kr",
            "category": "공고", "is_mock": True,
        },
        {
            "org": "전기위원회", "org_key": "eleccom",
            "title": "[예시] 전기사업법 개정에 따른 발전사업 허가 기준 안내",
            "date": "——", "link": "https://www.electricitycommission.go.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "전기위원회", "org_key": "eleccom",
            "title": "[예시] 육상풍력 발전사업 허가 신청 접수 결과",
            "date": "——", "link": "https://www.electricitycommission.go.kr",
            "category": "허가심의", "is_mock": True,
        },
        {
            "org": "전기위원회", "org_key": "eleccom",
            "title": "[예시] 발전사업 사업 계획서 작성 요령 개정 안내",
            "date": "——", "link": "https://www.electricitycommission.go.kr",
            "category": "공지사항", "is_mock": True,
        },
    ],
    "shinan": [
        {
            "org": "신안군청", "org_key": "shinan",
            "title": "[예시] 해상풍력 발전단지 지구지정 고시",
            "date": "——", "link": "https://www.shinan.go.kr",
            "category": "고시", "is_mock": True,
        },
        {
            "org": "신안군청", "org_key": "shinan",
            "title": "[예시] 해상풍력 집적화단지 어업인 협의체 관련 공고",
            "date": "——", "link": "https://www.shinan.go.kr",
            "category": "공고", "is_mock": True,
        },
        {
            "org": "신안군청", "org_key": "shinan",
            "title": "[예시] 태양광·풍력 발전시설 이격거리 조례 관련 공고",
            "date": "——", "link": "https://www.shinan.go.kr",
            "category": "입법예고", "is_mock": True,
        },
        {
            "org": "신안군청", "org_key": "shinan",
            "title": "[예시] 해상풍력 주민참여 이익공유 사업 안내",
            "date": "——", "link": "https://www.shinan.go.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "신안군청", "org_key": "shinan",
            "title": "[예시] 공유수면 점용·사용허가 신청 처리 결과 공고",
            "date": "——", "link": "https://www.shinan.go.kr",
            "category": "공고", "is_mock": True,
        },
    ],
    "jeonnam": [
        {
            "org": "전남도청", "org_key": "jeonnam",
            "title": "[예시] 전라남도 해상풍력 특화단지 개발 기본계획 수립 공고",
            "date": "——", "link": "https://www.jeonnam.go.kr",
            "category": "공고", "is_mock": True,
        },
        {
            "org": "전남도청", "org_key": "jeonnam",
            "title": "[예시] 신재생에너지 산업 육성 지원 조례 관련 고시",
            "date": "——", "link": "https://www.jeonnam.go.kr",
            "category": "고시", "is_mock": True,
        },
        {
            "org": "전남도청", "org_key": "jeonnam",
            "title": "[예시] 전라남도 해상풍력 인허가 지원단 운영 계획 공고",
            "date": "——", "link": "https://www.jeonnam.go.kr",
            "category": "공고", "is_mock": True,
        },
        {
            "org": "전남도청", "org_key": "jeonnam",
            "title": "[예시] 해상풍력 어업피해 조사 및 보상 기준 안내",
            "date": "——", "link": "https://www.jeonnam.go.kr",
            "category": "공지사항", "is_mock": True,
        },
        {
            "org": "전남도청", "org_key": "jeonnam",
            "title": "[예시] 육상풍력 환경영향평가 협의 결과 고시",
            "date": "——", "link": "https://www.jeonnam.go.kr",
            "category": "고시", "is_mock": True,
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


def _fetch_generic_board(org_key: str) -> list[dict]:
    """
    한국 정부기관 표준 HTML 테이블 게시판 범용 파서.
    KPX·KEMCO·KEPCO 이외의 기관(전기위원회·신안군청·전남도청)에 사용.
    eGovFrame·행안부 표준프레임워크 사이트의 공통 테이블 구조를 처리.

    실패 조건: 403, 타임아웃, 테이블 없음, 파싱된 공지 0건 → 즉시 Mock 반환
    """
    cfg = _AGENCY_CONFIG[org_key]
    tag  = f"[{org_key.upper()}]"
    try:
        resp = requests.get(cfg["url"], headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        notices: list[dict] = []

        # 게시판 테이블 탐색 — class에 board/list/notice/bbs/tbl 포함하는 것 우선
        _BOARD_CLASSES = ("board", "list", "notice", "bbs", "tbl", "table")
        table = next(
            (
                soup.find("table", class_=lambda c: c and any(k in " ".join(c) for k in _BOARD_CLASSES))
                for _ in [1]  # 단일 순회용
            ),
            None,
        ) or soup.find("table")

        if not table:
            print(f"{tag} 테이블 요소 미발견 → Mock 반환")
            return _MOCK_NOTICES[org_key]

        tbody = table.find("tbody") or table
        rows  = tbody.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            # 제목 열: <a> 태그가 있는 첫 번째 td
            title_td = next((td for td in cols if td.find("a")), None)
            if not title_td:
                continue

            a_tag  = title_td.find("a")
            title  = a_tag.get_text(strip=True)
            href   = a_tag.get("href", "")
            link   = (cfg["base"] + href) if href.startswith("/") else (href or cfg["base"])

            # 날짜 열: 보통 마지막에서 두 번째 열 (마지막은 조회수)
            date_text = cols[-2].get_text(strip=True) if len(cols) >= 4 else cols[-1].get_text(strip=True)
            date = _parse_date(date_text)

            if title:
                notices.append({
                    "org":      cfg["org"],
                    "org_key":  org_key,
                    "title":    title,
                    "date":     date,
                    "link":     link,
                    "category": cfg["category"],
                    "is_mock":  False,
                })

        if not notices:
            print(f"{tag} 파싱된 공지 0건 → Mock 반환")
            return _MOCK_NOTICES[org_key]

        print(f"{tag} 실데이터 수집 완료: {len(notices)}건")
        return notices[:10]

    except Exception as e:
        print(f"{tag} 수집 실패: {e} → Mock 반환")
        return _MOCK_NOTICES[org_key]


def _fetch_eleccom_notices() -> list[dict]:
    """전기위원회 발전사업 허가·심의 공지 크롤링. 실패 시 Mock 즉시 반환."""
    return _fetch_generic_board("eleccom")


def _fetch_shinan_notices() -> list[dict]:
    """신안군청 해상풍력 고시·공고 크롤링. 실패 시 Mock 즉시 반환."""
    return _fetch_generic_board("shinan")


def _fetch_jeonnam_notices() -> list[dict]:
    """전남도청 신재생에너지 고시·공고 크롤링. 실패 시 Mock 즉시 반환."""
    return _fetch_generic_board("jeonnam")


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
    _FETCHERS = [
        _fetch_kpx_notices,
        _fetch_kemco_notices,
        _fetch_kepco_notices,
        _fetch_eleccom_notices,  # 전기위원회
        _fetch_shinan_notices,   # 신안군청
        _fetch_jeonnam_notices,  # 전남도청
    ]
    for fetcher in _FETCHERS:
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
