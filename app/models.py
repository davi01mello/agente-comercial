"""Modelo de dados. Espelha docs/playbook-modelo.md (Fase 0)."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, func
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


class Insight(Base):
    __tablename__ = "insights"

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
