/* Waechter: Bearbeitungsmaske fuer BEREITS UEBERNOMMENE Dokumente (/wissen).
 *
 * Die Massenzuordnung hatte eine Spalte "Bearb.", die seit dem 2026-07-21
 * ausschliesslich eine LESEANSICHT oeffnete: der Vorrang-Zweig zeigte auf
 * `extractorManager._openReview`, und jenes Modul wurde an dem Tag aus
 * settings.html ausgehaengt und nie in wissen.html eingebunden. Die Spalte
 * versprach also eine Faehigkeit, die es nicht gab.
 *
 * Diese Maske stellt sie her. Gemessen wird die WIRKUNG an der ECHTEN
 * `wissen.html` mit der ECHTEN `wissen.js` (plus icons.js und i18n.js – ein
 * UI-Test, der weniger laedt als die Seite, prueft eine Kette, die es nicht
 * gibt). Geklickt und getippt wird wirklich.
 *
 * DIE TRAGENDE ZUSAGE: "Aktualisieren" ist PATCH **UND** erneutes Uebernehmen.
 * Das PATCH aendert nur den Entwurfsdatensatz; erst das Uebernehmen schreibt
 * die .md-Datei in der Wissensdatenbank neu, setzt die Gruppen und indiziert
 * nach. Faellt der zweite Aufruf weg, meldet die Maske Erfolg und die Datei
 * bleibt unveraendert – ein stiller Fehlschlag mit Erfolgsmeldung, und genau
 * die Klasse Fehler, gegen die diese Arbeit gemacht wurde. Eine
 * Quelltext-Suche kann "wurden BEIDE Aufrufe abgesetzt, in dieser Reihenfolge"
 * nicht beantworten.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
({ JSDOM } = require('./lib/jsdom_laden')());
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
    console.log('  \x1b[31m✗\x1b[0m unbehandelte Zurueckweisung: ' + (e && e.stack || e));
    fail++; bilanz(); process.exit(1);
});

const HTML     = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS_ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
const JS_I18N  = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const JS_WISS  = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');

/* ⚠ ZWEI Gruppen, nicht eine: `groupBoxes` hakt bei genau EINER von selbst an
 * (Bestandsverhalten – dort gibt es nichts zu waehlen). Der Fall "Dokument
 * offen, aber keine Gruppe gewaehlt" waere mit einer Gruppe gar nicht
 * herstellbar, und die Pflicht-Pruefung waere trivial gruen. */
const GRUPPEN = [
    { id: 'g1', name: 'Vertrieb', color: '#3b82f6', folders: ['data/rag/community'] },
    { id: 'g2', name: 'Recht',    color: '#10b981', folders: ['data/rag/community'] },
];

// Ein UEBERNOMMENES Extraktor-Dokument: `file` und status 'approved' setzt
// erst approve_pending (backend/web_extractor.py) - ein offener Entwurf hat
// beides nicht.
function doc() {
    return {
        id: 'doc-7', status: 'approved', file: 'data/rag/community/preise.md',
        title: 'Preisliste 2026', summary: 'Zusammenfassung der Preise',
        facts: ['Grundpreis 100 EUR', 'Rabatt ab 10 Stueck'],
        qa_pairs: [{ id: 'q1', q: 'Was kostet es?', a: '100 EUR', approved: true }],
        source_type: 'file', source_name: 'preise.xlsx',
    };
}

