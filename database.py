"""
Sistema de estatísticas agregadas para o Entenda Aqui
LGPD COMPLIANT - Armazena APENAS contadores e hashes, ZERO dados de documentos
Inclui auditoria de IP para administração (sem conteúdo de documentos)
Inclui cofre criptografado de CPF (apagado diariamente) e controle de tokens
"""
import sqlite3
import os
import logging
import hashlib
import secrets
from datetime import datetime, timedelta
from threading import Lock, Thread, Event
import time
import hmac
import base64

# Criptografia para cofre de CPF
try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("⚠️ cryptography não disponível - cofre de CPF desabilitado")

# Lock para operações thread-safe
db_lock = Lock()

# Caminho do banco (persistente, não em TEMP_DIR para não perder dados)
DB_PATH = os.path.join(os.path.dirname(__file__), 'stats.db')

# === CONFIGURAÇÕES DE LIMITE DE TOKENS ===
# Limite diário: 171.6 milhões de tokens
DAILY_TOKEN_LIMIT = 171_600_000

# === CONFIGURAÇÕES DO COFRE DE CPF ===
# Chave de criptografia do cofre (deve ser definida como variável de ambiente)
CPF_VAULT_KEY = os.getenv("CPF_VAULT_KEY", "")
# Limite de documentos por CPF por dia
CPF_DAILY_LIMIT = 5
# Sub-limite por combinação (CPF, IP) — dificulta uso do mesmo CPF via botnet
CPF_IP_DAILY_LIMIT = 3
# Sub-limite por IP único — dificulta abuso com muitos CPFs diferentes do mesmo IP
IP_DAILY_LIMIT = 20

# Salts para hashing (DEVEM ser definidos como variáveis de ambiente em produção)
IP_HASH_SALT = os.getenv("IP_HASH_SALT", "entenda-aqui-tjto-2024-default")
CPF_HASH_SALT = os.getenv("CPF_HASH_SALT", "entenda-aqui-cpf-vault-2024-default")

# Inicializar Fernet se chave disponível
_fernet = None
if CRYPTO_AVAILABLE and CPF_VAULT_KEY:
    try:
        # Derivar chave Fernet de 32 bytes a partir da chave fornecida
        key_bytes = hashlib.sha256(CPF_VAULT_KEY.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        _fernet = Fernet(fernet_key)
        logging.info("🔐 Cofre de CPF inicializado com criptografia Fernet")
    except Exception as e:
        logging.error(f"❌ Erro ao inicializar cofre de CPF: {e}")
        _fernet = None
elif CRYPTO_AVAILABLE and not CPF_VAULT_KEY:
    # Gerar chave temporária (dados perdidos ao reiniciar - aceitável pois limpeza é diária)
    key_bytes = hashlib.sha256(secrets.token_bytes(32)).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    _fernet = Fernet(fernet_key)
    logging.warning("⚠️ CPF_VAULT_KEY não configurada - usando chave temporária (dados perdidos ao reiniciar)")

def init_db():
    """Inicializa banco de dados com tabelas de estatísticas.

    Usa retry com backoff exponencial para sobreviver a "database is locked"
    durante deploys do Render (container antigo ainda segura o lock por
    alguns segundos enquanto o novo sobe).
    """
    tentativas_max = 5
    for tentativa in range(1, tentativas_max + 1):
        try:
            _init_db_inner()
            return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if 'locked' in msg and tentativa < tentativas_max:
                espera_s = 2 ** (tentativa - 1)  # 1, 2, 4, 8s
                logging.warning(
                    f"⏳ init_db: tentativa {tentativa}/{tentativas_max} falhou "
                    f"(database is locked) — aguardando {espera_s}s..."
                )
                time.sleep(espera_s)
                continue
            raise


def _init_db_inner():
    """Implementação real de init_db. Chamada com retry pelo wrapper."""
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # busy_timeout = 30s: SQLite faz polling interno em vez
            # de retornar "database is locked" imediatamente
            cursor.execute('PRAGMA busy_timeout = 30000')

            # Ativar WAL mode para melhor concorrência entre processos
            cursor.execute('PRAGMA journal_mode=WAL')

            # Tabela de estatísticas gerais
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats_geral (
                    id INTEGER PRIMARY KEY,
                    total_documentos INTEGER DEFAULT 0,
                    data_inicio TEXT,
                    ultima_atualizacao TEXT
                )
            ''')

            # Tabela de estatísticas por tipo (APENAS contadores)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats_por_tipo (
                    tipo TEXT PRIMARY KEY,
                    quantidade INTEGER DEFAULT 0
                )
            ''')

            # Tabela de estatísticas diárias (para "documentos processados hoje")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats_diarias (
                    data TEXT PRIMARY KEY,
                    quantidade INTEGER DEFAULT 0
                )
            ''')

            # Tabela de feedback (LGPD compliant - só contadores)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats_feedback (
                    tipo TEXT PRIMARY KEY,
                    quantidade INTEGER DEFAULT 0
                )
            ''')

            # Tabela de validação de documentos (LGPD compliant)
            # Armazena APENAS: ID, hash do conteúdo (não o conteúdo), hash do IP (não o IP)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS validacao_documentos (
                    doc_id TEXT PRIMARY KEY,
                    hash_conteudo TEXT NOT NULL,
                    ip_hash TEXT NOT NULL,
                    tipo_documento TEXT,
                    data_criacao TEXT NOT NULL,
                    data_expiracao TEXT NOT NULL
                )
            ''')

            # Tabela de auditoria (LGPD compliant - apenas hashes)
            # Migração: se tabela antiga existe com ip_address, recriar com ip_hash
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_ip'")
            if cursor.fetchone():
                # Verificar se precisa migrar (coluna antiga ip_address)
                cursor.execute('PRAGMA table_info(audit_ip)')
                colunas = [col[1] for col in cursor.fetchall()]
                if 'ip_address' in colunas:
                    logging.info("🔄 Migrando tabela audit_ip: removendo dados com IP real (LGPD)")
                    cursor.execute('DROP TABLE audit_ip')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_ip (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_hash TEXT NOT NULL,
                    tipo_documento TEXT NOT NULL,
                    nome_arquivo_hash TEXT,
                    tamanho_bytes INTEGER,
                    modelo_usado TEXT,
                    data_processamento TEXT NOT NULL
                )
            ''')

            # Migração aditiva: campos para o painel de admin (tempo, tentativa, sucesso, hora, tokens)
            # Adicionados via ALTER TABLE para preservar dados de instalações antigas
            cursor.execute('PRAGMA table_info(audit_ip)')
            colunas_audit = {col[1] for col in cursor.fetchall()}
            if 'tempo_ms' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN tempo_ms INTEGER')
            if 'tentativa_numero' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN tentativa_numero INTEGER DEFAULT 1')
            if 'sucesso' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN sucesso INTEGER DEFAULT 1')
            if 'hora_dia' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN hora_dia INTEGER')
            if 'tokens_input' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN tokens_input INTEGER DEFAULT 0')
            if 'tokens_output' not in colunas_audit:
                cursor.execute('ALTER TABLE audit_ip ADD COLUMN tokens_output INTEGER DEFAULT 0')

            # Índices para acelerar consultas do painel de admin
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_data ON audit_ip(data_processamento)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_modelo ON audit_ip(modelo_usado)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_hora ON audit_ip(hora_dia)')

            # === TABELA DE TENTATIVAS DE LOGIN DO ADMIN (proteção brute-force) ===
            # Mantém apenas hash do IP (LGPD) e timestamp; limpa após 24h
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_login_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    sucesso INTEGER NOT NULL DEFAULT 0
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_ip_ts ON admin_login_attempts(ip_hash, timestamp)')

            # === TABELA DE USO DIÁRIO DE TOKENS ===
            # Controla o consumo de tokens da API Gemini por dia
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS token_usage_diario (
                    data TEXT PRIMARY KEY,
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    tokens_total INTEGER DEFAULT 0,
                    requisicoes INTEGER DEFAULT 0,
                    ultima_atualizacao TEXT
                )
            ''')

            # === COFRE CRIPTOGRAFADO DE CPF (LGPD) ===
            # CPFs criptografados com Fernet - apagados diariamente
            # Hash SHA-256 para lookup rápido sem descriptografar
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cpf_vault (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cpf_hash TEXT NOT NULL,
                    cpf_encrypted TEXT NOT NULL,
                    data_registro TEXT NOT NULL,
                    ip_hash TEXT
                )
            ''')

            # === CONTROLE DE USO POR CPF ===
            # Rate limiting por CPF (máximo X documentos por dia)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cpf_rate_limit (
                    cpf_hash TEXT NOT NULL,
                    data TEXT NOT NULL,
                    contagem INTEGER DEFAULT 0,
                    PRIMARY KEY (cpf_hash, data)
                )
            ''')

            # === RATE LIMIT COMBINADO CPF + IP ===
            # Anti-abuso: mesmo CPF usado de múltiplos IPs (botnet) é bloqueado mais cedo.
            # Cada par (CPF, IP) recebe um sub-limite diário.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cpf_ip_rate_limit (
                    cpf_hash TEXT NOT NULL,
                    ip_hash TEXT NOT NULL,
                    data TEXT NOT NULL,
                    contagem INTEGER DEFAULT 0,
                    PRIMARY KEY (cpf_hash, ip_hash, data)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_cpf_ip_data ON cpf_ip_rate_limit(data)
            ''')

            # Inserir registro inicial se não existir
            cursor.execute('SELECT COUNT(*) FROM stats_geral')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO stats_geral (id, total_documentos, data_inicio, ultima_atualizacao)
                    VALUES (1, 0, ?, ?)
                ''', (datetime.now().isoformat(), datetime.now().isoformat()))

            conn.commit()
        finally:
            conn.close()
        logging.info("✅ Database de estatísticas inicializado")

def incrementar_documento(tipo_documento):
    """
    Incrementa contadores ao processar documento
    LGPD: Armazena APENAS contadores agregados, sem dados do documento

    Args:
        tipo_documento: 'mandado', 'sentenca', 'acordao', etc
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Incrementar total geral
            cursor.execute('''
                UPDATE stats_geral
                SET total_documentos = total_documentos + 1,
                    ultima_atualizacao = ?
                WHERE id = 1
            ''', (datetime.now().isoformat(),))

            # Incrementar por tipo
            cursor.execute('''
                INSERT INTO stats_por_tipo (tipo, quantidade) VALUES (?, 1)
                ON CONFLICT(tipo) DO UPDATE SET quantidade = quantidade + 1
            ''', (tipo_documento,))

            # Incrementar contador diário
            hoje = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                INSERT INTO stats_diarias (data, quantidade) VALUES (?, 1)
                ON CONFLICT(data) DO UPDATE SET quantidade = quantidade + 1
            ''', (hoje,))

            # Buscar novo total
            cursor.execute('SELECT total_documentos FROM stats_geral WHERE id = 1')
            total = cursor.fetchone()[0]

            conn.commit()
        finally:
            conn.close()

        logging.info(f"📊 Estatísticas atualizadas: Total={total}, Tipo={tipo_documento}")
        return total

