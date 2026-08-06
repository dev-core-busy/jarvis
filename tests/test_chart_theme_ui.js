/* UI-Test: Diagramm-Theme, Plugins, PNG-Export und Mermaid-Bloecke.
 *
 * Geprueft wird gegen die ECHTEN Dateien (frontend/js/charts.js,
 * mermaid_blocks.js, chatlib.js, css/theme.css) – kein Nachbau.
 *
 * DER TRICK, mit dem das ohne Browser geht: jsdom hat kein Canvas. Statt die
 * Funktionen nachzubauen, wird Chart.js durch einen ATTRAPPEN-Konstruktor
 * ersetzt, der die uebergebene Konfiguration festhaelt, und
 * HTMLCanvasElement.getContext ueberschrieben. Damit laeuft der echte Weg
 * (JSON.parse -> sanitize -> applyTheme -> new Chart) und der Test prueft
 * genau das, was Chart.js im Browser bekommen wuerde.
 *
 * Lauf:  timeout 60 node tests/test_chart_theme_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const CHARTS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/charts.js'), 'utf8');
const MERMAID_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/mermaid_blocks.js'), 'utf8');
const CHATLIB_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/chatlib.js'), 'utf8');
const THEME_CSS = fs.readFileSync(path.join(ROOT, 'frontend/css/theme.css'), 'utf8');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

/* Baut ein Fenster mit den Theme-Variablen, der Chart-Attrappe und charts.js. */
function umgebung(specs, opt) {
    opt = opt || {};
    const dom = new JSDOM(`<!doctype html><html><head><style>
        :root {
            --accent: #9B59B6; --accent-rgb: 155, 89, 182;
            --fg-rgb: 255, 255, 255; --bg-secondary: #111827;
            --text-primary: #f8fafc; --text-secondary: #94a3b8;
            --text-muted: #64748b; --font-body: TestSans, sans-serif;
        }
        body.light { --bg-secondary: #ffffff; --text-primary: #1a2233; --fg-rgb: 26, 34, 51; }
        </style></head><body${opt.light ? ' class="light"' : ''}>
        ${specs.map((s) => `<div class="jarvis-chart" data-spec="${b64(s)}"></div>`).join('')}
        </body></html>`, { url: 'https://localhost/chat', runScripts: 'outside-only' });

    const w = dom.window;
    const erzeugt = [];
    // Chart-Attrappe: haelt die Konfiguration fest, statt zu zeichnen.
    function ChartFake(ctx, cfg) {
        this.ctx = ctx;
        this.options = cfg.options;
        this.canvas = ctx && ctx.canvas;
        this.data = cfg.data;
        this.destroyed = false;
        erzeugt.push(cfg);
    }
    ChartFake.prototype.destroy = function () { this.destroyed = true; };
    ChartFake.defaults = { font: {}, color: '' };
    ChartFake.register = function () { ChartFake.registered = true; };
    w.Chart = ChartFake;
    if (opt.datalabels) w.ChartDataLabels = { id: 'datalabels' };
    if (opt.annotation) w['chartjs-plugin-annotation'] = { id: 'annotation' };
    // jsdom liefert fuer getContext null (+ Warnung) – ohne diesen Stub
    // scheitert renderInto, bevor das Theme geprueft werden kann.
    w.HTMLCanvasElement.prototype.getContext = function () {
        return { canvas: this, fillRect() {}, drawImage() {}, fillStyle: '' };
    };
    if (opt.lang) w.localStorage.setItem('jarvis_lang', opt.lang);
    ergaenzeFehlendes(w);
    w.eval(CHARTS_JS);
    // jsdom hat das Dokument beim Konstruieren noch auf 'loading' – charts.js
    // wartet dann (korrekt) auf DOMContentLoaded. Hier ausloesen, damit der
    // ECHTE Startweg samt Zuhoerern und Plugin-Registrierung laeuft.
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { dom, w, erzeugt };
}

/* jsdom bringt TextDecoder/TextEncoder nicht am Fenster mit – im Browser sind
 * sie ueberall vorhanden. Ohne sie wirft die base64-Umwandlung der Spec, und
 * der Test wuerde ein Problem melden, das es nicht gibt. */
