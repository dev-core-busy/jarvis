/* ────────────────────────────────────────────────────────────────────────────
   activity.js – meldet ECHTE Benutzer-Aktivitaet an die Anwesenheitsliste.

   WARUM ES DIESE DATEI GIBT
   Bis 2026-08-13 galt serverseitig die Faustregel "GET = nachsehen, alles
   andere = tun" (main.py::_note_activity). Damit zaehlte NUR eine veraendernde
   Anfrage als Handlung – und ein Benutzer, der die Seite neu laedt, den
   Info-Ordner oeffnet, einen Chat-Verlauf aufschlaegt oder ein Dokument
   anklickt, stand weiter mit "untaetig seit 2 Std." in der Liste. Gemeldet
   wurde genau das: F5 gedrueckt, Ordner geklickt, trotzdem "untaetig seit
   2 Std. 37 Min.".

   Die Regel liess sich nicht einfach auf GET ausweiten: die Oberflaechen
   fragen staendig Zustaende ab (LLM-Status alle 30 s, CPU alle 3 s,
   Ungelesen-Zaehler, Fortschritte, die Anwesenheitsliste selbst). Wuerde jeder
   dieser Abrufe zaehlen, waere jeder offene Tab dauerhaft "aktiv" und die
   Anzeige wertlos.

   Deshalb wird hier das gemessen, was die Anzeige BEHAUPTET: eine Handlung
   eines Menschen (Seite geoeffnet, geklickt, getippt, Tab zurueckgeholt).
   Automatische Abrufe koennen das nicht ausloesen – sie kommen ohne Klick.

   FAIL-SAFE-RICHTUNG: Wird diese Datei auf einer Seite vergessen, meldet sie
   dort zu WENIG (die Seite verhaelt sich wie vorher, veraendernde Anfragen
   zaehlen weiterhin). Der umgekehrte Weg – eine Poll-Sperrliste im Backend –
   waere bei einem vergessenen Eintrag zu VIEL und machte die Anzeige
   unbrauchbar. Deshalb diese Richtung.

   Bewusst NICHT gemeldet werden Mausbewegung und Scrollen: eine verschobene
   Maus ist keine Handlung, und "untaetig" soll etwas aussagen.
   ──────────────────────────────────────────────────────────────────────────── */
(function () {
    'use strict';

    // Hoechstens eine Meldung je Minute. Der Endpunkt schreibt die Buchhaltung
    // sofort auf Platte (user_sessions.note_action) – bei jedem Klick zu senden
    // waere verschwendete Schreiblast fuer eine Anzeige, die in Minuten rechnet.
    var ABSTAND_MS = 60000;

    // Gleiche Kette wie support.js/chatlib.js – je nach Seite liegt der Token
    // unter einem anderen Schluessel.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    var _letzte = 0;
    var _aus = false;      // nach 401/403: nicht weiter klopfen
    var _laeuft = false;

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var v = localStorage.getItem(TOKEN_KEYS[i]);
                if (v) return v;
            } catch (e) { return ''; }
        }
        return '';
    }

    /* Seitenkennung aus dem Pfad: "/portal" -> "portal", "/" -> "" .
       Der Server nimmt nur bekannte Kennungen an (Whitelist) – der Wert wird
       zur Beschriftung in einer Admin-Ansicht. */
    function seite() {
        try {
            var p = (location.pathname || '').replace(/^\/+|\/+$/g, '');
            return p.split('/')[0].replace(/\.html$/, '').toLowerCase();
        } catch (e) { return ''; }
    }

    function melde(erzwingen) {
        if (_aus || _laeuft) return;
        var now = Date.now();
        if (!erzwingen && now - _letzte < ABSTAND_MS) return;
        var tk = token();
        if (!tk) return;                     // nicht angemeldet – nichts zu melden
        _letzte = now;
        _laeuft = true;
        fetch('/api/activity', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + tk, 'Content-Type': 'application/json' },
            body: JSON.stringify({ page: seite() })
        }).then(function (r) {
            // 401/403 = abgemeldet, gesperrt oder Recht entzogen. Weiter zu
            // senden wuerde nur Journal und Verstosszaehler fuellen.
            if (r.status === 401 || r.status === 403) _aus = true;
        }).catch(function () {
            // Netzfehler: nichts melden, beim naechsten Klick erneut versuchen.
            _letzte = 0;
        }).then(function () { _laeuft = false; });
    }

    function bei(ereignis, fn) {
        try { document.addEventListener(ereignis, fn, { capture: true, passive: true }); }
        catch (e) { document.addEventListener(ereignis, fn, true); }
    }

    // pointerdown deckt Maus UND Touch ab; keydown das Tippen.
    bei('pointerdown', function () { melde(false); });
    bei('keydown', function () { melde(false); });

    // Tab zurueckgeholt = der Mensch ist wieder da.
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) melde(false);
    });

    // Seitenaufbau ist selbst eine Handlung (Navigation, F5) – und der Fall,
    // mit dem der Fehler gemeldet wurde. Deshalb ERZWINGEN, ohne Drosselung.
    melde(true);

    window.JarvisActivity = { melde: melde, _abstand: ABSTAND_MS };
})();
