"""Página → trechos que cabem no curador (ADR-005, decisão "página grande").

- Página normal (até LIMITE_TRECHO caracteres): vai INTEIRA, num trecho só. Uma chamada do curador por página.
- Página grande: é cortada nos títulos (#, ## e ###) e as seções vizinhas são juntadas, em ordem, até o limite. Uma
  seção sozinha maior que o limite é dividida entre parágrafos, depois entre linhas e, em último caso, no meio da linha.
- Todo trecho leva no topo o título da página; o da página grande leva também o caminho das seções e "parte i de n".
  É assim que o curador não perde o contexto de um pedaço solto.

Quantos trechos são demais (a página é pulada) é decisão de quem chama: MAX_TRECHOS.
"""
import re
from dataclasses import dataclass

LIMITE_TRECHO = 8000  # caracteres: o mesmo limite de texto que o curador aceita no Registrar (RegistrarIn.texto)
MAX_TRECHOS = 5  # acima disso (~40 mil caracteres) a página é "longa demais" e não vai ao curador
_TITULO_NO_CABECALHO = 150  # o título e o caminho são cortados no cabeçalho, para sobrar espaço para o conteúdo
_CAMINHO_NO_CABECALHO = 200
_RESERVA_CABECALHO = 450  # o cabeçalho de um trecho nunca passa disto

_TITULO_MD = re.compile(r"^(#{1,3}) (.+)$")


@dataclass(frozen=True)
class Trecho:
    texto: str  # o que vai ao curador: cabeçalho de contexto + conteúdo
    parte: int
    total: int


def _cortar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _secoes(markdown: str) -> list[tuple[list[str], str]]:
    """(caminho dos títulos, texto) de cada seção. Um título dentro de um bloco de código não corta nada."""
    secoes: list[tuple[list[str], list[str]]] = [([], [])]
    pilha: list[tuple[int, str]] = []  # (nível, título) dos títulos abertos: "# A" > "## B" dá A › B
    no_codigo = False
    for linha in markdown.split("\n"):
        if linha.startswith("```"):
            no_codigo = not no_codigo
        titulo = None if no_codigo else _TITULO_MD.match(linha)
        if titulo:
            nivel = len(titulo.group(1))
            pilha = [(n, t) for n, t in pilha if n < nivel] + [(nivel, titulo.group(2).strip())]
            secoes.append(([t for _, t in pilha], []))
        secoes[-1][1].append(linha)
    return [(c, "\n".join(linhas).strip("\n")) for c, linhas in secoes if "\n".join(linhas).strip()]


def _quebrar(texto: str, capacidade: int, separadores: tuple[str, ...] = ("\n\n", "\n")) -> list[str]:
    """Divide o texto em pedaços de até `capacidade`, pelo separador mais "grosso" que resolver: parágrafo, linha e,
    se nem a linha couber, no meio dela."""
    if len(texto) <= capacidade:
        return [texto]
    if not separadores:
        return [texto[i: i + capacidade] for i in range(0, len(texto), capacidade)]
    separador, *resto = separadores
    unidades = []
    for parte in texto.split(separador):
        unidades += _quebrar(parte, capacidade, tuple(resto)) if len(parte) > capacidade else [parte]
    return _juntar(unidades, capacidade, separador)


def _juntar(unidades: list[str], capacidade: int, separador: str) -> list[str]:
    """Junta unidades vizinhas enquanto couberem (guloso, em ordem)."""
    grupos: list[str] = []
    for unidade in unidades:
        if grupos and len(grupos[-1]) + len(separador) + len(unidade) <= capacidade:
            grupos[-1] += separador + unidade
        else:
            grupos.append(unidade)
    return grupos


def quebrar(texto: str, capacidade: int) -> list[str]:
    """Pedaços de até `capacidade` caracteres, cortados em parágrafo ou linha (a busca do Drive usa)."""
    return _quebrar(texto, capacidade)


def dividir(titulo: str, markdown: str, rotulo: str = "Página do Notion") -> list[Trecho]:
    """Os trechos de uma página. Página sem texto devolve [] (quem chama decide o que fazer com ela). `rotulo` é o
    começo do cabeçalho de contexto ("Documento do Drive: título")."""
    if not markdown.strip():
        return []
    cabecalho = f"{rotulo}: {_cortar(titulo, _TITULO_NO_CABECALHO)}"
    if len(cabecalho) + 2 + len(markdown) <= LIMITE_TRECHO:
        return [Trecho(texto=f"{cabecalho}\n\n{markdown}", parte=1, total=1)]

    capacidade = LIMITE_TRECHO - _RESERVA_CABECALHO
    unidades: list[tuple[list[str], str]] = []  # (caminho, texto) de até `capacidade` cada
    for caminho, texto in _secoes(markdown):
        unidades += [(caminho, pedaco) for pedaco in _quebrar(texto, capacidade)]

    grupos: list[tuple[list[str], str]] = []  # seções vizinhas juntas; o caminho é o da 1ª seção do grupo
    for caminho, texto in unidades:
        if grupos and len(grupos[-1][1]) + 2 + len(texto) <= capacidade:
            grupos[-1] = (grupos[-1][0], grupos[-1][1] + "\n\n" + texto)
        else:
            grupos.append((caminho, texto))

    total = len(grupos)
    trechos = []
    for i, (caminho, texto) in enumerate(grupos, start=1):
        secao = _cortar(" › ".join(caminho), _CAMINHO_NO_CABECALHO) if caminho else "(início da página)"
        trechos.append(Trecho(
            texto=f"{cabecalho}\nSeção: {secao}\n(parte {i} de {total})\n\n{texto}", parte=i, total=total,
        ))
    return trechos
