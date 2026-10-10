"""Curadoria: texto solto -> proposta conferida. "O LLM propõe, o código dispõe."

O modelo (app/llm.py) estrutura o texto; este módulo confere e corrige o que ele devolveu, usando as regras de
app/dominio.py, e busca no banco os itens com que o novo pode se relacionar. NADA é gravado aqui.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dominio, llm
from app.models import Insight
from app.schemas import InsightBase, InsightLLM, MensagemHistorico, PropostaCuradoria, RelacaoIn

MAX_TURNOS = 3  # no 3º turno o curador fecha a proposta com o que tem, sem novas perguntas
MAX_PERGUNTAS = 2
MAX_CANDIDATOS = 30  # itens existentes mostrados ao modelo na 2ª chamada (relações)
MAX_RELACOES = 10  # o mesmo limite de InsightCreate.relacoes


def propor(texto: str, autor: str, conversa: list[MensagemHistorico], db: Session) -> PropostaCuradoria:
    """Roda o curador e devolve um rascunho para a pessoa revisar. Levanta llm.ErroLLM se o modelo falhar."""
    turno = 1 + sum(1 for m in conversa if m.role == "user")
    ultimo_turno = turno >= MAX_TURNOS

    proposta = llm.curar(texto, [m.model_dump() for m in conversa], turno, ultimo_turno)
    avisos = list(proposta.avisos)

    insight = _conferir_insight(proposta.insight, autor, avisos)

    perguntas = [p.strip() for p in proposta.perguntas if p.strip()][:MAX_PERGUNTAS]
    if ultimo_turno and perguntas:  # o modelo perguntou mesmo sendo o último turno: vira aviso
        avisos += [f"Ficou sem resposta: {p}" for p in perguntas]
        perguntas = []

    avisos += dominio.detectar_dados_pessoais(descricao=insight.descricao, contexto_cliente=insight.contexto_cliente)

    return PropostaCuradoria(
        insight=insight,
        relacoes=_relacoes(insight, db),
        perguntas=perguntas,
        avisos=avisos,
    )


def _conferir_insight(item: InsightLLM, autor: str, avisos: list[str]) -> InsightBase:
    """Aplica as regras de evidência (rebaixando com aviso, em vez de recusar) e põe o que é do código."""
    tipo, evidencia = item.tipo, item.evidencia

    if evidencia == 4 and not dominio.tem_numero(item.resultado):
        evidencia = 3
        avisos.append("Evidência 4 (resultado medido) exige um número no resultado: rebaixada para 3.")
    if tipo == "regra" and evidencia < 3:
        tipo = "hipotese" if evidencia == 1 else "aprendizado"
        avisos.append(f"'regra' exige evidência 3 ou 4 (veio {evidencia}): o tipo virou '{tipo}'.")

    dominio.validar_insight(tipo, evidencia, item.resultado)  # garantia final: se levantar aqui, é bug nosso

    return InsightBase(
        **item.model_dump(exclude={"tipo", "evidencia", "data_evento"}),
        tipo=tipo,
        evidencia=evidencia,
        data_evento=_data_ou_none(item.data_evento, avisos),
        autor=autor,  # do código, nunca do modelo
        fonte="chat",
    )


def _data_ou_none(texto: str | None, avisos: list[str]) -> date | None:
    """O modelo devolve a data como texto (AAAA-MM-DD). Data inválida não derruba a proposta: vira aviso."""
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        avisos.append(f"Data '{texto}' não reconhecida: preencha à mão (AAAA-MM-DD).")
        return None


def _candidatos(db: Session, secao: str, segmento: str | None) -> list[Insight]:
    """Itens validados/consolidados da mesma seção (e do mesmo segmento, se houver), os mais fortes primeiro."""
    consulta = select(Insight).where(
        Insight.status.in_(["validado", "consolidado"]),
        Insight.secao == secao,
    )
    if segmento:
        consulta = consulta.where(Insight.segmento == segmento)
    consulta = consulta.order_by(Insight.evidencia.desc(), Insight.id.desc()).limit(MAX_CANDIDATOS)
    return list(db.scalars(consulta))


def _relacoes(insight: InsightBase, db: Session) -> list[RelacaoIn]:
    """2ª chamada ao modelo, só se houver candidatos. Ids que não estão entre os candidatos são descartados."""
    candidatos = _candidatos(db, insight.secao, insight.segmento)
    if not candidatos:
        return []  # base vazia (ou sem itens dessa seção/segmento): nenhuma chamada extra, custo zero

    lista = "\n".join(f"[INS-{c.id}] {c.titulo} | {c.tipo} | evid {c.evidencia}" for c in candidatos)
    item_novo = f"{insight.titulo} | {insight.tipo} | evid {insight.evidencia}\n{insight.descricao}"
    resposta = llm.relacionar(item_novo, lista)

    ids_validos = {c.id for c in candidatos}
    relacoes, vistos = [], set()
    for r in resposta.relacoes:
        par = (r.id, r.tipo)
        if r.id in ids_validos and par not in vistos:  # o modelo às vezes inventa ids ou repete
            vistos.add(par)
            relacoes.append(RelacaoIn(relacionado_id=r.id, tipo=r.tipo))
    return relacoes[:MAX_RELACOES]