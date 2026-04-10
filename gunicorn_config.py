import os
import multiprocessing

# Configurações do Gunicorn otimizadas para Render
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"

# Workers
workers = 2  # REDUZIDO - 2 workers é suficiente para evitar OOM
worker_class = "sync"
worker_connections = 100
max_requests = 100  # Reciclar worker após 100 requests
max_requests_jitter = 20

# Timeouts
timeout = 120  # 2 minutos - tempo máximo para processar uma request
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True
enable_stdio_inheritance = True

# Process naming
proc_name = "entenda-aqui"

# Server mechanics
daemon = False
pidfile = None
umask = 0o027  # Arquivos temporários não acessíveis a outros usuários
user = None
group = None
tmp_upload_dir = None

# Memory management
preload_app = True  # Pre-load para compartilhar memória entre workers
worker_tmp_dir = "/dev/shm"  # Usar RAM para arquivos temporários

# Limites
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190