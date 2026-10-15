#!/usr/bin/env node
/* Waechter: Zuruecknehmen im Excel-Aufgabenfenster uebersteht von Hand
 * entfernte Objekte und Blaetter (Review 2026-09-28 #11).
 *
 * ⚠ DER BEFUND: `zuruecknehmen` hatte je Objekt ein `try` um `getItem(...)
 * .delete()`. Office.js wirft dort aber NICHT – ItemNotFound kommt erst beim
 * gemeinsamen `ctx.sync()`. Ein von Hand geloeschtes Diagramm liess damit die
 * GANZE Ruecknahme scheitern; Zellen und uebrige Objekte blieben stehen.
 *
 * ⚠ DIE ATTRAPPE WIRFT DORT, WO OFFICE.JS WIRFT: beim Sync, nicht beim Aufruf.
 * Eine Attrappe, die schon bei `getItem` wirft, liesse genau den Fehler
 * durchgehen, um den es geht (das `try` saehe dann wirksam aus). Und sie
 * verlangt `load()` + Sync vor dem Lesen von `isNullObject` / `value`.
 *
 * AUSGEFUEHRT: die echten Funktionen aus excel.js werden geschnitten und
 * gegen die Attrappe laufen gelassen.
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

/* Geklammert schneiden (Einzeiler-Funktionen, Strings, Kommentare). */
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

// Pflicht: zuruecknehmen, objektLoeschen, blattVon, istObjekt. Die Helfer des
// Fixes sind OPTIONAL geschnitten - fehlen sie (Altstand/Gegenprobe), soll der
// Waechter an der WIRKUNG scheitern, nicht am Schnitt.
const PFLICHT = ['zuruecknehmen', 'objektLoeschen', 'blattVon', 'istObjekt'];
const code = [];
for (const t of PFLICHT) {
    const c = schneide(t);
    if (!c) { console.log('ABBRUCH: ' + t + ' nicht schneidbar'); bilanz = true; process.exit(2); }
    code.push(c);
}
for (const t of ['objektSuchen', 'objektVorhanden']) {
    const c = schneide(t);
    if (c) code.push(c);
}
pruefe(code[0].includes('Excel.run'), 'Positivkontrolle: Schnitt zuruecknehmen enthaelt Excel.run');

/* ── Attrappe: Arbeitsmappe + verzoegerte Fehler ─────────────────────────── */
function mappe(def) {
    // def: { Blatt: { charts:[..], pivots:[..], tables:[..], cf:{adr:n} } }
    const wb = {};
    for (const [n, d] of Object.entries(def)) {
        wb[n] = { charts: new Set(d.charts || []), pivots: new Set(d.pivots || []),
                  tables: new Set(d.tables || []), cf: Object.assign({}, d.cf || {}),
                  zellen: {} };
    }
    return wb;
}

