let currentEditId = null;
let availableActions = [];
let currentProfilesData = {};

document.addEventListener('DOMContentLoaded', () => {
    // Event Listeners binden
    const bind = (id, fn) => {
        const el = document.getElementById(id);
        if (el) el.onclick = fn;
    };

    bind('btn-train-start', startTraining);
    bind('btn-train-stop', stopTraining);
    bind('btn-cleanup', cleanupSystem);
    bind('btn-save-name', saveName);
    bind('btn-save-action', saveAction);
    bind('btn-refresh-logs', fetchLogs);

    // Cancel Binding (Fehlertolerant)
    bind('btn-cancel-name', () => {
        const mod = document.getElementById('modal-edit-name');
        if (mod) mod.classList.add('hidden');
    });
    bind('btn-cancel-action', () => {
        const mod = document.getElementById('modal-edit-action');
        if (mod) mod.classList.add('hidden');
    });

    const camSelect = document.getElementById('camera-select');
    if (camSelect) camSelect.onchange = updatePreview;

    // Initialisierung
    updateStatus();
    loadProfiles();
    setInterval(updateStatus, 2000);
});

function showSection(id) {
    document.querySelectorAll('main > section').forEach(s => s.classList.add('hidden'));
    const section = document.getElementById(`section-${id}`);
    if (section) section.classList.remove('hidden');

    document.querySelectorAll('.sidebar nav li').forEach(li => {
        li.classList.remove('active');
        if (li.getAttribute('onclick') && li.getAttribute('onclick').includes(`showSection('${id}')`)) {
            li.classList.add('active');
        }
    });

    if (id === 'settings') refreshCameras();
    if (id === 'logs') fetchLogs();
    if (id === 'profiles' || id === 'actions' || id === 'dashboard') loadProfiles();
}

async function fetchLogs() {
    try {
        const res = await fetch('/api/logs');
        const data = await res.json();
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = data.logs.length ? data.logs.join('<br>') : "Keine Logs vorhanden.";
            container.scrollTop = container.scrollHeight;
        }
    } catch (e) { console.error("Log-Fehler", e); }
}

async function refreshCameras(force = false) {
    try {
        const res = await fetch(`/api/cameras${force ? '?refresh=true' : ''}`);
        const data = await res.json();
        const select = document.getElementById('camera-select');
        if (!select) return;
        select.innerHTML = '';

        data.available.forEach(idx => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.innerText = `Kamera #${idx}`;
            if (idx === data.current) opt.selected = true;
            select.appendChild(opt);
        });

        if (data.available.length === 0) {
            select.innerHTML = '<option>Keine Kamera gefunden</option>';
        } else {
            // Initiales Vorschaubild laden
            updatePreview();
        }

        // Preview bei Änderung aktualisieren
        select.onchange = updatePreview;

    } catch (e) { console.error("Kamera-Liste Fehler", e); }
}

function updatePreview() {
    const select = document.getElementById('camera-select');
    const img = document.getElementById('camera-preview-img');
    const placeholder = document.getElementById('preview-placeholder');

    if (select && select.value !== "" && img && placeholder) {
        // Cache-Busting mit Zeitstempel
        img.src = `/api/camera/preview/${select.value}?t=${new Date().getTime()}`;
        img.onload = () => {
            img.style.display = 'block';
            placeholder.style.display = 'none';
        };
        img.onerror = () => {
            img.style.display = 'none';
            placeholder.style.display = 'flex';
            placeholder.innerText = 'Vorschau nicht verfügbar';
        };
    }
}

async function changeCamera() {
    const select = document.getElementById('camera-select');
    if (!select) return;
    const index = select.value;
    const res = await fetch('/api/camera/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: parseInt(index) })
    });
    const data = await res.json();
    alert(data.status === 'ok' ? "Kamera erfolgreich gewechselt!" : "Fehler beim Kamerawechsel.");
    updateStatus();
}

async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        const nameEl = document.getElementById('detected-name');
        if (nameEl) nameEl.innerText = data.detected_info || "Warten...";

        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        const camInfo = document.getElementById('current-camera');

        if (data.mock_mode) {
            if (dot) dot.style.background = '#f39c12';
            if (text) text.innerText = "Mock-Modus";
            if (camInfo) camInfo.innerText = "Keine Hardware";
        } else {
            if (dot) dot.style.background = '#2ecc71';
            if (text) text.innerText = "Live";
            if (camInfo) camInfo.innerText = `Index #${data.camera_index}`;
        }

        const isTraining = data.training_mode;
        document.body.classList.toggle('training-active', !!isTraining);

        const recDot = document.getElementById('rec-dot');
        const btnStart = document.getElementById('btn-train-start');
        const btnStop = document.getElementById('btn-train-stop');

        if (recDot) recDot.style.display = isTraining ? 'flex' : 'none';
        if (btnStart) btnStart.classList.toggle('hidden', !!isTraining);
        if (btnStop) btnStop.classList.toggle('hidden', !isTraining);

    } catch (e) { console.error("Status Update Fehler", e); }
}

async function loadProfiles() {
    const response = await fetch('/api/profiles');
    const data = await response.json();
    availableActions = data.actions;
    currentProfilesData = data.profiles || {};

    const list = document.getElementById('profile-list-full');
    if (list) {
        list.innerHTML = '';
        // Bestehende Profile
        for (const [id, profile] of Object.entries(data.profiles)) {
            addProfileItem('profile-list-full', id, profile.name, profile.created_at);
        }

        // Unbenannte IDs
        data.unnamed_profiles.forEach(p => {
            addProfileItem('profile-list-full', p.id, `Neu # ${p.id}`, p.created_at);
        });
    }

    // Aktions-Liste aufbauen
    const actionList = document.getElementById('action-list-full');
    if (actionList) {
        actionList.innerHTML = '';
        for (const [id, profile] of Object.entries(data.profiles)) {
            addActionItem('action-list-full', id, profile.name, profile.action, profile.created_at);
        }
    }
}

