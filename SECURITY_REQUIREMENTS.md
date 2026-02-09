# Requisitos de Segurança — Entenda Aqui

**Documento para apresentação à Diretoria**
**Data**: 2026-02-09
**Versão**: 1.0
**Classificação**: Interno — Uso da Diretoria

---

## 1. Resumo Executivo

O sistema **Entenda Aqui** é uma aplicação web que simplifica documentos jurídicos complexos em linguagem acessível, utilizando inteligência artificial (Google Gemini). Este documento apresenta os requisitos e mecanismos de segurança implementados, com foco especial na conformidade com a **LGPD** (Lei Geral de Proteção de Dados — Lei nº 13.709/2018).

### Pilares de Segurança Adotados

| Pilar | Descrição |
|---|---|
| **Privacidade por Design** | Nenhum dado pessoal ou conteúdo de documento é armazenado permanentemente |
| **Minimização de Dados** | Apenas contadores agregados e hashes são persistidos |
| **Exclusão Automática** | Mecanismos automáticos de limpeza em múltiplas camadas |
| **Defesa em Profundidade** | Múltiplas camadas de proteção contra diferentes vetores de ataque |

---

## 2. Conformidade com a LGPD

### 2.1 Princípio da Minimização de Dados

O sistema foi projetado para **nunca armazenar dados pessoais** ou conteúdo de documentos:

| Dado | Armazenado? | Justificativa |
|---|---|---|
| Conteúdo do documento | **NÃO** | Processado em memória e descartado |
| Nome do usuário | **NÃO** | Não solicitado |
| E-mail / telefone | **NÃO** | Não solicitado |
| Endereço IP | **NÃO** (apenas hash) | Hash SHA-256 com salt, irreversível |
| Estatísticas de uso | **SIM** (somente contadores) | Dados agregados, sem identificação individual |

**Referências no código:**
- Hash de IP: `database.py:274-281` — Função `gerar_hash_ip()` com SHA-256 + salt
- Hash de conteúdo: `database.py:265-271` — Função `gerar_hash_conteudo()` com SHA-256
- Geração de ID seguro: `database.py:255-262` — Usa `secrets.token_hex()` (criptograficamente seguro)

### 2.2 Exclusão Automática de Dados

O sistema implementa **três camadas de limpeza automática**:

| Camada | Frequência | Retenção | Referência |
|---|---|---|---|
| Arquivos temporários | A cada 60 segundos | 30 minutos | `app.py:136-173` |
| Estatísticas diárias | A cada 24 horas | 30 dias | `database.py:567-591` |
| Registros de auditoria | A cada 24 horas | 90 dias | `database.py:582` |
| Validações de documentos | A cada 24 horas | 30 dias | `database.py:581` |
| Cache de resultados | A cada 60 minutos | 60 minutos | `app.py:2131-2133` |

Todos os processos de limpeza executam como threads daemon, garantindo operação contínua sem intervenção manual.

### 2.3 Dados Armazenados no Banco de Dados

O banco de dados SQLite (`stats.db`) contém **exclusivamente**:

- **Contadores agregados**: total de documentos processados, quantidade por tipo
- **Contadores diários**: quantidade de documentos por dia (sem identificação)
- **Hashes**: SHA-256 de conteúdo e IP (irreversíveis)
- **Feedback**: contadores de feedback positivo/negativo

**Tabelas do banco** (`database.py:28-86`):
- `stats_geral` — Contadores gerais
- `stats_por_tipo` — Contadores por tipo de documento
- `stats_diarias` — Contadores diários
- `stats_feedback` — Contadores de feedback
- `validacao_documentos` — Hashes de validação (sem conteúdo)
- `audit_ip` — Logs de auditoria (sem conteúdo de documentos)

---

## 3. Controle de Acesso

### 3.1 Autenticação do Painel Administrativo

| Item | Implementação |
|---|---|
| Método | Token Bearer via header ou query parameter |
| Configuração | Variável de ambiente `ADMIN_TOKEN` |
| Endpoint protegido | `POST /admin/auditoria` |
| Resposta sem token | HTTP 403 — "Acesso negado. Token inválido." |
| Token ausente no servidor | HTTP 503 — Sistema indisponível |