def incrementar_feedback(tipo_feedback):
    """
    Incrementa contadores de feedback
    LGPD: Armazena APENAS contadores agregados, sem dados do usuário

    Args:
        tipo_feedback: 'positivo' ou 'negativo'
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Incrementar contador de feedback
            cursor.execute('''
                INSERT INTO stats_feedback (tipo, quantidade) VALUES (?, 1)
                ON CONFLICT(tipo) DO UPDATE SET quantidade = quantidade + 1
            ''', (tipo_feedback,))

            # Buscar novo total
            cursor.execute('SELECT quantidade FROM stats_feedback WHERE tipo = ?', (tipo_feedback,))
            total = cursor.fetchone()[0]

            conn.commit()
        finally:
            conn.close()

        logging.info(f"👍👎 Feedback registrado: {tipo_feedback} (Total: {total})")
        return total

def get_estatisticas():
    """
    Retorna estatísticas agregadas para exibição
    LGPD: Apenas números, sem dados identificáveis
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Total geral
            cursor.execute('SELECT total_documentos, data_inicio FROM stats_geral WHERE id = 1')
            row = cursor.fetchone()
            total_documentos = row[0] if row else 0
            data_inicio = row[1] if row else None

            # Documentos hoje
            hoje = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('SELECT quantidade FROM stats_diarias WHERE data = ?', (hoje,))
            row = cursor.fetchone()
            documentos_hoje = row[0] if row else 0

            # Por tipo
            cursor.execute('SELECT tipo, quantidade FROM stats_por_tipo ORDER BY quantidade DESC')
            por_tipo = {row[0]: row[1] for row in cursor.fetchall()}

            # Tipo mais comum
            tipo_mais_comum = max(por_tipo.items(), key=lambda x: x[1])[0] if por_tipo else None

            # Feedback
            cursor.execute('SELECT tipo, quantidade FROM stats_feedback')
            feedback_stats = {row[0]: row[1] for row in cursor.fetchall()}
            total_feedback = sum(feedback_stats.values())
            feedback_positivo = feedback_stats.get('positivo', 0)
            feedback_negativo = feedback_stats.get('negativo', 0)
            taxa_satisfacao = int((feedback_positivo / total_feedback * 100)) if total_feedback > 0 else 0

            # Calcular milestone atual
            milestones = [
                {'valor': 100, 'nome': 'Bronze', 'emoji': '🥉'},
                {'valor': 1000, 'nome': 'Prata', 'emoji': '🥈'},
                {'valor': 10000, 'nome': 'Ouro', 'emoji': '🥇'},
                {'valor': 100000, 'nome': 'Diamante', 'emoji': '💎'},
            ]

            milestone_atual = None
            proximo_milestone = None
            progresso_percentual = 0

            for m in milestones:
                if total_documentos >= m['valor']:
                    milestone_atual = m
                elif proximo_milestone is None:
                    proximo_milestone = m
                    if milestone_atual:
                        # Calcular progresso entre milestones
                        anterior = milestone_atual['valor']
                        proximo = proximo_milestone['valor']
                        progresso_percentual = int(((total_documentos - anterior) / (proximo - anterior)) * 100)
                    else:
                        # Progresso até primeiro milestone
                        progresso_percentual = int((total_documentos / proximo_milestone['valor']) * 100)
                    break
        finally:
            conn.close()

        stats = {
            'total_documentos': total_documentos,
            'documentos_hoje': documentos_hoje,
            'por_tipo': por_tipo,
            'tipo_mais_comum': tipo_mais_comum,
            'milestone_atual': milestone_atual,
            'proximo_milestone': proximo_milestone,
            'progresso_percentual': progresso_percentual,
            'data_inicio': data_inicio,
            'feedback': {
                'total': total_feedback,
                'positivo': feedback_positivo,
                'negativo': feedback_negativo,
                'taxa_satisfacao': taxa_satisfacao
            }
        }

        return stats

