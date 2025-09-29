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
from functools import wraps
from datetime import datetime, timedelta
import hashlib
import tempfile
import threading
import json
import re
import subprocess
import numpy as np

# Tentativa de importar OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
    logging.info("OpenCV disponível")
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("OpenCV não disponível")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
TEMP_DIR = tempfile.gettempdir()

request_counts = {}
RATE_LIMIT = 10
cleanup_lock = threading.Lock()

results_cache = {}
CACHE_EXPIRATION = 3600

model_usage_stats = {model["name"]: {"attempts": 0, "successes": 0, "failures": 0} for model in GEMINI_MODELS}

# ============================================================================
# TIPOS DE DOCUMENTOS JURÍDICOS
# ============================================================================

TIPOS_DOCUMENTOS = {
    "sentenca": {
        "nome": "Sentença Judicial",
        "icone": "⚖️",
        "padroes": [
            r"sentença",
            r"ante\s+o\s+exposto",
            r"diante\s+do\s+exposto",
            r"isto\s+posto",
            r"julgo\s+(procedente|improcedente|parcialmente\s+procedente)",
            r"condeno\s+(o\s+réu|a\s+ré|os\s+réus)",
            r"extingo\s+o\s+processo",
            r"dispositivo",
            r"p\.?\s*r\.?\s*i\.?",
            r"resolvo\s+o\s+mérito"
        ],
        "peso": 10,
        "descricao": "Decisão final do juiz"
    },
    "acordao": {
        "nome": "Acórdão",
        "icone": "🏛️",
        "padroes": [
            r"acórdão",
            r"acordão",
            r"tribunal",
            r"câmara",
            r"turma\s+julgadora",
            r"desembargador",
            r"relator",
            r"ementa",
            r"por\s+unanimidade",
            r"negaram\s+provimento"
        ],
        "peso": 12,
        "descricao": "Decisão de tribunal"
    },
    "peticao_inicial": {
        "nome": "Petição Inicial",
        "icone": "📝",
        "padroes": [
            r"petição\s+inicial",
            r"excelentíssimo\s+senhor",
            r"exmo\.?\s+sr",
            r"dos\s+fatos",
            r"do\s+direito",
            r"dos\s+pedidos",
            r"pede\s+deferimento"
        ],
        "peso": 11,
        "descricao": "Início do processo"
    },
    "contestacao": {
        "nome": "Contestação",
        "icone": "🛡️",
        "padroes": [
            r"contestação",
            r"impugna\s+os\s+fatos",
            r"preliminarmente",
            r"da\s+improcedência",
            r"no\s+mérito"
        ],
        "peso": 9,
        "descricao": "Defesa do réu"
    },
    "despacho": {
        "nome": "Despacho",
        "icone": "📋",
        "padroes": [
            r"^despacho",
            r"intime-se",
            r"cite-se",
            r"cumpra-se",
            r"manifestem-se"
        ],
        "peso": 7,
        "descricao": "Ordem de andamento"
    },
    "decisao_interlocutoria": {
        "nome": "Decisão Interlocutória",
        "icone": "⚡",
        "padroes": [
            r"decisão\s+interlocutória",
            r"defiro\s+o\s+pedido",
            r"indefiro\s+o\s+pedido",
            r"tutela\s+de\s+urgência",
            r"liminar"
        ],
        "peso": 8,
        "descricao": "Decisão durante processo"
    }
}

