"""Testes da base do consultor (app/knowledge.py): quais itens entram, em que formato e em que ordem."""
import logging
import uuid
from datetime import date, datetime

import pytest

from app import knowledge
from app.db import SessionLocal
from app.models import Insight


def item(id_: int, **campos) -> Insight:
    """Um Insight em memória (sem banco), com o mínimo para formatar. Os testes mudam só o que importa."""
    padrao = {
        "titulo": f"Item {id_}",
        "tipo": "aprendizado",
        "secao": "reuniao_diagnostico",
        "descricao": "Abrir com perguntas fez o cliente contar os problemas.",
        "evidencia": 2,
        "status": "validado",
        "autor": "Rafael",
        "criado_em": datetime(2026, 10, 1, 12, 0),
    }
    return Insight(id=id_, **(padrao | campos))


# --- quais itens entram -------------------------------------------------------------------------

def test_so_validado_e_consolidado_entram():
    marca = uuid.uuid4().hex[:8]
    status = ["validado", "consolidado", "proposto", "historico_a_validar", "obsoleto"]
    with SessionLocal() as db:
        for s in status:
            db.add(Insight(titulo=f"{s} {marca}", tipo="aprendizado", secao="proposta", descricao="x",
                           evidencia=2, status=s, autor="Rafael"))
        db.commit()

        base = knowledge.montar_base(db)

    assert f"validado {marca}" in base and f"consolidado {marca}" in base
    for fora in ["proposto", "historico_a_validar", "obsoleto"]:
        assert f"{fora} {marca}" not in base


def test_base_vazia_avisa_o_modelo():
    assert knowledge.compor_base([]) == knowledge.BASE_VAZIA
    assert "não cobre" in knowledge.BASE_VAZIA


# --- formato: uma linha por item ----------------------------------------------------------------

def test_formato_enxuto_de_uma_linha():
    linha = knowledge.formatar(item(
        12, titulo="Abrir com diagnóstico", tipo="aprendizado", secao="reuniao_diagnostico", segmento="hotelaria",
        evidencia=2, descricao="Perguntas antes da solução.", resultado="Pediu proposta.",
        o_que_foi_feito="20 minutos só de perguntas.",  # aprendizado não leva o "feito"
    ))

    assert linha == (
        "[INS-12] Abrir com diagnóstico | aprendizado | reuniao_diagnostico | hotelaria | evid 2 | "
        "Perguntas antes da solução. | Pediu proposta."
    )


def test_case_leva_o_que_foi_feito_antes_do_resultado():
    linha = knowledge.formatar(item(
        12, titulo="Piloto antes de expandir", tipo="case", secao="proposta", segmento="hotelaria", evidencia=4,
        descricao="Piloto em uma unidade.", o_que_foi_feito="Check-in digital em 1 hotel por 30 dias.",
        resultado="Check-in de 9 para 4 minutos.",
    ))

    assert linha == (
        "[INS-12] Piloto antes de expandir | case | proposta | hotelaria | evid 4 | Piloto em uma unidade. | "
        "feito: Check-in digital em 1 hotel por 30 dias. | Check-in de 9 para 4 minutos."
    )


@pytest.mark.parametrize("tipo", sorted(knowledge.TIPOS_COM_DETALHE))
def test_tipos_com_detalhe_levam_a_descricao_inteira(tipo):
    descricao = "palavra " * 40  # 320 caracteres: o resumo cortaria

    linha = knowledge.formatar(item(9, tipo=tipo, descricao=descricao))

    assert linha.split(" | ")[5] == descricao.strip()
    assert "| feito: não registrado |" in linha  # sem o campo, fica explícito, como o segmento


@pytest.mark.parametrize("tipo", ["aprendizado", "hipotese", "objecao", "perfil_segmento"])
def test_outros_tipos_continuam_com_resumo_e_sem_feito(tipo):
    linha = knowledge.formatar(item(9, tipo=tipo, descricao="palavra " * 40, o_que_foi_feito="algo"))

    assert len(linha.split(" | ")[5]) <= knowledge.TAMANHO_DO_RESUMO + 1
    assert "feito:" not in linha


