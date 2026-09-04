/* Abruf-Schluessel fuer Datei-Adressen – ersetzt das Sitzungstoken in ?token=.
 *
 * WARUM (gemessen 2026-09-02): ein Download-Link trug bis dahin das
 * SITZUNGStoken. Dasselbe Token oeffnet als `Authorization: Bearer` jeden
 * Endpunkt und lebt 30 Tage ab Ausstellung – wer den Link weitergab, gab seine
 * Sitzung weiter. Der Schluessel hier gilt 15 Minuten und wird ausschliesslich
 * von den Abruf-Endpunkten angenommen (backend/download_key.py).
 *
 * ⚠ ER MUSS SYNCHRON VERFUEGBAR SEIN. Alle Stellen, die eine solche Adresse
 * bauen (chatlib::_withToken, wissen.js, knowledge.js, kbmatrix.js, tracks.js,
 * info_files.js, vision.js, issues.js), tun das MITTEN IM RENDERN. Deshalb wird
 * er einmal je Tab geholt und im sessionStorage gehalten, statt je Link
 * angefordert zu werden.
 *
 * ⚠ UND GENAU DAHER STAMMT DER FEHLER VOM 2026-09-04: die Adresse wird beim
 * RENDERN gebaut und friert im DOM ein, geklickt wird sie MINUTEN SPAETER. Ein
 * Download-Chip in einem offenen /chat war damit 15 Minuten nach seiner Anzeige
 * tot – der Server antwortet 401 (ein abgelaufener Schluessel wird bewusst NICHT
 * als Sitzungstoken nachgeprueft), und Chrome macht daraus „Versuch, dich auf
 * der Website anzumelden". Auf DEV gemessen: derselbe Link 200 → nach Ablauf
 * 401 → mit frischem Schluessel wieder 200.
 * Dagegen stehen hier DREI Netze, jedes fuer eine andere Lage:
 *   1. TAKT      – erneuert vor dem Ablauf, solange der Tab laeuft.
 *   2. NACHZIEHEN – schreibt den neuen Schluessel in bereits gerenderte
 *      Adressen; ohne das haelt der Takt nur den Zwischenspeicher frisch und
 *      das DOM bleibt alt (also genau der gemeldete Fehler).
 *   3. KLICK     – letzte Schranke. Ein Hintergrund-Tab drosselt Timer, der
 *      Takt kann also ausfallen; beim Klick wird deshalb noch einmal geprueft
 *      und notfalls synchron nachgeholt.
 *
 * Der Rueckfall auf das Sitzungstoken ist die Sicherheitsnetz-Zeile fuer die
 * ersten Millisekunden eines frischen Tabs (der Abruf laeuft, die Antwort ist
 * noch nicht da). In der Praxis greift er nicht: der Schluessel wird beim Laden
 * des Skripts angefordert, ein Chat-Verlauf rendert erst nach mindestens zwei
 * weiteren Rundreisen. Ohne den Rueckfall waere die Folge ein totes Bild bzw.
 * ein 401 beim Klick – ein sichtbarer Fehler dort, wo vorher nichts kaputt war.
 */
