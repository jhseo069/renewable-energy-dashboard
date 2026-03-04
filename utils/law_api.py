"""
국가법령정보센터 API 연동 유틸리티
- 지자체 조례/입지 규제 검색 및 분석
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

LAW_API_KEY = os.getenv("LAW_API_KEY", "")
BASE_URL = "https://www.law.go.kr/DRF/lawSearch.do"


def search_local_ordinances(query: str, page: int = 1) -> dict:
    """
    국가법령정보센터에서 지자체 조례를 검색합니다.
    (API 연동 예정 - 현재는 placeholder)
    """
    # TODO: 실제 API 연동
    return {
        "status": "placeholder",
        "message": "API 연동 예정입니다. LAW_API_KEY를 .env에 설정해주세요.",
        "query": query,
        "results": [],
    }


def analyze_regulation_with_claude(text: str) -> str:
    """
    Claude API를 사용하여 규제 텍스트를 분석합니다.
    (API 연동 예정 - 현재는 placeholder)
    """
    # TODO: Anthropic Claude API 연동
    return "Claude API 연동 후 분석 결과가 표시됩니다."
