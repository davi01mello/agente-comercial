"""usuarios: quem entrou com o Google (T5)

Revision ID: e31a5b7c9d02
Revises: c7d2e9a41f10
Create Date: 2026-10-20 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identificadores usados pelo Alembic para encadear as migrações.
revision: str = 'e31a5b7c9d02'
down_revision: str | Sequence[str] | None = 'c7d2e9a41f10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('nome', sa.String(length=100), nullable=False),
        sa.Column('criado_em', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('ultimo_acesso', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )


def downgrade() -> None:
    op.drop_table('usuarios')
