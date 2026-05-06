'use strict';

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const AnalyticsState = {
  // Current selections
  selectedNode: null,
  selectedTimeframe: '7d',
  selectedMetric: 'aqi',
  lockedNodeId: null,
  selectedInterval: 'auto', // 'hourly', 'daily', 'auto'
  selectedLocation: null, // ADDED: location filtering support

  // Cached data
  allNodes: [],
  allLocations: [],
  overviewData: {},
  trendsData: [],
  forecastData: [],
  nodeDetails: {},
  systemHealthData: {},

  // Chart instances
  charts: {
    aqiDonut: null,
    compDonut: null,
    trendLine: null,
    sparkline: null,
  },

  // Flags
  isLoading: false,
  isTrendView: 'line', // 'line' or 'heatmap'
  isCustomDate: false,
  customDateStart: null,
  customDateEnd: null,

  // KPI cache
  kpiData: {
    avgValue: 0,
    peakValue: 0,
    freshness: 'live',
    samplingRate: '10s',
  },

  // ADDED: Performance optimization tracking
  // Prevents unnecessary re-renders and API calls
  lastNodesListHash: null, // Hash of last rendered nodes list
  lastTrendsDataLength: 0, // Track trends data changes
  lastHeatmapHash: null, // Track heatmap data changes
  lastSparklineNodeId: null, // Cache last sparkline node
  lastSparklineTimeframe: null, // Cache last sparkline timeframe
  lastFilterValue: 'all', // Track filter selection
  lastTrendMetric: 'aqi', // Track last metric selection
  trendChartUpdateInProgress: false // Prevent concurrent updates
};

// ============================================================================
// API INTEGRATION
// ============================================================================

