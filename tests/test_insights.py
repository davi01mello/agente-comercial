"""Testes de POST e GET /insights, no banco temporário dos testes (sem LLM).

O banco é o mesmo para todos os testes da execução, então cada teste usa títulos e segmentos próprios
(com uuid) para não enxergar o que os outros gravaram.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import HistoricoStatus, Insight


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def novo(**campos) -> dict:
    """Um item válido com título único. Os testes mudam só o campo que importa."""
    item = {
        "titulo": f"Diagnóstico antes da proposta {uuid.uuid4().hex[:8]}",
        "tipo": "aprendizado",
        "secao": "reuniao_diagnostico",
        "descricao": "Abrir com perguntas fez o cliente contar os problemas.",
        "autor": "Rafael",
    }
    return item | campos


# --- POST /insights -------------------------------------------------------------------------

def test_cria_como_proposto_e_grava_historico(client):
    r = client.post("/insights", json=novo())

    assert r.status_code == 201
    corpo = r.json()
    assert corpo["status"] == "proposto"
    assert corpo["avisos"] == []
    with SessionLocal() as db:
        historico = db.scalars(select(HistoricoStatus).where(HistoricoStatus.insight_id == corpo["id"])).all()
    assert [(h.de, h.para, h.por_quem) for h in historico] == [(None, "proposto", "Rafael")]


def test_status_do_body_e_ignorado(client):
    r = client.post("/insights", json=novo(status="consolidado"))

    assert r.status_code == 201
    assert r.json()["status"] == "proposto"


@pytest.mark.parametrize("campos, trecho", [
    ({"tipo": "regra", "evidencia": 1}, "virar regra"),
    ({"tipo": "case", "evidencia": 4, "resultado": "o cliente adorou"}, "exige um número"),
])
def test_regra_de_negocio_vira_422(client, campos, trecho):
    r = client.post("/insights", json=novo(**campos))

    assert r.status_code == 422
    assert trecho in r.json()["detail"]


@pytest.mark.parametrize("campos", [{"tipo": "dica"}, {"secao": "vendas"}, {"evidencia": 5}, {"titulo": "  "}])
def test_campo_invalido_vira_422(client, campos):
    assert client.post("/insights", json=novo(**campos)).status_code == 422


def test_dado_pessoal_grava_mas_avisa(client):
    r = client.post("/insights", json=novo(contexto_cliente="falar com ana@hotelx.com.br"))

    assert r.status_code == 201
    assert r.json()["avisos"] == [
        "Possível e-mail em 'contexto_cliente': dado pessoal de cliente não deve entrar na base (LGPD)."
    ]


@pytest.mark.parametrize("digitado", ["saude", "Saúde", " SAUDE "])
def test_segmento_com_ou_sem_acento_vira_o_mesmo(client, digitado):
    r = client.post("/insights", json=novo(segmento=digitado))
    assert r.status_code == 201
    assert r.json()["segmento"] == "saúde"


def test_filtro_por_segmento_ignora_acento_e_caixa(client):
    titulo = f"seg-{uuid.uuid4().hex[:8]}"
    id_ = client.post("/insights", json=novo(titulo=titulo, segmento="Saúde")).json()["id"]

    ids = [i["id"] for i in client.get("/insights", params={"segmento": "SAUDE", "limit": 100}).json()["itens"]]

    assert id_ in ids


def test_segmento_e_gravado_em_minusculo(client):
    r = client.post("/insights", json=novo(segmento="  Hotelaria "))

    assert r.json()["segmento"] == "hotelaria"


def test_relacoes_sao_gravadas_sem_repetir(client):
    existente = client.post("/insights", json=novo()).json()["id"]
    relacao = {"relacionado_id": existente, "tipo": "reforca"}

    r = client.post("/insights", json=novo(relacoes=[relacao, relacao]))

    assert r.status_code == 201
    assert r.json()["relacoes"] == [relacao]


def test_relacao_com_item_inexistente_vira_422(client):
    r = client.post("/insights", json=novo(relacoes=[{"relacionado_id": 999_999, "tipo": "reforca"}]))

    assert r.status_code == 422
    assert "INS-999999" in r.json()["detail"]


def test_duplo_clique_vira_409(client):
    item = novo()
    assert client.post("/insights", json=item).status_code == 201

    r = client.post("/insights", json=item)

    assert r.status_code == 409


def test_mesmo_item_depois_de_60s_pode(client):
    item = novo(data_evento="2026-03-12")
    primeiro = client.post("/insights", json=item).json()["id"]
    with SessionLocal() as db:  # "envelhece" o primeiro em vez de esperar 60s de verdade
        db.get(Insight, primeiro).criado_em = datetime.now() - timedelta(days=1)
        db.commit()

    assert client.post("/insights", json=item).status_code == 201


# --- GET /insights --------------------------------------------------------------------------

def test_lista_com_filtros_e_paginacao(client):
    segmento = f"teste-{uuid.uuid4().hex[:8]}"  # segmento só deste teste
    ids = [client.post("/insights", json=novo(segmento=segmento)).json()["id"] for _ in range(3)]
    client.post("/insights", json=novo(segmento=segmento, secao="proposta"))

    r = client.get("/insights", params={"segmento": segmento, "secao": "reuniao_diagnostico", "limit": 2})

    corpo = r.json()
    assert r.status_code == 200
    assert corpo["total"] == 3
    assert [i["id"] for i in corpo["itens"]] == [ids[2], ids[1]]  # mais novo primeiro

    pagina2 = client.get("/insights", params={"segmento": segmento, "secao": "reuniao_diagnostico", "limit": 2,
                                              "offset": 2}).json()
    assert [i["id"] for i in pagina2["itens"]] == [ids[0]]


def test_lista_mostra_relacoes(client):
    segmento = f"teste-{uuid.uuid4().hex[:8]}"
    existente = client.post("/insights", json=novo()).json()["id"]
    client.post("/insights", json=novo(segmento=segmento, relacoes=[{"relacionado_id": existente,
                                                                     "tipo": "contradiz"}]))

    itens = client.get("/insights", params={"segmento": segmento}).json()["itens"]

    assert itens[0]["relacoes"] == [{"relacionado_id": existente, "tipo": "contradiz"}]


@pytest.mark.parametrize("params", [{"status": "aprovado"}, {"stauts": "proposto"}, {"limit": 101}, {"offset": -1}])
def test_filtro_invalido_vira_422(client, params):
    assert client.get("/insights", params=params).status_code == 422