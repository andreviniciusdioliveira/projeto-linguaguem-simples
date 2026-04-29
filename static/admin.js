/**
 * Painel Administrativo · Entenda Aqui
 * Polling de /admin/api/stats a cada 30s, renderização com Chart.js,
 * tratamento de 401 (sessão expirada -> redireciona pra login).
 */

(function() {
    'use strict';

    const API_URL = '/admin/api/stats';
    const POLL_INTERVAL_MS = 30 * 1000;
    const TJTO_AZUL = '#1c4870';
    const TJTO_AZUL_LIGHT = '#4a78a3';
    const TJTO_DOURADO = '#b8963c';
    const SUCCESS_GREEN = '#1d7a4a';
    const DANGER_RED = '#b3261e';

    let charts = {};
    let pollTimer = null;

    function fmtNumero(n) {
        if (n == null) return '—';
        return new Intl.NumberFormat('pt-BR').format(n);
    }

    function fmtTempo(ms) {
        if (!ms || ms <= 0) return '—';
        if (ms < 1000) return `${ms} ms`;
        return `${(ms / 1000).toFixed(1)} s`;
    }

    function fmtBRL(valor) {
        if (valor == null || isNaN(valor)) return '—';
        return new Intl.NumberFormat('pt-BR', {
            style: 'currency',
            currency: 'BRL',
            minimumFractionDigits: 2,
            maximumFractionDigits: valor < 1 ? 4 : 2
        }).format(valor);
    }

    function fmtHora() {
        return new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function pillClass(taxa) {
        if (taxa < 5) return 'admin-pill admin-pill--ok';
        if (taxa < 25) return 'admin-pill admin-pill--warn';
        return 'admin-pill admin-pill--danger';
    }

    function preencherKPIs(data) {
        const docs = data.documentos || {};
        const fb = data.feedback || {};
        const tk = data.tokens || {};
        const tp = data.tempo_processamento || {};
        const al = data.alcance || {};

        setText('kpiDocsHoje', fmtNumero(docs.hoje));
        setText('kpiDocsHojeFoot', `total: ${fmtNumero(docs.total)}`);
        setText('kpiDocs7d', fmtNumero(docs.sete_dias));
        setText('kpiDocs30d', `30d: ${fmtNumero(docs.trinta_dias)}`);

        const tkHoje = (tk.hoje && tk.hoje.total) || 0;
        const tkMes = (tk.mes_atual && tk.mes_atual.total) || 0;
        setText('kpiTokensHoje', fmtNumero(tkHoje));
        setText('kpiTokensMes', `mês: ${fmtNumero(tkMes)}`);

        setText('kpiSatisfacao', fb.total ? `${fb.satisfacao_pct}%` : '—');
        setText('kpiFeedbackTotal', `amostras: ${fmtNumero(fb.total)}`);

        setText('kpiTempoMedio', fmtTempo(tp.media_ms));
        setText('kpiTempoFoot', tp.amostras_7d ? `7d · ${fmtNumero(tp.amostras_7d)} amostras` : '7d · sem dados');

        setText('kpiIpsUnicos', fmtNumero(al.ips_unicos_30d));

        // KPIs de custo (Gemini · BRL)
        const custos = data.custos || {};
        const ch = custos.hoje || {};
        const cm = custos.mes_atual || {};
        const c30 = custos.trinta_dias || {};

        setText('kpiCustoHoje', fmtBRL(ch.total_brl));
        setText('kpiCustoHojeFoot',
            `${fmtNumero(ch.total_documentos || 0)} docs · ${fmtNumero((ch.total_tokens_input || 0) + (ch.total_tokens_output || 0))} tokens`);

        setText('kpiCustoMes', fmtBRL(cm.total_brl));
        setText('kpiCustoMesFoot',
            `${fmtNumero(cm.total_documentos || 0)} docs · ${fmtNumero((cm.total_tokens_input || 0) + (cm.total_tokens_output || 0))} tokens`);

        // Médias por simplificação (baseadas em 30 dias)
        setText('kpiTokensPorDoc', fmtNumero(c30.tokens_medio_por_doc || 0));
        setText('kpiTokensPorDocFoot',
            `in: ${fmtNumero(c30.tokens_input_medio_por_doc || 0)} · out: ${fmtNumero(c30.tokens_output_medio_por_doc || 0)}`);

        setText('kpiCustoPorDoc', fmtBRL(c30.custo_medio_por_doc_brl));
    }

    function preencherSeguranca(data) {
        const sec = data.admin_login_24h || {};
        setText('loginSucesso', fmtNumero(sec.sucesso || 0));
        setText('loginFalha', fmtNumero(sec.falha || 0));
        setText('loginIps', fmtNumero(sec.ips_distintos || 0));
    }

    function ensureChart(id, config) {
        const canvas = document.getElementById(id);
        if (!canvas) return null;
        if (charts[id]) {
            charts[id].destroy();
        }
        charts[id] = new Chart(canvas, config);
        return charts[id];
    }

    function renderTokensChart(data) {
        const serie = (data.tokens && data.tokens.serie_30d) || [];
        const labels = serie.map(p => p.data.slice(5));  // MM-DD
        const tokens = serie.map(p => p.tokens);
        ensureChart('chartTokens', {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Tokens',
                    data: tokens,
                    borderColor: TJTO_AZUL,
                    backgroundColor: 'rgba(28, 72, 112, 0.12)',
                    tension: 0.25,
                    fill: true,
                    pointRadius: 2,
                    pointHoverRadius: 4,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${fmtNumero(ctx.parsed.y)} tokens` } }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { callback: v => fmtNumero(v) } },
                    x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } }
                }
            }
        });
    }

    function renderFeedbackChart(data) {
        const fb = data.feedback || {};
        ensureChart('chartFeedback', {
            type: 'doughnut',
            data: {
                labels: ['Útil', 'Não útil'],
                datasets: [{
                    data: [fb.positivo || 0, fb.negativo || 0],
                    backgroundColor: [SUCCESS_GREEN, DANGER_RED],
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                cutout: '65%',
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.label}: ${fmtNumero(ctx.parsed)} (${fb.total ? Math.round((ctx.parsed / fb.total) * 100) : 0}%)`
                        }
                    }
                }
            }
        });
    }

    function renderHeatmapChart(data) {
        const horas = data.heatmap_horas_7d || new Array(24).fill(0);
        const labels = horas.map((_, i) => `${String(i).padStart(2, '0')}h`);
        ensureChart('chartHeatmap', {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Documentos',
                    data: horas,
                    backgroundColor: TJTO_AZUL_LIGHT,
                    borderColor: TJTO_AZUL,
                    borderWidth: 1,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${fmtNumero(ctx.parsed.y)} documentos` } }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                    x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } }
                }
            }
        });
    }

    function renderIpsChart(data) {
        const serie = (data.alcance && data.alcance.serie_diaria) || [];
        const labels = serie.map(p => p.data.slice(5));
        const ips = serie.map(p => p.ips);
        ensureChart('chartIps', {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'IPs únicos',
                    data: ips,
                    backgroundColor: TJTO_DOURADO,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${fmtNumero(ctx.parsed.y)} IPs distintos` } }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                    x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } }
                }
            }
        });
    }

    function renderTabelaModelos(data) {
        const tbody = document.getElementById('tabelaModelosBody');
        if (!tbody) return;
        const modelos = data.modelos_gemini || [];
        if (modelos.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="admin-empty">Sem dados ainda.</td></tr>';
            return;
        }
        tbody.innerHTML = modelos.map(m => `
            <tr>
                <td><code>${escapeHtml(m.modelo)}</code></td>
                <td class="num">${fmtNumero(m.total)}</td>
                <td class="num">${fmtNumero(m.primario)}</td>
                <td class="num">${fmtNumero(m.fallback)}</td>
                <td class="num"><span class="${pillClass(m.taxa_fallback)}">${m.taxa_fallback}%</span></td>
            </tr>
        `).join('');
    }

    function renderTabelaCustoModelos(data) {
        const tbody = document.getElementById('tabelaCustoModelosBody');
        const tfoot = document.getElementById('tabelaCustoModelosFoot');
        if (!tbody) return;
        const c30 = (data.custos && data.custos.trinta_dias) || {};
        const linhas = c30.por_modelo || [];

        // Atualiza o câmbio mostrado no help text
        if (data.custos && data.custos.cambio_usd_brl) {
            setText('custoCambio', `R$ ${data.custos.cambio_usd_brl.toFixed(2)}/USD`);
        }

        if (linhas.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="admin-empty">Sem tokens registrados ainda. Aguardando processar 1ª simplificação após o deploy.</td></tr>';
            if (tfoot) tfoot.hidden = true;
            return;
        }

        tbody.innerHTML = linhas.map(r => `
            <tr>
                <td><code>${escapeHtml(r.modelo)}</code></td>
                <td class="num">${fmtNumero(r.documentos)}</td>
                <td class="num">${fmtNumero(r.tokens_input)}</td>
                <td class="num">${fmtNumero(r.tokens_output)}</td>
                <td class="num">${fmtNumero(r.tokens_medio_por_doc)}</td>
                <td class="num"><strong>${fmtBRL(r.custo_brl)}</strong></td>
                <td class="num">${fmtBRL(r.custo_brl_por_doc)}</td>
            </tr>
        `).join('');

        if (tfoot) {
            tfoot.hidden = false;
            setText('custoFootDocs', fmtNumero(c30.total_documentos));
            setText('custoFootIn', fmtNumero(c30.total_tokens_input));
            setText('custoFootOut', fmtNumero(c30.total_tokens_output));
            setText('custoFootMedio', fmtNumero(c30.tokens_medio_por_doc));
            setText('custoFootTotal', fmtBRL(c30.total_brl));
            setText('custoFootPorDoc', fmtBRL(c30.custo_medio_por_doc_brl));
        }
    }

    function renderTabelaTipos(data) {
        const tbody = document.getElementById('tabelaTiposBody');
        if (!tbody) return;
        const tipos = (data.documentos && data.documentos.tipos) || [];
        const total = tipos.reduce((acc, t) => acc + t.quantidade, 0);
        if (tipos.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="admin-empty">Sem dados ainda.</td></tr>';
            return;
        }
        tbody.innerHTML = tipos.map(t => {
            const pct = total ? ((t.quantidade / total) * 100).toFixed(1) : '0';
            return `<tr>
                <td>${escapeHtml(t.tipo)}</td>
                <td class="num">${fmtNumero(t.quantidade)}</td>
                <td class="num">${pct}%</td>
            </tr>`;
        }).join('');
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function setLastUpdate(text) {
        setText('lastUpdate', text);
    }

    async function fetchStats() {
        try {
            setLastUpdate('atualizando…');
            const resp = await fetch(API_URL, {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' }
            });
            if (resp.status === 401) {
                window.location.href = '/admin/login';
                return;
            }
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const data = await resp.json();
            if (data.erro) {
                console.error('Erro do backend:', data.erro);
                setLastUpdate(`erro: ${data.erro}`);
                return;
            }
            preencherKPIs(data);
            preencherSeguranca(data);
            renderTokensChart(data);
            renderFeedbackChart(data);
            renderHeatmapChart(data);
            renderIpsChart(data);
            renderTabelaModelos(data);
            renderTabelaCustoModelos(data);
            renderTabelaTipos(data);
            setLastUpdate(`atualizado ${fmtHora()}`);
        } catch (err) {
            console.error('fetchStats falhou:', err);
            setLastUpdate(`falha em ${fmtHora()} — tentando novamente…`);
        }
    }

    function start() {
        // Garante que Chart.js carregou (script tag tem defer).
        // Se passar de 5s sem aparecer, provavelmente foi bloqueado (CSP, ad-blocker
        // ou erro 404 no asset). Avisa o usuário em vez de esperar pra sempre.
        const PRAZO_CHART_MS = 5000;
        if (typeof Chart === 'undefined') {
            if (!start._chartTimeout) {
                start._chartTimeout = setTimeout(() => {
                    setLastUpdate('falha ao carregar Chart.js — verifique /static/chart.umd.min.js');
                    console.error('Chart.js não carregou em ' + PRAZO_CHART_MS + 'ms — abortando renderização de gráficos');
                }, PRAZO_CHART_MS);
            }
            setTimeout(start, 100);
            return;
        }
        if (start._chartTimeout) {
            clearTimeout(start._chartTimeout);
            start._chartTimeout = null;
        }
        Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
        Chart.defaults.color = '#5b6776';

        fetchStats();
        pollTimer = setInterval(fetchStats, POLL_INTERVAL_MS);

        // Pausa polling quando aba não está visível (economia)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                clearInterval(pollTimer);
            } else {
                fetchStats();
                pollTimer = setInterval(fetchStats, POLL_INTERVAL_MS);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
