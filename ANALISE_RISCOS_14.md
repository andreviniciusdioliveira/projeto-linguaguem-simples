# 14. ANÁLISE DE RISCOS - Entenda Aqui

## Contexto

Considerando as informações da DSI (Despacho 105422 - 6831378) e da DASR (Despacho 113248 - 6869343), apresentamos a análise técnica dos riscos identificados com base no código-fonte e arquitetura do projeto.

---

## RISCO 1: Ausência de Equipe Técnica na DSI

### Descrição do Risco

A DSI informou que **não possui equipe que trabalhe efetivamente com a arquitetura proposta** (Python + Flask, Tesseract + OpenCV, PyMuPDF + ReportLab) e **não possui ambiente preparado** para essa stack tecnológica.

A DASR destacou a necessidade de **definir servidores e substitutos** como responsáveis técnicos pela VM.

### Análise Técnica

A arquitetura do sistema é composta por:

| Componente | Tecnologia | Complexidade |
|------------|-----------|--------------|
| Backend | Python 3.11 + Flask 3.0.3 | Média |
| Servidor WSGI | Gunicorn 21.2.0 (2 workers, timeout 120s) | Baixa |
| OCR | Tesseract OCR + Pillow + OpenCV (opcional) | Média-Alta |
| Extração PDF | PyMuPDF 1.24.2 | Baixa |
| Geração PDF | ReportLab 4.2.2 | Baixa |
| IA | Google Gemini API (serviço externo) | Baixa (é API REST) |
| Banco de Dados | SQLite (arquivo local) | Baixa |
| Deploy atual | Render.com (Free Tier, Oregon) | Baixa |

**Pontos críticos para a equipe de sustentação:**

1. **Tesseract OCR** - Requer instalação de pacotes de sistema (`tesseract-ocr`, `tesseract-ocr-por`) e conhecimento de configuração de OCR. É o componente mais especializado.
2. **OpenCV** - Usado opcionalmente para pré-processamento de imagens. O sistema já possui fallback gracioso: se o OpenCV não estiver disponível (`CV2_AVAILABLE = False`), usa processamento básico com Pillow.
3. **Gunicorn** - Configuração otimizada para 512MB RAM com apenas 2 workers. Alterações sem conhecimento podem causar problemas de memória.

### Questão: O risco de falta de equipe foi sanado?

**Este risco permanece parcialmente em aberto.** Independentemente de quem sustentará o sistema (DSI ou INOVASSOL), é necessário garantir:

1. **Capacitação mínima** em Python/Flask e administração Linux para manutenção da VM
2. **Documentação operacional** (runbooks) para procedimentos de:
   - Reinicialização do serviço
   - Monitoramento de logs e saúde (`GET /health`)
   - Atualização de dependências (`pip install -r requirements.txt`)
   - Renovação/troca da chave da API Gemini
   - Instalação/atualização do Tesseract OCR
3. **Definição formal** de responsabilidades (DSI vs. INOVASSOL)

### Questão: A equipe INOVASSOL vai assumir esse papel?

Se a equipe INOVASSOL assumir a sustentação técnica, os seguintes aspectos devem ser formalizados:

- **Acordo de nível de serviço (SLA)** para disponibilidade e tempo de resposta a incidentes
- **Acesso administrativo** à VM e ao painel do Render.com (ou infraestrutura alternativa)
- **Plano de contingência** caso membros-chave da equipe INOVASSOL se tornem indisponíveis
- **Treinamento cruzado** com pelo menos 1 servidor da DSI como backup

### Ações Mitigadoras Recomendadas

| # | Ação | Responsável Sugerido | Prazo |
|---|------|---------------------|-------|
| 1 | Definir formalmente a equipe de sustentação (DSI, INOVASSOL ou mista) | Gestão do Projeto | Antes do go-live |
| 2 | Elaborar runbooks operacionais com procedimentos passo-a-passo | Equipe de Desenvolvimento | Antes do go-live |
| 3 | Capacitar pelo menos 2 servidores + 2 substitutos na stack do projeto | DSI/INOVASSOL | 30 dias após definição |
| 4 | Documentar processo de deploy e rollback | Equipe de Desenvolvimento | Antes do go-live |
| 5 | Implementar monitoramento automatizado (alertas via e-mail/Slack) | Equipe Técnica | 60 dias após go-live |

