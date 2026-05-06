/**
 * WAQI-Style Map Controls for Leaflet
 * Unified, minimalist control panel at bottom-left
 */

// ============================================================================
// UNIFIED BOTTOM-LEFT CONTROL
// ============================================================================
class UnifiedMapControl extends L.Control {
  constructor(options = {}) {
    super(options);
    this.map = null;
    this.container = null;
    this.buttonGroup = null;
    this.filterMenu = null;
    this.filterMenuVisible = false;
    
    // Pollutant filter state
    this.allMarkers = [];
    this.visibleMarkers = new Set();
    this.activePollutant = 'aqi';
    this.pollutants = ['pm25', 'pm10', 'pm1_0', 'aqi'];
    this.displayLabels = {
      pm25: 'PM2.5',
      pm10: 'PM10',
      pm1_0: 'PM1.0',
      aqi: 'AQI'
    };
  }

  onAdd(map) {
    this.map = map;

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
    
    const title = L.DomUtil.create('div', 'unified-filter-title', this.filterMenu);
    title.textContent = 'Pollutant';

    const list = L.DomUtil.create('div', 'unified-filter-list', this.filterMenu);
    
    this.pollutants.forEach(pollutant => {
      const item = L.DomUtil.create('div', 'unified-filter-item', list);
      if (pollutant === this.activePollutant) item.classList.add('active');
      item.textContent = this.displayLabels[pollutant];
      item.dataset.pollutant = pollutant;
      
      L.DomEvent.on(item, 'click', () => this._selectPollutant(pollutant));
    });
  }

  _toggleFilterMenu() {
    this.filterMenuVisible = !this.filterMenuVisible;
    this.filterMenu.classList.toggle('unified-filter-hidden');
  }

  _selectPollutant(pollutant) {
    const items = this.filterMenu.querySelectorAll('.unified-filter-item');
    items.forEach(item => item.classList.remove('active'));

    const selectedItem = this.filterMenu.querySelector(`[data-pollutant="${pollutant}"]`);
    if (selectedItem) selectedItem.classList.add('active');

    this.activePollutant = pollutant;
    this._applyFilters();
  }

  // ✅ FIXED: Always add markers
  addMarker(marker, markerData) {
    marker.options.markerData = markerData;
    this.allMarkers.push(marker);

    marker.addTo(this.map);
    this.visibleMarkers.add(marker);
  }

  // ✅ FIXED: Full filter logic rewrite (safe + UI update)
  _applyFilters() {
    console.log("Filtering by:", this.activePollutant);

    this.allMarkers.forEach(marker => {
      const markerData = marker.options.markerData || {};
      const value = markerData[this.activePollutant];

      const color = this._getColorForValue(value ?? 0);
      const displayValue = value !== null && value !== undefined ? Math.round(value) : 'N/A';

      // 🔥 Update DIV ICON (critical fix)
      const newIcon = L.divIcon({
        html: `
          <div class="waqi-marker">
            <div class="waqi-box" style="background:${color}">
              ${displayValue}
            </div>
            <div class="waqi-pointer" style="background:${color}"></div>
          </div>
        `,
        iconSize: null,
        className: '',
        popupAnchor: [0, -50],
      });

      marker.setIcon(newIcon);

      // ✅ Fade instead of hiding
      if (value == null) {
        marker.setOpacity(0.3);
      } else {
        marker.setOpacity(1);
      }
    });

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

  addMarkerToControl(marker, markerData) {
    if (this.unifiedControl) {
      this.unifiedControl.addMarker(marker, markerData.pollutants);
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
}



window.EnviroMapController = EnviroMapController;
window.UnifiedMapControl = UnifiedMapControl;