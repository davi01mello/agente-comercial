"""Importação do Drive (T6): arquivos da pasta "Conhecimento Comercial" → tabela `fontes` → curador e busca.

É o mesmo pipeline do Notion (app/importacao.py: execução registrada, progresso por arquivo, teto de gasto, curador,
Fila). O que muda aqui é a LEITURA e a TRIAGEM:

- vídeo não entra na lista, e com DRIVE_IDADE_MAX_ANOS o arquivo sem edição há mais que N anos também não (a base
  prefere o recente: o que é velho demais sai e o que sobrou leva a data de edição até o consultor);
- lê a lista de arquivos (com as subpastas) e, só dos novos ou editados (`modifiedTime`), baixa e extrai o texto;
  arquivo acima de DRIVE_MAX_MB nem é baixado (fica `pulada_longa`, com o motivo);
- dado pessoal NÃO barra nem mascara (decisão do Davi: o documento é privado e não sai do agente); fica só um aviso
  no motivo da fonte ("contém e-mail, telefone");
- o documento tem DUAS destinações: o curador (itens `historico_a_validar` na Fila, com [INS-n] só depois de
  aprovados) e a busca (pedaços em `trechos_documento`, que o consultor cita como [DOC-n] com o aviso "ainda não
  revisado"). Planilha e documento longo demais vão só para a busca (`so_busca`);
- o que saiu da pasta (apagado, movido, sem acesso) vira `removida`, só quando a lista veio completa; os pedaços de
  busca dele somem, e os itens pendentes viram obsoletos (os aprovados não mudam, como no Notion).

Nunca loga nome de arquivo nem texto: o log tem só contagens.
"""
import hashlib
import logging
import tempfile
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import dominio, extrair_texto, importacao, markdown_notion, trechos
from app.config import settings
from app.drive import ArquivoDrive, ErroDrive, LeitorDrive
from app.importacao import DRIVE, MIN_CARACTERES, TITULO_MAX, PaginaLida, Relatorio
from app.models import ExecucaoImportacao, Fonte, TrechoDocumento

logger = logging.getLogger(__name__)

ORIGEM = DRIVE.nome
TAMANHO_DO_TRECHO_DE_BUSCA = 1500  # caracteres de cada pedaço que o consultor recebe
COM_BUSCA = {"a_curar", "importada", "falha", "so_busca"}  # as fontes que têm pedaços de busca
EXTENSOES = (".docx", ".pdf", ".xlsx", ".csv", ".txt", ".md")


def conferir_configuracao(dry_run: bool) -> None:
    importacao.conferir_configuracao(dry_run)  # a chave do Gemini: a mesma regra do Notion


def executar(leitor: LeitorDrive, **opcoes) -> Relatorio:
    """A importação do Drive com a própria sessão do banco (o script, a API e o agendador chamam esta)."""
    return importacao.executar(leitor, origem=DRIVE, sincronizar=sincronizar, **opcoes)


def nova_execucao(db: Session, **opcoes) -> ExecucaoImportacao:
    return importacao.nova_execucao(db, origem=DRIVE, **opcoes)


def configurado() -> bool:
    """Há pasta e credencial no .env? É o que liga o agendador."""
    return bool(settings.drive_pasta_id.strip()
                and (settings.google_service_account_json.strip() or settings.google_application_credentials.strip()))


# --- a sincronização --------------------------------------------------------------------------------------------

def sincronizar(
    leitor: LeitorDrive, db: Session, relatorio: Relatorio, limite_paginas: int | None, execucao: ExecucaoImportacao
) -> None:
    busca = leitor.arquivos(limite=limite_paginas)
    videos = getattr(busca, "videos_ignorados", 0)
    antigos = getattr(busca, "antigos_ignorados", 0)
    if videos or antigos:
        logger.info("Drive: %d vídeo(s) e %d arquivo(s) antigo(s) ficaram de fora da lista", videos, antigos)
    if antigos:
        relatorio.avisos.append(
            f"{antigos} arquivo(s) sem edição há mais de {settings.drive_idade_max_anos} ano(s) ficaram de fora "
            "(DRIVE_IDADE_MAX_ANOS). Se algum já tinha sido importado, ele sai da base como removido."
        )
    vistas: set[str] = set()
    hashes: dict[str, str] = {}  # hash -> título dos arquivos tratados nesta execução (duplicatas no dry-run)
    for arquivo in busca.arquivos:
        vistas.add(arquivo.id)
        relatorio.lidas += 1
        _sincronizar_arquivo(leitor, db, arquivo, relatorio, hashes)
        importacao._gravar_progresso(db, execucao, relatorio)

    if busca.completa:
        _conferir_removidas(db, vistas, relatorio)
    else:
        relatorio.avisos.append(
            "A lista de arquivos veio incompleta (--limite-arquivos, ou uma subpasta não pôde ser lida): o que sumiu "
            "do Drive não foi conferido nesta execução."
        )
    importacao._listar_pendentes(db, vistas, relatorio, DRIVE)


