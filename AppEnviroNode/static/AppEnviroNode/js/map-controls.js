
window.formatNumber = function(value, decimals = 2) {
  if (value === null || value === undefined) return 'N/A';
  const num = parseFloat(value);
  if (isNaN(num)) return 'N/A';
  return num.toFixed(decimals);
};

class UnifiedMapControl extends L.Control {
  constructor(options = {}) {
    super(options);
    this.map = null;
    this.markerClusterGroup = null;  // OPTIMIZATION: Marker clustering
    this.markerBounds = L.latLngBounds();  // OPTIMIZATION: Track bounds for auto-fit
    this.container = null;
    this.buttonGroup = null;
    this.filterMenu = null;
    this.filterMenuVisible = false;
    
    // Pollutant filter state
    this.markersByNodeId = new Map();  // OPTIMIZATION: Cache markers by node ID
    this.nodeDataByNodeId = new Map(); // OPTIMIZATION: Cache node data
    this.activePollutant = 'aqi';
    this.pollutants = ['pm25', 'pm10', 'pm1_0', 'aqi'];
    this.displayLabels = {
      pm25: 'PM2.5',
      pm10: 'PM10',
      pm1_0: 'PM1.0',
      aqi: 'AQI'
    };
    
    // Filter hierarchy state
    this.activeNodeFilter = 'all';  // 'all' | node_id | location_name
    this.filterGroups = {
      nodes: {},      // { node_id: node_data }
      locations: {}   // { location: [node_ids] }
    };
    
    // OPTIMIZATION: Debounce timer for filter changes
    this.filterDebounceTimer = null;
  }

  onAdd(map) {
    this.map = map;

    // OPTIMIZATION: Create marker cluster group for efficient rendering
    if (typeof L.markerClusterGroup !== 'undefined') {
      this.markerClusterGroup = L.markerClusterGroup({
        maxClusterRadius: 80,
        disableClusteringAtZoom: 18
      }).addTo(this.map);
    }

    this.container = L.DomUtil.create('div', 'unified-control-container');
    this._createButtonGroup();
    this._createFilterMenu();

    L.DomEvent.disableClickPropagation(this.container);
    L.DomEvent.disableScrollPropagation(this.container);

    return this.container;
  }

  _createButtonGroup() {
    this.buttonGroup = L.DomUtil.create('div', 'unified-button-group', this.container);
    
    const zoomInBtn = L.DomUtil.create('button', 'unified-btn', this.buttonGroup);
    zoomInBtn.innerHTML = '+';
    L.DomEvent.on(zoomInBtn, 'click', () => this.map.zoomIn());

    const zoomOutBtn = L.DomUtil.create('button', 'unified-btn', this.buttonGroup);
    zoomOutBtn.innerHTML = '−';
    L.DomEvent.on(zoomOutBtn, 'click', () => this.map.zoomOut());

    const fullscreenBtn = L.DomUtil.create('button', 'unified-btn', this.buttonGroup);
    fullscreenBtn.innerHTML = '⛶';
    L.DomEvent.on(fullscreenBtn, 'click', () => this._toggleFullscreen());

    const gpsBtn = L.DomUtil.create('button', 'unified-btn', this.buttonGroup);
    gpsBtn.innerHTML = '📍';
    L.DomEvent.on(gpsBtn, 'click', () => this._locateUser());

    const filterBtn = L.DomUtil.create('button', 'unified-btn', this.buttonGroup);
    filterBtn.innerHTML = '⋮';
    L.DomEvent.on(filterBtn, 'click', () => this._toggleFilterMenu());
  }

