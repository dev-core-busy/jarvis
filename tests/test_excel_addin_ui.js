#!/usr/bin/env node
/**
 * Excel-Add-in: Aufgabenfenster.
 *
 * Geprueft wird gegen die ECHTEN Dateien (taskpane.html, excel.js, i18n.js) –
 * ein Test, der sein Markup selbst baut, prueft nur seine eigene Annahme
 * (Lehre vom 2026-08-12, als ein falscher Mock zehn Pruefungen gruen liess,
 * obwohl das Laden der Konfiguration kaputt war).
 *
 * DER SCHWERPUNKT liegt auf `formelVerschieben`. Schreibt man in G2:G40 ueberall
 * dieselbe Formel `=E2*F2`, steht sie auch in G40 – Excel passt relative
 * Bezuege nur beim KOPIEREN an. Der Kernfall der Anforderung ("trage in G2:G40
 * die Marge ein") haengt also an dieser Funktion, sobald ExcelApi 1.9 (copyFrom)
 * nicht verfuegbar ist.
 *
 *   node tests/test_excel_addin_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/taskpane.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

/* Kommentare entfernen. NOETIG, nicht kosmetisch: mehrere Waechter in diesem
   Projekt haben ihre eigene BEGRUENDUNG gelesen und waren dadurch wertlos
   (zuletzt am 2026-08-19). Wer auf "kein window.confirm" prueft, darf den
   Kommentar nicht mitzaehlen, der erklaert, warum es keins gibt. */
function nurCode(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}
const JS_CODE = nurCode(JS);

/* ══════════════════════════════════════════════════════════════════════
   0. Reine Funktionen – ueber window._xlIntern
   ══════════════════════════════════════════════════════════════════════ */
abschnitt('0. Formelbezuege verschieben');

function fensterMitStub(officeDa) {
    const dom = new JSDOM(HTML, { url: 'https://jarvis.test/excel-addin/taskpane.html?mv=1.0.0.0',
                                  runScripts: 'outside-only' });
    const win = dom.window;
    win.fetch = () => Promise.resolve({
        status: 200, ok: true, json: () => Promise.resolve({ ok: true, version: '1.0.0.0' })
    });
    // Office-Stub, damit officeErmitteln() SOFORT aufloest – ohne ihn laeuft
    // die 4-Sekunden-Wartegrenze und der Test haengt.
    if (officeDa) {
        win.Office = {
            HostType: { Excel: 'Excel' },
            onReady: (cb) => cb({ host: 'Excel' }),
            context: { requirements: { isSetSupported: () => false } }
        };
    }
    win.eval(JS);
    return { dom, win };
}

const { dom: dom0, win: win0 } = fensterMitStub(true);
const I = win0._xlIntern || {};
pruefe(typeof I.formelVerschieben === 'function', 'formelVerschieben ist erreichbar');

const fv = I.formelVerschieben || (() => '');

// Der Kernfall: eine Zeile nach unten.
pruefe(fv('=E2*F2', 1, 0) === '=E3*F3', 'relative Bezuege wandern mit der Zeile',
       fv('=E2*F2', 1, 0));
pruefe(fv('=E2*F2', 0, 1) === '=F2*G2', 'relative Bezuege wandern mit der Spalte',
       fv('=E2*F2', 0, 1));
pruefe(fv('=SUM(A1:A10)', 2, 0) === '=SUM(A3:A12)', 'Bereiche wandern vollstaendig',
       fv('=SUM(A1:A10)', 2, 0));

// Absolute Anteile sind der Zweck von '$' – sie duerfen NICHT wandern.
pruefe(fv('=$E$2*F2', 1, 0) === '=$E$2*F3', 'absolute Bezuege bleiben stehen',
       fv('=$E$2*F2', 1, 0));
pruefe(fv('=E$2*F2', 1, 0) === '=E$2*F3', 'gemischter Bezug: Zeile fest',
       fv('=E$2*F2', 1, 0));
pruefe(fv('=$E2*F2', 0, 1) === '=$E2*G2', 'gemischter Bezug: Spalte fest',
       fv('=$E2*F2', 0, 1));

