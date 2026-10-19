"""Sincronização automática do Drive (T6): de tempos em tempos o servidor olha a pasta e traz o que mudou.

Liga com DRIVE_SYNC_INTERVALO_MIN > 0 (e a pasta e a credencial no .env). Cada rodada é uma execução comum de
`importacao_drive` (aparece na tela de Fontes), incremental: arquivo que não mudou nem é baixado, então uma rodada sem
novidade custa só a lista de arquivos. O curador roda com o teto DRIVE_SYNC_TETO_USD por rodada.

Sem fila externa de propósito: o servidor tem um processo só (como no dev e na Railway), e a trava de uma
sincronização por vez é a mesma da API. Rodada que cai no meio vira `erro` e a próxima continua de onde parou.
"""
import asyncio
import json
import logging
import threading

from sqlalchemy import select

from app import importacao, importacao_drive
from app.config import settings
from app.db import SessionLocal
from app.drive import ErroDrive, LeitorDrive
from app.models import ExecucaoImportacao

logger = logging.getLogger(__name__)

PRIMEIRA_ESPERA_S = 30


def rodar_uma_vez(trava: threading.Lock) -> int | None:
    """Uma rodada. Devolve o id da execução, ou None se não rodou (Drive sem configuração, Gemini sem chave ou outra
    sincronização em andamento). Nunca levanta: quem chama é um laço que não pode morrer."""
    if not importacao_drive.configurado():
        return None
    try:
        importacao_drive.conferir_configuracao(dry_run=False)
        leitor = LeitorDrive()
    except (importacao.FaltaConfiguracao, ErroDrive) as e:
        logger.warning(json.dumps({"evento": "sync_drive_agendada_sem_configuracao", "erro": type(e).__name__}))
        return None

    with trava, SessionLocal() as db:
        rodando = db.scalar(
            select(ExecucaoImportacao.id)
            .where(ExecucaoImportacao.status == "rodando", ExecucaoImportacao.dry_run.is_(False)).limit(1)
        )
        if rodando is not None:  # alguém (a tela, o script, a rodada anterior) já está sincronizando
            return None
        execucao_id = importacao_drive.nova_execucao(db, teto_usd=settings.drive_sync_teto_usd).id

    try:
        importacao_drive.executar(leitor, teto_usd=settings.drive_sync_teto_usd, execucao_id=execucao_id)
    except Exception as e:  # a execução já ficou `erro`, com o tipo; a próxima rodada tenta de novo
        logger.warning(json.dumps({"evento": "sync_drive_agendada_falhou", "execucao_id": execucao_id,
                                   "erro": type(e).__name__}))
    return execucao_id


async def laco(trava: threading.Lock) -> None:
    """Dorme o intervalo, roda, repete. Roda a rodada numa thread: ela é bloqueante (rede, banco, modelo)."""
    intervalo = settings.drive_sync_intervalo_min * 60
    await asyncio.sleep(PRIMEIRA_ESPERA_S)  # deixa o servidor terminar de subir antes da primeira rodada
    while True:
        await asyncio.to_thread(rodar_uma_vez, trava)
        await asyncio.sleep(intervalo)
