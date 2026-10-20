"""Briefing de reunião (T7): o roteiro de uma reunião montado SÓ com o que está na base.

Quem escolhe os itens é o CÓDIGO (aprovados, do segmento, por prioridade e com teto por tipo); o modelo só organiza e
redige. Depois, o código confere tudo que o modelo devolveu: ponto sem fonte válida (id que não foi enviado) é
descartado, id escrito no texto sai, e a evidência de cada ponto vem dos itens citados, não do que o modelo disse.
Sem item e sem documento, o modelo nem é chamado.
"""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import busca, knowledge, llm
from app.models import Insight
from app.schemas import (
    BriefingIn,
    BriefingLLM,
    BriefingOut,
    DocumentoCitavel,
    FonteDoPonto,
    ItemDoBriefing,
    PontoLLM,
    PontoOut,
    SecaoOut,
)

# Quantos itens de cada tipo entram (os de maior prioridade primeiro): o prompt do modelo fica pequeno e focado.
TETO_POR_TIPO = {
    "case": 6, "objecao": 6, "perfil_segmento": 2, "regra": 6, "aprendizado": 8, "hipotese": 3, "template": 3,
}
MIN_DO_SEGMENTO = 3  # no diagnóstico, se o segmento tem menos que isto, completa com itens de outros segmentos
MAX_DE_OUTRO_SEGMENTO = 3
MAX_PONTOS_POR_SECAO = 6
MAX_TEXTO_DO_PONTO = 400
MAX_LACUNAS_DO_MODELO = 5
MAX_TEXTO_DA_LACUNA = 200

TITULOS = {
    "cases": "Cases parecidos",
    "perfil": "O que sabemos de {segmento}",
    "roteiro": "Roteiro de condução",
    "objecoes": "Objeções prováveis",
    "proposta": "Estrutura da proposta",
}
SECAO_DO_BANCO_POR_REUNIAO = {
    "diagnostico": "reuniao_diagnostico", "proposta": "proposta", "negociacao": "negociacao_fechamento",
}
# Seções da base que a reunião precisa ter coberta (sem item nelas, vira lacuna calculada pelo código).
SECOES_QUE_IMPORTAM = {
    "diagnostico": ["reuniao_diagnostico"],
    "proposta": ["proposta"],
    "negociacao": ["negociacao_fechamento"],
}
NOME_DA_SECAO = {
    "reuniao_diagnostico": "reunião de diagnóstico",
    "proposta": "proposta",
    "negociacao_fechamento": "negociação e fechamento",
}

_CODIGO = re.compile(r"^\s*\[?\s*(INS|DOC)\s*-\s*(\d+)\s*\]?\s*$", re.IGNORECASE)
_CODIGO_NO_TEXTO = re.compile(r"\s*\[\s*(?:INS|DOC)\s*-\s*\d+(?:\s*[,;]\s*(?:INS|DOC)\s*-\s*\d+)*\s*\]", re.IGNORECASE)


@dataclass
class Selecao:
    itens: list[Insight]
    de_outro_segmento: set[int]


def selecionar_itens(db: Session, segmento: str, tipo_reuniao: str) -> Selecao:
    """Os itens aprovados que o briefing pode usar: do segmento (ou sem segmento), por prioridade, com teto por tipo.
    No diagnóstico, se o segmento tem pouco, entram até 3 de outros segmentos (marcados, para o modelo avisar)."""
    aprovados = list(db.scalars(select(Insight).where(Insight.status.in_(knowledge.STATUS_NA_BASE))))
    aprovados.sort(key=knowledge._prioridade, reverse=True)

    do_segmento = [i for i in aprovados if i.segmento in (segmento, None)]
    escolhidos: list[Insight] = []
    por_tipo: dict[str, int] = {}
    for item in do_segmento:
        if por_tipo.get(item.tipo, 0) < TETO_POR_TIPO.get(item.tipo, 4):
            escolhidos.append(item)
            por_tipo[item.tipo] = por_tipo.get(item.tipo, 0) + 1

    de_fora: set[int] = set()
    if tipo_reuniao == "diagnostico" and len(escolhidos) < MIN_DO_SEGMENTO:
        ja = {i.id for i in escolhidos}
        extras = [i for i in aprovados if i.id not in ja and i.segmento not in (segmento, None)]
        for item in extras[:MAX_DE_OUTRO_SEGMENTO]:
            escolhidos.append(item)
            de_fora.add(item.id)
    return Selecao(escolhidos, de_fora)


def _linha(item: Insight, de_fora: set[int]) -> str:
    linha = knowledge.formatar(item)
    return linha + " | DE OUTRO SEGMENTO" if item.id in de_fora else linha


def lacunas_calculadas(segmento: str, tipo_reuniao: str, itens: list[Insight]) -> list[str]:
    """O que falta, contado pelo código (não depende do modelo): sem case, sem perfil, sem objeção, seção vazia."""
    do_segmento = [i for i in itens if i.segmento in (segmento, None)]
    achados: list[str] = []
    if not any(i.tipo == "case" for i in do_segmento):
        achados.append(f"Nenhum case aprovado de {segmento}.")
    if not any(i.tipo == "perfil_segmento" for i in do_segmento):
        achados.append(f"Ninguém registrou o perfil de {segmento} (como decide, quem decide, sazonalidade).")
    if not any(i.tipo == "objecao" for i in do_segmento):
        achados.append(f"Nenhuma objeção registrada para {segmento}.")
    for secao in SECOES_QUE_IMPORTAM[tipo_reuniao]:
        if not any(i.secao == secao for i in do_segmento):
            achados.append(f"A base não tem nada aprovado na seção de {NOME_DA_SECAO[secao]} para {segmento}.")
    return achados


