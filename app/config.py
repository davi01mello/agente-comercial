"""Configuração do app, lida das variáveis de ambiente (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    model_curador: str = "gemini-3.8-flash"
    model_consultor: str = "gemini-3.8-flash"
    llm_timeout_s: int = 30
    database_url: str = "sqlite:///./data/cerebro.db"
    app_env: str = "dev"


settings = Settings()
