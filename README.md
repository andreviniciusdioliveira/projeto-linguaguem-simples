<p align="center">
  <img src="static/logo.png" alt="Entenda Aqui - Logo" width="200">
</p>

<h1 align="center">Entenda Aqui</h1>

<p align="center">
  <strong>Transformando documentos jurídicos complexos em linguagem simples e acessível para todos os cidadãos brasileiros.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11-blue.svg" alt="Python 3.11"></a>
  <a href="https://flask.palletsprojects.com/"><img src="https://img.shields.io/badge/Flask-3.0.3-green.svg" alt="Flask 3.0.3"></a>
  <a href="https://ai.google.dev/"><img src="https://img.shields.io/badge/Google%20Gemini-AI-orange.svg" alt="Google Gemini"></a>
  <a href="#-lgpd--privacidade"><img src="https://img.shields.io/badge/LGPD-Compliance-brightgreen.svg" alt="LGPD Compliant"></a>
  <a href="https://render.com"><img src="https://img.shields.io/badge/Deploy-Render-purple.svg" alt="Render Deploy"></a>
</p>

<p align="center">
  <a href="#sobre-o-projeto">Sobre</a> •
  <a href="#funcionalidades">Funcionalidades</a> •
  <a href="#painel-administrativo">Painel Admin</a> •
  <a href="#como-funciona">Como Funciona</a> •
  <a href="#instalação">Instalação</a> •
  <a href="#deploy">Deploy</a> •
  <a href="#api-endpoints">API</a> •
  <a href="#lgpd--privacidade">LGPD</a>
</p>

---

## Sobre o Projeto

O **Entenda Aqui** é uma aplicação web desenvolvida pela **INOVASSOL - Centro de Inovação AI** que utiliza inteligência artificial do Google Gemini para simplificar documentos jurídicos complexos — sentenças, mandados, acórdãos, despachos e outros — transformando-os em linguagem clara, objetiva e acessível ao cidadão comum.

### O Problema

Milhões de brasileiros recebem documentos jurídicos todos os dias e não conseguem compreender seu conteúdo. A linguagem técnica do Direito cria uma barreira que impede o cidadão de entender seus próprios direitos e obrigações.

### A Solução

O Entenda Aqui recebe o documento jurídico (PDF, imagem ou texto), processa com IA e entrega:

- Um **resumo claro** do que o documento diz
- A **identificação do resultado** (vitória, derrota, parcial, pendente)
- Os **valores e prazos** extraídos automaticamente
- Um **glossário** dos termos jurídicos usados
- Uma **explicação personalizada** com base no papel do usuário (autor ou réu)
- **Indicadores de urgência** para documentos com prazos críticos
- Um **PDF simplificado** para download com marca d'água anti-fraude

---

## Funcionalidades

### Processamento de Documentos

| Recurso | Descrição |
|---------|-----------|
| **Upload de PDF** | Extração de texto via PyMuPDF com fallback para OCR |
| **Upload de Imagens** | Suporte a PNG, JPG, GIF, BMP, TIFF, WEBP com OCR Tesseract |
| **Texto Manual** | Cole o texto jurídico diretamente na interface (endpoint `/processar_texto`) |
| **Documentos Digitalizados** | OCR automático com pré-processamento de imagem (contraste, escala de cinza) |

### Inteligência Artificial

| Recurso | Descrição |
|---------|-----------|
| **Multi-Modelo** | Sistema de fallback com 4 modelos Gemini em cascata |
| **Perspectiva Personalizada** | Explicação adaptada para autor, réu ou caso ECA |
| **Detecção de Segredo de Justiça** | Bloqueio automático de documentos sigilosos (exceto mandados e intimações) |
| **Validação Judicial** | Aceita apenas documentos emitidos pelo Poder Judiciário — bloqueia petições e reclamações trabalhistas |
| **Perguntas Sugeridas** | Sugestões contextuais baseadas no tipo de documento |

### Segurança e Proteção Anti-Abuso

| Recurso | Descrição |
|---------|-----------|
| **Validação de CPF** | Verificação algorítmica com check digits antes do processamento |
| **Cofre Criptografado de CPF** | Armazenamento criptografado com Fernet, apagado diariamente (LGPD) |
| **Rate Limiting por CPF** | Máximo de 5 documentos por CPF por dia |
| **Rate Limiting por IP** | 10 requisições por minuto + 20 documentos/dia por IP |
| **Rate Limiting CPF+IP (anti-botnet)** | Máximo de 3 documentos/dia por par (CPF, IP) |
| **Limite Diário de Tokens** | 171,6 milhões de tokens/dia para controlar custos da API |
| **Bloqueio de Documentos Não-Judiciais** | Pré-detecção de petições, reclamações trabalhistas e documentos advocatícios |
| **Proteção CSRF** | Token por sessão para endpoints POST |
| **Validação MIME por Magic Bytes** | Confirma tipo real do arquivo (previne upload de executáveis com extensão falsa) |
| **Vínculo PDF↔Sessão** | PDFs só podem ser baixados na mesma sessão que os gerou (anti-enumeração) |

### Interface

| Recurso | Descrição |
|---------|-----------|
| **Identidade Institucional** | Barra superior em azul TJTO com logo oficial do Poder Judiciário; footer com endereço da Sede e do Anexo I, telefones e horário de atendimento |
| **Drag & Drop** | Arraste e solte arquivos para upload |
| **Modo Escuro/Claro** | Alternância de tema com preferência salva |
| **Responsivo** | Interface mobile-first adaptável a qualquer tela |
| **Acessibilidade** | ARIA labels nos botões, `<main>` landmark, `aria-live` no resultado, suporte a `prefers-reduced-motion` |
| **Avatar Assistente** | Avatar flutuante "JUS Bot" com chat contextual sobre o documento |
| **Feedback Sonoro** | Áudios pré-gravados de confirmação ao iniciar e concluir a simplificação |
| **Narração com Voz Neural** | Leitura em áudio do texto simplificado via `edge-tts` (voz `pt-BR-FranciscaNeural`) com fallback para Web Speech API |
| **Download PDF** | Gera PDF simplificado com marca d'água anti-fraude e QR code |
| **Compartilhamento** | Compartilhe via WhatsApp, Twitter, Facebook ou copie o link |

