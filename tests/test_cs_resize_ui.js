/* ═══════════════════════════════════════════════════════════════════════
   Waechter: Ziehgriff der Verlaufsleiste in /chat
   ───────────────────────────────────────────────────────────────────────
   Die Breite der Leiste laesst sich seit 2026-09-13 ziehen. Der teuerste
   Fehler dabei ist NICHT das Ziehen selbst, sondern was er kaputt macht:

   ⚠ EIN INLINE-STYLE AUF `.chat-sidebar` SCHLAEGT DIE EINKLAPP-REGEL.
     `.chat-screen.sidebar-collapsed .chat-sidebar { flex-basis: 0; width: 0 }`
     ist eine Klassenregel – Inline gewinnt gegen jede Klasse. Wer die gezogene
     Breite direkt auf die Leiste schreibt, macht das Einklappen ab dem ersten
     Zug dauerhaft wirkungslos, und zwar STILL: der Knopf ist da, die Klasse
     wird gesetzt, es passiert nur nichts. Deshalb steht die Breite als
     Variable `--cs-w` auf `#chat-screen`.

   Geprueft wird die EIGENSCHAFT, nicht die Schreibweise: nicht "steht
   `--cs-w` in der Datei", sondern "die Leiste liest ihre Breite aus der
   Variablen UND das JS fasst die Leiste nicht direkt an".

   Das LAYOUT (Trefferflaeche, Zug, Grenzen, Kontrast) kann jsdom nicht –
   dafuer gibt es tests/live_cs_resize_ui_dev.py mit echtem Chrome.

   Ausgefuehrt: node tests/test_cs_resize_ui.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM = null;
for (const kandidat of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom',
                        '/usr/share/nodejs/jsdom', '/opt/jarvis/data/node_modules/jsdom']) {
    if (!kandidat) continue;
    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }
}
// Exit 2, nicht 0: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const WURZEL = path.resolve(__dirname, '..');
const FE = path.join(WURZEL, 'frontend');
const lies = (rel) => fs.readFileSync(path.join(FE, rel), 'utf-8');

let ok = 0, fail = 0;
function pruefe(text, bedingung, zusatz) {
    if (typeof text !== 'string' || typeof bedingung === 'string') {
        console.error('TESTFEHLER: pruefe(Text, Bedingung) vertauscht:', text);
        process.exit(2);
    }
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}
process.on('unhandledRejection', (e) => {
    fail++; console.log('  FAIL unbehandelte Zurueckweisung: ' + ((e && e.message) || e));
});

const CSS  = lies('css/chat.css');
const HTML = lies('chat.html');
const JS   = lies('js/chat.js');
const I18N = lies('js/i18n.js');

/* Kommentare weg – ein Waechter darf nicht seine eigene Begruendung lesen
 * (Register). Die Kommentare an diesen Stellen nennen `flex-basis`, `width`
 * und `--cs-w` woertlich, mehrfach. */
const ohneKommentarCss = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '');
const ohneKommentarJs  = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '')
                                 .replace(/^[ \t]*\/\/.*$/gm, '');

/* Der CSS-Block einer Regel – an der STRUKTUR geschnitten, nicht an einer
 * Textmarke im Fliesstext. */
function regel(selektor) {
    const roh = ohneKommentarCss(CSS);
    const i = roh.indexOf(selektor + ' {');
    if (i < 0) return '';
    const a = roh.indexOf('{', i), b = roh.indexOf('}', a);
    return (a < 0 || b < 0) ? '' : roh.slice(a + 1, b);
}
/* Eine Funktion aus chat.js – geklammert gezaehlt, nicht bis zum ersten
 * `\n}`: eine Einzeiler-Funktion dahinter wuerde sonst mitgeschnitten und der
 * Waechter pruefte fremden Code (Register). */
function funktion(name) {
    const roh = JS;
    const i = roh.indexOf('function ' + name + '(');
    if (i < 0) return '';
    const auf = roh.indexOf('{', i);
    let tief = 0;
    for (let j = auf; j < roh.length; j++) {
        if (roh[j] === '{') tief++;
        else if (roh[j] === '}') { tief--; if (tief === 0) return roh.slice(i, j + 1); }
    }
    return '';
}

