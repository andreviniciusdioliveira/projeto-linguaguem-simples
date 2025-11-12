"""
Sistema de estatísticas agregadas para o Entenda Aqui
LGPD COMPLIANT - Armazena APENAS contadores, ZERO dados de documentos
"""
import sqlite3
import os
import logging
from datetime import datetime
from threading import Lock

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
            'data_inicio': data_inicio
        }

        return stats

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

# Inicializar database ao importar módulo
try:
    init_db()
except Exception as e:
    logging.error(f"Erro ao inicializar database: {e}")
