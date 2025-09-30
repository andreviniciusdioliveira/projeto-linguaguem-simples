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
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

# ========================================
# SOLUÇÃO 1: PROMPT MELHORADO COM ÊNFASE EM VALORES
# ========================================

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
**⚠️ ATENÇÃO CRÍTICA: Esta é a seção MAIS IMPORTANTE para o usuário!**

**INSTRUÇÕES PARA EXTRAÇÃO DE VALORES:**
1. Procure atentamente por TODOS os valores monetários no DISPOSITIVO da sentença
2. Procure especialmente por frases como "CONDENO ao pagamento de R$", "indenização de R$", "danos morais no valor de R$"
3. Se houver valores já identificados (veja abaixo), USE-OS na resposta
4. NUNCA escreva "A ser definido" se houver um valor específico no texto
5. Se realmente não houver valor, explique o motivo (ex: "Será calculado em liquidação de sentença")

- Valor da causa: R$ [extrair do início do documento ou especificar "não informado"]

- **VALORES QUE VOCÊ VAI RECEBER** (se for o autor vencedor):
  - **Danos morais**: R$ [VALOR ESPECÍFICO ou "não concedido"] 
  - **Danos materiais**: R$ [VALOR ESPECÍFICO ou "não concedido"]
  - **Lucros cessantes**: R$ [VALOR ESPECÍFICO ou "pedido negado"]
  - **TOTAL APROXIMADO A RECEBER**: R$ [somar todos os valores concedidos]

- **Valores a pagar** (se você perdeu ou perdeu parcialmente):
  - **Custas processuais**: R$ [valor] ou [% sobre valor da causa]
  - **Honorários advocatícios da parte contrária**: [percentual, ex: 10%] sobre R$ [base de cálculo] = R$ [valor aproximado]

- **Correção monetária**: Desde [data especificada na sentença], pelo índice [IPCA-E/SELIC/IGP-M]
- **Juros de mora**: [taxa especificada]% desde [data do evento danoso ou da citação]

- **Forma de pagamento**: [Precatório/RPV/Pagamento direto]

📚 MINI DICIONÁRIO DOS TERMOS JURÍDICOS
[Listar apenas os termos jurídicos que aparecem no texto com explicação simples]
- **Termo 1:** Explicação clara e simples
- **Termo 2:** Explicação clara e simples
- **Termo 3:** Explicação clara e simples

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
8. **VALORES SÃO PRIORIDADE MÁXIMA** - Nunca omita valores que estejam explícitos no texto

