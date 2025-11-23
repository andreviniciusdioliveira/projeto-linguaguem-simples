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
# Importar gerador de PDF melhorado
from gerador_pdf import gerar_pdf_simplificado as gerar_pdf_melhorado

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

PROMPT_SIMPLIFICACAO_MELHORADO = """
╔══════════════════════════════════════════════════════════════════╗
║  ⚠️⚠️⚠️ IMPORTANTE: NÃO COPIE ESTAS INSTRUÇÕES PARA O OUTPUT ⚠️⚠️⚠️  ║
║                                                                  ║
║  As instruções abaixo são para VOCÊ SEGUIR internamente.        ║
║  O texto que você vai GERAR deve ser APENAS o documento         ║
║  simplificado, SEM incluir nenhuma destas instruções,           ║
║  marcadores (🚨, ■, ═), ou lembretes.                          ║
╚══════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════════
SEÇÃO 1: INSTRUÇÕES PARA VOCÊ SEGUIR (NÃO INCLUIR NO OUTPUT)
═══════════════════════════════════════════════════════════════════

**INSTRUÇÕES PARA ESCOLHER O TIPO DE TÍTULO:**

**VERIFICAÇÃO OBRIGATÓRIA:**

PASSO 1: Quem são as partes do processo?
- ADOLESCENTE (menor de 18 anos) vs Ministério Público/Estado?
- ADULTO vs ADULTO/EMPRESA/ESTADO?

PASSO 2: O documento menciona EXPLICITAMENTE:
- "ato infracional"
- "adolescente representado"
- "medida socioeducativa"
- "Estatuto da Criança e do Adolescente"

DECISÃO:
→ Se PASSO 1 = ADOLESCENTE E PASSO 2 = SIM → Use "DECISÃO SOBRE ATO INFRACIONAL"
→ Se PASSO 1 = ADULTO → NUNCA use "ATO INFRACIONAL", escolha título apropriado abaixo

**OPÇÕES DE TÍTULOS:**

Se for MANDADO/CITAÇÃO/INTIMAÇÃO:
→ "📋 ORDEM JUDICIAL PARA [ação específica]"
→ Exemplo: "📋 ORDEM JUDICIAL PARA COMPARECER À AUDIÊNCIA"

Se for PROCESSO DE ATO INFRACIONAL (ECA - adolescente):
→ "⚖️ DECISÃO SOBRE ATO INFRACIONAL"
→ Só use se o documento mencionar explicitamente termos do ECA
→ NÃO use para processos cíveis, consumidor, trabalhista, família entre adultos

Se for SENTENÇA/ACÓRDÃO/DECISÃO CÍVEL/TRABALHISTA/CONSUMIDOR:
→ Para AUTOR que ganhou tudo: "✅ CONSEGUIU O QUE PEDIU"
→ Para AUTOR que ganhou parte: "🟡 CONSEGUIU PARTE DO QUE PEDIU"
→ Para AUTOR que perdeu: "❌ NÃO CONSEGUIU O QUE PEDIU"
→ Para RÉU absolvido: "✅ VITÓRIA TOTAL - Você foi absolvido de tudo"
→ Para RÉU parcialmente condenado: "🟡 CONDENAÇÃO PARCIAL"
→ Para RÉU totalmente condenado: "⚪ PEDIDO NEGADO - Você foi condenado"
→ Para perspectiva NEUTRA: "✅ VITÓRIA TOTAL", "🟡 VITÓRIA PARCIAL", "⚪ PEDIDO NEGADO"

**REGRAS CRÍTICAS DE PERSPECTIVA:**

Se AUTOR:
- Use "VOCÊ" para o autor
- Use nome do réu diretamente (ex: "Estado de Goiás", "GOL")
- Nunca use o nome do autor

Se RÉU:
- Use "VOCÊ" para o réu
- Use nome do autor diretamente (ex: "João Silva")
- Para valores, use "O QUE VOCÊ VAI PAGAR" se condenado
- Adapte títulos (ex: "Você foi condenado" ao invés de "Você ganhou")

Se ECA (Ato Infracional):
- NUNCA use "você"
- Use nome completo do adolescente
- Não use conceitos de vitória/derrota
- Foque na medida socioeducativa aplicada

Se NEUTRO (não informado):
- Use nomes reais das partes
- Não use "você"
- Mantenha imparcialidade

**REGRAS SOBRE VALORES DISCRIMINADOS:**

🚨🚨🚨 REGRA ABSOLUTA - LEIA ISSO 3 VEZES: 🚨🚨🚨

Se o documento original menciona QUALQUER detalhamento de valores, você é OBRIGADO a manter essa discriminação completa no texto simplificado.

EXEMPLOS DE DETALHAMENTO QUE VOCÊ DEVE PROCURAR:
- "R$ 1.362,14 referente às passagens aéreas"
- "R$ 65,50 compreendido pela soma de R$ 54,00 e R$ 11,50 gastos com alimentação"
- "R$ 3.000,00 para João + R$ 3.000,00 para Maria"
- "sendo: R$ X de item A e R$ Y de item B"

SE ENCONTROU DETALHAMENTO → USE O FORMATO DISCRIMINADO (OBRIGATÓRIO):

✅ FORMATO CORRETO:
```
📋 **Danos Materiais: R$ 1.427,64**
- Reembolso de passagens aéreas: R$ 1.362,14
- Reembolso de alimentação durante a viagem: R$ 65,50

📋 **TOTAL GERAL: R$ 7.427,64**
⚠️ Este valor será atualizado até o pagamento.
```

❌ FORMATO ERRADO (NÃO FAÇA ISSO):
```
Danos Materiais: R$ 1.427,64
```

Se o documento REALMENTE só menciona total sem nenhum detalhamento, use formato simples.

**REGRAS SOBRE JUSTIÇA GRATUITA:**

Se tem_justica_gratuita = true:
- NÃO inclua honorários/custas na seção "O QUE VOCÊ VAI GANHAR"
- Na seção "Sobre custas e honorários", escreva APENAS: "Você NÃO vai pagar custas e honorários porque tem justiça gratuita."
- NÃO mencione valores, não use "suspenso", "agora", "futuramente"

**REGRAS SOBRE PRÓXIMOS PASSOS:**

SEMPRE oriente a consultar advogado(a) ou defensoria pública quando:
- Ganhou parcialmente
- Perdeu
- Cabe recurso
- Valores a receber sem indicação de como/quando
- Na dúvida

NUNCA diga "Aguarde o tribunal te avisar" ou "Aguarde pagamento automático"

Use "Aguarde" APENAS para:
- Mandados com data/hora marcada
- Ordens diretas e claras

**REGRAS SOBRE PRAZOS:**

- Se NÃO houver prazos específicos → NÃO mencione prazos
- Se houver → especifique PARA QUEM e PARA QUÊ
- Exemplo CORRETO: "A Secretaria tem 15 dias para realizar avaliação"
- Exemplo ERRADO: "15 dias" (sem contexto)

**REGRAS SOBRE TERMOS TÉCNICOS:**

🚨 SEMPRE explique ou substitua estes termos quando aparecerem:

TERMOS QUE DEVEM SER EXPLICADOS NO GLOSSÁRIO (obrigatório):
- "Juiz de primeira instância" → Explique: "O primeiro juiz que analisa o caso"
- "Segunda instância" ou "Tribunal" → Explique: "Juízes que analisam recursos"
- "Honorários" → Explique: "Pagamento ao advogado pelo trabalho"
- "Trânsito em julgado" → Explique: "Quando não dá mais para contestar"

TERMOS QUE DEVEM SER SUBSTITUÍDOS NO TEXTO (sempre):
- "Parcialmente procedente" → Use: "Você ganhou parte do que pediu"
- "Procedente" → Use: "Você ganhou"
- "Improcedente" → Use: "Você perdeu"
- "Deferido" → Use: "aprovado" ou "aceito"
- "Indeferido" → Use: "negado" ou "recusado"

QUANDO MENCIONAR "JUIZ DE PRIMEIRA INSTÂNCIA" NO TEXTO:
Na primeira vez, escreva: "juiz de primeira instância (o primeiro juiz que analisa o caso)"
Nas vezes seguintes, pode usar apenas "juiz" ou "juiz de primeira instância"

**REGRAS DE ESCRITA:**

- Máximo 15 palavras por frase
- NUNCA use: "exequente", "executado", "lide", "mérito"
- Seja empático conforme a perspectiva
- Use linguagem simples e conversacional

═══════════════════════════════════════════════════════════════════
SEÇÃO 2: TEMPLATE DO QUE VOCÊ VAI GERAR (SUA RESPOSTA FINAL)
═══════════════════════════════════════════════════════════════════

🚨🚨🚨 ANTES DE COMEÇAR A ESCREVER - CHECKLIST OBRIGATÓRIO 🚨🚨🚨

PASSO 1: Procure no documento por valores discriminados
- Busque palavras: "sendo", "compreendido", "soma de", "referente a", "gastos com"
- Procure múltiplos valores R$ próximos com descrições
- Se encontrar → marque SIM
- Se não encontrar nada → marque NÃO

PASSO 2: Se marcou SIM no Passo 1
→ Você é OBRIGADO a usar o formato discriminado com 📋
→ NUNCA use formato simples quando há discriminação
→ Exemplo: Se viu "R$ 1.362,14 de passagens" + "R$ 65,50 de alimentação"
  ENTÃO use:
  📋 **Danos Materiais: R$ 1.427,64**
  - Reembolso de passagens aéreas: R$ 1.362,14
  - Reembolso de alimentação: R$ 65,50

PASSO 3: Se marcou NÃO no Passo 1
→ Use formato simples: "- Danos materiais: R$ X"

═══════════════════════════════════════════════════════════════════

[TÍTULO ESCOLHIDO CONFORME INSTRUÇÕES ACIMA]

**Em uma frase simples:** [Explique o resultado direto - use a perspectiva correta]

---

**O QUE ESTÁ ACONTECENDO**

[Em 2-3 parágrafos curtos, conte a história do processo respeitando a perspectiva]

[Use frases de 10-15 palavras. Seja direto e claro.]

---

**A DECISÃO DO JUIZ** (ou DESEMBARGADOR(A) se for acórdão, ou ORDEM JUDICIAL se for mandado)

[Explique em linguagem simples o que foi decidido]

[Use blocos curtos:]
- Sobre [assunto X]: O juiz decidiu que...
- Sobre [assunto Y]: O juiz entendeu que...

[Nesta seção, mencione valores de forma RESUMIDA (ex: "R$ 1.427,64 de danos materiais")]
[NÃO discrimine os valores aqui - discriminação vai na próxima seção]

---

**VALORES E O QUE VOCÊ PRECISA FAZER**

**O QUE VOCÊ VAI GANHAR:** (ou "O QUE VOCÊ VAI PAGAR:" se for réu condenado, ou "BOA NOTÍCIA - VOCÊ NÃO VAI PAGAR:" se réu absolvido)

🚨 RELEIA O CHECKLIST OBRIGATÓRIO ACIMA ANTES DE ESCREVER ESTA SEÇÃO! 🚨

[FORMATO DISCRIMINADO - Use quando encontrou detalhamento no documento:]
📋 **[Categoria]: R$ [TOTAL]**
- [Descrição item 1]: R$ [valor1]
- [Descrição item 2]: R$ [valor2]

📋 **TOTAL GERAL: R$ [total]**
⚠️ Este valor será atualizado! Isso quer dizer que ele poderá sofrer um pequeno aumento até o dia do pagamento.

[FORMATO SIMPLES - Use SOMENTE quando documento não tem detalhamento:]
- Danos materiais: R$ X
- Danos morais: R$ Y

[NÃO inclua honorários/custas aqui se tem justiça gratuita]

**O QUE VOCÊ NÃO VAI GANHAR:**
[Liste valores negados, se houver. Omita esta seção se não aplicável]

**Sobre custas e honorários:**

[Se tem justiça gratuita:]
Você NÃO vai pagar custas e honorários porque tem justiça gratuita.

[Se NÃO tem justiça gratuita:]
Você deve pagar [valores específicos de custas e honorários].

**Próximos passos:**

[Seja ESPECÍFICO e PRÁTICO]
[Oriente a consultar advogado(a) ou defensoria pública na maioria dos casos]
[Só use "Aguarde" para mandados com data/hora ou ordens diretas]
[Se houver prazos, especifique PARA QUEM e PARA QUÊ]

---

**PALAVRAS QUE PODEM APARECER NO DOCUMENTO**

[Liste APENAS 5-7 termos mais importantes QUE REALMENTE APARECEM NO DOCUMENTO]

- **[Termo]**: [Explicação simples em 5-10 palavras]

[Priorize termos como: Cumprimento da decisão, Indenização, Honorários, Intimação, Recurso, Trânsito em julgado, Audiência, Citação, Danos Materiais, Danos Morais, Revelia]

[Só inclua "Ato Infracional" e "Medida Socioeducativa" se for processo ECA]

[Máximo 7 termos!]

---

*💡 Dica: Este documento não substitui a orientação jurídica. Se precisar, busque ajuda com um advogado ou uma advogada ou com a Defensoria Pública.*

═══════════════════════════════════════════════════════════════════
FIM DO TEMPLATE
═══════════════════════════════════════════════════════════════════

LEMBRE-SE: Seu output final deve conter APENAS o documento simplificado seguindo o template acima, SEM incluir as instruções, marcadores (🚨, ■, ═), ou lembretes desta seção.
"""

