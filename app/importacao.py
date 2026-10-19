"""Importação do Notion (T4): páginas → tabela `fontes` (o staging) → triagem. Decisões no
docs/adr-005-importacao-notion.md.

Uma execução (`importar`) faz, em ordem:
1. **sincronizar**: lê as páginas compartilhadas com a integração e, só para as novas ou editadas, os blocos;
   converte em markdown e faz a triagem: dado pessoal, página vazia, duplicata e página longa demais;
2. confere as páginas que sumiram do Notion (só quando a lista veio completa);
3. **curar** (só fora do dry-run e só com teto de gasto): o curador propõe um item por trecho das fontes que
   esperam por ele. Os itens entram na Fila como `historico_a_validar`, todos os de uma página ou nenhum.

Quando uma página já importada passa pela triagem de novo (mudou) ou sai do Notion, os itens dela que ninguém
revisou viram `obsoleto`; os aprovados não mudam (ADR-005 §3).

Rodar duas vezes seguidas não muda nada: página com o mesmo `last_edited_time` nem é relida, e página relida com o
mesmo hash não gera nada novo. O `--dry-run` faz as mesmas leituras e a mesma triagem, mas não muda nenhuma fonte nem
chama o modelo: só a execução é gravada (com dry_run=True).

Toda execução fica em `execucoes_importacao`, com o status, a fase e as contagens gravados a cada página: é por ali
que a tela acompanha uma execução pedida pela API (POST /fontes/sincronizar).

Nunca loga texto de página nem título: o log tem só contagens. O relatório (impresso pelo script) mostra títulos,
e o título com dado pessoal sai omitido.
"""
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import curadoria, dominio, llm, markdown_notion, trechos
from app.config import settings
from app.db import SessionLocal
from app.models import MOTIVO_MAX, ExecucaoImportacao, Fonte, HistoricoStatus, Insight, Relacao
from app.notion import ErroNotion, LeitorNotion, na_lixeira, url_da_pagina
from app.trechos import Trecho

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class Origem:
    """O que muda de uma fonte para outra no pipeline (a triagem e a leitura são de cada uma; o curador é comum)."""

    nome: str  # um de ORIGENS: também é o Insight.fonte dos itens
    autor: str  # o autor dos itens importados e o por_quem do histórico: nunca o nome de uma pessoa
    rotulo: str  # "do Notion": o "Importado do Notion (execução #n)" do histórico
    barra_dado_pessoal: bool  # Notion: dado pessoal nunca vai ao modelo. Drive: decisão do Davi, o texto é privado


NOTION = Origem("notion", "importação Notion", "do Notion", barra_dado_pessoal=True)
DRIVE = Origem("drive", "importação Drive", "do Drive", barra_dado_pessoal=False)
ORIGEM = NOTION.nome
AUTOR = NOTION.autor
FOLGA_DO_TETO = 2  # antes de cada página: gasto real + 2 × a estimativa dela precisa caber no teto (ADR §4.6)
MIN_CARACTERES = 20  # menos que isso de texto (sem títulos e marcadores): página "vazia", não vai ao modelo
TITULO_OMITIDO = "(título omitido: tem dado pessoal)"
SEM_TITULO = "(sem título)"
TITULO_MAX = 500  # o tamanho da coluna fontes.titulo (o Notion aceita títulos maiores; o Postgres recusaria)
PULADAS = {"vazia", "pulada_dado_pessoal", "pulada_longa", "pulada_duplicata"}
A_CURAR = {"a_curar", "falha"}  # o que o curador (PR 2) processa
_NOME_DO_CAMPO = {"titulo": "título", "conteudo": "conteúdo"}

