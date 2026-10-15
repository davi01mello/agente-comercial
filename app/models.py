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
ORIGENS = ["notion"]  # de onde vêm as fontes importadas (o Drive entra na Fase 2)
# Status de uma fonte (decisões no docs/adr-005-importacao-notion.md):
STATUS_FONTE = [
    "a_curar",  # passou na triagem e espera o curador (ou a execução parou no teto de gasto)
    "importada",  # o curador já propôs os itens (historico_a_validar, na Fila)
    "falha",  # o curador falhou nela; nada dela foi gravado e a próxima execução tenta de novo
    "vazia",  # quase sem texto: não vai ao modelo
    "pulada_dado_pessoal",  # e-mail, CPF, CNPJ ou telefone: NUNCA vai ao modelo (e o texto não é guardado)
    "pulada_longa",  # grande demais mesmo dividida em trechos
    "pulada_duplicata",  # mesmo conteúdo de outra fonte
    "removida",  # saiu do Notion (lixeira, apagada ou sem compartilhamento)
]


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


class Fonte(Base):
    """Uma página importada de fora (o "staging"). NÃO é conhecimento aprovado: os itens que o curador propõe a partir
    dela entram na Fila como historico_a_validar, com fonte_ref = esta url."""

    __tablename__ = "fontes"
    __table_args__ = (
        UniqueConstraint("origem", "id_externo", name="uq_fontes_origem_id_externo"),  # a chave da idempotência
        Index("ix_fontes_status", "status"),
        Index("ix_fontes_hash_conteudo", "hash_conteudo"),  # a busca de duplicatas é por hash
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origem: Mapped[str] = mapped_column(String(20))  # um de ORIGENS
    id_externo: Mapped[str] = mapped_column(String(100))  # o id da página no Notion (não muda ao renomear ou mover)
    titulo: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))  # montada pelo id: a do Notion repete o título no endereço
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # None quando pulada por dado pessoal
    hash_conteudo: Mapped[str] = mapped_column(String(64))  # SHA-256 do markdown normalizado
    editado_em: Mapped[datetime] = mapped_column(DateTime)  # last_edited_time do Notion, em UTC
    importado_em: Mapped[datetime] = mapped_column(DateTime)  # quando ESTE conteúdo (este hash) foi lido, em UTC
    status: Mapped[str] = mapped_column(String(30))  # um de STATUS_FONTE


class ExecucaoImportacao(Base):
    """Uma execução do scripts/importar_notion.py (o --dry-run não grava). O relatório completo (puladas com motivo,
    insights e custo) é impresso no fim da execução; aqui ficam as contagens que a spec pede."""

    __tablename__ = "execucoes_importacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inicio: Mapped[datetime] = mapped_column(DateTime)  # UTC
    fim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # None: a execução ainda roda ou caiu
    paginas_lidas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_novas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_alteradas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_falhas: Mapped[int] = mapped_column(Integer, default=0)
