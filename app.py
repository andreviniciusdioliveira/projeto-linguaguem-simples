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
import google.generativeai as genai
import database

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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# CONFIGURAR GEMINI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logging.info("✅ Gemini configurado com API Key")
else:
    logging.error("❌ GEMINI_API_KEY não configurada!")

# INICIALIZAR BANCO DE DADOS
try:
    database.init_db()
    logging.info("✅ Banco de dados de estatísticas inicializado")
except Exception as e:
    logging.error(f"❌ Erro ao inicializar banco de dados: {e}")

# Modelos Gemini
GEMINI_MODELS = [
    {
        "name": "gemini-2.0-flash-exp",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 1
    },
    {
        "name": "gemini-1.5-flash",
        "urls": [
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        ],
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 2
    }
]

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
TEMP_DIR = tempfile.gettempdir()

# Rate limiting
request_counts = {}
RATE_LIMIT = 10
cleanup_lock = threading.Lock()

# Cache
results_cache = {}
CACHE_EXPIRATION = 3600

# Estatísticas de uso dos modelos
model_usage_stats = {model["name"]: {"attempts": 0, "successes": 0, "failures": 0} for model in GEMINI_MODELS}

# ===== LGPD - Sistema de Limpeza Automática =====
temp_files_tracker = {}
TEMP_FILE_EXPIRATION = 1800  # 30 minutos

def registrar_arquivo_temporario(file_path, session_id=None):
    """Registra arquivo temporário para limpeza automática (LGPD)"""
    with cleanup_lock:
        temp_files_tracker[file_path] = {
            "criado_em": time.time(),
            "session_id": session_id,
            "expira_em": time.time() + TEMP_FILE_EXPIRATION
        }
    logging.info(f"📋 Arquivo temporário registrado: {file_path}")

def limpar_arquivos_expirados():
    """Remove arquivos temporários expirados (LGPD)"""
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
                    logging.info(f"🗑️ LGPD: Arquivo removido: {file_path}")
                del temp_files_tracker[file_path]
            except Exception as e:
                logging.error(f"Erro ao remover arquivo {file_path}: {e}")

    if arquivos_removidos > 0:
        logging.info(f"✅ LGPD: {arquivos_removidos} arquivo(s) removido(s)")

    return arquivos_removidos

def iniciar_limpeza_automatica():
    """Inicia thread de limpeza automática (LGPD)"""
    def executar_limpeza():
        while True:
            time.sleep(60)
            limpar_arquivos_expirados()

    thread = threading.Thread(target=executar_limpeza, daemon=True)
    thread.start()
    logging.info("🔄 Sistema de limpeza automática LGPD iniciado")

iniciar_limpeza_automatica()

def verificar_tesseract():
    """Verifica se o Tesseract está disponível"""
    try:
        result = subprocess.run(['tesseract', '--version'],
                              capture_output=True, text=True, check=True, timeout=10)
        version = result.stdout.split('\n')[0]
        logging.info(f"Tesseract detectado: {version}")

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
                        return jsonify({"erro": "Limite de requisições excedido"}), 429
                    request_counts[ip] = (count + 1, first_request)
                else:
                    request_counts[ip] = (1, now)
            else:
                request_counts[ip] = (1, now)

        return f(*args, **kwargs)
    return decorated_function

# ============= PROMPT DE SIMPLIFICAÇÃO =============