**Referência**: `app.py:97-98, 2010-2024`

### 3.2 Limitação de Taxa (Rate Limiting)

| Parâmetro | Valor |
|---|---|
| Limite | 10 requisições por minuto por IP |
| Endpoints protegidos | `/processar` e `/chat` |
| Resposta ao exceder | HTTP 429 — "Limite de requisições excedido" |
| Limpeza de contadores | Automática, entradas expiram após 1 minuto |
| Thread-safety | Lock dedicado (`cleanup_lock`) |

**Referência**: `app.py:105-108, 208-229`

### 3.3 Gerenciamento de Sessão

| Item | Implementação |
|---|---|
| Duração da sessão | 1 hora (`PERMANENT_SESSION_LIFETIME`) |
| Chave secreta | Variável de ambiente ou `os.urandom(24)` |
| Proteção | Assinatura criptográfica (Flask default) |

**Referência**: `app.py:43-44`

---

## 4. Segurança de Upload de Arquivos

### 4.1 Validações Implementadas

| Validação | Detalhe | Referência |
|---|---|---|
| Tamanho máximo | 10 MB | `app.py:100` |
| Extensões permitidas | pdf, png, jpg, jpeg, gif, bmp, tiff, webp | `app.py:101-102` |
| Nome seguro | `werkzeug.secure_filename()` | `app.py:1539, 1760, 1887, 1907` |
| Verificação de presença | Rejeita requisição sem arquivo | `app.py:1508-1509` |
| Verificação de nome | Rejeita arquivo sem nome | `app.py:1522-1523` |
| Hash do arquivo | MD5 para identificação única | `app.py:1537` |

### 4.2 Prevenção de Path Traversal

O sistema implementa verificação de caminho real para impedir acesso a diretórios fora da área temporária:

```
safe_basename = secure_filename(os.path.basename(pdf_basename))
pdf_path_real = os.path.realpath(pdf_path)
temp_dir_real = os.path.realpath(TEMP_DIR)
if not pdf_path_real.startswith(temp_dir_real):
    → HTTP 403 — "Acesso não autorizado"
```

**Referência**: `app.py:1886-1895`

### 4.3 Ciclo de Vida dos Arquivos

```
Upload → Validação → Processamento em memória → Geração de resultado → Exclusão automática (30 min)
```

Nenhum arquivo é armazenado permanentemente. O armazenamento temporário utiliza o diretório do sistema (`tempfile.gettempdir()`), e os workers do Gunicorn utilizam `/dev/shm` (memória RAM).

---

## 5. Segurança da Infraestrutura

### 5.1 Servidor de Produção (Gunicorn)

| Parâmetro | Valor | Propósito |
|---|---|---|
| Workers | 2 | Limite de memória (512MB) |
| Timeout | 120 segundos | Prevenção de requisições penduradas |
| Graceful timeout | 30 segundos | Encerramento controlado |
| Max requests | 100 por worker | Reciclagem contra vazamento de memória |
| Max request jitter | 20 | Evita reciclagem simultânea |
| Limite de request line | 4.096 bytes | Prevenção de buffer overflow |
| Limite de header fields | 100 campos | Prevenção de abuso |
| Limite de header size | 8.190 bytes | Prevenção de buffer overflow |
| Diretório temp. do worker | `/dev/shm` (RAM) | Dados perdidos ao reiniciar |

**Referência**: `gunicorn_config.py`

### 5.2 Deployment (Render.com)

| Item | Configuração |
|---|---|
| Plano | Free tier |
| Região | Oregon (EUA) |
| Health check | Endpoint `/health` |
| Deploy automático | Ativado (push para main) |
| HTTPS/TLS | Gerenciado pela plataforma Render |
| Variáveis de ambiente | Configuradas via dashboard Render |

**Referência**: `render.yaml`

### 5.3 Gerenciamento de Chaves de API