def gerar_doc_id():
    """
    Gera ID único para documento simplificado
    Formato: TJTO-YYYYMMDD-XXXXXXXX (8 hex aleatórios)
    """
    data = datetime.now().strftime('%Y%m%d')
    random_hex = secrets.token_hex(4).upper()
    return f"TJTO-{data}-{random_hex}"


def gerar_hash_conteudo(texto):
    """
    Gera hash SHA-256 do conteúdo simplificado
    LGPD: Armazena o hash, NUNCA o conteúdo original
    O hash é irreversível - impossível reconstruir o documento
    """
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def gerar_hash_ip(ip_address):
    """
    Gera hash SHA-256 do endereço IP com salt
    LGPD: O IP real NUNCA é armazenado, apenas seu hash
    O salt impede ataques de força bruta contra IPs conhecidos
    """
    return hashlib.sha256(f"{IP_HASH_SALT}:{ip_address}".encode('utf-8')).hexdigest()


def registrar_validacao(doc_id, hash_conteudo, ip_hash, tipo_documento):
    """
    Registra documento para validação futura
    LGPD COMPLIANT: Armazena APENAS hashes e metadados mínimos

    Args:
        doc_id: Identificador único do documento (TJTO-YYYYMMDD-XXXXXXXX)
        hash_conteudo: SHA-256 do texto simplificado
        ip_hash: SHA-256 do IP (anonimizado)
        tipo_documento: Tipo do documento (sentença, mandado, etc.)
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            agora = datetime.now()
            expiracao = agora + timedelta(days=30)

            cursor.execute('''
                INSERT INTO validacao_documentos
                (doc_id, hash_conteudo, ip_hash, tipo_documento, data_criacao, data_expiracao)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                doc_id,
                hash_conteudo,
                ip_hash,
                tipo_documento,
                agora.isoformat(),
                expiracao.isoformat()
            ))

            conn.commit()
        finally:
            conn.close()

        logging.info(f"🔐 Validação registrada: {doc_id} (tipo: {tipo_documento})")
        return doc_id


def buscar_validacao(doc_id):
    """
    Busca dados de validação de um documento
    Retorna None se não encontrado ou expirado

    Args:
        doc_id: Identificador único do documento
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT doc_id, hash_conteudo, ip_hash, tipo_documento, data_criacao, data_expiracao
                FROM validacao_documentos
                WHERE doc_id = ?
            ''', (doc_id,))

            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        return {
            'doc_id': row[0],
            'hash_conteudo': row[1],
            'ip_hash': row[2],
            'tipo_documento': row[3],
            'data_criacao': row[4],
            'data_expiracao': row[5]
        }


def limpar_validacoes_expiradas():
    """
    Remove registros de validação expirados (mais de 30 dias)
    LGPD: Não mantém dados desnecessariamente
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                DELETE FROM validacao_documentos
                WHERE datetime(data_expiracao) < datetime('now')
            ''')

            deletados = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        if deletados > 0:
            logging.info(f"🗑️ LGPD: Removidos {deletados} registros de validação expirados")

        return deletados


def registrar_auditoria_ip(ip_address, tipo_documento, nome_arquivo=None, tamanho_bytes=None,
                           modelo_usado=None, tempo_ms=None, tentativa_numero=1, sucesso=True,
                           tokens_input=0, tokens_output=0):
    """
    Registra auditoria de processamento (LGPD compliant).
    Armazena APENAS hashes - NUNCA dados identificáveis.

    Args:
        tempo_ms: Tempo total de processamento em milissegundos (para métricas).
        tentativa_numero: Posição do modelo Gemini na cadeia de fallback que respondeu
                         (1=primário, 2=primeiro fallback, etc). Útil pra detectar
                         degradação do modelo principal.
        sucesso: Se o processamento terminou com sucesso (False conta como erro nas
                métricas do dashboard).
        tokens_input/tokens_output: Tokens de entrada/saída desta simplificação.
                                    Usados para cálculo de custo no painel admin.
    """
    ip_hash = gerar_hash_ip(ip_address) if ip_address else "unknown"
    nome_hash = hashlib.sha256(nome_arquivo.encode('utf-8')).hexdigest()[:16] if nome_arquivo else None
    agora = datetime.now()

    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO audit_ip (ip_hash, tipo_documento, nome_arquivo_hash, tamanho_bytes,
                                      modelo_usado, data_processamento, tempo_ms,
                                      tentativa_numero, sucesso, hora_dia,
                                      tokens_input, tokens_output)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ip_hash,
                tipo_documento,
                nome_hash,
                tamanho_bytes,
                modelo_usado,
                agora.isoformat(),
                tempo_ms,
                tentativa_numero,
                1 if sucesso else 0,
                agora.hour,
                tokens_input or 0,
                tokens_output or 0,
            ))

            conn.commit()
        except Exception as e:
            logging.error(f"❌ Erro ao registrar auditoria: {e}")
        finally:
            conn.close()

    logging.info(
        f"📋 Auditoria registrada: tipo={tipo_documento} tempo_ms={tempo_ms} "
        f"tentativa={tentativa_numero} tokens_in={tokens_input} tokens_out={tokens_output}"
    )