async function seite() {
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/wissen',
        runScripts: 'outside-only',
        pretendToBeVisual: false,
    });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.localStorage.setItem('jarvis_theme', 'dark');
    win.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener() {}, removeListener() {},
                 addEventListener() {}, removeEventListener() {} };
    };

    const gerufen = [];
    function antwort(körper) {
        return Promise.resolve({
            ok: true, status: 200,
            json: function () { return Promise.resolve(körper); },
        });
    }
    // Routing ueber den PFAD, nie ueber die volle URL (Register).
    const attrappe = function (url, opt) {
        const voll = String(url);
        const p = voll.split('?')[0];
        gerufen.push({ pfad: p, methode: (opt && opt.method) || 'GET',
                       rumpf: (opt && opt.body) ? JSON.parse(opt.body) : null });
        if (p === '/api/wissen/scope') {
            return antwort({ ok: true, user: 'anna', is_editor: true, is_admin: false,
                             groups: GRUPPEN,
                             folders: [{ path: 'data/rag/community', name: 'community',
                                         root: 'data/rag/community', depth: 0 }] });
        }
        if (p === '/api/wissen/files') return antwort({ ok: true, files: [] });
        return antwort({ ok: true, pending: [], spaces: [], status: 'ok' });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;
    win.alert = function () {};

    // ⚠ sitzung.js VOR jedem Modul-Eval. `wissen.js` liest den Sitzungstoken
    // seit `8d082990` aus der gemeinsamen Quelle (`window.JarvisSitzung`) und
    // ruft sie schon beim LADEN auf (Zeile 8) - ohne sie stirbt das Modul mit
    // "Cannot read properties of undefined (reading 'token')", und der
    // Waechter misst gar nichts mehr. Jede echte Seite laedt sie davor
    // (wissen.html: js/sitzung.js ganz oben).
    // Die ECHTE Datei, keine Attrappe: eine Attrappe, die weniger verlangt als
    // das Original, prueft eine Kette, die es nicht gibt.
    const JS_SITZUNG = require('fs').readFileSync(
        require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8');
    win.eval(JS_SITZUNG);
    win.eval(JS_ICONS);
    win.eval(JS_I18N);
    win.eval(JS_WISS);
    win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    // Auf den Scope warten - ohne ihn kennt groupBoxes keine Gruppen.
    for (let i = 0; i < 80; i++) {
        await new Promise(r => setTimeout(r, 5));
        if (gerufen.some(g => g.pfad === '/api/wissen/scope')) break;
    }
    await new Promise(r => setTimeout(r, 10));
    return { win, doc: win.document, gerufen };
}

function schlaf(ms) { return new Promise(r => setTimeout(r, ms)); }
const an = (w, id) => w.document.getElementById(id);

(async () => {

// ── 1. Die Maske ist erreichbar und vorbelegt ───────────────────────────────
section('1. Die Maske oeffnet sich und ist aus dem Dokument vorbelegt');
const a = await seite();
check('Positivkontrolle: der Scope ist geladen (Gruppen bekannt)',
      a.gerufen.some(g => g.pfad === '/api/wissen/scope'));
check('wissen.js gibt openDocEdit nach aussen (kbmatrix.js ruft es)',
      !!(a.win.WissenPortal && typeof a.win.WissenPortal.openDocEdit === 'function'));

a.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => Promise.resolve() });
await schlaf(10);
check('das Fenster steht im DOM', !!an(a.win, 'wi-doc-edit'));
check('Titel ist vorbelegt', (an(a.win, 'wi-de-title') || {}).value === 'Preisliste 2026',
      (an(a.win, 'wi-de-title') || {}).value);
check('Zusammenfassung ist vorbelegt',
      (an(a.win, 'wi-de-summary') || {}).value === 'Zusammenfassung der Preise');
check('Kernfakten stehen zeilenweise',
      (an(a.win, 'wi-de-facts') || {}).value === 'Grundpreis 100 EUR\nRabatt ab 10 Stueck',
      JSON.stringify((an(a.win, 'wi-de-facts') || {}).value));
check('das Q&A-Paar ist bearbeitbar da',
      a.doc.querySelectorAll('#wi-de-qa .wi-qa-row').length === 1);

/* ⚠ Die Knoepfe muessen die WAHRHEIT sagen. "Uebernehmen" an einem Dokument,
 * das schon in der Datenbank liegt, ist eine falsche Zusage; "Verwerfen" statt
 * "Aus DB entfernen" verschweigt, dass wirklich geloescht wird. */
const save = an(a.win, 'wi-de-save'), rem = an(a.win, 'wi-de-remove');
check('der Speicher-Knopf heisst "Aktualisieren", nicht "Uebernehmen"',
      !!save && /Aktualisieren/i.test(save.textContent) && !/Übernehmen/i.test(save.textContent),
      save && save.textContent.trim());
check('⚠ der Loesch-Knopf heisst "Aus DB entfernen", nicht "Verwerfen"',
      !!rem && /Aus DB entfernen/i.test(rem.textContent) && !/Verwerfen/i.test(rem.textContent),
      rem && rem.textContent.trim());
check('und er traegt den Muelleimer (er loescht wirklich)',
      !!rem && rem.innerHTML.includes('<svg'));
check('die Gruppen der Zeile sind vorbelegt',
      Array.from(a.doc.querySelectorAll('.wi-grp-doc:checked')).map(c => c.value).join(',') === 'g1',
      Array.from(a.doc.querySelectorAll('.wi-grp-doc:checked')).map(c => c.value).join(','));
check('der Hinweis sagt, dass die Datei neu geschrieben wird',
      /Wissensdatenbank/i.test(a.doc.querySelector('#wi-doc-edit .desc').textContent));

/* Die Sammelleiste "alle/keine" ist am Dokument DELEGIERT und prueft die
 * Klasse gegen /^wi-grp-[a-z]+$/ - fuer ein neues Praefix traegt sie damit von
 * selbst. Gemessen statt angenommen: ein Knopf, der nichts tut, ist schlimmer
 * als keiner. */
const bulkAn = a.doc.querySelector('#wi-de-groups .wi-grp-bulkbtn[data-grp-an="1"]');
check('Positivkontrolle: die Sammelleiste ist gezeichnet', !!bulkAn);
if (bulkAn) bulkAn.click();
await schlaf(5);
check('"alle markieren" wirkt auch im neuen Praefix (kein toter Knopf)',
      a.doc.querySelectorAll('.wi-grp-doc:checked').length === GRUPPEN.length,
      String(a.doc.querySelectorAll('.wi-grp-doc:checked').length) + ' von ' + GRUPPEN.length);

// ── 2. DIE TRAGENDE ZUSAGE: PATCH *und* Uebernehmen ─────────────────────────
section('2. "Aktualisieren" setzt BEIDE Aufrufe ab, in dieser Reihenfolge');
const b = await seite();
b.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => Promise.resolve() });
await schlaf(10);
// Felder wirklich bearbeiten - sonst messen wir nur die Vorbelegung.
an(b.win, 'wi-de-title').value   = 'Preisliste 2027';
an(b.win, 'wi-de-summary').value = 'Neue Zusammenfassung';
an(b.win, 'wi-de-facts').value   = 'Grundpreis 120 EUR\n- Rabatt entfaellt\n\n';
b.gerufen.length = 0;
an(b.win, 'wi-de-save').click();
await schlaf(30);

