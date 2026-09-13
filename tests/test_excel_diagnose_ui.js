/*
 * Excel-Add-in: Diagnose-Protokoll, Kosmetik-Isolation, Auto-Uebernahme.
 *
 * ANLASS (2026-09-09, gemeldet mit Screenshot): das Fenster zeigte
 * "Schreiben fehlgeschlagen: Interner Fehler waehrend der Verarbeitung der
 * Anforderung." – und darunter stand der Vorschlag weiter mit "Uebernehmen",
 * obwohl "Aenderungen automatisch uebernehmen" angehakt war.
 *
 * ZWEI BEFUNDE, und der erste ist der schwerere:
 *
 * (1) Markierung und Zellkommentar liefen im SELBEN `Excel.run` wie das
 *     Schreiben. Ein `comments.add` auf eine Zelle, die schon einen Kommentar
 *     traegt, wirft – und zwar beim `ctx.sync()`, also AUSSERHALB der
 *     `try`-Bloecke daneben. Der ganze Vorgang landete im Fehlerzweig: die
 *     Meldung sagte "Schreiben fehlgeschlagen", waehrend die Werte laengst in
 *     der Mappe standen.
 *
 *     ⚠ DESHALB WIRFT DIE ATTRAPPE HIER BEIM `sync()`, NICHT BEIM `add()`.
 *     Eine Attrappe, die beim Aufruf wirft, stellt die gemeldete Lage GAR
 *     NICHT her – der `try/catch` daneben faengt sie, und der Waechter waere
 *     gruen, ohne etwas zu messen.
 *
 * (2) Es gab kein Protokoll. `String(e.message)` wirft die ganze Diagnose weg:
 *     `e.code`, `e.debugInfo.errorLocation` und die scheiternde Anweisung.
 *     `console.warn` ist KEIN Ersatz – an die Entwicklerkonsole von WebView2
 *     kommt am Arbeitsplatz niemand.
 *
 * Gemessen wird die EIGENSCHAFT am ausgefuehrten Code, nicht ein Vorkommen im
 * Quelltext: der echte `excel.js` laeuft in jsdom gegen eine Excel-Attrappe.
 */
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + t); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + t + (d ? '\n      ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try {
    const kandidaten = [process.env.JSDOM_PATH, '/tmp/node_modules/jsdom',
                        path.join(ROOT, 'node_modules/jsdom'),
                        path.join(ROOT, 'data/node_modules/jsdom'),
                        '/usr/share/nodejs/jsdom'].filter(Boolean);
    let letzter = null;
    for (const k of kandidaten) {
        try { JSDOM = require(k).JSDOM; break; } catch (e) { letzter = e; }
    }
    if (!JSDOM) throw letzter;
} catch (e) {
    // Exit 2, nicht 0: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
    console.log('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH setzen)');
    process.exit(2);
}

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/taskpane.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

/* Kommentare heraus, bevor irgendetwas im Quelltext gesucht wird. Ein
   Waechter, der seine eigene Begruendung liest, prueft nichts – im Projekt
   dreizehn belegte Faelle. */
function nurCode(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ');
}
const JS_CODE = nurCode(JS);

/* ── Wachhund ──────────────────────────────────────────────────────────
   Die ganze Datei ist eine async-IIFE: wirft etwas darin, wird alles bis zum
   Ende uebersprungen – auch die Bilanzzeile – und Node beendet mit 0. Ein
   abgebrochener Lauf saehe dann wie ein bestandener aus. */
let bilanz = false;
const hund = setTimeout(() => {
    console.log('\n\x1b[31mABBRUCH: Zeitgrenze erreicht\x1b[0m');
    console.log('Bestanden: ' + ok + ' / Fehlgeschlagen: ' + (fail + 1) + ' (ABGEBROCHEN)');
    process.exit(1);
}, 40000);
process.on('exit', (c) => {
    if (!bilanz && c === 0) {
        console.log('\n\x1b[31mABBRUCH ohne Bilanz\x1b[0m');
        process.exitCode = 1;
    }
});

function warte(ms) { return new Promise(r => setTimeout(r, ms)); }

/* Office.js-Fehler, wie er wirklich aussieht: `code`, `message` und
   `debugInfo` mit der scheiternden Anweisung. Genau diese Felder wirft
   `String(e.message)` weg. */
