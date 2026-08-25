/* ═══════════════════════════════════════════════════════════════════
   Waechter: Vorgabe-Thema ist HELL (seit 2026-08-25)
   ───────────────────────────────────────────────────────────────────
   Vorher war Dunkel die Vorgabe. Die Umstellung beruehrt VIELE Dateien –
   14 HTML-Seiten mit je einem Anti-Flacker-Skript plus theme.js und
   chat.js. Genau dort ist die Fehlerklasse „eine Seite vergessen"
   teuer: sie faellt nicht auf, weil die Seite ja funktioniert – sie
   sieht nur anders aus als alle anderen.

   ZWEI FALLEN, die dieser Test abdeckt:
   1. Geprueft werden muss auf `!== 'dark'`, NICHT auf `=== 'light'`.
      Mit der alten Bedingung waere die Vorgabe dunkel geblieben.
   2. Das Anti-Flacker-Skript war fuer den SELTENEN Fall gebaut. Jetzt
      ist Hell der Normalfall: fehlt es auf einer Seite, blitzt bei
      JEDEM Laden Dunkel auf, statt wie frueher nur ausnahmsweise.

   Aufruf: node tests/test_theme_default.js
   ═══════════════════════════════════════════════════════════════════ */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.dirname(__dirname);
let ok = 0, fail = 0;
function pruefe(b, t) {
    if (b) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + t); }
    else   { fail++; console.log('  \x1b[31m✗\x1b[0m ' + t); }
}
function abschnitt(t) { console.log('\n── ' + t); }

// ── 1 · Alle Seiten mit Theme tragen das Anti-Flacker-Skript ──────────
abschnitt('1 · Anti-Flacker-Skript auf jeder Seite mit Thema');

const SEITEN = [];
for (const d of ['', 'addin', 'excel-addin']) {
    const dir = path.join(ROOT, 'frontend', d);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
        if (f.endsWith('.html')) SEITEN.push(path.join(dir, f));
    }
}
pruefe(SEITEN.length >= 14, `${SEITEN.length} HTML-Seiten gefunden (Basis der Pruefung)`);

const MIT_THEMA = SEITEN.filter(p => {
    const s = fs.readFileSync(p, 'utf8');
    return s.includes('theme.js') || s.includes('theme.css');
});
let ohneSkript = [], altebedingung = [], falschePosition = [];
for (const p of MIT_THEMA) {
    const s = fs.readFileSync(p, 'utf8');
    const rel = path.relative(ROOT, p);
    if (s.includes("jarvis_theme')==='light'")) altebedingung.push(rel);
    if (!s.includes("jarvis_theme')!=='dark'")) { ohneSkript.push(rel); continue; }
    // Es MUSS vor dem Inhalt stehen – sonst rendert der Browser erst dunkel.
    const iBody = s.indexOf('<body');
    const iAusdruck = s.indexOf("jarvis_theme')!=='dark'");
    // Gemessen wird der Anfang des <script>-TAGS, nicht der Ausdruck darin –
    // sonst zaehlt der Test die eigene Skript-Einleitung als "davor" und
    // meldet auf JEDER Seite dieselben 37 Zeichen Abstand.
    const iSkript = s.lastIndexOf('<script', iAusdruck);
    const dazwischen = s.slice(s.indexOf('>', iBody) + 1, iSkript).trim();
    if (iSkript < iBody || dazwischen.length > 0) falschePosition.push(rel + ' (' + dazwischen.length + ' Zeichen davor)');
}
pruefe(ohneSkript.length === 0, 'jede Seite mit Thema hat das Skript' +
    (ohneSkript.length ? ' – FEHLT: ' + ohneSkript.join(', ') : ` (${MIT_THEMA.length} Seiten)`));
pruefe(altebedingung.length === 0, 'keine Seite prueft noch auf ===\'light\'' +
    (altebedingung.length ? ' – ALT: ' + altebedingung.join(', ') : ''));
pruefe(falschePosition.length === 0, 'das Skript steht unmittelbar nach <body>' +
    (falschePosition.length ? ' – VERSPAETET: ' + falschePosition.join(', ') : ''));

