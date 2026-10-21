"""A persona do consultor (ADR-009) no prompt: as frases que o código e os testes de ouro dependem. Sem Gemini.

O tom não dá para testar por código (fica na nota humana do golden set). Aqui se garante que a persona não levou
embora o que o sistema usa: a frase da lacuna, a citação por colchete e a regra de ouro.
"""
import re

from app import lacunas, llm


def _sem_acento(texto: str) -> str:
    return texto.translate(str.maketrans("áâãàéêíóôõúç", "aaaaeeiooouc")).lower()


def _consultor() -> str:
    return " ".join(llm.carregar_prompt("consultor").split())  # junta as quebras de linha do texto


def test_a_frase_da_lacuna_continua_literal_no_prompt():
    assert "A base não cobre <tema>." in _consultor()
    assert lacunas.FRASE in _sem_acento(_consultor())


def test_pergunta_vaga_nao_usa_a_frase_da_lacuna():
    assert 'Não diga "A base não cobre" para uma pergunta vaga' in _consultor()


def test_a_persona_muda_o_como_nunca_o_que():
    prompt = _consultor()

    assert "colega sênior do comercial do CITi" in prompt
    assert "muda COMO você responde, nunca O QUE" in prompt
    assert "nunca como quem viveu o caso" in prompt


def test_citacao_um_colchete_por_item_continua():
    assert 'nunca "[INS-2, INS-7]"' in _consultor()


def test_regras_de_formato_da_persona():
    prompt = _consultor()

    for regra in ["No máximo 2 perguntas", "Sem emojis", "Próximo passo:", "Esse caso vale registrar",
                  "(um caso só)", "(ainda não validado)", "(só um item da base)", "vale como pista, não como regra"]:
        assert regra in prompt, regra


def test_case_regra_e_template_sao_destrinchados():
    prompt = _consultor()

    assert "Case e orientação destrinchados" in prompt
    assert "o que foi feito" in prompt
    assert "não a preencha" in prompt


def test_o_prompt_nao_ensina_emoji():
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", llm.carregar_prompt("consultor"))


def test_o_curador_pergunta_na_voz_do_colega_sem_mudar_as_regras():
    prompt = " ".join(llm.carregar_prompt("curador").split())

    assert "colega sênior do comercial do CITi" in prompt
    assert "A voz muda só o jeito de perguntar" in prompt
