"""Camada única de acesso ao modelo (Gemini). Todo o resto do app chama SÓ este arquivo.

Aqui mora só a conversa com o modelo (montar a chamada, repetir, traduzir erros, conferir o formato).
As regras de negócio sobre o que o modelo devolve ficam em app/curadoria.py e app/dominio.py.
"""
import time
from pathlib import Path
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.knowledge import carregar_base
from app.schemas import PropostaLLM, RelacoesLLM

PROMPTS = Path(__file__).parent / "prompts"

TENTATIVAS = 3  # incluindo a primeira
ESPERA_INICIAL_S = 1.0  # depois dobra: 1s, 2s, 4s...
CODIGOS_TEMPORARIOS = {429, 503}  # limite e sobrecarga: costumam passar sozinhos
_dormir = time.sleep  # os testes trocam por uma função que não espera de verdade

M = TypeVar("M", bound=BaseModel)  # "algum schema Pydantic": _gerar_json devolve o mesmo tipo que recebeu


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


def _traduzir_erro(e: errors.APIError, modelo: str) -> str:
    """Transforma o erro técnico da API numa frase que o usuário entende."""
    if e.code in (401, 403) or "API key" in (e.message or ""):
        return "A chave do Gemini é inválida. Confira GEMINI_API_KEY no .env e reinicie o servidor."
    if e.code == 404:
        return f"O modelo '{modelo}' não foi encontrado. Confira MODEL_CONSULTOR e MODEL_CURADOR no .env."
    if e.code == 429:
        return (
            "Limite de uso do Gemini atingido. "
            "Espere um minuto ou troque o modelo para gemini-3.5-flash-lite no .env."
        )
    if e.code == 503:
        return (
            "O Gemini está sobrecarregado agora. "
            "Tente de novo em alguns instantes (ou use gemini-3.5-flash-lite no .env)."
        )
    return f"O Gemini devolveu um erro ({e.code}). Tente de novo em instantes."


def _vale_tentar_de_novo(e: Exception) -> bool:
    """Só erros temporários: limite (429), sobrecarga (503) e rede/timeout. 401/404 não mudam repetindo."""
    if isinstance(e, errors.APIError):
        return e.code in CODIGOS_TEMPORARIOS
    return isinstance(e, httpx.TransportError)


def _gerar_com_retry(client: genai.Client, **kwargs):
    """Chama generate_content; em erro temporário espera (1s, 2s...) e tenta de novo, até TENTATIVAS."""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return client.models.generate_content(**kwargs)
        except (errors.APIError, httpx.TransportError) as e:
            if tentativa == TENTATIVAS or not _vale_tentar_de_novo(e):
                raise
            _dormir(ESPERA_INICIAL_S * 2 ** (tentativa - 1))


def _chamar(client: genai.Client, **kwargs):
    """_gerar_com_retry + tradução dos erros da API e da rede para ErroLLM (mensagem pronta para o usuário)."""
    try:
        return _gerar_com_retry(client, **kwargs)
    except errors.APIError as e:
        raise ErroLLM(_traduzir_erro(e, kwargs["model"])) from e
    except httpx.TransportError as e:
        raise ErroLLM("Não consegui falar com o Gemini (sem internet ou demorou demais). Tente de novo.") from e


def _checar_chave() -> None:
    if not settings.gemini_api_key:
        raise ErroLLM("A chave do Gemini não está configurada. Preencha GEMINI_API_KEY no .env e reinicie o servidor.")


def _mensagem(role: str, texto: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part(text=texto)])


