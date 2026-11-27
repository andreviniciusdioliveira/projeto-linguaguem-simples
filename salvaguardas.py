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
_RE_CNJ = re.compile(r'(?<!\d)\d{7}-?\s*\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}')

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


# ===================== PEÇAS QUE NÃO SÃO DO PODER JUDICIÁRIO =====================
# Sistemas como o SEEU e o eproc guardam tanto atos de magistrados e servidores quanto
# peças das partes. O que decide é QUEM ASSINA o documento, e não o sistema de origem.

_RE_TITULO_JUDICIAL = re.compile(
    r'^[ \t]*(?:SENTENÇA|DECISÃO|DESPACHO(?:\s*/\s*DECISÃO)?|ACÓRDÃO|VOTO|EMENTA|CERTIDÃO|ATO ORDINATÓRIO)[ \t]*$',
    re.MULTILINE,
)


def detectar_peca_nao_judicial(texto):
    """Identifica manifestação do Ministério Público (peça de parte, não ato judicial).

    Retorna {"detectado": bool, "razao": str | None}. Não bloqueia documentos assinados
    por magistrado ou servidor, ainda que venham do mesmo sistema."""
    texto = texto or ''
    inicio = _normalizar(texto[:1500])
    fim = _normalizar(texto[-700:])
    tudo = _normalizar(texto)

    assinado_por_magistrado = bool(re.search(r'JUIZ(?:A)? (?:\(A\) )?DE DIREITO|JUIZ(?:A)? SUBSTITUT|DESEMBARGADOR', fim))
    tem_titulo_judicial = bool(_RE_TITULO_JUDICIAL.search(texto[:3000]))
    if documento_procedimental(texto) or assinado_por_magistrado or tem_titulo_judicial:
        return {"detectado": False, "razao": None}

    assinatura_mp = bool(re.search(r'PROMOTOR(?:A)? DE JUSTICA|PROCURADOR(?:A)? DE JUSTICA|PROCURADOR(?:A)? DA REPUBLICA', fim))
    vocativo = bool(re.search(r'(?:SENHOR(?:A)?|MM\.?|MERITISSIM[OA]|EXCELENTISSIM[OA])[^.]{0,40}\bJUIZ', inicio))
    juntada = 'JUNTADA DE MANIFESTACAO' in inicio or 'PARECER DO MINISTERIO PUBLICO' in inicio
    opina = bool(re.search(r'PELO (?:IN)?DEFERIMENTO|MINISTERIO PUBLICO[^.]{0,80}(?:MANIFESTA-SE|REQUER|OPINA|PUGNA)', tudo[-2500:]))

    if assinatura_mp and sum([vocativo, juntada, opina]) >= 1:
        return {"detectado": True,
                "razao": "Manifestação do Ministério Público: é a opinião do promotor, e não uma decisão do juiz."}
    return {"detectado": False, "razao": None}


# ===================== JUSTIÇA GRATUITA =====================

_RE_GRATUIDADE_ORIGINAL = re.compile(r'gratuidade|justica gratuita|assistencia judiciaria')
_RE_SEM_CUSTAS_ORIGINAL = re.compile(r'sem (?:condenacao em )?custas|isent[oa]s? de custas')
_RE_FRASE_GRATUIDADE = re.compile(
    r'\s*,?\s*porque\s+(?:você\s+|voce\s+)?(?:tem|possui|recebeu|é\s+beneficiári[oa]\s+d[ae])\s+(?:direito\s+[àa]\s+)?'
    r'(?:a\s+)?(?:justiça\s+gratuita|gratuidade(?:\s+d[ae]\s+justiça)?)', re.IGNORECASE)
_RE_SENTENCA_CUSTAS = re.compile(r'[^\n.]*\bN[ÃA]O\s+vai\s+pagar\s+custas[^\n.]*\.', re.IGNORECASE)


