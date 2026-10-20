"""Anexo no chat vira fonte (POST /fontes/anexo, T7). Sem Gemini: o curador é o falso do test_curador.

A resposta do POST sai com a fonte `a_curar`; o curador roda depois, em segundo plano (o TestClient espera ele terminar
antes de devolver o controle ao teste), e o resultado se vê em GET /fontes/{id}."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import anexos, busca, llm
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Fonte, HistoricoStatus, Insight, TrechoDocumento
from tests.drive_falso import docx_com, xlsx_com
from tests.test_curador import CuradorFalso, proposta, usar


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def curador(monkeypatch):
    return usar(monkeypatch, CuradorFalso(proposta()))


def texto_unico(*extra: str) -> str:
    """Cada teste anexa um texto só dele: o banco é compartilhado e o mesmo texto é deduplicado."""
    return " ".join([f"Marca {uuid.uuid4().hex}.", "Quando pedem desconto, ofereço parcela única ou menos escopo.",
                     *extra])


def anexar(client, conteudo: bytes | str, nome="aprendizado.txt"):
    if isinstance(conteudo, str):
        conteudo = conteudo.encode()
    return client.post("/fontes/anexo", files={"arquivo": (nome, conteudo)})


# --- o caminho feliz ------------------------------------------------------------------------------

def test_anexo_de_texto_vira_fonte_buscavel_e_curada(client, curador):
    texto = texto_unico("A diretoria decide sozinha.")

    r = anexar(client, texto, "Nota de reunião.txt")

    assert r.status_code == 201
    j = r.json()
    fonte = j["fonte"]
    assert (fonte["origem"], fonte["status"], fonte["titulo"]) == ("upload", "a_curar", "Nota de reunião")
    assert fonte["categoria"] == "Anexo de Rafael"
    assert j["curando"] is True and j["ja_existia"] is False
    assert j["documento"] == {"id": fonte["id"], "titulo": "Nota de reunião", "url": f"/fontes/{fonte['id']}/texto",
                              "categoria": "Anexo de Rafael"}
    depois = client.get(f"/fontes/{fonte['id']}").json()
    assert depois["status"] == "importada"
    assert depois["itens"] == {"historico_a_validar": 1}  # entrou na Fila, nunca direto na base
    assert "Anexo do chat: Nota de reunião" in curador.curar_chamadas[0]["texto"]

    with SessionLocal() as db:
        item = db.scalar(select(Insight).where(Insight.fonte_ref == fonte["url"]))
        assert (item.fonte, item.autor, item.status) == ("upload", "anexo no chat", "historico_a_validar")
        historico = db.scalar(select(HistoricoStatus).where(HistoricoStatus.insight_id == item.id))
        assert historico.motivo == "Importado de um anexo"  # sem "(execução #n)": o anexo não tem execução

    busca.limpar_cache()
    with SessionLocal() as db:
        achados = busca.buscar(db, "desconto parcela única diretoria")
    assert fonte["id"] in [a.fonte_id for a in achados]  # o consultor acha o anexo (como [DOC-n])


def test_o_texto_do_anexo_e_o_link_do_doc(client, curador):
    texto = texto_unico()
    fonte = anexar(client, texto, "guia.md").json()["fonte"]

    r = client.get(f"/fontes/{fonte['id']}/texto")

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert texto in r.text and r.text.startswith("guia")


def test_docx_e_lido_de_verdade(client, curador):
    marca = uuid.uuid4().hex
    arquivo = docx_com("# Playbook", "## Negociação", f"Parcela única funciona. {marca}")

    j = anexar(client, arquivo, "Playbook.docx").json()

    assert j["fonte"]["status"] == "a_curar"
    assert client.get(f"/fontes/{j['fonte']['id']}").json()["status"] == "importada"
    assert marca in curador.curar_chamadas[0]["texto"]


def test_mesmo_texto_de_novo_devolve_a_fonte_que_ja_existe(client, curador):
    texto = texto_unico()
    primeira = anexar(client, texto, "a.txt").json()

    segunda = anexar(client, texto, "b.txt").json()

    assert segunda["ja_existia"] is True and segunda["curando"] is False
    assert segunda["fonte"]["id"] == primeira["fonte"]["id"]
    assert len(curador.curar_chamadas) == 1  # não gastou o modelo de novo


# --- a triagem ------------------------------------------------------------------------------------

def test_dado_pessoal_barra_tudo_e_nada_e_guardado(client, curador):
    j = anexar(client, texto_unico("Fale com ana@hotelx.com.br ou 11 98888-7777.")).json()

    fonte = j["fonte"]
    assert fonte["status"] == "pulada_dado_pessoal"
    assert "e-mail" in fonte["motivo"] and "ana@hotelx" not in fonte["motivo"]
    assert j["documento"] is None and j["curando"] is False and "dado pessoal" in j["aviso"]
    assert curador.curar_chamadas == []
    with SessionLocal() as db:
        f = db.get(Fonte, fonte["id"])
        assert f.markdown is None  # o texto com dado pessoal não fica no banco
        assert db.scalar(select(TrechoDocumento).where(TrechoDocumento.fonte_id == f.id)) is None
    assert client.get(f"/fontes/{fonte['id']}/texto").status_code == 404


def test_dado_pessoal_no_nome_do_arquivo_nao_vira_titulo(client, curador):
    j = anexar(client, texto_unico(), "contato ana@hotelx.com.br.txt").json()

    assert "ana@" not in j["fonte"]["titulo"]


def test_planilha_fica_so_na_busca(client, curador):
    marca = uuid.uuid4().hex
    arquivo = xlsx_com([["cliente", "segmento"], [marca, "hotelaria"], ["Outra", "varejo"]])

    j = anexar(client, arquivo, "clientes.xlsx").json()

    assert j["fonte"]["status"] == "so_busca" and j["curando"] is False and j["documento"]
    assert curador.curar_chamadas == []
    with SessionLocal() as db:
        assert db.scalar(select(TrechoDocumento).where(TrechoDocumento.fonte_id == j["fonte"]["id"])) is not None


def test_texto_muito_longo_fica_so_na_busca(client, curador, monkeypatch):
    monkeypatch.setattr(anexos, "MAX_TRECHOS_NO_CURADOR", 0)

    j = anexar(client, texto_unico()).json()

    assert j["fonte"]["status"] == "so_busca" and "limite" in j["fonte"]["motivo"]
    assert curador.curar_chamadas == []


def test_arquivo_sem_texto_vira_vazia(client, curador):
    j = anexar(client, f"# {uuid.uuid4().hex[:4]}").json()

    assert j["fonte"]["status"] == "vazia" and j["documento"] is None


# --- arquivos que não servem ----------------------------------------------------------------------

@pytest.mark.parametrize("nome, conteudo, status, trecho_da_mensagem", [
    ("virus.exe", b"MZ....", 422, "Formato não suportado"),
    ("sem-extensao", b"texto qualquer", 422, "Formato não suportado"),
    ("vazio.txt", b"", 422, "vazio"),
    ("quebrado.docx", b"isto nao e um zip", 422, "Não consegui ler"),
    ("quebrado.pdf", b"isto nao e um pdf", 422, "Não consegui ler"),
])
def test_arquivo_que_nao_serve_vira_erro_claro(client, curador, nome, conteudo, status, trecho_da_mensagem):
    r = anexar(client, conteudo, nome)

    assert r.status_code == status and trecho_da_mensagem in r.json()["detail"]
    assert curador.curar_chamadas == []


def test_arquivo_grande_demais_vira_413(client, curador, monkeypatch):
    monkeypatch.setattr(anexos, "MAX_BYTES", 100)

    r = anexar(client, "x" * 500)

    assert r.status_code == 413


def test_zip_que_explode_ao_abrir_e_recusado(client, curador, monkeypatch):
    monkeypatch.setattr(anexos, "MAX_DESCOMPACTADO", 10)

    r = anexar(client, docx_com("# Título", "um parágrafo qualquer"), "bomba.docx")

    assert r.status_code == 422 and "grande demais" in r.json()["detail"]


def test_sem_arquivo_no_corpo_vira_422(client, curador):
    assert client.post("/fontes/anexo", data={}).status_code == 422


# --- falha do curador e nova tentativa ---------------------------------------------------------------

def test_curador_que_falha_deixa_a_fonte_em_falha_e_a_nova_tentativa_resolve(client, monkeypatch):
    def quebra(*a, **k):
        raise llm.ErroLLM("Gemini fora do ar")

    monkeypatch.setattr(llm, "curar", quebra)
    j = anexar(client, texto_unico()).json()
    fonte_id = j["fonte"]["id"]
    assert client.get(f"/fontes/{fonte_id}").json()["status"] == "falha"
    assert client.get(f"/fontes/{fonte_id}").json()["itens"] == {}

    usar(monkeypatch, CuradorFalso(proposta()))
    r = client.post(f"/fontes/{fonte_id}/curar")

    assert r.status_code == 202
    assert client.get(f"/fontes/{fonte_id}").json()["status"] == "importada"
    assert client.post(f"/fontes/{fonte_id}/curar").status_code == 409  # já curada: nada a fazer


def test_curar_de_fonte_que_nao_e_anexo_ou_nao_existe_vira_404(client, curador):
    with SessionLocal() as db:
        outra = Fonte(origem="drive", id_externo=f"d-{uuid.uuid4().hex}", titulo="x", url="https://drive/x",
                      hash_conteudo="h", editado_em=anexos.importacao._agora(),
                      importado_em=anexos.importacao._agora(), status="a_curar", markdown="texto")
        db.add(outra)
        db.commit()
        outra_id = outra.id

    assert client.post(f"/fontes/{outra_id}/curar").status_code == 404
    assert client.get(f"/fontes/{outra_id}/texto").status_code == 404
    assert client.post("/fontes/99999999/curar").status_code == 404
    assert client.get("/fontes/99999999").status_code == 404


def test_curar_nao_levanta_nem_toca_fonte_que_nao_e_anexo():
    anexos.curar(99999999)  # não existe: volta quieto


# --- login e a lista de fontes -----------------------------------------------------------------------

def test_anexo_exige_login(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cliente-teste.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "segredo-teste")
    monkeypatch.setattr(settings, "app_url", "https://cerebro.exemplo.com")
    with TestClient(app) as c:
        assert c.post("/fontes/anexo", files={"arquivo": ("a.txt", b"oi")}).status_code == 401
        assert c.get("/fontes/1").status_code == 401


def test_anexos_aparecem_na_lista_de_fontes_pela_origem(client, curador):
    fonte_id = anexar(client, texto_unico()).json()["fonte"]["id"]

    lista = client.get("/fontes", params={"origem": "upload", "limit": 200}).json()

    assert fonte_id in [f["id"] for f in lista["itens"]]
    assert all(f["origem"] == "upload" for f in lista["itens"])
