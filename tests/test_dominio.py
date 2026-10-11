"""Testes das regras de negócio (app/dominio.py). O CI exige 100% de cobertura deste módulo."""
import pytest

from app import dominio
from app.dominio import DadoPessoalNaEntrada, EvidenciaInvalida, MotivoObrigatorio, TransicaoInvalida

# --- ciclo de vida -------------------------------------------------------------------------

@pytest.mark.parametrize("de, para", [
    ("proposto", "validado"),
    ("historico_a_validar", "validado"),
    ("validado", "consolidado"),
])
def test_transicoes_validas(de, para):
    dominio.validar_transicao(de, para)  # não levanta nada


@pytest.mark.parametrize("de", ["proposto", "historico_a_validar", "validado", "consolidado"])
def test_todos_podem_virar_obsoleto_com_motivo(de):
    dominio.validar_transicao(de, "obsoleto", motivo="substituído por item mais recente")


@pytest.mark.parametrize("de, para", [
    ("proposto", "consolidado"),   # pulou a validação
    ("validado", "proposto"),      # voltou atrás
    ("consolidado", "validado"),   # voltou atrás
    ("obsoleto", "validado"),      # obsoleto é o fim da linha
    ("proposto", "proposto"),      # "mudar" para o mesmo status
    ("inexistente", "validado"),   # status desconhecido
])
def test_transicoes_invalidas(de, para):
    with pytest.raises(TransicaoInvalida, match=f"'{de}' para '{para}'"):
        dominio.validar_transicao(de, para)


@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_obsoleto_sem_motivo(motivo):
    with pytest.raises(MotivoObrigatorio):
        dominio.validar_transicao("validado", "obsoleto", motivo=motivo)


def test_toda_regra_de_negocio_herda_da_base():
    for erro in (TransicaoInvalida, MotivoObrigatorio, EvidenciaInvalida, DadoPessoalNaEntrada):
        assert issubclass(erro, dominio.RegraDeNegocio)


# --- evidência ------------------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("caiu de 9 para 4 minutos", True),
    ("aumentou 30%", True),
    ("o cliente gostou muito", False),
    ("", False),
    (None, False),
])
def test_tem_numero(texto, esperado):
    assert dominio.tem_numero(texto) is esperado


@pytest.mark.parametrize("tipo, evidencia, resultado", [
    ("aprendizado", 1, None),
    ("regra", 3, None),
    ("regra", 4, "fechou 2 de 3 propostas"),
    ("case", 4, "check-in caiu de 9 para 4 minutos"),
])
def test_insights_validos(tipo, evidencia, resultado):
    dominio.validar_insight(tipo, evidencia, resultado)


@pytest.mark.parametrize("evidencia", [0, 5, -1])
def test_evidencia_fora_da_escala(evidencia):
    with pytest.raises(EvidenciaInvalida, match="vai de 1"):
        dominio.validar_insight("aprendizado", evidencia, None)


@pytest.mark.parametrize("evidencia", [1, 2])
def test_regra_exige_evidencia_3_ou_mais(evidencia):
    with pytest.raises(EvidenciaInvalida, match="virar regra"):
        dominio.validar_insight("regra", evidencia, "qualquer coisa")


@pytest.mark.parametrize("resultado", [None, "", "o cliente adorou"])
def test_evidencia_4_exige_numero(resultado):
    with pytest.raises(EvidenciaInvalida, match="exige um número"):
        dominio.validar_insight("case", 4, resultado)


# --- dados pessoais (LGPD) ----------------------------------------------------------------

@pytest.mark.parametrize("texto, tipo", [
    ("falar com joao.silva@hotelx.com.br amanhã", "e-mail"),
    ("CPF do decisor: 123.456.789-09", "CPF"),
    ("cpf 12345678909 no cadastro", "CPF"),
    ("CNPJ 12.345.678/0001-90", "CNPJ"),
    ("ligar no (81) 99876-5432", "telefone"),
    ("whats 81 3456-7890", "telefone"),
])
def test_detecta_dado_pessoal(texto, tipo):
    avisos = dominio.detectar_dados_pessoais(descricao=texto)
    assert any(f"Possível {tipo} em 'descricao'" in a for a in avisos)


@pytest.mark.parametrize("texto", [
    "o check-in caiu de 9 para 4 minutos",
    "reunião em 2026-03-12 com a rede",
    "proposta de R$ 15.000 em 3 parcelas",
    "aumentou 30% em 2025",
])
def test_nao_acusa_numeros_comuns(texto):
    assert dominio.detectar_dados_pessoais(descricao=texto) == []


def test_aviso_nao_repete_o_dado_e_indica_o_campo():
    avisos = dominio.detectar_dados_pessoais(descricao="ok", contexto_cliente="email: ana@cliente.com")
    assert avisos == [
        "Possível e-mail em 'contexto_cliente': dado pessoal de cliente não deve entrar na base (LGPD)."
    ]
    assert "ana@cliente.com" not in avisos[0]


def test_campos_vazios_nao_geram_aviso():
    assert dominio.detectar_dados_pessoais(descricao=None, contexto_cliente="") == []


# --- dado pessoal que BLOQUEIA (antes de o texto ir ao modelo) ---------------------------------

def test_exigir_sem_dados_pessoais_deixa_passar_texto_limpo():
    dominio.exigir_sem_dados_pessoais(texto="o check-in caiu de 9 para 4 minutos", vazio=None)


def test_exigir_sem_dados_pessoais_barra_e_explica_sem_repetir_o_dado():
    with pytest.raises(DadoPessoalNaEntrada) as e:
        dominio.exigir_sem_dados_pessoais(
            texto="falar com ana@cliente.com",
            **{"relato anterior 1": "ligar (81) 99876-5432"},
        )

    mensagem = str(e.value)
    assert "e-mail em 'texto'" in mensagem
    assert "telefone em 'relato anterior 1'" in mensagem
    assert "Nada foi enviado ao modelo" in mensagem
    assert "ana@cliente.com" not in mensagem and "99876" not in mensagem


# --- segmento -------------------------------------------------------------------------------

@pytest.mark.parametrize("entrada, esperado", [
    ("saude", "saúde"),
    ("saúde", "saúde"),
    ("  SAÚDE ", "saúde"),
    ("Educacao", "educação"),
    ("industria", "indústria"),
    ("Setor   Publico", "setor público"),
    ("hotelaria", "hotelaria"),
    ("Padaria Artesanal", "padaria artesanal"),  # fora da lista: continua livre, só arrumado
    ("  Logística ", "logística"),
    ("", ""),
])
def test_normalizar_segmento(entrada, esperado):
    assert dominio.normalizar_segmento(entrada) == esperado


def test_normalizar_segmento_e_idempotente():
    for s in [*dominio.SEGMENTOS_CONHECIDOS, "saude", "Padaria  Nova"]:
        uma_vez = dominio.normalizar_segmento(s)
        assert dominio.normalizar_segmento(uma_vez) == uma_vez