PROMPT_SIMPLIFICACAO_MELHORADO = """**VOCÊ É UM ASSISTENTE QUE EXPLICA DOCUMENTOS JURÍDICOS DE FORMA PESSOAL, EMPÁTICA E SIMPLES.**

**TOM DE VOZ E EMPATIA:**
- Fale DIRETAMENTE com o cidadão usando "você"
- Seja MUITO empático
- Use frases como: "Entendo que esta situação pode ser difícil..."
- NUNCA use termos técnicos sem explicar
- Use linguagem de conversa calorosa, não formal/fria
- Seja direto mas gentil

---

🚨🚨🚨 **REGRA CRÍTICA ANTI-ALUCINAÇÃO** 🚨🚨🚨

**NUNCA NUNCA NUNCA invente informações que NÃO estão no documento!**

❌ **NÃO FAÇA:**
- Inventar valores que não estão explícitos
- Deduzir datas que não foram mencionadas
- Criar prazos que não aparecem
- Supor nomes que não estão escritos
- Inventar decisões não mencionadas

✅ **FAÇA:**
- Use APENAS informações que você pode CITAR diretamente
- Se algo NÃO está no documento, diga: "O documento não menciona [isso]"
- Quando em dúvida, OMITA a informação - não invente!

**SE NÃO ESTÁ NO DOCUMENTO, NÃO EXISTE!**

---

**SIMPLIFICAÇÃO OBRIGATÓRIA DE TERMOS TÉCNICOS:**
- "PARCIALMENTE PROCEDENTE" → "Você ganhou PARTE do que pediu"
- "PROCEDENTE" → "Você ganhou"
- "IMPROCEDENTE" → "Você perdeu" ou "Seu pedido foi negado"
- "Habeas Corpus" → "um pedido urgente para garantir sua liberdade"
- "Cerceamento de defesa" → "você foi impedido de se defender corretamente"
- "Deferido" → "aprovado" ou "aceito"
- "Indeferido" → "negado" ou "recusado"

---

**ESTRUTURA DA EXPLICAÇÃO:**

📊 **RESULTADO EM UMA FRASE**
[Escolha o emoji e explique em 1 frase o que aconteceu]
✅ VITÓRIA TOTAL - Você ganhou tudo que pediu
❌ DERROTA - Você perdeu
⚠️ VITÓRIA PARCIAL - Você ganhou parte do que pediu
⏳ AGUARDANDO JULGAMENTO - Ainda não foi decidido
📋 ANDAMENTO DO PROCESSO - Apenas uma movimentação

**Em uma frase simples:** [Explique o resultado direto]

---

📑 **O QUE ESTÁ ACONTECENDO**
[Em 2-3 parágrafos curtos, conte a história do processo]
- O que você pediu na Justiça?
- O que a outra parte disse?
- Qual foi a decisão até agora?

Use frases de 10-15 palavras. Seja direto e claro.

---

⚖️ **A DECISÃO DO [AUTORIDADE]**

**REGRA IMPORTANTE - ESCOLHA O TÍTULO CORRETO:**
- Se for SENTENÇA, DECISÃO ou DESPACHO → use "**A DECISÃO DO JUIZ**"
- Se for ACÓRDÃO → use "**A DECISÃO DO DESEMBARGADOR(A)**"
- Se for MANDADO → use "**ORDEM JUDICIAL**"

[Explique em linguagem super simples o que foi decidido]

Use blocos curtos:
- Sobre [assunto X]: O juiz (ou desembargador/a) decidiu que...
- Sobre [assunto Y]: O juiz (ou desembargador/a) entendeu que...

IMPORTANTE: Explique o PORQUÊ da decisão de forma simples.

---

💰 **VALORES E O QUE VOCÊ PRECISA FAZER**

🚨 **REGRA ANTI-ALUCINAÇÃO PARA VALORES** 🚨
**NUNCA invente valores!** Se o documento NÃO menciona valor específico, NÃO escreva valores!

**Valores mencionados:**

✅ O QUE VOCÊ VAI GANHAR:
- [Liste APENAS valores que estão EXPLÍCITOS no documento]

❌ O QUE VOCÊ NÃO VAI GANHAR:
- [Liste valores negados]

**Sobre custas e honorários:**
- [Se tem justiça gratuita: "Você NÃO vai pagar porque tem justiça gratuita"]
- [Se não tem: Liste os valores a pagar]

**Próximos passos:**
[O que você deve fazer agora? Seja ESPECÍFICO e PRÁTICO]

---

📚 **PALAVRAS QUE PODEM APARECER NO DOCUMENTO**
[Liste APENAS 5-7 termos mais importantes]

- **[Termo]**: Significa [explicação em 5-10 palavras]

**Não coloque mais de 7 termos!**

---

*💡 Dica: Este resumo não substitui orientação de um advogado. Procure a Defensoria Pública (gratuita) ou um advogado.*

---

**REGRAS DE ESCRITA:**
1. Máximo 15 palavras por frase
2. NUNCA use: "exequente", "executado", "lide", "mérito"
3. SEMPRE use: "você", "a outra parte", "o processo"
4. Seja empático: "Você ganhou!", "Infelizmente você perdeu"
5. Mini dicionário: NO MÁXIMO 7 termos
"""

# ============= ANÁLISE COMPLETA COM GEMINI =============

