#!/usr/bin/env node
/* Waechter: Excel-OBJEKTE im Aufgabenfenster (Pivot, Diagramm, Tabelle, bedingt).
 *
 * Die ECHTEN Funktionen aus `frontend/excel-addin/excel.js` werden geschnitten
 * und WIRKLICH AUSGEFUEHRT – gegen eine Office.js-Attrappe, die die Aufrufe
 * aufzeichnet. Eine Quelltext-Pruefung koennte die Frage „entsteht am Ende eine
 * Pivot-Tabelle, und mit welchen Feldern?" gar nicht beantworten.
 *
 * ⚠ DIE ATTRAPPE IST VERSIONSGENAU. `test_excel_addin_ui.js` hat ein pauschales
 * `isSetSupported: () => !!opt.api` – damit waere der 1.8-Zweig (Pivot ja/nein)
 * UNMESSBAR, weil die Attrappe die zu pruefende Lage gar nicht herstellen kann.
 * Hier antwortet sie je Version.
 *
 * ⚠ SIE VERLANGT `load()` VOR DEM LESEN. Ein echtes Office.js wirft dort
 * ("PropertyNotLoaded") – eine Attrappe, die den Wert auch ohne `load()`
 * herausgibt, laesst ein vergessenes `load()` durchgehen; das ist der
 * haeufigste Office.js-Fehler ueberhaupt (Register, 2026-09-08).
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');

let ok = 0, fail = 0, bilanz = false;

function pruefe(bed, text) {
    if (bed) ok++; else { fail++; console.log('  FAIL: ' + text); }
}

/* Zwei Netze gegen den stillen Abbruch: die ganze Datei ist eine async-IIFE –
 * wirft etwas darin, wird alles bis zum Ende uebersprungen, auch die Bilanz,
 * und Node beendet mit 0. Ein abgebrochener Lauf saehe wie ein bestandener aus. */
process.on('exit', () => {
    if (!bilanz) {
        console.log('\nErgebnis: ABGEBROCHEN – keine Bilanz erreicht');
        process.exitCode = 1;
    }
});
const wachhund = setTimeout(() => {
    console.log('\nErgebnis: ABGEBROCHEN – Zeitlimit (30 s)');
    process.exit(1);
}, 30000);
wachhund.unref();

/* ── Funktionen schneiden ────────────────────────────────────────────────
   GEKLAMMERT gezaehlt, nicht „bis zum ersten \n}": eine Einzeiler-Funktion
   (`function istObjekt(a) { return !!(a && a.typ); }`) endet in DERSELBEN
   Zeile – ein naiver Schnitt nimmt die naechste Funktion mit und prueft dann
   fremden Code (Register, 2026-09-02). */
function schneide(name) {
    const anker = 'function ' + name + '(';
    const i = JS.indexOf(anker);
    if (i < 0) return null;
    const auf = JS.indexOf('{', i);
    if (auf < 0) return null;
    let tiefe = 0, j = auf, inStr = null, inCom = null;
    for (; j < JS.length; j++) {
        const c = JS[j], n = JS[j + 1];
        if (inCom === '/*') { if (c === '*' && n === '/') { inCom = null; j++; } continue; }
        if (inCom === '//') { if (c === '\n') inCom = null; continue; }
        if (inStr) {
            if (c === '\\') { j++; continue; }
            if (c === inStr) inStr = null;
            continue;
        }
        if (c === '/' && n === '*') { inCom = '/*'; j++; continue; }
        if (c === '/' && n === '/') { inCom = '//'; j++; continue; }
        if (c === '"' || c === "'" || c === '`') { inStr = c; continue; }
        if (c === '{') tiefe++;
        else if (c === '}') { tiefe--; if (tiefe === 0) return JS.slice(i, j + 1); }
    }
    return null;
}

const TEILE = ['istObjekt', 'quellBereich', 'blattVon', 'objektSchreiben',
               'bedingtSetzen', 'objektLoeschen', 'objektText', 'eintragKurz'];
