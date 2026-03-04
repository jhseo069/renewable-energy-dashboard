"""
네이버 뉴스 API 연동 유틸리티
- 신재생에너지 키워드 뉴스 검색
- 3대 에너지 전문지 집중 검색
- DataFrame 변환 및 CSV 아카이브 자동 저장
"""

import os
import re
import io
import difflib
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# 3대 에너지 전문지
ENERGY_PUBLISHERS = ["전기신문", "에너지경제", "일렉트릭파워"]

# 언론사 URL → 이름 매핑
_SOURCE_MAP = {
    "electimes.com": "전기신문",
    "energy-news.co.kr": "에너지경제",
    "ekn.kr": "에너지경제",
    "electrica.co.kr": "일렉트릭파워",
}

# ── 품질 필터 설정 ──────────────────────────────────────────
# 3대 전문지는 모든 필터를 우회 (최우선 노출)
_BYPASS_PUBLISHERS = frozenset(["전기신문", "에너지경제", "일렉트릭파워"])

# 금지어 목록 — 제목(title) 또는 요약(summary)에 하나라도 포함되면 제외
_BAN_WORDS = frozenset([
    # 주식·증권
    "주식", "주가", "증권", "특징주", "시황", "폭락", "폭등",
    "상한가", "하한가", "코스피", "코스닥", "목표가", "종가",
    "시총", "펀드", "투자의견", "목표주가", "매수", "매도", "급등", "급락",
    # 영상·사진·기타 불량 포맷
    "[영상]", "(영상)", "[동영상]", "(동영상)", "다시보기",
    "동영상", "영상뉴스", "포토", "사진", "인터뷰", "언터뷰",
])

# 요약 최소 길이 (이보다 짧으면 알맹이 없는 기사로 간주)
_MIN_SUMMARY_LEN = 30

# 키워드별 조건부 금지어 — 특정 키워드로 수집할 때만 적용
# 예) '풍력' 검색 시 '해상풍력' 기사 제외 (해상풍력은 별도 키워드로 수집)
_KEYWORD_SPECIFIC_BANS: dict[str, frozenset] = {
    "풍력": frozenset(["해상", "해상풍력"]),
}


def _strip_for_compare(text: str) -> str:
    """유사도 비교 전 전처리: 공백·특수기호 모두 제거하여 글자 자체의 일치율만 비교"""
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", text)


def _deduplicate_by_similarity(articles: list[dict], threshold: float = 0.3) -> list[dict]:
    """유사도 기반 중복 기사 제거 (difflib.SequenceMatcher, threshold=30%)
    비교 전 공백·특수기호를 제거한 후, 제목 OR 요약 중 하나라도 유사도 30% 이상이면 중복으로 간주합니다.
    3대 전문지(전기신문·에너지경제·일렉트릭파워)는 중복 검사 없이 항상 포함합니다.
    """
    unique: list[dict] = []
    for article in articles:
        # 3대 전문지는 중복 검사 우회
        if article.get("source", "") in _BYPASS_PUBLISHERS:
            unique.append(article)
            continue
        title = _strip_for_compare(article.get("title", ""))
        summary = _strip_for_compare(article.get("summary", ""))
        is_dup = any(
            difflib.SequenceMatcher(None, title, _strip_for_compare(u.get("title", ""))).ratio() >= threshold
            or difflib.SequenceMatcher(None, summary, _strip_for_compare(u.get("summary", ""))).ratio() >= threshold
            for u in unique
        )
        if not is_dup:
            unique.append(article)
    return unique


def _is_quality_article(item: dict, keyword: str = "") -> bool:
    """
    기사 품질 검사. True이면 포함, False이면 제외.
    3대 전문지(전기신문·에너지경제·일렉트릭파워)는 모든 필터를 우회해 항상 포함.
    title과 summary 모두 금지어 검사 대상.
    """
    # 3대 전문지는 무조건 통과
    if item.get("source", "") in _BYPASS_PUBLISHERS:
        return True

    title = item.get("title", "")
    summary = item.get("summary", "")

    # 제목에 핵심 키워드 없으면 낚시성 기사로 간주
    if keyword and keyword not in title:
        return False

    # 요약이 너무 짧거나 비어있음
    if len(summary) < _MIN_SUMMARY_LEN:
        return False

    # 제목 또는 요약에 금지어 포함 시 제외
    combined = title + summary
    for word in _BAN_WORDS:
        if word in combined:
            return False

    # 키워드별 조건부 금지어 검사 (예: '풍력' 검색 시 해상풍력 기사 제외)
    for word in _KEYWORD_SPECIFIC_BANS.get(keyword, frozenset()):
        if word in combined:
            return False

    return True


