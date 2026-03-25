/**
 * MCP Settings Manager – Verwaltet MCP-Server im Settings-Modal.
 */
(function () {
    'use strict';

    class JarvisMcpManager {
        constructor() {
            this._servers = [];
            this._initialized = false;
        }

        async refresh() {
            const token = localStorage.getItem('jarvis_token') || '';
            try {
                const resp = await fetch('/api/mcp/servers', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                this._servers = await resp.json();
            } catch (e) {
                console.error('MCP: Fehler beim Laden', e);
                this._servers = [];
            }
            this._render();
        }

        _render() {
            const list = document.getElementById('mcp-server-list');
            if (!list) return;

            if (!this._servers.length) {
                list.innerHTML = `
                    <div class="mcp-empty">
                        <p>Keine MCP-Server konfiguriert.</p>
                        <p class="mcp-hint">MCP-Server erweitern Jarvis um externe Tools – z.B. Dateisystem, Datenbanken, Web-Suche.</p>
                    </div>`;
                return;
            }

            list.innerHTML = this._servers.map(srv => this._renderCard(srv)).join('');
            this._bindEvents();
        }

        _renderCard(srv) {
            const statusDot = srv.connected
                ? '<span class="mcp-dot mcp-dot-on"></span>'
                : '<span class="mcp-dot mcp-dot-off"></span>';
            const statusText = srv.connected
                ? `Verbunden – ${srv.tool_count} Tools`
                : (srv.error ? `Fehler: ${srv.error}` : 'Nicht verbunden');
            const toggleLabel = srv.enabled ? 'Aktiv' : 'Inaktiv';
            const transportBadge = srv.transport === 'stdio' ? '⌨️ stdio' : '🌐 SSE';

            const toolsList = srv.tools && srv.tools.length
                ? `<div class="mcp-tools-list">
                    <details>
                        <summary>${srv.tool_count} Tools</summary>
                        <ul>${srv.tools.map(t =>
                            `<li><strong>${t.name}</strong> – ${t.description || ''}</li>`
                        ).join('')}</ul>
                    </details>
                   </div>`
                : '';

            return `
                <div class="mcp-card" data-id="${srv.id}">
                    <div class="mcp-card-header">
                        <div class="mcp-card-title">
                            ${statusDot}
                            <strong>${srv.name}</strong>
                            <span class="mcp-badge">${transportBadge}</span>
                        </div>
                        <div class="mcp-card-actions">
                            <label class="mcp-toggle">
                                <input type="checkbox" ${srv.enabled ? 'checked' : ''} data-action="toggle" data-id="${srv.id}">
                                <span>${toggleLabel}</span>
                            </label>
                            <button class="mcp-btn-sm" data-action="reconnect" data-id="${srv.id}" title="Neu verbinden">🔄</button>
                            <button class="mcp-btn-sm mcp-btn-danger" data-action="remove" data-id="${srv.id}" title="Entfernen">✕</button>
                        </div>
                    </div>
                    <div class="mcp-card-status">${statusText}</div>
                    ${toolsList}
                </div>`;
        }

        _bindEvents() {
            const list = document.getElementById('mcp-server-list');
            if (!list) return;

            list.querySelectorAll('[data-action="toggle"]').forEach(el => {
                el.addEventListener('change', () => this._toggle(el.dataset.id, el.checked));
            });
            list.querySelectorAll('[data-action="reconnect"]').forEach(el => {
                el.addEventListener('click', () => this._reconnect(el.dataset.id));
            });
            list.querySelectorAll('[data-action="remove"]').forEach(el => {
                el.addEventListener('click', () => this._remove(el.dataset.id));
            });
        }

        showAddForm() {
            const list = document.getElementById('mcp-server-list');
            if (!list) return;

            // Pruefen ob Form schon offen
            if (document.getElementById('mcp-add-form')) return;

            const form = document.createElement('div');
            form.id = 'mcp-add-form';
            form.className = 'mcp-form';
            form.innerHTML = `
                <h4>Neuer MCP-Server</h4>
                <div class="mcp-form-row">
                    <label>Name</label>
                    <input type="text" id="mcp-f-name" placeholder="z.B. filesystem" class="mcp-input">
                </div>
                <div class="mcp-form-row">
                    <label>Transport</label>
                    <select id="mcp-f-transport" class="mcp-input">
                        <option value="stdio">stdio (Subprozess)</option>
                        <option value="sse">SSE (HTTP)</option>
                    </select>
                </div>
                <div id="mcp-f-stdio-fields">
                    <div class="mcp-form-row">
                        <label>Command</label>
                        <input type="text" id="mcp-f-command" placeholder="z.B. npx, python3, node" class="mcp-input">
                    </div>
                    <div class="mcp-form-row">
                        <label>Argumente (je Zeile eins)</label>
                        <textarea id="mcp-f-args" class="mcp-input" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/tmp"></textarea>
                    </div>
                </div>
                <div id="mcp-f-sse-fields" style="display:none;">
                    <div class="mcp-form-row">
                        <label>URL</label>
                        <input type="text" id="mcp-f-url" placeholder="http://localhost:8080/sse" class="mcp-input">
                    </div>
                </div>
                <div class="mcp-form-row">
                    <label>Umgebungsvariablen (KEY=VALUE, je Zeile)</label>
                    <textarea id="mcp-f-env" class="mcp-input" rows="2" placeholder="API_KEY=xxx"></textarea>
                </div>
                <div class="mcp-form-buttons">
                    <button id="mcp-f-save" class="mcp-btn-primary">Hinzufügen</button>
                    <button id="mcp-f-cancel" class="mcp-btn-sm">Abbrechen</button>
                </div>`;

            list.parentNode.insertBefore(form, list);

            // Transport-Wechsel
            form.querySelector('#mcp-f-transport').addEventListener('change', (e) => {
                const isStdio = e.target.value === 'stdio';
                form.querySelector('#mcp-f-stdio-fields').style.display = isStdio ? '' : 'none';
                form.querySelector('#mcp-f-sse-fields').style.display = isStdio ? 'none' : '';
            });

            form.querySelector('#mcp-f-save').addEventListener('click', () => this._addServer());
            form.querySelector('#mcp-f-cancel').addEventListener('click', () => form.remove());
        }

        async _addServer() {
            const name = document.getElementById('mcp-f-name')?.value?.trim();
            const transport = document.getElementById('mcp-f-transport')?.value;
            const command = document.getElementById('mcp-f-command')?.value?.trim();
            const argsText = document.getElementById('mcp-f-args')?.value || '';
            const url = document.getElementById('mcp-f-url')?.value?.trim();
            const envText = document.getElementById('mcp-f-env')?.value || '';

            if (!name) return alert('Name ist Pflicht');

            const args = argsText.split('\n').map(s => s.trim()).filter(Boolean);
            const env = {};
            envText.split('\n').forEach(line => {
                const eq = line.indexOf('=');
                if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
            });

            const data = { name, transport, command, args, url, env, enabled: true };
            const token = localStorage.getItem('jarvis_token') || '';

            try {
                await fetch('/api/mcp/servers', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                document.getElementById('mcp-add-form')?.remove();
                await this.refresh();
            } catch (e) {
                alert('Fehler: ' + e.message);
            }
        }

        async _toggle(id, enabled) {
            const token = localStorage.getItem('jarvis_token') || '';
            await fetch(`/api/mcp/servers/${id}/toggle`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            await this.refresh();
        }

        async _reconnect(id) {
            const token = localStorage.getItem('jarvis_token') || '';
            await fetch(`/api/mcp/servers/${id}/reconnect`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            await this.refresh();
        }

        async _remove(id) {
            if (!confirm('MCP-Server wirklich entfernen?')) return;
            const token = localStorage.getItem('jarvis_token') || '';
            await fetch(`/api/mcp/servers/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            await this.refresh();
        }
    }

    window.mcpManager = new JarvisMcpManager();

    // Add-Button Event
    document.addEventListener('DOMContentLoaded', () => {
        const addBtn = document.getElementById('mcp-add-btn');
        if (addBtn) addBtn.addEventListener('click', () => window.mcpManager.showAddForm());
    });
})();
