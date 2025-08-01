from flask import Flask, render_template, request, send_file, jsonify
import fitz
import pytesseract
from PIL import Image
import io
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
genai.configure(api_key="SUA_CHAVE_API_GEMINI")

PROMPT_SIMPLIFICACAO = """
Você é um especialista em linguagem cidadã.
Reescreva o texto abaixo de forma simples, clara e acessível,
sem termos técnicos difíceis, mantendo o sentido original.

Texto:
"""

texto_simplificado_global = ""

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
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(PROMPT_SIMPLIFICACAO + texto)
    return response.text

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
    global texto_simplificado_global
    file = request.files['file']
    pdf_bytes = file.read()
    texto_original = extrair_texto_pdf(pdf_bytes)
    texto_simplificado_global = simplificar_com_gemini(texto_original)
    gerar_pdf_simplificado(texto_simplificado_global)
    return jsonify({"texto": texto_simplificado_global})

@app.route("/download_pdf")
def download_pdf():
    return send_file("pdf_simplificado.pdf", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
