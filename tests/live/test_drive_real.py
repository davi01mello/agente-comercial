"""A pasta REAL do Drive, com a conta de serviço de verdade: prova que a credencial, o compartilhamento e a leitura
funcionam fora dos testes com Drive falso.

Roda só à mão:  pytest -m live tests/live
- Sem DRIVE_PASTA_ID e a credencial do Google no .env, os testes são pulados.
- Não chama o Gemini (não gasta cota) e não grava nada no banco: só lista e lê. Não imprime nome de arquivo nem texto.
- No `pytest` normal (e no CI) eles nem rodam: o pytest.ini tem `-m "not live"`.
"""
import tempfile
from pathlib import Path

import pytest

from app import extrair_texto
from app.config import settings
from app.drive import LeitorDrive

CREDENCIAL = settings.google_application_credentials or settings.google_service_account_json

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.drive_pasta_id or not CREDENCIAL,
                       reason="sem DRIVE_PASTA_ID e credencial do Google no .env"),
]

LIMITE_DO_TESTE = 5 * 1024 * 1024  # baixa só arquivo pequeno: o teste é rápido


@pytest.fixture(scope="module")
def busca():
    return LeitorDrive().arquivos()


def test_lista_a_pasta_com_as_subpastas(busca):
    assert busca.completa, "alguma subpasta não pôde ser lida: confira se a conta de serviço tem acesso a todas"
    assert busca.arquivos, "a pasta veio vazia: confira o DRIVE_PASTA_ID e o compartilhamento com a conta de serviço"
    assert len({a.id for a in busca.arquivos}) == len(busca.arquivos)
    assert all(a.url.startswith("https://drive.google.com/") for a in busca.arquivos)
    assert any(a.categoria for a in busca.arquivos), "esperava arquivos dentro de subpastas (Ensinamentos, Resumo...)"


def test_baixa_e_le_um_arquivo_de_cada_formato(busca):
    """Um arquivo pequeno de cada tipo suportado (docx, pdf, Google Doc...): baixa e tira texto, sem erro."""
    por_mime: dict[str, object] = {}
    for a in busca.arquivos:
        if extrair_texto.suportado(a.mime) and (a.tamanho is None or a.tamanho <= LIMITE_DO_TESTE):
            por_mime.setdefault(a.mime, a)
    if not por_mime:
        pytest.skip("nenhum arquivo pequeno de formato suportado na pasta")
    leitor = LeitorDrive()
    sem_texto = []
    with tempfile.TemporaryDirectory() as pasta:
        for mime, arquivo in por_mime.items():
            destino = Path(pasta) / "arquivo"
            leitor.baixar(arquivo, destino)
            assert destino.stat().st_size > 0
            if not extrair_texto.extrair(destino, mime).strip():
                sem_texto.append(mime)  # PDF só de imagem dá texto vazio: é esperado, a importação marca "vazia"
    assert len(sem_texto) < len(por_mime), "nenhum formato deu texto: a leitura não está funcionando"
