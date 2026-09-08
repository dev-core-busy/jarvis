#!/usr/bin/env node
/**
 * Waechter: der Netzwerkpfad einer Wissensquelle wird zum LINK.
 *
 * WAS GEMELDET WURDE (Betreiber, 2026-09-08)
 * ------------------------------------------
 * "wir haben doch an allen Stellen URLs als link dargestellt - hier bitte auch".
 * Die Quellangabe im Chat war reiner Text.
 *
 * ⚠ EIN `file://`-LINK LEISTET DAS NICHT – im echten Chrome gemessen: die
 * Navigation von einer https-Seite aus wird verworfen, OHNE Meldung und ohne
 * eine einzige Konsolenzeile. Der Klick tut sichtbar gar nichts. Deshalb zeigt
 * der Link auf `/api/knowledge/netzquelle`, das die Datei aus der
 * Wissensdatenbank ausliefert; der sichtbare Text bleibt der Netzwerkpfad.
 *
 * ⚠ UND DER PFAD STEHT IN BACKTICKS – live gemessen schreibt das Modell
 * "**Quelle:** `\\\\host\\freigabe\\…`". `renderMarkdown` sichert Inline-Code
 * als ERSTES in einen Platzhalter; ein Autolinker weiter unten saehe ihn also
 * NIE. Genau dieser Fall ist die wichtigste Pruefung hier.
 *
 * Gemessen wird am ECHTEN `renderMarkdown` gegen ein echtes DOM – nicht am
 * Quelltext: ob ein Link entsteht, kann eine Textsuche nicht beantworten.
 *
 * Aufruf: node tests/test_quell_netzpfad_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const W = path.resolve(__dirname, '..');

let OK = 0, FAIL = 0, BILANZ = false;

function check(b, t) {
    if (b) { OK++; console.log('  \x1b[32mOK\x1b[0m   ' + t); }
    else { FAIL++; console.log('  \x1b[31mFAIL\x1b[0m ' + t); }
}
function sicher(fn, t) {
    try { check(fn(), t); }
    catch (e) { check(false, t + ' [wirft: ' + e.message + ']'); }
}
function kopf(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

// jsdom an allen ueblichen Orten suchen – ein Waechter, der nur auf einem
// Rechner laeuft, ist ein halber. Ohne Parser gibt es KEINE Aussage: Exit 2.
let JSDOM = null;
for (const p of [process.env.JSDOM_PATH, W + '/node_modules/jsdom',
                 '/tmp/node_modules/jsdom', W + '/data/node_modules/jsdom',
                 '/usr/share/nodejs/jsdom', 'jsdom']) {
    if (!p) continue;
    try { JSDOM = require(p).JSDOM; break; } catch (e) { /* weiter */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH setzen)'); process.exit(2); }

// Ein Wachhund: haengt der Lauf, endet er MIT Bilanz statt still (Exit 0).
const hund = setTimeout(() => {
    console.log('\x1b[31mFAIL\x1b[0m Wachhund: der Lauf haengt');
    FAIL++; bilanz(); process.exit(1);
}, 40000);
hund.unref && hund.unref();

function bilanz() {
    if (BILANZ) return;
    BILANZ = true;
    console.log('\n' + '='.repeat(62));
    console.log('\x1b[1mErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL\x1b[0m');
}
process.on('exit', () => { if (!BILANZ) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; } });

