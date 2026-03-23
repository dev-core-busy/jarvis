/**
 * Jarvis Vision Manager – Settings-Tab für Gesichtserkennung
 * Verwaltet Dashboard, Training, Profile, Aktionen und Kamera-Einstellungen.
 *
 * Training-Flow (Wizard):
 *   1. Klick "Neues Gesicht trainieren" → Kamera startet automatisch
 *   2. Warten auf Gesichtserkennung → Overlay zeigt Status
 *   3. Gesicht erkannt → "Training starten" Button (OHNE Name)
 *   4. Training laeuft mit Fortschrittsbalken (capturing → encoding → done)
 *   5. Name eingeben + Aktion konfigurieren + Speichern
 */
class JarvisVisionManager {
    constructor() {
        this._token = () => localStorage.getItem('jarvis_token') || '';
        this._hdr  = () => ({ 'Authorization': `Bearer ${this._token()}`, 'Content-Type': 'application/json' });
        this._polling = null;       // Status-Polling (setInterval)
        this._trainingPoll = null;  // Training-Polling (setInterval)
        this._feedActive = false;   // Feed laeuft?
        this._feedFrame = 0;        // Frame-Zaehler
        this._feedInterval = null;  // Feed setInterval-Handle
        this._editProfileId = null;
        this._wizardDetectPoll = null;  // Polling: Gesicht suchen im Wizard
        this._lastLogState = null;      // Letzter Log-Status (Duplikat-Vermeidung)
        this._lastFaceKey = '';         // Letzte erkannte Gesichter (Duplikat-Vermeidung)
    }

    /* ── Lifecycle ──────────────────────────────────────────────────── */

    async refresh() {
        console.log('[Vision] refresh()');
        this._bindEvents();

        // Feed SOFORT starten
        this._startFeed();

        // Status-Polling starten
        clearInterval(this._polling);
        this._polling = setInterval(() => this._fetchStatus(), 2000);

        // Daten laden (parallel)
        this._loadConfig();
        this._fetchStatus();
        this._fetchProfiles();
    }

    stop() {
        console.log('[Vision] stop()');
        clearInterval(this._polling);
        this._polling = null;
        clearInterval(this._trainingPoll);
        this._trainingPoll = null;
        clearInterval(this._wizardDetectPoll);
        this._wizardDetectPoll = null;
        this._stopFeed();
    }

    /* ── Feed-Steuerung ────────────────────────────────────────────── */

    _startFeed() {
        console.log('[Vision] _startFeed()');
        this._feedActive = true;
        this._feedFrame = 0;
        this._showFeedImage(true);
        clearInterval(this._feedInterval);
        this._feedInterval = setInterval(() => this._feedTick(), 300);
        this._feedTick();
    }

    _stopFeed() {
        console.log('[Vision] _stopFeed(), frames:', this._feedFrame);
        this._feedActive = false;
        clearInterval(this._feedInterval);
        this._feedInterval = null;
        this._showFeedImage(false);
    }

    _showFeedImage(show) {
        const img = document.getElementById('vis-feed-img');
        const ph = document.getElementById('vis-feed-placeholder');
        if (img) img.style.display = show ? 'block' : 'none';
        if (ph) ph.style.display = show ? 'none' : 'flex';
    }

    _feedTick() {
        if (!this._feedActive) return;
        const img = document.getElementById('vis-feed-img');
        if (!img) return;
        const token = encodeURIComponent(this._token());
        if (!token) return;
        const newImg = new Image();
        newImg.onload = () => {
            img.src = newImg.src;
            this._showFeedImage(true);
            this._feedFrame++;
        };
        newImg.onerror = () => {
            // Kein Frame verfuegbar – Platzhalter zeigen
            this._showFeedImage(false);
            const ph = document.getElementById('vis-feed-placeholder');
            if (ph) ph.textContent = 'Kein Kamerabild verfügbar';
        };
        newImg.src = `/api/vision/snapshot?t=${Date.now()}&token=${token}`;
    }

    /* ── Log ──────────────────────────────────────────────────────── */

