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

# Modelos Gemini com fallback expandido (5 modelos para máxima disponibilidade)
GEMINI_MODELS = [
    {
        "name": "gemini-2.5-flash-lite",
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 1,
        "description": "Modelo mais leve e rápido (menor chance de quota excedida)"
    },
    {
        "name": "gemini-2.5-flash",
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 2,
        "description": "Modelo flash versão 2.5"
    },
    {
        "name": "gemini-1.5-flash",
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 3,
        "description": "Modelo flash estável versão 1.5"
    },
    {
        "name": "gemini-2.0-flash-exp",
        "max_tokens": 8192,
        "max_input_tokens": 1000000,
        "priority": 4,
        "description": "Modelo experimental 2.0"
    },
    {
        "name": "gemini-1.5-pro",
        "max_tokens": 8192,
        "max_input_tokens": 2000000,
        "priority": 5,
        "description": "Modelo Pro (mais robusto, fallback final)"
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

# Log dos modelos configurados
logging.info(f"🤖 Sistema multi-modelo configurado com {len(GEMINI_MODELS)} modelos:")
for idx, model in enumerate(sorted(GEMINI_MODELS, key=lambda x: x["priority"]), 1):
    logging.info(f"  {idx}. {model['name']} (priority {model['priority']}) - {model.get('description', 'N/A')}")

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

PROMPT_SIMPLIFICACAO_MELHORADO = """**ESTRUTURA DA EXPLICAÇÃO:**

📊 **RESULTADO EM UMA FRASE**

🚨 REGRAS ESPECIAIS POR TIPO DE DOCUMENTO:

**MANDADOS/CITAÇÕES/INTIMAÇÕES:**
- Use "📋 ORDEM JUDICIAL PARA [ação]" (ex: "ORDEM JUDICIAL PARA COMPARECER À AUDIÊNCIA")
- NÃO mencione vitória ou derrota
- Mencione valores APENAS se explícitos no documento original

**PROCESSOS DE ATO INFRACIONAL (ECA - menores):**
- Use "⚖️ DECISÃO SOBRE ATO INFRACIONAL"
- NÃO use vitória/derrota (não se aplica)
- Explique a medida aplicada em linguagem simples
- Use o NOME do adolescente, não "você"
- Exemplo: "O juiz aplicou a medida de semiliberdade a [NOME] por no mínimo 6 meses"

**OUTROS DOCUMENTOS (sentenças, acórdãos, decisões cíveis/trabalhistas):**
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

**Valores mencionados:**

✅ O QUE VOCÊ VAI GANHAR:
- [Liste APENAS valores que estão EXPLÍCITOS no documento. Se não houver valores a receber, omita esta seção]

❌ O QUE VOCÊ NÃO VAI GANHAR:
- [Liste valores negados. Se não houver, omita esta seção]

**Sobre custas e honorários:**

REGRAS PARA JUSTIÇA GRATUITA (MUITO IMPORTANTE - LEIA COM ATENÇÃO):

1. **Se tem justiça gratuita E menciona "suspendo a exigibilidade", "art. 98, §3º, CPC" ou similar:**
   → Escreva APENAS: "Você NÃO vai pagar custas e honorários porque tem justiça gratuita."
   → NÃO mencione valores de condenação
   → NÃO use "no entanto", "mas", "porém"
   → A suspensão da exigibilidade significa que o autor está ISENTO

2. **Se tem justiça gratuita E não há menção de condenação ao pagamento:**
   → "Você NÃO vai pagar custas e honorários porque tem justiça gratuita."

3. **Se tem justiça gratuita MAS foi expressamente condenado SEM suspensão da exigibilidade (raro):**
   → "Você tem justiça gratuita, MAS neste caso o juiz decidiu que você deve pagar [valores específicos]."

4. **Se NÃO tem justiça gratuita:**
   → Liste claramente os valores a pagar

IMPORTANTE:
- NUNCA use a palavra "encargos" - use sempre "custas e honorários"
- Se for MANDADO ou CITAÇÃO, só mencione valores se estiverem explícitos no documento original
- Quando há suspensão de exigibilidade + justiça gratuita = pessoa NÃO paga (é como se fosse isentada)

**Próximos passos:**
[O que você deve fazer agora? Seja ESPECÍFICO e PRÁTICO]

**REGRA IMPORTANTE SOBRE PRAZOS:**
- Se houver prazos, liste cada um especificando PARA QUEM e PARA QUÊ
- Exemplo CORRETO: "A Secretaria de Saúde tem 15 dias para realizar a avaliação psicológica"
- Exemplo CORRETO: "O adolescente tem 24 horas para se apresentar na Unidade de Semiliberdade"
- Exemplo ERRADO: "15 dias" (sem dizer para quem e para quê)

---

📚 **PALAVRAS QUE PODEM APARECER NO DOCUMENTO**
[Liste APENAS 5-7 termos mais importantes]

- **[Termo]**: Significa [explicação em 5-10 palavras]

**Não coloque mais de 7 termos!**

---

*💡 Dica: Este documento não substitui a orientação jurídica. Se precisar, busque ajuda com um advogado ou uma advogada ou com a Defensoria Pública.*

---

**REGRAS DE ESCRITA:**
1. Máximo 15 palavras por frase
2. NUNCA use: "exequente", "executado", "lide", "mérito"
3. SEMPRE use conforme a perspectiva escolhida
4. Seja empático: "Você ganhou!", "Infelizmente você perdeu"
5. Mini dicionário: NO MÁXIMO 7 termos

**IMPORTANTE - NÃO INCLUIR NO TEXTO SIMPLIFICADO:**
❌ NÃO crie seções sobre "Recursos" ou "Cabe recurso" no texto simplificado
❌ NÃO mencione prazos de recurso no texto simplificado
❌ NÃO inclua seções sobre "Audiências Marcadas" se não houver data/hora
❌ NÃO adicione informações como "geralmente é de X dias" ou "normalmente"
✅ Essas informações devem estar APENAS no JSON, não no texto simplificado
✅ O frontend exibirá as informações de recursos e audiências automaticamente a partir do JSON
"""

# ============= ANÁLISE COMPLETA COM GEMINI =============

def analisar_documento_completo_gemini(texto, perspectiva="nao_informado"):
    """
    ANÁLISE COMPLETA DO DOCUMENTO EM 1 ÚNICA CHAMADA GEMINI
    Retorna dict com análise técnica + texto simplificado
    
    🔥 VERSÃO CORRIGIDA - Perspectiva aplicada corretamente
    """

    # Truncar texto se necessário
    if len(texto) > 15000:
        texto_analise = texto[:7500] + "\n\n[... TEXTO TRUNCADO ...]\n\n" + texto[-7500:]
    else:
        texto_analise = texto

    # 🔥 DETECTAR PROCESSO DE ATO INFRACIONAL (tem prioridade sobre perspectiva)
    is_ato_infracional = any([
        "ato infracional" in texto.lower(),
        "adolescente representado" in texto.lower(),
        "medida socioeducativa" in texto.lower(),
        "estatuto da criança" in texto.lower(),
        "eca" in texto.lower() and ("adolescente" in texto.lower() or "menor" in texto.lower())
    ])

    # 🔥 MAPEAR PERSPECTIVA DE FORMA EXPLÍCITA E FORTE
    if is_ato_infracional:
        instrucao_perspectiva = '''
╔══════════════════════════════════════════════════════════════════╗
║  🚨 PROCESSO DE ATO INFRACIONAL - USE O NOME DO ADOLESCENTE     ║
╚══════════════════════════════════════════════════════════════════╝

**INSTRUÇÕES ABSOLUTAS:**

1️⃣ Este é um processo de ATO INFRACIONAL (ECA - Estatuto da Criança e do Adolescente)
2️⃣ Use o NOME COMPLETO do adolescente, NÃO use "você"
3️⃣ NÃO use conceitos de vitória/derrota
4️⃣ Foque na MEDIDA SOCIOEDUCATIVA aplicada

**EXEMPLOS OBRIGATÓRIOS:**

❌ ERRADO: "Você foi condenado à semiliberdade..."
✅ CORRETO: "O juiz aplicou a medida de semiliberdade a [NOME DO ADOLESCENTE]..."

❌ ERRADO: "VITÓRIA PARCIAL - Você ganhou parte do que pediu"
✅ CORRETO: "DECISÃO SOBRE ATO INFRACIONAL - O juiz aplicou medida de semiliberdade"

❌ ERRADO: "Você entrou com um processo..."
✅ CORRETO: "O Ministério Público iniciou um processo contra [NOME DO ADOLESCENTE]..."

**ATENÇÃO:**
- Identifique o nome do adolescente no documento (após "adolescente representado" ou similar)
- Use linguagem respeitosa e educativa
- Explique claramente a medida aplicada e o que o adolescente deve fazer
- NÃO criminalize: use "ato infracional", não "crime"
'''
    elif perspectiva == "autor":
        instrucao_perspectiva = '''
╔══════════════════════════════════════════════════════════════════╗
║  🚨 REGRA CRÍTICA DE PERSPECTIVA - VOCÊ É O AUTOR/REQUERENTE     ║
╚══════════════════════════════════════════════════════════════════╝

**INSTRUÇÕES ABSOLUTAS:**

1️⃣ Use **"VOCÊ"** para se referir ao **AUTOR/REQUERENTE** do processo
2️⃣ Use **"a outra parte"**, **"o réu"** ou **"o requerido"** para o ADVERSÁRIO
3️⃣ NUNCA troque essas referências!

**EXEMPLOS OBRIGATÓRIOS:**

❌ ERRADO: "O autor João Silva foi condenado..."
✅ CORRETO: "VOCÊ foi condenado..."

❌ ERRADO: "O requerente deve pagar..."
✅ CORRETO: "VOCÊ deve pagar..."

❌ ERRADO: "João Silva ganhou o processo..."
✅ CORRETO: "VOCÊ ganhou o processo..."

❌ ERRADO: "O Estado de Goiás deve pagar ao autor..."
✅ CORRETO: "O Estado de Goiás deve pagar a VOCÊ..."

**REGRA DE OURO:** 
Sempre que o documento mencionar "AUTOR", "REQUERENTE", "APELANTE" (se for quem apelou primeiro), substitua por "VOCÊ".
Sempre que mencionar "RÉU", "REQUERIDO", "APELADO" (se for o adversário), substitua por "a outra parte" ou mantenha o nome.

**ATENÇÃO REDOBRADA EM:**
- Seção "O QUE ESTÁ ACONTECENDO" → Diga "Você entrou com um processo pedindo..."
- Seção "A DECISÃO DO JUIZ" → Diga "O juiz decidiu que VOCÊ..."
- Seção "VALORES E O QUE VOCÊ PRECISA FAZER" → Diga "Você vai receber..." ou "Você deve pagar..."
'''
        
    elif perspectiva == "reu":
        instrucao_perspectiva = '''
╔══════════════════════════════════════════════════════════════════╗
║  🚨 REGRA CRÍTICA DE PERSPECTIVA - VOCÊ É O RÉU/REQUERIDO        ║
╚══════════════════════════════════════════════════════════════════╝

**INSTRUÇÕES ABSOLUTAS:**

1️⃣ Use **"VOCÊ"** para se referir ao **RÉU/REQUERIDO** do processo
2️⃣ Use **"a outra parte"**, **"o autor"** ou **"o requerente"** para o ADVERSÁRIO
3️⃣ NUNCA troque essas referências!

**EXEMPLOS OBRIGATÓRIOS:**

❌ ERRADO: "O réu Estado de Goiás foi condenado..."
✅ CORRETO: "VOCÊ foi condenado..."

❌ ERRADO: "O requerido deve pagar..."
✅ CORRETO: "VOCÊ deve pagar..."

❌ ERRADO: "Maria Santos foi absolvida..."
✅ CORRETO: "VOCÊ foi absolvida..."

❌ ERRADO: "O autor entrou com processo contra o Estado..."
✅ CORRETO: "A outra parte entrou com processo contra VOCÊ..."

**REGRA DE OURO:** 
Sempre que o documento mencionar "RÉU", "REQUERIDO", "APELADO" (se for você), substitua por "VOCÊ".
Sempre que mencionar "AUTOR", "REQUERENTE", "APELANTE" (se for o adversário), substitua por "a outra parte" ou mantenha o nome.

**ATENÇÃO REDOBRADA EM:**
- Seção "O QUE ESTÁ ACONTECENDO" → Diga "A outra parte entrou com um processo contra você..."
- Seção "A DECISÃO DO JUIZ" → Diga "O juiz decidiu que VOCÊ..."
- Seção "VALORES E O QUE VOCÊ PRECISA FAZER" → Diga "Você deve pagar..." ou "Você não precisa pagar..."
'''
        
    else:
        instrucao_perspectiva = '''
╔══════════════════════════════════════════════════════════════════╗
║  ℹ️ PERSPECTIVA NEUTRA - POSIÇÃO NÃO INFORMADA                   ║
╚══════════════════════════════════════════════════════════════════╝

**INSTRUÇÕES:**

1️⃣ Use os **nomes reais** das partes (não use "você")
2️⃣ Mantenha linguagem neutra e imparcial
3️⃣ Seja claro sobre quem é quem

**EXEMPLOS:**

✅ CORRETO: "João Silva foi condenado a pagar indenização"
✅ CORRETO: "O Estado de Goiás deve pagar R$ 30.000,00 a Andresley Carlos"
✅ CORRETO: "Maria Santos ganhou o processo contra a empresa"

**NÃO use "você" em nenhuma circunstância quando a perspectiva for "nao_informado".**
'''

    # 🔥 LOG PARA DEBUG
    logging.info(f"🎯 Perspectiva aplicada no prompt Gemini: {perspectiva}")
    logging.info(f"📝 Instrução gerada: {instrucao_perspectiva[:150]}...")

    prompt = f"""Você é um especialista em análise de documentos jurídicos brasileiros com foco em linguagem acessível.

🎯 **TAREFA:** Analisar este documento COMPLETAMENTE e gerar:
1. Identificação técnica (tipo, partes, autoridade) em JSON
2. Texto simplificado em linguagem acessível em Markdown

═══════════════════════════════════════════════════════════════════

{instrucao_perspectiva}

═══════════════════════════════════════════════════════════════════

**INSTRUÇÕES DE PRECISÃO:**

Use APENAS informações que estão explicitamente escritas no documento.

❌ Não invente: valores, datas, prazos, nomes ou decisões que não estão mencionados
✅ Se algo não está no documento, escreva: "O documento não menciona [isso]"
✅ Quando em dúvida, omita a informação

═══════════════════════════════════════════════════════════════════

**SIMPLIFICAÇÃO OBRIGATÓRIA DE TERMOS TÉCNICOS:**
- "PARCIALMENTE PROCEDENTE" → "Você ganhou PARTE do que pediu" (ajuste conforme perspectiva)
- "PROCEDENTE" → "Você ganhou" (ajuste conforme perspectiva)
- "IMPROCEDENTE" → "Você perdeu" ou "Seu pedido foi negado" (ajuste conforme perspectiva)
- "Habeas Corpus" → "um pedido urgente para garantir sua liberdade"
- "Cerceamento de defesa" → "você foi impedido de se defender corretamente"
- "Deferido" → "aprovado" ou "aceito"
- "Indeferido" → "negado" ou "recusado"
- "Trânsito em julgado" → "quando a decisão se tornar definitiva (não couber mais recurso)"
- "Aguardar trânsito em julgado" → "Aguardar que a decisão se torne definitiva (quando não couber mais recurso)"
- "Cumprimento de sentença" ou "Cumprimento da decisão" → "quando você receber o que foi decidido" ou "quando a decisão for cumprida"
- "Exigibilidade suspensa" → "cobrança suspensa" ou "você não precisa pagar agora"
- "Suspendo a exigibilidade" → "a cobrança fica suspensa" ou "você não precisa pagar agora"

═══════════════════════════════════════════════════════════════════

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
    {{"tipo": "recurso", "prazo": "15 dias", "destinatario": "para quem é o prazo", "finalidade": "para que serve"}},
    {{"tipo": "contestacao", "prazo": "30 dias", "destinatario": "para quem é o prazo", "finalidade": "para que serve"}}
  ],

  "audiencia": {{
    "tem_audiencia": true|false,
    "data": "DD/MM/AAAA ou null",
    "hora": "HH:MM ou null",
    "link": "URL ou null"
  }},

  "recursos_cabiveis": {{
    "cabe_recurso": "Sim|Não|Consulte advogado(a) ou defensoria pública",
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

**Instruções para preenchimento:**
- Use apenas informações explícitas do texto
- Se não encontrar informação, use `null` ou `[]` ou `false`
- Cite trechos literais quando solicitado (trecho_justica_gratuita)
- Se em dúvida sobre o tipo, use confianca_tipo: "BAIXA"

**REGRAS CRÍTICAS PARA AUDIÊNCIAS:**
- Se o documento NÃO menciona audiência → use "tem_audiencia": false, "data": null, "hora": null, "link": null
- Se menciona audiência mas sem data/hora específicas → use "tem_audiencia": true, mas deixe "data" e "hora" como null
- NUNCA invente datas ou horários de audiências que não estão no documento

**REGRAS CRÍTICAS PARA PRAZOS:**
- Use APENAS prazos explicitamente mencionados no documento
- Para CADA prazo, especifique:
  * "tipo": tipo do prazo (recurso, contestação, cumprimento, apresentação, etc)
  * "prazo": quanto tempo (ex: "15 dias", "10 dias úteis", "24 horas")
  * "destinatario": PARA QUEM é o prazo (ex: "para o Ministério Público", "para o adolescente se apresentar", "para a Secretaria de Saúde")
  * "finalidade": PARA QUÊ serve o prazo (ex: "para apresentar recurso", "para se apresentar na Unidade", "para realizar avaliação psicológica")
- Se o documento não menciona prazo específico → deixe a lista "prazos" vazia: []
- NUNCA adicione prazos "gerais" como "geralmente é de 15 dias" - se não está no documento, não coloque
- Exemplo correto: {{"tipo": "apresentação", "prazo": "24 horas", "destinatario": "Adolescente Matheus", "finalidade": "Para se apresentar na Unidade de Semiliberdade"}}

**REGRAS CRÍTICAS PARA RECURSOS:**
- "cabe_recurso": Escolha APENAS UMA opção clara:
  * "Sim" - se o documento menciona explicitamente que cabe recurso
  * "Não" - se o documento menciona explicitamente que não cabe recurso ou que é decisão irrecorrível
  * "Consulte advogado(a) ou defensoria pública" - se o documento não menciona se cabe ou não cabe recurso
- "prazo": Use APENAS se o documento mencionar prazo específico para recurso, senão use null
- NUNCA escreva "Sim|Não|Consulte..." com todas as opções juntas - escolha apenas UMA

═══════════════════════════════════════════════════════════════════

## 📝 **PARTE 2: TEXTO SIMPLIFICADO (MARKDOWN)**

🚨🚨🚨 **LEMBRE-SE SEMPRE DA PERSPECTIVA ESCOLHIDA:** 🚨🚨🚨

{instrucao_perspectiva}

**TOM DE VOZ E EMPATIA:**
- Fale conforme a perspectiva (use "você" corretamente ou nomes reais)
- Seja MUITO empático
- Use frases como: "Entendo que esta situação pode ser difícil..."
- NUNCA use termos técnicos sem explicar
- Use linguagem de conversa calorosa, não formal/fria
- Seja direto mas gentil

Após o JSON, gere o texto simplificado seguindo EXATAMENTE esta estrutura:

{PROMPT_SIMPLIFICACAO_MELHORADO}

═══════════════════════════════════════════════════════════════════

## 📄 **DOCUMENTO PARA ANÁLISE:**

{texto_analise}

═══════════════════════════════════════════════════════════════════

## ✅ **FORMATO DE RESPOSTA OBRIGATÓRIO:**

Responda EXATAMENTE neste formato:
```json
{{
  "tipo_documento": "...",
  ...
}}
```

---SEPARADOR---

[TEXTO SIMPLIFICADO EM MARKDOWN AQUI - RESPEITANDO A PERSPECTIVA ESCOLHIDA]
"""

    # Tentar cada modelo em ordem de prioridade
    modelos_ordenados = sorted(GEMINI_MODELS, key=lambda x: x["priority"])
    total_modelos = len(modelos_ordenados)
    ultimo_erro = None
    erros_por_modelo = {}

    logging.info(f"🔄 Sistema multi-modelo: {total_modelos} modelos disponíveis para fallback")

    for idx, modelo_config in enumerate(modelos_ordenados, 1):
        modelo_nome = modelo_config["name"]

        try:
            logging.info(f"🤖 [{idx}/{total_modelos}] Tentando modelo: {modelo_nome} - {modelo_config.get('description', '')}")

            # Criar modelo
            model = genai.GenerativeModel(modelo_nome)

            # Chamada com timeout implícito
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 3000
                }
            )

            resposta_completa = response.text.strip()
            logging.info(f"✅ Resposta recebida do {modelo_nome} ({len(resposta_completa)} chars)")

            # Separar JSON e texto simplificado
            if "---SEPARADOR---" in resposta_completa:
                partes = resposta_completa.split("---SEPARADOR---", 1)
                json_texto = partes[0].strip()
                texto_simplificado = partes[1].strip()
                logging.info("✅ Separador encontrado na resposta")
            else:
                logging.warning("⚠️ Separador não encontrado, tentando regex fallback")
                # Fallback: tentar extrair JSON
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', resposta_completa, re.DOTALL)
                if json_match:
                    json_texto = json_match.group(1)
                    texto_simplificado = resposta_completa.replace(json_match.group(0), "").strip()
                    logging.info("✅ JSON extraído via regex")
                else:
                    logging.error("❌ Formato de resposta inválido - separador não encontrado")
                    logging.error(f"Primeiros 500 chars da resposta: {resposta_completa[:500]}")
                    raise ValueError("Formato de resposta inválido")

            # Limpar e parsear JSON
            json_texto = json_texto.replace("```json", "").replace("```", "").strip()

            # Tentar parsear
            try:
                analise = json.loads(json_texto)
                logging.info(f"✅ JSON parseado com sucesso")
            except json.JSONDecodeError as e:
                logging.error(f"❌ Erro ao parsear JSON: {e}")
                logging.error(f"JSON recebido (primeiros 500 chars): {json_texto[:500]}")
                raise ValueError(f"Gemini retornou JSON inválido: {e}")

            # Adicionar texto simplificado
            analise["texto_simplificado"] = texto_simplificado
            analise["modelo_usado"] = modelo_nome
            analise["perspectiva_aplicada"] = perspectiva  # 🔥 NOVO - registrar perspectiva

            # Atualizar estatísticas de sucesso
            model_usage_stats[modelo_nome]["attempts"] += 1
            model_usage_stats[modelo_nome]["successes"] += 1

            logging.info(f"✅ Análise completa com {modelo_nome}: tipo={analise.get('tipo_documento')}, confiança={analise.get('confianca_tipo')}, perspectiva={perspectiva}")

            return analise

        except Exception as e:
            ultimo_erro = e
            erro_msg = str(e)
            erros_por_modelo[modelo_nome] = erro_msg[:200]  # Salvar primeiros 200 chars do erro

            # Atualizar estatísticas de falha
            if modelo_nome in model_usage_stats:
                model_usage_stats[modelo_nome]["attempts"] += 1
                model_usage_stats[modelo_nome]["failures"] += 1

            # Identificar tipo de erro
            if "quota" in erro_msg.lower() or "429" in erro_msg or "resource" in erro_msg.lower():
                logging.error(f"❌ [{idx}/{total_modelos}] Quota excedida em {modelo_nome}")
                if idx < total_modelos:
                    logging.warning(f"⚠️ Tentando próximo modelo ({idx+1}/{total_modelos})...")
            else:
                logging.error(f"❌ [{idx}/{total_modelos}] Erro em {modelo_nome}: {erro_msg[:100]}")
                if idx < total_modelos:
                    logging.warning(f"⚠️ Tentando próximo modelo ({idx+1}/{total_modelos})...")

            continue

    # Se chegou aqui, todos os modelos falharam
    logging.error(f"❌ TODOS OS {total_modelos} MODELOS FALHARAM!")
    logging.error(f"📊 Resumo de erros por modelo:")
    for modelo, erro in erros_por_modelo.items():
        logging.error(f"  - {modelo}: {erro}")
    logging.error(f"📊 Estatísticas dos modelos: {model_usage_stats}")

    # Mensagem de erro amigável
    if all("quota" in err.lower() or "429" in err for err in erros_por_modelo.values()):
        raise Exception(
            "Todos os modelos Gemini atingiram o limite de quota. "
            "Aguarde alguns minutos e tente novamente, ou verifique sua chave API."
        )
    else:
        raise Exception(f"Erro ao processar documento com IA. Último erro: {ultimo_erro}")

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
    """Processa upload com análise 100% Gemini - VERSÃO CORRIGIDA"""
    try:
        session.permanent = True
        session.modified = True

        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400

        file = request.files['file']
        perspectiva = request.form.get('perspectiva', 'nao_informado')

        # 🔥 LOG PARA DEBUG DA PERSPECTIVA
        logging.info(f"""
╔════════════════════════════════════════════════╗
║  📍 PERSPECTIVA CAPTURADA DO FORMULÁRIO       ║
║  Valor: {perspectiva:^35} ║
╚════════════════════════════════════════════════╝
        """)

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
        try:
            if file_extension == 'pdf':
                logging.info("📄 Extraindo texto de PDF...")
                texto_original, metadados_arquivo = extrair_texto_pdf(file_bytes)
                logging.info(f"✅ Texto extraído do PDF: {len(texto_original)} caracteres")
            elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
                logging.info("🖼️ Extraindo texto de imagem com OCR...")
                texto_original, metadados_arquivo = processar_imagem_para_texto(file_bytes, file_extension.upper())
                logging.info(f"✅ Texto extraído da imagem: {len(texto_original)} caracteres")
            else:
                return jsonify({"erro": "Tipo não suportado"}), 400
        except Exception as e:
            logging.error(f"❌ Erro ao extrair texto do arquivo: {e}", exc_info=True)
            return jsonify({"erro": f"Erro ao extrair texto: {str(e)}"}), 500

        if len(texto_original) < 10:
            logging.warning(f"⚠️ Texto muito curto: {len(texto_original)} caracteres")
            return jsonify({"erro": "Texto insuficiente no documento"}), 400

        # 🎯 ANÁLISE COMPLETA COM GEMINI (COM PERSPECTIVA CORRIGIDA)
        logging.info(f"🤖 Iniciando análise completa com Gemini (perspectiva: {perspectiva})...")
        logging.info(f"📝 Texto extraído: {len(texto_original)} caracteres")

        try:
            analise_completa = analisar_documento_completo_gemini(texto_original, perspectiva)
        except Exception as e:
            logging.error(f"❌ ERRO CRÍTICO na análise Gemini: {e}", exc_info=True)
            return jsonify({"erro": f"Erro ao analisar documento: {str(e)}"}), 500

        tipo_doc = analise_completa.get("tipo_documento", "desconhecido")
        texto_simplificado = analise_completa.get("texto_simplificado", "")
        modelo_usado = analise_completa.get("modelo_usado", GEMINI_MODELS[0]["name"])
        perspectiva_aplicada = analise_completa.get("perspectiva_aplicada", perspectiva)

        logging.info(f"✅ Análise concluída: tipo={tipo_doc}, modelo={modelo_usado}, perspectiva={perspectiva_aplicada}")

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
            "cabe_recurso": "Consulte advogado(a) ou defensoria pública",
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
            "modelo": modelo_usado,
            "tipo": metadados_arquivo.get("tipo"),
            "tipo_documento": tipo_doc,
            "urgencia": info_doc["urgencia"],
            "dados": dados_estruturados,
            "recursos": recursos_info,
            "confianca": analise_completa.get("confianca_tipo", "MÉDIA"),
            "perspectiva": perspectiva_aplicada  # 🔥 NOVO
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

        logging.info(f"✅ Processamento completo: {tipo_doc} (confiança: {analise_completa.get('confianca_tipo')}, perspectiva: {perspectiva_aplicada})")

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
            "modelo_usado": modelo_usado,
            "perspectiva_aplicada": perspectiva_aplicada,  # 🔥 NOVO - confirmar perspectiva
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
        perspectiva = contexto.get("perspectiva", "nao_informado")

        # Prompt simplificado para chat
        prompt = f"""Você é um assistente que responde perguntas sobre documentos jurídicos.

IMPORTANTE - PERSPECTIVA: {perspectiva}
{f'- Use "você" para o AUTOR/REQUERENTE' if perspectiva == 'autor' else ''}
{f'- Use "você" para o RÉU/REQUERIDO' if perspectiva == 'reu' else ''}
{f'- Use nomes próprios (não use "você")' if perspectiva == 'nao_informado' else ''}

DOCUMENTO (resumo):
- Tipo: {dados.get('tipo_documento')}
- Partes: {dados.get('partes')}
- Decisão: {dados.get('decisao')}
- Valores: {dados.get('valores')}
- Prazos: {dados.get('prazos')}

PERGUNTA: {pergunta}

Responda em NO MÁXIMO 2-3 frases curtas e simples, respeitando a perspectiva {perspectiva}. Se não souber, diga "Não encontrei essa informação".
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
    """Health check com informações dos modelos"""
    try:
        stats = database.get_estatisticas()
        total_docs = stats.get("total_documentos", 0)
        today_docs = stats.get("documentos_hoje", 0)
    except:
        total_docs = 0
        today_docs = 0

    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(GEMINI_API_KEY),
        "models": {
            "total": len(GEMINI_MODELS),
            "configured": [m["name"] for m in sorted(GEMINI_MODELS, key=lambda x: x["priority"])],
            "usage_stats": model_usage_stats
        },
        "tesseract_available": TESSERACT_AVAILABLE,
        "documents_processed": {
            "total": total_docs,
            "today": today_docs
        }
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
