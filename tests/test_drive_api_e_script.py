"""O Drive pelas três portas: POST /fontes/sincronizar (origem "drive"), o scripts/sincronizar_drive.py e a rodada
agendada (app/agendador.py), mais o /chat com os documentos achados pela busca. Tudo com o DriveFalso e o curador
falso."""
import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import agendador, importacao, importacao_drive, llm, main
from app.db import SessionLocal
from app.main import app, leitor_drive
from app.models import ExecucaoImportacao, Fonte, Insight, TrechoDocumento
from scripts import sincronizar_drive
from tests.drive_falso import DriveFalso, docx_com, pdf_com
from tests.notion_falso import limpar_banco_da_importacao
from tests.test_curadoria_notion import usar
from tests.test_importacao_drive import GUIA, CuradorDoDrive


@pytest.fixture(autouse=True)
def banco_limpo(monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "chave-de-teste")  # nunca a do .env: o curador é o falso
    usar(monkeypatch, CuradorDoDrive())
    with SessionLocal() as db:
        limpar_banco_da_importacao(db)
    yield
    with SessionLocal() as db:
        limpar_banco_da_importacao(db)


@pytest.fixture
def drive():
    falso = DriveFalso()
    falso.adicionar("guia.docx", GUIA, caminho=("Resumo Comercial",))
    return falso


@pytest.fixture
def client(drive):
    app.dependency_overrides[leitor_drive] = lambda: drive
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(leitor_drive, None)


def contar(modelo, *filtros) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(modelo).where(*filtros))


# --- POST /fontes/sincronizar ----------------------------------------------------------------------------------

def test_sincronizar_o_drive_pela_api(client):
    r = client.post("/fontes/sincronizar", json={"origem": "drive"})

    assert r.status_code == 202
    with SessionLocal() as db:
        e = db.get(ExecucaoImportacao, r.json()["execucao_id"])
        assert (e.origem, e.status, e.paginas_lidas, e.paginas_curadas, e.teto_usd) == ("drive", "concluida", 1, 1, 1.0)
    assert contar(Fonte, Fonte.origem == "drive") == 1 and contar(Insight, Insight.fonte == "drive") == 1
    assert contar(TrechoDocumento) >= 1


def test_a_execucao_do_drive_diz_a_origem_e_o_resumo_separa_por_origem(client):
    r = client.post("/fontes/sincronizar", json={"origem": "drive", "limite_paginas": 1})

    detalhe = client.get(f"/fontes/execucoes/{r.json()['execucao_id']}").json()
    resumo = client.get("/fontes/resumo").json()

    assert detalhe["origem"] == "drive"
    assert resumo["por_origem"] == {"drive": 1}
    assert resumo["ultima_execucao"]["origem"] == "drive"
    assert list(resumo["ultima_por_origem"]) == ["drive"]


def test_a_lista_de_fontes_traz_a_categoria_e_filtra_por_origem(client):
    client.post("/fontes/sincronizar", json={"origem": "drive"})

    [fonte] = client.get("/fontes", params={"origem": "drive"}).json()["itens"]

    assert (fonte["titulo"], fonte["categoria"], fonte["status"]) == ("guia", "Resumo Comercial", "importada")
    assert client.get("/fontes", params={"origem": "notion"}).json()["total"] == 0


def test_o_drive_nao_exige_o_token_do_notion(client, monkeypatch):
    monkeypatch.setattr("app.notion.settings.notion_token", "")

    assert client.post("/fontes/sincronizar", json={"origem": "drive", "dry_run": True}).status_code == 202


def test_sem_configuracao_do_drive_vira_503_com_o_que_falta(monkeypatch):
    monkeypatch.setattr("app.drive.settings.drive_pasta_id", "")
    with TestClient(app) as c:
        r = c.post("/fontes/sincronizar", json={"origem": "drive"})

    assert r.status_code == 503 and "DRIVE_PASTA_ID" in r.json()["detail"]
    assert contar(ExecucaoImportacao) == 0


def test_409_com_uma_importacao_do_notion_rodando(client):
    with SessionLocal() as db:
        db.add(ExecucaoImportacao(inicio=importacao._agora(), status="rodando", origem="notion"))
        db.commit()

    r = client.post("/fontes/sincronizar", json={"origem": "drive"})

    assert r.status_code == 409


def test_download_que_falha_conta_como_falha_na_execucao(client, drive, caplog):
    drive.falhar_download.add("arq001")
    caplog.set_level("INFO")

    r = client.post("/fontes/sincronizar", json={"origem": "drive"})

    assert client.get(f"/fontes/execucoes/{r.json()['execucao_id']}").json()["contagens"]["falhas"] == 1


# --- o script ---------------------------------------------------------------------------------------------------

def rodar_script(drive, capsys, *args) -> tuple[int, str, str]:
    codigo = sincronizar_drive.main(list(args), leitor=drive)
    saida = capsys.readouterr()
    return codigo, saida.out, saida.err


