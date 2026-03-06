"""
정부 부처 보도자료 RSS 수집 스크립트
=====================================
Layer 3 (Execution) — 결정론적 Python 스크립트

수집 대상: 신재생에너지 사업개발과 직접 관련된 부처 3개
  - 산업통상부(구 산업통상자원부), 기후에너지환경부, 해양수산부
  - 산림청: RSS 미제공 → 제외 (추후 대안 방안 검토 예정)
  - 국방부: 해상풍력 군 협의 필요하나 보도자료 직접 관련성 낮아 제외

RSS 출처: 대한민국 정책브리핑 부처별 RSS (korea.kr)
  - 인증 불필요 (공개 API)
  - 수집 실패 시 Dummy 데이터 반환 → 앱이 멈추지 않도록 설계

첨부파일 수집:
  - korea.kr의 모든 부처 보도자료는 동일한 HTML 구조 사용 (통합 플랫폼)
  - 첨부파일 섹션: div.filedown > dl > dd > span > a
  - 다운로드 URL 형식: https://www.korea.kr/common/download.do?fileId=...
  - 병렬 HTTP 요청(ThreadPoolExecutor)으로 성능 최적화
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.utils import parsedate_to_datetime


# ── 수집 대상 부처 설정 ────────────────────────────────────────────────
# 부처별 개별 RSS URL 사용 이유:
# 통합 RSS보다 부처별 RSS가 더 정확하게 해당 부처 기사만 반환함
# url 필드만 교체하면 되므로 향후 URL 변경 시 유지보수가 쉬움
RSS_SOURCES = [
    {
        "name": "산업통상부",
        "short": "산업부",
        # RPS, 재생에너지 계획입지, 에너지 기본계획 등 핵심 정책 담당
        # 구 산업통상자원부 → 산업통상부로 개편 (2026년)
        "url": "https://www.korea.kr/rss/dept_motir.xml",
        "filter_dept": "",  # 부처별 RSS라 별도 필터 불필요
    },
    {
        "name": "기후에너지환경부",
        "short": "기후부",
        # 탄소중립, 신재생에너지 보급 목표, 온실가스 감축 담당
        "url": "https://www.korea.kr/rss/dept_mcee.xml",
        "filter_dept": "",  # 부처별 RSS라 별도 필터 불필요
    },
    {
        "name": "해양수산부",
        "short": "해수부",
        # 해상풍력 공유수면 점용·사용 허가, 어업인 협의 등 담당
        "url": "https://www.korea.kr/rss/dept_mof.xml",
        "filter_dept": "",  # 부처별 RSS라 별도 필터 불필요
    },
]

# ── 신재생 사업개발 핵심 키워드 (제목 전용 필터) ────────────────────────
# 제목에만 적용하는 이유:
#   요약(summary)은 관련 없는 기사도 "에너지", "발전", "해상" 등을 포함할 수 있어
#   노이즈가 심함. 제목에 키워드가 없으면 신재생 사업과 직접 관련이 없는 기사.
#
# 제외한 광범위 키워드 (노이즈 원인):
#   "에너지" — 에너지음료, 에너지절약 등도 포함됨
#   "해상"   — 해상관광, 해상물류, 해상안전 등도 포함됨
#   "발전"   — 경제발전, 기술발전, 조직발전 등도 포함됨
#   "전력"   — 군사전력, 경찰전력 등도 포함됨
#   "허가"   — 각종 영업허가, 식품허가 등 모든 행정허가 포함됨
#   "온실가스"— 기후부 전반 기사 포함, 신재생 직접 관련성 낮음
ENERGY_KEYWORDS_TITLE = [
    # 발전원 (명확하게 신재생만 지칭)
    "풍력", "태양광", "신재생", "재생에너지", "ESS", "BESS",
    # 인허가·계통 관련 (신재생 특화 용어)
    "계통", "RPS", "REC", "PPA", "집적화단지", "공유수면", "산지전용",
    # 수소·분산에너지
    "수소", "분산에너지",
    # 탄소중립 (신재생 정책 직결)
    "탄소중립",
    # 해상풍력 특화
    "WTIV", "해상풍력", "어업인",
]

# ── HTTP 요청 공통 헤더 ────────────────────────────────────────────────
# korea.kr은 User-Agent 없으면 접근 차단할 수 있으므로 브라우저처럼 위장
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── 첨부파일 수집 설정 ────────────────────────────────────────────────
# 병렬 요청 최대 스레드 수 — 너무 많으면 서버 부하, 너무 적으면 느림
_MAX_WORKERS = 5
# 개별 페이지 요청 타임아웃 (초)
_PAGE_TIMEOUT = 8


def _is_energy_related(title: str) -> bool:
    """
    제목에 신재생 사업개발 핵심 키워드가 포함되면 True 반환.
    요약은 검사하지 않음 — 요약의 광범위한 키워드 매칭이 노이즈의 주원인.
    """
    return any(keyword in title for keyword in ENERGY_KEYWORDS_TITLE)


def _parse_date_safe(pub_date_str: str) -> str:
    """
    RFC 822 형식 날짜 문자열을 'YYYY-MM-DD'로 변환.
    파싱 실패 시 오늘 날짜 반환 — RSS 포맷이 부처마다 달라 예외가 자주 발생함.
    """
    try:
        return parsedate_to_datetime(pub_date_str).strftime("%Y-%m-%d")
    except Exception:
        return datetime.today().strftime("%Y-%m-%d")


def _make_dummy_articles(dept_short: str) -> list[dict]:
    """
    RSS 수집 실패 시 반환할 Dummy 데이터.
    is_dummy=True 로 마킹해 UI에서 '수집 준비 중' 안내 표시 가능.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    return [
        {
            "date": today,
            "source": dept_short,
            "title": f"[{dept_short}] 보도자료 수집 연결 중",
            "summary": (
                "RSS 주소를 확인 중입니다. "
                "실제 URL 설정 후 자동으로 수집됩니다. "
                "(directives/policy_tracking_sop.md 참고)"
            ),
            "link": "https://www.korea.kr/briefing/pressReleaseList.do",
            "attachments": [],
            "is_dummy": True,
        }
    ]


