"""Configuração do app, lida das variáveis de ambiente (.env)."""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    model_curador: str = "gemini-3.8-flash"
    model_consultor: str = "gemini-3.8-flash"
    llm_timeout_s: int = 30  # por chamada ao modelo
    llm_prazo_total_s: int = 60  # por pedido do usuário (soma das chamadas, tentativas e esperas)

    # Preço do modelo, em US$ por 1 milhão de tokens, para estimar o custo de cada chamada no log.
    # Padrão: gemini-3.8-flash, válido até 31/12/2026. Sobe em 01/01/2027: confira a página de preços do Gemini.
    preco_entrada_1m: float = 0.75
    preco_saida_1m: float = 3.75  # a saída inclui os tokens de raciocínio (thoughts)
    database_url: str = "sqlite:///./data/cerebro.db"

    # Token da integração interna do Notion (T4). Só no .env: nunca no código, no chat ou em log.
    notion_token: str = ""
    app_env: str = "dev"

    @field_validator("database_url")
    @classmethod
    def _driver_do_postgres(cls, url: str) -> str:
        """A Railway entrega `postgresql://...` (ou `postgres://...`); o SQLAlchemy precisa do driver no nome."""
        for prefixo in ("postgres://", "postgresql://"):
            if url.startswith(prefixo):
                return "postgresql+psycopg://" + url[len(prefixo):]
        return url


settings = Settings()
