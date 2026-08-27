/* ═══════════════════════════════════════════════════════════════════
   Waechter: Issue-Fenster oeffnet mit dem Filter „offen" (2026-08-27)
   ───────────────────────────────────────────────────────────────────
   Vorgabe war „alle" – beim Oeffnen stand damit das Archiv oben mit
   drin, obwohl beim Aufschlagen des Fensters interessiert, was noch
   aussteht. „alle" bleibt einen Klick entfernt.

   MIT DER VORGABE KAM EINE ZWEITE PFLICHT: der Zaehler in der
   Werkzeugleiste nannte immer die GESAMTZAHL. Bei gesetztem Filter
   waere das eine Zahl ueber eine Liste, die so gar nicht dasteht –
   genau die Fehlerklasse „eine Anzeige behauptet einen Zustand, den
   sie nicht kennt". Er nennt jetzt „angezeigt / gesamt".

   Der Test fuehrt issues.js WIRKLICH aus (jsdom + Attrappen-fetch),
   statt den Quelltext zu lesen: geprueft wird, was gerendert wird.

   Aufruf: node tests/test_issues_filter_ui.js
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

// jsdom braucht ein `url:` – auf about:blank ist localStorage unbenutzbar
// und issues.js saehe ein fehlendes Token, das im Browser da ist.
const dom = new JSDOM('<!doctype html><html><body></body></html>',
                      { url: 'https://localhost/portal' });
global.window = dom.window;
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
localStorage.setItem('jarvis_token', 'testtoken');
// Uebersetzung als Kennung zurueckgeben: der Test prueft Struktur, nicht Text.
global.t = dom.window.t = (k) => k;

const ISSUES = [
    { id: '1', title: 'A', status: 'open',        type: 'bug',     author: 'a', created: '2026-01-01' },
    { id: '2', title: 'B', status: 'closed',      type: 'bug',     author: 'a', created: '2026-01-02' },
    { id: '3', title: 'C', status: 'in_progress', type: 'feature', author: 'b', created: '2026-01-03' },
    { id: '4', title: 'D', status: 'open',        type: 'feature', author: 'b', created: '2026-01-04' },
];
global.fetch = dom.window.fetch = async () => ({
    ok: true, status: 200,
    json: async () => ({ issues: ISSUES, current_user: 'a', is_admin: false }),
});

// issues.js liest `window`/`document` aus dem Node-Kontext (kein runScripts) –
// deshalb die globalen Zuweisungen oben.
dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/issues.js'), 'utf8'));

function titel() {
    return [...document.querySelectorAll('.jv-iss-item-title')].map(e => e.textContent).join(',');
}

(async () => {
    abschnitt('1 · Vorgabe beim Oeffnen');
    window.JarvisIssues.open();
    await new Promise(r => setTimeout(r, 150));

    const sel = document.getElementById('jv-iss-flt-status');
    pruefe(!!sel, 'Status-Pulldown gerendert');
    pruefe(!!sel && sel.value === 'open', 'Pulldown steht auf „offen"');
    pruefe(document.querySelectorAll('.jv-iss-item').length === 2,
        'nur die zwei offenen Eintraege gelistet');
    pruefe(titel() === 'A,D', 'es sind die richtigen zwei (A, D)');

    abschnitt('2 · Zaehler nennt die ANGEZEIGTEN Eintraege');
    const cnt = document.getElementById('jv-iss-count');
    pruefe(!!cnt, 'Zaehler-Element vorhanden');
    pruefe(!!cnt && /^2 \/ 4\b/.test(cnt.textContent),
        `Zaehler zeigt „2 / 4" (ist: „${cnt ? cnt.textContent : '–'}")`);

    abschnitt('3 · „alle" bleibt einen Klick entfernt');
    sel.value = ''; sel.onchange();
    await new Promise(r => setTimeout(r, 20));
    pruefe(document.querySelectorAll('.jv-iss-item').length === 4, 'alle vier Eintraege');
    pruefe(!document.getElementById('jv-iss-count').textContent.includes('/'),
        'ohne Filter nennt der Zaehler nur die Gesamtzahl');

    abschnitt('4 · Die uebrigen Filter wirken weiter');
    sel.value = 'open'; sel.onchange();
    const typ = document.getElementById('jv-iss-flt-type');
    typ.value = 'feature'; typ.onchange();
    await new Promise(r => setTimeout(r, 20));
    pruefe(titel() === 'D', 'offen + Typ „feature" ergibt genau D');
    const mine = document.getElementById('jv-iss-flt-mine');
    typ.value = ''; typ.onchange();
    mine.checked = true; mine.onchange();
    await new Promise(r => setTimeout(r, 20));
    pruefe(titel() === 'A', 'offen + „nur meine" ergibt genau A');

    console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
    dom.window.close();
    process.exit(fail ? 1 : 0);
})();
