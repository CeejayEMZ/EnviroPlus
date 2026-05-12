// Dashboard AQI Trend Module
// Fetches hourly AQI averages from the backend and renders a 24-hour line chart.
// FIXED: Chart aspect ratio and stretching issues
// FIXED: In-place chart updates without destruction

(function() {
  let aqiTrendChart = null;
  let lastDataHash = null;
  let lastUpdateTime = null;
  const UPDATE_THROTTLE_MS = 30000; // Minimum 30s between updates
  let resizeObserver = null;

  function buildEndpoint() {
    return window.location.origin + '/api/analytics/aqi-trend/';
  }

  function formatEmptyCard(message) {
    const container = document.querySelector('.dashb-trend-chart-wrap');
    if (!container) return;
    container.innerHTML = `<div class="dashb-trend-empty">${message}</div>`;
  }

  function createGradient(ctx) {
    const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
    gradient.addColorStop(0, 'rgba(52, 199, 89, 0.25)');
    gradient.addColorStop(0.8, 'rgba(52, 199, 89, 0.08)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    return gradient;
  }

  // Compute hash to detect data changes
  function computeDataHash(data) {
    if (!data || !data.aqi) return null;
    const hashStr = JSON.stringify(data.aqi);
    let hash = 0;
    for (let i = 0; i < hashStr.length; i++) {
      const char = hashStr.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(36);
  }

  const trendAxisPlugin = {
    id: 'trendAxisPlugin',
    afterDraw(chart) {
      const {ctx, chartArea: {left, right, top, bottom}} = chart;
      ctx.save();
      ctx.strokeStyle = '#1f2937';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(left, top);
      ctx.lineTo(left, bottom);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(left, bottom);
      ctx.lineTo(right, bottom);
      ctx.stroke();
      ctx.restore();
    }
  };

  async function fetchAqiTrendData() {
    try {
      const response = await fetch(buildEndpoint(), {
        headers: {
          'Accept': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Dashboard AQI trend fetch failed:', error);
      formatEmptyCard('Unable to load AQI trend data.');
      return null;
    }
  }

  function renderAqiTrendChart(data) {
    const canvas = document.getElementById('dashboardChart');
    if (!canvas) {
      console.error('Dashboard AQI trend canvas not found');
      return;
    }

    if (!data || !Array.isArray(data.labels) || data.labels.length === 0) {
      formatEmptyCard('No AQI data available for the last 24 hours.');
      return;
    }

    // Get the canvas context
    const ctx = canvas.getContext('2d');
    const gradient = createGradient(ctx);
    
    // Get container for proper sizing
    const container = canvas.parentElement;
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;
    
    // Set canvas dimensions to match container for proper aspect ratio
    canvas.width = containerWidth;
    canvas.height = containerHeight;

    // Destroy existing chart instance if it exists
    if (aqiTrendChart) {
      aqiTrendChart.destroy();
      aqiTrendChart = null;
    }

    aqiTrendChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'AQI',
          data: data.aqi,
          backgroundColor: 'rgba(52, 199, 89, 0.9)',
          borderColor: '#22c55e',
          borderWidth: 0,
          borderRadius: 12,
          borderSkipped: false,
          maxBarThickness: 28,
          barPercentage: 0.7,
          categoryPercentage: 0.85,
        }]
      },
      plugins: [trendAxisPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2.2,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1c1f26',
            titleColor: '#ffffff',
            bodyColor: '#f4f5f7',
            borderColor: 'rgba(255,255,255,0.08)',
            borderWidth: 1,
            callbacks: {
              label: item => `AQI: ${item.parsed.y}`
            }
          }
        },
        scales: {
          x: {
            grid: {
              display: true,
              color: 'rgba(148, 163, 184, 0.16)',
              borderDash: [4, 4],
              drawBorder: false,
            },
            ticks: {
              color: '#475569',
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 5,
              padding: 10,
            }
          },
          y: {
            beginAtZero: true,
            min: 0,
            max: 300,
            grid: {
              display: true,
              color: 'rgba(148, 163, 184, 0.16)',
              borderDash: [4, 4],
            },
            ticks: {
              color: '#475569',
              stepSize: 50,
              padding: 12,
            },
            title: {
              display: false,
            }
          }
        },
        layout: {
          padding: {
            top: 10,
            bottom: 8,
            left: 4,
            right: 4
          }
        },
        animation: {
          duration: 500,
          easing: 'easeOutQuart'
        },
        // FIX: Ensure proper resize handling
        onResize: function(chart, size) {
          chart.resize(size);
        }
      }
    });
  }

  // In-place chart update without destroying/recreating
  function updateAqiTrendChart(data) {
    // If no chart instance, create new one
    if (!aqiTrendChart) {
      renderAqiTrendChart(data);
      lastDataHash = computeDataHash(data);
      lastUpdateTime = Date.now();
      return;
    }

    // Check if data actually changed
    const newHash = computeDataHash(data);
    if (newHash === lastDataHash) {
      console.log('📊 Chart data unchanged - skipping update');
      return;
    }

    // Check throttle
    const now = Date.now();
    if (lastUpdateTime && (now - lastUpdateTime) < UPDATE_THROTTLE_MS) {
      console.log(`📊 Chart update throttled (${UPDATE_THROTTLE_MS}ms minimum)`);
      return;
    }

    console.log('📊 Chart updated in-place (no destruction)');
    
    // Update chart data in-place
    aqiTrendChart.data.labels = data.labels;
    aqiTrendChart.data.datasets[0].data = data.aqi;
    
    // Update without animation for speed
    aqiTrendChart.update('none');
    
    lastDataHash = newHash;
    lastUpdateTime = now;
  }

  async function initializeAqiTrend() {
    const trendCard = document.querySelector('.dashb-trend-card');
    if (!trendCard) {
      return;
    }

    const data = await fetchAqiTrendData();
    if (data) {
      renderAqiTrendChart(data);
      lastDataHash = computeDataHash(data);
      lastUpdateTime = Date.now();
    }
  }

  // FIX: Add resize observer to handle container size changes
  function setupResizeObserver() {
    const container = document.querySelector('.dashb-trend-chart-wrap');
    if (!container) return;
    
    // Clean up existing observer
    if (resizeObserver) {
      resizeObserver.disconnect();
    }
    
    resizeObserver = new ResizeObserver(() => {
      if (aqiTrendChart) {
        // Use requestAnimationFrame to ensure smooth resize
        requestAnimationFrame(() => {
          if (aqiTrendChart) {
            aqiTrendChart.resize();
          }
        });
      }
    });
    
    resizeObserver.observe(container);
  }

  // FIX: Handle window resize events
  function handleWindowResize() {
    if (aqiTrendChart) {
      // Debounce resize to avoid excessive calls
      clearTimeout(window._resizeTimeout);
      window._resizeTimeout = setTimeout(() => {
        if (aqiTrendChart) {
          aqiTrendChart.resize();
        }
      }, 150);
    }
  }

  // FIX: Handle visibility change (tab switching)
  function handleVisibilityChange() {
    if (!document.hidden && aqiTrendChart) {
      // Force chart refresh when tab becomes visible
      setTimeout(() => {
        if (aqiTrendChart) {
          aqiTrendChart.update();
        }
      }, 100);
    }
  }

  // Export function for external updates
  window.updateAqiTrendChart = updateAqiTrendChart;

  // Initialize on DOM ready
  document.addEventListener('DOMContentLoaded', () => {
    initializeAqiTrend();
    setupResizeObserver();
    window.addEventListener('resize', handleWindowResize);
    document.addEventListener('visibilitychange', handleVisibilityChange);
  });
})();