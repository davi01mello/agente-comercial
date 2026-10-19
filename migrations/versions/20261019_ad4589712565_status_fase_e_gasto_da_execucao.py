"""status fase e gasto da execucao

Revision ID: ad4589712565
Revises: 670776546379
Create Date: 2026-10-19 10:00:33.630647

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identificadores usados pelo Alembic para encadear as migrações.
revision: str = 'ad4589712565'
down_revision: str | Sequence[str] | None = '670776546379'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As colunas obrigatórias e o valor delas nas execuções que já existem (as do script, antes da T4c). O
# server_default só existe para preencher essas linhas: depois ele sai, e quem dá o valor é o app (app/models.py).
OBRIGATORIAS = {
    "status": (sa.String(length=20), "concluida"),
    "fase": (sa.String(length=20), "fim"),
    "dry_run": (sa.Boolean(), sa.false()),
    "paginas_puladas": (sa.Integer(), "0"),
    "paginas_removidas": (sa.Integer(), "0"),
    "paginas_curadas": (sa.Integer(), "0"),
    "insights_propostos": (sa.Integer(), "0"),
    "gasto_usd": (sa.Float(), "0"),
}


def upgrade() -> None:
    with op.batch_alter_table('execucoes_importacao', schema=None) as batch_op:
        for nome, (tipo, valor) in OBRIGATORIAS.items():
            batch_op.add_column(sa.Column(nome, tipo, nullable=False, server_default=valor))
        batch_op.add_column(sa.Column('teto_usd', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('estimativa_usd', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('erro', sa.String(length=100), nullable=True))

    # Uma execução antiga sem fim caiu no meio (o script só fecha a execução no fim).
    op.execute("UPDATE execucoes_importacao SET status = 'erro', erro = 'interrompida' WHERE fim IS NULL")

    with op.batch_alter_table('execucoes_importacao', schema=None) as batch_op:
        for nome in OBRIGATORIAS:
            batch_op.alter_column(nome, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('execucoes_importacao', schema=None) as batch_op:
        batch_op.drop_column('erro')
        batch_op.drop_column('estimativa_usd')
        batch_op.drop_column('teto_usd')
        for nome in reversed(OBRIGATORIAS):
            batch_op.drop_column(nome)
