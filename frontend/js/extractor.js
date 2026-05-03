/**
 * Jarvis Informationsextraktor
 * URL oder Datei → LLM-Extraktion → menschliche Validierung → Wissens-DB
 * Unterstützte Formate: URLs, PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, MP3/MP4 u.v.m.
 */
window.extractorManager = new (class JarvisExtractorManager {

    constructor() {
        this._pending          = [];
        this._reviewing        = null;
        this._reviewIsApproved = false;
        this._container        = null;
        this._infoModal        = null;
        this._initialized      = false;
        this._activeInputTab   = 'url';
        this._dropFile         = null;   // Datei die per DnD reingekommen ist
    }

    init() {
        this._container = document.getElementById('extractor-tab-content');
        if (!this._container) return;
        if (!this._initialized) {
            this._renderInfoModal();
            this._renderSections();
            this._setupDnD();
            this._initialized = true;
        }
        this._loadPending();
    }

    // ─── Info-Modal ──────────────────────────────────────────────────────────

    _renderInfoModal() {
        const existing = document.getElementById('ext-info-modal');
        if (existing) { this._infoModal = existing; return; }
        const modal = document.createElement('div');
        modal.id = 'ext-info-modal';
        modal.className = 'modal-overlay hidden';
        modal.innerHTML = `
            <div class="modal-card" style="max-width:540px;text-align:left;">
                <h2 class="modal-title">Informationsextraktor</h2>

                <div class="ext-info-step">
                    <span class="ext-info-num">1</span>
                    <div>
                        <strong>Quelle wählen</strong><br>
                        <span class="kb-hint" style="margin:0;">
                            <strong>URL:</strong> Adresse einer öffentlich erreichbaren Webseite eingeben.<br>
                            <strong>Datei:</strong> Datei per Drag &amp; Drop ablegen oder über den Datei-Browser wählen.
                            Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV,
                            sowie Audio/Video (MP3, MP4, MOV …) via Whisper-Transkription.
                        </span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">2</span>
                    <div>
                        <strong>Extraktion starten</strong><br>
                        <span class="kb-hint" style="margin:0;">Jarvis ruft die Seite ab bzw. liest die Datei und analysiert den Inhalt mit dem konfigurierten LLM. Dabei werden automatisch eine Zusammenfassung, Kernfakten und Frage-Antwort-Paare generiert.</span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">3</span>
                    <div>
                        <strong>Ergebnis validieren</strong><br>
                        <span class="kb-hint" style="margin:0;">Öffne das Dokument über <em>Prüfen</em>. Du kannst Titel, Zusammenfassung und Fakten bearbeiten sowie einzelne Frage-Antwort-Paare aktivieren, deaktivieren, bearbeiten oder löschen.</span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">4</span>
                    <div>
                        <strong>In Wissens-DB speichern</strong><br>
                        <span class="kb-hint" style="margin:0;">Klicke auf <em>In Wissens-DB speichern</em>. Nur aktivierte Elemente werden übernommen. Das Dokument wird als Markdown-Datei angelegt und der Suchindex automatisch neu aufgebaut.</span>
                    </div>
                </div>

                <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px 14px;margin-top:4px;">
                    <p class="kb-hint" style="margin:0;">
                        <strong>Hinweis:</strong> Nicht gespeicherte Extraktionen bleiben im Bereich <em>Ausstehend</em>.
                        Audio/Video-Transkription erfordert faster-whisper + ffmpeg auf dem Server.
                    </p>
                </div>

                <button class="btn-modal-close" id="ext-info-close" style="margin-top:16px;">Schließen</button>
            </div>`;
        document.body.appendChild(modal);
        this._infoModal = modal;
        modal.addEventListener('click', e => { if (e.target === modal) this._hideInfo(); });
        document.getElementById('ext-info-close').onclick = () => this._hideInfo();
    }

    _showInfo() { this._infoModal?.classList.remove('hidden'); }
    _hideInfo() { this._infoModal?.classList.add('hidden'); }

    // ─── Sektionen rendern ───────────────────────────────────────────────────

    _renderSections() {
        this._container.innerHTML = `

            <!-- Extraktor: Eingabe (URL + Datei) -->
            <div class="kb-section">
                <div class="kb-section-header">
                    <h3>Informationsextraktor</h3>
                    <button id="ext-info-btn" class="kb-btn-secondary" title="Anleitung">❓</button>
                </div>
                <p class="kb-hint">Webseiten oder Dateien per LLM in strukturiertes Wissen umwandeln – mit menschlicher Validierung.</p>

                <!-- Sub-Tabs -->
                <div class="ext-input-tabs">
                    <button class="ext-input-tab active" id="ext-tab-url">🌐 URL</button>
                    <button class="ext-input-tab"        id="ext-tab-file">📄 Datei</button>
                </div>

                <!-- Panel: URL -->
                <div id="ext-panel-url">
                    <div style="display:flex;gap:8px;">
                        <input id="ext-url-input" type="url" placeholder="https://beispiel.de/artikel" class="kb-input" style="flex:1;">
                        <button id="ext-extract-btn" class="kb-btn-action">Extrahieren</button>
                    </div>
                </div>

                <!-- Panel: Datei -->
                <div id="ext-panel-file" style="display:none;">
                    <div class="ext-drop-zone" id="ext-drop-zone">
                        <input type="file" id="ext-file-input"
                            accept=".pdf,.txt,.md,.rst,.csv,.docx,.doc,.xlsx,.ods,.pptx,.mp3,.m4a,.wav,.ogg,.mp4,.mov,.mkv,.avi">
                        <div style="font-size:1.8rem;line-height:1;">📄</div>
                        <div class="ext-drop-zone-label">Datei hierher ziehen oder <span style="color:var(--accent);text-decoration:underline;cursor:pointer;">durchsuchen</span></div>
                        <div class="ext-drop-zone-hint">PDF · DOCX · XLSX · PPTX · TXT · MD · CSV · MP3 · MP4 · MOV · max. 50 MB</div>
                    </div>
                    <!-- Drop-Banner: erscheint nach DnD-Ablage -->
                    <div id="ext-drop-banner" class="ext-drop-banner" style="display:none;margin-top:8px;">
                        <span style="font-size:1.1rem;">📄</span>
                        <span class="ext-drop-banner-name" id="ext-drop-name">–</span>
                        <span class="ext-drop-banner-size" id="ext-drop-size"></span>
                        <button id="ext-drop-analyse-btn" class="kb-btn-action" style="padding:.35rem .9rem;font-size:.8rem;flex-shrink:0;">Analysieren ▶</button>
                        <button id="ext-drop-cancel-btn"  class="kb-btn-secondary" style="padding:.35rem .6rem;font-size:.8rem;flex-shrink:0;">✕</button>
                    </div>
                </div>

                <div id="ext-extract-status" class="kb-hint" style="margin-top:6px;display:none;"></div>
                <div id="ext-notification" class="kb-notification" style="display:none;margin-top:8px;"></div>
            </div>

            <!-- Extraktor: Pending-Liste -->
            <div class="kb-section">
                <div class="kb-section-header">
                    <h3>Ausstehend <span id="ext-pending-count" class="ext-badge" style="display:none;">0</span></h3>
                    <button id="ext-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                </div>
                <div id="ext-pending-list"><p class="kb-empty">Keine ausstehenden Extraktionen.</p></div>
            </div>

            <!-- Extraktor: Genehmigter Verlauf -->
            <div class="kb-section" id="ext-approved-section" style="display:none;">
                <div class="kb-section-header">
                    <h3>Genehmigt <span id="ext-approved-count" class="ext-badge ext-badge-approved" style="display:none;">0</span></h3>
                </div>
                <div id="ext-approved-list"></div>
            </div>

            <!-- Extraktor: Review -->
            <div id="ext-review-wrap" class="kb-section" style="display:none;">
                <div class="kb-section-header">
                    <h3 id="ext-review-title">Dokument prüfen</h3>
                    <button id="ext-review-close" class="kb-btn-secondary">✕</button>
                </div>
                <p class="kb-hint" id="ext-review-source" style="word-break:break-all;margin-bottom:12px;"></p>

                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">Titel</label>
                    <input id="ext-edit-title" type="text" class="kb-input" style="width:100%;box-sizing:border-box;">
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">Zusammenfassung</label>
                    <textarea id="ext-edit-summary" rows="3" class="kb-input" style="width:100%;box-sizing:border-box;resize:vertical;"></textarea>
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">Kernfakten</label>
                    <div id="ext-facts-list" class="ext-facts-list"></div>
                    <button id="ext-add-fact-btn" class="kb-btn-secondary" style="margin-top:6px;font-size:.78rem;">+ Fakt hinzufügen</button>
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">Fragen &amp; Antworten <span class="kb-hint" style="margin:0;font-size:.73rem;">(aktivierte werden gespeichert)</span></label>
                    <div id="ext-qa-list" class="ext-qa-list"></div>
                    <button id="ext-add-qa-btn" class="kb-btn-secondary" style="margin-top:6px;font-size:.78rem;">+ Paar hinzufügen</button>
                </div>

                <div class="kb-form-footer" style="margin-top:12px;">
                    <button id="ext-reject-btn" class="kb-btn-danger" style="padding:.45rem 1rem;font-size:.82rem;">❌ Verwerfen</button>
                    <div class="kb-form-footer-right">
                        <button id="ext-save-btn" class="kb-btn-action">✅ In Wissens-DB speichern</button>
                    </div>
                </div>
                <div id="ext-review-notification" class="kb-notification" style="display:none;margin-top:8px;"></div>
            </div>
        `;

        // Tab-Buttons
        document.getElementById('ext-tab-url').onclick  = () => this._switchInputTab('url');
        document.getElementById('ext-tab-file').onclick = () => this._switchInputTab('file');

        // URL-Tab
        document.getElementById('ext-info-btn').onclick    = () => this._showInfo();
        document.getElementById('ext-extract-btn').onclick = () => this._startExtract();
        document.getElementById('ext-url-input').addEventListener('keydown', e => {
            if (e.key === 'Enter') this._startExtract();
        });

        // Datei-Tab
        document.getElementById('ext-file-input').addEventListener('change', e => {
            const file = e.target.files?.[0];
            if (file) this._showDropBanner(file);
        });

        // Drop-Banner
        document.getElementById('ext-drop-analyse-btn').onclick = () => {
            if (this._dropFile) this._startExtractFile(this._dropFile);
        };
        document.getElementById('ext-drop-cancel-btn').onclick = () => this._hideDropBanner();

        // Allgemein
        document.getElementById('ext-refresh-btn').onclick  = () => this._loadPending();
        document.getElementById('ext-review-close').onclick = () => this._closeReview();
        document.getElementById('ext-add-fact-btn').onclick = () => this._addFact();
        document.getElementById('ext-add-qa-btn').onclick   = () => this._addQa();
        document.getElementById('ext-save-btn').onclick     = () => this._approve();
        document.getElementById('ext-reject-btn').onclick   = () => this._reject();
    }

    // ─── Input-Tab-Umschalter ────────────────────────────────────────────────

    _switchInputTab(tab) {
        this._activeInputTab = tab;
        document.getElementById('ext-tab-url').classList.toggle('active', tab === 'url');
        document.getElementById('ext-tab-file').classList.toggle('active', tab === 'file');
        document.getElementById('ext-panel-url').style.display  = tab === 'url'  ? '' : 'none';
        document.getElementById('ext-panel-file').style.display = tab === 'file' ? '' : 'none';
    }

    // ─── Drag & Drop ─────────────────────────────────────────────────────────

    _setupDnD() {
        const zone = document.getElementById('ext-drop-zone');
        if (!zone) return;

        // Drop-Zone selbst
        zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            const file = e.dataTransfer?.files?.[0];
            if (file) this._showDropBanner(file);
        });

        // Globaler Listener auf dem Container → Datei-Tab automatisch aktivieren
        this._container.addEventListener('dragover', e => {
            if (e.dataTransfer?.types?.includes('Files')) e.preventDefault();
        });
        this._container.addEventListener('drop', e => {
            const file = e.dataTransfer?.files?.[0];
            if (!file) return;
            e.preventDefault();
            // Nicht doppelt verarbeiten wenn Drop bereits in der Drop-Zone landete
            if (e.target.closest('#ext-drop-zone')) return;
            this._switchInputTab('file');
            this._showDropBanner(file);
        });
    }

    _showDropBanner(file) {
        this._dropFile = file;
        this._switchInputTab('file');
        const fmt = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1024).toFixed(0) + ' KB';
        document.getElementById('ext-drop-name').textContent = file.name;
        document.getElementById('ext-drop-size').textContent = fmt(file.size);
        document.getElementById('ext-drop-banner').style.display = 'flex';
    }

    _hideDropBanner() {
        this._dropFile = null;
        document.getElementById('ext-drop-banner').style.display = 'none';
        // Datei-Input zurücksetzen
        const inp = document.getElementById('ext-file-input');
        if (inp) inp.value = '';
    }

    // ─── URL-Extraktion ──────────────────────────────────────────────────────

    async _startExtract() {
        const url = document.getElementById('ext-url-input').value.trim();
        if (!url) { this._notify('Bitte eine URL eingeben.', 'error'); return; }

        const btn    = document.getElementById('ext-extract-btn');
        const status = document.getElementById('ext-extract-status');
        btn.disabled = true; btn.textContent = '⏳ Läuft…';
        status.textContent = 'Seite wird abgerufen und analysiert…';
        status.style.display = 'block';

        try {
            const r = await fetch('/api/knowledge/extract', {
                method: 'POST',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            });
            const d = await r.json();
            if (!r.ok || d.error) {
                this._notify('Fehler: ' + (d.error || r.status), 'error');
            } else {
                document.getElementById('ext-url-input').value = '';
                this._notify(`✅ Extraktion abgeschlossen: „${d.title}"`);
                this._loadPending();
                setTimeout(() => this._openReview(d), 300);
            }
        } catch (e) {
            this._notify('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            btn.disabled = false; btn.textContent = 'Extrahieren';
            status.style.display = 'none';
        }
    }

    // ─── Datei-Extraktion ────────────────────────────────────────────────────

    async _startExtractFile(file) {
        const banner = document.getElementById('ext-drop-banner');
        const btn    = document.getElementById('ext-drop-analyse-btn');
        const status = document.getElementById('ext-extract-status');

        btn.disabled = true; btn.textContent = '⏳ Läuft…';
        status.textContent = `„${file.name}" wird analysiert (${file.type || 'unbekannter Typ'})…`;
        status.style.display = 'block';

        try {
            const form = new FormData();
            form.append('file', file);
            const r = await fetch('/api/knowledge/extract/upload', {
                method: 'POST',
                headers: _authHeaders(),   // kein Content-Type – FormData setzt es selbst
                body: form,
            });
            const d = await r.json();
            if (!r.ok || d.error) {
                this._notify('Fehler: ' + (d.error || r.status), 'error');
            } else {
                this._hideDropBanner();
                this._notify(`✅ Extraktion abgeschlossen: „${d.title}"`);
                this._loadPending();
                setTimeout(() => this._openReview(d), 300);
            }
        } catch (e) {
            this._notify('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            btn.disabled = false; btn.textContent = 'Analysieren ▶';
            status.style.display = 'none';
        }
    }

    // ─── Pending-Liste ───────────────────────────────────────────────────────

    async _loadPending() {
        try {
            const r = await fetch('/api/knowledge/pending', { headers: _authHeaders() });
            if (!r.ok) return;
            this._pending = await r.json();
            this._renderPending();
        } catch (e) { console.error('[Extractor]', e); }
    }

    _sourceLabel(doc) {
        if (doc.source_type === 'file') return `📄 ${doc.source_name || doc.url}`;
        try { return '🌐 ' + new URL(doc.url).hostname; } catch { return doc.url || ''; }
    }

    _renderPending() {
        const el    = document.getElementById('ext-pending-list');
        const badge = document.getElementById('ext-pending-count');
        if (!el) return;

        const pending  = this._pending.filter(d => (d.status || 'pending') === 'pending');
        const approved = this._pending.filter(d => d.status === 'approved');

        badge.textContent = pending.length;
        badge.style.display = pending.length ? 'inline-block' : 'none';

        if (!pending.length) {
            el.innerHTML = `<p class="kb-empty">Keine ausstehenden Extraktionen.</p>`;
        } else {
            el.innerHTML = pending.map(doc => {
                const dt  = new Date(doc.created_at * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
                const qa  = doc.qa_pairs?.length || 0;
                const fct = doc.facts?.length    || 0;
                return `
                <div class="cron-item" data-id="${doc.id}">
                    <div class="cron-item-row">
                        <span class="cron-item-dot active"></span>
                        <span class="cron-item-label">${this._esc(doc.title)}</span>
                        <div class="cron-item-actions">
                            <button class="kb-btn-action ext-review-btn" data-id="${doc.id}" style="padding:3px 10px;font-size:.75rem;">Prüfen</button>
                            <button class="kb-btn-secondary ext-dl-btn"  data-id="${doc.id}" style="padding:3px 8px;font-size:.75rem;" title="JSON herunterladen">⬇️</button>
                            <button class="kb-btn-danger ext-del-btn"    data-id="${doc.id}" style="padding:3px 8px;font-size:.75rem;">🗑️</button>
                        </div>
                    </div>
                    <div class="cron-item-meta">${this._esc(this._sourceLabel(doc))} · ${dt} · ${fct} Fakten · ${qa} Q&amp;A-Paare</div>
                </div>`;
            }).join('');
            el.querySelectorAll('.ext-review-btn').forEach(btn => {
                btn.onclick = () => {
                    const doc = this._pending.find(d => d.id === btn.dataset.id);
                    if (doc) this._openReview(doc);
                };
            });
            el.querySelectorAll('.ext-dl-btn').forEach(btn => {
                btn.onclick = () => {
                    const doc = this._pending.find(d => d.id === btn.dataset.id);
                    if (doc) this._downloadJson(doc);
                };
            });
            el.querySelectorAll('.ext-del-btn').forEach(btn => {
                btn.onclick = () => this._deletePending(btn.dataset.id);
            });
        }

        // Genehmigter Verlauf
        const secEl   = document.getElementById('ext-approved-section');
        const apprEl  = document.getElementById('ext-approved-list');
        const apprBdg = document.getElementById('ext-approved-count');
        if (!secEl || !apprEl) return;
        if (!approved.length) { secEl.style.display = 'none'; return; }

        secEl.style.display = '';
        apprBdg.textContent = approved.length;
        apprBdg.style.display = 'inline-block';

        apprEl.innerHTML = approved.map(doc => {
            const dtC    = new Date(doc.created_at  * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
            const dtA    = new Date((doc.approved_at || doc.created_at) * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
            const qa     = doc.qa_count  ?? doc.qa_pairs?.filter(p => p.approved !== false).length ?? 0;
            const fct    = doc.fact_count ?? doc.facts?.length ?? 0;
            const fileHint = doc.file ? `<div style="padding:2px 0 0 18px;font-family:monospace;font-size:.7rem;color:var(--text-secondary);">${this._esc(doc.file)}</div>` : '';
            return `
            <div class="cron-item" data-id="${doc.id}" style="border-left:3px solid var(--green,#10b981);">
                <div class="cron-item-row">
                    <span class="cron-item-dot" style="background:var(--green,#10b981);"></span>
                    <span class="cron-item-label">${this._esc(doc.title)}</span>
                    <div class="cron-item-actions">
                        <button class="kb-btn-secondary ext-edit-btn" data-id="${doc.id}" style="padding:3px 10px;font-size:.75rem;">✏️ Bearbeiten</button>
                        <button class="kb-btn-secondary ext-dl-btn"   data-id="${doc.id}" style="padding:3px 8px;font-size:.75rem;" title="JSON herunterladen">⬇️</button>
                        <button class="kb-btn-danger ext-del-btn"     data-id="${doc.id}" style="padding:3px 8px;font-size:.75rem;" title="Aus Verlauf und Wissens-DB entfernen">🗑️</button>
                    </div>
                </div>
                <div class="cron-item-meta">${this._esc(this._sourceLabel(doc))} · Extrahiert: ${dtC} · Genehmigt: ${dtA} · ${fct} Fakten · ${qa} Q&amp;A-Paare</div>
                ${fileHint}
            </div>`;
        }).join('');

        apprEl.querySelectorAll('.ext-edit-btn').forEach(btn => {
            btn.onclick = () => {
                const doc = this._pending.find(d => d.id === btn.dataset.id);
                if (doc) this._openReview(doc, true);
            };
        });
        apprEl.querySelectorAll('.ext-dl-btn').forEach(btn => {
            btn.onclick = () => {
                const doc = this._pending.find(d => d.id === btn.dataset.id);
                if (doc) this._downloadJson(doc);
            };
        });
        apprEl.querySelectorAll('.ext-del-btn').forEach(btn => {
            btn.onclick = () => this._deleteApproved(btn.dataset.id);
        });
    }

    async _deleteApproved(id) {
        if (!confirm('Aus Verlauf und Wissens-DB entfernen?\nDie .md-Datei wird ebenfalls gelöscht.')) return;
        const doc = this._pending.find(d => d.id === id);
        if (doc?.file) {
            try {
                await fetch('/api/knowledge/extract/file', {
                    method: 'DELETE',
                    headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file: doc.file }),
                });
            } catch (e) {}
        }
        await fetch(`/api/knowledge/pending/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadPending();
        this._notify('Eintrag entfernt', 'info');
    }

    async _deletePending(id) {
        if (!confirm('Extraktion wirklich verwerfen?')) return;
        await fetch(`/api/knowledge/pending/${id}`, { method: 'DELETE', headers: _authHeaders() });
        if (this._reviewing?.id === id) this._closeReview();
        this._loadPending();
        this._notify('Extraktion verworfen', 'info');
    }

    // ─── Review ──────────────────────────────────────────────────────────────

    _openReview(doc, isApproved = false) {
        this._reviewing        = doc;
        this._reviewIsApproved = isApproved;

        document.getElementById('ext-review-wrap').style.display = '';
        document.getElementById('ext-review-title').textContent  =
            isApproved ? `Bearbeiten – ${doc.title}` : `Dokument prüfen – ${doc.title}`;

        // Quellenzeile: URL klickbar, Datei nur Text
        const srcEl = document.getElementById('ext-review-source');
        if (doc.source_type === 'file') {
            srcEl.innerHTML = `📄 <strong>${this._esc(doc.source_name || doc.url)}</strong>`;
        } else {
            srcEl.innerHTML = `🔗 <a href="${this._esc(doc.url)}" target="_blank" style="color:var(--accent);">${this._esc(doc.url)}</a>`;
        }

        document.getElementById('ext-edit-title').value   = doc.title   || '';
        document.getElementById('ext-edit-summary').value = doc.summary || '';
        this._renderFacts(doc.facts || []);
        this._renderQa(doc.qa_pairs || []);

        const saveBtn   = document.getElementById('ext-save-btn');
        const rejectBtn = document.getElementById('ext-reject-btn');
        saveBtn.textContent   = isApproved ? '💾 Aktualisieren'         : '✅ In Wissens-DB speichern';
        rejectBtn.textContent = isApproved ? '🗑️ Aus DB entfernen'      : '❌ Verwerfen';

        document.getElementById('ext-review-wrap').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    _closeReview() {
        this._reviewing        = null;
        this._reviewIsApproved = false;
        document.getElementById('ext-review-wrap').style.display = 'none';
        const saveBtn   = document.getElementById('ext-save-btn');
        const rejectBtn = document.getElementById('ext-reject-btn');
        if (saveBtn)   saveBtn.textContent   = '✅ In Wissens-DB speichern';
        if (rejectBtn) rejectBtn.textContent = '❌ Verwerfen';
    }

    // ─── Fakten-Editor ───────────────────────────────────────────────────────

    _renderFacts(facts) {
        const el = document.getElementById('ext-facts-list');
        if (!el) return;
        el.innerHTML = facts.map((f, i) => `
            <div class="ext-fact-row" data-idx="${i}">
                <input type="text" class="kb-input ext-fact-input" value="${this._esc(f)}" style="flex:1;">
                <button class="kb-btn-danger ext-fact-del" data-idx="${i}" style="padding:.3rem .6rem;">✕</button>
            </div>`).join('');
        el.querySelectorAll('.ext-fact-del').forEach(btn => {
            btn.onclick = () => {
                const facts = this._getFacts();
                facts.splice(parseInt(btn.dataset.idx), 1);
                this._renderFacts(facts);
            };
        });
    }

    _getFacts() {
        return [...document.querySelectorAll('.ext-fact-input')].map(i => i.value.trim()).filter(Boolean);
    }

    _addFact() {
        const facts = this._getFacts();
        facts.push('');
        this._renderFacts(facts);
        const inputs = document.querySelectorAll('.ext-fact-input');
        if (inputs.length) inputs[inputs.length - 1].focus();
    }

    // ─── Q&A-Editor ──────────────────────────────────────────────────────────

    _renderQa(pairs) {
        const el = document.getElementById('ext-qa-list');
        if (!el) return;
        el.innerHTML = pairs.map((p, i) => `
            <div class="ext-qa-row" data-id="${p.id || i}">
                <div class="ext-qa-header">
                    <label class="kb-form-checkbox-label" title="Aktiviert → wird gespeichert">
                        <input type="checkbox" class="ext-qa-check" data-id="${p.id || i}" ${p.approved !== false ? 'checked' : ''}>
                        <span style="font-size:.75rem;color:var(--text-secondary);">Übernehmen</span>
                    </label>
                    <button class="kb-btn-danger ext-qa-del" data-idx="${i}" style="padding:2px 7px;font-size:.73rem;margin-left:auto;">✕</button>
                </div>
                <div class="ext-qa-fields">
                    <input  type="text" class="kb-input ext-qa-q" data-idx="${i}" placeholder="Frage…"  value="${this._esc(p.q || '')}" style="width:100%;box-sizing:border-box;margin-bottom:5px;">
                    <textarea          class="kb-input ext-qa-a" data-idx="${i}" placeholder="Antwort…" rows="2" style="width:100%;box-sizing:border-box;resize:vertical;">${this._esc(p.a || '')}</textarea>
                </div>
            </div>`).join('');
        el.querySelectorAll('.ext-qa-del').forEach(btn => {
            btn.onclick = () => {
                const pairs = this._getQaPairs();
                pairs.splice(parseInt(btn.dataset.idx), 1);
                this._renderQa(pairs);
            };
        });
    }

    _getQaPairs() {
        return [...document.querySelectorAll('.ext-qa-row')].map(row => ({
            id:       row.dataset.id,
            q:        row.querySelector('.ext-qa-q')?.value.trim() || '',
            a:        row.querySelector('.ext-qa-a')?.value.trim() || '',
            approved: row.querySelector('.ext-qa-check')?.checked ?? true,
        })).filter(p => p.q || p.a);
    }

    _addQa() {
        const pairs = this._getQaPairs();
        pairs.push({ id: 'new_' + Date.now(), q: '', a: '', approved: true });
        this._renderQa(pairs);
        const qInputs = document.querySelectorAll('.ext-qa-q');
        if (qInputs.length) qInputs[qInputs.length - 1].focus();
    }

    // ─── Speichern & Verwerfen ───────────────────────────────────────────────

    async _approve() {
        if (!this._reviewing) return;
        const id         = this._reviewing.id;
        const isApproved = this._reviewIsApproved;
        const updated = {
            title:    document.getElementById('ext-edit-title').value.trim(),
            summary:  document.getElementById('ext-edit-summary').value.trim(),
            facts:    this._getFacts(),
            qa_pairs: this._getQaPairs(),
        };
        if (!updated.qa_pairs.filter(p => p.approved).length && !updated.facts.length) {
            this._notifyReview('Mindestens ein Fakt oder ein aktiviertes Q&A-Paar erforderlich.', 'error');
            return;
        }
        const btn = document.getElementById('ext-save-btn');
        const origLabel = btn.textContent;
        btn.disabled = true; btn.textContent = '⏳ Speichere…';
        try {
            await fetch(`/api/knowledge/pending/${id}`, {
                method: 'PATCH',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(updated),
            });
            const r = await fetch(`/api/knowledge/pending/${id}/approve`, {
                method: 'POST', headers: _authHeaders(),
            });
            const d = await r.json();
            if (!r.ok || !d.ok) {
                this._notifyReview('Fehler: ' + (d.error || r.status), 'error');
            } else {
                const msg = isApproved
                    ? `💾 Aktualisiert: ${d.fact_count} Fakten + ${d.qa_count} Q&A-Paare`
                    : `✅ Gespeichert: ${d.fact_count} Fakten + ${d.qa_count} Q&A-Paare`;
                this._notify(msg);
                this._closeReview();
                this._loadPending();
            }
        } catch (e) {
            this._notifyReview('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            btn.disabled = false; btn.textContent = origLabel;
        }
    }

    async _reject() {
        if (!this._reviewing) return;
        if (this._reviewIsApproved) {
            await this._deleteApproved(this._reviewing.id);
        } else {
            if (!confirm('Extraktion wirklich verwerfen? Der Inhalt wird nicht gespeichert.')) return;
            await this._deletePending(this._reviewing.id);
        }
    }

    // ─── Download ────────────────────────────────────────────────────────────

    _downloadJson(doc) {
        const json = JSON.stringify(doc, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `jarvis_extract_${doc.id}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // ─── Hilfsmethoden ───────────────────────────────────────────────────────

    _notify(msg, type = 'success') {
        const el = document.getElementById('ext-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `kb-notification kb-notification-${type}`;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 5000);
    }

    _notifyReview(msg, type = 'error') {
        const el = document.getElementById('ext-review-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `kb-notification kb-notification-${type}`;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 5000);
    }

    _esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
})();