function ergaenzeFehlendes(w) {
    const util = require('util');
    if (typeof w.TextDecoder === 'undefined') w.TextDecoder = util.TextDecoder;
    if (typeof w.TextEncoder === 'undefined') w.TextEncoder = util.TextEncoder;
    if (typeof w.DOMParser === 'undefined' && w.window) w.DOMParser = w.window.DOMParser;
}

function eineSpec(spec, opt) {
    const u = umgebung([JSON.stringify(spec)], opt);
    return { cfg: u.erzeugt[0], u };
}

/* ═════════════════════════════════════════════════════════════════════
   1. Theme setzt fehlende Optik – und nur die
   ═══════════════════════════════════════════════════════════════════ */
section('1. Theme-Layer: Farben, Achsen, Legende');

{
    const { cfg } = eineSpec({
        type: 'bar',
        data: { labels: ['Q1', 'Q2'], datasets: [{ label: 'Umsatz', data: [10, 20] }] }
    });
    check('Diagramm wird ueberhaupt erzeugt', !!cfg);
    const ds = cfg.data.datasets[0];
    check('Balken bekommen die Markenfarbe als Flaeche',
        typeof ds.backgroundColor === 'string' && /^rgba\(155,89,182/.test(ds.backgroundColor),
        String(ds.backgroundColor));
    check('Balken bekommen abgerundete Ecken', ds.borderRadius === 4);
    check('Balkenbreite ist gedeckelt', ds.maxBarThickness === 48);
    check('Kategorie-Achse ohne Gitter', cfg.options.scales.x.grid.display === false);
    check('Wert-Achse MIT Gitter', cfg.options.scales.y.grid.display === true);
    check('Achsenrahmen aus', cfg.options.scales.y.border.display === false);
    check('Wert-Achse beginnt bei 0 (Balken)', cfg.options.scales.y.beginAtZero === true);
    check('eine Datenreihe -> keine Legende', cfg.options.plugins.legend.display === false);
    check('Tooltip hat eine DECKENDE Flaeche',
        cfg.options.plugins.tooltip.backgroundColor === '#111827',
        String(cfg.options.plugins.tooltip.backgroundColor));
    check('responsive + ohne festes Seitenverhaeltnis',
        cfg.options.responsive === true && cfg.options.maintainAspectRatio === false);
    check('devicePixelRatio 2 fuer scharfen PNG-Export', cfg.options.devicePixelRatio === 2);
}

{
    const { cfg } = eineSpec({
        type: 'line',
        data: {
            labels: ['a', 'b'],
            datasets: [{ label: 'A', data: [1, 2] }, { label: 'B', data: [3, 4] }]
        }
    });
    check('zweite Datenreihe bekommt die zweite Palettenfarbe',
        cfg.data.datasets[1].borderColor === '#3b82f6', String(cfg.data.datasets[1].borderColor));
    check('Linien werden leicht geglaettet', cfg.data.datasets[0].tension === 0.3);
    check('Linienfuellung ist transparent',
        /rgba\(155,89,182,0\.15\)/.test(String(cfg.data.datasets[0].backgroundColor)));
    check('mehrere Reihen -> Legende unten',
        cfg.options.plugins.legend.display === true
        && cfg.options.plugins.legend.position === 'bottom');
    check('Legende nutzt Punkt-Symbole', cfg.options.plugins.legend.labels.usePointStyle === true);
}

{   // Viele Punkte: Marker weglassen, sonst wird die Linie zur Perlenkette
    const daten = Array.from({ length: 60 }, (_, i) => i);
    const { cfg } = eineSpec({
        type: 'line',
        data: { labels: daten.map(String), datasets: [{ label: 'X', data: daten }] }
    });
    check('viele Punkte -> keine Punktmarkierungen', cfg.data.datasets[0].pointRadius === 0);
}

{   // Kreisdiagramm: Segmentfarben + Trennlinie in Panelfarbe
    const { cfg } = eineSpec({
        type: 'doughnut',
        data: { labels: ['a', 'b', 'c'], datasets: [{ label: 'Anteile', data: [1, 2, 3] }] }
    });
    check('Kreissegmente werden einzeln gefaerbt',
        Array.isArray(cfg.data.datasets[0].backgroundColor)
        && cfg.data.datasets[0].backgroundColor.length === 3);
    check('Segmenttrennung in Panelfarbe', cfg.data.datasets[0].borderColor === '#111827');
    check('Kreisdiagramm behaelt die Legende', cfg.options.plugins.legend.display === true);
    check('Kreisdiagramm hat KEINE Achsen angelegt', cfg.options.scales === undefined);
}

/* ═════════════════════════════════════════════════════════════════════
   2. Vorrang: was das Modell sagt, gilt
   ═══════════════════════════════════════════════════════════════════ */
section('2. Vorrang der Modell-Angaben');

{
    const { cfg } = eineSpec({
        type: 'bar',
        data: { labels: ['a'], datasets: [{ label: 'X', data: [1], backgroundColor: '#ff0000' }] },
        options: {
            plugins: { legend: { display: true, position: 'top' } },
            scales: { y: { grid: { display: false }, beginAtZero: false } }
        }
    });
    check('ausdrueckliche Farbe bleibt', cfg.data.datasets[0].backgroundColor === '#ff0000');
    check('ausdrueckliche Legendenposition bleibt', cfg.options.plugins.legend.position === 'top');
    check('Legende bleibt an, obwohl nur eine Reihe', cfg.options.plugins.legend.display === true);
    check('ausdrueckliches "kein Gitter" bleibt', cfg.options.scales.y.grid.display === false);
    check('ausdrueckliches beginAtZero:false bleibt (false gilt als Angabe)',
        cfg.options.scales.y.beginAtZero === false);
}

{   // DER KERNFALL: charts.js ersetzt gestrippte Callbacks durch null. null
    // MUSS als "nicht gesetzt" gelten, sonst bleibt die Achse unformatiert.
    const { cfg } = eineSpec({
        type: 'bar',
        data: { labels: ['a'], datasets: [{ label: 'X', data: [1000] }] },
        options: { scales: { y: { ticks: { callback: null } } } }
    });
    check('null-Callback wird durch unseren Formatter ersetzt',
        typeof cfg.options.scales.y.ticks.callback === 'function');
    const f = cfg.options.scales.y.ticks.callback;
    check('Achsenzahl deutsch formatiert (1.234)', f(1234) === '1.234', String(f(1234)));
    check('grosse Achsenzahl kompakt', /Mio|Mill/.test(String(f(1200000))), String(f(1200000)));
    check('Tooltip-Formatter vorhanden',
        typeof cfg.options.plugins.tooltip.callbacks.label === 'function');
}

{   // Englische Anzeige -> englische Zahlformate
    const { cfg } = eineSpec({
        type: 'bar', data: { labels: ['a'], datasets: [{ label: 'X', data: [1234] }] }
    }, { lang: 'en' });
    const f = cfg.options.scales.y.ticks.callback;
    check('bei Sprache EN wird 1,234 formatiert', f(1234) === '1,234', String(f(1234)));
}

{   // Titel nur zeigen, wenn Text da ist
    const a = eineSpec({ type: 'bar', data: { labels: ['x'], datasets: [{ data: [1] }] } }).cfg;
    check('ohne Titeltext kein Titel', !(a.options.plugins.title && a.options.plugins.title.display));
    const b = eineSpec({
        type: 'bar', data: { labels: ['x'], datasets: [{ data: [1] }] },
        options: { plugins: { title: { text: 'Absatz je Monat' } } }
    }).cfg;
    check('Titeltext schaltet den Titel sichtbar', b.options.plugins.title.display === true);
    check('Titel bekommt Theme-Schriftfarbe', b.options.plugins.title.color === '#f8fafc');
}

{   // Hell-Modus liest andere Variablen
    const { cfg } = eineSpec({
        type: 'bar', data: { labels: ['x'], datasets: [{ data: [1] }] }
    }, { light: true });
    check('Hell-Modus: Tooltipflaeche weiss', cfg.options.plugins.tooltip.backgroundColor === '#ffffff');
    check('Hell-Modus: dunkler Titeltext', cfg.options.plugins.title.color === '#1a2233');
}

/* ═════════════════════════════════════════════════════════════════════
   3. Werte-Labels (datalabels) nur wenn lesbar
   ═══════════════════════════════════════════════════════════════════ */
section('3. Werte-Labels');

function dl(spec, opt) {
    const { cfg } = eineSpec(spec, Object.assign({ datalabels: true }, opt || {}));
    return cfg;
}
{
    const cfg = dl({ type: 'bar', data: { labels: ['a', 'b'], datasets: [{ data: [1, 2] }] } });
    check('wenige Balken -> Werte-Labels an', cfg.options.plugins.datalabels.display !== false);
    check('Label-Plugin wird pro Diagramm zugeschaltet',
        Array.isArray(cfg.plugins) && cfg.plugins.some((p) => p && p.id === 'datalabels'));
    check('Platz oben fuer die Zahlen', cfg.options.layout.padding.top >= 18);
    const fmt = cfg.options.plugins.datalabels.formatter;
    check('Label-Formatter formatiert lokalisiert', fmt(1500) === '1.500', String(fmt(1500)));

    const viele = Array.from({ length: 40 }, (_, i) => i);
    const cfg2 = dl({ type: 'bar', data: { labels: viele.map(String), datasets: [{ data: viele }] } });
    check('40 Balken -> Werte-Labels AUS', cfg2.options.plugins.datalabels.display === false);
    check('Plugin dann NICHT zugeschaltet',
        !(cfg2.plugins || []).some((p) => p && p.id === 'datalabels'));

    const cfg3 = dl({ type: 'scatter', data: { datasets: [{ data: [{ x: 1, y: 2 }] }] } });
    check('Streudiagramm nie mit Werte-Labels', cfg3.options.plugins.datalabels.display === false);

    const cfg4 = dl({ type: 'pie', data: { labels: ['a', 'b'], datasets: [{ data: [30, 70] }] } });
    const pf = cfg4.options.plugins.datalabels.formatter;
    const ctx = { chart: { data: { datasets: [{ data: [30, 70] }] } }, datasetIndex: 0 };
    check('Kreisdiagramm zeigt Prozente', pf(70, ctx) === '70 %', String(pf(70, ctx)));
    check('Splitter unter 5 % werden weggelassen',
        pf(2, { chart: { data: { datasets: [{ data: [2, 98] }] } }, datasetIndex: 0 }) === '');

    const cfg5 = dl({
        type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] },
        options: { plugins: { datalabels: { display: false } } }
    });
    check('ausdrueckliches "aus" wird respektiert',
        cfg5.options.plugins.datalabels.display === false);
}
{
    const cfg = eineSpec({ type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] } }).cfg;
    check('ohne geladenes Plugin keine plugins-Liste', !(cfg.plugins || []).length);
}

