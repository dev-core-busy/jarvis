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

const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
const SITZUNG = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');

/**
 * Probeseite. ⚠ `icons.js` und `sitzung.js` werden ECHT geladen, nicht
 * nachgestellt: eine Teil-Attrappe von `JarvisIcons` stirbt am naechsten
 * Symbol, und eine Attrappe von `JarvisSitzung` prueft die eigene Annahme
 * statt des Transportwegs (beides im Register bezahlt).
 *
 * `antworten`: Attrappe fuer die Adressbuch-Abfrage. OHNE sie ginge `fetch`
 * ins echte Netz, landete im `catch`, und der Pruefstand messe eine Kette, die
 * nie stattgefunden hat – jsdom hat ein eigenes `fetch`.
 */
function seite(lang, antworten) {
    const dom = new JSDOM('<!doctype html><html><body><div id="messages"></div></body></html>',
                          { runScripts: 'outside-only', url: 'https://beispiel.de/chat' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_lang', lang || 'de');
    w.localStorage.setItem('jarvis_token', 'tok-probe');
    w.eval(I18N);
    w._lang = lang || 'de';
    w.eval(ICONS);
    w.eval(SITZUNG);
    w.__abrufe = [];
    w.fetch = function (url, opt) {
        w.__abrufe.push({ url: url, opt: opt });
        const n = w.__abrufe.length - 1;
        const a = (antworten || [])[n];
        if (a === undefined) {
            return Promise.resolve({ ok: true, json: function () {
                return Promise.resolve({ ok: true, treffer: [], hinweis: '' }); } });
        }
        if (a instanceof Error) return Promise.reject(a);
        return Promise.resolve({ ok: a.http !== false, json: function () {
            return Promise.resolve(a.body); } });
    };
    w.eval(MODUL);
    return w;
}

/** Wartet, bis Entprellung UND Promise-Kette durch sind. */
function warten(w, ms) {
    return new Promise(function (aufl) { w.setTimeout(aufl, ms === undefined ? 450 : ms); });
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

// ── 6. Korrigierbares Empfaengerfeld + Adressbuch ───────────────────────────
// Der gemeldete Fall: das Modell setzt "Max Mustermann" als Empfaenger ein.
// Gemessen wird die WIRKUNG an der echten Karte – entsteht ein Eingabefeld,
// loest die Suche auf, und steht die gewaehlte Adresse danach in der ANTWORT?
async function teil6() {
    section('6. Empfaengerfeld: Adressbuch und Korrektur');
    const TREFFER = {
        ok: true, quelle: 'ews', hinweis: '',
        treffer: [{ name: 'Max Mustermann', adresse: 'max.mustermann@beispiel.de', art: 'person' },
                  { name: 'Alle Mitarbeiter', adresse: 'alle@beispiel.de', art: 'verteiler' }]
    };
    const w6 = seite('de', [{ body: TREFFER }]);
    const b6 = w6.document.getElementById('messages');
    const g6 = [];
    w6.JarvisBestaetigung.anfrage({
        id: 'f1', werkzeug: 'email_senden', klasse: 'aussen',
        argumente: [['an', 'Max Mustermann'], ['betreff', 'Angebot'], ['text', 'Hallo']],
        aenderbar: ['an'], frist_s: 300
    }, { container: b6, senden: function (o) { g6.push(o); return true; } });
    const k6 = b6.querySelector('[data-best-id="f1"]');

    // ⚠ EXIT 2 NUR, WENN DER MESSAUFBAU NICHT LAUFEN KANN – nicht, wenn sich
    // das Produkt geaendert hat. Die erste Fassung brach hier ab, sobald kein
    // Eingabefeld entstand; genau das stellen VIER Gegenproben her
    // ("aenderbar ignoriert", "Korrektur nicht gesendet", "Vorschlag nicht
    // gezeigt", "Feld bleibt tippbar"). Alle vier meldeten damit "konnte nicht
    // laufen" statt eines Bisses – und das ist von "bestanden" nicht zu
    // unterscheiden. Nicht messen kann der Aufbau nur ohne Modul oder Karte.
    if (!w6.JarvisBestaetigung || !k6) {
        console.log('ABBRUCH: Modul oder Karte fehlt – Abschnitt 6 kann nichts messen');
        bilanz();
        process.exit(2);
    }
    // Ab hier ist JEDE Pruefung gegen ein fehlendes Element abgesichert: ein
    // Zugriff auf `.textContent` von `null` WIRFT, und ein Wurf landet im
    // catch() am Ende – also wieder in Exit 2 statt in einem FAIL (Register:
    // kein unabgesicherter Zugriff in einer Pruefung).
    const txt = function (sel, wurzel) {
        const el = (wurzel || k6).querySelector(sel);
        return el ? el.textContent : null;
    };
    const inp = k6.querySelector('.jv-best-feld');
    check('Positivkontrolle: fuer ein aenderbares Feld entsteht eine Eingabe', !!inp);
    check('die Eingabe ist mit dem Vorschlag des Modells vorbelegt',
          !!inp && inp.value === 'Max Mustermann', inp ? inp.value : 'kein Feld');
    check('der Vorschlag des Modells bleibt als Text lesbar',
          /Max Mustermann/.test(txt('.jv-best-vorschlag-war') || ''),
          String(txt('.jv-best-vorschlag-war')));
    // Genau EIN Feld: `betreff` und `text` stehen nicht in `aenderbar`.
    check('nur das freigegebene Feld ist aenderbar (betreff/text nicht)',
          k6.querySelectorAll('.jv-best-feld').length === 1,
          String(k6.querySelectorAll('.jv-best-feld').length));
    check('ein Symbol aus icons.js am Adressbuch-Knopf (kein Emoji)',
          !!k6.querySelector('.jv-best-ab svg'));

    // Die Karte fragt von selbst, weil der Wert offensichtlich keine Adresse ist
    await warten(w6);
    check('ein Wert ohne @ loest die Adressbuch-Suche von selbst aus',
          w6.__abrufe.length === 1, JSON.stringify(w6.__abrufe.map(function (a) { return a.url; })));
    const abruf = w6.__abrufe[0] || {};
    check('gefragt wird /api/email/adressbuch', abruf.url === '/api/email/adressbuch', abruf.url);
    check('mit dem Sitzungstoken im Kopfsatz',
          !!(abruf.opt && abruf.opt.headers
             && abruf.opt.headers['Authorization'] === 'Bearer tok-probe'),
          JSON.stringify(abruf.opt && abruf.opt.headers));
    check('die Frage steht im Koerper',
          !!(abruf.opt && JSON.parse(abruf.opt.body).q === 'Max Mustermann'),
          abruf.opt && abruf.opt.body);

    const vor = k6.querySelectorAll('.jv-best-vorschlag');
    check('beide Treffer werden angeboten', vor.length === 2, String(vor.length));
    check('Name und Adresse stehen am Vorschlag',
          vor[0] && /Max Mustermann/.test(vor[0].textContent)
          && /max\.mustermann@beispiel\.de/.test(vor[0].textContent), vor[0] && vor[0].textContent);
    check('ein Verteiler wird als solcher benannt',
          vor[1] && /Verteiler/.test(vor[1].textContent), vor[1] && vor[1].textContent);

    if (vor[0]) vor[0].click();
    check('ein Klick auf den Vorschlag setzt die Adresse ein',
          !!inp && inp.value === 'max.mustermann@beispiel.de',
          inp ? inp.value : 'kein Feld');
    check('die Vorschlagsliste ist danach leer',
          k6.querySelectorAll('.jv-best-vorschlag').length === 0);

    const ja6 = k6.querySelector('.jv-best-ja');
    if (ja6) ja6.click();
    check('genau eine Antwort', g6.length === 1, JSON.stringify(g6));
    check('die Antwort traegt die KORRIGIERTE Adresse',
          !!(g6[0] && g6[0].aenderungen
             && g6[0].aenderungen.an === 'max.mustermann@beispiel.de'),
          JSON.stringify(g6[0]));
    // `Object.keys(undefined)` WIRFT – deshalb erst die Anwesenheit pruefen.
    check('und nur das geaenderte Feld',
          !!(g6[0] && g6[0].aenderungen
             && Object.keys(g6[0].aenderungen).length === 1),
          JSON.stringify(g6[0] && g6[0].aenderungen));
    check('aus der Eingabe wird danach Text (nichts mehr zu tippen)',
          !k6.querySelector('.jv-best-feld') && !!k6.querySelector('.jv-best-feldfest'));
    check('der festgeschriebene Wert ist der gesendete',
          txt('.jv-best-feldfest') === 'max.mustermann@beispiel.de',
          String(txt('.jv-best-feldfest')));

    // ── 6a2. Herkunft der Adresse ist SICHTBAR ─────────────────────────────
    // Eine uebernommene und eine aufgeloeste Adresse sehen am Feld gleich aus
    // (beide mit "@"). Der Benutzer muss den Unterschied sehen, BEVOR er
    // klickt – die uebernommene war der Fall, der an den Falschen ging.
    {
        const wu = seite('de', [{ body: { ok: true, treffer: [] } }]);
        const bu = wu.document.getElementById('messages');
        wu.JarvisBestaetigung.anfrage({
            id: 'h1', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'alt@beispiel.de']], aenderbar: ['an'],
            herkunft: { an: 'uebernommen' }
        }, { container: bu, senden: function () { return true; } });
        const ku = bu.querySelector('[data-best-id="h1"]');
        const hu = ku.querySelector('.jv-best-herkunft');
        check('eine UEBERNOMMENE Adresse wird in der Karte benannt', !!hu);
        check('… und als nicht geprueft gekennzeichnet',
              !!hu && hu.classList.contains('is-uebernommen'));
        check('… der Text nennt das Adressbuch und fordert zum Nachsehen auf',
              !!hu && /Adressbuch/.test(hu.textContent)
              && /nachsehen|verify/i.test(hu.textContent),
              hu ? hu.textContent : 'keine Zeile');
        wu.close();

        const wa = seite('de', [{ body: { ok: true, treffer: [] } }]);
        const ba = wa.document.getElementById('messages');
        wa.JarvisBestaetigung.anfrage({
            id: 'h2', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'neu@beispiel.de']], aenderbar: ['an'],
            herkunft: { an: 'aufgeloest' }
        }, { container: ba, senden: function () { return true; } });
        const ha = ba.querySelector('[data-best-id="h2"] .jv-best-herkunft');
        check('eine AUFGELOESTE Adresse wird als solche gezeigt',
              !!ha && ha.classList.contains('is-aufgeloest'),
              ha ? ha.className : 'keine Zeile');
        check('… und nicht als Warnung',
              !!ha && !ha.classList.contains('is-uebernommen'));
        wa.close();

        // 'unbekannt' behauptet NICHTS – eine Anzeige darf keinen Zustand
        // erfinden, den der Server nicht kennt.
        const wn2 = seite('de', [{ body: { ok: true, treffer: [] } }]);
        const bn2 = wn2.document.getElementById('messages');
        wn2.JarvisBestaetigung.anfrage({
            id: 'h3', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'x@beispiel.de']], aenderbar: ['an'],
            herkunft: { an: 'unbekannt' }
        }, { container: bn2, senden: function () { return true; } });
        check('bei UNBEKANNTER Herkunft steht keine Behauptung in der Karte',
              !bn2.querySelector('[data-best-id="h3"] .jv-best-herkunft'));
        // Und ohne das Feld ueberhaupt (alter Server): kein Absturz, keine Zeile
        const wo = seite('de', [{ body: { ok: true, treffer: [] } }]);
        const bo = wo.document.getElementById('messages');
        wo.JarvisBestaetigung.anfrage({
            id: 'h4', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'x@beispiel.de']], aenderbar: ['an']
        }, { container: bo, senden: function () { return true; } });
        check('ohne das Feld herkunft bleibt die Karte bedienbar',
              !!bo.querySelector('[data-best-id="h4"] .jv-best-feld')
              && !bo.querySelector('[data-best-id="h4"] .jv-best-herkunft'));
        wn2.close(); wo.close();
    }

    // ── 6b. OHNE KLICK AUF "AUSFUEHREN" GESCHIEHT NICHTS ───────────────────
    // Die Kernzusage von H9 – und die neuen Bedienelemente (Eingabefeld,
    // Adressbuch-Knopf, Vorschlaege) sind neue Flaeche, auf der ein
    // versehentliches Absenden entstehen koennte: ein Knopf ohne
    // type="button" in einem Formular, ein Enter im Feld, ein
    // Vorschlags-Klick, der durchreicht. Gemessen wird deshalb, dass NACH all
    // diesen Handlungen noch NICHTS gesendet wurde.
    {
        // ⚠ VIER Antworten, nicht eine: dieser Abschnitt loest MEHRERE
        // Abfragen aus (Auto-Suche beim Erscheinen, Tippen, Adressbuch-Knopf).
        // Mit nur einer Antwort beantwortet die Attrappe die spaeteren mit
        // einer LEEREN Liste – die loescht die Vorschlaege, und die
        // Positivkontrolle "ein Vorschlag steht zur Wahl" faellt an meinem
        // Messaufbau statt am Produkt (so im ersten Lauf passiert).
        const wz = seite('de', [{ body: TREFFER }, { body: TREFFER },
                                 { body: TREFFER }, { body: TREFFER }]);
        const bz = wz.document.getElementById('messages');
        const gz = [];
        wz.JarvisBestaetigung.anfrage({
            id: 'z1', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'Max Mustermann'], ['betreff', 'B'], ['text', 'T']],
            aenderbar: ['an']
        }, { container: bz, senden: function (o) { gz.push(o); return true; } });
        const kz = bz.querySelector('[data-best-id="z1"]');
        const fz = kz.querySelector('.jv-best-feld');
        check('Positivkontrolle: die Karte mit Feld steht', !!kz && !!fz);
        check('direkt nach dem Erscheinen der Karte: NICHTS gesendet',
              gz.length === 0, JSON.stringify(gz));

        // Tippen
        if (fz) {
            fz.value = 'Muster';
            fz.dispatchEvent(new wz.Event('input', { bubbles: true }));
        }
        check('nach dem Tippen im Empfaengerfeld: NICHTS gesendet',
              gz.length === 0, JSON.stringify(gz));

        // Enter im Feld (haeufigster Weg zu einem versehentlichen Absenden)
        if (fz) {
            fz.dispatchEvent(new wz.KeyboardEvent('keydown',
                { key: 'Enter', keyCode: 13, bubbles: true }));
            fz.dispatchEvent(new wz.KeyboardEvent('keyup',
                { key: 'Enter', keyCode: 13, bubbles: true }));
        }
        check('Enter im Empfaengerfeld sendet NICHTS',
              gz.length === 0, JSON.stringify(gz));

        // Adressbuch-Knopf
        const abz = kz.querySelector('.jv-best-ab');
        check('Positivkontrolle: der Adressbuch-Knopf ist da', !!abz);
        if (abz) abz.click();
        check('Klick auf den Adressbuch-Knopf sendet NICHTS',
              gz.length === 0, JSON.stringify(gz));
        // ⚠ Jeder Knopf in der Karte traegt type="button". Ohne das waere er
        // in einem Formular ein Absende-Knopf (die Karte steht heute in
        // keinem <form>, aber das ist eine Eigenschaft der Umgebung, nicht
        // der Karte – und Umgebungen aendern sich).
        const alleKnoepfe = kz.querySelectorAll('button');
        check('Positivkontrolle: es gibt Knoepfe in der Karte',
              alleKnoepfe.length >= 3, String(alleKnoepfe.length));
        let ohneTyp = 0;
        alleKnoepfe.forEach(function (b) { if (b.type !== 'button') ohneTyp++; });
        check('JEDER Knopf der Karte traegt type="button"', ohneTyp === 0,
              ohneTyp + ' von ' + alleKnoepfe.length + ' ohne');

        await warten(wz);
        check('nach der Adressbuch-Abfrage: NICHTS gesendet',
              gz.length === 0, JSON.stringify(gz));

        // Klick auf einen Vorschlag
        const vz = kz.querySelector('.jv-best-vorschlag');
        check('Positivkontrolle: ein Vorschlag steht zur Wahl', !!vz);
        if (vz) vz.click();
        check('Klick auf einen Vorschlag sendet NICHTS',
              gz.length === 0, JSON.stringify(gz));

        // Erst JETZT der bewusste Klick
        kz.querySelector('.jv-best-ja').click();
        check('erst der Klick auf "Ausfuehren" sendet – und genau einmal',
              gz.length === 1 && gz[0].erlaubt === true, JSON.stringify(gz));
        wz.close();
    }

    // Unveraendert freigeben: KEINE Korrektur im Paket (sonst stuende eine
    // Zeile im Journal, die nichts bewirkt hat).
    {
        const w2 = seite('de');
        const b2 = w2.document.getElementById('messages');
        const g2b = [];
        w2.JarvisBestaetigung.anfrage({
            id: 'f2', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'fest@beispiel.de']], aenderbar: ['an']
        }, { container: b2, senden: function (o) { g2b.push(o); return true; } });
        b2.querySelector('.jv-best-ja').click();
        check('unveraendert freigegeben: kein Feld aenderungen',
              g2b.length === 1 && g2b[0].aenderungen === undefined, JSON.stringify(g2b[0]));
        await warten(w2, 450);
        check('eine fertige Adresse loest KEINE Suche aus',
              w2.__abrufe.length === 0, String(w2.__abrufe.length));
        w2.close();
    }

    // ABLEHNEN mit getippter Korrektur: nichts mitschicken
    {
        const w3 = seite('de');
        const b3 = w3.document.getElementById('messages');
        const g3 = [];
        w3.JarvisBestaetigung.anfrage({
            id: 'f3', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'alt@beispiel.de']], aenderbar: ['an']
        }, { container: b3, senden: function (o) { g3.push(o); return true; } });
        const f3 = b3.querySelector('.jv-best-feld');
        check('Positivkontrolle: das Ablehnen-Feld ist da', !!f3);
        if (f3) f3.value = 'neu@beispiel.de';
        b3.querySelector('.jv-best-nein').click();
        check('bei Ablehnen wird keine Korrektur mitgeschickt',
              g3.length === 1 && g3[0].erlaubt === false && g3[0].aenderungen === undefined,
              JSON.stringify(g3[0]));
        w3.close();
    }

    // Ohne `aenderbar` bleibt die Karte, wie sie war – kein Feld, kein Abruf.
    {
        const w4 = seite('de');
        const b4 = w4.document.getElementById('messages');
        w4.JarvisBestaetigung.anfrage({
            id: 'f4', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'Max Mustermann']]
        }, { container: b4, senden: function () { return true; } });
        check('ohne Freigabe des Servers entsteht KEIN Eingabefeld',
              !b4.querySelector('.jv-best-feld'));
        await warten(w4, 450);
        check('… und es wird nichts abgefragt', w4.__abrufe.length === 0);
        w4.close();
    }

    // Ein Treffer aus dem Verzeichnis ist FREMDTEXT: er darf kein Markup werden.
    {
        const boese = '<img src=x onerror="window.__xss2=1">';
        const w5 = seite('de', [{ body: { ok: true, treffer: [
            { name: boese, adresse: 'x@beispiel.de', art: 'person' }] } }]);
        const b5 = w5.document.getElementById('messages');
        w5.JarvisBestaetigung.anfrage({
            id: 'f5', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'Suchbegriff']], aenderbar: ['an']
        }, { container: b5, senden: function () { return true; } });
        await warten(w5);
        const v = b5.querySelector('.jv-best-v-name');
        check('ein Name aus dem Verzeichnis erscheint als TEXT',
              !!v && v.textContent === boese, v && v.textContent);
        check('kein eingeschleustes Element aus einem Treffer',
              !b5.querySelector('.jv-best-vorschlaege img') && !w5.__xss2);
        w5.close();
    }

    // Fehler und Leerstand: beide werden GENANNT, nicht verschluckt
    {
        const w7 = seite('de', [{ http: false, body: { ok: false, error: 'Postfach ausgesetzt' } }]);
        const b7 = w7.document.getElementById('messages');
        w7.JarvisBestaetigung.anfrage({
            id: 'f7', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'Suchbegriff']], aenderbar: ['an']
        }, { container: b7, senden: function () { return true; } });
        await warten(w7);
        const m7 = b7.querySelector('.jv-best-feldmeldung');
        const j7 = b7.querySelector('.jv-best-ja');
        check('ein Fehler der Suche wird im Klartext angezeigt',
              !!m7 && /Postfach ausgesetzt/.test(m7.textContent), m7 && m7.textContent);
        check('… und die Karte bleibt bedienbar (Adresse von Hand)',
              !!b7.querySelector('.jv-best-feld') && !!j7 && !j7.disabled);
        w7.close();

        const w8 = seite('de', [{ body: { ok: true, treffer: [] } }]);
        const b8 = w8.document.getElementById('messages');
        w8.JarvisBestaetigung.anfrage({
            id: 'f8', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'Niemand']], aenderbar: ['an']
        }, { container: b8, senden: function () { return true; } });
        await warten(w8);
        const m8 = b8.querySelector('.jv-best-feldmeldung');
        check('kein Treffer wird benannt und nennt den naechsten Schritt',
              !!m8 && /Kein Eintrag gefunden/.test(m8.textContent), m8 && m8.textContent);
        w8.close();
    }

    // Englisch: die neuen Texte sind uebersetzt
    {
        const w9 = seite('en');
        const b9 = w9.document.getElementById('messages');
        w9.JarvisBestaetigung.anfrage({
            id: 'f9', werkzeug: 'email_senden', klasse: 'aussen',
            argumente: [['an', 'x@beispiel.de']], aenderbar: ['an']
        }, { container: b9, senden: function () { return true; } });
        const v9 = b9.querySelector('.jv-best-vorschlag-war');
        const a9 = b9.querySelector('.jv-best-ab');
        check('englisch: Vorschlag-Zeile uebersetzt',
              !!v9 && /^Suggested:/.test(v9.textContent),
              v9 ? v9.textContent : 'keine Vorschlag-Zeile');
        check('englisch: Adressbuch-Knopf hat einen englischen Titel',
              !!a9 && a9.title === 'Search the address book',
              a9 ? a9.title : 'kein Knopf');
        w9.close();
    }
    w6.close();
}

teil6().then(function () {
    bilanz();
    w.close(); we.close();
    process.exit(fail === 0 ? 0 : 1);
}).catch(function (e) {
    // Ein Wurf hier ist "konnte nicht laufen" – NICHT "beisst" (Exit 2).
    console.log('ABBRUCH in Abschnitt 6: ' + (e && e.stack ? e.stack : e));
    bilanz();
    process.exit(2);
});
