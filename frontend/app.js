/* ═══════════════════════════════════════════════════════════════
   DMS Instance Monitor — app.js
   Fetch-based, no dependencies
═══════════════════════════════════════════════════════════════ */

const API_BASE = '/api/instances';
const REFRESH_INTERVAL = 30_000; // 30 seconds

// ─── State ───────────────────────────────────────────────────────────────────
let instances = [];
let selectedId = null;
let editMode = false;
let refreshTimer = null;

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const grid = document.getElementById('instancesGrid');
const overlay = document.getElementById('panelOverlay');
const panel = document.getElementById('detailPanel');
const panelClose = document.getElementById('panelClose');
const panelBadge = document.getElementById('panelBadge');
const panelTitle = document.getElementById('panelTitle');
const panelUrl = document.getElementById('panelUrl');
const panelStatus = document.getElementById('panelStatusBadge');
const panelBody = document.getElementById('panelBody');
const panelActions = document.getElementById('panelActions');
const panelFeedback = document.getElementById('panelFeedback');
const editForm = document.getElementById('editForm');
const btnAssign = document.getElementById('btnAssign');
const btnFree = document.getElementById('btnFree');
const btnMaintenance = document.getElementById('btnMaintenance');
const btnCancelEdit = document.getElementById('btnCancelEdit');
const btnExit = document.getElementById('btnExit');
const btnRefresh = document.getElementById('btnRefresh');
const lastUpdated = document.getElementById('lastUpdated');
const countAvail = document.getElementById('countAvailable');
const countInUse = document.getElementById('countInUse');
const countUnknown = document.getElementById('countUnknown');

// ─── API helpers ──────────────────────────────────────────────────────────────
async function fetchAll() {
  const res = await fetch(API_BASE);
  if (!res.ok) throw new Error('Failed to fetch instances');
  return res.json();
}

