/**
 * Jarvis Telemetry Manager – Frontend für Telemetry-Tab
 * Enthält: LLM-Verlauf, Fehler-Log, Aufbewahrungsfrist und den Knopf
 * "Aktualisieren" fuer den ganzen Reiter (seit 2026-10-20 "Protokolle").
 *
 * Stat-Karten, Tool-Stats, LLM-Stats und Spans wurden am 2026-09-28 aus dem
 * Reiter ENTFERNT (Vorgabe des Betreibers). /api/telemetry/stats wird weiter
 * geholt: es traegt den Nachweis "zuletzt geleert", den das Fehler-Log zeigt.
 *
 * Der globale Knopf "Zuruecksetzen" und die Kopfzeile "Zuletzt zurueckgesetzt"
 * sind seit 2026-10-20 ENTFERNT (Vorgabe des Betreibers): der Knopf leerte nur
 * noch unsichtbare Zaehler/Spans und das Fehler-Log, versprach im Reiter
 * "Protokolle" aber, alles zurueckzusetzen. DELETE /api/telemetry bleibt als
 * Schnittstelle bestehen.
 */

class JarvisTelemetryManager {
    constructor() {
        this._token = () => window.authToken || window.JarvisSitzung.token();
        this._convLogInitialized = false;
        // Bereits geladene Konversations-Inhalte (id -> Rumpf). Ein zweites
        // Aufklappen desselben Eintrags soll nicht erneut abrufen.
        this._convBodies = {};
        this._bound = false;
    }

    async init() {
        this._bind();
        await this.refresh();
    }

