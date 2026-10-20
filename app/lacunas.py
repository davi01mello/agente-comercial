"""Lacunas (T7): o que o time perguntou e a base não soube responder.

Quando o consultor responde "A base não cobre <tema>" (a frase que o prompt manda usar), a pergunta é guardada. As
parecidas se juntam (mesmas palavras, em qualquer ordem) e a lista mostra o que mais falta, para o time registrar.
Quando alguém registra um item a partir de uma lacuna (POST /insights com `lacuna_id`), ela sai da lista aberta.

Quem decide que é lacuna é o CÓDIGO, pela frase da resposta: o modelo não escreve na tabela. A pergunta guardada já
passou pela barreira de dado pessoal do /chat, e ela nunca vai ao modelo de novo por aqui.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.busca import palavras
from app.models import Lacuna

logger = logging.getLogger(__name__)

FRASE = "a base nao cobre"  # a de app/prompts/consultor.md, sem acento e em minúsculas
MAX_PALAVRAS_NA_CHAVE = 12
MAX_LINHAS_NA_LISTA = 5000  # a lista agrupa em Python: as mais recentes bastam para um time


@dataclass(frozen=True)
class GrupoDeLacunas:
    id: int  # a lacuna mais antiga do grupo (é o id que o resolver recebe)
    pergunta: str  # a mais recente do grupo
    vezes: int
    pessoas: int
    primeira_em: datetime
    ultima_em: datetime
    status: str
    resolvida_por_insight_id: int | None


def _sem_acento(texto: str) -> str:
    from unicodedata import normalize

    return normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def e_lacuna(resposta: str) -> bool:
    """A resposta do consultor admite que a base não cobre o tema?"""
    return FRASE in _sem_acento(resposta)


def chave_da(pergunta: str) -> str:
    """As palavras da pergunta (sem acento, sem as vazias), sem repetir e em ordem: "preço hotelaria" e "hotelaria,
    preço?" dão a mesma chave. Vazia se a pergunta não tem palavra útil."""
    return " ".join(sorted(set(palavras(pergunta)))[:MAX_PALAVRAS_NA_CHAVE])


def registrar(db: Session, pergunta: str, pessoa: str) -> Lacuna | None:
    """Guarda a pergunta que ficou sem resposta. Nunca levanta: o /chat não pode falhar por causa disto."""
    chave = chave_da(pergunta)
    if not chave:
        return None
    try:
        lacuna = Lacuna(chave=chave[:200], pergunta=" ".join(pergunta.split())[:500], pessoa=pessoa[:100])
        db.add(lacuna)
        db.commit()
        db.refresh(lacuna)
        return lacuna
    except SQLAlchemyError:
        db.rollback()
        logger.warning("não consegui guardar a lacuna (erro do banco)")
        return None


def agrupar(db: Session, status: str = "aberta", limite: int = 50) -> list[GrupoDeLacunas]:
    """As lacunas do status pedido, juntas por chave: as que mais se repetem primeiro (empate: a mais recente)."""
    linhas = list(db.scalars(
        select(Lacuna).where(Lacuna.status == status).order_by(Lacuna.id.desc()).limit(MAX_LINHAS_NA_LISTA)
    ))
    grupos: dict[str, list[Lacuna]] = {}
    for linha in linhas:  # da mais nova para a mais velha
        grupos.setdefault(linha.chave, []).append(linha)
    saida = [
        GrupoDeLacunas(
            id=min(x.id for x in g), pergunta=g[0].pergunta, vezes=len(g), pessoas=len({x.pessoa for x in g}),
            primeira_em=min(x.criado_em for x in g), ultima_em=max(x.criado_em for x in g), status=status,
            resolvida_por_insight_id=next((x.resolvida_por_insight_id for x in g if x.resolvida_por_insight_id), None),
        )
        for g in grupos.values()
    ]
    saida.sort(key=lambda g: (g.vezes, g.ultima_em), reverse=True)
    return saida[:limite]


def resolver(db: Session, lacuna_id: int, insight_id: int | None = None) -> bool:
    """Fecha a lacuna e todas as parecidas (mesma chave). False se o id não existe. Já resolvida: não muda nada."""
    lacuna = db.get(Lacuna, lacuna_id)
    if lacuna is None:
        return False
    agora = datetime.now(UTC).replace(tzinfo=None)
    for x in db.scalars(select(Lacuna).where(Lacuna.chave == lacuna.chave, Lacuna.status == "aberta")):
        x.status, x.resolvida_em, x.resolvida_por_insight_id = "resolvida", agora, insight_id
    db.commit()
    return True