function kontext(wb, log) {
    let queue = [];
    const q = (fn) => queue.push(fn);
    const nf = (was) => { const e = new Error('ItemNotFound: ' + was); e.code = 'ItemNotFound'; return e; };

    function nullObj(pruef) {
        const o = { _geladen: false, _wert: null };
        Object.defineProperty(o, 'isNullObject', { get() {
            if (!o._geladen) throw new Error('PropertyNotLoaded: isNullObject');
            return o._wert;
        } });
        o.load = () => q(() => { o._geladen = true; o._wert = !pruef(); });
        return o;
    }
    function sammlung(blattName, feld, art) {
        return {
            getItem(n) {
                return { delete() { q(() => {
                    const b = wb[blattName];
                    if (!b) throw nf('Blatt ' + blattName);
                    if (!b[feld].has(n)) throw nf(art + ' ' + n);
                    b[feld].delete(n); log.push(art + '-weg:' + n);
                }); }, convertToRange() { q(() => {
                    const b = wb[blattName];
                    if (!b) throw nf('Blatt ' + blattName);
                    if (!b[feld].has(n)) throw nf(art + ' ' + n);
                    b[feld].delete(n); log.push(art + '-weg:' + n);
                }); } };
            },
            getItemOrNullObject(n) {
                const o = nullObj(() => wb[blattName] && wb[blattName][feld].has(n));
                return o;
            }
        };
    }
    function blatt(name) {
        return {
            pivotTables: sammlung(name, 'pivots', 'pivot'),
            charts: sammlung(name, 'charts', 'chart'),
            tables: sammlung(name, 'tables', 'tabelle'),
            getRange(adr) {
                const r = {
                    format: { fill: { set color(v) { q(() => {}); }, clear() { q(() => {}); } } },
                    set formulas(v) { q(() => {
                        if (!wb[name]) throw nf('Blatt ' + name);
                        wb[name].zellen[adr] = v; log.push('zelle:' + name + '!' + adr);
                    }); },
                    set numberFormat(v) { q(() => { if (!wb[name]) throw nf('Blatt ' + name); }); },
                    conditionalFormats: {
                        getCount() {
                            const res = { _g: false, _v: 0 };
                            Object.defineProperty(res, 'value', { get() {
                                if (!res._g) throw new Error('PropertyNotLoaded: value');
                                return res._v;
                            } });
                            q(() => {
                                if (!wb[name]) throw nf('Blatt ' + name);
                                res._g = true; res._v = wb[name].cf[adr] || 0;
                            });
                            return res;
                        },
                        getItemAt(i) { return { delete() { q(() => {
                            if (!wb[name]) throw nf('Blatt ' + name);
                            if (!(wb[name].cf[adr] > i)) throw nf('bedingt ' + adr);
                            wb[name].cf[adr]--; log.push('bedingt-weg:' + adr);
                        }); } }; }
                    }
                };
                return r;
            }
        };
    }
    return {
        workbook: { worksheets: {
            getItem: (n) => blatt(n),
            getActiveWorksheet: () => blatt(Object.keys(wb)[0]),
            getItemOrNullObject(n) {
                const o = nullObj(() => !!wb[n]);
                const b = blatt(n);
                // defineProperty, NICHT Object.assign: assign ruft den Getter
                // sofort auf - und der wirft vor dem Sync (PropertyNotLoaded).
                b.load = o.load;
                Object.defineProperty(b, 'isNullObject', { get() { return o.isNullObject; } });
                return b;
            }
        } },
        // Office-Semantik: der Stapel laeuft der Reihe nach, der ERSTE Fehler
        // bricht ab, der Rest des Stapels entfaellt.
        sync() {
            const jetzt = queue; queue = [];
            try { jetzt.forEach((f) => f()); }
            catch (e) { log.push('SYNC-FEHLER:' + e.message); return Promise.reject(e); }
            return Promise.resolve();
        }
    };
}

async function lauf(wb, aenderungen) {
    const log = [], meldungen = [];
    const env = {
        _rueckweg: { aenderungen: aenderungen, angelegt: [] },
        _erledigt: null, _laeuft: false, _verlauf: [],
    };
    const fabrik = new Function('env', 'Excel', 'log', 'meldungen', `
        var _rueckweg = env._rueckweg, _erledigt = env._erledigt, _laeuft = false,
            _verlauf = env._verlauf;
        function T(k, f) { return f; }
        function frage() { return Promise.resolve(true); }
        function melde(id, text, art) { meldungen.push({ text: text, art: art }); }
        function setzeLaeuft() {}
        function markAn() { return false; }
        function protokoll(w, t) { log.push('protokoll:' + t); }
        function fehlerDetails(e) { return String(e && e.message || e); }
        function eintragKurz(a) { return a.typ + ':' + (a._objName || a.adresse); }
        function zeichneVerlauf() {}
        ${code.join('\n')}
        return { zuruecknehmen: zuruecknehmen,
                 stand: function () { return { rueckweg: _rueckweg }; } };
    `);
    const Excel = { run: (fn) => Promise.resolve().then(() => fn(kontext(wb, log))) };
    const f = fabrik(env, Excel, log, meldungen);
    f.zuruecknehmen();
    for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
    return { log, meldungen, stand: f.stand() };
}