def analisar_documento_completo_gemini(texto, perspectiva="nao_informado"):
    """
    ANÁLISE COMPLETA DO DOCUMENTO EM 1 ÚNICA CHAMADA GEMINI
    Retorna dict com análise técnica + texto simplificado
    """

    # Truncar texto se necessário
    if len(texto) > 15000:
        texto_analise = texto[:7500] + "\n\n[... TEXTO TRUNCADO ...]\n\n" + texto[-7500:]
    else:
        texto_analise = texto

    # Mapear perspectiva
    if perspectiva == "autor":
        instrucao_perspectiva = '**CRÍTICO:** Use "VOCÊ" para autor/requerente e "a outra parte" para réu.'
    elif perspectiva == "reu":
        instrucao_perspectiva = '**CRÍTICO:** Use "VOCÊ" para réu/requerido e "a outra parte" para autor.'
    else:
        instrucao_perspectiva = 'Use os nomes reais das partes (não use "você").'

    prompt = f"""Você é um especialista em análise de documentos jurídicos brasileiros.

🎯 **TAREFA:** Analisar este documento COMPLETAMENTE e gerar:
1. Identificação técnica (tipo, partes, autoridade)
2. Texto simplificado em linguagem acessível

---

## 🔍 **PARTE 1: ANÁLISE TÉCNICA (JSON)**

Analise o documento e retorne JSON com:
```json
{{
  "tipo_documento": "acordao|sentenca|mandado|decisao|despacho|intimacao",
  "confianca_tipo": "ALTA|MÉDIA|BAIXA",
  "razao_tipo": "Explique em 1 frase por que é este tipo",

  "urgencia": "MÁXIMA|ALTA|MÉDIA|BAIXA",
  "acao_necessaria": "Frase curta sobre o que fazer",

  "tem_justica_gratuita": true|false,
  "trecho_justica_gratuita": "trecho literal ou vazio",

  "autoridade": {{
    "cargo": "Juiz|Juíza|Desembargador|Desembargadora",
    "nome": "Nome completo"
  }},

  "partes": {{
    "autor": "Nome completo ou null",
    "reu": "Nome completo ou null"
  }},

  "decisao_resumida": "1 frase: o que foi decidido",

  "valores_principais": {{
    "total_a_receber": "R$ XXX ou null",
    "danos_morais": "R$ XXX ou null",
    "danos_materiais": "R$ XXX ou null",
    "honorarios": "X% ou R$ XXX ou null",
    "custas": "quem paga ou null"
  }},

  "prazos": [
    {{"tipo": "recurso", "prazo": "15 dias"}},
    {{"tipo": "contestacao", "prazo": "30 dias"}}
  ],

  "audiencia": {{
    "tem_audiencia": true|false,
    "data": "DD/MM/AAAA ou null",
    "hora": "HH:MM ou null",
    "link": "URL ou null"
  }},

  "recursos_cabiveis": {{
    "cabe_recurso": "Sim|Não|Consulte advogado",
    "tipo_recurso": "Apelação|Agravo|etc ou null",
    "prazo": "X dias ou null"
  }}
}}
```

### 🚨 **REGRAS CRÍTICAS PARA IDENTIFICAÇÃO DE TIPO:**

**ORDEM DE VERIFICAÇÃO (do mais específico ao mais genérico):**

1️⃣ **ACÓRDÃO** - Verifique PRIMEIRO os marcadores estruturais:
   - ✅ Tem "ACÓRDÃO" explícito no cabeçalho (primeiros 800 chars)?
   - ✅ Tem "RELATOR(A): Des./Desembargador(a)" no início?
   - ✅ Tem "VISTOS, RELATADOS E DISCUTIDOS"?
   - ✅ Tem "Acordam os Desembargadores" ou "Acordam os Membros"?
   - ✅ Tem estrutura colegial (CÂMARA/TURMA/COLEGIADO)?
   - ✅ Tem "TRIBUNAL DE JUSTIÇA" ou "TRIBUNAL REGIONAL"?
   - ⚠️ **IGNORE completamente** menções a "JULGO PROCEDENTE" - são citações de sentenças antigas!
   - **DECISÃO: SE 3+ marcadores acima = ACÓRDÃO com confianca_tipo: "ALTA"**

2️⃣ **SENTENÇA** - Verifique APENAS se NÃO for acórdão:
   - ✅ Tem "SENTENÇA" no cabeçalho (primeiros 500 chars)?
   - ✅ Tem "JULGO PROCEDENTE/IMPROCEDENTE/PARCIALMENTE PROCEDENTE" no dispositivo?
   - ✅ Assinado por UM juiz (não desembargador) no final?
   - ✅ NÃO tem estrutura colegial (câmara/turma)?
   - **DECISÃO: SE os 3 primeiros = SENTENÇA com confianca_tipo: "ALTA"**

3️⃣ **MANDADO**:
   - ✅ Tem "MANDADO DE CITAÇÃO/INTIMAÇÃO/PENHORA" no título?
   - ✅ Tem "INTIMO" ou "CITO" + audiência/prazo marcado?
   - ✅ Tem "OFICIAL DE JUSTIÇA" + "CUMPRA-SE"?
   - **DECISÃO: SE qualquer acima = MANDADO**

4️⃣ **OUTROS**:
   - Decisão interlocutória, Despacho, Intimação simples

### 🚨 **REGRAS ANTI-ALUCINAÇÃO:**
- **NUNCA invente valores** que não estão explícitos no texto
- Se não encontrar informação, use `null` ou `[]` ou `false`
- Cite trechos literais quando solicitado (trecho_justica_gratuita)
- Se em dúvida sobre o tipo, use confianca_tipo: "BAIXA"

---

## 📝 **PARTE 2: TEXTO SIMPLIFICADO (MARKDOWN)**

{instrucao_perspectiva}

Após o JSON, gere o texto simplificado seguindo EXATAMENTE esta estrutura:

{PROMPT_SIMPLIFICACAO_MELHORADO}

---

## 📄 **DOCUMENTO PARA ANÁLISE:**

{texto_analise}

---

## ✅ **FORMATO DE RESPOSTA:**

Responda EXATAMENTE neste formato:
```json
{{
  "tipo_documento": "...",
  ...
}}
```

---SEPARADOR---

[TEXTO SIMPLIFICADO EM MARKDOWN AQUI]
"""

    try:
        logging.info("🤖 Chamando Gemini para análise completa...")

        # Usar modelo mais potente
        model = genai.GenerativeModel(GEMINI_MODELS[0]["name"])

        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 3000
            }
        )

        resposta_completa = response.text.strip()

        # Separar JSON e texto simplificado
        if "---SEPARADOR---" in resposta_completa:
            partes = resposta_completa.split("---SEPARADOR---", 1)
            json_texto = partes[0].strip()
            texto_simplificado = partes[1].strip()
        else:
            # Fallback: tentar extrair JSON
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', resposta_completa, re.DOTALL)
            if json_match:
                json_texto = json_match.group(1)
                texto_simplificado = resposta_completa.replace(json_match.group(0), "").strip()
            else:
                logging.error("❌ Formato de resposta inválido - separador não encontrado")
                raise ValueError("Formato de resposta inválido")

        # Limpar e parsear JSON
        json_texto = json_texto.replace("```json", "").replace("```", "").strip()

        # Tentar parsear
        try:
            analise = json.loads(json_texto)
        except json.JSONDecodeError as e:
            logging.error(f"❌ Erro ao parsear JSON: {e}")
            logging.error(f"JSON recebido: {json_texto[:500]}")
            raise ValueError("Gemini retornou JSON inválido")

        # Adicionar texto simplificado
        analise["texto_simplificado"] = texto_simplificado

        logging.info(f"✅ Análise completa: tipo={analise.get('tipo_documento')}, confiança={analise.get('confianca_tipo')}")

        return analise

    except Exception as e:
        logging.error(f"❌ Erro na análise completa: {e}", exc_info=True)
        raise

