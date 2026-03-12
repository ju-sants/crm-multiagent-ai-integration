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


# --- Dev Mode: Model Registry & Override Support ---

AVAILABLE_MODELS = {

    # --- HEAVYWEIGHT ---

    # OpenAI — Frontier
    "gpt-5.4": {"provider": "openai", "description": "GPT-5.4 — Latest flagship, state-of-the-art intelligence"},
    "gpt-5.4-2026-03-05": {"provider": "openai", "description": "GPT-5.4 March 2026 snapshot — Pinned flagship version"},
    "gpt-5.4-thinking": {"provider": "openai", "description": "GPT-5.4 Thinking — Native extended reasoning"},
    "gpt-oss-120b": {"provider": "openai", "description": "GPT-OSS 120B — Open-weights heavyweight"},
    "o3-2025-04-16": {"provider": "openai", "description": "OpenAI o3 — Top-tier reasoning (previous gen)"},

    # Google — Frontier
    "gemini-3.1-pro-preview": {"provider": "google", "description": "Gemini 3.1 Pro — Frontier long context & multimodal"},
    "gemini-3.1-pro-preview-customtools": {"provider": "google", "description": "Gemini 3.1 Pro Custom Tools — Optimized for tool calls"},
    "gemini-3-deep-think": {"provider": "google", "description": "Gemini 3 Deep Think — Science & engineering reasoning"},
    "gemini-2.5-pro-preview-05-06": {"provider": "google", "description": "Gemini 2.5 Pro — Reliable performance (previous gen)"},

    # xAI — Frontier
    "xai/grok-4.20-beta": {"provider": "xai", "description": "Grok 4.20 Beta — Flagship, high prompt adherence"},
    "xai/grok-4.20-multiagent-beta": {"provider": "xai", "description": "Grok 4.20 Multiagent — Parallel multi-agent reasoning"},
    "xai/grok-3": {"provider": "xai", "description": "Grok 3 — High-end balanced (previous gen)"},

    # --- MID-RANGE ---

    # OpenAI
    "gpt-5-mini-2025-08-07": {"provider": "openai", "description": "GPT-5 Mini — Cost-optimized intelligence"},
    "o4-mini": {"provider": "openai", "description": "OpenAI o4-mini — Latest reasoning series"},
    "o3-mini-2025-01-31": {"provider": "openai", "description": "OpenAI o3-mini — Specialized reasoning (previous gen)"},
    "gpt-4.1-2025-04-14": {"provider": "openai", "description": "GPT-4.1 — Strong all-rounder (previous gen)"},

    # Google
    "gemini-3.1-flash-preview": {"provider": "google", "description": "Gemini 3.1 Flash — Fast high-performance"},
    "gemini-2.5-flash": {"provider": "google", "description": "Gemini 2.5 Flash — Fast & reliable"},

    # xAI
    "xai/grok-4.1-fast": {"provider": "xai", "description": "Grok 4.1 Fast — Low-latency real-time"},
    "xai/grok-code-fast-1": {"provider": "xai", "description": "Grok Code Fast — Specialized code generation & debugging"},
    "xai/grok-3-mini": {"provider": "xai", "description": "Grok 3 Mini — Balanced for dev tasks"},

    # --- LIGHTWEIGHT ---

    # OpenAI
    "gpt-4.1-mini-2025-04-14": {"provider": "openai", "description": "GPT-4.1 Mini — Fast & efficient (previous gen)"},
    "gpt-4.1-nano-2025-04-14": {"provider": "openai", "description": "GPT-4.1 Nano — Ultra-light (previous gen)"},
    "gpt-4o-mini-2024-07-18": {"provider": "openai", "description": "GPT-4o Mini — Cost-effective (previous gen)"},

    # Google
    "gemini-3.1-flash-lite-preview": {"provider": "google", "description": "Gemini 3.1 Flash-Lite — Ultra-low cost"},
    "gemini-2.5-flash-lite-preview-06-17": {"provider": "google", "description": "Gemini 2.5 Flash-Lite — Ultra-low cost (previous gen)"},

    # xAI
    "xai/grok-3-mini-fast": {"provider": "xai", "description": "Grok 3 Mini Fast — Maximum speed"},
}


DEFAULT_AGENT_MODELS = {
    "RoutingAgent": "xai/grok-3-mini-fast",
    "StrategicAdvisor": "xai/grok-3-mini-fast",
    "IncrementalStrategicPlannerAgent": "xai/grok-3-mini-fast",
    "CommunicationAgent": "xai/grok-3-mini-fast",
    "SystemOperationsAgent": "xai/grok-3-mini-fast",
    "RegistrationDataCollectorAgent": "xai/grok-3-mini-fast",
    "PurchaseConfirmationAgent": "xai/grok-3-mini-fast",
    "VerifySystemActionAgent": "xai/grok-3-mini-fast",
    "HistorySummarizer": "o3-mini-2025-01-31",
    "DataQualityAgent": "o3-mini-2025-01-31",
    "StateSummarizerAgent": "o3-mini-2025-01-31",
    "ProfileEnhancerAgent": "o3-mini-2025-01-31",
    "FollowUpAgent": "o3-mini-2025-01-31",
}


def create_llm(model_key: str, temperature: float = None, top_p: float = None, max_tokens: int = None):
    """Create a langchain LLM instance from a model key string."""
    config = AVAILABLE_MODELS.get(model_key)
    if not config:
        raise ValueError(f"Unknown model: {model_key}")

    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if config["provider"] == "xai":
        xai_model = model_key.removeprefix("xai/")
        return ChatXAI(model=xai_model, api_key=settings.XAI_API_KEY, **kwargs)
    elif config["provider"] == "openai":
        return ChatOpenAI(model=model_key, api_key=settings.OPENAI_API_KEY, **kwargs)
    elif config["provider"] == "google":
        return ChatGoogleGenerativeAI(
            model=model_key, google_api_key=settings.GEMINI_API_KEY, **kwargs
        )

    raise ValueError(f"Unsupported provider: {config['provider']}")


def create_crewai_llm(model_key: str, temperature: float = None, top_p: float = None, max_tokens: int = None):
    """Create a crewai.LLM instance (litellm-based) from a model key string.
    Use this for benchmarks where the LLM is passed to CrewAI Agent directly."""
    config = AVAILABLE_MODELS.get(model_key)
    if not config:
        raise ValueError(f"Unknown model: {model_key}")

    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if config["provider"] == "google":
        litellm_model = f"gemini/{model_key}"
    elif config["provider"] == "openai":
        litellm_model = f"openai/{model_key}"
    else:
        litellm_model = model_key

    return LLM(model=litellm_model, **kwargs)


def get_llm(agent_role: str = None, contact_id: str = None, default_llm=None):
    """
    Get LLM for an agent with dev mode override support.

    In DEV_CHAT_MODE, checks Redis for per-session or global model overrides.
    Falls back to default_llm (or X_llm).
    """
    _default = default_llm if default_llm is not None else X_llm

    if not settings.DEV_CHAT_MODE or not agent_role:
        return _default

    try:
        from app.services.redis_service import get_redis
        redis = get_redis()

        if contact_id:
            override = redis.get(f"dev:model_override:{contact_id}:{agent_role}")
            if override:
                return create_llm(override)

        override = redis.get(f"dev:model_override:global:{agent_role}")
        if override:
            return create_llm(override)
    except Exception:
        pass

    return _default