### Privacidade (LGPD)

| Recurso | Descrição |
|---------|-----------|
| **LGPD Compliant** | Zero armazenamento de dados pessoais ou conteúdo de documentos |
| **Limpeza Automática** | Arquivos temporários removidos em 30 minutos |
| **Validação de Integridade** | QR code e hash SHA-256 para verificar autenticidade do PDF gerado |
| **Anti-Fraude** | Marca d'água diagonal + logotipos variados no PDF |

### Painel Administrativo

Dashboard interno em `/admin` para o time visualizar uso, custos e auditoria. **Tudo agregado e LGPD-compliant** — não exibe nenhum dado pessoal identificável.

| Recurso | Descrição |
|---------|-----------|
| **Multi-usuário com Papéis** | `superadmin` (gerencia contas) e `viewer` (só dashboard) |
| **Bootstrap Automático** | 1º usuário criado a partir de `ADMIN_PASSWORD_HASH` no primeiro init |
| **Reset de Senha por Token** | Link one-time-use com validade de 24h, sem precisar de SMTP |
| **Brute-Force Protection** | 5 falhas em 15 min bloqueiam o IP; tentativas retidas por 24h |
| **Sessão com Timeout** | Logout automático após 30 min de inatividade |
| **KPIs em Tempo Real** | Documentos hoje/7d/30d, satisfação, tempo médio, IPs únicos |
| **Custos em BRL** | Cálculo automático do gasto Gemini (hoje, mês, 30d) com câmbio configurável |
| **Tokens por Simplificação** | Média de tokens entrada/saída por documento, breakdown por modelo |
| **Gráficos** | Tokens 30d, Feedback, Heatmap por hora, IPs únicos por dia (Chart.js) |
| **Tabelas** | Uso e taxa de fallback dos modelos Gemini, custo por modelo, tipos de documento |
| **Audit Log Completo** | login/logout, criação/desativação de usuários, reset de senha, com retenção de 180 dias |
| **Debounce no Audit** | `dashboard_view` e `api_stats` deduplicados em janela de 5 min (evita inflar log com polling) |
| **Identidade Institucional** | Visual alinhado ao Poder Judiciário do Tocantins (paleta TJTO + logo oficial) |

---

## Como Funciona

### Fluxo de Processamento

```
  Usuário informa CPF
           │
           ▼
  ┌─────────────────┐
  │ Validação CPF    │  Check digits + rate limit (5/dia) + cofre criptografado
  └────────┬────────┘
           ▼
  Usuário envia documento
           │
           ▼
  ┌─────────────────┐
  │ Validação        │  Extensão, tamanho (max 10MB), rate limit IP
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Validação Judicial│  Rejeita petições, reclamações e docs não-judiciais
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Extração de Texto│  PyMuPDF (PDF) ou Tesseract OCR (Imagem)
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Cache Check      │  MD5 hash dos primeiros 5000 chars + perspectiva
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Token Check      │  Verifica limite diário de 171,6M tokens
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Google Gemini AI │  Análise com fallback automático entre modelos
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Pós-Processamento│  Validação de output, extração de valores,
  │                  │  detecção de perspectiva, glossário
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Geração de PDF   │  ReportLab + marca d'água + QR code
  └────────┬────────┘
           ▼
  Resultado simplificado exibido ao usuário
```

### Sistema de Fallback de IA

O sistema tenta os modelos Gemini em ordem de prioridade. Se um modelo falhar (cota esgotada, erro de API, etc.), o próximo é utilizado automaticamente:

| Prioridade | Modelo | Descrição |
|:----------:|--------|-----------|
| 1 | `gemini-2.5-flash-lite` | Modelo 2.5 flash-lite (mais rápido, cota separada da 2.0) |
| 2 | `gemini-2.5-flash` | Modelo 2.5 flash (qualidade superior, cota separada da 2.0) |
| 3 | `gemini-2.0-flash` | Modelo flash estável v2.0 (fallback) |
| 4 | `gemini-2.0-flash-lite` | Modelo flash-lite v2.0 (último fallback) |

> O modelo `gemini-1.5-flash` foi removido — descontinuado na API v1beta (retornava 404). A família 2.5 é priorizada por possuir cota separada da 2.0 no plano gratuito.

Todos os modelos usam **temperatura 0** (saída determinística) e máximo de **8192 tokens** de output. Documentos com mais de ~60.000 caracteres são truncados inteligentemente (mantendo início e fim com aviso explícito) para caber na análise.

### Perspectivas do Usuário

A simplificação é personalizada de acordo com a perspectiva selecionada no modal inicial:

| Perspectiva | Comportamento |
|-------------|---------------|
| **Autor** (quem moveu a ação) | Usa "VOCÊ" para o autor, nome real do réu |
| **Réu** (quem responde a ação) | Usa "VOCÊ" para o réu, nome real do autor |
| **Não Informado** | Linguagem neutra com nomes reais de todas as partes |

**Detecção automática de ECA/Ato Infracional**: Quando o backend identifica que o documento trata de ato infracional (Estatuto da Criança e do Adolescente), aplica instrucional específico: usa o nome completo do adolescente (nunca "você"), adota linguagem neutra e respeita as regras de proteção do ECA. Isso ocorre independentemente da perspectiva escolhida.

### Indicadores de Resultado

