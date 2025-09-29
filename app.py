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

# Modelos Gemini disponíveis
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
RATE_LIMIT = 10
cleanup_lock = threading.Lock()

# Cache de resultados processados
results_cache = {}
CACHE_EXPIRATION = 3600

# Estatísticas de uso dos modelos
model_usage_stats = {model["name"]: {"attempts": 0, "successes": 0, "failures": 0} for model in GEMINI_MODELS}

# ============================================================================
# SISTEMA DE DETECÇÃO DE TIPO DE DOCUMENTO JURÍDICO
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
        "descricao": "Decisão final do juiz que põe fim ao processo"
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
            r"des\.\s+",
            r"desembargador",
            r"relator",
            r"voto\s+do\s+relator",
            r"ementa",
            r"vistos,\s+relatados\s+e\s+discutidos",
            r"por\s+unanimidade",
            r"por\s+maioria",
            r"negaram\s+provimento",
            r"deram\s+provimento"
        ],
        "peso": 12,
        "descricao": "Decisão colegiada de tribunal"
    },
    "peticao_inicial": {
        "nome": "Petição Inicial",
        "icone": "📝",
        "padroes": [
            r"petição\s+inicial",
            r"excelentíssimo\s+senhor\s+doutor\s+juiz",
            r"exmo\.?\s+sr\.?\s+dr\.?\s+juiz",
            r"vem\s+à\s+presença\s+de\s+vossa\s+excelência",
            r"autor.*em\s+face\s+de.*réu",
            r"dos\s+fatos",
            r"do\s+direito",
            r"dos\s+pedidos",
            r"requer\s+a\s+citação",
            r"termos\s+em\s+que",
            r"pede\s+deferimento",
            r"nestes\s+termos,\s+pede\s+deferimento"
        ],
        "peso": 11,
        "descricao": "Documento que inicia um processo judicial"
    },
    "contestacao": {
        "nome": "Contestação",
        "icone": "🛡️",
        "padroes": [
            r"contestação",
            r"réu.*vem.*contestar",
            r"impugna\s+os\s+fatos",
            r"preliminarmente",
            r"da\s+improcedência",
            r"carência\s+de\s+ação",
            r"falta\s+de\s+interesse",
            r"ilegitimidade",
            r"no\s+mérito",
            r"defesa\s+do\s+réu",
            r"refuta",
            r"contesta\s+os\s+fatos"
        ],
        "peso": 9,
        "descricao": "Resposta do réu aos pedidos do autor"
    },
    "despacho": {
        "nome": "Despacho",
        "icone": "📋",
        "padroes": [
            r"^despacho",
            r"intime-se",
            r"cite-se",
            r"cumpra-se",
            r"manifestem-se",
            r"vista\s+às\s+partes",
            r"vista\s+ao\s+ministério\s+público",
            r"arquivem-se",
            r"registre-se",
            r"publique-se",
            r"intimem-se",
            r"^(intime|cite|cumpra|manifeste)",
        ],
        "peso": 7,
        "descricao": "Ordem judicial para andamento processual"
    },
    "decisao_interlocutoria": {
        "nome": "Decisão Interlocutória",
        "icone": "⚡",
        "padroes": [
            r"decisão\s+interlocutória",
            r"indefiro\s+o\s+pedido",
            r"defiro\s+o\s+pedido",
            r"tutela\s+de\s+urgência",
            r"tutela\s+antecipada",
            r"liminar",
            r"medida\s+liminar",
            r"suspendo",
            r"determino",
            r"concedo",
            r"agravo\s+de\s+instrumento"
        ],
        "peso": 8,
        "descricao": "Decisão judicial durante o processo, sem encerrar"
    },
    "recurso_apelacao": {
        "nome": "Recurso de Apelação",
        "icone": "📤",
        "padroes": [
            r"apelação",
            r"recurso\s+de\s+apelação",
            r"apelante",
            r"apelado",
            r"razões\s+de\s+apelação",
            r"inconformado",
            r"reforma\s+da\s+sentença",
            r"provimento\s+do\s+recurso",
            r"recorre\s+da\s+sentença"
        ],
        "peso": 10,
        "descricao": "Recurso contra sentença de primeiro grau"
    },
    "agravo": {
        "nome": "Agravo",
        "icone": "⚠️",
        "padroes": [
            r"agravo\s+de\s+instrumento",
            r"agravo\s+interno",
            r"agravante",
            r"agravado",
            r"razões\s+de\s+agravo",
            r"decisão\s+agravada"
        ],
        "peso": 9,
        "descricao": "Recurso contra decisões interlocutórias"
    },
    "intimacao": {
        "nome": "Intimação",
        "icone": "📨",
        "padroes": [
            r"^intimação",
            r"fica\s+intimado",
            r"ficam\s+intimados",
            r"intima-se",
            r"para\s+conhecimento",
            r"ciência\s+da\s+decisão",
            r"prazo\s+de.*dias",
            r"manifestar-se\s+no\s+prazo"
        ],
        "peso": 6,
        "descricao": "Comunicação oficial às partes"
    },
    "mandado": {
        "nome": "Mandado",
        "icone": "📜",
        "padroes": [
            r"^mandado",
            r"mandado\s+de\s+(citação|intimação|penhora|busca)",
            r"oficial\s+de\s+justiça",
            r"cumpra-se\s+o\s+mandado",
            r"certidão\s+do\s+oficial"
        ],
        "peso": 8,
        "descricao": "Ordem para oficial de justiça"
    },
    "alvara": {
        "nome": "Alvará",
        "icone": "🔓",
        "padroes": [
            r"^alvará",
            r"alvará\s+judicial",
            r"levantamento\s+de\s+valores",
            r"autorizo\s+o\s+levantamento",
            r"expedir\s+alvará"
        ],
        "peso": 7,
        "descricao": "Autorização judicial para atos específicos"
    },
    "certidao": {
        "nome": "Certidão",
        "icone": "📄",
        "padroes": [
            r"^certidão",
            r"certifico\s+que",
            r"certidão\s+de\s+trânsito\s+em\s+julgado",
            r"certidão\s+de\s+objeto\s+e\s+pé",
            r"certidão\s+de\s+decurso\s+de\s+prazo"
        ],
        "peso": 6,
        "descricao": "Documento que certifica fatos processuais"
    },
    "embargo_declaracao": {
        "nome": "Embargos de Declaração",
        "icone": "❓",
        "padroes": [
            r"embargos\s+de\s+declaração",
            r"embargante",
            r"embargado",
            r"obscuridade",
            r"contradição",
            r"omissão",
            r"esclarecer\s+a\s+decisão"
        ],
        "peso": 8,
        "descricao": "Recurso para esclarecer decisão"
    }
}

