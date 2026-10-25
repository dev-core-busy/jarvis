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
            this._offen = new Set();
            try {
                const roh = JSON.parse(localStorage.getItem('jarvis_mcp_offen') || '[]');
                if (Array.isArray(roh)) roh.forEach(x => this._offen.add(String(x)));
            } catch (_) { /* privates Fenster o.ae. – dann eben alles zu */ }
        }

        /** Karte auf-/zuklappen – ohne Neuaufbau (offene Formulare bleiben). */
        _klappen(id, auf) {
            const karte = document.querySelector(`.mcp-card[data-id="${CSS.escape(id)}"]`);
            if (!karte) return;
            const jetztAuf = auf === undefined ? karte.classList.contains('mcp-zu') : auf;
            karte.classList.toggle('mcp-zu', !jetztAuf);
            const knopf = karte.querySelector('[data-action="klapp-knopf"]');
            if (knopf) {
                const txt = jetztAuf ? _tt('mcp.collapse', 'Einklappen') : _tt('mcp.expand', 'Aufklappen');
                knopf.setAttribute('aria-expanded', jetztAuf ? 'true' : 'false');
                knopf.title = txt;
                knopf.setAttribute('aria-label', txt);
            }
            if (jetztAuf) this._offen.add(id); else this._offen.delete(id);
            const fach = karte.querySelector('[data-form-for]');
            if (jetztAuf && fach && !fach.firstChild) this._formLaden(id);
            try { localStorage.setItem('jarvis_mcp_offen', JSON.stringify([...this._offen])); }
            catch (_) { /* nur Bequemlichkeit */ }
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
            // Offene Karten tragen ihr Einstellungsformular (siehe _formLaden).
            this._servers.filter(srv => this._offen.has(srv.id))
                .forEach(srv => this._formLaden(srv.id));
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
            // Freigabe wie bei SAP & Co.: Benutzer/Gruppen, leer = niemand (auch
            // kein Administrator). Die Marke nennt den Stand im TEXT; die Zahlen
            // kommen aus derselben Zusammenfassung wie im Popup.
            const wert = this._freigabeWert(srv);
            const hatFreigabe = srv.freigabe === 'auswahl';
            const netMark = hatFreigabe && window.JarvisFreigabe
                ? `<span class="mcp-badge mcp-badge-warn" title="${_esc(window.t('mcp.net_users_hint'))}">${_esc(_tt('mcp.rights_selected', 'freigegeben für') + ' ' + window.JarvisFreigabe.zusammenfassung(wert))}</span>`
                : `<span class="mcp-badge" title="${_esc(window.t('mcp.net_users_hint'))}">${_esc(_tt('mcp.rights_none', 'niemand freigegeben'))}</span>`;
            // API-Schluessel gibt es nur bei HTTP-Transporten. Angezeigt wird
            // nur, OB einer hinterlegt ist – der Wert verlaesst das Backend nie.
            const istHttp = srv.transport !== 'stdio';
            const keyMark = istHttp && srv.api_key_gesetzt
                ? `<span class="mcp-badge" title="${_esc(_tt('mcp.key_hint', 'Für diesen Server ist ein API-Schlüssel hinterlegt.'))}">${_esc(_tt('mcp.key_set_badge', 'API-Schlüssel'))}</span>`
                : '';

            // Zugeklappt ist die Vorgabe; aufgeklappte Karten merkt sich der
            // Browser (Bequemlichkeit, kein Zustand, der woanders gebraucht wird).
            const offen = this._offen.has(srv.id);
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
                <div class="mcp-card${offen ? '' : ' mcp-zu'}" data-id="${id}">
                    <div class="mcp-card-header" data-action="klapp" data-id="${id}">
                        <div class="mcp-card-title">
                            <button type="button" class="mcp-klapp" data-action="klapp-knopf" data-id="${id}"
                                    aria-expanded="${offen ? 'true' : 'false'}"
                                    title="${_esc(offen ? _tt('mcp.collapse', 'Einklappen') : _tt('mcp.expand', 'Aufklappen'))}"
                                    aria-label="${_esc(offen ? _tt('mcp.collapse', 'Einklappen') : _tt('mcp.expand', 'Aufklappen'))}"><span class="mcp-klapp-pfeil"></span></button>
                            ${statusDot}
                            <strong>${_esc(srv.name)}</strong>
                            <span class="mcp-badge">${transportBadge}</span>
                            ${istHttps ? `<button class="mcp-btn-sm mcp-btn-cert" data-action="cert" data-id="${id}">${_tt('mcp.cert_check', 'Zertifikat prüfen')}</button>` : ''}
                            ${netMark}
                            ${sbMark}
                            ${caMark}
                            ${keyMark}
                        </div>
                        <div class="mcp-card-actions">
                            <label class="mcp-toggle">
                                <input type="checkbox" ${srv.enabled ? 'checked' : ''} data-action="toggle" data-id="${id}">
                                <span>${toggleLabel}</span>
                            </label>
                            <button class="mcp-btn-sm mcp-btn-ico" data-action="rechte" data-id="${id}" title="${_esc(_tt('mcp.rights_manage', 'Berechtigungen verwalten'))}" aria-label="${_esc(_tt('mcp.rights_manage', 'Berechtigungen verwalten'))}">🔐</button>
                            <button class="mcp-btn-sm mcp-btn-ico" data-action="reconnect" data-id="${id}" title="${window.t('mcp.reconnect')}" aria-label="${window.t('mcp.reconnect')}">${JarvisIcons.refresh()}</button>
                            <button class="mcp-btn-sm mcp-btn-danger" data-action="remove" data-id="${id}" title="${window.t('mcp.remove')}">${JarvisIcons.trash()}</button>
                        </div>
                    </div>
                    <div class="mcp-card-status">${statusText}</div>
                    <div class="mcp-card-body">
                        <div class="mcp-cert" data-cert-for="${id}"></div>
                        <div class="mcp-form-fach" data-form-for="${id}"></div>
                        ${toolsList}
                    </div>
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
            list.querySelectorAll('[data-action="rechte"]').forEach(el => {
                el.addEventListener('click', () => this._rechte(el.dataset.id));
            });
            // Klappen: die ganze Kopfzeile und der Pfeil. Bedienelemente IN der
            // Kopfzeile (Zertifikat, Aktiv, Berechtigungen, Loeschen …) duerfen NICHT
            // klappen – Klick-Ausnahme wie im Register gefordert.
            list.querySelectorAll('[data-action="klapp"]').forEach(el => {
                el.addEventListener('click', (e) => {
                    const ziel = e.target.closest('button, input, label, a, select');
                    if (ziel && !ziel.matches('[data-action="klapp-knopf"]')) return;
                    this._klappen(el.dataset.id);
                });
            });
        }

        showAddForm() {
            this._formular(null);
        }

        /**
         * Einstellungen eines Servers IN seine Karte laden (einklappbarer Teil).
         * Laeuft beim Aufklappen und nach jedem Neuaufbau fuer offene Karten.
         * Ein Fehler bleibt im Fach stehen (Register: Fehler verschwinden nicht).
         */
        async _formLaden(id) {
            const fach = document.querySelector(`[data-form-for="${CSS.escape(id)}"]`);
            if (!fach) return;
            fach.replaceChildren();
            try {
                const token = window.JarvisSitzung.token();
                const r = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/konfig`, {
                    headers: { 'Authorization': `Bearer ${token}` },
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                this._formular(await r.json(), fach);
            } catch (e) {
                const d = document.createElement('div');
                d.className = 'mcp-cert-fehler';
                d.textContent = window.t('mcp.error').replace('{msg}', e.message || e);
                fach.replaceChildren(d);
            }
        }

        /**
         * EIN Formular fuer Hinzufuegen (cfg = null, ueber der Liste) und
         * Bearbeiten (cfg = Konfig, IN der Karte – `ziel` ist deren Fach).
         * Felder werden INNERHALB des Formulars adressiert (data-f), nicht ueber
         * feste IDs: mehrere Karten koennen gleichzeitig offen sein.
         *
         * ⚠ GEHEIMNISSE KOMMEN NICHT ZURUECK (GET .../konfig nennt nur Namen bzw.
         * "gesetzt"): beim Bearbeiten heisst ein leeres Feld fuer API-Schluessel,
         * Umgebungsvariablen und PEM-Zertifikat "unveraendert" – und der
         * Platzhalter SAGT das (Register: "leer = unveraendert" ist eine Zusage,
         * keine Dekoration). Entfernen ist jeweils ein ausdrueckliches Kaestchen.
         * Werte aus der Konfiguration gehen ueber .value ins DOM, nie ins Markup.
         */
        _formular(cfg, ziel) {
            const list = document.getElementById('mcp-server-list');
            if (!list) return;
            const neu = !cfg;
            if (neu) document.getElementById('mcp-add-form')?.remove();

            const form = document.createElement('div');
            if (neu) form.id = 'mcp-add-form';
            form.className = neu ? 'mcp-form' : 'mcp-form mcp-form-inline';
            if (!neu) form.dataset.id = cfg.id;
            form.innerHTML = `
                <h4 data-f="titel"></h4>
                <div class="mcp-form-row">
                    <label>Name</label>
                    <input type="text" data-f="name" placeholder="${window.t('mcp.name_ph')}" class="mcp-input">
                </div>
                <div class="mcp-form-row">
                    <label>Transport</label>
                    <select data-f="transport" class="mcp-input">
                        <option value="stdio">${window.t('mcp.transport_stdio')}</option>
                        <option value="streamable_http">${window.t('mcp.transport_shttp')}</option>
                        <option value="sse">${window.t('mcp.transport_sse')}</option>
                    </select>
                </div>
                <div data-f="stdio-fields">
                    <div class="mcp-form-row">
                        <label>Command</label>
                        <input type="text" data-f="command" placeholder="${window.t('mcp.command_ph')}" class="mcp-input">
                    </div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.args_label')}</label>
                        <textarea data-f="args" class="mcp-input" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/tmp"></textarea>
                    </div>
                    <label class="mcp-toggle">
                        <input type="checkbox" data-f="sandbox" checked>
                        <span>${window.t('mcp.sandbox_label')}</span>
                    </label>
                    <div class="mcp-hint">${window.t('mcp.sandbox_hint')}</div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.sandbox_paths_label')}</label>
                        <textarea data-f="sandbox-paths" class="mcp-input" rows="2" placeholder="/daten/freigabe"></textarea>
                    </div>
                </div>
                <div data-f="sse-fields" style="display:none;">
                    <div class="mcp-form-row">
                        <label>URL</label>
                        <input type="text" data-f="url" placeholder="https://host/mcp" class="mcp-input">
                    </div>
                    <div class="mcp-form-row">
                        <label>${_tt('mcp.key_label', 'API-Schlüssel (optional)')}</label>
                        <input type="password" data-f="key" class="mcp-input" autocomplete="new-password">
                    </div>
                    <label class="mcp-toggle" data-f="key-weg-zeile" style="display:none;">
                        <input type="checkbox" data-f="key-weg">
                        <span>${_tt('mcp.key_remove', 'Schlüssel entfernen')}</span>
                    </label>
                    <div class="mcp-form-row">
                        <label>${_tt('mcp.key_header_label', 'Header-Name')}</label>
                        <input type="text" data-f="key-header" class="mcp-input" placeholder="Authorization">
                    </div>
                    <div class="mcp-form-hint">${_esc(_tt('mcp.key_header_hint', 'Leer = „Authorization: Bearer <Schlüssel>“. Erwartet der Server einen eigenen Header (z. B. X-API-Key), hier dessen Namen eintragen.'))}</div>
                    <div class="mcp-form-row">
                        <label>${window.t('mcp.ca_label')}</label>
                        <textarea data-f="ca" class="mcp-input" rows="3"
                                  placeholder="-----BEGIN CERTIFICATE-----"></textarea>
                    </div>
                    <label class="mcp-toggle" data-f="ca-weg-zeile" style="display:none;">
                        <input type="checkbox" data-f="ca-weg">
                        <span>${_tt('mcp.ca_remove', 'Eigenes Zertifikat entfernen')}</span>
                    </label>
                    <div class="mcp-form-hint">${window.t('mcp.ca_form_hint')}</div>
                </div>
                <div class="mcp-form-row">
                    <label>${window.t('mcp.env_label')}</label>
                    <textarea data-f="env" class="mcp-input" rows="2" placeholder="API_KEY=xxx"></textarea>
                </div>
                <div class="mcp-cert-fehler" data-f="fehler" role="alert"></div>
                <div class="mcp-form-buttons">
                    <button data-f="save" class="mcp-btn-primary"></button>
                    <button data-f="cancel" class="mcp-btn-sm">${window.t('common.cancel')}</button>
                </div>`;

            const $ = (sel) => form.querySelector(sel);
            $('[data-f="titel"]').textContent = neu ? window.t('mcp.new_server')
                : _tt('mcp.settings_title', 'Einstellungen');
            $('[data-f="save"]').textContent = neu ? window.t('mcp.add_btn')
                : _tt('mcp.edit_save', 'Speichern und neu verbinden');

            if (!neu) {
                $('[data-f="name"]').value = cfg.name || '';
                // ⚠ DEN GESPEICHERTEN TRANSPORT BEWAHREN (Code-Review 2026-10-25):
                // "http" (erst Streamable HTTP, bei Misserfolg SSE) hat keine eigene
                // Option – frueher wurde daraus hier still 'streamable_http', und das
                // naechste Speichern nahm einem SSE-Server seinen Rueckfall. Ein
                // unbekannter Wert bekommt eine eigene Option statt eines Ersatzes.
                const tr = cfg.transport || 'stdio';
                const sel = $('[data-f="transport"]');
                if (![...sel.options].some(o => o.value === tr)) {
                    const o = document.createElement('option');
                    o.value = tr;
                    o.textContent = tr === 'http'
                        ? _tt('mcp.transport_http', 'HTTP (automatisch: Streamable HTTP, sonst SSE)')
                        : tr;
                    sel.appendChild(o);
                }
                sel.value = tr;
                $('[data-f="command"]').value = cfg.command || '';
                $('[data-f="args"]').value = (cfg.args || []).join('\n');
                $('[data-f="sandbox"]').checked = cfg.sandbox !== false;
                $('[data-f="sandbox-paths"]').value = (cfg.sandbox_paths || []).join('\n');
                $('[data-f="url"]').value = cfg.url || '';
                $('[data-f="key-header"]').value = cfg.api_key_header || '';
                if (cfg.api_key_gesetzt) {
                    $('[data-f="key"]').placeholder = _tt('mcp.key_keep_ph', 'hinterlegt – leer lassen = unverändert');
                    $('[data-f="key-weg-zeile"]').style.display = '';
                }
                if (cfg.ca_cert_art === 'pfad') {
                    $('[data-f="ca"]').value = cfg.ca_cert_pfad || '';
                } else if (cfg.ca_cert_art === 'pem') {
                    $('[data-f="ca"]').placeholder = _tt('mcp.ca_keep_ph', 'Eigenes Zertifikat hinterlegt – leer lassen = unverändert');
                    $('[data-f="ca-weg-zeile"]').style.display = '';
                }
                if ((cfg.env_namen || []).length) {
                    $('[data-f="env"]').placeholder = _tt('mcp.env_keep_ph', 'Hinterlegt: {namen} – leer lassen = unverändert, eine Eingabe ersetzt alle')
                        .replace('{namen}', cfg.env_namen.join(', '));
                }
            }

            const transportZeigen = () => {
                const isStdio = $('[data-f="transport"]').value === 'stdio';
                $('[data-f="stdio-fields"]').style.display = isStdio ? '' : 'none';
                $('[data-f="sse-fields"]').style.display = isStdio ? 'none' : '';
            };
            $('[data-f="transport"]').addEventListener('change', transportZeigen);
            transportZeigen();

            $('[data-f="save"]').addEventListener('click', () => this._speichern(cfg, form));
            if (neu) {
                $('[data-f="cancel"]').addEventListener('click', () => form.remove());
                list.parentNode.insertBefore(form, list);
                $('[data-f="name"]').focus();
            } else {
                // In der Karte heisst "Abbrechen": Eingaben verwerfen, Stand neu laden.
                $('[data-f="cancel"]').textContent = _tt('mcp.discard', 'Änderungen verwerfen');
                $('[data-f="cancel"]').addEventListener('click', () => this._formLaden(cfg.id));
                ziel.replaceChildren(form);
            }
        }

        async _speichern(cfg, form) {
            const neu = !cfg;
            const wert = (k) => form.querySelector(`[data-f="${k}"]`)?.value ?? '';
            const fehler = form.querySelector('[data-f="fehler"]');
            if (fehler) fehler.textContent = '';
            const name = wert('name').trim();
            if (!name) return alert(window.t('mcp.name_required'));

            const zeilen = (t) => t.split('\n').map(s => s.trim()).filter(Boolean);
            const envText = wert('env');
            const env = {};
            envText.split('\n').forEach(line => {
                const eq = line.indexOf('=');
                if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
            });
            const data = {
                name,
                transport: wert('transport'),
                command: wert('command').trim(),
                args: zeilen(wert('args')),
                url: wert('url').trim(),
                sandbox: form.querySelector('[data-f="sandbox"]')?.checked !== false,
                sandbox_paths: zeilen(wert('sandbox-paths')),
                api_key_header: wert('key-header').trim(),
            };
            // Eigenes Zertifikat: PEM-Block ODER absoluter Pfad, beides im
            // selben Feld (die Weiche steht im Backend, backend/mcp_tls.py).
            // Zeilenumbrueche bleiben erhalten – ein PEM-Block braucht sie.
            const ca = wert('ca').trim();
            const key = wert('key').trim();
            if (neu) {
                Object.assign(data, { env, enabled: true, ca_cert: ca, api_key: key });
            } else {
                // Leer = unveraendert (siehe _formular); Entfernen nur per Kaestchen.
                if (form.querySelector('[data-f="key-weg"]')?.checked) data.api_key = '';
                else if (key) data.api_key = key;
                if (envText.trim()) data.env = env;
                if (form.querySelector('[data-f="ca-weg"]')?.checked) data.ca_cert = '';
                else if (cfg.ca_cert_art === 'pem') { if (ca) data.ca_cert = ca; }
                else data.ca_cert = ca;     // Pfad stand im Feld – leer heisst entfernt
            }

            try {
                const token = window.JarvisSitzung.token();
                const r = await fetch(neu ? '/api/mcp/servers'
                                          : `/api/mcp/servers/${encodeURIComponent(cfg.id)}`, {
                    method: neu ? 'POST' : 'PUT',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                if (!r.ok) {
                    let d = null;
                    try { d = await r.json(); } catch (_) { /* kein JSON */ }
                    throw new Error((d && d.detail) || `HTTP ${r.status}`);
                }
                if (neu) form.remove();
                await this.refresh();
            } catch (e) {
                // Ein Fehler bleibt im Formular stehen, bis er gelesen ist.
                const msg = window.t('mcp.error').replace('{msg}', e.message || e);
                if (fehler) fehler.textContent = msg; else alert(msg);
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

        /** Freigabe-Wert eines Servers in der Form des Freigabe-Popups. */
        _freigabeWert(srv) {
            return { users: srv.allowed_users || '', groups: srv.allowed_group || '' };
        }

        /**
         * Berechtigungen ueber das gemeinsame Freigabe-Popup (freigabe_dialog.js).
         * Gesendet werden NUR die zwei Freigabefelder – der Endpunkt merged,
         * ein voller Formularstand ueberschriebe sonst die Serverdaten.
         */
        _rechte(id) {
            const srv = this._servers.find(s => s.id === id);
            if (!srv || !window.JarvisFreigabe) return;
            window.JarvisFreigabe.oeffnen({
                titel: _tt('mcp.rights_title', 'Berechtigungen') + ' – ' + (srv.name || ''),
                hinweis: window.t('mcp.net_users_hint'),
                wert: this._freigabeWert(srv),
                speichern: async (w) => {
                    const token = window.JarvisSitzung.token();
                    const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}`, {
                        method: 'PUT',
                        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                        body: JSON.stringify({ allowed_users: w.users,
                                               allowed_group: w.groups }),
                    });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    await this.refresh();
                },
            });
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
            // Der Kasten liegt im einklappbaren Teil – sonst kaeme das Ergebnis
            // in einer zugeklappten Karte nie zum Vorschein.
            this._klappen(id, true);
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
