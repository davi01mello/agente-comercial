"""Camada única de acesso ao modelo (Gemini). Todo o resto do app chama SÓ este arquivo.

TODO(T4): implementar `curar_insight` (texto solto -> InsightCreate estruturado).
"""
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types

from app.config import settings
from app.knowledge import carregar_base

PROMPTS = Path(__file__).parent / "prompts"


class ErroLLM(Exception):
    """Falha ao falar com o modelo. A mensagem já vem pronta para mostrar ao usuário."""


def carregar_prompt(nome: str) -> str:
    """Lê app/prompts/<nome>.md (os prompts são arquivos versionados no Git)."""
    return (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


def _client() -> genai.Client:
    """Cria o cliente do Gemini com a chave e o timeout do .env (o SDK espera milissegundos)."""
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=settings.llm_timeout_s * 1000),
    )


def _system_consultor() -> str:
    """Camadas do agente: instruções (base + consultor) e conhecimento (a base inteira)."""
    return "\n\n".join([
        carregar_prompt("base"),
        carregar_prompt("consultor"),
        "# BASE DE CONHECIMENTO\n\n" + carregar_base(),
    ])


def _traduzir_erro(e: errors.APIError) -> str:
    """Transforma o erro técnico da API numa frase que o usuário entende."""
    if e.code in (401, 403) or "API key" in (e.message or ""):
        return "A chave do Gemini é inválida. Confira GEMINI_API_KEY no .env e reinicie o servidor."
    if e.code == 404:
        return f"O modelo '{settings.model_consultor}' não foi encontrado. Confira MODEL_CONSULTOR no .env."
    if e.code == 429:
        return "Limite de uso do Gemini atingido. Espere um minuto ou troque o modelo para gemini-3.5-flash-lite no .env."
    if e.code == 503:
        return "O Gemini está sobrecarregado agora. Tente de novo em alguns instantes (ou use gemini-3.5-flash-lite no .env)."
    return f"O Gemini devolveu um erro ({e.code}). Tente de novo em instantes."


def consultar(mensagem: str, historico: list[dict]) -> str:
    """Responde como consultor, usando a base de conhecimento e lembrando da conversa.

    historico: mensagens anteriores, no formato [{"role": "user" ou "model", "text": "..."}].
    """
    if not settings.gemini_api_key:
        raise ErroLLM("A chave do Gemini não está configurada. Preencha GEMINI_API_KEY no .env e reinicie o servidor.")

    contents = [
        types.Content(role=h["role"], parts=[types.Part(text=h["text"])])
        for h in historico
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))

    client = _client()  # guardar numa variável: se o cliente for descartado, a conexão fecha no meio
    try:
        resp = client.models.generate_content(
            model=settings.model_consultor,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_system_consultor(),
                temperature=0.3,
            ),
        )
    except errors.APIError as e:
        raise ErroLLM(_traduzir_erro(e)) from e
    except httpx.TransportError as e:
        raise ErroLLM("Não consegui falar com o Gemini (sem internet ou demorou demais). Tente de novo.") from e

    if not resp.text:
        raise ErroLLM("O Gemini não devolveu texto. Tente reformular a pergunta.")
    return resp.text