/**
 * Jarvis Wissens-Gruppen-Matrix
 * Vollbild-Tabelle über ALLE indizierten Wissens-Dateien mit Spalten
 * Name · Beschreibung · Quelle · [je Gruppe eine Spalte] · Bearbeiten · Löschen.
 * Klick in eine Gruppen-Spalte setzt/entfernt die Zugehörigkeit sofort.
 * Spaltenbreiten sind per Drag verschiebbar.
 */
window.KbMatrix = (function () {
    'use strict';

    function _auth(extra) {
        const tok = localStorage.getItem('jarvis_token') || '';
        return Object.assign({ 'Authorization': 'Bearer ' + tok }, extra || {});
    }
    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }
    function _attr(s) { return _esc(s); }
    function T(k, d) { return (window.t && window.t(k)) || d; }

    let _rows = [];      // [{path,name,desc,source,docId,doc}]
    let _assign = {};    // path -> [group-ids]
    let _groups = [];
    let _contentCache = {};  // path -> Inhalts-Vorschau (lazy)

    async function open() {
        const KG = window.KbGroups;
        if (KG && !KG.all().length) await KG.load();
        _groups = KG ? KG.all() : [];

        const [filesResp, pendingResp, assignMap] = await Promise.all([
            fetch('/api/knowledge/files', { headers: _auth() }).then(r => r.json()).catch(() => []),
            fetch('/api/knowledge/pending', { headers: _auth() }).then(r => r.json()).catch(() => []),
            KG ? KG.getMap() : Promise.resolve({}),
        ]);
        _assign = assignMap || {};

        // Extraktor-Metadaten (Titel/Beschreibung/Quelle) je Datei
        const docByFile = {};
        (pendingResp || []).forEach(d => { if (d.file) docByFile[d.file] = d; });

        _rows = [];
        (filesResp || []).forEach(folder => {
            (folder.files || []).forEach(f => {
                const doc = docByFile[f.path];
                _rows.push({
                    path: f.path,
                    name: (doc && doc.title) || f.name,
                    desc: (doc && doc.summary) || '',
                    source: doc ? (doc.source_name || doc.url || '') : (folder.folder || ''),
                    docId: doc ? doc.id : null,
                    doc: doc || null,
                });
            });
        });
        _rows.sort((a, b) => a.name.localeCompare(b.name, 'de'));
        _render();
    }

    function _groupCount(gid) {
        let n = 0;
        for (const p in _assign) if ((_assign[p] || []).includes(gid)) n++;
        return n;
    }

    function _cols() {
        const cols = [
            { key: 'name',   label: T('kbmatrix.col_name', 'Name'),          tip: T('kbmatrix.t_name', 'Name bzw. Titel des Dokuments'),          cls: 'kbm-c-text' },
            { key: 'desc',   label: T('kbmatrix.col_desc', 'Beschreibung'),  tip: T('kbmatrix.t_desc', 'Kurzbeschreibung / Zusammenfassung'),      cls: 'kbm-c-text' },
            { key: 'source', label: T('kbmatrix.col_source', 'Quelle'),      tip: T('kbmatrix.t_source', 'Quelle (URL/Datei) bzw. Ordner'),        cls: 'kbm-c-text' },
        ];
        const gTip = T('kbmatrix.t_group', 'Klick in eine Zelle setzt/entfernt die Zugehörigkeit zu dieser Gruppe');
        _groups.forEach(g => cols.push({ key: 'g:' + g.id, group: g, tip: g.name + ' – ' + gTip, cls: 'kbm-c-grp' }));
        cols.push({ key: 'edit', label: T('kbmatrix.col_edit', 'Bearb.'),   tip: T('kbmatrix.t_edit', 'Dokument bearbeiten'),   cls: 'kbm-c-act' });
        cols.push({ key: 'del',  label: T('kbmatrix.col_delete', 'Lösch.'), tip: T('kbmatrix.t_delete', 'Dokument löschen'),    cls: 'kbm-c-act' });
        return cols;
    }

    // Spaltenbreiten so setzen, dass die Tabelle exakt auf den Schirm passt;
    // Gruppen-/Aktionsspalten so schmal wie möglich, Text teilt sich den Rest.
    function _applyFitWidths(ov) {
        const wrap  = ov.querySelector('.kbm-table-wrap');
        const table = ov.querySelector('.kbm-table');
        const cols  = ov.querySelectorAll('.kbm-table col');
        const G = _groups.length;
        const avail = Math.max(360, (wrap.clientWidth || 900) - 2);
        const groupW = 46, actW = 48;
        const textAvail = Math.max(240, avail - (G * groupW + 2 * actW));
        const nameW = Math.round(textAvail * 0.30);
        const descW = Math.round(textAvail * 0.45);
        const srcW  = textAvail - nameW - descW;
        const widths = [nameW, descW, srcW];
        for (let i = 0; i < G; i++) widths.push(groupW);
        widths.push(actW, actW);
        let total = 0;
        widths.forEach((w, i) => { if (cols[i]) cols[i].style.width = w + 'px'; total += w; });
        table.style.width = total + 'px';
    }

    function _render() {
        document.getElementById('kbm-overlay')?.remove();
        const cols = _cols();

        const colgroup = '<colgroup>' + cols.map(() => '<col>').join('') + '</colgroup>';
        const thead = '<thead><tr>' + cols.map((c, i) => {
            let inner;
            if (c.group) {
                inner = `<span class="kbm-th-dot" style="background:${_attr(c.group.color)}"></span>`
                    + `<span class="kbm-th-name" title="${_attr(c.group.name)}">${_esc(c.group.name)}</span>`
                    + `<span class="kbm-th-count" data-gid="${_attr(c.group.id)}">${_groupCount(c.group.id)}</span>`;
            } else {
                inner = _esc(c.label);
            }
            const rez = (i < cols.length - 1) ? `<span class="kbm-resizer" data-ci="${i}"></span>` : '';
            return `<th class="${c.cls}" title="${_attr(c.tip || '')}">${inner}${rez}</th>`;
        }).join('') + '</tr></thead>';

        const tbody = '<tbody>' + _rows.map(row => {
            const gcells = _groups.map(g => {
                const on = (_assign[row.path] || []).includes(g.id);
                return `<td class="kbm-gcell${on ? ' on' : ''}" data-gid="${_attr(g.id)}" style="--grp:${_attr(g.color)}">`
                    + `<span class="kbm-check">${on ? '✓' : ''}</span></td>`;
            }).join('');
            // Beschreibung: liegt keine vor, "Inhalt" anzeigen und den Dateiinhalt
            // per Hover-Tooltip (lazy geladen) daran hängen.
            const descTd = row.desc
                ? `<td class="kbm-c-text" title="${_attr(row.desc)}">${_esc(row.desc)}</td>`
                : `<td class="kbm-c-text kbm-content">${_esc(T('kbmatrix.content', 'Inhalt'))}</td>`;
            return `<tr data-path="${_attr(row.path)}">
                <td class="kbm-c-text" title="${_attr(row.path)}">${_esc(row.name)}</td>
                ${descTd}
                <td class="kbm-c-text" title="${_attr(row.source)}">${_esc(row.source)}</td>
                ${gcells}
                <td class="kbm-c-act"><button class="kbm-edit" title="${T('kbgroups.rename', 'Bearbeiten')}">✏️</button></td>
                <td class="kbm-c-act"><button class="kbm-del" title="${T('kbgroups.delete', 'Löschen')}">×</button></td>
            </tr>`;
        }).join('') + '</tbody>';

        const ov = document.createElement('div');
        ov.id = 'kbm-overlay';
        ov.className = 'kbm-overlay';
        ov.innerHTML = `
            <div class="kbm-panel">
                <div class="kbm-head">
                    <span class="kbm-title">${T('kbmatrix.title', 'Wissensgruppen-Tabelle')}
                        <span class="kbm-count">${_rows.length} ${T('kbmatrix.docs', 'Dokumente')}</span></span>
                    <input type="text" class="kbm-filter" placeholder="${T('kbmatrix.filter', 'Filter…')}">
                    <button class="kbm-close" title="${T('common.close', 'Schließen')}">✕</button>
                </div>
                <div class="kbm-table-wrap">
                    <table class="kbm-table">${colgroup}${thead}${tbody}</table>
                </div>
            </div>`;
        document.body.appendChild(ov);

        _applyFitWidths(ov);
        _bind(ov);
    }

    function _bind(ov) {
        ov.querySelector('.kbm-close').onclick = () => close();
        ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });

        // Filter: sofort ueber den sichtbaren Zeilentext, zusaetzlich (debounced)
        // ueber den DATEI-INHALT via Server (extrahierte Text-Chunks, z.B. JSON).
        const filter = ov.querySelector('.kbm-filter');
        let fSeq = 0, fTimer = null;
        const applyFilter = (q, contentHits) => {
            ov.querySelectorAll('tbody tr').forEach(tr => {
                const hit = !q || tr.textContent.toLowerCase().indexOf(q) !== -1
                    || (contentHits && contentHits.has(tr.dataset.path));
                tr.style.display = hit ? '' : 'none';
            });
        };
        filter.addEventListener('input', () => {
            const q = filter.value.trim().toLowerCase();
            clearTimeout(fTimer);
            applyFilter(q, null);
            if (q.length < 2) return;
            fTimer = setTimeout(async () => {
                const mySeq = ++fSeq;
                try {
                    const r = await fetch('/api/knowledge/content_search?q=' + encodeURIComponent(q), { headers: _auth() });
                    const d = await r.json();
                    // Antwort verwerfen, wenn inzwischen weitergetippt wurde
                    if (mySeq !== fSeq || filter.value.trim().toLowerCase() !== q) return;
                    if (d && d.ok) applyFilter(q, new Set(d.files || []));
                } catch (e) { /* dann eben nur Text-Treffer */ }
            }, 300);
        });

        // Klicks in der Tabelle (Delegation)
        const tbody = ov.querySelector('tbody');
        tbody.addEventListener('click', e => {
            const gcell = e.target.closest('.kbm-gcell');
            if (gcell) { _toggle(gcell, ov); return; }
            const tr = e.target.closest('tr[data-path]');
            if (!tr) return;
            if (e.target.closest('.kbm-edit')) { _edit(tr.dataset.path); return; }
            if (e.target.closest('.kbm-del'))  { _del(tr, ov); return; }
        });

        _bindResize(ov);
        _bindContentTip(ov);
    }

    // JSON huebsch einrücken, wenn der Inhalt gültiges JSON ist – sonst Rohtext.
    // Gibt { text, json } zurück (json=true -> Monospace-Darstellung im Tooltip).
    function _prettyMaybeJson(txt) {
        const s = (txt || '').trim();
        if (s && (s[0] === '{' || s[0] === '[')) {
            try { return { text: JSON.stringify(JSON.parse(s), null, 2), json: true }; }
            catch (e) { /* abgeschnitten/kein JSON -> Rohtext */ }
        }
        return { text: txt, json: false };
    }

    // ── Info-Popup mit Dateiinhalt für "Inhalt"-Zellen (lazy geladen) ─────────
    // Bleibt offen, solange die Maus in Zelle ODER Popup ist (Scrollbar erreichbar),
    // und wird vertikal in den Viewport eingepasst.
    function _bindContentTip(ov) {
        const tbody = ov.querySelector('tbody');
        const tip = document.createElement('div');
        tip.className = 'kbm-tip';
        tip.style.display = 'none';
        ov.appendChild(tip);

        let hideTimer = null;
        const cancelHide = () => { clearTimeout(hideTimer); };
        const scheduleHide = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => { tip.style.display = 'none'; }, 250); };

        function place(cell) {
            const r = cell.getBoundingClientRect();
            const w = Math.min(680, window.innerWidth - 24);
            tip.style.width = w + 'px';
            tip.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left)) + 'px';
            tip._anchorBottom = r.bottom + 6;
            tip.style.top = tip._anchorBottom + 'px';
        }
        function reclamp() {
            // Passt der Tooltip unterhalb nicht mehr, nach oben schieben.
            const h = tip.offsetHeight;
            let top = tip._anchorBottom || 12;
            if (top + h > window.innerHeight - 12) top = Math.max(12, window.innerHeight - h - 12);
            tip.style.top = top + 'px';
        }
        function setContent(entry) {
            tip.textContent = entry.text;
            tip.classList.toggle('kbm-tip-json', !!entry.json);
            reclamp();
        }
        function show(cell) {
            cancelHide();
            const path = cell.closest('tr').dataset.path;
            tip._path = path;
            place(cell);
            tip.style.display = 'block';
            if (_contentCache[path] !== undefined) { setContent(_contentCache[path]); return; }
            tip.classList.remove('kbm-tip-json');
            tip.textContent = T('kbmatrix.loading', 'lädt…');
            fetch('/api/knowledge/file_read?path=' + encodeURIComponent(path), { headers: _auth() })
                .then(r => r.json()).then(d => {
                    let raw = (d && d.ok && d.content != null && d.content !== '')
                        ? String(d.content) : T('kbmatrix.no_content', '(Inhalt nicht als Text lesbar)');
                    raw = raw.replace(/\s+$/, '');
                    const entry = _prettyMaybeJson(raw);
                    if (entry.text.length > 8000) entry.text = entry.text.slice(0, 8000) + '\n…';
                    _contentCache[path] = entry;
                    if (tip.style.display !== 'none' && tip._path === path) setContent(entry);
                }).catch(() => {
                    _contentCache[path] = { text: T('kbmatrix.no_content', '(Inhalt nicht lesbar)'), json: false };
                    if (tip._path === path) setContent(_contentCache[path]);
                });
        }
        tbody.addEventListener('mouseover', e => {
            const cell = e.target.closest('.kbm-content');
            if (cell) show(cell);
        });
        tbody.addEventListener('mouseout', e => {
            const cell = e.target.closest('.kbm-content');
            if (!cell) return;
            // Nicht schließen, wenn die Maus in den Tooltip wandert.
            if (e.relatedTarget && (tip === e.relatedTarget || tip.contains(e.relatedTarget))) return;
            scheduleHide();
        });
        // Solange die Maus im Tooltip ist, offen halten (Scrollen/Markieren möglich).
        tip.addEventListener('mouseenter', cancelHide);
        tip.addEventListener('mouseleave', scheduleHide);
    }

    async function _toggle(cell, ov) {
        const tr = cell.closest('tr');
        const path = tr.dataset.path;
        const gid = cell.dataset.gid;
        let ids = (_assign[path] || []).slice();
        const on = ids.includes(gid);
        ids = on ? ids.filter(x => x !== gid) : ids.concat(gid);
        // Optimistisch umschalten
        cell.classList.toggle('on', !on);
        cell.querySelector('.kbm-check').textContent = !on ? '✓' : '';
        _assign[path] = ids;
        const cnt = ov.querySelector('.kbm-th-count[data-gid="' + CSS.escape(gid) + '"]');
        if (cnt) cnt.textContent = _groupCount(gid);
        try {
            await window.KbGroups.setAssignment(path, ids);
        } catch (err) {
            // Zurückrollen bei Fehler
            _assign[path] = on ? ids.concat(gid) : ids.filter(x => x !== gid);
            cell.classList.toggle('on', on);
            cell.querySelector('.kbm-check').textContent = on ? '✓' : '';
            if (cnt) cnt.textContent = _groupCount(gid);
        }
    }

    function _edit(path) {
        const row = _rows.find(r => r.path === path);
        if (!row) return;
        close();
        if (row.docId && window.extractorManager && window.extractorManager._openReview) {
            window.extractorManager._openReview(row.doc, true);
        } else if (window.knowledgeManager && window.knowledgeManager.viewFile) {
            window.knowledgeManager.viewFile(path, row.name);
        }
    }

    async function _del(tr, ov) {
        const path = tr.dataset.path;
        const row = _rows.find(r => r.path === path);
        const name = row ? row.name : path;
        const msg = (T('kbmatrix.delete_confirm', 'Dokument „{name}" wirklich aus der Wissens-DB löschen?')).replace('{name}', name);
        if (!confirm(msg)) return;
        try {
            if (row && row.docId) {
                await fetch('/api/knowledge/extract/file', {
                    method: 'DELETE', headers: _auth({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ file: path }),
                }).catch(() => {});
                await fetch('/api/knowledge/pending/' + encodeURIComponent(row.docId), {
                    method: 'DELETE', headers: _auth(),
                }).catch(() => {});
            } else {
                const r = await fetch('/api/knowledge/files', {
                    method: 'DELETE', headers: _auth({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ path: path }),
                });
                if (!r.ok) { alert(T('kbmatrix.delete_failed', 'Löschen fehlgeschlagen.')); return; }
            }
            delete _assign[path];
            _rows = _rows.filter(r => r.path !== path);
            tr.remove();
            const cnt = ov.querySelector('.kbm-count');
            if (cnt) cnt.textContent = _rows.length + ' ' + T('kbmatrix.docs', 'Dokumente');
            // Gruppen-Zähler in den Kopfzeilen neu setzen
            ov.querySelectorAll('.kbm-th-count').forEach(el => { el.textContent = _groupCount(el.dataset.gid); });
        } catch (e) {
            alert(T('kbmatrix.delete_failed', 'Löschen fehlgeschlagen.'));
        }
    }

    // ── Spaltenbreiten per Drag ──────────────────────────────────────────────
    function _bindResize(ov) {
        const table = ov.querySelector('.kbm-table');
        const cols  = ov.querySelectorAll('.kbm-table col');
        const ths   = ov.querySelectorAll('.kbm-table thead th');
        let ci = -1, startX = 0, startW = 0, startTableW = 0;
        const onMove = (e) => {
            if (ci < 0) return;
            const w = Math.max(40, startW + (e.clientX - startX));
            if (cols[ci]) cols[ci].style.width = w + 'px';
            table.style.width = (startTableW + (w - startW)) + 'px';
        };
        const onUp = () => {
            ci = -1;
            document.body.classList.remove('kbm-resizing');
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        ov.querySelectorAll('.kbm-resizer').forEach(rz => {
            rz.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                ci = parseInt(rz.dataset.ci, 10);
                startX = e.clientX;
                startW = ths[ci] ? ths[ci].getBoundingClientRect().width : 100;
                startTableW = table.getBoundingClientRect().width;
                document.body.classList.add('kbm-resizing');
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
        });
    }

    function close() {
        document.getElementById('kbm-overlay')?.remove();
        // Übersicht im Wissen-Tab auffrischen (Zähler)
        if (window.knowledgeManager && window.knowledgeManager._refreshGroups) {
            window.knowledgeManager._refreshGroups();
        }
    }

    return { open, close };
})();
