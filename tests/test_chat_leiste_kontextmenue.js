/* Waechter: eigenes Kontextmenue in der linken Verlaufsleiste von /chat (2026-11-23).
 *
 * Auftrag des Betreibers: in der Seitenleiste das Browser-Menue ersetzen –
 * Prompt, Umbenennen, Loeschen und was sonst sinnvoll ist. Gemessen wird die
 * WIRKUNG: ein echtes `contextmenu`-Ereignis auf Elemente des ECHTEN Markups
 * (chat.html), verarbeitet vom ECHTEN `setupBubbleContextMenu` (chatlib.js),
 * Eintraege aus dem echten `_csCtxItems`, Zeilen gezeichnet vom echten
 * `_renderSidebar`. Ein Klick auf einen Eintrag muss die Aktion fuer GENAU den
 * angeklickten Chat ausloesen (Attrappen zeichnen die Aufrufe auf).
 *
 * Faelle:
 *   * Chat-Zeile (Titel, Knopf an der Zeile) -> Prompt, Umbenennen,
 *     Mehrere auswaehlen, Loeschen (zuletzt); PDF nur am OFFENEN Chat
 *   * freie Flaeche der Leiste / Kopfzeile   -> Neuer Chat, Mehrere auswaehlen,
 *     Beispiel-Prompts, Chat-Einstellungen; KEIN Loeschen
 *   * Auswahlmodus                           -> nur Auswahl-Aktionen, kein
 *     Einzel-Loeschen
 *   * SHIFT                                  -> Browser-Menue bleibt
 * Dazu die REGEL, dass chat.js das Menue an #chat-sidebar haengt (die
 * Verdrahtung liegt im Seitenstart, der hier nicht laeuft).
 *
 * Texte aus dem ECHTEN i18n.js (DE) – ein fehlender Schluessel faellt auf.
 *
 *   node tests/test_chat_leiste_kontextmenue.js
 * CHAT_JS / CHATLIB_JS legen sabotierte KOPIEN vor (Gegenprobe).
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
if (!JSDOM) {
    console.log('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH=... setzen)');
    process.exit(2);
}

let ok = 0, fail = 0, _bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail !== undefined ? ' – ' + JSON.stringify(detail) : '')); }
}
function section(t) { console.log('\n' + t); }
function bilanz() { _bilanz = true; console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL'); }
function abbruch(t) { console.log('ABBRUCH: ' + t); _bilanz = true; process.exit(2); }
process.on('exit', (code) => { if (!_bilanz && code === 0) process.exitCode = 1; });
const wachhund = require('./lib/wachhund')(() => {
    console.log('  FAIL Wachhund: Lauf haengt'); fail++; bilanz(); process.exit(1);
}, 20000);

const lies = (env, rel) => fs.readFileSync(process.env[env] || path.join(ROOT, rel), 'utf8');
const HTML    = lies('CHAT_HTML', 'frontend/chat.html');
const CHATJS  = lies('CHAT_JS', 'frontend/js/chat.js');
const CHATLIB = lies('CHATLIB_JS', 'frontend/js/chatlib.js');
const ICONS   = lies('ICONS_JS', 'frontend/js/icons.js');
const I18N    = lies('I18N_JS', 'frontend/js/i18n.js');

function schneide(quelle, name) {
    for (const kopf of ['async function ' + name + '(', 'function ' + name + '(']) {
        const i = quelle.indexOf(kopf);
        if (i < 0) continue;
        const auf = quelle.indexOf('{', i);
        let tief = 0;
        for (let j = auf; j < quelle.length; j++) {
            const c = quelle[j];
            if (c === '{') tief++;
            else if (c === '}') { tief--; if (tief === 0) return quelle.slice(i, j + 1); }
        }
    }
    return null;
}

const NAMEN = ['_csCtxItems', '_renderSidebar', '_renderTools', '_ctxPdfItem', '_selSetze', '_selModus',
               '_istSensibel'];   // Helfer des sensiblen Chats (2026-11-24), ECHT geschnitten
const TEILE = NAMEN.map(n => schneide(CHATJS, n));
if (TEILE.some(t => !t)) abbruch('Funktionen in chat.js nicht gefunden: '
    + NAMEN.filter((n, i) => !TEILE[i]).join(', '));

/* ── 0. Regel: chat.js haengt das Menue an die GANZE Leiste ─────────────── */
section('0. Verdrahtung in chat.js');
// Kommentare ausblenden, sonst liest die Regel ihre eigene Begruendung.
const ohneKomm = CHATJS.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:'"\\])\/\/[^\n]*/g, '$1');
const mVar = ohneKomm.match(/const\s+(\w+)\s*=\s*\$\(\s*'chat-sidebar'\s*\)/);
check('die Leiste wird ueber ihre id geholt', !!mVar);
const re = mVar ? new RegExp('setupBubbleContextMenu\\(\\s*' + mVar[1] + '\\s*,\\s*_csCtxItems\\s*\\)') : null;
check('setupBubbleContextMenu(<Leiste>, _csCtxItems) wird aufgerufen', !!(re && re.test(ohneKomm)));

