/**
 * dashboard-spatial-context.js
 * Dedicated Spatial Context Manager for Dashboard Map
 */

(function() {
    'use strict';

    const CONFIG = {
        MAP_CONTAINER_ID: 'cdashboard-real-map',
        MAP_CENTER: [14.5631, 121.0192],
        MAP_ZOOM: 12,
        MARKER_SIZE: 32
    };

    const SpatialContextState = {
        map: null,
        allNodes: [],
        activeCount: 0,
        offlineCount: 0,
        avgAqi: null,
        isInitialized: false
    };

    function getAqiColorClass(aqi) {
        if (aqi === null || aqi === undefined || isNaN(aqi)) return 'offline';
        if (aqi <= 50) return 'good';
        if (aqi <= 100) return 'moderate';
        if (aqi <= 150) return 'sensitive';
        if (aqi <= 200) return 'unhealthy';
        if (aqi <= 300) return 'very-unhealthy';
        return 'hazardous';
    }

    function getAqiColorHex(aqi) {
        if (aqi === null || aqi === undefined || isNaN(aqi)) return '#94a3b8';
        if (aqi <= 50) return '#10b981';
        if (aqi <= 100) return '#f59e0b';
        if (aqi <= 150) return '#f97316';
        if (aqi <= 200) return '#ef4444';
        if (aqi <= 300) return '#8b5cf6';
        return '#7f1d1d';
    }

    function getAqiLabel(aqi) {
        if (aqi === null || aqi === undefined || isNaN(aqi)) return 'No Data';
        if (aqi <= 50) return 'Good';
        if (aqi <= 100) return 'Moderate';
        if (aqi <= 150) return 'Unhealthy for Sensitive';
        if (aqi <= 200) return 'Unhealthy';
        if (aqi <= 300) return 'Very Unhealthy';
        return 'Hazardous';
    }

    function formatRelativeTime(timestamp) {
        if (!timestamp) return 'Never';
        const date = new Date(timestamp);
        if (isNaN(date.getTime())) return 'Unknown';
        const now = new Date();
        const diffMins = Math.floor((now - date) / 60000);
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays}d ago`;
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function initMap() {
        const mapContainer = document.getElementById(CONFIG.MAP_CONTAINER_ID);
        if (!mapContainer) {
            console.error('[SpatialContext] Map container not found');
            return false;
        }

        if (SpatialContextState.map) {
            SpatialContextState.map.remove();
            SpatialContextState.map = null;
        }

        try {
            SpatialContextState.map = L.map(mapContainer).setView(CONFIG.MAP_CENTER, CONFIG.MAP_ZOOM);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '© OpenStreetMap contributors'
            }).addTo(SpatialContextState.map);
            console.log('[SpatialContext] Map initialized');
            return true;
        } catch (error) {
            console.error('[SpatialContext] Map init failed:', error);
            mapContainer.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; background: #f1f5f9; color: #64748b; font-size: 12px;">Map unavailable</div>';
            return false;
        }
    }

    function renderMarkers() {
        if (!SpatialContextState.map) {
            console.warn('[SpatialContext] Map not initialized');
            return;
        }

        // Clear existing markers
        SpatialContextState.map.eachLayer(function(layer) {
            if (layer instanceof L.Marker) {
                SpatialContextState.map.removeLayer(layer);
            }
        });

        const nodes = window.CDASHBOARD_NODES || [];
        
        console.log('[SpatialContext] Total nodes from Django:', nodes.length);
        
        if (!nodes || nodes.length === 0) {
            console.warn('[SpatialContext] No node data available');
            document.getElementById('mapActiveCount').textContent = '0';
            document.getElementById('mapOfflineCount').textContent = '0';
            document.getElementById('mapAvgAqi').textContent = '—';
            
            // Show message on map
            const mapContainer = document.getElementById(CONFIG.MAP_CONTAINER_ID);
            if (mapContainer && mapContainer.querySelector('.leaflet-container')) {
                // Map already has tiles, just show no data message as popup or leave as is
            }
            return;
        }

        let activeCount = 0;
        let offlineCount = 0;
        let totalAqi = 0;
        let aqiCount = 0;
        let markersAdded = 0;
        const boundsPoints = [];

        nodes.forEach(node => {
            const lat = node.latitude || node.lat;
            const lng = node.longitude || node.lng;
            
            console.log('[SpatialContext] Node:', node.name, 'lat:', lat, 'lng:', lng);
            
            // Skip nodes without valid coordinates
            if (!lat || !lng || typeof lat !== 'number' || typeof lng !== 'number') {
                console.log('[SpatialContext] Skipping node without coordinates:', node.name);
                return;
            }

            boundsPoints.push([lat, lng]);

            const isActive = node.status === 'active' || node.status === 'online';
            const aqi = node.aqi !== undefined && node.aqi !== null ? node.aqi : null;

            if (isActive) activeCount++;
            else offlineCount++;

            if (aqi !== null && !isNaN(aqi)) {
                totalAqi += aqi;
                aqiCount++;
            }

            const colorClass = getAqiColorClass(aqi);
            const displayValue = aqi !== null && !isNaN(aqi) ? Math.round(aqi) : 'N/A';
            
            const markerHtml = `<div class="cd-dashboard-marker ${colorClass}">${displayValue}</div>`;
            const icon = L.divIcon({
                html: markerHtml,
                className: '',
                iconSize: [CONFIG.MARKER_SIZE, CONFIG.MARKER_SIZE],
                popupAnchor: [0, -CONFIG.MARKER_SIZE / 2]
            });

            const isActiveText = isActive ? '✅ Active' : '⚠️ Offline';
            const popupContent = `
                <div style="font-family: 'Inter', sans-serif; padding: 8px; min-width: 200px;">
                    <strong style="font-size: 13px; display: block; margin-bottom: 8px;">${escapeHtml(node.name || 'Unknown Node')}</strong>
                    <div style="font-size: 11px; margin-bottom: 6px;">
                        <span style="color: #666;">📍 Location:</span> ${escapeHtml(node.location || 'Not specified')}
                    </div>
                    <div style="font-size: 11px; margin-bottom: 6px;">
                        <span style="color: #666;">📊 AQI:</span> 
                        <strong style="color: ${getAqiColorHex(aqi)};">${aqi !== null ? Math.round(aqi) : 'N/A'}</strong> 
                        (${getAqiLabel(aqi)})
                    </div>
                    <div style="font-size: 11px; margin-bottom: 6px;">
                        <span style="color: #666;">🔌 Status:</span> ${isActiveText}
                    </div>
                    ${node.last_seen ? `<div style="font-size: 10px; color: #888; margin-top: 6px; border-top: 1px solid #e5e7eb; padding-top: 4px;">🕐 Last seen: ${formatRelativeTime(node.last_seen)}</div>` : ''}
                </div>
            `;

            const marker = L.marker([lat, lng], { icon: icon });
            marker.bindPopup(popupContent);
            marker.addTo(SpatialContextState.map);
            markersAdded++;
        });

        SpatialContextState.activeCount = activeCount;
        SpatialContextState.offlineCount = offlineCount;
        SpatialContextState.avgAqi = aqiCount > 0 ? Math.round(totalAqi / aqiCount) : null;

        // Update UI
        document.getElementById('mapActiveCount').textContent = activeCount;
        document.getElementById('mapOfflineCount').textContent = offlineCount;
        document.getElementById('mapAvgAqi').textContent = SpatialContextState.avgAqi !== null ? SpatialContextState.avgAqi : '—';

        // Update status tag
        const statusTag = document.getElementById('mapStatusTag');
        if (statusTag) {
            if (offlineCount > 0) {
                statusTag.className = 'cd-time-tag ongoing';
                statusTag.textContent = '⚠️ PARTIAL';
            } else if (activeCount === 0) {
                statusTag.className = 'cd-time-tag new';
                statusTag.textContent = '⚠️ NO DATA';
            } else {
                statusTag.className = 'cd-time-tag stable';
                statusTag.textContent = 'LIVE';
            }
        }

        // Auto-fit bounds if we have markers
        if (boundsPoints.length > 0) {
            try {
                const bounds = L.latLngBounds(boundsPoints);
                if (bounds.isValid()) {
                    SpatialContextState.map.fitBounds(bounds, { padding: [50, 50] });
                }
            } catch (e) {
                console.warn('[SpatialContext] Could not fit bounds:', e);
            }
        }

        console.log(`[SpatialContext] Rendered ${markersAdded} markers (${activeCount} active, ${offlineCount} offline)`);
    }

    function updateActivityFeed() {
        const container = document.getElementById('mapRecentActivity');
        if (!container) return;

        const nodes = window.CDASHBOARD_NODES || [];
        const recentActivities = [];
        const now = Date.now();

        nodes.forEach(node => {
            const lastSeen = node.last_seen || node.timestamp;
            if (lastSeen) {
                const lastSeenDate = new Date(lastSeen);
                if (!isNaN(lastSeenDate.getTime())) {
                    const minutesAgo = Math.floor((now - lastSeenDate) / 60000);
                    if (minutesAgo < 60) {
                        const isActive = node.status === 'active' || node.status === 'online';
                        recentActivities.push({
                            nodeName: node.name || 'Unknown',
                            activity: isActive ? (minutesAgo < 5 ? 'Data reported' : 'Online') : 'Offline',
                            time: minutesAgo,
                            dotClass: isActive ? 'green' : 'red'
                        });
                    }
                }
            }
        });

        recentActivities.sort((a, b) => a.time - b.time);
        const latest = recentActivities.slice(0, 5);

        if (latest.length === 0) {
            container.innerHTML = '<div class="cd-activity-item"><span class="cd-activity-text">No recent node activity</span></div>';
        } else {
            container.innerHTML = latest.map(act => `
                <div class="cd-activity-item">
                    <div class="cd-activity-dot ${act.dotClass}"></div>
                    <span class="cd-activity-text">${escapeHtml(act.nodeName)} — ${act.activity}</span>
                    <span class="cd-activity-time">${act.time === 0 ? 'Just now' : `${act.time}m ago`}</span>
                </div>
            `).join('');
        }
    }

    function loadNodesFromApi() {
        console.log('[SpatialContext] Attempting to fetch nodes from API...');
        fetch('/api/dashboard/nodes/?limit=200')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.nodes && data.nodes.length > 0) {
                    console.log('[SpatialContext] Loaded', data.nodes.length, 'nodes from API');
                    const formattedNodes = data.nodes.map(item => ({
                        id: item.node.id,
                        name: item.node.name,
                        location: item.node.location,
                        latitude: item.node.latitude,
                        longitude: item.node.longitude,
                        status: item.node.status,
                        aqi: item.pollutants.aqi,
                        last_seen: null
                    }));
                    window.CDASHBOARD_NODES = formattedNodes;
                    renderMarkers();
                    updateActivityFeed();
                } else {
                    console.warn('[SpatialContext] API returned no nodes, using template data');
                    if (window.CDASHBOARD_NODES && window.CDASHBOARD_NODES.length > 0) {
                        renderMarkers();
                        updateActivityFeed();
                    }
                }
            })
            .catch(err => {
                console.warn('[SpatialContext] API fetch failed:', err);
                if (window.CDASHBOARD_NODES && window.CDASHBOARD_NODES.length > 0) {
                    renderMarkers();
                    updateActivityFeed();
                }
            });
    }

    function initSpatialContext() {
        if (SpatialContextState.isInitialized) {
            console.warn('[SpatialContext] Already initialized');
            return;
        }

        console.log('[SpatialContext] Initializing...');

        if (typeof L === 'undefined') {
            console.error('[SpatialContext] Leaflet not loaded');
            const mapContainer = document.getElementById(CONFIG.MAP_CONTAINER_ID);
            if (mapContainer) {
                mapContainer.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; background: #f1f5f9; color: #64748b; font-size: 12px;">Leaflet library not loaded. Please refresh.</div>';
            }
            return;
        }

        const mapInitialized = initMap();
        if (!mapInitialized) return;

        // Check if we have nodes in the template data
        if (window.CDASHBOARD_NODES && window.CDASHBOARD_NODES.length > 0) {
            console.log('[SpatialContext] Using template data, nodes:', window.CDASHBOARD_NODES.length);
            setTimeout(() => {
                renderMarkers();
                updateActivityFeed();
                if (SpatialContextState.map) {
                    SpatialContextState.map.invalidateSize();
                }
            }, 200);
        } else {
            console.log('[SpatialContext] No template data, fetching from API...');
            setTimeout(() => {
                loadNodesFromApi();
                if (SpatialContextState.map) {
                    SpatialContextState.map.invalidateSize();
                }
            }, 200);
        }

        SpatialContextState.isInitialized = true;
    }

    function handleVisibilityChange() {
        if (!document.hidden && SpatialContextState.map) {
            setTimeout(() => {
                if (SpatialContextState.map) {
                    SpatialContextState.map.invalidateSize();
                }
            }, 100);
        }
    }

    function handleWindowResize() {
        if (SpatialContextState.map) {
            setTimeout(() => {
                if (SpatialContextState.map) {
                    SpatialContextState.map.invalidateSize();
                }
            }, 200);
        }
    }

    window.SpatialContext = {
        init: initSpatialContext,
        refresh: renderMarkers,
        getStats: () => ({
            active: SpatialContextState.activeCount,
            offline: SpatialContextState.offlineCount,
            avgAqi: SpatialContextState.avgAqi
        })
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSpatialContext);
    } else {
        initSpatialContext();
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('resize', handleWindowResize);
})();