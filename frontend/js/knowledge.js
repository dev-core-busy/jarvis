/**
 * Jarvis Knowledge Manager – Frontend-Steuerung für Wissen-Tab
 */

class JarvisKnowledgeManager {
    constructor() {
        this._pollInterval = null;

        // Buttons verbinden
        const btnReindex = document.getElementById('btn-kb-reindex');
        const btnAddFolder = document.getElementById('btn-kb-add-folder');
        const btnCreateFolder = document.getElementById('btn-kb-create-folder');

        if (btnReindex) btnReindex.addEventListener('click', () => this.reindex());
        if (btnAddFolder) btnAddFolder.addEventListener('click', () => this.addFolder());
        if (btnCreateFolder) btnCreateFolder.addEventListener('click', () => this.createFolder());

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
        // Gruppen-Auswahl fuer "Ordner neu anlegen" (Speicherordner-Zuordnung)
        window.KbGroups.renderCheckboxes(document.getElementById('kb-folder-groups'), []);
        // Die Massenzuordnungs-Tabelle (▦) wurde nach /wissen -> "Massenzuordnung"
        // verschoben (nur fuer globale Wissens-Editoren).
    }

    _renderGroupsOverview() {
        const el = document.getElementById('kb-groups-overview');
        if (!el || !window.KbGroups) return;
        const KG = window.KbGroups;
        const T = (k, d) => (window.t && window.t(k)) || d;
        const rows = KG.all().map(g => {
            const ed = this._editorsSummary(g) + this._foldersSummary(g);
            return `
            <div class="kb-grp-manage-row" data-gid="${KG.esc(g.id)}" draggable="true">
                <span class="kb-grp-drag" title="${T('kbgroups.drag_title', 'Ziehen zum Sortieren')}">⋮⋮</span>
                <input type="color" class="kb-grp-color-input" value="${KG.esc(g.color)}" title="${T('kbgroups.color', 'Farbe ändern')}">
                <span class="kb-grp-manage-name" title="${T('kbgroups.show_files', 'Dokumente anzeigen')}">${KG.esc(g.name)}${ed}</span>
                <span class="kb-grp-count">${g.count}</span>
                <span class="kb-grp-manage-spacer"></span>
                <button class="kb-grp-manage-btn kb-grp-perms" title="${T('kbgroups.perms', 'Berechtigungen verwalten')}">🔐</button>
                <button class="kb-grp-manage-btn kb-grp-rename" title="${T('kbgroups.rename', 'Umbenennen')}">✏️</button>
                <button class="kb-grp-manage-btn kb-grp-delete" title="${T('kbgroups.delete', 'Löschen')}">×</button>
            </div>`;
        }).join('');
        const ung = KG.ungroupedCount();
        const ungRow = (ung != null) ? `
            <div class="kb-grp-manage-row kb-grp-row-ung">
                <span class="kb-grp-dot" style="background:var(--text-secondary);"></span>
                <span class="kb-grp-manage-name" title="${T('kbgroups.show_files', 'Dokumente anzeigen')}">${T('kbgroups.ungrouped', 'ungruppiert')}</span>
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
            row.querySelector('.kb-grp-perms').onclick = () => this._editGroupPermissions(gid);
            row.querySelector('.kb-grp-rename').onclick = () => this._renameGroup(gid);
            row.querySelector('.kb-grp-delete').onclick = () => this._deleteGroup(gid);
        });

        // "ungruppiert"-Zeile: Klick zeigt die Dateien ohne Gruppen-Zuordnung
        const ungName = el.querySelector('.kb-grp-row-ung .kb-grp-manage-name');
        if (ungName) ungName.onclick = () => this._showUngroupedFiles();

        this._initGroupReorder(el.querySelector('.kb-grp-manage-list'));
    }

    // ── Drag & Drop Sortierung der Wissensgruppen ─────────────────────────
    // Zeile am ⋮⋮-Griff (oder frei) ziehen; beim Ablegen wird die neue
    // Reihenfolge als order-Feld (0..n) via PATCH persistiert.
    _initGroupReorder(list) {
        if (!list) return;
        let dragRow = null;

        list.querySelectorAll('.kb-grp-manage-row[data-gid]').forEach(row => {
            row.addEventListener('dragstart', (e) => {
                // Nicht aus Eingabefeldern/Buttons heraus ziehen (Farbwähler etc.)
                if (e.target.closest && e.target.closest('input, button')) { e.preventDefault(); return; }
                dragRow = row;
                row.classList.add('kb-grp-dragging');
                e.dataTransfer.effectAllowed = 'move';
                try { e.dataTransfer.setData('text/plain', row.dataset.gid); } catch (_) { /* IE */ }
            });
            row.addEventListener('dragend', () => {
                row.classList.remove('kb-grp-dragging');
                list.querySelectorAll('.kb-grp-dropover').forEach(r => r.classList.remove('kb-grp-dropover'));
                if (dragRow) { dragRow = null; this._saveGroupOrder(list); }
            });
            row.addEventListener('dragover', (e) => {
                if (!dragRow || dragRow === row) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                row.classList.add('kb-grp-dropover');
                // Ober-/Unterhalb der Zeilenmitte einsortieren
                const rect = row.getBoundingClientRect();
                const before = (e.clientY - rect.top) < rect.height / 2;
                row.parentNode.insertBefore(dragRow, before ? row : row.nextSibling);
            });
            row.addEventListener('dragleave', () => row.classList.remove('kb-grp-dropover'));
            row.addEventListener('drop', (e) => e.preventDefault());
        });
    }

    async _saveGroupOrder(list) {
        const KG = window.KbGroups;
        const ids = [...list.querySelectorAll('.kb-grp-manage-row[data-gid]')].map(r => r.dataset.gid);
        // Nur Gruppen patchen, deren Position sich geaendert hat
        const changed = ids.filter((gid, i) => {
            const g = KG.byId(gid);
            return g && g.order !== i;
        });
        if (!changed.length) return;
        try {
            await Promise.all(ids.map((gid, i) => {
                const g = KG.byId(gid);
                return (g && g.order !== i) ? KG.updateGroup(gid, { order: i }) : null;
            }));
            await this._refreshGroups();
            this._showNotification(window.t('kbgroups.order_saved') || 'Reihenfolge gespeichert', 'success');
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
            await this._refreshGroups();
        }
    }

    // Fasst die zusätzlichen Editoren einer Gruppe für die Anzeige in Klammern
    // hinter dem Gruppennamen zusammen (AD-Benutzer + Kurz-CN der AD-Gruppen).
    _editorsSummary(g) {
        const KG = window.KbGroups;
        const cn = (dn) => { const m = /^CN=([^,]+)/i.exec((dn || '').trim()); return m ? m[1] : (dn || '').trim(); };
        const users = (g.editors_users || '').split(',').map(s => s.trim()).filter(Boolean);
        const groups = (g.editors_group || '').split('\n').map(cn).filter(Boolean);
        const all = users.concat(groups);
        if (!all.length) return '';
        return ` <span class="kb-grp-editors" title="${KG.esc(all.join(', '))}">(${KG.esc(all.join(', '))})</span>`;
    }

    // Zeigt die der Gruppe zugeordneten Speicherordner (/wissen) hinter dem Namen.
    _foldersSummary(g) {
        const KG = window.KbGroups;
        const fl = g.folders || [];
        if (!fl.length) return '';
        return ` <span class="kb-grp-editors" title="${KG.esc(fl.join(', '))}">📁 ${KG.esc(fl.map(p => p.replace(/^data\//, '')).join(', '))}</span>`;
    }

    // ── Pro-Gruppe Berechtigungen (zusaetzliche AD-Editoren + Speicherordner) ──
    async _editGroupPermissions(gid) {
        const KG = window.KbGroups;
        const g = KG && KG.byId(gid);
        if (!g) return;
        const T = (k, d) => (window.t && window.t(k)) || d;
        const esc = KG.esc;

        // Konfigurierte Knowledge-Ordner fuer die Speicherordner-Auswahl laden
        let kbFolders = [];
        try {
            const resp = await fetch('/api/knowledge/stats', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            kbFolders = ((await resp.json()).folders || []).map(f => f.path);
        } catch (e) { /* Sektion zeigt dann nur den Hinweis */ }
        const assigned = new Set(g.folders || []);
        const folderRows = kbFolders.length
            ? kbFolders.map(p => `
                <label class="kb-grp-check" style="--grp:${esc(g.color)};">
                    <input type="checkbox" class="kbgrp-perm-folder" value="${esc(p)}"${assigned.has(p) ? ' checked' : ''}>
                    <span>📁 ${esc(p)}</span>
                </label>`).join('')
            : `<span class="kb-hint" style="margin:0;">${T('knowledge.no_folders', 'Keine Ordner konfiguriert')}</span>`;

        // Bestehendes Modal entfernen (frischer State pro Aufruf)
        const old = document.getElementById('kbgrp-perm-modal');
        if (old) old.remove();

        const m = document.createElement('div');
        m.id = 'kbgrp-perm-modal';
        m.className = 'modal';
        m.style.zIndex = '10001';
        m.innerHTML = `
            <div class="modal-content glass" style="max-width:620px;">
                <div class="modal-header">
                    <h2>${T('kbgroups.perms_title', 'Berechtigungen')} – ${esc(g.name)}</h2>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <button class="btn-icon" id="kbgrp-perm-close" aria-label="Schließen">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                </div>
                <div class="modal-body" style="overflow-y:auto;">
                    <p class="kb-hint" style="margin-top:0;">${T('kbgroups.perms_hint',
                        'Diese AD-Benutzer und -Gruppen dürfen – zusätzlich zu den globalen Wissens-Editoren (Einstellungen → Sicherheit) – NUR diese Gruppe über die /wissen-Seite bearbeiten und Dokumente zuordnen. Hinweis: greift erst, wenn die globalen Editoren dort eingeschränkt sind – sonst darf ohnehin jeder alle Gruppen bearbeiten. Lokale Admins sind immer berechtigt.')}</p>
                    <label class="kb-form-label" style="display:block;margin:12px 0 4px;">${T('kbgroups.perms_users', 'Zusätzliche Editoren (AD-Benutzer)')}</label>
                    <input type="text" id="kbgrp-perm-users" class="kb-input" style="width:100%;box-sizing:border-box;">
                    <label class="kb-form-label" style="display:block;margin:16px 0 4px;">${T('kbgroups.perms_groups', 'Zusätzliche Editoren (AD-Gruppen)')}</label>
                    <textarea id="kbgrp-perm-groups" class="kb-input" rows="2" style="width:100%;box-sizing:border-box;"></textarea>
                    <label class="kb-form-label" style="display:block;margin:16px 0 4px;">${T('kbgroups.folders_label', 'Speicherordner (/wissen)')}</label>
                    <p class="kb-hint" style="margin:0 0 6px;">${T('kbgroups.folders_hint',
                        'Nutzern dieser Gruppe werden auf der /wissen-Seite nur diese Ordner als Speicherziel angeboten. Ohne Auswahl gilt der Standardordner data/knowledge.')}</p>
                    <div id="kbgrp-perm-folders" class="kb-grp-checks">${folderRows}</div>
                    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
                        <button type="button" id="kbgrp-perm-cancel" class="kb-btn-action">${T('common.cancel', 'Abbrechen')}</button>
                        <button type="button" id="kbgrp-perm-save" class="kb-btn-action kb-btn-primary">${T('common.save', 'Speichern')}</button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(m);

        const usersInp = m.querySelector('#kbgrp-perm-users');
        const groupsInp = m.querySelector('#kbgrp-perm-groups');
        // Werte VOR dem Attach setzen, damit die Chip-Liste sie sofort rendert.
        usersInp.value = g.editors_users || '';
        groupsInp.value = g.editors_group || '';
        if (window.LdapPicker) {
            window.LdapPicker.attachField(usersInp, { kind: 'users', sep: ',' });
            window.LdapPicker.attachField(groupsInp, { kind: 'groups', sep: '\n' });
        }

        const close = () => m.remove();
        m.querySelector('#kbgrp-perm-close').onclick = close;
        m.querySelector('#kbgrp-perm-cancel').onclick = close;
        m.addEventListener('click', (e) => { if (e.target === m) close(); });
        m.querySelector('#kbgrp-perm-save').onclick = async () => {
            const patch = {
                editors_users: (usersInp.value || '').trim(),
                editors_group: (groupsInp.value || '').trim(),
            };
            // Speicherordner nur mitsenden, wenn geaendert (das Feld duerfen nur
            // globale Wissens-Editoren aendern – sonst lehnt der Server ab)
            const pickedFolders = [...m.querySelectorAll('.kbgrp-perm-folder:checked')].map(c => c.value);
            const before = (g.folders || []).slice().sort().join(',');
            if (pickedFolders.slice().sort().join(',') !== before) patch.folders = pickedFolders;
            const res = await KG.updateGroup(gid, patch);
            if (res && res.ok) {
                await this._refreshGroups();
                this._showNotification(T('kbgroups.perms_saved', 'Berechtigungen gespeichert'), 'success');
                close();
            } else {
                this._showNotification((res && res.error) || T('kbgroups.perms_err', 'Fehler beim Speichern'), 'error');
            }
        };
        requestAnimationFrame(() => m.classList.add('open'));
    }

    async _refreshGroups() {
        await window.KbGroups.load();
        this._renderGroupsOverview();
        window.KbGroups.renderCheckboxes(document.getElementById('kb-upload-groups'), []);
        window.KbGroups.renderCheckboxes(document.getElementById('kb-folder-groups'), []);
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
            this._showNotification((res && res.error) || window.t('knowledge.err_create'), 'error');
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
        else this._showNotification((res && res.error) || window.t('common.error'), 'error');
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
            this._showNotification(window.t('knowledge.err_delete'), 'error');
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
        const barBulk = `<div class="kb-bulk-bar hidden">
                <button class="btn-secondary kb-bulk-del" type="button">${window.t('knowledge.bulk_remove') || 'Aus Gruppe entfernen'} (<span class="kb-bulk-count">0</span>)</button>
                <button class="btn-secondary kb-bulk-clear" type="button">${window.t('knowledge.bulk_clear') || 'Auswahl aufheben'}</button>
                <span class="kb-bulk-hint">${window.t('knowledge.bulk_hint') || 'Mehrfachauswahl: Klick oder mit der Maus aufziehen'}</span>
            </div>`;
        box.innerHTML = title + barBulk + `<div class="kb-grp-file-list">` + files.map(p => `
            <div class="kb-grp-file-row" data-path="${KG.esc(p)}">
                <span class="kb-file-icon">${this._fileIcon(p)}</span>
                <span class="kb-file-name" title="${KG.esc(p)}">${KG.esc(KG.baseName(p))}</span>
                <button class="kb-btn-view-file kb-grp-tag" data-path="${KG.esc(p)}" title="${window.t('kbgroups.perms') || 'Berechtigungen verwalten'}">🔐</button>
                <button class="kb-btn-remove kb-grp-untag" data-path="${KG.esc(p)}" title="${window.t('kbgroups.remove') || 'Aus Gruppe entfernen'}">✕</button>
            </div>`).join('') + `</div>`;
        // Wissensgruppen des Eintrags bearbeiten (Popover) – danach Liste auffrischen
        box.querySelectorAll('.kb-grp-tag').forEach(btn => {
            btn.onclick = () => {
                if (!window.KbGroups) return;
                window.KbGroups.openTagPopover(btn, btn.dataset.path, async () => {
                    await KG.load();
                    this._renderGroupsOverview();
                    this._showGroupFiles(gid);
                });
            };
        });
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
        // Mehrfachauswahl (Drag/Klick) -> ausgewaehlte Dokumente gesammelt aus der Gruppe entfernen
        this._setupRowSelection(box, '.kb-grp-file-row', (paths) => this._bulkRemoveFromGroup(paths, gid));
        this._bindFilePreview(box);
    }

    async _showUngroupedFiles() {
        const box = document.getElementById('kb-groups-files');
        if (!box || !window.KbGroups) return;
        const KG = window.KbGroups;
        const T = (k, d) => (window.t && window.t(k)) || d;
        box.style.display = 'block';
        box.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading') || 'Lädt…'}</div>`;
        let files = [];
        try {
            const resp = await fetch('/api/knowledge/groups/ungrouped', {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            const d = await resp.json();
            if (!resp.ok || !d.ok) throw new Error(d.error || ('HTTP ' + resp.status));
            files = d.files || [];
        } catch (e) {
            box.innerHTML = `<div class="kb-files-empty">${KG.esc(e.message)}</div>`;
            return;
        }
        const title = `<div class="kb-grp-files-head">
            <span class="kb-grp-dot" style="background:var(--text-secondary);"></span>
            <b>${T('kbgroups.ungrouped', 'ungruppiert')}</b>
            <span class="kb-hint" style="margin:0;">${files.length} ${window.t('kbgroups.docs') || 'Dokument(e)'}</span></div>`;
        if (!files.length) {
            box.innerHTML = title + `<div class="kb-files-empty">${T('kbgroups.no_ungrouped', 'Keine ungruppierten Dokumente – alles ist zugeordnet.')}</div>`;
            return;
        }
        // Ungruppierte Dateien sind keiner Gruppe zugeordnet -> das "✕" LÖSCHT die
        // Datei ganz (in der Gruppen-Ansicht entfernt es dagegen nur die Zuordnung).
        const barBulk = `<div class="kb-bulk-bar hidden">
                <button class="btn-secondary kb-bulk-del" type="button">${window.t('knowledge.bulk_delete') || 'Auswahl löschen'} (<span class="kb-bulk-count">0</span>)</button>
                <button class="btn-secondary kb-bulk-clear" type="button">${window.t('knowledge.bulk_clear') || 'Auswahl aufheben'}</button>
                <span class="kb-bulk-hint">${window.t('knowledge.bulk_hint') || 'Mehrfachauswahl: Klick oder mit der Maus aufziehen'}</span>
            </div>`;
        box.innerHTML = title + barBulk + files.map(p => `
            <div class="kb-grp-file-row" data-path="${KG.esc(p)}">
                <span class="kb-file-icon">${this._fileIcon(p)}</span>
                <span class="kb-file-name" title="${KG.esc(p)}">${KG.esc(KG.baseName(p))}</span>
                <button class="kb-btn-view-file kb-grp-tag" data-path="${KG.esc(p)}" title="${window.t('kbgroups.perms') || 'Berechtigungen verwalten'}">🔐</button>
                <button class="kb-btn-remove kb-ung-del" data-path="${KG.esc(p)}" title="${T('knowledge.file_delete_title', 'Datei löschen')}">✕</button>
            </div>`).join('');
        this._setupRowSelection(box, '.kb-grp-file-row', (paths) =>
            this._bulkDeleteFiles(paths, () => { this._renderGroupsOverview(); return this._showUngroupedFiles(); }));
        // Wissensgruppen zuweisen (Popover) – danach Ansicht auffrischen
        box.querySelectorAll('.kb-grp-tag').forEach(btn => {
            btn.onclick = () => {
                if (!window.KbGroups) return;
                window.KbGroups.openTagPopover(btn, btn.dataset.path, async () => {
                    await KG.load();
                    this._renderGroupsOverview();
                    this._showUngroupedFiles();
                });
            };
        });
        box.querySelectorAll('.kb-ung-del').forEach(btn => {
            btn.onclick = async () => {
                const path = btn.dataset.path;
                if (!confirm((window.t('knowledge.file_delete_confirm') || 'Datei „{name}" wirklich löschen?')
                        .replace('{name}', KG.baseName(path)))) return;
                try {
                    const r = await fetch('/api/knowledge/files', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json',
                                   'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') },
                        body: JSON.stringify({ path })
                    });
                    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error || ('HTTP ' + r.status)); }
                    this._showNotification(window.t('knowledge.file_deleted') || 'Datei gelöscht', 'success');
                    await KG.load();
                    this._renderGroupsOverview();
                    this._showUngroupedFiles();
                    this.fetchStats && this.fetchStats();
                } catch (e) {
                    this._showNotification((window.t('common.error') || 'Fehler') + ': ' + e.message, 'error');
                }
            };
        });
        this._bindFilePreview(box);
    }

    // Maus-über-Vorschau fuer Datei-Zeilen in der Gruppen-/Ungruppiert-Ansicht:
    // Bilder/GIF/SVG -> <img>, PDF -> <iframe>, Text/JSON/MD/… -> Textvorschau
    // (wie in der Wissenstabelle). Inhalte werden lazy geladen und gecacht.
    // Dateisymbol nach Endung (PDF eigenes Symbol; Bild/Office/Medien passend).
    _fileIcon(path) {
        const ext = String(path || '').split('.').pop().toLowerCase();
        if (ext === 'pdf') return '📕';
        if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico', 'tif', 'tiff'].includes(ext)) return '🖼️';
        if (['doc', 'docx', 'odt', 'rtf'].includes(ext)) return '📝';
        if (['xls', 'xlsx', 'ods', 'csv'].includes(ext)) return '📊';
        if (['ppt', 'pptx', 'odp'].includes(ext)) return '📽️';
        if (['mp3', 'wav', 'ogg', 'm4a', 'flac'].includes(ext)) return '🎵';
        if (['mp4', 'mov', 'mkv', 'avi', 'webm'].includes(ext)) return '🎬';
        if (['zip', 'tar', 'gz', '7z', 'rar'].includes(ext)) return '🗜️';
        return '📄';
    }

    _bindFilePreview(box) {
        if (!box) return;
        const token = () => localStorage.getItem('jarvis_token') || '';
        const T = (k, d) => (window.t && window.t(k)) || d;
        if (!this._filePreviewCache) this._filePreviewCache = {};
        const cache = this._filePreviewCache;

        // Wiederverwendbaren Tooltip nur einmal erzeugen.
        let tip = this._filePreviewTip;
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'kb-file-tip';
            tip.style.display = 'none';
            document.body.appendChild(tip);
            this._filePreviewTip = tip;
            let ht = null;
            tip._cancelHide   = () => clearTimeout(ht);
            tip._scheduleHide = () => { clearTimeout(ht); ht = setTimeout(() => { tip.style.display = 'none'; tip._path = null; }, 250); };
            tip.addEventListener('mouseenter', () => tip._cancelHide());
            tip.addEventListener('mouseleave', () => tip._scheduleHide());
            // ESC schliesst die Vorschau sofort (unabhaengig von der Maus-Position).
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && tip.style.display !== 'none') {
                    tip._cancelHide();
                    tip.style.display = 'none';
                    tip._path = null;
                }
            });
        }

        const IMG = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico'];
        // disp=inline: neue URL, damit alte im Browser gecachte attachment-Antwort
        // (die den PDF-Download ausloeste) nicht wiederverwendet wird.
        const rawUrl = (p) => '/api/knowledge/file_raw?path=' + encodeURIComponent(p)
            + '&token=' + encodeURIComponent(token()) + '&disp=inline';

        const place = (anchor) => {
            const r = anchor.getBoundingClientRect();
            const w = Math.min(560, window.innerWidth - 24);
            tip.style.width = w + 'px';
            tip.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left)) + 'px';
            tip._anchorBottom = r.bottom + 6;
            tip.style.top = tip._anchorBottom + 'px';
        };
        const reclamp = () => {
            const h = tip.offsetHeight;
            let top = tip._anchorBottom || 12;
            if (top + h > window.innerHeight - 12) top = Math.max(12, window.innerHeight - h - 12);
            tip.style.top = top + 'px';
        };
        const setText = (entry) => {
            tip.classList.remove('kb-file-tip-media');
            tip.classList.toggle('kb-file-tip-json', !!entry.json);
            tip.textContent = entry.text;
            reclamp();
        };
        const setMedia = (html) => {
            tip.classList.remove('kb-file-tip-json');
            tip.classList.add('kb-file-tip-media');
            tip.innerHTML = html;
            reclamp();
        };
        const prettyMaybeJson = (txt) => {
            const s = (txt || '').trim();
            if (s && (s[0] === '{' || s[0] === '[')) {
                try { return { text: JSON.stringify(JSON.parse(s), null, 2), json: true }; } catch (e) {}
            }
            return { text: txt, json: false };
        };

        const show = (anchor) => {
            tip._cancelHide();
            const row = anchor.closest('[data-path]');
            if (!row) return;
            const path = row.dataset.path;
            tip._path = path;
            const ext = (path.split('.').pop() || '').toLowerCase();
            place(anchor);
            tip.style.display = 'block';

            if (IMG.includes(ext)) {
                setMedia('<img src="' + rawUrl(path) + '" alt="" '
                    + 'style="max-width:100%;max-height:60vh;display:block;border-radius:6px;">');
                const img = tip.querySelector('img');
                if (img) { img.onload = reclamp; img.onerror = () => setText({ text: T('kbmatrix.no_content', '(Vorschau nicht verfügbar)'), json: false }); }
                return;
            }
            if (ext === 'pdf') {
                setMedia('<iframe src="' + rawUrl(path) + '#toolbar=0" '
                    + 'style="width:100%;height:60vh;border:0;border-radius:6px;background:#fff;"></iframe>');
                return;
            }
            // Text/JSON/MD/… -> file_read (mit JSON-Verschönerung wie in der Wissenstabelle)
            if (cache[path] !== undefined) { setText(cache[path]); return; }
            setText({ text: T('kbmatrix.loading', 'lädt…'), json: false });
            fetch('/api/knowledge/file_read?path=' + encodeURIComponent(path),
                  { headers: { 'Authorization': 'Bearer ' + token() } })
                .then(r => r.json()).then(d => {
                    let raw = (d && d.ok && d.content != null && d.content !== '')
                        ? String(d.content) : T('kbmatrix.no_content', '(Inhalt nicht als Text lesbar)');
                    raw = raw.replace(/\s+$/, '');
                    const entry = prettyMaybeJson(raw);
                    if (entry.text.length > 8000) entry.text = entry.text.slice(0, 8000) + '\n…';
                    cache[path] = entry;
                    if (tip.style.display !== 'none' && tip._path === path) setText(entry);
                }).catch(() => {
                    cache[path] = { text: T('kbmatrix.no_content', '(Inhalt nicht lesbar)'), json: false };
                    if (tip._path === path) setText(cache[path]);
                });
        };

        // Listener nur einmal pro Box-Element anhaengen (innerHTML-Neuaufbau entfernt sie nicht).
        if (box._filePreviewBound) return;
        box._filePreviewBound = true;
        // Vorschau wird ueber das Datei-SYMBOL ausgeloest (nicht ueber den
        // Dateinamen) – so bleibt der Name frei fuer Auswahl/Klick.
        box.addEventListener('mouseover', e => {
            const anchor = e.target.closest('.kb-file-icon');
            if (anchor && box.contains(anchor)) show(anchor);
        });
        box.addEventListener('mouseout', e => {
            const anchor = e.target.closest('.kb-file-icon');
            if (!anchor) return;
            if (e.relatedTarget && (tip === e.relatedTarget || tip.contains(e.relatedTarget))) return;
            tip._scheduleHide();
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
                status.style.color = result.total_rejected > 0 ? 'var(--warning)' : 'var(--success)';
                setTimeout(() => { status.textContent = ''; status.style.color = ''; }, 5000);
            }
            this._showNotification(msg, result.total_rejected > 0 ? 'warning' : 'success');
            await this.fetchStats();
        } catch (e) {
            if (status) {
                status.textContent = window.t('knowledge.upload_failed').replace('{msg}', e.message);
                status.style.color = 'var(--danger)';
            }
            this._showNotification(window.t('knowledge.upload_failed').replace('{msg}', e.message), 'error');
        }
    }

    // ─── Stats laden ──────────────────────────────────────────────────

    async fetchStats() {
        const container = document.getElementById('kb-stats-container');

        try {
            const [statsResp, learnedResp, compactResp] = await Promise.all([
                fetch('/api/knowledge/stats', {
                    headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
                }),
                fetch('/api/knowledge/learned_stats', {
                    headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
                }).catch(() => null),
                fetch('/api/knowledge/compact_status', {
                    headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
                }).catch(() => null),
            ]);
            if (!statsResp.ok) throw new Error('HTTP ' + statsResp.status);
            const stats = await statsResp.json();
            const learnedStats = learnedResp && learnedResp.ok ? await learnedResp.json() : null;
            const compactStatus = compactResp && compactResp.ok ? await compactResp.json() : null;

            this._renderStats(stats, learnedStats, compactStatus);
            this._renderFolders(stats.folders);
            this._populateUploadTargets(stats.folders);
        } catch (e) {
            if (container) container.innerHTML = `<div class="kb-error">${window.t('knowledge.load_error').replace('{msg}', e.message)}</div>`;
        }
    }

    _renderStats(stats, learnedStats, compactStatus) {
        const el = document.getElementById('kb-stats-container');
        if (!el) return;

        const sizeMb = (stats.total_size_bytes / (1024 * 1024)).toFixed(1);
        const pdfIcon = stats.pdf_support ? '✅' : '⚠️';
        const docxIcon = stats.docx_support ? '✅' : '⚠️';
        const xlsxIcon = stats.xlsx_support ? '✅' : '⚠️';
        const pptxIcon = stats.pptx_support ? '✅' : '⚠️';
        const pdfTitle = stats.pdf_support ? window.t('knowledge.support_pdf_ok') : window.t('knowledge.support_pdf_missing');
        const docxTitle = stats.docx_support ? window.t('knowledge.support_word_ok') : window.t('knowledge.support_word_missing');
        const xlsxTitle = stats.xlsx_support ? window.t('knowledge.support_excel_ok') : window.t('knowledge.support_excel_missing');
        const pptxTitle = stats.pptx_support ? window.t('knowledge.support_ppt_ok') : window.t('knowledge.support_ppt_missing');
        const videoIcon = stats.video_support ? '✅' : '⚠️';
        const videoTitle = stats.video_support ? window.t('knowledge.support_video_ok') : window.t('knowledge.support_video_missing');
        const imageIcon = stats.image_support ? '✅' : '⚠️';
        const imageTitle = stats.image_support ? window.t('knowledge.support_image_ok') : window.t('knowledge.support_image_missing');
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
            : window.t('knowledge.support_vector_missing');

        // Aktueller Suchmodus
        const mode = stats.search_mode || 'auto';

        // Statuszeile: gelb während Indizierung, grün wenn fertig
        const phase = stats.index_phase || '';
        const isVectorPhase = phase.toLowerCase().includes('vektor');
        const GREEN = 'var(--success)', YELLOW = 'var(--warning)', GREY = 'var(--text-secondary)';

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
            : window.t('knowledge.support_faiss_missing');

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
            </div>`;
            // Wissens-Verdichtung: Verdichten-Button + ❓-Erklärung + Auto-Schalter
            const cs = compactStatus || {};
            const pending = cs.pending_files || 0;
            const lastRun = cs.last_run ? `${window.t('knowledge.compact.last_run')} ${cs.last_run}` : '';
            el.innerHTML += `
            <div class="kb-learned-panel" title="${window.t('knowledge.compact.title')}">
                <span class="kb-learned-icon">🗜️</span>
                <span class="kb-learned-title">${window.t('knowledge.compact.title')}</span>
                <button class="kb-learned-open-btn" id="kb-compact-btn" onclick="window.knowledgeManager.compactLearned(this)"
                        title="${window.t('knowledge.compact.btn_title')}" ${cs.running ? 'disabled' : ''}>
                    ${cs.running ? window.t('knowledge.compact.running') : window.t('knowledge.compact.btn')}
                </button>
                <button class="kb-learned-open-btn" onclick="window.knowledgeManager.showCompactInfo(true)"
                        title="${window.t('knowledge.compact.info_title')}" style="font-weight:700;">❓</button>
                <label class="kb-learned-embed-opt" title="${window.t('knowledge.compact.auto_title')}" style="display:inline-flex;align-items:center;gap:5px;font-size:0.78rem;color:var(--text-muted);margin-left:8px;cursor:pointer;">
                    <input type="checkbox" id="kb-compact-auto" style="margin:0;cursor:pointer;" ${cs.auto ? 'checked' : ''}
                           onchange="window.knowledgeManager.setCompactAuto(this)">
                    ${window.t('knowledge.compact.auto_label')}
                </label>
                <span class="kb-learned-sep">·</span>
                <span class="kb-learned-stat">${pending} ${window.t('knowledge.compact.pending')}</span>
                ${lastRun ? `<span class="kb-learned-sep">·</span><span class="kb-learned-months">${lastRun}</span>` : ''}
            </div>
            <div id="kb-compact-status" style="display:none;font-size:0.8rem;margin-top:8px;"></div>
            <div id="kb-export-status" style="display:none;font-size:0.8rem;margin-top:8px;"></div>
            <div id="kb-learned-list" style="display:none;"></div>`;
        }
    }

    // ─── Wissens-Verdichtung ──────────────────────────────────────────

    _compactStatusLine(msg, color) {
        const st = document.getElementById('kb-compact-status');
        if (!st) return;
        st.style.display = 'block';
        st.style.color = color || 'var(--text-muted)';
        st.textContent = msg;
    }

    async compactLearned(btn) {
        if (btn) { btn.disabled = true; btn.textContent = window.t('knowledge.compact.running'); }
        this._compactStatusLine(window.t('knowledge.compact.status_running'), 'var(--warning)');
        try {
            const resp = await fetch('/api/knowledge/compact', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.error) throw new Error(data.error || ('HTTP ' + resp.status));
            if (data.skipped) {
                this._compactStatusLine(window.t('knowledge.compact.nothing'), 'var(--text-muted)');
            } else {
                this._compactStatusLine(
                    window.t('knowledge.compact.done')
                        .replace('{in}', data.files_in)
                        .replace('{out}', data.files_out)
                        .replace('{topics}', (data.topics || []).join(', ')),
                    'var(--success)');
            }
            setTimeout(() => this.fetchStats(), 2500);
        } catch (e) {
            this._compactStatusLine(window.t('knowledge.compact.fail').replace('{msg}', e.message), 'var(--danger)');
            if (btn) { btn.disabled = false; btn.textContent = window.t('knowledge.compact.btn'); }
        }
    }

    async setCompactAuto(cb) {
        try {
            const resp = await fetch('/api/knowledge/compact_config', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || ''),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ auto: !!cb.checked })
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            this._compactStatusLine(cb.checked
                ? window.t('knowledge.compact.auto_on')
                : window.t('knowledge.compact.auto_off'), 'var(--success)');
        } catch (e) {
            cb.checked = !cb.checked;
            this._compactStatusLine(window.t('knowledge.compact.fail').replace('{msg}', e.message), 'var(--danger)');
        }
    }

    showCompactInfo(show) {
        const m = document.getElementById('kb-compact-modal');
        if (m) m.classList.toggle('open', !!show);
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
                          : window.t('knowledge.learned.export_running'), 'var(--warning)');
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
            setStatus(`✓ ${fname} (${sizeKb} KB)`, 'var(--success)');
            setTimeout(() => { if (st) st.style.display = 'none'; }, 6000);
        } catch (e) {
            setStatus('✗ ' + (window.t('knowledge.learned.export_fail') || 'Export fehlgeschlagen') + ': ' + e.message, 'var(--danger)');
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
                            <button class="kb-btn-sm kb-btn-del" onclick="window.knowledgeManager.deleteLearnedFile('${f.path.replace(/'/g,"\\'")}')">×</button>
                        </div>
                    </div>
                    <div class="kb-learned-item-editor" id="${safeId}_editor" style="display:none;"></div>
                </div>`;
            }).join('');
        } catch (e) {
            el.innerHTML = `<div class="kb-files-error">${window.t('common.error')}: ${e.message}</div>`;
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
            editorEl.innerHTML = `<div class="kb-files-error">${window.t('common.error')}: ${e.message}</div>`;
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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

    // Eindeutige, DOM-taugliche ID aus einem (beliebig tiefen) Ordnerpfad.
    _pathId(path) {
        return 'kbn-' + btoa(unescape(encodeURIComponent(path))).replace(/[^a-zA-Z0-9]/g, '');
    }

    _escHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g,
            c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }

    // HTML eines Ordner-Knotens. Wurzeln behalten Bearbeiten/Entfernen; Unterordner
    // bekommen Löschen. Beide erhalten "Unterordner erstellen" (➕).
    _folderNodeHtml(path, exists, isRoot, hasChildren) {
        const id = this._pathId(path);
        const sp = path.replace(/'/g, "\\'");
        const name = isRoot ? path : path.split('/').pop();
        // Symbol richtet sich danach, ob der Ordner Unterordner enthält:
        // 🗂️ = mit Unterordnern, 📁 = ohne, ⚠️ = existiert nicht.
        const icon = exists === false ? '⚠️' : (hasChildren ? '🗂️' : '📁');
        const T = (k, d) => (window.t && window.t(k)) || d;
        const addSub = `<button class="kb-btn-remove kb-btn-addsub" title="${T('knowledge.subfolder_create_title', 'Unterordner erstellen')}"
                onclick="event.stopPropagation();window.knowledgeManager.createSubfolder('${sp}')">➕</button>`;
        const actions = isRoot
            ? `<button class="kb-btn-remove kb-btn-rename" title="${T('knowledge.folder_edit_title', 'Bearbeiten')}"
                    onclick="event.stopPropagation();window.knowledgeManager.editFolder('${sp}')">✏️</button>${addSub}<button class="kb-btn-remove" title="${T('knowledge.folder_remove_title', 'Ordner entfernen')}"
                    onclick="event.stopPropagation();window.knowledgeManager.removeFolder('${sp}')">✕</button>`
            : `${addSub}<button class="kb-btn-remove" title="${T('knowledge.subfolder_remove_title', 'Unterordner löschen')}"
                    onclick="event.stopPropagation();window.knowledgeManager.deleteSubfolder('${sp}')">✕</button>`;
        return `
            <div class="kb-folder-item${isRoot ? '' : ' kb-subfolder-item'}" data-path="${this._escHtml(path)}">
                <div class="kb-folder-header">
                    <button class="kb-folder-toggle" title="${T('knowledge.folder_files_title', 'Dateien anzeigen')}"
                        onclick="window.knowledgeManager.toggleDir('${sp}', '${id}')">
                        <span class="kb-folder-icon">${icon}</span>
                        <span class="kb-folder-path" title="${this._escHtml(path)}">${this._escHtml(name)}</span>
                        <span class="kb-folder-arrow" id="${id}-arr">▶</span>
                    </button>
                    ${actions}
                </div>
                <div class="kb-folder-files" id="${id}-body" style="display:none;"></div>
            </div>`;
    }

    _renderFolders(folders) {
        const el = document.getElementById('kb-folder-list');
        if (!el) return;
        if (!folders || folders.length === 0) {
            el.innerHTML = `<div class="kb-empty">${window.t('knowledge.no_folders')}</div>`;
            return;
        }
        el.innerHTML = folders.map(f => this._folderNodeHtml(f.path, f.exists, true, f.has_children)).join('');
    }

    // Ordner auf-/zuklappen; lädt Unterordner + Dateien per /api/knowledge/browse.
    async toggleDir(path, id) {
        const body = document.getElementById(`${id}-body`);
        const arrow = document.getElementById(`${id}-arr`);
        if (!body) return;
        if (body.style.display !== 'none') {
            body.style.display = 'none';
            if (arrow) arrow.textContent = '▶';
            return;
        }
        body.style.display = 'block';
        if (arrow) arrow.textContent = '▼';
        body.innerHTML = `<div class="kb-files-loading">${window.t('knowledge.loading')}</div>`;
        await this._loadDir(path, id, body);
    }

    // Inhalt eines Ordner-Knotens laden/rendern (Unterordner-Knoten + eigene Dateien).
    async _loadDir(path, id, body) {
        try {
            const resp = await fetch('/api/knowledge/browse?path=' + encodeURIComponent(path), {
                headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') }
            });
            if (!resp.ok) {
                const e = await resp.json().catch(() => ({}));
                throw new Error(e.error || 'HTTP ' + resp.status);
            }
            const data = await resp.json();
            const subs = (data.subfolders || []).map(sf =>
                this._folderNodeHtml(sf.path, true, false, sf.has_children)).join('');
            const files = data.files || [];
            const bar = files.length ? `<div class="kb-bulk-bar hidden" id="${id}-bulk">
                    <button class="btn-secondary kb-bulk-del" type="button">${window.t('knowledge.bulk_delete') || 'Auswahl löschen'} (<span class="kb-bulk-count">0</span>)</button>
                    <button class="btn-secondary kb-bulk-clear" type="button">${window.t('knowledge.bulk_clear') || 'Auswahl aufheben'}</button>
                    <span class="kb-bulk-hint">${window.t('knowledge.bulk_hint') || 'Mehrfachauswahl: Klick oder mit der Maus aufziehen'}</span>
                </div>` : '';
            const rows = files.map(f => this._fileRowHtml(f, path)).join('');
            let inner = '';
            if (subs) inner += `<div class="kb-subfolders">${subs}</div>`;
            if (files.length) inner += `<div class="kb-node-files">${bar}${rows}</div>`;
            if (!inner) inner = `<div class="kb-files-empty">${window.t('knowledge.no_files')}</div>`;
            body.innerHTML = inner;
            // Kopf-Symbol dieses Knotens an die tatsächlichen Unterordner angleichen
            // (deckt Anlegen/Löschen von Unterordnern ab, ohne Voll-Refresh).
            const hdrIcon = body.previousElementSibling
                && body.previousElementSibling.querySelector('.kb-folder-icon');
            if (hdrIcon && hdrIcon.textContent !== '⚠️') {
                hdrIcon.textContent = (data.subfolders && data.subfolders.length) ? '🗂️' : '📁';
            }
            // Auswahl/Vorschau NUR auf die direkten Dateien dieses Knotens binden
            // (verschachtelte Unterordner-Dateien haben eigene Container).
            const nodeFiles = body.querySelector(':scope > .kb-node-files');
            if (nodeFiles) {
                this._setupRowSelection(nodeFiles, '.kb-file-item', (paths) =>
                    this._bulkDeleteFiles(paths, () => this._loadDir(path, id, body)));
                this._bindFilePreview(nodeFiles);
            }
        } catch (e) {
            body.innerHTML = `<div class="kb-files-error">${window.t('common.error')}: ${e.message}</div>`;
        }
    }

    // HTML einer Datei-Zeile innerhalb eines Ordner-Knotens.
    _fileRowHtml(f, dirPath) {
        const esc = (s) => this._escHtml(s);
        const safePath = f.path.replace(/'/g, "\\'");
        const dp = dirPath.replace(/'/g, "\\'");
        const tagBtn = window.KbGroups
            ? `<button class="kb-btn-view-file kb-btn-tag-file" title="${window.t('kbgroups.assign_title') || 'Wissensgruppe bearbeiten'}"
                    onclick="window.knowledgeManager.tagFile(this, '${safePath}')">🔐</button>`
            : '';
        return `
                <div class="kb-file-item" data-path="${esc(f.path)}" id="kb-file-${btoa(unescape(encodeURIComponent(f.path))).replace(/[^a-zA-Z0-9]/g, '')}">
                    <span class="kb-file-icon">${this._fileIcon(f.path)}</span>
                    <span class="kb-file-name" title="${esc(f.path)}">${esc(f.name)}</span>
                    <span class="kb-file-size">${esc(f.size)}</span>
                    ${tagBtn}
                    <button class="kb-btn-delete-file" title="${window.t('knowledge.file_delete_title')}"
                        onclick="window.knowledgeManager.deleteFile('${safePath}', '${dp}')">✕</button>
                </div>`;
    }

    // Unterordner anlegen (physisch, erbt Gruppen der Wurzel – Modell A).
    async createSubfolder(parentPath) {
        const name = (window.prompt(window.t('knowledge.subfolder_prompt') || 'Name des neuen Unterordners:') || '').trim();
        if (!name) return;
        try {
            const resp = await fetch('/api/knowledge/subfolders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') },
                body: JSON.stringify({ parent: parentPath, name })
            });
            const r = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(r.error || 'HTTP ' + resp.status);
            this._showNotification(window.t('knowledge.subfolder_created') || 'Unterordner erstellt', 'success');
            const id = this._pathId(parentPath);
            const bodyEl = document.getElementById(`${id}-body`);
            if (bodyEl && bodyEl.style.display !== 'none') await this._loadDir(parentPath, id, bodyEl);
            else await this.toggleDir(parentPath, id);   // aufklappen + laden
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
        }
    }

    // Unterordner löschen (Index/Gruppen immer, Dateien optional).
    async deleteSubfolder(path) {
        const name = path.split('/').pop();
        if (!confirm((window.t('knowledge.subfolder_delete_confirm') || 'Unterordner „{name}" entfernen? Das darin indizierte Wissen wird entfernt.').replace('{name}', name))) return;
        const withFiles = confirm(window.t('knowledge.subfolder_delete_files') || 'Auch die Dateien auf der Platte löschen?\n\nOK = Ordner + Dateien löschen · Abbrechen = nur aus dem Index entfernen');
        try {
            const resp = await fetch('/api/knowledge/subfolders', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '') },
                body: JSON.stringify({ path, delete_files: withFiles })
            });
            const r = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(r.error || 'HTTP ' + resp.status);
            this._showNotification(window.t('knowledge.subfolder_removed') || 'Unterordner entfernt', 'success');
            const parent = path.split('/').slice(0, -1).join('/');
            const pid = this._pathId(parent);
            const bodyEl = document.getElementById(`${pid}-body`);
            if (bodyEl && bodyEl.style.display !== 'none') await this._loadDir(parent, pid, bodyEl);
            if (window.KbGroups) await this._refreshGroups();
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
        }
    }

    // ─── Mehrfachauswahl (Klick + Maus-Drag/Rubber-Band) – generisch ────
    // container: Listen-Element (position:relative); rowSel: Zeilen-Selektor;
    // onBulk(paths): Aktion fuer die ausgewaehlten data-path-Werte.
    _setupRowSelection(container, rowSel, onBulk) {
        if (!container) return;
        // Bezugspunkt fuer das absolut positionierte Auswahl-Rechteck
        try { if (getComputedStyle(container).position === 'static') container.style.position = 'relative'; } catch (e) {}
        const self = this;
        const items = () => Array.prototype.slice.call(container.querySelectorAll(rowSel));
        const selected = () => Array.prototype.slice.call(container.querySelectorAll(rowSel + '.selected'));
        const bar = container.querySelector('.kb-bulk-bar');
        const updateBar = () => {
            if (!bar) return;
            const n = selected().length;
            bar.classList.toggle('hidden', n === 0);
            const c = bar.querySelector('.kb-bulk-count'); if (c) c.textContent = String(n);
        };
        // Einzelklick schaltet Auswahl um (nicht auf Buttons/Links)
        container.addEventListener('click', (e) => {
            if (e.target.closest('button, a, input')) return;
            const row = e.target.closest(rowSel);
            if (!row || !container.contains(row)) return;
            if (self._dragMoved) return;
            row.classList.toggle('selected');
            updateBar();
        });
        if (bar) {
            const del = bar.querySelector('.kb-bulk-del');
            const clr = bar.querySelector('.kb-bulk-clear');
            if (del) del.addEventListener('click', () => {
                const paths = selected().map(it => it.getAttribute('data-path')).filter(Boolean);
                if (paths.length) onBulk(paths);
            });
            if (clr) clr.addEventListener('click', () => {
                items().forEach(it => it.classList.remove('selected')); updateBar();
            });
        }
        // Maus-Drag: Auswahl-Rechteck. Start nur auf leerer Flaeche (nicht Buttons).
        let sx = 0, sy = 0, rubber = null, additive = false;
        const onDown = (e) => {
            if (e.button !== 0 || e.target.closest('button, a, input')) return;
            self._dragMoved = false;
            additive = e.ctrlKey || e.metaKey || e.shiftKey;
            const r = container.getBoundingClientRect();
            sx = e.clientX - r.left + container.scrollLeft;
            sy = e.clientY - r.top + container.scrollTop;
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        };
        const onMove = (e) => {
            const r = container.getBoundingClientRect();
            const cx = e.clientX - r.left + container.scrollLeft;
            const cy = e.clientY - r.top + container.scrollTop;
            if (!rubber) {
                if (Math.abs(cx - sx) < 4 && Math.abs(cy - sy) < 4) return;
                self._dragMoved = true;
                container.classList.add('kb-selecting');
                rubber = document.createElement('div'); rubber.className = 'kb-rubber';
                container.appendChild(rubber);
                if (!additive) items().forEach(it => it.classList.remove('selected'));
            }
            const x = Math.min(sx, cx), y = Math.min(sy, cy), w = Math.abs(cx - sx), h = Math.abs(cy - sy);
            rubber.style.left = x + 'px'; rubber.style.top = y + 'px';
            rubber.style.width = w + 'px'; rubber.style.height = h + 'px';
            const cr = container.getBoundingClientRect();
            items().forEach(it => {
                const b = it.getBoundingClientRect();
                const iy1 = b.top - cr.top + container.scrollTop, iy2 = iy1 + b.height;
                const ix1 = b.left - cr.left + container.scrollLeft, ix2 = ix1 + b.width;
                const hit = !(iy2 < y || iy1 > y + h || ix2 < x || ix1 > x + w);
                if (hit) it.classList.add('selected');
                else if (!additive) it.classList.remove('selected');
            });
            updateBar();
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            if (rubber) { rubber.remove(); rubber = null; }
            container.classList.remove('kb-selecting');
            updateBar();
            setTimeout(() => { self._dragMoved = false; }, 0);
        };
        container.addEventListener('mousedown', onDown);
        updateBar();
    }

    // Sammel-Löschen von Dateien (per Pfad); refresh() lädt die Liste neu.
    async _bulkDeleteFiles(paths, refresh) {
        if (!paths || !paths.length) return;
        const msg = (window.t('knowledge.bulk_delete_confirm') || '{n} Dateien wirklich löschen?').replace('{n}', paths.length);
        if (!confirm(msg)) return;
        const token = localStorage.getItem('jarvis_token') || '';
        let ok = 0, fail = 0;
        for (const p of paths) {
            try {
                const r = await fetch('/api/knowledge/files', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ path: p })
                });
                if (r.ok) ok++; else fail++;
            } catch (e) { fail++; }
        }
        this._showNotification(
            (window.t('knowledge.bulk_deleted') || '{n} gelöscht').replace('{n}', ok)
            + (fail ? ' · ' + fail + ' ' + (window.t('knowledge.bulk_failed') || 'fehlgeschlagen') : ''),
            fail ? 'error' : 'success');
        if (refresh) await refresh();
        await this.fetchStats();
    }

    // Sammel-Entfernen aus einer Gruppe (Zuordnung lösen, Datei bleibt bestehen).
    async _bulkRemoveFromGroup(paths, gid) {
        if (!paths || !paths.length || !window.KbGroups) return;
        const msg = (window.t('knowledge.bulk_remove_confirm') || '{n} Dokumente aus der Gruppe entfernen?').replace('{n}', paths.length);
        if (!confirm(msg)) return;
        const KG = window.KbGroups;
        let ok = 0;
        for (const p of paths) {
            try {
                const cur = await KG.getAssignment(p);
                await KG.setAssignment(p, cur.filter(x => x !== gid));
                ok++;
            } catch (e) { /* weiter */ }
        }
        this._showNotification((window.t('knowledge.bulk_removed') || '{n} aus Gruppe entfernt').replace('{n}', ok), 'success');
        await KG.load();
        this._renderGroupsOverview();
        this._showGroupFiles(gid);
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

    async deleteFile(filePath, dirPath) {
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
            // Knoten-Inhalt neu laden (dirPath = Ordner, in dem die Datei lag)
            const id = this._pathId(dirPath);
            const bodyEl = document.getElementById(`${id}-body`);
            if (bodyEl && bodyEl.style.display !== 'none') await this._loadDir(dirPath, id, bodyEl);
            await this.fetchStats();
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
                    <div style="text-align:center;padding:20px;color:var(--text-muted);">${window.t('common.loading')}</div>
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
                body.textContent = data.error || window.t('knowledge.load_failed');
            }
        } catch (e) {
            const body = modal.querySelector('#kb-file-view-body');
            body.style.color = 'var(--error, #f87171)';
            body.textContent = window.t('common.error') + ': ' + e.message;
        }
    }

    // ─── Ordner hinzufügen ────────────────────────────────────────────

    async addFolder() {
        const input = document.getElementById('kb-folder-input');
        if (!input) return;

        const folder = input.value.trim();
        if (!folder) return;

        // Einfacher Name (optional mit fuehrendem data/) -> Ordner ANLEGEN, falls
        // er fehlt, und in die Liste aufnehmen (Create-Endpoint legt data/<name>
        // physisch an; 409 = schon vorhanden = ok). Verhindert das Warndreieck
        // "Ordner existiert nicht" beim Hinzufuegen eines neuen Namens.
        // Echte Pfade (mit / oder absolut) werden wie bisher nur registriert.
        const bareName = folder.replace(/^data\//, '');
        const isSimpleName = !folder.startsWith('/') && !bareName.includes('/') && !bareName.includes('..');
        const token = localStorage.getItem('jarvis_token') || '';
        // Ausgewaehlte Wissensgruppen ("Beim Anlegen als Speicherordner zuordnen")
        // – gilt fuer BEIDE Buttons; das Zuordnen erfolgt nur beim Create-Weg.
        const groupsEl = document.getElementById('kb-folder-groups');
        const groups = window.KbGroups ? window.KbGroups.readChecked(groupsEl) : [];
        try {
            if (isSimpleName) {
                const resp = await fetch('/api/knowledge/folders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ name: bareName, groups })
                });
                const result = await resp.json().catch(() => ({}));
                // 409 = Ordner ist bereits in der Liste -> kein Fehler
                if (!resp.ok && resp.status !== 409) throw new Error(result.error || ('HTTP ' + resp.status));
            } else {
                const resp = await fetch('/api/skills/knowledge/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ folders: await this._buildNewFolderList(folder, 'add') })
                });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
            }
            input.value = '';
            this._showNotification(window.t('knowledge.folder_added'), 'success');
            await this.fetchStats();
            if (window.KbGroups) await this._refreshGroups();
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
        }
    }

    // ─── Ordner neu anlegen (data/<name>, physisch + in der Liste) ────

    async createFolder() {
        const input = document.getElementById('kb-folder-input');
        if (!input) return;

        const name = input.value.trim();
        if (!name) return;

        // Gewaehlte Wissensgruppen: der neue Ordner wird dort direkt als
        // Speicherordner (/wissen-Upload-Ziel) eingetragen
        const groupsEl = document.getElementById('kb-folder-groups');
        const groups = window.KbGroups ? window.KbGroups.readChecked(groupsEl) : [];

        try {
            const resp = await fetch('/api/knowledge/folders', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ name, groups })
            });
            const result = await resp.json();
            if (!resp.ok) throw new Error(result.error || 'HTTP ' + resp.status);

            input.value = '';
            const msg = result.groups_assigned
                ? window.t('knowledge.folder_created_assigned').replace('{n}', result.groups_assigned)
                : window.t('knowledge.folder_created');
            this._showNotification(result.warning ? result.warning : msg,
                result.warning ? 'error' : 'success');
            await this.fetchStats();
            // Gruppen-Uebersicht + Checkboxen aktualisieren (Zuordnung sichtbar, Auswahl leeren)
            if (window.KbGroups) await this._refreshGroups();
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
        }
    }

    // ─── Ordner bearbeiten: Wissensgruppen-Zuordnung + Umbenennen ─────
    // Umbenennen nur fuer direkte data/-Unterordner (nicht der Default-Ordner);
    // die Gruppen-Zuordnung (Speicherordner fuer /wissen) geht fuer JEDEN Ordner.

    async editFolder(folder) {
        const KG = window.KbGroups;
        if (KG) await KG.load();
        const T = (k, d) => (window.t && window.t(k)) || d;
        const esc = KG ? KG.esc : (s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));

        const renameable = folder.startsWith('data/') && !folder.slice(5).includes('/')
            && folder !== 'data/knowledge';
        const curName = folder.replace(/^data\//, '');

        // Aktuelle Zuordnung: Gruppen, die diesen Ordner als Speicherordner fuehren
        const assigned = new Set();
        const groups = KG ? KG.all() : [];
        groups.forEach(g => { if ((g.folders || []).includes(folder)) assigned.add(g.id); });
        const groupRows = groups.length
            ? groups.map(g => `
                <label class="kb-grp-check" style="--grp:${esc(g.color)};">
                    <input type="checkbox" class="kbfld-grp" value="${esc(g.id)}"${assigned.has(g.id) ? ' checked' : ''}>
                    <span>${esc(g.name)}</span>
                </label>`).join('')
            : `<span class="kb-hint" style="margin:0;">${T('kbgroups.none', 'Keine Gruppen angelegt.')}</span>`;

        const nameRow = renameable ? `
            <label class="kb-form-label" style="display:block;margin:12px 0 4px;">${T('knowledge.folder_name_label', 'Ordnername (umbenennen – das indizierte Wissen zieht mit)')}</label>
            <input type="text" id="kbfld-name" class="kb-input" style="width:100%;box-sizing:border-box;" value="${esc(curName)}">` : '';

        document.getElementById('kbfld-edit-modal')?.remove();
        const m = document.createElement('div');
        m.id = 'kbfld-edit-modal';
        m.className = 'modal';
        m.style.zIndex = '10001';
        m.innerHTML = `
            <div class="modal-content glass" style="max-width:560px;">
                <div class="modal-header">
                    <h2>${T('knowledge.folder_edit_title', 'Ordner bearbeiten')} – ${esc(folder)}</h2>
                    <button class="btn-icon" id="kbfld-close" aria-label="Schließen">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                    </button>
                </div>
                <div class="modal-body" style="overflow-y:auto;">
                    ${nameRow}
                    <label class="kb-form-label" style="display:block;margin:16px 0 4px;">${T('kbgroups.folders_label', 'Speicherordner (/wissen)')}</label>
                    <p class="kb-hint" style="margin:0 0 6px;">${T('knowledge.folder_groups_hint',
                        'Wissensgruppen, denen dieser Ordner als Speicherziel angeboten wird. Abwählen entfernt die Zuordnung.')}</p>
                    <div class="kb-grp-checks">${groupRows}</div>
                    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
                        <button type="button" id="kbfld-cancel" class="kb-btn-action">${T('common.cancel', 'Abbrechen')}</button>
                        <button type="button" id="kbfld-save" class="kb-btn-action kb-btn-primary">${T('common.save', 'Speichern')}</button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(m);

        const close = () => m.remove();
        m.querySelector('#kbfld-close').onclick = close;
        m.querySelector('#kbfld-cancel').onclick = close;
        m.addEventListener('click', (e) => { if (e.target === m) close(); });

        m.querySelector('#kbfld-save').onclick = async () => {
            const auth = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
            };
            try {
                // 1) Umbenennen (falls geaendert) – Server relokalisiert Index + Zuordnungen
                let path = folder;
                const nameInp = m.querySelector('#kbfld-name');
                const newName = nameInp ? nameInp.value.trim() : '';
                if (renameable && newName && newName !== curName) {
                    const resp = await fetch('/api/knowledge/folders', {
                        method: 'PUT', headers: auth,
                        body: JSON.stringify({ path: folder, new_name: newName })
                    });
                    const r = await resp.json();
                    if (!resp.ok) throw new Error(r.error || 'HTTP ' + resp.status);
                    path = r.path;
                }
                // 2) Gruppen-Zuordnung setzen (zuordnen UND entfernen)
                if (KG) {
                    const ids = [...m.querySelectorAll('.kbfld-grp:checked')].map(c => c.value);
                    const resp = await fetch('/api/knowledge/folders/groups', {
                        method: 'POST', headers: auth,
                        body: JSON.stringify({ path, groups: ids })
                    });
                    const r = await resp.json();
                    if (!resp.ok) throw new Error(r.error || 'HTTP ' + resp.status);
                }
                this._showNotification(T('knowledge.folder_saved', 'Ordner gespeichert'), 'success');
                close();
                await this.fetchStats();
                if (KG) await this._refreshGroups();
            } catch (e) {
                this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
            }
        };
        requestAnimationFrame(() => m.classList.add('open'));
    }

    async removeFolder(folder) {
        if (!confirm(window.t('knowledge.folder_remove_confirm').replace('{folder}', folder))) return;

        // data/-Unterordner: nachfragen, ob Dateien + Wissen von der Platte sollen
        let deleteFiles = false;
        if (folder.startsWith('data/') && !folder.slice(5).includes('/') && folder !== 'data/knowledge') {
            deleteFiles = confirm(window.t('knowledge.folder_delete_files_confirm').replace('{folder}', folder));
        }

        try {
            const resp = await fetch('/api/knowledge/folders', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || '')
                },
                body: JSON.stringify({ path: folder, delete_files: deleteFiles })
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'HTTP ' + resp.status);
            }
            this._showNotification(window.t('knowledge.folder_removed'), 'success');
            await this.fetchStats();
        } catch (e) {
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
        const GREEN = 'var(--success)', YELLOW = 'var(--warning)', GREY = 'var(--text-secondary)';
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
            this._showNotification(window.t('common.error') + ': ' + e.message, 'error');
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
