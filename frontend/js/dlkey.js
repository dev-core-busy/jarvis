/* Abruf-Schluessel fuer Datei-Adressen – ersetzt das Sitzungstoken in ?token=.
 *
 * WARUM (gemessen 2026-09-02): ein Download-Link trug bis dahin das
 * SITZUNGStoken. Dasselbe Token oeffnet als `Authorization: Bearer` jeden
 * Endpunkt und lebt 30 Tage ab Ausstellung – wer den Link weitergab, gab seine
 * Sitzung weiter. Der Schluessel hier gilt 15 Minuten und wird ausschliesslich
 * von den Abruf-Endpunkten angenommen (backend/download_key.py).
 *
 * ⚠ JE ADRESSE EIN SCHLUESSEL (Pentest "Hardening" F-20, 2026-11-17). Bis dahin
 * galt EIN Schluessel je Benutzer fuer jede Datei, die er laden darf – ein aus
 * Verlauf oder Proxy-Protokoll abgegriffener Link oeffnete 15 Minuten lang auch
 * alle anderen. Jetzt bindet der Server jeden Schluessel an genau eine Adresse
 * (backend/download_key.py, `ziel_kanon`; ohne `token` und den Cache-Buster
 * `t`). Der Client rechnet dabei NICHTS nach: er schickt die Adresse im
 * Sammelabruf (POST /api/download-key) und merkt sich die Antwort unter der
 * Adresse. Ein ungebundener Schluessel wird abgewiesen.
 *
 * ⚠ ER MUSS SYNCHRON VERFUEGBAR SEIN. Alle Stellen, die eine solche Adresse
 * bauen (chatlib::_withToken, wissen.js, knowledge.js, kbmatrix.js, tracks.js,
 * info_files.js, vision.js, issues.js), tun das MITTEN IM RENDERN. Deshalb gibt
 * `url()` sofort eine Adresse zurueck – mit dem gemerkten Schluessel dieser
 * Adresse oder dem Platzhalter – und alle Adressen eines Durchgangs gehen in
 * EINEM Sammelabruf an den Server. Alle diese Stellen uebergeben die GANZE
 * Adresse an `url()`; einen Schluessel ohne Adresse gibt es nicht mehr.
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
 * ⚠ KEIN RUECKFALL AUF DAS SITZUNGSTOKEN MEHR (BSI M4, 2026-10-05). Bis dahin
 * trug eine Adresse, die vor dem ersten Schluessel gerendert wurde, das
 * Sitzungstoken – mit der Begruendung, das greife „in der Praxis nicht". Auf
 * ECHT gemessen griff es doch (05.10., ein Chat-Bild). Seit der Server ein
 * Sitzungstoken in ?token= per Vorgabe ABWEIST, waere das ausserdem ein totes
 * Bild, das niemand repariert: das Nachziehen erkennt nur `token=JDL1.…`.
 * Deshalb steht in diesem Moment ein PLATZHALTER in Schluesselform
 * (WARTEN, Ablauf 0): der Server weist ihn ab, ohne dass ein Sitzungstoken die
 * Seite verlaesst, und Nachziehen (2.) und Klick (3.) halten ihn fuer veraltet
 * und setzen den echten Schluessel ein, sobald er da ist.
 */
