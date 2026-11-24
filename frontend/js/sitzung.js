/* Sitzungstoken und angemeldeter Benutzer – EINE Quelle fuer alle Seiten.
 *
 * WARUM ES DAS GIBT (bezahlt am 2026-10-01 auf ECHT, /chat): ein Download-Chip
 * im Chat fuehrte auf einen Anmelde-Dialog des Browsers. Ursache war KEINE
 * Berechtigung, sondern ein Name: die Anmeldung wird je Seite unter einem
 * EIGENEN Schluessel abgelegt –
 *
 *     app.js (settings)   -> jarvis_token
 *     chat.js (chat)      -> jarvis_chat_token
 *     userchat.js         -> jarvis_uc_token
 *
 * – und `dlkey.js` las nur `jarvis_token`. Im Chat war der Wert damit leer,
 * die Datei-Adresse bekam GAR KEIN `?token=`, der Server antwortete 401, und
 * Chrome macht aus einem 401 beim Download die Frage nach Benutzername und
 * Kennwort. Gemessen: `/api/download-key` wurde dabei nie aufgerufen.
 *
 * Die Schluesselkette stand zu diesem Zeitpunkt in 27 Dateien kopiert – in 37
 * weiteren stand nur EIN Schluessel. Welche der beiden Fassungen richtig war,
 * entschied allein, ob die Seite zufaellig `app.js` mitlud. Genau diese
 * Abweichung ist der Fehler, deshalb liegt die Kette ab hier an EINER Stelle
 * und `tests/test_sitzung_eine_quelle.py` haelt das fest.
 *
 * ⚠ DIESE DATEI MUSS VOR ALLEN ANDEREN JARVIS-SKRIPTEN GELADEN WERDEN. Sie hat
 * keine Abhaengigkeiten und baut kein DOM – sie darf deshalb ganz oben stehen.
 * Der Waechter prueft die Reihenfolge je Seite; ohne diese Pruefung wuerde ein
 * vergessenes `<script>` wie ein Anmeldeproblem aussehen, nicht wie ein
 * fehlendes Skript.
 *
 * ⚠ UND DIE ABHAENGIGKEIT IST ABSICHTLICH HART – das ist gemessen, nicht
 * Geschmack. Die naheliegende Milderung
 *
 *     var x = (window.JarvisSitzung && window.JarvisSitzung.token()) || '';
 *
 * wurde ausprobiert und VERWORFEN: ein fehlendes sitzung.js faellt damit nicht
 * mehr auf, es sieht nur wie „nicht angemeldet" aus. In den Waechtern war die
 * Folge der schlimmere Ausgang – 23 von 23 endeten danach mit Exit 0, aber ihre
 * Pruefzahl brach ein (`test_wissen_suche_ui` 43 → 0, `test_email_ui` 279 → 4):
 * gruen, und nichts gemessen. Ein TypeError beim Laden ist laut, sofort sichtbar
 * und vom Waechter (Abschnitt 3) ausgeschlossen. Wer die Milderung erneut
 * erwaegt, misst vorher die PRUEFZAHLEN, nicht die Exitcodes.
 *
 * KEIN SCHREIBWEG. Dass jede Seite ihren eigenen Schluessel SCHREIBT, ist
 * gewollt (zwei Anmeldungen in zwei Tabs sollen sich nicht gegenseitig
 * ueberschreiben) – hier steht nur das Lesen.
 */