  _createFilterMenu() {
    this.filterMenu = L.DomUtil.create('div', 'unified-filter-menu unified-filter-hidden', this.container);
    
    // Pollutant section
    const pollutantTitle = L.DomUtil.create('div', 'unified-filter-title', this.filterMenu);
    pollutantTitle.textContent = 'Pollutant';

    const pollutantList = L.DomUtil.create('div', 'unified-filter-list', this.filterMenu);
    
    this.pollutants.forEach(pollutant => {
      const item = L.DomUtil.create('div', 'unified-filter-item', pollutantList);
      if (pollutant === this.activePollutant) item.classList.add('active');
      item.textContent = this.displayLabels[pollutant];
      item.dataset.pollutant = pollutant;
      
      L.DomEvent.on(item, 'click', () => this._selectPollutant(pollutant));
    });
    
    // Filter section (node/location)
    const filterTitle = L.DomUtil.create('div', 'unified-filter-title', this.filterMenu);
    filterTitle.textContent = 'Filter';
    filterTitle.style.marginTop = '10px';

    this.filterList = L.DomUtil.create('div', 'unified-filter-list', this.filterMenu);
    this._renderFilterList();
  }

  _renderFilterList() {
    if (!this.filterList) return;
    
    // Clear existing items
    this.filterList.innerHTML = '';
    
    // "All Nodes" option
    const allItem = L.DomUtil.create('div', 'unified-filter-item', this.filterList);
    if (this.activeNodeFilter === 'all') allItem.classList.add('active');
    allItem.textContent = 'All Nodes';
    L.DomEvent.on(allItem, 'click', () => this._selectNodeFilter('all'));
    
    // Nodes section
    if (Object.keys(this.filterGroups.nodes).length > 0) {
      const nodesHeader = L.DomUtil.create('div', 'unified-filter-item unified-filter-header', this.filterList);
      nodesHeader.textContent = '📍 Nodes';
      nodesHeader.style.pointerEvents = 'none';
      nodesHeader.style.fontSize = '0.85em';
      nodesHeader.style.opacity = '0.7';
      
      Object.entries(this.filterGroups.nodes).forEach(([nodeId, nodeData]) => {
        const nodeName = nodeData.name || `Node ${nodeId}`;
        const nodeItem = L.DomUtil.create('div', 'unified-filter-item unified-filter-subitem', this.filterList);
        if (this.activeNodeFilter === nodeId) nodeItem.classList.add('active');
        nodeItem.textContent = nodeName;
        nodeItem.style.paddingLeft = '20px';
        L.DomEvent.on(nodeItem, 'click', () => this._selectNodeFilter(nodeId));
      });
    }
    
    // Locations section
    if (Object.keys(this.filterGroups.locations).length > 0) {
      const locationsHeader = L.DomUtil.create('div', 'unified-filter-item unified-filter-header', this.filterList);
      locationsHeader.textContent = '🗺️ Locations';
      locationsHeader.style.pointerEvents = 'none';
      locationsHeader.style.fontSize = '0.85em';
      locationsHeader.style.opacity = '0.7';
      
      Object.entries(this.filterGroups.locations).forEach(([location, nodeIds]) => {
        const locItem = L.DomUtil.create('div', 'unified-filter-item unified-filter-subitem', this.filterList);
        if (this.activeNodeFilter === location) locItem.classList.add('active');
        locItem.textContent = location || 'Unknown';
        locItem.style.paddingLeft = '20px';
        L.DomEvent.on(locItem, 'click', () => this._selectNodeFilter(location));
      });
    }
  }

  _toggleFilterMenu() {
    this.filterMenuVisible = !this.filterMenuVisible;
    this.filterMenu.classList.toggle('unified-filter-hidden');
  }

  _selectPollutant(pollutant) {
    const items = this.filterMenu.querySelectorAll('.unified-filter-item:not(.unified-filter-header):not(.unified-filter-subitem)');
    items.forEach(item => item.classList.remove('active'));

    const selectedItem = this.filterMenu.querySelector(`[data-pollutant="${pollutant}"]`);
    if (selectedItem) selectedItem.classList.add('active');

    this.activePollutant = pollutant;
    this._applyFiltersDebounced();
  }

  _selectNodeFilter(filter) {
    this.activeNodeFilter = filter;
    this._renderFilterList();  // Update UI to show active filter
    this._applyFiltersDebounced();
  }