def detectar_tipo_documento(texto):
    """
    Detecta o tipo de documento jurídico através de análise de padrões textuais.
    Retorna tipo detectado e nível de confiança.
    """
    texto_lower = texto.lower()
    texto_normalizado = re.sub(r'\s+', ' ', texto_lower)
    
    pontuacoes = {}
    
    for tipo, info in TIPOS_DOCUMENTOS.items():
        pontos = 0
        padroes_encontrados = []
        
        for padrao in info["padroes"]:
            matches = re.findall(padrao, texto_normalizado, re.IGNORECASE)
            if matches:
                # Cada match aumenta a pontuação
                pontos += len(matches) * info["peso"]
                padroes_encontrados.append(padrao)
        
        if pontos > 0:
            pontuacoes[tipo] = {
                "pontos": pontos,
                "info": info,
                "padroes": padroes_encontrados
            }
    
    if not pontuacoes:
        return {
            "tipo": "documento_generico",
            "nome": "Documento Jurídico",
            "icone": "📑",
            "confianca": 0,
            "descricao": "Documento jurídico não classificado",
            "padroes_encontrados": []
        }
    
    # Ordenar por pontuação
    tipo_detectado = max(pontuacoes.items(), key=lambda x: x[1]["pontos"])
    tipo_id = tipo_detectado[0]
    dados = tipo_detectado[1]
    
    # Calcular confiança (0-100)
    max_pontos_possiveis = len(TIPOS_DOCUMENTOS[tipo_id]["padroes"]) * TIPOS_DOCUMENTOS[tipo_id]["peso"] * 3
    confianca = min(100, int((dados["pontos"] / max_pontos_possiveis) * 100))
    
    return {
        "tipo": tipo_id,
        "nome": dados["info"]["nome"],
        "icone": dados["info"]["icone"],
        "confianca": confianca,
        "descricao": dados["info"]["descricao"],
        "padroes_encontrados": dados["padroes"][:5]  # Primeiros 5 padrões
    }

# ============================================================================
# PROMPTS ESPECÍFICOS POR TIPO DE DOCUMENTO
# ============================================================================

