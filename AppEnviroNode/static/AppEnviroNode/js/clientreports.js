(function () {
    'use strict';

    const REPORT_TYPES = ['24hrs', 'Weekly', 'Monthly', 'Custom'];
    const DEFAULT_NODE = { id: 'all', label: 'All Nodes' };
    const POLL_INTERVAL_MS = 300000;
    const DEBOUNCE_DELAY_MS = 300;

    const state = {
        reportUrl: '',
        reportType: '24hrs',
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
        lastNodeOptionsHash: '',
        isRequestPending: false,
        requestAbort: null,
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
        // State key based on report_type and node filter only
        // Custom mode includes dates since they're user-selected
        if (state.reportType === 'Custom') {
            return `${state.reportType}|${state.dateFrom}|${state.dateTo}|${state.selectedNode}`;
        }
        return `${state.reportType}|${state.selectedNode}`;
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
        
        const currentButtons = elements.reportTypeContainer.querySelectorAll('.creports-segmented__btn');
        
        // Check if buttons already match current state
        if (currentButtons.length === REPORT_TYPES.length) {
            let allMatch = true;
            for (let i = 0; i < currentButtons.length; i++) {
                const isActive = currentButtons[i].textContent === state.reportType;
                const hasActiveClass = currentButtons[i].classList.contains('is-active');
                if (isActive !== hasActiveClass) {
                    allMatch = false;
                    break;
                }
            }
            if (allMatch) return;
        }
        
        const frag = document.createDocumentFragment();
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
            frag.appendChild(button);
        });
        elements.reportTypeContainer.innerHTML = '';
        elements.reportTypeContainer.appendChild(frag);
    }

    function renderNodeOptions(newNodes) {
        if (!elements.nodeDropdownMenu) return;
        
        const nodeList = [DEFAULT_NODE].concat(newNodes || []);
        
        // Simple check: compare lengths and first node
        const currentOptions = elements.nodeDropdownMenu.querySelectorAll('.creports-dropdown-menu__option');
        if (currentOptions.length === nodeList.length && currentOptions.length > 0) {
            const firstOptionText = currentOptions[0].textContent.trim();
            const newFirstText = (nodeList[0].label || '').trim();
            if (firstOptionText === newFirstText) {
                const activeNode = state.nodes.find((item) => item.id === state.selectedNode) || DEFAULT_NODE;
                if (elements.nodeDisplay) elements.nodeDisplay.textContent = activeNode.label;
                return;
            }
        }
        
        state.nodes = nodeList;
        
        const frag = document.createDocumentFragment();
        state.nodes.forEach((node) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `creports-dropdown-menu__option ${state.selectedNode === node.id ? 'is-active' : ''}`;
            button.textContent = node.label;
            button.addEventListener('click', () => {
                setSelectedNode(node.id, node.label);
                closeDropdowns();
            });
            frag.appendChild(button);
        });
        elements.nodeDropdownMenu.innerHTML = '';
        elements.nodeDropdownMenu.appendChild(frag);

        const activeNode = state.nodes.find((item) => item.id === state.selectedNode) || DEFAULT_NODE;
        if (elements.nodeDisplay) {
            elements.nodeDisplay.textContent = activeNode.label;
        }
    }

    function setReportType(type) {
        if (state.reportType === type) return;
        
        state.reportType = type;
        closeDropdowns();

        renderReportTypeButtons();
        
        // For preset types (24hrs, Weekly, Monthly), clear manual dates
        // Backend will compute the rolling window
        if (type !== 'Custom') {
            state.dateFrom = '';
            state.dateTo = '';
            updateDateInputs();
            updateDateDisplays();
            triggerFetch();
            return;
        }
        
        // For Custom mode, open date picker
        updateDateInputs();
        updateDateDisplays();
        if (elements.dateDropdownMenu) {
            elements.dateDropdownMenu.classList.add('is-open');
        }
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
        
        if (!Array.isArray(labels) || !Array.isArray(values)) {
            labels = [];
            values = [];
        }
        
        const currentLabels = state.chartInstance.data.labels || [];
        let labelsChanged = currentLabels.length !== labels.length;
        if (!labelsChanged) {
            for (let i = 0; i < labels.length; i++) {
                if (currentLabels[i] !== labels[i]) {
                    labelsChanged = true;
                    break;
                }
            }
        }
        
        if (labelsChanged) {
            state.chartInstance.data.labels = labels;
        }
        
        const currentData = state.chartInstance.data.datasets[0].data || [];
        let dataChanged = currentData.length !== values.length;
        if (!dataChanged) {
            for (let i = 0; i < values.length; i++) {
                if (currentData[i] !== values[i]) {
                    dataChanged = true;
                    break;
                }
            }
        }
        
        if (dataChanged) {
            state.chartInstance.data.datasets[0].data = values;
        }
        
        if (labelsChanged || dataChanged) {
            state.chartInstance.update('none');
        }
    }

    function setMetricText(element, value) {
        if (!element) return;
        const newText = value != null ? String(value) : '-';
        if (element.textContent !== newText) {
            element.textContent = newText;
        }
    }

    function renderListItems(container, items, styleClass, bulletColor, storageKey) {
        if (!container) return;
        
        // Simplified check: just compare item count and first item
        const currentItems = container.querySelectorAll('.creports-list__item');
        const itemsValid = Array.isArray(items) && items.length > 0;
        
        if (itemsValid && currentItems.length === items.length && currentItems.length > 0) {
            const firstItemText = currentItems[0].textContent.trim();
            const newFirstItemText = (items[0] || '').trim();
            if (firstItemText === newFirstItemText) {
                return; // No update needed
            }
        }
        
        const frag = document.createDocumentFragment();
        if (!itemsValid) {
            const item = document.createElement('li');
            item.className = styleClass;
            item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>No data available.</span>`;
            frag.appendChild(item);
        } else {
            items.forEach((text) => {
                const item = document.createElement('li');
                item.className = styleClass;
                item.innerHTML = `<div class="creports-list__bullet" style="background-color: ${bulletColor}"></div><span>${text}</span>`;
                frag.appendChild(item);
            });
        }
        container.innerHTML = '';
        container.appendChild(frag);
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
        if (!state.reportUrl) return;
        if (state.isFetching) return;
        if (!hasStateChanged()) return;
        
        state.isFetching = true;
        const currentStateKey = getStateKey();

        const url = new URL(state.reportUrl, window.location.origin);
        
        // Always send report_type
        url.searchParams.set('report_type', state.reportType);
        
        // Send dates only for Custom reports
        if (state.reportType === 'Custom') {
            url.searchParams.set('date_from', state.dateFrom);
            url.searchParams.set('date_to', state.dateTo);
        }
        
        // Send node filter
        if (state.selectedNode !== 'all') {
            url.searchParams.set('node', state.selectedNode);
        }

        try {
            const data = await fetchJson(url.toString());
            
            if (getStateKey() !== currentStateKey) {
                state.isFetching = false;
                return;
            }
            
            state.lastFetchState = currentStateKey;
            if (data.nodes && Array.isArray(data.nodes)) {
                renderNodeOptions(data.nodes);
            }
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
        
        // Prevent excessive requests - minimum 300ms between attempts
        debouncedFetch = setTimeout(() => {
            if (!state.isFetching && hasStateChanged()) {
                fetchAndRenderReport();
            }
        }, DEBOUNCE_DELAY_MS);
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

        if (elements.goodPctBar && (elements.goodPctBar.style.width !== `${data.good_pct}%` || elements.goodPctBar.textContent !== `${data.good_pct}%`)) {
            elements.goodPctBar.style.width = `${data.good_pct}%`;
            elements.goodPctBar.textContent = `${data.good_pct}%`;
        }
        if (elements.moderatePctBar && (elements.moderatePctBar.style.width !== `${data.moderate_pct}%` || elements.moderatePctBar.textContent !== `${data.moderate_pct}%`)) {
            elements.moderatePctBar.style.width = `${data.moderate_pct}%`;
            elements.moderatePctBar.textContent = `${data.moderate_pct}%`;
        }
        if (elements.unhealthyPctBar && (elements.unhealthyPctBar.style.width !== `${data.unhealthy_pct}%` || elements.unhealthyPctBar.textContent !== `${data.unhealthy_pct}%`)) {
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
        
        if (state.reportType !== data.report_type) {
            state.reportType = data.report_type || state.reportType;
            renderReportTypeButtons();
        }
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
                const url = `${window.location.origin}/export/pdf/?report_type=${encodeURIComponent(state.reportType)}&date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = url;
            });
        }

        if (elements.exportCsvBtn) {
            elements.exportCsvBtn.addEventListener('click', () => {
                const url = `${window.location.origin}/export/csv/?report_type=${encodeURIComponent(state.reportType)}&date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.location.href = url;
            });
        }

        if (elements.printBtn) {
            elements.printBtn.addEventListener('click', () => {
                const url = `${window.location.origin}/export/print/?report_type=${encodeURIComponent(state.reportType)}&date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}&node=${encodeURIComponent(state.selectedNode)}`;
                window.open(url, '_blank');
            });
        }
    }

    function loadInitialState(root) {
        state.reportUrl = root.dataset.reportUrl || '';
        
        // Only set dates if explicitly provided AND for Custom reports
        if (root.dataset.dateFrom && root.dataset.dateTo && root.dataset.reportType === 'Custom') {
            state.dateFrom = root.dataset.dateFrom;
            state.dateTo = root.dataset.dateTo;
            state.reportType = 'Custom';
        } else {
            // For presets, NEVER set dates initially
            state.dateFrom = '';
            state.dateTo = '';
            state.reportType = '24hrs';
        }
        
        state.selectedNode = root.dataset.selectedNode || 'all';
        state.lastFetchState = null;
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
        renderReportTypeButtons();
        updateDateInputs();
        updateDateDisplays();
        attachEventListeners();
        
        state.lastFetchState = null;
        fetchAndRenderReport();

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }

        setupPolling();
    }

    document.addEventListener('DOMContentLoaded', init);
})();