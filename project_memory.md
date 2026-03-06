# 신재생에너지 사업개발 대시보드 — 프로젝트 메모리

> **마지막 업데이트:** 2026-03-04
> **작성 목적:** 대화 컨텍스트 초기화 후에도 다음 작업자(AI 포함)가 현재 상태를 100% 파악하고 즉시 이어서 작업할 수 있도록 작성한 전체 현황 문서입니다.

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 프로젝트명 | 신재생에너지 사업개발 대시보드 |
| 목적 | 신재생에너지 사업개발팀 사내 전용 대시보드 — 뉴스 모니터링, 입지/규제 분석, 정책·입법 동향, 유관기관 공지사항 통합 |
| 기술 스택 | Python 3.13, Streamlit, pandas, requests, difflib (내장), python-dotenv, feedparser, beautifulsoup4, anthropic |
| 실행 경로 | `e:\바이브코딩(Gemini,Claude Code)\renewable-energy-dashboard\` |
| 실행 명령 | `streamlit run app.py` |
| 로컬 URL | `http://localhost:8501` (포트는 상황에 따라 8502~8504로 변경될 수 있음) |
| 클라우드 URL | `https://renewable-energy-dashboard-nsmgneobdtz3xqpddasevz.streamlit.app/` |
| 버전 | v0.2.0 |

---

## 2. 디렉토리 구조

```
renewable-energy-dashboard/
├── app.py                          # 메인 Streamlit 앱 (4탭 UI)
├── requirements.txt                # 의존성 패키지
├── .env                            # API 키 (git 제외)
├── .env.example                    # API 키 템플릿
├── project_memory.md               # 이 파일
├── streamlit.log                   # Streamlit 실행 로그
├── utils/
│   ├── __init__.py
│   ├── news_crawler.py             # 네이버 뉴스 API + 필터링 로직 (핵심)
│   └── law_api.py                  # 국가법령정보센터 API (미구현 플레이스홀더)
├── pages/
│   └── __init__.py
└── data/
    └── news_archive/
        └── YYYY-MM-DD_news.csv     # 날짜별 뉴스 자동 아카이브
```

---

## 2-2. 추가된 디렉토리 (v0.3.0, 2026-03-05)

```
renewable-energy-dashboard/
├── directives/
│   └── policy_tracking_sop.md      # 정책/입법 수집 SOP (Layer 1)
├── execution/
│   ├── rss_crawler.py              # 부처 보도자료 RSS 수집 (Layer 3)
│   └── law_api.py                  # 국회 법안 API 연동 (Layer 3, Mock 포함)
├── app.py                          # Tab 3 실데이터 연동으로 업데이트
```

---

## 3. API 키 설정 (.env)

```
LAW_API_KEY=your_law_api_key_here          # 국가법령정보센터 (미연동)
ANTHROPIC_API_KEY=your_anthropic_api_key_here  # Claude AI (미연동)
NAVER_CLIENT_ID=KVpRm83DQimDWn3N_3Uq      # 네이버 검색 API (연동 완료)
NAVER_CLIENT_SECRET=z0ByXCovGJ             # 네이버 검색 API (연동 완료)
ASSEMBLY_API_KEY=                          # 국회 오픈 API (미발급 → Mock 자동 전환)
```

> **주의:** `.env` 파일의 `NAVER_CLIENT_SECRET`에서 숫자 `0`을 영문자 `O`로 혼동하지 않도록 주의. 과거에 이 오류로 401 인증 실패 발생 이력 있음.

---

## 4. 4탭 UI 구성 현황

### Tab 1: 📜 입지/규제 분석
- **상태:** UI 레이아웃 완성, API 연동 미구현 (Coming Soon)
- **목표:** 국가법령정보센터 API로 지자체 조례 검색 → Claude AI 자동 분석
- **준비 필요:** `.env`에 `LAW_API_KEY`, `ANTHROPIC_API_KEY` 설정 후 `utils/law_api.py` 구현

### Tab 2: 📰 일일 뉴스 모니터링
- **상태:** 완전 구현 완료 (핵심 기능)
- 상세 내용은 아래 섹션 5~7 참조

### Tab 3: 🏛️ 정책 및 입법 동향
- **상태:** ✅ **기능 구현 완료 + 필터 개선 완료 (v0.3.0, 2026-03-05~06)**
- 왼쪽: 부처 보도자료 — `execution/rss_crawler.py` 연동 (RSS 실패 시 Dummy 자동 표시)
- 오른쪽: 국회 법안 — `execution/law_api.py` 연동 (API 키 미설정 시 Mock 자동 표시)
- RSS 1시간 캐시, 법안 6시간 캐시
- **RSS URL (실운영 중):**
  - 산업통상부: `https://www.korea.kr/rss/dept_motir.xml`
  - 기후에너지환경부: `https://www.korea.kr/rss/dept_mcee.xml`
  - 해양수산부: `https://www.korea.kr/rss/dept_mof.xml`
  - 산림청: RSS 미제공 → 제외
