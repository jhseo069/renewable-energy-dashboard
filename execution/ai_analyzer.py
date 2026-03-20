"""
Gemini AI 요약 분석 모듈
========================
Layer 3 (Execution) — 결정론적 AI 분석 스크립트

기능:
  - Tab 1: 지자체 조례 / 국가법령 원문 분석 (핵심 규제, 사업개발 유의점, 대응 방안)
  - Tab 2: 뉴스 키워드별 동향 분석

원문 수집 방식:
  - 1순위: law.go.kr DRF JSON API (target=ordin 또는 target=law) → 조문 전체 텍스트 추출
  - 2순위: HTML 스크래핑 (JSON 실패 시 폴백)
  - 3순위: 조례명/법령명만으로 추론 (원문 수집 완전 실패 시)

사용 패키지: google-genai (신버전 — google-generativeai 대체)
사용 모델  : gemini-3-flash-preview
예외 처리  : API 키 오류 / 원문 수집 실패 / 생성 오류 각각 독립 처리
"""

import os
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_LAW_API_KEY    = os.getenv("LAW_API_KEY", "")
_MODEL_NAME     = "gemini-3-flash-preview"
_DRF_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
_BASE_URL        = "https://www.law.go.kr"

# ── 조례/법령 분석 시스템 프롬프트 ─────────────────────────────────
_ORDINANCE_SYSTEM_PROMPT = """당신은 신재생에너지(태양광·풍력·해상풍력·ESS·수소) 사업개발 전문 컨설턴트입니다.
제공된 조례 또는 법령 원문을 분석하여 반드시 아래 3단 형식으로 응답하세요.

**1. 핵심 규제 내용**
- 이격거리(민가·학교·도로·하천 기준별 수치), 소음 기준(dB), 설치 가능 구역·용도지역, 규모 제한, 인허가 조건 등
- **수치 기준이 있으면 모두 명시** (예: 민가 이격 500m, 소음 45dB 이하 등)
- 태양광·풍력·ESS·해상풍력별로 구분하여 서술
- 원문에 있는 조문 번호도 함께 표기 (예: 제20조의2)

**2. 사업개발 시 유의점**
- 이 규제가 신재생에너지 사업 인허가에 미치는 실무적 영향
- 특히 까다롭거나 사업성에 직접 영향을 미치는 조항 중심으로 서술
- 준수하지 않을 경우 발생하는 불이익(허가 거부, 과태료 등)

**3. 대응 방안**
- 규제 준수를 위한 입지 선정·설계 전략 (구체적 수치 기반)
- 허가 취득 시 유의사항 및 절차
- 예외 조항이나 완화 가능한 조건이 있다면 반드시 언급

※ 원문에 있는 내용만 분석하세요. 원문이 없는 경우 추론임을 명시하고, 실제 확인을 권고하세요."""

# ── 뉴스 동향 분석 시스템 프롬프트 ──────────────────────────────────
_NEWS_SYSTEM_PROMPT = """당신은 신재생에너지(태양광·풍력·해상풍력·ESS) 사업개발 전문 컨설턴트입니다.
제공된 최근 뉴스 목록을 읽고, 반드시 아래 3단 형식으로 응답하세요.

**1. 핵심 규제/정책 변화**
- 이번 기간 주목해야 할 정책·규제 변화 (구체적 수치·일정 포함)

**2. 사업개발 시 유의점**
- 뉴스 트렌드가 신재생에너지 사업 개발에 미치는 영향
- 리스크 요인 중심으로 서술

**3. 대응 방안**
- 단기(1개월 내) 및 중기(3개월 내) 대응 전략 제언

※ 반드시 간결하고 실무 중심으로 작성하세요."""


def _get_client() -> genai.Client:
    """Gemini 클라이언트 반환. API 키 없으면 ValueError 발생.
    우선순위: 환경변수(.env) → Streamlit Secrets → 오류
    """
    key = _GEMINI_API_KEY
    # Streamlit Cloud에서 os.getenv()로 못 읽는 경우 st.secrets 폴백
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
    if not key:
        raise ValueError(
            "GEMINI_API_KEY가 설정되지 않았습니다. "
            ".env 파일 또는 Streamlit Cloud Secrets에 GEMINI_API_KEY를 추가하세요."
        )
    return genai.Client(api_key=key)