  // OPTIMIZATION: Debounce filter updates to prevent rapid re-renders
  _applyFiltersDebounced() {
    if (this.filterDebounceTimer) {
      clearTimeout(this.filterDebounceTimer);
    }
    this.filterDebounceTimer = setTimeout(() => {
      this._applyFilters();
      this.filterDebounceTimer = null;

    }, 50);  // 50ms debounce
  }

  // OPTIMIZATION: Register marker for caching and differential updates
  registerMarker(marker, nodeData) {
    const nodeId = nodeData.node.id;
    
    // FIX 7: Ensure cluster/map mismatch doesn't crash - add explicit safety guards
    if (!this.map) {
      console.error('❌ Map not initialized');
      return;
    }

    // Cache marker and node data
    this.markersByNodeId.set(nodeId, marker);
    this.nodeDataByNodeId.set(nodeId, nodeData);
    
    // Build filter groups for hierarchy
    if (nodeData.node.id && !this.filterGroups.nodes[nodeId]) {
      this.filterGroups.nodes[nodeId] = nodeData.node;
    }
    if (nodeData.node.location) {
      if (!this.filterGroups.locations[nodeData.node.location]) {
        this.filterGroups.locations[nodeData.node.location] = [];
      }
      if (!this.filterGroups.locations[nodeData.node.location].includes(nodeId)) {
        this.filterGroups.locations[nodeData.node.location].push(nodeId);
      }
    }
    
    // OPTIMIZATION: Add to cluster group if available, otherwise to map
    if (this.markerClusterGroup) {
      try {
        this.markerClusterGroup.addLayer(marker);
      } catch (err) {
        console.warn('⚠️ Failed to add to cluster:', err);
        marker.addTo(this.map);
      }
    } else {
      marker.addTo(this.map);
    }
    
    // OPTIMIZATION: Track bounds for auto-fit
    if (nodeData.node.latitude && nodeData.node.longitude) {
      this.markerBounds.extend([nodeData.node.latitude, nodeData.node.longitude]);
    }
    
    // Apply initial filters
    this._applyMarkerFilter(marker, nodeData);
  }

  // OPTIMIZATION: Only update marker if value or filter state changed
  _applyMarkerFilter(marker, nodeData) {
    const nodeId = nodeData.node.id;
    const pollutants = nodeData.pollutants || {};
    const value = pollutants[this.activePollutant];
    
    // Check if this node passes the active filter
    const passesFilter = this._nodePassesFilter(nodeId, nodeData);
    
    if (passesFilter) {
      // OPTIMIZATION: Add to cluster or map (idempotent)
      if (this.markerClusterGroup) {
        if (!this.markerClusterGroup.hasLayer(marker)) {
          this.markerClusterGroup.addLayer(marker);
          this.map.addLayer(this.markerClusterGroup);
        }
      } else {
        marker.addTo(this.map);
      }
    } else {
      // OPTIMIZATION: Remove from cluster or map (idempotent)
      if (this.markerClusterGroup) {
        this.markerClusterGroup.removeLayer(marker);
      } else {
        marker.removeFrom(this.map);
      }
      return;  // Don't update icon if not visible
    }
    
    // Update icon only if value changed (differential update)
    const currentColor = marker._icon ? marker._icon.style.background : null;
    const newColor = this._getColorForValue(value ?? 0);
    
    if (currentColor !== newColor || !marker._icon) {
      const displayValue = value !== null && value !== undefined ? Math.round(value) : 'N/A';
      const isOffline = value === null || value === undefined;
      
      const newIcon = L.divIcon({
        html: `
          <div class="waqi-marker" style="opacity: ${isOffline ? 0.5 : 1};">
            <div class="waqi-box" style="background:${newColor}">
              ${displayValue}
            </div>
            <div class="waqi-pointer" style="background:${newColor}"></div>
          </div>
        `,
        iconSize: null,
        className: '',
        popupAnchor: [0, -50],
      });
      
      marker.setIcon(newIcon);
    }
  }