def detectar_tipo_documento(texto):
    """Detecta tipo de documento jurídico"""
    texto_lower = texto.lower()
    texto_normalizado = re.sub(r'\s+', ' ', texto_lower)
    
    pontuacoes = {}
    
    for tipo, info in TIPOS_DOCUMENTOS.items():
        pontos = 0
        padroes_encontrados = []
        
        for padrao in info["padroes"]:
            try:
                matches = re.findall(padrao, texto_normalizado, re.IGNORECASE)
                if matches:
                    pontos += len(matches) * info["peso"]
                    padroes_encontrados.append(padrao)
            except Exception as e:
                logging.error(f"Erro no padrão {padrao}: {e}")
                continue
        
        if pontos > 0:
            pontuacoes[tipo] = {
                "pontos": pontos,
                "info": info,
                "padroes": padroes_encontrados
            }
    
    if not pontuacoes:
        logging.info("Nenhum tipo específico detectado, usando genérico")
        return {
            "tipo": "documento_generico",
            "nome": "Documento Jurídico",
            "icone": "📑",
            "confianca": 0,
            "descricao": "Documento não classificado",
            "padroes_encontrados": []
        }
    
    # Pegar o tipo com maior pontuação
    tipo_detectado = max(pontuacoes.items(), key=lambda x: x[1]["pontos"])
    tipo_id = tipo_detectado[0]
    dados = tipo_detectado[1]
    
    # Calcular confiança
    max_pontos = len(TIPOS_DOCUMENTOS[tipo_id]["padroes"]) * TIPOS_DOCUMENTOS[tipo_id]["peso"] * 3
    confianca = min(100, int((dados["pontos"] / max_pontos) * 100))
    
    resultado = {
        "tipo": tipo_id,
        "nome": dados["info"]["nome"],
        "icone": dados["info"]["icone"],
        "confianca": confianca,
        "descricao": dados["info"]["descricao"],
        "padroes_encontrados": dados["padroes"][:5]
    }
    
    logging.info(f"Tipo detectado: {resultado['nome']} com {confianca}% de confiança")
    
    return resultado

# ============================================================================
# PROMPTS ESPECÍFICOS POR TIPO DE DOCUMENTO
# ============================================================================

PROMPT_SENTENCA = """**INSTRUÇÕES CRÍTICAS - SENTENÇA JUDICIAL:**

Você está analisando uma SENTENÇA JUDICIAL. Este é o documento que ENCERRA o processo de primeiro grau.

**ESTRUTURA OBRIGATÓRIA DA ANÁLISE:**

1. **IDENTIFICAÇÃO** ⚖️
   - Tipo: Sentença Judicial
   - Número do processo: [extrair exatamente como está]
   - Juiz(a): [nome completo]
   - Vara/Comarca: [identificar]
   - Partes:
     * Autor(es): [nome completo]
     * Réu(s): [nome completo]

2. **RESULTADO DA SENTENÇA** 🎯 (MAIS IMPORTANTE)
   
   **ATENÇÃO MÁXIMA:** Procure SEMPRE pela seção "DISPOSITIVO", "ANTE O EXPOSTO", "DIANTE DO EXPOSTO" ou "ISTO POSTO"
   
   Identificação PRECISA do resultado:
   
   ✅ **AUTOR GANHOU TOTALMENTE** se encontrar:
   - "JULGO PROCEDENTE o pedido"
   - "JULGO PROCEDENTE a ação"
   - "CONDENO o réu a pagar"
   - "DEFIRO o pedido"
   
   ❌ **AUTOR PERDEU** se encontrar:
   - "JULGO IMPROCEDENTE"
   - "JULGO IMPROCEDENTE o pedido"
   - "CONDENO o autor ao pagamento de honorários"
   - "INDEFIRO o pedido"
   
   ⚠️ **VITÓRIA PARCIAL** se encontrar:
   - "JULGO PARCIALMENTE PROCEDENTE"
   - Parte dos pedidos foi deferida
   
   🚫 **PROCESSO EXTINTO SEM JULGAMENTO DE MÉRITO** se encontrar:
   - "EXTINGO o processo SEM RESOLUÇÃO DE MÉRITO"

3. **FORMATAÇÃO DA RESPOSTA**

📊 **RESUMO EXECUTIVO**
[Ícone apropriado: ✅/❌/⚠️/🚫] **[VITÓRIA TOTAL/DERROTA/VITÓRIA PARCIAL/EXTINÇÃO]**

**Em uma frase:** [Explicar o resultado em linguagem muito clara - exemplo: "O juiz decidiu que a empresa deve pagar R$ 15.000 ao autor"]

📑 **O QUE ACONTECEU**
[Explicar em 3-5 linhas o contexto: qual era a disputa]

⚖️ **O QUE O JUIZ DECIDIU**
[Detalhar a decisão em linguagem simples, parágrafo por parágrafo]
- Fundamentos principais
- Cada pedido e se foi aceito ou negado

💰 **VALORES E OBRIGAÇÕES**
• Valor da causa: R$ [se houver]
• Valores que o AUTOR vai receber: R$ [detalhar]
• Valores que o RÉU tem que pagar: R$ [detalhar]
• Honorários advocatícios: [percentual] = R$ [valor]
• Custas processuais: [quem paga]
• Correção monetária: [desde quando]
• Juros: [percentual e desde quando]

⏰ **PRAZOS IMPORTANTES**
• Prazo para recurso: [geralmente 15 dias]
• Outras obrigações com prazo

📚 **MINI DICIONÁRIO DOS TERMOS JURÍDICOS**
[Apenas termos que APARECEM no texto original]
• **Termo 1:** Explicação simples
• **Termo 2:** Explicação simples
• **Termo 3:** Explicação simples

📤 **PODE RECORRER?**
• Tipo de recurso: Apelação
• Prazo: 15 dias úteis
• Para quem: Tribunal [identificar]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente informações que não estão no texto
2. ❌ NUNCA adicione valores que não foram mencionados
3. ❌ NUNCA especule sobre possíveis recursos ou consequências
4. ✅ Se algo não estiver claro no texto, escreva "Não informado no documento"
5. ✅ Transcreva nomes, números de processo e valores EXATAMENTE como aparecem
6. ✅ Use frases com máximo 20 palavras
7. ✅ Mantenha tom respeitoso e neutro

**TEXTO DA SENTENÇA:**
{texto}

---
*Documento processado em: {data}*
*Este é um resumo simplificado. Consulte seu advogado para orientações específicas.*
"""

