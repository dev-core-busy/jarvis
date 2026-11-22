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
 *  1b. "Alles löschen" (2026-11-16): Rueckfrage, EIN DELETE mit {alle:true},
 *      Liste leer, Knopf weg; abgelehnte Rueckfrage schickt nichts; Fehler
 *      bleibt am Knopf stehen; Infozeile zur Loeschfrist steht im Container
 *  1c. Suche (2026-11-20): filtert nach Schluessel UND Wert, Gross-/Klein-
 *      schreibung egal, mehrere Woerter = UND; Trefferzahl, "keine Treffer",
 *      Escape leert; Loeschen eines Treffers behaelt den Filter; "Alles
 *      löschen" bei aktiver Suche fragt ausdruecklich nach ALLEN und loescht
 *      alle; ohne Eintraege ist das Suchfeld weg
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
const WACH = require('./lib/wachhund')(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 30000);
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
            const rumpf = JSON.parse(init.body);
            if (opt.deleteFehler) return j({ error: 'Testfehler' }, 500);
            if (rumpf.alle === true) {
                const n = mem.length;
                mem.splice(0, mem.length);
                return j({ ok: true, deleted_all: n });
            }
            const key = rumpf.key;
            const i = mem.findIndex(e => e.key === key);
            if (i === -1) return j({ error: 'Eintrag nicht gefunden' }, 404);
            mem.splice(i, 1);
            return j({ ok: true, deleted: key });
        }
        if (p === '/api/wissen/files') return j({ ok: true, files: [] });
        return j({ ok: true, pending: [], spaces: [], bereiche: [] });
    };
    win.alert = () => {};
    // Rueckfrage: gezaehlt, Antwort steuerbar (Vorgabe: ja)
    win.__fragen = [];
    win.confirm = (txt) => { win.__fragen.push(txt); return opt.confirm !== false; };
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

section('1b. "Alles löschen" und Infozeile zur Loeschfrist');
{
    const EINTR = [
        { key: 'a', value: '1', updated: '2026-10-14T10:00:00' },
        { key: 'b', value: '2', updated: '2026-10-13T10:00:00' },
        { key: 'c', value: '3', updated: '2026-10-12T10:00:00' },
    ];
    const s = await seite({ is_editor: false, groups: [], folders: [] }, EINTR);
    const d = s.doc;
    const knopf = d.getElementById('wi-gedaechtnis-alle');
    const zeilen = () => d.querySelectorAll('#wi-gedaechtnis-liste .lk-mem').length;
    check('Positivkontrolle: drei Eintraege gezeigt', zeilen() === 3, String(zeilen()));
    if (zeilen() !== 3) { console.log('ABBRUCH: Liste nicht aufgebaut'); process.exit(2); }
    check('Knopf "Alles löschen" steht im Gedaechtnis-Container',
          !!knopf && !!knopf.closest('#wi-sec-gedaechtnis'));
    check('… mit Eintraegen sichtbar', !!knopf && knopf.hidden === false);
    check('… beschriftet', !!knopf && /Alles löschen/.test(knopf.textContent), knopf && knopf.textContent);
    const frist = d.querySelector('#wi-sec-gedaechtnis .wi-mem-frist');
    check('Infozeile zur Loeschfrist steht im Container', !!frist);
    check('… und sagt, dass nichts automatisch geloescht wird',
          !!frist && /Automatisch gelöscht wird hier nichts/.test(frist.textContent), frist && frist.textContent);
    if (knopf) knopf.click();
    await schlaf(40);
    const dels = () => s.rufe.filter(r => r.p === '/api/memory' && r.methode === 'DELETE');
    check('Rueckfrage nennt die Anzahl', s.win.__fragen.length === 1 && /\b3\b/.test(s.win.__fragen[0]),
          s.win.__fragen.join(' | '));
    check('genau EIN DELETE mit {alle:true}',
          dels().length === 1 && JSON.parse(dels()[0].body).alle === true, dels().map(r => r.body).join(' | '));
    check('Liste danach leer mit Leer-Anzeige',
          zeilen() === 0 && !!d.querySelector('#wi-gedaechtnis-liste .lk-leer'));
    check('Knopf danach ausgeblendet', !!knopf && knopf.hidden === true);
    s.win.close();
}
{
    const s = await seite({ is_editor: false, groups: [], folders: [] },
                          [{ key: 'a', value: '1', updated: '' }], { confirm: false });
    const d = s.doc;
    const knopf = d.getElementById('wi-gedaechtnis-alle');
    if (knopf) knopf.click();
    await schlaf(40);
    check('Positivkontrolle: Rueckfrage gestellt', s.win.__fragen.length === 1);
    check('abgelehnte Rueckfrage schickt KEIN DELETE',
          !s.rufe.some(r => r.p === '/api/memory' && r.methode === 'DELETE'));
    check('… und die Zeile bleibt', d.querySelectorAll('#wi-gedaechtnis-liste .lk-mem').length === 1);
    s.win.close();
}
{
    const s = await seite({ is_editor: false, groups: [], folders: [] },
                          [{ key: 'a', value: '1', updated: '' }], { deleteFehler: true });
    const d = s.doc;
    const knopf = d.getElementById('wi-gedaechtnis-alle');
    if (knopf) knopf.click();
    await schlaf(40);
    const fehler = knopf && knopf.parentNode.querySelector('.lk-fehler');
    check('Serverfehler steht am Knopf', !!fehler && /Testfehler/.test(fehler.textContent));
    check('… die Liste bleibt stehen', d.querySelectorAll('#wi-gedaechtnis-liste .lk-mem').length === 1);
    check('… der Knopf ist wieder bedienbar', !!knopf && !knopf.disabled && !knopf.hidden);
    s.win.close();
}

