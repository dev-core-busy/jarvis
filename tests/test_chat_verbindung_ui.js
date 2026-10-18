#!/usr/bin/env node
/* Waechter (Code-Review 2026-10-18, /chat): Wiederverbinden und Abmelden.
 *
 * Zusagen, gemessen am ECHTEN chat.html + chat.js (mit sitzung.js, i18n.js,
 * icons.js, chatlib.js) in jsdom, WebSocket und fetch als Attrappen:
 *   1. Der Reconnect gibt NICHT auf (frueher: Schluss nach 20 Versuchen) –
 *      auch Versuch 25 wird noch geplant.
 *   2. Die Wartezeit waechst exponentiell, ist gedeckelt (30 s) und streut
 *      (Jitter), damit nicht alle Fenster im selben Takt anklopfen.
 *   3. Der Zustand ist fuer den Benutzer sichtbar (Hinweis ueber der Eingabe)
 *      und verschwindet, sobald die Verbindung steht; danach beginnt die
 *      Wartezeit wieder klein.
 *   4. Abmelden haelt die Takte dieses Moduls an (LLM-Status 30 s,
 *      Kontext-Anzeige 8 s) und verbindet NICHT wieder.
 *   5. Erneutes Anmelden ohne Neuladen legt keinen zweiten Kontext-Takt an
 *      (derselbe Endpunkt wurde sonst doppelt abgefragt).
 *   6. Regel: die Feedback-Symbole tragen keine fest eingetragene Farbe.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 * Lauf:  timeout 60 node tests/test_chat_verbindung_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/chat.html');
const SITZUNG = lies('frontend/js/sitzung.js');
const I18N = lies('frontend/js/i18n.js');
const ICONS = lies('frontend/js/icons.js');
const CHATLIB = lies('frontend/js/chatlib.js');
const CHAT = lies('frontend/js/chat.js');

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
    w.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
    w.cancelAnimationFrame = (id) => clearTimeout(id);

    // Takt-Buchhaltung: welche Intervalle (mit welcher Periode) sind aktiv,
    // und welche Timeouts wurden waehrend eines bestimmten Aufrufs geplant.
    const echtSI = w.setInterval.bind(w), echtCI = w.clearInterval.bind(w);
    const echtST = w.setTimeout.bind(w), echtCT = w.clearTimeout.bind(w);
    w.__iv = new Map();
    w.setInterval = function (fn, ms) {
        const id = echtSI(fn, ms);
        w.__iv.set(id, ms);
        return id;
    };
    w.clearInterval = function (id) { w.__iv.delete(id); return echtCI(id); };
    w.__mitschnitt = null;
    w.setTimeout = function (fn, ms) {
        // Mitgeschnittene Timeouts laufen NICHT von selbst – der Test loest sie aus.
        if (w.__mitschnitt) {
            const e = { fn, ms: ms || 0 };
            w.__mitschnitt.push(e);
            return 900000 + w.__mitschnitt.length;
        }
        return echtST(fn, ms);
    };
    w.clearTimeout = function (id) { return echtCT(id); };

    const sockets = [];
    function FakeWS(url) {
        this.url = url;
        this.readyState = 1;
        this.gesendet = [];
        sockets.push(this);
        FakeWS.letzter = this;
    }
    FakeWS.prototype.send = function (s) { this.gesendet.push(s); };
    // Wie der Browser: close() meldet sich ASYNCHRON ueber onclose.
    FakeWS.prototype.close = function () {
        this.readyState = 3;
        const f = this.onclose, self = this;
        if (f) echtST(() => f.call(self), 0);
    };
    w.WebSocket = FakeWS;
    w.__sockets = sockets;

    w.__fetches = [];
    w.fetch = function (url) {
        const u = String(url);
        w.__fetches.push(u);
        let body = {};
        if (/\/api\/chat\/sessions/.test(u)) body = { sessions: [{ id: 's1', title: 'Test' }] };
        if (/\/api\/me/.test(u)) body = { username: 'jarvis', is_admin: false, permissions: {} };
        if (/\/api\/login/.test(u)) body = { success: true, token: 'zweitertoken', username: 'jarvis' };
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(body),
            text: () => Promise.resolve(JSON.stringify(body)),
        });
    };
    w.localStorage.setItem('jarvis_token', 'testtoken');
    w.localStorage.setItem('jarvis_chat_token', 'testtoken');
    w.alert = () => {};
    w.confirm = () => true;
    for (const src of [I18N, ICONS, CHATLIB, CHAT]) {
        w.eval(SITZUNG);
        w.eval(src);
    }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { dom, w, FakeWS };
}

/* Schliesst den aktuellen Socket und liefert den dabei geplanten
 * Reconnect-Termin (Timeout >= 400 ms) oder null. */
function schliessen(w) {
    const s = w.__sockets[w.__sockets.length - 1];
    s.readyState = 3;
    w.__mitschnitt = [];
    let geplant;
    try { if (s.onclose) s.onclose(); } finally {
        geplant = w.__mitschnitt;
        w.__mitschnitt = null;
    }
    const rc = geplant.filter((e) => e.ms >= 400);
    return rc.length ? rc[rc.length - 1] : null;
}

function hinweis(w) {
    const el = w.document.getElementById('chat-conn-hint');
    return { da: !!el && !el.hidden, text: el ? el.textContent : '' };
}

