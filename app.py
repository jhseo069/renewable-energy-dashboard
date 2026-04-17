"""
신재생에너지 사업개발팀 - 사내 대시보드
=============================================
- Tab 1: 입지/규제 분석      (국가법령정보센터 API + Gemini AI)
- Tab 2: 일일 뉴스 모니터링   (네이버 뉴스 API + Gemini AI)
- Tab 3: 정책 및 입법 동향    (국회 API + 중앙부처 RSS)
- Tab 4: 유관기관 공지사항    (한전, KPX, 지자체 크롤링)
"""

import sys
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dtime, timezone
from pathlib import Path
from dotenv import load_dotenv
from utils.news_crawler import search_naver_news, save_to_archive, to_csv_bytes
from utils.law_api import search_ordinances, search_national_laws, get_server_ip

# execution/ 디렉토리를 Python 경로에 추가
# app.py와 같은 레벨의 execution/ 폴더에서 스크립트를 import하기 위함
sys.path.insert(0, str(Path(__file__).parent / "execution"))
from rss_crawler import fetch_rss_articles
from law_api import fetch_all_bills
from notice_crawler import fetch_all_notices
from ai_analyzer import analyze_ordinance, analyze_news_trends

load_dotenv()

_PERIOD_DELTA = {
    "최근 3일": timedelta(hours=72),
    "1주일": timedelta(weeks=1),
    "1개월": timedelta(days=30),
    "1년": timedelta(days=365),
}


def get_kst_now() -> datetime:
    """Returns the current naive datetime in KST (UTC+9)."""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).replace(tzinfo=None)


def _safe_parse_dt(date_str: str) -> datetime:
    # 뉴스 크롤러: "2026-03-06 14:30" / RSS: "2026-03-06"
    # 국회 API PROPOSE_DT: "20260415"(YYYYMMDD) 또는 "2026.04.15" 형식 추가 지원
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    return datetime.min


def _filter_by_period(items: list, period: str, date_key: str = "date") -> list:
    """기사 리스트를 선택 기간으로 필터링합니다."""
    if period == "전체":
        return items
    cutoff = get_kst_now() - _PERIOD_DELTA.get(period, timedelta(hours=72))
    return [
        item for item in items
        if _safe_parse_dt(item.get(date_key, "")) >= cutoff
    ]


# ── 뉴스 자동 수집 설정 ─────────────────────────────────
_KEYWORDS = (
    '해상풍력', '해상풍력설치선', 'WTIV', '하부설치선',
    '풍력', '태양광', 'ESS', 'BESS', '분산에너지',
    '그린수소', '수소발전', '출력제어', '전력계통', '신재생', 'PPA', 'REC',
)
_ENERGY_PUBLISHERS = ("전기신문", "에너지경제", "일렉트릭파워")
_KEYWORD_ICONS = {
    '해상풍력': '🌊', '해상풍력설치선': '🚢', 'WTIV': '🏗️', '하부설치선': '⚓',
    '풍력': '💨', '태양광': '☀️', 'ESS': '🔋',
    'BESS': '🔋', '분산에너지': '⚡', '그린수소': '💧', '수소발전': '⚡', '출력제어': '🎛️',
    '전력계통': '🔌', '신재생': '♻️', 'PPA': '📄', 'REC': '📋',
}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_all_keyword_news(keywords: tuple) -> dict:
    """15개 키워드 뉴스 일괄 수집 (1시간 캐시). 인증 오류는 즉시 전파."""
    result = {}
    for kw in keywords:
        try:
            result[kw] = search_naver_news(kw, display=100, keyword_in_title=kw)
        except ValueError:
            raise  # 401 등 인증 오류는 즉시 전파
        except Exception:
            result[kw] = []  # 개별 키워드 실패는 빈 리스트로 처리
    return result

# ── 정책/입법 동향 캐시 함수 ──────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _fetch_policy_rss() -> list[dict]:
    """수동 등록된 부처 보도자료를 반환합니다 (사이드바/뉴스레터용 5분 캐시).
    Tab 3 메인 디스플레이는 _load_press_releases() 직접 호출 (캐시 없이 즉시 반영).
    """
    return _load_press_releases()


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_attachments_cached(link: str) -> list[dict]:
    """단일 보도자료 링크의 첨부파일 목록 캐시 (1시간).
    기사 카드 렌더링 시 개별 호출 — 실패 시 빈 리스트 반환.
    """
    from rss_crawler import _fetch_attachments
    try:
        return _fetch_attachments(link)
    except Exception:
        return []


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_assembly_bills() -> list[dict]:
    """국회 법안 수집 (6시간 캐시). API 키 없으면 Mock 반환."""
    return fetch_all_bills()


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_agency_notices() -> list[dict]:
    """유관기관 공지사항 수집 (1시간 캐시). 크롤링 실패 시 Mock 반환."""
    return fetch_all_notices()


