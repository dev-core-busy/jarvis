/* UI-Waechter: Wissensgruppen einer Netzwerk-Freigabe zuordnen.
 *
 * GEMELDET 2026-10-21: Kundenlisten auf einer SMB-Freigabe bekamen keine
 * Wissensgruppe. Das Backend ordnet seitdem neue Dateien eines Speicherordners
 * dessen Gruppen zu (tests/test_auto_gruppe.py). Damit das fuer eine Freigabe
 * ueberhaupt einstellbar ist, brauchte es drei Dinge in der Oberflaeche – und
 * zwei davon waren Bestandsfehler, die die Verknuepfung STILL wieder geloescht
 * haetten:
 *   1. ein Bedienelement an der Freigabe (die Ordnerliste blendet Freigaben aus)
 *   2. der Dialog vergleicht '/mnt/rag/share_2' mit dem Manifest-Schluessel
 *      'mnt/rag/share_2' – ohne Angleichung nie ein Haken, und Speichern
 *      schickte eine LEERE Gruppenliste
 *   3. der Gruppen-Editor bot nur die Ordner aus /api/knowledge/stats an (ohne
 *      Freigaben) und schrieb beim Speichern genau diese Liste zurueck
 *
 * Gemessen wird am ECHTEN Renderer gegen die ECHTE settings.html; der Rumpf
 * jedes Speicherns wird an einer fetch-Attrappe abgegriffen.
 *
 * Lauf:  timeout 120 node tests/test_auto_gruppe_ui.js
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

const html = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
const dom = new JSDOM(html, {
    url: 'https://localhost/settings',
    runScripts: 'outside-only',
    pretendToBeVisual: true,          // sonst fehlt requestAnimationFrame (Dialoge)
    virtualConsole: new VirtualConsole(),
});
const w = dom.window, dc = w.document;
w.localStorage.setItem('jarvis_token', 'testtoken');
w.confirm = () => true;

const GRUPPEN = [
    { id: 'vertrieb', name: 'Vertrieb', color: '#3b82f6', order: 0,
      folders: ['data/rag/vertrieb', 'mnt/rag/share_2'] },
    { id: 'ibs', name: 'IBS', color: '#a855f7', order: 1, folders: ['data/rag/ibs'] },
    // Unterordner als Speicherordner (2026-10-21) – die Wurzel gehoert IBS.
    { id: 'reha', name: 'REHA', color: '#22c55e', order: 2, folders: ['data/rag/ibs/reha'] },
];
const gesendet = [];
const attrappe = (url, o) => {
    const pfad = String(url).split('?')[0];
    const methode = ((o && o.method) || 'GET').toUpperCase();
    const rumpf = o && o.body ? JSON.parse(o.body) : null;
    gesendet.push({ pfad, methode, rumpf });
    if (pfad === '/api/knowledge/groups' && methode === 'GET') {
        return antwort({ ok: true, groups: JSON.parse(JSON.stringify(GRUPPEN)), ungrouped_count: 0 });
    }
    if (pfad === '/api/knowledge/stats') {
        // Wie im echten Endpunkt: Freigaben sind aus der Ordnerliste gefiltert.
        return antwort({ folders: [{ path: 'data/rag/vertrieb', exists: true, display: 'vertrieb' },
                                   { path: 'data/rag/ibs', exists: true, display: 'ibs' }] });
    }
    if (pfad.startsWith('/api/knowledge/groups/')) return antwort({ ok: true, group: {} });
    if (pfad === '/api/knowledge/folders/groups') return antwort({ ok: true, zugeordnet: 0 });
    return antwort({ ok: true });
};
w.fetch = attrappe;
global.fetch = attrappe;

for (const f of ['sitzung.js', 'icons.js', 'i18n.js', 'kbgroups.js', 'knowledge.js']) {
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js', f), 'utf8'));
}
const km = w.knowledgeManager;
const T = (k) => w.t(k);
if (!km || !w.KbGroups || !w.JarvisIcons) {
    console.log('ABBRUCH: Module nicht geladen'); process.exit(2);
}
check('Positivkontrolle: i18n liefert den neuen deutschen Text',
      T('knowledge.share_groups_title') === 'Wissensgruppen zuordnen', T('knowledge.share_groups_title'));

section('1. Die Freigabe-Zeile traegt einen Knopf fuer die Wissensgruppen');
km._renderMounts([{ type: 'smb', source: '//srv/Kundenlisten', active: true, unknown: false,
                    mountpoint: '/mnt/rag/share_2', username: '', has_password: false }]);
const knopf = dc.querySelector('#kb-mount-list [data-kb-aktion="editFolder"]');
check('Knopf vorhanden', !!knopf);
check('… adressiert den Einhaengepunkt der Freigabe',
      !!knopf && knopf.getAttribute('data-kb-pfad') === '/mnt/rag/share_2',
      knopf && knopf.getAttribute('data-kb-pfad'));
check('… mit dem Etikett-Symbol (nicht dem Stift der Verbindungsdaten)',
      !!knopf && !!knopf.querySelector('.jv-ico-tag') && !knopf.querySelector('.jv-ico-pencil'));
check('… und beschriftet', !!knopf && knopf.getAttribute('title') === T('knowledge.share_groups_title'));
if (knopf) knopf.click();
await sleep(30);
check('Klick oeffnet den Gruppen-Dialog', !!dc.getElementById('kbfld-edit-modal'));

section('2. Der Dialog erkennt die bestehende Verknuepfung einer Freigabe');
await km.editFolder('/mnt/rag/share_2');
await sleep(10);
let modal = dc.getElementById('kbfld-edit-modal');
const haken = (id) => { const c = modal && modal.querySelector('.kbfld-grp[value="' + id + '"]'); return c ? c.checked : null; };
check('⚠ Vertrieb ist angehakt (Manifest speichert ohne fuehrenden Schraegstrich)', haken('vertrieb') === true, String(haken('vertrieb')));
check('IBS ist nicht angehakt', haken('ibs') === false, String(haken('ibs')));
check('Beschriftung nennt die Freigabe, nicht das /wissen-Upload-Ziel',
      !!modal && modal.textContent.includes(T('knowledge.share_groups_label')));
check('Hinweis sagt, dass neue Dateien automatisch zugeordnet werden',
      !!modal && modal.textContent.includes(T('knowledge.share_groups_hint')));
check('kein Umbenennen-Feld bei einer Freigabe', !!modal && !modal.querySelector('#kbfld-name'));

gesendet.length = 0;
modal.querySelector('#kbfld-save').click();
await sleep(50);
const post = gesendet.find((g) => g.pfad === '/api/knowledge/folders/groups');
check('⚠ unveraendert speichern schickt Vertrieb mit (nicht die leere Liste)',
      !!post && JSON.stringify(post.rumpf.groups) === '["vertrieb"]', post && JSON.stringify(post.rumpf));
check('… fuer den Einhaengepunkt', !!post && post.rumpf.path === '/mnt/rag/share_2');

section('3. Gewoehnliche Ordner bleiben, wie sie waren');
await km.editFolder('data/rag/ibs');
await sleep(10);
modal = dc.getElementById('kbfld-edit-modal');
check('data/rag/ibs: IBS angehakt', haken('ibs') === true);
check('… Vertrieb nicht', haken('vertrieb') === false);
check('… mit dem bisherigen Speicherordner-Titel',
      !!modal && modal.textContent.includes(T('kbgroups.folders_label')));
modal.remove();

section('4. Der Gruppen-Editor nimmt die Freigabe nicht still heraus');
await w.KbGroups.load();
await km._editGroupPermissions('vertrieb');
await sleep(20);
let pm = dc.getElementById('kbgrp-perm-modal');
check('Positivkontrolle: Editor offen, Wurzelordner angehakt',
      !!pm && !!pm.querySelector('.kbgrp-perm-folder[value="data/rag/vertrieb"]:checked'));
// Seit 2026-10-21 zeigt der Dialog ALLE Speicherordner der Gruppe – vorher war
// die Freigabe (und ein Unterordner) zugeordnet, aber unsichtbar.
check('die Freigabe steht angehakt in der Auswahl',
      !!pm.querySelector('.kbgrp-perm-folder[value="mnt/rag/share_2"]:checked'));
gesendet.length = 0;
pm.querySelector('#kbgrp-perm-save').click();
await sleep(50);
let patch = gesendet.find((g) => g.methode === 'PATCH');
check('⚠ ohne Aenderung wird KEINE Ordnerliste gesendet',
      !!patch && !('folders' in patch.rumpf), patch && JSON.stringify(patch.rumpf));

await km._editGroupPermissions('vertrieb');
await sleep(20);
pm = dc.getElementById('kbgrp-perm-modal');
const cb = pm && pm.querySelector('.kbgrp-perm-folder[value="data/rag/vertrieb"]');
if (cb) cb.checked = false;
gesendet.length = 0;
pm.querySelector('#kbgrp-perm-save').click();
await sleep(50);
patch = gesendet.find((g) => g.methode === 'PATCH');
check('⚠ abgewaehlter Ordner geht raus, die Freigabe bleibt drin',
      !!patch && JSON.stringify(patch.rumpf.folders) === '["mnt/rag/share_2"]',
      patch && JSON.stringify(patch.rumpf));

section('5. Ein Unterordner als Speicherordner ist im Gruppen-Editor sichtbar');
await km._editGroupPermissions('reha');
await sleep(20);
pm = dc.getElementById('kbgrp-perm-modal');
const werte = pm ? [...pm.querySelectorAll('.kbgrp-perm-folder')].map((c) => c.value) : [];
check('Positivkontrolle: Editor offen, beide Wurzeln angeboten',
      werte.includes('data/rag/vertrieb') && werte.includes('data/rag/ibs'), JSON.stringify(werte));
check('Unterordner steht angehakt in der Auswahl',
      !!pm.querySelector('.kbgrp-perm-folder[value="data/rag/ibs/reha"]:checked'), JSON.stringify(werte));
check('… direkt unter seinem Wurzelordner',
      werte.indexOf('data/rag/ibs/reha') === werte.indexOf('data/rag/ibs') + 1, JSON.stringify(werte));
check('… nur einmal', werte.filter((v) => v === 'data/rag/ibs/reha').length === 1);
gesendet.length = 0;
pm.querySelector('#kbgrp-perm-save').click();
await sleep(50);
patch = gesendet.find((g) => g.methode === 'PATCH');
check('ohne Aenderung keine Ordnerliste', !!patch && !('folders' in patch.rumpf),
      patch && JSON.stringify(patch.rumpf));
await km._editGroupPermissions('reha');
await sleep(20);
pm = dc.getElementById('kbgrp-perm-modal');
// Kein `.checked` auf ein womoeglich fehlendes Element: das WIRFT, der Lauf
// endet ohne Bilanz und ist von "nicht gelaufen" nicht zu unterscheiden.
const cbReha = pm && pm.querySelector('.kbgrp-perm-folder[value="data/rag/ibs/reha"]');
if (cbReha) cbReha.checked = false;
gesendet.length = 0;
pm.querySelector('#kbgrp-perm-save').click();
await sleep(50);
patch = gesendet.find((g) => g.methode === 'PATCH');
check('abgewaehlter Unterordner geht raus',
      !!cbReha && !!patch && JSON.stringify(patch.rumpf.folders) === '[]', patch && JSON.stringify(patch.rumpf));

section('6. Wurzelordner: Umbenennen und Gruppen getrennt (2026-10-21)');
w.prompt = () => 'ibs-neu';
km.fetchStats = async () => {};
gesendet.length = 0;
await km.renameFolder('data/rag/ibs');
await sleep(20);
let put = gesendet.find((g) => g.methode === 'PUT' && g.pfad === '/api/knowledge/folders');
check('Bleistift: PUT /api/knowledge/folders mit Pfad und neuem Namen',
      !!put && put.rumpf.path === 'data/rag/ibs' && put.rumpf.new_name === 'ibs-neu',
      put && JSON.stringify(put.rumpf));
check('… und keine Gruppen-Zuordnung nebenbei',
      !gesendet.some((g) => g.pfad === '/api/knowledge/folders/groups'));
gesendet.length = 0;
await km.renameFolder('data/rag/ibs/reha');
check('Unterordner geht NICHT ueber renameFolder (eigener Knopf)', gesendet.length === 0);
await km.editFolder('data/rag/ibs');
await sleep(20);
const dlg = dc.getElementById('kbfld-edit-modal');
check('Positivkontrolle: Gruppen-Dialog der Wurzel offen', !!dlg);
check('… ohne Namensfeld', !!dlg && !dlg.querySelector('#kbfld-name'));
gesendet.length = 0;
dlg && dlg.querySelector('#kbfld-save').click();
await sleep(50);
check('Speichern: nur die Gruppen-Zuordnung, kein Umbenennen',
      gesendet.some((g) => g.pfad === '/api/knowledge/folders/groups' && g.rumpf.path === 'data/rag/ibs')
      && !gesendet.some((g) => g.methode === 'PUT'), JSON.stringify(gesendet.map((g) => g.methode + ' ' + g.pfad)));

section('7. Wurzel verschieben: die Meldung sagt, wohin sie gewandert ist');
{
    const meldungen = [];
    km._showNotification = (t, art) => meldungen.push([t, art]);
    km._pickFolder = async () => 'data/rag/ziel';
    const altFetch = w.fetch;
    const zeitweise = (url, o) => {
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/knowledge/folder_tree') {
            return antwort({ ok: true, folders: [{ path: 'data/rag/ziel', name: 'ziel', depth: 0 }] });
        }
        if (pfad === '/api/knowledge/subfolders/move') {
            gesendet.push({ pfad, methode: 'POST', rumpf: JSON.parse(o.body) });
            return antwort({ ok: true, path: 'data/rag/ziel/ibs', from: 'data/rag/ibs',
                             was_root: true, moved: { vector_chunks: 3 } });
        }
        return altFetch(url, o);
    };
    w.fetch = zeitweise; global.fetch = zeitweise;
    gesendet.length = 0;
    await km.moveSubfolder('data/rag/ibs');
    await sleep(30);
    w.fetch = altFetch; global.fetch = altFetch;
    const post = gesendet.find((g) => g.pfad === '/api/knowledge/subfolders/move');
    check('Positivkontrolle: Verschieben wurde gesendet',
          !!post && post.rumpf.path === 'data/rag/ibs' && post.rumpf.target === 'data/rag/ziel',
          post && JSON.stringify(post.rumpf));
    const m = meldungen.find((x) => x[1] === 'success');
    check('Meldung nennt das Ziel und dass es jetzt ein Unterordner ist',
          !!m && m[0].includes('ziel') && m[0].includes('Unterordner von') && m[0].includes('3'),
          m && m[0]);
}

section('8. Unterordner zurueck auf die oberste Ebene (Ziel data/rag)');
{
    const meldungen = [];
    km._showNotification = (t, art) => meldungen.push([t, art]);
    let angeboten = [];
    km._pickFolder = async (opts) => { angeboten = opts.map((o) => o.path); return 'data/rag'; };
    const altFetch = w.fetch;
    const zeitweise = (url, o) => {
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/knowledge/folder_tree') {
            return antwort({ ok: true, folders: [
                { path: 'data/rag/ibs', name: 'ibs', depth: 0, is_root: true },
                { path: 'data/rag/ibs/reha', name: 'reha', depth: 1, is_root: false },
                // Zweite Wurzel: ohne sie hat die Wurzel 'ibs' gar kein Ziel, der
                // Dialog oeffnet nicht, und "nicht angeboten" waere trivial wahr.
                { path: 'data/rag/andere', name: 'andere', depth: 0, is_root: true }] });
        }
        if (pfad === '/api/knowledge/subfolders/move') {
            gesendet.push({ pfad, methode: 'POST', rumpf: JSON.parse(o.body) });
            return antwort({ ok: true, path: 'data/rag/reha', from: 'data/rag/ibs/reha',
                             was_root: false, now_root: true, moved: { vector_chunks: 4 } });
        }
        return altFetch(url, o);
    };
    w.fetch = zeitweise; global.fetch = zeitweise;
    gesendet.length = 0;
    await km.moveSubfolder('data/rag/ibs/reha');
    await sleep(30);
    check('Unterordner: "oberste Ebene" wird zuerst angeboten',
          angeboten.length > 0 && angeboten[0] === 'data/rag', JSON.stringify(angeboten));
    const post = gesendet.find((g) => g.pfad === '/api/knowledge/subfolders/move');
    check('… und als Ziel data/rag gesendet', !!post && post.rumpf.target === 'data/rag',
          post && JSON.stringify(post.rumpf));
    const m = meldungen.find((x) => x[1] === 'success');
    check('Meldung: jetzt eigener Wissensordner',
          !!m && m[0].includes('eigener Wissensordner') && m[0].includes('4'), m && m[0]);
    angeboten = [];
    km._pickFolder = async (opts) => { angeboten = opts.map((o) => o.path); return null; };
    await km.moveSubfolder('data/rag/ibs');
    await sleep(30);
    check('Wurzel: "oberste Ebene" wird NICHT angeboten (liegt schon dort)',
          angeboten.length > 0 && !angeboten.includes('data/rag'), JSON.stringify(angeboten));
    w.fetch = altFetch; global.fetch = altFetch;
}

const ok = results.filter((r) => r.ok).length;
const fail = results.length - ok;
console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
BILANZ = true;
clearTimeout(WACHHUND);
w.close();
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('❌ ABBRUCH: ' + (e && e.stack || e)); process.exit(1); });