PROMPTS_POR_TIPO = {
    "sentenca": """**INSTRUÇÕES CRÍTICAS - SENTENÇA JUDICIAL:**

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
   - "Carência de ação"
   - "Ilegitimidade"

3. **RESUMO EXECUTIVO**
   [Ícone apropriado] **[VITÓRIA TOTAL/DERROTA/VITÓRIA PARCIAL/EXTINÇÃO]**
   
   **Em uma frase simples:** [Explicar o resultado em linguagem muito clara]

4. **O QUE ACONTECEU**
   [Explicar em 3-5 linhas o contexto: qual era a disputa]

5. **O QUE O JUIZ DECIDIU**
   [Detalhar a decisão em linguagem simples, parágrafo por parágrafo]
   - Fundamentos principais
   - Cada pedido e se foi aceito ou negado

6. **VALORES E OBRIGAÇÕES** 💰
   • Valor da causa: R$ [se houver]
   • Valores que o AUTOR vai receber: R$ [detalhar]
   • Valores que o RÉU tem que pagar: R$ [detalhar]
   • Honorários advocatícios: [percentual] = R$ [valor]
   • Custas processuais: [quem paga]
   • Correção monetária: [desde quando]
   • Juros: [percentual e desde quando]

7. **PRAZOS IMPORTANTES** ⏰
   • Prazo para recurso: [geralmente 15 dias]
   • Outras obrigações com prazo

8. **MINI DICIONÁRIO** 📚
   [Apenas termos jurídicos QUE APARECEM no texto]
   • **Termo:** Explicação simples
   
9. **PODE RECORRER?**
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
""",

    "acordao": """**INSTRUÇÕES CRÍTICAS - ACÓRDÃO:**

Você está analisando um ACÓRDÃO. Este é a decisão COLEGIADA de um tribunal.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 🏛️
   - Tipo: Acórdão
   - Tribunal: [identificar - TJ, STJ, TST, etc]
   - Órgão julgador: [Câmara, Turma, etc]
   - Relator: [Des. Nome completo]
   - Número do processo/recurso: [exato]
   - Partes:
     * Recorrente: [quem recorreu]
     * Recorrido: [contra quem]

2. **EMENTA** 📋
   [Transcrever ou resumir a ementa se houver]

3. **RESULTADO DO JULGAMENTO** 🎯
   
   ✅ **RECURSO PROVIDO** (recorrente ganhou):
   - "DERAM PROVIMENTO ao recurso"
   - "DÃO PROVIMENTO"
   - Decisão anterior foi reformada
   
   ❌ **RECURSO NEGADO** (recorrente perdeu):
   - "NEGARAM PROVIMENTO"
   - "NEGAM PROVIMENTO"
   - Decisão anterior foi mantida
   
   ⚠️ **PROVIMENTO PARCIAL**:
   - "DERAM PARCIAL PROVIMENTO"
   - Decisão foi parcialmente reformada

4. **VOTAÇÃO**
   • Tipo: [Unanimidade/Maioria]
   • Placar: [se for por maioria]
   • Votos vencidos: [se houver]

5. **RESUMO EXECUTIVO**
   [Ícone] **[RESULTADO]**
   **Em linguagem simples:** [explicar o que mudou ou se manteve]

6. **CONTEXTO**
   [Explicar qual era a disputa e por que recorreram]

7. **FUNDAMENTOS DA DECISÃO**
   [Principais argumentos do relator em linguagem simples]

8. **EFEITOS PRÁTICOS**
   [O que muda na prática com esta decisão]
   • Para o recorrente: [consequências]
   • Para o recorrido: [consequências]

9. **VALORES** 💰 (se aplicável)
   • Valores envolvidos: R$ [se houver]
   • Honorários advocatícios recursais: [se houver]

10. **PODE RECORRER AINDA?**
    • Recursos cabíveis: [Embargos de Declaração, REsp, RE]
    • Prazos: [informar]

**MINI DICIONÁRIO** 📚
[Termos que aparecem no acórdão]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente precedentes ou jurisprudência
2. ❌ NUNCA adicione interpretações não explícitas
3. ✅ Transcreva nomes exatos de desembargadores
4. ✅ Se houver divergência entre votos, explique claramente
5. ✅ Indique se há decisão monocrática ou colegiada

**TEXTO DO ACÓRDÃO:**
""",

    "peticao_inicial": """**INSTRUÇÕES CRÍTICAS - PETIÇÃO INICIAL:**

Você está analisando uma PETIÇÃO INICIAL. Este é o documento que INICIA um processo.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📝
   - Tipo: Petição Inicial
   - Autor(es): [nome completo]
   - Réu(s): [nome completo]
   - Tipo de ação: [ex: Ação de Cobrança, Indenização, etc]
   - Valor da causa: R$ [exato]
   - Advogado(a): [nome e OAB]

2. **RESUMO EXECUTIVO**
   📝 **PEDIDO INICIAL**
   **Em linguagem simples:** [O que o autor está pedindo ao juiz em uma frase]

3. **O QUE ACONTECEU** (DOS FATOS)
   [Resumir a história contada pelo autor em linguagem clara]
   - Quando começou o problema
   - O que o réu fez ou deixou de fazer
   - Por que o autor se sente prejudicado

4. **O QUE O AUTOR ESTÁ PEDINDO** 🎯
   **Pedidos principais:**
   1. [Pedido 1 em linguagem simples]
   2. [Pedido 2 em linguagem simples]
   3. [etc]
   
   **Pedidos secundários:**
   • [Tutela de urgência, se houver]
   • [Outros pedidos]

5. **VALORES PEDIDOS** 💰
   • Valor principal: R$ [especificar]
   • Danos morais: R$ [se houver]
   • Danos materiais: R$ [se houver]
   • Lucros cessantes: R$ [se houver]
   • Total: R$ [soma]

6. **ARGUMENTOS JURÍDICOS** (DO DIREITO)
   [Principais leis e argumentos citados, em linguagem simples]
   • [Argumento 1]
   • [Argumento 2]

7. **PROVAS APRESENTADAS** 📎
   [Listar documentos e provas que acompanham]
   • [Prova 1]
   • [Prova 2]

8. **PRÓXIMOS PASSOS** ⏭️
   • O juiz vai analisar a petição
   • O réu será citado para se defender
   • Prazo estimado para resposta: [se mencionado]

**MINI DICIONÁRIO** 📚
[Termos jurídicos que aparecem]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente fatos não narrados
2. ❌ NUNCA adicione valores não mencionados
3. ❌ NUNCA especule sobre chances de sucesso
4. ✅ Deixe claro que esta é apenas a versão do AUTOR
5. ✅ Transcreva valores exatos
6. ✅ Esta é apenas a ABERTURA do processo, não há decisão ainda

**TEXTO DA PETIÇÃO INICIAL:**
""",

    "contestacao": """**INSTRUÇÕES CRÍTICAS - CONTESTAÇÃO:**

Você está analisando uma CONTESTAÇÃO. Este é a DEFESA do réu.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 🛡️
   - Tipo: Contestação
   - Réu/Contestante: [nome completo]
   - Autor: [nome completo]
   - Processo: [número]
   - Advogado(a) do réu: [nome e OAB]

2. **RESUMO EXECUTIVO**
   🛡️ **DEFESA DO RÉU**
   **Em linguagem simples:** [O que o réu está argumentando em uma frase]

3. **PRELIMINARES** (se houver) ⚠️
   [Questões processuais antes de entrar no mérito]
   • [Preliminar 1 - ex: ilegitimidade]
   • [Preliminar 2 - ex: falta de interesse]
   
   **O que isso significa:** [Explicar em linguagem simples]

4. **DEFESA NO MÉRITO** 🎯
   [A versão do réu sobre os fatos]
   
   **O réu nega:**
   • [Fato 1 que o réu contesta]
   • [Fato 2 que o réu contesta]
   
   **O réu afirma:**
   • [Versão do réu sobre o ocorrido]
   • [Justificativas apresentadas]

5. **ARGUMENTOS JURÍDICOS**
   [Leis e argumentos do réu em linguagem simples]
   • [Argumento 1]
   • [Argumento 2]

6. **PROVAS DA DEFESA** 📎
   [Documentos que o réu apresentou]
   • [Prova 1]
   • [Prova 2]

7. **PEDIDO DO RÉU**
   O réu pede que o juiz:
   • [Pedido 1 - geralmente improcedência]
   • [Outros pedidos]

8. **COMPARAÇÃO** ⚖️
   
   | AUTOR DIZ | RÉU DIZ |
   |-----------|---------|
   | [versão do autor] | [versão do réu] |

9. **PRÓXIMOS PASSOS** ⏭️
   • Autor pode se manifestar sobre a contestação (réplica)
   • Juiz pode designar audiência
   • Processo segue para decisão

**MINI DICIONÁRIO** 📚
[Termos jurídicos]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA tome partido (autor ou réu)
2. ❌ NUNCA invente argumentos não apresentados
3. ✅ Deixe claro que esta é a versão do RÉU
4. ✅ Mostre que há duas versões diferentes
5. ✅ Não há decisão ainda, apenas defesa

**TEXTO DA CONTESTAÇÃO:**
""",

    "despacho": """**INSTRUÇÕES CRÍTICAS - DESPACHO:**

Você está analisando um DESPACHO. Este é uma ordem simples do juiz para andamento.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📋
   - Tipo: Despacho
   - Processo: [número]
   - Juiz(a): [se identificado]
   - Data: [se consta]

2. **RESUMO EXECUTIVO**
   📋 **DESPACHO - ORDEM DE ANDAMENTO**
   **Em linguagem simples:** [O que o juiz está mandando fazer]

3. **ORDEM DADA** 🎯
   [Explicar em linguagem simples o que foi determinado]
   
   Exemplos:
   • Se "Intime-se": As partes serão comunicadas
   • Se "Cite-se": O réu será chamado ao processo
   • Se "Manifeste-se": Alguém deve responder algo
   • Se "Arquive-se": Processo será arquivado

4. **PARA QUEM É A ORDEM**
   • Direcionada a: [autor/réu/ambos/cartório/oficial]
   • Sobre: [assunto do despacho]

5. **PRAZO** ⏰ (se houver)
   • Prazo: [X dias]
   • Para fazer: [ação específica]

6. **O QUE ISSO SIGNIFICA**
   [Explicar em linguagem muito simples o impacto prático]

7. **PRÓXIMOS PASSOS** ⏭️
   [O que vai acontecer agora]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA interprete além do que está escrito
2. ❌ Despacho NÃO é decisão final
3. ✅ É apenas ordem de andamento processual
4. ✅ Seja breve e direto

**TEXTO DO DESPACHO:**
""",

    "decisao_interlocutoria": """**INSTRUÇÕES CRÍTICAS - DECISÃO INTERLOCUTÓRIA:**

Você está analisando uma DECISÃO INTERLOCUTÓRIA. É uma decisão DURANTE o processo, NÃO é a sentença final.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** ⚡
   - Tipo: Decisão Interlocutória
   - Processo: [número]
   - Juiz(a): [nome]
   - Data: [se consta]
   - Sobre: [tema da decisão]

2. **RESUMO EXECUTIVO**
   ⚡ **DECISÃO DURANTE O PROCESSO**
   **Em linguagem simples:** [O que o juiz decidiu]

3. **O QUE FOI PEDIDO**
   [Explicar o pedido que estava sendo analisado]
   • Quem pediu: [autor/réu]
   • O que pediu: [resumo simples]

4. **O QUE O JUIZ DECIDIU** 🎯
   
   ✅ **DEFERIDO** (pedido aceito):
   [Se o juiz aceitou o pedido]
   
   ❌ **INDEFERIDO** (pedido negado):
   [Se o juiz negou o pedido]
   
   ⚠️ **DEFERIDO PARCIALMENTE**:
   [Se aceitou só parte]

5. **FUNDAMENTOS**
   [Por que o juiz decidiu assim, em linguagem simples]

6. **EFEITOS PRÁTICOS**
   [O que muda agora com essa decisão]
   • Para o autor: [consequências]
   • Para o réu: [consequências]

7. **VALORES** 💰 (se aplicável)
   [Se envolve valores ou bloqueios]

8. **PRAZOS** ⏰ (se houver)
   [Obrigações com prazo]

9. **IMPORTANTE** ⚠️
   • Esta NÃO é a decisão final do processo
   • O processo continua
   • É possível recorrer: [Agravo de Instrumento]

**MINI DICIONÁRIO** 📚
[Termos que aparecem]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA confunda com sentença final
2. ❌ Deixe claro que é decisão PARCIAL
3. ✅ Explique que o processo continua
4. ✅ Mencione possibilidade de recurso (agravo)

**TEXTO DA DECISÃO INTERLOCUTÓRIA:**
""",

    "recurso_apelacao": """**INSTRUÇÕES CRÍTICAS - RECURSO DE APELAÇÃO:**

Você está analisando um RECURSO DE APELAÇÃO. É o pedido de revisão de uma sentença.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📤
   - Tipo: Recurso de Apelação
   - Apelante: [quem está recorrendo]
   - Apelado: [contra quem]
   - Processo de origem: [número]
   - Sentença recorrida: [resumo breve]
   - Advogado(a): [nome e OAB]

2. **RESUMO EXECUTIVO**
   📤 **RECURSO CONTRA SENTENÇA**
   **Em linguagem simples:** [O que o apelante quer mudar]

3. **O QUE ACONTECEU ANTES**
   [Resumir a sentença que está sendo contestada]
   • Decisão do juiz: [resultado]
   • Por que o apelante ficou insatisfeito: [razão]

4. **O QUE O APELANTE PEDE** 🎯
   **Pedido principal:**
   [O que quer que o tribunal mude]
   
   **Pedidos específicos:**
   • [Pedido 1]
   • [Pedido 2]
   • [Reforma total ou parcial]

5. **ARGUMENTOS DO RECURSO**
   [Principais razões do apelante em linguagem simples]
   
   **Erros apontados na sentença:**
   • [Erro 1 alegado]
   • [Erro 2 alegado]
   
   **Provas que diz terem sido ignoradas:**
   • [Prova 1]
   • [Prova 2]

6. **NOVOS ELEMENTOS** (se houver)
   [Fatos ou provas novas apresentadas]

7. **VALORES** 💰
   • Valor envolvido: R$ [se aplicável]
   • Mudança de valor pedida: [se aplicável]

8. **PRÓXIMOS PASSOS** ⏭️
   • O apelado pode responder (contrarrazões)
   • Tribunal vai julgar: [TJ/TRF identificado]
   • Tempo estimado: [se mencionado]

9. **IMPORTANTE** ⚠️
   • Este é apenas o PEDIDO de revisão
   • NÃO há decisão ainda
   • A sentença pode ser mantida ou reformada

**MINI DICIONÁRIO** 📚
[Termos jurídicos]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA especule sobre chances de sucesso
2. ❌ NÃO invente erros não apontados
3. ✅ Deixe claro que é só o pedido, não a decisão
4. ✅ Explique que o tribunal ainda vai julgar

**TEXTO DO RECURSO DE APELAÇÃO:**
""",

    "intimacao": """**INSTRUÇÕES CRÍTICAS - INTIMAÇÃO:**

Você está analisando uma INTIMAÇÃO. É uma comunicação oficial às partes.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📨
   - Tipo: Intimação
   - Processo: [número]
   - Intimado: [quem está sendo comunicado]
   - Data: [data da intimação]

2. **RESUMO EXECUTIVO**
   📨 **COMUNICAÇÃO OFICIAL**
   **Em linguagem simples:** [Do que se trata]

3. **CONTEÚDO DA INTIMAÇÃO** 🎯
   [Explicar sobre o que é a comunicação]
   
   Exemplos:
   • Ciência de decisão
   • Chamado para manifestação
   • Informação sobre andamento
   • Cumprimento de obrigação

4. **O QUE VOCÊ PRECISA FAZER** (se aplicável)
   [Ação necessária em resposta]
   • Ação: [o que fazer]
   • Como: [instruções]

5. **PRAZO** ⏰
   • Prazo: [X dias úteis]
   • A partir de: [data inicial]
   • Até: [data final, se calculável]
   • Para: [ação específica]

6. **CONSEQUÊNCIAS** ⚠️
   [O que acontece se não cumprir o prazo]
   • Se não cumprir: [consequência]

7. **IMPORTANTE**
   [Informações críticas]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente prazos não mencionados
2. ✅ Seja claro sobre o que precisa ser feito
3. ✅ Destaque prazos com ênfase
4. ✅ Explique consequências se houver

**TEXTO DA INTIMAÇÃO:**
""",

    "documento_generico": """**INSTRUÇÕES CRÍTICAS - DOCUMENTO JURÍDICO:**

Você está analisando um DOCUMENTO JURÍDICO que não se encaixa nas categorias específicas.

**ESTRUTURA OBRIGATÓRIA:**

1. **IDENTIFICAÇÃO** 📑
   - Tipo: [Tentar identificar o tipo mais próximo]
   - Processo: [se houver]
   - Partes: [se identificáveis]

2. **RESUMO EXECUTIVO**
   📑 **DOCUMENTO JURÍDICO**
   **Em linguagem simples:** [Objetivo do documento]

3. **CONTEÚDO PRINCIPAL**
   [Explicar o conteúdo em linguagem simples]

4. **INFORMAÇÕES IMPORTANTES**
   [Extrair pontos relevantes]

5. **PRAZOS** ⏰ (se houver)
   [Listar prazos mencionados]

6. **VALORES** 💰 (se houver)
   [Valores mencionados]

7. **MINI DICIONÁRIO** 📚
   [Termos jurídicos que aparecem]

---

**REGRAS ABSOLUTAS:**
1. ❌ NUNCA invente informações
2. ❌ NUNCA especule sobre decisões futuras
3. ✅ Admita se algo não estiver claro
4. ✅ Transcreva informações exatas

**TEXTO DO DOCUMENTO:**
"""
}