section('1c. Suche im Gedaechtnis');
{
    const EINTR = [
        { key: 'lieblingsfarbe', value: 'Blau', updated: '2026-10-14T10:00:00' },
        { key: 'projekt', value: 'Apollo Umbau', updated: '2026-10-13T09:00:00' },
        { key: 'drucker', value: 'steht im Flur, blaues Gehaeuse', updated: '' },
        { key: 'kollege', value: 'sitzt im Raum 4', updated: '' },
    ];
    const s = await seite({ is_editor: false, groups: [], folders: [] }, EINTR);
    const d = s.doc;
    const feld = d.getElementById('wi-gedaechtnis-q');
    const leiste = d.getElementById('wi-gedaechtnis-suche');
    const zahl = d.getElementById('wi-gedaechtnis-treffer');
    const alle = () => Array.from(d.querySelectorAll('#wi-gedaechtnis-liste .lk-mem'));
    const sichtbar = () => alle().filter(z => z.style.display !== 'none');
    const sichtbareSchluessel = () => sichtbar().map(z => (z.querySelector('b') || {}).textContent).sort().join(',');
    const keineTreffer = () => d.querySelector('#wi-gedaechtnis-liste .lk-keine-treffer');
    const suche = (q) => { if (feld) { feld.value = q; feld.dispatchEvent(new s.win.Event('input', { bubbles: true })); } };
    check('Positivkontrolle: vier Eintraege gezeigt, alle sichtbar',
          alle().length === 4 && sichtbar().length === 4, alle().length + '/' + sichtbar().length);
    if (alle().length !== 4) { console.log('ABBRUCH: Liste nicht aufgebaut'); process.exit(2); }
    check('Suchfeld steht im Gedaechtnis-Container', !!feld && !!feld.closest('#wi-sec-gedaechtnis'));
    check('… und ist mit Eintraegen sichtbar', !!leiste && leiste.hidden === false);
    check('… traegt einen Platzhalter (i18n)', !!feld && /Gedächtnis/.test(feld.placeholder), feld && feld.placeholder);
    check('… ist als Suchfeld vom TAB-Vorschlag ausgenommen', !!feld && feld.hasAttribute('data-tabfill-nein'));
    check('ohne Suchbegriff keine Trefferzahl', !!zahl && zahl.textContent === '', zahl && zahl.textContent);

    suche('apollo');
    check('Suche im WERT, Gross-/Kleinschreibung egal ("apollo")', sichtbareSchluessel() === 'projekt', sichtbareSchluessel());
    check('… Trefferzahl "1 von 4"', !!zahl && /1 von 4/.test(zahl.textContent), zahl && zahl.textContent);
    suche('DRUCK');
    check('Suche im SCHLUESSEL ("DRUCK")', sichtbareSchluessel() === 'drucker', sichtbareSchluessel());
    suche('blau');
    check('Teilwort trifft mehrere ("blau" -> Blau, blaues)', sichtbareSchluessel() === 'drucker,lieblingsfarbe', sichtbareSchluessel());
    suche('  im   flur ');
    check('mehrere Woerter = UND, Leerraum egal ("im flur")', sichtbareSchluessel() === 'drucker', sichtbareSchluessel());
    suche('im');
    check('… "im" allein trifft beide', sichtbareSchluessel() === 'drucker,kollege', sichtbareSchluessel());
    check('bei Treffern keine "keine Treffer"-Zeile', !keineTreffer());
    suche('zebra');
    check('kein Treffer -> nichts sichtbar', sichtbar().length === 0, String(sichtbar().length));
    check('… mit Hinweis "Kein Eintrag passt"', !!keineTreffer() && /Kein Eintrag passt/.test(keineTreffer().textContent));
    check('… und Trefferzahl "0 von 4"', !!zahl && /0 von 4/.test(zahl.textContent), zahl && zahl.textContent);
    check('… die Eintraege selbst bleiben (nur ausgeblendet)', alle().length === 4);
    suche('');
    check('leerer Suchbegriff -> wieder alle sichtbar, Hinweis weg',
          sichtbar().length === 4 && !keineTreffer() && zahl.textContent === '');
    suche('blau');
    if (feld) feld.dispatchEvent(new s.win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check('Escape leert das Feld und zeigt alles', !!feld && feld.value === '' && sichtbar().length === 4,
          feld && (feld.value + '/' + sichtbar().length));

    // Einen Treffer loeschen: der Filter bleibt, Zahl zieht nach
    suche('blau');
    const del = sichtbar().map(z => z.querySelector('.lk-mem-del')).find(Boolean);
    if (del) del.click();
    await schlaf(40);
    check('Loeschen eines Treffers: Filter bleibt aktiv (nur der andere Treffer sichtbar)',
          alle().length === 3 && sichtbar().length === 1, alle().length + '/' + sichtbar().length);
    check('… Trefferzahl zieht nach ("1 von 3")', !!zahl && /1 von 3/.test(zahl.textContent), zahl && zahl.textContent);
    const del2 = sichtbar().map(z => z.querySelector('.lk-mem-del')).find(Boolean);
    if (del2) del2.click();
    await schlaf(40);
    check('letzter Treffer geloescht, andere da -> "keine Treffer"',
          alle().length === 2 && sichtbar().length === 0 && !!keineTreffer(), alle().length + '/' + sichtbar().length);
    check('… nicht die Leer-Anzeige des ganzen Gedaechtnisses',
          !d.querySelector('#wi-gedaechtnis-liste .lk-leer:not(.lk-keine-treffer)'));

    // "Alles löschen" bei aktiver Suche: ausdrueckliche Frage, loescht ALLES
    suche('apollo');
    const knopf = d.getElementById('wi-gedaechtnis-alle');
    if (knopf) knopf.click();
    await schlaf(40);
    const frage = s.win.__fragen[s.win.__fragen.length - 1] || '';
    check('Rueckfrage bei aktiver Suche nennt ALLE und die ausgeblendeten',
          /ALLE 2/.test(frage) && /ausblendet/.test(frage), frage);
    const dels = s.rufe.filter(r => r.p === '/api/memory' && r.methode === 'DELETE');
    const letzter = dels.length ? JSON.parse(dels[dels.length - 1].body) : {};
    check('… geschickt wird {alle:true}, keine Einzelloeschung der Treffer', letzter.alle === true,
          dels.map(r => r.body).join(' | '));
    check('danach: Liste leer, Leer-Anzeige, Suchfeld geleert und ausgeblendet',
          alle().length === 0 && !!d.querySelector('#wi-gedaechtnis-liste .lk-leer') && !keineTreffer()
          && !!feld && feld.value === '' && !!leiste && leiste.hidden === true);
    s.win.close();
}
{
    // Ohne Suche: die gewohnte Rueckfrage (nicht die mit "ausblendet")
    const s = await seite({ is_editor: false, groups: [], folders: [] },
                          [{ key: 'a', value: '1', updated: '' }]);
    const knopf = s.doc.getElementById('wi-gedaechtnis-alle');
    if (knopf) knopf.click();
    await schlaf(40);
    check('Positivkontrolle: Rueckfrage gestellt', s.win.__fragen.length === 1);
    check('ohne Suche: gewohnte Rueckfrage ohne "ausblendet"',
          s.win.__fragen.length === 1 && !/ausblendet/.test(s.win.__fragen[0]), s.win.__fragen.join(' | '));
    s.win.close();
}
{
    const s = await seite({ is_editor: false, groups: [], folders: [] }, []);
    const leiste = s.doc.getElementById('wi-gedaechtnis-suche');
    check('Positivkontrolle: leeres Gedaechtnis zeigt die Leer-Anzeige',
          !!s.doc.querySelector('#wi-gedaechtnis-liste .lk-leer'));
    check('leeres Gedaechtnis -> kein Suchfeld', !!leiste && leiste.hidden === true);
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
    check('leeres Gedaechtnis -> kein "Alles löschen"',
          !!d.getElementById('wi-gedaechtnis-alle') && d.getElementById('wi-gedaechtnis-alle').hidden === true);
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
    // .wi-mem-suche setzt display:flex und schluege sonst das hidden-Attribut
    check('Suchzeile: [hidden] ausdruecklich auf display:none',
          /\.wi-mem-suche\[hidden\]\s*\{\s*display:\s*none/.test(HTML));
    check('wissen.html bindet gedaechtnis.js VOR wissen.js ein',
          /gedaechtnis\.js\?v=\d+[\s\S]*wissen\.js\?v=\d+/.test(HTML.slice(HTML.indexOf('<script'))));
    const i18n = lies('frontend/js/i18n.js');
    ['wissen.sec_mem', 'wissen.sec_mem_desc', 'wissen.nur_eigenes', 'wissen.no_groups_editor',
     'wissen.mem_frist', 'wissen.mem_alle', 'wissen.mem_alle_frage', 'wissen.mem_alle_frage_suche',
     'wissen.mem_suche_ph', 'wissen.mem_treffer', 'wissen.mem_keine_treffer'].forEach(k =>
        check(k + ' in DE und EN', (i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length === 2));
}

clearTimeout(WACH);
BILANZ = true;
console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
