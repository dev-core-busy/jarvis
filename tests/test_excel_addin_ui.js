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
let JSDOM, VirtualConsole;
try {
    const _j = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');
    JSDOM = _j.JSDOM; VirtualConsole = _j.VirtualConsole;
}
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

function fensterMitStub(officeDa, vorher) {
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
    // Optional ein Skript VOR excel.js (theme.js) – die Reihenfolge ist die
    // des Fensters: theme.js bindet zuerst, excel.js haengt seinen eigenen
    // Handler daneben.
    if (vorher) win.eval(vorher);
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
// Der Rueckgaengig-Knopf ist auf Vorgabe des Nutzers entfallen (2026-08-24):
// Strg+Z in Excel holt die Aenderung zurueck. Er darf nicht zurueckkommen –
// zwei Rueckwege nebeneinander waeren zwei Wahrheiten.
pruefe(!doc0.getElementById('xl-undo'), 'kein eigener Rueckgaengig-Knopf mehr');
pruefe(HTML.indexOf('xl-undo') < 0 && JS_CODE.indexOf('xl-undo') < 0,
       '... und kein toter Code dazu');
pruefe(JS_CODE.indexOf('schnappschuss') < 0,
       'auch der Schnappschuss vor dem Schreiben ist weg (Strg+Z ist der Rueckweg)');
// Automatische Uebernahme: Vorgabe AN. Das `checked` steht im Markup.
const autoBox = doc0.getElementById('xl-auto');
pruefe(!!autoBox, 'Kontrollkaestchen "automatisch uebernehmen" vorhanden');
pruefe(!!autoBox && autoBox.checked === true, 'und es ist per Vorgabe angekreuzt');

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

/* Angemeldetes Fenster mit Excel-Attrappe. EIN Aufbau fuer Abschnitt 3
   (Handbetrieb) und den Auto-Abschnitt – zwei Fassungen desselben Stubs waeren
   beim naechsten Feld auseinandergelaufen. `opt.auto` legt den gespeicherten
   Zustand der Automatik VOR dem Laden fest. */
function angemeldetesFenster(opt) {
    opt = opt || {};
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
    if (opt.auto !== undefined) {
        win.localStorage.setItem('jarvis_xl_autoapply', opt.auto);
    }

    win.fetch = (url, opt2) => {
        const pfad = String(url).split('?')[0];
        zustand.gesendet.push({ pfad, opt: opt2 });
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
    return { win, dom, zustand };
}

(async function ablauf() {
    const { win, zustand } = angemeldetesFenster();
    await warte(60);

    const d = win.document;
    // DIESER ABSCHNITT PRUEFT DEN HANDBETRIEB. Die automatische Uebernahme ist
    // per Vorgabe AN – dann gibt es gar keinen "Uebernehmen"-Knopf mehr. Also
    // ausdruecklich abwaehlen; der Auto-Fall hat seinen eigenen Abschnitt.
    d.getElementById('xl-auto').checked = false;
    d.getElementById('xl-auto').dispatchEvent(new win.Event('change', { bubbles: true }));
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

    // ENTER muss WIRKLICH senden, nicht nur `preventDefault` rufen. Der
    // Abschnitt "Enter sendet" weiter unten kann das nicht belegen (dort ist
    // niemand angemeldet) – hier laeuft der echte Weg bis zum Endpunkt.
    {
        const vorher = zustand.gesendet.filter(g => g.pfad === '/api/excel/ask').length;
        d.getElementById('xl-frage').value = 'per Enter';
        d.getElementById('xl-frage').dispatchEvent(new win.KeyboardEvent('keydown',
            { key: 'Enter', bubbles: true, cancelable: true }));
        await warte(80);
        const alle = zustand.gesendet.filter(g => g.pfad === '/api/excel/ask');
        pruefe(alle.length === vorher + 1, 'Enter loest die Anfrage wirklich aus');
        pruefe(alle.length > vorher &&
               JSON.parse(alle[alle.length - 1].opt.body).frage === 'per Enter',
               'und schickt den getippten Text mit');
        // Kein nacktes `.click()`: gibt es keinen Diff (Gegenprobe!), ist der
        // Knopf null und der WURF beendet den Testlauf – dann sieht ein
        // beissender Waechter wie ein bestandener Lauf aus (Register).
        const verw = d.getElementById('xl-discard');
        if (verw) { verw.click(); await warte(20); }
    }

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
    // Der geschriebene Vorschlag bleibt SICHTBAR – ohne Knoepfe. Bei
    // automatischer Uebernahme ist das die einzige Stelle, an der steht, was
    // in die Mappe gelaufen ist.
    pruefe(!!d.querySelector('.xl-diff-done'),
           'der uebernommene Diff bleibt mit Vermerk stehen');
    pruefe(!d.getElementById('xl-apply') && !d.getElementById('xl-discard'),
           'und traegt keine Knoepfe mehr');

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

    /* ══════════════════════════════════════════════════════════════════
       7. Der Verteil-Knopf: Download ODER Hochladen
       ══════════════════════════════════════════════════════════════════
       GEMELDET 2026-08-23: "Manifest herunterladen" ist die falsche Ansage,
       sobald ein Katalogpfad hinterlegt ist – die Datei soll dann in genau
       diese Freigabe, nicht in den Download-Ordner.

       Getrieben wird der ECHTE excel_admin.js gegen das ECHTE Markup aus
       settings.html. Ein Test, der beides nachbaut, bestaetigt nur seine
       eigene Annahme. */
    abschnitt('7. Verteil-Knopf: Download oder Hochladen');
    const ADMINJS = fs.readFileSync(path.join(ROOT, 'frontend/js/excel_admin.js'), 'utf8');
    const ADMIN_CODE = nurCode(ADMINJS);

    /* Ein frischer Reiter je Fall. `pfad` = was der Server als gespeicherten
       Katalogpfad meldet, `picker` = die Attrappe der File System Access API
       (null bedeutet: dieser Browser hat sie nicht – Firefox/Safari).
       `manifestOk`: true = immer, false = nie (localhost-Absage des Servers),
       'spaeter' = der Pruefabruf beim Oeffnen gelingt, der beim KLICK nicht,
       'nur_erster' = umgekehrt.
       DIE BEIDEN LETZTEN TRENNEN ZWEI SCHRANKEN, die bei `false` beide
       gleichzeitig greifen: 'spaeter' prueft die Reihenfolge (erst holen, dann
       Dialog), 'nur_erster' die fortwirkende Absage (`_adresseKaputt`). Mit
       `false` allein bleiben beide Gegenproben gruen, obwohl die jeweilige
       Schranke ausgebaut ist – nachgemessen 2026-08-23. */
    function adminFenster(pfad, picker, manifestOk, ordner, speicher) {
        const spur = { urls: [], koerper: [], geschrieben: [], geschlossen: 0,
                       picker: 0, pickerArg: null, navigation: 0, manifestAbrufe: 0,
                       dirPicker: 0, dirArg: null, gefragt: 0,
                       dateiName: null, create: false };
        /* Ein NICHT verhinderter Klick auf den <a> laesst jsdom "Not
           implemented: navigation" melden. Das ist hier kein Rauschen, sondern
           der BELEG, dass der Link ein Link geblieben ist – jsdom gibt das Ziel
           nicht heraus, aber den Versuch. Ohne eigene VirtualConsole landet die
           Meldung als Fehlertext in der Testausgabe und sieht wie ein Defekt aus. */
        const vc = new VirtualConsole();
        vc.on('jsdomError', (e) => {
            if (/navigation/i.test(String(e && e.message))) spur.navigation++;
            else console.error(e);
        });
        const dom = new JSDOM('<body>' + SETH.slice(ia, ja) + '</body>',
            { url: 'https://jarvis.test/settings', runScripts: 'outside-only',
              virtualConsole: vc });
        const w = dom.window;
        const XML = '<?xml version="1.0"?><OfficeApp/>';
        w.fetch = function (url, opt) {
            spur.urls.push(url);
            if (opt && opt.body) spur.koerper.push(JSON.parse(opt.body));
            if (String(url).indexOf('/api/excel-addin/version') === 0) {
                return Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve({ ok: true, version: '1.0.0.0' }) });
            }
            if (String(url).indexOf('/api/skills/') === 0) {
                return Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve({ ok: true, config: {
                        max_runden: 3, max_aenderungen: 200, katalog_pfad: pfad } }) });
            }
            if (String(url).indexOf('/excel-addin/manifest.xml') === 0) {
                spur.manifestAbrufe++;
                const scheitert = (manifestOk === false) ||
                                  (manifestOk === 'spaeter' && spur.manifestAbrufe > 1) ||
                                  (manifestOk === 'nur_erster' && spur.manifestAbrufe === 1);
                if (scheitert) {
                    // `blob()` MUSS auch hier funktionieren – eine 400-Antwort hat
                    // einen Rumpf. Ohne das waere die Gegenprobe "Pruefung
                    // ausgebaut" gruen, weil sie an einem TypeError scheitert
                    // statt an der fehlenden Pruefung (nachgemessen 2026-08-23).
                    return Promise.resolve({ ok: false, status: 400,
                        headers: { get: () => null },
                        blob: () => Promise.resolve(new w.Blob(['{"error":"nein"}'])),
                        json: () => Promise.resolve({ error: 'localhost taugt nicht' }) });
                }
                return Promise.resolve({ ok: true, status: 200,
                    // Der Dateiname MUSS aus diesem Kopf kommen und nicht
                    // nachgebaut werden, sonst laeuft er dem Branding hinterher.
                    headers: { get: (k) => (String(k).toLowerCase() === 'content-disposition'
                        ? 'attachment; filename="nexus-dp-excel-addin.xml"' : null) },
                    blob: () => Promise.resolve(new w.Blob([XML], { type: 'application/xml' })),
                    json: () => Promise.resolve({}) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        };
        if (picker !== null) {
            w.showSaveFilePicker = function (opt) {
                spur.picker++; spur.pickerArg = opt;
                return picker(w, spur);
            };
        } else {
            try { delete w.showSaveFilePicker; } catch (e) { }
        }
        /* jsdom hat KEIN indexedDB – ohne Attrappe laeuft der Code in seinen
           catch-Zweig und das Merken des Ordners waere nicht pruefbar (der Test
           waere gruen, ohne etwas zu pruefen). `speicher` wird von aussen
           uebergeben, damit ein zweites Fenster den Stand des ersten sieht: nur
           so ist "der Ordner ist nach dem Neuladen noch gemerkt" belegbar. */
        w.indexedDB = ndbStub(speicher || {});
        if (ordner) {
            w.showDirectoryPicker = function (opt) {
                spur.dirPicker++; spur.dirArg = opt;
                return Promise.resolve(ordner);
            };
        } else {
            try { delete w.showDirectoryPicker; } catch (e) { }
        }
        w.eval(ADMIN_CODE);
        return { w, spur, dom };
    }

    /* Minimales indexedDB: open/get/put, alles im uebergebenen Objekt. Die
       Rueckrufe muessen ASYNCHRON feuern – synchron waeren sie gesetzt, bevor
       der Aufrufer `onsuccess` zuweisen kann, und nichts liefe. */
    function ndbStub(daten) {
        return {
            open: function () {
                const a = { result: null, error: null };
                setTimeout(function () {
                    a.result = {
                        objectStoreNames: { contains: () => true },
                        createObjectStore: () => ({}),
                        transaction: function () {
                            const t = {};
                            t.objectStore = function () {
                                return {
                                    get: function (k) {
                                        const r = {};
                                        setTimeout(function () {
                                            r.result = daten[k];
                                            if (r.onsuccess) r.onsuccess();
                                        }, 0);
                                        return r;
                                    },
                                    put: function (v, k) {
                                        daten[k] = v;
                                        setTimeout(function () { if (t.oncomplete) t.oncomplete(); }, 0);
                                        return {};
                                    }
                                };
                            };
                            return t;
                        }
                    };
                    if (a.onsuccess) a.onsuccess();
                }, 0);
                return a;
            }
        };
    }

    /* Ein Verzeichnis-Handle. `recht` = was queryPermission meldet
       ('granted' | 'prompt' | 'denied'), `gibt` = was requestPermission danach
       liefert. */
    function ordnerStub(name, recht, gibt, spur) {
        return {
            name: name,
            queryPermission: function () { return Promise.resolve(recht); },
            requestPermission: function () {
                if (spur) spur.gefragt++;
                return Promise.resolve(gibt || recht);
            },
            getFileHandle: function (n, o) {
                if (spur) { spur.dateiName = n; spur.create = !!(o && o.create); }
                return Promise.resolve({
                    name: n,
                    createWritable: () => Promise.resolve({
                        write: (b) => { if (spur) spur.geschrieben.push(b); return Promise.resolve(); },
                        close: () => { if (spur) spur.geschlossen++; return Promise.resolve(); }
                    })
                });
            }
        };
    }

    function pickerOk(w, spur) {
        return Promise.resolve({
            name: 'nexus-dp-excel-addin.xml',
            createWritable: () => Promise.resolve({
                write: (b) => { spur.geschrieben.push(b); return Promise.resolve(); },
                close: () => { spur.geschlossen++; return Promise.resolve(); }
            })
        });
    }
    function pickerAbbruch() {
        const e = new Error('The user aborted a request.');
        e.name = 'AbortError';
        return Promise.reject(e);
    }

    // ── a) Kein Pfad hinterlegt: alles wie bisher ──────────────────────
    {
        const { w, spur } = adminFenster('', pickerOk, true);
        w.ExcelAdmin.onShow();
        await warte(20);
        const dl = w.document.getElementById('xa-download');
        // DER DOWNLOAD-KNOPF HAT NUR EINEN ZUSTAND (Umbau 2026-08-24). Vorher
        // wechselte er die Beschriftung je nach Katalogpfad – was er gerade tut,
        // war ihm nicht anzusehen.
        pruefe(dl.textContent === 'Manifest downloaden',
               'der Knopf heisst immer "Manifest downloaden"', dl.textContent);
        pruefe(w.document.getElementById('xa-dl-hint').style.display === 'none',
               'ohne Pfad steht kein Zusatzhinweis da');
        pruefe(w.document.getElementById('xa-upload').style.display === 'none',
               'ohne Pfad ist der Ordner-Knopf unsichtbar');
        const ev = new w.MouseEvent('click', { bubbles: true, cancelable: true });
        dl.dispatchEvent(ev);
        await warte(20);
        // DAS IST DIE ZUSAGE "der Download darf auch auf den Desktop": der Klick
        // wird NICHT abgefangen, also entscheidet der Browser ueber das Ziel.
        pruefe(ev.defaultPrevented === false,
               'der Klick wird nicht abgefangen – das Ziel bestimmt der Browser');
        pruefe(spur.navigation === 1,
               'der Browser folgt dem Link wirklich (jsdom meldet den Navigationsversuch)',
               'navigationen=' + spur.navigation);
        pruefe(spur.picker === 0, 'und es oeffnet sich kein Dialog');
        w.close();
    }

    // ── b) Pfad hinterlegt, Browser kann speichern ─────────────────────
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe\\addins', pickerOk, true);
        w.ExcelAdmin.onShow();
        await warte(20);
        pruefe(w.document.getElementById('xa-download').textContent === 'Manifest downloaden',
               'auch mit Pfad heisst der Download-Knopf unveraendert so');
        const dl = w.document.getElementById('xa-upload');
        pruefe(dl.style.display !== 'none' && /Ordner/.test(dl.textContent),
               'mit Pfad erscheint der Ordner-Knopf', dl.textContent);
        // Der Hinweis MUSS den Weg nennen: herunterladen, dann selbst
        // verschieben. Ohne diesen Satz haelt der Administrator den
        // eingetragenen Pfad fuer ein Ziel des Browsers – das war die Meldung.
        const hint = w.document.getElementById('xa-dl-hint');
        pruefe(hint.style.display !== 'none' && /verschieben/i.test(hint.textContent),
               'der Hinweis sagt, dass die Datei selbst verschoben werden muss',
               hint.textContent.slice(0, 90));
        pruefe(hint.textContent.indexOf('\\\\srv\\freigabe\\addins') >= 0,
               'und nennt den eingetragenen Pfad woertlich', hint.textContent);
        pruefe(!!hint.querySelector('.xa-pfad') &&
               hint.querySelector('.xa-pfad').textContent === '\\\\srv\\freigabe\\addins',
               'der Pfad steht per textContent in einem eigenen Element (Fremdeingabe)');

        const ev = new w.MouseEvent('click', { bubbles: true, cancelable: true });
        dl.dispatchEvent(ev);
        await warte(40);
        pruefe(spur.navigation === 0,
               'der Ordner-Knopf loest KEINEN Download aus, sondern den Dialog');
        pruefe(spur.picker === 1, 'genau ein Speichern-Dialog', 'picker=' + spur.picker);
        pruefe(spur.pickerArg && spur.pickerArg.suggestedName === 'nexus-dp-excel-addin.xml',
               'der Dateiname kommt aus dem Content-Disposition-Kopf (Branding)',
               spur.pickerArg && spur.pickerArg.suggestedName);
        pruefe(spur.geschrieben.length === 1 && spur.geschlossen === 1,
               'genau einmal geschrieben und der Datenstrom geschlossen');
        const st = w.document.getElementById('xa-dl-status');
        pruefe(/geschrieben/.test(st.textContent) && !/Fehler/.test(st.textContent),
               'Erfolg wird gemeldet', st.textContent);
        w.close();
    }

    // ── c) Pfad hinterlegt, Browser kann es nicht (Firefox/Safari) ─────
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe\\addins', null, true);
        w.ExcelAdmin.onShow();
        await warte(20);
        // Ein Knopf, der in Firefox nichts tun kann, wird nicht angeboten.
        pruefe(w.document.getElementById('xa-upload').style.display === 'none',
               'ohne File-System-API gibt es den Ordner-Knopf nicht');
        const dl = w.document.getElementById('xa-download');
        pruefe(dl.textContent === 'Manifest downloaden',
               'der Download-Knopf ist unveraendert da', dl.textContent);
        const ev = new w.MouseEvent('click', { bubbles: true, cancelable: true });
        dl.dispatchEvent(ev);
        await warte(20);
        pruefe(ev.defaultPrevented === false, 'der Link bleibt ein Link');
        w.close();
    }

    // ── d) Abbrechen im Dialog ist kein Fehler ─────────────────────────
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe', pickerAbbruch, true);
        w.ExcelAdmin.onShow();
        await warte(20);
        w.document.getElementById('xa-upload')
            .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(40);
        const st = w.document.getElementById('xa-dl-status');
        pruefe(st.textContent === '',
               'Abbrechen im Dialog erzeugt KEINE Fehlermeldung', st.textContent);
        w.close();
    }

    // ── e) Server lehnt die Adresse ab (localhost): nichts geht raus ───
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe', pickerOk, false);
        w.ExcelAdmin.onShow();
        await warte(20);
        w.document.getElementById('xa-upload')
            .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(40);
        pruefe(spur.picker === 0,
               'bei abgelehnter Basis-Adresse wird kein Dialog geoeffnet – sonst laege ' +
               'ein Manifest im Katalog, das auf jedem Arbeitsplatz ins Leere zeigt',
               'picker=' + spur.picker);
        w.close();
    }

    // ── e1) Die Absage beim Oeffnen wirkt fort ─────────────────────────
    //  Auch wenn ein spaeterer Abruf gelaenge: der Server hat diese Basis
    //  einmal abgelehnt, das Manifest waere auf den Arbeitsplaetzen wertlos.
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe', pickerOk, 'nur_erster');
        w.ExcelAdmin.onShow();
        await warte(20);
        w.document.getElementById('xa-upload')
            .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(40);
        pruefe(spur.picker === 0,
               'die Absage beim Oeffnen sperrt den Knopf dauerhaft, nicht nur den ' +
               'einen Abruf', 'picker=' + spur.picker);
        w.close();
    }

    // ── e2) Erst holen, DANN den Dialog – nie eine 0-Byte-Datei ────────
    //  Beim Oeffnen des Reiters war die Adresse in Ordnung, der Abruf beim
    //  Klick scheitert (Deploy dazwischen, Netzstoerung). `_adresseKaputt`
    //  greift hier NICHT – geprueft wird allein die Reihenfolge.
    {
        const { w, spur } = adminFenster('\\\\srv\\freigabe', pickerOk, 'spaeter');
        w.ExcelAdmin.onShow();
        await warte(20);
        w.document.getElementById('xa-upload')
            .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(40);
        pruefe(spur.manifestAbrufe > 1, 'Vorbedingung: der Klick hat wirklich abgerufen',
               'abrufe=' + spur.manifestAbrufe);
        pruefe(spur.picker === 0,
               'scheitert der Abruf, wird gar kein Dialog geoeffnet (der Picker legt die ' +
               'Zieldatei schon beim Auswaehlen an – es laege eine 0-Byte-Datei im Katalog)',
               'picker=' + spur.picker);
        pruefe(/Fehler/.test(w.document.getElementById('xa-dl-status').textContent),
               'und der Grund steht im Klartext da');
        w.close();
    }

    // ── f) Speichern des Pfades schaltet den Knopf sofort um ───────────
    {
        const { w, spur } = adminFenster('', pickerOk, true);
        w.ExcelAdmin.onShow();
        await warte(20);
        const dl = w.document.getElementById('xa-upload');
        pruefe(dl.style.display === 'none', 'Ausgangszustand: kein Ordner-Knopf');
        pruefe(w.document.getElementById('xa-dl-hint').style.display === 'none',
               'und kein Hinweis');
        w.document.getElementById('xa-katalog').value = '\\\\srv\\neu';
        w.document.getElementById('xa-katalog-save').click();
        await warte(40);
        pruefe(dl.style.display !== 'none',
               'nach dem Speichern des Pfades erscheint der Ordner-Knopf sofort ' +
               '(ohne Neuladen des Reiters)');
        pruefe(w.document.getElementById('xa-dl-hint').textContent.indexOf('srv\\neu') > 0,
               'und der Hinweis nennt den neuen Pfad');
        // Der Knopf sendet nur SEINE Teilmenge – `update_skill_config` merged,
        // ein voller Formularstand ueberschriebe die Grenzwerte.
        const letzte = spur.koerper[spur.koerper.length - 1];
        pruefe(letzte && Object.keys(letzte).length === 1 && 'katalog_pfad' in letzte,
               'gesendet wird ausschliesslich katalog_pfad', JSON.stringify(letzte));
        w.close();
    }

    // ── g) Waechter im Quelltext ───────────────────────────────────────
    pruefe(/showSaveFilePicker/.test(ADMIN_CODE) &&
           ADMIN_CODE.indexOf('typeof window.showSaveFilePicker') > 0,
           'die API wird geprueft, nicht vorausgesetzt');
    // Der Reiter ist durchgehend deutsch (wie der Jira-Reiter) – ein einzelner
    // i18n-Schluessel hier waere eine halbe Uebersetzung.
    const XPANEL = SETH.slice(ia, ja);
    pruefe(XPANEL.indexOf('id="xa-dl-hint"') > 0,
           'das Hinweisfeld steht im echten Markup');
    // Auf Vorgabe des Nutzers entfallen (2026-08-24): die curl-Zeile samt
    // Erklaerung. Beides darf nicht zurueckkommen – weder im Markup noch als
    // toter Code, der die Zeile weiter baut.
    pruefe(XPANEL.indexOf('xa-cmd') < 0 && XPANEL.indexOf('Eingabeaufforderung') < 0,
           'die Befehlszeile ist aus dem Markup entfernt');
    pruefe(ADMIN_CODE.indexOf('xa-cmd') < 0 && ADMIN_CODE.indexOf('curl.exe') < 0,
           '... und es gibt keinen toten Code mehr dazu');
    pruefe(!/Sicherheitsgrenze des Browsers/.test(ADMIN_CODE),
           'der Erklaertext zum Ordner-Dialog ist entfernt');

    /* ZWEI KNOEPFE, ZWEI AUFGABEN (Umbau 2026-08-24, mehrfach gemeldet).
       #xa-download ist ein reines <a href> – wird es abgefangen, bestimmt die
       Seite das Ziel und die Datei kann NICHT mehr auf den Desktop. Genau das
       war die Meldung. */
    pruefe(XPANEL.indexOf('id="xa-upload"') > 0,
           'der Ordner-Weg hat einen EIGENEN Knopf');
    pruefe(XPANEL.indexOf('>Manifest downloaden<') > 0,
           'der Download-Knopf heisst "Manifest downloaden"');
    pruefe(!/xa-download[^>]*>\s*Manifest (herunterladen|hochladen)/.test(XPANEL),
           '... und traegt keine der alten Beschriftungen mehr');
    // Die Beschriftung darf nicht mehr umgeschaltet werden - ein Knopf, dessen
    // Aufgabe an einem Feld weiter unten haengt, ist ihm nicht anzusehen.
    pruefe(ADMIN_CODE.indexOf("$('xa-download').textContent") < 0 &&
           !/dl\.textContent\s*=/.test(ADMIN_CODE),
           'die Beschriftung des Download-Knopfes wird nirgends umgeschrieben');
    pruefe(!/\$\('xa-download'\)[\s\S]{0,120}addEventListener/.test(ADMIN_CODE),
           'am Download-Knopf haengt KEIN Klick-Handler (das Ziel bestimmt der Browser)');
    // Der Hinweis muss den manuellen Schritt benennen.
    pruefe(/verschieben/i.test(ADMIN_CODE) && /nicht.{0,40}selbst.{0,40}Netzwerkfreigabe|Netzwerkfreigabe/i.test(ADMIN_CODE),
           'der Hinweis nennt das Verschieben von Hand');

    /* Die Liste "Was der Assistent darf" ist eine ZUSAGE an den Administrator.
       Zwei ihrer Zeilen waren nach dem Umbau vom 2026-08-24 unwahr - genau die
       Fehlerklasse, die in diesem Projekt dreimal teuer war (WA_TASK_PROMPT
       versprach cron_create, der EWS-Hinweis das Gegenteil der Weiche). */
    pruefe(XPANEL.indexOf('nie ohne Bestätigung') < 0,
           'die Liste behauptet nicht mehr "nie ohne Bestätigung" (Automatik ist Vorgabe)');
    pruefe(XPANEL.indexOf('Änderungen automatisch übernehmen') > 0,
           '... sondern nennt das Kaestchen beim Namen');
    pruefe(XPANEL.indexOf('Strg+Z holt die Änderung nicht zurück') < 0,
           'die Liste behauptet nicht mehr, Strg+Z wirke nicht');
    pruefe(XPANEL.indexOf('eigenen Rückweg') < 0,
           '... und verspricht keinen eigenen Rueckweg mehr (den Knopf gibt es nicht)');
    pruefe(/Strg\+Z/.test(XPANEL) && /Excel im Web/.test(XPANEL),
           'sie nennt Strg+Z als Rueckweg UND die Einschraenkung fuer Excel im Web');
    // Die Beschriftung im Fenster und der Text hier muessen dasselbe Kaestchen
    // benennen - sonst sucht der Benutzer eine Einstellung, die anders heisst.
    pruefe(HTML.indexOf('Änderungen automatisch übernehmen') > 0,
           'und trifft die Beschriftung im Aufgabenfenster woertlich');
    // GEMELDET 2026-08-23: "was soll dieser Bullshit mit 'Ordner einmal
    // auswaehlen' und 'Pfad kopieren'". Beide Knoepfe sind weg und duerfen nicht
    // zurueckkommen – der Hochlade-Knopf erledigt beides selbst.
    pruefe(XPANEL.indexOf('xa-ordner-btn') < 0 && XPANEL.indexOf('xa-pfad-copy') < 0,
           'die beiden Vorstufen-Knoepfe sind aus dem Markup entfernt');
    pruefe(ADMIN_CODE.indexOf('xa-ordner-btn') < 0 && ADMIN_CODE.indexOf('xa-pfad-copy') < 0,
           '... und es gibt keinen toten Code mehr dazu');
    pruefe(!/JarvisIcons\.trash/.test(ADMIN_CODE),
           'kein Muelleimer im Verteil-Bereich (es wird nichts geloescht)');

    // ══ 8. Der gemerkte Katalog-Ordner ════════════════════════════════════
    abschnitt('8. "Manifest hochladen" schreibt in den gemerkten Ordner');
    /* GEMELDET: "'Manifest hochladen' nutzt nicht den gespeicherten Pfad zum
       hochladen." Ein PFAD als Text laesst sich im Speichern-Dialog nicht
       vorbelegen – der VORGANG geht aber: showDirectoryPicker liefert ein
       Handle, und Handles sind in IndexedDB persistierbar. */
    const PFAD = '\\\\srv\\freigabe\\addins';

    // ── i) EIN Klick: fragt einmal nach dem Ordner und schreibt hinein ─
    {
        const laden = {};
        /* Der Ordner-Stub schreibt in SEINE eigene Spur, nicht in die des
           Fensters – ohne diese Verknuepfung prueft man die falsche Variable und
           bekommt "schreibvorgaenge=0", obwohl der Code richtig arbeitet. */
        const hSpur = { geschrieben: [], geschlossen: 0, gefragt: 0 };
        const h = ordnerStub('office-addins', 'granted', 'granted', hSpur);
        const { w, spur } = adminFenster(PFAD, pickerOk, true, h, laden);
        w.ExcelAdmin.onShow();
        await warte(40);
        // Kein Vorstufen-Knopf mehr – das war die Meldung.
        pruefe(w.document.getElementById('xa-ordner-btn') === null,
               'es gibt keinen Knopf "Ordner einmal auswaehlen" mehr');
        const dl = w.document.getElementById('xa-upload');
        // Noch KEIN Ordner gemerkt (das Handle kommt erst aus dem Dialog) –
        // der Knopf laedt also zum Waehlen ein.
        pruefe(dl.style.display !== 'none' && /wählen/.test(dl.textContent),
               'ohne gemerkten Ordner laedt der Knopf zum Waehlen ein', dl.textContent);

        dl.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(80);
        pruefe(spur.dirPicker === 1,
               'derselbe Klick fragt EINMAL nach dem Ordner', 'aufrufe=' + spur.dirPicker);
        pruefe(spur.picker === 0,
               'und oeffnet KEINEN Speichern-Dialog daneben', 'dialoge=' + spur.picker);
        pruefe(hSpur.geschrieben.length === 1 && hSpur.geschlossen === 1,
               'die Datei landet im gewaehlten Ordner',
               'schreibvorgaenge=' + hSpur.geschrieben.length);
        pruefe(hSpur.dateiName === 'nexus-dp-excel-addin.xml',
               'Dateiname aus dem Antwortkopf (folgt dem Branding)', hSpur.dateiName);
        pruefe(hSpur.create === true,
               'die Datei wird angelegt, wenn sie noch nicht existiert');
        pruefe(!!laden['excel-katalog'], 'das Handle wird in IndexedDB gemerkt');
        w.close();

        // ── j) NEUES Fenster: kein zweiter Ordner-Dialog ───────────────
        const zwei = adminFenster(PFAD, pickerOk, true, h, laden);
        zwei.w.ExcelAdmin.onShow();
        await warte(60);
        const knopf2 = zwei.w.document.getElementById('xa-upload');
        pruefe(knopf2.textContent.indexOf('office-addins') >= 0,
               'nach dem Neuladen nennt der Knopf den gemerkten Ordner (Persistenz)',
               knopf2.textContent);
        zwei.w.document.getElementById('xa-upload')
            .dispatchEvent(new zwei.w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(60);
        pruefe(zwei.spur.dirPicker === 0,
               'beim zweiten Mal wird NICHT mehr nach dem Ordner gefragt',
               'aufrufe=' + zwei.spur.dirPicker);
        pruefe(zwei.spur.picker === 0, 'und weiterhin kein Speichern-Dialog');
        pruefe(hSpur.geschrieben.length === 2, 'geschrieben wurde trotzdem',
               'schreibvorgaenge=' + hSpur.geschrieben.length);
        zwei.w.close();
    }

    // ── i2) DER GEMELDETE FEHLER: getippter, NICHT gespeicherter Pfad ──
    /* "ich habe den pfad bereits im 'Netzwerk Pfad' Feld eingetragen" – der
       Knopf hing am GESPEICHERTEN Wert und bot deshalb weiter einen Download
       an. Jetzt entscheidet der Feldinhalt, und der Klick speichert ihn mit. */
    {
        const laden = {};
        const hSpur = { geschrieben: [], geschlossen: 0, gefragt: 0 };
        const h = ordnerStub('office-addins', 'granted', 'granted', hSpur);
        const { w, spur } = adminFenster('', pickerOk, true, h, laden);
        w.ExcelAdmin.onShow();
        await warte(40);
        const dl = w.document.getElementById('xa-upload');
        pruefe(dl.style.display === 'none', 'ohne Pfad kein Ordner-Knopf');

        const feld = w.document.getElementById('xa-katalog');
        feld.value = '\\\\srv\\freigabe\\neu';
        feld.dispatchEvent(new w.Event('input', { bubbles: true }));
        await warte(20);
        // MASSGEBLICH IST DER FELDINHALT, nicht der gespeicherte Wert: wer
        // eintippt, sieht sofort, wohin die Datei gehoert.
        pruefe(dl.style.display !== 'none',
               'beim Tippen erscheint der Ordner-Knopf sofort');
        pruefe(w.document.getElementById('xa-dl-hint').textContent.indexOf('freigabe\\neu') > 0,
               'und der Hinweis wandert mit');

        const vorher = spur.koerper.length;
        dl.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(80);
        pruefe(hSpur.geschrieben.length === 1,
               'der Klick laedt hoch, ohne dass vorher gespeichert wurde');
        const gesendet = spur.koerper.slice(vorher)
                             .filter(function (b) { return 'katalog_pfad' in b; });
        pruefe(gesendet.length === 1 && gesendet[0].katalog_pfad === '\\\\srv\\freigabe\\neu',
               'und speichert den eingetragenen Pfad gleich mit',
               JSON.stringify(gesendet));
        // Nur die eigene Teilmenge – sonst ueberschriebe der Knopf die Grenzen.
        pruefe(gesendet.length === 1 && !('max_runden' in gesendet[0]),
               'dabei werden die Grenzwerte NICHT mitgeschickt');
        w.close();
    }

    // ── k) Berechtigung auf "prompt": einmal fragen, dann schreiben ────
    {
        const laden = {};
        const spurRef = { geschrieben: [], geschlossen: 0, gefragt: 0 };
        const h = ordnerStub('office-addins', 'prompt', 'granted', spurRef);
        laden['excel-katalog'] = h;
        const { w, spur } = adminFenster(PFAD, pickerOk, true, h, laden);
        w.ExcelAdmin.onShow();
        await warte(60);
        w.document.getElementById('xa-upload')
         .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(60);
        // Nach einem Browser-Neustart ist "prompt" der NORMALFALL und kein
        // Fehler – es darf genau einmal gefragt und dann geschrieben werden.
        pruefe(spurRef.gefragt === 1, 'bei "prompt" wird genau einmal nachgefragt',
               'fragen=' + spurRef.gefragt);
        pruefe(spurRef.geschrieben.length === 1,
               'nach erteilter Erlaubnis wird geschrieben');
        pruefe(spur.picker === 0, 'und weiterhin ohne Speichern-Dialog');
        w.close();
    }

    // ── l) Berechtigung verweigert: Rueckfall auf den Dialog ───────────
    {
        const laden = {};
        const spurRef = { geschrieben: [], geschlossen: 0, gefragt: 0 };
        const h = ordnerStub('office-addins', 'prompt', 'denied', spurRef);
        laden['excel-katalog'] = h;
        const { w, spur } = adminFenster(PFAD, pickerOk, true, h, laden);
        w.ExcelAdmin.onShow();
        await warte(60);
        w.document.getElementById('xa-upload')
         .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(60);
        // FAIL-SAFE IN DIE RICHTIGE RICHTUNG: verweigerte Erlaubnis darf nicht
        // in "geht nicht" enden, sondern in den Weg, der vorher schon ging.
        pruefe(spurRef.geschrieben.length === 0,
               'ohne Erlaubnis wird NICHT in den Ordner geschrieben');
        pruefe(spur.picker === 1, 'stattdessen oeffnet der Speichern-Dialog (Rueckfall)',
               'dialoge=' + spur.picker);
        pruefe(spur.pickerArg && spur.pickerArg.id === 'jarvis-excel-katalog',
               'der Dialog traegt eine id – Chrome merkt sich das Verzeichnis');
        pruefe(spur.pickerArg && spur.pickerArg.startIn === h,
               'und startet im gemerkten Ordner');
        w.close();
    }

    // ── m) Kein Ordner-Picker im Browser: Rueckfall auf den Dialog ─────
    {
        const { w, spur } = adminFenster(PFAD, pickerOk, true, null, {});
        w.ExcelAdmin.onShow();
        await warte(60);
        w.document.getElementById('xa-upload')
         .dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
        await warte(60);
        // FAIL-SAFE IN DIE RICHTIGE RICHTUNG: fehlt die Ordner-API, endet es
        // nicht in "geht nicht", sondern im Weg, der vorher schon ging.
        pruefe(spur.picker === 1, 'ohne showDirectoryPicker oeffnet der Speichern-Dialog',
               'dialoge=' + spur.picker);
        pruefe(spur.geschrieben.length === 1, 'und geschrieben wird trotzdem');
        w.close();
    }

    // ── n) Ordnername ist Fremdeingabe des Dateisystems ────────────────
    {
        const laden = {};
        const h = ordnerStub('a<img src=x onerror=alert(1)>', 'granted', 'granted', null);
        laden['excel-katalog'] = h;
        const { w } = adminFenster(PFAD, pickerOk, true, h, laden);
        w.ExcelAdmin.onShow();
        await warte(60);
        // Der Ordnername steht seit dem Umbau in der KNOPF-Beschriftung, nicht
        // mehr im Hinweis – dort wird er per textContent gesetzt, kann also
        // gar kein Markup werden. Beides wird geprueft: kein Element UND der
        // Name als Text sichtbar.
        const knopf = w.document.getElementById('xa-upload');
        pruefe(knopf.querySelector('img') === null,
               'ein Ordnername mit Markup wird nicht zu Markup');
        pruefe(knopf.textContent.indexOf('<img') >= 0,
               'und erscheint als Text', knopf.textContent);
        // Und der eingetragene Pfad im Hinweis ebenso – er ist Fremdeingabe.
        const hint = w.document.getElementById('xa-dl-hint');
        pruefe(hint.querySelector('img') === null,
               'auch der Hinweis traegt kein Markup aus Fremdeingabe');
        w.close();
    }

    /* ══════════════════════════════════════════════════════════════════
       Automatische Uebernahme (Vorgabe AN)
       ──────────────────────────────────────────────────────────────────
       Der Handbetrieb steht in Abschnitt 3. Hier der Auto-Fall: nach der
       Antwort wird OHNE Rueckfrage geschrieben – und der Diff bleibt
       sichtbar stehen, sonst aendern sich Zellen und niemand sieht, welche.
       ══════════════════════════════════════════════════════════════════ */
    abschnitt('Automatische Uebernahme');
    {
        const { win, zustand } = angemeldetesFenster();
        await warte(60);
        const d = win.document;
        pruefe(d.getElementById('xl-auto').checked === true,
               'ohne gespeicherte Wahl ist die Automatik AN');

        d.getElementById('xl-frage').value = 'Berechne die Marge';
        d.getElementById('xl-send').click();
        await warte(160);

        pruefe(zustand.geschrieben.length > 0,
               'geschrieben wird ohne jede Rueckfrage');
        const dlg = d.getElementById('xl-ask');
        pruefe(!dlg || dlg.classList.contains('hidden'),
               'der Bestaetigungsdialog bleibt zu');
        pruefe(!d.getElementById('xl-apply'),
               'und es steht kein Uebernehmen-Knopf mehr da');

        // Der Diff MUSS bleiben – er ist die einzige Stelle, an der steht,
        // was gerade in die Mappe gelaufen ist.
        const fertig = d.querySelector('.xl-diff-done');
        pruefe(!!fertig, 'der uebernommene Diff bleibt sichtbar');
        pruefe(!!fertig && /[Aa]utomatisch/.test(fertig.textContent),
               'und ist als automatisch uebernommen gekennzeichnet',
               fertig && fertig.textContent);
        const diff = d.querySelector('.xl-diff');
        pruefe(!!diff && /G2/.test(diff.textContent),
               'mit Zelladresse');
        pruefe(!!diff && /=E2\*F2/.test(diff.textContent),
               'und der geschriebenen Formel');

        // Die naechste Frage raeumt ihn ab – sonst stuende ein alter Diff
        // UNTER der neuen Frage und saehe wie deren Ergebnis aus.
        d.getElementById('xl-frage').value = 'noch etwas';
        d.getElementById('xl-send').click();
        // OHNE Wartezeit geprueft: `fragen()` raeumt auf und zeichnet noch
        // synchron. Wer hier wartet, sieht schon den Diff der NEUEN Antwort
        // (die Automatik ist schnell) und misst damit das Falsche.
        pruefe(!d.querySelector('.xl-diff-done'),
               'eine neue Frage raeumt den erledigten Diff sofort ab');
        // Den angestossenen Lauf AUSLAUFEN lassen, bevor das Fenster zugeht:
        // `close()` nimmt das `document` weg, und der noch laufende Lauf
        // zeichnet danach in ein Nichts (Absturz des Testlaufs, nicht ein
        // Fehlschlag – also nicht als Fehler erkennbar).
        await warte(200);
        win.close();
    }
    {
        // Abwaehlen wird gemerkt: ein '0' im Speicher heisst AUS, ein
        // FEHLENDER Wert heisst AN (nicht entschieden).
        const { win, zustand } = angemeldetesFenster();
        await warte(60);
        const d = win.document;
        const box = d.getElementById('xl-auto');
        box.checked = false;
        box.dispatchEvent(new win.Event('change', { bubbles: true }));
        pruefe(win.localStorage.getItem('jarvis_xl_autoapply') === '0',
               'das Abwaehlen wird gespeichert');

        d.getElementById('xl-frage').value = 'Berechne die Marge';
        d.getElementById('xl-send').click();
        await warte(160);
        pruefe(zustand.geschrieben.length === 0,
               'abgewaehlt wird NICHTS ohne Zutun geschrieben');
        pruefe(!!d.getElementById('xl-apply'),
               'stattdessen steht der Uebernehmen-Knopf da');
        win.close();
    }
    {
        // Ein gespeichertes AUS muss das `checked` im Markup ueberstimmen –
        // sonst bekaeme der Benutzer nach dem Neuladen wieder die Automatik.
        const { win } = angemeldetesFenster({ auto: '0' });
        await warte(60);
        pruefe(win.document.getElementById('xl-auto').checked === false,
               'ein gespeichertes AUS ueberstimmt das checked im Markup');
        win.close();
    }

    /* ══════════════════════════════════════════════════════════════════
       Tastatur im Eingabefeld
       ──────────────────────────────────────────────────────────────────
       ENTER sendet (Vorgabe des Nutzers, vorher nur Strg+Enter).
       Umschalt+Enter muss den Zeilenumbruch BEHALTEN – sonst gibt es aus
       einem dreizeiligen Feld keinen Weg zu einer mehrzeiligen Frage.
       Geprueft wird ueber die ECHTE Bindung: `preventDefault` ist das
       einzige beobachtbare Zeichen dafuer, dass gesendet statt umgebrochen
       wird (jsdom fuehrt die Vorgabeaktion eines Textfelds nicht aus). */
    abschnitt('Enter sendet');
    {
        const { win } = fensterMitStub(true);
        await warte(60);
        const doc = win.document;
        const feld = doc.getElementById('xl-frage');

        function taste(opt) {
            const ev = new win.KeyboardEvent('keydown',
                Object.assign({ key: 'Enter', bubbles: true, cancelable: true }, opt));
            feld.dispatchEvent(ev);
            return ev.defaultPrevented;
        }

        pruefe(taste({}) === true,
               'Enter sendet (Vorgabeaktion unterbunden)');
        pruefe(taste({ shiftKey: true }) === false,
               'Umschalt+Enter macht weiter einen Zeilenumbruch');
        pruefe(taste({ ctrlKey: true }) === true,
               'Strg+Enter sendet weiter mit (der bisherige Weg)');
        pruefe(taste({ metaKey: true }) === true,
               'Cmd+Enter ebenso');

        const ev = new win.KeyboardEvent('keydown',
            { key: 'a', bubbles: true, cancelable: true });
        feld.dispatchEvent(ev);
        pruefe(ev.defaultPrevented === false,
               'eine gewoehnliche Taste wird nicht abgefangen');

        // Die Beschriftung heisst "Senden", nicht "Fragen" – der Knopf sendet
        // auch Arbeitsauftraege ("trage in G2:G40 die Marge ein"), nicht nur
        // Fragen. Geprueft in BEIDEN Sprachen, weil der Text aus i18n kommt.
        pruefe(doc.getElementById('xl-send').getAttribute('data-i18n') === 'xl.send',
               'der Sende-Knopf haengt an xl.send');
        win.close();
    }
    {
        const T = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        pruefe(/'xl\.send':\s*'Senden'/.test(T), 'DE: Senden');
        pruefe(/'xl\.send':\s*'Send'/.test(T), 'EN: Send');
        pruefe(!/'xl\.send':\s*'(Fragen|Ask)'/.test(T),
               'die alte Beschriftung kommt nicht zurueck');
    }

    /* ══════════════════════════════════════════════════════════════════
       Hell/Dunkel-Umschalter
       ──────────────────────────────────────────────────────────────────
       Der Knopf rief `window.toggleTheme()` – eine Funktion, die es NIE
       gab (`theme.js` exportiert `applyTheme`). Der Klick tat damit
       nichts: keine Reaktion, kein Fehler. Derselbe Fehler war im
       Outlook-Add-in schon behoben, hier nicht.

       Geprueft wird der ECHTE Klick mit dem ECHTEN theme.js – eine
       Quelltextpruefung auf "applyTheme" waere gruen, sobald das Wort
       irgendwo steht. */
    abschnitt('Hell/Dunkel');
    {
        const THEME = fs.readFileSync(path.join(ROOT, 'frontend/js/theme.js'), 'utf8');

        pruefe(nurCode(THEME).indexOf('window.toggleTheme') < 0,
               'theme.js exportiert KEIN toggleTheme (deshalb darf niemand darauf pruefen)');
        pruefe(JS_CODE.indexOf('toggleTheme') < 0,
               'excel.js ruft toggleTheme nicht mehr auf');

        const { dom, win } = fensterMitStub(true, THEME);
        // `start()` laeuft ueber `officeErmitteln().then(...)`, die Bindung
        // steht also erst nach einem Durchlauf der Ereigniswarteschlange –
        // ein Klick direkt nach `eval` trifft ins Leere.
        await warte(60);
        const doc = win.document;
        const knopf = doc.getElementById('xl-theme');
        pruefe(!!knopf, 'der Umschalter ist vorhanden');

        // Start ist Dunkel (kein gespeicherter Wert).
        pruefe(!doc.body.classList.contains('light'), 'Start: Dunkel');

        knopf.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
        pruefe(doc.body.classList.contains('light'),
               'ein Klick schaltet auf Hell');
        pruefe(win.localStorage.getItem('jarvis_theme') === 'light',
               'und merkt sich das (jarvis_theme)');

        knopf.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
        pruefe(!doc.body.classList.contains('light'),
               'ein zweiter Klick schaltet zurueck auf Dunkel');
        pruefe(win.localStorage.getItem('jarvis_theme') === 'dark',
               'und merkt sich auch das');

        // branding.js zieht die Hell-Farben der Marke ueber dieses Ereignis
        // nach – ohne `applyTheme` (nur Klasse umschalten) feuert es nicht.
        var gesehen = 0;
        doc.addEventListener('jarvis:themechange', function () { gesehen++; });
        knopf.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
        pruefe(gesehen === 1, 'der Wechsel feuert jarvis:themechange (fuer branding.js)');

        win.close();
    }

    console.log('\n' + '='.repeat(50));
    console.log('Bestanden: ' + ok + ' / Fehlgeschlagen: ' + fail);
    dom0.window.close();
    process.exit(fail ? 1 : 0);
})().catch(e => {
    console.error('\nABBRUCH:', e && e.stack || e);
    process.exit(1);
});
