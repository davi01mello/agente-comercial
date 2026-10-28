"""LeitorDrive (app/drive.py) com a SessaoFalsa de tests/drive_falso.py: a lista recursiva, a paginação, as novas
tentativas, os erros e o download em blocos. Sem rede e sem Google."""
import json
from datetime import datetime

import pytest

from app import drive
from app.drive import API, ErroDrive, LeitorDrive, ids_das_pastas
from app.extrair_texto import MIME_DOCX, MIME_PDF
from tests.drive_falso import RespostaFalsa, SessaoFalsa, atalho, item, pasta

RAIZ = "raiz123"
GOOGLE_DOC = "application/vnd.google-apps.document"


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    esperas = []
    monkeypatch.setattr(drive, "_dormir", esperas.append)
    return esperas


@pytest.fixture
def sessao():
    return SessaoFalsa()


@pytest.fixture
def leitor(sessao):
    return LeitorDrive(RAIZ, sessao=sessao)


def test_lista_as_subpastas_com_o_caminho_e_o_link(sessao, leitor):
    sessao.pastas[RAIZ] = [[pasta("p1", "Resumo Comercial"), item("a1", "solto.docx", MIME_DOCX)]]
    sessao.pastas["p1"] = [[item("a2", "guia.pdf", MIME_PDF, tamanho=2048, md5="abc"), pasta("p2", "Antigos")]]
    sessao.pastas["p2"] = [[item("a3", "velho.pdf", MIME_PDF)]]

    busca = leitor.arquivos()

    assert busca.completa
    por_id = {a.id: a for a in busca.arquivos}
    assert set(por_id) == {"a1", "a2", "a3"}
    assert por_id["a1"].caminho == () and por_id["a1"].categoria is None
    assert por_id["a2"].caminho == ("Resumo Comercial",) and por_id["a2"].categoria == "Resumo Comercial"
    assert por_id["a3"].categoria == "Resumo Comercial / Antigos"
    assert (por_id["a2"].tamanho, por_id["a2"].md5, por_id["a2"].mime) == (2048, "abc", MIME_PDF)
    assert por_id["a2"].url == "https://drive.google.com/file/d/a2/view"
    assert por_id["a2"].modificado_em == datetime(2026, 10, 13, 7, 59, 22)  # UTC, sem fuso, como o banco guarda


def test_pergunta_pelos_filhos_da_pasta_sem_a_lixeira_e_com_drives_compartilhados(sessao, leitor):
    leitor.arquivos()

    [(url, params)] = sessao.pedidos
    assert url == API
    assert params["q"] == f"'{RAIZ}' in parents and trashed = false"
    assert params["supportsAllDrives"] == "true" and params["includeItemsFromAllDrives"] == "true"


def test_atalhos_ficam_de_fora_e_nao_sao_seguidos(sessao, leitor):
    sessao.pastas[RAIZ] = [[atalho("s1", "atalho"), item("a1", "x.docx", MIME_DOCX)]]

    assert [a.id for a in leitor.arquivos().arquivos] == ["a1"]


def test_pagina_ate_acabar(sessao, leitor):
    sessao.pastas[RAIZ] = [[item("a1", "1.docx", MIME_DOCX)], [item("a2", "2.docx", MIME_DOCX)],
                           [item("a3", "3.docx", MIME_DOCX)]]

    busca = leitor.arquivos()

    assert [a.id for a in busca.arquivos] == ["a1", "a2", "a3"]
    assert [p.get("pageToken") for _, p in sessao.pedidos] == [None, "1", "2"]
    assert leitor.requisicoes == 3


def test_limite_corta_a_lista_e_ela_sai_incompleta(sessao, leitor):
    sessao.pastas[RAIZ] = [[item(f"a{i}", f"{i}.docx", MIME_DOCX) for i in range(5)]]

    busca = leitor.arquivos(limite=2)

    assert [a.id for a in busca.arquivos] == ["a0", "a1"] and not busca.completa


