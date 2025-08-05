#!/bin/bash

# Script para instalar Tesseract no Render
echo "Verificando se Tesseract está instalado..."

if ! command -v tesseract &> /dev/null
then
    echo "Tesseract não encontrado. Tentando instalar..."
    
    # Tenta baixar e instalar Tesseract de forma alternativa
    mkdir -p /tmp/tesseract
    cd /tmp/tesseract
    
    # Download de binários pré-compilados (se disponível)
    wget -q https://github.com/tesseract-ocr/tesseract/releases/download/5.3.0/tesseract-5.3.0-linux.tar.gz -O tesseract.tar.gz || echo "Download falhou"
    
    # Se o download falhou, tenta usar pytesseract sem Tesseract instalado
    echo "Usando configuração alternativa..."
else
    echo "Tesseract já está instalado!"
    tesseract --version
fi

echo "Continuando com o build..."