def test_detalhe_tem_teto_para_texto_colado_enorme():
    linha = knowledge.formatar(item(9, tipo="case", descricao="palavra " * 500, o_que_foi_feito="passo " * 500))

    descricao, feito = linha.split(" | ")[5:7]
    assert len(descricao) <= knowledge.TAMANHO_DO_DETALHE + 1 and descricao.endswith("palavra…")
    assert len(feito) <= len("feito: ") + knowledge.TAMANHO_DO_DETALHE + 1


def test_sem_segmento_e_sem_resultado_ficam_explicitos():
    linha = knowledge.formatar(item(3))

    assert "| sem segmento |" in linha
    assert linha.endswith("| sem resultado registrado")


def test_autor_e_contexto_do_cliente_nao_entram():
    """O contexto do cliente pode ter dado pessoal, e o consultor não precisa de nenhum dos dois."""
    linha = knowledge.formatar(item(4, autor="Fulano de Tal", contexto_cliente="diretor da rede, fala com Ana"))

    assert "Fulano" not in linha and "Ana" not in linha


def test_resumo_corta_a_descricao_sem_partir_palavra():
    descricao = "palavra " * 40  # 320 caracteres

    resumo = knowledge.formatar(item(5, descricao=descricao)).split(" | ")[5]

    assert len(resumo) <= knowledge.TAMANHO_DO_RESUMO + 1  # + o "…"
    assert resumo.endswith("palavra…")


def test_descricao_curta_vai_inteira():
    assert "| Abrir com perguntas fez o cliente contar os problemas. |" in knowledge.formatar(item(6))


def test_quebra_de_linha_e_barra_vertical_nao_desmontam_o_formato():
    linha = knowledge.formatar(item(7, titulo="A | B", descricao="linha 1\nlinha 2", resultado="x\n\ny"))

    assert "\n" not in linha
    assert linha.count(" | ") == 6  # 7 campos
    assert linha.startswith("[INS-7] A / B |")


def test_quebra_de_linha_no_que_foi_feito_nao_desmonta_o_formato():
    linha = knowledge.formatar(item(8, tipo="regra", evidencia=3, o_que_foi_feito="passo 1 | passo 2\npasso 3"))

    assert "\n" not in linha
    assert linha.count(" | ") == 7  # 8 campos: o "feito" a mais
    assert "| feito: passo 1 / passo 2 passo 3 |" in linha


# --- ordem e tamanho ----------------------------------------------------------------------------

def test_ordem_maior_evidencia_e_depois_mais_recente():
    itens = [
        item(1, evidencia=2, data_evento=date(2026, 1, 10)),
        item(2, evidencia=2, data_evento=None),  # sem data do evento: vale a do registro (2026-10-01)
        item(3, evidencia=4, data_evento=date(2025, 5, 1)),
        item(4, evidencia=1, data_evento=date(2026, 9, 1)),
    ]

    base = knowledge.compor_base(itens)

    assert [linha.split("]")[0] for linha in base.splitlines()] == ["[INS-3", "[INS-2", "[INS-1", "[INS-4"]


def test_acima_do_limite_avisa_no_log_e_nao_corta(monkeypatch, caplog):
    monkeypatch.setattr(knowledge, "ITENS_ANTES_DO_RAG", 2)

    with caplog.at_level(logging.WARNING, logger="app.knowledge"):
        base = knowledge.compor_base([item(1), item(2), item(3)])

    assert len(base.splitlines()) == 3  # a base vai inteira: RAG só na T8
    assert "3 itens (mais de 2)" in caplog.text and "RAG" in caplog.text


@pytest.mark.parametrize("quantos", [0, 2])
def test_no_limite_ou_abaixo_nao_avisa(monkeypatch, caplog, quantos):
    monkeypatch.setattr(knowledge, "ITENS_ANTES_DO_RAG", 2)

    with caplog.at_level(logging.WARNING, logger="app.knowledge"):
        knowledge.compor_base([item(i) for i in range(1, quantos + 1)])

    assert caplog.records == []
