"""Modelo de dados. Espelha docs/playbook-modelo.md (Fase 0).

Mudou alguma coisa aqui? Gere a migração: alembic revision --autogenerate -m "o que mudou"
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
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
MOTIVO_MAX = 200  # o tamanho de fontes.motivo
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
# Uma execução da importação (decisões no ADR-005):
STATUS_EXECUCAO = [
    "rodando",
    "concluida",
    "parou_no_teto",  # o curador parou antes de estourar o teto: o que falta continua a_curar para a próxima
    "erro",  # caiu no meio (o que estava pela metade não entrou) ou o servidor parou com ela rodando
]
FASES_EXECUCAO = ["sincronizando", "curando", "fim"]


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
    # Por que foi pulada, falhou ou saiu do Notion ("e-mail no conteúdo", "6 trechos (limite 5)"). NUNCA o dado em
    # si. None quando a fonte está a_curar ou importada. A tela de Fontes mostra.
    motivo: Mapped[str | None] = mapped_column(String(MOTIVO_MAX), nullable=True)


class ExecucaoImportacao(Base):
    """Uma execução da importação, pelo script ou pela API (POST /fontes/sincronizar). O --dry-run também fica
    registrado (dry_run=True), para a tela acompanhar a simulação; ele não muda as fontes, e o /fontes/resumo o
    ignora. As contagens são gravadas a cada página, para a tela acompanhar; o relatório completo (títulos e motivos)
    só o script imprime."""

    __tablename__ = "execucoes_importacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inicio: Mapped[datetime] = mapped_column(DateTime)  # UTC
    fim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # None: a execução ainda roda
    paginas_lidas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_novas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_alteradas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_falhas: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="rodando")  # um de STATUS_EXECUCAO
    fase: Mapped[str] = mapped_column(String(20), default="sincronizando")  # um de FASES; no erro, onde parou
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    paginas_puladas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_removidas: Mapped[int] = mapped_column(Integer, default=0)
    paginas_curadas: Mapped[int] = mapped_column(Integer, default=0)
    insights_propostos: Mapped[int] = mapped_column(Integer, default=0)
    gasto_usd: Mapped[float] = mapped_column(Float, default=0.0)  # o custo real do curador até aqui
    teto_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # None no dry-run (o curador não roda)
    estimativa_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # None até a sincronização acabar
    # Só o tipo do erro ("ErroNotion (401)", "RuntimeError") ou "interrompida": NUNCA a mensagem, que pode ter
    # texto de página (o SQLAlchemy põe os parâmetros do SQL nela).
    erro: Mapped[str | None] = mapped_column(String(100), nullable=True)
