
/**
 * EnviroPlus — Admin Map View
 * Satellite imagery fix
 *
 * Uses Esri World Imagery rather than the blocked
 * OpenStreetMap standard tile server.
 *
 * Existing element IDs and CSS classes are preserved.
 */

(function () {
  'use strict';

  if (typeof L === 'undefined') {
    console.error(
      '[MapView] Leaflet library not found.'
    );
    return;
  }

  /* ==========================================================
     CONFIGURATION
     ========================================================== */

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

    SATELLITE_URL:
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',

    SATELLITE_ATTRIBUTION:
      '&copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community',

    API_TIMEOUT: 8000,
    MAX_NODES: 200,
    MAX_AQI_HISTORY: 24,
    VIEWPORT_FETCH_DEBOUNCE: 300
  };

  /* ==========================================================
     APPLICATION STATE
     ========================================================== */

  const STATE = {
    map: null,
    satelliteLayer: null,

    leafletMarkers: [],
    markerLayerGroup: null,
    markersByNodeId: new Map(),
    nodeDataByNodeId: new Map(),

    allNodes: [],
    uniqueNodeIds: new Set(),

    currentLayer: 'aqi',

    overlays: {
      active: true,
      inactive: true,
      rogue: true,
      unregistered: true
    },

    timeframe: 'live',
    selectedNodeId: null,

    isLoading: false,
    isFetching: false,

    renderScheduleTimer: null,
    viewportFetchTimer: null,

    hasAutoCentered: false,

    fetchController: null,
    lastViewportBounds: null,

    allowViewportFetch: false,
    skipNextViewportFetch: false
  };

  /* ==========================================================
     SAFE DATA EXTRACTION
     ========================================================== */

  const SafeData = {
    getNode(nodeObj) {
      return (
        nodeObj &&
        typeof nodeObj === 'object'
      )
        ? nodeObj.node
        : null;
    },

    getPollutants(nodeObj) {
      return (
        nodeObj &&
        typeof nodeObj === 'object' &&
        nodeObj.pollutants
      )
        ? nodeObj.pollutants
        : {};
    },

    getLatestReading(nodeObj) {
      return (
        nodeObj &&
        typeof nodeObj === 'object' &&
        nodeObj.latest_reading
      )
        ? nodeObj.latest_reading
        : null;
    },

    getSafeValue(value, fallback = 'N/A') {
      return (
        value !== null &&
        value !== undefined
      )
        ? value
        : fallback;
    },

    getCoordinates(node) {
      if (!node || typeof node !== 'object') {
        return null;
      }

      const lat = Number(node.latitude);
      const lng = Number(node.longitude);

      if (
        !Number.isFinite(lat) ||
        !Number.isFinite(lng)
      ) {
        return null;
      }

      if (
        lat < -90 ||
        lat > 90 ||
        lng < -180 ||
        lng > 180
      ) {
        return null;
      }

      return [lat, lng];
    },

    isOffline(latestReading) {
      return (
        !latestReading ||
        !latestReading.timestamp
      );
    }
  };

  /* ==========================================================
     HTML ESCAPING
     ========================================================== */

  function escapeHTML(value) {
    return String(value ?? '').replace(
      /[&<>"']/g,
      char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char])
    );
  }

  /* ==========================================================
     MARKER UTILITIES
     ========================================================== */

  function isMarkerRendered(marker) {
    return (
      marker &&
      STATE.markerLayerGroup &&
      STATE.markerLayerGroup.hasLayer(marker)
    );
  }

  /* ==========================================================
     AIR QUALITY COLORS
     ========================================================== */

  const Colors = {
    getColorForValue(
      value,
      layer = 'aqi',
      isOffline = false
    ) {
      if (
        isOffline ||
        value === null ||
        value === undefined
      ) {
        return '#7f8c8d';
      }

      value = Number(value) || 0;

      if (layer === 'aqi') {
        if (value <= 50) return '#2ecc71';
        if (value <= 100) return '#f1c40f';
        if (value <= 150) return '#e67e22';
        if (value <= 200) return '#e74c3c';
        if (value <= 300) return '#c0392b';
        return '#8b0000';
      }

      if (
        layer === 'pm25' ||
        layer === 'pm10'
      ) {
        const thresholds = layer === 'pm25'
          ? [
              [12, '#2ecc71'],
              [35, '#f1c40f'],
              [55, '#e67e22'],
              [150, '#e74c3c'],
              [Infinity, '#c0392b']
            ]
          : [
              [54, '#2ecc71'],
              [154, '#f1c40f'],
              [254, '#e67e22'],
              [354, '#e74c3c'],
              [Infinity, '#c0392b']
            ];

        for (const [threshold, color] of thresholds) {
          if (value <= threshold) {
            return color;
          }
        }
      }

      if (layer === 'temperature') {
        if (value < 25) return '#2ecc71';
        if (value <= 30) return '#f1c40f';
        if (value <= 35) return '#e67e22';
        if (value <= 40) return '#e74c3c';
        return '#c0392b';
      }

      return '#95a5a6';
    },

    getAQIClass(aqi) {
      aqi = Number(aqi) || 0;

      if (aqi <= 50) return 'cmapv-good';
      if (aqi <= 100) return 'cmapv-warning';
      if (aqi <= 150) {
        return 'cmapv-unhealthy-sensitive';
      }
      if (aqi <= 200) return 'cmapv-unhealthy';

      return 'cmapv-critical';
    },

    getNodeStatusClass(status) {
      const classes = {
        active: 'cmapv-good',
        inactive: 'cmapv-inactive',
        rogue: 'cmapv-critical',
        unregistered: 'cmapv-warning'
      };

      return classes[status] || 'cmapv-unknown';
    }
  };

  /* ==========================================================
     FORMATTING
     ========================================================== */

  const Format = {
    getBatteryIcon(battery) {
      battery = Number(battery) || 0;

      if (battery >= 90) return 'fa-battery-full';
      if (battery >= 60) {
        return 'fa-battery-three-quarters';
      }
      if (battery >= 30) return 'fa-battery-half';
      if (battery >= 10) return 'fa-battery-quarter';

      return 'fa-battery-empty';
    },

    getLastSeen(timestamp) {
      if (!timestamp) return 'N/A';

      try {
        const time = new Date(timestamp);

        if (isNaN(time.getTime())) {
          return 'N/A';
        }

        const difference = Date.now() - time.getTime();
        const minutes = Math.floor(difference / 60000);

        if (minutes < 1) return 'Just now';
        if (minutes < 60) return `${minutes}m ago`;

        const hours = Math.floor(minutes / 60);

        if (hours < 24) return `${hours}h ago`;

        return time.toLocaleDateString();

      } catch (error) {
        return 'N/A';
      }
    },

    formatNumber(value, decimals = 1) {
      if (
        value === null ||
        value === undefined
      ) {
        return 'N/A';
      }

      const number = Number(value);

      return Number.isFinite(number)
        ? number.toFixed(decimals)
        : 'N/A';
    }
  };

  /* ==========================================================
     NODE DEDUPLICATION
     ========================================================== */

  function deduplicateNodes(nodes) {
    const seen = new Set();
    const result = [];

    for (const wrapper of nodes) {
      const node = SafeData.getNode(wrapper);

      if (!node || !node.id) {
        continue;
      }

      if (!seen.has(node.id)) {
        seen.add(node.id);
        result.push(wrapper);
      }
    }

    return result;
  }

  /* ==========================================================
     INITIALIZE NODE DATA
     ========================================================== */

  function initializeData() {
    try {
      const rawNodes = window.CMAPV_NODES;

      if (
        !rawNodes ||
        typeof rawNodes !== 'object'
      ) {
        STATE.allNodes = [];
        STATE.uniqueNodeIds.clear();
        return;
      }

      const active = Array.isArray(rawNodes.active)
        ? rawNodes.active
        : [];

      const inactive = Array.isArray(rawNodes.inactive)
        ? rawNodes.inactive
        : [];

      const unregistered =
        Array.isArray(rawNodes.unregistered)
          ? rawNodes.unregistered
          : [];

      const rogue = Array.isArray(rawNodes.rogue)
        ? rawNodes.rogue
        : [];

      let merged = [
        ...active,
        ...inactive,
        ...unregistered,
        ...rogue
      ];

      merged = deduplicateNodes(merged);

      if (merged.length > CONFIG.MAX_NODES) {
        merged = merged.slice(0, CONFIG.MAX_NODES);
      }

      STATE.uniqueNodeIds.clear();

      for (const wrapper of merged) {
        const node = SafeData.getNode(wrapper);

        if (node?.id) {
          STATE.uniqueNodeIds.add(node.id);
        }
      }

      STATE.allNodes = merged;

      console.log(
        '[MapView] Unique nodes:',
        STATE.allNodes.length
      );

    } catch (error) {
      console.error(
        '[MapView] Data initialization error:',
        error
      );

      STATE.allNodes = [];
      STATE.uniqueNodeIds.clear();
    }
  }

  /* ==========================================================
     AQI HISTORY CHART
     ========================================================== */

  function renderAQIChart(history) {
    if (
      !Array.isArray(history) ||
      history.length === 0
    ) {
      return `
        <div style="color:#888;text-align:center;padding:20px;font-size:.75rem;">
          No historical data available
        </div>
      `;
    }

    const validValues = history.filter(
      value => (
        typeof value === 'number' &&
        Number.isFinite(value)
      )
    );

    if (!validValues.length) {
      return `
        <div style="color:#888;text-align:center;padding:20px;font-size:.75rem;">
          No valid data points
        </div>
      `;
    }

    const maximum = Math.max(...validValues, 1);

    const bars = history.map(value => {
      if (
        value === null ||
        value === undefined ||
        !Number.isFinite(Number(value))
      ) {
        return '';
      }

      const height = Math.max(
        10,
        (Number(value) / maximum) * 100
      );

      const color = Colors.getColorForValue(
        Number(value),
        'aqi'
      );

      return `
        <div
          class="cmapv-chart-bar"
          style="height:${height}%;background:${color};"
        ></div>
      `;
    }).join('');

    return `
      <div class="cmapv-chart-placeholder">
        ${bars}
      </div>
    `;
  }

  /* ==========================================================
     NODE MARKER HTML
     ========================================================== */

  function buildMarkerHTML(
    wrapper,
    node,
    pollutants,
    latestReading,
    value
  ) {
    const offline = SafeData.isOffline(latestReading);

    const displayValue = (
      !offline &&
      value !== null &&
      value !== undefined &&
      Number.isFinite(Number(value))
    )
      ? Math.round(Number(value))
      : 'N/A';

    return `
      <span style="font-weight:800;font-size:12px;line-height:1;">
        ${displayValue}
      </span>
    `;
  }

  /* ==========================================================
     MARKER RENDER SCHEDULER
     ========================================================== */

  function scheduleRenderMarkers() {
    if (STATE.renderScheduleTimer) {
      clearTimeout(STATE.renderScheduleTimer);
    }

    STATE.renderScheduleTimer = setTimeout(() => {
      renderMarkers();
      STATE.renderScheduleTimer = null;
    }, 150);
  }

  /* ==========================================================
     RENDER LEAFLET MARKERS
     ========================================================== */

  function renderMarkers() {
    try {
      if (!STATE.map) {
        return;
      }

      if (!STATE.markerLayerGroup) {
        STATE.markerLayerGroup = L.markerClusterGroup();
        STATE.markerLayerGroup.addTo(STATE.map);
      }

      const bounds = STATE.map.getBounds();

      const nodesToRender = STATE.allNodes.filter(
        wrapper => {
          const node = SafeData.getNode(wrapper);

          if (!node) {
            return false;
          }

          const coordinates =
            SafeData.getCoordinates(node);

          if (!coordinates) {
            return false;
          }

          const latlng = L.latLng(
            coordinates[0],
            coordinates[1]
          );

          if (
            STATE.hasAutoCentered &&
            !bounds.contains(latlng)
          ) {
            return false;
          }

          const status = node.status || 'unknown';

          return Boolean(STATE.overlays[status]);
        }
      );

      const renderedIds = new Set();

      STATE.markerLayerGroup.eachLayer(layer => {
        if (layer.nodeId) {
          renderedIds.add(layer.nodeId);
        }
      });

      const desiredIds = new Set();

      for (const wrapper of nodesToRender) {
        try {
          const node = SafeData.getNode(wrapper);
          const nodeId = node.id;

          desiredIds.add(nodeId);

          const coordinates =
            SafeData.getCoordinates(node);

          const pollutants =
            SafeData.getPollutants(wrapper);

          const latestReading =
            SafeData.getLatestReading(wrapper);

          const value = (
            pollutants[STATE.currentLayer] ??
            pollutants.aqi ??
            null
          );

          const offline =
            SafeData.isOffline(latestReading);

          const markerHTML = buildMarkerHTML(
            wrapper,
            node,
            pollutants,
            latestReading,
            value
          );

          const aqiClass = Colors.getAQIClass(
            pollutants.aqi
          );

          const offlineClass = offline
            ? 'cmapv-offline'
            : '';

          const selectedClass = (
            STATE.selectedNodeId === nodeId
          )
            ? 'cmapv-selected'
            : '';

          const baseClass = offline
            ? 'cmapv-warning'
            : Colors.getNodeStatusClass(
                node.status || 'unknown'
              );

          const markerClass = [
            baseClass,
            aqiClass,
            offlineClass,
            selectedClass
          ].join(' ');

          const icon = L.divIcon({
            html: `
              <div class="cmapv-marker ${markerClass}">
                ${markerHTML}
              </div>
            `,
            className: '',
            iconSize: [40, 40],
            popupAnchor: [0, -20]
          });

          let marker =
            STATE.markersByNodeId.get(nodeId);

          if (marker) {
            marker.nodeData = wrapper;

            if (
              marker._aqi_value !== value ||
              marker._current_layer !== STATE.currentLayer ||
              marker._offline !== offline
            ) {
              marker.setIcon(icon);
              marker._aqi_value = value;
              marker._current_layer = STATE.currentLayer;
              marker._offline = offline;
            }

            if (!isMarkerRendered(marker)) {
              STATE.markerLayerGroup.addLayer(marker);
            }

          } else {
            marker = L.marker(coordinates, {
              icon
            });

            marker.nodeData = wrapper;
            marker.nodeId = nodeId;

            marker._aqi_value = value;
            marker._current_layer = STATE.currentLayer;
            marker._offline = offline;

            marker.on('click', () => {
              selectNode(nodeId);
            });

            STATE.markerLayerGroup.addLayer(marker);

            STATE.markersByNodeId.set(
              nodeId,
              marker
            );

            STATE.nodeDataByNodeId.set(
              nodeId,
              wrapper
            );

            STATE.leafletMarkers.push(marker);
          }

        } catch (error) {
          console.warn(
            '[MapView] Marker rendering error:',
            error
          );
        }
      }

      /* REMOVE MARKERS OUTSIDE THE CURRENT FILTER */

      for (
        const [nodeId, marker]
        of STATE.markersByNodeId.entries()
      ) {
        if (
          !desiredIds.has(nodeId) &&
          isMarkerRendered(marker)
        ) {
          STATE.markerLayerGroup.removeLayer(marker);
        }
      }

      /* ADD BACK VISIBLE CACHED MARKERS */

      for (const nodeId of desiredIds) {
        const marker =
          STATE.markersByNodeId.get(nodeId);

        if (
          marker &&
          !isMarkerRendered(marker)
        ) {
          STATE.markerLayerGroup.addLayer(marker);
        }
      }

      /* INITIAL AUTO-CENTER */

      if (
        !STATE.hasAutoCentered &&
        nodesToRender.length > 0
      ) {
        try {
          if (nodesToRender.length === 1) {
            const node = SafeData.getNode(
              nodesToRender[0]
            );

            const coordinates =
              SafeData.getCoordinates(node);

            if (coordinates) {
              STATE.map.setView(coordinates, 16);
            }

          } else {
            const markerBounds =
              STATE.markerLayerGroup.getBounds();

            if (markerBounds.isValid()) {
              STATE.map.fitBounds(
                markerBounds,
                {
                  padding: [50, 50],
                  maxZoom: 16
                }
              );
            }
          }

          STATE.hasAutoCentered = true;
          STATE.skipNextViewportFetch = true;
          STATE.allowViewportFetch = true;

        } catch (error) {
          console.warn(
            '[MapView] Auto-center failed:',
            error
          );

          STATE.allowViewportFetch = true;
          STATE.skipNextViewportFetch = true;
        }
      }

      if (nodesToRender.length === 0) {
        showNoDataFallback();
      }

    } catch (error) {
      console.error(
        '[MapView] Render failed:',
        error
      );

      showErrorFallback(
        'Failed to render markers: ' + error.message
      );
    }
  }

  /* ==========================================================
     SELECT A SENSOR NODE
     ========================================================== */

  function selectNode(nodeId) {
    STATE.selectedNodeId = (
      STATE.selectedNodeId === nodeId
    )
      ? null
      : nodeId;

    STATE.leafletMarkers.forEach(marker => {
      const element = marker.getElement();

      if (!element) {
        return;
      }

      const markerElement =
        element.querySelector('.cmapv-marker');

      if (!markerElement) {
        return;
      }

      markerElement.classList.toggle(
        'cmapv-selected',
        marker.nodeId === STATE.selectedNodeId
      );
    });

    renderDrilldownPanel();
  }

  /* ==========================================================
     NODE INFORMATION PANEL
     ========================================================== */

  function renderDrilldownPanel() {
    try {
      const panel = document.getElementById(
        CONFIG.DRILLDOWN_PANEL_ID
      );

      if (!panel) {
        return;
      }

      let selectedNode = STATE.allNodes.find(
        wrapper => {
          const node = SafeData.getNode(wrapper);

          return (
            node &&
            node.id === STATE.selectedNodeId
          );
        }
      );

      selectedNode = selectedNode || STATE.allNodes[0];

      if (!selectedNode) {
        panel.innerHTML = `
          <div style="padding:2em;color:#888;text-align:center;">
            No nodes available
          </div>
        `;
        return;
      }

      const node = SafeData.getNode(selectedNode);

      const pollutants =
        SafeData.getPollutants(selectedNode);

      const latestReading =
        SafeData.getLatestReading(selectedNode) || {};

      if (!node) {
        panel.innerHTML = `
          <div style="padding:2em;color:#888;text-align:center;">
            Invalid node data
          </div>
        `;
        return;
      }

      const nodeName = escapeHTML(
        SafeData.getSafeValue(
          node.name || node.id,
          'Unknown'
        )
      );

      const nodeStatus = String(
        node.status || 'unknown'
      );

      const location = escapeHTML(
        SafeData.getSafeValue(
          node.location,
          'Unknown'
        )
      );

      const aqi = Number(pollutants.aqi) || 0;

      const pm25 = Format.formatNumber(
        pollutants.pm25
      );

      const pm10 = Format.formatNumber(
        pollutants.pm10
      );

      const temperature = Format.formatNumber(
        pollutants.temperature
      );

      const humidity = Format.formatNumber(
        pollutants.humidity
      );

      const batteryValue = latestReading.battery;

      const battery = (
        batteryValue !== null &&
        batteryValue !== undefined
      )
        ? `${escapeHTML(batteryValue)}%`
        : 'N/A';

      const rssiValue = latestReading.rssi;

      const rssi = (
        rssiValue !== null &&
        rssiValue !== undefined
      )
        ? `${escapeHTML(rssiValue)} dBm`
        : 'N/A';

      const lastSeen = Format.getLastSeen(
        latestReading.timestamp
      );

      let aqiHistory =
        selectedNode.aqi_history || [];

      if (
        Array.isArray(aqiHistory) &&
        aqiHistory.length > CONFIG.MAX_AQI_HISTORY
      ) {
        aqiHistory = aqiHistory.slice(
          -CONFIG.MAX_AQI_HISTORY
        );
      }

      const chartHTML = renderAQIChart(
        aqiHistory
      );

      const statusClass =
        Colors.getNodeStatusClass(nodeStatus);

      const aqiClass =
        Colors.getAQIClass(aqi);

      let aqiLabel = 'Good';

      let aqiDescription =
        'Air quality is considered satisfactory.';

      if (aqi >= 200) {
        aqiLabel = 'Hazardous Conditions';

        aqiDescription =
          'Health warning of emergency conditions. The entire population is highly likely to be affected.';

      } else if (aqi >= 150) {
        aqiLabel = 'Unhealthy';

        aqiDescription =
          'Everyone may experience health effects; sensitive groups may experience more serious effects.';

      } else if (aqi >= 100) {
        aqiLabel = 'Unhealthy for Sensitive Groups';

        aqiDescription =
          'Sensitive groups may experience health effects.';

      } else if (aqi >= 51) {
        aqiLabel = 'Moderate';

        aqiDescription =
          'Air quality is acceptable.';
      }

      panel.innerHTML = `
        <div class="cmapv-panel-header">

          <div class="cmapv-node-title-row">

            <div class="cmapv-node-name">
              Node ${nodeName}
            </div>

            <span class="cmapv-status-pill ${statusClass}">
              ${escapeHTML(
                nodeStatus.charAt(0).toUpperCase() +
                nodeStatus.slice(1)
              )}
            </span>

          </div>

          <div class="cmapv-node-meta-row">

            <div class="cmapv-meta-item">
              <i class="fas fa-map-marker-alt"></i>
              ${location}
            </div>

            <div
              class="cmapv-meta-item ${aqiClass}"
              title="Signal Strength"
            >
              <i class="fas fa-signal"></i>
              ${rssi}
            </div>

            <div
              class="cmapv-meta-item ${aqiClass}"
              title="Battery"
            >
              <i class="fas ${Format.getBatteryIcon(batteryValue)}"></i>
              ${battery}
            </div>

            <div
              class="cmapv-meta-item ${aqiClass}"
              title="Last Seen"
            >
              <i class="fas fa-clock"></i>
              ${escapeHTML(lastSeen)}
            </div>

          </div>

        </div>

        <div class="cmapv-panel-body">

          <div class="cmapv-section-title">
            Node Health Summary
          </div>

          <div class="cmapv-health-grid">

            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Uptime</span>
              <span class="cmapv-hp-val cmapv-good">
                99.8%
              </span>
            </div>

            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Latency</span>
              <span class="cmapv-hp-val cmapv-warn">
                142ms
              </span>
            </div>

            <div class="cmapv-health-pill">
              <span class="cmapv-hp-label">Errors</span>
              <span class="cmapv-hp-val cmapv-crit">
                12/hr
              </span>
            </div>

          </div>

          <div class="cmapv-section-title">
            Air Quality Index
          </div>

          <div class="cmapv-aqi-hero">

            <div class="cmapv-aqi-value-box">
              <span class="cmapv-aqi-num">
                ${Math.round(aqi)}
              </span>

              <span class="cmapv-aqi-label">
                AQI
              </span>
            </div>

            <div class="cmapv-aqi-desc">

              <div class="cmapv-aqi-desc-title">
                ${aqiLabel}
              </div>

              <div class="cmapv-aqi-desc-text">
                ${aqiDescription}
              </div>

            </div>

          </div>

          <div class="cmapv-section-title">
            Sensor Telemetry
          </div>

          <div class="cmapv-pollutant-grid">

            <div class="cmapv-pollutant-card">

              <div class="cmapv-pollutant-name">
                PM 2.5
              </div>

              <div class="cmapv-pollutant-val ${aqi >= 150 ? 'cmapv-crit' : ''}">
                ${pm25}
                <span class="cmapv-pollutant-unit">
                  µg/m³
                </span>
              </div>

            </div>

            <div class="cmapv-pollutant-card">

              <div class="cmapv-pollutant-name">
                PM 10
              </div>

              <div class="cmapv-pollutant-val ${aqi >= 150 ? 'cmapv-crit' : ''}">
                ${pm10}
                <span class="cmapv-pollutant-unit">
                  µg/m³
                </span>
              </div>

            </div>

            <div class="cmapv-pollutant-card">

              <div class="cmapv-pollutant-name">
                Temperature
              </div>

              <div class="cmapv-pollutant-val">
                ${temperature}
                <span class="cmapv-pollutant-unit">
                  °C
                </span>
              </div>

            </div>

            <div class="cmapv-pollutant-card">

              <div class="cmapv-pollutant-name">
                Humidity
              </div>

              <div class="cmapv-pollutant-val">
                ${humidity}
                <span class="cmapv-pollutant-unit">
                  %
                </span>
              </div>

            </div>

          </div>

          <div class="cmapv-section-title">
            24H AQI Trend
          </div>

          ${chartHTML}

        </div>

        <div class="cmapv-panel-footer">

          <button
            class="cmapv-btn cmapv-btn-outline"
            type="button"
          >
            <i class="fas fa-sync-alt"></i>
            Reboot Node
          </button>

          <button
            class="cmapv-btn cmapv-btn-danger"
            type="button"
          >
            <i class="fas fa-ban"></i>
            Isolate Target
          </button>

        </div>
      `;

    } catch (error) {
      console.error(
        '[MapView] Drilldown rendering failed:',
        error
      );

      const panel = document.getElementById(
        CONFIG.DRILLDOWN_PANEL_ID
      );

      if (panel) {
        panel.textContent =
          'Error loading panel: ' + error.message;
      }
    }
  }

  /* ==========================================================
     AQI LEGEND
     ========================================================== */

  function renderLegend() {
    try {
      const legend = document.getElementById(
        CONFIG.LEGEND_ID
      );

      if (!legend) return;

      let html = '';

      if (STATE.currentLayer === 'aqi') {
        html = `
          <div class="cmapv-legend-title">AQI Index</div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-good);"></div>
            Good (0-50)
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-moderate);"></div>
            Mod (51-100)
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-sensitive);"></div>
            Sens (101-150)
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-unhealthy);"></div>
            Unhlth (151-200)
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-hazardous);"></div>
            Hzrd (201+)
          </div>
        `;

      } else if (STATE.currentLayer === 'pm25') {
        html = `
          <div class="cmapv-legend-title">PM2.5 (µg/m³)</div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-good);"></div>
            0-12
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-moderate);"></div>
            13-35
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-sensitive);"></div>
            36-55
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-unhealthy);"></div>
            56-150
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-hazardous);"></div>
            151+
          </div>
        `;

      } else if (STATE.currentLayer === 'pm10') {
        html = `
          <div class="cmapv-legend-title">PM10 (µg/m³)</div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-good);"></div>
            0-54
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-moderate);"></div>
            55-154
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-sensitive);"></div>
            155-254
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-unhealthy);"></div>
            255-354
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-hazardous);"></div>
            355+
          </div>
        `;

      } else if (STATE.currentLayer === 'temperature') {
        html = `
          <div class="cmapv-legend-title">Temperature (°C)</div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-good);"></div>
            &lt; 25°C
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-moderate);"></div>
            25-30°C
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-sensitive);"></div>
            31-35°C
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-unhealthy);"></div>
            36-40°C
          </div>
          <div class="cmapv-legend-item">
            <div class="cmapv-legend-color" style="background:var(--color-hazardous);"></div>
            &gt; 40°C
          </div>
        `;
      }

      legend.innerHTML = html;

    } catch (error) {
      console.error(
        '[MapView] Legend rendering error:',
        error
      );
    }
  }

  /* ==========================================================
     FETCH SENSOR DATA
     ========================================================== */

  async function fetchTimeframeData(timeframe) {
    if (STATE.fetchController) {
      STATE.fetchController.abort();
    }

    STATE.isFetching = true;

    const controller = new AbortController();
    STATE.fetchController = controller;

    const timeoutId = setTimeout(() => {
      controller.abort();
    }, CONFIG.API_TIMEOUT);

    try {
      const endpoint = timeframe === 'live'
        ? '/api/nodes/live/'
        : '/api/nodes/24h/';

      const response = await fetch(endpoint, {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        },
        credentials: 'same-origin',
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(
          `API error: ${response.status} ${response.statusText}`
        );
      }

      const data = await response.json();

      if (
        !data ||
        typeof data !== 'object'
      ) {
        throw new Error('Invalid API response.');
      }

      if (
        data.active ||
        data.inactive ||
        data.unregistered ||
        data.rogue
      ) {
        window.CMAPV_NODES = {
          active: Array.isArray(data.active)
            ? data.active
            : [],

          inactive: Array.isArray(data.inactive)
            ? data.inactive
            : [],

          unregistered: Array.isArray(data.unregistered)
            ? data.unregistered
            : [],

          rogue: Array.isArray(data.rogue)
            ? data.rogue
            : []
        };

        initializeData();
        scheduleRenderMarkers();
        renderDrilldownPanel();
      }

    } catch (error) {
      if (error.name === 'AbortError') {
        return;
      }

      console.error(
        '[MapView] Sensor fetch failed:',
        error
      );

      showErrorFallback(
        'Failed to fetch ' +
        timeframe +
        ' data: ' +
        error.message
      );

    } finally {
      clearTimeout(timeoutId);

      if (STATE.fetchController === controller) {
        STATE.fetchController = null;
      }

      STATE.isFetching = false;
    }
  }

  /* ==========================================================
     VIEWPORT-BASED FETCHING
     ========================================================== */

  async function fetchNodesInViewport() {
    if (
      !STATE.map ||
      STATE.isFetching ||
      !STATE.allowViewportFetch
    ) {
      return;
    }

    if (STATE.skipNextViewportFetch) {
      STATE.skipNextViewportFetch = false;

      STATE.lastViewportBounds =
        STATE.map.getBounds();

      return;
    }

    const bounds = STATE.map.getBounds();

    if (
      STATE.lastViewportBounds &&
      bounds.equals(STATE.lastViewportBounds)
    ) {
      return;
    }

    STATE.lastViewportBounds = bounds;

    const controller = new AbortController();

    const timeoutId = setTimeout(() => {
      controller.abort();
    }, CONFIG.API_TIMEOUT);

    STATE.isFetching = true;

    try {
      const url = new URL(
        '/api/nodes/viewport/',
        window.location.origin
      );

      url.searchParams.set(
        'bbox',
        bounds.toBBoxString()
      );

      url.searchParams.set(
        'timeframe',
        STATE.timeframe
      );

      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        },
        credentials: 'same-origin',
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(
          `Viewport API error: ${response.status}`
        );
      }

      const data = await response.json();

      const incomingNodes = {
        active: Array.isArray(data.active)
          ? data.active
          : [],

        inactive: Array.isArray(data.inactive)
          ? data.inactive
          : [],

        unregistered: Array.isArray(data.unregistered)
          ? data.unregistered
          : [],

        rogue: Array.isArray(data.rogue)
          ? data.rogue
          : []
      };

      const totalNodes = Object.values(
        incomingNodes
      ).reduce(
        (total, nodes) => total + nodes.length,
        0
      );

      if (totalNodes === 0) {
        return;
      }

      const currentNodes = window.CMAPV_NODES || {
        active: [],
        inactive: [],
        unregistered: [],
        rogue: []
      };

      const incomingMap = new Map();

      for (
        const category
        of ['active', 'inactive', 'unregistered', 'rogue']
      ) {
        for (const wrapper of incomingNodes[category]) {
          const node = SafeData.getNode(wrapper);

          if (node?.id) {
            incomingMap.set(
              node.id,
              { category, wrapper }
            );
          }
        }
      }

      const mergedNodes = {
        active: [],
        inactive: [],
        unregistered: [],
        rogue: []
      };

      for (
        const category
        of ['active', 'inactive', 'unregistered', 'rogue']
      ) {
        const existing = Array.isArray(
          currentNodes[category]
        )
          ? currentNodes[category]
          : [];

        for (const wrapper of existing) {
          const node = SafeData.getNode(wrapper);

          if (
            node?.id &&
            incomingMap.has(node.id)
          ) {
            const incoming =
              incomingMap.get(node.id);

            mergedNodes[incoming.category].push(
              incoming.wrapper
            );

            incomingMap.delete(node.id);

          } else {
            mergedNodes[category].push(wrapper);
          }
        }
      }

      incomingMap.forEach(
        ({ category, wrapper }) => {
          mergedNodes[category].push(wrapper);
        }
      );

      window.CMAPV_NODES = mergedNodes;

      initializeData();
      scheduleRenderMarkers();

    } catch (error) {
      if (error.name !== 'AbortError') {
        console.warn(
          '[MapView] Viewport fetching failed:',
          error
        );
      }

    } finally {
      clearTimeout(timeoutId);
      STATE.isFetching = false;
    }
  }

  /* ==========================================================
     VIEWPORT FETCH SCHEDULER
     ========================================================== */

  function scheduleViewportFetch() {
    // Keep existing behavior:
    // The live endpoint already supplies the full node list.
    // Automatic viewport fetching remains disabled to avoid
    // replacing valid node data with empty responses.
    return;
  }

  /* ==========================================================
     DATA LAYER AND NODE VISIBILITY CONTROLS
     ========================================================== */

  function setupControls() {
    try {
      const layerSelect = document.getElementById(
        CONFIG.LAYER_SELECT_ID
      );

      if (layerSelect) {
        layerSelect.addEventListener(
          'change',
          event => {
            STATE.currentLayer =
              event.target.value || 'aqi';

            renderLegend();
            scheduleRenderMarkers();
          }
        );
      }

      const bindToggle = (id, status) => {
        const element = document.getElementById(id);

        if (!element) return;

        element.classList.remove('cmapv-off');

        element.addEventListener(
          'click',
          function () {
            STATE.overlays[status] =
              !STATE.overlays[status];

            this.classList.toggle(
              'cmapv-off',
              !STATE.overlays[status]
            );

            scheduleRenderMarkers();
          }
        );
      };

      bindToggle(
        CONFIG.TOGGLE_ACTIVE_ID,
        'active'
      );

      bindToggle(
        CONFIG.TOGGLE_INACTIVE_ID,
        'inactive'
      );

      bindToggle(
        CONFIG.TOGGLE_ROGUE_ID,
        'rogue'
      );

      bindToggle(
        CONFIG.TOGGLE_UNREGISTERED_ID,
        'unregistered'
      );

      const liveButton = document.getElementById(
        CONFIG.BTN_LIVE_ID
      );

      const historyButton = document.getElementById(
        CONFIG.BTN_24H_ID
      );

      if (liveButton) {
        liveButton.addEventListener(
          'click',
          () => {
            STATE.timeframe = 'live';

            liveButton.classList.add(
              'cmapv-active'
            );

            historyButton?.classList.remove(
              'cmapv-active'
            );

            fetchTimeframeData('live');
          }
        );
      }

      if (historyButton) {
        historyButton.addEventListener(
          'click',
          () => {
            STATE.timeframe = '24h';

            historyButton.classList.add(
              'cmapv-active'
            );

            liveButton?.classList.remove(
              'cmapv-active'
            );

            fetchTimeframeData('24h');
          }
        );
      }

    } catch (error) {
      console.error(
        '[MapView] Controls initialization error:',
        error
      );
    }
  }

  /* ==========================================================
     FALLBACK MESSAGES
     ========================================================== */

  function showNoDataFallback() {
    const container = document.getElementById(
      CONFIG.MAP_CONTAINER_ID
    );

    if (container) {
      container.style.backgroundColor = '#f5f5f5';
    }
  }

  function showErrorFallback(message) {
    const container = document.getElementById(
      CONFIG.MAP_CONTAINER_ID
    );

    if (
      !container ||
      container.querySelector('.cmapv-error-banner')
    ) {
      return;
    }

    const banner = document.createElement('div');

    banner.className = 'cmapv-error-banner';

    banner.style.cssText = [
      'position:absolute',
      'top:10px',
      'left:10px',
      'right:10px',
      'background:#fee',
      'border:1px solid #fcc',
      'color:#c33',
      'padding:12px',
      'border-radius:4px',
      'z-index:9999',
      'font-size:14px'
    ].join(';');

    banner.textContent =
      message || 'An error occurred.';

    container.appendChild(banner);

    setTimeout(() => {
      banner.remove();
    }, 5000);
  }

  /* ==========================================================
     SATELLITE IMAGERY — LEAFLET INITIALIZATION
     ========================================================== */

  function initializeMap() {
    try {
      if (STATE.map) {
        console.warn(
          '[MapView] Map already initialized.'
        );
        return;
      }

      const container = L.DomUtil.get(
        CONFIG.MAP_CONTAINER_ID
      );

      if (!container) {
        throw new Error(
          'Leaflet map container not found.'
        );
      }

      STATE.map = L.map(
        CONFIG.MAP_CONTAINER_ID,
        {
          zoomControl: false,
          attributionControl: false,

          scrollWheelZoom: true,
          doubleClickZoom: true,

          boxZoom: false,
          dragging: true,

          minZoom: 12,
          maxZoom: 19
        }
      );

      STATE.map.setView(
        CONFIG.MAP_CENTER,
        CONFIG.MAP_ZOOM
      );

      /* Keep Esri imagery attribution visible */

      L.control.attribution({
        position: 'bottomleft',
        prefix: false
      }).addTo(STATE.map);

      /* Satellite background */

      STATE.satelliteLayer = L.tileLayer(
        CONFIG.SATELLITE_URL,
        {
          minZoom: 0,
          maxZoom: 19,

          tileSize: 256,

          attribution:
            CONFIG.SATELLITE_ATTRIBUTION,

          keepBuffer: 2,
          updateWhenIdle: true
        }
      );

      STATE.satelliteLayer.addTo(STATE.map);

      /* Report provider errors without replacing tiles */

      let satelliteErrorReported = false;

      STATE.satelliteLayer.on(
        'tileerror',
        function (event) {
          if (satelliteErrorReported) {
            return;
          }

          satelliteErrorReported = true;

          console.warn(
            '[MapView] Satellite imagery tile failed:',
            event?.error || 'Tile unavailable'
          );

          showErrorFallback(
            'Satellite imagery could not load. Check the map provider connection.'
          );
        }
      );

      /* Preserve original map movement handlers */

      STATE.map.on(
        'moveend',
        scheduleRenderMarkers
      );

      STATE.map.on(
        'zoomend',
        scheduleRenderMarkers
      );

      STATE.map.on(
        'moveend',
        scheduleViewportFetch
      );

      STATE.map.on(
        'zoomend',
        scheduleViewportFetch
      );

      /* Fix Leaflet sizing after layout initialization */

      setTimeout(() => {
        if (STATE.map) {
          STATE.map.invalidateSize({
            pan: false
          });
        }
      }, 150);

      console.log(
        '[MapView] Esri satellite imagery initialized.'
      );

    } catch (error) {
      console.error(
        '[MapView] Map initialization failed:',
        error
      );

      showErrorFallback(
        'Map failed to initialize: ' +
        error.message
      );
    }
  }

  /* ==========================================================
     MAIN APPLICATION INITIALIZATION
     ========================================================== */

  function init() {
    try {
      console.log(
        '[MapView] Initializing EnviroPlus map...'
      );

      initializeData();

      initializeMap();

      if (!STATE.map) {
        return;
      }

      renderLegend();
      scheduleRenderMarkers();
      setupControls();

      fetchTimeframeData('live');

      if (STATE.allNodes.length > 0) {
        const firstNode = SafeData.getNode(
          STATE.allNodes[0]
        );

        if (firstNode) {
          selectNode(firstNode.id);
        }

      } else {
        renderDrilldownPanel();
      }

      console.log(
        '[MapView] Initialization complete.'
      );

    } catch (error) {
      console.error(
        '[MapView] Initialization error:',
        error
      );

      showErrorFallback(
        'Failed to initialize map view: ' +
        error.message
      );
    }
  }

  /* ==========================================================
     BOOTSTRAP
     ========================================================== */

  if (!window.__CMAPV_INITIALIZED__) {
    window.__CMAPV_INITIALIZED__ = true;

    if (document.readyState === 'loading') {
      document.addEventListener(
        'DOMContentLoaded',
        init
      );
    } else {
      init();
    }

  } else {
    console.warn(
      '[MapView] Duplicate initialization prevented.'
    );
  }

})();
