"""Configuração do app, lida das variáveis de ambiente (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    model_curador: str = "claude-sonnet-5"
    model_consultor: str = "claude-sonnet-5"
    database_url: str = "sqlite:///./data/cerebro.db"
    app_env: str = "dev"


settings = Settings()
