from flask import Flask, render_template, request, send_file, jsonify
import fitz
import pytesseract
from PIL import Image
import io
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Verificação da chave API ---
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "models/gemini-1.5-pro-latest"

if not API_KEY:
    logging.error("Nenhuma chave de API encontrada! Defina GOOGLE_API_KEY no ambiente.")
    GEMINI_OK = False
else:
    try:
        genai.configure(api_key=API_KEY)
        logging.info(f"Validando chave do Gemini com modelo {MODEL_NAME}...")
        test_model = genai.GenerativeModel(MODEL_NAME)
        test_response = test_model.generate_content("Teste rápido da API Gemini")
        if test_response and hasattr(test_response, 'text'):
            logging.info("Chave do Gemini válida!")
            GEMINI_OK = True
        else:
            logging.error("Chave fornecida não retornou resposta válida.")
            GEMINI_OK = False
    except Exception as e:
        logging.error(f"Erro ao validar chave Gemini: {e}")
        GEMINI_OK = False

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

def simplificar_com_gemini(texto):
    if not GEMINI_OK:
        return None, "A chave do Gemini é inválida ou não foi configurada corretamente."
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(PROMPT_SIMPLIFICACAO + texto)
        return response.text, None
    except Exception as e:
        logging.error(f"Erro ao chamar o Gemini: {e}")
        return None, "Erro ao processar texto com o Gemini."

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
    return render_template("index.html", gemini_ok=GEMINI_OK)

@app.route("/processar", methods=["POST"])
def processar():
    file = request.files['file']
    pdf_bytes = file.read()
    texto_original = extrair_texto_pdf(pdf_bytes)

    texto_simplificado, erro = simplificar_com_gemini(texto_original)
    if erro:
        return jsonify({"erro": erro}), 500

    gerar_pdf_simplificado(texto_simplificado)
    return jsonify({"texto": texto_simplificado})

@app.route("/download_pdf")
def download_pdf():
    return send_file("pdf_simplificado.pdf", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
