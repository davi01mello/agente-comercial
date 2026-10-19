"""Regras de negócio do Cérebro Comercial. Python puro: sem FastAPI, sem banco, sem LLM.

"O LLM propõe, o código dispõe": o que não pode falhar mora aqui, com 100% de cobertura de teste (exigida no CI).
Quem usa (API, curador) só chama estas funções e traduz as exceções para a sua linguagem (409, 422, aviso...).
"""
import re
import unicodedata


class RegraDeNegocio(Exception):
    """Base de todas as violações de regra. A mensagem já vem pronta para mostrar ao usuário."""


class TransicaoInvalida(RegraDeNegocio):
    """Mudança de status que o ciclo de vida não permite (ex.: obsoleto -> validado)."""


class MotivoObrigatorio(RegraDeNegocio):
    """Tentativa de marcar como obsoleto sem dizer por quê."""


class EvidenciaInvalida(RegraDeNegocio):
    """Evidência fora da escala, ou fraca demais para o que se afirma."""


class DadoPessoalNaEntrada(RegraDeNegocio):
    """Texto que ainda vai para o modelo contém dado pessoal. Barrado ANTES de sair do nosso servidor.

    `achados`: os pares (campo, tipo do dado) encontrados, nunca o dado em si. Serve a quem precisa dizer o motivo
    com as próprias palavras (o relatório da importação do Notion), sem reler a mensagem.
    """

    def __init__(self, mensagem: str, achados: list[tuple[str, str]] | None = None):
        super().__init__(mensagem)
        self.achados = list(achados or [])


# Ciclo de vida: de cada status, para quais se pode ir. Qualquer outra mudança é inválida.
# historico_a_validar (fonte antiga) segue o mesmo caminho de proposto (confirmado pelo Davi no PR 1).
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


def _achar_dados_pessoais(campos: dict[str, str | None]) -> list[tuple[str, str]]:
    """Pares (campo, tipo do dado) encontrados. Nunca guarda o dado em si."""
    achados = []
    for campo, texto in campos.items():
        if not texto:
            continue
        for nome, padrao in PADROES_DADO_PESSOAL.items():
            if padrao.search(texto):
                achados.append((campo, nome))
    return achados


def tipos_de_dados_pessoais(texto: str) -> list[str]:
    """Os tipos de dado pessoal que o texto tem ("e-mail", "telefone"...), sem repetir e nunca o dado em si. Serve
    para quem NÃO bloqueia (o Drive, por decisão do time) mas quer avisar na tela de Fontes."""
    return [tipo for _, tipo in _achar_dados_pessoais({"texto": texto})]


def detectar_dados_pessoais(**campos: str | None) -> list[str]:
    """Procura e-mail, CNPJ, CPF e telefone nos campos. NÃO bloqueia: devolve avisos para o humano revisar.

    Uso: detectar_dados_pessoais(descricao=..., contexto_cliente=...)
    O aviso diz o tipo e o campo, mas nunca repete o dado encontrado (ele não deve se espalhar).
    Limitação conhecida: os padrões são só de formato (não conferem dígito verificador), então um número qualquer
    de 11 dígitos (ex.: id de pedido) pode ser apontado como CPF. É aviso para o humano, nunca bloqueio.
    (Antes de chamar o modelo, o bloqueio é `exigir_sem_dados_pessoais`: lá o dado ainda não saiu do servidor.)
    """
    return [
        f"Possível {nome} em '{campo}': dado pessoal de cliente não deve entrar na base (LGPD)."
        for campo, nome in _achar_dados_pessoais(campos)
    ]


def exigir_sem_dados_pessoais(**campos: str | None) -> None:
    """Levanta DadoPessoalNaEntrada se algum campo tiver dado pessoal. Usada ANTES de mandar texto ao modelo.

    Aqui bloquear é certo: a camada gratuita do Gemini pode usar e revisar o que enviamos, então o dado não pode
    sair daqui. Falso positivo custa reescrever o trecho; falso negativo vaza dado de cliente.
    A mensagem diz onde e o quê, mas nunca repete o dado.
    """
    achados = _achar_dados_pessoais(campos)
    if not achados:
        return
    onde = "; ".join(f"{nome} em '{campo}'" for campo, nome in achados)
    raise DadoPessoalNaEntrada(
        f"Encontrei possível dado pessoal: {onde}. Por LGPD, e porque o texto é enviado ao Gemini, ele não pode "
        "entrar. Troque por algo genérico (\"o cliente\", \"[e-mail]\") e envie de novo. Nada foi enviado ao modelo.",
        achados,
    )


# Segmentos que a tela sugere. A forma canônica (com acento) é a daqui: é ela que fica gravada e que a tela compara.
SEGMENTOS_CONHECIDOS = [
    "hotelaria", "varejo", "saúde", "educação", "indústria", "setor público", "startups", "terceiro setor", "outros",
]


def _chave(texto: str) -> str:
    """Forma de comparar: sem acento, minúsculo, espaços únicos. 'Saúde ' e 'saude' dão a mesma chave."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


_CANONICO = {_chave(s): s for s in SEGMENTOS_CONHECIDOS}


def normalizar_segmento(texto: str) -> str:
    """Forma única de gravar e de comparar um segmento.

    Segmento da lista conhecida (em qualquer grafia: 'SAUDE', 'saúde ', 'Setor  Publico') vira a forma com
    acento da lista. Segmento novo continua livre, só em minúsculo e com espaços arrumados (acento mantido).
    """
    chave = _chave(texto)
    return _CANONICO.get(chave) or " ".join(texto.lower().split())
