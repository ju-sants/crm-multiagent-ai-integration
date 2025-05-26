from crewai import LLM
from app.config.settings import settings


default_llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=settings.XAI_API_KEY,
    reasoning_effort='high',
    stream=True
    )