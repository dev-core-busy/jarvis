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
 *  10. Syntax: "nicht verfuegbar" ist eine eigene Stufe (keine gruene Pille),
 *      ein Syntaxfehler kippt die Pille, ein Dialekt ohne eigenen Pruefer
 *      zeigt Hinweise statt Fehler – alles maskiert
 *  11. Bearbeiten kippt die Anzeige auf "geaendert"; "Syntax pruefen" schickt
 *      GENAU den Feldinhalt mit Dialekt und Auswahl; "Eigenes SQL pruefen"
 *      leert das Feld, Knopf gesperrt MIT Grund
 *  12. Verlauf (je Benutzer im Browser): Eintrag nach einer Frage mit Frage,
 *      Dialekt, Schemata, Praefix und SQL; Klick stellt alles wieder her und
 *      prueft automatisch neu (ohne Modell); Muelleimer loescht GENAU einen;
 *      fehlende Schemata werden benannt
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
// Antwortform von main._sql_pruefung_antwort
const SYN_OK = { verfuegbar: true, ok: true, fehler: [], hinweise: [], ersatz: false, dialekt: 'mysql' };
const PR_OK = { ok: true, fehler: [], tabellen: ['erp.kunde'], spalten_geprueft: 2, unbelegte_joins: [], joins_belegt: 0,
                syntax: SYN_OK };
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
    if (cfg.verlauf !== undefined) win.localStorage.setItem('jarvis_sql_verlauf_anna', JSON.stringify(cfg.verlauf));
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
        if (p === '/api/sql/pruefen') return antwort(cfg.pruefen || { ok: true, dialekt: 'mysql', pruefung: PR_OK });
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
        pruefung: { ok: true, fehler: [], tabellen: ['erp.kunde'], spalten_geprueft: 2, syntax: SYN_OK },
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
    check('SQL im Feld (als Wert, nicht als Markup)', s.doc.getElementById('sq-sql').value.indexOf('SELECT 1') === 0
          && !s.doc.querySelector('#sq-sql img'));
    check('Syntaxzeile nennt den Dialekt', /Syntax in Ordnung \(mysql\)/.test(s.doc.getElementById('sq-syntax').textContent),
          s.doc.getElementById('sq-syntax').textContent);
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

    abschnitt('10. Syntax-Anzeige');
    const FR = function (pr) {
        return { frage: { ok: true, dialekt: 'hana', sql: 'SELECT 1 FROM erp.kunde', erklaerung: '', annahmen: '',
            pruefung: pr, tabellen_kontext: ['erp.kunde'], verbinder: [], unverbunden: [], runden: 1 } };
    };
    // (a) Pruefer fehlt: eigene Stufe, NICHT gruen
    s = await seite(FR(Object.assign({}, PR_OK, { syntax: { verfuegbar: false, ok: null, fehler: [], hinweise: [], ersatz: false, dialekt: 'hana' } })));
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    let pl = s.doc.getElementById('sq-pill');
    check('Ohne Syntaxpruefer: KEINE gruene Pille, Text sagt es', !pl.classList.contains('is-ok') && pl.classList.contains('is-warn')
          && /Syntax nicht geprüft/.test(pl.textContent), pl.className + ' ' + pl.textContent);
    check('Ohne Syntaxpruefer: Syntaxzeile nennt den Grund', /nicht installiert/.test(s.doc.getElementById('sq-syntax').textContent));
    s.win.close();
    // (b) Syntaxfehler: rote Pille, Befund maskiert sichtbar
    s = await seite(FR({ ok: false, fehler: ['Syntax – Zeile 1, Spalte 9: Überzähliges Komma vor FROM ' + BOESE + '.'],
        tabellen: [], spalten_geprueft: 0, unbelegte_joins: [], joins_belegt: 0,
        syntax: { verfuegbar: true, ok: false, fehler: [{ text: 'Überzähliges Komma vor FROM', zeile: 1, spalte: 9, stelle: 'FROM' }],
                  hinweise: [], ersatz: false, dialekt: 'postgresql' } }));
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    pl = s.doc.getElementById('sq-pill');
    check('Syntaxfehler: rote Pille', pl.classList.contains('is-bad') && /nicht bestanden/.test(pl.textContent), pl.textContent);
    check('Syntaxfehler: Zeile mit ✗ und Dialekt', /✗ Syntaxfehler \(postgresql\)/.test(s.doc.getElementById('sq-syntax').textContent),
          s.doc.getElementById('sq-syntax').textContent);
    const bf = s.doc.getElementById('sq-befunde');
    check('Syntaxfehler: Befund sichtbar und maskiert', !bf.classList.contains('hidden') && /Überzähliges Komma/.test(bf.textContent)
          && !bf.querySelector('img') && !s.win.__xss);
    s.win.close();
    // (c) Dialekt ohne eigenen Pruefer: gueltig, Hinweis statt Fehler
    s = await seite(FR(Object.assign({}, PR_OK, { syntax: { verfuegbar: true, ok: true, fehler: [], ersatz: true, dialekt: 'hana',
        hinweise: [{ text: 'Unerwartetes Wort ' + BOESE, zeile: 2, spalte: 5, stelle: 'TOP' }] } })));
    tippe(s, 'sq-frage', 'x');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    pl = s.doc.getElementById('sq-pill');
    check('Ersatz-Pruefer: Pille gruen', pl.classList.contains('is-ok'), pl.className);
    check('Ersatz-Pruefer: Zeile sagt "als Standard-SQL"', /Standard-SQL geprüft – für hana/.test(s.doc.getElementById('sq-syntax').textContent),
          s.doc.getElementById('sq-syntax').textContent);
    const bf2 = s.doc.getElementById('sq-befunde');
    check('Ersatz-Pruefer: Hinweis mit Ort sichtbar, maskiert', !bf2.classList.contains('hidden') && /Hinweis des Standard-SQL-Prüfers/.test(bf2.textContent)
          && /2:5/.test(bf2.textContent) && !bf2.querySelector('img') && !s.win.__xss, bf2.textContent);
    s.win.close();

    abschnitt('11. Bearbeiten und "Syntax pruefen"');
    s = await seite({ frage: { ok: true, dialekt: 'mysql', sql: 'SELECT 1 FROM erp.kunde', erklaerung: '', annahmen: '',
        pruefung: PR_OK, tabellen_kontext: ['erp.kunde'], verbinder: [], unverbunden: [], runden: 1 },
        pruefen: { ok: true, dialekt: 'mysql', pruefung: { ok: false, fehler: ['Syntax – Zeile 1: Schließende Klammer fehlt.'],
            tabellen: [], spalten_geprueft: 0, unbelegte_joins: [], joins_belegt: 0,
            syntax: { verfuegbar: true, ok: false, fehler: [{ text: 'Schließende Klammer fehlt', zeile: 1, spalte: 20, stelle: '' }],
                      hinweise: [], ersatz: false, dialekt: 'mysql' } } } });
    s.doc.getElementById('sq-dialekt').value = 'mysql';
    s.doc.getElementById('sq-dialekt').dispatchEvent(new s.win.Event('change', { bubbles: true }));
    tippe(s, 'sq-frage', 'Kunden');
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    check('Positivkontrolle: gepruefte Pille', s.doc.getElementById('sq-pill').classList.contains('is-ok'));
    tippe(s, 'sq-sql', 'SELECT (1 FROM erp.kunde');
    pl = s.doc.getElementById('sq-pill');
    check('Bearbeitet: Pille neutral "Geändert – noch nicht geprüft"', !/is-(ok|bad|warn)/.test(pl.className)
          && /Geändert – noch nicht geprüft/.test(pl.textContent), pl.className + ' ' + pl.textContent);
    check('Bearbeitet: Syntaxzeile leer', s.doc.getElementById('sq-syntax').textContent === '');
    const pk = s.doc.getElementById('sq-pruefen');
    check('Pruefknopf frei', !pk.disabled, pk.title);
    klick(s, pk);
    await schlaf(40);
    const pp = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/pruefen'; });
    let prRumpf = null;
    try { prRumpf = JSON.parse(pp[0].opt.body); } catch (e) { prRumpf = null; }
    check('POST /api/sql/pruefen mit GENAU dem Feldinhalt, Dialekt und Auswahl', pp.length === 1 && prRumpf
          && prRumpf.sql === 'SELECT (1 FROM erp.kunde' && prRumpf.dialekt === 'mysql' && JSON.stringify(prRumpf.schemata) === '["erp","hr"]',
          pp.length + ' ' + (pp[0] && pp[0].opt.body));
    pl = s.doc.getElementById('sq-pill');
    check('Nach der Pruefung: rote Pille', pl.classList.contains('is-bad'), pl.className);
    // Rueckweg ohne erneute Pruefung: zurueck auf den gepruefte Text zeigt KEIN "geaendert"
    tippe(s, 'sq-sql', 'SELECT (1 FROM erp.kunde');
    check('Unveraenderter Text bleibt "geprueft"', s.doc.getElementById('sq-pill').classList.contains('is-bad'));
    // Dialektwechsel macht die Anzeige ungueltig
    s.doc.getElementById('sq-dialekt').value = 'oracle';
    s.doc.getElementById('sq-dialekt').dispatchEvent(new s.win.Event('change', { bubbles: true }));
    check('Dialektwechsel: Anzeige "geaendert"', /Geändert/.test(s.doc.getElementById('sq-pill').textContent));
    // Eigenes SQL: Feld leer, Knopf gesperrt MIT Grund, nach Tippen frei
    klick(s, s.doc.getElementById('sq-eigenes'));
    check('Eigenes SQL: Feld leer, Ergebnis sichtbar', s.doc.getElementById('sq-sql').value === ''
          && !s.doc.getElementById('sq-ergebnis').classList.contains('hidden'));
    check('Eigenes SQL: keine alte Grundlage', s.doc.getElementById('sq-basis').innerHTML === '');
    check('Eigenes SQL: Pruefknopf gesperrt MIT Grund', pk.disabled && /SQL eingeben/.test(pk.title), pk.title);
    check('Eigenes SQL: Pille "Noch nicht geprüft"', /Noch nicht geprüft/.test(s.doc.getElementById('sq-pill').textContent));
    tippe(s, 'sq-sql', 'SELECT 2 FROM erp.kunde');
    check('Eigenes SQL: nach Tippen frei', !pk.disabled);
    s.win.close();

    abschnitt('12. Verlauf');
    s = await seite({ frage: { ok: true, dialekt: 'mysql', sql: 'SELECT 1 FROM erp.kunde', erklaerung: 'E', annahmen: '',
        pruefung: PR_OK, tabellen_kontext: ['erp.kunde'], verbinder: [], unverbunden: [], runden: 1 } });
    s.doc.getElementById('sq-dialekt').value = 'mysql';
    s.doc.getElementById('sq-dialekt').dispatchEvent(new s.win.Event('change', { bubbles: true }));
    tippe(s, 'sq-frage', 'Umsatz ' + BOESE);
    klick(s, s.doc.getElementById('sq-los'));
    await schlaf(40);
    let vl = [];
    try { vl = JSON.parse(s.win.localStorage.getItem('jarvis_sql_verlauf_anna') || '[]'); } catch (e) { vl = []; }
    const e0 = vl[0] || {};
    check('Eintrag je Benutzer mit Frage, Dialekt, Schemata, SQL und Pruefung', vl.length === 1 && e0.q === 'Umsatz ' + BOESE
          && e0.dialekt === 'mysql' && JSON.stringify(e0.schemata) === '["erp","hr"]' && e0.erg && e0.erg.sql === 'SELECT 1 FROM erp.kunde'
          && e0.erg.pruefung && e0.erg.pruefung.ok === true, JSON.stringify(e0).slice(0, 200));
    check('Schemanamen gemerkt', e0.schemata_namen && e0.schemata_namen[1] === 'Personal');
    check('Keine Laufzeiten/Rundenverlauf im Speicher', e0.erg && !('zeiten' in e0.erg) && !('verlauf' in e0.erg));
    klick(s, s.doc.getElementById('sq-hist-btn'));
    const panel = s.doc.getElementById('sq-hist-panel');
    check('Verlaufsfeld oeffnet', !panel.classList.contains('hidden'));
    const it = s.doc.querySelectorAll('#sq-hist-list .sq-hist-item');
    check('Eintrag gezeichnet, maskiert, mit Muelleimer', it.length === 1 && /Umsatz/.test(it[0].textContent)
          && !s.doc.querySelector('#sq-hist-list img') && !s.win.__xss && it[0].querySelector('.sq-hist-del svg'), it.length);
    // Bearbeitet + geprueft -> der Eintrag haelt den Arbeitsstand
    klick(s, s.doc.body);
    tippe(s, 'sq-sql', 'SELECT 3 FROM erp.kunde');
    klick(s, s.doc.getElementById('sq-pruefen'));
    await schlaf(40);
    try { vl = JSON.parse(s.win.localStorage.getItem('jarvis_sql_verlauf_anna') || '[]'); } catch (e) { vl = []; }
    check('Gepruefte Bearbeitung ersetzt das SQL des Eintrags (kein neuer)', vl.length === 1 && vl[0].erg.sql === 'SELECT 3 FROM erp.kunde'
          && vl[0].bearbeitet === true, JSON.stringify(vl).slice(0, 200));
    s.win.close();

    // Wiederherstellen in einer frischen Seite: zwei Eintraege, einer mit verschwundenem Schema
    const VERLAUF = [
        { ts: 2000, q: 'Zweite Frage', dialekt: 'oracle', schemata: ['hr', 'weg'], schemata_namen: ['Personal', 'Altbestand'],
          praefix: '', bearbeitet: false, erg: { sql: 'SELECT 9 FROM hr.x', dialekt: 'oracle', pruefung: PR_OK,
          erklaerung: '', annahmen: '', hauswissen: [], tabellen_kontext: ['hr.x'], verbinder: [] } },
        { ts: 1000, q: 'Erste Frage', dialekt: 'mssql', schemata: ['erp'], schemata_namen: ['ERP'], praefix: '',
          bearbeitet: false, erg: { sql: 'SELECT 8 FROM erp.kunde', dialekt: 'mssql', pruefung: PR_OK, erklaerung: 'Alt',
          annahmen: '', hauswissen: [], tabellen_kontext: ['erp.kunde'], verbinder: [] } }];
    s = await seite({ verlauf: VERLAUF });
    klick(s, s.doc.getElementById('sq-hist-btn'));
    let items = s.doc.querySelectorAll('#sq-hist-list .sq-hist-item');
    check('Positivkontrolle: zwei Eintraege gezeichnet', items.length === 2, items.length);
    klick(s, items[1]);
    await schlaf(40);
    check('Klick: Frage zurueck', s.doc.getElementById('sq-frage').value === 'Erste Frage');
    check('Klick: Dialekt zurueck', s.doc.getElementById('sq-dialekt').value === 'mssql', s.doc.getElementById('sq-dialekt').value);
    check('Klick: Auswahl zurueck und gemerkt', JSON.stringify(s.win.jarvisSql._gewaehlt()) === '["erp"]'
          && s.win.localStorage.getItem('jarvis_sql_schemata_anna') === '["erp"]', JSON.stringify(s.win.jarvisSql._gewaehlt()));
    check('Klick: SQL und Erklaerung zurueck', s.doc.getElementById('sq-sql').value === 'SELECT 8 FROM erp.kunde'
          && /Alt/.test(s.doc.getElementById('sq-erklaerung').textContent));
    check('Klick: Verlaufsfeld schliesst', s.doc.getElementById('sq-hist-panel').classList.contains('hidden'));
    const auto = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/pruefen'; });
    let ab = null;
    try { ab = JSON.parse(auto[0].opt.body); } catch (e) { ab = null; }
    check('Klick: automatische Neupruefung gegen heute (ohne Modell)', auto.length === 1 && ab && ab.sql === 'SELECT 8 FROM erp.kunde'
          && ab.dialekt === 'mssql' && JSON.stringify(ab.schemata) === '["erp"]', auto.length);
    check('Klick: KEINE neue Frage an das Modell', !s.gerufen.some(function (g) { return g.pfad === '/api/sql/frage'; }));
    check('Klick: Hinweis nennt den Verlauf', /Aus dem Verlauf/.test(s.doc.getElementById('sq-frage-status').textContent));
    klick(s, s.doc.getElementById('sq-hist-btn'));
    items = s.doc.querySelectorAll('#sq-hist-list .sq-hist-item');
    klick(s, items[0]);
    await schlaf(40);
    const fst = s.doc.getElementById('sq-frage-status');
    check('Verschwundenes Schema wird BENANNT, vorhandenes gewaehlt', /Altbestand/.test(fst.textContent) && fst.classList.contains('is-fehler')
          && JSON.stringify(s.win.jarvisSql._gewaehlt()) === '["hr"]', fst.textContent);
    // Muelleimer loescht GENAU den angeklickten Eintrag und uebernimmt nichts
    klick(s, s.doc.getElementById('sq-hist-btn'));
    const vorFrage = s.doc.getElementById('sq-frage').value;
    const del = s.doc.querySelector('#sq-hist-list .sq-hist-del[data-ts="1000"]');
    klick(s, del);
    try { vl = JSON.parse(s.win.localStorage.getItem('jarvis_sql_verlauf_anna') || '[]'); } catch (e) { vl = []; }
    check('Muelleimer: genau dieser Eintrag weg', vl.length === 1 && vl[0].ts === 2000, JSON.stringify(vl.map(function (x) { return x.ts; })));
    check('Muelleimer: nichts uebernommen, Feld bleibt offen', s.doc.getElementById('sq-frage').value === vorFrage
          && !s.doc.getElementById('sq-hist-panel').classList.contains('hidden'));
    klick(s, s.doc.getElementById('sq-hist-clear'));
    check('Leeren: Verlauf leer', !s.win.localStorage.getItem('jarvis_sql_verlauf_anna')
          && /Noch keine Fragen/.test(s.doc.getElementById('sq-hist-list').textContent));
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