- **RSS bozo=True 이슈**: korea.kr RSS는 charset 선언(us-ascii)과 실제 인코딩(utf-8) 불일치로 bozo=True 반환되지만 entries는 정상. `if not feed.entries`만 실패 조건으로 처리.
- **에너지 키워드 필터**: 제목(title)만 체크, 요약(summary) 미사용. 광범위 키워드(에너지·해상·발전·전력·허가·온실가스) 제거하고 신재생 특화 키워드만 유지.
- **필터 적용 후 0건**: Dummy 카드 표시 안 함 (RSS 연결 실패 시에만 Dummy 표시)
- **UI 개선 사항 완료 (2026-03-06)**: Tab 3 RSS expander 내부에 `st.container(height=400)` 적용하여 모든 기사 스크롤 확인 가능.

### Tab 4: 📡 유관기관 공지사항
- **상태:** UI 레이아웃 완성, 크롤러 미구현 (Coming Soon)
- **목표:** 한전(KEPCO), KPX(전력거래소), 한국에너지공단, 전기위원회, 신안군청 공지 크롤링
- **준비 필요:** BeautifulSoup4 (이미 설치됨), JS 렌더링 필요 시 Selenium 추가

---

## 5. Tab 2: 일일 뉴스 모니터링 — 핵심 구현

### 5-1. 12개 모니터링 키워드
```python
_KEYWORDS = (
    '해상풍력', '풍력', '태양광', 'ESS', 'BESS', '분산에너지',
    '수소', '출력제어', '전력계통', '신재생', 'PPA', 'REC',
)
```

### 5-2. 데이터 수집 흐름
```
네이버 뉴스 API (display=100, sort=date)
    → _is_quality_article() 품질 필터
    → _deduplicate_by_similarity() 유사도 중복 제거
    → @st.cache_data(ttl=3600) 1시간 캐시
    → UI 조회 기간 필터 (최근 2일 / 1주일 / 1개월 / 1년 / 전체)
    → 3대 전문지 토글 필터
    → 화면 표시 + CSV 다운로드 + 아카이브 자동 저장
```

### 5-3. 11개 화면 표시 그룹 (ESS+BESS 통합)
```python
_DISPLAY_GROUPS = [
    ("해상풍력",),
    ("풍력",),
    ("태양광",),
    ("ESS", "BESS"),   # 두 키워드 병합, 링크 기준 중복 제거 후 최신순
    ("분산에너지",),
    ("수소",),
    ("출력제어",),
    ("전력계통",),
    ("신재생",),
    ("PPA",),
    ("REC",),
]
```
> ESS와 BESS는 수집 시 별도 키워드로 API 호출하지만, 화면에는 "ESS/BESS 동향" 하나로 합쳐서 표시.

### 5-4. 캐시 및 기간 필터
- **캐시:** `@st.cache_data(ttl=3600)` — 1시간 동안 API 재호출 없음
- **캐시 갱신:** UI의 "🔄 캐시 갱신" 버튼 클릭
- **기간 필터 옵션:** `["최근 2일(어제~오늘)", "1주일", "1개월", "1년", "전체"]`
  - 기본값: **최근 2일(어제~오늘)** = 과거 48시간 이내
- **아카이브:** 기간 필터 적용 전 전체 데이터를 `data/news_archive/YYYY-MM-DD_news.csv`에 세션당 1회 자동 저장

### 5-5. 3대 에너지 전문지
```python
_ENERGY_PUBLISHERS = ("전기신문", "에너지경제", "일렉트릭파워")
```
- 토글 ON 시 3대 전문지 기사만 표시
- 모든 필터(금지어, 키워드 매칭, 유사도 중복)를 **우회**하여 항상 포함

---

## 6. utils/news_crawler.py — 필터링 로직 상세

### 6-1. 전역 금지어 (_BAN_WORDS)
제목 + 요약 결합 텍스트에 하나라도 포함되면 기사 제외 (3대 전문지에는 미적용):
```python
_BAN_WORDS = frozenset([
    # 주식·증권
    "주식", "주가", "증권", "특징주", "시황", "폭락", "폭등",
    "상한가", "하한가", "코스피", "코스닥", "목표가", "종가",
    "시총", "펀드", "투자의견", "목표주가", "매수", "매도", "급등", "급락",
    # 영상·사진·기타 불량 포맷
    "[영상]", "(영상)", "[동영상]", "(동영상)", "다시보기",
    "동영상", "영상뉴스", "포토", "사진", "인터뷰", "언터뷰",
    # 로컬·지자체 행정 뉴스 (사업개발 무관) — 2026-03-05 추가
    "로컬뉴스", "주민자치", "인터배터리",
])
```

