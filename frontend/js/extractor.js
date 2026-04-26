/**
 * Jarvis Web-Extraktor
 * URL → LLM-Extraktion → Validierung durch Mensch → Wissens-DB
 * Eingebettet in den Wissen-Tab (kein eigener Settings-Tab).
 * Design: kb-section System
 */
window.extractorManager = new (class JarvisExtractorManager {

    constructor() {
        this._pending     = [];
        this._reviewing   = null;
        this._container   = null;
        this._infoModal   = null;
        this._initialized = false;
    }

    init() {
        this._container = document.getElementById('extractor-tab-content');
        if (!this._container) return;
        if (!this._initialized) {
            this._renderInfoModal();   // Info-Modal global an <body>
            this._renderSections();    // Sektionen in den Wissen-Tab
            this._initialized = true;
        }
        this._loadPending();
    }

    // ─── Info-Modal (an <body> angehängt, damit fixed-Overlay funktioniert) ──

    _renderInfoModal() {
        if (document.getElementById('ext-info-modal')) return;
        const modal = document.createElement('div');
        modal.id = 'ext-info-modal';
        modal.className = 'modal-overlay hidden';
        modal.innerHTML = `
            <div class="modal-card" style="max-width:520px;text-align:left;">
                <h2 class="modal-title">URL-Informationsextraktor</h2>

                <div class="ext-info-step">
                    <span class="ext-info-num">1</span>
                    <div>
                        <strong>URL eingeben</strong><br>
                        <span class="kb-hint" style="margin:0;">Gib die Adresse einer Webseite ein, deren Inhalt du in die Wissensdatenbank aufnehmen möchtest.</span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">2</span>
                    <div>
                        <strong>Extraktion starten</strong><br>
                        <span class="kb-hint" style="margin:0;">Jarvis ruft die Seite ab und analysiert den Inhalt mit dem konfigurierten LLM. Dabei werden automatisch eine Zusammenfassung, Kernfakten und Frage-Antwort-Paare generiert.</span>
                    </div>
                </div>
                <div class="ext-info-step">
                    <span class="ext-info-num">3</span>
                    <div>
                        <strong>Ergebnis validieren</strong><br>
                        <span class="kb-hint" style="margin:0;">Öffne das Dokument über <em>Prüfen</em>. Du kannst Titel, Zusammenfassung und Fakten bearbeiten sowie einzelne Frage-Antwort-Paare aktivieren, deaktivieren, bearbeiten oder löschen. Neue Paare können hinzugefügt werden.</span>
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
                        <strong>Hinweis:</strong> Nicht gespeicherte Extraktionen bleiben im Bereich <em>Ausstehend</em> und können jederzeit geprüft oder verworfen werden. Funktioniert nur mit öffentlich erreichbaren Webseiten.
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

    // ─── Sektionen im Wissen-Tab ─────────────────────────────────────────────

    _renderSections() {
        this._container.innerHTML = `

            <!-- Extraktor: URL-Eingabe -->
            <div class="kb-section">
                <div class="kb-section-header">
                    <h3>URL-Informationsextraktor</h3>
                    <button id="ext-info-btn" class="kb-btn-secondary" title="Anleitung">❓</button>
                </div>
                <p class="kb-hint">Webseiten-Inhalt per LLM in strukturiertes Wissen umwandeln – mit menschlicher Validierung vor der Ablage.</p>
                <div style="display:flex;gap:8px;margin-top:4px;">
                    <input id="ext-url-input" type="url" placeholder="https://beispiel.de/artikel" class="kb-input" style="flex:1;">
                    <button id="ext-extract-btn" class="kb-btn-action">Extrahieren</button>
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

            <!-- Extraktor: Review -->
            <div id="ext-review-wrap" class="kb-section" style="display:none;">
                <div class="kb-section-header">
                    <h3 id="ext-review-title">Dokument prüfen</h3>
                    <button id="ext-review-close" class="kb-btn-secondary">✕</button>
                </div>
                <p class="kb-hint" id="ext-review-url" style="word-break:break-all;margin-bottom:12px;"></p>

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

        document.getElementById('ext-info-btn').onclick    = () => this._showInfo();
        document.getElementById('ext-extract-btn').onclick = () => this._startExtract();
        document.getElementById('ext-refresh-btn').onclick = () => this._loadPending();
        document.getElementById('ext-review-close').onclick = () => this._closeReview();
        document.getElementById('ext-add-fact-btn').onclick = () => this._addFact();
        document.getElementById('ext-add-qa-btn').onclick   = () => this._addQa();
        document.getElementById('ext-save-btn').onclick    = () => this._approve();
        document.getElementById('ext-reject-btn').onclick  = () => this._reject();

        document.getElementById('ext-url-input').addEventListener('keydown', e => {
            if (e.key === 'Enter') this._startExtract();
        });
    }

    // ─── Extraktion starten ──────────────────────────────────────────────────

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
                body: JSON.stringify({ url })
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

    // ─── Pending-Liste ───────────────────────────────────────────────────────

    async _loadPending() {
        try {
            const r = await fetch('/api/knowledge/pending', { headers: _authHeaders() });
            if (!r.ok) return;
            this._pending = await r.json();
            this._renderPending();
        } catch (e) { console.error('[Extractor]', e); }
    }

    _renderPending() {
        const el    = document.getElementById('ext-pending-list');
        const badge = document.getElementById('ext-pending-count');
        if (!el) return;
        badge.textContent = this._pending.length;
        badge.style.display = this._pending.length ? 'inline-block' : 'none';

        if (!this._pending.length) {
            el.innerHTML = `<p class="kb-empty">Keine ausstehenden Extraktionen.</p>`;
            return;
        }
        el.innerHTML = this._pending.map(doc => {
            const dt     = new Date(doc.created_at * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
            const qa     = doc.qa_pairs?.length || 0;
            const fct    = doc.facts?.length    || 0;
            const domain = (() => { try { return new URL(doc.url).hostname; } catch { return doc.url; } })();
            return `
            <div class="cron-item" data-id="${doc.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot active"></span>
                    <span class="cron-item-label">${this._esc(doc.title)}</span>
                    <div class="cron-item-actions">
                        <button class="kb-btn-action ext-review-btn" data-id="${doc.id}" style="padding:3px 10px;font-size:.75rem;">Prüfen</button>
                        <button class="kb-btn-danger ext-del-btn"    data-id="${doc.id}" style="padding:3px 8px;font-size:.75rem;">🗑️</button>
                    </div>
                </div>
                <div class="cron-item-meta">${this._esc(domain)} · ${dt} · ${fct} Fakten · ${qa} Q&amp;A-Paare</div>
            </div>`;
        }).join('');

        el.querySelectorAll('.ext-review-btn').forEach(btn => {
            btn.onclick = () => {
                const doc = this._pending.find(d => d.id === btn.dataset.id);
                if (doc) this._openReview(doc);
            };
        });
        el.querySelectorAll('.ext-del-btn').forEach(btn => {
            btn.onclick = () => this._deletePending(btn.dataset.id);
        });
    }

    async _deletePending(id) {
        if (!confirm('Extraktion wirklich verwerfen?')) return;
        await fetch(`/api/knowledge/pending/${id}`, { method: 'DELETE', headers: _authHeaders() });
        if (this._reviewing?.id === id) this._closeReview();
        this._loadPending();
        this._notify('Extraktion verworfen', 'info');
    }

    // ─── Review ──────────────────────────────────────────────────────────────

    _openReview(doc) {
        this._reviewing = doc;
        document.getElementById('ext-review-wrap').style.display = '';
        document.getElementById('ext-review-title').textContent  = `Dokument prüfen – ${doc.title}`;
        document.getElementById('ext-review-url').innerHTML =
            `🔗 <a href="${this._esc(doc.url)}" target="_blank" style="color:var(--accent);">${this._esc(doc.url)}</a>`;
        document.getElementById('ext-edit-title').value   = doc.title   || '';
        document.getElementById('ext-edit-summary').value = doc.summary || '';
        this._renderFacts(doc.facts || []);
        this._renderQa(doc.qa_pairs || []);
        document.getElementById('ext-review-wrap').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    _closeReview() {
        this._reviewing = null;
        document.getElementById('ext-review-wrap').style.display = 'none';
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
        const id = this._reviewing.id;
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
        btn.disabled = true; btn.textContent = '⏳ Speichere…';
        try {
            await fetch(`/api/knowledge/pending/${id}`, {
                method: 'PATCH',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(updated)
            });
            const r = await fetch(`/api/knowledge/pending/${id}/approve`, {
                method: 'POST', headers: _authHeaders()
            });
            const d = await r.json();
            if (!r.ok || !d.ok) {
                this._notifyReview('Fehler: ' + (d.error || r.status), 'error');
            } else {
                this._notify(`✅ Gespeichert: ${d.fact_count} Fakten + ${d.qa_count} Q&A-Paare`);
                this._closeReview();
                this._loadPending();
            }
        } catch (e) {
            this._notifyReview('Netzwerkfehler: ' + e.message, 'error');
        } finally {
            btn.disabled = false; btn.textContent = '✅ In Wissens-DB speichern';
        }
    }

    async _reject() {
        if (!this._reviewing) return;
        if (!confirm('Extraktion wirklich verwerfen? Der Inhalt wird nicht gespeichert.')) return;
        await this._deletePending(this._reviewing.id);
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
