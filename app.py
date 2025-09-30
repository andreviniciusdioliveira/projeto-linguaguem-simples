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

# Prompt otimizado e estruturado (NÃO ALTERADO)
PROMPT_SIMPLIFICACAO = """**Papel:** Você é um especialista em linguagem simples aplicada ao Poder Judiciário, com experiência em transformar textos jurídicos complexos em comunicações claras e acessíveis.

**ESTRUTURA DE ANÁLISE OBRIGATÓRIA:**

1. IDENTIFICAÇÃO DO DOCUMENTO
- Tipo: [Sentença/Despacho/Decisão/Acórdão]
- Número do processo: [identificar]
- Partes envolvidas: [Autor x Réu]
- Assunto principal: [identificar]

2. ANÁLISE DO RESULTADO (MAIS IMPORTANTE)
**ATENÇÃO:** Procure SEMPRE pela seção "DISPOSITIVO", "DECIDE", "ANTE O EXPOSTO" ou "DIANTE DO EXPOSTO"

Identificação do Vencedor:
- ✅ AUTOR GANHOU se encontrar: "JULGO PROCEDENTE", "CONDENO o réu/requerido", "DEFIRO"
- ❌ AUTOR PERDEU se encontrar: "JULGO IMPROCEDENTE", "CONDENO o autor/requerente", "INDEFIRO"  
- ⚠️ PARCIAL se encontrar: "JULGO PARCIALMENTE PROCEDENTE"

3. FORMATAÇÃO DA RESPOSTA

📊 RESUMO EXECUTIVO
[Use sempre um dos ícones abaixo]
✅ **VITÓRIA TOTAL** - Você ganhou completamente a causa
❌ **DERROTA** - Você perdeu a causa
⚠️ **VITÓRIA PARCIAL** - Você ganhou parte do que pediu
⏳ **AGUARDANDO** - Ainda não há decisão final
📋 **ANDAMENTO** - Apenas um despacho processual

**Em uma frase:** [Explicar o resultado em linguagem muito simples]

📑 O QUE ACONTECEU
[Explicar em 3-4 linhas o contexto do processo]

⚖️ O QUE O JUIZ DECIDIU
[Detalhar a decisão em linguagem simples, usando parágrafos curtos]

💰 VALORES E OBRIGAÇÕES
• Valor da causa: R$ [valor]
• Valores a receber: R$ [detalhar]
• Valores a pagar: R$ [detalhar]
• Honorários: [percentual e valor]
• Custas processuais: [quem paga]

📚 MINI DICIONÁRIO DOS TERMOS JURÍDICOS
[Listar apenas os termos jurídicos que aparecem no texto com explicação simples]
• **Termo 1:** Explicação clara e simples
• **Termo 2:** Explicação clara e simples
• **Termo 3:** Explicação clara e simples

---
*Documento processado em: [data/hora]*
*Este é um resumo simplificado. Consulte seu advogado para orientações específicas.*

**REGRAS DE SIMPLIFICAÇÃO:**
1. Use frases com máximo 20 palavras
2. Substitua jargões por palavras comuns
3. Explique siglas na primeira vez que aparecem
4. Use exemplos concretos quando possível
5. Mantenha tom respeitoso mas acessível
6. Destaque informações críticas com formatação

**TEXTO ORIGINAL A SIMPLIFICAR:**
"""

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
    
    # 1. DISPOSITIVO (mais importante)
    dispositivo_match = re.search(r'(DISPOSITIVO|DECIDE|ANTE O EXPOSTO|DIANTE DO EXPOSTO).*?(?=(CONCLUSÃO|P\.R\.I\.|$))', 
                                   texto, re.IGNORECASE | re.DOTALL)
    if dispositivo_match:
        secoes_importantes.append(("DISPOSITIVO", dispositivo_match.group(0), 10000))
    
    # 2. Identificação do processo
    inicio = texto[:3000]
    secoes_importantes.append(("IDENTIFICAÇÃO", inicio, 1000))
    
    # 3. Fundamentação (resumida)
    fundamentacao_match = re.search(r'(FUNDAMENTAÇÃO|FUNDAMENTO).*?(?=(DISPOSITIVO|DECIDE|$))', 
                                     texto, re.IGNORECASE | re.DOTALL)
    if fundamentacao_match:
        fund_texto = fundamentacao_match.group(0)
        # Pegar só as primeiras linhas da fundamentação
        fund_linhas = fund_texto.split('\n')[:30]
        secoes_importantes.append(("FUNDAMENTAÇÃO", '\n'.join(fund_linhas), 3000))
    
    # Montar texto truncado
    texto_final = "=== DOCUMENTO TRUNCADO PARA PROCESSAMENTO ===\n\n"
    
    tokens_usados = 0
    # Ordenar por prioridade (maior prioridade = mais tokens)
    for nome, conteudo, tokens_max in secoes_importantes:
        if tokens_usados >= max_tokens:
            break
            
        caracteres_max = min(tokens_max * 4, (max_tokens - tokens_usados) * 4)
        if len(conteudo) > caracteres_max:
            conteudo = conteudo[:caracteres_max] + "...[truncado]"
        
        texto_final += f"\n\n=== {nome} ===\n{conteudo}\n"
        tokens_usados += len(conteudo) // 4
    
    logging.info(f"Texto truncado de {tokens_estimados} para ~{tokens_usados} tokens")
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
        
        # Simplificar com Gemini
        texto_simplificado, erro = simplificar_com_gemini(texto_original)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Preparar metadados para o PDF
        metadados_geracao = {
            "modelo": results_cache.get(hashlib.md5(texto_original.encode()).hexdigest(), {}).get("modelo", "Gemini"),
            "tipo": metadados.get("tipo", file_extension)
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
        
        # Salvar o caminho na sessão
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        
        # Análise adicional do resultado
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
            
        if len(texto) > 50000:
            return jsonify({"erro": "Texto muito longo. Máximo: 50.000 caracteres"}), 400
        
        texto_simplificado, erro = simplificar_com_gemini(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Análise adicional
        analise = analisar_resultado_judicial(texto_simplificado)
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto)) * 100, 1),
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