async function main() {
    section('1) Positivkontrolle: Messaufbau');
    const { dom, w } = fenster();
    await sleep(150);
    check('chat.js ist angelaufen und hat verbunden', w.__sockets.length >= 1, String(w.__sockets.length));
    const ersterRC = w.__sockets.length ? schliessen(w) : null;
    check('ein Verbindungsabbruch plant einen Reconnect (Mitschnitt greift)', !!ersterRC);
    if (FAIL) { bilanz(); w.close(); process.exit(2); }

    section('2) Unbegrenzt, exponentiell, gedeckelt, mit Jitter');
    const delays = [ersterRC.ms];
    let termin = ersterRC;
    let weiter = true;
    for (let n = 2; n <= 25; n++) {
        const vorher = w.__sockets.length;
        termin.fn();   // Termin ausloesen -> connectWS
        if (w.__sockets.length !== vorher + 1) { weiter = false; check('Versuch ' + (n - 1) + ' baut eine neue Verbindung auf', false); break; }
        const t = schliessen(w);
        if (!t) { weiter = false; check('Versuch ' + n + ' wird noch geplant (kein Aufgeben)', false, 'nach ' + (n - 1) + ' Versuchen Schluss'); break; }
        delays.push(t.ms);
        termin = t;
    }
    if (weiter) check('auch Versuch 25 wird noch geplant (frueher Schluss nach 20)', delays.length === 25, String(delays.length));
    const soll = (n) => Math.min(30000, 1000 * Math.pow(2, n - 1));
    const imBand = delays.every((d, i) => d >= 0.5 * soll(i + 1) - 1 && d <= soll(i + 1) + 1);
    check('jede Wartezeit liegt im Band [50 %, 100 %] von min(30 s, 1 s·2^(n-1))', imBand,
        delays.map((d, i) => (i + 1) + ':' + d).join(' '));
    check('keine Wartezeit ueber 30 s', delays.every((d) => d <= 30000), String(Math.max(...delays)));
    check('die Wartezeit waechst (Versuch 6 > Versuch 1)', delays.length >= 6 && delays[5] > delays[0],
        delays.slice(0, 6).join(','));
    const gedeckelt = delays.slice(6);
    check('Jitter: die gedeckelten Wartezeiten sind nicht alle gleich',
        gedeckelt.length > 2 && new Set(gedeckelt).size > 1, gedeckelt.join(','));

    section('3) Sichtbarer Zustand');
    const h = hinweis(w);
    check('ein Hinweis steht ueber der Eingabe', h.da, JSON.stringify(h));
    check('der Hinweis nennt den Versuch', /25/.test(h.text), h.text);
    check('der Hinweis ist uebersetzt (i18n-Schluessel vorhanden)',
        w.t('chat.conn_retry') !== 'chat.conn_retry');
    termin.fn();
    const neu = w.__sockets[w.__sockets.length - 1];
    if (neu.onopen) neu.onopen();
    check('nach dem Verbinden ist der Hinweis weg', !hinweis(w).da, JSON.stringify(hinweis(w)));
    const nachOpen = schliessen(w);
    check('nach erfolgreichem Verbinden beginnt die Wartezeit wieder klein (<= 1 s)',
        !!nachOpen && nachOpen.ms <= 1000, nachOpen ? String(nachOpen.ms) : 'kein Termin');
    nachOpen.fn();
    const s2 = w.__sockets[w.__sockets.length - 1];
    if (s2.onopen) s2.onopen();

    section('4) Abmelden stoppt die Takte');
    const perioden = () => [...w.__iv.values()];
    check('Vorbedingung: LLM-Status-Takt (30 s) laeuft', perioden().includes(30000), perioden().join(','));
    check('Vorbedingung: Kontext-Takt (8 s) laeuft', perioden().includes(8000), perioden().join(','));
    const socketsVorher = w.__sockets.length;
    w.document.getElementById('btn-logout').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(60);   // asynchrones onclose der Attrappe abwarten
    check('LLM-Status-Takt ist nach dem Abmelden angehalten', !perioden().includes(30000), perioden().join(','));
    check('Kontext-Takt ist nach dem Abmelden angehalten', !perioden().includes(8000), perioden().join(','));
    check('nach dem Abmelden wird nicht wieder verbunden', w.__sockets.length === socketsVorher,
        socketsVorher + ' -> ' + w.__sockets.length);
    check('kein Verbindungshinweis nach dem Abmelden', !hinweis(w).da, JSON.stringify(hinweis(w)));
    // Auch ein spaeter (fremd ausgeloester) Abbruch plant nichts mehr.
    const spaet = schliessen(w);
    check('ein Abbruch nach dem Abmelden plant keinen Reconnect', !spaet, spaet ? String(spaet.ms) : '');

    section('5) Erneut anmelden ohne Neuladen');
    w.document.getElementById('login-user').value = 'jarvis';
    w.document.getElementById('login-pass').value = 'x';
    w.document.getElementById('login-form').dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
    await sleep(150);
    const acht = perioden().filter((p) => p === 8000).length;
    const dreissig = perioden().filter((p) => p === 30000).length;
    check('genau EIN Kontext-Takt nach erneuter Anmeldung', acht === 1, String(acht));
    check('genau EIN LLM-Status-Takt nach erneuter Anmeldung', dreissig === 1, String(dreissig));
    check('nach erneuter Anmeldung wird wieder verbunden', w.__sockets.length > socketsVorher,
        socketsVorher + ' -> ' + w.__sockets.length);

    section('6) Regel: Feedback-Symbole ohne feste Farbe');
    const svgs = CHAT.match(/const SVG_(UP|DOWN|X)\s*=\s*`[^`]*`/g) || [];
    check('drei Feedback-Symbole gefunden (Positivkontrolle der Regel)', svgs.length === 3, String(svgs.length));
    check('keines traegt fill="#…"', svgs.every((s) => !/fill="#/.test(s)));

    bilanz();
    dom.window.close();
    process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