/* ── Aufbau ────────────────────────────────────────────────────────────── */
const dom = new JSDOM(HTML, { url: 'https://pruef.local/chat', runScripts: 'outside-only' });
const w = dom.window, doc = w.document;
w.eval(ICONS);
w.eval(I18N);
try { w.localStorage.setItem('jarvis_lang', 'de'); } catch (_) {}
w.eval(CHATLIB);

const PROLOG = `
var _sessions = [
  { id: 's1', title: 'Erster Chat',  has_prompt: false },
  { id: 's2', title: 'Zweiter Chat', has_prompt: true  },
  { id: 's3', title: 'Dritter Chat', has_prompt: false },
];
var _activeSid = 's1', _selMode = false, _selIds = new Set();
// Sensibler Chat (Schalter "sensible Daten", 2026-11-24): die Leiste fragt
// _istSensibel; die Map ist Modulvariable und faellt aus jedem Schnitt.
var _sensChats = new Map(), ws = null;
var messagesEl = document.getElementById('messages') || document.body;
var $ = function (id) { return document.getElementById(id); };
function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
var AUFRUFE = [];
function _merk(n, s) { AUFRUFE.push(n + (s ? ':' + s.id : '')); }
function _newSession() { _merk('neu'); }
function _restoreWelcome() { _merk('beispiele'); }
function _openChatSettings() { _merk('einstellungen'); }
function _openSessionPrompt(s) { _merk('prompt', s); }
function _renameSession(s) { _merk('umbenennen', s); }
function _deleteSession(s) { _merk('loeschen', s); }
function _deleteSelected() { _merk('sammelloeschen'); }
function _exportChatPdf() { _merk('pdf'); }
function _switchSession(id) { _merk('oeffnen', { id: id }); }
function showToast() {}
`;
w.eval(PROLOG + TEILE.join('\n') + `
window.__t = { _csCtxItems: _csCtxItems, _renderSidebar: _renderSidebar,
  zustand: function () { return { sel: _selMode, ids: Array.from(_selIds) }; },
  setzeAktiv: function (id) { _activeSid = id; }, aufrufe: AUFRUFE };
`);
const T = w.__t;
const side = doc.getElementById('chat-sidebar');
if (!side) abbruch('#chat-sidebar fehlt im Markup');
// Die Verdrahtung wie im Seitenstart (Regel in Abschnitt 0).
w.JarvisChatLib.setupBubbleContextMenu(side, T._csCtxItems);
T._renderSidebar();

// Zeilen ueber die Position finden, NICHT ueber data-sid: fehlt die Kennung
// (Produktfehler), soll das als FAIL in Abschnitt 2/3 auffallen statt als
// "konnte nicht laufen".
const IDX = { s1: 0, s2: 1, s3: 2 };
const zeile = id => doc.querySelectorAll('#cs-list .cs-item')[IDX[id]];
if (doc.querySelectorAll('#cs-list .cs-item').length !== 3) abbruch('_renderSidebar zeichnet nicht drei Zeilen – Messaufbau kaputt');
// Eine Nachricht im Verlauf, damit der PDF-Eintrag am offenen Chat moeglich ist.
const ms = doc.getElementById('messages');
if (ms) { const r = doc.createElement('div'); r.className = 'msg-row user'; ms.appendChild(r); }

