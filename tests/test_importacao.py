"""Testes da sincronização Notion → `fontes` (app/importacao.py), sem rede e sem modelo: o SDK oficial fala com o
NotionFalso, que serve o workspace FICTÍCIO de tests/fixtures/notion/workspace.json.

O que o workspace tem (e o que a 1ª rodada deve fazer com cada página):
- "Cérebro: teste fictício": só subpáginas → vazia;
- "Como qualificar leads de hotelaria", "Objeções comuns e respostas", "Roteiro da reunião de diagnóstico",
  "Prospecção por indicação", "Hotel Fictício Sol" (linha de banco de dados) e "Rascunho antigo de proposta" → a_curar;
- "Contato do hotel parceiro": e-mail no texto → pulada_dado_pessoal;
- "Ligar para 81 99876-5432 amanhã": telefone no TÍTULO → pulada_dado_pessoal, título omitido;
- "Cópia de Prospecção por indicação": o mesmo texto da outra → pulada_duplicata.
"""
import logging
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app import importacao, notion, trechos
from app.db import SessionLocal
from app.importacao import TITULO_OMITIDO, importar
from app.models import MOTIVO_MAX, ExecucaoImportacao, Fonte
from app.notion import ErroNotion, LeitorNotion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, id_da_pagina, limpar_banco_da_importacao

AGORA = datetime(2026, 10, 13, 12, 0)

ESPERADO_NA_1A_RODADA = {
    "Cérebro: teste fictício": "vazia",
    "Como qualificar leads de hotelaria": "a_curar",
    "Objeções comuns e respostas": "a_curar",
    "Roteiro da reunião de diagnóstico": "a_curar",
    "Contato do hotel parceiro": "pulada_dado_pessoal",
    TITULO_OMITIDO: "pulada_dado_pessoal",
    "Prospecção por indicação": "a_curar",
    "Cópia de Prospecção por indicação": "pulada_duplicata",
    "Hotel Fictício Sol": "a_curar",
    "Rascunho antigo de proposta": "a_curar",
}


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        limpar_banco_da_importacao(sessao)
        yield sessao


@pytest.fixture
def relogio(monkeypatch):
    """O relógio da importação: fixo, e os testes podem avançar. O do leitor não espera de verdade."""
    hora = {"agora": AGORA}
    monkeypatch.setattr(importacao, "_agora", lambda: hora["agora"])
    monkeypatch.setattr(notion, "_dormir", lambda segundos: None)
    return hora


@pytest.fixture
def falso():
    return NotionFalso()


@pytest.fixture
def rodar(falso, db, relogio):
    """Uma execução da importação sobre o workspace falso (cada uma com um leitor novo, como o script faz)."""
    def _rodar(**opcoes):
        return importar(LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http()), db, **opcoes)
    return _rodar


def status_no_banco(db) -> dict[str, str]:
    return {f.titulo: f.status for f in db.scalars(select(Fonte))}


def fonte(db, falso, titulo) -> Fonte:
    return db.scalar(select(Fonte).where(Fonte.id_externo == id_da_pagina(falso.ws, titulo)))


def retrato(db) -> list[tuple]:
    """Todas as colunas de todas as fontes: para provar que uma rodada não mudou nada."""
    db.expire_all()
    return [
        (f.id, f.origem, f.id_externo, f.titulo, f.url, f.markdown, f.hash_conteudo, f.editado_em, f.importado_em,
         f.status, f.motivo)
        for f in db.scalars(select(Fonte).order_by(Fonte.id))
    ]


# --- 1ª rodada: a triagem de cada página -----------------------------------------------------------------

def test_primeira_rodada_classifica_cada_pagina(rodar, db):
    relatorio = rodar()

    assert status_no_banco(db) == ESPERADO_NA_1A_RODADA
    assert (relatorio.lidas, len(relatorio.novas), len(relatorio.alteradas)) == (10, 10, 0)
    assert len(relatorio.puladas) == 4
    assert len(relatorio.a_curar) == 6
    assert relatorio.falhas == relatorio.removidas == []
    assert relatorio.avisos == []


