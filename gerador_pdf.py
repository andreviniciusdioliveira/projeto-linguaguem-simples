"""
Gerador de PDF Melhorado para o Entenda Aqui
Versão robusta que garante inclusão completa do texto
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os
import io
import math
import logging
from datetime import datetime

# QR Code
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logging.warning("⚠️ qrcode não disponível - QR codes não serão gerados")

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Cores JUS
JUS_VINHO = colors.HexColor('#6d2932')
JUS_AZUL = colors.HexColor('#2c4f5e')
JUS_DOURADO = colors.HexColor('#b8963c')

def registrar_fontes():
    """Registra fontes personalizadas se disponíveis"""
    try:
        # Tentar usar fontes do sistema
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            'C:\\Windows\\Fonts\\arial.ttf'
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path))
                    logging.info(f"✅ Fonte registrada: {font_path}")
                    return True
                except:
                    continue
    except Exception as e:
        logging.warning(f"Usando fontes padrão: {e}")
    
    return False

class HeaderFooterCanvas(canvas.Canvas):
    """Canvas customizado com cabeçalho e rodapé"""
    
    def __init__(self, *args, **kwargs):
        self.metadados = kwargs.pop('metadados', {})
        canvas.Canvas.__init__(self, *args, **kwargs)
        self.pages = []
        
    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()
        
    def save(self):
        page_count = len(self.pages)
        for page_num, page_dict in enumerate(self.pages, 1):
            self.__dict__.update(page_dict)
            self.draw_header_footer(page_num, page_count)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)
        
    def draw_header_footer(self, page_num, page_count):
        """Desenha cabeçalho, rodapé e marca d'água em cada página"""
        page_width, page_height = A4

        # MARCA D'ÁGUA DIAGONAL - Aviso de finalidade informativa
        self.saveState()
        self.setFillColor(colors.Color(0, 0, 0, alpha=0.06))
        self.setFont('Helvetica-Bold', 14)

        marca_dagua_texto = "SEM VALOR OFICIAL - DOCUMENTO INFORMATIVO"

        # Calcular posições para repetir a marca d'água em toda a página
        angulo = 45
        # Espaçamento entre linhas da marca d'água
        espacamento_y = 4 * cm
        espacamento_x = 1 * cm

        # Cobrir toda a página com linhas diagonais de marca d'água
        for y in range(-5, int(page_height / espacamento_y) + 5):
            for x in range(-2, 4):
                pos_x = x * 8 * cm + espacamento_x
                pos_y = y * espacamento_y
                self.saveState()
                self.translate(pos_x, pos_y)
                self.rotate(angulo)
                self.drawString(0, 0, marca_dagua_texto)
                self.restoreState()

        self.restoreState()

        # MARCA D'ÁGUA TJTO - Múltiplas miniaturas da logo para dificultar falsificação
        logo_tjto_path = 'static/logotjto.png'
        if os.path.exists(logo_tjto_path):
            try:
                self.saveState()

                # Padrão de miniaturas em grade cobrindo toda a página
                # Tamanhos variados para criar complexidade visual anti-falsificação
                tamanhos_mini = [1.8 * cm, 2.2 * cm, 1.5 * cm, 2.0 * cm, 1.6 * cm]
                rotacoes = [0, 15, -10, 5, -15, 20, -5, 10]
                alphas = [0.08, 0.10, 0.07, 0.09, 0.12]

                # Espaçamento da grade
                espacamento_x = 4.5 * cm
                espacamento_y = 4.0 * cm

                # Offset alternado para padrão de "tijolos" (mais difícil de reproduzir)
                idx = 0
                for row in range(int(page_height / espacamento_y) + 1):
                    # Linhas ímpares têm offset horizontal
                    offset_x = (espacamento_x / 2) if row % 2 else 0

                    for col in range(int(page_width / espacamento_x) + 1):
                        pos_x = col * espacamento_x + offset_x
                        pos_y = row * espacamento_y

                        # Variação de tamanho, rotação e transparência por posição
                        tamanho = tamanhos_mini[idx % len(tamanhos_mini)]
                        rotacao = rotacoes[idx % len(rotacoes)]
                        alpha = alphas[idx % len(alphas)]

                        self.saveState()
                        self.setFillAlpha(alpha)
                        self.setStrokeAlpha(alpha)

                        # Aplicar rotação em torno do centro da miniatura
                        centro_x = pos_x + tamanho / 2
                        centro_y = pos_y + tamanho / 2
                        self.translate(centro_x, centro_y)
                        self.rotate(rotacao)
                        self.translate(-tamanho / 2, -tamanho / 2)

                        self.drawImage(
                            logo_tjto_path,
                            0, 0,
                            width=tamanho, height=tamanho,
                            preserveAspectRatio=True,
                            mask='auto'
                        )
                        self.restoreState()
                        idx += 1

                # Logo central maior como destaque (mantém referência visual principal)
                self.saveState()
                self.setFillAlpha(0.10)
                logo_central = 6 * cm
                x_center = (page_width - logo_central) / 2
                y_center = (page_height - logo_central) / 2
                self.drawImage(
                    logo_tjto_path,
                    x_center, y_center,
                    width=logo_central, height=logo_central,
                    preserveAspectRatio=True,
                    mask='auto'
                )
                self.restoreState()

                self.restoreState()
            except Exception as e:
                logging.warning(f"⚠️ Não foi possível adicionar marca d'água TJTO: {e}")

        # CABEÇALHO
        self.saveState()

        # Linha superior colorida (cores JUS)
        self.setFillColor(JUS_VINHO)
        self.rect(0, page_height - 1.5*cm, page_width/3, 0.3*cm, fill=True, stroke=False)
        self.setFillColor(JUS_AZUL)
        self.rect(page_width/3, page_height - 1.5*cm, page_width/3, 0.3*cm, fill=True, stroke=False)
        self.setFillColor(JUS_DOURADO)
        self.rect(2*page_width/3, page_height - 1.5*cm, page_width/3, 0.3*cm, fill=True, stroke=False)

        # Logo JUS (esquerda)
        logo_jus_path = 'static/avatar.png'
        if os.path.exists(logo_jus_path):
            try:
                self.drawImage(logo_jus_path, 1.5*cm, page_height - 2.8*cm,
                              width=1.2*cm, height=1.2*cm,
                              preserveAspectRatio=True, mask='auto')
            except Exception as e:
                logging.warning(f"⚠️ Não foi possível carregar logo JUS: {e}")

        # Título do documento (centro)
        self.setFont('Helvetica-Bold', 11)
        self.setFillColor(JUS_AZUL)
        self.drawCentredString(page_width/2, page_height - 2.1*cm, "PODER JUDICIARIO DO ESTADO DO TOCANTINS")

        # Subtítulo
        self.setFont('Helvetica-Bold', 10)
        self.setFillColor(colors.grey)
        self.drawCentredString(page_width/2, page_height - 2.6*cm,
                              "Documento em Linguagem Simples")

        # Logo INOVASSOL (direita)
        logo_inovassol_path = 'static/inovassol.png'
        if os.path.exists(logo_inovassol_path):
            try:
                self.drawImage(logo_inovassol_path, page_width - 2.7*cm, page_height - 2.8*cm,
                              width=1.2*cm, height=1.2*cm,
                              preserveAspectRatio=True, mask='auto')
            except Exception as e:
                logging.warning(f"⚠️ Não foi possível carregar logo INOVASSOL: {e}")

        # Linha separadora
        self.setStrokeColor(colors.lightgrey)
        self.setLineWidth(0.5)
        self.line(1.5*cm, page_height - 3*cm, page_width - 1.5*cm, page_height - 3*cm)
        
        # RODAPÉ
        # Informações do documento
        self.setFont('Helvetica', 7)
        self.setFillColor(colors.grey)
        
        # Data de geração
        data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M")
        self.drawString(1.5*cm, 1.8*cm, f"Gerado em: {data_geracao}")
        
        # Modelo usado
        modelo = self.metadados.get('modelo', 'gemini-2.5-flash-lite')
        self.drawString(1.5*cm, 1.4*cm, f"Processado com: {modelo}")
        
        # Tipo de documento
        tipo_doc = self.metadados.get('tipo_documento', 'DOCUMENTO')
        self.drawString(1.5*cm, 1.0*cm, f"Tipo: {tipo_doc.upper()}")
        
        # Número da página (direita)
        self.setFont('Helvetica', 8)
        self.drawRightString(page_width - 1.5*cm, 1.5*cm, f"Página {page_num} de {page_count}")
        
        # Linha separadora rodapé
        self.setStrokeColor(colors.lightgrey)
        self.line(1.5*cm, 2.2*cm, page_width - 1.5*cm, 2.2*cm)
        
        # Informações institucionais no rodapé
        self.setFont('Helvetica-Bold', 7)
        self.setFillColor(colors.grey)
        self.drawCentredString(page_width/2, 1.1*cm, "Poder Judiciario do Estado do Tocantins")

        self.setFont('Helvetica', 6)
        sede_text = "SEDE: Palacio da Justica Rio Tocantins, Praca dos Girassois, s/no Centro | Palmas - Tocantins / CEP: 77015-007"
        self.drawCentredString(page_width/2, 0.8*cm, sede_text)

        contato_text = "Tel: (63) 3142-2200 / (63) 3142-2201 | Atendimento ao publico: 12:00 as 18:00 | www.tjto.jus.br"
        self.drawCentredString(page_width/2, 0.5*cm, contato_text)

        inovassol_text = "Desenvolvido pelo INOVASSOL - Centro de Inovacao do Poder Judiciario do Estado do Tocantins"
        self.drawCentredString(page_width/2, 0.2*cm, inovassol_text)

        # QR CODE DE VALIDAÇÃO E CÓDIGO (apenas na última página)
        doc_id = self.metadados.get('doc_id')
        validation_url = self.metadados.get('validation_url')

        if doc_id and page_num == page_count:
            # QR Code no canto inferior direito
            if QRCODE_AVAILABLE and validation_url:
                try:
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=4,
                        border=1,
                    )
                    qr.add_data(validation_url)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white")

                    # Converter para bytes para o ReportLab
                    qr_buffer = io.BytesIO()
                    qr_img.save(qr_buffer, format='PNG')
                    qr_buffer.seek(0)

                    qr_size = 2.0 * cm
                    qr_x = page_width - 3.5 * cm
                    qr_y = 2.4 * cm

                    self.drawImage(
                        ImageReader(qr_buffer),
                        qr_x, qr_y,
                        width=qr_size, height=qr_size,
                        preserveAspectRatio=True
                    )

                    # Texto "Validar" abaixo do QR
                    self.setFont('Helvetica', 5)
                    self.setFillColor(colors.grey)
                    self.drawCentredString(qr_x + qr_size/2, 2.25*cm, "Validar documento")
                except Exception as e:
                    logging.warning(f"⚠️ Erro ao gerar QR code: {e}")

            # Código de validação textual (ao lado esquerdo do QR)
            self.setFont('Helvetica', 6)
            self.setFillColor(colors.grey)

            hash_curto = self.metadados.get('hash_curto', '')
            self.drawString(1.5*cm, 2.7*cm, f"Codigo de validacao: {doc_id}")
            if hash_curto:
                self.drawString(1.5*cm, 2.45*cm, f"Hash: {hash_curto}")

        self.restoreState()