const anDoc = b.gerufen.filter(g => g.pfad.indexOf('/api/knowledge/pending/') === 0);
const patch = anDoc.find(g => g.methode === 'PATCH');
const appr  = anDoc.find(g => g.pfad.endsWith('/approve'));
check('ein PATCH ging an /api/knowledge/pending/doc-7',
      !!patch && patch.pfad === '/api/knowledge/pending/doc-7', JSON.stringify(anDoc.map(x => x.methode + ' ' + x.pfad)));
check('⚠ UND ein Uebernehmen (ohne das bliebe die Datei unveraendert)',
      !!appr && appr.methode === 'POST', JSON.stringify(anDoc.map(x => x.methode + ' ' + x.pfad)));
check('und zwar in dieser Reihenfolge (erst aendern, dann schreiben)',
      !!patch && !!appr && anDoc.indexOf(patch) < anDoc.indexOf(appr));
check('⚠ es ist die EDITOREN-Familie /api/knowledge/ (sie sieht alle Dokumente)',
      anDoc.length >= 2 && !b.gerufen.some(g => g.pfad.indexOf('/api/wissen/pending/') === 0),
      JSON.stringify(b.gerufen.map(g => g.pfad)));

check('der bearbeitete Titel steht im Rumpf', !!patch && patch.rumpf.title === 'Preisliste 2027',
      patch && JSON.stringify(patch.rumpf.title));