def test_limite_igual_ao_total_nao_marca_incompleta(sessao, leitor):
    sessao.pastas[RAIZ] = [[item("a1", "1.docx", MIME_DOCX), item("a2", "2.docx", MIME_DOCX)]]

    assert leitor.arquivos(limite=2).completa


def test_pasta_dentro_dela_mesma_nao_faz_laco(sessao, leitor):
    sessao.pastas[RAIZ] = [[pasta("p1", "A")]]
    sessao.pastas["p1"] = [[pasta(RAIZ, "volta"), pasta("p1", "ela mesma"), item("a1", "x.docx", MIME_DOCX)]]

    assert [a.id for a in leitor.arquivos().arquivos] == ["a1"]


def test_subpasta_que_nao_abre_deixa_a_lista_incompleta_mas_nao_derruba(sessao, leitor):
    sessao.pastas[RAIZ] = [[pasta("p1", "Fechada"), item("a1", "x.docx", MIME_DOCX)]]
    pedir = sessao.get

    def get(url, params=None, stream=False, timeout=None):
        if "'p1'" in (params or {}).get("q", ""):
            return RespostaFalsa(status=403)  # a raiz responde normal; só a subpasta recusa
        return pedir(url, params, stream, timeout)

    sessao.get = get

    busca = leitor.arquivos()

    assert [a.id for a in busca.arquivos] == ["a1"] and not busca.completa


def test_raiz_sem_acesso_levanta_com_o_que_fazer(sessao, leitor):
    sessao.programadas = [RespostaFalsa(status=403)]

    with pytest.raises(ErroDrive, match="compartilhada com o e-mail da conta de serviço") as erro:
        leitor.arquivos()

    assert erro.value.status == 403


def test_pasta_inexistente_diz_para_conferir_o_id(sessao, leitor):
    sessao.programadas = [RespostaFalsa(status=404)]

    with pytest.raises(ErroDrive, match="DRIVE_PASTA_ID"):
        leitor.arquivos()


def test_429_e_5xx_tentam_de_novo_com_espera_crescente(sessao, leitor, sem_espera):
    sessao.pastas[RAIZ] = [[item("a1", "x.docx", MIME_DOCX)]]
    sessao.programadas = [RespostaFalsa(status=429), RespostaFalsa(status=503), RespostaFalsa(status=500)]

    assert [a.id for a in leitor.arquivos().arquivos] == ["a1"]
    assert sem_espera == [1.0, 2.0, 4.0] and leitor.requisicoes == 4


def test_desiste_depois_de_quatro_tentativas(sessao, leitor):
    sessao.programadas = [RespostaFalsa(status=503)] * 4

    with pytest.raises(ErroDrive, match="erro \\(503\\)"):
        leitor.arquivos()

    assert leitor.requisicoes == 4


def test_rede_que_cai_tenta_de_novo_e_depois_desiste_so_com_o_tipo(sessao, leitor, sem_espera):
    sessao.programadas = [ConnectionError("SEGREDO") for _ in range(4)]

    with pytest.raises(ErroDrive) as erro:
        leitor.arquivos()

    assert "ConnectionError" in str(erro.value) and "SEGREDO" not in str(erro.value)
    assert len(sem_espera) == 3


def test_4xx_nao_tenta_de_novo(sessao, leitor):
    sessao.programadas = [RespostaFalsa(status=400)]

    with pytest.raises(ErroDrive):
        leitor.arquivos()

    assert leitor.requisicoes == 1


# --- baixar --------------------------------------------------------------------------------------------------

def arquivo_do_drive(sessao, leitor, mime=MIME_PDF, conteudo=b"x"):
    sessao.pastas[RAIZ] = [[item("a1", "doc", mime)]]
    sessao.corpos["a1"] = conteudo
    sessao.corpos["a1/export"] = conteudo
    return leitor.arquivos().arquivos[0]


