/* Waechter: Einstellungen-Dialog in /chat (Preprompt + Wissens-Vorauswahl).
 *
 * Gemessen wird die WIRKUNG am ECHTEN Markup mit dem ECHTEN chat.js: der Dialog
 * wird geoeffnet, die Kaestchen werden GEKLICKT und der Speichern-Aufruf an
 * einer fetch-Attrappe abgenommen. Eine Quelltext-Suche koennte weder "ist das
 * Kaestchen wirklich umgeschaltet" noch "was geht an den Server" beantworten.
 *
 * Die Funktionen werden geklammert aus chat.js geschnitten (bis zur passenden
 * schliessenden Klammer, NICHT bis zum ersten "\n}": eine Einzeiler-Funktion
 * dazwischen wuerde sonst mitgenommen und der Waechter pruefte fremden Code).
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

// Wachhund: haengt der Lauf (offene Timer der geladenen Seite), soll er MIT
// Bilanz abbrechen statt still weiterzulaufen.
const wachhund = setTimeout(() => {
    console.log('  \x1b[31m✗\x1b[0m Wachhund: Lauf haengt (25 s)');
    fail++; bilanz(); process.exit(1);
}, 25000);

let _bilanzGedruckt = false;
function bilanz() {
    _bilanzGedruckt = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
}
/* ⚠ Ein Lauf, der ohne Bilanzzeile endet, ist von "nicht gelaufen" nicht zu
 * unterscheiden – und mit Exit 0 sieht er wie ein bestandener aus. Die ganze
 * Datei ist EINE async-IIFE: bricht sie mittendrin ab, wird alles danach
 * uebersprungen. Dieser Haken zieht den Ausgang nach (im Projekt bezahlt). */
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
const CSS = fs.readFileSync(path.join(ROOT, 'frontend', 'css', 'chat.css'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'i18n.js'), 'utf8');

/* Geklammerter Schnitt einer Funktion aus chat.js. */
function schneide(quelle, kopf) {
    const i = quelle.indexOf(kopf);
    if (i < 0) return null;
    const auf = quelle.indexOf('{', i);
    if (auf < 0) return null;
    let tief = 0;
    for (let j = auf; j < quelle.length; j++) {
        const c = quelle[j];
        if (c === '{') tief++;
        else if (c === '}') { tief--; if (tief === 0) return quelle.slice(i, j + 1); }
    }
    return null;
}

// ── 1. Markup ───────────────────────────────────────────────────────────────
section('1. Markup: aus "Persoenlicher Preprompt" wird "Einstellungen"');
const dom0 = new JSDOM(HTML, { url: 'https://pruef.local/chat' });
const doc0 = dom0.window.document;

const zahn = doc0.getElementById('cs-settings');
check('Zahnrad neben "+ Neuer Chat" heisst Einstellungen',
      zahn && zahn.getAttribute('data-i18n-title') === 'chat.settings_title',
      zahn ? zahn.getAttribute('data-i18n-title') : 'Knopf fehlt');
check('Zahnrad hat auch das aria-label an dem Schluessel',
      zahn && zahn.getAttribute('data-i18n-aria') === 'chat.settings_title');
check('der alte Schluessel chat.preprompt_title kommt nicht mehr vor',
      !HTML.includes('chat.preprompt_title') && !CHATJS.includes('chat.preprompt_title')
      && !I18N.includes('chat.preprompt_title'));

const modal = doc0.getElementById('chat-settings-modal');
check('Dialog vorhanden und startet versteckt',
      modal && modal.classList.contains('hidden'));
check('Dialog ist direktes Kind von <body> (eigener Stapelkontext)',
      modal && modal.parentElement === doc0.body);
const titel = modal && modal.querySelector('.modal-title');
check('Dialog-Titel ist "Einstellungen"',
      titel && titel.getAttribute('data-i18n') === 'chat.settings_title',
      titel ? titel.getAttribute('data-i18n') : 'kein Titel');

const sects = modal ? Array.from(modal.querySelectorAll('.chs-sect')) : [];
check('genau ZWEI Container', sects.length === 2, 'gefunden: ' + sects.length);
check('beide Container sind KLAPPBAR (<details> mit <summary>)',
      sects.length === 2 && sects.every(d => d.tagName === 'DETAILS'
          && d.firstElementChild && d.firstElementChild.tagName === 'SUMMARY'),
      sects.map(d => d.tagName + '/' + (d.firstElementChild || {}).tagName).join(','));
check('jeder Container traegt seinen Speicher-Schluessel (data-chs)',
      sects.length === 2 && sects.map(d => d.dataset.chs).join(',') === 'preprompt,kb',
      sects.map(d => d.dataset.chs).join(','));
check('VORGABE im Markup: Preprompt offen, Wissensquellen zu',
      sects.length === 2 && sects[0].open === true && sects[1].open === false,
      sects.map(d => d.dataset.chs + ':' + d.open).join(','));
