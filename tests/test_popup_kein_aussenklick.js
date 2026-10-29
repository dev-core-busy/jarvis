#!/usr/bin/env node
/**
 * Waechter: kein Popup schliesst sich bei einem Klick auf den grauen
 * Hintergrund daneben.
 *
 * Gemeldet 2026-10-29 („in ALLEN Popup-Fenstern fuehrt ein Mausklick in den
 * grauen Randbereich zum Schliessen – SEHR NERVIG"): wer beim Markieren oder
 * Scrollen einen Pixel neben der Karte loslaesst, verliert das Fenster samt
 * Eingaben. 39 Stellen in 23 Dateien trugen dasselbe Muster
 * `overlay.addEventListener('click', e => { if (e.target === overlay) zu(); })`.
 * Geschlossen wird seitdem nur noch ueber × / Schliessen-Knopf / Escape.
 *
 * Gemessen wird die EIGENSCHAFT am Syntaxbaum (acorn), nicht eine Liste von
 * Dateien oder Namen: ein Klick-Zuhoerer (click/mousedown/mouseup/
 * pointerdown/pointerup – per addEventListener, per `.onclick = …` oder als
 * Eintrag der KLICK-Tabelle in settings_bedienung.js) vergleicht
 * `<ereignis>.target` mit einem ELEMENT (nicht mit einer Zeichenkette). Genau
 * dieser Vergleich ist die Frage „wurde die Flaeche selbst getroffen?" – also
 * der Hintergrund.
 *
 * Bewusst NICHT erfasst:
 *  - `!x.contains(e.target)` an Ausklapp-Listen und Menues (Verlauf, Gruppen-
 *    filter, Emoji-Auswahl): das sind keine Popup-Fenster mit grauem Rand,
 *    sondern Aufklapper ohne eigenen Schliessen-Knopf.
 *  - `dragleave`/`dragover` (Ablagemarkierung, kein Schliessen).
 *  - Inline-<script> in HTML: die CSP (`script-src 'self'`, BSI H4) laesst
 *    keine zu, Zuhoerer stehen ausschliesslich in Dateien.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
require('./lib/bilanz')();
const fs = require('fs'), path = require('path');
const acorn = require('./lib/acorn_laden')();
const REPO = path.resolve(__dirname, '..');

let OK = 0, FAIL = 0;
const check = (n, b, info) => {
    console.log((b ? '  OK   ' : '  FAIL ') + n + (b || !info ? '' : '  → ' + info));
    b ? OK++ : FAIL++;
};

const KLICK_EREIGNISSE = new Set(['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup']);
const KLICK_EIGENSCHAFTEN = new Set(['onclick', 'onmousedown', 'onmouseup', 'onpointerdown', 'onpointerup']);

function kinder(n) {
    const o = [];
    for (const k in n) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && o.push(x));
        else if (v && typeof v.type === 'string') o.push(v);
    }
    return o;
}
function walk(n, f) { f(n); kinder(n).forEach(k => walk(k, f)); }
const istFunktion = n => n && /^(FunctionExpression|ArrowFunctionExpression)$/.test(n.type);

/** Alle Funktionen, die als Klick-Zuhoerer gebunden werden. */
function klickZuhoerer(ast) {
    const fns = [];
    walk(ast, n => {
        // x.addEventListener('click', function (e) {...})
        if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
            && n.callee.property && n.callee.property.name === 'addEventListener'
            && n.arguments.length >= 2 && n.arguments[0].type === 'Literal'
            && KLICK_EREIGNISSE.has(n.arguments[0].value) && istFunktion(n.arguments[1])) {
            fns.push(n.arguments[1]);
        }
        // x.onclick = function (e) {...}
        if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression'
            && n.left.property && KLICK_EIGENSCHAFTEN.has(n.left.property.name)
            && istFunktion(n.right)) {
            fns.push(n.right);
        }
        // var KLICK = { 'name': function (event) {...} } – settings_bedienung.js
        // bindet jeden Eintrag als el.onclick.
        if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === 'KLICK'
            && n.init && n.init.type === 'ObjectExpression') {
            n.init.properties.forEach(p => { if (p.value && istFunktion(p.value)) fns.push(p.value); });
        }
    });
    return fns;
}

const istTarget = (n, param) => n && n.type === 'MemberExpression' && !n.computed
    && n.property.name === 'target' && n.object.type === 'Identifier'
    && (n.object.name === param || n.object.name === 'event');
const istZeichenkette = n => n && (n.type === 'Literal' || n.type === 'TemplateLiteral');

/** Fundstellen „<ereignis>.target === <Element>" in Klick-Zuhoerern. */
function befunde(quelle) {
    const ast = acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: 'script', locations: true });
    const out = [];
    for (const fn of klickZuhoerer(ast)) {
        const p0 = fn.params[0];
        const param = p0 && p0.type === 'Identifier' ? p0.name : null;
        // Aufklapper-Muster `!liste.contains(e.target) && e.target !== knopf`:
        // der Vergleich nimmt dort nur den OEFFNENDEN Knopf aus, er fragt nicht
        // nach einer Hintergrundflaeche. Alles unter einem solchen Ausdruck
        // bleibt aussen vor.
        const aufklapper = new Set();
        walk(fn.body, n => {
            if (n.type !== 'LogicalExpression') return;
            let mitContains = false;
            walk(n, m => {
                if (m.type === 'CallExpression' && m.callee.type === 'MemberExpression'
                    && m.callee.property && m.callee.property.name === 'contains'
                    && m.arguments.some(x => istTarget(x, param))) mitContains = true;
            });
            if (mitContains) walk(n, m => aufklapper.add(m));
        });
        walk(fn.body, n => {
            if (aufklapper.has(n)) return;
            if (n.type !== 'BinaryExpression' || !/^[!=]==?$/.test(n.operator)) return;
            const [a, b] = istTarget(n.left, param) ? [n.left, n.right]
                         : istTarget(n.right, param) ? [n.right, n.left] : [null, null];
            if (a && !istZeichenkette(b)) out.push(n.loc.start.line);
        });
    }
    return out;
}