| Indicador | Significado |
|-----------|-------------|
| ✅ **VITÓRIA TOTAL** | Todos os pedidos foram atendidos |
| ❌ **DERROTA** | Os pedidos foram negados |
| ⚠️ **VITÓRIA PARCIAL** | Parte dos pedidos foi atendida |
| ⏳ **AGUARDANDO** | Ainda não há decisão final |
| 📋 **ANDAMENTO** | Despacho processual (sem decisão de mérito) |

---

## Arquitetura

### Stack Tecnológico

```
┌─────────────────────────────────────────────────────┐
│                    FRONTEND                          │
│  Vanilla JavaScript (ES6+) · HTML5/CSS3             │
│  SPA · Responsivo · Modo Escuro · Chat Contextual   │
├─────────────────────────────────────────────────────┤
│                    BACKEND                           │
│  Python 3.11 · Flask 3.0.3 · Gunicorn 21.2.0       │
├─────────────────────────────────────────────────────┤
│               PROCESSAMENTO                          │
│  PyMuPDF · Tesseract OCR · Pillow · OpenCV          │
│  ReportLab · QRCode                                  │
├─────────────────────────────────────────────────────┤
│                      IA                              │
│  Google Gemini API (Multi-modelo com fallback)       │
├─────────────────────────────────────────────────────┤
│                  SEGURANÇA                           │
│  Fernet (CPF) · SHA-256 · Rate Limiting · LGPD      │
├─────────────────────────────────────────────────────┤
│               ARMAZENAMENTO                          │
│  SQLite (contadores agregados + auditoria - LGPD)    │
├─────────────────────────────────────────────────────┤
│               INFRAESTRUTURA                         │
│  Render.com · Docker · 2 Workers · 512MB RAM         │
└─────────────────────────────────────────────────────┘
```

### Estrutura do Projeto

```
projeto-linguaguem-simples/
│
├── app.py                          # Aplicação Flask principal
│                                   #   - Rotas do app público (/processar, /chat, /narrar)
│                                   #   - Rotas do painel admin (/admin/login, /admin, /admin/usuarios...)
│                                   #   - Integração com Gemini AI (google-genai SDK)
│                                   #   - Processamento de PDF/imagem
│                                   #   - Rate limiting, cache e tokens
│                                   #   - Validação de CPF e documentos judiciais
│                                   #   - Limpeza automática LGPD
│
├── database.py                     # Sistema de estatísticas e segurança
│                                   #   - Schema SQLite (14 tabelas)
│                                   #   - Contadores agregados (LGPD)
│                                   #   - Cofre criptografado de CPF
│                                   #   - Controle de tokens diários
│                                   #   - Auditoria de IP do app público
│                                   #   - Gestão de usuários do painel admin (Fase 2)
│                                   #   - Tokens de reset de senha (one-time)
│                                   #   - Audit log do painel admin
│                                   #   - init_db com retry/backoff para deploys
│                                   #   - Limpeza automática
│
├── auth.py                         # Autenticação multi-usuário do painel admin
│                                   #   - autenticar(username, senha)
│                                   #   - admin_required / superadmin_required
│                                   #   - Sessão com timeout de 30 min
│                                   #   - Bootstrap automático do 1º admin
│                                   #   - audit_action() com debounce
│
├── pricing.py                      # Preços oficiais Gemini + conversão USD→BRL
│                                   #   - Tabela de preços por 1M tokens (8 modelos)
│                                   #   - custo_brl(modelo, tokens_in, tokens_out)
│                                   #   - Câmbio configurável via USD_TO_BRL
│
├── gerador_pdf.py                  # Geração de PDF simplificado
│                                   #   - Layout com header/footer
│                                   #   - Marca d'água anti-fraude
│                                   #   - QR code de validação
│                                   #   - Fontes personalizadas
│
├── templates/
│   ├── index.html                  # Interface principal SPA (com identidade TJTO)
│   ├── validar.html                # Página de validação de documentos
│   └── admin/                      # Painel administrativo
│       ├── _nav.html               # Componente: barra com logo, nav, papel
│       ├── login.html              # Tela de login (username + senha)
│       ├── dashboard.html          # Dashboard com KPIs, gráficos, custos
│       ├── usuarios.html           # CRUD de usuários (só superadmin)
│       ├── reset.html              # Reset de senha via token one-time
│       ├── conta.html              # Trocar a própria senha
│       └── audit.html              # Audit log paginado (só superadmin)
│
├── static/
│   ├── style.css                   # Estilos do app público
│   ├── admin.css                   # Estilos do painel administrativo
│   ├── admin.js                    # Lógica do dashboard (Chart.js, polling 30s)
│   ├── chart.umd.min.js            # Chart.js 4.4.1 (servido localmente, sem CDN)
│   ├── avatar.js                   # Interações do avatar com voz
│   ├── logo.png                    # Logo do projeto
│   ├── avatar.png                  # Imagem do avatar JUS Bot
│   ├── inovassol.png               # Logo da INOVASSOL
│   ├── logojto.png                 # Logo Poder Judiciário do Tocantins (header/footer)
│   ├── logotjto.png                # Logo TJTO (marca d'água do PDF)
│   ├── vou-começar.mp3             # Áudio: "Vou começar"
│   └── prontinho-simplifiquei.mp3  # Áudio: "Prontinho, simplifiquei"
│
├── gunicorn_config.py              # Configuração do servidor de produção
├── render.yaml                     # Configuração de deploy no Render
├── Dockerfile.txt                  # Configuração Docker
├── install_tesseract.sh            # Script de instalação do Tesseract OCR
├── requirements.txt                # Dependências Python
├── SECURITY_REQUIREMENTS.md        # Documentação de requisitos de segurança
├── CLAUDE.md                       # Guia para assistentes AI
├── stats.db                        # Banco SQLite (contadores LGPD + admin)
├── .gitignore                      # Regras de exclusão Git
└── .dockerignore                   # Regras de exclusão Docker
```

---

## Instalação

### Pré-requisitos

