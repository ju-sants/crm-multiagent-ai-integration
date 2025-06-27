from crewai import LLM
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config.settings import settings


default_X_llm = LLM(
    model='xai/grok-3',
    api_key=settings.XAI_API_KEY,
    stop=None
    )

reasoning_X_llm = LLM(
    model='xai/grok-3-mini',
    api_key=settings.XAI_API_KEY,
    stop=None,
    stream=True
    )

fast_reasoning_X_llm = LLM(
    model='xai/grok-3-mini-fast',
    api_key=settings.XAI_API_KEY,
    stop=None
    )

pro_Google_llm = LLM(
    model='gemini/gemini-2.5-pro-preview-05-06',
    api_key=settings.GEMINI_API_KEY,
)

flash_Google_llm_decisive = ChatGoogleGenerativeAI(
    model='gemini/gemini-2.5-flash-preview-05-20',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.1,
)
flash_Google_llm_decisive_reason = ChatGoogleGenerativeAI(
    model='gemini/gemini-2.5-flash-preview-05-20',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.1,
    thinking_budget=-1,
)

flash_Google_llm_creative = ChatGoogleGenerativeAI(
    model='gemini/gemini-2.5-flash-preview-05-20',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.9,
)
flash_Google_llm_creative_reason = ChatGoogleGenerativeAI(
    model='gemini/gemini-2.5-flash-preview-05-20',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.9,
    thinking_budget=-1,
)


flash_Google_llm_reason = LLM(
    model='gemini/gemini-2.5-flash-preview-05-20',
    thinking={"type": "enabled", "budget": 2048},
)

default_openai_llm = ChatOpenAI(
    model="o4-mini-2025-04-16",
    api_key=settings.OPENAI_API_KEY,
)