const t1 = sects[0] && sects[0].querySelector('.chs-sect-title');
check('erster Container ist "Persoenlicher Preprompt"',
      t1 && t1.getAttribute('data-i18n') === 'chat.preprompt_heading',
      t1 ? t1.getAttribute('data-i18n') : 'kein Titel');
check('das Preprompt-Textfeld liegt IN diesem Container',
      sects[0] && sects[0].querySelector('#preprompt-text') !== null);
const t2 = sects[1] && sects[1].querySelector('.chs-sect-title');
check('zweiter Container ist die Wissens-Vorauswahl',
      t2 && t2.getAttribute('data-i18n') === 'chat.kbdef_heading',
      t2 ? t2.getAttribute('data-i18n') : 'kein Titel');
check('Gruppenliste und Alle/Keine liegen IN diesem Container',
      sects[1] && sects[1].querySelector('#chs-kb-list') && sects[1].querySelector('#chs-kb-all')
      && sects[1].querySelector('#chs-kb-none'));

// Der Fuss darf NICHT im scrollenden Koerper liegen: sonst waere "Speichern"
// bei vielen Wissensgruppen ausserhalb des Sichtfensters (Update-Popup-Lehre).
const body = modal && modal.querySelector('.chs-body');
const save = doc0.getElementById('btn-chat-settings-save');
check('Speichern liegt NICHT im scrollenden Koerper',
      save && body && !body.contains(save));
check('Speichern und Schliessen liegen im Fuss',
      save && save.closest('.chs-foot') !== null
      && doc0.getElementById('btn-chat-settings-close').closest('.chs-foot') !== null);

