/**
 * Real-time Dashboard - Dynamic Data Handler
 * Handles all dynamic behavior, data filtering, chart rendering, and API integration
 * All functionality centralized in this module as per requirements
 */

class RealtimeDashboard {
  constructor() {
    this.currentFilters = {
      range: window.djangoContext?.selectedRange || '24h',
      nodeId: window.djangoContext?.selectedNodeId || '',
      startDate: window.djangoContext?.startDate || '',
      endDate: window.djangoContext?.endDate || '',
    };

    this.chartInstances = {
      aqi: null,
      pm: null,
      temperature: null,
    };

    this.init();
  }

  /**
   * Initialize dashboard - attach event listeners and render initial data
   */
  init() {
    this.attachEventListeners();
    this.renderInitialData();
  }

  /**
   * Attach all event listeners
   */
  attachEventListeners() {
    // Time range buttons
    document.querySelectorAll('.rt-time-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => this.handleRangeChange(e));
    });

    // Node filter dropdown
    const nodeFilter = document.getElementById('nodeFilter');
    if (nodeFilter) {
      nodeFilter.addEventListener('change', (e) => this.handleNodeFilter(e));
    }

    // Custom date popup
    const customBtn = document.querySelector('[data-range="custom"]');
    if (customBtn) {
      customBtn.addEventListener('click', () => this.showDatePopup());
    }

