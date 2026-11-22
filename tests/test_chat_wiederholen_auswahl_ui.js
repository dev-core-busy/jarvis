#!/usr/bin/env node
/* Waechter (Vorfall ECHT 2026-11-06, gemeldet 2026-11-15): "Wiederholen" und
 * "Bearbeiten" im Chat verloren die Wissensgruppen-Auswahl.
 *
 * DER FEHLER: sendMessage haengte kb_groups/sql_schemata an den Auftrag,
 * _submitEdit (Bearbeiten UND Wiederholen ↻) baute seinen Rahmen selbst und
 * liess beide weg. Das Backend liest ein FEHLENDES kb_groups als "alle Gruppen"
 * – auf ECHT lieferte knowledge_search danach ein Dokument aus einer Gruppe,
 * die in der Sitzung abgewaehlt war (Datei nur dieser Gruppe zugeordnet,
 * gespeicherte Auswahl ohne sie; derselbe Auftrag lief fuenfmal, im Verlauf
 * stand er einmal – das Muster von "Wiederholen").
 *
 * Gemessen am ECHTEN chat.html + chat.js + kbgroupfilter.js (mit sitzung.js,
 * i18n.js, icons.js, chatlib.js) in jsdom; WebSocket und fetch sind Attrappen.
 *   1. Positivkontrolle: Filter montiert, Gruppen geladen, Abwahl wirkt,
 *      der NORMALE Sendeweg traegt kb_groups (sonst ist 2 trivial).
 *   2. Klick auf ↻ sendet einen Auftrag mit DERSELBEN kb_groups-Auswahl und
 *      dem Kuerzungs-Hinweis (es ist wirklich der Wiederholen-Weg).
 *   3. "Alle gewaehlt" laesst das Feld auch beim Wiederholen weg (null = alle).
 *   4. Regel (acorn): JEDES Objekt `{type: 'task', …}` in chat.js geht durch
 *      _auswahlMitgeben – direkt als Argument oder ueber eine Variable, die in
 *      derselben Funktion durchgereicht wird. Faengt auch einen KUENFTIGEN
 *      dritten Sendeweg.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 * Lauf:  timeout 60 node tests/test_chat_wiederholen_auswahl_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/chat.html');
const SITZUNG = lies('frontend/js/sitzung.js');
const CHAT_QUELLE = lies('frontend/js/chat.js');
const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/chatlib.js',
    'frontend/js/kbgroupfilter.js'].map(lies).concat([CHAT_QUELLE]);

let OK = 0, FAIL = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) OK++; else FAIL++;
    console.log((cond ? '  ✓ ' : '  ✗ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Wachhund: eine geladene Seite haelt eigene Takte; ohne ihn haengt ein Wurf.
const WACHHUND = require('./lib/wachhund')(() => { check('Lauf endet innerhalb von 40 s', false); bilanz(); process.exit(1); }, 40000);

const GRUPPEN = [
    { id: 'g-eins', name: 'Eins', color: '#336699' },
    { id: 'g-zwei', name: 'Zwei', color: '#996633' },
];

function fenster() {
    const dom = new JSDOM(HTML, { url: 'https://localhost/chat', runScripts: 'outside-only' });
    const w = dom.window;
    const util = require('util');
    if (typeof w.TextDecoder === 'undefined') w.TextDecoder = util.TextDecoder;
    if (typeof w.TextEncoder === 'undefined') w.TextEncoder = util.TextEncoder;
    if (typeof w.matchMedia === 'undefined') {
        w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
    }
    w.scrollTo = () => {};
    w.Element.prototype.scrollIntoView = function () {};
    w.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
    w.cancelAnimationFrame = (id) => clearTimeout(id);
    w.alert = () => {};
    w.confirm = () => true;

    const sockets = [];
    function FakeWS(url) {
        this.url = url;
        this.readyState = 1;
        this.gesendet = [];
        sockets.push(this);
    }
    FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
    FakeWS.prototype.send = function (s) { this.gesendet.push(JSON.parse(s)); };
    FakeWS.prototype.close = function () { this.readyState = 3; };
    w.WebSocket = FakeWS;
    w.__sockets = sockets;

    w.fetch = function (url) {
        const u = String(url).split('?')[0];
        let body = {};
        if (u === '/api/chat/sessions') body = { sessions: [{ id: 's1', title: 'Test' }] };
        if (u === '/api/me') body = { username: 'jarvis', is_admin: false, permissions: {} };
        if (u === '/api/knowledge/groups') body = { groups: GRUPPEN };
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(body),
            text: () => Promise.resolve(JSON.stringify(body)),
        });
    };
    w.localStorage.setItem('jarvis_token', 'testtoken');
    w.localStorage.setItem('jarvis_chat_token', 'testtoken');
    for (const src of MODULE) { w.eval(SITZUNG); w.eval(src); }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { dom, w };
}

function aufgaben(w) {
    const out = [];
    for (const s of w.__sockets) for (const m of s.gesendet) if (m && m.type === 'task') out.push(m);
    return out;
}

/* Setzt die Gruppen-Auswahl ueber den ECHTEN Bedienweg (Panel oeffnen,
 * Kaestchen umschalten, change feuern) – nicht ueber localStorage. */
