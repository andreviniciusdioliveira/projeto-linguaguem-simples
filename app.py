from flask import Flask, render_template, request, send_file, jsonify
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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuração Claude ---
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

PROMPT_SIMPLIFICACAO = """
Você é um especialista em linguagem cidadã.
Reescreva o texto abaixo de forma simples, clara e acessível,
sem termos técnicos difíceis, mantendo o sentido original.

Texto:
"""

def extrair_texto_pdf(pdf_bytes):
    texto = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            conteudo = page.get_text()
            if not conteudo.strip():
                pix = page.get_pixmap()
                img = Image.open(io.BytesIO(pix.tobytes()))
                conteudo = pytesseract.image_to_string(img)
            texto += conteudo + "\n"
    return texto

def simplificar_com_claude(texto):
    start_time = time.time()
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-3-opus-20240229",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": PROMPT_SIMPLIFICACAO + texto}]
    }
    try:
        response = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        elapsed = round(time.time() - start_time, 2)
        logging.info(f"[Claude] Texto enviado: {len(texto)} caracteres | Tempo: {elapsed}s")
        return data["content"][0]["text"], None
    except Exception as e:
        logging.error(f"Erro ao chamar Claude: {e}")
        return None, "Erro ao processar texto com Claude. Verifique a chave ou a API."

def gerar_pdf_simplificado(texto):
    output_path = "pdf_simplificado.pdf"
    c = canvas.Canvas(output_path, pagesize=letter)
    largura, altura = letter
    y = altura - 50
    for linha in texto.split("\n"):
        c.drawString(50, y, linha)
        y -= 15
        if y < 50:
            c.showPage()
            y = altura - 50
    c.save()
    return output_path

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/processar", methods=["POST"])
def processar():
    file = request.files['file']
    pdf_bytes = file.read()
    texto_original = extrair_texto_pdf(pdf_bytes)

    texto_simplificado, erro = simplificar_com_claude(texto_original)
    if erro:
        return jsonify({"erro": erro}), 500

    gerar_pdf_simplificado(texto_simplificado)
    return jsonify({"texto": texto_simplificado})

@app.route("/processar_texto", methods=["POST"])
def processar_texto():
    data = request.get_json()
    texto = data.get("texto", "")
    if not texto:
        return jsonify({"erro": "Nenhum texto recebido"}), 400

    texto_simplificado, erro = simplificar_com_claude(texto)
    if erro:
        return jsonify({"erro": erro}), 500

    return jsonify({"texto": texto_simplificado})

@app.route("/download_pdf")
def download_pdf():
    return send_file("pdf_simplificado.pdf", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
