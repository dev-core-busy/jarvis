#!/usr/bin/env node
/**
 * /chat: Bild-Anhaenge – Erkennung aus den BYTES + Einfuegen aus der
 * Zwischenablage.
 *
 * ZWEI MELDUNGEN VOM 2026-09-16, und sie haben DIESELBE Wurzel:
 *   a) "ein GIF wird als Bild angezeigt, ein JPG als Text" (per Drag & Drop)
 *   b) "ein im Bildbetrachter kopiertes Bild laesst sich nicht einfuegen"
 *
 * Zu (a): der Code unterscheidet GIF und JPG an KEINER Stelle – gemessen. Was
 * ihn trennt, ist `file.type`: den holt der Browser unter Windows aus der
 * Registry, und hat ein Bildbetrachter die .jpg-Zuordnung uebernommen, steht
 * dort "" oder application/octet-stream. Danach faellt JEDE mime-basierte
 * Stelle durch – die gesendete Nachricht zeichnet einen Datei-Chip ("als
 * Text"), und der Server behandelt den Anhang als Dokument, sodass das MODELL
 * das Bild gar nicht sieht.
 *
 * WAS HIER GEMESSEN WIRD – und warum genau das:
 *
 *  1) `addFiles()` und `_renderAttachments()` werden WIRKLICH AUSGEFUEHRT, mit
 *     echten Bytes. Eine Quelltext-Pruefung koennte die Frage "steht am Ende
 *     ein Bild oder ein Datei-Chip in der Blase?" gar nicht beantworten.
 *
 *  2) DIE GEGENRICHTUNG ist genauso wichtig: ein PDF, ein Video und eine
 *     Tabelle muessen ihren gemeldeten Typ BEHALTEN. Eine Byte-Erkennung, die
 *     zu viel an sich zieht, waere schlimmer als der behobene Fehler.
 *
 *  3) Der `paste`-Zuhoerer wird ueber ein ECHTES Ereignis ausgeloest. Und die
 *     Gegenprobe dazu: reiner TEXT darf NICHT abgefangen werden – sonst waere
 *     das gewoehnliche Einfuegen im Eingabefeld kaputt.
 *
 *   node tests/test_chat_bild_einfuegen.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const P = (...p) => path.join(ROOT, ...p);

let ok = 0, fail = 0;
const pruefe = (b, t, d) => { if (b) { ok++; console.log('  ✓ ' + t); }
                              else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); } };
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
// Nie ungeprueft dereferenzieren: eine werfende Pruefung bricht den Lauf ab
// und sieht dann wie ein bestandener aus (Register).
const sicher = (fn, t) => { try { return fn(); } catch (e) { fail++; console.log('  ✗ ' + t + ' – WURF: ' + e.message); return undefined; } };
process.on('unhandledRejection', e => { fail++; console.log('  ✗ unbehandelte Zurueckweisung: ' + (e && e.message)); });

// Wachhunde: die Datei ist eine async-IIFE. Haengt ein Promise, wird die
// Bilanz nie erreicht – Node beendet mit 0, und ein ABGEBROCHENER Lauf sieht
// aus wie ein bestandener (Register).
let _bilanz = false;
process.on('exit', (c) => { if (!_bilanz && c === 0) {
    console.log('  ✗ ABBRUCH: keine Bilanzzeile – der Lauf ist vorzeitig beendet');
    process.exitCode = 1; } });
setTimeout(() => { console.log('  ✗ ABBRUCH: der Lauf haengt (kein Ergebnis nach 30 s)'); process.exit(1); }, 30000);

let JSDOM = null;
for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom',
                 P('node_modules/jsdom'), '/usr/share/nodejs/jsdom']) {
    if (!k) continue;
    try { JSDOM = require(k).JSDOM; break; } catch (e) { /* naechster */ }
}
// "Konnte nicht laufen" darf nie wie "bestanden" aussehen -> Exit 2.
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht gefunden'); process.exit(2); }

const CHATJS = fs.readFileSync(P('frontend/js/chat.js'), 'utf8');

