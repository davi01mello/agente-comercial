"""A interface é servida pelo próprio FastAPI: página em app/templates, CSS e JS em app/static."""
import re

from fastapi.testclient import TestClient

from app.main import app


def test_pagina_carrega_cena_e_scripts():
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert 'id="cena"' in r.text
    assert "/static/cerebro.css" in r.text
    assert "/static/cerebro.js" in r.text


def test_arquivos_estaticos():
    with TestClient(app) as client:
        css = client.get("/static/cerebro.css")
        js = client.get("/static/cerebro.js")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_js_nao_usa_innerhtml_com_texto_de_fora():
    """O único innerHTML permitido é o do SVG do orbe, gerado pelo próprio script (proteção contra XSS)."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)  # tira os comentários de bloco
    usos = [linha.strip() for linha in codigo.splitlines() if "innerHTML" in linha]
    assert all("orbe(" in u for u in usos), usos


def test_tela_de_fontes_esta_no_menu_e_na_pagina():
    with TestClient(app) as client:
        pagina = client.get("/").text
        js = client.get("/static/cerebro.js").text
    assert 'data-tela="fontes"' in pagina and 'href="#fontes"' in pagina
    assert '"/fontes/resumo"' in js and "/fontes?${params}" in js


def test_fila_mostra_tambem_o_historico_a_validar():
    """Os itens que a importação do Notion propõe entram como historico_a_validar: a Fila precisa mostrá-los."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert 'i.status === "proposto" || i.status === "historico_a_validar"' in js



def test_fila_pede_todas_as_paginas_de_itens():
    """A API entrega no máximo 100 por chamada: sem paginar, uma importação grande esconderia itens da Fila."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "offset=${offset}" in js
    assert "itensDoStatus" in js


def test_fila_aprova_em_lote_com_confirmacao():
    """Aprovar vários de uma vez passa por um segundo clique e usa o mesmo endpoint de cada item."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "aprovarSelecionados" in js
    assert "sem ler um a um" in js  # a confirmação diz o que está sendo feito
    assert 'chamar("POST", `/insights/${id}/aprovar`' in js


def test_tela_de_fontes_mostra_o_motivo():
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "f.motivo" in js
    assert "motivo-fonte" in js


def test_modo_ao_vivo_nao_mistura_itens_de_exemplo():
    """Ao vivo só existe o que está no banco: nada de EX-0n na busca, no briefing, na saudação ou nos atalhos."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert js.count("aoVivo() ? estado.itens : [...estado.itens, ...EXEMPLOS]") == 2  # acharItem e baseUtil
    assert "ATALHOS_CHAT.filter((_, i) => !aoVivo() || i > 0)" in js  # o atalho do caso fictício de hotelaria
    assert "aoVivo() ? null : el(\"div\", { class: \"exemplos\" }" in js  # relatos de exemplo só na demonstração


def test_playbook_pagina_e_filtra_por_origem():
    """Centenas de itens: o Playbook mostra uma página por etapa do funil e deixa filtrar por origem."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "POR_PAGINA_PLAYBOOK" in js
    assert "Todas as origens" in js
    assert "(!f.origem || i.fonte === f.origem)" in js


def test_listas_nao_encolhem_a_faixa_do_funil():
    """Com muitos cartões o grid encolhia o funil para 30px: as linhas precisam do tamanho do conteúdo."""
    with TestClient(app) as client:
        css = client.get("/static/cerebro.css").text
    assert "grid-auto-rows: max-content" in css


def test_tela_de_fontes_sincroniza_pela_api():
    """O botão chama a API da T4c e acompanha a execução; não manda mais rodar o script no terminal."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
        html = client.get("/").text
    assert 'chamar("POST", "/fontes/sincronizar"' in js
    assert "`/fontes/execucoes/${id}`" in js
    assert "Sincronizar agora" in js and "Só simular" in js
    assert "pelo botão chega na T4c" not in js and "pelo botão chega na T4c" not in html


def test_tela_de_fontes_pagina_e_filtra_no_servidor():
    """São milhares de páginas: filtro, busca e "mostrar mais" vão na query de GET /fontes, não no navegador."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "POR_PAGINA_FONTES" in js
    assert 'params.set("status", filtro.status)' in js
    assert 'params.set("q", filtro.busca.trim())' in js
    assert "/fontes?limit=200" not in js


def test_chat_mostra_os_documentos_do_drive_com_aviso_de_nao_revisado():
    """[DOC-n] vira link para o Drive só se o servidor mandou o documento; o link é https e abre fora da página."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
        css = client.get("/static/cerebro.css").text
    assert r"\[(DOC-\d+)\]" in js
    assert "function chipDocumento(" in js and "linkSeguro(doc.url)" in js
    assert "r.documentos" in js
    assert "ainda não revisados" in js
    assert "a.cita.doc" in css


def test_tela_de_fontes_escolhe_notion_ou_drive_e_mostra_o_so_na_busca():
    """O painel de sincronizar manda a origem escolhida; o status novo e a pasta do Drive aparecem nos cartões."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert '{ origem: sy.origem, dry_run: dry, teto_usd: sy.teto }' in js
    assert 'origem: "notion", dry_run' not in js
    assert "so_busca:" in js and "STATUS_FONTE_DRIVE" in js
    assert "f.categoria" in js
    assert 'params.set("origem", filtro.origem)' in js
    assert "ultima_por_origem" in js
