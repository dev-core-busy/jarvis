/**
 * Jarvis Skill Manager – Zwei-Listen-UI (Installiert / Mögliche)
 *
 * Layout orientiert an KI-Profile + Wissen:
 *  - "Installierte Skills"  = enabled:true  → profile-card-Stil, Toggle + Config + Info + Entfernen
 *  - "Mögliche Skills"      = enabled:false → durchsuchbare Liste mit Kategorie-Pills
 *  - "OpenClaw Marketplace" = aufklappbare Sektion unterhalb (nur lokales LLM)
 *
 * API:
 *  GET  /api/skills                → { skills: [...] }
 *  POST /api/skills/{name}/enable  → aktivieren
 *  POST /api/skills/{name}/disable → deaktivieren
 *  GET  /api/skills/{name}/config  → { config: {...} }
 *  POST /api/skills/{name}/config  → config speichern
 *  GET  /api/openclaw/llm-check    → { local: bool, provider, reason }
 *  GET  /api/openclaw/workflow-task?description=... → { task: string }
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
        mail:     '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"></rect><polyline points="2,4 12,13 22,4"></polyline></svg>',
        message:  '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>',
    };

    // Große Icons für das Info-Popup (28px)
    const ICON_MAP_LG = {
        terminal: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
        monitor:  '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>',
        folder:   '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>',
        camera:   '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>',
        book:     '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>',
        brain:    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 1.5.5 2.8 1.3 3.8L12 21l6.7-9.7c.8-1 1.3-2.3 1.3-3.8A5.5 5.5 0 0 0 14.5 2 5.5 5.5 0 0 0 12 2.8 5.5 5.5 0 0 0 9.5 2z"></path></svg>',
        globe:    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>',
        puzzle:   '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M19.439 7.85c-.049.322.059.648.289.878l1.568 1.568c.47.47.706 1.087.706 1.704s-.235 1.233-.706 1.704l-1.611 1.611a.98.98 0 0 1-.837.276c-.47-.07-.802-.48-.968-.925a2.501 2.501 0 1 0-3.214 3.214c.446.166.855.497.925.968a.979.979 0 0 1-.276.837l-1.61 1.611a2.404 2.404 0 0 1-1.705.707 2.402 2.402 0 0 1-1.704-.706l-1.568-1.568a1.026 1.026 0 0 0-.877-.29c-.493.074-.84.504-1.02.968a2.5 2.5 0 1 1-3.237-3.237c.464-.18.894-.527.967-1.02a1.026 1.026 0 0 0-.289-.877l-1.568-1.568A2.402 2.402 0 0 1 1.998 12c0-.617.236-1.234.706-1.704L4.315 8.685a.98.98 0 0 1 .837-.276c.47.07.802.48.968.925a2.501 2.501 0 1 0 3.214-3.214c-.446-.166-.855-.497-.925-.968a.979.979 0 0 1 .276-.837l1.61-1.611a2.404 2.404 0 0 1 1.705-.707c.618 0 1.234.236 1.704.706l1.568 1.568c.23.23.556.338.877.29.493-.074.84-.504 1.02-.968a2.5 2.5 0 1 1 3.237 3.237c-.464.18-.894.527-.967 1.02z"></path></svg>',
        mail:     '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="4" width="20" height="16" rx="2"></rect><polyline points="2,4 12,13 22,4"></polyline></svg>',
        message:  '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>',
    };

    const CATEGORY_LABELS = {
        system:        'System',
        automation:    'Automation',
        kommunikation: 'Kommunikation',
        wissen:        'Wissen',
        sonstige:      'Sonstige',
    };

    // Kategorie-Pills Konfiguration
    const CATEGORY_PILLS = [
        { key: 'all',          label: 'Alle' },
        { key: 'system',       label: 'System' },
        { key: 'automation',   label: 'Automation' },
        { key: 'kommunikation',label: 'Kommunikation' },
        { key: 'wissen',       label: 'Wissen' },
        { key: 'sonstige',     label: 'Sonstige' },
    ];

    // SVG-Buttons
    const SVG_CFG  = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.32 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>`;
    const SVG_INFO = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;

    class JarvisSkillManager {
        constructor() {
            this.skills          = [];
            this.searchVal       = '';
            this.categoryFilter  = 'all';
            this._ocCollapsed    = true;   // OpenClaw initial zugeklappt
            this._availCollapsed = true;   // Mögliche Skills initial zugeklappt
            this._instCollapsed  = true;   // Installierte Skills initial zugeklappt
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
            this._renderCategoryPills();
            this._renderAvailable();
            this._renderOpenClawSection();
            this._bindSectionToggles();
        }

        // ── Aufklapp-Logik für Mögliche / Installierte Skills ─────────

        _bindSectionToggles() {
            // Einmalig binden (Flag auf dem Element)
            const bind = (headerId, bodyId, toggleId, getCollapsed, setCollapsed) => {
                const header = document.getElementById(headerId);
                if (!header || header._skBound) return;
                header._skBound = true;
                header.addEventListener('click', () => {
                    setCollapsed(!getCollapsed());
                    const body   = document.getElementById(bodyId);
                    const toggle = document.getElementById(toggleId);
                    if (body)   body.style.display   = getCollapsed() ? 'none' : '';
                    if (toggle) toggle.textContent    = getCollapsed() ? '▶' : '▼';
                });
            };

            bind('sk-available-header', 'sk-available-body', 'sk-available-toggle',
                () => this._availCollapsed,
                (v) => { this._availCollapsed = v; });

            bind('sk-installed-header', 'sk-installed-body', 'sk-installed-toggle',
                () => this._instCollapsed,
                (v) => { this._instCollapsed = v; });
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

            const isOpenClaw = skill.source === 'openclaw';

            const item = document.createElement('div');
            item.className = isOpenClaw ? 'sk-item sk-item-oc' : 'sk-item';
            item.innerHTML = `
                <span class="sk-item-icon">${icon}</span>
                <div class="sk-item-info">
                    <span class="sk-item-name">${skill.name}</span>
                    ${isSystem ? '<span class="sk-badge-sys">System</span>' : ''}
                    ${isOpenClaw ? '<span class="sk-badge-oc">OpenClaw</span>' : ''}
                    <span class="sk-item-cat">${catLabel}</span>
                    <span class="sk-item-tools">${toolCount} Tool${toolCount !== 1 ? 's' : ''}</span>
                    <span class="sk-item-desc">${skill.description || ''}</span>
                </div>
                <div class="sk-item-actions">
                    <button class="sk-btn sk-btn-info" title="Anleitung anzeigen">${SVG_INFO}</button>
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

            // Info
            item.querySelector('.sk-btn-info').addEventListener('click', (e) => {
                e.stopPropagation();
                this._showInfo(skill);
            });
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

        // ── Kategorie-Pills ───────────────────────────────────────────

        _renderCategoryPills() {
            // Bestehenden Container wiederverwenden oder neu erstellen
            let pillsEl = document.getElementById('sk-pills-row');
            if (!pillsEl) {
                const availList = document.getElementById('sk-available-list');
                if (!availList) return;
                pillsEl = document.createElement('div');
                pillsEl.id = 'sk-pills-row';
                pillsEl.className = 'sk-category-pills';
                availList.parentNode.insertBefore(pillsEl, availList);
            }

            pillsEl.innerHTML = CATEGORY_PILLS.map(cat => `
                <button class="sk-cat-pill${this.categoryFilter === cat.key ? ' active' : ''}"
                        data-cat="${cat.key}">${cat.label}</button>
            `).join('');

            pillsEl.querySelectorAll('.sk-cat-pill').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.categoryFilter = btn.dataset.cat;
                    // Aktive Pill direkt umschalten ohne komplettes Re-render
                    pillsEl.querySelectorAll('.sk-cat-pill').forEach(b =>
                        b.classList.toggle('active', b.dataset.cat === this.categoryFilter));
                    this._renderAvailable();
                });
            });
        }

        // ── Mögliche Skills (gefiltert) ───────────────────────────────

        _renderAvailable() {
            const el = document.getElementById('sk-available-list');
            if (!el) return;
            const available = this.skills.filter(s => !s.enabled);

            // Kategorie-Filter anwenden
            let filtered = this.categoryFilter === 'all'
                ? available
                : available.filter(s => (s.category || 'sonstige') === this.categoryFilter);

            // Suchbegriff-Filter
            const q = this.searchVal;
            if (q) {
                filtered = filtered.filter(s =>
                    s.name.toLowerCase().includes(q) ||
                    (s.description || '').toLowerCase().includes(q) ||
                    (s.category || '').toLowerCase().includes(q));
            }

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
                    <button class="sk-btn sk-btn-info" title="Anleitung anzeigen">${SVG_INFO}</button>
                    <button class="sk-btn-add">+ Hinzufügen</button>
                </div>`;

            item.querySelector('.sk-btn-info').addEventListener('click', (e) => {
                e.stopPropagation();
                this._showInfo(skill);
            });
            item.querySelector('.sk-btn-add')
                .addEventListener('click', () => this._activate(dirName));
            return item;
        }

        // ── OpenClaw Marketplace Sektion ──────────────────────────────

        _renderOpenClawSection() {
            // Nach der gesamten "Mögliche Skills"-Sektion einfügen
            let ocEl = document.getElementById('sk-openclaw-section');
            if (!ocEl) {
                const availSection = document.getElementById('sk-available-section');
                if (!availSection) return;
                ocEl = document.createElement('div');
                ocEl.id = 'sk-openclaw-section';
                ocEl.className = 'sk-openclaw-section';
                availSection.parentNode.insertBefore(ocEl, availSection.nextSibling);
            }

            const bodyHTML = this._ocCollapsed ? '' : `
                <div class="sk-openclaw-body">
                    <div id="sk-oc-llm-status" class="sk-openclaw-llm-status sk-openclaw-llm-checking">
                        ⏳ Prüfe LLM-Verbindung…
                    </div>
                    <p class="sk-openclaw-hint">
                        Skills werden gesucht, sicherheitsgeprüft und lokal eingebunden.<br>
                        <small>Nur mit lokalem LLM verfügbar – kein Cloud-Anbieter.</small>
                    </p>
                    <label class="sk-openclaw-label">Welchen Skill suchst du?
                        <small>(leer = populäre Skills anzeigen)</small>
                    </label>
                    <textarea id="sk-oc-description" class="sk-openclaw-textarea"
                        placeholder='z. B. "Skill für Telegram" oder "PDF-Analyse"'
                        rows="2"></textarea>
                    <button id="sk-oc-import-btn" class="sk-openclaw-btn" disabled>
                        🔍 Skill suchen &amp; importieren
                    </button>
                </div>`;

            ocEl.innerHTML = `
                <div class="sk-openclaw-header" id="sk-oc-header">
                    <span class="sk-openclaw-title">🛒 OpenClaw Marketplace</span>
                    <span class="sk-openclaw-toggle">${this._ocCollapsed ? '▶' : '▼'}</span>
                </div>
                ${bodyHTML}`;

            // Header-Klick: aufklappen / zuklappen
            ocEl.querySelector('#sk-oc-header').addEventListener('click', () => {
                this._ocCollapsed = !this._ocCollapsed;
                this._renderOpenClawSection();
                if (!this._ocCollapsed) {
                    this._checkLLM();
                }
            });

            // Import-Button nur wenn aufgeklappt
            if (!this._ocCollapsed) {
                const importBtn = ocEl.querySelector('#sk-oc-import-btn');
                if (importBtn) {
                    importBtn.addEventListener('click', () => {
                        const desc = ocEl.querySelector('#sk-oc-description')?.value || '';
                        this._openClawImport(desc);
                    });
                }
            }
        }

        async _checkLLM() {
            const token    = localStorage.getItem('jarvis_token') || '';
            const statusEl = document.getElementById('sk-oc-llm-status');
            const importBtn = document.getElementById('sk-oc-import-btn');
            if (!statusEl) return;
            try {
                const resp = await fetch('/api/openclaw/llm-check', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                if (data.local) {
                    statusEl.className = 'sk-openclaw-llm-status sk-openclaw-llm-local';
                    statusEl.textContent = '🟢 Lokales LLM aktiv – Import verfügbar';
                    if (importBtn) importBtn.disabled = false;
                } else {
                    statusEl.className = 'sk-openclaw-llm-status sk-openclaw-llm-cloud';
                    statusEl.textContent = '⚠ Cloud-LLM aktiv – nur mit lokalem LLM verfügbar';
                    if (importBtn) importBtn.disabled = true;
                }
            } catch (e) {
                if (statusEl) {
                    statusEl.className = 'sk-openclaw-llm-status sk-openclaw-llm-cloud';
                    statusEl.textContent = '❌ LLM-Check fehlgeschlagen';
                }
            }
        }

        async _openClawImport(descriptionText) {
            const token    = localStorage.getItem('jarvis_token') || '';
            const statusEl = document.getElementById('sk-oc-llm-status');

            // 1. LLM-Check
            try {
                const checkResp = await fetch('/api/openclaw/llm-check', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const checkData = await checkResp.json();
                if (!checkData.local) {
                    if (statusEl) {
                        statusEl.className = 'sk-openclaw-llm-status sk-openclaw-llm-cloud';
                        statusEl.textContent = '⚠ ' + checkData.reason;
                    }
                    return;
                }
            } catch (e) {
                if (statusEl) statusEl.textContent = '❌ LLM-Check fehlgeschlagen';
                return;
            }

            // 2. Workflow-Task zusammenbauen
            let taskText = '';
            try {
                const desc     = encodeURIComponent(descriptionText.trim() || '');
                const taskResp = await fetch(`/api/openclaw/workflow-task?description=${desc}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const taskData = await taskResp.json();
                taskText = taskData.task || '';
            } catch (e) {
                if (statusEl) statusEl.textContent = '❌ Workflow-Task konnte nicht geladen werden';
                return;
            }

            // 3. Import-Modal öffnen (startet Task)
            this._showImportModal(taskText, descriptionText || 'OpenClaw Skill-Import');
        }

        // ── Import-Modal mit Mini-Chat ────────────────────────────────

        _showImportModal(taskText, title) {
            // Ggf. vorhandenes Modal entfernen
            const existing = document.getElementById('sk-import-overlay');
            if (existing) existing.remove();

            const overlay = document.createElement('div');
            overlay.id = 'sk-import-overlay';
            overlay.innerHTML = `
                <div class="sk-import-panel" role="dialog" aria-modal="true">
                    <div class="sk-import-header">
                        <span class="sk-import-title">🛒 OpenClaw Skill Import</span>
                        <button class="sk-import-close" title="Schließen">✕</button>
                    </div>
                    <div class="sk-import-log" id="sk-import-log">
                        <div class="sk-import-msg sk-import-msg-info">
                            🤖 Jarvis startet den OpenClaw Skill-Import…
                        </div>
                    </div>
                    <div class="sk-import-input-row">
                        <textarea id="sk-import-input" class="sk-import-input"
                            placeholder="Antwort eingeben (Enter = Senden, Shift+Enter = Zeilenumbruch)…"
                            rows="2"></textarea>
                        <button id="sk-import-send" class="sk-import-send-btn" title="Senden">➤</button>
                    </div>
                    <div class="sk-import-footer">
                        <button id="sk-import-reload" class="btn-secondary sk-import-footer-btn">
                            📋 Skills neu laden
                        </button>
                        <button id="sk-import-close2" class="btn-secondary sk-import-footer-btn">
                            Schließen
                        </button>
                    </div>
                </div>`;

            document.body.appendChild(overlay);

            // Logging-Helper
            const logEl = overlay.querySelector('#sk-import-log');
            let _streamBuf = null; // Aktiver Streaming-Block

            const addMsg = (html, type = 'agent') => {
                _streamBuf = null; // Streaming-Puffer zurücksetzen
                const msg = document.createElement('div');
                msg.className = `sk-import-msg sk-import-msg-${type}`;
                msg.innerHTML = html;
                logEl.appendChild(msg);
                logEl.scrollTop = logEl.scrollHeight;
                return msg;
            };

            // WS-Listener – horcht auf jarvis-ws-message Events
            const wsListener = (e) => {
                const data = e.detail;
                if (!data) return;

                if (data.type === 'status') {
                    // Status-Nachrichten vom Agenten (Haupt-Kanal für Jarvis-Antworten)
                    const msg = data.message || '';
                    if (!msg.trim()) return;

                    // Tool-Aufrufe und technische Statusmeldungen etwas dezenter darstellen
                    const isTool   = msg.startsWith('🔧') || msg.startsWith('📋');
                    const isSystem = msg.startsWith('🚀') || msg.startsWith('🧠') ||
                                     msg.startsWith('⏸') || msg.startsWith('▶') ||
                                     msg.startsWith('⏹') || msg.startsWith('⚡');

                    const type = isTool ? 'tool' : (isSystem ? 'sys' : 'agent');
                    addMsg(`<span>${msg}</span>`, type);

                } else if (data.type === 'error') {
                    addMsg(`❌ ${data.message || 'Fehler'}`, 'error');
                }
            };
            window.addEventListener('jarvis-ws-message', wsListener);

            // Task an Agenten senden
            if (typeof window.sendJarvisTask === 'function') {
                window.sendJarvisTask(taskText);
            } else {
                addMsg('⚠ WebSocket nicht verbunden – bitte den Jarvis-Chat öffnen und erneut versuchen.', 'error');
            }

            // Follow-up-Nachricht senden
            const inputEl = overlay.querySelector('#sk-import-input');
            const sendFollowup = () => {
                const text = inputEl.value.trim();
                if (!text) return;
                addMsg(`<span>${text}</span>`, 'user');
                inputEl.value = '';
                if (typeof window.sendJarvisTask === 'function') {
                    window.sendJarvisTask(text);
                }
            };
            overlay.querySelector('#sk-import-send').addEventListener('click', sendFollowup);
            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendFollowup(); }
            });

            // Skills neu laden
            overlay.querySelector('#sk-import-reload').addEventListener('click', async () => {
                await this.loadSkills();
                addMsg('📋 Skill-Liste neu geladen.', 'info');
            });

            // Schließen-Logik
            const close = () => {
                window.removeEventListener('jarvis-ws-message', wsListener);
                overlay.remove();
            };
            overlay.querySelector('.sk-import-close').addEventListener('click', close);
            overlay.querySelector('#sk-import-close2').addEventListener('click', close);

            // Escape-Taste
            const onKey = (e) => {
                if (e.key === 'Escape') {
                    close();
                    document.removeEventListener('keydown', onKey);
                }
            };
            document.addEventListener('keydown', onKey);
        }

        // ─── Info-Popup ───────────────────────────────────────────────

        _showInfo(skill) {
            // Doppeltes Öffnen verhindern
            const existing = document.getElementById('sk-info-overlay');
            if (existing) existing.remove();

            const help     = skill.help || {};
            const catLabel = CATEGORY_LABELS[skill.category] || skill.category || '';
            const isSystem = skill.system || false;
            const iconLg   = ICON_MAP_LG[skill.icon] || ICON_MAP_LG.puzzle;
            const tools    = help.tools || (skill.tools || []).map(t => ({ name: t, label: t, desc: '' }));
            const useCases = help.use_cases || [];
            const details  = help.details || skill.description || '';

            // Tools-HTML
            const toolsHTML = tools.length
                ? `<div class="sk-info-section">
                    <div class="sk-info-section-title">Verfügbare Tools (${tools.length})</div>
                    <div class="sk-info-tools">
                        ${tools.map(t => `
                        <div class="sk-info-tool">
                            <code class="sk-info-tool-name">${t.name}</code>
                            ${t.label && t.label !== t.name ? `<span class="sk-info-tool-label">${t.label}</span>` : ''}
                            ${t.desc ? `<p class="sk-info-tool-desc">${t.desc}</p>` : ''}
                        </div>`).join('')}
                    </div>
                </div>`
                : '';

            // Use-Cases-HTML
            const useCasesHTML = useCases.length
                ? `<div class="sk-info-section">
                    <div class="sk-info-section-title">Beispiel-Prompts</div>
                    <ul class="sk-info-use-cases">
                        ${useCases.map(uc => `<li>${uc}</li>`).join('')}
                    </ul>
                </div>`
                : '';

            // Setup-HTML
            const setupHTML = help.setup
                ? `<div class="sk-info-section sk-info-section-setup">
                    <div class="sk-info-section-title">⚙ Einrichtung</div>
                    <p class="sk-info-section-text">${help.setup}</p>
                </div>`
                : '';

            // Notes-HTML
            const notesHTML = help.notes
                ? `<div class="sk-info-section sk-info-section-notes">
                    <div class="sk-info-section-title">ℹ Hinweise</div>
                    <p class="sk-info-section-text">${help.notes}</p>
                </div>`
                : '';

            // Footer
            const footerParts = [];
            if (skill.version) footerParts.push(`v${skill.version}`);
            if (skill.author)  footerParts.push(skill.author);

            const overlay = document.createElement('div');
            overlay.id = 'sk-info-overlay';
            overlay.innerHTML = `
                <div class="sk-info-panel" role="dialog" aria-modal="true">
                    <div class="sk-info-header">
                        <span class="sk-info-icon-lg">${iconLg}</span>
                        <div class="sk-info-title-group">
                            <span class="sk-info-name">${skill.name}</span>
                            <div class="sk-info-badges">
                                ${isSystem ? '<span class="sk-badge-sys">System</span>' : ''}
                                <span class="sk-info-cat">${catLabel}</span>
                            </div>
                        </div>
                        <button class="sk-info-close" title="Schließen">✕</button>
                    </div>
                    <div class="sk-info-body">
                        <p class="sk-info-details">${details}</p>
                        ${toolsHTML}
                        ${useCasesHTML}
                        ${setupHTML}
                        ${notesHTML}
                    </div>
                    ${footerParts.length ? `<div class="sk-info-footer">${footerParts.join(' · ')}</div>` : ''}
                </div>`;

            document.body.appendChild(overlay);

            // Schließen via ×-Button
            overlay.querySelector('.sk-info-close').addEventListener('click', () => overlay.remove());
            // Schließen via Backdrop-Klick
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) overlay.remove();
            });
            // Schließen via Escape
            const onKey = (e) => {
                if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); }
            };
            document.addEventListener('keydown', onKey);
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
                if (typeof window.updateGoogleTabVisibility === 'function') window.updateGoogleTabVisibility();
                if (typeof window.updateVisionTabVisibility === 'function') window.updateVisionTabVisibility();
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
                if (typeof window.updateGoogleTabVisibility === 'function') window.updateGoogleTabVisibility();
                if (typeof window.updateVisionTabVisibility === 'function') window.updateVisionTabVisibility();
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
                // Tab-Sichtbarkeit nach Skill-Änderung aktualisieren
                if (typeof window.updateGoogleTabVisibility === 'function') window.updateGoogleTabVisibility();
                if (typeof window.updateVisionTabVisibility === 'function') window.updateVisionTabVisibility();
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
