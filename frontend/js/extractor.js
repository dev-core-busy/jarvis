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
        this._cfEnabled        = false;  // Confluence-Sub-Tab sichtbar?
        this._cfSpaces         = null;   // gecachte Bereichsliste
        this._selectedSpaceKey = '';     // aktuell gewählter Bereich
        this._ddOpen           = false;  // Bereichs-Dropdown offen?
        this._ddIndex          = -1;     // Tastatur-Markierung im Dropdown
        this._ddList           = [];     // aktuell angezeigte Treffer
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
        // Confluence-Sichtbarkeit erneut anwenden (Button existiert erst nach Render)
        this.setConfluenceEnabled(this._cfEnabled);
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
                <h2 class="modal-title">${window.t('ext.title')}</h2>

                <div class="ext-info-step">
                    <span class="ext-info-num">1</span>
                    <div>
                        <strong>Quelle wählen</strong><br>
                        <span class="kb-hint" style="margin:0;">
                            <strong>URL:</strong> Adresse einer öffentlich erreichbaren Webseite eingeben.<br>
                            <strong>Datei:</strong> Datei per Drag &amp; Drop ablegen oder über den Datei-Browser wählen.
                            Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV,
                            sowie Audio/Video (MP3, MP4, MOV …) via Whisper-Transkription.<br>
                            <strong>Confluence:</strong> (nur bei aktivem Skill) Bereich wählen, dann eine einzelne
                            Seite oder den ganzen Bereich importieren – wahlweise mit Review oder
                            <em>ohne Audit</em> direkt in die Wissens-DB.
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
                        <span class="kb-hint" style="margin:0;">Öffne das Dokument über <em>${window.t('ext.check_btn')}</em>. Du kannst Titel, Zusammenfassung und Fakten bearbeiten sowie einzelne Frage-Antwort-Paare aktivieren, deaktivieren, bearbeiten oder löschen.</span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">4</span>
                    <div>
                        <strong>In Wissens-DB speichern</strong><br>
                        <span class="kb-hint" style="margin:0;">Klicke auf <em>${window.t('ext.save_btn')}</em>. Nur aktivierte Elemente werden übernommen. Das Dokument wird als Markdown-Datei angelegt und der Suchindex automatisch neu aufgebaut.</span>
                    </div>
                </div>

                <div style="background:rgba(var(--fg-rgb),0.04);border-radius:8px;padding:10px 14px;margin-top:4px;">
                    <p class="kb-hint" style="margin:0;">
                        <strong>Hinweis:</strong> Nicht gespeicherte Extraktionen bleiben im Bereich <em>${window.t('ext.pending')}</em>.
                        Audio/Video-Transkription erfordert faster-whisper + ffmpeg auf dem Server.
                    </p>
                </div>

                <button class="btn-modal-close" id="ext-info-close" style="margin-top:16px;">${window.t('common.close')}</button>
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
                    <h3>${window.t('ext.title')}</h3>
                    <button id="ext-info-btn" class="kb-btn-secondary" title="${window.t('ext.info_title')}">❓</button>
                </div>
                <p class="kb-hint">${window.t('ext.hint')}</p>

                <!-- Sub-Tabs -->
                <div class="ext-input-tabs">
                    <button class="ext-input-tab active" id="ext-tab-url">🌐 URL</button>
                    <button class="ext-input-tab"        id="ext-tab-file">📄 Datei</button>
                    <button class="ext-input-tab"        id="ext-tab-confluence" style="display:none;">📘 Confluence</button>
                </div>

                <!-- Panel: URL -->
                <div id="ext-panel-url">
                    <div style="display:flex;gap:8px;">
                        <input id="ext-url-input" type="url" placeholder="https://beispiel.de/artikel" class="kb-input" style="flex:1;">
                        <button id="ext-extract-btn" class="kb-btn-action">${window.t('ext.extract_btn')}</button>
                        <button id="ext-extract-cancel-btn" class="kb-btn-danger" style="display:none;">${window.t('common.cancel')}</button>
                    </div>
                </div>

                <!-- Panel: Datei -->
                <div id="ext-panel-file" style="display:none;">
                    <div class="ext-drop-zone" id="ext-drop-zone">
                        <input type="file" id="ext-file-input"
                            accept=".pdf,.txt,.md,.rst,.csv,.docx,.doc,.xlsx,.ods,.pptx,.jpg,.jpeg,.png,.gif,.bmp,.tif,.tiff,.webp,.mp3,.m4a,.wav,.ogg,.mp4,.mov,.mkv,.avi">
                        <div style="font-size:1.8rem;line-height:1;">📄</div>
                        <div class="ext-drop-zone-label">Datei hierher ziehen oder <span style="color:var(--accent);text-decoration:underline;cursor:pointer;">durchsuchen</span></div>
                        <div class="ext-drop-zone-hint">PDF · DOCX · XLSX · PPTX · TXT · MD · CSV · MP3 · MP4 · MOV · max. 50 MB</div>
                    </div>
                    <!-- Drop-Banner: erscheint nach DnD-Ablage -->
                    <div id="ext-drop-banner" class="ext-drop-banner" style="display:none;margin-top:8px;">
                        <span style="font-size:1.1rem;">📄</span>
                        <span class="ext-drop-banner-name" id="ext-drop-name">–</span>
                        <span class="ext-drop-banner-size" id="ext-drop-size"></span>
                        <button id="ext-drop-analyse-btn" class="kb-btn-action" style="padding:.35rem .9rem;font-size:.8rem;flex-shrink:0;">${window.t('ext.analyse_btn')}</button>
                        <button id="ext-drop-abort-btn" class="kb-btn-danger" style="padding:.35rem .9rem;font-size:.8rem;flex-shrink:0;display:none;">${window.t('common.cancel')}</button>
                        <button id="ext-drop-cancel-btn"  class="kb-btn-secondary" style="padding:.35rem .6rem;font-size:.8rem;flex-shrink:0;">✕</button>
                    </div>
                </div>

                <!-- Panel: Confluence -->
                <div id="ext-panel-confluence" style="display:none;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                        <div id="ext-cf-space-box" style="position:relative;flex:1;min-width:180px;">
                            <input type="text" id="ext-cf-space-search" class="kb-input" placeholder="Bereich suchen…"
                                   autocomplete="off" style="width:100%;box-sizing:border-box;">
                            <div id="ext-cf-space-dd" style="display:none;position:absolute;z-index:50;left:0;right:0;
                                 top:calc(100% + 2px);max-height:260px;overflow-y:auto;background:var(--bg-secondary);
                                 border:1px solid var(--border);border-radius:8px;
                                 box-shadow:0 8px 24px rgba(var(--shadow-rgb),0.4);"></div>
                        </div>
                        <label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;white-space:nowrap;cursor:pointer;">
                            <input type="checkbox" id="ext-cf-personal"> persönliche
                        </label>
                        <button id="ext-cf-refresh" class="kb-btn-secondary" title="Bereiche neu laden" style="flex-shrink:0;">🔄</button>
                    </div>
                    <label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;margin-bottom:10px;cursor:pointer;">
                        <input type="checkbox" id="ext-cf-no-audit"> ohne Audit – direkt in die Wissens-DB (kein Review)
                    </label>
                    <div id="ext-cf-page-wrap" style="display:none;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
                        <select id="ext-cf-page" class="kb-input" style="flex:1;min-width:180px;">
                            <option value="">– Seite wählen –</option>
                        </select>
                        <button id="ext-cf-import-page" class="kb-btn-action" style="flex-shrink:0;">Seite importieren</button>
                    </div>
                    <div id="ext-cf-bulk-wrap" style="display:none;align-items:center;gap:10px;flex-wrap:wrap;">
                        <button id="ext-cf-import-space" class="kb-btn-secondary">Ganzen Bereich importieren</button>
                        <span class="kb-hint" id="ext-cf-bulk-hint" style="margin:0;"></span>
                    </div>
                </div>

                <div id="ext-extract-status" class="kb-hint" style="margin-top:6px;display:none;"></div>
                <div id="ext-notification" class="kb-notification" style="display:none;margin-top:8px;"></div>
            </div>

            <!-- Extraktor: Pending-Liste -->
            <div class="kb-section">
                <div class="kb-section-header">
                    <h3>${window.t('ext.pending')} <span id="ext-pending-count" class="ext-badge" style="display:none;">0</span></h3>
                    <button id="ext-refresh-btn" class="kb-btn-secondary" title="${window.t('ext.refresh_title')}">🔄</button>
                </div>
                <div id="ext-pending-list"><p class="kb-empty">${window.t('ext.no_pending')}</p></div>
            </div>

            <!-- Extraktor: Genehmigter Verlauf -->
            <div class="kb-section" id="ext-approved-section" style="display:none;">
                <div class="kb-section-header">
                    <h3>${window.t('ext.approved_section')} <span id="ext-approved-count" class="ext-badge ext-badge-approved" style="display:none;">0</span></h3>
                </div>
                <div id="ext-approved-list"></div>
            </div>

            <!-- Extraktor: Review -->
            <div id="ext-review-wrap" class="kb-section" style="display:none;">
                <div class="kb-section-header">
                    <h3 id="ext-review-title">${window.t('ext.review_title')}</h3>
                    <button id="ext-review-close" class="kb-btn-secondary">✕</button>
                </div>
                <p class="kb-hint" id="ext-review-source" style="word-break:break-all;margin-bottom:12px;"></p>

                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">${window.t('ext.title_label')}</label>
                    <input id="ext-edit-title" type="text" class="kb-input" style="width:100%;box-sizing:border-box;">
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">${window.t('ext.summary_label')}</label>
                    <textarea id="ext-edit-summary" rows="3" class="kb-input" style="width:100%;box-sizing:border-box;resize:vertical;"></textarea>
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">${window.t('ext.facts_label')}</label>
                    <div id="ext-facts-list" class="ext-facts-list"></div>
                    <button id="ext-add-fact-btn" class="kb-btn-secondary" style="margin-top:6px;font-size:.78rem;">${window.t('ext.add_fact')}</button>
                </div>
                <div class="kb-form-field" style="margin-bottom:10px;">
                    <label class="kb-label">${window.t('ext.qa_label')} <span class="kb-hint" style="margin:0;font-size:.73rem;">${window.t('ext.qa_hint')}</span></label>
                    <div id="ext-qa-list" class="ext-qa-list"></div>
                    <button id="ext-add-qa-btn" class="kb-btn-secondary" style="margin-top:6px;font-size:.78rem;">${window.t('ext.add_qa')}</button>
                </div>

                <div class="kb-form-footer" style="margin-top:12px;">
                    <button id="ext-reject-btn" class="kb-btn-danger" style="padding:.45rem 1rem;font-size:.82rem;">${window.t('ext.reject_btn')}</button>
                    <div class="kb-form-footer-right">
                        <button id="ext-save-btn" class="kb-btn-action">${window.t('ext.save_btn')}</button>
                    </div>
                </div>
                <div id="ext-review-notification" class="kb-notification" style="display:none;margin-top:8px;"></div>
            </div>
        `;

        // Tab-Buttons
        document.getElementById('ext-tab-url').onclick  = () => this._switchInputTab('url');
        document.getElementById('ext-tab-file').onclick = () => this._switchInputTab('file');
        document.getElementById('ext-tab-confluence').onclick = () => this._switchInputTab('confluence');

        // Confluence-Tab
        document.getElementById('ext-cf-refresh').onclick   = () => this._loadCfSpaces(true);
        document.getElementById('ext-cf-personal').onchange = () => { if (this._ddOpen) this._renderCfSpaceDropdown(); };
        const cfSearch = document.getElementById('ext-cf-space-search');
        cfSearch.addEventListener('input', () => this._onSpaceSearchInput());
        cfSearch.addEventListener('focus', () => this._openSpaceDropdown());
        cfSearch.addEventListener('keydown', e => this._spaceSearchKey(e));
        cfSearch.addEventListener('blur', () => setTimeout(() => this._closeSpaceDropdown(), 150));
        document.getElementById('ext-cf-import-page').onclick  = () => this._importCfPage();
        document.getElementById('ext-cf-import-space').onclick = () => this._importCfSpace();

        // URL-Tab
        document.getElementById('ext-info-btn').onclick    = () => this._showInfo();
        document.getElementById('ext-extract-btn').onclick = () => this._startExtract();
        document.getElementById('ext-extract-cancel-btn').onclick = () => this._abortExtract();
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
        document.getElementById('ext-drop-abort-btn').onclick = () => this._abortExtract();
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
        const cfTab = document.getElementById('ext-tab-confluence');
        if (cfTab) cfTab.classList.toggle('active', tab === 'confluence');
        document.getElementById('ext-panel-url').style.display  = tab === 'url'  ? '' : 'none';
        document.getElementById('ext-panel-file').style.display = tab === 'file' ? '' : 'none';
        const cfPanel = document.getElementById('ext-panel-confluence');
        if (cfPanel) cfPanel.style.display = tab === 'confluence' ? '' : 'none';
        if (tab === 'confluence' && !this._cfSpaces) this._loadCfSpaces(false);
    }

    // ─── Confluence-Importquelle ───────────────────────────────────────────────

    /** Blendet den Confluence-Sub-Tab ein/aus (je nach Skill-Aktivierung). */
    setConfluenceEnabled(on) {
        this._cfEnabled = !!on;
        const btn = document.getElementById('ext-tab-confluence');
        if (btn) btn.style.display = on ? '' : 'none';
        // Falls der aktive Tab wegfällt → zurück auf URL
        if (!on && this._activeInputTab === 'confluence') this._switchInputTab('url');
    }

    _loadCfSpaces(force) {
        const input = document.getElementById('ext-cf-space-search');
        if (!input) return;
        if (this._cfSpaces && !force) { if (this._ddOpen) this._renderCfSpaceDropdown(); return; }
        input.placeholder = 'Lädt Bereiche…';
        fetch('/api/confluence/spaces', { headers: this._authHeaders() })
            .then(r => r.json())
            .then(d => {
                if (!d || !d.ok) { input.placeholder = (d && d.error) || 'Fehler beim Laden'; return; }
                this._cfSpaces = d.spaces || [];
                input.placeholder = 'Bereich suchen… (' + this._filteredSpaces().length + ')';
                if (this._ddOpen) this._renderCfSpaceDropdown();
            })
            .catch(() => { input.placeholder = 'Fehler beim Laden'; });
    }

    /** Bereiche gemäß Suchtext + "persönliche"-Schalter gefiltert. */
    _filteredSpaces() {
        if (!this._cfSpaces) return [];
        const inclPersonal = document.getElementById('ext-cf-personal')?.checked;
        const q = (document.getElementById('ext-cf-space-search')?.value || '').trim().toLowerCase();
        return this._cfSpaces.filter(s => {
            if (!inclPersonal && s.type === 'personal') return false;
            if (q) {
                const hay = ((s.name || '') + ' ' + (s.key || '')).toLowerCase();
                if (hay.indexOf(q) === -1) return false;
            }
            return true;
        });
    }

    _onSpaceSearchInput() {
        // Tippen = Auswahl zurücksetzen, Seitenbereich verbergen, Liste eingrenzen
        this._selectedSpaceKey = '';
        const pw = document.getElementById('ext-cf-page-wrap'); if (pw) pw.style.display = 'none';
        const bw = document.getElementById('ext-cf-bulk-wrap'); if (bw) bw.style.display = 'none';
        this._ddIndex = -1;
        this._openSpaceDropdown();
    }

    _openSpaceDropdown() {
        this._ddOpen = true;
        if (!this._cfSpaces) { this._loadCfSpaces(false); return; }
        this._renderCfSpaceDropdown();
    }

    _closeSpaceDropdown() {
        this._ddOpen = false;
        const dd = document.getElementById('ext-cf-space-dd');
        if (dd) dd.style.display = 'none';
    }

    _renderCfSpaceDropdown() {
        const dd = document.getElementById('ext-cf-space-dd');
        if (!dd) return;
        const list = this._filteredSpaces();
        const CAP = 200;
        const shown = list.slice(0, CAP);
        this._ddList = shown;
        if (this._ddIndex >= shown.length) this._ddIndex = -1;
        if (!shown.length) {
            dd.innerHTML = '<div style="padding:8px 10px;color:var(--text-secondary);font-size:0.85rem;">Keine Treffer</div>';
            dd.style.display = '';
            return;
        }
        dd.innerHTML = shown.map((s, i) =>
            '<div class="ext-cf-opt" data-key="' + this._attr(s.key) + '" data-i="' + i + '" '
            + 'style="padding:7px 10px;cursor:pointer;font-size:0.86rem;'
            + (i === this._ddIndex ? 'background:rgba(var(--accent-rgb),0.18);' : '') + '">'
            + this._esc(s.name) + ' <span style="color:var(--text-secondary);">('
            + this._esc(s.key) + (s.type === 'personal' ? ', persönlich' : '') + ')</span></div>'
        ).join('')
        + (list.length > CAP
            ? '<div style="padding:6px 10px;color:var(--text-secondary);font-size:0.78rem;">… '
              + (list.length - CAP) + ' weitere – weiter tippen zum Eingrenzen</div>'
            : '');
        dd.style.display = '';
        dd.querySelectorAll('.ext-cf-opt').forEach(el => {
            el.addEventListener('mousedown', ev => {
                ev.preventDefault();   // verhindert blur vor der Auswahl
                this._selectSpace(el.getAttribute('data-key'));
            });
            el.addEventListener('mouseover', () => {
                this._ddIndex = parseInt(el.getAttribute('data-i'), 10);
                this._highlightDd();
            });
        });
    }

    _highlightDd() {
        const dd = document.getElementById('ext-cf-space-dd');
        if (!dd) return;
        dd.querySelectorAll('.ext-cf-opt').forEach(el => {
            const i = parseInt(el.getAttribute('data-i'), 10);
            el.style.background = (i === this._ddIndex) ? 'rgba(var(--accent-rgb),0.18)' : '';
        });
    }

    _spaceSearchKey(e) {
        if (!this._ddOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { this._openSpaceDropdown(); return; }
        const n = (this._ddList || []).length;
        if (e.key === 'ArrowDown') {
            e.preventDefault(); this._ddIndex = Math.min(this._ddIndex + 1, n - 1);
            this._highlightDd(); this._scrollDdIntoView();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault(); this._ddIndex = Math.max(this._ddIndex - 1, 0);
            this._highlightDd(); this._scrollDdIntoView();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const pick = (this._ddList || [])[this._ddIndex] || (this._ddList || [])[0];
            if (pick) this._selectSpace(pick.key);
        } else if (e.key === 'Escape') {
            this._closeSpaceDropdown();
        }
    }

    _scrollDdIntoView() {
        const dd = document.getElementById('ext-cf-space-dd');
        const el = dd && dd.querySelector('.ext-cf-opt[data-i="' + this._ddIndex + '"]');
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    _selectSpace(key) {
        const sp = (this._cfSpaces || []).find(s => s.key === key);
        if (!sp) return;
        this._selectedSpaceKey = key;
        const input = document.getElementById('ext-cf-space-search');
        if (input) input.value = sp.name + ' (' + sp.key + ')';
        this._closeSpaceDropdown();
        this._onCfSpaceChange();
    }

    _onCfSpaceChange() {
        const space = this._selectedSpaceKey || '';
        const pageWrap = document.getElementById('ext-cf-page-wrap');
        const bulkWrap = document.getElementById('ext-cf-bulk-wrap');
        const pageSel  = document.getElementById('ext-cf-page');
        if (!space) {
            if (pageWrap) pageWrap.style.display = 'none';
            if (bulkWrap) bulkWrap.style.display = 'none';
            return;
        }
        if (pageWrap) pageWrap.style.display = 'flex';
        if (bulkWrap) bulkWrap.style.display = 'flex';
        if (pageSel) { pageSel.disabled = true; pageSel.innerHTML = '<option value="">Lädt…</option>'; }
        document.getElementById('ext-cf-bulk-hint').textContent = '';
        fetch('/api/confluence/pages?space=' + encodeURIComponent(space), { headers: this._authHeaders() })
            .then(r => r.json())
            .then(d => {
                if (!d || !d.ok) {
                    if (pageSel) pageSel.innerHTML = '<option value="">' + ((d && d.error) || 'Fehler') + '</option>';
                    return;
                }
                const pages = d.pages || [];
                if (pageSel) {
                    pageSel.disabled = false;
                    pageSel.innerHTML = '<option value="">– Seite wählen –</option>'
                        + pages.map(p => '<option value="' + this._attr(p.id) + '">'
                            + this._esc(p.title) + '</option>').join('');
                }
                document.getElementById('ext-cf-bulk-hint').textContent =
                    pages.length + ' Seite(n) im Bereich';
            })
            .catch(() => { if (pageSel) pageSel.innerHTML = '<option value="">Fehler</option>'; });
    }

    _setExtractStatus(msg, show) {
        const status = document.getElementById('ext-extract-status');
        if (!status) return;
        status.textContent = msg || '';
        status.style.display = show ? 'block' : 'none';
    }

    _cfAudit() {
        // true = mit Review (Pending), false = auditlos direkt in die Wissens-DB
        return !document.getElementById('ext-cf-no-audit')?.checked;
    }

    _importCfPage() {
        const pageId = document.getElementById('ext-cf-page')?.value || '';
        if (!pageId) { this._notify('Bitte zuerst eine Seite wählen.', 'error'); return; }
        const audit = this._cfAudit();
        const btn = document.getElementById('ext-cf-import-page');
        if (btn) btn.disabled = true;
        this._setExtractStatus(audit ? '⏳ Importiere Seite…' : '⏳ Importiere direkt…', true);
        fetch('/api/knowledge/extract/confluence', {
            method: 'POST',
            headers: this._authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ page_id: pageId, audit }),
        })
            .then(r => r.json().then(j => ({ ok: r.ok, j })))
            .then(({ ok, j }) => {
                this._setExtractStatus('', false);
                if (btn) btn.disabled = false;
                if (!ok) { this._notify('Fehler: ' + (j.error || 'Import fehlgeschlagen'), 'error'); return; }
                this._loadPending();
                if (audit) {
                    this._notify(`✅ Seite importiert: „${j.title}"`);
                    setTimeout(() => this._openReview(j), 300);
                } else {
                    this._notify(`✅ Direkt in die Wissens-DB übernommen: „${j.title}"`);
                }
            })
            .catch(() => {
                this._setExtractStatus('', false);
                if (btn) btn.disabled = false;
                this._notify('Netzwerkfehler beim Import', 'error');
            });
    }

    _importCfSpace() {
        const space = this._selectedSpaceKey || '';
        if (!space) { this._notify('Bitte zuerst einen Bereich wählen.', 'error'); return; }
        const audit = this._cfAudit();
        const warn = audit
            ? 'Alle Seiten dieses Bereichs importieren? Das kann je nach Größe dauern.'
            : 'Alle Seiten dieses Bereichs OHNE Audit direkt in die Wissens-DB schreiben? '
              + 'Das kann je nach Größe dauern und überspringt die Prüfung.';
        if (!confirm(warn)) return;
        const btn = document.getElementById('ext-cf-import-space');
        if (btn) btn.disabled = true;
        this._setExtractStatus('⏳ Starte Bereichs-Import…', true);
        fetch('/api/knowledge/extract/confluence', {
            method: 'POST',
            headers: this._authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ space: space, audit }),
        })
            .then(r => r.json().then(j => ({ ok: r.ok, j })))
            .then(({ ok, j }) => {
                this._setExtractStatus('', false);
                if (btn) btn.disabled = false;
                if (!ok) { this._notify('Fehler: ' + (j.error || 'Import fehlgeschlagen'), 'error'); return; }
                if (audit) {
                    this._notify('⏳ Import von ' + j.total
                        + ' Seite(n) gestartet – sie erscheinen nach und nach unten in den Pending-Dokumenten.');
                } else {
                    this._notify('⏳ Auditloser Import von ' + j.total
                        + ' Seite(n) gestartet – sie werden direkt in die Wissens-DB geschrieben (Reindex am Ende).');
                }
                setTimeout(() => this._loadPending(), 3000);
            })
            .catch(() => {
                this._setExtractStatus('', false);
                if (btn) btn.disabled = false;
                this._notify('Netzwerkfehler beim Import', 'error');
            });
    }

    _authHeaders(extra) {
        const t = localStorage.getItem('jarvis_token') || '';
        return Object.assign({ 'Authorization': 'Bearer ' + t }, extra || {});
    }
    _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    }
    _attr(s) { return this._esc(s).replace(/"/g, '&quot;'); }

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
        if (!url) { this._notify(window.t('ext.url_required'), 'error'); return; }

        const btn    = document.getElementById('ext-extract-btn');
        const cancel = document.getElementById('ext-extract-cancel-btn');
        const status = document.getElementById('ext-extract-status');
        btn.disabled = true; btn.textContent = window.t('ext.running');
        if (cancel) cancel.style.display = '';
        status.textContent = window.t('ext.extracting');
        status.style.display = 'block';
        this._extractAbort = new AbortController();

        try {
            const r = await fetch('/api/knowledge/extract', {
                method: 'POST',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
                signal: this._extractAbort.signal,
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
            if (e && e.name === 'AbortError') this._notify(window.t('ext.cancelled'), 'error');
            else this._notify('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            this._extractAbort = null;
            btn.disabled = false; btn.textContent = window.t('ext.extract_btn');
            if (cancel) cancel.style.display = 'none';
            status.style.display = 'none';
        }
    }

    // Laufende Extraktion (URL oder Datei) abbrechen
    _abortExtract() {
        if (this._extractAbort) { try { this._extractAbort.abort(); } catch (e) {} }
    }

    // ─── Datei-Extraktion ────────────────────────────────────────────────────

    async _startExtractFile(file) {
        const banner = document.getElementById('ext-drop-banner');
        const btn    = document.getElementById('ext-drop-analyse-btn');
        const cancel = document.getElementById('ext-drop-abort-btn');
        const status = document.getElementById('ext-extract-status');

        btn.disabled = true; btn.textContent = window.t('ext.running');
        if (cancel) cancel.style.display = '';
        status.textContent = `„${file.name}" ${window.t('ext.running').replace('⏳ ', '')} (${file.type || '?'})…`;
        status.style.display = 'block';
        this._extractAbort = new AbortController();

        try {
            const form = new FormData();
            form.append('file', file);
            const r = await fetch('/api/knowledge/extract/upload', {
                method: 'POST',
                headers: _authHeaders(),   // kein Content-Type – FormData setzt es selbst
                body: form,
                signal: this._extractAbort.signal,
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
            if (e && e.name === 'AbortError') this._notify(window.t('ext.cancelled'), 'error');
            else this._notify('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            this._extractAbort = null;
            btn.disabled = false; btn.textContent = window.t('ext.analyse_btn');
            if (cancel) cancel.style.display = 'none';
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
            el.innerHTML = `<p class="kb-empty">${window.t('ext.no_pending')}</p>`;
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
                            <button class="kb-btn-action ext-review-btn" data-id="${doc.id}" style="padding:3px 10px;font-size:.75rem;">${window.t('ext.check_btn')}</button>
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
        if (!confirm(window.t('ext.delete_approved_confirm'))) return;
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
            isApproved ? `${window.t('common.edit')} – ${doc.title}` : `${window.t('ext.review_title')} – ${doc.title}`;

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
        saveBtn.textContent   = isApproved ? window.t('ext.update_btn')    : window.t('ext.save_btn');
        rejectBtn.textContent = isApproved ? window.t('ext.remove_from_db') : window.t('ext.reject_btn');

        document.getElementById('ext-review-wrap').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    _closeReview() {
        this._reviewing        = null;
        this._reviewIsApproved = false;
        document.getElementById('ext-review-wrap').style.display = 'none';
        const saveBtn   = document.getElementById('ext-save-btn');
        const rejectBtn = document.getElementById('ext-reject-btn');
        if (saveBtn)   saveBtn.textContent   = window.t('ext.save_btn');
        if (rejectBtn) rejectBtn.textContent = window.t('ext.reject_btn');
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
                        <span style="font-size:.75rem;color:var(--text-secondary);">${window.t('ext.apply')}</span>
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
        btn.disabled = true; btn.textContent = window.t('ext.saving');
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
