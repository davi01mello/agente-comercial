"""Os testes usam um banco temporário NOVO a cada execução, criado pelas migrações (nunca o banco de dev).

Assim todo `pytest` também prova que as migrações sobem do zero.
"""
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

# Precisa vir antes de qualquer `import app...`: o app lê DATABASE_URL quando é importado.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='cerebro_teste_')}/teste.db"

RAIZ = Path(__file__).parent.parent


@pytest.fixture(scope="session", autouse=True)
def banco_migrado():
    """Aplica todas as migrações (alembic upgrade head) uma vez, antes do primeiro teste."""
    command.upgrade(Config(str(RAIZ / "alembic.ini")), "head")
