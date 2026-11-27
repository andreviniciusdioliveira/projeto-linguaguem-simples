"""
Proteção de dados antes do envio a modelos de IA externos.

Fundamento normativo:
- Resolução CNJ 615/2025, art. 19, §3º, IV, e art. 20, V: vedado processar em LLM
  externo documento sigiloso ou sob segredo de justiça, salvo anonimização na origem.
- Resolução CNJ 615/2025, art. 7º, §2º, e Resolução TJTO 20/2026, art. 6º, §2º:
  dados pessoais anonimizados antes do processamento pela IA, sempre que possível.

Este módulo não depende de Flask nem do Gemini, para poder ser testado isoladamente.

Duas funções:
1. detectar_segredo_local(): decide, SEM chamar a IA, se o documento não pode ser enviado.
2. MascaradorDados: troca identificadores pessoais por marcadores ([CPF_1], [EMAIL_2]...)
   antes do envio e devolve os valores originais na resposta, localmente.

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

# Mandados, intimações, citações e notificações são simplificados mesmo quando o
# processo é sigiloso (regra de produto já existente: contêm dados operacionais).
# Defina SEGREDO_PERMITIR_PROCEDIMENTAIS=false para bloquear também esses documentos.
SEGREDO_PERMITIR_PROCEDIMENTAIS = _env_bool('SEGREDO_PERMITIR_PROCEDIMENTAIS', True)


# ============================================================================
# 1. DETECÇÃO LOCAL DE SEGREDO DE JUSTIÇA
# ============================================================================

_F = re.IGNORECASE

# Menção expressa a sigilo. Cada item: (regex, motivo exibido ao usuário).
_MARCADORES_EXPLICITOS = [
    (re.compile(r'segredo\s+de\s+justi[çc]a', _F), "O documento menciona segredo de justiça"),
    (re.compile(r'tramita\w*\s+(?:sob|em)\s+(?:segredo|sigilo)', _F), "O documento informa que o processo tramita em sigilo"),
    (re.compile(r'sigilo\s+(?:processual|dos\s+autos)', _F), "O documento menciona sigilo processual"),
    (re.compile(r'n[íi]vel\s+(?:de\s+)?sigilo\s*:?\s*[1-5]\b', _F), "O documento indica nível de sigilo"),
]

# Negações que afastam o marcador ("não tramita em segredo de justiça", "indefiro o pedido de...").
_NEGACAO_ANTES = re.compile(
    r'(?:\bn[ãa]o\b|\bsem\b|\bindefiro\b|\bindeferido\b|\bafasto\b|\blevant\w+\b|\binexist\w+\b)[^.\n]{0,60}$', _F
)

# Matérias que tramitam em segredo por força de lei. Cada item: (regex, hipótese legal).
_MATERIAS_SIGILOSAS = [
    (re.compile(r'vara\s+(?:c[íi]vel\s+)?(?:de|da|das)\s+fam[íi]lias?', _F), "Art. 189, II, do CPC (Direito de Família)"),
    (re.compile(
        r'a[çc][ãa]o\s+de\s+(?:alimentos|div[óo]rcio|guarda|ado[çc][ãa]o|interdi[çc][ãa]o|curatela|'
        r'investiga[çc][ãa]o\s+de\s+paternidade|'
        r'reconhecimento\s+(?:e\s+dissolu[çc][ãa]o\s+)?de\s+uni[ãa]o\s+est[áa]vel)', _F),
     "Art. 189, II, do CPC (Direito de Família)"),
    (re.compile(r'destitui[çc][ãa]o\s+do\s+poder\s+familiar', _F), "Estatuto da Criança e do Adolescente"),
    (re.compile(r'regulamenta[çc][ãa]o\s+de\s+(?:visitas|conviv[êe]ncia)', _F), "Art. 189, II, do CPC (Direito de Família)"),
    (re.compile(r'maria\s+da\s+penha|medidas?\s+protetivas?\s+de\s+urg[êe]ncia|viol[êe]ncia\s+dom[ée]stica', _F),
     "Lei 11.340/2006 (Lei Maria da Penha)"),
    (re.compile(r'\bestupro\b|viola[çc][ãa]o\s+sexual|importuna[çc][ãa]o\s+sexual|ass[ée]dio\s+sexual|dignidade\s+sexual', _F),
     "Art. 234-B do Código Penal (crimes contra a dignidade sexual)"),
    (re.compile(r'depoimento\s+especial', _F), "Lei 13.431/2017"),
    (re.compile(r'intercepta[çc][ãa]o\s+(?:telef[ôo]nica|telem[áa]tica)|'
                r'quebra\s+d[eo]\s+sigilo\s+(?:banc[áa]rio|fiscal|telef[ôo]nico|telem[áa]tico)', _F),
     "Lei 9.296/1996 e sigilo de dados"),
]

# Título de documento procedimental nas primeiras linhas.
_TITULO_PROCEDIMENTAL = re.compile(
    r'^\s*(?:(?:mandado|carta)\s+de\s+(?:intima[çc][ãa]o|cita[çc][ãa]o|notifica[çc][ãa]o)|'
    r'mandado\b|intima[çc][ãa]o\b|cita[çc][ãa]o\b|notifica[çc][ãa]o\b)',
    _F | re.MULTILINE
)
# Sinais de que NÃO é procedimental (sentença, acórdão, decisão de mérito).
_SINAIS_DECISORIOS = re.compile(
    r'\bsenten[çc]a\b|\bac[óo]rd[ãa]o\b|julgo\s+(?:parcialmente\s+)?(?:procedente|improcedente)', _F
)


def documento_procedimental(texto):
    """True se o documento tem título de mandado/intimação/citação/notificação no
    cabeçalho e não traz sinais de sentença ou acórdão."""
    if not texto:
        return False
    cabecalho = texto[:1500]
    if not _TITULO_PROCEDIMENTAL.search(cabecalho):
        return False
    return not _SINAIS_DECISORIOS.search(texto[:3000])


def detectar_segredo_local(texto):
    """Verifica localmente, sem IA, se o documento está sob segredo de justiça.

    Retorna dict:
      - detectado (bool): True = NÃO enviar ao modelo externo
      - nivel: 'explicito' (menção expressa a sigilo), 'materia' (matéria sigilosa por lei) ou None
      - motivo / hipotese_legal: textos genéricos, sem conteúdo do documento
      - procedimental (bool): documento é mandado/intimação/citação/notificação
      - indicios (bool): há indício de sigilo, mesmo quando liberado por ser procedimental
    """
    resultado = {
        "detectado": False, "nivel": None, "motivo": None, "hipotese_legal": None,
        "procedimental": False, "indicios": False,
    }
    if not texto:
        return resultado

    nivel = motivo = hipotese = None

    for regex, descricao in _MARCADORES_EXPLICITOS:
        for m in regex.finditer(texto):
            antes = texto[max(0, m.start() - 80):m.start()]
            if _NEGACAO_ANTES.search(antes):
                continue
            nivel, motivo, hipotese = 'explicito', descricao, "Sigilo indicado no próprio documento"
            break
        if nivel:
            break

    if not nivel:
        for regex, hip in _MATERIAS_SIGILOSAS:
            if regex.search(texto):
                nivel = 'materia'
                motivo = "O assunto do documento é protegido por segredo de justiça"
                hipotese = hip
                break

    if not nivel:
        return resultado

    procedimental = documento_procedimental(texto)
    resultado.update({
        "nivel": nivel, "motivo": motivo, "hipotese_legal": hipotese,
        "procedimental": procedimental, "indicios": True,
    })
    resultado["detectado"] = not (procedimental and SEGREDO_PERMITIR_PROCEDIMENTAIS)
    return resultado


# ============================================================================
# 2. MASCARAMENTO REVERSÍVEL DE DADOS PESSOAIS
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
