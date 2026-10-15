"""Testes do curador na importação do Notion (importacao._curar), sem rede e sem modelo: o Notion é o NotionFalso (o
workspace FICTÍCIO de tests/fixtures/notion/workspace.json) e o modelo é o CuradorDeLote, que devolve o que o modelo
teria devolvido e "gasta" um valor combinado por chamada.

Na 1ª rodada, 6 das 10 páginas vão ao curador (as outras são vazia, duplicata ou têm dado pessoal: test_importacao).
"""
import logging
from datetime import datetime

import pytest
from sqlalchemy import select

from app import importacao, llm, notion, trechos
from app.db import SessionLocal
from app.importacao import AUTOR, importar
from app.models import ExecucaoImportacao, Fonte, HistoricoStatus, Insight, Relacao
from app.notion import LeitorNotion
from app.schemas import RelacoesLLM
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, id_da_pagina, limpar_banco_da_importacao
from tests.test_curador import proposta

AGORA = datetime(2026, 10, 15, 12, 0)
A_CURAR = [  # as 6 páginas que passam na triagem da 1ª rodada, na ordem da busca
    "Como qualificar leads de hotelaria", "Objeções comuns e respostas", "Roteiro da reunião de diagnóstico",
    "Prospecção por indicação", "Hotel Fictício Sol", "Rascunho antigo de proposta",
]


class CuradorDeLote:
    """Troca llm.curar e llm.relacionar. O título do item é o da página (a 1ª linha do trecho), para os testes
    saberem de onde cada item veio. `custo`: o que cada chamada "curar" soma no gasto real (None = resposta sem a
    contagem de tokens). `falhar_se` / `dado_pessoal_se`: o trecho que faz o modelo falhar ou devolver um telefone."""

    def __init__(self, custo: float | None = 0.001, falhar_se=lambda texto: False, dado_pessoal_se=lambda texto: False):
        self.custo = custo
        self.falhar_se = falhar_se
        self.dado_pessoal_se = dado_pessoal_se
        self.textos: list[str] = []

    def curar(self, texto, conversa, turno, ultimo_turno):
        assert (conversa, turno, ultimo_turno) == ([], 1, True)  # em lote: sempre o último turno, sem conversa
        self.textos.append(texto)
        llm._somar_gasto("ok", self.custo)
        if self.falhar_se(texto):
            raise llm.ErroLLM("o Gemini caiu (simulado)")
        campos = {"titulo": texto.splitlines()[0].removeprefix("Página do Notion: ")}
        if self.dado_pessoal_se(texto):
            campos["contexto_cliente"] = "o gerente atende no (81) 99876-5432"
        return proposta(**campos)

    def relacionar(self, item_novo, candidatos):
        return RelacoesLLM(relacoes=[])


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        limpar_banco_da_importacao(sessao)
        yield sessao


@pytest.fixture
def falso(monkeypatch):
    monkeypatch.setattr(importacao, "_agora", lambda: AGORA)
    monkeypatch.setattr(notion, "_dormir", lambda segundos: None)
    return NotionFalso()


@pytest.fixture
def curador(monkeypatch):
    """O curador falso padrão. Um teste que precisa de outro chama `usar(monkeypatch, CuradorDeLote(...))`."""
    return usar(monkeypatch, CuradorDeLote())


def usar(monkeypatch, falso_do_modelo: CuradorDeLote) -> CuradorDeLote:
    monkeypatch.setattr(llm, "curar", falso_do_modelo.curar)
    monkeypatch.setattr(llm, "relacionar", falso_do_modelo.relacionar)
    return falso_do_modelo


@pytest.fixture
def rodar(falso, db):
    def _rodar(**opcoes):
        opcoes.setdefault("teto_usd", 1.0)
        return importar(LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http()), db, **opcoes)
    return _rodar


def url(falso, titulo: str) -> str:
    return notion.url_da_pagina(id_da_pagina(falso.ws, titulo))


def itens(db, falso=None, titulo: str | None = None) -> list[Insight]:
    db.expire_all()
    consulta = select(Insight).where(Insight.fonte == "notion").order_by(Insight.id)
    if titulo:
        consulta = consulta.where(Insight.fonte_ref == url(falso, titulo))
    return list(db.scalars(consulta))


def status_da_fonte(db, falso, titulo: str) -> tuple[str, str | None]:
    db.expire_all()
    f = db.scalar(select(Fonte).where(Fonte.id_externo == id_da_pagina(falso.ws, titulo)))
    return f.status, f.motivo


