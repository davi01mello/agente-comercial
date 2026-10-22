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


def test_item_unico_nao_apaga_o_aviso_de_hipotese():
    """O "(só um item da base)" substitui o "(um caso só)", nunca o "(ainda não validado)": a pessoa precisa saber
    que a hipótese não foi testada."""
    prompt = _consultor()

    assert 'diga "(só um item da base)" no lugar de "(um caso só)"' in prompt
    assert 'mantenha "(ainda não validado)" junto' in prompt
    assert "sem repetir o aviso do item" not in prompt  # a versão que apagava o aviso da hipótese


def test_proximo_passo_vem_antes_das_perguntas_de_volta():
    """Sem a ordem, "termine com Próximo passo" e "pergunte qual é o caminho" disputam o fim da resposta (P26)."""
    prompt = _consultor()

    assert 'o "Próximo passo" vem antes das perguntas e serve para qualquer dos caminhos' in prompt


def test_case_regra_e_template_sao_destrinchados():
    prompt = _consultor()

    assert "Case e orientação destrinchados" in prompt
    assert "o que foi feito" in prompt
    assert "não a preencha" in prompt


def test_regras_da_v2_1_depois_das_notas_do_rafael():
    prompt = _consultor()

    for regra in ["Use o termo exato do item", "não \"piloto\"",  # Discovery é o serviço inicial do CITi
                  "Cada tópico da resposta sai de um item citado",
                  "UMA vez por item na resposta",
                  "é um relato, não um pedido de roteiro",
                  "Quando isso aparecer numa conta sua, registra o que aprendeu",
                  "pergunte (até 2 perguntas) como está a conta"]:
        assert regra in prompt, regra


def test_regras_da_v2_2_contra_os_deslizes_de_o_que():
    prompt = _consultor()

    for regra in ["não faça conta com ele", "Não invente frequência", "não vira regra",
                  "Traga só os itens que a pergunta toca", "o que ele tem em comum com o tema"]:
        assert regra in prompt, regra


def test_na_lacuna_a_pista_vem_antes_das_perguntas_sobre_a_conta():
    prompt = _consultor()

    assert prompt.index("o mais perto é de") < prompt.index("registra o que aprendeu") < prompt.index(
        "como está a conta")


def test_caso_contado_registra_antes_do_proximo_passo():
    prompt = _consultor()

    assert prompt.index("Sugira registrar") < prompt.index('o "Próximo passo:" (depois do convite a registrar)')


def test_a_pergunta_sobre_a_conta_na_lacuna_nao_repete_a_frase():
    assert 'Não repita "A base não cobre" nessa pergunta' in _consultor()


def test_o_prompt_nao_ensina_emoji():
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", llm.carregar_prompt("consultor"))


def test_o_curador_pergunta_na_voz_do_colega_sem_mudar_as_regras():
    prompt = " ".join(llm.carregar_prompt("curador").split())

    assert "colega sênior do comercial do CITi" in prompt
    assert "A voz muda só o jeito de perguntar" in prompt
