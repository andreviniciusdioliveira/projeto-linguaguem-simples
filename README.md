⚖️ Linguagem Simples Jurídica
Uma aplicação web que transforma documentos jurídicos complexos em linguagem simples e acessível, utilizando inteligência artificial (Google Gemini) para democratizar o acesso à informação jurídica.
🎯 Objetivo
Facilitar a compreensão de documentos jurídicos por pessoas sem formação técnica na área, tornando a justiça mais acessível e transparente. A aplicação converte jargões jurídicos em linguagem cotidiana, mantendo a precisão das informações.

✨ Funcionalidades

📄 Processamento de Documentos

Upload de PDFs: Suporte a documentos de até 10MB
OCR Inteligente: Extração de texto usando Tesseract (português e inglês)
Texto Manual: Interface para colar textos diretamente
Drag & Drop: Interface intuitiva para upload de arquivos

🤖 IA Avançada

Múltiplos Modelos Gemini: Seleção automática baseada na complexidade

gemini-1.5-flash-8b (textos simples)
gemini-1.5-flash (textos médios)
gemini-2.0-flash-exp (textos complexos)


Fallback Inteligente: Troca automática entre modelos em caso de falha
Cache Inteligente: Evita reprocessamento de documentos iguais

📊 Análise Jurídica

Identificação de Resultados: Detecta vitórias, derrotas ou resultados parciais
Extração de Valores: Identifica quantias financeiras
Detecção de Prazos: Localiza datas importantes
Possibilidade de Recursos: Sugere quando cabível

🎨 Interface Moderna

Design Responsivo: Funciona em desktop, tablet e mobile
Modo Escuro: Alternância automática de temas
Animações Fluidas: Transições suaves e feedback visual
Glassmorphism: Efeitos visuais modernos
Progressão Visual: Steps que mostram o andamento do processo

🔊 Acessibilidade

Leitura em Voz Alta: Text-to-speech em português
Contraste Adequado: Paleta de cores acessível
Navegação por Teclado: Atalhos e navegação completa
Tooltips Informativos: Ajuda contextual

📥 Exportação

PDF Formatado: Geração de PDF com layout profissional
Cópia de Texto: Clipboard integrado
Download Direto: Baixar resultado simplificado

🏗️ Arquitetura
⚖️ Linguagem Simples Jurídica
Uma aplicação web que transforma documentos jurídicos complexos em linguagem simples e acessível, utilizando inteligência artificial (Google Gemini) para democratizar o acesso à informação jurídica.
🎯 Objetivo
Facilitar a compreensão de documentos jurídicos por pessoas sem formação técnica na área, tornando a justiça mais acessível e transparente. A aplicação converte jargões jurídicos em linguagem cotidiana, mantendo a precisão das informações.
✨ Funcionalidades
📄 Processamento de Documentos

Upload de PDFs: Suporte a documentos de até 10MB
OCR Inteligente: Extração de texto usando Tesseract (português e inglês)
Texto Manual: Interface para colar textos diretamente
Drag & Drop: Interface intuitiva para upload de arquivos

🤖 IA Avançada

Múltiplos Modelos Gemini: Seleção automática baseada na complexidade

gemini-1.5-flash-8b (textos simples)
gemini-1.5-flash (textos médios)
gemini-2.0-flash-exp (textos complexos)


Fallback Inteligente: Troca automática entre modelos em caso de falha
Cache Inteligente: Evita reprocessamento de documentos iguais

📊 Análise Jurídica

Identificação de Resultados: Detecta vitórias, derrotas ou resultados parciais
Extração de Valores: Identifica quantias financeiras
Detecção de Prazos: Localiza datas importantes
Possibilidade de Recursos: Sugere quando cabível

🎨 Interface Moderna

Design Responsivo: Funciona em desktop, tablet e mobile
Modo Escuro: Alternância automática de temas
Animações Fluidas: Transições suaves e feedback visual
Glassmorphism: Efeitos visuais modernos
Progressão Visual: Steps que mostram o andamento do processo

🔊 Acessibilidade

Leitura em Voz Alta: Text-to-speech em português
Contraste Adequado: Paleta de cores acessível
Navegação por Teclado: Atalhos e navegação completa
Tooltips Informativos: Ajuda contextual

📥 Exportação

PDF Formatado: Geração de PDF com layout profissional
Cópia de Texto: Clipboard integrado
Download Direto: Baixar resultado simplificado

🏗️ Arquitetura
Backend (Flask)
app.py                 # Aplicação principal
├── Rotas principais
│   ├── /              # Página inicial
│   ├── /processar     # Upload e processamento de PDF
│   ├── /processar_texto # Processamento de texto manual
│   ├── /download_pdf  # Download do resultado
│   ├── /feedback      # Avaliações dos usuários
│   ├── /estatisticas  # Métricas de uso
│   └── /health        # Health check
├── Processamento
│   ├── extrair_texto_pdf()     # Extração com OCR
│   ├── simplificar_com_gemini() # IA e fallback
│   ├── analisar_complexidade() # Escolha do modelo
│   └── gerar_pdf_simplificado() # Criação do PDF
└── Utilitários
    ├── Rate limiting
    ├── Cache de resultados
    ├── Limpeza automática
    └── Estatísticas de uso
Frontend (HTML/CSS/JS)
templates/index.html   # Interface principal
├── Upload de arquivos (drag & drop)
├── Editor de texto manual
├── Visualização de resultados
├── Modal de feedback
├── Sistema de notificações
└── Controles de acessibilidade

