#!/usr/bin/env node
/**
 * MESSUNG (aendert nichts): unterscheidet der Anhang-Weg von /chat zwischen
 * GIF und JPG?
 *
 * Anlass ist die Meldung "unter /chat wird ein GIF als Vorschau angezeigt, ein
 * JPG aber nicht". Gemessen wird der ECHTE Weg: `addFiles()` und
 * `renderPreviews()` werden aus `frontend/js/chat.js` geschnitten und
 * AUSGEFUEHRT, mit echten File-Objekten. Eine Quelltext-Lesung koennte die
 * Frage nicht beantworten - ob am Ende ein <img> mit brauchbarer Adresse
 * dasteht, zeigt nur der Lauf.
 *
 * Mitgemessen werden die Lagen, in denen ein Browser KEINEN MIME-Typ liefert
 * (Drag aus manchen Quellen) - dort entscheidet allein die Endung.
 *
 *   node tests/lies_chat_vorschau.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

const CHATJS = fs.readFileSync(path.join(ROOT, 'frontend/js/chat.js'), 'utf8');

/* ⚠ TRANSITIV SCHNEIDEN, STATT EINE LISTE ZU PFLEGEN.
 *
 * Hier standen zwei Funktionen und zwei von Hand abgemessene Scheiben
 * Modul-Konstanten (`_EXEC_EXT`, `_BILD_MAGIE`). Zweimal hat das Geld
 * gekostet: als `addFiles()` den Helfer `_bildMimeAusBytes()` dazubekam,
 * starb dieses Skript mitten in seiner Tabelle an einem nackten
 * `ReferenceError` (2026-10-11) - die Fehlerklasse aus dem Register ("eine
 * neue Modulvariable in einer geschnittenen Funktion bricht jeden fremden
 * Harness, der sie auch schneidet"). Nachgetragen wurde damals der EINE
 * fehlende Helfer; die Liste blieb eine Liste, und sie ist an dem Tag wieder
 * unvollstaendig, an dem jemand den naechsten ergaenzt - die fehlende Zeile
 * meldet sich nicht.
 *
 * Deshalb wird die Abhaengigkeit GEMESSEN statt aufgezaehlt: von den Wurzeln
 * aus wird eingesammelt, bis sich nichts mehr aendert. Am SYNTAXBAUM, nicht
 * am Text - ein Name in einem Kommentar oder einer Zeichenkette ist keine
 * Abhaengigkeit, und `att.name` ist kein Bezug auf eine Modulvariable `name`
 * (wer das mitzaehlt, schneidet fremde Deklarationen mit).
 *
 * Nachgemessen am 2026-10-12: der Schnitt greift `_BILD_MAGIE` und
 * `_bildMimeAusBytes` von selbst - genau die zwei, die vorher von Hand
 * nachgetragen werden mussten. */
const WURZELN = ['addFiles', 'renderPreviews'];
/* Was der Messaufbau SELBST stellt und deshalb nicht geschnitten wird: die
 * DOM-Knoten (die Probeseite vergibt eigene IDs), der Anhang-Puffer, und
 * `showToast` als Sonde - die Meldungen sollen gesammelt werden, nicht nach
 * vier Sekunden aus einem Element verschwinden. */
const SELBST = ['attachBar', 'msgInput', 'sendBtn', 'btnAttach',
                '_pendingAttachments', 'showToast'];

/** Nur ECHTE Namensbezuege: Eigenschaftsnamen und Objektschluessel sind keine. */
function bezuege(knoten, nimm) {
    if (!knoten || typeof knoten !== 'object') return;
    if (Array.isArray(knoten)) { knoten.forEach(k => bezuege(k, nimm)); return; }
    if (knoten.type === 'Identifier') { nimm(knoten.name); return; }
    if (knoten.type === 'MemberExpression') {
        bezuege(knoten.object, nimm);
        if (knoten.computed) bezuege(knoten.property, nimm);
        return;
    }
    if (knoten.type === 'Property') {
        if (knoten.computed) bezuege(knoten.key, nimm);
        bezuege(knoten.value, nimm);
        return;
    }
    for (const feld in knoten) {
        if (feld === 'type' || feld === 'loc' || feld === 'start' || feld === 'end') continue;
        bezuege(knoten[feld], nimm);
    }
}

let BAUM;
/* Ein unparsebares chat.js ist ein Defekt am Produkt - hier aber "konnte
 * nicht messen", also Exit 2 mit einer lesbaren Zeile. Ein nackter
 * acorn-Stacktrace endet mit Exit 1, und Exit 1 ist in diesem Projekt die
 * Sprache fuer "ich beisse" (Register: ein falscher Abbruchgrund ist teurer
 * als ein Absturz). */
try { BAUM = acorn.parse(CHATJS, { ecmaVersion: 2023 }); }
catch (e) {
    console.log('ABBRUCH: frontend/js/chat.js ist nicht parsebar - ' + e.message);
    console.log('Exit 2 = konnte nicht messen (weder Messwert noch Befund).');
    process.exit(2);
}

