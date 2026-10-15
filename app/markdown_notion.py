"""Blocos do Notion → markdown. Funções puras: recebem o JSON que o app/notion.py leu (com os filhos em "_filhos") e
devolvem texto. Nada de rede, banco ou modelo aqui.

O markdown é o que vai para a triagem (dado pessoal, tamanho, duplicata) e, se passar, para o curador. Por isso:
- títulos, listas (inclusive aninhadas), tabelas, links e formatação viram markdown de verdade (spec do Davi);
- o que não é texto (imagem, arquivo, banco de dados, notas de reunião) vira um marcador curto entre colchetes;
- uma pessoa mencionada com @ vira "@pessoa": o nome não vai ao modelo.
"""
import hashlib
import re
import unicodedata

MARCADOR_PESSOA = "@pessoa"

# Blocos que viram só um marcador (o conteúdo deles não é lido).
_MIDIA = {"image": "imagem", "video": "vídeo", "file": "arquivo", "pdf": "PDF", "audio": "áudio"}
_IGNORADOS = {"table_of_contents", "breadcrumb", "template"}
_SO_FILHOS = {"column_list", "column", "synced_block"}  # contêineres: valem os filhos


# --- texto rico -------------------------------------------------------------------------------------------

def _envolver(texto: str, marca: str) -> str:
    """Põe a marca (**, _, ~~, `) em volta do texto, deixando os espaços das pontas de fora ("** a **" quebra)."""
    miolo = texto.strip()
    if not miolo:
        return texto
    inicio = texto[: len(texto) - len(texto.lstrip())]
    fim = texto[len(texto.rstrip()):]
    return f"{inicio}{marca}{miolo}{marca}{fim}"


def _pedaco(rico: dict, formatado: bool) -> str:
    tipo = rico.get("type")
    if tipo == "mention" and rico.get("mention", {}).get("type") == "user":
        return MARCADOR_PESSOA  # o nome da pessoa não vai ao modelo
    if tipo == "equation":
        return f"${rico.get('equation', {}).get('expression', '')}$"
    texto = rico.get("plain_text", "")
    if not formatado:
        return texto
    anotacoes = rico.get("annotations") or {}
    if anotacoes.get("code"):
        texto = _envolver(texto, "`")
    if anotacoes.get("bold"):
        texto = _envolver(texto, "**")
    if anotacoes.get("italic"):
        texto = _envolver(texto, "_")
    if anotacoes.get("strikethrough"):
        texto = _envolver(texto, "~~")
    href = rico.get("href")
    if href and tipo == "text" and texto.strip():
        texto = f"[{texto}]({href})"
    return texto


def texto(ricos: list[dict] | None, formatado: bool = True) -> str:
    """Uma lista de "rich text" do Notion em texto (com markdown se `formatado`)."""
    return "".join(_pedaco(r, formatado) for r in (ricos or []))


def titulo(pagina: dict) -> str:
    """O título de uma página: a propriedade de tipo "title" (numa página comum ela se chama "title"; numa linha de
    banco de dados, tem o nome da coluna). Sem formatação, e com a pessoa mencionada trocada por "@pessoa"."""
    for prop in (pagina.get("properties") or {}).values():
        if prop.get("type") == "title":
            return " ".join(texto(prop.get("title"), formatado=False).split())
    return ""


# --- blocos -----------------------------------------------------------------------------------------------

def _recuar(linhas: list[str], espacos: int) -> list[str]:
    return [(" " * espacos + linha) if linha else linha for linha in linhas]


def _item(marcador: str, conteudo: str, filhos: list[str]) -> list[str]:
    """Um item de lista: a 1ª linha com o marcador; as linhas seguintes e os filhos recuados até o texto do item."""
    recuo = len(marcador)
    primeira, *resto = (conteudo or "").split("\n")
    return [marcador + primeira, *_recuar(resto, recuo), *_recuar(filhos, recuo)]


def _celula(ricos: list[dict]) -> str:
    """Uma célula de tabela numa linha só: '|' viraria uma coluna a mais, e a quebra de linha quebraria a tabela."""
    return " ".join(texto(ricos).replace("|", "/").split())


def _tabela(bloco: dict) -> list[str]:
    linhas = [b for b in bloco.get("_filhos", []) if b.get("type") == "table_row"]
    if not linhas:
        return []
    largura = bloco["table"].get("table_width") or len(linhas[0]["table_row"]["cells"])
    celulas = [[_celula(c) for c in linha["table_row"]["cells"]] for linha in linhas]
    celulas = [linha + [""] * (largura - len(linha)) for linha in celulas]

    def formatar(linha: list[str]) -> str:
        return "| " + " | ".join(linha) + " |"

    if bloco["table"].get("has_column_header"):
        cabecalho, corpo = celulas[0], celulas[1:]
    else:  # o markdown exige um cabeçalho: sem um no Notion, ele fica vazio e todas as linhas vão para o corpo
        cabecalho, corpo = [""] * largura, celulas
    return [formatar(cabecalho), formatar(["---"] * largura), *(formatar(linha) for linha in corpo)]


