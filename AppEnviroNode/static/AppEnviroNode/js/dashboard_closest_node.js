// ============================================================
//  dashboard_closest_node.js
//  ADD this inside {% block extra_js %} in dashboard.html
//  OR save as a separate JS file and load it there.
//
//  What it does:
//  1. Asks user for geolocation
//  2. Calls /api/closest-node/ with their coordinates
//  3. Updates AQI circle + all metric cards with real data
//  4. Falls back to area average if location denied
// ============================================================

(function () {
  const CLOSEST_NODE_API = "{% url 'app:api_closest_node' %}";

  // ── AQI color map ────────────────────────────────────────
  const AQI_COLORS = {
    good:                '#2ecc71',
    moderate:            '#f1c40f',
    unhealthy_sensitive: '#e67e22',
    unhealthy:           '#e74c3c',
    very_unhealthy:      '#c0392b',
    hazardous:           '#8b0000',
  };

  const AQI_LABELS = {
    good:                'Good',
    moderate:            'Moderate',
    unhealthy_sensitive: 'Unhealthy for Sensitive Groups',
    unhealthy:           'Unhealthy',
    very_unhealthy:      'Very Unhealthy',
    hazardous:           'Hazardous',
  };

  const AQI_DESCRIPTIONS = {
    good:                'Air quality is satisfactory. Outdoor activities are safe for everyone.',
    moderate:            'Air quality is acceptable. Sensitive individuals should reduce prolonged outdoor exertion.',
    unhealthy_sensitive: 'Members of sensitive groups may experience health effects. General public is less likely to be affected.',
    unhealthy:           'The air has reached a high level of pollution. Reduce time spent outside if feeling symptoms.',
    very_unhealthy:      'Health alert! Everyone may experience more serious health effects. Avoid outdoor activities.',
    hazardous:           'Health warnings of emergency conditions. The entire population is more likely to be affected.',
  };

  // ── DOM helpers ──────────────────────────────────────────
  function setEl(id, value, fallback = '-') {
    const el = document.getElementById(id);
    if (el) el.textContent = value !== null && value !== undefined ? value : fallback;
  }

  function updateLocationBadge(source, nodeName, distanceKm) {
    const badge = document.getElementById('dashb-location-badge');
    if (!badge) return;
    if (source === 'closest_node') {
      badge.textContent = `📍 Nearest node: ${nodeName} (${distanceKm} km away)`;
      badge.style.display = 'inline-block';
    } else {
      badge.textContent = '📊 Showing average across all nodes';
      badge.style.display = 'inline-block';
    }
  }

  // ── Update AQI circle ────────────────────────────────────
  function updateAQICircle(aqi, aqiLevel) {
    const valEl   = document.getElementById('currentAqiVal');
    const levelEl = document.getElementById('currentAqiLevel');
    const ring    = document.getElementById('aqiProgressRing');
    const descEl  = document.querySelector('.aqi-description');

    if (valEl)   valEl.textContent   = aqi !== null ? aqi : '-';
    if (levelEl) {
      levelEl.textContent  = AQI_LABELS[aqiLevel] || aqiLevel || 'Unknown';
      levelEl.dataset.level = aqiLevel || '';
    }
    if (descEl)  descEl.textContent  = AQI_DESCRIPTIONS[aqiLevel] || '';

    // Update ring color
    if (ring && aqiLevel) {
      const color = AQI_COLORS[aqiLevel] || '#ccc';
      ring.style.stroke = color;
      // Animate stroke-dashoffset based on AQI (0-500 → full circle)
      const circumference = 2 * Math.PI * 65; // r=65
      const pct = Math.min((aqi || 0) / 500, 1);
      ring.style.strokeDasharray  = circumference;
      ring.style.strokeDashoffset = circumference * (1 - pct);
    }
  }

  // ── Update metric cards ──────────────────────────────────
  function updateMetricCards(data) {
    // PM2.5
    const pm25El = document.querySelector('[data-metric="pm25"] .metric-value');
    if (pm25El) pm25El.textContent = data.pm2_5 !== null ? parseFloat(data.pm2_5).toFixed(1) : '-';

    // PM10
    const pm10El = document.querySelector('[data-metric="pm10"] .metric-value');
    if (pm10El) pm10El.textContent = data.pm10 !== null ? parseFloat(data.pm10).toFixed(1) : '-';

    // PM1.0
    const pm1El = document.querySelector('[data-metric="pm1_0"] .metric-value');
    if (pm1El) pm1El.textContent = data.pm1_0 !== null ? parseFloat(data.pm1_0).toFixed(1) : '-';

    // Temperature
    const tempEl = document.querySelector('[data-metric="temperature"] .metric-value');
    if (tempEl) tempEl.textContent = data.temperature !== null ? parseFloat(data.temperature).toFixed(1) : '-';

    // Humidity
    const humEl = document.querySelector('[data-metric="humidity"] .metric-value');
    if (humEl) humEl.textContent = data.humidity !== null ? parseFloat(data.humidity).toFixed(0) : '-';

    // Humidity sub on temperature card
    const humSubEl = document.querySelector('[data-metric="temperature"] .metric-humidity-sub');
    if (humSubEl) humSubEl.textContent = data.humidity !== null ? `Humidity: ${parseFloat(data.humidity).toFixed(0)}%` : 'Humidity: -';

    // Pressure
    const presEl = document.querySelector('[data-metric="pressure"] .metric-value');
    if (presEl) presEl.textContent = data.pressure !== null ? parseFloat(data.pressure).toFixed(1) : '-';

    // VOCs (gas_resistance)
    const vocEl = document.querySelector('[data-metric="vocs"] .metric-value');
    if (vocEl) vocEl.textContent = data.gas_resistance !== null ? parseFloat(data.gas_resistance).toFixed(1) : '-';
  }

  // ── Main: fetch and update ───────────────────────────────
  async function fetchAndUpdate(lat, lng) {
    try {
      let url = CLOSEST_NODE_API;
      if (lat !== null && lng !== null) {
        url += `?lat=${lat}&lng=${lng}`;
      }

      const res  = await fetch(url);
      const json = await res.json();

      if (!json.success) return;

      const d = json.data;
      updateAQICircle(d.aqi, d.aqi_level);
      updateMetricCards(d);
      updateLocationBadge(d.source, d.node_name, d.distance_km);

    } catch (err) {
      console.warn('Closest node fetch failed:', err);
    }
  }

  // ── Init on DOM ready ────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          fetchAndUpdate(pos.coords.latitude, pos.coords.longitude);
        },
        function () {
          // Denied or error — use area average
          fetchAndUpdate(null, null);
        },
        { timeout: 8000 }
      );
    } else {
      // Browser doesn't support geolocation
      fetchAndUpdate(null, null);
    }
  });

})();