/* chat.js ist EINE IIFE - ihr Rumpf IST die Modulebene. Ueber die STRUKTUR
 * gefunden, nicht ueber die Einrueckung: ein Umformatieren soll den Schnitt
 * nicht still leeren. */
let EBENE = null;
for (const st of BAUM.body) {
    if (st.type !== 'ExpressionStatement') continue;
    let e = st.expression;
    if (e.type === 'UnaryExpression') e = e.argument;
    if (e.type !== 'CallExpression') continue;
    const f = e.callee;
    if ((f.type === 'ArrowFunctionExpression' || f.type === 'FunctionExpression')
        && f.body && f.body.type === 'BlockStatement') { EBENE = f.body.body; break; }
}
if (!EBENE) {
    console.log('ABBRUCH: in chat.js keine umschliessende IIFE gefunden - der Schnitt'
              + ' waere leer und die Messung ohne Aussage'); process.exit(2);
}

// Name -> die Anweisung, die ihn auf der Modulebene deklariert.
const DEKL = new Map();
for (const st of EBENE) {
    if (st.type === 'FunctionDeclaration' && st.id) DEKL.set(st.id.name, st);
    else if (st.type === 'VariableDeclaration') {
        for (const d of st.declarations) {
            if (d.id && d.id.type === 'Identifier') DEKL.set(d.id.name, st);
        }
    }
}

const gebraucht = new Set();
const rand = WURZELN.slice();
while (rand.length) {
    const n = rand.pop();
    if (gebraucht.has(n) || SELBST.includes(n) || !DEKL.has(n)) continue;
    gebraucht.add(n);
    bezuege(DEKL.get(n), (name) => { if (DEKL.has(name) && !gebraucht.has(name)) rand.push(name); });
}
const KNOTEN = new Set([...gebraucht].map(n => DEKL.get(n)));
/* In QUELLTEXT-REIHENFOLGE zusammensetzen: eine Konstante, die hinter ihrem
 * Benutzer landet, waere ein TDZ-Fehler statt eines Messwerts. */
const SCHNITT = EBENE.filter(st => KNOTEN.has(st))
                     .map(st => CHATJS.slice(st.start, st.end)).join('\n\n');
/* Der Rumpf von `addFiles` einzeln - der Zweig-Bericht unten verankert an
 * seiner WIRKUNG, und ein Muster ueber das ganze chat.js traefe auch die
 * Symbol- und Render-Stellen. */
const ADD = DEKL.has('addFiles')
    ? CHATJS.slice(DEKL.get('addFiles').start, DEKL.get('addFiles').end) : '';

/* Positivkontrollen des Schnitts - "konnte nicht laufen" muss von einem
 * Messwert unterscheidbar bleiben, deshalb Exit 2 und kein stilles Weiter. */
const fehlendeWurzel = WURZELN.filter(n => !gebraucht.has(n));
if (fehlendeWurzel.length) {
    console.log('ABBRUCH: auf der Modulebene von chat.js nicht gefunden: '
              + fehlendeWurzel.join(', ')); process.exit(2);
}
/* Eine Attrappe, die nichts mehr verdeckt, ist kein Ersatz - sie laesst den
 * echten Namen ungeschnitten und die Messung still ins Leere laufen. */
const toteAttrappe = SELBST.filter(n => !DEKL.has(n));
if (toteAttrappe.length) {
    console.log('ABBRUCH: der Messaufbau stellt Namen, die chat.js nicht mehr auf der'
              + ' Modulebene fuehrt (umbenannt?): ' + toteAttrappe.join(', ')); process.exit(2);
}
/* Und der Schnitt muss die Helfer WIRKLICH tragen, die die Messung braucht -
 * sonst ist "GIF gegen JPG" eine Aussage ueber einen halben Schnitt. */
for (const pflicht of ['_bildMimeAusBytes', '_BILD_MAGIE', '_EXEC_EXT']) {
    if (!gebraucht.has(pflicht)) {
        console.log('ABBRUCH: ' + pflicht + ' ist nicht im transitiven Schnitt - entweder'
                  + ' heisst es anders, oder addFiles ruft es nicht mehr.'); process.exit(2);
    }
}

const dom = new JSDOM(`<!doctype html><body>
  <div id="attach-bar"></div><textarea id="msg-input"></textarea>
  <button id="send-btn"></button><button id="btn-attach"></button>
</body>`, { url: 'https://h/chat', runScripts: 'outside-only' });
const w = dom.window;
w.t = (k) => k;
const toasts = [];

const rumpf = `
    const attachBar = document.getElementById('attach-bar');
    const msgInput  = document.getElementById('msg-input');
    const sendBtn   = document.getElementById('send-btn');
    const btnAttach = document.getElementById('btn-attach');
    let _pendingAttachments = [];
    function showToast(m) { window.__toast(m); }
    ${SCHNITT}
    window.__mimeAusBytes = _bildMimeAusBytes;
    window.__lauf = async function (datei) {
        _pendingAttachments = [];
        await addFiles([datei]);
        const chip = attachBar.querySelector('.attach-chip');
        const img  = chip ? chip.querySelector('img') : null;
        return {
            angenommen: _pendingAttachments.length,
            typ:  _pendingAttachments[0] ? _pendingAttachments[0].type : null,
            mime: _pendingAttachments[0] ? _pendingAttachments[0].mime_type : null,
            hatImg: !!img,
            src: img ? String(img.src).slice(0, 34) : (chip ? '(Symbol statt Bild)' : '(kein Chip)')
        };
    };`;
