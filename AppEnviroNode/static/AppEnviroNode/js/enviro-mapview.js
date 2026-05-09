// enviro-mapview.js
// Enhanced dynamic map rendering for admin/clientmapview.html
// Robust Leaflet integration with defensive programming
// STRICT: do not change existing CSS class names

(function() {
  'use strict';

  // === SAFETY CHECK: Ensure Leaflet is loaded ===
  if (typeof L === 'undefined') {
    console.error('[MapView] Leaflet library not found. Map will not initialize.');
    return;
  }

  // === CONFIG ===
  const CONFIG = {
    MAP_CONTAINER_ID: 'cmapv-leaflet-map',
    DRILLDOWN_PANEL_ID: 'cmapv-drilldown-panel',
    LEGEND_ID: 'cmapv-map-legend',
    LAYER_SELECT_ID: 'cmapv-layer-select',
    TOGGLE_ACTIVE_ID: 'cmapv-toggle-active',
    TOGGLE_INACTIVE_ID: 'cmapv-toggle-inactive',
    TOGGLE_ROGUE_ID: 'cmapv-toggle-rogue',
    TOGGLE_UNREGISTERED_ID: 'cmapv-toggle-unregistered',
    BTN_LIVE_ID: 'cmapv-btn-live',
    BTN_24H_ID: 'cmapv-btn-24h',
    MAP_CENTER: [14.5631, 121.0192],
    MAP_ZOOM: 14,
    API_TIMEOUT: 8000,
    MAX_NODES: 200,        // FIX #4: Hard limit to prevent DOM bloat
    MAX_AQI_HISTORY: 24,   // FIX #5: Limit chart points
    VIEWPORT_FETCH_DEBOUNCE: 300  // FIX #7: Debounce viewport-based fetches
  };

  // === STATE ===
  const STATE = {
    map: null,
    leafletMarkers: [],
    markerLayerGroup: null,
    markersByNodeId: new Map(),  // OPTIMIZATION: Cache markers by node ID for reuse
    nodeDataByNodeId: new Map(),  // OPTIMIZATION: Cache node data by node ID
    allNodes: [],
    uniqueNodeIds: new Set(),  // FIX #1: Deduplication tracking
    currentLayer: 'aqi',
    overlays: { active: true, inactive: true, rogue: true, unregistered: true },
    timeframe: 'live',
    selectedNodeId: null,
    isLoading: false,
    isFetching: false,
    renderScheduleTimer: null,
    viewportFetchTimer: null,  // FIX #7: Viewport fetch debounce
    hasAutoCentered: false,
    fetchController: null,
    lastViewportBounds: null   // FIX #7: Track viewport to avoid redundant fetches
  };

  // === UTILITY: Safe data extraction ===
  const SafeData = {
    getNode: (nodeObj) => {
      return nodeObj && typeof nodeObj === 'object' ? nodeObj.node : null;
    },
    getPollutants: (nodeObj) => {
      return nodeObj && typeof nodeObj === 'object' && nodeObj.pollutants ? nodeObj.pollutants : {};
    },
    getLatestReading: (nodeObj) => {
      return nodeObj && typeof nodeObj === 'object' && nodeObj.latest_reading ? nodeObj.latest_reading : null;
    },
    getSafeValue: (value, fallback = 'N/A') => {
      return value !== null && value !== undefined ? value : fallback;
    },
    getCoordinates: (node) => {
      if (!node || typeof node !== 'object') return null;
      const lat = node.latitude;
      const lng = node.longitude;
      if (lat === null || lat === undefined || lng === null || lng === undefined) return null;
      if (typeof lat !== 'number' || typeof lng !== 'number') return null;
      return [lat, lng];
    },
    isOffline: (latestReading) => {
      // FIX: Consider node offline if no reading or no timestamp
      return !latestReading || !latestReading.timestamp;
    }
  };

  // === COLOR & CLASSIFICATION ===
  const Colors = {
    getColorForValue: (value, layer = 'aqi', isOffline = false) => {
      // FIX: Offline nodes always render gray
      if (isOffline || value === null || value === undefined) {
        return '#7f8c8d';  // gray
      }
      
      value = value ?? 0;
      
      if (layer === 'aqi') {
        if (value <= 50) return '#2ecc71';  // green
        if (value <= 100) return '#f1c40f'; // yellow
        if (value <= 150) return '#e67e22'; // orange
        if (value <= 200) return '#e74c3c'; // red
        if (value <= 300) return '#c0392b'; // dark red
        return '#8b0000';                    // maroon
      }
      
      if (layer === 'pm25' || layer === 'pm10') {
        const thresholds = layer === 'pm25' ? 
          [[12, '#2ecc71'], [35, '#f1c40f'], [55, '#e67e22'], [150, '#e74c3c'], [Infinity, '#c0392b']] :
          [[54, '#2ecc71'], [154, '#f1c40f'], [254, '#e67e22'], [354, '#e74c3c'], [Infinity, '#c0392b']];
        for (const [threshold, color] of thresholds) {
          if (value <= threshold) return color;
        }
      }
      
      if (layer === 'temperature') {
        if (value < 25) return '#2ecc71';
        if (value <= 30) return '#f1c40f';
        if (value <= 35) return '#e67e22';
        if (value <= 40) return '#e74c3c';
        return '#c0392b';
      }
      
      return '#95a5a6'; // gray fallback
    },

    getAQIClass: (aqi) => {
      aqi = aqi ?? 0;
      if (aqi <= 50) return 'cmapv-good';
      if (aqi <= 100) return 'cmapv-warning';
      if (aqi <= 150) return 'cmapv-unhealthy-sensitive';
      if (aqi <= 200) return 'cmapv-unhealthy';
      if (aqi <= 300) return 'cmapv-critical';
      return 'cmapv-critical';
    },

    getNodeStatusClass: (nodeStatus) => {
      if (nodeStatus === 'active') return 'cmapv-good';
      if (nodeStatus === 'inactive') return 'cmapv-inactive';
      if (nodeStatus === 'rogue') return 'cmapv-critical';
      if (nodeStatus === 'unregistered') return 'cmapv-warning';
      return 'cmapv-unknown';
    }
  };

  // === FORMATTING ===
  const Format = {
    getBatteryIcon: (battery) => {
      battery = battery ?? 0;
      if (battery >= 90) return 'fa-battery-full';
      if (battery >= 60) return 'fa-battery-three-quarters';
      if (battery >= 30) return 'fa-battery-half';
      if (battery >= 10) return 'fa-battery-quarter';
      return 'fa-battery-empty';
    },

    getLastSeen: (timestamp) => {
      if (!timestamp) return 'N/A';
      try {
        const t = new Date(timestamp);
        if (isNaN(t.getTime())) return 'N/A';
        const now = new Date();
        const diffMs = now - t;
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return 'Just now';
        if (diffMin < 60) return diffMin + 'm ago';
        const diffHour = Math.floor(diffMin / 60);
        if (diffHour < 24) return diffHour + 'h ago';
        return t.toLocaleDateString();
      } catch (e) {
        return 'N/A';
      }
    },

    formatNumber: (num, decimals = 1) => {
      if (num === null || num === undefined) return 'N/A';
      return typeof num === 'number' ? num.toFixed(decimals) : String(num);
    }
  };

  // === FIX #1 & #2: DEDUPLICATION & API-FIRST INITIALIZATION ===
  function deduplicateNodes(nodes) {
    "Deduplicates nodes by unique node.id, keeping first occurrence."
    const seen = new Set();
    const deduplicated = [];
    
    for (const nodeWrapper of nodes) {
      const nodeData = SafeData.getNode(nodeWrapper);
      if (!nodeData || !nodeData.id) continue;  // Skip invalid nodes
      
      if (!seen.has(nodeData.id)) {
        seen.add(nodeData.id);
        deduplicated.push(nodeWrapper);
      } else {
        console.warn(`[MapView] Duplicate node skipped: ${nodeData.id}`);
      }
    }
    
    return deduplicated;
  }

  function initializeData() {
    "FIX #2: Initialize with empty arrays - API is single source of truth."
    try {
      const rawNodes = window.CMAPV_NODES;
      
      // If no data or empty data, start fresh
      if (!rawNodes || typeof rawNodes !== 'object') {
        STATE.allNodes = [];
        STATE.uniqueNodeIds.clear();
        console.log('[MapView] Starting with empty node array (API-first approach)');
        return;
      }
      
      const active = Array.isArray(rawNodes.active) ? rawNodes.active : [];
      const inactive = Array.isArray(rawNodes.inactive) ? rawNodes.inactive : [];
      const unregistered = Array.isArray(rawNodes.unregistered) ? rawNodes.unregistered : [];
      const rogue = Array.isArray(rawNodes.rogue) ? rawNodes.rogue : [];
      
      let mergedNodes = [...active, ...inactive, ...unregistered, ...rogue];
      
      // FIX #1: Deduplicate nodes by ID
      mergedNodes = deduplicateNodes(mergedNodes);
      
      // FIX #4: Hard limit to prevent DOM bloat
      if (mergedNodes.length > CONFIG.MAX_NODES) {
        mergedNodes = mergedNodes.slice(0, CONFIG.MAX_NODES);
        console.warn(`[MapView] Node count limited to ${CONFIG.MAX_NODES} for performance`);
      }
      
      // Update unique ID set
      STATE.uniqueNodeIds.clear();
      mergedNodes.forEach(nodeWrapper => {
        const nodeData = SafeData.getNode(nodeWrapper);
        if (nodeData && nodeData.id) {
          STATE.uniqueNodeIds.add(nodeData.id);
        }
      });
      
      STATE.allNodes = mergedNodes;
      console.log(`[MapView] Loaded ${STATE.allNodes.length} unique nodes`);
    } catch (e) {
      console.error('[MapView] Error initializing data:', e);
      STATE.allNodes = [];
      STATE.uniqueNodeIds.clear();
    }
  }

  // === MARKER RENDERING ===
  // NEW: Dynamic AQI Chart from historical data
  function renderAQIChart(aqiHistory) {
    if (!Array.isArray(aqiHistory) || aqiHistory.length === 0) {
      return '<div style="color:#888;text-align:center;padding:20px;font-size:0.75rem;">No historical data available</div>';
    }

    const validValues = aqiHistory.filter(v => v !== null && v !== undefined && typeof v === 'number');
    if (validValues.length === 0) {
      return '<div style="color:#888;text-align:center;padding:20px;font-size:0.75rem;">No valid data points</div>';
    }

    const max = Math.max(...validValues, 1);

    const bars = aqiHistory.map(val => {
      if (val === null || val === undefined) return '';
      const height = Math.max(10, (val / max) * 100);
      const color = Colors.getColorForValue(val, 'aqi');
      return `<div class="cmapv-chart-bar" style="height:${height}%;background:${color};"></div>`;
    }).join('');

    return `<div class="cmapv-chart-placeholder">${bars}</div>`;
  }

  // === MARKER RENDERING ===
  // OPTIMIZATION: Simplified marker HTML - removes tooltip card (shown in drilldown panel instead)
  function buildMarkerHTML(node, nodeData, pollutants, latestReading, aqi) {
    // FIX: Handle offline nodes with gray color and "N/A" display
    const isOffline = SafeData.isOffline(latestReading);
    const aqiValue = !isOffline && aqi !== null && aqi !== undefined ? Math.round(aqi) : 'N/A';
    const aqlClass = Colors.getAQIClass(aqi);
    // OPTIMIZATION: Ultra-lightweight marker showing only AQI number
    return `<span style="font-weight:800;font-size:11px;line-height:1;">${aqiValue}</span>`;
  }

  // OPTIMIZATION: Debounced marker rendering (150ms throttle)
  function scheduleRenderMarkers() {
    if (STATE.renderScheduleTimer) {
      clearTimeout(STATE.renderScheduleTimer);
    }
    STATE.renderScheduleTimer = setTimeout(() => {
      renderMarkers();
      STATE.renderScheduleTimer = null;
    }, 150);
  }

  function renderMarkers() {
    try {
      // OPTIMIZATION: Reuse layer group instead of recreate
      if (!STATE.markerLayerGroup) {
        STATE.markerLayerGroup = L.markerClusterGroup(); // Use clustering instead of featureGroup
        STATE.markerLayerGroup.addTo(STATE.map);
      }
      // NOTE: Do NOT clearLayers() - instead use differential updates below

      // FIX #3: Implement actual viewport bounds checking
      const bounds = STATE.map.getBounds();
      
      const nodesToRender = STATE.allNodes.filter(nodeWrapper => {
        // FIX #4: Validate node structure - defensive safeguards
        const nodeData = SafeData.getNode(nodeWrapper);
        if (!nodeData || typeof nodeData !== 'object') return false;

        // Check coordinates
        const coords = SafeData.getCoordinates(nodeData);
        if (!coords) return false;

        // FIX #3: Only render markers inside current viewport bounds
        const latlng = L.latLng(coords[0], coords[1]);
        if (!bounds.contains(latlng)) {
          return false;  // Outside viewport
        }

        // Filter by status visibility toggles
        const status = nodeData.status || 'unknown';
        if (!STATE.overlays[status]) {
          return false;
        }

        return true;
      });

      console.log(`[MapView] Rendering ${nodesToRender.length} markers (filtered from ${STATE.allNodes.length})`);

      // OPTIMIZATION: Track which nodes should be rendered
      const nodesToRenderIds = new Set();

      nodesToRender.forEach((nodeWrapper) => {
        try {
          const nodeData = SafeData.getNode(nodeWrapper);
          const nodeId = nodeData.id;
          nodesToRenderIds.add(nodeId);
          
          const coords = SafeData.getCoordinates(nodeData);
          const pollutants = SafeData.getPollutants(nodeWrapper);
          const latestReading = SafeData.getLatestReading(nodeWrapper);
          const aqi = pollutants[STATE.currentLayer] ?? pollutants.aqi ?? null;
          const isOffline = SafeData.isOffline(latestReading);

          // OPTIMIZATION: Check if marker already exists - if yes, update only if needed
          let marker = STATE.markersByNodeId.get(nodeId);
          
          if (marker) {
            // Marker exists - only update if value/state changed (differential update)
            const oldAqi = marker._aqi_value;
            const oldLayer = marker._current_layer;
            
            if (oldAqi !== aqi || oldLayer !== STATE.currentLayer) {
              // Value changed - update icon
              const markerHtml = buildMarkerHTML(nodeWrapper, nodeData, pollutants, latestReading, aqi);
              const aqiClass = Colors.getAQIClass(aqi);
              const offlineClass = isOffline ? 'cmapv-offline' : '';
              const selected = STATE.selectedNodeId === nodeId ? 'cmapv-selected' : '';
              const baseClass = isOffline ? 'cmapv-warning' : Colors.getNodeStatusClass(nodeData.status || 'unknown');
              const markerClass = baseClass + ' ' + aqiClass + ' ' + offlineClass;

              const newIcon = L.divIcon({
                html: `<div class="cmapv-marker ${markerClass} ${selected}">${markerHtml}</div>`,
                className: '',
                iconSize: [30, 30],
                popupAnchor: [0, -15]
              });
              
              marker.setIcon(newIcon);
              marker._aqi_value = aqi;
              marker._current_layer = STATE.currentLayer;
            }
            
            // Ensure marker is in layer group (idempotent operation)
            if (!marker._layerGroup || marker._layerGroup !== STATE.markerLayerGroup) {
              STATE.markerLayerGroup.addLayer(marker);
              marker._layerGroup = STATE.markerLayerGroup;
            }
          } else {
            // Marker doesn't exist - create new one
            const markerHtml = buildMarkerHTML(nodeWrapper, nodeData, pollutants, latestReading, aqi);
            const aqiClass = Colors.getAQIClass(aqi);
            const offlineClass = isOffline ? 'cmapv-offline' : '';
            const selected = STATE.selectedNodeId === nodeId ? 'cmapv-selected' : '';
            const baseClass = isOffline ? 'cmapv-warning' : Colors.getNodeStatusClass(nodeData.status || 'unknown');
            const markerClass = baseClass + ' ' + aqiClass + ' ' + offlineClass;

            // OPTIMIZATION: Create lightweight marker with simple icon
            marker = L.marker(coords, {
              icon: L.divIcon({
                html: `<div class="cmapv-marker ${markerClass} ${selected}">${markerHtml}</div>`,
                className: '',
                iconSize: [30, 30],
                popupAnchor: [0, -15]
              })
            });

            // Attach metadata for future updates
            marker.nodeData = nodeWrapper;
            marker.nodeId = nodeId;
            marker._aqi_value = aqi;
            marker._current_layer = STATE.currentLayer;
            marker._layerGroup = STATE.markerLayerGroup;
            
            marker.on('click', () => selectNode(nodeId));

            STATE.markerLayerGroup.addLayer(marker);
            STATE.markersByNodeId.set(nodeId, marker);
            STATE.nodeDataByNodeId.set(nodeId, nodeWrapper);
            STATE.leafletMarkers.push(marker);
          }
        } catch (e) {
          console.warn('[MapView] Error rendering individual marker:', e);
        }
      });

      // OPTIMIZATION: Remove markers that are no longer in viewport/visible
      for (const [nodeId, marker] of STATE.markersByNodeId.entries()) {
        if (!nodesToRenderIds.has(nodeId)) {
          // This node should not be rendered - remove from layer group
          STATE.markerLayerGroup.removeLayer(marker);
        }
      }

      // OPTIMIZATION: Auto-recenter on first successful render
      if (!STATE.hasAutoCentered && nodesToRender.length > 0) {
        try {
          if (nodesToRender.length === 1) {
            const coords = SafeData.getCoordinates(SafeData.getNode(nodesToRender[0]));
            if (coords) {
              STATE.map.setView(coords, 16);
            }
          } else {
            STATE.markerLayerGroup.getBounds && STATE.map.fitBounds(STATE.markerLayerGroup.getBounds(), { padding: [50, 50] });
          }
          STATE.hasAutoCentered = true;
        } catch (e) {
          console.warn('[MapView] Auto-center failed:', e);
        }
      }

      // Show fallback if no nodes
      if (nodesToRender.length === 0) {
        console.warn('[MapView] No markers to render in current view.');
        showNoDataFallback();
      }

    } catch (e) {
      console.error('[MapView] Error rendering markers:', e);
      showErrorFallback('Failed to render markers: ' + e.message);
    }
  }

  // OPTIMIZATION: Selection doesn't trigger full marker re-render, only panel update
  function selectNode(nodeId) {
    STATE.selectedNodeId = nodeId;
    renderDrilldownPanel();
  }

  // === DRILLDOWN PANEL ===
  function renderDrilldownPanel() {
    try {
      const panel = document.getElementById(CONFIG.DRILLDOWN_PANEL_ID);
      if (!panel) {
        console.warn('[MapView] Drilldown panel element not found');
        return;
      }

      // Find selected node or use first available
      let selectedNode = STATE.allNodes.find(n => {
        const nodeData = SafeData.getNode(n);
        return nodeData && nodeData.id === STATE.selectedNodeId;
      }) || STATE.allNodes[0];

      if (!selectedNode) {
        panel.innerHTML = '<div style="padding:2em;color:#888;text-align:center;">No nodes available</div>';
        return;
      }

      // Safe extraction
      const nodeData = SafeData.getNode(selectedNode);
      const pollutants = SafeData.getPollutants(selectedNode);
      const latestReading = SafeData.getLatestReading(selectedNode);

      if (!nodeData) {
        panel.innerHTML = '<div style="padding:2em;color:#888;text-align:center;">Invalid node data</div>';
        return;
      }

      // Extract values with fallbacks
      const nodeName = SafeData.getSafeValue(nodeData.name || nodeData.id, 'Unknown');
      const nodeStatus = SafeData.getSafeValue(nodeData.status || 'unknown', 'unknown');
      const location = SafeData.getSafeValue(nodeData.location, 'Unknown');
      const aqi = pollutants.aqi ?? 0;
      const pm25 = Format.formatNumber(pollutants.pm25);
      const pm10 = Format.formatNumber(pollutants.pm10);
      const temp = Format.formatNumber(pollutants.temperature);
      const hum = Format.formatNumber(pollutants.humidity);
      const battery = SafeData.getSafeValue(latestReading.battery !== null ? latestReading.battery + '%' : null, 'N/A');
      const rssi = SafeData.getSafeValue(latestReading.rssi !== null ? latestReading.rssi + ' dBm' : null, 'N/A');
      const lastSeen = Format.getLastSeen(latestReading.timestamp);
      
      // FIX #5: Get AQI history for dynamic chart - limit to last 24 points
      let aqiHistory = selectedNode.aqi_history || [];
      if (Array.isArray(aqiHistory) && aqiHistory.length > CONFIG.MAX_AQI_HISTORY) {
        aqiHistory = aqiHistory.slice(-CONFIG.MAX_AQI_HISTORY);
      }
      const chartHTML = renderAQIChart(aqiHistory);

      const statusClass = Colors.getNodeStatusClass(nodeStatus);
      const aqiClass = Colors.getAQIClass(aqi);

      // AQI label logic
      let aqiLabel = 'Good';
      let aqiDesc = 'Air quality is considered satisfactory.';
      if (aqi >= 200) {
        aqiLabel = 'Hazardous Conditions';
        aqiDesc = 'Health warning of emergency conditions. The entire population is highly likely to be affected.';
      } else if (aqi >= 150) {
        aqiLabel = 'Unhealthy';
        aqiDesc = 'Everyone may experience health effects; sensitive groups may experience more serious effects.';
      } else if (aqi >= 100) {
        aqiLabel = 'Unhealthy for Sensitive Groups';
        aqiDesc = 'Sensitive groups may experience health effects.';
      } else if (aqi >= 51) {
        aqiLabel = 'Moderate';
        aqiDesc = 'Air quality is acceptable.';
      }

      panel.innerHTML = `
        <div class="cmapv-panel-header">
          <div class="cmapv-node-title-row">
            <div class="cmapv-node-name">Node ${nodeName}</div>
            <span class="cmapv-status-pill ${statusClass}">${nodeStatus.charAt(0).toUpperCase() + nodeStatus.slice(1)}</span>
          </div>
          <div class="cmapv-node-meta-row">
            <div class="cmapv-meta-item"><i class="fas fa-map-marker-alt"></i> ${location}</div>
            <div class="cmapv-meta-item ${aqiClass}" title="Signal Strength"><i class="fas fa-signal"></i> ${rssi}</div>
            <div class="cmapv-meta-item ${aqiClass}" title="Battery"><i class="fas ${Format.getBatteryIcon(latestReading.battery)}"></i> ${battery}</div>
            <div class="cmapv-meta-item ${aqiClass}" title="Last Seen"><i class="fas fa-clock"></i> ${lastSeen}</div>
          </div>
        </div>
        <div class="cmapv-panel-body">
          <div class="cmapv-section-title">Node Health Summary</div>
          <div class="cmapv-health-grid">
            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Uptime</span>
              <span class="cmapv-hp-val cmapv-good">99.8%</span>
            </div>
            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Latency</span>
              <span class="cmapv-hp-val cmapv-warn">142ms</span>
            </div>
            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Errors</span>
              <span class="cmapv-hp-val cmapv-crit">12/hr</span>
            </div>
          </div>
          <div class="cmapv-section-title">Air Quality Index</div>
          <div class="cmapv-aqi-hero">
            <div class="cmapv-aqi-value-box">
              <span class="cmapv-aqi-num">${Math.round(aqi)}</span>
              <span class="cmapv-aqi-label">AQI</span>
            </div>
            <div class="cmapv-aqi-desc">
              <div class="cmapv-aqi-desc-title">${aqiLabel}</div>
              <div class="cmapv-aqi-desc-text">${aqiDesc}</div>
            </div>
          </div>
          <div class="cmapv-section-title">Sensor Telemetry</div>
          <div class="cmapv-pollutant-grid">
            <div class="cmapv-pollutant-card">
              <div class="cmapv-pollutant-name">PM 2.5</div>
              <div class="cmapv-pollutant-val ${aqi >= 150 ? 'cmapv-crit' : ''}">${pm25} <span class="cmapv-pollutant-unit">µg/m³</span></div>
            </div>
            <div class="cmapv-pollutant-card">
              <div class="cmapv-pollutant-name">PM 10</div>
              <div class="cmapv-pollutant-val ${aqi >= 150 ? 'cmapv-crit' : ''}">${pm10} <span class="cmapv-pollutant-unit">µg/m³</span></div>
            </div>
            <div class="cmapv-pollutant-card">
              <div class="cmapv-pollutant-name">Temperature</div>
              <div class="cmapv-pollutant-val">${temp} <span class="cmapv-pollutant-unit">°C</span></div>
            </div>
            <div class="cmapv-pollutant-card">
              <div class="cmapv-pollutant-name">Humidity</div>
              <div class="cmapv-pollutant-val">${hum} <span class="cmapv-pollutant-unit">%</span></div>
            </div>
          </div>
          <div class="cmapv-section-title">24H AQI Trend</div>
          ${chartHTML}
        </div>
        <div class="cmapv-panel-footer">
          <button class="cmapv-btn cmapv-btn-outline"><i class="fas fa-sync-alt"></i> Reboot Node</button>
          <button class="cmapv-btn cmapv-btn-danger"><i class="fas fa-ban"></i> Isolate Target</button>
        </div>
      `;
    } catch (e) {
      console.error('[MapView] Error rendering drilldown panel:', e);
      const panel = document.getElementById(CONFIG.DRILLDOWN_PANEL_ID);
      if (panel) {
        panel.innerHTML = '<div style="padding:2em;color:#888;text-align:center;">Error loading panel: ' + e.message + '</div>';
      }
    }
  }

  // === LEGEND ===
  function renderLegend() {
    try {
      const legend = document.getElementById(CONFIG.LEGEND_ID);
      if (!legend) return;

      let html = '';
      if (STATE.currentLayer === 'aqi') {
        html = `<div class="cmapv-legend-title">AQI Index</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-good);"></div> Good (0-50)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-moderate);"></div> Mod (51-100)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-sensitive);"></div> Sens (101-150)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-unhealthy);"></div> Unhlth (151-200)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-hazardous);"></div> Hzrd (201+)</div>`;
      } else if (STATE.currentLayer === 'pm25') {
        html = `<div class="cmapv-legend-title">PM2.5 (µg/m³)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-good);"></div> 0-12</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-moderate);"></div> 13-35</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-sensitive);"></div> 36-55</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-unhealthy);"></div> 56-150</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-hazardous);"></div> 151+</div>`;
      } else if (STATE.currentLayer === 'pm10') {
        html = `<div class="cmapv-legend-title">PM10 (µg/m³)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-good);"></div> 0-54</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-moderate);"></div> 55-154</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-sensitive);"></div> 155-254</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-unhealthy);"></div> 255-354</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-hazardous);"></div> 355+</div>`;
      } else if (STATE.currentLayer === 'temperature') {
        html = `<div class="cmapv-legend-title">Temperature (°C)</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-good);"></div> &lt; 25°C</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-moderate);"></div> 25-30°C</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-sensitive);"></div> 31-35°C</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-unhealthy);"></div> 36-40°C</div>
          <div class="cmapv-legend-item"><div class="cmapv-legend-color" style="background: var(--color-hazardous);"></div> &gt; 40°C</div>`;
      }
      legend.innerHTML = html;
    } catch (e) {
      console.error('[MapView] Error rendering legend:', e);
    }
  }

  // === FIX #8: ENHANCED API FETCHING WITH ABORT CONTROL ===
  async function fetchTimeframeData(timeframe) {
    "Fetch nodes by timeframe with proper AbortController cleanup."
    // Cancel any pending fetch
    if (STATE.fetchController) {
      STATE.fetchController.abort();
    }
    
    try {
      STATE.isFetching = true;
      const endpoint = timeframe === 'live' ? '/api/nodes/live/' : '/api/nodes/24h/';
      
      // FIX #8: Use AbortController for proper fetch timeout & cancellation
      STATE.fetchController = new AbortController();
      const timeoutId = setTimeout(() => {
        if (STATE.fetchController) {
          STATE.fetchController.abort();
        }
      }, CONFIG.API_TIMEOUT);
      
      const response = await fetch(endpoint, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: STATE.fetchController.signal
      });
      
      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      console.log('[MapView] API response received for timeframe:', timeframe);
      
      // FIX #4: Validate response structure
      if (!data || typeof data !== 'object') {
        throw new Error('Invalid API response format');
      }

      // Update node data if structure is valid
      if (data.active || data.inactive || data.unregistered || data.rogue) {
        // FIX #1: Merge and deduplicate
        window.CMAPV_NODES = {
          active: Array.isArray(data.active) ? data.active : [],
          inactive: Array.isArray(data.inactive) ? data.inactive : [],
          unregistered: Array.isArray(data.unregistered) ? data.unregistered : [],
          rogue: Array.isArray(data.rogue) ? data.rogue : []
        };
        initializeData();
        console.log('[MapView] Total unique nodes after fetch:', STATE.allNodes.length);
        scheduleRenderMarkers();
        renderDrilldownPanel();
        console.log('[MapView] Data refreshed for timeframe:', timeframe);
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        console.log('[MapView] Fetch cancelled');
        return;  // Cancelled - don't show error
      }
      console.error('[MapView] Fetch error:', e);
      console.warn('[MapView] Using fallback cached data');
      showErrorFallback('Failed to fetch ' + timeframe + ' data: ' + e.message);
    } finally {
      STATE.isFetching = false;
    }
  }

  // FIX #7: NEW FEATURE - Viewport-based API fetching
  async function fetchNodesInViewport() {
    "Fetch nodes only within current map viewport using bbox parameter."
    if (!STATE.map || STATE.isFetching) return;
    
    try {
      const bounds = STATE.map.getBounds();
      
      // Check if bounds changed significantly (avoid redundant fetches)
      if (STATE.lastViewportBounds && 
          JSON.stringify(bounds) === JSON.stringify(STATE.lastViewportBounds)) {
        return;  // Same viewport, skip
      }
      
      STATE.lastViewportBounds = bounds;
      const bbox = bounds.toBBoxString();  // "south,west,north,east" format
      
      STATE.isFetching = true;
      STATE.fetchController = new AbortController();
      const timeoutId = setTimeout(() => STATE.fetchController.abort(), CONFIG.API_TIMEOUT);
      
      const url = new URL('/api/nodes/viewport/', window.location.origin);
      url.searchParams.append('bbox', bbox);
      url.searchParams.append('timeframe', STATE.timeframe);
      
      const response = await fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: STATE.fetchController.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      
      const data = await response.json();
      
      // FIX #1 & #4: Merge, deduplicate, and apply hard limit
      if (data.active || data.inactive || data.unregistered || data.rogue) {
        window.CMAPV_NODES = {
          active: Array.isArray(data.active) ? data.active : [],
          inactive: Array.isArray(data.inactive) ? data.inactive : [],
          unregistered: Array.isArray(data.unregistered) ? data.unregistered : [],
          rogue: Array.isArray(data.rogue) ? data.rogue : []
        };
        initializeData();
        scheduleRenderMarkers();
        console.log('[MapView] Viewport fetch complete:', STATE.allNodes.length, 'nodes');
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        console.warn('[MapView] Viewport fetch failed:', e.message);
      }
    } finally {
      STATE.isFetching = false;
    }
  }
  
  // FIX #7: Debounced viewport fetch
  function scheduleViewportFetch() {
    "Debounce viewport-based API fetches to prevent over-querying."
    if (STATE.viewportFetchTimer) {
      clearTimeout(STATE.viewportFetchTimer);
    }
    STATE.viewportFetchTimer = setTimeout(() => {
      fetchNodesInViewport();
      STATE.viewportFetchTimer = null;
    }, CONFIG.VIEWPORT_FETCH_DEBOUNCE);
  }

  // === CONTROL HANDLERS ===
  function setupControls() {
    try {
      // Layer select
      const layerSelect = document.getElementById(CONFIG.LAYER_SELECT_ID);
      if (layerSelect) {
        layerSelect.addEventListener('change', function(e) {
          STATE.currentLayer = e.target.value || 'aqi';
          renderLegend();
          scheduleRenderMarkers(); // OPTIMIZATION: Use debounced render
          console.log('[MapView] Layer changed to:', STATE.currentLayer);
        });
      }

      // NEW: Node status visibility filters
      const bindToggle = (id, key) => {
        const el = document.getElementById(id);
        if (!el) return;
        
        // Default: all statuses visible (no cmapv-off class)
        el.classList.remove('cmapv-off');
        
        el.addEventListener('click', function() {
          STATE.overlays[key] = !STATE.overlays[key];
          this.classList.toggle('cmapv-off', !STATE.overlays[key]);
          scheduleRenderMarkers();
          console.log(`[MapView] ${key} visibility:`, STATE.overlays[key] ? 'ON' : 'OFF');
        });
      };
      
      bindToggle(CONFIG.TOGGLE_ACTIVE_ID, 'active');
      bindToggle(CONFIG.TOGGLE_INACTIVE_ID, 'inactive');
      bindToggle(CONFIG.TOGGLE_ROGUE_ID, 'rogue');
      bindToggle(CONFIG.TOGGLE_UNREGISTERED_ID, 'unregistered');

      // Live button
      const liveBtn = document.getElementById(CONFIG.BTN_LIVE_ID);
      if (liveBtn) {
        liveBtn.addEventListener('click', function() {
          STATE.timeframe = 'live';
          this.classList.add('cmapv-active');
          document.getElementById(CONFIG.BTN_24H_ID)?.classList.remove('cmapv-active');
          console.log('[MapView] Switched to live data');
          fetchTimeframeData('live');
        });
      }

      // 24h button
      const btn24h = document.getElementById(CONFIG.BTN_24H_ID);
      if (btn24h) {
        btn24h.addEventListener('click', function() {
          STATE.timeframe = '24h';
          this.classList.add('cmapv-active');
          document.getElementById(CONFIG.BTN_LIVE_ID)?.classList.remove('cmapv-active');
          console.log('[MapView] Switched to 24h data');
          fetchTimeframeData('24h');
        });
      }

      console.log('[MapView] Controls initialized');
    } catch (e) {
      console.error('[MapView] Error setting up controls:', e);
    }
  }

  // === FALLBACK UI ===
  function showNoDataFallback() {
    const mapContainer = document.getElementById(CONFIG.MAP_CONTAINER_ID);
    if (mapContainer) {
      mapContainer.style.backgroundColor = '#f5f5f5';
    }
  }

  function showErrorFallback(message) {
    const mapContainer = document.getElementById(CONFIG.MAP_CONTAINER_ID);
    if (mapContainer && !mapContainer.querySelector('.cmapv-error-banner')) {
      const banner = document.createElement('div');
      banner.className = 'cmapv-error-banner';
      banner.style.cssText = 'position:absolute;top:10px;left:10px;right:10px;background:#fee;border:1px solid #fcc;color:#c33;padding:12px;border-radius:4px;z-index:9999;font-size:14px;';
      banner.innerHTML = '⚠️ ' + (message || 'An error occurred');
      mapContainer.appendChild(banner);
      setTimeout(() => banner.remove(), 5000);
    }
  }

  // === INITIALIZATION ===
  function initializeMap() {
    try {
      // FIX: Prevent double initialization
      if (STATE.map) {
        console.warn('[MapView] Map already initialized. Skipping re-init.');
        return;
      }
      
      // FIX: Clean up leaflet_id if container was previously used
      const container = L.DomUtil.get(CONFIG.MAP_CONTAINER_ID);
      if (container && container._leaflet_id) {
        container._leaflet_id = null;
      }
      
      // Create map
      STATE.map = L.map(CONFIG.MAP_CONTAINER_ID, {
        zoomControl: false,
        attributionControl: false,
        scrollWheelZoom: true,
        doubleClickZoom: true,
        boxZoom: false,
        dragging: true,
        minZoom: 12,
        maxZoom: 19
      });

      if (!STATE.map) {
        throw new Error('Failed to initialize Leaflet map');
      }

      STATE.map.setView(CONFIG.MAP_CENTER, CONFIG.MAP_ZOOM);

      // OPTIMIZATION: Add map movement hooks for viewport-based rendering
      STATE.map.on('moveend', scheduleRenderMarkers);
      STATE.map.on('zoomend', scheduleRenderMarkers);
      
      // FIX #7: Add viewport-based API fetching on map movement
      STATE.map.on('moveend', scheduleViewportFetch);
      STATE.map.on('zoomend', scheduleViewportFetch);

      // Add tile layer
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
      }).addTo(STATE.map);

      console.log('[MapView] Map initialized successfully');
    } catch (e) {
      console.error('[MapView] Map initialization failed:', e);
      showErrorFallback('Map failed to initialize: ' + e.message);
    }
  }

  function init() {
    try {
      console.log('[MapView] Initializing...');
      
      // FIX #2: Initialize with empty arrays (API is single source of truth)
      initializeData();

      // Initialize map
      initializeMap();
      if (!STATE.map) return;

      // Render UI
      renderLegend();
      scheduleRenderMarkers();
      setupControls();

      // FIX #2: Fetch initial data from API (not template)
      console.log('[MapView] Fetching initial data from API...');
      fetchTimeframeData('live');

      // Select first node (will be set after fetch completes)
      if (STATE.allNodes.length > 0) {
        const firstNode = SafeData.getNode(STATE.allNodes[0]);
        if (firstNode) {
          selectNode(firstNode.id);
        }
      } else {
        renderDrilldownPanel();
      }

      console.log('[MapView] Initialization complete');
    } catch (e) {
      console.error('[MapView] Initialization error:', e);
      showErrorFallback('Failed to initialize map view: ' + e.message);
    }
  }

  // === BOOTSTRAP ===
  // FIX: Guard against duplicate initialization
  if (!window.__CMAPV_INITIALIZED__) {
    window.__CMAPV_INITIALIZED__ = true;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  } else {
    console.warn('[MapView] Already initialized. Skipping duplicate bootstrap.');
  }
})();