# --- estimativa de custo (--dry-run e teto de gasto), SEM chamar o modelo -------------------------------------
# Medidos com o count_tokens do Gemini (ADR-003 §4): as instruções do curador, o prompt de relações e a linha de
# candidato. A saída do curador foi medida na 1ª rodada real (ADR-005 §5): 282 chamadas, média de 1.223 tokens.
TOKENS_INSTRUCOES_CURADOR = 1976  # base.md + curador.md (medido)
TOKENS_EXTRA_CURAR = 60  # o embrulho <texto_do_usuario> e o aviso de turno (estimado)
TOKENS_SAIDA_CURAR = 1250  # medido: ~280 do JSON da proposta + ~940 de raciocínio (era 800, uma suposição)
TOKENS_ENTRADA_RELACIONAR = 1187  # 257 do prompt + 30 candidatos × 26 (o pior caso) + ~150 do item novo
TOKENS_SAIDA_RELACIONAR = 100  # medido: 145 em 16 chamadas; o pior caso da entrada já cobre a diferença
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
    # o curador (só fora do dry-run e com teto)
    teto_usd: float | None = None
    curadas: list[PaginaLida] = field(default_factory=list)  # os itens delas entraram na Fila
    falhas_do_curador: list[PaginaLida] = field(default_factory=list)  # nada delas entrou; tentadas de novo depois
    esperando: list[PaginaLida] = field(default_factory=list)  # não couberam no teto: ficam para a próxima
    insights_propostos: int = 0
    custo_real_usd: float = 0.0
    obsoletos: int = 0  # itens pendentes de páginas que mudaram ou saíram do Notion
    aprovados_de_paginas_mudadas: int = 0  # itens já aprovados dessas páginas: não mudam, alguém confere à mão

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
    def parou_no_teto(self) -> bool:
        return bool(self.esperando)

    @property
    def estimativa(self) -> Estimativa:
        """O custo estimado do curador para tudo o que espera por ele."""
        return estimar([t for p in self.a_curar for t in p.trechos])


# --- a execução ---------------------------------------------------------------------------------------------

class FaltaConfiguracao(Exception):
    """Falta algo no .env para esta execução. A mensagem já vem pronta para quem pediu."""


def conferir_configuracao(dry_run: bool) -> None:
    """Antes de ler o Notion. Fora do dry-run, sem a chave do Gemini o curador não roda, e toda página viraria
    `falha`. O NOTION_TOKEN é conferido pelo LeitorNotion, quando ele é criado."""
    if not dry_run and not settings.gemini_api_key:
        raise FaltaConfiguracao("Falta GEMINI_API_KEY no .env. Sem ela o curador não roda; para só ver o que seria "
                                "importado, use o dry-run.")


def executar(
    leitor, *, dry_run: bool = False, limite_paginas: int | None = None, teto_usd: float | None = None,
    execucao_id: int | None = None, origem: Origem = NOTION, sincronizar=None,
) -> Relatorio:
    """A importação com a própria sessão do banco: a única porta de entrada, para o script e para a API (em segundo
    plano, quando a sessão da requisição já fechou). Os erros são os de `importar`."""
    with SessionLocal() as db:
        return importar(leitor, db, dry_run=dry_run, limite_paginas=limite_paginas, teto_usd=teto_usd,
                        execucao_id=execucao_id, origem=origem, sincronizar=sincronizar)


def marcar_interrompidas(db: Session) -> int:
    """Na subida do servidor: uma execução que ainda está `rodando` é de um servidor que parou no meio dela (caiu,
    foi morto, ou levou dois Ctrl+C: o 1º, e o --reload, esperam a execução acabar). Ela vira `erro`, "interrompida";
    sem isso, travaria o POST /fontes/sincronizar (409) para sempre. O que ela já gravou fica: cada página entra
    inteira ou não entra. Devolve quantas mudaram."""
    resultado = db.execute(
        update(ExecucaoImportacao)
        .where(ExecucaoImportacao.status == "rodando")
        .values(status="erro", erro="interrompida", fim=_agora())
    )
    db.commit()
    return resultado.rowcount


def nova_execucao(
    db: Session, *, dry_run: bool = False, teto_usd: float | None = None, origem: Origem = NOTION
) -> ExecucaoImportacao:
    """A linha da execução, `rodando`, gravada já: a API devolve o id antes de o trabalho começar."""
    execucao = ExecucaoImportacao(origem=origem.nome, inicio=_agora(), status="rodando", fase="sincronizando",
                                  dry_run=dry_run, teto_usd=None if dry_run else teto_usd)
    db.add(execucao)
    db.commit()
    return execucao