PROMPT_GENERICO = """**INSTRUÇÕES CRÍTICAS - DOCUMENTO JURÍDICO:**

Você está analisando um DOCUMENTO JURÍDICO: {tipo_documento}

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📋
   - Tipo: {tipo_documento}
   - Processo: [se houver]
   - Partes: [se identificáveis]

2. **ANÁLISE DO RESULTADO**
   [Identifique o objetivo e resultado do documento]

3. **FORMATAÇÃO DA RESPOSTA**

📊 **RESUMO EXECUTIVO**
[Ícone apropriado] **[STATUS/RESULTADO]**

**Em uma frase:** [Explicar o propósito/resultado do documento]

📑 **O QUE ACONTECEU**
[Explicar o contexto em 3-5 linhas]

📋 **CONTEÚDO PRINCIPAL**
[Explicar o conteúdo em linguagem simples]

💰 **VALORES E OBRIGAÇÕES** (se houver)
• Valores mencionados: R$ [listar]
• Obrigações: [detalhar]

⏰ **PRAZOS IMPORTANTES** (se houver)
• Prazo: [X dias]
• Para fazer: [ação específica]

📚 **MINI DICIONÁRIO DOS TERMOS JURÍDICOS**
[Apenas termos que APARECEM no texto]
• **Termo 1:** Explicação simples e clara
• **Termo 2:** Explicação simples e clara
• **Termo 3:** Explicação simples e clara

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente informações
2. ❌ NUNCA adicione valores não mencionados
3. ✅ Use APENAS o que está no texto
4. ✅ Se não souber, escreva "Não informado no documento"
5. ✅ Transcreva nomes e números EXATAMENTE
6. ✅ Use frases com máximo 20 palavras
7. ✅ Explique todos os termos jurídicos que aparecem no texto

**TEXTO DO DOCUMENTO:**
{texto}

---
*Documento processado em: {data}*
*Este é um resumo simplificado. Consulte seu advogado para orientações específicas.*
"""

