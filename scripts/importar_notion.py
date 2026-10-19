"""Importa as páginas do Notion compartilhadas com a integração (T4). Rode na raiz do repositório, com o .venv ativo:

    python -m scripts.importar_notion --dry-run             # só lista o que faria e estima tokens e custo
    python -m scripts.importar_notion --limite-paginas 3    # lê só as 3 primeiras páginas
    python -m scripts.importar_notion                       # importa e roda o curador (teto padrão: US$ 1)
    python -m scripts.importar_notion --teto-usd 0.50       # o mesmo, com outro teto de gasto

Precisa de NOTION_TOKEN no .env e, fora do --dry-run, de GEMINI_API_KEY. O --dry-run não muda nenhuma fonte e não
chama o modelo (só a execução fica registrada, com dry_run=True). Conteúdo REAL do comercial só com a chave PAGA do
Gemini (ADR-005 §4.4). O relatório sai no terminal (os títulos aparecem nele; título com dado pessoal sai omitido). O
log (stderr) tem só números, nunca texto.
"""
import argparse
import logging
import sys

from app.importacao import FaltaConfiguracao, Relatorio, conferir_configuracao, executar
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


def _dolares_positivos(texto: str) -> float:
    valor = float(texto.replace(",", "."))
    if not valor > 0:  # "not >" também recusa nan
        raise argparse.ArgumentTypeError("precisa ser maior que zero (ex.: 1 ou 0,50)")
    return valor


def argumentos(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.importar_notion",
        description="Importa as páginas do Notion compartilhadas com a integração para a tabela fontes.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="só lista o que faria e estima tokens e custo (não muda as fontes, não chama o modelo)")
    parser.add_argument("--limite-paginas", type=_inteiro_positivo, metavar="N",
                        help="lê só as N primeiras páginas (as mais antigas pela data de edição)")
    parser.add_argument("--teto-usd", type=_dolares_positivos, default=1.0, metavar="US$",
                        help="o máximo que o curador pode gastar nesta execução (padrão: 1). Se não couber, ele para e "
                             "a próxima execução continua de onde parou")
    return parser.parse_args(args)


def _numero(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def _dolares(valor: float, casas: int = 4) -> str:
    return "US$ " + f"{valor:.{casas}f}".replace(".", ",")


def formatar(relatorio: Relatorio) -> str:
    """O relatório da execução, como a spec pede: lidas / novas / alteradas / puladas (com motivo) / custo estimado."""
    r = relatorio
    linhas = [
        f"SIMULAÇÃO (--dry-run, execução #{r.execucao_id}): nenhuma fonte mudou e o modelo não foi chamado."
        if r.dry_run else f"Importação do Notion: execução #{r.execucao_id}",
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
    if not r.dry_run and r.teto_usd is not None:
        linhas += _curador(r)
    if r.avisos:
        linhas += ["", "Avisos:"] + [f"  - {aviso}" for aviso in r.avisos]
    return "\n".join(linhas)


def _curador(r: Relatorio) -> list[str]:
    """O que o curador fez: itens propostos, custo real × teto, falhas, o que ficou esperando e os obsoletos."""
    linhas = [
        "",
        f"Curador: {len(r.curadas)} páginas, {r.insights_propostos} itens propostos (na Fila, como "
        "historico_a_validar: alguém do time revisa)",
        f"Custo real: {_dolares(r.custo_real_usd)} (teto: {_dolares(r.teto_usd, 2)})",
    ]
    if r.falhas_do_curador:
        linhas += [f"Falhas do curador ({len(r.falhas_do_curador)}), tentadas de novo na próxima execução:"]
        linhas += [f"  - {p.titulo}: {p.motivo}" for p in r.falhas_do_curador]
    if r.parou_no_teto:
        linhas.append(f"Parou no teto: {len(r.esperando)} páginas esperando. Rode de novo para continuar (o que já "
                      "entrou na Fila não se repete).")
    if r.obsoletos or r.aprovados_de_paginas_mudadas:
        linhas.append(f"Páginas que mudaram ou saíram do Notion: {r.obsoletos} itens pendentes viraram obsoletos.")
    if r.aprovados_de_paginas_mudadas:
        linhas.append(f"  - {r.aprovados_de_paginas_mudadas} itens JÁ APROVADOS vieram dessas páginas e não mudaram: "
                      "confira no Playbook se ainda valem.")
    return linhas


def _ligar_log() -> None:
    """As linhas do app (contagens, novas tentativas no Notion) no stderr, como no servidor. Nunca têm texto."""
    log_do_app = logging.getLogger("app")
    if not log_do_app.handlers:
        saida = logging.StreamHandler()
        saida.setFormatter(logging.Formatter("%(levelname)s: [%(name)s] %(message)s"))
        log_do_app.addHandler(saida)
    log_do_app.setLevel(logging.INFO)


def main(args: list[str] | None = None, leitor: LeitorNotion | None = None) -> int:
    """`leitor` serve para os testes (um leitor com o Notion falso). Devolve o código de saída do processo. As
    regras são as do POST /fontes/sincronizar: as duas portas chamam as mesmas funções de app/importacao.py."""
    opcoes = argumentos(args)
    _ligar_log()
    try:
        leitor = leitor or LeitorNotion()
        conferir_configuracao(opcoes.dry_run)  # antes de ler o Notion: sem a chave, toda página só falharia
        relatorio = executar(leitor, dry_run=opcoes.dry_run, limite_paginas=opcoes.limite_paginas,
                             teto_usd=opcoes.teto_usd)
    except (ErroNotion, FaltaConfiguracao) as e:
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
