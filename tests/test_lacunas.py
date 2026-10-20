"""Lacunas (o que o consultor não soube responder) e o "Registrar isso" a partir do chat (T7). Sem Gemini."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import lacunas, llm
from app.db import SessionLocal
from app.main import app
from app.models import Insight, Lacuna
from tests.test_curador import CuradorFalso, proposta, usar

LACUNA = "A base não cobre preço para o setor público. Se você viveu algo assim, registre."


@pytest.fixture
def client():
    with SessionLocal() as db:  # cada teste começa sem lacunas
        db.execute(delete(Lacuna))
        db.commit()
    with TestClient(app) as c:
        yield c


def consultor(monkeypatch, resposta):
    monkeypatch.setattr(llm, "consultar", lambda mensagem, historico, base, documentos="": resposta)


# --- as funções puras ---------------------------------------------------------------------------

@pytest.mark.parametrize("resposta, esperado", [
    ("A base não cobre preço para o setor público.", True),
    ("A BASE NAO COBRE isso ainda", True),
    ("a base não  cobre", False),  # dois espaços: não é a frase do prompt
    ("Use o piloto [INS-2].", False),
    ("", False),
])
def test_e_lacuna_pela_frase_do_prompt(resposta, esperado):
    assert lacunas.e_lacuna(resposta) is esperado


def test_chave_junta_perguntas_parecidas_em_qualquer_ordem():
    a = lacunas.chave_da("Como negociar preço com hotelaria?")
    b = lacunas.chave_da("hotelaria: preço, negociar como")
    assert a == b and a
    assert lacunas.chave_da("e de o a") == ""  # só palavras vazias: nada para guardar


# --- o /chat registra a lacuna --------------------------------------------------------------------

def test_chat_que_admite_lacuna_guarda_a_pergunta_e_devolve_o_id(client, monkeypatch):
    consultor(monkeypatch, LACUNA)

    r = client.post("/chat", json={"mensagem": "Como precificar para prefeituras?"})

    assert r.status_code == 200
    lacuna_id = r.json()["lacuna_id"]
    assert lacuna_id
    with SessionLocal() as db:
        linha = db.get(Lacuna, lacuna_id)
    assert linha.pergunta == "Como precificar para prefeituras?"
    assert linha.pessoa == "Rafael" and linha.status == "aberta"


def test_chat_com_resposta_da_base_nao_guarda_lacuna(client, monkeypatch):
    consultor(monkeypatch, "Proponha um piloto [INS-2].")

    r = client.post("/chat", json={"mensagem": "Como abrir a reunião?"})

    assert r.json()["lacuna_id"] is None
    with SessionLocal() as db:
        assert db.scalars(select(Lacuna)).first() is None


def test_pergunta_com_dado_pessoal_nao_chega_nem_a_lacuna(client, monkeypatch):
    consultor(monkeypatch, LACUNA)
    r = client.post("/chat", json={"mensagem": "ligue para ana@hotelx.com.br sobre preço"})
    assert r.status_code == 422
    with SessionLocal() as db:
        assert db.scalars(select(Lacuna)).first() is None


def test_falha_ao_guardar_nao_derruba_o_chat(client, monkeypatch):
    consultor(monkeypatch, LACUNA)
    monkeypatch.setattr(lacunas, "registrar", lambda *a, **k: None)
    r = client.post("/chat", json={"mensagem": "Como precificar para prefeituras?"})
    assert r.status_code == 200 and r.json()["lacuna_id"] is None


def test_registrar_nao_levanta_se_o_banco_falha(monkeypatch):
    from sqlalchemy.exc import OperationalError

    class DbQuebrado:
        def add(self, _):
            pass

        def commit(self):
            raise OperationalError("x", {}, Exception("banco fora"))

        def rollback(self):
            self.voltou = True

    db = DbQuebrado()
    assert lacunas.registrar(db, "preço hotelaria negociar", "Ana") is None
    assert db.voltou


# --- a lista -----------------------------------------------------------------------------------

def perguntar(client, monkeypatch, texto):
    consultor(monkeypatch, LACUNA)
    return client.post("/chat", json={"mensagem": texto}).json()["lacuna_id"]


def test_lista_junta_as_parecidas_e_ordena_pelas_mais_repetidas(client, monkeypatch):
    primeira = perguntar(client, monkeypatch, "Como negociar preço com hotelaria?")
    perguntar(client, monkeypatch, "hotelaria preço negociar como")
    perguntar(client, monkeypatch, "Qual o ticket médio de varejo?")
    mais_recente_do_grupo = perguntar(client, monkeypatch, "Negociar preço, hotelaria?")

    itens = client.get("/lacunas").json()["itens"]

    assert [i["vezes"] for i in itens] == [3, 1]
    assert itens[0]["id"] == primeira  # o id é o da mais antiga do grupo
    assert itens[0]["pergunta"] == "Negociar preço, hotelaria?"  # o texto é o da mais recente
    assert itens[0]["status"] == "aberta" and itens[0]["pessoas"] == 1
    assert mais_recente_do_grupo > primeira


def test_resolver_fecha_o_grupo_inteiro(client, monkeypatch):
    a = perguntar(client, monkeypatch, "Como negociar preço com hotelaria?")
    perguntar(client, monkeypatch, "hotelaria preço negociar como")

    assert client.post(f"/lacunas/{a}/resolver").status_code == 204

    assert client.get("/lacunas").json()["itens"] == []
    resolvidas = client.get("/lacunas", params={"status": "resolvida"}).json()["itens"]
    assert len(resolvidas) == 1 and resolvidas[0]["vezes"] == 2
    assert client.post(f"/lacunas/{a}/resolver").status_code == 204  # repetir não quebra


def test_resolver_lacuna_que_nao_existe_e_404(client):
    assert client.post("/lacunas/999999/resolver").status_code == 404


def test_filtro_invalido_da_lista_vira_422(client):
    assert client.get("/lacunas", params={"status": "qualquer"}).status_code == 422
    assert client.get("/lacunas", params={"limite": 3}).status_code == 422


# --- criar o item a partir da lacuna fecha o ciclo --------------------------------------------------------

def novo(**campos):
    return {"titulo": f"Preço no setor público {uuid.uuid4().hex[:8]}", "tipo": "aprendizado", "secao": "proposta",
            "descricao": "Pregão exige proposta formal."} | campos


def test_item_criado_com_lacuna_id_resolve_a_lacuna(client, monkeypatch):
    lacuna_id = perguntar(client, monkeypatch, "Como precificar para prefeituras?")

    r = client.post("/insights", json=novo(lacuna_id=lacuna_id))

    assert r.status_code == 201
    assert client.get("/lacunas").json()["itens"] == []
    with SessionLocal() as db:
        linha = db.get(Lacuna, lacuna_id)
    assert linha.status == "resolvida" and linha.resolvida_por_insight_id == r.json()["id"]
    assert linha.resolvida_em is not None


def test_lacuna_id_que_nao_existe_barra_e_nao_grava(client):
    corpo = novo(lacuna_id=999999)
    r = client.post("/insights", json=corpo)
    assert r.status_code == 422 and "lacuna" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(Insight.id).where(Insight.titulo == corpo["titulo"])) is None


# --- POST /chat/registrar ------------------------------------------------------------------------------

def test_registrar_do_chat_monta_o_relato_com_as_ultimas_falas_da_pessoa(client, monkeypatch):
    falso = usar(monkeypatch, CuradorFalso(proposta()))
    historico = [
        {"role": "user", "text": "primeira fala"}, {"role": "model", "text": "resposta do modelo"},
        {"role": "user", "text": "segunda fala"}, {"role": "user", "text": "terceira"},
        {"role": "user", "text": "quarta"},
    ]

    r = client.post("/chat/registrar", json={"historico": historico})

    assert r.status_code == 200 and r.json()["insight"]["autor"] == "Rafael"
    relato = falso.curar_chamadas[0]["texto"]
    assert "segunda fala" in relato and "terceira" in relato and "quarta" in relato
    assert "primeira fala" not in relato and "resposta do modelo" not in relato  # só as 3 últimas, só as da pessoa


def test_registrar_do_chat_usa_o_texto_quando_vem(client, monkeypatch):
    falso = usar(monkeypatch, CuradorFalso(proposta()))
    client.post("/chat/registrar", json={"texto": "abri com diagnóstico", "historico": [{"role": "user", "text": "x"}]})
    assert falso.curar_chamadas[0]["texto"] == "abri com diagnóstico"


def test_registrar_do_chat_nao_grava_nada(client, monkeypatch):
    usar(monkeypatch, CuradorFalso(proposta()))
    with SessionLocal() as db:
        antes = len(db.scalars(select(Insight.id)).all())
    client.post("/chat/registrar", json={"texto": "abri com diagnóstico"})
    with SessionLocal() as db:
        assert len(db.scalars(select(Insight.id)).all()) == antes


@pytest.mark.parametrize("corpo", [{}, {"historico": [{"role": "model", "text": "só o modelo falou"}]},
                                   {"historico": [{"role": "user", "text": "   "}]}])
def test_registrar_do_chat_sem_relato_vira_422(client, monkeypatch, corpo):
    usar(monkeypatch, CuradorFalso(proposta()))
    assert client.post("/chat/registrar", json=corpo).status_code == 422


def test_registrar_do_chat_barra_dado_pessoal_antes_do_modelo(client, monkeypatch):
    falso = usar(monkeypatch, CuradorFalso(proposta()))
    r = client.post("/chat/registrar", json={"texto": "o contato é ana@hotelx.com.br e fechou"})
    assert r.status_code == 422 and falso.curar_chamadas == []


def test_registrar_do_chat_com_lacuna_inexistente_e_404(client, monkeypatch):
    usar(monkeypatch, CuradorFalso(proposta()))
    assert client.post("/chat/registrar", json={"texto": "x", "lacuna_id": 999999}).status_code == 404


def test_registrar_do_chat_erro_do_modelo_vira_502(client, monkeypatch):
    def cai(*a, **k):
        raise llm.ErroLLM("fora do formato")

    monkeypatch.setattr(llm, "curar", cai)
    assert client.post("/chat/registrar", json={"texto": "abri com diagnóstico"}).status_code == 502
