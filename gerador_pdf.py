"""
Gerador de PDF Aprimorado - Entenda Aqui
Sistema de simplificação de documentos jurídicos
Desenvolvido por INOVASSOL - Centro de Inovação do Tribunal de Justiça do Estado do Tocantins
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime
import os
import re

# ==================== CORES JUS ====================
COR_VINHO = HexColor('#6d2932')
COR_AZUL = HexColor('#2c4f5e')
COR_DOURADO = HexColor('#b8963c')
COR_VERDE = HexColor('#34a853')
COR_VERMELHO = HexColor('#ea4335')
COR_LARANJA = HexColor('#fbbc04')
COR_CINZA_CLARO = HexColor('#f8f9fa')
COR_CINZA_ESCURO = HexColor('#5f6368')
COR_FUNDO = HexColor('#f5f7fa')

# ==================== CONFIGURAÇÕES ====================
MARGEM_X = 2 * cm
MARGEM_Y = 2 * cm
LARGURA_UTIL = A4[0] - 2 * MARGEM_X
ALTURA_UTIL = A4[1] - 2 * MARGEM_Y

# Caminhos das logos
LOGO_JUS = 'static/avatar.png'
LOGO_INOVASSOL = 'static/inovassol.png'

# ==================== ÍCONES UNICODE ====================
ICONES = {
    'vitoria': '✅',
    'vitoria_parcial': '🟡',
    'derrota': '❌',
    'neutro': '⚪',
    'documento': '📄',
    'dinheiro': '💰',
    'calendario': '📅',
    'balanca': '⚖️',
    'alerta': '⚠️',
    'info': 'ℹ️',
    'juiz': '👨‍⚖️',
    'check': '✓',
    'seta': '→',
    'estrela': '⭐',
    'telefone': '📞',
    'localizacao': '📍',
    'relogio': '🕐',
    'internet': '🌐',
    'email': '✉️'
}

# ==================== CLASSE DE CABEÇALHO/RODAPÉ ====================
class CabecalhoRodape:
    def __init__(self, logo_jus=None, logo_inovassol=None):
        self.logo_jus = logo_jus
        self.logo_inovassol = logo_inovassol

    def cabecalho(self, canvas_obj, doc):
        """Desenha cabeçalho com logos em todas as páginas"""
        canvas_obj.saveState()

        # Fundo do cabeçalho
        canvas_obj.setFillColor(COR_AZUL)
        canvas_obj.rect(0, A4[1] - 1.5*cm, A4[0], 1.5*cm, fill=True, stroke=False)

        # Logo JUS (esquerda)
        if self.logo_jus and os.path.exists(self.logo_jus):
            try:
                canvas_obj.drawImage(
                    self.logo_jus,
                    MARGEM_X,
                    A4[1] - 1.3*cm,
                    width=1*cm,
                    height=1*cm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except:
                pass

        # Título central
        canvas_obj.setFillColor(white)
        canvas_obj.setFont('Helvetica-Bold', 14)
        canvas_obj.drawCentredString(
            A4[0]/2,
            A4[1] - 1*cm,
            'Documento em Linguagem Simples'
        )

        # Logo INOVASSOL (direita)
        if self.logo_inovassol and os.path.exists(self.logo_inovassol):
            try:
                canvas_obj.drawImage(
                    self.logo_inovassol,
                    A4[0] - MARGEM_X - 1*cm,
                    A4[1] - 1.3*cm,
                    width=1*cm,
                    height=1*cm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except:
                pass

        canvas_obj.restoreState()

    def rodape(self, canvas_obj, doc):
        """Desenha rodapé com informações do TJTO"""
        canvas_obj.saveState()

        # Linha separadora
        canvas_obj.setStrokeColor(COR_DOURADO)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(MARGEM_X, 3*cm, A4[0] - MARGEM_X, 3*cm)

        # Desenvolvido por
        canvas_obj.setFillColor(COR_AZUL)
        canvas_obj.setFont('Helvetica-Bold', 9)
        canvas_obj.drawCentredString(A4[0]/2, 2.5*cm, 'Desenvolvido pelo INOVASSOL - Centro de Inovação do Tribunal de Justiça do Estado do Tocantins')

        # Endereço
        canvas_obj.setFillColor(COR_CINZA_ESCURO)
        canvas_obj.setFont('Helvetica', 8)

        # Linha 1: SEDE
        canvas_obj.drawCentredString(
            A4[0]/2,
            2.1*cm,
            'SEDE: Palácio da Justiça Rio Tocantins, Praça dos Girassóis, s/nº Centro'
        )

        # Linha 2: Cidade/CEP
        canvas_obj.drawCentredString(
            A4[0]/2,
            1.8*cm,
            'Palmas - Tocantins / CEP: 77015-007'
        )

        # Linha 3: Contatos
        canvas_obj.setFont('Helvetica-Bold', 8)
        canvas_obj.drawCentredString(
            A4[0]/2,
            1.5*cm,
            f'{ICONES["telefone"]} (63) 3142-2200 / (63) 3142-2201'
        )

        # Linha 4: Horário e Site
        canvas_obj.setFont('Helvetica', 8)
        canvas_obj.drawCentredString(
            A4[0]/2,
            1.2*cm,
            f'{ICONES["relogio"]} Atendimento ao público: 12:00 às 18:00 | {ICONES["internet"]} www.tjto.jus.br'
        )

        # Número da página
        canvas_obj.setFillColor(COR_AZUL)
        canvas_obj.setFont('Helvetica', 9)
        canvas_obj.drawRightString(
            A4[0] - MARGEM_X,
            0.7*cm,
            f'Página {doc.page}'
        )

        canvas_obj.restoreState()

# ==================== ESTILOS ====================
def criar_estilos():
    """Cria estilos customizados para o PDF"""
    styles = getSampleStyleSheet()

    # Título principal
    styles.add(ParagraphStyle(
        name='TituloPrincipal',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=COR_AZUL,
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))

    # Subtítulo
    styles.add(ParagraphStyle(
        name='Subtitulo',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=COR_VINHO,
        spaceBefore=12,
        spaceAfter=8,
        fontName='Helvetica-Bold',
        borderColor=COR_DOURADO,
        borderWidth=0,
        borderPadding=5,
        leftIndent=0,
        backColor=None
    ))

    # Texto normal
    styles.add(ParagraphStyle(
        name='TextoNormal',
        parent=styles['Normal'],
        fontSize=11,
        leading=16,
        textColor=black,
        alignment=TA_JUSTIFY,
        fontName='Helvetica'
    ))

    # Texto destaque
    styles.add(ParagraphStyle(
        name='TextoDestaque',
        parent=styles['Normal'],
        fontSize=11,
        textColor=COR_AZUL,
        fontName='Helvetica-Bold',
        spaceAfter=6
    ))

    # Valor monetário
    styles.add(ParagraphStyle(
        name='ValorMonetario',
        parent=styles['Normal'],
        fontSize=13,
        textColor=COR_VERDE,
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    ))

    # Info box
    styles.add(ParagraphStyle(
        name='InfoBox',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COR_CINZA_ESCURO,
        fontName='Helvetica',
        leftIndent=10,
        rightIndent=10
    ))

    return styles

# ==================== FUNÇÕES AUXILIARES ====================
def criar_caixa_destaque(texto, cor_fundo, cor_texto, icone=''):
    """Cria uma caixa de destaque colorida"""
    return Table(
        [[f'{icone} {texto}']],
        colWidths=[LARGURA_UTIL],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), cor_fundo),
            ('TEXTCOLOR', (0, 0), (-1, -1), cor_texto),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('ROUNDEDCORNERS', [10, 10, 10, 10]),
        ])
    )

def detectar_tipo_resultado(texto):
    """Detecta o tipo de resultado baseado nos ícones presentes no texto"""
    if '✅ CONSEGUIU O QUE PEDIU' in texto:
        return 'vitoria'
    elif '🟡 CONSEGUIU PARTE DO QUE PEDIU' in texto:
        return 'vitoria_parcial'
    elif '❌ NÃO CONSEGUIU O QUE PEDIU' in texto:
        return 'derrota'
    elif '⚪ PEDIDO NEGADO' in texto:
        return 'derrota'
    return 'neutro'

def extrair_secoes(texto):
    """Extrai seções do texto simplificado"""
    secoes = {}

    # Padrões de seções
    padroes = {
        'resultado': r'(✅|🟡|❌|⚪)\s*(CONSEGUIU.*?|NÃO CONSEGUIU.*?|PEDIDO NEGADO.*?)(?=\n\n|\Z)',
        'resumo': r'📋\s*\*\*O QUE ESTÁ ACONTECENDO\*\*.*?\n\n(.*?)(?=\n\n[📋⚖️💰📅💡]|\Z)',
        'decisao': r'⚖️\s*\*\*A DECISÃO.*?\*\*.*?\n\n(.*?)(?=\n\n[📋⚖️💰📅💡]|\Z)',
        'valores': r'💰\s*\*\*VALORES.*?\*\*.*?\n\n(.*?)(?=\n\n[📋⚖️💰📅💡]|\Z)',
        'prazos': r'📅\s*\*\*PRAZOS.*?\*\*.*?\n\n(.*?)(?=\n\n[📋⚖️💰📅💡]|\Z)',
        'glossario': r'💡\s*\*\*PALAVRAS.*?\*\*.*?\n\n(.*?)(?=\Z)',
    }

    for chave, padrao in padroes.items():
        match = re.search(padrao, texto, re.DOTALL)
        if match:
            if chave == 'resultado':
                secoes[chave] = match.group(0).strip()
            else:
                secoes[chave] = match.group(1).strip()

    return secoes

# ==================== FUNÇÃO PRINCIPAL ====================
def gerar_pdf_simplificado(texto, metadados=None, filename="documento_simplificado.pdf"):
    """
    Gera PDF simplificado com layout profissional

    Args:
        texto: texto simplificado completo
        metadados: dicionário com metadados do processamento
        filename: nome do arquivo de saída
    """

    # Criar documento
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGEM_X,
        leftMargin=MARGEM_X,
        topMargin=2.5*cm,  # Espaço para cabeçalho
        bottomMargin=3.5*cm  # Espaço para rodapé
    )

    # Criar estilos
    styles = criar_estilos()

    # Story (conteúdo do PDF)
    story = []

    # ========== METADADOS ==========
    story.append(Spacer(1, 0.3*cm))

    # Info de geração
    data_hora = datetime.now().strftime('%d/%m/%Y às %H:%M')
    info_geracao = f"""
    <para align=center>
    <font size=9 color=#5f6368>
    Gerado em: {data_hora}<br/>
    """

    if metadados:
        if metadados.get('modelo'):
            info_geracao += f"Processado com: {metadados['modelo']}<br/>"
        if metadados.get('tipo_documento'):
            info_geracao += f"Tipo: {metadados['tipo_documento'].upper()}<br/>"

    info_geracao += """
    </font>
    </para>
    """
    story.append(Paragraph(info_geracao, styles['InfoBox']))
    story.append(Spacer(1, 0.5*cm))

    # ========== DETECTAR TIPO DE RESULTADO ==========
    tipo_resultado = detectar_tipo_resultado(texto)

    if tipo_resultado == 'vitoria':
        caixa_resultado = criar_caixa_destaque(
            'CONSEGUIU O QUE PEDIU',
            COR_VERDE,
            white,
            ICONES['vitoria']
        )
    elif tipo_resultado == 'vitoria_parcial':
        caixa_resultado = criar_caixa_destaque(
            'CONSEGUIU PARTE DO QUE PEDIU',
            COR_LARANJA,
            white,
            ICONES['vitoria_parcial']
        )
    elif tipo_resultado == 'derrota':
        caixa_resultado = criar_caixa_destaque(
            'NÃO CONSEGUIU O QUE PEDIU',
            COR_VERMELHO,
            white,
            ICONES['derrota']
        )
    else:
        caixa_resultado = criar_caixa_destaque(
            'DOCUMENTO PROCESSADO',
            COR_AZUL,
            white,
            ICONES['documento']
        )

    story.append(caixa_resultado)
    story.append(Spacer(1, 0.7*cm))

    # ========== EXTRAIR SEÇÕES ==========
    secoes = extrair_secoes(texto)

    # ========== O QUE ESTÁ ACONTECENDO ==========
    if 'resumo' in secoes:
        story.append(Paragraph(
            f"{ICONES['info']} O QUE ESTÁ ACONTECENDO",
            styles['Subtitulo']
        ))
        story.append(Spacer(1, 0.3*cm))

        resumo = secoes['resumo'].replace('**', '').strip()
        story.append(Paragraph(resumo, styles['TextoNormal']))
        story.append(Spacer(1, 0.7*cm))

    # ========== A DECISÃO ==========
    if 'decisao' in secoes:
        story.append(Paragraph(
            f"{ICONES['balanca']} A DECISÃO DO JUIZ",
            styles['Subtitulo']
        ))
        story.append(Spacer(1, 0.3*cm))

        decisao = secoes['decisao'].replace('**', '').strip()
        story.append(Paragraph(decisao, styles['TextoNormal']))
        story.append(Spacer(1, 0.7*cm))

    # ========== VALORES ==========
    if 'valores' in secoes:
        story.append(Paragraph(
            f"{ICONES['dinheiro']} VALORES E O QUE VOCÊ PRECISA FAZER",
            styles['Subtitulo']
        ))
        story.append(Spacer(1, 0.3*cm))

        valores = secoes['valores'].replace('**', '').strip()
        story.append(Paragraph(valores, styles['TextoNormal']))
        story.append(Spacer(1, 0.7*cm))

    # ========== PRAZOS ==========
    if 'prazos' in secoes:
        story.append(Paragraph(
            f"{ICONES['calendario']} PRAZOS IMPORTANTES",
            styles['Subtitulo']
        ))
        story.append(Spacer(1, 0.3*cm))

        prazos = secoes['prazos'].replace('**', '').strip()
        story.append(Paragraph(prazos, styles['TextoNormal']))
        story.append(Spacer(1, 0.7*cm))

    # ========== GLOSSÁRIO ==========
    if 'glossario' in secoes:
        story.append(Paragraph(
            f"{ICONES['info']} PALAVRAS QUE PODEM APARECER NO DOCUMENTO",
            styles['Subtitulo']
        ))
        story.append(Spacer(1, 0.3*cm))

        glossario = secoes['glossario'].replace('**', '').strip()
        story.append(Paragraph(glossario, styles['TextoNormal']))
        story.append(Spacer(1, 0.7*cm))

    # ========== AVISO FINAL ==========
    story.append(Spacer(1, 0.5*cm))
    aviso = criar_caixa_destaque(
        'Este documento não substitui a orientação jurídica. Se precisar, busque ajuda com um advogado ou na Defensoria Pública.',
        HexColor('#fff3cd'),
        COR_CINZA_ESCURO,
        ICONES['alerta']
    )
    story.append(aviso)

    # ========== GERAR PDF ==========
    cabecalho_rodape = CabecalhoRodape(LOGO_JUS, LOGO_INOVASSOL)

    doc.build(
        story,
        onFirstPage=lambda canvas_obj, doc: (
            cabecalho_rodape.cabecalho(canvas_obj, doc),
            cabecalho_rodape.rodape(canvas_obj, doc)
        ),
        onLaterPages=lambda canvas_obj, doc: (
            cabecalho_rodape.cabecalho(canvas_obj, doc),
            cabecalho_rodape.rodape(canvas_obj, doc)
        )
    )

    # Salvar arquivo
    pdf = buffer.getvalue()
    buffer.close()

    with open(filename, 'wb') as f:
        f.write(pdf)

    return filename
