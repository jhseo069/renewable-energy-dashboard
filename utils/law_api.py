"""
국가법령정보센터 자치법규(조례) 검색 API 연동
================================================
- 신재생에너지 관련 지자체 조례 키워드 검색
- API 엔드포인트: https://www.law.go.kr/DRF/lawSearch.do
- 인증: OC 파라미터에 API 키 전달 (무료 발급)
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

LAW_API_KEY = os.getenv("LAW_API_KEY", "")
_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"


def _fmt_date(s: str) -> str:
    """YYYYMMDD → YYYY-MM-DD 변환. 형식이 다르면 원본 반환."""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def search_ordinances(query: str, display: int = 20, page: int = 1) -> dict:
    """
    국가법령정보센터에서 자치법규(조례·규칙)를 키워드로 검색합니다.

    Args:
        query:   검색어 (예: "태양광 이격거리", "풍력 소음 기준")
        display: 페이지당 결과 수 (최대 20)
        page:    페이지 번호 (1부터 시작)

    Returns:
        {
            "total": int,       ← 전체 검색 건수
            "items": [
                {
                    "name":         str,  ← 법규명
                    "org":          str,  ← 자치단체명
                    "date":         str,  ← 공포일자 (YYYY-MM-DD)
                    "enforce_date": str,  ← 시행일자 (YYYY-MM-DD)
                    "type":         str,  ← 법규유형 (조례/규칙 등)
                    "law_id":       str,  ← 법규ID (상세 링크 구성에 사용)
                    "link":         str,  ← 국가법령정보센터 상세 페이지 URL
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

    resp = requests.get(
        _SEARCH_URL,
        params={
            "OC":      LAW_API_KEY,
            "target":  "ordin",   # 자치법규(조례·규칙) 검색 대상
            "query":   query,
            "type":    "JSON",
            "display": display,
            "page":    page,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    # API 응답 루트 키: "자치법규" 또는 "법령" (버전에 따라 다를 수 있음)
    root = data.get("자치법규") or data.get("법령") or {}
    total = int(root.get("@현재총건수", 0))

    # 단건 결과는 dict, 다건 결과는 list로 옴 → 항상 list로 정규화
    raw = root.get("자치법규") or root.get("법령") or []
    if isinstance(raw, dict):
        raw = [raw]

    items = []
    for item in raw:
        law_id = item.get("법규ID", "")
        items.append({
            "name":         item.get("법규명", ""),
            "org":          item.get("자치단체명", ""),
            "date":         _fmt_date(item.get("공포일자", "")),
            "enforce_date": _fmt_date(item.get("시행일자", "")),
            "type":         item.get("법규유형", "조례"),
            "law_id":       law_id,
            # 자치법규 상세 페이지 URL (법규ID 기반)
            "link": f"https://www.law.go.kr/ordinInfoP.do?ordinSeq={law_id}" if law_id else "",
        })

    return {"total": total, "items": items}
