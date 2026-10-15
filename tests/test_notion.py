"""Testes do app/notion.py (o leitor do Notion) sem rede: o SDK oficial fala com o NotionFalso (tests/notion_falso.py),
que serve o workspace fictício. Aqui se testa o que é NOSSO: paginação, intervalo entre requisições, backoff em
429/529/5xx/rede, o que vira erro e o que nunca pode aparecer no log.
"""
import logging

import pytest

from app import notion
from app.notion import ErroNotion, LeitorNotion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, id_da_pagina


class Relogio:
    """Relógio falso: _dormir só anota a espera e avança o relógio (nenhum teste espera de verdade)."""

    def __init__(self):
        self.agora = 1000.0
        self.esperas: list[float] = []

    def dormir(self, segundos: float) -> None:
        self.esperas.append(round(segundos, 3))
        self.agora += segundos


@pytest.fixture
def relogio(monkeypatch):
    r = Relogio()
    monkeypatch.setattr(notion, "_agora", lambda: r.agora)
    monkeypatch.setattr(notion, "_dormir", r.dormir)
    return r


@pytest.fixture
def falso():
    return NotionFalso()


@pytest.fixture
def leitor(falso, relogio):
    return LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http())


# --- cliente e token ---------------------------------------------------------------------------------------

def test_cliente_usa_a_versao_fixa_e_o_token(leitor, falso):
    leitor.paginas()

    assert falso.cabecalhos["notion-version"] == "2026-03-11"
    assert falso.cabecalhos["authorization"] == f"Bearer {TOKEN_DE_TESTE}"


def test_token_vem_do_env(monkeypatch, falso, relogio):
    monkeypatch.setattr(notion.settings, "notion_token", "ntn_do_env")

    LeitorNotion(cliente_http=falso.cliente_http()).paginas()

    assert falso.cabecalhos["authorization"] == "Bearer ntn_do_env"


def test_sem_token_para_antes_de_qualquer_requisicao(monkeypatch, falso):
    monkeypatch.setattr(notion.settings, "notion_token", "")

    with pytest.raises(ErroNotion, match="Falta NOTION_TOKEN"):
        LeitorNotion(cliente_http=falso.cliente_http())
    assert falso.pedidos == []


# --- search ------------------------------------------------------------------------------------------------

def test_paginas_usa_o_search_so_de_paginas_e_segue_o_has_more(leitor, falso):
    busca = leitor.paginas()

    assert len(busca.paginas) == 10  # todas as do workspace, que o falso entrega de 3 em 3
    assert busca.completa
    assert len(falso.corpos_da_busca) == 4  # 3 + 3 + 3 + 1
    primeiro, segundo = falso.corpos_da_busca[:2]
    assert primeiro["filter"] == {"property": "object", "value": "page"}
    assert primeiro["sort"] == {"timestamp": "last_edited_time", "direction": "ascending"}
    assert primeiro["page_size"] == 100
    assert "start_cursor" not in primeiro
    assert segundo["start_cursor"] == "3"


def test_paginas_ignora_pagina_na_lixeira_mesmo_no_formato_antigo(leitor, falso):
    falso.pagina("Rascunho antigo de proposta")["archived"] = True  # nome antigo de in_trash

    titulos = [p["id"] for p in leitor.paginas().paginas]

    assert id_da_pagina(falso.ws, "Rascunho antigo de proposta") not in titulos
    assert len(titulos) == 9


def test_pagina_repetida_na_busca_vem_uma_vez_so(leitor, falso):
    """Se alguém edita uma página durante a leitura, a busca (ordenada pela data de edição) pode trazê-la de novo."""
    pid = id_da_pagina(falso.ws, "Cérebro: teste fictício")  # a 1ª da busca
    original = falso._pagina_da_lista

    def com_repeticao(itens, cursor, tamanho):
        resposta = original(itens, cursor, tamanho)
        if cursor == "3":
            resposta["results"].append(falso.ws["paginas"][pid])
        return resposta

    falso._pagina_da_lista = com_repeticao

    ids = [p["id"] for p in leitor.paginas().paginas]

    assert ids.count(pid) == 1
    assert len(ids) == 10


def test_limite_de_paginas_para_cedo_e_marca_a_busca_incompleta(leitor, falso):
    busca = leitor.paginas(limite=4)

    assert len(busca.paginas) == 4
    assert not busca.completa  # com limite, ninguém pode concluir que uma página sumiu
    assert len(falso.corpos_da_busca) == 2


def test_busca_que_o_notion_cortou_fica_incompleta(leitor, falso):
    falso.busca_incompleta = True

    assert not leitor.paginas().completa


