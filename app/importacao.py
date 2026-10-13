"""Importação do Notion (T4): páginas → tabela `fontes` (o staging) → triagem. Decisões no
docs/adr-005-importacao-notion.md.

Uma execução (`importar`) faz, em ordem:
1. **sincronizar**: lê as páginas compartilhadas com a integração e, só para as novas ou editadas, os blocos;
   converte em markdown e faz a triagem: dado pessoal, página vazia, duplicata e página longa demais;
2. confere as páginas que sumiram do Notion (só quando a lista veio completa).

Rodar duas vezes seguidas não muda nada: página com o mesmo `last_edited_time` nem é relida, e página relida com o
mesmo hash não gera nada novo. O `--dry-run` faz as mesmas leituras e a mesma triagem, mas não grava nada.

Nunca loga texto de página nem título: o log tem só contagens. O relatório (impresso pelo script) mostra títulos,
e o título com dado pessoal sai omitido.
"""
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dominio, markdown_notion, trechos
from app.config import settings
from app.models import ExecucaoImportacao, Fonte
from app.notion import ErroNotion, LeitorNotion, na_lixeira, url_da_pagina
from app.trechos import Trecho

logger = logging.getLogger(__name__)

ORIGEM = "notion"
MIN_CARACTERES = 20  # menos que isso de texto (sem títulos e marcadores): página "vazia", não vai ao modelo
TITULO_OMITIDO = "(título omitido: tem dado pessoal)"
SEM_TITULO = "(sem título)"
TITULO_MAX = 500  # o tamanho da coluna fontes.titulo (o Notion aceita títulos maiores; o Postgres recusaria)
PULADAS = {"vazia", "pulada_dado_pessoal", "pulada_longa", "pulada_duplicata"}
A_CURAR = {"a_curar", "falha"}  # o que o curador (PR 2) processa
_NOME_DO_CAMPO = {"titulo": "título", "conteudo": "conteúdo"}

# --- estimativa de custo (--dry-run e teto de gasto), SEM chamar o modelo -------------------------------------
# Medidos com o count_tokens do Gemini (ADR-003 §4): as instruções do curador, o prompt de relações e a linha de
# candidato. SUPOSIÇÕES (não há medição ainda): os tokens de saída. Conferir com o custo do log depois da 1ª rodada
# real e ajustar aqui (ADR-005).
TOKENS_INSTRUCOES_CURADOR = 1976  # base.md + curador.md (medido)
TOKENS_EXTRA_CURAR = 60  # o embrulho <texto_do_usuario> e o aviso de turno (estimado)
TOKENS_SAIDA_CURAR = 800  # SUPOSIÇÃO: o JSON da proposta (~350) mais o raciocínio
TOKENS_ENTRADA_RELACIONAR = 1187  # 257 do prompt + 30 candidatos × 26 (o pior caso) + ~150 do item novo
TOKENS_SAIDA_RELACIONAR = 100  # SUPOSIÇÃO
CARACTERES_POR_TOKEN = 4  # acertou o formato enxuto do consultor (70 estimados contra 73 medidos, ADR-004 §1)


@dataclass(frozen=True)
class Estimativa:
    chamadas: int
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float


def estimar(partes: list[Trecho]) -> Estimativa:
    """Quanto o curador gastaria com estes trechos: uma chamada "curar" e uma "relacionar" por trecho (a de relações
    só acontece se houver candidatos; a estimativa supõe que sempre há). Preços do .env, os mesmos do log."""
    entrada = sum(
        TOKENS_INSTRUCOES_CURADOR + TOKENS_EXTRA_CURAR + math.ceil(len(t.texto) / CARACTERES_POR_TOKEN)
        + TOKENS_ENTRADA_RELACIONAR
        for t in partes
    )
    saida = len(partes) * (TOKENS_SAIDA_CURAR + TOKENS_SAIDA_RELACIONAR)
    custo = (entrada * settings.preco_entrada_1m + saida * settings.preco_saida_1m) / 1_000_000
    return Estimativa(chamadas=2 * len(partes), tokens_entrada=entrada, tokens_saida=saida, custo_usd=custo)


