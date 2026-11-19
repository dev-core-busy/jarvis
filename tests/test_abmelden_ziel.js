#!/usr/bin/env node
/**
 * Waechter: Jeder Abmelde-KNOPF meldet beim Server ab und fuehrt auf "/".
 *
 * WARUM (gemeldet 2026-11-18): nach dem Abmelden in /chat stand der Benutzer
 * auf der eigenen Maske von /chat – nur Benutzername und Kennwort, ohne
 * "Mit Firmenkonto anmelden". Portal und Kopfzeile fuehrten laengst auf "/";
 * /chat, /userchat, /support und der Sperrbildschirm wichen ab, /support
 * meldete beim Server nicht einmal ab (das Sitzungs-Cookie blieb gueltig).
 *
 * REGEL am Syntaxbaum (acorn), ueber ALLE Module in frontend/js – keine Liste:
 *   Ein Klick-Handler (addEventListener('click', …) oder .onclick = …) ist ein
 *   Abmelde-Handler, wenn er
 *     - JarvisSession.logout ruft (direkt oder ueber eine Funktion derselben
 *       Datei, die es tut), ODER
 *     - fetch('/api/logout', …) ruft, ODER
 *     - das Sitzungs-Token aus localStorage loescht (removeItem mit 'token' im
 *       Namen oder ueber TOKEN_KEYS / tokenSchluessel()).
 *   Die dritte Erkennung ist der Grund fuer diese Liste: /support, /claude,
 *   /sql und /tracks loeschten NUR das Token und hatten damit keinen
 *   JarvisSession-Aufruf, an dem man sie haette finden koennen.
 *   Er muss dann
 *     (a) beim Server abmelden (JarvisSession.logout / Abmelde-Funktion /
 *         fetch('/api/logout')),
 *     (b) auf "/" fuehren: location.replace('/') oder location.href = '/'
 *         (auch in einem .then darin),
 *     (c) KEIN location.reload() und kein anderes Ziel.
 *   Eine Abmelde-Funktion, die DIREKT als Handler uebergeben wird
 *   (addEventListener('click', logout)), verletzt (a) immer.
 *
 * Positivkontrolle: die Erkennung findet in den Dateien, in denen es die Faelle
 * nachweislich gibt, je einen Handler – direkt (kopfzeile.js) und ueber eine
 * Funktion (chat.js). Sonst Exit 2.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs'), path = require('path');
const acorn = require('./lib/acorn_laden')();
const WURZEL = path.resolve(__dirname, '..');
const JS = path.join(WURZEL, 'frontend/js');

// app.js laeuft unter "/" selbst: dort IST die Anmeldemaske das Ziel.
const AUSNAHMEN = { 'app.js': 'liefert die Anmeldung unter "/" selbst aus' };

let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}

function kinder(n, cb) {
    for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && cb(x));
        else if (v && typeof v.type === 'string' && k !== 'loc') cb(v);
    }
}
function laufe(n, cb) { cb(n); kinder(n, c => laufe(c, cb)); }
const istFn = n => /^(FunctionExpression|ArrowFunctionExpression|FunctionDeclaration)$/.test(n.type);
const name = (n) => n && (n.type === 'Identifier' ? n.name
    : n.type === 'MemberExpression' && !n.computed ? name(n.object) + '.' + n.property.name : '');
const istServerAbmeldung = c => c.type === 'CallExpression' && /(^|\.)JarvisSession\.logout$/.test(name(c.callee));
const istLocation = n => /^(window\.)?location$/.test(name(n));

function pruefeDatei(datei) {
    const src = fs.readFileSync(path.join(JS, datei), 'utf8');
    let baum;
    try { baum = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true }); }
    catch (e) { return { fehler: 'nicht parsebar: ' + e.message, handler: [] }; }

    // Funktionen dieser Datei, die beim Server abmelden (Name -> true).
    const abmelder = new Set();
    laufe(baum, n => {
        if (!istFn(n)) return;
        let direkt = false;
        laufe(n.body, c => { if (istServerAbmeldung(c)) direkt = true; });
        if (!direkt) return;
        if (n.type === 'FunctionDeclaration' && n.id) abmelder.add(n.id.name);
    });
    laufe(baum, n => {   // const logout = function () {...}
        if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.init && istFn(n.init)) {
            let d = false; laufe(n.init.body, c => { if (istServerAbmeldung(c)) d = true; });
            if (d) abmelder.add(n.id.name);
        }
    });

    const handler = [];
    function klickHandler(fn, wo) {
        if (fn.type === 'Identifier') {
            if (abmelder.has(fn.name)) handler.push({ wo, direktReferenz: fn.name });
            return;
        }
        if (!istFn(fn)) return;
        let server = false, token = false, ziel = false, falsch = [];
        laufe(fn.body, c => {
            if (istServerAbmeldung(c)) server = true;
            if (c.type === 'CallExpression' && c.callee.type === 'Identifier' && abmelder.has(c.callee.name)) server = true;
            if (c.type === 'CallExpression' && name(c.callee) === 'fetch' && c.arguments[0]
                && c.arguments[0].type === 'Literal' && c.arguments[0].value === '/api/logout') server = true;
            if (c.type === 'CallExpression' && /localStorage\.removeItem$/.test(name(c.callee)) && c.arguments[0]
                && c.arguments[0].type === 'Literal' && /token/i.test(String(c.arguments[0].value))) token = true;
            if (c.type === 'CallExpression' && c.callee.type === 'MemberExpression' && c.callee.property.name === 'forEach'
                && /TOKEN_KEYS|tokenSchluessel/.test(name(c.callee.object) || (c.callee.object.callee && name(c.callee.object.callee)) || '')) token = true;
            if (c.type === 'CallExpression' && c.callee.type === 'MemberExpression' && istLocation(c.callee.object)) {
                const m = c.callee.property.name;
                const a0 = c.arguments[0];
                if (m === 'replace' || m === 'assign') {
                    if (a0 && a0.type === 'Literal' && a0.value === '/') ziel = true;
                    else falsch.push('location.' + m + '(' + (a0 && a0.type === 'Literal' ? JSON.stringify(a0.value) : '…') + ')');
                }
                if (m === 'reload') falsch.push('location.reload()');
            }
            if (c.type === 'AssignmentExpression' && /^(window\.)?location(\.href)?$/.test(name(c.left))) {
                if (c.right.type === 'Literal' && c.right.value === '/') ziel = true;
                else falsch.push(name(c.left) + ' = ' + (c.right.type === 'Literal' ? JSON.stringify(c.right.value) : '…'));
            }
        });
        if (server || token) handler.push({ wo, server, ziel, falsch });
    }
    laufe(baum, n => {
        if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
            && n.callee.property.name === 'addEventListener'
            && n.arguments[0] && n.arguments[0].value === 'click' && n.arguments[1]) {
            klickHandler(n.arguments[1], datei + ':' + n.loc.start.line);
        }
        if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression'
            && n.left.property && n.left.property.name === 'onclick') {
            klickHandler(n.right, datei + ':' + n.loc.start.line);
        }
    });
    return { handler };
}

// acorn braucht loc fuer Zeilennummern
const _parse = acorn.parse;
acorn.parse = (s, o) => _parse(s, Object.assign({ locations: true }, o));

const dateien = fs.readdirSync(JS).filter(f => f.endsWith('.js')).sort();
const erg = {};
let parsefehler = [];
for (const d of dateien) {
    const r = pruefeDatei(d);
    if (r.fehler) parsefehler.push(d + ': ' + r.fehler);
    erg[d] = r.handler;
}

console.log('Positivkontrolle');
const findet = (d, art) => (erg[d] || []).some(h => art === 'direkt' ? h.ziel !== undefined : true);
if (!findet('kopfzeile.js', 'direkt') || !findet('chat.js') || !findet('portal_seite.js')) {
    console.log('ABBRUCH (Exit 2): Erkennung findet die bekannten Abmelde-Knoepfe nicht ('
        + ['kopfzeile.js', 'chat.js', 'portal_seite.js'].map(d => d + '=' + (erg[d] || []).length).join(', ') + ')');
    process.exit(2);
}
// chat.js geht ueber die Funktion logout() – das muss als Abmeldung erkannt werden.
check('Erkennung ueber eine Abmelde-Funktion derselben Datei (chat.js)', (erg['chat.js'] || []).length >= 1);
check('alle Module parsebar', parsefehler.length === 0, parsefehler.join(' | '));

console.log('Regel ueber ' + dateien.length + ' Module');
let gesamt = 0;
for (const d of dateien) {
    for (const h of erg[d]) {
        gesamt++;
        if (AUSNAHMEN[d]) { console.log('  · ' + h.wo + ' ausgenommen: ' + AUSNAHMEN[d]); continue; }
        if (h.direktReferenz) {
            check(h.wo + ': Abmelde-Knopf fuehrt auf "/"', false,
                  'Funktion "' + h.direktReferenz + '" direkt als Handler – kein Ziel');
            continue;
        }
        check(h.wo + ': Abmelde-Knopf meldet beim Server ab', h.server,
              'nur lokales Token geloescht – das Sitzungs-Cookie bliebe gueltig');
        check(h.wo + ': Abmelde-Knopf fuehrt auf "/"', h.ziel && h.falsch.length === 0,
              (!h.ziel ? 'kein Ziel "/"' : '') + (h.falsch.length ? ' ' + h.falsch.join(', ') : ''));
    }
}
check('Abmelde-Knoepfe gefunden (' + gesamt + ')', gesamt >= 3);

console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
