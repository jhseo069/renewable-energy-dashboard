# SOP: 유관기관 공지사항 수집 (agency_notice_sop.md)

> **계층**: Layer 1 — Directive (무엇을 할지 정의)
> **작성일**: 2026-03-09
> **담당 실행 스크립트**: `execution/notice_crawler.py`
> **UI 연동**: `app.py` → Tab 4 (📡 유관기관 공지사항)

---

## 수집 목표

신재생에너지 사업개발팀이 모니터링해야 하는 유관기관의 최신 공지사항을 자동 수집하여
계통 연계, RPS/REC, 인허가, 시장 운영 등의 변화를 즉시 파악한다.

---

## 수집 대상 기관 (3개)

| 기관명 | 약칭 | 수집 이유 | 공지 URL |
|--------|------|-----------|----------|
| 전력거래소 | KPX | SMP·REC 시장 운영, 출력제어, 입찰 공고 | `https://www.kpx.or.kr/www/selectBbsNttList.do?key=102&bbsNo=3` |
| 한국에너지공단 | KEMCO | RPS 의무량, REC 발급 기준, 보조금 공고 | `https://www.kemco.or.kr/web/kem_home_new/info/publicNotice/list.do` |
| 한국전력공사 | KEPCO | 계통 연계 기술기준, 전기공급약관, 접속 신청 | `https://home.kepco.co.kr/kepco/KO/ntcf/1/list.do` |

### 추후 추가 검토 기관 (Phase 2)
- **전기위원회**: 발전사업 허가 심의 결과 (`https://www.electricitycommission.go.kr`)
- **신안군청**: 태양광·풍력 인허가 공고 (`https://www.shinan.go.kr`)

---

## 크롤링 기술 스택

| 항목 | 설정값 | 이유 |
|------|--------|------|
| HTTP 라이브러리 | `requests` | 정적 HTML 수집에 충분 |
| HTML 파서 | `BeautifulSoup (lxml)` | 테이블·리스트 파싱에 적합 |
| JavaScript 렌더링 | ❌ 미사용 | Streamlit Cloud에 Selenium 설치 불가 |
| User-Agent | Chrome 130 (Windows) | 봇 차단 우회 |
| 타임아웃 | 10초 | Cloud 환경 응답 지연 대응 |
| 재시도 | ❌ 미사용 | 실패 시 즉시 Mock 반환 (무한 루프 방지) |

### 필수 요청 헤더
```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.google.co.kr/",
}
```

---

## 수집 공지 데이터 스키마

```python
{
    "org":      str,   # 기관 전체명 (예: "KPX (전력거래소)")
    "org_key":  str,   # 필터용 키 (예: "kpx", "kemco", "kepco")
    "title":    str,   # 공지 제목
    "date":     str,   # 게시일 (YYYY-MM-DD)
    "link":     str,   # 원문 URL (절대 경로)
    "category": str,   # 카테고리 (공지사항 / 입찰공고 / 규정개정 등)
    "is_mock":  bool,  # 크롤링 실패 시 True
}
```

---

## 예외 처리 원칙 (핵심)

1. **즉시 Mock 전환**: 403 Forbidden · 404 · 타임아웃 · 파싱 오류 → 즉시 Mock 반환
2. **재시도 금지**: 실패 시 루프 없이 즉각 Mock 반환 (Cloud 타임아웃 방지)
3. **기관별 독립 try/except**: 한 기관 실패가 다른 기관 수집에 영향 없어야 함
4. **앱 중단 금지**: 크롤링 오류가 Streamlit 앱 전체를 멈추게 하면 안 됨
5. **Mock 마킹 필수**: `is_mock=True` 필드 + UI에서 "[연결 준비 중]" 배지 표시

---

## 캐시 정책

| 항목 | 설정값 |
|------|--------|
| 캐시 TTL | 1시간 (`@st.cache_data(ttl=3600)`) |
| 수동 갱신 | UI "🔄 갱신" 버튼 클릭 시 캐시 초기화 |
| Mock 캐시 | 동일 — Mock도 1시간 캐시 (불필요한 반복 요청 방지) |

---

## UI 표시 원칙

- 기관별 Expander로 구분 (기관명 + 건수 표시)
- 각 공지에 원문 링크 클릭 연결
- Mock 공지에 "⚙️ [연결 준비 중]" 배지 표시
- 기관 필터 selectbox로 특정 기관만 조회 가능
- CSV 다운로드 버튼 제공

---

## 향후 개선 사항

- [ ] JS 렌더링 필요 기관 대응 (Playwright 등 비동기 크롤러 검토)
- [ ] 전기위원회 공지 추가
- [ ] 신안군청 공고 추가
- [ ] 공지 변경 감지 시 슬랙 알림
- [ ] 제목 키워드 필터 (신재생 관련 공지만 선별)
