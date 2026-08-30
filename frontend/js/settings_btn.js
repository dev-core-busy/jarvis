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
 *
 * MOUSEOVER AM BADGE (2026-08-30, nach dem Vorbild des Issues-Badges): die Zahl
 * sagt "3" und sonst nichts. Wer wissen wollte, WAS zu tun ist, musste erst
 * /settings oeffnen und den Sicherheits-Reiter durchsehen – bei zwei
 * gleichzeitigen Quellen (offene Freigaben UND Sperren) sogar zwei getrennte
 * Abschnitte. Das Panel zeigt die Eintraege dahinter, und jede Zeile fuehrt in
 * GENAU den Abschnitt, der sie erledigt (`jarvis_settings_focus`). Ein nativer
 * `title` konnte das nie: er kommt verzoegert, laesst sich nicht anklicken und
 * wird je nach Browser hart abgeschnitten.
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

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* Wechselt nach /settings – mit Rueckweg, Reiter und (optional) dem
     * Abschnitt, der den Eintrag erledigt.
     *
     * Der Rueckweg kommt aus dem Zahnrad-Knopf: die Zeilen des Panels haengen
     * an `body` und koennen den Klick nicht an ihn weiterreichen, sonst waere
     * es dieselbe Bahn wie beim Klick auf die Badge. */
    function nachSettings(fokus) {
        var b = knoepfe()[0];
        var ziel = (b && b.getAttribute('data-jarvis-settings')) || location.pathname;
        try {
            sessionStorage.setItem('jarvis_settings_return', ziel);
            sessionStorage.setItem('jarvis_settings_tab', 'security');
            if (fokus) sessionStorage.setItem('jarvis_settings_focus', fokus);
            else sessionStorage.removeItem('jarvis_settings_focus');
        } catch (e) { /* egal - dann oeffnet der Vorgabe-Reiter */ }
        location.href = '/settings';
    }

    // ── Mouseover am Badge: was hinter der Zahl steckt ──────────────────────
    var _tip = null;
    var _tipTimer = null;

    function tipEl() {
        if (_tip) return _tip;
        _tip = document.createElement('div');
        _tip.className = 'jv-gear-tip';
        _tip.setAttribute('role', 'group');
        // Der Zeiger muss vom Badge INS Panel wandern koennen (die Zeilen sind
        // anklickbar). Deshalb haelt das Panel sich selbst offen.
        _tip.addEventListener('mouseenter', function () { clearTimeout(_tipTimer); });
        _tip.addEventListener('mouseleave', tipAusGleich);
        document.body.appendChild(_tip);
        return _tip;
    }

    /* Welcher Abschnitt des Sicherheits-Reiters erledigt diesen Eintrag?
     * Die Zuordnung steht HIER und nicht im Backend: sie beschreibt die
     * Oberflaeche, nicht die Daten. */
    function fokusFuer(art) {
        return art === 'blocked' ? 'incidents' : 'broker';
    }

    function tipZeichnen() {
        var el = tipEl();
        var posten = (_badge && _badge.items) || [];
        var gesamt = (_badge && _badge.gesamt) || 0;
        el.setAttribute('aria-label', T('security.gear_tip_title', 'Zu erledigen'));
        var zeilen = posten.map(function (it) {
            var blockiert = it.art === 'blocked';
            var marke = blockiert
                ? T('security.gear_tip_blocked', 'Gesperrt')
                : T('security.gear_tip_root', 'Freigabe');
            // Fremdtext: Befehlsbeschreibung, Benutzername und Sperrgrund
            // stammen aus fremden Quellen und werden ausnahmslos maskiert.
            var sub = it.sub
                ? (blockiert ? esc(it.sub)
                             : esc(T('security.gear_tip_by', 'angefragt von')
                                   + ' ' + it.sub))
                : '';
            var zeit = it.ts ? zeitpunkt(it.ts) : '';
            var unten = [sub, zeit].filter(Boolean).join(' · ');
            return '<button type="button" class="jv-gear-tip-row" data-fokus="'
                + esc(fokusFuer(it.art)) + '">'
                + '<div class="jv-gear-tip-top">'
                + '<span class="jv-gear-tip-k ' + (blockiert ? 'blocked' : 'root') + '">'
                + esc(marke) + '</span>'
                + '<span class="jv-gear-tip-t">' + (esc(it.titel) || '–') + '</span>'
                + '</div>'
                + (unten ? '<div class="jv-gear-tip-sub">' + unten + '</div>' : '')
                + '</button>';
        }).join('');
        // ⚠ Die Restzahl MUSS dastehen: der Server deckelt die Uebertragung.
        // Ohne diese Zeile haelt der Administrator die gekuerzte Liste fuer
        // vollstaendig, waehrend die Badge eine groessere Zahl zeigt.
        var rest = gesamt - posten.length;
        var mehr = rest > 0
            ? '<div class="jv-gear-tip-more">'
              + esc(T('security.gear_tip_more', '… und {n} weitere')
                    .replace('{n}', String(rest))) + '</div>'
            : '';
        // Aeltere Fassungen liefern `items` nicht mit. Dann steht statt einer
        // Liste die Aufschluesselung nach Quellen da – eine leere Flaeche waere
        // die Behauptung, es gaebe nichts (Register).
        var ersatz = '<div class="jv-gear-tip-hint">' + esc(quellenText()) + '</div>';
        el.innerHTML = '<div class="jv-gear-tip-h">'
            + esc(T('security.gear_tip_title', 'Zu erledigen'))
            + ' (' + gesamt + ')</div>'
            + (zeilen || ersatz)
            + mehr
            + '<div class="jv-gear-tip-hint">'
            + esc(T('security.gear_tip_hint',
                    'Eintrag anklicken, um den Abschnitt zu öffnen')) + '</div>';
        Array.prototype.forEach.call(el.querySelectorAll('.jv-gear-tip-row'),
            function (b) {
                b.addEventListener('click', function () {
                    nachSettings(b.getAttribute('data-fokus'));
                });
            });
    }

    function tipAn(anker) {
        clearTimeout(_tipTimer);
        if (!(_admin && _badge && _badge.gesamt)) return;
        var el = tipEl();
        tipZeichnen();
        el.style.display = 'block';
        // Erst nach dem Einblenden messen – ein verstecktes Element hat die
        // Breite 0, die Klammerung liefe ins Leere (Register).
        var a = anker.getBoundingClientRect();
        var b = el.getBoundingClientRect();
        var rand = 8;
        var links = a.right - b.width;               // rechtsbuendig zum Badge
        links = Math.max(rand, Math.min(links, window.innerWidth - b.width - rand));
        var oben = a.bottom + 8;
        // Kein Platz nach unten? Dann darueber – sonst haengt das Panel im
        // Nichts und ist unlesbar.
        if (oben + b.height > window.innerHeight - rand) {
            oben = Math.max(rand, a.top - b.height - 8);
        }
        el.style.left = links + 'px';
        el.style.top = oben + 'px';
    }

    function tipAus() {
        clearTimeout(_tipTimer);
        if (_tip) _tip.style.display = 'none';
    }

    // Verzoegert schliessen: der Weg vom Badge ins Panel fuehrt ueber ein paar
    // Pixel Zwischenraum. Ohne die Frist waere keine Zeile je anklickbar.
    function tipAusGleich() {
        clearTimeout(_tipTimer);
        _tipTimer = setTimeout(tipAus, 220);
    }

    function tipOffen() {
        return !!(_tip && _tip.style.display === 'block');
    }

    /** Kurzer Datums-/Zeitstempel in der Sprache des Browsers. */
    function zeitpunkt(ts) {
        try {
            return new Date(ts * 1000).toLocaleString(undefined,
                { day: '2-digit', month: '2-digit', hour: '2-digit',
                  minute: '2-digit' });
        } catch (e) { return ''; }
    }

    /** „Offene Root-Freigaben: 2 · Gesperrte Konten: 1" – die Aufschluesselung
     *  nach Quellen. Sie ist die Beschriftung der Badge (aria-label) UND der
     *  Rueckfall im Panel, wenn `items` fehlt. */
    function quellenText() {
        var teile = [];
        if (_badge && _badge.root_pending) {
            teile.push(T('security.gear_badge_title', 'Offene Root-Freigaben')
                + ': ' + _badge.root_pending);
        }
        if (_badge && _badge.gesperrt) {
            teile.push(T('security.gear_badge_blocked', 'Gesperrte Konten')
                + ': ' + _badge.gesperrt);
        }
        return teile.join(' · ');
    }

    /* Malt die Badge in JEDEN Zahnrad-Knopf (bzw. entfernt sie wieder).
     *
     * Wird aus `zeige()` gerufen, damit ein NACHTRAEGLICH erzeugter Knopf sie
     * ebenfalls bekommt (claude_portal.js baut bei 403 eine Absage-Seite samt
     * Knopf) – und aus dem Sprachwechsel, weil der Titel uebersetzt ist.
     *
     * `pointer-events: auto` (und nicht `none` wie bei der alten
     * `.issues-badge`) ist Absicht – nur so kommen Zeigerereignisse an, und
     * ohne die gibt es kein Mouseover-Panel; der Klick blubbert trotzdem an den
     * Knopf.
     *
     * ⚠ LEERER title IST ABSICHT und keine Vergesslichkeit (dieselbe Stelle wie
     * beim Issues-Badge): der Knopf darunter traegt `title` aus
     * `data-i18n-title="nav.settings"`. Ohne das leere Attribut sucht der
     * Browser beim Hovern der Badge beim Vorfahren weiter und zeigt SEINEN
     * nativen Tooltip ZUSAETZLICH zum Panel – zwei Kaesten uebereinander. Die
     * Aufschluesselung nach Quellen steht statt dessen im `aria-label`; ein
     * `title` an der Badge waere ausserdem beim naechsten `applyLang()` weg,
     * wenn er am Knopf haenge. */
    function badgeMalen() {
        // Tiefenverteidigung: ohne belegten Administrator-Status wird nichts
        // gemalt. Das Backend fuellt `admin_badge` ohnehin nur fuer Admins –
        // aber eine Badge in einen ausgeblendeten Knopf zu malen, weil ein
        // (aelteres oder manipuliertes) Antwort-Objekt das Feld mitbringt,
        // waere eine Aussage ueber die Rechteverwaltung an den Falschen.
        var n = (_admin && _badge && _badge.gesamt) || 0;
        if (!n) tipAus();
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
                el.setAttribute('title', '');
                // Der Klick auf die Badge soll IN den Sicherheits-Reiter fuehren.
                // Eigener Handler statt Ausnutzen des Knopf-Handlers, weil nur
                // hier bekannt ist, dass die Badge gemeint war.
                el.addEventListener('click', function () {
                    try { sessionStorage.setItem('jarvis_settings_tab', 'security'); }
                    catch (e) { /* egal - dann oeffnet der Vorgabe-Reiter */ }
                });
                el.addEventListener('mouseenter', function () { tipAn(el); });
                el.addEventListener('mouseleave', tipAusGleich);
                btn.appendChild(el);
            }
            btn.classList.add('jv-gear-host');
            el.textContent = n > 99 ? '99+' : String(n);
            // Eine Sperre ist dringlicher als eine offene Freigabe: ein Konto
            // kommt nicht mehr herein, bis jemand handelt.
            el.classList.toggle('is-danger', !!(_badge && _badge.gesperrt));
            el.setAttribute('aria-label', quellenText());
        });
        // Steht das Panel gerade offen, muss es dem neuen Stand folgen \u2013 sonst
        // zeigt es nach dem 60-s-Takt eine Liste, die es nicht mehr gibt
        // (Register: eine Anzeige darf keinen Zustand behaupten, den sie nicht
        // kennt). Bei 0 ist es oben schon geschlossen.
        if (n && tipOffen()) tipZeichnen();
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
