"""POST /fontes/sincronizar (T4c): a importação do Notion pela API, em segundo plano. Sem rede e sem modelo: o leitor
vem do NotionFalso (pela dependência leitor_notion) e o curador é o CuradorDeLote de test_curadoria_notion.

O TestClient só devolve a resposta DEPOIS de rodar a tarefa em segundo plano (BackgroundTasks): quando o POST volta, a
execução já terminou. Por isso o teste do 409 põe a execução `rodando` direto no banco.
"""
import logging
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import importacao, llm, main, notion
from app.db import SessionLocal
from app.main import app, leitor_notion
from app.models import ExecucaoImportacao, Fonte, Insight
from app.notion import LeitorNotion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, limpar_banco_da_importacao
from tests.test_curadoria_notion import CuradorDeLote, retrato, usar


@pytest.fixture
def falso(monkeypatch):
    monkeypatch.setattr(notion, "_dormir", lambda segundos: None)
    monkeypatch.setattr(llm.settings, "gemini_api_key", "chave-de-teste")  # nunca a do .env: o curador é o falso
    with SessionLocal() as db:
        limpar_banco_da_importacao(db)
    return NotionFalso()


@pytest.fixture
def curador(monkeypatch):
    return usar(monkeypatch, CuradorDeLote())


@pytest.fixture
def com_o_notion_falso(falso):
    """A dependência do leitor troca o Notion de verdade pelo falso (um leitor novo por requisição, como no app)."""
    app.dependency_overrides[leitor_notion] = lambda: LeitorNotion(token=TOKEN_DE_TESTE,
                                                                   cliente_http=falso.cliente_http())
    yield
    app.dependency_overrides.pop(leitor_notion, None)


@pytest.fixture
def client(com_o_notion_falso, curador):
    with TestClient(app) as c:
        yield c


def execucao(execucao_id: int) -> ExecucaoImportacao:
    with SessionLocal() as db:
        return db.get(ExecucaoImportacao, execucao_id)


def contar(modelo) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(modelo))


def rodando(dry_run: bool = False) -> int:
    """Uma execução que ainda roda (a de outra requisição, ou a de um servidor que caiu)."""
    with SessionLocal() as db:
        e = ExecucaoImportacao(inicio=datetime(2026, 10, 19, 9, 0), status="rodando", dry_run=dry_run)
        db.add(e)
        db.commit()
        return e.id


# --- o caminho feliz ----------------------------------------------------------------------------------------

def test_devolve_202_com_o_id_e_a_execucao_termina_concluida(client):
    r = client.post("/fontes/sincronizar", json={"origem": "notion"})

    assert r.status_code == 202
    e = execucao(r.json()["execucao_id"])
    assert (e.status, e.fase, e.dry_run, e.teto_usd) == ("concluida", "fim", False, 1.0)  # o teto padrão
    assert (e.paginas_lidas, e.paginas_curadas, e.insights_propostos) == (10, 6, 6)
    assert contar(Fonte) == 10
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).where(Insight.fonte == "notion")) == 6


def test_limite_de_paginas_e_teto_chegam_na_importacao(client):
    r = client.post("/fontes/sincronizar", json={"origem": "notion", "limite_paginas": 3, "teto_usd": 0.25})

    e = execucao(r.json()["execucao_id"])
    assert (e.paginas_lidas, e.teto_usd) == (3, 0.25)


def test_duas_execucoes_pela_api_nao_mudam_nada(client):
    client.post("/fontes/sincronizar", json={"origem": "notion"})
    with SessionLocal() as db:
        antes = retrato(db)

    r = client.post("/fontes/sincronizar", json={"origem": "notion"})

    with SessionLocal() as db:
        assert retrato(db) == antes
    e = execucao(r.json()["execucao_id"])
    assert (e.paginas_novas, e.paginas_alteradas, e.paginas_curadas, e.gasto_usd) == (0, 0, 0, 0.0)


def test_dry_run_nao_muda_as_fontes_e_o_resumo_o_ignora(client, falso, curador):
    real = client.post("/fontes/sincronizar", json={"origem": "notion"}).json()["execucao_id"]
    with SessionLocal() as db:
        antes = retrato(db)
    falso.editar("Prospecção por indicação", "Indicação no encerramento trouxe três clientes novos no ano.")
    chamadas = len(curador.textos)

    r = client.post("/fontes/sincronizar", json={"origem": "notion", "dry_run": True})

    assert r.status_code == 202
    e = execucao(r.json()["execucao_id"])
    assert (e.status, e.dry_run, e.paginas_alteradas, e.teto_usd) == ("concluida", True, 1, None)
    with SessionLocal() as db:
        assert retrato(db) == antes  # nem a página alterada foi gravada
    assert len(curador.textos) == chamadas  # o modelo não foi chamado
    assert client.get("/fontes/resumo").json()["ultima_execucao"]["id"] == real


