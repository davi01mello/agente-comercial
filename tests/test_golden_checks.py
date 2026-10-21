"""Testes dos checks do golden set (tests/golden/checks.py), sem o Gemini: respostas escritas à mão."""
import json
from pathlib import Path

import pytest

from tests.golden.checks import falhas_de, palavras, perguntas

IDS = {2: "case", 3: "objecao", 7: "regra", 18: "aprendizado"}  # {id: tipo}, como a base do golden
COBERTA = {"coberta": True, "esperados": [7]}
SEM_COBERTURA = {"coberta": False, "esperados": []}
BOA = "Proponha um piloto em uma unidade antes de expandir [INS-7]."


def etiquetas(falhas: list[str]) -> list[str]:
    return [f.split("]")[0] + "]" for f in falhas]


# --- as regras de antes (ADR-004) ---------------------------------------------------------------

def test_resposta_boa_passa():
    assert falhas_de(COBERTA, BOA, IDS) == []


def test_id_inventado_mesmo_dentro_de_grupo():
    falhas = falhas_de(COBERTA, "Piloto [INS-7] e [INS-2, INS-99].", IDS)
    assert any("[99]" in f for f in falhas)
    assert any("agrupada" in f for f in falhas)


def test_coberta_sem_nenhum_esperado():
    assert falhas_de(COBERTA, "Quebre por fase [INS-3].", IDS) == ["[regra] não citou nenhum dos esperados [7]"]


def test_lacuna_precisa_da_frase_literal():
    assert falhas_de(SEM_COBERTURA, "A base não cobre setor público.", IDS) == []
    assert falhas_de(SEM_COBERTURA, "Não temos nada sobre setor público.", IDS) == [
        "[regra] a base não cobre a pergunta, mas a resposta não admitiu a lacuna"]


# --- persona (ADR-009) --------------------------------------------------------------------------

@pytest.mark.parametrize("emoji", ["✅", "🚀", "⭐", "👍"])
def test_emoji_reprova(emoji):
    assert falhas_de(COBERTA, f"{BOA} {emoji}", IDS) == ["[persona] tem emoji"]


def test_seta_e_marcador_nao_sao_emoji():
    assert falhas_de(COBERTA, f"- {BOA}\n• Próximo passo → marcar a reunião.", IDS) == []


def test_mais_de_duas_perguntas_reprova_e_livre_libera():
    resposta = f"{BOA} Qual o segmento? Em que etapa? Quem decide?"
    assert falhas_de(COBERTA, resposta, IDS) == ["[persona] 3 perguntas (máximo 2)"]
    assert falhas_de(COBERTA | {"livre": ["perguntas"]}, resposta, IDS) == []


def test_teto_de_palavras_nao_conta_os_ids():
    assert palavras("Piloto antes [INS-7] [INS-18] [DOC-3].") == 2


def test_teto_sem_detalhe_e_160():
    caso = {"coberta": True, "esperados": [3]}
    curta, longa = "Volte ao custo do problema [INS-3]." + " palavra" * 150, "Volte [INS-3]." + " palavra" * 160
    assert falhas_de(caso, curta, IDS) == []
    assert palavras(longa) == 161
    assert falhas_de(caso, longa, IDS) == ["[persona] 161 palavras (teto 160)"]
    assert falhas_de(caso | {"livre": ["teto"]}, longa, IDS) == []


def test_teto_sobe_para_260_quando_cita_case_regra_ou_template():
    assert falhas_de(COBERTA, BOA + " palavra" * 200, IDS) == []  # cita o INS-7, uma regra
    longa = BOA + " palavra" * 260
    assert palavras(longa) == 269  # as 9 palavras da BOA + 260
    assert falhas_de(COBERTA, longa, IDS) == ["[persona] 269 palavras (teto 260)"]


def test_deve_citar_exige_todos():
    caso = COBERTA | {"deve_citar": [7, 18]}
    assert falhas_de(caso, BOA, IDS) == ["[persona] não citou [18]"]
    assert falhas_de(caso, f"{BOA} Mandar só por e-mail teve pouca resposta [INS-18].", IDS) == []


def test_pergunta_vaga_precisa_perguntar_e_nao_pode_virar_lacuna():
    caso = COBERTA | {"pergunta_de_volta": True}
    assert falhas_de(caso, f"{BOA} Qual o segmento do cliente?", IDS) == []
    assert falhas_de(caso, BOA, IDS) == ["[persona] pergunta vaga, mas a resposta não perguntou nada de volta"]
    assert "registraria lacuna falsa" in falhas_de(caso, f"A base não cobre isso. {BOA} Qual o segmento?", IDS)[0]


def test_registrar_aceita_as_formas_do_verbo():
    caso = SEM_COBERTURA | {"registrar": True}
    assert falhas_de(caso, "A base não cobre setor público. Quando acontecer, registra o que aprendeu.", IDS) == []
    assert falhas_de(caso, "A base não cobre setor público. Vale registrar depois.", IDS) == []
    assert falhas_de(caso, "A base não cobre setor público.", IDS) == [
        "[persona] não sugeriu registrar o aprendizado"]


def test_proximo_passo_com_ou_sem_acento():
    caso = COBERTA | {"proximo_passo": True}
    assert falhas_de(caso, f"{BOA}\n\n**Próximo passo:** marcar a reunião.", IDS) == []
    assert falhas_de(caso, f"{BOA} Proximo passo: marcar.", IDS) == []
    assert falhas_de(caso, BOA, IDS) == ["[persona] não fechou com 'Próximo passo'"]


def test_contagem_de_perguntas():
    assert perguntas("Qual? E o prazo?") == 2


# --- as perguntas do golden ----------------------------------------------------------------------

def test_casos_do_golden_bem_formados():
    """Um campo com nome errado ("proximo_paso") faria o check sumir em silêncio na rodada que gasta cota."""
    pasta = Path(__file__).parent / "golden"
    base = {i["id"] for i in json.loads((pasta / "base.json").read_text(encoding="utf-8"))}
    casos = json.loads((pasta / "perguntas.json").read_text(encoding="utf-8"))
    campos = {"n", "pergunta", "testa", "coberta", "esperados", "historico", "deve_citar", "pergunta_de_volta",
              "registrar", "proximo_passo", "livre"}

    assert [c["n"] for c in casos] == list(range(1, len(casos) + 1))
    for c in casos:
        assert set(c) <= campos, f"P{c['n']:02d}: campo desconhecido {set(c) - campos}"
        assert set(c["esperados"]) | set(c.get("deve_citar", [])) <= base, f"P{c['n']:02d}: id fora da base"
        assert c["coberta"] == bool(c["esperados"]), f"P{c['n']:02d}: coberta e esperados não batem"
        assert set(c.get("livre", [])) <= {"teto", "perguntas"}
        for h in c.get("historico", []):
            assert set(h) == {"role", "text"} and h["role"] in {"user", "model"}
        if c.get("historico"):
            assert c["historico"][0]["role"] == "user" and c["historico"][-1]["role"] == "model"