static/
├── style.css          # Estilos modernos com CSS Grid/Flexbox
└── avatar.js          # Funcionalidades interativas
🚀 Instalação e Deploy
Pré-requisitos

Python 3.11+
Tesseract OCR
Chave da API Google Gemini
Poppler (para processamento de PDF)

Instalação Local

Clone o repositório

bashgit clone <seu-repositorio>
cd linguagem-simples-juridica

Instale dependências do sistema

bash# Ubuntu/Debian
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-por poppler-utils

# macOS
brew install tesseract tesseract-lang poppler

Configure o ambiente Python

bashpython -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows

pip install -r requirements.txt

Configure variáveis de ambiente

bashexport GEMINI_API_KEY="sua_chave_aqui"
export SECRET_KEY="chave_secreta_flask"

Execute a aplicação

bashpython app.py
Deploy no Render

Configure o render.yaml (já incluído)
Adicione variáveis de ambiente:

GEMINI_API_KEY: Sua chave da API Gemini


Deploy automático via Git push

Deploy com Docker
bashdocker build -t linguagem-simples .
docker run -p 8080:8080 \
  -e GEMINI_API_KEY="sua_chave" \
  -e SECRET_KEY="chave_secreta" \
  linguagem-simples
📦 Dependências Principais
Backend

Flask 3.0.3: Framework web
PyMuPDF 1.24.2: Processamento de PDF
pytesseract 0.3.10: OCR
ReportLab 4.2.2: Geração de PDF
Pillow 10.4.0: Processamento de imagens
requests 2.31.0: Requisições HTTP para API Gemini
gunicorn 21.2.0: Servidor WSGI para produção

Sistema

Tesseract OCR: Reconhecimento de texto em imagens
Poppler: Utilitários para PDF

🔧 Configuração da API Gemini

Acesse o Google AI Studio
Crie uma nova chave de API
Configure a variável de ambiente GEMINI_API_KEY

Modelos Utilizados

gemini-1.5-flash-8b: Documentos simples (< 5.000 caracteres)
gemini-1.5-flash: Documentos médios (5.000-10.000 caracteres)
gemini-2.0-flash-exp: Documentos complexos (> 10.000 caracteres)

💡 Como Usar
1. Upload de PDF

Arraste o arquivo para a área de upload
Ou clique para selecionar arquivo
Aguarde o processamento automático

2. Texto Manual

Cole o texto jurídico na área de texto
Clique em "Simplificar Texto"
Use o botão "Exemplo" para testar

3. Resultado

Visualize o texto simplificado
Baixe em PDF formatado
Use text-to-speech para ouvir
Avalie a qualidade da simplificação

🛡️ Segurança e Limitações
Rate Limiting

10 requisições por minuto por IP
Cleanup automático de contadores antigos

Validações

Tamanho máximo: 10MB por PDF
Tipos aceitos: Apenas PDF
Texto manual: 20-10.000 caracteres

Cache e Performance

Cache de resultados: 1 hora
Limpeza automática: Arquivos temporários
Múltiplos workers: Gunicorn com 2 workers

📊 Métricas e Monitoramento
Endpoint de Health Check
GET /health
Estatísticas de Uso
GET /estatisticas
Dados Coletados

Número de documentos processados
Taxa de sucesso por modelo
Tempo médio de processamento
Feedback dos usuários (avaliações)

🎨 Características Técnicas
Design System

CSS Grid & Flexbox: Layout responsivo
Custom Properties: Variáveis CSS para temas
Animations: Transições suaves
Mobile-first: Design pensado para dispositivos móveis

Acessibilidade

WCAG 2.1: Padrões de acessibilidade
Semantic HTML: Estrutura semântica
Keyboard Navigation: Navegação completa por teclado
Screen Reader: Compatível com leitores de tela

Performance

Lazy Loading: Carregamento sob demanda
Resource Hints: Otimização de carregamento
Minification: CSS e JS otimizados
Caching: Cache inteligente de resultados

🤝 Contribuindo

Fork o projeto
Crie uma branch para sua feature (git checkout -b feature/MinhaFeature)
Commit suas mudanças (git commit -m 'Add: Nova funcionalidade')
Push para a branch (git push origin feature/MinhaFeature)
Abra um Pull Request

Padrões de Código

PEP 8: Para código Python
Prettier: Para JavaScript/CSS
Semantic Commits: Mensagens de commit descritivas

📝 Licença
Este projeto está sob licença MIT. Veja o arquivo LICENSE para mais detalhes.
🆘 Suporte
Issues Comuns
Tesseract não encontrado
bash# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-por

# Verificar instalação
tesseract --version
Erro de API Key
bash# Verificar se a variável está configurada
echo $GEMINI_API_KEY
Problemas de PDF

Verifique se o arquivo não está corrompido
Teste com PDF simples primeiro
Verifique o tamanho do arquivo (máx. 10MB)


🎯 Roadmap
Próximas Funcionalidades

 Suporte a múltiplos idiomas
 Integração com APIs jurídicas
 Sistema de usuários e histórico
 API REST para integração
 Suporte a documentos Word
 Análise de jurisprudência
 Dashboard administrativo
 Notificações em tempo real

Melhorias Técnicas

 Testes automatizados
 CI/CD pipeline
 Monitoramento avançado
 Logs estruturados
 Backup automático
 Scaling horizontal

"A justiça deve ser acessível a todos, começando pela compreensão de seus documentos."
