from crewai import LLM
from app.config.settings import settings


default_llm = LLM(
    model='xai/grok-3',
    api_key=settings.XAI_API_KEY,
    stream=True
    )