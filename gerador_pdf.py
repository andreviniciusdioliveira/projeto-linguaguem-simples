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
import os
import logging
from datetime import datetime

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
        """Desenha cabeçalho e rodapé em cada página"""
        page_width, page_height = A4

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
        self.setFont('Helvetica-Bold', 12)
        self.setFillColor(JUS_AZUL)
        self.drawCentredString(page_width/2, page_height - 2.2*cm, "Documento em Linguagem Simples")

        # Subtítulo
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.grey)
        self.drawCentredString(page_width/2, page_height - 2.6*cm,
                              "Desenvolvido pelo INOVASSOL - Centro de Inovação do TJTO")

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
        
        # Informações INOVASSOL no final
        self.setFont('Helvetica', 6)
        self.setFillColor(colors.grey)
        info_text = "SEDE: Palacio da Justica Rio Tocantins, Praca dos Girassois, s/no Centro | Palmas - Tocantins / CEP: 77015-007"
        self.drawCentredString(page_width/2, 0.7*cm, info_text)
        contato_text = "Tel: (63) 3142-2200 / (63) 3142-2201 | Atendimento: 12:00 as 18:00 | www.tjto.jus.br"
        self.drawCentredString(page_width/2, 0.3*cm, contato_text)
        
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
        spaceAfter=10,
        spaceBefore=12,
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
        spaceAfter=8,
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
        spaceAfter=6
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
        
        # Pular linhas vazias (mas adicionar espaço)
        if not linha:
            elementos.append(Spacer(1, 0.2*cm))
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
            elementos.append(Spacer(1, 0.3*cm))
        
        # Detectar negrito (**texto**)
        elif '**' in linha:
            texto_limpo = processar_negrito(linha)
            elementos.append(Paragraph(texto_limpo, styles['Destaque']))
        
        # Detectar listas (começam com -)
        elif linha.startswith('-') or linha.startswith('•'):
            texto_limpo = limpar_markdown(linha.lstrip('-•').strip())
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
        
        # Criar documento com margens adequadas
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=1.5*cm,
            leftMargin=1.5*cm,
            topMargin=3.5*cm,  # Espaço para cabeçalho
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
            story.append(Spacer(1, 0.8*cm))

        # AVISO INICIAL DESTACADO
        aviso_table = Table(
            [[Paragraph(
                '<b>AVISO IMPORTANTE</b><br/>'
                'Este documento foi simplificado usando Inteligência Artificial. '
                'Para orientação jurídica adequada, consulte um(a) advogado(a) ou a Defensoria Pública.',
                styles['Observacao']
            )]],
            colWidths=[16*cm],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.Color(1, 0.95, 0.8, alpha=0.3)),
                ('BOX', (0,0), (-1,-1), 1, JUS_DOURADO),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ])
        )
        story.append(aviso_table)
        story.append(Spacer(1, 0.8*cm))
        
        # Processar texto completo
        elementos_texto = processar_markdown_para_pdf(texto, styles)
        story.extend(elementos_texto)
        
        # AVISO FINAL
        story.append(Spacer(1, 1*cm))
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
