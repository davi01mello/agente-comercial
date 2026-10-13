"""Gera o workspace.json ao lado: um workspace do Notion 100% FICTÍCIO, no formato real da API (versão 2026-03-11).
Para mudar as fixtures, edite aqui e rode (na raiz do repositório):
    python tests/fixtures/notion/gerar_workspace.py tests/fixtures/notion/workspace.json
"""
import json
import sys
import uuid

NS = uuid.UUID("12345678-1234-5678-1234-567812345678")
T0 = "2026-09-01T12:00:00.000Z"


def uid(nome: str) -> str:
    return str(uuid.uuid5(NS, nome))


def rt(texto, bold=False, italic=False, code=False, strike=False, link=None):
    return {
        "type": "text",
        "text": {"content": texto, "link": {"url": link} if link else None},
        "annotations": {"bold": bold, "italic": italic, "strikethrough": strike, "underline": False, "code": code,
                        "color": "default"},
        "plain_text": texto,
        "href": link,
    }


def mencao_pessoa(nome_exibido):
    return {
        "type": "mention",
        "mention": {"type": "user", "user": {"object": "user", "id": uid("pessoa" + nome_exibido)}},
        "annotations": {"bold": False, "italic": False, "strikethrough": False, "underline": False, "code": False,
                        "color": "default"},
        "plain_text": nome_exibido,
        "href": None,
    }


BLOCOS: dict[str, list] = {}
PAGINAS: dict[str, dict] = {}
_cont = [0]


def bloco(pai: str, tipo: str, conteudo: dict, filhos: list | None = None) -> dict:
    _cont[0] += 1
    bid = uid(f"bloco-{_cont[0]}")
    b = {
        "object": "block", "id": bid, "parent": {"type": "page_id", "page_id": pai}, "type": tipo,
        "created_time": T0, "last_edited_time": T0, "in_trash": False, "has_children": bool(filhos), tipo: conteudo,
    }
    if filhos:
        BLOCOS[bid] = [f(bid) for f in filhos]
    return b


# Construtores "atrasados": recebem o id do pai na hora (para o parent ficar certo).
def P(*rich, filhos=None):
    return lambda pai: bloco(pai, "paragraph", {"rich_text": list(rich), "color": "default"}, filhos)


def H(n, texto):
    return lambda pai: bloco(pai, f"heading_{n}", {"rich_text": [rt(texto)], "color": "default",
                                                   "is_toggleable": False})


def LI(*rich, filhos=None):
    return lambda pai: bloco(pai, "bulleted_list_item", {"rich_text": list(rich), "color": "default"}, filhos)


def NUM(*rich, filhos=None):
    return lambda pai: bloco(pai, "numbered_list_item", {"rich_text": list(rich), "color": "default"}, filhos)


def TODO(texto, feito):
    return lambda pai: bloco(pai, "to_do", {"rich_text": [rt(texto)], "checked": feito, "color": "default"})


def TOGGLE(texto, filhos):
    return lambda pai: bloco(pai, "toggle", {"rich_text": [rt(texto)], "color": "default"}, filhos)


def CALLOUT(texto, emoji):
    return lambda pai: bloco(pai, "callout", {"rich_text": [rt(texto)], "icon": {"type": "emoji", "emoji": emoji},
                                              "color": "default"})


def QUOTE(*rich):
    return lambda pai: bloco(pai, "quote", {"rich_text": list(rich), "color": "default"})


def DIVISOR():
    return lambda pai: bloco(pai, "divider", {})


def LINHA(*celulas):
    return lambda pai: bloco(pai, "table_row", {"cells": [[rt(c)] for c in celulas]})


def TABELA(cabecalho, *linhas):
    largura = len(linhas[0])
    return lambda pai: bloco(pai, "table", {"table_width": largura, "has_column_header": cabecalho,
                                            "has_row_header": False}, [LINHA(*linha) for linha in linhas])


def SUBPAGINA(titulo):
    return lambda pai: bloco(pai, "child_page", {"title": titulo})


def pagina(nome, titulo, conteudo, pai=None, editado=T0, linha_de_banco=False):
    pid = uid(nome)
    if linha_de_banco:
        parent = {"type": "data_source_id", "data_source_id": uid("ds-clientes"), "database_id": uid("db-clientes")}
        props = {
            "Nome": {"id": "title", "type": "title", "title": [rt(titulo)]},
            "Segmento": {"id": "a1b2", "type": "select", "select": {"name": "hotelaria", "color": "blue"}},
        }
    else:
        parent = {"type": "page_id", "page_id": pai} if pai else {"type": "workspace", "workspace": True}
        props = {"title": {"id": "title", "type": "title", "title": [rt(titulo)]}}
    slug = titulo.replace(" ", "-").replace(":", "")
    PAGINAS[pid] = {
        "object": "page", "id": pid, "created_time": T0, "last_edited_time": editado, "in_trash": False,
        "is_locked": False, "url": f"https://www.notion.so/{slug}-{pid.replace('-', '')}", "public_url": None,
        "parent": parent, "properties": props, "icon": None, "cover": None,
    }
    BLOCOS[pid] = [f(pid) for f in conteudo]
    return pid