(function () {
    'use strict';

    var LAGER = 'jarvis_dlkey2';         // {user, keys: {<adresse>: {key, exp}}}
    var VORLAUF_S = 60;                  // so frueh erneuern, dass kein Klick in den Ablauf faellt
    var TAKT_MS = 30000;                 // Pruefintervall; Hintergrund-Tabs drosseln das auf ~1/min
    var MAX_ZIELE = 200;                 // = _DLKEY_MAX_ZIELE im Backend
    // Eintraege im Zwischenspeicher (abgelaufene fliegen zuerst). Gemessen im
    // echten Chrome (DEV 2026-11-17): /wissen rendert ~1500 Datei-Adressen; ein
    // Deckel von 500 verdraengte dort Schluessel, und jedes Neuzeichnen der
    // Liste holte ~1000 neu. 3000 Eintraege sind ~0,8 MB sessionStorage.
    var MAX_LAGER = 3000;
    // Platzhalter, solange fuer diese Adresse noch kein Schluessel da ist –
    // JDL1-Form mit Ablauf 0, damit ablauf()/veraltet() ihn erkennen und das
    // Nachziehen ihn ersetzt. Der Server weist ihn ab, ohne dass ein
    // Sitzungstoken die Seite verlaesst.
    var WARTEN = 'JDL1.warten.0.0';

    /* ⚠ NICHT direkt localStorage lesen – die Kette steht in sitzung.js
     * (Vorfall 2026-10-01: im Chat war der Schluessel dadurch leer). */
    function tok() { return window.JarvisSitzung.token(); }
    function benutzer() { return window.JarvisSitzung.benutzer(); }
    function jetzt() { return Math.floor(Date.now() / 1000); }

    /* ── Die Adresse als Merkschluessel ────────────────────────────────────
     * Ohne `token` und `t`, Parameter sortiert, ohne eigenen Ursprung: dieselbe
     * Datei, einmal mit und einmal ohne Cache-Buster gebaut, ist EIN Eintrag.
     * Das ist nur der Merkschluessel des Clients – das Ziel, an das der Server
     * den Schluessel bindet, bildet der Server selbst. */
    function merk(u) {
        try {
            var x = new URL(String(u || ''), location.origin);
            if (x.origin !== location.origin) return '';
            var q = new URLSearchParams(x.search);
            q.delete('token'); q.delete('t');
            q.sort();
            var s = q.toString();
            return x.pathname + (s ? '?' + s : '');
        } catch (e) { return ''; }
    }

    function ohneToken(u) {
        return String(u || '').replace(/([?&])token=[^&#]*(&?)/, function (_, a, b) {
            return b ? a : '';
        }).replace(/[?&]$/, '');
    }

    function lager() {
        try {
            var d = JSON.parse(sessionStorage.getItem(LAGER) || 'null');
            // An den Benutzer gebunden: nach einem Benutzerwechsel im selben Tab
            // waeren die alten Schluessel die eines Fremden.
            if (!d || !d.keys || (d.user && benutzer() && d.user !== benutzer())) {
                return { user: benutzer(), keys: {} };
            }
            return d;
        } catch (e) { return { user: benutzer(), keys: {} }; }
    }

    function lagerSchreiben(d) {
        try {
            var t = jetzt(), namen = Object.keys(d.keys);
            namen.forEach(function (k) { if (!(d.keys[k].exp > t)) delete d.keys[k]; });
            namen = Object.keys(d.keys);
            if (namen.length > MAX_LAGER) {
                namen.sort(function (a, b) { return d.keys[a].exp - d.keys[b].exp; });
                namen.slice(0, namen.length - MAX_LAGER).forEach(function (k) { delete d.keys[k]; });
            }
            sessionStorage.setItem(LAGER, JSON.stringify(d));
        } catch (e) { /* privater Modus */ }
    }

    /* Gueltiger (nicht bald ablaufender) Schluessel fuer diese Adresse – oder null. */
    function gemerkt(u) {
        var k = merk(u);
        if (!k) return null;
        var e = lager().keys[k];
        return (e && e.key && e.exp - VORLAUF_S > jetzt()) ? e : null;
    }

    /* ── Adressen, die schon einen Schluessel (oder den Platzhalter) tragen ──
     * Angefasst wird AUSSCHLIESSLICH ein Wert der Form `token=JDL1.…`. */
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

    /* ── Sammelabruf ───────────────────────────────────────────────────────
     * Alles, was in einem Render-Durchgang vorgemerkt wird, geht in EINEM
     * Aufruf an den Server (setTimeout 0 sammelt den synchronen Durchgang). */
    var _offen = {};                     // merk -> Adresse (ohne token)
    var _geplant = false;
    var _laeuft = null;

    function vormerken(u) {
        var k = merk(u);
        if (!k || !tok()) return;
        _offen[k] = ohneToken(u);
        if (!_geplant) {
            _geplant = true;
            setTimeout(abholen, 0);
        }
    }

    function abholen() {
        _geplant = false;
        if (_laeuft) return _laeuft.then(function () { if (Object.keys(_offen).length) return abholen(); });
        var namen = Object.keys(_offen).slice(0, MAX_ZIELE);
        if (!namen.length || !tok()) return Promise.resolve(null);
        var ziele = namen.map(function (k) { return _offen[k]; });
        namen.forEach(function (k) { delete _offen[k]; });
        _laeuft = fetch('/api/download-key', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + tok(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ ziele: ziele })
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok || !d.keys) return null;
                var l = lager();
                l.user = benutzer();
                Object.keys(d.keys).forEach(function (adr) {
                    var k = merk(adr), e = d.keys[adr];
                    if (k && e && e.key) l.keys[k] = { key: e.key, exp: e.exp };
                });
                lagerSchreiben(l);
                aktualisiere();
                return d;
            })
            .catch(function () { return null; })
            .then(function (x) {
                _laeuft = null;
                // Rest ueber dem Deckel (oder waehrenddessen vorgemerkt): naechster Durchgang.
                if (Object.keys(_offen).length) setTimeout(abholen, 0);
                return x;
            });
        return _laeuft;
    }

    /* Schluessel fuer GENAU diese Adresse – aus dem Zwischenspeicher oder vom
     * Server (Promise auf {key, exp} oder null). */
    function fuer(u) {
        var e = gemerkt(u);
        if (e) return Promise.resolve(e);
        vormerken(u);
        return (_laeuft || abholen() || Promise.resolve(null)).then(function () {
            return gemerkt(u);
        });
    }

    /* Schreibt frische Schluessel in bereits gerenderte Adressen – je Adresse
     * ihren eigenen. Nur VERALTETE werden angefasst (Platzhalter oder bald
     * ablaufend): ein `src`-Tausch startet einen neuen Netzabruf, und ein
     * bereits geladenes Bild braucht seine Adresse nicht mehr. Fehlt fuer eine
     * veraltete Adresse noch ein Schluessel, wird sie vorgemerkt. */
    function aktualisiere() {
        if (typeof document === 'undefined' || !document.querySelectorAll) return 0;
        var n = 0;
        function eins(el, attr) {
            var h = el.getAttribute(attr);
            if (!veraltet(h)) return;
            var e = gemerkt(h);
            if (e) { el.setAttribute(attr, ersetzen(h, e.key)); n++; }
            else vormerken(h);
        }
        try {
            var links = document.querySelectorAll('a[href*="token=JDL1."]');
            for (var i = 0; i < links.length; i++) eins(links[i], 'href');
            var medien = document.querySelectorAll(
                'img[src*="token=JDL1."], audio[src*="token=JDL1."], source[src*="token=JDL1."], iframe[src*="token=JDL1."]');
            for (var j = 0; j < medien.length; j++) {
                var b = medien[j];
                if (b.tagName === 'IMG' && b.complete && b.naturalWidth > 0) continue;   // laengst geladen
                eins(b, 'src');
            }
        } catch (e) { /* eine Anzeige darf an einer Adresse nicht sterben */ }
        return n;
    }

    var DL = {
        /* Haengt den Schluessel DIESER Adresse an – SYNCHRON. Ist er (noch)
         * nicht da, steht der Platzhalter WARTEN darin, die Adresse wird zum
         * Sammelabruf vorgemerkt, und das Nachziehen setzt den echten Schluessel
         * ein, sobald er da ist. Nie das Sitzungstoken (siehe Kopf).
         * Ohne Anmeldung bleibt die Adresse ohne ?token=. */
        url: function (u) {
            if (!u) return u;
            var e = gemerkt(u);
            var wert = e ? e.key : '';
            if (!wert) {
                if (!tok()) return u;
                vormerken(u);
                wert = WARTEN;
            }
            return u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(wert);
        },
        fuer: fuer,
        veraltet: veraltet,
        ersetzen: ersetzen,
        aktualisiere: aktualisiere,
        _merk: merk,
        _lager: LAGER
    };

    /* ── 1. Takt ───────────────────────────────────────────────────────────
     * Erneuert, was im DOM bald ablaeuft (aktualisiere merkt es vor). Der
     * Sichtbarkeitswechsel ist Pflicht: ein Hintergrund-Tab drosselt Timer auf
     * etwa einen Lauf je Minute, beim Zurueckholen soll alles sofort stimmen. */
    function takt() { if (tok()) aktualisiere(); }
    if (typeof setInterval === 'function') setInterval(takt, TAKT_MS);
    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) takt();
        });

        /* ── 3. Klick ──────────────────────────────────────────────────────
         * Capture-Phase, damit eigene Klick-Handler der Seite nicht vorher
         * navigieren. Nur eine WIRKLICH veraltete Adresse haelt den Klick an;
         * der Merker verhindert die Endlosschleife beim erneuten Ausloesen. */
        document.addEventListener('click', function (ev) {
            var a = ev.target && ev.target.closest &&
                    ev.target.closest('a[href*="token=JDL1."]');
            if (!a || a.__dlkNeu) return;
            var h = a.getAttribute('href');
            if (!veraltet(h)) return;
            ev.preventDefault();
            ev.stopPropagation();
            fuer(h).then(function (d) {
                if (d) a.setAttribute('href', ersetzen(h, d.key));
                a.__dlkNeu = true;
                try { a.click(); } catch (e) { /* nichts zu retten */ }
                setTimeout(function () { a.__dlkNeu = false; }, 0);
            });
        }, true);

        /* Ziehen (DownloadURL) und Kontextmenue koennen NICHT warten – beim
         * Druecken der Maustaste wird schon geholt. Best effort. */
        document.addEventListener('pointerdown', function (ev) {
            var a = ev.target && ev.target.closest &&
                    ev.target.closest('a[href*="token=JDL1."]');
            if (a && veraltet(a.getAttribute('href'))) fuer(a.getAttribute('href'));
        }, true);
    }

    window.JarvisDL = DL;
})();
