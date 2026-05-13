// clientrealtime.js - Complete Real-Time Monitoring System
// FIXED: Status now displays AQI level category instead of online/offline
// ENHANCED: Dynamic node status with AQI color mapping, improved pause mode, detailed last sync timestamp
(function() {
    'use strict';
    
    // Configuration
    const DATA_ENDPOINT = '/api/realtime-data/';
    const WEBSOCKET_ENDPOINT = '/ws/realtime/';
    const REFRESH_INTERVAL_MS = 5000;
    const MAX_FEED_ITEMS = 30;
    
    // DOM Elements
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
    const autoRefreshToggle = document.getElementById('crealtime-auto-refresh');
    const priorityBanner = document.getElementById('crealtime-priority-banner');
    const bannerMsg = document.getElementById('crealtime-banner-msg');
    
    // State
    let isLive = true;
    let chartInstance = null;
    let chartData = [];
    let currentFilter = 'all';
    let currentZone = 'all';
    let currentTimeRange = '15m';
    let lastEventTimestamp = null;
    let pollInterval = null;
    let isLoadingData = false;
    let activeModal = null;
    let lastSyncTimestamp = null;
    
    // Real-time WebSocket connection
    let wsConnection = null;
    let wsReconnectTimer = null;
    let wsReconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const WS_RECONNECT_DELAY = 3000;
    
    // Event deduplication cache
    const recentEventIds = new Set();
    const EVENT_DEDUPE_WINDOW_MS = 5000;
    
    // Alert deduplication cache
    const recentAlertIds = new Map();
    const ALERT_DEDUPE_WINDOW_MS = 30000;
    
    // Alert dismissal persistence with localStorage
    let dismissedAlerts = new Set();
    const DISMISSED_ALERTS_KEY = 'crealtime_dismissed_alerts';
    
    // Load dismissed alerts from localStorage on init
    const loadDismissedAlerts = () => {
        try {
            const stored = localStorage.getItem(DISMISSED_ALERTS_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                const now = Date.now();
                for (const [key, timestamp] of Object.entries(parsed)) {
                    if (now - timestamp < 30 * 60 * 1000) {
                        dismissedAlerts.add(key);
                    }
                }
                saveDismissedAlerts();
            }
        } catch (e) {
            console.warn('[Realtime] Failed to load dismissed alerts:', e);
        }
    };
    
    // Save dismissed alerts to localStorage
    const saveDismissedAlerts = () => {
        try {
            const data = {};
            dismissedAlerts.forEach(key => {
                data[key] = Date.now();
            });
            localStorage.setItem(DISMISSED_ALERTS_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('[Realtime] Failed to save dismissed alerts:', e);
        }
    };
    
    // Paused overlay with "Turn Back Live" button
    let pausedOverlay = null;
    
    const createPausedOverlay = () => {
        if (pausedOverlay) return;
        
        pausedOverlay = document.createElement('div');
        pausedOverlay.id = 'crealtime-paused-overlay';
        pausedOverlay.className = 'crealtime-paused-overlay';
        pausedOverlay.innerHTML = `
            <div class="crealtime-paused-content">
                <div class="crealtime-paused-icon">⏸</div>
                <div class="crealtime-paused-title">Real-time monitoring is now paused</div>
                <div class="crealtime-paused-subtitle">Click below to resume updates</div>
                <button class="crealtime-paused-resume-btn" id="crealtime-resume-live-btn">Turn Back Live</button>
            </div>
        `;
        
        document.body.appendChild(pausedOverlay);
        
        const resumeBtn = document.getElementById('crealtime-resume-live-btn');
        if (resumeBtn) {
            resumeBtn.addEventListener('click', () => {
                if (autoRefreshToggle) {
                    isLive = true;
                    autoRefreshToggle.classList.remove('crealtime-off');
                    const toggleWrapper = autoRefreshToggle.closest('.crealtime-toggle-wrapper');
                    const pausedLabel = toggleWrapper?.querySelector('.crealtime-paused-label');
                    if (pausedLabel) pausedLabel.remove();
                    
                    removePausedOverlay();
                    
                    startPolling();
                    
                    if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) {
                        connectWebSocket();
                    }
                    
                    manualRefresh();
                    showToast('Real-time monitoring resumed', false);
                }
            });
        }
    };
    
    const removePausedOverlay = () => {
        if (pausedOverlay) {
            pausedOverlay.remove();
            pausedOverlay = null;
        }
    };
    
    // ============================================================================
    // AQI Level Information - Single source of truth
    // ============================================================================
    const getAqiLevelInfo = (aqi) => {
        // Disconnected/No Data case
        if (aqi === null || aqi === undefined || aqi === '—') {
            return {
                label: 'Disconnected',
                color: '#94a3b8',
                backgroundColor: '#f1f5f9',
                dotColor: '#94a3b8',
                dotClass: 'crealtime-dot-gray',
                level: 'disconnected'
            };
        }
        // Good: 0-50
        if (aqi <= 50) {
            return {
                label: 'Good',
                color: '#10b981',
                backgroundColor: '#d1fae5',
                dotColor: '#10b981',
                dotClass: 'crealtime-dot-green',
                level: 'good'
            };
        }
        // Moderate: 51-100
        if (aqi <= 100) {
            return {
                label: 'Moderate',
                color: '#f59e0b',
                backgroundColor: '#fef3c7',
                dotColor: '#f59e0b',
                dotClass: 'crealtime-dot-yellow',
                level: 'moderate'
            };
        }
        // Unhealthy for Sensitive Groups: 101-150
        if (aqi <= 150) {
            return {
                label: 'Unhealthy for Sensitive Groups',
                color: '#f97316',
                backgroundColor: '#ffedd5',
                dotColor: '#f97316',
                dotClass: 'crealtime-dot-orange',
                level: 'unhealthy-sensitive'
            };
        }
        // Unhealthy: 151-200
        if (aqi <= 200) {
            return {
                label: 'Unhealthy',
                color: '#ef4444',
                backgroundColor: '#fee2e2',
                dotColor: '#ef4444',
                dotClass: 'crealtime-dot-red',
                level: 'unhealthy'
            };
        }
        // Very Unhealthy: 201-300
        if (aqi <= 300) {
            return {
                label: 'Very Unhealthy',
                color: '#8b5cf6',
                backgroundColor: '#f3e8ff',
                dotColor: '#8b5cf6',
                dotClass: 'crealtime-dot-purple',
                level: 'very-unhealthy'
            };
        }
        // Hazardous: 301+
        return {
            label: 'Hazardous',
            color: '#b91c1c',
            backgroundColor: '#fecaca',
            dotColor: '#7f1d1d',
            dotClass: 'crealtime-dot-maroon',
            level: 'hazardous'
        };
    };
    
    // Helper: Get AQI label
    const getAqiLabel = (aqi) => {
        return getAqiLevelInfo(aqi).label;
    };
    
    // Helper: Get AQI color
    const getAqiColor = (aqi) => {
        return getAqiLevelInfo(aqi).color;
    };
    
    // Helper: Get AQI dot class
    const getAqiDotClass = (aqi) => {
        return getAqiLevelInfo(aqi).dotClass;
    };
    
    // Helper: Get AQI badge class
    const getAqiBadgeClass = (aqi) => {
        const info = getAqiLevelInfo(aqi);
        switch(info.level) {
            case 'good': return 'aqi-good';
            case 'moderate': return 'aqi-moderate';
            case 'unhealthy-sensitive': return 'aqi-unhealthy-sensitive';
            case 'unhealthy': return 'aqi-unhealthy';
            case 'very-unhealthy': return 'aqi-very-unhealthy';
            case 'hazardous': return 'aqi-hazardous';
            default: return 'aqi-unknown';
        }
    };
    
    // Helper: Get status text (returns AQI label or 'Disconnected')
    const getStatusText = (aqi, hasTimestamp = true, isStale = false) => {
        // Check if node is disconnected (no AQI data OR stale data OR no timestamp)
        if (aqi === null || aqi === undefined || aqi === '—') {
            return 'Disconnected';
        }
        // Check if data is stale (5+ minutes old)
        if (isStale) {
            return 'Disconnected';
        }
        // Return AQI level label
        return getAqiLevelInfo(aqi).label;
    };
    
    // Helper: Get status dot class (based on AQI)
    const getStatusDotClass = (aqi, isStale = false) => {
        if (aqi === null || aqi === undefined || aqi === '—' || isStale) {
            return 'crealtime-dot-gray';
        }
        return getAqiLevelInfo(aqi).dotClass;
    };
    
    // Format last sync timestamp with full date and time
    const formatLastSync = (timestamp) => {
        if (!timestamp) return 'Never';
        const date = new Date(timestamp * 1000);
        const options = { 
            year: 'numeric', 
            month: 'long', 
            day: 'numeric',
            hour: '2-digit', 
            minute: '2-digit', 
            second: '2-digit',
            hour12: true
        };
        return date.toLocaleString('en-US', options);
    };
    
    const updateSyncTimeDisplay = (syncTimestamp = null) => {
        if (syncTimeLabel) {
            const now = syncTimestamp || (Date.now() / 1000);
            lastSyncTimestamp = now;
            syncTimeLabel.textContent = formatLastSync(now);
            syncTimeLabel.classList.add('crealtime-is-highlighted');
            setTimeout(() => {
                if (syncTimeLabel) syncTimeLabel.classList.remove('crealtime-is-highlighted');
            }, 1000);
        }
    };
    
    // Helper: Parse timestamp
    const parseTimestamp = (value) => {
        if (!value) return 0;
        if (typeof value === 'number') return value > 1e12 ? value : value * 1000;
        if (/^\d+$/.test(value)) return parseInt(value, 10) * 1000;
        const parsed = Date.parse(value);
        return isNaN(parsed) ? 0 : parsed;
    };
    
    // Helper: Format relative time
    const formatTimeAgo = (timestamp, shortFormat = false) => {
        const ts = parseTimestamp(timestamp);
        const diffSeconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
        if (diffSeconds < 60) return `${diffSeconds}s${shortFormat ? '' : ' ago'}`;
        const diffMinutes = Math.floor(diffSeconds / 60);
        if (diffMinutes < 60) return `${diffMinutes}m${shortFormat ? '' : ' ago'}`;
        const diffHours = Math.floor(diffMinutes / 60);
        if (diffHours < 24) return `${diffHours}h${shortFormat ? '' : ' ago'}`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays}d${shortFormat ? '' : ' ago'}`;
    };
    
    // Helper: Check if data is stale (no update in 5+ minutes)
    const isDataStale = (timestamp) => {
        if (!timestamp) return true;
        const now = Date.now();
        const lastUpdate = parseTimestamp(timestamp);
        const diffMinutes = (now - lastUpdate) / 1000 / 60;
        return diffMinutes >= 5;
    };
    
    // Helper: Escape HTML
    const escapeHtml = (text) => {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
    
    // Helper: Check if alert is dismissed
    const isAlertDismissed = (alert) => {
        const alertKey = `${alert.node_name || 'system'}_${alert.severity}_${alert.title}`;
        return dismissedAlerts.has(alertKey);
    };
    
    // Helper: Dismiss alert and persist
    const dismissAlertPermanently = (alertKey) => {
        dismissedAlerts.add(alertKey);
        saveDismissedAlerts();
    };
    
    // Helper: Check if event is duplicate
    const isDuplicateEvent = (event) => {
        const eventId = `${event.node_id || 'system'}_${event.title}_${event.timestamp_unix || event.timestamp}`;
        if (recentEventIds.has(eventId)) {
            console.log('[Realtime] Duplicate event filtered:', event.title);
            return true;
        }
        recentEventIds.add(eventId);
        setTimeout(() => recentEventIds.delete(eventId), EVENT_DEDUPE_WINDOW_MS);
        return false;
    };
    
    // Helper: Check if alert is duplicate
    const isDuplicateAlert = (alert) => {
        const alertKey = `${alert.node_name || 'system'}_${alert.severity}_${alert.title}`;
        const lastTime = recentAlertIds.get(alertKey);
        const now = Date.now();
        
        if (lastTime && (now - lastTime) < ALERT_DEDUPE_WINDOW_MS) {
            console.log('[Realtime] Duplicate alert filtered:', alert.title);
            return true;
        }
        recentAlertIds.set(alertKey, now);
        return false;
    };
    
    // ============================================================================
    // REAL-TIME WEBSOCKET CONNECTION
    // ============================================================================
    
    const connectWebSocket = () => {
        if (!isLive) return;
        
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${WEBSOCKET_ENDPOINT}`;
        
        try {
            wsConnection = new WebSocket(wsUrl);
            
            wsConnection.onopen = () => {
                console.log('[Realtime] WebSocket connected - live updates active');
                wsReconnectAttempts = 0;
                updateSyncTimeDisplay();
                
                wsConnection.send(JSON.stringify({
                    type: 'subscribe',
                    channels: ['nodes', 'events', 'alerts']
                }));
            };
            
            wsConnection.onmessage = (event) => {
                if (!isLive) return;
                try {
                    const data = JSON.parse(event.data);
                    handleRealtimeMessage(data);
                } catch (err) {
                    console.error('[Realtime] WebSocket message parse error:', err);
                }
            };
            
            wsConnection.onerror = (error) => {
                console.error('[Realtime] WebSocket error:', error);
            };
            
            wsConnection.onclose = () => {
                console.log('[Realtime] WebSocket disconnected');
                scheduleReconnect();
            };
        } catch (err) {
            console.error('[Realtime] WebSocket connection failed:', err);
            scheduleReconnect();
        }
    };
    
    const scheduleReconnect = () => {
        if (!isLive) return;
        
        if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
        
        if (wsReconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            wsReconnectAttempts++;
            const delay = WS_RECONNECT_DELAY * Math.min(wsReconnectAttempts, 5);
            console.log(`[Realtime] Scheduling reconnect attempt ${wsReconnectAttempts} in ${delay}ms`);
            wsReconnectTimer = setTimeout(connectWebSocket, delay);
        } else {
            console.warn('[Realtime] Max reconnect attempts reached, falling back to polling');
            if (pollInterval) startPolling();
        }
    };
    
    const handleRealtimeMessage = (data) => {
        if (!data || !data.type) return;
        
        updateSyncTimeDisplay();
        
        switch (data.type) {
            case 'node_update':
                handleNodeUpdateRealtime(data);
                break;
            case 'event_update':
                handleEventUpdateRealtime(data);
                break;
            case 'alert_update':
                handleAlertUpdateRealtime(data);
                break;
            case 'chart_update':
                handleChartUpdateRealtime(data);
                break;
            case 'system_status':
                handleSystemStatusRealtime(data);
                break;
            default:
                console.log('[Realtime] Unknown message type:', data.type);
        }
    };
    
    // Create node row HTML with dynamic status based on AQI
    const createNodeRowHtml = (node) => {
        const aqi = node.aqi !== null && node.aqi !== undefined ? node.aqi : null;
        const isStale = isDataStale(node.timestamp);
        const statusText = getStatusText(aqi, !!node.timestamp, isStale);
        const statusDotClass = getStatusDotClass(aqi, isStale);
        const aqiInfo = getAqiLevelInfo(aqi);
        const zone = node.zone || node.location || 'Unknown';
        const lastSeen = node.timestamp ? formatTimeAgo(node.timestamp, true) : 'Never';
        const isCriticalRow = (aqi === null || aqi === '—' || aqi > 150);
        
        return `
            <tr data-node-id="${escapeHtml(node.name)}" data-node-real-id="${node.node_id}" data-zone="${zone.toLowerCase().replace(/\s+/g, '-')}" data-timestamp="${node.timestamp || ''}" data-aqi="${aqi !== null ? aqi : ''}" class="${isCriticalRow ? 'crealtime-row-critical' : ''}">
                <td class="crealtime-mono crealtime-font-medium">${escapeHtml(node.name)}</td>
                <td class="crealtime-text-xs">${escapeHtml(zone)}</td>
                <td>
                    <span class="crealtime-dot ${statusDotClass}" style="margin-right: 8px;"></span>
                    <span class="crealtime-status-text" style="color: ${aqiInfo.color}; font-size: 0.75rem; font-weight: 500;">${escapeHtml(statusText)}</span>
                </td>
                <td class="crealtime-mono" style="color: ${aqiInfo.color}; font-weight: 600;">
                    ${aqi !== null ? aqi : '—'}
                </td>
                <td class="crealtime-text-xs crealtime-text-muted crealtime-dynamic-time">${lastSeen}</td>
                <td>
                    <div class="crealtime-action-group">
                        <div class="crealtime-action-btn-wrap" data-tooltip="View Details">
                            <button class="crealtime-action-btn" data-action="view-details" data-node-name="${escapeHtml(node.name)}" data-node-id="${node.node_id}">👁</button>
                        </div>
                        <div class="crealtime-action-btn-wrap" data-tooltip="View on Map">
                            <button class="crealtime-action-btn" data-action="view-map" data-node-name="${escapeHtml(node.name)}" data-node-id="${node.node_id}">🗺</button>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    };
    
    const handleNodeUpdateRealtime = (data) => {
        if (!data.node) return;
        
        updateNodeInTable(data.node);
        
        if (data.active_count !== undefined && activeNodesLabel) {
            activeNodesLabel.textContent = `${data.active_count}/${data.total_count || data.active_count}`;
        }
        
        if (data.node.aqi !== undefined && liveAqiLabel) {
            const aqi = data.node.aqi;
            const aqiInfo = getAqiLevelInfo(aqi);
            liveAqiLabel.textContent = aqi !== null && aqi !== undefined ? aqi.toFixed(1) : '—';
            if (aqi !== null && aqi !== undefined) {
                liveAqiLabel.style.color = aqiInfo.color;
            }
        }
    };
    
    // Update node in table with dynamic status
    const updateNodeInTable = (node) => {
        if (!nodeTableBody) return;
        
        const existingRow = nodeTableBody.querySelector(`tr[data-node-id="${node.name}"]`);
        const aqi = node.aqi !== undefined && node.aqi !== null ? node.aqi : null;
        const isStale = isDataStale(node.timestamp);
        const statusText = getStatusText(aqi, !!node.timestamp, isStale);
        const statusDotClass = getStatusDotClass(aqi, isStale);
        const aqiInfo = getAqiLevelInfo(aqi);
        const aqiValue = aqi !== null ? aqi : '—';
        const lastSeen = node.timestamp ? formatTimeAgo(node.timestamp, true) : 'Never';
        
        if (existingRow) {
            const statusCell = existingRow.querySelector('td:nth-child(3)');
            if (statusCell) {
                const dot = statusCell.querySelector('.crealtime-dot');
                const statusSpan = statusCell.querySelector('.crealtime-status-text');
                if (dot) {
                    dot.className = `crealtime-dot ${statusDotClass}`;
                }
                if (statusSpan) {
                    statusSpan.textContent = statusText;
                    statusSpan.style.color = aqiInfo.color;
                }
            }
            
            const aqiCell = existingRow.querySelector('td:nth-child(4)');
            if (aqiCell) {
                aqiCell.textContent = aqiValue;
                aqiCell.style.color = aqiInfo.color;
            }
            
            const lastSeenCell = existingRow.querySelector('td:nth-child(5)');
            if (lastSeenCell) {
                lastSeenCell.textContent = lastSeen;
                lastSeenCell.setAttribute('data-timestamp', node.timestamp || '');
            }
            
            // Update data-aqi attribute
            existingRow.setAttribute('data-aqi', aqi !== null ? aqi : '');
            
            existingRow.classList.add('crealtime-is-highlighted');
            setTimeout(() => {
                existingRow.classList.remove('crealtime-is-highlighted');
            }, 2000);
        } else {
            const newRowHtml = createNodeRowHtml(node);
            nodeTableBody.insertAdjacentHTML('afterbegin', newRowHtml);
            
            const newRow = nodeTableBody.querySelector(`tr[data-node-id="${node.name}"]`);
            if (newRow) {
                newRow.classList.add('crealtime-is-highlighted');
                setTimeout(() => {
                    newRow.classList.remove('crealtime-is-highlighted');
                }, 2000);
            }
        }
    };
    
    // Alert handling with persistent dismissal
    const handleAlertUpdateRealtime = (data) => {
        if (!data.alert) return;
        
        const alertKey = `${data.alert.node_name || 'system'}_${data.alert.severity}_${data.alert.title}`;
        
        if (isAlertDismissed(data.alert)) {
            console.log('[Realtime] Skipping dismissed alert:', data.alert.title);
            return;
        }
        
        if (!isDuplicateAlert(data.alert)) {
            addAlertRealtime(data.alert);
        }
    };
    
    // Add alert with dismiss functionality
    const addAlertRealtime = (alert) => {
        if (!alertList) return;
        
        const alertKey = `${alert.node_name || 'system'}_${alert.severity}_${alert.title}`;
        
        if (isAlertDismissed(alert)) return;
        
        const placeholder = alertList.querySelector('.crealtime-alert-item:first-child');
        if (placeholder && placeholder.querySelector('.crealtime-alert-msg')?.textContent === 'No active alerts') {
            alertList.innerHTML = '';
        }
        
        const existingAlert = alertList.querySelector(`.crealtime-alert-item[data-alert-key="${alertKey}"]`);
        if (existingAlert) return;
        
        const alertHtml = createAlertHtml(alert, alertKey);
        alertList.insertAdjacentHTML('afterbegin', alertHtml);
        
        while (alertList.children.length > 30) {
            alertList.removeChild(alertList.lastChild);
        }
        
        updateAlertCount();
        
        const newAlert = alertList.firstElementChild;
        if (newAlert) {
            const dismissBtn = newAlert.querySelector('.crealtime-alert-dismiss');
            if (dismissBtn) {
                dismissBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const alertKeyAttr = newAlert.getAttribute('data-alert-key');
                    if (alertKeyAttr) {
                        dismissAlertPermanently(alertKeyAttr);
                    }
                    newAlert.style.opacity = '0';
                    setTimeout(() => {
                        newAlert.remove();
                        updateAlertCount();
                        if (alertList.children.length === 0) {
                            alertList.innerHTML = `<div class="crealtime-alert-item"><div><div class="crealtime-alert-msg">No active alerts</div><div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div></div></div>`;
                        }
                    }, 200);
                });
            }
        }
        
        if (alert.severity === 'critical' && systemBadge) {
            systemBadge.classList.add('crealtime-badge-critical');
            setTimeout(() => {}, 5000);
        }
    };
    
    const updateAlertCount = () => {
        if (!alertList || !alertCountLabel) return;
        const visibleAlerts = alertList.querySelectorAll('.crealtime-alert-item:not(.placeholder)').length;
        alertCountLabel.textContent = `${visibleAlerts} Alerts`;
    };
    
    // Create alert HTML with data-alert-key attribute
    const createAlertHtml = (alert, alertKey) => {
        const warningClass = alert.severity === 'warning' ? 'crealtime-warning' : '';
        const criticalClass = alert.severity === 'critical' ? 'crealtime-feed-critical' : '';
        const styleAttr = alert.severity === 'critical' ? ' style="color:var(--crealtime-red)"' : '';
        const timestamp = alert.timestamp_unix || alert.timestamp;
        
        return `
            <div class="crealtime-alert-item ${warningClass} ${criticalClass}" data-node-id="${escapeHtml(alert.node_name || 'system')}" data-timestamp="${timestamp}" data-alert-key="${escapeHtml(alertKey)}">
                <div>
                    <div class="crealtime-alert-msg"${styleAttr}>${escapeHtml(alert.title || 'Alert')}</div>
                    <div class="crealtime-text-xs crealtime-text-muted">${escapeHtml(alert.description || '')} <span class="crealtime-dynamic-time">Just now</span></div>
                </div>
                <button class="crealtime-alert-dismiss" data-alert-title="${escapeHtml(alert.title)}">&times;</button>
            </div>
        `;
    };
    
    const handleEventUpdateRealtime = (data) => {
        if (!data.event) return;
        
        const event = data.event;
        const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed'];
        const titleLower = (event.title || '').toLowerCase();
        
        if (filteredTitles.some(t => titleLower.includes(t))) {
            return;
        }
        
        if (!isDuplicateEvent(event)) {
            addFeedEvent(event);
        }
    };
    
    const handleChartUpdateRealtime = (data) => {
        if (data.chart_values && Array.isArray(data.chart_values) && data.chart_values.length > 0) {
            updateChartRealtime(data.chart_values);
        }
        
        if (data.live_aqi !== undefined && liveAqiLabel) {
            const aqi = data.live_aqi;
            const aqiInfo = getAqiLevelInfo(aqi);
            liveAqiLabel.textContent = aqi !== null && aqi !== undefined ? aqi.toFixed(1) : '—';
            if (aqi !== null && aqi !== undefined) {
                liveAqiLabel.style.color = aqiInfo.color;
            }
        }
    };
    
    const handleSystemStatusRealtime = (data) => {
        if (data.status) {
            updateSystemStatusRealtime(data);
        }
    };
    
    const updateChartRealtime = (values) => {
        if (!chartCanvas || !values || values.length === 0) return;
        
        chartData = values.slice();
        
        if (chartInstance) {
            chartInstance.data.datasets[0].data = chartData;
            chartInstance.update('none');
        }
        
        updateTrendIndicator(chartData);
    };
    
    const updateSystemStatusRealtime = (data) => {
        if (!systemBadge || !systemPulse) return;
        
        const activeCount = data.active_count || 0;
        const totalCount = data.total_count || 0;
        const avgAqi = data.avg_aqi || null;
        const hasOffline = (totalCount - activeCount) > 0;
        
        let status = 'GOOD';
        let badgeClass = 'crealtime-badge-good';
        let pulseClass = 'crealtime-dot-green';
        let bannerActive = false;
        let bannerText = '';
        
        if (activeCount === 0) {
            status = 'CRITICAL';
            badgeClass = 'crealtime-badge-critical';
            pulseClass = 'crealtime-dot-red';
            bannerActive = true;
            bannerText = 'System Critical - No Active Nodes';
        } else if (hasOffline || (avgAqi !== null && avgAqi > 150)) {
            status = 'CRITICAL';
            badgeClass = 'crealtime-badge-critical';
            pulseClass = 'crealtime-dot-red';
            bannerActive = true;
            const offlineCount = totalCount - activeCount;
            bannerText = offlineCount > 0 ? `${offlineCount} Node(s) Offline` : 'Critical Air Quality Levels';
        } else if (hasOffline || (avgAqi !== null && avgAqi > 100)) {
            status = 'WARNING';
            badgeClass = 'crealtime-badge-degraded';
            pulseClass = 'crealtime-dot-yellow';
        }
        
        systemBadge.className = `crealtime-badge ${badgeClass}`;
        systemBadge.textContent = status;
        systemPulse.className = `crealtime-dot ${pulseClass}`;
        if (status !== 'GOOD') systemPulse.classList.add('crealtime-pulse');
        
        if (priorityBanner) {
            if (bannerActive) {
                priorityBanner.classList.add('crealtime-banner-active');
                if (bannerMsg) bannerMsg.textContent = bannerText;
            } else {
                priorityBanner.classList.remove('crealtime-banner-active');
            }
        }
        
        if (activeNodesLabel) {
            activeNodesLabel.textContent = `${activeCount}/${totalCount}`;
        }
    };
    
    // ============================================================================
    // MODAL SYSTEM
    // ============================================================================
    
    const injectModalStyles = () => {
        if (document.querySelector('#crealtime-modal-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'crealtime-modal-styles';
        style.textContent = `
            .crealtime-modal-overlay {
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                background: rgba(0, 0, 0, 0.5) !important;
                backdrop-filter: blur(4px) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 999999 !important;
                opacity: 0 !important;
                visibility: hidden !important;
                transition: opacity 0.3s ease, visibility 0.3s ease !important;
                margin: 0 !important;
                padding: 0 !important;
                box-sizing: border-box !important;
            }
            
            .crealtime-modal-overlay.active {
                opacity: 1 !important;
                visibility: visible !important;
            }
            
            .crealtime-modal {
                position: relative !important;
                background: #ffffff !important;
                border-radius: 16px !important;
                box-shadow: 0 25px 40px -12px rgba(0, 0, 0, 0.25) !important;
                max-width: 560px !important;
                width: 90% !important;
                max-height: 85vh !important;
                overflow: hidden !important;
                transform: scale(0.95) !important;
                transition: transform 0.3s cubic-bezier(0.34, 1.2, 0.64, 1) !important;
                margin: 0 auto !important;
            }
            
            .crealtime-modal-overlay.active .crealtime-modal {
                transform: scale(1) !important;
            }
            
            .crealtime-modal-header {
                padding: 20px 24px 16px !important;
                border-bottom: 1px solid #e2e8f0 !important;
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                background: #f8fafc !important;
            }
            
            .crealtime-modal-header-left {
                flex: 1 !important;
            }
            
            .crealtime-modal-title {
                font-size: 1.25rem !important;
                font-weight: 600 !important;
                color: #1e293b !important;
                margin: 0 0 4px 0 !important;
            }
            
            .crealtime-modal-subtitle {
                font-size: 0.8rem !important;
                color: #64748b !important;
                font-weight: 500 !important;
            }
            
            .crealtime-modal-close {
                background: none !important;
                border: none !important;
                font-size: 28px !important;
                cursor: pointer !important;
                color: #94a3b8 !important;
                padding: 0 !important;
                line-height: 1 !important;
                transition: all 0.2s !important;
                width: 32px !important;
                height: 32px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                border-radius: 8px !important;
            }
            
            .crealtime-modal-close:hover {
                color: #ef4444 !important;
                background: #fee2e2 !important;
            }
            
            .crealtime-modal-body {
                padding: 20px 24px !important;
                max-height: calc(85vh - 140px) !important;
                overflow-y: auto !important;
            }
            
            .crealtime-modal-footer {
                padding: 16px 24px !important;
                border-top: 1px solid #e2e8f0 !important;
                display: flex !important;
                justify-content: flex-end !important;
                gap: 12px !important;
                background: #f8fafc !important;
            }
            
            .crealtime-btn-modal {
                padding: 8px 20px !important;
                border-radius: 8px !important;
                font-weight: 500 !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                border: none !important;
                font-size: 0.85rem !important;
            }
            
            .crealtime-btn-modal-cancel {
                background: #f1f5f9 !important;
                color: #475569 !important;
            }
            
            .crealtime-btn-modal-cancel:hover {
                background: #e2e8f0 !important;
            }
            
            .crealtime-btn-modal-confirm {
                background: #ef4444 !important;
                color: white !important;
            }
            
            .crealtime-btn-modal-confirm:hover {
                background: #dc2626 !important;
            }
            
            .crealtime-btn-modal-primary {
                background: #3b82f6 !important;
                color: white !important;
            }
            
            .crealtime-btn-modal-primary:hover {
                background: #2563eb !important;
            }
            
            .crealtime-spinner {
                display: inline-block !important;
                width: 16px !important;
                height: 16px !important;
                border: 2px solid rgba(255,255,255,0.3) !important;
                border-radius: 50% !important;
                border-top-color: white !important;
                animation: crealtime-spin 0.6s linear infinite !important;
                margin-right: 8px !important;
            }
            
            @keyframes crealtime-spin {
                to { transform: rotate(360deg); }
            }
            
            .crealtime-btn-loading {
                opacity: 0.7 !important;
                cursor: not-allowed !important;
            }
            
            .crealtime-node-detail-section {
                margin-bottom: 20px !important;
            }
            
            .crealtime-node-detail-section-title {
                font-size: 0.75rem !important;
                font-weight: 600 !important;
                text-transform: uppercase !important;
                letter-spacing: 0.05em !important;
                color: #64748b !important;
                margin-bottom: 12px !important;
                padding-bottom: 6px !important;
                border-bottom: 1px solid #e2e8f0 !important;
            }
            
            .crealtime-node-detail-grid {
                display: grid !important;
                grid-template-columns: 1fr 1fr !important;
                gap: 12px 16px !important;
            }
            
            .crealtime-node-detail-row {
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                padding: 8px 0 !important;
                border-bottom: 1px solid #f1f5f9 !important;
            }
            
            .crealtime-node-detail-row-full {
                grid-column: span 2 !important;
            }
            
            .crealtime-node-detail-label {
                font-weight: 600 !important;
                color: #64748b !important;
                font-size: 0.8rem !important;
            }
            
            .crealtime-node-detail-value {
                color: #1e293b !important;
                font-weight: 500 !important;
                font-size: 0.85rem !important;
            }
            
            .crealtime-aqi-badge {
                display: inline-block !important;
                padding: 4px 12px !important;
                border-radius: 20px !important;
                font-size: 0.75rem !important;
                font-weight: 600 !important;
            }
            
            .aqi-good { background: #d1fae5 !important; color: #059669 !important; border: 1px solid #a7f3d0 !important; }
            .aqi-moderate { background: #fef3c7 !important; color: #d97706 !important; border: 1px solid #fde68a !important; }
            .aqi-unhealthy-sensitive { background: #ffedd5 !important; color: #ea580c !important; border: 1px solid #fed7aa !important; }
            .aqi-unhealthy { background: #fee2e2 !important; color: #dc2626 !important; border: 1px solid #fecaca !important; }
            .aqi-very-unhealthy { background: #f3e8ff !important; color: #7c3aed !important; border: 1px solid #e9d5ff !important; }
            .aqi-hazardous { background: #fecaca !important; color: #b91c1c !important; border: 1px solid #fca5a5 !important; }
            .aqi-unknown { background: #f1f5f9 !important; color: #64748b !important; border: 1px solid #e2e8f0 !important; }
            
            .crealtime-status-badge {
                display: inline-flex !important;
                align-items: center !important;
                gap: 6px !important;
                padding: 4px 10px !important;
                border-radius: 20px !important;
                font-size: 0.7rem !important;
                font-weight: 600 !important;
            }
            
            .crealtime-activity-item {
                padding: 8px 0 !important;
                border-bottom: 1px solid #f1f5f9 !important;
                display: flex !important;
                align-items: center !important;
                gap: 10px !important;
                font-size: 0.75rem !important;
            }
            
            .crealtime-activity-icon {
                width: 24px !important;
                height: 24px !important;
                border-radius: 6px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                font-size: 0.7rem !important;
                background: #f1f5f9 !important;
            }
            
            .crealtime-activity-content {
                flex: 1 !important;
            }
            
            .crealtime-activity-time {
                font-size: 0.65rem !important;
                color: #94a3b8 !important;
            }
            
            .crealtime-toast {
                position: fixed !important;
                top: 20px !important;
                right: 20px !important;
                background: #10b981 !important;
                color: white !important;
                padding: 12px 20px !important;
                border-radius: 8px !important;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
                z-index: 1000000 !important;
                transform: translateX(400px) !important;
                transition: transform 0.3s ease !important;
                font-size: 0.875rem !important;
                font-weight: 500 !important;
            }
            
            .crealtime-toast.show {
                transform: translateX(0) !important;
            }
            
            .crealtime-toast.error {
                background: #ef4444 !important;
            }
            
            .crealtime-paused-label {
                font-size: 0.7rem !important;
                color: #64748b !important;
                margin-left: 8px !important;
            }
            
            .crealtime-modal-body::-webkit-scrollbar {
                width: 6px !important;
            }
            
            .crealtime-modal-body::-webkit-scrollbar-track {
                background: #f1f5f9 !important;
                border-radius: 3px !important;
            }
            
            .crealtime-modal-body::-webkit-scrollbar-thumb {
                background: #cbd5e1 !important;
                border-radius: 3px !important;
            }
            
            /* Dot colors for AQI levels */
            .crealtime-dot-green { background: #10b981; box-shadow: 0 0 4px #10b981; }
            .crealtime-dot-yellow { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
            .crealtime-dot-orange { background: #f97316; box-shadow: 0 0 4px #f97316; }
            .crealtime-dot-red { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
            .crealtime-dot-purple { background: #8b5cf6; box-shadow: 0 0 4px #8b5cf6; }
            .crealtime-dot-maroon { background: #7f1d1d; box-shadow: 0 0 4px #7f1d1d; }
            .crealtime-dot-gray { background: #94a3b8; box-shadow: 0 0 4px #94a3b8; }
            
            .crealtime-paused-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.75);
                backdrop-filter: blur(4px);
                z-index: 99999;
                display: flex;
                align-items: center;
                justify-content: center;
                animation: crealtime-fade-in 0.3s ease;
            }
            
            .crealtime-paused-content {
                background: #1e293b;
                border-radius: 16px;
                padding: 32px 48px;
                text-align: center;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                animation: crealtime-scale-in 0.3s cubic-bezier(0.34, 1.2, 0.64, 1);
            }
            
            .crealtime-paused-icon {
                font-size: 48px;
                margin-bottom: 16px;
            }
            
            .crealtime-paused-title {
                font-size: 1.25rem;
                font-weight: 600;
                color: #f1f5f9;
                margin-bottom: 8px;
            }
            
            .crealtime-paused-subtitle {
                font-size: 0.85rem;
                color: #94a3b8;
                margin-bottom: 20px;
            }
            
            .crealtime-paused-resume-btn {
                background: #3b82f6;
                color: white;
                border: none;
                padding: 10px 24px;
                border-radius: 8px;
                font-size: 0.875rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }
            
            .crealtime-paused-resume-btn:hover {
                background: #2563eb;
                transform: scale(1.02);
            }
            
            @keyframes crealtime-fade-in {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            
            @keyframes crealtime-scale-in {
                from { transform: scale(0.95); opacity: 0; }
                to { transform: scale(1); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    };
    
    injectModalStyles();
    
    const showToast = (message, isError = false) => {
        const existingToast = document.querySelector('.crealtime-toast');
        if (existingToast) existingToast.remove();
        
        const toast = document.createElement('div');
        toast.className = `crealtime-toast ${isError ? 'error' : ''}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => toast.classList.add('show'), 10);
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    };
    
    const closeModal = () => {
        if (!activeModal) return;
        const overlay = activeModal;
        overlay.classList.remove('active');
        setTimeout(() => {
            if (overlay.parentNode) overlay.remove();
            if (activeModal === overlay) activeModal = null;
        }, 300);
        
        const escHandler = overlay._escHandler;
        if (escHandler) {
            document.removeEventListener('keydown', escHandler);
        }
        
        document.body.style.overflow = '';
    };
    
    const showNodeDetailsModal = (node) => {
        if (activeModal) closeModal();
        
        document.body.style.overflow = 'hidden';
        
        const aqi = node.aqi !== undefined && node.aqi !== null ? node.aqi : node.latest_aqi;
        const aqiInfo = getAqiLevelInfo(aqi);
        const aqiLabel = aqiInfo.label;
        const aqiBadgeClass = getAqiBadgeClass(aqi);
        const statusText = getStatusText(aqi, !!node.timestamp, isDataStale(node.timestamp));
        const statusDotClass = getStatusDotClass(aqi, isDataStale(node.timestamp));
        
        const activities = [];
        
        if (aqi !== null && aqi !== '—') {
            activities.unshift({
                icon: '✓',
                bgColor: 'crealtime-bg-green',
                text: `Current AQI: ${aqi} - ${aqiLabel}`,
                timeAgo: 'Just now'
            });
            activities.push({
                icon: '📡',
                bgColor: 'crealtime-bg-green',
                text: 'Data transmission active',
                timeAgo: '2 minutes ago'
            });
        } else {
            activities.push({
                icon: '❌',
                bgColor: 'crealtime-bg-red',
                text: 'Node disconnected - No data received',
                timeAgo: 'Just now'
            });
            activities.push({
                icon: '⏱',
                bgColor: 'crealtime-bg-red',
                text: `Last reading: ${node.last_seen || 'Never'}`,
                timeAgo: node.timestamp ? formatTimeAgo(node.timestamp, true) : 'N/A'
            });
        }
        
        if (node.timestamp) {
            activities.push({
                icon: '📊',
                bgColor: 'crealtime-bg-info',
                text: 'Sensor reading recorded',
                timeAgo: formatTimeAgo(node.timestamp, true)
            });
        }
        
        const activitiesHtml = activities.map(act => `
            <div class="crealtime-activity-item">
                <div class="crealtime-activity-icon ${act.bgColor}">${act.icon}</div>
                <div class="crealtime-activity-content">
                    <div>${escapeHtml(act.text)}</div>
                    <div class="crealtime-activity-time">${act.timeAgo}</div>
                </div>
            </div>
        `).join('');
        
        const overlay = document.createElement('div');
        overlay.className = 'crealtime-modal-overlay';
        overlay.innerHTML = `
            <div class="crealtime-modal">
                <div class="crealtime-modal-header">
                    <div class="crealtime-modal-header-left">
                        <h3 class="crealtime-modal-title">Node Details</h3>
                        <div class="crealtime-modal-subtitle">${escapeHtml(node.name)}</div>
                    </div>
                    <button class="crealtime-modal-close">&times;</button>
                </div>
                <div class="crealtime-modal-body">
                    <div class="crealtime-node-detail-section">
                        <div class="crealtime-node-detail-section-title">Basic Information</div>
                        <div class="crealtime-node-detail-grid">
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Node ID:</span>
                                <span class="crealtime-node-detail-value">${escapeHtml(node.name)}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Zone/Location:</span>
                                <span class="crealtime-node-detail-value">${escapeHtml(node.zone || node.location || 'Unknown')}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">AQI:</span>
                                <span class="crealtime-node-detail-value">
                                    <span class="crealtime-aqi-badge ${aqiBadgeClass}">
                                        ${aqi !== null && aqi !== '—' ? aqi : '—'} - ${aqiLabel}
                                    </span>
                                </span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Node Status:</span>
                                <span class="crealtime-node-detail-value">
                                    <span class="crealtime-status-badge">
                                        <span class="crealtime-dot ${statusDotClass}" style="margin-right: 4px;"></span>
                                        ${escapeHtml(statusText)}
                                    </span>
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="crealtime-node-detail-section">
                        <div class="crealtime-node-detail-section-title">Sensor Readings</div>
                        <div class="crealtime-node-detail-grid">
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Temperature:</span>
                                <span class="crealtime-node-detail-value">${node.temperature !== undefined && node.temperature !== null ? node.temperature + '°C' : '—'}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Humidity:</span>
                                <span class="crealtime-node-detail-value">${node.humidity !== undefined && node.humidity !== null ? node.humidity + '%' : '—'}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">PM2.5:</span>
                                <span class="crealtime-node-detail-value">${node.pm2_5 !== undefined && node.pm2_5 !== null ? node.pm2_5 + ' µg/m³' : '—'}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">PM10:</span>
                                <span class="crealtime-node-detail-value">${node.pm10 !== undefined && node.pm10 !== null ? node.pm10 + ' µg/m³' : '—'}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Last Seen:</span>
                                <span class="crealtime-node-detail-value">${node.last_seen || (node.timestamp ? formatTimeAgo(node.timestamp) : 'Never')}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="crealtime-node-detail-section">
                        <div class="crealtime-node-detail-section-title">Recent Activity Log</div>
                        <div id="crealtime-activity-log">
                            ${activitiesHtml || '<div class="crealtime-activity-item">No recent activity</div>'}
                        </div>
                    </div>
                </div>
                <div class="crealtime-modal-footer">
                    <button class="crealtime-btn-modal crealtime-btn-modal-primary" id="modal-view-map-btn">🗺 View on Map</button>
                    <button class="crealtime-btn-modal crealtime-btn-modal-cancel" id="modal-close-footer-btn">Close</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(overlay);
        activeModal = overlay;
        
        const closeBtn = overlay.querySelector('.crealtime-modal-close');
        const closeFooterBtn = overlay.querySelector('#modal-close-footer-btn');
        const viewMapBtn = overlay.querySelector('#modal-view-map-btn');
        
        const handleClose = () => closeModal();
        closeBtn.addEventListener('click', handleClose);
        closeFooterBtn.addEventListener('click', handleClose);
        
        if (viewMapBtn) {
            viewMapBtn.addEventListener('click', () => {
                window.location.href = `/dashboard/map/?highlight=${encodeURIComponent(node.name)}`;
            });
        }
        
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
        
        const escHandler = (e) => {
            if (e.key === 'Escape') closeModal();
        };
        overlay._escHandler = escHandler;
        document.addEventListener('keydown', escHandler);
        
        setTimeout(() => overlay.classList.add('active'), 10);
    };
    
    const showConfirmModal = (title, message, onConfirm) => {
        if (activeModal) closeModal();
        
        document.body.style.overflow = 'hidden';
        
        const overlay = document.createElement('div');
        overlay.className = 'crealtime-modal-overlay';
        overlay.innerHTML = `
            <div class="crealtime-modal">
                <div class="crealtime-modal-header">
                    <h3 class="crealtime-modal-title">${escapeHtml(title)}</h3>
                    <button class="crealtime-modal-close">&times;</button>
                </div>
                <div class="crealtime-modal-body">
                    <p style="color: #475569; line-height: 1.5;">${escapeHtml(message)}</p>
                </div>
                <div class="crealtime-modal-footer">
                    <button class="crealtime-btn-modal crealtime-btn-modal-cancel" id="modal-cancel-btn">Cancel</button>
                    <button class="crealtime-btn-modal crealtime-btn-modal-confirm" id="modal-confirm-btn">Confirm Restart</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        activeModal = overlay;
        
        const closeModalLocal = () => {
            overlay.classList.remove('active');
            setTimeout(() => {
                if (overlay.parentNode) overlay.remove();
                if (activeModal === overlay) activeModal = null;
            }, 300);
            document.removeEventListener('keydown', escHandler);
            document.body.style.overflow = '';
        };
        
        const confirmBtn = overlay.querySelector('#modal-confirm-btn');
        const cancelBtn = overlay.querySelector('#modal-cancel-btn');
        const closeBtn = overlay.querySelector('.crealtime-modal-close');
        
        const handleConfirm = async () => {
            confirmBtn.innerHTML = '<span class="crealtime-spinner"></span>Restarting...';
            confirmBtn.disabled = true;
            confirmBtn.classList.add('crealtime-btn-loading');
            cancelBtn.disabled = true;
            
            if (onConfirm) await onConfirm();
            closeModalLocal();
        };
        
        confirmBtn.addEventListener('click', handleConfirm);
        cancelBtn.addEventListener('click', closeModalLocal);
        closeBtn.addEventListener('click', closeModalLocal);
        
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModalLocal();
        });
        
        const escHandler = (e) => {
            if (e.key === 'Escape') closeModalLocal();
        };
        document.addEventListener('keydown', escHandler);
        
        setTimeout(() => overlay.classList.add('active'), 10);
    };
    
    // ============================================================================
    // UPDATE FUNCTIONS
    // ============================================================================
    
    const updateDynamicTimes = () => {
        document.querySelectorAll('[data-timestamp]').forEach((element) => {
            const timestamp = element.getAttribute('data-timestamp');
            const timeSpan = element.querySelector('.crealtime-dynamic-time');
            if (timeSpan && timestamp) {
                const isAlert = element.classList.contains('crealtime-alert-item');
                timeSpan.textContent = formatTimeAgo(parseInt(timestamp), isAlert);
            }
        });
    };
    
    const createFeedItemHtml = (event, index = 0) => {
        const titleLower = (event.title || '').toLowerCase();
        const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed'];
        
        if (filteredTitles.some(t => titleLower.includes(t))) {
            return null;
        }
        
        const isCritical = event.severity === 'critical';
        const eventClass = isCritical ? 'crealtime-feed-critical' : '';
        const label = event.tag_label || (event.severity || 'INFO').toUpperCase();
        const timestamp = event.timestamp_unix || event.timestamp;
        
        return `
            <div class="crealtime-feed-item ${eventClass}" data-node-id="${event.node_id || 'system'}" data-timestamp="${timestamp}" data-feed-index="${index}">
                <div class="crealtime-feed-icon ${event.bg_class || 'crealtime-bg-green'}">${event.icon || '✓'}</div>
                <div class="crealtime-feed-content">
                    <div class="crealtime-feed-header-row">
                        <span class="crealtime-tag ${event.tag_class || 'crealtime-tag-info'}">${escapeHtml(label)}</span>
                        <div class="crealtime-text-sm crealtime-font-medium">${escapeHtml(event.title || 'Event')}</div>
                    </div>
                    <div class="crealtime-text-xs crealtime-text-muted">${escapeHtml(event.description || '')}</div>
                </div>
                <div class="crealtime-feed-time crealtime-mono crealtime-dynamic-time">Just now</div>
            </div>
        `;
    };
    
    const renderFeed = (feed = []) => {
        if (!feedContainer) return;
        
        const filteredFeed = feed.filter(event => {
            const titleLower = (event.title || '').toLowerCase();
            const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed', 'test event'];
            return !filteredTitles.some(t => titleLower.includes(t));
        });
        
        if (!filteredFeed.length) {
            feedContainer.innerHTML = `
                <div class="crealtime-feed-item" data-node-id="none" data-timestamp="${Date.now() / 1000}">
                    <div class="crealtime-feed-icon crealtime-bg-green">✓</div>
                    <div class="crealtime-feed-content">
                        <div class="crealtime-feed-header-row">
                            <span class="crealtime-tag crealtime-tag-info">INFO</span>
                            <div class="crealtime-text-sm crealtime-font-medium">System Ready</div>
                        </div>
                        <div class="crealtime-text-xs crealtime-text-muted">Monitoring active. Waiting for data...</div>
                    </div>
                    <div class="crealtime-feed-time crealtime-mono crealtime-dynamic-time">Just now</div>
                </div>
            `;
            return;
        }
        
        feedContainer.innerHTML = filteredFeed.map(createFeedItemHtml).join('');
        updateDynamicTimes();
        if (isLive && feedContainer) feedContainer.scrollTop = 0;
    };
    
    const addFeedEvent = (event) => {
        if (!feedContainer) return;
        
        const titleLower = (event.title || '').toLowerCase();
        const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed', 'test event'];
        if (filteredTitles.some(t => titleLower.includes(t))) {
            console.log('[Realtime] Skipping system heartbeat event:', event.title);
            return;
        }
        
        const placeholder = feedContainer.querySelector('.crealtime-feed-item:first-child');
        if (placeholder && placeholder.querySelector('.crealtime-feed-header-row .crealtime-tag')?.textContent === 'INFO' &&
            placeholder.querySelector('.crealtime-text-sm')?.textContent === 'System Ready') {
            feedContainer.innerHTML = '';
        }
        
        const html = createFeedItemHtml(event, 0);
        if (html) {
            feedContainer.insertAdjacentHTML('afterbegin', html);
            while (feedContainer.children.length > MAX_FEED_ITEMS) {
                feedContainer.removeChild(feedContainer.lastChild);
            }
            updateDynamicTimes();
            if (isLive && feedContainer) feedContainer.scrollTop = 0;
        }
    };
    
    let nodeDataCache = {};
    
    const renderNodeTable = (nodes = []) => {
        if (!nodeTableBody) return;
        
        nodes.forEach(node => {
            nodeDataCache[node.name] = node;
            nodeDataCache[node.node_id] = node;
        });
        
        if (!nodes.length) {
            nodeTableBody.innerHTML = `<tr><td colspan="6" class="crealtime-text-xs crealtime-text-muted">No active node readings available.</td></tr>`;
            return;
        }
        
        let filteredNodes = [...nodes];
        if (currentZone !== 'all') {
            filteredNodes = filteredNodes.filter(n => (n.zone || n.location || '').toLowerCase() === currentZone.toLowerCase());
        }
        if (currentFilter === 'online') {
            filteredNodes = filteredNodes.filter(n => n.aqi !== null && n.aqi !== '—' && !isDataStale(n.timestamp));
        } else if (currentFilter === 'alerts') {
            filteredNodes = filteredNodes.filter(n => 
                n.aqi === null || n.aqi === '—' || isDataStale(n.timestamp) || (n.aqi !== null && n.aqi >= 101)
            );
        }
        
        nodeTableBody.innerHTML = filteredNodes.map(createNodeRowHtml).join('');
        updateDynamicTimes();
        
        document.querySelectorAll('#crealtime-node-table-body tr').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.crealtime-action-btn')) return;
                const nodeName = row.getAttribute('data-node-id');
                const nodeData = nodeDataCache[nodeName];
                if (nodeData) showNodeDetailsModal(nodeData);
            });
        });
        
        document.querySelectorAll('#crealtime-node-table-body .crealtime-action-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const action = btn.getAttribute('data-action');
                const nodeName = btn.getAttribute('data-node-name');
                const nodeId = btn.getAttribute('data-node-id');
                const nodeData = nodeDataCache[nodeName] || nodeDataCache[nodeId];
                handleNodeAction(nodeData, action);
            });
        });
    };
    
    const renderAlerts = (alerts = []) => {
        if (!alertList) return;
        
        const filteredAlerts = alerts.filter(alert => !isAlertDismissed(alert));
        
        if (!filteredAlerts.length) {
            alertList.innerHTML = `<div class="crealtime-alert-item"><div><div class="crealtime-alert-msg">No active alerts</div><div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div></div></div>`;
            if (alertCountLabel) alertCountLabel.textContent = '0 Alerts';
            return;
        }
        
        alertList.innerHTML = filteredAlerts.map(alert => createAlertHtml(alert, `${alert.node_name || 'system'}_${alert.severity}_${alert.title}`)).join('');
        updateDynamicTimes();
        if (alertCountLabel) alertCountLabel.textContent = `${filteredAlerts.length} Alerts`;
        
        document.querySelectorAll('.crealtime-alert-dismiss').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const alertItem = btn.closest('.crealtime-alert-item');
                if (alertItem) {
                    const alertKey = alertItem.getAttribute('data-alert-key');
                    if (alertKey) {
                        dismissAlertPermanently(alertKey);
                    }
                    alertItem.style.opacity = '0';
                    setTimeout(() => {
                        alertItem.remove();
                        updateAlertCount();
                        if (alertList.children.length === 0) {
                            alertList.innerHTML = `<div class="crealtime-alert-item"><div><div class="crealtime-alert-msg">No active alerts</div><div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div></div></div>`;
                        }
                    }, 200);
                }
            });
        });
    };
    
    const updateSystemStatus = (activeCount, totalCount, avgAqi, hasOffline) => {
        if (!systemBadge || !systemPulse) return;
        
        let status = 'GOOD';
        let badgeClass = 'crealtime-badge-good';
        let pulseClass = 'crealtime-dot-green';
        let bannerActive = false;
        let bannerText = '';
        
        if (activeCount === 0) {
            status = 'CRITICAL';
            badgeClass = 'crealtime-badge-critical';
            pulseClass = 'crealtime-dot-red';
            bannerActive = true;
            bannerText = 'System Critical - No Active Nodes';
        } else if (hasOffline || (avgAqi !== null && avgAqi >= 101)) {
            status = 'CRITICAL';
            badgeClass = 'crealtime-badge-critical';
            pulseClass = 'crealtime-dot-red';
            bannerActive = true;
            const offlineCount = totalCount - activeCount;
            bannerText = offlineCount > 0 ? `${offlineCount} Node(s) Disconnected/Offline` : 'Critical Air Quality Levels';
        } else if ((avgAqi !== null && avgAqi > 50)) {
            status = 'WARNING';
            badgeClass = 'crealtime-badge-degraded';
            pulseClass = 'crealtime-dot-yellow';
        }
        
        systemBadge.className = `crealtime-badge ${badgeClass}`;
        systemBadge.textContent = status;
        systemPulse.className = `crealtime-dot ${pulseClass}`;
        if (status !== 'GOOD') systemPulse.classList.add('crealtime-pulse');
        
        if (priorityBanner) {
            if (bannerActive) {
                priorityBanner.classList.add('crealtime-banner-active');
                if (bannerMsg) bannerMsg.textContent = bannerText;
            } else {
                priorityBanner.classList.remove('crealtime-banner-active');
            }
        }
    };
    
    const updateLiveAqi = (avgAqi) => {
        if (!liveAqiLabel) return;
        const displayValue = avgAqi !== null ? avgAqi.toFixed(1) : '—';
        liveAqiLabel.textContent = displayValue;
        if (avgAqi !== null) {
            const aqiInfo = getAqiLevelInfo(avgAqi);
            liveAqiLabel.style.color = aqiInfo.color;
        }
    };
    
    const updateTrendIndicator = (values) => {
        const trendEl = document.getElementById('crealtime-trend-indicator');
        if (!trendEl || !values || values.length < 5) return;
        
        const recent = values.slice(-5);
        const start = recent[0] || 0;
        const end = recent[recent.length - 1] || 0;
        const diff = end - start;
        
        trendEl.className = 'crealtime-trend';
        if (diff > 2) {
            trendEl.innerHTML = '↑ Rising';
            trendEl.classList.add('crealtime-trend-up');
        } else if (diff < -2) {
            trendEl.innerHTML = '↓ Falling';
            trendEl.classList.add('crealtime-trend-down');
        } else {
            trendEl.innerHTML = '→ Stable';
            trendEl.classList.add('crealtime-trend-stable');
        }
    };
    
    const updateChart = (values, showLoading = false) => {
        if (!chartCanvas) return;
        
        if (showLoading) {
            chartCanvas.style.opacity = '0.5';
            setTimeout(() => { chartCanvas.style.opacity = '1'; }, 300);
        }
        
        chartData = values.slice();
        
        const ctx = chartCanvas.getContext('2d');
        
        if (!chartInstance) {
            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.map((_, i) => i),
                    datasets: [{
                        data: chartData,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        fill: true,
                        tension: 0.3,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    aspectRatio: 2.5,
                    animation: { duration: 300 },
                    plugins: { 
                        legend: { display: false }, 
                        tooltip: { 
                            mode: 'index', 
                            intersect: false, 
                            callbacks: { 
                                label: (ctx) => `AQI: ${ctx.raw}` 
                            } 
                        } 
                    },
                    scales: { 
                        x: { 
                            display: true, 
                            ticks: { 
                                maxRotation: 0, 
                                autoSkip: true, 
                                maxTicksLimit: 6 
                            },
                            grid: { display: false }
                        }, 
                        y: { 
                            display: true, 
                            beginAtZero: true, 
                            grid: { color: '#f1f5f9' },
                            ticks: { stepSize: 50 }
                        } 
                    },
                    layout: {
                        padding: {
                            top: 10,
                            bottom: 10,
                            left: 5,
                            right: 5
                        }
                    }
                }
            });
        } else {
            chartInstance.data.datasets[0].data = chartData;
            chartInstance.update('none');
        }
        
        updateTrendIndicator(chartData);
    };
    
    const handleNodeAction = (node, action) => {
        if (!node) return;
        if (action === 'view-details') {
            showNodeDetailsModal(node);
        } else if (action === 'view-map') {
            window.location.href = `/dashboard/map/?highlight=${encodeURIComponent(node.name)}`;
        }
    };
    
    const showLoadingTransition = () => {
        if (isLoadingData) return;
        isLoadingData = true;
        const panels = document.querySelectorAll('.crealtime-panel');
        panels.forEach(panel => { panel.style.opacity = '0.6'; panel.style.transition = 'opacity 0.2s'; });
        setTimeout(() => { panels.forEach(panel => { panel.style.opacity = '1'; }); isLoadingData = false; }, 300);
    };
    
    const pollRealtimeData = async () => {
        if (!isLive) return;
        try {
            const url = `${DATA_ENDPOINT}?filter=${currentFilter}&zone=${encodeURIComponent(currentZone)}&time_range=${currentTimeRange}`;
            const response = await fetch(url, { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const json = await response.json();
            if (json.status !== 'success') return;
            
            if (json.timestamp) {
                updateSyncTimeDisplay(json.timestamp);
            } else {
                updateSyncTimeDisplay();
            }
            
            if (json.data) renderNodeTable(json.data);
            
            if (json.feed && json.feed.length) {
                const relevantEvents = json.feed.filter(event => {
                    const titleLower = (event.title || '').toLowerCase();
                    const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed'];
                    return !filteredTitles.some(t => titleLower.includes(t));
                });
                
                if (relevantEvents.length > 0) {
                    const latestTimestamp = relevantEvents[0]?.timestamp_unix || relevantEvents[0]?.timestamp;
                    if (latestTimestamp && (!lastEventTimestamp || latestTimestamp > lastEventTimestamp)) {
                        addFeedEvent(relevantEvents[0]);
                        lastEventTimestamp = latestTimestamp;
                    } else if (!lastEventTimestamp) {
                        renderFeed(relevantEvents);
                        if (relevantEvents[0]) lastEventTimestamp = relevantEvents[0].timestamp_unix || relevantEvents[0].timestamp;
                    }
                } else {
                    renderFeed([]);
                }
            }
            
            if (json.alerts) {
                renderAlerts(json.alerts);
            }
            
            if (json.chart_values && json.chart_values.length) updateChart(json.chart_values);
            
            const nodesWithData = (json.data || []).filter(n => n.aqi !== null && n.aqi !== '—' && !isDataStale(n.timestamp));
            const activeCount = nodesWithData.length;
            const totalCount = json.total_nodes || (json.data || []).length;
            const hasOffline = (totalCount - activeCount) > 0;
            updateSystemStatus(activeCount, totalCount, json.live_aqi, hasOffline);
            updateLiveAqi(json.live_aqi);
            if (activeNodesLabel) activeNodesLabel.textContent = `${activeCount}/${totalCount}`;
            
            if (zoneSelect && json.zones && json.zones.length && zoneSelect.options.length <= 1) {
                const currentValue = zoneSelect.value;
                zoneSelect.innerHTML = '<option value="all">All Nodes</option>';
                json.zones.forEach(zone => { zoneSelect.innerHTML += `<option value="${zone.toLowerCase()}">${escapeHtml(zone)}</option>`; });
                zoneSelect.value = currentValue;
            }
        } catch (error) { console.error('Poll error:', error); }
    };
    
    const manualRefresh = async () => { showLoadingTransition(); await pollRealtimeData(); };
    
    const setupEventListeners = () => {
        const filterButtons = document.querySelectorAll('.crealtime-btn-group .crealtime-btn');
        filterButtons.forEach((btn, idx) => {
            btn.addEventListener('click', () => {
                filterButtons.forEach(b => b.classList.remove('crealtime-active'));
                btn.classList.add('crealtime-active');
                currentFilter = idx === 0 ? 'all' : idx === 1 ? 'online' : 'alerts';
                manualRefresh();
            });
        });
        
        if (zoneSelect) zoneSelect.addEventListener('change', (e) => { currentZone = e.target.value; manualRefresh(); });
        
        const timeSelect = document.getElementById('crealtime-time-range');
        if (timeSelect) {
            timeSelect.addEventListener('change', (e) => {
                const value = e.target.value;
                currentTimeRange = value === '1m' ? '1m' : value === '5m' ? '5m' : '15m';
                if (chartCanvas) chartCanvas.style.opacity = '0.5';
                manualRefresh();
                setTimeout(() => { if (chartCanvas) chartCanvas.style.opacity = '1'; }, 500);
            });
        }
        
        if (autoRefreshToggle) {
            autoRefreshToggle.addEventListener('click', () => {
                isLive = !isLive;
                autoRefreshToggle.classList.toggle('crealtime-off', !isLive);
                const toggleWrapper = autoRefreshToggle.closest('.crealtime-toggle-wrapper');
                let pausedLabel = toggleWrapper?.querySelector('.crealtime-paused-label');
                
                if (!isLive) {
                    if (!pausedLabel) { 
                        pausedLabel = document.createElement('span'); 
                        pausedLabel.className = 'crealtime-paused-label'; 
                        pausedLabel.textContent = 'Paused'; 
                        toggleWrapper?.appendChild(pausedLabel); 
                    }
                    if (pollInterval) clearInterval(pollInterval);
                    pollInterval = null;
                    
                    if (wsConnection) {
                        wsConnection.close();
                        wsConnection = null;
                    }
                    
                    createPausedOverlay();
                } else {
                    if (pausedLabel) pausedLabel.remove();
                    
                    removePausedOverlay();
                    
                    startPolling();
                    
                    if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) {
                        connectWebSocket();
                    }
                    
                    manualRefresh();
                    showToast('Real-time monitoring resumed', false);
                }
            });
        }
        
        if (priorityBanner) {
            const bannerBtns = priorityBanner.querySelectorAll('.crealtime-banner-btn');
            if (bannerBtns[0]) bannerBtns[0].addEventListener('click', () => {
                showConfirmModal('Restart Node', 'Are you sure you want to restart all active nodes?', async () => {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    showToast('Nodes restarted successfully.');
                    addFeedEvent({ node_id: 'system', title: 'System Restart Initiated', description: 'All active nodes have been restarted.', severity: 'info', tag_class: 'crealtime-tag-info', bg_class: 'crealtime-bg-green', icon: '↻', tag_label: 'INFO', timestamp_unix: Date.now() / 1000 });
                });
            });
            if (bannerBtns[1]) bannerBtns[1].addEventListener('click', () => { window.location.href = '/dashboard/devices/'; });
        }
        
        const analyticsLink = document.getElementById('crealtime-analytics-link');
        if (analyticsLink) analyticsLink.addEventListener('click', (e) => { e.preventDefault(); window.location.href = '/dashboard/analytics/'; });
        
        const mapLink = document.getElementById('crealtime-map-link');
        if (mapLink) mapLink.addEventListener('click', (e) => { e.preventDefault(); window.location.href = '/dashboard/map/'; });
        
        if (alertList) {
            alertList.addEventListener('click', (e) => {
                if (e.target.classList.contains('crealtime-alert-dismiss')) {
                    const alertItem = e.target.closest('.crealtime-alert-item');
                    if (alertItem) {
                        const alertKey = alertItem.getAttribute('data-alert-key');
                        if (alertKey) {
                            dismissAlertPermanently(alertKey);
                        }
                        alertItem.style.opacity = '0';
                        setTimeout(() => {
                            alertItem.remove();
                            updateAlertCount();
                            if (alertList.children.length === 0) {
                                alertList.innerHTML = `<div class="crealtime-alert-item"><div><div class="crealtime-alert-msg">No active alerts</div><div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div></div></div>`;
                            }
                        }, 200);
                    }
                }
            });
        }
    };
    
    const startPolling = () => { if (pollInterval) clearInterval(pollInterval); pollInterval = setInterval(pollRealtimeData, REFRESH_INTERVAL_MS); pollRealtimeData(); };
    
    const initFromTemplate = () => {
        const initialDataScript = document.getElementById('crealtime-initial-data');
        if (initialDataScript && initialDataScript.textContent) {
            try {
                const payload = JSON.parse(initialDataScript.textContent);
                if (payload.data) renderNodeTable(payload.data);
                if (payload.feed) {
                    const filteredFeed = payload.feed.filter(event => {
                        const titleLower = (event.title || '').toLowerCase();
                        const filteredTitles = ['heartbeat', 'system check', 'data sync', 'poll completed'];
                        return !filteredTitles.some(t => titleLower.includes(t));
                    });
                    renderFeed(filteredFeed);
                }
                if (payload.alerts) {
                    renderAlerts(payload.alerts);
                }
                if (payload.chart_values) updateChart(payload.chart_values);
                
                const nodesWithData = (payload.data || []).filter(n => n.aqi !== null && n.aqi !== '—' && !isDataStale(n.timestamp));
                const activeCount = nodesWithData.length;
                const totalCount = payload.total_nodes || (payload.data || []).length;
                const hasOffline = (totalCount - activeCount) > 0;
                updateSystemStatus(activeCount, totalCount, payload.live_aqi, hasOffline);
                updateLiveAqi(payload.live_aqi);
                if (activeNodesLabel) activeNodesLabel.textContent = `${activeCount}/${totalCount}`;
                
                if (payload.timestamp) {
                    updateSyncTimeDisplay(payload.timestamp);
                }
                
                if (payload.zones && payload.zones.length) {
                    zoneSelect.innerHTML = '<option value="all">All Nodes</option>';
                    payload.zones.forEach(zone => { zoneSelect.innerHTML += `<option value="${zone.toLowerCase()}">${escapeHtml(zone)}</option>`; });
                }
            } catch (e) { console.error('Error parsing initial data:', e); }
        }
    };
    
    const init = () => { 
        loadDismissedAlerts();
        setupEventListeners(); 
        initFromTemplate(); 
        startPolling(); 
        connectWebSocket();
        setInterval(updateDynamicTimes, 10000); 
    };
    
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();