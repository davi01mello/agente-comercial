"""As tabelas da importação (T4): exatamente os campos da spec do Davi, e a chave da idempotência."""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import ExecucaoImportacao, Fonte


def colunas(tabela: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(tabela)}


def test_fontes_tem_exatamente_os_campos_da_spec():
    assert colunas("fontes") == {
        "id", "origem", "id_externo", "titulo", "url", "markdown", "hash_conteudo", "editado_em", "importado_em",
        "status",
    }


def test_execucoes_tem_exatamente_os_campos_da_spec():
    assert colunas("execucoes_importacao") == {
        "id", "inicio", "fim", "paginas_lidas", "paginas_novas", "paginas_alteradas", "paginas_falhas",
    }


def fonte(id_externo: str) -> Fonte:
    agora = datetime(2026, 10, 13, 12, 0)
    return Fonte(origem="notion", id_externo=id_externo, titulo="t", url="u", markdown="m", hash_conteudo="h",
                 editado_em=agora, importado_em=agora, status="a_curar")


def test_origem_e_id_externo_sao_unicos():
    """É o que garante que a mesma página do Notion nunca vira duas fontes."""
    id_externo = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(fonte(id_externo))
        db.commit()
        db.add(fonte(id_externo))
        with pytest.raises(IntegrityError):
            db.commit()


def test_a_mesma_pagina_em_outra_origem_pode_existir():
    id_externo = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(fonte(id_externo))
        outra = fonte(id_externo)
        outra.origem = "drive"
        db.add(outra)
        db.commit()  # não levanta


def test_contagens_da_execucao_comecam_em_zero():
    with SessionLocal() as db:
        execucao = ExecucaoImportacao(inicio=datetime(2026, 10, 13, 12, 0))
        db.add(execucao)
        db.commit()
        assert (execucao.paginas_lidas, execucao.paginas_novas, execucao.paginas_alteradas,
                execucao.paginas_falhas, execucao.fim) == (0, 0, 0, 0, None)
