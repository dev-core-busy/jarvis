/* Anmeldung ueber das Firmenkonto (IdP) in den Office-Add-ins (Outlook, Excel).

   EINE Quelle fuer beide Aufgabenfenster: zwei Kopien desselben Ablaufs liefen
   beim naechsten Feinschliff auseinander (Register: Kopien laufen auseinander).

   ABLAUF (Vertrag mit backend/main.py, App-Anmeldung ueber den IdP):
     1. GET /api/login/oidc/status -> {aktiv, ad_modus}. Nur bei aktiv UND
        vorhandener Dialog-API (office.js, Office.context.ui.displayDialogAsync)
        und WebCrypto erscheint der Knopf; sonst bleibt die Maske exakt wie
        bisher (Kennwortanmeldung offen, kein Knopf).
     2. Klick: verifier (32 Zufallsbytes, base64url), challenge = SHA-256 davon,
        zustand (16 Zufallsbytes). Der Office-Dialog oeffnet
        /api/login/oidc/start?app=<app>&challenge=..&zustand=.. auf DIESEM
        Ursprung; der Server leitet zum IdP und am Ende auf
        /addin/idp-fertig.html, die das Ergebnis per messageParent meldet.
     3. Nachricht {code, zustand} bzw. {fehler, zustand}. Ein fremder zustand
        wird VERWORFEN – er gehoert nicht zu der Anmeldung, die dieses Fenster
        begonnen hat.
     4. POST /api/login/oidc/app-einloesen {code, verifier} -> Token. Der
        verifier verlaesst das Fenster erst hier: ein abgefangener Code allein
        ist wertlos (PKCE).

   KENNWORTANMELDUNG ALS NOTWEG: bei ad_modus "fallback" eingeklappt (Link
   darunter klappt auf) und von selbst offen, sobald die IdP-Anmeldung
   scheitert; bei "zusaetzlich" immer sichtbar. Dieselbe Regel wie im Portal
   (idp_anmeldung.js).

   Kein window.confirm/alert: in Office-Aufgabenfenstern (WebView2) unterdrueckt.
*/
(function () {
    'use strict';

    // Benutzer hat das Dialogfenster geschlossen (Office-Fehlercode).
    var DIALOG_GESCHLOSSEN = 12006;

    function b64url(bytes) {
        var s = '';
        for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
        return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    function zufall(n) {
        var a = new Uint8Array(n);
        window.crypto.getRandomValues(a);
        return b64url(a);
    }
    function challengeAus(verifier) {
        var roh = new TextEncoder().encode(verifier);
        return window.crypto.subtle.digest('SHA-256', roh).then(function (h) {
            return b64url(new Uint8Array(h));
        });
    }
    function kryptoDa() {
        try {
            return !!(window.crypto && window.crypto.getRandomValues && window.crypto.subtle &&
                typeof window.crypto.subtle.digest === 'function' &&
                typeof TextEncoder === 'function');
        } catch (e) { return false; }
    }
    function dialogDa() {
        try {
            return !!(window.Office && Office.context && Office.context.ui &&
                typeof Office.context.ui.displayDialogAsync === 'function');
        } catch (e) { return false; }
    }

    /* opts: {app, praefix, T, tokenSetzen, weiter}
       Erwartetes Markup (praefix "ad" bzw. "xl"):
         #<p>-idp            Block mit Knopf (Vorgabe hidden)
         #<p>-idp-btn        der Knopf
         #<p>-idp-status     Statuszeile unter dem Knopf
         #<p>-idp-kennwort   Link "Mit Benutzername und Kennwort anmelden"
         #<p>-kennwort       Kennwortmaske (Felder + Anmelden-Knopf) */
    function einrichten(opts) {
        var p = opts.praefix;
        var T = opts.T;
        var _status = null;      // Promise der Statusabfrage (einmal je Fenster)
        var _lage = null;        // {aktiv, ad_modus} nach der Abfrage
        var _laeuft = false;
        var _offen = false;      // Kennwortmaske ausdruecklich aufgeklappt

        function $(id) { return document.getElementById(id); }

        function melde(text, art, kreis) {
            var e = $(p + '-idp-status');
            if (!e) return;
            e.textContent = '';
            if (kreis) {
                var k = document.createElement('span');
                k.className = 'jv-pkg-spin';
                k.setAttribute('aria-hidden', 'true');
                e.appendChild(k);
                e.appendChild(document.createTextNode(' '));
            }
            e.appendChild(document.createTextNode(text || ''));
            e.style.color = art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
        }

        function verfuegbar() {
            return !!(_lage && _lage.aktiv && dialogDa() && kryptoDa());
        }

        // Sichtbarkeit von Knopf, Link und Kennwortmaske – EINE Stelle.
        function anwenden() {
            var block = $(p + '-idp'), link = $(p + '-idp-kennwort'),
                maske = $(p + '-kennwort');
            var an = verfuegbar();
            if (block) block.classList.toggle('hidden', !an);
            var zu = an && _lage.ad_modus !== 'zusaetzlich' && !_offen;
            if (maske) maske.classList.toggle('hidden', zu);
            if (link) link.classList.toggle('hidden', !zu);
        }

        function kennwortAufklappen() {
            _offen = true;
            anwenden();
            var u = $(p + '-user');
            if (u && !u.value) { try { u.focus(); } catch (e) { } }
        }

        function statusHolen() {
            if (!_status) {
                _status = fetch('/api/login/oidc/status')
                    .then(function (r) { return r.ok ? r.json() : {}; })
                    .catch(function () { return {}; })
                    .then(function (d) {
                        _lage = { aktiv: !!(d && d.aktiv === true),
                                  ad_modus: (d && d.ad_modus) || 'fallback' };
                        return _lage;
                    });
            }
            return _status;
        }

        // Aufruf aus zeigeLogin(): Status (einmal) holen und anwenden.
        function anzeigen() {
            anwenden();
            return statusHolen().then(anwenden);
        }

        function fertig() {
            _laeuft = false;
            var b = $(p + '-idp-btn');
            if (b) b.disabled = false;
        }

        function scheitern(text) {
            fertig();
            melde(text, 'fehler');
            kennwortAufklappen();
        }

        function fehlerText(kennung) {
            var allg = T('login.idp_err.allgemein', 'Die Anmeldung über das Firmenkonto ist fehlgeschlagen.');
            if (!kennung || !/^[a-z_]{1,40}$/.test(String(kennung))) return allg;
            return T('login.idp_err.' + kennung, allg);
        }

        function einloesen(code, verifier) {
            return fetch('/api/login/oidc/app-einloesen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code, verifier: verifier })
            }).then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { ok: r.ok, d: d || {} }; });
            }).then(function (a) {
                if (!a.ok || !a.d.success || !a.d.token) {
                    scheitern(a.d.error || (a.d.abgelaufen ? fehlerText('abgelaufen')
                        : fehlerText('')));
                    return;
                }
                opts.tokenSetzen(a.d.token);
                fertig();
                melde('');
                opts.weiter();
            }).catch(function () {
                scheitern(T('login.server_error', 'Server nicht erreichbar'));
            });
        }

        function starten() {
            if (_laeuft || !verfuegbar()) return;
            _laeuft = true;
            var b = $(p + '-idp-btn');
            if (b) b.disabled = true;
            melde(T('login.idp_laeuft', 'Anmeldung über das Firmenkonto läuft …'), '', true);
            var verifier, zustand;
            try {
                verifier = zufall(32);
                zustand = zufall(16);
            } catch (e) {
                scheitern(fehlerText(''));
                return;
            }
            challengeAus(verifier).then(function (challenge) {
                var url = location.origin + '/api/login/oidc/start?app=' +
                    encodeURIComponent(opts.app) + '&challenge=' + encodeURIComponent(challenge) +
                    '&zustand=' + encodeURIComponent(zustand);
                Office.context.ui.displayDialogAsync(url,
                    { height: 60, width: 30, promptBeforeOpen: false },
                    function (res) {
                        if (!res || String(res.status).toLowerCase() !== 'succeeded' || !res.value) {
                            scheitern(T('login.idp_err.dialog',
                                'Das Anmeldefenster ließ sich nicht öffnen. Bitte mit Kennwort anmelden.'));
                            return;
                        }
                        var dialog = res.value;
                        var erledigt = false;
                        function zu() {
                            erledigt = true;
                            try { dialog.close(); } catch (e) { }
                        }
                        dialog.addEventHandler(Office.EventType.DialogMessageReceived, function (arg) {
                            if (erledigt) return;
                            var m = null;
                            try { m = JSON.parse(arg && arg.message); } catch (e) { m = null; }
                            zu();
                            // Fremder oder fehlender zustand: diese Antwort gehoert
                            // nicht zu der Anmeldung, die hier begonnen wurde.
                            if (!m || typeof m !== 'object' || m.zustand !== zustand) {
                                scheitern(T('login.idp_err.zustand',
                                    'Die Rückmeldung des Anmeldefensters gehört nicht zu dieser Anmeldung. Bitte erneut versuchen.'));
                                return;
                            }
                            if (m.fehler || !m.code) {
                                scheitern(fehlerText(m.fehler));
                                return;
                            }
                            einloesen(String(m.code), verifier);
                        });
                        dialog.addEventHandler(Office.EventType.DialogEventReceived, function (arg) {
                            if (erledigt) return;
                            erledigt = true;
                            if (arg && arg.error === DIALOG_GESCHLOSSEN) {
                                // Selbst geschlossen: kein Fehler, nur zurueck.
                                fertig();
                                melde('');
                                return;
                            }
                            scheitern(T('login.idp_err.dialog',
                                'Das Anmeldefenster ließ sich nicht öffnen. Bitte mit Kennwort anmelden.'));
                        });
                    });
            }).catch(function () {
                scheitern(fehlerText(''));
            });
        }

        var b = $(p + '-idp-btn');
        if (b) b.addEventListener('click', starten);
        var l = $(p + '-idp-kennwort');
        if (l) l.addEventListener('click', function (ev) {
            if (ev && ev.preventDefault) ev.preventDefault();
            kennwortAufklappen();
        });

        return { anzeigen: anzeigen, starten: starten, verfuegbar: verfuegbar };
    }

    window.OfficeIdp = { einrichten: einrichten };
})();