check('die bearbeitete Zusammenfassung steht im Rumpf',
      !!patch && patch.rumpf.summary === 'Neue Zusammenfassung');
check('Kernfakten: Aufzaehlungszeichen und Leerzeilen sind entfernt',
      !!patch && JSON.stringify(patch.rumpf.facts) === JSON.stringify(['Grundpreis 120 EUR', 'Rabatt entfaellt']),
      patch && JSON.stringify(patch.rumpf.facts));
check('das Q&A-Paar geht mit', !!patch && (patch.rumpf.qa_pairs || []).length === 1);
check('die Gruppen gehen an das Uebernehmen', !!appr && JSON.stringify(appr.rumpf.groups) === JSON.stringify(['g1']),
      appr && JSON.stringify(appr.rumpf));
check('das Fenster ist danach zu', !an(b.win, 'wi-doc-edit'));
check('und die Dateiliste wird nachgezogen',
      b.gerufen.some(g => g.pfad === '/api/wissen/files'));

// ── 3. Pflichten: ohne Gruppe und ohne Inhalt wird NICHT geschrieben ────────
section('3. Ohne Zielgruppe und ohne Inhalt passiert nichts');
const c = await seite();
c.win.WissenPortal.openDocEdit(doc(), { gruppen: [], entfernen: () => Promise.resolve() });
await schlaf(10);
check('Positivkontrolle: kein Haken gesetzt (zwei Gruppen, keine vorbelegt)',
      c.doc.querySelectorAll('.wi-grp-doc:checked').length === 0,
      String(c.doc.querySelectorAll('.wi-grp-doc:checked').length));
c.gerufen.length = 0;
an(c.win, 'wi-de-save').click();
await schlaf(20);
check('⚠ ohne Zielgruppe geht KEIN Aufruf raus',
      !c.gerufen.some(g => g.pfad.indexOf('/api/knowledge/pending/') === 0),
      JSON.stringify(c.gerufen.map(g => g.pfad)));
check('und der Grund steht im Fenster',
      /Zielgruppe/i.test((an(c.win, 'wi-de-status') || {}).textContent || ''),
      (an(c.win, 'wi-de-status') || {}).textContent);
check('das Fenster bleibt offen (die Arbeit ist nicht verloren)', !!an(c.win, 'wi-doc-edit'));

// Jetzt Gruppe setzen, aber jeden Inhalt entfernen.
c.doc.querySelector('.wi-grp-doc').checked = true;
an(c.win, 'wi-de-facts').value = '';
c.doc.querySelectorAll('#wi-de-qa .wi-qa-keep').forEach(cb => { cb.checked = false; });
c.gerufen.length = 0;
an(c.win, 'wi-de-save').click();
await schlaf(20);
check('⚠ ohne Fakt und ohne freigegebenes Q&A geht KEIN Aufruf raus',
      !c.gerufen.some(g => g.pfad.indexOf('/api/knowledge/pending/') === 0),
      JSON.stringify(c.gerufen.map(g => g.pfad)));
check('und der Grund nennt den leeren Inhalt',
      /Kernfakt|Frage-Antwort/i.test((an(c.win, 'wi-de-status') || {}).textContent || ''),
      (an(c.win, 'wi-de-status') || {}).textContent);