const code = {};
for (const t of TEILE) {
    code[t] = schneide(t);
    if (!code[t]) {
        console.log('ABBRUCH: Funktion ' + t + ' nicht schneidbar');
        bilanz = true;
        process.exit(2);
    }
}
// Positivkontrolle des Schnitts: sonst prueft der Waechter womoeglich eine
// leere Zeichenkette gegen sich selbst.
pruefe(code.objektSchreiben.includes('pivotTables.add'),
       'Schnitt objektSchreiben enthaelt den Pivot-Zweig');
pruefe(code.objektLoeschen.includes('convertToRange'),
       'Schnitt objektLoeschen enthaelt den Tabellen-Zweig');
pruefe(!code.istObjekt.includes('function quellBereich'),
       'Schnitt istObjekt nimmt die naechste Funktion NICHT mit');

/* ── Office.js-Attrappe ──────────────────────────────────────────────────── */
function stub(zustand, opt) {
    opt = opt || {};
    const geladen = new WeakSet();

    function range(adr, blattName) {
        const r = {
            _adr: adr,
            conditionalFormats: {
                _liste: [],
                add(typ) {
                    const cf = {
                        typ: typ,
                        cellValue: { format: { fill: {}, font: {} }, rule: null },
                        colorScale: { criteria: null },
                        dataBar: { positiveFormat: {} }
                    };
                    this._liste.push(cf);
                    zustand.bedingt.push({ adresse: adr, blatt: blattName, cf: cf });
                    return cf;
                },
                getItemAt(i) {
                    const self = this;
                    return { delete() { zustand.geloescht.push('bedingt@' + adr + '#' + i);
                                        self._liste.splice(i, 1); } };
                }
            },
            getCell() { return range(adr, blattName); },
            load() { geladen.add(r); }
        };
        return r;
    }

    function blatt(name) {
        const s = {
            name: name,
            isNullObject: opt.fehlendeBlaetter && opt.fehlendeBlaetter.includes(name),
            getRange: (adr) => range(adr, name),
            load() { geladen.add(s); },
            pivotTables: {
                add(n, quelle, ziel) {
                    if (!opt.api18) {
                        throw new Error('ApiNotFound: pivotTables ist hier nicht verfuegbar');
                    }
                    const p = {
                        _name: n,
                        hierarchies: { getItem: (f) => ({ _feld: f }) },
                        rowHierarchies: { add(h) { p._zeilen.push(h._feld); } },
                        columnHierarchies: { add(h) { p._spalten.push(h._feld); } },
                        dataHierarchies: {
                            add(h) {
                                const d = { _feld: h._feld, summarizeBy: null };
                                p._werte.push(d);
                                return d;
                            }
                        },
                        _zeilen: [], _spalten: [], _werte: [],
                        load() { geladen.add(p); },
                        get name() {
                            if (!geladen.has(p)) {
                                throw new Error('PropertyNotLoaded: name');
                            }
                            return p._name;
                        }
                    };
                    zustand.pivots.push({ name: n, quelle: quelle,
                                          ziel: ziel && ziel._adr, blatt: name, obj: p });
                    return p;
                },
                getItem(n) {
                    return { delete() { zustand.geloescht.push('pivot:' + n); } };
                }
            },
            charts: {
                add(art, quelle, seriesBy) {
                    const c = {
                        _name: 'Diagramm 1', title: { text: null },
                        setPosition(r) { c._pos = r && r._adr; },
                        load() { geladen.add(c); },
                        get name() {
                            if (!geladen.has(c)) throw new Error('PropertyNotLoaded: name');
                            return c._name;
                        },
                        set name(v) { c._name = v; }
                    };
                    zustand.charts.push({ art: art, quelle: quelle && quelle._adr,
                                          seriesBy: seriesBy, blatt: name, obj: c });
                    return c;
                },
                getItem(n) {
                    return { delete() { zustand.geloescht.push('chart:' + n); } };
                }
            },
            tables: {
                add(adr, kopf) {
                    const t = {
                        _name: 'Tabelle1', style: null,
                        load() { geladen.add(t); },
                        get name() {
                            if (!geladen.has(t)) throw new Error('PropertyNotLoaded: name');
                            return t._name;
                        },
                        set name(v) { t._name = v; }
                    };
                    zustand.tabellen.push({ adresse: adr, kopfzeile: kopf,
                                            blatt: name, obj: t });
                    return t;
                },
                getItem(n) {
                    return {
                        delete() { zustand.geloescht.push('tabelle-DELETE:' + n); },
                        convertToRange() { zustand.geloescht.push('tabelle-CONVERT:' + n); }
                    };
                }
            }
        };
        return s;
    }

    return {
        ConditionalFormatType: { cellValue: 'CellValue', colorScale: 'ColorScale',
                                 dataBar: 'DataBar' },
        ConditionalFormatColorCriterionType: { lowestValue: 'LowestValue',
                                               percentile: 'Percentile',
                                               highestValue: 'HighestValue' },
        run(fn) {
            const ctx = {
                workbook: {
                    worksheets: {
                        getItem: (n) => blatt(n),
                        getActiveWorksheet: () => blatt('Tabelle1')
                    }
                },
                sync() {
                    if (opt.syncWirft) return Promise.reject(new Error(opt.syncWirft));
                    return Promise.resolve();
                }
            };
            try { return Promise.resolve(fn(ctx)); }
            catch (e) { return Promise.reject(e); }
        }
    };
}

