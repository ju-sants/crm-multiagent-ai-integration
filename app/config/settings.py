from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_MODEL: str = "xai/grok-3-mini-beta"
    
    XAI_API_KEY: str = "your_xai_api_key_here"
    GEMINI_API_KEY: str = "your_gemini_api_key_here"
    CALLBELL_API_KEY: str = "your_callbell_api_key_here"
    
    LOG_LEVEL: str = "INFO"
    

settings = Settings()