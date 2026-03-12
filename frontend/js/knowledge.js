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
    }

    // ─── Init (wird beim Tab-Wechsel aufgerufen) ──────────────────────

    async init() {
        await this.fetchStats();
    }

    // ─── Stats laden ──────────────────────────────────────────────────

    async fetchStats() {
        const container = document.getElementById('kb-stats-container');
        const folderList = document.getElementById('kb-folder-list');

        try {
            const resp = await fetch('/api/knowledge/stats', {
                headers: { 'Authorization': 'Bearer ' + (window.authToken || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const stats = await resp.json();

            this._renderStats(stats);
            this._renderFolders(stats.folders);
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
        const pdfTitle = stats.pdf_support ? 'PDF-Support aktiv' : 'pdfplumber nicht installiert';
        const docxTitle = stats.docx_support ? 'DOCX-Support aktiv' : 'python-docx nicht installiert';

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
            <div class="kb-formats">
                <span class="kb-format-badge" title="Text-Formate immer aktiv">✅ Text/Markdown</span>
                <span class="kb-format-badge" title="${pdfTitle}">${pdfIcon} PDF</span>
                <span class="kb-format-badge" title="${docxTitle}">${docxIcon} DOCX</span>
            </div>
        `;
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
                headers: { 'Authorization': 'Bearer ' + (window.authToken || '') }
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
                <div class="kb-file-item">
                    <span class="kb-file-icon">📄</span>
                    <span class="kb-file-name" title="${f.path}">${f.name}</span>
                    <span class="kb-file-size">${f.size}</span>
                </div>
            `).join('');
        } catch (e) {
            filesEl.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
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
                    'Authorization': 'Bearer ' + (window.authToken || '')
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
                    'Authorization': 'Bearer ' + (window.authToken || '')
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
            headers: { 'Authorization': 'Bearer ' + (window.authToken || '') }
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
        const btn = document.getElementById('btn-kb-reindex');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Läuft...';
        }

        try {
            const resp = await fetch('/api/knowledge/reindex', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (window.authToken || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const result = await resp.json();

            this._showNotification(
                `Index neu aufgebaut: ${result.indexed_files} Dateien, ${result.total_chunks} Chunks`,
                'success'
            );
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Index neu aufbauen';
            }
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