/* ═════════════════════════════════════════════════════════════════════
   4. Annotation-Plugin (Ziellinien)
   ═══════════════════════════════════════════════════════════════════ */
section('4. Annotation-Plugin');

{
    const u = umgebung([JSON.stringify({
        type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] },
        options: { plugins: { annotation: { annotations: { ziel: { type: 'line', yMin: 5, yMax: 5 } } } } }
    })], { annotation: true });
    check('Annotation-Plugin wird global registriert', u.w.Chart.registered === true);
    check('Annotation-Angaben bleiben unveraendert',
        u.erzeugt[0].options.plugins.annotation.annotations.ziel.yMin === 5);
}

/* ═════════════════════════════════════════════════════════════════════
   5. PNG-Export
   ═══════════════════════════════════════════════════════════════════ */
section('5. PNG-Export');

{
    const u = umgebung([JSON.stringify({
        type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] },
        options: { plugins: { title: { text: 'Umsatz Süd & Nord' } } }
    })]);
    const el = u.w.document.querySelector('.jarvis-chart');
    const btn = el.querySelector('.jarvis-chart-tools .jarvis-chart-btn');
    check('Werkzeugleiste mit Knopf ist da', !!btn);
    check('Knopf hat einen Titel', btn && /PNG/.test(btn.getAttribute('title') || ''));
    check('Knopf ist i18n-verdrahtet',
        btn && btn.getAttribute('data-i18n-title') === 'chart.save_png');
    check('Knopf hat ein aria-label', btn && !!btn.getAttribute('aria-label'));
    check('Knopf ist ein <button type=button> (kein Formular-Absenden)',
        btn && btn.tagName === 'BUTTON' && btn.getAttribute('type') === 'button');

    // Export: Hintergrund MUSS gefuellt werden (transparentes PNG waere in
    // Word unlesbar), Dateiname aus dem Titel.
    let gefuellt = null, gezeichnet = false, dateiname = null, blobAbgefragt = false;
    u.w.HTMLCanvasElement.prototype.getContext = function () {
        const self = this;
        return {
            canvas: self,
            set fillStyle(v) { gefuellt = v; },
            get fillStyle() { return gefuellt; },
            fillRect() {}, drawImage() { gezeichnet = true; }
        };
    };
    u.w.HTMLCanvasElement.prototype.toBlob = function (cb) { blobAbgefragt = true; cb(null); };
    u.w.URL.createObjectURL = () => 'blob:test';
    const echtesClick = u.w.HTMLAnchorElement.prototype.click;
    u.w.HTMLAnchorElement.prototype.click = function () { dateiname = this.download; };
    btn.dispatchEvent(new u.w.MouseEvent('click', { bubbles: true }));
    check('Export unterlegt einen deckenden Hintergrund', gefuellt === '#111827', String(gefuellt));
    check('Export kopiert das Diagramm-Canvas', gezeichnet === true);
    check('Export nutzt toBlob', blobAbgefragt === true);
    u.w.HTMLAnchorElement.prototype.click = echtesClick;

    // Dateiname: Umlaute und Sonderzeichen muessen weg
    let name2 = null;
    u.w.HTMLCanvasElement.prototype.toBlob = function (cb) {
        cb({ size: 1, type: 'image/png' });
    };
    u.w.HTMLAnchorElement.prototype.click = function () { name2 = this.download; };
    btn.dispatchEvent(new u.w.MouseEvent('click', { bubbles: true }));
    check('Dateiname aus dem Titel, ohne Umlaute/Sonderzeichen',
        name2 === 'umsatz-sued-nord.png', String(name2));
    u.w.HTMLAnchorElement.prototype.click = echtesClick;
}

