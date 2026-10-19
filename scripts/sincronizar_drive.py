"""Sincroniza a pasta "Conhecimento Comercial" do Google Drive (T6). Rode na raiz do repositório, com o .venv ativo:

    python -m scripts.sincronizar_drive --dry-run             # só lista o que faria e estima tokens e custo
    python -m scripts.sincronizar_drive --limite-arquivos 3   # lê só os 3 primeiros arquivos
    python -m scripts.sincronizar_drive                       # sincroniza e roda o curador (teto padrão: US$ 1)
    python -m scripts.sincronizar_drive --teto-usd 0.50       # o mesmo, com outro teto de gasto

Precisa no .env de DRIVE_PASTA_ID e da credencial da conta de serviço (GOOGLE_APPLICATION_CREDENTIALS, o caminho do
JSON) e, fora do --dry-run, de GEMINI_API_KEY. O --dry-run baixa e lê os arquivos, mas não muda nenhuma fonte e não
chama o modelo (só a execução fica registrada, com dry_run=True). É incremental: arquivo que não mudou nem é baixado.
Dado pessoal NÃO barra nem mascara os documentos do Drive (decisão do time: o texto é privado). Os mesmos passos
rodam no servidor, pelo botão "Sincronizar agora" da tela de Fontes e pela sincronização automática. O log (stderr)
tem só números, nunca nome de arquivo nem texto.
"""
import argparse
import sys

from app import importacao_drive
from app.drive import ErroDrive, LeitorDrive
from app.importacao import FaltaConfiguracao
from scripts.importar_notion import _dolares_positivos, _inteiro_positivo, _ligar_log, formatar


def argumentos(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.sincronizar_drive",
        description="Traz os arquivos da pasta do Drive para a tabela fontes e para a busca do consultor.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="só lista o que faria e estima tokens e custo (não muda as fontes, não chama o modelo)")
    parser.add_argument("--limite-arquivos", type=_inteiro_positivo, metavar="N",
                        help="lê só os N primeiros arquivos (os mais antigos pela data de edição, pasta a pasta)")
    parser.add_argument("--teto-usd", type=_dolares_positivos, default=1.0, metavar="US$",
                        help="o máximo que o curador pode gastar nesta execução (padrão: 1). Se não couber, ele para e "
                             "a próxima execução continua de onde parou")
    return parser.parse_args(args)


def main(args: list[str] | None = None, leitor: LeitorDrive | None = None) -> int:
    """`leitor` serve para os testes (um leitor com o Drive falso). Devolve o código de saída do processo."""
    opcoes = argumentos(args)
    _ligar_log()
    try:
        leitor = leitor or LeitorDrive()
        importacao_drive.conferir_configuracao(opcoes.dry_run)  # antes de ler o Drive: sem a chave, tudo só falharia
        relatorio = importacao_drive.executar(leitor, dry_run=opcoes.dry_run, limite_paginas=opcoes.limite_arquivos,
                                              teto_usd=opcoes.teto_usd)
    except (ErroDrive, FaltaConfiguracao) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # a mensagem NÃO é mostrada: ela pode ter texto de documento
        print(f"Erro inesperado ({type(e).__name__}). O que estava pela metade não foi gravado. Rode de novo e, se "
              "repetir, avise quem cuida do código.", file=sys.stderr)
        return 2
    print(formatar(relatorio, fonte="Drive", unidade="Arquivos"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
