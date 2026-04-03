/**
 * 신재생에너지 부처 보도자료 RSS 자동 수집기
 * =============================================
 * 설치 방법:
 *   1. Google Sheets → 확장 프로그램 → Apps Script
 *   2. 이 코드 전체 붙여넣기
 *   3. SPREADSHEET_ID를 본인 시트 ID로 변경 (Streamlit secrets의 GSHEET_ID와 동일)
 *   4. 저장 후 fetchRSSArticles() 함수를 한 번 수동 실행 (권한 승인)
 *   5. 트리거 설정: 시계 아이콘 → 트리거 추가 → fetchRSSArticles → 시간 기반 → 1시간마다
 */

// ── 설정 ──────────────────────────────────────────────────────────────────
// Streamlit Cloud Secrets의 GSHEET_ID 값과 동일하게 입력하세요
const SPREADSHEET_ID = 'YOUR_GSHEET_ID_HERE';
const SHEET_NAME     = 'press_releases_rss';  // 자동수집 전용 탭
const MAX_ITEMS      = 300;                   // 탭 최대 보관 건수

// ── 수집 대상 부처 RSS (korea.kr 부처별 RSS) ──────────────────────────────
const RSS_SOURCES = [
  { name: '산업부', url: 'https://www.korea.kr/rss/dept_motir.xml' },
  { name: '기후부', url: 'https://www.korea.kr/rss/dept_mcee.xml' },
  { name: '해수부', url: 'https://www.korea.kr/rss/dept_mof.xml'  },
  { name: '농림부', url: 'https://www.korea.kr/rss/dept_mafra.xml'},
  { name: '국토부', url: 'https://www.korea.kr/rss/dept_molit.xml'},
];

// ── 신재생에너지 핵심 키워드 (제목 필터) ──────────────────────────────────
const ENERGY_KEYWORDS = [
  '풍력', '태양광', '신재생', '재생에너지', 'ESS', 'BESS',
  '계통', 'RPS', 'REC', 'PPA', '집적화단지', '공유수면', '산지전용',
  '수소', '분산에너지', '탄소중립', '탄소규제',
  'WTIV', '해상풍력', '어업인 보상', '어업인 협의', '어업피해',
  '농지전용', '농업진흥구역', '개발행위허가', '용도지역', '도시계획',
];

// ── 헬퍼 함수 ─────────────────────────────────────────────────────────────

/** 제목에 신재생 키워드 포함 여부 확인 */
function isEnergyRelated(title) {
  return ENERGY_KEYWORDS.some(kw => title.includes(kw));
}

/** 현재 시각을 KST ISO 문자열로 반환 (YYYY-MM-DDTHH:MM:SS) */
function getKSTNow() {
  const now  = new Date();
  const kst  = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return kst.toISOString().substring(0, 19);
}

/** RFC 822 날짜 → 'YYYY-MM-DD' 변환 */
function parseDate(pubDateStr) {
  try {
    const d = new Date(pubDateStr);
    return Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM-dd');
  } catch (e) {
    return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
  }
}

/** HTML 태그 제거 + 앞뒤 공백 정리 */
function stripHtml(html) {
  return (html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

// ── 메인 수집 함수 (트리거로 1시간마다 실행) ──────────────────────────────
function fetchRSSArticles() {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);

  // 컬럼 헤더 정의 (Streamlit press_releases 구조와 동일)
  const HEADERS = [
    'source', 'category', 'title', 'date',
    'link', 'summary', 'attachments', 'added_at', 'source_type'
  ];

  // 시트 초기화: 헤더가 없으면 추가
  const existingRows = sheet.getLastRow();
  if (existingRows === 0) {
    sheet.appendRow(HEADERS);
  }

  // 기존 링크 목록 (중복 방지)
  const existingLinks = new Set();
  if (existingRows > 1) {
    const data    = sheet.getDataRange().getValues();
    const linkIdx = data[0].indexOf('link');
    if (linkIdx >= 0) {
      data.slice(1).forEach(row => {
        if (row[linkIdx]) existingLinks.add(String(row[linkIdx]).trim());
      });
    }
  }

  const addedAt  = getKSTNow();
  const newRows  = [];

  // ── 부처별 RSS 수집 ──────────────────────────────────────────────────
  for (const src of RSS_SOURCES) {
    try {
      const resp = UrlFetchApp.fetch(src.url, {
        muteHttpExceptions: true,
        headers: {
          'User-Agent': 'Mozilla/5.0 (compatible; KCHRenewableEnergyBot/1.0)',
        },
      });

      if (resp.getResponseCode() !== 200) {
        console.log(`[${src.name}] HTTP ${resp.getResponseCode()} — 건너뜀`);
        continue;
      }

      const xml     = resp.getContentText('UTF-8');
      const doc     = XmlService.parse(xml);
      const channel = doc.getRootElement().getChild('channel');
      if (!channel) continue;

      const items = channel.getChildren('item');
      let srcCount = 0;

      for (const item of items) {
        const title   = (item.getChildText('title')       || '').trim();
        const link    = (item.getChildText('link')        || '').trim();
        const summary = stripHtml(item.getChildText('description') || '');
        const pubDate = (item.getChildText('pubDate')     || '');

        // 키워드 필터
        if (!isEnergyRelated(title)) continue;

        // 중복 체크
        if (existingLinks.has(link)) continue;

        newRows.push([
          src.name,       // source
          '보도자료',      // category
          title,          // title
          parseDate(pubDate), // date
          link,           // link
          summary.substring(0, 300), // summary (최대 300자)
          '[]',           // attachments (JSON 문자열)
          addedAt,        // added_at
          'auto',         // source_type (자동수집 구분용)
        ]);

        existingLinks.add(link);
        srcCount++;
      }

      console.log(`[${src.name}] ${srcCount}건 신규 수집`);

    } catch (e) {
      console.log(`[${src.name}] 수집 실패: ${e.message}`);
    }
  }

  // ── 새 행 일괄 추가 ──────────────────────────────────────────────────
  if (newRows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, HEADERS.length)
         .setValues(newRows);
    console.log(`✅ 총 ${newRows.length}건 추가 완료`);
  } else {
    console.log('ℹ️ 신규 기사 없음');
  }

  // ── 30일 초과 항목 자동 정리 ──────────────────────────────────────────
  _cleanOldItems(sheet);
}

/** 30일 초과 항목 삭제 (최신순 정렬 유지) */
function _cleanOldItems(sheet) {
  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return;

  const headers    = data[0];
  const addedAtIdx = headers.indexOf('added_at');
  if (addedAtIdx < 0) return;

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 30);

  // 아래에서 위로 삭제해야 행 번호 어긋남 없음
  for (let i = data.length - 1; i >= 1; i--) {
    const val = data[i][addedAtIdx];
    if (!val) continue;
    const dt = new Date(val);
    if (dt < cutoff) {
      sheet.deleteRow(i + 1); // 시트는 1-indexed
    }
  }
}
