"""POST /briefing (T7): seleção dos itens pelo código e conferência do que o modelo devolve. Sem Gemini."""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import briefing, busca, knowledge, llm
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Fonte, Insight, TrechoDocumento
from app.schemas import BriefingIn, BriefingLLM, PontoLLM

AGORA = datetime(2026, 10, 15, 12, 0)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seg():
    """Um segmento só deste teste: o banco é compartilhado entre os testes."""
    return f"seg{uuid.uuid4().hex[:8]}"


def item(db, seg, *, tipo="case", secao="reuniao_diagnostico", evidencia=3, status="validado", titulo=None,
         segmento="usar-seg", resultado="fechou em 30 dias"):
    i = Insight(titulo=titulo or f"{tipo} {uuid.uuid4().hex[:6]}", tipo=tipo, secao=secao, descricao="descrição longa",
                segmento=seg if segmento == "usar-seg" else segmento, evidencia=evidencia, autor="Rafael",
                status=status, resultado=resultado)
    db.add(i)
    db.commit()
    return i


def vazio(**mudancas) -> BriefingLLM:
    base = dict(resumo="Resumo.", cases=[], perfil=[], roteiro=[], objecoes=[], proposta=[], lacunas=[])
    return BriefingLLM(**(base | mudancas))


@pytest.fixture
def modelo(monkeypatch):
    """Troca o llm.briefar por um falso; `.resposta` é o que ele devolve e `.chamadas` o que ele recebeu."""
    class Falso:
        resposta = vazio()
        chamadas: list = []

        def __call__(self, segmento, tipo_reuniao, contexto, itens, documentos=""):
            self.chamadas.append({"segmento": segmento, "tipo": tipo_reuniao, "contexto": contexto,
                                  "itens": itens, "documentos": documentos})
            return self.resposta

    falso = Falso()
    falso.chamadas = []
    monkeypatch.setattr(llm, "briefar", falso)
    return falso


# --- seleção --------------------------------------------------------------------------------

def test_so_entram_itens_aprovados_do_segmento(seg):
    with SessionLocal() as db:
        ok = item(db, seg)
        consolidado = item(db, seg, status="consolidado")
        sem_segmento = item(db, seg, segmento=None, tipo="regra")
        proposto = item(db, seg, status="proposto")
        a_validar = item(db, seg, status="historico_a_validar")
        obsoleto = item(db, seg, status="obsoleto")
        de_outro = item(db, seg, segmento=f"outro{seg}")

        ids = {i.id for i in briefing.selecionar_itens(db, seg, "proposta").itens}

    assert {ok.id, consolidado.id, sem_segmento.id} <= ids
    assert not ids & {proposto.id, a_validar.id, obsoleto.id, de_outro.id}


def test_teto_por_tipo_fica_com_os_de_maior_evidencia(seg):
    with SessionLocal() as db:
        fortes = [item(db, seg, tipo="perfil_segmento", evidencia=4) for _ in range(2)]
        fraco = item(db, seg, tipo="perfil_segmento", evidencia=1)

        ids = {i.id for i in briefing.selecionar_itens(db, seg, "proposta").itens}

    assert {f.id for f in fortes} <= ids
    assert fraco.id not in ids  # o teto de perfil_segmento é 2


def test_diagnostico_com_pouco_do_segmento_completa_com_outros_marcados(seg, monkeypatch):
    # itens sem segmento de outros testes também contam como "do segmento": o limite alto isola este caso
    monkeypatch.setattr(briefing, "MIN_DO_SEGMENTO", 10_000)
    with SessionLocal() as db:
        do_segmento = item(db, seg)
        outros = [item(db, seg, segmento=f"x{seg}{n}") for n in range(5)]

        sel_diag = briefing.selecionar_itens(db, seg, "diagnostico")
        sel_prop = briefing.selecionar_itens(db, seg, "proposta")

    de_fora = sel_diag.de_outro_segmento
    assert 0 < len(de_fora) <= briefing.MAX_DE_OUTRO_SEGMENTO
    assert de_fora <= {o.id for o in outros} | {i.id for i in sel_diag.itens}
    assert do_segmento.id in {i.id for i in sel_diag.itens}
    assert not sel_prop.de_outro_segmento  # só o diagnóstico completa com outros segmentos


