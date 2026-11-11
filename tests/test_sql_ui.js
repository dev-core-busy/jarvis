/* Waechter: Seite /sql (SQL-Assistent) – am ECHTEN DOM.
 *
 * Die echte `sql.html` mit der echten `sql.js` (plus sitzung.js, icons.js,
 * i18n.js – ein UI-Test, der weniger laedt als die Seite, prueft eine Kette,
 * die es nicht gibt). Geklickt und getippt wird ueber echte Ereignisse, die
 * Antworten kommen aus einer fetch-Attrappe in der ECHTEN Antwortform der
 * Endpunkte (main.py: sql_status, sql_frage, sql_suche, sql_tabelle,
 * sql_verbindung).
 *
 * Geprueft wird die EIGENSCHAFT:
 *   1. ohne permissions.schema bleibt die Seite verborgen, kein Datenabruf
 *   2. Schema-Auswahl: alle Schemata maskiert als Kaestchen, ohne gemerkte
 *      Auswahl alle gewaehlt, eine gemerkte gilt (Unbekanntes faellt weg),
 *      jede Aenderung wird gemerkt; Dialekt-Vorgabe vom Server
 *   3. Knopf gesperrt MIT Grund (keine Frage / kein Schema / nichts gewaehlt /
 *      kein Graph) – Aussehen und Verhalten am selben Praedikat
 *   4. POST traegt Frage, Dialekt und AUSWAHL; geprueft -> gruene Pille ZUERST
 *   5. nicht bestanden -> rote Pille, Befunde sichtbar
 *   6. alles vom Server wird MASKIERT (Tabellennamen, Kommentare, SQL)
 *   7. Suche -> Treffer -> Tabellendetail, Kuerzung beziffert
 *   8. Join-Pfad: "kein Pfad" sagt die Schrittzahl
 *   9. Schema-Praefix: Auswahl nur bei mehreren Datenbankschemata der
 *      GEWAEHLTEN Ablagen, POST traegt sie, gemerkt; Mischhinweis mit
 *      "nur X fragen", Zusammengelegtes genannt – alles maskiert
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
function abbruch(t) { console.log('\x1b[31mABBRUCH: ' + t + '\x1b[0m'); process.exit(2); }
process.on('exit', function (code) {
    if (!bilanz && code === 0) { console.log('ABBRUCH: ohne Bilanzzeile'); process.exitCode = 1; }
});
const WACHHUND = setTimeout(function () {
    bilanz = true;
    console.log('✗ Wachhund: der Lauf haengt (>40 s)');
    console.log('\nErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    process.exit(1);
}, 40000);
WACHHUND.unref && WACHHUND.unref();

const lies = function (p) { return fs.readFileSync(path.join(ROOT, p), 'utf8'); };
const HTML = lies('frontend/sql.html');
const JS = { sitzung: lies('frontend/js/sitzung.js'), icons: lies('frontend/js/icons.js'),
             i18n: lies('frontend/js/i18n.js'), sql: lies('frontend/js/sql.js') };

const BOESE = '<img src=x onerror="window.__xss=1">';
function schlaf(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function seite(cfg) {
    cfg = cfg || {};
    // jsdom kann nicht navigieren; das erwartete "Not implemented: navigation"
    // (toPortal) wird ausgeblendet, alles andere bleibt sichtbar.
    const vc = new (require('./lib/jsdom_laden')().VirtualConsole)();
    vc.on('jsdomError', function (e) { if (!/navigation/.test(String(e && e.message))) console.log('jsdom: ' + e); });
    const dom = new JSDOM(HTML, { url: 'https://localhost/sql', runScripts: 'outside-only', virtualConsole: vc });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.localStorage.setItem('jarvis_user', 'anna');
    if (cfg.gemerkt !== undefined) win.localStorage.setItem('jarvis_sql_schemata_anna', JSON.stringify(cfg.gemerkt));
    if (cfg.praefixGemerkt !== undefined) win.localStorage.setItem('jarvis_sql_praefix_anna', cfg.praefixGemerkt);
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
    };
    const gerufen = [];
    function antwort(koerper, status) {
        status = status || 200;
        return Promise.resolve({ ok: status < 400, status: status, json: function () { return Promise.resolve(koerper); } });
    }
    const attrappe = function (url, o) {
        const voll = String(url), p = voll.split('?')[0];
        gerufen.push({ pfad: p, url: voll, opt: o || {} });
        if (p === '/api/me') return antwort({ username: 'anna', permissions: cfg.perm === false ? {} : { schema: true } });
        if (p === '/api/sql/status') return antwort(Object.assign({ ok: true, vorhanden: true, stand: '2026-11-07 10:00:00',
            // Der Dialekt steht JE SCHEMA (seit 2026-11-10), nicht mehr einmal fuer alle
            schemata: [{ id: 'erp', name: 'ERP ' + BOESE, tabellen: 12, sichten: 1, spalten: 99, dialekt: 'postgresql' },
                       { id: 'hr', name: 'Personal', tabellen: 3, sichten: 0, spalten: 9, dialekt: 'mssql' }],
            frage_max: 2000, erfassung_laeuft: false }, cfg.status || {}));
        if (p === '/api/sql/frage' && cfg.netzweg) return Promise.reject(new TypeError('Failed to fetch'));
        if (p === '/api/sql/frage') return antwort(cfg.frage || {}, cfg.frageStatus);
        if (p === '/api/sql/suche') return antwort({ ok: true, treffer: [
            { name: 'erp.kunde', art: 'tabelle', spalten_n: 3, bereich: 'kunde', kommentar: 'Stamm ' + BOESE }] });
        if (p === '/api/sql/tabelle') return antwort(cfg.tabelle || { ok: true, tabelle: {
            name: 'erp.kunde', art: 'tabelle', kommentar: 'Kundenstamm', bereich: null, spalten_gesamt: 250,
            spalten: [{ name: 'id', typ: 'int', pk: true, nullable: false, kommentar: '' },
                      { name: 'nm' + BOESE, typ: 'varchar', pk: false, nullable: true, kommentar: BOESE }],
            raus_gesamt: 1, raus: [{ ziel: 'erp.land', art: 'fk', paare: [['land', 'code']] }],
            rein_gesamt: 0, rein: [] } });
        if (p === '/api/sql/verbindung') return antwort(cfg.pfad || { ok: false, fehler: 'kein_pfad', von: 'a', nach: 'b', max_tiefe: 6 },
            cfg.pfad ? 200 : 404);
        return antwort({ ok: true });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;
    win.eval(JS.sitzung);
    win.eval(JS.icons);
    win.eval(JS.i18n);
    win.eval(JS.sql);
    for (let i = 0; i < 60; i++) {
        await schlaf(5);
        if (gerufen.some(function (g) { return g.pfad === '/api/sql/status'; }) || i > 30) break;
    }
    await schlaf(20);
    return { win: win, doc: win.document, gerufen: gerufen };
}

function tippe(s, id, text) {
    const el = s.doc.getElementById(id);
    if (!el) abbruch('Feld #' + id + ' fehlt');
    el.value = text;
    el.dispatchEvent(new s.win.Event('input', { bubbles: true }));
}
function klick(s, el) {
    if (!el) return false;
    el.dispatchEvent(new s.win.MouseEvent('click', { bubbles: true }));
    return true;
}

(async function () {
    abschnitt('1. Ohne Freigabe');
    let s = await seite({ perm: false });
    check('Seite bleibt verborgen', s.doc.getElementById('sq-app').classList.contains('hidden'));
    check('kein Datenabruf', !s.gerufen.some(function (g) { return g.pfad.indexOf('/api/sql/') === 0; }),
          s.gerufen.map(function (g) { return g.pfad; }));
    s.win.close();

    abschnitt('2. Status');
    s = await seite({});
    const app = s.doc.getElementById('sq-app');
    check('Positivkontrolle: Seite sichtbar', app && !app.classList.contains('hidden'));
    const bar = s.doc.getElementById('sq-schemata');
    const kaesten = bar ? bar.querySelectorAll('input[data-schema]') : [];
    check('Schema-Auswahl nennt beide Schemata als Kaestchen', kaesten.length === 2 && /ERP/.test(bar.textContent)
          && /Personal/.test(bar.textContent), bar && bar.textContent);
    check('Schemaname maskiert (kein img)', !s.doc.querySelector('#sq-schemata img') && !s.win.__xss);
    check('Ohne gemerkte Auswahl: auf /sql alle gewaehlt', Array.prototype.every.call(kaesten, function (k) { return k.checked; }));
    check('Zustand auch als Klasse am Etikett (nicht nur der Haken)',
          s.doc.querySelectorAll('#sq-schemata .sq-schema.is-an').length === 2);
    check('Dialekt-Vorgabe: der des ersten GEWAEHLTEN Schemas', s.doc.getElementById('sq-dialekt').value === 'postgresql',
          s.doc.getElementById('sq-dialekt').value);
    // Der Dialekt gehoert zum Schema: die Vorgabe folgt der Auswahl (eigene Seite,
    // damit die Abwahl die folgenden Abschnitte nicht verstellt)
    const sd = await seite();
    const selD = sd.doc.getElementById('sq-dialekt');
    function schalte(id, an) {
        const cb = sd.doc.querySelector('#sq-schemata input[data-schema="' + id + '"]');
        if (!cb) abbruch('Kaestchen fuer ' + id + ' fehlt');
        cb.checked = an;
        cb.dispatchEvent(new sd.win.Event('change', { bubbles: true }));
    }
    schalte('erp', false);
    check('Erstes Schema abgewaehlt: Vorgabe wechselt auf den Dialekt des verbleibenden (mssql)', selD.value === 'mssql', selD.value);
    schalte('hr', false);
    check('Nichts gewaehlt: allgemein', selD.value === 'allgemein', selD.value);
    schalte('hr', true);
    selD.value = 'mysql';
    selD.dispatchEvent(new sd.win.Event('change', { bubbles: true }));
    schalte('erp', true);
    check('Selbst gewaehlter Dialekt bleibt, auch wenn sich die Auswahl aendert', selD.value === 'mysql', selD.value);
    sd.win.close();

    abschnitt('3. Knopf-Zustand');
    const los = s.doc.getElementById('sq-los');
    check('Ohne Frage gesperrt MIT Grund', los.disabled && /Frage/.test(los.title), los.title);
    tippe(s, 'sq-frage', 'Umsatz je Land');
    check('Mit Frage frei', !los.disabled && los.title === '', los.title);
    // Beide abwaehlen -> gesperrt mit dem RICHTIGEN Grund, und gemerkt
    s.doc.querySelectorAll('#sq-schemata input[data-schema]').forEach(function (k) {
        k.checked = false;
        k.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    });
    check('Nichts gewaehlt -> gesperrt, Grund nennt die Auswahl', los.disabled && /Schema auswählen/.test(los.title), los.title);
    check('... und Hinweis an der Frage sichtbar', /Schema auswählen/.test(s.doc.getElementById('sq-quellen').textContent));
    check('Abwahl wird gemerkt', s.win.localStorage.getItem('jarvis_sql_schemata_anna') === '[]',
          s.win.localStorage.getItem('jarvis_sql_schemata_anna'));
    s.win.close();
    s = await seite({ gemerkt: ['hr', 'geloescht'] });
    const k2 = s.doc.querySelectorAll('#sq-schemata input[data-schema]');
    check('Gemerkte Auswahl gilt, ein geloeschtes Schema faellt weg',
          k2.length === 2 && !k2[0].checked && k2[1].checked && s.win.jarvisSql._gewaehlt().join() === 'hr',
          s.win.jarvisSql && s.win.jarvisSql._gewaehlt());
    tippe(s, 'sq-frage', 'Gehalt');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const post0 = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/frage'; })[0];
    let r0 = null;
    try { r0 = JSON.parse(post0.opt.body); } catch (e) { r0 = null; }
    check('POST traegt GENAU die Auswahl', r0 && JSON.stringify(r0.schemata) === '["hr"]', post0 && post0.opt.body);
    s.win.close();
    s = await seite({ status: { schemata: [] } });
    tippe(s, 'sq-frage', 'Umsatz je Land');
    const los2 = s.doc.getElementById('sq-los');
    check('Ohne Schema gesperrt MIT Grund', los2.disabled && /Schema/.test(los2.title), los2.title);
    check('Hinweis "noch kein Schema angelegt" sichtbar', /kein Schema angelegt/.test(s.doc.getElementById('sq-schemata').textContent));
    s.win.close();
    s = await seite({ status: { vorhanden: false, schemata: [] } });
    tippe(s, 'sq-frage', 'x');
    check('Ohne Graph gesperrt MIT Grund', s.doc.getElementById('sq-los').disabled
          && /Graph/.test(s.doc.getElementById('sq-los').title), s.doc.getElementById('sq-los').title);
    s.win.close();

    abschnitt('4. Geprueftes Ergebnis');
    s = await seite({ frage: { ok: true, dialekt: 'mysql', sql: 'SELECT 1 FROM erp.kunde -- ' + BOESE,
        erklaerung: 'Erkl ' + BOESE, annahmen: 'keine',
        pruefung: { ok: true, fehler: [], tabellen: ['erp.kunde'], spalten_geprueft: 2 },
        tabellen_kontext: ['erp.kunde', 'erp.glied' + BOESE], verbinder: ['erp.glied' + BOESE], unverbunden: [], runden: 1 } });
    s.doc.getElementById('sq-dialekt').value = 'mysql';
    s.doc.getElementById('sq-dialekt').dispatchEvent(new s.win.Event('change', { bubbles: true }));
    tippe(s, 'sq-frage', 'Umsatz je Land');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const post = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/frage'; })[0];
    let rumpf = null;
    try { rumpf = JSON.parse(post.opt.body); } catch (e) { rumpf = null; }
    check('POST mit Frage, Dialekt und Auswahl', post && post.opt.method === 'POST' && rumpf && rumpf.frage === 'Umsatz je Land'
          && rumpf.dialekt === 'mysql' && JSON.stringify(rumpf.schemata) === '["erp","hr"]', post && post.opt.body);
    const erg = s.doc.getElementById('sq-ergebnis');
    check('Ergebnis sichtbar', erg && !erg.classList.contains('hidden'));
    const erstes = erg.firstElementChild;
    check('Pruefstatus ist das ERSTE Element', erstes && erstes.id === 'sq-pill', erstes && erstes.id);
    const pill = s.doc.getElementById('sq-pill');
    check('Gruene Pille mit Text', pill.classList.contains('is-ok') && /Geprüft/.test(pill.textContent), pill.textContent);
    check('SQL als Text (maskiert)', s.doc.getElementById('sq-sql').textContent.indexOf('SELECT 1') === 0
          && !s.doc.querySelector('#sq-sql img'));
    check('Befunde verborgen', s.doc.getElementById('sq-befunde').classList.contains('hidden'));
    check('Annahmen "keine" nicht angezeigt', s.doc.getElementById('sq-annahmen').textContent === '');
    check('Kein Element aus Servertext entstanden', !s.doc.querySelector('#sq-ergebnis img') && !s.win.__xss);
    const glied = s.doc.querySelector('#sq-basis .sq-chip.is-glied');
    check('Join-Glied gekennzeichnet (Zeichen + title)', glied && /↔/.test(glied.textContent) && glied.title, glied && glied.outerHTML);
    check('Knopf nach dem Lauf wieder frei', !s.doc.getElementById('sq-los').disabled);
    s.win.close();

    abschnitt('5. Nicht bestanden');
    s = await seite({ frage: { ok: true, sql: 'DELETE FROM x', erklaerung: '', annahmen: '',
        pruefung: { ok: false, fehler: ['Nicht lesendes Schlüsselwort: DELETE.', BOESE], tabellen: [], spalten_geprueft: 0 },
        tabellen_kontext: [], verbinder: [], unverbunden: [], runden: 3 } });
    tippe(s, 'sq-frage', 'loesche alles');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const pill2 = s.doc.getElementById('sq-pill');
    check('Rote Pille mit Text', pill2.classList.contains('is-bad') && /nicht bestanden/.test(pill2.textContent), pill2.textContent);
    const bef = s.doc.querySelectorAll('#sq-befunde li');
    check('Befunde sichtbar und maskiert', bef.length === 2 && !s.doc.getElementById('sq-befunde').classList.contains('hidden')
          && !s.doc.querySelector('#sq-befunde img'), bef.length);
    s.win.close();

    abschnitt('5b. Gueltig mit Vorbehalt + Hauswissen');
    s = await seite({ frage: { ok: true, sql: 'SELECT 1 FROM erp.kunde k JOIN erp.x p ON p.a = k.b', erklaerung: '', annahmen: '',
        pruefung: { ok: true, fehler: [], tabellen: ['erp.kunde'], spalten_geprueft: 2, unbelegte_joins: ['p.a = k.b ' + BOESE] },
        tabellen_kontext: [], verbinder: [], unverbunden: [], runden: 2,
        hauswissen: [{ titel: 'Konventionen ' + BOESE, nr: 3 }] } });
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const pw = s.doc.getElementById('sq-pill');
    check('Join ohne Beleg: gelbe Pille mit Zeichen UND Text (nicht gruen)', pw.classList.contains('is-warn')
          && !pw.classList.contains('is-ok') && /⚠/.test(pw.textContent) && /ohne Beleg/.test(pw.textContent), pw.outerHTML);
    const bw = s.doc.querySelectorAll('#sq-befunde li');
    check('... die Bedingung steht sichtbar in der Liste, maskiert', bw.length === 1 && /p\.a = k\.b/.test(bw[0].textContent)
          && !s.doc.getElementById('sq-befunde').classList.contains('hidden') && !s.doc.querySelector('#sq-befunde img'), bw.length);
    const hwz = s.doc.getElementById('sq-hauswissen');
    check('Hauswissen: Herkunft genannt (Titel + Abschnitt), maskiert', hwz && /Konventionen/.test(hwz.textContent)
          && /Abschnitt 3/.test(hwz.textContent) && !s.doc.querySelector('#sq-hauswissen img') && !s.win.__xss, hwz && hwz.innerHTML);
    s.win.close();

    abschnitt('5c. Schema-Praefix');
    const MIT_PRAEFIX = { schemata: [
        { id: 'erp', name: 'ERP', tabellen: 12, sichten: 1, spalten: 99,
          praefixe: [{ name: 'ALT', objekte: 5 }, { name: 'NEU', objekte: 7 }] },
        { id: 'hr', name: 'Personal', tabellen: 3, sichten: 0, spalten: 9, praefixe: [{ name: 'NEU', objekte: 2 }] }] };
    const GEMISCHT = { ok: true, sql: 'SELECT 1', erklaerung: '', annahmen: '',
        pruefung: { ok: true, fehler: [], tabellen: [], spalten_geprueft: 0 }, tabellen_kontext: [], verbinder: [],
        unverbunden: [], runden: 1, praefixe: [], praefixe_kontext: { ALT: 5, NEU: 7 }, praefixe_sql: { ALT: 3, NEU: 4 },
        gleichwertig: [{ sicht: 'NEU.S' + BOESE, tabelle: 'NEU.S_T' }] };
    s = await seite({ status: MIT_PRAEFIX, frage: GEMISCHT });
    const psel = s.doc.getElementById('sq-praefix');
    const opts = psel ? Array.prototype.map.call(psel.options, function (o) { return o.value + '=' + o.textContent; }) : [];
    check('Mehrere Datenbankschemata: Auswahl sichtbar, je Praefix summiert, Vorgabe "alle"',
          psel && !psel.classList.contains('hidden') && !s.doc.getElementById('sq-praefix-lbl').classList.contains('hidden')
          && JSON.stringify(opts) === JSON.stringify(['=alle', 'ALT=ALT (5)', 'NEU=NEU (9)']) && psel.value === '', opts);
    klick(s, s.doc.querySelector('#sq-schemata input[data-schema="erp"]'));
    s.doc.querySelector('#sq-schemata input[data-schema="erp"]').checked = false;
    s.doc.querySelector('#sq-schemata input[data-schema="erp"]').dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await schlaf(10);
    check('Nur EIN Datenbankschema in der Auswahl: nichts zu waehlen (verborgen)',
          s.doc.getElementById('sq-praefix').classList.contains('hidden'), s.doc.getElementById('sq-praefix').outerHTML.slice(0, 120));
    const erpK = s.doc.querySelector('#sq-schemata input[data-schema="erp"]');
    erpK.checked = true;
    erpK.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await schlaf(10);
    tippe(s, 'sq-frage', 'Faelle je Art');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const fposts = function () { return s.gerufen.filter(function (g) { return g.pfad === '/api/sql/frage'; }); };
    let pr0 = null;
    try { pr0 = JSON.parse(fposts()[0].opt.body); } catch (e) { pr0 = null; }
    check('Ohne Wahl: POST traegt praefixe []', pr0 && JSON.stringify(pr0.praefixe) === '[]', pr0 && JSON.stringify(pr0));
    const hin = s.doc.getElementById('sq-hinweise');
    const knoepfe = hin ? hin.querySelectorAll('button[data-praefix]') : [];
    check('Gemischter Ausschnitt: Hinweis nennt beide mit Anzahl, je ein Knopf',
          hin && /ALT \(3\)/.test(hin.textContent) && /NEU \(4\)/.test(hin.textContent) && knoepfe.length === 2
          && /nur ALT fragen/.test(knoepfe[0].textContent), hin && hin.innerHTML.slice(0, 300));
    check('Zusammengelegtes genannt, maskiert', hin && /zeigt alle Spalten von NEU\.S_T/.test(hin.textContent)
          && !s.doc.querySelector('#sq-hinweise img') && !s.win.__xss, hin && hin.textContent);
    klick(s, knoepfe[0]);
    await schlaf(40);
    let pr1 = null;
    try { pr1 = JSON.parse(fposts()[1].opt.body); } catch (e) { pr1 = null; }
    check('"nur ALT fragen": neue Frage mit praefixe ["ALT"], Auswahl steht auf ALT, gemerkt',
          pr1 && JSON.stringify(pr1.praefixe) === '["ALT"]' && s.doc.getElementById('sq-praefix').value === 'ALT'
          && s.win.localStorage.getItem('jarvis_sql_praefix_anna') === 'ALT', pr1 && JSON.stringify(pr1));
    s.win.close();
    s = await seite({ status: MIT_PRAEFIX, praefixGemerkt: 'NEU',
                      frage: Object.assign({}, GEMISCHT, { praefixe: ['NEU'], praefixe_sql: { ALT: 1, NEU: 4 }, gleichwertig: [] }) });
    check('Gemerkter Praefix gilt beim Laden', s.doc.getElementById('sq-praefix').value === 'NEU', s.doc.getElementById('sq-praefix').value);
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const hin2 = s.doc.getElementById('sq-hinweise');
    check('Mit Wahl: Hinweis "eingegrenzt", kein Mischhinweis', /Eingegrenzt auf das Datenbankschema NEU/.test(hin2.textContent)
          && !hin2.querySelector('button[data-praefix]'), hin2.textContent);
    s.win.close();
    // Ausschnitt gemischt, SQL aus EINEM Schema: kein Hinweis (sonst stuende er
    // am echten Bestand bei fast jeder Frage)
    s = await seite({ status: MIT_PRAEFIX, frage: Object.assign({}, GEMISCHT, { praefixe_sql: { NEU: 2 }, gleichwertig: [] }) });
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const hin3 = s.doc.getElementById('sq-hinweise');
    check('Nur der Ausschnitt gemischt, das SQL nicht: kein Mischhinweis', hin3 && hin3.textContent === ''
          && !hin3.querySelector('button[data-praefix]'), hin3 && hin3.innerHTML);
    s.win.close();
    // Gemerkter Praefix, den es nicht mehr gibt: "alle" (das DOM haelt das schon
    // selbst – ein unbekannter Wert ist keine Option; geprueft wird die Wirkung)
    s = await seite({ status: MIT_PRAEFIX, praefixGemerkt: 'WEG', frage: GEMISCHT });
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    let prw = null;
    try { prw = JSON.parse(s.gerufen.filter(function (g) { return g.pfad === '/api/sql/frage'; })[0].opt.body); } catch (e) { prw = null; }
    check('Gemerkter, verschwundener Praefix: Auswahl "alle", POST praefixe []',
          s.doc.getElementById('sq-praefix').value === '' && prw && JSON.stringify(prw.praefixe) === '[]', prw && JSON.stringify(prw));
    s.win.close();
    s = await seite({ praefixGemerkt: 'WEG', frage: GEMISCHT });
    check('Aelterer Server ohne praefixe: Auswahl verborgen, gemerkter Wert greift nicht',
          s.doc.getElementById('sq-praefix').classList.contains('hidden'));
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    let pr2 = null;
    try { pr2 = JSON.parse(s.gerufen.filter(function (g) { return g.pfad === '/api/sql/frage'; })[0].opt.body); } catch (e) { pr2 = null; }
    check('... und der POST traegt praefixe []', pr2 && JSON.stringify(pr2.praefixe) === '[]', pr2 && JSON.stringify(pr2));
    s.win.close();

    abschnitt('6. Fehler vom Server bleibt stehen');
    s = await seite({ frage: { error: 'Es läuft bereits eine Frage von dir – bitte warten.' }, frageStatus: 429 });
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const fs1 = s.doc.getElementById('sq-frage-status');
    check('Fehlertext aus `error` angezeigt', /bereits eine Frage/.test(fs1.textContent), fs1.textContent);
    await schlaf(3700);   // laenger als die 3,5 s, nach denen ein Erfolg verschwindet
    check('... und bleibt stehen (auch nach 3,7 s)', /bereits eine Frage/.test(fs1.textContent));
    s.win.close();

    abschnitt('6b. Keine Antwort vom Server (Netzfehler)');
    s = await seite({ netzweg: true });
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    const nf = s.doc.getElementById('sq-frage-status').textContent;
    check('Statt "Failed to fetch": Meldung mit Pfad und Uhrzeit', /Keine Antwort vom Server/.test(nf)
          && /\/api\/sql\/frage/.test(nf) && /\d{1,2}:\d{2}/.test(nf) && !/Failed to fetch/.test(nf), nf);
    check('... und der Knopf ist wieder frei', !s.doc.getElementById('sq-los').disabled);
    s.win.close();

    abschnitt('7. Suche und Detail');
    s = await seite({});
    tippe(s, 'sq-suchfeld', 'kunde');
    klick(s, s.doc.getElementById('sq-suchen'));
    await schlaf(30);
    const such = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/suche'; })[0];
    check('Suche traegt die Auswahl', such && /schemata=erp%2Chr/.test(such.url), such && such.url);
    const tr = s.doc.querySelectorAll('#sq-treffer .sq-treffer');
    check('Treffer gezeichnet', tr.length === 1, tr.length);
    check('Treffer maskiert', !s.doc.querySelector('#sq-treffer img'));
    klick(s, tr[0]);
    await schlaf(30);
    const tabRuf = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/tabelle'; })[0];
    check('Klick holt das Detail (mit Auswahl)', tabRuf && /name=erp\.kunde/.test(tabRuf.url)
          && /schemata=erp%2Chr/.test(tabRuf.url), tabRuf && tabRuf.url);
    const det = s.doc.getElementById('sq-detail');
    check('Kuerzung beziffert VOR der Tabelle', /2 von 250/.test(det.textContent)
          && det.textContent.indexOf('2 von 250') < det.textContent.indexOf('Kundenstamm') + 200, det.textContent.slice(0, 200));
    check('Detail maskiert', !s.doc.querySelector('#sq-detail img') && !s.win.__xss);
    const ver = s.doc.querySelector('#sq-detail .sq-chip[data-tabelle="erp.land"]');
    check('Verweis als klickbarer Chip mit Bedingung', ver && /land = code/.test(ver.title), ver && ver.outerHTML);
    s.win.close();

    abschnitt('8. Join-Pfad');
    s = await seite({});
    tippe(s, 'sq-von', 'a');
    tippe(s, 'sq-nach', 'b');
    klick(s, s.doc.getElementById('sq-pfad-los'));
    await schlaf(30);
    const pr = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/verbindung'; })[0];
    check('Join-Pfad traegt die Auswahl', pr && /schemata=erp%2Chr/.test(pr.url), pr && pr.url);
    const ps = s.doc.getElementById('sq-pfad-status');
    check('"kein Pfad" nennt die Schrittzahl', /6 Schritten/.test(ps.textContent), ps.textContent);
    s.win.close();
    s = await seite({ pfad: { ok: true, von: 'a', nach: 'b', schritte: [
        { von: 'a', nach: 'k', bedingung: 'a.k_id = k.id', art: 'fk' },
        { von: 'k', nach: 'b', bedingung: 'k.b_id = b.id', art: 'abgeleitet' }] } });
    tippe(s, 'sq-von', 'a');
    tippe(s, 'sq-nach', 'b');
    klick(s, s.doc.getElementById('sq-pfad-los'));
    await schlaf(30);
    const schritte = s.doc.querySelectorAll('#sq-pfad .sq-treffer');
    check('Zwei Schritte, der vermutete gekennzeichnet', schritte.length === 2 && /vermutet/.test(schritte[1].textContent)
          && !/vermutet/.test(schritte[0].textContent), schritte.length);
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
