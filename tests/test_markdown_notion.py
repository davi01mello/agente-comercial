"""Testes do app/markdown_notion.py: blocos do Notion (no formato da API) → markdown. Funções puras, sem rede.

Os blocos aqui são montados à mão, só com os campos que a conversão usa. O teste do fim usa as páginas do workspace
fictício inteiras, como o leitor as devolve.
"""
import pytest

from app import markdown_notion as md
from app import notion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, id_da_pagina


def rt(texto, href=None, **anotacoes):
    return {"type": "text", "text": {"content": texto}, "plain_text": texto, "href": href, "annotations": anotacoes}


def bloco(tipo, *ricos, filhos=None, **dados):
    b = {"type": tipo, tipo: {"rich_text": list(ricos), **dados}}
    if filhos is not None:
        b["_filhos"] = filhos
    return b


def converter(*blocos):
    return md.para_markdown(list(blocos))


# --- texto rico -------------------------------------------------------------------------------------------

def test_links_e_formatacao():
    saida = converter(bloco(
        "paragraph",
        rt("Veja "), rt("isto", bold=True), rt(", "), rt("aquilo", italic=True), rt(", "), rt("x=1", code=True),
        rt(", "), rt("velho", strikethrough=True), rt(" e o "), rt("modelo", href="https://exemplo.com/m"), rt("."),
    ))

    assert saida == "Veja **isto**, _aquilo_, `x=1`, ~~velho~~ e o [modelo](https://exemplo.com/m)."


def test_formatacao_deixa_os_espacos_das_pontas_de_fora():
    """'** importante **' não é negrito em markdown."""
    assert converter(bloco("paragraph", rt("é"), rt(" importante ", bold=True), rt("sim"))) == "é **importante** sim"
    assert converter(bloco("paragraph", rt("a"), rt("  ", bold=True), rt("b"))) == "a  b"  # só espaço: sem marca


def test_pessoa_mencionada_vira_marcador_e_o_nome_nao_aparece():
    mencao = {"type": "mention", "mention": {"type": "user", "user": {"id": "u1"}}, "plain_text": "@Joana Fictícia",
              "href": None, "annotations": {}}

    saida = converter(bloco("paragraph", rt("Fale com "), mencao, rt(".")))

    assert saida == "Fale com @pessoa."
    assert "Joana" not in saida


def test_mencao_a_pagina_ou_data_usa_o_texto_e_equacao_inline():
    pagina = {"type": "mention", "mention": {"type": "page", "page": {"id": "p1"}}, "plain_text": "Roteiro",
              "href": "https://www.notion.so/p1", "annotations": {}}
    data = {"type": "mention", "mention": {"type": "date", "date": {"start": "2026-10-01"}},
            "plain_text": "2026-10-01", "href": None, "annotations": {}}
    equacao = {"type": "equation", "equation": {"expression": "a+b"}, "plain_text": "a+b", "annotations": {}}

    assert converter(bloco("paragraph", pagina, rt(" em "), data, rt(" "), equacao)) == "Roteiro em 2026-10-01 $a+b$"


def test_titulo_da_pagina_comum_e_da_linha_de_banco():
    comum = {"properties": {"title": {"type": "title", "title": [rt("Roteiro "), rt("v2", bold=True)]}}}
    linha = {"properties": {"Segmento": {"type": "select"}, "Nome": {"type": "title", "title": [rt("Hotel Sol")]}}}

    assert md.titulo(comum) == "Roteiro v2"  # sem formatação
    assert md.titulo(linha) == "Hotel Sol"
    assert md.titulo({"properties": {}}) == ""


# --- blocos -----------------------------------------------------------------------------------------------

def test_titulos():
    saida = converter(bloco("heading_1", rt("Um")), bloco("heading_2", rt("Dois")), bloco("heading_3", rt("Três")))

    assert saida == "# Um\n\n## Dois\n\n### Três"


def test_titulo_que_abre_e_fecha_leva_os_filhos():
    saida = converter(bloco("heading_2", rt("Dicas"), is_toggleable=True, filhos=[bloco("paragraph", rt("Ouça."))]))

    assert saida == "## Dicas\n\nOuça."


def test_listas_aninhadas():
    saida = converter(
        bloco("bulleted_list_item", rt("A"), filhos=[
            bloco("bulleted_list_item", rt("A1"), filhos=[bloco("bulleted_list_item", rt("A1a"))]),
        ]),
        bloco("bulleted_list_item", rt("B")),
    )

    assert saida == "- A\n  - A1\n    - A1a\n- B"


