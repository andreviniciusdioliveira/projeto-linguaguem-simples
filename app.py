from flask import Flask, render_template, request, send_file, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
import fitz
import pytesseract
from PIL import Image, ImageEnhance
import io
import os
import logging
import requests
import time
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from functools import wraps
from datetime import datetime, timedelta
import hashlib
import tempfile
import threading
import queue
import json
import re
import base64
import subprocess
import numpy as np
import google.generativeai as genai  # CRÍTICO: Import do Gemini

# Tentativa de importar OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
    logging.info("OpenCV disponível para processamento avançado de imagens")
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("OpenCV não disponível - usando processamento básico")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)  # Sessão dura 1 hora
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# CONFIGURAR GEMINI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logging.info("✅ Gemini configurado com API Key")
else:
    logging.error("❌ GEMINI_API_KEY não configurada!")

# Modelos Gemini ATUALIZADOS - Setembro 2025
GEMINI_MODELS = [
    {
        "name": "gemini-2.5-flash-lite",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 1
    },
    {
        "name": "gemini-2.5-flash",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 2
    },
    {
        "name": "gemini-2.0-flash-exp",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 3
    },
    {
        "name": "gemini-1.5-flash",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 4
    }
]

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
TEMP_DIR = tempfile.gettempdir()

# Rate limiting
request_counts = {}
RATE_LIMIT = 10  # requisições por minuto
cleanup_lock = threading.Lock()

# Cache de resultados processados
results_cache = {}
CACHE_EXPIRATION = 3600  # 1 hora

# Estatísticas de uso dos modelos
model_usage_stats = {model["name"]: {"attempts": 0, "successes": 0, "failures": 0} for model in GEMINI_MODELS}

# ===== LGPD - Sistema de Limpeza Automática =====
# Controle de arquivos temporários
temp_files_tracker = {}
TEMP_FILE_EXPIRATION = 1800  # 30 minutos em segundos (aumentado para evitar perda de PDF)

def registrar_arquivo_temporario(file_path, session_id=None):
    """Registra arquivo temporário para limpeza automática (LGPD)"""
    with cleanup_lock:
        temp_files_tracker[file_path] = {
            "criado_em": time.time(),
            "session_id": session_id,
            "expira_em": time.time() + TEMP_FILE_EXPIRATION
        }
    logging.info(f"📋 Arquivo temporário registrado: {file_path} (expira em 30 minutos)")

def limpar_arquivos_expirados():
    """Remove arquivos temporários expirados (LGPD - 10 minutos)"""
    agora = time.time()
    arquivos_removidos = 0

    with cleanup_lock:
        arquivos_expirados = [
            path for path, info in temp_files_tracker.items()
            if agora > info["expira_em"]
        ]

        for file_path in arquivos_expirados:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    arquivos_removidos += 1
                    logging.info(f"🗑️ LGPD: Arquivo removido após 10 min: {file_path}")

                del temp_files_tracker[file_path]
            except Exception as e:
                logging.error(f"Erro ao remover arquivo {file_path}: {e}")

    if arquivos_removidos > 0:
        logging.info(f"✅ LGPD: {arquivos_removidos} arquivo(s) temporário(s) removido(s)")

    return arquivos_removidos

def iniciar_limpeza_automatica():
    """Inicia thread de limpeza automática (LGPD)"""
    def executar_limpeza():
        while True:
            time.sleep(60)  # Verificar a cada 1 minuto
            limpar_arquivos_expirados()

    thread = threading.Thread(target=executar_limpeza, daemon=True)
    thread.start()
    logging.info("🔄 Sistema de limpeza automática LGPD iniciado (10 min)")

# Iniciar limpeza automática ao carregar o app
iniciar_limpeza_automatica()

def verificar_tesseract():
    """Verifica se o Tesseract está disponível e configurado"""
    try:
        result = subprocess.run(['tesseract', '--version'], 
                              capture_output=True, text=True, check=True, timeout=10)
        version = result.stdout.split('\n')[0]
        logging.info(f"Tesseract detectado: {version}")
        
        # Verificar idiomas disponíveis
        langs_result = subprocess.run(['tesseract', '--list-langs'], 
                                    capture_output=True, text=True, check=True, timeout=10)
        langs = langs_result.stdout.strip().split('\n')[1:]
        logging.info(f"Idiomas disponíveis: {langs}")
        
        if 'por' not in langs:
            logging.warning("Português não disponível no Tesseract")
            
        return True, version, langs
    except Exception as e:
        logging.error(f"Tesseract não está disponível: {e}")
        return False, None, []

# Verificar Tesseract na inicialização
TESSERACT_AVAILABLE, TESSERACT_VERSION, TESSERACT_LANGS = verificar_tesseract()

def cleanup_old_requests():
    with cleanup_lock:
        now = datetime.now()
        to_remove = []
        for ip, (count, timestamp) in request_counts.items():
            if now - timestamp > timedelta(minutes=1):
                to_remove.append(ip)
        for ip in to_remove:
            del request_counts[ip]

def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip = request.remote_addr
        now = datetime.now()
        
        cleanup_old_requests()
        
        with cleanup_lock:
            if ip in request_counts:
                count, first_request = request_counts[ip]
                if now - first_request < timedelta(minutes=1):
                    if count >= RATE_LIMIT:
                        return jsonify({"erro": "Limite de requisições excedido. Tente novamente em alguns minutos."}), 429
                    request_counts[ip] = (count + 1, first_request)
                else:
                    request_counts[ip] = (1, now)
            else:
                request_counts[ip] = (1, now)
        
        return f(*args, **kwargs)
    return decorated_function

# Prompt otimizado e estruturado (NÃO ALTERADO)
PROMPT_SIMPLIFICACAO = """**Papel:** Você é um especialista em linguagem simples aplicada ao Poder Judiciário, com experiência em transformar textos jurídicos complexos em comunicações claras e acessíveis.

**ESTRUTURA DE ANÁLISE OBRIGATÓRIA:**

IDENTIFICAÇÃO DO DOCUMENTO
- Tipo: [Sentença/Despacho/Decisão/Acórdão/Voto/Intimação/Mandado]
- Número do processo: [identificar]
- Assunto principal: [identificar]


📊 ENTENDA AQUI
[Use sempre um dos ícones abaixo]
✅ **VITÓRIA TOTAL** - Você ganhou completamente a causa
❌ **DERROTA** - Você perdeu a causa
⚠️ **VITÓRIA PARCIAL** - Você ganhou parte do que pediu
⏳ **AGUARDANDO** - Ainda não há decisão final
📋 **ANDAMENTO** - Apenas um despacho processual
⚠️ **MANDADO** - O que Você deve fazer

**Em uma frase:** [Explicar o resultado em linguagem muito simples]

📑 O QUE ACONTECEU
[Explicar em 3-4 linhas o contexto do processo]

⚖️ O QUE O(A) [JUIZ(A)/DESEMBARGADOR(A)] DECIDIU
[Detalhar a decisão em linguagem simples, usando parágrafos curtos]
[Use "Desembargador(a)" se for ACÓRDÃO ou VOTO]
[Use "Juiz(a)" se for SENTENÇA, DECISÃO ou DESPACHO]

💰 VALORES E OBRIGAÇÕES
**ATENÇÃO: Procure atentamente por valores monetários no texto, especialmente:**
- Indenizações por danos morais (procure "danos morais", "R$", "reais")
- Indenizações por danos materiais (procure "danos materiais", "lucros cessantes")
- Custas e honorários (procure "honorários", "custas", "despesas")

- Valor da causa: R$ [extrair valor ou indicar "não especificado"]
- **Valores a receber**: R$ [EXTRAIR VALORES ESPECÍFICOS DO DISPOSITIVO/SENTENÇA]
  - Danos morais: R$ [valor]
  - Danos materiais: R$ [valor]
  - Lucros cessantes: R$ [valor ou "pedido negado"]
- Valores a pagar: R$ [detalhar custas, honorários]
- Honorários advocatícios: [percentual] sobre [base de cálculo] = R$ [valor aproximado]
- Custas processuais: [quem paga]
- Correção monetária: desde [data], pelo índice [IPCA/SELIC/etc]
- Juros de mora: [taxa] desde [data]

**SE HOUVER CONDENAÇÃO AO PAGAMENTO, SEMPRE INFORME O VALOR TOTAL APROXIMADO QUE A PESSOA VAI RECEBER**

📚 MINI DICIONÁRIO DOS TERMOS JURÍDICOS
[Listar apenas os termos jurídicos que aparecem no texto com explicação simples]
• **Termo 1:** Explicação clara e simples
• **Termo 2:** Explicação clara e simples
• **Termo 3:** Explicação clara e simples

---
*Documento processado em: [data/hora]*
*Este é um resumo simplificado. Consulte seu advogado ou defensor público para orientações específicas.*

**REGRAS DE SIMPLIFICAÇÃO:**
1. Use frases com máximo 20 palavras
2. Substitua jargões por palavras comuns
3. Explique siglas na primeira vez que aparecem
4. Use exemplos concretos quando possível
5. Mantenha tom respeitoso mas acessível
6. Destaque informações críticas com formatação
7. **CRÍTICO:** Identifique o tipo de documento e use a autoridade correta:
   - ACÓRDÃO ou VOTO → use "Desembargador(a)" ou "Tribunal"
   - SENTENÇA, DECISÃO ou DESPACHO → use "Juiz(a)"

**TEXTO ORIGINAL A SIMPLIFICAR:**
"""

# Prompt melhorado com identificação de tipo
PROMPT_SIMPLIFICACAO_MELHORADO = """**PAPEL:** Você é um especialista em linguagem simples do Poder Judiciário.

**INSTRUÇÕES CRÍTICAS:**
1. NUNCA invente informações que não estejam no documento
2. SEMPRE identifique o tipo de documento primeiro
3. Use APENAS informações presentes no texto original
4. Se for MANDADO, destaque a urgência e ação necessária
5. Se for INTIMAÇÃO, explique claramente do que se trata

**ANÁLISE OBRIGATÓRIA DO DOCUMENTO:**

1. TIPO DE DOCUMENTO:
Identifique: [Sentença/Acórdão/Decisão/Despacho/Mandado de Citação/Mandado de Intimação/Intimação/etc.]

2. SE FOR MANDADO (URGÊNCIA MÁXIMA):
🚨 MANDADO - AÇÃO OBRIGATÓRIA 🚨
- Tipo específico: [Citação/Intimação/Penhora/Despejo]
- O que fazer: [Ação clara e específica]
- Prazo: [Extrair do documento]
- Consequências de ignorar: [Baseado no tipo]

3. SE FOR INTIMAÇÃO:
📬 INTIMAÇÃO - AVISO IMPORTANTE
- Sobre o quê: [Sentença/Audiência/Pagamento/etc.]
- Data/Prazo: [Extrair do documento]
- Ação necessária: [O que o cidadão deve fazer]

4. ESTRUTURA PARA OUTROS DOCUMENTOS:

📊 ENTENDA AQUI
[Escolha o ícone apropriado baseado no resultado]
✅ VITÓRIA TOTAL - Você ganhou completamente
❌ DERROTA - Você perdeu a causa
⚠️ VITÓRIA PARCIAL - Você ganhou parte
⏳ AGUARDANDO - Não há decisão final
📋 ANDAMENTO - Apenas despacho processual

**Em uma frase:** [Resultado em linguagem simples]

📑 O QUE ACONTECEU
[Contexto em 3-4 linhas simples]

⚖️ DECISÃO
[Use Juiz(a) para 1ª instância ou Desembargador(a) para 2ª instância]
[Explique a decisão em parágrafos curtos]

💰 VALORES E OBRIGAÇÕES
**EXTRAIA TODOS OS VALORES MENCIONADOS:**
- Danos morais: R$ [valor exato do documento]
- Danos materiais: R$ [valor exato do documento]
- Valor total: R$ [somar se possível]
- Honorários: [percentual e base de cálculo]
- Custas: [quem paga]
- Correção: [índice e data inicial]

📅 PRAZOS IMPORTANTES
- Recurso: [dias - se cabível]
- Pagamento: [dias - se houver]
- Audiência: [data e hora - se houver]

🚶 PRÓXIMOS PASSOS
[Orientações práticas baseadas no tipo de decisão]

📚 MINI DICIONÁRIO
[APENAS termos que aparecem no documento]
• **Termo**: Explicação simples

⚠️ CABE RECURSO?
[Se cabível, explique:]
- Tipo de recurso: [Nome]
- Prazo: [Dias]
- Onde: [Tribunal/Turma]
- Precisa de advogado: [Sim/Não]

---
*Documento processado em: [data/hora]*
*Este resumo não substitui orientação jurídica*

**REGRAS:**
1. Máximo 20 palavras por frase
2. Substitua jargões por palavras comuns
3. Identifique corretamente o tipo de documento
4. DESTAQUE se for MANDADO (urgência máxima)
5. Mantenha 100% de fidelidade ao documento original

**TEXTO ORIGINAL:**
"""

# ============= NOVAS FUNÇÕES DE IDENTIFICAÇÃO E ANÁLISE =============

