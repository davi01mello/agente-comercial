"""Leitor do Google Drive (T6): lista os arquivos de uma pasta (com as subpastas) e baixa o conteúdo.

Entra como CONTA DE SERVIÇO, só com o escopo drive.readonly: a pasta precisa estar compartilhada com o e-mail dela (de
preferência num drive compartilhado do CITi, para não depender de uma pessoa). A credencial vem de UMA destas:
- GOOGLE_APPLICATION_CREDENTIALS: o caminho do JSON, no computador;
- GOOGLE_SERVICE_ACCOUNT_JSON: o CONTEÚDO do JSON, para onde não há arquivo (Railway).

É a porta que a importação (app/importacao_drive.py) usa: nunca guarda nem loga nome de arquivo ou texto. As requisições
são HTTP simples (google-auth + requests): sem o cliente gigante do Google. Os testes passam uma `sessao` falsa.
"""
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

ESCOPO = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3/files"
MIME_PASTA = "application/vnd.google-apps.folder"
MIME_ATALHO = "application/vnd.google-apps.shortcut"
# Os documentos nativos do Google não têm bytes: saem exportados (o mime de saída é o texto puro ou o CSV).
EXPORTACAO = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}
CAMPOS = "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size,webViewLink)"
TIMEOUT_S = 60
TENTATIVAS = 4
PAUSA_BASE_S = 1.0
STATUS_DE_NOVA_TENTATIVA = {429, 500, 502, 503, 504}
BLOCO = 1024 * 1024  # o download vai para o disco em blocos de 1 MB: um PDF de 50 MB não pode ocupar a memória
MAX_PASTAS = 500  # trava contra laço (atalhos, pasta dentro dela mesma): um acervo de verdade tem bem menos


