#!/usr/bin/env node
/**
 * Waechter: der Download-Chip im Chat traegt ein Token – unter JEDEM der drei
 * Anmelde-Schluessel.
 *
 * DER VORFALL (2026-10-01, ECHT, /chat, eine Benutzerin): der Klick
 * auf den Chip einer zusammengefuehrten Rechnung brachte eine Frage nach
 * Benutzername und Kennwort. Auf ECHT gemessen war die Datei vorhanden, der
 * Eigentuemer-Eintrag korrekt, `api_local_only` leer und `download_key_strict`
 * aus – und im Journal stand ueber drei Tage KEINE Zeile dazu. Ursache war ein
 * NAME: `dlkey.js` las nur `jarvis_token`, die Chat-Seite schreibt aber
 * `jarvis_chat_token` (chat.js) bzw. `jarvis_uc_token` (userchat.js). Damit
 * stand `tok()` auf leer, und das hatte DREI Folgen auf einmal:
 *   1. `holen()` brach ab – `/api/download-key` wurde NIE gerufen,
 *   2. der Takt sprang nie an,
 *   3. `DL.url()` gab die Adresse OHNE `?token=` zurueck → 401.
 * Die drei Sicherheitsnetze in dlkey.js greifen dagegen NICHT: sie fassen nur
 * Adressen an, die schon ein `token=JDL1.` tragen.
 *
 * GEMESSEN WIRD DIE WIRKUNG AN DER ECHTEN KETTE – sitzung.js, dlkey.js und
 * chatlib.js laufen wirklich, der Chip entsteht ueber den echten
 * `renderMarkdown`, und geprueft wird das `href` im DOM. Eine Quelltext-Suche
 * koennte „traegt der Link ein Token" grundsaetzlich nicht beantworten: genau
 * deshalb war der Fehler ein Jahr lang unsichtbar, obwohl `_withToken` an jeder
 * Stelle im Code stand.
 *
 * Aufruf: node tests/test_dlkey_token_schluessel.js
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const W = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

const SITZUNG = fs.readFileSync(W + '/frontend/js/sitzung.js', 'utf8');
const DLKEY = fs.readFileSync(W + '/frontend/js/dlkey.js', 'utf8');
const CHATLIB = fs.readFileSync(W + '/frontend/js/chatlib.js', 'utf8');

/* Der gemeldete Fall, Name und Form unveraendert: Capability-Name aus 32 Hex,
 * dann `__`, dann der Originalname. Die Endung MUSS dabei sein – die
 * Chip-Regel in chatlib.js verlangt docx|xlsx|pptx|pdf. */
const CAP = '0123456789abcdef0123456789abcdef__Rechnung_4711_20260930.pdf';
const CHIP_MD = '[📥 Rechnung_4711_20260930.pdf herunterladen](/api/documents/' + CAP + ')';

const TOKEN_SCHLUESSEL = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
const BENUTZER_SCHLUESSEL = ['jarvis_user', 'jarvis_chat_user', 'jarvis_uc_user'];

let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t) {
    if (typeof b !== 'boolean') {
        console.log('ABBRUCH: check(Bedingung, Text) – Argumente vertauscht: ' + t);
        process.exit(2);
    }
    if (b) { OK++; console.log('  \x1b[32mOK\x1b[0m   ' + t); }
    else { FAIL++; console.log('  \x1b[31mFAIL\x1b[0m ' + t); }
}
function kopf(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function bilanz() {
    if (BILANZ) return;
    BILANZ = true;
    console.log('\n' + '='.repeat(62));
    console.log('\x1b[1mErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL\x1b[0m');
}
/* Ein stiller Abbruch darf nicht wie „bestanden" aussehen. Nur einen Lauf
 * OHNE Bilanz anheben – ein ausdrueckliches process.exit(2) bleibt Exit 2. */
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
const hund = setTimeout(() => {
    console.log('\x1b[31mFAIL\x1b[0m Wachhund: der Lauf haengt');
    FAIL++; bilanz(); process.exit(1);
}, 40000);
hund.unref && hund.unref();

/** Baut eine Seite wie /chat: echte sitzung.js, echte dlkey.js, echte chatlib.js.
 *  `schluessel` = der EINE Anmelde-Schluessel, den die Seite gesetzt hat. */
function seite(schluessel, benutzerSchluessel) {
    /* ⚠ `runScripts: 'outside-only'` IST PFLICHT, UND DER GRUND HAT MICH HIER
     * SECHS FAIL GEKOSTET: ohne diese Option ist `win.eval` NODES eval – das
     * Skript laeuft dann im Node-Namensraum, wo `sessionStorage` nicht
     * existiert. `dlkey.js::schreiben()` faengt jeden Fehler ab ("privater
     * Modus"), der Zwischenspeicher blieb also STILL leer und der Link trug
     * nur den Rueckfall. Das sah exakt wie ein Codefehler aus und war ein
     * Messfehler. Mit der Option loesen `window`, `localStorage` und
     * `sessionStorage` im Skript natuerlich auf – kein global-Gebastel. */
    const dom = new JSDOM('<!doctype html><html><body></body></html>',
        { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
    const win = dom.window;

    if (schluessel) win.localStorage.setItem(schluessel, 'm.mustermann:1790000000:abcdef');
    if (benutzerSchluessel) win.localStorage.setItem(benutzerSchluessel, 'm.mustermann');

    const zustand = { abrufe: 0, pfade: [] };
    const exp = Math.floor(Date.now() / 1000) + 900;
    const b64 = Buffer.from('m.mustermann', 'utf8').toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    zustand.key = 'JDL1.' + b64 + '.' + exp + '.' + 'a'.repeat(64);

    // Attrappe nach dem PFAD routen, nicht nach der vollen URL – ein spaeter
    // ergaenztes ?lang= verfehlt sonst jede Route (Register).
    win.fetch = function (url, opt) {
        const pfad = String(url).split('?')[0];
        zustand.pfade.push(pfad);
        if (pfad === '/api/download-key') {
            zustand.abrufe++;
            // Form und Felder wie der echte Endpunkt (main.py: ok/key/exp/ttl_min)
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ok: true, key: zustand.key, exp: exp, ttl_min: 15 })
            });
        }
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    };

    win.eval(SITZUNG);
    win.eval(DLKEY);
    win.eval(CHATLIB);
    return { win, zustand, render: win.JarvisChatLib.renderMarkdown };
}

