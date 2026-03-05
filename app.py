"""
신재생에너지 사업개발팀 - 사내 대시보드
=============================================
- Tab 1: 입지/규제 분석      (국가법령정보센터 API + Claude AI)
- Tab 2: 일일 뉴스 모니터링   (네이버 뉴스 API)
- Tab 3: 정책 및 입법 동향    (국회 API + 중앙부처 RSS)
- Tab 4: 유관기관 공지사항    (한전, KPX, 지자체 크롤링)
"""

import sys
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from utils.news_crawler import search_naver_news, save_to_archive, to_csv_bytes

# execution/ 디렉토리를 Python 경로에 추가
# app.py와 같은 레벨의 execution/ 폴더에서 스크립트를 import하기 위함
sys.path.insert(0, str(Path(__file__).parent / "execution"))
from rss_crawler import fetch_rss_articles
from law_api import fetch_all_bills

load_dotenv()

_PERIOD_DELTA = {
    "최근 2일(어제~오늘)": timedelta(hours=48),
    "1주일": timedelta(weeks=1),
    "1개월": timedelta(days=30),
    "1년": timedelta(days=365),
}


def _safe_parse_dt(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except Exception:
        return datetime.min


def _filter_by_period(items: list, period: str) -> list:
    """기사 리스트를 선택 기간으로 필터링합니다."""
    if period == "전체":
        return items
    cutoff = datetime.now() - _PERIOD_DELTA.get(period, timedelta(hours=48))
    return [
        item for item in items
        if _safe_parse_dt(item.get("date", "")) >= cutoff
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
    """부처 보도자료 RSS 수집 (1시간 캐시). 실패 시 Dummy 반환."""
    return fetch_rss_articles(filter_energy=True)


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_assembly_bills() -> list[dict]:
    """국회 법안 수집 (6시간 캐시). API 키 없으면 Mock 반환."""
    return fetch_all_bills()


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

    /* 익스팬더 (키워드별 뉴스 브리핑) */
    [data-testid="stExpander"] {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        margin-bottom: 0.4rem;
    }
    [data-testid="stExpander"] summary {
        padding: 0.75rem 1rem;
        border-radius: 12px;
    }
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span {
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
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ 대시보드 설정")
    st.markdown("---")

    st.markdown("**API 연동 현황**")
    api_status = [
        ("badge-pending", "● 국가법령정보센터 API"),
        ("badge-pending", "● Claude AI"),
        ("badge-ready",   "● 네이버 뉴스 API"),
        ("badge-plan",    "● 국회 열린국회 API"),
        ("badge-plan",    "● 중앙부처 RSS"),
        ("badge-plan",    "● 한전/KPX 크롤러"),
    ]
    for cls, label in api_status:
        st.markdown(f'<span class="badge {cls}">{label}</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        "<p style='color:#8892b0; font-size:0.8rem;'>"
        "신재생에너지 사업개발팀<br>사내 대시보드 v0.2.0</p>",
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
    st.markdown("### 📜 지자체 조례 · 입지 규제 분석")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "국가법령정보센터 API로 지자체 조례를 검색하고, Claude AI가 핵심 규제 사항을 자동 분석합니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # KPI 행
    kpi_cols = st.columns(4)
    kpis = [
        ("🏛️", "연동 대기", "법령 API"),
        ("📋", "—", "분석 완료 조례"),
        ("🤖", "연동 대기", "Claude 분석"),
        ("⚠️", "—", "규제 알림"),
    ]
    for col, (icon, value, label) in zip(kpi_cols, kpis):
        with col:
            st.markdown(
                f"""<div class="kpi-card">
                    <div style="font-size:1.4rem;">{icon}</div>
                    <div class="value">{value}</div>
                    <div class="label">{label}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # 검색 영역
    col_q, col_btn = st.columns([4, 1])
    with col_q:
        search_query = st.text_input(
            "검색어",
            placeholder="예: 태양광 이격거리, 풍력 소음 기준, 농지 전용 …",
            label_visibility="collapsed",
        )
    with col_btn:
        st.button("🔍 검색", use_container_width=True)

    # 예정 기능 안내
    st.markdown(
        """<div class="coming-card">
            <h4>🚀 연동 예정 기능</h4>
            <ul>
                <li><b>국가법령정보센터 API</b> — 조례 키워드 검색 및 원문 조회</li>
                <li><b>Claude AI 자동 분석</b> — 이격거리·소음·농지 전용 등 핵심 규제 항목 요약</li>
                <li><b>지자체별 필터</b> — 전라남도, 경상남도, 제주도 등 권역별 비교</li>
                <li><b>규제 변경 알림</b> — 검색 조례 개정 시 자동 알림</li>
            </ul>
            <p style="margin-top:0.6rem;">✅ 준비 사항: <code>.env</code>에 <code>LAW_API_KEY</code>와 <code>ANTHROPIC_API_KEY</code> 설정</p>
        </div>""",
        unsafe_allow_html=True,
    )

    # 결과 영역 Mock
    st.markdown('<p class="section-title">검색 결과 (샘플 레이아웃)</p>', unsafe_allow_html=True)
    mock_laws = [
        ("전라남도 신안군 태양광발전시설 설치 및 관리 조례", "신안군", "2025-11-01", "이격거리 100m, 농지 전용 제한"),
        ("전남 진도군 풍력발전시설 설치 기준 조례", "진도군", "2025-08-15", "소음 기준 45dB, 민가 이격 300m"),
        ("전라남도 ESS 설치 안전 관리 조례", "전라남도", "2025-06-20", "소방법 병행 적용, 분리 설치 의무"),
    ]
    for title, org, date, summary in mock_laws:
        st.markdown(
            f"""<div class="card">
                <p class="meta">📍 {org} · {date}</p>
                <h4>{title}</h4>
                <p>🤖 <b>AI 분석 예정:</b> {summary}</p>
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
        ["최근 2일(어제~오늘)", "1주일", "1개월", "1년", "전체"],
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
            _cutoff = datetime.now() - _PERIOD_DELTA[period]
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
            today_str = datetime.today().strftime("%Y-%m-%d")
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
                    for item in kw_news:
                        st.markdown(
                            f"""<div class="card">
                                <p class="meta">🏢 {item['source']} &nbsp;·&nbsp; {item['date']}</p>
                                <h4><a href="{item['link']}" target="_blank"
                                    style="color:#ccd6f6; text-decoration:none;">{item['title']}</a></h4>
                                <p>{item['summary']}</p>
                            </div>""",
                            unsafe_allow_html=True,
                        )
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
                        st.markdown(
                            f"""<div class="card">
                                <p class="meta">🏢 {item['source']} &nbsp;·&nbsp; {item['date']}</p>
                                <h4><a href="{item['link']}" target="_blank"
                                    style="color:#ccd6f6; text-decoration:none;">{item['title']}</a></h4>
                                <p>{item['summary']}</p>
                            </div>""",
                            unsafe_allow_html=True,
                        )
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

    # 갱신 버튼
    col_pol_refresh, col_pol_info = st.columns([1, 4])
    with col_pol_refresh:
        if st.button("🔄 갱신", key="policy_refresh", use_container_width=True,
                     help="RSS·법안 캐시를 초기화하고 최신 데이터를 다시 수집합니다."):
            st.cache_data.clear()
            st.rerun()
    with col_pol_info:
        st.markdown(
            "<p style='color:#8892b0; font-size:0.82rem; margin-top:0.5rem;'>"
            "RSS 1시간 캐시 · 법안 6시간 캐시 · "
            "<code>ASSEMBLY_API_KEY</code> 설정 시 실서버 전환</p>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 두 섹션 나란히 배치 ────────────────────────────────────────────
    col_rss, col_law = st.columns(2)

    # ── 왼쪽: 부처 보도자료 RSS ────────────────────────────────────────
    with col_rss:
        st.markdown('<p class="section-title">📢 유관 부처 보도자료 (RSS)</p>', unsafe_allow_html=True)

        with st.spinner("보도자료 수집 중…"):
            rss_articles = _fetch_policy_rss()

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
                    for article in articles[:5]:  # 부처당 최대 5건 표시
                        if article["is_dummy"]:
                            st.markdown(
                                f"""<div class="coming-card" style="margin-bottom:0.5rem;">
                                    <p class="meta" style="color:#ffc837;">🔧 {article['source']} · {article['date']}</p>
                                    <h4 style="color:#ffc837; font-size:0.9rem;">{article['title']}</h4>
                                    <p>{article['summary']}</p>
                                </div>""",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"""<div class="card" style="margin-bottom:0.5rem;">
                                    <p class="meta">🏢 {article['source']} · {article['date']}</p>
                                    <h4 style="font-size:0.92rem;">
                                        <a href="{article['link']}" target="_blank"
                                           style="color:#ccd6f6; text-decoration:none;">{article['title']}</a>
                                    </h4>
                                    <p>{article['summary'][:120]}…</p>
                                </div>""",
                                unsafe_allow_html=True,
                            )
        else:
            st.info("수집된 보도자료가 없습니다.")

    # ── 오른쪽: 국회 법안 ─────────────────────────────────────────────
    with col_law:
        st.markdown('<p class="section-title">🏛️ 국회 법안 동향 (해상풍력·신재생)</p>', unsafe_allow_html=True)

        with st.spinner("법안 수집 중…"):
            bills = _fetch_assembly_bills()

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
                st.markdown(
                    f"""<div class="card" style="margin-bottom:0.6rem;">
                        <p class="meta">
                            📋 {bill['committee']}{mock_badge} · {bill['propose_date']}
                        </p>
                        <h4 style="font-size:0.9rem;">
                            <a href="{bill['link']}" target="_blank"
                               style="color:#ccd6f6; text-decoration:none;">{bill['title']}</a>
                        </h4>
                        <p>
                            👤 {bill['proposer']}&nbsp;&nbsp;
                            <span style="color:{status_color}; font-weight:700;">
                                ● {bill['status']}
                            </span>
                        </p>
                    </div>""",
                    unsafe_allow_html=True,
                )
        else:
            st.info("수집된 법안이 없습니다.")


# =============================================
# TAB 4 : 유관기관 공지사항
# =============================================
with tab4:
    st.markdown("### 📡 유관기관 공지사항")
    st.markdown(
        "<p style='color:#8892b0;'>"
        "한전·KPX·에너지공단·전기위원회·지자체의 최신 공지를 한곳에서 모니터링합니다."
        "</p>",
        unsafe_allow_html=True,
    )

    # 기관 필터
    institutions = ["전체", "한전 (KEPCO)", "KPX (전력거래소)", "한국에너지공단", "전기위원회", "신안군청"]
    st.selectbox("기관 선택", institutions)
    st.markdown("<br>", unsafe_allow_html=True)

    # 예정 기능 안내
    st.markdown(
        """<div class="coming-card">
            <h4>🚀 연동 예정 기관 및 방법</h4>
            <ul>
                <li><b>한전 (KEPCO)</b> — 계통 연계 공지, 약관 개정 크롤링</li>
                <li><b>KPX (전력거래소)</b> — 시장 운영 공지, SMP 동향 크롤링</li>
                <li><b>한국에너지공단</b> — RPS/REC 공지, 보조금 공고 크롤링</li>
                <li><b>전기위원회</b> — 허가 심의 결과, 규칙 개정 크롤링</li>
                <li><b>신안군청</b> — 인허가 공고, 군 고시 크롤링</li>
            </ul>
            <p style="margin-top:0.6rem;">⚙️ 사용 기술: BeautifulSoup (정적), Selenium (JS 렌더링 필요 시)</p>
        </div>""",
        unsafe_allow_html=True,
    )

    # 공지 카드 Mock — 3열
    st.markdown('<p class="section-title">최신 공지 (샘플 레이아웃)</p>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)

    notices_col1 = [
        ("⚡ 한전", "계통 연계 신청 접수 일정 공지 (3월)", "2026-03-01"),
        ("⚡ 한전", "전기공급약관 제19차 개정 시행 안내", "2026-02-20"),
    ]
    notices_col2 = [
        ("📊 KPX", "2026년 3월 SMP 산정 결과 공표", "2026-03-02"),
        ("📊 KPX", "재생에너지 입찰시장 운영 세칙 개정 공고", "2026-02-15"),
    ]
    notices_col3 = [
        ("🌿 에너지공단", "RPS 공급인증서(REC) 발급 기준 개정 안내", "2026-02-28"),
        ("🏛️ 신안군청", "태양광발전소 인허가 민원 처리 절차 안내", "2026-02-22"),
    ]

    for col, notices in zip([col1, col2, col3], [notices_col1, notices_col2, notices_col3]):
        with col:
            for org, title, date in notices:
                st.markdown(
                    f"""<div class="card">
                        <p class="meta">{org} · {date}</p>
                        <h4 style="font-size:0.92rem;">{title}</h4>
                    </div>""",
                    unsafe_allow_html=True,
                )
