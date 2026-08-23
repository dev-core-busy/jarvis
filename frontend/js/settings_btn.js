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
 *
 * BADGE (offene Root-Freigaben + gesperrte Konten): die Zahlen kommen aus
 * DERSELBEN /api/me-Antwort (`admin_badge`), die den Knopf ohnehin einblendet –
 * kein zusaetzlicher Roundtrip. Es gab sie schon einmal im alten
 * Einzelseiten-Hauptfenster (`gear-broker-badge` in app.js); sie fiel am
 * 2026-07-15 mit `bc41701` als toter Code, weil das Zahnrad in die
 * Bereichsseiten gewandert war und das Element nicht mitgenommen wurde. Sie
 * gehoert deshalb HIERHIN und nicht in eine Seite: sonst haette sie elf
 * Fassungen, und die zwoelfte Seite vergisst sie wieder.
 *
 * Ein Klick auf die Badge fuehrt in den Sicherheits-Reiter (sessionStorage
 * `jarvis_settings_tab`, ausgewertet in app.js) – eine Warnung ohne Weg zur
 * Abhilfe ist nur Laerm (dieselbe Regel wie beim Lizenz-Banner im Portal).
 */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    // Letzter Stand aus /api/me: {root_pending, gesperrt, gesamt}. null = noch
    // nichts gemessen (dann wird auch nichts behauptet, also keine Badge).
    var _badge = null;
    var _admin = false;      // belegter Administrator-Status
    var _pollTimer = null;
    var POLL_MS = 60000;   // wie die alte Fassung in app.js

    function T(key, fallback) {
        try { if (window.t) return window.t(key) || fallback; } catch (e) {}
        return fallback;
    }

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

    /* Malt die Badge in JEDEN Zahnrad-Knopf (bzw. entfernt sie wieder).
     *
     * Wird aus `zeige()` gerufen, damit ein NACHTRAEGLICH erzeugter Knopf sie
     * ebenfalls bekommt (claude_portal.js baut bei 403 eine Absage-Seite samt
     * Knopf) – und aus dem Sprachwechsel, weil der Titel uebersetzt ist.
     *
     * Das `title` gehoert an die Badge, NICHT an den Knopf: der traegt
     * `data-i18n-title="nav.settings"`, ein dort gesetzter Text waere beim
     * naechsten `applyLang()` weg. `pointer-events: auto` (und nicht `none` wie
     * bei der alten `.issues-badge`) ist Absicht – nur so erscheint der
     * Tooltip; der Klick blubbert trotzdem an den Knopf. */
    function badgeMalen() {
        // Tiefenverteidigung: ohne belegten Administrator-Status wird nichts
        // gemalt. Das Backend fuellt `admin_badge` ohnehin nur fuer Admins –
        // aber eine Badge in einen ausgeblendeten Knopf zu malen, weil ein
        // (aelteres oder manipuliertes) Antwort-Objekt das Feld mitbringt,
        // waere eine Aussage ueber die Rechteverwaltung an den Falschen.
        var n = (_admin && _badge && _badge.gesamt) || 0;
        knoepfe().forEach(function (btn) {
            var el = btn.querySelector('.jv-gear-badge');
            if (!n) {
                if (el) el.parentNode.removeChild(el);
                btn.classList.remove('jv-gear-host');
                return;
            }
            if (!el) {
                el = document.createElement('span');
                el.className = 'jv-gear-badge';
                // Der Klick auf die Badge soll IN den Sicherheits-Reiter fuehren.
                // Eigener Handler statt Ausnutzen des Knopf-Handlers, weil nur
                // hier bekannt ist, dass die Badge gemeint war.
                el.addEventListener('click', function () {
                    try { sessionStorage.setItem('jarvis_settings_tab', 'security'); }
                    catch (e) { /* egal - dann oeffnet der Vorgabe-Reiter */ }
                });
                btn.appendChild(el);
            }
            btn.classList.add('jv-gear-host');
            el.textContent = n > 99 ? '99+' : String(n);
            // Eine Sperre ist dringlicher als eine offene Freigabe: ein Konto
            // kommt nicht mehr herein, bis jemand handelt.
            el.classList.toggle('is-danger', !!(_badge && _badge.gesperrt));
            var teile = [];
            if (_badge && _badge.root_pending) {
                teile.push(T('security.gear_badge_title', 'Offene Root-Freigaben')
                    + ': ' + _badge.root_pending);
            }
            if (_badge && _badge.gesperrt) {
                teile.push(T('security.gear_badge_blocked', 'Gesperrte Konten')
                    + ': ' + _badge.gesperrt);
            }
            el.title = teile.join(' \u00b7 ');
        });
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
        badgeMalen();
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
                _admin = an;
                _badge = (d && d.admin_badge) || null;
                zeige(an);
                if (an) starteTakt();
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

    /* Haelt die Badge aktuell, solange die Seite offen ist.
     *
     * NUR fuer Administratoren und erst NACH dem belegten Admin-Status – ein
     * Takt, der bei jedem Benutzer laeuft, waere Last ohne Aussage. Der Server
     * merkt sich die Zahlen 20 s, der Takt kostet also hoechstens eine
     * Datei- und eine Socket-Abfrage je Minute.
     *
     * WARUM UEBERHAUPT EIN TAKT: eine offene Freigabe entsteht, WAEHREND der
     * Administrator auf der Seite steht (er drueckt ⤓ an einem Skill, der
     * apt braucht). Ein Stand vom Seitenaufbau zeigte sie nie – genau deshalb
     * hatte die alte Fassung in app.js denselben 60-Sekunden-Takt. */
    function aktualisiere() {
        var t = token();
        if (!t) return Promise.resolve(null);
        return fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                // 401/403/Netzfehler: den alten Stand BEHALTEN. "Keine offene
                // Freigabe" waere eine Behauptung, die der Abruf nicht deckt.
                if (!d) return null;
                _badge = d.admin_badge || null;
                badgeMalen();
                return _badge;
            })
            .catch(function () { return null; });
    }

    function starteTakt() {
        if (_pollTimer) return;
        _pollTimer = setInterval(aktualisiere, POLL_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', pruefe);
    } else {
        pruefe();
    }

    // Der Badge-Tooltip ist uebersetzt, steht aber nicht im Markup –
    // `applyLang()` erreicht ihn nicht. Neu malen, NICHT neu abrufen.
    window.addEventListener('jarvis-lang-changed', badgeMalen);

    window.JarvisSettingsBtn = { pruefe: pruefe, zeige: zeige,
                                 aktualisiere: aktualisiere };
})();
