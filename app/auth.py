"""Login com a conta Google do CITi (T5).

O fluxo é o "código de autorização" do Google, com `state`, `nonce` e PKCE:
1. GET /auth/login manda a pessoa ao Google (já pedindo a conta do domínio do CITi);
2. o Google devolve para GET /auth/callback com um código;
3. o servidor troca o código por um token, CONFERE a assinatura dele e só deixa entrar quem tem e-mail verificado do
   domínio do CITi (o e-mail E o domínio do Google Workspace, `hd`, têm que bater: uma conta @gmail.com não passa);
4. a pessoa fica numa sessão (cookie assinado, HttpOnly). O nome dela é o `autor` dos itens e o `por_quem` do histórico:
   vem daqui, nunca do corpo da requisição.

Sem GOOGLE_CLIENT_ID no .env, o dev roda sem login (entra como "Dev local"). Em produção (APP_ENV=prod) isso não existe:
`conferir_configuracao()` derruba a subida se faltar qualquer peça do login, para o app nunca ir ao ar aberto.

Os dois pontos de contato com o Google (`trocar_codigo` e `verificar_token`) são funções soltas: os testes trocam por
falsas, e nenhum teste fala com a internet.
"""
import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Usuario

logger = logging.getLogger(__name__)

URL_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
TIMEOUT_S = 15
COOKIE = "cerebro_sessao"
ABERTAS = {"/health", "/"}  # o resto (fora /static e /auth/*) exige sessão
METODOS_QUE_ALTERAM = {"POST", "PUT", "PATCH", "DELETE"}

DEV = "dev"
DEV_EMAIL = "dev@local"
DEV_NOME = "Dev local"


@dataclass(frozen=True)
class Pessoa:
    email: str
    nome: str
    dev: bool = False  # True: o login está desligado (só no dev)


class ErroLogin(Exception):
    """O Google recusou, o token não confere ou a conta não é do CITi. A mensagem é só para o log (sem dado)."""

    def __init__(self, mensagem: str, fora_do_citi: bool = False):
        super().__init__(mensagem)
        self.fora_do_citi = fora_do_citi  # a tela explica "use a conta do CITi" só neste caso


# --- configuração ---------------------------------------------------------------------------------------------

def ativo() -> bool:
    """O login está ligado? (cliente OAuth no .env.) Em prod ele é obrigatório: ver conferir_configuracao."""
    return bool(settings.google_client_id and settings.google_client_secret)


def conferir_configuracao() -> None:
    """Chamada na subida. Em prod, sem login completo o app NÃO sobe (melhor cair do que ir ao ar aberto)."""
    em_prod = settings.app_env == "prod"
    if em_prod:
        faltando = [nome for nome, valor in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("SESSION_SECRET", settings.session_secret),
        ) if not valor]
        if faltando:
            raise RuntimeError(f"APP_ENV=prod exige o login do Google. Faltam no ambiente: {', '.join(faltando)}.")
        if len(settings.session_secret) < 32:
            raise RuntimeError("SESSION_SECRET curto demais: use pelo menos 32 caracteres aleatórios.")
        if not settings.app_url.startswith("https://"):
            raise RuntimeError("APP_URL precisa ser https:// em produção (o cookie de sessão só vale em https).")
    if ativo():
        return
    logger.warning("Login do Google DESLIGADO (sem GOOGLE_CLIENT_ID): todos entram como \"%s\". Só vale no dev.",
                   DEV_NOME)


def segredo_da_sessao() -> str:
    """O segredo que assina o cookie. Sem ele (dev), um aleatório por processo: reiniciar o servidor desloga."""
    return settings.session_secret or secrets.token_urlsafe(32)


def _dominio() -> str:
    return settings.auth_dominio.strip().lower().lstrip("@")


def _redirect_uri() -> str:
    return f"{settings.app_url.rstrip('/')}/auth/callback"


# --- quem é a pessoa desta requisição ---------------------------------------------------------------------------

def pessoa_da_sessao(request: Request) -> Pessoa | None:
    """Quem está na sessão (ou None). Confere o domínio de novo a cada requisição: se o domínio permitido mudar, quem
    entrou antes sai."""
    dados = request.session.get("pessoa")
    if not isinstance(dados, dict):
        return None
    email, nome = str(dados.get("email", "")).lower(), str(dados.get("nome", ""))
    if not email.endswith(f"@{_dominio()}") or not nome:
        return None
    return Pessoa(email=email, nome=nome)


def usuario_atual(request: Request) -> Pessoa:
    """A pessoa logada, ou 401. Sem login configurado (só no dev), todos são o "Dev local"."""
    if not ativo():
        if settings.app_env == "prod":  # não acontece (a subida cai antes), mas nunca abre a porta por engano
            raise HTTPException(status_code=401, detail="Login indisponível.")
        return Pessoa(email=DEV_EMAIL, nome=DEV_NOME, dev=True)
    pessoa = pessoa_da_sessao(request)
    if pessoa is None:
        raise HTTPException(status_code=401, detail="Entre com a sua conta Google do CITi.")
    return pessoa


def _mesma_origem(request: Request) -> bool:
    """Contra requisição de outro site: um POST do navegador traz o Origin; se existir, tem que ser o do próprio app."""
    origem = request.headers.get("origin")
    if not origem:
        return True  # curl, scripts e testes não mandam Origin; o cookie de sessão é SameSite=Lax de qualquer jeito
    return urlsplit(origem).netloc == request.headers.get("host", "")


