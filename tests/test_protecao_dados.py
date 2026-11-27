"""Testes do módulo protecao_dados (não dependem de Flask nem do Gemini).

Executar:  python -m pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protecao_dados as pd  # noqa: E402
from protecao_dados import MascaradorDados, detectar_segredo_local  # noqa: E402


# ---------- Mascaramento ----------

TEXTO = (
    "Processo nº 0001234-56.2026.8.27.2729. Autor: João da Silva, CPF 123.456.789-09, "
    "RG 1.234.567 SSP/TO, telefone (63) 99999-1234, e-mail joao.silva@example.com, "
    "CEP 77015-007. Ré: Empresa X Ltda, CNPJ 12.345.678/0001-90. "
    "Condeno ao pagamento de R$ 10.000,00 em 15/03/2026."
)


def test_mascara_remove_identificadores():
    m = MascaradorDados(ativo=True)
    mascarado = m.mascarar(TEXTO)
    for valor in ("123.456.789-09", "1.234.567", "99999-1234", "joao.silva@example.com",
                  "77015-007", "12.345.678/0001-90", "0001234-56.2026.8.27.2729"):
        assert valor not in mascarado, valor
    for marcador in ("[CPF_1]", "[RG_1]", "[TELEFONE_1]", "[EMAIL_1]", "[CEP_1]", "[CNPJ_1]", "[PROCESSO_1]"):
        assert marcador in mascarado, marcador


def test_mascara_preserva_valores_datas_e_nomes():
    m = MascaradorDados(ativo=True)
    mascarado = m.mascarar(TEXTO)
    assert "R$ 10.000,00" in mascarado
    assert "15/03/2026" in mascarado
    assert "João da Silva" in mascarado  # nomes não são mascarados (limitação documentada)


def test_ida_e_volta_restaura_o_texto_original():
    m = MascaradorDados(ativo=True)
    assert m.restaurar(m.mascarar(TEXTO)) == TEXTO


def test_mesmo_valor_recebe_mesmo_marcador():
    m = MascaradorDados(ativo=True)
    a = m.mascarar("CPF 123.456.789-09")
    b = m.mascarar("o CPF 123.456.789-09 consta nos autos; outro: 987.654.321-00")
    assert "[CPF_1]" in a and "[CPF_1]" in b and "[CPF_2]" in b


def test_cpf_sem_pontuacao_so_com_rotulo():
    m = MascaradorDados(ativo=True)
    assert "[CPF_1]" in m.mascarar("CPF: 12345678909")
    m2 = MascaradorDados(ativo=True)
    assert m2.mascarar("código 12345678909") == "código 12345678909"


def test_restaurar_tolera_variacoes_do_modelo():
    m = MascaradorDados(ativo=True)
    m.mascarar("CPF 123.456.789-09")
    assert m.restaurar("Seu CPF é [cpf 1].") == "Seu CPF é 123.456.789-09."
    assert m.restaurar("[ CPF_1 ]") == "123.456.789-09"
    assert m.restaurar("[CPF_9]") == "[CPF_9]"  # marcador desconhecido fica como está


def test_restaurar_estrutura_aninhada():
    m = MascaradorDados(ativo=True)
    m.mascarar("CPF 123.456.789-09 e-mail a@b.com")
    dados = {"partes": {"autor": "Fulano ([CPF_1])"}, "emails": ["[EMAIL_1]"], "n": 3, "x": None}
    assert m.restaurar_estrutura(dados) == {
        "partes": {"autor": "Fulano (123.456.789-09)"}, "emails": ["a@b.com"], "n": 3, "x": None,
    }


def test_desativado_nao_altera():
    m = MascaradorDados(ativo=False)
    assert m.mascarar(TEXTO) == TEXTO
    assert m.total() == 0


def test_contagem_nao_expoe_valores():
    m = MascaradorDados(ativo=True)
    m.mascarar(TEXTO)
    assert m.contagem()["CPF"] == 1
    assert m.total() == 7


# ---------- Segredo de justiça ----------

SENTENCA_COMUM = (
    "PODER JUDICIÁRIO DO ESTADO DO TOCANTINS\nSENTENÇA\n"
    "Trata-se de ação de indenização por danos morais movida contra banco. "
    "Ante o exposto, JULGO PROCEDENTE o pedido. Defiro a justiça gratuita."
)


def test_sentenca_comum_nao_bloqueia():
    r = detectar_segredo_local(SENTENCA_COMUM)
    assert r["detectado"] is False and r["indicios"] is False


def test_marcador_explicito_bloqueia():
    r = detectar_segredo_local("SENTENÇA\nProcesso em SEGREDO DE JUSTIÇA.\nJulgo procedente o pedido.")
    assert r["detectado"] is True and r["nivel"] == "explicito"


def test_negacao_nao_bloqueia():
    r = detectar_segredo_local(SENTENCA_COMUM + " O feito não tramita em segredo de justiça.")
    assert r["detectado"] is False
    r = detectar_segredo_local(SENTENCA_COMUM + " Indefiro o pedido de segredo de justiça.")
    assert r["detectado"] is False


def test_materia_de_familia_bloqueia():
    r = detectar_segredo_local("SENTENÇA\nVara de Família de Palmas. Ação de alimentos. Julgo procedente.")
    assert r["detectado"] is True and r["nivel"] == "materia"
    assert "189" in r["hipotese_legal"]


def test_crime_sexual_e_maria_da_penha_bloqueiam():
    assert detectar_segredo_local("SENTENÇA. O réu foi denunciado por estupro de vulnerável.")["detectado"]
    assert detectar_segredo_local("DECISÃO. Defiro medidas protetivas de urgência.")["detectado"]


def test_mandado_procedimental_e_liberado_por_padrao(monkeypatch):
    monkeypatch.setattr(pd, "SEGREDO_PERMITIR_PROCEDIMENTAIS", True)
    texto = "MANDADO DE INTIMAÇÃO\nVara de Família de Palmas\nCompareça à audiência no dia 10/12/2026 às 14h."
    r = detectar_segredo_local(texto)
    assert r["procedimental"] is True and r["indicios"] is True and r["detectado"] is False


def test_mandado_bloqueado_quando_configurado(monkeypatch):
    monkeypatch.setattr(pd, "SEGREDO_PERMITIR_PROCEDIMENTAIS", False)
    texto = "MANDADO DE INTIMAÇÃO\nVara de Família de Palmas\nCompareça à audiência."
    assert detectar_segredo_local(texto)["detectado"] is True


def test_sentenca_que_cita_intimacao_nao_e_procedimental():
    texto = "SENTENÇA\nVara de Família. Após a intimação das partes, julgo procedente o pedido de guarda."
    r = detectar_segredo_local(texto)
    assert r["procedimental"] is False and r["detectado"] is True


def test_motivo_nao_contem_trecho_do_documento():
    r = detectar_segredo_local("SENTENÇA. Ação de divórcio de Maria Fulana contra José Beltrano.")
    assert "Maria" not in (r["motivo"] or "") and "José" not in (r["hipotese_legal"] or "")
