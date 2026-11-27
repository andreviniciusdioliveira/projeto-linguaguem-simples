"""Salvaguardas determinísticas aplicadas fora do modelo de IA.

1. detectar_segredo_justica_local: triagem de segredo de justiça feita ANTES de
   qualquer envio do texto ao provedor de IA. Documento sigiloso não procedimental
   é bloqueado localmente e nunca sai do servidor.
2. validar_prazos_contra_original: remove da resposta do modelo qualquer prazo em
   dias/horas cujo número não esteja escrito no documento original. O modelo não
   pode deduzir prazo pela lei (ex.: 15 dias do cível em sentença criminal, cujo
   prazo de apelação é de 5 dias).

Módulo puro (só `re` e `unicodedata`) para poder ser testado sem subir o Flask.
"""
import re
import unicodedata

# Número de processo no padrão CNJ; tolera quebra de linha após o hífen (OCR).
_RE_CNJ = re.compile(r'\d{7}-\s*\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}')

_LIMITE_CABECALHO = 1500
_CABECALHO_SEM_NUMERO = 600


def _normalizar(texto):
    """Maiúsculas, sem acentos e com espaços colapsados."""
    sem_acento = unicodedata.normalize('NFKD', texto or '')
    sem_acento = ''.join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', sem_acento).upper()


def _cabecalho(texto):
    """Trecho que identifica o juízo e a classe processual: do início do documento
    até o primeiro número de processo. Nos documentos do eproc e do SEEU a vara e a
    classe vêm antes do número; partes e conteúdo vêm depois."""
    inicio = (texto or '')[:_LIMITE_CABECALHO + 40]
    m = _RE_CNJ.search(inicio)
    if m:
        return inicio[:min(m.start(), _LIMITE_CABECALHO)]
    return inicio[:_CABECALHO_SEM_NUMERO]


# Título de documento procedimental: linha em maiúsculas que começa com o tipo.
# Deliberadamente restrito: "Int. Cumpra-se" ou "expeça-se mandado" no corpo de um
# despacho NÃO tornam o documento procedimental.
_RE_TITULO_PROCEDIMENTAL = re.compile(
    r'^[ \t]*(?:MANDADO|CARTA DE (?:INTIMAÇÃO|CITAÇÃO|NOTIFICAÇÃO)|INTIMAÇÃO|CITAÇÃO|NOTIFICAÇÃO)'
    r'\b[^a-zà-ÿ\n]{0,80}$',
    re.MULTILINE,
)


def documento_procedimental(texto):
    """True para mandado, intimação, citação ou notificação identificados pelo título."""
    return bool(_RE_TITULO_PROCEDIMENTAL.search((texto or '')[:3000]))


# (padrão sobre o cabeçalho normalizado, descrição do indicador)
_INDICADORES_JUIZO = [
    (r'INFANCIA E (?:DA )?JUVENTUDE', 'juízo da Infância e Juventude'),
    (r'\b(?:VARA|VARAS|JUIZADO|JUIZO)\b[^.]{0,80}\bFAMILIA\b', 'vara de Família'),
    (r'VIOLENCIA DOMESTICA', 'juízo de Violência Doméstica'),
]
_INDICADORES_CLASSE = [
    (r'ATO INFRACIONAL', 'apuração de ato infracional'),
    (r'MEDIDAS? SOCIO-? ?EDUCATIVAS?', 'medida socioeducativa'),
    (r'MEDIDAS? DE PROTECAO', 'medida de proteção'),
    (r'MEDIDAS? PROTETIVAS?', 'medida protetiva'),
    (r'\bADOCAO\b', 'adoção'),
    (r'\bGUARDA\b', 'guarda'),
    (r'PODER FAMILIAR', 'poder familiar'),
    (r'\bALIMENTOS\b', 'alimentos'),
    (r'\bDIVORCIO\b', 'divórcio'),
    (r'UNIAO ESTAVEL', 'união estável'),
    (r'\bPATERNIDADE\b', 'investigação de paternidade'),
    (r'REGULAMENTACAO DE VISITAS', 'regulamentação de visitas'),
    (r'\bINTERDICAO\b|\bCURATELA\b', 'interdição ou curatela'),
]
# Marcação explícita de sigilo no cabeçalho. "(PROCESSO ORIGINÁRIO SIGILOSO)" em decisão
# recursal publicada e "Segredo de Justiça: Não" não contam.
_RE_ORIGINARIO_SIGILOSO = re.compile(r'PROCESSO ORIGINARIO:? ?SIGILOSO')
_RE_SIGILO_EXPLICITO = re.compile(
    r'(?:SEGREDO DE JUSTICA|NIVEL DE SIGILO|\bSIGILOS[OA]\b)(?! ?: ?(?:NAO|SEM|0\b))'
)