def exigir_login(request: Request) -> None:
    """Dependência do app inteiro: nenhuma rota nova nasce aberta por esquecimento. Ficam de fora a página, o /health,
    os arquivos estáticos (nada secreto) e as próprias rotas /auth."""
    caminho = request.url.path
    if caminho in ABERTAS or caminho.startswith("/auth/") or caminho.startswith("/static/"):
        return
    if request.method in METODOS_QUE_ALTERAM and not _mesma_origem(request):
        raise HTTPException(status_code=403, detail="Origem não permitida.")
    usuario_atual(request)


# --- o Google ---------------------------------------------------------------------------------------------------

def trocar_codigo(codigo: str, verificador: str) -> str:
    """Troca o código de autorização pelo id_token (o servidor autentica com o segredo do cliente)."""
    try:
        resposta = requests.post(URL_TOKEN, timeout=TIMEOUT_S, data={
            "code": codigo,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verificador,
        })
    except requests.RequestException as e:
        raise ErroLogin(f"o Google não respondeu ({type(e).__name__})") from e
    if resposta.status_code != 200:
        raise ErroLogin(f"o Google recusou o código ({resposta.status_code})")
    token = resposta.json().get("id_token")
    if not token:
        raise ErroLogin("o Google não devolveu o id_token")
    return token


def verificar_token(token: str) -> dict:
    """Confere a assinatura, o emissor, a validade e o público (o nosso cliente) do id_token do Google."""
    from google.auth.transport import requests as transporte
    from google.oauth2 import id_token

    try:
        return id_token.verify_oauth2_token(token, transporte.Request(), settings.google_client_id)
    except (ValueError, requests.RequestException) as e:
        raise ErroLogin(f"id_token inválido ({type(e).__name__})") from e


def conferir_conta(claims: dict, nonce: str) -> Pessoa:
    """Só entra quem é do CITi: e-mail verificado do domínio E conta do Workspace do domínio (`hd`)."""
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ErroLogin("nonce não confere")
    email = str(claims.get("email", "")).strip().lower()
    dominio = _dominio()
    if claims.get("email_verified") is not True or not email.endswith(f"@{dominio}"):
        raise ErroLogin("conta fora do domínio", fora_do_citi=True)
    if str(claims.get("hd", "")).lower() != dominio:
        raise ErroLogin("conta fora do Workspace", fora_do_citi=True)
    nome = " ".join(str(claims.get("name") or email.split("@")[0]).split())[:100]
    return Pessoa(email=email, nome=nome)


def _desafio(verificador: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()


# --- rotas ------------------------------------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["login"])
Db = Annotated[Session, Depends(get_db)]
Logada = Annotated[Pessoa, Depends(usuario_atual)]  # "esta rota precisa de uma pessoa logada" (e diz quem é)


@router.get("/login")
def entrar(request: Request):
    """Manda a pessoa ao Google. Sem o login ligado (dev), volta para a página."""
    if not ativo():
        return RedirectResponse("/", status_code=303)
    verificador = secrets.token_urlsafe(64)
    sessao = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verificador": verificador}
    request.session["oauth"] = sessao
    consulta = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": sessao["state"],
        "nonce": sessao["nonce"],
        "code_challenge": _desafio(verificador),
        "code_challenge_method": "S256",
        "hd": _dominio(),  # só um atalho de tela do Google: quem decide se entra é o conferir_conta
        "prompt": "select_account",
    })
    return RedirectResponse(f"{URL_AUTORIZACAO}?{consulta}", status_code=303)


@router.get("/callback", name="auth_callback")
def retorno(request: Request, db: Db, code: str = "", state: str = "", error: str = ""):
    """O Google volta para cá. Qualquer falha devolve à página com ?login=<motivo>, sem detalhe para quem tenta."""
    guardado = request.session.pop("oauth", None)
    if error:
        return RedirectResponse("/?login=cancelado", status_code=303)
    if (not ativo() or not isinstance(guardado, dict) or not code
            or not secrets.compare_digest(str(guardado.get("state", "")), state)):
        return RedirectResponse("/?login=erro", status_code=303)
    try:
        pessoa = conferir_conta(verificar_token(trocar_codigo(code, guardado["verificador"])), guardado["nonce"])
    except ErroLogin as e:
        logger.warning(json.dumps({"evento": "login_recusado", "motivo": str(e)}))
        return RedirectResponse("/?login=dominio" if e.fora_do_citi else "/?login=erro", status_code=303)
    _registrar(db, pessoa)
    request.session.clear()  # sessão nova: nada do fluxo anterior sobra
    request.session["pessoa"] = {"email": pessoa.email, "nome": pessoa.nome}
    logger.info(json.dumps({"evento": "login"}))  # sem e-mail nem nome no log
    return RedirectResponse("/", status_code=303)


def _registrar(db: Session, pessoa: Pessoa) -> None:
    agora = datetime.now(UTC).replace(tzinfo=None)
    usuario = db.scalar(select(Usuario).where(Usuario.email == pessoa.email))
    if usuario is None:
        db.add(Usuario(email=pessoa.email, nome=pessoa.nome, ultimo_acesso=agora))
    else:
        usuario.nome, usuario.ultimo_acesso = pessoa.nome, agora
    db.commit()


@router.post("/logout", status_code=204)
def sair(request: Request):
    request.session.clear()
    return Response(status_code=204)


@router.get("/eu")
def quem_sou_eu(response: Response, pessoa: Logada):
    """Quem está logada (a tela usa para decidir entre o login e o app). 401 se ninguém."""
    response.headers["Cache-Control"] = "no-store"
    return {"email": pessoa.email, "nome": pessoa.nome, "dev": pessoa.dev, "dominio": _dominio()}