def criar_estilos():
    """Cria estilos customizados para o documento"""
    styles = getSampleStyleSheet()
    
    # Estilo para título principal
    styles.add(ParagraphStyle(
        name='TituloPrincipal',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=JUS_AZUL,
        spaceAfter=12,
        spaceBefore=6,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))
    
    # Estilo para seções
    styles.add(ParagraphStyle(
        name='Secao',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=JUS_VINHO,
        spaceAfter=6,
        spaceBefore=10,
        fontName='Helvetica-Bold',
        leftIndent=0
    ))

    # Estilo para corpo do texto
    styles.add(ParagraphStyle(
        name='CorpoTexto',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
        leftIndent=0,
        fontName='Helvetica'
    ))

    # Estilo para destaques
    styles.add(ParagraphStyle(
        name='Destaque',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=JUS_AZUL,
        fontName='Helvetica-Bold',
        spaceAfter=6,
        leftIndent=0
    ))
    
    # Estilo para observações
    styles.add(ParagraphStyle(
        name='Observacao',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.grey,
        fontName='Helvetica-Oblique',
        leftIndent=15,
        spaceAfter=8
    ))
    
    # Estilo para listas
    styles.add(ParagraphStyle(
        name='ItemLista',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        leftIndent=20,
        spaceAfter=4,
        fontName='Helvetica'
    ))
    
    return styles

