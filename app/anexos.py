"""Anexo no chat vira fonte (T7): a pessoa anexa um documento e ele entra no mesmo pipeline do Notion e do Drive.

O arquivo NUNCA é guardado: só o texto extraído (tabela `fontes`, origem "upload") e os pedaços de busca. O texto tem
as duas destinações de sempre: a busca (o consultor cita como [DOC-n], "ainda não revisado") e o curador (itens
`historico_a_validar` na Fila, que só viram [INS-n] depois de aprovados).

Diferença do Drive: o anexo é escrito/colado por UMA pessoa agora e pode ter dado de cliente de última hora, então vale
a regra do chat e do Notion: dado pessoal NUNCA vai ao modelo (a fonte fica `pulada_dado_pessoal`, sem texto
guardado). O Drive não barra por decisão do Davi (documento do time, privado); se ele quiser o mesmo para anexos, é
trocar `barra_dado_pessoal` em UPLOAD (ADR-008).

A leitura é feita aqui e o curador roda depois, em segundo plano (`curar`), uma fonte por vez. Nunca loga nome de
arquivo nem texto.
"""
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dominio, extrair_texto, importacao, importacao_drive, markdown_notion, trechos
from app.db import SessionLocal
from app.importacao import MIN_CARACTERES, Origem, PaginaLida, Relatorio
from app.models import Fonte

logger = logging.getLogger(__name__)