function addProfileItem(listId, id, name, created_at = "Unbekannt") {
    const item = document.createElement('div');
    item.className = 'profile-item';

    // Fallback SVG
    const fallbackSVG = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='%23666' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z'/></svg>";

    item.innerHTML = `
        <div class="profile-thumbnail">
            <img src="/api/profile/thumbnail/${id}?t=${Date.now()}" onerror="this.src='${fallbackSVG}'" alt="Face">
        </div>
        <div class="profile-info">
            <h4>${name}</h4>
            <span>ID: ${id}</span>
            <div class="profile-date"><small>Erfasst am: ${created_at}</small></div>
        </div>
        <div class="profile-actions">
            <button class="btn secondary small edit-btn">Edit</button>
            <button class="btn danger small delete-btn">✕</button>
        </div>
    `;

    item.querySelector('.edit-btn').onclick = () => openNameModal(id, name);
    item.querySelector('.delete-btn').onclick = () => deleteProfile(id);
    const list = document.getElementById(listId);
    if (list) list.appendChild(item);
}

function addActionItem(listId, id, name, action, created_at) {
    const item = document.createElement('div');
    item.className = 'profile-item';

    const fallbackSVG = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='%23666' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z'/></svg>";

    let actionLabel = action;
    if (availableActions) {
        const actObj = availableActions.find(a => a.id === action);
        if (actObj) actionLabel = actObj.label;
    }

    item.innerHTML = `
        <div class="profile-thumbnail">
            <img src="/api/profile/thumbnail/${id}?t=${Date.now()}" onerror="this.src='${fallbackSVG}'" alt="Face">
        </div>
        <div class="profile-info">
            <h4>${name}</h4>
            <span style="color: var(--accent);">Aktion: ${actionLabel}</span>
        </div>
        <div class="profile-actions">
            <button class="btn secondary small edit-btn">Aktion festlegen</button>
        </div>
    `;

    item.querySelector('.edit-btn').onclick = () => openActionModal(id, name);
    document.getElementById(listId).appendChild(item);
}


async function deleteProfile(id) {
    if (confirm(`Möchten Sie das Profil (ID: ${id}) und alle zugehörigen Trainingsdaten wirklich löschen?`)) {
        try {
            const res = await fetch('/api/profile/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id })
            });
            const data = await res.json();
            if (data.status === 'deleted') {
                loadProfiles();
            }
        } catch (e) { console.error("Lösch-Fehler", e); }
    }
}

function openNameModal(id, currentName) {
    currentEditId = id;
    document.getElementById('modal-name-id-text').innerText = id;
    document.getElementById('edit-name-input').value = currentName.startsWith('Neu #') ? '' : currentName;
    const modal = document.getElementById('modal-edit-name');
    if (modal) modal.classList.remove('hidden');
}

function openActionModal(id, currentName) {
    currentEditId = id;
    document.getElementById('modal-action-name-text').innerText = currentName;

    const select = document.getElementById('edit-action');
    if (!select) return;
    select.innerHTML = '';

    const profile = currentProfilesData[id] || { action: 'log', action_value: '' };
    availableActions.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a.id;
        opt.innerText = a.label;
        if (a.id === profile.action) opt.selected = true;
        select.appendChild(opt);
    });

    document.getElementById('edit-action-value').value = profile.action_value || '';
    updateActionValueVisibility();
    select.onchange = updateActionValueVisibility;

    const modal = document.getElementById('modal-edit-action');
    if (modal) modal.classList.remove('hidden');
}

function updateActionValueVisibility() {
    const select = document.getElementById('edit-action');
    if (!select) return;
    const action = availableActions.find(a => a.id === select.value);
    const group = document.getElementById('action-value-group');
    const label = document.getElementById('action-value-label');

    if (action && action.type !== 'none') {
        if (group) group.classList.remove('hidden');
        if (label) label.innerText = action.type === 'url' ? 'Webhook URL' : 'LLM Prompt';
    } else {
        if (group) group.classList.add('hidden');
    }
}

async function saveName() {
    const profile = currentProfilesData[currentEditId] || { action: 'log', action_value: '' };
    const payload = {
        id: currentEditId,
        name: document.getElementById('edit-name-input').value || `Neu # ${currentEditId}`,
        action: profile.action,
        action_value: profile.action_value
    };

    await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    document.getElementById('modal-edit-name').classList.add('hidden');
    loadProfiles();
}

async function saveAction() {
    const profile = currentProfilesData[currentEditId] || { name: `Neu # ${currentEditId}` };
    const payload = {
        id: currentEditId,
        name: profile.name,
        action: document.getElementById('edit-action').value,
        action_value: document.getElementById('edit-action-value').value
    };

    await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    document.getElementById('modal-edit-action').classList.add('hidden');
    loadProfiles();
}

async function startTraining() {
    const newId = Date.now().toString().slice(-4);
    await fetch('/api/training/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: newId })
    });
}

async function stopTraining() {
    await fetch('/api/training/stop', { method: 'POST' });
    loadProfiles();
}

async function cleanupSystem() {
    if (confirm("Möchten Sie alle Trainingsdaten und Profile löschen?")) {
        await fetch('/api/cleanup', { method: 'POST' });
        loadProfiles();
    }
}