def processar_markdown_para_pdf(texto, styles):
    """
    Converte texto Markdown em elementos PDF
    GARANTE que todo o texto seja processado
    """
    elementos = []
    
    # Dividir texto em linhas
    linhas = texto.split('\n')
    
    i = 0
    while i < len(linhas):
        linha = linhas[i].strip()
        
        # Pular linhas vazias (sem adicionar espaço extra - já controlado pelos estilos)
        if not linha:
            i += 1
            continue
        
        # Detectar emojis de seção e adicionar ícone visual
        emoji_map = {
            '📊': '[RESULTADO]',
            '📑': '[CONTEXTO]',
            '⚖️': '[DECISÃO]',
            '💰': '[VALORES]',
            '📅': '[PRAZOS]',
            '✅': '[OK]',
            '❌': '[X]',
            '⚠️': '[!]',
            '🟡': '[!]',
            '⚪': '[-]',
            '📋': '»',
            '💡': '[DICA]',
            '📚': '[GLOSSÁRIO]'
        }

        if any(emoji in linha for emoji in emoji_map.keys()):
            # Remover emojis da linha (converter para string vazia, não para ícones)
            texto_limpo = linha
            for emoji in emoji_map.keys():
                texto_limpo = texto_limpo.replace(emoji, '')
            texto_limpo = limpar_markdown(texto_limpo).strip()

            # Ignorar linhas vazias ou com apenas espaços
            if not texto_limpo:
                continue

            # Adicionar linha sem os emojis
            elementos.append(Paragraph(f'<b>{texto_limpo}</b>', styles['Secao']))
        
        # Detectar negrito (**texto**)
        elif '**' in linha:
            texto_limpo = processar_negrito(linha)
            elementos.append(Paragraph(texto_limpo, styles['Destaque']))
        
        # Detectar listas (começam com -)
        elif linha.startswith('-') or linha.startswith('•'):
            texto_limpo = limpar_markdown(linha.lstrip('-•').strip())
            # Ignorar bullets vazios (apenas o símbolo sem texto)
            if not texto_limpo:
                i += 1
                continue
            # Adicionar bullet point
            texto_com_bullet = f"• {texto_limpo}"
            elementos.append(Paragraph(texto_com_bullet, styles['ItemLista']))
        
        # Detectar linhas de separação (---)
        elif linha.startswith('---') or linha.startswith('═══'):
            elementos.append(Spacer(1, 0.5*cm))
            # Linha horizontal
            elementos.append(Table(
                [['']], 
                colWidths=[16*cm],
                style=TableStyle([
                    ('LINEABOVE', (0,0), (-1,-1), 1, colors.lightgrey),
                ])
            ))
            elementos.append(Spacer(1, 0.5*cm))
        
        # Detectar texto de observação (começa com *)
        elif linha.startswith('*'):
            texto_limpo = limpar_markdown(linha.lstrip('*').strip())
            elementos.append(Paragraph(texto_limpo, styles['Observacao']))
        
        # Texto normal
        else:
            texto_limpo = limpar_markdown(linha)
            elementos.append(Paragraph(texto_limpo, styles['CorpoTexto']))
        
        i += 1
    
    # CRÍTICO: Adicionar espaço final para garantir que todo conteúdo seja renderizado
    elementos.append(Spacer(1, 2*cm))
    
    logging.info(f"✅ Processados {len(elementos)} elementos do PDF")
    return elementos