# --- blocos ------------------------------------------------------------------------------------------------

def test_blocos_seguem_o_has_more_e_descem_nos_filhos(leitor, falso):
    pid = id_da_pagina(falso.ws, "Roteiro da reunião de diagnóstico")

    blocos = leitor.blocos(pid)

    assert len(blocos) == 10  # o falso entrega de 3 em 3: 4 requisições só para o 1º nível
    assert falso.pedidos.count(("GET", f"/v1/blocks/{pid}/children")) == 4
    numerado = blocos[1]
    assert numerado["type"] == "numbered_list_item"
    assert numerado["_filhos"][0]["numbered_list_item"]["rich_text"][0]["plain_text"] == "Sem slides."
    toggle = next(b for b in blocos if b["type"] == "toggle")
    assert toggle["_filhos"][0]["type"] == "paragraph"


def test_tabela_traz_as_linhas_como_filhos(leitor, falso):
    tabela = next(b for b in leitor.blocos(id_da_pagina(falso.ws, "Objeções comuns e respostas"))
                  if b["type"] == "table")

    assert [linha["type"] for linha in tabela["_filhos"]] == ["table_row"] * 4


def test_nao_desce_em_subpagina(leitor, falso):
    """A subpágina é importada como página própria (o search a traz): descer nela duplicaria o conteúdo."""
    raiz = id_da_pagina(falso.ws, "Cérebro: teste fictício")
    subpaginas = [b for b in falso.ws["blocos"][raiz] if b["type"] == "child_page"]
    for bloco in subpaginas:
        bloco["has_children"] = True  # no Notion de verdade, a subpágina com conteúdo vem com has_children
    assert len(subpaginas) == 2

    leitor.blocos(raiz)

    assert [caminho for _, caminho in falso.pedidos] == [f"/v1/blocks/{raiz}/children"]


def test_para_de_descer_na_profundidade_maxima(monkeypatch, leitor, falso):
    monkeypatch.setattr(notion, "PROFUNDIDADE_MAXIMA", 1)

    blocos = leitor.blocos(id_da_pagina(falso.ws, "Roteiro da reunião de diagnóstico"))

    numerado = blocos[1]
    assert numerado["_profundo_demais"] is True
    assert "_filhos" not in numerado


# --- uma página (para conferir se foi apagada) ------------------------------------------------------------

def test_pagina_existente(leitor, falso):
    pid = id_da_pagina(falso.ws, "Prospecção por indicação")

    assert leitor.pagina(pid)["id"] == pid


def test_pagina_que_nao_existe_ou_nao_esta_compartilhada_vira_none(leitor):
    assert leitor.pagina("00000000-0000-0000-0000-000000000000") is None


def test_pagina_sem_permissao_levanta_com_mensagem_clara(leitor, falso):
    falso.falhar("/v1/pages/", 403)

    with pytest.raises(ErroNotion, match="não tem permissão de leitura") as erro:
        leitor.pagina(id_da_pagina(falso.ws, "Prospecção por indicação"))
    assert erro.value.status == 403


# --- limite de requisições e backoff ---------------------------------------------------------------------

def test_intervalo_minimo_entre_requisicoes(leitor, relogio):
    """O Notion permite 3 requisições por segundo em média: 0,35 s entre elas dá ~2,9 por segundo."""
    leitor.paginas()  # 4 requisições seguidas, com o relógio parado

    assert relogio.esperas == [0.35, 0.35, 0.35]  # a 1ª não espera
    assert leitor.requisicoes == 4


def test_nao_espera_se_o_intervalo_ja_passou(leitor, relogio):
    leitor.paginas(limite=1)
    relogio.agora += 5  # passou bastante tempo

    leitor.paginas(limite=1)

    assert relogio.esperas == []


def test_429_espera_o_retry_after_e_tenta_de_novo(leitor, falso, relogio):
    falso.falhar("/v1/search", 429, retry_after="7")

    busca = leitor.paginas(limite=1)

    assert relogio.esperas == [7.0]
    assert len(busca.paginas) == 1


def test_retry_after_acima_de_60_segundos_e_limitado(leitor, falso, relogio):
    falso.falhar("/v1/search", 429, retry_after="300")

    leitor.paginas(limite=1)

    assert relogio.esperas == [60.0]