def detectar_segredo_justica_local(texto):
    """Triagem local de segredo de justiça, sem IA.

    Retorna dict:
      detectado     True quando o documento deve ser bloqueado sem ir ao provedor de IA.
      procedimental True para mandado/intimação/citação/notificação (não bloqueia:
                    segue a regra do sistema de simplificar atos procedimentais).
      indicadores   lista de indicadores de sigilo encontrados no cabeçalho.
      motivo        texto curto para log (nunca contém conteúdo do documento).
    """
    cab = _normalizar(_cabecalho(texto))
    indicadores = []

    cab_sem_originario = _RE_ORIGINARIO_SIGILOSO.sub(' ', cab)
    if _RE_SIGILO_EXPLICITO.search(cab_sem_originario):
        indicadores.append('marcação explícita de sigilo')
    for padrao, descricao in _INDICADORES_JUIZO + _INDICADORES_CLASSE:
        if re.search(padrao, cab):
            indicadores.append(descricao)

    procedimental = documento_procedimental(texto)
    detectado = bool(indicadores) and not procedimental
    return {
        "detectado": detectado,
        "procedimental": procedimental,
        "indicadores": indicadores,
        "motivo": ("Triagem local: " + ", ".join(indicadores)) if indicadores else None,
    }


# ===================== PRAZOS =====================

_UNIDADES_EXT = ['', 'um', 'dois', 'tres', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove',
                 'dez', 'onze', 'doze', 'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete',
                 'dezoito', 'dezenove']
_DEZENAS_EXT = {20: 'vinte', 30: 'trinta', 40: 'quarenta', 50: 'cinquenta', 60: 'sessenta',
                70: 'setenta', 80: 'oitenta', 90: 'noventa'}