// ── 4. "Aus DB entfernen" fragt nach und delegiert ──────────────────────────
section('4. "Aus DB entfernen" fragt nach und benutzt den Weg des Aufrufers');
const d = await seite();
let entfernt = 0;
d.win.confirm = () => false;   // Rueckfrage abgelehnt
d.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => { entfernt++; return Promise.resolve(); } });
await schlaf(10);
an(d.win, 'wi-de-remove').click();
await schlaf(20);
check('⚠ bei abgelehnter Rueckfrage wird NICHT geloescht', entfernt === 0, 'Aufrufe: ' + entfernt);
check('und das Fenster bleibt offen', !!an(d.win, 'wi-doc-edit'));

d.win.confirm = () => true;
an(d.win, 'wi-de-remove').click();
await schlaf(20);
check('nach Bestaetigung wird der Entfernen-Weg des Aufrufers gerufen', entfernt === 1, 'Aufrufe: ' + entfernt);
check('das Fenster ist danach zu', !an(d.win, 'wi-doc-edit'));

// ⚠ Ohne Entfernen-Weg darf es den Knopf nicht geben: ein Knopf, der nichts
// tut, ist schlimmer als keiner.
const e = await seite();
e.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'] });
await schlaf(10);
check('⚠ ohne Entfernen-Weg fehlt der Knopf ganz', !an(e.win, 'wi-de-remove'));
check('der Aktualisieren-Knopf ist trotzdem da', !!an(e.win, 'wi-de-save'));

// ── 4b. Q&A: geloeschte Paare verschwinden, fremde werden nicht gelesen ─────
section('4b. Q&A-Paare: geloescht heisst geloescht, und keine Fremdfelder');
const g = await seite();
g.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => Promise.resolve() });
await schlaf(10);
g.doc.querySelectorAll('#wi-de-qa .wi-qa-del').forEach(b => b.click());
await schlaf(10);
check('Positivkontrolle: alle Q&A-Zeilen sind weg',
      g.doc.querySelectorAll('#wi-de-qa .wi-qa-row').length === 0);
g.gerufen.length = 0;
an(g.win, 'wi-de-save').click();
await schlaf(30);
const gp = g.gerufen.find(x => x.methode === 'PATCH');
check('⚠ eine LEERE Q&A-Liste geht mit (sonst blieben sie stehen)',
      !!gp && Array.isArray(gp.rumpf.qa_pairs) && gp.rumpf.qa_pairs.length === 0,
      gp && JSON.stringify(gp.rumpf.qa_pairs));

/* ⚠ Ein Dokument OHNE Q&A darf die Felder eines offenen ENTWURFS nicht lesen:
 * collectQa() ohne Argument faellt auf #wi-rev-qa der Entwurfs-Pruefung
 * zurueck. Hier wird dieser Fremd-Container absichtlich hergestellt. */
const h = await seite();
const fremd = h.doc.createElement('div');
fremd.id = 'wi-rev-qa';
fremd.innerHTML = '<div class="wi-qa-row" data-qid="fremd">'
    + '<input type="checkbox" class="wi-qa-keep" checked>'
    + '<input class="wi-qa-q" value="FREMDE Frage">'
    + '<textarea class="wi-qa-a">FREMDE Antwort</textarea></div>';
h.doc.body.appendChild(fremd);
const ohneQa = doc(); delete ohneQa.qa_pairs;
h.win.WissenPortal.openDocEdit(ohneQa, { gruppen: ['g1'] });
await schlaf(10);
check('Positivkontrolle: der fremde Entwurfs-Container ist da und gefuellt',
      h.doc.querySelectorAll('#wi-rev-qa .wi-qa-row').length === 1);
check('und die Maske zeichnet selbst kein Q&A', !an(h.win, 'wi-de-qa'));
h.gerufen.length = 0;
an(h.win, 'wi-de-save').click();
await schlaf(30);
const hp = h.gerufen.find(x => x.methode === 'PATCH');
check('⚠ die Maske liest die FREMDEN Q&A-Felder nicht',
      !!hp && !('qa_pairs' in hp.rumpf),
      hp && JSON.stringify(hp.rumpf.qa_pairs));