async function updateInstance(id, payload) {
  const res = await fetch(`${API_BASE}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error('Failed to update instance');
  return res.json();
}

async function freeInstance(id) {
  const res = await fetch(`${API_BASE}/${id}/free`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to free instance');
  return res.json();
}

async function setMaintenanceInstance(id) {
  const res = await fetch(`${API_BASE}/${id}/maintenance`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to mark instance as in maintenance');
  return res.json();
}

// ─── Render grid ──────────────────────────────────────────────────────────────
function getStatus(inst) {
  if (inst.status === 'in_use') return 'in_use';
  if (inst.status === 'maintenance') return 'maintenance';
  return 'available';
}

function statusLabel(status) {
  if (status === 'available') return 'Available';
  if (status === 'in_use') return 'In Use';
  return 'In Maintenance';
}

function renderGrid(data) {
  grid.innerHTML = '';

  // ── Logo card — first cell of the grid ────────────────────────
  const logoCard = document.createElement('div');
  logoCard.className = 'instance-logo-card';
  logoCard.innerHTML = `<img src="/static/logo.jpg" alt="DMS Instance Monitor" />`;
  grid.appendChild(logoCard);

  let cAvail = 0, cInUse = 0, cUnk = 0;

  data.forEach(inst => {
    const status = getStatus(inst);
    if (status === 'available') cAvail++;
    else if (status === 'in_use') cInUse++;
    else cUnk++;

    const btn = document.createElement('button');
    btn.className = `instance-btn ${status}`;
    btn.id = `inst-btn-${inst.id}`;
    btn.title = inst.url;
    btn.setAttribute('aria-label', `Instance ${inst.port} – ${statusLabel(status)}`);

    const userHtml = (status === 'in_use' && inst.used_by)
      ? `<span class="user-label">${escHtml(truncate(inst.used_by, 18))}</span>`
      : `<span class="user-label" style="opacity:0">—</span>`;

    // Show expiry countdown if in_use + date_to
    let extraHtml = '';
    if (status === 'in_use' && inst.date_to) {
      const diff = daysUntil(inst.date_to);
      if (diff === 0) extraHtml = `<span class="status-text" style="color:#ffaa00;">Expires today</span>`;
      else if (diff > 0) extraHtml = `<span class="status-text">Until ${formatDateShort(inst.date_to)}</span>`;
      else extraHtml = `<span class="status-text" style="color:#ff5c5c;">Expired</span>`;
    } else {
      extraHtml = `<span class="status-text">${statusLabel(status)}</span>`;
    }

    btn.innerHTML = `
      <span class="status-dot"></span>
      <span class="port-num">${inst.port}</span>
      ${userHtml}
      ${extraHtml}
    `;

    btn.addEventListener('click', () => openPanel(inst.id));
    grid.appendChild(btn);
  });

  // Update stat chips
  countAvail.textContent = cAvail;
  countInUse.textContent = cInUse;
  countUnknown.textContent = cUnk;
}

// ─── Panel ─────────────────────────────────────────────────────────────────────
function openPanel(id) {
  selectedId = id;
  const inst = instances.find(i => i.id === id);
  if (!inst) return;

  const status = getStatus(inst);

  panelBadge.textContent = inst.port;
  panelTitle.textContent = `Instance ${inst.port}`;
  panelUrl.textContent = inst.url;
  panelUrl.href = inst.url;

  panelStatus.textContent = statusLabel(status);
  panelStatus.className = `panel-status-badge ${status}`;

  document.getElementById('infoUsedBy').textContent = inst.used_by || '—';
  document.getElementById('infoFrom').textContent = inst.date_from ? formatDate(inst.date_from) : '—';
  document.getElementById('infoTo').textContent = inst.date_to ? formatDate(inst.date_to) : '—';
  document.getElementById('infoNotes').textContent = inst.notes || '—';

  function setupCopyBtn(btn, text) {
    if (!text) {
      btn.style.display = 'none';
      return;
    }
    btn.style.display = 'inline-flex';
    btn.onclick = () => {
      navigator.clipboard.writeText(text);
      btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>';
      setTimeout(() => {
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
      }, 1500);
    };
  }

  const infoPassword = document.getElementById('infoPassword');
  const btnCopyPwd = document.getElementById('btnCopyPwd');
  const pwdExtras = document.querySelectorAll('.pwd-extra');
  if (inst.password) {
    infoPassword.textContent = inst.password;
    setupCopyBtn(btnCopyPwd, inst.password);

    document.getElementById('infoPwdArrival').textContent = inst.pwd_arrival || '—';
    setupCopyBtn(document.getElementById('btnCopyPwdArr'), inst.pwd_arrival);
    document.getElementById('infoPwdDesk').textContent = inst.pwd_desk || '—';
    setupCopyBtn(document.getElementById('btnCopyPwdDesk'), inst.pwd_desk);
    document.getElementById('infoPwdDisplay').textContent = inst.pwd_display || '—';
    setupCopyBtn(document.getElementById('btnCopyPwdDisp'), inst.pwd_display);

    pwdExtras.forEach(el => el.style.display = 'flex');
  } else {
    infoPassword.textContent = '—';
    btnCopyPwd.style.display = 'none';
    pwdExtras.forEach(el => el.style.display = 'none');
  }

  hideFeedback();
  showReadMode(status);

  overlay.classList.add('active');
  panel.classList.add('open');
  editMode = false;
}

function closePanel() {
  overlay.classList.remove('active');
  panel.classList.remove('open');
  selectedId = null;
  editMode = false;
}

function showReadMode(status) {
  panelBody.style.display = 'flex';
  panelActions.style.display = 'flex';
  editForm.style.display = 'none';

  // Assign + In Maintenance visible when NOT in_use; Free visible only when in_use
  btnAssign.style.display = (status !== 'in_use') ? 'inline-flex' : 'none';
  btnMaintenance.style.display = (status !== 'in_use') ? 'inline-flex' : 'none';
  btnFree.style.display = (status === 'in_use') ? 'inline-flex' : 'none';

  // Show print btn if in_use
  document.getElementById('btnPrint').style.display = (status === 'in_use') ? 'inline-flex' : 'none';

  // Show Exit button in read mode
  btnExit.style.display = 'inline-flex';
}

function showEditMode() {
  const inst = instances.find(i => i.id === selectedId);
  if (!inst) return;

  panelBody.style.display = 'none';
  panelActions.style.display = 'none';
  editForm.style.display = 'flex';

  // Hide print in edit mode
  document.getElementById('btnPrint').style.display = 'none';

  // Pre-fill if already assigned
  document.getElementById('fieldUsedBy').value = inst.used_by || '';
  document.getElementById('fieldFrom').value = inst.date_from || '';
  document.getElementById('fieldTo').value = inst.date_to || '';
  document.getElementById('fieldNotes').value = inst.notes || '';
  document.getElementById('fieldPassword').value = inst.password || generatePassword();

  // Default From to today if empty
  if (!inst.date_from) {
    document.getElementById('fieldFrom').value = new Date().toISOString().split('T')[0];
  }

  editMode = true;
}

function generatePassword() {
  // Evite les caractères ambigus (l, 1, I, O, 0)
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!?#@*+';
  let pwd = '';
  for (let i = 0; i < 10; i++) pwd += chars.charAt(Math.floor(Math.random() * chars.length));
  return pwd;
}

// ─── Events ───────────────────────────────────────────────────────────────────
overlay.addEventListener('click', closePanel);
panelClose.addEventListener('click', closePanel);
document.getElementById('btnGenPwd').addEventListener('click', () => {
  document.getElementById('fieldPassword').value = generatePassword();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

btnAssign.addEventListener('click', showEditMode);

btnCancelEdit.addEventListener('click', () => {
  const inst = instances.find(i => i.id === selectedId);
  const status = getStatus(inst);
  showReadMode(status);
});

document.getElementById('btnPrint').addEventListener('click', () => {
  window.print();
});

btnExit.addEventListener('click', closePanel);

btnFree.addEventListener('click', async () => {
  btnFree.disabled = true;
  btnFree.textContent = 'Freeing…';
  try {
    const updated = await freeInstance(selectedId);
    syncInstance(updated);
    closePanel();
  } catch (err) {
    showFeedback('Error: ' + err.message, 'error');
  } finally {
    btnFree.disabled = false;
    btnFree.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      Mark as Available`;
  }
});

