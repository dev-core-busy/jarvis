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
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
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

const { JSDOM } = require('./lib/jsdom_laden')();

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
            + '\n' + (_iMag > 0 ? CHATJS.slice(_iMag, CHATJS.indexOf('];', _iMag) + 2) : '')
            // Office-Erkennung (2026-09-28): zwei Einzeiler-Konstanten.
            + '\n' + (CHATJS.match(/const _OFFICE_HTML = [^\n]*/) || [''])[0]
            + '\n' + (CHATJS.match(/const _TABELLE_INLINE_MAX = [^\n]*/) || [''])[0]
            /* ⚠ DER ZUSTAND VON LIGHTBOX UND KONTEXTMENUE (2026-10-11, gefunden
             * von tests/test_prolog_vollstaendig.js). Oben werden
             * `openLightbox`, `_lbUpdate` und `showCtxMenu` geschnitten; die
             * lesen `_lbAtts`, `_lbIdx` und `_ctxAtt` – drei Modulvariablen,
             * die dieser Prolog nicht stellte. Gemessen: 42 Referenzen auf
             * Namen, die es im Fenster nicht gibt, bei 43 OK / 0 FAIL. Gruen
             * war der Lauf nur, weil kein Testfall die Lightbox oeffnet – der
             * erste, der es tut, bekommt einen ReferenceError statt eines
             * Befunds. GESCHNITTEN, nicht abgetippt: eine andere Vorbelegung im
             * Produktivcode wandert so mit. */
            + '\n' + (CHATJS.match(/let _lbAtts = [^\n]*/) || [''])[0]
            + '\n' + (CHATJS.match(/let _ctxAtt = [^\n]*/) || [''])[0];
// Der Bindeblock des Eingabefeldes (paste + drop) – ueber den Anker in seinem
// Rumpf gefunden, damit eine Umbenennung nicht still am Schnitt vorbeilaeuft.
const ANKER = CHATJS.indexOf("const dt = e.clipboardData");
const BIND  = ANKER > 0 ? klammern(CHATJS, CHATJS.lastIndexOf('if (msgInput) {', ANKER)) : '';

const TEILE = ['_bildMimeAusBytes', 'renderPreviews', 'addFiles', '_renderAttachments',
               '_renderFileChip', '_dataUrl', 'escapeHtml', 'openLightbox', '_lbUpdate',
               'showCtxMenu', 'addLongPress', '_mdZelle', '_rasterAusHtml', '_rasterAusTsv',
               '_rasterZuMarkdown', '_officeEinfuegen'].map(schneide);
