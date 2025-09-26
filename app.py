from flask import Flask, render_template, request, send_file, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
import fitz
import pytesseract
from PIL import Image
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

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Modelos Gemini disponíveis (do mais barato/rápido ao mais caro/potente)
GEMINI_MODELS = [
    {
        "name": "gemini-1.5-flash-8b",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-8b:generateContent",
        "max_tokens": 8192,
        "priority": 1
    },
    {
        "name": "gemini-1.5-flash",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "max_tokens": 32000,
        "priority": 2
    },
    {
        "name": "gemini-2.0-flash-exp",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
        "max_tokens": 40000,
        "priority": 3
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

# Prompt otimizado e estruturado
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
        "qualidade_ocr": "indefinida"
    }
    
    try:
        # Abrir a imagem
        img = Image.open(io.BytesIO(image_bytes))
        
        # Salvar dimensões originais
        metadados["dimensoes"] = f"{img.width}x{img.height}"
        
        # Converter para RGB se necessário
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Pré-processamento da imagem para melhorar OCR
        # 1. Redimensionar se muito grande
        if img.width > 3000 or img.height > 3000:
            ratio = min(3000/img.width, 3000/img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logging.info(f"Imagem redimensionada para {new_size}")
        
        # 2. Aumentar contraste
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # 3. Converter para escala de cinza
        img = img.convert('L')
        
        # 4. Aplicar threshold para binarização
        threshold = 180
        img = img.point(lambda p: 255 if p > threshold else 0)
        
        # Configurações otimizadas do Tesseract para português
        custom_config = r'--oem 3 --psm 3 -l por+eng'
        
        # Executar OCR
        logging.info("Iniciando OCR na imagem...")
        texto = pytesseract.image_to_string(img, config=custom_config)
        
        # Avaliar qualidade do OCR
        if len(texto.strip()) < 50:
            metadados["qualidade_ocr"] = "baixa"
            
            # Tentar novamente com configurações diferentes
            custom_config = r'--oem 3 --psm 6 -l por'
            texto_alt = pytesseract.image_to_string(img, config=custom_config)
            
            if len(texto_alt.strip()) > len(texto.strip()):
                texto = texto_alt
                metadados["qualidade_ocr"] = "média"
        else:
            # Verificar densidade de caracteres especiais (indicador de qualidade)
            special_chars = sum(1 for c in texto if c in '!@#$%^&*()[]{}|\\<>?')
            if special_chars / len(texto) > 0.1:
                metadados["qualidade_ocr"] = "baixa"
            elif len(texto.strip()) > 200:
                metadados["qualidade_ocr"] = "boa"
            else:
                metadados["qualidade_ocr"] = "média"
        
        # Limpar texto extraído
        texto = limpar_texto_ocr(texto)
        
        if not texto.strip():
            raise ValueError("Nenhum texto foi extraído da imagem")
        
        logging.info(f"OCR concluído. Qualidade: {metadados['qualidade_ocr']}, Caracteres extraídos: {len(texto)}")
        
    except Exception as e:
        logging.error(f"Erro ao processar imagem: {e}")
        raise
    
    return texto, metadados

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
            if alpha_count / len(linha_strip) >= 0.3:
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
    
    ocr_disponivel = True
    
    try:
        import subprocess
        subprocess.run(['tesseract', '--version'], capture_output=True, check=True)
    except:
        ocr_disponivel = False
        logging.warning("Tesseract não está instalado. OCR desabilitado.")
    
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
                    elif ocr_disponivel:
                        logging.info(f"Aplicando OCR na página {i+1}")
                        metadados["usou_ocr"] = True
                        metadados["paginas_com_ocr"].append(i+1)
                        
                        pix = page.get_pixmap(dpi=150)
                        img = Image.open(io.BytesIO(pix.tobytes()))
                        
                        # Configurações otimizadas do Tesseract
                        custom_config = r'--oem 3 --psm 6 -l por'
                        conteudo = pytesseract.image_to_string(img, config=custom_config)
                        texto_completo += conteudo + "\n"
                    
                except Exception as e:
                    logging.error(f"Erro ao processar página {i+1}: {e}")
            
            texto = texto_completo.strip()
            if not texto:
                raise ValueError("Nenhum texto foi extraído do PDF")
                
    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise
    
    return texto, metadados

def analisar_complexidade_texto(texto):
    """Analisa a complexidade do texto para escolher o modelo apropriado"""
    complexidade = {
        "caracteres": len(texto),
        "palavras": len(texto.split()),
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
    
    # Determinar nível de complexidade
    if complexidade["caracteres"] > 10000 or complexidade["termos_tecnicos"] > 20 or complexidade["citacoes"] > 15:
        complexidade["nivel"] = "alto"
    elif complexidade["caracteres"] > 5000 or complexidade["termos_tecnicos"] > 10 or complexidade["citacoes"] > 8:
        complexidade["nivel"] = "médio"
    
    return complexidade

def escolher_modelo_gemini(complexidade, tentativa=0):
    """Escolhe o modelo Gemini mais apropriado baseado na complexidade"""
    if complexidade["nivel"] == "baixo" and tentativa == 0:
        return GEMINI_MODELS[0]  # Modelo mais leve
    elif complexidade["nivel"] == "médio" or tentativa == 1:
        return GEMINI_MODELS[1]  # Modelo intermediário
    else:
        return GEMINI_MODELS[2] if tentativa < len(GEMINI_MODELS) else GEMINI_MODELS[-1]  # Modelo mais potente

def simplificar_com_gemini(texto, max_retries=3):
    """Chama a API do Gemini com fallback automático entre modelos"""
    
    # Para textos muito grandes, dividir em chunks se necessário
    MAX_CHUNK_SIZE = 30000  # Aumentado para processar textos maiores
    
    # Se o texto for muito grande, processar em partes
    if len(texto) > MAX_CHUNK_SIZE:
        # Dividir o texto preservando a estrutura
        chunks = []
        current_chunk = ""
        paragrafos = texto.split('\n\n')
        
        for paragrafo in paragrafos:
            if len(current_chunk) + len(paragrafo) < MAX_CHUNK_SIZE:
                current_chunk += paragrafo + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = paragrafo + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Processar o chunk mais importante (geralmente o que contém o dispositivo)
        texto_principal = chunks[-1] if "DISPOSITIVO" in chunks[-1] or "JULGO" in chunks[-1] else chunks[0]
        
        # Adicionar contexto dos outros chunks
        if len(chunks) > 1:
            texto_contexto = "\n\n[CONTEXTO ADICIONAL DO PROCESSO]\n"
            for i, chunk in enumerate(chunks):
                if chunk != texto_principal:
                    texto_contexto += f"\nParte {i+1}: " + chunk[:500] + "...\n"
            texto = texto_principal + texto_contexto
    
    # Verificar cache
    texto_hash = hashlib.md5(texto.encode()).hexdigest()
    if texto_hash in results_cache:
        cache_entry = results_cache[texto_hash]
        if time.time() - cache_entry["timestamp"] < CACHE_EXPIRATION:
            logging.info(f"Resultado encontrado no cache para hash {texto_hash[:8]}")
            return cache_entry["result"], None
    
    # Analisar complexidade
    complexidade = analisar_complexidade_texto(texto)
    logging.info(f"Complexidade do texto: {complexidade}")
    
    prompt_completo = PROMPT_SIMPLIFICACAO + texto
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    
    errors = []
    
    # Tentar com diferentes modelos
    for tentativa in range(len(GEMINI_MODELS)):
        modelo = escolher_modelo_gemini(complexidade, tentativa)
        logging.info(f"Tentativa {tentativa + 1}: Usando modelo {modelo['name']}")
        
        model_usage_stats[modelo["name"]]["attempts"] += 1
        
        # Ajustar tokens baseado no modelo
        max_tokens = min(4000, modelo["max_tokens"] // 2)
        
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
                "temperature": 0.3,
                "maxOutputTokens": max_tokens,
                "topP": 0.8,
                "topK": 10
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
        
        for retry in range(max_retries):
            try:
                start_time = time.time()
                response = requests.post(
                    modelo["url"],
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    data = response.json()
                    elapsed = round(time.time() - start_time, 2)
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        texto_simplificado = data["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # Adicionar ao cache
                        results_cache[texto_hash] = {
                            "result": texto_simplificado,
                            "timestamp": time.time(),
                            "modelo": modelo["name"]
                        }
                        
                        model_usage_stats[modelo["name"]]["successes"] += 1
                        logging.info(f"Sucesso com {modelo['name']} em {elapsed}s")
                        
                        return texto_simplificado, None
                    else:
                        errors.append(f"{modelo['name']}: Resposta vazia")
                        
                elif response.status_code == 429:
                    # Rate limit - tentar próximo modelo
                    errors.append(f"{modelo['name']}: Limite de requisições excedido")
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    break  # Sair do loop de retry, tentar próximo modelo
                    
                elif response.status_code == 400:
                    # Bad request - pode ser tokens demais
                    errors.append(f"{modelo['name']}: Requisição inválida (possível excesso de tokens)")
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    break
                    
                else:
                    errors.append(f"{modelo['name']}: Erro HTTP {response.status_code}")
                    
            except requests.exceptions.Timeout:
                errors.append(f"{modelo['name']}: Timeout")
                if retry < max_retries - 1:
                    time.sleep(2 ** retry)
                    
            except Exception as e:
                errors.append(f"{modelo['name']}: {str(e)}")
                logging.error(f"Erro com {modelo['name']}: {e}")
        
        # Pequena pausa antes de tentar próximo modelo
        if tentativa < len(GEMINI_MODELS) - 1:
            time.sleep(1)
    
    # Se todos os modelos falharam
    error_summary = " | ".join(errors)
    logging.error(f"Todos os modelos falharam: {error_summary}")
    return None, f"Erro ao processar. Tentativas: {error_summary}"

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
        c.drawString(margem_esq, 30, "Desenvolvido")
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
            texto_original, metadados = processar_imagem_para_texto(file_bytes, file_extension.upper())
            
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
            "modelo": results_cache.get(file_hash, {}).get("modelo", "Gemini"),
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
            
        if len(texto) > 10000:
            return jsonify({"erro": "Texto muito longo. Máximo: 10.000 caracteres"}), 400
        
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

@app.route("/estatisticas")
def estatisticas():
    """Retorna estatísticas de uso dos modelos"""
    return jsonify({
        "modelos": model_usage_stats,
        "cache_size": len(results_cache),
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
    # Verificar se Tesseract está disponível
    ocr_available = False
    try:
        import subprocess
        subprocess.run(['tesseract', '--version'], capture_output=True, check=True)
        ocr_available = True
    except:
        pass
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(GEMINI_API_KEY),
        "models_available": len(GEMINI_MODELS),
        "cache_entries": len(results_cache),
        "ocr_available": ocr_available,
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

def detectar_tipo_arquivo(file_bytes):
    """Detecta o tipo de arquivo pelos bytes iniciais (magic numbers)"""
    # Magic numbers para diferentes formatos
    if file_bytes[:4] == b'%PDF':
        return 'pdf'
    elif file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    elif file_bytes[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    elif file_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    elif file_bytes[:2] == b'BM':
        return 'bmp'
    elif file_bytes[:4] in (b'II\x2a\x00', b'MM\x00\x2a'):
        return 'tiff'
    elif file_bytes[:4] == b'RIFF' and file_bytes[8:12] == b'WEBP':
        return 'webp'
    else:
        return None

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
                    if os.stat(filepath).st_mtime < now - 3600:  # Arquivos com mais de 1 hora
                        os.remove(filepath)
                        logging.info(f"Arquivo temporário removido: {filename}")
            
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