# ============= FUNÇÕES AUXILIARES =============

def extrair_numero_processo_regex(texto):
    """Extração simples de número de processo com regex"""
    processo_patterns = [
        r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}',  # CNJ
        r'Processo\s+n[º°]?\s*([\d\.\-\/]+)'
    ]
    for pattern in processo_patterns:
        match = re.search(pattern, texto, re.IGNORECASE)
        if match:
            return match.group()
    return None

def gerar_perguntas_sugeridas(dados):
    """Gera perguntas baseadas nos dados extraídos"""
    perguntas = []

    valores = dados.get("valores", {})
    if valores.get("total_a_receber") or valores.get("danos_morais") or valores.get("danos_materiais"):
        perguntas.append("Quanto vou receber?")

    if dados.get("prazos"):
        perguntas.append("Quais são os prazos importantes?")

    if dados.get("audiencias"):
        perguntas.append("Quando é a audiência?")

    if dados.get("decisao"):
        perguntas.append("Eu ganhei ou perdi?")

    return perguntas[:4]

# ============= PROCESSAMENTO DE IMAGENS E PDFs =============

def processar_imagem_para_texto(image_bytes, formato='PNG'):
    """Extrai texto de imagem usando OCR"""
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
        raise ValueError("OCR não está disponível neste servidor")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        metadados["dimensoes"] = f"{img.width}x{img.height}"

        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')

        # Processamento básico
        if img.width > 3000 or img.height > 3000:
            ratio = min(3000/img.width, 3000/img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        img = img.convert('L')

        # OCR
        custom_config = r'--oem 3 --psm 6 -l por+eng' if 'por' in TESSERACT_LANGS else r'--oem 3 --psm 6 -l eng'
        texto = pytesseract.image_to_string(img, config=custom_config)

        if len(texto.strip()) < 50:
            metadados["qualidade_ocr"] = "baixa"
        elif len(texto.strip()) < 200:
            metadados["qualidade_ocr"] = "média"
        else:
            metadados["qualidade_ocr"] = "boa"

        logging.info(f"OCR concluído. Qualidade: {metadados['qualidade_ocr']}")

    except Exception as e:
        logging.error(f"Erro ao processar imagem: {e}")
        raise

    return texto, metadados

def extrair_texto_pdf(pdf_bytes):
    """Extrai texto de PDF"""
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
                raise ValueError("Nenhum texto extraído do PDF")

    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise

    return texto, metadados

# ============= GERAÇÃO DE PDF =============

def gerar_pdf_simplificado(texto, metadados=None, filename="documento_simplificado.pdf"):
    """Gera PDF com formatação"""
    output_path = os.path.join(TEMP_DIR, filename)

    try:
        c = canvas.Canvas(output_path, pagesize=letter)
        largura, altura = letter

        margem_esq = 50
        margem_dir = 50
        margem_top = 50
        margem_bottom = 50
        largura_texto = largura - margem_esq - margem_dir
        altura_linha = 14

        y = altura - margem_top

        # Cabeçalho
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_esq, y, "Documento em Linguagem Simples")
        y -= 30

        # Informações
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(margem_esq, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
        y -= 15

        if metadados:
            if metadados.get("modelo"):
                c.drawString(margem_esq, y, f"Processado com: {metadados['modelo']}")
                y -= 15
            if metadados.get("tipo_documento"):
                c.drawString(margem_esq, y, f"Tipo: {metadados['tipo_documento'].upper()}")
                y -= 15
            if metadados.get("confianca"):
                c.drawString(margem_esq, y, f"Confiança: {metadados['confianca']}")
                y -= 15

        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(margem_esq, y, largura - margem_dir, y)
        y -= 20

        # Processar texto
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0, 0, 0)

        linhas = texto.split('\n')

        for linha in linhas:
            if not linha.strip():
                y -= altura_linha
                continue

            # Detectar títulos
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

            # Quebra de linha
            palavras = linha.split()
            linha_atual = []

            for palavra in palavras:
                linha_teste = ' '.join(linha_atual + [palavra])
                if c.stringWidth(linha_teste, "Helvetica", 11) <= largura_texto:
                    linha_atual.append(palavra)
                else:
                    if linha_atual:
                        if y < margem_bottom + altura_linha:
                            c.showPage()
                            y = altura - margem_top
                        c.drawString(margem_esq, y, ' '.join(linha_atual))
                        y -= altura_linha
                        linha_atual = [palavra]

            if linha_atual:
                if y < margem_bottom + altura_linha:
                    c.showPage()
                    y = altura - margem_top
                c.drawString(margem_esq, y, ' '.join(linha_atual))
                y -= altura_linha

        # Rodapé
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(margem_esq, 30, "Desenvolvido pela INOVASSOL - TJTO")

        c.save()
        registrar_arquivo_temporario(output_path, session_id=session.get('session_id'))
        return output_path

    except Exception as e:
        logging.error(f"Erro ao gerar PDF: {e}")
        raise