def gerar_prompt_completo(texto_original, tipo_detectado):
    """
    Gera o prompt completo baseado no tipo de documento detectado
    """
    tipo = tipo_detectado["tipo"]
    
    # Cabeçalho comum
    cabecalho = f"""**CONTEXTO DO DOCUMENTO:**
Tipo detectado: {tipo_detectado['nome']} {tipo_detectado['icone']}
Confiança: {tipo_detectado['confianca']}%

**⚠️ REGRAS CRÍTICAS GERAIS - LEIA COM ATENÇÃO:**

1. **NUNCA INVENTE INFORMAÇÕES**
   - Use APENAS o que está escrito no texto original
   - Se algo não está no texto, escreva "Não informado no documento"
   - NUNCA adicione valores, datas ou fatos não mencionados
   - NUNCA especule sobre resultados ou decisões futuras

2. **SEJA PRECISO COM DADOS**
   - Transcreva nomes EXATAMENTE como aparecem
   - Copie números de processo EXATAMENTE
   - Reproduza valores EXATAMENTE (não arredonde)
   - Mantenha datas no formato original

3. **LINGUAGEM SIMPLES**
   - Máximo 20 palavras por frase
   - Substitua jargão por palavras comuns
   - Explique siglas na primeira vez
   - Use exemplos quando ajudar a entender

4. **FORMATAÇÃO**
   - Use ícones para destacar seções
   - Organize em tópicos claros
   - Destaque informações críticas
   - Mantenha estrutura lógica

5. **MINI DICIONÁRIO**
   - Inclua APENAS termos que aparecem no texto
   - Dê explicações simples e práticas
   - Máximo 10 termos

---

"""
    
    # Prompt específico do tipo
    prompt_especifico = PROMPTS_POR_TIPO.get(tipo, PROMPTS_POR_TIPO["documento_generico"])
    
    # Rodapé
    rodape = f"""

---

**VERIFICAÇÃO FINAL ANTES DE RESPONDER:**
✓ Usei apenas informações do texto original?
✓ Não inventei nenhum dado?
✓ Transcrevi nomes e números exatamente?
✓ Expliquei em linguagem simples?
✓ Deixei claro o que não está no documento?

*Processado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}*
*Este é um resumo simplificado. Consulte seu advogado para orientações específicas.*
"""
    
    return cabecalho + prompt_especifico + "\n" + texto_original + rodape

