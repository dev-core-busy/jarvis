#!/usr/bin/env node
/* Waechter: ein halb angelegtes Excel-Objekt bleibt nicht stehen
 * (Nebenbefund Code-Review 2026-09-28, "Pivot-Rest in objektSchreiben").
 *
 * ⚠ DER BEFUND: `pivotTables.add` und die Feld-Zuordnungen liefen in EINEM
 * `ctx.sync()`. Office.js fuehrt den Stapel der Reihe nach aus und bricht beim
 * ersten Fehler ab – was DAVOR lief, bleibt. Ein falscher Feldname legte also
 * die Pivot-Tabelle an, der Lauf meldete "nicht angelegt", `_angelegt` blieb
 * leer: ein Rest im Blatt, den keine Ruecknahme mehr trifft.
 *
 * ⚠ DIE ATTRAPPE HAT GENAU DIESE EIGENSCHAFT: Befehle landen in einer
 * Warteschlange, `sync` fuehrt sie der Reihe nach aus, der erste Fehler bricht
 * ab und die vorherigen Wirkungen bleiben. Eine Attrappe, die schon beim
 * Aufruf wirft oder den ganzen Stapel zuruecknimmt, liesse den Befund durch.
 *
 * AUSGEFUEHRT: die echten Funktionen aus excel.js werden geschnitten.
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');

let ok = 0, fail = 0, bilanz = false;
function pruefe(bed, text) {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text); }
}
process.on('exit', () => {
    if (!bilanz) {
        console.log('\nErgebnis: ABGEBROCHEN – keine Bilanz erreicht');
        process.exitCode = 1;
    }
});
setTimeout(() => { console.log('\nErgebnis: ABGEBROCHEN – Zeitlimit'); process.exit(1); },
           20000).unref();

/* Geklammert schneiden (Strings, Kommentare). */
function schneide(name) {
    const i = JS.indexOf('function ' + name + '(');
    if (i < 0) return null;
    const auf = JS.indexOf('{', i);
    let tiefe = 0, inStr = null, inCom = null;
    for (let j = auf; j < JS.length; j++) {
        const c = JS[j], n = JS[j + 1];
        if (inCom === '/*') { if (c === '*' && n === '/') { inCom = null; j++; } continue; }
        if (inCom === '//') { if (c === '\n') inCom = null; continue; }
        if (inStr) { if (c === '\\') { j++; continue; } if (c === inStr) inStr = null; continue; }
        if (c === '/' && n === '*') { inCom = '/*'; j++; continue; }
        if (c === '/' && n === '/') { inCom = '//'; j++; continue; }
        if (c === '"' || c === "'" || c === '`') { inStr = c; continue; }
        if (c === '{') tiefe++;
        else if (c === '}') { tiefe--; if (tiefe === 0) return JS.slice(i, j + 1); }
    }
    return null;
}

const code = [];
for (const t of ['objektSchreiben', 'blattVon', 'quellBereich']) {
    const c = schneide(t);
    if (!c) { console.log('ABBRUCH: ' + t + ' nicht schneidbar'); bilanz = true; process.exit(2); }
    code.push(c);
}
// Helfer des Fixes OPTIONAL – fehlt er (Altstand/Gegenprobe), soll der
// Waechter an der WIRKUNG scheitern, nicht am Schnitt.
const hilfe = schneide('objektAbbauen');
if (hilfe) code.push(hilfe);

/* ── Attrappe ───────────────────────────────────────────────────────────── */
function neueMappe() {
    return { pivots: new Set(), charts: new Set(), tables: new Set(), bereiche: new Set() };
}

function kontext(wb, felder) {
    let queue = [];
    const q = (fn) => queue.push(fn);
    const fehler = (was) => { const e = new Error('InvalidArgument: ' + was); e.code = 'InvalidArgument'; return e; };
    let zaehler = 0;

    function pivot(name) {
        const p = {
            name: undefined,
            load() { q(() => { p.name = name; }); },
            delete() { q(() => { if (!wb.pivots.delete(name)) throw fehler('pivot weg'); }); },
            hierarchies: { getItem(f) { return { f }; } },
        };
        const zuordnung = {
            add(h) { q(() => { if (!felder.includes(h.f)) throw fehler('Feld ' + h.f); }); return {}; }
        };
        p.rowHierarchies = zuordnung;
        p.columnHierarchies = zuordnung;
        p.dataHierarchies = {
            add(h) { q(() => { if (!felder.includes(h.f)) throw fehler('Feld ' + h.f); }); return {}; }
        };
        return p;
    }

    function blatt() {
        return {
            getRange(adr) { return { adr }; },
            pivotTables: {
                add(name) { q(() => { wb.pivots.add(name); }); return pivot(name); }
            },
            charts: {
                add() {
                    const n = 'Diagramm ' + (++zaehler);
                    q(() => { wb.charts.add(n); });
                    const c = {
                        name: undefined,
                        load() { q(() => { c.name = c._n || n; }); },
                        setPosition() { },
                        title: {},
                        delete() { q(() => { if (!wb.charts.delete(c._n || n)) throw fehler('chart weg'); }); },
                    };
                    Object.defineProperty(c, 'name', {
                        get() { return c._gelesen; },
                        set(v) { q(() => { if (/!/.test(v)) throw fehler('Name ' + v);
                                           wb.charts.delete(n); wb.charts.add(v); c._n = v; }); },
                    });
                    c.load = () => q(() => { c._gelesen = c._n || n; });
                    return c;
                }
            },
            tables: {
                add(adr) {
                    q(() => { wb.tables.add(adr); });
                    const t = {
                        load() { },
                        convertToRange() { q(() => { wb.tables.delete(adr); wb.bereiche.add(adr); }); },
                        delete() { q(() => { throw new Error('Table.delete nimmt die Daten mit'); }); },
                    };
                    Object.defineProperty(t, 'name', {
                        get() { return t._n; },
                        set(v) { q(() => { if (/\s/.test(v)) throw fehler('Tabellenname ' + v); t._n = v; }); },
                    });
                    return t;
                }
            },
        };
    }

    return {
        workbook: { worksheets: { getItem: () => blatt(), getActiveWorksheet: () => blatt() } },
        sync() {
            const jetzt = queue; queue = [];
            try { for (const fn of jetzt) fn(); }
            catch (e) { return Promise.reject(e); }   // vorherige Wirkungen BLEIBEN
            return Promise.resolve();
        },
    };
}