# ============= ROTAS =============

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/processar", methods=["POST"])
@rate_limit
def processar():
    """Processa upload com análise 100% Gemini"""
    try:
        session.permanent = True
        session.modified = True

        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400

        file = request.files['file']
        perspectiva = request.form.get('perspectiva', 'nao_informado')

        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado"}), 400

        if not allowed_file(file.filename):
            return jsonify({"erro": "Formato inválido"}), 400

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > MAX_FILE_SIZE:
            return jsonify({"erro": "Arquivo muito grande"}), 400

        file_bytes = file.read()
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        file_hash = hashlib.md5(file_bytes).hexdigest()

        logging.info(f"📄 Processando: {secure_filename(file.filename)} ({size/1024:.1f}KB)")

        # Extrair texto
        if file_extension == 'pdf':
            texto_original, metadados_arquivo = extrair_texto_pdf(file_bytes)
        elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
            texto_original, metadados_arquivo = processar_imagem_para_texto(file_bytes, file_extension.upper())
        else:
            return jsonify({"erro": "Tipo não suportado"}), 400

        if len(texto_original) < 10:
            return jsonify({"erro": "Texto insuficiente"}), 400

        # 🎯 ANÁLISE COMPLETA COM GEMINI
        logging.info("🤖 Iniciando análise completa com Gemini...")
        analise_completa = analisar_documento_completo_gemini(texto_original, perspectiva)

        tipo_doc = analise_completa["tipo_documento"]
        texto_simplificado = analise_completa["texto_simplificado"]

        # Preparar dados estruturados
        dados_estruturados = {
            "numero_processo": extrair_numero_processo_regex(texto_original),
            "tipo_documento": tipo_doc,
            "partes": analise_completa.get("partes", {}),
            "autoridade": f"{analise_completa.get('autoridade', {}).get('cargo', '')}: {analise_completa.get('autoridade', {}).get('nome', '')}".strip(),
            "valores": analise_completa.get("valores_principais", {}),
            "prazos": [p.get("prazo", "") for p in analise_completa.get("prazos", [])],
            "decisao": analise_completa.get("decisao_resumida"),
            "audiencias": [analise_completa.get("audiencia")] if analise_completa.get("audiencia", {}).get("tem_audiencia") else [],
            "links_audiencia": [analise_completa.get("audiencia", {}).get("link")] if analise_completa.get("audiencia", {}).get("link") else [],
        }

        info_doc = {
            "urgencia": analise_completa.get("urgencia", "MÉDIA"),
            "acao_necessaria": analise_completa.get("acao_necessaria", "Verificar documento")
        }

        recursos_info = analise_completa.get("recursos_cabiveis", {
            "cabe_recurso": "Consulte advogado",
            "prazo": None
        })

        # Contexto chat
        contexto_chat = {
            "dados_extraidos": dados_estruturados,
            "perspectiva": perspectiva,
            "perguntas_sugeridas": gerar_perguntas_sugeridas(dados_estruturados)
        }

        # Salvar texto original
        texto_original_path = os.path.join(TEMP_DIR, f"texto_{file_hash[:8]}.txt")
        with open(texto_original_path, 'w', encoding='utf-8') as f:
            f.write(texto_original)
        registrar_arquivo_temporario(texto_original_path, session_id=session.get('session_id'))

        # Gerar PDF
        metadados_pdf = {
            "modelo": GEMINI_MODELS[0]["name"],
            "tipo": metadados_arquivo.get("tipo"),
            "tipo_documento": tipo_doc,
            "urgencia": info_doc["urgencia"],
            "dados": dados_estruturados,
            "recursos": recursos_info,
            "confianca": analise_completa.get("confianca_tipo", "MÉDIA")
        }

        pdf_filename = f"simplificado_{file_hash[:8]}.pdf"
        pdf_path = gerar_pdf_simplificado(texto_simplificado, metadados_pdf, pdf_filename)

        # Salvar na sessão
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        session['texto_original_path'] = texto_original_path
        session['contexto_chat'] = contexto_chat
        session.modified = True

        # Estatísticas
        try:
            database.incrementar_documento(tipo_doc)
        except Exception as e:
            logging.error(f"Erro stats: {e}")

        logging.info(f"✅ Processamento completo: {tipo_doc} (confiança: {analise_completa.get('confianca_tipo')})")

        return jsonify({
            "texto": texto_simplificado,
            "tipo_documento": tipo_doc,
            "confianca_tipo": analise_completa.get("confianca_tipo"),
            "razao_tipo": analise_completa.get("razao_tipo"),
            "urgencia": info_doc["urgencia"],
            "acao_necessaria": info_doc["acao_necessaria"],
            "dados_extraidos": dados_estruturados,
            "recursos_cabiveis": recursos_info,
            "perguntas_sugeridas": contexto_chat["perguntas_sugeridas"],
            "tem_justica_gratuita": analise_completa.get("tem_justica_gratuita"),
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "modelo_usado": GEMINI_MODELS[0]["name"],
            "pdf_download_url": f"/download_pdf?path={os.path.basename(pdf_path)}&filename={pdf_filename}"
        })

    except Exception as e:
        logging.error(f"❌ Erro: {e}", exc_info=True)
        return jsonify({"erro": "Erro ao processar arquivo"}), 500

