#!/usr/bin/env node
/* Waechter fuer den Confluence-Seitenbaum im /wissen-Informationsextraktor.
 *
 * Vorgabe (2026-09-27): Seitenauswahl als aufklappbare Ordnerstruktur, Aeste
 * per Vorgabe EINGEKLAPPT; jede Seite einzeln an-/abwaehlbar; ein Klick auf
 * eine uebergeordnete Seite setzt/entfernt den Haken aller Untergeordneten.
 *
 * Gefahren wird `frontend/js/wissen.js` unveraendert gegen die ECHTE
 * `wissen.html` und das ECHTE `i18n.js`; gestellt sind nur die Endpunkte.
 * Gemessen wird am DOM und am gesendeten Import-Rumpf, nicht am Quelltext.
 *
 * ⚠ jsdom fehlt -> Exit 2. "Konnte nicht laufen" darf nie wie "bestanden"
 * aussehen (Register).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

let OK = 0, FAIL = 0, bilanz = false;
// Registriert FRUEH: ein Absturz mitten im Lauf darf nicht als Erfolg enden.
process.on('exit', () => {
    if (!bilanz) { console.error('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); process.exitCode = 1; }
});
const wach = setTimeout(() => {
    console.error('\n\x1b[31mZEITLIMIT – haengt\x1b[0m'); bilanz = true; process.exit(1);
}, 30000);

function section(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function check(d, c, i) {
    if (c) { OK++; console.log(`  \x1b[32m✓\x1b[0m ${d}`); }
    else { FAIL++; console.log(`  \x1b[31m✗\x1b[0m ${d}${i ? ' – ' + i : ''}`); }
}
const warten = (ms) => new Promise(r => setTimeout(r, ms));

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const WJS  = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');
const ICO  = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

/* Seitenbaum der Attrappe (Form wie /api/wissen/confluence/pages):
 *   A ─┬─ A1 ── A1a
 *      └─ A2
 *   B
 *   W  (Elternseite X nicht in der Liste -> muss als Wurzel erscheinen)
 * Absichtlich NICHT in Baum-Reihenfolge geliefert (Server sortiert nach Titel). */
const PAGES = [
    { id: '11', title: 'A1',  parent: '1' },
    { id: '111', title: 'A1a', parent: '11' },
    { id: '1',  title: 'A',   parent: '' },
    { id: '12', title: 'A2',  parent: '1' },
    { id: '2',  title: 'B',   parent: '' },
    { id: '9',  title: 'W',   parent: 'X' },
];

