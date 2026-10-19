"""drive: categoria da fonte, trechos de documento e origem da execução

Revision ID: c7d2e9a41f10
Revises: ad4589712565
Create Date: 2026-10-19 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identificadores usados pelo Alembic para encadear as migrações.
revision: str = 'c7d2e9a41f10'
down_revision: str | Sequence[str] | None = 'ad4589712565'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('fontes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('categoria', sa.String(length=300), nullable=True))

    # As execuções que já existem são todas do Notion (o Drive é novo): o server_default preenche essas linhas.
    with op.batch_alter_table('execucoes_importacao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origem', sa.String(length=20), nullable=False, server_default='notion'))

    op.create_table(
        'trechos_documento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fonte_id', sa.Integer(), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.Column('texto', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['fonte_id'], ['fontes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trechos_documento_fonte_id', 'trechos_documento', ['fonte_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_trechos_documento_fonte_id', table_name='trechos_documento')
    op.drop_table('trechos_documento')
    with op.batch_alter_table('execucoes_importacao', schema=None) as batch_op:
        batch_op.drop_column('origem')
    with op.batch_alter_table('fontes', schema=None) as batch_op:
        batch_op.drop_column('categoria')
