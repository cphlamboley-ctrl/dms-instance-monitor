/* ═══════════════════════════════════════════════════════════════
   DMS Instance Monitor — manager.js
   Coherent Admin UI for DMS
═══════════════════════════════════════════════════════════════ */

const API_ADMIN = '/api/admin/instances';
const API_BASE = '/api/instances';

let allInstances = [];
let filteredInstances = [];

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const tableBody = document.getElementById('tableBody');
const modal = document.getElementById('instanceModal');
const modalCancel = document.getElementById('modalCancel');
const modalTitle = document.getElementById('modalTitle');
const instanceForm = document.getElementById('instanceForm');
const btnAdd = document.getElementById('btnAddInstance');
const loading = document.getElementById('loadingIndicator');
const searchInput = document.getElementById('searchInput');
const instanceCounter = document.getElementById('instanceCounter');
const btnTestPublic = document.getElementById('btnTestPublic');
const btnTestInternal = document.getElementById('btnTestInternal');

// Fields
const fieldId = document.getElementById('instanceId');
const fieldPort = document.getElementById('port');
const fieldUrl = document.getElementById('url');
const fieldInternalUrl = document.getElementById('internal_url');

// ─── App Start ──────────────────────────────────────────────────────────────
async function init() {
  if (localStorage.getItem('dms_monitor_auth') !== 'true') {
    window.location.href = '/';
    return;
  }
  await loadInstances();
  
  // Search logic
  searchInput.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    filteredInstances = allInstances.filter(inst => 
      inst.port.toString().includes(term) || 
      inst.url.toLowerCase().includes(term)
    );
    renderTable();
  });
}

async function loadInstances() {
  showLoading(true);
  try {
    const res = await fetch(API_BASE);
    if (!res.ok) throw new Error('Failed to load instances');
    allInstances = await res.json();
    filteredInstances = [...allInstances];
    renderTable();
  } catch (err) {
    console.error(err);
  } finally {
    showLoading(false);
  }
}