// ── 2. CSS-Zusagen ──────────────────────────────────────────────────────────
section('2. CSS: der Fuss bleibt erreichbar');
function regel(sel) {
    const ohneKomm = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    const re = new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}');
    const m = ohneKomm.match(re);
    return m ? m[1] : '';
}
check('Positivkontrolle: .chs-card wird gefunden', regel('.chs-card').length > 10);
check('.chs-card ist eine Flex-Spalte mit Hoehendeckel am Sichtfenster',
      /flex-direction:\s*column/.test(regel('.chs-card')) && /max-height:\s*calc\(100vh/.test(regel('.chs-card')));
check('.chs-body scrollt und hat min-height:0 (sonst wirkungslos)',
      /overflow-y:\s*auto/.test(regel('.chs-body')) && /min-height:\s*0/.test(regel('.chs-body')));
check('.chs-foot gibt unter Druck nicht nach (flex:0 0 auto)',
      /flex:\s*0\s+0\s+auto/.test(regel('.chs-foot')));
check('.chs-save/.chs-close nehmen das width:100% der Basisklassen zurueck',
      /width:\s*auto/.test(regel('.chs-save')) && /width:\s*auto/.test(regel('.chs-close')));
check('.chs-kb-name hat min-width:0 (langer Name kuerzt statt zu schieben)',
      /min-width:\s*0/.test(regel('.chs-kb-name')));
check('der Titel ist als Klickflaeche erkennbar (cursor: pointer)',
      /cursor:\s*pointer/.test(regel('.chs-sect-title')));
check('der Tastatur-Fokus ist sichtbar (:focus-visible)',
      /outline/.test(regel('.chs-sect-title:focus-visible')));
check('und NICHT als :focus (das liesse nach jedem Mausklick einen Rahmen stehen)',
      !/\.chs-sect-title:focus\s*\{/.test(CSS.replace(/\.chs-sect-title:focus-visible/g, 'X')));
check('der zugeklappte Kasten ist kompakter (kein leerer Streifen)',
      /padding-bottom/.test(regel('.chs-sect:not([open])')));
check('die Gruppenliste hat KEINEN zweiten Scrollbereich (nur der Koerper scrollt)',
      !/overflow-y:\s*auto/.test(regel('.chs-kb-list')) && !/max-height/.test(regel('.chs-kb-list')),
      regel('.chs-kb-list'));

/* ⚠ DIE KOLLISION, DIE DER ECHTE BROWSER GEZEIGT HAT (2026-09-08):
 * `.modal-card input` setzt im Bestand display:block, width:100%, padding und
 * margin-bottom – gedacht fuer die Anmelde-/TOTP-Felder. Damit wurde das
 * Kaestchen einer Gruppenzeile fast zeilenbreit und der Gruppenname auf Breite
 * 0 gequetscht: die Liste zeigte NUR Kaestchen und Farbpunkte. jsdom rechnet
 * kein Layout, deshalb wird hier die REGEL geprueft – und zwar fuer JEDE
 * Eigenschaft, die die Bestandsregel setzt. Kommt dort morgen eine dazu, faellt
 * es hier auf, statt auf einem Kundensystem. */
const eigModal = {};
regel('.modal-card input').split(';').forEach(d => {
    const i = d.indexOf(':');
    if (i > 0) eigModal[d.slice(0, i).trim()] = d.slice(i + 1).trim();
});
const eigZeile = {};
regel('.chs-kb-row input').split(';').forEach(d => {
    const i = d.indexOf(':');
    if (i > 0) eigZeile[d.slice(0, i).trim()] = d.slice(i + 1).trim();
});
check('Positivkontrolle: .modal-card input setzt wirklich Layout-Eigenschaften',
      Object.keys(eigModal).length >= 4 && 'width' in eigModal, JSON.stringify(eigModal));
// Geprueft werden die Eigenschaften, die GROESSE UND PLATZ bestimmen – genau
// die haben die Zeile gesprengt. Rein optische (border/background/color) sind
// hier unschaedlich; dass der Haken sichtbar bleibt, misst die Live-Probe im
// echten Browser (jsdom kann das nicht).
const LAYOUT = ['display', 'width', 'height', 'padding', 'margin', 'margin-bottom'];
const offen = Object.keys(eigModal).filter(k => LAYOUT.indexOf(k) >= 0)
    .filter(k => !(k in eigZeile) && !(k.indexOf('margin') === 0 && 'margin' in eigZeile));
check('Positivkontrolle: die Bestandsregel setzt Layout-Eigenschaften',
      Object.keys(eigModal).filter(k => LAYOUT.indexOf(k) >= 0).length >= 3);
check('⚠ das Kaestchen der Gruppenzeile nimmt JEDE Layout-Eigenschaft von .modal-card input zurueck',
      offen.length === 0, 'nicht zurueckgenommen: ' + offen.join(', '));

/* Gemeldet 2026-09-08: "'schliessen' und 'speichern' funktionieren erst nach
 * vorherigem Klick auf eine Wissensgruppe". ⚠ NICHT REPRODUZIERT – und zwei
 * naheliegende Erklaerungen sind im echten Chrome WIDERLEGT:
 *   - z-index: .modal-overlay liegt auf 1000, die Popups der Eingabeleiste auf
 *     10050 – der Dialog liegt trotzdem oben (Stapelkontexte), der erste Klick
 *     wirkt auch mit dem alten Wert. Deshalb steht hier KEINE z-index-Zusage.
 *   - Layout-Sprung: der Dialog wuchs nach dem Erscheinen um 29 px (Kasten
 *     635 -> 693). Mit mousedown/mouseup ueber den Sprung hinweg kommt der
 *     Klick trotzdem an: 29 px sind weniger als die 45 px Knopfhoehe.
 * Der Abschnitt haelt deshalb eine VERBESSERUNG fest, keinen Fix: der Dialog
 * wird erst sichtbar, wenn sein Inhalt steht (ein nachwachsender Dialog ist in
 * jedem Fall schlechter), mit Doppelklick-Schutz und Wartezustand am Zahnrad. */
section('2b. Der erste Klick muss treffen');
check('das Zahnrad zeigt die Wartezeit (sonst wirkt der Klick tot)',
      /cursor:\s*progress|opacity/.test(regel('.cs-collapse.is-busy')));

// ── 3. Der Dialog im Betrieb ────────────────────────────────────────────────
section('3. Dialog ausgefuehrt: zeichnen, klicken, speichern');

function baueUmgebung(entries, off, opt) {
    opt = opt || {};
    const dom = new JSDOM(HTML, { url: 'https://pruef.local/chat' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    w.localStorage.setItem('jarvis_user', 'pruefer');
    const rufe = [];
    w.fetch = async function (url, o) {
        rufe.push({ url: String(url).split('?')[0], opt: o || {} });
        const pfad = String(url).split('?')[0];
        if (pfad === '/api/chat/kb-default') {
            if (opt.kbDefFehler) throw new Error('netz');
            if ((o || {}).method === 'PUT') {
                // Der echte Endpunkt antwortet mit dem GESPEICHERTEN Stand –
                // ggf. normalisiert. `opt.serverAntwort` stellt genau diesen
                // Fall: die Antwort des Servers gewinnt, nicht der Formularstand.
                const gesendet = JSON.parse(((o || {}).body) || '{}').off || [];
                const echo = opt.serverAntwort || gesendet;
                off = echo.slice();
                return { json: async () => ({ ok: true, off: echo, set: echo.length > 0 }) };
            }
            return { json: async () => ({ ok: true, off: off, set: off.length > 0 }) };
        }
        if (pfad === '/api/chat/preprompt') {
            return { json: async () => ({ ok: true, preprompt: 'mein text' }) };
        }
        return { json: async () => ({ ok: true }) };
    };
    w.t = (k) => k;                        // Schluessel als Text: eindeutig messbar
    w.KbGroupFilter = {
        loadEntries: async function () {
            if (opt.entriesFehler) throw new Error('keine gruppen');
            // `bremse` haelt den Abruf an: nur so ist der Zustand WAEHREND des
            // Ladens messbar (ein aufgeloestes Promise waere sofort fertig).
            if (opt.bremse) return await opt.bremse();
            return entries;
        },
        UNGROUPED: 'ungrouped'
    };
    // Nur die geschnittenen Teile ausfuehren, nicht das ganze chat.js (das
    // baut WebSockets, Timer und eine Anmeldung auf).
    const teile = [
        'function escapeHtml(str) {\n const d = w.document.createElement("div"); d.textContent = str; return d.innerHTML; }',
        'const $ = (id) => w.document.getElementById(id);',
        'const token = "T";',
        'const _authHdr = (extra) => Object.assign({ Authorization: "Bearer " + token }, extra || {});',
        'function _csHeaders(extra) { return _authHdr(extra); }',
        schneide(CHATJS, 'function _kbDefLaden('),
        schneide(CHATJS, 'async function _kbDefAlsAuswahl('),
        schneide(CHATJS, 'function _chsOffenLesen('),
        schneide(CHATJS, 'function _chsOffenSchreiben('),
        schneide(CHATJS, 'function _chsKlappZustand('),
        schneide(CHATJS, 'async function _openChatSettings('),
        schneide(CHATJS, 'function _closeChatSettings('),
        schneide(CHATJS, 'async function _kbDefZeichnen('),
        schneide(CHATJS, 'function _kbDefSetzeAlle('),
        schneide(CHATJS, 'function _kbDefHinweis('),
        schneide(CHATJS, 'async function _saveChatSettings(')
    ];
    const fehlend = teile.filter(x => x === null).length;
    if (fehlend) return { fehlend: fehlend };
    // Modul-Konstanten fallen aus jedem Funktions-Schnitt heraus (Register) –
    // sie werden hier ausdruecklich mitgegeben.
    const konst = (CHATJS.match(/const _CHS_OFFEN_KEY[^\n]*\n\s*const _CHS_VORGABE[^\n]*/) || [''])[0];
    if (!konst) { console.log('  \x1b[31m✗\x1b[0m _CHS_OFFEN_KEY/_CHS_VORGABE nicht gefunden'); fail++; }
    const src = 'let _kbDefOff = null, _kbDefPromise = null, _kbDefEintraege = null, _chsLaeuft = false;\n' + konst + '\n'
        + teile.join('\n') + '\n'
        + 'w.__api = { oeffnen: _openChatSettings, alle: _kbDefSetzeAlle, '
        + 'speichern: _saveChatSettings, auswahl: _kbDefAlsAuswahl, hinweis: _kbDefHinweis, '
        + 'schliessen: _closeChatSettings, klapp: _chsKlappZustand, offen: _chsOffenLesen };';
    const fn = new Function('w', 'window', 'document', 'localStorage', 'fetch', 'setTimeout', src);
    fn(w, w, w.document, w.localStorage, w.fetch, w.setTimeout);
    return { w: w, doc: w.document, rufe: rufe };
}

const EINTRAEGE = [
    { id: 'g1', name: 'Handbuecher', color: '#f00' },
    { id: 'g2', name: 'Tickets', color: '#0f0' },
    { id: 'ungrouped', name: 'ungruppiert', color: '#94a3b8' }
];

(async function () {
    // (a) Vorauswahl "g2 abgewaehlt" -> zwei Haken, einer leer
    let u = baueUmgebung(EINTRAEGE, ['g2']);
    if (u.fehlend) { check('alle Dialog-Funktionen geschnitten', false, u.fehlend + ' fehlen'); bilanz(); process.exit(1); }
    check('Positivkontrolle: alle Dialog-Funktionen geschnitten', true);
    await u.w.__api.oeffnen();
    let cbs = Array.from(u.doc.querySelectorAll('#chs-kb-list input[type=checkbox]'));
    check('alle Eintraege gezeichnet (Gruppen + ungruppiert)', cbs.length === 3, 'gezeichnet: ' + cbs.length);
    check('die abgewaehlte Gruppe ist NICHT angehakt',
          cbs.map(c => c.value + ':' + c.checked).join(',') === 'g1:true,g2:false,ungrouped:true',
          cbs.map(c => c.value + ':' + c.checked).join(','));
    check('der Preprompt wurde in sein Feld geladen',
          u.doc.getElementById('preprompt-text').value === 'mein text');
    check('der Gruppenname steht sichtbar in der Zeile',
          /Handbuecher/.test(u.doc.getElementById('chs-kb-list').textContent));
    check('Dialog ist sichtbar (Klasse hidden weg)',
          !u.doc.getElementById('chat-settings-modal').classList.contains('hidden'));

    // (b) Speichern schickt die ABGEWAEHLTEN
    u.rufe.length = 0;
    await u.w.__api.speichern();
    const put = u.rufe.filter(r => r.url === '/api/chat/kb-default' && (r.opt.method === 'PUT'));
    check('genau ein PUT auf /api/chat/kb-default', put.length === 1, 'Aufrufe: ' + put.length);
    check('gesendet werden die ABGEWAEHLTEN Ids (nicht die ausgewaehlten)',
          put.length === 1 && JSON.parse(put[0].opt.body).off.join(',') === 'g2',
          put.length ? put[0].opt.body : '-');
    const pp = u.rufe.filter(r => r.url === '/api/chat/preprompt' && r.opt.method === 'PUT');
    check('der Preprompt wird im selben Klick gespeichert', pp.length === 1);
    check('kein Benutzername im Rumpf (der kommt aus der Anmeldung)',
          put.length === 1 && !/"user"|"username"|"benutzer"/.test(put[0].opt.body));

    // (c) Kaestchen wirklich klicken – nie selbst umschalten (Label-Falle)
    u = baueUmgebung(EINTRAEGE, []);
    await u.w.__api.oeffnen();
    let box = u.doc.getElementById('chs-kb-list');
    let cb1 = box.querySelector('input[value=g1]');
    cb1.click();          // in einem <label>: der Browser schaltet selbst
    check('ein Klick auf das Kaestchen schaltet es AUS (kein Doppel-Toggle)',
          cb1.checked === false, 'checked=' + cb1.checked);
    cb1.click();
    check('der zweite Klick schaltet es wieder EIN', cb1.checked === true);
    // Klick auf den NAMEN wirkt ueber das <label> mit
    const label = box.querySelector('input[value=g2]').closest('label');
    label.querySelector('.chs-kb-name').click();
    check('ein Klick auf den Gruppennamen wirkt mit (label)',
          box.querySelector('input[value=g2]').checked === false);

    // (d) Alle / Keine + Hinweis
    u.w.__api.alle(false);
    cbs = Array.from(box.querySelectorAll('input[type=checkbox]'));
    check('"Keine" nimmt alle Haken weg', cbs.every(c => !c.checked));
    let hint = u.doc.getElementById('chs-kb-hint');
    check('bei 0 Gruppen erscheint der Hinweis "neue Chats ohne Wissensdatenbank"',
          !hint.hidden && hint.textContent === 'chat.kbdef_none_hint', hint.textContent);
    check('der Hinweis ist als Warnung ausgezeichnet (nicht nur Farbe im CSS)',
          hint.className.indexOf('is-warn') >= 0);
    u.w.__api.alle(true);
    check('"Alle" setzt alle Haken', Array.from(box.querySelectorAll('input')).every(c => c.checked));
    check('der Hinweis verschwindet wieder', hint.hidden === true);
    u.rufe.length = 0;
    await u.w.__api.speichern();
    const put2 = u.rufe.filter(r => r.url === '/api/chat/kb-default');
    check('"alle angehakt" sendet eine LEERE off-Liste (= keine Vorauswahl)',
          put2.length === 1 && JSON.parse(put2[0].opt.body).off.length === 0,
          put2.length ? put2[0].opt.body : '-');

    // (e) Gruppenliste nicht ladbar -> Vorauswahl wird NICHT ueberschrieben
    u = baueUmgebung(EINTRAEGE, ['g2'], { entriesFehler: true });
    await u.w.__api.oeffnen();
    hint = u.doc.getElementById('chs-kb-hint');
    check('ohne Gruppenliste sagt der Dialog es im Klartext',
          !hint.hidden && hint.textContent === 'chat.kbdef_load_failed', hint.textContent);
    u.rufe.length = 0;
    await u.w.__api.speichern();
    check('⚠ ohne Gruppenliste wird die Vorauswahl NICHT geschrieben',
          u.rufe.filter(r => r.url === '/api/chat/kb-default').length === 0,
          JSON.stringify(u.rufe.map(r => r.url)));
    check('der Preprompt wird trotzdem gespeichert (ein Fehler nimmt den anderen Teil nicht mit)',
          u.rufe.filter(r => r.url === '/api/chat/preprompt' && r.opt.method === 'PUT').length === 1);

    // (f) keine Gruppen angelegt
    u = baueUmgebung([{ id: 'ungrouped', name: 'ungruppiert', color: '#94a3b8' }], []);
    await u.w.__api.oeffnen();
    check('nur "ungruppiert" vorhanden: eine Zeile',
          u.doc.querySelectorAll('#chs-kb-list input').length === 1);

    /* ⚠ AUSGEFUEHRT: der Dialog darf NICHT sichtbar werden, solange die Liste
     * noch fehlt – sonst waechst er unter dem Zeiger und der erste Klick auf
     * "Speichern"/"Schliessen" geht verloren. Gemessen wird der Zustand
     * WAEHREND des Ladens, nicht danach. */
    section('3a. Sichtbar erst, wenn der Inhalt steht');
    let loese;
    u = baueUmgebung(EINTRAEGE, ['g2'], { bremse: () => new Promise(r => { loese = r; }) });
    const pOffen = u.w.__api.oeffnen();
    await new Promise(r => setTimeout(r, 0));
    check('waehrend die Gruppen noch laden, bleibt der Dialog VERSTECKT',
          u.doc.getElementById('chat-settings-modal').classList.contains('hidden'),
          'sichtbar, obwohl die Liste fehlt');
    check('und das Zahnrad zeigt den Wartezustand',
          u.doc.getElementById('cs-settings').getAttribute('aria-busy') === 'true',
          String(u.doc.getElementById('cs-settings').getAttribute('aria-busy')));
    loese(EINTRAEGE);
    await pOffen;
    check('nach dem Laden ist der Dialog sichtbar UND die Liste steht',
          !u.doc.getElementById('chat-settings-modal').classList.contains('hidden')
          && u.doc.querySelectorAll('#chs-kb-list input').length === 3);
    check('der Wartezustand ist wieder weg',
          !u.doc.getElementById('cs-settings').hasAttribute('aria-busy'));
    // Und ein zweiter Klick waehrend des Ladens darf nichts doppelt tun.
    u = baueUmgebung(EINTRAEGE, [], { bremse: () => new Promise(r => { loese = r; }) });
    const p1 = u.w.__api.oeffnen(); const p2 = u.w.__api.oeffnen();
    await new Promise(r => setTimeout(r, 0));
    loese(EINTRAEGE); await p1; await p2;
    check('ein zweiter Klick auf das Zahnrad waehrend des Ladens laeuft nicht doppelt',
          u.rufe.filter(r => r.url === '/api/chat/preprompt').length === 1,
          'Abrufe: ' + u.rufe.filter(r => r.url === '/api/chat/preprompt').length);

    // ── 3b. Klappzustand ────────────────────────────────────────────────────
    section('3b. Klapp-Container: Vorgabe und gemerkte Wahl');
    u = baueUmgebung(EINTRAEGE, ['g2']);
    let sc = () => Array.from(u.doc.querySelectorAll('#chat-settings-modal .chs-sect'));
    await u.w.__api.oeffnen();
    check('ohne gespeicherte Wahl gilt die Vorgabe (Preprompt offen, Wissen zu)',
          sc().map(d => d.dataset.chs + ':' + d.open).join(',') === 'preprompt:true,kb:false',
          sc().map(d => d.dataset.chs + ':' + d.open).join(','));
    check('der Speicher ist dabei noch leer (die Vorgabe wird nicht vorgeschrieben)',
          u.w.localStorage.getItem('jarvis_chat_settings_open') === null,
          String(u.w.localStorage.getItem('jarvis_chat_settings_open')));

    // Wie ein Benutzer: Container umklappen (das <details> feuert `toggle`).
    sc()[1].open = true;
    sc()[1].dispatchEvent(new u.w.Event('toggle'));
    sc()[0].open = false;
    sc()[0].dispatchEvent(new u.w.Event('toggle'));
    let gesp = JSON.parse(u.w.localStorage.getItem('jarvis_chat_settings_open') || 'null');
    check('⚠ die Wahl wird GEMERKT', gesp && gesp.kb === true && gesp.preprompt === false,
          JSON.stringify(gesp));

    // Dialog schliessen und erneut oeffnen: die gemerkte Wahl gewinnt.
    u.w.__api.schliessen();
    await u.w.__api.oeffnen();
    check('⚠ beim naechsten Oeffnen gilt die gemerkte Wahl, nicht die Vorgabe',
          sc().map(d => d.dataset.chs + ':' + d.open).join(',') === 'preprompt:false,kb:true',
          sc().map(d => d.dataset.chs + ':' + d.open).join(','));

    // Und in einem frischen Fenster mit demselben Speicherstand.
    const gemerkt = u.w.localStorage.getItem('jarvis_chat_settings_open');
    u = baueUmgebung(EINTRAEGE, ['g2']);
    u.w.localStorage.setItem('jarvis_chat_settings_open', gemerkt);
    sc = () => Array.from(u.doc.querySelectorAll('#chat-settings-modal .chs-sect'));
    await u.w.__api.oeffnen();
    check('auch nach einem Neuladen der Seite', sc()[1].open === true && sc()[0].open === false,
          sc().map(d => d.dataset.chs + ':' + d.open).join(','));

    // Kaputter Speicherstand -> Vorgaben, kein Wurf.
    u = baueUmgebung(EINTRAEGE, []);
    u.w.localStorage.setItem('jarvis_chat_settings_open', '{kein json');
    sc = () => Array.from(u.doc.querySelectorAll('#chat-settings-modal .chs-sect'));
    const w1 = sicher(() => u.w.__api.offen());
    check('kaputter Speicherstand -> Vorgaben, kein Wurf',
          w1 && w1.preprompt === true && w1.kb === false, JSON.stringify(w1));
    u.w.localStorage.setItem('jarvis_chat_settings_open', '{"kb":"ja","preprompt":1}');
    const w2 = sicher(() => u.w.__api.offen());
    check('falsche Typen im Speicher -> Vorgaben (nicht auf Falsyness geraten)',
          w2 && w2.preprompt === true && w2.kb === false, JSON.stringify(w2));

    /* ⚠ DIE FALLE, DIE DAS PROJEKT SCHON BEZAHLT HAT: eine Liste, die nur bei
     * OFFENEM Container geladen wird (loadReminders brach bei versteckter Box
     * ab). Hier waere die Folge schwerer als eine leere Liste: ohne
     * `_kbDefEintraege` ueberspringt das Speichern den Wissens-Teil (fail-safe)
     * – die Einstellung waere im zugeklappten Zustand still nicht speicherbar. */
    u = baueUmgebung(EINTRAEGE, ['g2']);
    await u.w.__api.oeffnen();
    sc = () => Array.from(u.doc.querySelectorAll('#chat-settings-modal .chs-sect'));
    check('Positivkontrolle: der Wissens-Container ist zu', sc()[1].open === false);
    check('⚠ die Gruppenliste wird TROTZDEM gezeichnet',
          u.doc.querySelectorAll('#chs-kb-list input').length === 3,
          'Zeilen: ' + u.doc.querySelectorAll('#chs-kb-list input').length);
    u.rufe.length = 0;
    await u.w.__api.speichern();
    check('⚠ und die Vorauswahl ist auch zugeklappt speicherbar',
          u.rufe.filter(r => r.url === '/api/chat/kb-default' && r.opt.method === 'PUT').length === 1,
          JSON.stringify(u.rufe.map(r => r.url)));

    // ── 4. Uebersetzung in die Filter-Semantik ──────────────────────────────
    section('4. Vorauswahl -> Filter-Semantik (null=alle, []=keine, [ids]=nur diese)');
    u = baueUmgebung(EINTRAEGE, []);
    check('nichts abgewaehlt -> null (kein Filter)', (await u.w.__api.auswahl()) === null);
    u = baueUmgebung(EINTRAEGE, ['g2']);
    let sel = await u.w.__api.auswahl();
    check('eine abgewaehlt -> nur die uebrigen',
          Array.isArray(sel) && sel.join(',') === 'g1,ungrouped', JSON.stringify(sel));
    u = baueUmgebung(EINTRAEGE, ['g1', 'g2', 'ungrouped']);
    sel = await u.w.__api.auswahl();
    check('alle abgewaehlt -> [] (kein Wissen, bewusste Wahl)',
          Array.isArray(sel) && sel.length === 0, JSON.stringify(sel));
    u = baueUmgebung(EINTRAEGE, ['weg'], {});
    sel = await u.w.__api.auswahl();
    check('nur unbekannte Ids abgewaehlt (Gruppe geloescht) -> null',
          sel === null, JSON.stringify(sel));
    u = baueUmgebung(EINTRAEGE, ['g2'], { entriesFehler: true });
    check('Gruppenliste nicht ladbar -> null (fail-open, wie bisher)',
          (await u.w.__api.auswahl()) === null);
    u = baueUmgebung(EINTRAEGE, ['g2'], { kbDefFehler: true });
    check('Vorauswahl nicht abrufbar -> null (fail-open)',
          (await u.w.__api.auswahl()) === null);

    /* ⚠ DIE LUECKE, DIE DER ENDE-ZU-ENDE-LAUF GEFUNDEN HAT (2026-09-08):
     * `_kbDefLaden()` cached ein Promise, und ein AUFGELOESTES Promise haelt
     * seinen Wert fest. Wer nach dem Speichern `await _kbDefLaden()` liest,
     * bekommt das Set des ERSTEN Abrufs – die frisch gespeicherte Vorauswahl
     * griff dadurch erst nach einem Neuladen der Seite. Die Abschnitte davor
     * konnten das nicht sehen, weil sie je Fall eine frische Umgebung bauen:
     * hier wird DERSELBE Zustand nacheinander benutzt. */
    section('4b. Nach dem Speichern gilt der NEUE Stand (ohne Neuladen)');
    u = baueUmgebung(EINTRAEGE, []);
    await u.w.__api.oeffnen();
    check('vorher: keine Vorauswahl -> null', (await u.w.__api.auswahl()) === null);
    u.doc.querySelector('#chs-kb-list input[value=g2]').click();
    await u.w.__api.speichern();
    sel = await u.w.__api.auswahl();
    check('⚠ direkt nach dem Speichern liefert die Vorauswahl den NEUEN Stand',
          Array.isArray(sel) && sel.join(',') === 'g1,ungrouped', JSON.stringify(sel));
    // und zurueck: alles anhaken -> wieder "alle"
    u.w.__api.alle(true);
    await u.w.__api.speichern();
    check('und die Ruecknahme wirkt genauso sofort', (await u.w.__api.auswahl()) === null);
    // Der SERVER ist die Wahrheit: normalisiert er die Liste, gilt seine.
    u = baueUmgebung(EINTRAEGE, [], { serverAntwort: ['g1'] });
    await u.w.__api.oeffnen();
    u.doc.querySelector('#chs-kb-list input[value=g2]').click();
    await u.w.__api.speichern();
    sel = await u.w.__api.auswahl();
    check('die Antwort des Servers gewinnt gegen den Formularstand',
          Array.isArray(sel) && sel.join(',') === 'g2,ungrouped', JSON.stringify(sel));

    // ── 5. Anwendung: nur beim NEUEN Chat ───────────────────────────────────
    section('5. Regel: die Vorauswahl greift nur in einem frischen Chat');
    const rh = schneide(CHATJS, 'async function _restoreHistory(');
    check('Positivkontrolle: _restoreHistory geschnitten', rh !== null);
    if (rh) {
        const zweig = rh.slice(rh.indexOf('if (_kbFilter) {'), rh.indexOf('if (_kbFilter) {') + 600);
        check('gespeicherte Sitzungs-Auswahl hat Vorrang',
              /kb_groups_set\)\s*_kbFilter\.setSelection\(_sdata\.kb_groups\)/.test(zweig.replace(/\s+/g, ' ').replace(/ /g, ' ')) ||
              /kb_groups_set/.test(zweig) && /_sdata\.kb_groups\)/.test(zweig));
        check('die Vorauswahl wird NUR bei leerem Transkript angewandt',
              /_chatHistory\.length === 0\)\s*_kbFilter\.setSelection\(await _kbDefAlsAuswahl\(\)\)/.test(zweig.replace(/\s+/g, ' ')),
              zweig.replace(/\s+/g, ' ').slice(0, 240));
        check('eine alte Sitzung MIT Verlauf bleibt bei "alle"',
              /else _kbFilter\.setSelection\(null\)/.test(zweig.replace(/\s+/g, ' ')));
        check('und darauf wird gewartet (await) – sonst sendet der erste Turn ungefiltert',
              /await _kbDefAlsAuswahl\(\)/.test(zweig));
    }
    check('die Vorauswahl wird beim Aufbau der Chat-Seite geladen',
          /_kbDefLaden\(\);/.test(schneide(CHATJS, 'function showChat(') || ''));

    // ── 6. i18n in BEIDEN Sprachen ──────────────────────────────────────────
    section('6. i18n');
    const benutzt = new Set();
    (HTML + CHATJS).replace(/['"]((?:chat\.(?:settings|kbdef)_[a-z_]+))['"]/g, (m, k) => { benutzt.add(k); return m; });
    check('Positivkontrolle: neue Schluessel im Code gefunden', benutzt.size >= 5, 'gefunden: ' + benutzt.size);
    const fehlen = [];
    benutzt.forEach(k => { if ((I18N.split("'" + k + "'").length - 1) < 2) fehlen.push(k); });
    check('jeder neue Schluessel steht in DE UND EN', fehlen.length === 0, fehlen.join(', '));
    check('der Platzhalter {t} der Fehlermeldung steht in beiden Sprachen',
          (I18N.match(/'chat\.settings_save_failed':\s*'[^']*\{t\}[^']*'/g) || []).length === 2);
    // Wiederverwendete Schluessel statt neuer Texte fuer dasselbe
    check('Alle/Keine/leer nutzen die vorhandenen kbfilter-Texte (eine Quelle)',
          /data-i18n="kbfilter\.select_all"/.test(HTML) && /data-i18n="kbfilter\.select_none"/.test(HTML)
          && /kbfilter\.empty/.test(CHATJS));

    // ── 7. Eine Quelle fuer die Eintragsliste ───────────────────────────────
    section('7. Eine Quelle fuer Gruppen + "ungruppiert"');
    const KBF = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'kbgroupfilter.js'), 'utf8');
    check('kbgroupfilter.js exportiert loadEntries', /loadEntries:\s*loadEntries/.test(KBF));
    const ohneKomm = KBF.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    check('der "ungruppiert"-Eintrag wird nur EINMAL gebaut',
          (ohneKomm.match(/kbfilter\.ungrouped/g) || []).length === 1,
          'Fundstellen: ' + (ohneKomm.match(/kbfilter\.ungrouped/g) || []).length);
    check('der Dialog baut die Liste NICHT selbst nach',
          !/kbfilter\.ungrouped/.test(CHATJS) && /KbGroupFilter\.loadEntries/.test(CHATJS));

    clearTimeout(wachhund);
    bilanz();
    process.exit(fail ? 1 : 0);
})().catch(e => {
    console.log('  \x1b[31m✗\x1b[0m unbehandelter Fehler: ' + e.stack);
    fail++; bilanz(); process.exit(1);
});