def identificar_tipo_documento(texto):
    """Identifica o tipo de documento jurídico usando IA (Gemini)"""

    # Truncar texto se muito longo (usar apenas início que geralmente tem o tipo)
    texto_analise = texto[:3000] if len(texto) > 3000 else texto

    prompt = f"""Analise este documento jurídico brasileiro e identifique o tipo EXATO.

REGRAS CRÍTICAS:
1. Se o documento tem as palavras "MANDADO" ou "OFICIAL DE JUSTIÇA" ou "CUMPRA-SE" → responda "mandado"
2. Se tem "SENTENÇA" ou "JULGO PROCEDENTE/IMPROCEDENTE" → responda "sentenca"
3. Se tem "ACÓRDÃO" ou "RELATOR" ou "TURMA JULGADORA" → responda "acordao"
4. Se tem apenas "INTIMAÇÃO" SEM mandado → responda "intimacao"
5. Se tem "DESPACHO" → responda "despacho"

ATENÇÃO: Procure pelas palavras-chave no INÍCIO do documento!

Documento:
{texto_analise}

Responda APENAS UMA PALAVRA (sem pontuação): sentenca, acordao, mandado, intimacao ou despacho"""

    try:
        logging.info("🤖 Chamando Gemini para identificar tipo de documento...")
        model = genai.GenerativeModel(GEMINI_MODELS[1]["name"])  # Usar flash para rapidez
        response = model.generate_content(prompt)
        tipo_bruto = response.text.strip()
        logging.info(f"🤖 Gemini retornou: '{tipo_bruto}'")

        # Limpar resposta (remover pontos, espaços extras, etc)
        tipo_identificado = tipo_bruto.lower().replace(".", "").replace(",", "").strip()
        logging.info(f"🤖 Tipo limpo: '{tipo_identificado}'")

        # Mapear tipo para informações de urgência
        tipos_info = {
            "sentenca": {"urgencia": "ALTA", "acao_necessaria": "Verificar prazo para recurso"},
            "acordao": {"urgencia": "MÉDIA", "acao_necessaria": "Analisar decisão do recurso"},
            "mandado": {"urgencia": "MÁXIMA", "acao_necessaria": "Comparecer/Contestar URGENTE"},
            "mandado_citacao": {"urgencia": "MÁXIMA", "acao_necessaria": "Procurar advogado URGENTE"},
            "mandado_intimacao": {"urgencia": "MÁXIMA", "acao_necessaria": "Comparecer no dia/hora marcados"},
            "mandado_penhora": {"urgencia": "MÁXIMA", "acao_necessaria": "Pagar ou apresentar defesa"},
            "intimacao": {"urgencia": "ALTA", "acao_necessaria": "Tomar ciência e verificar prazos"},
            "decisao_interlocutoria": {"urgencia": "ALTA", "acao_necessaria": "Cumprir ou recorrer via agravo"},
            "despacho": {"urgencia": "MÉDIA", "acao_necessaria": "Aguardar ou manifestar se necessário"}
        }

        # Tentar match exato primeiro
        if tipo_identificado in tipos_info:
            logging.info(f"✅ Tipo identificado: {tipo_identificado}")
            return tipo_identificado, tipos_info[tipo_identificado]

        # Tentar encontrar a palavra dentro da resposta
        for tipo in tipos_info.keys():
            if tipo in tipo_identificado:
                logging.info(f"✅ Tipo identificado (match parcial): {tipo}")
                return tipo, tipos_info[tipo]

        # Se Gemini mencionou "mandado" mas não especificou tipo, usar genérico
        if "mandado" in tipo_identificado:
            logging.info("✅ Tipo identificado: mandado (genérico)")
            return "mandado", tipos_info["mandado"]

        # Se nada bateu, fazer fallback com regex antes de retornar documento genérico
        logging.warning(f"⚠️ Tipo não reconhecido pela IA: '{tipo_identificado}' - tentando regex")
        texto_lower = texto.lower()

        # Verificar mandado primeiro (maior prioridade)
        if any(palavra in texto_lower for palavra in ["mandado", "oficial de justiça", "cumpra-se", "mandado de"]):
            logging.info("✅ Tipo identificado por regex: mandado")
            return "mandado", tipos_info["mandado"]

        # Outros tipos
        if any(palavra in texto_lower for palavra in ["sentença", "julgo procedente", "julgo improcedente"]):
            return "sentenca", tipos_info["sentenca"]
        if "acórdão" in texto_lower or "acordão" in texto_lower:
            return "acordao", tipos_info["acordao"]
        if "intimação" in texto_lower or "intimacao" in texto_lower:
            return "intimacao", tipos_info["intimacao"]

        logging.warning(f"⚠️ Nenhum tipo reconhecido - usando 'mandado' como padrão seguro")
        return "mandado", tipos_info["mandado"]  # Mudado de "documento" para "mandado" como padrão seguro

    except Exception as e:
        logging.error(f"❌ ERRO ao identificar tipo com Gemini: {e}", exc_info=True)
        # Fallback para regex simples em caso de erro
        texto_lower = texto.lower()

        if any(palavra in texto_lower for palavra in ["julgo procedente", "julgo improcedente", "sentença"]):
            logging.info("⚠️ Fallback regex: sentenca")
            return "sentenca", {"urgencia": "ALTA", "acao_necessaria": "Verificar prazo para recurso"}
        elif "acórdão" in texto_lower:
            logging.info("⚠️ Fallback regex: acordao")
            return "acordao", {"urgencia": "MÉDIA", "acao_necessaria": "Analisar decisão do recurso"}
        elif "mandado" in texto_lower:
            logging.info("⚠️ Fallback regex: mandado")
            return "mandado", {"urgencia": "MÁXIMA", "acao_necessaria": "Ler e tomar providências URGENTE"}
        else:
            logging.info("⚠️ Fallback regex: documento genérico")
            return "documento", {"urgencia": "MÉDIA", "acao_necessaria": "Ler com atenção"}

def analisar_recursos_cabiveis(tipo_doc, texto):
    """Analisa se cabe recurso baseado APENAS no documento"""
    texto_lower = texto.lower()

    # Verifica se é Juizado Especial
    eh_juizado = "juizado especial" in texto_lower

    # Busca prazo REAL mencionado no documento
    prazo_encontrado = None
    prazo_patterns = [
        r'prazo\s+(?:de\s+)?(\d+)\s+dias?(?:\s+úteis)?(?:\s+para\s+(?:recorrer|interpor\s+recurso))?',
        r'recurso.*?(?:no\s+)?prazo\s+de\s+(\d+)\s+dias?',
        r'interpor\s+recurso.*?(\d+)\s+dias?'
    ]

    import re
    for pattern in prazo_patterns:
        match = re.search(pattern, texto_lower)
        if match:
            prazo_encontrado = f"{match.group(1)} dias"
            break

    recursos_info = {
        "sentenca": {
            "cabe_recurso": "Sim",
            "prazo": prazo_encontrado,  # Só mostra se encontrado no documento
            "dica": "Sem advogado ou Defensor Público? Procure Juizado!" if eh_juizado else "Procure advogado ou Defensoria Pública"
        },
        "acordao": {
            "cabe_recurso": "Sim (procure seu advogado ou defensor público)",
            "prazo": prazo_encontrado,  # Só mostra se encontrado no documento
            "dica": "Recursos em tribunais superiores - necessário advogado ou defensor público"
        },
        "decisao_interlocutoria": {
            "cabe_recurso": "Sim (decisão interlocutória)",
            "prazo": prazo_encontrado,  # Só mostra se encontrado no documento
            "dica": "Recurso urgente - consulte advogado imediatamente"
        },
        "despacho": {
            "cabe_recurso": "Não",
            "observacao": "Despacho não comporta recurso",
            "dica": "Apenas cumpra o determinado ou aguarde próxima movimentação"
        }
    }

    return recursos_info.get(tipo_doc, None)

def extrair_dados_estruturados(texto):
    """Extrai todos os dados importantes do documento"""
    import re
    from datetime import datetime, timedelta

    dados = {
        "numero_processo": None,
        "partes": {"autor": None, "reu": None},
        "valores": {
            "danos_morais": None,
            "danos_materiais": None,
            "lucros_cessantes": None,
            "valor_causa": None,
            "honorarios": None,
            "custas": None,
            "total": None
        },
        "prazos": [],
        "datas_importantes": {},
        "decisao": None,
        "autoridade": None,
        "audiencias": [],
        "tipo_acao": None,
        "links_audiencia": [],  # NOVO: Links de audiência online
        "telefones": [],  # NOVO: Telefones de contato
        "emails": [],  # NOVO: Emails
        "qr_codes": [],  # NOVO: QR codes encontrados
        "termo_paciente": False  # NOVO: Se usa termo "paciente" (habeas corpus)
    }

    # Número do processo (formatos variados)
    processo_patterns = [
        r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}',  # CNJ
        r'\d{4}\.\d{2}\.\d{6}-\d',  # Antigo
        r'Processo\s+n[º°]?\s*([\d\.\-\/]+)'
    ]

    for pattern in processo_patterns:
        match = re.search(pattern, texto, re.IGNORECASE)
        if match:
            dados["numero_processo"] = match.group()
            break

    # Identificar partes com múltiplos padrões
    # NOVO: Incluindo "Paciente" para Habeas Corpus
    autor_patterns = [
        r'(?:Paciente):\s*([^,\n]+)',  # Prioridade para Paciente (Habeas Corpus)
        r'(?:Autor|Requerente|Exequente|Reclamante|Impetrante):\s*([^,\n]+)',
        r'([A-ZÀ-Ú][A-Za-zà-ú\s]+)\s*(?:moveu|ajuizou|propôs|requereu)'
    ]

    reu_patterns = [
        r'(?:Réu|Requerido|Executado|Reclamado|Impetrado):\s*([^,\n]+)',
        r'em\s+face\s+de\s+([A-ZÀ-Ú][A-Za-zà-ú\s]+)'
    ]

    # Detectar se usa termo "paciente" (Habeas Corpus)
    if re.search(r'(?:Paciente):\s*', texto, re.IGNORECASE):
        dados["termo_paciente"] = True

    for pattern in autor_patterns:
        match = re.search(pattern, texto)
        if match:
            dados["partes"]["autor"] = match.group(1).strip()
            break

    for pattern in reu_patterns:
        match = re.search(pattern, texto)
        if match:
            dados["partes"]["reu"] = match.group(1).strip()
            break

    # Extração detalhada de valores
    # Procurar especificamente no dispositivo
    dispositivo_match = re.search(
        r'(?:DISPOSITIVO|DECIDE|JULGO|ACORDAM).*?(?=Publique-se|P\.R\.I\.|Intimem-se|$)',
        texto, re.IGNORECASE | re.DOTALL
    )

    texto_busca = dispositivo_match.group(0) if dispositivo_match else texto

    # Danos morais
    danos_morais_patterns = [
        r'danos?\s+morais?.*?R\$\s*([\d\.,]+)',
        r'indenização.*?moral.*?R\$\s*([\d\.,]+)',
        r'R\$\s*([\d\.,]+).*?danos?\s+morais?'
    ]

    for pattern in danos_morais_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE | re.DOTALL)
        if match:
            dados["valores"]["danos_morais"] = match.group(1)
            break

    # Danos materiais
    danos_materiais_patterns = [
        r'danos?\s+materiais?.*?R\$\s*([\d\.,]+)',
        r'danos?\s+emergentes?.*?R\$\s*([\d\.,]+)'
    ]

    for pattern in danos_materiais_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE | re.DOTALL)
        if match:
            dados["valores"]["danos_materiais"] = match.group(1)
            break

    # Honorários
    honorarios_match = re.search(r'honorários.*?(\d+)\s*%', texto, re.IGNORECASE)
    if honorarios_match:
        dados["valores"]["honorarios"] = f"{honorarios_match.group(1)}%"

    # Valor da causa
    valor_causa_match = re.search(r'valor\s+da\s+causa.*?R\$\s*([\d\.,]+)', texto, re.IGNORECASE)
    if valor_causa_match:
        dados["valores"]["valor_causa"] = valor_causa_match.group(1)

    # Calcular total se possível
    total = 0
    for key in ["danos_morais", "danos_materiais", "lucros_cessantes"]:
        if dados["valores"][key]:
            valor_str = dados["valores"][key].replace(".", "").replace(",", ".")
            try:
                total += float(valor_str)
            except:
                pass

    if total > 0:
        dados["valores"]["total"] = f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Extrair prazos
    prazo_patterns = [
        r'prazo\s+de\s+(\d+)\s+(dias?(?:\s+úteis)?)',
        r'(\d+)\s+(dias?(?:\s+úteis)?)\s+para',
        r'no\s+prazo\s+de\s+(\d+)\s+(dias?)'
    ]

    for pattern in prazo_patterns:
        matches = re.findall(pattern, texto, re.IGNORECASE)
        for match in matches:
            prazo = f"{match[0]} {match[1]}"
            if prazo not in dados["prazos"]:
                dados["prazos"].append(prazo)

    # Identificar decisão (sem interpretar se ganhou/perdeu - isso depende da perspectiva)
    if re.search(r'julgo\s+procedentes?\s+os\s+pedidos', texto, re.IGNORECASE):
        dados["decisao"] = "PROCEDENTE"
    elif re.search(r'julgo\s+improcedentes?\s+os\s+pedidos', texto, re.IGNORECASE):
        dados["decisao"] = "IMPROCEDENTE"
    elif re.search(r'julgo\s+parcialmente\s+procedentes?', texto, re.IGNORECASE):
        dados["decisao"] = "PARCIALMENTE PROCEDENTE"
    elif re.search(r'homologo.*?acordo', texto, re.IGNORECASE):
        dados["decisao"] = "ACORDO HOMOLOGADO"

    # Identificar autoridade
    juiz_match = re.search(r'(?:Juiz|Juíza)(?:\s+de\s+Direito)?:\s*([A-ZÀ-Ú][A-Za-zà-ú\s]+)', texto)
    if juiz_match:
        dados["autoridade"] = f"Juiz(a): {juiz_match.group(1).strip()}"
    else:
        desembargador_match = re.search(r'(?:Desembargador|Relator):\s*([A-ZÀ-Ú][A-Za-zà-ú\s]+)', texto)
        if desembargador_match:
            dados["autoridade"] = f"Desembargador(a): {desembargador_match.group(1).strip()}"

    # Extrair audiências
    audiencia_patterns = [
        r'audiência.*?dia\s+(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}).*?(\d{1,2}[:h]\d{2})',
        r'(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}).*?às?\s+(\d{1,2}[:h]\d{2}).*?audiência'
    ]

    for pattern in audiencia_patterns:
        matches = re.findall(pattern, texto, re.IGNORECASE)
        for match in matches:
            dados["audiencias"].append({
                "data": match[0],
                "hora": match[1].replace("h", ":")
            })

    # NOVO: Extrair links de audiência online (Zoom, Teams, Meet, etc.)
    link_patterns = [
        r'https?://(?:zoom\.us|teams\.microsoft\.com|meet\.google\.com|meet\.jit\.si)[^\s<>\)]+',
        r'https?://[^\s<>\)]+(?:audiencia|reuniao|meeting|room)[^\s<>\)]+',
        r'(?:zoom|teams|meet|jitsi).*?(?:https?://[^\s<>\)]+)'
    ]

    for pattern in link_patterns:
        matches = re.findall(pattern, texto, re.IGNORECASE)
        for match in matches:
            if match not in dados["links_audiencia"]:
                dados["links_audiencia"].append(match)

    # NOVO: Extrair telefones (apenas telefones brasileiros válidos COM CONTEXTO)
    # Buscar telefones apenas quando aparecem próximos a palavras-chave
    telefone_keywords = r'(?:tel(?:efone)?|fone|contato|celular|cel\.|whatsapp|wpp)'

    # Palavras que indicam que NÃO é telefone (chave, processo, etc.)
    palavras_excluir = r'(?:chave|processo|código|cod\.|protocolo|cpf|cnpj|rg|identidade)'

    # Padrão 1: Palavra-chave seguida de telefone formatado
    # Ex: "Telefone: (11) 98765-4321" ou "Contato: 11 98765-4321"
    # Usar regex com captura de contexto para validar
    pattern1_completo = rf'(.{{0,50}}){telefone_keywords}[:\s]+\(?(\d{{2}})\)?[\s-]*(9?\d{{4,5}})[\s-]*(\d{{4}})(.{{0,50}})'
    matches = re.findall(pattern1_completo, texto, re.IGNORECASE)

    for match in matches:
        contexto_antes = match[0]
        ddd = match[1]
        parte1 = match[2]
        parte2 = match[3]
        contexto_depois = match[4]

        # Verificar se tem palavras de exclusão no contexto
        contexto_total = contexto_antes + contexto_depois
        if re.search(palavras_excluir, contexto_total, re.IGNORECASE):
            continue

        # Validar DDD (11-99)
        try:
            ddd_num = int(ddd)
            if ddd_num < 11 or ddd_num > 99:
                continue
        except:
            continue

        # Validar se não é CPF/CNPJ (não pode ter 11 dígitos seguidos sem separação)
        numero_completo = ddd + parte1 + parte2
        if len(numero_completo) != 10 and len(numero_completo) != 11:
            continue

        # Validar formato: celular deve começar com 9 e ter 5 dígitos, fixo 4 dígitos
        if len(parte1) == 5:
            if not parte1.startswith('9'):
                continue
        elif len(parte1) == 4:
            # Fixo: primeiro dígito deve ser 2-5
            if parte1[0] not in ['2', '3', '4', '5']:
                continue
        else:
            continue

        # Formatar telefone
        telefone = f"({ddd}) {parte1}-{parte2}"
        if telefone not in dados["telefones"]:
            dados["telefones"].append(telefone)

    # Padrão 2: Telefone com formatação clara (parênteses e hífen) COM CONTEXTO
    # Ex: "(11) 98765-4321" ou "(11)98765-4321"
    pattern2_completo = r'(.{0,50})\((\d{2})\)\s*(9\d{4})-(\d{4})(.{0,50})'
    matches = re.findall(pattern2_completo, texto)

    for match in matches:
        contexto_antes = match[0]
        ddd = match[1]
        parte1 = match[2]
        parte2 = match[3]
        contexto_depois = match[4]

        # Verificar se tem palavras de exclusão no contexto
        contexto_total = contexto_antes + contexto_depois
        if re.search(palavras_excluir, contexto_total, re.IGNORECASE):
            continue

        # Validar DDD
        try:
            ddd_num = int(ddd)
            if ddd_num < 11 or ddd_num > 99:
                continue
        except:
            continue

        telefone = f"({ddd}) {parte1}-{parte2}"
        if telefone not in dados["telefones"]:
            dados["telefones"].append(telefone)

    # NOVO: Extrair emails
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(email_pattern, texto)
    for email in matches:
        if email not in dados["emails"]:
            dados["emails"].append(email)

    # NOVO: Detectar menções a QR Code
    if re.search(r'(?:QR\s*Code|código\s+QR|qrcode)', texto, re.IGNORECASE):
        dados["qr_codes"].append("QR Code mencionado no documento (visualize o PDF original)")

    return dados

