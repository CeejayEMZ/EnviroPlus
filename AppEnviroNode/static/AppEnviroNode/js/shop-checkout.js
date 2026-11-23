
/* EnviroPlus checkout: totals, quantity, and optional deployment map.
   The backend remains the source of truth for order price and payment. */
(() => {
  'use strict';

  const form = document.getElementById('ep-checkout-form');
  if (!form) return;

  const quantity = document.getElementById('quantity');
  const minus = document.getElementById('ep-qty-minus');
  const plus = document.getElementById('ep-qty-plus');
  const quantityLabel = document.getElementById('ep-qty-label');
  const totalLabel = document.getElementById('ep-order-total');
  const payButton = document.getElementById('ep-submit');
  const currency = new Intl.NumberFormat('en-PH', {
    style: 'currency', currency: 'PHP', minimumFractionDigits: 2
  });

  if (quantity) {
    const price = Number(quantity.dataset.price);
    const stock = Number(quantity.max);

    function safeQuantity(value) {
      const number = Number(value);
      if (!Number.isSafeInteger(number)) return 1;
      return Math.max(1, Math.min(number, stock));
    }
    function updateQuantity(normalize = false) {
      const value = safeQuantity(quantity.value);
      if (normalize) quantity.value = String(value);
      quantityLabel.textContent = String(value);
      totalLabel.textContent = currency.format(price * value);
      minus.disabled = value <= 1;
      plus.disabled = value >= stock;
    }
    minus.addEventListener('click', () => {
      quantity.value = String(safeQuantity(Number(quantity.value) - 1));
      updateQuantity(true);
    });
    plus.addEventListener('click', () => {
      quantity.value = String(safeQuantity(Number(quantity.value) + 1));
      updateQuantity(true);
    });
    quantity.addEventListener('input', () => updateQuantity(false));
    quantity.addEventListener('change', () => updateQuantity(true));
    updateQuantity(true);

    form.addEventListener('submit', event => {
      quantity.value = String(safeQuantity(quantity.value));
      updateQuantity(true);
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
        return;
      }
      if (payButton) {
        payButton.disabled = true;
        payButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> Redirecting to payment…';
      }
    });
  }

  const mapContainer = document.getElementById('address-map');
  const mapStatus = document.getElementById('ep-map-status');
  const locationButton = document.getElementById('ep-locate-btn');
  const address = document.getElementById('shipping_address');
  const latitudeInput = document.getElementById('latitude');
  const longitudeInput = document.getElementById('longitude');

  function status(message, state = '') {
    if (!mapStatus) return;
    mapStatus.dataset.state = state;
    const text = mapStatus.querySelector('span');
    if (text) text.textContent = message;
  }

  if (!mapContainer || !address || !locationButton) return;
  if (!window.L) {
    status('The map could not load. Enter the full address manually.', 'warning');
    locationButton.disabled = true;
    return;
  }

  // A map preview is not a confirmed deployment location.
  const initial = [14.5322, 121.0493];
  const map = L.map(mapContainer, { scrollWheelZoom: false }).setView(initial, 13);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012'
  }).addTo(map);
  const marker = L.marker(initial, { draggable: true }).addTo(map);

  let lookupSequence = 0;
  let lookupController = null;
  let editSequence = 0;
  address.addEventListener('input', () => { editSequence += 1; });

  async function selectLocation(lat, lng) {
    latitudeInput.value = lat.toFixed(7);
    longitudeInput.value = lng.toFixed(7);
    marker.setLatLng([lat, lng]);
    status('Location selected. Looking up the address…');

    const currentLookup = ++lookupSequence;
    const editingAtStart = editSequence;
    if (lookupController) lookupController.abort();
    lookupController = new AbortController();
    const params = new URLSearchParams({
      format: 'jsonv2', lat: String(lat), lon: String(lng), zoom: '18', addressdetails: '1'
    });

    try {
      const response = await fetch(`https://nominatim.openstreetmap.org/reverse?${params}`, {
        headers: { 'Accept-Language': 'en' },
        signal: lookupController.signal
      });
      if (!response.ok) throw new Error('Address lookup unavailable');
      const data = await response.json();
      if (currentLookup !== lookupSequence) return;
      if (data.display_name) {
        if (editingAtStart === editSequence) {
          address.value = data.display_name;
          editSequence += 1;
          status('Address added from the map. Please review the details.', 'success');
        } else {
          status('Map location selected; your manually edited address was preserved.', 'success');
        }
      } else {
        status('Location selected. Please enter the complete address manually.', 'warning');
      }
    } catch (error) {
      if (error.name === 'AbortError' || currentLookup !== lookupSequence) return;
      status('Location selected, but the address service is unavailable. Enter the address manually.', 'warning');
    }
  }

  map.on('click', event => selectLocation(event.latlng.lat, event.latlng.lng));
  marker.on('dragend', () => {
    const position = marker.getLatLng();
    selectLocation(position.lat, position.lng);
  });

  locationButton.addEventListener('click', () => {
    if (!navigator.geolocation) {
      status('Location detection is unavailable in this browser. Select a point on the map.', 'warning');
      return;
    }
    locationButton.disabled = true;
    status('Requesting permission to find your location…');
    navigator.geolocation.getCurrentPosition(
      position => {
        locationButton.disabled = false;
        const { latitude, longitude } = position.coords;
        map.setView([latitude, longitude], 16);
        selectLocation(latitude, longitude);
      },
      () => {
        locationButton.disabled = false;
        status('Location access was denied or unavailable. Use the map or enter an address.', 'warning');
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  });

  window.addEventListener('load', () => map.invalidateSize());
})();