def gerar_prompt_completo(texto, tipo_detectado):
    """Gera prompt baseado no tipo detectado"""
    
    tipo = tipo_detectado.get("tipo", "documento_generico")
    nome = tipo_detectado.get("nome", "Documento Jurídico")
    data = datetime.now().strftime('%d/%m/%Y às %H:%M')
    
    # Usar prompt específico para sentença
    if tipo == "sentenca":
        return PROMPT_SENTENCA.format(texto=texto, data=data)
    
    # Prompt genérico para outros tipos
    return PROMPT_GENERICO.format(
        tipo_documento=nome,
        texto=texto,
        data=data
    )

# ============================================================================
# TESSERACT
# ============================================================================

def verificar_tesseract():
    """Verifica Tesseract"""
    try:
        result = subprocess.run(['tesseract', '--version'], 
                              capture_output=True, text=True, check=True, timeout=10)
        version = result.stdout.split('\n')[0]
        logging.info(f"Tesseract: {version}")
        
        langs_result = subprocess.run(['tesseract', '--list-langs'], 
                                    capture_output=True, text=True, check=True, timeout=10)
        langs = langs_result.stdout.strip().split('\n')[1:]
        logging.info(f"Idiomas: {langs}")
        
        return True, version, langs
    except Exception as e:
        logging.error(f"Tesseract não disponível: {e}")
        return False, None, []

TESSERACT_AVAILABLE, TESSERACT_VERSION, TESSERACT_LANGS = verificar_tesseract()

# ============================================================================
# RATE LIMIT
# ============================================================================

def cleanup_old_requests():
    with cleanup_lock:
        now = datetime.now()
        to_remove = [ip for ip, (count, timestamp) in request_counts.items() 
                     if now - timestamp > timedelta(minutes=1)]
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
                        return jsonify({"erro": "Limite excedido"}), 429
                    request_counts[ip] = (count + 1, first_request)
                else:
                    request_counts[ip] = (1, now)
            else:
                request_counts[ip] = (1, now)
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# OCR
# ============================================================================

def processar_imagem_para_texto(image_bytes, formato='PNG'):
    """Extrai texto de imagem"""
    if not TESSERACT_AVAILABLE:
        raise ValueError("OCR não disponível")
    
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Melhorar contraste
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # OCR
        config = r'--oem 3 --psm 6'
        if 'por' in TESSERACT_LANGS:
            config += ' -l por+eng'
        else:
            config += ' -l eng'
        
        texto = pytesseract.image_to_string(img, config=config)
        
        metadados = {
            "tipo": "imagem",
            "formato": formato,
            "usou_ocr": True,
            "dimensoes": f"{img.width}x{img.height}",
            "qualidade_ocr": "boa" if len(texto) > 200 else "média"
        }
        
        return texto.strip(), metadados
        
    except Exception as e:
        logging.error(f"Erro OCR: {e}")
        raise

# ============================================================================
# PDF
# ============================================================================

def extrair_texto_pdf(pdf_bytes):
    """Extrai texto de PDF"""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            texto = ""
            for page in doc:
                texto += page.get_text() + "\n"
            
            metadados = {
                "tipo": "pdf",
                "total_paginas": len(doc),
                "tem_texto": bool(texto.strip())
            }
            
            if not texto.strip():
                raise ValueError("PDF sem texto")
            
            return texto.strip(), metadados
            
    except Exception as e:
        logging.error(f"Erro PDF: {e}")
        raise

# ============================================================================
# GEMINI
# ============================================================================