---

## RISCO 2: Adesão em Massa e Esgotamento de Tokens

### Descrição do Risco

Um grande fluxo de usuários pode esgotar rapidamente os tokens diários previstos para a API Gemini, tornando o sistema indisponível.

### Análise Técnica - Mecanismos Existentes

O sistema **já possui múltiplas camadas de proteção** implementadas no código:

#### Camada 1: Limite de Tokens Diário
- **Configuração:** `DAILY_TOKEN_LIMIT = 171.600.000 tokens/dia` (arquivo `database.py`, linha 32)
- **Mecanismo:** Antes de cada processamento, a função `verificar_limite_tokens()` consulta o total consumido no dia
- **Resposta ao atingir o limite:** HTTP 503 com mensagem: *"O limite diário de processamento foi atingido. O sistema processa até 171,6 milhões de tokens por dia. Tente novamente amanhã."*

#### Camada 2: Limite por CPF
- **Configuração:** `CPF_DAILY_LIMIT = 5 documentos por CPF/dia` (arquivo `database.py`, linha 38)
- **Mecanismo:** CPF é criptografado com SHA-256 (nunca armazenado em texto plano - conformidade LGPD) e o sistema verifica quantos documentos aquele CPF já processou no dia
- **Resposta:** HTTP 400 com mensagem informando que o limite diário de 5 documentos foi atingido

#### Camada 3: Rate Limiting por IP
- **Configuração:** `RATE_LIMIT = 10 requisições por minuto por IP` (arquivo `app.py`, linha 114)
- **Mecanismo:** Dicionário em memória rastreia contagem de requisições por IP
- **Resposta:** HTTP 429 - "Limite de requisições excedido"

#### Camada 4: Cache Inteligente
- **Configuração:** Cache em memória com expiração de 1 hora, máximo 50 entradas
- **Chave de cache:** Hash MD5 dos primeiros 5.000 caracteres do documento + perspectiva do usuário
- **Efeito:** Documentos idênticos processados por diferentes usuários (mesma perspectiva) consomem tokens apenas na primeira vez. Nas requisições subsequentes, o resultado é retornado do cache sem consumo de tokens.

#### Camada 5: Fallback Multi-Modelo
- **4 modelos Gemini** configurados em ordem de prioridade, todos Flash (evitando compartilhamento de quota com modelos Pro):
  1. `gemini-2.0-flash` (principal)
  2. `gemini-2.0-flash-lite` (alternativa leve)
  3. `gemini-1.5-flash` (quota separada)
  4. `gemini-2.5-flash-lite` (fallback final)
- Se um modelo atinge quota, o próximo é tentado automaticamente

### Estimativa de Capacidade

| Métrica | Valor |
|---------|-------|
| Limite diário | 171.600.000 tokens |
| Consumo médio por documento | ~20.000 tokens (input + output) |
| **Capacidade estimada/dia** | **~6.200 a 12.500 documentos/dia** |
| Limite por CPF | 5 documentos/dia |
| Limite por IP | 10 requisições/minuto |

### Impacto Financeiro ao TJTO

| Cenário | Custo | Observação |
|---------|-------|------------|
| **Cenário Atual (Free Tier)** | **R$ 0,00** | API Gemini gratuita + Render Free Tier. Limite de ~171,6M tokens/dia |
| **Cenário de Crescimento (Tier Pago)** | **Variável** | Se a demanda exceder o free tier, será necessário contratar plano pago da API Gemini. Custos dependem do modelo: Gemini Flash custa ~US$ 0,075/1M tokens input e ~US$ 0,30/1M tokens output |
| **Estimativa cenário pago (10.000 docs/dia)** | **~US$ 15-30/dia (~R$ 90-180/dia)** | Se o free tier for insuficiente |
| **Infraestrutura própria (VM TJTO)** | **Custo de infraestrutura interna** | Elimina custo do Render, mas requer VM com pelo menos 2GB RAM e suporte da DSI |

