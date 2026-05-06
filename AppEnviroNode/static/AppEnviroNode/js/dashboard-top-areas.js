// Dashboard barangay rankings module
// Uses backend-injected ranking data and renders the cleanest areas list.

(function() {
  const topPollutedAreas = window.DashboardRankings ? window.DashboardRankings.polluted || [] : [];
  const cleanestAreas = window.DashboardRankings ? window.DashboardRankings.cleanest || [] : [];
  let activeView = 'cleanest';

  function parseAqi(value) {
    return Number.isFinite(+value) ? +value : parseFloat(value) || 0;
  }

  function sortAreasByAqiAscending(items) {
    return (items || []).slice().sort((a, b) => parseAqi(a.aqi) - parseAqi(b.aqi));
  }

  const sortedCleanestAreas = sortAreasByAqiAscending(cleanestAreas);

  function createAreaItemMarkup(item, rank) {
    const locationText = item.location ? item.location : 'No location assigned';
    return `
      <li class="dashb-area-list-item cleanest">
        <div class="dashb-area-item-meta">
          <span class="dashb-area-item-rank">${rank}</span>
          <span class="dashb-area-item-name">${item.name}</span>
          <span class="dashb-area-item-subtitle">${locationText}</span>
        </div>
        <span class="dashb-area-score">${item.aqi}</span>
      </li>
    `;
  }

  function renderAreaList(items, emptyMessage) {
    const listElement = document.getElementById('barangayRankings');
    if (!listElement) {
      return;
    }

    if (!items || items.length === 0) {
      listElement.innerHTML = `<li class="dashb-area-empty">${emptyMessage}</li>`;
      return;
    }

    listElement.innerHTML = items
      .map((item, index) => createAreaItemMarkup(item, index + 1))
      .join('');
  }

  function initializeTopAreas() {
    const listElement = document.getElementById('barangayRankings');
    if (!listElement) {
      return;
    }

    renderAreaList(sortedCleanestAreas, 'No cleanest area rankings available.');
  }

  document.addEventListener('DOMContentLoaded', initializeTopAreas);
})();