def simplificar_com_gemini(texto, max_retries=3):
    """Chama Gemini API"""
    
    # Detectar tipo SEMPRE
    logging.info("=" * 50)
    logging.info("INICIANDO DETECÇÃO DE TIPO DE DOCUMENTO")
    logging.info(f"Tamanho do texto: {len(texto)} caracteres")
    logging.info(f"Primeiros 200 caracteres: {texto[:200]}")
    
    tipo_detectado = detectar_tipo_documento(texto)
    
    logging.info(f"TIPO DETECTADO: {tipo_detectado['nome']}")
    logging.info(f"CONFIANÇA: {tipo_detectado['confianca']}%")
    logging.info(f"ÍCONE: {tipo_detectado['icone']}")
    logging.info(f"PADRÕES ENCONTRADOS: {len(tipo_detectado['padroes_encontrados'])}")
    logging.info("=" * 50)
    
    # Cache
    texto_hash = hashlib.md5(texto.encode()).hexdigest()
    if texto_hash in results_cache:
        cache_entry = results_cache[texto_hash]
        if time.time() - cache_entry["timestamp"] < CACHE_EXPIRATION:
            logging.info("Usando resultado do cache")
            return cache_entry["result"], None, tipo_detectado
    
    # Gerar prompt
    prompt = gerar_prompt_completo(texto, tipo_detectado)
    logging.info(f"Prompt gerado com {len(prompt)} caracteres")
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    
    for tentativa, modelo in enumerate(GEMINI_MODELS):
        logging.info(f"Tentativa {tentativa + 1}: Usando {modelo['name']}")
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4000,
                "topP": 0.8,
                "topK": 10
            }
        }
        
        try:
            response = requests.post(
                modelo["url"],
                headers=headers,
                json=payload,
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    texto_simplificado = data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    results_cache[texto_hash] = {
                        "result": texto_simplificado,
                        "timestamp": time.time(),
                        "modelo": modelo["name"],
                        "tipo_documento": tipo_detectado
                    }
                    
                    logging.info(f"✅ Sucesso com {modelo['name']}")
                    logging.info(f"Texto simplificado: {len(texto_simplificado)} caracteres")
                    
                    return texto_simplificado, None, tipo_detectado
                    
        except Exception as e:
            logging.error(f"Erro {modelo['name']}: {e}")
            continue
    
    return None, "Erro ao processar com IA", tipo_detectado

# ============================================================================
# PDF GERAÇÃO
# ============================================================================

def gerar_pdf_simplificado(texto, metadados=None, tipo_documento=None, filename="documento.pdf"):
    """Gera PDF"""
    output_path = os.path.join(TEMP_DIR, filename)
    
    try:
        c = canvas.Canvas(output_path, pagesize=letter)
        largura, altura = letter
        
        y = altura - 50
        
        # Título
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, "Documento Simplificado")
        y -= 40
        
        # Tipo
        if tipo_documento:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, f"{tipo_documento.get('icone', '')} {tipo_documento.get('nome', '')}")
            y -= 30
        
        # Texto
        c.setFont("Helvetica", 11)
        for linha in texto.split('\n'):
            if y < 100:
                c.showPage()
                y = altura - 50
                c.setFont("Helvetica", 11)
            
            if linha.strip():
                c.drawString(50, y, linha[:100])
                y -= 14
        
        c.save()
        return output_path
        
    except Exception as e:
        logging.error(f"Erro gerar PDF: {e}")
        raise

# ============================================================================
# ANÁLISE
# ============================================================================

def analisar_resultado_judicial(texto, tipo_documento=None):
    """Analisa resultado"""
    analise = {
        "tipo_resultado": "indefinido",
        "tem_valores": "r$" in texto.lower(),
        "tem_prazos": "prazo" in texto.lower() or "dias" in texto.lower(),
        "tipo_documento": tipo_documento.get("nome") if tipo_documento else "Não identificado",
        "confianca_tipo": tipo_documento.get("confianca") if tipo_documento else 0
    }
    
    texto_lower = texto.lower()
    
    if "✅" in texto or "procedente" in texto_lower:
        analise["tipo_resultado"] = "vitoria"
    elif "❌" in texto or "improcedente" in texto_lower:
        analise["tipo_resultado"] = "derrota"
    
    return analise

