"""A execução da importação como a tela acompanha (T4c): status, fase, contagens, gasto, teto e estimativa, gravados a
cada página. Sem rede e sem modelo: o NotionFalso e o CuradorDeLote de test_curadoria_notion."""
import pytest
from sqlalchemy import func, select

from app import importacao, notion
from app.db import SessionLocal
from app.importacao import importar, nova_execucao
from app.models import ExecucaoImportacao, Fonte
from app.notion import ErroNotion, LeitorNotion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, limpar_banco_da_importacao
from tests.test_curadoria_notion import CuradorDeLote, usar


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        limpar_banco_da_importacao(sessao)
        yield sessao


@pytest.fixture
def falso(monkeypatch):
    monkeypatch.setattr(notion, "_dormir", lambda segundos: None)
    return NotionFalso()


@pytest.fixture
def curador(monkeypatch):
    return usar(monkeypatch, CuradorDeLote())


@pytest.fixture
def rodar(falso, db):
    def _rodar(**opcoes):
        opcoes.setdefault("teto_usd", 1.0)
        return importar(LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http()), db, **opcoes)
    return _rodar


def execucao_no_banco(execucao_id: int) -> ExecucaoImportacao:
    """Lida numa sessão à parte, como a tela (GET /fontes/execucoes/{id}) leria: só vê o que já foi commitado."""
    with SessionLocal() as outra:
        return outra.get(ExecucaoImportacao, execucao_id)


def test_execucao_concluida_tem_status_fase_contagens_gasto_e_teto(rodar, curador):
    relatorio = rodar()

    e = execucao_no_banco(relatorio.execucao_id)
    assert (e.status, e.fase, e.dry_run, e.erro) == ("concluida", "fim", False, None)
    assert (e.paginas_lidas, e.paginas_novas, e.paginas_alteradas, e.paginas_puladas, e.paginas_removidas,
            e.paginas_falhas, e.paginas_curadas, e.insights_propostos) == (10, 10, 0, 4, 0, 0, 6, 6)
    assert e.gasto_usd == pytest.approx(0.006)  # 6 chamadas de US$ 0,001 no curador falso
    assert e.teto_usd == 1.0
    assert e.estimativa_usd == pytest.approx(relatorio.estimativa.custo_usd) and e.estimativa_usd > 0
    assert e.fim is not None


def test_o_progresso_e_gravado_a_cada_pagina(monkeypatch, rodar, db, falso):
    """No meio da execução, outra sessão já vê a fase e as contagens das páginas que terminaram."""
    vistos = []
    sincronizar_pagina = importacao._sincronizar_pagina

    def espiar_a_sincronizacao(leitor, db, pagina, relatorio, hashes):
        vistos.append(("sincronizando", relatorio.lidas, execucao_no_banco(relatorio.execucao_id)))
        sincronizar_pagina(leitor, db, pagina, relatorio, hashes)

    class CuradorQueEspia(CuradorDeLote):
        def curar(self, texto, conversa, turno, ultimo_turno):
            vistos.append(("curando", len(self.textos), execucao_no_banco(execucao_id)))
            return super().curar(texto, conversa, turno, ultimo_turno)

    monkeypatch.setattr(importacao, "_sincronizar_pagina", espiar_a_sincronizacao)
    usar(monkeypatch, CuradorQueEspia())
    execucao_id = nova_execucao(db, teto_usd=1.0).id

    rodar(execucao_id=execucao_id)

    sincronizando = [(n, e.status, e.fase, e.paginas_lidas) for fase, n, e in vistos if fase == "sincronizando"]
    assert sincronizando == [(n, "rodando", "sincronizando", n - 1) for n in range(1, 11)]  # a n-ésima vê n-1 prontas
    curando = [(n, e.status, e.fase, e.paginas_curadas) for fase, n, e in vistos if fase == "curando"]
    assert curando == [(n, "rodando", "curando", n) for n in range(6)]  # antes da página n+1, as n anteriores
    assert execucao_no_banco(execucao_id).gasto_usd == pytest.approx(0.006)


def test_parou_no_teto_fica_no_status(monkeypatch, rodar):
    """Cada página "custa" US$ 0,50: a 1ª e a 2ª cabem no teto de US$ 1, a 3ª não (folga de 2 × a estimativa)."""
    usar(monkeypatch, CuradorDeLote(custo=0.5))

    relatorio = rodar(teto_usd=1.0)

    e = execucao_no_banco(relatorio.execucao_id)
    assert (e.status, e.fase, e.paginas_curadas, e.gasto_usd, e.teto_usd) == ("parou_no_teto", "fim", 2, 1.0, 1.0)


def test_erro_do_notion_guarda_o_tipo_e_o_codigo_e_a_fase_onde_parou(rodar, db, falso, curador):
    falso.falhar("/v1/search", 401)

    with pytest.raises(ErroNotion):
        rodar()

    e = db.scalar(select(ExecucaoImportacao))
    assert (e.status, e.fase, e.erro) == ("erro", "sincronizando", "ErroNotion (401)")
    assert e.fim is not None and e.estimativa_usd is None


@pytest.mark.parametrize("onde, fase", [("_triar", "sincronizando"), ("_curar_pagina", "curando")])
def test_erro_inesperado_guarda_so_o_tipo(monkeypatch, rodar, db, curador, onde, fase):
    """A mensagem de um erro inesperado pode ter texto de página (o SQLAlchemy põe os parâmetros do SQL nela)."""
    def quebrar(*args):
        raise RuntimeError("TEXTO-DE-PAGINA-NO-ERRO")

    monkeypatch.setattr(importacao, onde, quebrar)

    with pytest.raises(RuntimeError):
        rodar()

    e = db.scalar(select(ExecucaoImportacao))
    assert (e.status, e.fase, e.erro) == ("erro", fase, "RuntimeError")


def test_dry_run_grava_a_execucao_sem_teto_e_sem_mudar_as_fontes(rodar, db, curador):
    relatorio = rodar(dry_run=True, teto_usd=1.0)

    e = execucao_no_banco(relatorio.execucao_id)
    assert (e.status, e.fase, e.dry_run, e.teto_usd) == ("concluida", "fim", True, None)
    assert (e.paginas_lidas, e.paginas_puladas, e.paginas_curadas, e.gasto_usd) == (10, 4, 0, 0.0)
    assert e.estimativa_usd == pytest.approx(relatorio.estimativa.custo_usd) and e.estimativa_usd > 0
    assert db.scalar(select(func.count()).select_from(Fonte)) == 0
    assert curador.textos == []


def test_importar_usa_a_execucao_ja_criada(rodar, db, curador):
    """A API cria a execução na requisição (para devolver o id) e o trabalho segue nela, sem criar outra."""
    criada = nova_execucao(db, teto_usd=0.5)

    relatorio = rodar(execucao_id=criada.id, teto_usd=0.5)

    assert relatorio.execucao_id == criada.id
    assert db.scalar(select(func.count()).select_from(ExecucaoImportacao)) == 1
    assert execucao_no_banco(criada.id).status == "concluida"


def test_nova_execucao_comeca_rodando_e_sem_teto_no_dry_run(db):
    real, simulacao = nova_execucao(db, teto_usd=2.0), nova_execucao(db, dry_run=True, teto_usd=2.0)

    assert (real.status, real.fase, real.dry_run, real.teto_usd, real.fim) == ("rodando", "sincronizando", False, 2.0,
                                                                               None)
    assert (simulacao.dry_run, simulacao.teto_usd) == (True, None)
