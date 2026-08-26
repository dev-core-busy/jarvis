/* ═══════════════════════════════════════════════════════════════════════
   Outlook-Add-in – Aufgabenfenster
   ───────────────────────────────────────────────────────────────────────
   Bildet den Bereich /email ab (Postfach, Regeln, Protokoll) und ergaenzt
   das, wofuer es ein Add-in ueberhaupt braucht: die gerade markierte
   Nachricht mit einer Regel verarbeiten.

   DREI DINGE, DIE HIER ANDERS SIND ALS IN /email:

   1. **Anmeldung ohne Kennwort – EINMAL angelernt.** Eine Navigation aus
      Outlook traegt keinen Authorization-Kopf, und es gibt keine Sitzung,
      in die man hineinlaufen koennte. Seit 2026-08-17 holt das Fenster
      deshalb ein **Exchange-Identity-Token** (`getUserIdentityTokenAsync`)
      und schickt es an `POST /api/addin/sso`; der Server prueft die
      Signatur des Exchange und weiss damit, welches Postfach dranhaengt.
      **Das Token nennt keine Mailadresse** – die Zuordnung zum Jarvis-Konto
      entsteht bei der ERSTEN Anmeldung: dort wird das Token mitgeschickt
      (`addin_token` an `POST /api/login`) und die Verknuepfung gespeichert.
      Ab dann meldet sich das Fenster von selbst an.
      **Ein SSO ueber Office/Entra scheidet aus**: das setzt eine
      Anwendungsregistrierung in Microsoft 365 voraus, und ein Exchange im
      Haus hat die nicht. Fuer Exchange **on-premises** sind die
      Identity-Token dagegen ausdruecklich weiter unterstuetzt (fuer
      Exchange Online hat Microsoft sie abgeschaltet) – deshalb genau dieser
      Weg und kein anderer.
      Der Token liegt weiterhin im localStorage, gleiche Schluesselkette wie
      die uebrigen Seiten: wer schon an /chat angemeldet ist, kommt ohne
      alles herein.

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
    var _updServer = '';     // Manifest-Version des Servers, sobald bekannt
    var _officeDa = false;   // Office.context.mailbox war erreichbar. NICHT
                             // dasselbe wie `_office`: das ist null, sobald
                             // keine Nachricht markiert ist – wir liefen dann
                             // trotzdem in Outlook. Genau diese Unterscheidung
                             // braucht `versionPruefen()`.
    var _idToken = '';       // Exchange-Identity-Token (fuer die Anmeldung)
    var _ssoGrund = '';      // warum SSO nicht griff – nur zur Anzeige
    var _ssoProbiert = false; // Endlosschleife-Bremse: hoechstens EIN
                              // kennwortloser Versuch je Fensterlauf
    var _stile = [];         // benannte Antwort-Stile des Postfachs
    var _stilEdit = null;    // welcher Stil ist offen ('neu' = neuer Stil)
    var _signaturen = [];    // benannte Signaturen des Postfachs
    var _sigEdit = null;     // welche Signatur ist offen ('neu' = neue)
    // Wahl in der Antwort-Vorschau. Beide leer = "Vorgabe des Postfachs";
    // '-' bei der Signatur heisst ausdruecklich KEINE. Der Unterschied ist
    // wichtig: leer faellt auf den Standard, '-' nicht.
    var _sigWahl = '';
    var _fmtWahl = '';
    var _stilWahl = '';      // im Nachrichten-Reiter gewaehlter Stil. Muss
                             // ausserhalb liegen: `zeichneNachricht()` baut
                             // den Reiter bei jedem Statuslauf und bei jedem
                             // Sprachwechsel neu auf.
    var _vorschlag = null;   // {text, an, betreff} – Antwort-Vorschlag,
                             // solange er nicht gesendet/verworfen ist
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
                    // Abgelaufen. ZUERST die kennwortlose Anmeldung erneut
                    // versuchen – ist das Postfach verknuepft, merkt der
                    // Benutzer vom Ablauf nichts. Erst wenn das scheitert,
                    // kommt die Anmeldemaske (statt einer Seite voller
                    // technischer Meldungen).
                    tokenLoeschen();
                    ssoVersuch().then(function (ok) {
                        if (ok && token()) { zeigeApp(); return; }
                        zeigeLogin(T('addin.session_over',
                            'Die Anmeldung ist abgelaufen. Bitte erneut anmelden.'));
                    });
                    throw new Error('401');
                }
                return r.json().catch(function () { return {}; })
                    .then(function (d) {
                        if (!r.ok || d.ok === false) {
                            var f = new Error(d.error || d.detail || ('HTTP ' + r.status));
                            // Der Status muss mit: ein Aufrufer, der auf eine
                            // Rueckfrage umschalten will (409 = wuerde etwas
                            // ueberschreiben), koennte das sonst nur am
                            // Meldungstext erkennen - und der darf sich aendern.
                            f.status = r.status;
                            throw f;
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
            // Bewusst OHNE Produktnamen: der Text wird per textContent gesetzt,
            // branding.js kaeme also nicht mehr heran (es brandet nur Markup,
            // das beim Anwenden schon dasteht). Ein markenneutraler Satz ist
            // hier ausserdem der praezisere.
            T('addin.login_hint', 'Melde dich mit deinem gewohnten Zugang an – denselben Daten wie im Browser.');
        // Anbindungs-Zustand ausweisen. Ohne diese Zeile ist von aussen nicht
        // zu unterscheiden, ob office.js geladen wurde – und genau das ist die
        // erste Frage, wenn sich das Fenster in Outlook seltsam verhaelt.
        // Der SSO-Grund hat VORRANG: er erklaert, warum hier ueberhaupt noch
        // eine Anmeldung steht.
        if (_ssoGrund) {
            melde('ad-login-office', _ssoGrund);
        } else if (_office) {
            melde('ad-login-office',
                T('addin.office_ok', 'Mit Outlook verbunden.'), 'ok');
        } else {
            melde('ad-login-office', _officeGrund || '');
        }
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
        // FELDNAME IST `totp_code` – so liest ihn `/api/login`, und so senden
        // ihn app.js, chat.js, userchat.js und wissen.js. Das Fenster schickte
        // `totp` und damit ins Leere: der Server sah keinen Code, antwortete
        // erneut `requires_totp` – eine Anmeldeschleife, aus der niemand
        // herauskam (gefunden 2026-08-17 beim Bau der kennwortlosen Anmeldung).
        if (totp) rumpf.totp_code = totp;
        // DIE ERSTANMELDUNG IST DIE ANLERNPHASE: das Exchange-Token geht mit,
        // der Server verknuepft das Postfach mit diesem Konto, und ab dem
        // naechsten Start entfaellt die Anmeldung. Ohne Token laeuft alles
        // unveraendert weiter – dann bleibt es eben bei der Anmeldung.
        if (_idToken) rumpf.addin_token = _idToken;
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
                var mb = null;
                try { mb = Office.context && Office.context.mailbox; } catch (e) { mb = null; }
                _officeDa = !!mb;
                // Das Identity-Token ist die Grundlage der kennwortlosen
                // Anmeldung und wird deshalb IMMER geholt – auch wenn gerade
                // keine Nachricht markiert ist. Es haengt am Postfach, nicht
                // an der Nachricht. Eigene Zeitgrenze: die aeussere ist oben
                // schon abgeraeumt, ein haengender Aufruf duerfte das Fenster
                // sonst dauerhaft blockieren.
                idTokenHolen(mb).then(function () {
                    try {
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
                });
            }
        });
    }

    /* Exchange-Identity-Token holen. Loest IMMER auf – ohne Token laeuft das
       Fenster mit der gewohnten Anmeldung weiter, und `_ssoGrund` sagt, warum.

       `getUserIdentityTokenAsync` gibt es erst ab Mailbox 1.3 und NICHT in
       Exchange Online (dort hat Microsoft die Token abgeschaltet); beides
       faengt der Zweig unten ab, statt eine Ausnahme bis in den Startlauf
       durchschlagen zu lassen. Eigene Zeitgrenze, weil die aeussere zu diesem
       Zeitpunkt schon abgeraeumt ist. */
    function idTokenHolen(mb) {
        return new Promise(function (fertig) {
            var fertigGemeldet = false;
            function ende(grund) {
                if (fertigGemeldet) return;
                fertigGemeldet = true;
                _ssoGrund = grund || '';
                fertig();
            }
            setTimeout(function () {
                ende(T('addin.sso_timeout',
                    'Der Exchange hat kein Anmelde-Token geliefert (Zeitüberschreitung).'));
            }, 3000);
            try {
                if (!mb || typeof mb.getUserIdentityTokenAsync !== 'function') {
                    ende(T('addin.sso_unsupported',
                        'Dieses Postfach liefert kein Anmelde-Token (nur Exchange im eigenen Haus kann das).'));
                    return;
                }
                mb.getUserIdentityTokenAsync(function (r) {
                    if (r && r.status === 'succeeded' && r.value) {
                        _idToken = String(r.value);
                        ende('');
                    } else {
                        ende((r && r.error && r.error.message) ||
                            T('addin.sso_failed', 'Der Exchange hat kein Anmelde-Token ausgestellt.'));
                    }
                });
            } catch (e) {
                ende(String((e && e.message) || e));
            }
        });
    }

    /* Kennwortlose Anmeldung versuchen. Liefert true, wenn ein Token kam.
       Ein Fehlschlag ist der NORMALFALL beim ersten Start (das Postfach ist
       noch keinem Konto zugeordnet) – deshalb keine Fehlermeldung, sondern
       ein Hinweis auf dem Anmeldebildschirm. */
    function ssoVersuch() {
        if (!_idToken) return Promise.resolve(false);
        return fetch('/api/addin/sso', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: _idToken })
        })
            .then(function (r) { return r.json().catch(function () { return {}; }); })
            .then(function (d) {
                if (d && d.ok && d.token) {
                    tokenSetzen(d.token);
                    return true;
                }
                // `unbekannt` heisst: einmal anmelden, danach geht es von selbst.
                _ssoGrund = (d && d.unbekannt)
                    ? T('addin.sso_first', 'Einmalige Anmeldung – danach meldet sich das Fenster von selbst an.')
                    : ((d && d.error) || '');
                return false;
            })
            .catch(function () { return false; });
    }

    /* ── Veraltetes Manifest ausweisen ────────────────────────────────
       DAS IST DER EINE TEIL, DER SICH NICHT VON SELBST AKTUALISIERT.
       Aufgabenfenster, Logik und CSS liegen auf dem Server, werden mit
       `no-store` ausgeliefert und erreichen jedes installierte Add-in beim
       naechsten Oeffnen. Das MANIFEST dagegen (Menueband, Berechtigungen,
       Anforderungssatz, URLs) wird von Microsoft bei einer Installation aus
       Datei oder URL NIE aktualisiert – automatische Updates gibt es nur fuer
       Add-ins aus dem Store. `New-App -Url` holt das Manifest einmalig beim
       Installieren, ein `Update-App` gibt es nicht.

       Office.js hat keine Schnittstelle, mit der ein Fenster die Version
       seines EIGENEN Manifests lesen koennte. Deshalb steckt sie im
       Abfrageteil der Taskpane-URL (`?mv=`, gesetzt in backend/addin.py) und
       wird hier gegen `GET /api/addin/version` verglichen.

       NICHTS BEHAUPTEN, WAS WIR NICHT WISSEN – dieselbe Regel wie beim
       Trenner "Neue Sitzung" und beim Audit-Filter. Drei Faelle:
         mv vorhanden und kleiner  → belegt veraltet, Versionen nennen
         mv fehlt, aber Outlook da → belegt aelter als diese Pruefung, aber
                                     WELCHE Fassung, wissen wir nicht
         mv fehlt, kein Outlook    → das ist ein direkter Browseraufruf.
                                     KEIN Band. */
    function versionKleiner(a, b) {
        // Segmentweise NUMERISCH. Ein String-Vergleich haette "1.10" fuer
        // kleiner als "1.9" gehalten – und der Fehler faellt erst beim
        // zehnten Manifest auf.
        var x = String(a || '').split('.'), y = String(b || '').split('.');
        var n = Math.max(x.length, y.length);
        for (var i = 0; i < n; i++) {
            var xi = parseInt(x[i], 10) || 0, yi = parseInt(y[i], 10) || 0;
            if (xi !== yi) return xi < yi;
        }
        return false;
    }
    function manifestVersion() {
        // Der Wert kommt aus der URL, ist also Fremdeingabe. Er wird nicht nur
        // maskiert, sondern zuerst auf seine FORM geprueft: ein Muellwert in
        // der Anzeige ist auch keine Information, und "unbekannt" ist die
        // ehrlichere Auskunft.
        var m = /[?&]mv=([^&]*)/.exec(location.search || '');
        var v = m ? decodeURIComponent(m[1]) : '';
        return /^[0-9]+(\.[0-9]+){0,3}$/.test(v) ? v : '';
    }
    /* Zeichnen ist vom Abruf GETRENNT, damit der Sprachwechsel das Band
       uebersetzen kann, ohne den Server ein zweites Mal zu fragen: der Text
       wird per innerHTML gesetzt, `applyLang()` erreicht ihn also nicht
       (gleiche Lage wie beim Bereichskatalog). */
    function zeichneUpdBand() {
        var kasten = $('ad-upd');
        if (!kasten) return;
        var installiert = manifestVersion();
        var server = _updServer;
        var zeigen = server && (installiert ? versionKleiner(installiert, server)
                                            : _officeDa);
        if (!zeigen) { kasten.classList.add('hidden'); kasten.innerHTML = ''; return; }
        var text;
        if (installiert) {
            text = T('addin.upd_text',
                'Installiert ist {alt}, auf dem Server liegt {neu}. Es funktioniert alles weiter – es fehlen nur Änderungen am Menüband und an den Berechtigungen.')
                .replace(/\{alt\}/g, installiert).replace(/\{neu\}/g, server);
        } else {
            text = T('addin.upd_unknown',
                'Die installierte Fassung meldet ihre Version nicht – sie stammt aus der Zeit vor dieser Prüfung. Auf dem Server liegt {neu}. Es funktioniert alles weiter.')
                .replace(/\{neu\}/g, server);
        }
        kasten.innerHTML =
            '<div class="ad-upd-head">' + esc(T('addin.upd_head',
                'Neue Fassung des Add-ins verfügbar')) + '</div>' +
            '<div class="ad-upd-text">' + esc(text) + ' ' +
            esc(T('addin.upd_how',
                'Lade das Manifest herunter und füge es in Outlook erneut hinzu – oder wende dich an deine Administration.')) +
            '</div>' +
            // target=_blank: im Aufgabenfenster oeffnet Outlook den Link im
            // Systembrowser, und dort landet die Datei (der Endpunkt setzt
            // Content-Disposition). Ein Download im Fenster selbst ist je nach
            // Client blockiert.
            '<a class="ad-btn" href="/addin/manifest.xml" target="_blank"' +
            ' rel="noopener noreferrer">' + esc(T('addin.upd_get',
                'Manifest herunterladen')) + '</a>';
        kasten.classList.remove('hidden');
    }
    function versionPruefen() {
        // Ohne mv UND ohne Outlook-Kontext: direkter Aufruf im Browser. Dann
        // gar nicht fragen – ein Band waere hier schlicht falsch, und genau das
        // sieht jeder, der die Seite zum Pruefen aufruft.
        if (!manifestVersion() && !_officeDa) return;
        // Ohne Authorization-Kopf: der Endpunkt haengt an keiner Anmeldung, und
        // der Hinweis soll auch VOR der Anmeldung gelten.
        fetch('/api/addin/version', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _updServer = (d && d.version) || '';
                if (_updServer) zeichneUpdBand();
            })
            .catch(function () { /* Ein nicht erreichbarer Server ist kein
                Anlass fuer eine Aussage ueber Versionen. */ });
    }

    /* ── Start ────────────────────────────────────────────────────────── */
    function start() {
        // Ohne Sitzung zuerst die kennwortlose Anmeldung versuchen. Sie greift
        // ab dem zweiten Start – beim ersten fehlt die Verknuepfung, und dann
        // steht der Grund auf dem Anmeldebildschirm.
        if (!token()) {
            ssoVersuch().then(function (ok) {
                // `token()` wird MITGEPRUEFT: liesse sich der Token weder im
                // Speicher noch im localStorage ablegen, riefe `start()` sich
                // sonst endlos selbst auf.
                if (ok && token()) start(); else zeigeLogin('');
            });
            return;
        }
        fetch('/api/me', { headers: kopf() })
            .then(function (r) {
                if (r.status === 401) {
                    // Abgelaufenes Token (haeufig: es stammt aus /chat und ist
                    // aelter). Auch hier zuerst kennwortlos versuchen – aber
                    // GENAU EINMAL, sonst koennten sich start() und der
                    // SSO-Versuch gegenseitig aufrufen.
                    tokenLoeschen();
                    if (!_ssoProbiert) {
                        _ssoProbiert = true;
                        ssoVersuch().then(function (ok) {
                            if (ok && token()) start(); else zeigeLogin('');
                        });
                    } else {
                        zeigeLogin('');
                    }
                    return null;
                }
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

    /* Feld-Erklaerungen (ⓘ) – EIN delegierter Listener statt Bindung je Knopf,
       damit auch nachtraeglich gezeichnete Bereiche mitmachen. Gleiche Bauart
       wie in email_portal.js. */
    function infoInit() {
        if (document._adInfoBound) return;
        document._adInfoBound = true;
        document.addEventListener('click', function (e) {
            var knopf = e.target && e.target.closest && e.target.closest('.ad-info');
            if (!knopf) return;
            e.preventDefault();
            var kasten = document.getElementById(knopf.getAttribute('data-help') || '');
            if (!kasten) return;
            var offen = kasten.classList.toggle('is-open');
            knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
        });
    }

    function binde() {
        infoInit();
        if (binde._fertig) return;
        binde._fertig = true;
        askBinden();
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
            var hell = !document.body.classList.contains('light');
            // `theme.js` exportiert `applyTheme`, NICHT `toggleTheme` – die
            // frueher geprueefte Funktion gab es nie, also lief immer der
            // Rueckfall. Der schaltet zwar die Klasse, feuert aber KEIN
            // `jarvis:themechange`; seit branding.js hier eingebunden ist,
            // waeren damit die Hell-Farben der Marke nicht nachgezogen worden.
            if (window.applyTheme) window.applyTheme(hell);
            else document.body.classList.toggle('light', hell);
            try {
                localStorage.setItem('jarvis_theme', hell ? 'light' : 'dark');
            } catch (e) { }
        });
        $('ad-lang').addEventListener('click', function () {
            var neu = sprache() === 'de' ? 'en' : 'de';
            if (window.setLang) window.setLang(neu);
            $('ad-lang').textContent = neu.toUpperCase();
            // Der Bereichskatalog kommt uebersetzt vom SERVER – applyLang()
            // erreicht ihn nicht (gleiche Lage wie im SAP-Katalog). Also neu
            // holen und alles neu zeichnen.
            // Das Band wird per innerHTML gesetzt und von applyLang() nicht
            // erreicht – ohne diese Zeile bliebe es in der Startsprache stehen.
            zeichneUpdBand();
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
        // Eigene Variable/benannte Funktion: eine Inline-Closure ueber eine
        // geteilte `var` sieht beim Klick den zuletzt zugewiesenen Wert
        // (der Fehler, der den Abmelde-Knopf umbeschriftet hat).
        var stilNeu = $('ad-stil-neu');
        if (stilNeu) stilNeu.addEventListener('click', function () {
            oeffneStilFormular(null, null);
        });
        var sigNeu = $('ad-sig-neu');
        if (sigNeu) sigNeu.addEventListener('click', function () {
            oeffneSigFormular(null, null);
        });
        var sigImp = $('ad-sig-import');
        if (sigImp) sigImp.addEventListener('click', function () {
            uebernehmeSig(false);
        });
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
        // Stile sind seit 2026-08-25 ein eigener Reiter. Neu zeichnen beim
        // Oeffnen, damit die Liste stimmt, wenn zwischenzeitlich ein
        // Statuslauf neue Stile geholt hat. _stile selbst wird weiterhin in
        // fuelleKonto() belegt, das aus ladeStatus() heraus IMMER laeuft -
        // der Nachricht-Reiter baut sein Stil-Pulldown daraus, das darf
        // nicht davon abhaengen, ob jemand diesen Reiter geoeffnet hat.
        if (name === 'stile') { zeichneStile(); zeichneSignaturen(); }
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

        // ── Antwort vorschlagen ──
        // Steht VOR dem Regel-Block und haengt bewusst NICHT an einer Regel:
        // eine Antwort zu entwerfen ist der haeufigste Wunsch, und wer noch
        // keine Regel angelegt hat, soll ihn trotzdem haben.
        teile.push('<div class="ad-sep"></div>');
        teile.push('<div class="ad-h">' + esc(T('addin.reply_head', 'Antwort vorschlagen')) + '</div>');
        if (_vorschlag) {
            teile.push('<p class="ad-hint">' + esc(T('addin.reply_check',
                'Prüfe den Text – du kannst ihn hier ändern. Gesendet wird erst auf Knopfdruck.')) +
                // Welcher Stil GEWIRKT hat, nicht welcher gewaehlt wurde: eine
                // Anzeige darf keinen Zustand behaupten, den sie nicht kennt.
                // Bei automatischer Wahl MUSS das dabeistehen: nur so ist
                // erkennbar, dass die Form nicht vom Benutzer bestimmt wurde
                // (und eine Manipulation faellt auf).
                (_vorschlag.stil ? ' · ' + esc(T('mail.style_used', 'Stil')) + ': ' +
                    esc(_vorschlag.stil) +
                    (_vorschlag.stil_quelle === 'auto'
                        ? ' (' + esc(T('mail.style_auto_mark', 'automatisch')) + ')' : '')
                    : '') + '</p>');
            if (_vorschlag.stil_hinweis) {
                teile.push('<div class="ad-warn" style="margin-top:6px;">' +
                    esc(_vorschlag.stil_hinweis) + '</div>');
            }
            teile.push('<div class="ad-field" style="margin-top:8px;">' +
                '<label>' + esc(T('addin.reply_to', 'An')) + ': ' + esc(_vorschlag.an || '') + '</label>' +
                '<textarea id="ad-reply-text" rows="10"></textarea></div>');
            // Format und Signatur stehen HIER, unmittelbar vor den Knoepfen -
            // nicht oben beim Vorschlagen: es sind Eigenschaften des VERSANDS,
            // nicht des Formulierens, und man entscheidet sie, nachdem man den
            // Text gelesen hat. Die Signatur ist im Textfeld bewusst NICHT
            // sichtbar (sie wird serverseitig angehaengt und darf nicht
            // bearbeitbar sein) - deshalb sagt die Zeile darunter, WAS
            // angehaengt wird.
            teile.push('<div class="ad-grid2" style="margin-top:8px;">' +
                '<div class="ad-field"><label>' +
                esc(T('mail.fmt_pick', 'Format')) + '</label>' +
                '<select id="ad-reply-fmt">' + formatOptionen(_fmtWahl) + '</select></div>' +
                '<div class="ad-field"><label>' +
                esc(T('mail.sig_pick', 'Signatur')) + '</label>' +
                '<select id="ad-reply-sig">' + sigOptionen(_sigWahl) + '</select></div></div>');
            teile.push('<p class="ad-hint" id="ad-reply-sighint" style="margin-top:0;"></p>');
            teile.push('<div class="ad-row" style="margin-top:0;">' +
                '<button class="ad-btn ad-btn-primary" id="ad-reply-send">' +
                esc(T('addin.reply_send', 'Senden')) + '</button>' +
                '<button class="ad-btn" id="ad-reply-draft">' +
                esc(T('addin.reply_draft', 'Als Entwurf')) + '</button>' +
                '<button class="ad-btn" id="ad-reply-new">' +
                esc(T('addin.reply_again', 'Neu formulieren')) + '</button>' +
                '<button class="ad-btn ad-btn-danger" id="ad-reply-drop">' +
                esc(T('addin.reply_drop', 'Verwerfen')) + '</button></div>');
        } else {
            teile.push('<div class="ad-field" style="margin-top:8px;">' +
                '<label>' + esc(T('addin.reply_hint_label', 'Hinweis (optional)')) + '</label>' +
                '<input type="text" id="ad-reply-hint" data-tabfill placeholder="' +
                esc(T('addin.reply_hint_ph', 'z. B. freundlich absagen, Termin bestätigen')) +
                '"></div>');
            if (_stile.length) {
                teile.push('<div class="ad-field">' +
                    '<label>' + esc(T('mail.style_pick', 'Stil')) + '</label>' +
                    '<select id="ad-reply-stil">' + stilOptionen(_stilWahl) + '</select></div>');
            }
            teile.push('<button class="ad-btn ad-btn-primary ad-btn-block" id="ad-reply-make">' +
                esc(T('addin.reply_make', 'Antwort vorschlagen')) + '</button>');
            teile.push('<p class="ad-hint" style="margin-top:6px;">' + esc(T('addin.reply_safe',
                'Es wird nichts gesendet – du siehst den Text zuerst.')) + '</p>');
        }
        teile.push('<p class="ad-status" id="ad-reply-status" style="margin-top:8px;"></p>');

        // ── Regel auf diese Nachricht anwenden ──
        teile.push('<div class="ad-sep"></div>');
        teile.push('<div class="ad-h">' + esc(T('addin.run_head', 'Mit einer Regel verarbeiten')) + '</div>');
        if (!aktive.length) {
            teile.push('<div class="ad-empty">' + esc(T('addin.no_rules',
                'Du hast noch keine aktive Regel. Lege im Reiter „Regeln" eine an.')) + '</div>');
        } else {
            teile.push('<div class="ad-field" style="margin-top:8px;">' +
                // Kurz: die Ueberschrift des Abschnitts sagt schon "Mit einer
                // Regel verarbeiten" – ein Label, das denselben Satz wiederholt,
                // ist Rauschen (gemeldet 2026-08-18).
                '<label>' + esc(T('addin.choose_rule', 'Regel')) + '</label>' +
                '<select id="ad-run-rule">' + aktive.map(function (r) {
                    return '<option value="' + esc(r.id) + '">' + esc(r.name) + '</option>';
                }).join('') + '</select></div>');
            teile.push('<button class="ad-btn ad-btn-block" id="ad-run-msg">' +
                esc(T('addin.run_now', 'Jetzt verarbeiten')) + '</button>');
            teile.push('<p class="ad-hint" style="margin-top:6px;">' + esc(T('addin.run_hint',
                'Die Regel wird auf genau dieser Nachricht ausgeführt – die Aktionen sind echt (sie kann also tatsächlich antworten).')) + '</p>');
            teile.push('<p class="ad-status" id="ad-run-status" style="margin-top:8px;"></p>');
            teile.push('<div id="ad-run-result"></div>');
        }

        box.innerHTML = teile.join('');
        if ($('ad-run-msg')) $('ad-run-msg').addEventListener('click', verarbeiteNachricht);
        if ($('ad-reply-make')) $('ad-reply-make').addEventListener('click', antwortVorschlagen);
        if ($('ad-reply-stil')) {
            $('ad-reply-stil').addEventListener('change', function () {
                _stilWahl = this.value;
            });
        }
        if ($('ad-reply-text')) {
            // Der bearbeitete Text wird SOFORT gespiegelt. `zeichneNachricht()`
            // baut den Reiter bei jedem Statusladen und bei jedem Sprachwechsel
            // neu auf – ohne die Spiegelung waere eine halb getippte Antwort
            // dabei weg (gleiche Lehre wie beim Regel-Formular).
            var ta = $('ad-reply-text');
            ta.value = _vorschlag.text || '';
            ta.addEventListener('input', function () {
                if (_vorschlag) _vorschlag.text = ta.value;
            });
            // Der Hinweis nennt die Signatur, die WIRKLICH angehaengt wird -
            // aufgeloest genauso wie serverseitig (leer = Standard, '-' = keine).
            // Ohne ihn waere die Signatur unsichtbar bis zum Blick ins Postfach.
            var sigHinweis = function () {
                var el = $('ad-reply-sighint');
                if (!el) return;
                var w = (($('ad-reply-sig') || {}).value || '');
                var e = null;
                if (w === '-') e = null;
                else if (w) e = _signaturen.filter(function (x) { return x.id === w; })[0] || null;
                else e = _signaturen.filter(function (x) { return x.standard; })[0] || null;
                el.textContent = e
                    ? T('mail.sig_will_append', 'Angehängt wird die Signatur „%s".')
                        .replace('%s', e.name)
                    : T('mail.sig_will_none', 'Es wird keine Signatur angehängt.');
            };
            if ($('ad-reply-sig')) {
                $('ad-reply-sig').addEventListener('change', function () {
                    _sigWahl = this.value; sigHinweis();
                });
            }
            if ($('ad-reply-fmt')) {
                $('ad-reply-fmt').addEventListener('change', function () {
                    _fmtWahl = this.value;
                });
            }
            sigHinweis();
            $('ad-reply-send').addEventListener('click', function () { antwortSenden(false); });
            $('ad-reply-draft').addEventListener('click', function () { antwortSenden(true); });
            $('ad-reply-new').addEventListener('click', function () {
                _vorschlag = null; zeichneNachricht();
            });
            $('ad-reply-drop').addEventListener('click', function () {
                _vorschlag = null; zeichneNachricht();
            });
        }
    }

    /* Antwort formulieren lassen. Der Lauf dahinter hat KEINE Werkzeuge – es
       kann also nichts gesendet oder verschoben werden, egal was in der
       eingegangenen Mail steht. Gesendet wird erst mit `antwortSenden`. */
    function antwortVorschlagen() {
        if (_laeuft || !_office || !_office.id) return;
        _laeuft = true;
        var knopf = $('ad-reply-make');
        if (knopf) knopf.disabled = true;
        melde('ad-reply-status', T('addin.reply_working', 'Formuliere eine Antwort…'));
        sende('/api/email/reply/preview', 'POST', {
            msg_id: _office.id,
            ordner: '',
            hinweis: (($('ad-reply-hint') || {}).value || '').trim(),
            stil: (($('ad-reply-stil') || {}).value || '')
        })
            .then(function (d) {
                _vorschlag = { text: d.text || '', an: d.an || '', betreff: d.betreff || '',
                               stil: d.stil || '', stil_hinweis: d.stil_hinweis || '',
                               stil_quelle: d.stil_quelle || '' };
                zeichneNachricht();
                melde('ad-reply-status', '');
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-reply-status', e.message, 'fehler');
            })
            .then(function () {
                _laeuft = false;
                if ($('ad-reply-make')) $('ad-reply-make').disabled = false;
            });
    }

    /* Den freigegebenen Text abschicken. Der EMPFAENGER kommt serverseitig aus
       der beantworteten Nachricht – hier geht nur der Text hinaus. */
    function antwortSenden(entwurf) {
        if (_laeuft || !_vorschlag || !_office || !_office.id) return;
        var text = ($('ad-reply-text') || {}).value || _vorschlag.text || '';
        if (!text.trim()) {
            melde('ad-reply-status', T('addin.reply_empty', 'Der Text ist leer.'), 'fehler');
            return;
        }
        _laeuft = true;
        ['ad-reply-send', 'ad-reply-draft'].forEach(function (id) {
            if ($(id)) $(id).disabled = true;
        });
        melde('ad-reply-status', entwurf
            ? T('addin.reply_saving', 'Speichere Entwurf…')
            : T('addin.reply_sending', 'Sende…'));
        sende('/api/email/reply/send', 'POST', {
            msg_id: _office.id, ordner: '', text: text, entwurf: !!entwurf,
            // Aus dem Pulldown, NICHT aus `_fmtWahl`/`_sigWahl` allein: der
            // Reiter wird bei jedem Statuslauf neu gebaut, und der Merker ist
            // nur die Bruecke darueber. Der Feldwert ist der Stand, den der
            // Benutzer zuletzt gesehen hat.
            format: (($('ad-reply-fmt') || {}).value || _fmtWahl || ''),
            signatur: (($('ad-reply-sig') || {}).value || _sigWahl || '')
        })
            .then(function (d) {
                _vorschlag = null;
                zeichneNachricht();
                melde('ad-reply-status', d.ergebnis ||
                    T('addin.reply_done', 'Antwort gesendet.'), 'ok');
                ladeLog();   // Funktionsname gegen die Datei geprueft
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-reply-status', e.message, 'fehler');
            })
            .then(function () {
                _laeuft = false;
                ['ad-reply-send', 'ad-reply-draft'].forEach(function (id) {
                    if ($(id)) $(id).disabled = false;
                });
            });
    }

    function verarbeiteNachricht() {
        if (_laeuft) return;
        var rid = ($('ad-run-rule') || {}).value || '';
        if (!rid || !_office || !_office.id) return;
        var regel = _regeln.filter(function (r) { return r.id === rid; })[0] || {};
        frage(T('addin.run_confirm',
                'Diese Nachricht jetzt mit der Regel verarbeiten? Die Aktionen sind echt.') +
              '\n\n' + (regel.name || ''), T('addin.run_now', 'Jetzt verarbeiten'))
            .then(function (ja) { if (ja) starteLaufJetzt(rid); });
    }

    function starteLaufJetzt(rid) {
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
                esc(T('common.delete', 'Löschen')) + '">' + JarvisIcons.trash() + '</button>' +
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

            // Der Hinweis muss hier stehen wie in /email: eine Absender-Bedingung
            // im Prompt ist nur eine Bitte an das Modell - am 2026-08-17 hat das
            // zwei fremde Empfaenger eine Mail gekostet.
            '<div class="ad-field"><label>' + esc(T('mail.f_from', 'Nur von diesen Absendern')) + '</label>' +
            '<input type="text" id="ad-f-from" value="' + esc(r.von_filter || '') + '"></div>' +
            '<div class="ad-hint">' + esc(T('mail.f_from_hint',
                'Bedingungen zum Absender gehören hierher, nicht ins Prompt. Komma trennt, '
                + '* ist Platzhalter. Leer = alle Absender.')) + '</div>' +

            '<div class="ad-field"><label>' + esc(T('mail.f_subject', 'Nur Betreff enthält')) + '</label>' +
            '<input type="text" id="ad-f-subject" value="' + esc(r.betreff_filter || '') + '"></div>' +

            '<label class="ad-check"><input type="checkbox" id="ad-f-unread"' +
            (r.nur_ungelesen !== false ? ' checked' : '') + '><span>' +
            esc(T('mail.f_unread', 'Nur ungelesene Nachrichten')) + '</span></label>' +

            '<label class="ad-check" style="margin-top:6px;"><input type="checkbox" id="ad-f-read"' +
            (r.markiere_gelesen ? ' checked' : '') + '><span>' +
            esc(T('mail.f_read', 'Nach Bearbeitung als gelesen markieren')) + '</span></label>' +

            '<div class="ad-field" style="margin-top:10px;"><label>' +
            esc(T('mail.f_style', 'Stil für Antworten dieser Regel')) + '</label>' +
            '<select id="ad-f-stil">' + stilOptionen(r.stil || '') + '</select>' +
            '<span class="ad-hint">' + esc(T('mail.f_style_hint_short',
                'Ohne Auswahl gilt der Standard-Stil oder der, den du im Prompt beim Namen nennst.')) +
            '</span></div>' +

            // Format und Signatur der Regel. Sie wirken auf JEDE Antwort, die
            // diese Regel automatisch schreibt - also dort, wo niemand
            // gegenliest. Genau deshalb sind sie Felder und keine
            // Prompt-Formulierung: das Modell sieht sie nicht.
            '<div class="ad-grid2" style="margin-top:10px;">' +
            '<div class="ad-field"><label>' + esc(T('mail.fmt_pick', 'Format')) + '</label>' +
            '<select id="ad-f-fmt">' + formatOptionen(r.format || '') + '</select></div>' +
            '<div class="ad-field"><label>' + esc(T('mail.sig_pick', 'Signatur')) + '</label>' +
            '<select id="ad-f-sig">' + sigOptionen(r.signatur || '') + '</select></div></div>' +

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
        'ad-f-max', 'ad-f-from', 'ad-f-subject', 'ad-f-stil', 'ad-f-fmt', 'ad-f-sig'];
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
            stil: (($('ad-f-stil') || {}).value || ''),
            format: (($('ad-f-fmt') || {}).value || ''),
            signatur: (($('ad-f-sig') || {}).value || ''),
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
        // `%s` MUSS ersetzt werden – der Text lautet „Regel „%s" wirklich
        // löschen?". Vorher wurde der Name nur angehaengt; im Dialog stand
        // dann woertlich „Regel „%s" …". Das ist erst aufgefallen, als der
        // Dialog ueberhaupt erschien (mit `window.confirm` sah es niemand).
        frage(T('mail.rule_del_confirm', 'Regel „%s" wirklich löschen?')
                  .replace('%s', r.name || '?'),
              T('common.delete', 'Löschen'), true)
            .then(function (ja) { if (ja) loescheRegelJetzt(id); });
    }

    function loescheRegelJetzt(id) {
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

    /* Muster-Stiltext fuer die TAB-Uebernahme (der Platzhalter zaehlt nur auf,
       was hineingehoert, und waere als Feldinhalt Unsinn). */
    var STIL_MUSTER = 'Antworte in der Sie-Form, sachlich und in h\u00f6chstens f\u00fcnf S\u00e4tzen.\n'
        + 'Best\u00e4tige zuerst kurz das Anliegen.\n'
        + 'Sage keine Preise, Rabatte oder Liefertermine zu.\n'
        + 'Schlie\u00dfe mit:\nMit freundlichen Gr\u00fc\u00dfen\n<Name>\n<Abteilung>';

    /* ── Antwort-Stile ────────────────────────────────────────────────── */
    /* Eigene Endpunkte (/api/email/styles): jeder Knopf hier speichert sofort.
       Der Knopf "Speichern" des Postfachs fasst die Stile NICHT an – zwei
       Wege, die dieselbe Liste schreiben, wuerden sich gegenseitig
       ueberschreiben. */
    function zeichneStile() {
        var box = $('ad-stile');
        if (!box) return;
        stilFormularHeim();
        if (!_stile.length) {
            box.innerHTML = '<div class="ad-empty">' + esc(T('mail.styles_none',
                'Noch kein Stil angelegt. Ohne Stil wird neutral geantwortet.')) + '</div>';
            return;
        }
        box.innerHTML = _stile.map(function (e) {
            return '<div class="ad-card' + (e.standard ? ' is-std' : '') +
                '" data-stil="' + esc(e.id) + '"><div class="ad-card-row">' +
                '<div class="ad-card-main"><div class="ad-card-name">' + esc(e.name) +
                (e.standard ? '<span class="ad-badge">\u25CF ' +
                    esc(T('mail.style_default', 'Standard')) + '</span>' : '') + '</div>' +
                '<div class="ad-card-meta">' +
                esc((e.text || '').replace(/\s+/g, ' ').slice(0, 70) ||
                    T('mail.style_empty', '(kein Text hinterlegt)')) + '</div></div>' +
                '<div class="ad-card-acts">' +
                (e.standard ? '' : '<button class="ad-mini" data-act="std" title="' +
                    esc(T('mail.style_make_default', 'Als Standard setzen')) + '">\u25CB</button>') +
                '<button class="ad-mini" data-act="edit" title="' +
                esc(T('common.edit', 'Bearbeiten')) + '">\u270E</button>' +
                '<button class="ad-mini is-danger" data-act="del" title="' +
                esc(T('common.delete', 'Löschen')) + '">\u2715</button>' +
                '</div></div></div>';
        }).join('');
        box.querySelectorAll('.ad-mini').forEach(function (b) {
            b.addEventListener('click', function () {
                var karte = b.closest('.ad-card');
                var id = karte.getAttribute('data-stil');
                var act = b.getAttribute('data-act');
                if (act === 'edit') oeffneStilFormular(id, karte);
                else if (act === 'del') loescheStil(id);
                else if (act === 'std') setzeStandard(id);
            });
        });
        if (_stilEdit && _stilEdit !== 'neu') {
            var k = box.querySelector('.ad-card[data-stil="' + _stilEdit + '"]');
            if (k) k.appendChild($('ad-stil-edit'));
        }
    }

    var _stilHeim = null;
    function stilFormularHeim() {
        var f = $('ad-stil-edit');
        if (!f) return;
        if (!_stilHeim) _stilHeim = f.parentNode;
        if (f.parentNode !== _stilHeim) _stilHeim.appendChild(f);
    }

    function schliesseStilFormular() {
        _stilEdit = null;
        var f = $('ad-stil-edit');
        if (!f) return;
        stilFormularHeim();
        f.innerHTML = '';
        f.className = 'hidden';
    }

    function oeffneStilFormular(id, karte) {
        var f = $('ad-stil-edit');
        if (!f) return;
        if (_stilEdit === (id || 'neu')) { schliesseStilFormular(); return; }
        if (!_stilHeim) _stilHeim = f.parentNode;
        _stilEdit = id || 'neu';
        var e = id ? (_stile.filter(function (x) { return x.id === id; })[0] || {}) : {};
        var g = (_status && _status.grenzen) || {};
        f.className = id ? 'ad-edit' : '';
        f.innerHTML =
            '<div class="ad-field" style="margin-top:8px;"><label>' +
            esc(T('mail.style_name', 'Name des Stils')) + '</label>' +
            '<input type="text" id="ad-s-name" maxlength="' + (g.stil_name_max || 60) +
            '" value="' + esc(e.name || '') + '" placeholder="' +
            esc(T('mail.style_name_ph', 'z. B. Förmlich')) + '"></div>' +
            '<div class="ad-field"><label>' + esc(T('mail.style_text', 'Stil und Signatur')) +
            '</label><textarea id="ad-s-text" rows="9" maxlength="' + (g.stil_text_max || 6000) +
            '" data-tabfill="' + esc(T('mail.style_text_suggest', STIL_MUSTER)) +
            '" placeholder="' + esc(T('mail.acct_guide_ph',
                'z. B. Signatur, Anrede-Form, was nie zugesagt werden darf')) + '">' +
            esc(e.text || '') + '</textarea>' +
            '<span class="ad-hint">' + esc(T('mail.acct_guide_hint',
                'Bestimmt nur den Ton – löst NIE eine Aktion aus.')) +
            ' <span id="ad-s-count"></span></span></div>' +
            '<label class="ad-check"><input type="checkbox" id="ad-s-std"' +
            ((e.standard || (!id && !_stile.length)) ? ' checked' : '') + '><span>' +
            esc(T('mail.style_is_default', 'Als Standard verwenden, wenn nichts gewählt ist')) +
            '</span></label>' +
            '<div class="ad-row"><button class="ad-btn ad-btn-primary" id="ad-s-save">' +
            esc(id ? T('common.save', 'Speichern') : T('mail.style_create', 'Stil anlegen')) +
            '</button><button class="ad-btn" id="ad-s-cancel">' +
            esc(T('common.cancel', 'Abbrechen')) + '</button></div>' +
            '<p class="ad-status" id="ad-s-status" style="margin-top:6px;"></p>';
        zaehlerBinden($('ad-s-text'), $('ad-s-count'), (g.stil_text_max || 6000));
        $('ad-s-save').addEventListener('click', function () { speichereStil(id); });
        $('ad-s-cancel').addEventListener('click', schliesseStilFormular);
        if (karte) karte.appendChild(f); else stilFormularHeim();
        try { f.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e2) { }
    }

    /* Zeichenzaehler ab 70%% - `maxlength` schneidet sonst still ab. */
    function zaehlerBinden(feld, anzeige, grenze) {
        if (!feld || !anzeige) return;
        var mal = function () {
            var n = (feld.value || '').length;
            if (n < grenze * 0.7) { anzeige.textContent = ''; return; }
            anzeige.textContent = '· ' + n + ' / ' + grenze;
            anzeige.style.color = (n >= grenze) ? 'var(--danger)' : '';
        };
        feld.addEventListener('input', mal);
        mal();
    }

    function speichereStil(id) {
        var d = {
            name: (($('ad-s-name') || {}).value || '').trim(),
            text: (($('ad-s-text') || {}).value || ''),
            standard: !!(($('ad-s-std') || {}).checked)
        };
        melde('ad-s-status', T('common.saving', 'Speichert…'));
        var p = id ? sende('/api/email/styles/' + encodeURIComponent(id), 'PUT', d)
            : sende('/api/email/styles', 'POST', d);
        p.then(function (a) {
            _stile = a.stile || [];
            schliesseStilFormular();
            zeichneStile();
            zeichneNachricht();      // die Stil-Auswahl dort haengt daran
            melde('ad-stil-status', T('mail.style_saved', 'Stil gespeichert.'), 'ok');
        }).catch(function (e) {
            if (String(e.message) !== '401') melde('ad-s-status', e.message, 'fehler');
        });
    }

    function setzeStandard(id) {
        sende('/api/email/styles/' + encodeURIComponent(id), 'PUT', { standard: true })
            .then(function (a) {
                _stile = a.stile || [];
                zeichneStile();
                zeichneNachricht();
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-stil-status', e.message, 'fehler');
            });
    }

    function loescheStil(id) {
        var e = _stile.filter(function (x) { return x.id === id; })[0] || {};
        frage(T('mail.style_del_confirm',
                'Diesen Stil wirklich löschen? Regeln, die ihn benutzen, antworten danach im Standard-Stil.')
              + '\n\n' + (e.name || ''), T('common.delete', 'Löschen'), true)
            .then(function (ja) { if (ja) loescheStilJetzt(id); });
    }

    function loescheStilJetzt(id) {
        sende('/api/email/styles/' + encodeURIComponent(id), 'DELETE')
            .then(function (a) {
                _stile = a.stile || [];
                if (_stilEdit === id) schliesseStilFormular();
                zeichneStile();
                zeichneNachricht();
                melde('ad-stil-status', T('mail.style_deleted', 'Stil entfernt.'), 'ok');
            })
            .catch(function (e2) {
                if (String(e2.message) !== '401') melde('ad-stil-status', e2.message, 'fehler');
            });
    }

    /* Optionen fuer ein Stil-Pulldown. Leer = Standard bzw. der im Prompt einer
       Regel genannte Stil, "-" = ausdruecklich ohne Stil. */
    /* Die automatische Wahl steht UEBERALL zur Verfuegung, wo ein Stil
       gewaehlt wird – in der Antwort-Vorschau wie im Regel-Formular
       (ausdrueckliche Vorgabe des Nutzers, 2026-08-19). Keine Bedingungen:
       wer sie nicht will, waehlt sie nicht. */
    function stilOptionen(gewaehlt) {
        var std = _stile.filter(function (e) { return e.standard; })[0];
        // Der Standard steht als ERSTER Eintrag, mit `*` und mit dem Wert "" –
        // "" heisst "nichts ausdruecklich gewaehlt", nur so greift in einer
        // Regel ein im Prompt genannter Stil. Und er wird NICHT zusaetzlich mit
        // eigener Kennung gelistet: doppelt in der Liste war genau das gemeldete
        // Problem ("Standard – Standard").
        var h = '<option value=""' + (gewaehlt ? '' : ' selected') + '>' + (std
            ? esc(std.name) + ' *'
            : esc(T('mail.style_opt_none', 'kein Stil'))) + '</option>';
        h += '<option value="auto"' + (gewaehlt === 'auto' ? ' selected' : '') +
            '>' + esc(T('mail.style_opt_auto', 'automatisch Stil wählen')) + '</option>';
        h += _stile.filter(function (e) { return !e.standard; }).map(function (e) {
            return '<option value="' + esc(e.id) + '"' +
                (gewaehlt === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>';
        }).join('');
        if (!_stile.length) return h;
        return h + '<option value="-"' + (gewaehlt === '-' ? ' selected' : '') + '>' +
            esc(T('mail.style_opt_off', '– ohne Stil –')) + '</option>';
    }

    /* ── Signaturen ───────────────────────────────────────────────────── */
    /* Gespiegelt an den Stilen - bewusst, damit sich beide gleich bedienen.
       Der UNTERSCHIED liegt nicht in der Oberflaeche, sondern in der Wirkung:
       ein Stil geht als Anweisung in den Auftrag, eine Signatur wird nach dem
       Lauf woertlich angehaengt. Deshalb hat eine Signatur zwei Felder (Text
       und optional HTML) und keine "automatisch waehlen"-Option: was fest
       angehaengt wird, soll kein Modell aussuchen. */
    function zeichneSignaturen() {
        var box = $('ad-sigs');
        if (!box) return;
        sigFormularHeim();
        if (!_signaturen.length) {
            box.innerHTML = '<div class="ad-empty">' + esc(T('mail.sigs_none',
                'Noch keine Signatur angelegt. Antworten gehen dann ohne Signatur hinaus.')) +
                '</div>';
            return;
        }
        box.innerHTML = _signaturen.map(function (e) {
            var vorschau = (e.text || '').replace(/\s+/g, ' ').slice(0, 70);
            if (!vorschau && e.html) vorschau = T('mail.sig_html_only', '(nur HTML-Fassung)');
            return '<div class="ad-card' + (e.standard ? ' is-std' : '') +
                '" data-sig="' + esc(e.id) + '"><div class="ad-card-row">' +
                '<div class="ad-card-main"><div class="ad-card-name">' + esc(e.name) +
                (e.standard ? '<span class="ad-badge">\u25CF ' +
                    esc(T('mail.style_default', 'Standard')) + '</span>' : '') +
                (e.html ? '<span class="ad-badge">HTML</span>' : '') + '</div>' +
                '<div class="ad-card-meta">' +
                esc(vorschau || T('mail.sig_empty', '(kein Text hinterlegt)')) +
                '</div></div>' +
                '<div class="ad-card-acts">' +
                (e.standard ? '' : '<button class="ad-mini" data-act="std" title="' +
                    esc(T('mail.sig_make_default', 'Als Standard setzen')) + '">\u25CB</button>') +
                '<button class="ad-mini" data-act="edit" title="' +
                esc(T('common.edit', 'Bearbeiten')) + '">\u270E</button>' +
                '<button class="ad-mini is-danger" data-act="del" title="' +
                esc(T('common.delete', 'Löschen')) + '">\u2715</button>' +
                '</div></div></div>';
        }).join('');
        box.querySelectorAll('.ad-mini').forEach(function (b) {
            b.addEventListener('click', function () {
                var karte = b.closest('.ad-card');
                var id = karte.getAttribute('data-sig');
                var act = b.getAttribute('data-act');
                if (act === 'edit') oeffneSigFormular(id, karte);
                else if (act === 'del') loescheSig(id);
                else if (act === 'std') setzeSigStandard(id);
            });
        });
        if (_sigEdit && _sigEdit !== 'neu') {
            var k = box.querySelector('.ad-card[data-sig="' + _sigEdit + '"]');
            if (k) k.appendChild($('ad-sig-edit'));
        }
    }

    /* EIN Container, der wandert - dieselbe Mechanik wie beim Stil-Formular:
       Heimatplatz nur beim ERSTEN Verschieben merken, vor dem Neuaufbau
       heimholen (sonst raeumt `innerHTML = ...` der Liste das Formular mit ab). */
    var _sigHeim = null;
    function sigFormularHeim() {
        var f = $('ad-sig-edit');
        if (!f) return;
        if (!_sigHeim) _sigHeim = f.parentNode;
        if (f.parentNode !== _sigHeim) _sigHeim.appendChild(f);
    }

    function schliesseSigFormular() {
        _sigEdit = null;
        var f = $('ad-sig-edit');
        if (!f) return;
        sigFormularHeim();
        f.innerHTML = '';
        f.className = 'hidden';
    }

    function oeffneSigFormular(id, karte) {
        var f = $('ad-sig-edit');
        if (!f) return;
        if (_sigEdit === (id || 'neu')) { schliesseSigFormular(); return; }
        if (!_sigHeim) _sigHeim = f.parentNode;
        _sigEdit = id || 'neu';
        var e = id ? (_signaturen.filter(function (x) { return x.id === id; })[0] || {}) : {};
        var g = (_status && _status.grenzen) || {};
        var tmax = g.sig_text_max || 4000;
        var hmax = g.sig_html_max || 60000;
        f.className = id ? 'ad-edit' : '';
        f.innerHTML =
            '<div class="ad-field" style="margin-top:8px;"><label>' +
            esc(T('mail.sig_name', 'Name der Signatur')) + '</label>' +
            '<input type="text" id="ad-g-name" maxlength="' + (g.sig_name_max || 60) +
            '" value="' + esc(e.name || '') + '" placeholder="' +
            esc(T('mail.sig_name_ph', 'z. B. Standard, Kurz, Englisch')) + '"></div>' +
            '<div class="ad-field"><label>' + esc(T('mail.sig_text', 'Signatur (Text)')) +
            '</label><textarea id="ad-g-text" rows="7" maxlength="' + tmax +
            '" placeholder="' + esc(T('mail.sig_text_ph',
                'Mit freundlichen Grüßen\nVorname Nachname\nFirma · Telefon')) + '">' +
            esc(e.text || '') + '</textarea>' +
            '<span class="ad-hint">' + esc(T('mail.sig_text_hint',
                'Wird wörtlich angehängt – die KI ändert daran nichts.')) +
            ' <span id="ad-g-count"></span></span></div>' +
            '<div class="ad-field"><label>' + esc(T('mail.sig_html', 'HTML-Fassung (optional)')) +
            '</label><textarea id="ad-g-html" rows="6" maxlength="' + hmax +
            '" placeholder="&lt;p&gt;Mit freundlichen Grüßen&lt;br&gt;&lt;b&gt;Vorname Nachname&lt;/b&gt;&lt;/p&gt;">' +
            esc(e.html || '') + '</textarea>' +
            '<span class="ad-hint">' + esc(T('mail.sig_html_hint',
                'Wirkt nur bei HTML-Antworten. Skripte werden entfernt.')) +
            ' <span id="ad-g-hcount"></span></span></div>' +
            '<label class="ad-check"><input type="checkbox" id="ad-g-std"' +
            ((e.standard || (!id && !_signaturen.length)) ? ' checked' : '') + '><span>' +
            esc(T('mail.sig_is_default', 'Als Standard verwenden, wenn nichts gewählt ist')) +
            '</span></label>' +
            '<div class="ad-row"><button class="ad-btn ad-btn-primary" id="ad-g-save">' +
            esc(id ? T('common.save', 'Speichern') : T('mail.sig_create', 'Signatur anlegen')) +
            '</button><button class="ad-btn" id="ad-g-cancel">' +
            esc(T('common.cancel', 'Abbrechen')) + '</button></div>' +
            '<p class="ad-status" id="ad-g-status" style="margin-top:6px;"></p>';
        zaehlerBinden($('ad-g-text'), $('ad-g-count'), tmax);
        zaehlerBinden($('ad-g-html'), $('ad-g-hcount'), hmax);
        $('ad-g-save').addEventListener('click', function () { speichereSig(id); });
        $('ad-g-cancel').addEventListener('click', schliesseSigFormular);
        if (karte) karte.appendChild(f); else sigFormularHeim();
        try { f.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e2) { }
    }

    function speichereSig(id) {
        var d = {
            name: (($('ad-g-name') || {}).value || '').trim(),
            text: (($('ad-g-text') || {}).value || ''),
            html: (($('ad-g-html') || {}).value || ''),
            standard: !!(($('ad-g-std') || {}).checked)
        };
        melde('ad-g-status', T('common.saving', 'Speichert…'));
        var p = id ? sende('/api/email/signatures/' + encodeURIComponent(id), 'PUT', d)
            : sende('/api/email/signatures', 'POST', d);
        p.then(function (a) {
            _signaturen = a.signaturen || [];
            schliesseSigFormular();
            zeichneSignaturen();
            zeichneNachricht();      // das Signatur-Pulldown dort haengt daran
            melde('ad-sig-status', T('mail.sig_saved', 'Signatur gespeichert.'), 'ok');
        }).catch(function (e) {
            if (String(e.message) !== '401') melde('ad-g-status', e.message, 'fehler');
        });
    }

    /* Meldung nach der Uebernahme. Verlorene Bilder werden GENANNT, nicht
       verschwiegen: eine in Outlook gebaute Signatur verweist ihr Logo auf
       einen Pfad auf dem eigenen Rechner (file:///C:/Users/...), und den kann
       der Server nicht aufloesen. Ohne diesen Satz fehlt hinterher das Logo
       und nichts erklaert warum. */
    function importMeldung(a) {
        var txt = (a.art === 'aktualisiert'
            ? T('mail.sig_import_upd', 'Signatur aus dem Postfach aufgefrischt.')
            : T('mail.sig_import_new', 'Signatur aus dem Postfach übernommen.'));
        if (a.bilder_weg > 0) {
            txt += ' ' + T('mail.sig_import_imgs',
                'Bilder wurden nicht übernommen (%n) – sie liegen in Outlook auf '
                + 'deinem Rechner und sind vom Server aus nicht erreichbar.')
                .replace('%n', a.bilder_weg);
        }
        return txt;
    }

    /* Signatur aus dem Postfach uebernehmen.

       Bei 409 ("gibt es schon") wird NICHT stillschweigend ueberschrieben,
       sondern gefragt - der Eintrag kann von Hand nachbearbeitet worden sein.
       `frage()` statt `confirm()`: im Aufgabenfenster (WebView2) ist confirm
       unterdrueckt und der Knopf braeche wortlos ab. */
    function uebernehmeSig(ersetzen) {
        var knopf = $('ad-sig-import');
        if (knopf) knopf.disabled = true;
        melde('ad-sig-status', T('mail.sig_import_run', 'Lese Signatur aus dem Postfach…'));
        sende('/api/email/signatures/import', 'POST', { ersetzen: !!ersetzen })
            .then(function (a) {
                _signaturen = a.signaturen || [];
                zeichneSignaturen();
                zeichneNachricht();   // das Signatur-Pulldown dort haengt daran
                melde('ad-sig-status', importMeldung(a), 'ok');
            })
            .catch(function (e) {
                if (String(e.message) === '401') return;
                if (e.status === 409 && !ersetzen) {
                    melde('ad-sig-status', '');
                    frage(T('mail.sig_import_ask',
                        'Es gibt bereits eine übernommene Signatur. Soll sie durch den '
                        + 'aktuellen Stand aus dem Postfach ersetzt werden? Eigene '
                        + 'Änderungen daran gehen dabei verloren.'),
                        T('mail.sig_import_yes', 'Ersetzen'), true)
                        .then(function (ja) { if (ja) uebernehmeSig(true); });
                    return;
                }
                melde('ad-sig-status', e.message, 'fehler');
            })
            .then(function () {
                if (knopf) knopf.disabled = false;
            });
    }

    function setzeSigStandard(id) {
        sende('/api/email/signatures/' + encodeURIComponent(id), 'PUT', { standard: true })
            .then(function (a) {
                _signaturen = a.signaturen || [];
                zeichneSignaturen();
                zeichneNachricht();
            })
            .catch(function (e) {
                if (String(e.message) !== '401') melde('ad-sig-status', e.message, 'fehler');
            });
    }

    function loescheSig(id) {
        var e = _signaturen.filter(function (x) { return x.id === id; })[0] || {};
        frage(T('mail.sig_del_confirm',
                'Diese Signatur wirklich löschen? Antworten ohne eigene Auswahl nehmen danach die Standard-Signatur.')
              + '\n\n' + (e.name || ''), T('common.delete', 'Löschen'), true)
            .then(function (ja) { if (ja) loescheSigJetzt(id); });
    }

    function loescheSigJetzt(id) {
        sende('/api/email/signatures/' + encodeURIComponent(id), 'DELETE')
            .then(function (a) {
                _signaturen = a.signaturen || [];
                if (_sigEdit === id) schliesseSigFormular();
                zeichneSignaturen();
                zeichneNachricht();
                melde('ad-sig-status', T('mail.sig_deleted', 'Signatur entfernt.'), 'ok');
            })
            .catch(function (e2) {
                if (String(e2.message) !== '401') melde('ad-sig-status', e2.message, 'fehler');
            });
    }

    /* Optionen fuer ein Signatur-Pulldown. Leer = Standard, "-" = ausdruecklich
       ohne. KEIN "automatisch": siehe Kommentar oben. */
    function sigOptionen(gewaehlt) {
        var std = _signaturen.filter(function (e) { return e.standard; })[0];
        var h = '<option value=""' + (gewaehlt ? '' : ' selected') + '>' + (std
            ? esc(std.name) + ' *'
            : esc(T('mail.sig_opt_none', 'keine Signatur'))) + '</option>';
        h += _signaturen.filter(function (e) { return !e.standard; }).map(function (e) {
            return '<option value="' + esc(e.id) + '"' +
                (gewaehlt === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>';
        }).join('');
        if (!_signaturen.length) return h;
        return h + '<option value="-"' + (gewaehlt === '-' ? ' selected' : '') + '>' +
            esc(T('mail.sig_opt_off', '– ohne Signatur –')) + '</option>';
    }

    /* Optionen fuer das Format-Pulldown.

       ACHTUNG: RICH-TEXT STEHT DRIN UND IST ABGESCHALTET. Das ist Absicht und keine
       Nachlaessigkeit: Exchange kann ueber EWS nur `HTML` oder `Text` als
       BodyType setzen (an exchangelib gemessen), und was Outlook "Rich-Text"
       nennt, ist TNEF (winmail.dat). Wer den Eintrag weglaesst, beantwortet die
       Frage "warum fehlt Rich-Text?" nirgends; wer ihn waehlbar macht und HTML
       daraus macht, behauptet etwas, das nicht passiert. */
    function formatOptionen(gewaehlt) {
        // LEER heisst "keine Vorgabe gesetzt", und das ist seit 2026-08-26
        // HTML. Deshalb wird auf 'text' geprueft und nicht auf 'html' - eine
        // Pruefung auf 'html' zeigte fuer ein unberuehrtes Postfach "Nur Text"
        // an, waehrend der Server HTML sendet: eine Anzeige, die einen Zustand
        // behauptet, den sie nicht kennt.
        var vorgabe = ((_konto || {}).antwort_format || '') === 'text'
            ? T('mail.fmt_text', 'Nur Text') : 'HTML';
        var h = '<option value=""' + (gewaehlt ? '' : ' selected') + '>' +
            esc(T('mail.fmt_default', 'Vorgabe') + ' (' + vorgabe + ')') + '</option>' +
            '<option value="html"' + (gewaehlt === 'html' ? ' selected' : '') + '>HTML</option>' +
            '<option value="text"' + (gewaehlt === 'text' ? ' selected' : '') + '>' +
            esc(T('mail.fmt_text', 'Nur Text')) + '</option>' +
            '<option value="richtext" disabled title="' +
            esc(T('mail.fmt_rtf_why',
                  'Exchange kann über EWS nur HTML oder Text setzen – Rich-Text (winmail.dat) ist nicht möglich.')) +
            '">' + esc(T('mail.fmt_rtf', 'Rich-Text (nicht möglich)')) + '</option>';
        return h;
    }

    /* ── Bestaetigung ─────────────────────────────────────────────────── */
    /* NIE `window.confirm` im Aufgabenfenster.

       GEMELDET 2026-08-19: Der Klick auf "Regel loeschen" loeschte nichts. In
       Office-Aufgabenfenstern (WebView2) sind alert/confirm/prompt je nach Host
       unterdrueckt; `confirm()` liefert dann keinen Wert, und das Muster
       `if (!window.confirm(...)) return;` bricht WORTLOS ab – der Knopf sieht
       kaputt aus, obwohl Endpunkt und Bindung in Ordnung sind.

       Rueckgabe ist ein Promise<boolean>. Fehlt das Markup (sollte nie sein),
       wird mit `true` aufgeloest: der Benutzer hat den Knopf bereits gedrueckt,
       die Rueckfrage ist Schutz vor dem Fehlgriff – und "tut wortlos nichts"
       waere genau der gemeldete Fehler. */
    var _askFertig = null;

    function askSchliessen(antwort) {
        var box = $('ad-ask');
        if (box) box.classList.add('hidden');
        var f = _askFertig;
        _askFertig = null;
        if (f) f(!!antwort);
    }

    function frage(text, jaText, gefahr) {
        return new Promise(function (fertig) {
            var box = $('ad-ask'), t = $('ad-ask-text'),
                ja = $('ad-ask-yes'), nein = $('ad-ask-no');
            if (!box || !t || !ja || !nein) { fertig(true); return; }
            // Ein zweiter Aufruf bei offenem Dialog: den ersten sauber abschliessen.
            if (_askFertig) askSchliessen(false);
            _askFertig = fertig;
            t.textContent = String(text || '');
            ja.textContent = jaText || T('addin.ask_yes', 'Ja');
            ja.className = 'ad-btn' + (gefahr ? ' ad-btn-danger' : '');
            box.classList.remove('hidden');
            // Fokus auf ABBRECHEN – bei einer Loeschfrage ist das der sichere
            // Vorbelegungswert, und Enter darf nicht versehentlich loeschen.
            try { nein.focus(); } catch (e) { }
        });
    }

    function askBinden() {
        var ja = $('ad-ask-yes'), nein = $('ad-ask-no'), box = $('ad-ask');
        if (ja) ja.addEventListener('click', function () { askSchliessen(true); });
        if (nein) nein.addEventListener('click', function () { askSchliessen(false); });
        // Klick auf die Flaeche = Abbrechen, Klick IN die Box nicht.
        if (box) box.addEventListener('click', function (e) {
            if (e.target === box) askSchliessen(false);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && _askFertig) { e.preventDefault(); askSchliessen(false); }
        });
    }

    /* ── Reiter: Postfach ─────────────────────────────────────────────── */
    function fuelleKonto() {
        if (!$('ad-adresse')) return;
        var k = _konto || {};
        // Die Stilliste wird gezeichnet, nicht in ein Eingabefeld geschrieben –
        // sie darf deshalb auch aktualisiert werden, waehrend jemand tippt.
        _stile = k.stile || [];
        zeichneStile();
        // Wie die Stile: gezeichnet, nicht in ein Eingabefeld geschrieben – darf
        // also auch aktualisiert werden, waehrend jemand tippt.
        _signaturen = k.signaturen || [];
        zeichneSignaturen();
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
        // Leer in der Datei heisst "keine Vorgabe" - und die ist seit
        // 2026-08-26 HTML. Das Pulldown kennt keinen leeren Eintrag: hier wird
        // eine Vorgabe GESETZT, nicht von einer geerbt - ein drittes
        // "unbestimmt" waere in diesem Feld sinnlos. Geprueft wird auf 'text',
        // sonst zeigte ein unberuehrtes Postfach "Nur Text" an, waehrend der
        // Server HTML sendet.
        if ($('ad-format')) $('ad-format').value = (k.antwort_format === 'text') ? 'text' : 'html';
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
            // KEIN `antwort_vorgabe`: die Stile haengen an eigenen Endpunkten.
            // Ebenso KEINE `signaturen` - eine Liste, die ein Formular als
            // Ganzes sendet, ueberschreibt bei zwei offenen Fenstern den
            // jeweils anderen Stand. `antwort_format` ist ein einzelner Wert
            // und darf mit.
            antwort_format: (($('ad-format') || {}).value === 'html') ? 'html' : 'text',
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
        frage(T('mail.acct_del_confirm',
                'Zugangsdaten wirklich entfernen? Deine Regeln bleiben erhalten, laufen aber nicht mehr.'),
              T('common.delete', 'Löschen'), true)
            .then(function (ja) { if (ja) loescheKontoJetzt(); });
    }

    function loescheKontoJetzt() {
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
        officeErmitteln().then(function () {
            start();
            // NACH officeErmitteln, weil die Pruefung `_officeDa` braucht;
            // unabhaengig von `start()`, weil sie ohne Anmeldung auskommt und
            // auch auf dem Anmeldebildschirm gelten soll.
            versionPruefen();
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', los);
    } else { los(); }
})();
