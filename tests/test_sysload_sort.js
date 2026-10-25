#!/usr/bin/env node
/**
 * /portal → Systemauslastung: die Spalten der Prozesstabelle sind sortierbar
 * (Wunsch des Betreibers 2026-09-28).
 *
 * GEMESSEN WIRD AM ECHTEN MODUL: `sysload.js` wird geladen, der Kasten ueber
 * die oeffentliche Schnittstelle geoeffnet, `/api/system/load` liefert eine
 * Attrappe in der ECHTEN Antwortform (Felder aus backend/system_load.py). Dann
 * wird auf die Kopfzellen GEKLICKT und die Zeilenfolge im DOM abgelesen.
 *
 * DIE EIGENTLICHE FALLE ist das Neuzeichnen: die Tabelle entsteht bei jedem
 * Takt (3 s) neu. Eine Sortierung, die im DOM lebt, oder ein Zuhoerer an der
 * Kopfzelle waere nach dem ersten Takt weg – deshalb wird nach jedem Klick
 * NEU GEZEICHNET (Sprachwechsel-Ereignis, derselbe `zeichnen()`-Weg) und
 * erneut gemessen.
 *
 *   node tests/test_sysload_sort.js
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => { if (b) { ok++; console.log('  ✓ ' + t); }
                              else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); } };
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
process.on('unhandledRejection', e => { fail++; console.log('  ✗ unbehandelte Zurueckweisung: ' + (e && e.message)); });
let _bilanz = false;
process.on('exit', (c) => { if (!_bilanz && c === 0) {
    console.log('  ✗ ABBRUCH: keine Bilanzzeile – der Lauf ist vorzeitig beendet'); process.exitCode = 1; } });
setTimeout(() => { console.log('  ✗ ABBRUCH: der Lauf haengt (kein Ergebnis nach 30 s)'); process.exit(1); }, 30000);

const { JSDOM } = require('./lib/jsdom_laden')();

const SRC = fs.readFileSync(path.join(ROOT, 'frontend/js/sysload.js'), 'utf8');

// Antwortform wie backend/system_load.py (Serverfolge: CPU absteigend).
const PROZESSE = [
    { pid: 900, name: 'python3', user: 'jarvis', cpu: 88.5, rss: 300e6, threads: 12, cmd: 'python3 run' },
    { pid: 12,  name: 'Xvfb',    user: 'root',   cpu: 7.3,  rss: 900e6, threads: 3,  cmd: 'Xvfb :1' },
    { pid: 4711, name: 'node',   user: 'jarvis', cpu: 7.25, rss: 50e6,  threads: 40, cmd: 'node bridge' },
    { pid: 3,   name: 'kworker', user: 'root',   cpu: 7.25, rss: 0,     threads: 1,  cmd: '' },
];
const ANTWORT = {
    host: 'dev', erzeugt_am: '2026-09-28T10:00:00', fenster_s: 0.5, prozesse_gesamt: 180,
    cpu: { prozent: 30, kerne: 4, je_kern: [10, 20, 30, 40], last: [1, 1, 1] },
    speicher: { prozent: 50, belegt: 4e9, gesamt: 8e9, swap_gesamt: 0 },
    netz: { rx_rate: 1, tx_rate: 2, rx_gesamt: 3, tx_gesamt: 4 },
    platte: { io: { lesen_rate: 1, schreiben_rate: 1 }, partitionen: [] },
    prozesse: PROZESSE,
};

const warte = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
    const dom = new JSDOM('<!doctype html><body><div id="cpu-bar"></div></body>',
                          { url: 'https://h/portal', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'x');
    let abrufe = 0;
    // Node hat ein eigenes globales fetch – das Modul laeuft aber im Fenster,
    // und dort gibt es ohne Attrappe keines (Register).
    w.fetch = (url) => {
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/me') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ is_admin: true }) });
        if (pfad === '/api/system/load') {
            abrufe++;
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(ANTWORT))) });
        }
        return Promise.reject(new Error('unerwartet: ' + pfad));
    };
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle und rufen sie beim
    // LADEN auf. Jede echte Seite laedt sie davor.
    w.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    w.eval(SRC);
    await warte(50);
    if (!w.JarvisSysLoad) { console.log('ABBRUCH: Modul nicht geladen'); process.exit(2); }
    w.JarvisSysLoad.oeffnen();
    await warte(80);

    const pids = () => Array.from(w.document.querySelectorAll('.jv-load-tab tbody tr'))
        .map(tr => Number(tr.children[2].textContent));
    const raenge = () => Array.from(w.document.querySelectorAll('.jv-load-tab tbody tr'))
        .map(tr => Number(tr.children[0].textContent));
    const kopf = (sp) => w.document.querySelector('.jv-load-tab th[data-sort="' + sp + '"]');
    const klick = (sp) => { const h = kopf(sp); if (h) h.dispatchEvent(new w.MouseEvent('click', { bubbles: true })); };
    const neuZeichnen = async () => { w.dispatchEvent(new w.Event('jarvis-lang-changed')); await warte(20); };

    abschnitt('0. Positivkontrolle');
    pruefe(abrufe === 1 && pids().length === 4, 'Kasten offen, Tabelle mit 4 Zeilen gezeichnet',
        `abrufe=${abrufe} zeilen=${pids().length}`);
    if (pids().length !== 4) { console.log('ABBRUCH: keine Tabelle – Messung ohne Aussage'); process.exit(2); }

    abschnitt('1. Vorgabe = Serverfolge (CPU absteigend)');
    pruefe(JSON.stringify(pids()) === '[900,12,4711,3]', 'Zeilen in Serverfolge', JSON.stringify(pids()));
    const alle = ['rang', 'name', 'pid', 'user', 'cpu', 'rss', 'threads'];
    pruefe(alle.every(sp => kopf(sp)), 'jede der 7 Spalten hat einen sortierbaren Kopf',
        alle.filter(sp => !kopf(sp)).join(','));
    pruefe(alle.every(sp => kopf(sp) && kopf(sp).getAttribute('tabindex') === '0'),
        'jeder Kopf ist per Tastatur erreichbar');
    pruefe(kopf('cpu').getAttribute('aria-sort') === 'descending' && kopf('pid').getAttribute('aria-sort') === 'none',
        'aria-sort zeigt die aktive Spalte');

    abschnitt('2. Klicken sortiert – und das Neuzeichnen haelt es fest');
    klick('rss');
    pruefe(JSON.stringify(pids()) === '[12,900,4711,3]', 'Speicher: erster Klick absteigend', JSON.stringify(pids()));
    await neuZeichnen();
    pruefe(JSON.stringify(pids()) === '[12,900,4711,3]', '⚠ nach dem Neuzeichnen bleibt die Sortierung', JSON.stringify(pids()));
    pruefe(kopf('rss') && /▾/.test(kopf('rss').textContent), 'der Pfeil steht an der aktiven Spalte');
    klick('rss');
    pruefe(JSON.stringify(pids()) === '[3,4711,900,12]', 'zweiter Klick kehrt die Reihenfolge um', JSON.stringify(pids()));
    pruefe(JSON.stringify(raenge()) === '[4,3,1,2]', '# bleibt der CPU-Rang (wandert mit der Zeile)', JSON.stringify(raenge()));

    klick('name');
    pruefe(JSON.stringify(pids()) === '[3,4711,900,12]', 'Prozess: erster Klick alphabetisch aufsteigend (kworker, node, python3, Xvfb)',
        JSON.stringify(pids()));
    klick('pid');
    pruefe(JSON.stringify(pids()) === '[4711,900,12,3]', 'PID: numerisch, nicht als Text', JSON.stringify(pids()));
    klick('threads');
    pruefe(JSON.stringify(pids()) === '[4711,900,12,3]', 'Threads absteigend', JSON.stringify(pids()));
    klick('user');
    pruefe(JSON.stringify(pids()) === '[900,4711,12,3]', 'Benutzer aufsteigend, Gleichstand nach CPU-Rang', JSON.stringify(pids()));
    klick('cpu');
    pruefe(JSON.stringify(pids()) === '[900,12,4711,3]', 'CPU: numerisch (7,3 vor 7,25), Gleichstand bleibt in CPU-Rang-Folge', JSON.stringify(pids()));
    klick('rang'); klick('rang');
    pruefe(JSON.stringify(pids()) === '[3,4711,12,900]', '#: zweiter Klick = umgekehrte CPU-Folge', JSON.stringify(pids()));

    abschnitt('3. Tastatur: Enter sortiert, Fokus ueberlebt das Neuzeichnen');
    const h = kopf('threads');
    h.focus();
    h.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    pruefe(JSON.stringify(pids()) === '[4711,900,12,3]', 'Enter auf dem Kopf sortiert', JSON.stringify(pids()));
    await neuZeichnen();
    const f = w.document.activeElement;
    pruefe(f && f.getAttribute && f.getAttribute('data-sort') === 'threads',
        '⚠ nach dem Neuzeichnen steht der Fokus wieder auf demselben Kopf',
        f ? (f.tagName + ' ' + (f.getAttribute && f.getAttribute('data-sort'))) : 'kein Fokus');

    w.JarvisSysLoad.schliessen();
    w.close();
    console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
    _bilanz = true;
    process.exit(fail ? 1 : 0);
})();
