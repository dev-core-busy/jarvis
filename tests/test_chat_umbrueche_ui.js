/* ═══════════════════════════════════════════════════════════════════════
   Waechter: Zeilenumbrueche im EIGENEN Chat-Text bleiben stehen
   ───────────────────────────────────────────────────────────────────────
   GEMELDET AUF ECHT (2026-08-31): "einen Text mit Zeilenumbruechen kopiert und
   abgesendet. In der Anzeige sind dann die Zeilenumbrueche weg."

   Gemessen wurde damals an vier Stellen getrennt – Eingabe, Anzeige, Speicher,
   Bot-Gegenprobe – und verloren ging NUR die Anzeige: `escapeHtml()` erzeugt
   kein <br> (richtig so, es ist die Sicherheitsschranke), und `.msg-bubble`
   hatte keine `white-space`-Regel. Die \n standen im DOM und im Transkript.

   ⚠ DIESER WAECHTER PRUEFT DIE EIGENSCHAFT, NICHT DIE SCHREIBWEISE. Nicht
   "steht `white-space: pre-wrap` in der Datei", sondern: bleibt der Umbruch
   erhalten, UND kommt er ueber `textContent` zurueck? Letzteres ist der Grund
   fuer pre-wrap statt <br> – ein Test, der nur die CSS-Zeile sucht, wuerde eine
   Umstellung auf <br> durchlassen und damit das Bearbeiten brechen.

   Ausgefuehrt: node tests/test_chat_umbrueche_ui.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM = null;
for (const kandidat of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom']) {
    if (!kandidat) continue;
    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }
}
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

const CSS = lies('css/chat.css');
const CHAT_JS = lies('js/chat.js');
const TEXT = 'Zeile 1\nZeile 2\n\nZeile 4';

/* Der CSS-Block einer Regel – geschnitten an der STRUKTUR, nicht an einer
 * Textmarke im Fliesstext (Register: eine Schnittgrenze aus einem fremden
 * Abschnitt umfasst irgendwann mehr, als sie soll). */
function regel(selektor) {
    const i = CSS.indexOf(selektor + ' {');
    if (i < 0) return '';
    const a = CSS.indexOf('{', i), b = CSS.indexOf('}', a);
    return (a < 0 || b < 0) ? '' : CSS.slice(a + 1, b);
}
/* Kommentare weg – ein Waechter darf nicht seine eigene Begruendung lesen.
 * Der Kommentar an der Regel nennt `white-space: normal` und `<br>` woertlich. */
const ohneKommentar = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '');