def montar(db: Session, dados: BriefingIn) -> BriefingOut:
    """O briefing completo. Levanta llm.ErroLLM se o modelo falhar (a rota vira 502)."""
    segmento = dados.segmento
    selecao = selecionar_itens(db, segmento, dados.tipo_reuniao)
    consulta = f"{segmento} {dados.tipo_reuniao} {dados.contexto or ''}"
    achados = busca.buscar(db, consulta)
    docs_citaveis = [DocumentoCitavel(id=a.fonte_id, titulo=a.titulo, url=a.url, categoria=a.categoria)
                     for a in achados]
    itens_out = [
        ItemDoBriefing(
            id=i.id, codigo=f"INS-{i.id}", titulo=i.titulo, tipo=i.tipo, secao=i.secao, evidencia=i.evidencia,
            de_outro_segmento=i.id in selecao.de_outro_segmento,
        )
        for i in selecao.itens
    ]
    calculadas = lacunas_calculadas(segmento, dados.tipo_reuniao, selecao.itens)

    if not selecao.itens and not achados:
        return BriefingOut(
            segmento=segmento, tipo_reuniao=dados.tipo_reuniao,
            resumo=f"A base ainda não tem nada aprovado para {segmento}: não há o que montar.",
            secoes=[_secao(chave, segmento, []) for chave in TITULOS],
            lacunas=calculadas, itens=[], documentos=[],
            avisos=["Sem itens aprovados nem documentos do Drive para este segmento: o modelo não foi chamado."],
            usou_modelo=False,
        )

    linhas = "\n".join(_linha(i, selecao.de_outro_segmento) for i in selecao.itens) or knowledge.BASE_VAZIA
    bruto = llm.briefar(segmento, dados.tipo_reuniao, dados.contexto or "", linhas,
                        knowledge.montar_documentos(achados))
    return _conferir(bruto, dados, selecao, achados, docs_citaveis, itens_out, calculadas)


def _conferir(bruto: BriefingLLM, dados: BriefingIn, selecao: Selecao, achados: list[busca.Achado],
              docs: list[DocumentoCitavel], itens_out: list[ItemDoBriefing], calculadas: list[str]) -> BriefingOut:
    """O código dispõe: só fica ponto com fonte válida, com a evidência calculada a partir dos itens citados."""
    por_id = {i.id: i for i in selecao.itens}
    docs_por_id = {a.fonte_id: a for a in achados}
    avisos: list[str] = []
    descartados = 0

    secoes = []
    for chave in TITULOS:
        pontos = []
        for p in getattr(bruto, chave):
            ponto = _ponto_valido(p, por_id, docs_por_id)
            if ponto is None:
                descartados += 1
            elif len(pontos) < MAX_PONTOS_POR_SECAO:
                pontos.append(ponto)
        secoes.append(_secao(chave, dados.segmento, pontos))
    if descartados:
        avisos.append(
            f"{descartados} ponto(s) do modelo foram descartados por citar fonte que não existe ou não citar nenhuma."
        )

    lacunas = list(calculadas)
    vistas = {_normal(x) for x in lacunas}
    for texto in bruto.lacunas[:MAX_LACUNAS_DO_MODELO]:
        limpo = _limpar(texto)[:MAX_TEXTO_DA_LACUNA]
        if limpo and _normal(limpo) not in vistas:
            vistas.add(_normal(limpo))
            lacunas.append(limpo)

    return BriefingOut(
        segmento=dados.segmento, tipo_reuniao=dados.tipo_reuniao, resumo=_limpar(bruto.resumo)[:600],
        secoes=secoes, lacunas=lacunas, itens=itens_out, documentos=docs, avisos=avisos, usou_modelo=True,
    )


def _secao(chave: str, segmento: str, pontos: list[PontoOut]) -> SecaoOut:
    return SecaoOut(chave=chave, titulo=TITULOS[chave].format(segmento=segmento), pontos=pontos)


def _ponto_valido(p: PontoLLM, por_id: dict[int, Insight], docs_por_id: dict[int, busca.Achado]) -> PontoOut | None:
    fontes: list[FonteDoPonto] = []
    vistos: set[str] = set()
    for bruto in p.fontes:
        m = _CODIGO.match(bruto)
        if not m:
            continue
        tipo, n = m.group(1).upper(), int(m.group(2))
        codigo = f"{tipo}-{n}"
        if codigo in vistos:
            continue
        if tipo == "INS" and n in por_id:
            fontes.append(FonteDoPonto(codigo=codigo, titulo=por_id[n].titulo, tipo="item"))
        elif tipo == "DOC" and n in docs_por_id:
            fontes.append(FonteDoPonto(codigo=codigo, titulo=docs_por_id[n].titulo, tipo="documento",
                                       url=docs_por_id[n].url))
        else:
            continue
        vistos.add(codigo)
    texto = _limpar(p.texto)[:MAX_TEXTO_DO_PONTO]
    if not fontes or not texto:
        return None
    evidencias = [por_id[int(f.codigo[4:])].evidencia for f in fontes if f.tipo == "item"]
    return PontoOut(
        texto=texto, fontes=fontes,
        evidencia_minima=min(evidencias) if evidencias else None,
        nao_revisado=any(f.tipo == "documento" for f in fontes),
    )


def _limpar(texto: str) -> str:
    """O id vai no campo `fontes`, não no texto: tira "[INS-12]" escrito no meio e arruma os espaços."""
    return " ".join(_CODIGO_NO_TEXTO.sub("", texto).split())


def _normal(texto: str) -> str:
    return " ".join(busca.palavras(texto))
