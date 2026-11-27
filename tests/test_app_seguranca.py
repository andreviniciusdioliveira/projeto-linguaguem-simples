"""Testes de integração da aplicação com um Gemini simulado (sem rede, sem chave).

Cobrem as correções de segurança e a proteção de dados antes do envio à IA.
Precisam das dependências do requirements.txt; sem elas, são pulados.

Executar:  python -m pytest tests/
"""
import io
import json
import os
import re
import sys
import tempfile

import pytest

pytest.importorskip("flask")
pytest.importorskip("fitz")
pytest.importorskip("google.genai")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Ambiente isolado ANTES de importar a aplicação: nada é gravado na pasta do projeto.
_DIR_DADOS = tempfile.mkdtemp(prefix="entenda-aqui-teste-")
os.environ["DATA_DIR"] = _DIR_DADOS
os.environ["FLASK_ENV"] = "development"
os.environ["SECRET_KEY"] = "chave-somente-para-testes"
os.environ["ADMIN_TOKEN"] = "token-de-teste-123"
os.environ.pop("DATABASE_PATH", None)
os.environ.pop("TRUSTED_PROXIES", None)

import database  # noqa: E402
import app as aplicacao  # noqa: E402

DOC = (
    "PODER JUDICIÁRIO DO ESTADO DO TOCANTINS\nSENTENÇA\nProcesso nº 0001234-56.2026.8.27.2729\n"
    "Autor: João da Silva, CPF 123.456.789-09, telefone (63) 99999-1234, e-mail joao@example.com.\n"
    "Réu: Banco X S.A., CNPJ 12.345.678/0001-90.\nTrata-se de ação de indenização por danos morais.\n"
    "Ante o exposto, JULGO PROCEDENTE o pedido para condenar o réu a pagar R$ 10.000,00.\nP.R.I."
)
SENSIVEIS = ["123.456.789-09", "99999-1234", "joao@example.com", "12.345.678/0001-90", "0001234-56.2026.8.27.2729"]


def cpf_valido(base9):
    d = [int(x) for x in base9]
    for n in (10, 11):
        resto = sum(v * (n - i) for i, v in enumerate(d)) % 11
        d.append(0 if resto < 2 else 11 - resto)
    return "".join(map(str, d))


class _Resposta:
    usage_metadata = None

    def __init__(self, text):
        self.text = text


class _ModelosFalsos:
    def __init__(self, enviados):
        self.enviados = enviados

    def generate_content(self, model, contents, config=None):
        self.enviados.append(contents)
        if "FORMATO DE RESPOSTA" not in contents:  # chat
            return _Resposta("O CPF do autor é [CPF_1] e o processo é [PROCESSO_1].")
        dados = {
            "tipo_documento": "sentenca", "confianca_tipo": "ALTA",
            "segredo_justica": {"detectado": False}, "numero_processo": "[PROCESSO_1]",
            "partes": {"autor": "João da Silva (CPF [CPF_1])", "reu": "Banco X ([CNPJ_1])"},
            "valores_principais": {"total_a_receber": "R$ 10.000,00"},
        }
        return _Resposta(
            "```json\n" + json.dumps(dados, ensure_ascii=False) + "\n```\n---SEPARADOR---\n"
            "Você ganhou a causa. O banco [CNPJ_1] deve pagar R$ 10.000,00. "
            "Seu CPF [CPF_1] consta no processo [PROCESSO_1]."
        )


class _ClienteFalso:
    def __init__(self, enviados):
        self.models = _ModelosFalsos(enviados)


