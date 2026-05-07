(function () {
    'use strict';

    const REPORT_TYPES = ['Weekly', 'Bi-Weekly', 'Monthly', 'Custom'];
    const DEFAULT_NODE = { id: 'all', label: 'All Nodes' };
    const POLL_INTERVAL_MS = 300000;
    const DEBOUNCE_DELAY_MS = 300;

    const state = {
        reportUrl: '',
        reportType: 'Bi-Weekly',
        selectedNode: 'all',
        dateFrom: '',
        dateTo: '',
        nodes: [DEFAULT_NODE],
        chartInstance: null,
        lastFetchState: null,
        isFetching: false,
        lastPollTime: 0,
        lastInsightsHash: '',
        lastActionsHash: '',
        lastButtonsHash: '',
    };

    const elements = {};
    let debouncedFetch;
    let abortController = null;


    function initializeElements(root) {
        const ids = {
            reportTypeContainer: 'reportTypeContainer',
            nodeDropdownMenu: 'nodeDropdownMenu',
            nodeDisplay: 'nodeDisplay',
            chartTitle: 'chartTitle',
            dateDisplay: 'dateDisplay',
            metaReportType: 'metaReportType',
            metaDateDisplay: 'metaDateDisplay',
            dateFromInput: 'dateFromInput',
            dateToInput: 'dateToInput',
            dateApplyBtn: 'dateApplyBtn',
            dateDropdownMenu: 'dateDropdownMenu',
            dateToggleBtn: 'dateToggleBtn',
            nodeToggleBtn: 'nodeToggleBtn',
            dateDropdownWrapper: 'dateDropdownWrapper',
            nodeDropdownWrapper: 'nodeDropdownWrapper',
            exportPdfBtn: 'exportPdfBtn',
            exportCsvBtn: 'exportCsvBtn',
            printBtn: 'printBtn',
            avgAqiValue: 'avgAqiValue',
            avgAqiSub: 'avgAqiSub',
            peakAqiValue: 'peakAqiValue',
            peakAqiSub: 'peakAqiSub',
            lowAqiValue: 'lowAqiValue',
            lowAqiSub: 'lowAqiSub',
            affectedNodeValue: 'affectedNodeValue',
            affectedNodeSub: 'affectedNodeSub',
            goodDays: 'goodDays',
            moderateDays: 'moderateDays',
            unhealthyDays: 'unhealthyDays',
            goodPctBar: 'goodPctBar',
            moderatePctBar: 'moderatePctBar',
            unhealthyPctBar: 'unhealthyPctBar',
            distributionNote: 'distributionNote',
            insightsList: 'insightsList',
            actionPlanList: 'actionPlanList',
            alertBadgeText: 'alertBadgeText',
            dateValidationMessage: 'dateValidationMessage',
            generatedAt: 'metaGeneratedAt',
            uptime: 'metaUptime',
            nodesOnline: 'metaNodesOnline',
            aqiChart: 'aqiChart',
        };
        
        Object.keys(ids).forEach(key => {
            elements[key] = document.getElementById(ids[key]);
        });
    }

    function formatDateLabel(dateString, keepYear = false) {
        if (!dateString) return '';
        const date = new Date(dateString);
        if (Number.isNaN(date.getTime())) return dateString;
        const options = { month: 'short', day: 'numeric' };
        if (keepYear) options.year = 'numeric';
        return date.toLocaleDateString('en-US', options);
    }

    function buildRangeLabel(from, to) {
        return `${formatDateLabel(from)} – ${formatDateLabel(to, true)}`;
    }

    function simpleHash(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = ((hash << 5) - hash) + str.charCodeAt(i);
            hash |= 0;
        }
        return String(hash);
    }

    function getStateKey() {
        return `${state.dateFrom}|${state.dateTo}|${state.selectedNode}|${state.reportType}`;
    }

    function hasStateChanged() {
        const currentKey = getStateKey();
        return state.lastFetchState !== currentKey;
    }


    function toggleDropdown(menu) {
        if (!menu) return;
        menu.classList.toggle('is-open');
    }

    function closeDropdowns() {
        if (elements.dateDropdownMenu) elements.dateDropdownMenu.classList.remove('is-open');
        if (elements.nodeDropdownMenu) elements.nodeDropdownMenu.classList.remove('is-open');
    }

    function renderReportTypeButtons() {
        if (!elements.reportTypeContainer) return;
        
        const btnHash = simpleHash(state.reportType);
        if (state.lastButtonsHash === btnHash) return;
        state.lastButtonsHash = btnHash;
        
        elements.reportTypeContainer.innerHTML = '';
        REPORT_TYPES.forEach((type) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `creports-segmented__btn ${state.reportType === type ? 'is-active' : ''}`;
            button.textContent = type;
            if (type === 'Custom') button.id = 'customBtn';
            button.addEventListener('click', (e) => {
                e.stopPropagation();
                setReportType(type);
            });
            elements.reportTypeContainer.appendChild(button);
        });
    }

    function renderNodeOptions(newNodes) {
        if (!elements.nodeDropdownMenu) return;
        
        const prevIds = state.nodes.map(n => n.id).join('|');
        const nextIds = [DEFAULT_NODE.id, ...(newNodes || []).map(n => n.id)].join('|');
        
        if (prevIds === nextIds) return;
        
        state.nodes = [DEFAULT_NODE].concat(newNodes || []);
        elements.nodeDropdownMenu.innerHTML = '';

        state.nodes.forEach((node) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `creports-dropdown-menu__option ${state.selectedNode === node.id ? 'is-active' : ''}`;
            button.textContent = node.label;
            button.addEventListener('click', () => {
                setSelectedNode(node.id, node.label);
                closeDropdowns();
            });
            elements.nodeDropdownMenu.appendChild(button);
        });

        const activeNode = state.nodes.find((item) => item.id === state.selectedNode) || DEFAULT_NODE;
        if (elements.nodeDisplay) {
            elements.nodeDisplay.textContent = activeNode.label;
        }
    }

    function setReportType(type) {
        if (state.reportType === type) return;
        
        state.reportType = type;
        closeDropdowns();

        const today = new Date();
        let fromDate = new Date();
        
        if (type === 'Weekly') {
            fromDate.setDate(today.getDate() - 6);
        } else if (type === 'Bi-Weekly') {
            fromDate.setDate(today.getDate() - 14);
        } else if (type === 'Monthly') {
            fromDate.setDate(today.getDate() - 29);
        } else {
            renderReportTypeButtons();
            updateDateInputs();
            updateDateDisplays();
            if (elements.dateDropdownMenu) {
                elements.dateDropdownMenu.classList.add('is-open');
            }
            return;
        }

        state.dateFrom = fromDate.toISOString().slice(0, 10);
        state.dateTo = today.toISOString().slice(0, 10);
        renderReportTypeButtons();
        updateDateInputs();
        updateDateDisplays();
        triggerFetch();
    }

    function setSelectedNode(id, label) {
        if (state.selectedNode === id) return;
        
        state.selectedNode = id;
        if (elements.nodeDisplay) {
            elements.nodeDisplay.textContent = label;
        }
        
        if (elements.nodeDropdownMenu) {
            Array.from(elements.nodeDropdownMenu.children).forEach((button) => {
                button.classList.toggle('is-active', button.textContent === label);
            });
        }
        
        triggerFetch();
    }

    function updateDateInputs() {
        if (elements.dateFromInput) elements.dateFromInput.value = state.dateFrom || '';
        if (elements.dateToInput) elements.dateToInput.value = state.dateTo || '';
    }

    function updateDateDisplays() {
        const label = buildRangeLabel(state.dateFrom, state.dateTo);
        if (elements.dateDisplay) elements.dateDisplay.textContent = label;
        if (elements.metaDateDisplay) elements.metaDateDisplay.textContent = label;
    }

    function createChart(labels, values) {
        if (!elements.aqiChart) return;
        
        const ctx = elements.aqiChart.getContext('2d');
        if (state.chartInstance) {
            state.chartInstance.destroy();
        }

        state.chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'AQI',
                    data: values,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.12)',
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#3b82f6',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1,
                    tension: 0.3,
                    spanGaps: true,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#0f172a',
                        titleFont: { size: 11 },
                        bodyFont: { size: 11, weight: 'bold' },
                        padding: 8,
                        displayColors: false,
                    }
                },
                scales: {
                    x: {
                        grid: { display: false, drawBorder: false },
                        ticks: { font: { size: 10 }, color: '#64748b' },
                        border: { color: '#cbd5e1' }
                    },
                    y: {
                        grid: {
                            color: '#e2e8f0',
                            borderDash: [3, 3],
                            drawBorder: false
                        },
                        ticks: {
                            font: { size: 10 },
                            color: '#64748b',
                            stepSize: 50,
                        },
                        min: 0,
                        max: 180,
                        border: { display: false }
                    }
                }
            }
        });
    }

    function updateChart(labels, values) {
        if (!state.chartInstance) {
            createChart(labels, values);
            return;
        }
        
        const labelsChanged = JSON.stringify(state.chartInstance.data.labels) !== JSON.stringify(labels);
        if (labelsChanged) {
            state.chartInstance.data.labels = labels;
        }
        
        state.chartInstance.data.datasets[0].data = values;
        state.chartInstance.update('none');
    }

    function setMetricText(element, value) {
        if (!element) return;
        const newText = value != null ? String(value) : '-';
        if (element.textContent !== newText) {
            element.textContent = newText;
        }
    }

    function renderListItems(container, items, styleClass, bulletColor, hashKey) {
        if (!container) return;
        
        const contentHash = simpleHash(JSON.stringify(items || []));
        if (hashKey && state[hashKey] === contentHash) return;
        if (hashKey) state[hashKey] = contentHash;
        
        container.innerHTML = '';
        if (!Array.isArray(items) || !items.length) {
            const item = document.createElement('li');
            item.className = styleClass;
            item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>No data available.</span>`;
            container.appendChild(item);
            return;
        }

        items.forEach((text) => {
            const item = document.createElement('li');
            item.className = styleClass;
            item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>${text}</span>`;
            container.appendChild(item);
        });
    }

    async function fetchJson(url) {
        if (abortController) abortController.abort();
        abortController = new AbortController();

        const response = await fetch(url, {
            headers: { 'Accept': 'application/json' },
            signal: abortController.signal,
        });
        
        if (!response.ok) {
            throw new Error(`Failed to fetch report data: ${response.statusText}`);
        }
        return await response.json();
    }

    async function fetchAndRenderReport() {
        if (!state.reportUrl || state.isFetching) return;
        if (!hasStateChanged()) return;

        state.isFetching = true;
        const currentStateKey = getStateKey();

        const url = new URL(state.reportUrl, window.location.origin);
        url.searchParams.set('date_from', state.dateFrom);
        url.searchParams.set('date_to', state.dateTo);
        if (state.selectedNode !== 'all') {
            url.searchParams.set('node', state.selectedNode);
        }

        try {
            const data = await fetchJson(url.toString());
            
            if (getStateKey() !== currentStateKey) return;
            
            state.lastFetchState = currentStateKey;
            renderNodeOptions(data.nodes);
            renderView(data);
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('[EnviroNode] Report fetch error:', error);
            }
        } finally {
            state.isFetching = false;
        }
    }

    function triggerFetch() {
        if (debouncedFetch) clearTimeout(debouncedFetch);
        debouncedFetch = setTimeout(fetchAndRenderReport, DEBOUNCE_DELAY_MS);
    }

    function renderView(data) {
        setMetricText(elements.avgAqiValue, data.avg_aqi);
        setMetricText(elements.avgAqiSub, data.avg_aqi_category);
        setMetricText(elements.peakAqiValue, data.peak_aqi);
        setMetricText(elements.peakAqiSub, data.peak_level ? `${data.peak_level}${data.peak_date ? ` (${data.peak_date})` : ''}` : '-');
        setMetricText(elements.lowAqiValue, data.low_aqi);
        setMetricText(elements.lowAqiSub, data.low_level ? `${data.low_level}${data.low_date ? ` (${data.low_date})` : ''}` : '-');
        setMetricText(elements.affectedNodeValue, data.most_affected_node ? data.most_affected_node.name : 'N/A');
        setMetricText(elements.affectedNodeSub, data.most_affected_node ? `(${data.most_affected_node.location})` : '(Unknown Area)');

        setMetricText(elements.goodDays, data.good_days);
        setMetricText(elements.moderateDays, data.moderate_days);
        setMetricText(elements.unhealthyDays, data.unhealthy_days);

        if (elements.goodPctBar) {
            elements.goodPctBar.style.width = `${data.good_pct}%`;
            elements.goodPctBar.textContent = `${data.good_pct}%`;
        }
        if (elements.moderatePctBar) {
            elements.moderatePctBar.style.width = `${data.moderate_pct}%`;
            elements.moderatePctBar.textContent = `${data.moderate_pct}%`;
        }
        if (elements.unhealthyPctBar) {
            elements.unhealthyPctBar.style.width = `${data.unhealthy_pct}%`;
            elements.unhealthyPctBar.textContent = `${data.unhealthy_pct}%`;
        }

        setMetricText(elements.distributionNote, data.distribution_note || 'Distribution summary unavailable.');
        setMetricText(elements.alertBadgeText, data.insights && data.insights.length ? data.insights[0] : 'No significant anomaly detected during this period.');
        setMetricText(elements.generatedAt, `Gen: ${data.generated_at || ''}`);
        setMetricText(elements.uptime, `${data.uptime_pct || 0}% Uptime`);
        setMetricText(elements.nodesOnline, `${data.nodes_online || 0}/${data.total_nodes || 0} Nodes Online`);
        setMetricText(elements.metaReportType, data.report_type || 'Custom');
        setMetricText(elements.metaDateDisplay, data.report_period || buildRangeLabel(state.dateFrom, state.dateTo));
        setMetricText(elements.dateDisplay, data.report_period || buildRangeLabel(state.dateFrom, state.dateTo));
        
        if (elements.dateFromInput) elements.dateFromInput.value = data.date_from || state.dateFrom;
        if (elements.dateToInput) elements.dateToInput.value = data.date_to || state.dateTo;
        
        state.reportType = data.report_type || state.reportType;
        renderReportTypeButtons();
        updateDateDisplays();

        setMetricText(elements.chartTitle, `AQI Trend (${data.total_days || 0} Days)`);
        updateChart(data.trend_labels || [], data.trend_values || []);

        renderListItems(elements.insightsList, data.insights, 'creports-list__item creports-list__item--light', '#ef4444', 'lastInsightsHash');
        renderListItems(elements.actionPlanList, data.actions, 'creports-list__item creports-list__item--dark', '#4ade80', 'lastActionsHash');
    }

    function attachEventListeners() {
        if (elements.dateToggleBtn) {
            elements.dateToggleBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                if (elements.nodeDropdownMenu) elements.nodeDropdownMenu.classList.remove('is-open');
                if (state.reportType !== 'Custom') {
                    setReportType('Custom');
                    return;
                }
                toggleDropdown(elements.dateDropdownMenu);
            });
        }

        if (elements.nodeToggleBtn) {
            elements.nodeToggleBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                if (elements.dateDropdownMenu) elements.dateDropdownMenu.classList.remove('is-open');
                toggleDropdown(elements.nodeDropdownMenu);
            });
        }

        if (elements.dateApplyBtn) {
            elements.dateApplyBtn.addEventListener('click', () => {
                const from = elements.dateFromInput?.value;
                const to = elements.dateToInput?.value;
                
                if (!from || !to) {
                    if (elements.dateValidationMessage) {
                        elements.dateValidationMessage.textContent = 'Please select both start and end dates.';
                    }
                    return;
                }
                
                const fromDate = new Date(from);
                const toDate = new Date(to);
                
                if (Number.isNaN(fromDate.getTime()) || Number.isNaN(toDate.getTime())) {
                    if (elements.dateValidationMessage) {
                        elements.dateValidationMessage.textContent = 'Please use valid dates.';
                    }
                    return;
                }
                
                if (toDate < fromDate) {
                    if (elements.dateValidationMessage) {
                        elements.dateValidationMessage.textContent = 'End date must be after start date.';
                    }
                    return;
                }
                
                if (elements.dateValidationMessage) elements.dateValidationMessage.textContent = '';
                state.dateFrom = from;
                state.dateTo = to;
                state.reportType = 'Custom';
                renderReportTypeButtons();
                updateDateDisplays();
                closeDropdowns();
                triggerFetch();
            });
        }

        if (elements.dateFromInput) {
            elements.dateFromInput.addEventListener('input', () => {
                if (elements.dateValidationMessage) elements.dateValidationMessage.textContent = '';
            });
        }

        if (elements.dateToInput) {
            elements.dateToInput.addEventListener('input', () => {
                if (elements.dateValidationMessage) elements.dateValidationMessage.textContent = '';
            });
        }

        document.addEventListener('click', (event) => {
            const isDateDropdown = elements.dateDropdownWrapper?.contains(event.target);
            const isNodeDropdown = elements.nodeDropdownWrapper?.contains(event.target);
            if (!isDateDropdown && !isNodeDropdown) {
                closeDropdowns();
            }
        });

        if (elements.exportPdfBtn) {
            elements.exportPdfBtn.addEventListener('click', () => {
                const url = `${window.location.origin}/export/pdf/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = url;
            });
        }

        if (elements.exportCsvBtn) {
            elements.exportCsvBtn.addEventListener('click', () => {
                const url = `${window.location.origin}/export/csv/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = url;
            });
        }

        if (elements.printBtn) {
            elements.printBtn.addEventListener('click', () => {
                const url = `${window.location.origin}/export/print/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.open(url, '_blank');
            });
        }
    }

    function loadInitialState(root) {
        state.reportUrl = root.dataset.reportUrl || '';
        state.dateFrom = root.dataset.dateFrom || state.dateFrom;
        state.dateTo = root.dataset.dateTo || state.dateTo;
        state.selectedNode = root.dataset.selectedNode || state.selectedNode;
        state.lastFetchState = getStateKey();
    }

    function setupPolling() {
        if (POLL_INTERVAL_MS <= 0) return;
        
        setInterval(() => {
            if (hasStateChanged()) {
                fetchAndRenderReport();
            }
        }, POLL_INTERVAL_MS);
    }

    function init() {
        const root = document.getElementById('creportsRoot');
        if (!root) return;

        loadInitialState(root);
        initializeElements(root);
        updateDateDisplays();
        renderReportTypeButtons();
        updateDateInputs();
        attachEventListeners();
        fetchAndRenderReport();

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }

        setupPolling();
    }

    document.addEventListener('DOMContentLoaded', init);
})();