def _fetch_attachments(article_url: str) -> list[dict]:
    """
    보도자료 원문 페이지에서 첨부파일 목록을 추출합니다.

    korea.kr 통합 플랫폼 기준 (모든 부처 동일 구조):
      - 첨부파일 섹션: <div class="filedown"> > <dl> > <dd> > <span> > <a>
      - 다운로드 링크: href="/common/download.do?fileId=...&tblKey=GMN"
      - 뷰어 링크(class="view")는 제외하고 실제 다운로드 링크만 추출

    Args:
        article_url: korea.kr 보도자료 상세 페이지 URL

    Returns:
        [{"name": "파일명.hwp", "url": "https://www.korea.kr/common/download.do?..."}]
        실패 또는 첨부파일 없으면 빈 리스트 반환
    """
    try:
        resp = requests.get(
            article_url,
            headers=_HTTP_HEADERS,
            timeout=_PAGE_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        attachments: list[dict] = []

        # korea.kr 첨부파일 섹션: div.filedown 아래 모든 a 태그 순회
        filedown_div = soup.find("div", class_="filedown")
        if not filedown_div:
            # 첨부파일 섹션 자체가 없는 보도자료 → 빈 리스트 정상 반환
            return []

        seen_file_ids: set[str] = set()  # fileId 기준 중복 방지

        for a_tag in filedown_div.find_all("a", href=True):
            href = a_tag.get("href", "")
            tag_class = a_tag.get("class", [])

            # 뷰어 링크(docViewer, class="view") 제외
            if "docViewer" in href or "view" in tag_class:
                continue

            # "내려받기" 버튼(class="down") 제외 — 파일명 링크와 URL이 동일한 중복 버튼
            if "down" in tag_class:
                continue

            # 실제 다운로드 링크만 포함
            if "/common/download.do" not in href:
                continue

            # fileId 기준 중복 제거 (같은 파일이 여러 a 태그로 표시되는 경우 방어)
            file_id = href.split("fileId=")[-1].split("&")[0] if "fileId=" in href else href
            if file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)

            # 파일명: a 태그 텍스트에서 이미지 alt 텍스트 제외하고 추출
            file_name = a_tag.get_text(separator=" ", strip=True)
            # img alt 텍스트(예: "한글파일", "PDF") 제거 — 파일명만 남김
            for img in a_tag.find_all("img"):
                alt_text = img.get("alt", "")
                file_name = file_name.replace(alt_text, "").strip()

            # 상대 경로 → 절대 URL 변환
            full_url = "https://www.korea.kr" + href if href.startswith("/") else href

            if file_name:
                attachments.append({"name": file_name, "url": full_url})

        return attachments

    except Exception as e:
        # 개별 페이지 요청 실패는 전체 수집을 중단시키지 않음
        print(f"[첨부파일] 수집 실패 ({article_url[:60]}...): {e}")
        return []


def _enrich_with_attachments(articles: list[dict]) -> list[dict]:
    """
    기사 목록에 첨부파일 정보를 병렬로 추가합니다.

    ThreadPoolExecutor 사용 이유:
      - 기사 1건당 HTTP 요청 1개 → 순차 처리 시 10건 × 2초 = 20초 지연
      - 병렬 처리 시 MAX_WORKERS=5 기준 → 10건도 2~3초 이내 완료
      - I/O bound 작업이므로 Thread 방식이 적합 (GIL 문제 없음)

    Args:
        articles: fetch_rss_articles()가 반환한 기사 리스트 (is_dummy=False만 처리)

    Returns:
        attachments 키가 추가된 기사 리스트 (순서 보존)
    """
    # Dummy 기사는 HTTP 요청 불필요 → 빈 attachments 설정 후 제외
    real_articles = [a for a in articles if not a.get("is_dummy")]
    dummy_articles = [a for a in articles if a.get("is_dummy")]
    for dummy in dummy_articles:
        dummy.setdefault("attachments", [])

    if not real_articles:
        return articles

    # 링크 → 기사 매핑 (병렬 결과를 원래 순서에 맞게 삽입하기 위해)
    link_to_article = {a["link"]: a for a in real_articles}

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        # 링크별로 future 생성
        future_to_link = {
            executor.submit(_fetch_attachments, link): link
            for link in link_to_article
        }

        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                attachments = future.result()
            except Exception:
                attachments = []
            link_to_article[link]["attachments"] = attachments

    # attachments 키가 설정 안 된 기사 방어 처리 (타임아웃 등)
    for article in real_articles:
        article.setdefault("attachments", [])

    return articles