RAIZ = uid("raiz")

pagina("raiz", "Cérebro: teste fictício", [  # página-índice: só subpáginas (fica "vazia")
    SUBPAGINA("Como qualificar leads de hotelaria"),
    SUBPAGINA("Objeções comuns e respostas"),
], editado="2026-09-01T12:00:00.000Z")

pagina("qualificar", "Como qualificar leads de hotelaria", [
    P(rt("Antes da primeira reunião, confira se o hotel tem "), rt("orçamento aprovado", bold=True),
      rt(" e quem decide. Veja o "), rt("modelo de qualificação", link="https://exemplo.com/modelo"), rt(".")),
    H(2, "Perguntas que funcionam"),
    LI(rt("Quantos quartos o hotel tem?")),
    LI(rt("Quem aprova o orçamento?"), filhos=[
        LI(rt("Se for o dono, a decisão é rápida.")),
        LI(rt("Se for um conselho, conte com duas reuniões a mais.")), ]),
    LI(rt("Qual sistema usam hoje?", italic=True)),
    H(2, "Sinais de alerta"),
    NUM(rt("Não sabe dizer o orçamento.")),
    NUM(rt("Quer proposta antes do diagnóstico.")),
    P(rt("Nas 3 reuniões em que pedimos o orçamento logo no início, a conversa ficou mais objetiva.")),
], pai=RAIZ, editado="2026-09-02T10:15:00.000Z")

pagina("objecoes", "Objeções comuns e respostas", [
    P(rt("Respostas que o time usou nas últimas negociações (exemplo inventado).")),
    TABELA(True,
           ("Objeção", "Resposta", "Funcionou?"),
           ("Está caro", "Mostrar o custo de não fazer | comparar com o prejuízo", "2 de 3 vezes"),
           ("Vamos pensar", "Marcar a próxima conversa na hora", "sim"),
           ("Já temos um fornecedor", "Propor um piloto pequeno", "não medimos")),
], pai=RAIZ, editado="2026-09-03T09:00:00.000Z")

pagina("diagnostico", "Roteiro da reunião de diagnóstico", [
    CALLOUT("Leia antes da reunião.", "💡"),
    NUM(rt("Apresente-se em um minuto."), filhos=[NUM(rt("Sem slides."))]),
    NUM(rt("Pergunte sobre o processo atual.")),
    TODO("Mandar o resumo em até 2 dias", True),
    TODO("Marcar a devolutiva", False),
    TOGGLE("Perguntas extras", [P(rt("Qual é a maior dor da equipe hoje?"))]),
    QUOTE(rt("Quem fala mais na reunião é o cliente."), ),
    P(rt("Dúvidas sobre o roteiro: fale com "), mencao_pessoa("@Joana Fictícia"), rt(".")),
    DIVISOR(),
    P(rt("Revisado pelo comercial em setembro.")),
], editado="2026-09-04T14:30:00.000Z")

pagina("contato", "Contato do hotel parceiro", [
    P(rt("O gerente pediu para mandar a proposta para contato@hotel-ficticio.com.br até sexta.")),
    P(rt("Ele gostou do piloto e quer ampliar para as outras unidades.")),
], editado="2026-09-05T08:00:00.000Z")

pagina("ligar", "Ligar para 81 99876-5432 amanhã", [
    P(rt("Retomar a conversa sobre o piloto do app de check-in, que o hotel achou interessante.")),
], editado="2026-09-05T09:00:00.000Z")

TEXTO_INDICACAO = [
    P(rt("Pedir indicação no fim de um projeto bem avaliado trouxe dois clientes novos no semestre.")),
    P(rt("O melhor momento é a reunião de encerramento, quando o cliente já viu o resultado.")),
]
pagina("indicacao", "Prospecção por indicação", TEXTO_INDICACAO, editado="2026-09-06T10:00:00.000Z")
pagina("indicacao-copia", "Cópia de Prospecção por indicação", TEXTO_INDICACAO, editado="2026-09-06T11:00:00.000Z")

pagina("linha-banco", "Hotel Fictício Sol", [
    P(rt("Aprendizado: o hotel só fechou depois que mostramos o piloto funcionando no celular do gerente.")),
], linha_de_banco=True, editado="2026-09-07T10:00:00.000Z")

pagina("lixeira", "Rascunho antigo de proposta", [
    P(rt("Um modelo de proposta que o time usava em 2025, com escopo, prazo e preço em três blocos separados.")),
], editado="2026-09-08T10:00:00.000Z")

workspace = {
    "_aviso": "Workspace do Notion 100% FICTÍCIO para os testes da T4. Nenhum nome, contato ou número é real.",
    "por_pagina": 3,
    "paginas": PAGINAS,
    "blocos": BLOCOS,
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(workspace, f, ensure_ascii=False, indent=1)
print(len(PAGINAS), "páginas,", sum(len(v) for v in BLOCOS.values()), "blocos")
