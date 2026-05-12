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
  nodeDetails: {},
  systemHealthData: {},

  // Chart instances
  charts: {
    aqiDonut: null,
    compDonut: null,
    trendLine: null,
    sparkline: null,
  },

  // Error state management
  lastError: null,
  errorNotificationShown: false,

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

  pendingRequests: new Map(), // Track in-flight requests by key
  requestTimestamps: {}, // Track last request time per endpoint
  requestDebounceMs: 300, // Min time between same requests
  lastNodesListHash: null, // Hash of last rendered nodes list
  lastTrendsDataLength: 0, // Track trends data changes
  lastHeatmapHash: null, // Track heatmap data changes
  lastSparklineNodeId: null, // Cache last sparkline node
  lastSparklineTimeframe: null, // Cache last sparkline timeframe
  lastFilterValue: 'all', // Track filter selection
  lastTrendMetric: 'aqi', // Track last metric selection
  trendChartUpdateInProgress: false, // Prevent concurrent updates

  // ⚡ OPTIMIZATION: Request deduplication
  lastRequestParams: {} // Track last params for each API call
};

// ============================================================================
// API INTEGRATION
// ============================================================================
function getDedupKey(endpoint, params) {
  const paramStr = new URLSearchParams(params).toString();
  return `${endpoint}?${paramStr}`;
}

function shouldSkipRequest(endpoint, params, debounceMs = 300) {
  const key = getDedupKey(endpoint, params);
  const lastTime = AnalyticsState.requestTimestamps[key] || 0;
  const now = Date.now();
  
  if (now - lastTime < debounceMs) {
    console.log(`[Analytics] Skipping duplicate request: ${key}`);
    return true;
  }
  
  AnalyticsState.requestTimestamps[key] = now;
  return false;
}