def test_lista_numerada_conta_e_recomeca_depois_de_outro_bloco():
    saida = converter(
        bloco("numbered_list_item", rt("um"), filhos=[bloco("numbered_list_item", rt("sub"))]),
        bloco("numbered_list_item", rt("dois")),
        bloco("paragraph", rt("pausa")),
        bloco("numbered_list_item", rt("de novo")),
    )

    assert saida == "1. um\n   1. sub\n2. dois\n\npausa\n\n1. de novo"


def test_tarefas_e_toggle():
    saida = converter(
        bloco("to_do", rt("feito"), checked=True),
        bloco("to_do", rt("falta"), checked=False),
        bloco("toggle", rt("Mais"), filhos=[bloco("paragraph", rt("escondido"))]),
    )

    assert saida == "- [x] feito\n- [ ] falta\n- Mais\n  escondido"


def test_quebra_de_linha_dentro_do_item_fica_recuada():
    assert converter(bloco("bulleted_list_item", rt("linha 1\nlinha 2"))) == "- linha 1\n  linha 2"


def test_citacao_e_destaque():
    saida = converter(
        bloco("quote", rt("Ouça mais."), filhos=[bloco("paragraph", rt("Sempre."))]),
        bloco("callout", rt("Atenção"), icon={"type": "emoji", "emoji": "💡"}),
        bloco("callout", rt("Sem ícone"), icon=None),
    )

    assert saida == "> Ouça mais.\n> Sempre.\n\n> 💡 Atenção\n\n> Sem ícone"


def test_codigo_divisor_e_equacao():
    saida = converter(
        bloco("code", rt("x = 1", bold=True), language="python"),
        {"type": "divider", "divider": {}},
        {"type": "equation", "equation": {"expression": "e=mc^2"}},
    )

    assert saida == "```python\nx = 1\n```\n\n---\n\n$$e=mc^2$$"  # código sem formatação


def linha(*celulas):
    return {"type": "table_row", "table_row": {"cells": [[rt(c)] for c in celulas]}}


def tabela(*linhas, cabecalho=True, largura=2):
    return {"type": "table", "table": {"table_width": largura, "has_column_header": cabecalho},
            "_filhos": list(linhas)}


def test_tabela():
    saida = converter(tabela(linha("Objeção", "Resposta"), linha("Está caro", "Mostrar o custo")))

    assert saida == "| Objeção | Resposta |\n| --- | --- |\n| Está caro | Mostrar o custo |"


def test_tabela_sem_cabecalho_e_barra_e_quebra_na_celula():
    """Sem cabeçalho no Notion, o do markdown fica vazio (ele é obrigatório) e nenhuma linha some. '|' e a quebra de
    linha dentro da célula desmontariam a tabela."""
    saida = converter(tabela(linha("a | b", "c\nd"), linha("e", "f"), cabecalho=False))

    assert saida == "|  |  |\n| --- | --- |\n| a / b | c d |\n| e | f |"


def test_tabela_com_linha_curta_e_tabela_vazia():
    assert converter(tabela(linha("só uma"), largura=2)) == "| só uma |  |\n| --- | --- |"
    assert converter(tabela(), bloco("paragraph", rt("depois"))) == "depois"


def test_colunas_e_bloco_sincronizado_valem_os_filhos():
    saida = converter(
        {"type": "column_list", "column_list": {}, "_filhos": [
            {"type": "column", "column": {}, "_filhos": [bloco("paragraph", rt("esquerda"))]},
            {"type": "column", "column": {}, "_filhos": [bloco("paragraph", rt("direita"))]},
        ]},
        {"type": "synced_block", "synced_block": {}, "_filhos": [bloco("paragraph", rt("sincronizado"))]},
    )

    assert saida == "esquerda\n\ndireita\n\nsincronizado"


