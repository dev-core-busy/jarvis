/* Waechter: mehrere Chats zusammen loeschen – Oberflaeche (2026-09-29).
 *
 * Gemessen wird die WIRKUNG am ECHTEN Markup (chat.html) mit dem ECHTEN
 * chat.js: die Verlaufsleiste zeichnet `_renderSidebar`, die Kaestchen werden
 * GEKLICKT, und was dabei an den Server geht, nimmt eine fetch-Attrappe ab.
 * Eine Quelltext-Suche koennte weder "entsteht das Kaestchen" noch "welche Ids
 * gehen an den Server" noch "was bleibt nach einem Teilfehlschlag stehen"
 * beantworten.
 *
 * ⚠ DREI Sitzungen, nicht eine: mit einer einzigen ist die Liste nach dem
 * Loeschen LEER, und "eines von mehreren verschwindet" ist damit gar nicht
 * messbar (Register: der Loeschfall wird nicht hergestellt).
 *
 * Die Texte kommen aus dem ECHTEN i18n.js – eine t()-Attrappe verschluckt
 * Platzhalter, und ein fehlender Schluessel faellt dann nicht auf.
 *
 *   node tests/test_chat_mehrfach_loeschen.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
({ JSDOM } = require('./lib/jsdom_laden')());
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
 * unterscheiden – und mit Exit 0 saehe er wie ein bestandener aus. */
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

const HTML   = fs.readFileSync(path.join(ROOT, 'frontend', 'chat.html'), 'utf8');
const CHATJS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'chat.js'), 'utf8');
const ICONS  = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8');
const I18N   = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'i18n.js'), 'utf8');
const CSS    = fs.readFileSync(path.join(ROOT, 'frontend', 'css', 'chat.css'), 'utf8')
             + fs.readFileSync(path.join(ROOT, 'frontend', 'css', 'theme.css'), 'utf8');

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
section('1. Markup: Werkzeugzeile der Verlaufsleiste');
const dom0 = new JSDOM(HTML, { url: 'https://pruef.local/chat' });
const doc0 = dom0.window.document;

const bar0 = doc0.getElementById('cs-tools');
check('Werkzeugzeile vorhanden', !!bar0);
check('sie startet VERSTECKT (ohne Chats gibt es nichts auszuwaehlen)',
      bar0 && bar0.hasAttribute('hidden'));
check('sie steht in der Verlaufsleiste, VOR der Liste',
      bar0 && bar0.parentElement && bar0.parentElement.id === 'chat-sidebar'
      && !!(bar0.compareDocumentPosition(doc0.getElementById('cs-list'))
            & dom0.window.Node.DOCUMENT_POSITION_FOLLOWING));
const um0 = doc0.getElementById('cs-selmode');
const del0 = doc0.getElementById('cs-seldel');
const all0 = doc0.getElementById('cs-all');
check('Umschalter, Loeschknopf und "Alle" vorhanden', !!um0 && !!del0 && !!all0);
check('Loeschknopf und "Alle" starten versteckt',
      del0 && del0.hasAttribute('hidden')
      && doc0.getElementById('cs-all-wrap').hasAttribute('hidden'));
check('alle drei sind <button>/<input type=checkbox>, kein Zierrat',
      um0.tagName === 'BUTTON' && um0.type === 'button'
      && del0.tagName === 'BUTTON' && del0.type === 'button'
      && all0.tagName === 'INPUT' && all0.type === 'checkbox');

/* ⚠ KEINE .btn-*-KLASSEN: die stehen in style.css, und /chat laedt nur
 * theme.css + chat.css – ein `.btn-secondary` waere dort ein nackter
 * Browser-Standardknopf (Register: derselbe Fehler traf /ai-mouse und
 * /jira-addon gleich dreimal). Und eine Klasse OHNE jede Regel faellt
 * niemandem auf (`.ja-actions` war frei erfunden).
 *
 * Gemessen wird deshalb nicht die SCHREIBWEISE im CSS, sondern ob das Element
 * von mindestens einer Regel ERREICHT wird: der Selektor-Motor von jsdom
 * beantwortet das (`el.matches`). Eine Textsuche nach ".cs-tool" koennte
 * weder `.cs-tools .cs-all` von `.cs-all` unterscheiden noch sagen, ob die
 * Regel dieses Element ueberhaupt trifft. (Die KASKADE bildet jsdom falsch
 * ab – danach wird hier bewusst nicht gefragt.) */
