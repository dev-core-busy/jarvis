/**
 * Jarvis Knowledge Manager – Frontend-Steuerung für Wissen-Tab
 */

class JarvisKnowledgeManager {
    constructor() {
        this._pollInterval = null;

        // Buttons verbinden
        const btnReindex = document.getElementById('btn-kb-reindex');
        const btnAddFolder = document.getElementById('btn-kb-add-folder');

        if (btnReindex) btnReindex.addEventListener('click', () => this.reindex());
        if (btnAddFolder) btnAddFolder.addEventListener('click', () => this.addFolder());

        // Enter-Taste im Eingabefeld
        const folderInput = document.getElementById('kb-folder-input');
        if (folderInput) {
            folderInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this.addFolder();
            });
        }

        // Drag & Drop Upload
        this._initDropZone();
    }

    // ─── Init (wird beim Tab-Wechsel aufgerufen) ──────────────────────

    async init() {
        await this.fetchStats();
        await this.initWebDAV();
        await this.initMounts();
        // Prüfen ob Indizierung gerade läuft (z.B. nach Seiten-Reload)
        await this._checkRunningIndex();
    }

    async _checkRunningIndex() {
        try {
            const resp = await fetch('/api/knowledge/index_progress', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) return;
            const p = await resp.json();
            if (p.running) {
                this._showProgressBar();
                this._updateProgressBar(p);
                this._startProgressPolling();
            }
        } catch (_) {}
    }

    // ─── Drag & Drop Upload ──────────────────────────────────────────

    _initDropZone() {
        const zone = document.getElementById('kb-drop-zone');
        const input = document.getElementById('kb-file-input');
        if (!zone || !input) return;

        // Drag Events
        zone.addEventListener('dragenter', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            if (e.dataTransfer.files.length) this._uploadFiles(e.dataTransfer.files);
        });

        // Klick auf Zone oeffnet Datei-Dialog
        zone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'LABEL') input.click();
        });

        // Datei-Input
        input.addEventListener('change', () => {
            if (input.files.length) this._uploadFiles(input.files);
            input.value = '';
        });
    }

    _getUploadTarget() {
        const sel = document.getElementById('kb-upload-target');
        return sel ? sel.value : 'data/knowledge';
    }

    _populateUploadTargets(folders) {
        const sel = document.getElementById('kb-upload-target');
        if (!sel || !folders) return;
        sel.innerHTML = folders.map(f =>
            `<option value="${f.path}" ${f.path === 'data/knowledge' ? 'selected' : ''}>${f.path}</option>`
        ).join('');
    }

    async _uploadFiles(fileList) {
        const status = document.getElementById('kb-upload-status');
        const folder = this._getUploadTarget();

        if (status) status.textContent = `${fileList.length} Datei(en) werden hochgeladen...`;

        const formData = new FormData();
        formData.append('folder', folder);
        for (const f of fileList) {
            formData.append('files', f);
        }

        try {
            const resp = await fetch('/api/knowledge/upload', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') },
                body: formData,
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const result = await resp.json();

            let msg = `${result.total_saved} Datei(en) hochgeladen`;
            if (result.total_rejected > 0) {
                const names = result.rejected.map(r => r.name).join(', ');
                msg += ` | ${result.total_rejected} abgelehnt: ${names}`;
            }
            if (status) {
                status.textContent = msg;
                status.style.color = result.total_rejected > 0 ? '#f59e0b' : '#10b981';
                setTimeout(() => { status.textContent = ''; status.style.color = ''; }, 5000);
            }
            this._showNotification(msg, result.total_rejected > 0 ? 'warning' : 'success');
            await this.fetchStats();
        } catch (e) {
            if (status) {
                status.textContent = 'Upload fehlgeschlagen: ' + e.message;
                status.style.color = '#ef4444';
            }
            this._showNotification('Upload fehlgeschlagen: ' + e.message, 'error');
        }
    }

    // ─── Stats laden ──────────────────────────────────────────────────

    async fetchStats() {
        const container = document.getElementById('kb-stats-container');
        const folderList = document.getElementById('kb-folder-list');

        try {
            const resp = await fetch('/api/knowledge/stats', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const stats = await resp.json();

            this._renderStats(stats);
            this._renderFolders(stats.folders);
            this._populateUploadTargets(stats.folders);
        } catch (e) {
            if (container) container.innerHTML = `<div class="kb-error">Fehler beim Laden: ${e.message}</div>`;
        }
    }

    _renderStats(stats) {
        const el = document.getElementById('kb-stats-container');
        if (!el) return;

        const sizeMb = (stats.total_size_bytes / (1024 * 1024)).toFixed(1);
        const pdfIcon = stats.pdf_support ? '✅' : '⚠️';
        const docxIcon = stats.docx_support ? '✅' : '⚠️';
        const xlsxIcon = stats.xlsx_support ? '✅' : '⚠️';
        const pptxIcon = stats.pptx_support ? '✅' : '⚠️';
        const pdfTitle = stats.pdf_support ? 'PDF-Support aktiv' : 'pdfplumber nicht installiert';
        const docxTitle = stats.docx_support ? 'Word-Support aktiv (.docx, .doc)' : 'python-docx nicht installiert';
        const xlsxTitle = stats.xlsx_support ? 'Excel-Support aktiv' : 'openpyxl nicht installiert';
        const pptxTitle = stats.pptx_support ? 'PowerPoint-Support aktiv' : 'python-pptx nicht installiert';
        const videoIcon = stats.video_support ? '✅' : '⚠️';
        const videoTitle = stats.video_support ? 'Video/Audio-Support aktiv (ffmpeg + faster-whisper)' : 'ffmpeg oder faster-whisper fehlt';
        const vectorIcon = stats.vector_search ? '✅' : (stats.indexing ? '🔄' : '⚠️');
        const vectorTitle = stats.vector_search
            ? `Vektor-Suche aktiv (${stats.vector_files} Dateien, ${stats.vector_chunks} Chunks)`
            : (stats.indexing ? 'Vektor-Index wird gerade aufgebaut...' : 'chromadb/sentence-transformers nicht installiert');

        // Aktueller Suchmodus
        const mode = stats.search_mode || 'auto';

        el.innerHTML = `
            <div class="kb-stat-grid">
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.total_files}</span>
                    <span class="kb-stat-label">Dateien</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.indexed_files}</span>
                    <span class="kb-stat-label">Indiziert</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.total_chunks}</span>
                    <span class="kb-stat-label">Chunks</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${sizeMb} MB</span>
                    <span class="kb-stat-label">Gesamt</span>
                </div>
            </div>
            <div class="kb-search-mode">
                <span class="kb-search-mode-label">Suchmodus:</span>
                <div class="kb-toggle-group">
                    <button class="kb-toggle-btn ${mode === 'auto' ? 'active' : ''}"
                        data-mode="auto" onclick="window.knowledgeManager.setSearchMode('auto')"
                        title="Vektor-Suche bevorzugt, TF-IDF als Fallback">Auto</button>
                    <button class="kb-toggle-btn ${mode === 'tfidf' ? 'active' : ''}"
                        data-mode="tfidf" onclick="window.knowledgeManager.setSearchMode('tfidf')"
                        title="Nur Keyword-basierte Suche (schnell, exakt)">Dateiinhalt</button>
                    <button class="kb-toggle-btn ${mode === 'vector' ? 'active' : ''} ${!stats.vector_search ? 'disabled' : ''}"
                        data-mode="vector" onclick="window.knowledgeManager.setSearchMode('vector')"
                        title="Nur semantische Vektor-Suche (Bedeutung, Synonyme)" ${!stats.vector_search ? 'disabled' : ''}>Datenbank</button>
                </div>
            </div>
            <div class="kb-formats">
                <span class="kb-format-badge" title="Text-Formate immer aktiv">✅ Text/Markdown</span>
                <span class="kb-format-badge" title="${pdfTitle}">${pdfIcon} PDF</span>
                <span class="kb-format-badge" title="${docxTitle}">${docxIcon} Word</span>
                <span class="kb-format-badge" title="${xlsxTitle}">${xlsxIcon} Excel</span>
                <span class="kb-format-badge" title="${pptxTitle}">${pptxIcon} PowerPoint</span>
                <span class="kb-format-badge" title="${videoTitle}">${videoIcon} Video/Audio</span>
                <span class="kb-format-badge" title="${vectorTitle}">${vectorIcon} Vektor-DB</span>
            </div>
        `;
    }

    async setSearchMode(mode) {
        try {
            const resp = await fetch('/api/skills/knowledge/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ search_mode: mode })
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            // Toggle-Buttons aktualisieren
            document.querySelectorAll('.kb-toggle-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === mode);
            });
        } catch (e) {
            console.error('Suchmodus setzen fehlgeschlagen:', e);
        }
    }

    _renderFolders(folders) {
        const el = document.getElementById('kb-folder-list');
        if (!el) return;

        if (!folders || folders.length === 0) {
            el.innerHTML = '<div class="kb-empty">Keine Ordner konfiguriert</div>';
            return;
        }

        el.innerHTML = folders.map((f, idx) => `
            <div class="kb-folder-item" id="kb-folder-item-${idx}">
                <div class="kb-folder-header">
                    <button class="kb-folder-toggle" title="Dateien anzeigen"
                        onclick="window.knowledgeManager.toggleFolder(${idx}, '${f.path}')">
                        <span class="kb-folder-icon">${f.exists ? '📁' : '⚠️'}</span>
                        <span class="kb-folder-path" title="${f.path}">${f.path}</span>
                        <span class="kb-folder-arrow" id="kb-arrow-${idx}">▶</span>
                    </button>
                    <button class="kb-btn-remove" data-folder="${f.path}" title="Ordner entfernen"
                        onclick="window.knowledgeManager.removeFolder('${f.path}')">✕</button>
                </div>
                <div class="kb-folder-files" id="kb-files-${idx}" style="display:none;"></div>
            </div>
        `).join('');
    }

    async toggleFolder(idx, folderPath) {
        const filesEl = document.getElementById(`kb-files-${idx}`);
        const arrowEl = document.getElementById(`kb-arrow-${idx}`);
        if (!filesEl) return;

        const isOpen = filesEl.style.display !== 'none';
        if (isOpen) {
            filesEl.style.display = 'none';
            if (arrowEl) arrowEl.textContent = '▶';
            return;
        }

        filesEl.innerHTML = '<div class="kb-files-loading">Lädt…</div>';
        filesEl.style.display = 'block';
        if (arrowEl) arrowEl.textContent = '▼';

        try {
            const resp = await fetch('/api/knowledge/files', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();

            const folderData = data.find(d => d.folder === folderPath);
            if (!folderData || !folderData.exists) {
                filesEl.innerHTML = '<div class="kb-files-empty">Ordner existiert nicht</div>';
                return;
            }
            if (!folderData.files || folderData.files.length === 0) {
                filesEl.innerHTML = '<div class="kb-files-empty">Keine Dateien gefunden</div>';
                return;
            }

            filesEl.innerHTML = folderData.files.map(f => `
                <div class="kb-file-item" id="kb-file-${btoa(f.path).replace(/[^a-zA-Z0-9]/g, '')}">
                    <span class="kb-file-icon">📄</span>
                    <span class="kb-file-name" title="${f.path}">${f.name}</span>
                    <span class="kb-file-size">${f.size}</span>
                    <button class="kb-btn-delete-file" title="Datei löschen"
                        onclick="window.knowledgeManager.deleteFile('${f.path.replace(/'/g, "\\'")}', ${idx}, '${folderPath}')">✕</button>
                </div>
            `).join('');
        } catch (e) {
            filesEl.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
        }
    }

    // ─── Datei löschen ──────────────────────────────────────────────

    async deleteFile(filePath, folderIdx, folderPath) {
        if (!confirm(`Datei "${filePath.split('/').pop()}" wirklich löschen?`)) return;

        try {
            const resp = await fetch('/api/knowledge/files', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ path: filePath })
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'HTTP ' + resp.status);
            }
            this._showNotification('Datei gelöscht', 'success');
            // Ordner-Inhalt neu laden
            const filesEl = document.getElementById(`kb-files-${folderIdx}`);
            if (filesEl) filesEl.style.display = 'none';
            await this.toggleFolder(folderIdx, folderPath);
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    // ─── Ordner hinzufügen ────────────────────────────────────────────

    async addFolder() {
        const input = document.getElementById('kb-folder-input');
        if (!input) return;

        const folder = input.value.trim();
        if (!folder) return;

        try {
            const resp = await fetch('/api/skills/knowledge/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ folders: await this._buildNewFolderList(folder, 'add') })
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            input.value = '';
            this._showNotification('Ordner hinzugefügt', 'success');
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async removeFolder(folder) {
        if (!confirm(`Ordner "${folder}" aus der Knowledge Base entfernen?`)) return;

        try {
            const newFolders = await this._buildNewFolderList(folder, 'remove');
            const resp = await fetch('/api/skills/knowledge/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ folders: newFolders })
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            this._showNotification('Ordner entfernt', 'success');
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async _buildNewFolderList(folder, action) {
        // Aktuelle Ordnerliste aus Stats laden
        const resp = await fetch('/api/knowledge/stats', {
            headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
        });
        const stats = await resp.json();
        let folders = (stats.folders || []).map(f => f.path);

        if (action === 'add') {
            if (!folders.includes(folder)) folders.push(folder);
        } else if (action === 'remove') {
            folders = folders.filter(f => f !== folder);
            if (folders.length === 0) folders = ['data/knowledge'];
        }

        return folders.join(',');
    }

    // ─── Reindex ─────────────────────────────────────────────────────

    async reindex() {
        try {
            const resp = await fetch('/api/knowledge/reindex', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const result = await resp.json();
            if (result.started === false) {
                this._showNotification(result.message || 'Läuft bereits', 'info');
            } else {
                this._showNotification('Indizierung gestartet...', 'success');
                this._startProgressPolling();
            }
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    // ─── Fortschritts-Polling ─────────────────────────────────────────

    _startProgressPolling() {
        if (this._progressTimer) return; // bereits aktiv
        this._showProgressBar();
        this._progressTimer = setInterval(() => this._pollProgress(), 800);
    }

    _stopProgressPolling() {
        if (this._progressTimer) {
            clearInterval(this._progressTimer);
            this._progressTimer = null;
        }
    }

    async _pollProgress() {
        try {
            const resp = await fetch('/api/knowledge/index_progress', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) return;
            const p = await resp.json();
            this._updateProgressBar(p);
            if (!p.running && (p.phase === 'Fertig' || p.phase === 'Fehler' || p.phase === '')) {
                this._stopProgressPolling();
                if (p.phase === 'Fertig') {
                    setTimeout(() => this._hideProgressBar(), 2000);
                    await this.fetchStats();
                }
            }
        } catch (_) {}
    }

    _showProgressBar() {
        const bar = document.getElementById('kb-index-progress-wrap');
        if (bar) bar.style.display = 'flex';
    }

    _hideProgressBar() {
        const bar = document.getElementById('kb-index-progress-wrap');
        if (bar) bar.style.display = 'none';
    }

    _updateProgressBar(p) {
        const label   = document.getElementById('kb-progress-label');
        const pct     = document.getElementById('kb-progress-pct');
        const bar     = document.getElementById('kb-progress-bar');
        const phase   = document.getElementById('kb-progress-phase');
        const count   = document.getElementById('kb-progress-count');
        if (!bar) return;

        // Gesamt-Fortschritt: TF-IDF + Vektor zusammen
        const tTotal = p.total || 0;
        const tDone  = p.done  || 0;
        const vTotal = p.vector_total || 0;
        const vDone  = p.vector_done  || 0;
        const grand  = tTotal + vTotal;
        const done   = tDone  + vDone;
        const pctVal = grand > 0 ? Math.round((done / grand) * 100) : (p.phase === 'Fertig' ? 100 : 0);

        bar.style.width = pctVal + '%';
        if (pct)   pct.textContent   = pctVal + '%';
        if (phase) phase.textContent = p.phase || '';
        if (p.error && count) count.textContent = '⚠ ' + p.error.slice(0, 60);
        else if (count) count.textContent = grand > 0 ? `${done} / ${grand}` : '';

        if (label) {
            if (p.phase === 'Fertig')      label.textContent = '✓ Indizierung abgeschlossen';
            else if (p.phase === 'Fehler') label.textContent = '❌ Fehler bei der Indizierung';
            else if (p.running)            label.textContent = 'Indizierung läuft...';
            else                           label.textContent = 'Indizierung bereit';
        }

        // Dateien + Indiziert-Zähler live aktualisieren während Indizierung läuft
        if (p.running) {
            const statEls = document.querySelectorAll('#kb-stats-container .kb-stat-value');
            // statEls[0] = Dateien, statEls[1] = Indiziert
            if (statEls.length >= 2 && p.done > 0) {
                statEls[0].textContent = p.total || p.done;
                statEls[1].textContent = p.done;
            }
        }
    }

    // ─── WebDAV ───────────────────────────────────────────────────────

    async initWebDAV() {
        const toggle = document.getElementById('kb-webdav-toggle');
        const details = document.getElementById('kb-webdav-details');
        if (!toggle) return;

        toggle.addEventListener('change', () => this.toggleWebDAV(toggle.checked));

        try {
            const resp = await fetch('/api/knowledge/webdav/status', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            const data = await resp.json();
            toggle.checked = data.enabled;
            if (details) details.style.display = data.enabled ? '' : 'none';
            if (data.enabled) {
                const urlEl = document.getElementById('kb-webdav-url');
                const userEl = document.getElementById('kb-webdav-user');
                const sharesEl = document.getElementById('kb-webdav-shares');
                if (urlEl) {
                    const urls = data.urls && data.urls.length ? data.urls : (data.url ? [data.url] : []);
                    urlEl.innerHTML = urls.map(u => `<a href="${u}" target="_blank" style="color:inherit">${u}</a>`).join('<br>');
                }
                if (userEl) userEl.textContent = data.username || 'jarvis';
                const passEl = document.getElementById('kb-webdav-pass');
                if (passEl) passEl.textContent = data.password || 'jarvis';
                if (sharesEl) sharesEl.textContent = (data.shares || []).join(', ');
            }
        } catch (e) {}
    }

    async saveWebdavCredentials() {
        const user = document.getElementById('kb-webdav-new-user')?.value.trim();
        const pass = document.getElementById('kb-webdav-new-pass')?.value;
        if (!user && !pass) { this._showNotification('Bitte Benutzername oder Passwort eingeben', 'error'); return; }
        try {
            const body = { enabled: true };
            if (user) body.username = user;
            if (pass) body.password = pass;
            await fetch('/api/knowledge/webdav/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') },
                body: JSON.stringify(body)
            });
            // Jarvis-Server neu starten damit WebDAV neue Credentials übernimmt
            await fetch('/api/system/restart', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            this._showNotification('Gespeichert – Server wird neu gestartet…', 'success');
            document.getElementById('kb-webdav-new-user').value = '';
            document.getElementById('kb-webdav-new-pass').value = '';
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async toggleWebDAV(enabled) {
        const details = document.getElementById('kb-webdav-details');
        try {
            await fetch('/api/knowledge/webdav/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ enabled })
            });
            if (details) details.style.display = enabled ? '' : 'none';
            this._showNotification(
                enabled ? 'WebDAV aktiviert (Server-Neustart noetig)' : 'WebDAV deaktiviert',
                'success'
            );
            if (enabled) await this.initWebDAV();
        } catch (e) {
            this._showNotification('WebDAV-Fehler: ' + e.message, 'error');
        }
    }

    // ─── Netzwerk-Freigaben ──────────────────────────────────────────

    async initMounts() {
        const addBtn = document.getElementById('btn-kb-add-mount');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                const form = document.getElementById('kb-mount-form');
                if (form) form.style.display = form.style.display === 'none' ? '' : 'none';
            });
        }
        await this.fetchMounts();
    }

    async fetchMounts() {
        const list = document.getElementById('kb-mount-list');
        if (!list) return;
        try {
            const resp = await fetch('/api/knowledge/mounts', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            const mounts = await resp.json();
            this._renderMounts(mounts);
        } catch (e) {
            list.innerHTML = '';
        }
    }

    _renderMounts(mounts) {
        const list = document.getElementById('kb-mount-list');
        if (!list) return;
        if (!mounts || mounts.length === 0) {
            list.innerHTML = '<div class="kb-hint" style="margin:0;">Keine Freigaben konfiguriert</div>';
            return;
        }
        list.innerHTML = mounts.map((m, i) => `
            <div class="kb-mount-item">
                <span class="kb-mount-status ${m.active ? 'active' : 'inactive'}"></span>
                <span class="kb-mount-type">${m.type}</span>
                <span class="kb-mount-source">${m.source}</span>
                <button class="btn-icon btn-small" title="${m.active ? 'Trennen' : 'Verbinden'}"
                    onclick="window.knowledgeManager.toggleMount(${i}, ${!m.active})">
                    ${m.active ? '⏏' : '▶'}
                </button>
                <button class="btn-icon btn-small" title="Entfernen"
                    onclick="window.knowledgeManager.removeMount(${i})">✕</button>
            </div>
        `).join('');
    }

    async saveMount() {
        const type = document.getElementById('kb-mount-type')?.value;
        const source = document.getElementById('kb-mount-source')?.value?.trim();
        const username = document.getElementById('kb-mount-user')?.value?.trim();
        const password = document.getElementById('kb-mount-pass')?.value;

        if (!source) {
            this._showNotification('Bitte Quelle angeben', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/knowledge/mounts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ type, source, username, password })
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Fehler');
            }
            document.getElementById('kb-mount-form').style.display = 'none';
            document.getElementById('kb-mount-source').value = '';
            document.getElementById('kb-mount-user').value = '';
            document.getElementById('kb-mount-pass').value = '';
            this._showNotification('Freigabe hinzugefuegt', 'success');
            await this.fetchMounts();
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async toggleMount(idx, mount) {
        try {
            const action = mount ? 'mount' : 'unmount';
            const resp = await fetch(`/api/knowledge/mounts/${idx}/${action}`, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Fehler');
            }
            this._showNotification(mount ? 'Freigabe verbunden' : 'Freigabe getrennt', 'success');
            await this.fetchMounts();
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async removeMount(idx) {
        if (!confirm('Freigabe entfernen?')) return;
        try {
            await fetch(`/api/knowledge/mounts/${idx}`, {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            this._showNotification('Freigabe entfernt', 'success');
            await this.fetchMounts();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    // ─── Hilfsmethoden ────────────────────────────────────────────────

    _showNotification(msg, type = 'info') {
        const el = document.getElementById('kb-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = 'kb-notification kb-notification-' + type;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 3500);
    }
}

// Globale Instanz
window.knowledgeManager = new JarvisKnowledgeManager();
window._saveWebdavCredentials = () => window.knowledgeManager.saveWebdavCredentials();