btnMaintenance.addEventListener('click', async () => {
  btnMaintenance.disabled = true;
  btnMaintenance.textContent = 'Updating…';
  try {
    const updated = await setMaintenanceInstance(selectedId);
    syncInstance(updated);
    closePanel();
  } catch (err) {
    showFeedback('Error: ' + err.message, 'error');
  } finally {
    btnMaintenance.disabled = false;
    btnMaintenance.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="0.5" fill="currentColor" stroke="currentColor" stroke-width="1.5"/></svg>
      In Maintenance`;
  }
});

editForm.addEventListener('submit', async e => {
  e.preventDefault();
  const usedBy = document.getElementById('fieldUsedBy').value.trim();
  const dateFrom = document.getElementById('fieldFrom').value;
  const dateTo = document.getElementById('fieldTo').value;
  const notes = document.getElementById('fieldNotes').value.trim();
  const password = document.getElementById('fieldPassword').value.trim();

  if (!usedBy || !dateFrom || !dateTo || !password) {
    showFeedback('Please fill in all required fields.', 'error');
    return;
  }
  if (dateTo < dateFrom) {
    showFeedback('"To" date must be after "From" date.', 'error');
    return;
  }

  const btnSave = document.getElementById('btnSave');
  btnSave.disabled = true;
  btnSave.textContent = 'Saving…';

  try {
    const updated = await updateInstance(selectedId, {
      status: 'in_use',
      used_by: usedBy,
      date_from: dateFrom,
      date_to: dateTo,
      notes: notes || null,
      password: password || null
    });
    syncInstance(updated);
    openPanel(selectedId);
    showFeedback('Instance configured successfully! Credits are displayed below.', 'success');
  } catch (err) {
    showFeedback('Error: ' + err.message, 'error');
  } finally {
    btnSave.disabled = false;
    btnSave.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" stroke="currentColor" stroke-width="2"/><polyline points="17 21 17 13 7 13 7 21" stroke="currentColor" stroke-width="2"/><polyline points="7 3 7 8 15 8" stroke="currentColor" stroke-width="2"/></svg>
      Save`;
  }
});

btnRefresh.addEventListener('click', () => {
  btnRefresh.classList.add('spinning');
  loadData().finally(() => btnRefresh.classList.remove('spinning'));
});

// ─── Data loading ─────────────────────────────────────────────────────────────
function showSkeletons() {
  grid.innerHTML = '';
  for (let i = 0; i < 29; i++) {
    const el = document.createElement('div');
    el.className = 'skeleton';
    grid.appendChild(el);
  }
}

async function loadData() {
  try {
    const data = await fetchAll();
    instances = data;
    renderGrid(data);
    lastUpdated.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    lastUpdated.textContent = 'Error loading data';
    console.error('[DMS Monitor]', err);
  }
}

function syncInstance(updated) {
  const idx = instances.findIndex(i => i.id === updated.id);
  if (idx !== -1) instances[idx] = updated;
  renderGrid(instances);
}

// ─── Feedback ─────────────────────────────────────────────────────────────────
let feedbackTimer = null;
function showFeedback(msg, type) {
  panelFeedback.textContent = msg;
  panelFeedback.className = `panel-feedback ${type} show`;
  clearTimeout(feedbackTimer);
  feedbackTimer = setTimeout(hideFeedback, 4000);
}
function hideFeedback() {
  panelFeedback.className = 'panel-feedback';
}

// ─── Utilities ───────────────────────────────────────────────────────────────
function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function truncate(str, max) {
  return str.length > max ? str.slice(0, max) + '…' : str;
}
function formatDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}
function formatDateShort(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y.slice(2)}`;
}
function daysUntil(iso) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const target = new Date(iso); target.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86_400_000);
}

// ─── Login Logic ──────────────────────────────────────────────────────────────
const LOGIN_STORAGE_KEY = 'dms_monitor_auth';

function checkAuth() {
  const isAuth = localStorage.getItem(LOGIN_STORAGE_KEY) === 'true';
  const loginScreen = document.getElementById('loginScreen');
  const appContent = document.getElementById('appContent');

  if (isAuth) {
    loginScreen.style.display = 'none';
    appContent.style.display = 'block';
    init(); // load data only if auth
  } else {
    loginScreen.style.display = 'flex';
    appContent.style.display = 'none';
  }
}

document.getElementById('loginForm').addEventListener('submit', e => {
  e.preventDefault();
  const user = document.getElementById('loginUser').value;
  const pass = document.getElementById('loginPass').value;
  const errorEl = document.getElementById('loginError');

  if (user === 'superuser' && pass === 'CphLby@2026!') {
    localStorage.setItem(LOGIN_STORAGE_KEY, 'true');
    errorEl.style.display = 'none';
    checkAuth();
  } else {
    errorEl.style.display = 'block';
  }
});

function init() {
  showSkeletons();
  loadData();
  refreshTimer = setInterval(loadData, REFRESH_INTERVAL);
}

// Start with auth check
checkAuth();
