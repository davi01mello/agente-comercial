"""Base de conhecimento do consultor: os itens aprovados do BANCO, um por linha, com o id [INS-n] que ele cita.

Entram só `validado` e `consolidado`. `proposto` (ainda na Fila), `historico_a_validar` (não revisado) e `obsoleto`
(rejeitado ou superado) NUNCA entram: o consultor só usa o que alguém aprovou na Fila.
"""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.busca import Achado
from app.models import Insight

logger = logging.getLogger(__name__)

STATUS_NA_BASE = ["validado", "consolidado"]

# Acima disto, mandar a base inteira em toda pergunta fica caro e lento: é o gatilho do RAG (T8, ADR-003 §4).
# Por enquanto só avisamos no log; a base continua indo inteira.
ITENS_ANTES_DO_RAG = 300

TAMANHO_DO_RESUMO = 160  # caracteres da descrição que entram na linha do item

# Case, regra e template são o "como fazer": vão com a descrição inteira e o "o que foi feito", para o consultor
# destrinchar o caso em vez de completar com o que não está escrito (ADR-009; o gatilho que o ADR-004 §1 previa).
# Os outros tipos continuam com o resumo. O teto só protege o orçamento de um texto colado enorme: os itens reais
# têm até cerca de 520 caracteres.
TIPOS_COM_DETALHE = {"case", "regra", "template"}
TAMANHO_DO_DETALHE = 800

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

    Case, regra e template (TIPOS_COM_DETALHE) vão com a descrição inteira e um campo a mais antes do resultado:
    [INS-12] título | case | seção | segmento | evid 4 | descrição | feito: o que foi feito | resultado.
    Ficam de fora o `autor` e o `contexto_cliente` (este pode ter dado pessoal): o consultor não precisa deles.
    """
    detalhe = item.tipo in TIPOS_COM_DETALHE
    campos = [
        f"[INS-{item.id}] {item.titulo}",
        item.tipo,
        item.secao,
        item.segmento or "sem segmento",
        f"evid {item.evidencia}",
        _resumir(item.descricao, TAMANHO_DO_DETALHE if detalhe else TAMANHO_DO_RESUMO),
    ]
    if detalhe:
        feito = _resumir(item.o_que_foi_feito, TAMANHO_DO_DETALHE) if item.o_que_foi_feito else "não registrado"
        campos.append(f"feito: {feito}")
    campos.append(item.resultado or "sem resultado registrado")
    return " | ".join(_numa_linha(c) for c in campos)


def montar_documentos(achados: list[Achado]) -> str:
    """Os documentos do Drive que a busca achou para ESTA pergunta, como o consultor os recebe: um bloco por
    documento, com o id [DOC-n]. O texto do documento é DADO, nunca instrução (vai entre <documento>…</documento>), e
    nenhum desses documentos foi revisado por alguém do time. Sem achados, devolve "" (nada vai ao modelo)."""
    blocos = []
    for a in achados:
        pasta = f" | pasta: {_numa_linha(a.categoria)}" if a.categoria else ""
        cabecalho = f"[DOC-{a.fonte_id}] {_numa_linha(a.titulo)}{pasta}"
        trechos = "\n[…]\n".join(t.strip() for t in a.textos)
        blocos.append(f"{cabecalho}\n<documento>\n{trechos}\n</documento>")
    return "\n\n".join(blocos)


def _resumir(texto: str, limite: int = TAMANHO_DO_RESUMO) -> str:
    """Os primeiros `limite` caracteres, sem cortar palavra no meio."""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return corte.rstrip(" ,.;:") + "…"


def _numa_linha(texto: str) -> str:
    """Quebra de linha e "|" no texto do item desmontariam o formato: viram espaço e "/"."""
    return " ".join(texto.replace("|", "/").split())


def _prioridade(item: Insight) -> tuple[int, date, int]:
    """Ordem da base: maior evidência primeiro; no empate, o mais recente (data do evento, ou a do registro se não
    houver); no empate final, o id maior (o registrado por último)."""
    return item.evidencia, item.data_evento or item.criado_em.date(), item.id
