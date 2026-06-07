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

    /* ── Markdown-Renderer ────────────────────────────────────── *
     *  Unterstuetzt: Ueberschriften (#–####), Listen (- / 1.),
     *  Blockquotes (>), Links, Tabellen, **bold**, *italic*,
     *  ~~del~~, `code`, ```block```                              */
    function renderMarkdown(text) {
        const _E = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // 1) Code-Bloecke extrahieren (vor HTML-Escape)
        const codeBlocks = [];
        let s = String(text == null ? '' : text).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
            const idx = codeBlocks.length;
            codeBlocks.push(`<pre><code>${_E(code.trim())}</code></pre>`);
            return `\x01CODE${idx}\x01`;
        });

        // 2) HTML-Escape den Rest
        s = _E(s);

        // 3) Inline-Code
        s = s.replace(/`([^`\n]+)`/g, (_, c) => `<code>${c}</code>`);

        function _inline(t) {
            t = t.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
            t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            t = t.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
            t = t.replace(/_([^_\n]+)_/g, '<em>$1</em>');
            t = t.replace(/~~(.+?)~~/g, '<del>$1</del>');
            t = t.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (_, tit, url) => {
                const raw = url.replace(/&amp;/g, '&');
                const safe = /^https?:\/\/|^\//.test(raw) ? raw : '#';
                return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${tit}</a>`;
            });
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
            alert(opts.blockMessage || 'Bitte stoppe zuerst die laufende Aufgabe.');
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

    /* ── Namespace exponieren ─────────────────────────────────── */
    global.JarvisChatLib = {
        escapeHtml: escapeHtml,
        renderMarkdown: renderMarkdown,
        timeStr: timeStr,
        currentDateStr: currentDateStr,
        saveHistory: saveHistory,
        loadHistory: loadHistory,
        truncateHistoryToUserIndex: truncateHistoryToUserIndex,
        removeRowsAfter: removeRowsAfter,
        enterEditMode: enterEditMode,
        exitEditMode: exitEditMode,
    };
})(typeof window !== 'undefined' ? window : this);
