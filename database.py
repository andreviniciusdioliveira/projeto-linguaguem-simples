"""
Sistema de estatísticas agregadas para o Entenda Aqui
LGPD COMPLIANT - Armazena APENAS contadores e hashes, ZERO dados de documentos
"""
import sqlite3
import os
import logging
import hashlib
import secrets
from datetime import datetime
from threading import Lock, Thread, Event
import time

# Lock para operações thread-safe
db_lock = Lock()

# Caminho do banco (persistente, não em TEMP_DIR para não perder dados)
DB_PATH = os.path.join(os.path.dirname(__file__), 'stats.db')

def init_db():
    """Inicializa banco de dados com tabelas de estatísticas"""
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
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

        # Inserir registro inicial se não existir
        cursor.execute('SELECT COUNT(*) FROM stats_geral')
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO stats_geral (id, total_documentos, data_inicio, ultima_atualizacao)
                VALUES (1, 0, ?, ?)
            ''', (datetime.now().isoformat(), datetime.now().isoformat()))

        conn.commit()
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
        conn = sqlite3.connect(DB_PATH)
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
        conn = sqlite3.connect(DB_PATH)
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
        conn.close()

        logging.info(f"👍👎 Feedback registrado: {tipo_feedback} (Total: {total})")
        return total

def get_estatisticas():
    """
    Retorna estatísticas agregadas para exibição
    LGPD: Apenas números, sem dados identificáveis
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
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
    salt = "entenda-aqui-tjto-2024"
    return hashlib.sha256(f"{salt}:{ip_address}".encode('utf-8')).hexdigest()


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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        agora = datetime.now()
        # Documentos expiram em 30 dias (LGPD)
        expiracao = datetime(agora.year, agora.month, agora.day)
        expiracao = agora.replace(day=1)
        # Calcular 30 dias a partir de agora
        from datetime import timedelta
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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT doc_id, hash_conteudo, ip_hash, tipo_documento, data_criacao, data_expiracao
            FROM validacao_documentos
            WHERE doc_id = ?
        ''', (doc_id,))

        row = cursor.fetchone()
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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM validacao_documentos
            WHERE datetime(data_expiracao) < datetime('now')
        ''')

        deletados = cursor.rowcount
        conn.commit()
        conn.close()

        if deletados > 0:
            logging.info(f"🗑️ LGPD: Removidos {deletados} registros de validação expirados")

        return deletados


def limpar_estatisticas_antigas():
    """
    Remove estatísticas diárias com mais de 30 dias
    LGPD: Não mantém dados antigos desnecessariamente
    """
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Manter apenas últimos 30 dias
        cursor.execute('''
            DELETE FROM stats_diarias
            WHERE date(data) < date('now', '-30 days')
        ''')

        deletados = cursor.rowcount
        conn.commit()
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

            total_deletados = deletados + deletados_validacao
            if total_deletados > 0:
                logging.info(f"✅ Limpeza concluída: {deletados} stats + {deletados_validacao} validações removidos")
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
    if deletados > 0 or deletados_val > 0:
        logging.info(f"🧹 Limpeza inicial: {deletados} stats + {deletados_val} validações removidos")

    # Iniciar thread de limpeza automática
    iniciar_limpeza_automatica()

except Exception as e:
    logging.error(f"Erro ao inicializar database: {e}")