# ============================================================================
# FUNÇÕES DE SUPORTE AO PAINEL ADMINISTRATIVO
# ============================================================================
# LGPD: todos os dados retornados são agregações estatísticas, sem identificação
# individual. IPs aparecem apenas como hashes contados.

def registrar_tentativa_login_admin(ip_address, sucesso):
    """Registra tentativa de login no painel admin (proteção brute-force)."""
    ip_hash = gerar_hash_ip(ip_address) if ip_address else "unknown"
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO admin_login_attempts (ip_hash, timestamp, sucesso) VALUES (?, ?, ?)',
                (ip_hash, datetime.now().isoformat(), 1 if sucesso else 0)
            )
            conn.commit()
        except Exception as e:
            logging.error(f"❌ Erro ao registrar tentativa de login admin: {e}")
        finally:
            conn.close()


def contar_tentativas_login_admin_falhas(ip_address, janela_minutos=15):
    """Conta tentativas de login que falharam nos últimos N minutos para um IP."""
    ip_hash = gerar_hash_ip(ip_address) if ip_address else "unknown"
    limite = (datetime.now() - timedelta(minutes=janela_minutos)).isoformat()
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT COUNT(*) FROM admin_login_attempts WHERE ip_hash = ? AND timestamp >= ? AND sucesso = 0',
                (ip_hash, limite)
            )
            return cursor.fetchone()[0] or 0
        except Exception as e:
            logging.error(f"❌ Erro ao contar tentativas admin: {e}")
            return 0
        finally:
            conn.close()


def limpar_tentativas_login_admin_antigas(horas=24):
    """Remove tentativas de login admin com mais de N horas (rotina LGPD)."""
    limite = (datetime.now() - timedelta(hours=horas)).isoformat()
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM admin_login_attempts WHERE timestamp < ?', (limite,))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logging.error(f"❌ Erro ao limpar tentativas admin: {e}")
            return 0
        finally:
            conn.close()


