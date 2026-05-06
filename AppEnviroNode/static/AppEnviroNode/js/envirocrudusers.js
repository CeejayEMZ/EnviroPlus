/**
 * ENVIROCRUDUSERS.JS - Dynamic User Management System
 * * Features:
 * - User CRUD (Create, Read, Update, Delete)
 * - Dynamic filtering and search (Server-side)
 * - Server-side Pagination
 * - Role-based UI control
 * - Modal-driven workflows
 * - Status management (active, pending, disabled)
 */

// ============================================================================
// APPLICATION STATE
// ============================================================================

const EnviroUserApp = {
  // Data State
  users: [],
  totalCount: 0, // Used for server-side pagination
  
  // UI State
  currentPage: 1,
  itemsPerPage: 10,
  currentUser: null,
  isLoading: false,
  
  // Alert State (prevent duplicates)
  lastAlertTime: 0,
  alertDebounceMs: 500,
  
  // Filters (Sent only to backend)
  filters: {
    search: '',
    role: 'all',
    status: 'all',
  },
  
  // Metrics (Populated directly from backend)
  metrics: {
    total_users: 0,
    active_users: 0,
    pending_invites: 0,
    administrators: 0,
  },

  // Modal State
  pendingAction: null,
};

// ============================================================================
// INITIALIZATION & SETUP
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  EnviroUserApp.init();
});