{   // Der Knopf sitzt in einer klickbaren Nachrichtenzeile: der Klick darf
    // nicht nach oben durchschlagen (Auswahl/Kontextmenue der Bubble).
    const u = umgebung([JSON.stringify({ type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] } })]);
    const el = u.w.document.querySelector('.jarvis-chart');
    let durchgeschlagen = false;
    u.w.document.body.addEventListener('click', () => { durchgeschlagen = true; });
    u.w.HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); };
    el.querySelector('.jarvis-chart-btn').dispatchEvent(new u.w.MouseEvent('click', { bubbles: true }));
    check('Klick auf den Knopf blubbert NICHT zur Nachrichtenzeile', durchgeschlagen === false);
}

/* ═════════════════════════════════════════════════════════════════════
   6. Robustheit: kaputte Specs, Neuzeichnen
   ═══════════════════════════════════════════════════════════════════ */
section('6. Robustheit');

{
    // LLM-Config mit Callback UND fehlender Klammer (der bekannte Fall)
    const roh = '{"type":"bar","data":{"labels":["a"],"datasets":[{"label":"X","data":[1],'
        + '"borderColor":"#123456"}]},"options":{"scales":{"y":{"ticks":{'
        + '"callback": function(v){ return v + " €"; }}}}}';
    const u = umgebung([roh]);
    check('kaputte Konfiguration wird trotzdem gerendert', u.erzeugt.length === 1);
    check('Callback wurde nicht ausgefuehrt, sondern ersetzt',
        u.erzeugt.length === 1 && typeof u.erzeugt[0].options.scales.y.ticks.callback === 'function');
    check('Modell-Farbe hat den Reparaturweg ueberlebt',
        u.erzeugt[0].data.datasets[0].borderColor === '#123456');
}
{
    const u = umgebung(['{"type":"tabelle","data":{}}']);
    const el = u.w.document.querySelector('.jarvis-chart');
    check('unerlaubter Typ -> Fehlertext, kein Diagramm',
        u.erzeugt.length === 0 && /nicht erlaubt/.test(el.textContent));
    check('Fehlerzustand traegt die Fehlerklasse', /jarvis-chart-err/.test(el.className));
}
{
    const u = umgebung(['{kaputt']);
    check('unlesbare Spec -> Meldung statt Absturz',
        u.erzeugt.length === 0 && /ungültig/.test(u.w.document.querySelector('.jarvis-chart').textContent));
}
{   // Theme-Wechsel: neu zeichnen, damit Farben/Formate mitgehen
    const u = umgebung([JSON.stringify({ type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] } })]);
    const erstes = u.erzeugt[0];
    u.w.document.body.classList.add('light');
    u.w.document.dispatchEvent(new u.w.CustomEvent('jarvis:themechange', { detail: { light: true } }));
    return new Promise((r) => setTimeout(r, 30)).then(() => {
        check('Theme-Wechsel zeichnet neu', u.erzeugt.length === 2);
        check('Neuzeichnung nutzt die neuen Farben',
            u.erzeugt[1] && u.erzeugt[1].options.plugins.tooltip.backgroundColor === '#ffffff');
        check('die Original-Spec wurde nicht veraendert (Daten bleiben)',
            u.erzeugt[1] && u.erzeugt[1].data.datasets[0].data[0] === 1);
        check('genau ein Canvas im Container (altes entfernt)',
            u.w.document.querySelectorAll('.jarvis-chart canvas').length === 1);
        check('genau eine Werkzeugleiste (nicht verdoppelt)',
            u.w.document.querySelectorAll('.jarvis-chart-tools').length === 1);
        check('JarvisCharts stellt hydrate + redraw bereit',
            typeof u.w.JarvisCharts.hydrate === 'function' && typeof u.w.JarvisCharts.redraw === 'function');
        weiter();
    });
}

