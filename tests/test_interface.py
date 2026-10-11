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