def importar(
    leitor, db: Session, *, dry_run: bool = False, limite_paginas: int | None = None,
    teto_usd: float | None = None, execucao_id: int | None = None, origem: Origem = NOTION, sincronizar=None,
) -> Relatorio:
    """Roda uma importação e a registra em `execucoes_importacao` (o dry-run também, com dry_run=True). Com
    `execucao_id`, usa a execução que a API já criou (nova_execucao); sem ele, cria uma.

    O curador só roda fora do dry-run e com `teto_usd` (o script sempre passa um): sem teto, as páginas só esperam.
    `origem` e `sincronizar` trocam a fonte: o padrão é o Notion (`_sincronizar`); o Drive passa DRIVE e a função de
    app/importacao_drive.py. O resto (execução, progresso, teto de gasto e curador) é o mesmo.
    Levanta ErroNotion se a lista de páginas não puder ser lida (token inválido, sem rede...). Uma página que falha
    sozinha (no Notion ou no curador) não derruba a execução: vira uma "falha" e é tentada de novo na próxima vez.
    O que derruba a execução a deixa `erro`, com só o tipo do erro (a mensagem pode ter texto de página).
    """
    if teto_usd is not None and teto_usd <= 0:
        raise ValueError("O teto de gasto precisa ser maior que zero.")
    if execucao_id is None:
        execucao = nova_execucao(db, dry_run=dry_run, teto_usd=teto_usd, origem=origem)
    else:
        execucao = db.get(ExecucaoImportacao, execucao_id)
    relatorio = Relatorio(dry_run=dry_run, teto_usd=teto_usd, execucao_id=execucao.id)
    erro = None
    try:
        (sincronizar or _sincronizar)(leitor, db, relatorio, limite_paginas, execucao)
        execucao.estimativa_usd = relatorio.estimativa.custo_usd
        if not dry_run and teto_usd is not None:
            execucao.fase = "curando"
            _gravar_progresso(db, execucao, relatorio)
            _curar(db, relatorio, teto_usd, execucao, origem)
    except BaseException as e:
        db.rollback()  # o que estava pela metade não entra; a execução é fechada abaixo, numa transação limpa
        erro = _nome_do_erro(e)
        raise
    finally:
        relatorio.requisicoes_notion = leitor.requisicoes
        execucao.fim = _agora()
        if erro is None:
            execucao.status = "parou_no_teto" if relatorio.parou_no_teto else "concluida"
            execucao.fase = "fim"
        else:  # a fase fica onde estava: diz em que parte a execução caiu
            execucao.status, execucao.erro = "erro", erro
        _gravar_progresso(db, execucao, relatorio)
        logger.info(json.dumps({  # só números: nunca título nem texto
            "evento": f"importacao_{origem.nome}",
            "execucao_id": execucao.id,
            "status": execucao.status,
            "dry_run": dry_run,
            "lidas": relatorio.lidas,
            "novas": len(relatorio.novas),
            "alteradas": len(relatorio.alteradas),
            "puladas": len(relatorio.puladas),
            "falhas": len(relatorio.falhas),
            "removidas": len(relatorio.removidas),
            "requisicoes_notion": relatorio.requisicoes_notion,
            "curadas": len(relatorio.curadas),
            "falhas_do_curador": len(relatorio.falhas_do_curador),
            "esperando": len(relatorio.esperando),
            "insights_propostos": relatorio.insights_propostos,
            "obsoletos": relatorio.obsoletos,
            "custo_real_usd": round(relatorio.custo_real_usd, 6),
        }))
    return relatorio


def _gravar_progresso(db: Session, execucao: ExecucaoImportacao, relatorio: Relatorio) -> None:
    """As contagens da execução até aqui, num commit curto (a tela lê enquanto a execução roda). Só é chamada entre
    uma página e outra, quando a sessão não tem nada pela metade: o commit não leva junto uma página incompleta."""
    execucao.paginas_lidas = relatorio.lidas
    execucao.paginas_novas = len(relatorio.novas)
    execucao.paginas_alteradas = len(relatorio.alteradas)
    execucao.paginas_puladas = len(relatorio.puladas)
    execucao.paginas_removidas = len(relatorio.removidas)
    execucao.paginas_falhas = len(relatorio.falhas) + len(relatorio.falhas_do_curador)
    execucao.paginas_curadas = len(relatorio.curadas)
    execucao.insights_propostos = relatorio.insights_propostos
    execucao.gasto_usd = relatorio.custo_real_usd
    db.commit()


def _nome_do_erro(e: BaseException) -> str:
    """O que a execução guarda do erro: o tipo e, do Notion, o código HTTP. Nunca a mensagem."""
    status = getattr(e, "status", None)  # ErroNotion e ErroDrive trazem o código HTTP
    return f"{type(e).__name__} ({status})" if status is not None else type(e).__name__