const stil = doc0.createElement('style');
stil.textContent = CSS;
doc0.head.appendChild(stil);
const regeln = [];
Array.from(doc0.styleSheets).forEach(sh => {
    let rs = [];
    try { rs = Array.from(sh.cssRules || []); } catch (e) { rs = []; }
    rs.forEach(r => { if (r.selectorText) regeln.push(r.selectorText); });
});
// Positivkontrolle: ohne geladene Regeln waere jede Aussage darunter wertlos.
const bekannt = regeln.some(s => /\.cs-item\b/.test(s));
if (!bekannt) {
    check('CSS von /chat geladen (Positivkontrolle)', false, regeln.length + ' Regeln');
    bilanz(); process.exit(2);
}
check('CSS von /chat geladen (Positivkontrolle: .cs-item gefunden)', true);
/* ⚠ NICHT "irgendeine Regel trifft": theme.css enthaelt `*, *::before,
 * *::after` – damit waere die Aussage fuer JEDES Element trivial wahr (beim
 * ersten Bauen genau so gemessen). Gefragt ist je KLASSE: gibt es eine Regel,
 * die diese Klasse NENNT und dieses Element auch TRIFFT? Das faengt beides –
 * die frei erfundene Klasse ohne Regel und die Regel, die nur in fremdem
 * Kontext gilt (`.jv-pc-foot .btn-primary`). */
const traegtKlasse = (el, k) => regeln.some(sel => {
    if (!new RegExp('\\.' + k + '(?![\\w-])').test(sel)) return false;
    try { return el.matches(sel); } catch (e) { return false; }
});
const neue = { 'cs-tools': bar0, 'cs-all-wrap': doc0.getElementById('cs-all-wrap'),
               'cs-all (Kaestchen)': all0, 'cs-selmode': um0, 'cs-seldel': del0 };
const klassen = new Set();
const ohneRegel = [];
Object.keys(neue).forEach(n => {
    const ks = (neue[n].className || '').split(/\s+/).filter(Boolean);
    ks.forEach(k => klassen.add(k));
    // Das Kaestchen traegt keine eigene Klasse – es wird ueber den Elternteil
    // gestylt; dort zaehlt, dass eine Regel es trifft, die .cs-all nennt.
    const gilt = ks.length ? ks.every(k => traegtKlasse(neue[n], k))
                           : traegtKlasse(neue[n], 'cs-all');
    if (!gilt) ohneRegel.push(n + ' (' + (ks.join('.') || 'ohne Klasse') + ')');
});
check('jede Klasse der neuen Bedienelemente wird von einer TREFFENDEN Regel gestylt',
      ohneRegel.length === 0, 'ohne Regel: ' + ohneRegel.join(', '));
check('keine .btn-*-Klasse aus style.css benutzt',
      !Array.from(klassen).some(k => k.indexOf('btn-') === 0), Array.from(klassen).join(' '));

// ── 2. Harness ──────────────────────────────────────────────────────────────
section('2. Harness: echte Funktionen, echte Texte');

const dom = new JSDOM(HTML, { url: 'https://pruef.local/chat', runScripts: 'outside-only' });
const win = dom.window;
const doc = win.document;
global.window = win; global.document = doc;

win.eval(ICONS);
win.localStorage.setItem('jarvis_lang', 'de');
/* ⚠ Die Sprachtabelle `_I18N` ist ein `const` – ein zweites win.eval() sieht
 * die Bindung NICHT (in jsdom hat jeder eval seinen eigenen Lexikalraum), und
 * window.t() faellt bei einem fehlenden Schluessel auf Deutsch zurueck. Damit
 * Abschnitt 10 die TABELLE messen kann statt des Rueckfalls, wird sie im
 * SELBEN Lauf herausgereicht. Die Datei selbst bleibt unangetastet. */
win.eval(I18N + '\nwindow.__i18n = _I18N;');