### Ações Mitigadoras

| # | Ação | Impacto Financeiro | Prioridade |
|---|------|--------------------|------------|
| 1 | **Monitorar consumo diário de tokens** via endpoint `/health` e `/estatisticas` | Nenhum | Alta |
| 2 | **Ajustar `CPF_DAILY_LIMIT`** conforme demanda real (atualmente 5/dia) | Nenhum | Média |
| 3 | **Aumentar eficiência do cache** (expandir de 50 para mais entradas, ou usar Redis) | Baixo | Média |
| 4 | **Implementar fila de processamento** para gerenciar picos de demanda | Baixo-Médio | Média |
| 5 | **Migrar para tier pago da API Gemini** caso demanda justifique | US$ 50-900/mês dependendo do volume | Sob demanda |
| 6 | **Considerar modelo local** (LLM open-source) para eliminar dependência de API externa | Custo de GPU/infraestrutura | Longo prazo |
| 7 | **Estabelecer horários de pico** e distribuir processamento ao longo do dia | Nenhum | Baixa |

---

## RISCO 3: Documentos Iguais com Resultados Diferentes

### Descrição do Risco

Diferentes usuários inserindo o mesmo documento podem obter resultados diferentes, gerando inconsistência e potencial insegurança jurídica.

### Análise Técnica - Mecanismos Existentes

#### O que já garante consistência:

**1. Cache de Resultados (Consistência de curto prazo)**
- Documentos com o **mesmo conteúdo + mesma perspectiva** geram a **mesma chave de cache** (hash MD5)
- Dentro da janela de 1 hora do cache, **todos os usuários recebem exatamente o mesmo resultado**
- Código relevante em `app.py`:
  ```python
  cache_key = hashlib.md5(f"{texto[:5000]}:{perspectiva}".encode()).hexdigest()
  ```

**2. Perspectiva do Usuário**
- O sistema pede ao usuário que informe sua perspectiva (autor/réu/advogado/interessado)
- Resultados são **intencionalmente diferentes** por perspectiva, pois a explicação é personalizada
- Isto é uma **feature, não um bug**: o mesmo documento explicado para o autor tem ênfase diferente do que para o réu

#### O que NÃO garante consistência:

**1. Natureza Probabilística da IA Generativa**
- O Google Gemini (como qualquer LLM) é **inerentemente não-determinístico**
- Mesmo com o mesmo input, respostas podem variar em redação, ordem e detalhes
- A configuração atual **não define `temperature=0`** nas chamadas à API, o que aumenta a variabilidade

**2. Cache Expirado (Após 1 hora)**
- Após expiração do cache, uma nova consulta ao Gemini pode gerar resultado com redação diferente
- O **conteúdo semântico** tende a ser consistente (mesmas conclusões jurídicas), mas a **redação** pode variar

**3. Modelo Diferente via Fallback**
- Se o modelo primário estiver indisponível e o sistema usar um modelo de fallback, os resultados podem ter **diferenças de qualidade e estilo**, embora as conclusões jurídicas devam ser semelhantes

**4. Reinício do Servidor**
- O cache é em memória (não persistido). Após reinício do servidor, todos os caches são perdidos

### Avaliação do Impacto

| Aspecto | Consistência | Observação |
|---------|-------------|------------|
| Informações jurídicas essenciais | **Alta** | Prazos, valores, partes envolvidas são extraídos do documento |
| Indicador de urgência | **Alta** | Baseado em prazos explícitos no documento |
| Redação da simplificação | **Média** | Pode variar entre consultas, mas sentido é preservado |
| Sugestões de ações | **Média** | Podem variar em ordem e detalhamento |
| Nível de detalhe | **Média-Baixa** | Depende do modelo usado e da "criatividade" da IA |

### Ações Mitigadoras

