"""Testes do POST /chat. O llm.consultar é trocado por uma função falsa (mock):
os testes não chamam o Gemini, não gastam cota e não dependem de internet."""
from fastapi.testclient import TestClient

from app import llm
from app.main import app


def test_chat_ok(monkeypatch):
    recebido = {}

    def consultar_falso(mensagem, historico):
        recebido["mensagem"] = mensagem
        recebido["historico"] = historico
        return "Proponha um piloto [EX-02]."

    monkeypatch.setattr(llm, "consultar", consultar_falso)

    historico = [
        {"role": "user", "text": "Vou apresentar proposta pra hotelaria."},
        {"role": "model", "text": "Comece por um piloto [EX-02]."},
    ]
    with TestClient(app) as client:
        r = client.post("/chat", json={"mensagem": "E se disser que está caro?", "historico": historico})

    assert r.status_code == 200
    assert r.json() == {"resposta": "Proponha um piloto [EX-02]."}
    assert recebido["mensagem"] == "E se disser que está caro?"
    assert recebido["historico"] == historico


def test_chat_erro_llm_vira_502(monkeypatch):
    def consultar_com_erro(mensagem, historico):
        raise llm.ErroLLM("A chave do Gemini é inválida.")

    monkeypatch.setattr(llm, "consultar", consultar_com_erro)

    with TestClient(app) as client:
        r = client.post("/chat", json={"mensagem": "oi"})

    assert r.status_code == 502
    assert r.json() == {"detail": "A chave do Gemini é inválida."}


def test_chat_mensagem_vazia_422():
    with TestClient(app) as client:
        r = client.post("/chat", json={"mensagem": ""})

    assert r.status_code == 422


def test_chat_role_invalido_422():
    with TestClient(app) as client:
        r = client.post("/chat", json={"mensagem": "oi", "historico": [{"role": "assistant", "text": "x"}]})

    assert r.status_code == 422
    