# ============================================================================
# FUNÇÕES AUXILIARES (mantidas do código original)
# ============================================================================

def verificar_tesseract():
    """Verifica se o Tesseract está disponível e configurado"""
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
                        return jsonify({"erro": "Limite de requisições excedido. Tente novamente em alguns minutos."}), 429
                    request_counts[ip] = (count + 1, first_request)
                else:
                    request_counts[ip] = (1, now)
            else:
                request_counts[ip] = (1, now)
        
        return f(*args, **kwargs)
    return decorated_function

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
    """Executa OCR com múltiplas configurações"""
    
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
            continue
    
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
                raise ValueError("Nenhum texto foi extraído do PDF")
                
    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise
    
    return texto, metadados

def analisar_complexidade_texto(texto):
    """Analisa a complexidade do texto"""
    complexidade = {
        "caracteres": len(texto),
        "palavras": len(texto.split()),
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
    
    if complexidade["caracteres"] > 10000 or complexidade["termos_tecnicos"] > 20 or complexidade["citacoes"] > 15:
        complexidade["nivel"] = "alto"
    elif complexidade["caracteres"] > 5000 or complexidade["termos_tecnicos"] > 10 or complexidade["citacoes"] > 8:
        complexidade["nivel"] = "médio"
    
    return complexidade

def escolher_modelo_gemini(complexidade, tentativa=0):
    """Escolhe o modelo Gemini mais apropriado"""
    if complexidade["nivel"] == "baixo" and tentativa == 0:
        return GEMINI_MODELS[0]
    elif complexidade["nivel"] == "médio" or tentativa == 1:
        return GEMINI_MODELS[1]
    else:
        return GEMINI_MODELS[2] if tentativa < len(GEMINI_MODELS) else GEMINI_MODELS[-1]

def simplificar_com_gemini(texto, max_retries=3):
    """Chama a API do Gemini com detecção de tipo de documento"""
    
    MAX_CHUNK_SIZE = 30000
    
    if len(texto) > MAX_CHUNK_SIZE:
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
        
        texto_principal = chunks[-1] if "DISPOSITIVO" in chunks[-1] or "JULGO" in chunks[-1] else chunks[0]
        
        if len(chunks) > 1:
            texto_contexto = "\n\n[CONTEXTO ADICIONAL DO PROCESSO]\n"
            for i, chunk in enumerate(chunks):
                if chunk != texto_principal:
                    texto_contexto += f"\nParte {i+1}: " + chunk[:500] + "...\n"
            texto = texto_principal + texto_contexto
    
    # DETECTAR TIPO DE DOCUMENTO
    tipo_detectado = detectar_tipo_documento(texto)
    logging.info(f"Tipo detectado: {tipo_detectado['nome']} (confiança: {tipo_detectado['confianca']}%)")
    
    # Cache
    texto_hash = hashlib.md5(texto.encode()).hexdigest()
    if texto_hash in results_cache:
        cache_entry = results_cache[texto_hash]
        if time.time() - cache_entry["timestamp"] < CACHE_EXPIRATION:
            logging.info(f"Resultado encontrado no cache")
            return cache_entry["result"], None, tipo_detectado
    
    # Gerar prompt específico para o tipo
    prompt_completo = gerar_prompt_completo(texto, tipo_detectado)
    
    complexidade = analisar_complexidade_texto(texto)
    logging.info(f"Complexidade: {complexidade}")
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    
    errors = []
    
    for tentativa in range(len(GEMINI_MODELS)):
        modelo = escolher_modelo_gemini(complexidade, tentativa)
        logging.info(f"Tentativa {tentativa + 1}: Usando modelo {modelo['name']}")
        
        model_usage_stats[modelo["name"]]["attempts"] += 1
        
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
                "temperature": 0.2,  # Reduzido para maior precisão
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
                        
                        results_cache[texto_hash] = {
                            "result": texto_simplificado,
                            "timestamp": time.time(),
                            "modelo": modelo["name"],
                            "tipo_documento": tipo_detectado
                        }
                        
                        model_usage_stats[modelo["name"]]["successes"] += 1
                        logging.info(f"Sucesso com {modelo['name']} em {elapsed}s")
                        
                        return texto_simplificado, None, tipo_detectado
                    else:
                        errors.append(f"{modelo['name']}: Resposta vazia")
                        
                elif response.status_code == 429:
                    errors.append(f"{modelo['name']}: Limite de requisições excedido")
                    model_usage_stats[modelo["name"]]["failures"] += 1
                    break
                    
                elif response.status_code == 400:
                    errors.append(f"{modelo['name']}: Requisição inválida")
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
        
        if tentativa < len(GEMINI_MODELS) - 1:
            time.sleep(1)
    
    error_summary = " | ".join(errors)
    logging.error(f"Todos os modelos falharam: {error_summary}")
    return None, f"Erro ao processar. Tentativas: {error_summary}", tipo_detectado

def gerar_pdf_simplificado(texto, metadados=None, tipo_documento=None, filename="documento_simplificado.pdf"):
    """Gera PDF com informações do tipo de documento"""
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
        
        # Cabeçalho com tipo de documento
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_esq, y, "Documento em Linguagem Simples")
        y -= 30
        
        # Tipo de documento detectado
        if tipo_documento:
            c.setFont("Helvetica-Bold", 12)
            c.setFillColorRGB(0.2, 0.4, 0.8)
            tipo_text = f"{tipo_documento.get('icone', '')} {tipo_documento.get('nome', 'Documento Jurídico')}"
            c.drawString(margem_esq, y, tipo_text)
            y -= 15
            
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(margem_esq, y, f"Confiança da detecção: {tipo_documento.get('confianca', 0)}%")
            y -= 20
        
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
        
        # Processar texto
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0, 0, 0)
        
        linhas = texto.split('\n')
        
        for linha in linhas:
            if not linha.strip():
                y -= altura_linha
                continue
            
            if any(icon in linha for icon in ['✅', '❌', '⚠️', '📊', '📑', '⚖️', '💰', '📅', '💡', '🏛️', '📝', '🛡️', '📋', '⚡', '📤', '📨']):
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

