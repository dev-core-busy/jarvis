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
    async function _adLoad() {
        try {
            const r = await fetch('/api/auth/ad_status', {
                headers: { 'Authorization': 'Bearer ' + (window.JarvisSitzung.token()) }
            });
            const d = await r.json();
            document.getElementById('ad-server').value        = d.server        || '';
            document.getElementById('ad-domain').value        = d.domain        || '';
            document.getElementById('ad-allowed-users').value = d.allowed_users || '';
            document.getElementById('ad-allowed-group').value = d.allowed_group || '';
            document.getElementById('ad-knowledge-editors').value = d.knowledge_editors || '';
            document.getElementById('ad-knowledge-editors-group').value = d.knowledge_editors_group || '';
            document.getElementById('ad-internet-users').value = d.internet_users || '';
            document.getElementById('ad-internet-group').value = d.internet_group || '';
            document.getElementById('ad-bind-user').value = d.bind_user || '';
            document.getElementById('ad-bind-password').value = '';
            document.getElementById('ad-bind-pw-hint').textContent = window.t(d.bind_password_set ? 'security.ad_pw_saved' : 'security.ad_pw_none');
            document.getElementById('ad-admins').value = d.admins || '';
            document.getElementById('ad-admins-group').value = d.admins_group || '';
            var _sapU = document.getElementById('sap-allowed-users'); if (_sapU) _sapU.value = d.sap_users || '';
            var _sapG = document.getElementById('sap-allowed-group'); if (_sapG) _sapG.value = d.sap_group || '';
            var _vemU = document.getElementById('vemas-allowed-users'); if (_vemU) _vemU.value = d.vemas_users || '';
            var _vemG = document.getElementById('vemas-allowed-group'); if (_vemG) _vemG.value = d.vemas_group || '';
            var _mailU = document.getElementById('email-allowed-users'); if (_mailU) _mailU.value = d.email_users || '';
            var _mailG = document.getElementById('email-allowed-group'); if (_mailG) _mailG.value = d.email_group || '';
            var _trU = document.getElementById('tracks-allowed-users'); if (_trU) _trU.value = d.tracks_users || '';
            var _trG = document.getElementById('tracks-allowed-group'); if (_trG) _trG.value = d.tracks_group || '';
            var _jaU = document.getElementById('jiraassist-allowed-users'); if (_jaU) _jaU.value = d.jira_assist_users || '';
            var _amU = document.getElementById('aimouse-allowed-users'); if (_amU) _amU.value = d.aimouse_users || '';
            var _amG = document.getElementById('aimouse-allowed-group'); if (_amG) _amG.value = d.aimouse_group || '';
            var _jaG = document.getElementById('jiraassist-allowed-group'); if (_jaG) _jaG.value = d.jira_assist_group || '';
            var _xlU = document.getElementById('excel-allowed-users'); if (_xlU) _xlU.value = d.excel_users || '';
            var _xlG = document.getElementById('excel-allowed-group'); if (_xlG) _xlG.value = d.excel_group || '';
            var _csU = document.getElementById('claudesub-allowed-users'); if (_csU) _csU.value = d.claudesub_users || '';
            var _csG = document.getElementById('claudesub-allowed-group'); if (_csG) _csG.value = d.claudesub_group || '';
            // Token-Listen (Chips) aller AD-Felder neu aufbauen (nach dem Setzen aller Werte)
            ['ad-allowed-users','ad-allowed-group','ad-knowledge-editors','ad-knowledge-editors-group','ad-internet-users','ad-internet-group','ad-admins','ad-admins-group','sap-allowed-users','sap-allowed-group','vemas-allowed-users','vemas-allowed-group','email-allowed-users','email-allowed-group','tracks-allowed-users','tracks-allowed-group','jiraassist-allowed-users','jiraassist-allowed-group','aimouse-allowed-users','aimouse-allowed-group','excel-allowed-users','excel-allowed-group','claudesub-allowed-users','claudesub-allowed-group'].forEach(function(_id){ var _e=document.getElementById(_id); if(_e) _e.dispatchEvent(new Event('change')); });
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
    function _tl(key, liste) { return window.t(key).replace('{liste}', liste || ''); }

    // Ein Freigabe-Block: keiner eingetragen -> Warnung, Liste -> ok, Gruppe -> info
    function _freigabe(el, users, group, mode, pre) {
        if (!users && !group) _hinweis(el, 'warn', window.t(pre + '_none'));
        else if (mode === 'users') _hinweis(el, 'ok', _tl(pre + '_users', users));
        else if (mode === 'group') _hinweis(el, 'info', _tl(pre + '_group', group));
        else _hinweis(el, null);
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
        _freigabe(document.getElementById('ad-knowledge-status'), d.knowledge_editors,
                  d.knowledge_editors_group, d.knowledge_edit_mode, 'security.ad_ke');
        _freigabe(document.getElementById('ad-sap-status'), d.sap_users, d.sap_group,
                  d.sap_mode, 'security.ad_sap');
        _freigabe(document.getElementById('ad-internet-status'), d.internet_users,
                  d.internet_group, d.internet_mode, 'security.ad_inet');
        _freigabe(document.getElementById('ad-admins-status'), d.admins, d.admins_group,
                  d.admin_mode, 'security.ad_adm');
    }

    // ⚠ DEN SPEICHERN-KNOPF GIBT ES ZWEIMAL: einmal im Container "Verbindung
    // (Domain-Controller)", einmal am Ende von "alte Benutzerberechtigungen".
    // Beide loesen DENSELBEN Vorgang aus (der Koerper unten enthaelt beides),
    // deshalb werden beide gesperrt und BEIDE Statuszeilen beschrieben - sonst
    // meldet nur der eine das Ergebnis, und wer den anderen geklickt hat, sieht
    // nichts und haelt den Knopf fuer kaputt. Gesammelt wird ueber die
    // Klick-Marke bzw. die Klasse, nicht ueber eine Liste von Ids: ein dritter
    // Knopf waere damit von selbst mit versorgt.
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

    window._adSave = async function() {
        const btns = _saveKnoepfe();
        btns.forEach(function (b) { b.disabled = true; });
        _saveStatus(window.t('common.saving'), 'var(--text-muted)');
        try {
            const r = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (window.JarvisSitzung.token()) },
                body: JSON.stringify({
                    ad_server:        document.getElementById('ad-server').value.trim(),
                    ad_domain:        document.getElementById('ad-domain').value.trim(),
                    ad_allowed_users:          document.getElementById('ad-allowed-users').value.trim(),
                    ad_allowed_group:          document.getElementById('ad-allowed-group').value.trim(),
                    ad_knowledge_editors:      document.getElementById('ad-knowledge-editors').value.trim(),
                    ad_knowledge_editors_group: document.getElementById('ad-knowledge-editors-group').value.trim(),
                    ad_internet_users:         document.getElementById('ad-internet-users').value.trim(),
                    ad_internet_group:         document.getElementById('ad-internet-group').value.trim(),
                    ad_bind_user:              document.getElementById('ad-bind-user').value.trim(),
                    ad_bind_password:          document.getElementById('ad-bind-password').value,
                    ad_admins:                 document.getElementById('ad-admins').value.trim(),
                    ad_admins_group:           document.getElementById('ad-admins-group').value.trim(),
                    sap_allowed_users:         (document.getElementById('sap-allowed-users')||{}).value ? document.getElementById('sap-allowed-users').value.trim() : '',
                    sap_allowed_group:         (document.getElementById('sap-allowed-group')||{}).value ? document.getElementById('sap-allowed-group').value.trim() : '',
                    vemas_allowed_users:       (document.getElementById('vemas-allowed-users')||{}).value ? document.getElementById('vemas-allowed-users').value.trim() : '',
                    vemas_allowed_group:       (document.getElementById('vemas-allowed-group')||{}).value ? document.getElementById('vemas-allowed-group').value.trim() : '',
                    email_allowed_users:       (document.getElementById('email-allowed-users')||{}).value ? document.getElementById('email-allowed-users').value.trim() : '',
                    email_allowed_group:       (document.getElementById('email-allowed-group')||{}).value ? document.getElementById('email-allowed-group').value.trim() : '',
                    tracks_allowed_users:      (document.getElementById('tracks-allowed-users')||{}).value ? document.getElementById('tracks-allowed-users').value.trim() : '',
                    tracks_allowed_group:      (document.getElementById('tracks-allowed-group')||{}).value ? document.getElementById('tracks-allowed-group').value.trim() : '',
                    jira_assist_allowed_users: (document.getElementById('jiraassist-allowed-users')||{}).value ? document.getElementById('jiraassist-allowed-users').value.trim() : '',
                    jira_assist_allowed_group: (document.getElementById('jiraassist-allowed-group')||{}).value ? document.getElementById('jiraassist-allowed-group').value.trim() : '',
                    aimouse_allowed_users: (document.getElementById('aimouse-allowed-users')||{}).value ? document.getElementById('aimouse-allowed-users').value.trim() : '',
                    aimouse_allowed_group: (document.getElementById('aimouse-allowed-group')||{}).value ? document.getElementById('aimouse-allowed-group').value.trim() : '',
                    excel_allowed_users:       (document.getElementById('excel-allowed-users')||{}).value ? document.getElementById('excel-allowed-users').value.trim() : '',
                    excel_allowed_group:       (document.getElementById('excel-allowed-group')||{}).value ? document.getElementById('excel-allowed-group').value.trim() : '',
                    claudesub_allowed_users:   (document.getElementById('claudesub-allowed-users')||{}).value ? document.getElementById('claudesub-allowed-users').value.trim() : '',
                    claudesub_allowed_group:   (document.getElementById('claudesub-allowed-group')||{}).value ? document.getElementById('claudesub-allowed-group').value.trim() : '',
                })
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