function umgebung(opt) {
    opt = opt || {};
    const zustand = { pivots: [], charts: [], tabellen: [], bedingt: [],
                      geloescht: [], protokoll: [] };
    const ns = {
        Excel: stub(zustand, opt),
        Promise: Promise,
        _kann18: opt.api18 !== false,
        T: (k, f) => f,
        protokoll: (b, t) => zustand.protokoll.push(b + ': ' + t),
        fehlerDetails: (e) => String(e && e.message || e),
        fehlerKurz: (e) => String(e && e.message || e),
        zustand: zustand
    };
    const rumpf = TEILE.map(t => code[t]).join('\n') +
        '\n;this.__f = {' + TEILE.map(t => t + ': ' + t).join(', ') + '};';
    const fn = new Function('Excel', 'Promise', '_kann18', 'T', 'protokoll',
                            'fehlerDetails', 'fehlerKurz', rumpf);
    const halter = {};
    fn.call(halter, ns.Excel, ns.Promise, ns._kann18, ns.T, ns.protokoll,
            ns.fehlerDetails, ns.fehlerKurz);
    return { f: halter.__f, zustand: zustand };
}

(async () => {
    console.log('── 1. istObjekt ────────────────────────────────────────────────');
    {
        const { f } = umgebung();
        pruefe(f.istObjekt({ typ: 'pivot' }) === true, 'typ=pivot ist ein Objekt');
        pruefe(!f.istObjekt({ adresse: 'A1', formel: '=A1' }),
               'Zell-Eintrag ist KEIN Objekt');
        pruefe(!f.istObjekt(null), 'null ist kein Objekt');
        pruefe(!f.istObjekt({}), 'leeres Objekt ist kein Objekt');
    }

    console.log('── 2. Quellbereich mit und ohne Blatt ──────────────────────────');
    {
        const { f } = umgebung();
        let ctxGemerkt = null;
        await f.Excel === undefined;  // nur zur Klarheit: Excel kommt aus dem Namensraum
        // quellBereich braucht einen ctx – wir bauen einen minimalen.
        const ctx = {
            workbook: {
                worksheets: {
                    getItem: (n) => ({ _blatt: n, getRange: (a) => ({ _adr: a, _blatt: n }) }),
                    getActiveWorksheet: () => ({ _blatt: '*aktiv*',
                                                 getRange: (a) => ({ _adr: a, _blatt: '*aktiv*' }) })
                }
            }
        };
        let r = f.quellBereich(ctx, 'Daten!A1:E200');
        pruefe(r._blatt === 'Daten' && r._adr === 'A1:E200',
               'Blattname wird abgetrennt');
        r = f.quellBereich(ctx, 'A1:E200');
        pruefe(r._blatt === '*aktiv*' && r._adr === 'A1:E200',
               'ohne Blattname gilt das aktive Blatt');
        r = f.quellBereich(ctx, "'Q1 2026'!A1:C9");
        pruefe(r._blatt === 'Q1 2026',
               'Blattname in Anfuehrungszeichen wird entpackt');
    }

    console.log('── 3. Pivot entsteht mit seinen Feldern ────────────────────────');
    {
        const { f, zustand } = umgebung({ api18: true });
        const a = { typ: 'pivot', blatt: 'Auswertung', adresse: 'A1',
                    name: 'Umsatz', quelle: 'Daten!A1:E200',
                    zeilenfelder: ['Region', 'Land'], spaltenfelder: ['Quartal'],
                    wertfelder: [{ feld: 'Umsatz', funktion: 'Sum' },
                                 { feld: 'Menge', funktion: 'Count' }] };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === true, 'Pivot wird angelegt');
        pruefe(zustand.pivots.length === 1, 'genau EINE Pivot-Tabelle');
        const p = zustand.pivots[0];
        pruefe(p.name === 'Umsatz', 'Name kommt an');
        pruefe(p.quelle === 'Daten!A1:E200', 'Quelle wird als Adressstring uebergeben');
        pruefe(p.ziel === 'A1', 'Ziel ist die Zielzelle');
        pruefe(p.blatt === 'Auswertung', 'Ziel liegt auf dem genannten Blatt');
        pruefe(JSON.stringify(p.obj._zeilen) === '["Region","Land"]',
               'beide Zeilenfelder gesetzt');
        pruefe(JSON.stringify(p.obj._spalten) === '["Quartal"]', 'Spaltenfeld gesetzt');
        pruefe(p.obj._werte.length === 2, 'beide Wertfelder gesetzt');
        pruefe(p.obj._werte[0].summarizeBy === 'Sum',
               'Aggregatfunktion wird gesetzt (sonst zaehlt Excel nur)');
        pruefe(p.obj._werte[1].summarizeBy === 'Count', 'zweite Funktion gesetzt');
        pruefe(a._objName === 'Umsatz', 'der Name wird fuer den Rueckweg gemerkt');
        pruefe(a._angelegt === true, 'als angelegt markiert');
    }

    console.log('── 4. ⚠ Ohne ExcelApi 1.8: Absage MIT GRUND, kein Wurf ─────────');
    {
        const { f, zustand } = umgebung({ api18: false });
        const a = { typ: 'pivot', blatt: '', adresse: 'A1', name: 'X',
                    quelle: 'D!A1:B9', zeilenfelder: ['R'],
                    wertfelder: [{ feld: 'U', funktion: 'Sum' }] };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === false, 'Pivot wird abgelehnt');
        pruefe(typeof r.grund === 'string' && r.grund.length > 10,
               'die Absage nennt einen Grund');
        pruefe(/1\.8/.test(r.grund), 'der Grund nennt die noetige Fassung');
        pruefe(zustand.pivots.length === 0, 'es wird NICHTS angelegt');
        pruefe(a._angelegt !== true,
               'nicht als angelegt markiert (sonst liefe der Rueckweg ins Leere)');
    }

    console.log('── 5. Diagramm ─────────────────────────────────────────────────');
    {
        const { f, zustand } = umgebung();
        const a = { typ: 'diagramm', blatt: 'Tabelle1', adresse: 'H2',
                    art: 'ColumnClustered', quelle: 'Daten!A1:B10',
                    titel: 'Umsatz 2026', name: 'MeinDiagramm' };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === true, 'Diagramm wird angelegt');
        pruefe(zustand.charts.length === 1, 'genau EIN Diagramm');
        const c = zustand.charts[0];
        pruefe(c.art === 'ColumnClustered', 'ChartType kommt unveraendert an');
        pruefe(c.quelle === 'A1:B10', 'Quelle wurde zur Range aufgeloest');
        pruefe(c.obj._pos === 'H2', 'Position wird gesetzt');
        pruefe(c.obj.title.text === 'Umsatz 2026', 'Titel wird gesetzt');
        pruefe(a._objName === 'MeinDiagramm', 'Name gemerkt');
    }
    {
        // Ohne eigenen Namen vergibt Excel einen – ohne Rueckleser gaebe es
        // keinen Rueckweg.
        const { f } = umgebung();
        const a = { typ: 'diagramm', blatt: '', adresse: 'A1', art: 'Line',
                    quelle: 'A1:B9' };
        await f.objektSchreiben(a);
        pruefe(a._objName === 'Diagramm 1',
               'ohne eigenen Namen wird der von Excel vergebene gelesen');
    }

    console.log('── 6. Tabelle ──────────────────────────────────────────────────');
    {
        const { f, zustand } = umgebung();
        const a = { typ: 'tabelle', blatt: 'Tabelle1', adresse: 'A1:E200',
                    name: 'Umsaetze', kopfzeile: true };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === true, 'Tabelle wird angelegt');
        pruefe(zustand.tabellen.length === 1, 'genau EINE Tabelle');
        pruefe(zustand.tabellen[0].adresse === 'A1:E200', 'Bereich kommt an');
        pruefe(zustand.tabellen[0].kopfzeile === true, 'kopfzeile kommt an');
        pruefe(a._objName === 'Umsaetze', 'Name gemerkt');
    }
    {
        const { f, zustand } = umgebung();
        await f.objektSchreiben({ typ: 'tabelle', blatt: '', adresse: 'A1:B9',
                                  name: 'T', kopfzeile: false });
        pruefe(zustand.tabellen[0].kopfzeile === false,
               'kopfzeile=false wird durchgereicht');
    }

    console.log('── 7. Bedingte Formatierung ────────────────────────────────────');
    {
        const { f, zustand } = umgebung();
        const a = { typ: 'bedingt', blatt: 'Tabelle1', adresse: 'B2:B99',
                    regel: 'zellwert', operator: 'GreaterThan', wert: '100',
                    farbe: '#FFC7CE', textfarbe: '#9C0006' };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === true, 'bedingtes Format wird angelegt');
        pruefe(zustand.bedingt.length === 1, 'genau EINE Regel');
        const cf = zustand.bedingt[0].cf;
        pruefe(cf.typ === 'CellValue', 'Typ CellValue');
        pruefe(cf.cellValue.rule && cf.cellValue.rule.operator === 'GreaterThan',
               'Operator kommt an');
        // ⚠ `formula1` erwartet eine FORMEL. Ein nackter Wert wird von Excel
        // teils als Text gelesen – dann greift die Regel nie.
        pruefe(cf.cellValue.rule.formula1 === '=100',
               'der Vergleichswert geht als FORMEL raus (mit fuehrendem =)');
        pruefe(cf.cellValue.format.fill.color === '#FFC7CE', 'Fuellfarbe gesetzt');
        pruefe(cf.cellValue.format.font.color === '#9C0006', 'Schriftfarbe gesetzt');
        pruefe(a._angelegt === true, 'als angelegt markiert');
    }
    {
        const { f, zustand } = umgebung();
        await f.objektSchreiben({ typ: 'bedingt', blatt: '', adresse: 'A1:A9',
                                  regel: 'zellwert', operator: 'Between',
                                  wert: '1', wert2: '9' });
        const rule = zustand.bedingt[0].cf.cellValue.rule;
        pruefe(rule.formula2 === '=9', 'zweiter Wert wird gesetzt');
    }
    {
        const { f, zustand } = umgebung();
        await f.objektSchreiben({ typ: 'bedingt', blatt: '', adresse: 'A1:A9',
                                  regel: 'farbskala' });
        pruefe(zustand.bedingt[0].cf.typ === 'ColorScale', 'Farbskala');
        pruefe(!!zustand.bedingt[0].cf.colorScale.criteria, 'Kriterien gesetzt');
    }
    {
        const { f, zustand } = umgebung();
        await f.objektSchreiben({ typ: 'bedingt', blatt: '', adresse: 'A1:A9',
                                  regel: 'datenbalken', farbe: '#63BE7B' });
        pruefe(zustand.bedingt[0].cf.typ === 'DataBar', 'Datenbalken');
    }

    console.log('── 8. ⚠ Ein Fehlschlag kostet NUR SICH SELBST ──────────────────');
    {
        // Das ist die tragende Zusage des „ein Excel.run je Objekt": ein
        // kaputtes Objekt darf die anderen nicht mitreissen.
        const { f, zustand } = umgebung({ syncWirft: 'InvalidArgument: Bereich' });
        const a = { typ: 'diagramm', blatt: '', adresse: 'A1', art: 'Line',
                    quelle: 'A1:B9' };
        const r = await f.objektSchreiben(a);
        pruefe(r.ok === false, 'ein Wurf wird zur Absage, nicht zum Absturz');
        pruefe(typeof r.grund === 'string' && r.grund.length > 0,
               'die Absage traegt den Grund');
        pruefe(zustand.protokoll.some(z => z.startsWith('objekt:')),
               'der Fehlschlag steht im Protokoll');
        pruefe(a._angelegt !== true, 'ein gescheitertes Objekt gilt NICHT als angelegt');
    }

    console.log('── 9. ⚠ Rueckweg: Tabelle wird ZURUECKVERWANDELT, nicht geloescht ─');
    {
        const { f, zustand } = umgebung();
        const ctx = {
            workbook: {
                worksheets: {
                    getItem: (n) => stubBlatt(n),
                    getActiveWorksheet: () => stubBlatt('Tabelle1')
                }
            }
        };
        function stubBlatt(n) {
            return {
                pivotTables: { getItem: (x) => ({ delete() { zustand.geloescht.push('pivot:' + x); } }) },
                charts: { getItem: (x) => ({ delete() { zustand.geloescht.push('chart:' + x); } }) },
                tables: {
                    getItem: (x) => ({
                        delete() { zustand.geloescht.push('tabelle-DELETE:' + x); },
                        convertToRange() { zustand.geloescht.push('tabelle-CONVERT:' + x); }
                    })
                },
                getRange: (adr) => ({
                    conditionalFormats: {
                        getItemAt: (i) => ({ delete() { zustand.geloescht.push('bedingt@' + adr + '#' + i); } })
                    }
                })
            };
        }
        f.objektLoeschen(ctx, { typ: 'pivot', blatt: 'A', _objName: 'P1' });
        f.objektLoeschen(ctx, { typ: 'diagramm', blatt: 'A', _objName: 'C1' });
        f.objektLoeschen(ctx, { typ: 'tabelle', blatt: 'A', _objName: 'T1' });
        f.objektLoeschen(ctx, { typ: 'bedingt', blatt: 'A', adresse: 'B2:B9' });

        pruefe(zustand.geloescht.includes('pivot:P1'), 'Pivot wird geloescht');
        pruefe(zustand.geloescht.includes('chart:C1'), 'Diagramm wird geloescht');
        // ⚠ DER WICHTIGSTE FALL DIESES WAECHTERS.
        // `Table.delete()` entfernt in Office.js die Tabelle SAMT DATEN. Beim
        // "Zuruecknehmen" waere das ein Datenverlust – und zwar genau dort, wo
        // der Benutzer den alten Zustand wiederhaben will.
        pruefe(zustand.geloescht.includes('tabelle-CONVERT:T1'),
               'Tabelle wird per convertToRange zurueckverwandelt');
        pruefe(!zustand.geloescht.some(x => x.startsWith('tabelle-DELETE')),
               'Table.delete() wird NIE gerufen (das loeschte die Daten mit)');
        pruefe(zustand.geloescht.includes('bedingt@B2:B9#0'),
               'bedingtes Format wird an Position 0 entfernt (add legt dort ab)');
        pruefe(!JSON.stringify(zustand.geloescht).includes('clearAll'),
               'clearAll() wird NIE gerufen (das traefe fremde Formate mit)');
    }

    console.log('── 10. Anzeige nennt WAS entsteht und WORAUS ───────────────────');
    {
        const { f } = umgebung();
        const t1 = f.objektText({ typ: 'pivot', quelle: 'Daten!A1:E9',
                                  zeilenfelder: ['Region'],
                                  wertfelder: [{ feld: 'Umsatz', funktion: 'Sum' }] });
        pruefe(/Daten!A1:E9/.test(t1), 'Pivot-Text nennt die Quelle');
        pruefe(/Region/.test(t1), 'Pivot-Text nennt das Zeilenfeld');
        pruefe(/Umsatz/.test(t1) && /Sum/.test(t1),
               'Pivot-Text nennt Wertfeld und Funktion');

        const t2 = f.objektText({ typ: 'tabelle', name: 'Umsaetze' });
        pruefe(/Umsaetze/.test(t2), 'Tabellen-Text nennt den Namen');

        const t3 = f.objektText({ typ: 'bedingt', regel: 'zellwert',
                                  operator: 'GreaterThan', wert: '100' });
        pruefe(/100/.test(t3), 'Regel-Text nennt den Vergleichswert');

        const k = f.eintragKurz({ typ: 'pivot', blatt: 'A', adresse: 'A1',
                                  name: 'P', quelle: 'D!A1:B9' });
        pruefe(/PIVOT/.test(k), 'Protokollzeile nennt die Gattung');
        // Ein Zell-Eintrag muss unveraendert aussehen.
        const k2 = f.eintragKurz({ blatt: 'A', adresse: 'B2', formel: '=A2*2' });
        pruefe(/formel\(/.test(k2) && !/PIVOT/.test(k2),
               'Zell-Eintrag behaelt seine Protokollform');
    }

    console.log('── 11. REGELN im Quelltext ─────────────────────────────────────');
    {
        // Diese drei Zusagen sind im Ablauf nicht messbar, weil sie ANDERE
        // Stellen betreffen – sie werden deshalb als Regel geprueft.
        const ohneKom = JS.replace(/\/\*[\s\S]*?\*\//g, '')
                          .split('\n').filter(z => !/^\s*\/\//.test(z)).join('\n');
        pruefe(/alle\.forEach\(function \(a\) \{\s*if \(!a\.blatt \|\| !a\._neuesBlatt\)/.test(ohneKom),
               'die Blatt-Anlage laeuft ueber ALLE Eintraege (auch Objekte)');
        pruefe(/var objekte = alle\.filter\(istObjekt\)/.test(ohneKom),
               'Objekte werden von den Zellen getrennt');
        pruefe(ohneKom.indexOf('var aenderungen = alle.filter') >
               ohneKom.indexOf('var objekte = alle.filter'),
               'beide Listen entstehen aus derselben Quelle');
        // Der Objekt-Schritt muss NACH dem Zellschreiben stehen.
        const iKos = ohneKom.indexOf('return kosmetik(aenderungen)');
        const iObj = ohneKom.indexOf('objekte.reduce(');
        pruefe(iKos > 0 && iObj > iKos,
               'Objekte werden NACH den Zellen geschrieben');
        pruefe(/_kann18/.test(ohneKom), 'die 1.8-Pruefung existiert');
        pruefe(/isSetSupported\('ExcelApi', '1\.8'\)/.test(ohneKom),
               'sie fragt genau ExcelApi 1.8 ab');
        // ⚠ EIN GESCHEITERTES OBJEKT GEHOERT IN DEN VERLAUF, nicht nur ins
        // Protokoll: anders als die Kosmetik hat der Benutzer es ausdruecklich
        // bestellt. Das Protokoll liegt hinter "Einstellungen → Diagnose",
        // dort sieht es im Alltag niemand. (Diese Verdrahtung war bis zur
        // Gegenprobe UNGEPRUEFT – der Waechter mass nur `objektSchreiben`.)
        // ⚠ GEPRUEFT WIRD DIE BEDINGUNG SELBST, nicht ihr Vorkommen: ein
        // `if (false && erg.objFehler …)` enthaelt den Ausdruck weiterhin und
        // laesst eine Suche nach dem Text gruen – die Gegenprobe blieb genau
        // daran stumm. Die Bedingung muss also GENAU so beginnen.
        pruefe(/if \(erg\.objFehler && erg\.objFehler\.length\)/.test(ohneKom),
               'die Bedingung ist nicht totgelegt (kein `false &&` davor)');
        const iFehl = ohneKom.indexOf('erg.objFehler && erg.objFehler.length');
        pruefe(iFehl > 0, 'der Objekt-Fehler wird ausgewertet');
        const nachFehl = ohneKom.slice(iFehl, iFehl + 700);
        pruefe(/_verlauf\.push/.test(nachFehl),
               'und landet im VERLAUF, nicht nur im Protokoll');
        pruefe(/xl\.obj_failed_hint/.test(nachFehl),
               'der Text sagt, dass die Zellenaenderungen trotzdem stehen');
    }

    clearTimeout(wachhund);
    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => {
    console.log('  FAIL: unbehandelter Fehler: ' + (e && e.stack || e));
    fail++;
    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(1);
});
