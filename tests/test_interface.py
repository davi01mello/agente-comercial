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
    assert '"/fontes/resumo"' in js and '"/fontes?limit=200"' in js


def test_fila_mostra_tambem_o_historico_a_validar():
    """Os itens que a importação do Notion propõe entram como historico_a_validar: a Fila precisa mostrá-los."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert 'i.status === "proposto" || i.status === "historico_a_validar"' in js