def test_a_execucao_fica_registrada_com_as_contagens_da_spec(rodar, db, relogio):
    relatorio = rodar()

    execucao = db.get(ExecucaoImportacao, relatorio.execucao_id)
    assert (execucao.inicio, execucao.fim) == (AGORA, AGORA)
    assert (execucao.paginas_lidas, execucao.paginas_novas, execucao.paginas_alteradas, execucao.paginas_falhas) \
        == (10, 10, 0, 0)


def test_fonte_guarda_os_campos_da_spec(rodar, db, falso):
    rodar()

    f = fonte(db, falso, "Objeções comuns e respostas")
    pid = id_da_pagina(falso.ws, "Objeções comuns e respostas")
    assert f.origem == "notion"
    assert f.id_externo == pid
    assert f.url == "https://www.notion.so/" + pid.replace("-", "")  # pelo id: o título não vai no endereço
    assert f.markdown.startswith("Respostas que o time usou")
    assert "| Está caro |" in f.markdown
    assert len(f.hash_conteudo) == 64
    assert f.editado_em == datetime(2026, 9, 3, 9, 0)  # o last_edited_time, em UTC
    assert f.importado_em == AGORA


def test_motivo_gravado_em_cada_pulada_e_vazio_nas_outras(rodar, db):
    """O motivo do relatório também fica na fonte (a tela de Fontes mostra), sem repetir o dado pessoal."""
    rodar()

    motivos = {f.titulo: f.motivo for f in db.scalars(select(Fonte))}
    assert motivos == {
        "Cérebro: teste fictício": f"menos de {importacao.MIN_CARACTERES} caracteres de texto",
        "Como qualificar leads de hotelaria": None,
        "Objeções comuns e respostas": None,
        "Roteiro da reunião de diagnóstico": None,
        "Contato do hotel parceiro": "e-mail no conteúdo",
        TITULO_OMITIDO: "telefone no título",
        "Prospecção por indicação": None,
        "Cópia de Prospecção por indicação": "mesmo conteúdo de “Prospecção por indicação”",
        "Hotel Fictício Sol": None,
        "Rascunho antigo de proposta": None,
    }
    assert not any("@" in m or "99876" in m for m in motivos.values() if m)


def test_motivo_longo_e_cortado_no_tamanho_da_coluna():
    assert importacao._motivo("") is None
    assert importacao._motivo("e-mail no conteúdo") == "e-mail no conteúdo"
    cortado = importacao._motivo("x" * 500)
    assert len(cortado) == MOTIVO_MAX and cortado.endswith("…")


# --- idempotência ------------------------------------------------------------------------------------------

def test_duas_rodadas_seguidas_nao_mudam_nada(rodar, db, falso, relogio):
    """Critério de aceite da spec: rodar duas vezes seguidas = zero mudança (e nada duplicado)."""
    rodar()
    antes = retrato(db)
    falso.pedidos.clear()
    relogio["agora"] = datetime(2026, 10, 14, 8, 0)

    relatorio = rodar()

    assert retrato(db) == antes  # nenhuma coluna de nenhuma fonte mudou, nem o importado_em
    assert (relatorio.lidas, len(relatorio.novas), len(relatorio.alteradas)) == (10, 0, 0)
    assert len(relatorio.sem_mudanca) == 10
    assert relatorio.puladas == []  # as puladas da 1ª rodada não "são puladas de novo"
    assert all(caminho == "/v1/search" for _, caminho in falso.pedidos)  # com a mesma data, nem lê os blocos
    assert db.scalar(select(func.count()).select_from(ExecucaoImportacao)) == 2  # só a execução nova


def test_editada_sem_mudar_o_texto_nao_reprocessa(rodar, db, falso, relogio):
    rodar()
    falso.editar("Prospecção por indicação", editado="2026-10-02T10:00:00.000Z")
    relogio["agora"] = datetime(2026, 10, 14, 8, 0)

    relatorio = rodar()

    f = fonte(db, falso, "Prospecção por indicação")
    assert f.editado_em == datetime(2026, 10, 2, 10, 0)  # a data nova é guardada...
    assert f.importado_em == AGORA  # ...mas o conteúdo é o mesmo: não foi reimportado
    assert relatorio.alteradas == []
    assert falso.pedidos.count(("GET", f"/v1/blocks/{f.id_externo}/children")) == 2  # leu, comparou o hash


