from flask import Flask, render_template, request, send_file, jsonify, session
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

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
logging.basicConfig(level=logging.INFO)

# --- Configurações ---
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'pdf'}
TEMP_DIR = tempfile.gettempdir()

# Rate limiting
request_counts = {}
RATE_LIMIT = 10  # requisições por minuto
cleanup_lock = threading.Lock()

# Limpar contadores antigos a cada 5 minutos
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

# Prompt otimizado para simplificação
PROMPT_SIMPLIFICACAO = """**Papel:** Você é um especialista em linguagem simples aplicada ao Poder Judiciário, com experiência em transformar textos jurídicos complexos em comunicações claras e acessíveis.

**Objetivo:** Reescrever sentenças, despachos, decisões e acórdãos jurídicos em linguagem simples, mantendo o conteúdo jurídico essencial, mas tornando-o mais fácil de entender para qualquer cidadão.

**Diretrizes obrigatórias:**
1. **Empatia:** considere quem vai ler; explique termos técnicos ou siglas quando necessário.
2. **Hierarquia da informação:** apresente primeiro as informações principais e depois as complementares.
3. **Palavras conhecidas:** substitua termos jurídicos difíceis por equivalentes comuns (use o mini dicionário abaixo).
4. **Palavras concretas:** use verbos de ação e substantivos concretos; evite abstrações excessivas.
5. **Frases curtas:** prefira frases com até 20 a 25 palavras.
6. **Ordem direta:** siga a estrutura sujeito + verbo + complemento, evitando voz passiva desnecessária.
7. **Clareza:** elimine jargões, expressões rebuscadas e termos em latim sem explicação.

**Mini Dicionário Jurídico Simplificado (substituições automáticas):**
* Autos → Processo
* Carta Magna → Constituição Federal
* Conciliação infrutífera → Não houve acordo
* Concluso → Aguardando decisão do juiz
* Dano emergente → Prejuízo imediato
* Data vênia → Com todo respeito
* Dilação → Prorrogação ou adiamento
* Egrégio → Respeitável
* Exordial → Petição inicial (documento que inicia o processo)
* Extra petita → Diferente do que foi pedido
* Impugnar → Contestar ou se opor
* Inaudita altera pars → Sem ouvir a outra parte
* Indubitável → Evidente
* Intempestivo → Fora do prazo
* Jurisprudência → Decisões anteriores sobre o tema
* Não obstante → Apesar de
* Óbice → Impedimento
* Outrossim → Além disso
* Pleitear / Postular → Pedir
* Preliminares → Alegações iniciais
* Pugnar → Defender
* Sucumbência → Perda do processo
* Ultra petita → Mais do que foi pedido

**Formato de saída:**
Por favor, apresente o resultado no seguinte formato:

**VERSÃO SIMPLIFICADA OFICIAL:**
[Texto em linguagem simples, mantendo tom formal e respeitoso]

**RESUMO PARA LEIGOS:**
[Explicação breve do que a decisão significa para quem não é da área jurídica]

**TEXTO ORIGINAL A SER SIMPLIFICADO:**
"""

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extrair_texto_pdf(pdf_bytes):
    """Extrai texto de PDF com melhor tratamento de erros e OCR otimizado"""
    texto = ""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            total_pages = len(doc)
            logging.info(f"Processando PDF com {total_pages} páginas")
            
            for i, page in enumerate(doc):
                try:
                    # Primeiro tenta extrair texto normal
                    conteudo = page.get_text()
                    
                    # Se não há texto, tenta OCR
                    if not conteudo.strip():
                        logging.info(f"Aplicando OCR na página {i+1}")
                        pix = page.get_pixmap(dpi=150)  # DPI reduzido para performance
                        img = Image.open(io.BytesIO(pix.tobytes()))
                        
                        # Configurações otimizadas do Tesseract
                        custom_config = r'--oem 3 --psm 6 -l por'
                        conteudo = pytesseract.image_to_string(img, config=custom_config)
                    
                    texto += f"\n--- Página {i+1} ---\n{conteudo}\n"
                    
                except Exception as e:
                    logging.error(f"Erro ao processar página {i+1}: {e}")
                    texto += f"\n--- Erro ao processar página {i+1} ---\n"
            
            # Limpa o texto
            texto = texto.strip()
            if not texto:
                raise ValueError("Nenhum texto foi extraído do PDF")
                
    except Exception as e:
        logging.error(f"Erro ao extrair texto do PDF: {e}")
        raise
    
    return texto

