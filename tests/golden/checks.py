"""O que o golden set confere em cada resposta do consultor. Fica fora do test_golden.py para ter testes sem o
Gemini (tests/test_golden_checks.py): um check errado reprovaria uma resposta boa, ou aprovaria uma ruim.

[regra] são as regras do consultor desde o ADR-004 (citação e lacuna). [persona] são as decisões do ADR-009, que dá
para conferir por código; tom, crítica e formato dos avisos ficam na nota humana da rodada.
"""
import re
import unicodedata

LACUNA = "A base não cobre"  # a frase do app/prompts/consultor.md que o app/lacunas.py procura
# Qualquer INS-n, dentro ou fora de colchete: um id inventado num grupo ("[INS-2, INS-99]") também é pego.
CITACAO = re.compile(r"INS-(\d+)")
# O grupo que a tela não transforma em link (o cerebro.js só reconhece [INS-n] sozinho).
AGRUPADA = re.compile(r"\[INS-\d+\s*[,;]")
COLCHETE = re.compile(r"\[(?:INS|DOC)-\d+\]")  # sai da contagem de palavras
# Emojis e símbolos pictográficos (inclui ✅, ⭐ e o seletor de variação); setas e marcadores de lista não entram.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
MAX_PERGUNTAS = 2  # decisão da persona: no máximo 2 perguntas de volta
TETO_PALAVRAS = 160  # a meta é cerca de 120; a folga evita reprovar por uma frase


def citados(resposta: str) -> set[int]:
    return {int(n) for n in CITACAO.findall(resposta)}


def palavras(resposta: str) -> int:
    """Palavras fora os [INS-n] e [DOC-n]: o id não pesa na leitura."""
    return len(re.findall(r"\w+", COLCHETE.sub(" ", resposta)))


def perguntas(resposta: str) -> int:
    """Quantos "?" a resposta tem. Conta também a pergunta sugerida para o cliente: por isso existe o `livre`."""
    return resposta.count("?")


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def falhas_de(caso: dict, resposta: str, ids: set[int]) -> list[str]:
    """Tudo o que a resposta descumpre (lista vazia: passou). `ids` são os ids da base que o modelo recebeu."""
    cit = citados(resposta)
    falhas = []

    if inventados := sorted(cit - ids):
        falhas.append(f"[regra] citou id que não existe na base: {inventados}")
    if AGRUPADA.search(resposta):
        falhas.append("[regra] citação agrupada ([INS-2, INS-7]): a tela só faz link de [INS-n] sozinho")
    if caso["coberta"] and not set(caso["esperados"]) & cit:
        falhas.append(f"[regra] não citou nenhum dos esperados {caso['esperados']}")
    if not caso["coberta"] and LACUNA not in resposta:
        falhas.append("[regra] a base não cobre a pergunta, mas a resposta não admitiu a lacuna")

    livre = set(caso.get("livre", []))
    if EMOJI.search(resposta):
        falhas.append("[persona] tem emoji")
    if "perguntas" not in livre and perguntas(resposta) > MAX_PERGUNTAS:
        falhas.append(f"[persona] {perguntas(resposta)} perguntas (máximo {MAX_PERGUNTAS})")
    if "teto" not in livre and palavras(resposta) > TETO_PALAVRAS:
        falhas.append(f"[persona] {palavras(resposta)} palavras (teto {TETO_PALAVRAS})")
    if faltando := sorted(set(caso.get("deve_citar", [])) - cit):
        falhas.append(f"[persona] não citou {faltando}")
    if caso.get("pergunta_de_volta"):
        if perguntas(resposta) == 0:
            falhas.append("[persona] pergunta vaga, mas a resposta não perguntou nada de volta")
        if LACUNA in resposta:
            falhas.append("[persona] pergunta vaga respondida com 'A base não cobre' (registraria lacuna falsa)")
    if caso.get("registrar") and "registr" not in resposta.lower():
        falhas.append("[persona] não sugeriu registrar o aprendizado")
    if caso.get("proximo_passo") and "proximo passo" not in _sem_acento(resposta):
        falhas.append("[persona] não fechou com 'Próximo passo'")
    return falhas