/* ═════════════════════════════════════════════════════════════════════
   7. Mermaid: Markdown-Erkennung, Laden auf Anforderung, Sicherheit
   ═══════════════════════════════════════════════════════════════════ */
function weiter() {
    section('7. Mermaid-Bloecke');

    // 7a) chatlib.js erkennt ```mermaid und macht einen Platzhalter daraus
    {
        const dom = new JSDOM('<!doctype html><body></body>', { url: 'https://localhost/chat', runScripts: 'outside-only' });
        ergaenzeFehlendes(dom.window);
        dom.window.eval(CHATLIB_JS);
        const rm = dom.window.JarvisChatLib && dom.window.JarvisChatLib.renderMarkdown;
        check('renderMarkdown ist erreichbar', typeof rm === 'function');
        if (typeof rm === 'function') {
            const html = rm('Ablauf:\n\n```mermaid\nflowchart LR\n A-->B\n```\n');
            check('```mermaid wird zum Platzhalter', /class="jarvis-mermaid"/.test(html));
            check('Quelle liegt base64 im data-Attribut', /data-src="[A-Za-z0-9+/=]+"/.test(html));
            const m = /data-src="([^"]+)"/.exec(html);
            check('Quelle ist wiederherstellbar',
                m && Buffer.from(m[1], 'base64').toString('utf8').includes('flowchart LR'));
            check('Mermaid-Quelle landet NICHT als <pre><code>', !/<code>flowchart/.test(html));

            const h2 = rm('```chartjs\n{"type":"bar"}\n```');
            check('chartjs bleibt ein Chart-Platzhalter', /class="jarvis-chart"/.test(h2));
            const h3 = rm('```python\nprint(1)\n```');
            check('anderer Code bleibt ein Codeblock', /<pre><code>/.test(h3));
            const h4 = rm('```mmd\ngraph TD\n A-->B\n```');
            check('Kurzform ```mmd wird auch erkannt', /class="jarvis-mermaid"/.test(h4));
        }
    }

    // 7b) mermaid_blocks.js: laedt die Bibliothek NUR bei Bedarf
    {
        const dom = new JSDOM('<!doctype html><body></body>', { url: 'https://localhost/chat', runScripts: 'outside-only' });
        const w = dom.window;
        let geladen = 0;
        const echtesAppend = w.document.head.appendChild.bind(w.document.head);
        w.document.head.appendChild = function (n) {
            if (n.tagName === 'SCRIPT' && /mermaid/.test(n.src || '')) geladen++;
            return echtesAppend(n);
        };
        ergaenzeFehlendes(w);
        w.eval(MERMAID_JS);
        w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
        check('ohne Schaubild wird mermaid.min.js NICHT geholt (2,7 MB)', geladen === 0);
        check('JarvisMermaid ist bereitgestellt', typeof w.JarvisMermaid.hydrate === 'function');

        const d = w.document.createElement('div');
        d.className = 'jarvis-mermaid';
        d.setAttribute('data-src', b64('flowchart LR\n A-->B'));
        w.document.body.appendChild(d);
        w.JarvisMermaid.hydrate(w.document);
        check('mit Schaubild wird die Bibliothek geholt', geladen === 1);
        check('Knoten ist sofort als bearbeitet markiert (kein Doppellauf)',
            d.getAttribute('data-rendered') === '1');
        w.JarvisMermaid.hydrate(w.document);
        check('zweiter Lauf laedt nicht erneut', geladen === 1);
    }

    // 7c) Rendern mit einer Mermaid-Attrappe + Sicherheitsvorgaben
    {
        const dom = new JSDOM('<!doctype html><body><div class="jarvis-mermaid" data-src="'
            + b64('flowchart LR\n A-->B') + '"></div></body>', { url: 'https://localhost/chat', runScripts: 'outside-only' });
        const w = dom.window;
        let conf = null, quelle = null;
        w.mermaid = {
            initialize(c) { conf = c; },
            render(id, text) {
                quelle = text;
                // Enthaelt absichtlich alles, was gefaehrlich ODER
                // faelschlich als gefaehrlich eingestuft werden koennte:
                // Skript, Ereignis-Attribut, javascript:-Ziel – und ein
                // <foreignObject> mit einer BESCHRIFTUNG, die erhalten
                // bleiben MUSS (die erste Fassung loeschte sie mit und
                // hinterliess leere Kaesten).
                return Promise.resolve({
                    svg: '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                        + '<script>window.__boese = 1;<\/script>'
                        + '<g onclick="window.__boese2 = 1"><text>A</text></g>'
                        + '<a xmlns:xlink="http://www.w3.org/1999/xlink" href="javascript:alert(1)">'
                        + '<text>Link</text></a>'
                        + '<foreignObject width="80" height="20">'
                        + '<div xmlns="http://www.w3.org/1999/xhtml">Antrag eingegangen</div>'
                        + '</foreignObject></svg>'
                });
            }
        };
        ergaenzeFehlendes(w);
        w.eval(MERMAID_JS);
        w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
        return new Promise((r) => setTimeout(r, 60)).then(() => {
            check('Mermaid wird initialisiert', !!conf);
            check('securityLevel strict', conf && conf.securityLevel === 'strict');
            check('htmlLabels aus (kein HTML aus Modelltext)',
                conf && conf.flowchart && conf.flowchart.htmlLabels === false);
            // Im Browser nachgemessen: nur unter `flowchart` gesetzt bleiben
            // die Kantenbeschriftungen HTML (foreignObject). Erst global
            // gesetzt rendert Mermaid alles als SVG-Text.
            check('htmlLabels auch GLOBAL aus (sonst bleiben foreignObjects)',
                conf && conf.htmlLabels === false);
            check('startOnLoad aus (wir steuern das Rendern)', conf && conf.startOnLoad === false);
            check('Markenfarbe wird durchgereicht',
                conf && conf.themeVariables === undefined || (conf.themeVariables && 'primaryColor' in conf.themeVariables));
            check('die Quelle wird unveraendert uebergeben', /flowchart LR/.test(String(quelle)));
            const el = w.document.querySelector('.jarvis-mermaid');
            check('SVG landet im Container', !!el.querySelector('svg'));
            check('<script> im SVG wird ENTFERNT', !el.querySelector('script'));
            check('kein Skript ausgefuehrt', w.__boese === undefined);
            const g = el.querySelector('g');
            check('Ereignis-Attribut (onclick) wird entfernt',
                g && !g.hasAttribute('onclick'));
            const a = el.querySelector('a');
            check('javascript:-Ziel wird entfernt',
                a && !/javascript:/i.test(a.getAttribute('href') || ''));
            // DER REGRESSIONSFALL: Beschriftungen in <foreignObject> muessen
            // BLEIBEN. Die erste Fassung entfernte das Element und zeigte im
            // Browser leere Kaesten mit Pfeilen dazwischen.
            check('Beschriftung in <foreignObject> BLEIBT sichtbar',
                /Antrag eingegangen/.test(el.textContent), el.textContent.slice(0, 40));
            fertig();
        });
    }
}