EnviroUserApp.init = async function() {
  try {
    const me = await this.fetchCurrentUser();
    this.currentUser = me;
    if (me.role !== 'admin') {
      this.removeNavbarManagementItems();
    }
  } catch (err) {
    console.warn('Could not fetch current user:', err);
  }
  
  this.setupEventListeners();
  await this.refreshUsers();
  this.setupModalHandlers();
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

EnviroUserApp.fetchCurrentUser = async function() {
  const response = await fetch('/api/auth/me/');
  if (!response.ok) throw new Error('Failed to fetch current user');
  return await response.json();
};

EnviroUserApp.setLoading = function(isLoading) {
  if (this._loadingLock && isLoading === true) return;
  this._loadingLock = isLoading;
  this.isLoading = isLoading;
  const loader = document.getElementById('cruduserLoadingOverlay');
  
  if (!loader) {
    if (isLoading) {
      const overlay = document.createElement('div');
      overlay.id = 'cruduserLoadingOverlay';
      overlay.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0, 0, 0, 0.3); display: flex;
        align-items: center; justify-content: center; z-index: 9999;
      `;
      overlay.innerHTML = `
        <div style="background: white; padding: 20px; border-radius: 8px; text-align: center;">
          <div style="width: 40px; height: 40px; margin: 0 auto 10px; border: 4px solid #e0e0e0; border-top-color: #2563eb; border-radius: 50%; animation: spin 1s linear infinite;"></div>
          <p style="color: #666; margin: 0;">Loading...</p>
        </div>
        <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
      `;
      document.body.appendChild(overlay);
    }
  } else {
    loader.style.display = isLoading ? 'flex' : 'none';
  }
  if (!isLoading) this._loadingLock = false;
};

EnviroUserApp.getAvatarColor = function(userId, name) {
  const colors = [
    'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
    'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
    'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
  ];
  return colors[(userId || 0) % colors.length];
};

EnviroUserApp.getInitials = function(name) {
  if (!name) return 'U';
  return name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
};

EnviroUserApp.formatDate = function(dateString) {
  if (!dateString) return 'Never';
  const date = new Date(dateString);
  const diff = new Date() - date;
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 1) return 'Today';
  if (days === 1) return 'Yesterday';
  
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
};

EnviroUserApp.removeNavbarManagementItems = function() {
  const navItems = document.querySelectorAll('[class*="navbar"], [class*="nav"] a, [class*="menu"] a');
  navItems.forEach(item => {
    if (item.textContent.toLowerCase().includes('management') || item.textContent.toLowerCase().includes('users')) {
      item.closest('[class*="nav-item"], li, div[role="menuitem"]')?.remove();
    }
  });
};

// ============================================================================
// API FUNCTIONS
// ============================================================================

EnviroUserApp.fetchUsers = async function() {
  try {
    this.setLoading(true);
    const params = new URLSearchParams({
      search: this.filters.search,
      role: this.filters.role,
      status: this.filters.status,
      page: this.currentPage,
      limit: this.itemsPerPage,
    });
    
    const response = await fetch(`/api/users/?${params}`);
    if (!response.ok) throw new Error('Failed to fetch users');
    
    const data = await response.json();
    
    // Server-side mapping
    this.users = data.results || data.data || [];
    this.totalCount = data.count || this.users.length;
    this.applyFilters();
    
    // Use backend metrics if provided, otherwise calculate client-side
    if (data.metrics) {
      this.metrics = data.metrics;
    } else {
      // Calculate metrics from users array as fallback
      this.metrics = {
        total_users: this.totalCount,
        active_users: this.users.filter(u => u.status === 'active').length,
        pending_invites: this.users.filter(u => u.status === 'pending').length,
        administrators: this.users.filter(u => u.role === 'admin').length,
      };
    }
    
    return data;
  } catch (err) {
    console.error('Error fetching users:', err);
    this.showErrorAlert('Failed to load users');
    return null;
  } finally {
    this.setLoading(false);
  }
};

EnviroUserApp.refreshUsers = async function() {
  await this.fetchUsers();
  this.renderMetrics();
  this.renderTable();
};

EnviroUserApp.createUser = async function(formData) {
  const response = await fetch('/api/users/create/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
    body: JSON.stringify(formData),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Failed to create user');
  return data;
};

EnviroUserApp.inviteUser = async function(formData) {
  const response = await fetch('/api/users/invite/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
    body: JSON.stringify(formData),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Failed to send invitation');
  return data;
};

EnviroUserApp.deleteUser = async function(userId) {
  const response = await fetch(`/api/users/${userId}/delete/`, {
    method: 'DELETE',
    headers: { 'X-CSRFToken': this.getCSRFToken() },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Failed to delete user');
  return data;
};

EnviroUserApp.toggleUserStatus = async function(userId, isActive) {
  const response = await fetch(`/api/users/${userId}/toggle/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
    body: JSON.stringify({ is_active: isActive }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Failed to update user status');
  return data;
};

EnviroUserApp.resendInvite = async function(userId) {
  const response = await fetch(`/api/users/${userId}/resend-invite/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Failed to resend invitation');
  return data;
};

EnviroUserApp.getCSRFToken = function() {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, 10) === ('csrftoken=')) {
        cookieValue = decodeURIComponent(cookie.substring(10));
        break;
      }
    }
  }
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value || cookieValue || '';
};

EnviroUserApp.isValidEmail = function(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
};

EnviroUserApp.validateUserForm = async function(data, isNewUser = false) {
  const errors = [];
  if (!data.email || !this.isValidEmail(data.email)) errors.push('Invalid email format');
  if (!data.username && !data.name) errors.push('Username or Name is required');
  return errors;
};

// ============================================================================
// RENDERING FUNCTIONS
// ============================================================================

EnviroUserApp.renderMetrics = function() {
  const metricCards = document.querySelectorAll('.cruduser-metric-value');
  if (metricCards[0]) metricCards[0].textContent = this.metrics.total_users || 0;
  if (metricCards[1]) metricCards[1].textContent = this.metrics.active_users || 0;
  if (metricCards[2]) metricCards[2].textContent = this.metrics.pending_invites || 0;
  if (metricCards[3]) metricCards[3].textContent = this.metrics.administrators || 0;
};

EnviroUserApp.renderTable = function() {
  const tbody = document.getElementById('cruduserTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  
  if (this.users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px 16px; color: var(--cruduser-text-muted);">No users found</td></tr>`;
    this.renderPagination(0);
    return;
  }
  
  this.users.forEach(user => {
    const row = document.createElement('tr');
    const initials = this.getInitials(user.full_name || user.username);
    const avatarColor = this.getAvatarColor(user.id, user.full_name);
    
    let actionsHTML = '';
    if (user.status === 'active') {
      actionsHTML = `
        <button class="cruduser-action-btn primary cruduserEditBtn" data-user-id="${user.id}"><i class="fa-solid fa-pen"></i></button>
        <button class="cruduser-action-btn danger cruduserDisableBtn" data-user-id="${user.id}" data-user-name="${user.full_name || user.email}"><i class="fa-solid fa-ban"></i></button>
      `;
    } else if (user.status === 'pending') {
      actionsHTML = `
        <button class="cruduser-action-btn primary cruduserResendBtn" data-user-id="${user.id}"><i class="fa-solid fa-paper-plane"></i></button>
        <button class="cruduser-action-btn primary cruduserCopyLinkBtn" data-user-id="${user.id}"><i class="fa-solid fa-link"></i></button>
        <button class="cruduser-action-btn danger cruduserRevokeBtn" data-user-id="${user.id}" data-user-name="${user.full_name || user.email}"><i class="fa-solid fa-trash"></i></button>
      `;
    } else if (user.status === 'disabled') {
      actionsHTML = `
        <button class="cruduser-action-btn cruduserRestoreBtn" data-user-id="${user.id}" style="color: var(--cruduser-success);"><i class="fa-solid fa-rotate-left"></i></button>
        <button class="cruduser-action-btn danger cruduserDeleteBtn" data-user-id="${user.id}" data-user-name="${user.full_name || user.email}"><i class="fa-solid fa-trash"></i></button>
      `;
    }
    
    row.innerHTML = `
      <td class="cruduser-td" style="text-align: center;"><input type="checkbox" class="cruduser-checkbox"></td>
      <td class="cruduser-td">
        <div class="cruduser-user-cell">
          <div class="cruduser-avatar" style="background: ${avatarColor};">${initials}</div>
          <div>
            <span class="cruduser-name">${user.full_name || user.username || 'Unknown'}</span>
            <span class="cruduser-email">${user.email}</span>
          </div>
        </div>
      </td>
      <td class="cruduser-td"><span class="cruduser-badge cruduser-role-${user.role}">${user.role === 'admin' ? 'Administrator' : 'Official'}</span></td>
      <td class="cruduser-td"><span class="cruduser-badge cruduser-status-${user.status}">${user.status.toUpperCase()}</span></td>
      <td class="cruduser-td" style="font-size: 0.8rem;">${this.formatDate(user.last_login)}</td>
      <td class="cruduser-td" style="font-size: 0.8rem;">${this.formatDate(user.created_at)}</td>
      <td class="cruduser-td"><div class="cruduser-actions-cell">${actionsHTML}</div></td>
    `;
    tbody.appendChild(row);
  });
  
  this.renderPagination(Math.ceil(this.totalCount / this.itemsPerPage));
};

EnviroUserApp.renderPagination = function(totalPages) {
  const pagination = document.querySelector('.cruduser-pagination');
  if (!pagination) return;
  
  const startUser = this.totalCount === 0 ? 0 : (this.currentPage - 1) * this.itemsPerPage + 1;
  const endUser = Math.min(this.currentPage * this.itemsPerPage, this.totalCount);
  
  const infoDiv = pagination.querySelector('.cruduser-pagination-info');
  if (infoDiv) infoDiv.innerHTML = `Showing <strong>${startUser}</strong> to <strong>${endUser}</strong> of <strong>${this.totalCount}</strong> users`;
  
  const controls = pagination.querySelector('.cruduser-pagination-controls');
  if (controls) {
    controls.innerHTML = '';
    
    const prevBtn = document.createElement('button');
    prevBtn.className = 'cruduser-page-btn';
    prevBtn.innerHTML = '<i class="fa-solid fa-chevron-left"></i>';
    prevBtn.disabled = this.currentPage === 1;
    prevBtn.onclick = () => { if (this.currentPage > 1) { this.currentPage--; this.refreshUsers(); } };
    controls.appendChild(prevBtn);
    
    for (let i = 1; i <= totalPages; i++) {
      const pageBtn = document.createElement('button');
      pageBtn.className = `cruduser-page-btn ${i === this.currentPage ? 'active' : ''}`;
      pageBtn.textContent = i;
      pageBtn.onclick = () => { this.currentPage = i; this.refreshUsers(); };
      controls.appendChild(pageBtn);
    }
    
    const nextBtn = document.createElement('button');
    nextBtn.className = 'cruduser-page-btn';
    nextBtn.innerHTML = '<i class="fa-solid fa-chevron-right"></i>';
    nextBtn.disabled = this.currentPage === totalPages || totalPages === 0;
    nextBtn.onclick = () => { if (this.currentPage < totalPages) { this.currentPage++; this.refreshUsers(); } };
    controls.appendChild(nextBtn);
  }
};

// ============================================================================
// EVENT LISTENERS & MODAL HANDLERS
// ============================================================================

EnviroUserApp.setupEventListeners = function() {
  const searchInput = document.querySelector('.cruduser-input-search');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        this.filters.search = e.target.value;
        this.currentPage = 1;
        this.refreshUsers();
      }, 300);
    });
  }
  
  const filters = document.querySelectorAll('.cruduser-filter-select');
  if (filters[0]) {
    filters[0].addEventListener('change', (e) => {
      this.filters.role = e.target.value === 'Administrator' ? 'admin' : e.target.value === 'Barangay Official' ? 'official' : 'all';
      this.currentPage = 1;
      this.refreshUsers();
    });
  }
  if (filters[1]) {
    filters[1].addEventListener('change', (e) => {
      const val = e.target.value;
      this.filters.status = val === 'Active' ? 'active' : val === 'Pending Invite' ? 'pending' : val === 'Disabled' ? 'disabled' : 'all';
      this.currentPage = 1;
      this.refreshUsers();
    });
  }
  
  document.addEventListener('click', (e) => {
    const target = e.target.closest('button');
    if (!target) return;
    
    const userId = target.dataset.userId;
    const userName = target.dataset.userName || 'this user';

    if (target.classList.contains('cruduserEditBtn')) this.handleEditUser(userId);
    if (target.classList.contains('cruduserResendBtn')) this.handleResendInvite(userId);
    if (target.classList.contains('cruduserCopyLinkBtn')) this.handleCopyInviteLink(userId);
    if (target.classList.contains('cruduserRestoreBtn')) this.handleRestoreUser(userId);
    
    if (target.classList.contains('cruduserDisableBtn')) {
      this.handleShowConfirm('Disable Account', `Are you sure you want to disable ${userName}?`, () => this.handleDisableUser(userId));
    }
    if (target.classList.contains('cruduserRevokeBtn')) {
      this.handleShowConfirm('Revoke Invite', `Are you sure you want to revoke the invitation for ${userName}?`, () => this.handleDeleteUser(userId));
    }
    if (target.classList.contains('cruduserDeleteBtn')) {
      this.handleShowConfirm('Delete Permanently', `Are you sure you want to permanently delete ${userName}?`, () => this.handleDeleteUser(userId));
    }
  });
};

