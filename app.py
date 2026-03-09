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
    # 뉴스 크롤러: "2026-03-06 14:30" 형식 (날짜+시간)
    # RSS 크롤러:  "2026-03-06" 형식 (날짜만) → 두 형식 모두 지원
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
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
    '수소', '출력제어', '전력계통', '신재생', 'PPA', 'REC',
)
_ENERGY_PUBLISHERS = ("전기신문", "에너지경제", "일렉트릭파워")
_KEYWORD_ICONS = {
    '해상풍력': '🌊', '해상풍력설치선': '🚢', 'WTIV': '🏗️', '하부설치선': '⚓',
    '풍력': '💨', '태양광': '☀️', 'ESS': '🔋',
    'BESS': '🔋', '분산에너지': '⚡', '수소': '💧', '출력제어': '🎛️',
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
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_policy_rss() -> list[dict]:
    """부처 보도자료 RSS 수집 (1시간 캐시). 실패 시 Dummy 반환.
    첨부파일 수집은 별도 캐시 함수에서 처리 — RSS 기사 수집과 분리해 Cloud 타임아웃 방지.
    """
    return fetch_rss_articles(filter_energy=True, fetch_attachments=False)


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
    /* 전체 배경 */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #1a1a3e 50%, #24243e 100%);
    }

    /* 상단 헤더 */
    .main-header {
        background: linear-gradient(90deg, #00c9ff 0%, #92fe9d 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.2rem;
        font-weight: 800;
        text-align: center;
        padding: 0.5rem 0 0.2rem 0;
        letter-spacing: -0.5px;
    }
    .sub-header {
        text-align: center;
        color: #8892b0;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        justify-content: center;
        background-color: rgba(255,255,255,0.03);
        border-radius: 12px;
        padding: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 10px 24px;
        font-weight: 600;
        color: #ccd6f6;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #00c9ff 0%, #92fe9d 100%);
        color: #0f0c29 !important;
        font-weight: 700;
    }

    /* 일반 카드 */
    .card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        backdrop-filter: blur(10px);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0,201,255,0.15);
    }
    .card h4 { color: #ccd6f6; margin-bottom: 0.4rem; }
    .card p  { color: #8892b0; font-size: 0.9rem; line-height: 1.6; }
    .card .meta { color: #64ffda; font-size: 0.78rem; margin-bottom: 0.3rem; }

    /* 예정 기능 안내 카드 (Coming Soon) */
    .coming-card {
        background: rgba(0,201,255,0.04);
        border: 1px dashed rgba(0,201,255,0.25);
        border-radius: 16px;
        padding: 1.6rem 2rem;
        margin-bottom: 1rem;
    }
    .coming-card h4 { color: #00c9ff; margin-bottom: 0.5rem; font-size: 1rem; }
    .coming-card p  { color: #8892b0; font-size: 0.88rem; line-height: 1.6; margin: 0; }
    .coming-card ul { color: #8892b0; font-size: 0.88rem; line-height: 1.8; padding-left: 1.2rem; margin: 0.4rem 0 0 0; }

    /* KPI 카드 */
    .kpi-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .kpi-card .value {
        font-size: 1.9rem;
        font-weight: 800;
        background: linear-gradient(135deg, #00c9ff, #92fe9d);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .kpi-card .label { color: #8892b0; font-size: 0.82rem; margin-top: 0.3rem; }

    /* 섹션 구분선 */
    .section-title {
        color: #ccd6f6;
        font-size: 1.05rem;
        font-weight: 700;
        margin: 1.4rem 0 0.6rem 0;
        padding-bottom: 0.4rem;
        border-bottom: 1px solid rgba(255,255,255,0.07);
    }

    /* 배지 */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .badge-ready   { background: rgba(100,255,218,0.15); color: #64ffda; }
    .badge-pending { background: rgba(255,200,55,0.15);  color: #ffc837; }
    .badge-plan    { background: rgba(0,201,255,0.12);   color: #00c9ff; }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background: rgba(15,12,41,0.95);
        border-right: 1px solid rgba(255,255,255,0.06);
    }

    /* 버튼 */
    .stButton>button {
        background: linear-gradient(135deg, #00c9ff 0%, #92fe9d 100%);
        color: #0f0c29;
        border: none;
        border-radius: 10px;
        font-weight: 700;
        padding: 0.5rem 1.5rem;
        transition: opacity 0.2s;
    }
    .stButton>button:hover { opacity: 0.85; }

    /* 검색 인풋 */
    .stTextInput>div>div>input {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px;
        color: #ccd6f6;
    }

    /* ── 익스팬더 공통 (Tab 1~4 전체 적용) ── */
    [data-testid="stExpander"] {
        background: rgba(20,18,50,0.95) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        margin-bottom: 0.4rem;
    }
    [data-testid="stExpander"] summary {
        padding: 0.75rem 1rem;
        border-radius: 12px;
        background: rgba(20,18,50,0.95) !important;
    }
    /* 열린 상태에서도 배경 어둡게 유지 */
    details[open],
    details[open] > summary {
        background: rgba(20,18,50,0.95) !important;
    }
    details[open] > summary {
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    /* 닫힘/열림 모두 타이틀 색상 보장 */
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span,
    details[open] > summary p,
    details[open] > summary span {
        color: #e2e8f0 !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
    }
    [data-testid="stExpander"] summary svg {
        fill: #64ffda !important;
    }
    [data-testid="stExpander"] summary:hover p,
    [data-testid="stExpander"] summary:hover span {
        color: #00c9ff !important;
    }

    /* ── 익스팬더 내부 본문 전체 텍스트 가시성 (Tab 1~4) ── */
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"],
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] li,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] strong,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] em,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] h1,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] h2,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] h3,
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] h4 {
        color: #ccd6f6 !important;
    }

    /* ── 탭 전체 일반 텍스트 (st.write, st.markdown 등) ── */
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span {
        color: #ccd6f6;
    }

    /* ── 폼 요소 레이블 ── */
    .stSelectbox label,
    .stRadio label,
    .stCheckbox label,
    .stTextInput label,
    .stDateInput label,
    .stNumberInput label {
        color: #ccd6f6 !important;
    }

    /* ── 셀렉트박스 다크 테마 ── */
    [data-testid="stSelectbox"] > div > div {
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: 10px !important;
        color: #ccd6f6 !important;
    }
    [data-testid="stSelectbox"] > div > div > div {
        color: #ccd6f6 !important;
    }
    /* 셀렉트박스 드롭다운 메뉴 */
    [data-testid="stSelectbox"] ul {
        background: #1a1a3e !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
    }
    [data-testid="stSelectbox"] li {
        color: #ccd6f6 !important;
    }
    [data-testid="stSelectbox"] li:hover {
        background: rgba(0,201,255,0.15) !important;
    }

    /* ── 라디오 버튼 다크 테마 ── */
    [data-testid="stRadio"] > div {
        background: transparent !important;
    }
    [data-testid="stRadio"] label {
        color: #ccd6f6 !important;
    }
    [data-testid="stRadio"] span {
        color: #ccd6f6 !important;
    }

    /* ── 2차 버튼 (갱신·CSV 다운로드 등 흰 배경 버튼) 다크 테마 ── */
    [data-testid="stDownloadButton"] > button,
    [data-testid="stFormSubmitButton"] > button {
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.15) !important;
        color: #ccd6f6 !important;
        border-radius: 10px !important;
    }
    [data-testid="stDownloadButton"] > button:hover,
    [data-testid="stFormSubmitButton"] > button:hover {
        background: rgba(255,255,255,0.12) !important;
        color: #00c9ff !important;
    }

    /* ── 메트릭 (st.metric) ── */
    [data-testid="stMetricLabel"] { color: #8892b0 !important; }
    [data-testid="stMetricValue"] { color: #ccd6f6 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 공지사항 / SMP/REC 헬퍼 (사이드바 + Tab 4 공통 사용)
# ─────────────────────────────────────────────
import json as _json

_NOTICES_FILE    = Path(__file__).parent / "data" / "notices.json"
_ATTACHMENTS_DIR = Path(__file__).parent / "data" / "attachments"
_SMP_REC_FILE    = Path(__file__).parent / "data" / "smp_rec.json"
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


def _load_notices() -> list[dict]:
    """data/notices.json 에서 공지사항 목록을 로드합니다."""
    if _NOTICES_FILE.exists():
        try:
            return _json.loads(_NOTICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_notices(notices: list[dict]) -> None:
    """공지사항 목록을 data/notices.json 에 저장합니다."""
    _NOTICES_FILE.write_text(_json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_smp_rec() -> list[dict]:
    """data/smp_rec.json 에서 SMP/REC 기록을 로드합니다."""
    if _SMP_REC_FILE.exists():
        try:
            return _json.loads(_SMP_REC_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_smp_rec(records: list[dict]) -> None:
    """SMP/REC 기록을 data/smp_rec.json 에 저장합니다."""
    _SMP_REC_FILE.write_text(_json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


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
        "탭2·탭3·탭4 선택 기간의 데이터를 하나의 CSV로 통합합니다.</p>",
        unsafe_allow_html=True,
    )

    # 기간 필터 — 탭3 선택값 반영, 기본 "최근 3일"
    _rpt_period  = st.session_state.get("policy_period", "최근 3일")
    _rpt_cutoff  = get_kst_now() - _PERIOD_DELTA.get(_rpt_period, timedelta(hours=72))
    _rpt_today   = get_kst_now().date()
    _rpt_930_str = datetime.combine(_rpt_today, dtime(9, 30)).strftime("%Y-%m-%dT%H:%M:%S")

    # 뉴스 (Tab 2) — 탭2 기간 선택값 반영
    _rpt_news_period = st.session_state.get("period_filter", "최근 3일")
    _rpt_news_cutoff = get_kst_now() - _PERIOD_DELTA.get(_rpt_news_period, timedelta(hours=72))
    try:
        _rpt_news_raw = _fetch_all_keyword_news(_KEYWORDS)
    except Exception:
        _rpt_news_raw = {}
    _rpt_rows = []
    for _kw in _KEYWORDS:
        for _n in _rpt_news_raw.get(_kw, []):
            if _safe_parse_dt(_n.get("date", "")) >= _rpt_news_cutoff:
                _rpt_rows.append({
                    "구분": "뉴스", "날짜": _n.get("date", ""),
                    "출처": _n.get("source", ""), "키워드": _kw,
                    "제목": _n.get("title", ""), "요약": _n.get("summary", ""),
                    "링크": _n.get("link", ""),
                })

    # 보도자료 (Tab 3 RSS) — 탭3 기간 필터 동일 적용
    for _a in _fetch_policy_rss():
        if not _a.get("is_dummy") and _safe_parse_dt(_a.get("date", "")) >= _rpt_cutoff:
            _rpt_rows.append({
                "구분": "보도자료", "날짜": _a.get("date", ""),
                "출처": _a.get("source", ""), "키워드": "",
                "제목": _a.get("title", ""), "요약": _a.get("summary", ""),
                "링크": _a.get("link", ""),
            })

    # 국회 법안 (Tab 3) — 탭3 기간 필터 동일 적용
    for _b in _fetch_assembly_bills():
        if not _b.get("is_mock") and _safe_parse_dt(_b.get("propose_date", "")) >= _rpt_cutoff:
            _rpt_rows.append({
                "구분": "국회법안", "날짜": _b.get("propose_date", ""),
                "출처": _b.get("committee", ""), "키워드": "",
                "제목": _b.get("title", ""),
                "요약": f"{_b.get('proposer','')} | {_b.get('status','')}",
                "링크": _b.get("link", ""),
            })

    # 공지사항 (Tab 4) — JSON에서 로드 (9:30 이후 등록분)
    for _nc in _load_notices():
        if _nc.get("added_at", "") >= _rpt_930_str:
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

    st.markdown("---")
    st.markdown(
        "<p style='color:#8892b0; font-size:0.8rem;'>"
        "신재생에너지 사업개발팀<br>사내 대시보드 v0.7.0</p>",
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
                st.error(f"❌ 검색 오류: {search_error}")

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
        _today_str = datetime.today().strftime("%Y-%m-%d")
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
            ("수소",),
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
                    display_name = "해상풍력 동향 (WTIV·설치선 포함)"
                    icon = "🌊"
                elif "ESS" in kw_group:
                    display_name = "ESS/BESS 동향"
                    icon = "🔋"
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
        "유관 부처 보도자료(RSS)와 국회 법안(오픈 API)을 자동 수집합니다. "
        "국회 API 키 미설정 시 Mock 데이터가 표시됩니다."
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
            "RSS 1시간 캐시 · 법안 6시간 캐시 · "
            "<code>ASSEMBLY_API_KEY</code> 설정 시 실서버 전환</p>",
            unsafe_allow_html=True,
        )

    # ── 데이터 사전 수집 (통합 CSV용) ─────────────────────────────────
    with st.spinner("데이터 수집 중…"):
        raw_rss_articles = _fetch_policy_rss()
        rss_articles     = _filter_by_period(raw_rss_articles, policy_period, date_key="date")
        raw_bills        = _fetch_assembly_bills()
        bills            = _filter_by_period(raw_bills, policy_period, date_key="propose_date")

    # ── 통합 CSV 다운로드 버튼 (Tab 2와 동일한 방식 — 상단 1개) ──────
    today_str = get_kst_now().strftime("%Y-%m-%d")
    rss_rows = [{
        "구분": "보도자료",
        "날짜": a.get("date", ""),
        "출처": a.get("source", ""),
        "제목": a.get("title", ""),
        "요약": a.get("summary", ""),
        "링크": a.get("link", ""),
    } for a in rss_articles if not a.get("is_dummy")]
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

    # ── 왼쪽: 부처 보도자료 RSS ────────────────────────────────────────
    with col_rss:
        st.markdown('<p class="section-title">📢 유관 부처 보도자료 (RSS)</p>', unsafe_allow_html=True)

        if rss_articles:
            
            # 부처별로 그룹핑해서 Expander로 표시
            dept_groups: dict[str, list] = {}
            for article in rss_articles:
                dept = article["source"]
                dept_groups.setdefault(dept, []).append(article)

            dept_icons = {
                "산업부": "⚡",   # 산업통상부 (구 산업통상자원부)
                "기후부": "🌿",   # 기후에너지환경부
                "해수부": "🌊",   # 해양수산부
            }

            for dept, articles in dept_groups.items():
                icon = dept_icons.get(dept, "🏛️")
                has_dummy = any(a["is_dummy"] for a in articles)
                dummy_badge = " <span style='color:#ffc837; font-size:0.75rem;'>[연결 준비 중]</span>" if has_dummy else ""

                with st.expander(f"{icon} {dept}  ({len(articles)}건)", expanded=True):
                    # ── Gemini AI 동향 분석 버튼 ──────────────────────
                    rss_btn_key    = f"analyze_rss_{dept}"
                    rss_result_key = f"rss_analysis_{dept}"
                    col_rss_ai, col_rss_space = st.columns([2, 5])
                    with col_rss_ai:
                        if st.button("🤖 Gemini AI 동향 분석", key=rss_btn_key, use_container_width=True):
                            news_for_ai = [
                                {"title": a["title"], "summary": a["summary"],
                                 "source": a["source"], "date": a["date"]}
                                for a in articles if not a.get("is_dummy")
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
                            if article["is_dummy"]:
                                html_str = (
                                    f'<div class="coming-card" style="margin-bottom:0.5rem;">'
                                    f'<p class="meta" style="color:#ffc837;">🔧 {article["source"]} · {article["date"]}</p>'
                                    f'<h4 style="color:#ffc837; font-size:0.9rem;">{article["title"]}</h4>'
                                    f'<p>{article["summary"]}</p>'
                                    f'</div>'
                                )
                                st.markdown(html_str, unsafe_allow_html=True)
                            else:
                                # 첨부파일: 개별 캐시 함수로 분리 호출 (RSS 수집과 독립)
                                attachments = _fetch_attachments_cached(article["link"])
                                att_html = ""
                                if attachments:
                                    att_links = "".join(
                                        f'<a href="{att["url"]}" target="_blank" '
                                        f'style="display:inline-block; margin:0.3rem 0.4rem 0 0; padding:0.25rem 0.6rem; '
                                        f'background:rgba(100,255,218,0.1); border:1px solid rgba(100,255,218,0.25); '
                                        f'border-radius:6px; color:#64ffda; font-size:0.75rem; text-decoration:none; '
                                        f'transition:all 0.2s ease;">'
                                        f'📎 {att["name"][:40]}</a>'
                                        for att in attachments
                                    )
                                    att_html = (
                                        f'<div style="margin-top:0.8rem; padding-top:0.6rem; border-top:1px dashed rgba(255,255,255,0.1);">'
                                        f'<span style="font-size:0.75rem; color:#8892b0; display:block;">⬇️ 첨부파일 다운로드</span>'
                                        f'{att_links}</div>'
                                    )

                                html_str = (
                                    f'<div class="card" style="margin-bottom:0.5rem;">'
                                    f'<p class="meta">🏢 {article["source"]} · {article["date"]}</p>'
                                    f'<h4 style="font-size:0.92rem;"><a href="{article["link"]}" target="_blank" style="color:#ccd6f6; text-decoration:none;">{article["title"]}</a></h4>'
                                    f'<p>{article["summary"][:120]}…</p>'
                                    f'{att_html}'
                                    f'</div>'
                                )
                                st.markdown(html_str, unsafe_allow_html=True)
        else:
            st.info("수집된 보도자료가 없습니다.")

    # ── 오른쪽: 국회 법안 ─────────────────────────────────────────────
    with col_law:
        st.markdown('<p class="section-title">🏛️ 국회 법안 동향 (신재생)</p>', unsafe_allow_html=True)
        # bills는 상단에서 이미 수집됨

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

    # ── 9:30 AM 일별 표시 필터 ───────────────────────────────────────────
    # 오전 9:30 이전에 등록된 공지는 대시보드에서 숨깁니다.
    # data/notices.json과 data/attachments/에는 영구 보존됩니다.
    _now = get_kst_now()
    _today_930 = datetime.combine(_now.date(), dtime(9, 30))
    _display_cutoff = _today_930 if _now >= _today_930 else _today_930 - timedelta(days=1)
    _cutoff_str     = _display_cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    display_notices = [n for n in all_notices if n.get("added_at", "") >= _cutoff_str]
    archived_count  = len(all_notices) - len(display_notices)

    if archived_count > 0:
        st.info(
            f"📦 오전 9:30 이전 공지 **{archived_count}건**은 보관 처리되어 숨겨졌습니다. "
            f"(data/notices.json에 영구 저장됨)"
        )

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
            rec_val = st.number_input("육지 REC (원/REC)", min_value=0.0, step=100.0, format="%.0f", key="rec_val")
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
            st.line_chart(filtered_sr.set_index("date")[["SMP", "REC"]], use_container_width=True)
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
                            all_notices = [
                                n for n in all_notices
                                if not (n["org_key"] == notice["org_key"]
                                        and n["title"] == notice["title"]
                                        and n["date"] == notice["date"])
                            ]
                            _save_notices(all_notices)
                            st.rerun()

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
