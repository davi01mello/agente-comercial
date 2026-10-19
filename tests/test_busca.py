"""Busca nos documentos do Drive (app/busca.py) e o texto que o consultor recebe (knowledge.montar_documentos), com
documentos INVENTADOS gravados direto no banco de teste. Sem rede e sem modelo."""
from datetime import datetime

import pytest

from app import busca, knowledge, llm
from app.busca import Achado
from app.db import SessionLocal
from app.models import Fonte, TrechoDocumento
from tests.notion_falso import limpar_banco_da_importacao

AGORA = datetime(2026, 10, 15, 12, 0)


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        limpar_banco_da_importacao(sessao)
        yield sessao
        limpar_banco_da_importacao(sessao)


def documento(db, titulo: str, *pedacos: str, categoria: str | None = "Resumo Comercial", status: str = "importada",
              importado_em: datetime = AGORA) -> Fonte:
    f = Fonte(origem="drive", id_externo=f"id-{titulo}", titulo=titulo, url=f"https://drive/{titulo}",
              categoria=categoria, hash_conteudo=titulo, editado_em=AGORA, importado_em=importado_em, status=status)
    db.add(f)
    db.flush()
    db.add_all(TrechoDocumento(fonte_id=f.id, ordem=i, texto=t) for i, t in enumerate(pedacos, start=1))
    db.commit()
    return f


def test_palavras_sem_acento_sem_maiuscula_e_sem_palavras_vazias():
    assert busca.palavras("Negociação: o que fazer com a objeção de preço?") == ["negociacao", "objecao", "preco"]


def test_acha_pelo_conteudo_ignorando_acento(db):
    guia = documento(db, "Guia", "Quando pedem desconto, peço pagamento em uma parcela só.")
    documento(db, "Outro", "O briefing da concessionária descreve as lojas e a frota.")

    [achado] = busca.buscar(db, "como respondo a pedido de DESCONTO?")

    assert (achado.fonte_id, achado.titulo, achado.categoria) == (guia.id, "Guia", "Resumo Comercial")
    assert achado.url == "https://drive/Guia"
    assert achado.textos == ("Quando pedem desconto, peço pagamento em uma parcela só.",)


def test_o_titulo_e_a_pasta_tambem_contam(db):
    briefing = documento(db, "Briefing Italiana", "Concessionária Fiat e Jeep em Recife.", categoria="Resumo Comercial")
    documento(db, "Guia", "Texto qualquer sobre a rotina de prospecção da equipe.")

    assert [a.fonte_id for a in busca.buscar(db, "briefing italiana")] == [briefing.id]


def test_nada_em_comum_devolve_vazio(db):
    documento(db, "Guia", "Texto sobre prospecção por telefone.")

    assert busca.buscar(db, "orçamento de energia solar") == []
    assert busca.buscar(db, "o que é a de?") == []  # só palavras vazias
    assert busca.buscar(db, "") == []


def test_sem_nenhum_documento(db):
    assert busca.buscar(db, "qualquer coisa") == []


def test_o_mais_parecido_vem_primeiro_e_agrupa_os_pedacos_do_mesmo_documento(db):
    fraco = documento(db, "Fraco", "Uma menção à cadência no meio de um texto longo sobre outros assuntos da rotina "
                                   "comercial, como reuniões, propostas e acompanhamento de clientes.")
    forte = documento(db, "Forte", "Cadência de ligações: a cadência de ligações precisa ser concluída antes de "
                                   "desistir do lead.",
                      "Sem relação nenhuma, só um pedaço de enchimento do documento.",
                      "Cadência de ligações: cada lead recebe seis tentativas de contato.")

    achados = busca.buscar(db, "cadência de ligações")

    assert [a.fonte_id for a in achados] == [forte.id, fraco.id]
    assert len(achados[0].textos) == 2  # os pedaços do documento, na ordem dele
    assert achados[0].textos[0].startswith("Cadência de ligações: a cadência")
    assert len(achados[1].textos) == 1


