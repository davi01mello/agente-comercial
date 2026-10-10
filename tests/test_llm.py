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

# --- curador: JSON estruturado ---------------------------------------------------------------

PROPOSTA_OK = (
    '{"insight": {"titulo": "Abrir com diagnóstico", "tipo": "aprendizado", "secao": "reuniao_diagnostico",'
    ' "descricao": "O cliente se abriu.", "evidencia": 2}, "perguntas": [], "avisos": []}'
)


def test_curar_json_valido(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso(PROPOSTA_OK))

    proposta = llm.curar("abri com diagnóstico", [], turno=1, ultimo_turno=False)

    assert proposta.insight.tipo == "aprendizado"
    chamada = cliente.chamadas[0]
    assert chamada["config"].response_schema is llm.PropostaLLM
    assert chamada["config"].temperature == 0


def test_curar_embrulha_o_texto_do_usuario_como_dado(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso(PROPOSTA_OK))
    conversa = [{"role": "user", "text": "texto 1"}, {"role": "model", "text": "Qual foi o resultado?"}]

    llm.curar("caiu 30%", conversa, turno=2, ultimo_turno=False)

    textos = [c.parts[0].text for c in cliente.chamadas[0]["contents"]]
    assert textos[0] == "<texto_do_usuario>\ntexto 1\n</texto_do_usuario>"
    assert textos[1] == "Qual foi o resultado?"  # a fala do modelo não é embrulhada
    assert textos[2].startswith("<texto_do_usuario>\ncaiu 30%\n</texto_do_usuario>")


def test_curar_no_ultimo_turno_avisa_o_modelo(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso(PROPOSTA_OK))

    llm.curar("x", [], turno=3, ultimo_turno=True)

    assert "ÚLTIMO. Não faça perguntas" in cliente.chamadas[0]["contents"][-1].parts[0].text


@pytest.mark.parametrize("ruim", [
    "isso não é json",
    '{"insight": {"titulo": "x"}, "perguntas": [], "avisos": []}',  # faltam campos
    PROPOSTA_OK.replace('"aprendizado"', '"dica"'),  # tipo fora da lista
])
def test_curar_json_invalido_tenta_de_novo_mostrando_o_erro(monkeypatch, esperas, ruim):
    cliente = usar(monkeypatch, ClienteFalso(ruim, PROPOSTA_OK))

    proposta = llm.curar("x", [], turno=1, ultimo_turno=False)

    assert proposta.insight.titulo == "Abrir com diagnóstico"
    assert len(cliente.chamadas) == 2
    segunda = cliente.chamadas[1]["contents"]
    assert segunda[-2].role == "model" and segunda[-2].parts[0].text == ruim  # o modelo vê o que mandou
    assert "não seguiu o schema" in segunda[-1].parts[0].text  # e o que estava errado


def test_curar_json_invalido_duas_vezes_vira_erro_amigavel(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso("lixo", "lixo de novo"))

    with pytest.raises(llm.ErroLLM, match="fora do formato duas vezes"):
        llm.curar("x", [], turno=1, ultimo_turno=False)
    assert len(cliente.chamadas) == 2


def test_curar_usa_o_modelo_do_curador_e_o_retry(monkeypatch, esperas):
    monkeypatch.setattr(llm.settings, "model_curador", "modelo-do-curador")
    cliente = usar(monkeypatch, ClienteFalso(erro_api(503), PROPOSTA_OK))

    llm.curar("x", [], turno=1, ultimo_turno=False)

    assert [c["model"] for c in cliente.chamadas] == ["modelo-do-curador"] * 2
    assert esperas == [1.0]


def test_relacionar(monkeypatch, esperas):
    cliente = usar(monkeypatch, ClienteFalso('{"relacoes": [{"id": 3, "tipo": "reforca"}]}'))

    resposta = llm.relacionar("item novo", "[INS-3] outro | aprendizado | evid 2")

    assert [(r.id, r.tipo) for r in resposta.relacoes] == [(3, "reforca")]
    pedido = cliente.chamadas[0]["contents"][0].parts[0].text
    assert "<itens_existentes>\n[INS-3] outro" in pedido