/** Das href des Download-Chips aus gerendertem Markdown. '' = kein Chip. */
function chipHref(win, html) {
    const d = win.document.createElement('div');
    d.innerHTML = html;
    const a = d.querySelector('a.chat-doc-dl');
    return a ? (a.getAttribute('href') || '') : '';
}

/* ══════════════════════════════════════════════════════════════════════════
 * 1. POSITIVKONTROLLE
 * Ohne diesen Abschnitt sind alle folgenden trivial deutbar: entsteht gar kein
 * Chip (Regex geaendert, chatlib kaputt), waere „kein Token" kein Befund,
 * sondern ein Messfehler.
 * ════════════════════════════════════════════════════════════════════════ */
kopf('1) Positivkontrolle: der Messaufbau stellt den Regelfall her');
{
    const { win, render, zustand } = seite('jarvis_token', 'jarvis_user');
    const href = chipHref(win, render(CHIP_MD));
    check(href !== '', 'aus dem Liefer-Markdown entsteht ein Download-Chip');
    check(href.indexOf('/api/documents/' + CAP) === 0,
          'und zeigt auf die Capability-Adresse');
    check(typeof win.JarvisSitzung === 'object' && !!win.JarvisSitzung,
          'sitzung.js ist geladen');
    check(typeof win.JarvisDL === 'object' && !!win.JarvisDL, 'dlkey.js ist geladen');
    check(win.JarvisSitzung.token() === 'm.mustermann:1790000000:abcdef',
          'die gemeinsame Quelle findet den gesetzten Schluessel');
    check(zustand.pfade.indexOf('/api/download-key') >= 0,
          '/api/download-key wird ueberhaupt angefordert');
    if (FAIL) { bilanz(); process.exit(2); }   // Messaufbau kaputt = keine Aussage
}

/* ══════════════════════════════════════════════════════════════════════════
 * 2. DER VORFALL: jeder der drei Schluessel muss tragen
 * ════════════════════════════════════════════════════════════════════════ */
kopf('2) Der Chip traegt ein Token – unter jedem Anmelde-Schluessel');
for (const s of TOKEN_SCHLUESSEL) {
    const { win, render, zustand } = seite(s, null);
    const href = chipHref(win, render(CHIP_MD));
    check(/[?&]token=/.test(href), s + ': die Adresse traegt ein ?token= (sonst 401)');
    check(zustand.abrufe === 1, s + ': /api/download-key wurde genau einmal gerufen'
          + ' (gemessen: ' + zustand.abrufe + ')');
    // BSI M4 (2026-10-05): vor dem ersten Schluessel steht der PLATZHALTER in
    // der Adresse, nie das Sitzungstoken (der Server weist es per Vorgabe ab).
    check(href.indexOf('m.mustermann:1790000000') < 0 && href.indexOf('1790000000%3Aabcdef') < 0,
          s + ': vor dem ersten Schluessel KEIN Sitzungstoken in der Adresse');
    check(/[?&]token=JDL1\.warten\.0\.0/.test(href),
          s + ': sondern der Platzhalter in Schluesselform (wird nachgezogen)');
}

