/**
 * MCP Settings Manager – Verwaltet MCP-Server im Settings-Modal.
 */
(function () {
    'use strict';

    // Servername, Werkzeugnamen und -beschreibungen stammen aus FREMDEM Code (der
    // MCP-Server liefert sie in `list_tools`). Sie gehen hier in ein innerHTML –
    // ohne Entschaerfung waere die Serverliste eine XSS-Flaeche im Admin-Bereich,
    // wo das Sitzungstoken im localStorage liegt.
    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ⚠ RUECKFALLTEXT, wenn der Schluessel fehlt: `window.t` liefert sonst den
    // NACKTEN SCHLUESSEL ("mcp.cert_check" auf dem Knopf), sobald ein Browser
    // ein aelteres i18n.js im Cache haelt. Der Cache-Buster von i18n.js steht
    // in 19 Seiten mit fremdem Arbeitsstand und wird hier bewusst nicht
    // angefasst – also traegt der Aufruf seinen Text selbst mit.
    const _tt = (k, f) => { const v = window.t(k); return (v && v !== k) ? v : f; };

    class JarvisMcpManager {
        constructor() {
            this._servers = [];
            this._initialized = false;
        }

        async refresh() {
            const token = window.JarvisSitzung.token();
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
                        <p>${window.t('mcp.no_servers')}</p>
                        <p class="mcp-hint">${window.t('mcp.empty_hint')}</p>
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
            // ⚠ DREI ZUSTAENDE, NICHT ZWEI (gemeldet 2026-10-24: "steht
            // weiterhin Nicht verbunden"). Ein ABGESCHALTETER Server wurde nie
            // versucht – ihn als "Nicht verbunden" zu melden behauptet einen
            // fehlgeschlagenen Versuch, den es nicht gab, und schickt den
            // Administrator auf die Suche nach einem Fehler. Der Server sagt
            // jetzt `versucht`, und "kein Versuch" ist eine eigene Stufe
            // (Register: eine Anzeige darf keinen Zustand behaupten, den sie
            // nicht kennt).
            const statusText = srv.connected
                ? window.t('mcp.connected').replace('{n}', srv.tool_count)
                : (srv.error
                    ? window.t('mcp.error').replace('{msg}', _esc(srv.error))
                    : (srv.versucht === false
                        ? window.t('mcp.not_attempted')
                        : window.t('mcp.disconnected')));
            // Eigenes Zertifikat hinterlegt? Die Marke sagt die FORM, nie den
            // Inhalt – und sie sagt ausdruecklich, dass geprueft wird.
            const caMark = srv.ca_cert_art
                ? `<span class="mcp-badge" title="${window.t('mcp.ca_hint')}">${
                    window.t(srv.ca_cert_art === 'pem' ? 'mcp.ca_pem' : 'mcp.ca_pfad')}</span>`
                : '';
            // Zertifikat ansehen gibt es nur, wo es eines gibt. Die Entscheidung
            // trifft der SERVER (`zertifikat_moeglich`) – er kennt Transport und
            // Adresse. Hier das URL-Schema zu pruefen waere eine zweite Quelle
            // fuer dieselbe Frage, und `get_status` gibt die URL gar nicht her.
            const istHttps = srv.zertifikat_moeglich === true;
            const toggleLabel = srv.enabled ? window.t('mcp.active') : window.t('mcp.inactive');
            const transportBadge = srv.transport === 'stdio' ? '⌨️ stdio' : '🌐 SSE';
            const id = _esc(srv.id);
            // Die Freigabe fuer Netzwerk-Benutzer traegt ihre Aussage doppelt (Marke
            // UND Text) – Farbe allein ist keine Information, und "wer darf diesen
            // Server benutzen" sieht man der Zeile sonst nicht an.
            // Isolation nur bei stdio aussagekraeftig; der Server meldet dort
            // null, wo die Frage sich nicht stellt (entfernter Server).
            const sbMark = srv.sandbox === true
                ? `<span class="mcp-badge" title="${window.t('mcp.sandbox_hint')}">${window.t('mcp.sandbox_on')}</span>`
                : (srv.sandbox === false
                    ? `<span class="mcp-badge mcp-badge-warn" title="${window.t('mcp.sandbox_hint')}">${window.t('mcp.sandbox_off')}</span>`
                    : '');
            const netMark = srv.allow_network_users
                ? `<span class="mcp-badge mcp-badge-warn" title="${window.t('mcp.net_users_hint')}">${window.t('mcp.net_users_on')}</span>`
                : `<span class="mcp-badge" title="${window.t('mcp.net_users_hint')}">${window.t('mcp.net_users_off')}</span>`;

            const toolsList = srv.tools && srv.tools.length
                ? `<div class="mcp-tools-list">
                    <details>
                        <summary>${srv.tools.length} Tools</summary>
                        <ul>${srv.tools.map(t =>
                            `<li><strong>${_esc(t.name)}</strong> – ${_esc(t.description || '')}</li>`
                        ).join('')}</ul>
                    </details>
                   </div>`
                : '';

            return `
                <div class="mcp-card" data-id="${id}">
                    <div class="mcp-card-header">
                        <div class="mcp-card-title">
                            ${statusDot}
                            <strong>${_esc(srv.name)}</strong>
                            <span class="mcp-badge">${transportBadge}</span>
                            ${netMark}
                            ${sbMark}
                            ${caMark}
                        </div>
                        <div class="mcp-card-actions">
                            <label class="mcp-toggle">
                                <input type="checkbox" ${srv.enabled ? 'checked' : ''} data-action="toggle" data-id="${id}">
                                <span>${toggleLabel}</span>
                            </label>
                            ${istHttps ? `<button class="mcp-btn-sm mcp-btn-cert" data-action="cert" data-id="${id}">${_tt('mcp.cert_check', 'Zertifikat prüfen')}</button>` : ''}
                            <button class="mcp-btn-sm" data-action="reconnect" data-id="${id}" title="${window.t('mcp.reconnect')}">🔄</button>
                            <button class="mcp-btn-sm mcp-btn-danger" data-action="remove" data-id="${id}" title="${window.t('mcp.remove')}">${JarvisIcons.trash()}</button>
                        </div>
                    </div>
                    <div class="mcp-card-status">${statusText}</div>
                    <div class="mcp-cert" data-cert-for="${id}"></div>
                    <label class="mcp-toggle mcp-net-toggle">
                        <input type="checkbox" ${srv.allow_network_users ? 'checked' : ''} data-action="netusers" data-id="${id}">
                        <span>${window.t('mcp.net_users_label')}</span>
                    </label>
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
            list.querySelectorAll('[data-action="cert"]').forEach(el => {
                el.addEventListener('click', () => this._zertifikat(el.dataset.id));
            });
            list.querySelectorAll('[data-action="remove"]').forEach(el => {
                el.addEventListener('click', () => this._remove(el.dataset.id));
            });
            list.querySelectorAll('[data-action="netusers"]').forEach(el => {
                el.addEventListener('change', () => this._setNetUsers(el.dataset.id, el.checked));
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
                <h4>${window.t('mcp.new_server')}</h4>
                <div class="mcp-form-row">
                    <label>Name</label>
                    <input type="text" id="mcp-f-name" placeholder="${window.t('mcp.name_ph')}" class="mcp-input">
                </div>
                <div class="mcp-form-row">
                    <label>Transport</label>
                    <select id="mcp-f-transport" class="mcp-input">
                        <option value="stdio">${window.t('mcp.transport_stdio')}</option>
                        <option value="streamable_http">${window.t('mcp.transport_shttp')}</option>
                        <option value="sse">${window.t('mcp.transport_sse')}</option>
                    </select>
                </div>
                <div id="mcp-f-stdio-fields">
                    <div class="mcp-form-row">
                        <label>Command</label>
                        <input type="text" id="mcp-f-command" placeholder="${window.t('mcp.command_ph')}" class="mcp-input">
                    </div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.args_label')}</label>
                        <textarea id="mcp-f-args" class="mcp-input" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/tmp"></textarea>
                    </div>
                    <label class="mcp-toggle">
                        <input type="checkbox" id="mcp-f-sandbox" checked>
                        <span>${window.t('mcp.sandbox_label')}</span>
                    </label>
                    <div class="mcp-hint">${window.t('mcp.sandbox_hint')}</div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.sandbox_paths_label')}</label>
                        <textarea id="mcp-f-sandbox-paths" class="mcp-input" rows="2" placeholder="/daten/freigabe"></textarea>
                    </div>
                </div>
                <div id="mcp-f-sse-fields" style="display:none;">
                    <div class="mcp-form-row">
                        <label>URL</label>
                        <input type="text" id="mcp-f-url" placeholder="https://host/mcp" class="mcp-input">
                    </div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.ca_label')}</label>
                        <textarea id="mcp-f-ca" class="mcp-input" rows="3"
                                  placeholder="-----BEGIN CERTIFICATE-----"></textarea>
                    </div>
                    <div class="mcp-form-hint">${window.t('mcp.ca_form_hint')}</div>
                </div>
                <div class="mcp-form-row">
                    <label>${window.t('mcp.env_label')}</label>
                    <textarea id="mcp-f-env" class="mcp-input" rows="2" placeholder="API_KEY=xxx"></textarea>
                </div>
                <div class="mcp-form-buttons">
                    <button id="mcp-f-save" class="mcp-btn-primary">${window.t('mcp.add_btn')}</button>
                    <button id="mcp-f-cancel" class="mcp-btn-sm">${window.t('common.cancel')}</button>
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

            if (!name) return alert(window.t('mcp.name_required'));

            const args = argsText.split('\n').map(s => s.trim()).filter(Boolean);
            const env = {};
            envText.split('\n').forEach(line => {
                const eq = line.indexOf('=');
                if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
            });
            const sandbox = document.getElementById('mcp-f-sandbox')?.checked !== false;
            const sandbox_paths = (document.getElementById('mcp-f-sandbox-paths')?.value || '')
                .split('\n').map(s => s.trim()).filter(Boolean);

            // Eigenes Zertifikat: PEM-Block ODER absoluter Pfad, beides im
            // selben Feld (die Weiche steht im Backend, backend/mcp_tls.py).
            // Zeilenumbrueche bleiben erhalten – ein PEM-Block braucht sie.
            const ca_cert = (document.getElementById('mcp-f-ca')?.value || '').trim();

            const data = { name, transport, command, args, url, env, enabled: true,
                           sandbox, sandbox_paths, ca_cert };
            const token = window.JarvisSitzung.token();

            try {
                await fetch('/api/mcp/servers', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                document.getElementById('mcp-add-form')?.remove();
                await this.refresh();
            } catch (e) {
                alert(window.t('mcp.error').replace('{msg}', e.message));
            }
        }

        async _toggle(id, enabled) {
            const token = window.JarvisSitzung.token();
            await fetch(`/api/mcp/servers/${id}/toggle`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            await this.refresh();
        }

        async _setNetUsers(id, allow) {
            // Beim Einschalten ausdruecklich nachfragen: es geht nicht um Bedienkomfort,
            // sondern darum, dass ab dann JEDER Netzwerk-Benutzer mit den hinterlegten
            // Zugangsdaten dieses Servers arbeiten kann.
            if (allow && !confirm(window.t('mcp.net_users_confirm'))) {
                await this.refresh();   // Kaestchen zuruecksetzen
                return;
            }
            const token = window.JarvisSitzung.token();
            try {
                // NUR dieses Feld senden – der Endpunkt merged, ein voller
                // Formularstand ueberschriebe sonst die Serverdaten.
                const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}`, {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ allow_network_users: allow }),
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            } catch (e) {
                alert(window.t('mcp.error').replace('{msg}', e.message));
            }
            await this.refresh();
        }

        async _reconnect(id) {
            const token = window.JarvisSitzung.token();
            await fetch(`/api/mcp/servers/${id}/reconnect`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            await this.refresh();
        }

        /**
         * Zertifikat ansehen, pruefen – und erst DANACH erlauben.
         *
         * ⚠ DER ABDRUCK IST DIE EIGENTLICHE INFORMATION. Das Zertifikat wird
         * ohne Pruefung abgeholt (anders kommt man an ein unbekanntes nicht
         * heran), also beweist das Ansehen NICHTS: wer auf dem Weg sitzt,
         * zeigt sein eigenes. Sicher wird der Weg erst durch den Menschen, der
         * den SHA-256-Abdruck mit dem vergleicht, den der Server-Betreiber
         * nennt. Deshalb steht der Abdruck gross und zuerst, und der
         * Erlauben-Knopf sagt im Klartext, was er tut.
         *
         * Alle Werte gehen ueber textContent ins DOM – sie kommen von einem
         * fremden Server und sind Daten, keine Auszeichnung.
         */
        async _zertifikat(id) {
            const kasten = document.querySelector(`[data-cert-for="${id}"]`);
            if (!kasten) return;
            const setzen = (el) => { kasten.replaceChildren(el); };
            const zeile = (klasse, text) => {
                const d = document.createElement('div');
                d.className = klasse;
                d.textContent = text;
                return d;
            };
            setzen(zeile('mcp-cert-wait', window.t('mcp.cert_loading')));

            let d;
            try {
                const token = window.JarvisSitzung.token();
                const r = await fetch(`/api/mcp/servers/${id}/zertifikat`, {
                    headers: { 'Authorization': `Bearer ${token}` },
                });
                d = await r.json();
                if (!r.ok || !d || d.ok === false) {
                    // ⚠ Ein Fehler verschwindet NICHT von selbst – man muss ihn
                    // lesen und kopieren koennen (Register).
                    setzen(zeile('mcp-cert-fehler',
                        (d && d.error) || window.t('mcp.cert_error')));
                    return;
                }
            } catch (e) {
                setzen(zeile('mcp-cert-fehler',
                    window.t('mcp.cert_error') + ' (' + (e && e.message || e) + ')'));
                return;
            }

            const z = d.zertifikat || {};
            const box = document.createElement('div');
            box.className = 'mcp-cert-box';

            // Erst der Abdruck – das ist das, was verglichen werden muss.
            const fp = document.createElement('div');
            fp.className = 'mcp-cert-fp';
            fp.appendChild(zeile('mcp-cert-fp-label', window.t('mcp.cert_fp')));
            const fpWert = zeile('mcp-cert-fp-wert', String(z.fingerprint_sha256 || ''));
            fpWert.title = window.t('mcp.cert_fp_hint');
            fp.appendChild(fpWert);
            box.appendChild(fp);
            box.appendChild(zeile('mcp-cert-hint', window.t('mcp.cert_fp_hint')));

            const dl = document.createElement('dl');
            dl.className = 'mcp-cert-dl';
            [[window.t('mcp.cert_host'), `${z.host || ''}:${z.port || ''}`],
             [window.t('mcp.cert_subject'), z.subject || ''],
             [window.t('mcp.cert_issuer'), z.issuer || ''],
             [window.t('mcp.cert_valid'), `${z.gueltig_von || ''} – ${z.gueltig_bis || ''}`],
             [window.t('mcp.cert_names'), (z.dns_namen || []).join(', ')
                 || window.t('mcp.cert_names_none')],
            ].forEach(([k, v]) => {
                const dt = document.createElement('dt'); dt.textContent = k;
                const dd = document.createElement('dd'); dd.textContent = v;
                dl.append(dt, dd);
            });
            box.appendChild(dl);

            const befunde = z.befunde || [];
            if (z.vertraut_system === true) {
                // Dann ist Hinterlegen UNNOETIG – und das zu sagen verhindert,
                // dass jemand ein Zertifikat festschreibt, das beim naechsten
                // regulaeren Wechsel nicht mehr passt.
                box.appendChild(zeile('mcp-cert-ok', window.t('mcp.cert_trusted')));
            } else if (befunde.length) {
                const ul = document.createElement('ul');
                ul.className = 'mcp-cert-befunde';
                befunde.forEach(b => {
                    const li = document.createElement('li');
                    li.textContent = b;
                    ul.appendChild(li);
                });
                box.appendChild(zeile('mcp-cert-warn', window.t('mcp.cert_findings')));
                box.appendChild(ul);
            }

            // ⚠ Ein Namensbefund (das Zertifikat gilt fuer andere Namen als
            // die eingetragene Adresse) ist nach dem ERLAUBEN kein Hindernis
            // mehr, wenn gepinnt wird – das Zertifikat selbst ist dann die
            // Identitaet. Ohne diesen Satz steht der Befund rot da, und das
            // Erlauben wirkt zwecklos (genau so gemeldet, 2026-10-25).
            if (d.wird_gepinnt === true) {
                box.appendChild(zeile('mcp-cert-hint', _tt('mcp.cert_pinned_hint', 'Dies ist ein selbstsigniertes Server-Zertifikat. Erlaubst du es, vertraut die Verbindung genau diesem einen Zertifikat (über seinen Schlüssel) – dann wird der Name nicht mehr verglichen, und ein Namensbefund oben ist kein Hindernis.')));
            }
            if (d.schon_erlaubt === true) {
                box.appendChild(zeile('mcp-cert-ok', window.t('mcp.cert_already')));
            } else if (z.pem) {
                const knopf = document.createElement('button');
                knopf.type = 'button';
                knopf.className = 'mcp-btn-sm';
                knopf.textContent = window.t('mcp.cert_allow');
                knopf.title = window.t('mcp.cert_allow_hint');
                knopf.addEventListener('click', () => this._erlauben(id, z.pem));
                box.appendChild(knopf);
                box.appendChild(zeile('mcp-cert-hint', window.t('mcp.cert_allow_hint')));
            }
            setzen(box);
        }

        /** Das ANGESEHENE Zertifikat hinterlegen – die Pruefung bleibt an. */
        async _erlauben(id, pem) {
            const token = window.JarvisSitzung.token();
            const r = await fetch(`/api/mcp/servers/${id}`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${token}`,
                           'Content-Type': 'application/json' },
                body: JSON.stringify({ ca_cert: pem }),
            });
            const kasten = document.querySelector(`[data-cert-for="${id}"]`);
            if (!r.ok) {
                if (kasten) {
                    const d = document.createElement('div');
                    d.className = 'mcp-cert-fehler';
                    d.textContent = window.t('mcp.cert_save_error');
                    kasten.replaceChildren(d);
                }
                return;
            }
            // Erst hinterlegen, dann neu verbinden: ein Reconnect vor dem
            // Speichern liefe noch gegen die alte Konfiguration.
            await fetch(`/api/mcp/servers/${id}/reconnect`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            await this.refresh();
        }

        async _remove(id) {
            if (!confirm(window.t('mcp.remove_confirm'))) return;
            const token = window.JarvisSitzung.token();
            await fetch(`/api/mcp/servers/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            await this.refresh();
        }
    }

    window.mcpManager = new JarvisMcpManager();

    // Ereignis am Hinzufuegen-Knopf
    document.addEventListener('DOMContentLoaded', () => {
        const addBtn = document.getElementById('mcp-add-btn');
        if (addBtn) addBtn.addEventListener('click', () => window.mcpManager.showAddForm());
    });
})();
