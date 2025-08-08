<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Linguagem Simples Jurídica - Powered by Gemini AI</title>
    <meta name="description" content="Transforme documentos jurídicos complexos em linguagem simples e acessível usando inteligência artificial">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='50%' x='50%' text-anchor='middle' font-size='80'>⚖️</text></svg>">
    
    <style>
        :root {
            --primary: #1a73e8;
            --primary-dark: #1557b0;
            --secondary: #34a853;
            --danger: #ea4335;
            --warning: #fbbc04;
            --dark: #202124;
            --light: #f8f9fa;
            --border: #dadce0;
            --shadow: rgba(0,0,0,0.1);
            --text: #202124;
            --text-muted: #5f6368;
            --success-bg: #e6f4ea;
            --error-bg: #fce8e6;
            --warning-bg: #fef7e0;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Google Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            color: var(--text);
            line-height: 1.6;
            transition: all 0.3s ease;
        }

        /* Dark mode */
        body.dark-mode {
            --primary: #4da3ff;
            --primary-dark: #66b3ff;
            --light: #1a1a1a;
            --text: #e8eaed;
            --text-muted: #9aa0a6;
            --border: #3c4043;
            --shadow: rgba(255,255,255,0.1);
            --success-bg: #1e3a2e;
            --error-bg: #3c1f1f;
            --warning-bg: #3a3319;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Header aprimorado */
        .header {
            text-align: center;
            margin-bottom: 3rem;
            animation: fadeInDown 0.8s ease;
        }

        .header h1 {
            font-size: 2.5rem;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
            font-weight: 700;
        }

        .header p {
            color: var(--text-muted);
            font-size: 1.1rem;
        }

        /* Cards com glassmorphism */
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            box-shadow: 0 8px 32px var(--shadow);
            padding: 2rem;
            margin-bottom: 2rem;
            transition: all 0.3s ease;
            animation: fadeInUp 0.8s ease;
            border: 1px solid var(--border);
        }

        body.dark-mode .card {
            background: rgba(42, 42, 42, 0.95);
            border-color: var(--border);
        }

        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 48px var(--shadow);
        }

        /* Progress Steps */
        .progress-steps {
            display: flex;
            justify-content: space-between;
            margin-bottom: 3rem;
            position: relative;
        }

        .progress-steps::before {
            content: '';
            position: absolute;
            top: 20px;
            left: 0;
            width: 100%;
            height: 2px;
            background: var(--border);
            z-index: -1;
        }

        .step {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
            position: relative;
        }

        .step-circle {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: white;
            border: 2px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            transition: all 0.3s ease;
            z-index: 1;
        }

        .step.active .step-circle {
            background: var(--primary);
            color: white;
            border-color: var(--primary);
            transform: scale(1.1);
        }

        .step.completed .step-circle {
            background: var(--secondary);
            color: white;
            border-color: var(--secondary);
        }

        .step-label {
            margin-top: 0.5rem;
            font-size: 0.875rem;
            color: var(--text-muted);
            text-align: center;
        }

        /* File upload area melhorada */
        #drop-area {
            border: 2px dashed var(--primary);
            border-radius: 12px;
            padding: 3rem 2rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            background: linear-gradient(135deg, rgba(26, 115, 232, 0.05) 0%, rgba(26, 115, 232, 0.1) 100%);
            position: relative;
            overflow: hidden;
        }

        #drop-area::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, var(--primary) 0%, transparent 70%);
            opacity: 0;
            transition: opacity 0.3s ease;
            pointer-events: none;
        }

        #drop-area:hover::before,
        #drop-area.hover::before {
            opacity: 0.1;
        }

        #drop-area:hover,
        #drop-area.hover {
            border-color: var(--primary-dark);
            transform: scale(1.02);
        }

        /* Botões melhorados */
        .button {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: white;
            border: none;
            padding: 0.75rem 2rem;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            text-decoration: none;
            box-shadow: 0 4px 12px rgba(26, 115, 232, 0.3);
            position: relative;
            overflow: hidden;
        }

        .button::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.3);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }

        .button:hover::before {
            width: 300px;
            height: 300px;
        }

        .button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(26, 115, 232, 0.4);
        }

        /* Resultado com animações */
        .result-card {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 8px var(--shadow);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        body.dark-mode .result-card {
            background: #333;
        }

        .result-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--primary);
        }

        .result-success::before {
            background: var(--secondary);
        }

        .result-error::before {
            background: var(--danger);
        }

        .result-warning::before {
            background: var(--warning);
        }

        /* Animação de digitação */
        @keyframes typing {
            from { width: 0; }
            to { width: 100%; }
        }

        .typing-effect {
            overflow: hidden;
            white-space: nowrap;
            animation: typing 2s steps(40, end);
        }

        /* Modal de feedback */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            animation: fadeIn 0.3s ease;
        }

        .modal.show {
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .modal-content {
            background: white;
            border-radius: 16px;
            padding: 2rem;
            max-width: 500px;
            width: 90%;
            animation: slideUp 0.3s ease;
        }

        body.dark-mode .modal-content {
            background: #2a2a2a;
        }

        /* Rating stars */
        .rating {
            display: flex;
            gap: 0.5rem;
            font-size: 2rem;
            justify-content: center;
            margin: 1rem 0;
        }

        .star {
            cursor: pointer;
            transition: all 0.2s ease;
            color: #ddd;
        }

        .star:hover,
        .star.active {
            color: #ffd700;
            transform: scale(1.1);
        }

        /* Estatísticas em tempo real */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .stat-box {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: white;
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
            transition: all 0.3s ease;
        }

        .stat-box:hover {
            transform: scale(1.05);
        }

        .stat-value {
            font-size: 2rem;
            font-weight: bold;
            display: block;
        }

        .stat-label {
            font-size: 0.875rem;
            opacity: 0.9;
        }

        /* Loading avançado */
        .loading-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.7);
            z-index: 9999;
            align-items: center;
            justify-content: center;
        }

        .loading-overlay.show {
            display: flex;
        }

        .loading-content {
            background: white;
            border-radius: 16px;
            padding: 2rem;
            text-align: center;
            max-width: 400px;
        }

        body.dark-mode .loading-content {
            background: #2a2a2a;
        }

        .loading-spinner {
            width: 60px;
            height: 60px;
            margin: 0 auto 1rem;
            border: 4px solid var(--border);
            border-top: 4px solid var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loading-text {
            color: var(--text);
            margin-bottom: 1rem;
        }

        .loading-progress {
            width: 100%;
            height: 8px;
            background: var(--border);
            border-radius: 4px;
            overflow: hidden;
        }

        .loading-progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--primary) 0%, var(--primary-dark) 100%);
            width: 0%;
            transition: width 0.3s ease;
            animation: shimmer 1.5s infinite;
        }

        @keyframes shimmer {
            0% { opacity: 0.8; }
            50% { opacity: 1; }
            100% { opacity: 0.8; }
        }

        /* Tooltips */
        .tooltip {
            position: relative;
            display: inline-block;
        }

        .tooltip .tooltiptext {
            visibility: hidden;
            width: 200px;
            background: var(--dark);
            color: white;
            text-align: center;
            border-radius: 6px;
            padding: 0.5rem;
            position: absolute;
            z-index: 1;
            bottom: 125%;
            left: 50%;
            margin-left: -100px;
            opacity: 0;
            transition: opacity 0.3s;
            font-size: 0.875rem;
        }

        .tooltip:hover .tooltiptext {
            visibility: visible;
            opacity: 1;
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeInDown {
            from {
                opacity: 0;
                transform: translateY(-20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes slideUp {
            from {
                transform: translateY(50px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }

        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }

        /* Responsive */
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }

            .header h1 {
                font-size: 1.8rem;
            }

            .progress-steps {
                flex-direction: column;
                gap: 1rem;
            }

            .progress-steps::before {
                display: none;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Toast notifications melhoradas */
        .toast {
            position: fixed;
            bottom: -100px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--dark);
            color: white;
            padding: 1rem 2rem;
            border-radius: 8px;
            box-shadow: 0 8px 32px var(--shadow);
            transition: bottom 0.3s ease;
            z-index: 10000;
            max-width: 90%;
            text-align: center;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .toast.show {
            bottom: 2rem;
        }

        .toast.success {
            background: var(--secondary);
        }

        .toast.error {
            background: var(--danger);
        }

        .toast.warning {
            background: var(--warning);
            color: var(--dark);
        }

        /* Switch de tema aprimorado */
        .theme-switch {
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 100;
        }

        .switch {
            position: relative;
            display: inline-block;
            width: 60px;
            height: 30px;
        }

        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            transition: .4s;
            border-radius: 30px;
        }

        .slider:before {
            position: absolute;
            content: "☀️";
            height: 22px;
            width: 22px;
            left: 4px;
            bottom: 4px;
            background: white;
            transition: .4s;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }

        input:checked + .slider {
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
        }

        input:checked + .slider:before {
            content: "🌙";
            transform: translateX(30px);
        }
    </style>
</head>
<body>
    <!-- Theme Switch -->
    <div class="theme-switch">
        <label class="switch">
            <input type="checkbox" id="themeSwitch">
            <span class="slider"></span>
        </label>
    </div>

    <!-- Loading Overlay -->
    <div class="loading-overlay" id="loadingOverlay">
        <div class="loading-content">
            <div class="loading-spinner"></div>
            <div class="loading-text" id="loadingText">Processando com IA...</div>
            <div class="loading-progress">
                <div class="loading-progress-bar" id="loadingProgress"></div>
            </div>
            <small id="modelInfo" style="color: var(--text-muted); margin-top: 0.5rem;"></small>
        </div>
    </div>

    <div class="container">
        <!-- Header -->
        <header class="header">
            <div style="display: flex; align-items: center; justify-content: center; gap: 2rem; margin-bottom: 2rem;">
                <img src="/static/logoinovassol.png" alt="INOVASSOL - Centro de Inovação" 
                     style="height: 80px; width: auto; filter: drop-shadow(0 4px 8px rgba(0,0,0,0.1));">
                <div style="text-align: left;">
                    <h1 style="margin-bottom: 0.25rem;">⚖️ Linguagem Simples Jurídica</h1>
                    <p style="margin: 0;">Transforme documentos complexos em linguagem clara com IA</p>
                </div>
            </div>
            <div style="text-align: center;">
                <p style="color: var(--text-muted); font-size: 1rem; margin-bottom: 0.5rem;">
                    <strong>Desenvolvido pelo INOVASSOL - Centro de Inovação</strong>
                </p>
                <p style="color: var(--text-muted); font-size: 0.9rem; max-width: 600px; margin: 0 auto; line-height: 1.5;">
                    ⚠️ Queremos facilitar sua vida com informações mais simples, mas só um advogado ou defensor público pode te dar uma orientação certa para o seu caso. Sempre que precisar, procure esse apoio!
                </p>
            </div>
        </header>

        <!-- Progress Steps -->
        <div class="progress-steps">
            <div class="step active" id="step1">
                <div class="step-circle">1</div>
                <div class="step-label">Enviar Documento</div>
            </div>
            <div class="step" id="step2">
                <div class="step-circle">2</div>
                <div class="step-label">Processar com IA</div>
            </div>
            <div class="step" id="step3">
                <div class="step-circle">3</div>
                <div class="step-label">Resultado Simplificado</div>
            </div>
        </div>

        <!-- Statistics -->
        <div class="stats-grid" id="statsGrid" style="display: none;">
            <div class="stat-box">
                <span class="stat-value" id="totalProcessed">0</span>
                <span class="stat-label">Documentos Processados</span>
            </div>
            <div class="stat-box">
                <span class="stat-value" id="avgReduction">0%</span>
                <span class="stat-label">Redução Média</span>
            </div>
            <div class="stat-box">
                <span class="stat-value" id="currentModel">-</span>
                <span class="stat-label">Modelo Atual</span>
            </div>
        </div>

        <!-- Upload Card -->
        <div class="card">
            <h2 style="color: var(--primary); margin-bottom: 1.5rem;">📤 Enviar Documento PDF</h2>
            <div id="drop-area">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📁</div>
                <p style="font-size: 1.1rem; color: var(--text); margin-bottom: 1rem;">
                    Arraste seu PDF aqui ou clique para selecionar
                </p>
                <input type="file" id="fileInput" accept=".pdf" style="display: none;">
                <button class="button" onclick="document.getElementById('fileInput').click()">
                    <span>📎</span> Escolher Arquivo
                </button>
                <p style="font-size: 0.875rem; color: var(--text-muted); margin-top: 1rem;">
                    Máximo: 10MB | Formato: PDF
                </p>
            </div>
            <div id="fileInfo" style="display: none; margin-top: 1rem; padding: 1rem; background: var(--success-bg); border-radius: 8px;">
                <p style="margin: 0; display: flex; justify-content: space-between; align-items: center;">
                    <span id="fileName" style="font-weight: 600;"></span>
                    <span id="fileSize" style="font-size: 0.875rem; color: var(--text-muted);"></span>
                </p>
            </div>
        </div>

        <!-- Manual Text Card -->
        <div class="card">
            <h2 style="color: var(--primary); margin-bottom: 1.5rem;">✍️ Ou Cole o Texto</h2>
            <textarea id="manualText" placeholder="Cole aqui o texto jurídico que deseja simplificar..." 
                style="width: 100%; min-height: 150px; padding: 1rem; border: 2px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 1rem; resize: vertical; transition: border-color 0.3s;"></textarea>
            <div style="display: flex; gap: 1rem; margin-top: 1rem;">
                <button class="button" onclick="processManualText()">
                    <span>🔄</span> Simplificar Texto
                </button>
                <button class="button" style="background: var(--danger);" onclick="clearAll()">
                    <span>🗑️</span> Limpar Tudo
                </button>
                <div class="tooltip" style="margin-left: auto;">
                    <button class="button" style="background: var(--warning); color: var(--dark);" onclick="loadExample()">
                        <span>📝</span> Exemplo
                    </button>
                    <span class="tooltiptext">Carregar um exemplo de texto jurídico</span>
                </div>
            </div>
        </div>

        <!-- Result Card -->
        <div id="resultSection" style="display: none;">
            <div class="card">
                <h2 style="color: var(--primary); margin-bottom: 1.5rem;">✅ Resultado Simplificado</h2>
                
                <!-- Result Analysis -->
                <div id="resultAnalysis" style="margin-bottom: 1.5rem;">
                    <!-- Filled dynamically -->
                </div>
                
                <!-- Simplified Text -->
                <div id="simplifiedText" style="background: var(--light); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; max-height: 500px; overflow-y: auto;">
                    <!-- Filled dynamically -->
                </div>
                
                <!-- Action Buttons -->
                <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                    <a href="#" class="button" id="downloadBtn" style="display: none;">
                        <span>📥</span> Baixar PDF
                    </a>
                    <button class="button" onclick="copyText()">
                        <span>📋</span> Copiar Texto
                    </button>
                    <button class="button" onclick="speakText()" id="speakBtn">
                        <span>🔊</span> Ler em Voz Alta
                    </button>
                    <button class="button" style="background: var(--secondary);" onclick="showFeedbackModal()">
                        <span>⭐</span> Avaliar
                    </button>
                </div>
            </div>
        </div>

        <!-- Feedback Modal -->
        <div id="feedbackModal" class="modal">
            <div class="modal-content">
                <h2 style="color: var(--primary); margin-bottom: 1rem;">Como foi sua experiência?</h2>
                <div class="rating" id="rating">
                    <span class="star" data-rating="1">⭐</span>
                    <span class="star" data-rating="2">⭐</span>
                    <span class="star" data-rating="3">⭐</span>
                    <span class="star" data-rating="4">⭐</span>
                    <span class="star" data-rating="5">⭐</span>
                </div>
                <textarea id="feedbackComment" placeholder="Deixe um comentário (opcional)" 
                    style="width: 100%; min-height: 100px; padding: 0.75rem; border: 2px solid var(--border); border-radius: 8px; margin: 1rem 0; font-family: inherit;"></textarea>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button class="button" style="background: var(--text-muted);" onclick="closeFeedbackModal()">
                        Cancelar
                    </button>
                    <button class="button" onclick="submitFeedback()">
                        Enviar Avaliação
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <script>
        // Configurações
        const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
        let isProcessing = false;
        let currentResultHash = '';
        let selectedRating = 0;
        let processedCount = 0;
        let totalReduction = 0;
        let currentModel = '-';

        // Theme
        const themeSwitch = document.getElementById('themeSwitch');
        const body = document.body;

        // Check saved theme
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            body.classList.add('dark-mode');
            themeSwitch.checked = true;
        }

        themeSwitch.addEventListener('change', () => {
            if (themeSwitch.checked) {
                body.classList.add('dark-mode');
                localStorage.setItem('theme', 'dark');
            } else {
                body.classList.remove('dark-mode');
                localStorage.setItem('theme', 'light');
            }
        });

        // Initialize stats from localStorage
        function initializeStats() {
            processedCount = parseInt(localStorage.getItem('processedCount') || '0');
            totalReduction = parseFloat(localStorage.getItem('totalReduction') || '0');
            updateStatsDisplay();
        }

        function updateStatsDisplay() {
            document.getElementById('totalProcessed').textContent = processedCount;
            const avgReduction = processedCount > 0 ? (totalReduction / processedCount).toFixed(1) : 0;
            document.getElementById('avgReduction').textContent = avgReduction + '%';
            document.getElementById('currentModel').textContent = currentModel;
            
            if (processedCount > 0) {
                document.getElementById('statsGrid').style.display = 'grid';
            }
        }

        // Progress steps
        function updateProgressSteps(step) {
            document.querySelectorAll('.step').forEach(s => {
                s.classList.remove('active', 'completed');
            });
            
            for (let i = 1; i <= step; i++) {
                const stepEl = document.getElementById(`step${i}`);
                if (i < step) {
                    stepEl.classList.add('completed');
                } else {
                    stepEl.classList.add('active');
                }
            }
        }

        // Toast notifications
        function showToast(message, type = 'info', duration = 3000) {
            const toast = document.getElementById('toast');
            
            // Add icon based on type
            let icon = '';
            switch(type) {
                case 'success': icon = '✅ '; break;
                case 'error': icon = '❌ '; break;
                case 'warning': icon = '⚠️ '; break;
                default: icon = 'ℹ️ ';
            }
            
            toast.textContent = icon + message;
            toast.className = `toast ${type}`;
            setTimeout(() => toast.classList.add('show'), 100);
            
            setTimeout(() => {
                toast.classList.remove('show');
            }, duration);
        }

        // File upload
        const dropArea = document.getElementById('drop-area');
        const fileInput = document.getElementById('fileInput');

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Highlight drop area
        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.add('hover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.remove('hover'), false);
        });

        // Handle dropped files
        dropArea.addEventListener('drop', handleDrop, false);
        fileInput.addEventListener('change', handleFileSelect, false);

        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            handleFiles(files);
        }

        function handleFileSelect(e) {
            const files = e.target.files;
            handleFiles(files);
        }

        function handleFiles(files) {
            if (files.length === 0) return;
            
            const file = files[0];
            
            // Validations
            if (file.type !== 'application/pdf') {
                showToast('Por favor, selecione apenas arquivos PDF', 'error');
                return;
            }
            
            if (file.size > MAX_FILE_SIZE) {
                showToast(`Arquivo muito grande. Máximo: ${MAX_FILE_SIZE / 1024 / 1024}MB`, 'error');
                return;
            }
            
            // Show file info
            document.getElementById('fileName').textContent = file.name;
            document.getElementById('fileSize').textContent = formatFileSize(file.size);
            document.getElementById('fileInfo').style.display = 'block';
            
            // Process file
            uploadFile(file);
        }

        function formatFileSize(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function uploadFile(file) {
            if (isProcessing) {
                showToast('Aguarde o processamento atual terminar', 'warning');
                return;
            }
            
            isProcessing = true;
            showLoading('Enviando documento...');
            updateProgressSteps(2);
            
            const formData = new FormData();
            formData.append('file', file);
            
            // Simulate progress
            let progress = 0;
            const progressInterval = setInterval(() => {
                progress += Math.random() * 20;
                if (progress > 90) progress = 90;
                updateLoadingProgress(progress);
            }, 500);
            
            fetch('/processar', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                clearInterval(progressInterval);
                updateLoadingProgress(100);
                
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.erro || 'Erro ao processar arquivo');
                    });
                }
                return response.json();
            })
            .then(data => {
                showResult(data);
                updateProgressSteps(3);
                showToast('Documento processado com sucesso!', 'success');
                
                // Update stats
                processedCount++;
                totalReduction += data.reducao_percentual || 0;
                currentModel = data.modelo_usado || 'Gemini';
                localStorage.setItem('processedCount', processedCount);
                localStorage.setItem('totalReduction', totalReduction);
                updateStatsDisplay();
            })
            .catch(error => {
                showToast(error.message || 'Erro ao processar PDF', 'error');
                console.error('Erro:', error);
            })
            .finally(() => {
                isProcessing = false;
                hideLoading();
                clearInterval(progressInterval);
            });
        }

        // Process manual text
        function processManualText() {
            const text = document.getElementById('manualText').value.trim();
            
            if (!text) {
                showToast('Por favor, insira algum texto', 'warning');
                return;
            }
            
            if (text.length < 20) {
                showToast('Texto muito curto. Mínimo: 20 caracteres', 'warning');
                return;
            }
            
            if (text.length > 10000) {
                showToast('Texto muito longo. Máximo: 10.000 caracteres', 'warning');
                return;
            }
            
            if (isProcessing) {
                showToast('Aguarde o processamento atual terminar', 'warning');
                return;
            }
            
            isProcessing = true;
            showLoading('Processando texto...');
            updateProgressSteps(2);
            
            fetch('/processar_texto', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ texto: text })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.erro || 'Erro ao processar texto');
                    });
                }
                return response.json();
            })
            .then(data => {
                showResult(data);
                updateProgressSteps(3);
                showToast('Texto processado com sucesso!', 'success');
                
                // Update stats
                processedCount++;
                totalReduction += data.reducao_percentual || 0;
                localStorage.setItem('processedCount', processedCount);
                localStorage.setItem('totalReduction', totalReduction);
                updateStatsDisplay();
            })
            .catch(error => {
                showToast(error.message || 'Erro ao processar texto', 'error');
                console.error('Erro:', error);
            })
            .finally(() => {
                isProcessing = false;
                hideLoading();
            });
        }

        // Loading functions
        function showLoading(text = 'Processando...') {
            const overlay = document.getElementById('loadingOverlay');
            document.getElementById('loadingText').textContent = text;
            document.getElementById('modelInfo').textContent = 'Selecionando melhor modelo...';
            overlay.classList.add('show');
            updateLoadingProgress(0);
        }

        function hideLoading() {
            document.getElementById('loadingOverlay').classList.remove('show');
        }

        function updateLoadingProgress(percent) {
            document.getElementById('loadingProgress').style.width = percent + '%';
            
            // Update loading text based on progress
            if (percent > 30 && percent < 60) {
                document.getElementById('loadingText').textContent = 'Analisando documento...';
            } else if (percent >= 60 && percent < 90) {
                document.getElementById('loadingText').textContent = 'Simplificando com IA...';
                document.getElementById('modelInfo').textContent = 'Usando Gemini AI';
            } else if (percent >= 90) {
                document.getElementById('loadingText').textContent = 'Finalizando...';
            }
        }

        // Show result
        function showResult(data) {
            currentResultHash = Date.now().toString();
            
            // Format and display simplified text
            const formattedText = formatResultText(data.texto);
            document.getElementById('simplifiedText').innerHTML = formattedText;
            
            // Show analysis if available
            if (data.analise) {
                showResultAnalysis(data.analise);
            }
            
            // Show download button if PDF was processed
            if (data.caracteres_original) {
                document.getElementById('downloadBtn').style.display = 'inline-flex';
                document.getElementById('downloadBtn').href = '/download_pdf';
            }
            
            // Show result section
            document.getElementById('resultSection').style.display = 'block';
            
            // Scroll to result
            document.getElementById('resultSection').scrollIntoView({ 
                behavior: 'smooth', 
                block: 'start' 
            });
        }

        function showResultAnalysis(analise) {
            let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1rem;">';
            
            // Result type card
            let resultClass = 'result-card';
            let resultIcon = '📄';
            let resultText = 'Documento Processado';
            
            if (analise.tipo_resultado === 'vitoria') {
                resultClass += ' result-success';
                resultIcon = '✅';
                resultText = 'Resultado Favorável';
            } else if (analise.tipo_resultado === 'derrota') {
                resultClass += ' result-error';
                resultIcon = '❌';
                resultText = 'Resultado Desfavorável';
            } else if (analise.tipo_resultado === 'parcial') {
                resultClass += ' result-warning';
                resultIcon = '⚠️';
                resultText = 'Resultado Parcial';
            }
            
            html += `
                <div class="${resultClass}" style="text-align: center;">
                    <div style="font-size: 2rem;">${resultIcon}</div>
                    <div style="font-weight: bold; margin-top: 0.5rem;">${resultText}</div>
                </div>
            `;
            
            // Info cards
            if (analise.tem_valores) {
                html += `
                    <div class="result-card" style="text-align: center;">
                        <div style="font-size: 2rem;">💰</div>
                        <div style="font-weight: bold; margin-top: 0.5rem;">Contém Valores</div>
                    </div>
                `;
            }
            
            if (analise.tem_prazos) {
                html += `
                    <div class="result-card" style="text-align: center;">
                        <div style="font-size: 2rem;">📅</div>
                        <div style="font-weight: bold; margin-top: 0.5rem;">Contém Prazos</div>
                    </div>
                `;
            }
            
            if (analise.tem_recursos) {
                html += `
                    <div class="result-card" style="text-align: center;">
                        <div style="font-size: 2rem;">⚖️</div>
                        <div style="font-weight: bold; margin-top: 0.5rem;">Possível Recurso</div>
                    </div>
                `;
            }
            
            html += '</div>';
            
            document.getElementById('resultAnalysis').innerHTML = html;
        }

        function formatResultText(text) {
            // Format text with proper HTML
            let formatted = text;
            
            // Format bold text
            formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            
            // Format sections with icons
            const iconPatterns = [
                { icon: '📊', color: 'var(--primary)' },
                { icon: '📑', color: 'var(--secondary)' },
                { icon: '⚖️', color: 'var(--primary)' },
                { icon: '💰', color: 'var(--warning)' },
                { icon: '📅', color: 'var(--primary)' },
                { icon: '⚠️', color: 'var(--danger)' },
                { icon: '💡', color: 'var(--secondary)' }
            ];
            
            iconPatterns.forEach(pattern => {
                const regex = new RegExp(`(${pattern.icon}[^\\n]+)`, 'g');
                formatted = formatted.replace(regex, `<div style="color: ${pattern.color}; font-weight: bold; margin: 1rem 0;">$1</div>`);
            });
            
            // Format bullet points
            formatted = formatted.replace(/•/g, '▸');
            formatted = formatted.replace(/^\d\.\s/gm, '<br><strong>                    <button class="button" onclick="copyText()"</strong>');
            
            // Convert line breaks to HTML
            formatted = formatted.replace(/\n/g, '<br>');
            
            return formatted;
        }

        // Copy text
        function copyText() {
            const element = document.getElementById('simplifiedText');
            const text = element.innerText || element.textContent;
            
            if (!text) {
                showToast('Nenhum texto para copiar', 'warning');
                return;
            }
            
            navigator.clipboard.writeText(text)
                .then(() => {
                    showToast('Texto copiado com sucesso!', 'success');
                })
                .catch(() => {
                    // Fallback
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    showToast('Texto copiado!', 'success');
                });
        }

        // Text to speech
        let isSpeaking = false;
        function speakText() {
            const text = document.getElementById('simplifiedText').textContent;
            const btn = document.getElementById('speakBtn');
            
            if (!text) {
                showToast('Nenhum texto para ler', 'warning');
                return;
            }
            
            if (isSpeaking) {
                window.speechSynthesis.cancel();
                btn.innerHTML = '<span>🔊</span> Ler em Voz Alta';
                isSpeaking = false;
                return;
            }
            
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'pt-BR';
            utterance.rate = 0.9;
            
            utterance.onend = () => {
                btn.innerHTML = '<span>🔊</span> Ler em Voz Alta';
                isSpeaking = false;
            };
            
            utterance.onerror = () => {
                showToast('Erro ao ler o texto', 'error');
                btn.innerHTML = '<span>🔊</span> Ler em Voz Alta';
                isSpeaking = false;
            };
            
            window.speechSynthesis.speak(utterance);
            btn.innerHTML = '<span>⏹️</span> Parar Leitura';
            isSpeaking = true;
        }

        // Clear all
        function clearAll() {
            document.getElementById('manualText').value = '';
            document.getElementById('resultSection').style.display = 'none';
            document.getElementById('fileInfo').style.display = 'none';
            fileInput.value = '';
            updateProgressSteps(1);
            showToast('Tudo limpo!', 'info');
        }

        // Load example
        function loadExample() {
            const exampleText = `SENTENÇA

Processo nº 1234567-89.2024.8.26.0100

RELATÓRIO
Trata-se de ação de cobrança movida por JOÃO DA SILVA em face de EMPRESA XYZ LTDA, alegando inadimplemento contratual no valor de R$ 15.000,00.

FUNDAMENTAÇÃO
Analisando os autos, verifico que o autor comprovou a existência da dívida através de contrato assinado e notas fiscais. O réu, devidamente citado, não apresentou contestação.

DISPOSITIVO
Ante o exposto, JULGO PROCEDENTE o pedido para CONDENAR o réu a pagar ao autor a quantia de R$ 15.000,00, corrigida monetariamente desde o vencimento e acrescida de juros de 1% ao mês.

Condeno o réu ao pagamento das custas processuais e honorários advocatícios que fixo em 10% do valor da condenação.

P.R.I.`;
            
            document.getElementById('manualText').value = exampleText;
            showToast('Exemplo carregado! Clique em "Simplificar Texto" para processar', 'info', 4000);
        }

        // Feedback modal
        function showFeedbackModal() {
            document.getElementById('feedbackModal').classList.add('show');
        }

        function closeFeedbackModal() {
            document.getElementById('feedbackModal').classList.remove('show');
            selectedRating = 0;
            document.querySelectorAll('.star').forEach(star => star.classList.remove('active'));
            document.getElementById('feedbackComment').value = '';
        }

        // Rating stars
        document.querySelectorAll('.star').forEach(star => {
            star.addEventListener('click', function() {
                selectedRating = parseInt(this.dataset.rating);
                updateStars(selectedRating);
            });
            
            star.addEventListener('mouseenter', function() {
                const rating = parseInt(this.dataset.rating);
                updateStars(rating);
            });
        });

        document.getElementById('rating').addEventListener('mouseleave', function() {
            updateStars(selectedRating);
        });

        function updateStars(rating) {
            document.querySelectorAll('.star').forEach((star, index) => {
                if (index < rating) {
                    star.classList.add('active');
                } else {
                    star.classList.remove('active');
                }
            });
        }

        function submitFeedback() {
            if (selectedRating === 0) {
                showToast('Por favor, selecione uma avaliação', 'warning');
                return;
            }
            
            const comment = document.getElementById('feedbackComment').value;
            
            fetch('/feedback', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    rating: selectedRating,
                    comment: comment,
                    hash: currentResultHash
                })
            })
            .then(response => response.json())
            .then(data => {
                showToast('Obrigado pela sua avaliação!', 'success');
                closeFeedbackModal();
            })
            .catch(error => {
                showToast('Erro ao enviar avaliação', 'error');
                console.error('Erro:', error);
            });
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + Enter to process
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const manualText = document.getElementById('manualText').value;
                if (manualText) {
                    processManualText();
                }
            }
            
            // Esc to close modal or clear
            if (e.key === 'Escape') {
                if (document.getElementById('feedbackModal').classList.contains('show')) {
                    closeFeedbackModal();
                }
            }
        });

        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {
            initializeStats();
        });
    </script>
</body>
</html>>