// ── Der ECHTE renderMarkdown, in einem echten DOM ───────────────────────────
function lade(mitDlKey) {
    const dom = new JSDOM('<body></body>', { url: 'https://x.test/chat' });
    const win = dom.window;
    global.window = win; global.document = win.document;
    global.localStorage = win.localStorage;
    win.localStorage.setItem('jarvis_token', 'sven:1:sitzung');
    if (mitDlKey) {
        // dlkey.js stellt den Abruf-Schluessel; genau der gehoert in den Link
        // (15 Minuten Lesezugriff statt 30 Tage volle Sitzung).
        win.JarvisDL = { url: (u) => u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=JDL1.a.b.c' };
    }
    win.eval(fs.readFileSync(W + '/frontend/js/chatlib.js', 'utf8'));
    return { win, R: win.JarvisChatLib.renderMarkdown };
}

const PFAD = '\\\\191.100.147.90\\OneNote_text_Jasmin\\0039_Maris\\Informationen.one';
// ⚠ MIT LEERZEICHEN – der gemeldete Fall (2026-09-08). Freigabe- und
// Dateinamen in Windows-Netzen enthalten staendig welche; ein am Leerraum
// endendes Muster schnitt den Pfad bei "…Anleitungen" ab, und in Backticks
// entstand GAR KEIN Link. Im Fliesstext ist die DATEIENDUNG das einzige
// erkennbare Ende – darauf ist das Muster verankert.
const PFAD_LZ = '\\\\191.100.147.90\\OneNote_text_Jasmin\\0039_Maris\\Anleitungen SAP.one';

function anker(html, win) {
    const d = win.document.createElement('div');
    d.innerHTML = html;
    return Array.from(d.querySelectorAll('a.jv-netzquelle'));
}

// ═════════════════════════════════════════════════════════════════════════════
function teil1() {
    kopf('1) Der Pfad wird zum Link – auch in Backticks');
    const { win, R } = lade(true);

    // DER GEMESSENE FALL: das Modell setzt den Pfad in Backticks.
    let a = anker(R('**Quelle:** `' + PFAD + '`'), win);
    check(a.length === 1, 'in Backticks: genau ein Link entsteht (' + a.length + ')');
    if (a.length) {
        check(a[0].textContent === PFAD,
              'der sichtbare Text ist der Netzwerkpfad (nicht der Serverpfad)');
        check(a[0].getAttribute('href').indexOf('/api/knowledge/netzquelle?netz=') === 0,
              'der Link zeigt auf den Ausliefer-Endpunkt');
        check(decodeURIComponent((a[0].getAttribute('href').match(/netz=([^&]+)/) || [])[1] || '')
              === PFAD, 'und uebergibt den Pfad unveraendert');
        check(/token=JDL1\./.test(a[0].getAttribute('href')),
              'mit ABRUF-SCHLUESSEL, nicht mit dem Sitzungstoken');
        check(a[0].getAttribute('target') === '_blank'
              && /noopener/.test(a[0].getAttribute('rel') || ''),
              'oeffnet in einem neuen Tab, mit noopener');
        check((a[0].getAttribute('title') || '').indexOf(PFAD) >= 0,
              'der Titel nennt den Pfad des Originals');
        check(a[0].parentElement && a[0].parentElement.tagName === 'CODE',
              'und bleibt in seinem <code> stehen (die Schreibweise des Modells)');
    }

    // ⚠ KEIN file:// – gemessen tut ein solcher Klick sichtbar gar nichts.
    check(!/file:/.test(R('`' + PFAD + '`')),
          'nirgends ein file://-Link (der Klick waere eine tote Zusage)');

    // Nackt im Text
    a = anker(R('Steht in ' + PFAD + ' – siehe dort.'), win);
    check(a.length === 1 && a[0].textContent === PFAD,
          'nackt im Text: ebenfalls ein Link');

    // Satzzeichen gehoeren nicht in den Pfad
    const html = R('Quelle: ' + PFAD + '.');
    a = anker(html, win);
    check(a.length === 1 && a[0].textContent === PFAD && /<\/a>\.$/.test(html.replace(/<\/p>|\n/g, '')),
          'ein Satzpunkt bleibt AUSSERHALB des Links');

    // ── LEERZEICHEN (der gemeldete Fall) ───────────────────────────────────
    for (const [was, txt] of [['in Backticks', '**Quelle:** `' + PFAD_LZ + '`'],
                              ['nackt im Satz', 'Steht in ' + PFAD_LZ + ' – siehe dort.'],
                              ['mit Satzpunkt', 'Quelle: ' + PFAD_LZ + '.'],
                              ['in Klammern', '(siehe ' + PFAD_LZ + ')']]) {
        const b = anker(R(txt), win);
        check(b.length === 1 && b[0].textContent === PFAD_LZ,
              'Pfad MIT LEERZEICHEN, ' + was + ': vollstaendig verlinkt'
              + (b.length ? ' (' + JSON.stringify(b[0].textContent) + ')' : ' (KEIN Link)'));
    }
    // Zwei Pfade mit Leerzeichen in EINER Zeile duerfen nicht zu einem werden.
    const zwei = anker(R('A: ' + PFAD_LZ + ' und B: \\\\srv\\s\\Zweite Datei.pdf'), win);
    check(zwei.length === 2 && zwei[0].textContent === PFAD_LZ
          && zwei[1].textContent === '\\\\srv\\s\\Zweite Datei.pdf',
          'zwei Pfade mit Leerzeichen bleiben zwei Links (' + zwei.length + ')');
    // Doppelendung gehoert ganz dazu – in Backticks UND nackt. Nackt ist der
    // strengere Fall: dort endet das Match beim ersten Erfolg, ohne den `+` im
    // Endungs-Anker also bei `.tar` (in Backticks erzwingt `^...$` ohnehin das
    // vollstaendige Match – deshalb genuegt der Backtick-Fall NICHT).
    for (const [was, txt] of [['in Backticks', '`\\\\srv\\s\\Archiv 1.tar.gz`'],
                              ['nackt', 'Liegt in \\\\srv\\s\\Archiv 1.tar.gz dort']]) {
        const tg = anker(R(txt), win);
        check(tg.length === 1 && tg[0].textContent === '\\\\srv\\s\\Archiv 1.tar.gz',
              'Doppelendung .tar.gz vollstaendig, ' + was
              + (tg.length ? ' (' + JSON.stringify(tg[0].textContent) + ')' : ''));
    }

    // NFS-Form
    a = anker(R('`srv:/export/a/b.pdf`'), win);
    check(a.length === 1 && a[0].textContent === 'srv:/export/a/b.pdf',
          'die NFS-Form wird ebenso verlinkt');

    win.close();
}

function teil2() {
    kopf('2) Was NICHT verlinkt werden darf');
    const { win, R } = lade(true);

    // Ein Laufwerksbuchstabe ist keine Netzwerkquelle – sonst wird aus jedem
    // Windows-Pfad im Chat ein Link auf eine Datei, die es hier nicht gibt.
    check(anker(R('`C:/temp/x.pdf`'), win).length === 0,
          'C:/temp/x.pdf ist KEINE Netzwerkquelle');
    // ⚠ BEWUSST: ohne Endung wird NICHT verlinkt. So ein Pfad liesse sich im
    // Fliesstext nicht begrenzen – ein abgeschnittener Link ist schlimmer als
    // reiner Text, er fuehrt auf einen 404.
    check(anker(R('Ordner `\\\\srv\\Meine Freigabe\\Unterordner` hier'), win).length === 0,
          'ein Pfad OHNE Endung wird nicht verlinkt (kein 404-Link)');
    check(R('`npm install`').indexOf('jv-netzquelle') < 0,
          'gewoehnlicher Inline-Code bleibt Code');
    check(R('`sudo systemctl restart jarvis.service`').indexOf('jv-netzquelle') < 0,
          'ein Befehl mit Punkten bleibt Code');

    // Eine gewoehnliche URL gehoert dem bestehenden Autolinker – nicht uns.
    let h = R('Siehe https://example.com/a.pdf');
    check(h.indexOf('jv-netzquelle') < 0 && h.indexOf('href="https://example.com/a.pdf"') >= 0,
          'eine http(s)-URL wird wie bisher verlinkt');

    // Ein Codeblock MIT Text drumherum bleibt Code (nur ein reiner Pfad wird Link).
    check(anker(R('`Pfad: ' + PFAD + '`'), win).length === 0,
          'Code mit Text drumherum bleibt unangetastet');

    // KEIN Doppel-Link: ein bereits gebauter <a> darf nicht erneut verlinkt werden.
    const d = R('[Quelle](/api/knowledge/netzquelle?netz=x) und ' + PFAD);
    const div = win.document.createElement('div'); div.innerHTML = d;
    check(div.querySelectorAll('a a').length === 0, 'kein Link im Link');

    win.close();
}

function teil3() {
    kopf('3) Ohne dlkey.js: Rueckfall aufs Sitzungstoken');
    const { win, R } = lade(false);
    const a = anker(R('`' + PFAD + '`'), win);
    check(a.length === 1, 'der Link entsteht auch ohne dlkey.js');
    // Ohne Token waere der Link ein 401 – ein toter Link ist schlechter als der
    // bekannte Zustand (gleiche Abwaegung wie beim Download-Chip).
    check(a.length === 1 && /token=/.test(a[0].getAttribute('href')),
          'und traegt ein Token (sonst 401)');
    win.close();
}

function teil4() {
    kopf('4) Beiwerk: CSS und Texte');
    const css = fs.readFileSync(W + '/frontend/css/theme.css', 'utf8');
    // Kommentare weg – sonst liest der Waechter seine eigene Begruendung.
    const rein = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const m = rein.match(/\.jv-netzquelle\s*\{([^}]*)\}/);
    check(!!m, 'die Regel .jv-netzquelle steht in theme.css (nicht in chat.css: '
             + 'renderMarkdown laeuft auch auf /support und /sap)');
    // Ein UNC-Pfad ist ein Wort ohne Trennstelle und sprengt sonst die Blase.
    check(!!m && /(overflow-wrap|word-break)\s*:/.test(m[1]),
          'und erlaubt den Umbruch eines Pfades ohne Trennstelle');

    // ⚠ IM HELLEN THEMA WAR JEDER LINK IN EINER BLASE UNLESBAR (gemessen:
    // 2,13:1 in der Blase, 1,83:1 im <code>; Grenze 4,5:1). Das betrifft nicht
    // nur den Quell-Link, aber ohne die Regel ist AUSGERECHNET der Pfad, den
    // der Benutzer lesen soll, nicht zu lesen. Geprueft wird die REGEL – der
    // gemessene Wert steht in der Live-Abnahme, jsdom rechnet kein color-mix.
    const chat = fs.readFileSync(W + '/frontend/css/chat.css', 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '');
    const hell = chat.match(/body\.light\s+\.msg-bubble\s+a\s*\{([^}]*)\}/);
    check(!!hell && /color\s*:/.test(hell[1]),
          'body.light .msg-bubble a setzt eine eigene, dunklere Linkfarbe');
    check(!!hell && /var\(--accent/.test(hell[1]),
          'und leitet sie aus --accent ab (ein fester Ton waere brandingblind)');

    const i18n = fs.readFileSync(W + '/frontend/js/i18n.js', 'utf8');
    check((i18n.match(/'media\.netz_hint'/g) || []).length === 2,
          'der Titel-Text steht in DE und EN');

    const lib = fs.readFileSync(W + '/frontend/js/chatlib.js', 'utf8');
    check(/knowledge\\\/netzquelle/.test(lib) || /knowledge\/netzquelle/.test(lib),
          'chatlib kennt den Endpunkt');
    // Das Token darf NUR ins gerenderte DOM – _withToken laeuft bei jeder
    // Anzeige neu, der gespeicherte Markdown bleibt token-frei (Register).
    check(/_withToken\('\/api\/knowledge\/netzquelle/.test(lib),
          'der Token kommt ueber _withToken (also erst beim Rendern)');
}

try {
    [teil1, teil2, teil3, teil4].forEach((t) => {
        try { t(); }
        catch (e) { check(false, 'Abschnitt ' + t.name + ' bricht ab: ' + e.message); }
    });
} finally {
    clearTimeout(hund);
    bilanz();
    process.exit(FAIL ? 1 : 0);
}