w.__toast = (m) => toasts.push(m);
w.eval(rumpf);

// Echte Bytes - kein Platzhalter: Material, das ein Konsument nicht oeffnet,
// belegt nichts (Register).
const JPG = Buffer.from('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL' +
    'DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QA' +
    'FAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==', 'base64');
const GIF = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64');

/* ⚠ POSITIVKONTROLLE DES MESSAUFBAUS – hier keine Zierde. Liefert
 * `_bildMimeAusBytes` immer '' (kaputter Schnitt, fehlende Signaturtabelle,
 * ein atob, das wirft), dann entscheidet wieder allein der GEMELDETE Typ. Die
 * Tabelle unten sieht in diesem Fall genauso plausibel aus und beantwortet
 * eine ANDERE Frage als die gestellte – „stechen die Bytes?" waere dann still
 * mit nein beantwortet, ohne dass es im Code so steht. Gemessen an Material,
 * dessen Typ bekannt ist. */
const blind = [[JPG, 'image/jpeg'], [GIF, 'image/gif']]
    .filter(([b, erwartet]) => w.__mimeAusBytes(b.toString('base64')) !== erwartet);
if (blind.length) {
    console.log('ABBRUCH: die Byte-Erkennung erkennt ihr eigenes Material nicht '
                + '(' + blind.length + ' von 2) - die Messung waere ohne Aussage.');
    process.exit(2);
}

function datei(name, mime, bytes) {
    return new w.File([new Uint8Array(bytes)], name, mime ? { type: mime } : {});
}

(async () => {
    /* Der Schnitt gehoert in die AUSGABE: wer die Zahlen deutet, muss sehen,
     * welcher Code gelaufen ist - und ein stillschweigend geschrumpfter
     * Schnitt faellt sonst niemandem auf. Genau das war der Vorlauf dieses
     * Umbaus: der fehlende Helfer stand in keiner Zeile der Ausgabe. */
    console.log('Geschnitten (transitiv ab ' + WURZELN.join(' + ') + '): '
                + EBENE.filter(st => KNOTEN.has(st))
                       .map(st => [...gebraucht].filter(n => DEKL.get(n) === st).join('/'))
                       .join(', '));
    console.log('Vom Messaufbau gestellt: ' + SELBST.join(', ') + '\n');
    const faelle = [
        ['GIF  mit MIME   ', datei('bild.gif',  'image/gif',  GIF)],
        ['JPG  mit MIME   ', datei('bild.jpg',  'image/jpeg', JPG)],
        ['JPEG mit MIME   ', datei('bild.jpeg', 'image/jpeg', JPG)],
        ['GIF  OHNE MIME  ', datei('bild.gif',  '',           GIF)],
        ['JPG  OHNE MIME  ', datei('bild.jpg',  '',           JPG)],
        ['JPG  Endung GROSS', datei('BILD.JPG', '',           JPG)],
    ];
    console.log('Fall                 | angen. | type  | mime       | <img> | src');
    console.log('-'.repeat(88));
    for (const [titel, f] of faelle) {
        const r = await w.__lauf(f);
        console.log(titel.padEnd(20) + ' |   ' + r.angenommen + '    | ' +
            String(r.typ).padEnd(5) + ' | ' + String(r.mime || '(leer)').padEnd(10) + ' |  ' +
            (r.hatImg ? 'ja ' : 'NEIN') + '  | ' + r.src);
    }
    if (toasts.length) console.log('\nMeldungen: ' + JSON.stringify(toasts));

    /* ⚠ AN DER WIRKUNG VERANKERT, NICHT AM VARIABLENNAMEN. Hier stand
     * `/if \(mime\.startsWith\('image\/'\).*$/` – die Schreibweise von damals.
     * Inzwischen heisst die Variable `mimeEff` (die Bytes stechen den
     * gemeldeten Typ), und die Zeile gab seitdem woertlich „(nicht gefunden)"
     * aus, obwohl die Erkennung danebensteht: eine FALSCHAUSSAGE ueber den
     * Code, in genau der Zeile, die den Code zeigen soll. Gesucht wird deshalb
     * der Zweig an seiner WIRKUNG (`type = 'image'`) und nur im geschnittenen
     * `addFiles` – im ganzen chat.js traefe es auch die Symbol- und
     * Render-Stellen. */
    console.log('\nBild-Erkennung im Quelltext (aus dem geschnittenen addFiles):');
    const zweige = ADD.split('\n').filter(z => /type\s*=\s*'image'/.test(z));
    if (!zweige.length) {
        console.log('  (keine Zuweisung type = \'image\' im Schnitt - der Schnitt ist verdaechtig)');
    } else {
        zweige.forEach(z => console.log('  ' + z.trim()));
    }
})();
