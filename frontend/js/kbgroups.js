/**
 * Jarvis Wissensgruppen (Modell B – logische Tags)
 * Gemeinsamer Helfer fuer knowledge.js (Ordner/Upload/Uebersicht) und
 * extractor.js (Zielgruppe beim Genehmigen). Kapselt Laden/Cachen der Gruppen,
 * das Tag-Popover pro Datei und die Checkbox-Auswahl fuer Upload/Extraktor.
 */
window.KbGroups = (function () {
    'use strict';

    const UNGROUPED = 'ungrouped';
    let _groups = [];          // [{id,name,color,order,count}]
    let _ungrouped = null;     // Anzahl ungruppierter Dateien (oder null)

    function _t(key, def) { return (window.t && window.t(key)) || def; }
    function _auth(extra) {
        const tok = localStorage.getItem('jarvis_token') || '';
        return Object.assign({ 'Authorization': 'Bearer ' + tok }, extra || {});
    }
    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }
    function _base(path) {
        const p = String(path || '');
        const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
        return i >= 0 ? p.slice(i + 1) : p;
    }

    async function load() {
        try {
            const r = await fetch('/api/knowledge/groups', { headers: _auth() });
            const d = await r.json();
            if (d && d.ok) {
                _groups = d.groups || [];
                _ungrouped = (d.ungrouped_count != null) ? d.ungrouped_count : null;
            }
        } catch (e) { /* still */ }
        return _groups;
    }

    function all() { return _groups; }
    function byId(id) { return _groups.find(g => g.id === id) || null; }
    function nameOf(id) { const g = byId(id); return g ? g.name : id; }
    function colorOf(id) { const g = byId(id); return g ? g.color : '#64748b'; }

    async function getAssignment(path) {
        try {
            const r = await fetch('/api/knowledge/assignments?path=' + encodeURIComponent(path), { headers: _auth() });
            const d = await r.json();
            return (d && d.ok && d.groups) ? d.groups : [];
        } catch (e) { return []; }
    }

    async function getMap() {
        try {
            const r = await fetch('/api/knowledge/assignments', { headers: _auth() });
            const d = await r.json();
            return (d && d.ok && d.assignments) ? d.assignments : {};
        } catch (e) { return {}; }
    }

    async function setAssignment(path, ids) {
        const r = await fetch('/api/knowledge/assignments', {
            method: 'POST',
            headers: _auth({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ path: path, groups: ids || [] }),
        });
        return r.json();
    }

    // ── Gruppen-Verwaltung (anlegen / umbenennen / loeschen) ────────────────
    async function createGroup(name, color) {
        const r = await fetch('/api/knowledge/groups', {
            method: 'POST',
            headers: _auth({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name: name, color: color || '#64748b' }),
        });
        return r.json();
    }
    async function updateGroup(gid, patch) {
        const r = await fetch('/api/knowledge/groups/' + encodeURIComponent(gid), {
            method: 'PATCH',
            headers: _auth({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(patch || {}),
        });
        return r.json();
    }
    async function deleteGroup(gid) {
        const r = await fetch('/api/knowledge/groups/' + encodeURIComponent(gid), {
            method: 'DELETE', headers: _auth(),
        });
        return r.ok;
    }

    // ── Farbiges Gruppen-Pill (nur Anzeige) ─────────────────────────────────
    function pillHtml(id, extra) {
        const c = colorOf(id);
        return '<span class="kb-grp-pill" style="--grp:' + _esc(c) + ';">'
            + _esc(nameOf(id)) + (extra || '') + '</span>';
    }

    // ── Checkbox-Auswahl (fuer Upload + Extraktor) ──────────────────────────
    // Rendert Checkboxen in ein Ziel-Element; ausgelesen via readChecked().
    function renderCheckboxes(containerEl, selectedIds) {
        if (!containerEl) return;
        const sel = new Set(selectedIds || []);
        if (!_groups.length) {
            containerEl.innerHTML = '<span class="kb-hint" style="margin:0;">'
                + _esc(_t('kbgroups.none', 'Keine Gruppen angelegt.')) + '</span>';
            return;
        }
        containerEl.innerHTML = _groups.map(g =>
            '<label class="kb-grp-check" style="--grp:' + _esc(g.color) + ';">'
            + '<input type="checkbox" value="' + _esc(g.id) + '"' + (sel.has(g.id) ? ' checked' : '') + '>'
            + '<span>' + _esc(g.name) + '</span></label>'
        ).join('');
    }
    function readChecked(containerEl) {
        if (!containerEl) return [];
        return [...containerEl.querySelectorAll('input[type=checkbox]:checked')].map(c => c.value);
    }

    // ── Button + aufklappbare Checkbox-Liste ────────────────────────────────
    // Kompakter Button je Zeile; Klick oeffnet die vertikale Gruppenliste
    // (Checkbox links) via openTagPopover(). Beschriftung zeigt die aktuelle
    // Zuordnung als farbige Mini-Tags.
    function buttonLabel(currentIds) {
        const ids = (currentIds || []).filter(id => byId(id));
        if (!ids.length) {
            return '<span class="kb-grp-btn-empty">' + _esc(_t('kbgroups.choose', 'Gruppen…')) + '</span>';
        }
        return ids.map(id =>
            '<span class="kb-grp-btn-tag" style="--grp:' + _esc(colorOf(id)) + ';">'
            + _esc(nameOf(id)) + '</span>').join('');
    }
    function buttonHtml(path, currentIds) {
        return '<button type="button" class="kb-grp-btn" data-path="' + _esc(path) + '" '
            + 'title="' + _esc(_t('kbgroups.assign_title', 'Gruppen')) + '">'
            + '<span class="kb-grp-btn-icon">🏷</span>'
            + '<span class="kb-grp-btn-label">' + buttonLabel(currentIds) + '</span>'
            + '<span class="kb-grp-btn-caret">▾</span></button>';
    }
    function bindButtons(rootEl, onChange) {
        if (!rootEl) return;
        rootEl.querySelectorAll('.kb-grp-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const path = btn.getAttribute('data-path');
                openTagPopover(btn, path, (p, ids) => {
                    const lbl = btn.querySelector('.kb-grp-btn-label');
                    if (lbl) lbl.innerHTML = buttonLabel(ids);
                    if (onChange) onChange(p, ids);
                });
            });
        });
    }

    // ── Tag-Popover pro Datei (vertikale Liste mit Checkbox links) ──────────
    async function openTagPopover(anchorEl, path, onSaved) {
        document.getElementById('kb-grp-popover')?.remove();
        const current = await getAssignment(path);
        const sel = new Set(current);

        const pop = document.createElement('div');
        pop.id = 'kb-grp-popover';
        pop.className = 'kb-grp-popover';
        const rows = _groups.length
            ? _groups.map(g =>
                '<label class="kb-grp-check" style="--grp:' + _esc(g.color) + ';">'
                + '<input type="checkbox" value="' + _esc(g.id) + '"' + (sel.has(g.id) ? ' checked' : '') + '>'
                + '<span>' + _esc(g.name) + '</span></label>').join('')
            : '<span class="kb-hint" style="margin:0;">' + _esc(_t('kbgroups.none', 'Keine Gruppen angelegt.')) + '</span>';
        pop.innerHTML =
            '<div class="kb-grp-popover-title">' + _esc(_t('kbgroups.assign_title', 'Gruppen')) + '</div>'
            + '<div class="kb-grp-popover-body">' + rows + '</div>'
            + '<div class="kb-grp-popover-file" title="' + _esc(path) + '">' + _esc(_base(path)) + '</div>';
        document.body.appendChild(pop);

        // Positionierung am Anker
        const r = anchorEl.getBoundingClientRect();
        pop.style.top = (window.scrollY + r.bottom + 4) + 'px';
        pop.style.left = Math.max(8, window.scrollX + r.right - pop.offsetWidth) + 'px';

        // Auto-Save bei jeder Aenderung
        pop.querySelectorAll('input[type=checkbox]').forEach(cb => {
            cb.addEventListener('change', async () => {
                const ids = [...pop.querySelectorAll('input:checked')].map(c => c.value);
                await setAssignment(path, ids);
                if (onSaved) onSaved(path, ids);
            });
        });

        // Schliessen bei Klick ausserhalb
        setTimeout(() => {
            const closer = (ev) => {
                if (!pop.contains(ev.target) && ev.target !== anchorEl) {
                    pop.remove();
                    document.removeEventListener('mousedown', closer);
                }
            };
            document.addEventListener('mousedown', closer);
        }, 0);
    }

    return {
        UNGROUPED, load, all, byId, nameOf, colorOf,
        getAssignment, getMap, setAssignment,
        createGroup, updateGroup, deleteGroup,
        pillHtml, renderCheckboxes, readChecked, openTagPopover,
        buttonHtml, bindButtons,
        ungroupedCount: () => _ungrouped,
        baseName: _base, esc: _esc,
    };
})();