# ============= VALIDAÇÃO DE OUTPUT =============

def validar_e_limpar_output(texto_simplificado):
    """
    Valida e remove qualquer vazamento de instruções do texto simplificado.
    Retorna o texto limpo e um booleano indicando se houve vazamentos.
    """
    texto_original = texto_simplificado
    vazamentos_encontrados = False

    # Lista de padrões que NÃO devem aparecer no documento final
    padroes_proibidos = [
        # Marcadores de instrução
        r'🚨\s*\*\*LEMBRETE CRÍTICO',
        r'🚨\s*\*\*REGRA CRÍTICA',
        r'■\s*LEMBRETE',
        r'■\s*REGRA',
        r'═+',  # Linhas de separação
        r'╔═+╗',  # Caixas de aviso
        r'║.*║',  # Linhas de caixas
        r'╚═+╝',

        # Textos de instrução específicos
        r'LEMBRETE CRÍTICO ANTES DE ESCREVER:',
        r'REGRA CRÍTICA #\d+',
        r'INSTRUÇÕES PARA',
        r'VERIFICAÇÃO OBRIGATÓRIA',
        r'CHECKLIST ANTES DE GERAR',
        r'Aplique isso em TODAS as seções abaixo!',
        r'não copie isso para o texto final',
        r'ESTAS SÃO INSTRUÇÕES - NÃO COPIE',
        r'NÃO INCLUIR NO TEXTO SIMPLIFICADO',

        # Checkboxes e listas de verificação
        r'□\s*Verifiquei',
        r'\[\s*\]\s*ADOLESCENTE',
        r'\[\s*\]\s*ADULTO',

        # Exemplos de instrução
        r'❌\s*ERRADO\s*\(O QUE VOCÊ NÃO DEVE FAZER\):',
        r'✅\s*CORRETO\s*\(O QUE VOCÊ DEVE FAZER\):',
        r'EXEMPLO REAL - CASO.*\(USE COMO REFERÊNCIA\):',

        # Instruções de perspectiva
        r'Antes de escrever cada seção, releia as INSTRUÇÕES DE PERSPECTIVA',
    ]

    # Remover padrões proibidos
    for padrao in padroes_proibidos:
        if re.search(padrao, texto_simplificado, re.IGNORECASE):
            vazamentos_encontrados = True
            # Remover linha inteira que contém o padrão
            linhas = texto_simplificado.split('\n')
            linhas_limpas = []
            for linha in linhas:
                if not re.search(padrao, linha, re.IGNORECASE):
                    linhas_limpas.append(linha)
            texto_simplificado = '\n'.join(linhas_limpas)

    # Remover blocos de código markdown que contenham exemplos de instrução
    texto_simplificado = re.sub(
        r'```\s*\n.*?(?:ERRADO|CORRETO).*?\n```',
        '',
        texto_simplificado,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Remover linhas vazias consecutivas (limpeza estética)
    texto_simplificado = re.sub(r'\n{3,}', '\n\n', texto_simplificado)

    # Log se houve vazamentos
    if vazamentos_encontrados:
        logging.warning("⚠️ Vazamentos de instruções detectados e removidos do output")
        logging.debug(f"Texto antes: {texto_original[:200]}...")
        logging.debug(f"Texto depois: {texto_simplificado[:200]}...")

    return texto_simplificado.strip(), vazamentos_encontrados

# ============= DETECÇÃO DE PERSPECTIVA =============

def determinar_perspectiva_automatica(texto, perspectiva_usuario=None):
    """
    Determina a perspectiva do usuário no processo de forma mais robusta.

    Args:
        texto: Texto completo do documento
        perspectiva_usuario: Perspectiva informada pelo usuário (se houver)

    Returns:
        tuple: (perspectiva, nome_parte, confianca)
        - perspectiva: 'autor', 'reu', 'eca', ou 'nao_informado'
        - nome_parte: Nome da parte identificada (se aplicável)
        - confianca: 'alta', 'media', 'baixa'
    """

    # Se usuário já informou, usar isso
    if perspectiva_usuario and perspectiva_usuario != "nao_informado":
        return (perspectiva_usuario, None, "alta")

    texto_lower = texto.lower()
    confianca = "baixa"

    # 1. VERIFICAR SE É PROCESSO ECA (Ato Infracional)
    indicadores_eca = 0

    if "ato infracional" in texto_lower:
        indicadores_eca += 3  # Indicador muito forte
    if "adolescente representado" in texto_lower:
        indicadores_eca += 3  # Indicador muito forte
    if "medida socioeducativa" in texto_lower or "medida sócio-educativa" in texto_lower:
        indicadores_eca += 3  # Indicador muito forte
    if "estatuto da criança e do adolescente" in texto_lower or "eca" in texto_lower:
        indicadores_eca += 2  # Indicador forte

    # Se tiver múltiplos indicadores ECA, é processo de adolescente
    if indicadores_eca >= 3:
        # Tentar extrair nome do adolescente
        nome_adolescente = None

        # Padrões comuns
        padroes_adolescente = [
            r'adolescente(?:\s+representado[a]?)?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+)*)',
            r'representado[a]?\s+(?:pelo|por)\s+(?:seu|sua)\s+(?:genitora?|responsável)\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+)*)',
        ]

        for padrao in padroes_adolescente:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                nome_adolescente = match.group(1).strip()
                break

        return ("eca", nome_adolescente, "alta" if nome_adolescente else "media")

    # 2. TENTAR IDENTIFICAR AUTOR E RÉU
    # Extrair autor (múltiplos padrões)
    autor_nome = None
    reu_nome = None

    padroes_autor = [
        r'autor[ea]?s?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){1,5})',
        r'requerente[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){1,5})',
        r'apelante[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){1,5})',
        r'recorrente[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){1,5})',
    ]

    for padrao in padroes_autor:
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            autor_nome = match.group(1).strip()
            confianca = "alta"
            break

    # Extrair réu (múltiplos padrões)
    padroes_reu = [
        r'réus?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,5})',
        r'requerido[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,5})',
        r'apelado[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,5})',
        r'recorrido[s]?\s*:?\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,5})',
    ]

    for padrao in padroes_reu:
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            reu_nome = match.group(1).strip()
            if confianca != "alta":
                confianca = "media"
            break

    # Log para debug
    if autor_nome:
        logging.info(f"🎯 Autor identificado: {autor_nome}")
    if reu_nome:
        logging.info(f"🎯 Réu identificado: {reu_nome}")

    # 3. RETORNAR PERSPECTIVA NEUTRA SE NÃO CONSEGUIU DETERMINAR
    # (O frontend pode pedir ao usuário para escolher)
    return ("nao_informado", {"autor": autor_nome, "reu": reu_nome}, confianca)

# ============= EXTRAÇÃO E VALIDAÇÃO DE VALORES =============

def extrair_valores_financeiros(texto):
    """
    Extrai todos os valores monetários do documento e classifica por contexto.

    Returns:
        dict: Dicionário com valores extraídos e suas classificações
    """
    valores = {
        'todos': [],  # Todos os valores encontrados
        'danos_morais': [],
        'danos_materiais': [],
        'honorarios': [],
        'custas': [],
        'total': [],
        'discriminacoes': []  # Lista de discriminações encontradas
    }

    # Regex para valores monetários (incluindo formato brasileiro)
    # Exemplos: R$ 1.000,00 | R$1000,00 | 1.000,00 | R$ 1000
    pattern_valor = r'R\$\s*[\d.,]+(?:\s*\([^)]+\))?'

    # Encontrar todos os valores
    matches_valores = list(re.finditer(pattern_valor, texto, re.IGNORECASE))

    for match in matches_valores:
        valor_texto = match.group()
        inicio = match.start()
        fim = match.end()

        # Pegar contexto (100 chars antes e depois)
        contexto_inicio = max(0, inicio - 100)
        contexto_fim = min(len(texto), fim + 100)
        contexto = texto[contexto_inicio:contexto_fim].lower()

        # Criar entrada de valor
        valor_info = {
            'valor': valor_texto,
            'contexto': contexto,
            'posicao': inicio
        }

        valores['todos'].append(valor_info)

        # Classificar por contexto
        if any(termo in contexto for termo in ['dano moral', 'danos morais', 'indenização moral']):
            valores['danos_morais'].append(valor_info)
        elif any(termo in contexto for termo in ['dano material', 'danos materiais', 'prejuízo material', 'reembolso', 'passagens', 'alimentação', 'despesas']):
            valores['danos_materiais'].append(valor_info)
        elif any(termo in contexto for termo in ['honorário', 'honorários', 'advogado']):
            valores['honorarios'].append(valor_info)
        elif any(termo in contexto for termo in ['custa', 'custas', 'despesas processuais']):
            valores['custas'].append(valor_info)
        elif any(termo in contexto for termo in ['total', 'soma', 'totaliza']):
            valores['total'].append(valor_info)

    # Detectar discriminações (múltiplos valores próximos com descrições)
    # Padrões de discriminação:
    # - "R$ X de passagens + R$ Y de alimentação"
    # - "R$ X para João + R$ Y para Maria"
    padroes_discriminacao = [
        r'(R\$\s*[\d.,]+)\s+(?:de|para|referente)\s+([^,\n]+?)(?:\s*\+|\s*e|\s*,)\s*(R\$\s*[\d.,]+)\s+(?:de|para|referente)\s+([^,\n]+)',
        r'(?:sendo|consistindo|distribuídos):\s*\n?\s*-\s*([^:\n]+):\s*(R\$\s*[\d.,]+)',
    ]

    for padrao in padroes_discriminacao:
        matches = re.finditer(padrao, texto, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            valores['discriminacoes'].append({
                'texto': match.group(0),
                'posicao': match.start()
            })

    # Log para debug
    logging.info(f"💰 Valores encontrados: {len(valores['todos'])}")
    if valores['danos_morais']:
        logging.info(f"   - Danos morais: {len(valores['danos_morais'])} valores")
    if valores['danos_materiais']:
        logging.info(f"   - Danos materiais: {len(valores['danos_materiais'])} valores")
    if valores['discriminacoes']:
        logging.info(f"   - Discriminações detectadas: {len(valores['discriminacoes'])}")

    return valores

def validar_discriminacao_valores(texto_simplificado, valores_json):
    """
    Valida se o texto simplificado manteve as discriminações de valores.

    Args:
        texto_simplificado: Texto simplificado gerado
        valores_json: Objeto valores_principais do JSON

    Returns:
        tuple: (passou_validacao, avisos)
    """
    avisos = []
    passou = True

    # Verificar discriminação de danos materiais
    danos_mat_disc = valores_json.get('danos_materiais_discriminado', [])
    if danos_mat_disc and len(danos_mat_disc) > 1:
        # Deve haver discriminação no texto
        tem_discriminacao = False

        for item in danos_mat_disc:
            item_desc = item.get('item', '')
            item_valor = item.get('valor', '')

            # Verificar se item aparece no texto simplificado
            if item_desc and item_desc.lower() in texto_simplificado.lower():
                tem_discriminacao = True
                break

        if not tem_discriminacao:
            avisos.append("⚠️ Discriminação de danos materiais esperada mas não encontrada no texto")
            passou = False

    # Verificar discriminação de danos morais
    danos_mor_disc = valores_json.get('danos_morais_discriminado', [])
    if danos_mor_disc and len(danos_mor_disc) > 1:
        tem_discriminacao = False

        for item in danos_mor_disc:
            beneficiario = item.get('beneficiario', '')

            if beneficiario and beneficiario.lower() in texto_simplificado.lower():
                tem_discriminacao = True
                break

        if not tem_discriminacao:
            avisos.append("⚠️ Discriminação de danos morais esperada mas não encontrada no texto")
            passou = False

    # Log avisos
    for aviso in avisos:
        logging.warning(aviso)

    return passou, avisos

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

    # 🔥 DETECTAR PROCESSO DE ATO INFRACIONAL - VERSÃO RESTRITIVA
    # Só considera ato infracional se tiver MÚLTIPLOS indicadores fortes
    indicadores_eca = 0

    if "ato infracional" in texto.lower():
        indicadores_eca += 2  # Indicador forte
    if "adolescente representado" in texto.lower():
        indicadores_eca += 2  # Indicador forte
    if "medida socioeducativa" in texto.lower():
        indicadores_eca += 2  # Indicador forte
    if "estatuto da criança e do adolescente" in texto.lower():
        indicadores_eca += 2  # Indicador forte

    # Só considera ECA se tiver indicadores FORTES (pontuação >= 2)
    # E NÃO sobrescreve a perspectiva do usuário se ela foi informada
    is_ato_infracional = (indicadores_eca >= 2) and (perspectiva == "nao_informado")

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

1️⃣ Use **"VOCÊ"** para se referir ao **AUTOR/REQUERENTE** em TODO o texto
2️⃣ Use o **NOME DO RÉU** diretamente (ex: "Estado de Goiás", "Empresa XYZ")
3️⃣ Escreva como se estivesse FALANDO DIRETAMENTE com o autor
4️⃣ NUNCA use o nome do autor - sempre "VOCÊ"

**EXEMPLOS OBRIGATÓRIOS:**

❌ ERRADO: "Andresley Carlos entrou com um processo..."
✅ CORRETO: "VOCÊ entrou com um processo..."

❌ ERRADO: "O juiz decidiu que o Estado de Goiás deve pagar a Andresley Carlos..."
✅ CORRETO: "O juiz decidiu que o Estado de Goiás deve pagar a VOCÊ..."

❌ ERRADO: "Para Andresley Carlos: R$ 30.000,00"
✅ CORRETO: "Para VOCÊ: R$ 30.000,00"

❌ ERRADO: "Andresley Carlos pediu indenização..."
✅ CORRETO: "VOCÊ pediu indenização..."

❌ ERRADO: "Ele disse que foi preso por engano..."
✅ CORRETO: "VOCÊ disse que foi preso por engano..."

❌ ERRADO: "O autor ganhou..."
✅ CORRETO: "VOCÊ ganhou..."

**REGRA DE OURO:**
- SUBSTITUA TODO "autor", "requerente", "apelante", nome do autor → **VOCÊ**
- MANTENHA o nome do réu/empresa/Estado (ex: "Estado de Goiás", "GOL", "Banco")
- Escreva em segunda pessoa (você, seu, sua) - seja PESSOAL e DIRETO

**ATENÇÃO REDOBRADA EM:**
- Seção "O QUE ESTÁ ACONTECENDO" → Diga "Você entrou com um processo contra [NOME DO RÉU]..."
- Seção "A DECISÃO DO JUIZ" → Diga "O juiz decidiu que [NOME DO RÉU] deve pagar a VOCÊ..." ou "O juiz decidiu que VOCÊ..."
- Seção "VALORES E O QUE VOCÊ PRECISA FAZER" → Diga "Você vai receber de [NOME DO RÉU]..." ou "Você deve pagar..."
- Use SEMPRE o nome do réu ao invés de "a outra parte" para evitar confusão
'''
        
    elif perspectiva == "reu":
        instrucao_perspectiva = '''
╔══════════════════════════════════════════════════════════════════╗
║  🚨 REGRA CRÍTICA DE PERSPECTIVA - VOCÊ É O RÉU/REQUERIDO        ║
╚══════════════════════════════════════════════════════════════════╝

**INSTRUÇÕES ABSOLUTAS:**

1️⃣ Use **"VOCÊ"** para se referir ao **RÉU/REQUERIDO** em TODO o texto
2️⃣ Use o **NOME DO AUTOR** diretamente (ex: "Andresley Carlos", "João Silva")
3️⃣ Escreva como se estivesse FALANDO DIRETAMENTE com o réu
4️⃣ NUNCA use "o réu", "o requerido", "o Estado" se for você - sempre "VOCÊ"

**EXEMPLOS OBRIGATÓRIOS:**

❌ ERRADO: "O Estado de Goiás foi condenado..."
✅ CORRETO: "VOCÊ foi condenado..."

❌ ERRADO: "O juiz decidiu que o Estado deve pagar..."
✅ CORRETO: "O juiz decidiu que VOCÊ deve pagar..."

❌ ERRADO: "Andresley Carlos entrou com processo contra o Estado de Goiás..."
✅ CORRETO: "Andresley Carlos entrou com processo contra VOCÊ..."

❌ ERRADO: "O autor pediu indenização ao réu..."
✅ CORRETO: "Andresley Carlos pediu indenização a VOCÊ..."

❌ ERRADO: "A outra parte entrou com processo..."
✅ CORRETO: "Andresley Carlos entrou com processo..."

❌ ERRADO: "O Estado de Goiás deve pagar R$ 30.000,00"
✅ CORRETO: "VOCÊ deve pagar R$ 30.000,00"

**REGRA DE OURO:**
- SUBSTITUA TODO "réu", "requerido", "apelado", nome do Estado/empresa → **VOCÊ**
- MANTENHA o nome do autor (ex: "Andresley Carlos", "João Silva")
- Escreva em segunda pessoa (você, seu, sua) - seja PESSOAL e DIRETO

**REGRAS CRÍTICAS ESPECÍFICAS PARA RÉU:**

🚨 **TÍTULOS - ADAPTADOS PARA RÉU:**
- Se réu foi TOTALMENTE condenado → "⚪ PEDIDO NEGADO - Você foi condenado"
- Se réu foi PARCIALMENTE condenado → "🟡 CONDENAÇÃO PARCIAL"
- Se réu foi TOTALMENTE absolvido → "✅ VITÓRIA TOTAL - Você foi absolvido de tudo"
- ❌ NUNCA diga "Você conseguiu parte do que pediu" porque o RÉU NÃO PEDE nada, é o AUTOR que pede

🚨 **VALORES - INVERTA A SEÇÃO:**
Quando o réu foi condenado a pagar:
- ❌ NÃO use: "✅ O QUE VOCÊ VAI GANHAR:"
- ✅ USE: "❌ O QUE VOCÊ VAI PAGAR:"

Quando o réu não foi condenado a pagar nada (ou foi absolvido):
- ✅ USE: "✅ BOA NOTÍCIA - VOCÊ NÃO VAI PAGAR:"

🚨 **FRASE RESUMO:**
- ❌ ERRADO: "A outra parte deve pagar a você R$ 20.000,00"
- ✅ CORRETO: "O juiz decidiu que você deve pagar R$ 20.000,00 a [NOME DO AUTOR]"

**ATENÇÃO REDOBRADA EM:**
- Seção "O QUE ESTÁ ACONTECENDO" → Use o nome do autor: "[NOME] entrou com um processo contra você..."
- Seção "A DECISÃO DO JUIZ" → Diga "O juiz decidiu que VOCÊ..."
- Seção "VALORES E O QUE VOCÊ PRECISA FAZER" → Se condenado, use "O QUE VOCÊ VAI PAGAR:" (não "ganhar")
- Use SEMPRE o nome do autor ao invés de "a outra parte" para evitar confusão
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
  "acao_necessaria": "Frase MUITO SIMPLES sobre o que fazer agora",

**INSTRUÇÕES PARA acao_necessaria:**
- Use linguagem de CONVERSA DIRETA, como se estivesse orientando um amigo ou familiar
- NUNCA use palavras difíceis: "cumprimento", "recursos", "decisão judicial", "indenização", "intimação", "trânsito em julgado"
- Diga EXATAMENTE o que a pessoa deve fazer AGORA, de forma ULTRA PRÁTICA
- Máximo 8 palavras
- Pense: "Como eu explicaria isso para minha avó?"
- Exemplos PROIBIDOS e CORRETOS:
  * ❌ ERRADO: "Aguardar cumprimento da decisão judicial"
  * ❌ ERRADO: "Aguarde o cumprimento da decisão"
  * ❌ ERRADO: "Aguarde o pagamento da indenização"
  * ❌ ERRADO: "Aguardar cumprimento da decisão ou informações sobre recursos"
  * ❌ ERRADO: "Verificar se cabe recurso e prazo"
  * ✅ CORRETO: "Fale com advogado(a) ou defensoria pública"
  * ❌ ERRADO: "Apresentar-se para cumprimento da medida"
  * ✅ CORRETO: "Vá ao endereço indicado no prazo"
  * ❌ ERRADO: "Acompanhar andamento processual"
  * ✅ CORRETO: "Acompanhe online no site do tribunal"
  * ❌ ERRADO: "Aguardar intimação"
  * ✅ CORRETO: "Fale com advogado(a) ou defensoria pública"
  * ❌ ERRADO: "Cumprir obrigação de fazer"
  * ✅ CORRETO: "Faça o que foi pedido na decisão"

**🚨 REGRA CRÍTICA SOBRE "AGUARDE":**
- ⚠️ CUIDADO ao usar "Aguarde..." - geralmente é melhor orientar a CONSULTAR ADVOGADO
- ❌ NUNCA use "Aguarde - será executado automaticamente" para sentenças/acórdãos
- ✅ Em sentenças/acórdãos, SEMPRE prefira: "Fale com advogado(a) ou defensoria pública"
- ✅ A execução raramente é automática - geralmente requer ação do advogado

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

  "decisao_resumida": "1 frase SIMPLES: o que foi decidido",

**INSTRUÇÕES PARA decisao_resumida:**
- Use linguagem MUITO SIMPLES, como se estivesse falando com uma criança
- NÃO use termos técnicos como "acolheu", "procedente", "improcedente", "parcialmente procedente"
- Diga CLARAMENTE o resultado prático
- Exemplos:
  * ❌ ERRADO: "O juiz acolheu em parte os pedidos iniciais, condenando a requerida ao pagamento de danos materiais e morais"
  * ✅ CORRETO: "O juiz decidiu que a empresa deve pagar indenização por danos materiais e morais"
  * ❌ ERRADO: "Julgo parcialmente procedente o pedido"
  * ✅ CORRETO: "O autor ganhou parte do que pediu"
  * ❌ ERRADO: "Acolho a preliminar de ilegitimidade passiva"
  * ✅ CORRETO: "O juiz decidiu que esta parte não deveria estar no processo"

  "valores_principais": {{
    "total_a_receber": "R$ XXX ou null",
    "danos_morais": "R$ XXX ou null",
    "danos_morais_discriminado": [
      {{"beneficiario": "Nome da Pessoa", "valor": "R$ XXX"}}
    ],
    "danos_materiais": "R$ XXX ou null",
    "danos_materiais_discriminado": [
      {{"item": "Descrição do item", "valor": "R$ XXX"}}
    ],
    "honorarios": "X% ou R$ XXX ou null",
    "custas": "quem paga ou null"
  }},

**🚨 INSTRUÇÕES CRÍTICAS PARA HONORÁRIOS E CUSTAS (LEIA COM ATENÇÃO):**

**REGRA ABSOLUTA:**
- Se `tem_justica_gratuita` = true → SEMPRE use:
  * "honorarios": "Isento (justiça gratuita)"
  * "custas": "Isento (justiça gratuita)"

- Se `tem_justica_gratuita` = false:
  * Preencha normalmente com valores ou percentuais

**❌ NUNCA faça isso quando tem justiça gratuita:**
- "honorarios": "10% do valor da condenação (devido pelo autor)" ← ERRADO!
- "honorarios": "R$ 3.000,00 a pagar" ← ERRADO!

**✅ SEMPRE faça isso quando tem justiça gratuita:**
- "honorarios": "Isento (justiça gratuita)" ← CORRETO!
- "custas": "Isento (justiça gratuita)" ← CORRETO!

**Por quê?**
- Justiça gratuita = pessoa NÃO paga custas e honorários
- Mesmo se houver "suspensão da exigibilidade" = pessoa está ISENTA
- O frontend vai mostrar isso na seção de valores, então deve estar claro que NÃO há pagamento

═══════════════════════════════════════════════════════════════════

**🚨🚨🚨 INSTRUÇÕES CRÍTICAS PARA VALORES DISCRIMINADOS 🚨🚨🚨**

⚠️⚠️⚠️ LEIA ESTA SEÇÃO 3 VEZES ANTES DE PREENCHER O JSON ⚠️⚠️⚠️

TAREFA OBRIGATÓRIA EM 3 ETAPAS:

ETAPA 1: PROCURE ATIVAMENTE POR DETALHAMENTOS
Leia TODO o documento procurando por estas palavras-chave:
✓ "sendo:" ou "sendo,"
✓ "consistindo" ou "compreendido"
✓ "soma de" ou "dividido"
✓ "referente a" ou "referente ao"
✓ "gastos com" ou "despesas de"
✓ Múltiplos valores R$ próximos com descrições entre eles

ETAPA 2: SE ENCONTROU QUALQUER DETALHAMENTO
→ Preencha OBRIGATORIAMENTE os arrays "_discriminado"
→ EXEMPLO REAL:
  Documento diz: "R$ 1.362,14 de passagens aéreas" + "R$ 65,50 de alimentação"
  Você DEVE criar:
  "danos_materiais_discriminado": [
    {{"item": "Reembolso de passagens aéreas", "valor": "R$ 1.362,14"}},
    {{"item": "Reembolso de alimentação durante a viagem", "valor": "R$ 65,50"}}
  ]

→ OUTRO EXEMPLO:
  Documento diz: "R$ 65,50 compreendido pela soma de R$ 54,00 e R$ 11,50"
  Você DEVE discriminar os dois valores, mesmo que seja uma "soma"

ETAPA 3: SE NÃO ENCONTROU NENHUM DETALHAMENTO
→ Deixe os arrays vazios: "danos_materiais_discriminado": []
→ Apenas preencha: "danos_materiais": "R$ X" com o total

🚨 LEMBRE-SE: Se você preencher arrays "_discriminado" com 2+ itens, o texto simplificado DEVE usar o formato discriminado com 📋 e lista!

**🎯 EXEMPLO REAL DE PREENCHIMENTO - CASO GOL LINHAS AÉREAS:**

Se o documento diz:
"CONDENO a requerida ao pagamento de R$ 1.427,64 (danos materiais), sendo:
- R$ 1.362,14 de reembolso de passagens aéreas
- R$ 65,50 de alimentação

E R$ 6.000,00 (danos morais), sendo:
- R$ 3.000,00 para Thiago José de Arruda Oliveira
- R$ 3.000,00 para Kamilla Sousa Prado"

Você DEVE preencher o JSON assim:

```json
{{
  "valores_principais": {{
    "total_a_receber": "R$ 7.427,64",
    "danos_morais": "R$ 6.000,00",
    "danos_morais_discriminado": [
      {{"beneficiario": "Thiago José de Arruda Oliveira", "valor": "R$ 3.000,00"}},
      {{"beneficiario": "Kamilla Sousa Prado", "valor": "R$ 3.000,00"}}
    ],
    "danos_materiais": "R$ 1.427,64",
    "danos_materiais_discriminado": [
      {{"item": "Reembolso de passagens aéreas", "valor": "R$ 1.362,14"}},
      {{"item": "Reembolso de alimentação durante a viagem", "valor": "R$ 65,50"}}
    ],
    "honorarios": "Não há cobrança (justiça gratuita)",
    "custas": "Não há cobrança (justiça gratuita)"
  }}
}}
```

**🚨 ATENÇÃO:** Se você preencheu "danos_materiais_discriminado" com 2+ itens,
o texto simplificado DEVE OBRIGATORIAMENTE usar essa discriminação!

**NÃO FAÇA ISSO:**
❌ Texto: "O juiz determinou o pagamento de R$ 1.427,64 de danos materiais"

**FAÇA ISSO:**
✅ Texto:
```
O juiz determinou o pagamento de R$ 1.427,64 de danos materiais:

📋 **Danos Materiais: R$ 1.427,64**
- Reembolso de passagens aéreas: R$ 1.362,14
- Reembolso de alimentação durante a viagem: R$ 65,50
```

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
    "cabe_recurso": "Sim|Não|Não se aplica|Consulte advogado(a) ou defensoria pública",
    "tipo_recurso": "Apelação|Agravo|etc ou null",
    "prazo": "X dias ou null",
    "explicacao_simples": "Explicação em linguagem simples sobre recurso (ex: 'Outros juízes podem analisar se você pedir recurso')"
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
   - ⚠️ **ATENÇÃO:** Se encontrar "JULGO", verifique se refere-se ao julgamento do RECURSO (ex: "Negar provimento", "Dar provimento", "Conhecer e negar") e NÃO a citações da sentença original. Citações como "o juiz julgou procedente" devem ser ignoradas.
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

🚨 REGRA ESPECIAL PARA MANDADOS:
- Se o tipo_documento for "mandado" → "cabe_recurso": "Não se aplica"
- Mandados são ordens judiciais de cumprimento, NÃO são decisões que se recorrem
- Em mandados, não existe recurso direto - o que pode ser recorrido é a decisão que originou o mandado

Para outros tipos de documento, "cabe_recurso":
  * "Sim" - se o documento menciona explicitamente que cabe recurso
  * "Não" - se o documento menciona explicitamente que não cabe recurso ou que é decisão irrecorrível
  * "Consulte advogado(a) ou defensoria pública" - se o documento não menciona se cabe ou não cabe recurso

- "prazo": Use APENAS se o documento mencionar prazo específico para recurso, senão use null
- NUNCA escreva "Sim|Não|Consulte..." com todas as opções juntas - escolha apenas UMA

**REGRAS CRÍTICAS PARA VALORES NO TEXTO SIMPLIFICADO:**

1️⃣ **Discriminação Obrigatória:**
   - Se o documento detalha valores (ex: "R$ 1.362,14 de passagens + R$ 65,50 de alimentação = R$ 1.427,64")
   - Você DEVE manter essa discriminação no texto simplificado
   - Use estrutura de lista com subitens

2️⃣ **Exemplo Real Correto:**

**Documento diz:**
"R$ 1.362,14 de reembolso de passagens + R$ 65,50 de alimentação = total de R$ 1.427,64"

**Texto simplificado DEVE dizer:**
```
📋 **Danos Materiais: R$ 1.427,64**
- Reembolso de passagens aéreas: R$ 1.362,14
- Reembolso de alimentação durante a viagem: R$ 65,50
```

3️⃣ **NÃO simplifique demais:**
   ❌ ERRADO: "R$ 1.427,64 para cobrir prejuízos"
   ✅ CORRETO: Discriminação detalhada conforme exemplo acima

4️⃣ **Sempre calcule e mostre totais:**
   - Se há discriminação, mostre: subtotais + TOTAL GERAL
   - Use emojis para destacar: 📋 para categorias, 💰 para total

═══════════════════════════════════════════════════════════════════

**LINGUAGEM SIMPLES PARA RECURSOS (campo "explicacao_simples"):**
- NÃO use: "instâncias superiores", "revista por", "órgão superior"
- USE linguagem clara:
  * Se cabe recurso: "Outros juízes podem analisar esta decisão se você pedir um recurso"
  * Se não cabe: "Esta decisão é definitiva e não pode ser revista"
  * Se for mandado: "Mandados são ordens para cumprir algo, não decisões que você pode pedir para outros juízes analisarem"
  * Se consultar advogado: "Consulte um advogado ou a Defensoria Pública para saber se você pode pedir que outros juízes analisem"

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

            # Validar e limpar texto simplificado
            texto_simplificado, teve_vazamentos = validar_e_limpar_output(texto_simplificado)

            # Adicionar texto simplificado
            analise["texto_simplificado"] = texto_simplificado
            analise["modelo_usado"] = modelo_nome
            analise["perspectiva_aplicada"] = perspectiva  # 🔥 NOVO - registrar perspectiva
            analise["teve_vazamentos"] = teve_vazamentos  # 🔥 NOVO - flag de vazamentos

            # 🔥 VALIDAÇÃO DE DISCRIMINAÇÃO DE VALORES
            valores = analise.get("valores_principais", {})

            # Log para debug
            if valores.get("danos_materiais_discriminado") and len(valores.get("danos_materiais_discriminado", [])) > 1:
                logging.info(f"✅ Discriminação de danos materiais detectada: {len(valores['danos_materiais_discriminado'])} itens")

            if valores.get("danos_morais_discriminado") and len(valores.get("danos_morais_discriminado", [])) > 1:
                logging.info(f"✅ Discriminação de danos morais detectada: {len(valores['danos_morais_discriminado'])} beneficiários")

            # Validar discriminação usando função robusta
            passou_validacao, avisos_validacao = validar_discriminacao_valores(texto_simplificado, valores)
            analise["validacao_discriminacao"] = {
                "passou": passou_validacao,
                "avisos": avisos_validacao
            }

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

            # Usar lista para melhor performance em memória (evita concatenação repetida)
            partes_texto = []

            for i, page in enumerate(doc):
                try:
                    conteudo = page.get_text()

                    if conteudo.strip():
                        metadados["tem_texto"] = True
                        partes_texto.append(conteudo)
                    elif TESSERACT_AVAILABLE:
                        logging.info(f"Aplicando OCR na página {i+1}")
                        metadados["usou_ocr"] = True
                        metadados["paginas_com_ocr"].append(i+1)

                        pix = page.get_pixmap(dpi=150)
                        img_data = pix.tobytes()
                        conteudo_ocr, _ = processar_imagem_para_texto(img_data, 'PNG')
                        partes_texto.append(conteudo_ocr)

                except Exception as e:
                    logging.error(f"Erro ao processar página {i+1}: {e}")

            # Join é muito mais eficiente que concatenação repetida
            texto = "\n".join(partes_texto).strip()
            if not texto:
                raise ValueError("Nenhum texto extraído do PDF")

    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise

    return texto, metadados

# ============= GERAÇÃO DE PDF =============

def gerar_pdf_simplificado(texto, metadados=None, filename="documento_simplificado.pdf"):
    """Gera PDF com formatação aprimorada usando o novo gerador"""
    output_path = os.path.join(TEMP_DIR, filename)

    try:
        # Usar o novo gerador de PDF melhorado
        gerar_pdf_melhorado(texto, metadados, output_path)
        registrar_arquivo_temporario(output_path, session_id=session.get('session_id'))
        return output_path

    except Exception as e:
        logging.error(f"❌ Erro ao gerar PDF: {e}")
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
        # Filtrar prazos válidos (não null, não vazios)
        prazos_validos = []
        for p in analise_completa.get("prazos", []):
            if isinstance(p, dict) and p.get("prazo") and p.get("prazo") != "null":
                prazos_validos.append(p)

        dados_estruturados = {
            "numero_processo": extrair_numero_processo_regex(texto_original),
            "tipo_documento": tipo_doc,
            "partes": analise_completa.get("partes", {}),
            "autoridade": analise_completa.get("autoridade", {}),  # Agora retorna objeto completo com cargo e nome
            "valores": analise_completa.get("valores_principais", {}),
            "prazos": prazos_validos,  # Agora retorna objetos completos com destinatario e finalidade
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
    """Download do PDF com validação de segurança aprimorada"""
    pdf_basename = request.args.get('path')
    pdf_filename = request.args.get('filename', 'documento_simplificado.pdf')

    # Priorizar sempre os parâmetros da URL (evita race condition entre abas)
    if pdf_basename:
        # Validação de segurança: previne path traversal
        safe_basename = secure_filename(os.path.basename(pdf_basename))
        pdf_path = os.path.join(TEMP_DIR, safe_basename)

        # Validar que o arquivo está dentro do TEMP_DIR (segurança adicional)
        pdf_path_real = os.path.realpath(pdf_path)
        temp_dir_real = os.path.realpath(TEMP_DIR)
        if not pdf_path_real.startswith(temp_dir_real):
            logging.warning(f"⚠️ Tentativa de acesso fora do TEMP_DIR: {pdf_basename}")
            return jsonify({"erro": "Acesso não autorizado"}), 403
    else:
        # Fallback para session (legado - pode causar problemas com múltiplas abas)
        logging.warning("⚠️ Download usando session (legado) - múltiplas abas podem causar conflito")
        pdf_path = session.get('pdf_path')
        pdf_filename = session.get('pdf_filename', 'documento_simplificado.pdf')

    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"erro": "PDF não encontrado ou expirado"}), 404

    try:
        # Sanitizar o filename de download também
        safe_download_name = secure_filename(pdf_filename)
        return send_file(pdf_path, as_attachment=True, download_name=safe_download_name, mimetype='application/pdf')
    except Exception as e:
        logging.error(f"❌ Erro download: {e}")
        return jsonify({"erro": "Erro ao baixar arquivo"}), 500

@app.route("/feedback", methods=["POST"])
def feedback():
    """Registra feedback do usuário (LGPD compliant - só contador)"""
    try:
        data = request.get_json()
        tipo = data.get("tipo", "").lower()

        if tipo not in ["positivo", "negativo"]:
            return jsonify({"erro": "Tipo de feedback inválido"}), 400

        # Incrementar contador de feedback (LGPD compliant)
        try:
            database.incrementar_feedback(tipo)
            logging.info(f"✅ Feedback {tipo} registrado")
        except Exception as e:
            logging.error(f"❌ Erro ao registrar feedback: {e}")
            # Retorna sucesso mesmo se houver erro no banco
            # para não prejudicar a experiência do usuário

        return jsonify({
            "sucesso": True,
            "mensagem": "Obrigado pelo seu feedback!"
        })

    except Exception as e:
        logging.error(f"Erro ao processar feedback: {e}")
        return jsonify({"erro": "Erro ao processar feedback"}), 500

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
