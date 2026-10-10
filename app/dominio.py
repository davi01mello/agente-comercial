"""Regras de negócio do Cérebro Comercial. Python puro: sem FastAPI, sem banco, sem LLM.

"O LLM propõe, o código dispõe": o que não pode falhar mora aqui, com 100% de cobertura de teste (exigida no CI).
Quem usa (API, curador) só chama estas funções e traduz as exceções para a sua linguagem (409, 422, aviso...).
"""
import re


class RegraDeNegocio(Exception):
    """Base de todas as violações de regra. A mensagem já vem pronta para mostrar ao usuário."""


class TransicaoInvalida(RegraDeNegocio):
    """Mudança de status que o ciclo de vida não permite (ex.: obsoleto -> validado)."""


class MotivoObrigatorio(RegraDeNegocio):
    """Tentativa de marcar como obsoleto sem dizer por quê."""


class EvidenciaInvalida(RegraDeNegocio):
    """Evidência fora da escala, ou fraca demais para o que se afirma."""


# Ciclo de vida: de cada status, para quais se pode ir. Qualquer outra mudança é inválida.
# historico_a_validar (fonte antiga) segue o mesmo caminho de proposto: decisão a confirmar com o Davi.
TRANSICOES: dict[str, set[str]] = {
    "proposto": {"validado", "obsoleto"},
    "historico_a_validar": {"validado", "obsoleto"},
    "validado": {"consolidado", "obsoleto"},
    "consolidado": {"obsoleto"},
    "obsoleto": set(),
}


def validar_transicao(de: str, para: str, motivo: str | None = None) -> None:
    """Levanta TransicaoInvalida ou MotivoObrigatorio se a mudança de status não for permitida."""
    if para not in TRANSICOES.get(de, set()):
        raise TransicaoInvalida(f"Não é possível mudar o status de '{de}' para '{para}'.")
    if para == "obsoleto" and not (motivo and motivo.strip()):
        raise MotivoObrigatorio("Para marcar um item como obsoleto, informe o motivo.")


_ALGUM_DIGITO = re.compile(r"\d")


def tem_numero(texto: str | None) -> bool:
    """True se o texto tem pelo menos um algarismo (ex.: "caiu de 9 para 4 minutos").

    É uma heurística: "melhorou no Q3" também passa. Ela barra o resultado sem número nenhum, não garante que
    o número seja uma medição de verdade. Quem revisa na Fila continua sendo o humano.
    """
    return bool(texto and _ALGUM_DIGITO.search(texto))


def validar_insight(tipo: str, evidencia: int, resultado: str | None) -> None:
    """Regras de consistência de um item. Levanta EvidenciaInvalida com a explicação."""
    if evidencia not in (1, 2, 3, 4):
        raise EvidenciaInvalida("A evidência vai de 1 (opinião) a 4 (resultado medido).")
    if tipo == "regra" and evidencia < 3:
        raise EvidenciaInvalida(
            "Para virar regra, a evidência precisa ser 3 (padrão repetido) ou 4 (resultado medido)."
        )
    if evidencia == 4 and not tem_numero(resultado):
        raise EvidenciaInvalida("Evidência 4 (resultado medido) exige um número no campo resultado.")


# Padrões de dado pessoal. CNPJ vem antes de CPF por ser mais longo (evita confusão entre os dois).
PADROES_DADO_PESSOAL: dict[str, re.Pattern[str]] = {
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "CNPJ": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    "CPF": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "telefone": re.compile(r"\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b"),
}


def detectar_dados_pessoais(**campos: str | None) -> list[str]:
    """Procura e-mail, CNPJ, CPF e telefone nos campos. NÃO bloqueia: devolve avisos para o humano revisar.

    Uso: detectar_dados_pessoais(descricao=..., contexto_cliente=...)
    O aviso diz o tipo e o campo, mas nunca repete o dado encontrado (ele não deve se espalhar).
    Limitação conhecida: os padrões são só de formato (não conferem dígito verificador), então um número qualquer
    de 11 dígitos (ex.: id de pedido) pode ser apontado como CPF. É aviso para o humano, nunca bloqueio.
    """
    avisos = []
    for campo, texto in campos.items():
        if not texto:
            continue
        for nome, padrao in PADROES_DADO_PESSOAL.items():
            if padrao.search(texto):
                avisos.append(f"Possível {nome} em '{campo}': dado pessoal de cliente não deve entrar na base (LGPD).")
    return avisos