"""Como o Alembic se conecta ao banco e descobre o modelo. Roda a cada comando `alembic ...`."""
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (importar registra as tabelas no Base.metadata)
from app.config import settings
from app.db import Base, engine

config = context.config

# disable_existing_loggers=False: sem isso, rodar migrações (ex.: nos testes) "desliga" os loggers do app.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# O "alvo": é comparando o banco com este metadata que o --autogenerate descobre o que mudou.
target_metadata = Base.metadata

# render_as_batch: o SQLite não sabe alterar/remover colunas (ALTER TABLE limitado). No modo batch, o Alembic
# recria a tabela por baixo dos panos. No Postgres o mesmo código funciona normalmente.
OPCOES = {"target_metadata": target_metadata, "render_as_batch": True, "compare_type": True}


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade head --sql`): só gera o SQL, sem conectar no banco."""
    context.configure(url=settings.database_url, literal_binds=True, **OPCOES)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo normal: conecta usando o mesmo engine do app (mesma DATABASE_URL do .env)."""
    with engine.connect() as connection:
        context.configure(connection=connection, **OPCOES)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