// ── 2 · theme.js WIRKLICH ausfuehren ─────────────────────────────────
abschnitt('2 · theme.js entscheidet richtig (ausgefuehrt, nicht gelesen)');

const THEME_JS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'theme.js'), 'utf8');

function themeLauf(gespeichert) {
    const dom = new JSDOM('<!doctype html><html><body><button id="btn-theme-toggle">' +
        '<span class="theme-icon-moon"></span><span class="theme-icon-sun"></span></button></body></html>',
        { url: 'https://localhost/', runScripts: 'outside-only' });
    const w = dom.window;
    const speicher = {};
    if (gespeichert !== null) speicher['jarvis_theme'] = gespeichert;
    Object.defineProperty(w, 'localStorage', {
        value: {
            getItem: k => (k in speicher ? speicher[k] : null),
            setItem: (k, v) => { speicher[k] = String(v); },
            removeItem: k => { delete speicher[k]; },
        }, configurable: true,
    });
    w.eval(THEME_JS);
    return { w, speicher };
}

// jsdom meldet direkt nach `new JSDOM` noch readyState 'loading' (gemessen).
// theme.js haengt sich dann an DOMContentLoaded – wer sofort auswertet,
// prueft den Zustand VOR der Initialisierung und bekommt ueberall "dunkel".
function fertig(w) {
    return new Promise(r => {
        if (w.document.readyState !== 'loading') return setTimeout(r, 0);
        w.document.addEventListener('DOMContentLoaded', () => setTimeout(r, 0));
    });
}
const istHell = w => w.document.body.classList.contains('light');

(async () => {
const a = themeLauf(null);   await fertig(a.w);
pruefe(istHell(a.w), 'ohne gespeicherte Wahl (= neuer Benutzer) ist es HELL');
const b = themeLauf('dark'); await fertig(b.w);
pruefe(!istHell(b.w), 'ein ausdrueckliches "dark" wird respektiert');
const c = themeLauf('light'); await fertig(c.w);
pruefe(istHell(c.w), 'ein ausdrueckliches "light" wird respektiert');

// Der Umschalter muss in BEIDE Richtungen arbeiten und die Wahl sichern –
// sonst waere die neue Vorgabe eine Einbahnstrasse.
const d = themeLauf(null); await fertig(d.w);
d.w.document.getElementById('btn-theme-toggle').dispatchEvent(new d.w.Event('click'));
pruefe(!istHell(d.w), 'ein Klick schaltet von der Vorgabe auf Dunkel');
pruefe(d.speicher['jarvis_theme'] === 'dark',
       'und speichert "dark" (sonst waere es beim naechsten Laden wieder hell)');
d.w.document.getElementById('btn-theme-toggle').dispatchEvent(new d.w.Event('click'));
pruefe(istHell(d.w) && d.speicher['jarvis_theme'] === 'light',
       'ein zweiter Klick schaltet zurueck auf Hell');

// Die Symbole muessen zum Zustand passen – bei der Vorgabe wird apply()
// gerufen, also darf kein Mond mehr sichtbar sein.
pruefe(a.w.document.querySelector('.theme-icon-moon').style.display === 'none' &&
       a.w.document.querySelector('.theme-icon-sun').style.display !== 'none',
       'die Symbole folgen der Vorgabe (Sonne sichtbar, Mond aus)');

// ── 3 · chat.js hat dieselbe Vorgabe ─────────────────────────────────
abschnitt('3 · chat.js (eigener, kompatibler Umschalter)');

const CHAT_JS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'chat.js'), 'utf8');
// Auf den AUFRUF pruefen, nicht auf das Wort: die Begruendung im Kommentar
// daneben nennt 'dark' ebenfalls.
const ohneKommentar = CHAT_JS.split('\n').filter(z => !z.trim().startsWith('//')).join('\n');
pruefe(ohneKommentar.includes("applyTheme(savedTheme !== 'dark')"),
       'chat.js schaltet bei allem ausser "dark" auf Hell');
pruefe(!ohneKommentar.includes("if (savedTheme === 'light') applyTheme(true)"),
       'die alte Bedingung ist weg');

console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
process.exit(fail ? 1 : 0);
})();
