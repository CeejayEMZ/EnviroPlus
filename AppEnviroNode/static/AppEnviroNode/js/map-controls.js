
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
    
    // Selection tracking
    this.selectedNodeId = null;  // Track currently selected node
  }

  _createClusterIcon(cluster) {
    const childMarkers = cluster.getAllChildMarkers();
    let totalAqi = 0;
    let count = 0;
    
    childMarkers.forEach(marker => {
      const nodeData = this.nodeDataByNodeId.get(marker.nodeId);
      if (nodeData && nodeData.pollutants) {
        const aqi = nodeData.pollutants.aqi || 0;
        totalAqi += aqi;
        count++;
      }
    });
    
    const avgAqi = count > 0 ? totalAqi / count : 0;
    const clusterColor = this._getColorForValue(avgAqi);
    const clusterClass = this._getAqiClass(avgAqi);
    
    return L.divIcon({
      html: `
        <div class="cluster-icon ${clusterClass}">
          <div class="cluster-aqi">${Math.round(avgAqi)}</div>
          <div class="cluster-count">${count}</div>
        </div>
      `,
      iconSize: [50, 50],
      iconAnchor: [25, 25],
      popupAnchor: [0, -25],
      className: '',
    });
  }

  _getAqiClass(aqi) {
    if (aqi <= 50) return 'aqi-good';
    if (aqi <= 100) return 'aqi-moderate';
    if (aqi <= 150) return 'aqi-unhealthy-sensitive';
    if (aqi <= 200) return 'aqi-unhealthy';
    if (aqi <= 300) return 'aqi-very-unhealthy';
    return 'aqi-hazardous';
  }

  onAdd(map) {
    this.map = map;

    if (typeof L.markerClusterGroup !== 'undefined') {
      this.markerClusterGroup = L.markerClusterGroup({
        maxClusterRadius: 80,
        disableClusteringAtZoom: 18,
        iconCreateFunction: (cluster) => this._createClusterIcon(cluster)
      }).addTo(this.map);
    }

    this.container = L.DomUtil.create('div', 'unified-control-container');
    this._createButtonGroup();
    this._createFilterMenu();

    L.DomEvent.disableClickPropagation(this.container);
    L.DomEvent.disableScrollPropagation(this.container);

    const handleClickOutside = (e) => {
      if (this.filterMenuVisible && 
          this.filterMenu && 
          !this.filterMenu.contains(e.target) &&
          !this.container.contains(e.target)) {
        this._toggleFilterMenu();
      }
    };

    document.addEventListener('click', handleClickOutside);

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
    filterBtn.innerHTML = '⚲';
    L.DomEvent.on(filterBtn, 'click', () => this._toggleFilterMenu());
  }

  _createFilterMenu() {
    this.filterMenu = L.DomUtil.create('div', null, this.container);
    this.filterMenu.style.position = 'absolute';
    this.filterMenu.style.bottom = '10px';
    this.filterMenu.style.left = '50px';
    this.filterMenu.style.width = '240px';
    this.filterMenu.style.maxHeight = '280px';
    this.filterMenu.style.background = '#ffffff';
    this.filterMenu.style.border = '1px solid #dbe0e7';
    this.filterMenu.style.borderRadius = '8px';
    this.filterMenu.style.boxShadow = '0 2px 8px rgba(15, 23, 42, 0.12)';
    this.filterMenu.style.overflow = 'auto';
    this.filterMenu.style.overflowX = 'hidden';
    this.filterMenu.style.zIndex = '1000';
    this.filterMenu.style.display = 'none';
    this.filterMenu.style.flexDirection = 'column';
    
    const searchSection = L.DomUtil.create('div', null, this.filterMenu);
    searchSection.style.padding = '10px';
    searchSection.style.borderBottom = '1px solid rgba(102,115,137,0.18)';
    searchSection.style.flexShrink = 0;
    
    const searchTitle = L.DomUtil.create('div', null, searchSection);
    searchTitle.textContent = 'Search';
    searchTitle.style.fontSize = '0.85rem';
    searchTitle.style.fontWeight = '600';
    searchTitle.style.color = '#334155';
    searchTitle.style.marginBottom = '8px';
    
    const searchContainer = L.DomUtil.create('div', null, searchSection);
    searchContainer.style.position = 'relative';
    
    const searchInput = L.DomUtil.create('input', null, searchContainer);
    searchInput.type = 'text';
    searchInput.placeholder = 'Find node...';
    searchInput.style.width = '100%';
    searchInput.style.padding = '6px 8px';
    searchInput.style.border = '1px solid #dbe0e7';
    searchInput.style.borderRadius = '4px';
    searchInput.style.fontSize = '0.85rem';
    searchInput.style.fontFamily = 'inherit';
    searchInput.style.boxSizing = 'border-box';
    
    searchInput.addEventListener('focus', (e) => {
      searchInput.style.borderColor = '#667789';
      searchInput.style.boxShadow = '0 0 0 2px rgba(102, 119, 137, 0.1)';
    });
    searchInput.addEventListener('blur', (e) => {
      searchInput.style.borderColor = '#dbe0e7';
      searchInput.style.boxShadow = 'none';
    });
    
    L.DomEvent.on(searchInput, 'input', (e) => this._handleSearchInput(e.target.value, searchInput));
    L.DomEvent.disableClickPropagation(searchInput);
    this.searchInput = searchInput;
    
    this.searchResults = L.DomUtil.create('div', null, searchContainer);
    this.searchResults.style.position = 'absolute';
    this.searchResults.style.top = '100%';
    this.searchResults.style.left = '0';
    this.searchResults.style.right = '0';
    this.searchResults.style.marginTop = '6px';
    this.searchResults.style.background = '#fff';
    this.searchResults.style.border = '1px solid #dbe0e7';
    this.searchResults.style.borderRadius = '6px';
    this.searchResults.style.boxShadow = '0 4px 12px rgba(15,23,42,0.08)';
    this.searchResults.style.maxHeight = '220px';
    this.searchResults.style.overflowY = 'auto';
    this.searchResults.style.zIndex = '2000';
    this.searchResults.style.display = 'none';
    
    const tabsSection = L.DomUtil.create('div', null, this.filterMenu);
    tabsSection.style.display = 'flex';
    tabsSection.style.gap = '0';
    tabsSection.style.borderBottom = '1px solid rgba(102,115,137,0.18)';
    tabsSection.style.padding = '0';
    tabsSection.style.flexShrink = 0;
    
    const nodesTab = L.DomUtil.create('button', null, tabsSection);
    nodesTab.textContent = '📍 Nodes';
    nodesTab.style.flex = '1';
    nodesTab.style.padding = '10px';
    nodesTab.style.background = '#ffffff';
    nodesTab.style.border = 'none';
    nodesTab.style.borderBottom = '2px solid #0369a1';
    nodesTab.style.cursor = 'pointer';
    nodesTab.style.fontSize = '0.85rem';
    nodesTab.style.fontWeight = '600';
    nodesTab.style.color = '#0369a1';
    nodesTab.style.transition = 'all 0.15s ease';
    nodesTab.style.textAlign = 'center';
    
    const locationsTab = L.DomUtil.create('button', null, tabsSection);
    locationsTab.textContent = '🗺️ Locations';
    locationsTab.style.flex = '1';
    locationsTab.style.padding = '10px';
    locationsTab.style.background = '#ffffff';
    locationsTab.style.border = 'none';
    locationsTab.style.borderBottom = '2px solid transparent';
    locationsTab.style.cursor = 'pointer';
    locationsTab.style.fontSize = '0.85rem';
    locationsTab.style.fontWeight = '600';
    locationsTab.style.color = '#475569';
    locationsTab.style.transition = 'all 0.15s ease';
    locationsTab.style.textAlign = 'center';
    
    this.activeTab = 'nodes';
    
    const filterListSection = L.DomUtil.create('div', null, this.filterMenu);
    filterListSection.style.padding = '10px';
    filterListSection.style.flex = '1';
    filterListSection.style.overflowY = 'auto';
    filterListSection.style.minHeight = 0;
    
    this.nodesList = L.DomUtil.create('div', null, filterListSection);
    this.nodesList.style.display = 'block';
    
    this.locationsList = L.DomUtil.create('div', null, filterListSection);
    this.locationsList.style.display = 'none';
    
    const pollutantSection = L.DomUtil.create('div', null, this.filterMenu);
    pollutantSection.style.padding = '10px';
    pollutantSection.style.borderTop = '1px solid rgba(102,115,137,0.18)';
    pollutantSection.style.flexShrink = 0;
    
    const pollutantTitle = L.DomUtil.create('div', null, pollutantSection);
    pollutantTitle.textContent = 'Pollutant';
    pollutantTitle.style.fontSize = '0.85rem';
    pollutantTitle.style.fontWeight = '600';
    pollutantTitle.style.color = '#334155';
    pollutantTitle.style.marginBottom = '8px';

    const pollutantList = L.DomUtil.create('div', null, pollutantSection);
    pollutantList.style.display = 'flex';
    pollutantList.style.gap = '6px';
    pollutantList.style.flexWrap = 'wrap';
    
    this.pollutants.forEach(pollutant => {
      const item = L.DomUtil.create('button', null, pollutantList);
      item.style.padding = '6px 12px';
      item.style.borderRadius = '4px';
      item.style.border = '1px solid #dbe0e7';
      item.style.cursor = 'pointer';
      item.style.fontSize = '0.8rem';
      item.style.color = '#475569';
      item.style.background = '#ffffff';
      item.style.transition = 'all 0.15s ease';
      item.style.fontWeight = '500';
      if (pollutant === this.activePollutant) {
        item.style.background = '#0369a1';
        item.style.color = '#ffffff';
        item.style.border = '1px solid #0369a1';
      }
      item.textContent = this.displayLabels[pollutant];
      item.dataset.pollutant = pollutant;
      
      item.addEventListener('mouseenter', () => {
        if (pollutant !== this.activePollutant) {
          item.style.background = 'rgba(15, 23, 42, 0.04)';
        }
      });
      item.addEventListener('mouseleave', () => {
        if (pollutant !== this.activePollutant) {
          item.style.background = '#ffffff';
        }
      });
      
      L.DomEvent.on(item, 'click', () => this._selectPollutant(pollutant, pollutantList));
    });
    
    L.DomEvent.on(nodesTab, 'click', () => {
      this.activeTab = 'nodes';
      this.nodesList.style.display = 'block';
      this.locationsList.style.display = 'none';
      nodesTab.style.borderBottomColor = '#0369a1';
      nodesTab.style.color = '#0369a1';
      locationsTab.style.borderBottomColor = 'transparent';
      locationsTab.style.color = '#475569';
    });
    
    L.DomEvent.on(locationsTab, 'click', () => {
      this.activeTab = 'locations';
      this.nodesList.style.display = 'none';
      this.locationsList.style.display = 'block';
      nodesTab.style.borderBottomColor = 'transparent';
      nodesTab.style.color = '#475569';
      locationsTab.style.borderBottomColor = '#0369a1';
      locationsTab.style.color = '#0369a1';
    });
    
    this._renderFilterList();
    
    L.DomEvent.disableClickPropagation(this.filterMenu);
  }

  _handleSearchInput(query, searchInput) {
    const normalizeString = (value) => String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
    const searchTerm = normalizeString(query);
    
    if (!searchTerm) {
      this.searchResults.style.display = 'none';
      this.searchResults.innerHTML = '';
      this._renderFilterList();
      return;
    }
    
    if (!this.searchResults) return;
    this.searchResults.innerHTML = '';
    this.searchResults.style.display = 'block';
    
    const results = [];
    
    for (const [nodeId, nodeData] of this.nodeDataByNodeId.entries()) {
      const pollutants = nodeData.pollutants || {};
      const aqi = pollutants.aqi || 0;
      const nodeName = nodeData.node.name || `Node ${nodeId}`;
      const location = nodeData.node.location || 'Unknown';
      
      if (normalizeString(nodeName).includes(searchTerm) || 
          normalizeString(location).includes(searchTerm) || 
          String(aqi).includes(searchTerm)) {
        results.push({
          nodeId,
          name: nodeName,
          location,
          aqi
        });
      }
    }
    
    if (results.length === 0) {
      const noResults = L.DomUtil.create('div', null, this.searchResults);
      noResults.textContent = 'No nodes found';
      noResults.style.padding = '8px';
      noResults.style.opacity = '0.6';
      noResults.style.fontSize = '0.85rem';
      return;
    }
    
    results.forEach(result => {
      const item = L.DomUtil.create('div', null, this.searchResults);
      item.style.padding = '8px';
      item.style.borderRadius = '4px';
      item.style.cursor = 'pointer';
      item.style.borderBottom = '1px solid rgba(102,115,137,0.1)';
      item.style.fontSize = '0.85rem';
      item.style.transition = 'background 0.15s ease';
      
      const resultName = document.createElement('div');
      resultName.textContent = result.name;
      resultName.style.fontWeight = '600';
      resultName.style.color = '#0f172a';
      resultName.style.marginBottom = '2px';
      
      const resultMeta = document.createElement('div');
      resultMeta.textContent = `${result.location} • AQI: ${Math.round(result.aqi)}`;
      resultMeta.style.fontSize = '0.8rem';
      resultMeta.style.color = '#64748b';
      
      item.appendChild(resultName);
      item.appendChild(resultMeta);
      
      item.addEventListener('mouseenter', () => {
        item.style.background = 'rgba(15, 23, 42, 0.04)';
      });
      item.addEventListener('mouseleave', () => {
        item.style.background = 'transparent';
      });
      
      L.DomEvent.on(item, 'click', () => {
        this._autoNavigateToNode(result.nodeId);
        this.searchInput.value = '';
        this.searchResults.style.display = 'none';
        this.searchResults.innerHTML = '';
        this._renderFilterList();
      });
    });
  }

  _renderFilterList() {
    if (!this.nodesList || !this.locationsList) return;
    
    this.nodesList.innerHTML = '';
    this.locationsList.innerHTML = '';
    
    const allItem = L.DomUtil.create('div', null, this.nodesList);
    allItem.style.padding = '6px 8px';
    allItem.style.borderRadius = '4px';
    allItem.style.cursor = 'pointer';
    allItem.style.fontSize = '0.85rem';
    allItem.style.color = '#475569';
    allItem.style.transition = 'background 0.15s ease';
    allItem.style.marginBottom = '4px';
    if (this.activeNodeFilter === 'all') {
      allItem.style.background = '#dbeafe';
      allItem.style.color = '#0369a1';
      allItem.style.fontWeight = '600';
    }
    allItem.textContent = 'All Nodes';
    
    allItem.addEventListener('mouseenter', () => {
      if (this.activeNodeFilter !== 'all') {
        allItem.style.background = 'rgba(15, 23, 42, 0.04)';
      }
    });
    allItem.addEventListener('mouseleave', () => {
      if (this.activeNodeFilter !== 'all') {
        allItem.style.background = 'transparent';
      }
    });
    
    L.DomEvent.on(allItem, 'click', () => this._selectNodeFilter('all'));
    
    if (Object.keys(this.filterGroups.nodes).length > 0) {
      Object.entries(this.filterGroups.nodes).forEach(([nodeId, nodeData]) => {
        const nodeName = nodeData.name || `Node ${nodeId}`;
        const nodeItem = L.DomUtil.create('div', null, this.nodesList);
        nodeItem.style.padding = '6px 8px';
        nodeItem.style.borderRadius = '4px';
        nodeItem.style.cursor = 'pointer';
        nodeItem.style.fontSize = '0.85rem';
        nodeItem.style.color = '#475569';
        nodeItem.style.transition = 'background 0.15s ease';
        nodeItem.style.marginBottom = '4px';
        if (this.activeNodeFilter === nodeId) {
          nodeItem.style.background = '#dbeafe';
          nodeItem.style.color = '#0369a1';
          nodeItem.style.fontWeight = '600';
        }
        nodeItem.textContent = nodeName;
        
        nodeItem.addEventListener('mouseenter', () => {
          if (this.activeNodeFilter !== nodeId) {
            nodeItem.style.background = 'rgba(15, 23, 42, 0.04)';
          }
        });
        nodeItem.addEventListener('mouseleave', () => {
          if (this.activeNodeFilter !== nodeId) {
            nodeItem.style.background = 'transparent';
          }
        });
        
        L.DomEvent.on(nodeItem, 'click', () => this._selectNodeFilter(nodeId));
      });
    }
    
    if (Object.keys(this.filterGroups.locations).length > 0) {
      Object.entries(this.filterGroups.locations).forEach(([location, nodeIds]) => {
        const locItem = L.DomUtil.create('div', null, this.locationsList);
        locItem.style.padding = '6px 8px';
        locItem.style.borderRadius = '4px';
        locItem.style.cursor = 'pointer';
        locItem.style.fontSize = '0.85rem';
        locItem.style.color = '#475569';
        locItem.style.transition = 'background 0.15s ease';
        locItem.style.marginBottom = '4px';
        if (this.activeNodeFilter === location) {
          locItem.style.background = '#dbeafe';
          locItem.style.color = '#0369a1';
          locItem.style.fontWeight = '600';
        }
        locItem.textContent = location || 'Unknown';
        
        locItem.addEventListener('mouseenter', () => {
          if (this.activeNodeFilter !== location) {
            locItem.style.background = 'rgba(15, 23, 42, 0.04)';
          }
        });
        locItem.addEventListener('mouseleave', () => {
          if (this.activeNodeFilter !== location) {
            locItem.style.background = 'transparent';
          }
        });
        
        L.DomEvent.on(locItem, 'click', () => this._selectNodeFilter(location));
      });
    }
  }

  _toggleFilterMenu() {
    this.filterMenuVisible = !this.filterMenuVisible;
    if (this.filterMenuVisible) {
      this.filterMenu.style.display = 'block';
      if (this.searchInput) {
        setTimeout(() => this.searchInput.focus(), 50);
      }
    } else {
      this.filterMenu.style.display = 'none';
      if (this.searchInput) {
        this.searchInput.value = '';
        this._handleSearchInput('', this.searchInput);
      }
    }
  }

  _autoNavigateToNode(nodeId) {
    const marker = this.markersByNodeId.get(nodeId);
    if (marker && this.map) {
      this.map.setView([marker.getLatLng().lat, marker.getLatLng().lng], 15);
      marker.openPopup();
      window.dispatchEvent(new CustomEvent('markerSelected', { detail: { nodeId: nodeId } }));
      // Select node with visual feedback
      this.selectNode(nodeId);
      this.filterMenuVisible = true;
      this.filterMenu.style.display = 'none';
      this.filterMenuVisible = false;
      if (this.searchInput) {
        this.searchInput.value = '';
      }
    }
  }

  _selectPollutant(pollutant, pollutantList) {
    this.activePollutant = pollutant;
    
    const buttons = pollutantList.querySelectorAll('button');
    buttons.forEach(btn => {
      if (btn.dataset.pollutant === pollutant) {
        btn.style.background = '#0369a1';
        btn.style.color = '#ffffff';
        btn.style.border = '1px solid #0369a1';
      } else {
        btn.style.background = '#ffffff';
        btn.style.color = '#475569';
        btn.style.border = '1px solid #dbe0e7';
      }
    });

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
    
    if (!this.map) {
      console.error('❌ Map not initialized');
      return;
    }

    marker.nodeId = nodeId;
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
    
    // Update icon with selection state consideration
    const isSelected = this.selectedNodeId === nodeId;
    this._updateMarkerIcon(marker, nodeData, isSelected);
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
          
          let nearestNode = null;
          let minDistance = Infinity;
          
          for (const [nodeId, nodeData] of this.nodeDataByNodeId.entries()) {
            if (nodeData.node.latitude && nodeData.node.longitude) {
              const lat1 = latitude * Math.PI / 180;
              const lat2 = nodeData.node.latitude * Math.PI / 180;
              const lon1 = longitude * Math.PI / 180;
              const lon2 = nodeData.node.longitude * Math.PI / 180;
              const dlat = lat2 - lat1;
              const dlon = lon2 - lon1;
              const a = Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
              const c = 2 * Math.asin(Math.sqrt(a));
              const distance = 6371 * c;
              
              if (distance < minDistance) {
                minDistance = distance;
                nearestNode = nodeId;
              }
            }
          }
          
          if (nearestNode !== null) {
            const marker = this.markersByNodeId.get(nearestNode);
            if (marker) {
              marker.openPopup();
              window.dispatchEvent(new CustomEvent('markerSelected', { detail: { nodeId: nearestNode } }));
            }
          }
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

  // Selection management
  selectNode(nodeId) {
    // Deselect previously selected node
    if (this.selectedNodeId !== null && this.selectedNodeId !== nodeId) {
      const prevMarker = this.markersByNodeId.get(this.selectedNodeId);
      if (prevMarker) {
        const prevNodeData = this.nodeDataByNodeId.get(this.selectedNodeId);
        if (prevNodeData) {
          this._updateMarkerIcon(prevMarker, prevNodeData, false);
        }
      }
    }

    // Select new node
    this.selectedNodeId = nodeId;
    const marker = this.markersByNodeId.get(nodeId);
    if (marker) {
      const nodeData = this.nodeDataByNodeId.get(nodeId);
      if (nodeData) {
        this._updateMarkerIcon(marker, nodeData, true);
      }
    }
  }

  deselectNode() {
    if (this.selectedNodeId !== null) {
      const marker = this.markersByNodeId.get(this.selectedNodeId);
      if (marker) {
        const nodeData = this.nodeDataByNodeId.get(this.selectedNodeId);
        if (nodeData) {
          this._updateMarkerIcon(marker, nodeData, false);
        }
      }
      this.selectedNodeId = null;
    }
  }

  // Update marker icon with selection styling
  _updateMarkerIcon(marker, nodeData, isSelected) {
    const pollutants = nodeData.pollutants || {};
    const value = pollutants[this.activePollutant];
    const displayValue = value !== null && value !== undefined ? Math.round(value) : 'N/A';
    const isOffline = value === null || value === undefined;
    const newColor = this._getColorForValue(value ?? 0);

    // Create icon with selection state
    if (isSelected) {
      const newIcon = L.divIcon({
        html: `
          <div class="waqi-marker-selected" style="opacity: ${isOffline ? 0.5 : 1};">
            <div class="waqi-box-selected" style="background:${newColor}; box-shadow: 0 0 0 4px rgba(3, 105, 161, 0.3), 0 4px 12px rgba(3, 105, 161, 0.4);">
              ${displayValue}
            </div>
            <div class="waqi-pointer-selected" style="background:${newColor}"></div>
          </div>
        `,
        iconSize: null,
        className: '',
        popupAnchor: [0, -50],
      });
      marker.setIcon(newIcon);
    } else {
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