def get_admin_dashboard_stats():
    """
    Retorna métricas agregadas para o painel administrativo.

    Tudo aqui é LGPD-compliant: apenas contagens, médias e distribuições.
    Nenhum dado identificável é retornado.
    """
    hoje = datetime.now().strftime('%Y-%m-%d')
    inicio_mes = datetime.now().strftime('%Y-%m-01')
    sete_dias_atras = (datetime.now() - timedelta(days=7)).isoformat()
    trinta_dias_atras = (datetime.now() - timedelta(days=30)).isoformat()

    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()

            # === Documentos: total, hoje, 7 dias, 30 dias ===
            cursor.execute('SELECT total_documentos FROM stats_geral WHERE id = 1')
            row = cursor.fetchone()
            total_documentos = row[0] if row else 0

            cursor.execute('SELECT quantidade FROM stats_diarias WHERE data = ?', (hoje,))
            row = cursor.fetchone()
            docs_hoje = row[0] if row else 0

            cursor.execute('SELECT COUNT(*) FROM audit_ip WHERE data_processamento >= ?', (sete_dias_atras,))
            docs_7d = cursor.fetchone()[0] or 0

            cursor.execute('SELECT COUNT(*) FROM audit_ip WHERE data_processamento >= ?', (trinta_dias_atras,))
            docs_30d = cursor.fetchone()[0] or 0

            # === Tipos de documento mais comuns (últimos 30 dias) ===
            cursor.execute('''
                SELECT tipo_documento, COUNT(*) as qtd
                FROM audit_ip
                WHERE data_processamento >= ?
                GROUP BY tipo_documento
                ORDER BY qtd DESC
                LIMIT 10
            ''', (trinta_dias_atras,))
            tipos_documento = [{'tipo': r[0], 'quantidade': r[1]} for r in cursor.fetchall()]

            # === Feedback agregado (tabela stats_feedback: tipo, quantidade) ===
            cursor.execute("SELECT tipo, quantidade FROM stats_feedback")
            fb_rows = dict(cursor.fetchall())
            fb_pos = fb_rows.get('positivo', 0)
            fb_neg = fb_rows.get('negativo', 0)
            fb_total = fb_pos + fb_neg
            fb_satisfacao = round((fb_pos / fb_total) * 100, 1) if fb_total else 0

            # === Tokens: hoje, mês, 30 dias ===
            cursor.execute(
                'SELECT tokens_input, tokens_output, tokens_total, requisicoes FROM token_usage_diario WHERE data = ?',
                (hoje,)
            )
            row = cursor.fetchone()
            tokens_hoje = {
                'input': row[0] if row else 0,
                'output': row[1] if row else 0,
                'total': row[2] if row else 0,
                'requisicoes': row[3] if row else 0,
            }

            cursor.execute('''
                SELECT COALESCE(SUM(tokens_input), 0), COALESCE(SUM(tokens_output), 0),
                       COALESCE(SUM(tokens_total), 0), COALESCE(SUM(requisicoes), 0)
                FROM token_usage_diario WHERE data >= ?
            ''', (inicio_mes,))
            row = cursor.fetchone()
            tokens_mes = {
                'input': row[0], 'output': row[1], 'total': row[2], 'requisicoes': row[3]
            }

            # Série temporal de tokens nos últimos 30 dias
            cursor.execute('''
                SELECT data, tokens_total, requisicoes
                FROM token_usage_diario
                WHERE data >= ?
                ORDER BY data ASC
            ''', ((datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),))
            serie_tokens = [{'data': r[0], 'tokens': r[1], 'requisicoes': r[2]} for r in cursor.fetchall()]

            # === Tempo médio de processamento (últimos 7 dias) ===
            cursor.execute('''
                SELECT AVG(tempo_ms), MIN(tempo_ms), MAX(tempo_ms), COUNT(tempo_ms)
                FROM audit_ip
                WHERE data_processamento >= ? AND tempo_ms IS NOT NULL
            ''', (sete_dias_atras,))
            row = cursor.fetchone()
            tempo_medio_ms = int(row[0]) if row[0] else 0
            tempo_min_ms = int(row[1]) if row[1] else 0
            tempo_max_ms = int(row[2]) if row[2] else 0
            tempo_amostras = row[3] or 0

            # === Taxa de erro/fallback por modelo Gemini ===
            cursor.execute('''
                SELECT modelo_usado, tentativa_numero, COUNT(*)
                FROM audit_ip
                WHERE data_processamento >= ? AND modelo_usado IS NOT NULL
                GROUP BY modelo_usado, tentativa_numero
                ORDER BY modelo_usado, tentativa_numero
            ''', (trinta_dias_atras,))
            uso_por_modelo = {}
            for modelo, tentativa, qtd in cursor.fetchall():
                uso_por_modelo.setdefault(modelo, {})
                uso_por_modelo[modelo][f'tentativa_{tentativa}'] = qtd
            modelos = []
            for modelo, tentativas in uso_por_modelo.items():
                total = sum(tentativas.values())
                primarios = tentativas.get('tentativa_1', 0)
                fallbacks = total - primarios
                modelos.append({
                    'modelo': modelo,
                    'total': total,
                    'primario': primarios,
                    'fallback': fallbacks,
                    'taxa_fallback': round((fallbacks / total) * 100, 1) if total else 0,
                })
            modelos.sort(key=lambda m: m['total'], reverse=True)

            # === Custo em BRL por simplificação (por modelo) ===
            # Agrega tokens reais por modelo nos últimos 30 dias e aplica
            # tabela de preços oficial Gemini (ver pricing.py).
            import pricing as _pricing
            cambio = _pricing.get_usd_to_brl()

            def _consulta_custo(corte_iso):
                cursor.execute('''
                    SELECT modelo_usado,
                           COALESCE(SUM(tokens_input), 0)  AS tin,
                           COALESCE(SUM(tokens_output), 0) AS tout,
                           COUNT(*)                        AS docs
                    FROM audit_ip
                    WHERE data_processamento >= ?
                      AND modelo_usado IS NOT NULL
                      AND sucesso = 1
                    GROUP BY modelo_usado
                ''', (corte_iso,))
                rows = cursor.fetchall()
                resultado = []
                total_brl = 0.0
                total_in = 0
                total_out = 0
                total_docs = 0
                for modelo, tin, tout, docs in rows:
                    custo = _pricing.custo_brl(modelo, tin, tout)
                    total_brl += custo
                    total_in += tin
                    total_out += tout
                    total_docs += docs
                    resultado.append({
                        'modelo': modelo,
                        'tokens_input': tin,
                        'tokens_output': tout,
                        'tokens_total': tin + tout,
                        'documentos': docs,
                        'custo_brl': round(custo, 4),
                        'custo_brl_por_doc': round(custo / docs, 4) if docs else 0,
                        'tokens_medio_por_doc': round((tin + tout) / docs, 0) if docs else 0,
                    })
                resultado.sort(key=lambda r: r['custo_brl'], reverse=True)
                return {
                    'por_modelo': resultado,
                    'total_brl': round(total_brl, 2),
                    'total_tokens_input': total_in,
                    'total_tokens_output': total_out,
                    'total_documentos': total_docs,
                    'custo_medio_por_doc_brl': round(total_brl / total_docs, 4) if total_docs else 0,
                    'tokens_medio_por_doc': round((total_in + total_out) / total_docs, 0) if total_docs else 0,
                    'tokens_input_medio_por_doc': round(total_in / total_docs, 0) if total_docs else 0,
                    'tokens_output_medio_por_doc': round(total_out / total_docs, 0) if total_docs else 0,
                }

            custo_30d = _consulta_custo(trinta_dias_atras)
            custo_7d = _consulta_custo(sete_dias_atras)
            custo_hoje = _consulta_custo(hoje)
            custo_mes = _consulta_custo(inicio_mes + 'T00:00:00')

            custos = {
                'cambio_usd_brl': cambio,
                'hoje': custo_hoje,
                'sete_dias': custo_7d,
                'mes_atual': custo_mes,
                'trinta_dias': custo_30d,
            }

            # === Heatmap por hora do dia (últimos 7 dias) ===
            cursor.execute('''
                SELECT hora_dia, COUNT(*)
                FROM audit_ip
                WHERE data_processamento >= ? AND hora_dia IS NOT NULL
                GROUP BY hora_dia
            ''', (sete_dias_atras,))
            heatmap_horas = [0] * 24
            for hora, qtd in cursor.fetchall():
                if 0 <= hora <= 23:
                    heatmap_horas[hora] = qtd

            # === Distribuição de IPs únicos (LGPD-safe: só hash) ===
            cursor.execute('''
                SELECT DATE(data_processamento) as dia, COUNT(DISTINCT ip_hash) as ips_unicos
                FROM audit_ip
                WHERE data_processamento >= ?
                GROUP BY dia
                ORDER BY dia ASC
            ''', (trinta_dias_atras,))
            ips_unicos_por_dia = [{'data': r[0], 'ips': r[1]} for r in cursor.fetchall()]

            cursor.execute('SELECT COUNT(DISTINCT ip_hash) FROM audit_ip WHERE data_processamento >= ?',
                          (trinta_dias_atras,))
            total_ips_unicos_30d = cursor.fetchone()[0] or 0

            # === Tentativas de login admin recentes (últimas 24h) ===
            cursor.execute('''
                SELECT
                    SUM(CASE WHEN sucesso = 1 THEN 1 ELSE 0 END) as ok,
                    SUM(CASE WHEN sucesso = 0 THEN 1 ELSE 0 END) as falha,
                    COUNT(DISTINCT ip_hash) as ips
                FROM admin_login_attempts
                WHERE timestamp >= ?
            ''', ((datetime.now() - timedelta(hours=24)).isoformat(),))
            row = cursor.fetchone()
            login_admin_24h = {
                'sucesso': row[0] or 0,
                'falha': row[1] or 0,
                'ips_distintos': row[2] or 0,
            }

            return {
                'gerado_em': datetime.now().isoformat(),
                'documentos': {
                    'total': total_documentos,
                    'hoje': docs_hoje,
                    'sete_dias': docs_7d,
                    'trinta_dias': docs_30d,
                    'tipos': tipos_documento,
                },
                'feedback': {
                    'positivo': fb_pos,
                    'negativo': fb_neg,
                    'total': fb_total,
                    'satisfacao_pct': fb_satisfacao,
                },
                'tokens': {
                    'hoje': tokens_hoje,
                    'mes_atual': tokens_mes,
                    'serie_30d': serie_tokens,
                },
                'tempo_processamento': {
                    'media_ms': tempo_medio_ms,
                    'min_ms': tempo_min_ms,
                    'max_ms': tempo_max_ms,
                    'amostras_7d': tempo_amostras,
                },
                'modelos_gemini': modelos,
                'custos': custos,
                'heatmap_horas_7d': heatmap_horas,
                'alcance': {
                    'ips_unicos_30d': total_ips_unicos_30d,
                    'serie_diaria': ips_unicos_por_dia,
                },
                'admin_login_24h': login_admin_24h,
            }
        except Exception as e:
            logging.error(f"❌ Erro ao montar dashboard admin: {e}")
            return {'erro': str(e)}
        finally:
            conn.close()


