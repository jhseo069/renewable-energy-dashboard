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
"""

import feedparser
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

# ── 에너지 관련 키워드 필터 ────────────────────────────────────────────
# 부처 보도자료 중 신재생 사업과 무관한 일반 행정·복지·인사 기사를 제거하기 위함.
# 제목 또는 요약에 아래 키워드 중 하나라도 포함되면 포함.
ENERGY_KEYWORDS = [
    "풍력", "태양광", "신재생", "재생에너지", "ESS", "에너지",
    "해상", "계통", "RPS", "REC", "수소", "발전", "전력",
    "탄소중립", "온실가스", "허가", "인허가", "산지전용",
    "집적화단지", "공유수면", "PPA", "분산에너지",
]


def _is_energy_related(title: str, summary: str) -> bool:
    """제목 또는 요약에 에너지 관련 키워드가 포함되어 있으면 True 반환"""
    combined_text = title + " " + summary
    return any(keyword in combined_text for keyword in ENERGY_KEYWORDS)


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
            "is_dummy": True,
        }
    ]


def fetch_rss_articles(filter_energy: bool = True) -> list[dict]:
    """
    등록된 부처 RSS를 순회하며 보도자료를 수집합니다.

    Args:
        filter_energy: True이면 에너지 관련 키워드 포함 기사만 반환.
                       False이면 부처 필터만 적용 (전체 보도자료).

    Returns:
        [{date, source, title, summary, link, is_dummy}, ...] 최신순 정렬
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
                    "is_dummy": False,
                }

                # 에너지 키워드 필터 적용
                if filter_energy and not _is_energy_related(title, summary):
                    continue

                dept_articles.append(article)

            # 부처별로 기사를 모았는데 0건이면 Dummy 추가
            # (RSS는 연결됐지만 해당 부처 기사가 없는 경우 대비)
            if not dept_articles:
                collected_articles.extend(_make_dummy_articles(source["short"]))
            else:
                collected_articles.extend(dept_articles)

        except Exception as e:
            # 부처 하나 실패가 전체 수집을 중단시키면 안 됨 → 개별 처리
            print(f"[{source['short']}] RSS 수집 실패: {e} → Dummy 데이터로 대체")
            collected_articles.extend(_make_dummy_articles(source["short"]))

    # 최신순 정렬 (날짜 문자열이 YYYY-MM-DD 형식이므로 문자열 정렬로 충분)
    collected_articles.sort(key=lambda x: x["date"], reverse=True)
    return collected_articles


# ── 단독 실행 시 테스트 ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("정부 부처 보도자료 RSS 수집 테스트")
    print("=" * 60)

    articles = fetch_rss_articles(filter_energy=True)
    print(f"\n수집된 기사 수: {len(articles)}건\n")

    for i, article in enumerate(articles[:10], 1):
        dummy_mark = " [DUMMY]" if article["is_dummy"] else ""
        print(f"[{i}] {article['date']} | {article['source']}{dummy_mark}")
        print(f"     제목: {article['title'][:60]}...")
        print(f"     링크: {article['link']}")
        print()
