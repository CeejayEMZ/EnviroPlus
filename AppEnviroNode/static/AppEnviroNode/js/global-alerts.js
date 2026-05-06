/**
 * Global Alerts System
 * 
 * Modular, reusable alert system for EnviroNode dashboard.
 * Provides:
 * - Alert drawer toggle functionality
 * - AI modal management
 * - Severity-based bell icon updates
 * - Cross-page alert state management
 * 
 * Usage:
 * 1. Include in base template: <script src="{% static 'AppEnviroNode/js/global-alerts.js' %}"></script>
 * 2. Use functions: toggleAlertDrawer(), openAIModal(type), closeAIModal()
 * 3. Update bell icon: updateAlertBellSeverity(level)
 */

// ============================================================================
// ALERT DRAWER MANAGEMENT
// ============================================================================

/**
 * Toggle alert drawer open/close
 * Manages drawer visibility and overlay interaction
 */
function toggleAlertDrawer() {
  const drawer = document.getElementById('alertDrawer');
  const overlay = document.getElementById('drawerOverlay');
  
  if (!drawer || !overlay) {
    console.warn('[Alerts] Alert drawer elements not found in DOM');
    return;
  }
  
  drawer.classList.toggle('open');
  overlay.classList.toggle('open');

  const isOpen = drawer.classList.contains('open');
  const alertBell = document.getElementById('alertBell');
  if (alertBell) {
    alertBell.setAttribute('aria-expanded', String(isOpen));
  }

  if (isOpen) {
    loadAlertNotifications();
  }
}

const alertNotificationState = {
  loaded: false,
  notifications: [],
};

const notificationDropdownState = {
  loaded: false,
  notifications: [],
  filterType: 'all',
  readIds: new Set(),
  filterMenuOpen: false,
};

function getAlertEndpoint() {
  const alertBell = document.getElementById('alertBell');
  return alertBell?.dataset.alertEndpoint || '/dashboard/alerts/';
}

function getStoredNotificationFilter() {
  try {
    const stored = localStorage.getItem('enviroNodeNotificationFilter');
    return stored || 'all';
  } catch (error) {
    return 'all';
  }
}

function saveNotificationFilter(filterType) {
  notificationDropdownState.filterType = filterType;
  try {
    localStorage.setItem('enviroNodeNotificationFilter', filterType);
  } catch (error) {
    // ignore storage errors
  }
}