def detectar_perspectiva_automatica(texto, dados_extraidos):
    """Usa IA para detectar automaticamente se usuário é autor ou réu"""

    # Pegar trecho relevante do documento
    texto_analise = texto[:2000] if len(texto) > 2000 else texto

    prompt = f"""Analise este documento jurídico e identifique qual é a perspectiva correta do USUÁRIO que enviou o documento.

INFORMAÇÕES DO DOCUMENTO:
- Autor/Requerente: {dados_extraidos.get('partes', {}).get('autor', 'Não identificado')}
- Réu/Requerido: {dados_extraidos.get('partes', {}).get('reu', 'Não identificado')}
- Decisão: {dados_extraidos.get('decisao', 'Não identificada')}

DOCUMENTO:
{texto_analise}

IMPORTANTE: Determine se o usuário que ENVIOU este documento provavelmente é:
- "autor": Se for quem MOVEU a ação, está processando alguém, é o requerente/autor
- "reu": Se está SENDO PROCESSADO, é quem está se defendendo, é o requerido/réu

Responda APENAS com uma palavra: "autor" ou "reu"
Analise o contexto e determine qual a perspectiva mais provável."""

    try:
        model = genai.GenerativeModel(GEMINI_MODELS[1]["name"])  # Flash para rapidez
        response = model.generate_content(prompt)
        perspectiva = response.text.strip().lower()

        if "autor" in perspectiva:
            return "autor"
        elif "reu" in perspectiva or "réu" in perspectiva:
            return "reu"
        else:
            return "autor"  # Padrão

    except Exception as e:
        logging.error(f"Erro ao detectar perspectiva com IA: {e}")
        # Fallback: tentar detectar pelo tipo de documento
        if "citação" in texto.lower() or "citado" in texto.lower():
            return "reu"
        return "autor"

def gerar_chat_contextual(texto_original, dados_extraidos):
    """Prepara contexto para o chat baseado APENAS no documento"""
    # NÃO armazenar documento_original para evitar sessão muito grande
    # O documento será lido do arquivo temporário quando necessário
    contexto = {
        "dados_extraidos": dados_extraidos,
        "perguntas_sugeridas": [],
        "respostas_preparadas": {}
    }

    # Gerar perguntas sugeridas baseadas no que foi encontrado
    if dados_extraidos["valores"]["total"]:
        contexto["perguntas_sugeridas"].append("Qual o valor total que vou receber?")
        contexto["respostas_preparadas"]["valor_total"] = f"Segundo o documento, o valor total é {dados_extraidos['valores']['total']}"

    if dados_extraidos["prazos"]:
        contexto["perguntas_sugeridas"].append("Quais são os prazos importantes?")
        prazos_texto = ", ".join(dados_extraidos["prazos"])
        contexto["respostas_preparadas"]["prazos"] = f"Os prazos mencionados no documento são: {prazos_texto}"

    if dados_extraidos["audiencias"]:
        contexto["perguntas_sugeridas"].append("Quando é a audiência?")
        aud = dados_extraidos["audiencias"][0]
        contexto["respostas_preparadas"]["audiencia"] = f"A audiência está marcada para {aud['data']} às {aud['hora']}"

    if dados_extraidos["decisao"]:
        contexto["perguntas_sugeridas"].append("Qual foi a decisão?")
        contexto["respostas_preparadas"]["decisao"] = f"A decisão foi: {dados_extraidos['decisao']}"

    return contexto

def adaptar_perspectiva_autor(texto, dados):
    """Adapta o texto e dados para a perspectiva do autor (mais pessoal)"""
    # Substituições para deixar o texto mais pessoal
    texto = texto.replace("A parte autora", "Você")
    texto = texto.replace("a parte autora", "você")
    texto = texto.replace("O requerente", "Você")
    texto = texto.replace("o requerente", "você")
    texto = texto.replace("O autor", "Você")
    texto = texto.replace("o autor", "você")
    texto = texto.replace("ao autor", "a você")
    texto = texto.replace("do autor", "seu/sua")
    texto = texto.replace("da parte autora", "sua")
    texto = texto.replace("pela parte autora", "por você")
    texto = texto.replace("foi determinado que a parte autora", "foi determinado que você")
    texto = texto.replace("a parte autora deverá", "você deverá")
    texto = texto.replace("a parte autora deve", "você deve")

    # Adaptar decisão para perspectiva do autor
    if dados.get("decisao"):
        if dados["decisao"] == "PROCEDENTE":
            dados["decisao"] = "PROCEDENTE (✅ Você ganhou)"
            texto = texto.replace("PROCEDENTE", "PROCEDENTE (✅ Você ganhou)")
        elif dados["decisao"] == "IMPROCEDENTE":
            dados["decisao"] = "IMPROCEDENTE (❌ Você perdeu)"
            texto = texto.replace("IMPROCEDENTE", "IMPROCEDENTE (❌ Você perdeu)")
        elif dados["decisao"] == "PARCIALMENTE PROCEDENTE":
            dados["decisao"] = "PARCIALMENTE PROCEDENTE (⚖️ Vitória parcial)"
            texto = texto.replace("PARCIALMENTE PROCEDENTE", "PARCIALMENTE PROCEDENTE (⚖️ Vitória parcial)")

    return texto

def adaptar_perspectiva_reu(texto, dados):
    """Adapta o texto e dados para a perspectiva do réu (mais pessoal)"""
    # Substituições para deixar o texto mais pessoal
    texto = texto.replace("A parte ré", "Você")
    texto = texto.replace("a parte ré", "você")
    texto = texto.replace("O requerido", "Você")
    texto = texto.replace("o requerido", "você")
    texto = texto.replace("O réu", "Você")
    texto = texto.replace("o réu", "você")
    texto = texto.replace("ao réu", "a você")
    texto = texto.replace("do réu", "seu/sua")
    texto = texto.replace("da parte ré", "sua")
    texto = texto.replace("pela parte ré", "por você")
    texto = texto.replace("foi determinado que a parte ré", "foi determinado que você")
    texto = texto.replace("a parte ré deverá", "você deverá")
    texto = texto.replace("a parte ré deve", "você deve")

    # Adaptar decisão para perspectiva do réu (INVERSO do autor!)
    if dados.get("decisao"):
        if dados["decisao"] == "PROCEDENTE":
            dados["decisao"] = "PROCEDENTE (❌ Você perdeu - pedido do autor foi aceito)"
            texto = texto.replace("PROCEDENTE", "PROCEDENTE (❌ Você perdeu - pedido do autor foi aceito)")
        elif dados["decisao"] == "IMPROCEDENTE":
            dados["decisao"] = "IMPROCEDENTE (✅ Você ganhou - pedido do autor foi negado)"
            texto = texto.replace("IMPROCEDENTE", "IMPROCEDENTE (✅ Você ganhou - pedido do autor foi negado)")
        elif dados["decisao"] == "PARCIALMENTE PROCEDENTE":
            dados["decisao"] = "PARCIALMENTE PROCEDENTE (⚖️ Resultado misto)"
            texto = texto.replace("PARCIALMENTE PROCEDENTE", "PARCIALMENTE PROCEDENTE (⚖️ Resultado misto)")

    return texto

def validar_tipo_pergunta(pergunta):
    """Valida e classifica o tipo de pergunta"""
    pergunta_lower = pergunta.lower()

    # Perguntas VÁLIDAS (sobre o documento)
    perguntas_validas = {
        "valores": ["quanto", "valor", "receber", "pagar", "multa", "indenização", "honorários", "custas", "danos morais", "danos materiais"],
        "prazos": ["prazo", "dias", "quando", "vence", "tempo", "recurso", "contestar"],
        "partes": ["quem", "autor", "réu", "juiz", "advogado", "desembargador"],
        "decisao": ["ganhou", "perdeu", "decidiu", "resultado", "procedente", "improcedente", "sentença", "cabe recurso"]
    }

    # Perguntas INVÁLIDAS (bloqueadas)
    perguntas_invalidas = {
        "juridicas_gerais": ["o que é", "como funciona", "explica", "define", "significado"],
        "opiniao_legal": ["devo", "deveria", "melhor", "recomenda", "acha", "sugere", "vale a pena", "tenho chance"],
        "fora_documento": ["custa", "onde fica", "horário", "telefone", "endereço"]
    }

    # Verificar se é pergunta inválida primeiro
    for tipo, palavras in perguntas_invalidas.items():
        if any(palavra in pergunta_lower for palavra in palavras):
            return {"valida": False, "tipo": tipo}

    # Verificar se é pergunta válida
    for tipo, palavras in perguntas_validas.items():
        if any(palavra in pergunta_lower for palavra in palavras):
            return {"valida": True, "tipo": tipo}

    # Pergunta não classificada
    return {"valida": None, "tipo": "desconhecida"}