// ═══ 1. Die Breite steht als Variable auf dem SCREEN ═══════════════════════
console.log('\n1. Breite als Variable (die Einklapp-Zusage)');
{
    const screen = regel('.chat-screen');
    pruefe('.chat-screen definiert --cs-w', /--cs-w:\s*\d+px/.test(screen),
           screen.trim().replace(/\s+/g, ' '));

    const leiste = regel('.chat-sidebar');
    pruefe('.chat-sidebar liest die Breite aus var(--cs-w)',
           /flex:\s*0\s+0\s+var\(--cs-w\)/.test(leiste) && /width:\s*var\(--cs-w\)/.test(leiste),
           leiste.trim().replace(/\s+/g, ' '));
    pruefe('.chat-sidebar setzt KEINE feste Pixelbreite mehr',
           !/(flex-basis|width):\s*\d+px/.test(leiste),
           leiste.trim().replace(/\s+/g, ' '));

    // Die Einklapp-Regel muss die Leiste weiterhin DIREKT auf 0 setzen – ueber
    // die Variable ginge es nicht, sie steht eine Ebene hoeher.
    const zu = regel('.chat-screen.sidebar-collapsed .chat-sidebar');
    pruefe('die Einklapp-Regel setzt flex-basis/width weiterhin direkt auf 0',
           /flex-basis:\s*0/.test(zu) && /width:\s*0/.test(zu),
           zu.trim().replace(/\s+/g, ' '));

    // ⚠ DIE TRAGENDE REGEL: das JS darf die Leiste nicht direkt anfassen.
    const js = ohneKommentarJs(JS);
    const direkt = /(chat-sidebar[^\n]*|leiste)\s*\.style\.(width|flexBasis|flex)\s*=/.test(js)
                || /setProperty\(\s*['"]--cs-w['"][^)]*\)/.test(js) === false;
    const setzt = js.match(/([A-Za-z_$][\w$]*)\.style\.setProperty\(\s*['"]--cs-w['"]/);
    pruefe('das JS setzt --cs-w ueber setProperty (nicht width/flexBasis)',
           !!setzt, setzt ? setzt[0] : 'keine setProperty-Zuweisung gefunden');
    pruefe('kein Inline-Style auf der Leiste selbst (sonst braeche das Einklappen)',
           !/(chat-sidebar|leiste)[^\n]{0,40}\.style\.(width|flexBasis)\s*=/.test(js));
    // Und das Ziel der Zuweisung ist der SCREEN, nicht die Leiste.
    const anwenden = ohneKommentarJs(funktion('_csBreiteAnwenden'));
    pruefe('_csBreiteAnwenden schreibt auf #chat-screen',
           /getElementById\(\s*['"]chat-screen['"]\s*\)/.test(anwenden) &&
           /screen\.style\.setProperty\(\s*['"]--cs-w['"]/.test(anwenden),
           anwenden.slice(0, 200).replace(/\s+/g, ' '));
}

// ═══ 2. Der Griff sitzt richtig im DOM ═════════════════════════════════════
console.log('\n2. Der Griff im DOM');
{
    const dom = new JSDOM(HTML, { runScripts: 'outside-only' });
    const d = dom.window.document;
    const griff = d.getElementById('cs-resize');
    const leiste = d.getElementById('chat-sidebar');
    const haupt = d.getElementById('chat-main');

    pruefe('der Griff existiert', !!griff);
    pruefe('er ist GESCHWISTER der Leiste, nicht ihr Kind '
           + '(die Leiste scrollt – ein Kind wanderte mit)',
           !!griff && !!leiste && !leiste.contains(griff) &&
           griff.parentElement === leiste.parentElement,
           griff ? griff.parentElement && griff.parentElement.id : '-');
    pruefe('er steht ZWISCHEN Leiste und Chatbereich',
           !!griff && !!leiste && !!haupt &&
           (leiste.compareDocumentPosition(griff) & 4) !== 0 &&   // griff folgt der Leiste
           (griff.compareDocumentPosition(haupt) & 4) !== 0);      // haupt folgt dem Griff

    pruefe('role="separator" + aria-orientation="vertical"',
           !!griff && griff.getAttribute('role') === 'separator' &&
           griff.getAttribute('aria-orientation') === 'vertical');
    pruefe('mit der Tastatur erreichbar (tabindex)',
           !!griff && griff.getAttribute('tabindex') === '0');
    pruefe('beschriftet, und die Beschriftung folgt dem Sprachwechsel',
           !!griff && !!griff.getAttribute('title') &&
           griff.getAttribute('data-i18n-title') === 'chat.sidebar_resize' &&
           griff.getAttribute('data-i18n-aria') === 'chat.sidebar_resize');

    dom.window.close();
}

// ═══ 3. CSS-Zusagen, die man ohne Browser pruefen kann ═════════════════════
console.log('\n3. CSS-Zusagen');
{
    const g = regel('.cs-resize');
    pruefe('col-resize als Zeiger', /cursor:\s*col-resize/.test(g), g.replace(/\s+/g, ' '));
    pruefe('touch-action: none – ohne das nimmt der Browser die Geste als Scrollen',
           /touch-action:\s*none/.test(g), g.replace(/\s+/g, ' '));
    pruefe('Trefferflaeche mind. 5px breit (1px findet mit der Maus niemand)',
           /flex:\s*0\s+0\s+([5-9]|\d{2,})px/.test(g), g.replace(/\s+/g, ' '));

    pruefe('eingeklappt ist der Griff weg',
           /display:\s*none/.test(regel('.chat-screen.sidebar-collapsed .cs-resize')));

    // ⚠ OHNE DAS LAEUFT DIE LEISTE DEM ZEIGER HINTERHER: .chat-sidebar animiert
    // flex-basis/width fuers Einklappen.
    pruefe('waehrend des Ziehens ist die Transition der Leiste aus',
           /transition:\s*none/.test(regel('body.cs-resizing .chat-sidebar')));
    pruefe('waehrend des Ziehens keine Textauswahl',
           /user-select:\s*none/.test(regel('body.cs-resizing')));

    // :focus-visible statt :focus – sonst bliebe nach jedem Mausklick ein
    // Strich stehen (Projektregel).
    const ohneK = ohneKommentarCss(CSS);
    pruefe('Fokus ueber :focus-visible sichtbar gemacht',
           /\.cs-resize:focus-visible::before/.test(ohneK));

    // Die Media-Query darf die Leiste nicht mehr direkt setzen, sonst gewinnt
    // sie gegen den gezogenen Wert (gleiche Spezifitaet, spaeter in der Datei).
    const mq = ohneK.slice(ohneK.indexOf('@media (max-width: 720px)'));
    const mqBlock = mq.slice(0, mq.indexOf('}', mq.indexOf('}') + 1) + 1);
    pruefe('die 720px-Media-Query setzt nur noch die Vorgabe (--cs-w)',
           /--cs-w:\s*\d+px/.test(mqBlock) && !/\.chat-sidebar\s*\{[^}]*flex-basis/.test(mqBlock),
           mqBlock.replace(/\s+/g, ' '));
}

// ═══ 4. Verhalten: Grenzen, Speichern, Rueckweg ════════════════════════════
console.log('\n4. Verhalten');
{
    const js = ohneKommentarJs(JS);
    pruefe('_initSidebarResize wird verdrahtet',
           /_initSidebarResize\(\s*\)\s*;/.test(js.replace(/function _initSidebarResize[\s\S]*/, '')) ||
           /^\s*_initSidebarResize\(\);/m.test(js));

    const init = ohneKommentarJs(funktion('_initSidebarResize'));
    pruefe('Pointer-Events statt mousemove am Dokument (Touch/Stift, Capture)',
           /addEventListener\(\s*['"]pointerdown['"]/.test(init) &&
           /addEventListener\(\s*['"]pointermove['"]/.test(init), '');
    pruefe('setPointerCapture – die Bewegung bleibt beim Griff',
           /setPointerCapture/.test(init));
    pruefe('pointercancel wird behandelt (sonst haengt die Leiste im Zug fest)',
           /addEventListener\(\s*['"]pointercancel['"]/.test(init));
    pruefe('Tastatur: Pfeiltasten wirken',
           /ArrowLeft/.test(init) && /ArrowRight/.test(init));
    pruefe('Doppelklick stellt die Vorgabe her',
           /addEventListener\(\s*['"]dblclick['"]/.test(init));
    pruefe('ein kleineres Fenster zieht die Breite nach',
           /addEventListener\(\s*['"]resize['"]/.test(init));
    pruefe('nur die linke Maustaste zieht',
           /e\.button\s*!==\s*0/.test(init), init.slice(0, 400).replace(/\s+/g, ' '));

    const max = ohneKommentarJs(funktion('_csMax'));
    pruefe('die Obergrenze rechnet am AKTUELLEN Fenster, nicht als feste Zahl',
           /window\.innerWidth/.test(max), max.replace(/\s+/g, ' '));

    const zurueck = ohneKommentarJs(funktion('_csBreiteZuruecksetzen'));
    pruefe('Zuruecksetzen NIMMT die Variable weg (nur so gilt die Media-Query wieder)',
           /removeProperty\(\s*['"]--cs-w['"]\s*\)/.test(zurueck),
           zurueck.replace(/\s+/g, ' '));
    pruefe('und raeumt den gespeicherten Wert ab',
           /removeItem\(\s*_CS_W_KEY\s*\)/.test(zurueck));

    const lesen = ohneKommentarJs(funktion('_csGespeicherteBreite'));
    pruefe('ein kaputter gespeicherter Wert gilt als KEINE Angabe (kein NaN in die Breite)',
           /Number\.isFinite/.test(lesen), lesen.replace(/\s+/g, ' '));

    /* Gespeichert wird am Ende des Zuges, nicht bei jeder Bewegung.
     * ⚠ GEMESSEN WIRD DER HANDLER, NICHT EIN MUSTER: ein Regex ueber den Aufruf
     * scheiterte an den inneren Klammern von `(e.clientX - startX)` – `[^)]*`
     * kann sie nicht ueberspringen, und der Waechter meldete einen Fehler, den
     * es nicht gab. Der Rumpf wird deshalb geklammert geschnitten. */
    function handler(quelle, ereignis) {
        const i = quelle.indexOf("'" + ereignis + "'");
        if (i < 0) return '';
        const auf = quelle.indexOf('{', i);
        let tief = 0;
        for (let j = auf; j < quelle.length; j++) {
            if (quelle[j] === '{') tief++;
            else if (quelle[j] === '}') { tief--; if (tief === 0) return quelle.slice(auf, j + 1); }
        }
        return '';
    }
    const bewegen = handler(init, 'pointermove');
    pruefe('der pointermove-Handler wurde gefunden (Positivkontrolle der Messung)',
           bewegen.length > 20, bewegen);
    pruefe('pointermove speichert NICHT (sonst hunderte Schreibzugriffe je Zug)',
           bewegen.length > 20 && !/setItem/.test(bewegen) && !/,\s*true\s*\)/.test(bewegen),
           bewegen.replace(/\s+/g, ' '));
    const los = handler(init, 'pointerup');
    pruefe('am Ende des Zuges wird gespeichert',
           /_csBreiteAnwenden|ende/.test(los) || /function ende/.test(init), los);
}

// ═══ 5. i18n in beiden Sprachen ════════════════════════════════════════════
console.log('\n5. i18n');
{
    const treffer = I18N.match(/'chat\.sidebar_resize':\s*'([^']*)'/g) || [];
    pruefe('chat.sidebar_resize ist in DE und EN gesetzt', treffer.length === 2,
           treffer.join(' | '));
    pruefe('die beiden Fassungen sind wirklich uebersetzt (nicht kopiert)',
           treffer.length === 2 && treffer[0] !== treffer[1], treffer.join(' | '));
}

console.log(`\nErgebnis: ${ok}/${ok + fail}`);
process.exit(fail === 0 ? 0 : 1);