def _por_extenso(n):
    """Formas por extenso (sem acento, minúsculas) de 1 a 99 e das centenas usuais."""
    formas = []
    if 1 <= n < 20:
        formas.append(_UNIDADES_EXT[n])
        if n == 1:
            formas.append('uma')
        if n == 2:
            formas.append('duas')
        if n == 14:
            formas.append('catorze')
    elif n < 100:
        dezena, unidade = (n // 10) * 10, n % 10
        formas.append(_DEZENAS_EXT[dezena] if unidade == 0 else f'{_DEZENAS_EXT[dezena]} e {_UNIDADES_EXT[unidade]}')
    elif n in (100, 120, 180):
        formas.append({100: 'cem', 120: 'cento e vinte', 180: 'cento e oitenta'}[n])
    return formas


def _numero_consta(numero, unidade, original_norm):
    """O prazo "<numero> <unidade>" está escrito no documento original?
    Aceita "15 dias", "15 (quinze) dias", "quinze dias" e "15 dias úteis"."""
    raiz = {'dia': r'dias?', 'hora': r'horas?'}[unidade]
    if re.search(rf'(?<![\d.,/]){numero}\s*(?:\([^)]{{1,30}}\)\s*)?{raiz}\b', original_norm):
        return True
    return any(re.search(rf'\b{forma}\s+{raiz}\b', original_norm) for forma in _por_extenso(numero))


_RE_PRAZO_CAMPO = re.compile(r'(\d{1,3})\s*(?:\([^)]{1,30}\)\s*)?(dia|hora)s?', re.IGNORECASE)

# Prazo em dias/horas dentro do texto simplificado, com o contexto que o introduz.
_RE_PRAZO_TEXTO = re.compile(
    r'(?P<lead>'
    r'(?:\b(?:no|do|o|um|em|dentro do|dentro de um)\s+)?\bprazo\s+(?:(?:é|será|era|máximo|legal)\s+)?de\s+(?:até\s+)?'
    r'|\b(?:em até|dentro de|em|até)\s+'
    r')?'
    r'(?P<n>\d{1,3})\s*(?:\([^)]{1,30}\)\s*)?(?P<u>dia|hora)s?(?P<suf>\s+(?:úteis|corridos))?',
    re.IGNORECASE,
)

_AVISO_PRAZO = (" (o documento não informa o número de dias; confirme o prazo com advogado(a) "
                "ou com a Defensoria Pública o quanto antes)")


def _substituto(lead):
    """Texto que entra no lugar de um prazo não escrito no documento."""
    l = (lead or '').lower().strip()
    if not l:
        return 'o prazo previsto em lei'
    if 'prazo' not in l:
        return 'no prazo previsto em lei'
    if re.search(r'\b(é|será|era)\b', l):
        artigo = 'o ' if l.startswith('o ') else ''
        verbo = re.search(r'\b(é|será|era)\b', l).group(1)
        return f'{artigo}prazo {verbo} o previsto em lei'
    for prefixo in ('dentro do', 'dentro de um', 'no', 'do', 'um', 'em', 'o'):
        if l.startswith(prefixo + ' '):
            artigo = {'dentro de um': 'dentro do', 'um': 'o', 'em': 'no'}.get(prefixo, prefixo)
            return f'{artigo} prazo previsto em lei'
    return 'prazo previsto em lei'


def validar_prazos_contra_original(analise, texto_original):
    """Remove da análise todo prazo em dias/horas cujo número não esteja escrito no
    documento original. Altera `analise` no lugar (prazos, recursos_cabiveis.prazo e
    texto_simplificado) e retorna a lista de prazos removidos, para log."""
    original_norm = _normalizar(texto_original).lower()
    removidos = []

    def consta(texto_prazo):
        """None se o texto não traz prazo numérico; senão True/False."""
        m = _RE_PRAZO_CAMPO.search(str(texto_prazo or ''))
        if not m:
            return None
        return _numero_consta(int(m.group(1)), m.group(2).lower(), original_norm)

    prazos = analise.get("prazos")
    if isinstance(prazos, list):
        mantidos = []
        for p in prazos:
            valor = p.get("prazo") if isinstance(p, dict) else p
            if consta(valor) is False:
                removidos.append(str(valor))
            else:
                mantidos.append(p)
        analise["prazos"] = mantidos

    recursos = analise.get("recursos_cabiveis")
    if isinstance(recursos, dict) and consta(recursos.get("prazo")) is False:
        removidos.append(str(recursos.get("prazo")))
        recursos["prazo"] = None

    texto = analise.get("texto_simplificado")
    if isinstance(texto, str) and texto:
        avisou = [False]

        def trocar(m):
            if _numero_consta(int(m.group('n')), m.group('u').lower(), original_norm):
                return m.group(0)
            removidos.append(m.group(0).strip())
            novo = _substituto(m.group('lead'))
            if m.group(0)[:1].isupper():
                novo = novo[:1].upper() + novo[1:]
            if not avisou[0]:
                avisou[0] = True
                novo += _AVISO_PRAZO
            return novo

        analise["texto_simplificado"] = _RE_PRAZO_TEXTO.sub(trocar, texto)

    if removidos:
        analise["prazos_removidos"] = removidos
    return removidos