# ─────────────────────────────────────────────
# 페이지 기본 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="신재생에너지 사업개발 대시보드",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 커스텀 CSS
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
    /*
      [Premium Dynamic Theme - "Wow!" Edition (안전성 최우선 리빌딩 버전)]
      - 기능 마비가 잦은 강제 색상 오버라이딩 전면 제거
      - Streamlit 네이티브 테마 변수 100% 존중
      - 그림자(Shadow), 모서리둥글기(Radius), 전환(Transition) 중심의 고급 호버스킨만 입힘
    */
    
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

    /* === 전역 CSS 변수 (안전한 값만 유지) === */
    :root {
        --glow-shadow: 0 4px 20px rgba(13, 148, 136, 0.08);
        --glow-shadow-hover: 0 8px 32px rgba(13, 148, 136, 0.15);
        --kpi-gradient: linear-gradient(135deg, var(--primary-color), #0284c7); 
        --glass-bg: linear-gradient(135deg, rgba(255,255,255,0.03), transparent);
    }

    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif !important;
    }

    /* 몽환적인 전체 프리미엄 배경 (앱 틀만 칠함) */
    .stApp {
        background-image: radial-gradient(circle at 50% -10%, rgba(13, 148, 136, 0.06) 0%, transparent 60%);
        background-attachment: fixed;
    }

    /* 메인 타이틀 프리미엄라이징 (안전) */
    .main-header {
        font-size: 2.5rem;
        font-weight: 900;
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
        letter-spacing: -0.5px;
        position: relative;
    }
    .main-header::after {
        content: "";
        display: block;
        width: 100px;
        height: 5px;
        background: var(--kpi-gradient);
        margin: 1.2rem auto 0;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(13, 148, 136, 0.2);
    }
    .sub-header {
        text-align: center;
        font-size: 1.1rem;
        margin-bottom: 2.5rem;
        font-weight: 700;
        opacity: 0.8;
    }

    /* === 카드 컨테이너 스킨 (글자색상 터치 절대 금지) === */
    .card {
        background: var(--glass-bg);
        border: 1px solid rgba(13, 148, 136, 0.15);
        border-top: 4px solid var(--primary-color);
        border-radius: 16px;
        padding: 1.8rem;
        margin-bottom: 1.5rem;
        box-shadow: var(--glow-shadow);
        transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        backdrop-filter: blur(8px);
    }
    .card:hover {
        transform: translateY(-3px);
        box-shadow: var(--glow-shadow-hover);
        border-color: rgba(13, 148, 136, 0.3);
    }
    .card h4 { margin-bottom: 0.8rem; font-weight: 800; font-size: 1.25rem; }
    .card p  { font-size: 1rem; line-height: 1.7; font-weight: 500; }
    .card .meta { color: var(--primary-color); font-size: 0.9rem; margin-bottom: 0.6rem; font-weight: 800; }

    .coming-card {
        background: transparent;
        border: 2px dashed rgba(13, 148, 136, 0.4);
        border-radius: 16px;
        padding: 1.8rem 2rem;
        margin-bottom: 1.5rem;
    }

    /* === KPI 카드 (안전) === */
    .kpi-card {
        position: relative;
        background: var(--glass-bg);
        border: 1px solid rgba(13, 148, 136, 0.15);
        border-radius: 16px;
        padding: 1.8rem;
        text-align: center;
        box-shadow: var(--glow-shadow);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .kpi-card:hover {
        transform: translateY(-3px);
        box-shadow: var(--glow-shadow-hover);
        border-color: var(--primary-color);
    }
    .kpi-card .value {
        font-size: 2.6rem;
        font-weight: 900;
        color: var(--primary-color);
    }
    .kpi-card .label { font-size: 1rem; margin-top: 0.6rem; font-weight: 800; opacity: 0.8; }

    .section-title {
        font-size: 1.3rem;
        font-weight: 800;
        margin: 2.2rem 0 1rem 0;
        padding-bottom: 0.6rem;
        border-bottom: 2px solid rgba(13, 148, 136, 0.15);
    }

    /* === 뱃지 디자인 (고정색상 유지해도 무방한 영역) === */
    .badge {
        display: inline-block;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 800;
        margin-bottom: 8px;
    }
    .badge-ready   { background: rgba(34, 197, 94, 0.1); color: #16a34a; border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-pending { background: rgba(234, 179, 8, 0.1); color: #ca8a04; border: 1px solid rgba(234, 179, 8, 0.3); }
    .badge-plan    { background: rgba(14, 165, 233, 0.1); color: #0284c7; border: 1px solid rgba(14, 165, 233, 0.3); }

    /* === 버튼 호버 이펙트 (색상 강제 할당 전부 삭제, 오직 트랜지션만 제어) === */
    div[data-testid="stButton"] button {
        border-radius: 10px !important;
        font-weight: 700 !important;
        transition: transform 0.2s, box-shadow 0.2s !important;
    }
    div[data-testid="stButton"] button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 12px rgba(13, 148, 136, 0.2) !important;
    }

    /* === 확장 패널(Expander) 안전한 테두리 스킨 === */
    [data-testid="stExpander"] {
        border: 1px solid rgba(13, 148, 136, 0.15) !important;
        border-radius: 12px !important;
        background: var(--glass-bg);
        margin-bottom: 0.8rem;
    }
    [data-testid="stExpander"]:hover {
        border-color: rgba(13, 148, 136, 0.3) !important;
    }
    [data-testid="stExpander"] details summary {
        border-radius: 12px;
    }
    [data-testid="stExpander"] summary span {
        font-weight: 800 !important;
        font-size: 1.1rem !important;
    }
    [data-testid="stExpander"] summary svg {
        fill: var(--primary-color) !important;
    }
    
    /* 텍스트 폰트 두께 살짝 올려주기 (색상은 순정유지) */
    p, li, span, strong, h1, h2, h3, h4 {
        font-weight: 500;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 공지사항 / SMP/REC 헬퍼 (사이드바 + Tab 4 공통 사용)
# ─────────────────────────────────────────────
import json as _json
import os as _os

_NOTICES_FILE    = Path(__file__).parent / "data" / "notices.json"
_ATTACHMENTS_DIR = Path(__file__).parent / "data" / "attachments"
_SMP_REC_FILE    = Path(__file__).parent / "data" / "smp_rec.json"
_PRESS_FILE      = Path(__file__).parent / "data" / "press_releases.json"
Path(__file__).parent.joinpath("data").mkdir(parents=True, exist_ok=True)
_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

_T4_ORG_DISPLAY = {
    "kpx":     "KPX (전력거래소)",
    "kemco":   "한국에너지공단",
    "kepco":   "한전 (KEPCO)",
    "eleccom": "전기위원회",
    "shinan":  "신안군청",
    "jeonnam": "전남도청",
}


# ── Google Sheets 연동 헬퍼 ────────────────────────────────────────────
# st.secrets 에 GSHEET_ID 와 [gcp_service_account] 설정 시 자동 활성화.
# 미설정 시 로컬 JSON 파일로 폴백 (로컬 개발 환경 호환).
# ──────────────────────────────────────────────────────────────────────

def _gs_client():
    """gspread 클라이언트 반환 (설정 없거나 오류 시 None).
    gspread.service_account_from_dict() 사용 — 5.x/6.x 모두 호환.
    """
    try:
        import gspread
        if "gcp_service_account" not in st.secrets:
            return None
        # Streamlit AttrDict → 일반 dict 로 변환
        creds_dict = {k: v for k, v in st.secrets["gcp_service_account"].items()}
        return gspread.service_account_from_dict(creds_dict)
    except Exception:
        pass
    return None


def _gs_sheet_id() -> str:
    """Streamlit secrets 또는 환경변수에서 Google Sheet ID 반환."""
    try:
        sid = st.secrets.get("GSHEET_ID", "")
        return sid if sid else _os.getenv("GSHEET_ID", "")
    except Exception:
        return _os.getenv("GSHEET_ID", "")


def _gs_load(tab: str) -> list[dict] | None:
    """Google Sheet 탭에서 데이터 로드.
    - 연결 성공·탭 없음 → [] 반환
    - 미설정·오류 → None 반환 (JSON 폴백 트리거)
    """
    gc = _gs_client()
    sid = _gs_sheet_id()
    if not gc or not sid:
        return None
    try:
        sh = gc.open_by_key(sid)
        try:
            ws = sh.worksheet(tab)
        except Exception:
            return None  # 탭 미생성 → None 반환 → JSON 폴백 트리거
        records = ws.get_all_records()
        # SMP/REC 숫자 타입 보장
        if tab == "smp_rec":
            for r in records:
                for k in ("SMP", "REC"):
                    try:
                        r[k] = float(r[k])
                    except (ValueError, TypeError, KeyError):
                        r[k] = 0.0
        # attachments: JSON 문자열 → 리스트 복원
        for r in records:
            if "attachments" in r and isinstance(r["attachments"], str):
                try:
                    r["attachments"] = _json.loads(r["attachments"]) if r["attachments"] else []
                except Exception:
                    r["attachments"] = []
        return records
    except Exception:
        return None


def _gs_save(tab: str, data: list[dict]) -> None:
    """Google Sheet 탭에 데이터 전체 덮어쓰기."""
    gc = _gs_client()
    sid = _gs_sheet_id()
    if not gc or not sid:
        return
    try:
        sh = gc.open_by_key(sid)
        try:
            ws = sh.worksheet(tab)
        except Exception:
            ws = sh.add_worksheet(title=tab, rows=2000, cols=20)
        if not data:
            ws.clear()
            return
        headers = list(data[0].keys())
        rows = []
        for item in data:
            row = []
            for h in headers:
                v = item.get(h, "")
                if isinstance(v, list):
                    v = _json.dumps(v, ensure_ascii=False)
                row.append(v if v is not None else "")
            rows.append(row)
        ws.clear()
        ws.update([headers] + rows)
    except Exception as _e:
        print(f"[Sheets] _gs_save({tab}) 실패: {_e}")  # 로그에 기록 (JSON은 이미 저장됨)


def _gs_archive(source_tab: str, old_items: list[dict]) -> None:
    """30일 초과 항목을 Google Sheets 'archive' 탭으로 이동 (중복 방지).
    active 탭에서는 제거되고, archive 탭에 누적 보관됨.
    """
    if not old_items:
        return
    gc = _gs_client()
    sid = _gs_sheet_id()
    if not gc or not sid:
        return
    try:
        sh = gc.open_by_key(sid)
        try:
            ws = sh.worksheet("archive")
        except Exception:
            ws = sh.add_worksheet(title="archive", rows=5000, cols=25)

        # 기존 아카이브 로드 (added_at 기준 중복 방지)
        try:
            existing = ws.get_all_records()
        except Exception:
            existing = []
        existing_keys = {r.get("added_at", "") for r in existing if r.get("added_at")}

        # source_tab / archived_at 메타 추가 후 신규분만 필터
        now_str = get_kst_now().strftime("%Y-%m-%dT%H:%M:%S")
        new_items = []
        for item in old_items:
            if item.get("added_at", "") not in existing_keys:
                row = dict(item)
                row["archived_from"] = source_tab
                row["archived_at"]   = now_str
                # attachments 리스트 → JSON 문자열 직렬화
                if isinstance(row.get("attachments"), list):
                    row["attachments"] = _json.dumps(row["attachments"], ensure_ascii=False)
                new_items.append(row)

        if not new_items:
            return

        all_data = existing + new_items
        # 헤더: 기존 헤더에 신규 키 병합
        headers = list(all_data[0].keys())
        for item in all_data[1:]:
            for k in item.keys():
                if k not in headers:
                    headers.append(k)

        rows = [[item.get(h, "") for h in headers] for item in all_data]
        ws.clear()
        ws.update([headers] + rows)
    except Exception:
        pass  # 아카이브 실패 → 무시 (active 데이터는 정상 저장됨)


def _load_press_releases() -> list[dict]:
    """보도자료 로드: 수동(press_releases) + 자동RSS(press_releases_rss) 합산 반환.

    수동 항목: Google Sheets [press_releases] 탭 우선 → JSON 폴백
    자동 항목: Google Sheets [press_releases_rss] 탭 (Apps Script 수집분)
    source_type='auto' 로 구분 가능.
    """
    # ── 수동 항목 ──────────────────────────────────────────────────────
    gs = _gs_load("press_releases")
    if gs is not None:
        manual = gs
    else:
        manual = []
        if _PRESS_FILE.exists():
            try:
                manual = _json.loads(_PRESS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        if manual and _gs_sheet_id():
            _gs_save("press_releases", manual)

    # ── 자동 RSS 항목 (Apps Script → press_releases_rss 탭) ───────────
    auto_rss = _gs_load("press_releases_rss") or []

    # 합산 후 최신순 정렬 (added_at 기준)
    combined = manual + auto_rss
    combined.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return combined


def _save_press_releases(articles: list[dict]) -> None:
    """보도자료 저장: 30일 초과 항목은 archive로 이동, 나머지는 JSON + Google Sheets 저장."""
    cutoff = (get_kst_now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    old_items    = [a for a in articles if a.get("added_at", "9999") < cutoff]
    active_items = [a for a in articles if a.get("added_at", "9999") >= cutoff]
    if old_items:
        _gs_archive("press_releases", old_items)
    _PRESS_FILE.write_text(_json.dumps(active_items, ensure_ascii=False, indent=2), encoding="utf-8")
    _gs_save("press_releases", active_items)


def _load_notices() -> list[dict]:
    """공지사항 로드: Google Sheets 우선 → JSON 폴백 (탭 없으면 자동 마이그레이션)."""
    gs = _gs_load("notices")
    if gs is not None:
        return gs
    data: list[dict] = []
    if _NOTICES_FILE.exists():
        try:
            data = _json.loads(_NOTICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    if data and _gs_sheet_id():
        _gs_save("notices", data)
    return data


def _save_notices(notices: list[dict]) -> None:
    """공지사항 저장: 30일 초과 항목은 archive로 이동, 나머지는 JSON + Google Sheets 저장."""
    cutoff = (get_kst_now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    old_items    = [n for n in notices if n.get("added_at", "9999") < cutoff]
    active_items = [n for n in notices if n.get("added_at", "9999") >= cutoff]
    if old_items:
        _gs_archive("notices", old_items)
    _NOTICES_FILE.write_text(_json.dumps(active_items, ensure_ascii=False, indent=2), encoding="utf-8")
    _gs_save("notices", active_items)


def _load_smp_rec() -> list[dict]:
    """SMP/REC 로드: Sheets + JSON 병합 (date 기준 중복 제거, Sheets 우선).

    Sheets 탭이 일부 데이터만 가진 경우(예: 컨테이너 재시작 후 신규 입력분만 저장)
    git 추적 JSON의 과거 데이터와 합산하여 전체 추이를 복원한다.
    """
    gs = _gs_load("smp_rec")
    # JSON 데이터 로드 (git 추적 과거 데이터)
    json_data: list[dict] = []
    if _SMP_REC_FILE.exists():
        try:
            json_data = _json.loads(_SMP_REC_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    if gs is None:
        # Sheets 미연동 → JSON만 사용, 마이그레이션 시도
        if json_data and _gs_sheet_id():
            _gs_save("smp_rec", json_data)
        return json_data

    # Sheets + JSON 병합: JSON 기준으로 채우고 Sheets 데이터로 덮어쓰기 (Sheets 우선)
    merged: dict[str, dict] = {r["date"]: r for r in json_data}
    for r in gs:
        merged[r["date"]] = r
    result = sorted(merged.values(), key=lambda x: x.get("date", ""), reverse=True)
    # JSON에 없던 Sheets 데이터가 있거나 반대인 경우 → Sheets에 전체 동기화
    if len(result) > len(gs):
        _gs_save("smp_rec", result)
    return result


def _save_smp_rec(records: list[dict]) -> None:
    """SMP/REC 저장: JSON + Google Sheets 동시 저장."""
    _SMP_REC_FILE.write_text(_json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    _gs_save("smp_rec", records)


# ─────────────────────────────────────────────
# 일일 뉴스레터 생성 헬퍼
# ─────────────────────────────────────────────
_NL_CATEGORIES = {
    "해상풍력":      ["해상풍력", "해상풍력설치선", "WTIV", "하부설치선"],
    "풍력":          ["풍력"],
    "태양광/ESS":    ["태양광", "ESS", "BESS"],
    "정부정책/기타": ["분산에너지", "그린수소", "수소발전", "출력제어", "전력계통", "신재생", "PPA", "REC"],
}


def _generate_newsletter_html(
    vol: int,
    issue_date_str: str,
    news_by_cat: dict,
    rss_rows: list,
    notice_rows: list,
    smp_records: list,
    issue_bg: str,
    issue_content: str,
    events: list,
) -> str:
    """일일 뉴스레터 HTML 생성 — 브라우저에서 열어 인쇄/PDF 저장 가능"""
    import io, base64
    import matplotlib
    matplotlib.use("Agg")  # GUI 없는 환경(Streamlit Cloud)용 백엔드
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib import rcParams
    rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]
    rcParams["axes.unicode_minus"] = False

    # ── SMP/REC 추이 차트 생성 (base64 PNG) ─────────────────────────────
    chart_b64 = ""
    if len(smp_records) >= 2:
        try:
            _sr_sorted = sorted(smp_records, key=lambda x: x["date"])
            _dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in _sr_sorted]
            _smps  = [r["SMP"] for r in _sr_sorted]
            _recs  = [r["REC"] for r in _sr_sorted]

            fig, ax1 = plt.subplots(figsize=(4.2, 2.4))
            fig.patch.set_facecolor("#f8f9fa")
            ax1.set_facecolor("#f8f9fa")

            # 단일 y축 — SMP(파랑)·REC(주황) 동일 축에 표시
            ax1.plot(_dates, _smps, color="#2176ae", linewidth=1.8,
                     marker="o", markersize=3, label="SMP (원/kWh)")
            ax1.plot(_dates, _recs, color="#e67e22", linewidth=1.8,
                     marker="s", markersize=3, label="REC (원/REC)")
            ax1.set_ylabel("가격 (원)", fontsize=7, color="#444")
            ax1.tick_params(axis="y", labelcolor="#444", labelsize=6)
            ax1.tick_params(axis="x", labelsize=6)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
            ax1.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))

            # 최신값 레이블 표시
            ax1.annotate(f"{_smps[-1]:.2f}", xy=(_dates[-1], _smps[-1]),
                         xytext=(4, 0), textcoords="offset points",
                         fontsize=6, color="#2176ae", va="center")
            ax1.annotate(f"{_recs[-1]:.2f}", xy=(_dates[-1], _recs[-1]),
                         xytext=(4, 0), textcoords="offset points",
                         fontsize=6, color="#e67e22", va="center")

            ax1.legend(fontsize=6, loc="upper left", framealpha=0.7)
            plt.tight_layout(pad=0.5)

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception:
            chart_b64 = ""

    chart_img_html = (
        f'<img src="data:image/png;base64,{chart_b64}" '
        f'style="width:100%;max-width:340px;" alt="SMP/REC 추이 차트"/>'
        if chart_b64
        else '<p style="font-size:0.78rem;color:#aaa;padding:18px 0;">'
             '(데이터 2건 이상 입력 시 차트가 표시됩니다)</p>'
    )

    # SMP/REC 가격 비교 (최신 2개 항목)
    # 날짜 내림차순 정렬 보장 — Google Sheets 로드 시 순서가 다를 수 있음
    smp_records = sorted(smp_records, key=lambda x: x.get("date", ""), reverse=True)
    curr = smp_records[0] if len(smp_records) >= 1 else {"date": "—", "SMP": 0.0, "REC": 0.0}
    prev = smp_records[1] if len(smp_records) >= 2 else curr
    smp_diff  = curr["SMP"] - prev["SMP"]
    rec_diff  = curr["REC"] - prev["REC"]
    smp_arrow = "▼" if smp_diff < 0 else ("→" if smp_diff == 0 else "▲")
    rec_arrow = "▼" if rec_diff < 0 else ("→" if rec_diff == 0 else "▲")
    smp_col   = "#c0392b" if smp_diff < 0 else ("#888888" if smp_diff == 0 else "#27ae60")
    rec_col   = "#c0392b" if rec_diff < 0 else ("#888888" if rec_diff == 0 else "#27ae60")

    def _news_ul(items: list, limit: int = 6) -> str:
        return "".join(
            f'<li><a href="{n.get("link","#")}" target="_blank">{n.get("title","")}</a></li>'
            for n in items[:limit]
        )

    def _section(title: str, body_html: str) -> str:
        return (
            f'<div class="sec"><div class="sec-hd">{title}</div>'
            f'<div class="sec-bd">{body_html}</div></div>'
        )

    # 뉴스 섹션
    news_html = ""
    for cat, items in news_by_cat.items():
        if items:
            news_html += _section(cat, f'<ul>{_news_ul(items)}</ul>')

    # 기관 보도/공지 섹션
    inst_items = rss_rows[:8] + [n for n in notice_rows if n.get("category") in ("보도", "고시", "공지")][:6]
    inst_html = ""
    if inst_items:
        sub = "※산자부, 환경부, 해수부, 국방부, 국회, 에관공, 한전, KPX, 전기위원회"
        inst_html = _section(
            f'기관(보도, 고시, 공지)<br><small style="font-weight:400;font-size:0.75rem;">{sub}</small>',
            f'<ul>{_news_ul(inst_items, 10)}</ul>'
        )

    # 주요이슈사항
    issue_html = ""
    if issue_bg or issue_content:
        rows = ""
        if issue_bg:
            rows += f'<tr><td class="il">배경</td><td>{issue_bg}</td></tr>'
        if issue_content:
            content_fmt = issue_content.replace("\n", "<br>")
            rows += f'<tr><td class="il">주요<br>내용</td><td>{content_fmt}</td></tr>'
        issue_html = _section("주요이슈사항",
            f'<table class="it"><tbody>{rows}</tbody></table>')

    # 행사 일정
    event_html = ""
    valid_ev = [e for e in events if e.get("name", "").strip()]
    if valid_ev:
        rows = "".join(
            f'<tr><td>{e.get("date","")}</td><td>{e.get("name","")}</td>'
            f'<td>{e.get("place","")}</td><td>{e.get("host","")}</td></tr>'
            for e in valid_ev
        )
        event_html = _section("행사 일정",
            f'<table class="et"><thead><tr><th>일 시</th><th>행사명</th><th>장 소</th><th>주 관</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>Renewable Energy Daily Vol.{vol}</title>
<style>
  body{{font-family:'맑은 고딕','Malgun Gothic',sans-serif;margin:0;padding:20px;background:#f0f0f0;color:#333;}}
  .wrap{{max-width:760px;margin:0 auto;background:#fff;}}
  .hdr{{background:linear-gradient(135deg,#1a3a5c 0%,#2176ae 55%,#56a0d3 100%);overflow:hidden;}}
  .hdr-top{{display:flex;justify-content:space-between;align-items:flex-start;padding:14px 20px 4px;}}
  .logo{{font-size:2.4rem;font-weight:900;color:#f39c12;letter-spacing:3px;}}
  .iss{{font-size:0.8rem;color:#ecf0f1;text-align:right;line-height:1.6;}}
  .ttl{{padding:2px 20px 18px;font-size:1.9rem;font-weight:700;color:#fff;letter-spacing:1px;}}
  .sec{{margin:10px 18px;border:1px solid #ccc;border-radius:3px;}}
  .sec-hd{{background:#e2e6ea;padding:7px 13px;font-weight:700;font-size:0.9rem;color:#2c3e50;border-bottom:1px solid #ccc;}}
  .sec-bd{{padding:10px 13px;}}
  ul{{margin:4px 0;padding-left:18px;}}
  li{{margin:5px 0;font-size:0.87rem;line-height:1.5;}}
  li a{{color:#2c3e50;text-decoration:none;}}
  li a:hover{{text-decoration:underline;color:#2176ae;}}
  .pg{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
  .pt{{width:100%;border-collapse:collapse;font-size:0.84rem;}}
  .pt th,.pt td{{border:1px solid #ccc;padding:5px 9px;text-align:center;}}
  .pt th{{background:#f0f4f8;font-weight:700;}}
  .pt .lb{{text-align:left;font-weight:600;}}
  .it{{width:100%;border-collapse:collapse;font-size:0.84rem;}}
  .it td{{border:1px solid #ccc;padding:8px 11px;vertical-align:top;}}
  .il{{background:#f0f4f8;font-weight:700;width:55px;text-align:center;color:#2c3e50;}}
  .et{{width:100%;border-collapse:collapse;font-size:0.83rem;}}
  .et th,.et td{{border:1px solid #ccc;padding:6px 8px;text-align:center;}}
  .et th{{background:#f0f4f8;font-weight:700;}}
  .foot{{text-align:center;font-size:0.78rem;color:#888;padding:14px;border-top:1px solid #eee;margin-top:8px;}}
  @media print{{body{{background:#fff;padding:0;}}.wrap{{max-width:100%;}}}}
</style></head>
<body><div class="wrap">
  <div class="hdr">
    <div class="hdr-top">
      <div class="logo">KCH</div>
      <div class="iss">Daily Renewable Energy Issue<br>{issue_date_str} Vol. {vol}</div>
    </div>
    <div class="ttl">Renewable Energy Daily</div>
  </div>

  <div class="sec">
    <div class="sec-hd">가격지표</div>
    <div class="sec-bd"><div class="pg">
      <div>
        <p style="font-size:0.8rem;color:#666;margin:0 0 6px;">주간 SMP/REC 가격</p>
        <table class="pt">
          <thead>
            <tr><th>구 분</th><th colspan="2">평균 가격</th><th>비 고</th></tr>
            <tr><th></th><th style="font-weight:400;">{prev.get("date","직전")}</th><th style="font-weight:400;">{curr.get("date","최신")}</th><th></th></tr>
          </thead>
          <tbody>
            <tr><td class="lb">SMP</td><td>{prev["SMP"]:.2f}</td><td>{curr["SMP"]:.2f}</td><td style="color:{smp_col};">({smp_diff:+.2f}원 {smp_arrow})</td></tr>
            <tr><td class="lb">REC</td><td>{prev["REC"]:.0f}</td><td>{curr["REC"]:.0f}</td><td style="color:{rec_col};">({rec_diff:+.0f}원 {rec_arrow})</td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <p style="font-size:0.8rem;color:#666;margin:0 0 6px;">누적 SMP/REC 가격동향</p>
        {chart_img_html}
      </div>
    </div></div>
  </div>

  {news_html}
  {inst_html}
  {issue_html}
  {event_html}

  <p class="foot">※ 기사 제목을 클릭하시면 해당 링크로 연결됩니다.</p>
</div></body></html>"""


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ 대시보드 설정")
    st.markdown("---")

    st.markdown("**API 연동 현황**")
    api_status = [
        ("badge-ready",   "● 국가법령정보센터 API"),
        ("badge-ready",   "● Gemini AI (요약 분석)"),
        ("badge-ready",   "● 네이버 뉴스 API"),
        ("badge-ready",   "● 국회 열린국회 API"),
        ("badge-ready",   "● 중앙부처 RSS"),
        ("badge-ready",   "● 유관기관 공지 크롤러 (6개)"),
    ]
    for cls, label in api_status:
        st.markdown(f'<span class="badge {cls}">{label}</span>', unsafe_allow_html=True)

    # ── 일일 모니터링 전체 리포트 CSV ───────────────────────────────────
    st.markdown("---")
    st.markdown("**📊 일일 모니터링 전체 다운로드**")
    st.markdown(
        "<p style='color:#8892b0; font-size:0.78rem;'>"
        "탭2(뉴스)·탭3(보도자료+법안)·탭4(공지사항)를 하나의 CSV로 통합합니다.</p>",
        unsafe_allow_html=True,
    )

    # 어제 KST 00:00 기준 컷오프 — 오늘 + 어제 데이터 포함 (모든 구분 동일 기준 적용)
    _rpt_today    = get_kst_now().date()
    _rpt_cutoff   = datetime.combine(_rpt_today - timedelta(days=1), dtime(0, 0))
    _rpt_cutoff_str = _rpt_cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    # 뉴스 (Tab 2) — 캐시 활용
    try:
        _rpt_news_raw = _fetch_all_keyword_news(_KEYWORDS)
    except Exception:
        _rpt_news_raw = {}
    _rpt_rows = []
    for _kw in _KEYWORDS:
        for _n in _rpt_news_raw.get(_kw, []):
            if _safe_parse_dt(_n.get("date", "")) >= _rpt_cutoff:
                _rpt_rows.append({
                    "구분": "뉴스", "날짜": _n.get("date", ""),
                    "출처": _n.get("source", ""), "키워드": _kw,
                    "제목": _n.get("title", ""), "요약": _n.get("summary", ""),
                    "링크": _n.get("link", ""),
                })

    # 보도자료 (Tab 3 RSS) — 캐시 활용
    for _a in _fetch_policy_rss():
        if not _a.get("is_dummy") and _safe_parse_dt(_a.get("date", "")) >= _rpt_cutoff:
            _rpt_rows.append({
                "구분": "보도자료", "날짜": _a.get("date", ""),
                "출처": _a.get("source", ""), "키워드": "",
                "제목": _a.get("title", ""), "요약": _a.get("summary", ""),
                "링크": _a.get("link", ""),
            })

    # 국회 법안 (Tab 3) — 캐시 활용
    for _b in _fetch_assembly_bills():
        if not _b.get("is_mock") and _safe_parse_dt(_b.get("propose_date", "")) >= _rpt_cutoff:
            _rpt_rows.append({
                "구분": "국회법안", "날짜": _b.get("propose_date", ""),
                "출처": _b.get("committee", ""), "키워드": "",
                "제목": _b.get("title", ""),
                "요약": f"{_b.get('proposer','')} | {_b.get('status','')}",
                "링크": _b.get("link", ""),
            })

    # 공지사항 (Tab 4) — JSON에서 로드 (어제 00:00 이후 등록분, 뉴스·법안과 동일 기준)
    for _nc in _load_notices():
        if _nc.get("added_at", "") >= _rpt_cutoff_str:
            _rpt_rows.append({
                "구분": "공지사항", "날짜": _nc.get("date", ""),
                "출처": _T4_ORG_DISPLAY.get(_nc.get("org_key", ""), _nc.get("org_key", "")),
                "키워드": _nc.get("category", ""),
                "제목": _nc.get("title", ""), "요약": "",
                "링크": _nc.get("link", ""),
            })

    _rpt_df   = pd.DataFrame(_rpt_rows) if _rpt_rows else pd.DataFrame(
        columns=["구분", "날짜", "출처", "키워드", "제목", "요약", "링크"])
    _rpt_date = _rpt_today.strftime("%Y-%m-%d")
    st.download_button(
        label=f"📥 {_rpt_date} 전체 리포트 CSV",
        data=to_csv_bytes(_rpt_df),
        file_name=f"{_rpt_date}_신재생에너지_일일모니터링.csv",
        mime="text/csv",
        use_container_width=True,
        disabled=_rpt_df.empty,
        key="dl_daily_report",
    )
    if _rpt_df.empty:
        st.caption("오늘 수집된 데이터가 없습니다.")
    else:
        st.caption(f"총 {len(_rpt_df)}건 (뉴스 {sum(1 for r in _rpt_rows if r['구분']=='뉴스')}·"
                   f"보도자료 {sum(1 for r in _rpt_rows if r['구분']=='보도자료')}·"
                   f"법안 {sum(1 for r in _rpt_rows if r['구분']=='국회법안')}·"
                   f"공지 {sum(1 for r in _rpt_rows if r['구분']=='공지사항')}건)")

    # ── 일일 뉴스레터 생성 ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**📰 일일 뉴스레터 생성**")
    with st.expander("⚙️ 뉴스레터 설정 및 생성", expanded=False):
        nl_c1, nl_c2 = st.columns(2)
        with nl_c1:
            nl_vol  = st.number_input("Vol.", min_value=1, value=1, step=1, key="nl_vol")
        with nl_c2:
            nl_date = st.date_input("발행일", value=get_kst_now().date(), key="nl_date")

        st.markdown("<p style='font-size:0.82rem; color:#8892b0; margin:6px 0 2px;'>주요이슈사항</p>", unsafe_allow_html=True)
        nl_issue_bg = st.text_input("배경 (한 줄)", placeholder="예: 태양광 업계 간담회 개최…", key="nl_issue_bg")

        if st.button("🤖 AI 초안 생성", key="nl_ai_btn", use_container_width=True):
            try:
                _ai_news_raw = _fetch_all_keyword_news(_KEYWORDS)
                _ai_combined = []
                for _kw in _KEYWORDS:
                    for _n in _ai_news_raw.get(_kw, [])[:2]:
                        _ai_combined.append({**_n, "키워드": _kw})
                if _ai_combined:
                    with st.spinner("Gemini AI 초안 작성 중…"):
                        _draft = analyze_news_trends(_ai_combined[:20], "신재생에너지 주간 동향")
                    st.session_state["nl_issue_content"] = _draft
                    st.rerun()
            except Exception as _e:
                st.error(f"AI 오류: {_e}")

        nl_issue_content = st.text_area(
            "주요내용 (직접 입력 또는 AI 초안 수정)",
            height=160, key="nl_issue_content",
            placeholder="AI 초안 버튼 클릭 후 편집하거나 직접 입력하세요.",
        )

        st.markdown("<p style='font-size:0.82rem; color:#8892b0; margin:6px 0 2px;'>행사 일정 (줄당 1건: 날짜, 행사명, 장소, 주관)</p>", unsafe_allow_html=True)
        nl_events_raw = st.text_area(
            "행사", height=90, key="nl_events",
            placeholder="2026-03-10, 풍력 경쟁입찰 설명회, 코엑스, 에너지공단\n2026-03-11, 인터배터리 2026, 코엑스, 산업부",
        )

        if st.button("📄 HTML 뉴스레터 생성", key="nl_gen_btn", use_container_width=True):
            # 어제+오늘 2일치 뉴스 수집 (일일 리포트와 동일 기간)
            _nl_cutoff = datetime.combine(get_kst_now().date() - timedelta(days=1), dtime(0, 0))
            try:
                _nl_raw = _fetch_all_keyword_news(_KEYWORDS)
            except Exception:
                _nl_raw = {}

            _nl_by_cat: dict = {}
            for _cat, _kws in _NL_CATEGORIES.items():
                _seen, _items = set(), []
                for _kw in _kws:
                    for _n in _nl_raw.get(_kw, []):
                        _t = _n.get("title", "")
                        if _t not in _seen and _safe_parse_dt(_n.get("date", "")) >= _nl_cutoff:
                            _seen.add(_t)
                            _items.append(_n)
                _nl_by_cat[_cat] = _items[:6]

            _nl_rss     = [a for a in _fetch_policy_rss()
                           if not a.get("is_dummy") and _safe_parse_dt(a.get("date","")) >= _nl_cutoff]
            _nl_notices = [nc for nc in _load_notices()
                           if _safe_parse_dt(nc.get("date","")) >= _nl_cutoff]
            _nl_smp     = _load_smp_rec()[:10]

            # 행사 파싱
            _nl_events = []
            for _line in nl_events_raw.strip().split("\n"):
                _parts = [p.strip() for p in _line.split(",")]
                if len(_parts) >= 2 and _parts[0]:
                    _nl_events.append({
                        "date":  _parts[0],
                        "name":  _parts[1] if len(_parts) > 1 else "",
                        "place": _parts[2] if len(_parts) > 2 else "",
                        "host":  _parts[3] if len(_parts) > 3 else "",
                    })

            _nl_html = _generate_newsletter_html(
                vol=int(nl_vol),
                issue_date_str=nl_date.strftime("%Y. %m. %d"),
                news_by_cat=_nl_by_cat,
                rss_rows=_nl_rss,
                notice_rows=_nl_notices,
                smp_records=_nl_smp,
                issue_bg=nl_issue_bg,
                issue_content=nl_issue_content,
                events=_nl_events,
            )
            st.session_state["nl_generated_html"] = _nl_html
            st.success("✅ 생성 완료! 아래 버튼으로 다운로드하세요.")

        if "nl_generated_html" in st.session_state:
            _fname = f"{get_kst_now().strftime('%Y-%m-%d')}_RE_Daily_Vol{st.session_state.get('nl_vol',1)}.html"
            st.download_button(
                label="📥 HTML 다운로드",
                data=st.session_state["nl_generated_html"].encode("utf-8"),
                file_name=_fname,
                mime="text/html",
                use_container_width=True,
                key="nl_dl_btn",
            )

    st.markdown("---")
    st.markdown(
        "<p style='color:#8892b0; font-size:0.8rem;'>"
        "신재생에너지 사업개발팀<br>사내 대시보드 v0.8.5</p>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# 메인 헤더
# ─────────────────────────────────────────────
st.markdown(
    '<h1 class="main-header">⚡ 신재생에너지 사업개발 대시보드</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="sub-header">'
    "입지/규제 분석 &nbsp;|&nbsp; 일일 뉴스 &nbsp;|&nbsp; 정책/입법 동향 &nbsp;|&nbsp; 유관기관 공지"
    "</p>",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 4탭 구성
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📜 입지/규제 분석",
    "📰 일일 뉴스 모니터링",
    "🏛️ 정책 및 입법 동향",
    "📡 유관기관 공지사항",
])


# =============================================
# TAB 1 : 입지/규제 분석
# =============================================
with tab1:
    st.markdown("### 📜 입지 · 규제 분석 (국가법령 + 지자체 조례)")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "국가법령정보센터 API로 <b>국가법령(농지법·환경영향평가법 등)</b>과 "
        "<b>지자체 조례</b>를 동시에 검색합니다. "
        "카드의 <b>🤖 Gemini AI 분석</b> 또는 <b>💬 직접 질문</b>으로 핵심 규제를 즉시 요약합니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # 검색 영역
    col_q, col_btn = st.columns([4, 1])
    with col_q:
        search_query = st.text_input(
            "검색어",
            placeholder="예: 농지법, 전기사업법, 환경영향평가법, 태양광, 풍력발전, 해상풍력 …",
            label_visibility="collapsed",
        )
    with col_btn:
        search_clicked = st.button("🔍 검색", use_container_width=True)

    # 검색 버튼 클릭 시 국가법령 + 조례 동시 조회
    if search_clicked and search_query:
        with st.spinner("검색 중…"):
            nat_result  = {"total": 0, "items": []}
            ord_result  = {"total": 0, "items": []}
            search_error = None
            try:
                nat_result = search_national_laws(search_query)
            except Exception as e:
                search_error = str(e)
            try:
                ord_result = search_ordinances(search_query)
            except ValueError as e:
                st.error(f"🔑 {e}")
                server_ip = get_server_ip()
                st.info(
                    f"**현재 서버 IP: `{server_ip}`**\n\n"
                    "국가법령정보 공동활용 사이트 → OPEN API → OPEN API 신청 → "
                    "해당 항목 수정에서 위 IP를 도메인주소란에 추가로 등록해 주세요."
                )
            except Exception as e:
                search_error = str(e)

            if search_error:
                st.warning(
                    f"⚠️ 국가법령 검색 실패 (서버 연결 오류) — "
                    f"[🔗 law.go.kr에서 직접 검색하기 ↗](https://www.law.go.kr/lsSc.do?query={search_query})"
                    "\n\n> Streamlit Cloud(AWS) IP가 law.go.kr 국가법령 서버에서 차단될 수 있습니다. "
                    "지자체 조례 검색은 정상 동작합니다."
                )

            st.session_state["law_nat_result"]  = nat_result
            st.session_state["law_ord_result"]  = ord_result
            st.session_state["law_search_query"] = search_query

    nat_result = st.session_state.get("law_nat_result")
    ord_result = st.session_state.get("law_ord_result")
    law_query  = st.session_state.get("law_search_query", "")

    # KPI 행
    nat_total = nat_result["total"] if nat_result else 0
    ord_total = ord_result["total"] if ord_result else 0
    kpi_cols = st.columns(4)
    kpis = [
        ("⚖️", str(nat_total) if nat_result else "✅ 연동 완료", "국가법령 검색 수"),
        ("🏛️", str(ord_total) if ord_result else "✅ 연동 완료", "지자체 조례 검색 수"),
        ("🤖", "준비완료", "Gemini AI 분석"),
        ("💬", "직접 질문", "커스텀 질문"),
    ]
    for col, (icon, value, label) in zip(kpi_cols, kpis):
        with col:
            st.markdown(
                f"""<div class="kpi-card">
                    <div style="font-size:1.4rem;">{icon}</div>
                    <div class="value" style="font-size:1.3rem;">{value}</div>
                    <div class="label">{label}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    def _render_law_cards(items: list, section_key_prefix: str, target: str):
        """법령/조례 카드 렌더링 공통 함수."""
        for item in items:
            name_html = (
                f'<a href="{item["link"]}" target="_blank" '
                f'style="color:#ccd6f6; text-decoration:none;">{item["name"]}</a>'
                if item["link"] else item["name"]
            )
            org_icon = "⚖️" if target == "law" else "📍"
            html_str = (
                f'<div class="card">'
                f'<p class="meta">{org_icon} {item["org"]} &nbsp;·&nbsp; 공포 {item["date"]} &nbsp;·&nbsp; 시행 {item["enforce_date"]}</p>'
                f'<h4>{name_html}</h4>'
                f'<p><span style="color:#64ffda; font-size:0.82rem;">{item["type"]}</span></p>'
                f'</div>'
            )
            st.markdown(html_str, unsafe_allow_html=True)

            item_id     = item["mst"] or item["name"]
            btn_key     = f"{section_key_prefix}_btn_{item_id}"
            result_key  = f"{section_key_prefix}_result_{item_id}"
            prompt_key  = f"{section_key_prefix}_prompt_{item_id}"
            qbtn_key    = f"{section_key_prefix}_qbtn_{item_id}"

            # ── 버튼 행: 표준 분석 + 커스텀 질문 ──────────────────────
            col_ai, col_q_label = st.columns([2, 5])
            with col_ai:
                if st.button("🤖 Gemini AI 분석", key=btn_key, use_container_width=True):
                    with st.spinner(f"Gemini AI 분석 중 — {item['name']}…"):
                        try:
                            ai_result = analyze_ordinance(
                                law_name=item["name"],
                                org=item["org"],
                                url=item.get("link", ""),
                                mst=item.get("mst", ""),
                                target=target,
                            )
                            st.session_state[result_key] = ("standard", ai_result)
                        except ValueError as e:
                            st.session_state[result_key] = ("standard", f"❌ **API 키 오류**: {e}")
                        except Exception as e:
                            st.session_state[result_key] = ("standard", f"❌ **분석 실패**: {e}")

            # ── 커스텀 질문 입력창 ─────────────────────────────────────
            with st.expander("💬 직접 질문하기", expanded=False):
                custom_prompt = st.text_area(
                    "질문을 입력하세요",
                    key=prompt_key,
                    placeholder=(
                        "예) 태양광 이격거리 기준을 알려주세요.\n"
                        "예) 풍력 소음 규제 조항과 허가 조건을 설명해 주세요.\n"
                        "예) 이 법령에서 농업진흥구역 관련 규제는 무엇인가요?"
                    ),
                    height=100,
                    label_visibility="collapsed",
                )
                if st.button("💬 질문 전송", key=qbtn_key, use_container_width=False):
                    if not custom_prompt.strip():
                        st.warning("질문을 입력해 주세요.")
                    else:
                        with st.spinner(f"Gemini AI 답변 중 — {item['name']}…"):
                            try:
                                ai_result = analyze_ordinance(
                                    law_name=item["name"],
                                    org=item["org"],
                                    url=item.get("link", ""),
                                    mst=item.get("mst", ""),
                                    target=target,
                                    custom_question=custom_prompt.strip(),
                                )
                                st.session_state[result_key] = ("custom", ai_result)
                            except ValueError as e:
                                st.session_state[result_key] = ("custom", f"❌ **API 키 오류**: {e}")
                            except Exception as e:
                                st.session_state[result_key] = ("custom", f"❌ **분석 실패**: {e}")

            # ── 분석 결과 표시 ────────────────────────────────────────
            if result_key in st.session_state:
                mode, content = st.session_state[result_key]
                title = "📋 Gemini AI 분석 결과" if mode == "standard" else "💬 질문 답변"
                with st.expander(title, expanded=True):
                    st.markdown(content)

    # ── 검색 결과 표시 ─────────────────────────────────────────────────
    if nat_result or ord_result:
        # 국가법령 섹션
        if nat_result and nat_result["items"]:
            st.markdown(
                f'<p class="section-title">⚖️ 국가법령 검색 결과: "{law_query}" ({nat_result["total"]}건)</p>',
                unsafe_allow_html=True,
            )
            _render_law_cards(nat_result["items"], "nat", "law")
        elif nat_result:
            st.info(f'⚖️ 국가법령: "{law_query}"에 해당하는 법령이 없습니다.')

        st.markdown("---")

        # 지자체 조례 섹션
        if ord_result and ord_result["items"]:
            st.markdown(
                f'<p class="section-title">🏛️ 지자체 조례 검색 결과: "{law_query}" ({ord_result["total"]}건)</p>',
                unsafe_allow_html=True,
            )
            _render_law_cards(ord_result["items"], "ord", "ordin")
        elif ord_result:
            st.info(f'🏛️ 지자체 조례: "{law_query}"에 해당하는 조례가 없습니다.')

    else:
        # 초기 상태: 검색 방법 안내
        st.markdown(
            """<div class="coming-card">
                <h4>🔍 법령명 또는 키워드로 검색하세요</h4>
                <p style="color:#ffc837; font-size:0.85rem; margin-bottom:0.6rem;">
                    ⚠️ 이 API는 <b>법령명(이름)</b>으로만 검색됩니다.
                    "이격거리", "소음" 같은 내용어는 검색 불가합니다.
                </p>
                <ul>
                    <li><b>농지법</b> — 농업진흥구역·농지전용 규제 (국가법령)</li>
                    <li><b>환경영향평가법</b> — 환경영향평가 대상 기준 (국가법령)</li>
                    <li><b>전기사업법</b> — 발전사업 허가·계통연계 (국가법령)</li>
                    <li><b>신에너지 및 재생에너지</b> — 신재생에너지법 (국가법령)</li>
                    <li><b>태양광</b> — 전국 태양광 관련 지자체 조례</li>
                    <li><b>풍력발전</b> — 풍력발전 설치·관리 조례</li>
                    <li><b>해상풍력</b> — 해상풍력 관련 조례</li>
                </ul>
                <p style="margin-top:0.6rem;">🤖 검색 후 카드의 <b>Gemini AI 분석</b> 또는 <b>💬 직접 질문하기</b>를 사용하세요</p>
            </div>""",
            unsafe_allow_html=True,
        )


# =============================================
# TAB 2 : 일일 뉴스 모니터링
# =============================================
with tab2:
    st.markdown("### 📰 신재생에너지 일일 뉴스 모니터링")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "15개 핵심 키워드의 최신 뉴스를 자동 수집합니다. 결과는 1시간 캐시되며, 아카이브에 자동 저장됩니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # 상단 컨트롤
    col_toggle, col_refresh = st.columns([3, 1])
    with col_toggle:
        filter_pubs = st.toggle(
            "💡 3대 전문지 기사만 보기  (전기신문 · 에너지경제 · 일렉트릭파워)",
        )
    with col_refresh:
        if st.button("🔄 캐시 갱신", use_container_width=True,
                     help="1시간 캐시를 초기화하고 최신 뉴스를 다시 수집합니다."):
            st.cache_data.clear()
            if "news_archived_today" in st.session_state:
                del st.session_state["news_archived_today"]
            st.rerun()

    period = st.radio(
        "🗓️ 조회 기간",
        ["최근 3일", "1주일", "1개월", "1년", "전체"],
        horizontal=True,
        index=0,
        key="period_filter",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 15개 키워드 자동 수집 ──────────────────────
    with st.spinner("🔄 15개 키워드 뉴스 자동 수집 중… (최초 로딩 후 1시간 캐시)"):
        try:
            all_news = _fetch_all_keyword_news(_KEYWORDS)
            fetch_error = None
        except ValueError as e:
            all_news = {}
            fetch_error = str(e)
        except Exception as e:
            all_news = {}
            fetch_error = f"수집 오류: {e}"

    if fetch_error:
        st.error(f"🔑 {fetch_error}")
        st.markdown(
            """<div class="coming-card">
                <h4>🛠️ API 키 수정 방법</h4>
                <ul>
                    <li><a href="https://developers.naver.com" target="_blank" style="color:#00c9ff;">네이버 개발자센터</a>에 로그인 → 내 애플리케이션 선택</li>
                    <li><b>Client Secret</b> 전체 값을 복사 (보통 15~20자)</li>
                    <li>프로젝트 폴더의 <code>.env</code> 파일을 열고 <code>NAVER_CLIENT_SECRET=</code> 뒤에 붙여넣기</li>
                    <li>저장 후 🔄 캐시 갱신 버튼 클릭</li>
                </ul>
            </div>""",
            unsafe_allow_html=True,
        )

    elif all_news:
        # 전체 결과 DataFrame 구성
        all_rows = []
        for kw in _KEYWORDS:
            for item in all_news.get(kw, []):
                all_rows.append({**item, "키워드": kw})

        combined_raw = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
        if not combined_raw.empty:
            combined_raw.rename(
                columns={"date": "날짜", "source": "언론사", "title": "제목",
                         "summary": "요약", "link": "링크"},
                inplace=True,
            )
        # 아카이브 자동 저장 — 날짜가 바뀌면 재저장 (탭을 이틀에 걸쳐 열어둔 경우 대응)
        _today_str = get_kst_now().strftime("%Y-%m-%d")  # KST 기준 (Cloud는 UTC)
        if st.session_state.get("news_archived_today", "")[:10] != _today_str and not combined_raw.empty:
            archive_cols = ["날짜", "언론사", "제목", "요약", "링크"]
            saved_path = save_to_archive(combined_raw[archive_cols])
            st.session_state.news_archived_today = saved_path.name

        # 기간 필터 적용
        if period != "전체" and not combined_raw.empty:
            _cutoff = get_kst_now() - _PERIOD_DELTA[period]
            combined_raw = combined_raw[
                combined_raw["날짜"].apply(lambda d: _safe_parse_dt(d) >= _cutoff)
            ]

        # 전문지 필터 적용
        display_df = (
            combined_raw[combined_raw["언론사"].isin(_ENERGY_PUBLISHERS)]
            if filter_pubs and not combined_raw.empty else combined_raw
        )

        # KPI 행
        kpi_cols = st.columns(4)
        kpi_data = [
            ("📰", str(len(display_df)), "수집된 뉴스"),
            ("🏢", str(display_df["언론사"].nunique()) if not display_df.empty else "0", "언론사 수"),
            ("🔑", str(len(_KEYWORDS)), "모니터링 키워드"),
            ("💾", "저장됨", st.session_state.get("news_archived_today", "—")),
        ]
        for col, (icon, value, label) in zip(kpi_cols, kpi_data):
            with col:
                st.markdown(
                    f"""<div class="kpi-card">
                        <div style="font-size:1.4rem;">{icon}</div>
                        <div class="value" style="font-size:1.3rem;">{value}</div>
                        <div class="label">{label}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

        st.markdown("<br>", unsafe_allow_html=True)

        # 다운로드 버튼
        col_dl, col_info = st.columns([2, 3])
        with col_dl:
            today_str = get_kst_now().strftime("%Y-%m-%d")
            dl_df = display_df[["키워드", "날짜", "언론사", "제목", "요약", "링크"]] if not display_df.empty else display_df
            st.download_button(
                label="📥 오늘의 전체 뉴스 엑셀(CSV) 다운로드",
                data=to_csv_bytes(dl_df),
                file_name=f"{today_str}_뉴스_전체.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_info:
            archived_name = st.session_state.get("news_archived_today", "")
            filter_status = "⚡ 3대 전문지 필터 ON" if filter_pubs else "🌐 전체 언론사 표시 중"
            st.markdown(
                f"<p style='color:#64ffda; font-size:0.85rem; margin-top:0.6rem;'>"
                f"✅ 자동 저장 → <code>data/news_archive/{archived_name}</code><br>"
                f"{filter_status} &nbsp;·&nbsp; 캐시 유효 1시간 &nbsp;·&nbsp; 🔄 캐시 갱신으로 즉시 업데이트</p>",
                unsafe_allow_html=True,
            )

        # 키워드별 Expander (해상풍력+WTIV 통합, ESS+BESS 통합)
        _DISPLAY_GROUPS = [
            ("해상풍력", "해상풍력설치선", "WTIV", "하부설치선"),  # 해상풍력 + 특수 선박 키워드 통합
            ("풍력",),
            ("태양광",),
            ("ESS", "BESS"),   # 통합 그룹
            ("분산에너지",),
            ("그린수소", "수소발전"),
            ("출력제어",),
            ("전력계통",),
            ("신재생",),
            ("PPA",),
            ("REC",),
        ]

        st.markdown('<p class="section-title">키워드별 뉴스 브리핑</p>', unsafe_allow_html=True)
        for kw_group in _DISPLAY_GROUPS:
            if len(kw_group) == 1:
                kw = kw_group[0]
                kw_news = all_news.get(kw, [])
                display_name = kw
                icon = _KEYWORD_ICONS.get(kw, "📌")
            else:
                # 복수 키워드 병합: 중복 제거(링크 기준) 후 최신순 정렬
                merged = []
                for kw in kw_group:
                    merged.extend(all_news.get(kw, []))
                seen_links: set = set()
                kw_news = []
                for item in merged:
                    if item["link"] not in seen_links:
                        seen_links.add(item["link"])
                        kw_news.append(item)
                kw_news.sort(key=lambda x: x["date"], reverse=True)
                # 그룹별 표시명 결정
                if "해상풍력" in kw_group:
                    display_name = "해상풍력"
                    icon = "🌊"
                elif "ESS" in kw_group:
                    display_name = "ESS/BESS 동향"
                    icon = "🔋"
                elif "그린수소" in kw_group:
                    display_name = "수소"
                    icon = "💧"
                else:
                    display_name = " / ".join(kw_group)
                    icon = "📌"

            # 전문지 필터 적용
            if filter_pubs:
                kw_news = [n for n in kw_news if n.get("source", "") in _ENERGY_PUBLISHERS]

            # 기간 필터 적용
            kw_news = _filter_by_period(kw_news, period)

            with st.expander(f"{icon} {display_name}  ({len(kw_news)}건)"):
                if kw_news:
                    # ── Gemini AI 동향 분석 버튼 ──────────────────────
                    news_btn_key    = f"analyze_news_{display_name}"
                    news_result_key = f"news_analysis_{display_name}"

                    col_ai_btn, col_ai_space = st.columns([2, 5])
                    with col_ai_btn:
                        if st.button("🤖 Gemini AI 동향 분석", key=news_btn_key, use_container_width=True):
                            with st.spinner(f"Gemini AI 분석 중 — {display_name}…"):
                                try:
                                    ai_result = analyze_news_trends(kw_news, display_name)
                                    st.session_state[news_result_key] = ai_result
                                except ValueError as e:
                                    st.session_state[news_result_key] = f"❌ **API 키 오류**: {e}"
                                except Exception as e:
                                    st.session_state[news_result_key] = f"❌ **분석 실패**: {e}"

                    if news_result_key in st.session_state:
                        with st.expander("📋 AI 동향 분석 결과", expanded=True):
                            st.markdown(st.session_state[news_result_key])

                    # ── 뉴스 카드 목록 ────────────────────────────────
                    with st.container(height=400):
                        for item in kw_news:
                            html_str = (
                                f'<div class="card">'
                                f'<p class="meta">🏢 {item["source"]} &nbsp;·&nbsp; {item["date"]}</p>'
                                f'<h4><a href="{item["link"]}" target="_blank" style="color:#ccd6f6; text-decoration:none;">{item["title"]}</a></h4>'
                                f'<p>{item["summary"]}</p>'
                                f'</div>'
                            )
                            st.markdown(html_str, unsafe_allow_html=True)
                else:
                    st.markdown(
                        "<p style='color:#8892b0; font-size:0.9rem; padding:0.5rem 0;'>"
                        "수집된 기사가 없습니다.</p>",
                        unsafe_allow_html=True,
                    )

    # ── 추가 키워드 직접 검색 ──────────────────────
    st.markdown("---")
    st.markdown('<p class="section-title">🔍 추가 키워드 직접 검색</p>', unsafe_allow_html=True)
    col_q, col_btn2 = st.columns([4, 1])
    with col_q:
        news_query = st.text_input(
            "검색어",
            placeholder="위 15개 외 추가 검색어를 입력하세요 …",
            label_visibility="collapsed",
            key="news_query",
        )
    with col_btn2:
        news_search = st.button("🔍 검색", use_container_width=True, key="news_search")

    use_pub_filter = st.checkbox(
        "⚡ 3대 전문지 집중 검색 (전기신문 · 에너지경제 · 일렉트릭파워)",
        key="pub_filter_manual",
    )

    if news_search and news_query:
        from utils.news_crawler import search_with_publishers
        with st.spinner("검색 중…"):
            try:
                if use_pub_filter:
                    manual_results = search_with_publishers(news_query)
                    label_text = f"3대 전문지 · {news_query}"
                else:
                    manual_results = search_naver_news(news_query, display=20)
                    label_text = f"전체 · {news_query}"

                if manual_results:
                    st.markdown(
                        f'<p class="section-title">검색 결과: {label_text} ({len(manual_results)}건)</p>',
                        unsafe_allow_html=True,
                    )
                    for item in manual_results:
                        html_str = (
                            f'<div class="card">'
                            f'<p class="meta">🏢 {item["source"]} &nbsp;·&nbsp; {item["date"]}</p>'
                            f'<h4><a href="{item["link"]}" target="_blank" style="color:#ccd6f6; text-decoration:none;">{item["title"]}</a></h4>'
                            f'<p>{item["summary"]}</p>'
                            f'</div>'
                        )
                        st.markdown(html_str, unsafe_allow_html=True)
                else:
                    st.info("검색 결과가 없습니다. 다른 키워드로 시도해 보세요.")
            except ValueError as e:
                st.error(f"🔑 API 키 오류: {e}")
            except Exception as e:
                st.error(f"❌ 검색 오류: {e}")


# =============================================
# TAB 3 : 정책 및 입법 동향
# =============================================
with tab3:
    st.markdown("### 🏛️ 정책 및 입법 동향")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "유관 부처 보도자료는 <b>브라우저에서 직접 추가·관리</b>합니다. "
        "등록한 내용은 서버에 영구 저장되며 클라우드에서 즉시 반영됩니다. "
        "국회 법안은 API로 직접 수집됩니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # 갱신 버튼 및 기간 필터
    col_pol_refresh, col_pol_period, col_pol_info = st.columns([1, 2, 2])
    with col_pol_refresh:
        if st.button("🔄 갱신", key="policy_refresh", use_container_width=True,
                     help="RSS·법안 캐시를 초기화하고 최신 데이터를 다시 수집합니다."):
            st.cache_data.clear()
            st.rerun()
    with col_pol_period:
        policy_period = st.selectbox(
            "보도자료 수집 범위",
            options=["최근 3일", "1주일", "1개월", "1년", "전체"],
            index=0,
            label_visibility="collapsed",
            key="policy_period"
        )
    with col_pol_info:
        st.markdown(
            "<p style='color:#8892b0; font-size:0.82rem; margin-top:0.5rem;'>"
            "보도자료: 브라우저 수동 등록 (서버 영구저장) · 법안 6시간 캐시 · "
            "<code>ASSEMBLY_API_KEY</code> 설정 시 실서버 전환</p>",
            unsafe_allow_html=True,
        )

    # ── 데이터 사전 수집 (통합 CSV용) ─────────────────────────────────
    # 보도자료: 캐시 없이 직접 로드 (추가/삭제 즉시 반영)
    with st.spinner("데이터 수집 중…"):
        all_press_articles = _load_press_releases()
        raw_bills          = _fetch_assembly_bills()
        bills              = _filter_by_period(raw_bills, policy_period, date_key="propose_date")

    # ── 오늘(자정 기준) 일별 표시 필터 ────────────────────────────────────
    # 오늘 00:00 KST 이후 등록분을 기본 표시합니다 (Google Sheets에 영구 보존).
    _p_now        = get_kst_now()
    _p_today_str  = _p_now.strftime("%Y-%m-%d")
    # added_at 형식이 "YYYY-MM-DDTHH:MM:SS"(수동) 또는 "YYYY-MM-DD HH:MM:SS"(RSS 자동수집) 혼재
    # → startswith로 날짜 문자열 비교하여 형식 차이 무관하게 오늘 항목 필터
    _p_today      = [a for a in all_press_articles if a.get("added_at", "").startswith(_p_today_str)]
    press_hidden_count = len(all_press_articles) - len(_p_today)

    # "이전 보도자료 보기" 체크박스 토글 반영
    display_press = all_press_articles if st.session_state.get("show_old_press") else _p_today

    # 화면 표시: 오늘(또는 전체) 필터 적용 후 기간 필터
    rss_articles = _filter_by_period(display_press, policy_period, date_key="date")

    # ── 통합 CSV 다운로드 버튼 (Tab 2와 동일한 방식 — 상단 1개) ──────
    today_str = get_kst_now().strftime("%Y-%m-%d")
    # CSV는 9:00 필터 미적용 — 전체 기간 필터 기준으로 다운로드
    rss_rows = [{
        "구분": "보도자료",
        "날짜": a.get("date", ""),
        "출처": a.get("source", ""),
        "제목": a.get("title", ""),
        "요약": a.get("summary", ""),
        "링크": a.get("link", ""),
    } for a in _filter_by_period(all_press_articles, policy_period, date_key="date")]
    bill_rows = [{
        "구분": "국회법안",
        "날짜": b.get("propose_date", ""),
        "출처": b.get("committee", ""),
        "제목": b.get("title", ""),
        "요약": f"{b.get('proposer','')} | {b.get('status','')}",
        "링크": b.get("link", ""),
    } for b in bills if not b.get("is_mock")]
    combined_df = pd.DataFrame(rss_rows + bill_rows)
    if not combined_df.empty:
        st.download_button(
            label="📥 정책·입법 전체 엑셀(CSV) 다운로드 (보도자료 + 국회법안)",
            data=to_csv_bytes(combined_df),
            file_name=f"{today_str}_정책입법동향.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 두 섹션 나란히 배치 ────────────────────────────────────────────
    col_rss, col_law = st.columns(2)

    # ── 왼쪽: 부처 보도자료 (수동 등록 — Tab 4 방식)
    with col_rss:
        st.markdown('<p class="section-title">📢 유관 부처 보도자료</p>', unsafe_allow_html=True)

        # ── 보도자료 추가 폼 ─────────────────────────────────────────────
        with st.expander("➕ 보도자료 추가하기", expanded=False):
            st.markdown(
                "<p style='color:#8892b0; font-size:0.85rem;'>"
                "부처 홈페이지에서 확인한 보도자료를 아래 폼에 입력하세요. "
                "입력한 내용은 서버에 영구 저장됩니다.</p>",
                unsafe_allow_html=True,
            )
            pr_col1, pr_col2 = st.columns(2)
            with pr_col1:
                pr_dept = st.selectbox(
                    "부처 선택",
                    options=["산업부", "기후부", "해수부", "농림부", "국토부"],
                    key="pr_form_dept",
                )
                pr_category = st.selectbox(
                    "카테고리",
                    options=["보도자료", "정책안내", "규제개정", "기타"],
                    key="pr_form_category",
                )
                pr_date = st.date_input("날짜", value=get_kst_now().date(), key="pr_form_date")
            with pr_col2:
                pr_title = st.text_input(
                    "제목 *",
                    placeholder="보도자료 제목을 입력하세요",
                    key="pr_form_title",
                )
                pr_link = st.text_input(
                    "원문 링크 URL (없으면 빈칸)",
                    placeholder="https://",
                    key="pr_form_link",
                )
                pr_summary = st.text_area(
                    "요약 (선택)",
                    placeholder="주요 내용을 간략히 입력하세요",
                    key="pr_form_summary",
                    height=80,
                )
                pr_files = st.file_uploader(
                    "첨부파일 (PDF·HWP·DOCX·XLSX·PNG·JPG 등, 복수 선택 가능)",
                    accept_multiple_files=True,
                    key=f"pr_form_files_{st.session_state.get('pr_uploader_key', 0)}",
                )

            if st.button("✅ 추가", key="pr_form_submit", use_container_width=False):
                if not pr_title.strip():
                    st.error("제목을 입력해 주세요.")
                else:
                    pr_added_at = get_kst_now().strftime("%Y-%m-%dT%H:%M:%S")

                    # 첨부파일 저장 (타임스탬프 prefix로 파일명 충돌 방지)
                    pr_saved_files = []
                    for uf in (pr_files or []):
                        safe_name = pr_added_at.replace(":", "-") + "_" + uf.name
                        save_path = _ATTACHMENTS_DIR / safe_name
                        save_path.write_bytes(uf.read())
                        pr_saved_files.append({"name": uf.name, "saved": safe_name})

                    new_press = {
                        "source":      pr_dept,
                        "category":    pr_category,
                        "title":       pr_title.strip(),
                        "date":        pr_date.strftime("%Y-%m-%d"),
                        "link":        pr_link.strip(),
                        "summary":     pr_summary.strip(),
                        "attachments": pr_saved_files,
                        "added_at":    pr_added_at,
                    }
                    all_press = _load_press_releases()
                    all_press.insert(0, new_press)   # 최신 순 맨 앞에 삽입
                    _save_press_releases(all_press)
                    st.cache_data.clear()
                    att_msg = f" (첨부 {len(pr_saved_files)}개)" if pr_saved_files else ""
                    st.success(f"✅ 보도자료가 등록되었습니다: {pr_title.strip()}{att_msg}")
                    # 폼 필드 초기화 (제목·링크·요약·파일업로더)
                    for _k in ["pr_form_title", "pr_form_link", "pr_form_summary"]:
                        if _k in st.session_state:
                            del st.session_state[_k]
                    st.session_state["pr_uploader_key"] = st.session_state.get("pr_uploader_key", 0) + 1
                    st.rerun()

        dept_icons = {
            "산업부": "⚡",
            "기후부": "🌿",
            "해수부": "🌊",
            "농림부": "🌾",
            "국토부": "🏗️",
        }
        _T3_DEPT_URL = {
            "산업부": "https://www.motie.go.kr/motie/ne/presse/press2/bbs/bbsList.do?bbs_seq_n=161",
            "기후부": "https://www.me.go.kr/home/web/board/list.do?menuId=10525",
            "해수부": "https://www.mof.go.kr/newsroom/pressReleases.do",
            "농림부": "https://www.mafra.go.kr/bbs/mafra/68/artcl/list.do",
            "국토부": "https://www.molit.go.kr/USR/NEWS/m_71/lst.jsp?m=71",
        }

        if rss_articles:
            # 부처별로 그룹핑해서 Expander로 표시
            dept_groups: dict[str, list] = {}
            for article in rss_articles:
                dept = article["source"]
                dept_groups.setdefault(dept, []).append(article)

            for dept, articles in dept_groups.items():
                icon = dept_icons.get(dept, "🏛️")

                with st.expander(f"{icon} {dept}  ({len(articles)}건)", expanded=True):
                    # 부처 보도자료 홈페이지 바로가기
                    dept_url = _T3_DEPT_URL.get(dept, "")
                    if dept_url:
                        st.markdown(
                            f'<a href="{dept_url}" target="_blank" style="'
                            f'display:inline-block; margin-bottom:0.7rem; padding:0.3rem 0.9rem; '
                            f'background:rgba(100,255,218,0.1); border:1px solid rgba(100,255,218,0.3); '
                            f'border-radius:8px; color:#64ffda; font-size:0.82rem; text-decoration:none;">'
                            f'🔗 {dept} 보도자료 바로가기 ↗</a>',
                            unsafe_allow_html=True,
                        )

                    # ── Gemini AI 동향 분석 버튼 ──────────────────────
                    rss_btn_key    = f"analyze_rss_{dept}"
                    rss_result_key = f"rss_analysis_{dept}"
                    col_rss_ai, col_rss_space = st.columns([2, 5])
                    with col_rss_ai:
                        if st.button("🤖 Gemini AI 동향 분석", key=rss_btn_key, use_container_width=True):
                            news_for_ai = [
                                {"title": a["title"], "summary": a["summary"],
                                 "source": a["source"], "date": a["date"]}
                                for a in articles
                            ]
                            if news_for_ai:
                                with st.spinner(f"Gemini AI 분석 중 — {dept} 보도자료…"):
                                    try:
                                        ai_result = analyze_news_trends(news_for_ai, f"{dept} 정책 보도자료")
                                        st.session_state[rss_result_key] = ai_result
                                    except ValueError as e:
                                        st.session_state[rss_result_key] = f"❌ **API 키 오류**: {e}"
                                    except Exception as e:
                                        st.session_state[rss_result_key] = f"❌ **분석 실패**: {e}"
                            else:
                                st.session_state[rss_result_key] = "분석할 보도자료가 없습니다."

                    if rss_result_key in st.session_state:
                        with st.expander("📋 Gemini AI 분석 결과 보기", expanded=True):
                            st.markdown(st.session_state[rss_result_key])

                    with st.container(height=400):
                        for article in articles:
                            c_card, c_del = st.columns([10, 1])
                            with c_card:
                                cat_badge = (
                                    f' · <span style="font-size:0.72rem; padding:0.1rem 0.4rem; '
                                    f'background:rgba(100,255,218,0.1); border-radius:4px;">'
                                    f'{article["category"]}</span>'
                                    if article.get("category") else ""
                                )
                                att_list = article.get("attachments", [])
                                att_badge = (
                                    f' &nbsp;<span style="color:#64ffda; font-size:0.78rem;">📎 {len(att_list)}개</span>'
                                    if att_list else ""
                                )
                                auto_badge = (
                                    ' &nbsp;<span style="font-size:0.72rem; padding:0.1rem 0.4rem; '
                                    'background:rgba(146,254,157,0.15); border-radius:4px; color:#92fe9d;">🤖 자동수집</span>'
                                    if article.get("source_type") == "auto" else ""
                                )
                                summary_text = article.get("summary", "")
                                summary_html = (
                                    f'<p>{summary_text[:150]}{"…" if len(summary_text) > 150 else ""}</p>'
                                    if summary_text else ""
                                )
                                link_href = article.get("link", "").strip()
                                title_html = (
                                    f'<a href="{link_href}" target="_blank" style="color:#ccd6f6; text-decoration:none;">{article["title"]}</a>'
                                    if link_href else f'<span style="color:#ccd6f6;">{article["title"]}</span>'
                                )
                                html_str = (
                                    f'<div class="card" style="margin-bottom:0.5rem;">'
                                    f'<p class="meta">🏢 {article["source"]} · {article["date"]}{cat_badge}{att_badge}{auto_badge}</p>'
                                    f'<h4 style="font-size:0.92rem;">{title_html}</h4>'
                                    f'{summary_html}'
                                    f'</div>'
                                )
                                st.markdown(html_str, unsafe_allow_html=True)
                                # 첨부파일 개별 다운로드 버튼
                                for att in att_list:
                                    att_path = _ATTACHMENTS_DIR / att["saved"]
                                    if att_path.exists():
                                        st.download_button(
                                            label=f"📎 {att['name']}",
                                            data=att_path.read_bytes(),
                                            file_name=att["name"],
                                            key=f"pr_att_{article.get('added_at','')}_{att['saved']}",
                                        )
                            with c_del:
                                del_key = f"del_pr_{article.get('added_at', '')}"
                                if st.button("🗑️", key=del_key, help="이 보도자료 삭제"):
                                    all_press = _load_press_releases()
                                    all_press = [
                                        p for p in all_press
                                        if p.get("added_at") != article.get("added_at")
                                    ]
                                    _save_press_releases(all_press)
                                    st.cache_data.clear()
                                    st.rerun()
        else:
            st.info(
                "📂 등록된 보도자료가 없습니다.\n\n"
                "위 **'➕ 보도자료 추가하기'** 를 클릭하여 직접 입력하세요."
            )

        # ── 이전 보도자료 보기 토글 ────────────────────────────────────
        if press_hidden_count > 0:
            st.markdown("<br>", unsafe_allow_html=True)
            st.checkbox(
                f"📦 이전 보도자료 {press_hidden_count}건 함께 보기 (어제 이전 등록분)",
                key="show_old_press",
            )

    # ── 오른쪽: 국회 법안 ─────────────────────────────────────────────
    with col_law:
        st.markdown('<p class="section-title">🏛️ 국회 법안 동향 (신재생)</p>', unsafe_allow_html=True)
        # bills는 상단에서 이미 수집됨

        # raw_bills 수집 결과 상태 안내 (기간 필터 전 전체 건수)
        real_bill_count = sum(1 for b in raw_bills if not b.get("is_mock"))
        if real_bill_count > 0:
            st.caption(f"API 수집: {real_bill_count}건 | 기간 필터 후: {len(bills)}건")
        elif raw_bills and raw_bills[0].get("is_mock"):
            st.caption("⚠️ API 키 미설정 — Mock 데이터")

        if bills:
            is_mock_mode = any(b["is_mock"] for b in bills)
            if is_mock_mode:
                st.markdown(
                    "<div class='coming-card' style='margin-bottom:1rem;'>"
                    "<h4>🔑 API 키 미설정 — Mock 데이터 표시 중</h4>"
                    "<p><code>.env</code>에 <code>ASSEMBLY_API_KEY</code>를 설정하면 "
                    "실제 국회 법안 데이터로 자동 전환됩니다.<br>"
                    "발급: <a href='https://open.assembly.go.kr' target='_blank' "
                    "style='color:#00c9ff;'>open.assembly.go.kr</a> (무료)</p>"
                    "</div>",
                    unsafe_allow_html=True,
                )

            # 법안 상태별 색상 매핑
            status_colors = {
                "원안가결": "#64ffda",
                "수정가결": "#64ffda",
                "본회의 부의": "#92fe9d",
                "소위심사": "#ffc837",
                "심사중": "#8892b0",
                "부결": "#ff6b6b",
                "임기만료폐기": "#ff6b6b",
            }

            for bill in bills:
                mock_badge = " [MOCK]" if bill["is_mock"] else ""
                status_color = status_colors.get(bill["status"], "#8892b0")
                html_str = (
                    f'<div class="card" style="margin-bottom:0.6rem;">'
                    f'<p class="meta">📋 {bill["committee"]}{mock_badge} · {bill["propose_date"]}</p>'
                    f'<h4 style="font-size:0.9rem;"><a href="{bill["link"]}" target="_blank" style="color:#ccd6f6; text-decoration:none;">{bill["title"]}</a></h4>'
                    f'<p>👤 {bill["proposer"]}&nbsp;&nbsp;<span style="color:{status_color}; font-weight:700;">● {bill["status"]}</span></p>'
                    f'</div>'
                )
                st.markdown(html_str, unsafe_allow_html=True)
        else:
            st.info("수집된 법안이 없습니다.")

    # ── 유관 부처 홈페이지 안내 (하단) ──────────────────────────────────
    st.markdown("---")
    st.markdown(
        """<div class="coming-card">
            <h4>📋 유관 부처 보도자료 바로가기</h4>
            <ul>
                <li><b>⚡ 산업통상자원부</b> — 에너지·전력산업, 통상·산업 정책 보도자료
                    &nbsp;<a href="https://www.motie.go.kr/motie/ne/presse/press2/bbs/bbsList.do?bbs_seq_n=161" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🌿 기후에너지환경부</b> — 재생에너지 정책, 탄소중립, 환경규제 보도자료
                    &nbsp;<a href="https://www.me.go.kr/home/web/board/list.do?menuId=10525" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🌊 해양수산부</b> — 해상풍력, 공유수면, 어업·해양 정책 보도자료
                    &nbsp;<a href="https://www.mof.go.kr/newsroom/pressReleases.do" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🌾 농림축산식품부</b> — 농지전용, 농업진흥구역, 농촌개발 보도자료
                    &nbsp;<a href="https://www.mafra.go.kr/bbs/mafra/68/artcl/list.do" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🏗️ 국토교통부</b> — 개발행위허가, 도시계획, 용도지역 보도자료
                    &nbsp;<a href="https://www.molit.go.kr/USR/NEWS/m_71/lst.jsp?m=71" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
            </ul>
        </div>""",
        unsafe_allow_html=True,
    )


# =============================================
# TAB 4 : 유관기관 공지사항 (수동 입력 방식)
# =============================================

# _load_notices, _save_notices, _load_smp_rec, _save_smp_rec,
# _T4_ORG_DISPLAY, _NOTICES_FILE, _ATTACHMENTS_DIR, _SMP_REC_FILE 는
# 사이드바 이전 공통 헬퍼 섹션에 정의됨.

_T4_ORG_ICON = {
    "kpx":     "📊",
    "kemco":   "🌿",
    "kepco":   "⚡",
    "eleccom": "⚖️",
    "shinan":  "🌊",
    "jeonnam": "🏛️",
}
_T4_ORG_URL = {
    "kpx":     "https://www.kpx.or.kr",
    "kemco":   "https://www.energy.or.kr",
    "kepco":   "https://home.kepco.co.kr",
    "eleccom": "https://www.korec.go.kr",
    "shinan":  "https://www.shinan.go.kr",
    "jeonnam": "https://www.jeonnam.go.kr",
}

with tab4:
    st.markdown("### 📡 유관기관 공지사항")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "공공기관 보안(IP 차단·JS 렌더링)으로 자동 크롤링이 불가합니다. "
        "각 기관 홈페이지에서 직접 확인 후 <b>공지사항 추가하기</b> 폼으로 등록하면 영구 저장됩니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # ── 공지사항 데이터 로드 ─────────────────────────────────────────────
    all_notices = _load_notices()

    # ── 오늘(자정 기준) 일별 표시 필터 ──────────────────────────────────────
    # 오늘 00:00 KST 이후 등록분을 기본 표시합니다 (Google Sheets에 영구 보존).
    _now        = get_kst_now()
    _today_str  = _now.strftime("%Y-%m-%d")
    # added_at 형식이 "YYYY-MM-DDTHH:MM:SS"(수동) 또는 "YYYY-MM-DD HH:MM:SS"(RSS/Sheets 자동) 혼재
    # → startswith로 날짜 문자열 비교하여 형식 차이 무관하게 오늘 항목 필터
    _today_notices = [n for n in all_notices if n.get("added_at", "").startswith(_today_str)]
    archived_count = len(all_notices) - len(_today_notices)

    # "이전 공지사항 보기" 체크박스 토글 반영
    display_notices = all_notices if st.session_state.get("show_old_notices") else _today_notices

    # ── 상단 컨트롤: 기관 필터 + 전체 CSV 다운로드 ─────────────────────
    col_n_filter, col_n_dl = st.columns([3, 2])
    with col_n_filter:
        _T4_FILTER_OPTIONS = {"전체": None} | {v: k for k, v in _T4_ORG_DISPLAY.items()}
        selected_org_label = st.selectbox(
            "기관 선택",
            options=list(_T4_FILTER_OPTIONS.keys()),
            label_visibility="collapsed",
            key="notice_org_filter",
        )
        selected_org_key = _T4_FILTER_OPTIONS[selected_org_label]

    with col_n_dl:
        # 전체 CSV 다운로드 — 보관 포함 all_notices 기준 (항상 표시)
        dl_notices = [n for n in all_notices if not selected_org_key or n["org_key"] == selected_org_key]
        today_str  = get_kst_now().strftime("%Y-%m-%d")
        dl_df_all  = pd.DataFrame([{
            "기관명":   _T4_ORG_DISPLAY.get(n["org_key"], n["org_key"]),
            "카테고리": n.get("category", ""),
            "제목":     n["title"],
            "날짜":     n["date"],
            "링크":     n["link"],
            "등록일시":  n.get("added_at", ""),
        } for n in dl_notices]) if dl_notices else pd.DataFrame()
        st.download_button(
            label="📥 유관기관 공지 전체 CSV 다운로드",
            data=to_csv_bytes(dl_df_all) if not dl_df_all.empty else b"",
            file_name=f"{today_str}_유관기관공지사항.csv",
            mime="text/csv",
            use_container_width=True,
            key="dl_all_notices",
            disabled=dl_df_all.empty,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # KPI 행
    filtered_for_kpi = [n for n in display_notices if not selected_org_key or n["org_key"] == selected_org_key]
    kpi_cols = st.columns(4)
    kpi_data_n = [
        ("📋", str(len(filtered_for_kpi)), "등록된 공지"),
        ("🏢", str(len(set(n["org_key"] for n in display_notices))), "등록 기관 수"),
        ("📅", filtered_for_kpi[0]["date"] if filtered_for_kpi else "—", "최신 공지 날짜"),
        ("🔗", "6개", "연동 기관"),
    ]
    for col, (icon, value, label) in zip(kpi_cols, kpi_data_n):
        with col:
            st.markdown(
                f"""<div class="kpi-card">
                    <div style="font-size:1.4rem;">{icon}</div>
                    <div class="value" style="font-size:1.1rem;">{value}</div>
                    <div class="label">{label}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── SMP/REC 데이터 로드 및 UI ────────────────────────────────────────────────
    smp_records = _load_smp_rec()
    
    st.markdown('<p class="section-title">📉 전력거래소(KPX) SMP 및 REC 단가 추이</p>', unsafe_allow_html=True)
    with st.expander("➕ 단가 수동 입력하기", expanded=False):
        c_sr_d, c_sr_smp, c_sr_rec, c_sr_btn = st.columns([2, 2, 2, 1])
        with c_sr_d:
            smp_date = st.date_input("기준 일자", key="smp_date")
        with c_sr_smp:
            smp_val = st.number_input("육지 SMP (원/kWh)", min_value=0.0, step=0.1, format="%.2f", key="smp_val")
        with c_sr_rec:
            rec_val = st.number_input("육지 REC (원/REC)", min_value=0.0, step=0.01, format="%.2f", key="rec_val")
        with c_sr_btn:
            st.markdown("<div style='margin-top:1.6rem;'></div>", unsafe_allow_html=True)
            if st.button("✅ 저장"):
                date_str = smp_date.strftime("%Y-%m-%d")
                # Remove exact duplicate date if exists, then append
                smp_records = [r for r in smp_records if r["date"] != date_str]
                smp_records.append({
                    "date": date_str,
                    "SMP": smp_val,
                    "REC": rec_val
                })
                smp_records.sort(key=lambda x: x["date"], reverse=True)
                _save_smp_rec(smp_records)
                st.rerun()
                
    if smp_records:
        # 차트용 데이터프레임
        sr_df = pd.DataFrame(smp_records)
        sr_df["date"] = pd.to_datetime(sr_df["date"])
        sr_df = sr_df.sort_values("date")
        
        c_ch_opt, c_ch_dl = st.columns([4, 1])
        with c_ch_opt:
            chart_period = st.radio("그래프 표시 기간", ["1주일", "1개월", "1년", "전체"], horizontal=True, key="sr_period")
        
        # 필터링
        if chart_period != "전체":
            if chart_period == "1주일":
                ch_cutoff = get_kst_now() - timedelta(days=7)
            elif chart_period == "1개월":
                ch_cutoff = get_kst_now() - timedelta(days=30)
            elif chart_period == "1년":
                ch_cutoff = get_kst_now() - timedelta(days=365)
            # Timezone aware comparison fix
            ch_cutoff = ch_cutoff.replace(tzinfo=None)
            filtered_sr = sr_df[sr_df["date"] >= ch_cutoff]
        else:
            filtered_sr = sr_df
            
        with c_ch_dl:
            # SMP/REC 전용 CSV 다운로드
            st.markdown("<div style='margin-top:0.5rem;'></div>", unsafe_allow_html=True)
            dl_sr_df = filtered_sr.copy()
            dl_sr_df["date"] = dl_sr_df["date"].dt.strftime("%Y-%m-%d")
            today_str = get_kst_now().strftime("%Y-%m-%d")
            st.download_button(
                label="📥 필터링된 기간 CSV",
                data=to_csv_bytes(dl_sr_df),
                file_name=f"{today_str}_SMP_REC_단가.csv",
                mime="text/csv",
                use_container_width=True,
                key="dl_sr_notices",
            )
            
        if not filtered_sr.empty:
            # x축을 날짜 문자열로 변환 — datetime 인덱스 사용 시 시간까지 표시되는 문제 방지
            _chart_df = filtered_sr.copy()
            _chart_df["date"] = _chart_df["date"].dt.strftime("%Y-%m-%d")
            st.line_chart(_chart_df.set_index("date")[["SMP", "REC"]], use_container_width=True)
        else:
            st.info("해당 기간에 등록된 단가 데이터가 없습니다.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 공지사항 추가 폼 ────────────────────────────────────────────────
    with st.expander("➕ 공지사항 추가하기", expanded=False):
        st.markdown(
            "<p style='color:#8892b0; font-size:0.85rem;'>"
            "각 기관 홈페이지에서 공지를 확인한 후 아래 폼에 입력하세요. "
            "입력한 내용은 서버에 영구 저장됩니다.</p>",
            unsafe_allow_html=True,
        )
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            f_org = st.selectbox(
                "기관 선택",
                options=list(_T4_ORG_DISPLAY.values()),
                key="form_org",
            )
            f_category = st.selectbox(
                "카테고리",
                options=["공지", "고시", "보도", "참고"],
                key="form_category",
            )
            f_date = st.date_input("날짜", key="form_date")
        with f_col2:
            f_title = st.text_input(
                "제목 *",
                placeholder="공지 제목을 입력하세요",
                key="form_title",
            )
            f_link = st.text_input(
                "원문 링크 URL (없으면 빈칸)",
                placeholder="https://",
                key="form_link",
            )
            f_files = st.file_uploader(
                "첨부파일 (PDF·HWP·DOCX·XLSX·PNG·JPG 등, 복수 선택 가능)",
                accept_multiple_files=True,
                key="form_files",
            )

        if st.button("✅ 추가", key="form_submit", use_container_width=False):
            if not f_title.strip():
                st.error("제목을 입력해 주세요.")
            else:
                # org_key 역방향 조회 (선택된 기관 display name으로 매핑)
                f_org_key = "etc"
                for k, v in _T4_ORG_DISPLAY.items():
                    if v == f_org:
                        f_org_key = k
                        break
                
                added_at  = get_kst_now().strftime("%Y-%m-%dT%H:%M:%S")

                # 첨부파일 저장
                saved_files = []
                for uf in (f_files or []):
                    # 타임스탬프 prefix로 파일명 충돌 방지
                    safe_name = added_at.replace(":", "-") + "_" + uf.name
                    save_path = _ATTACHMENTS_DIR / safe_name
                    save_path.write_bytes(uf.read())
                    saved_files.append({"name": uf.name, "saved": safe_name})

                new_entry = {
                    "org_key":     f_org_key,
                    "category":    f_category,
                    "title":       f_title.strip(),
                    "date":        f_date.strftime("%Y-%m-%d"),
                    "link":        f_link.strip(),
                    "attachments": saved_files,
                    "added_at":    added_at,
                }
                all_notices.insert(0, new_entry)   # 최신 순 맨 앞에 삽입
                _save_notices(all_notices)
                att_msg = f" (첨부 {len(saved_files)}개)" if saved_files else ""
                st.success(f"✅ 공지사항이 등록되었습니다: {f_title.strip()}{att_msg}")
                st.rerun()

    # ── 기관별 기관 홈 링크 + 공지 카드 ────────────────────────────────
    org_keys_to_show = [selected_org_key] if selected_org_key else list(_T4_ORG_DISPLAY.keys())

    for org_key in org_keys_to_show:
        org_notices = [n for n in display_notices if n["org_key"] == org_key]
        icon     = _T4_ORG_ICON.get(org_key, "🏢")
        org_name = _T4_ORG_DISPLAY.get(org_key, org_key)
        org_url  = _T4_ORG_URL.get(org_key, "")

        with st.expander(f"{icon} {org_name}  ({len(org_notices)}건)", expanded=bool(org_notices)):
            # 기관 홈페이지 바로가기
            if org_url:
                st.markdown(
                    f'<a href="{org_url}" target="_blank" style="'
                    f'display:inline-block; margin-bottom:0.7rem; padding:0.3rem 0.9rem; '
                    f'background:rgba(100,255,218,0.1); border:1px solid rgba(100,255,218,0.3); '
                    f'border-radius:8px; color:#64ffda; font-size:0.82rem; text-decoration:none;">'
                    f'🔗 {org_name} 공식 홈페이지 바로가기 ↗</a>',
                    unsafe_allow_html=True,
                )

            if not org_notices:
                st.info("등록된 공지가 없습니다. 위 '공지사항 추가하기'로 직접 입력하세요.")
                continue

            with st.container(height=400):
                for idx, notice in enumerate(org_notices):
                    # 삭제 버튼 + 카드 (두 열 레이아웃)
                    c_card, c_del = st.columns([10, 1])
                    with c_card:
                        # 제목 링크: URL 있으면 하이퍼링크, 없으면 일반 텍스트
                        title_html = (
                            f'<a href="{notice["link"]}" target="_blank" '
                            f'style="color:#ccd6f6; text-decoration:none;">{notice["title"]}</a>'
                            if notice.get("link")
                            else f'<span style="color:#ccd6f6;">{notice["title"]}</span>'
                        )
                        # 첨부파일 뱃지 표시
                        att_list = notice.get("attachments", [])
                        att_badge = (
                            f' &nbsp;<span style="color:#64ffda; font-size:0.78rem;">📎 {len(att_list)}개</span>'
                            if att_list else ""
                        )
                        html_str = (
                            f'<div class="card" style="margin-bottom:0.4rem;">'
                            f'<p class="meta">{icon} {org_name} &nbsp;·&nbsp; {notice.get("category","공지")} &nbsp;·&nbsp; {notice["date"]}{att_badge}</p>'
                            f'<h4 style="font-size:0.92rem;">{title_html}</h4>'
                            f'</div>'
                        )
                        st.markdown(html_str, unsafe_allow_html=True)
                        # 첨부파일 개별 다운로드 버튼
                        for att in att_list:
                            att_path = _ATTACHMENTS_DIR / att["saved"]
                            if att_path.exists():
                                st.download_button(
                                    label=f"📎 {att['name']}",
                                    data=att_path.read_bytes(),
                                    file_name=att["name"],
                                    key=f"att_{notice.get('added_at','')}_{att['saved']}",
                                )
                    with c_del:
                        # 삭제 버튼 — org_key + added_at 조합으로 고유 키 생성
                        del_key = f"del_{org_key}_{notice.get('added_at','')}"
                        if st.button("🗑️", key=del_key, help="이 공지 삭제"):
                            # added_at 기준 삭제 — org_key+title+date 조합은 중복 공지 2건 모두 삭제될 수 있음
                            all_notices = [
                                n for n in all_notices
                                if n.get("added_at") != notice.get("added_at")
                            ]
                            _save_notices(all_notices)
                            st.rerun()

    # ── 이전 공지사항 보기 토글 ──────────────────────────────────────────
    if archived_count > 0:
        st.markdown("<br>", unsafe_allow_html=True)
        st.checkbox(
            f"📦 이전 공지사항 {archived_count}건 함께 보기 (어제 이전 등록분)",
            key="show_old_notices",
        )

    # ── 기관 홈페이지 안내 (하단) ────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        """<div class="coming-card">
            <h4>📋 유관기관 홈페이지 바로가기</h4>
            <ul>
                <li><b>📊 KPX (전력거래소)</b> — SMP 산정 결과, 재생에너지 입찰공고
                    &nbsp;<a href="https://www.kpx.or.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🌿 한국에너지공단</b> — RPS 의무량, REC 발급 기준, 보조금 공모
                    &nbsp;<a href="https://www.energy.or.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>⚡ 한전 (KEPCO)</b> — 계통 연계 기술기준, 전기공급약관, 접속 신청
                    &nbsp;<a href="https://home.kepco.co.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>⚖️ 전기위원회</b> — 발전사업 허가·심의 결과, 허가 기준 개정
                    &nbsp;<a href="https://www.korec.go.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🌊 신안군청</b> — 해상풍력 고시·공고, 이익공유, 공유수면 허가
                    &nbsp;<a href="https://www.shinan.go.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
                <li><b>🏛️ 전남도청</b> — 해상풍력 단지 지정, 인허가 지원, 환경영향평가 고시
                    &nbsp;<a href="https://www.jeonnam.go.kr" target="_blank" style="color:#64ffda; font-size:0.78rem;">🔗 바로가기</a></li>
            </ul>
        </div>""",
        unsafe_allow_html=True,
    )
