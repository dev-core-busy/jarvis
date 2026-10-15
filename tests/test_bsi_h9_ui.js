/* Waechter: Bestaetigungskarte im Chat (BSI H9) – Oberflaeche.
 *
 * Gemessen wird am ECHTEN frontend/js/bestaetigung.js mit dem ECHTEN i18n.js
 * in jsdom: die Karte entsteht, Argumente landen als TEXT (nicht als Markup –
 * sie koennen aus einer praeparierten Mail stammen), ein Klick sendet genau
 * eine Antwort, die Quittung des Servers hat das letzte Wort.
 *
 * Dazu als REGEL am Syntaxbaum (acorn) von chat.js: JEDE Task-Nachricht
 * (`type: 'task'`) sagt `bestaetigung: true` – sonst weist das Backend
 * Aussenwirkung fuer den Browser-Chat ab –, und die Nachrichtenweiche reicht
 * Anfrage und Quittung an das Modul weiter. Und: chat.html bindet das Modul ein.
 *
 *   node tests/test_bsi_h9_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

let ok = 0, fail = 0, _bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n── ' + t); }
function bilanz() {
    _bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
}
process.on('exit', function (code) {
    if (!_bilanz) {
        console.log('\nABBRUCH ohne Bilanz – ' + ok + ' OK, ' + fail + ' FAIL');
        if (code === 0) process.exitCode = 1;
    }
});

const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const MODUL = fs.readFileSync(path.join(ROOT, 'frontend/js/bestaetigung.js'), 'utf8');
const CHAT = fs.readFileSync(path.join(ROOT, 'frontend/js/chat.js'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'frontend/chat.html'), 'utf8');

function seite(lang) {
    const dom = new JSDOM('<!doctype html><html><body><div id="messages"></div></body></html>',
                          { runScripts: 'outside-only', url: 'https://beispiel.de/chat' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_lang', lang || 'de');
    w.eval(I18N);
    w._lang = lang || 'de';
    w.eval(MODUL);
    return w;
}

// ── 1. Karte ─────────────────────────────────────────────────────────────────
section('1. Karte entsteht, Argumente als Text');
let w = seite('de');
check('Positivkontrolle: Modul geladen', !!(w.JarvisBestaetigung && w.JarvisBestaetigung.anfrage));
check('Positivkontrolle: echtes i18n geladen', typeof w.t === 'function'
      && w.t('bestaetigung.titel') === 'Bestätigung erforderlich', w.t && w.t('bestaetigung.titel'));

const gesendet = [];
let gescrollt = 0;
const box = w.document.getElementById('messages');
const ANGRIFF = '<img src=x onerror="window.__xss=1"><b>fett</b>';
const row = w.JarvisBestaetigung.anfrage({
    type: 'bestaetigung_anfrage', id: 'k1', werkzeug: 'email_senden', klasse: 'aussen',
    argumente: [['an', 'a@beispiel.de'], ['text', ANGRIFF]], frist_s: 300,
}, { container: box, senden: function (o) { gesendet.push(o); }, scroll: function () { gescrollt++; } });
check('Karte steht im Verlauf', !!row && box.contains(row));
const karte = box.querySelector('.jv-best');
check('Klasse der Karte nach Wirkung', karte && karte.classList.contains('is-aussen'));
check('Titel aus i18n', karte && karte.querySelector('.jv-best-titel').textContent === 'Bestätigung erforderlich');
check('Wirkung im Klartext (nicht der Werkzeugname)',
      karte && karte.querySelector('.jv-best-aktion').textContent === 'E-Mail senden',
      karte && karte.querySelector('.jv-best-aktion').textContent);
check('Klassentext nennt die Aussenwirkung',
      karte && /nach außen/.test(karte.querySelector('.jv-best-klasse').textContent));
const dds = karte ? karte.querySelectorAll('dd') : [];
check('Argumente vollstaendig gelistet', dds.length === 2);
check('Argument mit Markup erscheint als TEXT', dds[1] && dds[1].textContent === ANGRIFF);
check('kein eingeschleustes Element in der Karte',
      karte && !karte.querySelector('img') && !karte.querySelector('b'));
check('Frist im Hinweis eingesetzt ({min} ersetzt)',
      karte && /5 Minuten/.test(karte.querySelector('.jv-best-hinweis').textContent)
      && !/\{min\}/.test(karte.querySelector('.jv-best-hinweis').textContent));
check('gescrollt', gescrollt === 1);
const knoepfe = karte ? karte.querySelectorAll('.jv-best-knoepfe button') : [];
check('zwei Knoepfe: Ausfuehren, Ablehnen',
      knoepfe.length === 2 && knoepfe[0].textContent === 'Ausführen' && knoepfe[1].textContent === 'Ablehnen');
check('Karte traegt KEIN data-agent-id (immer sichtbar)', row && !row.dataset.agentId);

// ── 2. Klick ─────────────────────────────────────────────────────────────────
section('2. Klick sendet genau eine Antwort');
knoepfe[0].click();
knoepfe[0].click();
knoepfe[1].click();
check('genau EINE Antwort gesendet', gesendet.length === 1, JSON.stringify(gesendet));
check('Antwort: Typ, Kennung, erlaubt=true',
      gesendet[0] && gesendet[0].type === 'bestaetigung_antwort' && gesendet[0].id === 'k1'
      && gesendet[0].erlaubt === true, JSON.stringify(gesendet[0]));
check('Knoepfe danach gesperrt', knoepfe[0].disabled && knoepfe[1].disabled);
check('Status sagt, was passiert', /Freigegeben/.test(karte.querySelector('.jv-best-status').textContent));

w.JarvisBestaetigung.erledigt({ type: 'bestaetigung_erledigt', id: 'k1', grund: 'erlaubt' });
check('Quittung schliesst die Karte', karte.classList.contains('is-erledigt'));

// Ablehnen + Frist dazwischen: der Server hat das letzte Wort
const g2 = [];
w.JarvisBestaetigung.anfrage({ id: 'k2', werkzeug: 'email_loeschen', klasse: 'loeschen',
    argumente: [['mail_id', '7']] }, { container: box, senden: function (o) { g2.push(o); } });
const k2 = box.querySelector('[data-best-id="k2"]');
check('Loeschen-Karte mit eigener Klasse', k2 && k2.classList.contains('is-loeschen'));
k2.querySelectorAll('button')[1].click();
check('Ablehnen sendet erlaubt=false', g2.length === 1 && g2[0].erlaubt === false, JSON.stringify(g2));
w.JarvisBestaetigung.erledigt({ id: 'k2', grund: 'frist' });
check('Quittung "frist" ueberschreibt den Klick-Status',
      /Keine Antwort/.test(k2.querySelector('.jv-best-status').textContent),
      k2.querySelector('.jv-best-status').textContent);

// Stop ohne Klick
w.JarvisBestaetigung.anfrage({ id: 'k3', werkzeug: 'shell_execute', klasse: 'shell',
    argumente: [['command', 'rm -rf /srv/x']] }, { container: box, senden: function () {} });
const k3 = box.querySelector('[data-best-id="k3"]');
w.JarvisBestaetigung.erledigt({ id: 'k3', grund: 'abgebrochen' });
check('Stop ohne Klick: Karte gesperrt, Status "Abgebrochen"',
      k3.querySelector('button').disabled && /Abgebrochen/.test(k3.querySelector('.jv-best-status').textContent));

// Unbekannte Klasse -> wie Aussenwirkung, doppelte Zustellung -> eine Karte
w.JarvisBestaetigung.anfrage({ id: 'k4', werkzeug: 'x', klasse: '<script>' },
                              { container: box, senden: function () {} });
w.JarvisBestaetigung.anfrage({ id: 'k4', werkzeug: 'x', klasse: 'aussen' },
                              { container: box, senden: function () {} });
check('unbekannte Klasse wird als Aussenwirkung gezeigt',
      box.querySelector('[data-best-id="k4"]').classList.contains('is-aussen'));
check('doppelt zugestellte Anfrage erzeugt EINE Karte',
      box.querySelectorAll('[data-best-id="k4"]').length === 1);
check('unbekanntes Werkzeug: Name statt leerem Feld',
      box.querySelector('[data-best-id="k4"] .jv-best-aktion').textContent === 'x');

// Englisch
const we = seite('en');
const be = we.document.getElementById('messages');
we.JarvisBestaetigung.anfrage({ id: 'e1', werkzeug: 'email_senden', klasse: 'aussen', argumente: [] },
                              { container: be, senden: function () {} });
check('englische Texte vorhanden',
      be.querySelector('.jv-best-titel').textContent === 'Confirmation required'
      && be.querySelector('.jv-best-aktion').textContent === 'Send email',
      be.querySelector('.jv-best-titel').textContent);

// ── 2b. Antwort nicht gesendet (Code-Review 2026-10-07) ─────────────────────
// wsSend kehrte bei geschlossenem WebSocket STILL zurueck; die Karte meldete
// "Freigegeben – wird ausgefuehrt", obwohl der Server nie etwas bekam.
section('2b. Nicht gesendete Antwort wird gemeldet, Karte bleibt bedienbar');
{
    const wn = seite('de');
    const bn = wn.document.getElementById('messages');
    let versuche = 0;
    wn.JarvisBestaetigung.anfrage({ id: 'n1', werkzeug: 'email_senden', klasse: 'aussen', argumente: [] },
                                  { container: bn, senden: function () { versuche++; return false; } });
    const kn = bn.querySelector('[data-best-id="n1"]');
    kn.querySelector('.jv-best-ja').click();
    const st = kn.querySelector('.jv-best-status').textContent;
    check('senden() == false: Status sagt "nicht gesendet"',
          st === wn.t('bestaetigung.status.nicht_gesendet'), st);
    check('… und NICHT "Freigegeben"', st.indexOf('Freigegeben') === -1, st);
    check('… Knoepfe wieder frei, Zustand offen',
          !kn.querySelector('.jv-best-ja').disabled && !kn.querySelector('.jv-best-nein').disabled
          && kn.dataset.zustand === 'offen', kn.dataset.zustand);
    kn.querySelector('.jv-best-ja').click();
    check('… ein zweiter Versuch ist moeglich', versuche === 2, String(versuche));

    wn.JarvisBestaetigung.anfrage({ id: 'n2', werkzeug: 'email_senden', klasse: 'aussen', argumente: [] },
                                  { container: bn, senden: function () { throw new Error('zu'); } });
    const kw = bn.querySelector('[data-best-id="n2"]');
    kw.querySelector('.jv-best-nein').click();
    check('senden() wirft: ebenfalls "nicht gesendet" und bedienbar',
          kw.querySelector('.jv-best-status').textContent === wn.t('bestaetigung.status.nicht_gesendet')
          && !kw.querySelector('.jv-best-nein').disabled);

    // Positivkontrolle: undefined (Altvertrag) und true zaehlen als gesendet
    wn.JarvisBestaetigung.anfrage({ id: 'n3', werkzeug: 'email_senden', klasse: 'aussen', argumente: [] },
                                  { container: bn, senden: function () { return true; } });
    const kt = bn.querySelector('[data-best-id="n3"]');
    kt.querySelector('.jv-best-ja').click();
    check('Positivkontrolle: senden() == true -> "Freigegeben", Knoepfe gesperrt',
          kt.querySelector('.jv-best-status').textContent === wn.t('bestaetigung.status.erlaubt')
          && kt.querySelector('.jv-best-ja').disabled);

    // Das ECHTE wsSend aus chat.js, am Syntaxbaum geschnitten und ausgefuehrt
    const bm = acorn.parse(CHAT, { ecmaVersion: 'latest', sourceType: 'script' });
    let fn = null;
    (function such(n) {
        if (fn || !n || typeof n.type !== 'string') return;
        if (n.type === 'FunctionDeclaration' && n.id && n.id.name === 'wsSend') { fn = n; return; }
        for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(such); else if (v && typeof v.type === 'string') such(v); }
    })(bm);
    check('Positivkontrolle: wsSend in chat.js gefunden', !!fn);
    if (fn) {
        const quelle = CHAT.slice(fn.start, fn.end);
        const bau = new Function('ws', 'token', quelle + '; return wsSend;');
        const raus = [];
        const offen = { readyState: 1, send: function (x) { raus.push(x); } };
        check('wsSend bei geschlossenem Socket -> false',
              bau({ readyState: 3, send: function () { raus.push('x'); } }, 't')({ a: 1 }) === false && raus.length === 0);
        check('wsSend ohne Socket -> false', bau(null, 't')({ a: 1 }) === false);
        check('wsSend bei offenem Socket -> true und gesendet',
              bau(offen, 't')({ a: 1 }) === true && raus.length === 1);
    }
}

// ── 3. i18n vollstaendig ────────────────────────────────────────────────────
section('3. Jeder Schluessel des Moduls existiert in DE und EN');
const schluessel = new Set();
(MODUL.match(/'bestaetigung\.[a-z_.]+'/g) || []).forEach(function (s) {
    // Praefixe ('bestaetigung.wz.') werden im Modul zusammengesetzt – kein Schluessel.
    if (!s.endsWith(".'")) schluessel.add(s.slice(1, -1));
});
// Jedes eingestufte Werkzeug hat einen Klartext (Wirkung statt Technik) – die
// Liste kommt aus der Tabelle in backend/wirkung.py, nicht von Hand.
const WIRKUNG = fs.readFileSync(path.join(ROOT, 'backend/wirkung.py'), 'utf8');
const tab = (WIRKUNG.split('TABELLE: dict')[1] || '').split('\n}\n')[0] || '';
const tabNamen = (tab.match(/^    "([a-z_]+)":/gm) || []).map(function (z) { return z.trim().slice(1, -2); });
check('Positivkontrolle: Tabelle aus wirkung.py gelesen (' + tabNamen.length + ')', tabNamen.length >= 15);
tabNamen.concat(['shell_execute']).forEach(function (n) { schluessel.add('bestaetigung.wz.' + n); });
['aussen', 'loeschen', 'shell', 'zeitplan'].forEach(function (k) { schluessel.add('bestaetigung.klasse.' + k); });
['erlaubt', 'abgelehnt', 'frist', 'abgebrochen', 'nicht_gesendet']
    .forEach(function (k) { schluessel.add('bestaetigung.status.' + k); });
check('Positivkontrolle: Schluessel gesammelt (' + schluessel.size + ')', schluessel.size >= 12);
const de = w._I18N || null;
schluessel.forEach(function (k) {
    w._lang = 'de'; const vde = w.t(k);
    we._lang = 'en'; const ven = we.t(k);
    check(k + ' DE/EN', vde !== k && ven !== k && vde !== ven, vde + ' | ' + ven);
});

// ── 4. chat.js-Regeln am Syntaxbaum ─────────────────────────────────────────
section('4. chat.js: Task-Nachrichten und Weiche (Syntaxbaum)');
const baum = acorn.parse(CHAT, { ecmaVersion: 'latest', sourceType: 'script' });
const objekte = [];
const faelle = {};
(function lauf(n) {
    if (!n || typeof n.type !== 'string') return;
    if (n.type === 'ObjectExpression') objekte.push(n);
    if (n.type === 'SwitchCase' && n.test && n.test.type === 'Literal') faelle[n.test.value] = n;
    for (const k in n) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(lauf);
        else if (v && typeof v.type === 'string') lauf(v);
    }
})(baum);
function prop(o, name) {
    return o.properties.find(function (p) {
        return p.type === 'Property' && ((p.key.type === 'Identifier' && p.key.name === name)
            || (p.key.type === 'Literal' && p.key.value === name));
    });
}
const tasks = objekte.filter(function (o) {
    const t = prop(o, 'type'); return t && t.value.type === 'Literal' && t.value.value === 'task';
});
check('Positivkontrolle: Task-Nachrichten gefunden (' + tasks.length + ')', tasks.length >= 2);
tasks.forEach(function (o) {
    const b = prop(o, 'bestaetigung');
    check('Task-Nachricht ab Zeichen ' + o.start + ' sagt bestaetigung: true',
          b && b.value.type === 'Literal' && b.value.value === true);
});
function quelle(n) { return n ? CHAT.slice(n.start, n.end) : ''; }
const fa = faelle['bestaetigung_anfrage'];
check('Weiche kennt bestaetigung_anfrage', !!fa);
check('Anfrage geht an JarvisBestaetigung.anfrage mit messagesEl und wsSend',
      /JarvisBestaetigung\.anfrage\(\s*msg\s*,/.test(quelle(fa))
      && /container:\s*messagesEl/.test(quelle(fa)) && /senden:\s*wsSend/.test(quelle(fa)), quelle(fa));
check('ohne Modul wird ABGELEHNT, nicht gewartet',
      /erlaubt:\s*false/.test(quelle(fa)) && !/erlaubt:\s*true/.test(quelle(fa)));
const fe = faelle['bestaetigung_erledigt'];
check('Weiche kennt bestaetigung_erledigt und reicht weiter',
      !!fe && /JarvisBestaetigung\.erledigt\(\s*msg\s*\)/.test(quelle(fe)));

// ── 5. Einbindung ───────────────────────────────────────────────────────────
section('5. chat.html bindet das Modul ein');
const iMod = HTML.indexOf('/static/js/bestaetigung.js?v=');
const iChat = HTML.indexOf('/static/js/chat.js?v=');
check('bestaetigung.js mit Cache-Buster eingebunden', iMod >= 0);
check('vor chat.js (Modul steht bereit, bevor Nachrichten kommen)', iMod >= 0 && iChat > iMod);

bilanz();
w.close(); we.close();
process.exit(fail === 0 ? 0 : 1);
