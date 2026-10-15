"""Leitura do Notion: a única porta do app para a API do Notion, como o app/llm.py é para o Gemini. Só LÊ.

Usa o SDK oficial (notion-client) com o retry dele DESLIGADO, porque o nosso precisa fazer três coisas que ele não faz
(decisões no docs/adr-005-importacao-notion.md):
- respeitar o limite de requisições do Notion (180 por minuto, 3 por segundo em média) com um intervalo mínimo;
- repetir também o 529 (sobrecarga), que o Notion manda tratar como o 429, respeitando o Retry-After;
- esperar com funções que os testes trocam (_dormir/_agora), sem esperar de verdade.

Nunca loga o token nem conteúdo de página: só códigos de erro e números.
"""
import json
import logging
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx
import notion_client
from notion_client.errors import HTTPResponseError, RequestTimeoutError

from app.config import settings

logger = logging.getLogger(__name__)

NOTION_VERSION = "2026-03-11"  # a mais nova; nela `archived` saiu e ficou só `in_trash`
POR_PAGINA = 100  # o máximo que a API aceita por chamada
INTERVALO_MINIMO_S = 0.35  # entre duas requisições: ~2,9 por segundo, abaixo da média de 3 que o Notion permite
TENTATIVAS = 5  # incluindo a primeira
ESPERA_INICIAL_S = 1.0  # sem Retry-After: 1 s, 2 s, 4 s, 8 s
ESPERA_MAXIMA_S = 60.0  # o Retry-After do Notion é de no máximo 60 s
LIMITE_DE_TAXA = {429, 529}  # "rate_limited" e "service_overload": respeitam o Retry-After
TEMPORARIOS = {500, 502, 503, 504}  # costumam passar sozinhos
PROFUNDIDADE_MAXIMA = 8  # níveis de blocos aninhados que a leitura desce
NAO_DESCER = {"child_page", "child_database", "meeting_notes", "transcription", "unsupported"}
# child_page: a subpágina é importada como página própria (o search a traz). child_database: as linhas também vêm do
# search, como páginas. meeting_notes/transcription: notas e transcrição de reunião não são importadas.

_dormir = time.sleep  # os testes trocam por uma função que não espera de verdade
_agora = time.monotonic  # idem: os testes trocam por um relógio falso
_relogio_de_parede = time.time  # só para o Retry-After em formato de data (os testes também trocam)


