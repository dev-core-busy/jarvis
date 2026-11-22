/* Waechter: die Wachhunde der JS-Waechter schlagen bei STILLSTAND an, nicht nach fester Dauer.
 *
 * WARUM (2026-11-22): rund sechzig Waechter trugen einen festen Wecker ueber
 * den ganzen Lauf; unter Volllast im Sammellauf riss er, obwohl jede Pruefung
 * bestanden hatte (test_dienst_neustart_ui.js: allein 8 s, unter Last 28 s
 * bei 25 s Wecker). Seitdem nehmen alle `tests/lib/wachhund.js`.
 *
 * Teil A misst die WIRKUNG des Helfers, jeder Fall in einem eigenen Prozess
 * (der Hund beendet den Prozess): Stillstand schlaegt an, laufende Ausgabe
 * haelt wach, Last verlaengert die Frist, clearTimeout und unref wirken,
 * eine ersetzte Uhr (Date.now) stoert ihn nicht.
 * Teil B prueft die REGEL am Syntaxbaum: in tests/*.js und tests/lib/*.js
 * kein `setTimeout(..., >= 10000)` mehr auf oberster Ebene (dort stehen die
 * Wachhunde; lange Wartezeiten INNERHALB von Funktionen sind Ablauf, keine
 * Wachhunde). Ein Vorkommen im Text zaehlt nicht.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const HELFER = path.join(__dirname, 'lib', 'wachhund.js');
let ok = 0, fail = 0;
function pruefe(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail !== undefined ? '  -> ' + detail : '')); }
}
function abbruch(grund) {
    console.log('\nABBRUCH (Exit 2): ' + grund);
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL (nicht deutbar)');
    process.exit(2);
}
if (!fs.existsSync(HELFER)) abbruch('tests/lib/wachhund.js fehlt');

// ═══ Teil A: Wirkung ════════════════════════════════════════════════════
console.log('Teil A: Wirkung des Helfers (je Fall ein Prozess)');

const KERNE = (os.cpus() || []).length || 1;
// Kopf jedes Falls: Last festlegen (vor dem ersten Hund), Uhr fuer die Dauer.
function fall(last, rumpf) {
    const kopf = "const os = require('os'); os.loadavg = () => [" + last + ', 0, 0];\n'
        + "const t0 = Date.now();\nconst hund = require(" + JSON.stringify(HELFER) + ');\n';
    const r = spawnSync(process.execPath, ['-e', kopf + rumpf], { encoding: 'utf8', timeout: 20000 });
    return { rc: r.status, aus: (r.stdout || '') + (r.stderr || ''), zeit: r.error ? 'Zeitlimit' : null };
}
const dauer = (aus) => { const m = /DAUER (\d+)/.exec(aus); return m ? Number(m[1]) : NaN; };

// Positivkontrolle: ein Kindprozess laeuft ueberhaupt und meldet sich.
{
    const r = fall(0, "console.log('LEBT'); process.exit(0);");
    if (r.rc !== 0 || !/LEBT/.test(r.aus)) abbruch('Kindprozess laeuft nicht: rc=' + r.rc + ' ' + r.aus.slice(0, 200));
}

{
    const r = fall(0, "hund(() => { console.log('DAUER ' + (Date.now() - t0)); process.exit(7); }, 400);\n"
        + 'setInterval(() => {}, 1000);');
    const d = dauer(r.aus);
    pruefe('Stillstand: der Hund schlaegt an (Exit des Anschlags, Meldung mit Grund)',
           r.rc === 7 && /Wachhund: \d+ s ohne neue Ausgabe/.test(r.aus), 'rc=' + r.rc + ' ' + r.aus.trim());
    pruefe('…nach der Grundfrist, nicht davor (400 ms)', d >= 380 && d < 3000, d + ' ms');
}
{
    const r = fall(0, "hund(() => { console.log('ANGESCHLAGEN'); process.exit(7); }, 400);\n"
        + "let n = 0; const i = setInterval(() => { console.log('Pruefung ' + (++n));\n"
        + '  if (n === 15) { clearInterval(i); process.exit(0); } }, 100);');
    pruefe('laufende Ausgabe haelt wach (1,5 s Lauf bei 0,4 s Frist)',
           r.rc === 0 && !/ANGESCHLAGEN/.test(r.aus), 'rc=' + r.rc + ' ' + r.aus.slice(-200));
}
{
    const r = fall(KERNE * 3, "hund(() => { console.log('DAUER ' + (Date.now() - t0)); process.exit(7); }, 300);\n"
        + 'setInterval(() => {}, 1000);');
    const d = dauer(r.aus);
    pruefe('Last 3 je Kern: Frist verdreifacht (>= 900 ms statt 300 ms)', r.rc === 7 && d >= 880, d + ' ms');
    pruefe('…und die Meldung nennt den Lastfaktor', /Lastfaktor 3\.0/.test(r.aus), r.aus.trim());
}
{
    const r = fall(0, "const h = hund(() => { console.log('ANGESCHLAGEN'); process.exit(7); }, 300);\n"
        + "clearTimeout(h);\nconst i = setInterval(() => console.log('Ausgabe'), 100);\n"
        + 'setTimeout(() => { clearInterval(i); process.exit(0); }, 1200);');
    // Zusage der LAUFZEITUMGEBUNG (refresh() nach clearTimeout ist wirkungslos),
    // keine eigene Logik - gemessen, damit ein Node-Wechsel sie nicht still bricht.
    pruefe('clearTimeout schaltet ab - spaetere Ausgabe weckt ihn nicht wieder',
           r.rc === 0 && !/ANGESCHLAGEN/.test(r.aus), 'rc=' + r.rc + ' ' + r.aus.slice(-200));
}
{
    const r = fall(0, "const h = hund(() => { console.log('ANGESCHLAGEN'); process.exit(7); }, 5000);\n"
        + "h.unref();\nprocess.on('exit', () => console.log('DAUER ' + (Date.now() - t0)));");
    pruefe('unref: der Hund haelt den Prozess nicht am Leben', r.rc === 0 && dauer(r.aus) < 3000,
           'rc=' + r.rc + ' ' + r.aus.trim());
}
{
    const r = fall(0, "const h = hund(() => { console.log('DAUER ' + (Date.now() - t0)); process.exit(7); }, 400);\n"
        + "Date.now = () => 0;\nsetInterval(() => {}, 1000);");
    pruefe('ersetzte Uhr (Date.now, virtuelle Zeit) reisst den Hund nicht mit',
           r.rc === 7, 'rc=' + r.rc + ' ' + r.aus.trim());
}
{
    const r = fall(0, "const h = hund(() => {}, 1000); console.log('TYP ' + (typeof h.refresh) + ' ' + (typeof h.unref));\n"
        + 'clearTimeout(h);');
    pruefe('Rueckgabe ist der Timer selbst (refresh/unref wie bei setTimeout)', /TYP function function/.test(r.aus), r.aus.trim());
}

// ═══ Teil B: Regel ══════════════════════════════════════════════════════
console.log('\nTeil B: kein fester Wecker >= 10 s auf oberster Ebene');

const acorn = require('./lib/acorn_laden')();
const OPT = { ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true, allowHashBang: true, locations: true };

function befunde(quelle) {
    const aus = [];
    const gehe = (n, tiefe) => {
        if (!n || typeof n.type !== 'string') return;
        if (tiefe === 0 && n.type === 'CallExpression' && n.callee.type === 'Identifier'
            && n.callee.name === 'setTimeout' && n.arguments.length >= 2
            && n.arguments[1].type === 'Literal' && typeof n.arguments[1].value === 'number'
            && n.arguments[1].value >= 10000) aus.push(n.loc.start.line);
        const t = tiefe + (/Function/.test(n.type) ? 1 : 0);
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach((c) => gehe(c, t));
            else if (v && typeof v.type === 'string') gehe(v, t);
        }
    };
    gehe(acorn.parse(quelle, OPT), 0);
    return aus;
}

// Positivkontrollen: jede Form schlaegt genau einmal an, die harmlosen nie.
const PROBEN = {
    'zugewiesen': 'const W = setTimeout(() => { process.exit(1); }, 25000);',
    'als Anweisung': "setTimeout(() => { console.log('haengt'); process.exit(1); }, 30000);",
    'mit .unref()': 'setTimeout(() => process.exit(2), 20000).unref();',
    'Funktionsausdruck': 'const w = setTimeout(function () { process.exit(1); }, 10000);',
};
const HARMLOS = "const W = require('./lib/wachhund')(() => process.exit(1), 25000);\n"
    + 'function warte() { return new Promise((r) => setTimeout(r, 20000)); }\n'
    + '(async () => { await new Promise((r) => setTimeout(r, 30000)); })();\n'
    + 'setTimeout(() => process.exit(0), 0);\nsetTimeout(weiter, 9999);\n'
    + "// setTimeout(() => {}, 25000) im Kommentar\nconst t = 'setTimeout(x, 25000)';\n";
for (const [titel, q] of Object.entries(PROBEN)) {
    const n = befunde(q).length;
    if (n !== 1) abbruch("Positivkontrolle '" + titel + "': " + n + ' statt 1 Befund');
}
if (befunde(HARMLOS).length) abbruch('Positivkontrolle harmlos: ' + befunde(HARMLOS));
pruefe('Erkennung: ' + Object.keys(PROBEN).length + ' Formen schlagen an, Ablauf/Kommentar/Text nicht', true);

const dateien = fs.readdirSync(__dirname).filter((n) => n.endsWith('.js')).map((n) => path.join(__dirname, n))
    .concat(fs.readdirSync(path.join(__dirname, 'lib')).filter((n) => n.endsWith('.js'))
        .map((n) => path.join(__dirname, 'lib', n)))
    .filter((p) => p !== HELFER);
// Positivkontrolle: der Bestand, an dem der Fehler gemessen wurde, ist dabei.
const namen = new Set(dateien.map((p) => path.relative(__dirname, p)));
for (const muss of ['test_dienst_neustart_ui.js', 'test_settings_suche_ui.js', 'test_bsi_m5_ui.js']) {
    if (!namen.has(muss)) abbruch('Geltungsbereich verfehlt: ' + muss);
}
const verstoesse = [], unlesbar = [];
let mitHund = 0;
for (const p of dateien) {
    const q = fs.readFileSync(p, 'utf8');
    if (/require\(\s*['"]\.\/lib\/wachhund['"]\s*\)/.test(q)) mitHund++;
    try {
        for (const z of befunde(q)) verstoesse.push(path.relative(ROOT, p) + ':' + z);
    } catch (e) {
        unlesbar.push(path.relative(ROOT, p) + ' (' + e.message + ')');
    }
}
pruefe(dateien.length + ' Dateien: kein fester Wecker >= 10 s auf oberster Ebene', !verstoesse.length,
       verstoesse.slice(0, 8).join(', '));
pruefe('alle Dateien am Syntaxbaum lesbar (sonst wuerde eine still uebersprungen)', !unlesbar.length,
       unlesbar.slice(0, 3).join('; '));
console.log('  (Helfer im Einsatz in ' + mitHund + ' Waechtern)');

console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
