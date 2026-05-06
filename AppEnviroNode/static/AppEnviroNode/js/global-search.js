(function () {
  const apiNodesUrl = '/api/nodes/';
  const apiTopAreasUrl = '/api/analytics/top-areas/';
  const formId = 'locationSearchForm';
  const inputId = 'locationSearchInput';
  const modalId = 'globalSearchModal';
  const overlayId = 'globalSearchModalOverlay';
  const bannerId = 'globalSearchBanner';
  const locationStorageKey = 'enviroLocationContext';

  const normalize = (value) => String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
  const encodeParam = (value) => encodeURIComponent(String(value || '').trim());
  const isLocationQuery = (query) => /cleanest area|most polluted area|highest aqi|lowest aqi|barangay|street|city|location|monitoring node|node|area/.test(query);

  const createModal = () => {
    if (document.getElementById(modalId)) return;
    const overlay = document.createElement('div');
    overlay.id = overlayId;
    overlay.className = 'search-modal-overlay';
    overlay.innerHTML = `
      <div class="search-modal-card" role="dialog" aria-modal="true" aria-labelledby="globalSearchModalTitle">
        <div class="search-modal-header">
          <h2 id="globalSearchModalTitle">Search Results</h2>
          <button type="button" class="search-modal-close" aria-label="Close search message">×</button>
        </div>
        <div class="search-modal-body" id="${modalId}">No data found.</div>
      </div>
    `;
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) closeModal();
    });
    document.body.appendChild(overlay);
    overlay.querySelector('.search-modal-close')?.addEventListener('click', closeModal);
  };

  const openModal = (message) => {
    createModal();
    const overlay = document.getElementById(overlayId);
    const body = document.getElementById(modalId);
    if (body) body.textContent = message;
    overlay?.classList.add('active');
  };

  const closeModal = () => {
    document.getElementById(overlayId)?.classList.remove('active');
  };

  const showBanner = (message) => {
    let banner = document.getElementById(bannerId);
    if (!banner) {
      banner = document.createElement('div');
      banner.id = bannerId;
      banner.className = 'search-banner';
      banner.innerHTML = `
        <span class="search-banner-text"></span>
        <button type="button" class="search-banner-close" aria-label="Close search banner">×</button>
      `;
      document.body.insertBefore(banner, document.body.firstChild);
      banner.querySelector('.search-banner-close')?.addEventListener('click', () => {
        banner.remove();
      });
    }
    banner.querySelector('.search-banner-text').textContent = message;
    banner.classList.add('active');
  };

  const clearBanner = () => {
    const banner = document.getElementById(bannerId);
    if (banner) banner.remove();
  };

  const fetchJson = async (url) => {
    try {
      const response = await fetch(url, { credentials: 'same-origin' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      console.error('Search fetch failed:', url, error);
      return null;
    }
  };

  const getSearchQueryFromUrl = () => new URLSearchParams(window.location.search).get('search') || '';
  const getNodeParamFromUrl = () => new URLSearchParams(window.location.search).get('node') || '';
  const getLocationParamFromUrl = () => new URLSearchParams(window.location.search).get('location') || '';

  const storeLocationContext = (context) => {
    try {
      localStorage.setItem(locationStorageKey, JSON.stringify(context));
    } catch (error) {
      console.warn('Unable to store location context', error);
    }
  };

  const buildRedirectUrl = (path, context, query) => {
    const url = new URL(path, window.location.origin);
    if (query) url.searchParams.set('search', query);

    if (context?.nodeId != null) {
      url.searchParams.set('node', `node:${context.nodeId}`);
    } else if (context?.location) {
      if (path === '/realtime/') {
        url.searchParams.set('node', `location:${context.location}`);
      } else {
        url.searchParams.set('location', context.location);
      }
    }

    return url.toString();
  };

  const searchMatch = (text, query) => {
    if (!text || !query) return false;
    return normalize(text).includes(query);
  };

  const getBestNodeMatch = (query, nodes) => {
    const normalizedQuery = normalize(query);
    if (!normalizedQuery || !Array.isArray(nodes)) return null;

    const exactMatch = nodes.find((item) => {
      return normalize(item.name) === normalizedQuery || normalize(item.location) === normalizedQuery;
    });
    if (exactMatch) return { nodeId: exactMatch.id, location: exactMatch.location, nodeName: exactMatch.name };

    const partialMatch = nodes.find((item) => {
      return searchMatch(item.name, normalizedQuery) || searchMatch(item.location, normalizedQuery);
    });
    if (partialMatch) return { nodeId: partialMatch.id, location: partialMatch.location, nodeName: partialMatch.name };

    return null;
  };

  const getTopAreaMatch = (query, topAreas) => {
    if (!query || !topAreas?.success) return null;
    const normalizedQuery = normalize(query);
    const isCleanest = /cleanest|lowest aqi|best air/.test(normalizedQuery);
    const isPolluted = /most polluted|highest aqi|worst air/.test(normalizedQuery);
    const preferredList = isPolluted ? topAreas.top_polluted_areas : topAreas.cleanest_areas;
    if (Array.isArray(preferredList) && preferredList.length > 0) {
      const bestArea = preferredList[0];
      return {
        nodeId: bestArea.node_id,
        location: bestArea.location,
        nodeName: bestArea.name,
        aqi: bestArea.aqi,
        aqiLevel: bestArea.aqi_level,
        reason: isPolluted ? 'top_polluted' : 'top_cleanest'
      };
    }
    return null;
  };

  const resolveLocationContext = (query, nodesData, topAreasData) => {
    const normalizedQuery = normalize(query);
    if (!normalizedQuery) return null;

    const nodeMatch = getBestNodeMatch(normalizedQuery, nodesData);
    if (nodeMatch) {
      return {
        type: 'node',
        nodeId: nodeMatch.nodeId,
        location: nodeMatch.location,
        nodeName: nodeMatch.nodeName,
        query,
        reason: 'node_match'
      };
    }

    if (isLocationQuery(normalizedQuery) && topAreasData?.success) {
      const areaMatch = getTopAreaMatch(normalizedQuery, topAreasData);
      if (areaMatch) {
        return {
          type: 'top_area',
          nodeId: areaMatch.nodeId,
          location: areaMatch.location,
          nodeName: areaMatch.nodeName,
          query,
          reason: areaMatch.reason
        };
      }
    }

    if (isLocationQuery(normalizedQuery)) {
      return {
        type: 'location',
        location: query,
        query,
        reason: 'location_query'
      };
    }

    return null;
  };

  const determineTargetPage = (query, context) => {
    const normalizedQuery = normalize(query);
    const hasRealtime = /real-?time|live|current|aqi|reading|sensor|node/.test(normalizedQuery);
    const hasMap = /map|location|pin|marker|geo|site|area|barangay|street|city|monitoring/.test(normalizedQuery);
    const hasDashboard = /dashboard|rankings|polluted|cleanest|best air|worst air|area/.test(normalizedQuery);
    const hasHealth = /health|advice|safety|outdoor|sensitive|risk|advisory/.test(normalizedQuery);
    const hasAbout = /about|team|research|project|embo|mission|vision/.test(normalizedQuery);
    const hasHistory = /history|logs|events|records|past|archive/.test(normalizedQuery);

    if (hasRealtime) return '/realtime/';
    if (hasMap || context?.nodeId || context?.location) return '/map/';
    if (hasDashboard) return '/';
    if (hasHealth) return '/health/';
    if (hasAbout) return '/about/';
    if (hasHistory) return '/history/';
    return context?.nodeId || context?.location ? '/map/' : '/';
  };

  const normalizePath = (path) => {
    if (!path) return '/';
    const cleaned = path.replace(/\/+/g, '/').replace(/\/$/, '');
    return cleaned === '' ? '/' : cleaned;
  };

  const handleSearchRedirect = async (query) => {
    const normalizedQuery = normalize(query);
    if (!normalizedQuery) {
      openModal('Please enter a search keyword.');
      return false;
    }

    const [nodesData, topAreasData] = await Promise.all([
      fetchJson(apiNodesUrl),
      fetchJson(apiTopAreasUrl)
    ]);

    const nodes = Array.isArray(nodesData?.results) ? nodesData.results : [];
    const context = resolveLocationContext(normalizedQuery, nodes, topAreasData);
    const targetPage = determineTargetPage(normalizedQuery, context);
    const currentPath = normalizePath(window.location.pathname);

    storeLocationContext({ query, targetPage, context, timestamp: Date.now() });

    const destinationUrl = buildRedirectUrl(targetPage, context, query);
    if (currentPath === normalizePath(targetPage)) {
      window.location.href = destinationUrl;
      return false;
    }

    window.location.href = destinationUrl;
    return false;
  };

  window.submitLocationSearch = () => {
    const input = document.getElementById(inputId);
    const query = input?.value || '';
    return handleSearchRedirect(query);
  };

  window.showEnviroSearchBanner = showBanner;

  document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById(formId);
    if (form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        window.submitLocationSearch();
      });
    }
  });
})();
