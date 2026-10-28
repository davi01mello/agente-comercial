"""A interface é servida pelo próprio FastAPI: página em app/templates, CSS e JS em app/static."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
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
    """O único innerHTML permitido é o do SVG do mascote, gerado pelo próprio script (proteção contra XSS)."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)  # tira os comentários de bloco
    usos = [linha.strip() for linha in codigo.splitlines() if "innerHTML" in linha]
    assert all("mascote(" in u for u in usos), usos


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


def test_interface_nao_tem_dado_fictício_nem_modo_demonstracao():
    """Só existe o que está no banco: sem base de exemplo, sem respostas simuladas e sem ?demo."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
        html = client.get("/").text
    restos = ("EXEMPLOS", "RESPOSTAS_DEMO", "respostaDemo", "curarDemo", "NOTA_DEMO", "EX-0", "fictício",
              "Demonstração", "?demo", "Hotel Exemplo")
    for resto in restos:
        assert resto not in js, resto
    assert "Rede com 6 hotéis" not in html and 'data-modo="demo"' not in html


def test_briefing_usa_a_api_e_nao_monta_texto_no_navegador():
    """O briefing vem do POST /briefing (fontes conferidas pelo servidor); a tela não inventa passos nem lacunas."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert 'chamar("POST", "/briefing"' in js
    inventados = ("Abra com diagnóstico, não com a solução", "Piloto em uma unidade",
                  "Nenhum case de rede com mais de 4")
    for inventado in inventados:
        assert inventado not in js


def test_sem_servidor_a_tela_avisa_e_nao_mostra_nada():
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert '"fora"' in js and "Não consegui falar com o servidor" in js


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


def test_tela_tem_a_entrada_do_google_e_nao_pede_mais_o_nome():
    """T5: quem entra é a conta Google do CITi; o campo "Seu nome" saiu e o autor vem da sessão no servidor."""
    with TestClient(app) as client:
        html = client.get("/").text
        js = client.get("/static/cerebro.js").text
    assert 'id="entrada-login"' in html and 'href="/auth/login"' in html and "Entrar com o Google" in html
    assert 'id="autor"' not in html and "$(\"#autor\")" not in js
    assert 'fetch("/auth/eu"' in js and 'fetch("/auth/logout"' in js
    assert "r.status === 401" in js  # a sessão que acaba volta para a entrada
    assert "por_quem" not in js  # o corpo não leva mais o nome de quem aprova...
    assert "{ ...dados, autor" not in js.split("criado = await chamar")[1][:60]  # ...nem o de quem registra


def test_css_tem_os_tokens_do_observatorio():
    """O tema escolhido em 28/10 (Observatório): os tokens do Design System e as fontes Sora, Inter e JetBrains Mono."""
    with TestClient(app) as client:
        css = client.get("/static/cerebro.css").text
        html = client.get("/").text
    assert "--fundo: #080a11;" in css and "--marca: #a9a6dd;" in css and "--ev-4: #e6e5f4;" in css
    assert "family=Sora" in html and "family=Inter" in html and "family=JetBrains+Mono" in html
    assert "Bricolage" not in html


def test_fundo_nao_derruba_o_inicio():
    """A tela em branco de 27/10: o fundo em canvas quebrava com a janela em 0 px e levava o iniciar() junto.
    O chão agora é só CSS, e o que é enfeite roda dentro de seguro()."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert "drawImage" not in js
    assert "function seguro(" in js
    inicio = js.split("async function iniciar()")[1]
    assert "seguro(" in inicio.split("detectarModo()")[0]


JS = Path(__file__).resolve().parents[1] / "app" / "static" / "cerebro.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="sem o Node para conferir a sintaxe")
def test_js_tem_sintaxe_valida():
    """Os outros testes da tela conferem texto: um erro de sintaxe passaria por eles e deixaria a página parada."""
    r = subprocess.run(["node", "--check", str(JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_casca_tem_barra_centro_e_painel():
    """O espaço único: a barra com a árvore da base, o centro com abas e o painel do Cérebro fixo à direita."""
    with TestClient(app) as client:
        html = client.get("/").text
        js = client.get("/static/cerebro.js").text
    for id_ in ('id="barra"', 'id="arvore"', 'id="centro"', 'id="abas"', 'id="painel-cerebro"', 'id="form-chat"'):
        assert id_ in html, id_
    assert 'id="gaveta"' not in html  # o item abre numa aba do centro
    assert 'data-tela="fontes"' in html and 'href="#fontes"' in html
    # um link com "%" quebrado não derruba a navegação: o decodeURIComponent fica dentro de um try
    assert "decodeURIComponent" in js and "catch {" in js.split("decodeURIComponent")[1][:200]


def test_abas_lembradas_sem_depender_do_localstorage():
    """As abas abertas ficam no localStorage, que pode falhar (aba anônima, armazenamento cheio): a tela segue sem."""
    with TestClient(app) as client:
        js = client.get("/static/cerebro.js").text
    assert 'guardar.ler("cerebro.abas")' in js and 'guardar.escrever("cerebro.abas"' in js
    assert "ler(chave) { try { return localStorage.getItem(chave); } catch { return null; } }" in js
    assert 'location.hash = `#item/${codigo}`' in js  # o link do item funciona sozinho


def test_celular_tem_a_navegacao_do_mascote_e_alvos_de_toque():
    """No celular, o chat é a tela inicial e o botão do mascote abre a navegação; os alvos têm 44px e os campos
    16px (o iOS não dá zoom). De 861 a 1279 px, o Cérebro vira gaveta."""
    with TestClient(app) as client:
        html = client.get("/").text
        css = client.get("/static/cerebro.css").text
        js = client.get("/static/cerebro.js").text
    assert 'id="nav-mascote"' in html and 'id="nav-celular"' in html and 'id="abrir-cerebro"' in html
    celular = "".join(css.split("@media (max-width: 860px) {")[1:])  # todos os blocos do celular
    assert "min-height: var(--alvo-toque)" in celular and "font-size: 16px" in celular
    assert "@media (max-width: 1279px)" in css
    assert 'matchMedia("(max-width: 860px)")' in js