function waehle(w, an) {
    const d = w.document;
    const btn = d.querySelector('.kbgf-btn');
    if (!btn) return false;
    if (btn.getAttribute('aria-expanded') !== 'true') btn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    const boxen = Array.from(d.querySelectorAll('.kbgf-panel input[type=checkbox]'));
    if (!boxen.length) return false;
    for (const cb of boxen) {
        const soll = an.indexOf(cb.value) >= 0;
        if (cb.checked !== soll) { cb.checked = soll; cb.dispatchEvent(new w.Event('change', { bubbles: true })); }
    }
    d.body.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));   // Panel schliessen
    return true;
}

function senden(w, text) {
    const d = w.document;
    const inp = d.getElementById('msg-input');
    inp.value = text;
    inp.dispatchEvent(new w.Event('input', { bubbles: true }));
    const b = d.getElementById('btn-send');
    b.disabled = false;
    b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
}

function wiederholen(w) {
    const knoepfe = w.document.querySelectorAll('.msg-row.user .msg-retry-btn');
    const k = knoepfe[knoepfe.length - 1];
    if (!k) return false;
    k.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    return true;
}

function gleicheMenge(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    const s = new Set(a);
    return b.every((x) => s.has(x));
}

/* Regel 4 am Syntaxbaum: Objekt-Literale mit type: 'task'. */
function regelPruefen(quelle) {
    const ast = acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: 'script' });
    const funde = [];   // { ok, zeile, wie }
    function istTask(o) {
        return o && o.type === 'ObjectExpression' && o.properties.some((p) =>
            p.type === 'Property' && !p.computed &&
            ((p.key.type === 'Identifier' && p.key.name === 'type') || (p.key.type === 'Literal' && p.key.value === 'type')) &&
            p.value.type === 'Literal' && p.value.value === 'task');
    }
    function istMitgeben(n) {
        return n && n.type === 'CallExpression' && n.callee.type === 'Identifier' && n.callee.name === '_auswahlMitgeben';
    }
    // Alle _auswahlMitgeben(<Identifier>)-Aufrufe je umschliessender Funktion.
    function sammleDurchgereicht(fn) {
        const namen = new Set();
        (function lauf(n) {
            if (!n || typeof n.type !== 'string') return;
            if (n !== fn && /Function/.test(n.type)) return;   // nicht in innere Funktionen
            if (istMitgeben(n) && n.arguments[0] && n.arguments[0].type === 'Identifier') namen.add(n.arguments[0].name);
            for (const k of Object.keys(n)) {
                const v = n[k];
                if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v);
            }
        })(fn.body);
        return namen;
    }
    (function lauf(n, eltern, fnStapel) {
        if (!n || typeof n.type !== 'string') return;
        const istFn = /Function/.test(n.type);
        const stapel = istFn ? fnStapel.concat([n]) : fnStapel;
        if (istTask(n)) {
            const zeile = quelle.slice(0, n.start).split('\n').length;
            const e = eltern[eltern.length - 1];
            if (istMitgeben(e) && e.arguments[0] === n) funde.push({ ok: true, zeile, wie: 'direkt' });
            else if (e && e.type === 'VariableDeclarator' && e.id.type === 'Identifier' && e.init === n) {
                const fn = stapel[stapel.length - 1];
                const ok = !!fn && sammleDurchgereicht(fn).has(e.id.name);
                funde.push({ ok, zeile, wie: 'Variable ' + e.id.name });
            } else funde.push({ ok: false, zeile, wie: e ? e.type : '?' });
        }
        const neu = eltern.concat([n]);
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach((c) => lauf(c, neu, stapel));
            else if (v && typeof v.type === 'string') lauf(v, neu, stapel);
        }
    })(ast, [], []);
    return funde;
}