def validar_gratuidade(analise, texto_original):
    """Remove a menção a justiça gratuita quando o documento original não a contém.
    Em juizados, por exemplo, não há custas por força de lei, e não por gratuidade."""
    orig = _normalizar(texto_original).lower()
    if _RE_GRATUIDADE_ORIGINAL.search(orig):
        return False
    sem_custas = bool(_RE_SEM_CUSTAS_ORIGINAL.search(orig))
    alterou = False
    if analise.get("tem_justica_gratuita"):
        analise["tem_justica_gratuita"] = False
        alterou = True
    valores = analise.get("valores_principais")
    if isinstance(valores, dict):
        for chave in ("custas", "honorarios"):
            v = valores.get(chave)
            if isinstance(v, str) and 'gratuit' in _normalizar(v).lower():
                valores[chave] = "Sem cobrança, conforme o documento" if sem_custas else None
                alterou = True
    texto = analise.get("texto_simplificado")
    if isinstance(texto, str) and _RE_FRASE_GRATUIDADE.search(texto):
        if sem_custas:
            novo = _RE_FRASE_GRATUIDADE.sub(", conforme consta do documento", texto)
        else:
            novo = _RE_SENTENCA_CUSTAS.sub("O documento não informa quem paga as custas e os honorários.", texto)
            novo = _RE_FRASE_GRATUIDADE.sub("", novo)
        if novo != texto:
            analise["texto_simplificado"] = novo
            alterou = True
    return alterou


# ===================== DATA DA ASSINATURA E PRAZOS ESCRITOS =====================

