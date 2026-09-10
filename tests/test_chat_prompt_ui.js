/* Waechter: Prompt fuer EINEN Chat – Oberflaeche (2026-09-09).
 *
 * Gemessen wird die WIRKUNG am ECHTEN Markup mit dem ECHTEN chat.js: die
 * Verlaufsleiste wird vom ECHTEN `_renderSidebar` gezeichnet, die Sprechblase
 * wird GEKLICKT, und was dabei an den Server geht, nimmt eine fetch-Attrappe
 * ab. Eine Quelltext-Suche koennte weder "entsteht der Knopf" noch "welche
 * Sitzung wird geladen" noch "was passiert nach einem Ladefehler" beantworten.
 *
 * Die Texte kommen aus dem ECHTEN i18n.js: eine t()-Attrappe verschluckt
 * Platzhalter, und ein fehlender Schluessel faellt dann gar nicht auf.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try {
    ({ JSDOM } = require('jsdom'));
} catch (e) {
    for (const d of [path.join(ROOT, 'node_modules'), path.join(ROOT, 'data', 'node_modules'),
                     '/tmp/node_modules', '/usr/share/nodejs', '/usr/lib/node_modules',
                     process.env.JSDOM_PATH || '']) {
        if (!d) continue;
        try { ({ JSDOM } = require(path.join(d, 'jsdom'))); break; } catch (e2) { /* weiter */ }
    }
}
if (!JSDOM) {
    // "konnte nicht laufen" darf nie wie "bestanden" aussehen.
    console.log('\x1b[31mABBRUCH\x1b[0m: jsdom nicht gefunden (JSDOM_PATH=... setzen)');
    process.exit(2);
}

let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function sicher(fn) { try { return fn(); } catch (e) { return 'WURF: ' + e.message; } }

let _bilanzGedruckt = false;
function bilanz() {
    _bilanzGedruckt = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
}
const wachhund = setTimeout(() => {
    console.log('  \x1b[31m✗\x1b[0m Wachhund: Lauf haengt (25 s)');
    fail++; bilanz(); process.exit(1);
}, 25000);
/* ⚠ Ein Lauf, der ohne Bilanzzeile endet, ist von "nicht gelaufen" nicht zu
 * unterscheiden – und mit Exit 0 sieht er wie ein bestandener aus. */
