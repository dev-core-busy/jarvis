/* Waechter: "Mein Gedaechtnis" in /wissen – fuer JEDEN Benutzer.
 *
 * Auftrag 2026-10-15: das eigene Gedaechtnis (BSI M9: einsehen und einzeln
 * loeschen) stand unter Einstellungen -> KI & System. /settings leitet
 * Nicht-Admins nach /portal um – die Funktion war damit faktisch admin-only.
 * Jetzt: Container in der Wissen-Seite, und die Wissen-Kachel erscheint fuer
 * jeden (Kachel: tests/test_portal_kacheln_ui.js, Abschnitt 2).
 *
 * Gemessen an der ECHTEN wissen.html mit ECHTER wissen.js und gedaechtnis.js:
 *   1. ohne Wissensbereich: NUR der Gedaechtnis-Container, keine Pflege-Abrufe,
 *      Liste geladen, Loeschen schickt DELETE und nimmt die Zeile heraus
 *   2. mit Wissensbereich: Pflege-Abschnitte UND Gedaechtnis-Container
 *   3. globaler Editor ohne Gruppen: sieht die Gruppenverwaltung
 *  3b. erste Gruppe angelegt (echtes knowledge.js): Seite schaltet selbst um
 *   4. Regeln: Einstellungen tragen den Block nicht mehr, Texte DE/EN da
 *
 *   node tests/test_wissen_gedaechtnis_ui.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));
const WACH = setTimeout(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 30000);
process.on('exit', (c) => { if (!BILANZ && c === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 2; } });

const HTML = lies('frontend/wissen.html');
const GRUPPE = { id: 'g1', name: 'Vertrieb', color: '#888', folders: ['data/rag/x'] };

async function seite(scope, gedaechtnis, opt) {
    opt = opt || {};
    const vc = new VirtualConsole();
    vc.on('jsdomError', () => {});
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissen', runScripts: 'outside-only',
                                  virtualConsole: vc });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'TOK');
    const rufe = [];
    const mem = (gedaechtnis || []).slice();
    // Wissensgruppen des Servers – das Anlegen in 3b aendert sie, und der
    // Scope-Abruf liefert sie danach (wie _editable_groups_for fuer Editoren).
    const kgruppen = [];
    win.fetch = function (url, init) {
        const p = String(url).split('?')[0];
        const methode = ((init && init.method) || 'GET').toUpperCase();
        rufe.push({ p, methode, body: init && init.body });
        const j = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                               json: () => Promise.resolve(d) });
        if (p === '/api/wissen/scope') {
            const sc = Object.assign({ ok: true, user: 'anna' }, scope);
            if (opt.gruppenVomServer) sc.groups = kgruppen.slice();
            return j(sc);
        }
        if (p === '/api/knowledge/groups' && methode === 'POST') {
            const b = JSON.parse(init.body);
            kgruppen.push({ id: 'g' + (kgruppen.length + 1), name: b.name, color: b.color, folders: [], count: 0 });
            return j({ ok: true });
        }
        if (p === '/api/knowledge/groups') return j({ ok: true, groups: kgruppen.slice(), ungrouped_count: 0 });
        if (p === '/api/memory' && methode === 'GET') return j({ eintraege: mem });
        if (p === '/api/memory' && methode === 'DELETE') {
            const key = JSON.parse(init.body).key;
            const i = mem.findIndex(e => e.key === key);
            if (i === -1) return j({ error: 'Eintrag nicht gefunden' }, 404);
            mem.splice(i, 1);
            return j({ ok: true, deleted: key });
        }
        if (p === '/api/wissen/files') return j({ ok: true, files: [] });
        return j({ ok: true, pending: [], spaces: [], bereiche: [] });
    };
    win.alert = () => {};
    win.eval(lies('frontend/js/sitzung.js'));
    win.eval(lies('frontend/js/icons.js'));
    win.eval(lies('frontend/js/i18n.js'));
    if (opt.gruppenModul) {
        // Reihenfolge wie in wissen.html: kbgroups -> knowledge -> … -> wissen
        win.eval(lies('frontend/js/kbgroups.js'));
        win.eval(lies('frontend/js/knowledge.js').replace(/^class JarvisKnowledgeManager/m,
                                                           'window.JarvisKnowledgeManager = class JarvisKnowledgeManager'));
    }
    win.eval(lies('frontend/js/gedaechtnis.js'));
    win.eval(lies('frontend/js/wissen.js'));
    if (win.document.readyState === 'loading') {
        await new Promise(r => win.document.addEventListener('DOMContentLoaded', r, { once: true }));
    } else {
        win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    }
    await schlaf(100);
    return { win, doc: win.document, rufe, mem };
}
const aus = (el) => !el || el.style.display === 'none' || el.classList.contains('hidden');
const gerufen = (s, p, m) => s.rufe.some(r => r.p.indexOf(p) === 0 && (!m || r.methode === m));
const PFLEGE = ['wi-sec-upload', 'wi-sec-destillat', 'wi-sec-cfbind', 'wi-sec-files'];
const PFLEGE_RUFE = ['/api/wissen/files', '/api/wissen/pending', '/api/wissen/confluence/'];

(async () => {
section('1. Ohne Wissensbereich: nur "Mein Gedaechtnis"');
{
    const s = await seite({ is_editor: false, groups: [], folders: [] }, [
        { key: 'lieblingsfarbe', value: 'blau', updated: '2026-10-14T10:00:00' },
        { key: 'projekt', value: 'Apollo', updated: '2026-10-13T09:00:00' },
    ]);
    const d = s.doc;
    check('Positivkontrolle: die Seite ist angemeldet (App sichtbar)',
          !d.getElementById('wi-app').classList.contains('hidden'));
    if (d.getElementById('wi-app').classList.contains('hidden')) {
        console.log('ABBRUCH: App nicht sichtbar – alle Folgepruefungen waeren trivial'); process.exit(2);
    }
    check('Gedaechtnis-Container ist sichtbar', !aus(d.getElementById('wi-sec-gedaechtnis')));
    PFLEGE.forEach(id => check(id + ' ist aus', aus(d.getElementById(id))));
    check('Massenzuordnung/Gruppen bleiben aus',
          aus(d.getElementById('wi-sec-matrix')) && aus(d.getElementById('wi-sec-groups')));
    PFLEGE_RUFE.forEach(p => check('kein Abruf ' + p, !gerufen(s, p), s.rufe.map(r => r.p).join(',')));
    check('Banner nennt den fehlenden Wissensbereich',
          /kein Wissensbereich/.test(d.getElementById('wi-scope-banner').textContent),
          d.getElementById('wi-scope-banner').textContent);
    check('/api/memory geladen', gerufen(s, '/api/memory', 'GET'));
    const zeilen = () => d.querySelectorAll('#wi-gedaechtnis-liste .lk-mem');
    check('zwei Eintraege gezeigt', zeilen().length === 2, String(zeilen().length));
    check('… mit Schluessel und Wert',
          /lieblingsfarbe/.test(d.getElementById('wi-gedaechtnis-liste').textContent)
          && /Apollo/.test(d.getElementById('wi-gedaechtnis-liste').textContent));
    const knopf = d.querySelector('#wi-gedaechtnis-liste .lk-mem-del');
    check('Loeschknopf traegt den Muelleimer', !!(knopf && knopf.querySelector('.jv-ico-trash, svg')),
          knopf ? knopf.innerHTML.slice(0, 60) : 'kein Knopf');
    // Ohne Liste kein Knopf: als FAIL melden, nicht abstuerzen (ein Wurf
    // endete ohne Bilanz und saehe wie "konnte nicht laufen" aus).
    if (knopf) knopf.click();
    await schlaf(40);
    const del = s.rufe.filter(r => r.p === '/api/memory' && r.methode === 'DELETE');
    check('Loeschen schickt DELETE /api/memory mit dem Schluessel',
          del.length === 1 && JSON.parse(del[0].body).key === 'lieblingsfarbe',
          del.map(r => r.body).join(' | '));
    check('… und die Zeile ist weg', zeilen().length === 1, String(zeilen().length));
    const knopf2 = d.querySelector('#wi-gedaechtnis-liste .lk-mem-del');
    if (knopf2) knopf2.click();
    await schlaf(40);
    check('letzter Eintrag weg -> Leer-Anzeige',
          !!knopf2 && zeilen().length === 0 && !!d.querySelector('#wi-gedaechtnis-liste .lk-leer'));
    s.win.close();
}

section('2. Mit Wissensbereich: Pflege UND eigenes Wissen');
{
    const s = await seite({ is_editor: false, groups: [GRUPPE],
                            folders: [{ path: 'data/rag/x', name: 'x', root: 'data/rag/x', depth: 0 }] }, []);
    const d = s.doc;
    check('Positivkontrolle: App sichtbar', !d.getElementById('wi-app').classList.contains('hidden'));
    check('Extraktor sichtbar', !aus(d.getElementById('wi-sec-upload')));
    check('Mein Wissen sichtbar', !aus(d.getElementById('wi-sec-files')));
    check('Dateien werden geladen', gerufen(s, '/api/wissen/files'));
    check('Gedaechtnis-Container ebenfalls sichtbar', !aus(d.getElementById('wi-sec-gedaechtnis')));
    check('/api/memory geladen', gerufen(s, '/api/memory', 'GET'));
    check('leeres Gedaechtnis -> Leer-Anzeige', !!d.querySelector('#wi-gedaechtnis-liste .lk-leer'));
    s.win.close();
}

// Befund 2026-10-15: renderScope() kehrte bei leerer Gruppenliste VOR der
// Gruppenverwaltung zurueck – ein globaler Editor konnte in /wissen die erste
// Wissensgruppe nicht anlegen.
section('3. Globaler Editor ohne Gruppen: Gruppenverwaltung sichtbar');
{
    const s = await seite({ is_editor: true, groups: [], folders: [] }, []);
    const d = s.doc;
    check('Positivkontrolle: App sichtbar', !d.getElementById('wi-app').classList.contains('hidden'));
    check('⚠ Wissensgruppen-Verwaltung sichtbar (erste Gruppe anlegen)', !aus(d.getElementById('wi-sec-groups')));
    check('Massenzuordnung sichtbar', !aus(d.getElementById('wi-sec-matrix')));
    check('Banner sagt dem Editor, was zu tun ist (nicht "wende dich an einen Admin")',
          /keine Wissensgruppe/.test(d.getElementById('wi-scope-banner').textContent)
          && !/Administrator/.test(d.getElementById('wi-scope-banner').textContent),
          d.getElementById('wi-scope-banner').textContent);
    check('Mein Wissen nicht ausgeblendet', !aus(d.getElementById('wi-sec-files')));
    check('Dateien werden geladen', gerufen(s, '/api/wissen/files'));
    s.win.close();
}

section('3b. Erste Gruppe anlegen -> Seite schaltet ohne Neuladen um');
{
    const s = await seite({ is_editor: true, folders: [] }, [], { gruppenModul: true, gruppenVomServer: true });
    const d = s.doc;
    const km = s.win.knowledgeManager;
    check('Positivkontrolle: echtes knowledge.js geladen', !!(km && km._addGroup), typeof km);
    if (!(km && km._addGroup)) { console.log('ABBRUCH: knowledge.js nicht ladbar'); process.exit(2); }
    await schlaf(60);
    const feld = d.getElementById('kb-grp-new-name');
    check('Positivkontrolle: Anlegen-Feld gezeichnet', !!feld);
    check('vorher: Extraktor aus', aus(d.getElementById('wi-sec-upload')));
    if (feld) feld.value = 'Vertrieb';
    await km._addGroup();
    await schlaf(80);
    check('Gruppe wurde angelegt (POST)', gerufen(s, '/api/knowledge/groups', 'POST'));
    check('⚠ danach: Extraktor sichtbar, ohne Neuladen', !aus(d.getElementById('wi-sec-upload')));
    check('… Banner ist kein Warnbanner mehr', !d.getElementById('wi-scope-banner').classList.contains('warn'),
          d.getElementById('wi-scope-banner').textContent);
    check('… die neue Gruppe steht zur Auswahl',
          /Vertrieb/.test((d.getElementById('wi-upload-groups') || {}).textContent || ''));
    s.win.close();
}

section('4. Regeln');
{
    const settings = lies('frontend/settings.html');
    check('Einstellungen tragen den Gedaechtnis-Block nicht mehr', settings.indexOf('lk-gedaechtnis') === -1);
    check('loeschkonzept.js fragt /api/memory nicht mehr ab',
          lies('frontend/js/loeschkonzept.js').indexOf('/api/memory') === -1);
    check('wissen.html bindet gedaechtnis.js VOR wissen.js ein',
          /gedaechtnis\.js\?v=\d+[\s\S]*wissen\.js\?v=\d+/.test(HTML.slice(HTML.indexOf('<script'))));
    const i18n = lies('frontend/js/i18n.js');
    ['wissen.sec_mem', 'wissen.sec_mem_desc', 'wissen.nur_eigenes', 'wissen.no_groups_editor'].forEach(k =>
        check(k + ' in DE und EN', (i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length === 2));
}

clearTimeout(WACH);
BILANZ = true;
console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
