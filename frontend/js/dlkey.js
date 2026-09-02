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
    var _laeuft = null;                  // laufender Abruf (buendelt parallele Aufrufer)

    function tok() { try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; } }
    function benutzer() { try { return localStorage.getItem('jarvis_user') || ''; } catch (e) { return ''; } }

    function lesen() {
        try {
            var roh = sessionStorage.getItem(LAGER);
            if (!roh) return null;
            var d = JSON.parse(roh);
            if (!d || !d.key || !d.exp) return null;
            // An den Benutzer gebunden: nach einem Benutzerwechsel im selben Tab
            // waere der alte Schluessel der eines Fremden.
            if (d.user && benutzer() && d.user !== benutzer()) return null;
            if (d.exp - VORLAUF_S <= Math.floor(Date.now() / 1000)) return null;
            return d;
        } catch (e) { return null; }
    }

    function schreiben(d) {
        try { sessionStorage.setItem(LAGER, JSON.stringify(d)); } catch (e) { /* privater Modus */ }
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
        _lager: LAGER
    };

    // Frueh holen: je eher der Schluessel da ist, desto sicherer greift der
    // Rueckfall oben nie. Kein await noetig – die Renderer laufen spaeter.
    if (tok()) holen();

    window.JarvisDL = DL;
})();