def test_titulo_novo_com_o_mesmo_texto_so_atualiza_o_titulo(rodar, db, falso):
    rodar()
    falso.pagina("Prospecção por indicação")["properties"]["title"]["title"][0]["plain_text"] = "Indicação (v2)"
    falso.editar("Indicação (v2)", editado="2026-10-02T10:00:00.000Z")

    relatorio = rodar()

    assert db.scalar(select(Fonte.titulo).where(Fonte.titulo == "Indicação (v2)"))
    assert relatorio.alteradas == []


def test_pagina_editada_vira_alterada(rodar, db, falso, relogio):
    rodar()
    falso.editar("Prospecção por indicação", "Indicação no encerramento trouxe três clientes novos no ano.")
    relogio["agora"] = datetime(2026, 10, 14, 8, 0)

    relatorio = rodar()

    f = fonte(db, falso, "Prospecção por indicação")
    assert [p.titulo for p in relatorio.alteradas] == ["Prospecção por indicação"]
    assert f.markdown.startswith("Indicação no encerramento")
    assert f.importado_em == datetime(2026, 10, 14, 8, 0)
    assert f.status == "a_curar"
    assert db.get(ExecucaoImportacao, relatorio.execucao_id).paginas_alteradas == 1


# --- triagem: dado pessoal ----------------------------------------------------------------------------------

def test_dado_pessoal_no_conteudo_pula_sem_guardar_o_texto(rodar, db, falso):
    relatorio = rodar()

    f = fonte(db, falso, "Contato do hotel parceiro")
    assert f.status == "pulada_dado_pessoal"
    assert f.markdown is None  # o texto com o dado não fica no banco
    assert len(f.hash_conteudo) == 64  # o hash basta para saber se a página mudou
    [pulada] = [p for p in relatorio.puladas if p.titulo == "Contato do hotel parceiro"]
    assert pulada.motivo == "e-mail no conteúdo"
    assert pulada.trechos == []


def test_dado_pessoal_no_titulo_omite_o_titulo(rodar, db, falso):
    relatorio = rodar()

    f = fonte(db, falso, "Ligar para 81 99876-5432 amanhã")
    assert f.titulo == TITULO_OMITIDO
    assert "99876" not in f.url
    [pulada] = [p for p in relatorio.puladas if p.titulo == TITULO_OMITIDO]
    assert pulada.motivo == "telefone no título"


def test_o_relatorio_nunca_repete_o_dado_pessoal(rodar):
    relatorio = rodar()

    tudo = repr(relatorio)
    assert "contato@hotel-ficticio.com.br" not in tudo
    assert "99876" not in tudo


def renomear(falso, titulo: str, novo: str) -> None:
    """Simula uma troca de título no Notion (muda também a data de edição; o texto continua o mesmo)."""
    rico = falso.pagina(titulo)["properties"]["title"]["title"][0]
    rico["plain_text"] = rico["text"]["content"] = novo
    falso.editar(novo, editado="2026-10-05T09:00:00.000Z")


def test_titulo_corrigido_libera_a_pagina(rodar, db, falso):
    """O dado pessoal estava só no título: corrigido o título (com o mesmo texto), a página passa na triagem."""
    rodar()
    renomear(falso, "Ligar para 81 99876-5432 amanhã", "Ligar amanhã para o parceiro")

    relatorio = rodar()

    f = fonte(db, falso, "Ligar amanhã para o parceiro")
    assert (f.status, f.titulo, f.motivo) == ("a_curar", "Ligar amanhã para o parceiro", None)
    assert f.markdown.startswith("Retomar a conversa")
    assert [p.titulo for p in relatorio.alteradas] == ["Ligar amanhã para o parceiro"]


