// Dashboard AQI Trend Module
// Fetches hourly AQI averages from the backend and renders a 24-hour line chart.

(function() {
  let aqiTrendChart = null;

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
    const ctx = document.getElementById('dashboardChart');
    if (!ctx) {
      console.error('Dashboard AQI trend canvas not found');
      return;
    }

    if (!data || !Array.isArray(data.labels) || data.labels.length === 0) {
      formatEmptyCard('No AQI data available for the last 24 hours.');
      return;
    }

    if (aqiTrendChart) {
      aqiTrendChart.destroy();
    }

    const gradient = createGradient(ctx.getContext('2d'));

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
          maxBarThickness: 24,
          barPercentage: 0.7,
          categoryPercentage: 0.85,
        }]
      },
      plugins: [trendAxisPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
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
        }
      }
    });
  }

  async function initializeAqiTrend() {
    const trendCard = document.querySelector('.dashb-trend-card');
    if (!trendCard) {
      return;
    }

    const data = await fetchAqiTrendData();
    renderAqiTrendChart(data);
  }

  document.addEventListener('DOMContentLoaded', initializeAqiTrend);
})();