    /** Ereignisse binden – idempotent, weil init() bei jedem Reiter-Wechsel läuft. */
    _bind() {
        if (this._bound) return;
        this._bound = true;
        document.getElementById('btn-tele-refresh')?.addEventListener('click', () => this.refreshAll());

        const ipSel = document.getElementById('conv-log-ip-filter');
        if (ipSel) ipSel.addEventListener('change', () => this._loadConvLog());

        const userSel = document.getElementById('conv-log-user-filter');
        if (userSel) userSel.addEventListener('change', () => this._loadConvLog());

        const refreshBtn = document.getElementById('conv-log-refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadConvLog());

        const clearBtn = document.getElementById('conv-log-clear-btn');
        if (clearBtn) clearBtn.addEventListener('click', () => this._clearConvLog());

        // Eigener Leeren-Knopf am Fehler-Log.
        this._bindClear('tele-errors-clear-btn', '/api/telemetry/errors', 'telemetry.clear_errors_confirm');

    }

    _bindClear(btnId, url, confirmKey) {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        btn.addEventListener('click', async () => {
            if (!confirm(window.t(confirmKey))) return;
            btn.disabled = true;
            try {
                const res = await fetch(url, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() }
                });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                await this.refresh();
            } catch (e) {
                alert(window.t('telemetry.error_prefix') + ' ' + e.message);
            } finally {
                btn.disabled = false;
            }
        });
    }

    async refresh() {
        // Stats ZUERST: die Bereichs-Hinweise ("zuletzt geleert") stehen darin
        // und werden von _loadErrors mitgerendert.
        await this._loadStats();
        await Promise.all([this._loadErrors(), this._loadRetention()]);
        // LLM-Verlauf nur nachladen wenn Accordion offen
        const body = document.getElementById('tele-convlog-body');
        if (body && body.style.display !== 'none') await this._loadConvLog();
    }

    /** Knopf "Aktualisieren" unten im Reiter: ALLE geoeffneten Abschnitte neu laden.
     *
     * Vorher lud er nur Fehler-Log, Aufbewahrung und LLM-Verlauf – neben den
     * Protokoll-Abschnitten der anderen Module (Tool-Audit, Sicherheit, Journal,
     * SSH …) war das ein Knopf, der "alles" verspricht und die Haelfte laesst.
     * Zugeklappte Abschnitte laden beim Aufklappen ohnehin frisch. */
    async refreshAll() {
        await this.refresh();
        const offen = (id) => {
            const b = document.getElementById(id);
            return !!b && b.style.display !== 'none';
        };
        const auftraege = [];
        if (offen('audit-section-body') && window.auditManager) auftraege.push(window.auditManager.init());
        if (offen('sprot-section-body') && window.sicherheitsProtokoll) auftraege.push(window.sicherheitsProtokoll.init());
        ['journal', 'csp', 'updates', 'ssh', 'fixes', 'abh'].forEach((n) => {
            if (offen('plog-' + n + '-body') && window.Protokolle) auftraege.push(window.Protokolle.init(n));
        });
        await Promise.all(auftraege);
    }

    // ── Aufbewahrungsfrist ────────────────────────────────────────────────────

    async _loadRetention() {
        const txt = document.getElementById('tele-retention-text');
        if (!txt) return;
        try {
            const res = await fetch('/api/logs/retention', {
                headers: { 'Authorization': 'Bearer ' + this._token() }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const r = await res.json();
            const parts = [];
            // Ohne Symbol: das fruehere Kalender-Emoji erschien als unlesbares
            // Zeichen, und icons.js hat keinen Kalender (2026-10-20).
            parts.push(r.days > 0
                ? window.t('telemetry.ret_days').replace('{n}', r.days)
                : window.t('telemetry.ret_forever'));
            const cv = r.conv_log || {};
            if (cv.count) {
                let s = window.t('telemetry.ret_convs').replace('{n}', cv.count);
                if (cv.oldest_ts) s += ' · ' + window.t('telemetry.ret_oldest') + ' '
                    + new Date(cv.oldest_ts * 1000).toLocaleDateString('de-DE');
                if (cv.bytes) s += ' · ' + _fmtBytes(cv.bytes);
                parts.push(s);
            }
            const al = r.audit_log || {};
            if (al.lines) parts.push(window.t('telemetry.ret_audit')
                .replace('{n}', al.lines) + (al.bytes ? ' · ' + _fmtBytes(al.bytes) : ''));
            if (r.last_run_ts) parts.push(window.t('telemetry.ret_last') + ' '
                + new Date(r.last_run_ts * 1000).toLocaleString('de-DE'));
            if (r.error) parts.push('⚠ ' + String(r.error).replace(/</g, '&lt;'));
            txt.innerHTML = parts.join(' · ');
        } catch (e) {
            txt.textContent = '';
        }
    }

    /** Hinweis "zuletzt geleert" unter einem Abschnitt (oder leer). */
    _areaResetHtml(stats, area) {
        const r = (stats.area_resets || {})[area];
        if (!r || !r.ts) return '';
        const when = new Date(r.ts * 1000).toLocaleString('de-DE');
        const who = String(r.by || '?').replace(/</g, '&lt;');
        return `<div style="font-size:0.72rem;color:var(--text-muted);padding:6px 10px;">↺ `
             + window.t('telemetry.area_cleared') + ': ' + when + ' · '
             + window.t('telemetry.by') + ' ' + who + '</div>';
    }

    async _loadStats() {
        try {
            const res = await fetch('/api/telemetry/stats', {
                headers: { 'Authorization': 'Bearer ' + this._token() }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const s = await res.json();

            this._lastStats = s;
        } catch (e) {
            console.error('[Telemetry] Stats-Fehler:', e);
        }
    }

    // ── LLM-Verlauf ───────────────────────────────────────────────────────────

    async _loadConvLog() {
        const body = document.getElementById('tele-convlog-body');
        if (!body) return;
        body.innerHTML = '<div class="kb-loading">' + window.t('telemetry.loading') + '</div>';

        // IPs und Benutzer nachladen
        await Promise.all([this._loadConvLogIps(), this._loadConvLogUsers()]);

        const ip = (document.getElementById('conv-log-ip-filter') || {}).value || '';
        const user = (document.getElementById('conv-log-user-filter') || {}).value || '';
        let url = '/api/conv_log?limit=100';
        if (ip) url += '&ip=' + encodeURIComponent(ip);
        if (user) url += '&user=' + encodeURIComponent(user);
        try {
            const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + this._token() } });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const entries = await res.json();
            // Kopfdaten je Id merken: der Rumpf eines Alt-Eintrags (vor der
            // Umstellung) enthaelt kein task-Feld – dann kommt die Aufgabe aus
            // dem Index. Ohne diesen Rückfall fehlte sie in der aufgeklappten
            // Ansicht genau bei den Eintraegen, bei denen sie ohnehin gekuerzt ist.
            this._convIndex = {};
            entries.forEach(e => { this._convIndex[e.id] = e; });
            if (!entries.length) {
                body.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_convs') + '</div>';
                return;
            }
            body.innerHTML = entries.map(e => this._renderConvEntry(e)).join('');
            // Inhalte werden ERST beim Aufklappen geholt (ein Rumpf kann sehr
            // gross sein – 100 Rümpfe auf einmal wären Megabyte für nichts).
            body.querySelectorAll('.conv-log-header').forEach(hdr => {
                hdr.addEventListener('click', () => {
                    const b = hdr.nextElementSibling;
                    const open = b.style.display === 'block';
                    b.style.display = open ? 'none' : 'block';
                    hdr.querySelector('.conv-log-chevron').textContent = open ? '▶' : '▼';
                    if (!open) this._loadConvBody(hdr.dataset.convId, b);
                });
            });
        } catch (e) {
            body.innerHTML = `<div class="kb-files-error">${window.t('telemetry.error_prefix')} ${e.message}</div>`;
        }
    }

    async _loadConvLogIps() {
        const sel = document.getElementById('conv-log-ip-filter');
        if (!sel) return;
        try {
            const res = await fetch('/api/conv_log/ips', { headers: { 'Authorization': 'Bearer ' + this._token() } });
            if (!res.ok) return;
            const ips = await res.json();
            const cur = sel.value;
            sel.innerHTML = '<option value="">' + window.t('telemetry.all_ips') + '</option>';
            for (const ip of ips) {
                const opt = document.createElement('option');
                opt.value = ip; opt.textContent = ip;
                if (ip === cur) opt.selected = true;
                sel.appendChild(opt);
            }
        } catch (_) {}
    }

    async _loadConvLogUsers() {
        const sel = document.getElementById('conv-log-user-filter');
        if (!sel) return;
        try {
            const res = await fetch('/api/conv_log/users', { headers: { 'Authorization': 'Bearer ' + this._token() } });
            if (!res.ok) return;
            const users = await res.json();
            const cur = sel.value;
            sel.innerHTML = '<option value="">' + window.t('telemetry.all_users') + '</option>';
            for (const u of users) {
                const opt = document.createElement('option');
                opt.value = u; opt.textContent = u;
                if (u === cur) opt.selected = true;
                sel.appendChild(opt);
            }
        } catch (_) {}
    }

    /** Kopfzeile eines Verlaufs-Eintrags. Der Inhalt kommt aus _loadConvBody(). */
    _renderConvEntry(e) {
        const esc = s => String(s == null ? '' : s).replace(/</g, '&lt;');
        const ts  = new Date(e.ts * 1000).toLocaleString('de-DE');
        const dur = _fmtDur(e.duration_ms);
        const errBadge = e.error
            ? `<span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--danger-rgb),0.15);color:var(--danger);border:1px solid rgba(var(--danger-rgb),0.25);">${window.t('telemetry.error_badge')}</span>`
            : '';
        // Alt-Einträge (vor der Umstellung auf vollständige Inhalte) tragen ein
        // Abzeichen: ihre Texte SIND gekürzt und lassen sich nicht mehr
        // vervollständigen. Ohne den Hinweis hielte man sie für vollständig.
        const legacyBadge = e.legacy
            ? `<span title="${window.t('telemetry.legacy_hint')}" style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--warning-rgb),0.15);color:var(--warning);border:1px solid rgba(var(--warning-rgb),0.25);">${window.t('telemetry.legacy_badge')}</span>`
            : '';

        return `<div style="border:1px solid ${e.error ? 'rgba(var(--danger-rgb),0.3)' : 'var(--border)'};border-radius:7px;margin-bottom:5px;overflow:hidden;background:var(--bg-glass);">
  <div class="conv-log-header" data-conv-id="${esc(e.id)}" style="display:flex;align-items:center;gap:7px;padding:7px 11px;cursor:pointer;user-select:none;">
    <span class="conv-log-chevron" style="color:var(--text-muted);font-size:0.68rem;flex-shrink:0;">▶</span>
    <span style="flex:1;font-size:0.83rem;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:300px;">${esc(e.task)}</span>
    <span style="display:flex;align-items:center;gap:5px;flex-shrink:0;flex-wrap:wrap;">
      ${errBadge}
      ${legacyBadge}
      ${e.username ? `<span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--success-rgb),0.18);color:var(--success);border:1px solid rgba(var(--success-rgb),0.25);">👤 ${esc(e.username)}</span>` : ''}
      <span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--accent-rgb),0.18);color:var(--accent-hover);border:1px solid rgba(var(--accent-rgb),0.2);">${esc(e.client_type) || 'browser'}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${esc(e.client_ip)}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${esc(e.model)}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${e.steps} ${window.t('telemetry.steps_abbr')}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${dur}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${ts}</span>
    </span>
  </div>
  <div class="conv-log-body" style="display:none;padding:8px 12px;border-top:1px solid var(--border);">
    ${e.error ? `<div style="font-size:0.81rem;color:var(--danger);margin-bottom:7px;">❌ ${esc(e.error)}</div>` : ''}
    <div class="conv-log-content"><div class="kb-loading">${window.t('telemetry.loading')}</div></div>
  </div>
