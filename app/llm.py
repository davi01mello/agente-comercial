"""Camada única de acesso ao Claude. Todo o resto do app chama SÓ este arquivo.

TODO(T2): implementar `perguntar_claude`.
TODO(T4): implementar `curar_insight` (texto solto -> InsightCreate estruturado).
TODO(T7): implementar `consultar` (pergunta + playbook -> resposta com fontes).
"""
from pathlib import Path

from app.config import settings

PROMPTS = Path(__file__).parent / "prompts"


def carregar_prompt(nome: str) -> str:
    """Lê app/prompts/<nome>.md (os prompts são arquivos versionados no Git)."""
    return (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


def perguntar_claude(mensagem: str, system: str = "") -> str:
    raise NotImplementedError("T2: fazer a primeira chamada à API do Claude")
