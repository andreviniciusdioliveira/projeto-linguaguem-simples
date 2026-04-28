"""
Autenticação do painel administrativo.

Estratégia: senha única de admin guardada como hash em variável de ambiente
ADMIN_PASSWORD_HASH (gerado com werkzeug.security.generate_password_hash).
Senha em texto puro nunca toca o servidor.

Sessão Flask normal com cookies httponly + samesite=Lax. Logout automático
após 30 minutos de inatividade. Proteção contra brute-force via tabela
admin_login_attempts (5 tentativas falhas em 15 min bloqueia o IP).

LGPD: nenhum dado pessoal armazenado. IPs viram hash SHA-256 antes de ir
pro banco.
"""

import os
import logging
from functools import wraps
from datetime import datetime, timedelta

from flask import session, redirect, url_for, request, flash, jsonify
from werkzeug.security import check_password_hash

import database

ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH', '').strip()
SESSION_KEY = 'admin_authenticated'
SESSION_TS_KEY = 'admin_authenticated_at'

# Política de segurança
MAX_TENTATIVAS_FALHAS = 5
JANELA_BLOQUEIO_MIN = 15
TIMEOUT_INATIVIDADE_MIN = 30


def admin_configurado():
    """Indica se o painel admin tem senha configurada."""
    return bool(ADMIN_PASSWORD_HASH)


def verificar_senha_admin(senha):
    """
    Confere a senha contra ADMIN_PASSWORD_HASH.
    Retorna False com segurança se a senha não estiver configurada.
    """
    if not ADMIN_PASSWORD_HASH:
        logging.warning('⚠️ Tentativa de login admin sem ADMIN_PASSWORD_HASH configurado')
        return False
    try:
        return check_password_hash(ADMIN_PASSWORD_HASH, senha or '')
    except Exception as e:
        logging.error(f'❌ Erro ao verificar senha admin: {e}')
        return False


def ip_bloqueado(ip_address):
    """Retorna True se o IP excedeu o limite de tentativas falhas na janela."""
    falhas = database.contar_tentativas_login_admin_falhas(ip_address, JANELA_BLOQUEIO_MIN)
    return falhas >= MAX_TENTATIVAS_FALHAS


def sessao_admin_valida():
    """Valida sessão admin: precisa estar autenticada e não estar expirada por inatividade."""
    if not session.get(SESSION_KEY):
        return False
    ts_iso = session.get(SESSION_TS_KEY)
    if not ts_iso:
        return False
    try:
        ts = datetime.fromisoformat(ts_iso)
    except ValueError:
        return False
    if datetime.now() - ts > timedelta(minutes=TIMEOUT_INATIVIDADE_MIN):
        return False
    return True


def renovar_sessao_admin():
    """Atualiza o timestamp de atividade da sessão admin."""
    session[SESSION_TS_KEY] = datetime.now().isoformat()


def autenticar_admin():
    """Marca a sessão como autenticada (chame só após verificar a senha)."""
    session[SESSION_KEY] = True
    session[SESSION_TS_KEY] = datetime.now().isoformat()
    session.permanent = True


def desautenticar_admin():
    """Remove dados de autenticação da sessão."""
    session.pop(SESSION_KEY, None)
    session.pop(SESSION_TS_KEY, None)


def admin_required(view_func):
    """Decorador que protege rotas: redireciona para /admin/login se não autenticado.

    Para rotas de API (que esperam JSON), retorna 401 em vez de redirect.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not sessao_admin_valida():
            desautenticar_admin()
            # Detecta se é chamada AJAX/API pelo Accept ou prefixo de rota
            quer_json = (
                request.path.startswith('/admin/api/')
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in (request.headers.get('Accept') or '')
            )
            if quer_json:
                return jsonify({'erro': 'nao_autenticado', 'mensagem': 'Faça login para acessar.'}), 401
            return redirect(url_for('admin_login_page', next=request.path))
        renovar_sessao_admin()
        return view_func(*args, **kwargs)
    return wrapper
