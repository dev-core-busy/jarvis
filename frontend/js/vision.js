/**
 * Jarvis Vision Manager – Settings-Tab fuer Gesichtserkennung
 * Verwaltet Dashboard, Training, Profile, Aktionen und Kamera-Einstellungen.
 * v1
 */
class JarvisVisionManager {
    constructor() {
        this._token = () => localStorage.getItem('jarvis_token') || '';
        this._hdr  = () => ({ 'Authorization': `Bearer ${this._token()}`, 'Content-Type': 'application/json' });
        this._polling = null;
        this._feedPoll = null;
        this._trainingPoll = null;
        this._editProfileId = null;
    }

    /* ── Lifecycle ──────────────────────────────────────────────────── */

    async refresh() {
        this._bindEvents();
        await this._fetchStatus();
        await this._fetchProfiles();
        this._startPolling();
    }

    stop() {
        clearInterval(this._polling);
        clearInterval(this._feedPoll);
        clearInterval(this._trainingPoll);
        this._polling = null;
        this._feedPoll = null;
        this._trainingPoll = null;
    }

    /* ── Event-Binding ──────────────────────────────────────────────── */

    _bindEvents() {
        // Start / Stop
        const btnStart = document.getElementById('vis-btn-start');
        const btnStop  = document.getElementById('vis-btn-stop');
        if (btnStart) btnStart.onclick = () => this._controlEngine('start');
        if (btnStop)  btnStop.onclick  = () => this._controlEngine('stop');

        // Training
        const btnTrainStart = document.getElementById('vis-btn-train-start');
        const btnTrainStop  = document.getElementById('vis-btn-train-stop');
        if (btnTrainStart) btnTrainStart.onclick = () => this._startTraining();
        if (btnTrainStop)  btnTrainStop.onclick  = () => this._stopTraining();

        // Kamera-Einstellungen
        const btnCamLoad = document.getElementById('vis-btn-cam-load');
        const btnCamApply = document.getElementById('vis-btn-cam-apply');
        if (btnCamLoad)  btnCamLoad.onclick  = () => this._loadCameras();
        if (btnCamApply) btnCamApply.onclick = () => this._applyCamera();

        // Settings speichern
        const btnSaveSettings = document.getElementById('vis-btn-save-settings');
        if (btnSaveSettings) btnSaveSettings.onclick = () => this._saveSettings();

        // System-Reset
        const btnCleanup = document.getElementById('vis-btn-cleanup');
        if (btnCleanup) btnCleanup.onclick = () => this._cleanup();

        // Profil-Modal schliessen
        const btnModalClose = document.getElementById('vis-modal-close');
        const btnModalCancel = document.getElementById('vis-modal-cancel');
        const btnModalSave = document.getElementById('vis-modal-save');
        if (btnModalClose)  btnModalClose.onclick  = () => this._closeModal();
        if (btnModalCancel) btnModalCancel.onclick = () => this._closeModal();
        if (btnModalSave)   btnModalSave.onclick   = () => this._saveProfile();

        // Aktions-Typ wechseln → bedingtes Feld anzeigen
        const actionSelect = document.getElementById('vis-modal-action');
        if (actionSelect) actionSelect.onchange = () => this._onActionTypeChange();
    }

    /* ── API-Aufrufe ────────────────────────────────────────────────── */