// Zeichenketten sind KEINE Bezuege. In =IF(A1="B2",…) ist B2 Text.
pruefe(fv('=IF(A1="B2",1,0)', 1, 0) === '=IF(A2="B2",1,0)',
       'Bezug in einer Zeichenkette wird nicht verschoben', fv('=IF(A1="B2",1,0)', 1, 0));
pruefe(fv('=CONCAT("A1",A1)', 1, 0) === '=CONCAT("A1",A2)',
       'Text und Bezug im selben Aufruf werden unterschieden', fv('=CONCAT("A1",A1)', 1, 0));

// Funktionsnamen duerfen nicht getroffen werden.
pruefe(fv('=LOG10(A1)', 1, 0) === '=LOG10(A2)', 'Funktionsname mit Ziffern bleibt heil',
       fv('=LOG10(A1)', 1, 0));
pruefe(fv('=SUM(A1:A2)*2', 1, 0) === '=SUM(A2:A3)*2', 'Zahlen ausserhalb von Bezuegen bleiben',
       fv('=SUM(A1:A2)*2', 1, 0));

// Funktionsnamen, die auf Ziffern enden, sind die gefaehrlichste Falle: ohne
// Klammer-Lookahead wird aus =LOG10( ein =LOG11( – die Formel ist lautlos
// zerstoert.
pruefe(fv('=LOG10(A1)+LOG10(B1)', 1, 0) === '=LOG10(A2)+LOG10(B2)',
       'Funktionsnamen mit Ziffern bleiben auch mehrfach heil',
       fv('=LOG10(A1)+LOG10(B1)', 1, 0));
pruefe(fv('=T1(A1)', 1, 0) === '=T1(A2)', 'benannte Funktion mit Ziffer bleibt heil',
       fv('=T1(A1)', 1, 0));

// Blattbezug: der Blattname darf nicht als Spalte gelesen werden.
pruefe(fv('=Blatt2!A1', 1, 0) === '=Blatt2!A2', 'Bezug mit Blattname wandert korrekt',
       fv('=Blatt2!A1', 1, 0));
// Blattname mit Leerzeichen steht in EINFACHEN Anfuehrungszeichen. Ohne
// Sonderbehandlung wird daraus ein Bezug und der Blattname veraendert sich.
pruefe(fv("='Q1 2026'!A1", 1, 0) === "='Q1 2026'!A2",
       'Blattname in Anfuehrungszeichen bleibt unveraendert',
       fv("='Q1 2026'!A1", 1, 0));
pruefe(fv("=SUM('Q1 2026'!A1:A5)", 2, 0) === "=SUM('Q1 2026'!A3:A7)",
       'Bereich hinter einem zitierten Blattnamen wandert trotzdem',
       fv("=SUM('Q1 2026'!A1:A5)", 2, 0));

// Ueber den Rand hinaus ergibt in Excel selbst #REF!.
pruefe(fv('=A1', -1, 0) === '=#REF!', 'ueber den Blattrand hinaus wird #REF!',
       fv('=A1', -1, 0));

// Kein Versatz = unveraendert (Schnellpfad).
pruefe(fv('=E2*F2', 0, 0) === '=E2*F2', 'ohne Versatz bleibt die Formel unveraendert');

pruefe(I.spalteZuIndex('A') === 1 && I.spalteZuIndex('Z') === 26 &&
       I.spalteZuIndex('AA') === 27 && I.spalteZuIndex('XFD') === 16384,
       'Spaltenbuchstaben werden korrekt umgerechnet');
pruefe(I.indexZuSpalte(1) === 'A' && I.indexZuSpalte(27) === 'AA' &&
       I.indexZuSpalte(16384) === 'XFD', 'Rueckrichtung stimmt ebenfalls');

abschnitt('0b. Versionsvergleich');
const vn = I.versionNeuer || (() => false);
pruefe(vn('1.1.0.0', '1.0.0.0') === true, 'hoehere Fassung wird erkannt');
pruefe(vn('1.0.0.0', '1.0.0.0') === false, 'gleiche Fassung ist nicht neuer');
// String-Vergleich haelt "1.10" fuer kleiner als "1.9" - der Fehler faellt
// erst beim zehnten Manifest auf.
pruefe(vn('1.10.0.0', '1.9.0.0') === true, 'segmentweise NUMERISCH, nicht als Text');

