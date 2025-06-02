from crewai import LLM
from app.config.settings import settings


default_X_llm = LLM(
    model='xai/grok-3',
    api_key=settings.XAI_API_KEY,
    )

reasoning_X_llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=settings.XAI_API_KEY,
    )

default_Google_llm = LLM(
    model='gemini/gemini-2.5-pro-preview-05-06',
    api_key=settings.GEMINI_API_KEY,
)

default_openai_llm = LLM(
    model='openai/o4-mini-2025-04-16',
    api_key=settings.OPENAI_API_KEY,
)