def test_script_sincroniza_e_imprime_o_relatorio(drive, capsys):
    codigo, saida, _ = rodar_script(drive, capsys)

    assert codigo == 0
    assert "Importação do Drive: execução #" in saida
    assert "Arquivos lidas: 1 · novas: 1" in saida and "Requisições ao Drive:" in saida
    assert "Curador: 1 arquivos, 1 itens propostos" in saida
    assert contar(Insight, Insight.fonte == "drive") == 1


def test_script_dry_run_estima_o_custo_e_nao_grava(drive, capsys):
    codigo, saida, _ = rodar_script(drive, capsys, "--dry-run")

    assert codigo == 0 and "SIMULAÇÃO (--dry-run" in saida and "Custo estimado do curador: US$" in saida
    assert "por arquivo)" in saida
    assert contar(Fonte) == 0


def test_script_lista_o_que_ficou_so_na_busca(drive, capsys):
    from tests.drive_falso import xlsx_com
    drive.adicionar("contatos.xlsx", xlsx_com([["Empresa", "Setor"], ["Acme", "Indústria e agronegócio"]]))

    _, saida, _ = rodar_script(drive, capsys)

    assert "Só na busca, não vão ao curador (1):" in saida and "contatos" in saida


def test_script_limite_de_arquivos_e_teto(drive, capsys):
    drive.adicionar("outro.docx", docx_com("# Outro", "Conteúdo diferente do primeiro documento da pasta."))

    _, saida, _ = rodar_script(drive, capsys, "--limite-arquivos", "1", "--teto-usd", "0,50")

    assert "Arquivos lidas: 1" in saida and "(teto: US$ 0,50)" in saida
    assert "A lista de arquivos veio incompleta" in saida


@pytest.mark.parametrize("opcao", [["--limite-arquivos", "0"], ["--teto-usd", "0"], ["--teto-usd", "nan"]])
def test_script_recusa_opcao_invalida(drive, capsys, opcao):
    with pytest.raises(SystemExit):
        sincronizar_drive.main(opcao, leitor=drive)


def test_script_sem_chave_do_gemini_so_o_dry_run_roda(drive, capsys, monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    codigo, _, erro = rodar_script(drive, capsys)

    assert codigo == 1 and "Falta GEMINI_API_KEY" in erro and contar(ExecucaoImportacao) == 0
    assert rodar_script(drive, capsys, "--dry-run")[0] == 0


def test_script_sem_configuracao_do_drive_diz_o_que_falta(capsys, monkeypatch):
    monkeypatch.setattr("app.drive.settings.drive_pasta_id", "")

    codigo = sincronizar_drive.main([])

    assert codigo == 1 and "DRIVE_PASTA_ID" in capsys.readouterr().err


def test_script_erro_inesperado_nao_mostra_a_mensagem(drive, capsys, monkeypatch):
    def quebrar(*args, **kwargs):
        raise RuntimeError("texto do documento SEGREDO")

    monkeypatch.setattr(importacao_drive, "executar", quebrar)

    codigo, _, erro = rodar_script(drive, capsys)

    assert codigo == 2 and "RuntimeError" in erro and "SEGREDO" not in erro


# --- a rodada agendada -------------------------------------------------------------------------------------------

@pytest.fixture
def configurado(monkeypatch, drive):
    monkeypatch.setattr(importacao_drive.settings, "drive_pasta_id", "pasta")
    monkeypatch.setattr(importacao_drive.settings, "google_application_credentials", "/chave.json")
    monkeypatch.setattr(agendador, "LeitorDrive", lambda: drive)


def test_rodada_agendada_sincroniza_e_registra_a_execucao(configurado):
    execucao_id = agendador.rodar_uma_vez(threading.Lock())

    with SessionLocal() as db:
        e = db.get(ExecucaoImportacao, execucao_id)
        assert (e.origem, e.status, e.teto_usd) == ("drive", "concluida", agendador.settings.drive_sync_teto_usd)
    assert contar(Insight, Insight.fonte == "drive") == 1


def test_rodada_agendada_seguinte_e_barata_nada_mudou(configurado, drive):
    agendador.rodar_uma_vez(threading.Lock())
    drive.baixados.clear()

    execucao_id = agendador.rodar_uma_vez(threading.Lock())

    assert drive.baixados == []
    with SessionLocal() as db:
        assert db.get(ExecucaoImportacao, execucao_id).paginas_novas == 0


def test_rodada_agendada_sem_drive_configurado_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(importacao_drive.settings, "drive_pasta_id", "")

    assert agendador.rodar_uma_vez(threading.Lock()) is None and contar(ExecucaoImportacao) == 0


def test_rodada_agendada_sem_chave_do_gemini_so_avisa(configurado, monkeypatch, caplog):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    assert agendador.rodar_uma_vez(threading.Lock()) is None
    assert "sync_drive_agendada_sem_configuracao" in caplog.text


def test_rodada_agendada_pula_se_ja_ha_sincronizacao_rodando(configurado):
    with SessionLocal() as db:
        db.add(ExecucaoImportacao(inicio=importacao._agora(), status="rodando", origem="notion"))
        db.commit()

    assert agendador.rodar_uma_vez(threading.Lock()) is None and contar(Fonte) == 0


def test_rodada_agendada_que_quebra_fica_como_erro_e_nao_derruba_o_laco(configurado, drive, caplog):
    drive.falhar_download.add("arq001")  # o arquivo vira "falha", a execução termina: simula o caso comum
    assert agendador.rodar_uma_vez(threading.Lock()) is not None

    def quebrar(*args, **kwargs):
        raise RuntimeError("SEGREDO")

    import app.importacao_drive as modulo
    original = modulo.executar
    modulo.executar = quebrar
    try:
        execucao_id = agendador.rodar_uma_vez(threading.Lock())
    finally:
        modulo.executar = original

    assert execucao_id is not None
    assert "sync_drive_agendada_falhou" in caplog.text and "SEGREDO" not in caplog.text


def test_o_laco_dorme_roda_e_dorme_de_novo(monkeypatch):
    chamadas, esperas = [], []

    async def dormir(segundos):
        esperas.append(segundos)
        if len(esperas) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(agendador.asyncio, "sleep", dormir)
    monkeypatch.setattr(agendador, "rodar_uma_vez", lambda trava: chamadas.append(trava))
    monkeypatch.setattr(agendador.settings, "drive_sync_intervalo_min", 15)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agendador.laco("trava"))

    assert esperas == [agendador.PRIMEIRA_ESPERA_S, 900, 900] and chamadas == ["trava", "trava"]


