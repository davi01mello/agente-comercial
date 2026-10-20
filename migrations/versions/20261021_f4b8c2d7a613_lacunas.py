"""lacunas: perguntas que o consultor nao soube responder (T7)

Revision ID: f4b8c2d7a613
Revises: e31a5b7c9d02
Create Date: 2026-10-21 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identificadores usados pelo Alembic para encadear as migrações.
revision: str = 'f4b8c2d7a613'
down_revision: str | Sequence[str] | None = 'e31a5b7c9d02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'lacunas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chave', sa.String(length=200), nullable=False),
        sa.Column('pergunta', sa.String(length=500), nullable=False),
        sa.Column('pessoa', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('resolvida_por_insight_id', sa.Integer(), nullable=True),
        sa.Column('resolvida_em', sa.DateTime(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['resolvida_por_insight_id'], ['insights.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lacunas', schema=None) as batch_op:
        batch_op.create_index('ix_lacunas_chave', ['chave'], unique=False)
        batch_op.create_index('ix_lacunas_status', ['status'], unique=False)


def downgrade() -> None:
    op.drop_table('lacunas')
