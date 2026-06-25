/* ============================================================
 * issues.js – Issue-Tracker UI (shared)
 *
 * Wird in /index.html, /chat, /userchat geladen. Stellt einen Modal-Dialog
 * mit Liste, Detail, Erstellen, Editieren, Attachments bereit.
 *
 * API:
 *   JarvisIssues.open()      – Modal oeffnen (Listenansicht)
 *   JarvisIssues.create()    – Modal oeffnen + direkt im Erstell-Modus
 *
 * Auth: erwartet localStorage["jarvis_token"] (von app.js/chat.js gesetzt).
 * ============================================================ */
(function () {
    'use strict';

    if (window.JarvisIssues) return;  // doppeltes Laden vermeiden

    // Reihenfolge: app.js (index.html), chat.js (chat.html), userchat.js (userchat.html)
    const TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function _token() {
        for (const k of TOKEN_KEYS) {
            const v = localStorage.getItem(k);
            if (v) return v;
        }
        return '';
    }

    function _headers(extra) {
        const h = Object.assign({}, extra || {});
        const t = _token();
        if (t) h['Authorization'] = 'Bearer ' + t;
        return h;
    }

    function _escape(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function _fmtDate(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleString();
        } catch (e) {
            return iso;
        }
    }

    function _typeLabel(t) {
        return { bug: 'Bug', feature: 'Feature', improvement: 'Verbesserung' }[t] || t || '–';
    }

    function _statusLabel(s) {
        return { open: 'Offen', in_progress: 'In Arbeit', closed: 'Geschlossen' }[s] || s || '–';
    }

    function _statusColor(s) {
        return { open: '#3b82f6', in_progress: '#f59e0b', closed: '#10b981' }[s] || '#6b7280';
    }

    function _prioLabel(p) {
        return { low: 'Niedrig', medium: 'Mittel', high: 'Hoch' }[p] || p || '–';
    }

    // ─── State ────────────────────────────────────────────────────────
    let _modal = null;
    let _currentUser = '';
    let _isAdmin = false;
    let _detailIssueId = null;

    // ─── CSS einfuegen ────────────────────────────────────────────────
    function _injectCss() {
        if (document.getElementById('jv-issues-css')) return;
        const s = document.createElement('style');
        s.id = 'jv-issues-css';
        s.textContent = `
.jv-iss-overlay{position:fixed;inset:0;background:rgba(var(--shadow-rgb),.6);z-index:99999;
  display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);}
.jv-iss-modal{background:var(--bg-secondary);color:var(--text-primary);
  border:1px solid rgba(var(--accent-rgb),.4);
  border-radius:12px;width:min(900px,95vw);max-height:90vh;display:flex;flex-direction:column;
  box-shadow:0 20px 60px rgba(var(--shadow-rgb),.6);font-family:system-ui,-apple-system,sans-serif;}
.jv-iss-header{display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px;border-bottom:1px solid rgba(var(--fg-rgb),.08);}
.jv-iss-title{font-size:16px;font-weight:600;color:var(--text-primary);margin:0;}
.jv-iss-close{background:none;border:none;color:var(--text-secondary);font-size:22px;cursor:pointer;
  line-height:1;padding:0 4px;}
.jv-iss-close:hover{color:var(--text-primary);}
.jv-iss-body{padding:14px 18px;overflow-y:auto;flex:1;min-height:0;}
.jv-iss-footer{padding:12px 18px;border-top:1px solid rgba(var(--fg-rgb),.08);
  display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;}
.jv-iss-btn{padding:7px 14px;border-radius:6px;font-size:13px;cursor:pointer;
  border:1px solid rgba(var(--fg-rgb),.15);background:rgba(var(--fg-rgb),.06);color:var(--text-primary);
  transition:background .15s,border-color .15s;font-family:inherit;}
.jv-iss-btn:hover{background:rgba(var(--fg-rgb),.12);}
.jv-iss-btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;}
.jv-iss-btn.primary:hover{background:var(--accent-hover);}
.jv-iss-btn.danger{background:#dc2626;border-color:#dc2626;color:#fff;}
.jv-iss-btn.danger:hover{background:#ef4444;}
.jv-iss-btn:disabled{opacity:.4;cursor:not-allowed;}
.jv-iss-toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;}
.jv-iss-toolbar select,.jv-iss-toolbar input{background:rgba(var(--fg-rgb),.06);
  border:1px solid rgba(var(--fg-rgb),.12);border-radius:5px;color:var(--text-primary);
  padding:5px 9px;font-size:13px;font-family:inherit;}
.jv-iss-toolbar label{font-size:12px;color:var(--text-secondary);display:flex;align-items:center;gap:6px;}
.jv-iss-list{display:flex;flex-direction:column;gap:6px;}
.jv-iss-item{padding:10px 12px;border:1px solid rgba(var(--fg-rgb),.08);
  border-radius:8px;background:rgba(var(--fg-rgb),.02);cursor:pointer;transition:background .15s;}
.jv-iss-item:hover{background:rgba(var(--accent-rgb),.08);border-color:rgba(var(--accent-rgb),.3);}
.jv-iss-item-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.jv-iss-item-title{font-weight:600;color:var(--text-primary);font-size:14px;flex:1;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.jv-iss-badge{font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:.04em;color:#fff;background:#6b7280;}
.jv-iss-badge.bug{background:#dc2626;}
.jv-iss-badge.feature{background:#3b82f6;}
.jv-iss-badge.improvement{background:#10b981;}
.jv-iss-badge.prio-low{background:#6b7280;}
.jv-iss-badge.prio-medium{background:#f59e0b;}
.jv-iss-badge.prio-high{background:#dc2626;}
.jv-iss-item-meta{font-size:11px;color:var(--text-muted);margin-top:3px;display:flex;
  gap:10px;flex-wrap:wrap;}
.jv-iss-item-author{color:var(--text-secondary);}
.jv-iss-empty{text-align:center;padding:40px 16px;color:var(--text-muted);}
.jv-iss-form-row{margin-bottom:12px;}
.jv-iss-form-row label{display:block;font-size:12px;color:var(--text-secondary);
  margin-bottom:4px;font-weight:500;}
.jv-iss-form-row input[type="text"],
.jv-iss-form-row textarea,
.jv-iss-form-row select{width:100%;background:rgba(var(--fg-rgb),.06);
  border:1px solid rgba(var(--fg-rgb),.12);border-radius:6px;color:var(--text-primary);
  padding:7px 10px;font-size:13px;font-family:inherit;box-sizing:border-box;}
.jv-iss-form-row textarea{min-height:100px;resize:vertical;line-height:1.5;}
.jv-iss-form-row input:focus,
.jv-iss-form-row textarea:focus,
.jv-iss-form-row select:focus{outline:none;border-color:var(--accent);}
.jv-iss-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.jv-iss-detail-section{margin-bottom:14px;}
.jv-iss-detail-label{font-size:11px;color:var(--text-muted);text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:4px;}
.jv-iss-detail-value{color:var(--text-primary);line-height:1.5;font-size:13px;white-space:pre-wrap;
  word-break:break-word;}
.jv-iss-jarvis-comment{background:rgba(var(--accent-rgb),.08);border-left:3px solid var(--accent);
  border-radius:0 6px 6px 0;padding:10px 14px;}
.jv-iss-attach-list{display:flex;flex-direction:column;gap:6px;margin-top:6px;}
.jv-iss-attach-item{display:flex;align-items:center;gap:10px;padding:6px 10px;
  background:rgba(var(--fg-rgb),.04);border-radius:6px;font-size:12px;}
.jv-iss-attach-item a{color:var(--accent-hover);text-decoration:none;flex:1;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.jv-iss-attach-item a:hover{text-decoration:underline;}
.jv-iss-attach-thumb{max-width:120px;max-height:120px;border-radius:4px;cursor:pointer;}
.jv-iss-attach-del{background:none;border:none;color:#dc2626;cursor:pointer;
  font-size:14px;padding:0 4px;}
.jv-iss-attach-del:hover{color:#ef4444;}
.jv-iss-err{color:#ef4444;font-size:12px;padding:6px 0;}
.jv-iss-ok{color:#10b981;font-size:12px;padding:6px 0;}
@media(max-width:600px){
  .jv-iss-form-grid{grid-template-columns:1fr;}
  .jv-iss-modal{width:100vw;height:100vh;max-height:100vh;border-radius:0;}
}
        `;
        document.head.appendChild(s);
    }

    // ─── Modal-Skelett ────────────────────────────────────────────────
    function _ensureModal() {
        _injectCss();
        if (_modal) return _modal;
        const overlay = document.createElement('div');
        overlay.className = 'jv-iss-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="jv-iss-modal" role="dialog" aria-modal="true">
                <div class="jv-iss-header">
                    <h2 class="jv-iss-title" id="jv-iss-title">Issues</h2>
                    <button class="jv-iss-close" aria-label="Schliessen">&times;</button>
                </div>
                <div class="jv-iss-body" id="jv-iss-body"></div>
                <div class="jv-iss-footer" id="jv-iss-footer"></div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector('.jv-iss-close').addEventListener('click', close);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay.style.display !== 'none') close();
        });
        _modal = overlay;
        return overlay;
    }

    function open(initialView) {
        _ensureModal();
        _modal.style.display = 'flex';
        if (initialView === 'create') {
            _showForm(null);
        } else {
            _showList();
        }
    }

    function close() {
        if (_modal) _modal.style.display = 'none';
        _detailIssueId = null;
    }

    // ─── Liste ────────────────────────────────────────────────────────
    async function _showList() {
        document.getElementById('jv-iss-title').textContent = 'Issues – Feedback & Bugs';
        const body = document.getElementById('jv-iss-body');
        const footer = document.getElementById('jv-iss-footer');
        body.innerHTML = '<div class="jv-iss-empty">Lade …</div>';
        footer.innerHTML = `
            <button class="jv-iss-btn primary" id="jv-iss-new-btn">Neues Issue</button>
        `;
        document.getElementById('jv-iss-new-btn').onclick = () => _showForm(null);

        try {
            const res = await fetch('/api/issues', { headers: _headers() });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            _currentUser = data.current_user || '';
            _isAdmin = !!data.is_admin;
            _renderList(data.issues || []);
        } catch (e) {
            body.innerHTML = `<div class="jv-iss-err">Fehler beim Laden: ${_escape(e.message)}</div>`;
        }
    }

    function _renderList(issues) {
        const body = document.getElementById('jv-iss-body');
        body.innerHTML = `
            <div class="jv-iss-toolbar">
                <label>Status
                    <select id="jv-iss-flt-status">
                        <option value="">alle</option>
                        <option value="open">Offen</option>
                        <option value="in_progress">In Arbeit</option>
                        <option value="closed">Geschlossen</option>
                    </select>
                </label>
                <label>Typ
                    <select id="jv-iss-flt-type">
                        <option value="">alle</option>
                        <option value="bug">Bug</option>
                        <option value="feature">Feature</option>
                        <option value="improvement">Verbesserung</option>
                    </select>
                </label>
                <label><input type="checkbox" id="jv-iss-flt-mine"> nur meine</label>
                <span style="flex:1"></span>
                <span style="font-size:11px;color:var(--text-muted);">${issues.length} Issue(s)</span>
            </div>
            <div class="jv-iss-list" id="jv-iss-list"></div>
        `;

        function _apply() {
            const fs = document.getElementById('jv-iss-flt-status').value;
            const ft = document.getElementById('jv-iss-flt-type').value;
            const fm = document.getElementById('jv-iss-flt-mine').checked;
            let filtered = issues;
            if (fs) filtered = filtered.filter(i => i.status === fs);
            if (ft) filtered = filtered.filter(i => i.type === ft);
            if (fm) filtered = filtered.filter(i =>
                (i.author || '').toLowerCase() === _currentUser.toLowerCase());
            _renderItems(filtered);
        }
        document.getElementById('jv-iss-flt-status').onchange = _apply;
        document.getElementById('jv-iss-flt-type').onchange = _apply;
        document.getElementById('jv-iss-flt-mine').onchange = _apply;
        _renderItems(issues);
    }

    function _renderItems(items) {
        const list = document.getElementById('jv-iss-list');
        if (!items.length) {
            list.innerHTML = '<div class="jv-iss-empty">Keine Issues gefunden.</div>';
            return;
        }
        list.innerHTML = items.map(i => `
            <div class="jv-iss-item" data-id="${_escape(i.id)}">
                <div class="jv-iss-item-head">
                    <span class="jv-iss-badge ${_escape(i.type)}">${_typeLabel(i.type)}</span>
                    <span class="jv-iss-badge prio-${_escape(i.priority)}">${_prioLabel(i.priority)}</span>
                    <span class="jv-iss-item-title">${_escape(i.title)}</span>
                    <span class="jv-iss-badge" style="background:${_statusColor(i.status)}">${_statusLabel(i.status)}</span>
                </div>
                <div class="jv-iss-item-meta">
                    <span class="jv-iss-item-author" title="Melder">👤 ${_escape(i.author || '—')}</span>
                    <span>${_fmtDate(i.created)}</span>
                    ${(i.attachments && i.attachments.length) ? `<span>📎 ${i.attachments.length}</span>` : ''}
                </div>
            </div>
        `).join('');
        list.querySelectorAll('.jv-iss-item').forEach(el => {
            el.onclick = () => _showDetail(el.getAttribute('data-id'));
        });
    }

    // ─── Detail ───────────────────────────────────────────────────────
    async function _showDetail(id) {
        _detailIssueId = id;
        document.getElementById('jv-iss-title').textContent = 'Issue-Details';
        const body = document.getElementById('jv-iss-body');
        const footer = document.getElementById('jv-iss-footer');
        body.innerHTML = '<div class="jv-iss-empty">Lade …</div>';
        footer.innerHTML = '';

        try {
            const res = await fetch('/api/issues/' + encodeURIComponent(id),
                { headers: _headers() });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            _currentUser = data.current_user || '';
            _isAdmin = !!data.is_admin;
            _renderDetail(data.issue, data.can_edit, data.can_delete);
        } catch (e) {
            body.innerHTML = `<div class="jv-iss-err">Fehler: ${_escape(e.message)}</div>`;
        }
    }

    function _renderDetail(issue, canEdit, canDelete) {
        const body = document.getElementById('jv-iss-body');
        const footer = document.getElementById('jv-iss-footer');
        const attHtml = (issue.attachments || []).map(name => {
            const url = `/api/issues/${encodeURIComponent(issue.id)}/attachments/${encodeURIComponent(name)}?token=${encodeURIComponent(_token())}`;
            const isImg = /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(name);
            const delBtn = canEdit
                ? `<button class="jv-iss-attach-del" data-name="${_escape(name)}" title="Loeschen">✕</button>`
                : '';
            if (isImg) {
                return `<div class="jv-iss-attach-item">
                    <img src="${url}" class="jv-iss-attach-thumb" alt="${_escape(name)}"
                         onclick="window.open('${url}','_blank')">
                    <a href="${url}" download="${_escape(name)}">${_escape(name)}</a>
                    ${delBtn}
                </div>`;
            }
            return `<div class="jv-iss-attach-item">
                <span>📎</span>
                <a href="${url}" download="${_escape(name)}">${_escape(name)}</a>
                ${delBtn}
            </div>`;
        }).join('');

        body.innerHTML = `
            <div class="jv-iss-detail-section">
                <div class="jv-iss-item-head" style="margin-bottom:8px;">
                    <span class="jv-iss-badge ${_escape(issue.type)}">${_typeLabel(issue.type)}</span>
                    <span class="jv-iss-badge prio-${_escape(issue.priority)}">${_prioLabel(issue.priority)}</span>
                    <span class="jv-iss-badge" style="background:${_statusColor(issue.status)}">${_statusLabel(issue.status)}</span>
                </div>
                <div class="jv-iss-detail-value" style="font-size:16px;font-weight:600;color:var(--text-primary);">${_escape(issue.title)}</div>
                <div class="jv-iss-item-meta" style="margin-top:6px;">
                    <span class="jv-iss-item-author" title="Melder">👤 Gemeldet von: ${_escape(issue.author || '—')}</span>
                    <span>Erstellt: ${_fmtDate(issue.created)}</span>
                    <span>Aktualisiert: ${_fmtDate(issue.updated)}</span>
                </div>
            </div>
            <div class="jv-iss-detail-section">
                <div class="jv-iss-detail-label">Beschreibung</div>
                <div class="jv-iss-detail-value">${_escape(issue.body) || '<em style="color:var(--text-muted)">(leer)</em>'}</div>
            </div>
            ${issue.jarvis_comment ? `
            <div class="jv-iss-detail-section">
                <div class="jv-iss-detail-label">Antwort von Jarvis</div>
                <div class="jv-iss-jarvis-comment jv-iss-detail-value">${_escape(issue.jarvis_comment)}</div>
            </div>` : ''}
            <div class="jv-iss-detail-section">
                <div class="jv-iss-detail-label">Anhaenge</div>
                ${attHtml ? `<div class="jv-iss-attach-list">${attHtml}</div>` :
                    '<div style="color:var(--text-muted);font-size:12px;">(keine)</div>'}
                ${canEdit ? `
                    <div style="margin-top:8px;">
                        <input type="file" id="jv-iss-att-input" multiple style="display:none;">
                        <button class="jv-iss-btn" id="jv-iss-att-btn">+ Anhang hinzufuegen</button>
                        <span id="jv-iss-att-status" style="margin-left:8px;font-size:11px;color:var(--text-muted);"></span>
                    </div>` : ''}
            </div>
        `;

        // Attachment-Loesch-Buttons
        if (canEdit) {
            body.querySelectorAll('.jv-iss-attach-del').forEach(btn => {
                btn.onclick = async (e) => {
                    e.stopPropagation();
                    const name = btn.getAttribute('data-name');
                    if (!confirm('Anhang "' + name + '" wirklich loeschen?')) return;
                    try {
                        const r = await fetch(
                            `/api/issues/${encodeURIComponent(issue.id)}/attachments/${encodeURIComponent(name)}`,
                            { method: 'DELETE', headers: _headers() }
                        );
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        _showDetail(issue.id);
                    } catch (err) {
                        alert('Fehler: ' + err.message);
                    }
                };
            });

            const attBtn = document.getElementById('jv-iss-att-btn');
            const attInput = document.getElementById('jv-iss-att-input');
            const attStatus = document.getElementById('jv-iss-att-status');
            attBtn.onclick = () => attInput.click();
            attInput.onchange = async () => {
                const files = Array.from(attInput.files || []);
                if (!files.length) return;
                attStatus.textContent = 'Lade hoch …';
                let okCount = 0;
                for (const f of files) {
                    try {
                        const fd = new FormData();
                        fd.append('file', f);
                        const r = await fetch(
                            `/api/issues/${encodeURIComponent(issue.id)}/attachments`,
                            { method: 'POST', headers: _headers(), body: fd }
                        );
                        if (r.ok) okCount++;
                        else {
                            const t = await r.text();
                            attStatus.textContent = `Fehler bei ${f.name}: ${t}`;
                        }
                    } catch (err) {
                        attStatus.textContent = `Fehler bei ${f.name}: ${err.message}`;
                    }
                }
                if (okCount === files.length) {
                    attStatus.textContent = '';
                    _showDetail(issue.id);
                }
            };
        }

        // Footer-Buttons
        const buttons = [`<button class="jv-iss-btn" id="jv-iss-back-btn">← Zurueck</button>`];
        if (canEdit) buttons.push(`<button class="jv-iss-btn primary" id="jv-iss-edit-btn">Bearbeiten</button>`);
        if (_isAdmin) buttons.push(`<button class="jv-iss-btn primary" id="jv-iss-jarvis-btn">Jarvis-Bereich</button>`);
        if (canDelete) buttons.push(`<button class="jv-iss-btn danger" id="jv-iss-del-btn">Loeschen</button>`);
        footer.innerHTML = buttons.join('');

        document.getElementById('jv-iss-back-btn').onclick = () => _showList();
        if (canEdit) {
            document.getElementById('jv-iss-edit-btn').onclick = () => _showForm(issue);
        }
        if (_isAdmin) {
            document.getElementById('jv-iss-jarvis-btn').onclick = () => _showJarvisForm(issue);
        }
        if (canDelete) {
            document.getElementById('jv-iss-del-btn').onclick = async () => {
                if (!confirm('Issue wirklich loeschen? Anhaenge werden mit entfernt.')) return;
                try {
                    const r = await fetch('/api/issues/' + encodeURIComponent(issue.id),
                        { method: 'DELETE', headers: _headers() });
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    _showList();
                } catch (e) {
                    alert('Fehler: ' + e.message);
                }
            };
        }
    }

    // ─── Erstellen / Bearbeiten (User-Felder) ─────────────────────────
    function _showForm(issue) {
        const isEdit = !!issue;
        document.getElementById('jv-iss-title').textContent = isEdit ? 'Issue bearbeiten' : 'Neues Issue';
        const body = document.getElementById('jv-iss-body');
        const footer = document.getElementById('jv-iss-footer');

        body.innerHTML = `
            <div class="jv-iss-form-row">
                <label>Titel *</label>
                <input type="text" id="jv-iss-f-title" maxlength="200"
                       value="${_escape(issue ? issue.title : '')}">
            </div>
            <div class="jv-iss-form-grid">
                <div class="jv-iss-form-row">
                    <label>Typ</label>
                    <select id="jv-iss-f-type">
                        <option value="bug">Bug</option>
                        <option value="feature">Feature</option>
                        <option value="improvement">Verbesserung</option>
                    </select>
                </div>
                <div class="jv-iss-form-row">
                    <label>Prioritaet</label>
                    <select id="jv-iss-f-priority">
                        <option value="low">Niedrig</option>
                        <option value="medium">Mittel</option>
                        <option value="high">Hoch</option>
                    </select>
                </div>
            </div>
            <div class="jv-iss-form-row">
                <label>Beschreibung</label>
                <textarea id="jv-iss-f-body" maxlength="20000">${_escape(issue ? issue.body : '')}</textarea>
            </div>
            <div id="jv-iss-form-err" class="jv-iss-err" style="display:none;"></div>
        `;
        document.getElementById('jv-iss-f-type').value = issue ? issue.type : 'bug';
        document.getElementById('jv-iss-f-priority').value = issue ? issue.priority : 'medium';

        footer.innerHTML = `
            <button class="jv-iss-btn" id="jv-iss-cancel-btn">Abbrechen</button>
            <button class="jv-iss-btn primary" id="jv-iss-save-btn">${isEdit ? 'Speichern' : 'Erstellen'}</button>
        `;
        document.getElementById('jv-iss-cancel-btn').onclick =
            () => isEdit ? _showDetail(issue.id) : _showList();
        document.getElementById('jv-iss-save-btn').onclick = async () => {
            const errBox = document.getElementById('jv-iss-form-err');
            errBox.style.display = 'none';
            const payload = {
                title: document.getElementById('jv-iss-f-title').value.trim(),
                body: document.getElementById('jv-iss-f-body').value,
                type: document.getElementById('jv-iss-f-type').value,
                priority: document.getElementById('jv-iss-f-priority').value,
            };
            if (!payload.title) {
                errBox.textContent = 'Titel ist erforderlich.';
                errBox.style.display = 'block';
                return;
            }
            try {
                const url = isEdit ? '/api/issues/' + encodeURIComponent(issue.id) : '/api/issues';
                const method = isEdit ? 'PATCH' : 'POST';
                const r = await fetch(url, {
                    method, headers: _headers({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(payload),
                });
                if (!r.ok) {
                    const t = await r.text();
                    throw new Error(t || ('HTTP ' + r.status));
                }
                const data = await r.json();
                _showDetail(data.issue.id);
            } catch (e) {
                errBox.textContent = e.message;
                errBox.style.display = 'block';
            }
        };
    }

    // ─── Jarvis-Bereich (Status + Comment) ────────────────────────────
    function _showJarvisForm(issue) {
        document.getElementById('jv-iss-title').textContent = 'Issue – Jarvis-Bereich';
        const body = document.getElementById('jv-iss-body');
        const footer = document.getElementById('jv-iss-footer');

        body.innerHTML = `
            <div class="jv-iss-detail-section" style="background:rgba(var(--fg-rgb),0.03);border-radius:8px;padding:12px;margin-bottom:14px;">
                <div class="jv-iss-item-head" style="margin-bottom:8px;">
                    <span class="jv-iss-badge ${_escape(issue.type)}">${_typeLabel(issue.type)}</span>
                    <span class="jv-iss-badge prio-${_escape(issue.priority)}">${_prioLabel(issue.priority)}</span>
                    <span class="jv-iss-badge" style="background:${_statusColor(issue.status)}">${_statusLabel(issue.status)}</span>
                </div>
                <div class="jv-iss-detail-value" style="font-size:15px;font-weight:600;color:var(--text-primary);">${_escape(issue.title)}</div>
                <div class="jv-iss-item-meta" style="margin-top:6px;">
                    <span>👤 ${_escape(issue.author || '—')}</span>
                    <span>Erstellt: ${_fmtDate(issue.created)}</span>
                </div>
                <div class="jv-iss-detail-label" style="margin-top:10px;">Ursprünglicher Text</div>
                <div class="jv-iss-detail-value" style="white-space:pre-wrap;">${_escape(issue.body) || '<em style="color:var(--text-muted)">(leer)</em>'}</div>
            </div>
            <div style="margin-bottom:14px;color:var(--text-secondary);font-size:12px;">
                Hier kann nur Jarvis Status setzen und einen oeffentlichen Kommentar hinterlassen.
            </div>
            <div class="jv-iss-form-row">
                <label>Status</label>
                <select id="jv-iss-j-status">
                    <option value="open">Offen</option>
                    <option value="in_progress">In Arbeit</option>
                    <option value="closed">Geschlossen</option>
                </select>
            </div>
            <div class="jv-iss-form-row">
                <label>Antwort/Kommentar an User (oeffentlich sichtbar)</label>
                <textarea id="jv-iss-j-comment" maxlength="20000">${_escape(issue.jarvis_comment || '')}</textarea>
            </div>
            <div id="jv-iss-form-err" class="jv-iss-err" style="display:none;"></div>
        `;
        document.getElementById('jv-iss-j-status').value = issue.status || 'open';

        footer.innerHTML = `
            <button class="jv-iss-btn" id="jv-iss-cancel-btn">Abbrechen</button>
            <button class="jv-iss-btn primary" id="jv-iss-save-btn">Speichern</button>
        `;
        document.getElementById('jv-iss-cancel-btn').onclick = () => _showDetail(issue.id);
        document.getElementById('jv-iss-save-btn').onclick = async () => {
            const errBox = document.getElementById('jv-iss-form-err');
            errBox.style.display = 'none';
            const payload = {
                status: document.getElementById('jv-iss-j-status').value,
                jarvis_comment: document.getElementById('jv-iss-j-comment').value,
            };
            try {
                const r = await fetch('/api/issues/' + encodeURIComponent(issue.id), {
                    method: 'PATCH',
                    headers: _headers({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(payload),
                });
                if (!r.ok) {
                    const t = await r.text();
                    throw new Error(t || ('HTTP ' + r.status));
                }
                _showDetail(issue.id);
            } catch (e) {
                errBox.textContent = e.message;
                errBox.style.display = 'block';
            }
        };
    }

    // ─── Public API ───────────────────────────────────────────────────
    window.JarvisIssues = {
        open: () => open('list'),
        create: () => open('create'),
        close: close,
    };
})();
