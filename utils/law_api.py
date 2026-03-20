"""
국가법령정보센터 법령·자치법규 검색 API 연동
================================================
- API 엔드포인트: https://www.law.go.kr/DRF/lawSearch.do
- 인증: OC 파라미터에 API 키 전달 (무료 발급)

[자치법규(조례) 응답 구조 - OrdinSearch]
{
  "OrdinSearch": {
    "totalCnt": "18",
    "law": [ ... ]
  }
}
필드: 자치법규명, 지자체기관명, 자치법규종류, 공포일자, 시행일자,
      자치법규일련번호, 자치법규상세링크

[국가법령 응답 구조 - LawSearch]
{
  "LawSearch": {
    "totalCnt": "3",
    "law": [ ... ]
  }
}
필드: 법령명한글, 법령구분명, 소관부처명, 공포일자, 시행일자,
      법령일련번호, 법령상세링크

[검색 특성]
  - target=ordin: 자치법규(조례·규칙) 검색
  - target=law:   국가법령(법률·시행령·시행규칙) 검색
  - 법규명 검색만 지원 — "이격거리", "소음" 같은 내용어 검색 불가
  - 권장 검색어: "태양광", "풍력", "ESS", "농지법", "전기사업법", "환경영향평가법" 등
"""

import os
import ssl
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv

load_dotenv()

LAW_API_KEY = os.getenv("LAW_API_KEY", "")
_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
_BASE_URL    = "https://www.law.go.kr"

# 한국 정부기관 사이트 호환 헤더 — 브라우저로 위장하여 IP 차단 및 연결 리셋 방지
_REQUEST_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer":         "https://www.law.go.kr/",
    "Origin":          "https://www.law.go.kr",
    "Connection":      "close",  # keep-alive 연결 리셋 방지
}


class _LegacySSLAdapter(HTTPAdapter):
    """한국 정부기관 사이트의 레거시 SSL 설정 호환 어댑터.
    DEFAULT@SECLEVEL=1 으로 구형 암호화 방식을 허용 — ConnectionResetError 방지.
    """
    def init_poolmanager(self, *args, **kwargs):
        try:
            from urllib3.util.ssl_ import create_urllib3_context
            ctx = create_urllib3_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            # Python 3.10+ OP_LEGACY_SERVER_CONNECT 플래그 (구 서버 호환)
            ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
            kwargs["ssl_context"] = ctx
        except Exception:
            pass
        return super().init_poolmanager(*args, **kwargs)


def _make_session() -> requests.Session:
    """법령 API 전용 requests 세션 — 레거시 SSL 어댑터 장착."""
    session = requests.Session()
    try:
        session.mount("https://", _LegacySSLAdapter())
    except Exception:
        pass  # 어댑터 실패 시 기본 세션 폴백
    return session


def get_server_ip() -> str:
    """현재 서버의 외부 IP를 반환합니다. 실패 시 '확인불가' 반환."""
    try:
        resp = requests.get("https://api.ipify.org?format=json", timeout=5)
        return resp.json().get("ip", "확인불가")
    except Exception:
        return "확인불가"