def _sincronizar(
    leitor: LeitorNotion, db: Session, relatorio: Relatorio, limite_paginas: int | None, execucao: ExecucaoImportacao
) -> None:
    busca = leitor.paginas(limite=limite_paginas)
    vistas: set[str] = set()
    hashes: dict[str, str] = {}  # hash -> título das páginas tratadas nesta execução (duplicatas no dry-run)
    for pagina in busca.paginas:
        vistas.add(pagina["id"])
        relatorio.lidas += 1
        _sincronizar_pagina(leitor, db, pagina, relatorio, hashes)
        _gravar_progresso(db, execucao, relatorio)

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
    else:  # passou pela triagem de novo: o que o conteúdo antigo gerou e ninguém revisou sai da Fila
        _obsoletar_pendentes(db, fonte.url, f"a página do Notion mudou (execução #{relatorio.execucao_id})", relatorio)
    fonte.titulo = seguro
    fonte.url = url_da_pagina(pid)
    fonte.markdown = None if status == "pulada_dado_pessoal" else markdown  # o texto com dado pessoal não é guardado
    fonte.hash_conteudo = hash_novo
    fonte.editado_em = editado
    fonte.importado_em = _agora()
    fonte.status = status
    fonte.motivo = motivo_da_coluna(motivo)
    db.commit()


def motivo_da_coluna(texto: str) -> str | None:
    """O motivo como a coluna guarda: vazio vira None, e o longo (um título grande em "mesmo conteúdo de …") é
    cortado no tamanho da coluna (o Postgres recusaria)."""
    if not texto:
        return None
    return texto if len(texto) <= MOTIVO_MAX else texto[: MOTIVO_MAX - 1] + "…"


def trechos_da_fonte(fonte: Fonte) -> list[Trecho]:
    """Os trechos que o curador recebe, refeitos a partir do markdown guardado (o cabeçalho diz de onde vêm)."""
    if fonte.origem == DRIVE.nome:
        titulo = f"{fonte.titulo} (pasta {fonte.categoria})" if fonte.categoria else fonte.titulo
        return trechos.dividir(titulo, fonte.markdown or "", rotulo="Documento do Drive")
    return trechos.dividir(fonte.titulo, fonte.markdown or "")


def _sem_mudanca(fonte: Fonte) -> PaginaLida:
    """Página que não mudou. Se ainda espera o curador (a execução anterior parou no teto, ou ele falhou), os trechos
    vêm junto, refeitos a partir do markdown guardado."""
    partes = trechos_da_fonte(fonte) if fonte.status in A_CURAR else []
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
            fonte.motivo = motivo
            _obsoletar_pendentes(db, fonte.url, f"a página saiu do Notion ({motivo})", relatorio)
            db.commit()


def _listar_pendentes(db: Session, vistas: set[str], relatorio: Relatorio, origem: Origem = NOTION) -> None:
    """Fontes que esperam o curador e não vieram nesta busca (ex.: com --limite-paginas): entram no relatório para
    a estimativa do --dry-run e para o curador saber o que falta. As que já estão no relatório (removidas, ou que
    falharam na conferência) ficam de fora."""
    no_relatorio = vistas | {p.id_externo for p in relatorio.paginas}
    pendentes = db.scalars(
        select(Fonte).where(Fonte.origem == origem.nome, Fonte.status.in_(A_CURAR),
                            Fonte.id_externo.not_in(no_relatorio))
        .order_by(Fonte.id)
    )
    for fonte in pendentes:
        partes = trechos_da_fonte(fonte)
        relatorio.paginas.append(PaginaLida(fonte.id_externo, fonte.titulo, "pendente", fonte.status, trechos=partes))


def _obsoletar_pendentes(
    db: Session, url: str, motivo: str, relatorio: Relatorio, origem: Origem = NOTION
) -> None:
    """Os itens da página que ninguém revisou (historico_a_validar) viram `obsoleto`, pela regra do domínio e com
    histórico. Os aprovados (validado, consolidado) não mudam: foram decisão do time; o relatório conta quantos são.
    Não faz commit: entra na mesma transação da mudança da fonte."""
    itens = list(db.scalars(select(Insight).where(Insight.fonte == origem.nome, Insight.fonte_ref == url)))
    for item in itens:
        if item.status == "historico_a_validar":
            dominio.validar_transicao(item.status, "obsoleto", motivo)
            db.add(HistoricoStatus(insight_id=item.id, de=item.status, para="obsoleto", por_quem=origem.autor,
                                   motivo=motivo))
            item.status = "obsoleto"
            item.motivo_obsolescencia = motivo
            relatorio.obsoletos += 1
        elif item.status in ("validado", "consolidado"):
            relatorio.aprovados_de_paginas_mudadas += 1


