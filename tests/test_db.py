"""Testes de integridade do banco: as regras que o SQLite só cumpre porque ligamos as chaves estrangeiras.

Cada teste trabalha numa sessão que no fim é desfeita (rollback), então não deixa lixo para os outros.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import HistoricoStatus, Insight, Relacao


@pytest.fixture
def sessao():
    with SessionLocal() as s:
        yield s
        s.rollback()


def _insight(titulo: str) -> Insight:
    return Insight(titulo=titulo, tipo="aprendizado", secao="proposta", descricao="d", autor="teste")


def test_relacao_valida(sessao):
    a, b = _insight("a"), _insight("b")
    sessao.add_all([a, b])
    sessao.flush()
    sessao.add(Relacao(insight_id=a.id, relacionado_id=b.id, tipo="reforca"))
    sessao.flush()  # não levanta nada


def test_relacao_para_insight_inexistente(sessao):
    a = _insight("a")
    sessao.add(a)
    sessao.flush()
    sessao.add(Relacao(insight_id=a.id, relacionado_id=999_999, tipo="reforca"))
    with pytest.raises(IntegrityError):  # só acontece com PRAGMA foreign_keys=ON
        sessao.flush()


def test_relacao_nao_aponta_para_si(sessao):
    a = _insight("a")
    sessao.add(a)
    sessao.flush()
    sessao.add(Relacao(insight_id=a.id, relacionado_id=a.id, tipo="duplica"))
    with pytest.raises(IntegrityError):
        sessao.flush()


def test_relacao_duplicada(sessao):
    a, b = _insight("a"), _insight("b")
    sessao.add_all([a, b])
    sessao.flush()
    sessao.add(Relacao(insight_id=a.id, relacionado_id=b.id, tipo="contradiz"))
    sessao.flush()
    sessao.add(Relacao(insight_id=a.id, relacionado_id=b.id, tipo="contradiz"))
    with pytest.raises(IntegrityError):
        sessao.flush()


def test_historico_de_insight_inexistente(sessao):
    sessao.add(HistoricoStatus(insight_id=999_999, de=None, para="proposto", por_quem="teste"))
    with pytest.raises(IntegrityError):
        sessao.flush()
