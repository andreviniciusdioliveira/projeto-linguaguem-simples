from flask import Flask, render_template, request, send_file, jsonify
import fitz
import pytesseract
from PIL import Image
import io
import os
import logging
import openai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuração OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("Nenhuma chave de API do OpenAI encontrada! Defina OPENAI_API_KEY no ambiente.")
openai.api_key = OPENAI_API_KEY

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

def simplificar_com_chatgpt(texto):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # você pode trocar para "gpt-3.5-turbo" se quiser reduzir custo
            messages=[
                {"role": "system", "content": "Você é um especialista em linguagem simples."},
                {"role": "user", "content": PROMPT_SIMPLIFICACAO + texto}
            ]
        )
        return response.choices[0].message["content"], None
    except Exception as e:
        logging.error(f"Erro ao chamar o ChatGPT: {e}")
        return None, "Erro ao processar texto com ChatGPT. Verifique a chave ou a API."

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

    texto_simplificado, erro = simplificar_com_chatgpt(texto_original)
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

    texto_simplificado, erro = simplificar_com_chatgpt(texto)
    if erro:
        return jsonify({"erro": erro}), 500

    return jsonify({"texto": texto_simplificado})

@app.route("/download_pdf")
def download_pdf():
    return send_file("pdf_simplificado.pdf", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