def test_lacunas_calculadas_pelo_codigo(seg):
    with SessionLocal() as db:
        so_case = [item(db, seg, tipo="case", secao="proposta")]
        achadas = briefing.lacunas_calculadas(seg, "diagnostico", so_case)

    texto = " ".join(achadas)
    assert "perfil" in texto and "objeção" in texto and "diagnóstico" in texto
    assert "case" not in texto.replace("Nenhum case", "")  # tem case: não reclama dele


# --- a rota ---------------------------------------------------------------------------------

def test_briefing_monta_pontos_com_fontes_e_evidencia(client, modelo, seg):
    with SessionLocal() as db:
        a = item(db, seg, tipo="case", evidencia=4, titulo="Piloto de 60 dias")
        b = item(db, seg, tipo="objecao", evidencia=2, titulo="Está caro")
    modelo.resposta = vazio(
        resumo="A base tem um case e uma objeção.",
        cases=[PontoLLM(texto=f"Cite o piloto [INS-{a.id}] de 60 dias.", fontes=[f"INS-{a.id}"])],
        objecoes=[PontoLLM(texto="Preço: mostre o piloto.", fontes=[f"INS-{b.id}", f"ins-{a.id}"])],
        lacunas=["Falta o perfil do decisor."],
    )

    r = client.post("/briefing", json={"segmento": seg, "tipo_reuniao": "proposta", "contexto": "primeira conversa"})

    assert r.status_code == 200
    j = r.json()
    assert j["usou_modelo"] is True and j["avisos"] == []
    cases = next(s for s in j["secoes"] if s["chave"] == "cases")
    assert cases["pontos"][0]["texto"] == "Cite o piloto de 60 dias."  # o id saiu do texto
    assert cases["pontos"][0]["evidencia_minima"] == 4
    assert cases["pontos"][0]["fontes"][0] == {"codigo": f"INS-{a.id}", "titulo": "Piloto de 60 dias",
                                               "tipo": "item", "url": None}
    obj = next(s for s in j["secoes"] if s["chave"] == "objecoes")["pontos"][0]
    assert obj["evidencia_minima"] == 2  # a MENOR entre os itens citados
    assert [f["codigo"] for f in obj["fontes"]] == [f"INS-{b.id}", f"INS-{a.id}"]  # "ins-N" minúsculo também vale
    assert "Falta o perfil do decisor." in j["lacunas"]
    assert {i["codigo"] for i in j["itens"]} >= {f"INS-{a.id}", f"INS-{b.id}"}
    assert modelo.chamadas[0]["contexto"] == "primeira conversa"
    assert f"[INS-{a.id}]" in modelo.chamadas[0]["itens"]


def test_ponto_sem_fonte_valida_e_descartado_e_avisado(client, modelo, seg):
    with SessionLocal() as db:
        a = item(db, seg)
        proposto = item(db, seg, status="proposto")  # nunca foi enviado ao modelo
    modelo.resposta = vazio(
        cases=[
            PontoLLM(texto="Sem fonte nenhuma.", fontes=[]),
            PontoLLM(texto="Fonte inventada.", fontes=["INS-999999"]),
            PontoLLM(texto="Fonte que não foi enviada.", fontes=[f"INS-{proposto.id}"]),
            PontoLLM(texto="Fonte mal escrita.", fontes=["abc"]),
            PontoLLM(texto="Esse vale.", fontes=[f"INS-{a.id}"]),
        ],
    )

    j = client.post("/briefing", json={"segmento": seg}).json()

    pontos = next(s for s in j["secoes"] if s["chave"] == "cases")["pontos"]
    assert [p["texto"] for p in pontos] == ["Esse vale."]
    assert any("4 ponto" in a for a in j["avisos"])