function officeFehler(ort, anweisung) {
    const e = new Error('Interner Fehler während der Verarbeitung der Anforderung.');
    e.code = 'GeneralException';
    e.debugInfo = {
        code: 'GeneralException',
        errorLocation: ort,
        fullStatement: anweisung,
        statements: [anweisung],
        surroundingStatements: ['range.load(...)', anweisung]
    };
    e.traceMessages = [];
    return e;
}

/* Excel-Attrappe. `opt.kommentarFehler` laesst den KOSMETIK-Lauf beim sync
   scheitern, `opt.schreibFehler` den Schreib-Lauf – zwei verschiedene Lagen,
   die verschiedene Antworten verlangen. */
function excelStub(z, opt) {
    opt = opt || {};
    const masse = (adr) => {
        const m = /^\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$/i.exec(adr || '');
        if (!m) return { z: 1, s: 1 };
        const idx = (b) => b.toUpperCase().split('').reduce((a, c) => a * 26 + c.charCodeAt(0) - 64, 0);
        const z1 = +m[2], z2 = m[4] ? +m[4] : z1;
        const s1 = idx(m[1]), s2 = m[3] ? idx(m[3]) : s1;
        return { z: Math.abs(z2 - z1) + 1, s: Math.abs(s2 - s1) + 1 };
    };
    const machRange = (adr) => {
        const mm = masse(adr);
        const leer = (f) => Array.from({ length: mm.z }, () => Array.from({ length: mm.s }, f));
        const r = {
            address: 'Tabelle1!' + adr, rowCount: mm.z, columnCount: mm.s,
            _values: leer(() => 'alt'), _formulas: leer(() => 'alt'),
            _numberFormat: leer(() => 'General'),
            load() { }, getCell() { return machRange(adr); },
            copyFrom() { z.copyFrom = true; }, select() { },
            format: { fill: { load() { }, clear() { } } }
        };
        Object.defineProperty(r, 'formulas', {
            get() { return this._formulas; },
            set(v) { this._formulas = v; z.geschrieben.push({ adr, v }); }
        });
        Object.defineProperty(r, 'values', {
            get() { return this._values; },
            set(v) { this._values = v; z.werte.push({ adr, v }); }
        });
        Object.defineProperty(r, 'numberFormat', {
            get() { return this._numberFormat; },
            set(v) { this._numberFormat = v; z.formate.push({ adr, v }); }
        });
        Object.defineProperty(r.format.fill, 'color', {
            get() { return ''; },
            set(v) { z.markiert.push({ adr, v }); }
        });
        return r;
    };
    const blatt = (name) => ({
        name, isNullObject: false, activate() { }, load() { },
        getRange: (adr) => machRange(adr),
        getUsedRangeOrNullObject: () => ({ address: 'A1:C3', rowCount: 3, columnCount: 3,
            rowIndex: 0, columnIndex: 0, isNullObject: false, load() { },
            getSpecialCellsOrNullObject: () => ({ isNullObject: true, load() { } }) }),
        getRangeByIndexes: () => {
            const daten = {
                values: [['A', 1]], formulas: [['A', 1]],
                numberFormat: [['General', 'General']], valueTypes: [['String', 'Double']]
            };
            const gel = {};
            const r = { load(p) { String(p || '').split(',').forEach(n => { gel[n.trim()] = true; }); } };
            Object.keys(daten).forEach(n => Object.defineProperty(r, n, {
                get() {
                    if (!gel[n]) throw new Error("PropertyNotLoaded: '" + n + "'");
                    return daten[n];
                }
            }));
            return r;
        },
        tables: { items: [], load() { } }
    });
    return {
        RangeCopyType: { formulas: 'formulas' },
        SpecialCellType: { formulas: 'formulas' },
        SpecialCellValueType: { errors: 'errors' },
        run(fn) {
            // JEDER Lauf bekommt seinen eigenen Fehlerspeicher – nur so
            // laesst sich messen, dass der Kosmetik-Lauf getrennt ist.
            let fehler = null;
            const ctx = {
                workbook: {
                    name: 'Mappe1.xlsx',
                    worksheets: {
                        items: [{ name: 'Tabelle1' }], load() { },
                        getItem: (n) => blatt(n),
                        getItemOrNullObject: (n) => (n === 'Tabelle1' ? blatt(n)
                            : { name: n, isNullObject: true, load() { } }),
                        add(n) { z.angelegt.push(n); return blatt(n); },
                        getActiveWorksheet: () => blatt('Tabelle1'),
                        onSelectionChanged: { add() { } }
                    },
                    names: { items: [], load() { } },
                    comments: {
                        add(r, t) {
                            z.kommentare.push(t);
                            // ⚠ NICHT hier werfen: Office.js meldet den Fehler
                            // erst beim sync – der try/catch daneben faengt ihn
                            // sonst, und die gemeldete Lage entsteht nie.
                            if (opt.kommentarFehler) {
                                fehler = officeFehler('Workbook.comments.add',
                                    'workbook.comments.add(range, "Jarvis: ...")');
                            }
                        },
                        getItemByCell(adr) {
                            z.gesuchteKommentare.push(adr);
                            if (!opt.kommentarDa) {
                                // Wie im echten Office.js: der Fehler faellt
                                // beim sync an, nicht beim Aufruf.
                                fehler = officeFehler('Workbook.comments.getItemByCell',
                                    'workbook.comments.getItemByCell("A1")');
                                return { load() { } };
                            }
                            const k = { id: 'k1', load() { } };
                            Object.defineProperty(k, 'content', {
                                get() { return ''; },
                                set(v) { z.ersetzt.push(v); }
                            });
                            return k;
                        }
                    },
                    getSelectedRange: () => ({ address: 'Tabelle1!A1', rowCount: 1,
                        columnCount: 1, values: [[1]], formulas: [['1']],
                        worksheet: { name: 'Tabelle1', load() { } }, load() { } }),
                    load() { }
                },
                sync() {
                    if (opt.schreibFehler && z.geschrieben.length && !z.schreibGeworfen) {
                        z.schreibGeworfen = true;
                        // `lang` bildet den Regelfall eines Werte-Bereichs ab:
                        // die Anweisung traegt die ganze Matrix.
                        const anw = opt.lang
                            ? 'worksheet.getRange("A2:A400").values = [[' +
                              Array.from({ length: 400 }, (_, i) => '"Wert ' + i + '"').join(',') + ']]'
                            : 'worksheet.getRange("G2").formulas = [["=E2*F2"]]';
                        return Promise.reject(officeFehler('Range.formulas', anw));
                    }
                    if (fehler) { const f = fehler; fehler = null; return Promise.reject(f); }
                    return Promise.resolve();
                }
            };
            return Promise.resolve().then(() => fn(ctx));
        }
    };
}

