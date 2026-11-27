"""
Mascaramento de dados pessoais antes do envio a modelos de IA externos.

Fundamento normativo: Resolução CNJ 615/2025, art. 7º, §2º, e Resolução TJTO 20/2026,
art. 6º, §2º (dados pessoais anonimizados antes do processamento pela IA, sempre que possível).

MascaradorDados troca identificadores pessoais por marcadores ([CPF_1], [EMAIL_2]...)
antes do envio e devolve os valores originais na resposta, localmente.

A triagem de segredo de justiça fica em salvaguardas.py.

Este módulo não depende de Flask nem do Gemini, para poder ser testado isoladamente.

Limitação conhecida: o mascaramento cobre identificadores com formato reconhecível
(CPF, CNPJ, RG rotulado, telefone, e-mail, CEP e número do processo). Nomes de pessoas
e endereços por extenso NÃO são mascarados, pois exigiriam reconhecimento de entidades.
"""

import os
import re


def _env_bool(nome, padrao):
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ('1', 'true', 'yes', 'sim')


# Liga/desliga o mascaramento (padrão: ligado).
MASCARAR_DADOS_PESSOAIS = _env_bool('MASCARAR_DADOS_PESSOAIS', True)


# ============================================================================
# MASCARAMENTO REVERSÍVEL DE DADOS PESSOAIS
# ============================================================================

# Ordem importa: padrões mais específicos primeiro (o número do processo contém
# sequências que poderiam casar com outros padrões).
# Cada item: (rótulo, regex, índice do grupo que contém o valor a mascarar).
_PADROES_MASCARA = [
    ("PROCESSO", re.compile(r'(?<!\d)\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}(?!\d)'), 0),
    ("CNPJ", re.compile(r'(?<!\d)\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}(?!\d)'), 0),
    ("CPF", re.compile(r'(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)'), 0),
    ("CPF", re.compile(r'\bCPF\b[^\d\n\[]{0,20}(\d{11})(?!\d)', re.IGNORECASE), 1),
    ("RG", re.compile(r'\bRG\b[^\d\n\[]{0,20}(\d[\d.]{4,12}(?:-[\dxX])?)', re.IGNORECASE), 1),
    ("EMAIL", re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), 0),
    ("TELEFONE", re.compile(r'(?<![\d\[])(?:\+?55\s?)?(?:\(\d{2}\)\s?|\d{2}[\s-])9?\d{4}[-\s]?\d{4}(?!\d)'), 0),
    ("CEP", re.compile(r'(?<!\d)\d{2}\.?\d{3}-\d{3}(?!\d)'), 0),
]

_ROTULOS = sorted({rotulo for rotulo, _, _ in _PADROES_MASCARA})
# Tolerante a pequenas alterações do modelo: [cpf 1], [ CPF_1 ], [CPF-1].
_REGEX_MARCADOR = re.compile(r'\[\s*(' + '|'.join(_ROTULOS) + r')[\s_-]?(\d+)\s*\]', re.IGNORECASE)

# Instrução incluída no prompt para o modelo preservar os marcadores.
INSTRUCAO_MARCADORES = (
    "MARCADORES DE DADOS PROTEGIDOS: alguns dados pessoais do documento foram trocados por "
    "marcadores entre colchetes, como [CPF_1], [CNPJ_1], [RG_1], [TELEFONE_1], [EMAIL_1], "
    "[CEP_1] e [PROCESSO_1]. Trate cada marcador como se fosse o dado real. Sempre que "
    "precisar citar o dado, copie o marcador EXATAMENTE como aparece, com os colchetes. "
    "Nunca tente adivinhar, completar ou explicar o valor escondido."
)


class MascaradorDados:
    """Troca identificadores pessoais por marcadores e os restaura depois.

    O mesmo valor recebe sempre o mesmo marcador dentro de uma instância, então
    documento, dados extraídos e pergunta do chat ficam coerentes entre si.
    """

    def __init__(self, ativo=None):
        self.ativo = MASCARAR_DADOS_PESSOAIS if ativo is None else ativo
        self._valor_para_marcador = {}
        self._marcador_para_valor = {}
        self._contadores = {}

    def _marcador(self, rotulo, valor):
        chave = (rotulo, valor)
        existente = self._valor_para_marcador.get(chave)
        if existente:
            return existente
        n = self._contadores.get(rotulo, 0) + 1
        self._contadores[rotulo] = n
        marcador = f"[{rotulo}_{n}]"
        self._valor_para_marcador[chave] = marcador
        self._marcador_para_valor[(rotulo, n)] = valor
        return marcador

    def mascarar(self, texto):
        """Devolve o texto com os identificadores trocados por marcadores."""
        if not self.ativo or not texto or not isinstance(texto, str):
            return texto
        for rotulo, regex, grupo in _PADROES_MASCARA:
            def _trocar(m, rotulo=rotulo, grupo=grupo):
                valor = m.group(grupo)
                marcador = self._marcador(rotulo, valor)
                if grupo == 0:
                    return marcador
                inicio = m.start(grupo) - m.start()
                fim = m.end(grupo) - m.start()
                completo = m.group(0)
                return completo[:inicio] + marcador + completo[fim:]
            texto = regex.sub(_trocar, texto)
        return texto

    def restaurar(self, texto):
        """Devolve os valores originais no lugar dos marcadores."""
        if not texto or not isinstance(texto, str) or not self._marcador_para_valor:
            return texto

        def _voltar(m):
            chave = (m.group(1).upper(), int(m.group(2)))
            return self._marcador_para_valor.get(chave, m.group(0))

        return _REGEX_MARCADOR.sub(_voltar, texto)

    def restaurar_estrutura(self, obj):
        """Restaura marcadores em todas as strings de dicts/listas aninhados."""
        if isinstance(obj, str):
            return self.restaurar(obj)
        if isinstance(obj, list):
            return [self.restaurar_estrutura(item) for item in obj]
        if isinstance(obj, dict):
            return {chave: self.restaurar_estrutura(valor) for chave, valor in obj.items()}
        return obj

    def contagem(self):
        """Quantidade de valores distintos mascarados por tipo (sem os valores)."""
        return dict(self._contadores)

    def total(self):
        return sum(self._contadores.values())
