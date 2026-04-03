"""사용 가능한 Gemini 모델 목록 확인"""
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

print("=== 사용 가능한 모델 목록 ===\n")
for model in client.models.list():
    # generateContent 지원 모델만 표시
    if hasattr(model, "supported_actions") and "generateContent" in (model.supported_actions or []):
        print(f"ID: {model.name}")
    elif "flash" in (model.name or "").lower() or "pro" in (model.name or "").lower():
        print(f"ID: {model.name}  (actions: {getattr(model, 'supported_actions', 'N/A')})")
