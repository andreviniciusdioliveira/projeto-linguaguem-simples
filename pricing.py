"""
Tabela de preços da API Gemini e conversão para Reais (BRL).

Preços oficiais por 1 milhão de tokens (input/output), em USD.
Fonte: https://ai.google.dev/gemini-api/docs/pricing
Atualizado em: abril/2026 — confira periodicamente, o Google ajusta preços
ocasionalmente. Para alterar, edite o dict abaixo (não precisa redeploy se
você só quer ajustar o câmbio — basta a env var USD_TO_BRL).

Modelos não listados são considerados gratuitos / experimentais (custo zero).

A conversão para BRL usa a env var USD_TO_BRL (default: 5.0). Em produção,
configure essa variável no Render conforme o câmbio que você quer usar como
referência (idealmente uma média mensal ou o valor da nota fiscal do Google).
"""

import os
import logging

# Preços por 1.000.000 de tokens, em USD
# (input = tokens enviados no prompt, output = tokens gerados pelo modelo)
GEMINI_PRICING_USD_PER_1M = {
    'gemini-2.5-flash-lite': {'input': 0.10, 'output': 0.40},
    'gemini-2.5-flash':      {'input': 0.30, 'output': 2.50},
    'gemini-2.5-pro':        {'input': 1.25, 'output': 10.00},
    'gemini-2.0-flash':      {'input': 0.10, 'output': 0.40},
    'gemini-2.0-flash-exp':  {'input': 0.00, 'output': 0.00},  # experimental / free tier
    'gemini-1.5-flash':      {'input': 0.075, 'output': 0.30},
    'gemini-1.5-flash-8b':   {'input': 0.0375, 'output': 0.15},
    'gemini-1.5-pro':        {'input': 1.25, 'output': 5.00},
}

USD_TO_BRL_DEFAULT = 5.0


def get_usd_to_brl():
    """Lê o câmbio da env var (permite ajuste sem redeploy)."""
    try:
        valor = float(os.getenv('USD_TO_BRL', str(USD_TO_BRL_DEFAULT)))
        if valor <= 0:
            raise ValueError("USD_TO_BRL deve ser > 0")
        return valor
    except (ValueError, TypeError) as e:
        logging.warning(f"⚠️ USD_TO_BRL inválido ({e}), usando default {USD_TO_BRL_DEFAULT}")
        return USD_TO_BRL_DEFAULT


def custo_usd(modelo, tokens_input, tokens_output):
    """Calcula o custo em USD para um modelo dado tokens de input e output."""
    pricing = GEMINI_PRICING_USD_PER_1M.get(modelo)
    if not pricing:
        # Modelo desconhecido - sem custo registrado (provavelmente experimental)
        return 0.0
    custo_in = (tokens_input or 0) * pricing['input'] / 1_000_000
    custo_out = (tokens_output or 0) * pricing['output'] / 1_000_000
    return custo_in + custo_out


def custo_brl(modelo, tokens_input, tokens_output):
    """Calcula o custo em BRL aplicando o câmbio configurado."""
    return custo_usd(modelo, tokens_input, tokens_output) * get_usd_to_brl()


def custo_brl_lote(items):
    """
    Calcula custo total em BRL para uma lista de tuplas (modelo, tokens_in, tokens_out).
    Mais eficiente que chamar custo_brl em loop quando se tem muitos items.
    """
    cambio = get_usd_to_brl()
    total = 0.0
    for modelo, tin, tout in items:
        total += custo_usd(modelo, tin, tout)
    return total * cambio


def listar_precos():
    """Retorna a tabela de preços com câmbio aplicado, útil pro dashboard mostrar."""
    cambio = get_usd_to_brl()
    return {
        'cambio_usd_brl': cambio,
        'modelos': [
            {
                'modelo': m,
                'input_usd_1m': p['input'],
                'output_usd_1m': p['output'],
                'input_brl_1m': round(p['input'] * cambio, 4),
                'output_brl_1m': round(p['output'] * cambio, 4),
            }
            for m, p in sorted(GEMINI_PRICING_USD_PER_1M.items())
        ]
    }