// Positivkontrolle des Schnitts: ein leerer Schnitt macht jede Aussage wertlos.
if (TEILE.some(t => !t) || !BIND || !/_BILD_MAGIE\s*=\s*\[/.test(KONST)
    || !/_OFFICE_HTML = \//.test(KONST) || !/_TABELLE_INLINE_MAX = \d/.test(KONST)
    || !/_lbAtts\s*=/.test(KONST) || !/_lbIdx\s*=/.test(KONST)
    || !/_ctxAtt\s*=/.test(KONST)) {
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
function einfuegen(w, eintraege, fassungen) {
    const ev = new w.Event('paste', { bubbles: true, cancelable: true });
    // getData() wie im Browser: eine fehlende Fassung liefert '' (kein Wurf).
    ev.clipboardData = { items: eintraege, getData: (t) => (fassungen || {})[t] || '' };
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

abschnitt('6. Aus Excel/Word kopiert: der INHALT, nicht das Bild (2026-09-28)');
{
    // Die Fassungen so, wie Excel sie liefert: HTML mit ProgId-Kennung,
    // Tabulator-Text UND ein PNG der Auswahl.
    const EXCEL_HTML = '<html xmlns:o="urn:schemas-microsoft-com:office:office"><head>'
        + '<meta name=ProgId content=Excel.Sheet></head><body><!--StartFragment-->'
        + '<table><tr><td>Name</td><td>Betrag</td><td></td></tr>'
        + '<tr><td>M&uuml;ller | GmbH</td><td>1.234,50</td><td></td></tr>'
        + '<tr><td colspan=2>Summe</td><td>9</td></tr>'
        + '<tr><td></td><td></td><td></td></tr></table><!--EndFragment--></body></html>';
    const EXCEL_TSV = 'Name\tBetrag\t\r\nMüller | GmbH\t1.234,50\t\r\nSumme\t\t9\r\n';
    const png = w => ({ kind: 'file', getAsFile: () => datei(w, '', 'image/png', PNG) });

    const { w } = fenster();
    const el = w.document.getElementById('msg-input');
    el.value = 'Bitte summieren:'; el.selectionStart = el.selectionEnd = el.value.length;
    let eingabe = 0; el.addEventListener('input', () => eingabe++);
    const ev = einfuegen(w, [png(w)], { 'text/html': EXCEL_HTML, 'text/plain': EXCEL_TSV });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w.__anh().length === 0, 'Excel-Auswahl: KEIN Bild-Anhang', 'Anhaenge: ' + w.__anh().length);
    pruefe(ev.defaultPrevented, 'der Vorgang wird abgefangen (sonst kaeme der Tabulator-Text doppelt)');
    const soll = 'Bitte summieren:\n| Name | Betrag |  |\n| --- | --- | --- |\n'
               + '| Müller \\| GmbH | 1.234,50 |  |\n| Summe |  | 9 |\n';
    pruefe(el.value === soll, 'die Tabelle steht als Markdown im Eingabefeld, auf eigener Zeile',
        JSON.stringify(el.value));
    pruefe(eingabe === 1, 'das input-Ereignis feuert (Senden-Knopf, Hoehe)', 'ist: ' + eingabe);
    pruefe(el.selectionStart === el.value.length, 'die Einfuegemarke steht hinter der Tabelle');

    // Rueckfall: Office-HTML ohne <table> -> die Tabulator-Fassung.
    const { w: w2 } = fenster();
    einfuegen(w2, [png(w2)], { 'text/html': '<meta name=ProgId content=Excel.Sheet><p>x</p>',
                               'text/plain': 'a\t"b\nc"\td\r\n1\t2\t3\r\n' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w2.document.getElementById('msg-input').value === '| a | b c | d |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n',
        'ohne HTML-Tabelle: Tabulator-Text (mit Umbruch in "…") wird zur Markdown-Tabelle',
        JSON.stringify(w2.document.getElementById('msg-input').value));

    // Eine einzelne Zelle ist keine Tabelle.
    const { w: w3 } = fenster();
    einfuegen(w3, [png(w3)], { 'text/html': '<meta name=ProgId content=Excel.Sheet><table><tr><td>42</td></tr></table>',
                               'text/plain': '42\r\n' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w3.document.getElementById('msg-input').value === '42\n' && w3.__anh().length === 0,
        'eine einzelne Excel-Zelle kommt als ihr Wert, nicht als Tabelle',
        JSON.stringify(w3.document.getElementById('msg-input').value));

    // Grosse Tabelle -> Textanhang ueber addFiles(), NICHT das Bild.
    const { w: w4 } = fenster();
    let gross = '<meta name=ProgId content=Excel.Sheet><table>';
    for (let i = 0; i < 400; i++) gross += `<tr><td>Zeile ${i}</td><td>Wert ${i * 7}</td></tr>`;
    einfuegen(w4, [png(w4)], { 'text/html': gross + '</table>', 'text/plain': 'x' });
    await new Promise(r => setTimeout(r, 60));
    const g = (w4.__anh() || [])[0] || {};
    pruefe(w4.__anh().length === 1 && /\.md$/.test(g.name || '') && g.type === 'document',
        'eine grosse Tabelle wird als .md-Textanhang angehaengt, nicht als Bild',
        `name=${g.name} type=${g.type}`);
    pruefe(w4.document.getElementById('msg-input').value === '', 'das Eingabefeld bleibt dabei leer');
    let gtext = '';
    try { gtext = Buffer.from(g.data || '', 'base64').toString('utf8'); } catch (e) { /* bleibt leer */ }
    pruefe(gtext.startsWith('| Zeile 0 | Wert 0 |') && gtext.includes('| Zeile 399 | Wert 2793 |'),
        'der Anhang enthaelt die ganze Tabelle');

    // Word-Text: Bild daneben, aber kein <img> im HTML -> Browser fuegt Text ein.
    const { w: w5 } = fenster();
    const ev5 = einfuegen(w5, [png(w5)], { 'text/html': '<html xmlns:w="urn:schemas-microsoft-com:office:word"><meta name=ProgId content=Word.Document><p>Hallo</p>',
                                           'text/plain': 'Hallo' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(!ev5.defaultPrevented && w5.__anh().length === 0,
        'Word-Text: nicht abgefangen, kein Bild – der Browser fuegt den Text ein');

    // Kopierte Grafik aus Word, MIT Beschriftung: text/plain ist dann nicht
    // leer – entscheiden muss das <img> im HTML, das Bild IST gemeint.
    const { w: w6 } = fenster();
    einfuegen(w6, [png(w6)], { 'text/html': '<meta name=ProgId content=Word.Document><p><img src="file:///x.png"></p><p>Abbildung 1: Umsatz</p>',
                               'text/plain': 'Abbildung 1: Umsatz' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w6.__anh().length === 1 && w6.__anh()[0].type === 'image',
        'kopierte Grafik aus Word (mit Beschriftung) bleibt ein Bild');

    // GEGENPROBE: Bild aus einer Webseite (HTML daneben, aber keine Office-Kennung).
    const { w: w7 } = fenster();
    einfuegen(w7, [png(w7)], { 'text/html': '<table><tr><td><img src="https://x/y.png"></td><td>a</td></tr></table>',
                               'text/plain': 'a\tb' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w7.__anh().length === 1 && w7.__anh()[0].type === 'image'
           && w7.document.getElementById('msg-input').value === '',
        'Bild aus einer Webseite (auch in einer Tabelle): bleibt der Bild-Anhang');

    // LibreOffice Calc
    const { w: w8 } = fenster();
    einfuegen(w8, [png(w8)], { 'text/html': '<meta name="generator" content="LibreOffice 24.2"><table><tr><td>a</td><td>b</td></tr></table>',
                               'text/plain': 'a\tb' });
    await new Promise(r => setTimeout(r, 30));
    pruefe(w8.document.getElementById('msg-input').value === '| a | b |\n| --- | --- |\n' && w8.__anh().length === 0,
        'LibreOffice Calc wird wie Excel behandelt');
}

console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
_bilanz = true;
process.exit(fail ? 1 : 0);
})();
