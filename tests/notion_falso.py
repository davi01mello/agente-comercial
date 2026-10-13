"""Um Notion falso para os testes da T4: serve o workspace FICTÍCIO de tests/fixtures/notion/workspace.json pelo
httpx.MockTransport. O SDK oficial (notion-client) roda de verdade; só a rede é falsa: nenhum teste sai da máquina.

- POST /v1/search, GET /v1/blocks/{id}/children e GET /v1/pages/{id}, no formato da API (versão 2026-03-11);
- paginação de verdade: cada resposta traz no máximo `por_pagina` itens (3 no workspace), com has_more e next_cursor;
- `falhar(...)` programa respostas de erro (429 com Retry-After, 529, 500...) antes das normais.
"""
import copy
import json
import re
from pathlib import Path

import httpx

WORKSPACE = Path(__file__).parent / "fixtures" / "notion" / "workspace.json"
TOKEN_DE_TESTE = "ntn_TOKEN-DE-TESTE-NAO-PODE-VAZAR"


def carregar_workspace() -> dict:
    return json.loads(WORKSPACE.read_text(encoding="utf-8"))


def id_da_pagina(workspace: dict, titulo: str) -> str:
    """O id de uma página do workspace pelo título (os testes falam em títulos, não em uuids)."""
    for pid, pagina in workspace["paginas"].items():
        for prop in pagina["properties"].values():
            if prop["type"] == "title" and "".join(t["plain_text"] for t in prop["title"]) == titulo:
                return pid
    raise KeyError(titulo)


