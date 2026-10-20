"""Testes do scripts/exportar_golden.py: o que sai do banco para a base real do golden set, e o que fica de fora."""
import json
import uuid
from datetime import date, datetime
from pathlib import Path

from app.db import SessionLocal
from app.models import Insight
from scripts import exportar_golden

BASE_FICTICIA = Path(__file__).parent / "golden" / "base.json"


def criar(db, marca: str, status: str = "validado", **campos) -> Insight:
    padrao = {"titulo": f"Item {marca}", "tipo": "aprendizado", "secao": "proposta", "descricao": "Piloto ajudou.",
              "evidencia": 2, "status": status, "autor": "Rafael"}
    item = Insight(**(padrao | campos))
    db.add(item)
    db.commit()
    return item


def da_marca(itens: list[dict], marca: str) -> list[dict]:
    """O banco de teste é um só para todos os testes: olhamos só os itens criados aqui."""
    return [i for i in itens if marca in i["titulo"]]


def test_so_os_aprovados_saem_nos_campos_da_base_ficticia():
    marca = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        for s in ["validado", "consolidado", "proposto", "historico_a_validar", "obsoleto"]:
            criar(db, f"{s} {marca}", status=s, data_evento=date(2026, 3, 12))
        itens, _ = exportar_golden.exportar(db)

    meus = da_marca(itens, marca)
    assert sorted(i["titulo"] for i in meus) == [f"Item consolidado {marca}", f"Item validado {marca}"]
    campos_ficticia = list(json.loads(BASE_FICTICIA.read_text(encoding="utf-8"))[0])
    assert all(list(i) == campos_ficticia for i in meus)  # mesmos campos, mesma ordem
    assert meus[0]["data_evento"] == "2026-03-12"


def test_contexto_do_cliente_e_autor_nao_saem():
    marca = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        criar(db, marca, contexto_cliente=f"Rede com 4 hotéis {marca}", autor="Fulano")
        itens, _ = exportar_golden.exportar(db)

    texto = json.dumps(da_marca(itens, marca), ensure_ascii=False)
    assert "Rede com 4 hotéis" not in texto and "Fulano" not in texto


def test_item_com_dado_pessoal_e_pulado_sem_mostrar_o_dado(tmp_path, capsys):
    marca = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        limpo = criar(db, f"limpo {marca}")
        sujo = criar(db, f"sujo {marca}", descricao="Falei com contato@cliente-exemplo.com.br e ele topou.")

    saida = tmp_path / "base_real.json"
    assert exportar_golden.main(["--saida", str(saida)]) == 0

    gravados = da_marca(json.loads(saida.read_text(encoding="utf-8")), marca)
    assert [i["id"] for i in gravados] == [limpo.id]
    erro = capsys.readouterr().err
    assert str(sujo.id) in erro
    assert "contato@cliente-exemplo.com.br" not in erro


def test_o_arquivo_gravado_vira_insight_como_no_golden(tmp_path):
    """O test_golden.py monta Insight(**linha, status=..., autor=..., criado_em=...): o JSON tem que encaixar."""
    marca = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        criar(db, marca, segmento="hotelaria", resultado="4 de 6 aprovadas.", data_evento=date(2026, 1, 5))
    saida = tmp_path / "base_real.json"
    exportar_golden.main(["--saida", str(saida)])

    linha = da_marca(json.loads(saida.read_text(encoding="utf-8")), marca)[0]
    linha["data_evento"] = datetime.strptime(linha["data_evento"], "%Y-%m-%d").date()
    item = Insight(**linha, status="validado", autor="golden", criado_em=datetime(2026, 10, 1))
    assert item.segmento == "hotelaria" and item.data_evento == date(2026, 1, 5)


def test_sem_itens_aprovados_nao_grava_nada(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(exportar_golden, "exportar", lambda db: ([], []))
    saida = tmp_path / "base_real.json"

    assert exportar_golden.main(["--saida", str(saida)]) == 1
    assert not saida.exists()
    assert "nenhum item aprovado" in capsys.readouterr().err
