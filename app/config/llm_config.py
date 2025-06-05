from crewai import LLM
from app.config.settings import settings


default_X_llm = LLM(
    model='xai/grok-3',
    api_key=settings.XAI_API_KEY,
    stop=None
    )

reasoning_X_llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=settings.XAI_API_KEY,
    stop=None
    )

fast_reasoning_X_llm = LLM(
    model='xai/grok-3-mini-fast',
    api_key=settings.XAI_API_KEY,
    stop=None
    )

pro_Google_llm = LLM(
    model='gemini/gemini-2.5-pro-preview-05-06',
    api_key=settings.GEMINI_API_KEY,
    thinking={"type": "enabled", "budget": 2048},
)

flash_Google_llm = LLM(
    model='gemini/gemini-2.5-flash-preview-05-20',
    api_key=settings.GEMINI_API_KEY,
    thinking={"type": "enabled", "budget": 4096},
)

default_openai_llm = LLM(
    model='openai/o4-mini-2025-04-16',
    api_key=settings.OPENAI_API_KEY,
)