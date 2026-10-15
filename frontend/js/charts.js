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
 *
 * THEME-LAYER (seit 2026-08-06): Das Modell liefert Typ + Daten + Beschriftung,
 * die OPTIK kommt von hier – Farbpalette, Schrift, Gitter, Legende, Achsen- und
 * Tooltip-Formate. Zwei Gruende:
 *  1) LLM-Vorgaben sind optisch beliebig (grelle Defaultfarben, kein
 *     Achsentitel, keine Tausendertrennung) und schwanken von Antwort zu
 *     Antwort. Ein festes Theme macht jedes Diagramm gleich lesbar und folgt
 *     ueber die CSS-Variablen automatisch Dark/Light UND dem Branding-Skill.
 *  2) Zahlenformate SIND clientseitig nur hier moeglich: Chart.js formatiert
 *     Achsen und Tooltips ueber Callback-FUNKTIONEN, und genau die entfernt
 *     stripJsFunctions() aus der Modellantwort (zu Recht – ausgefuehrter Code
 *     aus einer LLM-Antwort waere eine Luecke). Ohne Theme-Layer stand deshalb
 *     "1000" statt "1.000" im Diagramm, obwohl das Modell es richtig wollte.
 *
 * VORRANG: fillDefaults() setzt ausschliesslich FEHLENDE Werte – eine
 * ausdrueckliche Angabe des Modells gewinnt immer. `null` gilt dabei als
 * "nicht gesetzt", weil stripJsFunctions() entfernte Callbacks durch null
 * ersetzt; sonst wuerde ein gestrippter Formatter unsere Formatierung
 * blockieren und das Diagramm bliebe unformatiert.
 */