def test_limites_do_que_o_modelo_devolve(client, modelo, seg):
    with SessionLocal() as db:
        a = item(db, seg)
    muitos = [PontoLLM(texto=f"ponto {n} " + "x" * 600, fontes=[f"INS-{a.id}"]) for n in range(10)]
    modelo.resposta = vazio(roteiro=muitos, lacunas=[f"lacuna {n}" for n in range(9)] + ["lacuna 0"])

    j = client.post("/briefing", json={"segmento": seg}).json()

    roteiro = next(s for s in j["secoes"] if s["chave"] == "roteiro")["pontos"]
    assert len(roteiro) == briefing.MAX_PONTOS_POR_SECAO
    assert all(len(p["texto"]) <= briefing.MAX_TEXTO_DO_PONTO for p in roteiro)
    do_modelo = [x for x in j["lacunas"] if x.startswith("lacuna ")]
    assert len(do_modelo) <= briefing.MAX_LACUNAS_DO_MODELO


def test_documento_do_drive_vira_fonte_nao_revisada(client, modelo, seg):
    with SessionLocal() as db:
        busca.limpar_cache()
        doc = Fonte(origem="drive", id_externo=f"id-{seg}", titulo=f"Guia {seg}", url="https://drive/guia",
                    categoria="Resumo", hash_conteudo=seg, editado_em=AGORA, importado_em=AGORA, status="importada")
        db.add(doc)
        db.flush()
        db.add(TrechoDocumento(fonte_id=doc.id, ordem=1, texto=f"No {seg} o decisor é a diretoria."))
        db.commit()
        doc_id = doc.id
        item(db, seg)
    modelo.resposta = vazio(perfil=[PontoLLM(texto="Quem decide é a diretoria.", fontes=[f"DOC-{doc_id}"])])

    j = client.post("/briefing", json={"segmento": seg}).json()

    ponto = next(s for s in j["secoes"] if s["chave"] == "perfil")["pontos"][0]
    assert ponto["nao_revisado"] is True and ponto["evidencia_minima"] is None
    assert ponto["fontes"][0]["url"] == "https://drive/guia"
    assert [d["id"] for d in j["documentos"]] == [doc_id]
    assert f"[DOC-{doc_id}]" in modelo.chamadas[0]["documentos"]


def test_sem_nada_na_base_o_modelo_nem_e_chamado(client, modelo, monkeypatch, seg):
    monkeypatch.setattr(knowledge, "STATUS_NA_BASE", ["nenhum"])
    monkeypatch.setattr(busca, "buscar", lambda db, consulta, limite=5: [])

    r = client.post("/briefing", json={"segmento": seg})

    assert r.status_code == 200
    j = r.json()
    assert j["usou_modelo"] is False and modelo.chamadas == []
    assert all(s["pontos"] == [] for s in j["secoes"]) and len(j["secoes"]) == 5
    assert j["lacunas"] and j["avisos"]


def test_dado_pessoal_no_contexto_e_barrado_antes_do_modelo(client, modelo, seg):
    r = client.post("/briefing", json={"segmento": seg, "contexto": "falei com ana@hotelx.com.br"})

    assert r.status_code == 422
    assert "e-mail" in r.json()["detail"] and "ana@hotelx" not in r.json()["detail"]
    assert modelo.chamadas == []


@pytest.mark.parametrize("corpo", [
    {}, {"segmento": "   "}, {"segmento": "x", "tipo_reuniao": "cafe"}, {"segmento": "x", "contexto": "a" * 1501},
])
def test_corpo_invalido_vira_422(client, modelo, corpo):
    assert client.post("/briefing", json=corpo).status_code == 422
    assert modelo.chamadas == []


def test_falha_do_modelo_vira_502(client, monkeypatch, seg):
    with SessionLocal() as db:
        item(db, seg)

    def quebra(*a, **k):
        raise llm.ErroLLM("O briefing falhou.")

    monkeypatch.setattr(llm, "briefar", quebra)

    r = client.post("/briefing", json={"segmento": seg})

    assert r.status_code == 502 and "briefing" in r.json()["detail"]


def test_briefing_exige_login(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cliente-teste.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "segredo-teste")
    monkeypatch.setattr(settings, "app_url", "https://cerebro.exemplo.com")
    with TestClient(app) as c:
        assert c.post("/briefing", json={"segmento": "x"}).status_code == 401


def test_briefing_in_normaliza_o_segmento():
    assert BriefingIn(segmento=" SAUDE ").segmento == "saúde"