def consultar(mensagem: str, historico: list[dict]) -> str:
    """Responde como consultor, usando a base de conhecimento e lembrando da conversa.

    historico: mensagens anteriores, no formato [{"role": "user" ou "model", "text": "..."}].
    """
    _checar_chave()
    contents = [_mensagem(h["role"], h["text"]) for h in historico]
    contents.append(_mensagem("user", mensagem))

    client = _client()  # guardar numa variável: se o cliente for descartado, a conexão fecha no meio
    resp = _chamar(
        client,
        model=settings.model_consultor,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_system_consultor(),
            temperature=0.3,
        ),
    )
    if not resp.text:
        raise ErroLLM("O Gemini não devolveu texto. Tente reformular a pergunta.")
    return resp.text


# --- curador --------------------------------------------------------------------------------

def _resumo_do_erro(e: ValidationError) -> str:
    """Erro de validação em poucas linhas, no formato que o modelo entende: 'insight.tipo: Input should be ...'."""
    linhas = [f"{'.'.join(str(p) for p in err['loc']) or 'json'}: {err['msg']}" for err in e.errors()[:5]]
    return "; ".join(linhas)


def _gerar_json(schema: type[M], system: str, contents: list[types.Content]) -> M:
    """Pede ao modelo um JSON no formato `schema` e confere com o Pydantic.

    Se vier fora do formato, devolve o erro ao modelo e pede de novo, UMA vez. Na segunda falha, ErroLLM.
    (Não usamos resp.parsed: quando o JSON é inválido, o SDK só deixa parsed=None, sem dizer o porquê.)
    """
    _checar_chave()
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        response_mime_type="application/json",
        response_schema=schema,
    )
    client = _client()

    resp = _chamar(client, model=settings.model_curador, contents=contents, config=config)
    try:
        return schema.model_validate_json(resp.text or "")
    except ValidationError as e:
        # 2ª e última chance: o modelo vê a resposta dele e o que estava errado nela
        contents = [
            *contents,
            _mensagem("model", resp.text or ""),
            _mensagem("user", f"Seu JSON não seguiu o schema ({_resumo_do_erro(e)}). Devolva o JSON corrigido."),
        ]

    resp = _chamar(client, model=settings.model_curador, contents=contents, config=config)
    try:
        return schema.model_validate_json(resp.text or "")
    except ValidationError as e:
        raise ErroLLM(
            "O curador devolveu uma resposta fora do formato duas vezes. Tente de novo ou reescreva o texto."
        ) from e


def _como_dado(texto: str) -> str:
    """Embrulha o texto do usuário como DADO. O prompt diz que instruções aqui dentro não valem."""
    return f"<texto_do_usuario>\n{texto}\n</texto_do_usuario>"


def curar(texto: str, conversa: list[dict], turno: int, ultimo_turno: bool) -> PropostaLLM:
    """1ª chamada do curador: texto solto -> proposta estruturada (+ até 2 perguntas, se faltar algo).

    conversa: turnos anteriores [{"role": "user" | "model", "text": ...}]; o texto do usuário vai sempre embrulhado.
    O autor NÃO vai para o modelo: quem põe autor e status é o código.
    """
    contents = [
        _mensagem(m["role"], _como_dado(m["text"]) if m["role"] == "user" else m["text"]) for m in conversa
    ]
    aviso_turno = (
        f"(turno {turno}: ÚLTIMO. Não faça perguntas: feche a proposta com o que tem e diga em avisos o que faltou.)"
        if ultimo_turno
        else f"(turno {turno})"
    )
    contents.append(_mensagem("user", f"{_como_dado(texto)}\n{aviso_turno}"))
    system = "\n\n".join([carregar_prompt("base"), carregar_prompt("curador")])
    return _gerar_json(PropostaLLM, system, contents)


def relacionar(item_novo: str, candidatos: str) -> RelacoesLLM:
    """2ª chamada do curador: como o item novo se relaciona com os candidatos (itens que já existem)."""
    pedido = f"<item_novo>\n{item_novo}\n</item_novo>\n\n<itens_existentes>\n{candidatos}\n</itens_existentes>"
    return _gerar_json(RelacoesLLM, carregar_prompt("relacoes"), [_mensagem("user", pedido)])