def test_baixa_em_blocos_para_o_disco_e_fecha_a_resposta(sessao, leitor, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "BLOCO", 4)
    arquivo = arquivo_do_drive(sessao, leitor, conteudo=b"0123456789")

    leitor.baixar(arquivo, tmp_path / "saida")

    assert (tmp_path / "saida").read_bytes() == b"0123456789"
    url, params = sessao.pedidos[-1]
    assert url == f"{API}/a1" and params["alt"] == "media" and params["supportsAllDrives"] == "true"


def test_documento_do_google_e_exportado_como_texto(sessao, leitor, tmp_path):
    arquivo = arquivo_do_drive(sessao, leitor, mime=GOOGLE_DOC, conteudo="Olá".encode())

    leitor.baixar(arquivo, tmp_path / "saida")

    url, params = sessao.pedidos[-1]
    assert url == f"{API}/a1/export" and params == {"mimeType": "text/plain"}
    assert (tmp_path / "saida").read_bytes() == "Olá".encode()


def test_planilha_do_google_e_exportada_como_csv(sessao, leitor, tmp_path):
    arquivo = arquivo_do_drive(sessao, leitor, mime="application/vnd.google-apps.spreadsheet")

    leitor.baixar(arquivo, tmp_path / "saida")

    assert sessao.pedidos[-1][1] == {"mimeType": "text/csv"}


def test_download_com_erro_levanta(sessao, leitor, tmp_path):
    arquivo = arquivo_do_drive(sessao, leitor)
    sessao.programadas = [RespostaFalsa(status=404)]

    with pytest.raises(ErroDrive):
        leitor.baixar(arquivo, tmp_path / "saida")

    assert not (tmp_path / "saida").exists()


# --- configuração --------------------------------------------------------------------------------------------

def test_sem_pasta_no_env_diz_qual_variavel_falta(monkeypatch):
    monkeypatch.setattr(drive.settings, "drive_pasta_id", "")

    with pytest.raises(ErroDrive, match="DRIVE_PASTA_ID"):
        LeitorDrive(sessao=SessaoFalsa())


def test_sem_credencial_diz_as_duas_variaveis(monkeypatch):
    monkeypatch.setattr(drive.settings, "google_service_account_json", "")
    monkeypatch.setattr(drive.settings, "google_application_credentials", "")

    with pytest.raises(ErroDrive, match="GOOGLE_APPLICATION_CREDENTIALS.*GOOGLE_SERVICE_ACCOUNT_JSON"):
        LeitorDrive(RAIZ)


def test_credencial_ilegivel_nao_vaza_pedaco_da_chave():
    with pytest.raises(ErroDrive) as erro:
        LeitorDrive(RAIZ, credenciais_json='{"private_key": "SEGREDO-DA-CHAVE", ')

    assert "JSON da conta de serviço" in str(erro.value) and "SEGREDO" not in str(erro.value)


def test_credencial_por_arquivo_que_nao_existe():
    with pytest.raises(ErroDrive, match="FileNotFoundError"):
        LeitorDrive(RAIZ, caminho_credenciais="/nao/existe/chave.json")


def test_credencial_json_sem_os_campos_da_conta_de_servico():
    with pytest.raises(ErroDrive, match="MalformedError"):
        LeitorDrive(RAIZ, credenciais_json=json.dumps({"type": "service_account"}))


# --- várias pastas ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("abc", ["abc"]),
    (" abc , def;ghi\njkl ", ["abc", "def", "ghi", "jkl"]),
    ("abc,abc", ["abc"]),
    ("https://drive.google.com/drive/folders/1y0tQ5PAy?usp=sharing", ["1y0tQ5PAy"]),
    ("https://drive.google.com/drive/u/0/folders/0AJv7Ehj", ["0AJv7Ehj"]),
    ("", []),
    ("  ,  ", []),
])
def test_ids_das_pastas_aceita_varios_e_o_endereco_inteiro(texto, esperado):
    assert ids_das_pastas(texto) == esperado


