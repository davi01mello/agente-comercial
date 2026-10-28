"""Busca nos documentos do Drive (T6): acha os pedaços que o consultor recebe junto com a base, citados como [DOC-n].

É busca por palavras (BM25), feita em Python, de propósito: o banco do dev (SQLite) e o de produção (Postgres) não têm a
mesma busca de texto (FTS5 × tsvector), e um acervo de algumas centenas de pedaços cabe na memória. Se um dia passar
de milhares de pedaços, é aqui que entra a busca do banco, ou os embeddings (T8).

Normaliza sem acento e sem maiúscula e tira as palavras vazias do português, para "negociação" achar "Negociacao".
O [DOC-n] é o id da fonte (do documento), não do pedaço: dois pedaços do mesmo documento viram um [DOC-n] só.
"""
import math
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Fonte, TrechoDocumento

MAX_PEDACOS = 5  # os pedaços que o consultor recebe por pergunta (~7.500 caracteres)
MAX_POR_DOCUMENTO = 2  # no máximo 2 do mesmo documento: um só não ocupa o espaço dos outros
K1 = 1.4
B = 0.75
# Documento velho perde um pouco de nota (5% por ano acima de 1 ano, no máximo 30%): empatados no assunto, o recente
# aparece antes. É um desempate, não um filtro: quem quer cortar o antigo de vez usa DRIVE_IDADE_MAX_ANOS.
DESCONTO_POR_ANO = 0.05
DESCONTO_MAXIMO = 0.30
PESO_DO_TITULO = 2  # o título e a pasta entram no índice repetidos: "Briefing Italiana" acha o briefing

PALAVRAS_VAZIAS = frozenset("""
a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sobre entre ate ao aos
e ou mas que se como quando onde qual quais quem ja nao sim mais menos muito muita muitos muitas pouco tem ter
tinha foi sao ser era eh isso isto esse essa esses essas este esta estes estas aquele aquela eu voce vc nos eles
elas ele ela meu minha seu sua nosso nossa lhe me te ha vai vou pode posso precisa preciso fazer faz feito
""".split())

_PALAVRA = re.compile(r"[a-z0-9]{2,}")