def limpar_markdown(texto):
    """Remove marcações Markdown mas preserva HTML básico"""
    # Preservar tags HTML
    texto = texto.replace('<strong>', '<b>')
    texto = texto.replace('</strong>', '</b>')
    texto = texto.replace('<em>', '<i>')
    texto = texto.replace('</em>', '</i>')
    
    # Remover markdown restante
    texto = texto.replace('**', '')
    texto = texto.replace('__', '')
    texto = texto.replace('*', '')
    texto = texto.replace('_', '')
    
    return texto

def processar_negrito(texto):
    """Converte **texto** em <b>texto</b>"""
    import re
    texto = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', texto)
    return texto

def gerar_pdf_simplificado(texto, metadados=None, output_path='documento_simplificado.pdf'):
    """
    Gera PDF com todo o texto, sem truncamento
    
    Args:
        texto: Texto completo para incluir no PDF
        metadados: Dicionário com informações do documento
        output_path: Caminho do arquivo de saída
    """
    
    if metadados is None:
        metadados = {}
    
    logging.info(f"📄 Gerando PDF: {output_path}")
    logging.info(f"📏 Tamanho do texto: {len(texto)} caracteres")
    
    try:
        # Registrar fontes
        registrar_fontes()
        
        # Criar documento com margens adequadas para 16cm de conteúdo
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2.5*cm,  # (21cm - 16cm) / 2 = 2.5cm
            leftMargin=2.5*cm,   # (21cm - 16cm) / 2 = 2.5cm
            topMargin=3.5*cm,    # Espaço para cabeçalho
            bottomMargin=2.5*cm,  # Espaço para rodapé
            title='Documento em Linguagem Simples',
            author='INOVASSOL - TJTO'
        )
        
        # Criar estilos
        styles = criar_estilos()
        
        # Lista de elementos do PDF
        story = []

        # DETECTAR TIPO DE RESULTADO (do texto simplificado)
        resultado_texto = ""
        cor_resultado = JUS_AZUL

        if 'CONSEGUIU O QUE PEDIU' in texto and 'PARTE' not in texto:
            resultado_texto = "CONSEGUIU O QUE PEDIU"
            cor_resultado = colors.HexColor('#34a853')  # Verde
        elif 'CONSEGUIU PARTE DO QUE PEDIU' in texto:
            resultado_texto = "CONSEGUIU PARTE DO QUE PEDIU"
            cor_resultado = colors.HexColor('#fbbc04')  # Laranja
        elif 'NÃO CONSEGUIU O QUE PEDIU' in texto:
            resultado_texto = "NÃO CONSEGUIU O QUE PEDIU"
            cor_resultado = colors.HexColor('#ea4335')  # Vermelho
        elif 'PEDIDO NEGADO' in texto:
            resultado_texto = "PEDIDO NEGADO"
            cor_resultado = colors.HexColor('#9e9e9e')  # Cinza
        else:
            resultado_texto = "Entenda Aqui"
            cor_resultado = JUS_AZUL

        # CAIXA DE RESULTADO DESTACADA
        if resultado_texto:
            resultado_table = Table(
                [[Paragraph(
                    f'<b>{resultado_texto}</b>',
                    ParagraphStyle(
                        name='ResultadoStyle',
                        parent=styles['Normal'],
                        fontSize=16,
                        textColor=colors.white,
                        alignment=TA_CENTER,
                        fontName='Helvetica-Bold'
                    )
                )]],
                colWidths=[16*cm],
                style=TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), cor_resultado),
                    ('TOPPADDING', (0,0), (-1,-1), 15),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 15),
                    ('LEFTPADDING', (0,0), (-1,-1), 15),
                    ('RIGHTPADDING', (0,0), (-1,-1), 15),
                    ('ROUNDEDCORNERS', [8, 8, 8, 8]),
                ])
            )
            story.append(resultado_table)
            story.append(Spacer(1, 0.5*cm))

        # AVISO DE FINALIDADE INFORMATIVA - DESTAQUE PRINCIPAL
        aviso_informativo = Table(
            [[Paragraph(
                '<b>Aviso: Este documento tem finalidade exclusivamente informativa, sem valor oficial.</b>',
                styles['Observacao']
            )]],
            colWidths=[16*cm],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.Color(1, 0.97, 0.88, alpha=0.5)),
                ('BOX', (0,0), (-1,-1), 2, colors.HexColor('#f9a825')),
                ('TOPPADDING', (0,0), (-1,-1), 10),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                ('LEFTPADDING', (0,0), (-1,-1), 12),
                ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ])
        )
        story.append(aviso_informativo)
        story.append(Spacer(1, 0.4*cm))

        # AVISO INICIAL DESTACADO
        aviso_table = Table(
            [[Paragraph(
                '<b>AVISO IMPORTANTE</b><br/>'
                'Este documento foi simplificado usando Inteligencia Artificial. '
                'Para orientacao juridica completa, consulte um advogado ou a Defensoria Publica.',
                styles['Observacao']
            )]],
            colWidths=[16*cm],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.Color(1, 0.95, 0.8, alpha=0.3)),
                ('BOX', (0,0), (-1,-1), 1, JUS_DOURADO),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ])
        )
        story.append(aviso_table)
        story.append(Spacer(1, 0.5*cm))
        
        # Processar texto completo
        elementos_texto = processar_markdown_para_pdf(texto, styles)
        story.extend(elementos_texto)
        
        # AVISO DE FINALIDADE INFORMATIVA - REPETIDO AO FINAL
        story.append(Spacer(1, 1*cm))
        aviso_informativo_final = Table(
            [[Paragraph(
                '<b>Aviso: Este documento tem finalidade exclusivamente informativa, sem valor oficial.</b>',
                styles['Observacao']
            )]],
            colWidths=[16*cm],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.Color(1, 0.97, 0.88, alpha=0.5)),
                ('BOX', (0,0), (-1,-1), 2, colors.HexColor('#f9a825')),
                ('TOPPADDING', (0,0), (-1,-1), 10),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                ('LEFTPADDING', (0,0), (-1,-1), 12),
                ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ])
        )
        story.append(aviso_informativo_final)
        story.append(Spacer(1, 0.4*cm))

        # AVISO FINAL
        aviso_final = Table(
            [[Paragraph(
                '<b>LEMBRE-SE:</b><br/>'
                'Este documento nao substitui orientacao juridica profissional. '
                'Em caso de duvidas, procure um(a) advogado(a) ou a Defensoria Publica.',
                styles['Observacao']
            )]],
            colWidths=[16*cm],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.Color(0.9, 0.95, 1, alpha=0.3)),
                ('BOX', (0,0), (-1,-1), 1, JUS_AZUL),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ])
        )
        story.append(aviso_final)

        # SEÇÃO DE VALIDAÇÃO DO DOCUMENTO
        doc_id = metadados.get('doc_id')
        validation_url = metadados.get('validation_url')

        if doc_id:
            story.append(Spacer(1, 0.5*cm))

            hash_curto = metadados.get('hash_curto', '')
            texto_validacao = (
                f'<b>VALIDACAO DO DOCUMENTO</b><br/>'
                f'Codigo: <b>{doc_id}</b><br/>'
            )
            if hash_curto:
                texto_validacao += f'Hash de integridade: <b>{hash_curto}</b><br/>'
            if validation_url:
                texto_validacao += (
                    f'Para verificar a autenticidade deste documento, '
                    f'acesse o QR Code na ultima pagina ou visite o endereco de validacao.'
                )

            validacao_table = Table(
                [[Paragraph(texto_validacao, styles['Observacao'])]],
                colWidths=[16*cm],
                style=TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.Color(0.95, 0.95, 0.95, alpha=0.5)),
                    ('BOX', (0,0), (-1,-1), 1, colors.grey),
                    ('TOPPADDING', (0,0), (-1,-1), 8),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                    ('LEFTPADDING', (0,0), (-1,-1), 10),
                    ('RIGHTPADDING', (0,0), (-1,-1), 10),
                ])
            )
            story.append(validacao_table)
        
        # Construir PDF com canvas customizado
        doc.build(
            story,
            canvasmaker=lambda *args, **kwargs: HeaderFooterCanvas(
                *args, 
                metadados=metadados,
                **kwargs
            )
        )
        
        logging.info(f"✅ PDF gerado com sucesso: {output_path}")
        logging.info(f"📦 Tamanho do arquivo: {os.path.getsize(output_path) / 1024:.1f} KB")
        
        return output_path
        
    except Exception as e:
        logging.error(f"❌ Erro ao gerar PDF: {e}", exc_info=True)
        raise