def _titulo(arquivo: ArquivoDrive) -> str:
    nome = arquivo.nome
    if nome.lower().endswith(EXTENSOES):
        nome = nome.rsplit(".", 1)[0]
    nome = nome.strip() or importacao.SEM_TITULO
    return nome if len(nome) <= TITULO_MAX else nome[: TITULO_MAX - 1] + "…"


def _hash_sem_leitura(arquivo: ArquivoDrive) -> str:
    """Quando o arquivo não foi lido (grande demais, formato novo): um hash que identifica ESTA versão dele e que
    nunca bate com o de um texto."""
    return hashlib.sha256(f"sem-leitura:{arquivo.id}:{arquivo.md5 or arquivo.tamanho}".encode()).hexdigest()


def _sincronizar_arquivo(
    leitor: LeitorDrive, db: Session, arquivo: ArquivoDrive, relatorio: Relatorio, hashes: dict[str, str]
) -> None:
    titulo = _titulo(arquivo)
    fonte = db.scalar(select(Fonte).where(Fonte.origem == ORIGEM, Fonte.id_externo == arquivo.id))
    existe = fonte is not None and fonte.status != "removida"  # o que voltou para a pasta é tratado como alterado

    # Sem mudança: nem baixa. A exceção é o arquivo que foi pulado só pelo tamanho: o limite pode ter subido no .env,
    # e reavaliar não custa nada (o tamanho vem na lista, sem baixar).
    if existe and fonte.editado_em == arquivo.modificado_em and fonte.status != "pulada_longa":
        relatorio.paginas.append(importacao._sem_mudanca(fonte))
        return

    texto, status, motivo, hash_novo = _ler(leitor, arquivo, titulo, relatorio)
    if status == "falha":  # não deu para ler agora: a fonte fica como estava e a próxima execução tenta de novo
        return

    # Tocado sem mudar o conteúdo (o hash do texto é o mesmo): não passa pela triagem de novo, ou o que já foi ao
    # curador voltaria a esperar por ele. Um arquivo que continua não lido (grande, formato novo) tem o mesmo status.
    if existe and fonte.hash_conteudo == hash_novo and status in ("triar", fonte.status):
        if not relatorio.dry_run:
            fonte.editado_em, fonte.titulo, fonte.categoria = arquivo.modificado_em, titulo, arquivo.categoria
            db.commit()
        relatorio.paginas.append(importacao._sem_mudanca(fonte))
        return

    partes: list[trechos.Trecho] = []
    if status == "triar":
        status, motivo, partes = _triar(db, arquivo, titulo, texto, hash_novo, hashes)
    if status not in ("vazia", "pulada_longa"):
        hashes.setdefault(hash_novo, titulo)
    if status in COM_BUSCA:  # o aviso de dado pessoal: o texto fica como está, só o motivo diz
        tipos = dominio.tipos_de_dados_pessoais(texto)
        if tipos:
            aviso = f"contém {', '.join(tipos)} (mantido, por decisão do time)"
            motivo = f"{motivo}; {aviso}" if motivo else aviso

    relatorio.paginas.append(PaginaLida(arquivo.id, titulo, "alterada" if fonte else "nova", status, motivo, partes))
    if relatorio.dry_run:
        return

    if fonte is None:
        fonte = Fonte(origem=ORIGEM, id_externo=arquivo.id)
        db.add(fonte)
    else:  # o conteúdo mudou: o que o antigo gerou e ninguém revisou sai da Fila
        importacao._obsoletar_pendentes(db, fonte.url, f"o arquivo do Drive mudou (execução #{relatorio.execucao_id})",
                                        relatorio, DRIVE)
    fonte.titulo = titulo
    fonte.url = arquivo.url
    fonte.categoria = arquivo.categoria
    fonte.markdown = texto if status in COM_BUSCA else None
    fonte.hash_conteudo = hash_novo
    fonte.editado_em = arquivo.modificado_em
    fonte.importado_em = importacao._agora()
    fonte.status = status
    fonte.motivo = importacao.motivo_da_coluna(motivo)
    db.flush()  # para ter o fonte.id
    _gravar_trechos_de_busca(db, fonte, texto if status in COM_BUSCA else "")
    db.commit()


