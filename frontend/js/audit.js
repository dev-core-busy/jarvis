/**
 * Jarvis Audit-Log Viewer
 * Zeigt alle Tool-Aufrufe des Agenten (user, tool, dauer, args).
 * Design: kb-container / kb-section System
 */
window.auditManager = new (class JarvisAuditManager {
    constructor() {
        this._initialized = false;
        // Filter, mit dem die ANGEZEIGTE Liste geholt wurde. Der Zaehler nennt ihn,
        // und weicht der Feldinhalt davon ab, sagt die Anzeige das ausdruecklich.
        // Grund (2026-08-05): Chrome trug den Login-Namen per Autofill in das
        // Benutzer-Feld ein, ohne ein Laden auszuloesen. Die Liste war ungefiltert,
        // das Feld sah gefiltert aus – und die Anzeige behauptete nichts dazu.
        // Merkregel im Projekt: eine Anzeige darf keinen Zustand suggerieren,
        // den sie nicht kennt.
        this._applied = null;
    }

    init() {
        if (!this._initialized) {
            this._bindButtons();
            this._initialized = true;
        }
        this._load();
    }

    _bindButtons() {
        const $ = id => document.getElementById(id);
        $('audit-refresh-btn').onclick = () => this._load();
        $('audit-apply-btn').onclick   = () => this._load();
        $('audit-clear-btn').onclick   = () => this._clear();

        // Enter in Filter-Feldern löst Laden aus
        ['audit-filter-user', 'audit-filter-tool'].forEach(id => {
            $(id).addEventListener('keydown', e => { if (e.key === 'Enter') this._load(); });
            // Jede Aenderung am Feld (Tippen, Einfuegen, Autofill mit Ereignis)
            // aktualisiert den Hinweis, dass die Liste noch zum alten Filter gehoert.
            ['input', 'change', 'focus'].forEach(ev =>
                $(id).addEventListener(ev, () => this._renderCount()));
        });
    }

    async _load() {
        const user  = document.getElementById('audit-filter-user')?.value.trim() || '';
        const tool  = document.getElementById('audit-filter-tool')?.value.trim() || '';
        const limit = document.getElementById('audit-limit')?.value || '200';

        const params = new URLSearchParams({ limit });
        if (user) params.set('user', user);
        if (tool) params.set('tool', tool);

        try {
            const r = await fetch(`/api/audit_log?${params}`, { headers: { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') } });
            if (!r.ok) {
                this._notify('Ladefehler: ' + r.status, 'error');
                // Die sichtbare Liste gehoert weiter zum vorherigen Filter – der
                // Hinweis darauf muss trotzdem erneuert werden, sonst steht nach
                // einem Fehlversuch wieder eine Anzeige da, die zum Feldinhalt
                // nicht passt und nichts dazu sagt.
                this._renderCount();
                return;
            }
            const entries = await r.json();
            // Erst NACH erfolgreicher Antwort festhalten: bei einem Fehler gehoert
            // die noch sichtbare Liste weiter zum vorherigen Filter.
            this._applied = { user, tool };
            this._render(entries);
        } catch (e) {
            this._notify('Netzwerkfehler: ' + e.message, 'error');
            this._renderCount();   // s.o.: Anzeige und Feldinhalt nicht auseinanderlaufen lassen
        }
    }

    /** Zeigt Trefferzahl UND den Filter, mit dem die Liste geholt wurde. */
    _renderCount(n) {
        const count = document.getElementById('audit-count');
        if (!count) return;
        if (n !== undefined) count._n = n;
        const anz = count._n || 0;
        const T = (k, f) => (window.t ? window.t(k) : f);
        const a = this._applied;
        let txt = T('telemetry.audit_count', '{n} Einträge').replace(/\{n\}/g, anz);
        if (a) {
            const teile = [];
            if (a.user) teile.push(`${T('telemetry.audit_user_label', 'Benutzer')}: ${a.user}`);
            if (a.tool) teile.push(`${T('telemetry.audit_tool_label', 'Tool')}: ${a.tool}`);
            txt += ' · ' + (teile.length
                ? T('telemetry.audit_filter_on', 'Filter').replace('{f}', teile.join(' · '))
                : T('telemetry.audit_filter_off', 'ohne Filter'));
        }
        count.innerHTML = this._esc(txt);
        // Weicht der Feldinhalt vom angewandten Filter ab, ist die Liste veraltet.
        const jetztU = document.getElementById('audit-filter-user')?.value.trim() || '';
        const jetztT = document.getElementById('audit-filter-tool')?.value.trim() || '';
        if (a && (jetztU !== a.user || jetztT !== a.tool)) {
            count.innerHTML += ` <span style="color:var(--warning,#f39c12);">⚠ ${
                this._esc(T('telemetry.audit_filter_stale', 'Filter geändert – „Anwenden" drücken'))}</span>`;
        }
    }

    _render(entries) {
        const tbody = document.getElementById('audit-tbody');
        if (!tbody) return;

        this._renderCount(entries.length);

        if (!entries.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="audit-empty">${
                this._esc(window.t ? window.t('telemetry.audit_empty') : 'Keine Einträge vorhanden.')}</td></tr>`;
            return;
        }

        tbody.innerHTML = entries.map(e => {
            const ts  = new Date(e.ts * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' });
            const isTask = e.tool === '[task]';
            const dur = isTask ? '—' : (e.duration_ms != null ? `${e.duration_ms} ms` : '—');
            const res = isTask ? '—' : (e.result_len  != null ? `${e.result_len} B`  : '—');
            const args = e.args && Object.keys(e.args).length
                ? Object.entries(e.args)
                    .map(([k, v]) => {
                        const val = typeof v === 'string' ? v.substring(0, 80) + (v.length > 80 ? '…' : '') : JSON.stringify(v).substring(0, 80);
                        return `<span class="audit-arg-key">${this._esc(k)}</span>=<span class="audit-arg-val">${this._esc(val)}</span>`;
                    })
                    .join(' ')
                : '<span style="opacity:.4;">—</span>';

            // Tool-Badge-Farbe nach Kategorie
            const toolClass = this._toolClass(e.tool || '');
            const rowStyle  = isTask ? 'opacity:.7;' : '';

            return `<tr style="${rowStyle}">
                <td class="audit-ts">${ts}</td>
                <td class="audit-user">${this._esc(e.user || '—')}</td>
                <td><span class="audit-tool-badge ${toolClass}">${this._esc(e.tool || '—')}</span></td>
                <td class="audit-dur">${dur}</td>
                <td class="audit-res">${res}</td>
                <td class="audit-args">${args}</td>
            </tr>`;
        }).join('');
    }

    _toolClass(tool) {
        if (tool === '[task]')             return 'audit-tool-task';
        if (tool.startsWith('shell'))      return 'audit-tool-shell';
        if (tool.startsWith('read_file') || tool.startsWith('write_file') || tool.startsWith('list_dir')) return 'audit-tool-fs';
        if (tool.startsWith('screenshot') || tool.startsWith('desktop') || tool.startsWith('wait_for')) return 'audit-tool-desktop';
        if (tool.startsWith('whatsapp') || tool.startsWith('telegram')) return 'audit-tool-msg';
        if (tool.startsWith('memory'))     return 'audit-tool-memory';
        if (tool.startsWith('knowledge') || tool.startsWith('vector')) return 'audit-tool-knowledge';
        if (tool.startsWith('spawn'))      return 'audit-tool-agent';
        return 'audit-tool-other';
    }

    async _clear() {
        if (!confirm('Audit-Log wirklich vollständig löschen?')) return;
        try {
            const r = await fetch('/api/audit_log', { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') } });
            const d = await r.json();
            if (d.ok) {
                this._notify('🗑️ Log gelöscht', 'info');
                this._load();
            } else {
                this._notify('Fehler: ' + (d.error || 'Unbekannt'), 'error');
            }
        } catch (e) {
            this._notify('Netzwerkfehler: ' + e.message, 'error');
        }
    }

    _notify(msg, type = 'success') {
        const el = document.getElementById('audit-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `kb-notification kb-notification-${type}`;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }

    _esc(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
})();