# --- uma de cada vez ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("pedido", [{"origem": "notion"}, {"origem": "notion", "dry_run": True}])
def test_409_com_uma_importacao_rodando(client, falso, pedido):
    ja_rodando = rodando()

    r = client.post("/fontes/sincronizar", json=pedido)

    assert r.status_code == 409
    assert f"execução #{ja_rodando}" in r.json()["detail"]
    assert contar(ExecucaoImportacao) == 1  # nenhuma execução nova
    assert falso.pedidos == []  # nem leu o Notion


def test_a_execucao_e_criada_com_a_trava_fechada(monkeypatch, client):
    """A conferência do 409 e a criação da execução ficam dentro da mesma trava: duas requisições ao mesmo tempo não
    passam as duas pela conferência antes de uma delas criar a execução."""
    travada = []
    criar = importacao.nova_execucao

    def criar_espiando(*args, **kwargs):
        travada.append(main._uma_sincronizacao_por_vez.locked())
        return criar(*args, **kwargs)

    monkeypatch.setattr(importacao, "nova_execucao", criar_espiando)

    assert client.post("/fontes/sincronizar", json={"origem": "notion"}).status_code == 202
    assert travada == [True]
    assert not main._uma_sincronizacao_por_vez.locked()  # e é aberta de novo


def test_um_dry_run_rodando_nao_bloqueia(client):
    rodando(dry_run=True)

    assert client.post("/fontes/sincronizar", json={"origem": "notion"}).status_code == 202


def test_na_subida_a_execucao_que_ficou_rodando_vira_erro_e_o_post_volta_a_funcionar(com_o_notion_falso, curador):
    """O servidor caiu (ou levou dois Ctrl+C) no meio de uma execução: sem isto, o 409 travaria para sempre."""
    caiu = rodando()

    with TestClient(app) as client:  # o `with` roda o lifespan (a subida do app)
        e = execucao(caiu)
        assert (e.status, e.erro) == ("erro", "interrompida") and e.fim is not None
        assert client.post("/fontes/sincronizar", json={"origem": "notion"}).status_code == 202


def test_marcar_interrompidas_so_mexe_nas_que_rodam(falso):
    with SessionLocal() as db:
        terminada = ExecucaoImportacao(inicio=datetime(2026, 10, 19, 8, 0), fim=datetime(2026, 10, 19, 8, 5),
                                       status="concluida", fase="fim")
        db.add(terminada)
        db.commit()
    caiu = rodando()

    with SessionLocal() as db:
        assert importacao.marcar_interrompidas(db) == 1
    assert (execucao(terminada.id).status, execucao(caiu).status) == ("concluida", "erro")


# --- configuração e entrada ---------------------------------------------------------------------------------

def test_sem_token_do_notion_erro_claro_e_nada_e_criado(monkeypatch, falso, curador):
    monkeypatch.setattr(notion.settings, "notion_token", "")  # sem o override: o leitor de verdade, sem token

    with TestClient(app) as client:
        r = client.post("/fontes/sincronizar", json={"origem": "notion", "dry_run": True})

    assert r.status_code == 503
    assert "Falta NOTION_TOKEN no .env" in r.json()["detail"]
    assert contar(ExecucaoImportacao) == 0


def test_sem_chave_do_gemini_so_o_dry_run_roda(monkeypatch, client, falso):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    r = client.post("/fontes/sincronizar", json={"origem": "notion"})

    assert r.status_code == 503
    assert "Falta GEMINI_API_KEY no .env" in r.json()["detail"]
    assert contar(ExecucaoImportacao) == 0 and falso.pedidos == []
    assert client.post("/fontes/sincronizar", json={"origem": "notion", "dry_run": True}).status_code == 202


@pytest.mark.parametrize("corpo", [
    '{}',
    '{"origem": "canva"}',
    '{"origem": "notion", "limite_paginas": 0}',
    '{"origem": "notion", "teto_usd": 0}',
    '{"origem": "notion", "teto_usd": -1}',
    '{"origem": "notion", "teto": 1}',  # campo que não existe (erro de digitação)
])
def test_entrada_invalida_vira_422(client, corpo):
    r = client.post("/fontes/sincronizar", content=corpo, headers={"content-type": "application/json"})

    assert r.status_code == 422
    assert contar(ExecucaoImportacao) == 0