### 6-2. 키워드별 조건부 금지어 (_KEYWORD_SPECIFIC_BANS)
특정 키워드로 수집할 때만 적용 (3대 전문지에는 미적용):
```python
_KEYWORD_SPECIFIC_BANS: dict[str, frozenset] = {
    "풍력":     frozenset(["해상", "해상풍력"]),          # 해상풍력은 별도 키워드로 수집
    "ESS":      frozenset(["자율제조", "인터배터리", "전시회"]),   # 제조·전시 무관 기사
    "BESS":     frozenset(["자율제조", "인터배터리", "전시회"]),
    "전력계통":  frozenset(["전기차", "EV충전", "EV 충전"]),      # EV는 별도 산업
    "분산에너지": frozenset(["전기차", "EV충전", "EV 충전"]),
    "수소":     frozenset(["공영충전소"]),                # 소비자용 수소버스 기사
}
```

### 6-3. _is_quality_article() 품질 필터 (2026-03-05 개정)
```
1. 제목에 검색 키워드 없으면 → False  ← 전문지 포함 공통 적용 (개정)
2. 3대 전문지이면 → True (금지어·요약 길이만 우회, 키워드 체크는 적용)
3. 요약 길이 < 30자이면 → False
4. 전역 금지어 포함이면 → False
5. 키워드별 조건부 금지어 포함이면 → False
6. 위 모두 통과 → True
```
> **개정 이유:** 에너지경제·전기신문도 로컬뉴스·지자체 행정·EV 충전 등 무관 기사를 다수 발행함.
> 제목 키워드 체크를 전문지에도 적용해 노이즈 대폭 감소.

### 6-4. _deduplicate_by_similarity() 유사도 중복 제거
- **임계값(threshold):** 0.4 (40%)
- **조건:** (제목 유사도 ≥ 40%) **OR** (요약 유사도 ≥ 40%) → 중복으로 간주하고 제외
- **3대 전문지:** 중복 검사 우회, 항상 포함
- **사용 라이브러리:** Python 내장 `difflib.SequenceMatcher`
- **이유:** 언론사가 단어 순서나 동의어만 바꿔서 보도자료를 베껴 쓰는 패턴 방어

### 6-5. 주요 함수 목록
| 함수 | 역할 |
|---|---|
| `search_naver_news(query, display=100, sort="date", keyword_in_title="")` | 네이버 API 호출 + 품질 필터 + 유사도 중복 제거 |
| `search_with_publishers(query, display_per_pub=10)` | 3대 전문지 집중 검색 (각 언론사명 쿼리에 추가해 3회 호출) |
| `save_to_archive(df)` | `data/news_archive/YYYY-MM-DD_news.csv` 누적 저장 |
| `to_csv_bytes(df)` | UTF-8 BOM CSV 바이트 반환 (엑셀 한글 호환) |
| `news_to_dataframe(news_list)` | 뉴스 리스트 → pandas DataFrame 변환 |

---

## 7. 과거 주요 트러블슈팅 이력

### 이슈 1: 네이버 API 401 인증 오류
- **원인 1:** `.env`의 `NAVER_CLIENT_SECRET` 값에서 숫자 `0`을 영문자 `O`로 오타 (`zOByXCovGJ` → `z0ByXCovGJ`)
- **원인 2:** `.env`의 `NAVER_CLIENT_ID` 대소문자 오류 (`KVPrM83DQimDWn3N_3Uq` → `KVpRm83DQimDWn3N_3Uq`)
- **원인 3:** `.env` 수정 후 Streamlit 서버 재시작 안 함 (모듈 레벨에서 환경변수를 읽으므로 재시작 필수)
- **해결:** `.env` 수정 → Streamlit 프로세스 완전 종료(`taskkill`) → 재시작

### 이슈 2: ImportError (cannot import name 'search_naver_news')
- **원인:** Streamlit 서버가 이전 버전의 모듈을 메모리에 캐싱
- **해결:** `taskkill /F /IM streamlit.exe` 후 재시작

### 이슈 3: 보도자료 복붙 중복 기사 과다
- **해결:** `difflib.SequenceMatcher` 기반 유사도 필터, threshold=0.4, 제목+요약 OR 조건

### 이슈 4: 풍력 탭에 해상풍력 기사 혼입
- **해결:** `_KEYWORD_SPECIFIC_BANS`에 `"풍력": frozenset(["해상", "해상풍력"])` 추가

