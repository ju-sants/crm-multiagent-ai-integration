from crewai import LLM
from app.config.settings import settings


default_X_llm = LLM(
    model='xai/grok-3',
    api_key=settings.XAI_API_KEY,
    stream=settings.LLM_STREAM
    )

reasoning_X_llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=settings.XAI_API_KEY,
    stream=settings.LLM_STREAM
    )

default_Google_llm = LLM(
    model='gemini/gemini-2.5-flash-preview-04-17',
    api_key=settings.GEMINI_API_KEY,
)