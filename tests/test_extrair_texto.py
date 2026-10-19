"""Extração de texto dos arquivos do Drive (app/extrair_texto.py), nos formatos de verdade (docx, PDF, xlsx...)
gerados em memória por tests/drive_falso.py. Sem rede e sem modelo."""
import pytest

from app import extrair_texto as e
from tests.drive_falso import docx_com, pdf_com, xlsx_com


def arquivo(tmp_path, conteudo: bytes):
    caminho = tmp_path / "arquivo"
    caminho.write_bytes(conteudo)
    return caminho


def test_docx_mantem_titulos_listas_tabelas_e_a_ordem(tmp_path):
    caminho = arquivo(tmp_path, docx_com(
        "# O que eu ensinaria", "## Prospecção", "Filtrar o ICP no Lusha. [Experiência]", "- Ligar na segunda",
        "| Pergunta | Onde rendeu |", "Fim do documento",
    ))

    texto = e.extrair(caminho, e.MIME_DOCX)

    assert texto.splitlines()[0] == "# O que eu ensinaria"
    assert "## Prospecção" in texto and "- Ligar na segunda" in texto
    assert "| Pergunta | Onde rendeu |" in texto
    assert texto.index("## Prospecção") < texto.index("Filtrar o ICP") < texto.index("Ligar na segunda") \
        < texto.index("| Pergunta") < texto.index("Fim do documento")


def test_docx_celula_mesclada_aparece_uma_vez(tmp_path):
    caminho = arquivo(tmp_path, docx_com("| mesma | mesma |"))

    assert e.extrair(caminho, e.MIME_DOCX) == "| mesma |"


def test_pdf_devolve_o_texto_com_acentos(tmp_path):
    caminho = arquivo(tmp_path, pdf_com("Negociação e objeções", "Reforço a reciprocidade [faço sempre]"))

    texto = e.extrair(caminho, e.MIME_PDF)

    assert "Negociação e objeções" in texto and "[faço sempre]" in texto


def test_pdf_de_imagem_nao_tem_texto(tmp_path):
    """Sem camada de texto (slides exportados como imagem): o texto sai vazio e quem chama marca a fonte `vazia`."""
    assert e.extrair(arquivo(tmp_path, pdf_com()), e.MIME_PDF) == ""


def test_xlsx_vira_uma_linha_por_linha_da_planilha_com_o_nome_da_aba(tmp_path):
    caminho = arquivo(tmp_path, xlsx_com([["Empresa", "Atendeu"], ["Acme", "Sim"], [None, None], ["Beta", None]]))

    assert e.extrair(caminho, e.MIME_XLSX) == "## Página1\n\nEmpresa | Atendeu\nAcme | Sim\nBeta"


def test_csv_e_o_documento_do_google_exportado(tmp_path):
    caminho = arquivo(tmp_path, "nome;valor\nx;1\n".replace(";", ",").encode())

    assert e.extrair(caminho, "text/csv") == "nome | valor\nx | 1"
    assert e.extrair(caminho, e.MIME_GOOGLE_PLANILHA) == "nome | valor\nx | 1"


@pytest.mark.parametrize("mime", ["text/plain", "text/markdown", "application/vnd.google-apps.document",
                                  "application/vnd.google-apps.presentation"])
def test_texto_puro_markdown_e_documentos_google(tmp_path, mime):
    assert e.extrair(arquivo(tmp_path, "﻿Olá,\r\n\r\n\r\n\r\nmundo  \n".encode()), mime) == "Olá,\n\nmundo"


def test_limpeza_tira_espacos_de_enchimento_e_linhas_em_branco_demais(tmp_path):
    caminho = arquivo(tmp_path, ("um" + " " * 40 + "dois\n\n\n\n\ntrês\xa0quatro").encode())

    assert e.extrair(caminho, "text/plain") == "um dois\n\ntrês quatro"


def test_texto_muito_grande_e_cortado(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "MAX_CARACTERES", 50)

    assert len(e.extrair(arquivo(tmp_path, b"x" * 500), "text/plain")) == 50


def test_pdf_para_de_ler_quando_passa_do_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "MAX_CARACTERES", 20)

    texto = e.extrair(arquivo(tmp_path, pdf_com("uma linha de texto bem longa aqui")), e.MIME_PDF)

    assert texto == "uma linha de texto b"


@pytest.mark.parametrize("mime", [e.MIME_DOCX, e.MIME_PDF, e.MIME_XLSX])
def test_arquivo_corrompido_levanta_erro_so_com_o_tipo(tmp_path, mime):
    caminho = arquivo(tmp_path, b"isto nao e um arquivo SEGREDO-DO-CLIENTE")

    with pytest.raises(e.ErroDeLeitura) as erro:
        e.extrair(caminho, mime)

    assert "SEGREDO" not in str(erro.value)  # a mensagem da biblioteca pode ter texto do arquivo: só o tipo sobe


def test_formato_nao_suportado(tmp_path):
    with pytest.raises(e.ErroDeLeitura, match="formato não suportado"):
        e.extrair(arquivo(tmp_path, b"x"), "image/png")


def test_quais_formatos_sao_suportados_e_quais_sao_planilha():
    assert e.suportado(e.MIME_PDF) and e.suportado(e.MIME_DOCX) and not e.suportado("image/png")
    assert e.e_planilha(e.MIME_XLSX) and e.e_planilha("text/csv") and not e.e_planilha(e.MIME_DOCX)