**TEXTO ORIGINAL A SIMPLIFICAR:**
"""

# ========================================
# SOLUÇÃO 3: EXTRAÇÃO PRÉ-PROCESSADA DE VALORES
# ========================================

def extrair_valores_sentenca(texto):
    """
    Extrai valores monetários importantes da sentença ANTES de enviar para IA.
    Isso garante que valores não sejam perdidos no processamento.
    """
    valores = {
        "danos_morais": None,
        "danos_materiais": None,
        "lucros_cessantes": None,
        "honorarios": None,
        "valor_causa": None,
        "custas": None
    }
    
    logging.info("🔍 Iniciando extração de valores...")
    
    # 1. DISPOSITIVO - procurar especificamente nesta seção
    dispositivo_match = re.search(
        r'(III\s*-?\s*DISPOSITIVO|DISPOSITIVO|DECIDE-?SE|ANTE O EXPOSTO|DIANTE DO EXPOSTO|ISTO POSTO).*?(?=Publique-se|Cumpra-se|Intimem-se|P\.R\.I\.|Palmas|Documento eletrônico|$)', 
        texto, re.IGNORECASE | re.DOTALL
    )
    
    texto_busca = texto  # Buscar no texto todo por padrão
    if dispositivo_match:
        texto_busca = dispositivo_match.group(0)
        logging.info(f"✅ DISPOSITIVO encontrado ({len(texto_busca)} caracteres)")
    
    # 2. VALOR DA CAUSA (geralmente no início)
    valor_causa_patterns = [
        r'valor\s+da\s+causa[:\s]+R\$\s*([\d\.]+,\d{2})',
        r'dá-se\s+à\s+causa\s+o\s+valor\s+de\s+R\$\s*([\d\.]+,\d{2})',
    ]
    for pattern in valor_causa_patterns:
        match = re.search(pattern, texto[:5000], re.IGNORECASE)  # Buscar nos primeiros 5000 caracteres
        if match:
            valores["valor_causa"] = match.group(1)
            logging.info(f"💰 Valor da causa: R$ {valores['valor_causa']}")
            break
    
    # 3. DANOS MORAIS (múltiplos padrões)
    danos_morais_patterns = [
        r'(?:CONDENO|condeno).*?(?:danos?\s+morais?).*?(?:de\s+|no\s+valor\s+de\s+|no\s+importe\s+de\s+)?R\$\s*([\d\.]+,\d{2})',
        r'(?:danos?\s+morais?).*?(?:de\s+|no\s+valor\s+de\s+|no\s+importe\s+de\s+)?R\$\s*([\d\.]+,\d{2})',
        r'indenização.*?(?:moral|morais).*?R\$\s*([\d\.]+,\d{2})',
        r'R\$\s*([\d\.]+,\d{2}).*?(?:danos?\s+morais?|indenização)',
        r'(?:trinta mil reais?|30\.000,00|R\$\s*30\.000,00).*?(?:danos?\s+morais?)',
    ]
    
    for pattern in danos_morais_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE | re.DOTALL)
        if match:
            valores["danos_morais"] = match.group(1)
            logging.info(f"💰 Danos morais encontrado: R$ {valores['danos_morais']}")
            break
    
    # 4. Se não encontrou com regex, procurar por valores grandes no dispositivo
    if not valores["danos_morais"] and dispositivo_match:
        valores_encontrados = re.findall(r'R\$\s*([\d\.]+,\d{2})', texto_busca)
        if valores_encontrados:
            logging.info(f"🔍 Valores brutos encontrados no dispositivo: {valores_encontrados}")
            # Pegar o primeiro valor >= R$ 5.000,00 (provavelmente é indenização)
            for valor_str in valores_encontrados:
                valor_num = float(valor_str.replace('.', '').replace(',', '.'))
                if valor_num >= 5000.00 and not valores["danos_morais"]:
                    valores["danos_morais"] = valor_str
                    logging.info(f"💰 Danos morais inferido (valor alto): R$ {valores['danos_morais']}")
                    break
    
    # 5. DANOS MATERIAIS
    danos_materiais_patterns = [
        r'(?:danos?\s+materiais?).*?R\$\s*([\d\.]+,\d{2})',
        r'(?:CONDENO|condeno).*?(?:danos?\s+materiais?).*?R\$\s*([\d\.]+,\d{2})',
    ]
    for pattern in danos_materiais_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE | re.DOTALL)
        if match:
            valores["danos_materiais"] = match.group(1)
            logging.info(f"💰 Danos materiais: R$ {valores['danos_materiais']}")
            break
    
    # 6. LUCROS CESSANTES
    lucros_patterns = [
        r'(?:lucros?\s+cessantes?).*?R\$\s*([\d\.]+,\d{2})',
        r'(?:CONDENO|condeno).*?(?:lucros?\s+cessantes?).*?R\$\s*([\d\.]+,\d{2})',
    ]
    for pattern in lucros_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE | re.DOTALL)
        if match:
            valores["lucros_cessantes"] = match.group(1)
            logging.info(f"💰 Lucros cessantes: R$ {valores['lucros_cessantes']}")
            break
    
    # Verificar se lucros cessantes foi NEGADO
    if re.search(r'(?:REJEITO|nego|indefiro).*?(?:lucros?\s+cessantes?)', texto_busca, re.IGNORECASE):
        valores["lucros_cessantes"] = "PEDIDO NEGADO"
        logging.info("❌ Lucros cessantes: PEDIDO NEGADO")
    
    # 7. HONORÁRIOS
    honorarios_patterns = [
        r'honorários.*?(\d+)%',
        r'(\d+)%.*?honorários',
    ]
    for pattern in honorarios_patterns:
        match = re.search(pattern, texto_busca, re.IGNORECASE)
        if match:
            valores["honorarios"] = match.group(1) + "%"
            logging.info(f"💰 Honorários: {valores['honorarios']}")
            break
    
    # Resumo final
    valores_encontrados = sum(1 for v in valores.values() if v and v != "PEDIDO NEGADO")
    logging.info(f"✅ Extração concluída: {valores_encontrados} valores encontrados")
    
    return valores

# ========================================
# SOLUÇÃO 2: TRUNCAMENTO INTELIGENTE QUE PROTEGE DISPOSITIVO
# ========================================

def truncar_texto_inteligente(texto, max_tokens=25000):
    """
    Trunca o texto preservando as partes mais importantes.
    NUNCA trunca o DISPOSITIVO, que contém os valores da condenação.
    """
    tokens_estimados = estimar_tokens(texto)
    
    if tokens_estimados <= max_tokens:
        return texto
    
    logging.warning(f"⚠️ Texto muito grande ({tokens_estimados} tokens). Truncando para {max_tokens} tokens...")
    logging.warning(f"🛡️ DISPOSITIVO será PROTEGIDO e mantido COMPLETO")
    
    # Procurar seções importantes
    secoes_importantes = []
    
    # 1. DISPOSITIVO (PRIORIDADE ABSOLUTA - NUNCA TRUNCAR)
    dispositivo_match = re.search(
        r'(III\s*-?\s*DISPOSITIVO|DISPOSITIVO|DECIDE-?SE|ANTE O EXPOSTO|DIANTE DO EXPOSTO|ISTO POSTO).*?(?=Publique-se|Cumpra-se|Intimem-se|P\.R\.I\.|Palmas|Documento eletrônico|$)', 
        texto, re.IGNORECASE | re.DOTALL
    )
    
    if dispositivo_match:
        dispositivo_completo = dispositivo_match.group(0)
        # DISPOSITIVO NUNCA É TRUNCADO - tokens infinitos
        secoes_importantes.append(("🔒 DISPOSITIVO [COMPLETO - PROTEGIDO]", dispositivo_completo, 999999))
        logging.info(f"✅ DISPOSITIVO capturado ({len(dispositivo_completo)} caracteres) - será mantido integralmente")
    else:
        logging.warning("⚠️ DISPOSITIVO não encontrado com regex - procurando alternativas")
        # Fallback: pegar últimos 8000 caracteres (geralmente contém dispositivo)
        fim_documento = texto[-8000:]
        secoes_importantes.append(("🔒 FINAL DO DOCUMENTO [PROTEGIDO]", fim_documento, 999999))
    
    # 2. Identificação do processo (importante mas pode ser resumida)
    inicio = texto[:3000]
    secoes_importantes.append(("📋 IDENTIFICAÇÃO", inicio, 2000))
    
    # 3. Mérito (se houver espaço, pegar um resumo)
    merito_match = re.search(
        r'(II\.?\s*II\s*-?\s*DO\s*MÉRITO|DO\s*MÉRITO).*?(?=(III\s*-?\s*DISPOSITIVO|DISPOSITIVO|$))', 
        texto, re.IGNORECASE | re.DOTALL
    )
    if merito_match:
        merito_texto = merito_match.group(0)
        # Só as primeiras 40 linhas do mérito
        merito_linhas = merito_texto.split('\n')[:40]
        secoes_importantes.append(("⚖️ MÉRITO [RESUMO]", '\n'.join(merito_linhas), 6000))
    
    # 4. Fundamentação (se houver espaço restante)
    fundamentacao_match = re.search(
        r'(II\s*-?\s*FUNDAMENTAÇÃO|FUNDAMENTAÇÃO).*?(?=(II\.?\s*II|DO\s*MÉRITO|III\s*-?\s*DISPOSITIVO|DISPOSITIVO|$))', 
        texto, re.IGNORECASE | re.DOTALL
    )
    if fundamentacao_match:
        fund_texto = fundamentacao_match.group(0)
        # Só as primeiras 30 linhas
        fund_linhas = fund_texto.split('\n')[:30]
        secoes_importantes.append(("📚 FUNDAMENTAÇÃO [RESUMO]", '\n'.join(fund_linhas), 4000))
    
    # Montar texto truncado
    texto_final = "=" * 60 + "\n"
    texto_final += "⚠️ DOCUMENTO TRUNCADO PARA PROCESSAMENTO\n"
    texto_final += "🛡️ O DISPOSITIVO (decisão e valores) FOI MANTIDO COMPLETO\n"
    texto_final += "=" * 60 + "\n\n"
    
    tokens_usados = 0
    # Processar seções por ordem de prioridade
    for nome, conteudo, tokens_max in secoes_importantes:
        if tokens_usados >= max_tokens:
            logging.warning(f"⏭️ Limite atingido, pulando seção: {nome}")
            break
        
        # DISPOSITIVO nunca é truncado (tokens_max = 999999)
        if tokens_max == 999999:
            logging.info(f"🔒 Mantendo {nome} COMPLETO ({len(conteudo)} caracteres)")
            texto_final += f"\n\n{'=' * 60}\n{nome}\n{'=' * 60}\n{conteudo}\n"
            tokens_usados += len(conteudo) // 4
        else:
            # Outras seções podem ser truncadas
            caracteres_max = min(tokens_max * 4, (max_tokens - tokens_usados) * 4)
            if len(conteudo) > caracteres_max:
                conteudo_truncado = conteudo[:caracteres_max] + "\n\n[... restante omitido ...]"
                logging.info(f"✂️ {nome} truncado de {len(conteudo)} para {caracteres_max} caracteres")
                conteudo = conteudo_truncado
            
            texto_final += f"\n\n{'=' * 60}\n{nome}\n{'=' * 60}\n{conteudo}\n"
            tokens_usados += len(conteudo) // 4
    
    logging.info(f"✅ Truncamento concluído: {tokens_estimados} → ~{tokens_usados} tokens (DISPOSITIVO intacto)")
    return texto_final

# ========================================
# RESTANTE DAS FUNÇÕES (SEM ALTERAÇÕES)
# ========================================

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
        img = Image.open(io.BytesIO(image_bytes))
        metadados["dimensoes"] = f"{img.width}x{img.height}"
        logging.info(f"Processando imagem: {metadados['dimensoes']}, formato: {formato}")
        
        if img.mode not in ('RGB', 'L'):
            original_mode = img.mode
            img = img.convert('RGB')
            logging.info(f"Convertido de {original_mode} para RGB")
        
        if CV2_AVAILABLE:
            texto = processar_com_opencv(img, metadados)
        else:
            texto = processar_com_pil(img, metadados)
        
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
    
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    
    height, width = img_cv.shape[:2]
    if width > 3000 or height > 3000:
        scale = min(3000/width, 3000/height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        img_cv = cv2.resize(img_cv, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        logging.info(f"Imagem redimensionada para {new_width}x{new_height}")
    
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    contrast = clahe.apply(denoised)
    binary = cv2.adaptiveThreshold(contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                 cv2.THRESH_BINARY, 11, 2)
    
    img_processed = Image.fromarray(binary)
    
    return executar_ocr_multiplas_configs(img_processed, metadados)

def processar_com_pil(img, metadados):
    """Processamento básico com PIL"""
    logging.info("Usando processamento básico com PIL")
    
    if img.width > 3000 or img.height > 3000:
        ratio = min(3000/img.width, 3000/img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        logging.info(f"Imagem redimensionada para {new_size}")
    
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    img = img.convert('L')
    threshold = 180
    img = img.point(lambda p: 255 if p > threshold else 0)
    
    return executar_ocr_multiplas_configs(img, metadados)

def executar_ocr_multiplas_configs(img_processed, metadados):
    """Executa OCR com múltiplas configurações e escolhe o melhor resultado"""
    
    custom_configs = [
        r'--oem 3 --psm 6 -l por+eng',
        r'--oem 3 --psm 3 -l por+eng',
        r'--oem 3 --psm 4 -l por+eng',
        r'--oem 3 --psm 6 -l por',
        r'--oem 3 --psm 3 -l eng',
    ]
    
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
            
            score = avaliar_qualidade_texto(texto_temp)
            logging.info(f"Score: {score}, Caracteres: {len(texto_temp.strip())}")
            
            if score > best_score or (score == best_score and len(texto_temp.strip()) > len(best_text.strip())):
                best_text = texto_temp
                best_score = score
                logging.info(f"Novo melhor resultado encontrado")
            
        except Exception as e:
            logging.warning(f"Erro com configuração {config}: {e}")
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
    
    alpha_ratio = sum(1 for c in texto if c.isalpha()) / len(texto)
    special_ratio = sum(1 for c in texto if c in '!@#$%^&*()[]{}|\\<>?~`') / len(texto)
    space_ratio = texto.count(' ') / len(texto)
    score = alpha_ratio * 0.6 + (1 - special_ratio) * 0.3 + min(space_ratio * 4, 0.1) * 1.0
    
    return min(score, 1.0)

def limpar_texto_ocr(texto):
    """Limpa e melhora o texto extraído via OCR"""
    if not texto:
        return ""
    
    texto = ''.join(char if char.isprintable() or char in '\n\r\t' else ' ' for char in texto)
    
    linhas = texto.split('\n')
    linhas_limpas = []
    
    for linha in linhas:
        linha_strip = linha.strip()
        if linha_strip:
            alpha_count = sum(1 for c in linha_strip if c.isalpha())
            if len(linha_strip) > 0 and alpha_count / len(linha_strip) >= 0.3:
                linhas_limpas.append(linha)
    
    texto = '\n'.join(linhas_limpas)
    texto = re.sub(r' +', ' ', texto)
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
                    conteudo = page.get_text()
                    
                    if conteudo.strip():
                        metadados["tem_texto"] = True
                        texto_completo += conteudo + "\n"
                    elif TESSERACT_AVAILABLE:
                        logging.info(f"Aplicando OCR na página {i+1}")
                        metadados["usou_ocr"] = True
                        metadados["paginas_com_ocr"].append(i+1)
                        
                        pix = page.get_pixmap(dpi=150)
                        img_data = pix.tobytes()
                        
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

def analisar_complexidade_texto(texto):
    """Analisa a complexidade do texto para escolher o modelo apropriado"""
    complexidade = {
        "caracteres": len(texto),
        "palavras": len(texto.split()),
        "tokens_estimados": estimar_tokens(texto),
        "termos_tecnicos": 0,
        "citacoes": 0,
        "nivel": "baixo"
    }
    
    termos_tecnicos = [
        "exordial", "sucumbência", "litispendência", "coisa julgada",
        "tutela antecipada", "liminar", "agravo", "embargo", "mandamus",
        "quantum", "extra petita", "ultra petita", "iura novit curia"
    ]
    
    texto_lower = texto.lower()
    for termo in termos_tecnicos:
        complexidade["termos_tecnicos"] += texto_lower.count(termo)
    
    complexidade["citacoes"] = len(re.findall(r'art\.\s*\d+|artigo\s*\d+|§\s*\d+|lei\s*n[º°]\s*[\d\.]+', texto_lower))
    
    if complexidade["tokens_estimados"] > 15000 or complexidade["termos_tecnicos"] > 20 or complexidade["citacoes"] > 15:
        complexidade["nivel"] = "alto"
    elif complexidade["tokens_estimados"] > 7000 or complexidade["termos_tecnicos"] > 10 or complexidade["citacoes"] > 8:
        complexidade["nivel"] = "médio"
    
    return complexidade

def escolher_modelo_gemini(complexidade, tentativa=0):
    """Escolhe o modelo Gemini mais apropriado baseado na complexidade"""
    if tentativa == 0:
        return GEMINI_MODELS[0]
    elif tentativa == 1:
        return GEMINI_MODELS[1]
    else:
        return GEMINI_MODELS[2]

def simplificar_com_gemini(texto, max_retries=1):
    """
    Chama a API do Gemini com fallback automático entre modelos.
    AGORA COM EXTRAÇÃO PRÉVIA DE VALORES.
    """
    
    # Truncar texto se necessário ANTES de enviar
    MAX_INPUT_TOKENS = 15000
    tokens_estimados = estimar_tokens(texto)
    
    if tokens_estimados > MAX_INPUT_TOKENS:
        logging.warning(f"Texto com {tokens_estimados} tokens. Truncando...")
        texto = truncar_texto_inteligente(texto, MAX_INPUT_TOKENS)
        tokens_estimados = estimar_tokens(texto)
        logging.info(f"Texto truncado para ~{tokens_estimados} tokens")
    
    # ========================================
    # 🆕 EXTRAÇÃO PRÉVIA DE VALORES
    # ========================================
    valores_extraidos = extrair_valores_sentenca(texto)
    
    prompt_valores = ""
    if any(v for v in valores_extraidos.values() if v):
        prompt_valores = "\n\n" + "="*60 + "\n"
        prompt_valores += "🔍 VALORES JÁ IDENTIFICADOS NO DOCUMENTO:\n"
        prompt_valores += "="*60 + "\n"
        
        if valores_extraidos["valor_causa"]:
            prompt_valores += f"✓ Valor da causa: R$ {valores_extraidos['valor_causa']}\n"
        
        if valores_extraidos["danos_morais"]:
            prompt_valores += f"✓ DANOS MORAIS: R$ {valores_extraidos['danos_morais']}\n"
        
        if valores_extraidos["danos_materiais"]:
            prompt_valores += f"✓ Danos materiais: R$ {valores_extraidos['danos_materiais']}\n"
        
        if valores_extraidos["lucros_cessantes"]:
            if valores_extraidos["lucros_cessantes"] == "PEDIDO NEGADO":
                prompt_valores += f"✗ Lucros cessantes: PEDIDO FOI NEGADO\n"
            else:
                prompt_valores += f"✓ Lucros cessantes: R$ {valores_extraidos['lucros_cessantes']}\n"
        
        if valores_extraidos["honorarios"]:
            prompt_valores += f"✓ Honorários: {valores_extraidos['honorarios']}\n"
        
        prompt_valores += "\n⚠️ **IMPORTANTE:** USE ESTES VALORES NA SEÇÃO 'VALORES E OBRIGAÇÕES'\n"
        prompt_valores += "⚠️ **NÃO ESCREVA** 'A ser definido' se o valor está listado acima!\n"
        prompt_valores += "="*60 + "\n\n"
        
        logging.info("✅ Valores extraídos serão injetados no prompt")
    else:
        logging.warning("⚠️ Nenhum valor foi extraído automaticamente")
    
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
    
    # Montar prompt completo com valores extraídos
    prompt_completo = PROMPT_SIMPLIFICACAO + prompt_valores + "\n\n**TEXTO ORIGINAL:**\n" + texto
    
    headers = {
        "Content-Type": "application/json"
    }
    
    errors = []
    
    max_tentativas = min(2, len(GEMINI_MODELS))
    
    for tentativa in range(max_tentativas):
        modelo = escolher_modelo_gemini(complexidade, tentativa)
        
        urls = modelo.get("urls", [modelo.get("url")]) if isinstance(modelo.get("urls"), list) else [modelo.get("url")]
        
        for url_base in urls:
            if not url_base:
                continue
                
            logging.info(f"Tentativa {tentativa + 1}/{max_tentativas}: Modelo {modelo['name']}")
            
            model_usage_stats[modelo["name"]]["attempts"] += 1
            
            max_output_tokens = 1500
            
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
            
            try:
                start_time = time.time()
                response = requests.post(
                    url_with_key,
                    headers=headers,
                    json=payload,
                    timeout=25
                )
                
                elapsed = round(time.time() - start_time, 2)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        texto_simplificado = data["candidates"][0]["content"]["parts"][0]["text"]
                        
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
                        break
                        
                elif response.status_code == 429:
                    error_msg = f"{modelo['name']}: Rate limit (429)"
                    errors.append(error_msg)
                    logging.warning(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    time.sleep(1)
                    break
                    
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
                    break
                    
                elif response.status_code == 404:
                    error_msg = f"{modelo['name']}: Não encontrado (404)"
                    errors.append(error_msg)
                    logging.error(error_msg)
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    continue
                    
                else:
                    error_msg = f"{modelo['name']}: HTTP {response.status_code}"
                    errors.append(error_msg)
                    logging.error(f"{error_msg}")
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    
            except requests.exceptions.Timeout:
                error_msg = f"{modelo['name']}: Timeout"
                errors.append(error_msg)
                logging.warning(error_msg)
                break
                    
            except Exception as e:
                error_msg = f"{modelo['name']}: {str(e)[:100]}"
                errors.append(error_msg)
                logging.error(f"Erro inesperado: {e}")
                break
            
            break
        
        if tentativa < max_tentativas - 1:
            time.sleep(0.5)
    
    error_summary = " | ".join(errors[-4:])
    logging.error(f"❌ Falhou: {error_summary}")
    
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
        
        margem_esq = 50
        margem_dir = 50
        margem_top = 50
        margem_bottom = 50
        largura_texto = largura - margem_esq - margem_dir
        
        c.setFont("Helvetica", 11)
        altura_linha = 14
        
        y = altura - margem_top
        
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_esq, y, "Documento em Linguagem Simples")
        y -= 30
        
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
        
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(margem_esq, y, largura - margem_dir, y)
        y -= 20
        
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0, 0, 0)
        
        linhas = texto.split('\n')
        
        for linha in linhas:
            if not linha.strip():
                y -= altura_linha
                continue
            
            if any(icon in linha for icon in ['✅', '❌', '⚠️', '📊', '📑', '⚖️', '💰', '📅', '💡']):
                c.setFont("Helvetica-Bold", 12)
                linha_limpa = linha.replace('**', '')
                if y < margem_bottom + altura_linha * 2:
                    c.showPage()
                    y = altura - margem_top
                c.drawString(margem_esq, y, linha_limpa)
                c.setFont("Helvetica", 11)
                y -= altura_linha * 1.5
                continue
            
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
        
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(margem_esq, 30, "Desenvolvido pela INOVASSOL")
        c.drawString(largura - margem_dir - 150, 30, "Consulte seu advogado para orientações")
        
        c.save()
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
        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado"}), 400
            
        if not allowed_file(file.filename):
            return jsonify({"erro": "Formato inválido. Aceitos: PDF, PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP"}), 400
        
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size > MAX_FILE_SIZE:
            return jsonify({"erro": f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE//1024//1024}MB"}), 400
        
        file_bytes = file.read()
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        
        file_hash = hashlib.md5(file_bytes).hexdigest()
        logging.info(f"Processando arquivo: {secure_filename(file.filename)} ({size/1024:.1f}KB) - Hash: {file_hash}")
        
        if file_extension == 'pdf':
            texto_original, metadados = extrair_texto_pdf(file_bytes)
        elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
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
            
            if metadados.get("qualidade_ocr") == "baixa":
                texto_original = "[AVISO: A qualidade do OCR foi baixa. Alguns trechos podem estar incorretos.]\n\n" + texto_original
        else:
            return jsonify({"erro": "Tipo de arquivo não suportado"}), 400
        
        if len(texto_original) < 10:
            return jsonify({"erro": "Arquivo não contém texto suficiente para processar"}), 400
        
        texto_simplificado, erro = simplificar_com_gemini(texto_original)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        metadados_geracao = {
            "modelo": results_cache.get(hashlib.md5(texto_original.encode()).hexdigest(), {}).get("modelo", "Gemini"),
            "tipo": metadados.get("tipo", file_extension)
        }
        
        if file_extension == 'pdf':
            metadados_geracao["paginas"] = metadados.get("total_paginas")
            metadados_geracao["usou_ocr"] = metadados.get("usou_ocr")
        else:
            metadados_geracao["dimensoes"] = metadados.get("dimensoes")
            metadados_geracao["qualidade_ocr"] = metadados.get("qualidade_ocr")
        
        pdf_filename = f"simplificado_{file_hash[:8]}.pdf"
        pdf_path = gerar_pdf_simplificado(texto_simplificado, metadados_geracao, pdf_filename)
        
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        
        analise = analisar_resultado_judicial(texto_simplificado)
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto_original)) * 100, 1),
            "metadados": metadados,
            "analise": analise,
            "modelo_usado": metadados_geracao.get("modelo", "Gemini"),
            "tipo_arquivo": file_extension
        })
        
    except Exception as e:
        logging.error(f"Erro ao processar arquivo: {e}")
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
            
        if len(texto) > 30000:
            return jsonify({"erro": "Texto muito longo. Máximo: 30.000 caracteres. Divida em partes menores."}), 400
        
        texto_simplificado, erro = simplificar_com_gemini(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
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
    
    if "✅" in texto or "vitória" in texto_lower or "procedente" in texto_lower:
        analise["tipo_resultado"] = "vitoria"
        analise["sentimento"] = "positivo"
    elif "❌" in texto or "derrota" in texto_lower or "improcedente" in texto_lower:
        analise["tipo_resultado"] = "derrota"
        analise["sentimento"] = "negativo"
    elif "⚠️" in texto or "parcial" in texto_lower:
        analise["tipo_resultado"] = "parcial"
        analise["sentimento"] = "neutro"
    
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
        diagnostico_info["python_libs"]["opencv"] = f"Erro: {str(e)
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
    
    import platform
    diagnostico_info["sistema"]["os"] = platform.system()
    diagnostico_info["sistema"]["arquitetura"] = platform.machine()
    diagnostico_info["sistema"]["python_version"] = platform.python_version()
    
    diagnostico_info["configuracao"]["gemini_api_configurada"] = bool(GEMINI_API_KEY)
    diagnostico_info["configuracao"]["temp_dir"] = TEMP_DIR
    diagnostico_info["configuracao"]["max_file_size_mb"] = MAX_FILE_SIZE // 1024 // 1024
    diagnostico_info["configuracao"]["tessdata_prefix"] = os.getenv("TESSDATA_PREFIX", "Não configurado")
    
    return jsonify(diagnostico_info)

@app.route("/diagnostico_api")
def diagnostico_api():
    """Testa conectividade com a API Gemini"""
    if not GEMINI_API_KEY:
        return jsonify({"erro": "API Key não configurada"}), 500
    
    resultados = []
    
    for modelo in GEMINI_MODELS:
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
                
                url_version = url_base.split('/')[4]
                
                resultados.append({
                    "modelo": modelo["name"],
                    "url_version": url_version,
                    "status": response.status_code,
                    "ok": response.status_code == 200,
                    "mensagem": "✅ OK" if response.status_code == 200 else f"❌ {response.text[:200]}"
                })
                
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
    pdf_path = session.get('pdf_path')
    pdf_filename = session.get('pdf_filename', 'documento_simplificado.pdf')
    
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"erro": "PDF não encontrado. Por favor, processe um documento primeiro"}), 404
    
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

def cleanup_temp_files():
    """Limpa arquivos temporários antigos periodicamente"""
    while True:
        try:
            time.sleep(3600)
            now = time.time()
            
            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('simplificado_'):
                    filepath = os.path.join(TEMP_DIR, filename)
                    try:
                        if os.stat(filepath).st_mtime < now - 3600:
                            os.remove(filepath)
                            logging.info(f"Arquivo temporário removido: {filename}")
                    except Exception as e:
                        logging.warning(f"Erro ao remover {filename}: {e}")
            
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

cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