def _agora() -> datetime:
    """UTC sem fuso, como o resto do banco (o CURRENT_TIMESTAMP do SQLite é UTC). Os testes trocam."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class PaginaLida:
    """Uma linha do relatório. `titulo` já é seguro para mostrar (sem dado pessoal)."""

    id_externo: str
    titulo: str
    acao: str  # nova | alterada | sem mudança | pendente | falha | removida
    status: str = ""  # o status da fonte depois desta execução
    motivo: str = ""  # por que foi pulada, falhou ou saiu
    trechos: list[Trecho] = field(default_factory=list)  # só de quem vai ao curador


@dataclass
class Relatorio:
    dry_run: bool
    execucao_id: int | None = None
    paginas: list[PaginaLida] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    requisicoes_notion: int = 0
    lidas: int = 0  # as páginas que vieram na busca do Notion nesta execução

    def _com(self, *acoes: str) -> list[PaginaLida]:
        return [p for p in self.paginas if p.acao in acoes]

    @property
    def novas(self) -> list[PaginaLida]:
        return self._com("nova")

    @property
    def alteradas(self) -> list[PaginaLida]:
        return self._com("alterada")

    @property
    def sem_mudanca(self) -> list[PaginaLida]:
        return self._com("sem mudança")

    @property
    def puladas(self) -> list[PaginaLida]:  # só as puladas NESTA execução (novas ou alteradas)
        return [p for p in self._com("nova", "alterada") if p.status in PULADAS]

    @property
    def falhas(self) -> list[PaginaLida]:
        return self._com("falha")

    @property
    def removidas(self) -> list[PaginaLida]:
        return self._com("removida")

    @property
    def a_curar(self) -> list[PaginaLida]:
        return [p for p in self.paginas if p.trechos]

    @property
    def estimativa(self) -> Estimativa:
        """O custo estimado do curador para tudo o que espera por ele."""
        return estimar([t for p in self.a_curar for t in p.trechos])


# --- a execução ---------------------------------------------------------------------------------------------

def importar(
    leitor: LeitorNotion, db: Session, *, dry_run: bool = False, limite_paginas: int | None = None
) -> Relatorio:
    """Roda uma importação. Fora do dry-run, registra a execução (início, fim e as contagens da spec).

    Levanta ErroNotion se a lista de páginas não puder ser lida (token inválido, sem rede...). Uma página que falha
    sozinha não derruba a execução: vira uma "falha" no relatório e é tentada de novo na próxima vez.
    """
    relatorio = Relatorio(dry_run=dry_run)
    execucao = None
    if not dry_run:
        execucao = ExecucaoImportacao(inicio=_agora())
        db.add(execucao)
        db.commit()
        relatorio.execucao_id = execucao.id
    try:
        _sincronizar(leitor, db, relatorio, limite_paginas)
    except BaseException:
        db.rollback()  # o que estava pela metade não entra; a execução é fechada abaixo, numa transação limpa
        raise
    finally:
        relatorio.requisicoes_notion = leitor.requisicoes
        if execucao is not None:
            execucao.fim = _agora()
            execucao.paginas_lidas = relatorio.lidas
            execucao.paginas_novas = len(relatorio.novas)
            execucao.paginas_alteradas = len(relatorio.alteradas)
            execucao.paginas_falhas = len(relatorio.falhas)
            db.commit()
        logger.info(json.dumps({  # só números: nunca título nem texto
            "evento": "importacao_notion",
            "dry_run": dry_run,
            "lidas": relatorio.lidas,
            "novas": len(relatorio.novas),
            "alteradas": len(relatorio.alteradas),
            "puladas": len(relatorio.puladas),
            "falhas": len(relatorio.falhas),
            "removidas": len(relatorio.removidas),
            "requisicoes_notion": relatorio.requisicoes_notion,
        }))
    return relatorio


def _sincronizar(leitor: LeitorNotion, db: Session, relatorio: Relatorio, limite_paginas: int | None) -> None:
    busca = leitor.paginas(limite=limite_paginas)
    vistas: set[str] = set()
    hashes: dict[str, str] = {}  # hash -> título das páginas tratadas nesta execução (duplicatas no dry-run)
    for pagina in busca.paginas:
        vistas.add(pagina["id"])
        relatorio.lidas += 1
        _sincronizar_pagina(leitor, db, pagina, relatorio, hashes)

    if busca.completa:
        _conferir_removidas(leitor, db, vistas, relatorio)
    else:
        relatorio.avisos.append(
            "A lista de páginas veio incompleta (--limite-paginas, ou o Notion cortou a busca): páginas que sumiram "
            "do Notion não foram conferidas nesta execução."
        )
    _listar_pendentes(db, vistas, relatorio)


def _titulo_seguro(titulo: str) -> str:
    """O título para mostrar e gravar: omitido se tiver dado pessoal (ele vai para o relatório e para o banco)."""
    try:
        dominio.exigir_sem_dados_pessoais(titulo=titulo)
    except dominio.DadoPessoalNaEntrada:
        return TITULO_OMITIDO
    if len(titulo) > TITULO_MAX:
        return titulo[: TITULO_MAX - 1] + "…"
    return titulo or SEM_TITULO


def _tem_dado_pessoal(titulo: str, markdown: str) -> bool:
    try:
        dominio.exigir_sem_dados_pessoais(titulo=titulo, conteudo=markdown)
    except dominio.DadoPessoalNaEntrada:
        return True
    return False


def _data(texto: str) -> datetime:
    """O last_edited_time do Notion ("2026-10-01T12:34:00.000Z") em UTC sem fuso, como o banco guarda."""
    return datetime.fromisoformat(texto).astimezone(UTC).replace(tzinfo=None)


def _sincronizar_pagina(
    leitor: LeitorNotion, db: Session, pagina: dict, relatorio: Relatorio, hashes: dict[str, str]
) -> None:
    pid = pagina["id"]
    titulo = markdown_notion.titulo(pagina)
    seguro = _titulo_seguro(titulo)
    editado = _data(pagina["last_edited_time"])
    fonte = db.scalar(select(Fonte).where(Fonte.origem == ORIGEM, Fonte.id_externo == pid))
    existe = fonte is not None and fonte.status != "removida"  # a que voltou do lixo é tratada como alterada

    if existe and fonte.editado_em == editado:  # nem lê os blocos: nada mudou
        relatorio.paginas.append(_sem_mudanca(fonte))
        return

    try:
        markdown = markdown_notion.para_markdown(leitor.blocos(pid))
    except ErroNotion as e:  # a página fica como estava; a próxima execução tenta de novo
        relatorio.paginas.append(PaginaLida(pid, seguro, "falha", motivo=str(e)))
        return
    hash_novo = markdown_notion.hash_conteudo(markdown)

    # Editada sem mudar o texto (ou só o título). A exceção é o dado pessoal no título: se ele apareceu ou sumiu, a
    # página passa pela triagem de novo (um título corrigido libera a página; um que ganhou um telefone a barra).
    if existe and fonte.hash_conteudo == hash_novo and (
        _tem_dado_pessoal(titulo, markdown) == (fonte.status == "pulada_dado_pessoal")
    ):
        if not relatorio.dry_run:
            fonte.editado_em = editado
            fonte.titulo = seguro
            db.commit()
        relatorio.paginas.append(_sem_mudanca(fonte))
        return

    status, motivo, partes = _triar(db, pid, titulo, markdown, hash_novo, hashes)
    if status != "pulada_dado_pessoal":
        hashes.setdefault(hash_novo, seguro)
    relatorio.paginas.append(PaginaLida(pid, seguro, "alterada" if fonte else "nova", status, motivo, partes))
    if relatorio.dry_run:
        return

    if fonte is None:
        fonte = Fonte(origem=ORIGEM, id_externo=pid)
        db.add(fonte)
    fonte.titulo = seguro
    fonte.url = url_da_pagina(pid)
    fonte.markdown = None if status == "pulada_dado_pessoal" else markdown  # o texto com dado pessoal não é guardado
    fonte.hash_conteudo = hash_novo
    fonte.editado_em = editado
    fonte.importado_em = _agora()
    fonte.status = status
    db.commit()


def _sem_mudanca(fonte: Fonte) -> PaginaLida:
    """Página que não mudou. Se ainda espera o curador (a execução anterior parou no teto, ou ele falhou), os trechos
    vêm junto, refeitos a partir do markdown guardado."""
    partes = trechos.dividir(fonte.titulo, fonte.markdown or "") if fonte.status in A_CURAR else []
    return PaginaLida(fonte.id_externo, fonte.titulo, "sem mudança", fonte.status, trechos=partes)


def _triar(
    db: Session, pid: str, titulo: str, markdown: str, hash_novo: str, hashes: dict[str, str]
) -> tuple[str, str, list[Trecho]]:
    """(status, motivo, trechos). A ordem importa: o dado pessoal vem primeiro, porque a página com dado pessoal não
    pode nem ser dividida nem comparada para ir ao modelo depois."""
    try:  # a MESMA regra do curador (decisão 2 do Davi): e-mail, CPF, CNPJ ou telefone, no título ou no texto
        dominio.exigir_sem_dados_pessoais(titulo=titulo, conteudo=markdown)
    except dominio.DadoPessoalNaEntrada as e:
        motivo = ", ".join(f"{tipo} no {_NOME_DO_CAMPO.get(campo, campo)}" for campo, tipo in e.achados)
        return "pulada_dado_pessoal", motivo, []

    if markdown_notion.caracteres_de_texto(markdown) < MIN_CARACTERES:
        return "vazia", f"menos de {MIN_CARACTERES} caracteres de texto", []

    original = hashes.get(hash_novo) or db.scalar(
        select(Fonte.titulo).where(
            Fonte.origem == ORIGEM,
            Fonte.hash_conteudo == hash_novo,
            Fonte.id_externo != pid,
            Fonte.status.not_in(["removida", "pulada_dado_pessoal", "pulada_duplicata"]),
        ).order_by(Fonte.id).limit(1)
    )
    if original:
        return "pulada_duplicata", f"mesmo conteúdo de “{original}”", []

    partes = trechos.dividir(_titulo_seguro(titulo), markdown)
    if len(partes) > trechos.MAX_TRECHOS:
        return "pulada_longa", f"{len(partes)} trechos (limite {trechos.MAX_TRECHOS})", []
    return "a_curar", "", partes


def _conferir_removidas(leitor: LeitorNotion, db: Session, vistas: set[str], relatorio: Relatorio) -> None:
    """As fontes que não vieram na busca: confere uma a uma. Na lixeira ou 404 (apagada ou não compartilhada) vira
    `removida`. Se a página ainda existe, o search só não a listou desta vez: nada muda."""
    sumidas = db.scalars(
        select(Fonte).where(Fonte.origem == ORIGEM, Fonte.status != "removida", Fonte.id_externo.not_in(vistas))
        .order_by(Fonte.id)
    )
    for fonte in list(sumidas):
        try:
            pagina = leitor.pagina(fonte.id_externo)
        except ErroNotion as e:
            relatorio.paginas.append(PaginaLida(fonte.id_externo, fonte.titulo, "falha", fonte.status, str(e)))
            continue
        if pagina is not None and not na_lixeira(pagina):
            continue
        motivo = "na lixeira do Notion" if pagina is not None else "apagada ou sem compartilhamento"
        relatorio.paginas.append(PaginaLida(fonte.id_externo, fonte.titulo, "removida", "removida", motivo))
        if not relatorio.dry_run:
            fonte.status = "removida"
            db.commit()


def _listar_pendentes(db: Session, vistas: set[str], relatorio: Relatorio) -> None:
    """Fontes que esperam o curador e não vieram nesta busca (ex.: com --limite-paginas): entram no relatório para
    a estimativa do --dry-run e para o curador saber o que falta. As que já estão no relatório (removidas, ou que
    falharam na conferência) ficam de fora."""
    no_relatorio = vistas | {p.id_externo for p in relatorio.paginas}
    pendentes = db.scalars(
        select(Fonte).where(Fonte.origem == ORIGEM, Fonte.status.in_(A_CURAR), Fonte.id_externo.not_in(no_relatorio))
        .order_by(Fonte.id)
    )
    for fonte in pendentes:
        partes = trechos.dividir(fonte.titulo, fonte.markdown or "")
        relatorio.paginas.append(PaginaLida(fonte.id_externo, fonte.titulo, "pendente", fonte.status, trechos=partes))