_MESES = {m: i + 1 for i, m in enumerate(
    ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'])}


def extrair_data_assinatura(texto):
    """Data em que o documento foi assinado, lida do próprio documento (dd/mm/aaaa) ou None."""
    texto = texto or ''
    # eproc: "Data e Hora: 28/10/2025, às 10:24:28" (a última assinatura fecha o ato)
    m = re.findall(r'Data\s+e\s+Hora:\s*(\d{1,2})/(\d{1,2})/(\d{4})', texto)
    if not m:
        m = re.findall(r'assinad[oa][^\n]{0,120}?\bem\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})', texto, re.IGNORECASE)
    if m:
        d, mes, a = m[-1]
        return f"{int(d):02d}/{int(mes):02d}/{a}"
    # fecho por extenso: "Palmas/TO, 4 de agosto de 2025."
    fim = unicodedata.normalize('NFKD', texto[-2500:])
    fim = ''.join(c for c in fim if not unicodedata.combining(c)).lower()
    m = re.findall(r'(\d{1,2})[ºo°]?\s+de\s+(' + '|'.join(_MESES) + r')\s+de\s+(\d{4})', fim)
    if m:
        d, mes, a = m[-1]
        return f"{int(d):02d}/{_MESES[mes]:02d}/{a}"
    return None


_RE_INICIO_DISPOSITIVO = re.compile(
    r'DISPOSITIVO|ANTE O EXPOSTO|DIANTE DO EXPOSTO|PELO EXPOSTO|POSTO ISSO|ISTO POSTO|ISSO POSTO|JULGO\s|DETERMIN[AO]\b|DECIDO\b',
    re.IGNORECASE)
_RE_PRAZO_ESCRITO = re.compile(
    r'(?:prazo[^.;\n]{0,40}?\bde\s+|\bem\s+(?:até\s+)?|\bno\s+prazo\s+de\s+)(\d{1,3})\s*(?:\([^)]{1,30}\)\s*)?(dias?(?:\s+úteis|\s+corridos)?|horas?)',
    re.IGNORECASE)


def extrair_prazos_escritos(texto, max_itens=4):
    """Prazos em dias ou horas ESCRITOS na parte decisória do documento.
    Retorna lista de {"prazo": "15 dias", "trecho": "frase do documento"}."""
    texto = texto or ''
    inicios = [m.start() for m in _RE_INICIO_DISPOSITIVO.finditer(texto) if m.start() > len(texto) * 0.35]
    parte = texto[inicios[0]:] if inicios else texto[-4000:]
    parte = re.sub(r'\s+', ' ', parte)
    achados, vistos = [], set()
    for m in _RE_PRAZO_ESCRITO.finditer(parte):
        prazo = f"{int(m.group(1))} {m.group(2).lower()}"
        ini = max(parte.rfind('. ', 0, m.start()), parte.rfind('; ', 0, m.start())) + 2
        fim = min([p for p in (parte.find('. ', m.end()), parte.find('; ', m.end())) if p != -1] or [len(parte)])
        trecho = parte[ini:fim].strip()
        if len(trecho) > 230:
            c = m.start() - ini
            trecho = ('… ' if c > 110 else '') + trecho[max(0, c - 110):c + 120].strip() + ' …'
        if prazo in vistos or len(trecho) < 12:
            continue
        vistos.add(prazo)
        achados.append({"prazo": prazo, "trecho": trecho})
        if len(achados) >= max_itens:
            break
    return achados


def bloco_data_e_prazos(texto_original, truncado=False):
    """Seção acrescentada ao texto simplificado com o que o PRÓPRIO DOCUMENTO informa:
    data da assinatura e prazos escritos. Não calcula data final: o prazo conta, em regra,
    da intimação, e não da assinatura. Retorna (markdown, dados)."""
    data = extrair_data_assinatura(texto_original)
    prazos = extrair_prazos_escritos(texto_original)
    linhas = ["**DATA E PRAZOS QUE CONSTAM NO DOCUMENTO**", ""]
    linhas.append(f"- Documento assinado em {data}." if data else "- Não foi possível ler a data da assinatura no documento.")
    if prazos:
        for p in prazos:
            linhas.append(f"- Prazo escrito no documento: {p['prazo']} (“{p['trecho']}”).")
        linhas += ["", "O prazo começa a contar, em regra, do dia em que você foi avisado oficialmente (intimação), e não da data da assinatura. "
                       "Confirme a data final com advogado(a) ou com a Defensoria Pública."]
    else:
        linhas.append("- O documento não informa prazo em dias. Se você precisar recorrer ou cumprir alguma ordem, "
                      "procure advogado(a) ou a Defensoria Pública o quanto antes: os prazos são curtos.")
    if truncado:
        linhas += ["", "Atenção: este documento é longo e uma parte do meio não foi analisada. Leia o original ou peça ajuda para conferir."]
    return "\n".join(linhas), {"data_assinatura": data, "prazos_documento": prazos}


def anexar_bloco(texto_simplificado, bloco):
    """Insere o bloco antes da dica final do texto simplificado (ou ao fim)."""
    m = re.search(r'\n-{3,}\s*\n+\*?\s*💡', texto_simplificado or '')
    if m:
        return texto_simplificado[:m.start()] + "\n\n---\n\n" + bloco + texto_simplificado[m.start():]
    return (texto_simplificado or '').rstrip() + "\n\n---\n\n" + bloco + "\n"


# ===================== TÍTULOS E RÓTULOS FIXOS =====================

import difflib  # noqa: E402

_ROTULOS = ["CONSEGUIU O QUE PEDIU", "CONSEGUIU PARTE DO QUE PEDIU", "NÃO CONSEGUIU O QUE PEDIU", "PEDIDO NEGADO",
            "VITÓRIA TOTAL", "VITÓRIA PARCIAL", "CONDENAÇÃO", "CONDENAÇÃO PARCIAL", "ABSOLVIÇÃO"]


def _taxa(a, b):
    return difflib.SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def normalizar_titulos(texto, texto_original=""):
    """Corrige, sem IA, títulos de seção com texto incoerente e rótulos de resultado com erro
    de digitação. Não muda o sentido: só troca por títulos fixos."""
    if not isinstance(texto, str) or not texto.strip():
        return texto
    linhas = texto.split("\n")
    orig = _normalizar(texto_original).lower()
    primeira = next((i for i, l in enumerate(linhas) if l.strip()), None)
    for i, linha in enumerate(linhas):
        limpo = re.sub(r'[*#_]', '', linha).strip()
        chave = _normalizar(limpo)
        if chave.startswith("VALORES E O QUE"):
            linhas[i] = "**VALORES E O QUE VOCÊ PRECISA FAZER**"
        elif chave.startswith("PALAVRAS QUE") and len(chave) < 60:
            linhas[i] = "**PALAVRAS QUE PODEM APARECER NO DOCUMENTO**"
        elif i == primeira:
            m = re.match(r'^([^A-Za-zÀ-ÿ]*)(.*?)([^A-Za-zÀ-ÿ]*)$', limpo)
            rotulo = m.group(2).strip()
            if 6 <= len(rotulo) <= 40 and rotulo.upper() == rotulo:
                melhor = max(_ROTULOS, key=lambda r: _taxa(r, rotulo))
                novo = melhor if _taxa(melhor, rotulo) >= 0.86 else rotulo
                if "CONDENA" in _normalizar(novo) and "PARCIAL" in _normalizar(novo) \
                        and "julgo procedente" in orig \
                        and not re.search(r'parcialmente procedente|procedente em parte|parcial procedencia', orig):
                    novo = "CONDENAÇÃO"
                if novo != rotulo:
                    linhas[i] = linha.replace(rotulo, novo)
    return "\n".join(linhas)


# O hífen é opcional: o pós-processamento do OCR une "0011307-" e "98.2025..." em "001130798.2025...".
_RE_CNJ_QUEBRADO = re.compile(r'(?<!\d)(\d{7})-?\s*(\d{2})\.\s*(\d{4})\.\s*(\d)\.\s*(\d{2})\.\s*(\d{4})')


def extrair_numero_processo(texto):
    """Primeiro número de processo no padrão CNJ, mesmo quando quebrado em duas linhas."""
    m = _RE_CNJ_QUEBRADO.search(texto or '')
    return "{}-{}.{}.{}.{}.{}".format(*m.groups()) if m else None

# ===================== DATAS COM ANO INCOMPLETO =====================

_RE_DATA_EXTENSO_CURTA = re.compile(r'\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{3})\b(?!\d)', re.IGNORECASE)
_RE_DATA_NUM_CURTA = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{3})\b(?!\d)')


def corrigir_datas_incompletas(analise, texto_original):
    """Quando o original traz a mesma data duas vezes, uma com erro de digitação no ano
    ("26 de maio de 205") e outra completa ("26/05/2025"), usa a forma completa e avisa.
    Só corrige se houver UMA data completa com o mesmo dia e mês no documento."""
    completas = {}
    for d, m, a in re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', texto_original or ''):
        completas.setdefault((int(d), int(m)), set()).add(a)

    def ano_para(dia, mes):
        anos = completas.get((dia, mes), set())
        return next(iter(anos)) if len(anos) == 1 else None

    corrigiu = [False]

    def troca_extenso(m):
        mes = _MESES.get(''.join(c for c in unicodedata.normalize('NFKD', m.group(2).lower()) if not unicodedata.combining(c)))
        ano = ano_para(int(m.group(1)), mes) if mes else None
        if not ano:
            return m.group(0)
        corrigiu[0] = True
        return f"{m.group(1)} de {m.group(2)} de {ano}"

    def troca_num(m):
        ano = ano_para(int(m.group(1)), int(m.group(2)))
        if not ano:
            return m.group(0)
        corrigiu[0] = True
        return f"{m.group(1)}/{m.group(2)}/{ano}"

    texto = analise.get("texto_simplificado")
    if isinstance(texto, str):
        analise["texto_simplificado"] = _RE_DATA_NUM_CURTA.sub(troca_num, _RE_DATA_EXTENSO_CURTA.sub(troca_extenso, texto))
    aud = analise.get("audiencia")
    if isinstance(aud, dict) and isinstance(aud.get("data"), str):
        aud["data"] = _RE_DATA_NUM_CURTA.sub(troca_num, aud["data"])
    if corrigiu[0] and isinstance(analise.get("texto_simplificado"), str):
        analise["texto_simplificado"] = anexar_bloco(
            analise["texto_simplificado"],
            "**ATENÇÃO À DATA**\n\nO documento original traz essa data com um erro de digitação no ano em um dos trechos. "
            "Usamos a data completa que aparece em outra parte do mesmo documento. Confirme no fórum se tiver dúvida.")
    return corrigiu[0]