function lade(wb, felder, protokollLog) {
    const Excel = { run: (fn) => { try { return Promise.resolve(fn(kontext(wb, felder))); }
                                   catch (e) { return Promise.reject(e); } } };
    const f = new Function('Excel', 'T', 'protokoll', 'fehlerDetails', 'fehlerKurz',
        '_kann18', 'bedingtSetzen',
        code.join('\n') + '\nreturn { objektSchreiben: objektSchreiben };');
    return f(Excel, (k, d) => d, (a, b) => protokollLog.push(a + ': ' + b),
             (e) => String(e && e.message), (e) => String(e && e.message), true, () => {});
}

/* ── Faelle ─────────────────────────────────────────────────────────────── */
(async () => {
    const FELDER = ['Region', 'Umsatz'];

    // Positivkontrolle: der gute Fall legt an und markiert – sonst waeren die
    // "kein Rest"-Pruefungen darunter trivial wahr (nichts angelegt = nichts uebrig).
    {
        const wb = neueMappe(), log = [];
        const r = await lade(wb, FELDER, log).objektSchreiben({
            typ: 'pivot', name: 'P1', quelle: 'A1:B9', adresse: 'D1', blatt: '',
            zeilenfelder: ['Region'], wertfelder: [{ feld: 'Umsatz', funktion: 'Sum' }] });
        pruefe(r.ok === true && r.a._angelegt === true && wb.pivots.has('P1'),
               'Positivkontrolle: gueltige Pivot wird angelegt und ist ruecknehmbar');
    }

    // Der gemeldete Fall: falscher Feldname.
    {
        const wb = neueMappe(), log = [];
        const r = await lade(wb, FELDER, log).objektSchreiben({
            typ: 'pivot', name: 'P2', quelle: 'A1:B9', adresse: 'D1', blatt: '',
            zeilenfelder: ['Regoin'], wertfelder: [{ feld: 'Umsatz', funktion: 'Sum' }] });
        pruefe(r.ok === false, 'falscher Feldname: gemeldet als nicht angelegt');
        pruefe(!wb.pivots.has('P2'),
               'falscher Feldname: KEINE halbe Pivot bleibt im Blatt (ist: ' + [...wb.pivots] + ')');
        pruefe(!r.a._angelegt, 'falscher Feldname: nicht als angelegt markiert');
    }

    // Gleiche Eigenschaft beim Diagramm (ungueltiger Name im zweiten Schritt).
    {
        const wb = neueMappe(), log = [];
        const r = await lade(wb, FELDER, log).objektSchreiben({
            typ: 'diagramm', art: 'ColumnClustered', quelle: 'A1:B9', adresse: 'D1',
            blatt: '', name: 'Kaputt!Name' });
        pruefe(r.ok === false && wb.charts.size === 0,
               'Diagramm mit ungueltigem Namen: kein Rest (ist: ' + [...wb.charts] + ')');
    }

    // Tabelle: der Abbau darf die DATEN nicht mitnehmen (convertToRange, nicht delete).
    {
        const wb = neueMappe(), log = [];
        const r = await lade(wb, FELDER, log).objektSchreiben({
            typ: 'tabelle', adresse: 'A1:B9', blatt: '', name: 'mit Leerzeichen' });
        pruefe(r.ok === false && wb.tables.size === 0,
               'Tabelle mit ungueltigem Namen: keine Tabelle bleibt');
        pruefe(wb.bereiche.has('A1:B9'),
               'Tabelle: zurueckverwandelt statt geloescht (Daten bleiben)');
    }

    // Scheitert schon das Anlegen selbst, darf kein Abbau-Fehler den Grund ersetzen.
    {
        const wb = neueMappe(), log = [];
        const r = await lade(wb, FELDER, log).objektSchreiben({
            typ: 'pivot', name: 'P3', quelle: 'A1:B9', adresse: 'D1', blatt: '',
            zeilenfelder: ['Regoin'] });
        pruefe(/Feld Regoin/.test(r.grund || ''),
               'der gemeldete Grund ist der URSPRUENGLICHE Fehler (ist: ' + r.grund + ')');
    }

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exitCode = fail ? 1 : 0;
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack)); bilanz = true; process.exitCode = 2; });
