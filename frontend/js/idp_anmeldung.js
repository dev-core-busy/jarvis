/* ═══════════════════════════════════════════════════════════════════
   Anmeldung ueber den IdP (OpenID Connect) – Anmeldemaske auf "/"

   1. Zeigt den Knopf "Mit Firmenkonto anmelden (SSO)", wenn der Server die
      IdP-Anmeldung meldet (/api/login/oidc/status). Der Knopf ist ein Link
      auf /api/login/oidc/start; der Server leitet zum IdP weiter.
   2. Nach der Rueckkehr (/?anmeldung=idp) liegt ein kurzlebiger Einloese-
      Schein im HttpOnly-Cookie. Diese Datei tauscht ihn per fetch gegen die
      Sitzung (/api/login/oidc/einloesen) – auf demselben Weg wie die
      Kennwortanmeldung (Sitzungs-Cookie + CSRF-Token in der Antwort).
      Einen Zwei-Faktor-Code fragt der Server dabei nie ab (Betreiberentscheid
      2026-11-20); Administratoren holen ihre Rechte am Zahnrad.
   3. Fehler (/?idp_fehler=<kennung>) stehen in #login-error, uebersetzt.
   4. Kennwortanmeldung (AD, #kennwort-bereich) neben dem IdP: der Server
      meldet ad_modus (die Vorgabe entscheidet der Server, seit 2026-11-20
      "fallback"). "zusaetzlich" -> immer sichtbar. "fallback"
      (Einstellung "AD-Anmeldung minimiert anzeigen") -> eingeklappt, bis die
      Anmeldung ueber den IdP scheitert (Fehlerkennung, Einloesen abgelehnt,
      Server nicht erreichbar) ODER jemand sie ueber den Link
      #btn-kennwort-zeigen aufklappt (Notfall-Anmeldung, 2026-11-20: faellt
      der IdP still aus, ohne eine Fehlerkennung zu liefern, gab es vorher
      keinen Weg zur Kennwortmaske). Der Link ist genau dann sichtbar, wenn
      der Bereich verborgen ist. FAIL-OPEN: jeder Zweifel
      (Status nicht lesbar, keine Antwort binnen SICHERUNG_MS, IdP aus) zeigt
      sie – ein verstecktes Formular ohne funktionierenden IdP sperrte alle
      aus. Damit die Maske nicht kurz aufblitzt, merkt sich der Browser den
      letzten Modus (localStorage) und verbirgt nur dann schon vor dem Status.

   5. Haken "Automatisch anmelden" (#idp-auto, je Browser in localStorage):
      gesetzt, startet die Seite "/" die Anmeldung ueber den IdP ohne Klick.
      NICHT, wenn (autoGrund):
        - die Seite von einer anderen Jarvis-Seite aus geoeffnet wurde
          (gleicher Ursprung im Referrer). So endet jedes Abmelden – alle
          Abmeldeknoepfe fuehren per location.replace('/') hierher (Waechter
          test_abmelden_ziel.js). Wer sich abmeldet, will nicht sofort wieder
          angemeldet sein; und es braucht keine Marke an jedem Abmeldeweg.
        - die Adresse eine Rueckkehr vom IdP traegt (anmeldung=idp, idp_fehler):
          ein Fehler bleibt stehen, statt in eine Schleife zu laufen.
        - in diesem Tab schon vor weniger als AUTO_SPERRE_MS automatisch
          gestartet wurde (Schleifenbremse, falls die Anmeldung zwar gelingt,
          die Folgeseite aber wieder auf "/" zurueckfuehrt).
      Liegt beim Laden ein Token vor, prueft app.js es erst; gestartet wird
      dann nur, wenn app.js die Maske wegen eines ungueltigen Tokens zeigt
      (Ereignis 'jarvis-anmeldemaske') – sonst liefen Weiterleitung aufs
      Portal und zum IdP um die Wette.

   6. EIN Servername (wechselGrund): meldet der Status einen `ursprung` (die
      fest eingetragene Rueckkehradresse) und steht die Seite unter einem
      anderen, wechselt "/" vorab dorthin – bevor Maske und Haken erscheinen.
      Sonst laege der Haken (localStorage gilt je Ursprung) unter dem einen
      Namen und Anmeldung samt Sitzung unter dem anderen; nach dem Abmelden
      stand er leer da (DEV 2026-11-19). Dieselben Schranken wie in Punkt 5
      (Pfad, Rueckkehr vom IdP, mitgebrachtes Token). Die Adresse traegt
      `umgeleitet=1` bzw. `=2` (= kam von einer Jarvis-Seite, also vom
      Abmelden): der Referrer geht ueber den Ursprungswechsel verloren
      (Referrer-Policy same-origin), die Marke nimmt seine Aussage mit. Und
      sie ist der Schleifenschutz: wer schon umgeleitet wurde, wechselt nicht
      noch einmal (Server sieht sich hinter einem Proxy unter anderem Namen).

   Die Kennwortanmeldung (app.js) selbst bleibt unberuehrt; /api/login ist in
   beiden Modi erreichbar (Ausweichweg, Apps, Add-in, Notfallkonto).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function T(key, def) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return def;
    }
    function $(id) { return document.getElementById(id); }

    // Kennungen aus backend/main.py (_oidc_zurueck) und oidc_anmeldung.OidcFehler.code
    var FEHLER = {
        nicht_eingerichtet: 'Die Anmeldung über das Firmenkonto ist auf diesem Server nicht eingerichtet.',
        zu_viele: 'Zu viele Anmeldeversuche. Bitte warte 5 Minuten.',
        abgelaufen: 'Die Anmeldung über das Firmenkonto ist abgelaufen. Bitte erneut versuchen.',
        abgebrochen: 'Die Anmeldung beim Firmenkonto wurde abgebrochen.',
        nicht_erreichbar: 'Der Anmeldedienst des Unternehmens ist gerade nicht erreichbar.',
        konfiguration: 'Die Anmeldung über das Firmenkonto ist falsch eingerichtet. Bitte den Administrator informieren.',
        idp: 'Der Anmeldedienst des Unternehmens hat die Anmeldung abgelehnt.',
        token: 'Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.',
        schluessel: 'Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.',
        name: 'Das Firmenkonto passt zu keinem Benutzer dieses Servers.',
        lokal: 'Dieses Konto lässt sich nur mit Kennwort anmelden.',
        gesperrt: 'Das Konto ist nach zu vielen Fehlversuchen vorübergehend gesperrt.',
        keine_freigabe: 'Keine Anmeldeberechtigung.',
        pruefung: 'Die Anmeldeberechtigung ist gerade nicht prüfbar. Bitte mit Kennwort anmelden.',
        lizenz: 'Die Zahl der Benutzer für diese Lizenz ist erreicht.'
    };

    function fehlerZeigen(ziel, text) {
        var e = $(ziel);
        if (!e) return;
        e.textContent = text;
        e.hidden = false;
    }

    var MERK = 'jarvis_idp_ad_modus';
    var SICHERUNG_MS = 4000;
    var ausgewichen = false;   // IdP-Anmeldung gescheitert -> Kennwort bleibt sichtbar

    function merken(modus) {
        try { if (modus) localStorage.setItem(MERK, modus); else localStorage.removeItem(MERK); }
        catch (e) { /* ohne Speicher: nur Aufblitzen moeglich */ }
    }
    function gemerkt() {
        try { return localStorage.getItem(MERK) || ''; } catch (e) { return ''; }
    }
    function kennwortZeigen(an) {
        var b = $('kennwort-bereich'), tr = $('idp-trenner'), k = $('btn-idp-login');
        var link = $('btn-kennwort-zeigen');
        if (b) b.hidden = !an;
        if (link) link.hidden = !!an;   // Aufklappen nur, solange es etwas aufzuklappen gibt
        if (tr) tr.hidden = !an;   // "oder" nur, wenn es etwas zu waehlen gibt
        // Allein auf der Maske ist der IdP-Knopf der Hauptknopf (Aussehen wie "Anmelden").
        if (k) k.classList.toggle('btn-idp-haupt', !an);
    }
    function ausweichen() {
        ausgewichen = true;
        kennwortZeigen(true);
    }

    // Notfall-Anmeldung: der Link klappt die Kennwortanmeldung auf. Ueber
    // ausweichen(), damit eine spaeter eintreffende Statusantwort "fallback"
    // sie nicht wieder einklappt.
    function aufklappVerdrahten() {
        var link = $('btn-kennwort-zeigen');
        if (!link) return;
        link.addEventListener('click', function () {
            ausweichen();
            var feld = $('login-username');
            if (feld) feld.focus();
        });
    }

    function adresseAufraeumen() {
        // Kennungen nicht im Verlauf stehen lassen (ein Neuladen wuerde sonst
        // erneut einloesen bzw. den alten Fehler zeigen).
        try { history.replaceState(null, '', '/'); } catch (e) { /* egal */ }
    }

    // ── Automatisch anmelden (Punkt 5 im Kopf) ─────────────────────────────
    var AUTO = 'jarvis_idp_auto';              // localStorage: '1' = Haken gesetzt
    var AUTO_ZEIT = 'jarvis_idp_auto_zeit';    // sessionStorage: letzter Start in diesem Tab
    var AUTO_SPERRE_MS = 60000;
    var autoLage = { aktiv: null, maske: false, rueckkehr: false, erledigt: false,
                     ursprung: '', umgeleitet: '' };
    var navigieren = function (url) { window.location.assign(url); };

    function autoGewuenscht() {
        try { return localStorage.getItem(AUTO) === '1'; } catch (e) { return false; }
    }
    function autoMerken(an) {
        try { if (an) localStorage.setItem(AUTO, '1'); else localStorage.removeItem(AUTO); }
        catch (e) { /* ohne Speicher gibt es keinen Haken ueber den Besuch hinaus */ }
    }
    function vonJarvis() {
        // Ueber einen Ursprungswechsel (Punkt 6) mitgebracht: dort war es eine Jarvis-Seite.
        if (autoLage.umgeleitet === '2') return true;
        // Referrer-Policy ist same-origin (sicherheits_kopf.py): von einer
        // Jarvis-Seite kommt der volle Ursprung mit, von aussen nichts.
        try { return !!document.referrer && new URL(document.referrer).origin === window.location.origin; }
        catch (e) { return false; }
    }

    // Leer = jetzt auf den Ursprung der Rueckkehradresse wechseln (Punkt 6).
    function wechselGrund(l) {
        if (!l.ursprung) return 'kein_ursprung';
        if (l.ursprung === l.hier) return 'gleicher_ursprung';
        if (l.pfad !== '/') return 'nicht_wurzel';
        if (l.rueckkehr) return 'idp_rueckkehr';
        if (l.umgeleitet) return 'schon_umgeleitet';
        if (!l.maske) return 'token_pruefung';
        return '';
    }
    function letzterStart() {
        try { return parseInt(sessionStorage.getItem(AUTO_ZEIT) || '0', 10) || 0; } catch (e) { return 0; }
    }

    // Leer = automatisch starten, sonst der Grund dagegen. EINE Entscheidung,
    // damit jede Regel einzeln messbar ist (tests/test_idp_anmeldung_ui.js).
    function autoGrund(l) {
        if (!l.gewuenscht) return 'aus';
        if (!l.aktiv) return 'idp_aus';
        if (l.pfad !== '/') return 'pfad';
        if (l.rueckkehr) return 'rueckkehr';
        if (l.vonJarvis) return 'von_jarvis';
        if (l.letzter && l.jetzt - l.letzter >= 0 && l.jetzt - l.letzter < AUTO_SPERRE_MS) return 'schleife';
        if (!l.maske) return 'maske';
        return '';
    }

    // Rueckgabe true = die Seite verlaesst sich gerade (Wechsel oder Start).
    function autoVersuchen() {
        // `erledigt` und die Schleifenbremse decken sich, solange sessionStorage
        // geht. Bei gesperrtem Speicher (privater Modus) traegt nur diese Marke:
        // ein zweites Ereignis von app.js startete sonst ein zweites Mal.
        if (autoLage.erledigt || autoLage.aktiv === null) return false;
        if (autoLage.aktiv) {
            var wg = wechselGrund({
                ursprung: autoLage.ursprung,
                hier: window.location.origin,
                pfad: window.location.pathname,
                rueckkehr: autoLage.rueckkehr,
                umgeleitet: autoLage.umgeleitet,
                maske: autoLage.maske
            });
            if (wg === 'token_pruefung') return false;   // app.js prueft noch das Token
            if (!wg) {
                autoLage.erledigt = true;
                navigieren(autoLage.ursprung + '/?umgeleitet=' + (vonJarvis() ? '2' : '1'));
                return true;
            }
        }
        var grund = autoGrund({
            gewuenscht: autoGewuenscht(),
            aktiv: autoLage.aktiv,
            pfad: window.location.pathname,
            rueckkehr: autoLage.rueckkehr,
            vonJarvis: vonJarvis(),
            letzter: letzterStart(),
            jetzt: Date.now(),
            maske: autoLage.maske
        });
        if (grund === 'maske') return false;   // app.js prueft noch das Token – spaeter erneut
        autoLage.erledigt = true;
        if (grund) return false;
        try { sessionStorage.setItem(AUTO_ZEIT, String(Date.now())); } catch (e) { /* Bremse fehlt dann */ }
        var k = $('btn-idp-login');
        navigieren((k && k.getAttribute('href')) || '/api/login/oidc/start');
        return true;
    }

    function autoHakenVerdrahten() {
        var cb = $('idp-auto');
        if (!cb) return;
        cb.checked = autoGewuenscht();
        // Nur auf change hoeren: das <label> schaltet selbst um.
        cb.addEventListener('change', function () { autoMerken(cb.checked); });
    }

    // Vor app.js geladen (settings.html) – das Ereignis kann also nicht verpasst werden.
    document.addEventListener('jarvis-anmeldemaske', function () {
        autoLage.maske = true;
        autoVersuchen();
    });

    function knopfZeigen() {
        var box = $('idp-login');
        if (!box) return;
        var entschieden = false;
        var sicherung = setTimeout(function () {
            if (!entschieden) kennwortZeigen(true);
        }, SICHERUNG_MS);
        function fertig(aktiv, modus, ursprung) {
            entschieden = true;
            clearTimeout(sicherung);
            merken(aktiv ? modus : '');
            autoLage.aktiv = !!aktiv;
            autoLage.ursprung = aktiv ? (ursprung || '') : '';
            // Verlaesst die Seite sich gleich, bleibt die Maske, wie sie ist –
            // sonst blitzen Knopf und Haken unter dem falschen Namen kurz auf.
            if (autoVersuchen()) return;
            box.hidden = !aktiv;
            kennwortZeigen(!aktiv || modus !== 'fallback' || ausgewichen);
        }
        fetch('/api/login/oidc/status', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var aktiv = !!(d && d.aktiv);
                // Nur ein ausdrueckliches "fallback" verbirgt das Kennwort (fail-open).
                fertig(aktiv, aktiv && d.ad_modus === 'fallback' ? 'fallback' : 'zusaetzlich',
                       aktiv && typeof d.ursprung === 'string' ? d.ursprung : '');
            })
            .catch(function () { fertig(false, ''); });
    }

    async function erfolg(data) {
        var token = data.token;
        localStorage.setItem('jarvis_token', token);
        localStorage.setItem('jarvis_user', data.username || '');
        if (data.account_blocked) {
            if (window.SecurityIncidents) {
                window.SecurityIncidents.showBlockedScreen(data.block_reason, data.block_incidents);
            }
            return;
        }
        // Zweiter Schritt wie nach der Kennwortanmeldung (app.js): weitere
        // Anmeldungen (SAP, Jira …), falls fuer diesen Benutzer noetig.
        if (window.ZugangAnmeldung) {
            try { await window.ZugangAnmeldung.schritt(token); } catch (e) { /* weiter */ }
        }
        window.location.replace('/portal');
    }

    var laeuft = false;
    async function einloesen() {
        if (laeuft) return;
        laeuft = true;
        try {
            var res = await fetch('/api/login/oidc/einloesen', {
                method: 'POST',
                headers: window.JarvisSitzung.anmeldeKopf({ 'Content-Type': 'application/json' }),
                body: '{}'
            });
            var data = {};
            try { data = await res.json(); } catch (e) { data = {}; }
            if (data.success && data.token) {
                await erfolg(data);
            } else {
                ausweichen();
                fehlerZeigen('login-error', data.error || T('login.failed', 'Anmeldung fehlgeschlagen.'));
            }
        } catch (e) {
            ausweichen();
            fehlerZeigen('login-error', T('login.server_error', 'Server nicht erreichbar.'));
        } finally {
            laeuft = false;
        }
    }

    var gestartet = false;
    function start() {
        // Genau einmal: ein zweiter Lauf saehe die schon aufgeraeumte Adresse,
        // hielte eine Rueckkehr vom IdP fuer einen frischen Aufruf und startete
        // "Automatisch anmelden" (jsdom feuert DOMContentLoaded nach einem
        // haendischen Ausloesen noch einmal – so gesehen, 2026-11-19).
        if (gestartet) return;
        gestartet = true;
        var q;
        try { q = new URLSearchParams(window.location.search); } catch (e) { q = null; }
        var fehler = q ? q.get('idp_fehler') : '';
        // Vor dem Status nur verbergen, wenn dieser Browser den Ausweich-Modus
        // schon kennt (sonst blitzte die Maske bei jedem ohne IdP kurz weg).
        if (fehler) ausweichen();
        else if (gemerkt() === 'fallback') kennwortZeigen(false);
        autoLage.rueckkehr = !!(fehler || (q && q.get('anmeldung') === 'idp'));
        // Marke eines Ursprungswechsels (Punkt 6): merken, dann aus der Adresse nehmen.
        var um = q ? (q.get('umgeleitet') || '') : '';
        if (um) {
            autoLage.umgeleitet = um === '2' ? '2' : '1';
            if (!autoLage.rueckkehr) adresseAufraeumen();
        }
        // Dieselbe Bedingung wie in app.js (`if (token)` -> erst pruefen).
        autoLage.maske = autoLage.maske || !window.JarvisSitzung.token();
        autoHakenVerdrahten();
        aufklappVerdrahten();
        knopfZeigen();
        if (!q) return;
        if (fehler) {
            adresseAufraeumen();
            fehlerZeigen('login-error', T('login.idp_err.' + fehler,
                FEHLER[fehler] || T('login.failed', 'Anmeldung fehlgeschlagen.')));
        } else if (q.get('anmeldung') === 'idp') {
            adresseAufraeumen();
            einloesen();
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.IdpAnmeldung = {
        _einloesen: einloesen, _FEHLER: FEHLER, _MERK: MERK,
        _AUTO: AUTO, _AUTO_ZEIT: AUTO_ZEIT, _autoGrund: autoGrund, _wechselGrund: wechselGrund,
        // Nur fuer Pruefstaende: jsdom kann nicht navigieren und verraet das Ziel nicht.
        _navigation: function (fn) { navigieren = fn; }
    };
})();