def _ler(
    leitor: LeitorDrive, arquivo: ArquivoDrive, titulo: str, relatorio: Relatorio
) -> tuple[str, str, str, str]:
    """(texto, status, motivo, hash). O status "triar" quer dizer: leu o texto, falta a triagem. "falha": o Drive
    falhou (já entrou no relatório)."""
    limite = settings.drive_max_mb * 1024 * 1024
    if arquivo.tamanho is not None and arquivo.tamanho > limite:
        mb = arquivo.tamanho / (1024 * 1024)
        return "", "pulada_longa", (f"arquivo de {mb:.0f} MB, acima do limite de {settings.drive_max_mb} MB "
                                    "(DRIVE_MAX_MB no .env)"), _hash_sem_leitura(arquivo)
    if not extrair_texto.suportado(arquivo.mime):
        return "", "vazia", f"formato não suportado ({arquivo.mime})", _hash_sem_leitura(arquivo)

    try:
        with tempfile.TemporaryDirectory(prefix="cerebro_drive_") as pasta:
            destino = Path(pasta) / "arquivo"
            leitor.baixar(arquivo, destino)
            texto = extrair_texto.extrair(destino, arquivo.mime)
    except ErroDrive as e:
        relatorio.paginas.append(PaginaLida(arquivo.id, titulo, "falha", motivo=str(e)))
        return "", "falha", "", ""
    except extrair_texto.ErroDeLeitura as e:
        return "", "vazia", f"não consegui ler o arquivo ({e})", _hash_sem_leitura(arquivo)
    return texto, "triar", "", markdown_notion.hash_conteudo(texto)


def _triar(
    db: Session, arquivo: ArquivoDrive, titulo: str, texto: str, hash_novo: str, hashes: dict[str, str]
) -> tuple[str, str, list[trechos.Trecho]]:
    """(status, motivo, trechos), depois de ler o texto. O dado pessoal NÃO entra aqui (decisão do Davi)."""
    if markdown_notion.caracteres_de_texto(texto) < MIN_CARACTERES:
        sem_texto = arquivo.mime == extrair_texto.MIME_PDF
        return "vazia", ("sem texto: o PDF parece ser só imagem (não faço OCR)" if sem_texto
                         else f"menos de {MIN_CARACTERES} caracteres de texto"), []

    original = hashes.get(hash_novo) or db.scalar(
        select(Fonte.titulo).where(
            Fonte.origem == ORIGEM,
            Fonte.hash_conteudo == hash_novo,
            Fonte.id_externo != arquivo.id,
            Fonte.status.not_in(["removida", "pulada_duplicata", "vazia", "pulada_longa"]),
        ).order_by(Fonte.id).limit(1)
    )
    if original:
        return "pulada_duplicata", f"mesmo conteúdo de “{original}”", []

    if extrair_texto.e_planilha(arquivo.mime):
        return "so_busca", "planilha: o consultor acha na busca, mas ela não vai ao curador", []

    titulo_com_pasta = f"{titulo} (pasta {arquivo.categoria})" if arquivo.categoria else titulo
    partes = trechos.dividir(titulo_com_pasta, texto, rotulo="Documento do Drive")
    if len(partes) > settings.drive_max_trechos:
        return "so_busca", (f"{len(partes)} trechos (limite {settings.drive_max_trechos}): "
                            "o consultor acha na busca, mas ele não vai ao curador"), []
    return "a_curar", "", partes


def _gravar_trechos_de_busca(db: Session, fonte: Fonte, texto: str) -> None:
    """Troca os pedaços de busca do documento (apaga os antigos; `texto` vazio só apaga)."""
    db.execute(delete(TrechoDocumento).where(TrechoDocumento.fonte_id == fonte.id))
    if texto:
        db.add_all(
            TrechoDocumento(fonte_id=fonte.id, ordem=i, texto=pedaco)
            for i, pedaco in enumerate(trechos.quebrar(texto, TAMANHO_DO_TRECHO_DE_BUSCA), start=1)
        )


def _conferir_removidas(db: Session, vistas: set[str], relatorio: Relatorio) -> None:
    """As fontes do Drive que não vieram na lista (e a lista veio completa): saíram da pasta."""
    sumidas = db.scalars(
        select(Fonte).where(Fonte.origem == ORIGEM, Fonte.status != "removida", Fonte.id_externo.not_in(vistas))
        .order_by(Fonte.id)
    )
    motivo = "saiu da pasta do Drive (apagado, movido ou sem acesso)"
    for fonte in list(sumidas):
        relatorio.paginas.append(PaginaLida(fonte.id_externo, fonte.titulo, "removida", "removida", motivo))
        if not relatorio.dry_run:
            fonte.status, fonte.motivo = "removida", motivo
            importacao._obsoletar_pendentes(db, fonte.url, f"o arquivo saiu do Drive ({motivo})", relatorio, DRIVE)
            _gravar_trechos_de_busca(db, fonte, "")
            db.commit()