/* ══════════════════════════════════════════════════════════════════════
   1. Markup
   ══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Markup des Fensters');
const doc0 = win0.document;

pruefe(!!doc0.getElementById('xl-login'), 'Anmeldebereich vorhanden');
pruefe(!!doc0.getElementById('xl-app'), 'Anwendungsbereich vorhanden');
pruefe(!!doc0.getElementById('xl-chat'), 'Verlauf vorhanden');
pruefe(!!doc0.getElementById('xl-frage'), 'Eingabefeld vorhanden');
pruefe(!!doc0.getElementById('xl-ctx'), 'Bezugszeile vorhanden');
pruefe(!!doc0.getElementById('xl-undo'), 'Rueckgaengig-Knopf vorhanden');

// Der Bestaetigungsdialog ist Pflicht: window.confirm ist in Office-
// Aufgabenfenstern je nach Host unterdrueckt und liefert dann keinen Wert.
const ask = doc0.getElementById('xl-ask');
pruefe(!!ask, 'eigener Bestaetigungsdialog im Markup');
pruefe(!!ask && !!doc0.getElementById('xl-ask-yes') && !!doc0.getElementById('xl-ask-no'),
       'Dialog hat beide Knoepfe');
pruefe(!!ask && ask.parentNode === doc0.body,
       'Dialog ist direktes Kind von <body> (sonst greift der z-index nicht)');

// Ein Band, das ohne Beleg erscheint, ist eine Behauptung.
const band = doc0.getElementById('xl-upd');
pruefe(!!band && band.classList.contains('hidden'),
       'Update-Band startet verborgen');

pruefe(/office\.js/.test(HTML) && /<script async[^>]+office\.js/.test(HTML),
       'office.js wird mit `async` eingebunden, nicht mit `defer`');
pruefe(!/<script defer[^>]+office\.js/.test(HTML),
       'kein defer auf office.js (blockiert DOMContentLoaded und damit den Start)');

const posI18n = HTML.indexOf('js/i18n.js');
const posExcel = HTML.indexOf('excel-addin/excel.js');
pruefe(posI18n > 0 && posExcel > posI18n, 'excel.js laedt NACH i18n.js');
pruefe(HTML.indexOf('js/branding.js') > 0, 'branding.js ist eingebunden');
pruefe(/class="[^"]*topbar-avatar/.test(HTML),
       'Marken-Haken .topbar-avatar vorhanden (sonst bleibt das Jarvis-Zeichen stehen)');
pruefe(/class="brand-app-name"/.test(HTML), 'Marken-Name .brand-app-name vorhanden');

/* ══════════════════════════════════════════════════════════════════════
   2. Quelltext-Regeln
   ══════════════════════════════════════════════════════════════════════ */
abschnitt('2. Regeln im Quelltext');

