"""Testes do módulo protecao_dados (não dependem de Flask nem do Gemini).

Executar:  python -m pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protecao_dados import MascaradorDados  # noqa: E402


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