async function main() {
    const { w } = fenster();
    await sleep(250);

    section('1) Positivkontrolle: Messaufbau');
    check('chat.js hat eine Verbindung aufgebaut', w.__sockets.length >= 1, String(w.__sockets.length));
    check('der Wissensgruppen-Filter ist montiert', !!w.document.querySelector('.kbgf-btn'));
    const gewaehlt = waehle(w, ['g-eins']);
    check('die Gruppen sind geladen und abwaehlbar', gewaehlt);
    senden(w, 'Wie funktioniert die Benutzerverwaltung?');
    await sleep(50);
    const normal = aufgaben(w);
    const n0 = normal[normal.length - 1];
    check('der normale Sendeweg schickt einen Auftrag', !!n0, String(normal.length));
    check('… und der traegt die Auswahl (nur g-eins)', !!n0 && gleicheMenge(n0.kb_groups, ['g-eins']),
        n0 ? JSON.stringify(n0.kb_groups) : 'kein Auftrag');
    check('die Frage steht als Benutzer-Sprechblase mit ↻ da',
        !!w.document.querySelector('.msg-row.user .msg-retry-btn'));
    if (FAIL) { bilanz(); w.close(); process.exit(2); }

    section('2) Wiederholen (↻) behaelt die Wissensgruppen-Auswahl');
    const vorher = aufgaben(w).length;
    check('der Klick auf ↻ ist moeglich', wiederholen(w));
    await sleep(50);
    const nach = aufgaben(w);
    const r = nach.length > vorher ? nach[nach.length - 1] : null;
    check('der Klick sendet genau einen weiteren Auftrag', nach.length === vorher + 1, vorher + ' -> ' + nach.length);
    check('es ist der Wiederholen-Weg (traegt den Kuerzungs-Hinweis)',
        !!r && Object.prototype.hasOwnProperty.call(r, 'truncate_user_msg_index'), r ? Object.keys(r).join(',') : '-');
    check('der wiederholte Auftrag traegt kb_groups', !!r && Array.isArray(r.kb_groups),
        r ? JSON.stringify(r.kb_groups) : '-');
    check('… und zwar DIESELBE Auswahl (nur g-eins)', !!r && gleicheMenge(r.kb_groups, ['g-eins']),
        r ? JSON.stringify(r.kb_groups) : '-');
    check('der Text ist unveraendert', !!r && r.text === 'Wie funktioniert die Benutzerverwaltung?');

    section('3) "Alle gewaehlt" bleibt beim Wiederholen "alle"');
    waehle(w, ['g-eins', 'g-zwei', 'ungrouped']);
    const v3 = aufgaben(w).length;
    wiederholen(w);
    await sleep(50);
    const a3 = aufgaben(w);
    const r3 = a3.length > v3 ? a3[a3.length - 1] : null;
    check('ein weiterer Auftrag ging hinaus', !!r3, v3 + ' -> ' + a3.length);
    // AUSDRUECKLICH null, nicht weggelassen: ein fehlendes Feld liest das
    // Backend als "gespeicherte Auswahl der Sitzung" (test_kb_auswahl_rueckfall).
    check('kb_groups ist ausdruecklich null (= alle, kein Filter)',
        !!r3 && Object.prototype.hasOwnProperty.call(r3, 'kb_groups') && r3.kb_groups === null,
        r3 ? JSON.stringify(r3) : '-');
    waehle(w, []);
    const v3b = aufgaben(w).length;
    wiederholen(w);
    await sleep(50);
    const a3b = aufgaben(w);
    const r3b = a3b.length > v3b ? a3b[a3b.length - 1] : null;
    check('"keine gewaehlt" wird als leere Liste wiederholt (kein Wissen)',
        !!r3b && Array.isArray(r3b.kb_groups) && r3b.kb_groups.length === 0, r3b ? JSON.stringify(r3b.kb_groups) : '-');

    section('4) Regel: jeder Auftrag in chat.js geht durch _auswahlMitgeben');
    const funde = regelPruefen(CHAT_QUELLE);
    check('Positivkontrolle: mindestens zwei Auftrags-Objekte gefunden (Senden + Wiederholen)',
        funde.length >= 2, String(funde.length));
    const schlecht = funde.filter((f) => !f.ok);
    check('kein Auftrag umgeht die Auswahl', schlecht.length === 0,
        schlecht.map((f) => 'Zeile ' + f.zeile + ' (' + f.wie + ')').join('; '));
    // Positivkontrolle der Regel: ein Auftrag ohne Helfer MUSS auffallen.
    const probe = regelPruefen("function f(){ wsSend({ type: 'task', text: 'x' }); }\n" +
        "function g(){ const m = { type: 'task' }; _auswahlMitgeben(m); wsSend(m); }\n" +
        "function h(){ const m = { type: 'task' }; wsSend(m); }");
    check('Positivkontrolle der Regel: Umgehung (direkt und ueber Variable) wird erkannt, Durchreichen nicht',
        probe.length === 3 && !probe[0].ok && probe[1].ok && !probe[2].ok, JSON.stringify(probe));

    clearTimeout(WACHHUND);
    bilanz();
    w.close();
    process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
