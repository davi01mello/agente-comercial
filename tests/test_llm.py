"""Testes do app/llm.py sem chamar a API: o cliente do Gemini é trocado por um cliente falso.

Assim testamos o que é NOSSO (montagem do histórico, tradução de erros, retry) sem gastar cota
e sem depender de internet.
"""
import httpx
import pytest
from google.genai import errors

from app import llm


class RespostaFalsa:
    def __init__(self, text):
        self.text = text


class ClienteFalso:
    """Imita genai.Client. `roteiro` diz o que cada chamada devolve: um texto, ou uma exceção a levantar."""

    def __init__(self, *roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = []
        self.models = self  # o código chama client.models.generate_content(...)

    def generate_content(self, **kwargs):
        self.chamadas.append(kwargs)
        proximo = self.roteiro.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return RespostaFalsa(proximo)


def erro_api(codigo, mensagem="erro"):
    """Cria o mesmo tipo de erro que o SDK levanta (ClientError para 4xx, ServerError para 5xx)."""
    classe = errors.ClientError if codigo < 500 else errors.ServerError
    return classe(codigo, {"error": {"code": codigo, "message": mensagem, "status": "X"}})


@pytest.fixture
def esperas(monkeypatch):
    """Chave de teste + troca o sleep por uma lista que só anota quanto tempo esperaria."""
    anotadas = []
    monkeypatch.setattr(llm.settings, "gemini_api_key", "chave-de-teste")
    monkeypatch.setattr(llm, "_dormir", anotadas.append)
    return anotadas


def usar(monkeypatch, cliente):
    monkeypatch.setattr(llm, "_client", lambda: cliente)
    return cliente


# --- caminho feliz e histórico -------------------------------------------------------------

def test_resposta_ok(monkeypatch, esperas):
    usar(monkeypatch, ClienteFalso("Proponha um piloto [EX-02]."))
    assert llm.consultar("oi", []) == "Proponha um piloto [EX-02]."
    assert esperas == []


def test_historico_vira_contents_na_ordem(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso("ok"))
    historico = [{"role": "user", "text": "pergunta 1"}, {"role": "model", "text": "resposta 1"}]

    llm.consultar("pergunta 2", historico)

    contents = cliente.chamadas[0]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [c.parts[0].text for c in contents] == ["pergunta 1", "resposta 1", "pergunta 2"]


# --- erros traduzidos ----------------------------------------------------------------------

@pytest.mark.parametrize("erro, trecho", [
    (erro_api(401), "chave do Gemini é inválida"),
    (erro_api(400, "API key not valid. Please pass a valid API key."), "chave do Gemini é inválida"),
    (erro_api(404), "não foi encontrado"),
    (erro_api(500), "devolveu um erro"),
])
def test_erros_que_nao_repetem(monkeypatch, esperas, erro, trecho):
    cliente = usar(monkeypatch, ClienteFalso(erro))
    with pytest.raises(llm.ErroLLM, match=trecho):
        llm.consultar("oi", [])
    assert len(cliente.chamadas) == 1  # não insistiu
    assert esperas == []


@pytest.mark.parametrize("erro, trecho", [
    (erro_api(429), "Limite de uso"),
    (erro_api(503), "sobrecarregado"),
    (httpx.ConnectTimeout("demorou"), "sem internet ou demorou"),
])
def test_erros_temporarios_tentam_3_vezes(monkeypatch, esperas, erro, trecho):
    cliente = usar(monkeypatch, ClienteFalso(erro, erro, erro))
    with pytest.raises(llm.ErroLLM, match=trecho):
        llm.consultar("oi", [])
    assert len(cliente.chamadas) == 3
    assert esperas == [1.0, 2.0]  # backoff exponencial


def test_retry_recupera_depois_de_503(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso(erro_api(503), erro_api(503), "voltou"))
    assert llm.consultar("oi", []) == "voltou"
    assert len(cliente.chamadas) == 3
    assert esperas == [1.0, 2.0]


def test_resposta_sem_texto(monkeypatch, esperas):
    usar(monkeypatch, ClienteFalso(None))
    with pytest.raises(llm.ErroLLM, match="não devolveu texto"):
        llm.consultar("oi", [])


def test_chave_vazia_nem_chama_a_api(monkeypatch, esperas):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")
    cliente = usar(monkeypatch, ClienteFalso("não deveria chegar aqui"))
    with pytest.raises(llm.ErroLLM, match="não está configurada"):
        llm.consultar("oi", [])
    assert cliente.chamadas == []