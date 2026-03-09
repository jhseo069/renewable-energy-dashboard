"""
Gemini AI 요약 분석 모듈
========================
Layer 3 (Execution) — 결정론적 AI 분석 스크립트

기능:
  - Tab 1: 지자체 조례 원문 분석 (핵심 규제, 사업개발 유의점, 대응 방안)
  - Tab 2: 뉴스 키워드별 동향 분석

사용 패키지: google-genai (신버전 — google-generativeai 대체)
사용 모델  : gemini-2.5-flash
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
_MODEL_NAME     = "gemini-2.5-flash"

# ── 조례 분석 시스템 프롬프트 ────────────────────────────────────────
_ORDINANCE_SYSTEM_PROMPT = """당신은 신재생에너지(태양광·풍력·해상풍력·ESS) 사업개발 전문 컨설턴트입니다.
제공된 지자체 조례 원문(또는 조례명)을 읽고, 반드시 아래 3단 형식으로 응답하세요.

**1. 핵심 규제 내용**
- 이격거리(민가·도로·하천 기준), 소음 기준(dB), 설치 가능 구역·용도지역, 규모 제한 등
- 수치 기준이 있으면 반드시 포함

**2. 사업개발 시 유의점**
- 이 조례가 태양광·풍력·해상풍력 사업 인허가에 미치는 실무적 영향
- 특히 주의해야 할 조항 중심으로 서술

**3. 대응 방안**
- 규제 준수를 위한 설계·입지 선정 전략
- 허가 취득 시 유의사항

※ 반드시 간결하고 실무 중심으로 작성하세요. 원문이 없으면 조례명 기반으로 일반적인 내용을 추론하되,
   추론임을 명시하세요."""

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
    """Gemini 클라이언트 반환. API 키 없으면 ValueError 발생."""
    if not _GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY가 설정되지 않았습니다. "
            ".env 파일 또는 Streamlit Cloud Secrets에 GEMINI_API_KEY를 추가하세요."
        )
    return genai.Client(api_key=_GEMINI_API_KEY)


def _fetch_ordinance_text(url: str) -> str:
    """
    조례 원문 HTML에서 텍스트를 추출합니다.
    실패 시 빈 문자열 반환 (예외 미발생 — 폴백 처리용).
    """
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; KCHRenewableEnergyDashboard/1.0)",
            "Referer": "https://www.law.go.kr",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # law.go.kr 조례 원문 본문 영역 순서대로 탐색
        body = (
            soup.find("div", class_="law-body")
            or soup.find("div", id="lawContent")
            or soup.find("article")
            or soup.body
        )
        if body:
            # 최대 8,000자 — Gemini 토큰 한도 고려
            return body.get_text(separator="\n", strip=True)[:8000]
        return ""
    except Exception:
        # 원문 수집 실패는 조례명 기반 분석으로 폴백 — 예외 미전파
        return ""


def analyze_ordinance(law_name: str, org: str, url: str = "") -> str:
    """
    지자체 조례 원문을 Gemini AI로 분석합니다.

    Args:
        law_name: 조례명 (예: "신안군 해상풍력발전 설치 및 관리 조례")
        org:      지자체 기관명 (예: "신안군")
        url:      국가법령정보센터 원문 URL (없으면 조례명만으로 분석)

    Returns:
        str: 마크다운 형식의 3단 분석 결과

    Raises:
        ValueError:  GEMINI_API_KEY 미설정
        Exception:   Gemini API 호출 실패
    """
    client = _get_client()

    # 원문 텍스트 수집 시도 (실패 시 빈 문자열)
    law_text = _fetch_ordinance_text(url)

    if law_text:
        prompt = (
            f"다음은 '{org}'의 '{law_name}' 조례 원문입니다.\n\n"
            f"{law_text}\n\n"
            "위 조례를 신재생에너지 사업개발 관점에서 분석해 주세요."
        )
    else:
        # 원문 수집 실패 — 조례명만으로 일반 분석 (폴백)
        prompt = (
            f"'{org}'의 '{law_name}' 조례에 대해 신재생에너지 사업개발 관점에서 분석해 주세요.\n\n"
            "※ 참고: 조례 원문을 직접 가져오지 못했습니다. "
            "조례명을 바탕으로 일반적인 내용을 추론하여 분석합니다. "
            "실제 조례 원문은 국가법령정보센터(law.go.kr)에서 직접 확인하시기 바랍니다."
        )

    try:
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_ORDINANCE_SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=1024,
            ),
        )
        return response.text
    except Exception as e:
        raise Exception(f"Gemini API 호출 실패: {e}") from e


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

    try:
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_NEWS_SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=1024,
            ),
        )
        return response.text
    except Exception as e:
        raise Exception(f"Gemini API 호출 실패: {e}") from e