def calcular_prazo_restante(data_intimacao, prazo_dias):
    """Calcula dias restantes considerando dias úteis"""
    try:
        from datetime import datetime, timedelta

        # Parse da data de intimação
        data_int = datetime.strptime(data_intimacao, "%d/%m/%Y")
        hoje = datetime.now()

        # Calcular data final (simplificado - não considera feriados)
        data_final = data_int + timedelta(days=prazo_dias * 1.4)  # Fator para dias úteis

        diferenca = (data_final - hoje).days

        if diferenca < 0:
            return {"vencido": True, "dias": abs(diferenca), "status": "VENCIDO"}
        elif diferenca <= 5:
            return {"vencido": False, "dias": diferenca, "status": "URGENTE"}
        else:
            return {"vencido": False, "dias": diferenca, "status": "OK"}
    except:
        return None

def gerar_checklist_personalizado(dados, tipo_doc):
    """Gera checklist baseado no tipo de documento"""
    checklist = []

    if tipo_doc in ["mandado_citacao", "mandado_intimacao"]:
        checklist.append("⚠️ URGENTE - Procurar advogado ou Defensoria Pública IMEDIATAMENTE")
        checklist.append("📋 Levar este documento impresso")
        checklist.append("📝 Reunir documentos e provas relacionadas ao caso")
        if dados.get("prazos"):
            checklist.append(f"⏰ Não perder o prazo: {dados['prazos'][0]}")

    elif tipo_doc == "sentenca":
        if dados.get("decisao"):
            if "PROCEDENTE" in dados["decisao"]:
                checklist.append("✅ Você ganhou! Analisar se aceita o valor ou se quer recorrer")
            elif "IMPROCEDENTE" in dados["decisao"]:
                checklist.append("⚠️ Avaliar possibilidade de recurso com advogado")

        checklist.append("📅 Verificar prazo para recurso (geralmente 15 dias)")
        if dados.get("valores", {}).get("total"):
            checklist.append(f"💰 Valor em jogo: {dados['valores']['total']}")

    elif tipo_doc == "intimacao":
        if dados.get("audiencias"):
            aud = dados["audiencias"][0]
            checklist.append(f"📅 Comparecer na audiência: {aud['data']} às {aud['hora']}")
            checklist.append("👔 Ir com traje adequado")
            checklist.append("📋 Levar documentos originais e cópias")

    return checklist

def processar_pergunta_contextual(pergunta, contexto):
    """Processa pergunta garantindo resposta APENAS do documento"""
    pergunta_lower = pergunta.lower()
    dados = contexto.get("dados_extraidos", {})
    documento = contexto.get("documento_original", "")

    # 1. VALIDAR TIPO DE PERGUNTA
    validacao = validar_tipo_pergunta(pergunta)

    # 2. BLOQUEAR PERGUNTAS INVÁLIDAS
    if validacao["valida"] == False:
        if validacao["tipo"] == "juridicas_gerais":
            return {
                "texto": "❌ Não posso dar explicações jurídicas gerais.\n\n💡 Posso responder sobre o SEU documento. Pergunte sobre:\n• Valores mencionados\n• Prazos\n• Partes envolvidas\n• Decisão do juiz",
                "tipo": "bloqueado",
                "sugestoes": ["Qual o valor dos danos morais?", "Qual o prazo para recorrer?", "Eu ganhei ou perdi?"]
            }

        elif validacao["tipo"] == "opiniao_legal":
            informacoes = []
            if dados.get("prazos"):
                informacoes.append(f"📅 Prazo: {dados['prazos'][0]}")
            if dados.get("valores", {}).get("total"):
                informacoes.append(f"💰 Valor: {dados['valores']['total']}")

            texto_info = "\n".join(informacoes) if informacoes else ""

            return {
                "texto": f"❌ Não posso dar conselhos jurídicos.\n\n📄 O que SEU documento diz:\n{texto_info}\n\n⚖️ Para decidir sobre ações (recorrer, fazer acordo, etc.), consulte um advogado ou a Defensoria Pública. Leve este documento!",
                "tipo": "redirecionamento_profissional"
            }

        elif validacao["tipo"] == "fora_documento":
            return {
                "texto": "❌ Só posso responder sobre o documento que você enviou.\n\nℹ️ Para informações sobre custos, endereços e horários, consulte os canais oficiais do tribunal.",
                "tipo": "fora_escopo"
            }

    # 3. PROCESSAR PERGUNTAS VÁLIDAS

    # VALORES
    if validacao.get("tipo") == "valores" or any(word in pergunta_lower for word in ["quanto", "valor"]):
        respostas = []
        valores = dados.get("valores", {})

        # Total (prioridade máxima - mostrar primeiro se existir)
        if valores.get("total"):
            # Se pergunta sobre total, receber, ou valores em geral
            if "total" in pergunta_lower or "receber" in pergunta_lower or "quanto" in pergunta_lower:
                respostas.append(f"💵 **VALOR TOTAL:** {valores['total']}")
                respostas.append("⚠️ Valores sujeitos a correção monetária e juros até o pagamento")

        # Danos morais
        if valores.get("danos_morais"):
            if "moral" in pergunta_lower or (not respostas and ("receber" in pergunta_lower or "quanto" in pergunta_lower)):
                valor = valores["danos_morais"]
                respostas.append(f"\n💰 **Danos morais:** R$ {valor}")
                respostas.append("📍 Este valor está no dispositivo da sentença")

        # Danos materiais
        if valores.get("danos_materiais"):
            if "material" in pergunta_lower or (not respostas and ("receber" in pergunta_lower or "quanto" in pergunta_lower)):
                valor = valores["danos_materiais"]
                respostas.append(f"\n💰 **Danos materiais:** R$ {valor}")

        # Honorários
        if valores.get("honorarios"):
            if "honorário" in pergunta_lower or "advogado" in pergunta_lower:
                respostas.append(f"\n⚖️ **Honorários advocatícios:** R$ {valores['honorarios']}")

        # Custas
        if valores.get("custas"):
            if "custa" in pergunta_lower or "taxa" in pergunta_lower:
                respostas.append(f"\n📄 **Custas processuais:** R$ {valores['custas']}")

        # Valor da causa
        if valores.get("valor_causa"):
            if "causa" in pergunta_lower:
                respostas.append(f"\n📋 **Valor da causa:** R$ {valores['valor_causa']}")

        # Se não encontrou valores específicos mas a pergunta é sobre valores, mostrar TODOS os valores disponíveis
        if not respostas:
            valores_encontrados = []
            if valores.get("total"):
                valores_encontrados.append(f"💵 **TOTAL:** {valores['total']}")
            if valores.get("danos_morais"):
                valores_encontrados.append(f"💰 **Danos morais:** R$ {valores['danos_morais']}")
            if valores.get("danos_materiais"):
                valores_encontrados.append(f"💰 **Danos materiais:** R$ {valores['danos_materiais']}")
            if valores.get("honorarios"):
                valores_encontrados.append(f"⚖️ **Honorários:** R$ {valores['honorarios']}")
            if valores.get("custas"):
                valores_encontrados.append(f"📄 **Custas:** R$ {valores['custas']}")
            if valores.get("valor_causa"):
                valores_encontrados.append(f"📋 **Valor da causa:** R$ {valores['valor_causa']}")

            if valores_encontrados:
                respostas = valores_encontrados
                respostas.append("\n⚠️ Valores sujeitos a correção monetária")

        if respostas:
            return {
                "texto": "\n".join(respostas),
                "tipo": "resposta",
                "referencia": "valores_extraidos"
            }
        else:
            return {
                "texto": "❓ Não encontrei informações sobre valores neste documento.\n\nO documento pode não conter valores monetários ou eles não foram identificados.",
                "tipo": "nao_encontrado"
            }

    # PRAZOS
    if validacao.get("tipo") == "prazos" or any(word in pergunta_lower for word in ["prazo", "quando", "dias"]):
        if dados.get("prazos"):
            prazos_texto = "\n• ".join(dados["prazos"])

            texto = f"📅 **Prazos mencionados no documento:**\n• {prazos_texto}"
            texto += "\n\n⚠️ Confirme estes prazos no documento original e consulte um advogado URGENTEMENTE se houver prazo para contestação ou recurso."

            return {
                "texto": texto,
                "tipo": "resposta",
                "referencia": "prazos_extraidos"
            }
        else:
            return {
                "texto": "❓ Não encontrei prazos específicos neste documento.",
                "tipo": "nao_encontrado"
            }

    # PARTES
    if validacao.get("tipo") == "partes" or any(word in pergunta_lower for word in ["quem", "autor", "réu", "juiz"]):
        respostas = []

        if dados.get("partes", {}).get("autor"):
            respostas.append(f"👤 **Autor:** {dados['partes']['autor']}")
        if dados.get("partes", {}).get("reu"):
            respostas.append(f"👤 **Réu:** {dados['partes']['reu']}")
        if dados.get("autoridade"):
            respostas.append(f"👨‍⚖️ **{dados['autoridade']}**")

        if respostas:
            return {
                "texto": "\n".join(respostas),
                "tipo": "resposta",
                "referencia": "partes"
            }

    # DECISÃO
    if validacao.get("tipo") == "decisao" or any(word in pergunta_lower for word in ["ganhou", "perdeu", "decidiu", "resultado", "decisão"]):
        if dados.get("decisao"):
            # A decisão já vem adaptada pela função de perspectiva (autor ou réu)
            texto = f"⚖️ **Decisão:** {dados['decisao']}\n\n"

            # Informações sobre recurso
            if any(word in pergunta_lower for word in ["recurso", "cabe recurso"]):
                texto += "\n📋 Consulte um advogado ou Defensoria Pública URGENTEMENTE para avaliar se vale a pena recorrer."
            else:
                texto += "💡 Dica: Se não concordar com a decisão, consulte um advogado sobre a possibilidade de recurso."

            return {
                "texto": texto,
                "tipo": "resposta",
                "referencia": "dispositivo"
            }

    # CHECKLIST
    if "fazer" in pergunta_lower or "próximos passos" in pergunta_lower or "preciso" in pergunta_lower:
        tipo_doc = dados.get("tipo_documento", "documento")
        checklist = gerar_checklist_personalizado(dados, tipo_doc)

        if checklist:
            texto = "📋 **Baseado no SEU documento, você deve:**\n\n"
            texto += "\n".join(f"{i+1}. {item}" for i, item in enumerate(checklist))

            return {
                "texto": texto,
                "tipo": "checklist"
            }

    # BUSCA GENÉRICA NO DOCUMENTO
    # Tentar encontrar informação relevante no texto
    resultado = buscar_no_documento(pergunta, documento, dados)
    if resultado:
            return {
                "texto": f"No documento consta: {resultado}",
                "tipo": "resposta",
                "referencia": "documento"
            }

    return {
        "texto": "Não encontrei essa informação no documento enviado. Posso ajudar com valores, prazos, partes ou decisões que estejam mencionados.",
        "tipo": "nao_encontrado"
    }

def buscar_no_documento(pergunta, documento, dados=None):
    """Busca informação específica no documento original"""
    if not documento:
        return None

    pergunta_lower = pergunta.lower()
    linhas = documento.split('\n')

    # Palavras-chave para busca
    palavras_busca = pergunta_lower.split()

    # Procurar linhas relevantes
    linhas_relevantes = []
    for linha in linhas:
        linha_lower = linha.lower()
        # Se a linha contém pelo menos 2 palavras da pergunta
        matches = sum(1 for palavra in palavras_busca if palavra in linha_lower and len(palavra) > 3)
        if matches >= 2:
            linhas_relevantes.append(linha.strip())

    if linhas_relevantes:
        # Retornar as 3 primeiras linhas mais relevantes
        resultado = " ".join(linhas_relevantes[:3])
        # Limitar tamanho
        if len(resultado) > 300:
            resultado = resultado[:300] + "..."
        return resultado

    return None

def extrair_valores_sentenca(texto):
    """Extrai valores monetários importantes da sentença"""
    valores = {
        "danos_morais": None,
        "danos_materiais": None,
        "lucros_cessantes": None,
        "honorarios": None,
        "valor_causa": None
    }
    
    # Procurar por valores de danos morais
    padrao_danos_morais = r'(?:danos?\s+morais?|indenização.*?moral).*?R\$\s*([\d\.,]+)'
    match = re.search(padrao_danos_morais, texto, re.IGNORECASE | re.DOTALL)
    if match:
        valores["danos_morais"] = match.group(1)
    
    # Procurar valores no dispositivo especificamente
    dispositivo_match = re.search(
        r'(DISPOSITIVO|DECIDE).*?(?=Cumpra-se|Intimem-se|P\.R\.I\.|$)', 
        texto, re.IGNORECASE | re.DOTALL
    )
    if dispositivo_match:
        dispositivo_texto = dispositivo_match.group(0)
        
        # Procurar "R$ XXX" no dispositivo
        valores_encontrados = re.findall(r'R\$\s*([\d\.]+,\d{2})', dispositivo_texto)
        if valores_encontrados:
            logging.info(f"Valores encontrados no dispositivo: {valores_encontrados}")
            # Assumir que o primeiro valor grande é danos morais
            for valor in valores_encontrados:
                valor_num = float(valor.replace('.', '').replace(',', '.'))
                if valor_num > 1000 and not valores["danos_morais"]:
                    valores["danos_morais"] = valor
                    break
    
    return valores

