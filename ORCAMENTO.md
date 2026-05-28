# Controle de Orçamento Mensal — Entenda Aqui

**Documento técnico**
**Data**: 2026-05-28
**Versão**: 1.0
**Aplicação**: Entenda Aqui

---

## 1. Objetivo

Limitar o gasto com a API Google Gemini a um teto configurável em **Reais (BRL)** por período. Quando o teto é atingido, o sistema **bloqueia automaticamente** novos uploads, texto colado e chat para preservar o orçamento — até a renovação do período (mensal/diário) ou até o admin desativar o limite.

**Default:** R$ 3.000,00 por mês.

---

## 2. Como funciona

### 2.1 Cálculo do gasto

Em vez de converter o teto para uma quantidade fixa de tokens, o sistema rastreia o **custo real acumulado em BRL** usando dados que já existiam:

1. Cada chamada ao Gemini grava `(modelo, tokens_input, tokens_output)` em `audit_ip`.
2. `_calcular_custo_periodo_brl()` (`database.py`) soma os tokens por modelo no período e aplica `pricing.custo_brl(modelo, tin, tout)`.
3. O resultado é o custo acumulado em BRL.

Vantagem: o custo reflete os preços reais por modelo (Flash-Lite é mais barato que Pro, por exemplo) e o câmbio configurado (`USD_TO_BRL`).

### 2.2 Estimativa de tokens equivalentes

A função `_estimar_tokens_para_teto()` calcula quantos tokens cabem no teto **assumindo o modelo primário** (`gemini-2.5-flash-lite`) e razão típica input:output de 5:1.

Exemplo: com R$ 3.000, câmbio USD/BRL = 5,00 e Flash-Lite (input $0,10/M, output $0,40/M):

- Teto em USD: $600
- Preço médio por token: ($0,10 × 5 + $0,40) / 6 = ~$0,15/M tokens
- Tokens estimados: ~**4 bilhões de tokens**

A estimativa é exibida no painel admin como referência (o valor exato varia conforme o modelo realmente usado).

### 2.3 Verificação por request

Antes de cada chamada paga ao Gemini, o app executa `verificar_orcamento_request()` (`app.py`). Se o gasto >= teto e a config está ativa, retorna HTTP 503 com:

```json
{
  "erro": "O orçamento de R$3000.00 este mês foi atingido...",
  "orcamento_bloqueado": true,
  "orcamento": { "teto_brl": 3000.0, "gasto_brl": 3010.5, ... }
}
```

**Endpoints protegidos:**
- `POST /processar` (upload de arquivo)
- `POST /processar_texto` (texto colado)
- `POST /chat` (perguntas)

### 2.4 Períodos suportados

| Período | Reset | Uso típico |
|---|---|---|
| `mensal` (default) | Dia 1 de cada mês | Orçamento operacional padrão |
| `diario` | Meia-noite todo dia | Controle granular, projetos com tráfego previsível |
| `total` | Nunca (manual) | Piloto / projeto com verba fechada |

---

## 3. Configuração

### 3.1 Via painel admin

`/admin` → seção "Orçamento Gemini":

- **Teto (R$):** valor numérico.
- **Período:** mensal / diário / acumulado total.
- **Ativo:** checkbox. Desativado = sem bloqueio (apenas exibe o gasto).

Requer permissão de **superadmin** para alterar (via `@auth.superadmin_required` no POST).

### 3.2 Via API

```
GET  /admin/api/orcamento  → status atual (qualquer admin)
POST /admin/api/orcamento  → atualiza (superadmin)
     body: { "teto_brl": 3000.0, "periodo": "mensal", "ativo": true }
```

### 3.3 Variáveis de ambiente relacionadas

- `USD_TO_BRL` (default: 5.0) — câmbio aplicado ao calcular custo. Pode ser ajustada sem redeploy.

---

## 4. Esquema de dados

```sql
CREATE TABLE orcamento_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    teto_brl REAL NOT NULL DEFAULT 3000.0,
    periodo TEXT NOT NULL DEFAULT 'mensal',
    ativo INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT NOT NULL
)
```

O cálculo do gasto não usa tabela própria — agrega `audit_ip.tokens_input/output × pricing` em tempo real.

---

## 5. Comportamento de borda

| Situação | Comportamento |
|---|---|
| `ativo = False` | Bloqueio desligado. Painel mostra gasto = 0. |
| `teto_brl = 0` | Bloqueia imediatamente (qualquer gasto >= 0). |
| Erro ao calcular custo | "Falha aberta" — não bloqueia (evita derrubar serviço por bug interno). Log warning. |
| Modelo desconhecido em `audit_ip` | `pricing.custo_brl()` retorna 0. Verifique a tabela `GEMINI_PRICING_USD_PER_1M`. |

---

## 6. Referências no código

| Componente | Arquivo:Linha aproximada |
|---|---|
| Tabela `orcamento_config` (DDL) | `database.py` (init_db) |
| `get_orcamento_config()` | `database.py` |
| `set_orcamento_config()` | `database.py` |
| `_calcular_custo_periodo_brl()` | `database.py` |
| `_estimar_tokens_para_teto()` | `database.py` |
| `verificar_orcamento()` | `database.py` |
| `verificar_orcamento_request()` (helper Flask) | `app.py` |
| Endpoint `GET /admin/api/orcamento` | `app.py` |
| Endpoint `POST /admin/api/orcamento` | `app.py` (superadmin) |
| UI no dashboard | `templates/admin/dashboard.html` (seção `#orcamentoCard`) |
| JS de render/form | `static/admin.js` (`fetchOrcamento`, `renderOrcamento`, `setupOrcamentoForm`) |

---

## 7. Limitações conhecidas

- **Sem alerta antes do bloqueio.** Hoje o painel mostra a barra ficando vermelha aos 90%+, mas não dispara e-mail/webhook. Adicionar notificação requer integração externa.
- **Cálculo on-demand.** Cada GET `/admin/api/orcamento` recalcula tudo agregando `audit_ip`. Em volume muito alto seria útil cachear por 1-2 minutos.
- **Câmbio fixo.** Usa `USD_TO_BRL` da env var, não cotação em tempo real. Configurar com folga (ex: USD_TO_BRL=5.5 quando dólar está em 5.2) para evitar surpresa.
- **Reset automático depende do calendário.** Mensal reseta dia 1; se o admin quiser reset em outra data, precisa criar período custom (não implementado).

---

**Última atualização:** 2026-05-28
**Documento relacionado:** `PROMPT_INJECTION.md`, `SECURITY_REQUIREMENTS.md`
