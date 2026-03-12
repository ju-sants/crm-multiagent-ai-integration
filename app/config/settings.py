from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_STREAM: bool = True
    DEV_CHAT_MODE: bool = False
    
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

    AGENTS_PROMPT_FILE: str = 'app/crews/agents_definitions/prompts/agents.yaml'
    TASKS_PROMPT_FILE: str = 'app/crews/agents_definitions/prompts/tasks.yaml'
    
    REDIS_HOST: str = 'localhost'
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = '...'
    REDIS_DB_MAIN: int = 0

    # SITES PASSWORDS
    ESEYE_BASE_URL: str = "..."

    SMS_BARATO_URL: str = "..."
    SMS_BARATO_PASSWORD: str = '...'
    SMS_BARATO_USER: str = '...'
    
    VS_COMPANY: str = "..."
    VS_LOGIN: str = "..."
    VS_SENHA: str = "..."

    VIVO_HOST: str = "..."
    VIVO_KEY_PASSWORD: str = "..."

    VEYE_BASE_URL: str = "..."
    VEYE_LOGIN: str = "..."
    VEYE_PASSWORD: str = "..."

    LINK_BASE_URL: str = "..."
    LINK_LOGIN: str = "..."
    LINK_PASSWORD: str = "..."

    ALLCOM_BASE_URL: str = "..."
    ALLCOM_TOKEN: str = "..."
    ALLCOM_USER: str = "..."
    ALLCOM_PASSWORD: str = "..."

settings = Settings()