const ZELLE_A = { blatt: 'A', adresse: 'B2', _altF: [['=1+1']] };
const ZELLE_B = { blatt: 'B', adresse: 'C3', _altF: [['7']] };
const CHART = { typ: 'diagramm', blatt: 'A', _objName: 'C1', _angelegt: true };
const PIVOT = { typ: 'pivot', blatt: 'A', _objName: 'P1', _angelegt: true };
const BEDINGT = { typ: 'bedingt', blatt: 'A', adresse: 'D1:D9', _angelegt: true };

(async () => {
    console.log('\n=== 1. Positivkontrolle: alles noch da ===');
    let wb = mappe({ A: { charts: ['C1'], pivots: ['P1'], cf: { 'D1:D9': 1 } } });
    let r = await lauf(wb, [ZELLE_A, CHART, PIVOT, BEDINGT]);
    pruefe(r.log.includes('zelle:A!B2'), 'Zelle zurueckgeschrieben');
    pruefe(!wb.A.charts.has('C1') && !wb.A.pivots.has('P1'), 'Diagramm und Pivot entfernt');
    pruefe(wb.A.cf['D1:D9'] === 0, 'bedingte Formatierung entfernt');
    const m1 = r.meldungen[r.meldungen.length - 1] || {};
    pruefe(m1.art === 'ok', 'Meldung ok: ' + JSON.stringify(m1));
    pruefe(r.stand.rueckweg === null, 'Rueckweg verbraucht');

    console.log('\n=== 2. ⚠ Diagramm von Hand geloescht ===');
    wb = mappe({ A: { charts: [], pivots: ['P1'], cf: { 'D1:D9': 1 } } });
    r = await lauf(wb, [ZELLE_A, CHART, PIVOT, BEDINGT]);
    pruefe(!r.log.some((l) => l.startsWith('SYNC-FEHLER')), 'kein Sync-Fehler: ' +
           r.log.filter((l) => l.startsWith('SYNC')).join(' | '));
    pruefe(r.log.includes('zelle:A!B2'), 'Zelle trotzdem zurueckgeschrieben');
    pruefe(!wb.A.pivots.has('P1'), 'Pivot trotzdem entfernt');
    pruefe(wb.A.cf['D1:D9'] === 0, 'bedingte Formatierung trotzdem entfernt');
    const m2 = r.meldungen[r.meldungen.length - 1] || {};
    pruefe(m2.art === 'ok', 'Meldung ok, nicht fehler: ' + JSON.stringify(m2));
    pruefe(/1 Teil/.test(m2.text || ''), 'Meldung nennt den fehlenden Teil: ' + m2.text);

    console.log('\n=== 3. ⚠ Blatt von Hand geloescht ===');
    wb = mappe({ A: { charts: ['C1'] } });
    r = await lauf(wb, [ZELLE_A, ZELLE_B, CHART]);
    pruefe(!r.log.some((l) => l.startsWith('SYNC-FEHLER')), 'kein Sync-Fehler: ' +
           r.log.filter((l) => l.startsWith('SYNC')).join(' | '));
    pruefe(r.log.includes('zelle:A!B2'), 'Zelle auf vorhandenem Blatt zurueckgeschrieben');
    pruefe(!wb.A.charts.has('C1'), 'Diagramm entfernt');
    const m3 = r.meldungen[r.meldungen.length - 1] || {};
    pruefe(m3.art === 'ok' && /1 Teil/.test(m3.text || ''),
           'Meldung ok mit fehlendem Teil: ' + JSON.stringify(m3));

    console.log('\n=== 4. Bedingte Formatierung von Hand entfernt ===');
    wb = mappe({ A: { cf: {} } });
    r = await lauf(wb, [ZELLE_A, BEDINGT]);
    pruefe(!r.log.some((l) => l.startsWith('SYNC-FEHLER')), 'kein Sync-Fehler');
    pruefe(r.log.includes('zelle:A!B2'), 'Zelle zurueckgeschrieben');

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('WURF: ' + (e && e.stack || e)); bilanz = true; process.exit(1); });
