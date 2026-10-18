#!/usr/bin/env node
/* Waechter (Code-Review 2026-10-18, /userchat): Senden ohne Verlust und
 * Daten des Gegenuebers nie als HTML.
 *
 * Gemessen am ECHTEN userchat.html + userchat.js (mit sitzung.js, i18n.js,
 * icons.js, chatlib.js) in jsdom; WebSocket und fetch sind Attrappen.
 *   1. Ist die Verbindung zu, bleibt die Nachricht im Eingabefeld, es geht
 *      nichts ueber den Draht, und der Benutzer sieht einen Hinweis
 *      (frueher: Feld geleert, Nachricht still verworfen).
 *   2. Ist sie offen, geht die Nachricht hinaus und das Feld wird geleert.
 *   3. Ein Reaktions-"Emoji" vom Server (vom Absender frei gewaehlt) wird als
 *      Text gezeigt, nie als Markup.
 *   4. Ein Anhangname mit Anfuehrungszeichen bricht nicht aus dem
 *      title-Attribut aus.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 * Lauf:  timeout 60 node tests/test_userchat_senden_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/userchat.html');
const SITZUNG = lies('frontend/js/sitzung.js');
const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/chatlib.js', 'frontend/js/userchat.js'].map(lies);

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

const BOESES_EMOJI = '<b id="rx">x</b>';            // 16 Zeichen – Messaufbau, nicht Server-Grenze
const BOESER_NAME = 'a" data-boese="1.pdf';

function fenster() {
    const dom = new JSDOM(HTML, { url: 'https://localhost/userchat', runScripts: 'outside-only' });
    const w = dom.window;
    w.scrollTo = () => {};
    w.Element.prototype.scrollIntoView = function () {};
    w.alert = () => {};
    w.confirm = () => true;

    const sockets = [];
    function FakeWS(url) {
        this.url = url;
        this.readyState = 0;
        this.gesendet = [];
        this.h = {};
        sockets.push(this);
    }
    FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
    FakeWS.prototype.addEventListener = function (t, f) { (this.h[t] = this.h[t] || []).push(f); };
    FakeWS.prototype.send = function (s) { this.gesendet.push(JSON.parse(s)); };
    FakeWS.prototype.close = function () { this.readyState = 3; };
    FakeWS.prototype.feuer = function (t, ev) { (this.h[t] || []).forEach((f) => f(ev || {})); };
    FakeWS.prototype.oeffnen = function () { this.readyState = 1; this.feuer('open'); };
    FakeWS.prototype.melde = function (obj) { this.feuer('message', { data: JSON.stringify(obj) }); };
    w.WebSocket = FakeWS;
    w.__sockets = sockets;

    w.fetch = function (url) {
        const u = String(url).split('?')[0];
        let body = {};
        if (u === '/api/me') body = { username: 'anna' };
        if (/\/api\/userchat\//.test(u)) body = { users: [] };
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve('{}') });
    };
    w.localStorage.setItem('jarvis_uc_token', 'testtoken');
    w.localStorage.setItem('jarvis_uc_user', 'anna');
    for (const src of MODULE) { w.eval(SITZUNG); w.eval(src); }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { dom, w };
}

async function main() {
    const { dom, w } = fenster();
    const d = w.document;
    await sleep(80);

    section('1) Positivkontrolle: Messaufbau');
    const ws = w.__sockets[w.__sockets.length - 1];
    check('userchat.js hat eine Verbindung aufgebaut', !!ws, String(w.__sockets.length));
    if (!ws) { bilanz(); w.close(); process.exit(2); }
    ws.oeffnen();
    ws.melde({ type: 'connected', username: 'anna', users: ['bert'] });
    ws.melde({ type: 'history', conversations: { bert: [
        { from: 'bert', to: 'anna', text: 'Hallo Anna', ts: Date.now(), msg_id: 'm1', status: 'read',
          reactions: { [BOESES_EMOJI]: ['bert'] } },
        { from: 'bert', to: 'anna', text: ' ', ts: Date.now(), msg_id: 'm2', status: 'read',
          attachments: [{ name: BOESER_NAME, mime_type: 'application/pdf', data: 'JVBERi0=' }] },
    ] } });
    const item = d.querySelector('.uc-user-item[data-username="bert"]');
    check('der Gespraechspartner steht in der Liste', !!item);
    if (item) item.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    const zeilen = d.querySelectorAll('#uc-messages [data-msgid]');
    check('der Verlauf wird gezeichnet (2 Nachrichten)', zeilen.length === 2, String(zeilen.length));
    const pill = d.querySelector('#uc-messages .uc-reaction-pill');
    check('die Reaktion wird gezeichnet', !!pill);
    const chip = d.querySelector('#uc-messages .uc-fc-name');
    check('der Anhang wird als Datei-Chip gezeichnet', !!chip);
    if (FAIL) { bilanz(); w.close(); process.exit(2); }

    section('2) Daten des Gegenuebers sind Text, kein Markup');
    check('kein eingeschleustes Element aus dem Reaktions-Emoji', !d.getElementById('rx'));
    check('das Emoji steht woertlich als Text in der Reaktion', pill.textContent.indexOf(BOESES_EMOJI) >= 0, pill.textContent);
    check('der Zaehler der Reaktion stimmt', (pill.querySelector('.uc-rp-count') || {}).textContent === '1');
    check('kein eingeschleustes Attribut aus dem Anhangnamen', !d.querySelector('[data-boese]'));
    check('der Titel des Chips traegt den Namen unveraendert', chip.getAttribute('title') === BOESER_NAME, chip.getAttribute('title'));
    const dl = d.querySelector('#uc-messages a.uc-fc-dl');
    check('auch das download-Attribut traegt den Namen unveraendert', !!dl && dl.getAttribute('download') === BOESER_NAME,
        dl ? dl.getAttribute('download') : 'kein Link');

    section('3) Senden bei geschlossener Verbindung');
    const input = d.getElementById('uc-input');
    const send = d.getElementById('uc-send-btn');
    const vorherFrames = ws.gesendet.filter((m) => m.type === 'dm').length;
    ws.readyState = 3;
    input.value = 'Wichtige Nachricht';
    const socketsVorher = w.__sockets.length;
    send.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    check('die Nachricht bleibt im Eingabefeld', input.value === 'Wichtige Nachricht', JSON.stringify(input.value));
    check('es ging nichts ueber den Draht', ws.gesendet.filter((m) => m.type === 'dm').length === vorherFrames);
    const toast = d.getElementById('uc-attach-toast');
    check('der Benutzer sieht einen Hinweis', !!toast && toast.classList.contains('show') && toast.textContent.length > 10,
        toast ? toast.textContent : 'kein Toast');
    check('der Hinweis ist uebersetzt (i18n-Schluessel vorhanden)', w.t('userchat.not_sent') !== 'userchat.not_sent');
    check('es wird sofort neu verbunden', w.__sockets.length === socketsVorher + 1,
        socketsVorher + ' -> ' + w.__sockets.length);

    section('4) Senden bei offener Verbindung');
    const ws2 = w.__sockets[w.__sockets.length - 1];
    ws2.oeffnen();
    send.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    const dm = ws2.gesendet.filter((m) => m.type === 'dm');
    check('die Nachricht geht hinaus', dm.length === 1 && dm[0].text === 'Wichtige Nachricht' && dm[0].to === 'bert',
        JSON.stringify(dm));
    check('danach ist das Eingabefeld leer', input.value === '', JSON.stringify(input.value));

    bilanz();
    dom.window.close();
    process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