/* Funktionsrumpf GEKLAMMERT GEZAEHLT schneiden, nicht bis zum ersten "\n}":
 * eine Einzeiler-Funktion endet in DERSELBEN Zeile, ein naiver Schnitt nimmt
 * dann die naechste Funktion mit und prueft fremden Code (Register). */
function klammern(src, von) {
    let i = src.indexOf('{', von), t = 0;
    for (let j = i; j < src.length; j++) {
        if (src[j] === '{') t++;
        else if (src[j] === '}') { t--; if (t === 0) return src.slice(von, j + 1); }
    }
    return '';
}
function schneide(name) {
    const m = CHATJS.match(new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\('));
    return m ? klammern(CHATJS, m.index) : '';
}
// Modul-Konstanten fallen aus jedem Funktions-Schnitt heraus (Register).
// _BILD_MAGIE ist ein ARRAY – `klammern()` sucht "{" und wuerde hier weit
// hinter das Ende greifen. Deshalb bis zum schliessenden "];" schneiden.
const _iMag = CHATJS.indexOf('const _BILD_MAGIE');
const KONST = CHATJS.slice(CHATJS.indexOf('const _EXEC_EXT'),
                           CHATJS.indexOf('const _MAX_FILE_BYTES') + 60)
            + '\n' + (_iMag > 0 ? CHATJS.slice(_iMag, CHATJS.indexOf('];', _iMag) + 2) : '');
// Der Bindeblock des Eingabefeldes (paste + drop) – ueber den Anker in seinem
// Rumpf gefunden, damit eine Umbenennung nicht still am Schnitt vorbeilaeuft.
const ANKER = CHATJS.indexOf("const dt = e.clipboardData");
const BIND  = ANKER > 0 ? klammern(CHATJS, CHATJS.lastIndexOf('if (msgInput) {', ANKER)) : '';

const TEILE = ['_bildMimeAusBytes', 'renderPreviews', 'addFiles', '_renderAttachments',
               '_renderFileChip', '_dataUrl', 'escapeHtml', 'openLightbox', '_lbUpdate',
               'showCtxMenu', 'addLongPress'].map(schneide);
// Positivkontrolle des Schnitts: ein leerer Schnitt macht jede Aussage wertlos.
if (TEILE.some(t => !t) || !BIND || !/_BILD_MAGIE\s*=\s*\[/.test(KONST)) {
    console.log('ABBRUCH: Schnitt leer – die Messung haette keine Aussage'); process.exit(2);
}

// Echte Bytes – Material, das ein Konsument nicht oeffnet, belegt nichts.
const B = s => Buffer.from(s, 'base64');
const JPG = B('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==');
const GIF = B('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7');
const PNG = B('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer<<>>', 'latin1');
const TXT = Buffer.from('Hallo Welt, das ist reiner Text.', 'latin1');

function fenster() {
    const dom = new JSDOM(`<!doctype html><body>
        <div id="attach-bar"></div><textarea id="msg-input"></textarea>
        <button id="send-btn"></button><button id="btn-attach"></button>
        <div id="attach-toast"></div></body>`,
        { url: 'https://h/chat', runScripts: 'outside-only' });
    const w = dom.window;
    w.t = (k) => k;
    const toasts = [];
    w.__toast = m => toasts.push(m);
    w.eval(`
        const attachBar   = document.getElementById('attach-bar');
        const msgInput    = document.getElementById('msg-input');
        const sendBtn     = document.getElementById('send-btn');
        const btnAttach   = document.getElementById('btn-attach');
        const attachToast = document.getElementById('attach-toast');
        let _pendingAttachments = [];
        function showToast(m) { window.__toast(m); }
        ${KONST}
        ${TEILE.join('\n')}
        ${BIND}
        window.__anh   = () => _pendingAttachments;
        window.__leere = () => { _pendingAttachments = []; renderPreviews(); };
        window.__addFiles = addFiles;
        window.__blase = function (att) {
            const b = document.createElement('div'); b.innerHTML = 'Text';
            _renderAttachments(b, { attachments: [att] });
            return b.querySelector('.uc-img-gallery') ? 'bild'
                 : (b.querySelector('.uc-file-chip') ? 'datei-chip' : 'nichts');
        };`);
    return { w, toasts };
}
const datei = (w, name, mime, bytes) =>
    new w.File([new Uint8Array(bytes)], name, mime ? { type: mime } : {});

/* Ein `paste`-Ereignis wie im Browser: jsdom kennt keine ClipboardEvent-Daten,
 * deshalb wird `clipboardData` am Ereignis gestellt. Der ZUHOERER ist der
 * echte – gemessen wird, was er daraus macht. */
function einfuegen(w, eintraege) {
    const ev = new w.Event('paste', { bubbles: true, cancelable: true });
    ev.clipboardData = { items: eintraege };
    w.document.getElementById('msg-input').dispatchEvent(ev);
    return ev;
}

(async () => {
// ═══════════════════════════════════════════════════════════════════════════
abschnitt('1. Der gemeldete Fall: JPG ohne brauchbaren MIME-Typ');
{
    const { w } = fenster();
    for (const [titel, gemeldet] of [['(leer)', ''], ['application/octet-stream', 'application/octet-stream'],
                                     ['text/plain', 'text/plain']]) {
        await w.__leere();
        await w.__addFiles([datei(w, 'foto.jpg', gemeldet, JPG)]);
        const a = (w.__anh() || [])[0] || {};
        pruefe(a.mime_type === 'image/jpeg',
            `JPG, gemeldet als ${titel}: wird als image/jpeg gefuehrt`, 'ist: ' + a.mime_type);
        pruefe(sicher(() => w.__blase(a), 'Blase') === 'bild',
            `JPG, gemeldet als ${titel}: erscheint in der Nachricht als BILD (nicht als Text)`);
    }
    // Der Vorzustand zum Vergleich – GIF war nie betroffen.
    await w.__leere();
    await w.__addFiles([datei(w, 'bild.gif', 'image/gif', GIF)]);
    pruefe(w.__blase(w.__anh()[0]) === 'bild', 'GIF verhaelt sich unveraendert (Gegenprobe zum Vorzustand)');
}

abschnitt('2. Die Bytes gewinnen – aber nur, wenn sie ein Bild BEWEISEN');
{
    const { w } = fenster();
    const fall = async (name, mime, bytes) => {
        await w.__leere(); await w.__addFiles([datei(w, name, mime, bytes)]);
        return (w.__anh() || [])[0] || {};
    };
    pruefe((await fall('x.png', '', PNG)).mime_type === 'image/png', 'PNG ohne MIME wird erkannt');
    pruefe((await fall('x.gif', '', GIF)).mime_type === 'image/gif', 'GIF ohne MIME wird erkannt');
    // GEGENRICHTUNG: eine zu gierige Erkennung waere schlimmer als der Fehler.
    const p = await fall('bericht.pdf', 'application/pdf', PDF);
    pruefe(p.mime_type === 'application/pdf' && p.type === 'pdf', 'ein PDF behaelt seinen Typ');
    const t = await fall('notiz.txt', 'text/plain', TXT);
    pruefe(t.mime_type === 'text/plain', 'eine Textdatei behaelt ihren Typ');
    pruefe(w.__blase(t) === 'datei-chip', 'eine Textdatei bleibt ein Datei-Chip');
    const v = await fall('clip.mp4', 'video/mp4', TXT);
    pruefe(v.mime_type === 'video/mp4' && v.type === 'video', 'ein Video behaelt seinen Typ');
    // TIFF steht bewusst NICHT in der Tabelle: der Browser kann es nicht
    // zeichnen – aus einem Datei-Chip wuerde ein kaputtes Bild.
    const tif = await fall('scan.tif', '', Buffer.from([0x49, 0x49, 0x2A, 0x00, 1, 2, 3, 4]));
    pruefe(tif.mime_type !== 'image/tiff', 'TIFF wird NICHT zu einem Bild-MIME erhoben');
}

abschnitt('3. Einfuegen aus der Zwischenablage (b)');
{
    const { w } = fenster();
    const ev = einfuegen(w, [{ kind: 'file', getAsFile: () => datei(w, '', 'image/png', PNG) }]);
    await new Promise(r => setTimeout(r, 30));
    const a = (w.__anh() || [])[0] || {};
    pruefe(w.__anh().length === 1, 'ein eingefuegtes Bild wird zum Anhang');
    pruefe(a.mime_type === 'image/png' && a.type === 'image', 'es wird als Bild gefuehrt');
    pruefe(/^clipboard-\d{8}-\d{6}\.png$/.test(a.name || ''),
        'ein namenloses Bild bekommt einen Namen', 'ist: ' + a.name);
    pruefe(ev.defaultPrevented, 'der Vorgang wird abgefangen (der Browser fuegt nichts daneben ein)');
    pruefe(sicher(() => w.__blase(a), 'Blase') === 'bild',
        'das eingefuegte Bild erscheint als BILD – nicht als Link und nicht als Name');
    const chip = w.document.querySelector('#attach-bar .attach-chip img');
    pruefe(!!chip && String(chip.src).startsWith('data:image/png;base64,'),
        'die Vorschau ueber dem Eingabefeld zeigt das Bild');
}
{
    // GEGENPROBE: reiner Text darf NICHT abgefangen werden, sonst ist das
    // gewoehnliche Einfuegen im Eingabefeld kaputt.
    const { w } = fenster();
    const ev = einfuegen(w, [{ kind: 'string', getAsFile: () => null }]);
    await new Promise(r => setTimeout(r, 30));
    pruefe(!ev.defaultPrevented, 'reiner Text wird NICHT abgefangen');
    pruefe(w.__anh().length === 0, 'reiner Text erzeugt keinen Anhang');
}
{
    // Aus einer Webseite kopiert: Datei UND Text liegen gleichzeitig vor.
    const { w } = fenster();
    einfuegen(w, [{ kind: 'string', getAsFile: () => null },
                  { kind: 'file', getAsFile: () => datei(w, 'foto.jpg', '', JPG) }]);
    await new Promise(r => setTimeout(r, 30));
    const a = (w.__anh() || [])[0] || {};
    pruefe(w.__anh().length === 1 && a.mime_type === 'image/jpeg',
        'aus einer Webseite kopiert: die Bilddatei wird genommen, der Text daneben ignoriert');
}

abschnitt('4. Ablegen direkt auf dem Eingabefeld');
{
    const { w } = fenster();
    const el = w.document.getElementById('msg-input');
    const ueber = new w.Event('dragover', { bubbles: true, cancelable: true });
    ueber.dataTransfer = { types: ['Files'], files: [] };
    el.dispatchEvent(ueber);
    pruefe(ueber.defaultPrevented,
        'dragover mit Datei wird abgefangen (sonst navigiert der Browser weg)');
    const weg = new w.Event('dragover', { bubbles: true, cancelable: true });
    weg.dataTransfer = { types: ['text/plain'], files: [] };
    el.dispatchEvent(weg);
    pruefe(!weg.defaultPrevented, 'ein gezogener TEXT wird nicht abgefangen');
    const drop = new w.Event('drop', { bubbles: true, cancelable: true });
    drop.dataTransfer = { files: [datei(w, 'foto.jpg', '', JPG)] };
    el.dispatchEvent(drop);
    await new Promise(r => setTimeout(r, 30));
    pruefe(w.__anh().length === 1 && w.__anh()[0].mime_type === 'image/jpeg',
        'eine auf dem Eingabefeld abgelegte Datei wird angehaengt');
}

abschnitt('5. Regel: es gibt nur EINEN Weg zum Anhang');
{
    // Ein eigener Pfad neben addFiles() waere eine zweite Fassung derselben
    // Regeln (Groessen-Deckel, Sperrliste, Byte-Erkennung) und liefe beim
    // naechsten Feinschliff auseinander.
    pruefe(/await addFiles\(dateien\)/.test(BIND), 'der Einfuege-Weg benutzt addFiles()');
    pruefe(!/_pendingAttachments\.push/.test(BIND), 'er baut den Anhang NICHT selbst');
    pruefe(BIND.indexOf('dateien.length === 0') < BIND.indexOf('preventDefault'),
        'preventDefault() steht HINTER der Pruefung auf Dateien');
}

console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
_bilanz = true;
process.exit(fail ? 1 : 0);
})();