/* ═════════════════════════════════════════════════════════════════════
   8. CSS liegt dort, wo ALLE Seiten hinschauen
   ═══════════════════════════════════════════════════════════════════ */
function fertig() {
    section('8. CSS-Ort und HTML-Einbindung');

    check('.jarvis-chart steht in theme.css (laedt jede Seite)',
        /\.jarvis-chart\s*\{/.test(THEME_CSS));
    check('.jarvis-mermaid steht in theme.css', /\.jarvis-mermaid\s*\{/.test(THEME_CSS));
    check('Container hat eine Hoehe (sonst rendert Chart.js ins Nichts)',
        /\.jarvis-chart\s*\{[^}]*height:\s*\d/.test(THEME_CSS));
    const chatCss = fs.readFileSync(path.join(ROOT, 'frontend/css/chat.css'), 'utf8');
    check('chat.css hat KEINE eigene .jarvis-chart-Regel mehr (kein Drift)',
        !/\.jarvis-chart\s*\{/.test(chatCss));
    check('Werkzeugleiste ist deckend (liegt ueber den Daten)',
        /\.jarvis-chart-btn\s*\{[^}]*background-color:\s*var\(--bg-secondary\)/.test(THEME_CSS));
    check('keine harten Farben in den neuen Regeln',
        !/\.jarvis-chart-btn\s*\{[^}]*#[0-9a-f]{6}/i.test(THEME_CSS));

    for (const seite of ['chat.html', 'sap.html', 'support.html']) {
        const html = fs.readFileSync(path.join(ROOT, 'frontend', seite), 'utf8');
        const iChart = html.indexOf('chart.umd.min.js');
        const iDl = html.indexOf('chartjs-plugin-datalabels');
        const iAnn = html.indexOf('chartjs-plugin-annotation');
        const iOwn = html.indexOf('js/charts.js');
        check(`${seite}: Chart.js, Plugins und charts.js in dieser Reihenfolge`,
            iChart > 0 && iDl > iChart && iAnn > iChart && iOwn > iDl && iOwn > iAnn,
            `chart=${iChart} dl=${iDl} ann=${iAnn} own=${iOwn}`);
        check(`${seite}: mermaid_blocks.js eingebunden`, html.includes('mermaid_blocks.js'));
    }
    const uc = fs.readFileSync(path.join(ROOT, 'frontend/userchat.html'), 'utf8');
    check('userchat.html: Mermaid ja, Chart.js nein (kein LLM-Chat)',
        uc.includes('mermaid_blocks.js') && !uc.includes('chart.umd.min.js'));

    for (const f of ['chartjs-plugin-datalabels.min.js', 'chartjs-plugin-annotation.min.js',
                     'mermaid.min.js']) {
        const p = path.join(ROOT, 'frontend/js/vendor', f);
        check(`Vendor-Datei vorhanden: ${f}`, fs.existsSync(p) && fs.statSync(p).size > 5000);
    }
    const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
    check('i18n-Schluessel chart.save_png in DE und EN',
        (i18n.match(/'chart\.save_png'/g) || []).length === 2);

    // Abschluss
    const ok = results.filter((r) => r.ok).length;
    const bad = results.length - ok;
    console.log(`\n${'='.repeat(60)}\nErgebnis: ${ok}/${results.length} Pruefungen bestanden`);
    if (bad) {
        console.log(`\x1b[31mFEHLGESCHLAGEN: ${bad}\x1b[0m`);
        results.filter((r) => !r.ok).forEach((r) => console.log('  ✗ ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    // jsdom-Tests beenden sich nicht von selbst (offene Timer/Observer).
    process.exit(bad ? 1 : 0);
}