# --- o caminho feliz ----------------------------------------------------------------------------------------

def test_um_item_por_pagina_na_fila_como_historico_a_validar(rodar, db, falso, curador):
    relatorio = rodar()

    novos = itens(db)
    assert [i.titulo for i in novos] == A_CURAR
    assert {i.status for i in novos} == {"historico_a_validar"}  # nunca validado: quem aprova é o time, na Fila
    assert {(i.autor, i.fonte) for i in novos} == {(AUTOR, "notion")}
    assert [i.fonte_ref for i in novos] == [url(falso, t) for t in A_CURAR]  # o link da página, montado pelo id
    assert [status_da_fonte(db, falso, t) for t in A_CURAR] == [("importada", None)] * 6
    assert (relatorio.insights_propostos, len(relatorio.curadas), relatorio.falhas_do_curador) == (6, 6, [])


def test_cada_item_ganha_o_historico_de_criacao(rodar, db, curador):
    relatorio = rodar()

    [item, *_] = itens(db)
    [historico] = db.scalars(select(HistoricoStatus).where(HistoricoStatus.insight_id == item.id))
    assert (historico.de, historico.para, historico.por_quem) == (None, "historico_a_validar", AUTOR)
    assert historico.motivo == f"Importado do Notion (execução #{relatorio.execucao_id})"


def test_pagina_com_dado_pessoal_nunca_chega_ao_curador(rodar, curador):
    rodar()

    assert len(curador.textos) == 6
    enviado = "\n".join(curador.textos)
    for proibido in ["contato@hotel-ficticio.com.br", "99876", "Contato do hotel parceiro"]:
        assert proibido not in enviado


def test_sem_teto_ou_no_dry_run_o_curador_nao_roda(rodar, db, falso, curador):
    rodar(teto_usd=None)
    rodar(dry_run=True)

    assert curador.textos == [] and itens(db) == []
    assert status_da_fonte(db, falso, A_CURAR[0]) == ("a_curar", None)


def test_teto_zero_ou_negativo_e_recusado(rodar, curador):
    with pytest.raises(ValueError, match="maior que zero"):
        rodar(teto_usd=0)


# --- tudo ou nada por página ---------------------------------------------------------------------------------

@pytest.fixture
def paginas_em_trechos(monkeypatch):
    """Trechos pequenos: "Como qualificar leads de hotelaria" vira mais de um trecho."""
    monkeypatch.setattr(trechos, "LIMITE_TRECHO", 300)
    monkeypatch.setattr(trechos, "_RESERVA_CABECALHO", 150)


def test_uma_pagina_em_trechos_vira_um_item_por_trecho(paginas_em_trechos, rodar, db, falso, curador):
    relatorio = rodar()

    [qualificar] = [p for p in relatorio.curadas if p.titulo == A_CURAR[0]]
    assert len(itens(db, falso, A_CURAR[0])) == len(qualificar.trechos) > 1


def test_falha_no_segundo_trecho_nao_grava_nada_da_pagina(paginas_em_trechos, monkeypatch, rodar, db, falso):
    usar(monkeypatch, CuradorDeLote(falhar_se=lambda t: t.startswith(f"Página do Notion: {A_CURAR[0]}")
                                    and "(parte 2 de" in t))

    relatorio = rodar()

    assert itens(db, falso, A_CURAR[0]) == []  # nem o item do 1º trecho, que deu certo
    status, motivo = status_da_fonte(db, falso, A_CURAR[0])
    assert status == "falha" and motivo.startswith("o curador falhou")
    assert [p.titulo for p in relatorio.falhas_do_curador] == [A_CURAR[0]]
    assert len(relatorio.curadas) == 5  # as outras páginas seguem
    assert db.get(ExecucaoImportacao, relatorio.execucao_id).paginas_falhas == 1


def test_pagina_que_falhou_e_tentada_de_novo_e_nao_duplica(monkeypatch, rodar, db, falso):
    usar(monkeypatch, CuradorDeLote(falhar_se=lambda t: A_CURAR[1] in t))
    rodar()
    usar(monkeypatch, CuradorDeLote())

    relatorio = rodar()

    assert [p.titulo for p in relatorio.curadas] == [A_CURAR[1]]  # só a que tinha falhado
    assert [i.titulo for i in itens(db)].count(A_CURAR[1]) == 1
    assert status_da_fonte(db, falso, A_CURAR[1]) == ("importada", None)