(function () {
    'use strict';

    /* Reihenfolge = Vorrang. Nicht alphabetisch sortieren: `jarvis_token` ist
     * der seitenuebergreifend gespiegelte Wert (app.js) und gehoert nach vorn. */
    var TOKEN_SCHLUESSEL = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    var BENUTZER_SCHLUESSEL = ['jarvis_user', 'jarvis_chat_user', 'jarvis_uc_user'];

    /* Erster nicht-leerer Wert. Ein gesperrter Speicher (privater Modus,
     * Drittanbieter-Sperre im Add-in-Rahmen) wirft bei JEDEM Zugriff – deshalb
     * umschliesst der Schutz die ganze Schleife und nicht den einzelnen
     * Aufruf: sonst liefe sie dreimal ins selbe Leere.
     *
     * `bevorzugt` kommt NACH VORN, nicht anstelle der Kette. Das ist kein
     * Beiwerk: jede Seite hat ihren EIGENEN Schluessel zuerst gelesen
     * (`chat.js` → `jarvis_chat_token`, `userchat.js` → `jarvis_uc_token`),
     * und dieser Vorrang entscheidet, WER angemeldet ist, sobald in einem
     * Browser zwei verschiedene Anmeldungen liegen. Eine feste Reihenfolge fuer
     * alle haette den Vorrang still umgedreht – die Anzeige haette dann einen
     * anderen Benutzer gezeigt als die Datei-Adressen getragen haetten. */
    function ersterWert(schluessel, bevorzugt) {
        try {
            if (bevorzugt) {
                var b = localStorage.getItem(bevorzugt);
                if (b) return b;
            }
            for (var i = 0; i < schluessel.length; i++) {
                var v = localStorage.getItem(schluessel[i]);
                if (v) return v;
            }
        } catch (e) { /* kein Speicher = keine Sitzung */ }
        return '';
    }

    window.JarvisSitzung = {
        /* Der Sitzungstoken dieser Seite – '' wenn nicht angemeldet.
         * `bevorzugt`: der eigene Schluessel der Seite, falls sie einen hat. */
        token: function (bevorzugt) { return ersterWert(TOKEN_SCHLUESSEL, bevorzugt); },

        /* Der angemeldete Benutzername – '' wenn unbekannt. */
        benutzer: function (bevorzugt) { return ersterWert(BENUTZER_SCHLUESSEL, bevorzugt); },

        /* Fertiger Authorization-Kopfsatz. Die Zeile
         *     {'Authorization': 'Bearer ' + token()}
         * stand an ueber 100 Stellen; als Funktion ist sie eine Aenderung wert,
         * falls das Verfahren je wechselt. `extra` wird wie bei
         * Object.assign zusammengefuehrt, damit Aufrufer ihren Content-Type
         * behalten. */
        kopfsatz: function (extra) {
            var h = { 'Authorization': 'Bearer ' + this.token() };
            if (extra) {
                for (var k in extra) {
                    if (Object.prototype.hasOwnProperty.call(extra, k)) h[k] = extra[k];
                }
            }
            return h;
        },

        /* Kopien, nicht die Listen selbst: ein Aufrufer, der versehentlich
         * push() aufruft, darf die Quelle nicht veraendern. Gelesen werden sie
         * von den Abmelde-Wegen (alle drei Schluessel loeschen) und von den
         * Waechtern. */
        tokenSchluessel: function () { return TOKEN_SCHLUESSEL.slice(); },
        benutzerSchluessel: function () { return BENUTZER_SCHLUESSEL.slice(); },

        /* Kopfsatz fuer POST /api/login (und nur dafuer): verlangt das
         * Cookie-Verfahren (BSI H4) – das echte Sitzungstoken landet dann im
         * HttpOnly-Cookie, im Feld `token` der Antwort steht nur das CSRF-Token,
         * und das legt die Seite ab wie bisher. Ohne Cookie-Faehigkeit (Add-in,
         * fremder Rahmen) bleibt der Kopf weg und alles beim Alten. */
        anmeldeKopf: function (extra) {
            var h = {};
            if (extra) {
                for (var k in extra) {
                    if (Object.prototype.hasOwnProperty.call(extra, k)) h[k] = extra[k];
                }
            }
            if (cookieTauglich()) h['X-Jarvis-Sitzung'] = 'cookie';
            return h;
        },

        cookieTauglich: function () { return cookieTauglich(); }
    };

    /* SITZUNG IM COOKIE (BSI H4, 2026-10-12): bis dahin lag hier das volle
     * Sitzungstoken `benutzer:zeit:signatur` – jedes eingeschleuste Skript
     * konnte es lesen und mitnehmen. Seitdem haelt die Weboberflaeche nur noch
     * ein CSRF-Token `JCS1.…`; das echte Token liegt im HttpOnly-Cookie, und der
     * Server setzt beides zusammen (backend/sitzung_cookie.py). Die Aufrufer
     * merken davon nichts: `token()` liefert den Wert, der als Bearer geschickt
     * wird, wie vorher.
     *
     * Wo das Cookie NICHT ankommt, bleibt es beim echten Token:
     *  - in einem fremden Rahmen (Outlook im Web, Jira, Confluence): das Cookie
     *    ist SameSite=Strict und wird dort nicht mitgeschickt;
     *  - auf den Add-in-Seiten: Office laedt sie in eigenen WebViews (Office
     *    2019: Trident, siehe Register) – dort ist das Verhalten nicht belegt;
     *  - ohne https: ein `__Host-`-Cookie verwirft der Browser still. */
    var ADDIN_PFADE = ['/addin/', '/excel-addin/', '/jira-addon', '/confluence-addon'];

    function cookieTauglich() {
        try {
            if (window.top !== window.self) return false;
            if (location.protocol !== 'https:') return false;
            var p = location.pathname || '';
            for (var i = 0; i < ADDIN_PFADE.length; i++) {
                if (p.indexOf(ADDIN_PFADE[i]) === 0) return false;
            }
            return true;
        } catch (e) { return false; }   /* Zugriff auf top verweigert = fremder Rahmen */
    }

    /* Einmalige Umstellung einer Anmeldung von VOR der Umstellung: liegt noch
     * ein echtes Token im Speicher (es enthaelt `:`, ein CSRF-Token nie), wird
     * es gegen Cookie + CSRF-Token getauscht und danach aus dem Speicher
     * entfernt. Dasselbe Token, keine neue Sitzung.
     *
     * Es gibt nur EIN Cookie je Browser. Liegen unter den drei Schluesseln
     * VERSCHIEDENE echte Tokens (zwei Anmeldungen in zwei Bereichen), wird das
     * mit Vorrang umgestellt, die anderen werden entfernt – der Bereich fragt
     * dann neu nach der Anmeldung. Sie stehen zu lassen hiesse, genau das zu
     * behalten, was die Umstellung beseitigen soll.
     *
     * Bis die Antwort da ist, arbeitet die Seite mit dem echten Token weiter;
     * der Server nimmt es weiterhin an (Apps brauchen es). Scheitert der
     * Tausch, bleibt alles, wie es war – beim naechsten Laden neuer Versuch. */
    function umstellen() {
        if (!cookieTauglich() || typeof fetch !== 'function') return;
        var echt = '';
        try {
            for (var i = 0; i < TOKEN_SCHLUESSEL.length; i++) {
                var v = localStorage.getItem(TOKEN_SCHLUESSEL[i]);
                if (v && v.indexOf(':') >= 0) { echt = v; break; }
            }
        } catch (e) { return; }
        if (!echt) return;
        fetch('/api/sitzung/cookie', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + echt },
            credentials: 'same-origin'
        }).then(function (r) {
            return r.ok ? r.json() : null;
        }).then(function (d) {
            if (!d || !d.token || d.token.indexOf(':') >= 0) return;
            try {
                for (var j = 0; j < TOKEN_SCHLUESSEL.length; j++) {
                    var w = localStorage.getItem(TOKEN_SCHLUESSEL[j]);
                    if (!w || w.indexOf(':') < 0) continue;
                    if (w === echt) localStorage.setItem(TOKEN_SCHLUESSEL[j], d.token);
                    else localStorage.removeItem(TOKEN_SCHLUESSEL[j]);
                }
            } catch (e) { /* Speicher gesperrt */ }
        }).catch(function () { /* naechstes Laden versucht es erneut */ });
    }

    umstellen();

    /* KEIN AUFBLITZEN DER ANMELDEMASKE (2026-10-13). /chat, /userchat und
     * /settings (auch `/`) liefern die Maske SICHTBAR aus und blenden sie erst
     * aus, wenn der Server die Sitzung bestaetigt hat (`/api/me` bzw.
     * `/api/verify-token`). Bei jedem Kachel-Aufruf stand sie damit fuer die
     * Dauer eines Abrufs auf dem Schirm – gemeldet als "kommt immer wieder kurz
     * die Anmeldemaske".
     *
     * Liegt ein Token vor, ist der Regelfall "angemeldet": bis die Seite
     * entschieden hat, bleibt die Maske unsichtbar (`html.jv-sitzung-pruefen`,
     * Regel in theme.css). Jeder Weg, der die Maske ZEIGT, ruft vorher
     * `maskeFreigeben()`. Ohne Token wird nichts verborgen – dann ist die Maske
     * die richtige Antwort und erscheint sofort.
     *
     * Wirkt nur, wenn diese Datei VOR der Maske geladen wird (direkt hinter
     * theme_frueh.js). Der Deckel ist der Guertel: haengt der Abruf, steht
     * nach SPAETESTENS FREIGABE_MS die Maske da – also das alte Verhalten,
     * nie ein dauerhaft leerer Schirm. */
    var PRUEF_KLASSE = 'jv-sitzung-pruefen';
    var FREIGABE_MS = 4000;
    function maskeFreigeben() {
        try { document.documentElement.classList.remove(PRUEF_KLASSE); } catch (e) { /* kein DOM */ }
    }
    window.JarvisSitzung.maskeFreigeben = maskeFreigeben;

    /* RUECKKEHR NACH DER NEUANMELDUNG (2026-11-24). Laeuft eine Sitzung ab,
     * schickt `sitzung_ablauf.js` den Benutzer zur Anmeldung auf `/` – und
     * danach landete er bisher immer im Portal statt auf der Seite, auf der er
     * war. `merkeRueckkehr()` legt die aktuelle Adresse im sessionStorage ab
     * (NUR dieser Tab, ueberlebt den Weg ueber den Firmen-IdP),
     * `rueckkehrZiel(vorgabe)` liefert sie nach der Anmeldung EINMAL zurueck.
     *
     * Bewusst KEIN Adressparameter (`/?zurueck=…`): den koennte jeder in einen
     * Link schreiben, und die Anmeldeseite wuerde dorthin weiterleiten. Der
     * sessionStorage ist nur von dieser Seite selbst beschreibbar. Trotzdem
     * wird beim LESEN geprueft (`sicheresZiel`) – der Wert verlaesst sonst
     * ungeprueft den Speicher Richtung `location.replace`. */
    var RUECKKEHR_SCHLUESSEL = 'jarvis_rueckkehr';

    /* Nur ein eigener Pfad ist ein Ziel: beginnt mit genau EINEM `/`
     * (`//host` waere eine fremde Adresse), ohne Steuerzeichen und Rueckstrich
     * (manche Browser lesen `/\host` wie `//host`), und nicht die Wurzel
     * selbst – die IST die Anmeldeseite, ein Ziel `/` waere eine Schleife. */
    function sicheresZiel(z) {
        if (typeof z !== 'string' || z.length > 2000) return '';
        if (z.charAt(0) !== '/' || z.charAt(1) === '/') return '';
        if (/[\u0000-\u001f\u007f\\]/.test(z)) return '';
        var pfad = z.split(/[?#]/)[0].replace(/\/+$/, '');
        if (pfad === '') return '';
        return z;
    }

    window.JarvisSitzung.merkeRueckkehr = function (ziel) {
        var z = sicheresZiel(ziel != null ? ziel
            : (location.pathname || '') + (location.search || '') + (location.hash || ''));
        if (!z) return false;
        try { sessionStorage.setItem(RUECKKEHR_SCHLUESSEL, z); return true; }
        catch (e) { return false; }   /* Speicher gesperrt: dann eben Portal */
    };

    /* Einmalig: der Wert wird beim Lesen verbraucht, sonst fuehrte jede
     * spaetere Anmeldung in diesem Tab wieder dorthin. */
    window.JarvisSitzung.rueckkehrZiel = function (vorgabe) {
        var z = '';
        try {
            z = sessionStorage.getItem(RUECKKEHR_SCHLUESSEL) || '';
            sessionStorage.removeItem(RUECKKEHR_SCHLUESSEL);
        } catch (e) { /* Speicher gesperrt */ }
        return sicheresZiel(z) || vorgabe;
    };
    window.JarvisSitzung._sicheresZiel = sicheresZiel;

    if (window.JarvisSitzung.token()) {
        try {
            document.documentElement.classList.add(PRUEF_KLASSE);
            setTimeout(maskeFreigeben, FREIGABE_MS);
        } catch (e) { /* kein DOM: Maske bleibt, wie sie ist */ }
    }
})();
