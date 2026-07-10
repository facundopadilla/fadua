"""Application settings, loaded from environment variables (and .env locally)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI Analytics Chatbot"
    cors_origins: list[str] = ["http://localhost:5173"]

    # MySQL — not consumed by code yet; wired in when the SQL tool lands.
    database_url: str = "mysql+pymysql://analytics:analytics@localhost:3306/analytics"

    # Redis conversational memory
    redis_url: str = "redis://localhost:6379/0"
    conversation_ttl_seconds: int = 1_209_600  # 14 days (locked decision)

    # LLM — generic, provider-swappable (OpenCode GO models: Qwen, Minimax, GLM, ...).
    # TODO next iteration: consumed by the real PydanticAI agent.
    llm_provider: str = "opencode"
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-pro"


settings = Settings()