def processar_imagem_para_texto(image_bytes, formato='PNG'):
    """Extrai texto de uma imagem usando OCR com melhor pré-processamento"""
    texto = ""
    metadados = {
        "tipo": "imagem",
        "formato": formato,
        "usou_ocr": True,
        "dimensoes": None,
        "qualidade_ocr": "indefinida",
        "tesseract_disponivel": TESSERACT_AVAILABLE
    }
    
    if not TESSERACT_AVAILABLE:
        raise ValueError("OCR não está disponível neste servidor. Tesseract não foi encontrado.")
    
    try:
        # Abrir a imagem
        img = Image.open(io.BytesIO(image_bytes))
        
        # Salvar dimensões originais
        metadados["dimensoes"] = f"{img.width}x{img.height}"
        logging.info(f"Processando imagem: {metadados['dimensoes']}, formato: {formato}")
        
        # Converter para RGB se necessário
        if img.mode not in ('RGB', 'L'):
            original_mode = img.mode
            img = img.convert('RGB')
            logging.info(f"Convertido de {original_mode} para RGB")
        
        # Pré-processamento avançado com OpenCV se disponível
        if CV2_AVAILABLE:
            texto = processar_com_opencv(img, metadados)
        else:
            texto = processar_com_pil(img, metadados)
        
        # Limpar texto extraído
        texto = limpar_texto_ocr(texto)
        
        if not texto.strip():
            raise ValueError("Nenhum texto foi extraído da imagem")
        
        logging.info(f"OCR concluído. Qualidade: {metadados['qualidade_ocr']}, Caracteres: {len(texto)}")
        
    except Exception as e:
        logging.error(f"Erro ao processar imagem: {e}")
        raise
    
    return texto, metadados

