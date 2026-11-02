/* BSI H4, CSP ohne Inline-Skript (2026-10-04): Firmenverzeichnis (Active Directory) im
   Sicherheits-Reiter: Laden, Speichern (window._adSave), Verbindungstest
   (window._adTest).
   Bis hierher stand dieser Code als Inline-<script> in settings.html.
   Eine Content-Security-Policy mit script-src 'self' ohne 'unsafe-inline'
   fuehrt kein Inline-Skript aus – deshalb ausgelagert, Inhalt unveraendert.
   Eingebunden SYNCHRON an DERSELBEN Stelle der Seite wie vorher (kein
   defer/async): Zeitpunkt und Reihenfolge bleiben gleich, inklusive dessen,
   was das Skript zu diesem Zeitpunkt vom Dokument schon sieht. */
(function() {
    // ── Bereichs-Freigaben ────────────────────────────────────────────────
    // ⚠ SEIT 2026-11-02 GIBT ES DAFUER KEINE EINGABEFELDER MEHR. Bis dahin
    // standen je Bereich zwei Felder im Container "alte Benutzerberechtigungen",
    // und die Tabelle (rechte_matrix.js) schrieb dort hinein. Der Container ist
    // auf Vorgabe des Betreibers entfallen; der Bestand liegt jetzt HIER, die
    // Tabelle liest und schreibt ihn ueber window.AdRechte.
    // feld = Kennung (wie die frueheren Feld-Ids, rechte_matrix.js benutzt sie),
    // lesen = Schluessel in /api/auth/ad_status, schreiben = Schluessel fuer
    // POST /api/settings.
    var FREIGABEN = [
        { feld: 'ad-allowed-users',           lesen: 'allowed_users',           schreiben: 'ad_allowed_users' },
        { feld: 'ad-allowed-group',           lesen: 'allowed_group',           schreiben: 'ad_allowed_group' },
        { feld: 'ad-knowledge-editors',       lesen: 'knowledge_editors',       schreiben: 'ad_knowledge_editors' },
        { feld: 'ad-knowledge-editors-group', lesen: 'knowledge_editors_group', schreiben: 'ad_knowledge_editors_group' },
        { feld: 'ad-internet-users',          lesen: 'internet_users',          schreiben: 'ad_internet_users' },
        { feld: 'ad-internet-group',          lesen: 'internet_group',          schreiben: 'ad_internet_group' },
        { feld: 'ad-admins',                  lesen: 'admins',                  schreiben: 'ad_admins' },
        { feld: 'ad-admins-group',            lesen: 'admins_group',            schreiben: 'ad_admins_group' },
        { feld: 'sap-allowed-users',          lesen: 'sap_users',               schreiben: 'sap_allowed_users' },
        { feld: 'sap-allowed-group',          lesen: 'sap_group',               schreiben: 'sap_allowed_group' },
        { feld: 'vemas-allowed-users',        lesen: 'vemas_users',             schreiben: 'vemas_allowed_users' },
        { feld: 'vemas-allowed-group',        lesen: 'vemas_group',             schreiben: 'vemas_allowed_group' },
        { feld: 'email-allowed-users',        lesen: 'email_users',             schreiben: 'email_allowed_users' },
        { feld: 'email-allowed-group',        lesen: 'email_group',             schreiben: 'email_allowed_group' },
        { feld: 'tracks-allowed-users',       lesen: 'tracks_users',            schreiben: 'tracks_allowed_users' },
        { feld: 'tracks-allowed-group',       lesen: 'tracks_group',            schreiben: 'tracks_allowed_group' },
        { feld: 'jiraassist-allowed-users',   lesen: 'jira_assist_users',       schreiben: 'jira_assist_allowed_users' },
        { feld: 'jiraassist-allowed-group',   lesen: 'jira_assist_group',       schreiben: 'jira_assist_allowed_group' },
        { feld: 'aimouse-allowed-users',      lesen: 'aimouse_users',           schreiben: 'aimouse_allowed_users' },
        { feld: 'aimouse-allowed-group',      lesen: 'aimouse_group',           schreiben: 'aimouse_allowed_group' },
        { feld: 'excel-allowed-users',        lesen: 'excel_users',             schreiben: 'excel_allowed_users' },
        { feld: 'excel-allowed-group',        lesen: 'excel_group',             schreiben: 'excel_allowed_group' },
        { feld: 'claudesub-allowed-users',    lesen: 'claudesub_users',         schreiben: 'claudesub_allowed_users' },
        { feld: 'claudesub-allowed-group',    lesen: 'claudesub_group',         schreiben: 'claudesub_allowed_group' }
    ];
    var _bestand = {};
    function _kennt(feld) {
        return FREIGABEN.some(function (f) { return f.feld === feld; });
    }
    // Unbekannte Kennungen WERFEN: ein Tippfehler in rechte_matrix.js waere
    // sonst eine Spalte, die still nichts speichert.
    function _pruefe(feld) {
        if (!_kennt(feld)) throw new Error('unbekannte Freigabe: ' + feld);
    }
    window.AdRechte = {
        kennt: _kennt,
        lesen: function (feld) { _pruefe(feld); return _bestand[feld] || ''; },
        setzen: function (feld, wert) { _pruefe(feld); _bestand[feld] = String(wert == null ? '' : wert); }
    };

    async function _adLoad() {
        try {
            const r = await fetch('/api/auth/ad_status', {
                headers: { 'Authorization': 'Bearer ' + (window.JarvisSitzung.token()) }
            });
            // Ohne diese Zeile gaelte eine Fehlerantwort als geladener, LEERER
            // Bestand – und das naechste Speichern loeschte jede Freigabe.
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const d = await r.json();
            document.getElementById('ad-server').value        = d.server        || '';
            document.getElementById('ad-domain').value        = d.domain        || '';
            document.getElementById('ad-bind-user').value = d.bind_user || '';
            document.getElementById('ad-bind-password').value = '';
            document.getElementById('ad-bind-pw-hint').textContent = window.t(d.bind_password_set ? 'security.ad_pw_saved' : 'security.ad_pw_none');
            FREIGABEN.forEach(function (f) { _bestand[f.feld] = d[f.lesen] || ''; });
            _adUpdateStatus(d);
            _adCertMount(d);
            // Fuer die Berechtigungs-Tabelle (rechte_matrix.js): erst mit
            // geladenem Bestand darf von dort gespeichert werden, sonst gingen
            // leere Listen an den Server.
            window._adGeladen = true;
        } catch(e) {
        } finally {
            // ⚠ DIE TABELLE STEHT SEIT 2026-10-21 AUF DER SEITE, nicht mehr in
            // einem Popup – sie kann ihren Bestand also nicht mehr "beim
            // Oeffnen" lesen. Ohne dieses Signal zeigte sie dauerhaft die
            // leeren Felder von vor dem Abruf, und zwar ohne Fehlermeldung.
            // ⚠ IM `finally`, NICHT IM `try`: faellt der Abruf aus, muss die
            // Tabelle das ERFAHREN. Nur im Erfolgsfall gemeldet, bliebe sie
            // ewig bei "wird geladen…" stehen – eine Anzeige, die einen
            // Zustand behauptet, den sie nicht kennt.
            document.dispatchEvent(new CustomEvent('jarvis-ad-geladen',
                { detail: { ok: !!window._adGeladen } }));
        }
    }

    // Serverzertifikat des DCs pruefen/verankern (gemeinsamer Baustein
    // sapcert.js). Die Pruefung ist serverseitig IMMER an (BSI H5).
    var _adCert = null, _adAnker = {};
    function _adCertMount(d) {
        _adAnker = (d && d.tls_anker && typeof d.tls_anker === 'object') ? d.tls_anker : {};
        // Uebergangsfrist ohne Zertifikatspruefung: sichtbar warnen, bis ein Anker steht
        var ue = (d && d.tls_uebergang) || {};
        var hinw = document.getElementById('ad-tls-uebergang');
        if (hinw) {
            hinw.hidden = !(ue.aktiv && !_adAnker.fingerprint && d.configured);
            hinw.textContent = window.t('security.ad_tls_transition').replace('{bis}', ue.bis || '—');
        }
        if (_adCert) { _adCert.refresh(); return; }
        var box = document.getElementById('ad-cert');
        if (!box || !window.SapCert) return;
        _adCert = window.SapCert.mount(box, {
            basis: '/api/auth/ad_tls',
            kanal: 'ad',
            ziel: function () { return { server: document.getElementById('ad-server').value.trim() }; },
            gebunden: function () { return _adAnker; },
            nachAenderung: function () { _adLoad(); },
            texte: {
                v_no: ['adcert.v_no', 'Verankern würde hier nicht helfen ({grund}).'],
                browser_hint: ['adcert.browser_hint', 'Die Verbindung zum Domain-Controller baut der Server auf, nicht der Browser – ein Eintrag im Browser-Zertifikatsspeicher wirkt hier nicht.']
            }
        });
    }

    // Farben NUR ueber Klassen aus theme.css (Code-Review 2026-10-07: hier
    // standen feste Hex-Werte und Emojis, aus dem frueheren Inline-Skript
    // uebernommen). Der Rahmen folgt der Schriftfarbe (border: 1px solid im
    // Markup = currentColor).
    var _ART = ['jv-hinweis-warn', 'jv-hinweis-ok', 'jv-hinweis-info', 'jv-hinweis-err'];
    function _hinweis(el, art, text) {
        if (!el) return;
        _ART.forEach(function (k) { el.classList.remove(k); });
        if (!art) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        el.classList.add('jv-hinweis-' + art);
        el.textContent = text;
    }
    function _adUpdateStatus(d) {
        const dot  = document.getElementById('ad-status-dot');
        const txt  = document.getElementById('ad-status-text');
        const hint = document.getElementById('ad-mode-hint');
        _ART.forEach(function (k) { dot.classList.remove(k); txt.classList.remove(k); });
        if (!d.configured) {
            dot.style.background = 'var(--text-muted)';
            txt.style.color      = 'var(--text-muted)';
            txt.textContent      = window.t('security.ad_not_configured');
            _hinweis(hint, null);
            return;
        }
        const modeLabels = { none: window.t('security.ad_mode_none'), users: window.t('security.ad_mode_users'), group: window.t('security.ad_mode_group'), users_group: window.t('security.ad_mode_users_group') };
        // Punkt: Hintergrund = Schriftfarbe der Klasse; keine Inline-Farbe am
        // Text, sonst schlaegt sie die Klasse
        dot.style.background = 'currentColor';
        txt.style.color = '';
        if (d.reachable === false) {
            // Konfiguriert heisst NICHT erreichbar: rot statt gruen
            dot.classList.add('jv-hinweis-err'); txt.classList.add('jv-hinweis-err');
            txt.textContent = window.t('security.ad_unreachable_label') + ' · ' + d.server + ' · ' + d.domain;
        } else {
            dot.classList.add('jv-hinweis-ok'); txt.classList.add('jv-hinweis-ok');
            txt.textContent = window.t('security.ad_active_label') + ' · ' + d.server + ' · ' + d.domain + ' · ' + (modeLabels[d.access_mode] || d.access_mode);
        }
        if (d.access_mode === 'none') {
            _hinweis(hint, 'warn', window.t('security.ad_warn_none'));
        } else if (d.access_mode === 'users') {
            _hinweis(hint, 'ok', window.t('security.ad_users_active') + ' ' + d.allowed_users);
        } else if (d.access_mode === 'group') {
            _hinweis(hint, 'info', window.t('security.ad_group_active') + ' ' + d.allowed_group);
        } else if (d.access_mode === 'users_group') {
            // Liste UND Gruppe: ODER-verknuepft. Beide Werte nennen, damit
            // ablesbar ist, dass KEINES der Felder das andere aushebelt.
            _hinweis(hint, 'info', window.t('security.ad_users_group_active') + ' ' + d.allowed_users +
                                   ' ' + window.t('security.ad_or_group') + ' ' +
                                   (d.allowed_group || '').split('\n').join(', '));
        } else {
            _hinweis(hint, null);
        }
    }

    // Speichern-Knoepfe und Statuszeilen werden ueber Klick-Marke bzw. Klasse
    // gesammelt, nicht ueber Ids: bis 2026-11-02 gab es den Knopf zweimal, und
    // ein weiterer waere damit von selbst mit versorgt.
    function _saveKnoepfe() {
        return Array.prototype.slice.call(document.querySelectorAll('[data-klick="ad-speichern"]'));
    }
    function _saveStatus(text, farbe) {
        const sts = document.querySelectorAll('.ad-save-status');
        for (let i = 0; i < sts.length; i++) {
            sts[i].textContent = text;
            sts[i].style.color = farbe || '';
        }
    }

    // ⚠ FREIGABEN NUR MIT GELADENEM BESTAND. Das Backend uebernimmt nur
    // Schluessel, die im Koerper STEHEN. Ist der Abruf gescheitert, fehlen sie
    // deshalb ganz – sonst loeschte "Speichern" an der Verbindung jede Freigabe.
    function _koerper() {
        var k = {
            ad_server:        document.getElementById('ad-server').value.trim(),
            ad_domain:        document.getElementById('ad-domain').value.trim(),
            ad_bind_user:     document.getElementById('ad-bind-user').value.trim(),
            ad_bind_password: document.getElementById('ad-bind-password').value
        };
        if (window._adGeladen) {
            FREIGABEN.forEach(function (f) { k[f.schreiben] = (_bestand[f.feld] || '').trim(); });
        }
        return k;
    }

    window._adSave = async function() {
        const btns = _saveKnoepfe();
        btns.forEach(function (b) { b.disabled = true; });
        _saveStatus(window.t('common.saving'), 'var(--text-muted)');
        try {
            const r = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (window.JarvisSitzung.token()) },
                body: JSON.stringify(_koerper())
            });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            _saveStatus(window.t('security.ad_saved'), 'var(--success)');
            // Ein Erfolg darf von selbst verschwinden, ein Fehler nicht - den
            // muss man lesen und kopieren koennen.
            setTimeout(() => { _saveStatus(''); }, 3000);
            await _adLoad();
            return true;
        } catch(e) {
            _saveStatus(window.t('security.ad_save_failed').replace('{grund}', e.message), 'var(--danger)');
            return false;
        } finally { btns.forEach(function (b) { b.disabled = false; }); }
    };

    window._adTest = async function() {
        const res = document.getElementById('ad-test-result');
        const srv = document.getElementById('ad-server').value.trim();
        const dom = document.getElementById('ad-domain').value.trim();
        if (!srv || !dom) { res.style.color='var(--warning)'; res.textContent=window.t('security.ad_fill_fields'); return; }
        res.style.color='var(--text-muted)'; res.textContent=window.t('security.ad_connecting') + ' ' + srv + '…';
        try {
            const r = await fetch('/api/auth/ad_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (window.JarvisSitzung.token()) },
                body: JSON.stringify({ ad_server: srv, ad_domain: dom })
            });
            const d = await r.json();
            if (d.reachable && d.tls_ok && d.tls_ungeprueft) {
                res.style.color='var(--warning)'; res.textContent='⚠ ' + srv + ' – ' + window.t('security.ad_tls_unverified').replace('{bis}', (d.tls_uebergang && d.tls_uebergang.bis) || '—');
            } else if (d.reachable && d.tls_ok === false) {
                res.style.color='var(--warning)'; res.textContent='⚠ ' + srv + ' – ' + window.t('security.ad_tls_fail').replace('{grund}', d.tls_error || '—');
            } else if (d.reachable) {
                res.style.color='var(--success)'; res.textContent='✓ ' + srv + ' – ' + window.t('security.ad_reachable') + ' · ' + window.t('security.ad_tls_ok');
            } else {
                res.style.color='var(--danger)'; res.textContent='✗ ' + window.t('security.ad_unreachable') + ': ' + (d.error || 'Timeout');
            }
        } catch(e) { res.style.color='var(--danger)'; res.textContent='✗ ' + e.message; }
    };

    document.addEventListener('DOMContentLoaded', function() {
        const secBtn = document.querySelector('[data-settings-tab="security"]');
        if (secBtn) secBtn.addEventListener('click', _adLoad);
    });
    _adLoad();
})();
