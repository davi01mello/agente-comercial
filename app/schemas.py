"""Schemas Pydantic: o que entra e sai da API."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import FONTES, SECOES, STATUS, TIPOS, TIPOS_RELACAO

# Valores permitidos: a lista mora em app/models.py (fonte única). Valor fora da lista -> 422 automático.
Tipo = Literal[*TIPOS]
Secao = Literal[*SECOES]
Status = Literal[*STATUS]
Fonte = Literal[*FONTES]
TipoRelacao = Literal[*TIPOS_RELACAO]

# Segmento é texto livre, mas sempre minúsculo: "Hotelaria" e "hotelaria" precisam bater na busca por relações.
Segmento = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=100)]


# --- insights --------------------------------------------------------------------------------

class RelacaoIn(BaseModel):
    """Este item reforça / contradiz / duplica / substitui o item `relacionado_id`."""

    relacionado_id: int = Field(gt=0)
    tipo: TipoRelacao


class RelacaoOut(RelacaoIn):
    model_config = ConfigDict(from_attributes=True)


class InsightBase(BaseModel):
    """Campos que a pessoa (ou o curador) preenche. Espelha docs/playbook-modelo.md."""

    model_config = ConfigDict(str_strip_whitespace=True)

    titulo: str = Field(min_length=1, max_length=200)
    tipo: Tipo
    secao: Secao
    descricao: str = Field(min_length=1, max_length=4000)
    segmento: Segmento | None = None
    servico: str | None = Field(default=None, max_length=100)
    o_que_foi_feito: str | None = Field(default=None, max_length=4000)
    resultado: str | None = Field(default=None, max_length=2000)
    evidencia: int = Field(default=1, ge=1, le=4)
    contexto_cliente: str | None = Field(default=None, max_length=2000)
    autor: str = Field(min_length=1, max_length=100)
    data_evento: date | None = None
    fonte: Fonte = "chat"
    fonte_ref: str | None = Field(default=None, max_length=500)


class InsightCreate(InsightBase):
    """Body de POST /insights.

    Não tem `status`: todo item nasce `proposto`, e quem decide isso é o código, não quem chama a API.
    Campos a mais no JSON (ex.: "status": "consolidado") são ignorados em silêncio.
    """

    model_config = ConfigDict(extra="ignore")

    relacoes: list[RelacaoIn] = Field(default=[], max_length=10)


class InsightOut(InsightBase):
    """O que a API devolve sobre um item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Status
    motivo_obsolescencia: str | None = None
    criado_em: datetime
    relacoes: list[RelacaoOut] = []
    avisos: list[str] = []  # ex.: possível dado pessoal (LGPD). Vem só na resposta da criação; não é gravado.


class FiltroInsights(BaseModel):
    """Query string de GET /insights. Ex.: /insights?status=validado&secao=proposta&limit=50"""

    model_config = ConfigDict(extra="forbid")  # ?stauts=... (erro de digitação) vira 422, não "sem filtro"

    status: Status | None = None
    secao: Secao | None = None
    segmento: Segmento | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ListaInsights(BaseModel):
    """Resposta de GET /insights: uma página de itens + o total, para a tela saber se há mais."""

    itens: list[InsightOut]
    total: int
    limit: int
    offset: int


# --- chat -----------------------------------------------------------------------------------

class MensagemHistorico(BaseModel):
    """Uma mensagem já trocada no chat. No Gemini, os papéis são "user" e "model"."""
    role: Literal["user", "model"]
    text: str = Field(max_length=8000)


class ChatIn(BaseModel):
    """O que o navegador manda para POST /chat."""
    mensagem: str = Field(min_length=1, max_length=4000)
    historico: list[MensagemHistorico] = Field(default=[], max_length=30)


class ChatOut(BaseModel):
    """O que POST /chat devolve."""
    resposta: str