# ============================================================================
# ROTAS
# ============================================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/processar", methods=["POST"])
@rate_limit
def processar():
    """Processa arquivo"""
    try:
        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo"}), 400
            
        file = request.files['file']
        if not file.filename:
            return jsonify({"erro": "Arquivo vazio"}), 400
        
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size > MAX_FILE_SIZE:
            return jsonify({"erro": "Arquivo grande demais"}), 400
        
        file_bytes = file.read()
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        
        logging.info(f"Processando: {file.filename}")
        
        # Extrair texto
        if file_extension == 'pdf':
            texto_original, metadados = extrair_texto_pdf(file_bytes)
        elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
            if not TESSERACT_AVAILABLE:
                return jsonify({"erro": "OCR não disponível"}), 500
            texto_original, metadados = processar_imagem_para_texto(file_bytes, file_extension.upper())
        else:
            return jsonify({"erro": "Formato inválido"}), 400
        
        if len(texto_original) < 10:
            return jsonify({"erro": "Texto insuficiente"}), 400
        
        # Simplificar
        texto_simplificado, erro, tipo_documento = simplificar_com_gemini(texto_original)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Gerar PDF
        pdf_filename = f"simplificado_{int(time.time())}.pdf"
        pdf_path = gerar_pdf_simplificado(texto_simplificado, metadados, tipo_documento, pdf_filename)
        
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        
        # Análise
        analise = analisar_resultado_judicial(texto_simplificado, tipo_documento)
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "tipo_documento": tipo_documento,
            "analise": analise
        })
        
    except Exception as e:
        logging.error(f"Erro: {e}", exc_info=True)
        return jsonify({"erro": str(e)}), 500

@app.route("/processar_texto", methods=["POST"])
@rate_limit
def processar_texto():
    """Processa texto manual"""
    try:
        data = request.get_json()
        texto = data.get("texto", "").strip()
        
        if not texto or len(texto) < 20:
            return jsonify({"erro": "Texto muito curto"}), 400
        
        texto_simplificado, erro, tipo_documento = simplificar_com_gemini(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        analise = analisar_resultado_judicial(texto_simplificado, tipo_documento)
        
        return jsonify({
            "texto": texto_simplificado,
            "tipo_documento": tipo_documento,
            "analise": analise
        })
        
    except Exception as e:
        logging.error(f"Erro: {e}")
        return jsonify({"erro": str(e)}), 500

@app.route("/download_pdf")
def download_pdf():
    """Download PDF"""
    pdf_path = session.get('pdf_path')
    pdf_filename = session.get('pdf_filename', 'documento.pdf')
    
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"erro": "PDF não encontrado"}), 404
    
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)

@app.route("/diagnostico")
def diagnostico():
    """Diagnóstico"""
    return jsonify({
        "status": "online",
        "tesseract": {
            "disponivel": TESSERACT_AVAILABLE,
            "version": TESSERACT_VERSION,
            "linguas": TESSERACT_LANGS
        },
        "opencv": CV2_AVAILABLE,
        "gemini": bool(GEMINI_API_KEY),
        "tipos_documentos": len(TIPOS_DOCUMENTOS)
    })

@app.route("/health")
def health():
    """Health check"""
    return jsonify({"status": "healthy"})

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Limpeza
def cleanup_temp_files():
    while True:
        try:
            time.sleep(3600)
            now = time.time()
            
            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('simplificado_'):
                    filepath = os.path.join(TEMP_DIR, filename)
                    if os.stat(filepath).st_mtime < now - 3600:
                        os.remove(filepath)
                        
        except Exception as e:
            logging.error(f"Erro limpeza: {e}")

cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