UPLOAD = Origem("upload", "anexo no chat", "de um anexo", barra_dado_pessoal=True)
MAX_BYTES = 10 * 1024 * 1024
MAX_DESCOMPACTADO = 100 * 1024 * 1024  # docx e xlsx são zips: um "zip bomb" pequeno no arquivo vira GBs na memória
MAX_TRECHOS_NO_CURADOR = 5  # ~40 mil caracteres; acima disso o anexo fica só na busca (como o Drive, em escala menor)
EXTENSOES = {
    ".docx": extrair_texto.MIME_DOCX,
    ".pdf": extrair_texto.MIME_PDF,
    ".xlsx": extrair_texto.MIME_XLSX,
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
_ZIPADOS = {".docx", ".xlsx"}


class ErroDoAnexo(Exception):
    """O arquivo não serve (formato, tamanho, ilegível). A mensagem é para a pessoa e nunca traz texto do arquivo."""

    def __init__(self, mensagem: str, status_http: int = 422):
        super().__init__(mensagem)
        self.status_http = status_http


@dataclass
class Recebido:
    fonte: Fonte
    ja_existia: bool  # o mesmo texto já tinha sido anexado: nada novo foi gravado
    curar: bool  # o curador deve rodar nesta fonte (em segundo plano)


def extensao(nome: str) -> str:
    return Path(nome).suffix.lower()


def receber(db: Session, nome: str, conteudo: bytes, pessoa: str) -> Recebido:
    """Lê o arquivo, tria e grava a fonte (com os pedaços de busca). Levanta ErroDoAnexo se não servir."""
    ext = extensao(nome)
    if ext not in EXTENSOES:
        raise ErroDoAnexo(f"Formato não suportado. Anexe {', '.join(sorted(EXTENSOES))}.")
    if not conteudo:
        raise ErroDoAnexo("O arquivo está vazio.")
    if len(conteudo) > MAX_BYTES:
        raise ErroDoAnexo(f"O arquivo passa de {MAX_BYTES // (1024 * 1024)} MB.", status_http=413)

    texto = _ler(conteudo, ext)
    hash_texto = markdown_notion.hash_conteudo(texto)
    existente = db.scalar(select(Fonte).where(Fonte.origem == UPLOAD.nome, Fonte.id_externo == hash_texto))
    if existente is not None and existente.status != "removida":
        return Recebido(existente, ja_existia=True, curar=False)

    titulo = importacao._titulo_seguro(Path(nome).stem.strip() or importacao.SEM_TITULO)
    status, motivo, partes = _triar(titulo, texto, ext)
    com_busca = status in ("a_curar", "so_busca")
    agora = importacao._agora()

    fonte = existente or Fonte(origem=UPLOAD.nome, id_externo=hash_texto)  # "removida" volta a valer
    fonte.titulo, fonte.categoria = titulo, f"Anexo de {pessoa}"[:300]
    fonte.url = "pendente"  # depois do flush vira o endereço do texto, que usa o id
    fonte.markdown = texto if com_busca else None  # com dado pessoal ou vazio, o texto não é guardado
    fonte.hash_conteudo, fonte.editado_em, fonte.importado_em = hash_texto, agora, agora
    fonte.status, fonte.motivo = status, importacao.motivo_da_coluna(motivo)
    if existente is None:
        db.add(fonte)
    db.flush()
    fonte.url = f"/fontes/{fonte.id}/texto"
    importacao_drive._gravar_trechos_de_busca(db, fonte, texto if com_busca else "")
    db.commit()
    return Recebido(fonte, ja_existia=False, curar=status == "a_curar" and bool(partes))


def _ler(conteudo: bytes, ext: str) -> str:
    """O texto do arquivo, num arquivo temporário que some em seguida."""
    if ext in _ZIPADOS:
        _conferir_zip(conteudo)
    with tempfile.TemporaryDirectory(prefix="cerebro_anexo_") as pasta:
        destino = Path(pasta) / f"anexo{ext}"
        destino.write_bytes(conteudo)
        try:
            return extrair_texto.extrair(destino, EXTENSOES[ext])
        except extrair_texto.ErroDeLeitura as e:
            raise ErroDoAnexo(f"Não consegui ler o arquivo ({e}). Ele abre normalmente no computador?") from e


def _conferir_zip(conteudo: bytes) -> None:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPACTADO:
                raise ErroDoAnexo("O arquivo é grande demais depois de aberto.")
    except zipfile.BadZipFile as e:
        raise ErroDoAnexo("Não consegui ler o arquivo (não parece um .docx ou .xlsx de verdade).") from e


def _triar(titulo: str, texto: str, ext: str) -> tuple[str, str, list[trechos.Trecho]]:
    """(status, motivo, trechos). O dado pessoal é checado ANTES de qualquer outra coisa (decide o que é guardado)."""
    if markdown_notion.caracteres_de_texto(texto) < MIN_CARACTERES:
        sem_texto = ext == ".pdf"
        return "vazia", ("sem texto: o PDF parece ser só imagem (não faço OCR)" if sem_texto
                         else f"menos de {MIN_CARACTERES} caracteres de texto"), []
    if UPLOAD.barra_dado_pessoal:
        tipos = dominio.tipos_de_dados_pessoais(f"{titulo}\n{texto}")
        if tipos:
            return "pulada_dado_pessoal", f"contém {', '.join(tipos)}: troque por algo genérico e anexe de novo", []
    if ext in (".xlsx", ".csv"):
        return "so_busca", "planilha: o consultor acha na busca, mas ela não vai ao curador", []
    partes = trechos.dividir(titulo, texto, rotulo="Anexo do chat")
    if len(partes) > MAX_TRECHOS_NO_CURADOR:
        return "so_busca", (f"{len(partes)} trechos (limite {MAX_TRECHOS_NO_CURADOR}): o consultor acha na busca, "
                            "mas ele não vai ao curador"), []
    return "a_curar", "", partes


def curar(fonte_id: int) -> None:
    """O curador numa fonte de anexo (roda em segundo plano, com sessão própria). `a_curar` e `falha` são tentadas;
    qualquer outro estado não é tocado. Nunca levanta: o resultado fica no status da fonte (importada | falha)."""
    try:
        with SessionLocal() as db:
            fonte = db.get(Fonte, fonte_id)
            if fonte is None or fonte.origem != UPLOAD.nome or fonte.status not in importacao.A_CURAR:
                return
            if not fonte.markdown:
                return
            partes = trechos.dividir(fonte.titulo, fonte.markdown, rotulo="Anexo do chat")
            pagina = PaginaLida(fonte.id_externo, fonte.titulo, "nova", "a_curar", trechos=partes)
            relatorio = Relatorio(dry_run=False)
            try:
                importacao._curar_pagina(db, pagina, relatorio, UPLOAD)
            except Exception as e:  # o curador já trata os esperados; o resto não pode deixar a fonte "a_curar"
                logger.error("Curador do anexo %s falhou (%s)", fonte_id, type(e).__name__)
                db.rollback()
                importacao._falhou(db, fonte, pagina, relatorio, "erro inesperado ao curar o anexo; tenta de novo")
    except Exception as e:  # nem a sessão pode derrubar a tarefa de fundo
        logger.error("Anexo %s: erro fora do curador (%s)", fonte_id, type(e).__name__)