# --- curar ----------------------------------------------------------------------------------------------------

def _curar(
    db: Session, relatorio: Relatorio, teto_usd: float, execucao: ExecucaoImportacao, origem: Origem = NOTION
) -> None:
    """O curador nas fontes que esperam por ele, uma página por vez e dentro do teto de gasto.

    Antes de cada página: o gasto real até ali + FOLGA_DO_TETO × a estimativa dela precisa caber no teto. Se não
    couber, para: o que falta continua `a_curar` e a próxima execução continua dali. O gasto real é o custo que o
    Gemini informa (llm.medir_gasto); uma resposta sem a contagem de tokens conta como a estimativa.
    """
    with llm.medir_gasto() as gasto:
        for pagina in list(relatorio.a_curar):
            estimativa = estimar(pagina.trechos).custo_usd
            if relatorio.custo_real_usd + FOLGA_DO_TETO * estimativa > teto_usd:
                i = relatorio.a_curar.index(pagina)
                relatorio.esperando = relatorio.a_curar[i:]
                return
            antes, sem_contagem = gasto.usd, gasto.sem_contagem
            _curar_pagina(db, pagina, relatorio, origem)
            custo = gasto.usd - antes
            if gasto.sem_contagem > sem_contagem:  # custo desconhecido: conta como a estimativa (pessimista)
                custo = max(custo, estimativa)
            relatorio.custo_real_usd += custo
            _gravar_progresso(db, execucao, relatorio)


def _curar_pagina(db: Session, pagina: PaginaLida, relatorio: Relatorio, origem: Origem = NOTION) -> None:
    """Um item por trecho. Tudo ou nada: se um trecho falhar, nenhum item da página entra e ela fica `falha`."""
    fonte = db.scalar(select(Fonte).where(Fonte.origem == origem.nome, Fonte.id_externo == pagina.id_externo))
    try:
        propostas = [
            curadoria.propor_lote(t.texto, origem.autor, origem.nome, fonte.url, db,
                                  barrar_dado_pessoal=origem.barra_dado_pessoal)
            for t in pagina.trechos
        ]
        for proposta in propostas:  # o item que vai ser GRAVADO também não pode ter dado pessoal
            if origem.barra_dado_pessoal:
                curadoria.exigir_item_sem_dados_pessoais(proposta.insight)
    except llm.ErroLLM:
        _falhou(db, fonte, pagina, relatorio, "o curador falhou (o Gemini não respondeu direito); tenta de novo")
        return
    except dominio.DadoPessoalNaEntrada as e:  # a mensagem não é usada: o motivo diz só onde e o quê
        onde = ", ".join(f"{tipo} em {campo}" for campo, tipo in e.achados)
        _falhou(db, fonte, pagina, relatorio, f"o item proposto tem possível dado pessoal ({onde})")
        return

    motivo_do_item = f"Importado {origem.rotulo} (execução #{relatorio.execucao_id})"
    for proposta in propostas:
        item = Insight(**proposta.insight.model_dump(), status="historico_a_validar")  # nunca validado
        db.add(item)
        db.flush()  # para ter o item.id
        db.add_all(Relacao(insight_id=item.id, relacionado_id=r.relacionado_id, tipo=r.tipo)
                   for r in proposta.relacoes)
        db.add(HistoricoStatus(insight_id=item.id, de=None, para="historico_a_validar", por_quem=origem.autor,
                               motivo=motivo_do_item))
    fonte.status = "importada"
    if origem.barra_dado_pessoal:  # no Drive o motivo guarda o aviso de dado pessoal mantido: não se apaga
        fonte.motivo = None
    db.commit()  # os itens da página e a fonte entram juntos (ou nada entra)
    pagina.status = "importada"
    relatorio.curadas.append(pagina)
    relatorio.insights_propostos += len(propostas)


def _falhou(db: Session, fonte: Fonte, pagina: PaginaLida, relatorio: Relatorio, motivo: str) -> None:
    db.rollback()  # nada da página foi gravado (o curador não grava), mas a sessão volta limpa
    fonte = db.get(Fonte, fonte.id)
    fonte.status = "falha"
    fonte.motivo = motivo_da_coluna(motivo)
    db.commit()
    pagina.status, pagina.motivo = "falha", motivo
    relatorio.falhas_do_curador.append(pagina)
