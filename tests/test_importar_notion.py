"""Testes do scripts/importar_notion.py (opções e relatório) e da estimativa de custo, sem rede e sem modelo (o
curador é o CuradorDeLote de test_curadoria_notion)."""
import pytest
from sqlalchemy import func, select

from app import importacao, llm, notion
from app.db import SessionLocal
from app.importacao import estimar
from app.models import ExecucaoImportacao, Fonte, Insight
from app.notion import LeitorNotion
from app.trechos import Trecho
from scripts import importar_notion
from tests.notion_falso import TOKEN_DE_TESTE, NotionFalso, limpar_banco_da_importacao
from tests.test_curadoria_notion import CuradorDeLote


@pytest.fixture(autouse=True)
def banco_limpo(monkeypatch):
    monkeypatch.setattr(notion, "_dormir", lambda segundos: None)
    monkeypatch.setattr(llm.settings, "gemini_api_key", "chave-de-teste")
    usar_curador(monkeypatch, CuradorDeLote())
    with SessionLocal() as db:
        limpar_banco_da_importacao(db)


@pytest.fixture
def falso():
    return NotionFalso()


def rodar(falso, capsys, *args) -> tuple[int, str, str]:
    leitor = LeitorNotion(token=TOKEN_DE_TESTE, cliente_http=falso.cliente_http())
    codigo = importar_notion.main(list(args), leitor=leitor)
    saida = capsys.readouterr()
    return codigo, saida.out, saida.err


def usar_curador(monkeypatch, curador: CuradorDeLote) -> CuradorDeLote:
    monkeypatch.setattr(llm, "curar", curador.curar)
    monkeypatch.setattr(llm, "relacionar", curador.relacionar)
    return curador


def contar(modelo) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(modelo))


# --- opções -------------------------------------------------------------------------------------------------

def test_opcoes_padrao():
    opcoes = importar_notion.argumentos([])

    assert (opcoes.dry_run, opcoes.limite_paginas, opcoes.teto_usd) == (False, None, 1.0)  # teto do teste do Davi


@pytest.mark.parametrize("valor, esperado", [("0.5", 0.5), ("0,50", 0.5), ("3", 3.0)])
def test_teto_aceita_ponto_ou_virgula(valor, esperado):
    assert importar_notion.argumentos(["--teto-usd", valor]).teto_usd == esperado


@pytest.mark.parametrize("valor", ["0", "-1", "nan", "um"])
def test_teto_precisa_ser_positivo(valor):
    with pytest.raises(SystemExit):
        importar_notion.argumentos(["--teto-usd", valor])


@pytest.mark.parametrize("valor", ["0", "-1", "dez"])
def test_limite_de_paginas_precisa_ser_positivo(valor):
    with pytest.raises(SystemExit):
        importar_notion.argumentos(["--limite-paginas", valor])


# --- relatório ----------------------------------------------------------------------------------------------

def test_relatorio_tem_as_contagens_e_os_motivos(falso, capsys):
    codigo, saida, _ = rodar(falso, capsys)

    assert codigo == 0
    assert saida.startswith("Importação do Notion: execução #")
    assert ("Páginas lidas: 10 · novas: 10 · alteradas: 0 · sem mudança: 0 · puladas: 4 · falhas: 0 · "
            "removidas: 0") in saida
    assert "Puladas (4):" in saida
    assert "  - vazia: Cérebro: teste fictício (menos de 20 caracteres de texto)" in saida
    assert "  - pulada por dado pessoal: Contato do hotel parceiro (e-mail no conteúdo)" in saida
    assert "  - pulada por dado pessoal: (título omitido: tem dado pessoal) (telefone no título)" in saida
    assert ("  - duplicata: Cópia de Prospecção por indicação (mesmo conteúdo de “Prospecção por indicação”)"
            in saida)
    assert "Para o curador: 6 páginas, 6 trechos" in saida
    assert "  - Objeções comuns e respostas (1 trecho)" in saida
    assert "Custo estimado do curador: US$ " in saida


def test_relatorio_nao_repete_o_dado_pessoal(falso, capsys):
    _, saida, erro = rodar(falso, capsys)

    for dado in ["contato@hotel-ficticio.com.br", "99876"]:
        assert dado not in saida and dado not in erro


def test_relatorio_mostra_falhas_removidas_e_avisos(falso, capsys):
    rodar(falso, capsys)
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True
    falso.editar("Prospecção por indicação", "Indicação no encerramento trouxe três clientes novos no ano.")
    falso.falhar("/children", 403)

    _, saida, _ = rodar(falso, capsys)

    assert "Falhas (1), tentadas de novo na próxima execução:" in saida
    assert "  - Prospecção por indicação: A integração do Notion não tem permissão de leitura" in saida
    assert "Removidas do Notion (1):\n  - Rascunho antigo de proposta (na lixeira do Notion)" in saida

    _, saida, _ = rodar(falso, capsys, "--limite-paginas", "2")

    assert "Avisos:\n  - A lista de páginas veio incompleta" in saida


def test_sem_nada_para_o_curador_nao_mostra_custo(falso, capsys):
    falso.ws["paginas"] = {}

    _, saida, _ = rodar(falso, capsys)

    assert "Para o curador: 0 páginas, 0 trechos" in saida
    assert "Custo estimado" not in saida


def test_relatorio_mostra_o_curador_e_o_custo_real(falso, capsys):
    _, saida, _ = rodar(falso, capsys)

    assert ("Curador: 6 páginas, 6 itens propostos (na Fila, como historico_a_validar: alguém do time revisa)"
            in saida)
    assert "Custo real: US$ 0,0060 (teto: US$ 1,00)" in saida  # 6 chamadas de US$ 0,001 no curador falso
    assert "Parou no teto" not in saida and "Falhas do curador" not in saida