def analisar_resultado_judicial(texto, tipo_documento=None):
    """Analisa o resultado com base no tipo de documento"""
    analise = {
        "tipo_resultado": "indefinido",
        "tem_valores": False,
        "tem_prazos": False,
        "tem_recursos": False,
        "sentimento": "neutro",
        "palavras_chave": [],
        "tipo_documento": tipo_documento.get("nome") if tipo_documento else "Não identificado",
        "confianca_tipo": tipo_documento.get("confianca") if tipo_documento else 0
    }
    
    texto_lower = texto.lower()
    
    # Análise específica por tipo
    if tipo_documento:
        tipo = tipo_documento.get("tipo")
        
        if tipo == "sentenca":
            if "✅" in texto or "vitória" in texto_lower or "procedente" in texto_lower:
                analise["tipo_resultado"] = "vitoria"
                analise["sentimento"] = "positivo"
            elif "❌" in texto or "derrota" in texto_lower or "improcedente" in texto_lower:
                analise["tipo_resultado"] = "derrota"
                analise["sentimento"] = "negativo"
            elif "⚠️" in texto or "parcial" in texto_lower:
                analise["tipo_resultado"] = "parcial"
                analise["sentimento"] = "neutro"
        
        elif tipo == "acordao":
            if "provimento" in texto_lower and "negaram" not in texto_lower:
                analise["tipo_resultado"] = "recurso_provido"
                analise["sentimento"] = "positivo"
            elif "negaram provimento" in texto_lower:
                analise["tipo_resultado"] = "recurso_negado"
                analise["sentimento"] = "negativo"
        
        elif tipo in ["peticao_inicial", "contestacao", "recurso_apelacao"]:
            analise["tipo_resultado"] = "aguardando_decisao"
            analise["sentimento"] = "neutro"
        
        elif tipo == "decisao_interlocutoria":
            if "deferido" in texto_lower or "concedo" in texto_lower:
                analise["tipo_resultado"] = "deferido"
                analise["sentimento"] = "positivo"
            elif "indeferido" in texto_lower or "nego" in texto_lower:
                analise["tipo_resultado"] = "indeferido"
                analise["sentimento"] = "negativo"
    
    # Verificar presença de elementos importantes
    if "r$" in texto_lower or "valor" in texto_lower or "💰" in texto:
        analise["tem_valores"] = True
        analise["palavras_chave"].append("valores")
    
    if "prazo" in texto_lower or "dias" in texto_lower or "📅" in texto or "⏰" in texto:
        analise["tem_prazos"] = True
        analise["palavras_chave"].append("prazos")
    
    if "recurso" in texto_lower or "apelação" in texto_lower or "agravo" in texto_lower:
        analise["tem_recursos"] = True
        analise["palavras_chave"].append("recursos")
    
    return analise

