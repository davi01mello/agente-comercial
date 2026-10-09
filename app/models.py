"""Modelo de dados. Espelha docs/playbook-modelo.md (Fase 0).

Mudou alguma coisa aqui? Gere a migração: alembic revision --autogenerate -m "o que mudou"
"""
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Valores permitidos (fonte da verdade: docs/playbook-modelo.md)
TIPOS = ["aprendizado", "hipotese", "regra", "case", "objecao", "perfil_segmento", "template"]
SECOES = [
    "fundamentos", "prospeccao", "qualificacao", "reuniao_diagnostico",
    "proposta", "negociacao_fechamento", "pos_venda",
]
STATUS = ["proposto", "validado", "consolidado", "obsoleto", "historico_a_validar"]
EVIDENCIA = {1: "opiniao", 2: "observacao_unica", 3: "padrao_repetido", 4: "resultado_medido"}
FONTES = ["chat", "notion", "drive", "canva", "reuniao"]
TIPOS_RELACAO = ["reforca", "contradiz", "duplica", "substitui"]


class Insight(Base):
    __tablename__ = "insights"
    __table_args__ = (
        # A Fila e o consultor filtram por status; o playbook e o curador, por seção + segmento.
        Index("ix_insights_status", "status"),
        Index("ix_insights_secao_segmento", "secao", "segmento"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(30))
    secao: Mapped[str] = mapped_column(String(40))
    descricao: Mapped[str] = mapped_column(Text)
    segmento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    servico: Mapped[str | None] = mapped_column(String(100), nullable=True)
    o_que_foi_feito: Mapped[str | None] = mapped_column(Text, nullable=True)
    resultado: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidencia: Mapped[int] = mapped_column(Integer, default=1)  # 1 a 4
    contexto_cliente: Mapped[str | None] = mapped_column(Text, nullable=True)
    autor: Mapped[str] = mapped_column(String(100))
    data_evento: Mapped[date | None] = mapped_column(Date, nullable=True)
    fonte: Mapped[str] = mapped_column(String(20), default="chat")
    fonte_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)  # link/caminho
    status: Mapped[str] = mapped_column(String(30), default="proposto")
    motivo_obsolescencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Relacao(Base):
    """Liga dois insights: `insight_id` reforça/contradiz/duplica/substitui `relacionado_id`."""

    __tablename__ = "relacoes"
    __table_args__ = (
        UniqueConstraint("insight_id", "relacionado_id", "tipo", name="uq_relacoes_par_tipo"),
        CheckConstraint("insight_id <> relacionado_id", name="ck_relacoes_nao_aponta_para_si"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_id: Mapped[int] = mapped_column(ForeignKey("insights.id"), index=True)
    relacionado_id: Mapped[int] = mapped_column(ForeignKey("insights.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # um de TIPOS_RELACAO
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HistoricoStatus(Base):
    """Toda mudança de status de um insight. Nada é apagado: o histórico é parte do valor."""

    __tablename__ = "historico_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_id: Mapped[int] = mapped_column(ForeignKey("insights.id"), index=True)
    de: Mapped[str | None] = mapped_column(String(30), nullable=True)  # None = criação do item
    para: Mapped[str] = mapped_column(String(30))
    por_quem: Mapped[str] = mapped_column(String(100))
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())