/* Waechter: Kaestchen "nicht zugeordnet" in der Wissensgruppen-Tabelle (/wissen).
 *
 * Gemessen wird die WIRKUNG mit dem ECHTEN kbmatrix.js, dem ECHTEN icons.js und
 * dem ECHTEN i18n.js: die Tabelle wird ueber den echten Weg (KbMatrix.open()) an
 * einer fetch-Attrappe aufgebaut, das Kaestchen wird GEKLICKT und die Sichtbarkeit
 * der Zeilen gemessen. Ob eine Zeile ausgeblendet WIRD und was der Zaehler sagt,
 * kann eine Quelltext-Suche nicht beantworten.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try {
    ({ JSDOM } = require('jsdom'));
} catch (e) {
    for (const d of [path.join(ROOT, 'node_modules'), path.join(ROOT, 'data', 'node_modules'),
                     '/tmp/node_modules', '/usr/share/nodejs', '/usr/lib/node_modules',
                     process.env.JSDOM_PATH || '']) {
        if (!d) continue;
        try { ({ JSDOM } = require(path.join(d, 'jsdom'))); break; } catch (e2) { /* weiter */ }
    }
}
if (!JSDOM) {
    // "konnte nicht laufen" darf nie wie "bestanden" aussehen.
    console.log('\x1b[31mABBRUCH\x1b[0m: jsdom nicht gefunden (JSDOM_PATH=... setzen)');
    process.exit(2);
}

let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function sicher(fn) { try { return fn(); } catch (e) { return 'WURF: ' + e.message; } }

const wachhund = setTimeout(() => {
    console.log('  \x1b[31m✗\x1b[0m Wachhund: Lauf haengt (25 s)');
    fail++; bilanz(); process.exit(1);
}, 25000);

let _bilanzGedruckt = false;
function bilanz() {
    _bilanzGedruckt = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
}
/* ⚠ Ein Lauf ohne Bilanzzeile ist von "nicht gelaufen" nicht zu unterscheiden -
 * und mit Exit 0 sieht er wie ein bestandener aus. */
process.on('exit', function (code) {
    if (!_bilanzGedruckt) {
        console.log('\n\x1b[31mABBRUCH ohne Bilanz\x1b[0m – ' + ok + ' OK, ' + fail + ' FAIL bis zum Abbruch');
        if (code === 0) process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('  \x1b[31m✗\x1b[0m unbehandelte Zurueckweisung: ' + (e && e.message));
    fail++; bilanz(); process.exit(1);
});

const MATRIXJS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'kbmatrix.js'), 'utf8');
const ICONSJS  = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8');
const I18NJS   = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'i18n.js'), 'utf8');
const CSS      = fs.readFileSync(path.join(ROOT, 'frontend', 'css', 'style.css'), 'utf8');

/* Kommentare aus CSS entfernen - sonst liest der Waechter seine eigene
 * Begruendung (im Projekt vielfach bezahlt). */