function rechtsklick(el, shift) {
    const ev = new w.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 10, shiftKey: !!shift });
    el.dispatchEvent(ev);
    const menu = doc.getElementById('jv-bubble-ctx-menu');
    const offen = !!(menu && menu.classList.contains('open'));
    const labels = offen ? Array.from(menu.querySelectorAll('.jv-bubble-ctx-item')).map(b => b.textContent.trim()) : [];
    const knopf = text => offen ? Array.from(menu.querySelectorAll('.jv-bubble-ctx-item')).find(b => b.textContent.trim() === text) : null;
    const danger = offen ? Array.from(menu.querySelectorAll('.jv-bubble-ctx-item.danger')).map(b => b.textContent.trim()) : [];
    // Menue fuer den naechsten Fall schliessen (Escape-Handler von chatlib).
    return { verhindert: ev.defaultPrevented, offen, labels, knopf, danger,
             zu: () => doc.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' })) };
}
function klick(m, text) {
    const b = m.knopf(text);
    if (!b) return false;
    const vorher = T.aufrufe.length;
    b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    return T.aufrufe.slice(vorher);
}

/* ── 1. Positivkontrolle ───────────────────────────────────────────────── */
section('1. Positivkontrolle: Rechtsklick auf eine Zeile oeffnet ein eigenes Menue');
const m1 = rechtsklick(zeile('s1').querySelector('.cs-title'));
if (!m1.offen) abbruch('auf der Titelzeile oeffnet sich kein Menue – alle weiteren Pruefungen waeren trivial');
check('Browser-Menue unterdrueckt (preventDefault)', m1.verhindert);

/* ── 2. Zeile des OFFENEN Chats ────────────────────────────────────────── */
section('2. Zeile des offenen Chats (s1, ohne eigenen Prompt)');
check('Eintraege in fester Reihenfolge',
      JSON.stringify(m1.labels) === JSON.stringify(['Prompt festlegen', 'Umbenennen', 'Chat als PDF', 'Mehrere auswählen', 'Löschen']),
      m1.labels);
check('nur "Löschen" ist als gefaehrlich markiert', JSON.stringify(m1.danger) === '["Löschen"]', m1.danger);
check('Prompt -> _openSessionPrompt(s1)', JSON.stringify(klick(m1, 'Prompt festlegen')) === '["prompt:s1"]');
check('Umbenennen -> _renameSession(s1)', JSON.stringify(klick(rechtsklick(zeile('s1').querySelector('.cs-title')), 'Umbenennen')) === '["umbenennen:s1"]');
check('Löschen -> _deleteSession(s1)', JSON.stringify(klick(rechtsklick(zeile('s1').querySelector('.cs-title')), 'Löschen')) === '["loeschen:s1"]');
check('PDF -> _exportChatPdf()', JSON.stringify(klick(rechtsklick(zeile('s1').querySelector('.cs-title')), 'Chat als PDF')) === '["pdf"]');
check('ein Klick auf einen Menue-Eintrag oeffnet NICHT nebenbei den Chat',
      !T.aufrufe.some(a => a.startsWith('oeffnen')), T.aufrufe);

/* ── 3. Zeile eines ANDEREN Chats, ueber den Knopf an der Zeile ────────── */
section('3. Anderer Chat (s2, eigener Prompt), Rechtsklick auf den Muelleimer der Zeile');
const del2 = zeile('s2').querySelector('.cs-del');
const m3 = rechtsklick(del2 || zeile('s2'));
check('Menue offen', m3.offen);
check('kein PDF (der Chat ist nicht offen)', !m3.labels.includes('Chat als PDF'), m3.labels);
check('"Prompt bearbeiten" statt "festlegen", wenn einer hinterlegt ist',
      m3.labels[0] === 'Prompt bearbeiten', m3.labels);
check('"Löschen" steht zuletzt', m3.labels[m3.labels.length - 1] === 'Löschen', m3.labels);
check('Löschen trifft s2, nicht den offenen Chat', JSON.stringify(klick(m3, 'Löschen')) === '["loeschen:s2"]');