function loadNotificationReadIds() {
  try {
    const raw = localStorage.getItem('enviroNodeNotificationReadIds');
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch (error) {
    return new Set();
  }
}

function saveNotificationReadIds() {
  try {
    localStorage.setItem('enviroNodeNotificationReadIds', JSON.stringify([...notificationDropdownState.readIds]));
  } catch (error) {
    // ignore storage errors
  }
}

function setNotificationDropdownAria(isOpen) {
  const dropdown = document.getElementById('alertDropdown');
  const bell = document.getElementById('alertBell');
  if (dropdown) dropdown.setAttribute('aria-hidden', String(!isOpen));
  if (bell) bell.setAttribute('aria-expanded', String(isOpen));
}

function categorizeNotification(notification, sectionClass) {
  const title = (notification.title || '').toLowerCase();
  const description = (notification.description || '').toLowerCase();

  const adminKeywords = ['admin', 'user', 'permission', 'access', 'login', 'logout', 'approval', 'role'];
  if (adminKeywords.some(keyword => title.includes(keyword) || description.includes(keyword))) {
    return 'admin';
  }

  if (notification.node === 'System' || sectionClass === 'resolved' || sectionClass === 'pending' || notification.severity === 'info' || title.includes('system') || description.includes('system')) {
    return 'software';
  }

  return 'hardware';
}

function applyStoredReadState(notifications) {
  notifications.forEach(notification => {
    if (notificationDropdownState.readIds.has(notification.id)) {
      notification.unread = false;
    }
  });
}

function parseDropdownNotificationsHtml(html) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const items = [];
  const sections = doc.querySelectorAll('.alert-section');

  sections.forEach((section, sectionIndex) => {
    const sectionClass = section.className || '';
    section.querySelectorAll('.alert-item').forEach((alertNode, alertIndex) => {
      const titleEl = alertNode.querySelector('.alert-item-title');
      const descEl = alertNode.querySelector('.alert-item-desc');
      const timeEl = alertNode.querySelector('.alert-item-time');
      const nodeEl = alertNode.querySelector('.alert-item-reading');

      const title = titleEl?.textContent.trim() || 'Alert notification';
      const description = descEl?.textContent.trim() || '';
      let time = timeEl?.textContent.trim() || '';
      let node = nodeEl?.textContent.replace(/^Node:\s*/i, '').trim() || '';
      const footerText = alertNode.querySelector('.alert-item-footer')?.textContent.trim() || '';

      if (!time && footerText) {
        const resolvedMatch = footerText.match(/Resolved:\s*([^\n]+)/i);
        const agoMatch = footerText.match(/([\d]+\s+(minutes?|hours?|days?)\s+ago)/i);
        time = resolvedMatch ? resolvedMatch[1].trim() : (agoMatch ? agoMatch[1].trim() : footerText.slice(0, 35));
      }

      if (!node) {
        const nodeMatch = footerText.match(/Node:\s*([^\n]+)/i);
        node = nodeMatch ? nodeMatch[1].trim() : 'System';
      }

      if (!node) {
        node = 'System';
      }

      const severity = sectionClass.includes('critical') ? 'critical'
        : sectionClass.includes('warning') ? 'warning'
        : sectionClass.includes('pending') ? 'info'
        : sectionClass.includes('resolved') ? 'resolved'
        : 'info';

      const id = `notification-${severity}-${sectionIndex}-${alertIndex}`;
      const category = categorizeNotification({ title, description, node, severity }, sectionClass);
      const unread = severity !== 'resolved' && !notificationDropdownState.readIds.has(id);

      items.push({ id, title, description, time, node, severity, unread, category });
    });
  });

  return items;
}

function getNotificationDropdownContent() {
  return document.getElementById('alertDropdownContent');
}

function showNotificationDropdownLoading() {
  const content = getNotificationDropdownContent();
  if (content) {
    content.innerHTML = `<div class="alert-dropdown-empty">Loading notifications...</div>`;
  }
}

