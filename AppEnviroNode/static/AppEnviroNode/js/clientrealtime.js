(function() {
    const DATA_ENDPOINT = '/api/realtime-data/';
    const REFRESH_INTERVAL_MS = 10000;
    const MAX_FEED_ITEMS = 15;

    const initialDataScript = document.getElementById('crealtime-initial-data');
    if (!initialDataScript) {
        return;
    }

    const parsePayload = () => {
        try {
            return JSON.parse(initialDataScript.textContent || '{}');
        } catch (error) {
            console.error('Unable to parse initial realtime payload', error);
            return {};
        }
    };

    const payload = parsePayload();
    const feedContainer = document.getElementById('crealtime-feed');
    const nodeTableBody = document.getElementById('crealtime-node-table-body');
    const alertList = document.getElementById('crealtime-alert-list');
    const syncTimeLabel = document.getElementById('crealtime-sync-time');
    const activeNodesLabel = document.getElementById('crealtime-active-nodes');
    const liveAqiLabel = document.getElementById('crealtime-live-aqi-val');
    const systemBadge = document.getElementById('crealtime-system-badge');
    const systemPulse = document.getElementById('crealtime-global-pulse');
    const alertCountLabel = document.getElementById('crealtime-alert-count');
    const chartCanvas = document.getElementById('crealtime-sparkline');
    const zoneSelect = document.getElementById('crealtime-zone-select');
    const filterButtons = Array.from(document.querySelectorAll('.crealtime-btn'));
    const autoRefreshToggle = document.getElementById('crealtime-auto-refresh');

    let isLive = true;
    let chartData = Array.isArray(payload.chart_values) ? payload.chart_values.slice() : [];
    if (chartData.length === 0) {
        chartData = Array.from({ length: 30 }, () => 40 + Math.round(Math.random() * 10));
    }

    const parseTimestamp = (value) => {
        if (!value) {
            return 0;
        }
        if (typeof value === 'number') {
            return value > 1e12 ? value : value * 1000;
        }
        if (/^\d+$/.test(value)) {
            return parseInt(value, 10) * 1000;
        }
        const parsed = Date.parse(value);
        return Number.isNaN(parsed) ? 0 : parsed;
    };

    const formatTimeAgo = (dateValue, shortFormat = false) => {
        const timestamp = parseTimestamp(dateValue);
        const diffInSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
        if (diffInSeconds < 60) return `${diffInSeconds}s${shortFormat ? '' : ' ago'}`;
        const diffInMinutes = Math.floor(diffInSeconds / 60);
        if (diffInMinutes < 60) return `${diffInMinutes}m${shortFormat ? '' : ' ago'}`;
        const diffInHours = Math.floor(diffInMinutes / 60);
        return `${diffInHours}h${shortFormat ? '' : ' ago'}`;
    };

    const getStatusDotClass = (status) => {
        switch ((status || '').toLowerCase()) {
            case 'active':
                return 'crealtime-dot-green';
            case 'inactive':
            case 'unregistered':
                return 'crealtime-dot-yellow';
            default:
                return 'crealtime-dot-red';
        }
    };

    const createFeedItemHtml = (event) => {
        const isCritical = event.severity === 'critical';
        const eventClass = isCritical ? 'crealtime-feed-critical' : '';
        const label = event.tag_label || (event.severity || 'INFO').toUpperCase();
        return `
            <div class="crealtime-feed-item ${eventClass}" data-node-id="${event.node_id || 'unknown'}" data-timestamp="${parseTimestamp(event.timestamp)}">
                <div class="crealtime-feed-icon ${event.bg_class || 'crealtime-bg-green'}">${event.icon || '✓'}</div>
                <div class="crealtime-feed-content">
                    <div class="crealtime-feed-header-row">
                        <span class="crealtime-tag ${event.tag_class || 'crealtime-tag-info'}">${label}</span>
                        <div class="crealtime-text-sm crealtime-font-medium">${event.title || 'Realtime event'}</div>
                    </div>
                    <div class="crealtime-text-xs crealtime-text-muted">${event.description || ''}</div>
                </div>
                <div class="crealtime-feed-time crealtime-mono crealtime-dynamic-time">Just now</div>
            </div>
        `;
    };

    const renderFeed = (feed = []) => {
        if (!feedContainer) return;
        feedContainer.innerHTML = feed.map(createFeedItemHtml).join('');
        updateDynamicTimes();
    };

    const createNodeRowHtml = (node) => {
        const statusClass = getStatusDotClass(node.status);
        const isCriticalRow = node.status !== 'active' || node.aqi === null || (node.aqi !== null && node.aqi > 100);
        const aqiValue = node.aqi !== null && node.aqi !== undefined ? node.aqi : '—';
        const zone = node.zone || 'Unknown';
        return `
            <tr data-node-id="${node.name || node.node_id || 'unknown'}" data-zone="${zone.toLowerCase().replace(/\s+/g, '-')}" data-status="${node.status || 'unknown'}" data-timestamp="${parseTimestamp(node.timestamp)}" class="${isCriticalRow ? 'crealtime-row-critical' : ''}">
                <td class="crealtime-mono crealtime-font-medium">${node.name || 'Unknown'}</td>
                <td class="crealtime-text-xs">${zone}</td>
                <td><span class="crealtime-dot ${statusClass}"></span></td>
                <td class="crealtime-mono">${aqiValue}</td>
                <td class="crealtime-text-xs crealtime-text-muted crealtime-dynamic-time">Just now</td>
                <td>
                    <div class="crealtime-action-group">
                        <div class="crealtime-action-btn-wrap" data-tooltip="Restart">
                            <button class="crealtime-action-btn">↻</button>
                        </div>
                        <div class="crealtime-action-btn-wrap" data-tooltip="Calibrate">
                            <button class="crealtime-action-btn">⚙</button>
                        </div>
                        <div class="crealtime-action-btn-wrap" data-tooltip="Flag Node">
                            <button class="crealtime-action-btn crealtime-flag">⚑</button>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    };

    const renderNodeTable = (nodes = []) => {
        if (!nodeTableBody) return;
        if (!nodes.length) {
            nodeTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="crealtime-text-xs crealtime-text-muted">No active node readings available.</td>
                </tr>
            `;
            return;
        }
        nodeTableBody.innerHTML = nodes.map(createNodeRowHtml).join('');
        updateDynamicTimes();
    };

    const createAlertHtml = (alert) => {
        const warningClass = alert.severity === 'warning' ? 'crealtime-warning' : '';
        const criticalClass = alert.severity === 'critical' ? 'crealtime-feed-critical' : '';
        const styleAttr = alert.severity === 'critical' ? ' style="color:var(--crealtime-red)"' : '';
        return `
            <div class="crealtime-alert-item ${warningClass} ${criticalClass}" data-node-id="${alert.node_name || 'unknown'}" data-timestamp="${parseTimestamp(alert.timestamp)}">
                <div>
                    <div class="crealtime-alert-msg"${styleAttr}>${alert.title || 'Alert'}</div>
                    <div class="crealtime-text-xs crealtime-text-muted">${alert.description || ''} <span class="crealtime-dynamic-time">Just now</span></div>
                </div>
                <button class="crealtime-alert-dismiss" aria-label="Dismiss">&times;</button>
            </div>
        `;
    };

    const renderAlerts = (alerts = []) => {
        if (!alertList) return;
        if (!alerts.length) {
            alertList.innerHTML = `
                <div class="crealtime-alert-item">
                    <div>
                        <div class="crealtime-alert-msg">No active alerts</div>
                        <div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div>
                    </div>
                </div>
            `;
            return;
        }
        alertList.innerHTML = alerts.map(createAlertHtml).join('');
        updateDynamicTimes();
        if (alertCountLabel) {
            alertCountLabel.textContent = `${alerts.length} Alerts`;
        }
    };

    const refreshSyncTime = () => {
        if (!syncTimeLabel) return;
        syncTimeLabel.textContent = 'Just now';
    };

    const updateSystemStatus = (nodes, averageAqi) => {
        if (!systemBadge || !systemPulse) return;
        const hasOffline = nodes.some((node) => node.status !== 'active');
        let status = 'GOOD';
        if (hasOffline || (averageAqi !== null && averageAqi > 100)) {
            status = 'CRITICAL';
        } else if (averageAqi !== null && averageAqi > 50) {
            status = 'DEGRADED';
        }
        const badgeClass = status === 'CRITICAL'
            ? 'crealtime-badge-critical'
            : status === 'DEGRADED'
                ? 'crealtime-badge-degraded'
                : 'crealtime-badge-good';
        const pulseClass = status === 'CRITICAL'
            ? 'crealtime-dot-red'
            : status === 'DEGRADED'
                ? 'crealtime-dot-yellow'
                : 'crealtime-dot-green';

        systemBadge.className = `crealtime-badge ${badgeClass}`;
        systemBadge.textContent = status;
        systemPulse.className = `crealtime-dot crealtime-pulse ${pulseClass}`;

        const banner = document.getElementById('crealtime-priority-banner');
        if (banner) {
            if (status === 'CRITICAL' && hasOffline) {
                banner.classList.add('crealtime-banner-active');
            } else {
                banner.classList.remove('crealtime-banner-active');
            }
        }
    };

    const computeAverageAqi = (nodes = []) => {
        const values = nodes
            .map((node) => Number(node.aqi))
            .filter((value) => !Number.isNaN(value) && value !== null);
        if (!values.length) {
            return null;
        }
        return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1));
    };

    const updateLiveAqi = (averageAqi) => {
        if (!liveAqiLabel) return;
        const displayValue = averageAqi !== null ? averageAqi.toFixed(1) : '—';
        liveAqiLabel.textContent = displayValue;
        if (averageAqi === null) {
            liveAqiLabel.style.color = 'var(--crealtime-text-main)';
            return;
        }
        if (averageAqi > 80) {
            liveAqiLabel.style.color = 'var(--crealtime-red)';
        } else if (averageAqi > 60) {
            liveAqiLabel.style.color = 'var(--crealtime-yellow)';
        } else {
            liveAqiLabel.style.color = 'var(--crealtime-green)';
        }
    };

    const updateDynamicTimes = () => {
        document.querySelectorAll('[data-timestamp]').forEach((element) => {
            const timestamp = parseTimestamp(element.getAttribute('data-timestamp'));
            const timeSpan = element.querySelector('.crealtime-dynamic-time');
            if (!timeSpan) return;
            const isAlert = element.classList.contains('crealtime-alert-item');
            timeSpan.textContent = formatTimeAgo(timestamp, isAlert);
        });
    };

    const addFeedEvent = (event) => {
        if (!feedContainer) return;
        const html = createFeedItemHtml(event);
        feedContainer.insertAdjacentHTML('afterbegin', html);
        while (feedContainer.children.length > MAX_FEED_ITEMS) {
            feedContainer.removeChild(feedContainer.lastElementChild);
        }
        updateDynamicTimes();
    };

    const buildChart = () => {
        if (!chartCanvas) return null;
        const ctx = chartCanvas.getContext('2d');
        const horizontalLinesPlugin = {
            id: 'horizontalLines',
            beforeDraw: (chart) => {
                const { ctx, chartArea: { top, bottom, left, right }, scales: { y } } = chart;
                ctx.save();
                const drawLine = (value, color) => {
                    const yPos = y.getPixelForValue(value);
                    if (yPos >= top && yPos <= bottom) {
                        ctx.beginPath();
                        ctx.setLineDash([4, 4]);
                        ctx.moveTo(left, yPos);
                        ctx.lineTo(right, yPos);
                        ctx.lineWidth = 1;
                        ctx.strokeStyle = color;
                        ctx.stroke();
                    }
                };
                drawLine(50, 'rgba(245, 158, 11, 0.6)');
                drawLine(100, 'rgba(239, 68, 68, 0.6)');
                ctx.restore();
            }
        };
        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: chartData.map((_, index) => index),
                datasets: [{
                    data: chartData,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'linear' },
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: {
                    x: { display: false },
                    y: {
                        display: true,
                        position: 'right',
                        grid: { color: '#f1f5f9', drawBorder: false },
                        border: { display: false },
                        ticks: { font: { size: 9, family: 'ui-monospace, monospace' }, color: '#94a3b8', maxTicksLimit: 4 },
                        suggestedMin: 20,
                        suggestedMax: 110,
                    },
                },
                layout: { padding: { left: -10, bottom: -10 } },
            },
            plugins: [horizontalLinesPlugin],
        });
        return chart;
    };

    const updateTrendIndicator = () => {
        const trendEl = document.getElementById('crealtime-trend-indicator');
        if (!trendEl) return;
        const recent = chartData.slice(-5);
        const start = recent[0] ?? recent[recent.length - 1] ?? 0;
        const end = recent[recent.length - 1] ?? 0;
        const diff = end - start;
        trendEl.className = 'crealtime-trend';
        if (diff > 2) {
            trendEl.innerHTML = 'Rising &uarr;';
            trendEl.classList.add('crealtime-trend-up');
        } else if (diff < -2) {
            trendEl.innerHTML = 'Falling &darr;';
            trendEl.classList.add('crealtime-trend-down');
        } else {
            trendEl.innerHTML = 'Stable &rarr;';
            trendEl.classList.add('crealtime-trend-stable');
        }
    };

    const refreshNodeTableStatus = (filter = 'all') => {
        if (!nodeTableBody) return;
        const rows = Array.from(nodeTableBody.querySelectorAll('tr[data-node-id]'));
        rows.forEach((row) => {
            const zone = (row.getAttribute('data-zone') || '').toLowerCase();
            const status = row.getAttribute('data-status');
            let isVisible = true;
            if (filter === 'online') {
                isVisible = status === 'active';
            } else if (filter === 'alerts') {
                const aqiCell = row.querySelector('td.crealtime-mono');
                const aqiValue = aqiCell ? Number(aqiCell.textContent) : NaN;
                isVisible = status !== 'active' || (!Number.isNaN(aqiValue) && aqiValue > 65);
            }
            if (zoneSelect && filter !== 'all') {
                const selectedZone = zoneSelect.value;
                if (selectedZone !== 'all') {
                    isVisible = isVisible && zone === selectedZone;
                }
            }
            row.style.display = isVisible ? '' : 'none';
        });
    };

    const filterByZone = () => {
        refreshNodeTableStatus(filterButtons.find((button) => button.classList.contains('crealtime-active'))?.textContent.toLowerCase() || 'all');
    };

    const updateChartData = (value) => {
        if (chartInstance === null || value === null || Number.isNaN(value)) return;
        chartData.push(value);
        chartData.shift();
        chartInstance.data.datasets[0].data = chartData;
        chartInstance.update();
        updateTrendIndicator();
    };

    const addRealtimeFeedFromNode = (node) => {
        const averageAqi = computeAverageAqi([node]);
        addFeedEvent({
            node_id: node.name,
            icon: node.status === 'active' ? '✓' : '!',
            bg_class: node.status === 'active' ? 'crealtime-bg-green' : 'crealtime-bg-yellow',
            tag_class: node.status === 'active' ? 'crealtime-tag-info' : 'crealtime-tag-warn',
            tag_label: node.status === 'active' ? 'INFO' : 'WARN',
            title: `${node.name} updated`,
            description: `Current AQI ${node.aqi !== null ? node.aqi : '—'} in ${node.zone || 'Unknown'}.`, 
            severity: node.status === 'active' ? 'info' : 'warning',
            timestamp: Date.now(),
        });
    };

    const refreshRealtimeData = async () => {
        try {
            const response = await fetch(DATA_ENDPOINT, { cache: 'no-store' });
            if (!response.ok) {
                return;
            }
            const json = await response.json();
            if (!json || json.status !== 'success' || !Array.isArray(json.data)) {
                return;
            }
            const nodes = json.data.map((item) => ({
                name: item.name,
                zone: item.location || 'Unknown',
                status: item.status || 'unknown',
                aqi: item.aqi !== null ? item.aqi : null,
                timestamp: item.timestamp,
                node_id: item.node_id,
            }));
            renderNodeTable(nodes);
            const averageAqi = computeAverageAqi(nodes);
            updateLiveAqi(averageAqi);
            updateSystemStatus(nodes, averageAqi);
            if (!Number.isNaN(averageAqi) && averageAqi !== null) {
                updateChartData(averageAqi);
            }
            refreshSyncTime();
            if (nodes.length) {
                addRealtimeFeedFromNode(nodes[0]);
            }
            filterByZone();
        } catch (error) {
            console.error('Realtime refresh failed', error);
        }
    };

    const highlightElement = (nodeId) => {
        document.querySelectorAll('.crealtime-is-highlighted').forEach((element) => {
            element.classList.remove('crealtime-is-highlighted');
        });
        const targets = document.querySelectorAll(`[data-node-id="${nodeId}"]`);
        targets.forEach((element) => {
            void element.offsetWidth;
            element.classList.add('crealtime-is-highlighted');
            const scrollable = element.closest('.crealtime-scroll');
            if (scrollable) {
                scrollable.scrollTo({
                    top: element.offsetTop - scrollable.offsetTop - 20,
                    behavior: 'smooth',
                });
            }
        });
    };

    const chartInstance = buildChart();

    renderFeed(Array.isArray(payload.feed) ? payload.feed : []);
    renderNodeTable(Array.isArray(payload.nodes) ? payload.nodes : []);
    renderAlerts(Array.isArray(payload.alerts) ? payload.alerts : []);
    updateLiveAqi(payload.live_aqi !== null ? Number(payload.live_aqi) : null);
    updateSystemStatus(Array.isArray(payload.nodes) ? payload.nodes : [], payload.live_aqi);
    updateTrendIndicator();
    updateDynamicTimes();

    if (activeNodesLabel) {
        activeNodesLabel.textContent = `${payload.active_nodes || 0}/${payload.total_nodes || 0}`;
    }

    filterButtons.forEach((button) => {
        button.addEventListener('click', (event) => {
            filterButtons.forEach((btn) => btn.classList.remove('crealtime-active'));
            event.target.classList.add('crealtime-active');
            refreshNodeTableStatus(event.target.textContent.toLowerCase());
        });
    });

    if (zoneSelect) {
        zoneSelect.addEventListener('change', filterByZone);
    }

    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('click', () => {
            isLive = !isLive;
            autoRefreshToggle.classList.toggle('crealtime-off', !isLive);
        });
    }

    document.getElementById('crealtime-alert-list')?.addEventListener('click', (event) => {
        if (event.target.classList.contains('crealtime-alert-dismiss')) {
            const alertItem = event.target.closest('.crealtime-alert-item');
            if (!alertItem) return;
            alertItem.style.opacity = '0';
            setTimeout(() => {
                alertItem.remove();
                const remaining = alertList.querySelectorAll('.crealtime-alert-item').length;
                if (alertCountLabel) {
                    alertCountLabel.textContent = `${remaining} Alerts`;
                }
            }, 200);
        }
    });

    document.addEventListener('click', (event) => {
        const actionable = event.target.closest('.crealtime-feed-item, tr[data-node-id]');
        if (!actionable || event.target.closest('.crealtime-action-btn')) {
            return;
        }
        const nodeId = actionable.getAttribute('data-node-id');
        if (nodeId) {
            highlightElement(nodeId);
        }
    });

    setInterval(() => {
        updateDynamicTimes();
        if (isLive) {
            void refreshRealtimeData();
        }
    }, REFRESH_INTERVAL_MS);
})();