(function () {
    'use strict';

    var LAGER = 'jarvis_dlkey';          // {key, exp, user}
    var VORLAUF_S = 60;                  // so frueh erneuern, dass kein Klick in den Ablauf faellt
    var TAKT_MS = 30000;                 // Pruefintervall; Hintergrund-Tabs drosseln das auf ~1/min
    var _laeuft = null;                  // laufender Abruf (buendelt parallele Aufrufer)

    function tok() { try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; } }
    function benutzer() { try { return localStorage.getItem('jarvis_user') || ''; } catch (e) { return ''; } }
    function jetzt() { return Math.floor(Date.now() / 1000); }

    function lesen() {
        try {
            var roh = sessionStorage.getItem(LAGER);
            if (!roh) return null;
            var d = JSON.parse(roh);
            if (!d || !d.key || !d.exp) return null;
            // An den Benutzer gebunden: nach einem Benutzerwechsel im selben Tab
            // waere der alte Schluessel der eines Fremden.
            if (d.user && benutzer() && d.user !== benutzer()) return null;
            if (d.exp - VORLAUF_S <= jetzt()) return null;
            return d;
        } catch (e) { return null; }
    }

    function schreiben(d) {
        try { sessionStorage.setItem(LAGER, JSON.stringify(d)); } catch (e) { /* privater Modus */ }
    }

    /* ── Adressen, die den Schluessel schon tragen ──────────────────────────
     * Angefasst wird AUSSCHLIESSLICH ein Wert der Form `token=JDL1.…`. Ein
     * Sitzungstoken in ?token= (Alt-Weg der Android-App, /docs von Hand) bleibt
     * unberuehrt, und fremde Hosts kommen gar nicht erst vor – der Schluessel
     * wird nur an eigene /api-Pfade angehaengt. */
    var TOKEN_RE = /([?&]token=)(JDL1(?:\.|%2E)[^&#]*)/i;

    function ablauf(u) {
        var m = TOKEN_RE.exec(u || '');
        if (!m) return null;
        var teile = decodeURIComponent(m[2]).split('.');
        if (teile.length < 4) return null;
        var e = parseInt(teile[2], 10);
        return isNaN(e) ? null : e;
    }

    /* Traegt die Adresse einen Schluessel, der demnaechst nicht mehr angenommen
     * wird? Kein Schluessel drin = nichts zu tun (nicht „veraltet"). */
    function veraltet(u) {
        var e = ablauf(u);
        return e !== null && e - VORLAUF_S <= jetzt();
    }

    function ersetzen(u, neu) {
        if (!u || !neu) return u;
        return u.replace(TOKEN_RE, function (_, pre) { return pre + encodeURIComponent(neu); });
    }

    /* Schreibt den frischen Schluessel in bereits gerenderte Adressen.
     * Nur VERALTETE werden angefasst: ein `src`-Tausch startet einen neuen
     * Netzabruf, und ein bereits geladenes Bild braucht seine Adresse nicht
     * mehr. Deshalb bleiben fertig geladene <img> aussen vor. */
    function aktualisiere(neu) {
        if (!neu || typeof document === 'undefined' || !document.querySelectorAll) return 0;
        var n = 0;
        try {
            var links = document.querySelectorAll('a[href*="token=JDL1."]');
            for (var i = 0; i < links.length; i++) {
                var h = links[i].getAttribute('href');
                if (!veraltet(h)) continue;
                links[i].setAttribute('href', ersetzen(h, neu)); n++;
            }
            var bilder = document.querySelectorAll('img[src*="token=JDL1."]');
            for (var j = 0; j < bilder.length; j++) {
                var b = bilder[j];
                if (b.complete && b.naturalWidth > 0) continue;   // laengst geladen
                var s = b.getAttribute('src');
                if (!veraltet(s)) continue;
                b.setAttribute('src', ersetzen(s, neu)); n++;
            }
        } catch (e) { /* eine Anzeige darf an einer Adresse nicht sterben */ }
        return n;
    }

    function holen() {
        if (_laeuft) return _laeuft;
        if (!tok()) return Promise.resolve(null);
        _laeuft = fetch('/api/download-key', { headers: { 'Authorization': 'Bearer ' + tok() } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok || !d.key) return null;
                var eintrag = { key: d.key, exp: d.exp, user: benutzer() };
                schreiben(eintrag);
                aktualisiere(d.key);
                return eintrag;
            })
            .catch(function () { return null; })
            .then(function (x) { _laeuft = null; return x; });
        return _laeuft;
    }

    var DL = {
        /* Haengt den Schluessel an eine Adresse – SYNCHRON, aus dem Zwischenspeicher.
         * Ist er (noch) nicht da, wird er im Hintergrund geholt und fuer diesen
         * einen Aufruf das Sitzungstoken benutzt (siehe Kopf). */
        url: function (u) {
            if (!u) return u;
            var d = lesen();
            var wert = d ? d.key : '';
            if (!wert) {
                holen();
                wert = tok();
                if (!wert) return u;
            }
            return u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(wert);
        },
        /* Nur der Schluessel – fuer Stellen, die die Adresse selbst zusammensetzen. */
        schluessel: function () {
            var d = lesen();
            if (d) return d.key;
            holen();
            return tok();
        },
        bereit: function () {
            var d = lesen();
            return d ? Promise.resolve(d) : holen();
        },
        veraltet: veraltet,
        ersetzen: ersetzen,
        aktualisiere: aktualisiere,
        _lager: LAGER
    };

    /* ── 1. Takt ───────────────────────────────────────────────────────────
     * `lesen()` liefert bei nahem Ablauf null – das ist zugleich die
     * Faelligkeitspruefung. Der Sichtbarkeitswechsel ist Pflicht, nicht Kuer:
     * ein Hintergrund-Tab drosselt Timer auf etwa einen Lauf je Minute, und
     * beim Zurueckholen soll der Schluessel sofort stimmen. */
    function takt() { if (tok() && !lesen()) holen(); }
    if (typeof setInterval === 'function') setInterval(takt, TAKT_MS);
    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) takt();
        });

        /* ── 3. Klick ──────────────────────────────────────────────────────
         * Capture-Phase, damit eigene Klick-Handler der Seite (Kontextmenue,
         * Chip-Logik) nicht vorher schon navigieren. Nur wenn die Adresse
         * WIRKLICH veraltet ist, wird der Klick angehalten – im Normalfall
         * kostet das nichts. Der Merker verhindert die Endlosschleife beim
         * erneuten Ausloesen.
         * Bewusst OHNE Ausnahme fuer Strg-/Mittelklick: der wiederholte Klick
         * ist ein gewoehnlicher, ein `download`-Link verhaelt sich dabei
         * ohnehin gleich – und ein 401 waere der teurere Ausgang. */
        document.addEventListener('click', function (ev) {
            var a = ev.target && ev.target.closest &&
                    ev.target.closest('a[href*="token=JDL1."]');
            if (!a || a.__dlkNeu) return;
            var h = a.getAttribute('href');
            if (!veraltet(h)) return;
            ev.preventDefault();
            ev.stopPropagation();
            // bereit(), nicht holen(): liegt ein gueltiger Schluessel im
            // Zwischenspeicher, kostet die Reparatur keinen Serveraufruf.
            DL.bereit().then(function (d) {
                if (d) a.setAttribute('href', ersetzen(h, d.key));
                a.__dlkNeu = true;
                try { a.click(); } catch (e) { /* nichts zu retten */ }
                setTimeout(function () { a.__dlkNeu = false; }, 0);
            });
        }, true);

        /* Ziehen (DownloadURL) und Kontextmenue koennen NICHT warten – dort
         * gibt es kein preventDefault-und-spaeter. Deshalb wird beim Druecken
         * der Maustaste schon erneuert; bis zum dragstart ist der Schluessel in
         * aller Regel da. Best effort, kein Ersatz fuer Netz 1 und 2. */
        document.addEventListener('pointerdown', function (ev) {
            var a = ev.target && ev.target.closest &&
                    ev.target.closest('a[href*="token=JDL1."]');
            if (a && veraltet(a.getAttribute('href'))) DL.bereit();
        }, true);
    }

    // Frueh holen: je eher der Schluessel da ist, desto sicherer greift der
    // Rueckfall oben nie. Kein await noetig – die Renderer laufen spaeter.
    if (tok()) holen();

    window.JarvisDL = DL;
})();