class ErroDrive(Exception):
    """Falha ao falar com o Drive. A mensagem já vem pronta para quem rodou: sem texto de arquivo."""

    def __init__(self, mensagem: str, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


def ids_das_pastas(texto: str) -> list[str]:
    """Os ids de pasta de um valor do .env: um ou vários, separados por vírgula, ponto e vírgula, espaço ou quebra de
    linha. Cada um pode ser o id puro ou o endereço inteiro da pasta (".../folders/<id>?usp=sharing"). Sem repetir."""
    ids: list[str] = []
    for pedaco in re.split(r"[,;\s]+", texto.strip()):
        pedaco = pedaco.split("/folders/")[-1].split("?")[0].strip("/") if pedaco else ""
        if pedaco and pedaco not in ids:
            ids.append(pedaco)
    return ids


def _dormir(segundos: float) -> None:
    """Os testes trocam por uma função que não espera."""
    time.sleep(segundos)


@dataclass(frozen=True)
class ArquivoDrive:
    id: str
    nome: str
    mime: str
    modificado_em: datetime  # UTC sem fuso, como o banco guarda
    tamanho: int | None  # bytes; None nos documentos nativos do Google
    caminho: tuple[str, ...]  # as subpastas, a partir da raiz (sem o nome da raiz): ("Resumo Comercial",)
    md5: str | None = None

    @property
    def url(self) -> str:
        return f"https://drive.google.com/file/d/{self.id}/view"

    @property
    def categoria(self) -> str | None:
        return " / ".join(self.caminho) or None


@dataclass
class BuscaDrive:
    arquivos: list[ArquivoDrive] = field(default_factory=list)
    completa: bool = True  # False: a lista foi cortada (limite) ou uma subpasta não pôde ser lida


def _data(texto: str) -> datetime:
    """O modifiedTime do Drive ("2026-10-13T07:59:22.000Z") em UTC sem fuso."""
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


def _sessao_autorizada(credenciais_json: str, caminho_credenciais: str):
    """A sessão HTTP já autenticada com a conta de serviço. Os imports ficam aqui dentro: quem não usa o Drive (e os
    testes, que passam uma sessão falsa) não carrega o google-auth."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    try:
        if credenciais_json:
            credenciais = service_account.Credentials.from_service_account_info(json.loads(credenciais_json),
                                                                                 scopes=[ESCOPO])
        else:
            credenciais = service_account.Credentials.from_service_account_file(caminho_credenciais, scopes=[ESCOPO])
    except (OSError, ValueError, KeyError) as e:  # a mensagem do erro pode ter pedaço da chave: só o tipo vai adiante
        raise ErroDrive(f"Não consegui ler a credencial do Google ({type(e).__name__}). Confira se o arquivo é o "
                        "JSON da conta de serviço, inteiro.") from e
    return AuthorizedSession(credenciais)


class LeitorDrive:
    """Uma instância por execução (conta as requisições). Sem argumentos, lê as variáveis do .env."""

    def __init__(self, pasta_id: str | None = None, *, credenciais_json: str | None = None,
                 caminho_credenciais: str | None = None, sessao=None):
        self.pastas = ids_das_pastas(pasta_id if pasta_id is not None else settings.drive_pasta_id)
        if not self.pastas:
            raise ErroDrive("Falta DRIVE_PASTA_ID no .env: é o id da pasta \"Conhecimento Comercial\" (o final do "
                            "endereço dela no Drive). Para várias pastas, separe os ids por vírgula.")
        self.pasta_id = self.pastas[0]  # a principal: as outras entram com o nome delas no começo da categoria
        if sessao is None:
            json_da_chave = (credenciais_json if credenciais_json is not None
                             else settings.google_service_account_json).strip()
            caminho = (caminho_credenciais if caminho_credenciais is not None
                       else settings.google_application_credentials).strip()
            if not json_da_chave and not caminho:
                raise ErroDrive("Falta a credencial do Google no .env: GOOGLE_APPLICATION_CREDENTIALS (o caminho do "
                                "JSON da conta de serviço) ou GOOGLE_SERVICE_ACCOUNT_JSON (o conteúdo dele).")
            sessao = _sessao_autorizada(json_da_chave, caminho)
        self._sessao = sessao
        self.requisicoes = 0

    # --- HTTP ---------------------------------------------------------------------------------------------

    def _get(self, url: str, params: dict, *, stream: bool = False):
        """GET com novas tentativas (429 e 5xx, com espera crescente). Devolve a resposta; 4xx vira ErroDrive."""
        for tentativa in range(1, TENTATIVAS + 1):
            self.requisicoes += 1
            try:
                resposta = self._sessao.get(url, params=params, stream=stream, timeout=TIMEOUT_S)
            except OSError as e:  # rede caiu, DNS, timeout: o tipo basta
                if tentativa == TENTATIVAS:
                    raise ErroDrive(f"Não consegui falar com o Drive ({type(e).__name__}).") from e
                _dormir(PAUSA_BASE_S * 2 ** (tentativa - 1))
                continue
            if resposta.status_code in STATUS_DE_NOVA_TENTATIVA and tentativa < TENTATIVAS:
                _dormir(PAUSA_BASE_S * 2 ** (tentativa - 1))
                continue
            if resposta.status_code >= 400:
                raise ErroDrive(_explicar(resposta.status_code), resposta.status_code)
            return resposta
        raise AssertionError("inalcançável")  # o laço sempre devolve ou levanta

    # --- listar -------------------------------------------------------------------------------------------

    def _filhos(self, pasta_id: str) -> Iterator[dict]:
        pagina = None
        while True:
            params = {
                "q": f"'{pasta_id}' in parents and trashed = false",
                "fields": CAMPOS,
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "orderBy": "modifiedTime",
            }
            if pagina:
                params["pageToken"] = pagina
            dados = self._get(API, params).json()
            yield from dados.get("files", [])
            pagina = dados.get("nextPageToken")
            if not pagina:
                return

    def _nome_da_pasta(self, pasta_id: str) -> str:
        dados = self._get(f"{API}/{pasta_id}", {"fields": "name", "supportsAllDrives": "true"}).json()
        return str(dados.get("name") or pasta_id)

    def arquivos(self, limite: int | None = None) -> BuscaDrive:
        """Todos os arquivos das pastas e das subpastas (atalhos e a lixeira ficam de fora), do mais antigo ao mais novo
        por pasta. Com `limite`, só os N primeiros (e a busca sai `completa=False`: não dá para saber o que sumiu).

        A primeira pasta é a principal: se ela falhar, a execução toda falha. Uma das outras que não puder ser lida
        (ex.: ainda não foi compartilhada com a conta de serviço) só deixa a busca incompleta. As categorias das
        outras pastas começam pelo nome delas ("Conhecimento / Consultoria"); as da principal não mudam."""
        busca = BuscaDrive()
        fila: list[tuple[str, tuple[str, ...]]] = []
        for i, raiz in enumerate(self.pastas):
            if i == 0:
                fila.append((raiz, ()))
                continue
            try:
                fila.append((raiz, (self._nome_da_pasta(raiz),)))
            except ErroDrive as e:
                logger.warning("pasta extra do Drive não pôde ser lida (status %s)", e.status)
                busca.completa = False
        vistas = {raiz for raiz, _ in fila}
        arquivos_vistos: set[str] = set()
        while fila:
            pasta_id, caminho = fila.pop(0)
            try:
                filhos = list(self._filhos(pasta_id))
            except ErroDrive as e:
                if pasta_id == self.pasta_id:
                    raise  # a pasta principal é o que importa: sem ela, a execução toda falha com o motivo certo
                logger.warning("subpasta do Drive não pôde ser lida (status %s)", e.status)
                busca.completa = False
                continue
            for f in filhos:
                if f["mimeType"] == MIME_PASTA:
                    if f["id"] not in vistas and len(vistas) < MAX_PASTAS:
                        vistas.add(f["id"])
                        fila.append((f["id"], (*caminho, f["name"])))
                    continue
                if f["mimeType"] == MIME_ATALHO or f["id"] in arquivos_vistos:
                    continue  # o mesmo arquivo alcançado por duas pastas entra uma vez só
                if limite is not None and len(busca.arquivos) >= limite:
                    busca.completa = False
                    return busca
                arquivos_vistos.add(f["id"])
                busca.arquivos.append(ArquivoDrive(
                    id=f["id"], nome=f["name"], mime=f["mimeType"], modificado_em=_data(f["modifiedTime"]),
                    tamanho=int(f["size"]) if f.get("size") else None, caminho=caminho, md5=f.get("md5Checksum"),
                ))
        return busca

    # --- baixar -------------------------------------------------------------------------------------------

    def baixar(self, arquivo: ArquivoDrive, destino: Path) -> None:
        """Grava o conteúdo em `destino`, em blocos (arquivo comum) ou exportado (documento nativo do Google)."""
        mime_de_saida = EXPORTACAO.get(arquivo.mime)
        if mime_de_saida:
            resposta = self._get(f"{API}/{arquivo.id}/export", {"mimeType": mime_de_saida}, stream=True)
        else:
            resposta = self._get(f"{API}/{arquivo.id}", {"alt": "media", "supportsAllDrives": "true"}, stream=True)
        try:
            with destino.open("wb") as saida:
                for bloco in resposta.iter_content(chunk_size=BLOCO):
                    saida.write(bloco)
        finally:
            resposta.close()


def _explicar(status: int) -> str:
    if status in (401, 403):
        return (f"O Drive recusou o acesso ({status}). Confira se a pasta foi compartilhada com o e-mail da conta de "
                "serviço e se a API do Google Drive está ativada no projeto.")
    if status == 404:
        return "O Drive não achou a pasta ou o arquivo (404). Confira o DRIVE_PASTA_ID e o compartilhamento."
    return f"O Drive devolveu um erro ({status})."