- **Python 3.11+**
- **Tesseract OCR** com dados de idioma português
- **Chave de API do Google Gemini**

### 1. Instalar o Tesseract OCR

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng

# macOS (Homebrew)
brew install tesseract tesseract-lang

# Windows
# Baixe o instalador oficial em: https://github.com/tesseract-ocr/tesseract/releases
# Após instalar, adicione o caminho ao PATH do sistema
```

### 2. Clonar o Repositório

```bash
git clone https://github.com/andreviniciusdioliveira/projeto-linguaguem-simples.git
cd projeto-linguaguem-simples
```

### 3. Criar Ambiente Virtual

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 4. Instalar Dependências

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configurar Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto:

```env
# Obrigatório
GEMINI_API_KEY=sua_chave_api_gemini_aqui

# Recomendado em produção (evita que sessões caiam a cada restart)
SECRET_KEY=sua_chave_secreta_flask

# Painel administrativo (Fase 2)
# Hash da senha do 1º superadmin. Gere com:
#   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('SUA_SENHA'))"
ADMIN_PASSWORD_HASH=pbkdf2:sha256:600000$...
# Câmbio USD→BRL para o cálculo de custos no dashboard (default: 5.0)
USD_TO_BRL=5.0

# Opcionais
PORT=8080
FLASK_ENV=production
ADMIN_TOKEN=seu_token_legacy_para_admin_auditoria
CPF_VAULT_KEY=sua_chave_fernet_para_criptografia_de_cpf
IP_HASH_SALT=salt_aleatorio_para_hash_de_ip
CPF_HASH_SALT=salt_aleatorio_para_hash_de_cpf
```

### 6. Obter a Chave da API Gemini

1. Acesse [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Faça login com sua conta Google
3. Clique em **"Create API Key"**
4. Copie a chave e cole no arquivo `.env`

### 7. Executar

```bash
# Modo desenvolvimento
python app.py
# Acesse: http://localhost:8080

# Modo produção (recomendado)
gunicorn app:app --config gunicorn_config.py
```

---

## Deploy

### Render (Recomendado)

O projeto já inclui o arquivo `render.yaml` configurado para deploy automático:

1. Faça fork deste repositório
2. Crie uma conta no [Render](https://render.com)
3. Conecte sua conta GitHub
4. Clique em **"New" > "Blueprint"** e selecione o repositório
5. Configure as variáveis de ambiente no dashboard:
   - `GEMINI_API_KEY` (obrigatório)
   - `SECRET_KEY` (recomendado — sem isso a sessão admin cai a cada restart)
   - `ADMIN_PASSWORD_HASH` (recomendado — habilita o painel `/admin`)
   - `USD_TO_BRL` (opcional — câmbio para custos Gemini, default 5.0)
   - `CPF_VAULT_KEY` (recomendado — persistência do cofre de CPFs entre deploys)
6. O deploy será automático a cada push na branch `main`

**Configuração do Render:**

| Parâmetro | Valor |
|-----------|-------|
| Ambiente | Python 3.11.0 |
| Região | Oregon |
| Plano | Free |
| Build | `pip install -r requirements.txt` + Tesseract |
| Start | `gunicorn app:app --config gunicorn_config.py` |
| Health Check | `GET /health` |

### Docker

```bash
# Build da imagem
docker build -f Dockerfile.txt -t entenda-aqui .

# Executar container
docker run -d \
  -p 8080:8080 \
  -e GEMINI_API_KEY=sua_chave_aqui \
  -e SECRET_KEY=sua_chave_secreta \
  -e CPF_VAULT_KEY=sua_chave_fernet \
  --name entenda-aqui \
  entenda-aqui
```

A imagem Docker (`python:3.11-slim`) inclui:
- Tesseract OCR com dados em português e inglês
- Poppler utils para processamento de PDF
- Health check automático a cada 30 segundos
- 2 workers Gunicorn com timeout de 120s

### Outras Plataformas

<details>
<summary><strong>Heroku</strong></summary>

```bash
heroku create entenda-aqui
heroku config:set GEMINI_API_KEY=sua_chave
heroku buildpacks:add https://github.com/heroku/heroku-buildpack-apt
git push heroku main
```

Crie um arquivo `Aptfile` na raiz:
```
tesseract-ocr
tesseract-ocr-por
```
</details>

<details>
<summary><strong>Railway</strong></summary>

```bash
railway login
railway new
railway add
railway variables set GEMINI_API_KEY=sua_chave
railway up
```
</details>

---

## API Endpoints

### Endpoints do App Público

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Interface principal da aplicação |
| `GET` | `/csrf_token` | Retorna token CSRF para validação de sessão |
| `POST` | `/validar_cpf` | Valida CPF e verifica rate limit por CPF |
| `POST` | `/processar` | Processa documento enviado (PDF/imagem) |
| `POST` | `/processar_texto` | Processa texto jurídico colado diretamente |
| `POST` | `/chat` | Chat contextual sobre o documento processado |
| `POST` | `/narrar` | Gera narração em MP3 do texto simplificado (voz neural via edge-tts) |
| `GET` | `/download_pdf` | Baixa o PDF simplificado gerado (vínculo com sessão) |
| `GET` | `/validar/<doc_id>` | Página de validação de integridade |
| `POST` | `/validar/<doc_id>/verificar` | Verifica hash de integridade do documento |
| `POST` | `/feedback` | Registra feedback (positivo/negativo) |
| `GET` | `/api/stats` | Estatísticas agregadas (LGPD) |
| `GET` | `/admin/auditoria` | Painel legacy de auditoria de IPs (requer ADMIN_TOKEN) |
| `GET` | `/health` | Health check da aplicação |

### Endpoints do Painel Administrativo

Todas as rotas abaixo (exceto `/admin/login` e `/admin/reset/<token>`) exigem sessão autenticada. Rotas marcadas com 🔒 exigem papel `superadmin`.

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/admin/login` | Tela de login (username + senha) |
| `POST` | `/admin/login` | Autentica e abre sessão |
| `POST` | `/admin/logout` | Encerra sessão |
| `GET` | `/admin` | Dashboard com KPIs, custos e gráficos |
| `GET` | `/admin/api/stats` | JSON com todas as métricas (alimenta gráficos) |
| `GET` | `/admin/usuarios` 🔒 | Lista usuários do painel |
| `POST` | `/admin/usuarios/criar` 🔒 | Cria novo usuário |
| `POST` | `/admin/usuarios/<id>/ativar` 🔒 | Toggle de ativo/desativado |
| `POST` | `/admin/usuarios/<id>/reset` 🔒 | Gera token one-time de reset (24h) |
| `GET` | `/admin/reset/<token>` | Tela de redefinição de senha (sem auth, com token válido) |
| `POST` | `/admin/reset/<token>` | Aplica nova senha e consome token |
| `GET` | `/admin/conta` | Info da conta + form de troca de senha |
| `POST` | `/admin/conta/senha` | Troca a própria senha |
| `GET` | `/admin/audit` 🔒 | Audit log paginado com filtros |

