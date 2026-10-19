"""Ponto de entrada. Rodar com:  uvicorn app.main:app --reload

As tabelas do banco são criadas e atualizadas pelas migrações: rode `alembic upgrade head` antes.
"""
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import curadoria, dominio, knowledge, llm
from app.db import get_db
from app.models import ExecucaoImportacao, Fonte, HistoricoStatus, Insight, Relacao
from app.schemas import (
    AprovarIn,
    ChatIn,
    ChatOut,
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
)

# Logs do app (app.llm, app.knowledge...) no terminal, ao lado dos do uvicorn. O uvicorn só configura os loggers
# DELE: sem isto, as linhas INFO do app (ex.: uma por chamada ao modelo) não aparecem em lugar nenhum.
_log_do_app = logging.getLogger("app")
_log_do_app.setLevel(logging.INFO)
_saida_do_log = logging.StreamHandler()  # escreve no terminal (stderr), como o uvicorn
_saida_do_log.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
_log_do_app.addHandler(_saida_do_log)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Cérebro Comercial CITi")

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
def chat(dados: ChatIn, db: Db):
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
    try:
        resposta = llm.consultar(dados.mensagem, historico, knowledge.montar_base(db))
    except llm.ErroLLM as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ChatOut(resposta=resposta)


# --- insights -------------------------------------------------------------------------------

@app.post("/insights", response_model=InsightOut, status_code=201)
def criar_insight(dados: InsightCreate, db: Db):
    """Grava um item confirmado pela pessoa. Ele SEMPRE nasce `proposto` e só vale depois de aprovado na Fila."""
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

    if _acabou_de_ser_criado(db, dados):
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

    item = Insight(**dados.model_dump(exclude={"relacoes"}), status="proposto")
    db.add(item)
    db.flush()  # manda o INSERT agora para o banco gerar o item.id (ainda dá para desfazer tudo)
    relacoes = [Relacao(insight_id=item.id, relacionado_id=i, tipo=tipo) for i, tipo in pares]
    db.add_all(relacoes)
    db.add(HistoricoStatus(insight_id=item.id, de=None, para="proposto", por_quem=dados.autor))
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


def _acabou_de_ser_criado(db: Session, dados: InsightCreate) -> bool:
    """Duplo clique: o mesmo autor + título + data_evento gravado nos últimos 60 segundos.

    O banco grava criado_em em UTC (CURRENT_TIMESTAMP), então o limite também é calculado em UTC.
    Com datetime.now() (hora do Brasil, 3h atrás do UTC) a "janela" viraria 3 horas e 1 minuto.
    """
    limite = datetime.now(UTC).replace(tzinfo=None) - JANELA_DUPLO_CLIQUE
    consulta = select(Insight.id).where(
        Insight.autor == dados.autor,
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
def registrar_propor(dados: RegistrarIn, db: Db):
    """Curador: texto solto -> proposta estruturada para a pessoa revisar.

    NÃO grava nada. Quem grava é o POST /insights, depois que a pessoa confere e confirma.
    """
    try:
        return curadoria.propor(dados.texto, dados.autor, dados.conversa, db)
    except dominio.RegraDeNegocio as e:  # dado pessoal no relato: barrado antes de chamar o modelo
        raise HTTPException(status_code=422, detail=str(e)) from e
    except llm.ErroLLM as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

# --- fila -----------------------------------------------------------------------------------

@app.post("/insights/{insight_id}/aprovar", response_model=InsightOut)
def aprovar_insight(insight_id: int, dados: AprovarIn, db: Db):
    """Fila: proposto (ou historico_a_validar) -> validado. A partir daqui o item entra na base do consultor."""
    return _mudar_status(db, insight_id, "validado", dados.por_quem)


@app.post("/insights/{insight_id}/rejeitar", response_model=InsightOut)
def rejeitar_insight(insight_id: int, dados: RejeitarIn, db: Db):
    """Fila: -> obsoleto, com motivo obrigatório. Nada é apagado: o item e o motivo ficam no histórico."""
    return _mudar_status(db, insight_id, "obsoleto", dados.por_quem, dados.motivo)


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
# Só leitura: quem traz as páginas é o scripts/importar_notion.py. Estas rotas alimentam a tela de Fontes.
# Nunca devolvem o texto das páginas (`markdown`), só título, link, estado e quantos itens saíram delas.

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
    return ResumoFontes(
        total=sum(por_status.values()),
        por_status=por_status,
        por_origem=por_origem,
        ultima_execucao=ExecucaoOut.model_validate(ultima) if ultima else None,
    )

