/**
 * Jarvis Telemetry Manager – Frontend für Telemetry-Tab
 */

class JarvisTelemetryManager {
    constructor() {
        this._token = () => window.authToken || localStorage.getItem('jarvis_token') || '';
    }

    async init() {
        await this.refresh();
        document.getElementById('btn-tele-refresh')?.addEventListener('click', () => this.refresh());
        document.getElementById('btn-tele-clear')?.addEventListener('click', () => this.clear());
    }

    async refresh() {
        await Promise.all([this._loadStats(), this._loadSpans()]);
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
                    { label: 'Fehler',       value: s.errors,      icon: '❌', danger: s.errors > 0 },
                    { label: 'Gesamtdauer',  value: _fmtDur(s.total_duration_ms), icon: '⏱' },
                ].map(c => `
                    <div style="background:var(--bg-glass);border:1px solid ${c.danger ? 'rgba(239,68,68,0.4)' : 'var(--border)'};border-radius:var(--radius-md);padding:12px 14px;text-align:center;">
                        <div style="font-size:1.4rem;margin-bottom:4px;">${c.icon}</div>
                        <div style="font-size:1.1rem;font-weight:700;color:${c.danger ? '#ef4444' : 'var(--text-primary)'};">${c.value}</div>
                        <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:2px;">${c.label}</div>
                    </div>
                `).join('');
            }

            // Tool-Stats
            const toolBody = document.getElementById('tele-tool-body');
            if (toolBody) {
                const tools = Object.entries(s.tool_stats || {});
                if (tools.length === 0) {
                    toolBody.innerHTML = '<div class="kb-files-empty">Noch keine Tool-Calls aufgezeichnet</div>';
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
                                    <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
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
                    llmBody.innerHTML = '<div class="kb-files-empty">Noch keine LLM-Calls aufgezeichnet</div>';
                } else {
                    llmBody.innerHTML = `
                        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;padding:10px;">
                            ${[
                                ['Calls', l.calls],
                                ['Ø Antwortzeit', _fmtDur(l.avg_ms)],
                                ['Schnellste', _fmtDur(l.min_ms)],
                                ['Langsamste', _fmtDur(l.max_ms)],
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
                body.innerHTML = '<div class="kb-files-empty">Keine Spans vorhanden</div>';
                return;
            }

            const kindColor = { agent: '#818cf8', tool: '#34d399', llm: '#f59e0b', internal: 'var(--text-secondary)' };
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
                                <tr style="border-bottom:1px solid rgba(255,255,255,0.04);" title="${sp.error || ''}">
                                    <td style="padding:5px 8px;font-family:var(--font-mono);color:var(--text-primary);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${sp.name}</td>
                                    <td style="padding:5px 8px;"><span style="font-size:0.7rem;padding:2px 6px;border-radius:99px;background:rgba(255,255,255,0.07);color:${kindColor[sp.kind]||'var(--text-secondary)'};">${sp.kind}</span></td>
                                    <td style="padding:5px 8px;text-align:right;color:${sp.duration_ms>1000?'#f59e0b':'var(--text-primary)'};">${sp.duration_ms}</td>
                                    <td style="padding:5px 8px;color:${sp.status==='error'?'#ef4444':'#34d399'};">${sp.status}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>`;
        } catch (e) {
            if (body) body.innerHTML = `<div class="kb-files-error">Fehler: ${e.message}</div>`;
        }
    }

    async clear() {
        if (!confirm('Alle Telemetry-Daten zurücksetzen?')) return;
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
