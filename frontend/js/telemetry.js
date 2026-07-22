/**
 * Jarvis Telemetry Manager – Frontend für Telemetry-Tab
 * Enthält: Stat-Karten, Tool-Stats, LLM-Stats, LLM-Verlauf, Fehler-Log, Spans
 */

class JarvisTelemetryManager {
    constructor() {
        this._token = () => window.authToken || localStorage.getItem('jarvis_token') || '';
        this._convLogInitialized = false;
    }

    async init() {
        await this.refresh();
        document.getElementById('btn-tele-refresh')?.addEventListener('click', () => this.refresh());
        document.getElementById('btn-tele-clear')?.addEventListener('click', () => this.clear());

        const ipSel = document.getElementById('conv-log-ip-filter');
        if (ipSel) ipSel.addEventListener('change', () => this._loadConvLog());

        const userSel = document.getElementById('conv-log-user-filter');
        if (userSel) userSel.addEventListener('change', () => this._loadConvLog());

        const refreshBtn = document.getElementById('conv-log-refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadConvLog());

        const clearBtn = document.getElementById('conv-log-clear-btn');
        if (clearBtn) clearBtn.addEventListener('click', () => this._clearConvLog());
    }

    async refresh() {
        await Promise.all([this._loadStats(), this._loadSpans(), this._loadErrors()]);
        // LLM-Verlauf nur nachladen wenn Accordion offen
        const body = document.getElementById('tele-convlog-body');
        if (body && body.style.display !== 'none') await this._loadConvLog();
    }

    async _loadStats() {
        try {
            const res = await fetch('/api/telemetry/stats', {
                headers: { 'Authorization': 'Bearer ' + this._token() }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const s = await res.json();

            // Stat-Karten
            const cards = document.getElementById('tele-stat-cards');
            if (cards) {
                cards.innerHTML = [
                    { label: 'Agent-Runs',   value: s.agent_runs,  icon: '🤖' },
                    { label: 'Tool-Calls',   value: s.tool_calls,  icon: '🔧' },
                    { label: 'LLM-Calls',    value: s.llm_calls,   icon: '🧠' },
                    { label: window.t('telemetry.stat_errors'),   value: s.errors,      icon: '❌', danger: s.errors > 0 },
                    { label: window.t('telemetry.stat_duration'), value: _fmtDur(s.total_duration_ms), icon: '⏱' },
                ].map(c => `
                    <div style="background:var(--bg-glass);border:1px solid ${c.danger ? 'rgba(var(--danger-rgb),0.4)' : 'var(--border)'};border-radius:var(--radius-md);padding:12px 14px;text-align:center;">
                        <div style="font-size:1.4rem;margin-bottom:4px;">${c.icon}</div>
                        <div style="font-size:1.1rem;font-weight:700;color:${c.danger ? 'var(--danger)' : 'var(--text-primary)'};">${c.value}</div>
                        <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:2px;">${c.label}</div>
                    </div>
                `).join('');
            }

            // Tool-Stats
            const toolBody = document.getElementById('tele-tool-body');
            if (toolBody) {
                const tools = Object.entries(s.tool_stats || {});
                if (tools.length === 0) {
                    toolBody.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_tool_calls') + '</div>';
                } else {
                    toolBody.innerHTML = `
                        <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
                            <thead>
                                <tr style="color:var(--text-secondary);text-align:left;border-bottom:1px solid var(--border);">
                                    <th style="padding:6px 10px;">Tool</th>
                                    <th style="padding:6px 10px;text-align:right;">Calls</th>
                                    <th style="padding:6px 10px;text-align:right;">Ø ms</th>
                                    <th style="padding:6px 10px;text-align:right;">Min</th>
                                    <th style="padding:6px 10px;text-align:right;">Max</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${tools.sort((a,b) => b[1].calls - a[1].calls).map(([name, t]) => `
                                    <tr style="border-bottom:1px solid rgba(var(--fg-rgb),0.04);">
                                        <td style="padding:6px 10px;color:var(--text-primary);font-family:var(--font-mono);">${name}</td>
                                        <td style="padding:6px 10px;text-align:right;color:var(--accent-hover);">${t.calls}</td>
                                        <td style="padding:6px 10px;text-align:right;">${t.avg_ms}</td>
                                        <td style="padding:6px 10px;text-align:right;color:var(--text-secondary);">${t.min_ms}</td>
                                        <td style="padding:6px 10px;text-align:right;color:var(--text-secondary);">${t.max_ms}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>`;
                }
            }

            // LLM-Stats
            const llmBody = document.getElementById('tele-llm-body');
            if (llmBody) {
                const l = s.llm_stats || {};
                if (!l.calls) {
                    llmBody.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_llm_calls') + '</div>';
                } else {
                    llmBody.innerHTML = `
                        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;padding:10px;">
                            ${[
                                ['Calls', l.calls],
                                [window.t('telemetry.llm_avg_time'), _fmtDur(l.avg_ms)],
                                [window.t('telemetry.llm_fastest'), _fmtDur(l.min_ms)],
                                [window.t('telemetry.llm_slowest'), _fmtDur(l.max_ms)],
                            ].map(([k,v]) => `
                                <div style="background:var(--bg-secondary);border-radius:var(--radius-sm);padding:8px 10px;text-align:center;">
                                    <div style="font-size:0.95rem;font-weight:600;color:var(--text-primary);">${v}</div>
                                    <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:2px;">${k}</div>
                                </div>
                            `).join('')}
                        </div>`;
                }
            }
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
            if (!entries.length) {
                body.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_convs') + '</div>';
                return;
            }
            body.innerHTML = entries.map(e => this._renderConvEntry(e)).join('');
            body.querySelectorAll('.conv-log-header').forEach(hdr => {
                hdr.addEventListener('click', () => {
                    const b = hdr.nextElementSibling;
                    const open = b.style.display === 'block';
                    b.style.display = open ? 'none' : 'block';
                    hdr.querySelector('.conv-log-chevron').textContent = open ? '▶' : '▼';
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

    _renderConvEntry(e) {
        const ts  = new Date(e.ts * 1000).toLocaleString('de-DE');
        const dur = _fmtDur(e.duration_ms);
        const errBadge = e.error
            ? `<span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--danger-rgb),0.15);color:var(--danger);border:1px solid rgba(var(--danger-rgb),0.25);">${window.t('telemetry.error_badge')}</span>`
            : '';
        const msgsHtml = (e.messages || []).map(m => {
            const col = m.role === 'assistant' ? 'rgba(var(--accent-rgb),0.5)'
                      : m.role === 'tool'      ? 'rgba(var(--warning-rgb),0.4)'
                      : 'rgba(var(--success-rgb),0.4)';
            const lbl = m.role === 'tool' ? `🔧 ${m.tool || 'tool'}` : m.role === 'assistant' ? window.t('telemetry.role_assistant') : '👤 User';
            const prev = (m.preview || m.content || '').replace(/</g,'&lt;');
            return `<div style="display:flex;gap:8px;font-size:0.78rem;padding:4px 8px;border-radius:5px;background:rgba(var(--fg-rgb),0.03);border-left:2px solid ${col};">
                <span style="flex-shrink:0;color:var(--text-muted);font-size:0.71rem;min-width:88px;">${lbl}</span>
                <span style="color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;">${prev}</span>
            </div>`;
        }).join('');

        return `<div style="border:1px solid ${e.error ? 'rgba(var(--danger-rgb),0.3)' : 'var(--border)'};border-radius:7px;margin-bottom:5px;overflow:hidden;background:var(--bg-glass);">
  <div class="conv-log-header" style="display:flex;align-items:center;gap:7px;padding:7px 11px;cursor:pointer;user-select:none;">
    <span class="conv-log-chevron" style="color:var(--text-muted);font-size:0.68rem;flex-shrink:0;">▶</span>
    <span style="flex:1;font-size:0.83rem;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:300px;">${(e.task||'').replace(/</g,'&lt;')}</span>
    <span style="display:flex;align-items:center;gap:5px;flex-shrink:0;flex-wrap:wrap;">
      ${errBadge}
      ${e.username ? `<span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--success-rgb),0.18);color:var(--success);border:1px solid rgba(var(--success-rgb),0.25);">👤 ${e.username}</span>` : ''}
      <span style="font-size:0.68rem;padding:1px 5px;border-radius:99px;background:rgba(var(--accent-rgb),0.18);color:var(--accent-hover);border:1px solid rgba(var(--accent-rgb),0.2);">${e.client_type||'browser'}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${e.client_ip||''}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${e.model||''}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${e.steps} ${window.t('telemetry.steps_abbr')}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${dur}</span>
      <span style="font-size:0.71rem;color:var(--text-muted);">${ts}</span>
    </span>
  </div>
  <div style="display:none;padding:8px 12px;border-top:1px solid var(--border);">
    ${e.error ? `<div style="font-size:0.81rem;color:var(--danger);margin-bottom:7px;">❌ ${e.error.replace(/</g,'&lt;')}</div>` : ''}
    <div style="display:flex;flex-direction:column;gap:3px;">${msgsHtml || `<em style="font-size:0.78rem;color:var(--text-muted);">${window.t('telemetry.no_messages')}</em>`}</div>
  </div>
</div>`;
    }

    async _clearConvLog() {
        if (!confirm(window.t('telemetry.clear_convlog_confirm'))) return;
        await fetch('/api/conv_log', { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + this._token() } });
        await this._loadConvLog();
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
                body.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_errors') + '</div>';
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
            }).join('');
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

    // ── Spans ─────────────────────────────────────────────────────────────────

    async _loadSpans() {
        const body = document.getElementById('tele-spans-body');
        if (!body || body.style.display === 'none') return;
        try {
            const res = await fetch('/api/telemetry/spans?limit=50', {
                headers: { 'Authorization': 'Bearer ' + this._token() }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const spans = await res.json();

            if (!spans.length) {
                body.innerHTML = '<div class="kb-files-empty">' + window.t('telemetry.no_spans') + '</div>';
                return;
            }

            const kindColor = { agent: 'var(--accent)', tool: 'var(--success)', llm: 'var(--warning)', internal: 'var(--text-secondary)' };
            body.innerHTML = `
                <div style="font-size:0.8rem;overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;min-width:500px;">
                        <thead>
                            <tr style="color:var(--text-secondary);text-align:left;border-bottom:1px solid var(--border);">
                                <th style="padding:5px 8px;">Name</th>
                                <th style="padding:5px 8px;">Kind</th>
                                <th style="padding:5px 8px;text-align:right;">ms</th>
                                <th style="padding:5px 8px;">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${[...spans].reverse().map(sp => `
                                <tr style="border-bottom:1px solid rgba(var(--fg-rgb),0.04);" title="${(sp.error||'').replace(/"/g,"'")}">
                                    <td style="padding:5px 8px;font-family:var(--font-mono);color:var(--text-primary);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${sp.name}</td>
                                    <td style="padding:5px 8px;"><span style="font-size:0.7rem;padding:2px 6px;border-radius:99px;background:rgba(var(--fg-rgb),0.07);color:${kindColor[sp.kind]||'var(--text-secondary)'};">${sp.kind}</span></td>
                                    <td style="padding:5px 8px;text-align:right;color:${sp.duration_ms>1000?'var(--warning)':'var(--text-primary)'};">${sp.duration_ms}</td>
                                    <td style="padding:5px 8px;color:${sp.status==='error'?'var(--danger)':'var(--success)'};">${sp.status}${sp.error ? ' ⚠' : ''}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>`;
        } catch (e) {
            if (body) body.innerHTML = `<div class="kb-files-error">${window.t('telemetry.error_prefix')} ${e.message}</div>`;
        }
    }

    async clear() {
        if (!confirm(window.t('telemetry.clear_all_confirm'))) return;
        await fetch('/api/telemetry', {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + this._token() }
        });
        await this.refresh();
    }
}

function _fmtDur(ms) {
    if (ms === undefined || ms === null) return '–';
    if (ms >= 60000) return (ms / 60000).toFixed(1) + ' min';
    if (ms >= 1000)  return (ms / 1000).toFixed(1) + ' s';
    return ms + ' ms';
}

window.telemetryManager = new JarvisTelemetryManager();