def processar_com_opencv(img, metadados):
    """Processamento avançado com OpenCV"""
    logging.info("Usando processamento avançado com OpenCV")
    
    # Converter PIL para OpenCV
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    
    # Redimensionar se muito grande (otimização)
    height, width = img_cv.shape[:2]
    if width > 3000 or height > 3000:
        scale = min(3000/width, 3000/height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        img_cv = cv2.resize(img_cv, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        logging.info(f"Imagem redimensionada para {new_width}x{new_height}")
    
    # Converter para escala de cinza
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    
    # Aplicar filtros para melhorar OCR
    # 1. Denoising
    denoised = cv2.fastNlMeansDenoising(gray)
    
    # 2. Aumentar contraste
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    contrast = clahe.apply(denoised)
    
    # 3. Binarização adaptativa
    binary = cv2.adaptiveThreshold(contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                 cv2.THRESH_BINARY, 11, 2)
    
    # Converter de volta para PIL
    img_processed = Image.fromarray(binary)
    
    return executar_ocr_multiplas_configs(img_processed, metadados)

def processar_com_pil(img, metadados):
    """Processamento básico com PIL"""
    logging.info("Usando processamento básico com PIL")
    
    # Redimensionar se muito grande
    if img.width > 3000 or img.height > 3000:
        ratio = min(3000/img.width, 3000/img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        logging.info(f"Imagem redimensionada para {new_size}")
    
    # Aumentar contraste
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    
    # Converter para escala de cinza
    img = img.convert('L')
    
    # Aplicar threshold para binarização
    threshold = 180
    img = img.point(lambda p: 255 if p > threshold else 0)
    
    return executar_ocr_multiplas_configs(img, metadados)

def executar_ocr_multiplas_configs(img_processed, metadados):
    """Executa OCR com múltiplas configurações e escolhe o melhor resultado"""
    
    # Configurações otimizadas do Tesseract
    custom_configs = [
        r'--oem 3 --psm 6 -l por+eng',  # Melhor para documentos
        r'--oem 3 --psm 3 -l por+eng',  # Automático
        r'--oem 3 --psm 4 -l por+eng',  # Coluna única
        r'--oem 3 --psm 6 -l por',      # Só português
        r'--oem 3 --psm 3 -l eng',      # Só inglês
    ]
    
    # Se português não estiver disponível, usar apenas inglês
    if 'por' not in TESSERACT_LANGS:
        custom_configs = [
            r'--oem 3 --psm 6 -l eng',
            r'--oem 3 --psm 3 -l eng',
            r'--oem 3 --psm 4 -l eng',
        ]
        logging.warning("Português não disponível, usando apenas inglês")
    
    best_text = ""
    best_score = 0
    
    for i, config in enumerate(custom_configs):
        try:
            logging.info(f"Tentativa OCR {i+1}/{len(custom_configs)}: {config}")
            texto_temp = pytesseract.image_to_string(img_processed, config=config)
            
            # Avaliar qualidade do texto
            score = avaliar_qualidade_texto(texto_temp)
            logging.info(f"Score: {score}, Caracteres: {len(texto_temp.strip())}")
            
            if score > best_score or (score == best_score and len(texto_temp.strip()) > len(best_text.strip())):
                best_text = texto_temp
                best_score = score
                logging.info(f"Novo melhor resultado encontrado")
            
        except Exception as e:
            logging.warning(f"Erro com configuração {config}: {e}")
            continue
    
    # Avaliar qualidade final
    if len(best_text.strip()) < 50 or best_score < 0.3:
        metadados["qualidade_ocr"] = "baixa"
    elif len(best_text.strip()) < 200 or best_score < 0.6:
        metadados["qualidade_ocr"] = "média"
    else:
        metadados["qualidade_ocr"] = "boa"
    
    return best_text

def avaliar_qualidade_texto(texto):
    """Avalia a qualidade do texto extraído"""
    if not texto or len(texto.strip()) == 0:
        return 0
    
    # Proporção de caracteres alfabéticos
    alpha_ratio = sum(1 for c in texto if c.isalpha()) / len(texto)
    
    # Proporção de caracteres especiais/ruído
    special_ratio = sum(1 for c in texto if c in '!@#$%^&*()[]{}|\\<>?~`') / len(texto)
    
    # Proporção de espaços (texto bem formatado tem espaços)
    space_ratio = texto.count(' ') / len(texto)
    
    # Score combinado
    score = alpha_ratio * 0.6 + (1 - special_ratio) * 0.3 + min(space_ratio * 4, 0.1) * 1.0
    
    return min(score, 1.0)

def limpar_texto_ocr(texto):
    """Limpa e melhora o texto extraído via OCR"""
    if not texto:
        return ""
    
    # Remove caracteres de controle mantendo quebras de linha
    texto = ''.join(char if char.isprintable() or char in '\n\r\t' else ' ' for char in texto)
    
    # Remove linhas com apenas caracteres especiais
    linhas = texto.split('\n')
    linhas_limpas = []
    
    for linha in linhas:
        linha_strip = linha.strip()
        if linha_strip:
            # Conta caracteres alfabéticos
            alpha_count = sum(1 for c in linha_strip if c.isalpha())
            # Só mantém a linha se tiver pelo menos 30% de letras
            if len(linha_strip) > 0 and alpha_count / len(linha_strip) >= 0.3:
                linhas_limpas.append(linha)
    
    texto = '\n'.join(linhas_limpas)
    
    # Remove espaços múltiplos
    texto = re.sub(r' +', ' ', texto)
    
    # Remove quebras de linha múltiplas
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    
    return texto.strip()

def extrair_texto_pdf(pdf_bytes):
    """Extrai texto de PDF com melhor tratamento de erros e OCR otimizado"""
    texto = ""
    metadados = {
        "total_paginas": 0,
        "tem_texto": False,
        "usou_ocr": False,
        "paginas_com_ocr": [],
        "tipo": "pdf"
    }
    
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            total_pages = len(doc)
            metadados["total_paginas"] = total_pages
            logging.info(f"Processando PDF com {total_pages} páginas")
            
            texto_completo = ""
            
            for i, page in enumerate(doc):
                try:
                    # Primeiro tenta extrair texto normal
                    conteudo = page.get_text()
                    
                    if conteudo.strip():
                        metadados["tem_texto"] = True
                        texto_completo += conteudo + "\n"
                    # Se não há texto e OCR está disponível, tenta OCR
                    elif TESSERACT_AVAILABLE:
                        logging.info(f"Aplicando OCR na página {i+1}")
                        metadados["usou_ocr"] = True
                        metadados["paginas_com_ocr"].append(i+1)
                        
                        pix = page.get_pixmap(dpi=150)
                        img_data = pix.tobytes()
                        
                        # Usar a função melhorada de OCR
                        conteudo_ocr, _ = processar_imagem_para_texto(img_data, 'PNG')
                        texto_completo += conteudo_ocr + "\n"
                    
                except Exception as e:
                    logging.error(f"Erro ao processar página {i+1}: {e}")
            
            texto = texto_completo.strip()
            if not texto:
                raise ValueError("Nenhum texto foi extraído do PDF")
                
    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise
    
    return texto, metadados

def estimar_tokens(texto):
    """Estima número de tokens (aproximadamente 1 token = 4 caracteres para português)"""
    return len(texto) // 4

def truncar_texto_inteligente(texto, max_tokens=25000):
    """Trunca o texto preservando as partes mais importantes"""
    tokens_estimados = estimar_tokens(texto)
    
    if tokens_estimados <= max_tokens:
        return texto
    
    logging.warning(f"Texto muito grande ({tokens_estimados} tokens). Truncando para {max_tokens} tokens...")
    
    # Procurar seções importantes
    secoes_importantes = []
    
    # 1. DISPOSITIVO (PRIORIDADE MÁXIMA - NUNCA CORTAR)
    dispositivo_match = re.search(
        r'(III\s*-?\s*DISPOSITIVO|DISPOSITIVO|DECIDE-SE|ANTE O EXPOSTO|DIANTE DO EXPOSTO|ISTO POSTO).*?(?=(Publique-se|Cumpra-se|Intimem-se|P\.R\.I\.|Palmas|$))', 
        texto, re.IGNORECASE | re.DOTALL
    )
    if dispositivo_match:
        # Dispositivo COMPLETO, sem cortes
        secoes_importantes.append(("DISPOSITIVO [COMPLETO]", dispositivo_match.group(0), 12000))
    
    # 2. Identificação do processo
    inicio = texto[:3000]
    secoes_importantes.append(("IDENTIFICAÇÃO", inicio, 2000))
    
    # 3. Fundamentação (resumida SOMENTE se sobrar espaço)
    fundamentacao_match = re.search(
        r'(II\s*-?\s*FUNDAMENTAÇÃO|FUNDAMENTAÇÃO|FUNDAMENTO).*?(?=(III\s*-?\s*DISPOSITIVO|DISPOSITIVO|DECIDE|$))', 
        texto, re.IGNORECASE | re.DOTALL
    )
    if fundamentacao_match:
        fund_texto = fundamentacao_match.group(0)
        # Pegar só as primeiras 50 linhas da fundamentação
        fund_linhas = fund_texto.split('\n')[:50]
        secoes_importantes.append(("FUNDAMENTAÇÃO [RESUMO]", '\n'.join(fund_linhas), 8000))
    
    # Montar texto truncado
    texto_final = "=== DOCUMENTO TRUNCADO PARA PROCESSAMENTO ===\n\n"
    texto_final += "⚠️ IMPORTANTE: O DISPOSITIVO (decisão final e valores) FOI MANTIDO INTEGRALMENTE\n\n"
    
    tokens_usados = 0
    # Ordenar por prioridade (DISPOSITIVO primeiro)
    for nome, conteudo, tokens_max in secoes_importantes:
        if tokens_usados >= max_tokens:
            break
            
        caracteres_max = min(tokens_max * 4, (max_tokens - tokens_usados) * 4)
        if len(conteudo) > caracteres_max and "DISPOSITIVO" not in nome:
            # Só trunca se NÃO for dispositivo
            conteudo = conteudo[:caracteres_max] + "...[truncado]"
        
        texto_final += f"\n\n=== {nome} ===\n{conteudo}\n"
        tokens_usados += len(conteudo) // 4
    
    logging.info(f"Texto truncado de {tokens_estimados} para ~{tokens_usados} tokens (DISPOSITIVO preservado)")
    return texto_final

def analisar_complexidade_texto(texto):
    """Analisa a complexidade do texto para escolher o modelo apropriado"""
    complexidade = {
        "caracteres": len(texto),
        "palavras": len(texto.split()),
        "tokens_estimados": estimar_tokens(texto),
        "termos_tecnicos": 0,
        "citacoes": 0,
        "nivel": "baixo"  # baixo, médio, alto
    }
    
    # Termos técnicos comuns em documentos jurídicos
    termos_tecnicos = [
        "exordial", "sucumbência", "litispendência", "coisa julgada",
        "tutela antecipada", "liminar", "agravo", "embargo", "mandamus",
        "quantum", "extra petita", "ultra petita", "iura novit curia"
    ]
    
    texto_lower = texto.lower()
    for termo in termos_tecnicos:
        complexidade["termos_tecnicos"] += texto_lower.count(termo)
    
    # Contar citações de leis/artigos
    complexidade["citacoes"] = len(re.findall(r'art\.\s*\d+|artigo\s*\d+|§\s*\d+|lei\s*n[º°]\s*[\d\.]+', texto_lower))
    
    # Determinar nível de complexidade baseado em tokens
    if complexidade["tokens_estimados"] > 15000 or complexidade["termos_tecnicos"] > 20 or complexidade["citacoes"] > 15:
        complexidade["nivel"] = "alto"
    elif complexidade["tokens_estimados"] > 7000 or complexidade["termos_tecnicos"] > 10 or complexidade["citacoes"] > 8:
        complexidade["nivel"] = "médio"
    
    return complexidade

def escolher_modelo_gemini(complexidade, tentativa=0):
    """Escolhe o modelo Gemini mais apropriado baseado na complexidade"""
    # Sempre começar com o modelo mais leve
    if tentativa == 0:
        return GEMINI_MODELS[0]  # flash-8b
    elif tentativa == 1:
        return GEMINI_MODELS[1]  # flash
    else:
        return GEMINI_MODELS[2]  # pro

def simplificar_com_gemini(texto, max_retries=1):  # REDUZIDO para 1 retry
    """Chama a API do Gemini com fallback automático entre modelos"""
    
    # Truncar texto se necessário ANTES de enviar
    MAX_INPUT_TOKENS = 15000  # REDUZIDO para 15k (mais conservador)
    tokens_estimados = estimar_tokens(texto)
    
    if tokens_estimados > MAX_INPUT_TOKENS:
        logging.warning(f"Texto com {tokens_estimados} tokens. Truncando...")
        texto = truncar_texto_inteligente(texto, MAX_INPUT_TOKENS)
        tokens_estimados = estimar_tokens(texto)
        logging.info(f"Texto truncado para ~{tokens_estimados} tokens")
    valores_extraidos = extrair_valores_sentenca(texto)
    
    prompt_valores = ""
    if any(valores_extraidos.values()):
        prompt_valores = "\n\n**VALORES JÁ IDENTIFICADOS NO DOCUMENTO:**\n"
        if valores_extraidos["danos_morais"]:
            prompt_valores += f"- Danos morais: R$ {valores_extraidos['danos_morais']}\n"
        if valores_extraidos["danos_materiais"]:
            prompt_valores += f"- Danos materiais: R$ {valores_extraidos['danos_materiais']}\n"
        if valores_extraidos["lucros_cessantes"]:
            prompt_valores += f"- Lucros cessantes: R$ {valores_extraidos['lucros_cessantes']}\n"
        prompt_valores += "\n**USE ESTES VALORES NA SEÇÃO 'VALORES E OBRIGAÇÕES'**\n"
    
    prompt_completo = PROMPT_SIMPLIFICACAO + prompt_valores + "\n\n**TEXTO ORIGINAL:**\n" + texto
    # Verificar cache
    texto_hash = hashlib.md5(texto.encode()).hexdigest()
    if texto_hash in results_cache:
        cache_entry = results_cache[texto_hash]
        if time.time() - cache_entry["timestamp"] < CACHE_EXPIRATION:
            logging.info(f"Resultado encontrado no cache para hash {texto_hash[:8]}")
            return cache_entry["result"], None
    
    # Analisar complexidade
    complexidade = analisar_complexidade_texto(texto)
    logging.info(f"Complexidade: {complexidade['nivel']}, Tokens estimados: {tokens_estimados}")
    
    prompt_completo = PROMPT_SIMPLIFICACAO + texto
    
    headers = {
        "Content-Type": "application/json"
    }
    
    errors = []
    
    # Tentar com diferentes modelos (LIMITADO A 2 MODELOS para evitar timeout)
    max_tentativas = min(2, len(GEMINI_MODELS))  # Máximo 2 modelos
    
    for tentativa in range(max_tentativas):
        modelo = escolher_modelo_gemini(complexidade, tentativa)
        
        # Cada modelo pode ter múltiplas URLs (v1 e v1beta)
        urls = modelo.get("urls", [modelo.get("url")]) if isinstance(modelo.get("urls"), list) else [modelo.get("url")]
        
        for url_base in urls:
            if not url_base:
                continue
                
            logging.info(f"Tentativa {tentativa + 1}/{max_tentativas}: Modelo {modelo['name']}")
            
            model_usage_stats[modelo["name"]]["attempts"] += 1
            
            # Ajustar tokens de saída - REDUZIDO
            max_output_tokens = 1500  # REDUZIDO de 2048 para 1500
            
            # URL com API key como parâmetro (formato correto)
            url_with_key = f"{url_base}?key={GEMINI_API_KEY}"
        
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt_completo
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": max_output_tokens,
                    "topP": 0.85,
                    "topK": 20
                },
                "safetySettings": [
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "BLOCK_NONE"
                    },
                    {
                        "category": "HARM_CATEGORY_HATE_SPEECH",
                        "threshold": "BLOCK_NONE"
                    },
                    {
                        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        "threshold": "BLOCK_NONE"
                    },
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "BLOCK_NONE"
                    }
                ]
            }
            
            # APENAS 1 RETRY por modelo para evitar timeout
            try:
                start_time = time.time()
                response = requests.post(
                    url_with_key,
                    headers=headers,
                    json=payload,
                    timeout=25  # REDUZIDO de 90 para 25 segundos
                )
                
                elapsed = round(time.time() - start_time, 2)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        texto_simplificado = data["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # Adicionar ao cache
                        results_cache[texto_hash] = {
                            "result": texto_simplificado,
                            "timestamp": time.time(),
                            "modelo": modelo["name"]
                        }
                        
                        model_usage_stats[modelo["name"]]["successes"] += 1
                        logging.info(f"✅ Sucesso com {modelo['name']} em {elapsed}s")
                        
                        return texto_simplificado, None
                    else:
                        error_msg = f"{modelo['name']}: Resposta vazia"
                        errors.append(error_msg)
                        logging.warning(error_msg)
                        break  # Tentar próxima URL ou próximo modelo
                        
                elif response.status_code == 429:
                    error_msg = f"{modelo['name']}: Rate limit (429)"
                    errors.append(error_msg)
                    logging.warning(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    time.sleep(1)  # Pausa REDUZIDA
                    break  # Tentar próximo modelo
                    
                elif response.status_code == 400:
                    try:
                        error_data = response.json()
                        error_detail = error_data.get('error', {}).get('message', 'Erro desconhecido')
                        error_msg = f"{modelo['name']}: {error_detail[:100]}"
                    except:
                        error_msg = f"{modelo['name']}: Requisição inválida (400)"
                    
                    errors.append(error_msg)
                    logging.error(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    break
                    
                elif response.status_code == 500:
                    error_msg = f"{modelo['name']}: Erro interno (500)"
                    errors.append(error_msg)
                    logging.error(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    break  # Tentar próxima URL ou próximo modelo
                    
                elif response.status_code == 404:
                    error_msg = f"{modelo['name']}: Não encontrado (404)"
                    errors.append(error_msg)
                    logging.error(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    # NÃO fazer break - tentar próxima URL do mesmo modelo
                    continue  # Tentar próxima URL
                    
                else:
                    error_msg = f"{modelo['name']}: HTTP {response.status_code}"
                    errors.append(error_msg)
                    logging.error(f"{error_msg}")
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    
            except requests.exceptions.Timeout:
                error_msg = f"{modelo['name']}: Timeout"
                errors.append(error_msg)
                logging.warning(error_msg)
                break  # Não fazer retry, ir para próximo modelo
                    
            except Exception as e:
                error_msg = f"{modelo['name']}: {str(e)[:100]}"
                errors.append(error_msg)
                logging.error(f"Erro inesperado: {e}")
                break
            
            # Se chegou aqui e teve sucesso, sai do loop de URLs
            break
        
        # Pausa mínima antes de tentar próximo modelo
        if tentativa < max_tentativas - 1:
            time.sleep(0.5)  # REDUZIDO de 2s para 0.5s
    
    # Se todos os modelos falharam
    error_summary = " | ".join(errors[-4:])  # Últimos 4 erros
    logging.error(f"❌ Falhou: {error_summary}")
    
    # Mensagem mais clara para o usuário
    if "rate limit" in error_summary.lower() or "429" in error_summary:
        return None, "Limite de requisições excedido. Aguarde 1 minuto e tente novamente."
    elif "quota" in error_summary.lower():
        return None, "Cota da API excedida. Tente novamente mais tarde."
    elif "token" in error_summary.lower() or "500" in error_summary:
        return None, "Documento muito grande. Tente com um documento menor."
    elif "404" in error_summary:
        return None, "Erro de configuração. Entre em contato com o suporte."
    else:
        return None, "Erro ao processar. Tente novamente em alguns instantes."

def gerar_pdf_simplificado(texto, metadados=None, filename="documento_simplificado.pdf"):
    """Gera PDF com melhor formatação e metadados"""
    output_path = os.path.join(TEMP_DIR, filename)
    
    try:
        c = canvas.Canvas(output_path, pagesize=letter)
        largura, altura = letter
        
        # Margens
        margem_esq = 50
        margem_dir = 50
        margem_top = 50
        margem_bottom = 50
        largura_texto = largura - margem_esq - margem_dir
        
        # Configurações de fonte
        c.setFont("Helvetica", 11)
        altura_linha = 14
        
        y = altura - margem_top
        
        # Cabeçalho
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_esq, y, "Documento em Linguagem Simples")
        y -= 30
        
        # Informações do processamento
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(margem_esq, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
        y -= 15
        
        if metadados:
            if metadados.get("modelo"):
                c.drawString(margem_esq, y, f"Processado com: {metadados['modelo']}")
                y -= 15
            if metadados.get("tipo"):
                c.drawString(margem_esq, y, f"Tipo de arquivo original: {metadados['tipo'].upper()}")
                y -= 15
            if metadados.get("paginas"):
                c.drawString(margem_esq, y, f"Páginas do original: {metadados['paginas']}")
                y -= 15
            elif metadados.get("dimensoes"):
                c.drawString(margem_esq, y, f"Dimensões da imagem: {metadados['dimensoes']}")
                y -= 15
            if metadados.get("qualidade_ocr"):
                c.drawString(margem_esq, y, f"Qualidade do OCR: {metadados['qualidade_ocr']}")
                y -= 15
        
        # Linha separadora
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(margem_esq, y, largura - margem_dir, y)
        y -= 20

        # NOVO: Adicionar informações de contato e links se disponíveis
        if metadados and metadados.get('dados'):
            dados = metadados['dados']

            # Links de audiência online
            if dados.get('links_audiencia') and len(dados['links_audiencia']) > 0:
                c.setFont("Helvetica-Bold", 11)
                c.setFillColorRGB(0.2, 0.6, 0.2)
                c.drawString(margem_esq, y, "Links de Audiência Online:")
                y -= 15
                c.setFont("Helvetica", 9)
                c.setFillColorRGB(0, 0, 1)
                for link in dados['links_audiencia']:
                    if y < margem_bottom + altura_linha * 2:
                        c.showPage()
                        y = altura - margem_top
                    c.drawString(margem_esq + 10, y, f"• {link}")
                    y -= 13
                y -= 5
                c.setFillColorRGB(0, 0, 0)

            # Telefones
            if dados.get('telefones') and len(dados['telefones']) > 0:
                c.setFont("Helvetica-Bold", 11)
                c.drawString(margem_esq, y, "Telefones de Contato:")
                y -= 15
                c.setFont("Helvetica", 10)
                for tel in dados['telefones']:
                    if y < margem_bottom + altura_linha * 2:
                        c.showPage()
                        y = altura - margem_top
                    c.drawString(margem_esq + 10, y, f"• {tel}")
                    y -= 13
                y -= 5

            # Emails
            if dados.get('emails') and len(dados['emails']) > 0:
                c.setFont("Helvetica-Bold", 11)
                c.drawString(margem_esq, y, "Emails:")
                y -= 15
                c.setFont("Helvetica", 10)
                c.setFillColorRGB(0, 0, 1)
                for email in dados['emails']:
                    if y < margem_bottom + altura_linha * 2:
                        c.showPage()
                        y = altura - margem_top
                    c.drawString(margem_esq + 10, y, f"• {email}")
                    y -= 13
                y -= 5
                c.setFillColorRGB(0, 0, 0)

            # QR Codes
            if dados.get('qr_codes') and len(dados['qr_codes']) > 0:
                c.setFont("Helvetica-Bold", 11)
                c.setFillColorRGB(1, 0.6, 0)
                c.drawString(margem_esq, y, "QR Code:")
                y -= 15
                c.setFont("Helvetica", 10)
                c.setFillColorRGB(0, 0, 0)
                for qr in dados['qr_codes']:
                    if y < margem_bottom + altura_linha * 2:
                        c.showPage()
                        y = altura - margem_top
                    c.drawString(margem_esq + 10, y, f"• {qr}")
                    y -= 13
                y -= 10

            # Separador se houver informações
            if any([dados.get('links_audiencia'), dados.get('telefones'), dados.get('emails'), dados.get('qr_codes')]):
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.line(margem_esq, y, largura - margem_dir, y)
                y -= 20

        # Processar texto com formatação especial para ícones
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0, 0, 0)
        
        linhas = texto.split('\n')
        
        for linha in linhas:
            if not linha.strip():
                y -= altura_linha
                continue
            
            # Detectar e formatar linhas com ícones especiais
            if any(icon in linha for icon in ['✅', '❌', '⚠️', '📊', '📑', '⚖️', '💰', '📅', '💡']):
                c.setFont("Helvetica-Bold", 12)
                # Remover asteriscos do texto para PDF
                linha_limpa = linha.replace('**', '')
                if y < margem_bottom + altura_linha * 2:
                    c.showPage()
                    y = altura - margem_top
                c.drawString(margem_esq, y, linha_limpa)
                c.setFont("Helvetica", 11)
                y -= altura_linha * 1.5
                continue
            
            # Detectar títulos de seção
            if linha.strip().startswith('**') and linha.strip().endswith('**'):
                titulo = linha.strip()[2:-2]
                c.setFont("Helvetica-Bold", 12)
                if y < margem_bottom + altura_linha * 2:
                    c.showPage()
                    y = altura - margem_top
                c.drawString(margem_esq, y, titulo)
                c.setFont("Helvetica", 11)
                y -= altura_linha * 1.5
                continue
            
            # Processar linha normal com quebra
            palavras = linha.split()
            linhas_formatadas = []
            linha_atual = []
            
            for palavra in palavras:
                linha_teste = ' '.join(linha_atual + [palavra])
                if c.stringWidth(linha_teste, "Helvetica", 11) <= largura_texto:
                    linha_atual.append(palavra)
                else:
                    if linha_atual:
                        linhas_formatadas.append(' '.join(linha_atual))
                        linha_atual = [palavra]
                    else:
                        linhas_formatadas.append(palavra)
            
            if linha_atual:
                linhas_formatadas.append(' '.join(linha_atual))
            
            for linha_formatada in linhas_formatadas:
                if y < margem_bottom + altura_linha:
                    c.showPage()
                    y = altura - margem_top
                    c.setFont("Helvetica", 11)
                
                c.drawString(margem_esq, y, linha_formatada)
                y -= altura_linha
        
        # Rodapé
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(margem_esq, 30, "Desenvolvido pela INOVASSOL")
        c.drawString(largura - margem_dir - 150, 30, "Consulte seu advogado para orientações")

        c.save()

        # Registrar arquivo para limpeza automática LGPD (10 minutos)
        registrar_arquivo_temporario(output_path, session_id=session.get('session_id'))

        return output_path

    except Exception as e:
        logging.error(f"Erro ao gerar PDF: {e}")
        raise

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/processar", methods=["POST"])
@rate_limit
def processar():
    """Processa upload de PDF ou imagem com análise aprimorada"""
    try:
        # Tornar sessão permanente para garantir persistência ANTES de qualquer coisa
        session.permanent = True
        session.modified = True
        logging.info("📄 Sessão configurada como permanente")

        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400

        file = request.files['file']
        perspectiva = request.form.get('perspectiva', 'nao_informado')  # autor/reu/nao_informado
        logging.info(f"📄 Processando arquivo: {file.filename}, Perspectiva: {perspectiva}")

        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado"}), 400

        if not allowed_file(file.filename):
            return jsonify({"erro": "Formato inválido. Aceitos: PDF, PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP"}), 400

        # Verifica tamanho
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > MAX_FILE_SIZE:
            return jsonify({"erro": f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE//1024//1024}MB"}), 400

        # Lê o arquivo
        file_bytes = file.read()
        file_extension = file.filename.rsplit('.', 1)[1].lower()

        # Hash do arquivo para cache
        file_hash = hashlib.md5(file_bytes).hexdigest()
        logging.info(f"Processando arquivo: {secure_filename(file.filename)} ({size/1024:.1f}KB) - Hash: {file_hash}")

        # Determina se é PDF ou imagem
        if file_extension == 'pdf':
            # Processa PDF
            texto_original, metadados = extrair_texto_pdf(file_bytes)
        elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
            # Processa imagem
            try:
                texto_original, metadados = processar_imagem_para_texto(file_bytes, file_extension.upper())
            except ValueError as e:
                if "OCR não está disponível" in str(e):
                    return jsonify({
                        "erro": "OCR não está disponível neste servidor. O Tesseract não foi encontrado.",
                        "detalhes": "Entre em contato com o administrador para instalar o Tesseract OCR."
                    }), 500
                else:
                    raise

            # Adiciona aviso sobre qualidade do OCR se necessário
            if metadados.get("qualidade_ocr") == "baixa":
                texto_original = "[AVISO: A qualidade do OCR foi baixa. Alguns trechos podem estar incorretos.]\n\n" + texto_original
        else:
            return jsonify({"erro": "Tipo de arquivo não suportado"}), 400

        if len(texto_original) < 10:
            return jsonify({"erro": "Arquivo não contém texto suficiente para processar"}), 400

        # NOVA: Identificar tipo de documento
        tipo_doc, info_doc = identificar_tipo_documento(texto_original)
        logging.info(f"Tipo de documento identificado: {tipo_doc} - Urgência: {info_doc['urgencia']}")

        # NOVA: Extrair dados estruturados
        dados_estruturados = extrair_dados_estruturados(texto_original)
        logging.info(f"Dados extraídos - Processo: {dados_estruturados['numero_processo']}, Decisão: {dados_estruturados['decisao']}")

        # NOVO: Detectar perspectiva automaticamente se usuário marcou "não sei"
        if perspectiva == "nao_informado":
            logging.info("Detectando perspectiva automaticamente com IA...")
            perspectiva = detectar_perspectiva_automatica(texto_original, dados_estruturados)
            logging.info(f"Perspectiva detectada: {perspectiva}")

        # NOVA: Analisar recursos cabíveis
        recursos_info = analisar_recursos_cabiveis(tipo_doc, texto_original)

        # Adaptar prompt com informações do tipo de documento
        prompt_adaptado = PROMPT_SIMPLIFICACAO_MELHORADO
        prompt_adaptado += f"\n\nTIPO IDENTIFICADO: {tipo_doc}"
        prompt_adaptado += f"\nPERSPECTIVA DO USUÁRIO: {perspectiva}"
        prompt_adaptado += f"\n\nTEXTO ORIGINAL:\n{texto_original}"

        # Simplificar com Gemini usando prompt melhorado
        texto_simplificado, erro = simplificar_com_gemini(prompt_adaptado)

        if erro:
            return jsonify({"erro": erro}), 500

        # Criar cópia dos dados para adaptação de perspectiva
        import copy
        dados_adaptados = copy.deepcopy(dados_estruturados)

        # Adaptar texto E dados baseado na perspectiva do usuário
        if perspectiva == "autor":
            texto_simplificado = adaptar_perspectiva_autor(texto_simplificado, dados_adaptados)
        elif perspectiva == "reu":
            texto_simplificado = adaptar_perspectiva_reu(texto_simplificado, dados_adaptados)

        # NOVO: Adicionar explicação do termo "paciente" se for Habeas Corpus
        if dados_adaptados.get("termo_paciente"):
            explicacao_paciente = "\n\n📚 **Explicação:** No Habeas Corpus, \"paciente\" é o termo jurídico usado para identificar a pessoa que está presa ou ameaçada de prisão e em favor de quem o habeas corpus foi impetrado. É similar ao termo \"autor\" em outras ações."
            texto_simplificado += explicacao_paciente

        # NOVA: Preparar contexto para chat (DEPOIS da adaptação de perspectiva, COM DADOS ADAPTADOS)
        contexto_chat = gerar_chat_contextual(texto_original, dados_adaptados)
        contexto_chat["perspectiva"] = perspectiva  # Salvar perspectiva no contexto

        # Preparar metadados para o PDF (COM DADOS ADAPTADOS)
        metadados_geracao = {
            "modelo": results_cache.get(hashlib.md5(texto_original.encode()).hexdigest(), {}).get("modelo", "Gemini"),
            "tipo": metadados.get("tipo", file_extension),
            "tipo_documento": tipo_doc,
            "urgencia": info_doc["urgencia"],
            "dados": dados_adaptados,  # USAR DADOS ADAPTADOS
            "recursos": recursos_info
        }

        # Adiciona informações específicas do tipo de arquivo
        if file_extension == 'pdf':
            metadados_geracao["paginas"] = metadados.get("total_paginas")
            metadados_geracao["usou_ocr"] = metadados.get("usou_ocr")
        else:
            metadados_geracao["dimensoes"] = metadados.get("dimensoes")
            metadados_geracao["qualidade_ocr"] = metadados.get("qualidade_ocr")

        # Gerar PDF simplificado
        pdf_filename = f"simplificado_{file_hash[:8]}.pdf"
        pdf_path = gerar_pdf_simplificado(texto_simplificado, metadados_geracao, pdf_filename)

        # Salvar texto_original em arquivo temporário (não na sessão - reduz cookie)
        texto_original_path = os.path.join(TEMP_DIR, f"texto_{file_hash[:8]}.txt")
        with open(texto_original_path, 'w', encoding='utf-8') as f:
            f.write(texto_original)
        # Registrar para limpeza automática LGPD
        registrar_arquivo_temporario(texto_original_path, session_id=session.get('session_id'))

        # Salvar o caminho na sessão (apenas referências, não dados grandes)
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        session['texto_original_path'] = texto_original_path  # Apenas o caminho, não o texto completo
        session['contexto_chat'] = contexto_chat  # Contexto SEM documento_original
        session.modified = True  # Forçar salvamento da sessão

        logging.info(f"📄 PDF gerado: {pdf_filename}")
        logging.info(f"📄 PDF salvo na sessão: {pdf_path}")
        logging.info(f"📄 Texto original salvo em: {texto_original_path}")
        logging.info(f"📄 Contexto chat salvo (sem documento): {len(str(contexto_chat))} chars")

        # Análise adicional do resultado
        analise = analisar_resultado_judicial(texto_simplificado)

        return jsonify({
            "texto": texto_simplificado,
            "tipo_documento": tipo_doc,
            "urgencia": info_doc["urgencia"],
            "acao_necessaria": info_doc["acao_necessaria"],
            "dados_extraidos": dados_adaptados,  # RETORNAR DADOS ADAPTADOS, NÃO OS ORIGINAIS
            "recursos_cabiveis": recursos_info,
            "perguntas_sugeridas": contexto_chat["perguntas_sugeridas"],
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto_original)) * 100, 1),
            "metadados": metadados,
            "analise": analise,
            "modelo_usado": metadados_geracao.get("modelo", "Gemini"),
            "tipo_arquivo": file_extension
        })

    except Exception as e:
        logging.error(f"❌ Erro ao processar arquivo: {e}", exc_info=True)
        return jsonify({"erro": "Erro ao processar o arquivo. Verifique se não está corrompido"}), 500

@app.route("/processar_texto", methods=["POST"])
@rate_limit
def processar_texto():
    """Processa texto manual com análise aprimorada"""
    try:
        data = request.get_json()
        texto = data.get("texto", "").strip()
        
        if not texto:
            return jsonify({"erro": "Nenhum texto fornecido"}), 400
            
        if len(texto) < 20:
            return jsonify({"erro": "Texto muito curto. Mínimo: 20 caracteres"}), 400
            
        if len(texto) > 30000:  # REDUZIDO de 50k para 30k
            return jsonify({"erro": "Texto muito longo. Máximo: 30.000 caracteres. Divida em partes menores."}), 400
        
        texto_simplificado, erro = simplificar_com_gemini(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Análise adicional
        analise = analisar_resultado_judicial(texto_simplificado)
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto)) * 100, 1) if len(texto) > 0 else 0,
            "analise": analise
        })
        
    except Exception as e:
        logging.error(f"Erro ao processar texto: {e}")
        return jsonify({"erro": "Erro ao processar o texto"}), 500

