/* ============================================================
 * chatlib.js – Gemeinsame Helfer fuer alle AI-Chat-Frontends.
 *
 * Wird von index.html (Hauptseite, app.js) UND chat.html
 * (Standalone-Chat, chat.js) geladen. Stellt einheitliche
 * Implementierungen fuer:
 *   - HTML-Escaping
 *   - Markdown-Rendering
 *   - Zeit-/Datums-Strings (de-DE)
 *   - localStorage-Persistenz (save/load mit Truncate-Limit)
 *   - History-Trim fuer "Nachricht editieren"
 *   - DOM-Trim (Bubbles nach einer Row entfernen)
 *   - Edit-Modus (Textarea + Save/Cancel) als generisches
 *     Modul mit parametrisierten CSS-Klassen
 *
 * Vorher waren diese Funktionen ~280 Zeilen pro Datei dupliziert
 * (in app.js und chat.js, jeweils mit minimalen Praefix-Unter-
 * schieden). Jetzt: Single Source of Truth.
 *
 * Siehe auch Protokoll-Block in backend/main.py vor
 * _truncate_history_to_user_index().
 * ============================================================ */

(function (global) {
    'use strict';

    /* ── HTML-Escape (XSS-sicher via textContent-Trick) ───────── */
    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = String(str == null ? '' : str);
        return d.innerHTML;
    }

    /* ── Zeit-/Datums-Strings (de-DE) ─────────────────────────── */
    function timeStr(date) {
        const d = date instanceof Date ? date : new Date();
        return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    function currentDateStr(date) {
        const d = date instanceof Date ? date : new Date();
        return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    /* Wird vom onload eines Chat-Bildes aufgerufen: scrollt den scrollbaren
       Vorfahren ans Ende, damit das frisch geladene Bild vollstaendig sichtbar ist.
       Funktioniert in allen Web-Chats (eigener Scroll-Container je Chat). */
    window.__jarvisImgScroll = function (el) {
        try {
            let p = el && el.parentElement;
            while (p) {
                const oy = getComputedStyle(p).overflowY;
                if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) {
                    p.scrollTop = p.scrollHeight;
                    return;
                }
                p = p.parentElement;
            }
        } catch (_e) { /* ignore */ }
    };

    /* ── Markdown-Renderer ────────────────────────────────────── *
     *  Unterstuetzt: Ueberschriften (#–####), Listen (- / 1.),
     *  Blockquotes (>), Links, Tabellen, **bold**, *italic*,
     *  ~~del~~, `code`, ```block```                              */
    function renderMarkdown(text) {
        const _E = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // UTF-8-String -> base64 (fuer die Chart-Spec im data-Attribut, ohne
        // deprecated unescape; Sonderzeichen stoeren so die Token-Ersetzung nicht)
        const _toB64 = (str) => {
            try {
                const bytes = new TextEncoder().encode(str);
                let bin = '';
                for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                return btoa(bin);
            } catch (e) { return ''; }
        };

        // 1) Code-Bloecke extrahieren (vor HTML-Escape)
        const codeBlocks = [];
        let s = String(text == null ? '' : text).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
            const idx = codeBlocks.length;
            // ```chartjs / ```jarvis-chart -> interaktives Chart.js-Diagramm.
            // Die Spec (JSON) wird base64-kodiert ins data-Attribut gelegt und
            // spaeter von charts.js sicher (JSON.parse, kein eval) gerendert.
            if (/^(chartjs|jarvis-chart|chart)$/i.test(lang)) {
                codeBlocks.push(`<div class="jarvis-chart" data-spec="${_toB64(code.trim())}"></div>`);
            } else {
                codeBlocks.push(`<pre><code>${_E(code.trim())}</code></pre>`);
            }
            return `\x01CODE${idx}\x01`;
        });

        // 2) HTML-Escape den Rest
        s = _E(s);

        // 3) Inline-Code
        s = s.replace(/`([^`\n]+)`/g, (_, c) => `<code>${c}</code>`);

        // Download-Icon (Office-Chip)
        const _DL_SVG = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>';

        function _inline(t) {
            // Platzhalter fuer fertiges HTML, das die **/_/* -Formatierung UND das
            // URL-Autolinking NICHT mehr anfassen duerfen (Bilder, Download-Chips):
            // deren Attribut-URLs enthalten '__' (zerstoert die Kursiv-Regex) bzw.
            // wuerden vom Autolinker ein zweites Mal verlinkt. Erst ganz am Ende zurueck.
            const _ph = [];
            const _hold = (htmlStr) => { _ph.push(htmlStr); return `\x02PH${_ph.length - 1}\x02`; };

            // Inline-Code SOFORT sichern – vor jeder Formatierung. Sonst frisst die
            // Kursiv-Regex weiter unten die Unterstriche im Code-Inhalt, z.B. wuerde
            // `LOCAL_RECEIVE_PATH` als LOCAL<em>RECEIVE</em>PATH gerendert.
            t = t.replace(/<code>[\s\S]*?<\/code>/g, (m) => _hold(m));

            // Bilder ![alt](url)
            t = t.replace(/!\[([^\]\n]*)\]\(([^)\n]+)\)/g, (_, alt, url) => {
                const raw = url.replace(/&amp;/g, '&');
                const safe = /^https?:\/\/|^\/|^data:image\//.test(raw) ? raw : '';
                if (!safe) return '';
                return _hold(`<img src="${safe}" alt="${alt}" class="chat-img" loading="lazy" `
                     + `onload="window.__jarvisImgScroll&&window.__jarvisImgScroll(this)" `
                     + `style="max-width:100%;border-radius:10px;margin:6px 0;display:block;">`);
            });
            // Office-Download-Chips als Platzhalter extrahieren
            const _chip = (label, url) => {
                const safe = (label || 'Datei').replace(/^[📥\s]+/, '').trim() || 'Datei';
                return _hold(`<a href="${url}" download class="chat-doc-dl">${_DL_SVG}<span>${safe}</span></a>`);
            };
            // Markdown-Form [label](/api/documents/..)
            t = t.replace(/\[([^\]\n]*)\]\((\/api\/documents\/[A-Za-z0-9_\-]+\.(?:docx|xlsx|pptx|pdf))\)/g,
                (_, tit, url) => _chip(tit, url));
            // Nackte URL /api/documents/..
            t = t.replace(/(^|[\s(])(\/api\/documents\/[A-Za-z0-9_\-]+\.(?:docx|xlsx|pptx|pdf))/g,
                (_, pre, url) => pre + _chip('Download', url));

            t = t.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
            t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            t = t.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
            // '_' kursiviert NUR ausserhalb von Woertern (wie CommonMark). Sonst
            // zerreisst jeder Bezeichner mit zwei Unterstrichen – LOCAL_RECEIVE_PATH,
            // LOCAL_SEND_PATH, snake_case – zu "LOCALRECEIVEPATH".
            t = t.replace(/(^|[^A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])/g, '$1<em>$2</em>');
            t = t.replace(/~~(.+?)~~/g, '<del>$1</del>');
            t = t.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (_, tit, url) => {
                const raw = url.replace(/&amp;/g, '&');
                const safe = /^https?:\/\/|^\//.test(raw) ? raw : '#';
                return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${tit}</a>`;
            });

            // Nackte URLs (http/https/www) klickbar machen. Bestehende Markdown-<a>-
            // Bereiche zuerst schuetzen, damit URLs in href-Attributen nicht ein
            // zweites Mal (und kaputt) verlinkt werden.
            // Bilder/Chips/Inline-Code sind hier bereits Platzhalter und daher
            // automatisch geschuetzt.
            const _prot = [];
            const _protect = (re) => { t = t.replace(re, (m) => { _prot.push(m); return `\x03P${_prot.length - 1}\x03`; }); };
            _protect(/<a\b[^>]*>[\s\S]*?<\/a>/g);
            t = t.replace(/(https?:\/\/[^\s<>"{}|\\^`[\]]+|www\.[a-zA-Z0-9][^\s<>"{}|\\^`[\]]*)/gi, (url) => {
                const raw = url.replace(/&amp;/g, '&');
                const href = /^www\./i.test(raw) ? 'https://' + raw : raw;
                return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
            });
            t = t.replace(/\x03P(\d+)\x03/g, (_, i) => _prot[+i]);

            // Bilder/Chips ganz am Ende wiederherstellen (nach jeder Formatierung)
            t = t.replace(/\x02PH(\d+)\x02/g, (_, i) => _ph[+i]);
            return t;
        }

        const lines = s.split('\n');
        const out = [];
        let i = 0;
        while (i < lines.length) {
            const l = lines[i];
            const hm = l.match(/^(#{1,4}) (.+)/);
            if (hm) { out.push(`<h${hm[1].length}>${_inline(hm[2])}</h${hm[1].length}>`); i++; continue; }
            if (/^---+$/.test(l.trim())) { out.push('<hr>'); i++; continue; }
            if (l.startsWith('&gt; ')) { out.push(`<blockquote>${_inline(l.slice(5))}</blockquote>`); i++; continue; }
            if (/^[ \t]*[-*+] /.test(l)) {
                const its = [];
                while (i < lines.length && /^[ \t]*[-*+] /.test(lines[i]))
                    its.push(`<li>${_inline(lines[i++].replace(/^[ \t]*[-*+] /, ''))}</li>`);
                out.push(`<ul>${its.join('')}</ul>`); continue;
            }
            if (/^[ \t]*\d+\. /.test(l)) {
                const its = [];
                while (i < lines.length && /^[ \t]*\d+\. /.test(lines[i]))
                    its.push(`<li>${_inline(lines[i++].replace(/^[ \t]*\d+\. /, ''))}</li>`);
                out.push(`<ol>${its.join('')}</ol>`); continue;
            }
            if (l.includes('|') && i + 1 < lines.length && /^\|?[\s\-:|]+\|/.test(lines[i + 1])) {
                const tl = [];
                while (i < lines.length && lines[i].includes('|')) tl.push(lines[i++]);
                if (tl.length >= 2) {
                    const hs = tl[0].split('|').map(c => c.trim()).filter(Boolean);
                    const rs = tl.slice(2).map(r => r.split('|').map(c => c.trim()).filter(Boolean));
                    let t = '<table><thead><tr>' + hs.map(h => `<th>${_inline(h)}</th>`).join('') + '</tr></thead><tbody>';
                    rs.forEach(r => { t += '<tr>' + r.map(c => `<td>${_inline(c)}</td>`).join('') + '</tr>'; });
                    out.push(t + '</tbody></table>'); continue;
                }
            }
            if (!l.trim()) { if (out.length && out[out.length - 1] !== '<br>') out.push('<br>'); i++; continue; }
            out.push(_inline(l) + '<br>'); i++;
        }
        let r = out.join('').replace(/\x01CODE(\d+)\x01/g, (_, n) => codeBlocks[+n]);
        return r.replace(/^(<br>)+/, '').replace(/(<br>)+$/, '');
    }

    /* ── localStorage-Persistenz ──────────────────────────────── */
    function saveHistory(key, list, maxItems) {
        if (!key || !Array.isArray(list)) return false;
        const max = (typeof maxItems === 'number' && maxItems > 0) ? maxItems : 200;
        try {
            const slice = list.length > max ? list.slice(-max) : list;
            localStorage.setItem(key, JSON.stringify(slice));
            return true;
        } catch (_e) {
            // QuotaExceeded oder Storage deaktiviert
            return false;
        }
    }

    function loadHistory(key) {
        if (!key) return [];
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (_e) {
            return [];
        }
    }

    /* ── Geteilte Anzeige-History (Backend, pro Benutzer) ─────────── *
     *  Hauptfenster und jarvis/chat teilen denselben Verlauf serverseitig.
     *  Neue Nachrichten werden ANGEHAENGT (additiv, fensteruebergreifend in
     *  Ankunftsreihenfolge); beim Oeffnen/Aktualisieren wird geladen.        */
    const _SHARED_URL = '/api/chat/shared-history';

    async function sharedLoad(token) {
        try {
            const r = await fetch(_SHARED_URL, { headers: { 'Authorization': 'Bearer ' + token } });
            if (!r.ok) return null;
            const d = await r.json();
            return Array.isArray(d.messages) ? d.messages : [];
        } catch (_e) { return null; }
    }

    async function sharedAppend(token, msg, clientId) {
        try {
            await fetch(_SHARED_URL + '/append', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg, client_id: clientId || '' }),
            });
        } catch (_e) { /* offline -> nur lokal */ }
    }

    async function sharedReplace(token, messages, clientId) {
        try {
            await fetch(_SHARED_URL, {
                method: 'PUT',
                headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: messages || [], client_id: clientId || '' }),
            });
        } catch (_e) { /* offline */ }
    }

    /* Einmalige Zusammenfuehrung der bisherigen getrennten localStorage-Verlaeufe
       ins Backend (nur wenn dort noch leer). keys = beide alten History-Keys. */
    async function sharedMigrate(token, keys) {
        try {
            if (localStorage.getItem('jarvis_shared_migrated') === '1') return;
            const backend = await sharedLoad(token);
            if (backend === null) return;          // Backend nicht erreichbar -> spaeter erneut
            if (backend.length === 0) {
                let merged = [];
                (keys || []).forEach(function (k) {
                    try {
                        const raw = localStorage.getItem(k);
                        if (raw) { const arr = JSON.parse(raw); if (Array.isArray(arr)) merged = merged.concat(arr); }
                    } catch (_e) {}
                });
                merged.sort(function (a, b) { return ((a && a.ts) || 0) - ((b && b.ts) || 0); });
                if (merged.length > 0) await sharedReplace(token, merged);
            }
            localStorage.setItem('jarvis_shared_migrated', '1');
        } catch (_e) {}
    }

    /* ── History-Trim fuer "Nachricht editieren" ──────────────── *
     *  Kuerzt eine History-Liste so, dass die ersten (userIndex+1)
     *  User-Eintraege erhalten bleiben und alles danach entfernt
     *  wird. Aktualisiert dabei den Text des betroffenen Eintrags.
     *
     *  history – Array von Objekten mit role + text (+ optional time/date)
     *  userIndex – 0-basierter Index unter den role==='user' Eintraegen
     *  newText – neuer Text fuer den editierten User-Eintrag
     *  opts.timeStr / opts.dateStr – optional neue Zeit-/Datums-Strings
     *
     *  Mutiert die Liste IN PLACE. Rueckgabe: Anzahl entfernter Eintraege. */
    function truncateHistoryToUserIndex(history, userIndex, newText, opts) {
        if (!Array.isArray(history) || userIndex < 0) return 0;
        opts = opts || {};
        let userSeen = 0;
        let cutAt = history.length;
        for (let i = 0; i < history.length; i++) {
            if (history[i] && history[i].role === 'user') {
                if (userSeen === userIndex) {
                    cutAt = i + 1;
                    if (typeof newText === 'string') {
                        history[i].text = newText;
                        if (opts.timeStr) history[i].time = opts.timeStr;
                        if (opts.dateStr) history[i].date = opts.dateStr;
                    }
                    break;
                }
                userSeen++;
            }
        }
        const removed = history.length - cutAt;
        if (removed > 0) history.length = cutAt;
        return removed;
    }

    /* ── DOM-Trim: alle Siblings nach einer Row entfernen ─────── */
    function removeRowsAfter(row) {
        if (!row || !row.parentNode) return 0;
        const toRemove = [];
        let sibling = row.nextSibling;
        while (sibling) {
            const next = sibling.nextSibling;
            toRemove.push(sibling);
            sibling = next;
        }
        toRemove.forEach(el => el.parentNode && el.parentNode.removeChild(el));
        return toRemove.length;
    }

    /* ── Edit-Modus: Bubble in Textarea verwandeln ────────────── *
     *  Generischer Workflow. Praefixe via opts parametrisierbar.
     *
     *  Pflicht-Parameter:
     *    row, bubble – DOM-Elemente der zu editierenden Bubble
     *    opts.onCommit(newText) – Callback bei Save (neuer Text)
     *
     *  Optionale Parameter:
     *    opts.isBlocked()        – z.B. () => agentRunning
     *    opts.blockMessage       – Alert-Text wenn blockiert
     *    opts.onCancel()         – Callback bei Abbruch
     *    opts.editBtnSelector    – z.B. '.msg-edit-btn'
     *    opts.areaClass          – z.B. 'msg-edit-area'
     *    opts.actionsClass       – z.B. 'msg-edit-actions'
     *    opts.saveClass          – z.B. 'msg-edit-save'
     *    opts.cancelClass        – z.B. 'msg-edit-cancel'
     *    opts.saveLabel / opts.cancelLabel – Button-Texte
     *
     *  Rueckgabe: true wenn Edit-Modus geoeffnet, false sonst. */
    function enterEditMode(row, bubble, opts) {
        opts = opts || {};
        if (!row || !bubble) return false;
        if (typeof opts.isBlocked === 'function' && opts.isBlocked()) {
            alert(opts.blockMessage || (window.t ? window.t('bubble.block_running') : 'Bitte stoppe zuerst die laufende Aufgabe.'));
            return false;
        }

        const editBtnSelector = opts.editBtnSelector || '.jv-bubble-edit-btn';
        const areaClass    = opts.areaClass    || 'jv-bubble-edit-area';
        const actionsClass = opts.actionsClass || 'jv-bubble-edit-actions';
        const saveClass    = opts.saveClass    || 'jv-bubble-edit-save';
        const cancelClass  = opts.cancelClass  || 'jv-bubble-edit-cancel';
        const saveLabel    = opts.saveLabel    || 'Speichern & neu generieren';
        const cancelLabel  = opts.cancelLabel  || 'Abbrechen';

        const oldText = row.dataset.rawText || bubble.textContent || '';

        bubble.dataset.origHtml = bubble.innerHTML;
        bubble.innerHTML = '';
        bubble.classList.add('editing');

        const ta = document.createElement('textarea');
        ta.className = areaClass;
        ta.value = oldText;
        ta.rows = Math.min(10, Math.max(2, oldText.split('\n').length + 1));
        bubble.appendChild(ta);

        const actions = document.createElement('div');
        actions.className = actionsClass;
        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.className = saveClass;
        saveBtn.textContent = saveLabel;
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = cancelClass;
        cancelBtn.textContent = cancelLabel;
        actions.appendChild(cancelBtn);
        actions.appendChild(saveBtn);
        bubble.appendChild(actions);

        const editBtnEl = row.querySelector(editBtnSelector);
        if (editBtnEl) editBtnEl.style.visibility = 'hidden';

        ta.focus();
        try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (_e) {}

        const _onCancel = typeof opts.onCancel === 'function' ? opts.onCancel : () => {};
        const _onCommit = typeof opts.onCommit === 'function' ? opts.onCommit : () => {};

        const finish = (commit) => {
            if (commit) {
                const newText = ta.value.trim();
                if (!newText) { alert('Text darf nicht leer sein.'); return; }
                if (newText === oldText) {
                    exitEditMode(row, bubble, { editBtnSelector: editBtnSelector });
                    _onCancel();
                    return;
                }
                _onCommit(newText);
            } else {
                exitEditMode(row, bubble, { editBtnSelector: editBtnSelector });
                _onCancel();
            }
        };

        cancelBtn.addEventListener('click', () => finish(false));
        saveBtn.addEventListener('click',   () => finish(true));
        ta.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.preventDefault(); finish(false); }
            else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault(); finish(true);
            }
        });
        return true;
    }

    /* ── Edit-Modus verlassen / Bubble zuruecksetzen ──────────── */
    function exitEditMode(row, bubble, opts) {
        opts = opts || {};
        if (!bubble) return;
        bubble.innerHTML = bubble.dataset.origHtml || '';
        delete bubble.dataset.origHtml;
        bubble.classList.remove('editing');
        const editBtnSelector = opts.editBtnSelector || '.jv-bubble-edit-btn';
        const editBtnEl = row && row.querySelector(editBtnSelector);
        if (editBtnEl) editBtnEl.style.visibility = '';
    }

    /* ───────────────────────────────────────────────────────────── *
     *  Bubble-Kontextmenue (Rechtsklick / Long-Press)
     *
     *  Erzeugt EIN globales Floating-Menu (#jv-bubble-ctx-menu) und
     *  haengt es per `setupBubbleContextMenu(el, opts)` an jede Bubble-
     *  Row. Die Aktionen werden pro Aufruf neu konfiguriert.
     *
     *  opts = {
     *    items: [
     *      { label: 'Bearbeiten', icon: '✏', onClick: () => {...} },
     *      { label: 'Loeschen',   icon: '×', danger: true, onClick: ... },
     *      { label: 'Kopieren',   icon: '⧉', onClick: ... },
     *    ]
     *  }
     *  Items mit `onClick === null` werden uebersprungen (z.B. Bearbeiten
     *  bei Bot-Bubbles weglassen).
     * ───────────────────────────────────────────────────────────── */
    let _ctxMenuEl = null;
    function _ensureCtxMenu() {
        if (_ctxMenuEl) return _ctxMenuEl;
        _ctxMenuEl = document.createElement('div');
        _ctxMenuEl.id = 'jv-bubble-ctx-menu';
        _ctxMenuEl.className = 'jv-bubble-ctx-menu';
        document.body.appendChild(_ctxMenuEl);
        // Globale Close-Handler
        document.addEventListener('click', () => _hideCtxMenu());
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') _hideCtxMenu();
        });
        window.addEventListener('blur', () => _hideCtxMenu());
        window.addEventListener('resize', () => _hideCtxMenu());
        return _ctxMenuEl;
    }
    function _hideCtxMenu() {
        if (_ctxMenuEl) _ctxMenuEl.classList.remove('open');
    }
    function _showCtxMenuAt(x, y, items) {
        const menu = _ensureCtxMenu();
        menu.innerHTML = '';
        const usable = items.filter(it => it && typeof it.onClick === 'function');
        if (usable.length === 0) return;
        for (const it of usable) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'jv-bubble-ctx-item' + (it.danger ? ' danger' : '');
            const icon = it.icon ? `<span class="jv-bubble-ctx-icon">${it.icon}</span>` : '';
            btn.innerHTML = `${icon}<span>${escapeHtml(it.label || '')}</span>`;
            btn.addEventListener('click', (ev) => {
                ev.stopPropagation();
                _hideCtxMenu();
                try { it.onClick(); } catch (e) { console.error('[CtxMenu]', e); }
            });
            menu.appendChild(btn);
        }
        // Positionierung (am Viewport-Rand abklemmen)
        menu.classList.add('open');
        const rect = menu.getBoundingClientRect();
        const maxX = window.innerWidth  - rect.width  - 8;
        const maxY = window.innerHeight - rect.height - 8;
        menu.style.left = Math.max(4, Math.min(x, maxX)) + 'px';
        menu.style.top  = Math.max(4, Math.min(y, maxY)) + 'px';
    }

    function setupBubbleContextMenu(targetEl, getItems) {
        if (!targetEl || typeof getItems !== 'function') return;
        targetEl.addEventListener('contextmenu', (e) => {
            // Edit-Mode aktiv? Dann kein Menue
            if (targetEl.classList.contains('editing') ||
                targetEl.querySelector('.editing')) return;
            const items = getItems();
            if (!items || items.length === 0) return;
            e.preventDefault();
            e.stopPropagation();
            _showCtxMenuAt(e.clientX, e.clientY, items);
        });
        // Long-Press fuer Touch-Geraete (~550ms)
        let _touchTimer = null;
        let _touchStartXY = null;
        targetEl.addEventListener('touchstart', (e) => {
            if (!e.touches || e.touches.length !== 1) return;
            const t = e.touches[0];
            _touchStartXY = { x: t.clientX, y: t.clientY };
            _touchTimer = setTimeout(() => {
                const items = getItems();
                if (!items || items.length === 0) return;
                _showCtxMenuAt(_touchStartXY.x, _touchStartXY.y, items);
                // haptisches Feedback (falls vorhanden)
                try { navigator.vibrate && navigator.vibrate(30); } catch(_) {}
            }, 550);
        }, { passive: true });
        const _cancelTouch = () => { if (_touchTimer) { clearTimeout(_touchTimer); _touchTimer = null; } };
        targetEl.addEventListener('touchend',    _cancelTouch);
        targetEl.addEventListener('touchcancel', _cancelTouch);
        targetEl.addEventListener('touchmove', (e) => {
            if (!_touchStartXY || !e.touches || e.touches.length !== 1) return _cancelTouch();
            const t = e.touches[0];
            const dx = Math.abs(t.clientX - _touchStartXY.x);
            const dy = Math.abs(t.clientY - _touchStartXY.y);
            if (dx > 8 || dy > 8) _cancelTouch();
        }, { passive: true });
    }

    /* ───────────────────────────────────────────────────────────── *
     *  Auswahlmodus (Mehrfachauswahl zum Loeschen von Nachrichten)
     *
     *  Kapselt den kompletten Lebenszyklus, der vorher in app.js,
     *  chat.js und userchat.js jeweils nahezu identisch dupliziert war:
     *    - Modus betreten/verlassen/umschalten
     *    - Checkbox je Row einfuegen/entfernen
     *    - Auswahl-Zaehler aktualisieren + Loesch-Button (de)aktivieren
     *    - Vorauswahl aus dem Kontextmenue ("Loeschen")
     *    - Bestaetigungsdialog (select.confirm)
     *
     *  Die SEITENSPEZIFISCHE Loeschlogik (lokale History filtern + DOM
     *  entfernen vs. WebSocket dm_delete) wird per opts.onDelete(rows)
     *  Callback delegiert.
     *
     *  opts = {
     *    container,            // DOM-Element mit den Rows (Pflicht)
     *    rowSelector,          // z.B. '.jv-bubble-row' (Pflicht)
     *    checkboxClass,        // z.B. 'jv-msg-check'   (Pflicht)
     *    selectModeClass,      // Klasse am Container, Default 'select-mode'
     *    bar, countEl, delBtn, // Aktionsleiste, Zaehler, Loesch-Button
     *    toggleBtn, cancelBtn, // optionale Buttons
     *    canSelectRow(row),    // Filter: welche Rows bekommen eine Checkbox
     *                          //   (Default: alle); userchat: nur eigene
     *    onEnter(),            // Hook beim Betreten (z.B. Edit-Modus beenden)
     *    onDelete(rows),       // Pflicht-Callback: loescht die markierten Rows
     *  }
     *
     *  Rueckgabe: Controller mit isActive(), enter(), exit(), toggle(),
     *  startSelectionDelete(row), addCheckboxToRow(row), updateCount(),
     *  checkbox(row).
     * ───────────────────────────────────────────────────────────── */
    function createSelectionController(opts) {
        opts = opts || {};
        const container       = opts.container;
        const rowSelector     = opts.rowSelector;
        const checkboxClass   = opts.checkboxClass;
        const selectModeClass = opts.selectModeClass || 'select-mode';
        const bar       = opts.bar       || null;
        const countEl   = opts.countEl   || null;
        const delBtn      = opts.delBtn      || null;
        const toggleBtn   = opts.toggleBtn   || null;
        const cancelBtn   = opts.cancelBtn   || null;
        const selectAllBtn = opts.selectAllBtn || null;
        const canSelectRow = typeof opts.canSelectRow === 'function' ? opts.canSelectRow : () => true;
        const onEnter  = typeof opts.onEnter  === 'function' ? opts.onEnter  : null;
        const onDelete = typeof opts.onDelete === 'function' ? opts.onDelete : () => {};

        if (!container || !rowSelector || !checkboxClass) {
            console.error('[SelectionController] container/rowSelector/checkboxClass erforderlich');
            const noop = () => {};
            return { isActive: () => false, enter: noop, exit: noop, toggle: noop,
                     startSelectionDelete: noop, addCheckboxToRow: noop, updateCount: noop,
                     checkbox: () => null };
        }

        const checkSel = '.' + checkboxClass;
        let active = false;

        function checkbox(row) { return row ? row.querySelector(checkSel) : null; }

        function updateCount() {
            const n = container.querySelectorAll(checkSel + ':checked').length;
            if (countEl) countEl.textContent = String(n);
            if (delBtn) delBtn.disabled = (n === 0);
        }

        function addCheckboxToRow(row) {
            if (!row || !canSelectRow(row) || checkbox(row)) return;
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = checkboxClass;
            cb.addEventListener('change', updateCount);
            // Checkbox als erstes Element der Row → immer links
            row.insertBefore(cb, row.firstChild);
        }

        function enter() {
            if (active) return;
            if (onEnter) { try { onEnter(); } catch (_) {} }
            active = true;
            container.classList.add(selectModeClass);
            container.querySelectorAll(rowSelector).forEach(addCheckboxToRow);
            if (bar) bar.hidden = false;
            if (toggleBtn) toggleBtn.classList.add('active');
            updateCount();
        }

        function exit() {
            active = false;
            container.classList.remove(selectModeClass);
            container.querySelectorAll(checkSel).forEach(cb => cb.remove());
            if (bar) bar.hidden = true;
            if (toggleBtn) toggleBtn.classList.remove('active');
        }

        function toggle() { active ? exit() : enter(); }

        // Aus dem Kontextmenue "Loeschen": Modus starten und die
        // angeklickte Nachricht direkt vorauswaehlen (wie Android/Windows-App).
        function startSelectionDelete(row) {
            enter();
            if (row) {
                const cb = checkbox(row);
                if (cb) { cb.checked = true; updateCount(); }
            }
        }

        // Alle auswaehlbaren Nachrichten markieren bzw. (wenn schon alle markiert)
        // die Auswahl wieder aufheben.
        function selectAll() {
            const boxes = Array.from(container.querySelectorAll(checkSel));
            const allChecked = boxes.length > 0 && boxes.every(cb => cb.checked);
            boxes.forEach(cb => { cb.checked = !allChecked; });
            updateCount();
        }

        function deleteSelected() {
            const checked = Array.from(container.querySelectorAll(checkSel + ':checked'))
                .map(cb => cb.closest(rowSelector))
                .filter(Boolean);
            if (checked.length === 0) return;
            const q = window.t ? window.t('select.confirm') : 'Ausgewählte Nachrichten löschen?';
            if (!confirm(q.replace('{n}', String(checked.length)))) return;
            try { onDelete(checked); } catch (e) { console.error('[SelectionController] onDelete', e); }
            exit();
        }

        if (toggleBtn)    toggleBtn.addEventListener('click', toggle);
        if (cancelBtn)    cancelBtn.addEventListener('click', exit);
        if (delBtn)       delBtn.addEventListener('click', deleteSelected);
        if (selectAllBtn) selectAllBtn.addEventListener('click', selectAll);

        return {
            isActive: () => active,
            enter: enter,
            exit: exit,
            toggle: toggle,
            startSelectionDelete: startSelectionDelete,
            addCheckboxToRow: addCheckboxToRow,
            updateCount: updateCount,
            selectAll: selectAll,
            checkbox: checkbox,
        };
    }

    /* ── Clipboard-Helfer (Best-Effort, fallback auf execCommand) ──── */
    async function copyTextToClipboard(text) {
        if (text == null) text = '';
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch (_) {}
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity  = '0';
            document.body.appendChild(ta);
            ta.focus(); ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return ok;
        } catch (_) { return false; }
    }

    /* ── Namespace exponieren ─────────────────────────────────── */
    global.JarvisChatLib = {
        escapeHtml: escapeHtml,
        renderMarkdown: renderMarkdown,
        timeStr: timeStr,
        currentDateStr: currentDateStr,
        saveHistory: saveHistory,
        loadHistory: loadHistory,
        sharedLoad: sharedLoad,
        sharedAppend: sharedAppend,
        sharedReplace: sharedReplace,
        sharedMigrate: sharedMigrate,
        truncateHistoryToUserIndex: truncateHistoryToUserIndex,
        removeRowsAfter: removeRowsAfter,
        enterEditMode: enterEditMode,
        exitEditMode: exitEditMode,
        setupBubbleContextMenu: setupBubbleContextMenu,
        hideBubbleContextMenu: _hideCtxMenu,
        copyTextToClipboard: copyTextToClipboard,
        createSelectionController: createSelectionController,
    };
})(typeof window !== 'undefined' ? window : this);