def get_auditoria_ip(limite=100, pagina=1, filtro_ip=None, filtro_tipo=None, filtro_data=None):
    """
    Retorna registros de auditoria para o painel administrativo.

    Args:
        limite: Quantidade máxima de registros por página
        pagina: Número da página (1-indexed)
        filtro_ip: Filtrar por hash de IP específico
        filtro_tipo: Filtrar por tipo de documento
        filtro_data: Filtrar por data (formato YYYY-MM-DD)

    Returns:
        Dict com registros, total e informações de paginação
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Construir query com filtros
            where_clauses = []
            params = []

            if filtro_ip:
                where_clauses.append("ip_hash = ?")
                params.append(filtro_ip)

            if filtro_tipo:
                where_clauses.append("tipo_documento = ?")
                params.append(filtro_tipo)

            if filtro_data:
                where_clauses.append("date(data_processamento) = ?")
                params.append(filtro_data)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # Contar total
            cursor.execute(f'SELECT COUNT(*) FROM audit_ip {where_sql}', params)
            total = cursor.fetchone()[0]

            # Buscar registros com paginação
            offset = (pagina - 1) * limite
            cursor.execute(f'''
                SELECT id, ip_hash, tipo_documento, nome_arquivo_hash, tamanho_bytes, modelo_usado, data_processamento
                FROM audit_ip
                {where_sql}
                ORDER BY data_processamento DESC
                LIMIT ? OFFSET ?
            ''', params + [limite, offset])

            registros = []
            for row in cursor.fetchall():
                registros.append({
                    'id': row[0],
                    'ip_hash': row[1],
                    'tipo_documento': row[2],
                    'nome_arquivo_hash': row[3],
                    'tamanho_bytes': row[4],
                    'modelo_usado': row[5],
                    'data_processamento': row[6]
                })

            # IPs únicos para resumo
            cursor.execute(f'SELECT DISTINCT ip_hash FROM audit_ip {where_sql}', params)
            ips_unicos = len(cursor.fetchall())

            # Resumo por tipo
            cursor.execute(f'''
                SELECT tipo_documento, COUNT(*) as qtd
                FROM audit_ip
                {where_sql}
                GROUP BY tipo_documento
                ORDER BY qtd DESC
            ''', params)
            por_tipo = {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()

        total_paginas = (total + limite - 1) // limite if total > 0 else 1

        return {
            'registros': registros,
            'total': total,
            'pagina': pagina,
            'total_paginas': total_paginas,
            'limite': limite,
            'ips_unicos': ips_unicos,
            'por_tipo': por_tipo
        }


# ==========================================
# === FUNÇÕES DE CONTROLE DE TOKENS ===
# ==========================================

def registrar_uso_tokens(tokens_input=0, tokens_output=0):
    """
    Registra tokens consumidos na requisição atual.
    Incrementa contadores diários de input, output e total.

    Args:
        tokens_input: Tokens consumidos no prompt (input)
        tokens_output: Tokens gerados na resposta (output)

    Returns:
        Dict com tokens_total_hoje e limite_atingido
    """
    tokens_total = tokens_input + tokens_output
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO token_usage_diario (data, tokens_input, tokens_output, tokens_total, requisicoes, ultima_atualizacao)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(data) DO UPDATE SET
                    tokens_input = tokens_input + ?,
                    tokens_output = tokens_output + ?,
                    tokens_total = tokens_total + ?,
                    requisicoes = requisicoes + 1,
                    ultima_atualizacao = ?
            ''', (
                hoje, tokens_input, tokens_output, tokens_total, datetime.now().isoformat(),
                tokens_input, tokens_output, tokens_total, datetime.now().isoformat()
            ))

            # Buscar total atualizado
            cursor.execute('SELECT tokens_total, requisicoes FROM token_usage_diario WHERE data = ?', (hoje,))
            row = cursor.fetchone()
            total_hoje = row[0] if row else 0
            reqs_hoje = row[1] if row else 0

            conn.commit()
        finally:
            conn.close()

    limite_atingido = total_hoje >= DAILY_TOKEN_LIMIT
    percentual = min(100, int((total_hoje / DAILY_TOKEN_LIMIT) * 100))

    if limite_atingido:
        logging.warning(f"⚠️ LIMITE DIÁRIO DE TOKENS ATINGIDO: {total_hoje:,} / {DAILY_TOKEN_LIMIT:,}")
    else:
        logging.info(f"📊 Tokens hoje: {total_hoje:,} / {DAILY_TOKEN_LIMIT:,} ({percentual}%) - Requisições: {reqs_hoje}")

    return {
        "tokens_total_hoje": total_hoje,
        "limite_diario": DAILY_TOKEN_LIMIT,
        "limite_atingido": limite_atingido,
        "percentual_uso": percentual,
        "requisicoes_hoje": reqs_hoje
    }


def verificar_limite_tokens():
    """
    Verifica se o limite diário de tokens foi atingido.

    Returns:
        Dict com tokens_total_hoje, limite_atingido, percentual_uso
    """
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('SELECT tokens_total, requisicoes FROM token_usage_diario WHERE data = ?', (hoje,))
            row = cursor.fetchone()
        finally:
            conn.close()

    total_hoje = row[0] if row else 0
    reqs_hoje = row[1] if row else 0
    limite_atingido = total_hoje >= DAILY_TOKEN_LIMIT
    percentual = min(100, int((total_hoje / DAILY_TOKEN_LIMIT) * 100))

    return {
        "tokens_total_hoje": total_hoje,
        "limite_diario": DAILY_TOKEN_LIMIT,
        "limite_atingido": limite_atingido,
        "percentual_uso": percentual,
        "requisicoes_hoje": reqs_hoje
    }


def get_uso_tokens_hoje():
    """Retorna resumo do uso de tokens do dia para o endpoint /health"""
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('SELECT tokens_input, tokens_output, tokens_total, requisicoes FROM token_usage_diario WHERE data = ?', (hoje,))
            row = cursor.fetchone()
        finally:
            conn.close()

    if row:
        return {
            "data": hoje,
            "tokens_input": row[0],
            "tokens_output": row[1],
            "tokens_total": row[2],
            "requisicoes": row[3],
            "limite_diario": DAILY_TOKEN_LIMIT,
            "percentual_uso": min(100, int((row[2] / DAILY_TOKEN_LIMIT) * 100))
        }
    return {
        "data": hoje,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_total": 0,
        "requisicoes": 0,
        "limite_diario": DAILY_TOKEN_LIMIT,
        "percentual_uso": 0
    }


def limpar_tokens_antigos(dias=7):
    """Remove registros de uso de tokens com mais de X dias"""
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                DELETE FROM token_usage_diario
                WHERE date(data) < date('now', ? || ' days')
            ''', (f'-{dias}',))

            deletados = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        if deletados > 0:
            logging.info(f"🗑️ Tokens: Removidos {deletados} registros de uso antigos")

        return deletados


# ==========================================
# === FUNÇÕES DO COFRE DE CPF (LGPD) ===
# ==========================================

def gerar_hash_cpf(cpf):
    """
    Gera hash SHA-256 do CPF para lookup rápido.
    LGPD: O hash é irreversível - impossível reconstruir o CPF.

    Args:
        cpf: CPF limpo (apenas dígitos, 11 caracteres)
    """
    return hashlib.sha256(f"{CPF_HASH_SALT}:{cpf}".encode('utf-8')).hexdigest()


def criptografar_cpf(cpf):
    """
    Criptografa CPF usando Fernet (AES-128-CBC).

    Args:
        cpf: CPF limpo (apenas dígitos)

    Returns:
        CPF criptografado em base64, ou None se criptografia indisponível
    """
    if not _fernet:
        return None
    try:
        return _fernet.encrypt(cpf.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logging.error(f"❌ Erro ao criptografar CPF: {e}")
        return None


def descriptografar_cpf(cpf_encrypted):
    """
    Descriptografa CPF do cofre.

    Args:
        cpf_encrypted: CPF criptografado em base64

    Returns:
        CPF descriptografado ou None se falhar
    """
    if not _fernet:
        return None
    try:
        return _fernet.decrypt(cpf_encrypted.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logging.error(f"❌ Erro ao descriptografar CPF: {e}")
        return None


def registrar_cpf_vault(cpf, ip_address=None):
    """
    Registra CPF no cofre criptografado e incrementa rate limit.
    LGPD: CPF é armazenado CRIPTOGRAFADO e apagado diariamente.

    Args:
        cpf: CPF limpo (apenas dígitos, 11 caracteres)
        ip_address: IP do usuário (será convertido em hash)

    Returns:
        Dict com sucesso, contagem_hoje, limite_atingido
    """
    cpf_hash = gerar_hash_cpf(cpf)
    cpf_encrypted = criptografar_cpf(cpf)
    if not cpf_encrypted and not CPF_VAULT_KEY:
        logging.warning("⚠️ CPF_VAULT_KEY não configurada - CPF não será armazenado no cofre")
    ip_hash = gerar_hash_ip(ip_address) if ip_address else None
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Verificar rate limit ANTES de registrar
            cursor.execute('''
                SELECT contagem FROM cpf_rate_limit
                WHERE cpf_hash = ? AND data = ?
            ''', (cpf_hash, hoje))
            row = cursor.fetchone()
            contagem_atual = row[0] if row else 0

            if contagem_atual >= CPF_DAILY_LIMIT:
                logging.warning(f"⚠️ CPF rate limit atingido ({contagem_atual}/{CPF_DAILY_LIMIT})")
                return {
                    "sucesso": False,
                    "contagem_hoje": contagem_atual,
                    "limite": CPF_DAILY_LIMIT,
                    "limite_atingido": True,
                    "mensagem": f"Limite de {CPF_DAILY_LIMIT} documentos por dia atingido para este CPF."
                }

            # Registrar no cofre (apenas se criptografia disponível)
            if cpf_encrypted:
                cursor.execute('''
                    INSERT INTO cpf_vault (cpf_hash, cpf_encrypted, data_registro, ip_hash)
                    VALUES (?, ?, ?, ?)
                ''', (cpf_hash, cpf_encrypted, datetime.now().isoformat(), ip_hash))

            # Incrementar rate limit
            cursor.execute('''
                INSERT INTO cpf_rate_limit (cpf_hash, data, contagem)
                VALUES (?, ?, 1)
                ON CONFLICT(cpf_hash, data) DO UPDATE SET contagem = contagem + 1
            ''', (cpf_hash, hoje))

            # Buscar contagem atualizada
            cursor.execute('''
                SELECT contagem FROM cpf_rate_limit
                WHERE cpf_hash = ? AND data = ?
            ''', (cpf_hash, hoje))
            nova_contagem = cursor.fetchone()[0]

            conn.commit()
        finally:
            conn.close()

    logging.info(f"🔐 CPF registrado no cofre (uso: {nova_contagem}/{CPF_DAILY_LIMIT})")

    return {
        "sucesso": True,
        "contagem_hoje": nova_contagem,
        "limite": CPF_DAILY_LIMIT,
        "limite_atingido": False,
        "restantes": CPF_DAILY_LIMIT - nova_contagem
    }


def verificar_cpf_rate_limit(cpf):
    """
    Verifica se o CPF ainda pode processar documentos hoje.

    Args:
        cpf: CPF limpo (apenas dígitos)

    Returns:
        Dict com contagem_hoje, limite, limite_atingido, restantes
    """
    cpf_hash = gerar_hash_cpf(cpf)
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT contagem FROM cpf_rate_limit
                WHERE cpf_hash = ? AND data = ?
            ''', (cpf_hash, hoje))
            row = cursor.fetchone()
        finally:
            conn.close()

    contagem = row[0] if row else 0
    limite_atingido = contagem >= CPF_DAILY_LIMIT

    return {
        "contagem_hoje": contagem,
        "limite": CPF_DAILY_LIMIT,
        "limite_atingido": limite_atingido,
        "restantes": max(0, CPF_DAILY_LIMIT - contagem)
    }


def verificar_e_incrementar_cpf_ip(cpf, ip_address):
    """
    Rate limit combinado: incrementa contagem do par (cpf_hash, ip_hash) e do ip_hash isolado.
    Bloqueia se ultrapassar CPF_IP_DAILY_LIMIT ou IP_DAILY_LIMIT.
    Retorna dict com limite_atingido (bool) e motivo.

    Projetado para dificultar botnet: mesmo CPF usado de vários IPs é bloqueado mais cedo,
    e mesmo IP tentando dezenas de CPFs também é bloqueado.
    """
    if not cpf or not ip_address:
        return {"limite_atingido": False, "motivo": None}

    cpf_hash = gerar_hash_cpf(cpf)
    ip_hash = gerar_hash_ip(ip_address)
    hoje = datetime.now().strftime('%Y-%m-%d')

    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Contagem atual do par (CPF, IP)
            cursor.execute('''
                SELECT contagem FROM cpf_ip_rate_limit
                WHERE cpf_hash = ? AND ip_hash = ? AND data = ?
            ''', (cpf_hash, ip_hash, hoje))
            row = cursor.fetchone()
            contagem_par = row[0] if row else 0

            if contagem_par >= CPF_IP_DAILY_LIMIT:
                return {
                    "limite_atingido": True,
                    "motivo": f"Limite diário de {CPF_IP_DAILY_LIMIT} documentos para esta combinação de CPF e rede atingido.",
                    "contagem_par": contagem_par,
                    "limite_par": CPF_IP_DAILY_LIMIT
                }

            # Contagem total no IP (todos os CPFs vindos deste IP hoje)
            cursor.execute('''
                SELECT COALESCE(SUM(contagem), 0) FROM cpf_ip_rate_limit
                WHERE ip_hash = ? AND data = ?
            ''', (ip_hash, hoje))
            total_ip = cursor.fetchone()[0] or 0

            if total_ip >= IP_DAILY_LIMIT:
                return {
                    "limite_atingido": True,
                    "motivo": f"Limite diário de {IP_DAILY_LIMIT} documentos para esta rede atingido.",
                    "total_ip": total_ip,
                    "limite_ip": IP_DAILY_LIMIT
                }

            # Incrementar o par
            cursor.execute('''
                INSERT INTO cpf_ip_rate_limit (cpf_hash, ip_hash, data, contagem)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(cpf_hash, ip_hash, data) DO UPDATE SET contagem = contagem + 1
            ''', (cpf_hash, ip_hash, hoje))

            conn.commit()
        finally:
            conn.close()

    return {"limite_atingido": False, "motivo": None}


def limpar_cpf_ip_rate_limit_antigo():
    """Remove registros cpf_ip_rate_limit anteriores a hoje (LGPD)."""
    hoje = datetime.now().strftime('%Y-%m-%d')
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cpf_ip_rate_limit WHERE data < ?', (hoje,))
            deletados = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    return deletados


def limpar_cpf_vault():
    """
    Remove TODOS os registros do cofre de CPF.
    LGPD: Limpeza diária obrigatória - nenhum CPF persiste mais de 24h.

    Returns:
        Número de registros removidos
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Limpar cofre de CPFs criptografados
            cursor.execute('DELETE FROM cpf_vault')
            deletados_vault = cursor.rowcount

            # Limpar rate limits de dias anteriores (manter apenas hoje)
            hoje = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('DELETE FROM cpf_rate_limit WHERE data < ?', (hoje,))
            deletados_rate = cursor.rowcount

            conn.commit()
        finally:
            conn.close()

    total = deletados_vault + deletados_rate
    if total > 0:
        logging.info(f"🗑️ LGPD CPF: Removidos {deletados_vault} CPFs do cofre + {deletados_rate} registros de rate limit antigos")

    return total