  // Check if node passes current filters
  _nodePassesFilter(nodeId, nodeData) {
    if (this.activeNodeFilter === 'all') {
      return true;
    }
    
    // Check if filter is a node ID
    if (this.activeNodeFilter === String(nodeId)) {
      return true;
    }
    
    // Check if filter is a location
    if (this.activeNodeFilter === nodeData.node.location) {
      return true;
    }
    
    return false;
  }

  // OPTIMIZATION: Apply filters to all markers without recreation
  _applyFilters() {
    console.log(`[Filters] Pollutant: ${this.activePollutant}, NodeFilter: ${this.activeNodeFilter}`);
    
    // Update each cached marker
    for (const [nodeId, marker] of this.markersByNodeId.entries()) {
      const nodeData = this.nodeDataByNodeId.get(nodeId);
      if (nodeData) {
        this._applyMarkerFilter(marker, nodeData);
      }
    }
    
    this.map.fire('pollutant-changed', { pollutant: this.activePollutant });
  }

  _getColorForValue(value) {
    if (value <= 50) return '#2ecc71';
    if (value <= 100) return '#f1c40f';
    if (value <= 150) return '#e67e22';
    if (value <= 200) return '#e74c3c';
    if (value <= 300) return '#c0392b';
    return '#8b0000';
  }

  _locateUser() {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude } = position.coords;
          this.map.setView([latitude, longitude], 13);
          L.circleMarker([latitude, longitude]).addTo(this.map).bindPopup('Your Location');
        },
        (error) => alert('Geolocation error: ' + error.message)
      );
    }
  }

  _toggleFullscreen() {
    const mapElement = this.map._container;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      mapElement.requestFullscreen();
    }
  }

  getActivePollutant() {
    return this.activePollutant;
  }
  fitToVisibleMarkers() {
    try {
      if (this.markerClusterGroup && typeof this.markerClusterGroup.getBounds === 'function') {
        const bounds = this.markerClusterGroup.getBounds();
        if (bounds && bounds.isValid()) {
          this.map.fitBounds(bounds, {
            padding: [50, 50],
            maxZoom: 14
          });
          return;
        }
      }
      if (this.markerBounds.isValid()) {
        this.map.fitBounds(this.markerBounds, {
          padding: [50, 50],
          maxZoom: 14
        });
      }
    } catch (e) {
      console.warn('fitToVisibleMarkers error:', e);
    }
  }
}

// ============================================================================
// CONTROLLER
// ============================================================================
class EnviroMapController {
  constructor(mapId, lat = 14.5631, lng = 121.0192, zoom = 14) {
    this.mapId = mapId;
    this.initialLat = lat;
    this.initialLng = lng;
    this.initialZoom = zoom;
    this.map = null;
    this.unifiedControl = null;
  }

  initializeMap() {
    this.map = L.map(this.mapId, { zoomControl: false })
      .setView([this.initialLat, this.initialLng], this.initialZoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19
    }).addTo(this.map);

    this.unifiedControl = new UnifiedMapControl({ position: 'bottomleft' });
    this.unifiedControl.addTo(this.map);
    return this.map;
  }


  // OPTIMIZATION: Register marker for caching instead of storing in array
  addMarkerToControl(marker, markerData) {
    if (this.unifiedControl) {
      this.unifiedControl.registerMarker(marker, markerData);
    }
  }

  getFilterControl() {
    return this.unifiedControl;
  }

  getMap() {
    return this.map;
  }

  invalidateSize() {
    if (this.map) {
      setTimeout(() => this.map.invalidateSize(), 100);
    }
  }

  // OPTIMIZATION: Auto-fit map to visible markers
  fitToMarkers() {
    if (this.unifiedControl) {
      this.unifiedControl.fitToVisibleMarkers();
    }
  }
}

window.EnviroMapController = EnviroMapController;
window.UnifiedMapControl = UnifiedMapControl;