def test_titulo_que_ganha_dado_pessoal_barra_a_pagina(rodar, db, falso):
    rodar()
    renomear(falso, "Objeções comuns e respostas", "Objeções (ligar 81 99876-5432)")

    relatorio = rodar()

    f = fonte(db, falso, "Objeções (ligar 81 99876-5432)")
    assert (f.status, f.titulo, f.markdown) == ("pulada_dado_pessoal", TITULO_OMITIDO, None)
    assert [(p.titulo, p.motivo) for p in relatorio.puladas] == [(TITULO_OMITIDO, "telefone no título")]
    assert relatorio.a_curar == [p for p in relatorio.a_curar if p.titulo != TITULO_OMITIDO]


def test_dado_pessoal_no_texto_e_titulo_novo_continua_pulada_sem_mudanca(rodar, db, falso):
    rodar()
    renomear(falso, "Contato do hotel parceiro", "Contato do parceiro")

    relatorio = rodar()

    assert fonte(db, falso, "Contato do parceiro").status == "pulada_dado_pessoal"
    assert relatorio.alteradas == []  # o texto é o mesmo e continua com o e-mail: nada a refazer


def test_titulo_longo_demais_e_cortado(rodar, db, falso):
    rico = falso.pagina("Prospecção por indicação")["properties"]["title"]["title"][0]
    rico["plain_text"] = rico["text"]["content"] = "Indicação " * 80  # 800 caracteres

    rodar()

    f = db.scalar(select(Fonte).where(Fonte.titulo.like("Indicação Indicação%")))
    assert len(f.titulo) == importacao.TITULO_MAX
    assert f.titulo.endswith("…")


def test_pagina_que_ganha_dado_pessoal_deixa_de_guardar_o_texto(rodar, db, falso):
    rodar()
    falso.editar("Prospecção por indicação", "Indicação do cliente de CPF 123.456.789-09 trouxe dois contratos.")

    rodar()

    f = fonte(db, falso, "Prospecção por indicação")
    assert (f.status, f.markdown) == ("pulada_dado_pessoal", None)


# --- triagem: vazia, duplicata, longa ----------------------------------------------------------------------

def test_pagina_so_com_subpaginas_e_vazia(rodar):
    relatorio = rodar()

    [vazia] = [p for p in relatorio.puladas if p.status == "vazia"]
    assert vazia.titulo == "Cérebro: teste fictício"
    assert vazia.motivo == "menos de 20 caracteres de texto"


def test_duplicata_exata_pula_a_segunda(rodar):
    relatorio = rodar()

    [duplicata] = [p for p in relatorio.puladas if p.status == "pulada_duplicata"]
    assert duplicata.titulo == "Cópia de Prospecção por indicação"  # a mais nova: o search vem do mais antigo
    assert duplicata.motivo == "mesmo conteúdo de “Prospecção por indicação”"


def test_duplicata_ignora_o_titulo_e_espacos_no_fim(rodar, db, falso):
    copia = falso.ws["blocos"][id_da_pagina(falso.ws, "Cópia de Prospecção por indicação")][0]
    copia["paragraph"]["rich_text"][0]["plain_text"] += "   "

    rodar()

    assert fonte(db, falso, "Cópia de Prospecção por indicação").status == "pulada_duplicata"


def test_duplicata_de_uma_pagina_importada_antes(rodar, db, falso):
    """Na 1ª rodada a cópia ainda não existe; ela aparece depois e é comparada com o que está no banco."""
    pid = id_da_pagina(falso.ws, "Cópia de Prospecção por indicação")
    copia = falso.ws["paginas"].pop(pid)
    rodar()
    falso.ws["paginas"][pid] = copia

    relatorio = rodar()

    assert [(p.titulo, p.status) for p in relatorio.novas] == [
        ("Cópia de Prospecção por indicação", "pulada_duplicata")
    ]


def test_pagina_grande_e_dividida_em_trechos(monkeypatch, rodar):
    monkeypatch.setattr(trechos, "LIMITE_TRECHO", 300)
    monkeypatch.setattr(trechos, "_RESERVA_CABECALHO", 150)

    relatorio = rodar()

    [qualificar] = [p for p in relatorio.a_curar if p.titulo == "Como qualificar leads de hotelaria"]
    assert len(qualificar.trechos) > 1
    assert all(len(t.texto) <= 300 for t in qualificar.trechos)
    assert all(t.texto.startswith("Página do Notion: Como qualificar leads de hotelaria\n") for t in qualificar.trechos)


