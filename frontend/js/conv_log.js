/**
 * Konversations-Verlauf Tab
 * Zeigt LLM-Konversationen an, filterbar nach Client-IP.
 */

class ConvLogManager {
    constructor() {
        this._container  = document.getElementById('conv-log-list');
        this._ipSelect   = document.getElementById('conv-log-ip-filter');
        this._clearBtn   = document.getElementById('conv-log-clear-btn');
        this._loading    = false;
        this._entries    = [];

        if (this._ipSelect) {
            this._ipSelect.addEventListener('change', () => this.load());
        }
        if (this._clearBtn) {
            this._clearBtn.addEventListener('click', () => this._clear());
        }
    }

    async open() {
        await this._loadIps();
        await this.load();
    }

    async _loadIps() {
        try {
            const r = await fetch('/api/conv_log/ips', {
                headers: { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') }
            });
            if (!r.ok) return;
            const ips = await r.json();
            if (!this._ipSelect) return;
            const cur = this._ipSelect.value;
            this._ipSelect.innerHTML = '<option value="">Alle IPs</option>';
            for (const ip of ips) {
                const opt = document.createElement('option');
                opt.value = ip; opt.textContent = ip;
                if (ip === cur) opt.selected = true;
                this._ipSelect.appendChild(opt);
            }
        } catch (_) {}
    }

    async load() {
        if (!this._container) return;
        this._loading = true;
        const ip = this._ipSelect ? this._ipSelect.value : '';
        const url = '/api/conv_log?limit=100' + (ip ? '&ip=' + encodeURIComponent(ip) : '');
        try {
            const r = await fetch(url, {
                headers: { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') }
            });
            if (!r.ok) { this._showError('Fehler beim Laden'); return; }
            this._entries = await r.json();
            this._render();
        } catch (e) {
            this._showError('Netzwerkfehler: ' + e.message);
        } finally {
            this._loading = false;
        }
    }

    _render() {
        if (!this._container) return;
        if (!this._entries.length) {
            this._container.innerHTML = '<div class="conv-log-empty">Noch keine Konversationen aufgezeichnet.</div>';
            return;
        }
        this._container.innerHTML = this._entries.map(e => this._renderEntry(e)).join('');

        // Accordion toggles
        this._container.querySelectorAll('.conv-log-header').forEach(hdr => {
            hdr.addEventListener('click', () => {
                const body = hdr.nextElementSibling;
                const isOpen = body.style.display === 'block';
                body.style.display = isOpen ? 'none' : 'block';
                hdr.querySelector('.conv-log-chevron').textContent = isOpen ? '▶' : '▼';
            });
        });
    }

    _renderEntry(e) {
        const ts   = new Date(e.ts * 1000).toLocaleString('de-DE');
        const dur  = e.duration_ms < 1000
            ? `${e.duration_ms} ms`
            : `${(e.duration_ms / 1000).toFixed(1)} s`;
        const errorBadge = e.error
            ? `<span class="conv-log-badge conv-log-error">Fehler</span>`
            : '';
        const msgCount = (e.messages || []).length;

        const msgsHtml = (e.messages || []).map(m => {
            const roleClass = m.role === 'assistant' ? 'conv-msg-assistant'
                            : m.role === 'tool'      ? 'conv-msg-tool'
                            : 'conv-msg-user';
            const label = m.role === 'tool' ? `🔧 ${m.tool || 'tool'}` : (m.role === 'assistant' ? '🤖 Assistent' : '👤 User');
            const preview = (m.preview || m.content || '').replace(/</g, '&lt;');
            return `<div class="conv-msg ${roleClass}">
                <span class="conv-msg-label">${label}</span>
                <span class="conv-msg-preview">${preview}</span>
            </div>`;
        }).join('');

        const systemPreview = e.system_prompt_preview
            ? `<div class="conv-log-system-prompt"><strong>System-Prompt (Vorschau):</strong><pre>${e.system_prompt_preview.replace(/</g, '&lt;').substring(0, 300)}…</pre></div>`
            : '';

        return `<div class="conv-log-entry${e.error ? ' conv-log-has-error' : ''}">
  <div class="conv-log-header">
    <span class="conv-log-chevron">▶</span>
    <span class="conv-log-task">${(e.task || '').replace(/</g, '&lt;')}</span>
    <span class="conv-log-meta">
      ${errorBadge}
      <span class="conv-log-badge">${e.client_type || 'browser'}</span>
      <span class="conv-log-ip">${e.client_ip || ''}</span>
      <span class="conv-log-model">${e.model || ''}</span>
      <span class="conv-log-steps">${e.steps} Schritte</span>
      <span class="conv-log-dur">${dur}</span>
      <span class="conv-log-ts">${ts}</span>
    </span>
  </div>
  <div class="conv-log-body" style="display:none">
    ${e.error ? `<div class="conv-log-error-msg">❌ ${e.error.replace(/</g, '&lt;')}</div>` : ''}
    ${systemPreview}
    <div class="conv-log-msgs-label">${msgCount} Nachrichten:</div>
    <div class="conv-log-messages">${msgsHtml || '<em>Keine Nachrichten aufgezeichnet</em>'}</div>
  </div>
</div>`;
    }

    _showError(msg) {
        if (this._container) {
            this._container.innerHTML = `<div class="conv-log-empty" style="color:var(--accent-red)">${msg}</div>`;
        }
    }

    async _clear() {
        if (!confirm('Konversations-Verlauf löschen?')) return;
        await fetch('/api/conv_log', {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') }
        });
        this._entries = [];
        this._render();
        await this._loadIps();
    }
}

window._convLogManager = null;
function initConvLog() {
    if (!window._convLogManager) {
        window._convLogManager = new ConvLogManager();
    }
    window._convLogManager.open();
}