def _fetch_text_via_json_api(mst: str, target: str = "ordin") -> str:
    """
    law.go.kr DRF JSON API로 조문 전체 텍스트를 수집합니다.
    target: "ordin" (자치법규) 또는 "law" (국가법령)
    실패 시 빈 문자열 반환.
    """
    if not mst or not _LAW_API_KEY:
        return ""
    try:
        resp = requests.get(
            _DRF_SERVICE_URL,
            params={
                "OC":     _LAW_API_KEY,
                "target": target,
                "MST":    mst,
                "type":   "JSON",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        svc = data.get("LawService", {})

        # 조문 → 조 배열에서 조내용 추출
        articles_root = svc.get("조문", {})
        articles = articles_root.get("조", [])
        if isinstance(articles, dict):
            articles = [articles]

        # 부칙 텍스트도 포함
        addendum = svc.get("부칙", {}).get("부칙내용", "")

        lines = []
        for a in articles:
            content = a.get("조내용", "")
            if content:
                lines.append(content)
        if addendum:
            lines.append(addendum)

        text = "\n".join(lines)
        # 최대 10,000자 (Gemini 토큰 여유)
        return text[:10000]
    except Exception:
        return ""


def _fetch_text_via_html(url: str) -> str:
    """
    조례/법령 원문 HTML에서 텍스트를 추출합니다. (폴백용)
    실패 시 빈 문자열 반환.
    """
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; KCHRenewableEnergyDashboard/1.0)",
            "Referer": _BASE_URL,
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        body = (
            soup.find("div", class_="law-body")
            or soup.find("div", id="lawContent")
            or soup.find("article")
            or soup.body
        )
        if body:
            return body.get_text(separator="\n", strip=True)[:8000]
        return ""
    except Exception:
        return ""


def analyze_ordinance(
    law_name: str,
    org: str,
    url: str = "",
    mst: str = "",
    target: str = "ordin",
    custom_question: str = "",
) -> str:
    """
    지자체 조례 또는 국가법령 원문을 Gemini AI로 분석합니다.

    Args:
        law_name:        법령명 (예: "신안군 해상풍력발전 설치 및 관리 조례", "농지법")
        org:             기관명 (예: "신안군", "농림축산식품부")
        url:             국가법령정보센터 원문 HTML URL (없으면 MST로 시도)
        mst:             법령 일련번호 (JSON API 원문 수집에 사용 — 우선순위 1순위)
        target:          "ordin" (자치법규) 또는 "law" (국가법령)
        custom_question: 사용자 직접 입력 질문 (입력 시 표준 분석 대신 질문에 답변)

    Returns:
        str: 마크다운 형식의 분석 결과

    Raises:
        ValueError:  GEMINI_API_KEY 미설정
        Exception:   Gemini API 호출 실패
    """
    client = _get_client()

    # 원문 수집 시도 (우선순위: JSON API → HTML 스크래핑 → 폴백)
    law_text = _fetch_text_via_json_api(mst, target=target)
    if not law_text:
        law_text = _fetch_text_via_html(url)

    kind = "조례" if target == "ordin" else "법령"

    # 원문 유무에 따라 프롬프트 분기
    if law_text:
        base = (
            f"다음은 '{org}'의 '{law_name}' {kind} 원문입니다.\n\n"
            f"{law_text}\n\n"
        )
        if custom_question:
            # 커스텀 질문 모드: 원문 기반으로 질문에 답변
            prompt = (
                base
                + f"위 {kind} 원문을 바탕으로 아래 질문에 답변해 주세요. "
                "원문에 있는 조문 번호와 수치를 근거로 구체적으로 답변하세요.\n\n"
                f"【질문】 {custom_question}"
            )
        else:
            # 표준 분석 모드
            prompt = (
                base
                + f"위 {kind}를 신재생에너지 사업개발 관점에서 분석해 주세요. "
                "원문에 있는 수치(이격거리, 소음 기준 등)를 빠짐없이 포함하세요."
            )
    else:
        # 원문 수집 실패 — 추론 모드 (폴백)
        fallback_note = (
            f"※ 참고: {kind} 원문을 직접 가져오지 못했습니다. "
            f"{kind}명을 바탕으로 일반적인 내용을 추론합니다. "
            "실제 원문은 국가법령정보센터(law.go.kr)에서 직접 확인하시기 바랍니다.\n\n"
        )
        if custom_question:
            prompt = (
                f"'{org}'의 '{law_name}' {kind}에 대한 질문입니다.\n\n"
                + fallback_note
                + f"【질문】 {custom_question}"
            )
        else:
            prompt = (
                f"'{org}'의 '{law_name}' {kind}에 대해 신재생에너지 사업개발 관점에서 분석해 주세요.\n\n"
                + fallback_note
            )

    # 커스텀 질문 시 시스템 프롬프트를 간결한 Q&A 모드로 전환
    system_prompt = (
        _ORDINANCE_SYSTEM_PROMPT if not custom_question
        else (
            "당신은 신재생에너지(태양광·풍력·해상풍력·ESS·수소) 사업개발 전문 컨설턴트입니다. "
            "제공된 법령 원문을 바탕으로 사용자의 질문에 명확하고 구체적으로 답변하세요. "
            "원문의 조문 번호와 수치를 근거로 인용하고, 실무적으로 중요한 사항을 강조하세요."
        )
    )

    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )
    return response.text


def analyze_news_trends(news_list: list[dict], keyword: str) -> str:
    """
    키워드별 뉴스 목록을 Gemini AI로 동향 분석합니다.

    Args:
        news_list: [{"title": str, "summary": str, "source": str, "date": str}, ...]
        keyword:   분석 키워드 (예: "해상풍력")

    Returns:
        str: 마크다운 형식의 3단 동향 분석 결과

    Raises:
        ValueError:  GEMINI_API_KEY 미설정
        Exception:   Gemini API 호출 실패
    """
    if not news_list:
        return "분석할 뉴스가 없습니다."

    client = _get_client()

    # 최대 20건 — 토큰 한도 및 응답 품질 고려
    sample = news_list[:20]
    news_text = "\n\n".join(
        f"[{i + 1}] {n.get('date', '')} | {n.get('source', '')} | {n.get('title', '')}\n"
        f"{n.get('summary', '')}"
        for i, n in enumerate(sample)
    )

    prompt = (
        f"다음은 '{keyword}' 관련 최근 뉴스 {len(sample)}건입니다.\n\n"
        f"{news_text}\n\n"
        "위 뉴스들을 신재생에너지 사업개발 관점에서 동향 분석해 주세요."
    )

    client = _get_client()
    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_NEWS_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=1500,
        ),
    )
    return response.text
