"""Schemas Pydantic: o que entra e sai da API."""
from datetime import date, datetime

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