</div>`;
    }

    /** Holt den vollständigen Inhalt einer Konversation und stellt ihn dar. */
    async _loadConvBody(convId, wrap) {
        const target = wrap?.querySelector('.conv-log-content');
        if (!target || !convId) return;
        if (target.dataset.loaded === '1') return;   // schon geladen
        try {
            let d = this._convBodies[convId];
            if (!d) {
                const res = await fetch('/api/conv_log/' + encodeURIComponent(convId), {
                    headers: { 'Authorization': 'Bearer ' + this._token() }
                });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                d = await res.json();
                this._convBodies[convId] = d;
            }
            target.innerHTML = this._renderConvBody(d, (this._convIndex || {})[convId]);
            target.dataset.loaded = '1';
            target.querySelectorAll('.conv-sys-toggle').forEach(btn => {
                btn.addEventListener('click', () => {
                    const pre = btn.nextElementSibling;
                    const open = pre.style.display !== 'none';
                    pre.style.display = open ? 'none' : 'block';
                    btn.textContent = (open ? '▶ ' : '▼ ') + btn.dataset.label;
                });
            });
        } catch (e) {
            target.innerHTML = `<div class="kb-files-error">${window.t('telemetry.error_prefix')} ${e.message}</div>`;
        }
    }

    _renderConvBody(d, idx) {
        const esc = s => String(s == null ? '' : s).replace(/</g, '&lt;');
        const out = [];

        // Die VOLLSTÄNDIGE Aufgabe. In der Kopfzeile ist sie aus Platzgründen
        // beschnitten dargestellt (CSS-Ellipse) – hier steht sie ganz, denn
        // genau das ist der Zweck der Umstellung. Alt-Einträge haben sie nur
        // im Index, deshalb der Rückfall auf idx.
        const task = d.task || (idx && idx.task) || '';
        const taskCut = !d.task && idx && idx.task_truncated;
        if (task) {
            const lbl = window.t('telemetry.conv_task') + ' · ' + _fmtChars(task.length)
                + (taskCut ? ' · ' + window.t('telemetry.truncated') : '');
            out.push(`<div style="margin-bottom:8px;">
                <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:2px;">${lbl}</div>
                <pre style="margin:0;padding:8px;background:rgba(var(--fg-rgb),0.05);border-radius:6px;font-size:0.78rem;color:var(--text-primary);white-space:pre-wrap;word-break:break-word;font-family:var(--font-mono);max-height:320px;overflow:auto;">${esc(task)}</pre>
            </div>`);
        }

        // System-Prompt: eingeklappt, weil er mehrere zehntausend Zeichen haben
        // kann und sonst jeden Eintrag unlesbar macht.
        if (d.system_prompt) {
            const lbl = window.t('telemetry.conv_sysprompt') + ' · ' + _fmtChars(d.system_prompt.length)
                + (d.system_prompt_truncated ? ' · ' + window.t('telemetry.truncated') : '');
            out.push(`<div style="margin-bottom:8px;">
                <button class="conv-sys-toggle" data-label="${lbl}" style="background:none;border:none;padding:0;cursor:pointer;font-size:0.72rem;color:var(--text-muted);font-family:inherit;">▶ ${lbl}</button>
                <pre style="display:none;margin:4px 0 0;padding:8px;background:rgba(var(--fg-rgb),0.05);border-radius:6px;font-size:0.72rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;max-height:340px;overflow:auto;">${esc(d.system_prompt)}</pre>
            </div>`);
        }

        const msgs = d.messages || [];
        if (!msgs.length) {
            out.push(`<em style="font-size:0.78rem;color:var(--text-muted);">${window.t('telemetry.no_messages')}</em>`);
            return out.join('');
        }
        out.push('<div style="display:flex;flex-direction:column;gap:3px;">' + msgs.map(m => {
            const col = m.role === 'assistant' ? 'rgba(var(--accent-rgb),0.5)'
                      : m.role === 'tool'      ? 'rgba(var(--warning-rgb),0.4)'
                      : 'rgba(var(--success-rgb),0.4)';
            const lbl = m.role === 'tool' ? `🔧 ${esc(m.tool) || 'tool'}`
                      : m.role === 'assistant' ? window.t('telemetry.role_assistant')
                      : '👤 User';
            const txt = esc(m.content || m.preview || '');
            // Gekürzt wird praktisch nie (nur Notbremse bei > 1 MB je Nachricht).
            // Wenn doch, MUSS es dranstehen – samt Originallänge.
            const cut = m.truncated
                ? `<span style="color:var(--warning);font-size:0.7rem;"> [${window.t('telemetry.truncated')}${m.full_len ? ': ' + _fmtChars(m.full_len) : ''}]</span>`
                : '';
            return `<div style="display:flex;gap:8px;font-size:0.78rem;padding:4px 8px;border-radius:5px;background:rgba(var(--fg-rgb),0.03);border-left:2px solid ${col};">
                <span style="flex-shrink:0;color:var(--text-muted);font-size:0.71rem;min-width:88px;">${lbl}</span>
                <span style="color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;max-height:400px;overflow:auto;">${txt}${cut}</span>
            </div>`;
        }).join('') + '</div>');
        return out.join('');
    }

    async _clearConvLog() {
        if (!confirm(window.t('telemetry.clear_convlog_confirm'))) return;
        await fetch('/api/conv_log', { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + this._token() } });
        this._convBodies = {};
        await this._loadConvLog();
        await this._loadRetention();
    }

    // ── Fehler-Log ────────────────────────────────────────────────────────────

    async _loadErrors() {
        const body = document.getElementById('tele-errors-body');
        if (!body || body.style.display === 'none') return;
        try {
            const res = await fetch('/api/telemetry/errors', {
                headers: { 'Authorization': 'Bearer ' + this._token() }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const errors = await res.json();

            if (!errors.length) {
                body.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_errors') + '</div>'
                    + this._areaResetHtml(this._lastStats || {}, 'errors');
                return;
            }
            const esc = s => String(s == null ? '' : s).replace(/</g, '&lt;');
            // Aufklappbare Fehler-Karten: Kopfzeile mit Span/Aufgabe/Meldung/Zeit,
            // Detailbereich mit Fehlertyp, Kontext (Modell, Agent-ID, Schritte)
            // und – falls vorhanden – dem vollstaendigen Traceback.
            body.innerHTML = [...errors].reverse().map(sp => {
                const a = sp.attributes || {};
                const ts = sp.ts ? new Date(sp.ts * 1000).toLocaleString('de-DE') : '';
                const errType = a['error.type'] ? esc(a['error.type']) : '';
                // str(e) ist bei manchen Exceptions leer -> Fallback-Text zeigen
                const errShown = esc(sp.error) || `<span style="opacity:0.55;">${window.t('telemetry.no_error_msg')}</span>`;
                const task = a.task ? esc(a.task) : '';
                const tb = a['error.traceback'] ? esc(a['error.traceback']) : '';
                const rows = [];
                if (task)          rows.push([window.t('telemetry.err_task'),  task]);
                if (a.model)       rows.push([window.t('telemetry.err_model'), esc(a.model)]);
                if (a['agent.id']) rows.push(['Agent-ID', esc(a['agent.id'])]);
                if (a.steps != null) rows.push([window.t('telemetry.steps_abbr'), esc(a.steps)]);
                const detailRows = rows.map(([k, v]) =>
                    `<div style="display:flex;gap:8px;margin-bottom:3px;">
                        <span style="flex-shrink:0;color:var(--text-muted);min-width:88px;">${k}</span>
                        <span style="color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;">${v}</span>
                    </div>`).join('');
                const tbHtml = tb
                    ? `<div style="color:var(--text-muted);margin:8px 0 3px;">${window.t('telemetry.err_trace')}</div>
                       <pre style="margin:0;padding:8px;background:rgba(var(--fg-rgb),0.05);border-radius:6px;font-size:0.72rem;color:var(--text-secondary);overflow-x:auto;white-space:pre;">${tb}</pre>`
                    : '';
                return `<div style="border:1px solid rgba(var(--danger-rgb),0.3);border-radius:7px;margin-bottom:5px;overflow:hidden;background:var(--bg-glass);">
  <div class="conv-log-header" style="display:flex;align-items:center;gap:7px;padding:7px 11px;cursor:pointer;user-select:none;">
    <span class="conv-log-chevron" style="color:var(--text-muted);font-size:0.68rem;flex-shrink:0;">▶</span>
    <span style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-primary);flex-shrink:0;">${esc(sp.name)}</span>
    <span style="flex:1;font-size:0.8rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${task}</span>
    <span style="flex-shrink:0;font-size:0.8rem;color:var(--danger);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px;">${errShown}</span>
    <span style="flex-shrink:0;font-size:0.71rem;color:var(--text-muted);">${sp.duration_ms} ms</span>
    <span style="flex-shrink:0;font-size:0.71rem;color:var(--text-muted);">${ts}</span>
  </div>
  <div style="display:none;padding:9px 12px;border-top:1px solid rgba(var(--fg-rgb),0.06);font-size:0.8rem;">
    <div style="color:var(--danger);margin-bottom:7px;word-break:break-word;">❌ ${errType ? `<strong>${errType}:</strong> ` : ''}${errShown}</div>
    ${detailRows}
    ${tbHtml}
  </div>
