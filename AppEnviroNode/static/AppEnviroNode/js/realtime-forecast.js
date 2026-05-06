(function() {
  const forecastContainer = document.getElementById('dailyForecastContainer');
  if (!forecastContainer) {
    return;
  }

  const apiUrl = forecastContainer.dataset.apiUrl;

  function formatValue(value, suffix = '') {
    return value !== null && value !== undefined && value !== '' ? `${value}${suffix}` : '—';
  }

  function getAqiCategory(aqi) {
    if (aqi === null || aqi === undefined) {
      return { label: 'No Data', className: 'no-data' };
    }
    if (aqi <= 50) {
      return { label: 'Good', className: 'good' };
    }
    if (aqi <= 100) {
      return { label: 'Moderate', className: 'moderate' };
    }
    if (aqi <= 150) {
      return { label: 'Unhealthy for Sensitive', className: 'unhealthy-sensitive' };
    }
    if (aqi <= 200) {
      return { label: 'Unhealthy', className: 'unhealthy' };
    }
    if (aqi <= 300) {
      return { label: 'Very Unhealthy', className: 'very-unhealthy' };
    }
    return { label: 'Hazardous', className: 'hazardous' };
  }

  function renderDayCard(day) {
    const category = getAqiCategory(day.summary.avg_aqi);
    const today = new Date().toLocaleDateString('en-US', { weekday: 'long' });
    const showNow = day.day_label === today;

    return `
      <article class="forecast-day-card">
        <div class="forecast-day-header">
          <div>
            <div class="forecast-day-label">${day.day_label}</div>
            <div class="forecast-day-meta">${day.day_subtitle}</div>
          </div>
          ${showNow ? '<div class="forecast-day-now">Now</div>' : ''}
        </div>
        <div class="forecast-day-body">
          <div class="forecast-middle">
            <div class="forecast-average-label">Average AQI</div>
            <div class="forecast-average-value">${formatValue(day.summary.avg_aqi)}</div>
            <div class="aqi-badge ${category.className}">${category.label}</div>
          </div>
          <div class="forecast-bottom">
            <div class="forecast-row">
              <span>Avg PM2.5</span>
              <strong>${formatValue(day.summary.avg_pm2_5, ' µg/m³')}</strong>
            </div>
            <div class="forecast-row">
              <span>Avg Temp</span>
              <strong>${formatValue(day.summary.avg_temperature, '°C')}</strong>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function showEmpty(message) {
    forecastContainer.innerHTML = `<div class="forecast-empty">${message}</div>`;
  }

  function renderForecast(forecast) {
    if (!Array.isArray(forecast) || forecast.length === 0) {
      showEmpty('No forecast data available.');
      return;
    }

    forecastContainer.innerHTML = forecast.map(renderDayCard).join('');
  }

  function loadForecast() {
    if (!apiUrl) {
      showEmpty('Forecast endpoint not available.');
      return;
    }

    showEmpty('Loading forecast data…');

    fetch(apiUrl)
      .then(response => response.ok ? response.json() : Promise.reject('Unable to fetch forecast'))
      .then(data => {
        if (!data || data.success !== true) {
          throw new Error(data?.message || 'Forecast data not found.');
        }
        renderForecast(data.forecast);
      })
      .catch(error => {
        console.error('Forecast load error:', error);
        showEmpty('Unable to load forecast at this time.');
      });
  }

  document.addEventListener('DOMContentLoaded', loadForecast);

  const reloadButton = document.getElementById('reloadButton');
  if (reloadButton) {
    reloadButton.addEventListener('click', loadForecast);
  }
})();