EnviroUserApp.setupModalHandlers = function() {
  const attachFormHandler = (formId, submitLogic) => {
    const form = document.getElementById(formId);
    if (form) {
      const newForm = form.cloneNode(true);
      form.parentNode.replaceChild(newForm, form);
      newForm.addEventListener('submit', submitLogic);
    }
  };

  attachFormHandler('cruduserManualForm', async (e) => {
    e.preventDefault();
    const form = e.target;
    
    const formData = {
      username: form.querySelector('input[name="username"]')?.value.trim() || '',
      first_name: form.querySelector('input[name="first_name"]')?.value.trim() || '',
      last_name: form.querySelector('input[name="last_name"]')?.value.trim() || '',
      email: form.querySelector('input[type="email"]')?.value.trim() || '',
      role: form.querySelector('select')?.value || 'official',
      password: form.querySelector('input[type="password"]')?.value || '',
    };
    
    // Ensure "name" falls back safely if backend looks for `name`
    formData.name = formData.username || `${formData.first_name} ${formData.last_name}`.trim();
    
    try {
      this.setLoading(true);
      await this.createUser(formData);
      this.showSuccessAlert('User created successfully');
      cruduserToggleModal('cruduserManualModal');
      form.reset();
      await this.refreshUsers();
    } catch (err) {
      this.showErrorAlert(err.message || 'Failed to create user');
    } finally {
      this.setLoading(false);
    }
  });

  attachFormHandler('cruduserInviteForm', async (e) => {
    e.preventDefault();
    const form = e.target;
    
    const formData = {
      username: form.querySelector('input[name="username"]')?.value.trim() || '',
      first_name: form.querySelector('input[name="first_name"]')?.value.trim() || '',
      last_name: form.querySelector('input[name="last_name"]')?.value.trim() || '',
      email: form.querySelector('input[type="email"]')?.value.trim() || '',
      role: form.querySelector('select')?.value || 'official',
    };
    
    formData.name = formData.username || `${formData.first_name} ${formData.last_name}`.trim();
    
    try {
      this.setLoading(true);
      await this.inviteUser(formData);
      this.showSuccessAlert('Invitation sent successfully');
      cruduserToggleModal('cruduserInviteModal');
      form.reset();
      await this.refreshUsers();
    } catch (err) {
      this.showErrorAlert(err.message || 'Failed to send invitation');
    } finally {
      this.setLoading(false);
    }
  });

  attachFormHandler('cruduserEditForm', async (e) => {
    e.preventDefault();
    const userId = e.target.dataset.userId;
    
    const payload = {
      first_name: document.getElementById('cruduserEditFirstName').value.trim(),
      last_name: document.getElementById('cruduserEditLastName').value.trim(),
      email: document.getElementById('cruduserEditEmail').value.trim(),
      role: document.getElementById('cruduserEditRole').value,
      organization: document.getElementById('cruduserEditOrganization')?.value.trim() || '',
    };
    
    try {
      this.setLoading(true);
      const response = await fetch(`/api/users/${userId}/update/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error((await response.json()).message || 'Failed to update user');
      
      this.showSuccessAlert('User updated successfully');
      cruduserToggleModal('cruduserEditModal');
      await this.refreshUsers();
    } catch (err) {
      this.showErrorAlert(err.message);
    } finally {
      this.setLoading(false);
    }
  });
};

// ============================================================================
// ACTION HANDLERS
// ============================================================================

EnviroUserApp.handleEditUser = function(userId) {
  const user = this.users.find(u => u.id == userId);
  if (!user) return this.showErrorAlert('User not found');
  
  // Data inconsistency fix: split full_name into first_name and last_name mapping
  const nameParts = (user.full_name || '').split(' ');
  const firstName = user.first_name || nameParts[0] || '';
  const lastName = user.last_name || nameParts.slice(1).join(' ') || '';
  
  if(document.getElementById('cruduserEditUsername')) document.getElementById('cruduserEditUsername').value = user.username || '';
  if(document.getElementById('cruduserEditFirstName')) document.getElementById('cruduserEditFirstName').value = firstName;
  if(document.getElementById('cruduserEditLastName')) document.getElementById('cruduserEditLastName').value = lastName;
  if(document.getElementById('cruduserEditEmail')) document.getElementById('cruduserEditEmail').value = user.email || '';
  if(document.getElementById('cruduserEditRole')) document.getElementById('cruduserEditRole').value = user.role || 'official';
  if(document.getElementById('cruduserEditOrganization')) document.getElementById('cruduserEditOrganization').value = user.organization || '';
  
  document.getElementById('cruduserEditForm').dataset.userId = userId;
  cruduserToggleModal('cruduserEditModal');
};

EnviroUserApp.handleDeleteUser = async function(userId) {
  // Removed nested handleShowConfirm - delete directly when called from modal logic
  try {
    this.setLoading(true);
    await this.deleteUser(userId);
    this.showSuccessAlert('Action successful');
    // Close the confirmation modal
    cruduserToggleModal('cruduserConfirmModal');
    await this.refreshUsers();
  } catch (err) {
    this.showErrorAlert(err.message || 'Failed to delete user');
  } finally {
    this.setLoading(false);
  }
};

EnviroUserApp.handleDisableUser = async function(userId) {
  try {
    this.setLoading(true);
    await this.toggleUserStatus(userId, false);
    this.showSuccessAlert('Disabled successfully');
    // Close the confirmation modal
    cruduserToggleModal('cruduserConfirmModal');
    await this.refreshUsers();
  } catch (err) {
    this.showErrorAlert(err.message);
  } finally {
    this.setLoading(false);
  }
};

EnviroUserApp.handleRestoreUser = async function(userId) {
  try {
    this.setLoading(true);
    await this.toggleUserStatus(userId, true);
    this.showSuccessAlert('Restored successfully');
    // Close the confirmation modal
    cruduserToggleModal('cruduserConfirmModal');
    await this.refreshUsers();
  } catch (err) {
    this.showErrorAlert(err.message);
  } finally {
    this.setLoading(false);
  }
};

EnviroUserApp.handleResendInvite = async function(userId) {
  try { this.setLoading(true); await this.resendInvite(userId); this.showSuccessAlert('Invitation resent'); await this.refreshUsers(); } catch (err) { this.showErrorAlert(err.message); } finally { this.setLoading(false); }
};

EnviroUserApp.handleCopyInviteLink = async function(userId) {
  try {
    const response = await fetch(`/api/users/${userId}/invite-link/`);
    if (!response.ok) throw new Error('Failed to fetch link');
    const data = await response.json();
    const link = data.link || data.invite_link;
    if (link) {
      await navigator.clipboard.writeText(link);
      this.showSuccessAlert('Invite link copied to clipboard');
    } else throw new Error('Link missing');
  } catch (err) {
    this.showErrorAlert('Failed to copy: ' + err.message);
  }
};

EnviroUserApp.handleShowConfirm = function(title, message, onConfirm) {
  this.pendingAction = null; // reset first (IMPORTANT)

  document.getElementById('cruduserConfirmTitle').textContent = title;
  document.getElementById('cruduserConfirmMessage').textContent = message;

  this.pendingAction = async () => {
    this.pendingAction = null; // auto-clear after execution
    await onConfirm();
  };

  cruduserToggleModal('cruduserConfirmModal');
};

EnviroUserApp.setupConfirmationButton = function() {
  const modal = document.getElementById('cruduserConfirmModal');
  if (!modal) return;
  
  // FIX: Broaden the class match to catch the new HTML template classes
  const buttons = Array.from(modal.querySelectorAll('.cruduser-modal-footer button'));
  const confirmBtn = modal.querySelector('[data-action="confirm"]') || 
                     buttons.find(btn => btn.classList.contains('cruduser-btn-danger') || btn.classList.contains('danger') || btn.textContent.includes('Delete') || btn.textContent.includes('Confirm') || btn.textContent.includes('Revoke'));
  
  const cancelBtn = modal.querySelector('[data-action="cancel"]') || 
                    buttons.find(btn => btn.classList.contains('cruduser-btn-secondary') || btn.classList.contains('secondary') || btn.textContent.includes('Cancel'));
  
  if (!confirmBtn) return;
  
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
  
  newConfirmBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation(); // FIX: Prevent bubbling from re-opening modals
    const action = EnviroUserApp.pendingAction;
    EnviroUserApp.pendingAction = null; 
    
    cruduserToggleModal('cruduserConfirmModal');
    
    if (action && typeof action === 'function') {
      try { await action(); } catch (err) { console.error('Confirm action error:', err); }
    }
  });
  
  if (cancelBtn) {
    const newCancelBtn = cancelBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
    newCancelBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation(); // FIX: Prevent bubbling
      EnviroUserApp.pendingAction = null;
      cruduserToggleModal('cruduserConfirmModal');
    });
  }
};

// ============================================================================
// UI FEEDBACK FUNCTIONS
// ============================================================================

EnviroUserApp.showSuccessAlert = function(message) {
  const now = Date.now();
  if (now - this.lastAlertTime < this.alertDebounceMs) return;
  this.lastAlertTime = now;
  
  const alert = document.createElement('div');
  alert.style.cssText = `position: fixed; top: 20px; right: 20px; background: #dcfce7; color: #15803d; padding: 16px 20px; border-radius: 8px; border: 1px solid #86efac; z-index: 10000; animation: slideIn 0.3s ease;`;
  alert.innerHTML = `<i class="fa-solid fa-check"></i> ${message}`;
  document.body.appendChild(alert);
  setTimeout(() => alert.remove(), 3000);
};

EnviroUserApp.showErrorAlert = function(message) {
  const now = Date.now();
  if (now - this.lastAlertTime < this.alertDebounceMs) return;
  this.lastAlertTime = now;
  
  const alert = document.createElement('div');
  alert.style.cssText = `position: fixed; top: 20px; right: 20px; background: #fee2e2; color: #991b1b; padding: 16px 20px; border-radius: 8px; border: 1px solid #fecaca; z-index: 10000; animation: slideIn 0.3s ease;`;
  alert.innerHTML = `<i class="fa-solid fa-circle-exclamation"></i> ${message}`;
  document.body.appendChild(alert);
  setTimeout(() => alert.remove(), 3000);
};

// ============================================================================
// GLOBAL SCOPE MODAL FUNCTIONS
// ============================================================================

window.cruduserToggleModal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (modal.classList.contains('active')) {
    modal.classList.remove('active');
    const form = modal.querySelector('form');
    if (form) form.reset();
  } else {
    modal.classList.add('active');
  }
};

window.cruduserCloseOnOutsideClick = function(event, modalId) {
  if (event.target.id === modalId) cruduserToggleModal(modalId);
};

EnviroUserApp.applyFilters = function() {
  const search = this.filters.search.toLowerCase();

  this.filteredUsers = this.users.filter(user => {
    const matchesSearch =
      !search ||
      user.full_name.toLowerCase().includes(search) ||
      user.email.toLowerCase().includes(search);

    const matchesRole =
      this.filters.role === 'all' || user.role === this.filters.role;

    const matchesStatus =
      this.filters.status === 'all' || user.status === this.filters.status;

    return matchesSearch && matchesRole && matchesStatus;
  });

  this.currentPage = 1;
  this.renderMetrics();
  this.renderTable();
};