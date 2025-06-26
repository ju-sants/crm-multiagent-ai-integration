from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_STREAM: bool = True
    
    XAI_API_KEY: str = "..."
    GEMINI_API_KEY: str = "..."
    CALLBELL_API_KEY: str = "..."
    OPENAI_API_KEY: str = "..."
    ELEVEN_LABS_API_KEY: str = '...'
    
    X_GLADIA_KEY: str = "..."
    APPID_IMAGE_DESCRIPTION: str = '...'
    SECRET_IMAGE_DESCRIPTION: str = '...'

    PLATAFORMA_X_TOKEN: str = "..."

    GMAPS_API_KEY: str = "..."
    
    LOG_LEVEL: str = "INFO"
    
    MAX_RETRIES_MODEL: int = 500
    
    REDIS_HOST: str = '...'
    REDIS_PORT: str = '...'
    REDIS_PASSWORD: str = '...'
    REDIS_DB_MAIN: int = 7
    
    
settings = Settings()