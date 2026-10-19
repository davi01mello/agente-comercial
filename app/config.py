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

    # Google Drive (T6). A conta de serviço lê a pasta com o escopo drive.readonly. A credencial vem de UMA destas:
    # o caminho do JSON (GOOGLE_APPLICATION_CREDENTIALS, no computador) ou o conteúdo do JSON
    # (GOOGLE_SERVICE_ACCOUNT_JSON, na Railway). Só no .env: nunca no código, no chat ou em log.
    google_application_credentials: str = ""
    google_service_account_json: str = ""
    drive_pasta_id: str = ""  # a pasta "Conhecimento Comercial" (a raiz da leitura, com as subpastas)
    drive_max_mb: int = 30  # arquivo maior que isto não é baixado (os PDFs de slides de 50 MB não têm texto mesmo)
    drive_max_trechos: int = 12  # documento com mais trechos (~96 mil caracteres) fica só na busca, sem ir ao curador
    drive_sync_intervalo_min: int = 0  # 0 = desligado; >0: o servidor sincroniza o Drive sozinho a cada N minutos
    drive_sync_teto_usd: float = 0.5  # o teto de gasto do curador em cada sincronização automática

    # Login (T5): entrar com a conta Google do CITi. O cliente OAuth se cria no Google Cloud (docs/deploy-railway.md).
    # Sem GOOGLE_CLIENT_ID no dev, o login fica desligado (entra como "Dev local"). Em produção (APP_ENV=prod) o app
    # NÃO sobe sem login configurado. Só no .env: nunca no código, no chat ou em log.
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = ""  # assina o cookie de sessão; em prod: uma string longa e aleatória, só do servidor
    app_url: str = "http://localhost:8000"  # o endereço PÚBLICO do app: o Google volta em APP_URL/auth/callback
    auth_dominio: str = "citi.org.br"  # só e-mails deste domínio entram
    sessao_dias: int = 7

    @field_validator("database_url")
    @classmethod
    def _driver_do_postgres(cls, url: str) -> str:
        """A Railway entrega `postgresql://...` (ou `postgres://...`); o SQLAlchemy precisa do driver no nome."""
        for prefixo in ("postgres://", "postgresql://"):
            if url.startswith(prefixo):
                return "postgresql+psycopg://" + url[len(prefixo):]
        return url


settings = Settings()
