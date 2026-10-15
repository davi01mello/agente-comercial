"""Importa as páginas do Notion compartilhadas com a integração (T4). Rode na raiz do repositório, com o .venv ativo:

    python -m scripts.importar_notion --dry-run             # só lista o que faria e estima tokens e custo
    python -m scripts.importar_notion --limite-paginas 3    # lê só as 3 primeiras páginas
    python -m scripts.importar_notion                       # importa de verdade

Precisa de NOTION_TOKEN no .env. O --dry-run não grava nada e não chama o modelo. O relatório sai no terminal (os
títulos aparecem nele; título com dado pessoal sai omitido). O log (stderr) tem só números, nunca texto.
"""
import argparse
import logging
import sys

from app.db import SessionLocal
from app.importacao import Relatorio, importar
from app.notion import ErroNotion, LeitorNotion

ROTULO = {
    "vazia": "vazia",
    "pulada_dado_pessoal": "pulada por dado pessoal",
    "pulada_longa": "longa demais",
    "pulada_duplicata": "duplicata",
}


def _inteiro_positivo(texto: str) -> int:
    valor = int(texto)
    if valor < 1:
        raise argparse.ArgumentTypeError("precisa ser 1 ou mais")
    return valor


def argumentos(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.importar_notion",
        description="Importa as páginas do Notion compartilhadas com a integração para a tabela fontes.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="só lista o que faria e estima tokens e custo (não grava nada, não chama o modelo)")
    parser.add_argument("--limite-paginas", type=_inteiro_positivo, metavar="N",
                        help="lê só as N primeiras páginas (as mais antigas pela data de edição)")
    return parser.parse_args(args)


def _numero(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def _dolares(valor: float) -> str:
    return "US$ " + f"{valor:.4f}".replace(".", ",")


def formatar(relatorio: Relatorio) -> str:
    """O relatório da execução, como a spec pede: lidas / novas / alteradas / puladas (com motivo) / custo estimado."""
    r = relatorio
    linhas = [
        "SIMULAÇÃO (--dry-run): nada foi gravado e o modelo não foi chamado." if r.dry_run
        else f"Importação do Notion: execução #{r.execucao_id}",
        f"Páginas lidas: {r.lidas} · novas: {len(r.novas)} · alteradas: {len(r.alteradas)} · "
        f"sem mudança: {len(r.sem_mudanca)} · puladas: {len(r.puladas)} · falhas: {len(r.falhas)} · "
        f"removidas: {len(r.removidas)}",
        f"Requisições ao Notion: {r.requisicoes_notion}",
    ]
    if r.puladas:
        linhas += ["", f"Puladas ({len(r.puladas)}):"]
        linhas += [f"  - {ROTULO[p.status]}: {p.titulo} ({p.motivo})" for p in r.puladas]
    if r.falhas:
        linhas += ["", f"Falhas ({len(r.falhas)}), tentadas de novo na próxima execução:"]
        linhas += [f"  - {p.titulo}: {p.motivo}" for p in r.falhas]
    if r.removidas:
        linhas += ["", f"Removidas do Notion ({len(r.removidas)}):"]
        linhas += [f"  - {p.titulo} ({p.motivo})" for p in r.removidas]

    estimativa = r.estimativa
    n_trechos = sum(len(p.trechos) for p in r.a_curar)
    linhas += ["", f"Para o curador: {len(r.a_curar)} páginas, {n_trechos} trechos"]
    linhas += [f"  - {p.titulo} ({len(p.trechos)} {'trecho' if len(p.trechos) == 1 else 'trechos'})"
               for p in r.a_curar]
    if r.a_curar:
        media = estimativa.custo_usd / len(r.a_curar)
        linhas.append(
            f"Custo estimado do curador: {_dolares(estimativa.custo_usd)} ({estimativa.chamadas} chamadas, "
            f"~{_numero(estimativa.tokens_entrada)} tokens de entrada e ~{_numero(estimativa.tokens_saida)} de saída; "
            f"média de {_dolares(media)} por página)"
        )
    if r.avisos:
        linhas += ["", "Avisos:"] + [f"  - {aviso}" for aviso in r.avisos]
    return "\n".join(linhas)


def _ligar_log() -> None:
    """As linhas do app (contagens, novas tentativas no Notion) no stderr, como no servidor. Nunca têm texto."""
    log_do_app = logging.getLogger("app")
    if not log_do_app.handlers:
        saida = logging.StreamHandler()
        saida.setFormatter(logging.Formatter("%(levelname)s: [%(name)s] %(message)s"))
        log_do_app.addHandler(saida)
    log_do_app.setLevel(logging.INFO)


def main(args: list[str] | None = None, leitor: LeitorNotion | None = None) -> int:
    """`leitor` serve para os testes (um leitor com o Notion falso). Devolve o código de saída do processo."""
    opcoes = argumentos(args)
    _ligar_log()
    try:
        leitor = leitor or LeitorNotion()
        with SessionLocal() as db:
            relatorio = importar(leitor, db, dry_run=opcoes.dry_run, limite_paginas=opcoes.limite_paginas)
    except ErroNotion as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # a mensagem NÃO é mostrada: ela pode ter texto de página (ex.: os parâmetros de um SQL)
        print(f"Erro inesperado ({type(e).__name__}). O que estava pela metade não foi gravado. Rode de novo e, se "
              "repetir, avise quem cuida do código.", file=sys.stderr)
        return 2
    print(formatar(relatorio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
