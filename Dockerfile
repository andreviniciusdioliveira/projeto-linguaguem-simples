# Imagem base mínima com Python 3.11
FROM python:3.11-slim


# Variáveis para um Python mais "limpo"
ENV PYTHONDONTWRITEBYTECODE=1 \
PYTHONUNBUFFERED=1


# Instala o Tesseract OCR e dependências (inclui idiomas pt/pt-br e es, se disponíveis)
RUN apt-get update && apt-get install -y \
tesseract-ocr \
libtesseract-dev \
tesseract-ocr-por \
tesseract-ocr-spa \
&& rm -rf /var/lib/apt/lists/*


# Diretório da aplicação
WORKDIR /app


# Dependências Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


# Copia o restante do código
COPY . .


# (Opcional) expõe explicitamente a porta; o Render injeta $PORT
EXPOSE 8080


# (Opcional) variável para o caminho do binário do tesseract
ENV TESSERACT_CMD=/usr/bin/tesseract


# Comando de inicialização — usa a porta fornecida pelo Render via $PORT
# Ajuste "app:app" para o seu módulo/objeto WSGI se for diferente.
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