const API = {
  async getOverview() {
    try {
      const params = {
        timeframe: AnalyticsState.selectedTimeframe,
        node_id: AnalyticsState.selectedNode || 'all',
        location: AnalyticsState.selectedLocation || 'all',
        start_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateStart || '' : '',
        end_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateEnd || '' : ''
      };
      if (shouldSkipRequest('/api/analytics/overview/', params)) {
        return AnalyticsState.overviewData;
      }

      const response = await fetch(`/api/analytics/overview/?${new URLSearchParams(params)}`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      console.log('[Analytics] Overview data loaded:', data);
      AnalyticsState.overviewData = data;
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch overview:', error);
      return AnalyticsState.overviewData || null;
    }
  },

  async getNodes() {
    try {
      if (shouldSkipRequest('/api/nodes/', {})) {
        return AnalyticsState.allNodes;
      }

      const response = await fetch('/api/nodes/', {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      AnalyticsState.allNodes = data.results || data.nodes || [];
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
      return AnalyticsState.allNodes || [];
    }
  },

  async getNodeDetail(nodeId) {
    try {
      if (AnalyticsState.nodeDetails[nodeId]) {
        return AnalyticsState.nodeDetails[nodeId];
      }

      if (shouldSkipRequest(`/api/nodes/${nodeId}/detail/`, {})) {
        return AnalyticsState.nodeDetails[nodeId] || null;
      }

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
  async getTrends() {
    try {
      const params = {
        timeframe: AnalyticsState.selectedTimeframe,
        metric: AnalyticsState.selectedMetric,
        node_id: AnalyticsState.selectedNode || 'all',
        location: AnalyticsState.selectedLocation || 'all',
        start_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateStart || '' : '',
        end_date: AnalyticsState.selectedTimeframe === 'custom' ? AnalyticsState.customDateEnd || '' : ''
      };
      if (shouldSkipRequest('/api/analytics/trends/', params)) {
        return AnalyticsState.trendsData;
      }

      const response = await fetch(`/api/analytics/trends/?${new URLSearchParams(params)}`, {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      
      console.log('[Analytics] Trends data loaded:', data.datapoints?.length || 0, 'points (aggregated)');
      AnalyticsState.trendsData = data.datapoints || [];
      return data;
    } catch (error) {
      console.error('[Analytics] Failed to fetch trends:', error);
      return null;
    }
  },

  async getSystemHealth() {
    try {
      if (shouldSkipRequest('/api/analytics/system-health/', {})) {
        return AnalyticsState.systemHealthData;
      }

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
  }
};

// ============================================================================
// CHART INITIALIZATION & UPDATES
// ============================================================================

const Charts = {
  initAQIDonut() {
    const canvas = document.getElementById('aqiDonutChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let aqi = AnalyticsState.overviewData.aqi_current || 0;
    if (typeof aqi !== 'number' || isNaN(aqi)) {
      aqi = 0;
    }
    
    // Get composition percentages from overview data
    let pm25Pct = AnalyticsState.overviewData.composition?.pm25 || 55;
    let pm10Pct = AnalyticsState.overviewData.composition?.pm10 || 25;
    let otherPct = AnalyticsState.overviewData.composition?.other || 20;
    
    // Ensure valid percentages
    pm25Pct = (typeof pm25Pct === 'number' && !isNaN(pm25Pct)) ? pm25Pct : 55;
    pm10Pct = (typeof pm10Pct === 'number' && !isNaN(pm10Pct)) ? pm10Pct : 25;
    otherPct = (typeof otherPct === 'number' && !isNaN(otherPct)) ? otherPct : 20;
    
    // Normalize percentages to sum to 100
    const total = pm25Pct + pm10Pct + otherPct;
    if (total !== 100) {
      const factor = 100 / total;
      pm25Pct = Math.round(pm25Pct * factor);
      pm10Pct = Math.round(pm10Pct * factor);
      otherPct = Math.round(otherPct * factor);
      // Correct rounding errors
      const sum = pm25Pct + pm10Pct + otherPct;
      if (sum > 100) otherPct -= (sum - 100);
      else if (sum < 100) otherPct += (100 - sum);
    }

    // UPDATED: Use dynamic colors based on AQI quality level
    let pm25Color, pm10Color, otherColor;
    if (aqi <= 50) {
      // Good - use green shades
      pm25Color = '#10b981';
      pm10Color = '#6ee7b7';
      otherColor = '#a7f3d0';
    } else if (aqi <= 100) {
      // Moderate - use yellow/orange shades
      pm25Color = '#f97316';
      pm10Color = '#fb923c';
      otherColor = '#fdba74';
    } else if (aqi <= 150) {
      // Unhealthy for Sensitive - use red/orange shades
      pm25Color = '#ef4444';
      pm10Color = '#f87171';
      otherColor = '#fca5a5';
    } else if (aqi <= 200) {
      // Unhealthy - use dark red shades
      pm25Color = '#dc2626';
      pm10Color = '#991b1b';
      otherColor = '#7f1d1d';
    } else {
      // Very Unhealthy/Hazardous - use darkest reds
      pm25Color = '#7f1d1d';
      pm10Color = '#600101';
      otherColor = '#450101';
    }

    if (AnalyticsState.charts.aqiDonut) {
      AnalyticsState.charts.aqiDonut.destroy();
    }

    AnalyticsState.charts.aqiDonut = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['PM2.5', 'PM10', 'Other'],
        datasets: [{
          data: [pm25Pct, pm10Pct, otherPct],
          backgroundColor: [pm25Color, pm10Color, otherColor],
          borderWidth: 0,
          cutout: '80%'
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
          legend: { display: false }
        }
      }
    });

    console.log('[Analytics] AQI Donut initialized with composition:', { aqi, pm25Pct, pm10Pct, otherPct, colors: { pm25Color, pm10Color, otherColor } });
  },
  initCompDonut() {
    const canvas = document.getElementById('compDonutChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let pm25Pct = AnalyticsState.overviewData.composition?.pm25 || 55;
    let pm10Pct = AnalyticsState.overviewData.composition?.pm10 || 25;
    let otherPct = AnalyticsState.overviewData.composition?.other || 20;
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

  initTrendLine() {
    const canvas = document.getElementById('dateTrendChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const maxPoints = {
      '24h': 60,
      '7d': 80,
      '30d': 90
    }[AnalyticsState.selectedTimeframe] || 60;
    
    let trendData = AnalyticsState.trendsData || [];

    if (trendData.length > maxPoints) {
      const step = Math.ceil(trendData.length / maxPoints);
      trendData = trendData.filter((_, i) => i % step === 0);
      console.log(`[Analytics] Frontend downsampled ${AnalyticsState.trendsData.length} → ${trendData.length} points`);
    }
    
    const downsampledData = Utils.downsampleData(trendData, AnalyticsState.selectedTimeframe);
    const smoothedData = Utils.smoothData(downsampledData, 3);
    const fullTimeSeries = Utils.generateTimeSeriesRange(smoothedData, AnalyticsState.selectedTimeframe);
    const labels = fullTimeSeries.map(d => d.label);
    const dataPoints = fullTimeSeries.map(d => d.value);
    const lastRealIndex = smoothedData.length - 1;

    if (AnalyticsState.charts.trendLine !== null && AnalyticsState.lastTrendMetric === AnalyticsState.selectedMetric) {
      if (AnalyticsState.charts.trendLine.data && AnalyticsState.charts.trendLine.data.datasets) {
        AnalyticsState.charts.trendLine.data.labels = labels;
        AnalyticsState.charts.trendLine.data.datasets[0].data = dataPoints;
        
        AnalyticsState.charts.trendLine.update('none'); // Update without animation
        console.log('[Analytics] Trend chart data updated (no destroy/recreate)');
        return;
      }
    }

    if (AnalyticsState.charts.trendLine) {
      AnalyticsState.charts.trendLine.destroy();
    }
    AnalyticsState.lastTrendMetric = AnalyticsState.selectedMetric;

    // Get metric-specific color (use representative value for color mapping)
    let representativeValue = 50; // Default moderate value
    if (smoothedData && smoothedData.length > 0) {
      const firstPoint = smoothedData[0];
      if (firstPoint && typeof firstPoint.value === 'number') {
        representativeValue = firstPoint.value;
      }
    }
    const lineColor = Utils.getColorByMetric(AnalyticsState.selectedMetric, representativeValue);

    AnalyticsState.charts.trendLine = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: Utils.getMetricLabel(AnalyticsState.selectedMetric),
            data: dataPoints,
            borderColor: lineColor,
            backgroundColor: Utils.hexToRgba(lineColor, 0.1),
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 2,
            pointBackgroundColor: lineColor,
            pointBorderColor: '#fff',
            pointBorderWidth: 1,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { usePointStyle: true, boxWidth: 6 } },
          tooltip: { backgroundColor: 'rgba(0,0,0,0.8)', borderColor: '#64748b', borderWidth: 1 }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: Utils.getMetricLabel(AnalyticsState.selectedMetric) },
            grid: { color: 'rgba(0,0,0,0.05)' }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });

    console.log('[Analytics] Trend chart initialized with', dataPoints.length, 'points (optimized)');
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

    // Create clean timestamp labels with proper time progression
    const labels = smoothedData.map((d, idx) => {
      if (d.timestamp) {
        const date = new Date(d.timestamp);
        if (!isNaN(date.getTime())) {
          return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        }
      }
      return d.label || `${idx}h`;
    });
    
    // Extract multi-metric data from smoothed data
    const aqiPoints = smoothedData.map(d => (typeof d.aqi === 'number' ? d.aqi : d.value) || null);
    const pm25Points = smoothedData.map(d => typeof d.pm2_5 === 'number' ? d.pm2_5 : null);
    const pm10Points = smoothedData.map(d => typeof d.pm10 === 'number' ? d.pm10 : null);
    const tempPoints = smoothedData.map(d => typeof d.temperature === 'number' ? d.temperature : null);

    // Calculate dynamic scale ranges based on actual data
    const calculateScaleRange = (points, defaultMin = 0, defaultMax = 200, padding = 0.1) => {
      const validPoints = points.filter(p => p !== null && typeof p === 'number');
      if (validPoints.length === 0) return { min: defaultMin, max: defaultMax };
      
      const min = Math.min(...validPoints);
      const max = Math.max(...validPoints);
      const range = max - min;
      const paddingAmount = Math.max(range * padding, 1); // Ensure minimum padding
      
      return {
        min: Math.max(0, Math.floor(min - paddingAmount)),
        max: Math.ceil(max + paddingAmount)
      };
    };

    // Calculate scales for each axis
    const aqiScale = calculateScaleRange(aqiPoints, 0, 200, 0.1);
    const pm25Scale = calculateScaleRange(pm25Points, 0, 200, 0.1);
    const tempScale = calculateScaleRange(tempPoints, -20, 50, 0.15);

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
            min: aqiScale.min, 
            max: aqiScale.max
          },
          y1: {
            type: 'linear',
            position: 'right',
            display: false,
            min: pm25Scale.min,
            max: pm25Scale.max
          },
          y2: {
            type: 'linear',
            position: 'right',
            display: false,
            min: tempScale.min,
            max: tempScale.max
          },
          x: { display: false }
        },
        plugins: { 
          legend: { display: false }, 
          tooltip: { 
            enabled: true,
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(0,0,0,0.9)',
            titleColor: '#fff',
            bodyColor: '#fff',
            borderColor: aqiColor,
            borderWidth: 1,
            padding: 8,
            titleFont: { size: 12, weight: 'bold' },
            bodyFont: { size: 11 },
            callbacks: {
              title: function(context) {
                if (!context || context.length === 0) return 'No Data';
                const idx = context[0].dataIndex;
                if (idx < 0 || idx >= smoothedData.length) return 'No Data';
                const point = smoothedData[idx];
                if (!point) return 'No Data';
                
                if (point.timestamp) {
                  const date = new Date(point.timestamp);
                  if (!isNaN(date.getTime())) {
                    return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                  }
                }
                return point.label ? String(point.label) : 'Data Point';
              },
              label: function(context) {
                const metric = context.dataset.label || 'Unknown';
                const value = Math.round(context.parsed.y * 10) / 10;
                let unit = '';
                if (metric === 'AQI') unit = '';
                else if (metric === 'PM2.5' || metric === 'PM10') unit = ' µg/m³';
                else if (metric === 'Temp') unit = ' °C';
                return `${metric}: ${value}${unit}`;
              }
            }
          } 
        },
        layout: { padding: { top: 10, bottom: 5 } }
      }
    });

    AnalyticsState.lastSparklineNodeId = nodeId;
    AnalyticsState.lastSparklineTimeframe = AnalyticsState.selectedTimeframe;

    console.log('[Analytics] Sparkline initialized for node:', nodeId, 'with', datasets.length, 'metrics,', smoothedData.length, 'points (downsampled & smoothed)');
  }
};