    _visLog(msg, level = 'info') {
        const el = document.getElementById('vis-log');
        if (!el) return;
        const now = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const entry = document.createElement('div');
        entry.className = `vis-log-entry ${level}`;
        entry.innerHTML = `<span class="vis-log-time">${now}</span>${msg}`;
        el.appendChild(entry);
        // Max 100 Eintraege
        while (el.children.length > 100) el.removeChild(el.firstChild);
        el.scrollTop = el.scrollHeight;
    }

    _clearVisLog() {
        const el = document.getElementById('vis-log');
        if (el) el.innerHTML = '';
    }

    /* ── Event-Binding ──────────────────────────────────────────────── */

    _bindEvents() {
        // Start / Stop Toggle
        const btnToggle = document.getElementById('vis-btn-toggle');
        if (btnToggle) btnToggle.onclick = () => this._toggleEngine();

        // Log leeren
        const btnClearLog = document.getElementById('vis-btn-clear-log');
        if (btnClearLog) btnClearLog.onclick = () => this._clearVisLog();

        // Training Wizard
        const btnTrainNew = document.getElementById('vis-btn-train-new');
        if (btnTrainNew) btnTrainNew.onclick = () => this._startWizard();

        const btnWizardCancel = document.getElementById('vis-wizard-cancel');
        if (btnWizardCancel) btnWizardCancel.onclick = () => this._cancelWizard();

        const btnWizardConfirm = document.getElementById('vis-wizard-confirm');
        if (btnWizardConfirm) btnWizardConfirm.onclick = () => this._confirmWizardTraining();

        const btnWizardSave = document.getElementById('vis-wizard-save');
        if (btnWizardSave) btnWizardSave.onclick = () => this._saveWizardAction();

        const wizardActionSelect = document.getElementById('vis-wizard-action');
        if (wizardActionSelect) wizardActionSelect.onchange = () => this._onWizardActionChange();

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

        // Aktions-Typ wechseln
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

    /* ── Status-Polling ─────────────────────────────────────────────── */

    async _fetchStatus() {
        const data = await this._api('/status');
        if (data.error) {
            if (this._lastLogState !== 'error') {
                this._visLog('Engine nicht erreichbar: ' + data.error, 'error');
                this._lastLogState = 'error';
            }
            this._setStatusBadge('offline', 'Nicht verfuegbar');
            return;
        }

        if (data.running) {
            const fps = data.fps || 0;
            const extra = this._feedFrame > 0 ? ` · F:${this._feedFrame}` : '';
            this._setStatusBadge('live', `Live · ${fps} FPS${extra}`);

            if (this._lastLogState !== 'running') {
                this._visLog(`Engine gestartet (${fps} FPS)`, 'success');
                this._lastLogState = 'running';
            }

            // Kein Frame verfuegbar (Kamera offline)
            if (fps === 0 && this._lastLogState !== 'no_frame') {
                this._visLog('Kein Kamerabild – Stream nicht erreichbar', 'warn');
                this._lastLogState = 'no_frame';
            } else if (fps > 0) {
                this._lastLogState = 'running';
            }

            // Fallback: Bild direkt setzen
            if (this._feedActive) {
                const img = document.getElementById('vis-feed-img');
                if (img) {
                    const token = encodeURIComponent(this._token());
                    img.src = `/api/vision/snapshot?t=${Date.now()}&token=${token}`;
                    if (this._feedFrame === 0) this._feedFrame = 1;
                }
            }
        } else {
            if (this._lastLogState !== 'stopped') {
                this._visLog('Engine gestoppt', 'info');
                this._lastLogState = 'stopped';
            }
            this._setStatusBadge('offline', 'Gestoppt');
            this._showFeedImage(false);
        }

        // Erkannte Gesichter – Änderungen loggen
        const faces = data.current_faces || [];
        const faceKey = faces.map(f => f.name).sort().join(',');
        if (faceKey !== this._lastFaceKey && faceKey) {
            const names = faces.map(f => {
                const conf = f.confidence ? ` (${(f.confidence * 100).toFixed(0)}%)` : '';
                return f.name + conf;
            }).join(', ');
            this._visLog(`Erkannt: ${names}`, 'success');
        } else if (!faceKey && this._lastFaceKey) {
            this._visLog('Keine Gesichter mehr erkannt', 'info');
        }
        this._lastFaceKey = faceKey;

        this._renderDetectedFaces(faces);

        // Training-Fortschritt (falls aktiv)
        if (data.training && data.training.active) {
            this._renderTrainingProgress(data.training);
        }
    }

    _setStatusBadge(state, text) {
        const dot = document.getElementById('vis-status-dot');
        const label = document.getElementById('vis-status-text');
        const btn = document.getElementById('vis-btn-toggle');
        if (dot) {
            dot.className = 'vis-status-dot';
            dot.classList.add(state === 'live' ? 'vis-dot-on' : 'vis-dot-off');
        }
        if (label) label.textContent = text;
        if (btn) {
            btn.textContent = state === 'live' ? 'Stoppen' : 'Starten';
            btn.classList.toggle('vis-btn-active', state === 'live');
        }
    }

    _renderDetectedFaces(faces) {
        const el = document.getElementById('vis-detected-faces');
        if (!el) return;
        if (!faces.length) {
            el.innerHTML = '<span class="vis-no-faces">Keine Gesichter erkannt</span>';
            return;
        }
        const token = encodeURIComponent(this._token());
        el.innerHTML = faces.map((f, i) => {
            const conf = f.confidence ? `${(f.confidence * 100).toFixed(0)}%` : '';
            const icon = f.name === 'Unbekannt' ? '👤' : '✅';
            const cropUrl = `/api/vision/face-crop/${i}?t=${Date.now()}&token=${token}`;
            return `<div class="vis-face-badge">
                <img class="vis-face-crop" src="${cropUrl}"
                     onerror="this.style.display='none'" />
                <span>${icon} ${this._esc(f.name)} <small>${conf}</small></span>
            </div>`;
        }).join('');
    }

    /* ── Konfiguration laden ──────────────────────────────────────── */

    async _loadConfig() {
        try {
            const resp = await fetch('/api/skills/vision/config', { headers: this._hdr() });
            if (!resp.ok) return;
            const data = await resp.json();
            const cfg = data.config || {};

            const urlInput = document.getElementById('vis-cam-url');
            const camSelect = document.getElementById('vis-cam-select');
            if (cfg.camera_source && cfg.camera_source !== '0') {
                if (cfg.camera_source.startsWith('http') || cfg.camera_source.startsWith('rtsp')) {
                    if (urlInput) urlInput.value = cfg.camera_source;
                    // Dropdown deaktivieren wenn URL gesetzt (URL hat Vorrang)
                    if (camSelect) {
                        camSelect.disabled = true;
                        camSelect.title = 'URL-Feld hat Vorrang';
                    }
                } else {
                    if (camSelect) camSelect.value = cfg.camera_source;
                }
            }

            // URL-Feld Listener: Dropdown deaktivieren wenn URL eingegeben
            if (urlInput && camSelect) {
                urlInput.addEventListener('input', () => {
                    const hasUrl = urlInput.value.trim().length > 0;
                    camSelect.disabled = hasUrl;
                    camSelect.title = hasUrl ? 'URL-Feld hat Vorrang' : '';
                });
            }

            const model = document.getElementById('vis-set-model');
            if (model && cfg.detection_model) model.value = cfg.detection_model;
            const tol = document.getElementById('vis-set-tolerance');
            if (tol && cfg.tolerance != null) tol.value = cfg.tolerance;
            const intv = document.getElementById('vis-set-interval');
            if (intv && cfg.recognition_interval != null) intv.value = cfg.recognition_interval;
            const samp = document.getElementById('vis-set-samples');
            if (samp && cfg.training_samples != null) samp.value = cfg.training_samples;
            const auto = document.getElementById('vis-set-autostart');
            if (auto) auto.checked = !!cfg.auto_start;
        } catch (e) {
            // Config nicht ladbar
        }
    }

    _getActiveSource() {
        const urlInput = document.getElementById('vis-cam-url');
        const urlVal = urlInput?.value?.trim();
        if (urlVal) return urlVal;
        return document.getElementById('vis-cam-select')?.value || '0';
    }

    /* ── Engine-Steuerung ───────────────────────────────────────────── */

    async _toggleEngine() {
        const dot = document.getElementById('vis-status-dot');
        const isRunning = dot && dot.classList.contains('vis-dot-on');
        await this._controlEngine(isRunning ? 'stop' : 'start');
    }

    async _controlEngine(action) {
        const source = this._getActiveSource();
        this._visLog(`${action === 'start' ? 'Starte' : 'Stoppe'} Engine...`, 'info');
        const data = await this._api('/control', {
            method: 'POST',
            body: JSON.stringify({ action, source }),
        });
        if (data.error) {
            this._visLog(`Fehler: ${data.error}`, 'error');
        } else {
            this._visLog(data.message || `Engine ${action}`, 'success');
        }
        this._notify(data.message || data.error || action);
        await this._fetchStatus();
    }

    /* ══════════════════════════════════════════════════════════════════
       Training Wizard – Neuer Flow
       ══════════════════════════════════════════════════════════════════ */

    async _startWizard() {
        const wizard = document.getElementById('vis-wizard');
        if (!wizard) return;

        // UI: Wizard anzeigen, Button verstecken
        wizard.style.display = '';
        const btnNew = document.getElementById('vis-btn-train-new');
        if (btnNew) btnNew.style.display = 'none';

        // Schritt 1: Gesicht suchen
        this._setWizardStep('detect');

        // Engine starten wenn noetig
        const dot = document.getElementById('vis-status-dot');
        if (dot && dot.classList.contains('vis-dot-off')) {
            this._notify('Starte Kamera...');
            await this._controlEngine('start');
            await new Promise(r => setTimeout(r, 2000));
        }

        // Polling: Gesicht suchen
        clearInterval(this._wizardDetectPoll);
        this._wizardDetectPoll = setInterval(() => this._wizardCheckFace(), 800);
    }

    async _wizardCheckFace() {
        const data = await this._api('/status');
        if (data.error) return;

        const faces = data.current_faces || [];
        if (faces.length > 0) {
            // Gesicht gefunden! Polling stoppen
            clearInterval(this._wizardDetectPoll);
            this._wizardDetectPoll = null;

            // Face-Crop anzeigen
            const token = encodeURIComponent(this._token());
            const cropImg = document.getElementById('vis-wizard-crop');
            if (cropImg) {
                cropImg.src = `/api/vision/face-crop/0?t=${Date.now()}&token=${token}`;
            }

            // Schritt 2: Name eingeben
            this._setWizardStep('name');

            // Focus auf Name-Input
            setTimeout(() => {
                const nameInput = document.getElementById('vis-wizard-name');
                if (nameInput) nameInput.focus();
            }, 200);
        }
    }

    _setWizardStep(step) {
        const steps = ['detect', 'name', 'progress', 'action'];
        for (const s of steps) {
            const el = document.getElementById(`vis-wizard-step-${s}`);
            if (el) el.style.display = s === step ? '' : 'none';
        }
    }

    async _confirmWizardTraining() {
        try {
            // Temp-Name generieren (Name wird NACH Training vergeben)
            const tempName = '_training_' + Date.now();
            this._tempTrainingName = tempName;

            const samplesEl = document.getElementById('vis-set-samples');
            const samples = parseInt(samplesEl?.value) || 30;

            // SOFORT visuelles Feedback
            this._setWizardStep('progress');

            const bar = document.getElementById('vis-train-progress');
            const text = document.getElementById('vis-train-progress-text');
            const wrap = bar?.closest('.vis-progress-wrap');

            if (bar) { bar.style.width = '5%'; bar.classList.add('vis-progress-pulse'); }
            if (text) text.textContent = 'Starte Training...';
            if (wrap) wrap.style.display = '';
            this._notify('Training gestartet – bitte in die Kamera schauen...');

            const data = await this._api('/training/start', {
                method: 'POST',
                body: JSON.stringify({ name: tempName, samples }),
            });

            if (data.error) {
                this._notify(data.error, 'error');
                this._setWizardStep('name');
                return;
            }

            // Training-Polling starten
            clearInterval(this._trainingPoll);
            this._trainingPoll = setInterval(() => this._pollTraining(), 500);
        } catch (e) {
            alert('Training-Fehler: ' + e.message);
        }
    }

    _cancelWizard() {
        clearInterval(this._wizardDetectPoll);
        this._wizardDetectPoll = null;
        clearInterval(this._trainingPoll);
        this._trainingPoll = null;

        const wizard = document.getElementById('vis-wizard');
        if (wizard) wizard.style.display = 'none';
        const btnNew = document.getElementById('vis-btn-train-new');
        if (btnNew) btnNew.style.display = '';

        // Inputs leeren
        const nameInput = document.getElementById('vis-wizard-name');
        if (nameInput) nameInput.value = '';
        const actionVal = document.getElementById('vis-wizard-action-value');
        if (actionVal) actionVal.value = '';
        const actionSel = document.getElementById('vis-wizard-action');
        if (actionSel) actionSel.value = 'log';

        // Temp-Profil löschen falls abgebrochen
        if (this._tempTrainingName) {
            this._api(`/profile/${encodeURIComponent(this._tempTrainingName)}`, { method: 'DELETE' });
            this._tempTrainingName = null;
        }

        // Evtl. laufendes Training stoppen
        this._api('/training/stop', { method: 'POST' });
    }

    /* ── Wizard Schritt 4: Aktion konfigurieren + Speichern ──────── */

    _onWizardActionChange() {
        const sel = document.getElementById('vis-wizard-action');
        const wrap = document.getElementById('vis-wizard-action-value-wrap');
        const input = document.getElementById('vis-wizard-action-value');
        if (!sel || !wrap) return;

        const type = this._actionValueType(sel.value);
        if (type === 'none') {
            wrap.style.display = 'none';
        } else {
            wrap.style.display = '';
            if (input) {
                input.placeholder = type === 'url' ? 'https://example.com/webhook' : 'z.B. Hallo {name}!';
            }
        }
    }

    async _saveWizardAction() {
        const nameInput = document.getElementById('vis-wizard-name');
        const name = nameInput?.value?.trim();
        if (!name) {
            this._notify('Bitte einen Namen eingeben.', 'error');
            if (nameInput) nameInput.focus();
            return;
        }

        const newName = name.toLowerCase().replace(/\s+/g, '_');
        const tempName = this._tempTrainingName || '';

        // Temp-Profil auf echten Namen umbenennen
        if (tempName) {
            const renameData = await this._api('/profiles/rename', {
                method: 'POST',
                body: JSON.stringify({ old_name: tempName, new_name: newName }),
            });
            if (renameData.error) {
                this._notify(renameData.error, 'error');
                return;
            }
        }

        // Aktion setzen
        const actionSel = document.getElementById('vis-wizard-action');
        const actionValInput = document.getElementById('vis-wizard-action-value');
        const action = actionSel?.value || 'log';
        const actionValue = actionValInput?.value || '';

        await this._api('/profiles', {
            method: 'POST',
            body: JSON.stringify({ name: newName, action, action_value: actionValue }),
        });

        this._notify(`"${name}" gespeichert!`);
        this._tempTrainingName = null;
        await this._fetchProfiles();

        // Wizard schliessen
        this._cancelWizard();
    }

    async _pollTraining() {
        const data = await this._api('/training/status');
        if (data.error) return;
        this._renderTrainingProgress(data);

        // Wenn Training fertig → Schritt 4 (Name + Aktion)
        if (data.phase === 'done' && this._trainingPoll) {
            clearInterval(this._trainingPoll);
            this._trainingPoll = null;

            const title = document.getElementById('vis-wizard-done-title');
            if (title) title.textContent = 'Training abgeschlossen!';

            this._setWizardStep('action');

            // Focus auf Name-Input
            setTimeout(() => {
                const nameInput = document.getElementById('vis-wizard-name');
                if (nameInput) nameInput.focus();
            }, 200);
        }

        // Falls Backend idle zurückgesetzt hat ohne done (Fallback)
        if (!data.active && data.phase === 'idle' && this._trainingPoll) {
            clearInterval(this._trainingPoll);
            this._trainingPoll = null;
            this._setWizardStep('action');
        }
    }

    _renderTrainingProgress(t) {
        const bar = document.getElementById('vis-train-progress');
        const text = document.getElementById('vis-train-progress-text');
        const wrap = bar?.closest('.vis-progress-wrap');
        if (!bar || !text || !wrap) return;

        const phase = t.phase || 'idle';

        // Temp-Name nicht anzeigen
        const displayName = (t.name && !t.name.startsWith('_training_')) ? t.name + ': ' : '';

        if (phase === 'capturing') {
            const pct = t.total > 0 ? Math.round((t.progress / t.total) * 100) : 0;
            bar.style.width = `${pct}%`;
            bar.classList.remove('vis-progress-pulse');
            text.textContent = `${displayName}${t.progress}/${t.total} Aufnahmen (${pct}%)`;
            wrap.style.display = '';
        } else if (phase === 'encoding') {
            bar.style.width = '100%';
            bar.classList.add('vis-progress-pulse');
            text.textContent = `${displayName}Berechne Gesichtsdaten...`;
            wrap.style.display = '';
        } else if (phase === 'done') {
            bar.style.width = '100%';
            bar.classList.remove('vis-progress-pulse');
            text.textContent = `\u2705 Training abgeschlossen! ${t.result || ''}`;
            wrap.style.display = '';
        } else {
            bar.style.width = '0%';
            bar.classList.remove('vis-progress-pulse');
            text.textContent = '';
            wrap.style.display = 'none';
        }
    }

    /* ── Profile ────────────────────────────────────────────────────── */

    async _fetchProfiles() {
        const data = await this._api('/profiles');
        if (data.error) return;
        this._availableActions = data.actions || [];
        this._renderProfilesList(data.profiles || [], data.actions || []);
    }

    _renderProfilesList(profiles, actions) {
        const el = document.getElementById('vis-profiles-list');
        if (!el) return;

        if (!profiles.length) {
            el.innerHTML = '<div class="vis-empty">Noch keine Gesichter trainiert.</div>';
            return;
        }

        actions = actions || this._availableActions || [];
        const token = encodeURIComponent(this._token());

        el.innerHTML = profiles.map(p => {
            const date = p.created_at ? new Date(p.created_at).toLocaleDateString('de-DE') : '';

            // Aktions-Dropdown
            const options = actions.map(a =>
                `<option value="${a.id}" ${a.id === p.action ? 'selected' : ''}>${this._esc(a.label)}</option>`
            ).join('');

            // Aktions-Wert (URL/Prompt/nichts)
            const valueType = this._actionValueType(p.action);
            const valueField = valueType === 'url'
                ? `<input type="url" class="vis-input vis-action-value" data-profile="${p.id}" value="${this._esc(p.action_value || '')}" placeholder="https://example.com/webhook" />`
                : valueType === 'prompt'
                ? `<textarea class="vis-input vis-action-value" data-profile="${p.id}" rows="2" placeholder="z.B. Hallo {name}! oder LLM-Prompt...">${this._esc(p.action_value || '')}</textarea>`
                : '';

            // Lautsprecher-Auswahl bei "greet"
            const greetTarget = p.greet_target || 'browser';
            const greetSelect = p.action === 'greet'
                ? `<div class="vis-greet-target-wrap" id="vis-gt-${p.id}">
                       <label style="font-size:0.8rem;color:var(--text-secondary);">Ausgabe:</label>
                       <select class="vis-select vis-greet-target" data-profile="${p.id}">
                           <option value="browser" ${greetTarget === 'browser' ? 'selected' : ''}>🔊 Browser (TTS)</option>
                           <option value="server" ${greetTarget === 'server' ? 'selected' : ''}>🖥️ Server (espeak)</option>
                       </select>
                   </div>`
                : '';

            // Test-Button nur bei greet-Aktion
            const testBtn = p.action === 'greet'
                ? `<button class="vis-btn-sm vis-btn-test" id="vis-test-${p.id}" onclick="visionManager._testGreetAudio('${p.id}')" title="Audio testen">🔊</button>`
                : `<button class="vis-btn-sm vis-btn-test" id="vis-test-${p.id}" onclick="visionManager._testGreetAudio('${p.id}')" title="Audio testen" style="display:none">🔊</button>`;

            return `
                <div class="vis-profile-item">
                    <div class="vis-profile-header">
                        <img class="vis-profile-thumb" src="/api/vision/thumbnail/${encodeURIComponent(p.id)}?t=${Date.now()}&token=${token}"
                             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2250%22 height=%2250%22><rect fill=%22%23333%22 width=%2250%22 height=%2250%22/><text x=%2225%22 y=%2232%22 text-anchor=%22middle%22 fill=%22%23888%22 font-size=%2220%22>?</text></svg>'" />
                        <div class="vis-profile-info">
                            <strong>${this._esc(p.name)}</strong>
                            <small>${p.num_images} Bilder · ${date}</small>
                        </div>
                        <div class="vis-profile-actions">
                            <button class="vis-btn-sm" onclick="visionManager._editProfile('${p.id}')" title="Bearbeiten">✏</button>
                            <button class="vis-btn-sm vis-btn-danger" onclick="visionManager._deleteProfile('${p.id}')" title="Löschen">✕</button>
                        </div>
                    </div>
                    <div class="vis-profile-action-config">
                        <select class="vis-select vis-action-select" data-profile="${p.id}" onchange="visionManager._onInlineActionChange(this)">
                            ${options}
                        </select>
                        <div class="vis-action-value-wrap" id="vis-av-${p.id}">${valueField}</div>
                        ${greetSelect}
                        ${testBtn}
                        <button class="vis-btn-sm vis-btn-primary" onclick="visionManager._saveInlineAction('${p.id}')">💾</button>
                    </div>
                </div>`;
        }).join('');
    }

    _onInlineActionChange(selectEl) {
        const pid = selectEl.dataset.profile;
        const action = selectEl.value;
        const type = this._actionValueType(action);
        const wrap = document.getElementById(`vis-av-${pid}`);
        if (!wrap) return;
        if (type === 'url') {
            wrap.innerHTML = `<input type="url" class="vis-input vis-action-value" data-profile="${pid}" placeholder="https://example.com/webhook" />`;
        } else if (type === 'prompt') {
            wrap.innerHTML = `<textarea class="vis-input vis-action-value" data-profile="${pid}" rows="2" placeholder="z.B. Hallo {name}! oder LLM-Prompt..."></textarea>`;
        } else {
            wrap.innerHTML = '';
        }

        // Lautsprecher-Auswahl: anzeigen/verbergen bei greet
        let gtWrap = document.getElementById(`vis-gt-${pid}`);
        if (action === 'greet') {
            if (!gtWrap) {
                gtWrap = document.createElement('div');
                gtWrap.className = 'vis-greet-target-wrap';
                gtWrap.id = `vis-gt-${pid}`;
                gtWrap.innerHTML = `
                    <label style="font-size:0.8rem;color:var(--text-secondary);">Ausgabe:</label>
                    <select class="vis-select vis-greet-target" data-profile="${pid}">
                        <option value="browser" selected>🔊 Browser (TTS)</option>
                        <option value="server">🖥️ Server (espeak)</option>
                    </select>`;
                wrap.parentNode.insertBefore(gtWrap, wrap.nextSibling?.nextSibling || null);
            }
        } else if (gtWrap) {
            gtWrap.remove();
        }

        // Test-Button: anzeigen/verbergen bei greet
        const testBtn = document.getElementById(`vis-test-${pid}`);
        if (testBtn) {
            testBtn.style.display = action === 'greet' ? '' : 'none';
        }
    }

    async _saveInlineAction(profileId) {
        const select = document.querySelector(`.vis-action-select[data-profile="${profileId}"]`);
        const valueEl = document.querySelector(`.vis-action-value[data-profile="${profileId}"]`);
        const greetTargetEl = document.querySelector(`.vis-greet-target[data-profile="${profileId}"]`);
        const action = select?.value || 'log';
        const actionValue = valueEl?.value || '';
        const greetTarget = greetTargetEl?.value || 'browser';

        const payload = { name: profileId, action, action_value: actionValue };
        if (action === 'greet') {
            payload.greet_target = greetTarget;
        }

        const data = await this._api('/profiles', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        this._notify(data.message || data.error || 'Gespeichert');
    }

    async _testGreetAudio(profileId) {
        const token = encodeURIComponent(this._token());
        const url = `/api/vision/greet-audio/${encodeURIComponent(profileId)}?token=${token}`;

        // Button visuell als "ladend" markieren
        const btn = document.getElementById(`vis-test-${profileId}`);
        const resetBtn = () => { if (btn) { btn.disabled = false; btn.textContent = '🔊'; } };
        if (btn) { btn.disabled = true; btn.textContent = '⏳'; }

        try {
            const audio = new Audio(url);
            audio.onended = resetBtn;
            audio.onerror = () => {
                this._notify('Keine Audio-Datei – bitte erst speichern.', 'error');
                resetBtn();
            };
            await audio.play();
        } catch (e) {
            this._notify('Keine Audio-Datei – bitte erst speichern.', 'error');
            resetBtn();
        }
    }

    _actionLabel(actionId) {
        const map = {
            greet: 'Begrüßung',
            llm: 'An LLM',
            door: 'Tür öffnen',
            webhook: 'Webhook',
            log: 'Loggen',
        };
        return map[actionId] || actionId || 'Loggen';
    }

    _actionValueType(actionId) {
        const map = {
            greet: 'prompt',
            llm: 'prompt',
            door: 'none',
            webhook: 'url',
            log: 'none',
        };
        return map[actionId] || 'none';
    }

    /* ── Profil bearbeiten (Modal) ──────────────────────────────────── */

    _editProfile(profileId) {
        this._editProfileId = profileId;
        const modal = document.getElementById('vis-profile-modal');
        if (!modal) return;

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
        if (!confirm(`Profil '${profileId}' wirklich löschen?`)) return;

        const resp = await fetch(`/api/vision/profile/${encodeURIComponent(profileId)}`, {
            method: 'DELETE',
            headers: this._hdr(),
        });
        const data = await resp.json();
        this._notify(data.message || data.error || 'Gelöscht');
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
        await this._controlEngine('stop');
        await new Promise(r => setTimeout(r, 500));
        await this._controlEngine('start');
    }

    /* ── Einstellungen speichern ─────────────────────────────────────── */

    async _saveSettings() {
        const cfg = {
            detection_model: document.getElementById('vis-set-model')?.value || 'hog',
            tolerance: parseFloat(document.getElementById('vis-set-tolerance')?.value) || 0.6,
            recognition_interval: parseFloat(document.getElementById('vis-set-interval')?.value) || 1.0,
            training_samples: parseInt(document.getElementById('vis-set-samples')?.value) || 30,
            auto_start: document.getElementById('vis-set-autostart')?.checked || false,
            camera_source: this._getActiveSource(),
        };

        const resp = await fetch('/api/skills/vision/config', {
            method: 'POST',
            headers: this._hdr(),
            body: JSON.stringify(cfg),
        });
        const data = await resp.json();
        this._notify(data.success ? 'Einstellungen gespeichert.' : (data.error || 'Fehler'));
    }

    /* ── Stream-Tools Download ─────────────────────────────────────── */

    _downloadStreamTools() {
        // Direkt von jarvis-ai.info herunterladen (kein Backend-Proxy noetig)
        window.open('https://jarvis-ai.info/downloads/jarvis_cam_stream.zip', '_blank');
        this._notify('Download gestartet – ZIP enthält ffmpeg.exe + ffmpeg_stream.ps1');
    }

    /* ── System-Reset ───────────────────────────────────────────────── */

    async _cleanup() {
        if (!confirm('Alle Vision-Daten (Profile, Bilder, Events) wirklich löschen?')) return;

        const data = await this._api('/cleanup', { method: 'POST' });
        this._notify(data.message || data.error || 'Zurückgesetzt');
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
            if (label) label.textContent = type === 'url' ? 'Webhook URL' : 'Text / Prompt';
            if (input) input.placeholder = type === 'url' ? 'https://...' : 'z.B. Hallo {name}!';
        }
    }
}

/* ── Globale Instanz ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    window.visionManager = new JarvisVisionManager();
});
