/* Bestaetigung vor Aktionen mit Aussen- oder Loeschwirkung (BSI H9).
 *
 * Das Backend (backend/wirkung.py) haelt einen Werkzeugaufruf an und schickt
 * `bestaetigung_anfrage`; hier entsteht daraus eine Karte im Chat mit den
 * Angaben des Aufrufs und zwei Knoepfen. Der Klick geht als eigene
 * WebSocket-Nachricht `bestaetigung_antwort` zurueck – das Modell kann ihn
 * nicht erzeugen. `bestaetigung_erledigt` schliesst die Karte (Klick
 * quittiert, Frist abgelaufen, Lauf gestoppt).
 *
 * ⚠ Die Argumente stammen vom MODELL und koennen aus Fremdtext abgeleitet
 * sein (eine praeparierte Mail). Sie gehen deshalb ausschliesslich ueber
 * textContent ins DOM, nie ueber innerHTML.
 */
(function () {
    'use strict';

    function T(key, ersatz) {
        var v = (typeof window.t === 'function') ? window.t(key) : key;
        if (!v || v === key) v = ersatz || key;
        var marke = 'Jarvis';
        try { if (window.jarvisMarke) marke = window.jarvisMarke() || marke; }
        catch (e) { /* Rueckfall bleibt */ }
        return String(v).split('{marke}').join(marke);
    }

    var KLASSEN = ['aussen', 'loeschen', 'shell', 'zeitplan'];

    // Kennung -> Karte. Eine Karte, deren Anfrage erledigt ist, bleibt im
    // Verlauf stehen (man soll nachlesen koennen, was freigegeben wurde),
    // reagiert aber nicht mehr.
    var _karten = new Map();

    function _el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function _werkzeugText(name) {
        // Wirkung statt Technik: bekannte Werkzeuge mit Klartext, sonst der Name.
        var key = 'bestaetigung.wz.' + name;
        var v = (typeof window.t === 'function') ? window.t(key) : key;
        return (v && v !== key) ? v : String(name || '');
    }

    function _abschliessen(karte, grund) {
        if (!karte || karte.dataset.zustand === 'erledigt') return;
        karte.dataset.zustand = 'erledigt';
        karte.classList.add('is-erledigt');
        karte.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
        var st = karte.querySelector('.jv-best-status');
        // Der Server hat das letzte Wort: nach einem Klick bestaetigt er ihn
        // nur, kam aber Frist oder Stop dazwischen, gilt das – sonst stuende
        // "Freigegeben" an einer Aktion, die nie lief.
        if (st) {
            st.textContent = T('bestaetigung.status.' + grund,
                               T('bestaetigung.status.abgebrochen', 'Abgebrochen'));
        }
        karte.dataset.grund = grund || '';
    }

    /**
     * Karte fuer eine Anfrage anlegen.
     * @param {object} msg        die Server-Nachricht `bestaetigung_anfrage`
     * @param {object} umgebung   { container: Element, senden: fn(obj), scroll: fn() }
     * @returns {Element|null}    die Zeile, die eingefuegt wurde
     */
    function anfrage(msg, umgebung) {
        if (!msg || !msg.id || !umgebung || !umgebung.container) return null;
        if (_karten.has(msg.id)) return null;   // doppelt zugestellt
        var klasse = KLASSEN.indexOf(msg.klasse) >= 0 ? msg.klasse : 'aussen';

        var row = _el('div', 'msg-row bot jv-best-row');
        // Bewusst KEIN data-agent-id: die Karte muss sichtbar sein, auch wenn
        // gerade ein anderer Agent-Reiter offen ist – sonst wartet der Lauf
        // bis zur Frist auf einen Knopf, den niemand sieht.
        var karte = _el('div', 'jv-best is-' + klasse);
        karte.dataset.bestId = msg.id;
        karte.dataset.zustand = 'offen';
        karte.setAttribute('role', 'group');

        var titel = _el('div', 'jv-best-titel',
                        T('bestaetigung.titel', 'Bestätigung erforderlich'));
        karte.appendChild(titel);
        karte.setAttribute('aria-label', titel.textContent);
        karte.appendChild(_el('div', 'jv-best-klasse',
                              T('bestaetigung.klasse.' + klasse, klasse)));
        karte.appendChild(_el('div', 'jv-best-aktion', _werkzeugText(msg.werkzeug)));

        var args = Array.isArray(msg.argumente) ? msg.argumente : [];
        if (args.length) {
            var dl = _el('dl', 'jv-best-args');
            args.forEach(function (paar) {
                if (!Array.isArray(paar) || paar.length < 2) return;
                dl.appendChild(_el('dt', null, String(paar[0])));
                dl.appendChild(_el('dd', null, String(paar[1])));
            });
            karte.appendChild(dl);
        }

        var minuten = Math.max(1, Math.round((Number(msg.frist_s) || 300) / 60));
        karte.appendChild(_el('div', 'jv-best-hinweis',
            T('bestaetigung.hinweis', 'Nichts geschieht ohne deinen Klick.')
                .split('{min}').join(String(minuten))));

        var knoepfe = _el('div', 'jv-best-knoepfe');
        var ja = _el('button', 'jv-best-btn jv-best-ja',
                     T('bestaetigung.ausfuehren', 'Ausführen'));
        ja.type = 'button';
        var nein = _el('button', 'jv-best-btn jv-best-nein',
                       T('bestaetigung.ablehnen', 'Ablehnen'));
        nein.type = 'button';
        knoepfe.appendChild(ja);
        knoepfe.appendChild(nein);
        karte.appendChild(knoepfe);

        var status = _el('div', 'jv-best-status');
        status.setAttribute('role', 'status');
        karte.appendChild(status);

        function klick(erlaubt) {
            // Genau EINE Antwort: das Sperren beider Knoepfe traegt das – ein
            // gesperrter Knopf loest keinen Klick mehr aus. Eine zusaetzliche
            // Zustandsabfrage hier war wirkungslos (Gegenprobe 2026-10-04).
            karte.dataset.zustand = 'gesendet';
            ja.disabled = true;
            nein.disabled = true;
            status.textContent = erlaubt
                ? T('bestaetigung.status.erlaubt', 'Freigegeben – wird ausgeführt')
                : T('bestaetigung.status.abgelehnt', 'Abgelehnt – nicht ausgeführt');
            var gesendet;
            try {
                gesendet = umgebung.senden({ type: 'bestaetigung_antwort', id: msg.id,
                                             erlaubt: erlaubt === true });
            } catch (e) {
                gesendet = false;
            }
            // ⚠ `senden` meldet ein NICHT gesendetes Paket mit `false` (Code-
            // Review 2026-10-07): chat.js' wsSend kehrte bei geschlossenem
            // WebSocket still zurueck, die Karte stand dann dauerhaft auf
            // "Freigegeben – wird ausgefuehrt", obwohl der Server nie etwas
            // bekam. Jetzt: Hinweis UND die Knoepfe wieder frei, damit nach dem
            // Wiederverbinden erneut geantwortet werden kann.
            if (gesendet === false) {
                karte.dataset.zustand = 'offen';
                ja.disabled = false;
                nein.disabled = false;
                status.textContent = T('bestaetigung.status.nicht_gesendet',
                                       'Antwort konnte nicht gesendet werden');
            }
        }
        ja.addEventListener('click', function () { klick(true); });
        nein.addEventListener('click', function () { klick(false); });

        row.appendChild(karte);
        umgebung.container.appendChild(row);
        _karten.set(msg.id, karte);
        if (typeof umgebung.scroll === 'function') {
            try { umgebung.scroll(); } catch (e) { /* nur Komfort */ }
        }
        return row;
    }

    /** Server meldet: die Anfrage wartet nicht mehr (Klick, Frist, Stop). */
    function erledigt(msg) {
        if (!msg || !msg.id) return;
        var karte = _karten.get(msg.id);
        if (!karte) return;
        _abschliessen(karte, String(msg.grund || 'abgebrochen'));
    }

    window.JarvisBestaetigung = { anfrage: anfrage, erledigt: erledigt };
})();