class NotionFalso:
    def __init__(self, workspace: dict | None = None):
        self.ws = copy.deepcopy(workspace if workspace is not None else carregar_workspace())
        self.pedidos: list[tuple[str, str]] = []  # (método, caminho) de cada requisição, na ordem
        self.corpos_da_busca: list[dict] = []  # o JSON de cada POST /v1/search
        self.cabecalhos: dict = {}  # os cabeçalhos da última requisição
        self._falhas: list[tuple[str, int, dict]] = []  # (trecho do caminho, status, cabeçalhos)
        self.busca_incompleta = False  # simula request_status "incomplete" no search
        self.escondidas_da_busca: set[str] = set()  # ids que o search "esquece" (a página existe, mas não é listada)

    def cliente_http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._responder))

    def falhar(self, trecho_do_caminho: str, status: int, vezes: int = 1, retry_after: str | None = None) -> None:
        """As próximas `vezes` requisições cujo caminho contém o trecho recebem este erro. Status 0 simula falha de rede
        (httpx.ConnectError) e -1, timeout (httpx.ReadTimeout)."""
        cabecalhos = {"retry-after": retry_after} if retry_after is not None else {}
        self._falhas += [(trecho_do_caminho, status, cabecalhos)] * vezes

    # --- atalhos para os testes mexerem no workspace entre uma rodada e outra --------------------------------

    def pagina(self, titulo: str) -> dict:
        return self.ws["paginas"][id_da_pagina(self.ws, titulo)]

    def editar(self, titulo: str, novo_texto: str | None = None, editado: str = "2026-10-01T09:00:00.000Z") -> None:
        """Simula uma edição: muda o last_edited_time e, se pedido, o texto do 1º parágrafo da página."""
        pagina = self.pagina(titulo)
        pagina["last_edited_time"] = editado
        if novo_texto is not None:
            primeiro = next(b for b in self.ws["blocos"][pagina["id"]] if b["type"] == "paragraph")
            primeiro["paragraph"]["rich_text"][0]["text"]["content"] = novo_texto
            primeiro["paragraph"]["rich_text"][0]["plain_text"] = novo_texto

    # --- o "servidor" ---------------------------------------------------------------------------------------

    def _responder(self, pedido: httpx.Request) -> httpx.Response:
        caminho = pedido.url.path
        self.pedidos.append((pedido.method, caminho))
        self.cabecalhos = dict(pedido.headers)
        for i, (trecho, status, cabecalhos) in enumerate(self._falhas):
            if trecho in caminho:
                del self._falhas[i]
                if status == 0:
                    raise httpx.ConnectError("sem rede (simulado)", request=pedido)
                if status == -1:
                    raise httpx.ReadTimeout("demorou (simulado)", request=pedido)
                return self._erro(status, cabecalhos)

        if caminho == "/v1/search":
            corpo = json.loads(pedido.content)
            self.corpos_da_busca.append(corpo)
            visiveis = [p for p in self.ws["paginas"].values()
                        if not p.get("in_trash") and p["id"] not in self.escondidas_da_busca]
            visiveis.sort(key=lambda p: p["last_edited_time"])  # o pedido é por last_edited_time crescente
            resposta = self._pagina_da_lista(visiveis, corpo.get("start_cursor"), corpo.get("page_size"))
            if self.busca_incompleta:
                resposta["request_status"] = {"type": "incomplete", "incomplete_reason": "query_result_limit_reached"}
            return httpx.Response(200, json=resposta)

        if achou := re.fullmatch(r"/v1/blocks/([^/]+)/children", caminho):
            bloco_id = achou.group(1)
            if bloco_id not in self.ws["blocos"]:
                return self._erro(404)
            params = pedido.url.params
            tamanho = int(params["page_size"]) if "page_size" in params else None
            return httpx.Response(200, json=self._pagina_da_lista(
                self.ws["blocos"][bloco_id], params.get("start_cursor"), tamanho))

        if achou := re.fullmatch(r"/v1/pages/([^/]+)", caminho):
            pagina = self.ws["paginas"].get(achou.group(1))
            return httpx.Response(200, json=pagina) if pagina else self._erro(404)

        raise AssertionError(f"rota não simulada: {pedido.method} {caminho}")

    def _pagina_da_lista(self, itens: list, cursor: str | None, tamanho: int | None) -> dict:
        """Uma página de resultados, como a API faz: o cursor aqui é só a posição na lista."""
        inicio = int(cursor) if cursor else 0
        tamanho = min(tamanho or 100, self.ws.get("por_pagina", 100))
        fatia = itens[inicio:inicio + tamanho]
        tem_mais = inicio + tamanho < len(itens)
        return {"object": "list", "results": copy.deepcopy(fatia), "has_more": tem_mais,
                "next_cursor": str(inicio + tamanho) if tem_mais else None, "type": "block"}

    @staticmethod
    def _erro(status: int, cabecalhos: dict | None = None) -> httpx.Response:
        codigos = {400: "validation_error", 401: "unauthorized", 403: "restricted_resource", 404: "object_not_found",
                   429: "rate_limited", 500: "internal_server_error", 502: "bad_gateway",
                   503: "service_unavailable", 504: "gateway_timeout", 529: "service_overload"}
        corpo = {"object": "error", "status": status, "code": codigos.get(status, "erro"),
                 "message": f"erro {status} simulado"}
        return httpx.Response(status, json=corpo, headers=cabecalhos or {})


def limpar_banco_da_importacao(db) -> None:
    """Apaga o que a importação do Notion gravou no banco de TESTE (temporário). As páginas do workspace fictício têm
    ids fixos, então cada teste da importação começa do zero."""
    from sqlalchemy import delete, select

    from app.models import ExecucaoImportacao, Fonte, HistoricoStatus, Insight, Relacao

    ids = list(db.scalars(select(Insight.id).where(Insight.fonte == "notion")))
    if ids:
        db.execute(delete(Relacao).where(Relacao.insight_id.in_(ids) | Relacao.relacionado_id.in_(ids)))
        db.execute(delete(HistoricoStatus).where(HistoricoStatus.insight_id.in_(ids)))
        db.execute(delete(Insight).where(Insight.id.in_(ids)))
    db.execute(delete(Fonte))
    db.execute(delete(ExecucaoImportacao))
    db.commit()