function renderTable() {
  tableBody.innerHTML = '';
  instanceCounter.textContent = `Displaying ${filteredInstances.length} of ${allInstances.length} entries`;

  filteredInstances.sort((a,b) => a.id - b.id).forEach((inst) => {
    const row = document.createElement('div');
    row.className = `instance-row ${inst.status || 'available'}`;
    
    const displayUrl = inst.url.replace(/^https?:\/\//, '');
    const status = inst.status || 'available';

    row.innerHTML = `
      <div class="row-id">#ID-${inst.id}</div>
      <div class="row-port">${inst.port}</div>
      <div class="row-url" title="${inst.url}">
        ${displayUrl}
        <span class="status-pill ${status} clickable" title="Click to change status">${status}</span>
      </div>
      <div class="row-internal">${inst.internal_url || '—'}</div>
      <div class="row-actions">
        <button class="btn-action action-edit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          Edit
        </button>
        <button class="btn-action action-delete ${status === 'in_use' ? 'disabled' : ''}" ${status === 'in_use' ? 'disabled' : ''}>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          Delete
        </button>
      </div>
    `;
    
    row.querySelector('.action-edit').onclick = () => openEditModal(inst);
    row.querySelector('.action-delete').onclick = () => deleteInstance(inst.id, inst.port, status);
    
    // Status Toggle Logic
    row.querySelector('.status-pill').onclick = (e) => toggleStatus(inst.id, status, e);
    
    tableBody.appendChild(row);
  });
}

async function toggleStatus(id, currentStatus, event) {
  event.stopPropagation();
  const nextStatusMap = {
    'available': 'maintenance',
    'maintenance': 'available',
    'in_use': 'available' // Usually manual unlock
  };
  const nextStatus = nextStatusMap[currentStatus] || 'available';
  
  if (currentStatus === 'in_use') {
    if (!confirm('This instance is currently IN USE. Are you sure you want to force it to Available?')) return;
  }

  showLoading(true);
  try {
    const res = await fetch(`${API_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: nextStatus })
    });
    if (!res.ok) throw new Error('Failed to update status');
    const data = await res.json();
    
    if (data.sync_ok === false) {
      alert(`⚠️ Status updated in database, but FAILED to sync with the DMS instance.\n\nError: ${data.sync_msg}\n\nPlease check network connectivity or internal tokens.`);
    }
    
    await loadInstances();
  } catch (err) {
    alert(err.message);
  } finally {
    showLoading(false);
  }
}

async function testConnection(urlFieldId, btnId) {
  const url = document.getElementById(urlFieldId).value.trim();
  const btn = document.getElementById(btnId);
  if (!url) return alert('Please enter a URL first.');
  
  btn.textContent = 'Testing...';
  btn.className = 'test-btn';

  const endpoint = urlFieldId === 'internal_url' ? '/api/admin/test-sync' : '/api/admin/test-connection';

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    
    if (data.status === 'ok') {
      btn.textContent = 'Success';
      btn.classList.add('success');
    } else {
      btn.textContent = 'Failed';
      btn.classList.add('error');
      console.error('Connection test failed:', data.detail);
    }
  } catch (err) {
    btn.textContent = 'Error';
    btn.classList.add('error');
  }
  
  setTimeout(() => {
    btn.textContent = 'Test';
    btn.className = 'test-btn';
  }, 3000);
}

// ─── Modal Logic ─────────────────────────────────────────────────────────────
function openAddModal() {
  modalTitle.textContent = 'Add New Instance';
  instanceForm.reset();
  fieldId.value = '';
  modal.classList.add('active');
}

function openEditModal(inst) {
  modalTitle.textContent = `Edit Configuration : ${inst.port}`;
  fieldId.value = inst.id;
  fieldPort.value = inst.port;
  fieldUrl.value = inst.url;
  fieldInternalUrl.value = inst.internal_url || '';
  modal.classList.add('active');
}

function closeModal() {
  modal.classList.remove('active');
}

// ─── Actions ──────────────────────────────────────────────────────────────────
instanceForm.onsubmit = async (e) => {
  e.preventDefault();
  const id = fieldId.value;
  const payload = {
    port: fieldPort.value.trim(),
    url: fieldUrl.value.trim(),
    internal_url: fieldInternalUrl.value.trim() || null
  };
  
  showLoading(true);
  try {
    let res;
    if (id) {
      res = await fetch(`${API_ADMIN}/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch(API_ADMIN, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }
    
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Save failed');
    }

    const data = await res.json();
    if (data.sync_ok === false) {
      alert(`⚠️ Instance updated, but FAILED to sync new passwords with the DMS instance.\n\nError: ${data.sync_msg}\n\nYour changes might not be effective on the DMS side.`);
    }
    
    closeModal();
    await loadInstances();
  } catch (err) {
    alert(err.message);
  } finally {
    showLoading(false);
  }
};

async function deleteInstance(id, port, status) {
  if (status === 'in_use') {
    alert(`Cannot delete instance ${port} because it is currently IN USE. Please free it first.`);
    return;
  }
  if (!confirm(`Are you sure you want to remove Instance ${port}?`)) return;
  
  showLoading(true);
  try {
    const res = await fetch(`${API_ADMIN}/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Delete failed');
    await loadInstances();
  } catch (err) {
    alert(err.message);
  } finally {
    showLoading(false);
  }
}

function showLoading(show) {
  loading.style.display = show ? 'flex' : 'none';
}

// ─── Event Listeners ──────────────────────────────────────────────────────────
btnAdd.onclick = openAddModal;
modalCancel.onclick = closeModal;
window.onclick = (e) => { if (e.target === modal) closeModal(); };

btnTestPublic.onclick = () => testConnection('url', 'btnTestPublic');
btnTestInternal.onclick = () => testConnection('internal_url', 'btnTestInternal');

// Init
init();
