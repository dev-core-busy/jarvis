/* Abgelaufene Sitzung SICHTBAR machen – statt still kaputter Seiten.
 *
 * WARUM ES DAS GIBT (gemeldet 2026-11-24): wer laengere Zeit nicht arbeitet
 * und zurueckkommt, ist serverseitig abgemeldet (sitzung_token: 12 h
 * Laufzeit, 2 h Leerlauf – der Leerlauf greift bei offenem Tab praktisch nur
 * nach Ruhezustand oder eingefrorenem Hintergrund-Tab). Gesagt wurde das
 * niemandem: `activity.js` und `cpubar.js` verstummen bei 401, manche Portale
 * springen kommentarlos auf `/`, der Chat merkt es erst beim Absenden – und
 * dann ist die getippte Nachricht womoeglich verloren.
 *
 * Diese Datei macht zweierlei, auf JEDER angemeldeten Seite gleich:
 *
 *  1. RUECKKEHR PRUEFEN: Tab wieder sichtbar, Fenster aktiviert, Seite aus dem
 *     bfcache, Rechner aufgewacht (der Takt unten sieht einen Zeitsprung) →
 *     EINE Anfrage an `/api/verify-token`. Ungueltig → Hinweis, bevor der
 *     Benutzer etwas tippt.
 *     ⚠ BEWUSST KEIN TAKT GEGEN DEN SERVER: jede Pruefung setzt dort
 *     "zuletzt gesehen" neu (`pruefe_und_beruehre`). Ein Abruf im Takt wuerde
 *     den 2-h-Leerlauf (BSI H3) aushebeln. Der Takt unten misst nur die
 *     eigene Uhr und fragt den Server erst nach einem Sprung.
 *
 *  2. 401 ABFANGEN: `fetch` wird einmal umwickelt. Antwortet eine eigene
 *     `/api/`-Anfrage mit 401, wird die Sitzung geprueft – NICHT sofort der
 *     Hinweis gezeigt. Ein 401 ist nicht immer die Sitzung (`/api/ldap/*`
 *     meldet damit falsche LDAP-Zugangsdaten); geprueft wird deshalb, ob die
 *     gespeicherte Sitzung noch gilt.
 *
 * DER HINWEIS hat EINEN Knopf "Neu anmelden": Adresse merken
 * (`JarvisSitzung.merkeRueckkehr`), dann `/`. Die Anmeldeseite prueft das
 * gespeicherte Token selbst – abgelaufen → abraeumen + Maske, gueltig (in
 * einem anderen Tab neu angemeldet) → gleich weiter. Nach der Anmeldung geht
 * es zurueck auf die gemerkte Seite. Deshalb raeumt diese Datei NICHTS ab:
 * zwei Stellen, die Tokens loeschen, liefen frueher oder spaeter auseinander.
 *
 * Das × schliesst den Hinweis, damit noch nicht Gesendetes kopiert werden
 * kann; der naechste 401 bzw. die naechste Rueckkehr zeigt ihn erneut.
 *
 * FAIL-SAFE-RICHTUNG: Netzfehler, 5xx oder eine unlesbare Antwort zeigen
 * NICHTS an – "abgelaufen" wird nur behauptet, wenn der Server es sagt
 * (`valid: false`). Ein falscher Hinweis waere schlimmer als keiner: er
 * schickt einen angemeldeten Benutzer zur Anmeldung.
 *
 * ⚠ MUSS DIREKT HINTER sitzung.js STEHEN – vor allen Skripten, die beim Laden
 * `fetch` rufen, sonst laufen deren Anfragen an der Huelle vorbei.
 */
