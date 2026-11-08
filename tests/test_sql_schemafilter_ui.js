/* Waechter: Schema-Auswahl im Chat (sqlschemafilter.js) – am ECHTEN Modul.
 *
 * Die Auswahl steht neben den Wissensgruppen in der Eingabeleiste von /chat.
 * Vorgabe des Betreibers (2026-11-07): ohne Auswahl KEIN Schema – dann
 * bekommt der Lauf die SQL-Werkzeuge gar nicht erst angeboten.
 *
 * Geprueft wird die EIGENSCHAFT:
 *   1. ohne Freigabe (Status nicht ok) bleibt das Bedienelement verborgen
 *   2. Vorgabe: nichts gewaehlt, Abzeichen sagt es als TEXT ("aus")
 *   3. Haken -> Auswahl + Rueckruf (fuer die Sitzung), Abzeichen "n/m"
 *   4. setSelection VOR dem Laden greift nach dem Laden; Unbekanntes faellt weg
 *   5. "Kein Schema" leert die Auswahl
 *   6. alles vom Server wird maskiert
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, bilanz = false;
function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + String(detail).slice(0, 300) : '')); }
}
process.on('exit', function (code) {
    if (!bilanz && code === 0) { console.log('ABBRUCH: ohne Bilanzzeile'); process.exitCode = 1; }
});
const WACHHUND = setTimeout(function () {
    bilanz = true;
    console.log('✗ Wachhund (>20 s)');
    console.log('\nErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    process.exit(1);
}, 20000);
WACHHUND.unref && WACHHUND.unref();

const lies = function (p) { return fs.readFileSync(path.join(ROOT, p), 'utf8'); };
const JS = { sitzung: lies('frontend/js/sitzung.js'), i18n: lies('frontend/js/i18n.js'),
             f: lies('frontend/js/sqlschemafilter.js') };
const BOESE = '<img src=x onerror="window.__xss=1">';
function schlaf(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function seite(opt) {
    opt = opt || {};
    const dom = new JSDOM('<!DOCTYPE html><html><body><div id="slot"></div></body></html>',
                          { url: 'https://localhost/chat', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    const gerufen = [];
    win.fetch = function (url, o) {
        gerufen.push({ url: String(url), kopf: (o || {}).headers || {} });
        const st = opt.status || 200;
        const k = opt.antwort || { ok: true, schemata: [{ id: 'erp', name: 'ERP ' + BOESE, tabellen: 12 },
                                                         { id: 'hr', name: 'Personal', tabellen: 3 }] };
        return Promise.resolve({ ok: st < 400, status: st, json: function () { return Promise.resolve(k); } });
    };
    win.eval(JS.sitzung);
    win.eval(JS.i18n);
    win.eval(JS.f);
    const f = win.SqlSchemaFilter.mount({ anchor: win.document.getElementById('slot'), direction: 'up' });
    if (opt.vorher) f.setSelection(opt.vorher);
    await schlaf(20);
    return { win: win, doc: win.document, f: f, gerufen: gerufen };
}
function klick(s, el) { if (el) el.dispatchEvent(new s.win.MouseEvent('click', { bubbles: true })); return !!el; }

(async function () {
    abschnitt('1. Ohne Freigabe');
    let s = await seite({ status: 403, antwort: { detail: 'Kein Zugriff' } });
    check('Bedienelement verborgen', s.f.el.hidden === true);
    check('Auswahl leer', s.f.getSelection().length === 0);
    s.win.close();
    s = await seite({ antwort: { ok: false } });
    check('ok:false -> ebenfalls verborgen', s.f.el.hidden === true);
    s.win.close();

    abschnitt('2. Vorgabe');
    s = await seite();
    check('Positivkontrolle: Status mit Anmeldung abgefragt', s.gerufen.length === 1 && /\/api\/sql\/status$/.test(s.gerufen[0].url)
          && /Bearer test-token/.test(s.gerufen[0].kopf.Authorization), s.gerufen[0] && s.gerufen[0].url);
    check('Sichtbar', s.f.el.hidden === false);
    check('Vorgabe: KEIN Schema', JSON.stringify(s.f.getSelection()) === '[]', s.f.getSelection());
    const badge = s.doc.querySelector('.sqsf-badge');
    check('Abzeichen sagt es als Text ("aus")', badge && badge.textContent === 'aus', badge && badge.textContent);
    check('Knopf traegt den Hinweis (title)', /SQL-Fragen|Datenbankschemata/.test(s.doc.querySelector('.sqsf-btn').title));

    abschnitt('3. Auswaehlen');
    let rueckruf = null;
    s.f.onChange(function (sel) { rueckruf = sel; });
    klick(s, s.doc.querySelector('.sqsf-btn'));
    const kaesten = s.doc.querySelectorAll('.sqsf-panel input[type=checkbox]');
    check('Aufgeklappt: beide Schemata, keiner angehakt', kaesten.length === 2
          && !kaesten[0].checked && !kaesten[1].checked && !s.doc.querySelector('.sqsf-panel').hidden);
    check('Namen maskiert', !s.doc.querySelector('.sqsf-panel img') && !s.win.__xss
          && /ERP/.test(s.doc.querySelector('.sqsf-panel').textContent));
    kaesten[0].checked = true;
    kaesten[0].dispatchEvent(new s.win.Event('change', { bubbles: true }));
    check('Auswahl + Rueckruf', JSON.stringify(s.f.getSelection()) === '["erp"]' && JSON.stringify(rueckruf) === '["erp"]',
          JSON.stringify([s.f.getSelection(), rueckruf]));
    check('Abzeichen "1/2" und aktiv gekennzeichnet', badge.textContent === '1/2'
          && s.doc.querySelector('.sqsf-btn').classList.contains('sqsf-aktiv'), badge.textContent);
    klick(s, s.doc.querySelector('.sqsf-a[data-a="none"]'));
    check('"Kein Schema" leert und meldet', s.f.getSelection().length === 0 && JSON.stringify(rueckruf) === '[]'
          && badge.textContent === 'aus');
    klick(s, s.doc.body);
    check('Klick daneben klappt zu', s.doc.querySelector('.sqsf-panel').hidden === true);
    s.win.close();

    abschnitt('4. Auswahl einer Sitzung');
    s = await seite({ vorher: ['hr', 'geloescht', 7] });
    check('setSelection vor dem Laden greift danach; Unbekanntes faellt weg',
          JSON.stringify(s.f.getSelection()) === '["hr"]', s.f.getSelection());
    s.f.setSelection(null);
    check('setSelection(null) = kein Schema', s.f.getSelection().length === 0);
    s.f.setSelection(['erp', 'erp']);
    check('Doppelte Kennung einmal', JSON.stringify(s.f.getSelection()) === '["erp"]', s.f.getSelection());
    s.win.close();

    abschnitt('5. Keine Schemata');
    s = await seite({ antwort: { ok: true, schemata: [] } });
    klick(s, s.doc.querySelector('.sqsf-btn'));
    check('Leer: Hinweis statt Liste, kein "Kein Schema"-Knopf', /kein Schema angelegt/.test(s.doc.querySelector('.sqsf-panel').textContent)
          && !s.doc.querySelector('.sqsf-a'));
    s.win.close();

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(function (e) {
    bilanz = true;
    console.log('ABBRUCH: ' + (e && e.stack || e));
    console.log('\nErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    process.exit(1);
});