def analisar_resultado_judicial(texto):
    """Analisa o texto simplificado para extrair informações estruturadas"""
    analise = {
        "tipo_resultado": "indefinido",
        "tem_valores": False,
        "tem_prazos": False,
        "tem_recursos": False,
        "sentimento": "neutro",
        "palavras_chave": []
    }
    
    texto_lower = texto.lower()
    
    # Identificar tipo de resultado
    if "✅" in texto or "vitória" in texto_lower or "procedente" in texto_lower:
        analise["tipo_resultado"] = "vitoria"
        analise["sentimento"] = "positivo"
    elif "❌" in texto or "derrota" in texto_lower or "improcedente" in texto_lower:
        analise["tipo_resultado"] = "derrota"
        analise["sentimento"] = "negativo"
    elif "⚠️" in texto or "parcial" in texto_lower:
        analise["tipo_resultado"] = "parcial"
        analise["sentimento"] = "neutro"
    
    # Verificar presença de elementos importantes
    if "r$" in texto_lower or "valor" in texto_lower or "💰" in texto:
        analise["tem_valores"] = True
        analise["palavras_chave"].append("valores")
    
    if "prazo" in texto_lower or "dias" in texto_lower or "📅" in texto:
        analise["tem_prazos"] = True
        analise["palavras_chave"].append("prazos")
    
    if "recurso" in texto_lower or "apelação" in texto_lower or "agravo" in texto_lower:
        analise["tem_recursos"] = True
        analise["palavras_chave"].append("recursos")
    
    return analise

@app.route("/chat", methods=["POST"])
@rate_limit
def chat_contextual():
    """Chat INTELIGENTE baseado APENAS no documento enviado usando IA"""
    try:
        data = request.get_json()
        pergunta = data.get("pergunta", "").strip()

        if not pergunta:
            return jsonify({
                "resposta": "💬 Por favor, faça uma pergunta sobre o seu documento.",
                "tipo": "erro"
            }), 400

        # Recuperar contexto da sessão
        contexto = session.get('contexto_chat')
        if not contexto:
            return jsonify({
                "resposta": "📄 Por favor, envie um documento primeiro para que eu possa responder sobre ele.",
                "tipo": "erro"
            }), 400

        # NOVO: Usar Gemini para responder de forma inteligente
        resposta = responder_com_gemini_inteligente(pergunta, contexto)

        return jsonify({
            "resposta": resposta["texto"],
            "tipo": resposta["tipo"],
            "referencia": resposta.get("referencia"),
            "sugestoes": resposta.get("sugestoes", [])
        })

    except Exception as e:
        logging.error(f"Erro no chat: {e}", exc_info=True)
        return jsonify({
            "resposta": "😔 Desculpe, ocorreu um erro ao processar sua pergunta. Tente novamente.",
            "tipo": "erro"
        }), 500

