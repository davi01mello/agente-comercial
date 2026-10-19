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


@pytest.fixture(autouse=True)
def sem_login_como_rafael(monkeypatch):
    """Os testes rodam como o dev sem login (o .env de teste não tem GOOGLE_CLIENT_ID), e quem entra é o "Rafael": é
    o nome que a maioria dos testes já esperava como autor. Os testes do login (tests/test_auth.py) ligam o login de
    verdade pelo fixture `login_ligado`."""
    from app import auth, config

    monkeypatch.setattr(auth, "DEV_NOME", "Rafael")
    for campo in ("google_client_id", "google_client_secret"):
        monkeypatch.setattr(config.settings, campo, "")