pruefe(!/\bwindow\.confirm\s*\(/.test(JS_CODE) && !/(^|[^.\w])confirm\s*\(/.test(JS_CODE),
       'kein window.confirm (in Aufgabenfenstern wirkungslos)');
pruefe(!/(^|[^.\w])alert\s*\(/.test(JS_CODE), 'kein alert');
pruefe(!/(^|[^.\w])prompt\s*\(/.test(JS_CODE), 'kein prompt');

// Der Server liest `totp_code`. Ein `totp` ginge ins Leere und erzeugte eine
// Anmeldeschleife (im Outlook-Add-in genau so passiert).
pruefe(/totp_code/.test(JS_CODE), 'sendet das 2FA-Feld als totp_code');
const APPJS = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
pruefe(/totp_code/.test(APPJS),
       'Gegenprobe: app.js benutzt denselben Feldnamen');

// Abmelden muss VOR dem Verwerfen des Tokens raus und keepalive tragen.
pruefe(/keepalive/.test(JS_CODE), 'Abmeldung mit keepalive');
const posLogout = JS_CODE.indexOf("'/api/logout'");
const posClear = JS_CODE.indexOf('tokenLoeschen();', posLogout > 0 ? posLogout : 0);
pruefe(posLogout > 0 && posClear > posLogout,
       'Abmelde-Signal geht vor dem Verwerfen des Tokens raus');

// Der Ueberblick darf NIE ein ganzes Blatt mitschicken.
pruefe(/getUsedRangeOrNullObject/.test(JS_CODE),
       'benutzt getUsedRangeOrNullObject (getUsedRange wirft bei leerem Blatt)');
pruefe(/getRangeByIndexes/.test(JS_CODE),
       'liest nur einen begrenzten Ausschnitt je Blatt, nicht den ganzen benutzten Bereich');

// Fehlerwerte nach dem Schreiben pruefen statt einen Formelparser zu bauen.
pruefe(/NAME\\\?/.test(JS_CODE) && /load\('values'\)/.test(JS_CODE),
       'prueft nach dem Schreiben auf Fehlerwerte');

// Snapshot VOR dem Schreiben – Office.js-Schreibvorgaenge sind nicht im
// Undo-Stack von Excel.
const posSnap = JS_CODE.indexOf('schnappschuss.push');
const posWrite = JS_CODE.indexOf('z.r.formulas = m');
pruefe(posSnap > 0 && posWrite > 0 && posSnap < posWrite,
       'Schnappschuss wird VOR dem Schreiben genommen');

// copyFrom nur, wenn ExcelApi 1.9 wirklich da ist.
pruefe(/isSetSupported\('ExcelApi', '1\.9'\)/.test(JS_CODE),
       'prueft ExcelApi 1.9, bevor copyFrom benutzt wird');
pruefe(/_kann19/.test(JS_CODE) && /formelVerschieben\(/.test(JS_CODE),
       'hat einen Rueckfall fuer Staende ohne 1.9');

/* ══════════════════════════════════════════════════════════════════════
   3. Ablauf: fragen -> Diff -> uebernehmen
   ══════════════════════════════════════════════════════════════════════ */
abschnitt('3. Ablauf im Fenster');

function excelStub(zustand) {
    // Minimaler, aber ECHT benutzter Excel-Kontext. Er merkt sich, was
    // geschrieben wurde – daran haengen die Pruefungen unten.
    const bereich = (adr) => ({
        address: 'Tabelle1!' + adr, rowCount: 1, columnCount: 1,
        values: [['alt']], formulas: [['alt']], valueTypes: [['String']],
        load() { }, getCell() { return bereich(adr); },
        copyFrom() { zustand.copyFrom = true; },
        set formulas__(v) { },
    });
    const machRange = (adr) => {
        const r = {
            address: 'Tabelle1!' + adr, rowCount: 1, columnCount: 1,
            values: [['alt']], _formulas: [['alt']], valueTypes: [['String']],
            load() { }, getCell() { return machRange(adr); },
            copyFrom() { zustand.copyFrom = true; }
        };
        Object.defineProperty(r, 'formulas', {
            get() { return this._formulas; },
            set(v) { this._formulas = v; zustand.geschrieben.push({ adr, v }); }
        });
        return r;
    };
    const blatt = (name) => ({
        name: name,
        getUsedRangeOrNullObject() {
            return { address: 'A1:C3', rowCount: 3, columnCount: 3, rowIndex: 0,
                     columnIndex: 0, isNullObject: false, load() { } };
        },
        getRangeByIndexes() {
            return { values: [['Artikel', 'Preis', 'Menge'], ['A', 1, 2]],
                     valueTypes: [['String', 'String', 'String'],
                                  ['String', 'Double', 'Double']], load() { } };
        },
        getRange: (adr) => machRange(adr),
        load() { }
    });
    return {
        RangeCopyType: { formulas: 'formulas' },
        run(fn) {
            const ctx = {
                workbook: {
                    name: 'Mappe1.xlsx',
                    worksheets: {
                        items: [{ name: 'Tabelle1' }],
                        load() { },
                        getItem: (n) => blatt(n),
                        getActiveWorksheet: () => blatt('Tabelle1'),
                        onSelectionChanged: { add() { } }
                    },
                    getSelectedRange() {
                        return {
                            address: 'Tabelle1!B2:B3', rowCount: 2, columnCount: 1,
                            values: [[1], [2]], formulas: [['1'], ['2']],
                            worksheet: { name: 'Tabelle1', load() { } },
                            load() { }
                        };
                    },
                    load() { }
                },
                sync() { return Promise.resolve(); }
            };
            return Promise.resolve(fn(ctx));
        }
    };
}

function warte(ms) { return new Promise(r => setTimeout(r, ms)); }

(async function ablauf() {
    const zustand = { geschrieben: [], copyFrom: false, gesendet: [] };
    const dom = new JSDOM(HTML, { url: 'https://jarvis.test/excel-addin/taskpane.html?mv=1.0.0.0',
                                  runScripts: 'outside-only' });
    const win = dom.window;
    win.Office = {
        HostType: { Excel: 'Excel' },
        onReady: (cb) => cb({ host: 'Excel' }),
        context: { requirements: { isSetSupported: () => false } }
    };
    win.Excel = excelStub(zustand);
    win.localStorage.setItem('jarvis_token', 'T');

    win.fetch = (url, opt) => {
        const pfad = String(url).split('?')[0];
        zustand.gesendet.push({ pfad, opt });
        const j = (d) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/excel-addin/version') return j({ ok: true, version: '1.0.0.0' });
        if (pfad === '/api/me') return j({ username: 'u', permissions: { excel: true } });
        if (pfad === '/api/excel/ask') {
            return j({
                ok: true, text: 'Ich schlage eine Margenspalte vor.',
                aenderungen: [{ blatt: 'Tabelle1', adresse: 'G2', formel: '=E2*F2',
                                begruendung: 'Marge' }],
                abgelehnt: [{ adresse: 'H2', grund: 'WEBSERVICE ist nicht erlaubt.' }],
                zusammenfassung: 'Eine Spalte', brauche: [], runde: 1
            });
        }
        return j({ ok: true });
    };
    win.eval(JS);
    await warte(60);

    const d = win.document;
    pruefe(!d.getElementById('xl-app').classList.contains('hidden'),
           'nach gueltigem Token wird die Anwendung gezeigt');
    pruefe(zustand.gesendet.some(g => g.pfad === '/api/me'),
           'Freigabe wird vor dem ersten Chat geprueft');

    // Frage stellen
    d.getElementById('xl-frage').value = 'Berechne die Marge';
    d.getElementById('xl-send').click();
    await warte(80);

    const anfrage = zustand.gesendet.filter(g => g.pfad === '/api/excel/ask').pop();
    pruefe(!!anfrage, 'Frage wird an /api/excel/ask gesendet');
    const rumpf = anfrage ? JSON.parse(anfrage.opt.body) : {};
    pruefe(rumpf.frage === 'Berechne die Marge', 'Fragetext geht mit');
    pruefe(!!rumpf.ueberblick && Array.isArray(rumpf.ueberblick.blaetter) &&
           rumpf.ueberblick.blaetter.length === 1,
           'Mappen-Ueberblick wird mitgeschickt');
    pruefe(!!rumpf.ueberblick && !!rumpf.ueberblick.auswahl &&
           rumpf.ueberblick.auswahl.adresse === 'B2:B3',
           'aktuelle Auswahl wird mitgeschickt');
    const bl = (rumpf.ueberblick && rumpf.ueberblick.blaetter || [])[0] || {};
    pruefe(Array.isArray(bl.kopf) && bl.kopf[0] === 'Artikel',
           'Kopfzeile des Blattes wird uebermittelt');
    pruefe(Array.isArray(bl.beispiele) && bl.beispiele.length <= 4,
           'nur wenige Beispielzeilen, nicht das ganze Blatt');

    // Diff sichtbar?
    const diff = d.querySelector('.xl-diff');
    pruefe(!!diff, 'Diff-Ansicht wird gezeigt');
    pruefe(!!diff && /G2/.test(diff.textContent), 'Diff nennt die Zelladresse');
    pruefe(!!diff && /=E2\*F2/.test(diff.textContent), 'Diff nennt die neue Formel');
    // Abgelehnte Eintraege muessen SICHTBAR sein - sonst haelt der Benutzer den
    // gekuerzten Vorschlag fuer den ganzen.
    pruefe(!!d.querySelector('.xl-rej'), 'abgewiesene Eintraege werden angezeigt');
    pruefe(!!d.querySelector('.xl-rej') &&
           /WEBSERVICE/.test(d.querySelector('.xl-rej').textContent),
           'Ablehnungsgrund steht dabei');

    // Verwerfen schreibt NICHT.
    d.getElementById('xl-discard').click();
    await warte(20);
    pruefe(zustand.geschrieben.length === 0, 'Verwerfen schreibt nichts in die Mappe');
    pruefe(!d.querySelector('.xl-diff'), 'nach dem Verwerfen ist der Diff weg');

    // Erneut fragen und diesmal uebernehmen.
    d.getElementById('xl-frage').value = 'nochmal';
    d.getElementById('xl-send').click();
    await warte(80);
    pruefe(!!d.getElementById('xl-apply'), 'Uebernehmen-Knopf vorhanden');

    d.getElementById('xl-apply').click();
    await warte(20);
    const dlg = d.getElementById('xl-ask');
    pruefe(!!dlg && !dlg.classList.contains('hidden'),
           'Uebernehmen fragt ueber den EIGENEN Dialog nach');
    pruefe(zustand.geschrieben.length === 0, 'vor der Bestaetigung wird nichts geschrieben');

    // Abbrechen -> nichts geschrieben
    d.getElementById('xl-ask-no').click();
    await warte(30);
    pruefe(zustand.geschrieben.length === 0, 'Abbrechen im Dialog schreibt nichts');

    // Jetzt wirklich bestaetigen
    d.getElementById('xl-apply').click();
    await warte(20);
    d.getElementById('xl-ask-yes').click();
    await warte(80);
    pruefe(zustand.geschrieben.length > 0, 'nach Bestaetigung wird geschrieben');
    const g = zustand.geschrieben[0] || {};
    pruefe(!!g.v && g.v[0] && g.v[0][0] === '=E2*F2',
           'die vorgeschlagene Formel landet in der Zelle',
           JSON.stringify(g.v));
    pruefe(d.getElementById('xl-undo').style.display !== 'none',
           'Rueckgaengig-Knopf erscheint nach dem Schreiben');

    win.close();

    /* ══════════════════════════════════════════════════════════════════
       4. i18n
       ══════════════════════════════════════════════════════════════════ */
    abschnitt('4. Uebersetzungen');
    // Jeder im Fenster benutzte Schluessel muss in BEIDEN Sprachen existieren.
    const keys = new Set();
    (JS.match(/T\('([a-z0-9_.]+)'/g) || []).forEach(m => {
        keys.add(m.replace(/^T\('/, '').replace(/'$/, ''));
    });
    (HTML.match(/data-i18n(?:-title|-placeholder)?="([a-z0-9_.]+)"/g) || []).forEach(m => {
        keys.add(m.replace(/^data-i18n(?:-title|-placeholder)?="/, '').replace(/"$/, ''));
    });
    const xlKeys = [...keys].filter(k => k.startsWith('xl.'));
    pruefe(xlKeys.length >= 20, 'das Fenster benutzt die xl.-Schluessel (' + xlKeys.length + ')');

    // Die i18n-Datei hat einen DE- und einen EN-Block. Geprueft wird, dass
    // jeder Schluessel ZWEIMAL vorkommt.
    let fehlend = [];
    xlKeys.forEach(k => {
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':", 'g')) || []).length;
        if (n < 2) fehlend.push(k + ' (' + n + 'x)');
    });
    pruefe(fehlend.length === 0, 'alle xl.-Schluessel in DE UND EN vorhanden',
           fehlend.slice(0, 6).join(', '));

    // Platzhalter global ersetzen (Lehre von sessions.hint: String.replace mit
    // einem String tauscht nur das ERSTE Vorkommen).
    const updText = (I18N.match(/'xl\.upd_text':\s*'([^']*)'/) || [])[1] || '';
    const mehrfach = (updText.match(/\{alt\}/g) || []).length > 1 ||
                     (updText.match(/\{neu\}/g) || []).length > 1;
    pruefe(!mehrfach || /replace\(\/\\\{(alt|neu)\\\}\/g/.test(JS_CODE),
           'Platzhalter kommen hoechstens einmal vor ODER werden global ersetzt');

    /* ══════════════════════════════════════════════════════════════════
       5. Symbol-Semantik
       ══════════════════════════════════════════════════════════════════ */
    abschnitt('5. Symbole');
    // Projektregel: Muelleimer = loeschen, x = schliessen. Das Fenster hat
    // keinen Loeschknopf - also darf auch kein Muelleimer darin stehen.
    pruefe(!/JarvisIcons\.trash|🗑/.test(HTML + JS),
           'kein Muelleimer (es wird hier nichts Gespeichertes geloescht)');
    // Emojis werden je nach System farbig gerendert und folgen keinem Theme.
    const emojiRe = /[☀-➿\u{1F300}-\u{1F9FF}]/u;
    const btnTexte = (HTML.match(/<button[^>]*>([^<]*)</g) || []);
    const mitEmoji = btnTexte.filter(b => emojiRe.test(b));
    pruefe(mitEmoji.length === 0, 'keine Emojis in Knopfbeschriftungen',
           mitEmoji.slice(0, 3).join(' '));

    /* ══════════════════════════════════════════════════════════════════
       6. Einstellungs-Reiter: klappen die Container wirklich?
       ══════════════════════════════════════════════════════════════════ */
    abschnitt('6. Klapp-Container im Excel-Reiter');
    // GEMELDET 2026-08-20: sie liessen sich nicht auf- und zuklappen. Das
    // Markup trug die Klassen, aber NICHTS band sie – die Verdrahtung laeuft
    // ueber _collapseInit in app.js. Geprueft wird mit dem ECHTEN Code gegen
    // das ECHTE Markup; ein Test, der beides nachbaut, bestaetigt nur seine
    // eigene Annahme.
    const SETH = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
    const APPJ = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
    const ia = SETH.indexOf('<div id="settings-tab-excel"');
    const ja = SETH.indexOf('<div id="settings-tab-tracks"');
    pruefe(ia > 0 && ja > ia, 'Excel-Panel im Markup gefunden');

    const domK = new JSDOM('<body>' + SETH.slice(ia, ja) + '</body>',
        { url: 'https://x.test/settings', runScripts: 'outside-only' });
    const winK = domK.window;
    const s1 = APPJ.indexOf('function _collapseInit(sections)');
    const e1 = APPJ.indexOf('function _initProfilesCollapse');
    const s2 = APPJ.indexOf('function _initExcelCollapse()');
    const e2 = APPJ.indexOf('window.initExcelCollapse = _initExcelCollapse;');
    pruefe(s1 >= 0 && s2 >= 0 && e2 > s2,
           '_collapseInit und _initExcelCollapse sind in app.js vorhanden');
    if (s1 >= 0 && s2 >= 0) {
        winK.eval(APPJ.slice(s1, e1) + '\n' + APPJ.slice(s2, e2) + '\n_initExcelCollapse();');
        ['xa-sect-install', 'xa-sect-limits', 'xa-sect-info'].forEach(function (id) {
            const hdr = winK.document.getElementById(id + '-hdr');
            const body = winK.document.getElementById(id + '-body');
            const tog = winK.document.getElementById(id + '-tog');
            if (!hdr || !body || !tog) { pruefe(false, id + ': Markup unvollstaendig'); return; }
            const vorher = body.style.display;
            hdr.click();
            pruefe(body.style.display !== vorher, id + ': ein Klick klappt um');
            hdr.click();
            pruefe(body.style.display === vorher, id + ': der zweite Klick stellt es zurueck');
            // Ein Pfeil, der stehen bleibt, laesst den Klick wirkungslos aussehen.
            pruefe(tog.textContent === '▼' || tog.textContent === '▶',
                   id + ': der Pfeil folgt dem Zustand');
        });
    }
    winK.close();

    console.log('\n' + '='.repeat(50));
    console.log('Bestanden: ' + ok + ' / Fehlgeschlagen: ' + fail);
    dom0.window.close();
    process.exit(fail ? 1 : 0);
})().catch(e => {
    console.error('\nABBRUCH:', e && e.stack || e);
    process.exit(1);
});