// ── 5. Abgrenzung zur Entwurfs-Pruefung ────────────────────────────────────
section('5. Die Maske ist NICHT der Vorschau-Container der Entwurfsliste');
/* ⚠ Ein uebernommenes Dokument hat in der Entwurfsliste keine Zeile
 * (/api/wissen/pending filtert `approved` heraus). Laege die Maske im
 * gemeinsamen Container #wi-ext-review, wuerde sie beim naechsten
 * Listenaufbau mitgeloescht - siehe clearReview in wissen.js. */
const f = await seite();
f.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => Promise.resolve() });
await schlaf(10);
const fenster = an(f.win, 'wi-doc-edit');
check('die Maske liegt direkt am body (eigenes Fenster)',
      !!fenster && fenster.parentNode === f.doc.body);
check('⚠ und NICHT im Vorschau-Container der Entwurfsliste',
      !!fenster && !(an(f.win, 'wi-ext-review') || f.doc.body).contains(fenster));
/* ⚠ Register: `display:flex` allein oeffnet ein `.modal` NICHT - die globale
 * Klasse traegt `opacity:0` und wird erst mit `.open` sichtbar. Die Maske
 * benutzt sie deshalb gar nicht (Bauform von pickFolder). */
check('sie benutzt die globale Klasse "modal" nicht (opacity-0-Falle)',
      !!fenster && !fenster.classList.contains('modal'), fenster && fenster.className);
check('und ist nicht versteckt', !!fenster && fenster.style.display !== 'none'
      && !fenster.hasAttribute('hidden'));

// ── 6. Ablehnungen des Servers (Code-Review 2026-10-07) ─────────────────────
/* Vorher: das PATCH wurde nicht geprueft – scheiterte es, schrieb das
 * Uebernehmen die .md aus dem ALTEN Datensatz, und die Maske schloss als
 * Erfolg. Und "Aus DB entfernen" schluckte jeden Fehler in kbmatrix.js. */
section('6. Abgelehnt heisst: Fenster bleibt offen, Meldung, kein Folgeaufruf');
for (const [was, ant] of [['PATCH {ok:false}', { ok: true, status: 200, k: { ok: false } }],
                          ['PATCH 500', { ok: false, status: 500, k: { error: 'kaputt' } }]]) {
    const s6 = await seite();
    const urFetch = s6.win.fetch;
    s6.win.fetch = function (url, opt) {
        if ((opt && opt.method) === 'PATCH') {
            s6.gerufen.push({ pfad: String(url).split('?')[0], methode: 'PATCH', rumpf: null });
            return Promise.resolve({ ok: ant.ok, status: ant.status,
                                     json: function () { return Promise.resolve(ant.k); } });
        }
        return urFetch(url, opt);
    };
    s6.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'], entfernen: () => Promise.resolve() });
    await schlaf(10);
    s6.gerufen.length = 0;
    an(s6.win, 'wi-de-save').click();
    await schlaf(40);
    const pf = s6.gerufen.map(x => x.methode + ' ' + x.pfad);
    check('Positivkontrolle (' + was + '): das PATCH ging raus', pf.some(x => x.indexOf('PATCH ') === 0), JSON.stringify(pf));
    check('⚠ ' + was + ': KEIN Uebernehmen danach', !pf.some(x => x.endsWith('/approve')), JSON.stringify(pf));
    check('⚠ ' + was + ': Fenster bleibt offen', !!an(s6.win, 'wi-doc-edit'));
    const txt = (an(s6.win, 'wi-doc-edit') || {}).textContent || '';
    check('… mit Fehlermeldung', txt.indexOf(s6.win.t('kbmatrix.update_failed')) >= 0, txt.slice(-160));
    s6.win.close();
}
{
    const s7 = await seite();
    s7.win.confirm = () => true;
    s7.win.WissenPortal.openDocEdit(doc(), { gruppen: ['g1'],
        entfernen: () => Promise.reject(new Error('HTTP 403')) });
    await schlaf(10);
    an(s7.win, 'wi-de-remove').click();
    await schlaf(30);
    check('⚠ Entfernen abgelehnt: Fenster bleibt offen', !!an(s7.win, 'wi-doc-edit'));
    const txt = (an(s7.win, 'wi-doc-edit') || {}).textContent || '';
    check('… mit Meldung samt Grund', txt.indexOf(s7.win.t('kbmatrix.delete_failed')) >= 0
          && txt.indexOf('HTTP 403') >= 0, txt.slice(-160));
    s7.win.close();
}