    const cancelBtn = document.getElementById('cancelDate');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => this.hideDatePopup());
    }

    const applyBtn = document.getElementById('applyDate');
    if (applyBtn) {
      applyBtn.addEventListener('click', () => this.applyCustomDate());
    }

    // Close popup on background click
    const datePopup = document.getElementById('datePopup');
    if (datePopup) {
      datePopup.addEventListener('click', (e) => {
        if (e.target === datePopup) this.hideDatePopup();
      });
    }

    // Reload button
    const reloadBtn = document.getElementById('reloadButton');
    if (reloadBtn) {
      reloadBtn.addEventListener('click', () => this.fetchAndRefresh());
    }
  }

  /**
   * Handle time range button click
   */
  handleRangeChange(e) {
    const range = e.target.dataset.range;
    if (range === 'custom') {
      this.showDatePopup();
      return;
    }

    // Update button states
    document.querySelectorAll('.rt-time-btn').forEach((btn) => {
      btn.classList.remove('active');
    });
    e.target.classList.add('active');

    // Update filters
    this.currentFilters.range = range;
    this.currentFilters.startDate = '';
    this.currentFilters.endDate = '';

    // Fetch new data
    this.fetchAndRefresh();
  }

  /**
   * Handle node filter change
   */
  handleNodeFilter(e) {
    this.currentFilters.nodeId = e.target.value;
    this.fetchAndRefresh();
  }

  /**
   * Show custom date popup
   */
  showDatePopup() {
    const popup = document.getElementById('datePopup');
    if (popup) {
      popup.classList.add('visible');
      document.getElementById('dateFrom').focus();
    }
  }

  /**
   * Hide custom date popup
   */
  hideDatePopup() {
    const popup = document.getElementById('datePopup');
    if (popup) {
      popup.classList.remove('visible');
    }
  }

  /**
   * Apply custom date range
   */
  applyCustomDate() {
    const startDate = document.getElementById('dateFrom').value;
    const endDate = document.getElementById('dateTo').value;

    if (!startDate || !endDate) {
      alert('Please select both start and end dates');
      return;
    }

    if (new Date(startDate) > new Date(endDate)) {
      alert('Start date must be before end date');
      return;
    }

    // Update filters and buttons
    this.currentFilters.range = 'custom';
    this.currentFilters.startDate = startDate;
    this.currentFilters.endDate = endDate;

    document.querySelectorAll('.rt-time-btn').forEach((btn) => {
      btn.classList.remove('active');
      if (btn.dataset.range === 'custom') {
        btn.classList.add('active');
      }
    });

    this.hideDatePopup();
    this.fetchAndRefresh();
  }

  /**
   * Build query parameters for API call
   */
  buildQueryParams() {
    const params = new URLSearchParams();
    params.append('range', this.currentFilters.range);

    if (this.currentFilters.nodeId) {
      params.append('node', this.currentFilters.nodeId);
    }

    if (this.currentFilters.startDate) {
      params.append('start_date', this.currentFilters.startDate);
    }

    if (this.currentFilters.endDate) {
      params.append('end_date', this.currentFilters.endDate);
    }

    return params.toString();
  }

  /**
   * Fetch data from server and refresh all components
   */
  async fetchAndRefresh() {
    const queryParams = this.buildQueryParams();
    const url = `/realtime/?${queryParams}`;

    try {
      this.showLoadingState();

      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      // Parse HTML response
      const html = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');

      // Extract Django context from new HTML
      const scriptElements = doc.querySelectorAll('script');
      scriptElements.forEach((script) => {
        if (script.textContent.includes('window.djangoContext')) {
          eval(script.textContent);
        }
      });

      // Update summaries
      this.updateSummaries();

      // Update table
      this.updateTable();

      // Update charts
      this.updateCharts();

      this.hideLoadingState();
    } catch (error) {
      console.error('Error fetching data:', error);
      this.showError('Failed to load data. Please try again.');
      this.hideLoadingState();
    }
  }

  /**
   * Render initial data from Django context
   */
  renderInitialData() {
    this.updateSummaries();
    this.updateTable();
    this.initializeCharts();
  }

  /**
   * Update summary cards (AQI, readings count, active nodes)
   */
  updateSummaries() {
    const data = window.djangoContext;

    const avgAqiEl = document.getElementById('avgAqiValue');
    if (avgAqiEl) {
      avgAqiEl.textContent = data.avgAqi || '—';
    }

    const totalReadingsEl = document.getElementById('totalReadingsValue');
    if (totalReadingsEl) {
      totalReadingsEl.textContent = data.totalReadings || '0';
    }

    const activeNodesEl = document.getElementById('activeNodesValue');
    if (activeNodesEl) {
      activeNodesEl.textContent = data.activeNodes || '0';
    }

    const rangeNoteEl = document.getElementById('rangeNote');
    if (rangeNoteEl) {
      rangeNoteEl.textContent = data.rangeLabel;
    }
  }

  /**
   * Update readings table with latest data
   */
  updateTable() {
    const data = window.djangoContext.initialReadings || [];
    const tbody = document.getElementById('readingsTableBody');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (data.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="10" style="text-align: center; padding: 20px; color: #94a3b8;">
            No readings available for the selected range
          </td>
        </tr>
      `;
      return;
    }

    data.forEach((reading) => {
      const row = document.createElement('tr');

      const timestamp = new Date(reading.timestamp);
      const timeStr = timestamp.toLocaleString();
      const aqiLevel = this.getAQILevel(reading.aqi);

      row.innerHTML = `
        <td>${timeStr}</td>
        <td>${reading.node_name}</td>
        <td>${reading.location || 'Unknown'}</td>
        <td>
          <span class="aqi-cell">
            <span class="aqi-num">${reading.aqi || '—'}</span>
            <span class="aqi-level">${aqiLevel}</span>
          </span>
        </td>
        <td>${reading.pm2_5 !== null ? reading.pm2_5.toFixed(1) : '—'}</td>
        <td>${reading.pm10 !== null ? reading.pm10.toFixed(1) : '—'}</td>
        <td>${reading.temperature !== null ? reading.temperature.toFixed(1) : '—'}°C</td>
        <td>${reading.humidity !== null ? reading.humidity.toFixed(1) : '—'}%</td>
        <td>${reading.pressure !== null ? reading.pressure.toFixed(1) : '—'}</td>
        <td>${reading.gas_resistance !== null ? reading.gas_resistance.toFixed(1) : '—'}</td>
      `;

      tbody.appendChild(row);
    });
  }

  /**
   * Initialize Chart.js charts
   */
  initializeCharts() {
    this.destroyCharts();
    this.updateCharts();
  }

  /**
   * Update all charts with current data
   */
  updateCharts() {
    const data = window.djangoContext.initialChartData || [];

    if (data.length === 0) {
      console.warn('No chart data available');
      return;
    }

    // Prepare data
    const labels = data.map((item) => {
      const date = new Date(item.period);
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });

    const aqiData = data.map((item) => item.avg_aqi || 0);
    const pm25Data = data.map((item) => item.avg_pm2_5 || 0);
    const pm10Data = data.map((item) => item.avg_pm10 || 0);
    const tempData = data.map((item) => item.avg_temperature || 0);

    // AQI Trend Chart
    this.updateAQIChart(labels, aqiData);

    // PM Trend Chart
    this.updatePMChart(labels, pm25Data, pm10Data);

    // Temperature Trend Chart
    this.updateTemperatureChart(labels, tempData);
  }

  /**
   * Update AQI trend chart
   */
  updateAQIChart(labels, aqiData) {
    const ctx = document.getElementById('aqiTrendChart');
    if (!ctx) return;

    if (this.chartInstances.aqi) {
      this.chartInstances.aqi.destroy();
    }

    this.chartInstances.aqi = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Average AQI',
            data: aqiData,
            borderColor: '#2563eb',
            backgroundColor: 'rgba(37, 99, 235, 0.08)',
            borderWidth: 2.5,
            fill: true,
            tension: 0.4,
            pointRadius: 3.5,
            pointBackgroundColor: '#2563eb',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
            pointHoverRadius: 5,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(15, 23, 42, 0.9)',
            padding: 12,
            titleFont: { size: 12, weight: 600 },
            bodyFont: { size: 11 },
            cornerRadius: 8,
            displayColors: false,
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 500,
            grid: {
              color: 'rgba(203, 213, 225, 0.3)',
              drawBorder: false,
            },
            ticks: {
              font: { size: 11 },
              color: '#64748b',
            },
          },
          x: {
            grid: {
              display: false,
            },
            ticks: {
              font: { size: 10 },
              color: '#94a3b8',
            },
          },
        },
      },
    });
  }

  /**
   * Update PM trend chart
   */
  updatePMChart(labels, pm25Data, pm10Data) {
    const ctx = document.getElementById('pmTrendChart');
    if (!ctx) return;

    if (this.chartInstances.pm) {
      this.chartInstances.pm.destroy();
    }

    this.chartInstances.pm = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'PM2.5 (µg/m³)',
            data: pm25Data,
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.08)',
            borderWidth: 2.5,
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: '#f59e0b',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
          },
          {
            label: 'PM10 (µg/m³)',
            data: pm10Data,
            borderColor: '#ef4444',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            borderWidth: 2.5,
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: '#ef4444',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              usePointStyle: true,
              padding: 12,
              font: { size: 11, weight: 500 },
              color: '#64748b',
            },
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(15, 23, 42, 0.9)',
            padding: 12,
            titleFont: { size: 12, weight: 600 },
            bodyFont: { size: 11 },
            cornerRadius: 8,
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: 'rgba(203, 213, 225, 0.3)',
              drawBorder: false,
            },
            ticks: {
              font: { size: 11 },
              color: '#64748b',
            },
          },
          x: {
            grid: {
              display: false,
            },
            ticks: {
              font: { size: 10 },
              color: '#94a3b8',
            },
          },
        },
      },
    });
  }

  /**
   * Update temperature trend chart
   */
  updateTemperatureChart(labels, tempData) {
    const ctx = document.getElementById('temperatureTrendChart');
    if (!ctx) return;

    if (this.chartInstances.temperature) {
      this.chartInstances.temperature.destroy();
    }

    this.chartInstances.temperature = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Average Temperature (°C)',
            data: tempData,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.08)',
            borderWidth: 2.5,
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: '#10b981',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(15, 23, 42, 0.9)',
            padding: 12,
            titleFont: { size: 12, weight: 600 },
            bodyFont: { size: 11 },
            cornerRadius: 8,
            displayColors: false,
          },
        },
        scales: {
          y: {
            grid: {
              color: 'rgba(203, 213, 225, 0.3)',
              drawBorder: false,
            },
            ticks: {
              font: { size: 11 },
              color: '#64748b',
            },
          },
          x: {
            grid: {
              display: false,
            },
            ticks: {
              font: { size: 10 },
              color: '#94a3b8',
            },
          },
        },
      },
    });
  }

  /**
   * Destroy all chart instances
   */
  destroyCharts() {
    Object.values(this.chartInstances).forEach((chart) => {
      if (chart) chart.destroy();
    });
  }

  /**
   * Get AQI level label from AQI value
   */
  getAQILevel(aqi) {
    if (!aqi) return '—';
    if (aqi <= 50) return 'Good';
    if (aqi <= 100) return 'Moderate';
    if (aqi <= 150) return 'Unhealthy for sensitive';
    if (aqi <= 200) return 'Unhealthy';
    if (aqi <= 300) return 'Very unhealthy';
    return 'Hazardous';
  }

  /**
   * Show loading state
   */
  showLoadingState() {
    const spinner = document.getElementById('reloadSpinner');
    if (spinner) {
      spinner.style.display = 'inline-block';
    }
  }

  /**
   * Hide loading state
   */
  hideLoadingState() {
    const spinner = document.getElementById('reloadSpinner');
    if (spinner) {
      spinner.style.display = 'none';
    }
  }

  /**
   * Show error message
   */
  showError(message) {
    // Simple error display - can be enhanced with toast notifications
    console.error(message);
  }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.realtimeDashboard = new RealtimeDashboard();
});

// Handle visibility change for potential real-time updates
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && window.realtimeDashboard) {
    // Could refresh data when tab becomes visible
    // window.realtimeDashboard.fetchAndRefresh();
  }
});