def test_teto_infinito_e_recusado(com_o_notion_falso, curador):
    """O 1e999 do JSON vira infinito, e um teto infinito deixaria o curador gastar sem limite. O allow_inf_nan=False
    recusa. A resposta sai 500, não 422: o FastAPI repete o valor no detalhe do erro, e infinito não é JSON válido."""
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/fontes/sincronizar", content='{"origem": "notion", "teto_usd": 1e999}',
                        headers={"content-type": "application/json"})

    assert r.status_code in (422, 500)
    assert contar(ExecucaoImportacao) == 0


# --- o que dá errado em segundo plano -----------------------------------------------------------------------

def test_erro_em_segundo_plano_fica_na_execucao_sem_texto_de_pagina(monkeypatch, client, caplog):
    """A mensagem de um erro inesperado pode ter texto de página: nem a execução nem o log a repetem."""
    def quebrar(*args):
        raise RuntimeError("TEXTO-DE-PAGINA-NO-ERRO")

    monkeypatch.setattr(importacao, "_triar", quebrar)
    with caplog.at_level(logging.DEBUG, logger="app"):
        r = client.post("/fontes/sincronizar", json={"origem": "notion"})

    assert r.status_code == 202  # a resposta já tinha saído quando a importação caiu
    e = execucao(r.json()["execucao_id"])
    assert (e.status, e.erro) == ("erro", "RuntimeError")
    assert '"evento": "sincronizacao_falhou"' in caplog.text
    assert "TEXTO-DE-PAGINA-NO-ERRO" not in caplog.text
    assert client.post("/fontes/sincronizar", json={"origem": "notion"}).status_code == 202  # não ficou travado


# --- GET /fontes/execucoes/{id} -----------------------------------------------------------------------------

def ver(client, execucao_id: int) -> dict:
    r = client.get(f"/fontes/execucoes/{execucao_id}")
    assert r.status_code == 200
    return r.json()


def test_execucao_concluida_com_as_contagens_o_gasto_e_a_estimativa(client):
    execucao_id = client.post("/fontes/sincronizar", json={"origem": "notion"}).json()["execucao_id"]

    e = ver(client, execucao_id)

    assert (e["id"], e["status"], e["fase"], e["dry_run"], e["erro"]) == (execucao_id, "concluida", "fim", False, None)
    assert e["contagens"] == {"lidas": 10, "novas": 10, "alteradas": 0, "puladas": 4, "removidas": 0, "falhas": 0,
                              "curadas": 6, "insights_propostos": 6}
    assert e["gasto_usd"] == pytest.approx(0.006) and e["teto_usd"] == 1.0
    assert e["estimativa_usd"] > 0
    assert e["inicio"] and e["fim"]


def test_execucao_que_parou_no_teto(monkeypatch, client):
    """Cada página "custa" US$ 0,50 no curador falso: com teto de US$ 1, duas entram e quatro ficam esperando."""
    usar(monkeypatch, CuradorDeLote(custo=0.5))
    execucao_id = client.post("/fontes/sincronizar", json={"origem": "notion", "teto_usd": 1}).json()["execucao_id"]

    e = ver(client, execucao_id)

    assert (e["status"], e["fase"]) == ("parou_no_teto", "fim")
    assert (e["contagens"]["curadas"], e["gasto_usd"], e["teto_usd"]) == (2, 1.0, 1.0)


def test_execucao_com_erro_do_notion(client, falso):
    falso.falhar("/v1/search", 401)
    execucao_id = client.post("/fontes/sincronizar", json={"origem": "notion"}).json()["execucao_id"]

    e = ver(client, execucao_id)

    assert (e["status"], e["fase"], e["erro"]) == ("erro", "sincronizando", "ErroNotion (401)")
    assert e["contagens"]["lidas"] == 0 and e["estimativa_usd"] is None and e["fim"]
    assert TOKEN_DE_TESTE not in str(e)


def test_execucao_do_dry_run(client):
    execucao_id = client.post("/fontes/sincronizar", json={"origem": "notion", "dry_run": True}).json()["execucao_id"]

    e = ver(client, execucao_id)

    assert (e["status"], e["dry_run"], e["teto_usd"], e["gasto_usd"]) == ("concluida", True, None, 0.0)
    assert e["contagens"]["curadas"] == 0 and e["estimativa_usd"] > 0


def test_execucao_rodando_mostra_o_progresso(client):
    """Enquanto roda, o GET mostra o que já foi gravado (aqui, a execução que ficou parada no banco)."""
    execucao_id = rodando()

    e = ver(client, execucao_id)

    assert (e["status"], e["fase"], e["fim"], e["estimativa_usd"]) == ("rodando", "sincronizando", None, None)


def test_execucao_que_nao_existe_e_404(client):
    r = client.get("/fontes/execucoes/999999")

    assert r.status_code == 404
    assert r.json()["detail"] == "A execução #999999 não existe."