# ============================================================================
# ROTAS DA APLICAÇÃO
# ============================================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/processar", methods=["POST"])
@rate_limit
def processar():
    """Processa upload de PDF ou imagem com detecção de tipo"""
    try:
        # Verificação inicial
        if 'file' not in request.files:
            logging.error("Nenhum arquivo no request")
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400
            
        file = request.files['file']
        if file.filename == '':
            logging.error("Nome de arquivo vazio")
            return jsonify({"erro": "Nenhum arquivo selecionado"}), 400
        
        logging.info(f"Arquivo recebido: {file.filename}")
        
        # Validar extensão
        if not allowed_file(file.filename):
            logging.error(f"Extensão inválida: {file.filename}")
            return jsonify({"erro": "Formato inválido. Aceitos: PDF, PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP"}), 400
        
        # Verificar tamanho
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        logging.info(f"Tamanho do arquivo: {size} bytes ({size/1024:.2f} KB)")
        
        if size > MAX_FILE_SIZE:
            logging.error(f"Arquivo muito grande: {size} bytes")
            return jsonify({"erro": f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE//1024//1024}MB"}), 400
        
        if size == 0:
            logging.error("Arquivo vazio")
            return jsonify({"erro": "Arquivo está vazio"}), 400
        
        # Ler arquivo
        try:
            file_bytes = file.read()
            logging.info(f"Bytes lidos: {len(file_bytes)}")
        except Exception as e:
            logging.error(f"Erro ao ler arquivo: {e}")
            return jsonify({"erro": f"Erro ao ler arquivo: {str(e)}"}), 400
        
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        file_hash = hashlib.md5(file_bytes).hexdigest()
        logging.info(f"Processando: {secure_filename(file.filename)} - Extensão: {file_extension} - Hash: {file_hash}")
        
        # Processar baseado no tipo
        texto_original = None
        metadados = {}
        
        try:
            if file_extension == 'pdf':
                logging.info("Iniciando extração de PDF")
                texto_original, metadados = extrair_texto_pdf(file_bytes)
                logging.info(f"PDF processado - {metadados.get('total_paginas', 0)} páginas - {len(texto_original)} caracteres")
                
            elif file_extension in ALLOWED_IMAGE_EXTENSIONS:
                logging.info(f"Iniciando OCR para imagem {file_extension}")
                
                if not TESSERACT_AVAILABLE:
                    logging.error("Tesseract não disponível")
                    return jsonify({
                        "erro": "OCR não está disponível neste servidor",
                        "detalhes": "O Tesseract OCR não foi encontrado. Entre em contato com o administrador.",
                        "diagnostico": {
                            "tesseract_available": False,
                            "opencv_available": CV2_AVAILABLE
                        }
                    }), 500
                
                try:
                    texto_original, metadados = processar_imagem_para_texto(file_bytes, file_extension.upper())
                    logging.info(f"OCR concluído - Qualidade: {metadados.get('qualidade_ocr')} - {len(texto_original)} caracteres")
                    
                    if metadados.get("qualidade_ocr") == "baixa":
                        texto_original = "[AVISO: Qualidade do OCR baixa. Alguns trechos podem estar incorretos.]\n\n" + texto_original
                        
                except ValueError as ve:
                    logging.error(f"Erro no OCR: {ve}")
                    return jsonify({
                        "erro": str(ve),
                        "detalhes": "Não foi possível extrair texto da imagem"
                    }), 500
                    
            else:
                logging.error(f"Tipo não suportado: {file_extension}")
                return jsonify({"erro": "Tipo de arquivo não suportado"}), 400
            
        except Exception as e:
            logging.error(f"Erro na extração de texto: {str(e)}", exc_info=True)
            return jsonify({
                "erro": f"Erro ao extrair texto: {str(e)}",
                "tipo": file_extension,
                "detalhes": "Verifique se o arquivo não está corrompido"
            }), 500
        
        # Validar texto extraído
        if not texto_original:
            logging.error("Nenhum texto extraído")
            return jsonify({"erro": "Não foi possível extrair texto do arquivo"}), 400
            
        if len(texto_original.strip()) < 10:
            logging.error(f"Texto muito curto: {len(texto_original)} caracteres")
            return jsonify({"erro": "Arquivo não contém texto suficiente para processar"}), 400
        
        logging.info(f"Texto extraído com sucesso: {len(texto_original)} caracteres")
        
        # Simplificar com Gemini
        try:
            logging.info("Iniciando simplificação com Gemini")
            texto_simplificado, erro, tipo_documento = simplificar_com_gemini(texto_original)
            
            if erro:
                logging.error(f"Erro no Gemini: {erro}")
                return jsonify({"erro": f"Erro na IA: {erro}"}), 500
            
            if not texto_simplificado:
                logging.error("Gemini retornou texto vazio")
                return jsonify({"erro": "A IA não conseguiu processar o texto"}), 500
                
            logging.info(f"Simplificação concluída - Tipo: {tipo_documento.get('nome', 'N/A')} - {len(texto_simplificado)} caracteres")
            
        except Exception as e:
            logging.error(f"Erro na simplificação: {str(e)}", exc_info=True)
            return jsonify({
                "erro": f"Erro ao simplificar: {str(e)}",
                "detalhes": "Problema na comunicação com a IA"
            }), 500
        
        # Gerar PDF
        try:
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
            pdf_path = gerar_pdf_simplificado(texto_simplificado, metadados_geracao, tipo_documento, pdf_filename)
            
            session['pdf_path'] = pdf_path
            session['pdf_filename'] = pdf_filename
            
            logging.info(f"PDF gerado: {pdf_filename}")
            
        except Exception as e:
            logging.error(f"Erro ao gerar PDF: {str(e)}", exc_info=True)
            # Continua mesmo se PDF falhar
            pass
        
        # Análise do resultado
        try:
            analise = analisar_resultado_judicial(texto_simplificado, tipo_documento)
        except Exception as e:
            logging.error(f"Erro na análise: {str(e)}")
            analise = {
                "tipo_resultado": "indefinido",
                "tem_valores": False,
                "tem_prazos": False,
                "tipo_documento": tipo_documento.get("nome") if tipo_documento else "Não identificado"
            }
        
        # Resposta de sucesso
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto_original)) * 100, 1) if len(texto_original) > 0 else 0,
            "metadados": metadados,
            "analise": analise,
            "tipo_documento": tipo_documento,
            "modelo_usado": metadados_geracao.get("modelo", "Gemini"),
            "tipo_arquivo": file_extension
        })
        
    except Exception as e:
        # Log detalhado do erro
        logging.error(f"ERRO GERAL no processamento: {str(e)}", exc_info=True)
        import traceback
        traceback_str = traceback.format_exc()
        logging.error(f"Traceback completo:\n{traceback_str}")
        
        return jsonify({
            "erro": "Erro inesperado ao processar arquivo",
            "detalhes": str(e),
            "tipo_erro": type(e).__name__,
            "sugestao": "Tente novamente ou use um arquivo diferente"
        }), 500

@app.route("/processar_texto", methods=["POST"])
@rate_limit
def processar_texto():
    """Processa texto manual com detecção de tipo"""
    try:
        data = request.get_json()
        texto = data.get("texto", "").strip()
        
        if not texto:
            return jsonify({"erro": "Nenhum texto fornecido"}), 400
            
        if len(texto) < 20:
            return jsonify({"erro": "Texto muito curto. Mínimo: 20 caracteres"}), 400
            
        if len(texto) > 10000:
            return jsonify({"erro": "Texto muito longo. Máximo: 10.000 caracteres"}), 400
        
        # Simplificar com detecção de tipo
        texto_simplificado, erro, tipo_documento = simplificar_com_gemini(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Análise do resultado
        analise = analisar_resultado_judicial(texto_simplificado, tipo_documento)
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto)) * 100, 1),
            "analise": analise,
            "tipo_documento": tipo_documento
        })
        
    except Exception as e:
        logging.error(f"Erro ao processar texto: {e}")
        return jsonify({"erro": "Erro ao processar o texto"}), 500