async function fetchNotifications(forceRefresh = false) {
  if (notificationDropdownState.loaded && !forceRefresh) {
    return notificationDropdownState.notifications;
  }

  showNotificationDropdownLoading();
  const endpoint = getAlertEndpoint();

  try {
    const response = await fetch(endpoint, {
      method: 'GET',
      headers: {
        'Accept': 'text/html',
      },
      credentials: 'same-origin',
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const html = await response.text();
    const parsedNotifications = parseDropdownNotificationsHtml(html);
    notificationDropdownState.notifications = parsedNotifications;
    notificationDropdownState.loaded = true;
    applyStoredReadState(parsedNotifications);
    return parsedNotifications;
  } catch (error) {
    console.warn('[Alerts] Notification fetch failed:', error);
    const fallbackNotifications = [
      {
        id: 'fallback-admin-1',
        title: 'Admin access required',
        description: 'A new user request is pending approval. Review user roles in the dashboard.',
        time: 'Just now',
        node: 'System',
        severity: 'info',
        unread: true,
        category: 'admin',
      },
      {
        id: 'fallback-hardware-1',
        title: 'Sensor node connectivity issue',
        description: 'Node 03 has dropped offline and requires maintenance.',
        time: '12 minutes ago',
        node: 'Node 03',
        severity: 'warning',
        unread: true,
        category: 'hardware',
      },
      {
        id: 'fallback-software-1',
        title: 'System update available',
        description: 'A platform patch is ready to install for improved dashboard stability.',
        time: '30 minutes ago',
        node: 'System',
        severity: 'info',
        unread: false,
        category: 'software',
      },
    ];
    notificationDropdownState.notifications = fallbackNotifications;
    notificationDropdownState.loaded = true;
    return fallbackNotifications;
  }
}

function buildNotificationItemHtml(notification) {
  return `
    <button type="button" class="notification-item ${notification.unread ? 'notification-unread' : 'notification-read'}" data-notification-id="${notification.id}">
      <div class="notification-title" style="font-size: 0.95rem; color: #0f172a; line-height: 1.3;">${notification.title}</div>
      <div style="font-size: 0.86rem; color: #475569; margin-top: 6px;">${notification.description}</div>
      <div class="notification-meta">
        <span>${notification.time}</span>
        <span class="notification-category">${notification.category === 'all' ? 'General' : notification.category.charAt(0).toUpperCase() + notification.category.slice(1)} Alerts</span>
      </div>
    </button>
  `;
}

function renderNotificationDropdown() {
  const content = getNotificationDropdownContent();
  if (!content) return;

  const notifications = notificationDropdownState.notifications;
  if (!notifications.length) {
    content.innerHTML = `<div class="alert-dropdown-empty">No notifications available</div>`;
    return;
  }

  const filtered = notifications.filter(notification => notificationDropdownState.filterType === 'all' || notification.category === notificationDropdownState.filterType);
  if (!filtered.length) {
    content.innerHTML = `<div class="alert-dropdown-empty">No notifications in this category</div>`;
    return;
  }

  content.innerHTML = filtered.map(buildNotificationItemHtml).join('');
  attachNotificationDropdownListeners();
}

function attachNotificationDropdownListeners() {
  const content = getNotificationDropdownContent();
  if (!content) return;

  const notificationButtons = content.querySelectorAll('.notification-item');
  notificationButtons.forEach(button => {
    button.removeEventListener('click', handleNotificationDropdownItemClick);
    button.addEventListener('click', handleNotificationDropdownItemClick);
  });

  const filterButtons = document.querySelectorAll('.alert-filter-option');
  filterButtons.forEach(button => {
    button.removeEventListener('click', handleNotificationFilterSelection);
    button.addEventListener('click', handleNotificationFilterSelection);
    button.classList.toggle('active', button.dataset.filter === notificationDropdownState.filterType);
  });

  const filterToggle = document.getElementById('notificationFilterToggle');
  if (filterToggle) {
    filterToggle.removeEventListener('click', toggleNotificationFilterMenu);
    filterToggle.addEventListener('click', toggleNotificationFilterMenu);
  }

  const refreshButton = document.getElementById('notificationRefreshButton');
  if (refreshButton) {
    refreshButton.removeEventListener('click', refreshNotificationDropdown);
    refreshButton.addEventListener('click', refreshNotificationDropdown);
  }
}

function handleNotificationDropdownItemClick(event) {
  const button = event.currentTarget;
  const notificationId = button?.dataset.notificationId;
  if (!notificationId) return;

  markNotificationDropdownRead(notificationId);
}

function handleNotificationFilterSelection(event) {
  const button = event.currentTarget;
  const filterType = button?.dataset.filter || 'all';
  applyFilter(filterType);
  toggleNotificationFilterMenu(false);
}

function markNotificationDropdownRead(notificationId) {
  const notification = notificationDropdownState.notifications.find(item => item.id === notificationId);
  if (!notification || !notification.unread) return;

  notification.unread = false;
  notificationDropdownState.readIds.add(notificationId);
  saveNotificationReadIds();
  renderNotificationDropdown();
}

function applyFilter(filterType, save = true) {
  if (!['all', 'admin', 'hardware', 'software'].includes(filterType)) {
    filterType = 'all';
  }

  if (save) {
    saveNotificationFilter(filterType);
  }

  notificationDropdownState.filterType = filterType;
  renderNotificationDropdown();
}

function toggleNotificationFilterMenu(forceState) {
  const menu = document.getElementById('notificationFilterMenu');
  const toggle = document.getElementById('notificationFilterToggle');
  if (!menu || !toggle) return;

  const isOpen = forceState !== undefined ? forceState : menu.hidden;
  menu.hidden = !isOpen;
  toggle.setAttribute('aria-expanded', String(isOpen));
  notificationDropdownState.filterMenuOpen = isOpen;
}

function closeNotificationFilterMenu() {
  toggleNotificationFilterMenu(false);
}

function refreshNotificationDropdown() {
  notificationDropdownState.loaded = false;
  fetchNotifications(true).then(() => applyFilter(notificationDropdownState.filterType, false));
}

async function openNotificationDropdown() {
  const dropdown = document.getElementById('alertDropdown');
  if (!dropdown) return;

  closeAlertDrawer();

  if (typeof window.positionAlertDropdown === 'function') {
    window.positionAlertDropdown();
  }

  notificationDropdownState.readIds = loadNotificationReadIds();
  notificationDropdownState.filterType = getStoredNotificationFilter();
  saveNotificationFilter(notificationDropdownState.filterType);
  dropdown.classList.add('open');
  setNotificationDropdownAria(true);

  if (!notificationDropdownState.loaded || notificationDropdownState.notifications.length === 0) {
    await fetchNotifications();
  }

  applyFilter(notificationDropdownState.filterType, false);
}

function closeNotificationDropdown() {
  const dropdown = document.getElementById('alertDropdown');
  if (!dropdown) return;

  dropdown.classList.remove('open');
  setNotificationDropdownAria(false);
  closeNotificationFilterMenu();
}

function toggleNotificationDropdown(event) {
  event = event || window.event;
  if (event && event.stopPropagation) {
    event.stopPropagation();
  }

  const dropdown = document.getElementById('alertDropdown');
  if (!dropdown) return;

  if (dropdown.classList.contains('open')) {
    closeNotificationDropdown();
  } else {
    openNotificationDropdown();
  }
}

function closeNotificationDropdownOnOutsideClick(event) {
  const dropdown = document.getElementById('alertDropdown');
  const bell = document.getElementById('alertBell');
  const filterMenu = document.getElementById('notificationFilterMenu');
  if (!dropdown || dropdown.classList.contains('open') === false) return;
  if (dropdown.contains(event.target) || (bell && bell.contains(event.target)) || (filterMenu && filterMenu.contains(event.target))) {
    return;
  }

  closeNotificationDropdown();
}

function getNotificationPanel() {
  return document.getElementById('alertDrawerContent');
}

function createSeverityBadge(severity) {
  const colors = {
    critical: { bg: '#fee2e2', color: '#991b1b' },
    warning: { bg: '#ffedd5', color: '#92400e' },
    info: { bg: '#dbeafe', color: '#1e40af' },
    resolved: { bg: '#d1fae5', color: '#166534' },
  };

  const badge = colors[severity] || colors.info;
  return `<span style="background:${badge.bg}; color:${badge.color}; font-size:0.72rem; font-weight:700; padding:4px 8px; border-radius:999px; white-space:nowrap;">${severity.toUpperCase()}</span>`;
}

function parseAlertNotificationsHtml(html) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const items = [];
  const sections = doc.querySelectorAll('.alert-section');

  sections.forEach((section, sectionIndex) => {
    const severity = section.classList.contains('critical') ? 'critical'
      : section.classList.contains('warning') ? 'warning'
      : section.classList.contains('pending') ? 'info'
      : section.classList.contains('resolved') ? 'resolved'
      : 'info';

    section.querySelectorAll('.alert-item').forEach((alertNode, alertIndex) => {
      const titleEl = alertNode.querySelector('.alert-item-title');
      const descEl = alertNode.querySelector('.alert-item-desc');
      const timeEl = alertNode.querySelector('.alert-item-time');
      const nodeEl = alertNode.querySelector('.alert-item-reading');

      const title = titleEl?.textContent.trim() || 'Alert notification';
      const description = descEl?.textContent.trim() || '';
      const time = timeEl?.textContent.trim() || '';
      const node = nodeEl?.textContent.replace(/^Node:\s*/i, '').trim() || 'System';

      items.push({
        id: `alert-${severity}-${sectionIndex}-${alertIndex}`,
        title,
        description,
        time,
        node,
        severity,
        unread: severity !== 'resolved',
      });
    });
  });

  return items;
}

function setAlertDrawerMessage(title, subtitle) {
  const content = getNotificationPanel();
  if (!content) return;
  content.innerHTML = `
    <div style="padding: 28px 20px; text-align: center; color: #475569;">
      <div style="font-weight: 700; font-size: 1rem; margin-bottom: 10px;">${title}</div>
      <div style="font-size: 0.92rem; color: #64748b;">${subtitle}</div>
    </div>
  `;
}

function attachNotificationListeners() {
  const content = getNotificationPanel();
  if (!content) return;

  const notificationButtons = content.querySelectorAll('.notification-item');
  notificationButtons.forEach(button => {
    button.removeEventListener('click', handleNotificationItemClick);
    button.addEventListener('click', handleNotificationItemClick);
  });

  const refreshBtn = document.getElementById('notificationRefreshButton');
  if (refreshBtn) {
    refreshBtn.removeEventListener('click', refreshAlertNotifications);
    refreshBtn.addEventListener('click', refreshAlertNotifications);
  }
}

function handleNotificationItemClick(event) {
  const button = event.currentTarget;
  const notificationId = button?.dataset.notificationId;
  if (!notificationId) return;
  markNotificationRead(notificationId);
  window.location.href = getAlertEndpoint();
}

function markNotificationRead(notificationId) {
  const notification = alertNotificationState.notifications.find(item => item.id === notificationId);
  if (!notification || notification.read) return;

  notification.unread = false;
  const button = document.querySelector(`[data-notification-id="${notificationId}"]`);
  if (button) {
    button.classList.remove('notification-unread');
    button.classList.add('notification-read');
    button.style.opacity = '0.8';
  }

  updateAlertBadgeFromNotifications(alertNotificationState.notifications);
}

function updateAlertBadgeFromNotifications(notifications) {
  const unreadCount = notifications.filter(item => item.unread).length;
  updateAlertCount(unreadCount);
}

function renderAlertNotifications(notifications, noticeText = '') {
  const content = getNotificationPanel();
  if (!content) return;

  if (!notifications.length) {
    setAlertDrawerMessage('No active alerts available.', 'Your notification center is up to date.');
    updateAlertCount(0);
    return;
  }

  const itemsHtml = notifications.map(notification => {
    const severityBadge = createSeverityBadge(notification.severity);
    return `
      <button type="button" class="notification-item ${notification.unread ? 'notification-unread' : 'notification-read'}" data-notification-id="${notification.id}" style="width:100%; padding:16px; text-align:left; border:none; background:${notification.unread ? '#f8fbff' : '#ffffff'}; cursor:pointer; display:block; margin:0; border-bottom:1px solid #e2e8f0; border-left:4px solid ${notification.unread ? '#38bdf8' : 'transparent'};">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
          <div style="flex:1; min-width:0;">
            <div style="font-size:0.96rem; font-weight:${notification.unread ? 700 : 600}; color:#0f172a; line-height:1.3;">${notification.title}</div>
            <div style="font-size:0.88rem; color:#475569; margin-top:6px;">${notification.description}</div>
          </div>
          <span style="font-size:0.78rem; color:#64748b; white-space:nowrap;">${notification.time}</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-top:12px;">
          <span style="font-size:0.82rem; color:#64748b;">${notification.node}</span>
          ${severityBadge}
        </div>
      </button>
    `;
  }).join('');

  content.innerHTML = `
    <div style="padding: 18px 18px 8px; display:flex; justify-content:space-between; align-items:center; gap:12px;">
      <div style="font-size:0.95rem; font-weight:700; color:#0f172a;">Notifications</div>
      <button type="button" id="notificationRefreshButton" style="border:none; background:none; color:#2563eb; font-size:0.9rem; cursor:pointer; padding:0;">Refresh</button>
    </div>
    ${noticeText ? `<div style="padding: 0 18px 10px; color:#475569; font-size:0.88rem;">${noticeText}</div>` : ''}
    <div class="notification-list" style="overflow-y:auto; max-height:calc(100vh - 260px); padding:0 0 18px 0;">${itemsHtml}</div>
  `;

  attachNotificationListeners();
  updateAlertBadgeFromNotifications(notifications);
}

function refreshAlertNotifications() {
  alertNotificationState.loaded = false;
  loadAlertNotifications(true);
}

async function loadAlertNotifications(forceRefresh = false) {
  if (alertNotificationState.loaded && !forceRefresh) {
    renderAlertNotifications(alertNotificationState.notifications);
    return;
  }

  const content = getNotificationPanel();
  if (!content) return;

  content.innerHTML = `
    <div style="padding: 26px 20px; text-align:center; color:#64748b;">
      Loading notifications...
    </div>
  `;

  const endpoint = getAlertEndpoint();

  try {
    const response = await fetch(endpoint, {
      method: 'GET',
      headers: {
        'Accept': 'text/html',
      },
      credentials: 'same-origin',
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const html = await response.text();
    const parsedNotifications = parseAlertNotificationsHtml(html);

    alertNotificationState.notifications = parsedNotifications;
    alertNotificationState.loaded = true;
    renderAlertNotifications(parsedNotifications);
    return;
  } catch (error) {
    console.warn('[Alerts] Notification fetch failed:', error);

    const fallbackNotifications = [
      {
        id: 'fallback-1',
        title: 'New alert from EnviroNode',
        description: 'A sensor reading requires your attention. Open the alert center to review details.',
        time: 'Just now',
        node: 'System',
        severity: 'info',
        unread: true,
      },
      {
        id: 'fallback-2',
        title: 'Sensor node offline',
        description: 'Node 03 has not reported status for 22 minutes.',
        time: '22 minutes ago',
        node: 'Node 03',
        severity: 'warning',
        unread: true,
      },
    ];

    alertNotificationState.notifications = fallbackNotifications;
    alertNotificationState.loaded = true;
    renderAlertNotifications(fallbackNotifications, 'Showing sample notifications until the alert endpoint becomes available.');
  }
}

/**
 * Close alert drawer (programmatically)
 */
function closeAlertDrawer() {
  const drawer = document.getElementById('alertDrawer');
  const overlay = document.getElementById('drawerOverlay');
  
  if (drawer && overlay) {
    drawer.classList.remove('open');
    overlay.classList.remove('open');
  }
}

/**
 * Open alert drawer (programmatically)
 */
function openAlertDrawer() {
  const drawer = document.getElementById('alertDrawer');
  const overlay = document.getElementById('drawerOverlay');
  
  if (drawer && overlay) {
    drawer.classList.add('open');
    overlay.classList.add('open');
  }
}

// ============================================================================
// AI MODAL MANAGEMENT
// ============================================================================

/**
 * Open AI modal with content type
 * 
 * @param {string} type - Content type: 'trend_insight', 'action_plan', 'health_rec', etc.
 */
function openAIModal(type) {
  if (type === 'chat') {
    openAIChat();
    return;
  }

  const modal = document.getElementById('aiModal');
  const content = document.getElementById('aiModalContent');
  
  if (!modal || !content) {
    console.warn('[Alerts] AI modal elements not found in DOM');
    return;
  }
  
  // Close alert drawer if open
  closeAlertDrawer();
  
  // Show modal
  modal.classList.add('active');
  
  // Show loading state
  content.innerHTML = `<div class="ai-loading">
    <div class="spinner"></div>
    <p>Analyzing data context...</p>
  </div>`;
  
  // Simulate async data fetch (replace with actual API call in production)
  setTimeout(() => {
    const responses = {
      trend_insight: `<div class="ai-response">
        <h3>📊 Trend Analysis</h3>
        <p>The last 7 days show a concerning upward trend in PM2.5 levels, with peak readings correlating to increased traffic hours.</p>
        <ul>
          <li>Average AQI has increased by 12% week-over-week</li>
          <li>Peak readings typically occur 14:00-16:00 daily</li>
          <li>Recommend increasing monitoring frequency during peak hours</li>
        </ul>
      </div>`,
      action_plan: `<div class="ai-response">
        <h3>⚡ AI Action Plan</h3>
        <p><strong>Alert Status: Critical</strong></p>
        <p>Immediate recommendations for hazardous AQI levels:</p>
        <ol>
          <li>Issue public health alert to residents</li>
          <li>Recommend outdoor activity restrictions</li>
          <li>Deploy additional monitoring nodes to affected areas</li>
          <li>Check node calibration - verify sensor accuracy</li>
        </ol>
      </div>`,
      health_rec: `<div class="ai-response">
        <h3>🏥 Health Recommendations</h3>
        <p>Based on current air quality metrics:</p>
        <ul>
          <li><strong>Vulnerable Groups:</strong> Limit outdoor activities</li>
          <li><strong>General Population:</strong> Use N95 masks if outdoors</li>
          <li><strong>Optimal Time:</strong> Early morning (06:00-08:00) shows best AQI</li>
          <li><strong>Indoor Guidance:</strong> Use HEPA air purifiers during peak pollution hours</li>
        </ul>
      </div>`,
      default: `<div class="ai-response"><p>AI analysis loading for type: ${type}</p></div>`
    };
    
    content.innerHTML = responses[type] || responses.default;
  }, 800);
}

/**
 * Close AI modal
 */
function closeAIModal() {
  const modal = document.getElementById('aiModal');
  if (modal) {
    modal.classList.remove('active');
  }
}

/**
 * Open AI chat overlay
 */
function openAIChat() {
  const overlay = document.getElementById('aiChatOverlay');
  const launcher = document.getElementById('aiGifLauncher');
  const input = document.getElementById('aiChatInput');

  if (!overlay) {
    console.warn('[Alerts] AI chat overlay not found in DOM');
    return;
  }

  closeAlertDrawer();
  closeAIModal();

  overlay.classList.add('active');
  overlay.setAttribute('aria-hidden', 'false');

  if (launcher) {
    launcher.classList.add('hidden');
  }

  if (input) {
    input.focus();
  }
}

/**
 * Close AI chat overlay
 */
function closeAIChat() {
  const overlay = document.getElementById('aiChatOverlay');
  const launcher = document.getElementById('aiGifLauncher');

  if (overlay) {
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
  }

  if (launcher) {
    launcher.classList.remove('hidden');
  }
}

function hideAIGifLauncher() {
  const launcher = document.getElementById('aiGifLauncher');
  if (launcher) {
    launcher.classList.add('hidden');
  }
}

function appendChatMessage(text, sender = 'ai') {
  const body = document.getElementById('aiChatBody');
  if (!body) return;

  const message = document.createElement('div');
  message.className = `chat-message ${sender}`;

  const label = document.createElement('div');
  label.className = 'chat-label';
  label.innerHTML = sender === 'user'
    ? '<i class="fa-solid fa-user"></i> You'
    : '<i class="fa-solid fa-brain"></i> EnviroNode AI';

  const bubble = document.createElement('p');
  bubble.textContent = text;

  message.appendChild(label);
  message.appendChild(bubble);
  body.appendChild(message);
  body.scrollTop = body.scrollHeight;
}

function getAIResponse(message) {
  const cleaned = message.toLowerCase();

  if (cleaned.includes('aqi')) {
    return 'AQI stands for Air Quality Index. Lower values mean cleaner air; higher values require more caution. Ask me for current node status or health tips to learn more.';
  }
  if (cleaned.includes('health')) {
    return 'For current air quality, vulnerable people should limit outdoor activity, wear masks when needed, and stay indoors during peak pollution periods.';
  }
  if (cleaned.includes('node') || cleaned.includes('sensor')) {
    return 'All active nodes are being monitored in real time. You can filter nodes in the dashboard to see status and readings for each location.';
  }
  if (cleaned.includes('forecast')) {
    return 'Forecast results show short-term air quality trends. Use this to prepare for changes in pollution levels throughout the day.';
  }

  return 'Thanks for the question! I can help with AQI definitions, health guidance, node status, and forecast insights. Try asking "What is AQI?" or "How is the air today?".';
}

function sendAIChatMessage() {
  const input = document.getElementById('aiChatInput');
  if (!input) return;

  const text = input.value.trim();
  if (!text) return;

  appendChatMessage(text, 'user');
  input.value = '';
  input.disabled = true;

  setTimeout(() => {
    appendChatMessage(getAIResponse(text), 'ai');
    input.disabled = false;
    input.focus();
  }, 700);
}

function setupAIChatOverlayClose() {
  const overlay = document.getElementById('aiChatOverlay');
  if (!overlay) return;

  overlay.addEventListener('click', function (e) {
    if (e.target === this) {
      closeAIChat();
    }
  });
}

function setupAIModalOverlayClose() {
  const modal = document.getElementById('aiModal');
  if (!modal) return;

  modal.addEventListener('click', function (e) {
    if (e.target === this) {
      closeAIModal();
    }
  });
}

// ============================================================================
// ALERT BELL ICON SEVERITY MANAGEMENT
// ============================================================================

/**
 * Update alert bell icon based on severity level
 * 
 * @param {string} severity - One of: 'none', 'info', 'warning', 'critical'
 */
function updateAlertBellSeverity(severity) {
  const bell = document.getElementById('alertBell');
  const badge = document.getElementById('alertBadge');
  
  if (!bell) {
    console.warn('[Alerts] Alert bell icon not found in DOM');
    return;
  }
  
  // Remove all severity classes
  bell.classList.remove('alert-none', 'alert-info', 'alert-warning', 'alert-critical');
  
  // Add current severity class
  bell.classList.add(`alert-${severity}`);
  
  // Update badge if it exists
  if (badge) {
    const badgeColors = {
      none: { bg: '#10b981', color: '#fff' },
      info: { bg: '#3b82f6', color: '#fff' },
      warning: { bg: '#f59e0b', color: '#fff' },
      critical: { bg: '#ef4444', color: '#fff' }
    };
    
    const colors = badgeColors[severity] || badgeColors.none;
    badge.style.backgroundColor = colors.bg;
    badge.style.color = colors.color;
  }
}

/**
 * Update alert badge counter
 * 
 * @param {number} count - Number of active alerts
 */
function updateAlertCount(count) {
  const badge = document.getElementById('alertBadge');
  if (badge) {
    badge.textContent = count > 99 ? '99+' : count;
    badge.style.display = count > 0 ? 'flex' : 'none';
  }
}

// ============================================================================
// ALERT DRAWER FILTER FUNCTIONALITY
// ============================================================================

/**
 * Filter alerts by severity
 * 
 * @param {string} severity - Filter: 'all', 'critical', 'warning', 'info'
 */
function filterAlertsBySeverity(severity) {
  const alerts = document.querySelectorAll('.alert-card');
  
  alerts.forEach(alert => {
    if (severity === 'all') {
      alert.style.display = 'block';
    } else {
      const alertSeverity = alert.getAttribute('data-severity') || 'info';
      alert.style.display = alertSeverity === severity ? 'block' : 'none';
    }
  });
  
  // Update active filter button
  const filterBtns = document.querySelectorAll('.alert-filter-btn');
  filterBtns.forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-filter') === severity);
  });
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize global alerts system
 * Call this on document ready
 */
function initializeGlobalAlerts() {
  // Setup overlay close handlers
  setupAIModalOverlayClose();
  setupAIChatOverlayClose();
  
  // Setup drawer overlay click to close
  const drawerOverlay = document.getElementById('drawerOverlay');
  if (drawerOverlay) {
    drawerOverlay.addEventListener('click', toggleAlertDrawer);
  }
  
  // Setup notification dropdown for the bell
  const alertBell = document.getElementById('alertBell');
  if (alertBell) {
    const hasInlineClick = alertBell.getAttribute('onclick') || typeof alertBell.onclick === 'function';
    if (!hasInlineClick) {
      alertBell.addEventListener('click', toggleNotificationDropdown);
    }
  }

  document.addEventListener('click', closeNotificationDropdownOnOutsideClick);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeNotificationDropdown();
      closeAlertDrawer();
    }
  });

  const chatSendBtn = document.getElementById('aiChatSend');
  if (chatSendBtn) {
    chatSendBtn.addEventListener('click', sendAIChatMessage);
  }

  const chatInput = document.getElementById('aiChatInput');
  if (chatInput) {
    chatInput.addEventListener('keydown', function(event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendAIChatMessage();
      }
    });
  }
  
  console.log('[Alerts] Global alerts system initialized');
}

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeGlobalAlerts);
} else {
  initializeGlobalAlerts();
}
