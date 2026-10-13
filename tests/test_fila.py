"""Testes da Fila: POST /insights/{id}/aprovar e /rejeitar, no banco temporário dos testes (sem LLM).

As transições em si (o que pode ir para onde) já têm 100% de cobertura em test_dominio.py. Aqui o foco é a ligação
rota -> dominio -> banco: o código HTTP certo (404 e 422, como a tela espera), o status gravado e a linha no
historico_status.
"""
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main
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


def criar(client, **campos) -> int:
    """Grava um item (nasce `proposto`) e devolve o id."""
    return client.post("/insights", json=novo(**campos)).json()["id"]


def historico(insight_id: int) -> list[tuple]:
    """As mudanças de status do item, na ordem em que aconteceram."""
    with SessionLocal() as db:
        linhas = db.scalars(
            select(HistoricoStatus).where(HistoricoStatus.insight_id == insight_id).order_by(HistoricoStatus.id)
        )
        return [(h.de, h.para, h.por_quem, h.motivo) for h in linhas]


CRIACAO = (None, "proposto", "Rafael", None)  # a 1ª linha do histórico de todo item


# --- caminho feliz --------------------------------------------------------------------------

def test_aprovar_muda_para_validado_e_grava_historico(client):
    id_ = criar(client)

    r = client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"})

    assert r.status_code == 200
    assert r.json()["status"] == "validado"
    assert historico(id_) == [CRIACAO, ("proposto", "validado", "Davi", None)]


def test_item_aprovado_aparece_na_lista_de_validados(client):
    """É por essa lista que o Playbook (e o consultor) enxergam o item."""
    id_ = criar(client)
    client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"})

    r = client.get("/insights", params={"status": "validado", "limit": 100})

    assert id_ in [i["id"] for i in r.json()["itens"]]


def test_historico_a_validar_tambem_pode_ser_aprovado(client):
    """Itens de fonte antiga entram como historico_a_validar (não pela API) e seguem o mesmo caminho de proposto."""
    id_ = criar(client)
    with SessionLocal() as db:
        db.get(Insight, id_).status = "historico_a_validar"
        db.commit()

    r = client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"})

    assert r.json()["status"] == "validado"
    assert historico(id_)[-1] == ("historico_a_validar", "validado", "Davi", None)


def test_rejeitar_grava_motivo_no_item_e_no_historico(client):
    id_ = criar(client)

    r = client.post(f"/insights/{id_}/rejeitar", json={"por_quem": "Davi", "motivo": "  repete o INS-3  "})

    assert r.status_code == 200
    assert r.json()["status"] == "obsoleto"
    assert r.json()["motivo_obsolescencia"] == "repete o INS-3"  # espaços das pontas removidos
    assert historico(id_) == [CRIACAO, ("proposto", "obsoleto", "Davi", "repete o INS-3")]


def test_resposta_traz_as_relacoes_do_item(client):
    existente = criar(client)
    id_ = criar(client, relacoes=[{"relacionado_id": existente, "tipo": "reforca"}])

    r = client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"})

    assert r.json()["relacoes"] == [{"relacionado_id": existente, "tipo": "reforca"}]


# --- regras do domínio viram códigos HTTP ---------------------------------------------------

@pytest.mark.parametrize("corpo", [{}, {"motivo": ""}, {"motivo": "   "}])
def test_rejeitar_sem_motivo_vira_422_e_nao_muda_nada(client, corpo):
    id_ = criar(client)

    r = client.post(f"/insights/{id_}/rejeitar", json={"por_quem": "Davi"} | corpo)

    assert r.status_code == 422
    assert "informe o motivo" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Insight, id_).status == "proposto"
    assert historico(id_) == [CRIACAO]


def test_aprovar_duas_vezes_vira_422(client):
    """Duplo clique no Aprovar: o 2º pedido tenta validado -> validado, que o ciclo de vida não permite."""
    id_ = criar(client)
    assert client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"}).status_code == 200

    r = client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"})

    assert r.status_code == 422
    assert "de 'validado' para 'validado'" in r.json()["detail"]  # a mensagem do dominio, que a tela mostra
    assert historico(id_) == [CRIACAO, ("proposto", "validado", "Davi", None)]  # uma aprovação só


@pytest.mark.parametrize("rota, corpo", [
    ("aprovar", {"por_quem": "Davi"}),  # obsoleto -> validado
    ("rejeitar", {"por_quem": "Davi", "motivo": "de novo"}),  # obsoleto -> obsoleto
])
def test_item_rejeitado_nao_muda_mais_422(client, rota, corpo):
    id_ = criar(client)
    client.post(f"/insights/{id_}/rejeitar", json={"por_quem": "Davi", "motivo": "fora do escopo"})

    r = client.post(f"/insights/{id_}/{rota}", json=corpo)

    assert r.status_code == 422
    assert len(historico(id_)) == 2  # criação + a rejeição; nada novo


# --- entradas inválidas ---------------------------------------------------------------------

@pytest.mark.parametrize("rota", ["aprovar", "rejeitar"])
def test_item_inexistente_vira_404(client, rota):
    r = client.post(f"/insights/999999/{rota}", json={"por_quem": "Davi", "motivo": "x"})

    assert r.status_code == 404
    assert "INS-999999" in r.json()["detail"]


@pytest.mark.parametrize("corpo", [{}, {"por_quem": "   "}])
def test_aprovar_sem_por_quem_vira_422(client, corpo):
    id_ = criar(client)

    assert client.post(f"/insights/{id_}/aprovar", json=corpo).status_code == 422
    assert historico(id_) == [CRIACAO]


# --- concorrência ---------------------------------------------------------------------------

def test_duas_pessoas_ao_mesmo_tempo_a_segunda_recebe_422(client):
    """Davi e Rafael abrem a Fila juntos. Davi aprova; logo depois, Rafael (que ainda vê o item como `proposto`)
    rejeita. Sem o WHERE status = de, a rejeição passaria por cima da aprovação do Davi."""
    id_ = criar(client)
    with SessionLocal() as db_rafael:
        # Rafael leu o item: "proposto" na memória da sessão dele. A variável é necessária: a sessão só guarda
        # referências fracas, e sem ela o item seria descartado e relido do banco (já "validado").
        na_tela_do_rafael = db_rafael.get(Insight, id_)
        assert na_tela_do_rafael.status == "proposto"
        assert client.post(f"/insights/{id_}/aprovar", json={"por_quem": "Davi"}).status_code == 200

        with pytest.raises(HTTPException) as erro:
            main._mudar_status(db_rafael, id_, "obsoleto", "Rafael", "repetido")

    assert erro.value.status_code == 422
    assert "Recarregue a Fila" in erro.value.detail
    assert historico(id_) == [CRIACAO, ("proposto", "validado", "Davi", None)]