class ErroNotion(Exception):
    """Falha ao falar com o Notion. A mensagem já vem pronta, e nunca tem conteúdo de página nem o token."""

    def __init__(self, mensagem: str, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


@dataclass
class Busca:
    """O resultado do search. `completa=False` quando a lista pode não ter todas as páginas (limite pedido, ou o Notion
    avisou que cortou o resultado): aí ninguém pode concluir que uma página "sumiu"."""

    paginas: list[dict]
    completa: bool


def _mensagem(e: Exception) -> str:
    """Frase para o usuário a partir do erro do SDK. Usa só o código: a mensagem do Notion fica de fora."""
    status = getattr(e, "status", None)
    if status == 401:
        return "O token do Notion é inválido. Confira NOTION_TOKEN no .env."
    if status == 403:
        return "A integração do Notion não tem permissão de leitura (capacidade 'Read content')."
    if status == 404:
        return "Página ou bloco não encontrado no Notion (apagado ou não compartilhado com a integração)."
    if status in LIMITE_DE_TAXA:
        return f"O Notion continuou limitando as requisições após {TENTATIVAS} tentativas. Rode de novo mais tarde."
    if status is None:  # timeout ou rede
        return "Não consegui falar com o Notion (sem internet ou demorou demais). Tente de novo."
    return f"O Notion devolveu um erro ({status}). Tente de novo em instantes."


def _segundos_do_retry_after(valor: str | None) -> float | None:
    """O Retry-After vem em segundos ("7") ou, pela norma do HTTP, como data ("Wed, 21 Oct 2026 07:28:00 GMT")."""
    if not valor:
        return None
    if valor.strip().isdigit():
        return float(valor)
    try:
        quando = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None  # formato que não entendemos: vale a espera crescente
    return max(0.0, quando.timestamp() - _relogio_de_parede())


def _espera(e: Exception, tentativa: int) -> float | None:
    """Quanto esperar antes da próxima tentativa, ou None se não vale tentar de novo (401, 403, 404, 400...)."""
    status = getattr(e, "status", None)
    crescente = ESPERA_INICIAL_S * 2 ** (tentativa - 1)
    if status in LIMITE_DE_TAXA:
        pedido = _segundos_do_retry_after(e.headers.get("retry-after")) if isinstance(e, HTTPResponseError) else None
        return min(pedido, ESPERA_MAXIMA_S) if pedido is not None else crescente
    if status in TEMPORARIOS or isinstance(e, (RequestTimeoutError, httpx.TransportError)):
        return crescente
    return None


class LeitorNotion:
    """Lê páginas e blocos de um workspace do Notion. `cliente_http` serve para os testes (httpx.MockTransport)."""

    def __init__(self, token: str | None = None, cliente_http: httpx.Client | None = None):
        token = settings.notion_token if token is None else token
        if not token:
            raise ErroNotion("Falta NOTION_TOKEN no .env (o token da integração do Notion).")
        # logger próprio: sem ele, cada Client novo pendura mais um handler no logger "notion_client" (linhas
        # duplicadas). O SDK loga só o caminho (com ids), o código e a mensagem dos ERROS; nunca o corpo de uma resposta
        # de sucesso nem o cabeçalho com o token (conferido em notion_client/client.py).
        self._sdk = notion_client.Client(
            auth=token,
            notion_version=NOTION_VERSION,
            retry=False,  # o retry é o nosso (_chamar)
            logger=logging.getLogger("app.notion.sdk"),
            log_level=logging.WARNING,
            client=cliente_http,
        )
        self._ultima: float | None = None  # quando foi a última requisição (relógio _agora)
        self.requisicoes = 0  # quantas requisições esta leitura fez (o relatório mostra)

    # --- o caminho de toda requisição ----------------------------------------------------------------

    def _respeitar_intervalo(self) -> None:
        if self._ultima is not None:
            falta = INTERVALO_MINIMO_S - (_agora() - self._ultima)
            if falta > 0:
                _dormir(falta)
        self._ultima = _agora()
        self.requisicoes += 1

    def _chamar(self, funcao, *args, **kwargs) -> dict:
        """Chama o SDK respeitando o intervalo mínimo; em 429/529 espera o Retry-After, em 5xx/timeout/rede espera
        1, 2, 4, 8 s; até TENTATIVAS. Erro definitivo (ou tentativas esgotadas) vira ErroNotion."""
        for tentativa in range(1, TENTATIVAS + 1):
            self._respeitar_intervalo()
            try:
                return funcao(*args, **kwargs)
            except (HTTPResponseError, RequestTimeoutError, httpx.TransportError) as e:
                status = getattr(e, "status", None)
                espera = _espera(e, tentativa)
                if espera is None or tentativa == TENTATIVAS:
                    raise ErroNotion(_mensagem(e), status) from e
                logger.info(json.dumps({
                    "evento": "notion_nova_tentativa",
                    "codigo": status if status is not None else "rede",
                    "tentativa": tentativa,
                    "espera_s": espera,
                }))
                _dormir(espera)
        raise AssertionError("inalcançável")  # pragma: no cover

    # --- leituras --------------------------------------------------------------------------------------

    def paginas(self, limite: int | None = None) -> Busca:
        """Todas as páginas compartilhadas com a integração (search filtrando por página), das mais antigas às mais
        recentes pela data de edição. Com `limite`, para nas primeiras N e a busca fica incompleta."""
        paginas: list[dict] = []
        vistas: set[str] = set()  # uma página editada durante a leitura pode reaparecer na página seguinte da busca
        completa = True
        cursor = None
        while True:
            pedido = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"timestamp": "last_edited_time", "direction": "ascending"},
                "page_size": POR_PAGINA,
            }
            if cursor:
                pedido["start_cursor"] = cursor
            resposta = self._chamar(self._sdk.search, **pedido)
            for pagina in resposta.get("results", []):
                # Páginas na lixeira não deveriam vir sem o filtro in_trash, mas por garantia ficam de fora.
                if not na_lixeira(pagina) and pagina["id"] not in vistas:
                    vistas.add(pagina["id"])
                    paginas.append(pagina)
            if (resposta.get("request_status") or {}).get("type", "complete") != "complete":
                completa = False  # o Notion avisou que cortou o resultado (query_result_limit_reached)
            if limite is not None and len(paginas) >= limite:
                return Busca(paginas[:limite], completa=False)
            cursor = resposta.get("next_cursor")
            if not resposta.get("has_more") or not cursor:
                return Busca(paginas, completa)

    def blocos(self, bloco_id: str, profundidade: int = 0) -> list[dict]:
        """Os blocos filhos de uma página (ou de um bloco), com os filhos de cada um em bloco["_filhos"], recursivo.
        As linhas de uma tabela são filhas dela e vêm do mesmo jeito. Abaixo de PROFUNDIDADE_MAXIMA, o bloco fica
        marcado com bloco["_profundo_demais"] e o que está embaixo não é lido."""
        filhos: list[dict] = []
        cursor = None
        while True:
            pedido = {"page_size": POR_PAGINA}
            if cursor:
                pedido["start_cursor"] = cursor
            resposta = self._chamar(self._sdk.blocks.children.list, bloco_id, **pedido)
            filhos += resposta.get("results", [])
            cursor = resposta.get("next_cursor")
            if not resposta.get("has_more") or not cursor:
                break
        for bloco in filhos:
            if not bloco.get("has_children") or bloco.get("type") in NAO_DESCER:
                continue
            if profundidade + 1 >= PROFUNDIDADE_MAXIMA:
                bloco["_profundo_demais"] = True
            else:
                bloco["_filhos"] = self.blocos(bloco["id"], profundidade + 1)
        return filhos

    def pagina(self, pagina_id: str) -> dict | None:
        """A página, ou None se o Notion responder 404 (apagada, ou não compartilhada com a integração: a API não
        diferencia os dois casos)."""
        try:
            return self._chamar(self._sdk.pages.retrieve, pagina_id)
        except ErroNotion as e:
            if e.status == 404:
                return None
            raise


# --- ajudantes sobre o JSON de uma página ------------------------------------------------------------------

def na_lixeira(pagina: dict) -> bool:
    """`in_trash` na versão 2026-03-11; `archived` nas anteriores (era o mesmo campo com outro nome)."""
    return bool(pagina.get("in_trash") or pagina.get("archived"))


def url_da_pagina(pagina_id: str) -> str:
    """A URL da página montada pelo id. A `url` que o Notion devolve repete o título no endereço (/Titulo-<id>): se o
    título tiver dado pessoal, ela também teria. Esta abre a mesma página e não muda quando o título muda."""
    return f"https://www.notion.so/{pagina_id.replace('-', '')}"
