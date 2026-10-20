"""Golden set do consultor: as perguntas-teste contra uma base de itens, com o Gemini DE VERDADE.

Gasta cota, então roda só à mão:
    pytest -m live tests/golden                      # base fictícia (base.json + perguntas.json)
    GOLDEN_BASE=real pytest -m live tests/golden     # base real (base_real.json + perguntas_real.json, fora do Git)
    GOLDEN_PAUSA_S=1 pytest -m live tests/golden     # pausa menor entre perguntas (chave paga)
    pytest -m live tests/golden -k "P21 or P23"      # só alguns casos
- Sem GEMINI_API_KEY no .env, os testes são pulados.
- No `pytest` normal (e no CI) eles nem rodam: o pytest.ini tem `-m "not live"`.

Arquivos:
- base.json: os itens fictícios (como se já tivessem sido aprovados na Fila);
- perguntas.json: as perguntas de docs/perguntas-teste.md (P01 a P20) e as da persona (P21 em diante, ADR-009);
- base_real.json: os itens aprovados de verdade (python -m scripts.exportar_golden), fora do Git;
- perguntas_real.json: as perguntas do comercial sobre a base real, fora do Git;
- ultima_execucao.md / ultima_execucao_real.md: as respostas da última rodada, para a análise (fora do Git).

Cada caso de perguntas*.json tem `n`, `pergunta`, `testa`, `coberta` e `esperados`, e pode ter:
- `historico`: as falas anteriores ([{"role": "user" ou "model", "text": ...}]), para os casos de mais de um turno;
- `deve_citar`: ids que TODOS têm que aparecer (o item que a pessoa contradiz, o que o caso dela reforça);
- `pergunta_de_volta`: a pergunta é vaga, então a resposta pergunta algo e NÃO diz "A base não cobre";
- `registrar`: a resposta sugere registrar o aprendizado;
- `proximo_passo`: a resposta fecha com "Próximo passo";
- `livre`: quais checks gerais da persona não valem no caso ("teto" e/ou "perguntas"), como na preparação de
  reunião, que é longa e traz perguntas para fazer ao cliente.

O que se confere (tests/golden/checks.py, com testes sem o Gemini em tests/test_golden_checks.py):
- [regra] nenhum id inventado (todo INS-n citado existe na base);
- [regra] uma citação por colchete ([INS-2] [INS-7]), que é o que a tela transforma em link;
- [regra] pergunta coberta: cita pelo menos um dos esperados; sem cobertura: diz "A base não cobre" (é a frase que
  o app/lacunas.py procura para guardar a lacuna);
- [persona] sem emoji; no máximo 2 frases com "?"; até 160 palavras fora os ids (a meta é cerca de 120); e os
  checks opcionais acima. As decisões da persona estão no ADR-009.
Tom, crítica e formato dos avisos não dá para conferir por código: ficam na nota humana da rodada.
Todas as falhas de um caso aparecem juntas (no relatório e na mensagem do assert), e não só a primeira.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from app import knowledge, llm
from app.config import settings
from app.models import Insight
from tests.golden.checks import citados, falhas_de, palavras, perguntas

PASTA = Path(__file__).parent
REAL = os.environ.get("GOLDEN_BASE", "ficticia") == "real"
if REAL:
    ARQ_BASE, ARQ_PERGUNTAS, SAIDA = (PASTA / "base_real.json", PASTA / "perguntas_real.json",
                                      PASTA / "ultima_execucao_real.md")
else:
    ARQ_BASE, ARQ_PERGUNTAS, SAIDA = PASTA / "base.json", PASTA / "perguntas.json", PASTA / "ultima_execucao.md"
if not (ARQ_BASE.exists() and ARQ_PERGUNTAS.exists()):
    pytest.skip(f"falta {ARQ_BASE.name} ou {ARQ_PERGUNTAS.name} (a base real sai de python -m scripts.exportar_golden)",
                allow_module_level=True)

PAUSA_S = float(os.environ.get("GOLDEN_PAUSA_S", "6"))  # a camada gratuita limita as chamadas por minuto

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.gemini_api_key, reason="sem GEMINI_API_KEY no .env"),
]


def carregar_itens() -> list[Insight]:
    """Os itens da base como Insights em memória (sem banco): é a mesma formatação que o /chat usa."""
    dados = json.loads(ARQ_BASE.read_text(encoding="utf-8"))
    for d in dados:
        if d["data_evento"]:
            d["data_evento"] = datetime.strptime(d["data_evento"], "%Y-%m-%d").date()
    return [Insight(**d, status="validado", autor="golden", criado_em=datetime(2026, 10, 1)) for d in dados]


ITENS = carregar_itens()
IDS = {i.id for i in ITENS}
BASE = knowledge.compor_base(ITENS)
PERGUNTAS = json.loads(ARQ_PERGUNTAS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def relatorio():
    """Junta as respostas da rodada e, no fim, grava o ultima_execucao*.md com um resumo no topo."""
    rodada = {"resumo": [], "detalhes": []}
    yield rodada
    base = "real" if REAL else "fictícia"
    cabecalho = (f"# Golden set do consultor: {datetime.now():%Y-%m-%d %H:%M}, modelo {settings.model_consultor}, "
                 f"base {base} ({len(ITENS)} itens)\n\n## Resumo\n"
                 "| caso | palavras | perguntas | falhas |\n|---|---|---|---|")
    SAIDA.write_text("\n".join([cabecalho, *rodada["resumo"], *rodada["detalhes"]]) + "\n", encoding="utf-8")


def test_tokens_por_item(relatorio):
    """Mede o formato enxuto contra o formato completo (o do knowledge/exemplos.md, medido no ADR-003 §4)."""
    enxuto = llm.contar_tokens(BASE) / len(ITENS)
    exemplos = (PASTA.parent.parent / "knowledge" / "exemplos.md").read_text(encoding="utf-8")
    completo = llm.contar_tokens(exemplos) / exemplos.count("## [EX-")

    relatorio["detalhes"].append(
        f"\n## Tokens por item\n- enxuto ({ARQ_BASE.name}, {len(ITENS)} itens): {enxuto:.0f}\n"
        f"- completo (knowledge/exemplos.md): {completo:.0f}\n"
    )
    assert enxuto < completo


@pytest.mark.parametrize("caso", PERGUNTAS, ids=lambda c: f"P{c['n']:02d}")
def test_pergunta(caso, relatorio):
    time.sleep(PAUSA_S)
    historico = caso.get("historico", [])
    resposta = llm.consultar(caso["pergunta"], historico, BASE)
    falhas = falhas_de(caso, resposta, IDS)

    conversa = "".join(f"> **{h['role']}:** {h['text']}\n>\n" for h in historico)
    relatorio["resumo"].append(
        f"| P{caso['n']:02d} | {palavras(resposta)} | {perguntas(resposta)} | {'; '.join(falhas) or 'ok'} |"
    )
    relatorio["detalhes"].append(
        f"\n## P{caso['n']:02d}: {caso['pergunta']}\n"
        f"- testa: {caso['testa']}\n"
        f"- coberta: {caso['coberta']}; esperados: {caso['esperados']}; citados: {sorted(citados(resposta))}\n"
        f"- falhas: {'; '.join(falhas) or 'nenhuma'}\n\n{conversa}{resposta}\n"
    )

    assert not falhas, " | ".join(falhas)