def test_item_proposto_com_dado_pessoal_vira_falha(monkeypatch, rodar, db, falso):
    """O texto passou na triagem, mas o modelo devolveu algo com cara de telefone: o item não é gravado."""
    usar(monkeypatch, CuradorDeLote(dado_pessoal_se=lambda t: A_CURAR[2] in t))

    relatorio = rodar()

    assert itens(db, falso, A_CURAR[2]) == []
    assert status_da_fonte(db, falso, A_CURAR[2]) == (
        "falha", "o item proposto tem possível dado pessoal (telefone em contexto_cliente)")
    assert "99876" not in repr(relatorio)


# --- teto de gasto -------------------------------------------------------------------------------------------

def test_teto_para_antes_de_estourar_e_a_proxima_execucao_continua(monkeypatch, rodar, db, falso):
    """Cada página "custa" US$ 0,50. Teto de US$ 1: a 1ª cabe (0 + 2 × estimativa), a 2ª também (0,50 + 2 ×
    estimativa), e a 3ª não (1,00 + 2 × estimativa). O que falta continua a_curar e a próxima execução continua."""
    curador = usar(monkeypatch, CuradorDeLote(custo=0.5))

    relatorio = rodar(teto_usd=1.0)

    assert [p.titulo for p in relatorio.curadas] == A_CURAR[:2]
    assert [p.titulo for p in relatorio.esperando] == A_CURAR[2:]
    assert relatorio.parou_no_teto and relatorio.custo_real_usd == pytest.approx(1.0)
    assert [status_da_fonte(db, falso, t)[0] for t in A_CURAR[2:]] == ["a_curar"] * 4

    curador.textos.clear()
    relatorio = rodar(teto_usd=1.0)

    assert [p.titulo for p in relatorio.curadas] == A_CURAR[2:4]
    assert len(curador.textos) == 2  # as já importadas não voltam ao curador
    assert [i.titulo for i in itens(db)] == A_CURAR[:4]


def test_teto_menor_que_a_primeira_pagina_nao_chama_o_modelo(rodar, db, curador):
    relatorio = rodar(teto_usd=0.0001)

    assert curador.textos == [] and itens(db) == []
    assert len(relatorio.esperando) == 6 and relatorio.custo_real_usd == 0


def test_resposta_sem_contagem_de_tokens_conta_como_a_estimativa(monkeypatch, rodar):
    usar(monkeypatch, CuradorDeLote(custo=None))

    relatorio = rodar()

    esperado = sum(importacao.estimar(p.trechos).custo_usd for p in relatorio.curadas)
    assert relatorio.custo_real_usd == pytest.approx(esperado) and esperado > 0


# --- idempotência --------------------------------------------------------------------------------------------

def retrato(db) -> dict[str, list[tuple]]:
    """Todas as linhas das tabelas que a importação toca (menos a da execução, que a spec manda registrar)."""
    db.expire_all()
    ids = [i.id for i in itens(db)]
    return {
        "fontes": [(f.id, f.titulo, f.markdown, f.hash_conteudo, f.editado_em, f.importado_em, f.status, f.motivo)
                   for f in db.scalars(select(Fonte).order_by(Fonte.id))],
        "insights": [(i.id, i.titulo, i.status, i.fonte_ref) for i in itens(db)],
        "historico": [(h.id, h.insight_id, h.de, h.para) for h in db.scalars(
            select(HistoricoStatus).where(HistoricoStatus.insight_id.in_(ids)).order_by(HistoricoStatus.id))],
        "relacoes": [(r.id, r.insight_id) for r in db.scalars(select(Relacao).where(Relacao.insight_id.in_(ids)))],
    }


def test_duas_rodadas_com_o_curador_nao_mudam_nada(rodar, db, curador):
    """Critério de aceite da spec, agora com o curador: a 2ª execução não chama o modelo nem muda nenhuma linha."""
    rodar()
    antes = retrato(db)
    curador.textos.clear()

    relatorio = rodar()

    assert retrato(db) == antes
    assert curador.textos == []
    assert (relatorio.insights_propostos, relatorio.custo_real_usd) == (0, 0)


# --- log -----------------------------------------------------------------------------------------------------

def test_log_da_curadoria_so_tem_numeros(rodar, curador, caplog):
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="app"):
        rodar()

    assert '"insights_propostos": 6' in caplog.text
    for proibido in [*A_CURAR, "Abrir com diagnóstico", "orçamento aprovado", TOKEN_DE_TESTE]:
        assert proibido not in caplog.text
