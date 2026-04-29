"""
Autenticação multi-usuário do painel administrativo (Fase 2).

Mudanças vs Fase 1:
- Login agora exige username + senha
- Usuários ficam na tabela admin_users (papéis: superadmin / viewer)
- ADMIN_PASSWORD_HASH só é usado pra bootstrap inicial: se a tabela
  admin_users estiver vazia na inicialização, é criado o usuário "admin"
  com aquele hash e role=superadmin. Depois disso a env var não é mais
  consultada para autenticação (apenas para criar mais admins manualmente
  via script, se desejar).
- Sessão guarda: user_id, username, role, timestamp de atividade
- Decoradores: admin_required (qualquer logado), superadmin_required
- Helper audit_action() registra eventos críticos sempre, com debounce
  automático para dashboard_view e api_stats

LGPD:
- Senhas só viajam entre cliente e servidor; em repouso só ficam hashes
  (werkzeug.security.generate_password_hash, pbkdf2-sha256 600k iter)
- IPs viram hash SHA-256 antes de irem ao audit log
- Tokens de reset expiram em 24h e são one-time-use
"""

import os
import logging
from functools import wraps
from datetime import datetime, timedelta

from flask import session, redirect, url_for, request, jsonify, abort
from werkzeug.security import check_password_hash

import database

ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH', '').strip()

SESSION_USER_ID = 'admin_user_id'
SESSION_USERNAME = 'admin_username'
SESSION_ROLE = 'admin_role'
SESSION_TS = 'admin_ts'

# Política de segurança
MAX_TENTATIVAS_FALHAS = 5
JANELA_BLOQUEIO_MIN = 15
TIMEOUT_INATIVIDADE_MIN = 30

# Eventos com debounce automático (não inflam o log com polling)
EVENTOS_COM_DEBOUNCE = {'dashboard_view', 'api_stats'}
DEBOUNCE_JANELA_MIN = 5


def admin_configurado():
    """True se há pelo menos 1 superadmin ativo (ou bootstrap disponível)."""
    if database.admin_users_count() > 0:
        return True
    return bool(ADMIN_PASSWORD_HASH)


def bootstrap_se_necessario():
    """Cria usuário admin a partir do env var se admin_users estiver vazia."""
    return database.bootstrap_admin_user_se_vazio(ADMIN_PASSWORD_HASH)


def autenticar(username, senha):
    """
    Verifica credenciais. Retorna o dict do usuário (sem hash) se autenticou,
    None caso contrário.
    """
    user = database.obter_admin_user_por_username(username)
    if not user:
        return None
    if not user.get('ativo'):
        return None
    try:
        if not check_password_hash(user['password_hash'], senha or ''):
            return None
    except Exception as e:
        logging.error(f'❌ Erro ao verificar hash da senha admin: {e}')
        return None
    # Limpa o hash antes de retornar
    return {k: v for k, v in user.items() if k != 'password_hash'}


def ip_bloqueado(ip_address):
    """True se o IP excedeu o limite de tentativas falhas na janela."""
    falhas = database.contar_tentativas_login_admin_falhas(ip_address, JANELA_BLOQUEIO_MIN)
    return falhas >= MAX_TENTATIVAS_FALHAS


def sessao_admin_valida():
    """Sessão admin válida: tem user_id, role, timestamp dentro do timeout."""
    if not session.get(SESSION_USER_ID):
        return False
    ts_iso = session.get(SESSION_TS)
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
    session[SESSION_TS] = datetime.now().isoformat()


def autenticar_sessao(user):
    """Marca a sessão como autenticada com os dados do usuário."""
    session[SESSION_USER_ID] = user['id']
    session[SESSION_USERNAME] = user['username']
    session[SESSION_ROLE] = user['role']
    session[SESSION_TS] = datetime.now().isoformat()
    session.permanent = True


def desautenticar_admin():
    """Remove dados de autenticação da sessão."""
    for key in (SESSION_USER_ID, SESSION_USERNAME, SESSION_ROLE, SESSION_TS):
        session.pop(key, None)


def current_admin_user():
    """Retorna dict do usuário logado (sem hash) ou None."""
    if not sessao_admin_valida():
        return None
    user_id = session.get(SESSION_USER_ID)
    if not user_id:
        return None
    user = database.obter_admin_user_por_id(user_id)
    if not user or not user.get('ativo'):
        return None
    # Sincroniza role da sessão com o banco caso tenha mudado
    if user.get('role') != session.get(SESSION_ROLE):
        session[SESSION_ROLE] = user['role']
    return {k: v for k, v in user.items() if k != 'password_hash'}


def is_superadmin():
    """True se o usuário logado é superadmin."""
    user = current_admin_user()
    return user is not None and user.get('role') == database.ROLE_SUPERADMIN


def audit_action(action, target=None, detalhes=None, sucesso=True, username=None):
    """
    Registra ação no audit log.

    - Eventos em EVENTOS_COM_DEBOUNCE são desduplicados em janela de 5 min
    - Eventos críticos (login, logout, gestão de contas) são sempre gravados
    - username é puxado da sessão se não for passado (útil pra falhas de login)
    """
    if username is None:
        username = session.get(SESSION_USERNAME)
    ip = request.remote_addr if request else None

    if action in EVENTOS_COM_DEBOUNCE and username:
        database.registrar_audit_admin_debounced(
            username=username, action=action, janela_minutos=DEBOUNCE_JANELA_MIN,
            target=target, detalhes=detalhes, ip_address=ip, sucesso=sucesso
        )
    else:
        database.registrar_audit_admin(
            username=username, action=action, target=target,
            detalhes=detalhes, ip_address=ip, sucesso=sucesso
        )


def admin_required(view_func):
    """
    Decorador que protege rotas admin: redireciona para /admin/login se não autenticado.
    Para rotas de API (que esperam JSON), retorna 401 em vez de redirect.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not sessao_admin_valida():
            desautenticar_admin()
            quer_json = (
                request.path.startswith('/admin/api/')
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in (request.headers.get('Accept') or '')
            )
            if quer_json:
                return jsonify({'erro': 'nao_autenticado', 'mensagem': 'Faça login para acessar.'}), 401
            return redirect(url_for('admin_login_page', next=request.path))
        # Verifica se o usuário ainda existe e está ativo
        user = current_admin_user()
        if not user:
            desautenticar_admin()
            return redirect(url_for('admin_login_page'))
        renovar_sessao_admin()
        return view_func(*args, **kwargs)
    return wrapper


def superadmin_required(view_func):
    """Como admin_required, mas exige role=superadmin."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not sessao_admin_valida():
            desautenticar_admin()
            return redirect(url_for('admin_login_page', next=request.path))
        user = current_admin_user()
        if not user:
            desautenticar_admin()
            return redirect(url_for('admin_login_page'))
        if user.get('role') != database.ROLE_SUPERADMIN:
            audit_action('access_denied', target=request.path,
                         detalhes='superadmin_required', sucesso=False)
            abort(403)
        renovar_sessao_admin()
        return view_func(*args, **kwargs)
    return wrapper
