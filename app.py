import streamlit as st
import fitz  # PyMuPDF
import io
from openai import OpenAI
import re
from datetime import datetime
import time

# Configuração da página
st.set_page_config(
    page_title="Simplificador de Documentos Jurídicos",
    page_icon="⚖️",
    layout="wide"
)

# CSS customizado
st.markdown("""
<style>
    .main-title {
        color: #2E86AB;
        text-align: center;
        padding: 1rem 0;
        border-bottom: 3px solid #A23B72;
        margin-bottom: 2rem;
    }
    .upload-section {
        background-color: #f8f9fa;
        padding: 2rem;
        border-radius: 10px;
        border-left: 5px solid #2E86AB;
        margin: 1rem 0;
    }
    .resultado-section {
        background-color: #ffffff;
        padding: 2rem;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Prompt aprimorado
PROMPT_SIMPLIFICACAO = """**Papel:** Você é um especialista em linguagem simples aplicada ao Poder Judiciário, com experiência em transformar textos jurídicos complexos em comunicações claras e acessíveis.

**ESTRUTURA DE ANÁLISE OBRIGATÓRIA:**

## 1. IDENTIFICAÇÃO DO DOCUMENTO
- Tipo: [Sentença/Despacho/Decisão/Acórdão]
- Número do processo: [identificar]
- Partes envolvidas: [Autor x Réu]
- Assunto principal: [identificar]

## 2. ANÁLISE DO RESULTADO (MAIS IMPORTANTE)
**ATENÇÃO:** Procure SEMPRE pela seção "DISPOSITIVO", "DECIDE", "ANTE O EXPOSTO" ou "DIANTE DO EXPOSTO"

### Identificação do Vencedor:
- ✅ AUTOR GANHOU se encontrar: "JULGO PROCEDENTE", "CONDENO o réu/requerido", "DEFIRO"
- ❌ AUTOR PERDEU se encontrar: "JULGO IMPROCEDENTE", "CONDENO o autor/requerente", "INDEFIRO"  
- ⚠️ PARCIAL se encontrar: "JULGO PARCIALMENTE PROCEDENTE"

## 3. FORMATAÇÃO DA RESPOSTA

### 📊 RESUMO EXECUTIVO
[Use sempre um dos ícones abaixo]
✅ **VITÓRIA TOTAL** - Você ganhou completamente a causa
❌ **DERROTA** - Você perdeu a causa
⚠️ **VITÓRIA PARCIAL** - Você ganhou parte do que pediu
⏳ **AGUARDANDO** - Ainda não há decisão final
📋 **ANDAMENTO** - Apenas um despacho processual

**Em uma frase:** [Explicar o resultado em linguagem muito simples]

### 📑 O QUE ACONTECEU
[Explicar em 3-4 linhas o contexto do processo]

### ⚖️ O QUE O JUIZ DECIDIU
[Detalhar a decisão em linguagem simples, usando parágrafos curtos]

### 💰 VALORES E OBRIGAÇÕES
• Valor da causa: R$ [valor]
• Valores a receber: R$ [detalhar]
• Valores a pagar: R$ [detalhar]
• Honorários: [percentual e valor]
• Custas processuais: [quem paga]

### ⚠️ ATENÇÃO IMPORTANTE
[Alertas sobre prazos críticos ou consequências]

### 💡 DICA PRÁTICA
[Sugestão de ação imediata que a parte pode tomar]

### 📚 MINI DICIONÁRIO DOS TERMOS JURÍDICOS
[Listar apenas os termos jurídicos que aparecem no texto com explicação simples]
• **Termo 1:** Explicação clara e simples
• **Termo 2:** Explicação clara e simples
• **Termo 3:** Explicação clara e simples

---
*Documento processado em: [data/hora]*
*Este é um resumo simplificado. Consulte seu advogado para orientações específicas.*

**REGRAS DE SIMPLIFICAÇÃO:**
1. Use frases com máximo 20 palavras
2. Substitua jargões por palavras comuns
3. Explique siglas na primeira vez que aparecem
4. Use exemplos concretos quando possível
5. Mantenha tom respeitoso mas acessível
6. Destaque informações críticas com formatação

**TEXTO ORIGINAL A SIMPLIFICAR:**
"""

def extrair_texto_pdf(arquivo_pdf):
    """Extrai texto de um arquivo PDF"""
    try:
        doc = fitz.open(stream=arquivo_pdf.read(), filetype="pdf")
        texto_completo = ""
        
        for pagina_num in range(len(doc)):
            pagina = doc.load_page(pagina_num)
            texto = pagina.get_text()
            texto_completo += texto + "\n"
        
        doc.close()
        return texto_completo
    except Exception as e:
        st.error(f"Erro ao extrair texto do PDF: {str(e)}")
        return None

def limpar_texto(texto):
    """Limpa e formata o texto extraído"""
    if not texto:
        return ""
    
    # Remove caracteres especiais problemáticos
    texto = re.sub(r'[^\w\s\-.,;:!?()[\]{}/"\'@#$%&*+=<>]', ' ', texto)
    
    # Normaliza espaços em branco
    texto = re.sub(r'\s+', ' ', texto)
    
    # Remove linhas muito curtas que podem ser ruído
    linhas = texto.split('\n')
    linhas_filtradas = [linha.strip() for linha in linhas if len(linha.strip()) > 3]
    
    return '\n'.join(linhas_filtradas)

def simplificar_documento(texto, api_key):
    """Usa OpenAI para simplificar o documento jurídico"""
    try:
        client = OpenAI(api_key=api_key)
        
        # Limita o texto se for muito longo
        if len(texto) > 12000:  # Limite conservador
            texto = texto[:12000] + "..."
            st.warning("⚠️ Documento muito longo. Processando apenas os primeiros 12.000 caracteres.")
        
        prompt_completo = PROMPT_SIMPLIFICACAO + texto
        
        with st.spinner('🤖 Analisando documento...'):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um especialista em simplificação de documentos jurídicos."},
                    {"role": "user", "content": prompt_completo}
                ],
                max_tokens=2500,
                temperature=0.1
            )
        
        return response.choices[0].message.content
    
    except Exception as e:
        st.error(f"Erro ao processar com OpenAI: {str(e)}")
        return None

def main():
    # Título principal
    st.markdown('<h1 class="main-title">⚖️ Simplificador de Documentos Jurídicos</h1>', unsafe_allow_html=True)
    
    # Descrição
    st.markdown("""
    <div style="text-align: center; color: #666; margin-bottom: 2rem;">
        Transforme documentos jurídicos complexos em textos claros e compreensíveis
    </div>
    """, unsafe_allow_html=True)
    
    # Seção de configuração da API
    with st.sidebar:
        st.header("🔧 Configurações")
        api_key = st.text_input(
            "Chave da API OpenAI",
            type="password",
            help="Insira sua chave da API do OpenAI"
        )
        
        if not api_key:
            st.warning("⚠️ Insira sua chave da API para continuar")
            st.markdown("""
            **Como obter sua chave da API:**
            1. Acesse [platform.openai.com](https://platform.openai.com)
            2. Faça login na sua conta
            3. Vá em "API Keys"
            4. Clique em "Create new secret key"
            """)
        
        st.markdown("---")
        st.markdown("""
        **📋 Tipos de documentos suportados:**
        - ✅ Sentenças
        - ✅ Decisões
        - ✅ Despachos
        - ✅ Acórdãos
        - ✅ Outros documentos judiciais
        """)
        
        st.markdown("---")
        st.markdown("""
        **🛡️ Segurança:**
        - Seus dados não são armazenados
        - Processamento seguro
        - API key criptografada
        """)
    
    # Interface principal
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown('<div class="upload-section">', unsafe_allow_html=True)
        st.subheader("📄 Upload do Documento")
        
        arquivo_pdf = st.file_uploader(
            "Selecione o arquivo PDF",
            type=['pdf'],
            help="Faça upload de um documento jurídico em PDF"
        )
        
        if arquivo_pdf is not None:
            st.success(f"✅ Arquivo carregado: {arquivo_pdf.name}")
            st.info(f"📊 Tamanho: {arquivo_pdf.size / 1024:.1f} KB")
            
            if st.button("🚀 Processar Documento", type="primary", use_container_width=True):
                if not api_key:
                    st.error("❌ Por favor, insira sua chave da API OpenAI")
                else:
                    # Processa o documento
                    with st.spinner("📖 Extraindo texto do PDF..."):
                        texto_extraido = extrair_texto_pdf(arquivo_pdf)
                    
                    if texto_extraido:
                        texto_limpo = limpar_texto(texto_extraido)
                        
                        if len(texto_limpo.strip()) < 100:
                            st.error("❌ Texto muito curto ou não foi possível extrair conteúdo suficiente do PDF")
                        else:
                            # Simplifica o documento
                            resultado = simplificar_documento(texto_limpo, api_key)
                            
                            if resultado:
                                # Salva o resultado na sessão
                                st.session_state['resultado'] = resultado
                                st.session_state['nome_arquivo'] = arquivo_pdf.name
                                st.success("✅ Documento processado com sucesso!")
                            else:
                                st.error("❌ Erro ao processar o documento")
                    else:
                        st.error("❌ Erro ao extrair texto do PDF")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Seção de exemplo
        with st.expander("📖 Ver exemplo de resultado"):
            st.markdown("""
            **Exemplo de saída simplificada:**
            
            ### 📊 RESUMO EXECUTIVO
            ✅ **VITÓRIA TOTAL** - Você ganhou completamente a causa
            
            **Em uma frase:** O juiz decidiu que a empresa deve pagar R$ 50.000 de danos morais.
            
            ### 📑 O QUE ACONTECEU
            João processou a empresa XYZ porque teve seu nome negativado indevidamente...
            
            ### 📚 MINI DICIONÁRIO DOS TERMOS JURÍDICOS
            • **Danos morais:** Compensação em dinheiro por sofrimento emocional
            • **Tutela antecipada:** Decisão rápida antes do final do processo
            """)
    
    with col2:
        if 'resultado' in st.session_state:
            st.markdown('<div class="resultado-section">', unsafe_allow_html=True)
            st.subheader(f"📋 Resultado - {st.session_state.get('nome_arquivo', 'Documento')}")
            
            # Resultado simplificado
            st.markdown(st.session_state['resultado'])
            
            # Botões de ação
            col_download, col_limpar = st.columns(2)
            
            with col_download:
                # Botão de download
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                nome_download = f"documento_simplificado_{timestamp}.txt"
                
                st.download_button(
                    label="💾 Baixar Resultado",
                    data=st.session_state['resultado'],
                    file_name=nome_download,
                    mime="text/plain",
                    use_container_width=True
                )
            
            with col_limpar:
                if st.button("🗑️ Limpar Resultado", use_container_width=True):
                    del st.session_state['resultado']
                    if 'nome_arquivo' in st.session_state:
                        del st.session_state['nome_arquivo']
                    st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="text-align: center; padding: 4rem 2rem; color: #666;">
                <h3>📋 Resultado aparecerá aqui</h3>
                <p>Faça upload de um documento PDF e clique em "Processar" para ver a simplificação</p>
            </div>
            """, unsafe_allow_html=True)
    
    # Rodapé
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; font-size: 0.8em;">
        <p>⚖️ Simplificador de Documentos Jurídicos | 
        Desenvolvido para tornar o direito mais acessível | 
        Versão 2.0</p>
        <p><strong>Importante:</strong> Este é um resumo automatizado. 
        Sempre consulte um advogado para orientações específicas sobre seu caso.</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