@app.route("/chat", methods=["POST"])
@rate_limit
def chat_contextual():
    """Chat baseado no documento"""
    try:
        data = request.get_json()
        pergunta = data.get("pergunta", "").strip()

        if not pergunta:
            return jsonify({"resposta": "Faça uma pergunta sobre o documento", "tipo": "erro"}), 400

        contexto = session.get('contexto_chat')
        if not contexto:
            return jsonify({"resposta": "Envie um documento primeiro", "tipo": "erro"}), 400

        # Obter documento
        texto_original_path = session.get('texto_original_path')
        if texto_original_path and os.path.exists(texto_original_path):
            with open(texto_original_path, 'r', encoding='utf-8') as f:
                documento = f.read()
        else:
            documento = ""

        dados = contexto.get("dados_extraidos", {})

        # Prompt simplificado para chat
        prompt = f"""Você é um assistente que responde perguntas sobre documentos jurídicos.

DOCUMENTO (resumo):
- Tipo: {dados.get('tipo_documento')}
- Partes: {dados.get('partes')}
- Decisão: {dados.get('decisao')}
- Valores: {dados.get('valores')}
- Prazos: {dados.get('prazos')}

PERGUNTA: {pergunta}

Responda em NO MÁXIMO 2-3 frases curtas e simples. Se não souber, diga "Não encontrei essa informação".
"""

        try:
            model = genai.GenerativeModel(GEMINI_MODELS[1]["name"])
            response = model.generate_content(prompt)
            resposta_texto = response.text.strip()

            return jsonify({
                "resposta": resposta_texto,
                "tipo": "resposta"
            })
        except Exception as e:
            logging.error(f"Erro chat: {e}")
            return jsonify({"resposta": "Erro ao processar pergunta", "tipo": "erro"}), 500

    except Exception as e:
        logging.error(f"Erro: {e}")
        return jsonify({"resposta": "Erro", "tipo": "erro"}), 500