/* ── 4. Freie Flaeche und Kopfzeile ────────────────────────────────────── */
section('4. Freie Flaeche der Liste und Kopfzeile');
for (const [name, el] of [['Liste (Hintergrund)', doc.getElementById('cs-list')],
                          ['Knopf "+ Neuer Chat"', doc.getElementById('cs-new')],
                          ['Fusszeile', side.querySelector('.cs-foot')]]) {
    if (!el) { check(name + ': Element vorhanden', false); continue; }
    const m = rechtsklick(el);
    check(name + ': eigenes Menue', m.offen && m.verhindert);
    check(name + ': Neuer Chat, Mehrere auswählen, Beispiel-Prompts, Chat-Einstellungen',
          JSON.stringify(m.labels) === JSON.stringify(['Neuer Chat', 'Mehrere auswählen', 'Beispiel-Prompts', 'Chat-Einstellungen']),
          m.labels);
    check(name + ': kein Loeschen ohne Bezug auf einen Chat', !m.labels.some(l => l.startsWith('Löschen')), m.labels);
    m.zu();
}
check('Neuer Chat -> _newSession()', JSON.stringify(klick(rechtsklick(doc.getElementById('cs-list')), 'Neuer Chat')) === '["neu"]');
check('Beispiel-Prompts -> _restoreWelcome()', JSON.stringify(klick(rechtsklick(doc.getElementById('cs-list')), 'Beispiel-Prompts')) === '["beispiele"]');
check('Chat-Einstellungen -> _openChatSettings()', JSON.stringify(klick(rechtsklick(doc.getElementById('cs-list')), 'Chat-Einstellungen')) === '["einstellungen"]');

/* ── 5. Auswahlmodus ───────────────────────────────────────────────────── */
section('5. "Mehrere auswählen" an einer Zeile und der Auswahlmodus');
klick(rechtsklick(zeile('s3').querySelector('.cs-title')), 'Mehrere auswählen');
const z5 = T.zustand();
check('Auswahlmodus an, der angeklickte Chat ist ausgewaehlt',
      z5.sel === true && JSON.stringify(z5.ids) === '["s3"]', z5);
const m5 = rechtsklick(zeile('s3'));
check('ausgewaehlte Zeile: Auswahl aufheben, Löschen (1), Auswahl beenden',
      JSON.stringify(m5.labels) === JSON.stringify(['Auswahl aufheben', 'Löschen (1)', 'Auswahl beenden']), m5.labels);
m5.zu();
const m5b = rechtsklick(zeile('s1'));
check('andere Zeile: "Auswählen" statt Einzel-Loeschen',
      m5b.labels[0] === 'Auswählen' && !m5b.labels.includes('Löschen'), m5b.labels);
klick(m5b, 'Auswählen');
check('"Auswählen" nimmt die Zeile in die Auswahl', JSON.stringify(T.zustand().ids.sort()) === '["s1","s3"]', T.zustand());
check('Löschen (2) -> Sammelloeschen', JSON.stringify(klick(rechtsklick(zeile('s1')), 'Löschen (2)')) === '["sammelloeschen"]');
klick(rechtsklick(doc.getElementById('cs-list')), 'Auswahl beenden');
check('"Auswahl beenden" schaltet den Modus aus', T.zustand().sel === false, T.zustand());

/* ── 6. SHIFT ──────────────────────────────────────────────────────────── */
section('6. SHIFT laesst das Browser-Menue durch');
doc.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
const m6 = rechtsklick(zeile('s1').querySelector('.cs-title'), true);
check('mit SHIFT kein preventDefault und kein eigenes Menue', !m6.verhindert && !m6.offen, m6);

/* ── 7. i18n ───────────────────────────────────────────────────────────── */
section('7. Jeder neue Schluessel hat DE und EN');
const neu = ['chat.ctx_prompt', 'chat.ctx_prompt_edit', 'chat.ctx_select', 'chat.ctx_select_end',
             'chat.ctx_pick', 'chat.ctx_unpick', 'chat.ctx_new', 'chat.ctx_settings'];
for (const k of neu) {
    const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
    check(k + ' steht zweimal (DE + EN)', n === 2, n);
}

clearTimeout(wachhund);
bilanz();
w.close();
process.exit(fail ? 1 : 0);
