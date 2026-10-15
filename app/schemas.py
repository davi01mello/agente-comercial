"""Schemas Pydantic: o que entra e sai da API."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app import dominio
from app.models import FONTES, SECOES, STATUS, STATUS_FONTE, TIPOS, TIPOS_RELACAO

# Valores permitidos: a lista mora em app/models.py (fonte única). Valor fora da lista -> 422 automático.
Tipo = Literal[*TIPOS]
Secao = Literal[*SECOES]
Status = Literal[*STATUS]
Fonte = Literal[*FONTES]
TipoRelacao = Literal[*TIPOS_RELACAO]
StatusFonte = Literal[*STATUS_FONTE]

# Segmento é texto livre, mas gravado numa forma única: "Saúde", "saude" e " SAUDE " viram "saúde", e assim batem
# na busca por relações e nos filtros (regras em dominio.normalizar_segmento; decisão no ADR-003).
Segmento = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(dominio.normalizar_segmento),
]


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


# --- curador --------------------------------------------------------------------------------
# Dois níveis: o que o MODELO devolve (classes ...LLM, ainda não conferidas) e o que a API devolve
# (PropostaCuradoria, já corrigida pelo código em app/curadoria.py). Nos schemas ...LLM, nenhum campo tem
# valor padrão além de None: o schema vai para o Gemini, e quanto mais simples, menos ele recusa.

class InsightLLM(BaseModel):
    """O item como o modelo propõe. Sem `autor` e sem `status`: esses quem decide é o código."""

    titulo: str = Field(min_length=1, max_length=200)
    tipo: Tipo
    secao: Secao
    descricao: str = Field(min_length=1, max_length=4000)
    segmento: str | None = Field(default=None, max_length=100)
    servico: str | None = Field(default=None, max_length=100)
    o_que_foi_feito: str | None = Field(default=None, max_length=4000)
    resultado: str | None = Field(default=None, max_length=2000)
    evidencia: int = Field(ge=1, le=4)
    contexto_cliente: str | None = Field(default=None, max_length=2000)
    data_evento: str | None = Field(default=None, description="Data do acontecimento em AAAA-MM-DD, se o texto disser")


class PropostaLLM(BaseModel):
    """1ª chamada do curador: estruturar o texto (e perguntar o que faltou)."""

    insight: InsightLLM
    perguntas: list[str]
    avisos: list[str]


class RelacaoLLM(BaseModel):
    id: int
    tipo: TipoRelacao


class RelacoesLLM(BaseModel):
    """2ª chamada (só se houver candidatos): como o item novo se relaciona com os que já existem."""

    relacoes: list[RelacaoLLM]


class RegistrarIn(BaseModel):
    """Body de POST /registrar/propor. Como no /chat, o navegador reenvia a conversa inteira a cada turno."""

    texto: str = Field(min_length=1, max_length=8000)
    autor: str = Field(min_length=1, max_length=100)
    conversa: list[MensagemHistorico] = Field(default=[], max_length=10)


class PropostaCuradoria(BaseModel):
    """Resposta de POST /registrar/propor: um RASCUNHO para a pessoa revisar. Nada foi gravado ainda."""

    insight: InsightBase
    relacoes: list[RelacaoIn] = []
    perguntas: list[str] = Field(default=[], max_length=2)
    avisos: list[str] = []


# --- fila -----------------------------------------------------------------------------------

class AprovarIn(BaseModel):
    """Body de POST /insights/{id}/aprovar. Sem login por enquanto: quem decide se identifica em texto livre
    (quando entrar o login, na T5, passa a vir da sessão)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    por_quem: str = Field(min_length=1, max_length=100)


class RejeitarIn(AprovarIn):
    """Body de POST /insights/{id}/rejeitar.

    O motivo é opcional AQUI de propósito: quem o exige é o dominio (MotivoObrigatorio). Assim a regra mora num
    lugar só, e "sem motivo" e "motivo só com espaços" recebem a mesma mensagem.
    """

    motivo: str | None = Field(default=None, max_length=2000)


# --- fontes (a tela de Fontes) ----------------------------------------------------------------

class FiltroFontes(BaseModel):
    """Query string de GET /fontes. Ex.: /fontes?status=pulada_dado_pessoal&q=proposta"""

    model_config = ConfigDict(extra="forbid")

    status: StatusFonte | None = None
    origem: str | None = Field(default=None, max_length=20)
    q: str | None = Field(default=None, max_length=100, description="parte do título")
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class FonteOut(BaseModel):
    """Uma página importada, como a tela mostra. Nunca leva o texto (`markdown`): só o que identifica e o estado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    origem: str
    titulo: str
    url: str
    status: StatusFonte
    motivo: str | None = None  # por que foi pulada, falhou ou saiu do Notion (nunca o dado pessoal em si)
    editado_em: datetime
    importado_em: datetime
    itens: dict[str, int] = {}  # itens que o curador propôs a partir dela: status do item -> quantos


class ListaFontes(BaseModel):
    itens: list[FonteOut]
    total: int
    limit: int
    offset: int


class ExecucaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inicio: datetime
    fim: datetime | None = None  # None: ainda roda, ou caiu no meio
    paginas_lidas: int
    paginas_novas: int
    paginas_alteradas: int
    paginas_falhas: int


class ResumoFontes(BaseModel):
    """GET /fontes/resumo: os números do topo da tela de Fontes."""

    total: int
    por_status: dict[str, int]
    por_origem: dict[str, int]
    ultima_execucao: ExecucaoOut | None = None