process.on('exit', function (code) {
    if (!_bilanzGedruckt) {
        console.log('\n\x1b[31mABBRUCH ohne Bilanz\x1b[0m – ' + ok + ' OK, ' + fail
            + ' FAIL bis zum Abbruch');
        if (code === 0) process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('  \x1b[31m✗\x1b[0m unbehandelte Zurueckweisung: ' + (e && e.message));
    fail++; bilanz(); process.exit(1);
});

const HTML = fs.readFileSync(path.join(ROOT, 'frontend', 'chat.html'), 'utf8');
const CHATJS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'chat.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'i18n.js'), 'utf8');

/* Geklammerter Schnitt – NICHT bis zum ersten "\n}": eine Einzeiler-Funktion
 * dazwischen wuerde sonst mitgenommen und der Waechter pruefte fremden Code. */
function schneide(quelle, name) {
    for (const kopf of ['async function ' + name, 'function ' + name]) {
        const i = quelle.indexOf(kopf);
        if (i < 0) continue;
        const auf = quelle.indexOf('{', i);
        if (auf < 0) continue;
        let tief = 0;
        for (let j = auf; j < quelle.length; j++) {
            const c = quelle[j];
            if (c === '{') tief++;
            else if (c === '}') { tief--; if (tief === 0) return quelle.slice(i, j + 1); }
        }
    }
    return null;
}

(async function () {

// ── 1. Markup ───────────────────────────────────────────────────────────────
section('1. Markup: Dialog "Prompt fuer diesen Chat"');
const dom0 = new JSDOM(HTML, { url: 'https://pruef.local/chat' });
const doc0 = dom0.window.document;

const modal0 = doc0.getElementById('chat-prompt-modal');
check('Dialog vorhanden und startet versteckt',
      modal0 && modal0.classList.contains('hidden'));
check('Dialog ist direktes Kind von <body> (eigener Stapelkontext)',
      modal0 && modal0.parentElement === doc0.body);
check('Titel traegt den i18n-Schluessel',
      modal0 && modal0.querySelector('[data-i18n="chat.sprompt_title"]'));
check('ein Feld fuer den CHATNAMEN ist da (welcher Chat wird geaendert?)',
      modal0 && modal0.querySelector('#chat-prompt-name'));
check('Textfeld + Speichern + Schliessen vorhanden',
      modal0 && modal0.querySelector('#chat-prompt-text')
      && modal0.querySelector('#btn-chat-prompt-save')
      && modal0.querySelector('#btn-chat-prompt-close'));
check('Zustandszeile vorhanden (welche Anweisung greift gerade?)',
      modal0 && modal0.querySelector('#chat-prompt-state'));
check('die Beschreibung sagt, dass er den persoenlichen Preprompt ERSETZT',
      modal0 && (modal0.querySelector('[data-i18n="chat.sprompt_desc"]') !== null));

// ── 2. Renderer + Klicks ────────────────────────────────────────────────────
section('2. Verlaufsleiste: die Sprechblase entsteht und wirkt');

const dom = new JSDOM(HTML, { url: 'https://pruef.local/chat', runScripts: 'outside-only' });
const win = dom.window;
const doc = win.document;
global.window = win; global.document = doc;

// Echte Symbole und echte Texte laden.
win.eval(ICONS);
win.localStorage.setItem('jarvis_lang', 'de');
win.eval(I18N);

// fetch-Attrappe: routet ueber den PFAD (ein spaeter ergaenztes ?x= verfehlt
// sonst jede Route). Sie protokolliert JEDEN Aufruf.
const rufe = [];
let ladeFehler = false;
let deckel = 8000;      // wie im Backend: der Server kappt die Laenge
let gespeichert = {};   // sid -> text
win.fetch = async function (url, opt) {
    const pfad = String(url).split('?')[0];
    rufe.push({ pfad, method: (opt && opt.method) || 'GET', body: opt && opt.body });
    const m = pfad.match(/^\/api\/chat\/sessions\/([^/]+)\/preprompt$/);
    if (m) {
        const sid = decodeURIComponent(m[1]);
        if (ladeFehler && (!opt || !opt.method || opt.method === 'GET')) {
            return { ok: false, json: async () => ({ ok: false, error: 'kaputt' }) };
        }
        if (opt && opt.method === 'PUT') {
            // Der ECHTE Endpunkt DECKELT die Laenge – die Attrappe tut es auch,
            // sonst waere "die Antwort des Servers gewinnt" nicht messbar.
            const t = (JSON.parse(opt.body).preprompt || '').slice(0, deckel);
            gespeichert[sid] = t.trim() ? t : '';
            return { ok: true, json: async () => ({ ok: true, preprompt: gespeichert[sid],
                                                    has_prompt: !!gespeichert[sid] }) };
        }
        return { ok: true, json: async () => ({ ok: true, preprompt: gespeichert[sid] || '' }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
};
global.fetch = win.fetch;

// Harness: die ECHTEN Funktionen, drumherum nur Attrappen.
const teile = ['_renderSidebar', '_openSessionPrompt', '_closeSessionPrompt',
               '_spZustand', '_saveSessionPrompt'];
const stuecke = teile.map(n => {
    const s = schneide(CHATJS, n);
    if (!s) { check('Schnitt: ' + n + ' gefunden', false, 'nicht im Quelltext'); }
    return s || '';
});
check('alle fuenf Funktionen liessen sich schneiden', stuecke.every(s => s.length > 20),
      teile.map((n, i) => n + ':' + stuecke[i].length).join(' '));

const gewechselt = [], umbenannt = [], geloescht = [];
/* ⚠ Modulvariablen (_spSid, _spLaeuft, _sessions, _activeSid) fallen aus jedem
 * Funktions-Schnitt heraus – ohne diese Deklarationen bricht der Lauf mit einem
 * nackten ReferenceError ab (Register, im Projekt mehrfach bezahlt). */
const prolog = `
var _sessions = [], _activeSid = null, _spSid = null, _spLaeuft = false;
var gewechselt = [], umbenannt = [], geloescht = [];
var $ = function (id) { return document.getElementById(id); };
function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function _csHeaders(h) { return h || {}; }
function _switchSession(id) { gewechselt.push(id); }
function _renameSession(s) { umbenannt.push(s.id); }
function _deleteSession(s) { geloescht.push(s.id); }
`;
const epilog = `
window.__h = { setzeSessions: function (l, aktiv) { _sessions = l; _activeSid = aktiv || null; },
               render: _renderSidebar, oeffnen: _openSessionPrompt, speichern: _saveSessionPrompt,
               schliessen: _closeSessionPrompt, sid: function () { return _spSid; },
               sessions: function () { return _sessions; },
               gewechselt: gewechselt, umbenannt: umbenannt, geloescht: geloescht };
`;
win.eval(prolog + stuecke.join('\n') + epilog);
const H = win.__h;

const S = [
    { id: 'aaa111', title: 'Chat ohne Prompt', has_prompt: false },
    { id: 'bbb222', title: 'Chat MIT Prompt', has_prompt: true }
];
gespeichert = { bbb222: 'NUR ENGLISCH' };
H.setzeSessions(S, 'aaa111');
H.render();

const zeilen = Array.from(doc.querySelectorAll('#cs-list .cs-item'));
check('beide Chats gezeichnet', zeilen.length === 2, 'gefunden: ' + zeilen.length);

const bl0 = zeilen[0] && zeilen[0].querySelector('.cs-prompt');
const bl1 = zeilen[1] && zeilen[1].querySelector('.cs-prompt');
check('jede Zeile traegt eine Sprechblase', !!bl0 && !!bl1);
check('sie ist ein <button> (bedienbar, kein Zierrat)',
      bl0 && bl0.tagName === 'BUTTON' && bl0.type === 'button');
check('sie enthaelt ein Inline-SVG aus JarvisIcons',
      bl0 && bl0.querySelector('svg.jv-ico-prompt'));

// ⚠ Der Zustand muss an der FORM erkennbar sein, nicht nur an einer Farbe.
check('gesetzter Prompt: Sprechblase gefuellt (andere Silhouette)',
      bl1 && bl1.querySelector('svg').getAttribute('fill') === 'currentColor',
      bl1 ? bl1.innerHTML.slice(0, 60) : '');
check('kein Prompt: Sprechblase hohl',
      bl0 && bl0.querySelector('svg').getAttribute('fill') === 'none');
check('gesetzter Prompt: Zeile traegt die Klasse fuer die Dauer-Sichtbarkeit',
      bl1 && bl1.classList.contains('is-gesetzt') && !bl0.classList.contains('is-gesetzt'));

// ⚠ Der Zustand steht auch in WORTEN – ein Tooltip ist unsichtbar, aber das
// aria-label ist die Aussage fuer Hilfsmittel, und die Texte muessen sich
// unterscheiden (sonst sagt der Knopf nichts ueber den Zustand).
check('title und aria-label sind gesetzt und tragen echten Text (kein Schluessel)',
      bl0 && bl0.title && bl0.title === bl0.getAttribute('aria-label')
      && !bl0.title.startsWith('chat.'), bl0 ? bl0.title : '');
check('die Beschriftung UNTERSCHEIDET beide Zustaende',
      bl0 && bl1 && bl0.title !== bl1.title, (bl0 || {}).title + ' / ' + (bl1 || {}).title);

// ── 3. Klick auf die Sprechblase ────────────────────────────────────────────
section('3. Klick: oeffnet den Dialog fuer die ANGEKLICKTE Sitzung');

const svgTreffer = bl1.querySelector('svg path') || bl1.querySelector('svg');
svgTreffer.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 30));

const modal = doc.getElementById('chat-prompt-modal');
const ta = doc.getElementById('chat-prompt-text');
check('der Dialog ist offen', modal && !modal.classList.contains('hidden'));
// Der Klick traf das <path> IM Knopf – ohne `contains` waere zusaetzlich die
// Sitzung gewechselt worden.
check('⚠ der Klick hat NICHT zusaetzlich die Sitzung gewechselt',
      H.gewechselt.length === 0, JSON.stringify(H.gewechselt));
check('geladen wurde der Prompt der ANGEKLICKTEN Sitzung (nicht der aktiven)',
      rufe.some(r => r.pfad === '/api/chat/sessions/bbb222/preprompt' && r.method === 'GET')
      && !rufe.some(r => r.pfad.includes('aaa111')),
      rufe.map(r => r.method + ' ' + r.pfad).join(' | '));
check('der vorhandene Text steht im Feld', ta && ta.value === 'NUR ENGLISCH', ta ? ta.value : '');
check('der Chatname steht im Titel',
      (doc.getElementById('chat-prompt-name') || {}).textContent === 'Chat MIT Prompt');
check('die Zustandszeile sagt, dass DIESER Prompt gilt',
      (doc.getElementById('chat-prompt-state') || {}).textContent.length > 10
      && !(doc.getElementById('chat-prompt-state') || {}).textContent.startsWith('chat.'),
      (doc.getElementById('chat-prompt-state') || {}).textContent);

// ── 4. Speichern ────────────────────────────────────────────────────────────
section('4. Speichern: Endpunkt, Zustand, Neuzeichnen');

ta.value = 'Antworte als Pruefer.';
await H.speichern();
await new Promise(r => setTimeout(r, 30));
const put = rufe.filter(r => r.method === 'PUT');
check('genau EIN PUT, und zwar auf die richtige Sitzung',
      put.length === 1 && put[0].pfad === '/api/chat/sessions/bbb222/preprompt',
      put.map(r => r.pfad).join(','));
check('der Text geht als "preprompt" mit',
      put.length === 1 && JSON.parse(put[0].body).preprompt === 'Antworte als Pruefer.');
check('die Sitzung in der Liste traegt danach has_prompt=true',
      H.sessions().find(s => s.id === 'bbb222').has_prompt === true);

// ⚠ DIE ANTWORT DES SERVERS GEWINNT gegen den Formularstand: er deckelt die
// Laenge und entscheidet, ob noch etwas gilt. Uebernimmt der Client seinen
// eigenen Text, zeigt das Feld etwas anderes an, als gespeichert ist – und beim
// naechsten Speichern schriebe er den ungedeckelten Stand zurueck.
deckel = 10;
ta.value = 'DIESER TEXT IST VIEL ZU LANG';
await H.speichern();
await new Promise(r => setTimeout(r, 30));
check('⚠ das Feld zeigt danach den GEKUERZTEN Stand des Servers',
      ta.value === 'DIESER TEX', JSON.stringify(ta.value));
check('und der Server hat wirklich gekuerzt (Positivkontrolle der Messung)',
      gespeichert.bbb222 === 'DIESER TEX', JSON.stringify(gespeichert.bbb222));
deckel = 8000;

// Leeren -> Default gilt wieder
H.setzeSessions(S, 'aaa111'); H.render();
const bl1b = doc.querySelectorAll('#cs-list .cs-item')[1].querySelector('.cs-prompt');
bl1b.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 30));
doc.getElementById('chat-prompt-text').value = '   ';
await H.speichern();
await new Promise(r => setTimeout(r, 30));
check('leerer Text: die Sitzung meldet danach has_prompt=false',
      H.sessions().find(s => s.id === 'bbb222').has_prompt === false);
const blNach = doc.querySelectorAll('#cs-list .cs-item')[1].querySelector('.cs-prompt');
check('die Zeile wurde neu gezeichnet – Sprechblase wieder hohl',
      blNach && blNach.querySelector('svg').getAttribute('fill') === 'none'
      && !blNach.classList.contains('is-gesetzt'));
check('die Zustandszeile nennt danach den persoenlichen Preprompt',
      (doc.getElementById('chat-prompt-state') || {}).textContent.length > 10);

// ── 5. Ladefehler ───────────────────────────────────────────────────────────
section('5. Ladefehler: nichts ueberschreiben');

gespeichert = { aaa111: 'DARF NICHT VERLORENGEHEN' };
ladeFehler = true;
H.setzeSessions(S, 'aaa111'); H.render();
rufe.length = 0;
doc.querySelectorAll('#cs-list .cs-item')[0].querySelector('.cs-prompt')
   .dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 30));
