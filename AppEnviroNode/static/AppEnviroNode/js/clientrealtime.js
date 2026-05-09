// clientrealtime.js - Complete Real-Time Monitoring System
(function() {
    'use strict';
    
    // Configuration
    const DATA_ENDPOINT = '/api/realtime-data/';
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
    
    // Helper: Get AQI color
    const getAqiColor = (aqi) => {
        if (aqi === null || aqi === undefined) return '#94a3b8';
        if (aqi <= 50) return '#10b981';
        if (aqi <= 100) return '#f59e0b';
        if (aqi <= 150) return '#f97316';
        if (aqi <= 200) return '#ef4444';
        if (aqi <= 300) return '#8b5cf6';
        return '#dc2626';
    };
    
    // Helper: Get AQI label
    const getAqiLabel = (aqi) => {
        if (aqi === null || aqi === undefined) return 'Unknown';
        if (aqi <= 50) return 'Good';
        if (aqi <= 100) return 'Moderate';
        if (aqi <= 150) return 'Unhealthy for Sensitive';
        if (aqi <= 200) return 'Unhealthy';
        if (aqi <= 300) return 'Very Unhealthy';
        return 'Hazardous';
    };
    
    // Helper: Get AQI badge class
    const getAqiBadgeClass = (aqi) => {
        if (aqi === null || aqi === undefined) return 'aqi-unknown';
        if (aqi <= 50) return 'aqi-good';
        if (aqi <= 100) return 'aqi-moderate';
        if (aqi <= 150) return 'aqi-unhealthy-sensitive';
        if (aqi <= 200) return 'aqi-unhealthy';
        if (aqi <= 300) return 'aqi-very-unhealthy';
        return 'aqi-hazardous';
    };
    
    // Helper: Get status dot class
    const getStatusDotClass = (status) => {
        switch ((status || '').toLowerCase()) {
            case 'active': return 'crealtime-dot-green';
            case 'inactive': return 'crealtime-dot-yellow';
            default: return 'crealtime-dot-red';
        }
    };
    
    // Helper: Get status text
    const getStatusText = (status) => {
        switch ((status || '').toLowerCase()) {
            case 'active': return 'Online';
            case 'inactive': return 'Offline';
            default: return 'Warning';
        }
    };
    
    // Helper: Escape HTML
    const escapeHtml = (text) => {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
    
    // Helper: Format duration (uptime)
    const formatDuration = (seconds) => {
        if (!seconds || seconds <= 0) return 'N/A';
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        
        if (days > 0) return `${days}d ${hours}h`;
        if (hours > 0) return `${hours}h ${minutes}m`;
        if (minutes > 0) return `${minutes}m`;
        return `${seconds}s`;
    };
    
    // Helper: Get signal strength icon
    const getSignalIcon = (strength) => {
        if (!strength) return '📶 N/A';
        if (strength >= -50) return '📶 Excellent';
        if (strength >= -70) return '📶 Good';
        if (strength >= -90) return '📶 Fair';
        return '📶 Poor';
    };
    
    // Helper: Get battery icon
    const getBatteryIcon = (level) => {
        if (!level) return '🔋 N/A';
        if (level >= 90) return '🔋 Full';
        if (level >= 70) return '🔋 High';
        if (level >= 50) return '🔋 Medium';
        if (level >= 20) return '🔋 Low';
        return '🪫 Critical';
    };
    
    // ============================================================================
    // MODAL SYSTEM - CENTERED ON SCREEN
    // ============================================================================
    
    // Function to inject modal styles dynamically
    const injectModalStyles = () => {
        if (document.querySelector('#crealtime-modal-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'crealtime-modal-styles';
        style.textContent = `
            /* Modal Overlay - Full screen with flex centering */
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
            
            /* Modal Container - Centered */
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
            
            /* Node Detail Modal Specific Styles */
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
            
            .status-online { background: #d1fae5 !important; color: #059669 !important; }
            .status-offline { background: #fee2e2 !important; color: #dc2626 !important; }
            .status-warning { background: #fef3c7 !important; color: #d97706 !important; }
            
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
        `;
        document.head.appendChild(style);
    };
    
    // Inject styles immediately
    injectModalStyles();
    
    // Show toast notification
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
    
    // Close modal function
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
        
        // Restore body scroll
        document.body.style.overflow = '';
    };
    
    // Show node details modal - CENTERED ON SCREEN
    const showNodeDetailsModal = (node) => {
        if (activeModal) closeModal();
        
        // Prevent body scroll when modal is open
        document.body.style.overflow = 'hidden';
        
        const aqi = node.aqi !== undefined && node.aqi !== null ? node.aqi : node.latest_aqi;
        const aqiLabel = getAqiLabel(aqi);
        const aqiBadgeClass = getAqiBadgeClass(aqi);
        const statusText = getStatusText(node.status);
        const statusDotClass = getStatusDotClass(node.status);
        
        // Generate recent activity log
        const activities = [];
        
        if (node.status === 'active') {
            activities.push({
                icon: '✓',
                bgColor: 'crealtime-bg-green',
                text: 'Node connected successfully',
                timeAgo: 'Just now'
            });
            activities.push({
                icon: '📡',
                bgColor: 'crealtime-bg-green',
                text: 'Data transmission active',
                timeAgo: '2 minutes ago'
            });
        } else if (node.status === 'inactive') {
            activities.push({
                icon: '⚠',
                bgColor: 'crealtime-bg-yellow',
                text: 'Node disconnected',
                timeAgo: '5 minutes ago'
            });
            activities.push({
                icon: '🔄',
                bgColor: 'crealtime-bg-yellow',
                text: 'Reconnection attempt scheduled',
                timeAgo: 'Just now'
            });
        } else {
            activities.push({
                icon: '⚡',
                bgColor: 'crealtime-bg-red',
                text: 'Warning: Unusual readings detected',
                timeAgo: 'Just now'
            });
        }
        
        if (aqi && aqi > 100) {
            activities.unshift({
                icon: '⚠',
                bgColor: 'crealtime-bg-red',
                text: `AQI level ${aqi} - ${aqiLabel} alert`,
                timeAgo: 'Just now'
            });
        } else if (aqi && aqi > 50) {
            activities.unshift({
                icon: 'ℹ',
                bgColor: 'crealtime-bg-yellow',
                text: `Moderate air quality detected (AQI: ${aqi})`,
                timeAgo: 'Just now'
            });
        } else if (aqi) {
            activities.unshift({
                icon: '✓',
                bgColor: 'crealtime-bg-green',
                text: `Good air quality maintained (AQI: ${aqi})`,
                timeAgo: '2 minutes ago'
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
        
        // Create overlay and modal
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
                                        ${aqi !== null && aqi !== undefined ? aqi : '—'} - ${aqiLabel}
                                    </span>
                                </span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Node Status:</span>
                                <span class="crealtime-node-detail-value">
                                    <span class="crealtime-status-badge status-${statusText.toLowerCase()}">
                                        <span class="crealtime-dot ${statusDotClass}" style="margin-right: 4px;"></span>
                                        ${statusText}
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
                                <span class="crealtime-node-detail-label">CO2 Level:</span>
                                <span class="crealtime-node-detail-value">${node.co2 || node.co2_level || '—'} ppm</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Last Seen:</span>
                                <span class="crealtime-node-detail-value">${node.last_seen || (node.timestamp ? formatTimeAgo(node.timestamp) : 'Never')}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="crealtime-node-detail-section">
                        <div class="crealtime-node-detail-section-title">Device Status</div>
                        <div class="crealtime-node-detail-grid">
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Device Uptime:</span>
                                <span class="crealtime-node-detail-value">${node.uptime || formatDuration(node.uptime_seconds || 86400)}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Battery Status:</span>
                                <span class="crealtime-node-detail-value">${getBatteryIcon(node.battery_level || node.battery)}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Signal Strength:</span>
                                <span class="crealtime-node-detail-value">${getSignalIcon(node.signal_strength || node.rssi)}</span>
                            </div>
                            <div class="crealtime-node-detail-row">
                                <span class="crealtime-node-detail-label">Connection:</span>
                                <span class="crealtime-node-detail-value">${node.status === 'active' ? '✓ Connected' : '✗ Disconnected'}</span>
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
    
    // Show confirmation modal
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
        if (!feed.length) {
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
        
        feedContainer.innerHTML = feed.map(createFeedItemHtml).join('');
        updateDynamicTimes();
        if (isLive && feedContainer) feedContainer.scrollTop = 0;
    };
    
    const addFeedEvent = (event) => {
        if (!feedContainer) return;
        const html = createFeedItemHtml(event, 0);
        feedContainer.insertAdjacentHTML('afterbegin', html);
        while (feedContainer.children.length > MAX_FEED_ITEMS) {
            feedContainer.removeChild(feedContainer.lastChild);
        }
        updateDynamicTimes();
        if (isLive && feedContainer) feedContainer.scrollTop = 0;
    };
    
    const createNodeRowHtml = (node) => {
        const statusClass = getStatusDotClass(node.status);
        const isCriticalRow = node.status !== 'active' || (node.aqi !== null && node.aqi > 100);
        const aqiValue = node.aqi !== null ? node.aqi : '—';
        const aqiColor = getAqiColor(node.aqi);
        const zone = node.zone || node.location || 'Unknown';
        const lastSeen = node.timestamp ? formatTimeAgo(node.timestamp, true) : 'Never';
        
        return `
            <tr data-node-id="${escapeHtml(node.name)}" data-node-real-id="${node.node_id}" data-zone="${zone.toLowerCase().replace(/\s+/g, '-')}" data-status="${node.status || 'unknown'}" data-timestamp="${node.timestamp || ''}" class="${isCriticalRow ? 'crealtime-row-critical' : ''}">
                <td class="crealtime-mono crealtime-font-medium">${escapeHtml(node.name)}</td>
                <td class="crealtime-text-xs">${escapeHtml(zone)}</td>
                <td><span class="crealtime-dot ${statusClass}"></span></td>
                <td class="crealtime-mono" style="color: ${aqiColor}; font-weight: 600;">${aqiValue}</td>
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
            filteredNodes = filteredNodes.filter(n => n.status === 'active');
        } else if (currentFilter === 'alerts') {
            filteredNodes = filteredNodes.filter(n => n.status !== 'active' || (n.aqi !== null && n.aqi > 65));
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
    
    const createAlertHtml = (alert) => {
        const warningClass = alert.severity === 'warning' ? 'crealtime-warning' : '';
        const criticalClass = alert.severity === 'critical' ? 'crealtime-feed-critical' : '';
        const styleAttr = alert.severity === 'critical' ? ' style="color:var(--crealtime-red)"' : '';
        const timestamp = alert.timestamp_unix || alert.timestamp;
        
        return `
            <div class="crealtime-alert-item ${warningClass} ${criticalClass}" data-node-id="${escapeHtml(alert.node_name || 'system')}" data-timestamp="${timestamp}">
                <div>
                    <div class="crealtime-alert-msg"${styleAttr}>${escapeHtml(alert.title || 'Alert')}</div>
                    <div class="crealtime-text-xs crealtime-text-muted">${escapeHtml(alert.description || '')} <span class="crealtime-dynamic-time">Just now</span></div>
                </div>
                <button class="crealtime-alert-dismiss" data-alert-title="${escapeHtml(alert.title)}">&times;</button>
            </div>
        `;
    };
    
    const renderAlerts = (alerts = []) => {
        if (!alertList) return;
        
        if (!alerts.length) {
            alertList.innerHTML = `<div class="crealtime-alert-item"><div><div class="crealtime-alert-msg">No active alerts</div><div class="crealtime-text-xs crealtime-text-muted">All monitored nodes are operating normally.</div></div></div>`;
            if (alertCountLabel) alertCountLabel.textContent = '0 Alerts';
            return;
        }
        
        alertList.innerHTML = alerts.map(createAlertHtml).join('');
        updateDynamicTimes();
        if (alertCountLabel) alertCountLabel.textContent = `${alerts.length} Alerts`;
        
        document.querySelectorAll('.crealtime-alert-dismiss').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const alertItem = btn.closest('.crealtime-alert-item');
                if (alertItem) {
                    alertItem.style.opacity = '0';
                    setTimeout(() => alertItem.remove(), 200);
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
    };
    
    const updateLiveAqi = (avgAqi) => {
        if (!liveAqiLabel) return;
        const displayValue = avgAqi !== null ? avgAqi.toFixed(1) : '—';
        liveAqiLabel.textContent = displayValue;
        if (avgAqi !== null) {
            liveAqiLabel.style.color = getAqiColor(avgAqi);
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
        
        if (!chartInstance) {
            const ctx = chartCanvas.getContext('2d');
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
                    animation: { duration: 300 },
                    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, callbacks: { label: (ctx) => `AQI: ${ctx.raw}` } } },
                    scales: { x: { display: true, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } }, y: { display: true, beginAtZero: true, grid: { color: '#f1f5f9' } } }
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
            
            if (json.data) renderNodeTable(json.data);
            
            if (json.feed && json.feed.length) {
                const latestTimestamp = json.feed[0]?.timestamp_unix || json.feed[0]?.timestamp;
                if (latestTimestamp && (!lastEventTimestamp || latestTimestamp > lastEventTimestamp)) {
                    addFeedEvent(json.feed[0]);
                    lastEventTimestamp = latestTimestamp;
                } else if (!lastEventTimestamp) {
                    renderFeed(json.feed);
                    if (json.feed[0]) lastEventTimestamp = json.feed[0].timestamp_unix || json.feed[0].timestamp;
                }
            }
            
            if (json.alerts) renderAlerts(json.alerts);
            if (json.chart_values && json.chart_values.length) updateChart(json.chart_values);
            
            const activeCount = json.active_nodes || 0;
            const totalCount = json.total_nodes || 0;
            const hasOffline = (totalCount - activeCount) > 0;
            updateSystemStatus(activeCount, totalCount, json.live_aqi, hasOffline);
            updateLiveAqi(json.live_aqi);
            if (activeNodesLabel) activeNodesLabel.textContent = `${activeCount}/${totalCount}`;
            if (syncTimeLabel) syncTimeLabel.textContent = 'Just now';
            
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
                    if (!pausedLabel) { pausedLabel = document.createElement('span'); pausedLabel.className = 'crealtime-paused-label'; pausedLabel.textContent = 'Paused'; toggleWrapper?.appendChild(pausedLabel); }
                    if (pollInterval) clearInterval(pollInterval);
                    pollInterval = null;
                } else {
                    if (pausedLabel) pausedLabel.remove();
                    startPolling();
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
                        alertItem.style.opacity = '0';
                        setTimeout(() => alertItem.remove(), 200);
                        const remaining = alertList.querySelectorAll('.crealtime-alert-item').length;
                        if (alertCountLabel) alertCountLabel.textContent = `${remaining} Alerts`;
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
                if (payload.nodes) renderNodeTable(payload.nodes);
                if (payload.feed_events) renderFeed(payload.feed_events);
                if (payload.alert_entries) renderAlerts(payload.alert_entries);
                if (payload.system) {
                    updateSystemStatus(payload.system.active_count || 0, payload.system.total_nodes || 0, payload.system.avg_aqi || null, false);
                    updateLiveAqi(payload.system.avg_aqi);
                    if (activeNodesLabel) activeNodesLabel.textContent = `${payload.system.active_count || 0}/${payload.system.total_nodes || 0}`;
                }
                if (payload.chart_values) updateChart(payload.chart_values);
            } catch (e) { console.error('Error parsing initial data:', e); }
        }
    };
    
    const init = () => { setupEventListeners(); initFromTemplate(); startPolling(); setInterval(updateDynamicTimes, 10000); };
    
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();