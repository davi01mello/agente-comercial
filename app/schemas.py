"""Schemas Pydantic: o que entra e sai da API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class InsightCreate(BaseModel):
    titulo: str = Field(max_length=200)
    tipo: str
    secao: str
    descricao: str
    segmento: str | None = None
    servico: str | None = None
    o_que_foi_feito: str | None = None
    resultado: str | None = None
    evidencia: int = Field(default=1, ge=1, le=4)
    contexto_cliente: str | None = None
    autor: str
    data_evento: date | None = None
    fonte: str = "chat"
    fonte_ref: str | None = None


class InsightOut(InsightCreate):
    id: int
    status: str
    criado_em: datetime

    model_config = {"from_attributes": True}


class MensagemHistorico(BaseModel):
    """Uma mensagem já trocada no chat. No Gemini, os papéis são "user" e "model"."""
    role: Literal["user", "model"]
    text: str


class ChatIn(BaseModel):
    """O que o navegador manda para POST /chat."""
    mensagem: str = Field(min_length=1, max_length=4000)
    historico: list[MensagemHistorico] = []


class ChatOut(BaseModel):
    """O que POST /chat devolve."""
    resposta: str

class MensagemHistorico(BaseModel):
    role: Literal["user", "model"]
    text: str

class ChatIn(BaseModel):
    mensagem: str = Field(min_length=1, max_length=4000)
    historico: list[MensagemHistorico] = []

class ChatOut(BaseModel):
    resposta: str

    