/* Waechter: Einstellungen → SQL-Assistent (sql_admin.js) – am ECHTEN Markup.
 *
 * Das Panel wird aus der ECHTEN settings.html geschnitten (zwischen
 * `id="settings-tab-sql"` und dem naechsten Reiter) und mit den echten
 * Modulen (sitzung.js, icons.js, i18n.js, sql_admin.js) belebt. Dass das
 * Skript in settings.html eingebunden ist, prueft test_schema_graph_zugang.py
 * als REGEL – ein UI-Waechter, der seine Skripte selbst laedt, kann das nicht.
 *
 * Seit 2026-11-07: Schemata mit fester Ablage, Upload per Ablagefeld (Dateien,
 * Ordner, ZIP), Dateiliste mit Loeschen, KEINE Ordner- und Gruppenfelder.
 *
 * Geprueft wird die EIGENSCHAFT:
 *   1. Schemata aus der Server-Antwort, maskiert, mit Zahlen; ein noch nicht
 *      gespeichertes Schema hat KEIN Ablagefeld (es hat noch keinen Ordner)
 *   2. Upload ueber das Dateifeld: gefiltert nach Dateimustern (+ZIP, ohne
 *      Versteckte), relative Pfade im Feld `pfade`, Ergebnis + Ablehnungen
 *      maskiert sichtbar, danach neu geladen; der Klick aufs Ablagefeld oeffnet
 *      den Dateidialog GENAU einmal
 *   3. Ordner per Ziehen: Verzeichnis-Eintraege werden REKURSIV und bis zum
 *      leeren Stueck gelesen, die Ordnerstruktur bleibt im Pfad
 *   4. Pakete: hoechstens PAKET_DATEIEN bzw. PAKET_BYTES je Anfrage
 *   5. Dateiliste: aufklappen, Kuerzung beziffert, Loeschen nur nach Rueckfrage
 *   6. Schema entfernen: 409 -> Rueckfrage mit Name und Dateizahl -> erneut mit
 *      Bestaetigung; abgelehnt -> nichts geloescht, Grund steht da
 *   7. Speichern: 400 -> Fehlerliste maskiert, bleibt stehen
 *   8. Erfassung JE SCHEMA: Start am Schema -> Fortschritt und Abbrechen nur
 *      DORT, das andere Schema bleibt frei; Vormerkung; Ende -> Neuladen, ohne
 *      eine ungespeicherte Eingabe zu verlieren
 *   9. Seit 2026-11-10: je Schema EIN CONTAINER (Klapp-Kopfzeile wie die
 *      uebrigen Abschnitte), und Dialekt, Dateimuster, Beziehungen und
 *      Hoechstzahlen stehen DARIN – gespeichert je Schema, nie auf oberster
 *      Ebene; fuer alle gemeinsam nur Leseprozesse und Chat-Erlaubnis
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
    console.log('✗ Wachhund (>50 s)');
    console.log('\nErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    process.exit(1);
}, 50000);
WACHHUND.unref && WACHHUND.unref();

const lies = function (p) { return fs.readFileSync(path.join(ROOT, p), 'utf8'); };
const SETTINGS = lies('frontend/settings.html');
const a = SETTINGS.indexOf('<div id="settings-tab-sql"');
const b = SETTINGS.indexOf('<div id="settings-tab-tracks"');
if (a < 0 || b < 0 || b < a) abbruch('Panel #settings-tab-sql in settings.html nicht gefunden');
const PANEL = SETTINGS.slice(a, b).replace('id="settings-tab-sql" class="settings-tab-content" style="display:none;"',
                                           'id="settings-tab-sql" class="settings-tab-content"');
const JS = { sitzung: lies('frontend/js/sitzung.js'), icons: lies('frontend/js/icons.js'),
             i18n: lies('frontend/js/i18n.js'), adm: lies('frontend/js/sql_admin.js') };
const BOESE = '<img src=x onerror="window.__xss=1">';
function schlaf(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

// Zwei Schemata, die sich in JEDER Einstellung unterscheiden – sonst waere
// "je Schema" von "fuer alle" nicht zu unterscheiden.
function cfg0() {
    return { schemata: [
        { id: 'erp', name: 'ERP ' + BOESE, dialekt: 'oracle', dateimuster: '*.sql,*.ddl', fk_ableiten: true,
          max_tabellen: 12, max_spalten: 40 },
        { id: 'hr', name: 'Personal', dialekt: 'mssql', dateimuster: '*.yaml', fk_ableiten: false,
          max_tabellen: 20, max_spalten: 60 }],
        prozesse: 3, index_aus_chat: false };
}
const VORGABEN = { dialekt: 'allgemein', dateimuster: '*.sql,*.ddl,*.yaml,*.yml', fk_ableiten: true,
                   max_tabellen: 12, max_spalten: 40 };
// Letzter Lauf: NUR fuer erp bekannt – ueber hr weiss der Status nichts.
function ruhe() {
    return { laeuft: false, ergebnis: 'fertig', ende: '2026-11-07', dateien_gesamt: 3, dateien_neu: 1, schemata: ['erp'],
             je_schema: { erp: { ergebnis: 'fertig', ende: '2026-11-07 10:00:00', dateien_gesamt: 3, dateien_neu: 1,
                                 fehler: [], ausgelassen: [] } } };
}
function imLauf(sid, fertig) {
    const je = ruhe().je_schema;
    je[sid] = { ergebnis: '', ende: null, dateien_gesamt: 9, dateien_neu: 4, dateien_fertig: fertig, bytes_neu: 100,
                bytes_fertig: 25 * fertig, fehler: [], ausgelassen: [] };
    return { laeuft: true, phase: 'Dateien zerlegen', schemata: [sid], dateien_fertig: fertig, dateien_neu: 4,
             bytes_fertig: 25 * fertig, bytes_neu: 100, mb_pro_s: 12.5, je_schema: je };
}
function nachLauf(sid) {
    const st = ruhe();
    st.schemata = [sid];
    st.je_schema[sid] = { ergebnis: 'unveraendert', ende: '2026-11-10 09:00:00', dateien_gesamt: 9, dateien_neu: 4,
                          fehler: [], ausgelassen: [] };
    return st;
}

async function seite(opt) {
    opt = opt || {};
    const dom = new JSDOM('<!DOCTYPE html><html><body>' + PANEL + '</body></html>',
                          { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    const gerufen = [], hoch = [], fragen = [];
    // ``lauf``: Kennung des Schemas, das gerade erfasst wird (oder null);
    // ``wartet``: Kennungen mit vorgemerktem Nachlauf; ``fertig``: zuletzt erfasst
    const zustand = { cfg: cfg0(), lauf: null, wartet: null, fertig: null, polls: 0, puts: 0, pollsBisEnde: 2 };
    function erfStand() {
        return zustand.lauf ? imLauf(zustand.lauf, zustand.polls ? 2 : 0) : zustand.fertig ? nachLauf(zustand.fertig) : ruhe();
    }
    function vorgemerkt() { return zustand.wartet ? { nur: zustand.wartet.slice() } : null; }
    win.confirm = function (t) { fragen.push(t); return opt.bestaetigen !== false; };
    function antwort(k, st) {
        st = st || 200;
        return Promise.resolve({ ok: st < 400, status: st, json: function () { return Promise.resolve(k); } });
    }
    const attrappe = function (url, o) {
        const voll = String(url), p = voll.split('?')[0];
        o = o || {};
        gerufen.push({ pfad: p, url: voll, methode: o.method || 'GET', body: o.body });
        if (p === '/api/sql/admin' && (o.method || 'GET') === 'GET') {
            // ``getLangsam``: die Antwort kommt erst nach 60 ms (ein Nachladen,
            // das von einem Speichern ueberholt wird) – mit dem Stand von DANN.
            if (zustand.getLangsam) {
                zustand.getLangsam = false;
                return new Promise(function (fertig) { setTimeout(function () { fertig(attrappe(url, o)); }, 60); });
            }
            return antwort({ ok: true, cfg: JSON.parse(JSON.stringify(zustand.cfg)),
                graph: { vorhanden: true, stand: '2026-11-07', schemata: [{ id: 'erp', name: 'ERP', tabellen: 5, sichten: 1, spalten: 30, dokumente: 2 }] },
                upload_endungen: { erp: ['.ddl', '.docx', '.md', '.pdf', '.sql'], hr: ['.docx', '.md', '.pdf', '.yaml'] },
                schema_vorgaben: JSON.parse(JSON.stringify(VORGABEN)),
                dateien: { erp: { dateien: 3, ordner: 1, bytes: 2 * 1024 * 1024 }, hr: { dateien: 0, ordner: 0, bytes: 0 } },
                erfassung: erfStand(), vorgemerkt: vorgemerkt(),
                skill_aktiv: true });
        }
        if (p === '/api/sql/admin' && o.method === 'PUT' && opt.netzweg) return Promise.reject(new TypeError('Failed to fetch'));
        if (p === '/api/sql/admin' && o.method === 'PUT') {
            zustand.puts++;
            if (opt.speichernFehler) return antwort({ error: 'Nicht gespeichert: x', fehler: ['Schema „X“: ' + BOESE] }, 400);
            const rumpf = JSON.parse(o.body);
            const neu = rumpf.cfg;
            const weg = zustand.cfg.schemata.filter(function (s) { return !neu.schemata.some(function (n) { return n.id === s.id; }); });
            if (weg.length && rumpf.loeschen_bestaetigt !== true) {
                return antwort({ error: 'bitte bestätigen', zu_loeschen: weg }, 409);
            }
            neu.schemata.forEach(function (s, i) { if (!s.id) s.id = 'neu' + i; });
            // Wie der Server: neu erfasst wird, wessen Dateimuster sich aendert
            const erfasst = neu.schemata.filter(function (n) {
                const a = zustand.cfg.schemata.filter(function (x) { return x.id === n.id; })[0];
                return a && (a.dateimuster !== n.dateimuster || a.fk_ableiten !== n.fk_ableiten);
            }).map(function (n) { return n.id; });
            zustand.cfg = neu;
            if (erfasst.length) zustand.lauf = erfasst[0];
            return antwort({ ok: true, cfg: neu, hinweise: ['Hinweis A'], erfasst: erfasst });
        }
        if (/^\/api\/sql\/admin\/schema\/[^/]+\/dateien$/.test(p)) {
            return antwort({ ok: true, gekappt: true, gesamt: 9000, dateien: 2, ordner: 1, bytes: 30, eintraege: [
                { pfad: 'ordner', art: 'ordner', groesse: 0 },
                { pfad: 'ordner/' + BOESE + '.sql', art: 'datei', groesse: 10 },
                { pfad: 'x.sql', art: 'datei', groesse: 20 }] });
        }
        if (/^\/api\/sql\/admin\/schema\/[^/]+\/datei$/.test(p) && o.method === 'DELETE') {
            return antwort({ ok: true, art: 'datei', dateien: 1, erfassung: 'gestartet' });
        }
        const mi = /^\/api\/sql\/admin\/schema\/([^/]+)\/index$/.exec(p);
        if (mi && o.method === 'POST') {
            // Wie der Server: laeuft schon ein Lauf, wird vorgemerkt
            let wie = 'gestartet';
            if (zustand.lauf) { zustand.wartet = (zustand.wartet || []).concat([mi[1]]); wie = 'vorgemerkt'; }
            else zustand.lauf = mi[1];
            return antwort({ ok: true, antwort: wie, erfassung: erfStand(), vorgemerkt: vorgemerkt() });
        }
        if (p === '/api/sql/admin/index/abbrechen' && o.method === 'POST') return antwort({ ok: true, antwort: 'Abbruch angefordert' });
        if (p === '/api/sql/admin/index') {
            zustand.polls++;
            if (zustand.polls >= zustand.pollsBisEnde && zustand.lauf) { zustand.fertig = zustand.lauf; zustand.lauf = null; }
            return antwort({ ok: true, hier: true, erfassung: erfStand(), vorgemerkt: vorgemerkt() });
        }
        return antwort({ ok: true });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;
    // XMLHttpRequest-Attrappe (der Upload braucht den Fortschritt, fetch hat keinen)
    function XHR() { this.upload = {}; this.status = 0; this.responseText = ''; }
    XHR.prototype.open = function (m, u) { this.m = m; this.u = u; };
    XHR.prototype.setRequestHeader = function (k, v) { this.kopf = this.kopf || {}; this.kopf[k] = v; };
    XHR.prototype.send = function (fd) {
        const self = this;
        const dateien = fd.getAll('files'), pfade = JSON.parse(fd.get('pfade') || '[]');
        hoch.push({ url: self.u, kopf: self.kopf, namen: dateien.map(function (f) { return f.name; }), pfade: pfade });
        setTimeout(function () {
            if (self.upload.onprogress) self.upload.onprogress({ lengthComputable: true, loaded: 1, total: 2 });
            self.status = 200;
            self.responseText = JSON.stringify({ ok: true, erfassung: 'gestartet',
                gespeichert: pfade.filter(function (x) { return !/\.zip$/i.test(x); }).map(function (x) { return { pfad: x, groesse: 1 }; }),
                abgelehnt: pfade.some(function (x) { return /\.zip$/i.test(x); }) ? [{ name: 'dump.zip: boese.exe', grund: BOESE }] : [] });
            self.onload();
        }, 5);
    };
    win.XMLHttpRequest = XHR;
    win.eval(JS.sitzung);
    win.eval(JS.icons);
    win.eval(JS.i18n);
    win.eval(JS.adm);
    if (!win.SqlAdmin) abbruch('window.SqlAdmin fehlt');
    await win.SqlAdmin.onShow();
    await schlaf(10);
    return { win: win, doc: win.document, gerufen: gerufen, hoch: hoch, fragen: fragen, zustand: zustand };
}
function klick(s, el) { if (el) el.dispatchEvent(new s.win.MouseEvent('click', { bubbles: true })); return !!el; }
function karten(s) { return s.doc.querySelectorAll('#sqadm-schemata .sqadm-schema'); }
function karte(s, sid) { return s.doc.querySelector('#sqadm-schemata .sqadm-schema[data-id="' + sid + '"]'); }
function datei(s, name, groesse, rel) {
    const f = new s.win.File(['x'.repeat(groesse || 1)], name);
    if (rel) Object.defineProperty(f, 'webkitRelativePath', { value: rel });
    return f;
}
function waehle(s, input, dateien) {
    Object.defineProperty(input, 'files', { value: dateien, configurable: true });
    input.dispatchEvent(new s.win.Event('change', { bubbles: true }));
}
async function warteBis(fn, ms) {
    for (let i = 0; i < (ms || 2000) / 10; i++) { if (fn()) return true; await schlaf(10); }
    return false;
}

(async function () {
    abschnitt('1. Laden');
    let s = await seite();
    let k = karten(s);
    check('Zwei Schemata gezeichnet', k.length === 2, k.length);
    check('Name maskiert im Wert, kein Element', k[0] && k[0].querySelector('.sqadm-name').value.indexOf('<img') > 0
          && !s.doc.querySelector('#sqadm-schemata img') && !s.win.__xss);
    check('Zahlen: Dateien, Groesse und Graph', /3 Dateien \(2\.0 MB\)/.test(k[0].textContent) && /5 Tabellen/.test(k[0].textContent),
          k[0] && k[0].querySelector('.sqadm-zahlen').textContent);
    check('Begleitdokumente gezaehlt', /2 Begleitdokumente/.test(k[0].querySelector('.sqadm-zahlen').textContent),
          k[0].querySelector('.sqadm-zahlen').textContent);
    check('Ablagefeld nennt die Begleitdokument-Endungen (vom Server)', /\.docx/.test(k[0].querySelector('.sqadm-drop').textContent));
    check('Schema ohne Graph-Eintrag nennt nur die Dateien', /0 Dateien/.test(k[1].textContent) && !/Tabellen/.test(k[1].querySelector('.sqadm-zahlen').textContent));
    check('Mülleimer-Symbol (kein Emoji) am Schema', k[0].querySelector('[data-akt="del-schema"] svg'));
    check('Ablagefeld je gespeichertem Schema, nennt die Endungen', k[0].querySelector('.sqadm-drop')
          && /\.sql\b/.test(k[0].querySelector('.sqadm-drop').textContent) && /\.zip\b/.test(k[0].querySelector('.sqadm-drop').textContent));
    check('Keine Ordner- oder Gruppenfelder mehr', !s.doc.querySelector('.sqadm-ordner, .sqadm-grp'));
    check('Dialekt steht am SCHEMA: jedes hat seinen eigenen', k[0].querySelector('.sqadm-dialekt').value === 'oracle'
          && k[1].querySelector('.sqadm-dialekt').value === 'mssql',
          [k[0].querySelector('.sqadm-dialekt').value, k[1].querySelector('.sqadm-dialekt').value]);
    check('Ablagefeld nennt die Endungen DIESES Schemas (hr: .yaml, nicht .sql)',
          /\.yaml\b/.test(k[1].querySelector('.sqadm-drop').textContent) && !/\.sql\b/.test(k[1].querySelector('.sqadm-drop').textContent),
          k[1].querySelector('.sqadm-drop-sub').textContent);
    klick(s, s.doc.getElementById('sqadm-neu'));
    await schlaf(5);
    k = karten(s);
    check('Neues Schema: KEIN Ablagefeld, Hinweis "erst speichern"', k.length === 3 && !k[2].querySelector('.sqadm-drop')
          && /Erst speichern/.test(k[2].textContent));
    check('Neues Schema: Einstellungen schon da, mit den Vorgaben des SERVERS; keine Erfassung',
          k[2].querySelector('.sqadm-dialekt').value === VORGABEN.dialekt
          && k[2].querySelector('.sqadm-muster').value === VORGABEN.dateimuster
          && k[2].querySelector('.sqadm-maxtab').value === String(VORGABEN.max_tabellen)
          && k[2].querySelector('.sqadm-fk').checked === true && !k[2].querySelector('.sqadm-erf'));
    s.win.close();

    abschnitt('2. Upload ueber das Dateifeld');
    s = await seite();
    const fin = karte(s, 'erp').parentNode.querySelector('input.sqadm-fin[data-sid="erp"]');
    let klicks = 0;
    if (fin) fin.addEventListener('click', function (e) { klicks++; e.preventDefault(); });
    klick(s, karte(s, 'erp').querySelector('.sqadm-drop'));
    await schlaf(5);
    check('Klick aufs Ablagefeld oeffnet den Dateidialog GENAU einmal (kein Rueckklick)', klicks === 1, klicks);
    check('Dateifeld liegt NEBEN dem Ablagefeld, nicht darin', fin && !fin.closest('.sqadm-drop'));
    const vorGets = s.gerufen.filter(function (g) { return g.pfad === '/api/sql/admin' && g.methode === 'GET'; }).length;
    waehle(s, fin, [datei(s, 'a.sql'), datei(s, 'liesmich.txt'), datei(s, '.versteckt.sql'), datei(s, 'Dump.ZIP'),
                    datei(s, 'B.DDL'), datei(s, 'Konventionen.docx')]);
    await warteBis(function () { return s.hoch.length && !s.win.SqlAdmin._hochladen.erp; });
    await schlaf(30);
    const h = s.hoch[0];
    check('Eine Anfrage an den Upload des Schemas, mit Anmeldung', s.hoch.length === 1 && /\/schema\/erp\/upload$/.test(h.url)
          && h.kopf && /Bearer test-token/.test(h.kopf.Authorization), h && h.url);
    check('Gefiltert: Muster, ZIP und Begleitdokumente (Endungen vom Server), ohne Versteckte',
          h && h.namen.join('|') === 'a.sql|Dump.ZIP|B.DDL|Konventionen.docx', h && h.namen);
    check('pfade in derselben Reihenfolge', h && h.pfade.join('|') === 'a.sql|Dump.ZIP|B.DDL|Konventionen.docx', h && h.pfade);
    const st = karte(s, 'erp').querySelector('.sqadm-up-status');
    check('Ergebnis nennt uebernommen/abgelehnt/uebersprungen', st && /3 Dateien übernommen, 1 abgelehnt, 2 übersprungen/.test(st.textContent),
          st && st.textContent);
    const abl = karte(s, 'erp').querySelectorAll('.sqadm-up-fehler li');
    check('Ablehnung sichtbar und maskiert', abl.length === 1 && /dump\.zip: boese\.exe/.test(abl[0].textContent)
          && !s.doc.querySelector('.sqadm-up-fehler img') && !s.win.__xss, abl.length);
    check('Danach neu geladen', s.gerufen.filter(function (g) { return g.pfad === '/api/sql/admin' && g.methode === 'GET'; }).length > vorGets);
    check('Fortschritt wieder verborgen, Ablage wieder frei', karte(s, 'erp').parentNode.querySelector('.sqadm-up[data-sid="erp"]').hidden
          && !karte(s, 'erp').querySelector('.sqadm-drop').classList.contains('disabled'));
    const n0 = s.hoch.length;
    waehle(s, karte(s, 'erp').parentNode.querySelector('input.sqadm-fin[data-sid="erp"]'), [datei(s, 'x.txt')]);
    await schlaf(30);
    check('Nichts Passendes: KEINE Anfrage, Grund steht da', s.hoch.length === n0
          && /Keine passende Datei/.test(karte(s, 'erp').querySelector('.sqadm-up-status').textContent));
    waehle(s, karte(s, 'erp').parentNode.querySelector('input.sqadm-din[data-sid="erp"]'),
           [datei(s, 't.sql', 1, 'dump/sub/t.sql'), datei(s, 'c.sql', 1, 'dump/.git/c.sql')]);
    await warteBis(function () { return s.hoch.length > n0 && !s.win.SqlAdmin._hochladen.erp; });
    check('Ordner-Auswahl: relativer Pfad bleibt, versteckter Ordner faellt weg',
          s.hoch.length === n0 + 1 && s.hoch[n0].pfade.join('|') === 'dump/sub/t.sql', s.hoch[n0] && s.hoch[n0].pfade);
    const n1 = s.hoch.length;
    waehle(s, karte(s, 'hr').parentNode.querySelector('input.sqadm-fin[data-sid="hr"]'), [datei(s, 'a.sql'), datei(s, 'kunde.yaml')]);
    await warteBis(function () { return s.hoch.length > n1 && !s.win.SqlAdmin._hochladen.hr; });
    check('Gefiltert nach dem Dateimuster DES SCHEMAS: hr nimmt .yaml, kein .sql',
          s.hoch.length === n1 + 1 && s.hoch[n1].namen.join('|') === 'kunde.yaml' && /\/schema\/hr\/upload$/.test(s.hoch[n1].url),
          s.hoch[n1] && s.hoch[n1].namen);
    s.win.close();

    abschnitt('3. Ordner per Ziehen');
    s = await seite();
    function dateiEintrag(name) {
        return { isFile: true, isDirectory: false, name: name, file: function (ok) { ok(datei(s, name)); } };
    }
    function ordnerEintrag(name, stuecke) {
        return { isFile: false, isDirectory: true, name: name, createReader: function () {
            let i = 0;
            return { readEntries: function (ok) { ok(i < stuecke.length ? stuecke[i++] : []); } };
        } };
    }
    // Zwei Stuecke + leeres Stueck: wer nur EINMAL liest, verliert das zweite
    const baumE = ordnerEintrag('schema', [[dateiEintrag('a.sql'), ordnerEintrag('unter', [[dateiEintrag('b.ddl')]])],
                                           [dateiEintrag('c.sql')]]);
    const ev = new s.win.Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(ev, 'dataTransfer', { value: { items: [{ kind: 'file', webkitGetAsEntry: function () { return baumE; } }],
                                                          files: [] } });
    karte(s, 'erp').querySelector('.sqadm-drop').dispatchEvent(ev);
    await warteBis(function () { return s.hoch.length && !s.win.SqlAdmin._hochladen.erp; });
    const hz = s.hoch[0];
    check('Ziehen: alle Stuecke, rekursiv, mit Ordnerstruktur', hz && hz.pfade.slice().sort().join('|')
          === 'schema/a.sql|schema/c.sql|schema/unter/b.ddl' && /\/schema\/erp\/upload$/.test(hz.url), hz && hz.pfade);
    check('Ziehen verhindert das Standardverhalten (Browser oeffnet die Datei nicht)', ev.defaultPrevented);
    s.win.close();

    abschnitt('4. Pakete');
    s = await seite();
    const I = s.win.SqlAdmin._intern;
    const viele = [];
    for (let i = 0; i < 450; i++) viele.push({ datei: { size: 10 }, pfad: 'f' + i + '.sql' });
    const p1 = I.pakete(viele);
    check('450 kleine Dateien -> Pakete zu hoechstens PAKET_DATEIEN', p1.length === Math.ceil(450 / I.PAKET_DATEIEN)
          && p1.every(function (p) { return p.length <= I.PAKET_DATEIEN; }) && p1.reduce(function (x, p) { return x + p.length; }, 0) === 450,
          p1.map(function (p) { return p.length; }));
    const gross = [0, 1, 2].map(function (i) { return { datei: { size: I.PAKET_BYTES - 1 }, pfad: 'g' + i + '.sql' }; });
    const p2 = I.pakete(gross);
    check('Grosse Dateien: je eine Anfrage (Bytegrenze)', p2.length === 3, p2.map(function (p) { return p.length; }));
    const w = I.auswaehlen([{ pfad: 'A.SQL' }, { pfad: 'x/.git/y.sql' }, { pfad: 'z.sql.bak' }, { pfad: 'd.zip' }], ['.sql']);
    check('Auswahl: Gross/Klein egal, versteckte Teile und falsche Endung raus',
          w.nehmen.map(function (g) { return g.pfad; }).join('|') === 'A.SQL|d.zip' && w.gefiltert === 2, w.nehmen.map(function (g) { return g.pfad; }));
    s.win.close();

    abschnitt('5. Dateiliste und Loeschen');
    s = await seite();
    const lb = karte(s, 'erp').querySelector('.sqadm-listbtn');
    check('Liste zu Beginn zu', lb && lb.getAttribute('aria-expanded') === 'false' && karte(s, 'erp').querySelector('.sqadm-baum').hidden);
    klick(s, lb);
    await schlaf(30);
    const baum = karte(s, 'erp').querySelector('.sqadm-baum');
    check('Aufgeklappt: Dateien des Schemas geholt', !baum.hidden && s.gerufen.some(function (g) {
        return g.pfad === '/api/sql/admin/schema/erp/dateien'; }));
    check('Kuerzung VOR der Liste beziffert', /3 von 9000/.test(baum.textContent)
          && baum.textContent.indexOf('3 von 9000') < baum.textContent.indexOf('x.sql'), baum.textContent.slice(0, 120));
    const li = baum.querySelectorAll('.sqadm-datei');
    check('Eintraege maskiert, Ordner gekennzeichnet und eingerueckt', li.length === 3 && li[0].classList.contains('is-ordner')
          && /padding-left:\s*16px/.test(li[1].getAttribute('style')) && !baum.querySelector('img') && !s.win.__xss, li.length);
    check('Mülleimer je Eintrag, mit Pfad im aria-label', li[2].querySelector('[data-akt="del-datei"] svg')
          && /x\.sql/.test(li[2].querySelector('[data-akt="del-datei"]').getAttribute('aria-label')));
    klick(s, li[2].querySelector('[data-akt="del-datei"]'));
    await schlaf(30);
    const del = s.gerufen.filter(function (g) { return g.methode === 'DELETE'; })[0];
    check('Loeschen nach Rueckfrage: DELETE mit Pfad', s.fragen.length === 1 && /x\.sql/.test(s.fragen[0])
          && del && /\/schema\/erp\/datei\?pfad=x\.sql$/.test(del.url), del && del.url);
    check('Danach bleibt die Liste offen und wird neu geholt', !karte(s, 'erp').querySelector('.sqadm-baum').hidden
          && s.gerufen.filter(function (g) { return g.pfad === '/api/sql/admin/schema/erp/dateien'; }).length >= 2);
    s.win.close();
    s = await seite({ bestaetigen: false });
    klick(s, karte(s, 'erp').querySelector('.sqadm-listbtn'));
    await schlaf(30);
    const ord = karte(s, 'erp').querySelectorAll('.sqadm-datei')[0];
    klick(s, ord.querySelector('[data-akt="del-datei"]'));
    await schlaf(20);
    check('Ordner: Rueckfrage nennt "samt Inhalt"; abgelehnt -> KEIN Aufruf',
          /samt Inhalt/.test(s.fragen[0] || '') && !s.gerufen.some(function (g) { return g.methode === 'DELETE'; }), s.fragen);
    s.win.close();

    abschnitt('6. Schema entfernen');
    s = await seite();
    klick(s, karte(s, 'erp').querySelector('[data-akt="del-schema"]'));
    await schlaf(5);
    check('Karte entfernt, Hinweis nennt das Loeschen der Dateien', karten(s).length === 1
          && /Dateien werden dabei gelöscht/.test(s.doc.getElementById('sqadm-status').textContent));
    klick(s, s.doc.getElementById('sqadm-save'));
    await schlaf(40);
    const puts = s.gerufen.filter(function (g) { return g.methode === 'PUT'; });
    let b2 = null;
    try { b2 = JSON.parse(puts[1].body); } catch (e) { b2 = null; }
    check('409 -> Rueckfrage mit Name und Dateizahl', s.fragen.length === 1 && /ERP/.test(s.fragen[0]) && /3 Dateien/.test(s.fragen[0]),
          s.fragen);
    check('... dann erneut MIT Bestaetigung', puts.length === 2 && b2 && b2.loeschen_bestaetigt === true
          && b2.cfg.schemata.map(function (x) { return x.id; }).join() === 'hr', puts.length);
    check('Gespeichert gemeldet', /Gespeichert/.test(s.doc.getElementById('sqadm-status').textContent));
    s.win.close();
    s = await seite({ bestaetigen: false });
    klick(s, karte(s, 'erp').querySelector('[data-akt="del-schema"]'));
    klick(s, s.doc.getElementById('sqadm-save'));
    await schlaf(40);
    check('Abgelehnt: nur EIN PUT, nichts geloescht, Grund steht da', s.zustand.puts === 1
          && s.zustand.cfg.schemata.length === 2 && /bleibt erhalten/.test(s.doc.getElementById('sqadm-status').textContent));
    s.win.close();

    abschnitt('7. Fehler beim Speichern');
    s = await seite({ speichernFehler: true });
    klick(s, s.doc.getElementById('sqadm-save2'));
    await schlaf(20);
    const st2 = s.doc.getElementById('sqadm-status2');
    check('Status sagt "nicht gespeichert"', /Nicht gespeichert/.test(st2.textContent), st2.textContent);
    const hl = s.doc.querySelectorAll('#sqadm-hinweise li');
    check('Fehlerliste sichtbar und maskiert', hl.length === 1 && !s.doc.querySelector('#sqadm-hinweise img'), hl.length);
    // Ein ERFOLG verschwindet nach 3,5 s – laenger warten, sonst ist der
    // Unterschied gar nicht messbar.
    await schlaf(3700);
    check('Fehler bleibt stehen (auch nach 3,7 s)', /Nicht gespeichert/.test(st2.textContent));
    s.win.close();

    abschnitt('7b. Keine Antwort vom Server (Netzfehler)');
    s = await seite({ netzweg: true });
    klick(s, s.doc.getElementById('sqadm-save'));
    await schlaf(30);
    const nf = s.doc.getElementById('sqadm-status').textContent;
    check('Statt "Failed to fetch": Meldung mit Pfad und Uhrzeit', /Keine Antwort vom Server/.test(nf)
          && /\/api\/sql\/admin/.test(nf) && /\d{1,2}:\d{2}/.test(nf) && !/Failed to fetch/.test(nf), nf);
    check('Regel: kein nacktes fetch( im Modul ausser in holen()', (JS.adm.match(/(^|[^.\w])fetch\(/g) || []).length === 1);
    s.win.close();

    abschnitt('8. Erfassung je Schema');
    s = await seite();
    function erf(sid) { return karte(s, sid).querySelector('.sqadm-erf'); }
    function laeuftIn(sid) { return !erf(sid).querySelector('.sqadm-erf-fort').hidden; }
    check('Positivkontrolle: in JEDEM gespeicherten Schema ein eigener Erfassungs-Teil mit Knopf "Neu erfassen"',
          erf('erp') && erf('hr') && /Neu erfassen/.test(erf('erp').querySelector('.sqadm-erf-start').textContent)
          && /Neu erfassen/.test(erf('hr').querySelector('.sqadm-erf-start').textContent));
    if (!erf('erp') || !erf('hr')) abbruch('Erfassungs-Teil je Schema fehlt – die Folgepruefungen waeren trivial');
    check('Keine Erfassung ausserhalb der Schemata (kein gemeinsamer Knopf mehr)',
          !s.doc.getElementById('sqadm-start') && !s.doc.getElementById('sq-sect-erf')
          && s.doc.querySelectorAll('[data-akt="erfassen"]').length === 2);
    check('Letzte Erfassung steht je Schema: erp bekannt (mit Umlaut-freiem Ergebniswort aus den Texten)',
          /Letzte Erfassung: fertig am 2026-11-07 10:00:00/.test(erf('erp').querySelector('.sqadm-erf-stand').textContent),
          erf('erp').querySelector('.sqadm-erf-stand').textContent);
    check('... und fuer hr wird NICHTS behauptet (kein Lauf bekannt)', erf('hr').querySelector('.sqadm-erf-stand').textContent === '',
          erf('hr').querySelector('.sqadm-erf-stand').textContent);
    // Eine ungespeicherte Eingabe in hr – sie muss Takt und Laufende ueberleben
    const hrName = karte(s, 'hr').querySelector('.sqadm-name');
    hrName.value = 'Personal NEU';
    hrName.dispatchEvent(new s.win.Event('input', { bubbles: true }));
    karte(s, 'hr').querySelector('.sqadm-maxtab').value = '33';
    check('Titel des Containers folgt dem Namensfeld', karte(s, 'hr').querySelector('.sqadm-titel').textContent === 'Personal NEU');
    klick(s, erf('erp').querySelector('.sqadm-erf-start'));
    await schlaf(30);
    check('Start ruft die Erfassung DIESES Schemas', s.gerufen.some(function (g) {
        return g.pfad === '/api/sql/admin/schema/erp/index' && g.methode === 'POST'; })
        && !s.gerufen.some(function (g) { return g.pfad === '/api/sql/admin/index' && g.methode === 'POST'; }));
    check('Fortschritt und Abbrechen im erfassten Schema', laeuftIn('erp')
          && erf('erp').querySelector('.sqadm-erf-stop').style.display !== 'none'
          && erf('erp').querySelector('.sqadm-erf-start').disabled);
    check('Das ANDERE Schema laeuft nicht: kein Fortschritt, kein Abbrechen, Start frei', !laeuftIn('hr')
          && erf('hr').querySelector('.sqadm-erf-stop').style.display === 'none'
          && !erf('hr').querySelector('.sqadm-erf-start').disabled);
    check('Kopfzeile sagt es als TEXT (nicht nur der Balken)', /Erfassung läuft/.test(karte(s, 'erp').querySelector('.sqadm-kopfinfo').textContent)
          && !/läuft/.test(karte(s, 'hr').querySelector('.sqadm-kopfinfo').textContent));
    // Waehrend erp laeuft: hr von Hand -> vorgemerkt
    klick(s, erf('hr').querySelector('.sqadm-erf-start'));
    await schlaf(30);
    check('Zweites Schema waehrend des Laufs: VORGEMERKT, als Text und mit gesperrtem Knopf',
          /Vorgemerkt/.test(erf('hr').querySelector('.sqadm-erf-stand').textContent)
          && erf('hr').querySelector('.sqadm-erf-start').disabled && !laeuftIn('hr')
          && /vorgemerkt/.test(karte(s, 'hr').querySelector('.sqadm-kopfinfo').textContent),
          erf('hr').querySelector('.sqadm-erf-stand').textContent);
    const erpKarteVor = karte(s, 'erp');
    await schlaf(2300);
    check('Takt: Zaehler DIESES Schemas (2 von 4 Dateien, 50 %)', /2 von 4 Dateien/.test(erf('erp').querySelector('.vis-progress-text').textContent)
          && erf('erp').querySelector('.vis-progress-fill').style.width === '50%',
          erf('erp').querySelector('.vis-progress-text').textContent);
    check('Takt zeichnet die Container NICHT neu (dasselbe Element, Eingabe steht noch)', karte(s, 'erp') === erpKarteVor
          && karte(s, 'hr').querySelector('.sqadm-name').value === 'Personal NEU');
    klick(s, erf('erp').querySelector('.sqadm-erf-stop'));
    await schlaf(20);
    check('Abbrechen ruft den Abbruch, Rueckmeldung am Knopf', s.gerufen.some(function (g) {
        return g.pfad === '/api/sql/admin/index/abbrechen' && g.methode === 'POST'; })
        && /Abbruch angefordert/.test(erf('erp').querySelector('.sqadm-erf-status').textContent));
    s.zustand.wartet = null;      // der Nachlauf ist abgeholt – sonst endet der Takt nie
    await schlaf(2600);
    check('Ende erkannt: neu geladen, Fortschritt weg, Ergebnis DIESES Laufs am Schema', !laeuftIn('erp')
          && s.gerufen.filter(function (g) { return g.pfad === '/api/sql/admin' && g.methode === 'GET'; }).length >= 2
          && /Letzte Erfassung: unverändert am 2026-11-10 09:00:00 – 9 Dateien, davon 4 neu/.test(erf('erp').querySelector('.sqadm-erf-stand').textContent),
          erf('erp').querySelector('.sqadm-erf-stand').textContent + ' / polls ' + s.zustand.polls);
    check('Nachladen am Laufende behaelt die UNGESPEICHERTEN Eingaben (Name und Hoechstzahl in hr)',
          karte(s, 'hr').querySelector('.sqadm-name').value === 'Personal NEU'
          && karte(s, 'hr').querySelector('.sqadm-maxtab').value === '33',
          [karte(s, 'hr').querySelector('.sqadm-name').value, karte(s, 'hr').querySelector('.sqadm-maxtab').value]);
    s.win.close();

    abschnitt('9. Schema als Container, Einstellungen darin');
    s = await seite();
    k = karten(s);
    const kopfE = k[0].querySelector(':scope > .kb-collapse-header');
    check('Jedes Schema ist ein Container in der Bauform der Abschnitte (.kb-section, Klapp-Kopfzeile, Titel als h3)',
          Array.prototype.every.call(k, function (x) {
              return x.classList.contains('kb-section') && x.querySelector(':scope > .kb-collapse-header > h3')
                  && x.querySelector(':scope > .kb-collapse-body'); }));
    check('Titel = Name des Schemas, maskiert', kopfE && /ERP <img/.test(kopfE.querySelector('h3').textContent)
          && !kopfE.querySelector('img'));
    // Das Suchfeld der Einstellungen findet Abschnitt und Rumpf ueber <x>-hdr / <x>-body
    check('Kopfzeile und Rumpf tragen das Kennungspaar der Abschnitte (<x>-hdr / <x>-body), je Schema eindeutig',
          Array.prototype.every.call(k, function (x) {
              const h = x.querySelector(':scope > .kb-collapse-header'), r = x.querySelector(':scope > .kb-collapse-body');
              return /-hdr$/.test(h.id) && r.id === h.id.replace(/-hdr$/, '-body') && s.doc.querySelectorAll('#' + h.id).length === 1; })
          && k[0].querySelector('.kb-collapse-header').id !== k[1].querySelector('.kb-collapse-header').id,
          Array.prototype.map.call(k, function (x) { return x.querySelector('.kb-collapse-header').id; }));
    ['sqadm-dialekt', 'sqadm-muster', 'sqadm-maxtab', 'sqadm-maxsp', 'sqadm-fk'].forEach(function (kl) {
        check('Einstellung .' + kl + ' steht IN jedem Schema-Container und nirgends ausserhalb',
              Array.prototype.every.call(k, function (x) { return x.querySelectorAll('.kb-collapse-body .' + kl).length === 1; })
              && s.doc.querySelectorAll('.' + kl).length === k.length && !s.doc.getElementById(kl));
    });
    check('Werte je Schema: Muster, Hoechstzahlen und Ableiten', k[0].querySelector('.sqadm-muster').value === '*.sql,*.ddl'
          && k[1].querySelector('.sqadm-muster').value === '*.yaml' && k[1].querySelector('.sqadm-maxtab').value === '20'
          && k[1].querySelector('.sqadm-maxsp').value === '60' && k[0].querySelector('.sqadm-fk').checked
          && !k[1].querySelector('.sqadm-fk').checked);
    check('Beschriftung haengt am Feld (label for)', Array.prototype.every.call(k[1].querySelectorAll('.sqadm-einst .form-group'), function (g) {
        const l = g.querySelector('label'), f = g.querySelector('select, input');
        return l && f && f.id && l.getAttribute('for') === f.id && s.doc.querySelectorAll('#' + f.id).length === 1; }));
    check('Fuer alle Schemata bleibt NUR: Leseprozesse und Chat-Erlaubnis',
          s.doc.getElementById('sqadm-prozesse').value === '3' && s.doc.getElementById('sqadm-chat')
          && s.doc.querySelectorAll('#sq-sect-allg input, #sq-sect-allg select').length === 2);
    // Zuklappen
    klick(s, kopfE);
    const rumpfE = k[0].querySelector(':scope > .kb-collapse-body');
    check('Klick auf die Kopfzeile klappt zu (Rumpf weg, aria-expanded, Pfeil)', rumpfE.style.display === 'none'
          && kopfE.getAttribute('aria-expanded') === 'false' && kopfE.classList.contains('is-collapsed')
          && /▶/.test(kopfE.textContent));
    check('... und merkt es sich je Schema', s.win.localStorage.getItem('jarvis_sect_collapse_sqadm-erp') === '1'
          && s.win.localStorage.getItem('jarvis_sect_collapse_sqadm-hr') === null);
    check('Der andere Container bleibt offen', k[1].querySelector(':scope > .kb-collapse-body').style.display !== 'none');
    // Speichern aus einem Container: je Schema, nichts auf oberster Ebene
    k[1].querySelector('.sqadm-dialekt').value = 'postgresql';
    k[1].querySelector('.sqadm-maxsp').value = '77';
    klick(s, k[1].querySelector('[data-akt="speichern"]'));
    await schlaf(60);
    const put = s.gerufen.filter(function (g) { return g.methode === 'PUT'; })[0];
    let pb = null;
    try { pb = JSON.parse(put.body); } catch (e) { pb = null; }
    check('PUT traegt GENAU: schemata, prozesse, index_aus_chat – kein Schema-Feld auf oberster Ebene',
          pb && Object.keys(pb.cfg).sort().join() === 'index_aus_chat,prozesse,schemata', pb && Object.keys(pb.cfg));
    check('... die Aenderung steht im RICHTIGEN Schema, das andere ist unveraendert',
          pb && pb.cfg.schemata[1].id === 'hr' && pb.cfg.schemata[1].dialekt === 'postgresql' && pb.cfg.schemata[1].max_spalten === 77
          && pb.cfg.schemata[0].dialekt === 'oracle' && pb.cfg.schemata[0].max_spalten === 40, pb && pb.cfg.schemata);
    check('... auch die Werte des ZUGEKLAPPTEN Containers sind vollstaendig dabei',
          pb && JSON.stringify(Object.keys(pb.cfg.schemata[0]).sort()) === JSON.stringify(
              ['dateimuster', 'dialekt', 'fk_ableiten', 'id', 'max_spalten', 'max_tabellen', 'name'])
          && pb.cfg.schemata[0].dateimuster === '*.sql,*.ddl' && pb.cfg.schemata[0].fk_ableiten === true);
    check('Ergebnis steht AM Knopf im Container (nach dem Neuzeichnen)',
          /Gespeichert/.test(karte(s, 'hr').querySelector('.sqadm-einst-status').textContent),
          karte(s, 'hr').querySelector('.sqadm-einst-status').textContent);
    check('Zugeklappt bleibt zugeklappt ueber das Neuzeichnen', karte(s, 'erp').querySelector(':scope > .kb-collapse-body').style.display === 'none');
    s.win.close();
    // Dateimuster geaendert -> dieses Schema wird neu erfasst, und das steht da
    s = await seite();
    karte(s, 'hr').querySelector('.sqadm-muster').value = '*.yaml,*.yml';
    klick(s, karte(s, 'hr').querySelector('[data-akt="speichern"]'));
    await schlaf(60);
    check('Geaendertes Dateimuster: Meldung nennt das neu erfasste Schema, sein Container zeigt den Lauf',
          /neu erfasst wird: „Personal“/.test(karte(s, 'hr').querySelector('.sqadm-einst-status').textContent)
          && !karte(s, 'hr').querySelector('.sqadm-erf-fort').hidden && karte(s, 'erp').querySelector('.sqadm-erf-fort').hidden,
          karte(s, 'hr').querySelector('.sqadm-einst-status').textContent);
    s.win.close();
    // Fehler beim Speichern aus dem Container: der Grund steht am Knopf
    s = await seite({ speichernFehler: true });
    klick(s, karte(s, 'hr').querySelector('[data-akt="speichern"]'));
    await schlaf(30);
    const fe = karte(s, 'hr').querySelector('.sqadm-einst-status');
    check('Fehler: am Knopf im Container, mit dem ersten Grund, maskiert', /Nicht gespeichert: Schema „X“/.test(fe.textContent)
          && fe.classList.contains('is-fehler') && !fe.querySelector('img') && !s.win.__xss, fe.textContent);
    s.win.close();
    // Ein Nachladen ist unterwegs, waehrend gespeichert wird: das eben
    // gespeicherte neue Schema darf danach nicht wieder als ungespeichert dastehen
    s = await seite();
    klick(s, s.doc.getElementById('sqadm-neu'));
    await schlaf(5);
    const neuN = karten(s)[2].querySelector('.sqadm-name');
    neuN.value = 'Lager';
    s.zustand.getLangsam = true;
    const unterwegs = s.win.SqlAdmin.laden(true);
    klick(s, s.doc.getElementById('sqadm-save'));
    await unterwegs;
    await schlaf(80);
    const k3 = karten(s)[2];
    check('Positivkontrolle: gespeichert, waehrend ein Nachladen unterwegs war', s.zustand.puts === 1
          && s.zustand.cfg.schemata.length === 3 && s.zustand.cfg.schemata[2].id === 'neu2', s.zustand.cfg.schemata.map(function (x) { return x.id; }));
    check('... das neue Schema traegt danach SEINE Kennung und hat Ablage und Erfassung (nicht "erst speichern")',
          k3 && k3.getAttribute('data-id') === 'neu2' && k3.querySelector('.sqadm-drop') && k3.querySelector('.sqadm-erf')
          && !/Erst speichern/.test(k3.textContent), k3 && k3.getAttribute('data-id'));
    s.win.close();
    check('Regel: das Modul schickt kein Schema-Feld auf oberster Ebene (kein cfg.dialekt usw.)',
          !/cfg\.(dialekt|dateimuster|fk_ableiten|max_tabellen|max_spalten)\b/.test(JS.adm));

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(function (e) {
    bilanz = true;
    console.log('ABBRUCH: ' + (e && e.stack || e));
    console.log('\nErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    process.exit(1);
});
