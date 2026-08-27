/* ═══════════════════════════════════════════════════════════════════
   Waechter: Skill-Listen stehen alphabetisch (2026-08-27)
   ───────────────────────────────────────────────────────────────────
   „Installierte Skills" und „Mögliche Skills" uebernahmen bis dahin die
   Reihenfolge des Endpunkts – also die des Verzeichnis-Durchlaufs. Bei
   ueber zwanzig Eintraegen sucht man einen bestimmten Skill damit Zeile
   fuer Zeile ab.

   ZWEI FEINHEITEN, die dieser Test festhaelt:
   1. Sortiert wird mit `localeCompare`, nicht mit `<`. Ein reiner
      Codepoint-Vergleich stellt Grossbuchstaben vor Kleinbuchstaben und
      Umlaute hinter das ganze Alphabet – „Übersetzer" landete dann
      hinter „Zeitplan".
   2. Sortiert wird eine KOPIE. Wuerde `this.skills` selbst sortiert,
      haenge daran der Kategorie- und Suchfilter samt Neuzeichnen.

   Der Test fuehrt skills.js WIRKLICH aus (jsdom gegen die echte
   settings.html), statt den Quelltext zu lesen: geprueft wird die
   Reihenfolge im DOM.

   Aufruf: node tests/test_skills_sortierung_ui.js
   ═══════════════════════════════════════════════════════════════════ */
const fs = require('fs');
const path = require('path');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) {
    try { ({ JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom')); }
    catch (e2) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }
}

const ROOT = path.dirname(__dirname);
let ok = 0, fail = 0;
function pruefe(b, t, d) {
    if (b) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + t); }
    else   { fail++; console.log('  \x1b[31m✗\x1b[0m ' + t + (d !== undefined ? '  →  ' + d : '')); }
}
function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

// Bewusst UNSORTIERT und mit den Faellen, an denen ein naiver Vergleich
// scheitert: Klein-/Grossschreibung, Umlaut, Zahl.
const SKILLS = [
    { name: 'Zeitplan',    dir_name: 'cron',     installed: true,  enabled: true,  category: 'system' },
    { name: 'avatar',      dir_name: 'avatar',   installed: true,  enabled: false, category: 'system' },
    { name: 'Übersetzer',  dir_name: 'trans',    installed: true,  enabled: true,  category: 'system' },
    { name: 'Browser',     dir_name: 'browser',  installed: true,  enabled: true,  category: 'system' },
    { name: 'Skill 10',    dir_name: 'zehn',     installed: false, enabled: false, category: 'system' },
    { name: 'Skill 2',     dir_name: 'zwei',     installed: false, enabled: false, category: 'system' },
    { name: 'ärger',       dir_name: 'aerger',   installed: false, enabled: false, category: 'sonstige' },
    { name: 'Wetter',      dir_name: 'wetter',   installed: false, enabled: false, category: 'sonstige' },
];

const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const dom  = new JSDOM(html, { url: 'https://localhost/settings' });
const w = dom.window, d = w.document;
global.window = w; global.document = d; global.localStorage = w.localStorage;
w.localStorage.setItem('jarvis_token', 'testtoken');
w.t = (k) => k;
w._lang = 'de';
// fetch muss GLOBAL gesetzt sein: skills.js ruft das nackte `fetch`, das ohne
// runScripts im Node-Kontext aufgeloest wird - sonst liefe der Test gegen das
// echte Netz und schluckte den Fehler im catch.
global.fetch = w.fetch = async (u) => ({
    ok: true, status: 200,
    json: async () => (String(u).includes('/api/skills') ? { skills: SKILLS } : {}),
});

for (const f of ['frontend/js/icons.js', 'frontend/js/skills.js']) {
    const p = path.join(ROOT, f);
    if (fs.existsSync(p)) w.eval(fs.readFileSync(p, 'utf8'));
    // icons.js legt window.JarvisIcons an, skills.js ruft den nackten Namen.
    // Ohne diese Zeile stirbt das Rendern mit ReferenceError - und zwar im
    // catch von loadSkills(), also lautlos mit leeren Listen.
    if (w.JarvisIcons) global.JarvisIcons = w.JarvisIcons;
}

function namen(listId) {
    return [...d.querySelectorAll('#' + listId + ' .sk-item-name')].map(e => e.textContent.trim());
}

(async () => {
    abschnitt('1 · Grundlage');
    pruefe(typeof w.JarvisSkillManager === 'function', 'skills.js hat den Manager bereitgestellt');
    const mgr = new w.JarvisSkillManager();
    await mgr.loadSkills();
    await new Promise(r => setTimeout(r, 60));

    const inst = namen('sk-installed-list');
    const avail = namen('sk-available-list');
    pruefe(inst.length === 4, `4 installierte gerendert (ist: ${inst.length})`);
    pruefe(avail.length === 4, `4 moegliche gerendert (ist: ${avail.length})`);

    abschnitt('2 · „Installierte Skills" alphabetisch');
    pruefe(inst.join(', ') === 'avatar, Browser, Übersetzer, Zeitplan',
        'Reihenfolge: avatar, Browser, Übersetzer, Zeitplan', inst.join(', '));
    // Die beiden Einzelnachweise, damit bei einem Fehlschlag klar ist, WELCHE
    // der zwei Fallen zugeschnappt ist.
    pruefe(inst.indexOf('avatar') < inst.indexOf('Browser'),
        'Kleinschreibung wirft nicht nach hinten (avatar vor Browser)');
    pruefe(inst.indexOf('Übersetzer') < inst.indexOf('Zeitplan'),
        'Umlaut steht bei U, nicht hinter Z (Übersetzer vor Zeitplan)');

    abschnitt('3 · „Mögliche Skills" alphabetisch');
    pruefe(avail.join(', ') === 'ärger, Skill 2, Skill 10, Wetter',
        'Reihenfolge: ärger, Skill 2, Skill 10, Wetter', avail.join(', '));
    pruefe(avail.indexOf('Skill 2') < avail.indexOf('Skill 10'),
        'Zahlen natuerlich sortiert (Skill 2 vor Skill 10)');

    abschnitt('4 · Sortiert wird die ANZEIGE, nicht der Datenbestand');
    pruefe(mgr.skills.map(s => s.name).join(',') === SKILLS.map(s => s.name).join(','),
        'this.skills hat seine urspruengliche Reihenfolge behalten',
        mgr.skills.map(s => s.name).join(','));

    abschnitt('5 · Auch gefiltert bleibt es sortiert');
    // Der Suchfilter baut die Liste neu auf – ein Sortieren nur im Erstlauf
    // waere nach der ersten Eingabe wieder weg.
    mgr.searchVal = 's';
    mgr._renderAvailable();
    const gefiltert = namen('sk-available-list');
    pruefe(gefiltert.length >= 2, `Suche liefert Treffer (${gefiltert.length})`);
    pruefe(gefiltert.join(',') === gefiltert.slice().sort(
        (a, b) => a.localeCompare(b, 'de', { sensitivity: 'base', numeric: true })).join(','),
        'gefilterte Liste ist ebenfalls sortiert', gefiltert.join(', '));

    console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
    w.close();
    process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ABBRUCH: ' + e.message); process.exit(2); });