def fetch_rss_articles(
    filter_energy: bool = True,
    fetch_attachments: bool = True,
) -> list[dict]:
    """
    등록된 부처 RSS를 순회하며 보도자료를 수집합니다.

    Args:
        filter_energy: True이면 에너지 관련 키워드 포함 기사만 반환.
                       False이면 부처 필터만 적용 (전체 보도자료).
        fetch_attachments: True이면 각 기사의 첨부파일 목록을 함께 수집.
                           False이면 attachments=[] 로 설정하고 HTTP 요청 생략.

    Returns:
        [{date, source, title, summary, link, attachments, is_dummy}, ...] 최신순 정렬
        attachments: [{"name": "파일명.hwp", "url": "다운로드URL"}, ...]
    """
    collected_articles: list[dict] = []

    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])

            # korea.kr RSS는 charset 선언(us-ascii)과 실제 인코딩(utf-8)이 달라
            # bozo=True가 반환되지만 entries는 정상 수집됨 → bozo는 무시하고
            # entries가 비어있을 때만 실패로 간주함
            if not feed.entries:
                raise ValueError(f"RSS entries 없음 (status={feed.get('status', '?')})")

            dept_articles: list[dict] = []
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")
                pub_date = entry.get("published", "")

                # 부처명 필터: filter_dept가 있으면 적용, 없으면 통과
                # 부처별 개별 RSS URL은 이미 해당 부처 기사만 반환하므로 필터 불필요
                # 통합 RSS URL을 사용할 경우에만 filter_dept를 설정해서 필터링함
                if source["filter_dept"]:
                    source_tag = entry.get("source", {}).get("value", "")
                    author = entry.get("author", "")
                    dept_hint = source_tag + author + title + summary
                    if source["filter_dept"] not in dept_hint:
                        continue

                article = {
                    "date": _parse_date_safe(pub_date),
                    "source": source["short"],
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "attachments": [],  # _enrich_with_attachments에서 채워짐
                    "is_dummy": False,
                }

                # 에너지 키워드 필터 적용
                if filter_energy and not _is_energy_related(title):
                    continue

                dept_articles.append(article)

            # RSS는 정상 연결됐지만 에너지 관련 기사가 없으면 → 그냥 skip
            # (Dummy 카드를 "연결 준비 중"으로 표시하면 사용자가 오해할 수 있음)
            # Dummy는 RSS 연결 자체가 실패했을 때만 표시 (아래 except에서 처리)
            collected_articles.extend(dept_articles)

        except Exception as e:
            # 부처 하나 실패가 전체 수집을 중단시키면 안 됨 → 개별 처리
            print(f"[{source['short']}] RSS 수집 실패: {e} → Dummy 데이터로 대체")
            collected_articles.extend(_make_dummy_articles(source["short"]))

    # 최신순 정렬 (날짜 문자열이 YYYY-MM-DD 형식이므로 문자열 정렬로 충분)
    collected_articles.sort(key=lambda x: x["date"], reverse=True)

    # 첨부파일 수집 (병렬 HTTP 요청)
    # 최상위 try/except: 첨부파일 수집 전체 실패해도 기사 목록은 반드시 반환
    if fetch_attachments:
        try:
            collected_articles = _enrich_with_attachments(collected_articles)
        except Exception as e:
            print(f"[첨부파일] 전체 수집 실패: {e} → 첨부파일 없이 기사 반환")
            for a in collected_articles:
                a.setdefault("attachments", [])

    return collected_articles


# ── 단독 실행 시 테스트 ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("정부 부처 보도자료 RSS 수집 + 첨부파일 테스트")
    print("=" * 60)

    articles = fetch_rss_articles(filter_energy=True, fetch_attachments=True)
    print(f"\n수집된 기사 수: {len(articles)}건\n")

    for i, article in enumerate(articles[:10], 1):
        dummy_mark = " [DUMMY]" if article["is_dummy"] else ""
        print(f"[{i}] {article['date']} | {article['source']}{dummy_mark}")
        print(f"     제목: {article['title'][:60]}")
        print(f"     링크: {article['link']}")
        attachments = article.get("attachments", [])
        if attachments:
            print(f"     첨부파일 {len(attachments)}건:")
            for att in attachments:
                print(f"       - {att['name'][:50]}")
                print(f"         {att['url']}")
        else:
            print("     첨부파일: 없음")
        print()