(function () {
    'use strict';

    var S = window.JarvisSitzung;

    /* Hoechstens eine Rueckkehr-Pruefung je Minute: Tab-Wechsel sind haeufig,
     * und jede Pruefung beruehrt den Leerlauf auf dem Server. */
    var PRUEF_ABSTAND_MS = 60000;
    /* Eigene Uhr: tickt im Vordergrund alle 30 s. Liegt zwischen zwei Ticks
     * mehr als das Dreifache, stand der Rechner (oder der Tab war
     * eingefroren). Kein Serverkontakt dabei. */
    var TAKT_MS = 30000;
    var SPRUNG_MS = 3 * TAKT_MS;
    /* Nach dem Schliessen (×) bleibt der Hinweis so lange aus – sonst oeffnete
     * ihn der naechste 401 eines Hintergrund-Abrufs (manche Seiten fragen alle
     * paar Sekunden) sofort wieder, und Kopieren waere unmoeglich. */
    var RUHE_NACH_SCHLIESSEN_MS = 60000;

    /* Diese Anfragen gehoeren zum Anmeldeweg selbst – ein 401 dort ist eine
     * Antwort auf die Frage, nicht eine abgelaufene Sitzung. */
    var AUSGENOMMEN = /^\/api\/(login|logout|verify-token|auth\/|idp\/|sitzung\/cookie)/;

    var _orig = (typeof window.fetch === 'function') ? window.fetch : null;
    var _letztePruefung = 0;
    var _laeuft = false;
    var _offen = null;          // das sichtbare Hinweis-Element
    var _ruheBis = 0;

    function T(k, d) {
        try {
            var v = window.t ? window.t(k) : '';
            return (v && v !== k) ? v : d;
        } catch (e) { return d; }
    }

    /* Nur auf angemeldeten Seiten im eigenen Fenster. Die Wurzel `/` IST die
     * Anmeldeseite; in einem fremden Rahmen (Add-in) fuehrte `/` ins Leere. */
    function aktiv() {
        try {
            if (window.top !== window.self) return false;
        } catch (e) { return false; }
        var p = (location.pathname || '').replace(/\/+$/, '');
        if (p === '') return false;
        return !!S.token();
    }

    function eigeneApi(url) {
        try {
            var u = new URL(url, location.href);
            if (u.origin !== location.origin) return false;
            return u.pathname.indexOf('/api/') === 0 && !AUSGENOMMEN.test(u.pathname);
        } catch (e) { return false; }
    }

    function urlAus(eingabe) {
        if (typeof eingabe === 'string') return eingabe;
        if (eingabe && typeof eingabe.url === 'string') return eingabe.url;
        if (eingabe && typeof eingabe.href === 'string') return eingabe.href;
        return '';
    }

    /* Antwort von `/api/verify-token`: true = gilt, false = abgelaufen,
     * null = unbekannt (Netz, 5xx, Unlesbares). Nur false loest den Hinweis
     * aus – "unbekannt" ist keine Abmeldung. */
    function sitzungGilt() {
        if (!_orig) return Promise.resolve(null);
        return _orig.call(window, '/api/verify-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: S.token() }),
            credentials: 'same-origin'
        }).then(function (r) {
            if (r.status >= 500) return null;
            return r.json().then(function (d) {
                if (d && d.valid === true) return true;
                if (d && d.valid === false) return false;
                return null;
            }, function () { return null; });
        }).catch(function () { return null; });
    }

    function pruefen(erzwingen) {
        if (_offen || _laeuft || !aktiv()) return;
        var jetzt = Date.now();
        if (jetzt < _ruheBis) return;
        if (!erzwingen && jetzt - _letztePruefung < PRUEF_ABSTAND_MS) return;
        _letztePruefung = jetzt;
        _laeuft = true;
        /* Nur zeigen, wenn das gespeicherte Token WAEHREND der Pruefung gleich
         * geblieben ist. Seiten mit eigener Anmeldemaske (/chat, /userchat,
         * /settings) raeumen bei 401 selbst ab und zeigen die Maske – ein
         * Hinweis darueber waere doppelt. Ein ERSETZTES Token heisst: in
         * einem anderen Tab neu angemeldet, die alte Antwort ist veraltet. */
        var tk = S.token();
        sitzungGilt().then(function (gilt) {
            _laeuft = false;
            if (gilt === false && aktiv() && S.token() === tk) zeigen();
        });
    }

    function neuAnmelden() {
        S.merkeRueckkehr();
        location.replace('/');
    }

    function schliessen() {
        if (_offen && _offen.parentNode) _offen.parentNode.removeChild(_offen);
        _offen = null;
        _ruheBis = Date.now() + RUHE_NACH_SCHLIESSEN_MS;
    }

    function knopf(klasse, i18n, text) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = klasse;
        if (i18n) { b.setAttribute('data-i18n', i18n); b.textContent = T(i18n, text); }
        return b;
    }

    function zeigen() {
        if (_offen || !document.body) return;
        var huelle = document.createElement('div');
        huelle.className = 'jv-sitzung-ablauf';
        huelle.setAttribute('role', 'alertdialog');
        huelle.setAttribute('aria-modal', 'true');
        huelle.setAttribute('aria-labelledby', 'jv-sitzung-ablauf-titel');
        huelle.setAttribute('aria-describedby', 'jv-sitzung-ablauf-text');

        var karte = document.createElement('div');
        karte.className = 'jv-sitzung-ablauf-karte';

        var zu = knopf('jv-sitzung-ablauf-zu', '', '');
        zu.setAttribute('data-i18n-title', 'sitzung.ablauf_schliessen');
        zu.title = T('sitzung.ablauf_schliessen', 'Schließen');
        zu.setAttribute('data-i18n-aria', 'sitzung.ablauf_schliessen');
        zu.setAttribute('aria-label', zu.title);
        if (window.JarvisIcons && window.JarvisIcons.setClose) window.JarvisIcons.setClose(zu);
        else zu.textContent = '×';
        zu.addEventListener('click', schliessen);

        var titel = document.createElement('h2');
        titel.id = 'jv-sitzung-ablauf-titel';
        titel.className = 'jv-sitzung-ablauf-titel';
        titel.setAttribute('data-i18n', 'sitzung.ablauf_titel');
        titel.textContent = T('sitzung.ablauf_titel', 'Sitzung abgelaufen');

        var text = document.createElement('p');
        text.id = 'jv-sitzung-ablauf-text';
        text.className = 'jv-sitzung-ablauf-text';
        text.setAttribute('data-i18n', 'sitzung.ablauf_text');
        text.textContent = T('sitzung.ablauf_text',
            'Sie wurden abgemeldet – nach längerer Inaktivität oder weil die maximale Sitzungsdauer erreicht ist. Bitte melden Sie sich neu an; danach geht es auf dieser Seite weiter.');

        var tipp = document.createElement('p');
        tipp.className = 'jv-sitzung-ablauf-tipp';
        tipp.setAttribute('data-i18n', 'sitzung.ablauf_tipp');
        tipp.textContent = T('sitzung.ablauf_tipp',
            'Noch nicht gesendete Eingaben vorher kopieren: Schließen, kopieren, dann neu anmelden.');

        var los = knopf('jv-sitzung-ablauf-los', 'sitzung.ablauf_knopf', 'Neu anmelden');
        los.addEventListener('click', neuAnmelden);

        karte.appendChild(zu);
        karte.appendChild(titel);
        karte.appendChild(text);
        karte.appendChild(tipp);
        karte.appendChild(los);
        huelle.appendChild(karte);
        document.body.appendChild(huelle);
        _offen = huelle;
        try { los.focus(); } catch (e) { /* ohne Fokus geht es auch */ }
    }

    /* ── 2. fetch umwickeln ─────────────────────────────────────────────── */
    if (_orig) {
        window.fetch = function (eingabe) {
            var p = _orig.apply(window, arguments);
            try {
                var url = urlAus(eingabe);
                p.then(function (r) {
                    if (r && r.status === 401 && eigeneApi(url)) pruefen(true);
                }, function () { /* Netzfehler meldet der Aufrufer selbst */ });
            } catch (e) { /* die Huelle darf den Aufruf nie stoeren */ }
            return p;
        };
    }

    /* ── 1. Rueckkehr erkennen ──────────────────────────────────────────── */
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) pruefen(false);
    });
    window.addEventListener('focus', function () { pruefen(false); });
    window.addEventListener('pageshow', function (ev) {
        if (ev && ev.persisted) pruefen(true);
    });

    var _tick = Date.now();
    setInterval(function () {
        var jetzt = Date.now();
        var sprung = jetzt - _tick > SPRUNG_MS;
        _tick = jetzt;
        if (sprung && !document.hidden) pruefen(true);
    }, TAKT_MS);

    window.JarvisSitzungAblauf = {
        pruefen: pruefen,
        _zeigen: zeigen,
        _schliessen: schliessen,
        _eigeneApi: eigeneApi,
        _aktiv: aktiv
    };
})();
