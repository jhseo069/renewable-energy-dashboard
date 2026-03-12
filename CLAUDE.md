# CLAUDE.md — 신재생에너지 사업개발 대시보드

이 파일은 Claude Code가 이 프로젝트에서 작업할 때 반드시 따라야 할 규칙입니다.

---

## 🔒 보안 절대 규칙

1. **credentials 채팅 노출 절대 금지**
   - `private_key`, `client_secret`, API 키 전체 값을 대화창에 출력하지 말 것
   - 서비스 계정 JSON 전문을 절대 응답에 포함하지 말 것
   - 사용자가 JSON 파일을 열면 `client_email` 필드만 알려주고 나머지는 "Streamlit Secrets에 직접 붙여넣으세요"로 안내

2. **API 키 표기**: 메모리/대화에서 키 값은 `...RyZA` 형태로 끝 4자리만 표시

3. **`.env` 파일 절대 커밋 금지** — `.gitignore`에 항상 포함 여부 확인

---

## 프로젝트 개요

- **앱**: 신재생에너지 사업개발팀 사내 대시보드 (Streamlit)
- **배포**: Streamlit Cloud (https://renewable-energy-dashboard-nsmgneobdtz3xqpddasevz.streamlit.app/)
- **언어**: 항상 한국어로 소통, 코드 주석도 한국어
- **현재 버전**: v0.8.4

---

## 핵심 파일 구조

```
app.py                      # 메인 앱 (4탭 + 사이드바)
execution/
  rss_crawler.py            # 부처 RSS (사용 중단, 수동 입력으로 전환)
  law_api.py                # 국회 법안 API
  notice_crawler.py         # 유관기관 공지 크롤러
  ai_analyzer.py            # Gemini AI 분석
utils/
  news_crawler.py           # 네이버 뉴스 API
  law_api.py                # 법령 API
data/
  smp_rec.json              # SMP/REC 데이터 (git 추적 + Google Sheets)
  notices.json              # 공지사항 (git 추적 + Google Sheets)
  press_releases.json       # 보도자료 (git 추적 + Google Sheets)
  attachments/              # 첨부파일 (gitignore)
```

---

## 데이터 영속성 구조 (v0.8.4)

- **우선순위**: Google Sheets → JSON 파일 (폴백)
- `GSHEET_ID` + `[gcp_service_account]`를 Streamlit secrets에 설정하면 자동 활성화
- `_gs_client()`: `gspread.service_account_from_dict()` 사용 (authorize() deprecated)
- Cloud UI 입력 데이터는 Google Sheets에 영구 저장 (배포 재시작 무관)

---

## 코드 작성 원칙

1. 모든 시간은 `get_kst_now()` 사용 (Streamlit Cloud = UTC 서버)
2. `@st.cache_data` 변경 후 반드시 `.clear()` 또는 "🔄 갱신" 안내
3. `added_at` 필드로 단일 항목 고유 식별 (삭제 시 이 값 사용)
4. 공통 헬퍼(`_load_notices` 등)는 사이드바 코드 이전에 정의
5. `gspread.service_account_from_dict()` 사용 — `authorize()` 사용 금지