const API = {
  /**
   * Fetch overview analytics: current AQI, compositions, pollutants
   */
  async getOverview() {
    try {
      const params = new URLSearchParams({
        timeframe: AnalyticsState.selectedTimeframe,
        node_id: AnalyticsState.selectedNode || 'all',
        location: AnalyticsState.selectedLocation || 'all',
        start_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateStart || '' : '',
        end_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateEnd || '' : ''
      });

      const response = await fetch(`/api/analytics/overview/?${params}`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      console.log('[Analytics] Overview data loaded:', data);
      AnalyticsState.overviewData = data;
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch overview:', error);
      return null;
    }
  },

  /**
   * Fetch all sensor nodes for node selection
   */
  async getNodes() {
    try {
      const response = await fetch('/api/nodes/', {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      AnalyticsState.allNodes = data.results || data.nodes || [];
      
      // Extract unique locations for grouping
      const locationsSet = new Set();
      AnalyticsState.allNodes.forEach(node => {
        if (node.location) {
          locationsSet.add(node.location);
        }
      });
      AnalyticsState.allLocations = Array.from(locationsSet);
      
      console.log('[Analytics] Nodes loaded:', AnalyticsState.allNodes.length, 'nodes');
      return AnalyticsState.allNodes;
    } catch (error) {
      console.error('[Analytics] Failed to fetch nodes:', error);
      return [];
    }
  },

  /**
   * Fetch detailed data for a specific node
   */
  async getNodeDetail(nodeId) {
    try {
      const response = await fetch(`/api/nodes/${nodeId}/detail/`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      console.log('[Analytics] Node detail loaded:', nodeId, data);
      AnalyticsState.nodeDetails[nodeId] = data;
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch node detail:', error);
      return null;
    }
  },

  /**
   * Fetch time-series trend data (for line chart and heatmap)
   */
  async getTrends() {
    try {
      const params = new URLSearchParams({
        timeframe: AnalyticsState.selectedTimeframe,
        metric: AnalyticsState.selectedMetric,
        node_id: AnalyticsState.selectedNode || 'all',
        location: AnalyticsState.selectedLocation || 'all',
        start_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateStart || '' : '',
        end_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateEnd || '' : ''
      });

      const response = await fetch(`/api/analytics/trends/?${params}`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      console.log('[Analytics] Trends data loaded:', data.datapoints?.length || 0, 'points');
      AnalyticsState.trendsData = data.datapoints || [];
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch trends:', error);
      return null;
    }
  },

  /**
   * Fetch system health metrics
   */
  async getSystemHealth() {
    try {
      const response = await fetch('/api/analytics/system-health/', {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      AnalyticsState.systemHealthData = data;
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch system health:', error);
      return null;
    }
  },

  /**
   * Fetch AI forecast predictions
   */
  async getForecast() {
    try {
      const params = new URLSearchParams({
        timeframe: AnalyticsState.selectedTimeframe,
        days_ahead: AnalyticsState.selectedTimeframe === '24h' ? 1 : 
                    AnalyticsState.selectedTimeframe === '7d' ? 3 : 7,
        metric: AnalyticsState.selectedMetric,
        node_id: AnalyticsState.selectedNode || 'all',
        location: AnalyticsState.selectedLocation || 'all',
        start_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateStart || '' : '',
        end_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateEnd || '' : ''
      });

      const response = await fetch(`/api/analytics/forecast/?${params}`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) {
        console.warn('[Analytics] Forecast API not available');
        AnalyticsState.forecastData = [];
        return null;
      }
      const data = await response.json();
      AnalyticsState.forecastData = data.datapoints || [];
      console.log('[Analytics] Forecast data loaded:', AnalyticsState.forecastData.length, 'points');
      return data;
    } catch (error) {
      console.warn('[Analytics] Failed to fetch forecast:', error);
      AnalyticsState.forecastData = [];
      return null;
    }
  }
};

// ============================================================================
// CHART INITIALIZATION & UPDATES
// ============================================================================

const Charts = {
  /**
   * Initialize AQI donut chart (left panel top)
   */
  initAQIDonut() {
    const canvas = document.getElementById('aqiDonutChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    
    // Get current AQI from overview data - GUARD: handle undefined/NaN
    let aqi = AnalyticsState.overviewData.aqi_current || 0;
    if (typeof aqi !== 'number' || isNaN(aqi)) {
      aqi = 0;
    }
    
    const maxAQI = 500; // EPA scale max
    const fillPercent = Math.min(aqi / maxAQI * 100, 100);
    const emptyPercent = 100 - fillPercent;

    // Get color based on AQI level
    const color = Utils.getAQIColor(aqi);

    if (AnalyticsState.charts.aqiDonut) {
      AnalyticsState.charts.aqiDonut.destroy();
    }

    AnalyticsState.charts.aqiDonut = new Chart(ctx, {
      type: 'doughnut',
      data: {
        datasets: [{
          data: [fillPercent, emptyPercent],
          backgroundColor: [color, '#e2e8f0'],
          borderWidth: 0,
          cutout: '80%'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { tooltip: { enabled: false }, legend: { display: false } }
      }
    });

    console.log('[Analytics] AQI Donut initialized:', { aqi, color });
  },

  /**
   * Initialize composition donut chart (left panel top right) - with interactive tooltips
   */
  initCompDonut() {
    const canvas = document.getElementById('compDonutChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    
    // Get composition percentages from overview - GUARD: handle undefined/NaN
    let pm25Pct = AnalyticsState.overviewData.composition?.pm25 || 55;
    let pm10Pct = AnalyticsState.overviewData.composition?.pm10 || 25;
    let otherPct = AnalyticsState.overviewData.composition?.other || 20;
    
    // Ensure all values are valid numbers
    pm25Pct = (typeof pm25Pct === 'number' && !isNaN(pm25Pct)) ? pm25Pct : 55;
    pm10Pct = (typeof pm10Pct === 'number' && !isNaN(pm10Pct)) ? pm10Pct : 25;
    otherPct = (typeof otherPct === 'number' && !isNaN(otherPct)) ? otherPct : 20;

    if (AnalyticsState.charts.compDonut) {
      AnalyticsState.charts.compDonut.destroy();
    }

    AnalyticsState.charts.compDonut = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['PM2.5', 'PM10', 'Other'],
        datasets: [{
          data: [pm25Pct, pm10Pct, otherPct],
          backgroundColor: ['#991b1b', '#f97316', '#10b981'],
          borderWidth: 0,
          cutout: '75%'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { 
          tooltip: { 
            enabled: true,
            backgroundColor: 'rgba(0,0,0,0.85)',
            titleColor: '#fff',
            bodyColor: '#fff',
            borderColor: '#64748b',
            borderWidth: 1,
            callbacks: {
              label: function(context) {
                return context.label + ': ' + context.parsed + '%';
              }
            }
          }, 
          legend: { 
            display: true,
            position: 'bottom',
            labels: { 
              font: { size: 10 },
              padding: 8,
              usePointStyle: true
            }
          } 
        }
      }
    });

    console.log('[Analytics] Composition Donut initialized with interactive tooltips');
  },

  /**
   * Initialize trend line chart (right panel) - with forecast overlay
   * UPDATED: Apply downsampling and smoothing to reduce lag
   * FIXED: Update chart data instead of full destroy/recreate when possible
   * Only destroys chart if fundamental properties change
   */
  initTrendLine() {
    const canvas = document.getElementById('dateTrendChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    
    // UPDATED: Downsample and smooth data before generating time series
    const downsampledData = Utils.downsampleData(AnalyticsState.trendsData, AnalyticsState.selectedTimeframe);
    const smoothedData = Utils.smoothData(downsampledData, 3);
    
    // Generate full time-series with proper interpolation
    const fullTimeSeries = Utils.generateTimeSeriesRange(smoothedData, AnalyticsState.selectedTimeframe);
    
    const labels = fullTimeSeries.map(d => d.label);
    const dataPoints = fullTimeSeries.map(d => d.value);

    // Split real and forecast data
    const lastRealIndex = smoothedData.length - 1;

    // FIXED: If chart exists and metric hasn't changed, just update data instead of recreate
    // This preserves tooltips, legend, and animations while updating content
    if (AnalyticsState.charts.trendLine !== null && AnalyticsState.lastTrendMetric === AnalyticsState.selectedMetric) {
      // Guard: ensure valid chart instance before updating
      if (AnalyticsState.charts.trendLine.data && AnalyticsState.charts.trendLine.data.datasets) {
        // Update only the data
        AnalyticsState.charts.trendLine.data.labels = labels;
        AnalyticsState.charts.trendLine.data.datasets[0].data = dataPoints;
        
        // Update forecast dataset if present
        if (AnalyticsState.forecastData.length > 0 && AnalyticsState.charts.trendLine.data.datasets.length > 1) {
          const forecastPoints = AnalyticsState.forecastData.map(d => d.value);
          AnalyticsState.charts.trendLine.data.datasets[1].data = forecastPoints;
        }
        
        AnalyticsState.charts.trendLine.update('none'); // Update without animation
        console.log('[Analytics] Trend chart data updated (no destroy/recreate)');
        return;
      }
    }

    // Metric changed or chart doesn't exist - full recreate
    if (AnalyticsState.charts.trendLine) {
      AnalyticsState.charts.trendLine.destroy();
    }
    AnalyticsState.lastTrendMetric = AnalyticsState.selectedMetric;

    const datasets = [{
      label: Utils.getMetricLabel(AnalyticsState.selectedMetric),
      data: dataPoints,
      borderColor: '#2563eb',
      backgroundColor: 'rgba(37, 99, 235, 0.1)',
      borderWidth: 2.5,
      pointRadius: 3,
      pointBackgroundColor: '#fff',
      pointBorderColor: '#2563eb',
      fill: true,
      tension: 0.4,
      segment: {
        borderColor: ctx => {
          const dataIndex = typeof ctx.p0DataIndex === 'number' ? ctx.p0DataIndex : (typeof ctx.p0Index === 'number' ? ctx.p0Index : 0);
          return dataIndex > lastRealIndex ? '#8b5cf6' : '#2563eb';
        },
        borderDash: ctx => {
          const dataIndex = typeof ctx.p0DataIndex === 'number' ? ctx.p0DataIndex : (typeof ctx.p0Index === 'number' ? ctx.p0Index : 0);
          return dataIndex > lastRealIndex ? [5, 5] : [];
        }
      }
    }];

    // Add forecast overlay if available
    if (AnalyticsState.forecastData.length > 0) {
      const forecastPoints = AnalyticsState.forecastData.map(d => d.value);
      
      datasets.push({
        label: 'Predicted ' + Utils.getMetricLabel(AnalyticsState.selectedMetric),
        data: forecastPoints,
        borderColor: '#a855f7',
        borderWidth: 2,
        pointRadius: 2,
        pointBackgroundColor: '#d8b4fe',
        pointBorderColor: '#a855f7',
        fill: false,
        tension: 0.3,
        borderDash: [5, 5],
        spanGaps: true
      });
    }

    AnalyticsState.charts.trendLine = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: { 
            grid: { borderDash: [4, 4], color: '#e2e8f0' }, 
            beginAtZero: true 
          },
          x: { grid: { display: false } }
        },
        plugins: { 
          legend: { 
            display: AnalyticsState.forecastData.length > 0,
            position: 'top',
            labels: { font: { size: 11 }, usePointStyle: true }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              afterLabel: function(context) {
                if (context.dataIndex > lastRealIndex) {
                  return '(Predicted)';
                }
                return '';
              }
            }
          }
        }
      }
    });

    console.log('[Analytics] Trend chart initialized with', dataPoints.length, 'points (downsampled & smoothed)');
  },

  /**
   * Initialize sparkline for selected node - MULTI-METRIC overlay
   * Displays: AQI (primary), PM2.5, PM10, Temperature (secondary metrics)
   * UPDATED: Apply timeframe filtering, downsampling, and smoothing
   * FIXED: Only reinit when nodeId or timeframe actually changes
   */
  initSparkline(nodeId) {
    const canvas = document.getElementById('nodeSparkline');
    if (!canvas) return;

    // FIXED: Skip reinit if same node and timeframe already rendered
    // This prevents expensive recalculations on every data reload
    if (AnalyticsState.lastSparklineNodeId === nodeId && 
        AnalyticsState.lastSparklineTimeframe === AnalyticsState.selectedTimeframe &&
        AnalyticsState.charts.sparkline !== null) {
      console.log('[Analytics] Sparkline already initialized for node', nodeId, 'at timeframe', AnalyticsState.selectedTimeframe, '- skipping reinit');
      return;
    }

    const ctx = canvas.getContext('2d');
    const nodeData = AnalyticsState.nodeDetails[nodeId];
    
    if (!nodeData || !nodeData.sparkline_data) {
      console.warn('[Analytics] No sparkline data for node:', nodeId);
      return;
    }

    // UPDATED: Filter sparkline data by timeframe to match main trend chart
    // This ensures the sparkline respects the selected timeframe (24h, 7d, 30d, custom)
    let filteredData = nodeData.sparkline_data;
    const now = new Date();
    let cutoffTime = new Date();

    if (AnalyticsState.selectedTimeframe === '24h') {
      cutoffTime.setHours(cutoffTime.getHours() - 24);
    } else if (AnalyticsState.selectedTimeframe === '7d') {
      cutoffTime.setDate(cutoffTime.getDate() - 7);
    } else if (AnalyticsState.selectedTimeframe === '30d') {
      cutoffTime.setDate(cutoffTime.getDate() - 30);
    } else if (AnalyticsState.selectedTimeframe === 'custom') {
      // Use custom date range if set
      if (AnalyticsState.customDateStart) {
        cutoffTime = new Date(AnalyticsState.customDateStart);
      }
    }

    // Filter by timestamp
    filteredData = nodeData.sparkline_data.filter(point => {
      if (!point || !point.timestamp) return true; // Keep if no timestamp
      const pointDate = new Date(point.timestamp);
      if (isNaN(pointDate.getTime())) return true; // Guard: skip invalid dates
      if (AnalyticsState.selectedTimeframe === 'custom' && AnalyticsState.customDateEnd) {
        const endDate = new Date(AnalyticsState.customDateEnd);
        return pointDate >= cutoffTime && pointDate <= endDate;
      }
      return pointDate >= cutoffTime && pointDate <= now;
    });

    // Guard: handle empty filtered data
    if (filteredData.length === 0) {
      console.warn('[Analytics] Sparkline data empty after timeframe filtering for node:', nodeId);
      filteredData = nodeData.sparkline_data.slice(-50); // Fallback to last 50 points
    }

    // UPDATED: Apply downsampling and smoothing to sparkline data
    const downsampledData = Utils.downsampleData(filteredData, AnalyticsState.selectedTimeframe);
    const smoothedData = Utils.smoothData(downsampledData, 3);

    const labels = smoothedData.map(d => d.label || d.timestamp);
    
    // Extract multi-metric data from smoothed data
    const aqiPoints = smoothedData.map(d => d.aqi || d.value);
    const pm25Points = smoothedData.map(d => d.pm2_5 || null);
    const pm10Points = smoothedData.map(d => d.pm10 || null);
    const tempPoints = smoothedData.map(d => d.temperature || null);

    const aqiColor = Utils.getAQIColor(nodeData.aqi_current || 0);

    // Create gradient for AQI (primary)
    const gradient = ctx.createLinearGradient(0, 0, 0, 100);
    gradient.addColorStop(0, Utils.hexToRgba(aqiColor, 0.4));
    gradient.addColorStop(1, Utils.hexToRgba(aqiColor, 0.0));

    if (AnalyticsState.charts.sparkline) {
      AnalyticsState.charts.sparkline.destroy();
    }

    // Build multi-metric dataset array
    const datasets = [
      {
        label: 'AQI',
        data: aqiPoints,
        borderColor: aqiColor,
        backgroundColor: gradient,
        borderWidth: 2.5,
        pointRadius: 1,
        pointHoverRadius: 3,
        fill: true,
        tension: 0.3,
        yAxisID: 'y'
      }
    ];

    // Add secondary metrics if available
    if (pm25Points.some(v => v !== null)) {
      datasets.push({
        label: 'PM2.5',
        data: pm25Points,
        borderColor: '#991b1b',
        borderWidth: 1.5,
        pointRadius: 0.5,
        fill: false,
        tension: 0.3,
        borderDash: [2, 2],
        yAxisID: 'y1'
      });
    }

    if (pm10Points.some(v => v !== null)) {
      datasets.push({
        label: 'PM10',
        data: pm10Points,
        borderColor: '#f97316',
        borderWidth: 1.5,
        pointRadius: 0.5,
        fill: false,
        tension: 0.3,
        borderDash: [4, 4],
        yAxisID: 'y1'
      });
    }

    if (tempPoints.some(v => v !== null)) {
      datasets.push({
        label: 'Temp',
        data: tempPoints,
        borderColor: '#3b82f6',
        borderWidth: 1.5,
        pointRadius: 0.5,
        fill: false,
        tension: 0.3,
        borderDash: [6, 3],
        yAxisID: 'y2'
      });
    }

    AnalyticsState.charts.sparkline = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: { 
            position: 'left',
            display: false,
            min: 0, 
            max: 200 
          },
          y1: {
            type: 'linear',
            position: 'right',
            display: false,
            min: 0,
            max: 200
          },
          y2: {
            type: 'linear',
            position: 'right',
            display: false,
            min: -20,
            max: 50
          },
          x: { display: false }
        },
        plugins: { 
          legend: { display: false }, 
          tooltip: { 
            enabled: true,
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(0,0,0,0.8)',
            titleColor: '#fff',
            bodyColor: '#fff',
            borderColor: aqiColor,
            borderWidth: 1
          } 
        },
        layout: { padding: { top: 10, bottom: 5 } }
      }
    });

    // FIXED: Cache nodeId and timeframe to prevent unnecessary reinits
    AnalyticsState.lastSparklineNodeId = nodeId;
    AnalyticsState.lastSparklineTimeframe = AnalyticsState.selectedTimeframe;

    console.log('[Analytics] Sparkline initialized for node:', nodeId, 'with', datasets.length, 'metrics,', smoothedData.length, 'points (downsampled & smoothed)');
  }
};

// ============================================================================
// DOM UPDATES
// ============================================================================

const DOM = {
  /**
   * Update AQI value and badge in left panel
   */
  updateAQIDisplay() {
    const aqi = Math.round(AnalyticsState.overviewData.aqi_current || 0);
    const level = Utils.getAQILevel(aqi);
    const color = Utils.getAQIColor(aqi);

    const valueEl = document.querySelector('.aqi-value');
    if (valueEl) valueEl.innerText = aqi;

    const badgeEl = document.querySelector('.aqi-badge');
    if (badgeEl) {
      badgeEl.innerText = level.toUpperCase();
      badgeEl.style.background = color;
    }

    console.log('[Analytics] AQI display updated:', { aqi, level });
  },

  /**
   * Update pollutant bars (PM2.5, PM10, TVOC, Temp)
   */
  updatePollutantBars() {
    const data = AnalyticsState.overviewData;
    if (!data) return;

    const gasItems = [
      { id: 'pm25', label: 'PM2.5', value: data.pm2_5 || 0, unit: 'µg/m³', max: 100 },
      { id: 'pm10', label: 'PM10', value: data.pm10 || 0, unit: 'µg/m³', max: 150 },
      { id: 'tvoc', label: 'TVOC', value: data.tvoc || 0, unit: 'ppb', max: 200 },
      { id: 'temp', label: 'Temp', value: data.temperature || 0, unit: '°C', max: 50 }
    ];

    const gasList = document.querySelector('.gas-list');
    if (!gasList) return;

    gasItems.forEach(item => {
      const existingItem = gasList.querySelector(`[data-pollutant="${item.id}"]`);
      if (!existingItem) return;

      // Guard against NaN/Infinity
      const safeValue = isNaN(item.value) ? 0 : item.value;
      const fillPercent = Math.min((safeValue / item.max) * 100, 100);
      const color = Utils.getPollutantColor(item.id, safeValue);
      const valueSpan = existingItem.querySelector('.value');
      const fillDiv = existingItem.querySelector('.gas-fill');

      if (valueSpan) valueSpan.innerText = `${Math.round(safeValue)} ${item.unit}`;
      if (fillDiv) {
        fillDiv.style.width = fillPercent + '%';
        fillDiv.style.background = color;
      }
    });

    console.log('[Analytics] Pollutant bars updated');
  },

  /**
   * Populate node tiles dynamically (bottom left section) - OPTIMIZED + DEDUPED
   * Clears container before rendering, deduplicates by ID, respects filters
   * FIXED: Skip re-render if node list hasn't changed (performance optimization)
   */
  updateNodeTiles() {
    const nodeTilesContainer = document.querySelector('.node-tiles');
    if (!nodeTilesContainer || !AnalyticsState.allNodes) return;

    // Guard: ensure allNodes is an array
    if (!Array.isArray(AnalyticsState.allNodes)) {
      console.warn('[Analytics] allNodes is not an array');
      return;
    }

    // DEDUP: Filter nodes by node ID to remove duplicates, then by location/node filters
    const deduplicatedNodes = [];
    const seenIds = new Set();
    
    AnalyticsState.allNodes.forEach(node => {
      if (!node || !node.id || seenIds.has(String(node.id))) return; // Skip duplicates
      if (node.status === 'unregistered') return; // Skip unregistered
      
      // Respect location filter
      if (AnalyticsState.selectedLocation && node.location !== AnalyticsState.selectedLocation) {
        return; // Skip if location doesn't match filter
      }
      
      seenIds.add(String(node.id));
      deduplicatedNodes.push(node);
    });

    // FIXED: Check if nodes list has actually changed before re-rendering
    // This prevents unnecessary DOM mutations and re-renders on every data reload
    const currentHash = Utils.hashNodesList(deduplicatedNodes);
    if (!Utils.hasDataChanged(currentHash, AnalyticsState.lastNodesListHash)) {
      console.log('[Analytics] Node list unchanged, skipping re-render');
      return;
    }
    AnalyticsState.lastNodesListHash = currentHash;

    // CLEAR: Remove all existing tiles before re-rendering (prevents ghost elements)
    nodeTilesContainer.innerHTML = '';

    // Render deduplicated tiles
    deduplicatedNodes.forEach(node => {
      const aqi = node.aqi_current || 0;
      const color = Utils.getAQIColor(aqi);
      const trendIcon = node.trend_direction === 'up' ? 'fa-arrow-up' :
                        node.trend_direction === 'down' ? 'fa-arrow-down' : 'fa-minus';
      const onlineClass = node.status === 'inactive' ? 'offline' : '';
      const isActive = AnalyticsState.lockedNodeId === node.id;

      const tile = document.createElement('div');
      tile.className = `node-tile ${isActive ? 'active' : ''}`;
      tile.id = `tile-${node.id}`;
      tile.style.background = color;
      
      // Use addEventListener for cleaner handler attachment
      tile.addEventListener('mouseenter', () => UI.previewNode(node.id));
      tile.addEventListener('mouseleave', () => UI.clearPreview());
      tile.addEventListener('click', () => UI.lockNode(node.id));
      
      tile.innerHTML = `
        <div class="canalytics-nt-status ${onlineClass}"></div>
        <div class="nt-title">${(node.name || 'Node').substring(0, 5)}</div>
        <div class="nt-val">${Math.round(aqi)}</div>
        <i class="fas ${trendIcon} canalytics-nt-trend"></i>
      `;
      
      nodeTilesContainer.appendChild(tile);
    });

    console.log('[Analytics] Node tiles updated:', deduplicatedNodes.length, 'nodes (deduped, filtered)');
  },

  /**
   * Update drilldown panel for selected node
   */
  updateDrilldown(nodeId) {
    const nodeData = AnalyticsState.nodeDetails[nodeId];
    if (!nodeData) return;

    // Title and status
    const titleEl = document.getElementById('dd-title');
    if (titleEl) titleEl.innerText = nodeData.name || 'Unknown';

    const statusEl = document.getElementById('dd-status');
    if (statusEl) {
      const onlineClass = nodeData.status === 'active' ? 'online' : 'warning';
      const icon = nodeData.status === 'active' ? 'fa-wifi' : 'fa-exclamation-triangle';
      const text = nodeData.status === 'active' ? 'Online' : 'Elevated';
      statusEl.className = `canalytics-status-pill ${onlineClass}`;
      statusEl.innerHTML = `<i class="fas ${icon}"></i> ${text}`;
    }

    // Pollutant values - FIXED with guards
    const pm25El = document.getElementById('dd-pm25');
    if (pm25El) {
      const pm25 = typeof nodeData.pm2_5 === 'number' ? nodeData.pm2_5 : 0;
      pm25El.innerHTML = `${Math.round(isNaN(pm25) ? 0 : pm25)} <span style="font-size:0.55rem; font-weight:500; color:var(--text-muted);">µg/m³</span>`;
    }

    const pm10El = document.getElementById('dd-pm10');
    if (pm10El) {
      const pm10 = typeof nodeData.pm10 === 'number' ? nodeData.pm10 : 0;
      pm10El.innerHTML = `${Math.round(isNaN(pm10) ? 0 : pm10)} <span style="font-size:0.55rem; font-weight:500; color:var(--text-muted);">µg/m³</span>`;
    }

    const peakEl = document.getElementById('dd-peak');
    if (peakEl) {
      const peak = typeof nodeData.peak_24h === 'number' ? nodeData.peak_24h : 0;
      const safePeak = isNaN(peak) ? 0 : peak;
      peakEl.innerHTML = `${Math.round(safePeak)} <span style="font-size:0.55rem; font-weight:500; color:var(--text-muted);">AQI</span>`;
      peakEl.style.color = safePeak > 150 ? 'var(--unhealthy)' :
                           safePeak > 100 ? 'var(--moderate)' : 'var(--text-main)';
    }

    console.log('[Analytics] Drilldown updated for node:', nodeId);
  },

  /**
   * Update heatmap with dynamic data and visible values - FIXED event listener leaks
   * Uses title attribute instead of dynamic tooltip creation to avoid DOM leaks
   * FIXED: Only rebuild when trendsData actually changes (performance optimization)
   */
  updateHeatmap() {
    const heatmapWrapper = document.getElementById('heatmapWrapper');
    if (!heatmapWrapper || !AnalyticsState.trendsData) return;

    // FIXED: Check if trends data has actually changed before rebuilding
    // This prevents unnecessary DOM mutations on every reload
    const currentDataLength = AnalyticsState.trendsData.length;
    if (currentDataLength === AnalyticsState.lastTrendsDataLength && currentDataLength > 0) {
      console.log('[Analytics] Heatmap data unchanged, skipping rebuild');
      return;
    }
    AnalyticsState.lastTrendsDataLength = currentDataLength;

    heatmapWrapper.innerHTML = ''; // Clear

    // Group trend data by day with proper normalization
    const dayGroups = Utils.groupDataByDay(AnalyticsState.trendsData);
    if (dayGroups.length === 0) return;

    dayGroups.forEach(day => {
      const col = document.createElement('div');
      col.className = 'heatmap-col';

      const label = document.createElement('div');
      label.className = 'heatmap-lbl';
      label.innerText = day.label || 'N/A';
      col.appendChild(label);

      // Guard: ensure values is an array
      if (!Array.isArray(day.values)) return;

      day.values.forEach(value => {
        // Guard: validate value
        if (typeof value !== 'number' || isNaN(value)) return;

        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';
        cell.style.background = Utils.getAQIColor(value);
        cell.style.display = 'flex';
        cell.style.alignItems = 'center';
        cell.style.justifyContent = 'center';
        cell.style.position = 'relative';
        cell.style.fontSize = '0.55rem';
        cell.style.fontWeight = '700';
        cell.style.color = 'white';
        cell.innerHTML = `<span style="text-shadow: 0 1px 2px rgba(0,0,0,0.3);">${Math.round(value)}</span>`;
        // Use title attribute for built-in tooltip - avoids event listener leaks
        cell.title = `${Utils.getAQILevel(value)} - AQI: ${Math.round(value)}`;
        // Add data attribute for CSS tooltip if needed (cleaner than dynamic creation)
        cell.setAttribute('data-aqi', Math.round(value));

        col.appendChild(cell);
      });

      heatmapWrapper.appendChild(col);
    });

    console.log('[Analytics] Heatmap updated with', dayGroups.length, 'days');
  },

  /**
   * Update KPI row dynamically based on trends data - FIXED null guards
   */
  updateKPIRow() {
    if (!AnalyticsState.trendsData || AnalyticsState.trendsData.length === 0) return;

    // Guard: extract valid numeric values only
    const values = AnalyticsState.trendsData
      .map(d => {
        const v = d.value || 0;
        return (typeof v === 'number' && !isNaN(v)) ? v : 0;
      })
      .filter(v => v >= 0); // Include zero values
    
    if (values.length === 0) return; // No valid data
    
    const avgValue = Math.round(values.reduce((a, b) => a + b, 0) / values.length);
    const peakValue = Math.max(...values);
    
    // Calculate freshness based on last data timestamp
    let freshness = 'Live';
    let freshnessColor = 'var(--good)';
    
    if (AnalyticsState.trendsData.length > 0) {
      const lastDataTime = new Date(AnalyticsState.trendsData[AnalyticsState.trendsData.length - 1].timestamp || Date.now());
      const minutesAgo = Math.floor((Date.now() - lastDataTime) / 60000);
      
      if (minutesAgo > 5) {
        freshness = `Delayed (${minutesAgo}m)`;
        freshnessColor = 'var(--moderate)';
      } else if (minutesAgo > 0) {
        freshness = `${minutesAgo}m ago`;
        freshnessColor = 'var(--text-main)';
      }
    }

    // Determine sampling rate from data interval
    let samplingRate = '10s';
    if (AnalyticsState.selectedTimeframe === '24h') {
      samplingRate = '5-10s';
    } else if (AnalyticsState.selectedTimeframe === '7d') {
      samplingRate = '1m';
    } else if (AnalyticsState.selectedTimeframe === '30d') {
      samplingRate = '10m';
    }

    // Update KPI elements
    const kpiElements = document.querySelectorAll('.trend-kpi-row span');
    kpiElements.forEach(el => {
      if (el.textContent.includes('Avg:')) {
        el.innerHTML = `Avg: <strong style="color: var(--text-main);">${avgValue}</strong>`;
      } else if (el.textContent.includes('Peak:')) {
        el.innerHTML = `Peak: <strong style="color: ${peakValue > 150 ? 'var(--unhealthy)' : peakValue > 100 ? 'var(--moderate)' : 'var(--text-main)'};">${Math.round(peakValue)}</strong> <i class="fas fa-arrow-trend-up" style="color:${peakValue > 150 ? 'var(--unhealthy)' : peakValue > 100 ? 'var(--moderate)' : 'var(--text-main)'}; margin-left: 2px;"></i>`;
      } else if (el.textContent.includes('Freshness:')) {
        el.innerHTML = `Freshness: <strong style="color: ${freshnessColor};"><i class="fas fa-circle" style="font-size:0.4rem; vertical-align: middle;"></i> ${freshness}</strong>`;
      } else if (el.textContent.includes('Sampling:')) {
        el.innerHTML = `Sampling: <strong>${samplingRate}</strong>`;
      }
    });

    console.log('[Analytics] KPI row updated:', { avgValue, peakValue, freshness, samplingRate });
  },

  /**
   * Update risk distribution bar
   */
  updateRiskDistribution() {
    const data = AnalyticsState.overviewData;
    const stablePct = data.risk_stable || 60;
    const elevatedPct = data.risk_elevated || 25;
    const criticalPct = data.risk_critical || 15;

    const riskBar = document.querySelector('.canalytics-risk-bar');
    if (riskBar) {
      riskBar.innerHTML = `
        <div class="canalytics-risk-segment" style="width: ${stablePct}%; background: var(--good);" title="Stable: ${stablePct}%"></div>
        <div class="canalytics-risk-segment" style="width: ${elevatedPct}%; background: var(--moderate);" title="Elevated: ${elevatedPct}%"></div>
        <div class="canalytics-risk-segment" style="width: ${criticalPct}%; background: var(--unhealthy);" title="Critical: ${criticalPct}%"></div>
      `;
    }

    console.log('[Analytics] Risk distribution updated');
  },

  /**
   * Update system health metrics - FULLY DYNAMIC
   * Based on: node status, freshness, anomalies, data quality
   * FIXED: Added guards for missing DOM elements and invalid data
   */
  updateSystemHealth(healthData) {
    // Guard: ensure healthData is an object
    if (!healthData || typeof healthData !== 'object') {
      healthData = {};
    }

    // Calculate system status from nodes - FIXED with guards
    const onlineNodes = Array.isArray(AnalyticsState.allNodes) 
      ? AnalyticsState.allNodes.filter(n => n && n.status === 'active').length 
      : 0;
    const totalNodes = Array.isArray(AnalyticsState.allNodes) 
      ? AnalyticsState.allNodes.filter(n => n && n.status !== 'unregistered').length 
      : 0;
    
    let systemStatus = 'UNKNOWN';
    let reliability = 0;
    let statusIcon = 'fa-exclamation-circle';
    
    if (totalNodes === 0) {
      systemStatus = 'NO_NODES';
      reliability = 0;
    } else if (onlineNodes === totalNodes) {
      systemStatus = 'ONLINE';
      reliability = 99.8;
      statusIcon = 'fa-shield-check';
    } else if (onlineNodes > 0) {
      systemStatus = 'PARTIALLY_ONLINE';
      reliability = Math.round((onlineNodes / totalNodes) * 100);
      statusIcon = 'fa-exclamation-triangle';
    } else {
      systemStatus = 'OFFLINE';
      reliability = 0;
      statusIcon = 'fa-exclamation-circle';
    }

    // Get performance metrics from API response or use defaults - FIXED with type checks
    let latency = (typeof healthData.latency === 'number') ? healthData.latency : 1.2;
    let anomalies = (typeof healthData.anomalies === 'number') ? healthData.anomalies : 0;
    
    // Guard: ensure values are not NaN
    latency = isNaN(latency) ? 1.2 : latency;
    anomalies = isNaN(anomalies) ? 0 : anomalies;

    // Update reliability item - GUARD: check DOM element exists
    const reliabilityItem = document.querySelector('.canalytics-health-item');
    if (reliabilityItem) {
      const icon = reliabilityItem.querySelector('.canalytics-health-icon');
      const value = reliabilityItem.querySelector('.canalytics-health-value');
      const status = reliabilityItem.querySelector('[style*="font-size:0.6rem"]');
      
      if (icon) {
        icon.innerHTML = `<i class="fas ${statusIcon}"></i>`;
        icon.style.background = reliability >= 99 ? '#dcfce7' : reliability >= 90 ? '#fef3c7' : '#fee2e2';
        icon.style.color = reliability >= 99 ? '#166534' : reliability >= 90 ? '#92400e' : '#991b1b';
      }
      if (value) value.innerText = Math.round(reliability) + '%';
      if (status) {
        status.innerText = reliability >= 99 ? 'Healthy' : reliability >= 90 ? 'Degraded' : 'Critical';
        status.style.color = reliability >= 99 ? 'var(--good)' : reliability >= 90 ? 'var(--moderate)' : 'var(--unhealthy)';
      }
    }

    // Update performance item - GUARD: check DOM element exists
    const healthItems = document.querySelectorAll('.canalytics-health-item');
    const performanceItem = healthItems.length > 1 ? healthItems[1] : null;
    if (performanceItem) {
      const value = performanceItem.querySelector('.canalytics-health-value');
      const status = performanceItem.querySelector('[style*="font-size:0.6rem"]');
      if (value) value.innerText = latency.toFixed(2) + 's avg';
      if (status) {
        status.innerText = latency <= 1.5 ? 'Optimal' : latency <= 3 ? 'Good' : 'Slow';
        status.style.color = latency <= 1.5 ? 'var(--good)' : latency <= 3 ? 'var(--text-muted)' : 'var(--moderate)';
      }
    }

    // Update data quality item - GUARD: check DOM element exists
    const qualityItem = healthItems.length > 2 ? healthItems[2] : null;
    if (qualityItem) {
      const value = qualityItem.querySelector('.canalytics-health-value');
      const status = qualityItem.querySelector('button');
      if (value) {
        value.innerText = anomalies > 0 ? `${anomalies} Spikes Detected` : 'Clean';
      }
      if (anomalies > 0) {
        qualityItem.classList.add('canalytics-health-urgent');
        if (status) {
          status.style.display = '';
          status.innerText = 'Review';
        }
      } else {
        qualityItem.classList.remove('canalytics-health-urgent');
        if (status) status.style.display = 'none';
      }
    }

    console.log('[Analytics] System health updated:', { systemStatus, reliability, latency, anomalies });
  }
};

// ============================================================================
// UI INTERACTIONS
// ============================================================================

const UI = {
  /**
   * Preview node on hover (before locking)
   */
  previewNode(nodeId) {
    const regionEl = document.getElementById('dd-region');
    if (regionEl) regionEl.innerText = 'Previewing...';
    
    // Fetch if not cached
    if (!AnalyticsState.nodeDetails[nodeId]) {
      API.getNodeDetail(nodeId).then(() => {
        DOM.updateDrilldown(nodeId);
      });
    } else {
      DOM.updateDrilldown(nodeId);
    }
  },

  /**
   * Clear preview and return to locked node
   */
  clearPreview() {
    const regionEl = document.getElementById('dd-region');
    if (regionEl) regionEl.innerText = 'Focus Node';
    
    if (AnalyticsState.lockedNodeId) {
      DOM.updateDrilldown(AnalyticsState.lockedNodeId);
    }
  },

  /**
   * Lock node selection and update all panels
   */
  lockNode(nodeId) {
    AnalyticsState.lockedNodeId = nodeId;
    AnalyticsState.selectedNode = nodeId;

    // Update tile styling
    document.querySelectorAll('.node-tile').forEach(t => t.classList.remove('active'));
    const tile = document.getElementById(`tile-${nodeId}`);
    if (tile) tile.classList.add('active');

    // Fetch and display
    if (!AnalyticsState.nodeDetails[nodeId]) {
      API.getNodeDetail(nodeId).then(() => {
        DOM.updateDrilldown(nodeId);
        Charts.initSparkline(nodeId);
      });
    } else {
      DOM.updateDrilldown(nodeId);
      Charts.initSparkline(nodeId);
    }

    console.log('[Analytics] Node locked:', nodeId);
  },

  /**
   * Toggle trend view (line vs heatmap) - FIXED strict toggle
   */
  toggleTrendView(view, element) {
    // Ensure only ONE view is visible
    if (AnalyticsState.isTrendView === view) return; // Already active
    
    AnalyticsState.isTrendView = view;

    // Update button styling
    const toggleGroups = document.querySelectorAll('.gas-toggles');
    const viewButtons = toggleGroups.length ? toggleGroups[0].querySelectorAll('.gas-btn') : [];
    viewButtons.forEach(btn => btn.classList.remove('active'));
    if (element) {
      element.classList.add('active');
    } else {
      const defaultBtn = toggleGroups.length
        ? toggleGroups[0].querySelector(view === 'line' ? '#btnLineView' : '#btnHeatmapView')
        : null;
      if (defaultBtn) defaultBtn.classList.add('active');
    }

    // Strictly show/hide containers - only ONE visible
    const lineWrapper = document.getElementById('lineChartWrapper');
    const heatmapWrapper = document.getElementById('heatmapWrapper');

    if (view === 'line') {
      if (lineWrapper) lineWrapper.style.display = 'block';
      if (heatmapWrapper) heatmapWrapper.style.display = 'none';
      // Ensure chart is initialized
      if (AnalyticsState.charts.trendLine === null) {
        Charts.initTrendLine();
      }
    } else if (view === 'heatmap') {
      if (lineWrapper) lineWrapper.style.display = 'none';
      if (heatmapWrapper) heatmapWrapper.style.display = 'grid';
      // Generate heatmap
      DOM.updateHeatmap();
    }

    console.log('[Analytics] Trend view toggled to:', view);
  },

  /**
   * Update trend chart metric (AQI, PM2.5, PM10, Temp) - OPTIMIZED
   * Only reloads trends data, not full re-initialization
   */
  updateTrendChart(metric, element) {
    AnalyticsState.selectedMetric = metric;

    // Update button state
    const toggleGroups = document.querySelectorAll('.gas-toggles');
    const metricButtons = toggleGroups.length ? toggleGroups[toggleGroups.length - 1].querySelectorAll('.gas-btn') : [];
    metricButtons.forEach(btn => {
      btn.classList.remove('active');
    });
    if (element) element.classList.add('active');

    // Fetch new trend data and update visualization
    API.getTrends().then(data => {
      if (data) {
        // Update current view
        if (AnalyticsState.isTrendView === 'line') {
          Charts.initTrendLine();
        } else if (AnalyticsState.isTrendView === 'heatmap') {
          DOM.updateHeatmap();
        }
        DOM.updateKPIRow(); // Update KPI with new metric
      }
    }).catch(err => {
      console.warn('[Analytics] Failed to update metric:', err);
    });

    console.log('[Analytics] Trend metric changed to:', metric);
  },

  /**
   * Handle timeframe selection - OPTIMIZED to avoid full re-initialization
   * Only reloads data, not chart recreation
   */
  setTimeframe(timeframe, element) {
    // Auto-disable custom date mode if switching away from it
    if (timeframe !== 'custom') {
      AnalyticsState.isCustomDate = false;
      const customGroup = document.getElementById('customDateGroup');
      if (customGroup) customGroup.style.display = 'none';
    }

    AnalyticsState.selectedTimeframe = timeframe;

    // Update all filter pills to remove active, then set only the clicked one
    const pills = document.querySelectorAll('.range-pill');
    pills.forEach(pill => pill.classList.remove('active'));
    
    if (element) {
      element.classList.add('active');
    } else {
      // Fallback: find by text
      pills.forEach(pill => {
        if (pill.textContent.includes(timeframe.toUpperCase())) {
          pill.classList.add('active');
        }
      });
    }

    // Reload only data, not full re-initialization
    debouncedReloadAnalyticsData();

    console.log('[Analytics] Timeframe changed to:', timeframe);
  },

  /**
   * Toggle custom date picker - FIXED state management
   * Prevents auto-showing, ensures exclusive activation
   */
  toggleCustomDate(isCustom, element) {
    AnalyticsState.isCustomDate = isCustom;
    
    // Remove active from all pills first
    const pills = document.querySelectorAll('.range-pill');
    pills.forEach(p => p.classList.remove('active'));
    
    if (element && isCustom) {
      element.classList.add('active');
    }
    
    const customGroup = document.getElementById('customDateGroup');
    if (customGroup) {
      customGroup.style.display = isCustom ? 'flex' : 'none';
    }

    if (isCustom) {
      // Extract dates from inputs and set timeframe to 'custom'
      const dateInputs = customGroup ? Array.from(customGroup.querySelectorAll('input[type="date"]')) : [];
      const startInput = dateInputs[0];
      const endInput = dateInputs[dateInputs.length - 1];
      
      if (startInput && endInput) {
        AnalyticsState.customDateStart = startInput.value;
        AnalyticsState.customDateEnd = endInput.value;
        AnalyticsState.selectedTimeframe = 'custom';
        if (Utils.isCustomDateRangeValid()) {
          debouncedReloadAnalyticsData();
        }
      }
    }

    console.log('[Analytics] Custom date mode:', isCustom);
  }
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

const Utils = {
  /**
   * Get AQI color based on value
   */
  getAQIColor(aqi) {
    // Guard: handle undefined/null/NaN values
    if (typeof aqi !== 'number' || isNaN(aqi)) {
      return '#64748b'; // neutral gray for invalid values
    }
    if (aqi <= 50) return '#10b981';  // good - green
    if (aqi <= 100) return '#f59e0b'; // moderate - amber
    if (aqi <= 150) return '#f97316'; // unhealthy-sensitive - orange
    if (aqi <= 200) return '#ef4444'; // unhealthy - red
    if (aqi <= 300) return '#991b1b'; // very unhealthy - dark red
    return '#4b0000'; // hazardous - maroon
  },

  /**
   * Get AQI level text
   */
  getAQILevel(aqi) {
    if (aqi <= 50) return 'Good';
    if (aqi <= 100) return 'Moderate';
    if (aqi <= 150) return 'Unhealthy (Sensitive)';
    if (aqi <= 200) return 'Unhealthy';
    if (aqi <= 300) return 'Very Unhealthy';
    return 'Hazardous';
  },

  /**
   * Get pollutant color for bars
   */
  getPollutantColor(pollutant, value) {
    const aqi = value; // Simplified - use value as proxy
    return Utils.getAQIColor(aqi);
  },

  /**
   * Get metric label for chart
   */
  getMetricLabel(metric) {
    const labels = {
      'aqi': 'AQI',
      'pm25': 'PM2.5',
      'pm10': 'PM10',
      'temp': 'Temperature'
    };
    return labels[metric] || metric;
  },

  /**
   * Convert hex color to RGBA
   */
  hexToRgba(hex, alpha = 1) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  },

  /**
   * ADDED: Downsample data based on timeframe
   * Reduces rendered points: 24h→100, 7d→140, 30d→180
   * Uses bucket-based averaging to maintain trends
   */
  downsampleData(data, timeframe) {
    if (!Array.isArray(data) || data.length === 0) return [];

    // Determine max points based on timeframe
    const maxPoints = timeframe === '24h' ? 100 : 
                      timeframe === '7d' ? 140 : 
                      timeframe === '30d' ? 180 : 100;

    // If data is already small, return as-is
    if (data.length <= maxPoints) return data;

    // Calculate bucket size (how many points to average per bucket)
    const bucketSize = Math.ceil(data.length / maxPoints);
    const downsampled = [];

    for (let i = 0; i < data.length; i += bucketSize) {
      const bucket = data.slice(i, i + bucketSize);
      if (bucket.length === 0) continue;

      // Average values in bucket, preserve first label
      const avgValue = bucket.reduce((sum, p) => {
        const v = typeof p.value === 'number' ? p.value : (typeof p.aqi === 'number' ? p.aqi : 0);
        return sum + v;
      }, 0) / bucket.length;

      downsampled.push({
        ...bucket[0], // Preserve original structure
        value: avgValue,
        aqi: avgValue, // Ensure both fields are set for compatibility
        timestamp: bucket[0].timestamp || bucket[0].date,
        label: bucket[0].label || bucket[0].timestamp
      });
    }

    console.log(`[Analytics] Data downsampled: ${data.length} → ${downsampled.length} points (${timeframe})`);
    return downsampled;
  },

  /**
   * ADDED: Apply moving average smoothing to reduce noise
   * Window size 3-5, processes only numeric values
   * Does NOT modify original data
   */
  smoothData(data, windowSize = 3) {
    if (!Array.isArray(data) || data.length < 2) return data;

    // Guard: ensure windowSize is valid
    windowSize = Math.max(1, Math.min(windowSize, data.length));

    const smoothed = data.map((point, idx) => {
      // Guard: ensure value is numeric
      const centerValue = typeof point.value === 'number' ? point.value : 
                          (typeof point.aqi === 'number' ? point.aqi : 0);
      
      if (windowSize === 1) {
        return { ...point }; // No smoothing needed
      }

      // Calculate window boundaries
      const halfWindow = Math.floor(windowSize / 2);
      const start = Math.max(0, idx - halfWindow);
      const end = Math.min(data.length - 1, idx + halfWindow);

      // Average values in window
      let sum = 0;
      let count = 0;
      for (let i = start; i <= end; i++) {
        const v = typeof data[i].value === 'number' ? data[i].value : 
                  (typeof data[i].aqi === 'number' ? data[i].aqi : 0);
        sum += v;
        count++;
      }

      const smoothedValue = count > 0 ? sum / count : centerValue;

      return {
        ...point,
        value: smoothedValue,
        aqi: smoothedValue // Ensure both fields are updated
      };
    });

    console.log(`[Analytics] Data smoothed with moving average (window=${windowSize})`);
    return smoothed;
  },

  /**
   * Debounce async functions to prevent repeated API requests
   */
  debounce(fn, delay = 300) {
    let timer = null;
    let pendingReject = null;
    return (...args) => {
      if (timer) {
        clearTimeout(timer);
        if (pendingReject) {
          pendingReject({ canceled: true });
          pendingReject = null;
        }
      }
      return new Promise((resolve, reject) => {
        pendingReject = reject;
        timer = setTimeout(async () => {
          timer = null;
          pendingReject = null;
          try {
            resolve(await fn(...args));
          } catch (error) {
            reject(error);
          }
        }, delay);
      });
    };
  },

  /**
   * Validate custom date range before requesting analytics data
   */
  isCustomDateRangeValid() {
    if (AnalyticsState.selectedTimeframe !== 'custom') return true;
    const start = AnalyticsState.customDateStart;
    const end = AnalyticsState.customDateEnd;
    if (!start || !end) {
      console.warn('[Analytics] Custom date range invalid: missing start or end date');
      return false;
    }
    const startDate = new Date(start);
    const endDate = new Date(end);
    if (isNaN(startDate.getTime()) || isNaN(endDate.getTime()) || startDate > endDate) {
      console.warn('[Analytics] Custom date range invalid: start_date must be <= end_date');
      return false;
    }
    return true;
  },

  /**
   * ADDED: Generate simple hash of node list for deduplication checks
   * Detects if nodes list has actually changed (ID + count comparison)
   */
  hashNodesList(nodes) {
    if (!Array.isArray(nodes) || nodes.length === 0) return '';
    // Create hash from sorted node IDs and location filter
    const ids = nodes
      .filter(n => n && n.id)
      .map(n => String(n.id))
      .sort((a, b) => parseInt(a) - parseInt(b))
      .join(',');
    return `${ids}_${AnalyticsState.selectedLocation || 'all'}`;
  },

  /**
   * ADDED: Check if data has meaningfully changed
   * Prevents unnecessary re-renders when data structure hasn't changed
   */
  hasDataChanged(currentHash, lastHash) {
    return currentHash !== lastHash;
  },

  /**
   * Group trend data by day - FIXED timestamp normalization
   */
  groupDataByDay(data) {
    if (!Array.isArray(data)) return [];
    
    const grouped = {};
    
    data.forEach(point => {
      if (!point) return; // Guard: skip null/undefined
      
      // Extract date in consistent format (YYYY-MM-DD)
      let date = null;
      if (point.date) {
        date = point.date.split('T')[0]; // Handle ISO format
      } else if (point.timestamp) {
        date = new Date(point.timestamp).toISOString().split('T')[0];
      } else if (point.label) {
        // Try to parse label if it contains a date
        date = point.label.split(' ')[0];
      }
      
      if (!date) return; // Skip if no valid date
      
      if (!grouped[date]) {
        grouped[date] = { label: date, values: [] };
      }
      
      // Guard: ensure value is valid number
      if (typeof point.value === 'number' && !isNaN(point.value)) {
        grouped[date].values.push(point.value);
      }
    });

    return Object.values(grouped)
      .sort((a, b) => new Date(a.label) - new Date(b.label))
      .slice(-8);
  },

  /**
   * Generate full time-series range with interpolation
   * Fills missing dates based on timeframe selection
   */
  generateTimeSeriesRange(trendsData, timeframe) {
    if (trendsData.length === 0) return [];

    // Sort by timestamp or fallback to date string
    const sorted = [...trendsData].sort((a, b) => {
      const aDate = new Date(a.timestamp || a.date);
      const bDate = new Date(b.timestamp || b.date);
      return aDate - bDate;
    });

    const result = [];
    const startDate = new Date(sorted[0].timestamp || sorted[0].date);
    const endDate = new Date(sorted[sorted.length - 1].timestamp || sorted[sorted.length - 1].date);

    // Determine interval based on timeframe
    let intervalMs = 3600000; // 1 hour default
    let labelFormat = 'short'; // 'short' = HH:MM, 'long' = MMM DD

    if (timeframe === '24h') {
      intervalMs = 3600000; // 1 hour
      labelFormat = 'time'; // HH:MM
    } else if (timeframe === '7d') {
      intervalMs = 86400000; // 1 day
      labelFormat = 'date'; // MMM DD
    } else if (timeframe === '30d') {
      intervalMs = 86400000 * 2; // 2 days
      labelFormat = 'date';
    }

    // Generate date range
    let currentDate = new Date(startDate);
    const dataMap = new Map();
    
    // Map existing data by rounded timestamp
    sorted.forEach(point => {
      const timestamp = new Date(point.timestamp || point.date);
      if (isNaN(timestamp)) return;
      const key = Math.floor(timestamp.getTime() / intervalMs);
      if (!dataMap.has(key) || !dataMap.get(key).value) {
        dataMap.set(key, point);
      }
    });

    // Fill range
    while (currentDate <= endDate) {
      const key = Math.floor(currentDate.getTime() / intervalMs);
      const existingData = dataMap.get(key);

      let label = '';
      if (labelFormat === 'time') {
        label = currentDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
      } else if (labelFormat === 'date') {
        label = currentDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      }

      result.push({
        label: label,
        timestamp: currentDate.toISOString(),
        value: existingData?.value || null,
        date: currentDate.toISOString().split('T')[0]
      });

      currentDate = new Date(currentDate.getTime() + intervalMs);
    }

    return result;
  }
};

// ============================================================================
// FILTER MANAGEMENT
// ============================================================================

/**
 * Populate node group filter dropdown with Nodes + Locations - FIXED duplicate listeners
 * Uses flag to prevent re-adding event listeners
 * FIXED: Prevent redundant API calls when selecting same filter value
 */
let nodeFilterListenerAttached = false;

function populateNodeFilter() {
  const filterSelect = document.getElementById('nodeFilter');
  if (!filterSelect) return;

  // Guard: ensure allNodes is array
  if (!Array.isArray(AnalyticsState.allNodes)) {
    console.warn('[Analytics] allNodes is not an array');
    return;
  }

  // Store current selection
  const currentValue = filterSelect.value;

  // Clear existing options except first
  while (filterSelect.options.length > 1) {
    filterSelect.remove(1);
  }

  // Add nodes group
  const nodesOptGroup = document.createElement('optgroup');
  nodesOptGroup.label = 'Nodes';
  
  AnalyticsState.allNodes.forEach(node => {
    if (!node || !node.id) return; // Skip invalid nodes
    const option = document.createElement('option');
    option.value = `node_${node.id}`;
    const aqi = node.aqi_current || 0;
    option.text = `${node.name || 'Unknown'} (${Utils.getAQILevel(aqi)})`;
    nodesOptGroup.appendChild(option);
  });
  filterSelect.appendChild(nodesOptGroup);

  // Add locations group if available
  if (Array.isArray(AnalyticsState.allLocations) && AnalyticsState.allLocations.length > 0) {
    const locationsOptGroup = document.createElement('optgroup');
    locationsOptGroup.label = 'Locations';
    
    AnalyticsState.allLocations.forEach(location => {
      if (!location) return; // Skip empty locations
      const option = document.createElement('option');
      option.value = `location_${location}`;
      option.text = location;
      locationsOptGroup.appendChild(option);
    });
    filterSelect.appendChild(locationsOptGroup);
  }

  // Restore or reset selection
  filterSelect.value = currentValue;

  // FIXED: Only add listener once, not on every populate call
  if (!nodeFilterListenerAttached) {
    filterSelect.addEventListener('change', (e) => {
      const value = e.target.value;
      
      // FIXED: Skip if same filter value selected (prevents redundant API calls)
      if (value === AnalyticsState.lastFilterValue) {
        console.log('[Analytics] Same filter value selected, skipping reload');
        return;
      }
      AnalyticsState.lastFilterValue = value;

      if (value === 'all') {
        AnalyticsState.selectedNode = null;
        AnalyticsState.selectedLocation = null;
      } else if (value.startsWith('node_')) {
        AnalyticsState.selectedNode = value.replace('node_', '');
        AnalyticsState.selectedLocation = null; // Clear location filter
      } else if (value.startsWith('location_')) {
        // IMPLEMENTED: Location-based filtering
        AnalyticsState.selectedLocation = value.replace('location_', '');
        AnalyticsState.selectedNode = null; // Clear node filter
        console.log('[Analytics] Location filter selected:', AnalyticsState.selectedLocation);
      }
      // Only reload data, not full initialize
      debouncedReloadAnalyticsData();
    });
    nodeFilterListenerAttached = true;
  }

  console.log('[Analytics] Node filter populated');
}

/**
 * Reload analytics data without full re-initialization
 * Separates data loading from chart initialization for better performance
 * UPDATED: Also reloads sparkline when timeframe changes
 * FIXED: Prevent redundant chart updates when data hasn't changed
 */
async function reloadAnalyticsData() {
  console.log('[Analytics] Reloading data for current filters...');

  if (AnalyticsState.selectedTimeframe === 'custom' && !Utils.isCustomDateRangeValid()) {
    console.warn('[Analytics] Data reload skipped due to invalid custom date range');
    return;
  }

  if (AnalyticsState.isLoading) return; // Prevent concurrent requests
  AnalyticsState.isLoading = true;

  try {
    // Load data in parallel
    await Promise.allSettled([
      API.getOverview(),
      API.getTrends(),
      API.getForecast()
    ]);

    // Update affected UI elements only
    DOM.updateAQIDisplay();
    DOM.updatePollutantBars();
    DOM.updateRiskDistribution();
    DOM.updateKPIRow();
    DOM.updateNodeTiles(); // UPDATED: Refresh node tiles on reload

    // FIXED: Only update trend charts if view is currently active and data changed
    // Skip unnecessary recreates when switching between views
    if (AnalyticsState.isTrendView === 'line') {
      // initTrendLine now checks if metric changed and updates data instead of recreate
      Charts.initTrendLine();
    } else if (AnalyticsState.isTrendView === 'heatmap') {
      // updateHeatmap now checks if data length changed before rebuilding
      DOM.updateHeatmap();
    }

    // FIXED: Only reinit sparkline if nodeId and timeframe have actually changed
    // This prevents expensive recalculations on every data reload
    if (AnalyticsState.lockedNodeId && AnalyticsState.nodeDetails[AnalyticsState.lockedNodeId]) {
      // Charts.initSparkline now checks if nodeId/timeframe changed and skips if not
      Charts.initSparkline(AnalyticsState.lockedNodeId);
    }

    console.log('[Analytics] Data reload complete');
  } catch (error) {
    console.error('[Analytics] Data reload failed:', error);
  } finally {
    AnalyticsState.isLoading = false;
  }
}

const debouncedReloadAnalyticsData = Utils.debounce(reloadAnalyticsData, 300);

/**
 * Main initialization function - REFACTORED
 * Separates data loading from UI rendering for better state management
 */
async function initialize() {
  console.log('[Analytics] Initializing dashboard...');

  AnalyticsState.isLoading = true;

  try {
    // Load all initial data in parallel
    // Use Promise.allSettled to ensure one API failure doesn't break everything
    await Promise.allSettled([
      API.getOverview(),
      API.getNodes(),
      API.getTrends(),
      API.getSystemHealth(),
      API.getForecast()
    ]);

    // Populate filters with dynamic data
    populateNodeFilter();

    // Update UI with current data
    DOM.updateAQIDisplay();
    DOM.updatePollutantBars();
    DOM.updateNodeTiles();
    DOM.updateRiskDistribution();
    DOM.updateKPIRow();

    // Initialize charts
    Charts.initAQIDonut();
    Charts.initCompDonut();
    Charts.initTrendLine();

    // Ensure charts are visible
    UI.toggleTrendView(AnalyticsState.isTrendView);

    // 2. CHANGED: Added safety check (AnalyticsState.allNodes && ...)
    // If the getNodes API 404s, allNodes might be undefined or empty.
    if (AnalyticsState.allNodes && AnalyticsState.allNodes.length > 0) {
      const firstNode = AnalyticsState.allNodes[0];
      AnalyticsState.lockedNodeId = firstNode.id;
      
      // 3. CHANGED: Wrapped in its own try/catch so a drilldown 404 doesn't break the UI
      try {
        await API.getNodeDetail(firstNode.id);
      } catch (e) {
        console.warn(`[Analytics] Could not fetch details for node ${firstNode.id}`);
      }
      
      DOM.updateDrilldown(firstNode.id);
      Charts.initSparkline(firstNode.id);
      
      // Mark as active
      const tile = document.getElementById(`tile-${firstNode.id}`);
      if (tile) tile.classList.add('active');
    }

    // Update system health
    DOM.updateSystemHealth(AnalyticsState.systemHealthData || {});

    console.log('[Analytics] Dashboard initialized successfully');
  } catch (error) {
    console.error('[Analytics] Initialization failed:', error);
  } finally {
    AnalyticsState.isLoading = false;
  }
}


// ============================================================================
// EXPORT FOR TEMPLATE ACCESS
// ============================================================================

// Make functions available to template onclick handlers
window.toggleCustomDate = UI.toggleCustomDate;
window.toggleTrendView = UI.toggleTrendView;
window.updateTrendChart = UI.updateTrendChart;
window.setTimeframe = UI.setTimeframe;
window.previewNode = UI.previewNode;
window.clearPreview = UI.clearPreview;
window.lockNode = UI.lockNode;
window.openAIModal = (type) => {
  const modal = document.getElementById('aiModal');
  if (modal) modal.classList.add('active');
};
window.closeAIModal = () => {
  const modal = document.getElementById('aiModal');
  if (modal) modal.classList.remove('active');
};

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialize);
} else {
  initialize();
}
