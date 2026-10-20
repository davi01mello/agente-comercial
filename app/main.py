"""Ponto de entrada. Rodar com:  uvicorn app.main:app --reload

As tabelas do banco são criadas e atualizadas pelas migrações: rode `alembic upgrade head` antes.
"""
import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import agendador, auth, busca, curadoria, dominio, importacao, importacao_drive, knowledge, llm
from app.auth import Logada
from app.config import settings
from app.db import SessionLocal, get_db
from app.drive import ErroDrive, LeitorDrive
from app.models import ORIGENS, ExecucaoImportacao, Fonte, HistoricoStatus, Insight, Relacao
from app.notion import ErroNotion, LeitorNotion
from app.schemas import (
    AprovarIn,
    ChatIn,
    ChatOut,
    ContagensExecucao,
    DocumentoCitavel,
    ExecucaoDetalhe,
    ExecucaoOut,
    FiltroFontes,
    FiltroInsights,
    FonteOut,
    InsightCreate,
    InsightOut,
    ListaFontes,
    ListaInsights,
    PropostaCuradoria,
    RegistrarIn,
    RejeitarIn,
    RelacaoOut,
    ResumoFontes,
    SincronizarIn,
    SincronizarOut,
)

# Logs do app (app.llm, app.knowledge...) no terminal, ao lado dos do uvicorn. O uvicorn só configura os loggers
# DELE: sem isto, as linhas INFO do app (ex.: uma por chamada ao modelo) não aparecem em lugar nenhum.
_log_do_app = logging.getLogger("app")
_log_do_app.setLevel(logging.INFO)
_saida_do_log = logging.StreamHandler()  # escreve no terminal (stderr), como o uvicorn
_saida_do_log.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
_log_do_app.addHandler(_saida_do_log)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Na subida: confere o login (em prod, sem ele o app não sobe); a execução da importação que ficou `rodando` é de
    um servidor que parou no meio dela."""
    auth.conferir_configuracao()
    with SessionLocal() as db:
        importacao.marcar_interrompidas(db)
    agendada = None
    if settings.drive_sync_intervalo_min > 0:  # sincronização automática do Drive (DRIVE_SYNC_INTERVALO_MIN)
        agendada = asyncio.create_task(agendador.laco(_uma_sincronizacao_por_vez))
    yield
    if agendada is not None:
        agendada.cancel()


# Todas as rotas exigem a pessoa logada (app/auth.py), menos a página, o /health e as rotas /auth: uma rota nova
# nasce protegida, sem ninguém precisar lembrar. O cookie da sessão é assinado, HttpOnly e SameSite=Lax (https em prod).
# /docs, /redoc e /openapi.json são rotas do FastAPI fora desta proteção: em produção ficam desligados.
_EM_PROD = settings.app_env == "prod"
app = FastAPI(
    title="Cérebro Comercial CITi", lifespan=ciclo_de_vida, dependencies=[Depends(auth.exigir_login)],
    docs_url=None if _EM_PROD else "/docs", redoc_url=None if _EM_PROD else "/redoc",
    openapi_url=None if _EM_PROD else "/openapi.json",
)
app.add_middleware(
    SessionMiddleware, secret_key=auth.segredo_da_sessao(), session_cookie=auth.COOKIE,
    max_age=settings.sessao_dias * 86400, same_site="lax", https_only=_EM_PROD,
)
app.include_router(auth.router)

# Interface: CSS, JS e o que mais a página precisar ficam em app/static (sem build, servidos como estão).
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# "Esta rota precisa de uma sessão do banco": o FastAPI abre uma por requisição (get_db) e fecha no fim.
Db = Annotated[Session, Depends(get_db)]

JANELA_DUPLO_CLIQUE = timedelta(seconds=60)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"titulo": "Cérebro Comercial CITi"})


@app.post("/chat", response_model=ChatOut)
def chat(dados: ChatIn, db: Db, _pessoa: Logada):
    """Consultor: recebe a pergunta + o histórico e responde com os itens aprovados do banco, citando [INS-n]."""
    # Dado pessoal é barrado ANTES do modelo (como no /registrar/propor): depois que o texto sai daqui, não volta.
    # Só o que o usuário escreveu é conferido; as falas do modelo nasceram de textos que já passaram por aqui.
    anteriores = [h.text for h in dados.historico if h.role == "user"]
    try:
        dominio.exigir_sem_dados_pessoais(
            mensagem=dados.mensagem,
            **{f"mensagem anterior {i}": texto for i, texto in enumerate(anteriores, start=1)},
        )
    except dominio.RegraDeNegocio as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    historico = [h.model_dump() for h in dados.historico]
    achados = busca.buscar(db, busca.consulta_da_conversa(dados.mensagem, historico))  # documentos do Drive
    try:
        resposta = llm.consultar(dados.mensagem, historico, knowledge.montar_base(db),
                                 knowledge.montar_documentos(achados))
    except llm.ErroLLM as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ChatOut(
        resposta=resposta,
        documentos=[DocumentoCitavel(id=a.fonte_id, titulo=a.titulo, url=a.url, categoria=a.categoria)
                    for a in achados],
    )


# --- insights -------------------------------------------------------------------------------

@app.post("/insights", response_model=InsightOut, status_code=201)
def criar_insight(dados: InsightCreate, db: Db, pessoa: Logada):
    """Grava um item confirmado pela pessoa. Ele SEMPRE nasce `proposto` e só vale depois de aprovado na Fila.
    O autor é a pessoa logada (o `autor` do corpo, se vier, é ignorado)."""
    try:
        dominio.validar_insight(dados.tipo, dados.evidencia, dados.resultado)
    except dominio.RegraDeNegocio as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Dado pessoal de cliente não entra na base (pedido do Davi na T4b). Antes era só um aviso na resposta; agora é
    # a mesma regra da importação do Notion. A mensagem diz onde e o quê, nunca o dado.
    try:
        curadoria.exigir_item_sem_dados_pessoais(dados)
    except dominio.DadoPessoalNaEntrada as e:
        onde = "; ".join(f"{tipo} em '{campo}'" for campo, tipo in e.achados)
        raise HTTPException(
            status_code=422,
            detail=f"Encontrei possível dado pessoal: {onde}. Por LGPD, dado pessoal de cliente não entra na base. "
                   "Troque por algo genérico (\"o cliente\", \"[e-mail]\") e envie de novo. Nada foi gravado.",
        ) from e

    if _acabou_de_ser_criado(db, dados, pessoa.nome):
        raise HTTPException(
            status_code=409,
            detail="Este item acabou de ser registrado (mesmo autor, título e data). Confira a Fila antes de repetir.",
        )

    pares = sorted({(r.relacionado_id, r.tipo) for r in dados.relacoes})  # set: tira repetidos
    ids = {relacionado_id for relacionado_id, _ in pares}
    existentes = set(db.scalars(select(Insight.id).where(Insight.id.in_(ids)))) if ids else set()
    if faltando := sorted(ids - existentes):
        lista = ", ".join(f"INS-{i}" for i in faltando)
        raise HTTPException(status_code=422, detail=f"Relação com item que não existe: {lista}.")

    item = Insight(**dados.model_dump(exclude={"relacoes", "autor"}), autor=pessoa.nome, status="proposto")
    db.add(item)
    db.flush()  # manda o INSERT agora para o banco gerar o item.id (ainda dá para desfazer tudo)
    relacoes = [Relacao(insight_id=item.id, relacionado_id=i, tipo=tipo) for i, tipo in pares]
    db.add_all(relacoes)
    db.add(HistoricoStatus(insight_id=item.id, de=None, para="proposto", por_quem=pessoa.nome))
    db.commit()  # item + relações + histórico entram juntos (ou nada entra)
    return _para_saida(item, relacoes)


@app.get("/insights", response_model=ListaInsights)
def listar_insights(filtro: Annotated[FiltroInsights, Query()], db: Db):
    """Lista com filtros e paginação. Ex.: /insights?status=proposto&limit=20&offset=20 (2ª página)."""
    consulta = select(Insight)
    if filtro.status:
        consulta = consulta.where(Insight.status == filtro.status)
    if filtro.secao:
        consulta = consulta.where(Insight.secao == filtro.secao)
    if filtro.segmento:
        consulta = consulta.where(Insight.segmento == filtro.segmento)

    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    itens = list(db.scalars(consulta.order_by(Insight.id.desc()).limit(filtro.limit).offset(filtro.offset)))

    # Relações de todos os itens da página numa consulta só (e não uma por item)
    relacoes_por_item: dict[int, list[Relacao]] = {}
    if itens:
        for r in db.scalars(select(Relacao).where(Relacao.insight_id.in_([i.id for i in itens]))):
            relacoes_por_item.setdefault(r.insight_id, []).append(r)

    return ListaInsights(
        itens=[_para_saida(i, relacoes_por_item.get(i.id, [])) for i in itens],
        total=total,
        limit=filtro.limit,
        offset=filtro.offset,
    )


def _acabou_de_ser_criado(db: Session, dados: InsightCreate, autor: str) -> bool:
    """Duplo clique: o mesmo autor + título + data_evento gravado nos últimos 60 segundos.

    O banco grava criado_em em UTC (CURRENT_TIMESTAMP), então o limite também é calculado em UTC.
    Com datetime.now() (hora do Brasil, 3h atrás do UTC) a "janela" viraria 3 horas e 1 minuto.
    """
    limite = datetime.now(UTC).replace(tzinfo=None) - JANELA_DUPLO_CLIQUE
    consulta = select(Insight.id).where(
        Insight.autor == autor,
        Insight.titulo == dados.titulo,
        Insight.data_evento == dados.data_evento,  # com None, o SQLAlchemy gera "IS NULL"
        Insight.criado_em >= limite,
    )
    return db.scalar(consulta.limit(1)) is not None


def _para_saida(item: Insight, relacoes: list[Relacao], avisos: list[str] | None = None) -> InsightOut:
    saida = InsightOut.model_validate(item)
    saida.relacoes = [RelacaoOut.model_validate(r) for r in relacoes]
    saida.avisos = avisos or []
    return saida


# --- curador --------------------------------------------------------------------------------

@app.post("/registrar/propor", response_model=PropostaCuradoria)
def registrar_propor(dados: RegistrarIn, db: Db, pessoa: Logada):
    """Curador: texto solto -> proposta estruturada para a pessoa revisar.

    NÃO grava nada. Quem grava é o POST /insights, depois que a pessoa confere e confirma.
    """
    try:
        return curadoria.propor(dados.texto, pessoa.nome, dados.conversa, db)
    except dominio.RegraDeNegocio as e:  # dado pessoal no relato: barrado antes de chamar o modelo
        raise HTTPException(status_code=422, detail=str(e)) from e
    except llm.ErroLLM as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

# --- fila -----------------------------------------------------------------------------------

@app.post("/insights/{insight_id}/aprovar", response_model=InsightOut)
def aprovar_insight(insight_id: int, db: Db, pessoa: Logada, _dados: AprovarIn | None = None):
    """Fila: proposto (ou historico_a_validar) -> validado. A partir daqui o item entra na base do consultor."""
    return _mudar_status(db, insight_id, "validado", pessoa.nome)


@app.post("/insights/{insight_id}/rejeitar", response_model=InsightOut)
def rejeitar_insight(insight_id: int, dados: RejeitarIn, db: Db, pessoa: Logada):
    """Fila: -> obsoleto, com motivo obrigatório. Nada é apagado: o item e o motivo ficam no histórico."""
    return _mudar_status(db, insight_id, "obsoleto", pessoa.nome, dados.motivo)


def _mudar_status(db: Session, insight_id: int, para: str, por_quem: str, motivo: str | None = None) -> InsightOut:
    """Muda o status de um item seguindo o ciclo de vida do dominio e grava a mudança no histórico."""
    item = db.get(Insight, insight_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"INS-{insight_id} não existe.")

    de = item.status
    try:
        dominio.validar_transicao(de, para, motivo)
    except dominio.RegraDeNegocio as e:  # transição inválida ou sem motivo: a tela mostra a mensagem do domínio
        raise HTTPException(status_code=422, detail=str(e)) from e

    # O UPDATE só vale se o status no banco ainda for o que lemos acima (WHERE status = de). Se outra pessoa
    # aprovou ou rejeitou o item nesse meio-tempo, nenhuma linha bate (rowcount 0) e respondemos 422, em vez de
    # passar por cima da decisão dela e gravar duas mudanças no histórico.
    valores = {"status": para}
    if para == "obsoleto":
        valores["motivo_obsolescencia"] = motivo
    resultado = db.execute(
        update(Insight)
        .where(Insight.id == insight_id, Insight.status == de)
        .values(**valores)
        .execution_options(synchronize_session=False)  # o item é recarregado do banco no fim (refresh)
    )
    if resultado.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"INS-{insight_id} acabou de ser alterado por outra pessoa. Recarregue a Fila.",
        )

    db.add(HistoricoStatus(insight_id=insight_id, de=de, para=para, por_quem=por_quem, motivo=motivo))
    db.commit()  # status + histórico entram juntos (ou nada entra)

    db.refresh(item)  # lê do banco o status novo
    relacoes = list(db.scalars(select(Relacao).where(Relacao.insight_id == insight_id)))
    return _para_saida(item, relacoes)


# --- fontes ---------------------------------------------------------------------------------
# Quem traz as páginas é a importação (app/importacao.py), pelo scripts/importar_notion.py ou pelo POST
# /fontes/sincronizar. As rotas alimentam a tela de Fontes e nunca devolvem o texto das páginas (`markdown`): só título,
# link, estado e quantos itens saíram delas.

@app.get("/fontes", response_model=ListaFontes)
def listar_fontes(filtro: Annotated[FiltroFontes, Query()], db: Db):
    """Páginas importadas, as editadas mais recentemente primeiro, com os itens que o curador tirou de cada uma."""
    consulta = select(Fonte)
    if filtro.status:
        consulta = consulta.where(Fonte.status == filtro.status)
    if filtro.origem:
        consulta = consulta.where(Fonte.origem == filtro.origem)
    if filtro.q:
        consulta = consulta.where(func.lower(Fonte.titulo).contains(filtro.q.lower(), autoescape=True))

    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    pagina = consulta.order_by(Fonte.editado_em.desc(), Fonte.id.desc()).limit(filtro.limit).offset(filtro.offset)
    fontes = list(db.scalars(pagina))

    # Itens gerados por cada fonte da página, numa consulta só (o item guarda a url da fonte em fonte_ref)
    itens_por_url: dict[str, dict[str, int]] = {}
    if fontes:
        linhas = db.execute(
            select(Insight.fonte_ref, Insight.status, func.count())
            .where(Insight.fonte_ref.in_([f.url for f in fontes]))
            .group_by(Insight.fonte_ref, Insight.status)
        )
        for url, status, quantos in linhas:
            itens_por_url.setdefault(url, {})[status] = quantos

    saida = []
    for f in fontes:
        item = FonteOut.model_validate(f)
        item.itens = itens_por_url.get(f.url, {})
        saida.append(item)
    return ListaFontes(itens=saida, total=total, limit=filtro.limit, offset=filtro.offset)


@app.get("/fontes/resumo", response_model=ResumoFontes)
def resumo_fontes(db: Db):
    """Os números do topo da tela: quantas páginas em cada estado, por origem, e a última sincronização (o dry-run
    não conta: ele não muda as fontes)."""
    por_status = dict(db.execute(select(Fonte.status, func.count()).group_by(Fonte.status)).all())
    por_origem = dict(db.execute(select(Fonte.origem, func.count()).group_by(Fonte.origem)).all())
    recentes = (
        select(ExecucaoImportacao)
        .where(ExecucaoImportacao.dry_run.is_(False))
        .order_by(ExecucaoImportacao.inicio.desc(), ExecucaoImportacao.id.desc())
    )
    ultima = db.scalar(recentes.limit(1))
    por_execucao = {}
    for nome in ORIGENS:
        mais_recente = db.scalar(recentes.where(ExecucaoImportacao.origem == nome).limit(1))
        if mais_recente:
            por_execucao[nome] = ExecucaoOut.model_validate(mais_recente)
    return ResumoFontes(
        total=sum(por_status.values()),
        por_status=por_status,
        por_origem=por_origem,
        ultima_execucao=ExecucaoOut.model_validate(ultima) if ultima else None,
        ultima_por_origem=por_execucao,
    )


# --- sincronizar ----------------------------------------------------------------------------

# A conferência do 409 e a criação da execução são uma coisa só: sem a trava, duas requisições ao mesmo tempo veriam
# "nenhuma rodando" e criariam duas. A trava vale dentro de um processo (o uvicorn de um worker só, como no dev).
_uma_sincronizacao_por_vez = threading.Lock()


def leitor_notion() -> LeitorNotion:
    """O leitor do Notion da sincronização. Os testes trocam pelo Notion falso (app.dependency_overrides)."""
    try:
        return LeitorNotion()
    except ErroNotion as e:  # falta o NOTION_TOKEN no .env
        raise HTTPException(status_code=503, detail=str(e)) from e


def leitor_drive() -> LeitorDrive:
    """O leitor do Drive da sincronização. Os testes trocam pelo Drive falso (app.dependency_overrides)."""
    try:
        return LeitorDrive()
    except ErroDrive as e:  # falta a pasta ou a credencial no .env
        raise HTTPException(status_code=503, detail=str(e)) from e


LEITORES = {"notion": leitor_notion, "drive": leitor_drive}


def _criar_leitor(origem: str):
    """O leitor da origem pedida, só dele: pedir o Drive não exige o NOTION_TOKEN (e vice-versa). Respeita o
    app.dependency_overrides, que é como os testes põem o Notion e o Drive falsos."""
    fabrica = LEITORES[origem]
    return app.dependency_overrides.get(fabrica, fabrica)()


@app.post("/fontes/sincronizar", response_model=SincronizarOut, status_code=202)
def sincronizar_fontes(dados: SincronizarIn, tarefas: BackgroundTasks, db: Db):
    """Começa uma importação (do Notion ou do Drive, pelo campo `origem`) em segundo plano e devolve o id da execução
    na hora. Acompanhe pelo GET /fontes/execucoes/{id}. As mesmas regras dos scripts/importar_notion.py e
    scripts/sincronizar_drive.py: o dry-run não muda as fontes nem chama o modelo, e o curador para antes de passar do
    teto. 409 se já houver uma importação (não dry-run) rodando, de qualquer origem."""
    # Decisão do Davi (T5): todo @citi.org.br logado pode sincronizar (não há papéis por enquanto).
    try:
        importacao.conferir_configuracao(dados.dry_run)
    except importacao.FaltaConfiguracao as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    leitor = _criar_leitor(dados.origem)

    with _uma_sincronizacao_por_vez:
        rodando = db.scalar(
            select(ExecucaoImportacao.id)
            .where(ExecucaoImportacao.status == "rodando", ExecucaoImportacao.dry_run.is_(False))
            .limit(1)
        )
        if rodando is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Já há uma importação rodando (execução #{rodando}). Acompanhe em /fontes/execucoes/{rodando}.",
            )
        origem = importacao.DRIVE if dados.origem == "drive" else importacao.NOTION
        execucao = importacao.nova_execucao(db, dry_run=dados.dry_run, teto_usd=dados.teto_usd, origem=origem)

    tarefas.add_task(_sincronizar_em_segundo_plano, leitor, execucao.id, dados)
    return SincronizarOut(execucao_id=execucao.id)


@app.get("/fontes/execucoes/{execucao_id}", response_model=ExecucaoDetalhe)
def ver_execucao(execucao_id: int, db: Db):
    """Uma execução da importação (pela API ou pelo script): status, fase, contagens, gasto, teto e estimativa. As
    contagens mudam a cada página enquanto ela roda."""
    e = db.get(ExecucaoImportacao, execucao_id)
    if e is None:
        raise HTTPException(status_code=404, detail=f"A execução #{execucao_id} não existe.")
    return ExecucaoDetalhe(
        id=e.id, origem=e.origem, status=e.status, fase=e.fase, dry_run=e.dry_run,
        contagens=ContagensExecucao(
            lidas=e.paginas_lidas, novas=e.paginas_novas, alteradas=e.paginas_alteradas, puladas=e.paginas_puladas,
            removidas=e.paginas_removidas, falhas=e.paginas_falhas, curadas=e.paginas_curadas,
            insights_propostos=e.insights_propostos,
        ),
        gasto_usd=e.gasto_usd, teto_usd=e.teto_usd, estimativa_usd=e.estimativa_usd, erro=e.erro, inicio=e.inicio,
        fim=e.fim,
    )


def _sincronizar_em_segundo_plano(leitor, execucao_id: int, dados: SincronizarIn) -> None:
    """Roda depois que a resposta saiu, com a própria sessão do banco (importacao.executar)."""
    executar = importacao_drive.executar if dados.origem == "drive" else importacao.executar
    try:
        executar(leitor, dry_run=dados.dry_run, limite_paginas=dados.limite_paginas, teto_usd=dados.teto_usd,
                 execucao_id=execucao_id)
    except Exception as e:  # a execução já ficou `erro`, com o tipo; a mensagem pode ter texto de página
        logger.warning(json.dumps({"evento": "sincronizacao_falhou", "execucao_id": execucao_id,
                                   "origem": dados.origem, "erro": type(e).__name__}))