### POST `/validar_cpf`

Valida o CPF do usuário antes do processamento de documentos.

**Request:**
```json
{
  "cpf": "123.456.789-09"
}
```

**Response (200):**
```json
{
  "valido": true,
  "documentos_restantes": 4,
  "limite_diario": 5
}
```

**Response (429 - Rate limit):**
```json
{
  "valido": true,
  "erro": "Limite diário atingido",
  "documentos_restantes": 0,
  "limite_diario": 5
}
```

### POST `/processar`

Processa um documento jurídico e retorna a simplificação.

**Request:**
```
Content-Type: multipart/form-data

file: <arquivo PDF ou imagem> (max 10MB)
perspectiva: "autor" | "reu" | "nao_informado" (opcional)
cpf: "12345678909" (opcional)
```

**Formatos aceitos:** PDF, PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP

**Response (200):**
```json
{
  "sucesso": true,
  "resultado": "Texto simplificado em Markdown...",
  "tipo_documento": "sentenca",
  "urgencia": "media",
  "modelo_usado": "gemini-2.0-flash",
  "perguntas_sugeridas": ["Quais são os prazos?", "..."],
  "pdf_url": "/download_pdf?file=simplificado_abc123.pdf",
  "doc_id": "TJTO-20260206-A1B2C3D4",
  "validacao_url": "/validar/TJTO-20260206-A1B2C3D4"
}
```

### POST `/processar_texto`

Processa texto jurídico colado diretamente pelo usuário.

**Request:**
```json
{
  "texto": "Texto do documento jurídico...",
  "perspectiva": "autor",
  "cpf": "12345678909"
}
```

**Response:** Mesmo formato de `/processar`.

### POST `/chat`

Permite que o usuário faça perguntas sobre o documento já processado. O chat é contextual — responde apenas sobre o conteúdo simplificado da sessão atual.

**Request:**
```json
{
  "pergunta": "Quais são os prazos desse mandado?"
}
```

**Response (200):**
```json
{
  "sucesso": true,
  "resposta": "Resposta em linguagem simples sobre o documento..."
}
```

Requer sessão ativa com um documento já processado. O tamanho da pergunta é limitado para controlar custo de tokens.

### POST `/narrar`