### 이슈 5: 어제 자 중요 기사 누락
- **원인:** 기간 필터가 24시간으로 설정되어 있었고, display=50으로 수집 모수가 부족했음
- **해결:** display=50→100으로 증가, 기간 필터 "오늘(24시간)" → "최근 2일(어제~오늘)" (48시간)

---

## 8. requirements.txt 현황

```
streamlit>=1.30.0
requests>=2.31.0
beautifulsoup4>=4.12.0
anthropic>=0.18.0
python-dotenv>=1.0.0
feedparser>=6.0.0
pandas>=2.0.0
```
> `difflib`은 Python 내장 라이브러리 — 별도 설치 불필요

---

## 9. 향후 개발 로드맵

### Phase 2: Tab 1 — 입지/규제 분석 (다음 우선순위)
- [ ] `utils/law_api.py` 구현 — 국가법령정보센터 오픈API 연동
- [ ] 조례 키워드 검색 UI 연결
- [ ] Claude AI (`anthropic`) 자동 분석 — 이격거리, 소음, 농지전용 등 핵심 항목 추출
- [ ] 지자체별 필터 (전라남도, 경상남도, 제주도 등)

### Phase 3: Tab 3 — 정책 및 입법 동향
- [ ] 열린국회정보 API 연동 — 에너지 관련 법안 입법예고, 위원회 심의 추적
- [ ] 중앙부처 RSS 연동 (`feedparser` 이미 설치됨):
  - 산업통상자원부: `https://www.motie.go.kr/rss/...`
  - 해양수산부 (해상풍력 관련)
  - 환경부 (환경영향평가)

### Phase 4: Tab 4 — 유관기관 공지사항
- [ ] 한전(KEPCO) 계통 연계 공지 크롤러
- [ ] KPX(전력거래소) SMP/시장 운영 공지 크롤러
- [ ] 한국에너지공단 RPS/REC 공지 크롤러
- [ ] 신안군청 인허가 공고 크롤러

### Tab 2 추가 개선 가능 사항
- [ ] `_KEYWORD_SPECIFIC_BANS`에 필요한 키워드별 금지어 추가 (운영하면서 발견되는 패턴)
- [ ] Claude AI 연동 — 수집된 뉴스 요약·인사이트 자동 생성
- [ ] 주요 기사 알림 (이메일 또는 슬랙 웹훅)

---

## 10. Streamlit 서버 운영

```bash
# 서버 시작
cd "e:\바이브코딩(Gemini,Claude Code)\renewable-energy-dashboard"
streamlit run app.py

# 서버 종료 (Windows)
cmd /c "taskkill /F /IM streamlit.exe"

# 포트 확인 (여러 인스턴스 실행 중일 때)
# 기본 8501, 이미 사용 중이면 8502, 8503, 8504 순으로 자동 할당
```

---

## 11. 코드 설계 원칙 (다음 작업자 준수 사항)

1. **3대 전문지 우회 원칙:** `_BYPASS_PUBLISHERS = frozenset(["전기신문", "에너지경제", "일렉트릭파워"])`. 어떤 필터(금지어, 유사도 중복, 키워드 매칭)도 이 세 언론사는 우회. 절대 변경 금지.
2. **캐시 불변 원칙:** `_fetch_all_keyword_news`는 `@st.cache_data(ttl=3600)`. 수집 로직 변경 후에는 반드시 UI의 "🔄 캐시 갱신" 버튼을 눌러야 반영됨.
3. **아카이브 기간 필터 전 저장 원칙:** `save_to_archive()`는 기간 필터 적용 전 전체 데이터를 저장. 사용자가 어떤 기간을 선택해도 아카이브에는 전체가 보존됨.
4. **display=100 유지:** 네이버 API 최대 수집 한도. 모수를 줄이면 중요 기사 누락 위험.
5. **키워드 in 제목 필터:** `keyword_in_title=kw` 파라미터로 낚시성 기사 제거. 수동 검색(`추가 키워드 직접 검색`)에서는 이 파라미터를 비워둬야 함(현재 코드 그대로).

---

## 12. 배포 상태
- **현재 상태**: ✅ **배포 완료**
- **실운영 URL**: [https://renewable-energy-dashboard-nsmgneobdtz3xqpddasevz.streamlit.app/](https://renewable-energy-dashboard-nsmgneobdtz3xqpddasevz.streamlit.app/)
- **보안 점검**: `.gitignore`에 `.env`, `data/`, `news_archive/` 제외 적용 상태로 푸시됨
- **의존성 점검**: `requirements.txt` 패키지 모두 반영 완료