| # | Ação | Complexidade | Eficácia |
|---|------|-------------|----------|
| 1 | **Definir `temperature=0`** nas chamadas à API Gemini para maximizar determinismo | Baixa (1 linha de código) | Alta |
| 2 | **Aumentar tempo de cache** de 1h para 24h para documentos idênticos | Baixa | Alta |
| 3 | **Persistir cache em banco de dados** (SQLite ou Redis) para sobreviver a reinícios | Média | Alta |
| 4 | **Fixar modelo único** quando possível (evitar fallback exceto em erro) | Baixa | Média |
| 5 | **Incluir disclaimer** informando que a simplificação é orientativa e pode variar em redação | Baixa | Média (mitigação jurídica) |
| 6 | **Implementar hash de documento** para cache persistente por hash do documento completo | Média | Alta |
| 7 | **Gerar "versão canônica"** com campos estruturados (prazo, partes, valor) separados da narrativa livre | Alta | Muito Alta |

### Recomendação Prioritária

A ação de **maior impacto e menor esforço** é definir `temperature=0` na configuração do modelo Gemini. Isso reduz significativamente a variabilidade entre respostas para o mesmo input, tornando os resultados muito mais consistentes.

Exemplo de implementação:
```python
generation_config = genai.types.GenerationConfig(
    max_output_tokens=3000,
    temperature=0  # Maximiza determinismo
)
```

---

## RISCO 4: Aprovação pelo CGTIC

### Descrição do Risco

O projeto precisa ser aprovado pelo Comitê de Governança de TIC (CGTIC) para prosseguimento formal.

### Considerações Técnicas para Submissão

| Aspecto | Status Atual | Recomendação |
|---------|-------------|-------------|
| **LGPD Compliance** | Implementado (zero dados pessoais armazenados, cleanup automático) | Documentar em relatório formal |
| **Segurança** | Rate limiting, validação de uploads, sem armazenamento permanente | Realizar teste de segurança formal |
| **Custo** | R$ 0,00 (free tier) | Apresentar cenários de escalabilidade com custos |
| **Infraestrutura** | Render.com (externo) ou VM interna (pendente definição DSI) | Definir antes da submissão |
| **Equipe de sustentação** | Pendente definição | Resolver antes da submissão |
| **Documentação técnica** | CLAUDE.md + README existentes | Complementar com documentação formal do TJTO |
| **Testes** | Apenas manuais, sem testes automatizados | Considerar implementar testes básicos |

### Itens Recomendados para o Dossiê CGTIC

1. **Relatório de Conformidade LGPD** - Demonstrando que nenhum dado pessoal ou conteúdo de documentos é armazenado
2. **Análise de Impacto à Proteção de Dados (RIPD)** - Mesmo sem armazenamento, o processamento de documentos jurídicos requer avaliação
3. **Plano de Sustentação** - Equipe, SLA, procedimentos operacionais
4. **Análise de Custos (TCO)** - Cenários free tier vs. pago vs. infraestrutura própria
5. **Plano de Contingência** - Procedimentos em caso de indisponibilidade da API Gemini
6. **Parecer de Segurança** - Testes de penetração ou ao menos revisão de segurança do código

---

## Resumo Executivo

| Risco | Severidade | Probabilidade | Status | Ação Prioritária |
|-------|-----------|---------------|--------|-------------------|
| Falta de equipe DSI | **Alta** | **Alta** | Parcialmente em aberto | Definir equipe de sustentação formalmente |
| Adesão em massa / tokens | **Média** | **Média** | Mitigado parcialmente (5 limites implementados) | Monitorar consumo e preparar plano de escalabilidade |
| Inconsistência em documentos iguais | **Média** | **Alta** | Mitigado parcialmente (cache 1h) | Implementar `temperature=0` e cache persistente |
| Aprovação CGTIC | **Alta** | **Baixa** | Pendente | Preparar dossiê completo com os itens acima |

---

*Documento gerado com base na análise do código-fonte do projeto Entenda Aqui.*
*Data da análise: 23/03/2026*