async function seite() {
    const dom = new JSDOM(HTML, { url: 'https://example.invalid/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    win.fetch = function (url, init) {
        const pfad = String(url).split('?')[0];
        const m = ((init && init.method) || 'GET').toUpperCase();
        let body = null;
        try { body = init && init.body ? JSON.parse(init.body) : null; } catch (e) { body = init.body; }
        rufe.push({ pfad, m, body });
        const j = (d) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/wissen/scope')
            return j({ ok: true, user: 'm.mustermann', is_editor: false,
                       groups: [{ id: 'g1', name: 'Technik', color: '#888', folders: ['data/rag/x'] }],
                       folders: [{ path: 'data/rag/x', name: 'x', display: 'x', root: 'data/rag/x', depth: 0 }] });
        if (pfad === '/api/wissen/confluence/spaces')
            return j({ ok: true, configured: true, spaces: [{ key: 'NX', name: 'Contoso', type: 'global' }] });
        if (pfad === '/api/wissen/confluence/pages')
            return j({ ok: true, count: PAGES.length, pages: PAGES });
        if (pfad === '/api/wissen/confluence/bindung') return j({ ok: true, aktiv: false, bereiche: [] });
        if (pfad === '/api/wissen/extract/confluence') return j({ ok: true, total: 1, title: 't' });
        if (pfad === '/api/wissen/files')   return j({ ok: true, files: [] });
        if (pfad === '/api/wissen/pending') return j({ ok: true, items: [] });
        return j({ ok: true });
    };
    win.confirm = () => true;
    win.alert = () => {};
    win.scrollTo = () => {};
    win.HTMLElement.prototype.scrollIntoView = function () {};
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle und rufen sie beim
    // LADEN auf. Jede echte Seite laedt sie davor.
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(ICO);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(I18N);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(WJS);
    // jsdom feuert DOMContentLoaded selbst - nicht zusaetzlich ausloesen (Register)
    if (win.document.readyState === 'loading') {
        await new Promise(r => win.document.addEventListener('DOMContentLoaded', r, { once: true }));
    }
    await warten(60);
    const doc = win.document;
    // Bereich waehlen wie ein Mensch: Reiter, Suchfeld, Eintrag
    doc.getElementById('wi-tab-cf').click();
    const inp = doc.getElementById('wi-cf-space-search');
    inp.dispatchEvent(new win.Event('focus'));
    await warten(20);
    const opt = doc.querySelector('.wi-cf-opt[data-key="NX"]');
    if (opt) opt.dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    await warten(60);
    return { win, doc, rufe, zu: () => win.close() };
}

const cb = (doc, id) => doc.querySelector('#wi-cf-tree .wi-cf-cb[value="' + id + '"]');
const liVon = (doc, id) => { const c = cb(doc, id); return c ? c.closest('li') : null; };
function kidsVon(li) {
    if (!li) return null;
    for (const k of li.children) if (k.classList.contains('wi-cf-kids')) return k;
    return null;
}
function klick(win, el) {
    // echter Klick: jsdom schaltet den Haken um UND feuert change
    el.click();
}
function gewaehlt(doc) {
    return Array.from(doc.querySelectorAll('#wi-cf-tree .wi-cf-cb:checked')).map(c => c.value).sort().join(',');
}
async function importiere(s) {
    const vor = s.rufe.length;
    s.doc.getElementById('wi-extract-btn').click();
    await warten(40);
    return s.rufe.slice(vor).filter(r => r.pfad === '/api/wissen/extract/confluence').map(r => r.body);
}

(async () => {

section('0. Positivkontrolle – der Baum steht ueberhaupt');
const s0 = await seite();
{
    const tree = s0.doc.getElementById('wi-cf-tree');
    const n = tree ? tree.querySelectorAll('.wi-cf-cb').length : -1;
    check('(Positivkontrolle) Baum-Container vorhanden', !!tree);
    check('(Positivkontrolle) Seiten-Abruf fuer den gewaehlten Bereich lief',
          s0.rufe.some(r => r.pfad === '/api/wissen/confluence/pages'));
    check('(Positivkontrolle) der Baum traegt Haken', n > 0, `${n} Haken`);
    if (!tree || n <= 0) {
        console.error('\nBaum nicht aufgebaut – Inhaltspruefungen waeren trivial. NICHT PRUEFBAR');
        bilanz = true; clearTimeout(wach); process.exit(2);
    }
    // Inhaltlich, NICHT als Schranke: eine verlorene Seite ist ein Befund
    check('je Seite GENAU ein Haken (keine faellt heraus)', n === PAGES.length, `${n} Haken`);
    check('die alte Mehrfachauswahl (<select>) ist weg', !s0.doc.getElementById('wi-cf-page'));
}

section('1. Struktur – Eltern/Kind aus `parent`');
{
    const d = s0.doc;
    check('A1 haengt unter A', kidsVon(liVon(d, '1')) && kidsVon(liVon(d, '1')).contains(liVon(d, '11')));
    check('A1a haengt unter A1', kidsVon(liVon(d, '11')) && kidsVon(liVon(d, '11')).contains(liVon(d, '111')));
    check('A2 haengt unter A', kidsVon(liVon(d, '1')) && kidsVon(liVon(d, '1')).contains(liVon(d, '12')));
    const wurzeln = Array.from(d.querySelectorAll('#wi-cf-tree > ul > li'))
        .map(li => li.querySelector('.wi-cf-cb').value).sort().join(',');
    check('Wurzeln sind A, B und die Waise W', wurzeln === '1,2,9', wurzeln);
    check('Blatt B hat keinen Aufklapp-Pfeil', !liVon(d, '2').querySelector('.wi-cf-tog'));
}

section('2. Vorgabe: Aeste eingeklappt, Pfeil klappt EINE Ebene');
{
    const d = s0.doc;
    const offen = d.querySelectorAll('#wi-cf-tree .wi-cf-kids.open').length;
    check('nach dem Laden ist KEIN Ast aufgeklappt', offen === 0, `${offen} offen`);
    const tog = liVon(d, '1').querySelector('.wi-cf-tog');
    tog.click();
    check('Pfeil an A klappt A auf', kidsVon(liVon(d, '1')).classList.contains('open'));
    check('aria-expanded folgt', tog.getAttribute('aria-expanded') === 'true');
    check('A1 darunter bleibt eingeklappt', !kidsVon(liVon(d, '11')).classList.contains('open'));
    tog.click();
    check('zweiter Klick klappt wieder zu', !kidsVon(liVon(d, '1')).classList.contains('open'));
    check('Aufklappen setzt keinen Haken', gewaehlt(d) === '', gewaehlt(d));
}

section('3. Uebergeordneter Haken setzt/entfernt Untergeordnete');
{
    const d = s0.doc, w = s0.win;
    klick(w, cb(d, '1'));
    check('Haken an A -> A, A1, A1a, A2 gewaehlt, B/W nicht', gewaehlt(d) === '1,11,111,12', gewaehlt(d));
    klick(w, cb(d, '111'));
    check('A1a einzeln abwaehlbar', gewaehlt(d) === '1,11,12', gewaehlt(d));
    check('... Eltern A1/A bleiben gewaehlt', cb(d, '11').checked && cb(d, '1').checked);
    klick(w, cb(d, '11'));
    check('Haken an A1 weg -> nur A1-Zweig weg', gewaehlt(d) === '1,12', gewaehlt(d));
    klick(w, cb(d, '1'));
    check('Haken an A weg -> ganzer Ast leer', gewaehlt(d) === '', gewaehlt(d));
    klick(w, cb(d, '111'));
    check('Blatt einzeln waehlbar, Eltern unberuehrt', gewaehlt(d) === '111', gewaehlt(d));
    check('A1 und A zeigen den halben Haken',
          cb(d, '11').indeterminate === true && cb(d, '1').indeterminate === true);
    check('B zeigt keinen halben Haken', cb(d, '2').indeterminate === false);
    const all = d.getElementById('wi-cf-all');
    check('„Alles" zeigt Teilauswahl', all && all.indeterminate === true && !all.checked);
    klick(w, cb(d, '111'));
    check('halbe Haken verschwinden wieder', !cb(d, '11').indeterminate && !cb(d, '1').indeterminate);
}

section('4. „Alles"');
{
    const d = s0.doc, w = s0.win;
    const all = d.getElementById('wi-cf-all');
    klick(w, all);
    check('„Alles" hakt jede Seite an', gewaehlt(d) === '1,11,111,12,2,9', gewaehlt(d));
    klick(w, all);
    check('zweiter Klick leert', gewaehlt(d) === '', gewaehlt(d));
    const cnt = d.getElementById('wi-cf-sel-cnt');
    check('Zaehler steht da', cnt && /0 von 6/.test(cnt.textContent), cnt ? cnt.textContent : 'fehlt');
}
s0.zu();

section('5. Import-Rumpf folgt den Haken');
{
    let s = await seite();
    klick(s.win, cb(s.doc, '12'));
    let b = await importiere(s);
    check('eine Seite -> page_id', b.length === 1 && b[0].page_id === '12' && !b[0].page_ids && !b[0].space,
          JSON.stringify(b));
    s.zu();

    s = await seite();
    klick(s.win, cb(s.doc, '1'));
    b = await importiere(s);
    const ids = b[0] && b[0].page_ids ? b[0].page_ids.slice().sort().join(',') : '';
    check('Ast A -> page_ids mit allen vier Seiten', b.length === 1 && ids === '1,11,111,12', JSON.stringify(b));
    s.zu();

    s = await seite();
    klick(s.win, s.doc.getElementById('wi-cf-all'));
    b = await importiere(s);
    check('alles gewaehlt -> ganzer Bereich (space)', b.length === 1 && b[0].space === 'NX' && !b[0].page_ids,
          JSON.stringify(b));
    s.zu();

    s = await seite();
    b = await importiere(s);
    check('nichts gewaehlt -> kein Import', b.length === 0, JSON.stringify(b));
    check('... mit Hinweis', /Seiten wählen/.test(s.doc.getElementById('wi-cf-status').textContent));
    s.zu();
}

clearTimeout(wach);
bilanz = true;
console.log(`\n\x1b[1mErgebnis: ${OK}/${OK + FAIL}\x1b[0m`);
process.exit(FAIL ? 1 : 0);

})().catch(e => {
    clearTimeout(wach); bilanz = true;
    console.error('\n\x1b[31mABGEBROCHEN:\x1b[0m', e && e.stack || e);
    console.log(`\n\x1b[1mErgebnis: ${OK}/${OK + FAIL + 1} (ABGEBROCHEN)\x1b[0m`);
    process.exit(1);
});
