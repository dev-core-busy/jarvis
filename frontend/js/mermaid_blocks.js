/* Jarvis – Schaubilder im Chat (```mermaid).
 *
 * Der Agent gibt einen ```mermaid-Codeblock aus (Fluss-, Sequenz-, Gantt-,
 * ER-, Klassendiagramm). renderMarkdown() (chatlib.js) macht daraus einen
 * Platzhalter <div class="jarvis-mermaid" data-src="<base64>">, den dieses
 * Skript zu SVG rendert.
 *
 * ABGRENZUNG zu charts.js: Mermaid ist fuer SCHEMATISCHE Darstellungen
 * (Abläufe, Strukturen, Zeitpläne). Zahlenreihen gehoeren weiter in einen
 * ```chartjs-Block – Mermaid kennt keine Achsen, keine Skalierung und keine
 * Datenreihen.
 *
 * SICHERHEIT: Die Quelle kommt aus einer LLM-Antwort, ist also potenziell
 * angreiferkontrolliert (Prompt-Injection ueber ein Dokument). Deshalb
 *  - securityLevel: 'strict' UND htmlLabels: false -> Beschriftungen werden
 *    als SVG-Text gezeichnet, nicht als HTML. Ohne das koennte ein Label
 *    Markup einschleusen, das im Origin des Portals laeuft und dort an das
 *    Sitzungstoken im localStorage kaeme (gleiche Begruendung wie das
 *    SVG-Download-Verbot bei den Info-Dateien).
 *  - Klickbare Knoten (`click`-Direktive) sind mit 'strict' abgeschaltet.
 *
 * LADEN AUF ANFORDERUNG: mermaid.min.js ist ~2,7 MB. Es wird erst geholt,
 * wenn wirklich ein Schaubild im DOM steht – ein Chat ohne Diagramm zahlt
 * dafuer nichts.
 */
