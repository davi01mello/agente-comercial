"""Testes de GET /fontes e GET /fontes/resumo (a tela de Fontes). O banco é o mesmo de toda a execução, então cada
teste usa títulos com uuid e filtra por eles."""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import ExecucaoImportacao, Fonte, Insight


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def criar_fonte(titulo: str, status: str = "importada", editado_em=datetime(2026, 10, 13, 12, 0), origem="notion"):
    unico = uuid.uuid4().hex
    with SessionLocal() as db:
        f = Fonte(origem=origem, id_externo=unico, titulo=titulo, url=f"https://www.notion.so/{unico}",
                  markdown="TEXTO SECRETO DA PÁGINA", hash_conteudo=unico, editado_em=editado_em,
                  importado_em=editado_em, status=status)
        db.add(f)
        db.commit()
        return f.url


def criar_item(url: str, status: str):
    with SessionLocal() as db:
        db.add(Insight(titulo="Item da fonte", tipo="aprendizado", secao="proposta", descricao="d",
                       autor="importação Notion", fonte="notion", fonte_ref=url, status=status))
        db.commit()


def test_lista_a_fonte_com_os_itens_que_ela_gerou(client):
    marca = uuid.uuid4().hex[:8]
    url = criar_fonte(f"Manual {marca}")
    criar_item(url, "historico_a_validar")
    criar_item(url, "historico_a_validar")
    criar_item(url, "validado")

    r = client.get("/fontes", params={"q": marca})

    assert r.status_code == 200 and r.json()["total"] == 1
    fonte = r.json()["itens"][0]
    assert fonte["titulo"] == f"Manual {marca}" and fonte["url"] == url and fonte["status"] == "importada"
    assert fonte["itens"] == {"historico_a_validar": 2, "validado": 1}


def test_nunca_devolve_o_texto_da_pagina(client):
    marca = uuid.uuid4().hex[:8]
    criar_fonte(f"Sigilo {marca}")

    corpo = client.get("/fontes", params={"q": marca}).text

    assert "TEXTO SECRETO" not in corpo and "markdown" not in corpo


def test_filtra_por_status_origem_e_titulo_sem_ligar_para_caixa(client):
    marca = uuid.uuid4().hex[:8]
    criar_fonte(f"Alpha {marca}", "importada")
    criar_fonte(f"Beta {marca}", "pulada_dado_pessoal")
    criar_fonte(f"Gama {marca}", "importada", origem="drive")

    assert client.get("/fontes", params={"q": marca.upper()}).json()["total"] == 3
    assert client.get("/fontes", params={"q": marca, "status": "pulada_dado_pessoal"}).json()["total"] == 1
    assert client.get("/fontes", params={"q": marca, "origem": "drive"}).json()["total"] == 1


def test_busca_trata_percentual_como_texto(client):
    marca = uuid.uuid4().hex[:8]
    criar_fonte(f"Meta de 100% {marca}")
    criar_fonte(f"Meta de 1000 {marca}")

    assert client.get("/fontes", params={"q": f"100% {marca}"}).json()["total"] == 1


def test_ordem_e_paginacao_mais_editada_primeiro(client):
    marca = uuid.uuid4().hex[:8]
    for dia in (1, 2, 3):
        criar_fonte(f"P{dia} {marca}", editado_em=datetime(2026, 9, dia, 10, 0))

    pag1 = client.get("/fontes", params={"q": marca, "limit": 2}).json()
    pag2 = client.get("/fontes", params={"q": marca, "limit": 2, "offset": 2}).json()

    assert [i["titulo"] for i in pag1["itens"]] == [f"P3 {marca}", f"P2 {marca}"]
    assert [i["titulo"] for i in pag2["itens"]] == [f"P1 {marca}"] and pag1["total"] == 3


@pytest.mark.parametrize(
    "params",
    [{"status": "inventado"}, {"limit": 0}, {"limit": 201}, {"offset": -1}, {"stauts": "a_curar"}],
)
def test_filtro_invalido_vira_422(client, params):
    assert client.get("/fontes", params=params).status_code == 422


def test_resumo_conta_por_status_e_origem_e_traz_a_ultima_execucao(client):
    antes = client.get("/fontes/resumo").json()
    criar_fonte("Resumo a", "a_curar")
    criar_fonte("Resumo b", "removida", origem="drive")
    with SessionLocal() as db:
        db.add(ExecucaoImportacao(
            inicio=datetime(2099, 1, 1, 8, 0), fim=datetime(2099, 1, 1, 8, 5),
            paginas_lidas=7, paginas_novas=3, paginas_alteradas=2, paginas_falhas=1,
        ))
        db.commit()

    depois = client.get("/fontes/resumo").json()

    assert depois["total"] == antes["total"] + 2
    assert depois["por_status"].get("a_curar", 0) == antes["por_status"].get("a_curar", 0) + 1
    assert depois["por_origem"].get("drive", 0) == antes["por_origem"].get("drive", 0) + 1
    ultima = depois["ultima_execucao"]
    campos = ("paginas_lidas", "paginas_novas", "paginas_alteradas", "paginas_falhas")
    assert tuple(ultima[c] for c in campos) == (7, 3, 2, 1)