def _bloco(bloco: dict, numero: int) -> list[str]:
    """As linhas de markdown de um bloco (com os filhos). `numero` é a posição dele numa lista numerada."""
    tipo = bloco.get("type", "")
    dados = bloco.get(tipo) or {}
    filhos = _blocos(bloco.get("_filhos", []))
    if bloco.get("_profundo_demais"):
        filhos.append("[conteúdo aninhado demais (não importado)]")
    rico = texto(dados.get("rich_text"))

    if tipo == "paragraph":
        return ([rico] if rico.strip() else []) + filhos
    if tipo in ("heading_1", "heading_2", "heading_3"):
        return [f"{'#' * int(tipo[-1])} {rico}"] + ([""] + filhos if filhos else [])
    if tipo == "bulleted_list_item":
        return _item("- ", rico, filhos)
    if tipo == "numbered_list_item":
        return _item(f"{numero}. ", rico, filhos)
    if tipo == "to_do":
        return _item("- [x] " if dados.get("checked") else "- [ ] ", rico, filhos)
    if tipo == "toggle":
        return _item("- ", rico, filhos)
    if tipo in ("quote", "callout"):
        emoji = (dados.get("icon") or {}).get("emoji") if tipo == "callout" else None
        linhas = (f"{emoji} {rico}" if emoji else rico).split("\n") + filhos
        return [f"> {linha}" if linha else ">" for linha in linhas]
    if tipo == "code":
        return [f"```{dados.get('language', '')}", *texto(dados.get("rich_text"), formatado=False).split("\n"), "```"]
    if tipo == "divider":
        return ["---"]
    if tipo == "equation":
        return [f"$${dados.get('expression', '')}$$"]
    if tipo == "table":
        return _tabela(bloco)
    if tipo in _SO_FILHOS:
        return filhos
    if tipo == "child_page":
        return [f"[subpágina: {dados.get('title', '')}]"]
    if tipo == "child_database":
        return [f"[banco de dados: {dados.get('title', '')} (não importado)]"]
    if tipo in ("bookmark", "embed", "link_preview"):
        url = dados.get("url", "")
        legenda = texto(dados.get("caption"), formatado=False).strip()
        return [f"[{legenda or url}]({url})"] if url else []
    if tipo == "link_to_page":
        return ["[link para outra página]"]
    if tipo in _MIDIA:
        legenda = texto(dados.get("caption"), formatado=False).strip()
        return [f"[{_MIDIA[tipo]}: {legenda}]" if legenda else f"[{_MIDIA[tipo]}]"]
    if tipo in ("meeting_notes", "transcription"):
        return ["[notas de reunião (não importadas)]"]
    if tipo in _IGNORADOS:
        return []
    nome = dados.get("block_type", tipo) if tipo == "unsupported" else tipo
    return [f"[bloco não suportado: {nome}]"]


_ITENS_DE_LISTA = {"bulleted_list_item", "numbered_list_item", "to_do", "toggle"}


def _blocos(blocos: list[dict]) -> list[str]:
    """Os blocos irmãos, em ordem. Itens de lista seguidos ficam colados; o resto é separado por uma linha em branco.
    A numeração de uma lista numerada recomeça quando outro tipo de bloco aparece no meio."""
    linhas: list[str] = []
    numero = 0
    anterior = None
    for bloco in blocos:
        tipo = bloco.get("type")
        numero = numero + 1 if tipo == "numbered_list_item" else 0
        saida = _bloco(bloco, numero)
        if not saida:
            continue
        if linhas and not (tipo in _ITENS_DE_LISTA and anterior in _ITENS_DE_LISTA):
            linhas.append("")
        linhas += saida
        anterior = tipo
    return linhas


def para_markdown(blocos: list[dict]) -> str:
    """Os blocos de uma página (como o LeitorNotion.blocos devolve) em markdown normalizado."""
    return normalizar("\n".join(_blocos(blocos)))


# --- normalização, hash e tamanho -----------------------------------------------------------------------

def normalizar(markdown: str) -> str:
    """Forma única do texto, para o hash não mudar à toa: Unicode NFC, sem espaço no fim das linhas, no máximo uma
    linha em branco seguida e sem linhas em branco nas pontas."""
    texto_nfc = unicodedata.normalize("NFC", markdown)
    linhas = [linha.rstrip() for linha in texto_nfc.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip("\n")


def hash_conteudo(markdown: str) -> str:
    """SHA-256 do markdown normalizado. O título fica de fora: renomear a página não é conteúdo novo."""
    return hashlib.sha256(normalizar(markdown).encode("utf-8")).hexdigest()


_MARCADORES = re.compile(
    r"\[(subpágina|banco de dados|imagem|vídeo|arquivo|PDF|áudio|notas de reunião|link para outra página|"
    r"bloco não suportado|conteúdo aninhado demais)[^\]]*\]"
)


def caracteres_de_texto(markdown: str) -> int:
    """Quanto texto de verdade a página tem: sem os títulos, sem os marcadores ([subpágina: …], [imagem]...) e sem
    espaços. Serve para saber se a página está vazia (uma página-índice, só com links para subpáginas)."""
    sem_titulos = "\n".join(linha for linha in markdown.split("\n") if not linha.lstrip().startswith("#"))
    return len("".join(_MARCADORES.sub("", sem_titulos).split()))