@app.route("/download_pdf")
def download_pdf():
    """Download do PDF"""
    pdf_basename = request.args.get('path')
    pdf_filename = request.args.get('filename', 'documento_simplificado.pdf')

    if pdf_basename:
        pdf_path = os.path.join(TEMP_DIR, os.path.basename(pdf_basename))
    else:
        pdf_path = session.get('pdf_path')
        pdf_filename = session.get('pdf_filename', 'documento_simplificado.pdf')

    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"erro": "PDF não encontrado"}), 404

    try:
        return send_file(pdf_path, as_attachment=True, download_name=pdf_filename, mimetype='application/pdf')
    except Exception as e:
        logging.error(f"Erro download: {e}")
        return jsonify({"erro": "Erro ao baixar"}), 500

@app.route("/api/stats")
def get_stats():
    """Estatísticas LGPD compliant"""
    try:
        stats = database.get_estatisticas()
        return jsonify(stats)
    except Exception as e:
        logging.error(f"Erro stats: {e}")
        return jsonify({"erro": "Erro ao carregar estatísticas"}), 500

@app.route("/health")
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(GEMINI_API_KEY),
        "models_available": len(GEMINI_MODELS),
        "tesseract_available": TESSERACT_AVAILABLE
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

# Limpeza periódica
def cleanup_temp_files():
    while True:
        try:
            time.sleep(3600)
            now = time.time()

            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('simplificado_') or filename.startswith('texto_'):
                    filepath = os.path.join(TEMP_DIR, filename)
                    try:
                        if os.stat(filepath).st_mtime < now - 3600:
                            os.remove(filepath)
                    except Exception as e:
                        logging.warning(f"Erro ao remover {filename}: {e}")

            to_remove = [k for k, v in results_cache.items() if time.time() - v["timestamp"] > CACHE_EXPIRATION]
            for key in to_remove:
                del results_cache[key]

        except Exception as e:
            logging.error(f"Erro na limpeza: {e}")

cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