@pytest.fixture()
def ctx(monkeypatch, tmp_path):
    """Cliente HTTP com sessão e token CSRF, Gemini simulado, limites por minuto zerados
    e pasta temporária própria (sem reaproveitar áudio ou PDF de execuções anteriores)."""
    enviados = []
    monkeypatch.setattr(aplicacao, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(aplicacao, "gemini_client", _ClienteFalso(enviados))
    aplicacao.request_counts.clear()
    aplicacao.results_cache.clear()
    cliente = aplicacao.app.test_client()
    html = cliente.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    class Ctx:
        pass

    c = Ctx()
    c.cliente, c.cab, c.enviados, c.html = cliente, {"X-CSRF-Token": token}, enviados, html
    return c


def _simplificar(ctx, cpf, texto=DOC):
    return ctx.cliente.post("/processar_texto", json={"texto": texto, "cpf": cpf, "perspectiva": "autor"},
                            headers=ctx.cab)


# ---------- Proteção de dados antes da IA ----------

def test_analise_mascara_na_ida_e_restaura_na_volta(ctx):
    r = _simplificar(ctx, cpf_valido("529982247"))
    d = r.get_json()
    assert r.status_code == 200, d
    prompt = ctx.enviados[-1]
    for valor in SENSIVEIS:
        assert valor not in prompt, f"dado pessoal enviado à IA: {valor}"
    assert "[CPF_1]" in prompt and "[PROCESSO_1]" in prompt
    assert "123.456.789-09" in d["texto"] and "0001234-56.2026.8.27.2729" in d["texto"]
    assert not re.search(r"\[(CPF|CNPJ|PROCESSO|EMAIL|TELEFONE)_\d+\]", json.dumps(d, ensure_ascii=False))


def test_chat_mascara_e_restaura(ctx):
    assert _simplificar(ctx, cpf_valido("111444777")).status_code == 200
    r = ctx.cliente.post("/chat", json={"pergunta": "Qual o meu CPF 123.456.789-09?"}, headers=ctx.cab)
    assert r.status_code == 200, r.get_json()
    for valor in SENSIVEIS:
        assert valor not in ctx.enviados[-1]
    assert r.get_json()["resposta"] == "O CPF do autor é 123.456.789-09 e o processo é 0001234-56.2026.8.27.2729."


def test_documento_sigiloso_nao_e_enviado(ctx):
    sigiloso = DOC.replace("ação de indenização por danos morais", "ação de alimentos, em segredo de justiça")
    r = _simplificar(ctx, cpf_valido("222333444"), sigiloso)
    d = r.get_json()
    assert r.status_code == 200 and d["segredo_justica"]["detectado"] is True
    assert d["modelo_usado"] == "pre-validacao-local"
    assert ctx.enviados == [], "documento sigiloso chegou à IA"
    assert "João" not in json.dumps(d, ensure_ascii=False)


def test_pdf_sigiloso_nao_e_enviado(ctx):
    import fitz
    pdf = fitz.open()
    pdf.new_page().insert_text((50, 72), "SENTENCA\nVara de Familia de Palmas\nAcao de divorcio. Julgo procedente.",
                               fontsize=11)
    r = ctx.cliente.post(
        "/processar", headers=ctx.cab, content_type="multipart/form-data",
        data={"file": (io.BytesIO(pdf.tobytes()), "s.pdf"), "cpf": cpf_valido("333444555"), "perspectiva": "autor"},
    )
    assert r.status_code == 200 and r.get_json()["segredo_justica"]["detectado"] is True
    assert ctx.enviados == []


def test_aviso_de_ia_e_identificacao_do_modelo(ctx):
    assert "Este serviço usa inteligência artificial" in ctx.html
    assert "Sobre a inteligência artificial" in ctx.html
    info = ctx.cliente.get("/api/ia-info").get_json()
    assert info["modelo_principal"] and info["atualizado_em"]


# ---------- Correções de segurança ----------

def test_banco_e_segredos_ficam_no_diretorio_de_dados():
    assert os.path.dirname(database.DB_PATH) == _DIR_DADOS
    assert os.path.exists(database.DB_PATH)
    assert "default" not in database.IP_HASH_SALT and len(database.IP_HASH_SALT) >= 32
    assert database.IP_HASH_SALT != database.CPF_HASH_SALT
    assert os.path.exists(os.path.join(_DIR_DADOS, ".ip_hash_salt"))


def test_hash_de_cpf_nao_e_o_sha256_simples_do_valor_antigo():
    import hashlib
    antigo = hashlib.sha256("entenda-aqui-cpf-vault-2024-default:12345678909".encode()).hexdigest()
    assert database.gerar_hash_cpf("12345678909") != antigo
    assert database.gerar_hash_cpf("12345678909") == database.gerar_hash_cpf("12345678909")


def test_texto_colado_respeita_limite_por_cpf_e_ip(ctx):
    cpf = cpf_valido("444555666")
    for _ in range(database.CPF_IP_DAILY_LIMIT):
        assert _simplificar(ctx, cpf).status_code == 200
    aplicacao.request_counts.clear()
    r = _simplificar(ctx, cpf)
    assert r.status_code == 429 and r.get_json().get("cpf_ip_limit") is True


def test_narracao_exige_documento_simplificado_na_sessao(ctx):
    r = ctx.cliente.post("/narrar", json={"texto": "texto livre qualquer"}, headers=ctx.cab)
    if r.status_code == 503:
        pytest.skip("edge-tts não instalado")
    assert r.status_code == 403 and r.get_json()["fallback"] == "web_speech"


def test_narracao_usa_o_texto_do_servidor_e_ignora_o_do_cliente(ctx, monkeypatch):
    if not aplicacao.TTS_AVAILABLE:
        pytest.skip("edge-tts não instalado")
    narrados = []

    def tts_falso(texto, voz, caminho):
        narrados.append(texto)
        with open(caminho, "wb") as f:
            f.write(b"ID3fake")

    monkeypatch.setattr(aplicacao, "_gerar_audio_edge_tts", tts_falso)
    monkeypatch.setattr(aplicacao, "_gerar_audio_google_tts", tts_falso)
    assert _simplificar(ctx, cpf_valido("555666777")).status_code == 200
    r = ctx.cliente.post("/narrar", json={"texto": "TEXTO INJETADO PELO CLIENTE"}, headers=ctx.cab)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert narrados and "INJETADO" not in narrados[0] and "ganhou a causa" in narrados[0]


def test_auditoria_legada_nao_aceita_token_na_url(ctx):
    assert ctx.cliente.get("/admin/auditoria?token=token-de-teste-123").status_code == 403
    assert ctx.cliente.get("/admin/auditoria", headers={"Authorization": "Bearer errado"}).status_code == 403
    assert ctx.cliente.get("/admin/auditoria", headers={"Authorization": "Bearer tökén"}).status_code == 403
    ok = ctx.cliente.get("/admin/auditoria", headers={"Authorization": "Bearer token-de-teste-123"})
    assert ok.status_code == 200 and ok.get_json()["sucesso"] is True


def test_requisicao_acima_do_limite_e_recusada(ctx):
    grande = b"%PDF-" + b"0" * (13 * 1024 * 1024)
    r = ctx.cliente.post(
        "/processar", headers=ctx.cab, content_type="multipart/form-data",
        data={"file": (io.BytesIO(grande), "g.pdf"), "cpf": cpf_valido("666777888"), "perspectiva": "autor"},
    )
    assert r.status_code == 413 and "erro" in r.get_json()


def test_pdf_com_paginas_demais_e_recusado(ctx, monkeypatch):
    import fitz
    monkeypatch.setattr(aplicacao, "MAX_PAGINAS_PDF", 3)
    pdf = fitz.open()
    for _ in range(5):
        pdf.new_page().insert_text((50, 72), "SENTENCA. Julgo procedente o pedido.", fontsize=11)
    with pytest.raises(ValueError):
        aplicacao.extrair_texto_pdf(pdf.tobytes())


def test_arquivos_temporarios_levam_a_sessao_no_nome(ctx):
    r = _simplificar(ctx, cpf_valido("777888999"))
    assert r.status_code == 200
    with ctx.cliente.session_transaction() as sessao:
        sid8 = sessao["session_id"][:8]
        assert sid8 in os.path.basename(sessao["texto_original_path"])
        assert sid8 in os.path.basename(sessao["pdf_path"])


def test_link_de_reset_nao_vai_para_a_url(ctx):
    from werkzeug.security import generate_password_hash
    try:
        database.criar_admin_user("raiz", generate_password_hash("senha-de-teste-123"),
                                  role=database.ROLE_SUPERADMIN, criado_por="teste")
    except ValueError:
        pass
    csrf = ctx.cab["X-CSRF-Token"]
    r = ctx.cliente.post("/admin/login", data={"csrf_token": csrf, "username": "raiz", "senha": "senha-de-teste-123"})
    assert r.status_code == 302
    uid = database.obter_admin_user_por_username("raiz")["id"]
    r = ctx.cliente.post(f"/admin/usuarios/{uid}/reset", data={"csrf_token": csrf})
    assert r.status_code == 302
    assert "reset_link" not in r.headers["Location"] and "/admin/reset/" not in r.headers["Location"]
    pagina = ctx.cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "/admin/reset/" in pagina  # exibido uma única vez, a partir da sessão
    assert "/admin/reset/" not in ctx.cliente.get("/admin/usuarios").get_data(as_text=True)


def test_proxyfix_so_com_configuracao_explicita():
    assert aplicacao.TRUSTED_PROXIES == 0
    r = aplicacao.app.test_client().get("/health", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200