// ═══ 1. Die Regel steht am RICHTIGEN Ort ══════════════════════════════════
console.log('\n1. Die Regel');
{
    const user = ohneKommentar(regel('.msg-row.user .msg-bubble'));
    pruefe('die Benutzer-Blase setzt white-space: pre-wrap',
           /white-space:\s*pre-wrap/.test(user), user.trim().replace(/\s+/g, ' '));

    // Bot-Blasen enthalten echtes HTML (Listen, <pre>, Tabellen) – dort waere
    // pre-wrap ein Layoutfehler, und noetig ist es nicht: renderMarkdown setzt
    // die <br> selbst.
    const bot = ohneKommentar(regel('.msg-row.bot .msg-bubble'));
    pruefe('die BOT-Blase bekommt es NICHT', !/white-space:\s*pre/.test(bot),
           bot.trim().replace(/\s+/g, ' '));
    const alle = ohneKommentar(regel('.msg-bubble'));
    pruefe('und die gemeinsame .msg-bubble ebenfalls nicht',
           !/white-space:\s*pre/.test(alle), alle.trim().replace(/\s+/g, ' '));

    // `white-space` erbt: Chips und Galerie bringen eingeruecktes Markup mit.
    pruefe('Element-Kinder der Benutzer-Blase stellen white-space zurueck',
           /\.msg-row\.user \.msg-bubble > \*\s*\{[^}]*white-space:\s*normal/.test(
               CSS.replace(/\/\*[\s\S]*?\*\//g, '')));
}

// ═══ 2. Die WIRKUNG – gemessen, nicht gelesen ═════════════════════════════
/* jsdom rechnet kein Layout, wertet aber Stylesheets aus: `getComputedStyle`
 * liefert die kaskadierte `white-space`. Genau das ist die Aussage, auf die es
 * ankommt – ob der Browser den Umbruch behaelt. */
console.log('\n2. Wirkung im DOM');
{
    const dom = new JSDOM(
        '<html><head><style>' + CSS + '</style></head><body>'
        + '<div class="msg-row user"><div class="msg-bubble" id="u"></div></div>'
        + '<div class="msg-row bot"><div class="msg-bubble" id="b"></div></div>'
        + '</body></html>');
    const w = dom.window, d = w.document;

    // Genau der Weg aus chat.js: escapeHtml(text) in die Blase.
    const escapeHtml = (str) => { const x = d.createElement('div'); x.textContent = str; return x.innerHTML; };
    const u = d.getElementById('u');
    u.innerHTML = escapeHtml(TEXT);

    pruefe('escapeHtml erzeugt KEIN <br> (das ist der Ausgangsbefund)',
           u.querySelectorAll('br').length === 0);
    pruefe('die \\n stehen im DOM – verloren geht nichts',
           (u.textContent.match(/\n/g) || []).length === 3,
           JSON.stringify(u.textContent));
    pruefe('der Browser BEHAELT sie: white-space ist pre-wrap',
           w.getComputedStyle(u).whiteSpace === 'pre-wrap',
           w.getComputedStyle(u).whiteSpace);
    pruefe('bei der Bot-Blase bleibt es bei normal',
           /^(normal|)$/.test(w.getComputedStyle(d.getElementById('b')).whiteSpace),
           w.getComputedStyle(d.getElementById('b')).whiteSpace);

    /* ⚠ DIE ZUSAGE, DIE `<br>` NICHT HALTEN KOENNTE: der Text kommt ueber
     * `textContent` mit Umbruechen zurueck. Daran haengen Bearbeiten,
     * Wiederholen und Kopieren. */
    pruefe('der Text kommt ueber textContent VOLLSTAENDIG zurueck',
           u.textContent === TEXT, JSON.stringify(u.textContent));

    // Gegenprobe: mit <br> waere genau diese Zusage gebrochen.
    const v = d.createElement('div');
    v.innerHTML = escapeHtml(TEXT).replace(/\n/g, '<br>');
    pruefe('Gegenprobe: mit <br> liefert textContent KEINE Umbrueche mehr '
           + '(deshalb pre-wrap)', (v.textContent.match(/\n/g) || []).length === 0,
           JSON.stringify(v.textContent));

    // Ein Element-Kind (Anhang-Chip) erbt pre-wrap NICHT.
    const chip = d.createElement('div');
    chip.className = 'uc-file-chip';
    chip.innerHTML = '<div class="uc-fc-icon">X</div>\n                <div>Y</div>';
    u.appendChild(chip);
    pruefe('ein Anhang-Chip in der Blase erbt pre-wrap NICHT',
           w.getComputedStyle(chip).whiteSpace === 'normal',
           w.getComputedStyle(chip).whiteSpace);

    w.close();
}

// ═══ 3. Der Renderweg bleibt, wie er ist ══════════════════════════════════
/* Die Loesung liegt bewusst im CSS: am Renderpfad wird NICHTS geaendert.
 * `escapeHtml` fuer eigenen Text ist die Sicherheitsschranke – wer sie durch
 * einen Markup-Erzeuger ersetzt, oeffnet den Weg fuer Fremdmarkup. */
console.log('\n3. Der Renderweg ist unangetastet');
{
    const code = CHAT_JS.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
    const stellen = code.match(/role === 'user'[\s\S]{0,40}?escapeHtml\(/g) || [];
    const stellen2 = code.match(/\.role === 'user'\s*\?\s*escapeHtml\(/g) || [];
    pruefe('Benutzertext geht weiterhin durch escapeHtml (beide Stellen)',
           (stellen.length + stellen2.length) >= 2,
           String(stellen.length + stellen2.length));
    pruefe('und NICHT durch renderMarkdown',
           !/role === 'user'\s*\?\s*renderMarkdown/.test(code));
    /* ⚠ EIGENER TESTFEHLER, von diesem Lauf gefangen: die erste Fassung suchte
     * `escapeHtml(...).replace(...<br>...)` in der GANZEN Datei und traf den
     * RUECKFALL von `renderMarkdown` (chat.js:2370) – also den BOT-Pfad, wo das
     * <br> richtig ist. Gemessen wird jetzt der Benutzer-ZWEIG selbst: dort
     * steht `escapeHtml(x)` und direkt danach der Doppelpunkt des Ternaers,
     * also nichts Angehaengtes. */
    const zweige = [...code.matchAll(/role === 'user'\s*\?\s*escapeHtml\([^)]*\)\s*:/g)];
    pruefe('im Benutzerzweig haengt nichts an escapeHtml (kein \\n -> <br>)',
           zweige.length >= 2, String(zweige.length));
    // Der Eingabetext wird getrimmt – sonst erzeugte ein angehaengter Umbruch
    // unter pre-wrap eine sichtbare Leerzeile am Blasenende.
    pruefe('der Eingabetext wird getrimmt (keine Leerzeile am Blasenende)',
           /msgInput\.value\.trim\(\)/.test(code));
}

// ═══ 4. Cache-Buster mitgezogen ═══════════════════════════════════════════
console.log('\n4. Ausliefern');
{
    const seiten = fs.readdirSync(FE).filter((f) => f.endsWith('.html'));
    const staende = new Set();
    for (const f of seiten) {
        const s = fs.readFileSync(path.join(FE, f), 'utf-8');
        const m = s.match(/chat\.css\?v=(\d+)/);
        if (m) staende.add(m[1]);
    }
    pruefe('chat.css ist ueberall mit demselben Stand eingebunden',
           staende.size === 1, [...staende].join(', '));
    pruefe('und der Stand wurde erhoeht (>= 50)',
           [...staende].every((v) => Number(v) >= 50), [...staende].join(', '));
}

// ═══ 5. /userchat: dieselbe Zusage, andere Blase ══════════════════════════
/* Nachgezogen auf Anweisung (2026-08-31). Dort heisst die Blase `.uc-bubble`,
 * das CSS steht INLINE in `userchat.html` (nicht in chat.css), und der Text
 * laeuft durch `linkify()` – das maskiert und macht Adressen zu <a>, erzeugt
 * aber ebenso kein <br>. Betroffen sind BEIDE Seiten (.mine und .theirs).
 *
 * ⚠ Der Waechter liest das CSS aus der HTML-Datei, nicht aus chat.css – wer die
 * Regel dorthin verschiebt, wuerde sonst unbemerkt eine Datei prüfen, die
 * /userchat gar nicht als Quelle hat. */
console.log('\n5. /userchat (.uc-bubble)');
{
    const UC_HTML = lies('userchat.html');
    const UC_JS = lies('js/userchat.js');
    const stil = (UC_HTML.match(/<style[^>]*>([\s\S]*?)<\/style>/g) || []).join('\n');
    const ohneK = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '');

    function ucRegel(sel) {
        const i = stil.indexOf(sel + ' {');
        if (i < 0) return '';
        const a = stil.indexOf('{', i), b = stil.indexOf('}', a);
        return (a < 0 || b < 0) ? '' : stil.slice(a + 1, b);
    }
    pruefe('.uc-bubble setzt white-space: pre-wrap',
           /white-space:\s*pre-wrap/.test(ohneK(ucRegel('.uc-bubble'))),
           ohneK(ucRegel('.uc-bubble')).trim().replace(/\s+/g, ' '));
    pruefe('Element-Kinder stellen white-space zurueck (Galerie, Datei-Chips)',
           /\.uc-bubble > \*\s*\{[^}]*white-space:\s*normal/.test(ohneK(stil)));

    // WIRKUNG: mit dem echten Inline-CSS gemessen, fuer BEIDE Seiten.
    const dom = new JSDOM(
        '<html><head><style>' + stil + '</style></head><body>'
        + '<div class="uc-bubble mine" id="m"></div>'
        + '<div class="uc-bubble theirs" id="t"></div>'
        + '</body></html>');
    const w = dom.window, d = w.document;
    for (const [id, name] of [['m', 'eigene Nachricht (.mine)'],
                              ['t', 'fremde Nachricht (.theirs)']]) {
        const el = d.getElementById(id);
        el.textContent = TEXT;
        pruefe(name + ': der Browser behaelt die Umbrueche',
               w.getComputedStyle(el).whiteSpace === 'pre-wrap',
               w.getComputedStyle(el).whiteSpace);
        pruefe(name + ': textContent liefert sie vollstaendig zurueck',
               el.textContent === TEXT, JSON.stringify(el.textContent));
    }
    // Ein Datei-Chip erbt pre-wrap nicht.
    const chip = d.createElement('div');
    chip.className = 'uc-file-chip';
    d.getElementById('m').appendChild(chip);
    pruefe('ein Datei-Chip in der Blase erbt pre-wrap NICHT',
           w.getComputedStyle(chip).whiteSpace === 'normal',
           w.getComputedStyle(chip).whiteSpace);
    w.close();

    /* Der Renderweg bleibt: `linkify` maskiert selbst (es ist die
     * Sicherheitsschranke dieser Seite) und darf kein <br> bauen. */
    const code = UC_JS.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
    const stellen = code.match(/innerHTML\s*=\s*linkify\(/g) || [];
    pruefe('alle Blasen-Renderstellen gehen weiter durch linkify (3 erwartet)',
           stellen.length >= 3, String(stellen.length));
    pruefe('linkify baut kein <br>',
           !/<br>/.test((code.match(/function linkify[\s\S]{0,600}?\n    \}/) || [''])[0]));
    // Getrimmt: sonst erzeugte ein angehaengter Umbruch eine Leerzeile.
    pruefe('der Nachrichtentext wird getrimmt',
           (code.match(/\(msg\.text \|\| ''\)\.trim\(\)/g) || []).length >= 2);

    // Cache-Buster: userchat.html ist selbst die CSS-Quelle, aber chat.css
    // liegt dort ebenfalls – der Stand muss zu /chat passen (Abschnitt 4).
    pruefe('userchat.html bindet chat.css mit demselben Stand ein wie /chat',
           /chat\.css\?v=50/.test(UC_HTML));
}

console.log('\n' + (fail === 0 ? 'ALLE ' + ok + ' PRUEFUNGEN OK' : ok + ' OK, ' + fail + ' FAIL'));
process.exit(fail === 0 ? 0 : 1);