const taF = doc.getElementById('chat-prompt-text');
check('⚠ das Feld ist GESPERRT (ein leeres Feld waere hier eine Falle)',
      taF && taF.disabled === true);
check('und die Meldung sagt, dass nichts geladen wurde',
      (doc.getElementById('chat-prompt-status') || {}).textContent.length > 10);
await H.speichern();
await new Promise(r => setTimeout(r, 30));
check('⚠ ein Speichern in diesem Zustand schickt NICHTS',
      !rufe.some(r => r.method === 'PUT'), rufe.map(r => r.method + ' ' + r.pfad).join('|'));
check('der gespeicherte Prompt ist unangetastet',
      gespeichert.aaa111 === 'DARF NICHT VERLORENGEHEN');
ladeFehler = false;

// ── 6. Die uebrigen Knoepfe der Zeile wirken weiter ─────────────────────────
section('6. Gegenrichtung: Zeile, Umbenennen, Loeschen unveraendert');

H.setzeSessions(S, 'aaa111'); H.render();
const z0 = doc.querySelectorAll('#cs-list .cs-item')[0];
z0.querySelector('.cs-title').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
check('Klick auf den Titel wechselt weiterhin die Sitzung (Positivkontrolle)',
      H.gewechselt.length === 1 && H.gewechselt[0] === 'aaa111', JSON.stringify(H.gewechselt));
z0.querySelector('.cs-ren').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
check('Umbenennen unveraendert', H.umbenannt.join(',') === 'aaa111');
const muell = z0.querySelector('.cs-del svg') || z0.querySelector('.cs-del');
muell.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
check('Loeschen unveraendert (auch bei Treffer auf das SVG)',
      H.geloescht.join(',') === 'aaa111', JSON.stringify(H.geloescht));
check('Reihenfolge in der Zeile: Titel, Sprechblase, Umbenennen, Muelleimer',
      Array.from(z0.children).map(e => e.className.split(' ').pop()).join(',')
      === 'cs-title,cs-prompt,cs-ren,cs-del',
      Array.from(z0.children).map(e => e.className).join(' | '));

// ── 7. Schliessen ───────────────────────────────────────────────────────────
section('7. Schliessen');
H.schliessen();
check('der Dialog ist zu', doc.getElementById('chat-prompt-modal').classList.contains('hidden'));
check('und die gemerkte Sitzung ist zurueckgesetzt', H.sid() === null);

clearTimeout(wachhund);
try { win.close(); } catch (e) { /* egal */ }
bilanz();
process.exit(fail ? 1 : 0);

})();
