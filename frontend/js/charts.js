/* Jarvis – interaktive Charts im Chat.
 *
 * Der Agent gibt einen ```chartjs-Codeblock mit einer Chart.js-Konfiguration
 * (JSON) aus. renderMarkdown() (chatlib.js) wandelt den Block in einen
 * Platzhalter <div class="jarvis-chart" data-spec="<base64-json>"> um. Dieses
 * Skript hydratisiert die Platzhalter zu echten Chart.js-Diagrammen.
 *
 * SICHERHEIT:
 *  - Die Spec kommt ausschliesslich als JSON (JSON.parse) – niemals eval.
 *    JSON kann keine Funktionen transportieren, also keine Callback-Injection.
 *  - Chart.js zeichnet Beschriftungen auf ein <canvas> (kein HTML) -> kein XSS.
 *  - Nur eine feste Whitelist an Diagrammtypen wird zugelassen.
 *  - Wir setzen niemals untrusted Inhalt via innerHTML (nur statische
 *    Fehlermeldungen via textContent).
 */
(function () {
    'use strict';

    var ALLOWED_TYPES = {
        bar: 1, line: 1, pie: 1, doughnut: 1, radar: 1,
        polarArea: 1, bubble: 1, scatter: 1
    };

    // base64 -> UTF-8-String (ohne deprecated escape/unescape)
    function b64ToJson(b64) {
        var bin = atob(b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return new TextDecoder('utf-8').decode(bytes);
    }

    function sanitize(spec) {
        if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
            throw new Error('Spezifikation ist kein Objekt');
        }
        if (!ALLOWED_TYPES[spec.type]) {
            throw new Error('Diagrammtyp nicht erlaubt: ' + spec.type);
        }
        if (!spec.data || typeof spec.data !== 'object') {
            throw new Error('data fehlt');
        }
        spec.options = (spec.options && typeof spec.options === 'object') ? spec.options : {};
        // Responsiv in einen Container mit fester Hoehe einpassen
        spec.options.responsive = true;
        spec.options.maintainAspectRatio = false;
        return spec;
    }

    function fail(el, msg) {
        el.className = 'jarvis-chart jarvis-chart-err';
        el.textContent = '📊 ' + msg;
    }

    function renderInto(el) {
        el.setAttribute('data-rendered', '1');
        var spec;
        try {
            spec = sanitize(JSON.parse(b64ToJson(el.getAttribute('data-spec') || '')));
        } catch (e) {
            fail(el, 'Chart-Daten ungültig: ' + (e && e.message ? e.message : e));
            return;
        }
        if (!window.Chart) {
            fail(el, 'Chart-Bibliothek nicht geladen.');
            return;
        }
        var canvas = document.createElement('canvas');
        el.appendChild(canvas);
        try {
            el._chart = new window.Chart(canvas.getContext('2d'), spec);
        } catch (e) {
            fail(el, 'Chart-Fehler: ' + (e && e.message ? e.message : e));
        }
    }

    function hydrate(root) {
        var nodes = (root || document).querySelectorAll(
            '.jarvis-chart[data-spec]:not([data-rendered])');
        for (var i = 0; i < nodes.length; i++) renderInto(nodes[i]);
    }

    window.JarvisCharts = { hydrate: hydrate };

    // Trailing-Debounce: erst hydratisieren, wenn die DOM-Mutationen (z.B. beim
    // Streaming einer Antwort) fuer 250 ms ruhen -> kein wiederholtes Neu-Rendern.
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
        } catch (e) { /* ohne Observer bleibt der initiale hydrate-Lauf */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
