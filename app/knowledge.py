"""Base de conhecimento do consultor: os itens aprovados do BANCO, um por linha, com o id [INS-n] que ele cita.

Entram só `validado` e `consolidado`. `proposto` (ainda na Fila), `historico_a_validar` (não revisado) e `obsoleto`
(rejeitado ou superado) NUNCA entram: o consultor só usa o que alguém aprovou na Fila.
"""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Insight

logger = logging.getLogger(__name__)

STATUS_NA_BASE = ["validado", "consolidado"]

# Acima disto, mandar a base inteira em toda pergunta fica caro e lento: é o gatilho do RAG (T8, ADR-003 §4).
# Por enquanto só avisamos no log; a base continua indo inteira.
ITENS_ANTES_DO_RAG = 300

TAMANHO_DO_RESUMO = 160  # caracteres da descrição que entram na linha do item

BASE_VAZIA = "(A base ainda não tem nenhum item aprovado. Para qualquer pergunta, diga que a base não cobre o tema.)"


def montar_base(db: Session) -> str:
    """Lê do banco os itens que o consultor pode usar e devolve o texto da base."""
    itens = list(db.scalars(select(Insight).where(Insight.status.in_(STATUS_NA_BASE))))
    return compor_base(itens)


def compor_base(itens: list[Insight]) -> str:
    """A parte sem banco do montar_base (os testes chamam direto): ordena e formata, uma linha por item."""
    if len(itens) > ITENS_ANTES_DO_RAG:
        logger.warning(
            "Base do consultor com %d itens (mais de %d): hora de implementar o RAG (T8). Por enquanto vai inteira.",
            len(itens), ITENS_ANTES_DO_RAG,
        )
    if not itens:
        return BASE_VAZIA
    return "\n".join(formatar(i) for i in sorted(itens, key=_prioridade, reverse=True))


def formatar(item: Insight) -> str:
    """Um item em uma linha: [INS-12] título | tipo | seção | segmento | evid 3 | resumo curto | resultado.

    Ficam de fora o `autor` e o `contexto_cliente` (este pode ter dado pessoal): o consultor não precisa deles.
    """
    campos = [
        f"[INS-{item.id}] {item.titulo}",
        item.tipo,
        item.secao,
        item.segmento or "sem segmento",
        f"evid {item.evidencia}",
        _resumir(item.descricao),
        item.resultado or "sem resultado registrado",
    ]
    return " | ".join(_numa_linha(c) for c in campos)


def _resumir(texto: str) -> str:
    """Os primeiros TAMANHO_DO_RESUMO caracteres, sem cortar palavra no meio."""
    if len(texto) <= TAMANHO_DO_RESUMO:
        return texto
    corte = texto[:TAMANHO_DO_RESUMO].rsplit(" ", 1)[0]
    return corte.rstrip(" ,.;:") + "…"


def _numa_linha(texto: str) -> str:
    """Quebra de linha e "|" no texto do item desmontariam o formato: viram espaço e "/"."""
    return " ".join(texto.replace("|", "/").split())


def _prioridade(item: Insight) -> tuple[int, date, int]:
    """Ordem da base: maior evidência primeiro; no empate, o mais recente (data do evento, ou a do registro se não
    houver); no empate final, o id maior (o registrado por último)."""
    return item.evidencia, item.data_evento or item.criado_em.date(), item.id