def test_o_servidor_so_liga_o_agendador_com_intervalo(monkeypatch):
    iniciados = []

    async def laco_falso(trava):
        iniciados.append(trava)

    monkeypatch.setattr(main.agendador, "laco", laco_falso)
    monkeypatch.setattr(main.settings, "drive_sync_intervalo_min", 0)
    with TestClient(app):
        pass
    assert iniciados == []

    monkeypatch.setattr(main.settings, "drive_sync_intervalo_min", 15)
    with TestClient(app):
        pass
    assert iniciados == [main._uma_sincronizacao_por_vez]


# --- /chat com documentos -----------------------------------------------------------------------------------------

def test_o_chat_manda_ao_consultor_os_documentos_achados_e_devolve_os_ids(client, monkeypatch):
    client.post("/fontes/sincronizar", json={"origem": "drive"})
    recebido = {}

    def consultar(mensagem, historico, base, documentos=""):
        recebido["documentos"] = documentos
        return "Peça uma parcela só [DOC-1]."

    monkeypatch.setattr(llm, "consultar", consultar)

    r = client.post("/chat", json={"mensagem": "o cliente pediu desconto na negociação, o que faço?"})

    [doc] = r.json()["documentos"]
    assert doc["titulo"] == "guia" and doc["categoria"] == "Resumo Comercial" and doc["url"].startswith("https://drive")
    assert f"[DOC-{doc['id']}] guia | pasta: Resumo Comercial" in recebido["documentos"]
    assert "reduzo o escopo" in recebido["documentos"]
    assert r.json()["resposta"] == "Peça uma parcela só [DOC-1]."


def test_o_chat_sem_documento_parecido_nao_manda_nada(client, monkeypatch):
    client.post("/fontes/sincronizar", json={"origem": "drive"})
    recebido = {}

    def consultar(mensagem, historico, base, documentos=""):
        recebido["documentos"] = documentos
        return "A base não cobre isso."

    monkeypatch.setattr(llm, "consultar", consultar)

    r = client.post("/chat", json={"mensagem": "como funciona a tributação de energia solar?"})

    assert recebido["documentos"] == "" and r.json()["documentos"] == []


def test_o_chat_acha_pelo_assunto_da_conversa_anterior(client, monkeypatch):
    client.post("/fontes/sincronizar", json={"origem": "drive"})
    recebido = {}

    def consultar(mensagem, historico, base, documentos=""):
        recebido["documentos"] = documentos
        return "ok"

    monkeypatch.setattr(llm, "consultar", consultar)
    historico = [{"role": "user", "text": "como respondo a desconto na negociação?"},
                 {"role": "model", "text": "Peça uma parcela [DOC-1]."}]

    client.post("/chat", json={"mensagem": "e se ele insistir?", "historico": historico})

    assert "[DOC-" in recebido["documentos"]  # "e se ele insistir?" sozinho não acharia nada


def test_so_pdf_de_imagem_ou_removido_nao_aparece_no_chat(client, drive, monkeypatch):
    drive.adicionar("slides.pdf", pdf_com())
    client.post("/fontes/sincronizar", json={"origem": "drive"})
    monkeypatch.setattr(llm, "consultar", lambda m, h, b, d="": "x")

    assert client.post("/chat", json={"mensagem": "slides"}).json()["documentos"] == []