def _fmt_date(s: str) -> str:
    """YYYYMMDD → YYYY-MM-DD 변환. 형식이 다르면 원본 반환."""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def search_ordinances(query: str, display: int = 20, page: int = 1) -> dict:
    """
    국가법령정보센터에서 자치법규(조례·규칙)를 법규명으로 검색합니다.

    ※ 법규명(조례 이름) 검색만 지원됩니다.
       "이격거리", "소음" 등 내용어는 검색 불가 — 아래 권장 키워드 사용 권장:
       "태양광", "풍력", "해상풍력", "ESS", "신재생에너지", "수소", "분산에너지"

    Args:
        query:   검색어 (예: "태양광", "풍력발전", "해상풍력")
        display: 페이지당 결과 수 (최대 20)
        page:    페이지 번호 (1부터 시작)

    Returns:
        {
            "total": int,
            "items": [
                {
                    "name":         str,  ← 자치법규명
                    "org":          str,  ← 지자체기관명
                    "date":         str,  ← 공포일자 (YYYY-MM-DD)
                    "enforce_date": str,  ← 시행일자 (YYYY-MM-DD)
                    "type":         str,  ← 자치법규종류 (조례/규칙)
                    "mst":          str,  ← 일련번호 (상세 링크용)
                    "link":         str,  ← 국가법령정보센터 상세 HTML URL
                },
                ...
            ]
        }

    Raises:
        ValueError:           LAW_API_KEY 미설정 시
        requests.HTTPError:   API 호출 실패 시
    """
    if not LAW_API_KEY:
        raise ValueError("LAW_API_KEY가 .env에 설정되지 않았습니다.")

    resp = _make_session().get(
        _SEARCH_URL,
        params={
            "OC":      LAW_API_KEY,
            "target":  "ordin",   # 자치법규(조례·규칙) 검색
            "query":   query,
            "type":    "JSON",
            "display": display,
            "page":    page,
        },
        headers=_REQUEST_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # IP 미등록 오류 감지
    # law.go.kr는 미등록 IP에서 호출 시 HTTP 200이지만 "result" 키로 오류 메시지를 반환
    if "result" in data:
        raise ValueError(
            f"법령 API 접근 오류: {data.get('result', '')} "
            "— 국가법령정보 공동활용 사이트에서 이 서버의 IP/도메인을 등록해주세요."
        )

    # 실제 응답 루트 키: "OrdinSearch"
    root  = data.get("OrdinSearch", {})
    total = int(root.get("totalCnt", 0))

    # 단건(dict)과 다건(list) 모두 list로 정규화
    raw = root.get("law", [])
    if isinstance(raw, dict):
        raw = [raw]

    items = []
    for item in raw:
        mst        = item.get("자치법규일련번호", "")
        detail_rel = item.get("자치법규상세링크", "")
        # 원문 HTML 링크: 상대경로 → 절대 URL
        link = (_BASE_URL + detail_rel) if detail_rel.startswith("/") else detail_rel

        items.append({
            "name":         item.get("자치법규명", ""),
            "org":          item.get("지자체기관명", ""),
            "date":         _fmt_date(item.get("공포일자", "")),
            "enforce_date": _fmt_date(item.get("시행일자", "")),
            "type":         item.get("자치법규종류", "조례"),
            "mst":          mst,
            "link":         link,
        })

    return {"total": total, "items": items}


def search_national_laws(query: str, display: int = 10, page: int = 1) -> dict:
    """
    국가법령정보센터에서 국가법령(법률·시행령·시행규칙)을 법령명으로 검색합니다.

    Args:
        query:   검색어 (예: "농지법", "전기사업법", "환경영향평가법", "신재생에너지")
        display: 페이지당 결과 수 (최대 20)
        page:    페이지 번호 (1부터 시작)

    Returns:
        {
            "total": int,
            "items": [
                {
                    "name":      str,  ← 법령명한글
                    "org":       str,  ← 소관부처명
                    "date":      str,  ← 공포일자 (YYYY-MM-DD)
                    "enforce_date": str,  ← 시행일자 (YYYY-MM-DD)
                    "type":      str,  ← 법령구분명 (법률/대통령령/부령 등)
                    "mst":       str,  ← 법령일련번호
                    "link":      str,  ← 국가법령정보센터 상세 HTML URL
                    "target":    "law",
                },
                ...
            ]
        }

    Raises:
        ValueError:           LAW_API_KEY 미설정 시
        requests.HTTPError:   API 호출 실패 시
    """
    if not LAW_API_KEY:
        raise ValueError("LAW_API_KEY가 .env에 설정되지 않았습니다.")

    resp = _make_session().get(
        _SEARCH_URL,
        params={
            "OC":      LAW_API_KEY,
            "target":  "law",     # 국가법령 검색
            "query":   query,
            "type":    "JSON",
            "display": display,
            "page":    page,
        },
        headers=_REQUEST_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # 오류 감지
    if "result" in data:
        raise ValueError(
            f"법령 API 접근 오류: {data.get('result', '')} "
            "— 서버 IP/도메인 등록이 필요할 수 있습니다."
        )

    # 국가법령 응답 루트 키: "LawSearch"
    root  = data.get("LawSearch", {})
    total = int(root.get("totalCnt", 0))

    raw = root.get("law", [])
    if isinstance(raw, dict):
        raw = [raw]

    items = []
    for item in raw:
        mst        = item.get("법령일련번호", "")
        detail_rel = item.get("법령상세링크", "")
        link = (_BASE_URL + detail_rel) if detail_rel.startswith("/") else detail_rel

        items.append({
            "name":         item.get("법령명한글", ""),
            "org":          item.get("소관부처명", ""),
            "date":         _fmt_date(item.get("공포일자", "")),
            "enforce_date": _fmt_date(item.get("시행일자", "")),
            "type":         item.get("법령구분명", "법률"),
            "mst":          mst,
            "link":         link,
            "target":       "law",
        })

    return {"total": total, "items": items}
