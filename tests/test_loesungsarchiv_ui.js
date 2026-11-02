#!/usr/bin/env node
/* UI-Waechter: Loesungsarchiv – Mehrfachauswahl der Jira-Bereiche und der
 * Wissensgruppen (2026-11-02, Bauform wie "Erlaubte Netze fuer SSH").
 *
 * Gemessen wird WIRKLICH: echte settings.html, echtes jira.js/icons.js/
 * i18n.js in jsdom, geklickt wird auf die gezeichneten Knoepfe, und der
 * abgeschickte Rumpf von "Speichern" wird eingefangen. Ein Quelltext-Test
 * belegte nichts – die Auswahl lebt in Arbeitskopien, und der haeufigste
 * Fehler ist ein Knopf, der zeichnet, aber nichts in den Rumpf bringt.
 *
 * Lauf:  timeout 90 node tests/test_loesungsarchiv_ui.js
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) ok++; else fail++;
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const JIRA = [{ key: 'PRJA', name: 'Projekt A' }, { key: 'PRJB', name: 'Projekt B' },
              { key: 'PRJC', name: 'Contoso Service' }];
// Mehr Bereiche als der Vorschlags-Deckel, um "… und N weitere" zu messen.
for (let i = 0; i < 60; i++) JIRA.push({ key: 'X' + i, name: 'Extra ' + i });

function mkFetch(state) {
    return function (url, opts) {
        const u = String(url).split('?')[0];
        const method = (opts && opts.method) || 'GET';
        let body = null;
        try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
        state.calls.push({ method, url: u, body });
        const j = (data) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data),
                                              text: () => Promise.resolve('') });
        if (u === '/api/jira/admin/loesungsarchiv/bereiche') return j({ ok: true, bereiche: JIRA });
        if (u === '/api/jira/admin/loesungsarchiv' && method === 'GET') {
            return j({ ok: true, einstellungen: state.einst, gruppen: state.gruppen,
                       tickets_verarbeitet: 0, eintraege: 0, veroeffentlicht: 0,
                       letzter_lauf: null, naechster_lauf: null, laeuft: null,
                       ablage: state.ablage });
        }
        if (u === '/api/jira/admin/loesungsarchiv' && method === 'POST') {
            state.gespeichert = body;
            state.einst = Object.assign({}, state.einst, body);
            return j({ ok: true });
        }
        return j({ ok: true, global: [], eigene: [] });
    };
}

function makeDom(state) {
    const dom = new JSDOM(read('frontend/settings.html'),
        { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.confirm = () => true; w.alert = () => {}; w.scrollTo = () => {};
    w.fetch = mkFetch(state);
    w.eval(read('frontend/js/sitzung.js'));
    w.eval(read('frontend/js/icons.js'));
    w.eval(read('frontend/js/i18n.js'));
    w.eval(read('frontend/js/jira.js'));
    return dom;
}

const chips = (d, id) => Array.from(d.querySelectorAll('#' + id + ' .sec-ssh-chip code')).map((c) => c.textContent);
const vorschlag = (d, id, wert) => Array.from(d.querySelectorAll('#' + id + ' [data-larch-dazu]'))
    .find((b) => b.getAttribute('data-wert') === wert) || null;
const weg = (d, id, wert) => Array.from(d.querySelectorAll('#' + id + ' [data-larch-weg]'))
    .find((b) => b.getAttribute('data-wert') === wert) || null;
function klick(w, el, was) {
    if (!el) { check('Bedienelement vorhanden: ' + was, false); return false; }
    el.dispatchEvent(new w.Event('click', { bubbles: true }));
    return true;
}

(async () => {
    const state = { calls: [], gespeichert: null,
                    einst: { aktiv: true, bereiche: ['PRJA'], start: '2026-09-01', schwelle: 5,
                             cron: '30 2 * * *', gruppen: ['g1'] },
                    gruppen: [{ id: 'g1', name: 'Technik' }, { id: 'g2', name: 'Vertrieb' },
                              { id: 'g3', name: 'Leitung' }],
                    ablage: { privat: 'data/loesungsarchiv', entwuerfe: 150, ziel: 'data/rag/technik/loesungsarchiv',
                              veroeffentlicht: [{ ordner: 'data/rag/technik/loesungsarchiv/PRJA', dateien: 3 }] } };
    const dom = makeDom(state);
    const w = dom.window, d = w.document;

    section('0. Positivkontrolle');
    if (!w.JiraManager) { console.log('JiraManager fehlt – NICHT PRUEFBAR'); process.exit(2); }
    w.JiraManager.onShow();
    await sleep(150);
    const geladen = state.calls.some((c) => c.url === '/api/jira/admin/loesungsarchiv/bereiche');
    check('(Positivkontrolle) Einstellungen und Jira-Bereiche wurden geholt', geladen
          && state.calls.some((c) => c.url === '/api/jira/admin/loesungsarchiv' && c.method === 'GET'));
    if (!d.getElementById('jlarch-bereiche-liste')) { console.log('Markup fehlt – NICHT PRUEFBAR'); process.exit(2); }

    section('0b. Ablageorte in der Uebersicht');
    const zt = (d.getElementById('jlarch-zustand') || {}).textContent || '';
    check('Zwischenablage mit Pfad und Zahl', /data\/loesungsarchiv\/entwuerfe/.test(zt) && /150 Entwürfe/.test(zt), zt);
    check('veroeffentlichter Ordner mit Pfad und Zahl',
          /data\/rag\/technik\/loesungsarchiv\/PRJA/.test(zt) && /3 Dateien/.test(zt), zt);

    section('1. Gespeicherter Stand wird als Liste gezeigt');
    check('gewaehlter Bereich steht als Eintrag mit Muelleimer',
          chips(d, 'jlarch-bereiche-liste').join(',') === 'PRJA' && !!weg(d, 'jlarch-bereiche-liste', 'PRJA')
          && !!d.querySelector('#jlarch-bereiche-liste .jv-ico-trash'), chips(d, 'jlarch-bereiche-liste'));
    check('gewaehlter Bereich steht NICHT mehr unter den Vorschlaegen',
          !vorschlag(d, 'jlarch-bereiche-vorschlaege', 'PRJA'));
    check('andere Bereiche sind Vorschlaege', !!vorschlag(d, 'jlarch-bereiche-vorschlaege', 'PRJB'));
    const vsZahl = d.querySelectorAll('#jlarch-bereiche-vorschlaege [data-larch-dazu]').length;
    check('Vorschlaege sind gedeckelt, der Rest wird beziffert',
          vsZahl === 40 && /weitere/.test(d.getElementById('jlarch-bereiche-vorschlaege').textContent),
          String(vsZahl));
    check('gewaehlte Wissensgruppe als Eintrag', chips(d, 'jlarch-gruppen-liste').join(',') === 'Technik',
          chips(d, 'jlarch-gruppen-liste'));
    check('uebrige Gruppen als Vorschlaege',
          !!vorschlag(d, 'jlarch-gruppen-vorschlaege', 'g2') && !vorschlag(d, 'jlarch-gruppen-vorschlaege', 'g1'));
    check('kein Hinweis "ungespeichert" im Ausgangszustand',
          d.getElementById('jlarch-ungespeichert').style.display === 'none');

    section('2. Hinzufuegen und Entfernen per Klick');
    klick(w, vorschlag(d, 'jlarch-bereiche-vorschlaege', 'PRJB'), 'Vorschlag PRJB');
    check('Klick auf Vorschlag nimmt den Bereich auf', chips(d, 'jlarch-bereiche-liste').join(',') === 'PRJA,PRJB',
          chips(d, 'jlarch-bereiche-liste'));
    klick(w, vorschlag(d, 'jlarch-gruppen-vorschlaege', 'g3'), 'Vorschlag g3');
    klick(w, weg(d, 'jlarch-gruppen-liste', 'g1'), 'Muelleimer g1');
    check('Gruppe dazu und andere entfernt', chips(d, 'jlarch-gruppen-liste').join(',') === 'Leitung',
          chips(d, 'jlarch-gruppen-liste'));
    check('⚠ geaenderte Auswahl wird als ungespeichert gemeldet',
          d.getElementById('jlarch-ungespeichert').style.display !== 'none');

    section('3. Suchfeld');
    const feld = d.getElementById('jlarch-bereich-neu');
    feld.value = 'contoso';
    feld.dispatchEvent(new w.Event('input', { bubbles: true }));
    const gefiltert = Array.from(d.querySelectorAll('#jlarch-bereiche-vorschlaege [data-larch-dazu]'))
        .map((b) => b.getAttribute('data-wert'));
    check('Suche filtert die Vorschlaege (auch ueber den Namen)', gefiltert.join(',') === 'PRJC', gefiltert);
    klick(w, d.getElementById('jlarch-bereich-add'), 'Hinzufuegen');
    check('"Hinzufuegen" nimmt den EINEN passenden Bereich', chips(d, 'jlarch-bereiche-liste').includes('PRJC')
          && feld.value === '', chips(d, 'jlarch-bereiche-liste'));
    feld.value = 'Extra';
    klick(w, d.getElementById('jlarch-bereich-add'), 'Hinzufuegen mehrdeutig');
    const fehler = d.getElementById('jlarch-bereich-fehler');
    check('⚠ mehrdeutige Suche raet NICHT, sondern meldet', fehler.style.display !== 'none'
          && /passt auf/.test(fehler.textContent) && chips(d, 'jlarch-bereiche-liste').length === 3,
          fehler.textContent);
    feld.value = 'gibtsnicht';
    klick(w, d.getElementById('jlarch-bereich-add'), 'Hinzufuegen unbekannt');
    check('unbekannter Bereich wird gemeldet', /kein bekannter/.test(fehler.textContent), fehler.textContent);
    feld.value = 'prjb';
    feld.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    check('exakt getippter Schluessel (schon gewaehlt) wird nicht doppelt aufgenommen',
          chips(d, 'jlarch-bereiche-liste').filter((k) => k === 'PRJB').length === 1);

    section('4. Speichern schickt die Auswahl');
    klick(w, d.getElementById('jlarch-save'), 'Speichern');
    await sleep(150);
    const g = state.gespeichert || {};
    check('⚠ Rumpf traegt ALLE gewaehlten Bereiche in Reihenfolge',
          JSON.stringify(g.bereiche) === JSON.stringify(['PRJA', 'PRJB', 'PRJC']), JSON.stringify(g.bereiche));
    check('⚠ Rumpf traegt die gewaehlten Gruppen', JSON.stringify(g.gruppen) === JSON.stringify(['g3']),
          JSON.stringify(g.gruppen));
    check('kein Einzelfeld "bereich" mehr im Rumpf', !('bereich' in g));
    check('nach dem Speichern verschwindet der Hinweis',
          d.getElementById('jlarch-ungespeichert').style.display === 'none');

    section('4b. Noch nichts veroeffentlicht: der Zielordner wird genannt');
    state.ablage = Object.assign({}, state.ablage, { veroeffentlicht: [] });
    w.JiraManager.loadArchiv();
    await sleep(150);
    const zt2 = d.getElementById('jlarch-zustand').textContent;
    check('Zielordner und "noch keine Lösung" stehen da',
          /data\/rag\/technik\/loesungsarchiv/.test(zt2) && /noch keine Lösung/.test(zt2), zt2);

    section('5. Nachladen waehrend eines Laufs verwirft keine offene Auswahl');
    klick(w, weg(d, 'jlarch-bereiche-liste', 'PRJC'), 'Muelleimer PRJC');
    w.JiraManager.loadArchiv();
    await sleep(150);
    check('⚠ ungespeicherte Auswahl ueberlebt das Nachladen',
          chips(d, 'jlarch-bereiche-liste').join(',') === 'PRJA,PRJB', chips(d, 'jlarch-bereiche-liste'));

    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    w.close();
    process.exit(fail ? 1 : 0);
})();