def limpar_auditoria_antiga(dias=30):
    """
    Remove registros de auditoria com mais de X dias.
    Mantém histórico por 30 dias por padrão.

    Args:
        dias: Quantidade de dias para manter (padrão: 30)
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                DELETE FROM audit_ip
                WHERE date(data_processamento) < date('now', ? || ' days')
            ''', (f'-{dias}',))

            deletados = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        if deletados > 0:
            logging.info(f"🗑️ Auditoria: Removidos {deletados} registros com mais de {dias} dias")

        return deletados


def limpar_estatisticas_antigas():
    """
    Remove estatísticas diárias com mais de 30 dias
    LGPD: Não mantém dados antigos desnecessariamente
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

            # Manter apenas últimos 30 dias
            cursor.execute('''
                DELETE FROM stats_diarias
                WHERE date(data) < date('now', '-30 days')
            ''')

            deletados = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        if deletados > 0:
            logging.info(f"🗑️ LGPD: Removidos {deletados} registros diários antigos")

        return deletados

# Thread de limpeza automática
cleanup_event = Event()
cleanup_thread = None

def executar_limpeza_periodica():
    """
    Thread que executa limpeza de estatísticas antigas diariamente
    Roda em background sem impactar a aplicação
    """
    while not cleanup_event.is_set():
        try:
            # Aguardar 24 horas (ou até ser interrompido)
            if cleanup_event.wait(timeout=86400):  # 86400 segundos = 24 horas
                break

            # Executar limpeza
            logging.info("🧹 Iniciando limpeza automática de estatísticas antigas...")
            deletados = limpar_estatisticas_antigas()
            deletados_validacao = limpar_validacoes_expiradas()
            deletados_auditoria = limpar_auditoria_antiga()
            deletados_cpf = limpar_cpf_vault()
            deletados_tokens = limpar_tokens_antigos()

            total_deletados = deletados + deletados_validacao + deletados_auditoria + deletados_cpf + deletados_tokens
            if total_deletados > 0:
                logging.info(f"✅ Limpeza concluída: {deletados} stats + {deletados_validacao} validações + {deletados_auditoria} auditoria + {deletados_cpf} CPFs + {deletados_tokens} tokens removidos")
            else:
                logging.info("✅ Limpeza concluída: nenhum registro antigo encontrado")

        except Exception as e:
            logging.error(f"❌ Erro na limpeza automática: {e}")

