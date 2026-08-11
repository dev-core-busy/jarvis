/**
 * Pull-Synchronisation von Wissensordnern zwischen Jarvis-Standorten.
 *
 * Zwei Rollen auf einer Flaeche (Einstellungen -> Wissen):
 *   NEHMER  Container "Pull-Synchronisation": Standorte anlegen, pruefen,
 *           pausieren, jetzt holen.
 *   GEBER   Das 🔗-Symbol an jeder Ordnerzeile ("Ordner"): Freigabe anlegen,
 *           Token kopieren, Abruf-Protokoll ansehen, widerrufen.
 *
 * Grundsaetze der Anzeige (im Projekt mehrfach teuer gelernt):
 *   - Nie einen Zustand behaupten, den die Seite nicht kennt: solange der Abruf
 *     nicht beantwortet ist, steht "Lädt…" da, nicht "keine Standorte".
 *   - Fremdtexte (Standortname, Beschriftung, Fehlermeldung der Gegenstelle)
 *     immer per textContent bzw. escaped einsetzen.
 *   - Keine harten Farben, nur CSS-Variablen; jeder Text ueber data-i18n bzw.
 *     window.t().
 */
(function () {
    'use strict';

    const T = (k, f) => (window.t ? window.t(k) || f : f);
    const $ = (id) => document.getElementById(id);

    function esc(s) {
        return String(s === null || s === undefined ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function token() {
        for (const k of ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token']) {
            const v = localStorage.getItem(k);
            if (v) return v;
        }
        return '';
    }

    async function api(pfad, opt) {
        const o = Object.assign({ headers: {} }, opt || {});
        o.headers = Object.assign({ 'Authorization': 'Bearer ' + token() }, o.headers);
        if (o.body && !o.headers['Content-Type']) o.headers['Content-Type'] = 'application/json';
        const r = await fetch(pfad, o);
        let d = {};
        try { d = await r.json(); } catch (e) { d = {}; }
        return { ok: r.ok, status: r.status, data: d };
    }

    function bytes(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
        return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
    }

    function zeit(ts) {
        if (!ts) return '–';
        try { return new Date(Number(ts) * 1000).toLocaleString(); } catch (e) { return '–'; }
    }

    /** "vor 3 Min" / "in 2 Std" – eine absolute Zeit allein sagt nicht, ob es frisch ist. */
    function relativ(ts) {
        if (!ts) return '';
        const d = Number(ts) * 1000 - Date.now();
        const min = Math.round(Math.abs(d) / 60000);
        let text;
        if (min < 1) text = T('kbsync.rel_now', 'gerade eben');
        else if (min < 60) text = min + ' ' + T('kbsync.rel_min', 'Min');
        else if (min < 1440) text = Math.round(min / 60) + ' ' + T('kbsync.rel_hours', 'Std');
        else text = Math.round(min / 1440) + ' ' + T('kbsync.rel_days', 'Tage');
        if (min < 1) return text;
        return d < 0 ? T('kbsync.rel_ago', 'vor {x}').replace('{x}', text)
                     : T('kbsync.rel_in', 'in {x}').replace('{x}', text);
    }

    const KnowledgeSync = {
        _peers: [], _lizenz: true, _lizenzGrund: '', _sichtbar: false,
        _gebunden: false, _probe: null, _bearbeitet: null, _timer: null,
        _gruppen: [], _shares: [],

        // ── Container (Rolle Nehmer) ───────────────────────────────────────
        onShow() {
            this._bind();
            this.load();
        },

        _bind() {
            if (this._gebunden) return;
            this._gebunden = true;
            const b = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', fn); };
            b('kbsync-site-save', () => this.saveSite());
            b('kbsync-add-btn', () => this.showForm());
            b('kbsync-form-cancel', () => this.hideForm());
            b('kbsync-probe-btn', () => this.probe());
            b('kbsync-save-btn', () => this.savePeer());
            const hdr = $('kb-sect-sync-hdr');
            // Der Klapp-Umschalter selbst haengt in app.js (_collapseInit). Hier
            // nur nachladen, wenn der Abschnitt sichtbar WIRD – ein Abruf fuer
            // einen zugeklappten Abschnitt ist verschenkte Zeit.
            if (hdr) hdr.addEventListener('click', () => setTimeout(() => {
                const body = $('kb-sect-sync-body');
                const offen = body && body.style.display !== 'none';
                this._sichtbar = !!offen;
                if (offen) this.load();
                this._takt();
            }, 0));
        },

        /** Fortschritt nur takten, solange wirklich etwas laeuft und der Abschnitt offen ist. */
        _takt() {
            const laeuft = this._peers.some(p => p.running);
            if (this._timer && (!laeuft || !this._sichtbar)) {
                clearInterval(this._timer); this._timer = null;
            } else if (!this._timer && laeuft && this._sichtbar) {
                this._timer = setInterval(() => this.load(true), 2000);
            }
        },

        async load(still) {
            const box = $('kbsync-peer-list');
            if (!box) return;
            const r = await api('/api/knowledge/sync');
            if (!r.ok) {
                box.innerHTML = '<div class="kbsync-err">' +
                    esc(r.data.error || T('kbsync.load_failed', 'Standorte konnten nicht geladen werden')) +
                    '</div>';
                return;
            }
            this._peers = r.data.peers || [];
            this._lizenz = r.data.license_ok !== false;
            this._lizenzGrund = r.data.license_reason || '';
            const site = $('kbsync-site-name');
            // Eine laufende Eingabe nicht ueberschreiben (der Takt laeuft alle 2 s).
            if (site && document.activeElement !== site && !still) {
                site.value = r.data.site_name || '';
                site.placeholder = r.data.hostname || 'Standort';
            }
            const lic = $('kbsync-license');
            if (lic) {
                lic.style.display = this._lizenz ? 'none' : '';
                lic.textContent = this._lizenzGrund;
            }
            const add = $('kbsync-add-btn');
            if (add) add.disabled = !this._lizenz;
            this._render();
            this._takt();
        },

        _render() {
            const box = $('kbsync-peer-list');
            if (!box) return;
            const zaehler = $('kbsync-count');
            if (zaehler) zaehler.textContent = this._peers.length ? ' (' + this._peers.length + ')' : '';
            if (!this._peers.length) {
                box.innerHTML = '<div class="kb-hint" style="margin:0;">' +
                    esc(T('kbsync.empty', 'Noch kein Standort eingetragen.')) + '</div>';
                return;
            }
            box.innerHTML = this._peers.map(p => this._zeile(p)).join('');
            this._peers.forEach(p => {
                const w = (suffix, fn) => {
                    const el = document.querySelector(`[data-kbsync="${suffix}"][data-id="${p.id}"]`);
                    if (el) el.addEventListener('click', fn);
                };
                w('run', () => this.runNow(p.id));
                w('toggle', () => this.togglePause(p));
                w('edit', () => this.showForm(p));
                w('del', () => this.deletePeer(p));
            });
        },

        _zeile(p) {
            const ls = p.last_sync || {};
            const fehler = p.last_error;
            const zustand = p.running ? 'running'
                : (p.state === 'paused' ? 'paused' : (fehler ? 'error' : 'ok'));
            const zLabel = {
                running: T('kbsync.st_running', 'läuft…'),
                paused: T('kbsync.st_paused', 'pausiert'),
                error: T('kbsync.st_error', 'Fehler'),
                ok: T('kbsync.st_ok', 'aktiv'),
            }[zustand];
            const pg = p.progress || {};
            const phase = {
                manifest: T('kbsync.ph_manifest', 'Dateiliste holen'),
                download: T('kbsync.ph_download', 'lädt'),
                cleanup: T('kbsync.ph_cleanup', 'räumt auf'),
                index: T('kbsync.ph_index', 'indiziert'),
            }[pg.phase] || pg.phase || '';
            const fortschritt = p.running
                ? `<div class="kbsync-progress">${esc(phase)} ${pg.total ? esc(pg.done + '/' + pg.total) : ''}
                     <span class="kbsync-cur">${esc(pg.current || '')}</span></div>`
                : '';
            const stand = ls.ts
                ? T('kbsync.last', 'Letzter Lauf: {t} ({r})')
                    .replace('{t}', zeit(ls.ts)).replace('{r}', relativ(ls.ts))
                : T('kbsync.never', 'noch nie synchronisiert');
            const naechst = (p.auto && p.state === 'active' && p.next_run)
                ? ' · ' + T('kbsync.next', 'nächster: {r}').replace('{r}', relativ(p.next_run))
                : (p.auto ? '' : ' · ' + T('kbsync.manual_only', 'nur manuell'));
            return `
            <div class="kbsync-card${p.state === 'paused' ? ' is-paused' : ''}">
                <div class="kbsync-hdr">
                    <span class="kbsync-pill kbsync-${zustand}">${esc(zLabel)}</span>
                    <span class="kbsync-name">${esc(p.name || p.url)}</span>
                    <span class="kbsync-url">${esc(p.url)}</span>
                    <span class="kbsync-spacer"></span>
                    <button class="kb-hdr-btn" data-kbsync="run" data-id="${esc(p.id)}"
                        title="${esc(T('kbsync.run_title', 'Jetzt synchronisieren'))}"
                        ${p.running || !this._lizenz ? 'disabled' : ''}>⟳</button>
                    <button class="kb-hdr-btn" data-kbsync="toggle" data-id="${esc(p.id)}"
                        title="${esc(p.state === 'paused' ? T('kbsync.resume_title', 'Fortsetzen')
                                                          : T('kbsync.pause_title', 'Pausieren'))}"
                        >${p.state === 'paused' ? '▶' : '⏸'}</button>
                    <button class="kb-hdr-btn" data-kbsync="edit" data-id="${esc(p.id)}"
                        title="${esc(T('kbsync.edit_title', 'Bearbeiten'))}">✏️</button>
                    <button class="kb-hdr-btn is-danger" data-kbsync="del" data-id="${esc(p.id)}"
                        title="${esc(T('kbsync.del_title', 'Standort entfernen'))}">✕</button>
                </div>
                <div class="kbsync-meta">
                    <code>${esc(p.target_folder)}</code>
                    ${p.remote_label ? ' ← ' + esc(p.remote_label) : ''}
                    ${p.remote_site ? ' @ ' + esc(p.remote_site) : ''}
                    · ${esc(p.file_count)} ${esc(T('kbsync.files', 'Dateien'))}
                    · ${esc(bytes(p.total_bytes))}
                </div>
                <div class="kbsync-meta">${esc(stand)}${naechst}</div>
                ${ls.ts && ls.ok ? `<div class="kbsync-meta">+${esc(ls.added || 0)} ${esc(T('kbsync.added', 'neu'))},
                     ${esc(ls.updated || 0)} ${esc(T('kbsync.updated', 'aktualisiert'))},
                     ${esc(ls.removed || 0)} ${esc(T('kbsync.removed', 'entfernt'))}</div>` : ''}
                ${fehler ? `<div class="kbsync-err">${esc(fehler)}</div>` : ''}
                ${fortschritt}
            </div>`;
        },

        async saveSite() {
            const el = $('kbsync-site-name');
            if (!el) return;
            const r = await api('/api/knowledge/sync/site', {
                method: 'POST', body: JSON.stringify({ site_name: el.value }),
            });
            this._melden(r.ok ? T('kbsync.site_saved', 'Standortname gespeichert')
                              : (r.data.error || 'Fehler'), r.ok);
            if (r.ok) el.value = r.data.site_name || el.value;
        },

        // ── Formular ──────────────────────────────────────────────────────
        async showForm(peer) {
            this._bearbeitet = peer || null;
            this._probe = null;
            const f = $('kbsync-form');
            if (!f) return;
            f.style.display = '';
            $('kbsync-form-err').style.display = 'none';
            $('kbsync-probe-result').style.display = 'none';
            $('kbsync-f-url').value = peer ? peer.url : '';
            $('kbsync-f-token').value = '';
            $('kbsync-f-token').placeholder = peer
                ? T('kbsync.f_token_keep', 'leer lassen = unverändert')
                : 'JARVIS-KBS-1.…';
            $('kbsync-f-name').value = peer ? (peer.name || '') : '';
            $('kbsync-f-folder').value = peer ? peer.target_folder : '';
            $('kbsync-f-auto').checked = peer ? !!peer.auto : false;
            $('kbsync-f-interval').value = peer ? peer.interval : 24;
            $('kbsync-f-unit').value = peer ? peer.unit : 'hours';
            await this._gruppenLaden(peer ? peer.group_id : '');
            // Beim Bearbeiten ist der Zielordner fest: ein Umzug waere ein neuer
            // Spiegel, der alte bliebe verwaist liegen (Backend lehnt es ab).
            $('kbsync-f-folder').disabled = !!peer;
            $('kbsync-step2').style.display = peer ? '' : 'none';
            $('kbsync-add-btn').style.display = 'none';
        },

        hideForm() {
            const f = $('kbsync-form');
            if (f) f.style.display = 'none';
            const a = $('kbsync-add-btn');
            if (a) a.style.display = '';
            this._bearbeitet = null;
            this._probe = null;
        },

        async _gruppenLaden(vorauswahl) {
            const sel = $('kbsync-f-group');
            if (!sel) return;
            if (!this._gruppen.length) {
                const r = await api('/api/knowledge/groups');
                this._gruppen = (r.data.groups || []).filter(g => g.id && g.id !== 'ungrouped');
            }
            sel.innerHTML = '<option value="">' + esc(T('kbsync.no_group', '– keine Gruppe –')) + '</option>'
                + this._gruppen.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('');
            if (vorauswahl) sel.value = vorauswahl;
        },

        _fehler(text) {
            const el = $('kbsync-form-err');
            if (!el) return;
            el.style.display = text ? '' : 'none';
            el.textContent = text || '';
        },

        async probe() {
            const url = $('kbsync-f-url').value.trim();
            const tok = $('kbsync-f-token').value.trim();
            const btn = $('kbsync-probe-btn');
            this._fehler('');
            if (!url || (!tok && !this._bearbeitet)) {
                this._fehler(T('kbsync.need_url_token', 'Adresse und Token sind nötig.'));
                return;
            }
            btn.disabled = true;
            btn.textContent = T('kbsync.probing', 'prüfe…');
            const r = await api('/api/knowledge/sync/probe', {
                method: 'POST', body: JSON.stringify({ url, token: tok }),
            });
            btn.disabled = false;
            btn.textContent = T('kbsync.probe', 'Verbindung prüfen');
            const box = $('kbsync-probe-result');
            if (!r.ok || !r.data.ok) {
                box.style.display = '';
                box.className = 'kbsync-probe is-bad';
                box.innerHTML = '<div>' + esc(r.data.error || T('kbsync.probe_failed', 'Prüfung fehlgeschlagen')) + '</div>'
                    + (r.data.fingerprint ? '<div class="kbsync-fp">' + esc(r.data.fingerprint) + '</div>' : '');
                $('kbsync-step2').style.display = this._bearbeitet ? '' : 'none';
                return;
            }
            this._probe = r.data;
            box.style.display = '';
            box.className = 'kbsync-probe is-good';
            box.innerHTML =
                '<div><b>' + esc(r.data.remote_site || '?') + '</b> · '
                + esc(r.data.remote_label || r.data.folder_name || '') + '</div>'
                + '<div>' + esc(r.data.file_count) + ' ' + esc(T('kbsync.files', 'Dateien'))
                + ' · ' + esc(bytes(r.data.total_bytes)) + '</div>'
                + '<div class="kbsync-fp" title="' + esc(T('kbsync.fp_hint',
                    'Zertifikat der Gegenstelle. Wird beim Speichern gebunden – ändert es sich später, bricht der Lauf ab.'))
                + '">' + esc(T('kbsync.fp', 'Zertifikat')) + ': ' + esc(r.data.fingerprint) + '</div>';
            $('kbsync-step2').style.display = '';
            if (!$('kbsync-f-name').value) $('kbsync-f-name').value = r.data.remote_site || r.data.url;
            if (!$('kbsync-f-folder').value) $('kbsync-f-folder').value = r.data.suggest_folder || '';
        },

        async savePeer() {
            this._fehler('');
            const nutz = {
                name: $('kbsync-f-name').value.trim(),
                url: $('kbsync-f-url').value.trim(),
                token: $('kbsync-f-token').value.trim(),
                group_id: $('kbsync-f-group').value,
                auto: $('kbsync-f-auto').checked,
                interval: parseInt($('kbsync-f-interval').value, 10) || 24,
                unit: $('kbsync-f-unit').value,
            };
            let r;
            if (this._bearbeitet) {
                // Der Fingerabdruck wird beim Bearbeiten nur uebernommen, wenn
                // gerade geprueft wurde – sonst bliebe die Bindung bestehen.
                if (this._probe) nutz.fingerprint = this._probe.fingerprint;
                r = await api('/api/knowledge/sync/peers/' + encodeURIComponent(this._bearbeitet.id),
                              { method: 'PATCH', body: JSON.stringify(nutz) });
            } else {
                if (!this._probe) {
                    this._fehler(T('kbsync.probe_first', 'Bitte zuerst die Verbindung prüfen.'));
                    return;
                }
                nutz.target_folder = $('kbsync-f-folder').value.trim();
                nutz.fingerprint = this._probe.fingerprint;
                nutz.remote_site = this._probe.remote_site;
                nutz.remote_label = this._probe.remote_label;
                r = await api('/api/knowledge/sync/peers', { method: 'POST', body: JSON.stringify(nutz) });
            }
            if (!r.ok || !r.data.ok) {
                this._fehler(r.data.error || T('kbsync.save_failed', 'Speichern fehlgeschlagen'));
                return;
            }
            this.hideForm();
            this._melden(T('kbsync.saved', 'Standort gespeichert'), true);
            this.load();
        },

        async togglePause(p) {
            const r = await api('/api/knowledge/sync/peers/' + encodeURIComponent(p.id), {
                method: 'PATCH',
                body: JSON.stringify({ state: p.state === 'paused' ? 'active' : 'paused' }),
            });
            if (!r.ok) this._melden(r.data.error || 'Fehler', false);
            this.load();
        },

        async deletePeer(p) {
            const frage = T('kbsync.del_confirm',
                'Standort „{n}" entfernen?\n\nOK = Eintrag entfernen, die lokale Kopie bleibt erhalten.')
                .replace('{n}', p.name || p.url);
            if (!confirm(frage)) return;
            // Zweite, ausdrueckliche Frage – ein Konfigurationsschritt darf nicht
            // nebenbei Wissen loeschen (deshalb ist "abbrechen" hier das Sichere).
            const mitDaten = confirm(T('kbsync.del_data',
                'Auch die lokale Kopie „{f}" samt indiziertem Wissen löschen?\n\nOK = löschen · Abbrechen = behalten')
                .replace('{f}', p.target_folder));
            const r = await api('/api/knowledge/sync/peers/' + encodeURIComponent(p.id)
                + (mitDaten ? '?remove_data=1' : ''), { method: 'DELETE' });
            this._melden(r.ok ? T('kbsync.deleted', 'Standort entfernt') : (r.data.error || 'Fehler'), r.ok);
            this.load();
            if (window.knowledgeManager && mitDaten) window.knowledgeManager.fetchStats?.();
        },

        async runNow(id) {
            const btn = document.querySelector(`[data-kbsync="run"][data-id="${id}"]`);
            if (btn) btn.disabled = true;
            this.load(true);
            this._takt();
            const r = await api('/api/knowledge/sync/peers/' + encodeURIComponent(id) + '/run',
                                { method: 'POST' });
            const d = r.data || {};
            if (d.ok) {
                let text = T('kbsync.done', '{a} neu, {u} aktualisiert, {r} entfernt')
                    .replace('{a}', d.added || 0).replace('{u}', d.updated || 0)
                    .replace('{r}', d.removed || 0);
                if (d.error_count) {
                    text += ' · ' + T('kbsync.with_errors', '{n} Datei(en) übersprungen')
                        .replace('{n}', d.error_count);
                }
                if (d.skipped_remote) {
                    text += ' · ' + T('kbsync.remote_skipped',
                        '{n} Datei(en) am anderen Standort nicht übertragen (Grenze)')
                        .replace('{n}', d.skipped_remote);
                }
                this._melden(text, true);
            } else {
                this._melden(d.error || T('kbsync.sync_failed', 'Synchronisation fehlgeschlagen'), false);
            }
            this.load();
        },

        _melden(text, gut) {
            const el = $('kb-notification');
            // Klassenname wie in knowledge.js::_showNotification – die CSS-Regeln
            // heissen kb-notification-success/-error, ein blosses "success" waere
            // unsichtbar (weisser Text auf Glas).
            if (!el) { if (!gut) alert(text); return; }
            el.textContent = text;
            el.className = 'kb-notification kb-notification-' + (gut ? 'success' : 'error');
            el.style.display = 'block';
            // Ein Fehler steht laenger: er nennt oft den Weg zur Behebung.
            setTimeout(() => { el.style.display = 'none'; }, gut ? 6000 : 12000);
        },

        // ── Funktionsbeschreibung (❓, druckbar) ───────────────────────────
        openInfo(zeigen) {
            const m = $('kbsync-info-modal');
            if (m) m.classList.toggle('open', !!zeigen);
        },

        /** Druckdialog fuer die Funktionsbeschreibung ("Als PDF speichern").
         *
         * `printing-doc` blendet per @media print alles ausser dem Dialog aus –
         * dieselbe Mechanik wie bei der API- und der Sicherheits-Doku, nur ueber
         * die gemeinsame Klasse statt einer fuenften Kopie derselben Regeln.
         * Die Klasse MUSS im `afterprint` wieder weg: bleibt sie stehen, ist die
         * Seite beim naechsten Druck (irgendeiner Seite) leer.
         */
        drucken() {
            const koerper = document.body;
            koerper.classList.add('printing-doc');
            const aufraeumen = () => {
                koerper.classList.remove('printing-doc');
                window.removeEventListener('afterprint', aufraeumen);
            };
            window.addEventListener('afterprint', aufraeumen);
            try { window.print(); } catch (e) { aufraeumen(); }
        },

        // ── Freigabe (Rolle Geber) ────────────────────────────────────────
        async openShare(ordner) {
            const modal = $('kbsync-share-modal');
            const body = $('kbsync-share-body');
            if (!modal || !body) return;
            // Konvention des Projekts ist die Klasse `open` (.modal.open in
            // style.css) – ein eigenes style.display waere unsichtbar, weil das
            // Grundlayout opacity:0 setzt.
            modal.classList.add('open');
            this._shareFolder = ordner;
            body.innerHTML = '<div class="kb-loading">' + esc(T('knowledge.loading', 'Lädt…')) + '</div>';
            const r = await api('/api/knowledge/shares');
            if (!r.ok) {
                body.innerHTML = '<div class="kbsync-err">' + esc(r.data.error || 'Fehler') + '</div>';
                return;
            }
            this._shares = r.data.shares || [];
            this._renderShare();
        },

        closeShare() {
            const modal = $('kbsync-share-modal');
            if (modal) modal.classList.remove('open');
            // Die Ordnerliste zeigt an Marke und Symbol, ob eine Freigabe besteht –
            // nur die Marken auffrischen, NICHT die ganze Liste neu laden: ein
            // Neuaufbau wuerde aufgeklappte Dateilisten schliessen (und
            // `loadStats` gibt es gar nicht, der Aufruf war mit `?.()` still
            // wirkungslos – die Marke erschien erst nach einem Neuladen).
            if (window.knowledgeManager) window.knowledgeManager.refreshShareMarks?.();
        },

        _renderShare() {
            const body = $('kbsync-share-body');
            const ordner = this._shareFolder;
            const s = this._shares.find(x => x.folder === ordner);
            if (!s) {
                body.innerHTML = `
                    <p class="kb-hint">${esc(T('kbsync.share_new_hint',
                        'Der Ordner wird samt allen Unterordnern lesbar – über EIN Token. Der andere Standort trägt Adresse und Token bei sich unter Wissen → Pull-Synchronisation ein.'))}</p>
                    <div class="kbsync-field">
                        <label data-i18n="kbsync.share_folder">Ordner</label>
                        <code>${esc(ordner)}</code>
                    </div>
                    <div class="kbsync-field">
                        <label for="kbsync-share-label">${esc(T('kbsync.share_label', 'Beschriftung (was ist das für ein Wissen?)'))}</label>
                        <input type="text" id="kbsync-share-label" class="kb-input" maxlength="120"
                               value="${esc(ordner.split('/').pop())}" />
                    </div>
                    <button class="kb-btn-action" id="kbsync-share-create">${esc(T('kbsync.share_create', 'Freigeben und Token erzeugen'))}</button>
                    <div id="kbsync-share-err" class="kbsync-err" style="display:none;"></div>`;
                $('kbsync-share-create').addEventListener('click', () => this._createShare());
                return;
            }
            const abrufe = (s.pulls || []).slice(0, 20);
            body.innerHTML = `
                <div class="kbsync-field">
                    <label>${esc(T('kbsync.share_folder', 'Ordner'))}</label>
                    <div class="kbsync-row">
                        <code>${esc(s.folder)}</code>
                        <span class="kbsync-pill ${s.enabled ? 'kbsync-ok' : 'kbsync-paused'}">${
                            esc(s.enabled ? T('kbsync.share_active', 'freigegeben')
                                          : T('kbsync.share_paused', 'pausiert'))}</span>
                    </div>
                    ${s.label ? `<div class="kbsync-meta">${esc(s.label)}</div>` : ''}
                </div>
                <div class="kbsync-field">
                    <label>${esc(T('kbsync.share_token', 'Freigabe-Token'))}</label>
                    <div class="kbsync-row">
                        <input type="text" class="kb-input" id="kbsync-share-token" readonly value="${esc(s.token)}" />
                        <button class="kb-hdr-btn" id="kbsync-share-copy"
                            title="${esc(T('kbsync.share_copy', 'Token kopieren'))}">⧉</button>
                    </div>
                    <span class="kb-hint">${esc(T('kbsync.share_token_hint',
                        'Wie ein Passwort behandeln: wer das Token hat, kann diesen Ordner lesen.'))}</span>
                </div>
                <div class="kbsync-row">
                    <button class="kb-hdr-btn" id="kbsync-share-toggle">${
                        esc(s.enabled ? T('kbsync.share_pause', '⏸ Pausieren')
                                      : T('kbsync.share_resume', '▶ Fortsetzen'))}</button>
                    <button class="kb-hdr-btn" id="kbsync-share-rotate">${esc(T('kbsync.share_rotate', '↻ Neues Token'))}</button>
                    <button class="kb-hdr-btn is-danger" id="kbsync-share-revoke">${esc(T('kbsync.share_revoke', '✕ Freigabe widerrufen'))}</button>
                </div>
                <h3 style="margin-top:18px;">${esc(T('kbsync.share_pulls', 'Wer hat geholt?'))}</h3>
                ${abrufe.length ? `<table class="kbsync-pulls"><thead><tr>
                        <th>${esc(T('kbsync.pull_when', 'Zeitpunkt'))}</th>
                        <th>${esc(T('kbsync.pull_site', 'Standort'))}</th>
                        <th>${esc(T('kbsync.pull_addr', 'Adresse'))}</th>
                        <th>${esc(T('kbsync.pull_scope', 'Umfang'))}</th></tr></thead><tbody>${
                    abrufe.map(a => `<tr><td>${esc(zeit(a.ts))}</td><td>${esc(a.site)}</td>
                        <td>${esc(a.ip)}</td><td>${esc(a.files)} · ${esc(bytes(a.bytes))}</td></tr>`).join('')
                    }</tbody></table>`
                    : `<p class="kb-hint">${esc(T('kbsync.share_no_pulls', 'Bisher hat kein Standort etwas geholt.'))}</p>`}
                <div id="kbsync-share-err" class="kbsync-err" style="display:none;"></div>`;
            $('kbsync-share-copy').addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(s.token);
                    this._shareMeldung(T('kbsync.copied', 'Token kopiert'), true);
                } catch (e) {
                    $('kbsync-share-token').select();
                    this._shareMeldung(T('kbsync.copy_failed',
                        'Kopieren nicht möglich – das Token ist markiert, bitte mit Strg+C kopieren.'), false);
                }
            });
            $('kbsync-share-toggle').addEventListener('click', () => this._patchShare(s.id, { enabled: !s.enabled }));
            $('kbsync-share-rotate').addEventListener('click', () => {
                if (!confirm(T('kbsync.rotate_confirm',
                    'Neues Token erzeugen? Das alte wird sofort ungültig – der andere Standort muss das neue eintragen, sonst holt er nichts mehr.'))) return;
                this._rotateShare(s.id);
            });
            $('kbsync-share-revoke').addEventListener('click', () => {
                if (!confirm(T('kbsync.revoke_confirm',
                    'Freigabe widerrufen? Der andere Standort holt danach nichts mehr. Seine bereits vorhandene Kopie bleibt dort erhalten – die kann nur er selbst löschen.'))) return;
                this._revokeShare(s.id);
            });
        },

        _shareMeldung(text, gut) {
            const el = $('kbsync-share-err');
            if (!el) return;
            el.textContent = text;
            el.style.display = '';
            el.className = gut ? 'kbsync-ok-msg' : 'kbsync-err';
        },

        async _createShare() {
            const label = ($('kbsync-share-label') || {}).value || '';
            const r = await api('/api/knowledge/shares', {
                method: 'POST',
                body: JSON.stringify({ folder: this._shareFolder, label }),
            });
            if (!r.ok || !r.data.ok) { this._shareMeldung(r.data.error || 'Fehler', false); return; }
            this._shares.push(r.data.share);
            this._renderShare();
        },

        async _patchShare(id, felder) {
            const r = await api('/api/knowledge/shares/' + encodeURIComponent(id),
                                { method: 'PATCH', body: JSON.stringify(felder) });
            if (!r.ok || !r.data.ok) { this._shareMeldung(r.data.error || 'Fehler', false); return; }
            this._shares = this._shares.map(s => (s.id === id ? r.data.share : s));
            this._renderShare();
        },

        async _rotateShare(id) {
            const r = await api('/api/knowledge/shares/' + encodeURIComponent(id) + '/rotate',
                                { method: 'POST' });
            if (!r.ok || !r.data.ok) { this._shareMeldung(r.data.error || 'Fehler', false); return; }
            this._shares = this._shares.map(s => (s.id === id ? r.data.share : s));
            this._renderShare();
            this._shareMeldung(T('kbsync.rotated', 'Neues Token erzeugt – bitte am anderen Standort eintragen.'), true);
        },

        async _revokeShare(id) {
            const r = await api('/api/knowledge/shares/' + encodeURIComponent(id), { method: 'DELETE' });
            if (!r.ok) { this._shareMeldung(r.data.error || 'Fehler', false); return; }
            this._shares = this._shares.filter(s => s.id !== id);
            this._renderShare();
        },

        /** Ordnerpfade mit bestehender Freigabe – die Ordnerliste faerbt ihr Symbol danach. */
        async sharedFolders() {
            const r = await api('/api/knowledge/shares');
            this._shares = (r.data && r.data.shares) || [];
            return this._shares.filter(s => s.enabled).map(s => s.folder);
        },
    };

    window.KnowledgeSync = KnowledgeSync;
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        // Reihenfolge: die Funktionsbeschreibung liegt UEBER dem Freigabe-Dialog
        // (z-index 10002). Sonst bliebe sie ueber einem geschlossenen Dialog
        // stehen – dieselbe Regel wie beim AD-Picker mit Unter-Popup.
        const info = $('kbsync-info-modal');
        if (info && info.classList.contains('open')) { KnowledgeSync.openInfo(false); return; }
        const m = $('kbsync-share-modal');
        if (m && m.classList.contains('open')) KnowledgeSync.closeShare();
    });
})();