def test_varias_pastas_as_extras_levam_o_nome_na_categoria(sessao):
    sessao.pastas[RAIZ] = [[item("a1", "principal.docx", MIME_DOCX), pasta("p1", "Resumo Comercial")]]
    sessao.pastas["p1"] = [[item("a2", "dentro.docx", MIME_DOCX)]]
    sessao.pastas["extra"] = [[item("b1", "objecoes.docx", MIME_DOCX), pasta("p9", "Consultoria")]]
    sessao.pastas["p9"] = [[item("b2", "guia.docx", MIME_DOCX)]]
    sessao.nomes["extra"] = "Conhecimento"
    leitor = LeitorDrive(f"{RAIZ}, extra", sessao=sessao)

    busca = leitor.arquivos()

    assert busca.completa
    categorias = {a.id: a.categoria for a in busca.arquivos}
    assert categorias == {
        "a1": None, "a2": "Resumo Comercial", "b1": "Conhecimento", "b2": "Conhecimento / Consultoria",
    }


def test_arquivo_alcancado_por_duas_pastas_entra_uma_vez(sessao):
    sessao.pastas[RAIZ] = [[item("igual", "x.docx", MIME_DOCX)]]
    sessao.pastas["extra"] = [[item("igual", "x.docx", MIME_DOCX), item("outro", "y.docx", MIME_DOCX)]]
    sessao.nomes["extra"] = "Outra"

    busca = LeitorDrive(f"{RAIZ},extra", sessao=sessao).arquivos()

    assert sorted(a.id for a in busca.arquivos) == ["igual", "outro"]


def test_pasta_extra_sem_acesso_so_deixa_a_busca_incompleta(sessao):
    sessao.pastas[RAIZ] = [[item("a1", "ok.docx", MIME_DOCX)]]  # "extra" não tem nome: o 404 da fake

    busca = LeitorDrive(f"{RAIZ},extra", sessao=sessao).arquivos()

    assert [a.id for a in busca.arquivos] == ["a1"]
    assert busca.completa is False


def test_pasta_principal_sem_acesso_derruba_tudo(sessao):
    sessao.programadas = [RespostaFalsa(json={"name": "Extra"}), RespostaFalsa(status=404)]  # o nome, e a lista da 1ª

    with pytest.raises(ErroDrive, match="404"):
        LeitorDrive(f"{RAIZ},extra", sessao=sessao).arquivos()


# --- vídeos e arquivos velhos ficam de fora ----------------------------------------------------------------------

def test_video_nao_entra_na_lista_nem_por_tipo_nem_por_extensao(sessao, leitor):
    sessao.pastas[RAIZ] = [[
        item("v1", "case.mp4", "video/mp4"),
        item("v2", "reuniao.MOV", "application/octet-stream"),  # o Drive às vezes não sabe o tipo: vale a extensão
        item("d1", "guia.docx", MIME_DOCX),
    ]]

    busca = leitor.arquivos()

    assert [a.id for a in busca.arquivos] == ["d1"]
    assert busca.videos_ignorados == 2
    assert busca.completa  # ignorar vídeo não deixa a lista "incompleta": o que sumiu continua sendo conferido


def test_corte_por_idade_tira_o_arquivo_velho_e_conta(sessao, leitor, monkeypatch):
    monkeypatch.setattr(drive.settings, "drive_idade_max_anos", 3)
    agora = datetime.now(drive.UTC)
    recente = agora.replace(year=agora.year - 1).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    velho = agora.replace(year=agora.year - 5).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sessao.pastas[RAIZ] = [[
        item("novo", "recente.docx", MIME_DOCX, modificado=recente),
        item("velho", "antigo.docx", MIME_DOCX, modificado=velho),
    ]]

    busca = leitor.arquivos()

    assert [a.id for a in busca.arquivos] == ["novo"]
    assert busca.antigos_ignorados == 1


def test_sem_corte_configurado_arquivo_antigo_entra(sessao, leitor):
    sessao.pastas[RAIZ] = [[item("velho", "antigo.docx", MIME_DOCX, modificado="2018-05-01T10:00:00.000Z")]]

    busca = leitor.arquivos()

    assert [a.id for a in busca.arquivos] == ["velho"] and busca.antigos_ignorados == 0
