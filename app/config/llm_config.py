from crewai import LLM
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_xai import ChatXAI
from app.utils.wrappers.google_genai_LLM import GoogleGenAIWrapper
from app.config.settings import settings


default_X_llm = LLM(
    model='xai/grok-3-mini',
    api_key=settings.XAI_API_KEY,
    )

X_llm = ChatXAI(
    model='xai/grok-3-mini-fast',
    api_key=settings.XAI_API_KEY,
)

reasoning_X_llm = LLM(
    model='xai/grok-3-mini',
    api_key=settings.XAI_API_KEY,
    )

fast_reasoning_X_llm = LLM(
    model='xai/grok-3-mini-fast',
    api_key=settings.XAI_API_KEY,
    )

pro_Google_llm = LLM(
    model='gemini/gemini-2.5-pro-preview-05-06',
    api_key=settings.GEMINI_API_KEY,
)

flash_Google_llm_decisive = GoogleGenAIWrapper(ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.1,
))
flash_Google_llm_decisive_reason = GoogleGenAIWrapper(ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.1,
    thinking_budget=-1,
))

flash_Google_llm_creative = GoogleGenAIWrapper(ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.9,
))
flash_Google_llm_creative_reason = GoogleGenAIWrapper(ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.9,
    thinking_budget=-1,
))


flash_Google_llm_reason = LLM(
    model='gemini-2.5-flash-latest',
    thinking={"type": "enabled", "budget": 2048},
)

default_openai_llm = ChatOpenAI(
    model="o3-mini-2025-01-31",
    api_key=settings.OPENAI_API_KEY,
)

decivise_openai_llm = ChatOpenAI(
    model="o3-mini-2025-01-31",
    api_key=settings.OPENAI_API_KEY,
    temperature=0.1,
)

creative_openai_llm = ChatOpenAI(
    model="o3-mini-2025-01-31",
    api_key=settings.OPENAI_API_KEY,
    temperature=0.9,
)