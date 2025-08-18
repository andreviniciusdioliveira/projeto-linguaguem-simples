# 📄 Simplificador de Documentos Jurídicos

Uma aplicação web inteligente que transforma documentos jurídicos complexos em linguagem simples e acessível, utilizando IA para facilitar a compreensão de sentenças, decisões e outros textos.

## ✨ Funcionalidades

### 🔍 **Processamento Inteligente**
- **Upload de PDFs**: Processa documentos jurídicos em PDF com OCR automático
- **Texto Manual**: Análise direta de textos colados na plataforma
- **Extração Otimizada**: Suporte a documentos digitalizados e texto nativo

### 🤖 **IA Multi-Modelo**
- **Gemini AI**: Utiliza múltiplos modelos Google Gemini com fallback automático
- **Análise de Complexidade**: Escolha inteligente do modelo baseada no conteúdo

### 📊 **Análise Estruturada**
- **Identificação Automática**: Reconhece tipo de documento e partes envolvidas
- **Detecção de Resultado**: Identifica vitórias, derrotas ou decisões parciais
- **Valores e Prazos**: Extrai automaticamente valores monetários e prazos importantes
- **Glossário Dinâmico**: Cria dicionário dos termos jurídicos encontrados

### 📋 **Formato Padronizado**
- **Resumo Executivo**: Resultado claro com ícones visuais (✅ ❌ ⚠️)
- **Seções Organizadas**: Estrutura fixa para fácil localização da informação
- **PDF Otimizado**: Geração de documento simplificado para download
- **Design Responsivo**: Interface adaptável para desktop e mobile

## 🚀 Tecnologias Utilizadas

### **Backend**
- **Python 3.8+** - Linguagem principal
- **Flask** - Framework web minimalista e eficiente
- **PyMuPDF** - Extração de texto de PDFs
- **Tesseract OCR** - Reconhecimento óptico de caracteres
- **ReportLab** - Geração de PDFs formatados

### **IA e APIs**
- **Google Gemini API** - Processamento de linguagem natural
- **Multi-modelo**: Gemini 1.5 Flash 8B, Flash, e 2.0 Flash Experimental

### **Frontend**
- **HTML5/CSS3** - Interface moderna e responsiva
- **JavaScript ES6+** - Interatividade e AJAX
- **Bootstrap** - Framework CSS para design consistente

## 📦 Instalação

### **Pré-requisitos**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-por python3-pip

# macOS (Homebrew)
brew install tesseract tesseract-lang

# Windows
# Baixe e instale o Tesseract OCR do GitHub oficial
```

### **Configuração do Projeto**
```bash
# 1. Clone o repositório
git clone https://github.com/seu-usuario/simplificador-juridico.git
cd simplificador-juridico

# 2. Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
cp .env.example .env
# Edite o arquivo .env com suas configurações
```

### **Variáveis de Ambiente**
Crie um arquivo `.env` na raiz do projeto:
```env
# API do Google Gemini (Obrigatório)
GEMINI_API_KEY=sua_chave_api_aqui

# Configurações opcionais
SECRET_KEY=sua_chave_secreta_flask
PORT=8080
FLASK_ENV=production
```

### **Como Obter a API Key do Gemini**
1. Acesse [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Faça login com sua conta Google
3. Clique em "Create API Key"
4. Copie a chave gerada para o arquivo `.env`

## 🏃‍♂️ Execução

### **Desenvolvimento Local**
```bash
# Ativar ambiente virtual
source venv/bin/activate

# Executar aplicação
python app.py

# Aplicação estará disponível em http://localhost:8080
```

### **Produção com Gunicorn**
```bash
# Instalar Gunicorn (já incluído no requirements.txt)
pip install gunicorn

# Executar em produção
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

### **Docker (Opcional)**
```dockerfile
FROM python:3.9-slim

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8080

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "app:app"]
```

## 📁 Estrutura do Projeto

```
simplificador-juridico/
│
├── app.py                 # Aplicação principal Flask
├── requirements.txt       # Dependências Python
├── .env.example          # Exemplo de variáveis de ambiente
├── README.md             # Este arquivo
│
├── templates/            # Templates HTML
│   └── index.html       # Interface principal
│
├── static/              # Arquivos estáticos
│   ├── css/            # Estilos CSS
│   ├── js/             # Scripts JavaScript
│   └── img/            # Imagens e ícones
│
└── temp/               # Arquivos temporários (criado automaticamente)
```

## 🎯 Como Usar

### **1. Upload de PDF**
- Acesse a aplicação web
- Clique em "Selecionar PDF" ou arraste o arquivo
- Aguarde o processamento (pode levar alguns segundos)
- Visualize o resultado simplificado
- Baixe o PDF formatado (opcional)

### **2. Texto Manual**
- Cole o texto jurídico na área de texto
- Clique em "Simplificar Texto"
- Visualize o resultado estruturado

### **3. Interpretando os Resultados**
- **✅ VITÓRIA TOTAL**: Você ganhou completamente
- **❌ DERROTA**: Você perdeu a causa
- **⚠️ VITÓRIA PARCIAL**: Ganhou parte dos pedidos
- **⏳ AGUARDANDO**: Ainda não há decisão final
- **📋 ANDAMENTO**: Apenas despacho processual

## 🔧 Configurações Avançadas

### **Rate Limiting**
- **Limite**: 10 requisições por minuto por IP
- **Cleanup**: Automático a cada minuto
- **Personalização**: Modifique `RATE_LIMIT` no código

### **Cache do Sistema**
- **Expiração**: 1 hora por padrão
- **Hash MD5**: Identificação única de documentos
- **Cleanup**: Automático a cada hora

### **Modelos Gemini**
- **Seleção Automática**: Baseada na complexidade do texto
- **Fallback**: Tenta modelos alternativos em caso de falha
- **Estatísticas**: Endpoint `/estatisticas` para monitoramento

## 🚀 Deploy

### **Render (Recomendado)**
1. Fork este repositório
2. Conecte sua conta Render ao GitHub
3. Crie um novo Web Service
4. Configure as variáveis de ambiente
5. Deploy automático a cada push

### **Heroku**
```bash
# Instalar Heroku CLI
heroku create seu-app-name
heroku config:set GEMINI_API_KEY=sua_chave
git push heroku main
```

### **Railway**
```bash
# Conectar conta Railway
railway login
railway new
railway add
railway up
```

## 📊 Monitoramento

### **Health Check**
```
GET /health
```
Retorna status da aplicação, configuração da API e estatísticas.

### **Estatísticas de Uso**
```
GET /estatisticas
```
### "A justiça deve ser acessível a todos, começando pela compreensão de seus documentos."



⭐ **Se este projeto foi útil, deixe uma estrela no repositório!**

📝 **Encontrou um bug ou tem uma sugestão? Abra uma issue!**