def test_relatorio_mostra_falhas_do_curador_e_o_teto(monkeypatch, falso, capsys):
    usar_curador(monkeypatch, CuradorDeLote(custo=0.5, falhar_se=lambda t: "Objeções" in t))

    _, saida, _ = rodar(falso, capsys, "--teto-usd", "1")

    assert ("Falhas do curador (1), tentadas de novo na próxima execução:\n"
            "  - Objeções comuns e respostas: o curador falhou") in saida
    assert "Parou no teto: 4 páginas esperando. Rode de novo para continuar" in saida


def test_relatorio_mostra_obsoletos_e_aprovados_de_paginas_que_mudaram(falso, capsys):
    rodar(falso, capsys)
    with SessionLocal() as db:
        aprovado = db.scalar(select(Insight).where(Insight.titulo == "Rascunho antigo de proposta"))
        aprovado.status = "validado"
        db.commit()
    falso.pagina("Rascunho antigo de proposta")["in_trash"] = True
    falso.pagina("Hotel Fictício Sol")["in_trash"] = True

    _, saida, _ = rodar(falso, capsys)

    assert "Páginas que mudaram ou saíram do Notion: 1 itens pendentes viraram obsoletos." in saida
    assert "  - 1 itens JÁ APROVADOS vieram dessas páginas e não mudaram" in saida


def test_sem_chave_do_gemini_para_antes_de_ler(monkeypatch, falso, capsys):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    codigo, saida, erro = rodar(falso, capsys)

    assert codigo == 1 and saida == ""
    assert "Erro: Falta GEMINI_API_KEY no .env" in erro
    assert falso.pedidos == []  # nem leu o Notion
    assert rodar(falso, capsys, "--dry-run")[0] == 0  # o dry-run não precisa da chave


# --- dry-run ------------------------------------------------------------------------------------------------

def test_dry_run_nao_grava_nada_e_lista_o_que_faria(falso, capsys):
    codigo, saida, _ = rodar(falso, capsys, "--dry-run")

    assert codigo == 0
    assert saida.startswith("SIMULAÇÃO (--dry-run): nada foi gravado e o modelo não foi chamado.")
    assert "Para o curador: 6 páginas, 6 trechos" in saida
    assert "Custo estimado do curador: US$ " in saida
    assert "Curador:" not in saida
    assert contar(Fonte) == 0
    assert contar(ExecucaoImportacao) == 0


def test_limite_de_paginas_chega_na_importacao(falso, capsys):
    _, saida, _ = rodar(falso, capsys, "--dry-run", "--limite-paginas", "3")

    assert "Páginas lidas: 3 · " in saida


# --- erros --------------------------------------------------------------------------------------------------

def test_sem_token_para_antes_de_ler(monkeypatch, capsys):
    monkeypatch.setattr(notion.settings, "notion_token", "")

    codigo = importar_notion.main([])

    assert codigo == 1
    assert "Erro: Falta NOTION_TOKEN no .env" in capsys.readouterr().err


def test_erro_do_notion_vira_mensagem_e_codigo_de_saida(falso, capsys):
    falso.falhar("/v1/search", 401)

    codigo, saida, erro = rodar(falso, capsys)

    assert codigo == 1
    assert "Erro: O token do Notion é inválido" in erro
    assert TOKEN_DE_TESTE not in saida + erro


def test_erro_inesperado_nao_mostra_a_mensagem(monkeypatch, falso, capsys):
    """A mensagem de um erro inesperado pode trazer texto de página (o SQLAlchemy mostra os parâmetros do SQL)."""
    def quebrar(*args, **kwargs):
        raise RuntimeError("TEXTO-DE-PAGINA-NO-ERRO")

    monkeypatch.setattr(importar_notion, "importar", quebrar)

    codigo, saida, erro = rodar(falso, capsys)

    assert codigo == 2
    assert "Erro inesperado (RuntimeError)" in erro
    assert "TEXTO-DE-PAGINA-NO-ERRO" not in saida + erro


# --- estimativa ---------------------------------------------------------------------------------------------

def test_estimativa_de_um_trecho_de_3_mil_caracteres_e_comparavel_com_a_do_davi(monkeypatch):
    """O Davi estimou ~US$ 0,01 por página (curador + relações, no preço do 3.8 Flash)."""
    monkeypatch.setattr(importacao.settings, "preco_entrada_1m", 0.75)
    monkeypatch.setattr(importacao.settings, "preco_saida_1m", 3.75)

    estimativa = estimar([Trecho(texto="x" * 3000, parte=1, total=1)])

    assert estimativa.chamadas == 2
    assert estimativa.tokens_entrada == 1976 + 60 + 750 + 1187
    assert estimativa.tokens_saida == 900
    assert estimativa.custo_usd == pytest.approx(0.00635, abs=0.00001)


def test_estimativa_usa_os_precos_do_env_e_soma_os_trechos(monkeypatch):
    monkeypatch.setattr(importacao.settings, "preco_entrada_1m", 1.0)
    monkeypatch.setattr(importacao.settings, "preco_saida_1m", 10.0)
    partes = [Trecho(texto="x" * 4000, parte=i, total=2) for i in (1, 2)]

    estimativa = estimar(partes)

    assert estimativa.chamadas == 4
    assert estimativa.custo_usd == pytest.approx((2 * (1976 + 60 + 1000 + 1187) * 1 + 2 * 900 * 10) / 1_000_000)


def test_sem_trechos_custo_zero():
    assert estimar([]) == importacao.Estimativa(chamadas=0, tokens_entrada=0, tokens_saida=0, custo_usd=0.0)