| Prática | Implementação |
|---|---|
| Armazenamento | Exclusivamente em variáveis de ambiente |
| Código-fonte | Nenhuma chave hardcoded |
| Git | Arquivos `.env` no `.gitignore` |
| Render | `sync: false` para GEMINI_API_KEY |
| SECRET_KEY | Gerada automaticamente pelo Render (`generateValue: true`) |
| Fallback | `os.urandom(24)` — criptograficamente seguro |

**Referência**: `app.py:48-55`, `render.yaml:15-18`, `.gitignore:42-44`

---

## 6. Segurança do Banco de Dados

| Mecanismo | Detalhe |
|---|---|
| Motor | SQLite (arquivo local) |
| Prevenção de SQL Injection | Queries parametrizadas (`?` placeholders) em todas as consultas |
| Thread-safety | Lock dedicado (`db_lock`) para todas as operações |
| Dados sensíveis | Nenhum conteúdo de documento armazenado |
| IP de usuários | Somente hash SHA-256 com salt (irreversível) |
| Limpeza automática | Estatísticas: 30 dias / Auditoria: 90 dias |

**Referência**: `database.py:6-97`

---

## 7. Proteções contra Ataques Comuns

### 7.1 OWASP Top 10 — Cobertura

| Vulnerabilidade (OWASP) | Status | Mecanismo |
|---|---|---|
| **A01 — Broken Access Control** | ✅ Mitigado | Token de admin, rate limiting, validação de paths |
| **A02 — Cryptographic Failures** | ✅ Mitigado | SHA-256 para hashes, `os.urandom` para chaves, HTTPS via Render |
| **A03 — Injection** | ✅ Mitigado | Queries parametrizadas (SQL), subprocess com lista (OS), secure_filename |
| **A04 — Insecure Design** | ✅ Mitigado | Privacidade por design, minimização de dados, defesa em profundidade |
| **A05 — Security Misconfiguration** | ⚠️ Parcial | `debug=False` em produção, mas faltam security headers explícitos |
| **A06 — Vulnerable Components** | ✅ Mitigado | Dependências com versões fixas em `requirements.txt` |
| **A07 — Auth Failures** | ✅ Mitigado | Token-based admin, sessões com timeout de 1 hora |
| **A08 — Data Integrity Failures** | ✅ Mitigado | Hashes SHA-256 para validação de documentos |
| **A09 — Logging Failures** | ✅ Mitigado | Logging estruturado em todos os endpoints, auditoria de IPs |
| **A10 — SSRF** | ✅ Mitigado | Sem chamadas a URLs externas fornecidas pelo usuário |

### 7.2 Prevenção de XSS

- Respostas da API em formato JSON (`jsonify()`)
- Templates com autoescape do Jinja2 (padrão do Flask)
- Nenhum dado de usuário renderizado como HTML sem sanitização

### 7.3 Prevenção de Injeção de Comandos

- Subprocessos executados com lista de argumentos (não `shell=True`)
- Apenas comandos específicos do Tesseract OCR são executados
- Timeout de 10 segundos em subprocessos

**Referência**: `app.py:178-184`

### 7.4 Proteção de Conteúdo Jurídico Sensível

O sistema detecta e bloqueia automaticamente documentos classificados como **segredo de justiça**:

**Referência**: `app.py:1578-1597`

---

## 8. Criptografia e Hashing

### 8.1 Algoritmos Utilizados

| Algoritmo | Uso | Propósito |
|---|---|---|
| **SHA-256** | Hash de IP | Anonimização irreversível (LGPD) |
| **SHA-256** | Hash de conteúdo | Validação de integridade |
| **SHA-256 + salt** | Hash de IP com salt fixo | Proteção contra rainbow tables |
| **MD5** | Cache key / identificação de arquivo | Uso não-criptográfico (performance) |
| **os.urandom(24)** | Chave secreta Flask | Geração criptograficamente segura |
| **secrets.token_hex(4)** | IDs de documentos | Tokens criptograficamente seguros |

### 8.2 Nota sobre MD5