def test_limites_de_pedacos_por_pergunta_e_por_documento(db, monkeypatch):
    for i in range(4):
        documento(db, f"Doc{i}", *[f"discovery número {i} parte {j}" for j in range(4)])

    achados = busca.buscar(db, "discovery")

    assert sum(len(a.textos) for a in achados) == busca.MAX_PEDACOS == 5
    assert max(len(a.textos) for a in achados) <= busca.MAX_POR_DOCUMENTO == 2


def test_documento_removido_nao_aparece(db):
    removido = documento(db, "Velho", "Texto sobre proposta e discovery.")
    removido.status = "removida"
    db.commit()

    assert busca.buscar(db, "proposta discovery") == []


def test_o_indice_se_refaz_quando_os_pedacos_mudam(db):
    guia = documento(db, "Guia", "Texto sobre prospecção.")
    assert busca.buscar(db, "negociação") == []

    db.add(TrechoDocumento(fonte_id=guia.id, ordem=2, texto="Agora também fala de negociação."))
    db.commit()

    assert [a.fonte_id for a in busca.buscar(db, "negociação")] == [guia.id]


def test_o_indice_se_refaz_quando_o_documento_e_reimportado_com_os_mesmos_ids(db):
    guia = documento(db, "Guia", "Texto antigo sobre prospecção.")
    busca.buscar(db, "prospecção")
    db.query(TrechoDocumento).delete()
    db.add(TrechoDocumento(fonte_id=guia.id, ordem=1, texto="Texto novo sobre fechamento."))
    guia.importado_em = datetime(2026, 10, 16)
    db.commit()

    assert busca.buscar(db, "prospecção") == []
    assert [a.fonte_id for a in busca.buscar(db, "fechamento")] == [guia.id]


def test_a_consulta_junta_as_duas_ultimas_falas_do_usuario():
    historico = [{"role": "user", "text": "primeira"}, {"role": "model", "text": "resposta"},
                 {"role": "user", "text": "segunda"}, {"role": "user", "text": "terceira"}]

    assert busca.consulta_da_conversa("e se for caro?", historico) == "segunda terceira e se for caro?"
    assert busca.consulta_da_conversa("oi", []) == "oi"


# --- o texto que o consultor recebe -----------------------------------------------------------------------------

def test_montar_documentos_marca_o_id_a_pasta_e_embrulha_o_texto_como_dado():
    achados = [Achado(7, "Guia | do novato", "https://drive/7", "Resumo Comercial", ("trecho um", "trecho dois")),
               Achado(9, "Briefing", "https://drive/9", None, ("só um",))]

    texto = knowledge.montar_documentos(achados)

    assert texto == (
        "[DOC-7] Guia / do novato | pasta: Resumo Comercial\n<documento>\ntrecho um\n[…]\ntrecho dois\n</documento>"
        "\n\n[DOC-9] Briefing\n<documento>\nsó um\n</documento>"
    )


def test_montar_documentos_sem_achados_e_vazio():
    assert knowledge.montar_documentos([]) == ""


def test_o_prompt_do_consultor_so_ganha_a_secao_de_documentos_quando_ha_documentos():
    sem = llm._system_consultor("[INS-1] item")
    com = llm._system_consultor("[INS-1] item", "[DOC-7] guia\n<documento>\ntexto\n</documento>")

    assert "# DOCUMENTOS DO DRIVE (AINDA NÃO REVISADOS)\n\n" not in sem
    assert com.startswith(sem) and com.endswith("[DOC-7] guia\n<documento>\ntexto\n</documento>")
    assert "# DOCUMENTOS DO DRIVE (AINDA NÃO REVISADOS)" in com


def test_as_regras_do_doc_estao_no_prompt_do_consultor():
    prompt = llm.carregar_prompt("consultor")

    for regra in ["[DOC-n]", "ainda não revisado", "nunca ordem", "vale a base", "Documento não tem evidência"]:
        assert regra in prompt


def test_as_tags_de_origem_estao_no_prompt_do_curador():
    prompt = llm.carregar_prompt("curador")

    for tag in ["[Opinião]", "[Experiência]", "[faço sempre]", "[aconteceu 1x]"]:
        assert tag in prompt
