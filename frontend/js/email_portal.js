/* ═══════════════════════════════════════════════════════════════════
   E-Mail-Bereich (/email) – Benutzerseite
   ───────────────────────────────────────────────────────────────────
   Drei Dinge auf einer Seite:
     1. Eigenes Postfach hinterlegen (Adresse, Anmeldename, Kennwort)
     2. Regeln pflegen – jede mit frei editierbarem Prompt
     3. Protokoll der Laeufe

   Nicht zu verwechseln mit `email.js`: das ist der EINSTELLUNGS-Reiter, in
   dem ein Administrator die Serverdaten und die Werkzeug-Freigabe pflegt.
   Hier arbeitet der Benutzer nur an SEINEM Postfach und SEINEN Regeln.

   Berechtigung: jeder Endpunkt haengt serverseitig an
   `require_email_access`, und jeder filtert zusaetzlich auf den angemeldeten
   Benutzer. Die Pruefung hier ist reine Benutzerfuehrung – wer nicht
   freigegeben ist, soll aufs Portal zurueck statt auf einer Seite voller
   403-Meldungen zu landen.

   DAS KENNWORT WIRD NIE ANGEZEIGT. Der Server liefert nur
   `passwort_gesetzt`; ein leeres Feld heisst beim Speichern
   "unveraendert" (sonst wuerde jedes Speichern der uebrigen Felder das
   Kennwort loeschen).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Gleiche Schluesselkette wie sap_portal.js/support.js – wer ueber /chat
    // angemeldet ist, soll sich hier nicht erneut anmelden muessen.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    var _status = null;      // /api/email/status
    var _regeln = [];
    var _bereiche = [];
    var _bereicheLang = '';  // in welcher Sprache der Katalog geholt wurde
    var _ordner = null;      // erst auf Bedarf geladen
    var _editId = null;      // welche Regel ist offen ('neu' = neue Regel)
    var _editHeim = null;    // Heimatplatz des wandernden Formulars
    var _stile = [];         // benannte Antwort-Stile des Postfachs
    var _stilEdit = null;    // welcher Stil ist offen ('neu' = neuer Stil)

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function sprache() { return (window._lang === 'en') ? 'en' : 'de'; }
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = localStorage.getItem(TOKEN_KEYS[i]);
            if (v) return v;
        }
        return '';
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function toPortal() { window.location.replace('/portal'); }
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
    function hole(url, opt) {
        return fetch(url, Object.assign({ headers: kopf() }, opt || {}))
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) {
                        if (!r.ok || d.ok === false) {
                            throw new Error(d.error || ('HTTP ' + r.status));
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

    /* ── Start ─────────────────────────────────────────────────────────── */
    function init() {
        if (!token()) { window.location.replace('/'); return; }
        fetch('/api/me', { headers: kopf() })
            .then(function (r) {
                if (r.status === 401) { window.location.replace('/'); return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (me) {
                if (!me) { toPortal(); return; }
                // Fail-closed: fehlt das Feld (aelteres Backend), gilt "nicht
                // freigegeben" – lieber zurueck aufs Portal als eine Seite, auf
                // der jeder Knopf 403 liefert.
                if (!(me.permissions && me.permissions.email)) { toPortal(); return; }
                zeigeApp();
            })
            .catch(function () { toPortal(); });
    }

    function zeigeApp() {
        $('em-app').classList.remove('hidden');
        binde();
        ladeStatus();
        ladeRegeln();
        ladeLog();
        if (window.refreshBranding) { try { window.refreshBranding(); } catch (e) {} }
    }

    /* ── Postfach ──────────────────────────────────────────────────────── */
    function ladeStatus() {
        return hole('/api/email/status?lang=' + sprache())
            .then(function (d) {
                _status = d;
                _bereiche = d.bereiche || [];
                _bereicheLang = sprache();
                zeigeKonto(d.konto || {});
                zeigeServerHinweis(d);
            })
            .catch(function (e) {
                melde('em-acct-status', e.message, 'fehler');
            });
    }

    function zeigeKonto(k) {
        var setz = function (id, wert) { var e = $(id); if (e) e.value = wert == null ? '' : wert; };
        setz('em-adresse', k.adresse);
        setz('em-benutzer', k.benutzer);
        setz('em-kanal-user', k.kanal || '');
        setz('em-ord-eingang', k.ordner_eingang);
        setz('em-ord-entwuerfe', k.ordner_entwuerfe);
        setz('em-ord-gesendet', k.ordner_gesendet);
        // Das frueher hier stehende Einzelfeld ist seit 2026-08-18 eine
        // LISTE benannter Stile mit eigenen Endpunkten (siehe zeichneStile).
        _stile = k.stile || [];
        zeichneStile();
        var akt = $('em-aktiv');
        // NICHT auf Falsyness pruefen: ein gespeichertes `false` muss als false
        // erscheinen, ein FEHLENDES Feld dagegen als Vorgabe true.
        if (akt) akt.checked = (k.aktiv === undefined ? true : !!k.aktiv);
        var pw = $('em-passwort');
        if (pw) pw.value = '';   // Kennwort wird nie vorbelegt
        melde('em-pw-hint', k.passwort_gesetzt
            ? T('mail.pw_set', '✓ Kennwort gespeichert (leer lassen = unverändert)')
            : T('mail.pw_unset', 'Noch kein Kennwort gespeichert.'));

        var pill = $('em-acct-pill');
        if (pill) {
            if (!k.vorhanden) {
                pill.textContent = T('mail.pill_none', 'kein Postfach');
                pill.className = 'em-pill is-off';
            } else if (!k.aktiv) {
                pill.textContent = T('mail.pill_off', 'inaktiv');
                pill.className = 'em-pill is-off';
            } else if (k.ausgesetzt) {
                // Eigene Stufe zwischen "inaktiv" und "Fehler": nicht der
                // Benutzer hat abgeschaltet, und es ist auch nicht irgendein
                // Fehler - die Automatik haelt sich bewusst zurueck.
                pill.textContent = T('mail.pill_paused', 'ausgesetzt');
                pill.className = 'em-pill is-off';
            } else if (k.letzter_fehler) {
                pill.textContent = T('mail.pill_error', 'Fehler');
                pill.className = 'em-pill is-off';
            } else {
                pill.textContent = k.adresse || T('mail.pill_ok', 'verbunden');
                pill.className = 'em-pill is-ok';
            }
        }
        var box = $('em-acct-result');
        if (box) {
            var h = '';
            // Der Aussetzer steht GANZ OBEN und nennt den Weg zurueck. Ein
            // Zustand, den der Benutzer nicht selbst gesetzt hat, muss erklaert
            // werden - sonst sucht er den Fehler in seiner Regel.
            if (k.ausgesetzt) {
                h += '<div class="em-paused"><b>'
                    + T('mail.paused_head', 'Automatik ausgesetzt') + '</b><br>'
                    + T('mail.paused_text',
                        'Die Anmeldung am Postfach ist mehrfach hintereinander '
                        + 'fehlgeschlagen. Damit dein Domänenkonto nicht gesperrt wird, '
                        + 'melden sich die Regeln nicht mehr an. Trag dein Kennwort neu '
                        + 'ein und drücke „Verbindung testen“ – gelingt die Anmeldung, '
                        + 'läuft alles von selbst weiter.')
                    + '</div>';
            }
            if (k.letzter_erfolg) {
                h += '<div class="em-hint">' + T('mail.last_ok', 'Zuletzt erfolgreich:')
                    + ' ' + esc(zeit(k.letzter_erfolg)) + '</div>';
            }
            if (k.letzter_fehler) {
                h += '<div class="em-hint" style="color:var(--danger);">'
                    + T('mail.last_err', 'Letzter Fehler:') + ' ' + esc(k.letzter_fehler) + '</div>';
            }
            box.innerHTML = h;
        }
    }

    function zeigeServerHinweis(d) {
        var s = d.server || {};
        var wege = [];
        if (s.ews) wege.push('EWS');
        if (s.imap) wege.push('IMAP');
        if (s.smtp) wege.push('SMTP');
        if (!wege.length) {
            melde('em-acct-status', T('mail.no_server',
                'Es ist noch kein Mailserver hinterlegt – bitte an den Administrator wenden.'),
                'fehler');
        }
    }

    function speichereKonto() {
        var daten = {
            adresse: (($('em-adresse') || {}).value || '').trim(),
            benutzer: (($('em-benutzer') || {}).value || '').trim(),
            kanal: ($('em-kanal-user') || {}).value || '',
            aktiv: !!(($('em-aktiv') || {}).checked),
            ordner_eingang: (($('em-ord-eingang') || {}).value || '').trim(),
            ordner_entwuerfe: (($('em-ord-entwuerfe') || {}).value || '').trim(),
            ordner_gesendet: (($('em-ord-gesendet') || {}).value || '').trim()
            // KEIN `antwort_vorgabe` mehr: die Stile haengen an eigenen
            // Endpunkten. Wuerde dieses Formular das Feld mitsenden, schriebe
            // ein Klick auf "Speichern" den Text des Standardstils mit dem
            // Formularstand - genau die Vermischung, die bei den SAP-Sicht-
            // barkeiten und den Rollen-Agenten schon Aerger gemacht hat.
        };
        var pw = (($('em-passwort') || {}).value || '');
        // Nur senden, wenn wirklich etwas eingegeben wurde – ein leeres Feld
        // bedeutet "unveraendert", nicht "loeschen".
        if (pw.trim()) daten.passwort = pw;
        melde('em-acct-status', T('common.saving', 'Speichere…'));
        return sende('/api/email/account', 'POST', daten)
            .then(function (d) {
                melde('em-acct-status', T('mail.acct_saved', '✓ Postfach gespeichert.'), 'ok');
                zeigeKonto(d.konto || {});
                _ordner = null;    // Ordnerliste kann sich geaendert haben
            })
            .catch(function (e) { melde('em-acct-status', e.message, 'fehler'); });
    }

    function testeKonto() {
        var b = $('em-test-acct');
        if (b) b.disabled = true;
        melde('em-acct-status', T('mail.testing', 'Verbinde… (kann bis zu einer halben Minute dauern)'));
        return sende('/api/email/test', 'POST')
            .then(function (d) {
                var r = d.ergebnis || {};
                melde('em-acct-status', T('mail.test_ok', '✓ Verbindung steht') + ' ('
                    + esc(r.kanal || '?') + ')', 'ok');
                var box = $('em-acct-result');
                if (box) {
                    var h = '<div class="em-hint"><b>' + esc(r.postfach || '') + '</b>';
                    if (r.server_version) h += ' · ' + esc(r.server_version);
                    if (r.eingang_gesamt >= 0) {
                        h += '<br>' + T('mail.inbox_count', 'Posteingang:') + ' '
                            + r.eingang_gesamt + ' / ' + r.eingang_ungelesen + ' '
                            + T('mail.unread', 'ungelesen');
                    }
                    box.innerHTML = h + '</div>';
                }
                ladeStatus();
            })
            .catch(function (e) { melde('em-acct-status', e.message, 'fehler'); })
            .finally(function () { if (b) b.disabled = false; });
    }

    function loescheKonto() {
        if (!window.confirm(T('mail.acct_del_confirm',
            'Zugangsdaten wirklich entfernen? Deine Regeln bleiben erhalten, laufen aber nicht mehr.'))) {
            return Promise.resolve();
        }
        return sende('/api/email/account', 'DELETE')
            .then(function () {
                melde('em-acct-status', T('mail.acct_deleted', 'Zugangsdaten entfernt.'), 'ok');
                ladeStatus();
            })
            .catch(function (e) { melde('em-acct-status', e.message, 'fehler'); });
    }

    /* Muster-Stiltext, den TAB in ein leeres Feld uebernimmt. Der PLATZHALTER
       taugt dafuer nicht – er zaehlt auf, was hineingehoert ("Signatur,
       Anrede-Form, …") und waere als Feldinhalt Unsinn. */
    var STIL_MUSTER = 'Antworte in der Sie-Form, sachlich und in h\u00f6chstens f\u00fcnf S\u00e4tzen.\n'
        + 'Best\u00e4tige zuerst kurz das Anliegen.\n'
        + 'Sage keine Preise, Rabatte oder Liefertermine zu.\n'
        + 'Schlie\u00dfe mit:\nMit freundlichen Gr\u00fc\u00dfen\n<Name>\n<Abteilung>';

    /* ── Stile fuer Antworten ──────────────────────────────────────────── */
    /* Eigene Endpunkte (/api/email/styles), NICHT das Postfach-Formular: die
       Liste wird Eintrag fuer Eintrag gepflegt, und ein Formular, das sie als
       Ganzes sendet, wuerde bei zwei offenen Fenstern den jeweils anderen
       Stand ueberschreiben. Deshalb speichert jeder Knopf hier sofort. */
    function zeichneStile() {
        var box = $('em-stile-list');
        if (!box) return;
        // Ein offenes Formular wuerde beim Neuaufbau mitgeloescht - erst
        // heimholen (gleiches Muster wie beim Regel-Formular).
        stilFormularHeim();
        if (!_stile.length) {
            box.innerHTML = '<div class="em-empty">' + esc(T('mail.styles_none',
                'Noch kein Stil angelegt. Ohne Stil wird neutral geantwortet.')) + '</div>';
            return;
        }
        box.innerHTML = _stile.map(function (e) {
            var vorschau = (e.text || '').replace(/\s+/g, ' ').slice(0, 110);
            return '<div class="em-stil-card' + (e.standard ? ' is-std' : '') +
                '" data-stil="' + esc(e.id) + '">' +
                '<div class="em-stil-row"><div class="em-stil-main">' +
                '<div class="em-stil-name">' + esc(e.name) +
                (e.standard ? '<span class="em-stil-badge">\u25CF ' +
                    esc(T('mail.style_default', 'Standard')) + '</span>' : '') + '</div>' +
                '<div class="em-stil-meta">' + (vorschau ? esc(vorschau) :
                    esc(T('mail.style_empty', '(kein Text hinterlegt)'))) + '</div>' +
                '</div><div class="em-stil-acts">' +
                (e.standard ? '' : '<button class="em-icon-btn" data-act="std" title="' +
                    esc(T('mail.style_make_default', 'Als Standard setzen')) + '">\u25CB</button>') +
                '<button class="em-icon-btn" data-act="edit" title="' +
                esc(T('common.edit', 'Bearbeiten')) + '">\u270E</button>' +
                '<button class="em-icon-btn is-danger" data-act="del" title="' +
                esc(T('common.delete', 'Löschen')) + '">\u2715</button>' +
                '</div></div></div>';
        }).join('');
        box.querySelectorAll('.em-icon-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var karte = b.closest('.em-stil-card');
                var id = karte.getAttribute('data-stil');
                var act = b.getAttribute('data-act');
                if (act === 'edit') oeffneStilFormular(id, karte);
                else if (act === 'del') loescheStil(id);
                else if (act === 'std') setzeStandard(id);
            });
        });
        if (_stilEdit && _stilEdit !== 'neu') {
            var k = box.querySelector('.em-stil-card[data-stil="' + _stilEdit + '"]');
            if (k) k.appendChild($('em-stil-edit'));
        }
    }

    var _stilHeim = null;
    function stilFormularHeim() {
        var f = $('em-stil-edit');
        if (!f) return;
        if (!_stilHeim) _stilHeim = f.parentNode;
        if (f.parentNode !== _stilHeim) _stilHeim.appendChild(f);
    }

    function schliesseStilFormular() {
        _stilEdit = null;
        var f = $('em-stil-edit');
        if (!f) return;
        stilFormularHeim();
        f.innerHTML = '';
        f.className = 'hidden';
    }

    function oeffneStilFormular(id, karte) {
        var f = $('em-stil-edit');
        if (!f) return;
        // Zweiter Klick auf denselben Eintrag schliesst wieder.
        if (_stilEdit === (id || 'neu')) { schliesseStilFormular(); return; }
        if (!_stilHeim) _stilHeim = f.parentNode;
        _stilEdit = id || 'neu';
        var e = id ? (_stile.filter(function (x) { return x.id === id; })[0] || {}) : {};
        var g = (_status && _status.grenzen) || {};
        f.className = id ? 'em-stil-edit' : '';
        f.innerHTML =
            '<div class="em-field" style="margin-top:12px;"><label>'
            + T('mail.style_name', 'Name des Stils') + '</label>'
            + '<input type="text" id="em-s-name" maxlength="' + (g.stil_name_max || 60)
            + '" placeholder="' + esc(T('mail.style_name_ph', 'z. B. Förmlich')) + '"></div>'
            + '<div class="em-field" style="margin-top:10px;"><label>'
            + T('mail.style_text', 'Stil und Signatur') + '</label>'
            + '<textarea id="em-s-text" rows="9" maxlength="' + (g.stil_text_max || 6000)
            + '" data-tabfill="' + esc(T('mail.style_text_suggest', STIL_MUSTER))
            + '" placeholder="' + esc(T('mail.acct_guide_ph',
                'z. B. Signatur, Anrede-Form, was nie zugesagt werden darf')) + '"></textarea>'
            + '<span class="em-hint">' + T('mail.acct_guide_hint',
                'Bestimmt nur den Ton – löst NIE eine Aktion aus.')
            + ' <span id="em-s-count"></span></span></div>'
            + '<div class="em-field" style="margin-top:10px;"><label>'
            + '<input type="checkbox" id="em-s-std" style="width:auto;margin-right:8px;">'
            + T('mail.style_is_default', 'Als Standard verwenden, wenn nichts gewählt ist')
            + '</label></div>'
            + '<div class="em-row"><button class="em-btn em-btn-primary" id="em-s-save">'
            + (id ? T('common.save', 'Speichern') : T('mail.style_create', 'Stil anlegen'))
            + '</button><button class="em-btn" id="em-s-cancel">'
            + T('common.cancel', 'Abbrechen') + '</button>'
            + '<span class="em-status" id="em-s-status"></span></div>';
        $('em-s-name').value = e.name || '';
        $('em-s-text').value = e.text || '';
        $('em-s-std').checked = !!e.standard || (!id && !_stile.length);
        zaehlerBinden($('em-s-text'), $('em-s-count'), (g.stil_text_max || 6000));
        $('em-s-save').addEventListener('click', function () { speichereStil(id); });
        $('em-s-cancel').addEventListener('click', schliesseStilFormular);
        if (karte) karte.appendChild(f); else stilFormularHeim();
        $('em-s-name').focus();
    }

    /* Zeichenzaehler, der sich erst ab 70%% meldet. Grund: `maxlength` schneidet
       im Browser STILL ab - wer eine lange Signatur einfuegt, merkt nur, dass
       das Ende fehlt. Dauerhaft sichtbar waere er dagegen Rauschen. */
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
        var daten = {
            name: (($('em-s-name') || {}).value || '').trim(),
            text: (($('em-s-text') || {}).value || ''),
            standard: !!(($('em-s-std') || {}).checked)
        };
        melde('em-s-status', T('common.saving', 'Speichere…'));
        var p = id ? sende('/api/email/styles/' + encodeURIComponent(id), 'PUT', daten)
            : sende('/api/email/styles', 'POST', daten);
        return p.then(function (d) {
            _stile = d.stile || [];
            schliesseStilFormular();
            zeichneStile();
            melde('em-stil-status', T('mail.style_saved', '✓ Stil gespeichert.'), 'ok');
            // Ein offenes Regel-Formular zeigt die Stilauswahl - sie muss den
            // neuen Namen kennen, sonst waehlt der Benutzer ins Leere.
            fuelleStilWahl();
        }).catch(function (e) { melde('em-s-status', e.message, 'fehler'); });
    }

    function setzeStandard(id) {
        return sende('/api/email/styles/' + encodeURIComponent(id), 'PUT', { standard: true })
            .then(function (d) {
                _stile = d.stile || [];
                zeichneStile();
                fuelleStilWahl();
            })
            .catch(function (e) { melde('em-stil-status', e.message, 'fehler'); });
    }

    function loescheStil(id) {
        var e = _stile.filter(function (x) { return x.id === id; })[0] || {};
        // Der Hinweis auf die Regeln ist wichtig: sie fallen danach auf den
        // Standard zurueck, und das soll niemanden ueberraschen.
        if (!window.confirm(T('mail.style_del_confirm',
            'Diesen Stil wirklich löschen? Regeln, die ihn benutzen, antworten danach im Standard-Stil.')
            + '\n\n' + (e.name || ''))) return Promise.resolve();
        return sende('/api/email/styles/' + encodeURIComponent(id), 'DELETE')
            .then(function (d) {
                _stile = d.stile || [];
                if (_stilEdit === id) schliesseStilFormular();
                zeichneStile();
                fuelleStilWahl();
                melde('em-stil-status', T('mail.style_deleted', 'Stil entfernt.'), 'ok');
            })
            .catch(function (e2) { melde('em-stil-status', e2.message, 'fehler'); });
    }

    /* Auswahlfeld im Regel-Formular neu befuellen (falls es offen steht). */
    function fuelleStilWahl() {
        var sel = $('em-f-stil');
        if (!sel) return;
        var alt = sel.value;
        sel.innerHTML = stilOptionen(alt);
    }

    function stilOptionen(gewaehlt) {
        var std = _stile.filter(function (e) { return e.standard; })[0];
        // DER STANDARD STEHT ALS ERSTER EINTRAG – mit `*` und mit dem WERT "".
        //
        // Das ist keine Kosmetik: "" heisst "nichts ausdruecklich gewaehlt", und
        // nur dann greift in einer Regel ein im Prompt genannter Stil. Wuerde
        // hier die KENNUNG des Standardstils stehen, waere das Feld immer
        // gesetzt und die sprachliche Nennung damit tot.
        //
        // Frueher stand an dieser Stelle "Standard – <Name>"; bei einem Stil
        // namens "Standard" kam "Standard – Standard" heraus (gemeldet
        // 2026-08-18). Der Name allein plus `*` sagt dasselbe kuerzer.
        var h = '<option value=""' + (gewaehlt ? '' : ' selected') + '>' + (std
            ? esc(std.name) + ' *'
            : esc(T('mail.style_opt_none', 'kein Stil'))) + '</option>';
        // Der Standard wird NICHT zusaetzlich mit eigener Kennung gelistet – er
        // waere sonst zweimal in der Liste, und genau das war das Problem.
        h += _stile.filter(function (e) { return !e.standard; }).map(function (e) {
            return '<option value="' + esc(e.id) + '"' +
                (gewaehlt === e.id ? ' selected' : '') + '>' + esc(e.name) + '</option>';
        }).join('');
        // "-" ist die ausdrueckliche Wahl "ohne Stil" – unterscheidbar von
        // "nichts gewaehlt" (leer). Ohne Stile waere sie sinnlos.
        if (_stile.length) {
            h += '<option value="-"' + (gewaehlt === '-' ? ' selected' : '') + '>' +
                esc(T('mail.style_opt_off', '– ohne Stil –')) + '</option>';
        }
        return h;
    }

    /* ── Regeln ────────────────────────────────────────────────────────── */
    function ladeRegeln() {
        return hole('/api/email/rules?lang=' + sprache())
            .then(function (d) {
                _regeln = d.regeln || [];
                if (d.bereiche) { _bereiche = d.bereiche; _bereicheLang = sprache(); }
                zeichneRegeln();
            })
            .catch(function (e) { melde('em-rules-status', e.message, 'fehler'); });
    }

    function heimHolen() {
        // FALLSTRICK: liegt das Formular in der Liste, wuerde innerHTML='' es
        // MITLOESCHEN (danach liefert getElementById null). Deshalb VOR dem
        // Neuaufbau heimholen – gleiches Muster wie bei der Extraktions-Vorschau
        // in /wissen und dem Rollen-Formular.
        var box = $('em-rule-edit');
        if (!box) return;
        if (!_editHeim) return;          // noch nie verschoben
        if (box.parentNode !== _editHeim) _editHeim.appendChild(box);
    }

    function zeichneRegeln() {
        heimHolen();
        var box = $('em-rules');
        if (!box) return;
        if (!_regeln.length) {
            box.innerHTML = '<div class="em-empty">'
                + T('mail.rules_empty', 'Noch keine Regel. Mit „+ Neue Regel" anfangen – '
                    + 'zum Beispiel: „Wenn eine Rechnung eingeht, verschiebe sie in den Ordner '
                    + 'Buchhaltung und antworte dem Absender mit einer kurzen Bestätigung."')
                + '</div>';
            if (_editId === 'neu') oeffneFormular(null, null);
            return;
        }
        var h = '';
        _regeln.forEach(function (r) {
            var bereiche = (r.bereiche || []).map(function (b) {
                var t = _bereiche.filter(function (x) { return x.id === b; })[0];
                return t ? t.name : b;
            }).join(', ');
            h += '<div class="em-rule-card' + (r.enabled ? '' : ' is-off') + '" data-rid="'
                + esc(r.id) + '">'
                + '<div class="em-rule-row">'
                + '<div class="em-rule-main">'
                + '<div class="em-rule-name">' + esc(r.name)
                + (r.enabled ? '' : '<span class="em-badge">' + T('mail.disabled', 'aus') + '</span>')
                + '</div>'
                + '<div class="em-rule-meta">' + esc(r.ordner || 'INBOX') + ' · '
                + T('mail.every', 'alle') + ' ' + (r.intervall_min || 5) + ' min · '
                + esc(bereiche)
                + (r.letzter_lauf ? ' · ' + T('mail.last_run', 'zuletzt') + ' '
                    + esc(zeit(r.letzter_lauf)) : '')
                + '</div></div>'
                + '<div class="em-rule-acts">'
                + '<button class="em-icon-btn" data-act="toggle" title="'
                + (r.enabled ? T('mail.pause', 'Regel anhalten') : T('mail.resume', 'Regel aktivieren'))
                + '">' + (r.enabled ? '⏸' : '▶') + '</button>'
                // Monochrome TEXTZEICHEN, keine Emojis: 🗑/⚡ werden je nach System
                // farbig gerendert und folgen keinem Theme (dieselbe Regel wie bei
                // .kb-hdr-btn und dem ⧉-Fund im Medien-Kontextmenue).
                + '<button class="em-icon-btn" data-act="run" title="'
                + T('mail.testrun', 'Jetzt testen (neueste passende Nachricht)') + '">⟳</button>'
                + '<button class="em-icon-btn" data-act="edit" title="'
                + T('common.edit', 'Bearbeiten') + '">✎</button>'
                + '<button class="em-icon-btn is-danger" data-act="del" title="'
                + T('common.delete', 'Löschen') + '">✕</button>'
                + '</div></div></div>';
        });
        box.innerHTML = h;

        box.querySelectorAll('.em-icon-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var karte = b.closest('.em-rule-card');
                var rid = karte && karte.dataset.rid;
                var r = _regeln.filter(function (x) { return x.id === rid; })[0];
                if (!r) return;
                var act = b.dataset.act;
                if (act === 'toggle') return schalte(r);
                if (act === 'run') return testlauf(r, b);
                if (act === 'edit') return (_editId === r.id)
                    ? schliesseFormular() : oeffneFormular(r, karte);
                if (act === 'del') return loescheRegel(r);
            });
        });

        // Ein offenes Formular wieder unter seine Zeile setzen
        if (_editId && _editId !== 'neu') {
            var karte = box.querySelector('.em-rule-card[data-rid="' + _editId + '"]');
            var r = _regeln.filter(function (x) { return x.id === _editId; })[0];
            if (karte && r) oeffneFormular(r, karte);
        } else if (_editId === 'neu') {
            oeffneFormular(null, null);
        }
    }

    function schalte(r) {
        // Sendet AUSSCHLIESSLICH `enabled` – sonst schriebe der Schalter den
        // Formularstand mit (der Merge laeuft ueber die Feld-Whitelist).
        return sende('/api/email/rules/' + encodeURIComponent(r.id), 'PUT',
            { enabled: !r.enabled })
            .then(ladeRegeln)
            .catch(function (e) { melde('em-rules-status', e.message, 'fehler'); });
    }

    function loescheRegel(r) {
        if (!window.confirm(T('mail.rule_del_confirm', 'Regel „%s" wirklich löschen?')
            .replace('%s', r.name))) return Promise.resolve();
        return sende('/api/email/rules/' + encodeURIComponent(r.id), 'DELETE')
            .then(function () {
                if (_editId === r.id) { _editId = null; }
                melde('em-rules-status', T('mail.rule_deleted', 'Regel gelöscht.'), 'ok');
                return ladeRegeln();
            })
            .catch(function (e) { melde('em-rules-status', e.message, 'fehler'); });
    }

    function testlauf(r, knopf) {
        if (knopf) knopf.disabled = true;
        melde('em-rules-status', T('mail.testrun_wait',
            'Testlauf läuft – das Modell arbeitet wirklich (kann Minuten dauern).'));
        return sende('/api/email/rules/' + encodeURIComponent(r.id) + '/run', 'POST')
            .then(function (d) {
                var b = d.bericht || {};
                if (b.fehler) {
                    melde('em-rules-status', b.fehler, 'fehler');
                } else if (!b.verarbeitet) {
                    melde('em-rules-status', T('mail.testrun_none',
                        'Keine passende, noch unverarbeitete Nachricht gefunden.'));
                } else {
                    var a = (b.aktionen || [])[0] || {};
                    melde('em-rules-status', '✓ ' + (a.ergebnis || T('mail.testrun_ok', 'Lauf beendet.')), 'ok');
                }
                return ladeLog();
            })
            .catch(function (e) { melde('em-rules-status', e.message, 'fehler'); })
            .finally(function () { if (knopf) knopf.disabled = false; });
    }

    /* ── Regel-Formular (wandert, aber es gibt nur EINES) ──────────────── */
    function oeffneFormular(r, karte) {
        var box = $('em-rule-edit');
        if (!box) return;
        // Heimatplatz NUR beim ersten Verschieben merken – ein erneutes Auslesen
        // wuerde die verschobene Position als "Heimat" festschreiben.
        if (!_editHeim) _editHeim = box.parentNode;
        _editId = r ? r.id : 'neu';

        var neu = !r;
        r = r || { name: '', prompt: '', ordner: 'INBOX', bereiche: ['mail'],
                   intervall_min: 5, max_je_lauf: 3, nur_ungelesen: true,
                   markiere_gelesen: false, von_filter: '', betreff_filter: '',
                   enabled: true };

        var g = (_status && _status.grenzen) || {};
        box.className = 'em-edit-box';
        box.innerHTML =
            '<div class="em-grid" style="margin-top:14px;">'
            + '<div class="em-field"><label>' + T('mail.f_name', 'Name der Regel') + '</label>'
            + '<input type="text" id="em-f-name" maxlength="120"></div>'
            + '<div class="em-field"><label>' + T('mail.f_folder', 'Ordner') + '</label>'
            + '<input type="text" id="em-f-ordner" list="em-ordner-liste" placeholder="INBOX">'
            + '<datalist id="em-ordner-liste"></datalist></div>'
            + '</div>'
            + '<div class="em-field" style="margin-top:12px;">'
            + '<label>' + T('mail.f_prompt', 'Prompt – was soll mit der Nachricht geschehen?') + '</label>'
            + '<textarea id="em-f-prompt" data-tabfill maxlength="' + (g.prompt_max || 8000) + '" placeholder="'
            + esc(T('mail.f_prompt_ph',
                'Beispiel: Prüfe, ob es sich um eine Rechnung handelt. Wenn ja, verschiebe die '
                + 'Nachricht in den Ordner Buchhaltung und antworte dem Absender mit einer kurzen '
                + 'Eingangsbestätigung. Wenn Angaben fehlen, speichere stattdessen einen Entwurf.'))
            + '"></textarea>'
            + '<span class="em-hint">' + T('mail.f_prompt_hint',
                'Das Modell wählt die Aktion selbst. Schreib klar, was zutreffen muss und was dann '
                + 'passieren soll – und was im Zweifel NICHT passieren darf.') + '</span></div>'
            + '<div class="em-field" style="margin-top:12px;">'
            + '<label>' + T('mail.f_style', 'Stil für Antworten dieser Regel') + '</label>'
            + '<select id="em-f-stil">' + stilOptionen(r.stil || '') + '</select>'
            + '<span class="em-hint">' + T('mail.f_style_hint',
                'Bestimmt nur den Ton. Ohne Auswahl gilt der Standard-Stil – oder der Stil, '
                + 'den du im Prompt beim Namen nennst („Antworte im Stil ‚Förmlich‘“). '
                + 'Eine Auswahl hier gewinnt gegen die Nennung im Prompt.') + '</span></div>'
            + '<div class="em-field" style="margin-top:12px;">'
            + '<label>' + T('mail.f_areas', 'Werkzeuge, die diese Regel benutzen darf') + '</label>'
            + '<div class="em-tools" id="em-f-areas"></div></div>'
            + '<div class="em-grid em-grid-3" style="margin-top:12px;">'
            + '<div class="em-field"><label>' + T('mail.f_interval', 'Prüfen alle … Minuten') + '</label>'
            + '<input type="number" id="em-f-intervall" min="' + (g.min_intervall || 1)
            + '" max="' + (g.max_intervall || 1440) + '"></div>'
            + '<div class="em-field"><label>' + T('mail.f_max', 'Nachrichten je Durchgang') + '</label>'
            + '<input type="number" id="em-f-max" min="1" max="' + (g.max_je_lauf || 10) + '"></div>'
            + '<div class="em-field"><label>' + T('mail.f_from', 'Nur von diesen Absendern') + '</label>'
            + '<input type="text" id="em-f-von" placeholder="rechnung@, @lieferant.de, name@*"></div>'
            + '</div>'
            // Der Hinweis ist nicht Kosmetik: am 2026-08-17 stand eine
            // Absender-Bedingung NUR im Prompt, das Feld war leer - die Regel
            // hat daraufhin zwei fremde Empfaenger angeschrieben.
            + '<span class="em-hint">' + T('mail.f_from_hint',
                'WICHTIG: Wenn die Regel nur bei bestimmten Absendern gelten soll, gehört das '
                + 'hier hinein – nicht ins Prompt. Nur dieses Feld wird geprüft, bevor ein '
                + 'Sprachmodell die Nachricht überhaupt sieht; im Prompt ist eine Bedingung nur '
                + 'eine Bitte, die falsch bewertet werden kann. Mehrere durch Komma, '
                + '* als Platzhalter. Leer = alle Absender.') + '</span>'
            + '<div class="em-grid" style="margin-top:12px;">'
            + '<div class="em-field"><label>' + T('mail.f_subject', 'Nur Betreff enthält (optional)') + '</label>'
            + '<input type="text" id="em-f-betreff" placeholder="Rechnung, Invoice, AW:*"></div>'
            + '<div class="em-field" style="justify-content:flex-end;gap:8px;">'
            + '<label><input type="checkbox" id="em-f-unread" style="width:auto;margin-right:8px;">'
            + T('mail.f_unread', 'nur ungelesene Nachrichten') + '</label>'
            + '<label><input type="checkbox" id="em-f-read" style="width:auto;margin-right:8px;">'
            + T('mail.f_read', 'nach Bearbeitung als gelesen markieren') + '</label>'
            + '</div></div>'
            + '<div class="em-row">'
            + '<button class="em-btn em-btn-primary" id="em-f-save">'
            + (neu ? T('mail.f_create', 'Regel anlegen') : T('common.save', 'Speichern')) + '</button>'
            + '<button class="em-btn" id="em-f-cancel">' + T('common.cancel', 'Abbrechen') + '</button>'
            + '<span class="em-status" id="em-f-status"></span>'
            + '</div>';
        box.classList.remove('hidden');

        // Werte setzen (nach dem Aufbau, damit die Felder existieren)
        $('em-f-name').value = r.name || '';
        $('em-f-ordner').value = r.ordner || 'INBOX';
        $('em-f-prompt').value = r.prompt || '';
        $('em-f-intervall').value = r.intervall_min || 5;
        $('em-f-max').value = r.max_je_lauf || 3;
        $('em-f-von').value = r.von_filter || '';
        $('em-f-betreff').value = r.betreff_filter || '';
        if ($('em-f-stil')) $('em-f-stil').value = r.stil || '';
        $('em-f-unread').checked = (r.nur_ungelesen === undefined ? true : !!r.nur_ungelesen);
        $('em-f-read').checked = !!r.markiere_gelesen;
        zeichneBereichsWahl(r.bereiche || ['mail']);
        fuelleOrdner();

        $('em-f-save').addEventListener('click', function () { speichereRegel(neu ? null : _editId); });
        $('em-f-cancel').addEventListener('click', schliesseFormular);

        // Formular wird KIND der Karte – zwei Elemente, die wie eines aussehen
        // sollen, muessen ineinander liegen (sonst bleibt ein Spalt sichtbar).
        if (karte) karte.appendChild(box);
        else if (_editHeim) _editHeim.appendChild(box);
    }

    function zeichneBereichsWahl(gewaehlt) {
        var box = $('em-f-areas');
        if (!box) return;
        box.innerHTML = '';
        var frei = _bereiche.filter(function (b) { return b.freigegeben; });
        if (!frei.length) {
            box.innerHTML = '<span class="em-hint">' + T('mail.no_areas',
                'Der Administrator hat noch keine Werkzeuge freigegeben.') + '</span>';
            return;
        }
        frei.forEach(function (b) {
            var lab = document.createElement('label');
            if (b.pflicht) lab.className = 'is-locked';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = b.id;
            cb.checked = b.pflicht || gewaehlt.indexOf(b.id) >= 0;
            if (b.pflicht) cb.disabled = true;
            lab.appendChild(cb);
            var t = document.createElement('span');
            t.innerHTML = '<b>' + esc(b.name) + (b.id === 'voll' ? ' ⚠' : '') + '</b><br>'
                + '<span class="em-hint">' + esc(b.hinweis || '') + '</span>';
            lab.appendChild(t);
            box.appendChild(lab);
        });
    }

    function fuelleOrdner() {
        var dl = $('em-ordner-liste');
        if (!dl) return;
        var mal = function () {
            dl.innerHTML = '';
            (_ordner || []).forEach(function (o) {
                var op = document.createElement('option');
                op.value = o.pfad || o.name;
                dl.appendChild(op);
            });
        };
        if (_ordner) { mal(); return; }
        // Nur EINMAL laden, und die Liste ist reine Bequemlichkeit: das Formular
        // steht auch ohne sie (Freitextfeld). Eine Maske, die auf eine
        // schmueckende Abfrage wartet, ist der Fehler vom 2026-08-11.
        hole('/api/email/folders')
            .then(function (d) { _ordner = d.ordner || []; mal(); })
            .catch(function () { _ordner = []; });
    }

    function speichereRegel(id) {
        var bereiche = [];
        document.querySelectorAll('#em-f-areas input[type="checkbox"]').forEach(function (cb) {
            if (cb.checked) bereiche.push(cb.value);
        });
        var daten = {
            name: ($('em-f-name') || {}).value || '',
            ordner: (($('em-f-ordner') || {}).value || '').trim() || 'INBOX',
            prompt: ($('em-f-prompt') || {}).value || '',
            bereiche: bereiche,
            intervall_min: parseInt(($('em-f-intervall') || {}).value, 10),
            max_je_lauf: parseInt(($('em-f-max') || {}).value, 10),
            von_filter: (($('em-f-von') || {}).value || '').trim(),
            betreff_filter: (($('em-f-betreff') || {}).value || '').trim(),
            stil: (($('em-f-stil') || {}).value || ''),
            nur_ungelesen: !!(($('em-f-unread') || {}).checked),
            markiere_gelesen: !!(($('em-f-read') || {}).checked)
        };
        if (isNaN(daten.intervall_min)) delete daten.intervall_min;
        if (isNaN(daten.max_je_lauf)) delete daten.max_je_lauf;

        melde('em-f-status', T('common.saving', 'Speichere…'));
        var p = id
            ? sende('/api/email/rules/' + encodeURIComponent(id), 'PUT', daten)
            : sende('/api/email/rules', 'POST', daten);
        return p.then(function (d) {
            // Formular AUFRAEUMEN, nicht nur die Kennung vergessen: `ladeRegeln`
            // holt den Container zwar heim, leert ihn aber nicht – ohne
            // schliesseFormular() blieb das gefuellte Formular unter der Liste
            // stehen (vom UI-Test gefunden).
            schliesseFormular();
            melde('em-rules-status', T('mail.rule_saved', '✓ Regel gespeichert.'), 'ok');
            return ladeRegeln();
        }).catch(function (e) { melde('em-f-status', e.message, 'fehler'); });
    }

    // Der Sprachwechsel baut das Formular neu auf (die Beschriftungen entstehen
    // beim Oeffnen aus T()). Ohne diese beiden Helfer waere ein Klick auf DE/EN
    // mitten im Tippen Datenverlust – deshalb Stand sichern und zuruecklegen.
    var FORM_FELDER = ['em-f-name', 'em-f-ordner', 'em-f-prompt', 'em-f-intervall',
                       'em-f-max', 'em-f-von', 'em-f-betreff', 'em-f-stil'];
    function formularStand() {
        if (!_editId || !$('em-f-name')) return null;
        var s = { id: _editId, werte: {}, haken: {}, bereiche: [] };
        FORM_FELDER.forEach(function (f) { s.werte[f] = ($(f) || {}).value || ''; });
        ['em-f-unread', 'em-f-read'].forEach(function (f) {
            s.haken[f] = !!(($(f) || {}).checked);
        });
        document.querySelectorAll('#em-f-areas input[type="checkbox"]').forEach(function (cb) {
            if (cb.checked) s.bereiche.push(cb.value);
        });
        return s;
    }
    function formularStandSetzen(s) {
        if (!s || _editId !== s.id || !$('em-f-name')) return;
        FORM_FELDER.forEach(function (f) { if ($(f)) $(f).value = s.werte[f]; });
        Object.keys(s.haken).forEach(function (f) { if ($(f)) $(f).checked = s.haken[f]; });
        zeichneBereichsWahl(s.bereiche);
    }

    function schliesseFormular() {
        _editId = null;
        var box = $('em-rule-edit');
        if (!box) return;
        heimHolen();
        box.innerHTML = '';
        box.className = 'hidden';
    }

    /* ── Protokoll ─────────────────────────────────────────────────────── */
    function ladeLog() {
        return hole('/api/email/log?limit=60')
            .then(function (d) { zeichneLog(d.eintraege || []); })
            .catch(function (e) { melde('em-log-status', e.message, 'fehler'); });
    }

    function zeichneLog(eintraege) {
        var box = $('em-log');
        if (!box) return;
        melde('em-log-status', eintraege.length
            ? (eintraege.length + ' ' + T('mail.log_entries', 'Einträge'))
            : '');
        if (!eintraege.length) {
            box.innerHTML = '<div class="em-empty">'
                + T('mail.log_empty', 'Noch keine Läufe. Sobald eine Regel eine Nachricht '
                    + 'bearbeitet, steht hier, was sie getan hat.') + '</div>';
            return;
        }
        var h = '<div class="em-scroll">';
        eintraege.forEach(function (e) {
            h += '<div class="em-log-row' + (e.ok === false ? ' is-bad' : '') + '">'
                + '<div class="em-log-head">'
                + '<b>' + esc(e.regel || '?') + '</b>'
                + (e.testlauf ? '<span class="em-badge">' + T('mail.test', 'Test') + '</span>' : '')
                + '<span class="em-log-time">' + esc(zeit(e.ts)) + '</span>'
                + '</div>';
            if (e.mail_betreff || e.mail_von) {
                h += '<div class="em-log-time">' + esc(e.mail_von || '?') + ' — '
                    + esc(e.mail_betreff || T('mail.log_nosubject', '(kein Betreff)')) + '</div>';
            }
            h += '<div class="em-log-res">' + esc(e.ergebnis || '') + '</div></div>';
        });
        box.innerHTML = h + '</div>';
    }

    /* ── Einklappbare Karten ───────────────────────────────────────────── */
    var KLAPP_KEY = 'jarvis_email_zu';   // Liste der ZUGEKLAPPTEN Karten

    function klappZustand() {
        try {
            var v = JSON.parse(localStorage.getItem(KLAPP_KEY) || '[]');
            return Array.isArray(v) ? v : [];
        } catch (e) { return []; }
    }
    function klappMerken(liste) {
        try { localStorage.setItem(KLAPP_KEY, JSON.stringify(liste)); } catch (e) { }
    }
    function klappInit() {
        // Gespeichert werden die ZUGEKLAPPTEN – so ist die Vorgabe fuer einen
        // neuen Benutzer "alles offen" (verhaltensgleich zu vorher), und eine
        // spaeter ergaenzte Karte ist automatisch offen statt still versteckt.
        var zu = klappZustand();
        document.querySelectorAll('.em-card[data-klapp]').forEach(function (karte) {
            var id = karte.getAttribute('data-klapp');
            var kopf = karte.querySelector('.em-card-head');
            if (!kopf) return;
            setzeKlapp(karte, zu.indexOf(id) >= 0);
            kopf.addEventListener('click', function (ev) {
                // OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile die
                // Karte zu. Heute steht dort nichts ausser dem Titel – wer
                // spaeter einen Knopf ergaenzt (z.B. "Aktualisieren"), waere
                // sonst ratlos. Gleiche Regel wie in lm.js::klappInit.
                if (ev.target.closest('button, input, label, a, select, textarea')) return;
                umschalten(karte);
            });
            // Mit der Tastatur bedienbar: das Element ist ein role="button",
            // also muessen Enter und Leertaste wirken.
            kopf.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                    ev.preventDefault();
                    umschalten(karte);
                }
            });
        });
    }
    function setzeKlapp(karte, zu) {
        karte.classList.toggle('is-zu', !!zu);
        var kopf = karte.querySelector('.em-card-head');
        if (kopf) kopf.setAttribute('aria-expanded', zu ? 'false' : 'true');
    }
    function umschalten(karte) {
        var id = karte.getAttribute('data-klapp');
        var zu = !karte.classList.contains('is-zu');
        setzeKlapp(karte, zu);
        var liste = klappZustand().filter(function (x) { return x !== id; });
        if (zu) liste.push(id);
        klappMerken(liste);
    }

    /* ── Bindung ───────────────────────────────────────────────────────── */
    /* Feld-Erklaerungen (ⓘ). EIN delegierter Listener am Dokument statt einer
       Bindung je Knopf: so wirkt jedes spaeter ergaenzte ⓘ automatisch, auch in
       Bereichen, die erst nachtraeglich gezeichnet werden. Der Knopf traegt
       `data-help` mit der Id des Erklaerkastens. */
    function infoInit() {
        if (document._emInfoBound) return;
        document._emInfoBound = true;
        document.addEventListener('click', function (e) {
            var knopf = e.target && e.target.closest && e.target.closest('.em-info');
            if (!knopf) return;
            e.preventDefault();
            var kasten = document.getElementById(knopf.getAttribute('data-help') || '');
            if (!kasten) return;
            var offen = kasten.classList.toggle('is-open');
            knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
        });
    }

    function binde() {
        var b;
        klappInit();
        infoInit();
        if ((b = $('em-save-acct'))) b.addEventListener('click', speichereKonto);
        if ((b = $('em-test-acct'))) b.addEventListener('click', testeKonto);
        if ((b = $('em-del-acct'))) b.addEventListener('click', loescheKonto);
        if ((b = $('em-log-reload'))) b.addEventListener('click', ladeLog);
        // Anleitung zum Outlook-Add-in auf-/zuklappen. Die Beschriftung folgt
        // dem Zustand – ein Umschalter mit unveraenderlichem Text sieht beim
        // Zuklappen wie ein wirkungsloser Klick aus (Lehre vom Audit-Log-Knopf).
        //
        // ACHTUNG, hier lag ein Fehler: `var b` wird in dieser Funktion
        // MEHRFACH zugewiesen. Eine Closure ueber `b` sieht beim Klick den
        // ZULETZT zugewiesenen Wert – der Handler beschriftete dadurch den
        // Abmelde-Knopf oben rechts mit "Anleitung ausblenden" (im DOM-Abzug
        // gefunden, im Markup unsichtbar). Die uebrigen Bindungen hier
        // uebergeben benannte Funktionen und benutzen `b` nicht; wer eine
        // Inline-Funktion ergaenzt, braucht eine EIGENE Variable.
        var hilfeKnopf = $('em-addin-help');
        if (hilfeKnopf) hilfeKnopf.addEventListener('click', function () {
            var box = $('em-addin-steps');
            if (!box) return;
            var zu = box.classList.toggle('hidden');
            hilfeKnopf.textContent = zu ? T('mail.addin_howto', 'Anleitung anzeigen')
                : T('mail.addin_howto_hide', 'Anleitung ausblenden');
            // Damit der Knopf nach einem Sprachwechsel den richtigen Text
            // bekommt, merkt sich das Element seinen Zustand statt ihn aus der
            // Beschriftung zurueckzulesen.
            hilfeKnopf.dataset.i18n = zu ? 'mail.addin_howto' : 'mail.addin_howto_hide';
        });
        var stilNeu = $('em-stil-neu');
        if (stilNeu) stilNeu.addEventListener('click', function () {
            oeffneStilFormular(null, null);
        });
        if ((b = $('em-new-rule'))) b.addEventListener('click', function () {
            if (_editId === 'neu') { schliesseFormular(); return; }
            _editId = 'neu';
            oeffneFormular(null, null);
        });
        if ((b = $('em-portal-btn'))) b.addEventListener('click', function () {
            window.location.href = '/portal';
        });
        // Sprachwechsel: Bereichsnamen und -hinweise kommen UEBERSETZT vom
        // Server (sie stehen dort neben der Werkzeugliste, damit Text und
        // Wirkung nicht auseinanderlaufen) – applyLang() erreicht sie deshalb
        // nicht, ebenso wenig die per T() zusammengesetzten Zeilen der Liste.
        // Der Vergleich mit `_bereicheLang` verhindert einen zweiten Abruf beim
        // Seitenaufbau, wo applyLang() dasselbe Ereignis feuert (Muster aus
        // sap_portal.js).
        window.addEventListener('jarvis-lang-changed', function () {
            if (_bereicheLang === sprache()) return;
            var offen = formularStand();
            ladeStatus();
            ladeRegeln().then(function () { formularStandSetzen(offen); });
            ladeLog();
        });
        if ((b = $('em-logout-btn'))) b.addEventListener('click', function () {
            // Signal MUSS raus, bevor der Token verworfen wird (sonst ist die
            // Abmeldung nicht mehr authentifizierbar); keepalive, weil die Seite
            // unmittelbar danach wegnavigiert.
            var p = (window.JarvisSession ? window.JarvisSession.logout() : Promise.resolve());
            TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
            p.catch(function () {}).then(function () { window.location.replace('/'); });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
