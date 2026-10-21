/* UI-Waechter: /wissen -> Wissensgruppen -> Klick auf einen Gruppennamen.
 *
 * GEMELDET 2026-10-21: die Datensaetze einer Gruppe erschienen am ENDE der
 * Gruppenliste statt direkt unter dem angeklickten Namen. Ursache: es gibt EIN
 * #kb-groups-files, und das stand fest hinter #kb-groups-overview. Jetzt wandert
 * der Kasten unter die Zeile, deren Dateien er zeigt (knowledge.js
 * ::_placeGroupFiles), ein zweiter Klick klappt ihn zu.
 *
 * Gemessen wird am ECHTEN Renderer gegen die ECHTE wissen.html; geklickt wird
 * wirklich. Ob der Kasten UNTER der Zeile steht, ist eine DOM-Frage
 * (previousElementSibling), keine Layoutfrage – jsdom reicht dafuer.
 *
 * Lauf:  timeout 120 node tests/test_gruppe_dateien_platz_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

let BILANZ = false;
const WACHHUND = setTimeout(() => {
    console.log('❌ ABBRUCH: Lauf haengt (Wachhund nach 60 s)');
    process.exit(1);
}, 60000);
process.on('exit', (c) => {
    if (!BILANZ && c === 0) {
        console.log('❌ ABBRUCH: keine Bilanzzeile – der Lauf ist nicht durchgelaufen');
        process.exitCode = 1;
    }
});

function antwort(data, status) {
    const body = JSON.stringify(data);
    return Promise.resolve({
        ok: (status || 200) < 400, status: status || 200,
        clone() { return this; },
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(body),
    });
}

(async () => {

const html = fs.readFileSync(path.join(ROOT, 'frontend', 'wissen.html'), 'utf8');
const dom = new JSDOM(html, {
    url: 'https://localhost/wissen',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    virtualConsole: new VirtualConsole(),
});
const w = dom.window, dc = w.document;
w.localStorage.setItem('jarvis_token', 'testtoken');
w.confirm = () => true;

// Drei Gruppen: der gemeldete Fall braucht eine Gruppe, die NICHT die letzte ist –
// bei der letzten stuende der Kasten auch im Altstand zufaellig richtig.
let GRUPPEN = [
    { id: 'g1', name: 'Vertrieb', color: '#3b82f6', order: 0, count: 2, folders: [] },
    { id: 'g2', name: 'Technik', color: '#22c55e', order: 1, count: 1, folders: [] },
    { id: 'g3', name: 'Support', color: '#a855f7', order: 2, count: 1, folders: [] },
];
const ZUORDNUNG = {
    'data/rag/a/eins.pdf': ['g1'],
    'data/rag/a/zwei.docx': ['g1', 'g2'],
    'data/rag/b/drei.md': ['g3'],
};
const attrappe = (url, o) => {
    const pfad = String(url).split('?')[0];
    const methode = ((o && o.method) || 'GET').toUpperCase();
    if (pfad === '/api/knowledge/groups' && methode === 'GET') {
        return antwort({ ok: true, groups: JSON.parse(JSON.stringify(GRUPPEN)), ungrouped_count: 1 });
    }
    if (pfad === '/api/knowledge/assignments') return antwort({ ok: true, assignments: ZUORDNUNG });
    if (pfad === '/api/knowledge/groups/ungrouped') return antwort({ ok: true, files: ['data/rag/c/frei.txt'] });
    return antwort({ ok: true });
};
w.fetch = attrappe;
global.fetch = attrappe;

for (const f of ['sitzung.js', 'icons.js', 'i18n.js', 'kbgroups.js', 'knowledge.js']) {
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js', f), 'utf8'));
}
const km = w.knowledgeManager;
if (!km || !w.KbGroups || !w.JarvisIcons) {
    console.log('ABBRUCH: Module nicht geladen'); process.exit(2);
}
await w.KbGroups.load();
km._renderGroupsOverview();

const box = () => dc.getElementById('kb-groups-files');
// Nie ungeprueft dereferenzieren: fehlt der Kasten (Neuaufbau hat ihn geloescht),
// muessen die Pruefungen FEHLSCHLAGEN statt den Lauf ohne Bilanz abzubrechen.
const kasten = () => box() || dc.createElement('div');
const zeile = (gid) => [...dc.querySelectorAll('#kb-groups-overview .kb-grp-manage-row[data-gid]')]
    .find((r) => r.dataset.gid === gid) || null;
const name = (gid) => { const r = zeile(gid); return r ? r.querySelector('.kb-grp-manage-name') : null; };
const sichtbar = () => !!box() && box().style.display !== 'none';
const unter = (row) => !!row && !!box() && box().previousElementSibling === row;
const klick = async (el) => { if (el) el.click(); await sleep(30); };

section('0. Positivkontrolle');
const zeilen = dc.querySelectorAll('#kb-groups-overview .kb-grp-manage-row[data-gid]');
check('drei Gruppenzeilen gerendert', zeilen.length === 3, String(zeilen.length));
check('Zeile "ungruppiert" gerendert', !!dc.querySelector('#kb-groups-overview .kb-grp-row-ung'));
check('Dateikasten existiert genau einmal und ist zu',
      dc.querySelectorAll('#kb-groups-files').length === 1 && !sichtbar());
if (zeilen.length !== 3 || !box()) { console.log('ABBRUCH: Aufbau unvollstaendig'); process.exit(2); }

section('1. Klick auf die ERSTE Gruppe: Kasten direkt darunter (der gemeldete Fall)');
await klick(name('g1'));
check('Kasten ist sichtbar', sichtbar());
check('⚠ Kasten steht direkt unter "Vertrieb"', unter(zeile('g1')),
      kasten().previousElementSibling && (kasten().previousElementSibling.className + ' ' + (kasten().previousElementSibling.dataset.gid || '')));
check('… und NICHT hinter der letzten Zeile der Liste', !unter(dc.querySelector('#kb-groups-overview .kb-grp-row-ung')));
check('Kasten zeigt die zwei Dateien der Gruppe', kasten().querySelectorAll('.kb-grp-file-row').length === 2,
      String(kasten().querySelectorAll('.kb-grp-file-row').length));
check('die naechste Gruppenzeile folgt NACH dem Kasten', kasten().nextElementSibling === zeile('g2'));

section('2. Zweiter Klick auf denselben Namen klappt zu');
await klick(name('g1'));
check('Kasten ist zu', !sichtbar());

section('3. Wechsel auf eine andere Gruppe – der Kasten wandert mit');
await klick(name('g2'));
check('Kasten unter "Technik"', sichtbar() && unter(zeile('g2')));
await klick(name('g3'));
check('Kasten unter "Support"', sichtbar() && unter(zeile('g3')));
check('weiterhin genau EIN Kasten', dc.querySelectorAll('#kb-groups-files').length === 1);
check('Kasten zeigt die Datei von "Support"', kasten().textContent.includes('drei.md'));

section('4. Neuaufbau der Liste (Farbe, Umbenennen, Zuordnung) behaelt den Platz');
await km._refreshGroups();
await sleep(20);
check('Kasten ueberlebt den Neuaufbau', !!box() && dc.querySelectorAll('#kb-groups-files').length === 1);
check('… sichtbar und wieder unter "Support"', sichtbar() && unter(zeile('g3')));

section('5. Ziehen zum Sortieren trennt den Kasten nicht von seiner Zeile');
const ziehe = (row, typ) => {
    const ev = new w.Event(typ, { bubbles: true });
    ev.dataTransfer = { setData() {}, effectAllowed: '', dropEffect: '' };
    row.dispatchEvent(ev);
};
await klick(name('g1'));
ziehe(zeile('g2'), 'dragstart');
check('waehrend des Ziehens ist der Kasten weg', !sichtbar());
ziehe(zeile('g2'), 'dragend');
await sleep(20);
check('nach dem Ziehen wieder sichtbar unter "Vertrieb"', sichtbar() && unter(zeile('g1')));

section('6. "ungruppiert" bekommt den Kasten ebenfalls direkt darunter');
const ung = dc.querySelector('#kb-groups-overview .kb-grp-row-ung');
await klick(ung.querySelector('.kb-grp-manage-name'));
check('Kasten unter "ungruppiert"', sichtbar() && unter(ung));
check('… mit der ungruppierten Datei', kasten().textContent.includes('frei.txt'));
await klick(dc.querySelector('#kb-groups-overview .kb-grp-row-ung .kb-grp-manage-name'));
check('zweiter Klick klappt zu', !sichtbar());

section('7. Verschwindet die Gruppe, schliesst der Kasten statt am Listenende zu stehen');
await klick(name('g3'));
check('Positivkontrolle: Kasten offen unter "Support"', sichtbar() && unter(zeile('g3')));
GRUPPEN = GRUPPEN.filter((g) => g.id !== 'g3');
await km._refreshGroups();
await sleep(20);
check('Kasten ist zu', !sichtbar());
check('… und wieder an seinem Heimatplatz hinter der Uebersicht',
      kasten().previousElementSibling === dc.getElementById('kb-groups-overview'));

section('8. Gestaltung der eingerueckten Lage existiert (Regel, kein Layout)');
const css = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');
const regel = /\.kb-grp-manage-list\s*>\s*\.kb-groups-files\s*\{([^}]*)\}/.exec(css);
check('Regel fuer den Kasten IN der Liste vorhanden', !!regel);
check('… mit Theme-Farbe statt fester Farbe', !!regel && /var\(--accent-rgb\)/.test(regel[1]) && !/#[0-9a-f]{3,6}/i.test(regel[1]));

const ok = results.filter((r) => r.ok).length;
const fail = results.length - ok;
BILANZ = true;
console.log(`\nErgebnis: ${ok} ok, ${fail} fehlgeschlagen`);
clearTimeout(WACHHUND);
w.close();
process.exit(fail ? 1 : 0);

})().catch((e) => {
    console.log('❌ ABBRUCH: ' + (e && e.stack || e));
    process.exit(1);
});