function cssOhneKommentar(s) { return s.replace(/\/\*[\s\S]*?\*\//g, ' '); }
const CSS_REIN = cssOhneKommentar(CSS);
check.positivCss = CSS.includes('margin-left: auto') && CSS_REIN.includes('margin-left: auto');

/* Eine CSS-Regel herausschneiden (kommentarfrei). */
function regel(sel) {
    const i = CSS_REIN.indexOf(sel + ' {');
    if (i < 0) return '';
    const j = CSS_REIN.indexOf('}', i);
    return j < 0 ? '' : CSS_REIN.slice(i, j + 1);
}

// ── Testbestand ─────────────────────────────────────────────────────────────
// 4 Dateien: zwei ohne Gruppe, zwei mit. Damit ist "nur ungruppierte" eine
// echte Teilmenge - bei 0 oder allen waere jede Messung trivial wahr.
const DATEIEN = [{
    folder: 'data/rag/doku',
    files: [
        { path: 'data/rag/doku/anleitung.md', name: 'anleitung.md' },
        { path: 'data/rag/doku/preise.md',    name: 'preise.md' },
        { path: 'data/rag/doku/vertrag.pdf',  name: 'vertrag.pdf' },
        { path: 'data/rag/doku/notiz.txt',    name: 'notiz.txt' },
    ],
}];
const ZUORDNUNG = {
    'data/rag/doku/preise.md':   ['g1'],
    'data/rag/doku/vertrag.pdf': ['g1', 'g2'],
};
const GRUPPEN = [
    { id: 'g1', name: 'Vertrieb', color: '#3b82f6' },
    { id: 'g2', name: 'Recht',    color: '#10b981' },
];

let gesendet = [];   // Aufrufe an setAssignment

async function baueSeite() {
    const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>',
                          { url: 'https://pruef.local/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'pruef:tok');

    // fetch-Attrappe: nur die Endpunkte, die kbmatrix.open() wirklich ruft.
    const holen = async (url) => {
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/knowledge/files')   return { ok: true, json: async () => DATEIEN };
        if (pfad === '/api/knowledge/pending') return { ok: true, json: async () => [] };
        if (pfad === '/api/knowledge/content_search') return { ok: true, json: async () => ({ ok: true, files: [] }) };
        return { ok: true, json: async () => ({}) };
    };
    win.fetch = holen;
    win.confirm = () => true;
    /* ⚠ jsdom kennt CSS.escape nicht (gemessen: window.CSS ist undefined) -
     * kbmatrix.js benutzt es beim Nachziehen der Gruppen-Zaehler. Das ist eine
     * Luecke der Testumgebung, kein Codefehler: CSS.escape ist seit Jahren
     * Browser-Standard. Gestellt wird die echte Semantik, nicht ein No-op -
     * sonst prueft der Waechter eine Kette, die es so nicht gibt. */
    if (!win.CSS) win.CSS = {};
    if (!win.CSS.escape) win.CSS.escape = (s) => String(s).replace(
        /[^a-zA-Z0-9_ -￿-]/g, c => '\\' + c);

    // KbGroups stellen (das echte Modul braucht eigene Endpunkte; hier zaehlt
    // ausschliesslich, was kbmatrix.js daraus liest).
    win.KbGroups = {
        UNGROUPED: 'ungrouped',
        all: () => GRUPPEN,
        load: async () => GRUPPEN,
        getMap: async () => JSON.parse(JSON.stringify(ZUORDNUNG)),
        setAssignment: async (p, ids) => { gesendet.push({ path: p, ids: ids.slice() }); return { ok: true }; },
    };

    win.eval(ICONSJS);
    win.eval(I18NJS);
    win.eval(MATRIXJS);
    await new Promise(r => win.setTimeout(r, 0));   // applyLang() nach DOMContentLoaded
    return win;
}

function zeilen(win) {
    return Array.from(win.document.querySelectorAll('#kbm-overlay tbody tr'));
}
function sichtbare(win) {
    return zeilen(win).filter(tr => tr.style.display !== 'none').map(tr => tr.dataset.path);
}
function zaehlerText(win) {
    const el = win.document.querySelector('#kbm-overlay .kbm-count');
    return el ? el.textContent.trim() : '(kein Zaehler)';
}

(async () => {

// ── 1. Markup und Vorgabe ───────────────────────────────────────────────────
section('1. Kaestchen im Kopf, Vorgabe AN');
const win = await baueSeite();
await win.KbMatrix.open();

const ov = win.document.getElementById('kbm-overlay');
check('Tabelle ist aufgebaut', !!ov);
check('alle 4 Testzeilen sind im DOM (nichts wird geloescht, nur ausgeblendet)',
      zeilen(win).length === 4, 'Zeilen: ' + zeilen(win).length);

const kast = ov && ov.querySelector('.kbm-nogrp');
check('Kaestchen "nicht zugeordnet" ist vorhanden', !!kast);
check('es ist ein Kontrollkaestchen', kast && kast.type === 'checkbox', kast ? kast.type : '-');
check('⚠ VORGABE IST AN', !!(kast && kast.checked));
check('es liegt in der Kopfzeile (.kbm-head), nicht in der Tabelle',
      !!(kast && kast.closest('.kbm-head')));
const lbl = kast && kast.closest('label');
check('es sitzt in einem <label> (Klick auf den Text schaltet mit)', !!lbl);
check('das Label traegt einen sichtbaren Text',
      !!(lbl && lbl.textContent.trim().length > 3), lbl ? lbl.textContent.trim() : '-');
check('das Label traegt eine Erklaerung im title',
      !!(lbl && (lbl.getAttribute('title') || '').length > 10));

// ── 2. Wirkung: nur Ungruppierte ────────────────────────────────────────────
section('2. Angehakt = ausschliesslich Dateien OHNE jede Gruppe');
let s = sichtbare(win);
check('genau die zwei ungruppierten sind sichtbar',
      s.length === 2 && s.includes('data/rag/doku/anleitung.md') && s.includes('data/rag/doku/notiz.txt'),
      s.join(', '));
check('die Datei mit EINER Gruppe ist ausgeblendet', !s.includes('data/rag/doku/preise.md'));
check('die Datei mit ZWEI Gruppen ist ausgeblendet', !s.includes('data/rag/doku/vertrag.pdf'));

// ── 3. Der Zaehler luegt nicht ──────────────────────────────────────────────
section('3. Zaehler nennt BEIDE Zahlen, solange etwas ausgeblendet ist');
let z = zaehlerText(win);
check('der Zaehler nennt die gezeigte Zahl (2)', /\b2\b/.test(z), z);
check('⚠ der Zaehler nennt auch den GESAMTbestand (4)', /\b4\b/.test(z), z);

// ── 4. Haken weg = alles ────────────────────────────────────────────────────
section('4. Haken weg -> alle Dokumente');
kast.checked = false;
kast.dispatchEvent(new win.Event('change', { bubbles: true }));
s = sichtbare(win);
check('alle vier Zeilen sind sichtbar', s.length === 4, s.join(', '));
z = zaehlerText(win);
check('der Zaehler nennt dann nur noch EINE Zahl (nichts ausgeblendet)',
      z.indexOf('4') >= 0 && !/\bvon\b|\bof\b/.test(z), z);

// ── 5. Kein Doppel-Toggle ───────────────────────────────────────────────────
section('5. Im <label> wird NIE selbst umgeschaltet');
// Ein echter Klick auf das Label schaltet das Kaestchen ueber den Browser um.
// Schaltet der Handler zusaetzlich selbst, kippt es zweimal - unterm Strich gar
// nicht, und der Klick taete sichtbar nichts (im Projekt am AD-Picker bezahlt).
const vorher = kast.checked;
lbl.click();
check('ein Klick auf das Label kehrt den Zustand genau EINMAL um',
      kast.checked === !vorher, 'vorher ' + vorher + ', jetzt ' + kast.checked);
check('und die Liste folgt dem neuen Zustand',
      sichtbare(win).length === (kast.checked ? 2 : 4),
      'gezeigt: ' + sichtbare(win).length);

// Zustand fuer die naechsten Abschnitte: Kaestchen AN.
if (!kast.checked) { kast.checked = true; kast.dispatchEvent(new win.Event('change', { bubbles: true })); }
check('Positivkontrolle: Kaestchen steht fuer Abschnitt 6 wieder auf AN', kast.checked === true);

// ── 6. Text-Filter UND Kaestchen sind UND-verknuepft ────────────────────────
section('6. Suchbegriff und Kaestchen wirken ZUSAMMEN');
const feld = ov.querySelector('.kbm-filter');
feld.value = 'preise';
feld.dispatchEvent(new win.Event('input', { bubbles: true }));
s = sichtbare(win);
check('⚠ "preise" trifft eine GRUPPIERTE Datei - sie bleibt ausgeblendet',
      s.length === 0, s.join(', '));
z = zaehlerText(win);
check('der Zaehler sagt 0 von 4', /\b0\b/.test(z) && /\b4\b/.test(z), z);

feld.value = 'notiz';
feld.dispatchEvent(new win.Event('input', { bubbles: true }));
s = sichtbare(win);
check('"notiz" trifft eine UNgruppierte Datei - sie wird gezeigt',
      s.length === 1 && s[0] === 'data/rag/doku/notiz.txt', s.join(', '));

// Positivkontrolle: ohne Kaestchen findet derselbe Begriff die gruppierte Datei.
feld.value = 'preise';
feld.dispatchEvent(new win.Event('input', { bubbles: true }));
kast.checked = false;
kast.dispatchEvent(new win.Event('change', { bubbles: true }));
s = sichtbare(win);
check('Positivkontrolle: ohne Haken findet "preise" die gruppierte Datei',
      s.length === 1 && s[0] === 'data/rag/doku/preise.md', s.join(', '));

feld.value = '';
feld.dispatchEvent(new win.Event('input', { bubbles: true }));
kast.checked = true;
kast.dispatchEvent(new win.Event('change', { bubbles: true }));

// ── 7. Zuordnen zieht die Ansicht nach ──────────────────────────────────────
section('7. Eine gerade zugeordnete Zeile faellt aus der gefilterten Menge');
check('Ausgangslage: zwei ungruppierte sichtbar', sichtbare(win).length === 2);
const tr = zeilen(win).find(t => t.dataset.path === 'data/rag/doku/anleitung.md');
const zelle = tr && tr.querySelector('.kbm-gcell[data-gid="g1"]');
check('Gruppen-Zelle der ungruppierten Datei gefunden', !!zelle);
zelle.click();
await new Promise(r => win.setTimeout(r, 0));
check('die Zuordnung geht wirklich an den Server',
      gesendet.length === 1 && gesendet[0].path === 'data/rag/doku/anleitung.md'
      && gesendet[0].ids.join(',') === 'g1',
      JSON.stringify(gesendet));
s = sichtbare(win);
check('⚠ die Zeile ist danach nicht mehr "nicht zugeordnet" und verschwindet',
      !s.includes('data/rag/doku/anleitung.md'), s.join(', '));
z = zaehlerText(win);
check('der Zaehler zieht mit (1 von 4)', /\b1\b/.test(z) && /\b4\b/.test(z), z);

// ── 8. Loeschen zieht den Zaehler nach ──────────────────────────────────────
section('8. Loeschen setzt den Zaehler ueber DIESELBE Regel');
const trDel = zeilen(win).find(t => t.dataset.path === 'data/rag/doku/notiz.txt');
const del = trDel && trDel.querySelector('.kbm-del');
check('Loeschknopf der letzten sichtbaren Zeile gefunden', !!del);
del.click();
await new Promise(r => win.setTimeout(r, 0));
await new Promise(r => win.setTimeout(r, 0));
z = zaehlerText(win);
check('nach dem Loeschen: 0 gezeigt von 3 gesamt',
      /\b0\b/.test(z) && /\b3\b/.test(z), z);

// ── 9. i18n in BEIDEN Sprachen ──────────────────────────────────────────────
section('9. i18n');
for (const k of ['kbmatrix.only_ungrouped', 'kbmatrix.only_ungrouped_tip', 'kbmatrix.count_of']) {
    const treffer = (I18NJS.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
    check('Schluessel ' + k + ' steht in DE UND EN', treffer === 2, 'gefunden: ' + treffer);
}
check('count_of traegt BEIDE Platzhalter',
      /'kbmatrix\.count_of'\s*:\s*'[^']*\{n\}[^']*\{m\}[^']*'/.test(I18NJS));

// ── 10. CSS ─────────────────────────────────────────────────────────────────
section('10. CSS');
check('Positivkontrolle: der Kommentar-Filter hat den Code nicht zerlegt', check.positivCss === true);
const rLbl = regel('.kbm-nogrp-lbl');
check('.kbm-nogrp-lbl ist definiert', rLbl.length > 0);
check('das Label schiebt sich selbst nach rechts (margin-left: auto)',
      /margin-left:\s*auto/.test(rLbl), rLbl);
check('⚠ und nimmt dem Filterfeld sein auto (sonst stehen beide weit auseinander)',
      /\.kbm-nogrp-lbl\s*\+\s*\.kbm-filter\s*\{[^}]*margin-left:\s*0/.test(CSS_REIN));
check('Beschriftung und Kaestchen brechen nicht um (nowrap)',
      /white-space:\s*nowrap/.test(rLbl));
check('der Zaehler steht NICHT auf --text-muted (er traegt jetzt eine Zahl, die man liest)',
      !/color:\s*var\(--text-muted/.test(regel('.kbm-count')), regel('.kbm-count'));

// ── 11. EINE Filterregel ────────────────────────────────────────────────────
section('11. Regel: es gibt nur EINE Filterfassung');
// Zwei Fassungen liefen beim naechsten Feinschliff auseinander - dann gilt fuer
// den Text-Filter etwas anderes als fuer das Kaestchen.
// ⚠ Gemeint ist die SICHTBARKEIT DER ZEILEN - ein Muster auf ".style.display"
// zaehlt auch die Inhalts-Vorschau mit (tip.style.display) und meldet einen
// Fehler, den es nicht gibt.
const zuweis = (MATRIXJS.match(/\btr\.style\.display\s*=/g) || []).length;
check('tr.style.display wird an genau EINER Stelle gesetzt', zuweis === 1, 'Stellen: ' + zuweis);
check('die alte, getrennte applyFilter-Fassung ist weg', !/const\s+applyFilter\s*=/.test(MATRIXJS));
check('der Zaehler wird nirgends von Hand gesetzt (nur ueber _zaehlerSetzen)',
      (MATRIXJS.match(/\.kbm-count'\)/g) || []).length === 1);

clearTimeout(wachhund);
win.close();
bilanz();
process.exit(fail ? 1 : 0);

})().catch(e => {
    console.log('  \x1b[31m✗\x1b[0m ABBRUCH: ' + (e && e.stack || e));
    fail++; bilanz(); process.exit(1);
});