# Teste standalone
if __name__ == "__main__":
    texto_teste = """
📊 CONSEGUIU PARTE DO QUE PEDIU

**Em uma frase simples:** O juiz decidiu que a empresa GOL deve pagar uma parte do que vocês pediram.

---

📑 **O QUE ESTÁ ACONTECENDO**

Thiago José de Arruda Oliveira e Kamilla Sousa Prado entraram com um processo contra a GOL Linhas Aéreas S.A. Eles compraram passagens aéreas para um aniversário, mas a GOL alterou os horários dos voos várias vezes.

---

⚖️ **A DECISÃO DO JUIZ**

Sobre os danos materiais: O juiz decidiu que a GOL deve pagar R$ 1.427,64 para cobrir os prejuízos que vocês tiveram.

Sobre os danos morais: O juiz decidiu que a GOL deve pagar um total de R$ 6.000,00 para vocês, sendo R$ 3.000,00 para cada um.

---

💰 **VALORES E O QUE VOCÊ PRECISA FAZER**

**Valores mencionados:**

✅ **O QUE VOCÊ VAI GANHAR:**

📋 **Danos Materiais: R$ 1.427,64**
- Reembolso de passagens aéreas: R$ 1.362,14
- Reembolso de alimentação: R$ 65,50

📋 **Danos Morais: R$ 6.000,00**
- Para Thiago José de Arruda Oliveira: R$ 3.000,00
- Para Kamilla Sousa Prado: R$ 3.000,00

**Sobre custas e honorários:**

Você NÃO vai pagar custas e honorários porque tem justiça gratuita.

**Próximos passos:**

Fale com advogado(a) ou defensoria pública.

---

*💡 Dica: Este documento não substitui a orientação jurídica. Se precisar, busque ajuda com um advogado ou uma advogada ou com a Defensoria Pública.*
    """
    
    metadados_teste = {
        'modelo': 'gemini-2.5-flash-lite',
        'tipo_documento': 'SENTENCA',
        'confianca': 'ALTA'
    }
    
    gerar_pdf_simplificado(texto_teste, metadados_teste, 'teste_completo.pdf')
    print("✅ PDF de teste gerado: teste_completo.pdf")
