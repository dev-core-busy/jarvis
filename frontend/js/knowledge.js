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
        await this.initGroups();
        await this.initWebDAV();
        await this.initMounts();
        // Prüfen ob Indizierung gerade läuft (z.B. nach Seiten-Reload)
        await this._checkRunningIndex();
    }

    // ─── Wissensgruppen (logische Tags) ───────────────────────────────

    async initGroups() {
        if (!window.KbGroups) return;
        await window.KbGroups.load();
        this._renderGroupsOverview();
        // Upload-Ziel-Gruppen (Mehrfachauswahl) rendern
        window.KbGroups.renderCheckboxes(document.getElementById('kb-upload-groups'), []);
    }

    _renderGroupsOverview() {
        const el = document.getElementById('kb-groups-overview');
        if (!el || !window.KbGroups) return;
        const KG = window.KbGroups;
        const T = (k, d) => (window.t && window.t(k)) || d;
        const rows = KG.all().map(g => `
            <div class="kb-grp-manage-row" data-gid="${KG.esc(g.id)}">
                <input type="color" class="kb-grp-color-input" value="${KG.esc(g.color)}" title="${T('kbgroups.color', 'Farbe ändern')}">
                <span class="kb-grp-manage-name" title="${T('kbgroups.show_files', 'Dokumente anzeigen')}">${KG.esc(g.name)}</span>
                <span class="kb-grp-count">${g.count}</span>
                <span class="kb-grp-manage-spacer"></span>
                <button class="kb-grp-manage-btn kb-grp-rename" title="${T('kbgroups.rename', 'Umbenennen')}">✏️</button>
                <button class="kb-grp-manage-btn kb-grp-delete" title="${T('kbgroups.delete', 'Löschen')}">🗑️</button>
            </div>`).join('');
        const ung = KG.ungroupedCount();
        const ungRow = (ung != null) ? `
            <div class="kb-grp-manage-row kb-grp-row-ung">
                <span class="kb-grp-dot" style="background:#94a3b8;"></span>
                <span class="kb-grp-manage-name" style="cursor:default;">${T('kbgroups.ungrouped', 'ungruppiert')}</span>
                <span class="kb-grp-count">${ung}</span>
            </div>` : '';
        el.innerHTML = `
            <div class="kb-grp-manage">
                <div class="kb-grp-add-row">
                    <input type="text" id="kb-grp-new-name" class="kb-input" placeholder="${T('kbgroups.new_ph', 'Neue Gruppe…')}">
                    <input type="color" id="kb-grp-new-color" class="kb-grp-color-input" value="#3b82f6" title="${T('kbgroups.color', 'Farbe')}">
                    <button id="kb-grp-add-btn" class="kb-btn-action">${T('kbgroups.add', '+ Hinzufügen')}</button>
                </div>
                <div class="kb-grp-manage-list">${rows}${ungRow}</div>
            </div>`;

        const addBtn = document.getElementById('kb-grp-add-btn');
        if (addBtn) addBtn.onclick = () => this._addGroup();
        const nameInp = document.getElementById('kb-grp-new-name');
        if (nameInp) nameInp.addEventListener('keydown', e => { if (e.key === 'Enter') this._addGroup(); });

        el.querySelectorAll('.kb-grp-manage-row[data-gid]').forEach(row => {
            const gid = row.dataset.gid;
            row.querySelector('.kb-grp-manage-name').onclick = () => this._showGroupFiles(gid);
            row.querySelector('.kb-grp-color-input').onchange = (e) => this._setGroupColor(gid, e.target.value);
            row.querySelector('.kb-grp-rename').onclick = () => this._renameGroup(gid);
            row.querySelector('.kb-grp-delete').onclick = () => this._deleteGroup(gid);
        });
    }

    async _refreshGroups() {
        await window.KbGroups.load();
        this._renderGroupsOverview();
        window.KbGroups.renderCheckboxes(document.getElementById('kb-upload-groups'), []);
    }

    async _addGroup() {
        const nameEl = document.getElementById('kb-grp-new-name');
        const colorEl = document.getElementById('kb-grp-new-color');
        const name = (nameEl && nameEl.value || '').trim();
        if (!name) return;
        const res = await window.KbGroups.createGroup(name, colorEl ? colorEl.value : '#64748b');
        if (res && res.ok) {
            await this._refreshGroups();
            this._showNotification(window.t('kbgroups.added') || 'Gruppe angelegt', 'success');
        } else {
            this._showNotification((res && res.error) || 'Fehler beim Anlegen', 'error');
        }
    }

    async _renameGroup(gid) {
        const g = window.KbGroups.byId(gid);
        const cur = g ? g.name : '';
        const name = prompt(window.t('kbgroups.rename_prompt') || 'Neuer Name:', cur);
        if (name == null) return;
        const trimmed = name.trim();
        if (!trimmed || trimmed === cur) return;
        const res = await window.KbGroups.updateGroup(gid, { name: trimmed });
        if (res && res.ok) await this._refreshGroups();
        else this._showNotification((res && res.error) || 'Fehler', 'error');
    }

    async _setGroupColor(gid, color) {
        const res = await window.KbGroups.updateGroup(gid, { color });
        if (res && res.ok) await this._refreshGroups();
    }

    async _deleteGroup(gid) {
        const g = window.KbGroups.byId(gid);
        const nm = g ? g.name : gid;
        const msg = (window.t('kbgroups.delete_confirm')
            || 'Gruppe „{name}" löschen? Die Zuordnungen zu dieser Gruppe gehen verloren (die Dokumente bleiben erhalten).').replace('{name}', nm);
        if (!confirm(msg)) return;
        const ok = await window.KbGroups.deleteGroup(gid);
        if (ok) {
            const box = document.getElementById('kb-groups-files');
            if (box) box.style.display = 'none';
            await this._refreshGroups();
            this._showNotification(window.t('kbgroups.deleted') || 'Gruppe gelöscht', 'success');
        } else {
            this._showNotification('Fehler beim Löschen', 'error');
        }
    }

    async _showGroupFiles(gid) {
        const box = document.getElementById('kb-groups-files');
        if (!box || !window.KbGroups) return;
        const KG = window.KbGroups;
        box.style.display = 'block';
        box.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading') || 'Lädt…'}</div>`;
        const map = await KG.getMap();
        const files = Object.keys(map).filter(p => (map[p] || []).includes(gid));
        const title = `<div class="kb-grp-files-head">${KG.pillHtml(gid)}
            <span class="kb-hint" style="margin:0;">${files.length} ${window.t('kbgroups.docs') || 'Dokument(e)'}</span></div>`;
        if (!files.length) {
            box.innerHTML = title + `<div class="kb-files-empty">${window.t('kbgroups.no_docs') || 'Keine Dokumente in dieser Gruppe.'}</div>`;
            return;
        }
        box.innerHTML = title + files.map(p => `
            <div class="kb-grp-file-row">
                <span class="kb-file-icon">📄</span>
                <span class="kb-file-name" title="${KG.esc(p)}">${KG.esc(KG.baseName(p))}</span>
                <button class="kb-btn-remove kb-grp-untag" data-path="${KG.esc(p)}" title="${window.t('kbgroups.remove') || 'Aus Gruppe entfernen'}">✕</button>
            </div>`).join('');
        box.querySelectorAll('.kb-grp-untag').forEach(btn => {
            btn.onclick = async () => {
                const path = btn.dataset.path;
                const cur = await KG.getAssignment(path);
                await KG.setAssignment(path, cur.filter(x => x !== gid));
                await KG.load();
                this._renderGroupsOverview();
                this._showGroupFiles(gid);
            };
        });
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

        if (status) status.textContent = window.t('knowledge.uploading').replace('{n}', fileList.length);

        const formData = new FormData();
        formData.append('folder', folder);
        // Gewählte Zielgruppen (logische Tags) mitschicken
        if (window.KbGroups) {
            const gids = window.KbGroups.readChecked(document.getElementById('kb-upload-groups'));
            if (gids.length) formData.append('groups', gids.join(','));
        }
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

            let msg = window.t('knowledge.uploaded').replace('{saved}', result.total_saved);
            if (result.total_rejected > 0) {
                const names = result.rejected.map(r => r.name).join(', ');
                msg += ` | ` + window.t('knowledge.rejected').replace('{n}', result.total_rejected).replace('{names}', names);
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
                status.textContent = window.t('knowledge.upload_failed').replace('{msg}', e.message);
                status.style.color = '#ef4444';
            }
            this._showNotification(window.t('knowledge.upload_failed').replace('{msg}', e.message), 'error');
        }
    }

    // ─── Stats laden ──────────────────────────────────────────────────

    async fetchStats() {
        const container = document.getElementById('kb-stats-container');

        try {
            const [statsResp, learnedResp] = await Promise.all([
                fetch('/api/knowledge/stats', {
                    headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
                }),
                fetch('/api/knowledge/learned_stats', {
                    headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
                }).catch(() => null),
            ]);
            if (!statsResp.ok) throw new Error('HTTP ' + statsResp.status);
            const stats = await statsResp.json();
            const learnedStats = learnedResp && learnedResp.ok ? await learnedResp.json() : null;

            this._renderStats(stats, learnedStats);
            this._renderFolders(stats.folders);
            this._populateUploadTargets(stats.folders);
        } catch (e) {
            if (container) container.innerHTML = `<div class="kb-error">${window.t('knowledge.load_error').replace('{msg}', e.message)}</div>`;
        }
    }

    _renderStats(stats, learnedStats) {
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
        const imageIcon = stats.image_support ? '✅' : '⚠️';
        const imageTitle = stats.image_support ? 'Bild-OCR aktiv (Tesseract + pytesseract)' : 'tesseract-ocr oder pytesseract fehlt';
        const vectorAvail = stats.vector_db_available;
        const vectorIcon = vectorAvail ? '✅' : (stats.indexing ? '🔄' : '⚠️');
        const vectorDbLabel = stats.vector_db_name
            ? `${stats.vector_db_name}${stats.vector_db_version ? ' ' + stats.vector_db_version : ''}`
            : 'Vektor-DB';
        const vectorTitle = vectorAvail
            ? (stats.vector_search
                ? `${vectorDbLabel} · ${stats.vector_model || ''}\nIndex: ${stats.vector_files} ${window.t('knowledge.stat.files')}, ${stats.vector_chunks} Chunks`
                : (stats.indexing
                    ? `${vectorDbLabel} · ${stats.vector_model || ''}\n${window.t('knowledge.indexing_building')}`
                    : `${vectorDbLabel} · ${stats.vector_model || ''}\n${window.t('knowledge.no_index')}`))
            : 'faiss-cpu/sentence-transformers nicht installiert';

        // Aktueller Suchmodus
        const mode = stats.search_mode || 'auto';

        // Statuszeile: gelb während Indizierung, grün wenn fertig
        const phase = stats.index_phase || '';
        const isVectorPhase = phase.toLowerCase().includes('vektor');
        const GREEN = '#34d399', YELLOW = '#f59e0b', GREY = '#94a3b8';

        function activeLabel(label, color) {
            return `<span style="color:${color};font-weight:600;">${label}</span>`;
        }

        let activeText;
        if (stats.indexing) {
            activeText = isVectorPhase
                ? activeLabel(window.t('knowledge.vektor_db'), YELLOW) + ` <span style="color:${GREY}">(${window.t('knowledge.indexing_progress')})</span>`
                : activeLabel(window.t('knowledge.file_content'), YELLOW) + ` <span style="color:${GREY}">(${window.t('knowledge.indexing_progress')})</span>`;
        } else if (mode === 'auto') {
            activeText = stats.vector_search
                ? activeLabel(window.t('knowledge.vektor_db'), GREEN)
                : (stats.total_chunks > 0
                    ? activeLabel(window.t('knowledge.file_content'), GREEN)
                    : activeLabel(window.t('knowledge.none_label'), YELLOW));
        } else if (mode === 'vector') {
            activeText = stats.vector_search
                ? activeLabel(window.t('knowledge.vektor_db'), GREEN)
                : activeLabel(window.t('knowledge.none_label'), YELLOW);
        } else {
            activeText = stats.total_chunks > 0
                ? activeLabel(window.t('knowledge.file_content'), GREEN)
                : activeLabel(window.t('knowledge.none_label'), YELLOW);
        }

        // Datenbank-Button nur deaktivieren wenn FAISS nicht installiert
        const dbBtnDisabled = !stats.vector_db_available;
        const dbBtnTitle = stats.vector_db_available
            ? (stats.vector_search ? window.t('knowledge.search_auto_title') : window.t('knowledge.search_vector_no_index'))
            : 'faiss-cpu nicht installiert';

        el.innerHTML = `
            <div class="kb-stat-grid">
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.total_files}</span>
                    <span class="kb-stat-label">${window.t('knowledge.stat.files')}</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.indexed_files}</span>
                    <span class="kb-stat-label">${window.t('knowledge.stat.indexed')}</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${stats.total_chunks}</span>
                    <span class="kb-stat-label">${window.t('knowledge.stat.chunks')}</span>
                </div>
                <div class="kb-stat">
                    <span class="kb-stat-value">${sizeMb} MB</span>
                    <span class="kb-stat-label">${window.t('knowledge.stat.size')}</span>
                </div>
            </div>
            <div class="kb-search-mode" style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;">
                <span class="kb-search-mode-label">${window.t('knowledge.search_mode_label')}</span>
                <div class="kb-toggle-group">
                    <button class="kb-toggle-btn ${mode === 'auto' ? 'active' : ''}"
                        data-mode="auto" onclick="window.knowledgeManager.setSearchMode('auto')"
                        title="${window.t('knowledge.search_auto_title')}">${window.t('knowledge.search_auto')}</button>
                    <button class="kb-toggle-btn ${mode === 'tfidf' ? 'active' : ''}"
                        data-mode="tfidf" onclick="window.knowledgeManager.setSearchMode('tfidf')"
                        title="TF-IDF">${window.t('knowledge.search_tfidf')}</button>
                    <button class="kb-toggle-btn ${mode === 'vector' ? 'active' : ''} ${dbBtnDisabled ? 'disabled' : ''}"
                        data-mode="vector" onclick="window.knowledgeManager.setSearchMode('vector')"
                        title="${dbBtnTitle}" ${dbBtnDisabled ? 'disabled' : ''}>${window.t('knowledge.search_vector')}</button>
                </div>
                <span class="kb-search-mode-label" style="margin-left:8px;">${window.t('knowledge.search_active_label')}</span>
                <span id="kb-active-label" style="font-size:0.75rem;">${activeText}</span>
            </div>
            <div class="kb-formats">
                <span class="kb-format-badge" title="${window.t('knowledge.format_text_title')}">✅ Text/Markdown</span>
                <span class="kb-format-badge" title="${pdfTitle}">${pdfIcon} PDF</span>
                <span class="kb-format-badge" title="${docxTitle}">${docxIcon} Word</span>
                <span class="kb-format-badge" title="${xlsxTitle}">${xlsxIcon} Excel</span>
                <span class="kb-format-badge" title="${pptxTitle}">${pptxIcon} PowerPoint</span>
                <span class="kb-format-badge" title="${imageTitle}">${imageIcon} Bilder/OCR</span>
                <span class="kb-format-badge" title="${videoTitle}">${videoIcon} Video/Audio</span>
                <span class="kb-format-badge" title="${vectorTitle}">${vectorIcon} ${window.t('knowledge.vektor_db')}</span>
            </div>
        `;

        // Gelerntes Wissen – Statistik-Panel + Öffnen-Button
        if (learnedStats !== null && learnedStats !== undefined) {
            const lf = learnedStats.total_files || 0;
            const lkb = learnedStats.total_size_kb || 0;
            const lmonths = (learnedStats.months || []).join(', ') || '–';
            const convLabel = lf === 1
                ? `1 ${window.t('knowledge.stat.indexed')}`
                : `${lf} ${window.t('knowledge.stat.files')}`;
            el.innerHTML += `
            <div class="kb-learned-panel" title="${window.t('knowledge.learned.title')}">
                <span class="kb-learned-icon">🧠</span>
                <span class="kb-learned-title">${window.t('knowledge.learned.title')}</span>
                <span class="kb-learned-stat">${lf} ${lf !== 1 ? window.t('knowledge.stat.files') : window.t('knowledge.stat.indexed')}</span>
                <span class="kb-learned-sep">·</span>
                <span class="kb-learned-stat">${lkb} KB</span>
                ${lf > 0 ? `<span class="kb-learned-sep">·</span><span class="kb-learned-months">${lmonths}</span>` : ''}
                <button class="kb-learned-open-btn" onclick="window.knowledgeManager.toggleLearnedList()">
                    ${lf > 0 ? window.t('knowledge.learned.show') : window.t('knowledge.learned.list_btn')}
                </button>
                <button class="kb-learned-open-btn" onclick="window.knowledgeManager.downloadLearnedJson(this)" title="${window.t('knowledge.learned.export_title')}">
                    ${window.t('knowledge.learned.export_btn')}
                </button>
                <button class="kb-learned-open-btn" onclick="window.knowledgeManager.downloadLearnedJson(this, true)" title="${window.t('knowledge.learned.export_split_title')}">
                    ${window.t('knowledge.learned.export_split_btn')}
                </button>
                <label class="kb-learned-embed-opt" title="${window.t('knowledge.learned.llm_title')}" style="display:inline-flex;align-items:center;gap:5px;font-size:0.78rem;color:var(--text-muted);margin-left:8px;cursor:pointer;">
                    <input type="checkbox" id="kb-export-llm" style="margin:0;cursor:pointer;">
                    ${window.t('knowledge.learned.llm_label')}
                </label>
                <label class="kb-learned-embed-opt" title="${window.t('knowledge.learned.embeddings_title')}" style="display:inline-flex;align-items:center;gap:5px;font-size:0.78rem;color:var(--text-muted);margin-left:8px;cursor:pointer;">
                    <input type="checkbox" id="kb-export-embeddings" style="margin:0;cursor:pointer;">
                    ${window.t('knowledge.learned.embeddings_label')}
                </label>
            </div>
            <div id="kb-export-status" style="display:none;font-size:0.8rem;margin-top:8px;"></div>
            <div id="kb-learned-list" style="display:none;"></div>`;
        }
    }

    async downloadLearnedJson(btn, split) {
        const orig = btn ? btn.textContent : '';
        const st = document.getElementById('kb-export-status');
        const setStatus = (msg, color) => {
            if (!st) return;
            st.style.display = 'block';
            st.style.color = color || 'var(--text-muted)';
            st.textContent = msg;
        };
        const withEmb = document.getElementById('kb-export-embeddings')?.checked;
        const withLlm = document.getElementById('kb-export-llm')?.checked;
        if (btn) { btn.disabled = true; btn.textContent = window.t('knowledge.learned.exporting'); }
        setStatus(withLlm ? window.t('knowledge.learned.export_running_llm')
                          : window.t('knowledge.learned.export_running'), '#f59e0b');
        try {
            const params = [];
            if (withEmb) params.push('embeddings=1');
            if (withLlm) params.push('llm=1');
            if (split)   params.push('split=1');
            const resp = await fetch('/api/knowledge/export' + (params.length ? '?' + params.join('&') : ''), {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) {
                let detail = 'HTTP ' + resp.status;
                if (resp.status === 404) detail += ' – Echt-System evtl. nicht aktuell (Update nötig)';
                throw new Error(detail);
            }
            const blob = await resp.blob();
            // Dateinamen aus Content-Disposition lesen, sonst Fallback
            let fname = 'jarvis_gelerntes_wissen.zip';
            const cd = resp.headers.get('Content-Disposition') || '';
            const m = cd.match(/filename="?([^"]+)"?/);
            if (m) fname = m[1];
            const sizeKb = Math.max(1, Math.round(blob.size / 1024));
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = fname;
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 2000);
            setStatus(`✓ ${fname} (${sizeKb} KB)`, '#34d399');
            setTimeout(() => { if (st) st.style.display = 'none'; }, 6000);
        } catch (e) {
            setStatus('✗ ' + (window.t('knowledge.learned.export_fail') || 'Export fehlgeschlagen') + ': ' + e.message, '#ef4444');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = orig; }
        }
    }

    async toggleLearnedList() {
        const el = document.getElementById('kb-learned-list');
        if (!el) return;
        if (el.style.display !== 'none') { el.style.display = 'none'; return; }
        el.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading')}</div>`;
        el.style.display = 'block';
        try {
            const resp = await fetch('/api/knowledge/learned', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const files = await resp.json();
            if (!files.length) {
                el.innerHTML = `<div class="kb-files-empty" style="padding:10px 0;">${window.t('knowledge.learned.no_entries')}</div>`;
                return;
            }
            el.innerHTML = files.map((f, i) => {
                const d = new Date(f.mtime * 1000);
                const dateStr = d.toLocaleDateString('de-DE', {day:'2-digit',month:'2-digit',year:'numeric'}) +
                                ' ' + d.toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit'});
                const safeId = 'lf_' + i;
                return `
                <div class="kb-learned-item" id="${safeId}">
                    <div class="kb-learned-item-header">
                        <span class="kb-learned-item-title" title="${f.path}">${f.title}</span>
                        <span class="kb-learned-item-date">${dateStr} · ${f.size_kb} KB</span>
                        <div class="kb-learned-item-actions">
                            <button class="kb-btn-sm" onclick="window.knowledgeManager.toggleLearnedEdit('${safeId}', '${f.path.replace(/'/g,"\\'")}')">✏️</button>
                            <button class="kb-btn-sm kb-btn-del" onclick="window.knowledgeManager.deleteLearnedFile('${f.path.replace(/'/g,"\\'")}')">🗑</button>
                        </div>
                    </div>
                    <div class="kb-learned-item-editor" id="${safeId}_editor" style="display:none;"></div>
                </div>`;
            }).join('');
        } catch (e) {
            el.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
        }
    }

    async toggleLearnedEdit(itemId, filePath) {
        const editorEl = document.getElementById(itemId + '_editor');
        if (!editorEl) return;
        if (editorEl.style.display !== 'none') { editorEl.style.display = 'none'; return; }
        editorEl.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading')}</div>`;
        editorEl.style.display = 'block';
        try {
            const resp = await fetch('/api/knowledge/file_read?path=' + encodeURIComponent(filePath), {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            const safeContent = (data.content || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            editorEl.innerHTML = `
                <textarea class="kb-learned-textarea" id="${itemId}_ta">${data.content || ''}</textarea>
                <div class="kb-learned-editor-btns">
                    <button class="kb-btn-sm kb-btn-save" onclick="window.knowledgeManager.saveLearnedFile('${filePath.replace(/'/g,"\\'")}','${itemId}')">${window.t('knowledge.learned.save_btn')}</button>
                    <button class="kb-btn-sm" onclick="document.getElementById('${itemId}_editor').style.display='none'">${window.t('common.cancel')}</button>
                </div>`;
        } catch (e) {
            editorEl.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
        }
    }

    async saveLearnedFile(filePath, itemId) {
        const ta = document.getElementById(itemId + '_ta');
        if (!ta) return;
        try {
            const resp = await fetch('/api/knowledge/file_write', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ path: filePath, content: ta.value })
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            this._showNotification(window.t('knowledge.learned.saved'), 'success');
            document.getElementById(itemId + '_editor').style.display = 'none';
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async deleteLearnedFile(filePath) {
        if (!confirm(window.t('knowledge.learned.delete_confirm'))) return;
        try {
            const resp = await fetch('/api/knowledge/files', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ path: filePath })
            });
            if (!resp.ok) { const err = await resp.json(); throw new Error(err.error || 'HTTP ' + resp.status); }
            this._showNotification(window.t('knowledge.learned.deleted'), 'success');
            // Liste und Stats neu laden
            const listEl = document.getElementById('kb-learned-list');
            if (listEl) listEl.style.display = 'none';
            await this.fetchStats();
            await this.toggleLearnedList();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
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
            el.innerHTML = `<div class="kb-empty">${window.t('knowledge.no_folders')}</div>`;
            return;
        }

        el.innerHTML = folders.map((f, idx) => `
            <div class="kb-folder-item" id="kb-folder-item-${idx}">
                <div class="kb-folder-header">
                    <button class="kb-folder-toggle" title="${window.t('knowledge.folder_files_title')}"
                        onclick="window.knowledgeManager.toggleFolder(${idx}, '${f.path}')">
                        <span class="kb-folder-icon">${f.exists ? '📁' : '⚠️'}</span>
                        <span class="kb-folder-path" title="${f.path}">${f.path}</span>
                        <span class="kb-folder-arrow" id="kb-arrow-${idx}">▶</span>
                    </button>
                    <button class="kb-btn-remove" data-folder="${f.path}" title="${window.t('knowledge.folder_remove_title')}"
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

        filesEl.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading')}</div>`;
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
                filesEl.innerHTML = `<div class="kb-files-empty">${window.t('knowledge.folder_not_exists')}</div>`;
                return;
            }
            if (!folderData.files || folderData.files.length === 0) {
                filesEl.innerHTML = `<div class="kb-files-empty">${window.t('knowledge.no_files')}</div>`;
                return;
            }

            filesEl.innerHTML = folderData.files.map(f => {
                const safePath = f.path.replace(/'/g, "\\'");
                const isText = /\.(txt|md|json|yaml|yml|csv|log|xml|html|htm|py|js|ts|sh|cfg|ini|toml|rst|tex)$/i.test(f.name);
                const viewBtn = isText
                    ? `<button class="kb-btn-view-file" title="${window.t('knowledge.file_view_title') || 'Inhalt anzeigen'}"
                            onclick="window.knowledgeManager.viewFile('${safePath}', '${f.name}')">👁</button>`
                    : '';
                const tagBtn = window.KbGroups
                    ? `<button class="kb-btn-view-file kb-btn-tag-file" title="${window.t('kbgroups.assign_title') || 'Gruppen'}"
                            onclick="window.knowledgeManager.tagFile(this, '${safePath}')">🏷</button>`
                    : '';
                return `
                <div class="kb-file-item" id="kb-file-${btoa(unescape(encodeURIComponent(f.path))).replace(/[^a-zA-Z0-9]/g, '')}">
                    <span class="kb-file-icon">📄</span>
                    <span class="kb-file-name" title="${f.path}">${f.name}</span>
                    <span class="kb-file-size">${f.size}</span>
                    ${tagBtn}
                    ${viewBtn}
                    <button class="kb-btn-delete-file" title="${window.t('knowledge.file_delete_title')}"
                        onclick="window.knowledgeManager.deleteFile('${safePath}', ${idx}, '${folderPath}')">✕</button>
                </div>`;
            }).join('');
        } catch (e) {
            filesEl.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
        }
    }

    // ─── Datei einer Gruppe zuordnen ─────────────────────────────────

    tagFile(anchorEl, path) {
        if (!window.KbGroups) return;
        window.KbGroups.openTagPopover(anchorEl, path, async () => {
            // Zähler in der Übersicht nach dem Speichern aktualisieren
            await window.KbGroups.load();
            this._renderGroupsOverview();
        });
    }

    // ─── Datei löschen ──────────────────────────────────────────────

    async deleteFile(filePath, folderIdx, folderPath) {
        if (!confirm(window.t('knowledge.file_delete_confirm').replace('{name}', filePath.split('/').pop()))) return;

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
            this._showNotification(window.t('knowledge.file_deleted'), 'success');
            // Ordner-Inhalt neu laden
            const filesEl = document.getElementById(`kb-files-${folderIdx}`);
            if (filesEl) filesEl.style.display = 'none';
            await this.toggleFolder(folderIdx, folderPath);
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    // ─── Datei anzeigen ──────────────────────────────────────────────

    async viewFile(filePath, fileName) {
        // Vorherigen Modal entfernen
        document.getElementById('kb-file-view-modal')?.remove();

        const modal = document.createElement('div');
        modal.id = 'kb-file-view-modal';
        modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);';
        modal.innerHTML = `
            <div style="background:var(--bg-glass);border:1px solid var(--border-color);border-radius:12px;max-width:800px;width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
                <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border-color);">
                    <span style="font-weight:600;font-size:0.9rem;color:var(--text-primary);">📄 ${fileName}</span>
                    <button id="kb-file-view-close" style="background:none;border:none;color:var(--text-secondary);font-size:1.2rem;cursor:pointer;padding:2px 6px;border-radius:4px;" title="${window.t('common.close') || 'Schließen'}">✕</button>
                </div>
                <div id="kb-file-view-body" style="padding:16px;overflow:auto;flex:1;font-family:monospace;font-size:0.8rem;line-height:1.5;color:var(--text-primary);white-space:pre-wrap;word-break:break-word;">
                    <div style="text-align:center;padding:20px;color:var(--text-muted);">Lade…</div>
                </div>
                <div style="padding:10px 16px;border-top:1px solid var(--border-color);display:flex;justify-content:flex-end;">
                    <button id="kb-file-view-close2" style="padding:6px 16px;border-radius:6px;border:1px solid var(--border-color);background:var(--bg-glass);color:var(--text-primary);cursor:pointer;font-size:0.85rem;">${window.t('common.close') || 'Schließen'}</button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        const close = () => modal.remove();
        modal.querySelector('#kb-file-view-close').onclick  = close;
        modal.querySelector('#kb-file-view-close2').onclick = close;
        modal.addEventListener('click', e => { if (e.target === modal) close(); });
        document.addEventListener('keydown', function esc(e) {
            if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
        });

        try {
            const resp = await fetch(`/api/knowledge/file_read?path=${encodeURIComponent(filePath)}`, {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            const data = await resp.json();
            const body = modal.querySelector('#kb-file-view-body');
            if (data.ok) {
                body.textContent = data.content;
            } else {
                body.style.color = 'var(--error, #f87171)';
                body.textContent = data.error || 'Fehler beim Laden';
            }
        } catch (e) {
            const body = modal.querySelector('#kb-file-view-body');
            body.style.color = 'var(--error, #f87171)';
            body.textContent = 'Fehler: ' + e.message;
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
            this._showNotification(window.t('knowledge.folder_added'), 'success');
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async removeFolder(folder) {
        if (!confirm(window.t('knowledge.folder_remove_confirm').replace('{folder}', folder))) return;

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

            this._showNotification(window.t('knowledge.folder_removed'), 'success');
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
                this._showNotification(result.message || window.t('knowledge.already_running'), 'info');
            } else {
                this._showNotification(window.t('knowledge.indexing_started'), 'success');
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

            // "Aktiv:"-Label direkt aktualisieren (kein fetchStats → kein Flackern)
            if (p.running) this._updateActiveLabel(p.phase || '');

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
        // Defensiv auf 0–100% klemmen: bei (eigentlich verhinderten) inkonsistenten
        // Zaehlerstaenden niemals >100% / >grand anzeigen.
        const pctRaw = grand > 0 ? Math.round((done / grand) * 100) : (p.phase === 'Fertig' ? 100 : 0);
        const pctVal = Math.min(100, Math.max(0, pctRaw));
        const doneClamped = Math.min(done, grand);

        bar.style.width = pctVal + '%';
        if (pct)   pct.textContent   = pctVal + '%';
        if (phase) phase.textContent = p.phase || '';
        if (p.error && count) count.textContent = '⚠ ' + p.error.slice(0, 60);
        else if (count) count.textContent = grand > 0 ? `${doneClamped} / ${grand}` : '';

        if (label) {
            if (p.phase === 'Fertig')      label.textContent = window.t('knowledge.indexing_done');
            else if (p.phase === 'Fehler') label.textContent = window.t('knowledge.indexing_error_label');
            else if (p.running)            label.textContent = window.t('knowledge.indexing_running');
            else                           label.textContent = window.t('knowledge.indexing_ready');
        }

        // Dateien + Indiziert-Zähler live aktualisieren während Indizierung läuft
        // Vektor-Zähler bevorzugen (FAISS-Only-Modus), Fallback auf TF-IDF-Zähler
        if (p.running) {
            const statEls = document.querySelectorAll('#kb-stats-container .kb-stat-value');
            const liveFiles = p.vector_total || p.total || 0;
            const liveDone  = p.vector_done  || p.done  || 0;
            if (statEls.length >= 2 && liveFiles > 0) {
                statEls[0].textContent = liveFiles;
                statEls[1].textContent = liveDone;
            }
        }
    }

    _updateActiveLabel(phase) {
        const el = document.getElementById('kb-active-label');
        if (!el) return;
        const GREEN = '#34d399', YELLOW = '#f59e0b', GREY = '#94a3b8';
        const isVector = phase.toLowerCase().includes('vektor');
        const label = isVector ? window.t('knowledge.vektor_db') : window.t('knowledge.file_content');
        el.innerHTML = `<span style="color:${YELLOW};font-weight:600;">${label}</span>`
                     + ` <span style="color:${GREY}">(${window.t('knowledge.indexing_progress')})</span>`;
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
                if (sharesEl) sharesEl.textContent = window.t('knowledge.webdav_local_folder') + (data.shares || []).join(', ');
            }
        } catch (e) {}
    }

    async saveWebdavCredentials() {
        const user = document.getElementById('kb-webdav-new-user')?.value.trim();
        const pass = document.getElementById('kb-webdav-new-pass')?.value;
        if (!user && !pass) { this._showNotification(window.t('knowledge.webdav_fill_error'), 'error'); return; }
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
            this._showNotification(window.t('knowledge.webdav_saved'), 'success');
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
                enabled ? window.t('knowledge.webdav_enabled_msg') : window.t('knowledge.webdav_disabled_msg'),
                'success'
            );
            if (enabled) await this.initWebDAV();
        } catch (e) {
            this._showNotification(window.t('knowledge.webdav_error').replace('{msg}', e.message), 'error');
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
            list.innerHTML = `<div class="kb-hint" style="margin:0;">${window.t('knowledge.no_shares')}</div>`;
            return;
        }
        list.innerHTML = mounts.map((m, i) => `
            <div class="kb-mount-item-wrap">
                <div class="kb-mount-item">
                    <span class="kb-mount-status ${m.active ? 'active' : 'inactive'}" title="${m.active ? window.t('knowledge.share_connected_title') : window.t('knowledge.share_disconnected_title')}"></span>
                    <span class="kb-mount-type">${m.type}</span>
                    <span class="kb-mount-source" title="${m.source}">${m.source}</span>
                    <button class="btn-icon btn-small" title="${m.active ? window.t('knowledge.share_disconnect_title') : window.t('knowledge.share_connect_title')}"
                        onclick="window.knowledgeManager.toggleMount(${i}, ${!m.active})">
                        ${m.active ? '⏏' : '▶'}
                    </button>
                    <button class="btn-icon btn-small" title="${window.t('knowledge.share_edit_title')}"
                        onclick="window.knowledgeManager.showEditMount(${i})">✏️</button>
                    <button class="btn-icon btn-small" title="${window.t('knowledge.share_remove_title')}"
                        onclick="window.knowledgeManager.removeMount(${i})">✕</button>
                </div>
                <div class="kb-mount-edit-form" id="kb-mount-edit-${i}" style="display:none;">
                    <select class="kb-input kb-mount-edit-type">
                        <option value="smb" ${m.type==='smb'?'selected':''}>SMB/CIFS (Windows-Freigabe)</option>
                        <option value="nfs" ${m.type==='nfs'?'selected':''}>NFS</option>
                        <option value="webdav" ${m.type==='webdav'?'selected':''}>WebDAV</option>
                    </select>
                    <input type="text" class="kb-input kb-mount-edit-source" value="${m.source}" placeholder="${window.t('knowledge.share_source_ph')}" />
                    <input type="text" class="kb-input kb-mount-edit-user" value="${m.username||''}" placeholder="${window.t('knowledge.share_user_ph')}" />
                    <input type="password" class="kb-input kb-mount-edit-pass" placeholder="${window.t('knowledge.share_pass_unchanged_ph')}" />
                    <div class="kb-mount-actions">
                        <button class="kb-btn-action" onclick="window.knowledgeManager.saveEditMount(${i})">${window.t('knowledge.share_save_btn')}</button>
                        <button class="kb-btn-secondary" onclick="document.getElementById('kb-mount-edit-${i}').style.display='none'">${window.t('common.cancel')}</button>
                    </div>
                </div>
            </div>
        `).join('');
    }

    showEditMount(idx) {
        const form = document.getElementById(`kb-mount-edit-${idx}`);
        if (!form) return;
        form.style.display = form.style.display === 'none' ? '' : 'none';
    }

    async saveEditMount(idx) {
        const form = document.getElementById(`kb-mount-edit-${idx}`);
        if (!form) return;
        const type    = form.querySelector('.kb-mount-edit-type').value;
        const source  = form.querySelector('.kb-mount-edit-source').value.trim();
        const username = form.querySelector('.kb-mount-edit-user').value.trim();
        const passEl  = form.querySelector('.kb-mount-edit-pass');
        const password = passEl.value; // leer = wird im Backend nicht geändert wenn wir das so implementieren
        if (!source) { this._showNotification(window.t('knowledge.share_source_empty'), 'error'); return; }
        try {
            const resp = await fetch(`/api/knowledge/mounts/${idx}`, {
                method: 'PUT',
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
            this._showNotification(window.t('knowledge.share_updated'), 'success');
            await this.fetchMounts();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async saveMount() {
        const type = document.getElementById('kb-mount-type')?.value;
        const source = document.getElementById('kb-mount-source')?.value?.trim();
        const username = document.getElementById('kb-mount-user')?.value?.trim();
        const password = document.getElementById('kb-mount-pass')?.value;

        if (!source) {
            this._showNotification(window.t('knowledge.share_source_required'), 'error');
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
            this._showNotification(window.t('knowledge.share_added'), 'success');
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
            this._showNotification(mount ? window.t('knowledge.share_mounted') : window.t('knowledge.share_unmounted'), 'success');
            await this.fetchMounts();
            await this.fetchStats();
        } catch (e) {
            this._showNotification('Fehler: ' + e.message, 'error');
        }
    }

    async removeMount(idx) {
        if (!confirm(window.t('knowledge.share_remove_confirm'))) return;
        try {
            await fetch(`/api/knowledge/mounts/${idx}`, {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            this._showNotification(window.t('knowledge.share_removed'), 'success');
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