def simplificar_com_claude(texto, max_retries=3):
    """Chama a API do Claude com retry e melhor tratamento de erros"""
    # Limita o tamanho do texto para evitar tokens excessivos
    if len(texto) > 15000:
        texto = texto[:15000] + "\n\n[Texto truncado devido ao tamanho...]"
    
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    payload = {
        "model": "claude-3-opus-20240229",
        "max_tokens": 3000,  # Aumentado para acomodar a resposta em dois formatos
        "temperature": 0.2,  # Ainda mais consistência para textos jurídicos
        "messages": [{
            "role": "user", 
            "content": PROMPT_SIMPLIFICACAO + texto
        }]
    }
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = requests.post(
                CLAUDE_API_URL, 
                headers=headers, 
                json=payload, 
                timeout=120  # Aumentado para 2 minutos
            )
            response.raise_for_status()
            
            data = response.json()
            elapsed = round(time.time() - start_time, 2)
            
            logging.info(f"Claude API - Sucesso em {elapsed}s | Tokens: ~{len(texto)//4}")
            
            texto_simplificado = data["content"][0]["text"]
            return texto_simplificado, None
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Backoff exponencial
                continue
            return None, "Timeout ao processar. O texto pode ser muito longo."
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                return None, "Limite de taxa da API excedido. Tente novamente mais tarde."
            elif e.response.status_code == 401:
                return None, "Erro de autenticação. Verifique a chave da API."
            else:
                return None, f"Erro HTTP: {e.response.status_code}"
                
        except Exception as e:
            logging.error(f"Erro ao chamar Claude (tentativa {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None, "Erro ao processar texto. Verifique os logs."

def gerar_pdf_simplificado(texto, filename="documento_simplificado.pdf"):
    """Gera PDF com melhor formatação e suporte a UTF-8"""
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
        
        # Título
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_esq, y, "Documento em Linguagem Simples")
        y -= 30
        
        # Data
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(margem_esq, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
        y -= 20
        
        # Linha separadora
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(margem_esq, y, largura - margem_dir, y)
        y -= 20
        
        # Texto principal
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0, 0, 0)
        
        # Processa o texto separando por seções
        linhas = texto.split('\n')
        
        for linha in linhas:
            if not linha.strip():
                y -= altura_linha
                continue
            
            # Detecta títulos de seção
            if linha.strip().startswith('**') and linha.strip().endswith('**'):
                # Remove os asteriscos e formata como título
                titulo = linha.strip()[2:-2]
                c.setFont("Helvetica-Bold", 12)
                if y < margem_bottom + altura_linha * 2:
                    c.showPage()
                    y = altura - margem_top
                c.drawString(margem_esq, y, titulo)
                c.setFont("Helvetica", 11)
                y -= altura_linha * 1.5
                continue
            
            # Quebra o parágrafo em linhas
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
            
            # Desenha as linhas
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
        c.drawString(margem_esq, 30, "Processado pelo Sistema de Linguagem Simples - INOVASSOL")
        
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
    """Processa upload de PDF com validações aprimoradas"""
    try:
        # Validação do arquivo
        if 'file' not in request.files:
            return jsonify({"erro": "Nenhum arquivo enviado"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado"}), 400
            
        if not allowed_file(file.filename):
            return jsonify({"erro": "Formato inválido. Apenas PDFs são aceitos"}), 400
        
        # Verifica tamanho
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size > MAX_FILE_SIZE:
            return jsonify({"erro": f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE//1024//1024}MB"}), 400
        
        # Processa o PDF
        pdf_bytes = file.read()
        
        # Hash do arquivo para cache (futuro)
        file_hash = hashlib.md5(pdf_bytes).hexdigest()
        logging.info(f"Processando arquivo: {secure_filename(file.filename)} ({size/1024:.1f}KB) - Hash: {file_hash}")
        
        texto_original = extrair_texto_pdf(pdf_bytes)
        
        if len(texto_original) < 10:
            return jsonify({"erro": "PDF não contém texto suficiente para processar"}), 400
        
        texto_simplificado, erro = simplificar_com_claude(texto_original)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        # Gera PDF simplificado
        pdf_filename = f"simplificado_{file_hash[:8]}.pdf"
        pdf_path = gerar_pdf_simplificado(texto_simplificado, pdf_filename)
        
        # Salva o caminho na sessão para download posterior
        session['pdf_path'] = pdf_path
        session['pdf_filename'] = pdf_filename
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto_original),
            "caracteres_simplificado": len(texto_simplificado),
            "reducao_percentual": round((1 - len(texto_simplificado)/len(texto_original)) * 100, 1)
        })
        
    except Exception as e:
        logging.error(f"Erro ao processar PDF: {e}")
        return jsonify({"erro": "Erro ao processar o PDF. Verifique se o arquivo não está corrompido"}), 500

@app.route("/processar_texto", methods=["POST"])
@rate_limit
def processar_texto():
    """Processa texto manual com validações"""
    try:
        data = request.get_json()
        texto = data.get("texto", "").strip()
        
        if not texto:
            return jsonify({"erro": "Nenhum texto fornecido"}), 400
            
        if len(texto) < 20:
            return jsonify({"erro": "Texto muito curto. Mínimo: 20 caracteres"}), 400
            
        if len(texto) > 10000:
            return jsonify({"erro": "Texto muito longo. Máximo: 10.000 caracteres"}), 400
        
        texto_simplificado, erro = simplificar_com_claude(texto)
        
        if erro:
            return jsonify({"erro": erro}), 500
        
        return jsonify({
            "texto": texto_simplificado,
            "caracteres_original": len(texto),
            "caracteres_simplificado": len(texto_simplificado)
        })
        
    except Exception as e:
        logging.error(f"Erro ao processar texto: {e}")
        return jsonify({"erro": "Erro ao processar o texto"}), 500

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

@app.route("/health")
def health():
    """Endpoint de health check para o Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "api_configured": bool(CLAUDE_API_KEY)
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({"erro": "Endpoint não encontrado"}), 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Erro interno: {e}")
    return jsonify({"erro": "Erro interno do servidor"}), 500

# Limpa arquivos temporários antigos periodicamente
def cleanup_temp_files():
    while True:
        try:
            time.sleep(3600)  # A cada hora
            now = time.time()
            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('simplificado_'):
                    filepath = os.path.join(TEMP_DIR, filename)
                    if os.stat(filepath).st_mtime < now - 3600:  # Arquivos com mais de 1 hora
                        os.remove(filepath)
                        logging.info(f"Arquivo temporário removido: {filename}")
        except Exception as e:
            logging.error(f"Erro na limpeza de arquivos: {e}")

# Inicia thread de limpeza
cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
