"""Login com o Google (T5): só @citi.org.br entra, e toda rota (menos a página e o /health) exige a sessão.

Nenhum teste fala com o Google: `auth.trocar_codigo` e `auth.verificar_token` são trocados por falsas.
"""
import os
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Insight, Usuario

ABERTAS = {"/health", "/", "/auth/login", "/auth/callback", "/auth/logout"}  # /auth/eu responde 401 por conta própria


@pytest.fixture
def login_ligado(monkeypatch):
    """O login de verdade, com um cliente OAuth de mentira."""
    monkeypatch.setattr(settings, "google_client_id", "cliente-teste.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "segredo-teste")
    monkeypatch.setattr(settings, "app_url", "https://cerebro.exemplo.com")


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


def claims(**mudancas) -> dict:
    base = {"email": "ana.silva@citi.org.br", "email_verified": True, "hd": "citi.org.br", "name": "Ana Silva",
            "nonce": "NONCE"}
    return base | mudancas


def fazer_login(client, monkeypatch, **mudancas_dos_claims):
    """Percorre /auth/login e /auth/callback com o Google falso. Devolve a resposta do callback."""
    r = client.get("/auth/login")
    assert r.status_code == 303
    consulta = parse_qs(urlsplit(r.headers["location"]).query)
    visto = {}

    def trocar(codigo, verificador):
        visto["codigo"], visto["verificador"] = codigo, verificador
        return "id-token-falso"

    monkeypatch.setattr(auth, "trocar_codigo", trocar)
    monkeypatch.setattr(auth, "verificar_token",
                        lambda token: claims(nonce=consulta["nonce"][0]) | mudancas_dos_claims)
    resposta = client.get("/auth/callback", params={"code": "CODIGO", "state": consulta["state"][0]})
    resposta.visto = visto
    return resposta


# --- sem login configurado (dev) ----------------------------------------------------------------

def test_dev_sem_login_entra_como_dev_local(client, monkeypatch):
    monkeypatch.undo()  # o autouse trocou o nome do dev para "Rafael"; aqui vale o nome de verdade
    r = client.get("/auth/eu")
    assert r.status_code == 200
    assert r.json() == {"email": "dev@local", "nome": "Dev local", "dev": True, "dominio": "citi.org.br"}
    assert client.get("/insights").status_code == 200  # sem login configurado, o dev usa o app direto


def test_login_desligado_manda_de_volta_para_a_pagina(client):
    r = client.get("/auth/login")
    assert r.status_code == 303 and r.headers["location"] == "/"


# --- com login: tudo exige sessão ---------------------------------------------------------------

def test_toda_rota_exige_login_menos_a_pagina_o_health_e_o_auth(client, login_ligado):
    """Uma rota nova nasce protegida: este teste percorre TODAS as rotas do app."""
    caminhos = app.openapi()["paths"]  # inclui as rotas do router do login
    assert len(caminhos) > 12
    verificadas = 0
    for caminho, metodos in caminhos.items():
        if caminho in ABERTAS:
            continue
        for metodo in metodos:
            r = client.request(metodo.upper(), re.sub(r"\{[^}]+\}", "1", caminho),
                               json={} if metodo != "get" else None)
            assert r.status_code == 401, f"{metodo.upper()} {caminho} respondeu {r.status_code} sem login"
            verificadas += 1
    assert verificadas >= 10


def test_pagina_health_e_estaticos_ficam_abertos(client, login_ligado):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/static/cerebro.js").status_code == 200


def test_eu_sem_sessao_e_401(client, login_ligado):
    r = client.get("/auth/eu")
    assert r.status_code == 401


def test_cookie_forjado_nao_vale(client, login_ligado):
    client.cookies.set(auth.COOKIE, "eyJwZXNzb2EiOiB7ImVtYWlsIjogImFAY2l0aS5vcmcuYnIiLCAibm9tZSI6ICJBIn19.x.y")
    assert client.get("/insights").status_code == 401


# --- o fluxo do Google --------------------------------------------------------------------------

def test_login_manda_ao_google_com_state_nonce_e_pkce(client, login_ligado):
    r = client.get("/auth/login")
    url = urlsplit(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert r.status_code == 303 and f"{url.scheme}://{url.netloc}{url.path}" == auth.URL_AUTORIZACAO
    assert q["client_id"] == "cliente-teste.apps.googleusercontent.com"
    assert q["redirect_uri"] == "https://cerebro.exemplo.com/auth/callback"
    assert q["response_type"] == "code" and q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["hd"] == "citi.org.br"
    assert len(q["state"]) >= 32 and len(q["nonce"]) >= 32


def test_login_completo_cria_a_sessao_e_registra_o_usuario(client, login_ligado, monkeypatch):
    r = fazer_login(client, monkeypatch)

    assert r.status_code == 303 and r.headers["location"] == "/"
    assert r.visto["codigo"] == "CODIGO" and len(r.visto["verificador"]) >= 43  # o PKCE segue para o Google
    eu = client.get("/auth/eu").json()
    assert eu["nome"] == "Ana Silva" and eu["email"] == "ana.silva@citi.org.br" and eu["dev"] is False
    with SessionLocal() as db:
        usuarios = db.scalars(select(Usuario).where(Usuario.email == "ana.silva@citi.org.br")).all()
    assert len(usuarios) == 1 and usuarios[0].nome == "Ana Silva"


def test_entrar_de_novo_nao_duplica_o_usuario(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    fazer_login(client, monkeypatch, name="Ana S. Silva")
    with SessionLocal() as db:
        linhas = db.scalars(select(Usuario).where(Usuario.email == "ana.silva@citi.org.br")).all()
    assert len(linhas) == 1 and linhas[0].nome == "Ana S. Silva"


def test_email_em_maiusculas_do_dominio_entra(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch, email="Ana.Silva@CITI.org.br", hd="CITI.org.br")
    assert client.get("/auth/eu").json()["email"] == "ana.silva@citi.org.br"


def test_o_autor_e_a_pessoa_logada_e_nunca_o_corpo(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    corpo = {"titulo": "Teste de autor da sessão", "tipo": "aprendizado", "secao": "reuniao_diagnostico",
             "descricao": "Abrir com perguntas.", "autor": "Outra Pessoa"}

    r = client.post("/insights", json=corpo)

    assert r.status_code == 201 and r.json()["autor"] == "Ana Silva"
    with SessionLocal() as db:
        assert db.get(Insight, r.json()["id"]).autor == "Ana Silva"
    aprovado = client.post(f"/insights/{r.json()['id']}/aprovar", json={"por_quem": "Outra Pessoa"})
    assert aprovado.status_code == 200
    assert client.get("/insights", params={"status": "validado", "limit": 100}).status_code == 200


@pytest.mark.parametrize("mudancas, destino", [
    ({"email": "fulano@gmail.com", "hd": "gmail.com"}, "dominio"),  # conta pessoal
    ({"email": "fulano@gmail.com"}, "dominio"),  # hd do CITi com e-mail de fora
    ({"email": "fulano@citi.org.br.golpe.com"}, "dominio"),
    ({"email": "fulano@meucitI.org.br"}, "dominio"),  # termina parecido, mas não é o domínio
    ({"hd": "outra.com.br"}, "dominio"),  # e-mail do CITi mas conta de outro Workspace
    ({"email_verified": False}, "dominio"),
    ({"email_verified": "true"}, "dominio"),  # tem que ser o booleano verdadeiro
    ({"nonce": "OUTRO"}, "erro"),  # token de outro pedido
])
def test_conta_que_nao_e_do_citi_nao_entra(client, login_ligado, monkeypatch, mudancas, destino):
    r = fazer_login(client, monkeypatch, **mudancas)
    assert r.status_code == 303
    assert client.get("/auth/eu").status_code == 401, f"{mudancas} entrou"
    assert r.headers["location"] == f"/?login={destino}"


def test_conta_sem_hd_nao_entra(client, login_ligado, monkeypatch):
    """O `hd` só existe em conta do Workspace: sem ele (conta pessoal com e-mail igual), não passa."""
    client.get("/auth/login")
    monkeypatch.setattr(auth, "trocar_codigo", lambda c, v: "t")
    sem_hd = claims()
    sem_hd.pop("hd")
    estado = parse_qs(urlsplit(client.get("/auth/login").headers["location"]).query)
    monkeypatch.setattr(auth, "verificar_token", lambda t: sem_hd | {"nonce": estado["nonce"][0]})
    r = client.get("/auth/callback", params={"code": "x", "state": estado["state"][0]})
    assert r.headers["location"] == "/?login=dominio"
    assert client.get("/auth/eu").status_code == 401


def test_state_errado_ou_sem_login_iniciado_e_recusado(client, login_ligado, monkeypatch):
    chamado = []
    monkeypatch.setattr(auth, "trocar_codigo", lambda c, v: chamado.append(c) or "t")
    # callback sem ter passado por /auth/login
    assert client.get("/auth/callback", params={"code": "x", "state": "y"}).headers["location"] == "/?login=erro"
    # com /auth/login, mas state de outro fluxo
    client.get("/auth/login")
    assert client.get("/auth/callback", params={"code": "x", "state": "errado"}).headers["location"] == "/?login=erro"
    assert chamado == []  # nem chegou a trocar o código


def test_state_so_vale_uma_vez(client, login_ligado, monkeypatch):
    r = fazer_login(client, monkeypatch)
    assert r.status_code == 303
    client.post("/auth/logout")
    estado = parse_qs(urlsplit(client.get("/auth/login").headers["location"]).query)
    client.get("/auth/callback", params={"code": "x", "state": estado["state"][0]})  # gasta o state (falha: sem fake)
    repetido = client.get("/auth/callback", params={"code": "x", "state": estado["state"][0]})
    assert repetido.headers["location"] == "/?login=erro"


def test_pessoa_que_cancela_no_google_volta_com_aviso(client, login_ligado):
    client.get("/auth/login")
    r = client.get("/auth/callback", params={"error": "access_denied"})
    assert r.headers["location"] == "/?login=cancelado"


def test_falha_na_troca_do_codigo_vira_erro_sem_detalhe(client, login_ligado, monkeypatch):
    estado = parse_qs(urlsplit(client.get("/auth/login").headers["location"]).query)

    def recusa(codigo, verificador):
        raise auth.ErroLogin("o Google recusou o código (400)")

    monkeypatch.setattr(auth, "trocar_codigo", recusa)
    r = client.get("/auth/callback", params={"code": "x", "state": estado["state"][0]})
    assert r.headers["location"] == "/?login=erro"
    assert client.get("/auth/eu").status_code == 401


def test_logout_encerra_a_sessao(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    assert client.get("/auth/eu").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/eu").status_code == 401
    assert client.get("/insights").status_code == 401


def test_se_o_dominio_permitido_mudar_quem_entrou_antes_sai(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    monkeypatch.setattr(settings, "auth_dominio", "outro.org.br")
    assert client.get("/insights").status_code == 401


# --- requisição vinda de outro site -------------------------------------------------------------

def test_post_com_origin_de_outro_site_e_recusado(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    corpo = {"mensagem": "oi"}
    r = client.post("/chat", json=corpo, headers={"origin": "https://site-malicioso.com"})
    assert r.status_code == 403


def test_post_com_origin_do_proprio_app_passa_da_checagem(client, login_ligado, monkeypatch):
    fazer_login(client, monkeypatch)
    r = client.post("/chat", json={"mensagem": ""}, headers={"origin": "http://testserver"})
    assert r.status_code == 422  # passou do login e da origem; barrou a mensagem vazia


# --- a configuração de produção -----------------------------------------------------------------

def prod(monkeypatch, **campos):
    valores = {"app_env": "prod", "google_client_id": "id", "google_client_secret": "segredo",
               "session_secret": "s" * 40, "app_url": "https://cerebro.exemplo.com"} | campos
    for k, v in valores.items():
        monkeypatch.setattr(settings, k, v)


def test_prod_configurada_sobe(monkeypatch):
    prod(monkeypatch)
    auth.conferir_configuracao()  # não levanta


@pytest.mark.parametrize("campo", ["google_client_id", "google_client_secret", "session_secret"])
def test_prod_sem_login_completo_nao_sobe(monkeypatch, campo):
    prod(monkeypatch, **{campo: ""})
    with pytest.raises(RuntimeError, match=campo.upper()):
        auth.conferir_configuracao()


def test_prod_com_segredo_curto_ou_http_nao_sobe(monkeypatch):
    prod(monkeypatch, session_secret="curto")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        auth.conferir_configuracao()
    prod(monkeypatch, app_url="http://cerebro.exemplo.com")
    with pytest.raises(RuntimeError, match="https"):
        auth.conferir_configuracao()


def test_o_app_em_prod_sem_login_nem_inicia(monkeypatch):
    prod(monkeypatch, google_client_id="")
    with pytest.raises(RuntimeError), TestClient(app):
        pass


def test_prod_nunca_cai_no_modo_dev_aberto(client, monkeypatch):
    prod(monkeypatch, google_client_id="", google_client_secret="")
    assert client.get("/insights").status_code == 401


def test_em_prod_a_documentacao_automatica_fica_desligada():
    """/docs e /openapi.json não passam pelo login do app: em produção nem existem."""
    saida = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(app.openapi_url, app.docs_url, app.redoc_url)"],
        env={**os.environ, "APP_ENV": "prod"}, capture_output=True, text=True, check=True,
    )
    assert saida.stdout.split()[-3:] == ["None", "None", "None"]


def test_o_router_do_login_esta_montado():
    assert {"/auth/login", "/auth/callback", "/auth/logout", "/auth/eu"} <= set(app.openapi()["paths"])


# --- os dois pontos de contato com o Google (sem internet) --------------------------------------

class RespostaFalsa:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._corpo = status, corpo or {}

    def json(self):
        return self._corpo


def test_trocar_codigo_manda_o_segredo_e_o_pkce_e_devolve_o_id_token(login_ligado, monkeypatch):
    enviado = {}

    def post(url, timeout, data):
        enviado.update(url=url, data=data, timeout=timeout)
        return RespostaFalsa(200, {"id_token": "TOKEN"})

    monkeypatch.setattr(auth.requests, "post", post)

    assert auth.trocar_codigo("COD", "VERIF") == "TOKEN"
    assert enviado["url"] == auth.URL_TOKEN and enviado["timeout"] == auth.TIMEOUT_S
    assert enviado["data"] == {
        "code": "COD", "client_id": "cliente-teste.apps.googleusercontent.com", "client_secret": "segredo-teste",
        "redirect_uri": "https://cerebro.exemplo.com/auth/callback", "grant_type": "authorization_code",
        "code_verifier": "VERIF",
    }


@pytest.mark.parametrize("resposta", [RespostaFalsa(400), RespostaFalsa(200, {})])
def test_trocar_codigo_recusado_ou_sem_token_vira_erro_de_login(login_ligado, monkeypatch, resposta):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: resposta)
    with pytest.raises(auth.ErroLogin):
        auth.trocar_codigo("COD", "VERIF")


def test_trocar_codigo_sem_rede_vira_erro_de_login_sem_vazar_o_segredo(login_ligado, monkeypatch):
    def cai(*a, **k):
        raise auth.requests.ConnectionError("segredo-teste")

    monkeypatch.setattr(auth.requests, "post", cai)
    with pytest.raises(auth.ErroLogin) as erro:
        auth.trocar_codigo("COD", "VERIF")
    assert "segredo-teste" not in str(erro.value)


def test_verificar_token_confere_com_o_cliente_do_app(login_ligado, monkeypatch):
    from google.oauth2 import id_token

    visto = {}

    def verifica(token, requisicao, audiencia):
        visto["audiencia"] = audiencia
        return {"email": "a@citi.org.br"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", verifica)
    assert auth.verificar_token("T") == {"email": "a@citi.org.br"}
    assert visto["audiencia"] == "cliente-teste.apps.googleusercontent.com"


def test_verificar_token_invalido_vira_erro_de_login(login_ligado, monkeypatch):
    from google.oauth2 import id_token

    def verifica(*a):
        raise ValueError("Token expired")

    monkeypatch.setattr(id_token, "verify_oauth2_token", verifica)
    with pytest.raises(auth.ErroLogin):
        auth.verificar_token("T")
