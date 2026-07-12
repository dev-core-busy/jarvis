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
 *
 * ROBUSTHEIT: LLMs liefern Chart.js-Configs oft MIT JS-Callbacks (z.B.
 * "label": function(ctx){...} oder ticks.callback: v => v+'%'). Das ist kein
 * gueltiges JSON und liess das Rendern frueher mit "Chart-Daten ungueltig"
 * scheitern. stripJsFunctions() ENTFERNT solche Funktionswerte (ersetzt sie
 * durch null) VOR dem JSON.parse – die Funktionen werden also nie ausgefuehrt
 * (Sicherheit bleibt), Chart.js nutzt stattdessen seine Default-Formatierung.
 */
(function () {
    'use strict';

    var ALLOWED_TYPES = {
        bar: 1, line: 1, pie: 1, doughnut: 1, radar: 1,
        polarArea: 1, bubble: 1, scatter: 1
    };

    // Findet zu einer '{'-Position die passende schliessende '}'. String-bewusst
    // fuer "…", '…' UND Template-Literals `…${ … }…` (inkl. Interpolation, deren
    // Klammern korrekt mitgezaehlt werden). -1 bei fehlender Schliessung.
    function findMatchingBrace(s, start) {
        var depth = 0, i = start, mode = 'code', interp = [];
        while (i < s.length) {
            var c = s[i];
            if (mode === '"' || mode === "'") {
                if (c === '\\') { i += 2; continue; }
                if (c === mode) mode = 'code';
                i++; continue;
            }
            if (mode === '`') {
                if (c === '\\') { i += 2; continue; }
                if (c === '`') { mode = 'code'; i++; continue; }
                if (c === '$' && s[i + 1] === '{') { interp.push(depth); depth++; mode = 'code'; i += 2; continue; }
                i++; continue;
            }
            if (c === '"' || c === "'") { mode = c; i++; continue; }
            if (c === '`') { mode = '`'; i++; continue; }
            if (c === '{') { depth++; }
            else if (c === '}') {
                depth--;
                if (depth === 0) return i;
                if (interp.length && depth === interp[interp.length - 1]) { interp.pop(); mode = '`'; }
            }
            i++;
        }
        return -1;
    }

    // Haengt fehlende schliessende Klammern an (string-/template-bewusst). LLMs
    // vergessen bei langen Configs gern die letzte '}' -> ohne diese Reparatur
    // scheitert JSON.parse. Wird nur im Fallback benutzt; bei balanciertem Input
    // ein No-Op.
    function closeUnbalanced(src) {
        var stack = [], i = 0, mode = 'code', interp = [];
        while (i < src.length) {
            var c = src[i];
            if (mode === '"' || mode === "'") {
                if (c === '\\') { i += 2; continue; }
                if (c === mode) mode = 'code';
                i++; continue;
            }
            if (mode === '`') {
                if (c === '\\') { i += 2; continue; }
                if (c === '`') { mode = 'code'; i++; continue; }
                if (c === '$' && src[i + 1] === '{') { interp.push(stack.length); stack.push('{'); mode = 'code'; i += 2; continue; }
                i++; continue;
            }
            if (c === '"' || c === "'") { mode = c; i++; continue; }
            if (c === '`') { mode = '`'; i++; continue; }
            if (c === '{') { stack.push('{'); }
            else if (c === '[') { stack.push('['); }
            else if (c === '}') {
                if (stack.length) stack.pop();
                if (interp.length && stack.length === interp[interp.length - 1]) { interp.pop(); mode = '`'; }
            } else if (c === ']') {
                if (stack.length) stack.pop();
            }
            i++;
        }
        var tail = '';
        for (var k = stack.length - 1; k >= 0; k--) tail += (stack[k] === '{' ? '}' : ']');
        return src + tail;
    }

    // Ersetzt Funktions-WERTE (nach einem ':') durch null, damit die Spec
    // gueltiges JSON wird. Wird nie ausgefuehrt – reine Textbereinigung.
    function stripJsFunctions(src) {
        // Formen mit Block-Body: function(...){...} bzw. (...) => {...} bzw. x => {...}
        var blockForms = [
            /:\s*function\b\s*[A-Za-z0-9_$]*\s*\([^)]*\)\s*\{/,
            /:\s*\([^)]*\)\s*=>\s*\{/,
            /:\s*[A-Za-z_$][\w$]*\s*=>\s*\{/
        ];
        for (var guard = 0; guard < 500; guard++) {
            var best = -1, bestLen = 0;
            for (var p = 0; p < blockForms.length; p++) {
                blockForms[p].lastIndex = 0;
                var m = blockForms[p].exec(src);
                if (m && (best === -1 || m.index < best)) { best = m.index; bestLen = m[0].length; }
            }
            if (best === -1) break;
            var braceStart = best + bestLen - 1;          // Index der oeffnenden '{'
            var close = findMatchingBrace(src, braceStart);
            if (close === -1) break;                       // defekt -> abbrechen
            src = src.slice(0, best) + ': null' + src.slice(close + 1);
        }
        // Kurz-Arrows ohne Block:  : (a)=>expr  /  : x=>expr  (bis , } ])
        src = src.replace(
            /:\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*[^,}\]\n]+/g, ': null');
        return src;
    }

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
        var raw = b64ToJson(el.getAttribute('data-spec') || '');
        try {
            spec = JSON.parse(raw);
        } catch (e1) {
            // Fallback: LLM-Config ist kein sauberes JSON. Zwei typische Ursachen
            // reparieren (nie ausfuehren): JS-Callbacks entfernen UND fehlende
            // schliessende Klammern anhaengen. Gueltiges JSON kommt hier nie an.
            try {
                spec = JSON.parse(closeUnbalanced(stripJsFunctions(raw)));
            } catch (e2) {
                fail(el, 'Chart-Daten ungültig: ' + (e2 && e2.message ? e2.message : e2));
                return;
            }
        }
        try {
            spec = sanitize(spec);
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
