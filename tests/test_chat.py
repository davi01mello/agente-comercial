"""Testes do POST /chat. O llm.consultar é trocado por uma função falsa (mock):
os testes não chamam o Gemini, não gastam cota e não dependem de internet."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def recebido(monkeypatch):
    """Troca o llm.consultar por um falso que anota o que recebeu. Lista vazia = o modelo nem foi chamado."""
    chamadas = []

    def consultar_falso(mensagem, historico, base):
        chamadas.append({"mensagem": mensagem, "historico": historico, "base": base})
        return "Proponha um piloto [INS-2]."

    monkeypatch.setattr(llm, "consultar", consultar_falso)
    return chamadas


def test_chat_ok(client, recebido):
    historico = [
        {"role": "user", "text": "Vou apresentar proposta pra hotelaria."},
        {"role": "model", "text": "Comece por um piloto [INS-2]."},
    ]

    r = client.post("/chat", json={"mensagem": "E se disser que está caro?", "historico": historico})

    assert r.status_code == 200
    assert r.json() == {"resposta": "Proponha um piloto [INS-2]."}
    assert recebido[0]["mensagem"] == "E se disser que está caro?"
    assert recebido[0]["historico"] == historico


def test_chat_usa_os_aprovados_do_banco_e_nunca_os_propostos(client, recebido):
    marca = uuid.uuid4().hex[:8]
    novo = {"tipo": "aprendizado", "secao": "proposta", "descricao": "x", "autor": "Rafael"}
    aprovado = client.post("/insights", json=novo | {"titulo": f"aprovado {marca}"}).json()["id"]
    client.post(f"/insights/{aprovado}/aprovar", json={"por_quem": "Davi"})
    proposto = client.post("/insights", json=novo | {"titulo": f"proposto {marca}"}).json()["id"]

    client.post("/chat", json={"mensagem": "oi"})

    base = recebido[0]["base"]
    assert f"[INS-{aprovado}] aprovado {marca}" in base
    assert f"[INS-{proposto}]" not in base


@pytest.mark.parametrize("corpo, onde", [
    ({"mensagem": "liguei para ana@hotelx.com.br, e agora?"}, "e-mail em 'mensagem'"),
    (
        {"mensagem": "e agora?", "historico": [
            {"role": "user", "text": "o diretor atende no (81) 99876-5432"},
            {"role": "model", "text": "Entendi."},
        ]},
        "telefone em 'mensagem anterior 1'",
    ),
])
def test_dado_pessoal_vira_422_e_nem_chamou_o_modelo(client, recebido, corpo, onde):
    r = client.post("/chat", json=corpo)

    assert r.status_code == 422
    assert onde in r.json()["detail"]
    assert "ana@hotelx" not in r.json()["detail"] and "99876" not in r.json()["detail"]  # nunca repete o dado
    assert recebido == []  # o texto nem saiu do servidor


def test_fala_do_modelo_nao_e_conferida(client, recebido):
    """Só o que o usuário escreveu é checado (como no curador): a fala do modelo não tem como ser corrigida."""
    historico = [{"role": "user", "text": "e o pedido?"}, {"role": "model", "text": "Pedido 12345678901 [INS-2]."}]

    r = client.post("/chat", json={"mensagem": "ok", "historico": historico})

    assert r.status_code == 200


def test_chat_erro_llm_vira_502(client, monkeypatch):
    def consultar_com_erro(mensagem, historico, base):
        raise llm.ErroLLM("A chave do Gemini é inválida.")

    monkeypatch.setattr(llm, "consultar", consultar_com_erro)

    r = client.post("/chat", json={"mensagem": "oi"})

    assert r.status_code == 502
    assert r.json() == {"detail": "A chave do Gemini é inválida."}


def test_chat_mensagem_vazia_422(client):
    r = client.post("/chat", json={"mensagem": ""})

    assert r.status_code == 422


def test_chat_role_invalido_422(client):
    r = client.post("/chat", json={"mensagem": "oi", "historico": [{"role": "assistant", "text": "x"}]})

    assert r.status_code == 422