O MD5 é utilizado **exclusivamente** para geração de chaves de cache e identificação de arquivos — cenários onde colisões não representam risco de segurança. Para todas as operações sensíveis (anonimização de IP, validação de conteúdo), é utilizado SHA-256.

---

## 9. Resiliência e Disponibilidade

### 9.1 Sistema de Fallback de IA

O sistema implementa fallback automático entre 4 modelos de IA:

| Prioridade | Modelo | Características |
|---|---|---|
| 1 | gemini-2.5-flash-lite | Mais rápido, menor custo |
| 2 | gemini-2.5-flash | Balanceado |
| 3 | gemini-2.0-flash-exp | Experimental |
| 4 | gemini-1.5-flash | Fallback estável |

Se um modelo falhar (rate limit, erro, indisponibilidade), o sistema automaticamente tenta o próximo na lista.

**Referência**: `app.py:54-92`

### 9.2 Monitoramento de Saúde

O endpoint `/health` fornece status em tempo real:

- Status da aplicação
- Configuração da API Gemini
- Disponibilidade do Tesseract OCR
- Total de documentos processados
- Documentos processados hoje

**Referência**: `app.py:2076-2101`

### 9.3 Tratamento de Erros

- Handlers customizados para HTTP 404 e 500
- Respostas de erro em JSON (sem exposição de stack traces)
- Logging estruturado com prefixos visuais (✅❌⚠️📊🗑️🔄)
- Degradação graceful em todas as funcionalidades críticas

---

## 10. Lacunas Identificadas e Recomendações

### 10.1 Lacunas Atuais

| # | Lacuna | Risco | Recomendação |
|---|---|---|---|
| 1 | Ausência de security headers HTTP | Médio | Adicionar `X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`, `Content-Security-Policy` |
| 2 | Sem criptografia de dados em repouso | Baixo | Considerar criptografia do SQLite (baixa prioridade — não há dados sensíveis) |
| 3 | Rate limiting no endpoint admin | Baixo | Adicionar rate limiting ao `/admin/auditoria` |
| 4 | Retenção de auditoria de 90 dias | Informativo | Avaliar se atende requisitos regulatórios da organização |
| 5 | Sem WAF (Web Application Firewall) | Médio | Considerar Cloudflare ou similar para proteção adicional |
| 6 | Sem testes automatizados de segurança | Médio | Implementar SAST/DAST no pipeline de CI/CD |

### 10.2 Roadmap de Melhorias Sugerido

**Curto Prazo:**
- Implementar security headers HTTP
- Adicionar rate limiting ao painel administrativo

**Médio Prazo:**
- Implementar testes automatizados de segurança
- Avaliar uso de WAF

**Longo Prazo:**
- Criptografia de dados em repouso
- Certificação de conformidade LGPD por auditoria externa

---

## 11. Matriz de Responsabilidades

| Área | Responsável | Frequência de Revisão |
|---|---|---|
| Código-fonte | Equipe de Desenvolvimento | A cada commit |
| Variáveis de ambiente | Administrador do Sistema | Trimestral |
| Dependências (requirements.txt) | Equipe de Desenvolvimento | Mensal |
| Conformidade LGPD | DPO / Jurídico | Semestral |
| Logs de auditoria | Segurança da Informação | Mensal |
| Infraestrutura Render | DevOps / Administrador | Mensal |

---

## 12. Conclusão

O sistema **Entenda Aqui** implementa uma arquitetura de segurança robusta com foco em:

1. **Privacidade por design** — Conformidade com a LGPD desde a concepção
2. **Zero dados pessoais persistidos** — Apenas hashes e contadores agregados
3. **Exclusão automática em múltiplas camadas** — De 30 minutos a 90 dias
4. **Proteção contra as 10 principais vulnerabilidades OWASP**
5. **Resiliência** — Fallback automático de modelos de IA e tratamento robusto de erros

As lacunas identificadas são de risco baixo a médio e possuem recomendações claras para mitigação.

---

**Elaborado por**: Análise automatizada do código-fonte
**Aprovação pendente**: Diretoria / DPO
**Próxima revisão**: A definir