def test_retry_after_em_formato_de_data(monkeypatch, leitor, falso, relogio):
    """A norma do HTTP também permite uma data no Retry-After (o próprio SDK entende os dois formatos)."""
    monkeypatch.setattr(notion, "_relogio_de_parede", lambda: 1_792_567_660.0)  # 21/10/2026 07:27:40 UTC
    falso.falhar("/v1/search", 429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")

    leitor.paginas(limite=1)

    assert relogio.esperas == [20.0]


def test_retry_after_que_nao_se_entende_usa_a_espera_crescente(leitor, falso, relogio):
    falso.falhar("/v1/search", 429, retry_after="logo mais")

    leitor.paginas(limite=1)

    assert relogio.esperas == [1.0]


def test_429_sem_retry_after_espera_de_forma_crescente(leitor, falso, relogio):
    falso.falhar("/v1/search", 429, vezes=2)

    leitor.paginas(limite=1)

    assert relogio.esperas == [1.0, 2.0]


def test_529_sobrecarga_tambem_respeita_o_retry_after(leitor, falso, relogio):
    """O SDK não repete o 529 (não está na lista de códigos dele); o Notion manda tratá-lo como o 429."""
    falso.falhar("/v1/search", 529, retry_after="3")

    leitor.paginas(limite=1)

    assert relogio.esperas == [3.0]


@pytest.mark.parametrize("status", [500, 502, 503, 504, 0, -1])  # 0: falha de rede; -1: timeout
def test_erro_temporario_repete_com_espera_crescente(leitor, falso, relogio, status):
    falso.falhar("/v1/search", status, vezes=3)

    leitor.paginas(limite=1)

    assert relogio.esperas == [1.0, 2.0, 4.0]


def test_desiste_depois_de_5_tentativas(leitor, falso, relogio):
    falso.falhar("/v1/search", 503, vezes=5)

    with pytest.raises(ErroNotion, match=r"erro \(503\)") as erro:
        leitor.paginas()
    assert erro.value.status == 503
    assert len(falso.pedidos) == 5
    assert relogio.esperas == [1.0, 2.0, 4.0, 8.0]


def test_limite_que_nao_passa_avisa_para_rodar_mais_tarde(leitor, falso):
    falso.falhar("/v1/search", 429, vezes=5, retry_after="1")

    with pytest.raises(ErroNotion, match="continuou limitando"):
        leitor.paginas()


@pytest.mark.parametrize("status, mensagem", [
    (401, "token do Notion é inválido"),
    (400, r"erro \(400\)"),
])
def test_erro_definitivo_nao_repete(leitor, falso, relogio, status, mensagem):
    falso.falhar("/v1/search", status)

    with pytest.raises(ErroNotion, match=mensagem):
        leitor.paginas()
    assert len(falso.pedidos) == 1
    assert relogio.esperas == []


def test_rede_que_nao_volta_vira_mensagem_clara(leitor, falso):
    falso.falhar("/v1/search", 0, vezes=5)

    with pytest.raises(ErroNotion, match="Não consegui falar com o Notion"):
        leitor.paginas()


# --- log: nunca o token nem o texto das páginas ------------------------------------------------------------

def textos_do_workspace(ws: dict) -> list[str]:
    """Todo texto de página e de bloco do workspace fictício (títulos, parágrafos, células de tabela...)."""
    textos = []

    def coletar(valor):
        if isinstance(valor, dict):
            if "plain_text" in valor:
                textos.append(valor["plain_text"])
            for v in valor.values():
                coletar(v)
        elif isinstance(valor, list):
            for v in valor:
                coletar(v)

    coletar(ws["paginas"])
    coletar(ws["blocos"])
    return [t for t in textos if len(t.strip()) > 3]


def test_log_nunca_tem_token_nem_texto(leitor, falso, caplog):
    """Spec: "nenhum token ou texto de página em log". Tudo em DEBUG, inclusive o logger do SDK e o do httpx: um
    logger.debug(texto) em qualquer camada apareceria aqui."""
    falso.falhar("/v1/search", 429, retry_after="1")
    falso.falhar("/children", 503)
    falso.falhar("/v1/pages/", 404)

    # O LeitorNotion já foi criado: o SDK põe o logger dele em WARNING na criação, e o at_level desce para DEBUG.
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="app"), \
            caplog.at_level(logging.DEBUG, logger="app.notion.sdk"), caplog.at_level(logging.DEBUG, logger="httpx"):
        for pagina in leitor.paginas().paginas:
            leitor.blocos(pagina["id"])
        leitor.pagina("00000000-0000-0000-0000-000000000000")

    assert "notion_nova_tentativa" in caplog.text  # o log aconteceu: o teste não passa por estar vazio
    assert "request fail" in caplog.text  # o do SDK também
    assert TOKEN_DE_TESTE not in caplog.text
    textos = textos_do_workspace(falso.ws)
    assert len(textos) > 40
    for texto in textos:
        assert texto not in caplog.text, texto