(function () {
    'use strict';

    var LIB = '/static/js/vendor/mermaid.min.js?v=1';
    var ladeVersprechen = null;   // Promise des laufenden/erledigten Ladens
    var initialisiert = false;
    var zaehler = 0;

    function hell() {
        return !!(document.body && document.body.classList.contains('light'));
    }

    // base64 -> UTF-8 (ohne deprecated escape/unescape)
    function b64ToText(b64) {
        var bin = atob(b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return new TextDecoder('utf-8').decode(bytes);
    }

    function fail(el, msg) {
        el.className = 'jarvis-mermaid jarvis-mermaid-err';
        el.textContent = '🧩 ' + msg;
    }

    function ladeMermaid() {
        if (ladeVersprechen) return ladeVersprechen;
        ladeVersprechen = new Promise(function (resolve, reject) {
            if (window.mermaid) { resolve(window.mermaid); return; }
            var s = document.createElement('script');
            s.src = LIB;
            s.async = true;
            s.onload = function () {
                if (window.mermaid) resolve(window.mermaid);
                else reject(new Error('mermaid nicht verfügbar'));
            };
            s.onerror = function () { reject(new Error('mermaid.min.js nicht geladen')); };
            document.head.appendChild(s);
        });
        return ladeVersprechen;
    }

    /* Theme: bewusst die MITGELIEFERTEN Mermaid-Themes ('default'/'dark')
     * statt einer eigenen Variablen-Palette. Mermaid faerbt je Diagrammart
     * ein Dutzend Rollen (Knoten, Rahmen, Cluster, Notizen, Akteure); eine
     * halb gesetzte Palette erzeugt zuverlaessig unlesbare Kombinationen.
     * Die Markenfarbe wandert nur an die Stelle, die sie sicher vertraegt. */
    function initMermaid(m) {
        var akzent = '';
        try {
            var el = document.body || document.documentElement;
            akzent = getComputedStyle(el).getPropertyValue('--accent').trim();
        } catch (e) { /* ignoriert */ }
        var conf = {
            startOnLoad: false,
            securityLevel: 'strict',
            theme: hell() ? 'default' : 'dark',
            fontFamily: 'inherit',
            // htmlLabels MUSS auf der OBERSTEN Ebene stehen. Nur unter
            // `flowchart` gesetzt bleiben die Kantenbeschriftungen HTML
            // (<foreignObject>) – im Browser nachgemessen: 2 statt 0. Erst
            // global gesetzt rendert Mermaid alle Beschriftungen als
            // SVG-<text>, also ohne HTML aus Modelltext.
            htmlLabels: false,
            flowchart: { htmlLabels: false, curve: 'basis', useMaxWidth: true },
            sequence: { useMaxWidth: true },
            gantt: { useMaxWidth: true }
        };
        if (akzent) conf.themeVariables = { primaryColor: akzent };
        m.initialize(conf);
        initialisiert = true;
    }

    function renderInto(m, el) {
        var quelle = '';
        try { quelle = b64ToText(el.getAttribute('data-src') || ''); } catch (e) { quelle = ''; }
        if (!quelle.trim()) { fail(el, 'Leeres Schaubild.'); return Promise.resolve(); }

        var id = 'jmmd-' + (++zaehler) + '-' + Math.floor(Math.random() * 1e6);
        var ergebnis;
        try {
            ergebnis = m.render(id, quelle);
        } catch (e) {
            fail(el, 'Schaubild ungültig: ' + (e && e.message ? e.message : e));
            aufraeumen(id);
            return Promise.resolve();
        }
        // mermaid.render ist in v10/v11 asynchron, in aelteren Fassungen
        // synchron mit Callback – beides abfangen.
        if (!ergebnis || typeof ergebnis.then !== 'function') {
            try {
                el.innerHTML = '';
                el.appendChild(svgAusText(String(ergebnis && ergebnis.svg ? ergebnis.svg : ergebnis)));
            } catch (e) { fail(el, 'Schaubild nicht darstellbar.'); }
            aufraeumen(id);
            return Promise.resolve();
        }
        return ergebnis.then(function (r) {
            el.innerHTML = '';
            el.appendChild(svgAusText(r && r.svg ? r.svg : ''));
            aufraeumen(id);
        }).catch(function (e) {
            fail(el, 'Schaubild ungültig: ' + (e && e.message ? e.message : e));
            aufraeumen(id);
        });
    }

    /* Das von Mermaid erzeugte SVG wird UEBER DEN SVG-PARSER eingesetzt, nicht
     * per innerHTML: der SVG-Parser fuehrt keine <script>-Elemente aus und
     * behandelt den Text nicht als HTML. Zweite Schranke hinter
     * securityLevel 'strict' – die Quelle stammt aus einer Modellantwort. */
    function svgAusText(svgText) {
        var doc = new DOMParser().parseFromString(String(svgText || ''), 'image/svg+xml');
        var svg = doc.documentElement;
        if (!svg || svg.nodeName === 'parsererror' || svg.nodeName.toLowerCase() !== 'svg') {
            throw new Error('kein SVG');
        }
        /* Ausfuehrbares und Externes entfernen.
         *
         * <foreignObject> wird ABSICHTLICH NICHT entfernt, obwohl es HTML
         * enthaelt: die erste Fassung tat das – und loeschte damit die
         * KNOTENBESCHRIFTUNGEN mit (im Browser gesehen: leere Kaesten mit
         * Pfeilen dazwischen). Mit htmlLabels:false entstehen ohnehin keine
         * foreignObjects; sollte eine kuenftige Mermaid-Fassung wieder welche
         * liefern, ist ein sichtbares Label besser als ein leeres Kaestchen.
         * Die Gefahr steckt nicht im Element, sondern in Skripten und
         * Ereignis-Attributen – die werden unten entfernt. */
        var weg = svg.querySelectorAll('script, iframe, object, embed');
        for (var i = 0; i < weg.length; i++) weg[i].parentNode.removeChild(weg[i]);

        // on*-Attribute und javascript:-Ziele ueberall entfernen.
        var alle = svg.querySelectorAll('*');
        var pruefen = [svg];
        for (var k = 0; k < alle.length; k++) pruefen.push(alle[k]);
        for (var n = 0; n < pruefen.length; n++) {
            var el = pruefen[n];
            var attrs = el.attributes;
            for (var a = attrs.length - 1; a >= 0; a--) {
                var an = attrs[a].name, av = String(attrs[a].value || '');
                if (/^on/i.test(an)) { el.removeAttribute(an); continue; }
                if (/(^|:)(href|src)$/i.test(an) && /^\s*(javascript|data):/i.test(av)) {
                    el.removeAttribute(an);
                }
            }
        }
        return document.importNode(svg, true);
    }

    // Mermaid haengt beim Rendern Mess-Container an <body> und laesst sie bei
    // Fehlern stehen. Ohne dieses Aufraeumen wachsen sie mit jedem Versuch.
    function aufraeumen(id) {
        try {
            [id, 'd' + id].forEach(function (x) {
                var n = document.getElementById(x);
                if (n && n.parentNode === document.body) n.parentNode.removeChild(n);
            });
        } catch (e) { /* ignoriert */ }
    }

    function hydrate(root) {
        var nodes = (root || document).querySelectorAll(
            '.jarvis-mermaid[data-src]:not([data-rendered])');
        if (!nodes.length) return;
        // Erst markieren, dann laden: waehrend des Ladens (~2,7 MB) darf ein
        // zweiter Lauf dieselben Knoten nicht erneut einreihen.
        var liste = [];
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].setAttribute('data-rendered', '1');
            liste.push(nodes[i]);
        }
        ladeMermaid().then(function (m) {
            if (!initialisiert) initMermaid(m);
            // Sequenziell: Mermaid rendert ueber einen gemeinsamen
            // Mess-Container am body, parallele Laeufe stoeren sich.
            return liste.reduce(function (p, el) {
                return p.then(function () { return renderInto(m, el); });
            }, Promise.resolve());
        }).catch(function (e) {
            for (var k = 0; k < liste.length; k++) {
                fail(liste[k], 'Schaubild-Bibliothek nicht geladen.');
            }
            console.warn('[Mermaid]', e);
        });
    }

    // Theme-Wechsel: Mermaid backt die Farben ins SVG. Neu rendern aus der
    // unveraenderten Quelle in data-src (gleiches Muster wie JarvisCharts).
    function redrawAll() {
        if (!window.mermaid || !initialisiert) return;
        initMermaid(window.mermaid);
        var nodes = document.querySelectorAll('.jarvis-mermaid[data-rendered]');
        for (var i = 0; i < nodes.length; i++) {
            if (!nodes[i].getAttribute('data-src')) continue;
            nodes[i].textContent = '';
            nodes[i].className = 'jarvis-mermaid';
            nodes[i].removeAttribute('data-rendered');
        }
        hydrate(document);
    }

    window.JarvisMermaid = { hydrate: hydrate, redraw: redrawAll };

    // Trailing-Debounce wie in charts.js: waehrend eine Antwort streamt,
    // aendert sich das DOM dauernd – erst bei Ruhe rendern.
    var timer = null;
    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(function () { hydrate(document); }, 250);
    }

    function start() {
        hydrate(document);
        try {
            new MutationObserver(schedule).observe(
                document.body, { childList: true, subtree: true });
        } catch (e) { /* ohne Observer bleibt der initiale Lauf */ }
        try {
            document.addEventListener('jarvis:themechange', function () { setTimeout(redrawAll, 0); });
        } catch (e) { /* ignoriert */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