def test_pagina_longa_demais_pula_com_motivo(monkeypatch, rodar, db, falso):
    monkeypatch.setattr(trechos, "LIMITE_TRECHO", 300)
    monkeypatch.setattr(trechos, "_RESERVA_CABECALHO", 150)
    monkeypatch.setattr(trechos, "MAX_TRECHOS", 1)

    relatorio = rodar()

    [longa] = [p for p in relatorio.puladas if p.titulo == "Como qualificar leads de hotelaria"]
    assert longa.status == "pulada_longa"
    assert longa.motivo.endswith(" trechos (limite 1)")
    assert fonte(db, falso, "Como qualificar leads de hotelaria").markdown  # o texto fica, para conferir depois


def test_linha_de_banco_de_dados_e_tratada_como_pagina(rodar, db, falso):
    rodar()

    f = fonte(db, falso, "Hotel Fictício Sol")
    assert f.status == "a_curar"
    assert f.markdown.startswith("Aprendizado: o hotel só fechou")
    assert "hotelaria" not in f.markdown  # as colunas (propriedades) não entram: só os blocos


# --- página apagada ou movida ----------------------------------------------------------------------------

def test_pagina_na_lixeira_vira_removida(rodar, db, falso):
    rodar()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True

    relatorio = rodar()

    f = fonte(db, falso, "Rascunho antigo de proposta")
    assert (f.status, f.motivo) == ("removida", "na lixeira do Notion")
    assert f.markdown  # nada é apagado
    assert [(p.titulo, p.motivo) for p in relatorio.removidas] == [
        ("Rascunho antigo de proposta", "na lixeira do Notion")
    ]


def test_pagina_apagada_ou_sem_compartilhamento_vira_removida(rodar, db, falso):
    rodar()
    pid = id_da_pagina(falso.ws, "Rascunho antigo de proposta")
    del falso.ws["paginas"][pid]  # o Notion responde 404: apagada ou não compartilhada (a API não diferencia)

    relatorio = rodar()

    assert db.scalar(select(Fonte.motivo).where(Fonte.id_externo == pid)) == "apagada ou sem compartilhamento"
    assert [p.motivo for p in relatorio.removidas] == ["apagada ou sem compartilhamento"]


def test_pagina_que_o_search_nao_listou_mas_existe_nao_muda(rodar, db, falso):
    rodar()
    falso.escondidas_da_busca.add(id_da_pagina(falso.ws, "Rascunho antigo de proposta"))

    relatorio = rodar()

    assert fonte(db, falso, "Rascunho antigo de proposta").status == "a_curar"
    assert relatorio.removidas == []


def test_busca_incompleta_nao_marca_removida(rodar, db, falso):
    rodar()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True
    falso.busca_incompleta = True

    relatorio = rodar()

    assert fonte(db, falso, "Rascunho antigo de proposta").status == "a_curar"
    assert relatorio.removidas == []
    assert "não foram conferidas" in relatorio.avisos[0]


def test_limite_de_paginas_le_so_n_e_nao_marca_removida(rodar, db, falso):
    rodar()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True

    relatorio = rodar(limite_paginas=3)

    assert relatorio.lidas == 3
    assert fonte(db, falso, "Rascunho antigo de proposta").status == "a_curar"
    assert relatorio.removidas == []
    assert relatorio.avisos


def test_pagina_removida_que_volta_e_lida_de_novo(rodar, db, falso):
    rodar()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True
    rodar()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = False

    relatorio = rodar()

    assert [p.titulo for p in relatorio.alteradas] == ["Rascunho antigo de proposta"]
    assert fonte(db, falso, "Rascunho antigo de proposta").status == "a_curar"


# --- o que espera o curador ---------------------------------------------------------------------------------

def test_pendentes_de_execucoes_anteriores_continuam_na_lista_do_curador(rodar):
    rodar()

    relatorio = rodar(limite_paginas=2)  # só 2 páginas lidas, mas as 6 a_curar continuam esperando o curador

    assert len(relatorio.a_curar) == 6
    assert {p.acao for p in relatorio.a_curar} == {"sem mudança", "pendente"}