@app.route("/test_upload", methods=["POST"])
def test_upload():
    """Endpoint de teste para diagnóstico de upload"""
    try:
        info = {
            "request_method": request.method,
            "content_type": request.content_type,
            "files_in_request": 'file' in request.files,
            "form_data": dict(request.form),
            "headers": dict(request.headers),
            "tesseract_available": TESSERACT_AVAILABLE,
            "opencv_available": CV2_AVAILABLE,
            "gemini_configured": bool(GEMINI_API_KEY)
        }
        
        if 'file' in request.files:
            file = request.files['file']
            info["filename"] = file.filename
            info["content_type_file"] = file.content_type
            
            # Tentar ler primeiros bytes
            file.seek(0)
            first_bytes = file.read(100)
            file.seek(0)
            info["first_bytes"] = first_bytes.hex()[:50]
            info["file_size"] = len(file.read())
            
        return jsonify(info)
        
    except Exception as e:
        return jsonify({"erro": str(e), "tipo": type(e).__name__}), 500

@app.route("/diagnostico")
def diagnostico():
    """Endpoint para diagnosticar problemas de OCR e configuração"""
    diagnostico_info = {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "tesseract": {
            "disponivel": TESSERACT_AVAILABLE,
            "version": TESSERACT_VERSION,
            "linguas": TESSERACT_LANGS,
            "portugues_disponivel": 'por' in TESSERACT_LANGS if TESSERACT_LANGS else False
        },
        "opencv": {
            "disponivel": CV2_AVAILABLE
        },
        "python_libs": {},
        "sistema": {},
        "configuracao": {},
        "tipos_documentos": {
            "total": len(TIPOS_DOCUMENTOS),
            "lista": list(TIPOS_DOCUMENTOS.keys())
        }
    }
    
    # Bibliotecas Python
    try:
        import pytesseract
        diagnostico_info["python_libs"]["pytesseract"] = pytesseract.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["pytesseract"] = f"Erro: {str(e)}"
    
    try:
        import cv2
        diagnostico_info["python_libs"]["opencv"] = cv2.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["opencv"] = f"Erro: {str(e)}"
    
    try:
        from PIL import Image
        diagnostico_info["python_libs"]["pillow"] = Image.__version__
    except Exception as e:
        diagnostico_info["python_libs"]["pillow"] = f"Erro: {str(e)}"
    
    try:
        import fitz
        diagnostico_info["python_libs"]["pymupdf"] = fitz.version[0]
    except Exception as e:
        diagnostico_info["python_libs"]["pymupdf"] = f"Erro: {str(e)}"
    
    # Sistema
    import platform
    diagnostico_info["sistema"]["os"] = platform.system()
    diagnostico_info["sistema"]["arquitetura"] = platform.machine()
    diagnostico_info["sistema"]["python_version"] = platform.python_version()
    
    # Configurações
    diagnostico_info["configuracao"]["gemini_api_configurada"] = bool(GEMINI_API_KEY)
    diagnostico_info["configuracao"]["gemini_models"] = len(GEMINI_MODELS)
    diagnostico_info["configuracao"]["temp_dir"] = TEMP_DIR
    diagnostico_info["configuracao"]["max_file_size_mb"] = MAX_FILE_SIZE // 1024 // 1024
    diagnostico_info["configuracao"]["allowed_extensions"] = list(ALLOWED_EXTENSIONS)
    diagnostico_info["configuracao"]["tessdata_prefix"] = os.getenv("TESSDATA_PREFIX", "Não configurado")
    
    # Testar Tesseract
    if TESSERACT_AVAILABLE:
        try:
            test_result = subprocess.run(
                ['tesseract', '--version'], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            diagnostico_info["tesseract"]["teste"] = "OK"
            diagnostico_info["tesseract"]["output"] = test_result.stdout[:200]
        except Exception as e:
            diagnostico_info["tesseract"]["teste"] = f"Erro: {str(e)}"
    
    return jsonify(diagnostico_info)

@app.route("/estatisticas")
def estatisticas():
    """Retorna estatísticas"""
    return jsonify({
        "modelos": model_usage_stats,
        "cache_size": len(results_cache),
        "tesseract_disponivel": TESSERACT_AVAILABLE,
        "opencv_disponivel": CV2_AVAILABLE,
        "tipos_documentos": len(TIPOS_DOCUMENTOS),
        "timestamp": datetime.now().isoformat()
    })

@app.route("/download_pdf")
def download_pdf():
    """Download do PDF"""
    pdf_path = session.get('pdf_path')
    pdf_filename = session.get('pdf_filename', 'documento_simplificado.pdf')
    
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"erro": "PDF não encontrado"}), 404
    
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
    """Recebe feedback"""
    try:
        data = request.get_json()
        rating = data.get("rating")
        comment = data.get("comment", "")
        resultado_hash = data.get("hash", "")
        
        logging.info(f"Feedback - Rating: {rating}, Hash: {resultado_hash[:8]}, Comentário: {comment}")
        
        return jsonify({"sucesso": True, "mensagem": "Obrigado pelo seu feedback!"})
    except Exception as e:
        logging.error(f"Erro ao processar feedback: {e}")
        return jsonify({"erro": "Erro ao processar feedback"}), 500

@app.route("/health")
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(GEMINI_API_KEY),
        "models_available": len(GEMINI_MODELS),
        "cache_entries": len(results_cache),
        "tesseract_available": TESSERACT_AVAILABLE,
        "opencv_available": CV2_AVAILABLE,
        "tipos_documentos": len(TIPOS_DOCUMENTOS),
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

# Limpeza de arquivos temporários
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
                        logging.info(f"Arquivo removido: {filename}")
            
            to_remove = []
            for key, value in results_cache.items():
                if time.time() - value["timestamp"] > CACHE_EXPIRATION:
                    to_remove.append(key)
            
            for key in to_remove:
                del results_cache[key]
            
            if to_remove:
                logging.info(f"Removidos {len(to_remove)} itens do cache")
                
        except Exception as e:
            logging.error(f"Erro na limpeza: {e}")

cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