def _clean_html(text: str) -> str:
    """HTML 태그 및 특수 엔티티 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'")
    return text.strip()


def _parse_pub_date(pub_date: str) -> str:
    """RFC 822 날짜 → 'YYYY-MM-DD HH:MM' 변환"""
    try:
        dt = parsedate_to_datetime(pub_date)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return pub_date


def _extract_source(original_link: str, link: str) -> str:
    """URL 도메인에서 언론사 추출"""
    import urllib.parse
    for url in [original_link, link]:
        try:
            host = urllib.parse.urlparse(url).hostname or ""
            host = host.replace("www.", "")
            for domain, name in _SOURCE_MAP.items():
                if domain in host:
                    return name
            # 도메인 자체를 약칭으로 반환
            parts = host.split(".")
            return parts[0] if parts else host
        except Exception:
            continue
    return "기타"


def search_naver_news(query: str, display: int = 20, sort: str = "date", keyword_in_title: str = "") -> list[dict]:
    """
    네이버 뉴스 API로 뉴스를 검색합니다.

    Args:
        query: 검색 키워드
        display: 최대 결과 수 (최대 100)
        sort: 정렬 기준 - "date"(최신순) or "sim"(관련도순)

    Returns:
        [{"date", "source", "title", "summary", "link"}, ...]
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 .env에 설정되지 않았습니다.")

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": sort}

    resp = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=10)
    if resp.status_code == 401:
        raise ValueError(
            "네이버 API 인증 실패 (401). "
            ".env 파일의 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET이 올바른지 확인하세요. "
            "Secret 값이 잘렸거나 만료된 경우 네이버 개발자센터에서 재발급 받으세요."
        )
    resp.raise_for_status()

    items = resp.json().get("items", [])
    results = []
    for item in items:
        original_link = item.get("originallink", "")
        link = item.get("link", "")
        article = {
            "date": _parse_pub_date(item.get("pubDate", "")),
            "source": _extract_source(original_link, link),
            "title": _clean_html(item.get("title", "")),
            "summary": _clean_html(item.get("description", "")),
            "link": original_link or link,
        }
        if _is_quality_article(article, keyword=keyword_in_title):
            results.append(article)
    return _deduplicate_by_similarity(results)


def search_with_publishers(query: str, display_per_pub: int = 10) -> list[dict]:
    """
    3대 에너지 전문지(전기신문, 에너지경제, 일렉트릭파워)에서 집중 검색합니다.
    각 언론사 이름을 쿼리에 추가해 API를 3회 호출하고, 결과를 병합·중복 제거·최신순 정렬합니다.
    """
    all_results = []
    for pub in ENERGY_PUBLISHERS:
        try:
            items = search_naver_news(f"{query} {pub}", display=display_per_pub)
            # 언론사 이름을 확정 값으로 덮어씀
            for item in items:
                item["source"] = pub
            all_results.extend(items)
        except Exception:
            pass  # 한 언론사 실패해도 나머지 계속 진행

    # 중복 제거 (link 기준) + 최신순 정렬
    seen = set()
    unique = []
    for item in all_results:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)

    unique.sort(key=lambda x: x["date"], reverse=True)
    return unique


def news_to_dataframe(news_list: list[dict]) -> pd.DataFrame:
    """뉴스 리스트를 pandas DataFrame으로 변환합니다."""
    df = pd.DataFrame(news_list, columns=["date", "source", "title", "summary", "link"])
    df.columns = ["날짜", "언론사", "제목", "요약", "링크"]
    return df


def save_to_archive(df: pd.DataFrame) -> Path:
    """
    data/news_archive/YYYY-MM-DD_news.csv에 누적 저장합니다.
    같은 날짜 파일이 있으면 기존 데이터와 병합하여 중복을 제거합니다.
    """
    archive_dir = Path(__file__).parent.parent / "data" / "news_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.today().strftime("%Y-%m-%d")
    filepath = archive_dir / f"{today}_news.csv"

    if filepath.exists():
        existing = pd.read_csv(filepath, encoding="utf-8-sig")
        combined = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["링크"])
    else:
        combined = df

    combined.to_csv(filepath, index=False, encoding="utf-8-sig")
    return filepath


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame을 UTF-8 BOM CSV 바이트로 변환합니다 (엑셀 한글 호환)."""
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False, encoding="utf-8-sig")
    return buffer.getvalue()