# --- falhas -------------------------------------------------------------------------------------------------

def test_falha_ao_ler_uma_pagina_nao_derruba_a_execucao(rodar, db, falso):
    pid = id_da_pagina(falso.ws, "Objeções comuns e respostas")
    falso.falhar(f"/v1/blocks/{pid}/children", 403)

    relatorio = rodar()

    assert [(p.titulo, p.acao) for p in relatorio.falhas] == [("Objeções comuns e respostas", "falha")]
    assert "permissão de leitura" in relatorio.falhas[0].motivo
    assert fonte(db, falso, "Objeções comuns e respostas") is None  # nada gravado: a próxima tenta de novo
    assert db.get(ExecucaoImportacao, relatorio.execucao_id).paginas_falhas == 1

    segunda = rodar()

    assert [p.titulo for p in segunda.novas] == ["Objeções comuns e respostas"]


def test_falha_ao_conferir_uma_pagina_sumida(rodar, db, falso):
    rodar()
    pid = id_da_pagina(falso.ws, "Rascunho antigo de proposta")
    falso.escondidas_da_busca.add(pid)
    falso.falhar(f"/v1/pages/{pid}", 403)

    relatorio = rodar()

    assert [p.acao for p in relatorio.falhas] == ["falha"]
    assert relatorio.lidas == 9  # a que falhou na conferência não veio na busca: não conta como lida
    assert fonte(db, falso, "Rascunho antigo de proposta").status == "a_curar"


def test_erro_na_busca_levanta_e_fecha_a_execucao(rodar, db, falso):
    falso.falhar("/v1/search", 401)

    with pytest.raises(ErroNotion, match="token do Notion é inválido"):
        rodar()

    execucao = db.scalar(select(ExecucaoImportacao))
    assert execucao.fim is not None
    assert execucao.paginas_lidas == 0


def test_erro_inesperado_desfaz_o_que_estava_pela_metade_e_fecha_a_execucao(monkeypatch, rodar, db):
    def quebrar(*args):
        raise RuntimeError("bug simulado")

    monkeypatch.setattr(importacao, "_triar", quebrar)

    with pytest.raises(RuntimeError):
        rodar()

    execucao = db.scalar(select(ExecucaoImportacao))
    assert execucao.fim is not None
    assert db.scalar(select(func.count()).select_from(Fonte)) == 0


# --- dry-run --------------------------------------------------------------------------------------------------

def test_dry_run_faz_a_mesma_triagem_sem_gravar_nada(rodar, db):
    relatorio = rodar(dry_run=True)

    assert db.scalar(select(func.count()).select_from(Fonte)) == 0
    assert db.scalar(select(func.count()).select_from(ExecucaoImportacao)) == 0
    assert relatorio.execucao_id is None
    assert {p.titulo: p.status for p in relatorio.paginas} == ESPERADO_NA_1A_RODADA  # inclusive a duplicata


def test_dry_run_depois_de_uma_rodada_ve_as_mudancas_sem_gravar(rodar, db, falso):
    rodar()
    antes = retrato(db)
    falso.editar("Prospecção por indicação", "Indicação no encerramento trouxe três clientes novos no ano.")
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True

    relatorio = rodar(dry_run=True)

    assert [p.titulo for p in relatorio.alteradas] == ["Prospecção por indicação"]
    assert [p.titulo for p in relatorio.removidas] == ["Rascunho antigo de proposta"]
    assert "Rascunho antigo de proposta" not in [p.titulo for p in relatorio.a_curar]  # nem listada duas vezes
    assert retrato(db) == antes


# --- log ----------------------------------------------------------------------------------------------------

def test_log_da_sincronizacao_sem_texto_nem_titulo(rodar, falso, caplog):
    falso.falhar("/v1/search", 429, retry_after="1")
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="app"):
        rodar()

    assert '"evento": "importacao_notion"' in caplog.text
    assert TOKEN_DE_TESTE not in caplog.text
    for titulo in ESPERADO_NA_1A_RODADA:
        assert titulo not in caplog.text
    for proibido in ["Ligar para 81", "contato@hotel-ficticio", "orçamento aprovado", "Está caro"]:
        assert proibido not in caplog.text