(function () {
    'use strict';

    var ALLOWED_TYPES = {
        bar: 1, line: 1, pie: 1, doughnut: 1, radar: 1,
        polarArea: 1, bubble: 1, scatter: 1
    };

    // Typen ohne kartesische Achsen – bei ihnen darf scales nicht angefasst
    // werden (Chart.js wirft sonst bzw. zeichnet ein leeres Diagramm).
    var NO_AXES = { pie: 1, doughnut: 1, radar: 1, polarArea: 1 };

    // Palette: erste Farbe ist die Marken-/Akzentfarbe (Branding wirkt damit
    // automatisch mit), danach eine feste, gut unterscheidbare Reihe. Alle
    // Toene sind mittelgesaettigt, damit sie in Dark UND Light lesbar sind.
    var PALETTE_TAIL = [
        '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4',
        '#8b5cf6', '#ec4899', '#84cc16', '#f97316', '#14b8a6'
    ];

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

    /* ── Theme-Bausteine ─────────────────────────────────────── */

    // Liest eine CSS-Variable. Gelesen wird an <body>, nicht an <html>:
    // branding.js setzt die Markenfarbe dort, und body erbt alles aus :root.
    function cssVar(name, fallback) {
        try {
            var el = document.body || document.documentElement;
            var v = getComputedStyle(el).getPropertyValue(name).trim();
            return v || fallback;
        } catch (e) { return fallback; }
    }

    function palette() {
        var accent = cssVar('--accent', '#9B59B6');
        return [accent].concat(PALETTE_TAIL);
    }

    // Farbe + Deckkraft. Nutzt --accent-rgb bzw. zerlegt #rrggbb; bei
    // unbekanntem Format wird die Farbe unveraendert zurueckgegeben (dann ist
    // die Flaeche deckend – haesslicher, aber nie unsichtbar).
    function withAlpha(color, alpha) {
        var c = String(color || '').trim();
        var m = /^#([0-9a-f]{6})$/i.exec(c);
        if (m) {
            var n = parseInt(m[1], 16);
            return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
        }
        m = /^#([0-9a-f]{3})$/i.exec(c);
        if (m) {
            var h = m[1];
            return 'rgba(' + parseInt(h[0] + h[0], 16) + ',' + parseInt(h[1] + h[1], 16) +
                ',' + parseInt(h[2] + h[2], 16) + ',' + alpha + ')';
        }
        m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(c);
        if (m) return 'rgba(' + m[1] + ',' + m[2] + ',' + m[3] + ',' + alpha + ')';
        return c;
    }

    // Anzeigesprache fuer Zahlformate. Reihenfolge wie in i18n.js.
    function locale() {
        var l = '';
        try { l = localStorage.getItem('jarvis_lang') || ''; } catch (e) { /* ignoriert */ }
        if (!l && window.currentLang) l = window.currentLang;
        if (!l) l = (document.documentElement.getAttribute('lang') || '');
        return /^en/i.test(l) ? 'en-US' : 'de-DE';
    }

    // Zahl fuer die MENSCHLICHE Anzeige. `compact` nur fuer Achsen-Ticks:
    // "1,2 Mio" statt "1.200.000" haelt die Achse schmal; im Tooltip steht
    // immer der vollstaendige Wert, sonst waere die Zahl nicht mehr ablesbar.
    function fmtNum(v, compact) {
        if (v === null || v === undefined || v === '') return '';
        var n = typeof v === 'number' ? v : parseFloat(v);
        if (!isFinite(n)) return String(v);
        try {
            var opt = { maximumFractionDigits: Math.abs(n) < 10 ? 2 : (Math.abs(n) < 1000 ? 1 : 0) };
            if (compact && Math.abs(n) >= 10000) {
                opt = { notation: 'compact', maximumFractionDigits: 1 };
            }
            return new Intl.NumberFormat(locale(), opt).format(n);
        } catch (e) { return String(v); }
    }

    // Setzt NUR fehlende Werte (rekursiv). null zaehlt als fehlend – siehe
    // Kopfkommentar (gestrippte Callbacks).
    function fillDefaults(target, defs) {
        for (var k in defs) {
            if (!Object.prototype.hasOwnProperty.call(defs, k)) continue;
            var d = defs[k], t = target[k];
            if (d && typeof d === 'object' && !Array.isArray(d)) {
                if (t === undefined || t === null) { target[k] = t = {}; }
                if (t && typeof t === 'object' && !Array.isArray(t)) fillDefaults(t, d);
            } else if (t === undefined || t === null) {
                target[k] = d;
            }
        }
        return target;
    }

    // Anzahl Datenpunkte (fuer die Entscheidung, ob Werte-Labels lesbar sind)
    function pointCount(spec) {
        var sets = (spec.data && spec.data.datasets) || [], n = 0;
        for (var i = 0; i < sets.length; i++) {
            var d = sets[i] && sets[i].data;
            if (d && d.length) n += d.length;
        }
        return n;
    }

    // Faerbt Datenreihen ein, die keine eigene Farbe mitbringen. Pro Typ
    // unterschiedlich, weil "professionell" jeweils etwas anderes heisst:
    // Balken flaechig, Linien duenn mit weicher Fuellung, Kreise segmentweise.
    function colorize(spec) {
        var pal = palette();
        var sets = (spec.data && spec.data.datasets) || [];
        var segmented = (spec.type === 'pie' || spec.type === 'doughnut' || spec.type === 'polarArea');
        for (var i = 0; i < sets.length; i++) {
            var ds = sets[i];
            if (!ds || typeof ds !== 'object') continue;
            var c = pal[i % pal.length];
            if (segmented) {
                if (ds.backgroundColor === undefined || ds.backgroundColor === null) {
                    var n = (ds.data && ds.data.length) || 0, arr = [];
                    for (var j = 0; j < n; j++) arr.push(pal[j % pal.length]);
                    ds.backgroundColor = arr;
                }
                // Trennlinien in Panelfarbe – laesst die Segmente "atmen".
                fillDefaults(ds, { borderColor: cssVar('--bg-secondary', '#111827'), borderWidth: 2 });
            } else if (spec.type === 'line' || spec.type === 'radar') {
                fillDefaults(ds, {
                    borderColor: c,
                    backgroundColor: withAlpha(c, 0.15),
                    borderWidth: 2,
                    tension: 0.3,              // leichte Glaettung statt Zickzack
                    pointRadius: pointCount(spec) > 40 ? 0 : 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: c
                });
            } else if (spec.type === 'bar') {
                fillDefaults(ds, {
                    backgroundColor: withAlpha(c, 0.85),
                    borderColor: c,
                    borderWidth: 0,
                    borderRadius: 4,
                    maxBarThickness: 48        // sonst werden 2 Balken bildbreit
                });
            } else {                            // scatter / bubble
                fillDefaults(ds, {
                    backgroundColor: withAlpha(c, 0.7),
                    borderColor: c,
                    borderWidth: 1
                });
            }
        }
    }

    // Achsen: dezentes Gitter nur auf der WERT-Achse, Rahmen weg, Zahlen
    // lokalisiert. Ein Gitter in beide Richtungen wirkt wie Millimeterpapier.
    function styleAxes(spec) {
        if (NO_AXES[spec.type]) return;
        var grid = 'rgba(' + cssVar('--fg-rgb', '255, 255, 255') + ', 0.08)';
        var tick = cssVar('--text-secondary', '#94a3b8');
        var titleColor = cssVar('--text-muted', '#64748b');
        var axisFont = { size: 11, family: cssVar('--font-body', 'sans-serif') };
        var horizontal = (spec.options.indexAxis === 'y');
        var kategorieAchse = horizontal ? 'y' : 'x';
        var valueGrid = (spec.type === 'scatter' || spec.type === 'bubble');

        fillDefaults(spec.options, {
            scales: {
                x: {
                    grid: { display: valueGrid || kategorieAchse !== 'x', color: grid, drawTicks: false },
                    border: { display: false },
                    ticks: { color: tick, font: axisFont, maxRotation: 45, autoSkip: true },
                    title: { color: titleColor, font: { size: 11, weight: '500' } }
                },
                y: {
                    grid: { display: true, color: grid, drawTicks: false },
                    border: { display: false },
                    ticks: { color: tick, font: axisFont },
                    title: { color: titleColor, font: { size: 11, weight: '500' } }
                }
            }
        });
        // Kategorie-Achse braucht kein Gitter (nur die Wert-Achse).
        if (!valueGrid && spec.options.scales[kategorieAchse]) {
            fillDefaults(spec.options.scales[kategorieAchse], { grid: { display: false } });
        }
        // Achsentitel nur anzeigen, wenn das Modell einen Text geliefert hat.
        ['x', 'y'].forEach(function (ax) {
            var sc = spec.options.scales[ax];
            if (sc && sc.title && sc.title.text && sc.title.display === undefined) {
                sc.title.display = true;
            }
        });
        // Wert-Achse: bei Balken bei 0 beginnen (sonst uebertreibt das
        // Diagramm kleine Unterschiede), Zahlen lokalisiert + kompakt.
        var valueAxis = horizontal ? 'x' : 'y';
        if (spec.type === 'bar') fillDefaults(spec.options.scales[valueAxis], { beginAtZero: true });
        var vt = spec.options.scales[valueAxis];
        if (vt && vt.ticks && (vt.ticks.callback === undefined || vt.ticks.callback === null)) {
            vt.ticks.callback = function (value) { return fmtNum(value, true); };
        }
    }

    // Legende, Titel, Tooltip
    function styleOverlays(spec) {
        var sets = (spec.data && spec.data.datasets) || [];
        var segmented = (spec.type === 'pie' || spec.type === 'doughnut' || spec.type === 'polarArea');
        // Eine einzelne Reihe braucht keine Legende – der Titel sagt es schon.
        var showLegend = segmented || sets.length > 1;

        fillDefaults(spec.options, {
            plugins: {
                legend: {
                    display: showLegend,
                    position: 'bottom',
                    labels: {
                        color: cssVar('--text-secondary', '#94a3b8'),
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 8,
                        boxHeight: 8,
                        padding: 14,
                        font: { size: 11, family: cssVar('--font-body', 'sans-serif') }
                    }
                },
                title: {
                    color: cssVar('--text-primary', '#f8fafc'),
                    font: { size: 14, weight: '600', family: cssVar('--font-body', 'sans-serif') },
                    padding: { top: 2, bottom: 14 }
                },
                tooltip: {
                    backgroundColor: cssVar('--bg-secondary', '#111827'),
                    borderColor: 'rgba(' + cssVar('--fg-rgb', '255, 255, 255') + ', 0.14)',
                    borderWidth: 1,
                    titleColor: cssVar('--text-primary', '#f8fafc'),
                    bodyColor: cssVar('--text-secondary', '#94a3b8'),
                    padding: 10,
                    cornerRadius: 8,
                    usePointStyle: true
                }
            },
            layout: { padding: { top: 2, right: 6, bottom: 0, left: 0 } }
        });
        // Titel nur zeigen, wenn ein Text da ist.
        var ti = spec.options.plugins.title;
        if (ti && ti.text && ti.display === undefined) ti.display = true;

        // Tooltip-Werte lokalisiert (vollstaendig, nicht kompakt). Bei
        // Kreisdiagrammen zusaetzlich der Anteil – das ist dort die
        // eigentliche Aussage.
        var tt = spec.options.plugins.tooltip;
        if (tt && (tt.callbacks === undefined || tt.callbacks === null)) tt.callbacks = {};
        if (tt && tt.callbacks && (tt.callbacks.label === undefined || tt.callbacks.label === null)) {
            tt.callbacks.label = function (ctx) {
                var raw = ctx.parsed;
                var v = (raw && typeof raw === 'object')
                    ? (segmented ? ctx.parsed : (spec.options.indexAxis === 'y' ? raw.x : raw.y))
                    : raw;
                var txt = (ctx.dataset && ctx.dataset.label ? ctx.dataset.label + ': ' : '') + fmtNum(v, false);
                if (segmented) {
                    var arr = (ctx.chart.data.datasets[ctx.datasetIndex] || {}).data || [];
                    var sum = 0;
                    for (var i = 0; i < arr.length; i++) {
                        var n = parseFloat(arr[i]);
                        if (isFinite(n)) sum += n;
                    }
                    var label = ctx.label ? ctx.label + ': ' : '';
                    txt = label + fmtNum(v, false);
                    if (sum > 0) txt += ' (' + fmtNum((v / sum) * 100, false) + ' %)';
                }
                return txt;
            };
        }
    }

    /* ── A2: Werte-Labels (chartjs-plugin-datalabels) ──────────────
     * Absichtlich NICHT global registriert: global aktiv wuerde das Plugin in
     * JEDEM Diagramm Labels zeichnen, auch in einem Streudiagramm mit 500
     * Punkten. Es wird pro Diagramm zugeschaltet – und nur, wenn die Labels
     * lesbar bleiben. Ein ausdruecklicher Wunsch des Modells
     * (options.plugins.datalabels) hat immer Vorrang, auch "aus". */
    function datalabelDefaults(spec) {
        var sets = (spec.data && spec.data.datasets) || [];
        var pts = pointCount(spec);
        var segmented = (spec.type === 'pie' || spec.type === 'doughnut');
        var want;
        if (segmented) {
            want = pts > 0 && pts <= 8;
        } else if (spec.type === 'bar') {
            want = pts > 0 && pts <= 30 && sets.length <= 3;
        } else if (spec.type === 'line') {
            want = pts > 0 && pts <= 8 && sets.length === 1;
        } else {
            want = false;                       // scatter/bubble/radar: nie
        }
        if (!want) return null;

        if (segmented) {
            return {
                color: '#ffffff',
                font: { size: 11, weight: '600' },
                formatter: function (value, ctx) {
                    var arr = (ctx.chart.data.datasets[ctx.datasetIndex] || {}).data || [];
                    var sum = 0;
                    for (var i = 0; i < arr.length; i++) {
                        var n = parseFloat(arr[i]);
                        if (isFinite(n)) sum += n;
                    }
                    if (!sum) return fmtNum(value, true);
                    var p = (value / sum) * 100;
                    return p < 5 ? '' : fmtNum(p, false) + ' %';   // Splitter weglassen
                }
            };
        }
        return {
            anchor: 'end',
            align: 'end',
            offset: 2,
            clamp: true,
            color: cssVar('--text-secondary', '#94a3b8'),
            font: { size: 10 },
            formatter: function (value) {
                var v = (value && typeof value === 'object')
                    ? (spec.options.indexAxis === 'y' ? value.x : value.y) : value;
                return fmtNum(v, true);
            }
        };
    }

    // Gibt die pro Diagramm zuzuschaltenden Plugin-Objekte zurueck.
    function instancePlugins(spec) {
        var out = [];
        var dl = spec.options.plugins && spec.options.plugins.datalabels;
        if (window.ChartDataLabels && dl && dl.display !== false) out.push(window.ChartDataLabels);
        return out;
    }

    function applyTheme(spec) {
        // Globale Defaults (Schrift/Farbe) einmalig – wirkt auf alles, was wir
        // nicht ausdruecklich setzen.
        try {
            if (window.Chart && !window.Chart.__jarvisDefaults) {
                window.Chart.defaults.font.family = cssVar('--font-body', 'sans-serif');
                window.Chart.defaults.font.size = 11;
                window.Chart.defaults.color = cssVar('--text-secondary', '#94a3b8');
                window.Chart.__jarvisDefaults = true;
            }
        } catch (e) { /* Theme ist Kosmetik – nie den Chart daran scheitern lassen */ }

        colorize(spec);
        styleAxes(spec);
        styleOverlays(spec);

        var dl = datalabelDefaults(spec);
        if (dl) {
            fillDefaults(spec.options, { plugins: { datalabels: dl } });
            // Platz fuer die Labels ueber den Balken, sonst schneidet der
            // Container die oberste Zahl ab.
            if (spec.type === 'bar' || spec.type === 'line') {
                fillDefaults(spec.options, { layout: { padding: { top: 18 } } });
                spec.options.layout.padding.top = Math.max(spec.options.layout.padding.top || 0, 18);
            }
        } else if (window.ChartDataLabels) {
            // Plugin ist ggf. global registriert (fremde Seite) -> hart aus.
            fillDefaults(spec.options, { plugins: { datalabels: { display: false } } });
        }
        return spec;
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
        // Scharfe Kanten im PNG-Export (A6): der Export kopiert das Canvas in
        // seiner INTERNEN Aufloesung. Ohne diese Zeile ist das gespeicherte
        // Bild auf einem 1x-Bildschirm rund 640 px breit und damit fuer eine
        // Praesentation zu grob. Deckel 2, sonst waechst der Speicher
        // (Flaeche!) auf einem 3x-Display unnoetig.
        if (spec.options.devicePixelRatio === undefined || spec.options.devicePixelRatio === null) {
            var dpr = 1;
            try { dpr = window.devicePixelRatio || 1; } catch (e) { /* ignoriert */ }
            spec.options.devicePixelRatio = Math.max(2, Math.min(dpr, 2));
        }
        return spec;
    }

    function fail(el, msg) {
        el.className = 'jarvis-chart jarvis-chart-err';
        el.textContent = '📊 ' + msg;
    }

    function tr(key, fallback) {
        try {
            if (typeof window.t === 'function') {
                var v = window.t(key);
                if (v && v !== key) return v;
            }
        } catch (e) { /* ignoriert */ }
        return fallback;
    }

    /* ── A6: PNG speichern ────────────────────────────────────────
     * Bewusst OHNE Serverabhaengigkeit (kein chartjs-node-canvas, kein
     * headless Chrome): das Canvas liegt schon fertig gerendert im Browser.
     *
     * Der Hintergrund MUSS untergelegt werden – ein Chart.js-Canvas ist
     * transparent, und Chart.js zeichnet im Dark-Theme hellgraue Schrift.
     * Ein transparentes PNG in Word/PowerPoint eingefuegt landet auf weissem
     * Grund: hellgraue Schrift auf Weiss = unlesbar. Deshalb wird die
     * Panelfarbe der aktuellen Ansicht gefuellt (was man sieht, bekommt man).
     * Wer ein helles Bild braucht, schaltet vorher aufs Light-Theme. */
    function exportPng(el) {
        var chart = el && el._chart;
        if (!chart || !chart.canvas) return;
        var src = chart.canvas;
        try {
            var out = document.createElement('canvas');
            out.width = src.width;
            out.height = src.height;
            var g = out.getContext('2d');
            g.fillStyle = cssVar('--bg-secondary', '#111827');
            g.fillRect(0, 0, out.width, out.height);
            g.drawImage(src, 0, 0);

            var titel = '';
            try {
                var ti = chart.options && chart.options.plugins && chart.options.plugins.title;
                titel = (ti && ti.text) ? String(ti.text) : '';
                if (Array.isArray(titel)) titel = titel.join(' ');
            } catch (e) { /* ignoriert */ }
            var name = (titel || 'diagramm').toLowerCase()
                .replace(/[äöüß]/g, function (c) {
                    return { 'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss' }[c];
                })
                .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'diagramm';

            var speichern = function (url, revoke) {
                var a = document.createElement('a');
                a.href = url;
                a.download = name + '.png';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                if (revoke) setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
            };
            if (out.toBlob) {
                out.toBlob(function (blob) {
                    if (blob) speichern(URL.createObjectURL(blob), true);
                }, 'image/png');
            } else {
                speichern(out.toDataURL('image/png'), false);
            }
        } catch (e) {
            console.warn('[Charts] PNG-Export fehlgeschlagen:', e);
        }
    }

    var _DL_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>' +
        '<polyline points="7 10 12 15 17 10"></polyline>' +
        '<line x1="12" y1="15" x2="12" y2="3"></line></svg>';

    function addToolbar(el) {
        if (el.querySelector('.jarvis-chart-tools')) return;
        var bar = document.createElement('div');
        bar.className = 'jarvis-chart-tools';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'jarvis-chart-btn';
        var label = tr('chart.save_png', 'Als PNG speichern');
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.setAttribute('data-i18n-title', 'chart.save_png');
        btn.setAttribute('data-i18n-aria', 'chart.save_png');
        // Statisches, selbst erzeugtes SVG – kein Fremdinhalt (kein XSS-Weg).
        btn.innerHTML = _DL_ICON;
        btn.addEventListener('click', function (ev) {
            // Der Knopf sitzt in einer klickbaren Nachrichtenzeile (Auswahl,
            // Kontextmenue) – ohne stopPropagation loest der Klick beides aus.
            ev.preventDefault();
            ev.stopPropagation();
            exportPng(el);
        });
        bar.appendChild(btn);
        el.appendChild(bar);
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
        // Theme ist Kosmetik: schlaegt es fehl, wird das Diagramm ROH
        // gezeichnet statt gar nicht. Ein Formatierungsfehler darf keine
        // Antwort ohne Diagramm hinterlassen.
        try {
            applyTheme(spec);
        } catch (e) {
            console.warn('[Charts] Theme nicht angewendet:', e);
        }
        var canvas = document.createElement('canvas');
        el.appendChild(canvas);
        try {
            var plugs = [];
            try { plugs = instancePlugins(spec); } catch (e2) { /* ohne Plugins weiter */ }
            if (plugs.length) spec.plugins = (spec.plugins || []).concat(plugs);
            el._chart = new window.Chart(canvas.getContext('2d'), spec);
            addToolbar(el);
        } catch (e) {
            fail(el, 'Chart-Fehler: ' + (e && e.message ? e.message : e));
        }
    }

    function hydrate(root) {
        var nodes = (root || document).querySelectorAll(
            '.jarvis-chart[data-spec]:not([data-rendered])');
        for (var i = 0; i < nodes.length; i++) renderInto(nodes[i]);
    }

    /* Alle Diagramme verwerfen und neu zeichnen. Notwendig bei Theme- und
     * Sprachwechsel: Farben, Schrift und Zahlenformate stecken in der
     * fertigen Chart-Instanz und aendern sich nicht von selbst. Die
     * Original-Spec liegt unveraendert in data-spec, es wird also nichts
     * nachtraeglich "korrigiert", sondern derselbe Weg erneut gegangen. */
    function redrawAll() {
        if (!window.Chart) return;
        try { window.Chart.__jarvisDefaults = false; } catch (e) { /* ignoriert */ }
        var nodes = document.querySelectorAll('.jarvis-chart[data-rendered]');
        for (var i = 0; i < nodes.length; i++) {
            var el = nodes[i];
            if (!el.getAttribute('data-spec')) continue;
            try { if (el._chart) el._chart.destroy(); } catch (e) { /* ignoriert */ }
            el._chart = null;
            el.textContent = '';               // Canvas + Werkzeugleiste weg
            el.className = 'jarvis-chart';     // ggf. Fehlerklasse zuruecksetzen
            el.removeAttribute('data-rendered');
        }
        hydrate(document);
    }

    window.JarvisCharts = { hydrate: hydrate, redraw: redrawAll };

    // Trailing-Debounce: erst hydratisieren, wenn die DOM-Mutationen (z.B. beim
    // Streaming einer Antwort) fuer 250 ms ruhen -> kein wiederholtes Neu-Rendern.
    var timer = null;
    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(function () { hydrate(document); }, 250);
    }

    function start() {
        /* Annotation-Plugin GLOBAL registrieren ist hier richtig (anders als
         * bei datalabels): es zeichnet nur, wenn options.plugins.annotation
         * Eintraege enthaelt – ohne Angabe tut es nichts. Damit kann das
         * Modell Ziel-/Schwellenlinien setzen, ohne dass wir Plugins pro
         * Diagramm durchreichen muessen. */
        try {
            var ann = window['chartjs-plugin-annotation'];
            if (window.Chart && ann && !window.Chart.__jarvisAnnotation) {
                window.Chart.register(ann);
                window.Chart.__jarvisAnnotation = true;
            }
        } catch (e) { console.warn('[Charts] Annotation-Plugin nicht aktiv:', e); }

        hydrate(document);
        try {
            new MutationObserver(schedule).observe(
                document.body, { childList: true, subtree: true });
        } catch (e) { /* ohne Observer bleibt der initiale hydrate-Lauf */ }

        // Theme- und Sprachwechsel: neu zeichnen (Farben bzw. Zahlenformate).
        // Beide Ereignisse sind im Projekt schon vorhanden (theme.js/chat.js
        // bzw. i18n.js) – hier kommt nur ein Zuhoerer dazu.
        try {
            document.addEventListener('jarvis:themechange', function () { setTimeout(redrawAll, 0); });
            window.addEventListener('jarvis-lang-changed', function () { setTimeout(redrawAll, 0); });
        } catch (e) { /* ohne Zuhoerer bleibt die alte Faerbung bis zum Neuladen */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
