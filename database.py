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
    """Inicializa banco de dados com tabelas de estatísticas"""
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            cursor = conn.cursor()

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

        # Tabela de auditoria de IP (para administração)
        # Armazena HASH do IP + tipo de documento processado (SEM conteúdo do documento)
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

            # Inserir registro inicial se não existir
            cursor.execute('SELECT COUNT(*) FROM stats_geral')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO stats_geral (id, total_documentos, data_inicio, ultima_atualizacao)
                    VALUES (1, 0, ?, ?)
                ''', (datetime.now().isoformat(), datetime.now().isoformat()))

            cursor.execute('PRAGMA journal_mode=WAL')

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


def registrar_auditoria_ip(ip_address, tipo_documento, nome_arquivo=None, tamanho_bytes=None, modelo_usado=None):
    """
    Registra auditoria de processamento (LGPD compliant).
    Armazena APENAS hashes - NUNCA dados identificáveis.
    """
    ip_hash = gerar_hash_ip(ip_address) if ip_address else "unknown"
    nome_hash = hashlib.sha256(nome_arquivo.encode('utf-8')).hexdigest()[:16] if nome_arquivo else None

    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO audit_ip (ip_hash, tipo_documento, nome_arquivo_hash, tamanho_bytes, modelo_usado, data_processamento)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                ip_hash,
                tipo_documento,
                nome_hash,
                tamanho_bytes,
                modelo_usado,
                datetime.now().isoformat()
            ))

            conn.commit()
        except Exception as e:
            logging.error(f"❌ Erro ao registrar auditoria: {e}")
        finally:
            conn.close()

    logging.info(f"📋 Auditoria registrada: tipo={tipo_documento}")


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
