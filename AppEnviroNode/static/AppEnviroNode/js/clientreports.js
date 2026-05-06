(function () {
    'use strict';

    const REPORT_TYPES = ['Weekly', 'Bi-Weekly', 'Monthly', 'Custom'];
    const DEFAULT_NODE = { id: 'all', label: 'All Nodes' };
    const POLL_INTERVAL_MS = 300000; // 5 minutes

    const state = {
        reportUrl: '',
        reportType: 'Bi-Weekly',
        selectedNode: 'all',
        dateFrom: '',
        dateTo: '',
        nodes: [DEFAULT_NODE],
        chartInstance: null,
        shouldPoll: true,
    };

    const elements = {
        reportTypeContainer: null,
        nodeDropdownMenu: null,
        nodeDisplay: null,
        chartTitle: null,
        dateDisplay: null,
        metaReportType: null,
        metaDateDisplay: null,
        dateFromInput: null,
        dateToInput: null,
        dateApplyBtn: null,
        dateDropdownMenu: null,
        nodeToggleBtn: null,
        dateDropdownWrapper: null,
        nodeDropdownWrapper: null,
        exportPdfBtn: null,
        exportCsvBtn: null,
        printBtn: null,
        avgAqiValue: null,
        avgAqiSub: null,
        peakAqiValue: null,
        peakAqiSub: null,
        lowAqiValue: null,
        lowAqiSub: null,
        affectedNodeValue: null,
        affectedNodeSub: null,
        goodDays: null,
        moderateDays: null,
        unhealthyDays: null,
        goodPctBar: null,
        moderatePctBar: null,
        unhealthyPctBar: null,
        distributionNote: null,
        insightsList: null,
        actionPlanList: null,
        alertBadgeText: null,
        dateValidationMessage: null,
        generatedAt: null,
        uptime: null,
        nodesOnline: null,
    };

    function formatDateLabel(dateString, keepYear = false) {
        if (!dateString) {
            return '';
        }
        const date = new Date(dateString);
        if (Number.isNaN(date.getTime())) {
            return dateString;
        }
        const options = { month: 'short', day: 'numeric' };
        if (keepYear) {
            options.year = 'numeric';
        }
        return date.toLocaleDateString('en-US', options);
    }

    function buildRangeLabel(from, to) {
        const fromLabel = formatDateLabel(from);
        const toLabel = formatDateLabel(to, true);
        return `${fromLabel} – ${toLabel}`;
    }

    function getElement(id) {
        return document.getElementById(id);
    }

    function initializeElements(root) {
        elements.reportTypeContainer = getElement('reportTypeContainer');
        elements.nodeDropdownMenu = getElement('nodeDropdownMenu');
        elements.nodeDisplay = getElement('nodeDisplay');
        elements.chartTitle = getElement('chartTitle');
        elements.dateDisplay = getElement('dateDisplay');
        elements.metaReportType = getElement('metaReportType');
        elements.metaDateDisplay = getElement('metaDateDisplay');
        elements.dateFromInput = getElement('dateFromInput');
        elements.dateToInput = getElement('dateToInput');
        elements.dateApplyBtn = getElement('dateApplyBtn');
        elements.dateDropdownMenu = getElement('dateDropdownMenu');
        elements.nodeToggleBtn = getElement('nodeToggleBtn');
        elements.dateDropdownWrapper = getElement('dateDropdownWrapper');
        elements.nodeDropdownWrapper = getElement('nodeDropdownWrapper');
        elements.exportPdfBtn = getElement('exportPdfBtn');
        elements.exportCsvBtn = getElement('exportCsvBtn');
        elements.printBtn = getElement('printBtn');
        elements.avgAqiValue = getElement('avgAqiValue');
        elements.avgAqiSub = getElement('avgAqiSub');
        elements.peakAqiValue = getElement('peakAqiValue');
        elements.peakAqiSub = getElement('peakAqiSub');
        elements.lowAqiValue = getElement('lowAqiValue');
        elements.lowAqiSub = getElement('lowAqiSub');
        elements.affectedNodeValue = getElement('affectedNodeValue');
        elements.affectedNodeSub = getElement('affectedNodeSub');
        elements.goodDays = getElement('goodDays');
        elements.moderateDays = getElement('moderateDays');
        elements.unhealthyDays = getElement('unhealthyDays');
        elements.goodPctBar = getElement('goodPctBar');
        elements.moderatePctBar = getElement('moderatePctBar');
        elements.unhealthyPctBar = getElement('unhealthyPctBar');
        elements.distributionNote = getElement('distributionNote');
        elements.insightsList = getElement('insightsList');
        elements.actionPlanList = getElement('actionPlanList');
        elements.alertBadgeText = getElement('alertBadgeText');
        elements.dateValidationMessage = getElement('dateValidationMessage');
        elements.generatedAt = getElement('metaGeneratedAt');
        elements.uptime = getElement('metaUptime');
        elements.nodesOnline = getElement('metaNodesOnline');
    }

    function toggleDropdown(menu) {
        menu.classList.toggle('is-open');
    }

    function closeDropdowns() {
        elements.dateDropdownMenu.classList.remove('is-open');
        elements.nodeDropdownMenu.classList.remove('is-open');
    }

    function renderReportTypeButtons() {
        elements.reportTypeContainer.innerHTML = '';

        REPORT_TYPES.forEach((type) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `creports-segmented__btn ${state.reportType === type ? 'is-active' : ''}`;
            button.textContent = type;
            if (type === 'Custom') {
                button.id = 'customBtn';
            }
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                setReportType(type);
            });
            elements.reportTypeContainer.appendChild(button);
        });
    }

    function renderNodeOptions(nodes) {
        state.nodes = [DEFAULT_NODE].concat(nodes || []);
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
        elements.nodeDisplay.textContent = activeNode.label;
    }

    function setReportType(type) {
        state.reportType = type;
        renderReportTypeButtons();

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
            elements.nodeDropdownMenu.classList.remove('is-open');
            updateDateInputs();
            updateDateDisplays();
            elements.dateDropdownMenu.classList.add('is-open');
            return;
        }

        state.dateFrom = fromDate.toISOString().slice(0, 10);
        state.dateTo = today.toISOString().slice(0, 10);
        updateDateInputs();
        updateDateDisplays();
        fetchAndRenderReport();
    }

    function setSelectedNode(id, label) {
        state.selectedNode = id;
        elements.nodeDisplay.textContent = label;
        Array.from(elements.nodeDropdownMenu.children).forEach((button) => {
            button.classList.toggle('is-active', button.textContent === label);
        });
        fetchAndRenderReport();
    }

    function formatForDateInput(value) {
        return value || '';
    }

    function updateDateInputs() {
        elements.dateFromInput.value = formatForDateInput(state.dateFrom);
        elements.dateToInput.value = formatForDateInput(state.dateTo);
    }

    function updateDateDisplays() {
        const label = buildRangeLabel(state.dateFrom, state.dateTo);
        elements.dateDisplay.textContent = label;
        elements.metaDateDisplay.textContent = label;
    }

    function createChart(labels, values) {
        const ctx = document.getElementById('aqiChart').getContext('2d');

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
        state.chartInstance.data.labels = labels;
        state.chartInstance.data.datasets[0].data = values;
        state.chartInstance.update();
    }

    function setMetricText(element, value) {
        if (!element) return;
        element.textContent = value != null ? value : '-';
    }

    function renderListItems(container, items, styleClass, bulletColor) {
        if (!container) {
            return;
        }
        container.innerHTML = '';
        if (!Array.isArray(items) || !items.length) {
            const item = document.createElement('li');
            item.className = `${styleClass}`;
            item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>No data available.</span>`;
            container.appendChild(item);
            return;
        }

        items.forEach((text) => {
            const item = document.createElement('li');
            item.className = `${styleClass}`;
            item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>${text}</span>`;
            container.appendChild(item);
        });
    }

    async function fetchJson(url) {
        const response = await fetch(url, {
            headers: {
                'Accept': 'application/json',
            }
        });
        if (!response.ok) {
            throw new Error(`Failed to fetch report data: ${response.statusText}`);
        }
        return await response.json();
    }

    async function fetchAndRenderReport() {
        if (!state.reportUrl) {
            return;
        }

        const url = new URL(state.reportUrl, window.location.origin);
        url.searchParams.set('date_from', state.dateFrom);
        url.searchParams.set('date_to', state.dateTo);
        if (state.selectedNode !== 'all') {
            url.searchParams.set('node', state.selectedNode);
        }

        try {
            const data = await fetchJson(url.toString());
            state.nodes = data.nodes || state.nodes;
            renderNodeOptions(data.nodes);
            renderView(data);
        } catch (error) {
            // eslint-disable-next-line no-console
            console.error('[EnviroNode] Report fetch error:', error);
        }
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
        if (elements.dateFromInput) {
            elements.dateFromInput.value = data.date_from || state.dateFrom;
        }
        if (elements.dateToInput) {
            elements.dateToInput.value = data.date_to || state.dateTo;
        }
        state.reportType = data.report_type || state.reportType;
        renderReportTypeButtons();
        updateDateDisplays();

        setMetricText(elements.chartTitle, `AQI Trend (${data.total_days || 0} Days)`);

        updateChart(data.trend_labels || [], data.trend_values || []);

        renderListItems(elements.insightsList, data.insights, 'creports-list__item creports-list__item--light', '#ef4444');
        renderListItems(elements.actionPlanList, data.actions, 'creports-list__item creports-list__item--dark', '#4ade80');
    }

    function attachEventListeners() {
        if (elements.dateToggleBtn) {
            elements.dateToggleBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                elements.nodeDropdownMenu.classList.remove('is-open');
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
                elements.dateDropdownMenu.classList.remove('is-open');
                toggleDropdown(elements.nodeDropdownMenu);
            });
        }

        if (elements.dateApplyBtn) {
            elements.dateApplyBtn.addEventListener('click', () => {
                const from = elements.dateFromInput.value;
                const to = elements.dateToInput.value;
                if (!from || !to) {
                    elements.dateValidationMessage.textContent = 'Please select both start and end dates.';
                    return;
                }
                const fromDate = new Date(from);
                const toDate = new Date(to);
                if (Number.isNaN(fromDate.getTime()) || Number.isNaN(toDate.getTime())) {
                    elements.dateValidationMessage.textContent = 'Please use valid dates.';
                    return;
                }
                if (toDate < fromDate) {
                    elements.dateValidationMessage.textContent = 'End date must be after start date.';
                    return;
                }
                elements.dateValidationMessage.textContent = '';
                state.dateFrom = from;
                state.dateTo = to;
                state.reportType = 'Custom';
                renderReportTypeButtons();
                updateDateDisplays();
                closeDropdowns();
                fetchAndRenderReport();
            });
        }

        if (elements.dateFromInput) {
            elements.dateFromInput.addEventListener('input', () => {
                elements.dateValidationMessage.textContent = '';
            });
        }

        if (elements.dateToInput) {
            elements.dateToInput.addEventListener('input', () => {
                elements.dateValidationMessage.textContent = '';
            });
        }

        document.addEventListener('click', (event) => {
            if (!elements.dateDropdownWrapper.contains(event.target) && !elements.nodeDropdownWrapper.contains(event.target)) {
                closeDropdowns();
            }
        });

        if (elements.exportPdfBtn) {
            elements.exportPdfBtn.addEventListener('click', () => {
                const pdfUrl = `${window.location.origin}/export/pdf/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = pdfUrl;
            });
        }

        if (elements.exportCsvBtn) {
            elements.exportCsvBtn.addEventListener('click', () => {
                const csvUrl = `${window.location.origin}/export/csv/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = csvUrl;
            });
        }

        if (elements.printBtn) {
            elements.printBtn.addEventListener('click', () => {
                const printUrl = `${window.location.origin}/export/print/?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.open(printUrl, '_blank');
            });
        }
    }

    function loadInitialState(root) {
        state.reportUrl = root.dataset.reportUrl || '';
        state.dateFrom = root.dataset.dateFrom || state.dateFrom;
        state.dateTo = root.dataset.dateTo || state.dateTo;
        state.selectedNode = root.dataset.selectedNode || state.selectedNode;
    }

    function init() {
        const root = document.getElementById('creportsRoot');
        if (!root) {
            return;
        }

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

        if (POLL_INTERVAL_MS > 0) {
            setInterval(() => {
                if (state.shouldPoll) {
                    fetchAndRenderReport();
                }
            }, POLL_INTERVAL_MS);
        }
    }

    document.addEventListener('DOMContentLoaded', init);
})();