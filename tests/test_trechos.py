"""Testes do app/trechos.py: a página normal vai inteira; a grande é dividida nos títulos, sem passar do limite e sem
perder texto nem contexto. Os testes de divisão baixam o limite para 400 caracteres, para os textos ficarem curtos."""
import pytest

from app import trechos
from app.trechos import dividir


@pytest.fixture
def limite_baixo(monkeypatch):
    monkeypatch.setattr(trechos, "LIMITE_TRECHO", 400)
    monkeypatch.setattr(trechos, "_RESERVA_CABECALHO", 100)
    return 300  # a capacidade de conteúdo de cada trecho (400 - 100)


def conteudo(trecho) -> str:
    """O texto do trecho sem o cabeçalho."""
    return trecho.texto.split("\n\n", 1)[1]


def test_limite_padrao_e_o_mesmo_do_registrar():
    from app.schemas import RegistrarIn
    limite_do_registrar = next(m.max_length for m in RegistrarIn.model_fields["texto"].metadata
                               if hasattr(m, "max_length"))
    assert trechos.LIMITE_TRECHO == limite_do_registrar == 8000
    assert trechos.MAX_TRECHOS == 5


def test_pagina_normal_vai_inteira_com_o_titulo_no_topo():
    markdown = "## Perguntas\n\n- Quem decide?\n\nTexto final."

    [trecho] = dividir("Como qualificar leads", markdown)

    assert trecho.texto == f"Página do Notion: Como qualificar leads\n\n{markdown}"
    assert (trecho.parte, trecho.total) == (1, 1)


def test_pagina_exatamente_no_limite_ainda_vai_inteira(limite_baixo):
    titulo = "T"
    markdown = "x" * (400 - len("Página do Notion: T") - 2)

    assert len(dividir(titulo, markdown)) == 1
    assert len(dividir(titulo, markdown + "y")) > 1


def test_pagina_vazia_nao_tem_trecho():
    assert dividir("Índice", "  \n") == []


def test_pagina_grande_e_cortada_nos_titulos_com_o_caminho_no_cabecalho(limite_baixo):
    secao_a = "# Prospecção\n\n" + "a" * 200
    secao_b = "## Indicação\n\n" + "b" * 200
    secao_c = "# Proposta\n\n" + "c" * 200

    partes = dividir("Manual", "\n\n".join([secao_a, secao_b, secao_c]))

    assert [p.texto.split("\n")[1] for p in partes] == [
        "Seção: Prospecção", "Seção: Prospecção › Indicação", "Seção: Proposta",
    ]
    assert [(p.parte, p.total) for p in partes] == [(1, 3), (2, 3), (3, 3)]
    assert all(p.texto.startswith("Página do Notion: Manual\n") for p in partes)
    assert all("(parte" in p.texto for p in partes)
    assert [conteudo(p) for p in partes] == [secao_a, secao_b, secao_c]  # nenhum texto se perde


def test_secoes_pequenas_vizinhas_sao_juntadas(limite_baixo):
    secoes = [f"## S{i}\n\n" + "x" * 80 for i in range(6)]  # 6 seções de ~86 caracteres

    partes = dividir("Manual", "\n\n".join(secoes))

    assert len(partes) == 2  # 3 seções por trecho (3 × 86 + separadores ≤ 300)
    assert partes[1].texto.split("\n")[1] == "Seção: S3"  # o caminho é o da 1ª seção do trecho
    assert "## S4" in partes[1].texto


def test_texto_antes_do_primeiro_titulo_e_o_inicio_da_pagina(limite_baixo):
    partes = dividir("Manual", "intro " * 40 + "\n\n# Depois\n\n" + "d" * 250)

    assert partes[0].texto.split("\n")[1] == "Seção: (início da página)"


def test_secao_maior_que_o_limite_e_dividida_entre_paragrafos_linhas_e_no_meio(limite_baixo):
    paragrafos = ["p" * 200, "q" * 200]  # cabem um por trecho
    linhas = "\n".join(["r" * 150, "s" * 150, "t" * 150])  # um parágrafo de 3 linhas: vira 2 trechos
    sem_quebra = "u" * 700  # uma linha só: cortada no meio
    markdown = "# Grande\n\n" + "\n\n".join([*paragrafos, linhas, sem_quebra])

    partes = dividir("Manual", markdown)

    assert all(len(p.texto) <= 400 for p in partes)
    assert all(p.texto.split("\n")[1] == "Seção: Grande" for p in partes)
    juntos = "".join(conteudo(p) for p in partes)
    for pedaco in ["p" * 200, "q" * 200, "r" * 150, "s" * 150, "t" * 150]:
        assert pedaco in juntos
    assert juntos.count("u") == 700  # o texto cortado no meio continua inteiro, só em pedaços


def test_titulo_dentro_de_bloco_de_codigo_nao_corta(limite_baixo):
    markdown = "# Real\n\n```\n# comentário, não título\n" + "c" * 250 + "\n```\n\n" + "z" * 100

    partes = dividir("Manual", markdown)

    assert {p.texto.split("\n")[1] for p in partes} == {"Seção: Real"}


def test_titulo_e_caminho_longos_sao_cortados_no_cabecalho():
    titulo = "T" * 400
    markdown = "# " + "S" * 400 + "\n\n" + "x " * 4000 + "\n\n" + "y " * 4000

    partes = dividir(titulo, markdown)

    assert len(partes) > 1
    assert all(len(p.texto) <= trechos.LIMITE_TRECHO for p in partes)  # mesmo com o cabeçalho
    assert partes[0].texto.startswith("Página do Notion: " + "T" * 149 + "…\nSeção: " + "S" * 199 + "…\n")


def test_subtitulo_sem_titulo_acima_nao_herda_o_irmao(limite_baixo):
    partes = dividir("Manual", "## A\n\n" + "a" * 250 + "\n\n## B\n\n" + "b" * 250 + "\n\n### B1\n\n" + "c" * 250)

    assert [p.texto.split("\n")[1] for p in partes] == ["Seção: A", "Seção: B", "Seção: B › B1"]


def test_nenhum_trecho_passa_do_limite_padrao():
    markdown = "\n\n".join(f"## Seção {i}\n\n" + "palavra " * 900 for i in range(6))  # ~43 mil caracteres

    partes = dividir("Manual completo", markdown)

    assert len(partes) > trechos.MAX_TRECHOS  # é uma página "longa demais"
    assert all(len(p.texto) <= trechos.LIMITE_TRECHO for p in partes)