@pytest.mark.parametrize("b, esperado", [
    ({"type": "child_page", "child_page": {"title": "Roteiro"}}, "[subpágina: Roteiro]"),
    ({"type": "child_database", "child_database": {"title": "Clientes"}}, "[banco de dados: Clientes (não importado)]"),
    ({"type": "bookmark", "bookmark": {"url": "https://x.com", "caption": []}}, "[https://x.com](https://x.com)"),
    ({"type": "embed", "embed": {"url": "https://x.com", "caption": [rt("vídeo")]}}, "[vídeo](https://x.com)"),
    ({"type": "link_preview", "link_preview": {"url": ""}}, ""),
    ({"type": "link_to_page", "link_to_page": {"type": "page_id", "page_id": "p"}}, "[link para outra página]"),
    ({"type": "image", "image": {"caption": [rt("fluxo")]}}, "[imagem: fluxo]"),
    ({"type": "pdf", "pdf": {"caption": []}}, "[PDF]"),
    ({"type": "meeting_notes", "meeting_notes": {"title": []}}, "[notas de reunião (não importadas)]"),
    ({"type": "transcription", "transcription": {}}, "[notas de reunião (não importadas)]"),
    ({"type": "table_of_contents", "table_of_contents": {}}, ""),
    ({"type": "unsupported", "unsupported": {"block_type": "form"}}, "[bloco não suportado: form]"),
    ({"type": "tipo_que_ainda_nao_existe", "tipo_que_ainda_nao_existe": {}},
     "[bloco não suportado: tipo_que_ainda_nao_existe]"),
])
def test_blocos_que_nao_sao_texto_viram_marcador(b, esperado):
    assert converter(b) == esperado


def test_paragrafo_vazio_some_e_aninhado_demais_avisa():
    saida = converter(
        bloco("paragraph"),
        bloco("bulleted_list_item", rt("fundo")) | {"_profundo_demais": True},
    )

    assert saida == "- fundo\n  [conteúdo aninhado demais (não importado)]"


# --- normalização, hash e tamanho -----------------------------------------------------------------------

def test_normalizar_tira_espacos_e_linhas_em_branco_a_mais():
    assert md.normalizar("\n\na  \n\n\n\nb\t\n\n") == "a\n\nb"


def test_hash_ignora_espacos_e_forma_unicode_mas_nao_o_texto():
    composto = "Sau\u0301de"  # o "ú" escrito como "u" + acento: outros bytes, o mesmo texto
    assert md.hash_conteudo("Saúde  \n\n\n") == md.hash_conteudo(composto)
    assert md.hash_conteudo("Saúde") != md.hash_conteudo("Saúde.")
    assert len(md.hash_conteudo("x")) == 64


def test_caracteres_de_texto_ignora_titulos_marcadores_e_espacos():
    texto = "# Título grande\n\n[subpágina: Roteiro]\n\n[imagem: fluxo]\n\nab c"

    assert md.caracteres_de_texto(texto) == 3


# --- as páginas do workspace fictício, de ponta a ponta ----------------------------------------------------

@pytest.fixture
def ler(monkeypatch):
    monkeypatch.setattr(notion, "_dormir", lambda s: None)
    falso = NotionFalso()
    leitor = notion.LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http())
    return lambda titulo: md.para_markdown(leitor.blocos(id_da_pagina(falso.ws, titulo)))


def test_pagina_ficticia_com_titulos_listas_e_links(ler):
    assert ler("Como qualificar leads de hotelaria") == (
        "Antes da primeira reunião, confira se o hotel tem **orçamento aprovado** e quem decide. Veja o "
        "[modelo de qualificação](https://exemplo.com/modelo).\n"
        "\n"
        "## Perguntas que funcionam\n"
        "\n"
        "- Quantos quartos o hotel tem?\n"
        "- Quem aprova o orçamento?\n"
        "  - Se for o dono, a decisão é rápida.\n"
        "  - Se for um conselho, conte com duas reuniões a mais.\n"
        "- _Qual sistema usam hoje?_\n"
        "\n"
        "## Sinais de alerta\n"
        "\n"
        "1. Não sabe dizer o orçamento.\n"
        "2. Quer proposta antes do diagnóstico.\n"
        "\n"
        "Nas 3 reuniões em que pedimos o orçamento logo no início, a conversa ficou mais objetiva."
    )


def test_pagina_ficticia_com_tabela(ler):
    assert ler("Objeções comuns e respostas").endswith(
        "| Objeção | Resposta | Funcionou? |\n"
        "| --- | --- | --- |\n"
        "| Está caro | Mostrar o custo de não fazer / comparar com o prejuízo | 2 de 3 vezes |\n"
        "| Vamos pensar | Marcar a próxima conversa na hora | sim |\n"
        "| Já temos um fornecedor | Propor um piloto pequeno | não medimos |"
    )


def test_pagina_ficticia_com_roteiro(ler):
    saida = ler("Roteiro da reunião de diagnóstico")

    assert saida.startswith("> 💡 Leia antes da reunião.\n\n1. Apresente-se em um minuto.\n   1. Sem slides.\n")
    assert "- [x] Mandar o resumo em até 2 dias\n- [ ] Marcar a devolutiva\n" in saida
    assert "fale com @pessoa." in saida
    assert "Joana" not in saida