// ============================================================================
// DOM UPDATES
// ============================================================================

const DOM = {
  showErrorNotification(title, message, details = '') {
    AnalyticsState.lastError = { title, message, details, timestamp: new Date() };
    console.error(`[Analytics Error] ${title}: ${message}${details ? ' - ' + details : ''}`);
    
    // Create or get error notification element
    let errorNotif = document.getElementById('analyticsErrorNotification');
    if (!errorNotif) {
      errorNotif = document.createElement('div');
      errorNotif.id = 'analyticsErrorNotification';
      errorNotif.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #fee2e2;
        border: 1px solid #fca5a5;
        border-radius: 6px;
        padding: 12px 16px;
        max-width: 400px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        animation: slideIn 0.3s ease;
        font-family: system-ui, sans-serif;
      `;
      
      // Add CSS animation
      const style = document.createElement('style');
      style.textContent = `
        @keyframes slideIn {
          from { transform: translateX(420px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
          from { transform: translateX(0); opacity: 1; }
          to { transform: translateX(420px); opacity: 0; }
        }
        #analyticsErrorNotification.closing {
          animation: slideOut 0.3s ease forwards;
        }
      `;
      if (!document.querySelector('style[data-error-notif]')) {
        style.setAttribute('data-error-notif', 'true');
        document.head.appendChild(style);
      }
      document.body.appendChild(errorNotif);
    }
    
    // Build error content
    let content = `
      <div style="display: flex; gap: 8px;">
        <i class="fas fa-exclamation-circle" style="color: #991b1b; margin-top: 2px; flex-shrink: 0;"></i>
        <div style="flex-grow: 1;">
          <strong style="color: #991b1b; display: block; margin-bottom: 2px;">${title}</strong>
          <div style="font-size: 0.85rem; color: #7f1d1d; margin-bottom: ${details ? '4px' : '0'};">${message}</div>
          ${details ? `<div style="font-size: 0.75rem; color: #92400e; background: rgba(0,0,0,0.05); padding: 4px 6px; border-radius: 3px; font-family: monospace;">📍 ${details}</div>` : ''}
        </div>
        <button onclick="this.parentElement.parentElement.classList.add('closing'); setTimeout(() => this.parentElement.parentElement.remove(), 300);" style="background: none; border: none; color: #991b1b; cursor: pointer; font-size: 1.2rem; margin-top: -4px; padding: 0;">×</button>
      </div>
    `;
    
    errorNotif.innerHTML = content;
    errorNotif.classList.remove('closing');
    errorNotif.style.display = 'block';
    
    // Auto-dismiss after 8 seconds
    if (errorNotif.dismissTimer) clearTimeout(errorNotif.dismissTimer);
    errorNotif.dismissTimer = setTimeout(() => {
      if (errorNotif && errorNotif.parentElement) {
        errorNotif.classList.add('closing');
        setTimeout(() => {
          if (errorNotif && errorNotif.parentElement) {
            errorNotif.remove();
          }
        }, 300);
      }
    }, 8000);
  },

  clearErrorNotification() {
    const errorNotif = document.getElementById('analyticsErrorNotification');
    if (errorNotif) {
      errorNotif.classList.add('closing');
      setTimeout(() => {
        if (errorNotif && errorNotif.parentElement) {
          errorNotif.remove();
        }
      }, 300);
    }
  },

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

  updateAQIDonut() {
    const canvas = document.getElementById('aqiDonutChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let aqi = AnalyticsState.overviewData.aqi_current || 0;
    if (typeof aqi !== 'number' || isNaN(aqi)) {
      aqi = 0;
    }
    
    // Get composition percentages from overview data
    let pm25Pct = AnalyticsState.overviewData.composition?.pm25 || 55;
    let pm10Pct = AnalyticsState.overviewData.composition?.pm10 || 25;
    let otherPct = AnalyticsState.overviewData.composition?.other || 20;
    
    // Ensure valid percentages
    pm25Pct = (typeof pm25Pct === 'number' && !isNaN(pm25Pct)) ? pm25Pct : 55;
    pm10Pct = (typeof pm10Pct === 'number' && !isNaN(pm10Pct)) ? pm10Pct : 25;
    otherPct = (typeof otherPct === 'number' && !isNaN(otherPct)) ? otherPct : 20;
    
    // Normalize percentages to sum to 100
    const total = pm25Pct + pm10Pct + otherPct;
    if (total !== 100) {
      const factor = 100 / total;
      pm25Pct = Math.round(pm25Pct * factor);
      pm10Pct = Math.round(pm10Pct * factor);
      otherPct = Math.round(otherPct * factor);
      // Correct rounding errors
      const sum = pm25Pct + pm10Pct + otherPct;
      if (sum > 100) otherPct -= (sum - 100);
      else if (sum < 100) otherPct += (100 - sum);
    }

    // Update existing chart data instead of destroying/recreating
    if (AnalyticsState.charts.aqiDonut && AnalyticsState.charts.aqiDonut.data) {
      // UPDATED: Also update colors based on AQI level
      let pm25Color, pm10Color, otherColor;
      if (aqi <= 50) {
        pm25Color = '#10b981';
        pm10Color = '#6ee7b7';
        otherColor = '#a7f3d0';
      } else if (aqi <= 100) {
        pm25Color = '#f97316';
        pm10Color = '#fb923c';
        otherColor = '#fdba74';
      } else if (aqi <= 150) {
        pm25Color = '#ef4444';
        pm10Color = '#f87171';
        otherColor = '#fca5a5';
      } else if (aqi <= 200) {
        pm25Color = '#dc2626';
        pm10Color = '#991b1b';
        otherColor = '#7f1d1d';
      } else {
        pm25Color = '#7f1d1d';
        pm10Color = '#600101';
        otherColor = '#450101';
      }
      
      AnalyticsState.charts.aqiDonut.data.datasets[0].data = [pm25Pct, pm10Pct, otherPct];
      AnalyticsState.charts.aqiDonut.data.datasets[0].backgroundColor = [pm25Color, pm10Color, otherColor];
      AnalyticsState.charts.aqiDonut.update('none'); // Update without animation
      console.log('[Analytics] AQI Donut chart data updated (no recreate):', { aqi, pm25Pct, pm10Pct, otherPct, colors: { pm25Color, pm10Color, otherColor } });
      return;
    }

    // Fallback: recreate if chart not initialized
    if (AnalyticsState.charts.aqiDonut) {
      AnalyticsState.charts.aqiDonut.destroy();
    }

    // Use dynamic colors based on AQI quality level
    let pm25Color, pm10Color, otherColor;
    if (aqi <= 50) {
      pm25Color = '#10b981';
      pm10Color = '#6ee7b7';
      otherColor = '#a7f3d0';
    } else if (aqi <= 100) {
      pm25Color = '#f97316';
      pm10Color = '#fb923c';
      otherColor = '#fdba74';
    } else if (aqi <= 150) {
      pm25Color = '#ef4444';
      pm10Color = '#f87171';
      otherColor = '#fca5a5';
    } else if (aqi <= 200) {
      pm25Color = '#dc2626';
      pm10Color = '#991b1b';
      otherColor = '#7f1d1d';
    } else {
      pm25Color = '#7f1d1d';
      pm10Color = '#600101';
      otherColor = '#450101';
    }

    AnalyticsState.charts.aqiDonut = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['PM2.5', 'PM10', 'Other'],
        datasets: [{
          data: [pm25Pct, pm10Pct, otherPct],
          backgroundColor: [pm25Color, pm10Color, otherColor],
          borderWidth: 0,
          cutout: '80%'
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
          legend: { display: false }
        }
      }
    });

    console.log('[Analytics] AQI Donut initialized with composition:', { aqi, pm25Pct, pm10Pct, otherPct });
  },

  updatePollutantBars() {
    const data = AnalyticsState.overviewData;
    if (!data) return;

    const gasItems = [
      { id: 'pm25', label: 'PM2.5', value: data.pm2_5 || 0, unit: 'µg/m³', max: 100 },
      { id: 'pm10', label: 'PM10', value: data.pm10 || 0, unit: 'µg/m³', max: 150 },
      { id: 'gas_resistance', label: 'Gas Res', value: data.gas_resistance || 0, unit: 'kΩ', max: 200 },
      { id: 'temp', label: 'Temp', value: data.temperature || 0, unit: '°C', max: 50 }
    ];

    const gasList = document.querySelector('.gas-list');
    if (!gasList) return;

    gasItems.forEach(item => {
      const existingItem = gasList.querySelector(`[data-pollutant="${item.id}"]`);
      if (!existingItem) return;

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

  updateNodeTiles() {
    const nodeTilesContainer = document.querySelector('.node-tiles');
    if (!nodeTilesContainer || !AnalyticsState.allNodes) return;


    if (!Array.isArray(AnalyticsState.allNodes)) {
      console.warn('[Analytics] allNodes is not an array');
      return;
    }

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

    const currentHash = Utils.hashNodesList(deduplicatedNodes);
    if (!Utils.hasDataChanged(currentHash, AnalyticsState.lastNodesListHash)) {
      console.log('[Analytics] Node list unchanged, skipping re-render');
      return;
    }
    AnalyticsState.lastNodesListHash = currentHash;
    nodeTilesContainer.innerHTML = '';
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

  updateHeatmap() {
    const heatmapWrapper = document.getElementById('heatmapWrapper');
    if (!heatmapWrapper || !AnalyticsState.trendsData) return;

    // ⚡ OPTIMIZATION: Skip rebuild if data hasn't changed
    const currentDataLength = AnalyticsState.trendsData.length;
    const dataSignature = `${currentDataLength}-${AnalyticsState.selectedMetric}`;
    if (dataSignature === AnalyticsState.lastHeatmapHash && currentDataLength > 0) {
      console.log('[Analytics] Heatmap data unchanged, skipping rebuild');
      return;
    }
    AnalyticsState.lastHeatmapHash = dataSignature;

    // ⚡ OPTIMIZATION: Limit max datapoints to display in heatmap (max 8 days)
    const heatmapData = AnalyticsState.trendsData.slice(-8 * 24); // Max ~8 days of hourly data
    
    heatmapWrapper.innerHTML = ''; 
    const dayGroups = Utils.groupDataByDay(heatmapData);
    if (dayGroups.length === 0) return;

    dayGroups.slice(-8).forEach(day => { // Limit to 8 day columns
      const col = document.createElement('div');
      col.className = 'heatmap-col';

      const label = document.createElement('div');
      label.className = 'heatmap-lbl';
      label.innerText = day.label || 'N/A';
      col.appendChild(label);

      if (!Array.isArray(day.values)) return;

      // Limit cells per day to max 10 for performance
      const cellValues = day.values.slice(0, 10);
      cellValues.forEach(value => {
        if (typeof value !== 'number' || isNaN(value)) return;

        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';
        // Use dynamic color function based on selected metric
        cell.style.background = Utils.getColorByMetric(AnalyticsState.selectedMetric, value);
        cell.style.display = 'flex';
        cell.style.alignItems = 'center';
        cell.style.justifyContent = 'center';
        cell.style.position = 'relative';
        cell.style.fontSize = '0.55rem';
        cell.style.fontWeight = '700';
        cell.style.color = 'white';
        cell.innerHTML = `<span style="text-shadow: 0 1px 2px rgba(0,0,0,0.3);">${Math.round(value)}</span>`;
        cell.title = `${Utils.getMetricLabel(AnalyticsState.selectedMetric)}: ${Math.round(value)}`;
        cell.setAttribute('data-value', Math.round(value));

        col.appendChild(cell);
      });

      heatmapWrapper.appendChild(col);
    });

    console.log('[Analytics] Heatmap updated with', dayGroups.length, 'days (metric:', AnalyticsState.selectedMetric, ')');
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

  updateSystemHealth(healthData) {
    if (!healthData || typeof healthData !== 'object') {
      healthData = {};
    }

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


    let latency = (typeof healthData.latency === 'number') ? healthData.latency : 1.2;
    let anomalies = (typeof healthData.anomalies === 'number') ? healthData.anomalies : 0;
    
    latency = isNaN(latency) ? 1.2 : latency;
    anomalies = isNaN(anomalies) ? 0 : anomalies;

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
  previewNode(nodeId) {
    const regionEl = document.getElementById('dd-region');
    if (regionEl) regionEl.innerText = 'Previewing...';

    if (!AnalyticsState.nodeDetails[nodeId]) {
      API.getNodeDetail(nodeId).then(() => {
        DOM.updateDrilldown(nodeId);
      });
    } else {
      DOM.updateDrilldown(nodeId);
    }
  },

  clearPreview() {
    const regionEl = document.getElementById('dd-region');
    if (regionEl) regionEl.innerText = 'Focus Node';
    
    if (AnalyticsState.lockedNodeId) {
      DOM.updateDrilldown(AnalyticsState.lockedNodeId);
    }
  },

  lockNode(nodeId) {
    AnalyticsState.lockedNodeId = nodeId;
    AnalyticsState.selectedNode = nodeId;

    document.querySelectorAll('.node-tile').forEach(t => t.classList.remove('active'));
    const tile = document.getElementById(`tile-${nodeId}`);
    if (tile) tile.classList.add('active');

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

  toggleTrendView(view, element) {
    if (AnalyticsState.isTrendView === view) return; // Already active
    
    AnalyticsState.isTrendView = view;
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
    const lineWrapper = document.getElementById('lineChartWrapper');
    const heatmapWrapper = document.getElementById('heatmapWrapper');
    if (view === 'line') {
      if (lineWrapper) lineWrapper.style.display = 'block';
      if (heatmapWrapper) heatmapWrapper.style.display = 'none';
      if (AnalyticsState.charts.trendLine === null) {
        Charts.initTrendLine();
      }
    } else if (view === 'heatmap') {
      if (lineWrapper) lineWrapper.style.display = 'none';
      if (heatmapWrapper) heatmapWrapper.style.display = 'grid';
      DOM.updateHeatmap();
    }

    console.log('[Analytics] Trend view toggled to:', view);
  },
  updateTrendChart(metric, element) {
    AnalyticsState.selectedMetric = metric;
    const toggleGroups = document.querySelectorAll('.gas-toggles');
    const metricButtons = toggleGroups.length ? toggleGroups[toggleGroups.length - 1].querySelectorAll('.gas-btn') : [];
    metricButtons.forEach(btn => btn.classList.remove('active'));
    if (element) element.classList.add('active');
    
    API.getTrends().then(data => {
      if (data) {
        // Reset heatmap cache to force rebuild with new metric
        AnalyticsState.lastHeatmapHash = null;
        
        if (AnalyticsState.isTrendView === 'line') {
          Charts.initTrendLine();
        } else if (AnalyticsState.isTrendView === 'heatmap') {
          DOM.updateHeatmap();
        }
        DOM.updateKPIRow(); 
      }
    }).catch(err => {
      console.warn('[Analytics] Failed to update metric:', err);
    });

    console.log('[Analytics] Trend metric changed to:', metric);
  },

  setTimeframe(timeframe, element) {
    if (timeframe !== 'custom') {
      AnalyticsState.isCustomDate = false;
      const customGroup = document.getElementById('customDateGroup');
      if (customGroup) customGroup.style.display = 'none';
    }

    AnalyticsState.selectedTimeframe = timeframe;
    const pills = document.querySelectorAll('.range-pill');
    pills.forEach(pill => pill.classList.remove('active'));
    
    if (element) {
      element.classList.add('active');
    } else {
      pills.forEach(pill => {
        if (pill.textContent.includes(timeframe.toUpperCase())) {
          pill.classList.add('active');
        }
      });
    }
    
    // Reset sparkline/heatmap caches when timeframe changes
    AnalyticsState.lastSparklineTimeframe = null;
    AnalyticsState.lastHeatmapHash = null;
    
    debouncedReloadAnalyticsData();

    console.log('[Analytics] Timeframe changed to:', timeframe);
  },

  toggleCustomDate(isCustom, element) {
    AnalyticsState.isCustomDate = isCustom;
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
      const startInput = document.getElementById('customDateStart');
      const endInput = document.getElementById('customDateEnd');
      
      if (startInput && endInput) {
        AnalyticsState.customDateStart = startInput.value;
        AnalyticsState.customDateEnd = endInput.value;
        AnalyticsState.selectedTimeframe = 'custom';
        
        // Add change listeners for custom date inputs
        startInput.addEventListener('change', () => {
          AnalyticsState.customDateStart = startInput.value;
          if (Utils.isCustomDateRangeValid()) {
            debouncedReloadAnalyticsData();
          }
        });
        
        endInput.addEventListener('change', () => {
          AnalyticsState.customDateEnd = endInput.value;
          if (Utils.isCustomDateRangeValid()) {
            debouncedReloadAnalyticsData();
          }
        });
        
        if (Utils.isCustomDateRangeValid()) {
          debouncedReloadAnalyticsData();
        }
      }
    } else {
      // Remove change listeners when exiting custom mode
      const startInput = document.getElementById('customDateStart');
      const endInput = document.getElementById('customDateEnd');
      if (startInput) {
        startInput.removeEventListener('change', arguments.callee);
      }
      if (endInput) {
        endInput.removeEventListener('change', arguments.callee);
      }
    }

    console.log('[Analytics] Custom date mode:', isCustom);
  }
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================
const Utils = {

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

  getPM25Color(pm25) {
    // PM2.5 specific color mapping (µg/m³)
    if (typeof pm25 !== 'number' || isNaN(pm25)) return '#64748b';
    if (pm25 <= 12) return '#10b981';  // good - green
    if (pm25 <= 35.4) return '#f59e0b'; // moderate - amber
    if (pm25 <= 55.4) return '#f97316'; // unhealthy-sensitive - orange
    if (pm25 <= 150.4) return '#ef4444'; // unhealthy - red
    if (pm25 <= 250.4) return '#991b1b'; // very unhealthy - dark red
    return '#4b0000'; // hazardous - maroon
  },

  getPM10Color(pm10) {
    // PM10 specific color mapping (µg/m³)
    if (typeof pm10 !== 'number' || isNaN(pm10)) return '#64748b';
    if (pm10 <= 54) return '#10b981';  // good - green
    if (pm10 <= 154) return '#f59e0b'; // moderate - amber
    if (pm10 <= 254) return '#f97316'; // unhealthy-sensitive - orange
    if (pm10 <= 354) return '#ef4444'; // unhealthy - red
    if (pm10 <= 424) return '#991b1b'; // very unhealthy - dark red
    return '#4b0000'; // hazardous - maroon
  },

  getTempColor(temp) {
    // Temperature color mapping (°C) - represents comfort/stability
    if (typeof temp !== 'number' || isNaN(temp)) return '#64748b';
    if (temp >= 15 && temp <= 25) return '#10b981';  // optimal - green
    if (temp >= 10 && temp < 15 || temp > 25 && temp <= 30) return '#f59e0b'; // moderate - amber
    if (temp >= 5 && temp < 10 || temp > 30 && temp <= 35) return '#f97316'; // warm/cold - orange
    if (temp >= 0 && temp < 5 || temp > 35) return '#ef4444'; // extreme - red
    return '#4b0000'; // severe - maroon
  },

  getColorByMetric(metric, value) {
    // Dynamic color selection based on current metric
    switch(metric) {
      case 'aqi': return this.getAQIColor(value);
      case 'pm25': return this.getPM25Color(value);
      case 'pm10': return this.getPM10Color(value);
      case 'temp': return this.getTempColor(value);
      default: return this.getAQIColor(value);
    }
  },

  getAQILevel(aqi) {
    if (aqi <= 50) return 'Good';
    if (aqi <= 100) return 'Moderate';
    if (aqi <= 150) return 'Unhealthy (Sensitive)';
    if (aqi <= 200) return 'Unhealthy';
    if (aqi <= 300) return 'Very Unhealthy';
    return 'Hazardous';
  },

  getPollutantColor(pollutant, value) {
    // Define health thresholds for each pollutant
    switch(pollutant) {
      case 'pm25':
        // WHO guidelines: Good <12, Moderate 12-35, Unhealthy >35
        if (value <= 12) return '#10b981'; // Good - green
        if (value <= 35) return '#f97316'; // Moderate - orange
        if (value <= 55) return '#ef4444'; // Unhealthy for sensitive - red
        return '#7f1d1d'; // Hazardous - dark red
      case 'pm10':
        // WHO guidelines: Good <20, Moderate 20-50, Unhealthy >50
        if (value <= 20) return '#10b981'; // Good - green
        if (value <= 50) return '#f97316'; // Moderate - orange
        if (value <= 100) return '#ef4444'; // Unhealthy for sensitive - red
        return '#7f1d1d'; // Hazardous - dark red
      case 'gas_resistance':
        // Lower resistance = worse air quality (more volatile compounds)
        // Higher resistance = better air quality
        if (value >= 100) return '#10b981'; // Good - green
        if (value >= 50) return '#f97316'; // Moderate - orange
        if (value >= 20) return '#ef4444'; // Unhealthy for sensitive - red
        return '#7f1d1d'; // Hazardous - dark red
      case 'temp':
        // Temperature: optimal around 20-25°C
        if (value >= 18 && value <= 28) return '#10b981'; // Comfortable - green
        if ((value > 28 && value <= 35) || (value >= 15 && value < 18)) return '#f97316'; // Warm/Cool - orange
        return '#ef4444'; // Extreme - red
      default:
        return this.getAQIColor(value);
    }
  },

  getMetricLabel(metric) {
    const labels = {
      'aqi': 'AQI',
      'pm25': 'PM2.5',
      'pm10': 'PM10',
      'temp': 'Temperature'
    };
    return labels[metric] || metric;
  },

  hexToRgba(hex, alpha = 1) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  },

  downsampleData(data, timeframe) {
    if (!Array.isArray(data) || data.length === 0) return [];

    // ⚡ OPTIMIZATION: More aggressive downsampling limits for large datasets
    const maxPoints = timeframe === '24h' ? 60 :      // 1 point per ~24 minutes
                      timeframe === '7d' ? 80 :       // 1 point per ~2 hours
                      timeframe === '30d' ? 90 : 60;  // 1 point per ~8 hours

    if (data.length <= maxPoints) return data;

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

  smoothData(data, windowSize = 3) {
    if (!Array.isArray(data) || data.length < 2) return data;
    windowSize = Math.max(1, Math.min(windowSize, data.length));

    const smoothed = data.map((point, idx) => {
      // Guard: ensure value is numeric
      const centerValue = typeof point.value === 'number' ? point.value : 
                          (typeof point.aqi === 'number' ? point.aqi : 0);
      
      if (windowSize === 1) {
        return { ...point }; // No smoothing needed
      }
      const halfWindow = Math.floor(windowSize / 2);
      const start = Math.max(0, idx - halfWindow);
      const end = Math.min(data.length - 1, idx + halfWindow);
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

  hashNodesList(nodes) {
    if (!Array.isArray(nodes) || nodes.length === 0) return '';
    const ids = nodes
      .filter(n => n && n.id)
      .map(n => String(n.id))
      .sort((a, b) => parseInt(a) - parseInt(b))
      .join(',');
    return `${ids}_${AnalyticsState.selectedLocation || 'all'}`;
  },

  hasDataChanged(currentHash, lastHash) {
    return currentHash !== lastHash;
  },
  groupDataByDay(data) {
    if (!Array.isArray(data)) return [];
    
    const grouped = {};
    
    data.forEach(point => {
      if (!point) return; 
      let date = null;
      if (point.date) {
        date = point.date.split('T')[0]; // Handle ISO format
      } else if (point.timestamp) {
        date = new Date(point.timestamp).toISOString().split('T')[0];
      } else if (point.label) {
        // Try to parse label if it contains a date
        date = point.label.split(' ')[0];
      }
      
      if (!date) return; 
      
      if (!grouped[date]) {
        grouped[date] = { label: date, values: [] };
      }

      if (typeof point.value === 'number' && !isNaN(point.value)) {
        grouped[date].values.push(point.value);
      }
    });

    return Object.values(grouped)
      .sort((a, b) => new Date(a.label) - new Date(b.label))
      .slice(-8);
  },

  generateTimeSeriesRange(trendsData, timeframe) {
    if (trendsData.length === 0) return [];
    const sorted = [...trendsData].sort((a, b) => {
      const aDate = new Date(a.timestamp || a.date);
      const bDate = new Date(b.timestamp || b.date);
      return aDate - bDate;
    });

    const result = [];
    const startDate = new Date(sorted[0].timestamp || sorted[0].date);
    const endDate = new Date(sorted[sorted.length - 1].timestamp || sorted[sorted.length - 1].date);

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

    let currentDate = new Date(startDate);
    const dataMap = new Map();
 
    sorted.forEach(point => {
      const timestamp = new Date(point.timestamp || point.date);
      if (isNaN(timestamp)) return;
      const key = Math.floor(timestamp.getTime() / intervalMs);
      if (!dataMap.has(key) || !dataMap.get(key).value) {
        dataMap.set(key, point);
      }
    });

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

  filterSelect.value = currentValue;
  if (!nodeFilterListenerAttached) {
    filterSelect.addEventListener('change', (e) => {
      const value = e.target.value;
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
        AnalyticsState.selectedLocation = null; 
      } else if (value.startsWith('location_')) {
        AnalyticsState.selectedLocation = value.replace('location_', '');
        AnalyticsState.selectedNode = null; 
        console.log('[Analytics] Location filter selected:', AnalyticsState.selectedLocation);
      }
      debouncedReloadAnalyticsData();
    });
    nodeFilterListenerAttached = true;
  }

  console.log('[Analytics] Node filter populated');
}

async function reloadAnalyticsData() {
  console.log('[Analytics] Reloading data for current filters...');

  if (AnalyticsState.selectedTimeframe === 'custom' && !Utils.isCustomDateRangeValid()) {
    console.warn('[Analytics] Data reload skipped due to invalid custom date range');
    return;
  }

  // ⚡ OPTIMIZATION: Prevent concurrent reloads (single in-flight request at a time)
  if (AnalyticsState.isLoading) {
    console.log('[Analytics] Data reload already in progress, skipping duplicate request');
    return;
  }

  AnalyticsState.isLoading = true;

  try {
    // Load data in parallel (but backend caching prevents unnecessary work)
    await Promise.allSettled([
      API.getOverview(),
      API.getTrends()
    ]);

    // Update affected UI elements only
    DOM.updateAQIDisplay();
    DOM.updatePollutantBars();
    DOM.updateRiskDistribution();
    DOM.updateKPIRow();
    DOM.updateNodeTiles(); // UPDATED: Refresh node tiles on reload

    // ⚡ OPTIMIZATION: Only update trend charts if view is currently active and data changed
    // Skip unnecessary recreates when switching between views
    if (AnalyticsState.isTrendView === 'line') {
      // initTrendLine now checks if metric changed and updates data instead of recreate
      Charts.initTrendLine();
    } else if (AnalyticsState.isTrendView === 'heatmap') {
      // updateHeatmap now checks if data length changed before rebuilding
      DOM.updateHeatmap();
    }

    // ⚡ OPTIMIZATION: Only reinit sparkline if nodeId and timeframe have actually changed
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
      API.getSystemHealth()
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
// EXPORT FUNCTIONS - Analytics-based exports
// ============================================================================

/**
 * Build export parameters from current analytics state.
 * Maps JS timeframe keys to Django view's report_type values.
 */
function getExportParams() {
  let report_type = 'Weekly'; // default
  if (AnalyticsState.selectedTimeframe === '24h')       report_type = '24hrs';
  else if (AnalyticsState.selectedTimeframe === '7d')   report_type = 'Weekly';
  else if (AnalyticsState.selectedTimeframe === '30d')  report_type = 'Monthly';
  else if (AnalyticsState.isCustomDate)                 report_type = 'Custom';

  const params = new URLSearchParams();
  params.append('report_type', report_type);

  if (AnalyticsState.isCustomDate && AnalyticsState.customDateStart && AnalyticsState.customDateEnd) {
    params.append('date_from', AnalyticsState.customDateStart);
    params.append('date_to', AnalyticsState.customDateEnd);
  }

  if (AnalyticsState.selectedNode && AnalyticsState.selectedNode !== 'all') {
    params.append('node', AnalyticsState.selectedNode);
  }

  if (AnalyticsState.selectedLocation && AnalyticsState.selectedLocation !== 'all') {
    params.append('location', AnalyticsState.selectedLocation);
  }

  return params.toString();
}

/** Export as PDF — triggers Django export_report_pdf view */
window.exportAnalyticsAsPDF = function() {
  const params = getExportParams();
  window.location.href = `/export/pdf/?${params}`;
  console.log('[Analytics Export] PDF export initiated:', params);
};

/** Export as CSV — triggers Django export_report_csv view */
window.exportAnalyticsAsCSV = function() {
  const params = getExportParams();
  window.location.href = `/export/csv/?${params}`;
  console.log('[Analytics Export] CSV export initiated:', params);
};

/** Export as Excel — triggers Django export_report_excel view */
window.exportAnalyticsAsExcel = function() {
  const params = getExportParams();
  window.location.href = `/export/excel/?${params}`;
  console.log('[Analytics Export] Excel export initiated:', params);
};

/** Print report — opens print view in new tab */
window.printAnalyticsReport = function() {
  const params = getExportParams();
  window.open(`/export/print/?${params}`, '_blank');
  console.log('[Analytics Export] Print initiated:', params);
};

// ============================================================================
// EXPORT FOR TEMPLATE ACCESS
// ============================================================================
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

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialize);
} else {
  initialize();
}
