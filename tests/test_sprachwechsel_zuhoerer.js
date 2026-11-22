#!/usr/bin/env node
/* Waechter: jeder Zuhoerer auf `jarvis-lang-changed` haengt an DEM Ziel, an
 * dem i18n.js das Ereignis sendet.
 *
 * VORFALL (2026-11-22): sicherheitsprotokoll.js, protokolle.js,
 * fehleranalyse.js und token_verbrauch.js hoerten am `document`, i18n.js
 * sendet am `window`. Ein Ereignis am window erreicht einen Zuhoerer am
 * document nie (es laeuft nicht abwaerts) – die vier Ansichten blieben nach
 * einem Sprachwechsel in der alten Sprache, auf DEV im Chrome gemessen.
 * Ihre jsdom-Waechter waren gruen, weil sie das Ereignis SELBST am document
 * ausloesten: sie bestaetigten die Annahme des Codes statt den echten Weg.
 *
 * REGEL am Syntaxbaum (acorn), ueber ALLE Module in frontend/js (ohne
 * vendor/) – keine Namensliste:
 *   - das Sendeziel wird aus i18n.js GELESEN (`<ziel>.dispatchEvent(new
 *     CustomEvent('jarvis-lang-changed', …))`), nicht abgetippt; alle Sender
 *     muessen dasselbe Ziel haben;
 *   - jedes `<x>.addEventListener/removeEventListener('jarvis-lang-changed', …)`
 *     hat genau dieses Ziel.
 * Erwaehnungen in Kommentaren und Zeichenketten zaehlen nicht (Syntaxbaum).
 *
 * Nicht erfasst und deshalb hier benannt: Inline-Skripte in HTML-Seiten –
 * gemessen 2026-11-22: keine einzige Fundstelle dort.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen (Positivkontrolle).
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const acorn = require('./lib/acorn_laden')();

const WURZEL = path.resolve(__dirname, '..');
const JS = path.join(WURZEL, 'frontend/js');
const EREIGNIS = 'jarvis-lang-changed';

let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(text) {
    console.log('ABBRUCH: ' + text);
    process.exit(2);
}

function kinder(n, cb) {
    for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && cb(x));
        else if (v && typeof v.type === 'string' && k !== 'loc') cb(v);
    }
}
function laufe(n, cb) { cb(n); kinder(n, c => laufe(c, cb)); }
const name = (n) => n && (n.type === 'Identifier' ? n.name
    : n.type === 'ThisExpression' ? 'this'
    : n.type === 'MemberExpression' && !n.computed ? name(n.object) + '.' + n.property.name : '?');
const istEreignis = a => a && a.type === 'Literal' && a.value === EREIGNIS;

/** Sender und Zuhoerer einer Quelle: [{ziel, zeile}]. Wirft, wenn nicht parsebar. */
function untersuche(src) {
    const baum = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script',
                                    allowReturnOutsideFunction: true, locations: true });
    const sender = [], zuhoerer = [];
    laufe(baum, n => {
        if (n.type !== 'CallExpression' || n.callee.type !== 'MemberExpression' || n.callee.computed) return;
        const m = n.callee.property.name;
        const a0 = n.arguments[0];
        if (m === 'dispatchEvent' && a0 && a0.type === 'NewExpression' && istEreignis(a0.arguments[0])) {
            sender.push({ ziel: name(n.callee.object), zeile: n.loc.start.line });
        }
        if ((m === 'addEventListener' || m === 'removeEventListener') && istEreignis(a0)) {
            zuhoerer.push({ ziel: name(n.callee.object), zeile: n.loc.start.line, art: m });
        }
    });
    return { sender, zuhoerer };
}

function dateien(dir) {
    const aus = [];
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) { if (e.name !== 'vendor') aus.push(...dateien(p)); }
        else if (e.name.endsWith('.js')) aus.push(p);
    }
    return aus;
}

console.log('\n0. Positivkontrollen der Messung');
{
    const a = untersuche("document.addEventListener('" + EREIGNIS + "', function () {});");
    const b = untersuche("window.addEventListener('" + EREIGNIS + "', f); window.removeEventListener('" + EREIGNIS + "', f);");
    const c = untersuche("// document.addEventListener('" + EREIGNIS + "', f)\n"
                         + "var s = \"document.addEventListener('" + EREIGNIS + "', f)\";\n"
                         + "document.addEventListener('anderes-ereignis', f);");
    const d = untersuche("try { window.dispatchEvent(new CustomEvent('" + EREIGNIS + "', { detail: {} })); } catch (e) {}");
    const gut = a.zuhoerer.length === 1 && a.zuhoerer[0].ziel === 'document'
        && b.zuhoerer.length === 2 && b.zuhoerer.every(z => z.ziel === 'window')
        && c.zuhoerer.length === 0 && c.sender.length === 0
        && d.sender.length === 1 && d.sender[0].ziel === 'window';
    if (!gut) abbruch('die Sonde erkennt Ziel/Ereignis nicht richtig: ' + JSON.stringify({ a, b, c, d }));
    console.log('  Sonde erkennt document/window, uebergeht Kommentar, Zeichenkette und fremde Ereignisse');
}

const liste = dateien(JS);
const funde = { sender: [], zuhoerer: [] };
for (const p of liste) {
    let r;
    try { r = untersuche(fs.readFileSync(p, 'utf8')); }
    catch (e) { abbruch(path.relative(WURZEL, p) + ' nicht parsebar (' + e.message + ') – Regel waere dort blind'); }
    const rel = path.relative(WURZEL, p);
    r.sender.forEach(s => funde.sender.push(Object.assign({ datei: rel }, s)));
    r.zuhoerer.forEach(z => funde.zuhoerer.push(Object.assign({ datei: rel }, z)));
}
const i18nSender = funde.sender.filter(s => s.datei === 'frontend/js/i18n.js');
if (!i18nSender.length) abbruch('kein Sender in frontend/js/i18n.js gefunden – Sendeziel unbekannt');
if (!funde.zuhoerer.length) abbruch('kein einziger Zuhoerer gefunden – Messung waere trivial');
const ZIEL = i18nSender[0].ziel;
console.log('  ' + liste.length + ' Module, Sendeziel aus i18n.js: ' + ZIEL
            + ', ' + funde.zuhoerer.length + ' Zuhoerer');

console.log('\n1. Alle Sender haben dasselbe Ziel');
const fremdeSender = funde.sender.filter(s => s.ziel !== ZIEL);
check('kein Sender an einem anderen Ziel als ' + ZIEL, fremdeSender.length === 0,
      fremdeSender.map(s => s.datei + ':' + s.zeile + ' (' + s.ziel + ')').join(', '));

console.log('\n2. Jeder Zuhoerer haengt am Sendeziel');
const falsch = funde.zuhoerer.filter(z => z.ziel !== ZIEL);
check('⚠ jeder Zuhoerer auf ' + EREIGNIS + ' haengt an ' + ZIEL
      + ' (sonst erreicht ihn der Sprachwechsel nie)', falsch.length === 0,
      falsch.map(z => z.datei + ':' + z.zeile + ' (' + z.ziel + ')').join(', '));

console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
