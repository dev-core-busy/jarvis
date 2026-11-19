/* ═══════════════════════════════════════════════════════════════════════
   Vorschlag per TAB uebernehmen
   ───────────────────────────────────────────────────────────────────────
   Mehrere Freitextfelder zeigen im Platzhalter einen BRAUCHBAREN Vorschlag
   ("z. B. Antworte knapp in Stichpunkten …"). Bis 2026-08-18 liess er sich
   nur abtippen. Jetzt: TAB in einem LEEREN, ausdruecklich markierten Feld
   uebernimmt den Vorschlag in das Feld.

   OPT-IN ueber `data-tabfill`, nie global:
     <textarea data-tabfill>                  → nimmt den `placeholder`
     <textarea data-tabfill="Fertiger Text">  → nimmt genau diesen Text

   Der zweite Weg ist noetig, wo der Platzhalter eine AUFZAEHLUNG dessen ist,
   was hineingehoert ("z. B. Signatur, Anrede-Form, …") – als Feldinhalt waere
   das Unsinn. Und deshalb ist es Opt-in: Formvorgaben wie
   "vorname.nachname@firma.de" oder ein Beispiel-DN duerfen NIE uebernommen
   werden, sonst speichert jemand versehentlich das Beispiel.

   ⚠ EIN ZUR LAUFZEIT GESETZTER VORSCHLAG GEHT UEBER `JarvisTabfill.vorschlag`,
   NIE UEBER `el.placeholder = …`. Im Markup stehen Vorschlag und Markierung
   nebeneinander und werden zusammen gelesen; im JavaScript nicht – dort setzt
   eine Zeile den Platzhalter, und die Markierung muss jemand DARAN denken.
   Genau das ist 2026-11-19 gemeldet worden: die vom Server berechnete
   Rueckkehr-Adresse des Anmelde-Anbieters (settings_idp.js) stand als fertiger,
   richtiger Wert im Platzhalter und liess sich nur abtippen – TAB tat nichts,
   weil `data-tabfill` fehlte. Es war nicht der einzige Fall: Zeitstempeldienst,
   Key-Vault-Anmeldung, jsign-Quelle, Aufbewahrungsfrist und Standortname hatten
   dasselbe. Sechs Stellen, sechsmal dieselbe vergessene Zeile.

     JarvisTabfill.vorschlag(el, text)   // Platzhalter UND Markierung
     JarvisTabfill.vorschlag(el, '')     // beides wieder weg

   Damit ist "Vorschlag setzen" EINE Handlung statt zweier, und ein leerer Text
   raeumt die Markierung mit ab – sonst bliebe sie an einem Feld haengen, das
   inzwischen keinen Vorschlag mehr hat, und der Hinweis versprach etwas, das
   TAB nicht liefert. Gesetzt wird ein LEERES Attribut: der Vorschlag ist dann
   der Platzhalter selbst, also EINE Quelle – ein Attribut mit eigener Kopie des
   Textes liefe auseinander, sobald jemand anders den Platzhalter anfasst
   (`branding.js` ersetzt darin den Markennamen).

   Ein Platzhalter, der KEIN uebernehmbarer Wert ist (Kennwort-Punkte,
   "leer lassen = unveraendert", "Lade…", ein Formbeispiel), bleibt eine
   gewoehnliche Zuweisung und traegt die Begruendung als Marke im Kommentar
   direkt davor: `tabfill: nein – <Grund>`. Waechter `tests/test_tabfill_ui.js`
   prueft beides als REGEL ueber alle Module, damit die naechste neue Stelle
   auffaellt statt still durchzufallen.

   TAB IST DIE FOKUS-WEITERSCHALTUNG – dieser Eingriff ist deshalb eng:
   * nur bei LEEREM Feld (danach schaltet TAB wieder normal weiter),
   * nie bei Shift+TAB (rueckwaerts navigieren muss immer gehen),
   * der uebernommene Text wird MARKIERT: Tippen ersetzt ihn, Entf loescht ihn,
     ein weiteres TAB springt weiter. Wer nur durchtabben wollte, verliert
     dadurch nichts als einen Tastendruck.

   ⚠ AUCH IM MARKUP IST JEDES PLATZHALTERFELD EINE ENTSCHEIDUNG (2026-11-19,
   zweite Meldung am selben Tag): die Regel oben galt nur fuer JavaScript, und
   gemeldet wurde danach prompt ein Feld im HTML – die Basis-URL unter
   "Mein SAP-Zugang" (sap.html). 220 statische Platzhalterfelder waren nie
   angesehen worden. Seitdem traegt jedes <input>/<textarea> mit Platzhalter
   ENTWEDER `data-tabfill` ODER `data-tabfill-nein="<Grund>"` (Suchfeld,
   Einmalcode, "leer = …", Formmuster mit Platzhalterteilen). Ausgenommen ist
   nur type=password – das nimmt nie einen Vorschlag. Dasselbe gilt fuer
   Felder, die ein Modul als HTML-Text erzeugt. Waechter: Teil 6 und 7 in
   `tests/test_tabfill_ui.js`.

   Ein Feld, das niemand als uebernehmbar erkennt, nuetzt nichts – deshalb
   erscheint bei Fokus auf einem leeren Feld ein dezenter Hinweis darunter.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var HINWEIS_KLASSE = 'jv-tabfill-hint';

    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }

    /** Einen berechneten Vorschlag setzen: Platzhalter UND Markierung in einem
     *  Zug. Leerer Text raeumt beides ab (siehe Kopf). */
    function vorschlagSetzen(el, text) {
        if (!el || !el.setAttribute) return;
        var s = (text === null || text === undefined) ? '' : String(text);
        s = s.trim();
        el.placeholder = s;
        // Leeres Attribut: der Vorschlag IST der Platzhalter – eine Quelle.
        if (s) el.setAttribute('data-tabfill', '');
        else el.removeAttribute('data-tabfill');
        // Steht der Zeiger gerade in diesem Feld, muss der Hinweis sofort
        // nachziehen – die Felder werden oft waehrend der Eingabe neu versorgt.
        if (document.activeElement === el) hinweisZeigen(el);
        return el;
    }

    // "z. B. Projekte" ist als Platzhalter richtig, als Feldinhalt nicht: das
    // Beispiel-Kennwort davor und Anfuehrungszeichen darum fallen beim
    // Uebernehmen weg.
    var BEISPIEL_VORSATZ = /^(?:z\.\s*B\.|e\.\s*g\.|zum Beispiel|for example)[\s:,]*/i;
    var ANFUEHRUNG = /^[\u201E\u201C\u201D"'\u00AB\u00BB](.*)[\u201C\u201D"'\u00AB\u00BB]$/;

    function bereinigt(s) {
        var t = (s || '').trim().replace(BEISPIEL_VORSATZ, '').trim();
        var m = ANFUEHRUNG.exec(t);
        return (m ? m[1] : t).trim();
    }

    function vorschlag(el) {
        if (!el || !el.getAttribute) return '';
        var eigen = el.getAttribute('data-tabfill');
        // Ein gesetztes Attribut mit Text gewinnt; leeres Attribut = Platzhalter.
        if (eigen && eigen.trim()) return bereinigt(eigen);
        return bereinigt(el.getAttribute('placeholder'));
    }

    function passt(el) {
        if (!el || !el.hasAttribute || !el.hasAttribute('data-tabfill')) return false;
        // Die ausdrueckliche Ablehnung gewinnt immer (siehe Kopf), und ein
        // Kennwortfeld nimmt NIE einen Vorschlag – dort ist der Platzhalter
        // bestenfalls "leer = unveraendert".
        if (el.hasAttribute('data-tabfill-nein')) return false;
        if ((el.getAttribute('type') || '').toLowerCase() === 'password') return false;
        if (el.disabled || el.readOnly) return false;
        var tag = (el.tagName || '').toLowerCase();
        if (tag !== 'textarea' && tag !== 'input') return false;
        return !(el.value || '').length && !!vorschlag(el);
    }

    function hinweisWeg() {
        var alt = document.querySelectorAll('.' + HINWEIS_KLASSE);
        for (var i = 0; i < alt.length; i++) {
            if (alt[i].parentNode) alt[i].parentNode.removeChild(alt[i]);
        }
    }

    function hinweisZeigen(el) {
        hinweisWeg();
        if (!passt(el)) return;
        var s = document.createElement('span');
        s.className = HINWEIS_KLASSE;
        // Textzeichen statt Emoji: ⇥ ist monochrom und folgt dem Theme.
        s.textContent = '⇥ ' + T('common.tabfill_hint',
            'Tab übernimmt den Vorschlag');
        if (el.parentNode) el.parentNode.insertBefore(s, el.nextSibling);
    }

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
        var el = e.target;
        if (!passt(el)) return;          // nicht markiert oder nicht leer → normales TAB
        e.preventDefault();
        el.value = vorschlag(el);
        try { el.select(); } catch (x) { /* select() gibt es nicht ueberall */ }
        // Andere Module haengen an `input` (Zeichenzaehler, Formular-Spiegel) –
        // ohne dieses Ereignis wuesste keines von der Uebernahme.
        el.dispatchEvent(new Event('input', { bubbles: true }));
        hinweisWeg();
    }, true);

    window.JarvisTabfill = { vorschlag: vorschlagSetzen };

    document.addEventListener('focusin', function (e) { hinweisZeigen(e.target); });
    document.addEventListener('focusout', function () { hinweisWeg(); });
    // Nach einer Uebernahme (oder beim Tippen) ist der Hinweis erledigt.
    document.addEventListener('input', function (e) {
        if (e.target && e.target.hasAttribute &&
            e.target.hasAttribute('data-tabfill') && (e.target.value || '').length) {
            hinweisWeg();
        }
    });
})();