// ── 7. Das ECHTE _docAusDb aus kbmatrix.js (am Syntaxbaum geschnitten) ──────
section('7. kbmatrix._docAusDb wirft bei einer Ablehnung');
{
    const acorn = require('./lib/acorn_laden')();
    const KBM = fs.readFileSync(path.join(ROOT, 'frontend/js/kbmatrix.js'), 'utf8');
    let fn = null;
    (function such(n) {
        if (fn || !n || typeof n.type !== 'string') return;
        if (n.type === 'FunctionDeclaration' && n.id && n.id.name === '_docAusDb') { fn = n; return; }
        for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(such); else if (v && typeof v.type === 'string') such(v); }
    })(acorn.parse(KBM, { ecmaVersion: 'latest', sourceType: 'script' }));
    check('Positivkontrolle: _docAusDb in kbmatrix.js gefunden', !!fn);
    if (fn) {
        const bau = (antworten) => {
            const rufe = [];
            const f = function (url, opt) {
                const a = antworten[rufe.length] || { ok: true, status: 200, k: { ok: true } };
                rufe.push(((opt && opt.method) || 'GET') + ' ' + url);
                return Promise.resolve({ ok: a.ok, status: a.status, json: () => Promise.resolve(a.k) });
            };
            const g = new Function('fetch', '_auth', KBM.slice(fn.start, fn.end) + '; return _docAusDb;')(
                f, (h) => h || {});
            return { g, rufe };
        };
        const versuch = async (antworten) => {
            const { g, rufe } = bau(antworten);
            try { await g('data/rag/x/extract_a.md', 'doc-1'); return { geworfen: false, rufe }; }
            catch (e) { return { geworfen: true, rufe, msg: String(e && e.message) }; }
        };
        let r = await versuch([]);
        check('Positivkontrolle: beide ok -> wirft nicht, zwei Aufrufe', !r.geworfen && r.rufe.length === 2, JSON.stringify(r));
        r = await versuch([{ ok: false, status: 403, k: { error: 'verboten' } }]);
        check('⚠ Datei-DELETE 403 -> wirft, Entwurf bleibt (kein zweiter Aufruf)',
              r.geworfen && r.rufe.length === 1 && r.msg === 'verboten', JSON.stringify(r));
        r = await versuch([{ ok: true, status: 200, k: { ok: false, error: 'Ungültiger Pfad' } }]);
        check('⚠ Datei-DELETE {ok:false} -> wirft', r.geworfen && r.rufe.length === 1, JSON.stringify(r));
        r = await versuch([{ ok: true, status: 200, k: { ok: true } }, { ok: false, status: 500, k: {} }]);
        check('⚠ Entwurf-DELETE 500 -> wirft', r.geworfen && r.rufe.length === 2, JSON.stringify(r));
        r = await versuch([{ ok: true, status: 200, k: { ok: true } }, { ok: true, status: 200, k: { ok: false } }]);
        check('Entwurf schon weg ({ok:false}, 200) ist kein Fehler', !r.geworfen, JSON.stringify(r));
    }
}

clearTimeout(wachhund);
[a, b, c, d, e, f, g, h].forEach(s => s.win.close());
bilanz();
process.exit(fail ? 1 : 0);

})().catch(e => {
    console.log('  \x1b[31m✗\x1b[0m ABBRUCH: ' + (e && e.stack || e));
    fail++; bilanz(); process.exit(1);
});