def iniciar_limpeza_automatica():
    """Inicia thread de limpeza automática em background"""
    global cleanup_thread

    if cleanup_thread is not None and cleanup_thread.is_alive():
        logging.info("Thread de limpeza já está rodando")
        return

    cleanup_thread = Thread(target=executar_limpeza_periodica, daemon=True, name="LGPD-Cleanup")
    cleanup_thread.start()
    logging.info("🧹 Thread de limpeza automática iniciada (executa a cada 24h)")

def parar_limpeza_automatica():
    """Para a thread de limpeza (útil para testes ou shutdown)"""
    cleanup_event.set()
    if cleanup_thread is not None:
        cleanup_thread.join(timeout=2)
    logging.info("🛑 Thread de limpeza automática parada")

# Inicializar database ao importar módulo
try:
    init_db()

    # Executar limpeza inicial imediatamente (apenas registros antigos)
    deletados = limpar_estatisticas_antigas()
    deletados_val = limpar_validacoes_expiradas()
    deletados_aud = limpar_auditoria_antiga()
    deletados_cpf = limpar_cpf_vault()
    deletados_tok = limpar_tokens_antigos()
    total_limpeza = deletados + deletados_val + deletados_aud + deletados_cpf + deletados_tok
    if total_limpeza > 0:
        logging.info(f"🧹 Limpeza inicial: {deletados} stats + {deletados_val} validações + {deletados_aud} auditoria + {deletados_cpf} CPFs + {deletados_tok} tokens removidos")

    # Iniciar thread de limpeza automática
    iniciar_limpeza_automatica()

except Exception as e:
    logging.error(f"Erro ao inicializar database: {e}")
