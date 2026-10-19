"""A importação do Drive (app/importacao_drive.py), sem rede e sem modelo: o Drive é o DriveFalso, o modelo é o
CuradorDeLote (o mesmo da importação do Notion) e os arquivos são docx, PDF e xlsx de verdade, gerados em memória.

O que muda do Notion: nada de barreira de dado pessoal, a categoria vem da subpasta, o arquivo grande nem é baixado e
o documento vira também pedaços de busca (trechos_documento)."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import importacao, importacao_drive, llm, trechos
from app.db import SessionLocal
from app.importacao import DRIVE, importar
from app.models import ExecucaoImportacao, Fonte, HistoricoStatus, Insight, TrechoDocumento
from tests.drive_falso import BASE, DriveFalso, docx_com, pdf_com, xlsx_com
from tests.notion_falso import limpar_banco_da_importacao
from tests.test_curadoria_notion import CuradorDeLote, usar

AGORA = datetime(2026, 10, 15, 12, 0)
DEPOIS = BASE + timedelta(days=2)

GUIA = docx_com(
    "# O que eu ensinaria a um novato", "## Prospecção",
    "Filtrar o ICP no Lusha e conferir no olho antes de montar a lista. [Experiência]",
    "## Negociação", "Quando pedem desconto, peço uma parcela só ou reduzo o escopo. [faço sempre]",
)


class CuradorDoDrive(CuradorDeLote):
    """O CuradorDeLote tira o prefixo do Notion do título; aqui é o do Drive."""

    def curar(self, texto, conversa, turno, ultimo_turno):
        resposta = super().curar(texto, conversa, turno, ultimo_turno)
        resposta.insight.titulo = texto.splitlines()[0].removeprefix("Documento do Drive: ")
        return resposta


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        limpar_banco_da_importacao(sessao)
        yield sessao
        limpar_banco_da_importacao(sessao)


@pytest.fixture
def drive(monkeypatch):
    monkeypatch.setattr(importacao, "_agora", lambda: AGORA)
    return DriveFalso()


@pytest.fixture
def curador(monkeypatch):
    return usar(monkeypatch, CuradorDoDrive())


@pytest.fixture
def rodar(drive, db):
    def _rodar(**opcoes):
        opcoes.setdefault("teto_usd", 1.0)
        return importar(drive, db, origem=DRIVE, sincronizar=importacao_drive.sincronizar, **opcoes)
    return _rodar


def fonte(db, arquivo) -> Fonte:
    db.expire_all()
    return db.scalar(select(Fonte).where(Fonte.origem == "drive", Fonte.id_externo == arquivo.id))


def itens(db) -> list[Insight]:
    db.expire_all()
    return list(db.scalars(select(Insight).where(Insight.fonte == "drive").order_by(Insight.id)))


def pedacos(db, arquivo) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(TrechoDocumento.texto).where(TrechoDocumento.fonte_id == fonte(db, arquivo).id)
                           .order_by(TrechoDocumento.ordem)))


# --- o caminho feliz ----------------------------------------------------------------------------------------

def test_documento_vira_fonte_item_na_fila_e_pedacos_de_busca(rodar, db, drive, curador):
    guia = drive.adicionar("O que eu ensinaria a um novato.docx", GUIA, caminho=("Ensinamentos Comercial",))

    relatorio = rodar()

    f = fonte(db, guia)
    assert (f.status, f.motivo, f.categoria) == ("importada", None, "Ensinamentos Comercial")
    assert (f.titulo, f.url) == ("O que eu ensinaria a um novato", guia.url)  # sem a extensão; o link pelo id
    assert f.editado_em == BASE and f.markdown.startswith("# O que eu ensinaria")
    [item] = itens(db)
    assert (item.status, item.fonte, item.autor, item.fonte_ref) == ("historico_a_validar", "drive", "importação Drive",
                                                                    guia.url)
    [historico] = db.scalars(select(HistoricoStatus).where(HistoricoStatus.insight_id == item.id))
    assert historico.motivo == f"Importado do Drive (execução #{relatorio.execucao_id})"
    assert "Lusha" in "".join(pedacos(db, guia))
    execucao = db.get(ExecucaoImportacao, relatorio.execucao_id)
    assert (execucao.origem, execucao.status, execucao.paginas_curadas, execucao.insights_propostos) == (
        "drive", "concluida", 1, 1)


def test_o_curador_recebe_o_cabecalho_do_documento_com_a_pasta(rodar, drive, curador):
    drive.adicionar("guia.docx", GUIA, caminho=("Resumo Comercial",))

    rodar()

    [enviado] = curador.textos
    assert enviado.startswith("Documento do Drive: guia (pasta Resumo Comercial)\n\n")
    assert "[faço sempre]" in enviado  # as tags de origem chegam ao curador: é com elas que ele escolhe a evidência


def test_rodar_de_novo_nao_baixa_nem_cura_nada(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    drive.baixados.clear()

    relatorio = rodar()

    assert drive.baixados == []  # não mudou: nem baixa
    assert len(curador.textos) == 1 and len(itens(db)) == 1
    assert [p.acao for p in relatorio.paginas] == ["sem mudança"]
    assert fonte(db, guia).status == "importada"


def test_documento_editado_vira_alterado_obsoleta_o_pendente_e_refaz_os_pedacos(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    [antigo] = itens(db)
    drive.editar(guia, docx_com("# Guia", "Texto novo sobre a cadência de ligações que muda tudo."), DEPOIS)

    relatorio = rodar()

    db.refresh(antigo)
    assert antigo.status == "obsoleto" and "o arquivo do Drive mudou" in antigo.motivo_obsolescencia
    assert [i.status for i in itens(db)] == ["obsoleto", "historico_a_validar"]
    assert relatorio.obsoletos == 1 and [p.acao for p in relatorio.paginas] == ["alterada"]
    assert "cadência" in "".join(pedacos(db, guia)) and "Lusha" not in "".join(pedacos(db, guia))


def test_item_ja_aprovado_nao_muda_quando_o_documento_muda(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    [item] = itens(db)
    item.status = "validado"
    db.commit()
    drive.editar(guia, docx_com("# Guia", "Outro texto completamente novo para este documento."), DEPOIS)

    relatorio = rodar()

    db.refresh(item)
    assert item.status == "validado"
    assert relatorio.aprovados_de_paginas_mudadas == 1


def test_arquivo_tocado_sem_mudar_o_texto_nao_volta_ao_curador(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    drive.tocar(guia, DEPOIS)

    relatorio = rodar()

    assert len(curador.textos) == 1 and len(itens(db)) == 1  # abriu e salvou: o mesmo texto não é curado de novo
    assert fonte(db, guia).status == "importada" and fonte(db, guia).editado_em == DEPOIS
    assert [p.acao for p in relatorio.paginas] == ["sem mudança"]


def test_arquivo_que_saiu_da_pasta_vira_removido_e_sem_pedacos(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    outro = drive.adicionar("outro.docx", docx_com("# Outro", "Conteúdo bastante diferente do outro documento aqui."))
    rodar()
    drive.remover(guia)

    relatorio = rodar()

    f = fonte(db, guia)
    assert f.status == "removida" and f.motivo == "saiu da pasta do Drive (apagado, movido ou sem acesso)"
    assert pedacos(db, outro) != [] and db.scalar(select(func.count()).where(TrechoDocumento.fonte_id == f.id)) == 0
    assert [p.acao for p in relatorio.removidas] == ["removida"] and relatorio.obsoletos == 1
    assert [i.status for i in itens(db)].count("obsoleto") == 1


def test_lista_incompleta_nao_remove_nada(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    drive.remover(guia)
    drive.lista_incompleta = True

    relatorio = rodar()

    assert fonte(db, guia).status == "importada"
    assert any("incompleta" in aviso for aviso in relatorio.avisos)


def test_arquivo_que_voltou_para_a_pasta_e_tratado_como_alterado(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    rodar()
    drive.remover(guia)
    rodar()
    drive.meta[guia.id], drive.conteudos[guia.id] = guia, GUIA

    relatorio = rodar()

    assert fonte(db, guia).status == "importada" and [p.acao for p in relatorio.paginas] == ["alterada"]
    assert pedacos(db, guia) != []


# --- o que NÃO vai ao curador ---------------------------------------------------------------------------------

def test_arquivo_acima_do_limite_nem_e_baixado(monkeypatch, rodar, db, drive, curador):
    monkeypatch.setattr(importacao_drive.settings, "drive_max_mb", 30)
    grande = drive.adicionar("slides.pdf", pdf_com("x"), tamanho=56 * 1024 * 1024)

    relatorio = rodar()

    assert drive.baixados == []
    f = fonte(db, grande)
    assert f.status == "pulada_longa"
    assert f.motivo == "arquivo de 56 MB, acima do limite de 30 MB (DRIVE_MAX_MB no .env)"
    assert curador.textos == [] and [p.status for p in relatorio.puladas] == ["pulada_longa"]


def test_com_o_limite_maior_o_arquivo_grande_e_lido_na_proxima_rodada(monkeypatch, rodar, db, drive, curador):
    monkeypatch.setattr(importacao_drive.settings, "drive_max_mb", 30)
    grande = drive.adicionar("proposta.pdf", pdf_com("Proposta de Discovery para uma empresa de energia solar"),
                             tamanho=56 * 1024 * 1024)
    rodar()
    monkeypatch.setattr(importacao_drive.settings, "drive_max_mb", 60)

    rodar()

    assert drive.baixados == [grande.id] and fonte(db, grande).status == "importada"
    assert len(itens(db)) == 1


def test_arquivo_grande_que_continua_grande_nao_gera_trabalho(monkeypatch, rodar, db, drive, curador):
    grande = drive.adicionar("slides.pdf", pdf_com("x"), tamanho=56 * 1024 * 1024)
    rodar()

    relatorio = rodar()

    assert drive.baixados == [] and fonte(db, grande).status == "pulada_longa"
    assert [p.acao for p in relatorio.paginas] == ["sem mudança"]


def test_pdf_de_imagem_fica_vazio_com_o_motivo(rodar, db, drive, curador):
    imagem = drive.adicionar("slides.pdf", pdf_com())

    rodar()

    f = fonte(db, imagem)
    assert (f.status, f.motivo) == ("vazia", "sem texto: o PDF parece ser só imagem (não faço OCR)")
    assert f.markdown is None and pedacos(db, imagem) == [] and curador.textos == []


def test_formato_nao_suportado_fica_vazio_sem_baixar(rodar, db, drive, curador):
    figura = drive.adicionar("foto.png", b"\x89PNG")

    rodar()

    assert fonte(db, figura).motivo == "formato não suportado (image/png)" and drive.baixados == []


def test_arquivo_corrompido_fica_vazio_com_so_o_tipo_do_erro(rodar, db, drive, curador):
    ruim = drive.adicionar("quebrado.docx", b"nao e um docx SEGREDO")

    rodar()

    f = fonte(db, ruim)
    assert f.status == "vazia" and f.motivo.startswith("não consegui ler o arquivo (") and "SEGREDO" not in f.motivo


def test_planilha_vai_so_para_a_busca(rodar, db, drive, curador):
    planilha = drive.adicionar("prospeccao.xlsx", xlsx_com([["Empresa", "Setor"], ["Acme Ltda", "Indústria"]]))

    rodar()

    f = fonte(db, planilha)
    assert (f.status, f.motivo) == ("so_busca", "planilha: o consultor acha na busca, mas ela não vai ao curador")
    assert curador.textos == [] and itens(db) == []
    assert "Acme Ltda" in "".join(pedacos(db, planilha))


def test_documento_longo_demais_vai_so_para_a_busca(monkeypatch, rodar, db, drive, curador):
    monkeypatch.setattr(trechos, "LIMITE_TRECHO", 300)
    monkeypatch.setattr(trechos, "_RESERVA_CABECALHO", 150)
    monkeypatch.setattr(importacao_drive.settings, "drive_max_trechos", 2)
    livro = drive.adicionar("livro.docx", docx_com(*[f"Parágrafo {i} sobre vendas consultivas e discovery." * 3
                                                      for i in range(12)]))

    rodar()

    f = fonte(db, livro)
    assert f.status == "so_busca" and "trechos (limite 2)" in f.motivo and curador.textos == []
    assert len(pedacos(db, livro)) >= 1


def test_duplicata_do_mesmo_texto_em_outra_pasta(rodar, db, drive, curador):
    original = drive.adicionar("guia.docx", GUIA, caminho=("Resumo Comercial",))
    copia = drive.adicionar("guia (cópia).docx", GUIA, caminho=("Ensinamentos Comercial",),
                            modificado_em=BASE + timedelta(hours=1))

    rodar()

    assert fonte(db, original).status == "importada"
    f = fonte(db, copia)
    assert (f.status, f.motivo) == ("pulada_duplicata", "mesmo conteúdo de “guia”") and pedacos(db, copia) == []
    assert len(curador.textos) == 1


def test_documento_sem_texto_de_verdade_fica_vazio(rodar, db, drive, curador):
    pouco = drive.adicionar("nada.docx", docx_com("# Título", "oi"))

    rodar()

    assert fonte(db, pouco).status == "vazia" and "menos de 20 caracteres" in fonte(db, pouco).motivo


# --- dado pessoal: NÃO barra (decisão do Davi) -----------------------------------------------------------------

DOC_COM_DADO = docx_com(
    "# Acompanhamento da Acme", "Falei com a Ana (ana@acme.com.br, (81) 99876-5432) sobre o orçamento do projeto.",
    "O orçamento estava fora, sem margem para o Discovery. [Experiência]",
)


def test_dado_pessoal_nao_barra_o_documento_vai_ao_curador_e_a_busca(rodar, db, drive, curador):
    doc = drive.adicionar("acompanhamento.docx", DOC_COM_DADO)

    rodar()

    assert "ana@acme.com.br" in curador.textos[0] and "99876-5432" in curador.textos[0]  # o texto vai como está
    f = fonte(db, doc)
    assert f.status == "importada" and f.markdown is not None
    assert f.motivo == "contém e-mail, telefone (mantido, por decisão do time)"
    assert "ana@acme.com.br" in "".join(pedacos(db, doc))
    assert len(itens(db)) == 1


def test_item_proposto_com_dado_pessoal_tambem_entra_na_fila(monkeypatch, rodar, db, drive):
    usar(monkeypatch, CuradorDoDrive(dado_pessoal_se=lambda t: "Acompanhamento" in t))
    drive.adicionar("acompanhamento.docx", DOC_COM_DADO)

    relatorio = rodar()

    assert relatorio.falhas_do_curador == [] and len(itens(db)) == 1  # no Notion isto seria `falha`
    assert "99876-5432" in itens(db)[0].contexto_cliente


def test_o_aviso_de_dado_pessoal_sobrevive_ao_curador_e_aparece_tambem_no_so_busca(rodar, db, drive, curador):
    planilha = drive.adicionar("contatos.xlsx", xlsx_com([["Ana", "ana@acme.com.br"], ["Beto", "81 99876-5432"]]))

    rodar()

    assert fonte(db, planilha).motivo.endswith("contém e-mail, telefone (mantido, por decisão do time)")


# --- falhas e teto -----------------------------------------------------------------------------------------

def test_download_que_falha_deixa_a_fonte_como_estava_e_tenta_de_novo(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)
    drive.falhar_download.add(guia.id)

    relatorio = rodar()

    assert fonte(db, guia) is None and [p.acao for p in relatorio.falhas] == ["falha"]
    assert relatorio.falhas[0].motivo == "O Drive devolveu um erro (500)."
    assert db.get(ExecucaoImportacao, relatorio.execucao_id).paginas_falhas == 1
    drive.falhar_download.clear()
    rodar()
    assert fonte(db, guia).status == "importada"


def test_dry_run_le_mas_nao_muda_nada_nem_chama_o_modelo(rodar, db, drive, curador):
    guia = drive.adicionar("guia.docx", GUIA)

    relatorio = rodar(dry_run=True)

    assert drive.baixados == [guia.id] and curador.textos == []
    assert fonte(db, guia) is None and db.scalar(select(func.count()).select_from(TrechoDocumento)) == 0
    assert [p.acao for p in relatorio.novas] == ["nova"] and relatorio.estimativa.custo_usd > 0
    execucao = db.get(ExecucaoImportacao, relatorio.execucao_id)
    assert (execucao.origem, execucao.dry_run, execucao.teto_usd) == ("drive", True, None)


def test_teto_de_gasto_para_e_a_proxima_rodada_continua(monkeypatch, rodar, db, drive):
    usar(monkeypatch, CuradorDoDrive(custo=0.5))
    arquivos = [drive.adicionar(f"doc{i}.docx", docx_com(f"# Doc {i}", f"Conteúdo número {i} do documento comercial."),
                                modificado_em=BASE + timedelta(minutes=i)) for i in range(3)]

    primeira = rodar(teto_usd=1.0)

    assert primeira.parou_no_teto and len(primeira.curadas) == 2  # o 3º não cabe: 1,00 gasto + folga > teto
    assert [fonte(db, a).status for a in arquivos] == ["importada", "importada", "a_curar"]
    assert db.get(ExecucaoImportacao, primeira.execucao_id).status == "parou_no_teto"
    usar(monkeypatch, CuradorDoDrive(custo=0.001))
    drive.baixados.clear()

    segunda = rodar(teto_usd=1.0)

    assert [fonte(db, a).status for a in arquivos] == ["importada"] * 3 and drive.baixados == []  # sem baixar de novo
    assert len(segunda.curadas) == 1 and len(itens(db)) == 3


def test_limite_de_arquivos_so_le_os_primeiros_e_avisa(rodar, db, drive, curador):
    for i in range(3):
        drive.adicionar(f"doc{i}.docx", docx_com(f"# Doc {i}", f"Conteúdo número {i} do documento comercial."),
                        modificado_em=BASE + timedelta(minutes=i))

    relatorio = rodar(limite_paginas=2)

    assert relatorio.lidas == 2 and any("incompleta" in a for a in relatorio.avisos)


def test_falha_do_curador_no_documento_nao_grava_nada_e_tenta_de_novo(monkeypatch, rodar, db, drive):
    usar(monkeypatch, CuradorDoDrive(falhar_se=lambda t: True))
    guia = drive.adicionar("guia.docx", GUIA)

    relatorio = rodar()

    assert fonte(db, guia).status == "falha" and itens(db) == [] and len(relatorio.falhas_do_curador) == 1
    assert pedacos(db, guia) != []  # a busca não depende do curador
    usar(monkeypatch, CuradorDoDrive())
    rodar()
    assert fonte(db, guia).status == "importada" and len(itens(db)) == 1


def test_o_log_so_tem_numeros(caplog, rodar, drive, curador):
    caplog.set_level("INFO", logger="app.importacao")
    drive.adicionar("Segredo do Cliente Acme.docx", DOC_COM_DADO)

    rodar()

    log = caplog.text
    assert '"evento": "importacao_drive"' in log
    assert "Acme" not in log and "ana@" not in log and "Segredo" not in log


def test_configurado_exige_pasta_e_credencial(monkeypatch):
    cfg = importacao_drive.settings
    monkeypatch.setattr(cfg, "drive_pasta_id", "pasta")
    monkeypatch.setattr(cfg, "google_service_account_json", "")
    monkeypatch.setattr(cfg, "google_application_credentials", "")
    assert not importacao_drive.configurado()
    monkeypatch.setattr(cfg, "google_application_credentials", "/chave.json")
    assert importacao_drive.configurado()
    monkeypatch.setattr(cfg, "drive_pasta_id", " ")
    assert not importacao_drive.configurado()


def test_sem_chave_do_gemini_so_o_dry_run_roda(monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    with pytest.raises(importacao.FaltaConfiguracao, match="GEMINI_API_KEY"):
        importacao_drive.conferir_configuracao(dry_run=False)
    importacao_drive.conferir_configuracao(dry_run=True)