function fenster(opt) {
    opt = opt || {};
    const z = { geschrieben: [], werte: [], formate: [], markiert: [], kommentare: [],
                gesuchteKommentare: [], ersetzt: [], angelegt: [], gesendet: [],
                copyFrom: false, schreibGeworfen: false, extended: false };
    const dom = new JSDOM(HTML, { url: 'https://jarvis.test/excel-addin/taskpane.html?mv=1.0.0.0',
                                  runScripts: 'outside-only' });
    const win = dom.window;
    win.Office = {
        HostType: { Excel: 'Excel' },
        onReady: (cb) => cb({ host: 'Excel' }),
        context: { requirements: { isSetSupported: () => opt.api !== false },
                   platform: 'PC', diagnostics: { version: '16.0' } }
    };
    // OfficeExtension.config.extendedErrorLogging – ohne diesen Schalter
    // bleibt `debugInfo.fullStatement` leer, und das Protokoll kann die
    // scheiternde Anweisung gar nicht nennen.
    win.OfficeExtension = { config: {} };
    Object.defineProperty(win.OfficeExtension.config, 'extendedErrorLogging', {
        get() { return z.extended; }, set(v) { z.extended = !!v; }
    });
    win.Excel = excelStub(z, opt);
    win.localStorage.setItem('jarvis_token', 'T');
    if (opt.auto !== undefined) win.localStorage.setItem('jarvis_xl_autoapply', opt.auto);
    if (opt.mark !== undefined) win.localStorage.setItem('jarvis_xl_markieren', opt.mark);
    win.fetch = (url, o2) => {
        const pfad = String(url).split('?')[0];
        z.gesendet.push({ pfad, opt: o2 });
        const j = (d) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/excel-addin/version') return j({ ok: true, version: '1.0.0.0' });
        if (pfad === '/api/me') return j({ username: 'u', permissions: { excel: true } });
        if (pfad === '/api/excel/ask') return j(opt.antwort || {
            ok: true, text: 'Vorschlag.',
            aenderungen: [{ blatt: 'Tabelle1', adresse: 'G2', formel: '=E2*F2',
                            begruendung: 'Marge', format: 'dd.mm.yyyy' }],
            abgelehnt: [], zusammenfassung: 'Eine Spalte', brauche: [], runde: 1
        });
        return j({ ok: true });
    };
    win.eval(JS);
    return { win, dom, z };
}