// fetch-Attrappe: routet ueber den PFAD (ein spaeter ergaenztes ?x= verfehlt
// sonst jede Route) und bildet die ECHTE Antwortform des Endpunkts nach
// (ok/deleted/failed), nicht eine bequemere.
const rufe = [];
let antwort = null;           // was /api/chat/sessions/delete liefert
win.fetch = async function (url, opt) {
    const pfad = String(url).split('?')[0];
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    rufe.push({ pfad, method: (opt && opt.method) || 'GET', body });
    if (pfad === '/api/chat/sessions/delete') {
        const ids = (body && body.ids) || [];
        const a = antwort ? antwort(ids) : { ok: true, deleted: ids, failed: [] };
        return { ok: true, json: async () => a };
    }
    if (pfad === '/api/chat/sessions' && (opt && opt.method) === 'POST') {
        return { ok: true, json: async () => ({ ok: true, session: { id: 'neu999', title: 'Neuer Chat' } }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
};
global.fetch = win.fetch;

const teile = ['_renderSidebar', '_renderTools', '_selSetze', '_selModus', '_selAlle',
               '_deleteSelected', '_nachLoeschen'];
const stuecke = teile.map(n => {
    const s = schneide(CHATJS, n);
    if (!s) check('Schnitt: ' + n + ' gefunden', false, 'nicht im Quelltext');
    return s || '';
});
// Positivkontrolle VOR den inhaltlichen Pruefungen: ohne sie sind sie trivial.
if (!stuecke.every(s => s.length > 20)) {
    check('alle sieben Funktionen liessen sich schneiden', false,
          teile.map((n, i) => n + ':' + stuecke[i].length).join(' '));
    bilanz(); clearTimeout(wachhund); process.exit(2);
}
check('alle sieben Funktionen liessen sich schneiden', true);

/* ⚠ Modulvariablen fallen aus jedem Funktions-Schnitt heraus – ohne diese
 * Deklarationen bricht der Lauf mit einem nackten ReferenceError ab. */
const prolog = `
var _sessions = [], _activeSid = null, _selMode = false, _selIds = new Set();
var gewechselt = [], toasts = [], wiederhergestellt = 0;
var $ = function (id) { return document.getElementById(id); };
function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function _csHeaders(h) { return h || {}; }
function _sidKey() { return 'jarvis_chat_sid_pruef'; }
function _switchSession(id) { gewechselt.push(id); }
function _renameSession(s) {}
function _openSessionPrompt(s) {}
function _deleteSession(s) {}
function showToast(m) { toasts.push(m); }
function _updateContextIndicator() {}
async function _restoreHistory() { wiederhergestellt++; }
async function _csCreate(t) {
    var r = await fetch('/api/chat/sessions', { method: 'POST', headers: {}, body: JSON.stringify({ title: t || '' }) });
    var d = await r.json(); return d && d.session;
}
`;
const epilog = `
window.__h = {
    setzeSessions: function (l, aktiv) { _sessions = l.slice(); _activeSid = aktiv || null; },
    render: _renderSidebar, modus: _selModus, alle: _selAlle, loeschen: _deleteSelected,
    sessions: function () { return _sessions.map(function (s) { return s.id; }); },
    aktiv: function () { return _activeSid; },
    auswahl: function () { return Array.from(_selIds); },
    imModus: function () { return _selMode; },
    gewechselt: gewechselt, toasts: toasts
};
`;
win.eval(prolog + stuecke.join('\n') + epilog);
const H = win.__h;
const zeilen = () => Array.from(doc.querySelectorAll('#cs-list .cs-item'));

const S = [
    { id: 'aaa111', title: 'Erster Chat' },
    { id: 'bbb222', title: 'Zweiter Chat' },
    { id: 'ccc333', title: 'Dritter Chat' }
];
H.setzeSessions(S, 'aaa111');
H.render();
check('drei Chats gezeichnet (der Loeschfall braucht mehr als einen)',
      zeilen().length === 3, 'gefunden: ' + zeilen().length);

// ── 3. Normalzustand ────────────────────────────────────────────────────────
section('3. Normalzustand: die Leiste sieht aus wie bisher');
const bar = doc.getElementById('cs-tools');
const um = doc.getElementById('cs-selmode');
const delBtn = doc.getElementById('cs-seldel');

check('die Werkzeugzeile ist sichtbar, sobald es Chats gibt', bar.hidden === false);
check('Loeschknopf und "Alle" bleiben verborgen',
      delBtn.hidden === true && doc.getElementById('cs-all-wrap').hidden === true);
check('kein Kaestchen an den Zeilen', doc.querySelectorAll('#cs-list .cs-check').length === 0);
check('die Aktionsknoepfe je Zeile sind unveraendert da (Prompt/Umbenennen/Loeschen)',
      zeilen().every(z => z.querySelector('.cs-prompt') && z.querySelector('.cs-ren')
                          && z.querySelector('.cs-del')));
check('der Umschalter traegt echten Text, keinen Schluessel',
      um.textContent.trim().length > 2 && um.textContent.indexOf('chat.') !== 0,
      um.textContent);
const textAus = um.textContent.trim();

// ── 4. Auswahlmodus ─────────────────────────────────────────────────────────
section('4. Auswahlmodus: Kaestchen statt Aktionsknoepfe');
um.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
// Der Knopf ist noch nicht verdrahtet (das tut init()), also den Schnitt rufen.
H.modus(true);

check('jede Zeile hat jetzt ein Kaestchen',
      doc.querySelectorAll('#cs-list .cs-check').length === 3);
check('⚠ die Aktionsknoepfe je Zeile sind WEG (kein zweideutiger Muelleimer)',
      doc.querySelectorAll('#cs-list .cs-del').length === 0
      && doc.querySelectorAll('#cs-list .cs-ren').length === 0);
check('der Umschalter hat seine BESCHRIFTUNG gewechselt',
      um.textContent.trim() !== textAus && um.textContent.trim().length > 2,
      textAus + ' -> ' + um.textContent.trim());
check('und den i18n-Schluessel mit (sonst faellt er beim Sprachwechsel zurueck)',
      um.getAttribute('data-i18n') === 'chat.select_cancel',
      um.getAttribute('data-i18n'));
check('"Alle" und der Loeschknopf sind sichtbar',
      delBtn.hidden === false && doc.getElementById('cs-all-wrap').hidden === false);
check('⚠ der Loeschknopf ist bei LEERER Auswahl gesperrt', delBtn.disabled === true);
check('er traegt den Muelleimer (Muelleimer = loeschen)',
      !!delBtn.querySelector('#cs-seldel-ico svg.jv-ico-trash, #cs-seldel-ico svg'),
      delBtn.innerHTML.slice(0, 80));
check('die Zahl der Auswahl steht IM Knopf', /0/.test(delBtn.textContent),
      delBtn.textContent.trim());

// ── 5. Auswaehlen ───────────────────────────────────────────────────────────
section('5. Auswaehlen: Klick auf die Zeile und auf das Kaestchen');
zeilen()[0].querySelector('.cs-check').click();          // Kaestchen direkt
check('Kaestchen-Klick waehlt genau diese Sitzung',
      JSON.stringify(H.auswahl()) === JSON.stringify(['aaa111']), JSON.stringify(H.auswahl()));
check('⚠ er hat NICHT zusaetzlich die Sitzung gewechselt',
      H.gewechselt.length === 0, JSON.stringify(H.gewechselt));

// Klick auf die ZEILE (nicht auf das Kaestchen)
zeilen()[2].querySelector('.cs-title').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
check('Klick auf die Zeile waehlt dazu, statt zu wechseln',
      H.auswahl().length === 2 && H.auswahl().indexOf('ccc333') >= 0
      && H.gewechselt.length === 0, JSON.stringify(H.auswahl()));
check('die Zahl am Knopf zaehlt mit und der Knopf ist frei',
      /2/.test(delBtn.textContent) && delBtn.disabled === false, delBtn.textContent.trim());
check('die gewaehlten Zeilen sind auch OHNE Mauszeiger erkennbar',
      zeilen()[0].classList.contains('cs-picked')
      && zeilen()[2].classList.contains('cs-picked')
      && !zeilen()[1].classList.contains('cs-picked'));
const alleBox = doc.getElementById('cs-all');
check('"Alle" steht auf teilweise (2 von 3)',
      alleBox.indeterminate === true && alleBox.checked === false);

// Abwaehlen
zeilen()[0].querySelector('.cs-check').click();
check('nochmal klicken waehlt wieder ab',
      JSON.stringify(H.auswahl()) === JSON.stringify(['ccc333']), JSON.stringify(H.auswahl()));

H.alle(true);
check('"Alle" waehlt alle drei', H.auswahl().length === 3 && alleBox.checked === true);

/* ⚠ Eine Liste, die zwischendurch nachgezogen wird (Antwort-Routing zeichnet
 * die Leiste neu), kann eine gewaehlte Sitzung verlieren. Bleibt die Id in der
 * Auswahl, behauptet die Zahl am Knopf eine Auswahl, die die Liste nicht zeigt
 * – und sie ginge beim Loeschen mit an den Server. */
H.setzeSessions([S[0], S[2]], 'aaa111');
H.render();
check('⚠ eine verschwundene Sitzung faellt aus der Auswahl',
      H.auswahl().length === 2 && H.auswahl().indexOf('bbb222') < 0, JSON.stringify(H.auswahl()));
check('und die Zahl am Knopf zaehlt sie nicht mehr mit',
      /2/.test(delBtn.textContent), delBtn.textContent.trim());

H.setzeSessions(S, 'aaa111');
H.render();
H.alle(false);
check('"Alle" abwaehlen leert die Auswahl',
      H.auswahl().length === 0 && alleBox.checked === false && delBtn.disabled === true);

// ── 6. Rueckfrage ───────────────────────────────────────────────────────────
section('6. Rueckfrage: ohne Bestaetigung geht nichts an den Server');
H.alle(true);
let gefragt = null;
win.confirm = (m) => { gefragt = m; return false; };
const vorher = rufe.length;
await H.loeschen();
check('es wurde gefragt, und die Frage nennt die ANZAHL',
      typeof gefragt === 'string' && /3/.test(gefragt) && gefragt.indexOf('chat.') !== 0, gefragt);
check('⚠ nach "Abbrechen" ging KEINE Anfrage raus', rufe.length === vorher);
check('und die Liste steht unveraendert', H.sessions().length === 3);

// ── 7. Loeschen: EIN Aufruf, genau die gewaehlten Ids ───────────────────────
section('7. Loeschen: ein Sammel-Aufruf mit genau den gewaehlten Ids');
win.confirm = () => true;
H.modus(true);
zeilen()[1].querySelector('.cs-check').click();   // bbb222
zeilen()[2].querySelector('.cs-check').click();   // ccc333
rufe.length = 0;
antwort = (ids) => ({ ok: true, deleted: ids.slice(), failed: [] });
await H.loeschen();

const posts = rufe.filter(r => r.pfad === '/api/chat/sessions/delete');
check('genau EIN Aufruf an den Sammel-Endpunkt (nicht einer je Chat)',
      posts.length === 1, rufe.map(r => r.method + ' ' + r.pfad).join(' | '));
check('er geht per POST mit einer Id-LISTE',
      posts.length === 1 && posts[0].method === 'POST' && Array.isArray(posts[0].body.ids));
check('⚠ es gehen GENAU die gewaehlten Ids mit – nicht mehr',
      posts.length === 1
      && JSON.stringify(posts[0].body.ids.slice().sort()) === JSON.stringify(['bbb222', 'ccc333']),
      posts.length ? JSON.stringify(posts[0].body.ids) : '');
check('kein einzelner DELETE daneben',
      !rufe.some(r => r.method === 'DELETE'));
check('die geloeschten Chats sind aus der Liste, der dritte steht noch',
      JSON.stringify(H.sessions()) === JSON.stringify(['aaa111']), JSON.stringify(H.sessions()));
check('die aktive Sitzung war nicht dabei und bleibt offen', H.aktiv() === 'aaa111');
check('der Auswahlmodus ist danach beendet und die Auswahl leer',
      H.imModus() === false && H.auswahl().length === 0);
check('es gab eine Rueckmeldung mit der Anzahl',
      H.toasts.some(t => /2/.test(t)), JSON.stringify(H.toasts));

// ── 8. Teilfehlschlag ───────────────────────────────────────────────────────
section('8. Teilfehlschlag: nur was WEG ist, verschwindet aus der Liste');
H.setzeSessions(S, 'aaa111');
H.modus(true);
H.alle(true);
H.toasts.length = 0;
rufe.length = 0;
// Der Server meldet: eines geloescht, zwei nicht.
antwort = () => ({ ok: false, deleted: ['bbb222'], failed: ['aaa111', 'ccc333'] });
await H.loeschen();
check('⚠ nur die vom Server BENANNTEN Ids fallen aus der Liste',
      JSON.stringify(H.sessions().slice().sort()) === JSON.stringify(['aaa111', 'ccc333']),
      JSON.stringify(H.sessions()));
check('der Fehlschlag bleibt nicht still',
      H.toasts.some(t => /2/.test(t) && t.indexOf('chat.') !== 0), JSON.stringify(H.toasts));

// ── 9. Aktive Sitzung mitgeloescht ──────────────────────────────────────────
section('9. Die AKTIVE Sitzung ist dabei');
H.setzeSessions(S, 'bbb222');
H.modus(true);
zeilen()[1].querySelector('.cs-check').click();   // bbb222 = die aktive
rufe.length = 0;
antwort = (ids) => ({ ok: true, deleted: ids.slice(), failed: [] });
await H.loeschen();
check('eine andere Sitzung wird aktiv (kein Chat ohne session_id)',
      H.aktiv() === 'aaa111', String(H.aktiv()));
check('und ihr Verlauf wird geladen', win.eval('wiederhergestellt') > 0);

// Alle drei weg -> es muss eine neue entstehen
H.setzeSessions(S, 'aaa111');
H.modus(true);
H.alle(true);
rufe.length = 0;
await H.loeschen();
check('sind ALLE weg, entsteht eine neue Sitzung',
      H.aktiv() === 'neu999' && H.sessions().length === 1, String(H.aktiv()));
check('die Werkzeugzeile ist dabei nicht haengen geblieben',
      H.imModus() === false && bar.hidden === false);

// ── 10. Texte in beiden Sprachen ────────────────────────────────────────────
section('10. i18n: die Schluessel gibt es in DE und EN');
const noetig = ['chat.select_many', 'chat.select_many_title', 'chat.select_cancel',
                'chat.select_cancel_title', 'chat.select_all', 'chat.delete_selected',
                'chat.delete_selected_title', 'chat.delete_many_confirm',
                'chat.delete_many_done', 'chat.delete_many_partial', 'chat.delete_many_failed'];
/* ⚠ NICHT ueber window.t() messen: das faellt bei einem fehlenden Schluessel
 * auf DEUTSCH zurueck. Ein englischer Benutzer saehe dann deutschen Text,
 * waehrend die Pruefung gruen ist – gefragt ist die TABELLE der Sprache. */
const tabellen = win.__i18n;
if (!tabellen || !tabellen.de || !tabellen.en) {
    check('die Sprachtabellen sind erreichbar (Positivkontrolle)', false);
} else {
    check('die Sprachtabellen sind erreichbar (Positivkontrolle)', true);
    ['de', 'en'].forEach(lang => {
        const tab = tabellen[lang];
        const fehlt = noetig.filter(k => !Object.prototype.hasOwnProperty.call(tab, k));
        check(lang.toUpperCase() + ': alle ' + noetig.length
              + ' Schluessel stehen in der eigenen Tabelle', fehlt.length === 0, fehlt.join(', '));
        const mitN = ['chat.delete_selected', 'chat.delete_many_confirm', 'chat.delete_many_done',
                      'chat.delete_many_partial'];
        const ohne = mitN.filter(k => String(tab[k] || '').indexOf('{n}') < 0);
        check(lang.toUpperCase() + ': die Zahl-Platzhalter sind erhalten', ohne.length === 0,
              ohne.join(', '));
    });
}
win.setLang('de');

bilanz();
clearTimeout(wachhund);
win.close();
process.exit(fail ? 1 : 0);

})();
