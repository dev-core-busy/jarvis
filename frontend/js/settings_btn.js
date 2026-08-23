/* Einstellungs-Zahnrad in der Titelleiste – EINE Stelle fuer ALLE Bereichsseiten.
 *
 * WARUM ZENTRAL (gemeldet dreimal, zuletzt 2026-08-23 "IMMER NOCH kein
 * Einstellungen Symbol"):
 * Jede Seite hatte ihre eigene Verdrahtung, und drei davon hingen am ABRUF DES
 * BEREICHS statt am Administrator-Status:
 *     /tracks  -> `ist_admin` aus GET /api/tracks/status
 *     /claude  -> `ist_admin` aus GET /api/claude/status
 *     /wissen  -> `is_admin`  aus GET /api/wissen/scope
 * Scheitert dieser Abruf, laeuft die Einblendung NIE. Und er scheitert genau
 * dann, wenn der Bereich noch nicht freigegeben ist (403 "nicht in der
 * Benutzerliste/-Gruppe freigeschaltet") oder ein Zeitlimit zuschlaegt – also in
 * dem Moment, in dem ein Administrator den Weg in die Einstellungen am
 * dringendsten braucht, denn DORT wird die Freigabe gepflegt. Auf DEV
 * nachgemessen: `/api/tracks/status` und `/api/claude/status` antworten fuer
 * einen Administrator ohne Bereichs-Freigabe mit 403 – der Knopf blieb weg,
 * obwohl `/api/me` fuer denselben Benutzer `is_admin: true` liefert.
 *
 * Der Knopf beantwortet EINE Frage: "Bist du Administrator?" Die beantwortet
 * `/api/me` – und nur die darf ihn steuern.
 *
 * KONVENTION STATT AUFZAEHLUNG: gesucht wird `[data-jarvis-settings]`. Eine neue
 * Bereichsseite setzt das Attribut und bindet dieses Modul ein, mehr nicht – sie
 * kann den Fehler nicht wiederholen (dieselbe Lehre wie bei den MCP-Gates und
 * bei `icons.js`: eine Regel erwischt neue Faelle von selbst, eine Liste nie).
 * Der Attributwert ist der Rueckweg fuer /settings; ohne Wert gilt der aktuelle
 * Pfad.
 */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var t = localStorage.getItem(TOKEN_KEYS[i]);
                if (t) return t;
            } catch (e) { /* Speicher gesperrt (privates Fenster, iframe) */ }
        }
        return '';
    }

    function knoepfe() {
        return Array.prototype.slice.call(
            document.querySelectorAll('[data-jarvis-settings]'));
    }

    /* Einblenden + binden. Idempotent: mehrfaches Aufrufen (Sprachwechsel,
     * verzoegertes Nachladen) darf keinen zweiten Handler anhaengen.
     *
     * ZWEI VERSTECK-MECHANISMEN, beide muessen behandelt werden: die meisten
     * Seiten setzen `style="display:none"` am Knopf, /wissen dagegen die Klasse
     * `hidden` – und die ist dort `display: none !important`. Ein blosses
     * `style.display = ''` (oder auch `'block'`) verliert gegen `!important`:
     * der Knopf waere auf /wissen unsichtbar geblieben, ohne dass im DOM etwas
     * falsch aussieht. Deshalb IMMER beides. */
    function zeige(an) {
        knoepfe().forEach(function (b) {
            b.style.display = an ? '' : 'none';
            if (an) b.classList.remove('hidden');
            else b.classList.add('hidden');
            if (!an || b.dataset.jvsGebunden) return;
            b.dataset.jvsGebunden = '1';
            b.addEventListener('click', function () {
                var ziel = b.getAttribute('data-jarvis-settings') || location.pathname;
                try { sessionStorage.setItem('jarvis_settings_return', ziel); }
                catch (e) { /* egal – /settings faellt dann aufs Portal zurueck */ }
                location.href = '/settings';
            });
        });
    }

    var _lauf = null;

    /* Holt den Administrator-Status und blendet ein. Das Ergebnis wird je
     * Seitenaufruf gemerkt: mehrere Aufrufer (Seiten-Init, Sprachwechsel) sollen
     * nicht mehrere Roundtrips ausloesen – der Grund, aus dem /settings einmal
     * neun Sekunden brauchte. */
    function pruefe() {
        // Ein ERNEUTER Aufruf blendet nochmals ein, statt nur das gemerkte
        // Ergebnis zurueckzugeben: eine Seite kann den Knopf NACH dem Laden
        // erzeugen (claude_portal.js baut bei 403 eine Absage-Seite samt Knopf).
        // Gaebe `pruefe()` dann nur das Promise zurueck, blieben solche Knoepfe
        // verborgen – und der Roundtrip wird trotzdem nur einmal gemacht.
        if (_lauf) return _lauf.then(function (an) { zeige(an); return an; });
        var t = token();
        if (!t) { zeige(false); return Promise.resolve(false); }
        _lauf = fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var an = !!(d && d.is_admin);
                zeige(an);
                return an;
            })
            .catch(function () {
                // Kein Zustandswechsel bei Netzfehler: der Knopf startet
                // verborgen (display:none im Markup) und bleibt es. Ein
                // eingeblendeter Knopf ohne belegten Admin-Status waere eine
                // Behauptung.
                return false;
            });
        return _lauf;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', pruefe);
    } else {
        pruefe();
    }

    window.JarvisSettingsBtn = { pruefe: pruefe, zeige: zeige };
})();
