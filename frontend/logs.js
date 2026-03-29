/**
 * DMS Activity Journal — logs.js
 */

const API_LOGS = '/api/logs';
const API_INSTANCES = '/api/instances';

const logsList = document.getElementById('logsList');
const btnRefresh = document.getElementById('btnRefresh');
const filterInstance = document.getElementById('filterInstance');
const filterLimit = document.getElementById('filterLimit');
const btnClearLogs = document.getElementById('btnClearLogs');

async function init() {
  if (localStorage.getItem('dms_monitor_auth') !== 'true') {
    window.location.href = '/';
    return;
  }
  
  // Populate instance filter
  await loadInstanceFilter();
  await loadLogs();

  // Listeners
  btnRefresh.onclick = loadLogs;
  filterInstance.onchange = loadLogs;
  filterLimit.onchange = loadLogs;
  btnClearLogs.onclick = clearLogs;
}

async function loadInstanceFilter() {
    try {
        const res = await fetch(API_INSTANCES);
        if(!res.ok) return;
        const instances = await res.json();
        instances.sort((a,b) => a.id - b.id).forEach(inst => {
            const opt = document.createElement('option');
            opt.value = inst.id;
            opt.textContent = `Instance #${inst.id} (Port ${inst.port})`;
            filterInstance.appendChild(opt);
        });
    } catch(err) {
        console.error("Filter populate error:", err);
    }
}

async function loadLogs() {
  const limit = filterLimit.value;
  const instId = filterInstance.value;

  logsList.innerHTML = '<div style="padding: 40px; text-align: center; color: var(--text-muted);">Refreshing list...</div>';

  let url = `${API_LOGS}?limit=${limit}`;
  if(instId) url += `&instance_id=${instId}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch logs');
    const logs = await res.json();
    renderLogs(logs);
  } catch (err) {
    console.error('Error loading logs:', err);
    logsList.innerHTML = `<div style="padding: 40px; text-align: center; color: #ff5f5f;">Error: ${err.message}</div>`;
  }
}

async function clearLogs() {
    if(!confirm('Are you sure you want to permanently clear the entire activity journal?')) return;
    
    try {
        const res = await fetch(API_LOGS, { method: 'DELETE' });
        if(res.ok) {
            await loadLogs();
        }
    } catch(err) {
        alert('Failed to clear logs: ' + err.message);
    }
}

function renderLogs(logs) {
  if (logs.length === 0) {
    logsList.innerHTML = '<div style="padding: 40px; text-align: center; color: var(--text-muted);">No activity recorded matching these filters.</div>';
    return;
  }

  logsList.innerHTML = logs.map(log => {
      const dateStr = new Date(log.timestamp).toLocaleString('en-US', {
          year: 'numeric', month: 'short', day: '2-digit', 
          hour: '2-digit', minute: '2-digit', second: '2-digit',
          hour12: false
      });

      const instanceName = log.port ? `Port ${log.port}` : (log.instance_id ? `#${log.instance_id}` : 'SYS');
      const assignedTo = log.used_by ? ` — ${log.used_by}` : '';
      const instanceDisplay = `${instanceName}${assignedTo}`;
      const catClass = `cat-${log.category.toLowerCase()}`;

      return `
        <div class="log-item ${catClass}">
            <div class="log-time">${dateStr}</div>
            <div class="log-inst">${instanceDisplay}</div>
            <div class="log-cat">${log.category}</div>
            <div class="log-msg">${escapeHtml(log.message)}</div>
        </div>
      `;
  }).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

init();