    async _api(path, opts = {}) {
        try {
            const resp = await fetch(`/api/vision${path}`, {
                headers: this._hdr(),
                ...opts,
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                return { error: err.error || err.detail || `HTTP ${resp.status}` };
            }
            const ct = resp.headers.get('content-type') || '';
            if (ct.includes('image/')) return resp;
            return await resp.json();
        } catch (e) {
            return { error: e.message };
        }
    }

    /* ── Status + Polling ───────────────────────────────────────────── */

    _startPolling() {
        this.stop(); // Alte Timer loeschen
        this._polling = setInterval(() => this._fetchStatus(), 2000);
        this._feedPoll = setInterval(() => this._updateFeedImage(), 1000);
    }

    async _fetchStatus() {
        const data = await this._api('/status');
        if (data.error) {
            this._setStatusBadge('offline', 'Nicht verfuegbar');
            return;
        }

        // Status-Badge
        if (data.running) {
            this._setStatusBadge('live', `Live · ${data.fps || 0} FPS`);
        } else {
            this._setStatusBadge('offline', 'Gestoppt');
        }

        // Erkannte Gesichter
        this._renderDetectedFaces(data.current_faces || []);

        // Training-Fortschritt
        if (data.training && data.training.active) {
            this._renderTrainingProgress(data.training);
        }
    }

    _setStatusBadge(state, text) {
        const dot = document.getElementById('vis-status-dot');
        const label = document.getElementById('vis-status-text');
        if (dot) {
            dot.className = 'vis-status-dot';
            dot.classList.add(state === 'live' ? 'vis-dot-live' : 'vis-dot-off');
        }
        if (label) label.textContent = text;
    }

    _renderDetectedFaces(faces) {
        const el = document.getElementById('vis-detected-faces');
        if (!el) return;
        if (!faces.length) {
            el.innerHTML = '<span class="vis-no-faces">Keine Gesichter erkannt</span>';
            return;
        }
        el.innerHTML = faces.map(f => {
            const conf = f.confidence ? `${(f.confidence * 100).toFixed(0)}%` : '';
            const icon = f.name === 'Unbekannt' ? '👤' : '✅';
            return `<div class="vis-face-badge">${icon} ${this._esc(f.name)} <small>${conf}</small></div>`;
        }).join('');
    }

    _updateFeedImage() {
        const img = document.getElementById('vis-feed-img');
        if (!img) return;
        const dot = document.getElementById('vis-status-dot');
        if (dot && dot.classList.contains('vis-dot-off')) return;
        img.src = `/api/vision/snapshot?t=${Date.now()}`;
    }

    /* ── Engine-Steuerung ───────────────────────────────────────────── */

    async _controlEngine(action) {
        const source = document.getElementById('vis-cam-select')?.value || '0';
        const data = await this._api('/control', {
            method: 'POST',
            body: JSON.stringify({ action, source }),
        });
        this._notify(data.message || data.error || action);
        await this._fetchStatus();
    }

    /* ── Training ───────────────────────────────────────────────────── */

    async _startTraining() {
        const nameEl = document.getElementById('vis-train-name');
        const samplesEl = document.getElementById('vis-train-samples');
        const name = nameEl?.value?.trim();
        const samples = parseInt(samplesEl?.value) || 30;

        if (!name) {
            this._notify('Bitte einen Namen eingeben.', 'error');
            return;
        }

        const data = await this._api('/training/start', {
            method: 'POST',
            body: JSON.stringify({ name, samples }),
        });
        this._notify(data.message || data.error);

        // Training-Polling starten
        clearInterval(this._trainingPoll);
        this._trainingPoll = setInterval(() => this._pollTraining(), 1000);
    }

    async _stopTraining() {
        const data = await this._api('/training/stop', { method: 'POST' });
        this._notify(data.message || data.error);
        clearInterval(this._trainingPoll);
        this._trainingPoll = null;
        this._renderTrainingProgress({ active: false, progress: 0, total: 0 });
        await this._fetchProfiles();
    }

    async _pollTraining() {
        const data = await this._api('/training/status');
        if (data.error) return;
        this._renderTrainingProgress(data);
        if (!data.active && this._trainingPoll) {
            clearInterval(this._trainingPoll);
            this._trainingPoll = null;
            await this._fetchProfiles();
        }
    }

    _renderTrainingProgress(t) {
        const bar = document.getElementById('vis-train-progress');
        const text = document.getElementById('vis-train-progress-text');
        if (!bar || !text) return;

        if (t.active) {
            const pct = t.total > 0 ? Math.round((t.progress / t.total) * 100) : 0;
            bar.style.width = `${pct}%`;
            text.textContent = `${t.progress}/${t.total} Aufnahmen`;
            bar.parentElement.style.display = '';
        } else {
            bar.style.width = '0%';
            text.textContent = '';
            bar.parentElement.style.display = 'none';
        }
    }

    /* ── Profile ────────────────────────────────────────────────────── */

    async _fetchProfiles() {
        const data = await this._api('/profiles');
        if (data.error) return;
        this._renderProfilesList(data.profiles || []);
        this._renderActionsList(data.profiles || [], data.actions || []);
        this._availableActions = data.actions || [];
    }

    _renderProfilesList(profiles) {
        const el = document.getElementById('vis-profiles-list');
        if (!el) return;

        if (!profiles.length) {
            el.innerHTML = '<div class="vis-empty">Noch keine Gesichter trainiert.</div>';
            return;
        }

        el.innerHTML = profiles.map(p => {
            const date = p.created_at ? new Date(p.created_at).toLocaleDateString('de-DE') : '';
            const actionLabel = this._actionLabel(p.action);
            return `
                <div class="vis-profile-item">
                    <img class="vis-profile-thumb" src="/api/vision/thumbnail/${encodeURIComponent(p.id)}?t=${Date.now()}"
                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2250%22 height=%2250%22><rect fill=%22%23333%22 width=%2250%22 height=%2250%22/><text x=%2225%22 y=%2232%22 text-anchor=%22middle%22 fill=%22%23888%22 font-size=%2220%22>?</text></svg>'" />
                    <div class="vis-profile-info">
                        <strong>${this._esc(p.name)}</strong>
                        <small>${p.num_images} Bilder · ${date}</small>
                        <small>Aktion: ${actionLabel}</small>
                    </div>
                    <div class="vis-profile-actions">
                        <button class="vis-btn-sm" onclick="visionManager._editProfile('${p.id}')" title="Bearbeiten">✏</button>
                        <button class="vis-btn-sm vis-btn-danger" onclick="visionManager._deleteProfile('${p.id}')" title="Loeschen">✕</button>
                    </div>
                </div>`;
        }).join('');
    }

    _renderActionsList(profiles, actions) {
        const el = document.getElementById('vis-actions-list');
        if (!el) return;

        if (!profiles.length) {
            el.innerHTML = '<div class="vis-empty">Zuerst Gesichter trainieren, dann Aktionen festlegen.</div>';
            return;
        }

        el.innerHTML = profiles.map(p => {
            const options = actions.map(a =>
                `<option value="${a.id}" ${a.id === p.action ? 'selected' : ''}>${this._esc(a.label)}</option>`
            ).join('');

            const valueType = this._actionValueType(p.action);
            const valueField = valueType === 'url'
                ? `<input type="url" class="vis-input vis-action-value" data-profile="${p.id}" value="${this._esc(p.action_value || '')}" placeholder="https://example.com/webhook" />`
                : valueType === 'prompt'
                ? `<textarea class="vis-input vis-action-value" data-profile="${p.id}" rows="2" placeholder="Prompt fuer LLM...">${this._esc(p.action_value || '')}</textarea>`
                : '';

            return `
                <div class="vis-action-item">
                    <strong>${this._esc(p.name)}</strong>
                    <select class="vis-select vis-action-select" data-profile="${p.id}" onchange="visionManager._onInlineActionChange(this)">
                        ${options}
                    </select>
                    <div class="vis-action-value-wrap" id="vis-av-${p.id}">${valueField}</div>
                    <button class="vis-btn-sm vis-btn-primary" onclick="visionManager._saveInlineAction('${p.id}')">Speichern</button>
                </div>`;
        }).join('');
    }

    _onInlineActionChange(selectEl) {
        const pid = selectEl.dataset.profile;
        const type = this._actionValueType(selectEl.value);
        const wrap = document.getElementById(`vis-av-${pid}`);
        if (!wrap) return;
        if (type === 'url') {
            wrap.innerHTML = `<input type="url" class="vis-input vis-action-value" data-profile="${pid}" placeholder="https://example.com/webhook" />`;
        } else if (type === 'prompt') {
            wrap.innerHTML = `<textarea class="vis-input vis-action-value" data-profile="${pid}" rows="2" placeholder="Prompt fuer LLM..."></textarea>`;
        } else {
            wrap.innerHTML = '';
        }
    }

    async _saveInlineAction(profileId) {
        const select = document.querySelector(`.vis-action-select[data-profile="${profileId}"]`);
        const valueEl = document.querySelector(`.vis-action-value[data-profile="${profileId}"]`);
        const action = select?.value || 'log';
        const actionValue = valueEl?.value || '';

        const data = await this._api('/profiles', {
            method: 'POST',
            body: JSON.stringify({ name: profileId, action, action_value: actionValue }),
        });
        this._notify(data.message || data.error || 'Gespeichert');
    }

    _actionLabel(actionId) {
        const map = { webhook: 'Webhook', llm: 'LLM', log: 'Loggen' };
        return map[actionId] || actionId || 'Loggen';
    }

    _actionValueType(actionId) {
        const map = { webhook: 'url', llm: 'prompt', log: 'none' };
        return map[actionId] || 'none';
    }

    /* ── Profil bearbeiten (Modal) ──────────────────────────────────── */

    _editProfile(profileId) {
        this._editProfileId = profileId;
        const modal = document.getElementById('vis-profile-modal');
        if (!modal) return;

        // Profil-Daten aus der Liste holen
        const items = document.querySelectorAll('.vis-profile-item');
        let name = profileId;
        for (const item of items) {
            const btn = item.querySelector(`[onclick*="'${profileId}'"]`);
            if (btn) {
                name = item.querySelector('strong')?.textContent || profileId;
                break;
            }
        }

        document.getElementById('vis-modal-name').value = name;
        modal.style.display = 'flex';
    }

    _closeModal() {
        const modal = document.getElementById('vis-profile-modal');
        if (modal) modal.style.display = 'none';
        this._editProfileId = null;
    }

    async _saveProfile() {
        const pid = this._editProfileId;
        if (!pid) return;

        const newName = document.getElementById('vis-modal-name')?.value?.trim();
        if (!newName) {
            this._notify('Name darf nicht leer sein.', 'error');
            return;
        }

        const data = await this._api('/profiles', {
            method: 'POST',
            body: JSON.stringify({ name: pid, display_name: newName }),
        });
        this._notify(data.message || data.error || 'Gespeichert');
        this._closeModal();
        await this._fetchProfiles();
    }

    async _deleteProfile(profileId) {
        if (!confirm(`Profil '${profileId}' wirklich loeschen?`)) return;

        const resp = await fetch(`/api/vision/profile/${encodeURIComponent(profileId)}`, {
            method: 'DELETE',
            headers: this._hdr(),
        });
        const data = await resp.json();
        this._notify(data.message || data.error || 'Geloescht');
        await this._fetchProfiles();
    }

    /* ── Kamera-Einstellungen ───────────────────────────────────────── */

    async _loadCameras() {
        const data = await this._api('/cameras');
        if (data.error) {
            this._notify(data.error, 'error');
            return;
        }

        const select = document.getElementById('vis-cam-select');
        if (!select) return;

        select.innerHTML = (data.cameras || []).map(c =>
            `<option value="${c.index}">${this._esc(c.name)} (${c.device})</option>`
        ).join('');

        if (!data.cameras?.length) {
            select.innerHTML = '<option value="0">Keine Kamera gefunden</option>';
        }

        this._notify(`${(data.cameras || []).length} Kamera(s) gefunden.`);
    }

    async _applyCamera() {
        const select = document.getElementById('vis-cam-select');
        const source = select?.value || '0';
        await this._controlEngine('stop');
        await new Promise(r => setTimeout(r, 500));

        const data = await this._api('/control', {
            method: 'POST',
            body: JSON.stringify({ action: 'start', source }),
        });
        this._notify(data.message || data.error);

        // Preview aktualisieren
        const preview = document.getElementById('vis-cam-preview');
        if (preview) {
            preview.src = `/api/vision/preview/${source}?t=${Date.now()}`;
        }
    }

    /* ── Einstellungen speichern ─────────────────────────────────────── */

    async _saveSettings() {
        const cfg = {
            detection_model: document.getElementById('vis-set-model')?.value || 'hog',
            tolerance: parseFloat(document.getElementById('vis-set-tolerance')?.value) || 0.6,
            recognition_interval: parseFloat(document.getElementById('vis-set-interval')?.value) || 1.0,
            training_samples: parseInt(document.getElementById('vis-set-samples')?.value) || 30,
            auto_start: document.getElementById('vis-set-autostart')?.checked || false,
            camera_source: document.getElementById('vis-cam-select')?.value || '0',
        };

        const resp = await fetch('/api/skills/vision/config', {
            method: 'POST',
            headers: this._hdr(),
            body: JSON.stringify(cfg),
        });
        const data = await resp.json();
        this._notify(data.success ? 'Einstellungen gespeichert.' : (data.error || 'Fehler'));
    }

    /* ── System-Reset ───────────────────────────────────────────────── */

    async _cleanup() {
        if (!confirm('Alle Vision-Daten (Profile, Bilder, Events) wirklich loeschen?')) return;

        const data = await this._api('/cleanup', { method: 'POST' });
        this._notify(data.message || data.error || 'Zurueckgesetzt');
        await this._fetchProfiles();
        await this._fetchStatus();
    }

    /* ── Benachrichtigungen ─────────────────────────────────────────── */

    _notify(msg, type = 'success') {
        const el = document.getElementById('vis-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `vis-notification vis-notification-${type}`;
        el.style.display = 'block';
        clearTimeout(this._notifyTimer);
        this._notifyTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
    }

    /* ── Hilfsfunktionen ────────────────────────────────────────────── */

    _esc(s) {
        if (!s) return '';
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    _onActionTypeChange() {
        const sel = document.getElementById('vis-modal-action');
        const wrap = document.getElementById('vis-modal-value-wrap');
        const input = document.getElementById('vis-modal-value');
        const label = document.getElementById('vis-modal-value-label');
        if (!sel || !wrap) return;

        const type = this._actionValueType(sel.value);
        if (type === 'none') {
            wrap.style.display = 'none';
        } else {
            wrap.style.display = '';
            if (label) label.textContent = type === 'url' ? 'Webhook URL' : 'LLM Prompt';
            if (input) input.placeholder = type === 'url' ? 'https://...' : 'Prompt fuer LLM...';
        }
    }
}

/* ── Globale Instanz ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    window.visionManager = new JarvisVisionManager();
});