</div>`;
            }).join('') + this._areaResetHtml(this._lastStats || {}, 'errors');
            body.querySelectorAll('.conv-log-header').forEach(hdr => {
                hdr.addEventListener('click', () => {
                    const b = hdr.nextElementSibling;
                    const open = b.style.display === 'block';
                    b.style.display = open ? 'none' : 'block';
                    hdr.querySelector('.conv-log-chevron').textContent = open ? '▶' : '▼';
                });
            });
        } catch (e) {
            if (body) body.innerHTML = `<div class="kb-files-error">${window.t('telemetry.error_prefix')} ${e.message}</div>`;
        }
    }
}

function _fmtDur(ms) {
    if (ms === undefined || ms === null) return '–';
    if (ms >= 60000) return (ms / 60000).toFixed(1) + ' min';
    if (ms >= 1000)  return (ms / 1000).toFixed(1) + ' s';
    return ms + ' ms';
}

function _fmtBytes(n) {
    if (!n) return '0 B';
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024)    return (n / 1024).toFixed(0) + ' KB';
    return n + ' B';
}

function _fmtChars(n) {
    if (n === undefined || n === null) return '';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k ' + window.t('telemetry.chars');
    return n + ' ' + window.t('telemetry.chars');
}

window.telemetryManager = new JarvisTelemetryManager();
