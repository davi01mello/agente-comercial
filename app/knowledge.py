"""Base de conhecimento v0: os arquivos .md da pasta knowledge/, juntos num texto só."""
from pathlib import Path

PASTA = Path(__file__).parent.parent / "knowledge"


def carregar_base() -> str:
    """Lê todos os .md de knowledge/ (em ordem alfabética) e devolve um texto único."""
    partes = []
    for arquivo in sorted(PASTA.glob("*.md")):
        conteudo = arquivo.read_text(encoding="utf-8")
        partes.append(f"## Fonte: {arquivo.name}\n\n{conteudo}")
    return "\n\n".join(partes)