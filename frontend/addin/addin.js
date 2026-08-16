/* ═══════════════════════════════════════════════════════════════════════
   Outlook-Add-in – Aufgabenfenster
   ───────────────────────────────────────────────────────────────────────
   Bildet den Bereich /email ab (Postfach, Regeln, Protokoll) und ergaenzt
   das, wofuer es ein Add-in ueberhaupt braucht: die gerade markierte
   Nachricht mit einer Regel verarbeiten.

   DREI DINGE, DIE HIER ANDERS SIND ALS IN /email:

   1. **Eigene Anmeldung.** Eine Navigation aus Outlook traegt keinen
      Authorization-Kopf, und es gibt keine Sitzung, in die man
      hineinlaufen koennte. Das Fenster meldet sich deshalb selbst an
      (`POST /api/login`) und legt den Token im localStorage ab – dieselbe
      Schluesselkette wie die uebrigen Seiten, damit ein bereits an /chat
      angemeldeter Benutzer sich nicht erneut anmelden muss.
      **Ein SSO ueber Office/Entra scheidet aus**: das setzt eine
      Anwendungsregistrierung in Microsoft 365 voraus, und ein Exchange im
      Haus hat die nicht.

   2. **Office.js darf fehlen.** Die Bibliothek kommt aus dem Netz von
      Microsoft. Ist sie nicht erreichbar (Arbeitsplatz ohne Internet),
      bleibt das Fenster in vollem Umfang benutzbar – nur der Bezug zur
      markierten Nachricht entfaellt, und das steht dann im Klartext da.
      Ein Fenster, das wortlos weiss bleibt, waere der schlechtere Ausgang.

   3. **Der Nachrichtenbezug haengt am EWS-Kanal.** Die Kennung, die Outlook
      liefert (`item.itemId`), ist eine EWS-Kennung. Arbeitet das Postfach
      ueber IMAP, passt sie dort nicht – dann sagt das Fenster genau das,
      statt einen Knopf anzubieten, der in eine technische Fehlermeldung
      laeuft.

   Der Server ist und bleibt die Schranke: jeder Abruf haengt an
   `require_email_access`, jeder filtert auf den angemeldeten Benutzer, und
   der Regel-Lauf ist unprivilegiert. Alles hier ist Benutzerfuehrung.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    /* Gleiche Kette wie email_portal.js/sap_portal.js. Geschrieben wird auf
       den ersten Schluessel – ein Add-in-eigener Schluessel wuerde bedeuten,
       dass man sich zweimal anmeldet, obwohl es derselbe Server ist. */
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    var OFFICE_WARTE_MS = 4000;   // danach gilt: kein Outlook-Kontext

    var _status = null;      // /api/email/status
    var _regeln = [];
    var _bereiche = [];
    var _bereicheLang = '';
    var _konto = null;
    var _editId = null;      // 'neu' oder Regel-Id
    var _editHeim = null;    // Heimatplatz des wandernden Formulars
    var _office = null;      // { betreff, von, id, internetId } oder null
    var _officeGrund = '';   // warum kein Kontext
    var _tab = 'mail';
    var _laeuft = false;

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function sprache() { return (window._lang === 'en') ? 'en' : 'de'; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    /* Rueckfall im Arbeitsspeicher. NOETIG, nicht vorsorglich: das
       Aufgabenfenster laeuft in Outlook im Web in einem iframe, und dort ist der
       Speicher fremder Herkunft je nach Browsereinstellung gesperrt (auch bei
       strengen Cookie-Regeln, in privaten Fenstern und unter Safari-ITP).
       Ohne diesen Rueckfall wuerde `localStorage.setItem` still scheitern,
       `start()` faende keinen Token und zeigte wieder die Anmeldung – eine
       Endlosschleife mit RICHTIGEM Kennwort und ohne jede Fehlermeldung. */
    var _tokenRam = '';
    var _speicherGeht = true;

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try { var v = localStorage.getItem(TOKEN_KEYS[i]); if (v) return v; }
            catch (e) { _speicherGeht = false; }
        }
        return _tokenRam;
    }
    function tokenSetzen(v) {
        _tokenRam = v || '';
        try { localStorage.setItem(TOKEN_KEYS[0], v); }
        catch (e) { _speicherGeht = false; }
    }
    function tokenLoeschen() {
        _tokenRam = '';
        TOKEN_KEYS.forEach(function (k) {
            try { localStorage.removeItem(k); } catch (e) { }
        });
    }
    function speicherHinweis() {
        // Der Token lebt dann nur bis zum Schliessen des Fensters. Das ist
        // benutzbar, aber der Benutzer soll wissen, warum er sich morgen erneut
        // anmeldet – sonst haelt er es fuer einen Fehler.
        return _speicherGeht ? '' : T('addin.no_storage',
            'Hinweis: Dieser Browser erlaubt dem Fenster keinen dauerhaften Speicher. Die Anmeldung gilt nur, solange das Fenster offen ist.');
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }
    function zeit(ts) {
        if (!ts) return '–';
        try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return '–'; }
    }

    /* ── Server ───────────────────────────────────────────────────────── */
    function hole(url, opt) {
        return fetch(url, Object.assign({ headers: kopf() }, opt || {}))
            .then(function (r) {
                if (r.status === 401) {
                    // Abgelaufen: zurueck zur Anmeldung statt einer Seite
                    // voller technischer Meldungen.
                    tokenLoeschen();
                    zeigeLogin(T('addin.session_over', 'Die Anmeldung ist abgelaufen. Bitte erneut anmelden.'));
                    throw new Error('401');
                }
                return r.json().catch(function () { return {}; })
                    .then(function (d) {
                        if (!r.ok || d.ok === false) {
                            throw new Error(d.error || d.detail || ('HTTP ' + r.status));
                        }
                        return d;
                    });
            });
    }
    function sende(url, methode, daten) {
        return hole(url, {
            method: methode,
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: daten === undefined ? undefined : JSON.stringify(daten)
        });
    }

    /* ── Anmeldung ────────────────────────────────────────────────────── */
    function zeigeLogin(hinweis) {
        $('ad-app').classList.add('hidden');
        $('ad-login').classList.remove('hidden');
        $('ad-login-hint').textContent = hinweis ||
            T('addin.login_hint', 'Melde dich mit deinem Jarvis-Zugang an – denselben Daten wie im Browser.');
        var u = $('ad-user');
        if (u && !u.value) { try { u.focus(); } catch (e) { } }
    }
    function anmelden() {
        var u = ($('ad-user').value || '').trim();
        var p = $('ad-pass').value || '';
        var totp = ($('ad-totp').value || '').trim();
        if (!u || !p) {
            melde('ad-login-status', T('addin.login_need', 'Benutzername und Passwort eingeben.'), 'fehler');
            return;
        }
        var knopf = $('ad-do-login');
        knopf.disabled = true;
        melde('ad-login-status', T('login.connecting', 'Verbinde…'));
        var rumpf = { username: u, password: p };
        if (totp) rumpf.totp = totp;
        fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(rumpf)
        })
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { r: r, d: d }; });
            })
            .then(function (a) {
                knopf.disabled = false;
                if (a.d && a.d.requires_totp) {
                    $('ad-totp-wrap').classList.remove('hidden');
                    melde('ad-login-status', T('addin.login_totp', 'Bitte zusätzlich den Code aus deiner App eingeben.'));
                    try { $('ad-totp').focus(); } catch (e) { }
                    return;
                }
                if (!a.r.ok || !a.d || !a.d.success || !a.d.token) {
                    melde('ad-login-status',
                        (a.d && a.d.error) || T('login.failed', 'Anmeldung fehlgeschlagen'), 'fehler');
                    return;
                }
                tokenSetzen(a.d.token);
                $('ad-pass').value = '';
                $('ad-totp').value = '';
                melde('ad-login-status', speicherHinweis());
                start();
            })
            .catch(function () {
                knopf.disabled = false;
                melde('ad-login-status', T('login.server_error', 'Server nicht erreichbar'), 'fehler');
            });
    }

    /* ── Outlook-Kontext ──────────────────────────────────────────────── */
    function officeErmitteln() {
        /* Wartet begrenzt auf Office.js und liest die markierte Nachricht.
           Loest IMMER auf – ohne Kontext laeuft das Fenster im reinen
           Verwaltungsbetrieb weiter (siehe Modulkopf, Punkt 2). */
        return new Promise(function (fertig) {
            var erledigt = false;
            function ende(daten, grund) {
                if (erledigt) return;
                erledigt = true;
                _office = daten;
                _officeGrund = grund || '';
                fertig();
            }
            var uhr = setTimeout(function () {
                ende(null, T('addin.no_office',
                    'Outlook konnte nicht angebunden werden (office.js nicht erreichbar). Regeln, Postfach und Protokoll funktionieren trotzdem.'));
            }, OFFICE_WARTE_MS);

            // office.js wird mit `async` geladen, kann also NACH diesem Aufruf
            // eintreffen. Deshalb wird auf sein Erscheinen gewartet statt einmal
            // nachzusehen – ein einmaliger Blick haette bei langsamer Leitung
            // "kein Outlook" gemeldet, obwohl die Bibliothek Sekundenbruchteile
            // spaeter da war.
            function wennBereit() {
                if (typeof Office === 'undefined' || !Office.onReady) return false;
                Office.onReady(lesen);
                return true;
            }
            if (!wennBereit()) {
                var takt = setInterval(function () {
                    if (erledigt) { clearInterval(takt); return; }
                    if (wennBereit()) clearInterval(takt);
                }, 100);
                // Der Takt muss auch dann enden, wenn office.js nie kommt.
                setTimeout(function () { clearInterval(takt); }, OFFICE_WARTE_MS + 200);
            }

            function lesen() {
                clearTimeout(uhr);
                try {
                    var mb = Office.context && Office.context.mailbox;
                    var item = mb && mb.item;
                    if (!item) {
                        ende(null, T('addin.no_message',
                            'Es ist keine Nachricht geöffnet. Markiere eine E-Mail, um sie hier verarbeiten zu lassen.'));
                        return;
                    }
                    ende({
                        // itemId ist die EWS-Kennung – genau die, mit der der
                        // Server die Nachricht wiederfindet.
                        id: item.itemId || '',
                        internetId: item.internetMessageId || '',
                        betreff: item.subject || '',
                        von: (item.from && (item.from.emailAddress || item.from.displayName)) || ''
                    }, '');
                } catch (e) {
                    ende(null, T('addin.no_message',
                        'Es ist keine Nachricht geöffnet. Markiere eine E-Mail, um sie hier verarbeiten zu lassen.'));
                }
            }
        });
    }

    /* ── Start ────────────────────────────────────────────────────────── */
    function start() {
        if (!token()) { zeigeLogin(''); return; }
        fetch('/api/me', { headers: kopf() })
            .then(function (r) {
                if (r.status === 401) { tokenLoeschen(); zeigeLogin(''); return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (me) {
                if (!me) { zeigeLogin(T('addin.login_again', 'Bitte erneut anmelden.')); return; }
                // Fail-closed: fehlt das Feld (aelteres Backend), gilt "nicht
                // freigegeben".
                if (!(me.permissions && me.permissions.email)) {
                    $('ad-login').classList.add('hidden');
                    $('ad-app').classList.remove('hidden');
                    $('ad-global').innerHTML = '<div class="ad-warn">' + esc(T('addin.no_access',
                        'Dein Konto ist für den E-Mail-Bereich nicht freigeschaltet. Ein Administrator gibt ihn unter Einstellungen → Sicherheit → Berechtigungen → E-Mail-Zugriff frei.')) + '</div>';
                    document.querySelector('.ad-tabs').classList.add('hidden');
                    return;
                }
                zeigeApp();
            })
            .catch(function () {
                zeigeLogin(T('login.server_error', 'Server nicht erreichbar'));
            });
    }

    function zeigeApp() {
        $('ad-login').classList.add('hidden');
        $('ad-app').classList.remove('hidden');
        binde();
        ladeStatus().then(zeichneNachricht);
        ladeRegeln();
    }

    function binde() {
        if (binde._fertig) return;
        binde._fertig = true;
        document.querySelectorAll('.ad-tab').forEach(function (b) {
            b.addEventListener('click', function () { reiter(b.getAttribute('data-tab')); });
        });
        $('ad-logout').addEventListener('click', function () {
            // Abmeldesignal VOR dem Verwerfen des Tokens, sonst zaehlt der
            // Benutzer noch zwei Minuten als online (Muster aus sessions.js).
            try {
                fetch('/api/logout', { method: 'POST', headers: kopf(), keepalive: true });
            } catch (e) { }
            tokenLoeschen();
            _status = null; _regeln = []; _konto = null;
            zeigeLogin('');
        });
        $('ad-theme').addEventListener('click', function () {
            if (window.toggleTheme) { window.toggleTheme(); return; }
            document.body.classList.toggle('light');
            try {
                localStorage.setItem('jarvis_theme',
                    document.body.classList.contains('light') ? 'light' : 'dark');
            } catch (e) { }
        });
        $('ad-lang').addEventListener('click', function () {
            var neu = sprache() === 'de' ? 'en' : 'de';
            if (window.setLang) window.setLang(neu);
            $('ad-lang').textContent = neu.toUpperCase();
            // Der Bereichskatalog kommt uebersetzt vom SERVER – applyLang()
            // erreicht ihn nicht (gleiche Lage wie im SAP-Katalog). Also neu
            // holen und alles neu zeichnen.
            var stand = formularStand();
            ladeStatus().then(function () {
                zeichneNachricht();
                zeichneRegeln();
                formularStandSetzen(stand);
                if (_tab === 'log') ladeLog();
            });
        });
        $('ad-new-rule').addEventListener('click', function () { oeffneEditor('neu'); });
        $('ad-log-reload').addEventListener('click', ladeLog);
        $('ad-save-acct').addEventListener('click', speichereKonto);
        $('ad-test-acct').addEventListener('click', testeKonto);
        $('ad-del-acct').addEventListener('click', loescheKonto);
        $('ad-lang').textContent = sprache().toUpperCase();
    }

    function reiter(name) {
        _tab = name;
        document.querySelectorAll('.ad-tab').forEach(function (b) {
            b.classList.toggle('is-active', b.getAttribute('data-tab') === name);
        });
        document.querySelectorAll('.ad-pane').forEach(function (p) {
            p.classList.toggle('hidden', p.getAttribute('data-pane') !== name);
        });
        if (name === 'log') ladeLog();
        if (name === 'acct') fuelleKonto();
        window.scrollTo(0, 0);
    }

    /* ── Zustand / Marke ──────────────────────────────────────────────── */
    function ladeStatus() {
        return hole('/api/email/status?lang=' + sprache())
            .then(function (d) {
                _status = d;
                _konto = d.konto || null;
                _bereiche = d.bereiche || [];
                _bereicheLang = sprache();
                zeichneMarke();
                fuelleKonto();
                return d;
            })
            .catch(function (e) {
                if (String(e.message) === '401') return null;
                $('ad-global').innerHTML = '<div class="ad-warn">' + esc(e.message) + '</div>';
                return null;
            });
    }

    function zeichneMarke() {
        var box = $('ad-global');
        box.innerHTML = '';
        if (!_status) return;
        if (_status.skill_aktiv === false) {
            box.innerHTML = '<div class="ad-warn">' + esc(T('addin.skill_off',
                'Der E-Mail-Skill ist auf dem Server abgeschaltet. Ein Administrator schaltet ihn unter Einstellungen → Skills ein.')) + '</div>';
            return;
        }
        var s = _status.server || {};
        if (!s.ews && !s.imap) {
            box.innerHTML = '<div class="ad-warn">' + esc(T('mail.no_server',
                'Es ist kein Mailserver hinterlegt. Ein Administrator trägt ihn unter Einstellungen → E-Mail ein.')) + '</div>';
            return;
        }
        // DER AUSSETZER MUSS HIER STEHEN, nicht nur in /email: nach mehreren
        // fehlgeschlagenen Anmeldungen halten die Regeln an, damit das
        // Domaenenkonto nicht gesperrt wird. Wer ausschliesslich in Outlook
        // arbeitet – also die Zielgruppe dieses Fensters – saehe seine Regeln
        // sonst stillschweigend aufhoeren und suchte den Fehler in der Regel.
        if (_konto && _konto.ausgesetzt) {
            box.innerHTML = '<div class="ad-warn"><b>' +
                esc(T('mail.paused_head', 'Automatik ausgesetzt')) + '</b><br>' +
                esc(T('mail.paused_text',
                    'Die Anmeldung am Postfach ist mehrfach hintereinander fehlgeschlagen. ' +
                    'Damit dein Domänenkonto nicht gesperrt wird, melden sich die Regeln ' +
                    'nicht mehr an. Trag dein Kennwort neu ein und drücke „Verbindung ' +
                    'testen“ – gelingt die Anmeldung, läuft alles von selbst weiter.')) +
                (_konto.ausgesetzt_grund
                    ? '<br><br>' + esc(_konto.ausgesetzt_grund) : '') +
                '</div>';
        }
    }

    /* ── Reiter: markierte Nachricht ──────────────────────────────────── */
    function kontoBereit() {
        return !!(_konto && _konto.adresse && _konto.passwort_gesetzt && _konto.aktiv !== false);
    }
    function imapKonto() {
        /* Der Add-in-Weg braucht eine EWS-Kennung (siehe Modulkopf, Punkt 3).
           Massgeblich ist der WIRKSAME Kanal: die Wahl des Benutzers, sonst die
           Vorgabe des Administrators. Ein leeres Benutzerfeld heisst
           ausdruecklich "Vorgabe" – wer nur den eigenen Wert prueft, haelt ein
           reines IMAP-Haus faelschlich fuer EWS-faehig. */
        var s = (_status && _status.server) || {};
        var k = String((_konto && _konto.kanal) || s.kanal || 'auto').toLowerCase();
        if (k === 'imap') return true;
        if (k === 'ews') return false;
        // 'auto': EWS wird bevorzugt – ohne hinterlegtes EWS bleibt nur IMAP.
        return !s.ews;
    }

    function zeichneNachricht() {
        var box = $('ad-msg-box');
        if (!box) return;
        var teile = [];

        if (!_office) {
            teile.push('<div class="ad-empty">' + esc(_officeGrund ||
                T('addin.no_message', 'Es ist keine Nachricht geöffnet.')) + '</div>');
            box.innerHTML = teile.join('');
            return;
        }
        teile.push('<div class="ad-msg">' +
            '<div class="ad-msg-sub">' + esc(_office.betreff ||
                T('mail.log_nosubject', '(kein Betreff)')) + '</div>' +
            (_office.von ? '<div class="ad-msg-from">' + esc(_office.von) + '</div>' : '') +
            '</div>');

        if (!kontoBereit()) {
            teile.push('<div class="ad-empty">' + esc(T('addin.no_account',
                'Hinterlege zuerst dein Postfach im Reiter „Postfach".')) + '</div>');
            box.innerHTML = teile.join('');
            return;
        }
        if (imapKonto()) {
            teile.push('<div class="ad-warn" style="margin-top:10px;">' + esc(T('addin.imap_only',
                'Dieses Postfach arbeitet über IMAP. Die Kennung, die Outlook liefert, passt nur zum EWS-Zugang – eine einzelne Nachricht lässt sich hier deshalb nicht anstoßen. Die Regeln laufen davon unberührt nach Zeitplan.')) + '</div>');
            box.innerHTML = teile.join('');
            return;
        }
        if (!_office.id) {
            teile.push('<div class="ad-warn" style="margin-top:10px;">' + esc(T('addin.no_itemid',
                'Outlook hat für diese Nachricht keine Kennung geliefert (z.B. bei einem noch nicht gesendeten Entwurf).')) + '</div>');
            box.innerHTML = teile.join('');
            return;
        }

        var aktive = _regeln.filter(function (r) { return r.enabled !== false; });
        if (!aktive.length) {
            teile.push('<div class="ad-empty">' + esc(T('addin.no_rules',
                'Du hast noch keine aktive Regel. Lege im Reiter „Regeln" eine an.')) + '</div>');
            box.innerHTML = teile.join('');
            return;
        }
        teile.push('<div class="ad-field" style="margin-top:10px;">' +
            '<label>' + esc(T('addin.choose_rule', 'Mit dieser Regel verarbeiten')) + '</label>' +
            '<select id="ad-run-rule">' + aktive.map(function (r) {
                return '<option value="' + esc(r.id) + '">' + esc(r.name) + '</option>';
            }).join('') + '</select></div>');
        teile.push('<button class="ad-btn ad-btn-primary ad-btn-block" id="ad-run-msg">' +
            esc(T('addin.run_now', 'Jetzt verarbeiten')) + '</button>');
        teile.push('<p class="ad-hint" style="margin-top:6px;">' + esc(T('addin.run_hint',
            'Die Regel wird auf genau dieser Nachricht ausgeführt – die Aktionen sind echt (sie kann also tatsächlich antworten).')) + '</p>');
        teile.push('<p class="ad-status" id="ad-run-status" style="margin-top:8px;"></p>');
        teile.push('<div id="ad-run-result"></div>');
        box.innerHTML = teile.join('');
        $('ad-run-msg').addEventListener('click', verarbeiteNachricht);
    }

    function verarbeiteNachricht() {
        if (_laeuft) return;
        var rid = ($('ad-run-rule') || {}).value || '';
        if (!rid || !_office || !_office.id) return;
        var regel = _regeln.filter(function (r) { return r.id === rid; })[0] || {};
        if (!window.confirm(T('addin.run_confirm',
            'Diese Nachricht jetzt mit der Regel verarbeiten? Die Aktionen sind echt.') +
            '\n\n' + (regel.name || ''))) return;

        _laeuft = true;
        var knopf = $('ad-run-msg');
        knopf.disabled = true;
        $('ad-run-result').innerHTML = '';
        melde('ad-run-status', T('mail.testrun_wait', 'Der Lauf kann eine Weile dauern…'));
        sende('/api/email/rules/' + encodeURIComponent(rid) + '/run_message', 'POST',
            { msg_id: _office.id, internet_id: _office.internetId || '' })
            .then(function (d) { zeigeBericht(d.bericht, d.ok); })
            .catch(function (e) {
                if (String(e.message) === '401') return;
                melde('ad-run-status', e.message, 'fehler');
            })
            .then(function () {
                _laeuft = false;
                if ($('ad-run-msg')) $('ad-run-msg').disabled = false;
            });
    }

    function zeigeBericht(b, ok) {
        melde('ad-run-status', ok ? T('mail.testrun_ok', 'Lauf abgeschlossen.')
            : T('common.error', 'Fehler'), ok ? 'ok' : 'fehler');
        var ziel = $('ad-run-result');
        if (!ziel) return;
        if (!b) { ziel.innerHTML = ''; return; }
        if (b.fehler) {
            ziel.innerHTML = '<div class="ad-warn" style="margin-top:8px;">' + esc(b.fehler) + '</div>';
            return;
        }
        var akt = b.aktionen || [];
        if (!akt.length) {
            ziel.innerHTML = '<div class="ad-empty">' +
                esc(T('mail.testrun_none', 'Keine passende Nachricht gefunden.')) + '</div>';
            return;
        }
        ziel.innerHTML = akt.map(function (a) {
            return '<div class="ad-log' + (a.ok ? '' : ' is-bad') + '">' +
                '<div class="ad-log-res">' + esc(a.ergebnis || '') + '</div></div>';
        }).join('');
    }

    /* ── Reiter: Regeln ───────────────────────────────────────────────── */
    function ladeRegeln() {
        melde('ad-rules-status', T('common.loading', 'Lädt…'));
        return hole('/api/email/rules?lang=' + sprache())
            .then(function (d) {
                _regeln = d.regeln || [];
                if (d.bereiche) { _bereiche = d.bereiche; _bereicheLang = sprache(); }
                melde('ad-rules-status', '');
                zeichneRegeln();
                zeichneNachricht();   // die Regel-Auswahl haengt daran
            })
            .catch(function (e) {
                if (String(e.message) === '401') return;
                melde('ad-rules-status', e.message, 'fehler');
            });
    }

    function zeichneRegeln() {
        var box = $('ad-rules');
        if (!box) return;
        // Das wandernde Formular VOR dem Neuaufbau heimholen – sonst raeumt
        // innerHTML='' es mit ab (Lehre aus der /wissen-Vorschau).
        formularHeim();
        if (!_regeln.length) {
            box.innerHTML = '<div class="ad-empty">' +
                esc(T('mail.rules_empty', 'Noch keine Regel angelegt.')) + '</div>';
            return;
        }
        box.innerHTML = _regeln.map(function (r) {
            var meta = [];
            meta.push(esc(r.ordner || 'INBOX'));
            meta.push(esc(T('mail.every', 'alle') + ' ' + (r.intervall_min || 5) + ' min'));
            if (r.nur_ungelesen) meta.push(esc(T('mail.unread', 'nur ungelesen')));
            return '<div class="ad-card' + (r.enabled === false ? ' is-off' : '') +
                '" data-rule="' + esc(r.id) + '">' +
                '<div class="ad-card-row">' +
                '<div class="ad-card-main">' +
                '<div class="ad-card-name">' + esc(r.name) +
                (r.enabled === false ? '<span class="ad-badge">' +
                    esc(T('mail.disabled', 'aus')) + '</span>' : '') + '</div>' +
                '<div class="ad-card-meta">' + meta.join(' · ') + '</div>' +
                '</div>' +
                '<div class="ad-card-acts">' +
                '<button class="ad-mini" data-act="toggle" title="' +
                esc(r.enabled === false ? T('mail.resume', 'Fortsetzen') : T('mail.pause', 'Pausieren')) +
                '">' + (r.enabled === false ? '▶' : '⏸') + '</button>' +
                '<button class="ad-mini" data-act="test" title="' +
                esc(T('mail.testrun', 'Testlauf')) + '">⟳</button>' +
                '<button class="ad-mini" data-act="edit" title="' +
                esc(T('common.edit', 'Bearbeiten')) + '">✎</button>' +
                '<button class="ad-mini is-danger" data-act="del" title="' +
                esc(T('common.delete', 'Löschen')) + '">✕</button>' +
                '</div></div></div>';
        }).join('');
        box.querySelectorAll('.ad-mini').forEach(function (b) {
            b.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var id = b.closest('.ad-card').getAttribute('data-rule');
                var act = b.getAttribute('data-act');
                if (act === 'edit') oeffneEditor(id);
                else if (act === 'del') loescheRegel(id);
                else if (act === 'test') testlauf(id);
                else if (act === 'toggle') schalteRegel(id);
            });
        });
        if (_editId && _editId !== 'neu') formularUnter(_editId);
    }

    /* Ein einziger Formular-Container, der unter die angeklickte Karte
       wandert. Zwei Container haetten zwei Wege zum Speichern bedeutet. */
    function formularHeim() {
        var f = $('ad-rule-edit');
        if (!f) return;
        if (_editHeim && f.parentNode !== _editHeim) _editHeim.appendChild(f);
    }
    function formularUnter(id) {
        var f = $('ad-rule-edit');
        var karte = document.querySelector('.ad-card[data-rule="' + id + '"]');
        if (!f || !karte) return;
        // Heimatplatz NUR beim ersten Verschieben merken – ein erneutes
        // Auslesen wuerde die verschobene Position als "Heimat" merken.
        if (!_editHeim) _editHeim = f.parentNode;
        karte.appendChild(f);
        f.classList.add('ad-edit');
    }

    function bereichsWahl(gewaehlt) {
        var frei = _bereiche.filter(function (b) { return b.freigegeben; });
        if (!frei.length) {
            return '<p class="ad-hint">' + esc(T('mail.no_areas',
                'Ein Administrator hat noch keine Werkzeug-Bereiche freigegeben.')) + '</p>';
        }
        return '<div class="ad-tools" id="ad-f-areas">' + frei.map(function (b) {
            var an = b.pflicht || gewaehlt.indexOf(b.id) >= 0;
            return '<label class="' + (b.pflicht ? 'is-locked' : '') + '">' +
                '<input type="checkbox" value="' + esc(b.id) + '"' +
                (an ? ' checked' : '') + (b.pflicht ? ' disabled' : '') + '>' +
                '<span><b>' + esc(b.name) + '</b><br>' + esc(b.hinweis || '') + '</span></label>';
        }).join('') + '</div>';
    }

    function oeffneEditor(id) {
        // Zweiter Klick auf dieselbe Regel schliesst wieder – ein "Bearbeiten"
        // als Einbahnstrasse ist eine Zumutung im schmalen Fenster.
        if (_editId === id) { schliesseEditor(); return; }
        _editId = id;
        var r = (id === 'neu') ? { bereiche: ['mail'], intervall_min: 5, ordner: 'INBOX',
                                   nur_ungelesen: true, enabled: true, max_je_lauf: 5 }
            : (_regeln.filter(function (x) { return x.id === id; })[0] || {});
        var g = _status && _status.grenzen || {};
        var f = $('ad-rule-edit');
        f.classList.remove('hidden');
        f.innerHTML =
            '<div class="ad-field"><label>' + esc(T('mail.f_name', 'Name')) + '</label>' +
            '<input type="text" id="ad-f-name" value="' + esc(r.name || '') + '"></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_prompt', 'Prompt')) + '</label>' +
            '<textarea id="ad-f-prompt" placeholder="' +
            esc(T('mail.f_prompt_ph', 'Beschreibe, was mit passenden Nachrichten geschehen soll…')) +
            '">' + esc(r.prompt || '') + '</textarea>' +
            '<span class="ad-hint">' + esc(T('mail.f_prompt_hint',
                'Das Modell entscheidet anhand dieses Textes, was zu tun ist.')) + '</span></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_folder', 'Ordner')) + '</label>' +
            '<input type="text" id="ad-f-folder" value="' + esc(r.ordner || 'INBOX') + '"></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_interval', 'Intervall (Minuten)')) + '</label>' +
            '<input type="number" id="ad-f-interval" min="' + (g.min_intervall || 1) +
            '" max="' + (g.max_intervall || 1440) + '" value="' + (r.intervall_min || 5) + '"></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_max', 'Höchstens je Lauf')) + '</label>' +
            '<input type="number" id="ad-f-max" min="1" max="' + (g.max_je_lauf || 10) +
            '" value="' + (r.max_je_lauf || 5) + '"></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_from', 'Nur von (Filter)')) + '</label>' +
            '<input type="text" id="ad-f-from" value="' + esc(r.von_filter || '') + '"></div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_subject', 'Nur Betreff enthält')) + '</label>' +
            '<input type="text" id="ad-f-subject" value="' + esc(r.betreff_filter || '') + '"></div>' +

            '<label class="ad-check"><input type="checkbox" id="ad-f-unread"' +
            (r.nur_ungelesen !== false ? ' checked' : '') + '><span>' +
            esc(T('mail.f_unread', 'Nur ungelesene Nachrichten')) + '</span></label>' +

            '<label class="ad-check" style="margin-top:6px;"><input type="checkbox" id="ad-f-read"' +
            (r.markiere_gelesen ? ' checked' : '') + '><span>' +
            esc(T('mail.f_read', 'Nach Bearbeitung als gelesen markieren')) + '</span></label>' +

            '<div class="ad-field" style="margin-top:10px;"><label>' +
            esc(T('mail.f_areas', 'Werkzeug-Bereiche')) + '</label>' +
            bereichsWahl(r.bereiche || ['mail']) + '</div>' +

            '<div class="ad-row">' +
            '<button class="ad-btn ad-btn-primary" id="ad-f-save">' +
            esc(id === 'neu' ? T('mail.f_create', 'Anlegen') : T('common.save', 'Speichern')) + '</button>' +
            '<button class="ad-btn" id="ad-f-cancel">' + esc(T('common.cancel', 'Abbrechen')) + '</button>' +
            '</div><p class="ad-status" id="ad-f-status" style="margin-top:6px;"></p>';

        if (id === 'neu') { formularHeim(); f.classList.remove('ad-edit'); }
        else formularUnter(id);
        $('ad-f-save').addEventListener('click', speichereRegel);
        $('ad-f-cancel').addEventListener('click', schliesseEditor);
        try { f.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) { }
    }

    function schliesseEditor() {
        _editId = null;
        formularHeim();
        var f = $('ad-rule-edit');
        f.classList.add('hidden');
        f.classList.remove('ad-edit');
        f.innerHTML = '';
    }

    /* Sprachwechsel baut das Formular neu auf – ohne Sicherung waere ein
       Klick auf DE/EN mitten im Tippen Datenverlust. */
    var FORM_FELDER = ['ad-f-name', 'ad-f-prompt', 'ad-f-folder', 'ad-f-interval',
        'ad-f-max', 'ad-f-from', 'ad-f-subject'];
    function formularStand() {
        if (!_editId || !$('ad-f-name')) return null;
        var s = { id: _editId, werte: {}, haken: {}, bereiche: [] };
        FORM_FELDER.forEach(function (f) { s.werte[f] = ($(f) || {}).value || ''; });
        ['ad-f-unread', 'ad-f-read'].forEach(function (f) {
            s.haken[f] = !!(($(f) || {}).checked);
        });
        document.querySelectorAll('#ad-f-areas input[type=checkbox]').forEach(function (cb) {
            if (cb.checked) s.bereiche.push(cb.value);
        });
        return s;
    }
    function formularStandSetzen(s) {
        if (!s) return;
        if (_editId !== s.id) { oeffneEditor(s.id); }
        if (!$('ad-f-name')) return;
        FORM_FELDER.forEach(function (f) { if ($(f)) $(f).value = s.werte[f]; });
        Object.keys(s.haken).forEach(function (f) { if ($(f)) $(f).checked = s.haken[f]; });
        document.querySelectorAll('#ad-f-areas input[type=checkbox]').forEach(function (cb) {
            if (!cb.disabled) cb.checked = s.bereiche.indexOf(cb.value) >= 0;
        });
    }

    function formularWerte() {
        var b = ['mail'];
        document.querySelectorAll('#ad-f-areas input[type=checkbox]').forEach(function (cb) {
            if (cb.checked && b.indexOf(cb.value) < 0) b.push(cb.value);
        });
        return {
            name: ($('ad-f-name').value || '').trim(),
            prompt: ($('ad-f-prompt').value || '').trim(),
            ordner: ($('ad-f-folder').value || 'INBOX').trim(),
            intervall_min: parseInt($('ad-f-interval').value, 10) || 5,
            max_je_lauf: parseInt($('ad-f-max').value, 10) || 5,
            von_filter: ($('ad-f-from').value || '').trim(),
            betreff_filter: ($('ad-f-subject').value || '').trim(),
            nur_ungelesen: !!$('ad-f-unread').checked,
            markiere_gelesen: !!$('ad-f-read').checked,
            bereiche: b
        };
    }

    function speichereRegel() {
        var w = formularWerte();
        var neu = _editId === 'neu';
        melde('ad-f-status', T('common.saving', 'Speichert…'));
        var p = neu ? sende('/api/email/rules', 'POST', w)
            : sende('/api/email/rules/' + encodeURIComponent(_editId), 'PUT', w);
        p.then(function () {
            melde('ad-f-status', T('mail.rule_saved', 'Regel gespeichert.'), 'ok');
            schliesseEditor();
            ladeRegeln();
        }).catch(function (e) {
            if (String(e.message) === '401') return;
            melde('ad-f-status', e.message, 'fehler');
        });
    }

    function loescheRegel(id) {
        var r = _regeln.filter(function (x) { return x.id === id; })[0] || {};
        if (!window.confirm(T('mail.rule_del_confirm', 'Diese Regel wirklich löschen?') +
            '\n\n' + (r.name || ''))) return;
        sende('/api/email/rules/' + encodeURIComponent(id), 'DELETE')
            .then(function () {
                if (_editId === id) schliesseEditor();
                melde('ad-rules-status', T('mail.rule_deleted', 'Regel gelöscht.'), 'ok');
                ladeRegeln();
            })
            .catch(function (e) {
                if (String(e.message) === '401') return;
                melde('ad-rules-status', e.message, 'fehler');
            });
    }

    function schalteRegel(id) {
        var r = _regeln.filter(function (x) { return x.id === id; })[0];
        if (!r) return;
        // NUR das eine Feld senden – ein Merge mit dem Formularstand wuerde
        // sonst offene Eingaben festschreiben (Muster der Rollen-Agenten).
        sende('/api/email/rules/' + encodeURIComponent(id), 'PUT',
            { enabled: r.enabled === false })
            .then(ladeRegeln)
            .catch(function (e) {
                if (String(e.message) === '401') return;
                melde('ad-rules-status', e.message, 'fehler');
            });
    }

    function testlauf(id) {
        if (_laeuft) return;
        _laeuft = true;
        melde('ad-rules-status', T('mail.testrun_wait', 'Der Lauf kann eine Weile dauern…'));
        sende('/api/email/rules/' + encodeURIComponent(id) + '/run', 'POST')
            .then(function (d) {
                var b = d.bericht || {};
                if (b.fehler) { melde('ad-rules-status', b.fehler, 'fehler'); }
                else if (!(b.aktionen || []).length) {
                    melde('ad-rules-status', T('mail.testrun_none', 'Keine passende Nachricht gefunden.'));
                } else {
                    melde('ad-rules-status',
                        T('mail.testrun_ok', 'Lauf abgeschlossen.') + ' ' +
                        (b.aktionen[0].ergebnis || ''), d.ok ? 'ok' : 'fehler');
                }
                ladeRegeln();
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-rules-status', e.message, 'fehler');
            })
            .then(function () { _laeuft = false; });
    }

    /* ── Reiter: Postfach ─────────────────────────────────────────────── */
    function fuelleKonto() {
        if (!$('ad-adresse')) return;
        var k = _konto || {};
        // Nur belegen, wenn der Benutzer nicht gerade tippt – sonst
        // ueberschriebe ein Statuslauf die Eingabe.
        if (document.activeElement && document.activeElement.closest &&
            document.activeElement.closest('[data-pane="acct"]')) return;
        $('ad-adresse').value = k.adresse || '';
        $('ad-benutzer').value = k.benutzer || '';
        $('ad-kanal').value = k.kanal || '';
        $('ad-ord-eingang').value = k.ordner_eingang || '';
        $('ad-ord-entwuerfe').value = k.ordner_entwuerfe || '';
        $('ad-ord-gesendet').value = k.ordner_gesendet || '';
        $('ad-aktiv').checked = k.aktiv !== false;
        $('ad-pw-hint').textContent = k.passwort_gesetzt
            ? T('mail.pw_set', 'Ein Kennwort ist hinterlegt.')
            : T('mail.pw_unset', 'Noch kein Kennwort hinterlegt.');
    }

    function speichereKonto() {
        var d = {
            adresse: ($('ad-adresse').value || '').trim(),
            benutzer: ($('ad-benutzer').value || '').trim(),
            kanal: $('ad-kanal').value || '',
            ordner_eingang: ($('ad-ord-eingang').value || '').trim(),
            ordner_entwuerfe: ($('ad-ord-entwuerfe').value || '').trim(),
            ordner_gesendet: ($('ad-ord-gesendet').value || '').trim(),
            aktiv: !!$('ad-aktiv').checked
        };
        // LEERES Kennwortfeld heisst "unveraendert" – wird es mitgesendet,
        // loescht jedes Speichern der uebrigen Felder das Kennwort.
        var pw = $('ad-passwort').value || '';
        if (pw) d.passwort = pw;
        melde('ad-acct-status', T('common.saving', 'Speichert…'));
        sende('/api/email/account', 'POST', d)
            .then(function (a) {
                _konto = a.konto || null;
                $('ad-passwort').value = '';
                melde('ad-acct-status', T('mail.acct_saved', 'Postfach gespeichert.'), 'ok');
                fuelleKonto();
                zeichneNachricht();
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-acct-status', e.message, 'fehler');
            });
    }

    function testeKonto() {
        melde('ad-acct-status', T('mail.testing', 'Teste Verbindung…'));
        sende('/api/email/test', 'POST')
            .then(function (d) {
                var e = d.ergebnis || {};
                melde('ad-acct-status', T('mail.test_ok', 'Verbindung steht.') +
                    (e.kanal ? ' (' + e.kanal.toUpperCase() + ')' : ''), 'ok');
                return ladeStatus().then(zeichneNachricht);
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-acct-status', e.message, 'fehler');
            });
    }

    function loescheKonto() {
        if (!window.confirm(T('mail.acct_del_confirm',
            'Zugangsdaten wirklich entfernen? Deine Regeln bleiben erhalten, laufen aber nicht mehr.'))) return;
        sende('/api/email/account', 'DELETE')
            .then(function () {
                melde('ad-acct-status', T('mail.acct_deleted', 'Zugangsdaten entfernt.'), 'ok');
                return ladeStatus().then(zeichneNachricht);
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-acct-status', e.message, 'fehler');
            });
    }

    /* ── Reiter: Protokoll ────────────────────────────────────────────── */
    function ladeLog() {
        melde('ad-log-status', T('common.loading', 'Lädt…'));
        hole('/api/email/log?limit=40')
            .then(function (d) {
                var e = d.eintraege || [];
                melde('ad-log-status', e.length
                    ? (e.length + ' ' + T('mail.log_entries', 'Einträge')) : '');
                $('ad-log').innerHTML = e.length ? e.map(function (x) {
                    return '<div class="ad-log' + (x.ok === false ? ' is-bad' : '') + '">' +
                        '<div class="ad-log-time">' + esc(zeit(x.ts)) + ' · ' +
                        esc(x.regel || '') + '</div>' +
                        '<div><b>' + esc(x.mail_betreff ||
                            T('mail.log_nosubject', '(kein Betreff)')) + '</b></div>' +
                        '<div class="ad-log-res">' + esc(x.ergebnis || '') + '</div></div>';
                }).join('') : '<div class="ad-empty">' +
                    esc(T('mail.log_empty', 'Noch keine Läufe protokolliert.')) + '</div>';
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-log-status', e.message, 'fehler');
            });
    }

    /* ── Einstieg ─────────────────────────────────────────────────────── */
    function los() {
        if ($('ad-do-login')) {
            $('ad-do-login').addEventListener('click', anmelden);
            ['ad-user', 'ad-pass', 'ad-totp'].forEach(function (id) {
                var e = $(id);
                if (e) e.addEventListener('keydown', function (ev) {
                    if (ev.key === 'Enter') anmelden();
                });
            });
        }
        // Erst den Outlook-Kontext (mit Zeitgrenze), dann anmelden/starten:
        // die Nachricht steht damit sofort da, statt nachzuflackern.
        officeErmitteln().then(start);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', los);
    } else { los(); }
})();
