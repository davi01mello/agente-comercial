"""Exporta os itens aprovados do banco para a base REAL do golden set. Rode na raiz do repositório, com o .venv ativo:

    python -m scripts.exportar_golden                      # grava tests/golden/base_real.json
    python -m scripts.exportar_golden --saida outro.json   # grava em outro arquivo

Entram só os itens que o consultor usa (`validado` e `consolidado`, knowledge.STATUS_NA_BASE), nos mesmos campos da
base fictícia (tests/golden/base.json): é o que o test_golden.py sabe carregar. O arquivo tem conteúdo real do
comercial, então fica FORA do Git (.gitignore) e só vai ao modelo com a chave paga.

Item com possível dado pessoal (e-mail, CPF, CNPJ, telefone) no que vai ao modelo é PULADO: a saída mostra só o id,
para corrigir na Fila, nunca o dado. O `contexto_cliente` e o `autor` nem saem do banco (o consultor não os recebe).
Para exportar de outro banco (a Railway, por exemplo), troque o DATABASE_URL só nesta execução.
"""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dominio, knowledge
from app.db import SessionLocal
from app.models import Insight

SAIDA_PADRAO = Path(__file__).parent.parent / "tests" / "golden" / "base_real.json"
# Os campos da tests/golden/base.json, na mesma ordem: o test_golden.py monta um Insight com eles.
CAMPOS = ["id", "titulo", "tipo", "secao", "segmento", "evidencia", "descricao", "o_que_foi_feito", "resultado",
          "data_evento"]
# O que vai ao modelo pela linha do item (knowledge.formatar): é aqui que o dado pessoal não pode estar.
CAMPOS_DE_TEXTO = ["titulo", "segmento", "descricao", "o_que_foi_feito", "resultado"]


def exportar(db: Session) -> tuple[list[dict], list[int]]:
    """Os itens aprovados como dicionários (em ordem de id) e os ids pulados por possível dado pessoal."""
    itens = db.scalars(select(Insight).where(Insight.status.in_(knowledge.STATUS_NA_BASE)).order_by(Insight.id))
    exportados: list[dict] = []
    pulados: list[int] = []
    for item in itens:
        try:
            dominio.exigir_sem_dados_pessoais(**{c: getattr(item, c) for c in CAMPOS_DE_TEXTO})
        except dominio.DadoPessoalNaEntrada:
            pulados.append(item.id)
            continue
        linha = {c: getattr(item, c) for c in CAMPOS}
        linha["data_evento"] = item.data_evento.isoformat() if item.data_evento else None
        exportados.append(linha)
    return exportados, pulados


def argumentos(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.exportar_golden",
        description="Exporta os itens aprovados na Fila para a base real do golden set (fora do Git).",
    )
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO, metavar="ARQUIVO",
                        help=f"onde gravar o JSON (padrão: {SAIDA_PADRAO.relative_to(SAIDA_PADRAO.parents[2])})")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    opcoes = argumentos(args)
    with SessionLocal() as db:
        itens, pulados = exportar(db)
    if pulados:
        print(f"Pulei {len(pulados)} item(ns) com possível dado pessoal (ids {', '.join(map(str, pulados))}). "
              "Corrija na Fila e exporte de novo.", file=sys.stderr)
    if not itens:
        print("Erro: nenhum item aprovado para exportar. Aprove itens na Fila antes. Nenhum arquivo foi gravado.",
              file=sys.stderr)
        return 1
    opcoes.saida.write_text(json.dumps(itens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(itens)} itens exportados para {opcoes.saida}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