kopf('3) Derselbe Weg fuer den Benutzernamen (Bindung des Schluessels)');
for (const b of BENUTZER_SCHLUESSEL) {
    const { win } = seite('jarvis_token', b);
    check(win.JarvisSitzung.benutzer() === 'm.mustermann',
          b + ': der angemeldete Benutzer wird gefunden');
}

/* ══════════════════════════════════════════════════════════════════════════
 * 4. GEGENRICHTUNG – ohne sie waere Abschnitt 2 auch mit einem blinden
 *    „haenge immer irgendwas an" erfuellt.
 * ════════════════════════════════════════════════════════════════════════ */
kopf('4) Gegenrichtung: ohne Anmeldung kein Token in der Adresse');
{
    const { win, render, zustand } = seite(null, null);
    const href = chipHref(win, render(CHIP_MD));
    check(href !== '', 'der Chip entsteht trotzdem (die Anzeige haengt nicht am Token)');
    check(!/[?&]token=/.test(href), 'aber er traegt KEIN Token');
    check(zustand.abrufe === 0, 'und es wird kein Abruf-Schluessel angefordert');
}

/* ══════════════════════════════════════════════════════════════════════════
 * 5. Der frische Schluessel landet WIRKLICH in der Adresse
 *    (Abschnitt 2 misst synchron – dort greift noch der Rueckfall auf das
 *    Sitzungstoken. Hier wird gewartet, bis der Abruf durch ist.)
 * ════════════════════════════════════════════════════════════════════════ */
kopf('5) Nach dem Abruf traegt die Adresse den ABRUF-SCHLUESSEL');
(async () => {
    for (const s of TOKEN_SCHLUESSEL) {
        const { win, render, zustand } = seite(s, null);
        await win.JarvisDL.bereit();
        const href = chipHref(win, render(CHIP_MD));
        check(href.indexOf('token=JDL1.') > 0,
              s + ': der Link traegt JDL1 (15 Minuten Lesezugriff, nicht 30 Tage Sitzung)');
        check(href.indexOf(encodeURIComponent(zustand.key)) > 0
              || href.indexOf(zustand.key) > 0,
              s + ': und zwar genau den Schluessel aus /api/download-key');
    }

    /* Der Platzhalter wird im DOM ERSETZT, sobald der Schluessel da ist –
     * sonst bliebe ein frueh gerendertes Bild/Link dauerhaft tot. */
    kopf('5b) Platzhalter wird nach dem Abruf im DOM ersetzt');
    {
        const { win, render, zustand } = seite('jarvis_token', null);
        const html = render(CHIP_MD);                 // synchron: Platzhalter
        win.document.body.innerHTML = html;
        const a = win.document.querySelector('a.chat-doc-dl');
        const vorher = a ? a.getAttribute('href') : '';
        // KEIN Abbruch mit Exit 2: fehlt der Platzhalter, ist das ein PRODUKT-
        // Befund (z. B. Rueckfall aufs Sitzungstoken), kein kaputter Messaufbau.
        const mitPlatzhalter = /token=JDL1\.warten/.test(vorher);
        check(mitPlatzhalter, 'synchron gerendert: Platzhalter statt Sitzungstoken');
        if (mitPlatzhalter) {
            await win.JarvisDL.bereit();
            const nachher = a.getAttribute('href');
            check(nachher.indexOf('warten') < 0
                  && (nachher.indexOf(encodeURIComponent(zustand.key)) > 0 || nachher.indexOf(zustand.key) > 0),
                  'der gerenderte Link traegt danach den echten Schluessel');
            check(win.JarvisDL.veraltet(vorher), 'der Platzhalter gilt als veraltet (Klick-Netz greift)');
        }
    }

    /* Der eigene Vorrang der Seite – sonst gewinnt bei zwei Anmeldungen im
     * selben Browser die fremde Seite (siehe sitzung.js::ersterWert). */
    kopf('6) Der eigene Schluessel der Seite hat Vorrang');
    {
        const dom = new JSDOM('<!doctype html><html><body></body></html>',
            { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
        const win = dom.window;
        win.localStorage.setItem('jarvis_token', 'fremd:1:aaa');
        win.localStorage.setItem('jarvis_chat_token', 'eigen:1:bbb');
        win.localStorage.setItem('jarvis_user', 'fremd.person');
        win.localStorage.setItem('jarvis_chat_user', 'eigen.person');
        win.eval(SITZUNG);
        check(win.JarvisSitzung.token('jarvis_chat_token') === 'eigen:1:bbb',
              'mit Vorrang-Argument gewinnt der eigene Schluessel');
        check(win.JarvisSitzung.benutzer('jarvis_chat_user') === 'eigen.person',
              'dasselbe fuer den Benutzernamen');
        check(win.JarvisSitzung.token() === 'fremd:1:aaa',
              'ohne Argument gilt die gemeinsame Reihenfolge (jarvis_token zuerst)');
    }

    bilanz();
    process.exit(FAIL ? 1 : 0);
})();