Gera um arquivo MP3 do texto simplificado utilizando a voz neural `pt-BR-FranciscaNeural` via [`edge-tts`](https://github.com/rany2/edge-tts) (vozes neurais da Microsoft, gratuitas, sem necessidade de API key).

**Request:**
```json
{
  "texto": "Texto simplificado a ser narrado..."
}
```

**Response (200):** Arquivo `audio/mpeg` (MP3) gerado em streaming.

**Response (503):** `edge-tts` indisponível no servidor — o frontend cai automaticamente no `Web Speech API` do navegador como fallback.

**Características:**

- **Voz padrão**: `pt-BR-FranciscaNeural` (timbre natural, sem sotaque robotizado)
- **Limite de texto**: 8.000 caracteres (protege o worker contra timeout no Render free tier)
- **Pré-processamento**: o backend remove markdown, emojis e caracteres de moldura antes do TTS — evita que o leitor pronuncie `"#"` como `"jogo da velha"`, `"*"`, `` "`" ``, `"■"`, `"═"` etc.
- **Cache por sessão**: hash composto por `(session_id + voz + primeiros 256 chars do texto)` reaproveita MP3s já gerados na mesma sessão
- **LGPD**: arquivo MP3 registrado para auto-deleção em **30 minutos**; nenhum texto é persistido em banco
- **Fallback duplo**: se `edge-tts` falhar (rede, rate limit da Microsoft) ou estiver indisponível, o frontend usa `SpeechSynthesisUtterance` do navegador

### GET `/health`

Verifica o status da aplicação.

**Response (200):**
```json
{
  "status": "ok",
  "gemini_configurado": true,
  "tesseract_disponivel": true,
  "modelos_disponiveis": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "..."],
  "total_documentos": 1250,
  "documentos_hoje": 42,
  "tokens": {
    "tokens_total": 5000000,
    "limite_diario": 171600000,
    "percentual_uso": 2.9
  }
}
```

### GET `/api/stats`

Retorna estatísticas agregadas em conformidade com a LGPD.

**Response (200):**
```json
{
  "total_documentos": 1250,
  "documentos_hoje": 42,
  "por_tipo": {
    "sentenca": 520,
    "mandado": 310,
    "acordao": 200,
    "despacho": 220
  },
  "tipo_mais_comum": "sentenca",
  "milestone_atual": {"valor": 1000, "nome": "Prata", "emoji": "🥈"},
  "proximo_milestone": {"valor": 10000, "nome": "Ouro", "emoji": "🥇"},
  "progresso_percentual": 12,
  "feedback": {
    "positivo": 890,
    "negativo": 45,
    "taxa_satisfacao": 95
  }
}
```

---

## LGPD & Privacidade

O Entenda Aqui foi projetado desde a concepção para estar em total conformidade com a **Lei Geral de Proteção de Dados (Lei nº 13.709/2018)**.

### Princípios Aplicados

| Princípio LGPD | Implementação |
|-----------------|---------------|
| **Finalidade** | Dados usados exclusivamente para estatísticas agregadas |
| **Necessidade** | Coleta mínima — apenas contadores, sem dados pessoais |
| **Transparência** | Aviso legal visível na interface |
| **Segurança** | CPFs criptografados com Fernet, IPs anonimizados por SHA-256 |
| **Prevenção** | Threads de limpeza automática impedem acúmulo de dados |

### O que **NÃO** é armazenado

- Conteúdo dos documentos enviados
- Dados pessoais dos usuários
- CPFs em texto claro (apenas hash irreversível ou criptografia temporária)
- Texto original ou simplificado
- Áudios de narração (MP3 transitório, auto-deletado em 30 min)
- Cookies de rastreamento

### O que **É** armazenado (somente agregados)

| Dado | Retenção | Propósito |
|------|----------|-----------|
| Contadores totais | Permanente | Milestone de uso |
| Contagem por tipo de documento | Permanente | Estatística de tipos |
| Contagem diária | 30 dias | Tendência de uso |
| Feedback (positivo/negativo) | Permanente | Taxa de satisfação |
| Hashes de validação | 30 dias | Verificação de integridade |
| Auditoria admin (hash de IP + metadados) | 30 dias | Segurança operacional |
| Uso de tokens da API | 7 dias | Controle de custos |
| CPF criptografado (Fernet) | 1 dia | Rate limiting por CPF |
| Contagem de uso por CPF | 1 dia | Limite diário |
| Rate limit combinado CPF+IP | 1 dia | Proteção anti-botnet |

### Limpeza Automática

| Recurso | Frequência | Ação |
|---------|------------|------|
| Arquivos temporários | A cada 60 segundos | Remove arquivos > 30 minutos |
| Cache de resultados | A cada 1 hora | Remove entradas > 1 hora |
| Estatísticas diárias | A cada 24 horas | Remove registros > 30 dias |
| Validações expiradas | A cada 24 horas | Remove registros > 30 dias |
| Logs de auditoria | A cada 24 horas | Remove registros > 30 dias |
| Uso de tokens | A cada 24 horas | Remove registros > 7 dias |
| Cofre de CPF | A cada 24 horas | Remove todos os registros do dia anterior |
| Rate limit de CPF | A cada 24 horas | Remove contagens do dia anterior |
| Rate limit CPF+IP | A cada 24 horas | Remove contagens do dia anterior |

---

## Banco de Dados

O sistema utiliza **SQLite** com 14 tabelas, todas projetadas para armazenar apenas dados agregados ou temporários:

### Tabelas do app público

| Tabela | Propósito | Dados Sensíveis | Retenção |
|--------|-----------|:---------------:|----------|
| `stats_geral` | Contador total + timestamps | Nenhum | Permanente |
| `stats_por_tipo` | Contagem por tipo de documento | Nenhum | Permanente |
| `stats_diarias` | Contagem diária | Nenhum | 30 dias |
| `stats_feedback` | Contadores de feedback | Nenhum | Permanente |
| `validacao_documentos` | Hashes SHA-256 (sem conteúdo) | Nenhum | 30 dias |
| `audit_ip` | Auditoria por requisição (hash IP + metadados + tokens + tempo) | Hash de IP (com salt) | 30 dias |
| `token_usage_diario` | Consumo de tokens por dia | Nenhum | 7 dias |
| `cpf_vault` | CPFs criptografados (Fernet) | CPF criptografado | 1 dia |
| `cpf_rate_limit` | Contadores de uso por CPF | Hash de CPF | 1 dia |
| `cpf_ip_rate_limit` | Rate limiting combinado CPF+IP (anti-botnet) | Hash de CPF + hash de IP | 1 dia |

### Tabelas do painel administrativo

| Tabela | Propósito | Dados Sensíveis | Retenção |
|--------|-----------|:---------------:|----------|
| `admin_users` | Usuários do painel (id, username, password_hash, role, ativo) | Hash de senha (scrypt) | Permanente até desativação |
| `admin_password_reset_tokens` | Tokens one-time de reset de senha | Token aleatório | 24h ou até uso (limpeza após 7d) |
| `admin_audit` | Eventos de auditoria do painel | Hash de IP (com salt) | 180 dias |
| `admin_login_attempts` | Tentativas de login (brute-force protection) | Hash de IP | 24h |

Todas as operações de banco usam **lock de thread** para segurança em ambiente multi-worker. IPs e CPFs nunca são armazenados em texto claro — apenas hashes SHA-256 com salt (irreversíveis) ou criptografia Fernet temporária. Senhas do painel admin usam **scrypt** via `werkzeug.security`.

### Resiliência em deploys

O `init_db()` faz **retry com backoff exponencial** (1s, 2s, 4s, 8s) e configura `PRAGMA busy_timeout = 30000` antes de qualquer DDL. Isso evita o erro `database is locked` durante deploys do Render (estilo blue/green), em que o container antigo segura o lock por alguns segundos enquanto o novo sobe. Janela total tolerada: ~46s. Migrações de coluna são **aditivas** via `ALTER TABLE ADD COLUMN` — nunca destrutivas.

---

## Segurança

### Medidas Implementadas

- **Validação de Upload**: Whitelist de extensões + limite de 10MB
- **Validação de MIME por Magic Bytes**: Verifica tipo real do arquivo antes do processamento
- **Sanitização de Nomes**: `werkzeug.secure_filename()` em todos os uploads
- **Proteção Path Traversal**: Validação de caminho real vs diretório temporário
- **Proteção CSRF**: Token por sessão em endpoints POST críticos (via `/csrf_token`)
- **Rate Limiting por IP**: 10 req/min + 20 docs/dia por IP com limpeza automática
- **Rate Limiting por CPF**: 5 documentos/dia por CPF
- **Rate Limiting Combinado CPF+IP**: 3 documentos/dia por par (CPF, IP) — proteção anti-botnet
- **Sessões Seguras**: Cookies `HttpOnly`, `SameSite=Lax`, `Secure` em HTTPS, expiração de 1 hora
- **Security Headers**: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- **Admin Protegido**: Endpoint de auditoria requer `ADMIN_TOKEN` (Bearer ou query param)
- **Vínculo PDF↔Sessão**: Apenas a sessão que gerou o PDF pode baixá-lo (anti-enumeração)
- **Anti-Injeção de Prompt**: Validação e limpeza do output da IA (remove vazamentos de instruções)
- **Anti-Fraude em PDF**: Marca d'água diagonal + logotipos com rotação variável + QR code + hash SHA-256
- **Cofre Criptografado**: CPFs armazenados com criptografia Fernet (AES-128-CBC), apagados diariamente
- **Hashes com Salt**: IPs e CPFs armazenados apenas como SHA-256 com salt (irreversíveis)
- **Limite de Tokens**: 171,6M tokens/dia para prevenir abuso da API
- **Validação Judicial**: Pré-detecção (regex) bloqueia documentos não emitidos pelo Poder Judiciário antes de enviar ao Gemini
- **Detecção de Segredo de Justiça**: Bloqueia documentos sigilosos (art. 189 CPC, Lei Maria da Penha, ECA, crimes contra dignidade sexual, interceptação telefônica), exceto mandados/citações/intimações

### Variáveis Sensíveis

| Variável | Obrigatória | Descrição |
|----------|:-----------:|-----------|
| `GEMINI_API_KEY` | Sim | Chave da API Google Gemini |
| `SECRET_KEY` | **Recomendada em prod** | Chave de sessão Flask. Se ausente, é auto-gerada — mas isso faz com que **as sessões caiam a cada restart** (incluindo o login admin). Configure um valor estável em produção. |
| `ADMIN_PASSWORD_HASH` | **Recomendada em prod** | Hash da senha do 1º superadmin do painel. Gere localmente: `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('SUA_SENHA'))"`. Usado só no bootstrap (após o 1º init, a senha vive na tabela `admin_users` e pode ser trocada via UI). |
| `USD_TO_BRL` | Não | Câmbio para cálculo de custos Gemini em reais no painel admin (default: `5.0`). Editável sem redeploy. |
| `ADMIN_TOKEN` | Não | Token do painel **legacy** `/admin/auditoria` (auditoria de IPs do app público). Diferente do `ADMIN_PASSWORD_HASH`, que protege o novo painel `/admin`. |
| `CPF_VAULT_KEY` | Não | Chave Fernet para criptografia de CPF. Se ausente, é gerada temporariamente — CPFs criptografados são perdidos a cada restart. |
| `IP_HASH_SALT` | Não | Salt para hash SHA-256 de IPs (recomendado definir em produção) |
| `CPF_HASH_SALT` | Não | Salt para hash SHA-256 de CPFs (recomendado definir em produção) |
| `FLASK_ENV` | Não | `production` (padrão) ou `development` para modo debug |
| `PORT` | Não | Porta de execução (padrão: 8080) |

Nunca commite chaves de API. Use variáveis de ambiente ou arquivos `.env` (incluído no `.gitignore`).

**Geração rápida das chaves recomendadas:**

```bash
# SECRET_KEY (sessões Flask)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# ADMIN_PASSWORD_HASH (senha do superadmin)
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('SUA_SENHA_FORTE'))"

# CPF_VAULT_KEY (qualquer string ≥ 32 chars; é hashada com SHA-256 internamente)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## Configuração de Produção

### Gunicorn

O arquivo `gunicorn_config.py` está otimizado para o **Render Free Tier (512MB RAM)**:

| Parâmetro | Valor | Justificativa |
|-----------|-------|---------------|
| Workers | 2 | Limite de memória do free tier |
| Timeout | 120s | Documentos grandes + OCR + IA |
| Max Requests | 100 | Reciclagem de worker para liberar memória |
| Preload App | True | Compartilha memória entre workers |
| Worker Tmp Dir | `/dev/shm` | RAM ao invés de disco para temp files |
| Keep-alive | 5s | Reutilização de conexões |

### Limites da Aplicação

| Recurso | Limite |
|---------|--------|
| Tamanho máximo de arquivo | 10 MB |
| Requisições por minuto/IP | 10 |
| Documentos por dia/IP | 20 |
| Documentos por dia/CPF | 5 |
| Documentos por dia por par (CPF, IP) | 3 (anti-botnet) |
| Tokens diários da API | 171.600.000 |
| Tempo máximo por requisição | 120 segundos |
| Cache de resultados | 50 entradas, 1 hora |
| Arquivos temporários | Removidos após 30 min |
| Tamanho máximo de texto para narração | 8.000 caracteres |
| Documentos máximos por análise | Truncado a ~60.000 caracteres (mantém início + fim) |
| Workers simultâneos | 2 |

---

## Dependências

### Python

| Pacote | Versão | Propósito |
|--------|--------|-----------|
| Flask | 3.0.3 | Framework web |
| Werkzeug | 3.0.3 | Utilitários WSGI + hash de senha (scrypt) do painel admin |
| gunicorn | 21.2.0 | Servidor de produção |
| google-genai | ≥1.0 | API do Google Gemini (sucessor do `google-generativeai`, descontinuado) |
| pymupdf | 1.24.2 | Extração de texto de PDF |
| pytesseract | 0.3.10 | Interface para Tesseract OCR |
| Pillow | 10.4.0 | Processamento de imagens |
| opencv-python-headless | 4.8.1.78 | Pré-processamento avançado (opcional) |
| numpy | 1.24.3 | Operações numéricas |
| reportlab | 4.2.2 | Geração de PDF |
| qrcode[pil] | 7.4.2 | Geração de QR code |
| requests | 2.31.0 | Cliente HTTP |
| python-dotenv | 1.0.1 | Variáveis de ambiente |
| regex | 2023.12.25 | Expressões regulares avançadas |
| certifi | 2024.2.2 | Certificados SSL |
| urllib3 | 2.2.1 | Cliente HTTP |
| cryptography | 42.0.5 | Criptografia Fernet para cofre de CPF (LGPD) |
| edge-tts | 6.1.18 | Narração com vozes neurais (TTS) — sem API key |

### Sistema

| Dependência | Obrigatória | Propósito |
|-------------|:-----------:|-----------|
| Tesseract OCR | Não* | OCR para documentos digitalizados |
| Tesseract `por` | Não* | Dados de idioma português |
| Tesseract `eng` | Não | Dados de idioma inglês |
| Poppler Utils | Não | Utilitários PDF (Docker) |

\* A aplicação funciona sem Tesseract, mas documentos digitalizados/imagens não serão processados.

---

## Desenvolvimento

### Executando Localmente

```bash
# Ativar ambiente virtual
source venv/bin/activate

# Definir variável de ambiente
export GEMINI_API_KEY="sua_chave_aqui"

# Executar em modo de desenvolvimento
python app.py

# A aplicação estará disponível em http://localhost:8080
```

### Verificando Funcionamento

```bash
# Health check
curl http://localhost:8080/health

# Estatísticas
curl http://localhost:8080/api/stats

# Validar CPF
curl -X POST http://localhost:8080/validar_cpf \
  -H "Content-Type: application/json" \
  -d '{"cpf": "123.456.789-09"}'

# Processar documento (exemplo)
curl -X POST http://localhost:8080/processar \
  -F "file=@documento.pdf" \
  -F "perspectiva=autor" \
  -F "cpf=12345678909"

# Processar texto colado
curl -X POST http://localhost:8080/processar_texto \
  -H "Content-Type: application/json" \
  -d '{"texto": "Texto do documento...", "perspectiva": "autor"}'
```

### Testes Manuais Recomendados

O projeto não possui testes automatizados. Ao fazer alterações, verifique:

1. Validação de CPF (válido, inválido, rate limit)
2. Upload de PDF com texto nativo
3. Upload de documento digitalizado (OCR)
4. Upload de imagem (PNG/JPG)
5. Entrada de texto colado via `/processar_texto`
6. Chat contextual sobre documento via `/chat`
7. Rejeição de documentos não-judiciais (petições, reclamações trabalhistas)
8. Rejeição de documentos em segredo de justiça (exceto mandados/intimações)
9. Rate limiting por IP (enviar 11 requisições em 1 minuto)
10. Rate limiting por CPF (enviar 6 documentos com mesmo CPF)
11. Rate limiting combinado CPF+IP (4 documentos com mesmo par CPF+IP)
12. Download do PDF simplificado (marca d'água + QR code + hash)
13. Validação de integridade via QR code em `/validar/<doc_id>`
14. Alternância de tema escuro/claro
15. Interface em dispositivo móvel
16. Limpeza automática de arquivos temporários

---

## Monitoramento

### Health Check

```
GET /health
```

Retorna o status completo da aplicação incluindo:
- Estado do servidor
- Configuração da API Gemini
- Disponibilidade do Tesseract OCR
- Modelos disponíveis e estatísticas de uso
- Contagem de documentos processados
- Uso de tokens da API (total e limite diário)

### Estatísticas de Uso

```
GET /api/stats
```

Retorna dados agregados em conformidade com a LGPD:
- Total de documentos processados
- Contagem do dia
- Distribuição por tipo de documento
- Milestones (Bronze 🥉 → Prata 🥈 → Ouro 🥇 → Diamante 💎)
- Taxa de satisfação dos usuários

### Painel de Auditoria

```
GET /admin/auditoria?token=SEU_ADMIN_TOKEN
```

Disponível apenas com `ADMIN_TOKEN` configurado. Mostra:
- Registros de processamento com IP e metadados
- Filtros por IP, tipo de documento e data
- Paginação e contagem de IPs únicos
- Distribuição por tipo de documento

---

## Contribuindo

Contribuições são bem-vindas. Para contribuir:

1. Faça fork do repositório
2. Crie uma branch para sua feature (`git checkout -b feature/nova-funcionalidade`)
3. Faça commit das alterações (`git commit -m 'Adicionar nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request

### Diretrizes

- Mantenha a **conformidade LGPD** — nunca armazene dados pessoais em texto claro
- Use **português** para toda interface voltada ao usuário
- Siga os **padrões existentes** de código (logging com emojis, tratamento de erros com fallback)
- Teste em **dispositivos móveis** — a interface deve ser responsiva
- Respeite os **limites de memória** — o deploy roda em 512MB
- Valide que **documentos não-judiciais** continuam sendo bloqueados
- Verifique a **limpeza automática** de dados temporários (CPF, tokens, arquivos)

---

## Licença

Este projeto foi desenvolvido pela **INOVASSOL - Centro de Inovação AI** para promover a acessibilidade jurídica no Brasil.

---

## Contato

**INOVASSOL - Centro de Inovação AI**

Projeto desenvolvido para democratizar o acesso à justiça, tornando documentos jurídicos compreensíveis para todos os cidadãos brasileiros.

---

<p align="center">
  <sub>"A justiça deve ser acessível a todos, começando pela compreensão de seus documentos."</sub>
</p>

<p align="center">
 
</p>