def responder_com_gemini_inteligente(pergunta, contexto):
    """Usa Gemini para responder de forma inteligente e segura"""

    logging.info(f"💬 CHAT: Pergunta recebida: '{pergunta}'")

    # Tentar obter documento do contexto (compatibilidade) ou ler do arquivo
    documento_original = contexto.get("documento_original", "")
    if not documento_original:
        # Ler do arquivo temporário (novo método - reduz tamanho da sessão)
        texto_original_path = session.get('texto_original_path')
        if texto_original_path and os.path.exists(texto_original_path):
            with open(texto_original_path, 'r', encoding='utf-8') as f:
                documento_original = f.read()
            logging.info(f"💬 CHAT: Documento lido do arquivo: {len(documento_original)} chars")
        else:
            logging.warning("💬 CHAT: Nenhum documento disponível")

    dados_extraidos = contexto.get("dados_extraidos", {})
    perspectiva = contexto.get("perspectiva", "autor")

    logging.info(f"💬 CHAT: Contexto - Documento: {len(documento_original)} chars, Perspectiva: {perspectiva}")
    logging.info(f"💬 CHAT: Dados extraídos: Valores={list(dados_extraidos.get('valores', {}).keys())}, Prazos={len(dados_extraidos.get('prazos', []))}")

    # Truncar documento se muito grande
    doc_truncado = documento_original[:4000] if len(documento_original) > 4000 else documento_original

    prompt = f"""Você é o JUS Bot, assistente que explica documentos jurídicos em LINGUAGEM SIMPLES.

REGRAS CRÍTICAS:
1. Seja EXTREMAMENTE CONCISO - máximo 2-3 frases curtas
2. Use linguagem SIMPLES, como se explicasse para uma criança
3. NÃO cite o documento literalmente - PARAFRASEIE
4. Se perguntar "o que é X?", explique em 1 frase simples
5. Se NÃO tiver a informação, diga apenas: "Não encontrei essa informação no documento"
6. Se perguntar "devo fazer X?", diga: "Procure um advogado para orientação"
7. NÃO use termos jurídicos complexos - SIMPLIFIQUE

EXEMPLOS DE RESPOSTAS BOAS:
❌ RUIM: "A decisão tomada foi PARCIALMENTE PROCEDENTE. (Fonte: 'Sobre o mérito, o pedido é procedente em parte.' - FUNDAMENTAÇÃO do DOCUMENTO)"
✅ BOM: "O juiz aceitou parte do que você pediu e negou outra parte."

❌ RUIM: "Os próximos passos são: 1. Participar da teleaudiência... 2. Comparecer acompanhado..."
✅ BOM: "Você precisa entrar na audiência online no dia 26/05/2025 às 9h. Leve um advogado."

DADOS DO DOCUMENTO:
- Partes: {dados_extraidos.get('partes', {}).get('autor', 'não encontrado')} vs {dados_extraidos.get('partes', {}).get('reu', 'não encontrado')}
- Valores: {dados_extraidos.get('valores', {}).get('total', 'não informado')}
- Prazos: {', '.join(dados_extraidos.get('prazos', [])[:2]) if dados_extraidos.get('prazos') else 'nenhum'}
- Decisão: {(dados_extraidos.get('decisao') or 'não informada')[:100]}

PERGUNTA: {pergunta}

Responda em NO MÁXIMO 2-3 FRASES CURTAS E SIMPLES:"""

    try:
        logging.info("💬 🤖 Chamando Gemini para responder chat...")
        model = genai.GenerativeModel(GEMINI_MODELS[1]["name"])  # Flash para rapidez
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip()
        logging.info(f"💬 🤖 Gemini respondeu: '{resposta_texto[:100]}...'")

        # Detectar tipo de resposta
        tipo = "resposta"
        if "não encontrei" in resposta_texto.lower() or "não localizei" in resposta_texto.lower():
            tipo = "nao_encontrado"
            logging.info("💬 Tipo: nao_encontrado")
        elif "não posso dar conselhos" in resposta_texto.lower():
            tipo = "redirecionamento_profissional"
            logging.info("💬 Tipo: redirecionamento_profissional")
        else:
            logging.info("💬 Tipo: resposta")

        return {
            "texto": resposta_texto,
            "tipo": tipo,
            "referencia": "documento_original"
        }

    except Exception as e:
        logging.error(f"💬 ❌ ERRO ao gerar resposta com Gemini: {e}", exc_info=True)
        # Retornar mensagem de erro simples
        return {
            "texto": "Não consegui processar sua pergunta. Tente reformular de forma mais simples.",
            "tipo": "erro",
            "referencia": None
        }

@app.route("/diagnostico")
def diagnostico():
    """Endpoint para diagnosticar problemas de OCR e configuração"""
    diagnostico_info = {
        "tesseract_disponivel": TESSERACT_AVAILABLE,
        "tesseract_version": TESSERACT_VERSION,
        "tesseract_langs": TESSERACT_LANGS,
        "python_libs": {},
        "sistema": {},
        "configuracao": {}
    }
    
    # Verificar bibliotecas Python
    try:
        import pytesseract
        diagnostico_info["python_libs"]["pytesseract"] = pytesseract.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["pytesseract"] = f"Erro: {str(e)}"
    
    try:
        import cv2
        diagnostico_info["python_libs"]["opencv"] = cv2.__version__
        diagnostico_info["configuracao"]["opencv_disponivel"] = CV2_AVAILABLE
    except Exception as e:
        diagnostico_info["python_libs"]["opencv"] = f"Erro: {str(e)}"
        diagnostico_info["configuracao"]["opencv_disponivel"] = False
    
    try:
        from PIL import Image
        diagnostico_info["python_libs"]["pillow"] = Image.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["pillow"] = f"Erro: {str(e)}"
    
    try:
        import numpy
        diagnostico_info["python_libs"]["numpy"] = numpy.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["numpy"] = f"Erro: {str(e)}"
    
    # Info do sistema
    import platform
    diagnostico_info["sistema"]["os"] = platform.system()
    diagnostico_info["sistema"]["arquitetura"] = platform.machine()
    diagnostico_info["sistema"]["python_version"] = platform.python_version()
    
    # Configurações
    diagnostico_info["configuracao"]["gemini_api_configurada"] = bool(GEMINI_API_KEY)
    diagnostico_info["configuracao"]["temp_dir"] = TEMP_DIR
    diagnostico_info["configuracao"]["max_file_size_mb"] = MAX_FILE_SIZE // 1024 // 1024
    
    # Variáveis de ambiente relevantes
    diagnostico_info["configuracao"]["tessdata_prefix"] = os.getenv("TESSDATA_PREFIX", "Não configurado")
    
    return jsonify(diagnostico_info)

@app.route("/diagnostico_api")
def diagnostico_api():
    """Testa conectividade com a API Gemini"""
    if not GEMINI_API_KEY:
        return jsonify({"erro": "API Key não configurada"}), 500
    
    resultados = []
    
    for modelo in GEMINI_MODELS:
        # Cada modelo pode ter múltiplas URLs
        urls = modelo.get("urls", [modelo.get("url")]) if isinstance(modelo.get("urls"), list) else [modelo.get("url")]
        
        for url_base in urls:
            if not url_base:
                continue
                
            try:
                url_with_key = f"{url_base}?key={GEMINI_API_KEY}"
                
                payload = {
                    "contents": [{
                        "parts": [{"text": "Teste"}]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": 10
                    }
                }
                
                response = requests.post(
                    url_with_key,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=15
                )
                
                url_version = url_base.split('/')[4]  # 'v1' ou 'v1beta'
                
                resultados.append({
                    "modelo": modelo["name"],
                    "url_version": url_version,
                    "status": response.status_code,
                    "ok": response.status_code == 200,
                    "mensagem": "✅ OK" if response.status_code == 200 else f"❌ {response.text[:200]}"
                })
                
                # Se encontrou uma URL que funciona, não testa as outras do mesmo modelo
                if response.status_code == 200:
                    break
                
            except Exception as e:
                resultados.append({
                    "modelo": modelo["name"],
                    "url_version": url_base.split('/')[4] if url_base else "N/A",
                    "status": "erro",
                    "ok": False,
                    "mensagem": f"❌ {str(e)}"
                })
    
    # Contar quantos modelos funcionam
    working_models = sum(1 for r in resultados if r["ok"])
    
    return jsonify({
        "status": "ok" if working_models > 0 else "erro",
        "modelos_funcionando": working_models,
        "total_modelos": len(GEMINI_MODELS),
        "api_key_configurada": bool(GEMINI_API_KEY),
        "api_key_preview": GEMINI_API_KEY[:15] + "..." if GEMINI_API_KEY else None,
        "modelos_testados": resultados,
        "estatisticas": model_usage_stats,
        "cache_entries": len(results_cache),
        "recomendacao": "✅ Sistema operacional" if working_models > 0 else "❌ Nenhum modelo disponível - verifique a API key"
    })

@app.route("/estatisticas")
def estatisticas():
    """Retorna estatísticas de uso dos modelos"""
    return jsonify({
        "modelos": model_usage_stats,
        "cache_size": len(results_cache),
        "tesseract_disponivel": TESSERACT_AVAILABLE,
        "opencv_disponivel": CV2_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/download_pdf")
def download_pdf():
    """Download do PDF com verificação de sessão"""
    logging.info("📥 Tentando baixar PDF...")

    pdf_path = session.get('pdf_path')
    pdf_filename = session.get('pdf_filename', 'documento_simplificado.pdf')

    logging.info(f"📥 PDF path na sessão: {pdf_path}")
    logging.info(f"📥 PDF filename na sessão: {pdf_filename}")

    if not pdf_path:
        logging.error("📥 ❌ PDF path não encontrado na sessão")
        return jsonify({"erro": "PDF não encontrado. Por favor, processe um documento primeiro"}), 404

    if not os.path.exists(pdf_path):
        logging.error(f"📥 ❌ PDF não existe no disco: {pdf_path}")
        return jsonify({"erro": "PDF não encontrado. Por favor, processe um documento primeiro"}), 404

    logging.info(f"📥 ✅ PDF encontrado, enviando: {pdf_path}")
    
    try:
        return send_file(
            pdf_path, 
            as_attachment=True, 
            download_name=pdf_filename,
            mimetype='application/pdf'
        )
    except Exception as e:
        logging.error(f"Erro ao fazer download: {e}")
        return jsonify({"erro": "Erro ao baixar o arquivo"}), 500

@app.route("/feedback", methods=["POST"])
def feedback():
    """Recebe feedback do usuário sobre a simplificação"""
    try:
        data = request.get_json()
        rating = data.get("rating")
        comment = data.get("comment", "")
        resultado_hash = data.get("hash", "")
        
        # Aqui você pode salvar em um banco de dados ou arquivo
        logging.info(f"Feedback recebido - Rating: {rating}, Hash: {resultado_hash[:8]}, Comentário: {comment}")
        
        return jsonify({"sucesso": True, "mensagem": "Obrigado pelo seu feedback!"})
    except Exception as e:
        logging.error(f"Erro ao processar feedback: {e}")
        return jsonify({"erro": "Erro ao processar feedback"}), 500

@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve arquivos estáticos"""
    return send_from_directory('static', filename)

@app.route("/health")
def health():
    """Endpoint de health check para o Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(GEMINI_API_KEY),
        "models_available": len(GEMINI_MODELS),
        "cache_entries": len(results_cache),
        "tesseract_available": TESSERACT_AVAILABLE,
        "tesseract_version": TESSERACT_VERSION,
        "tesseract_langs": TESSERACT_LANGS,
        "opencv_available": CV2_AVAILABLE,
        "supported_formats": list(ALLOWED_EXTENSIONS)
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({"erro": "Endpoint não encontrado"}), 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Erro interno: {e}")
    return jsonify({"erro": "Erro interno do servidor"}), 500

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Limpa arquivos temporários antigos periodicamente
def cleanup_temp_files():
    while True:
        try:
            time.sleep(3600)  # A cada hora
            now = time.time()
            
            # Limpar arquivos temporários
            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('simplificado_'):
                    filepath = os.path.join(TEMP_DIR, filename)
                    try:
                        if os.stat(filepath).st_mtime < now - 3600:  # Arquivos com mais de 1 hora
                            os.remove(filepath)
                            logging.info(f"Arquivo temporário removido: {filename}")
                    except Exception as e:
                        logging.warning(f"Erro ao remover {filename}: {e}")
            
            # Limpar cache antigo
            to_remove = []
            for key, value in results_cache.items():
                if time.time() - value["timestamp"] > CACHE_EXPIRATION:
                    to_remove.append(key)
            
            for key in to_remove:
                del results_cache[key]
            
            if to_remove:
                logging.info(f"Removidos {len(to_remove)} itens do cache")
                
        except Exception as e:
            logging.error(f"Erro na limpeza de arquivos: {e}")

# Inicia thread de limpeza
cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)