async function frageStellen(win) {
    const f = win.document.getElementById('xl-frage');
    f.value = 'Trage die Marge ein';
    win.document.getElementById('xl-send').click();
    await warte(90);
}

(async () => {

abschnitt('1. Der Schalter, der die Diagnose ueberhaupt erst einschaltet');
{
    const { win, z, dom } = fenster({});
    await warte(60);
    pruefe(z.extended === true,
        'extendedErrorLogging wird gesetzt (sonst bleibt debugInfo leer)');
    const log = win.document.getElementById('xl-log-out');
    pruefe(!!log, 'die Protokoll-Ansicht existiert im Markup');
    pruefe(/ExcelApi 1\.9=/.test(log.textContent),
        'die Excel-Fassungen stehen im Protokoll',
        JSON.stringify((log && log.textContent || '').slice(0, 160)));
    dom.window.close();
}

abschnitt('2. Kosmetik kippt den Schreibvorgang NICHT (der gemeldete Fall)');
{
    const { win, z, dom } = fenster({ auto: '1', kommentarFehler: true });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    const doc = win.document;
    const chat = doc.getElementById('xl-chat').textContent;

    pruefe(z.geschrieben.length > 0, 'die Aenderung wurde geschrieben');
    pruefe(z.kommentare.length > 0, 'der Kommentar wurde versucht');
    // DAS IST DIE ZUSAGE: der gescheiterte Kommentar darf den Vorgang nicht
    // als Fehlschlag melden – die Werte stehen in der Mappe.
    pruefe(!/fehlgeschlagen/i.test(chat),
        'KEIN "Schreiben fehlgeschlagen" im Verlauf',
        JSON.stringify(chat.slice(-260)));
    pruefe(!doc.getElementById('xl-apply'),
        'kein "Uebernehmen"-Knopf mehr (der Vorschlag ist erledigt)');
    pruefe(/übernommen/i.test(chat),
        'der Verlauf meldet die Uebernahme', JSON.stringify(chat.slice(-200)));
    // ...aber verschwiegen wird es auch nicht.
    const log = doc.getElementById('xl-log-out').textContent;
    pruefe(/markierung/.test(log) && /GeneralException/.test(log),
        'der Kosmetik-Fehler steht im Protokoll', JSON.stringify(log.slice(-300)));
    pruefe(/die Aenderung selbst steht/.test(log),
        'und das Protokoll sagt, dass die Aenderung trotzdem geschrieben ist');
    dom.window.close();
}

abschnitt('3. Ein ECHTER Schreibfehler: Protokoll statt "interner Fehler"');
{
    const { win, z, dom } = fenster({ auto: '1', schreibFehler: true });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    const doc = win.document;
    const chat = doc.getElementById('xl-chat').textContent;
    const log = doc.getElementById('xl-log-out').textContent;

    pruefe(/fehlgeschlagen/i.test(chat),
        'der Fehlschlag steht im VERLAUF, nicht nur in der Statuszeile am Fuss',
        JSON.stringify(chat.slice(-240)));
    pruefe(/GeneralException/.test(chat),
        'die Meldung nennt den Fehlercode (nicht nur "interner Fehler")');
    pruefe(/Diagnose-Protokoll/.test(chat),
        'und sie nennt den Weg zu den Einzelheiten');
    pruefe(/errorLocation=Range\.formulas/.test(log),
        'das Protokoll nennt den ORT der gescheiterten Anweisung',
        JSON.stringify(log.slice(-400)));
    pruefe(/statement=worksheet\.getRange\("G2"\)\.formulas/.test(log),
        'und die Anweisung selbst');
    pruefe(/Tabelle1!G2/.test(log) && /fmt="dd\.mm\.yyyy"/.test(log),
        'der betroffene Eintrag steht mit Adresse und Format im Protokoll',
        JSON.stringify(log.slice(0, 400)));
    // ⚠ WAS HIER ZU MESSEN IST, hat der erste Lauf dieses Waechters
    // korrigiert: `fullStatement` TRAEGT die Werte (`… = [["=E2*F2"]]`) – eine
    // Zusage "keine Zellinhalte" waere gebrochen gewesen. Messbar ist, dass
    // (a) die EIGENEN Zeilen keine Inhalte tragen und (b) die Anweisung von
    // Excel gedeckelt ist. Der Hinweistext der Ansicht sagt das auch.
    const eigen = log.split('\n').filter(l => /\[schreiben\]\s+\[\d+\]/.test(l)).join('\n');
    pruefe(eigen.length > 0 && eigen.indexOf('=E2*F2') < 0,
        'die EIGENEN Protokollzeilen tragen Adresse und Format, aber keinen Inhalt',
        JSON.stringify(eigen));
    pruefe(/Ausschnitt dieser Anweisung/.test(I18N) || /gekürzten Ausschnitt/.test(I18N),
        'und der Hinweistext sagt, dass Excels Anweisung Werte enthalten kann');
    // Nach einem Fehlschlag sind die Knoepfe der richtige naechste Schritt.
    pruefe(!!doc.getElementById('xl-apply'),
        'nach dem Fehlschlag steht "Uebernehmen" wieder bereit');
    dom.window.close();
}

abschnitt('3b. Eine lange Anweisung wird gedeckelt – mit Ausweis');
{
    // Ohne Deckel steht eine Wertematrix mit tausend Zellen im Protokoll:
    // unlesbar, und beim Weitergeben ein Datenabfluss in Groesse der Tabelle.
    const { win, z, dom } = fenster({ auto: '1', schreibFehler: true, lang: true });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    const log = win.document.getElementById('xl-log-out').textContent;
    const zeile = log.split('\n').find(l => /statement=/.test(l)) || '';
    pruefe(zeile.length > 0, '3b eine Anweisungszeile ist da');
    pruefe(zeile.length < 400, '3b sie ist gedeckelt', 'Laenge ' + zeile.length);
    pruefe(/Zeichen gekürzt/.test(zeile),
        '3b und die Kuerzung wird AUSGEWIESEN (kein stiller Schnitt)',
        JSON.stringify(zeile.slice(-120)));
    dom.window.close();
}

abschnitt('4. Auto-Uebernahme: kein "Uebernehmen", solange geschrieben wird');
{
    // Der Diff wird gezeichnet, BEVOR der Schreibvorgang endet. Bis 2026-09-09
    // standen dort Knoepfe – bei einem grossen Bereich sekundenlang, und wer
    // druckte, schrieb zweimal.
    const { win, z, dom } = fenster({ auto: '1' });
    await warte(60);
    const f = win.document.getElementById('xl-frage');
    f.value = 'Trage die Marge ein';
    win.document.getElementById('xl-send').click();
    // Fruehes Fenster: die Antwort ist da, der Schreibvorgang laeuft noch.
    let sahKnopf = false;
    for (let i = 0; i < 14; i++) {
        await warte(12);
        if (win.document.getElementById('xl-apply')) sahKnopf = true;
    }
    await warte(220);
    const doc = win.document;
    pruefe(!sahKnopf,
        'waehrend der automatischen Uebernahme erscheint KEIN "Uebernehmen"');
    pruefe(!doc.getElementById('xl-apply'), 'und danach auch nicht');
    pruefe(z.geschrieben.length > 0, 'geschrieben wurde trotzdem');
    dom.window.close();
}

abschnitt('5. OHNE Automatik bleiben die Knoepfe – sonst waere es unbedienbar');
{
    const { win, z, dom } = fenster({ auto: '0' });
    await warte(60);
    await frageStellen(win);
    await warte(200);
    pruefe(!!win.document.getElementById('xl-apply'),
        'ohne Automatik steht "Uebernehmen" da');
    pruefe(z.geschrieben.length === 0, 'und es wurde NICHTS geschrieben');
    dom.window.close();
}

abschnitt('6. Der Kommentar wird ERSETZT, nicht ein zweites Mal angelegt');
{
    // Wer denselben Bereich zweimal bearbeitet (der Normalfall beim
    // Nachbessern), traefe sonst auf "es gibt hier schon einen Kommentar".
    const { win, z, dom } = fenster({ auto: '1', kommentarDa: true });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    pruefe(z.gesuchteKommentare.length > 0,
        'es wird nachgesehen, ob schon ein Kommentar da ist');
    pruefe(z.ersetzt.length > 0, 'ein vorhandener Kommentar wird ERSETZT',
        JSON.stringify(z.ersetzt));
    pruefe(z.kommentare.length === 0,
        'und NICHT zusaetzlich angelegt', JSON.stringify(z.kommentare));
    dom.window.close();
}

abschnitt('7. Markierung abgewaehlt = gar kein Kosmetik-Lauf');
{
    const { win, z, dom } = fenster({ auto: '1', mark: '0' });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    pruefe(z.geschrieben.length > 0, 'geschrieben wird');
    pruefe(z.markiert.length === 0 && z.kommentare.length === 0,
        'aber weder markiert noch kommentiert');
    dom.window.close();
}

abschnitt('8. Protokoll bedienen');
{
    const { win, z, dom } = fenster({ auto: '1', schreibFehler: true });
    await warte(60);
    await frageStellen(win);
    await warte(260);
    const doc = win.document;
    let kopiert = '';
    win.navigator.clipboard = { writeText: (t) => { kopiert = t; return Promise.resolve(); } };
    doc.getElementById('xl-log-copy').click();
    await warte(40);
    pruefe(kopiert.length > 50 && /GeneralException/.test(kopiert),
        'der Kopier-Knopf legt das ganze Protokoll in die Zwischenablage');
    doc.getElementById('xl-log-clear').click();
    await warte(20);
    pruefe(/Noch nichts protokolliert/.test(doc.getElementById('xl-log-out').textContent),
        'und "Leeren" raeumt es ab');
    dom.window.close();
}

abschnitt('9. Regeln am Quelltext');
{
    // Der Fehlschlag des Kopierens wird GEMELDET: navigator.clipboard fehlt in
    // unsicheren Kontexten ganz, und "hat scheinbar geklappt" waere hier der
    // teuerste Ausgang.
    pruefe(/xl\.log_copy_failed/.test(JS_CODE),
        'ein gescheitertes Kopieren wird gemeldet');
    // console.warn ist im Aufgabenfenster unerreichbar.
    pruefe(JS_CODE.indexOf('console.warn') < 0,
        'kein console.warn mehr – die Diagnose muss SICHTBAR sein',
        'noch vorhanden: ' + (JS_CODE.match(/console\.warn[^\n]*/g) || []).join(' | '));
    // Die Kosmetik darf nicht zurueck in den Schreib-Lauf.
    const iSchreib = JS_CODE.indexOf('function uebernehmenJetzt');
    const iKosm = JS_CODE.indexOf('function kosmetik');
    pruefe(iSchreib > 0 && iKosm > iSchreib,
        'kosmetik() ist eine EIGENE Funktion');
    const rumpf = JS_CODE.slice(iSchreib, iKosm);
    pruefe(rumpf.indexOf('comments.add') < 0,
        'im Schreib-Lauf steht KEIN comments.add mehr',
        'sonst kippt eine Verzierung den ganzen Vorgang');
    // i18n in BEIDEN Sprachen – sonst steht im englischen Fenster der Schluessel.
    const fehlt = ['xl.log', 'xl.log_note', 'xl.log_copy', 'xl.log_clear',
                   'xl.log_empty', 'xl.log_copied', 'xl.log_copy_failed',
                   'xl.log_cleared', 'xl.applying', 'xl.write_failed_hint']
        .filter(k => (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':", 'g')) || []).length < 2);
    pruefe(fehlt.length === 0, 'alle neuen Texte gibt es in DE und EN',
        'fehlt: ' + fehlt.join(', '));
}

console.log('\n' + '='.repeat(54));
console.log('Bestanden: ' + ok + ' / Fehlgeschlagen: ' + fail);
bilanz = true;
clearTimeout(hund);
process.exit(fail ? 1 : 0);

})().catch(e => {
    console.log('\n\x1b[31mABBRUCH: ' + (e && e.stack || e) + '\x1b[0m');
    console.log('Bestanden: ' + ok + ' / Fehlgeschlagen: ' + (fail + 1) + ' (ABGEBROCHEN)');
    bilanz = true;
    process.exit(1);
});
