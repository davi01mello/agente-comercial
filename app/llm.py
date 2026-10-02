"""Camada única de acesso ao modelo (Gemini). Todo o resto do app chama SÓ este arquivo.

TODO(T2): implementar `consultar` (pergunta + histórico + base -> resposta citando [EX-0X]).
TODO(T4): implementar `curar_insight` (texto solto -> InsightCreate estruturado).
"""
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings

PROMPTS = Path(__file__).parent / "prompts"


def carregar_prompt(nome: str) -> str:
    """Lê app/prompts/<nome>.md (os prompts são arquivos versionados no Git)."""
    return (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


def _client() -> genai.Client:
    """Cria o cliente do Gemini com a chave e o timeout do .env (o SDK espera milissegundos)."""
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=settings.llm_timeout_s * 1000),
    )
