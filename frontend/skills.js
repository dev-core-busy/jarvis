/**
 * Jarvis Skill Manager – Zwei-Listen-UI (Installiert / Mögliche)
 *
 * Layout orientiert an KI-Profile + Wissen:
 *  - "Installierte Skills"  = enabled:true  → profile-card-Stil, Toggle + Config + Entfernen
 *  - "Mögliche Skills"      = enabled:false → durchsuchbare Liste, [+ Hinzufügen]-Button
 *
 * API:
 *  GET  /api/skills                → { skills: [...] }
 *  POST /api/skills/{name}/enable  → aktivieren
 *  POST /api/skills/{name}/disable → deaktivieren
 *  GET  /api/skills/{name}/config  → { config: {...} }
 *  POST /api/skills/{name}/config  → config speichern
 */
(function () {
    'use strict';

    // ─── Icon-Map ─────────────────────────────────────────────────────
    const ICON_MAP = {
        terminal: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
        monitor:  '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>',
        folder:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>',
        camera:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>',
        book:     '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>',
        brain:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 1.5.5 2.8 1.3 3.8L12 21l6.7-9.7c.8-1 1.3-2.3 1.3-3.8A5.5 5.5 0 0 0 14.5 2 5.5 5.5 0 0 0 12 2.8 5.5 5.5 0 0 0 9.5 2z"></path></svg>',
        globe:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>',
        puzzle:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19.439 7.85c-.049.322.059.648.289.878l1.568 1.568c.47.47.706 1.087.706 1.704s-.235 1.233-.706 1.704l-1.611 1.611a.98.98 0 0 1-.837.276c-.47-.07-.802-.48-.968-.925a2.501 2.501 0 1 0-3.214 3.214c.446.166.855.497.925.968a.979.979 0 0 1-.276.837l-1.61 1.611a2.404 2.404 0 0 1-1.705.707 2.402 2.402 0 0 1-1.704-.706l-1.568-1.568a1.026 1.026 0 0 0-.877-.29c-.493.074-.84.504-1.02.968a2.5 2.5 0 1 1-3.237-3.237c.464-.18.894-.527.967-1.02a1.026 1.026 0 0 0-.289-.877l-1.568-1.568A2.402 2.402 0 0 1 1.998 12c0-.617.236-1.234.706-1.704L4.315 8.685a.98.98 0 0 1 .837-.276c.47.07.802.48.968.925a2.501 2.501 0 1 0 3.214-3.214c-.446-.166-.855-.497-.925-.968a.979.979 0 0 1 .276-.837l1.61-1.611a2.404 2.404 0 0 1 1.705-.707c.618 0 1.234.236 1.704.706l1.568 1.568c.23.23.556.338.877.29.493-.074.84-.504 1.02-.968a2.5 2.5 0 1 1 3.237 3.237c-.464.18-.894.527-.967 1.02z"></path></svg>',
    };

    const CATEGORY_LABELS = {
        system:        'System',
        automation:    'Automation',
        kommunikation: 'Kommunikation',
        wissen:        'Wissen',
        sonstige:      'Sonstige',
    };

    // SVG-Buttons
    const SVG_CFG   = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.32 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>`;

    class JarvisSkillManager {
        constructor() {
            this.skills    = [];
            this.searchVal = '';
        }

        // ─── Init ─────────────────────────────────────────────────────

        async loadSkills() {
            try {
                const token = localStorage.getItem('jarvis_token') || '';
                const resp  = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data  = await resp.json();
                this.skills = (data.skills || []).filter(s => !s.error);
                this._bindSearch();
                this._render();
            } catch (e) {
                console.error('Skills laden fehlgeschlagen:', e);
            }
        }

        _bindSearch() {
            const input = document.getElementById('sk-search');
            if (!input || input._skBound) return;
            input._skBound = true;
            input.addEventListener('input', () => {
                this.searchVal = input.value.toLowerCase().trim();
                this._renderAvailable();
            });
        }

        // ─── Render ───────────────────────────────────────────────────

        _render() {
            this._renderInstalled();
            this._renderAvailable();
        }

        // ── Installierte Skills ───────────────────────────────────────

        _renderInstalled() {
            const el = document.getElementById('sk-installed-list');
            if (!el) return;
            const installed = this.skills.filter(s => s.enabled);
            if (installed.length === 0) {
                el.innerHTML = '<div class="kb-empty">Keine Skills installiert.</div>';
                return;
            }
            el.innerHTML = '';
            installed.forEach(s => el.appendChild(this._mkInstalledItem(s)));
        }

        _mkInstalledItem(skill) {
            const dirName   = skill.dir_name || skill.path?.split('/').pop() || skill.name;
            const icon      = ICON_MAP[skill.icon] || ICON_MAP.puzzle;
            const isSystem  = skill.system || false;
            const hasConfig = skill.config_schema && Object.keys(skill.config_schema).length > 0;
            const catLabel  = CATEGORY_LABELS[skill.category] || skill.category || '';
            const toolCount = (skill.tools || []).length;

            const item = document.createElement('div');
            item.className = 'sk-item';
            item.innerHTML = `
                <span class="sk-item-icon">${icon}</span>
                <div class="sk-item-info">
                    <span class="sk-item-name">${skill.name}</span>
                    ${isSystem ? '<span class="sk-badge-sys">System</span>' : ''}
                    <span class="sk-item-cat">${catLabel}</span>
                    <span class="sk-item-tools">${toolCount} Tool${toolCount !== 1 ? 's' : ''}</span>
                    <span class="sk-item-desc">${skill.description || ''}</span>
                </div>
                <div class="sk-item-actions">
                    ${hasConfig
                        ? `<button class="sk-btn sk-btn-cfg" title="Konfigurieren">${SVG_CFG}</button>`
                        : ''}
                    <label class="skill-toggle" title="${isSystem ? 'System-Skill' : 'An / Aus'}">
                        <input type="checkbox" ${skill.enabled ? 'checked' : ''}>
                        <span class="skill-toggle-slider"></span>
                    </label>
                    ${!isSystem
                        ? `<button class="sk-btn sk-btn-rm" title="Deinstallieren">✕</button>`
                        : ''}
                </div>`;

            // Toggle
            item.querySelector('input[type="checkbox"]').addEventListener('change', (e) => {
                this._toggle(e, dirName, e.target.checked, isSystem);
            });
            // Config
            const cfgBtn = item.querySelector('.sk-btn-cfg');
            if (cfgBtn) cfgBtn.addEventListener('click', () => this._openConfig(dirName));
            // Entfernen
            const rmBtn  = item.querySelector('.sk-btn-rm');
            if (rmBtn)  rmBtn.addEventListener('click',  () => this._deactivate(dirName));

            return item;
        }

        // ── Mögliche Skills (gefiltert) ───────────────────────────────

        _renderAvailable() {
            const el = document.getElementById('sk-available-list');
            if (!el) return;
            const available = this.skills.filter(s => !s.enabled);
            const q = this.searchVal;
            const filtered = q
                ? available.filter(s =>
                    s.name.toLowerCase().includes(q) ||
                    (s.description || '').toLowerCase().includes(q) ||
                    (s.category || '').toLowerCase().includes(q))
                : available;

            if (filtered.length === 0) {
                el.innerHTML = `<div class="kb-empty">${
                    available.length === 0
                        ? 'Alle Skills sind bereits installiert.'
                        : 'Keine Skills gefunden.'
                }</div>`;
                return;
            }
            el.innerHTML = '';
            filtered.forEach(s => el.appendChild(this._mkAvailableItem(s)));
        }

        _mkAvailableItem(skill) {
            const dirName  = skill.dir_name || skill.path?.split('/').pop() || skill.name;
            const icon     = ICON_MAP[skill.icon] || ICON_MAP.puzzle;
            const catLabel = CATEGORY_LABELS[skill.category] || skill.category || '';

            const item = document.createElement('div');
            item.className = 'sk-avail-item';
            item.innerHTML = `
                <span class="sk-item-icon sk-item-icon-dim">${icon}</span>
                <div class="sk-item-info">
                    <span class="sk-item-name">${skill.name}</span>
                    <span class="sk-item-cat">${catLabel}</span>
                    <span class="sk-item-desc">${skill.description || ''}</span>
                </div>
                <div class="sk-item-actions">
                    <button class="sk-btn-add">+ Hinzufügen</button>
                </div>`;

            item.querySelector('.sk-btn-add')
                .addEventListener('click', () => this._activate(dirName));
            return item;
        }

        // ─── Aktionen ─────────────────────────────────────────────────

        async _activate(name) {
            const token = localStorage.getItem('jarvis_token') || '';
            try {
                await fetch(`/api/skills/${name}/enable`, {
                    method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
                });
                this._notify(`"${name}" aktiviert`, 'success');
                await this.loadSkills();
            } catch (e) { this._notify('Fehler: ' + e.message, 'error'); }
        }

        async _deactivate(name) {
            if (!confirm(`Skill "${name}" deinstallieren?`)) return;
            const token = localStorage.getItem('jarvis_token') || '';
            try {
                await fetch(`/api/skills/${name}/disable`, {
                    method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
                });
                this._notify(`"${name}" deinstalliert`, 'success');
                await this.loadSkills();
            } catch (e) { this._notify('Fehler: ' + e.message, 'error'); }
        }

        async _toggle(e, name, enabled, isSystem) {
            if (isSystem && !enabled) {
                if (!confirm(`"${name}" ist ein System-Skill. Wirklich deaktivieren?`)) {
                    e.target.checked = true; return;
                }
            }
            const token    = localStorage.getItem('jarvis_token') || '';
            const endpoint = enabled ? 'enable' : 'disable';
            try {
                await fetch(`/api/skills/${name}/${endpoint}`, {
                    method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
                });
                await this.loadSkills();
            } catch (e) { console.error('Toggle fehlgeschlagen:', e); }
        }

        // ─── Konfiguration ────────────────────────────────────────────

        async _openConfig(name) {
            const token = localStorage.getItem('jarvis_token') || '';
            try {
                const resp  = await fetch(`/api/skills/${name}/config`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data  = await resp.json();
                const skill = this.skills.find(
                    s => (s.dir_name || s.path?.split('/').pop()) === name);
                if (!skill?.config_schema) return;
                this._showConfigDialog(name, skill.config_schema, data.config || {});
            } catch (e) { console.error('Config laden fehlgeschlagen:', e); }
        }

        _showConfigDialog(name, schema, currentConfig) {
            const overlay = document.createElement('div');
            overlay.className = 'skill-config-overlay';
            let formHTML = '';
            for (const [key, def] of Object.entries(schema)) {
                const val   = currentConfig[key] !== undefined ? currentConfig[key] : (def.default || '');
                const label = def.label || key;
                if (def.type === 'boolean') {
                    formHTML += `<div class="form-group"><label class="checkbox-group"><input type="checkbox" name="${key}" ${val ? 'checked' : ''}><span>${label}</span></label></div>`;
                } else if (def.type === 'number') {
                    formHTML += `<div class="form-group"><label>${label}</label><input type="number" name="${key}" value="${val}" class="config-input"></div>`;
                } else {
                    formHTML += `<div class="form-group"><label>${label}</label><input type="text" name="${key}" value="${val}" class="config-input"></div>`;
                }
            }
            overlay.innerHTML = `
                <div class="skill-config-dialog">
                    <h3>Konfiguration: ${name}</h3>
                    <form id="skill-config-form">${formHTML}</form>
                    <div class="modal-actions">
                        <button class="btn-primary" id="btn-save-skill-config">Speichern</button>
                        <button class="btn-secondary" id="btn-cancel-skill-config">Abbrechen</button>
                    </div>
                </div>`;
            document.body.appendChild(overlay);
            overlay.querySelector('#btn-cancel-skill-config').addEventListener('click', () => overlay.remove());
            overlay.querySelector('#btn-save-skill-config').addEventListener('click',  () => this._saveConfig(name, schema, overlay));
        }

        async _saveConfig(name, schema, overlay) {
            const form       = overlay.querySelector('#skill-config-form');
            const configData = {};
            for (const key of Object.keys(schema)) {
                const input = form.querySelector(`[name="${key}"]`);
                if (!input) continue;
                if (schema[key].type === 'boolean')     configData[key] = input.checked;
                else if (schema[key].type === 'number') configData[key] = Number(input.value);
                else                                    configData[key] = input.value;
            }
            const token = localStorage.getItem('jarvis_token') || '';
            try {
                await fetch(`/api/skills/${name}/config`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(configData)
                });
                overlay.remove();
                await this.loadSkills();
            } catch (e) { console.error('Config speichern fehlgeschlagen:', e); }
        }

        // ─── Hilfsmethoden ────────────────────────────────────────────

        _notify(msg, type = 'info') {
            const el = document.getElementById('sk-notification');
            if (!el) return;
            el.textContent = msg;
            el.className = 'kb-notification kb-notification-' + type;
            el.style.display = 'block';
            setTimeout(() => { el.style.display = 'none'; }, 3000);
        }
    }

    window.JarvisSkillManager = JarvisSkillManager;
})();
