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
    
    LOG_LEVEL: str = "INFO"
    
    MAX_RETRIES_MODEL: int = 500
    
    ALLOWED_CHATS: list[str] = [
        '71464be80c504971ae263d710b39dd1f', # Juan
        # '2fa9529f9c1e4ed9b8ddea6c6a4272e8', # valdir
        # '7b337e574d63473ba0aba7e7de543a48', # ana paula
        # 'd3c9a42068b44b47bfbf6fc8adf62f71', # deibisson empresa
        # 'e426520a46f54bbeb5b98a76e95b1bbb', # cristiane
        # 'ff1b97c206e544f89127600a1a074d27', # aila
        # '8544e093bcdd4f47bb3a5d7da1ac1ad7', # jenifer
        # '7fee5fb4c62d41f98e027e86f57c16c8', # deibisson pessoal
        # 'acfe198b10254da0b8c6f1b46df07c94', # Roberta
        # 'ecad1a70b0004d7580398f96f8074489' # Gisele
        ]

    
    REDIS_HOST: str = '...'
    REDIS_PORT: str = '...'
    REDIS_PASSWORD: str = '...'
    REDIS_DB_MAIN: int = 7
    
    
settings = Settings()