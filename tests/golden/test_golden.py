"""Golden set do consultor: as perguntas-teste contra uma base fictícia, com o Gemini DE VERDADE.

Gasta cota, então roda só à mão:  pytest -m live tests/golden
- Sem GEMINI_API_KEY no .env, os testes são pulados.
- No `pytest` normal (e no CI) eles nem rodam: o pytest.ini tem `-m "not live"`.

Arquivos:
- base.json: os itens fictícios (como se já tivessem sido aprovados na Fila);
- perguntas.json: as 20 perguntas de docs/perguntas-teste.md, cada uma com o que se espera;
- ultima_execucao.md: as respostas da última rodada, para a análise do ADR-004 (fora do Git).

O que se confere em cada resposta:
- nenhum id inventado: todo [INS-n] citado existe na base;
- pergunta coberta pela base: cita pelo menos um dos itens esperados;
- pergunta sem cobertura (de propósito): admite a lacuna com a frase do prompt ("A base não cobre").
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

import pytest

from app import knowledge, llm
from app.config import settings
from app.models import Insight

PASTA = Path(__file__).parent
SAIDA = PASTA / "ultima_execucao.md"
LACUNA = "A base não cobre"  # a frase que o app/prompts/consultor.md manda usar
CITACAO = re.compile(r"\[INS-(\d+)\]")
PAUSA_S = 6  # entre perguntas: a camada gratuita limita as chamadas por minuto

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.gemini_api_key, reason="sem GEMINI_API_KEY no .env"),
]


def carregar_itens() -> list[Insight]:
    """Os itens da base.json como Insights em memória (sem banco): é a mesma formatação que o /chat usa."""
    dados = json.loads((PASTA / "base.json").read_text(encoding="utf-8"))
    for d in dados:
        if d["data_evento"]:
            d["data_evento"] = datetime.strptime(d["data_evento"], "%Y-%m-%d").date()
    return [Insight(**d, status="validado", autor="golden", criado_em=datetime(2026, 10, 1)) for d in dados]


ITENS = carregar_itens()
IDS = {i.id for i in ITENS}
BASE = knowledge.compor_base(ITENS)
PERGUNTAS = json.loads((PASTA / "perguntas.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def relatorio():
    """Junta as respostas da rodada e, no fim, grava o ultima_execucao.md."""
    linhas: list[str] = []
    yield linhas
    cabecalho = f"# Golden set do consultor: {datetime.now():%Y-%m-%d %H:%M}, modelo {settings.model_consultor}\n"
    SAIDA.write_text(cabecalho + "\n".join(linhas) + "\n", encoding="utf-8")


def test_tokens_por_item(relatorio):
    """Mede o formato enxuto contra o formato completo (o do knowledge/exemplos.md, medido no ADR-003 §4)."""
    enxuto = llm.contar_tokens(BASE) / len(ITENS)
    exemplos = (PASTA.parent.parent / "knowledge" / "exemplos.md").read_text(encoding="utf-8")
    completo = llm.contar_tokens(exemplos) / exemplos.count("## [EX-")

    relatorio.append(
        f"\n## Tokens por item\n- enxuto (base.json, {len(ITENS)} itens): {enxuto:.0f}\n"
        f"- completo (knowledge/exemplos.md): {completo:.0f}\n"
    )
    assert enxuto < completo


@pytest.mark.parametrize("caso", PERGUNTAS, ids=lambda c: f"P{c['n']:02d}")
def test_pergunta(caso, relatorio):
    time.sleep(PAUSA_S)
    resposta = llm.consultar(caso["pergunta"], [], BASE)
    citados = sorted({int(n) for n in CITACAO.findall(resposta)})
    inventados = [n for n in citados if n not in IDS]
    relatorio.append(
        f"\n## P{caso['n']:02d}: {caso['pergunta']}\n"
        f"- testa: {caso['testa']}\n"
        f"- coberta: {caso['coberta']}; esperados: {caso['esperados']}; citados: {citados}\n\n{resposta}\n"
    )

    assert not inventados, f"citou id que não existe na base: {inventados}"
    if caso["coberta"]:
        assert set(caso["esperados"]) & set(citados), f"não citou nenhum dos esperados {caso['esperados']}"
    else:
        assert LACUNA in resposta, "a base não cobre a pergunta, mas a resposta não admitiu a lacuna"