def palavras(texto: str) -> list[str]:
    """As palavras do texto para a busca: minúsculas, sem acento e sem as palavras vazias."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [p for p in _PALAVRA.findall(sem_acento) if p not in PALAVRAS_VAZIAS]


@dataclass(frozen=True)
class Achado:
    fonte_id: int  # o n do [DOC-n]
    titulo: str
    url: str
    categoria: str | None
    textos: tuple[str, ...]  # os pedaços achados deste documento, na ordem do documento
    editado_em: date | None = None  # a última edição do arquivo no Drive: o consultor usa para saber qual vale mais


@dataclass(frozen=True)
class _Pedaco:
    id: int
    fonte_id: int
    ordem: int
    texto: str
    termos: Counter
    tamanho: int


class _Indice:
    """O índice em memória: refeito quando os pedaços do banco mudam (a chave é a contagem e o maior id)."""

    def __init__(self, chave: tuple, pedacos: list[_Pedaco], docs: dict[int, tuple[str, str, str | None, date | None]]):
        self.chave = chave
        self.pedacos = pedacos
        self.docs = docs  # fonte_id -> (título, url, categoria, data de edição)
        self.media = (sum(p.tamanho for p in pedacos) / len(pedacos)) if pedacos else 0.0
        frequencia: Counter = Counter()
        for p in pedacos:
            frequencia.update(p.termos.keys())
        n = len(pedacos)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequencia.items()}


_trava = threading.Lock()
_cache: _Indice | None = None


def limpar_cache() -> None:
    """Os testes chamam entre um teste e outro (os ids do SQLite voltam a ser usados)."""
    global _cache
    with _trava:
        _cache = None


def _indice(db: Session) -> _Indice:
    global _cache
    quantos, maior = db.execute(select(func.count(), func.max(TrechoDocumento.id))).one()
    docs_vivos = db.execute(select(func.count(), func.max(Fonte.importado_em)).where(
        Fonte.id.in_(select(TrechoDocumento.fonte_id)))).one()
    chave = (quantos, maior, *docs_vivos)  # um documento renomeado (mesmos pedaços) também refaz o índice
    with _trava:
        if _cache is not None and _cache.chave == chave:
            return _cache
        linhas = db.execute(
            select(TrechoDocumento.id, TrechoDocumento.fonte_id, TrechoDocumento.ordem, TrechoDocumento.texto,
                   Fonte.titulo, Fonte.url, Fonte.categoria, Fonte.editado_em)
            .join(Fonte, Fonte.id == TrechoDocumento.fonte_id)
            .where(Fonte.status != "removida")
        ).all()
        pedacos, docs = [], {}
        for id_, fonte_id, ordem, texto, titulo, url, categoria, editado_em in linhas:
            docs[fonte_id] = (titulo, url, categoria, editado_em.date() if editado_em else None)
            termos = Counter(palavras(texto))
            termos.update({t: PESO_DO_TITULO * c for t, c in Counter(palavras(f"{titulo} {categoria or ''}")).items()})
            pedacos.append(_Pedaco(id_, fonte_id, ordem, texto, termos, sum(termos.values())))
        _cache = _Indice(chave, pedacos, docs)
        return _cache


def fator_de_recencia(editado_em: date | None, hoje: date) -> float:
    """1.0 para o documento de até 1 ano (ou sem data); depois cai 5% por ano, até 0.70."""
    if editado_em is None:
        return 1.0
    anos = (hoje - editado_em).days / 365.25
    return 1.0 - min(DESCONTO_MAXIMO, max(0.0, anos - 1) * DESCONTO_POR_ANO)


def buscar(db: Session, consulta: str, limite: int = MAX_PEDACOS) -> list[Achado]:
    """Os pedaços mais parecidos com a consulta, agrupados por documento (o melhor documento primeiro). Vazio se nada
    tem palavra em comum com a consulta: o consultor então não recebe nenhum documento."""
    termos = set(palavras(consulta))
    if not termos:
        return []
    indice = _indice(db)
    if not indice.pedacos:
        return []

    hoje = datetime.now(UTC).date()
    fatores = {fonte_id: fator_de_recencia(doc[3], hoje) for fonte_id, doc in indice.docs.items()}
    pontuados = []
    for p in indice.pedacos:
        nota = 0.0
        for t in termos:
            f = p.termos.get(t, 0)
            if f:
                nota += indice.idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * p.tamanho / indice.media))
        if nota > 0:
            pontuados.append((nota * fatores[p.fonte_id], p))
    pontuados.sort(key=lambda x: (-x[0], x[1].fonte_id, x[1].ordem))

    escolhidos: list[_Pedaco] = []
    por_documento: Counter = Counter()
    for _, p in pontuados:
        if por_documento[p.fonte_id] < MAX_POR_DOCUMENTO:
            escolhidos.append(p)
            por_documento[p.fonte_id] += 1
            if len(escolhidos) == limite:
                break

    achados: dict[int, list[_Pedaco]] = {}
    for p in escolhidos:  # a ordem de chegada é a do melhor pedaço de cada documento
        achados.setdefault(p.fonte_id, []).append(p)
    return [
        Achado(fonte_id, *indice.docs[fonte_id][:3], tuple(p.texto for p in sorted(ps, key=lambda p: p.ordem)),
               indice.docs[fonte_id][3])
        for fonte_id, ps in achados.items()
    ]


def consulta_da_conversa(mensagem: str, historico: list[dict]) -> str:
    """O que se procura: a pergunta e as duas falas anteriores do usuário (um "e se ele disser que está caro?" só faz
    sentido com o assunto que veio antes)."""
    anteriores = [h["text"] for h in historico if h.get("role") == "user"][-2:]
    return " ".join([*anteriores, mensagem])