// ─── Positivkontrolle: erkennt die Sonde jede Form – und NUR sie? ────────────
console.log('Positivkontrolle der Sonde');
const FORMEN = [
    ["addEventListener + e.target === el", "o.addEventListener('click', function (e) { if (e.target === o) zu(); });"],
    ["Pfeilfunktion + mousedown", "o.addEventListener('mousedown', e => { if (e.target === o) zu(); });"],
    ["e.target === this", "o.addEventListener('click', function (e) { if (e.target === this) zu(); });"],
    ["onclick-Zuweisung", "box.onclick = function (e) { if (e.target === box) zu(); };"],
    ["Umkehrung !==", "o.addEventListener('click', function (ev) { if (ev.target !== o) return; zu(); });"],
    ["Vergleich mit getElementById", "o.addEventListener('click', e => { if (e.target === document.getElementById('x')) zu(); });"],
    ["KLICK-Tabelle", "var KLICK = { 'a-hintergrund': function (event) { if (event.target === this) zu(); } };"],
];
const HARMLOS = [
    ["dragleave", "p.addEventListener('dragleave', function (e) { if (e.target === p) p.x(); });"],
    ["Vergleich mit Zeichenkette", "o.addEventListener('click', function (e) { if (e.target === 'jira') x(); });"],
    ["contains (Aufklapper)", "document.addEventListener('click', function (e) { if (!w.contains(e.target)) zu(); });"],
    ["kein Klick-Zuhoerer", "function f(e) { if (e.target === o) zu(); }"],
    ["Aufklapper mit Knopf-Ausnahme", "document.addEventListener('click', e => { if (!box.contains(e.target) && e.target !== btn) zu(); });"],
];
let sondeOk = true;
for (const [name, src] of FORMEN) {
    const n = befunde(src).length;
    if (n !== 1) { sondeOk = false; console.log('  SONDE BLIND: ' + name + ' (' + n + ' Treffer)'); }
}
for (const [name, src] of HARMLOS) {
    const n = befunde(src).length;
    if (n !== 0) { sondeOk = false; console.log('  SONDE FEHLALARM: ' + name + ' (' + n + ' Treffer)'); }
}
if (!sondeOk) {
    console.log('ABBRUCH: die Sonde misst nicht, was sie soll – Exit 2.');
    process.exit(2);
}
console.log('  ' + FORMEN.length + ' Formen erkannt, ' + HARMLOS.length + ' harmlose nicht');

// ─── Regel ueber alle ausgelieferten Frontend-Skripte ───────────────────────
function jsDateien(wurzel) {
    const o = [];
    for (const e of fs.readdirSync(wurzel, { withFileTypes: true })) {
        const p = path.join(wurzel, e.name);
        if (e.isDirectory()) { if (e.name !== 'vendor' && e.name !== 'node_modules') o.push(...jsDateien(p)); }
        else if (e.name.endsWith('.js')) o.push(p);
    }
    return o;
}
const dateien = jsDateien(path.join(REPO, 'frontend'));
const rel = f => path.relative(REPO, f);
// Wurzeln, in denen das Muster nachweislich stand – fehlen sie, ist der
// Geltungsbereich verrutscht und die Regel waere dort still blind.
const MUSS = ['frontend/js/syspackages.js', 'frontend/js/settings_bedienung.js',
              'frontend/addin/addin.js', 'frontend/excel-addin/excel.js'];
const fehlt = MUSS.filter(m => !dateien.some(f => rel(f) === m));
if (fehlt.length) {
    console.log('ABBRUCH: Geltungsbereich unvollstaendig, fehlt: ' + fehlt.join(', '));
    process.exit(2);
}

console.log('\nRegel: kein Klick-Zuhoerer schliesst ueber „target === Flaeche" (' + dateien.length + ' Dateien)');
let parseFehler = 0;
for (const f of dateien) {
    let treffer;
    try { treffer = befunde(fs.readFileSync(f, 'utf8')); }
    catch (e) { parseFehler++; console.log('  nicht lesbar: ' + rel(f) + ' – ' + e.message); continue; }
    check(rel(f), treffer.length === 0, 'Zeile ' + treffer.join(', '));
}
if (parseFehler) {
    console.log('ABBRUCH: ' + parseFehler + ' Datei(en) nicht parsebar – Aussage unvollstaendig.');
    process.exit(2);
}

// settings.html: die Hintergrund-Eintraege der KLICK-Tabelle sind weg – ein
// verwaistes data-klick="…-hintergrund" waere die Einladung, sie zurueckzuholen.
const html = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const verwaist = html.match(/data-klick="[^"]*-hintergrund"/g) || [];
check('settings.html traegt kein data-klick="…-hintergrund" mehr', verwaist.length === 0, verwaist.join(', '));

console.log('\n' + OK + ' OK, ' + FAIL + ' FAIL');
process.exit(FAIL ? 1 : 0);
