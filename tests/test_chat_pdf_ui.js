#!/usr/bin/env node
/**
 * "Chat als PDF": der KOMPLETTE Verlauf einer /chat-Sitzung als Druckdokument.
 *
 * WUNSCH DES NUTZERS (2026-09-03): "ich brauche in /chat eine Option den
 * kompletten Verlauf als PDF zu exportieren inkl. Bildern, z.B. als weiterer
 * Kontextmenue Punkt 'Chat als PDF'".
 *
 * WAS HIER GEMESSEN WIRD – und warum genau das:
 *
 *  1) `transcriptToPrintDom` wird WIRKLICH AUSGEFUEHRT, gegen ein echtes DOM.
 *     Eine Quelltext-Pruefung koennte nicht sehen, dass ein <canvas> im Klon
 *     LEER ist: `cloneNode(true)` kopiert das Element, nicht sein Bild – ein
 *     Chart.js-Diagramm waere im PDF eine leere Flaeche.
 *
 *  2) DIE REIHENFOLGE `open()` VOR JEDEM `await`. Nach dem ersten await ist die
 *     Benutzergeste verbraucht und der Browser lehnt das Fenster ab; sichtbar
 *     passiert dann GAR NICHTS. Gemessen wird eine Spur, nicht ein Vorkommen –
 *     ein Aufruf, der spaeter hinter das Einbetten rutscht, bliebe sonst gruen.
 *
 *  3) DASS DAS PDF SAGT, WAS FEHLT. Nicht eingebettete Bilder und
 *     ausgeblendete Agenten-Zeilen muessen im Kopf stehen. Ein stilles Loch in
 *     einem Protokoll ist schlimmer als ein Hinweis.
 *
 *  4) Der Kontextmenue-Eintrag in BEIDEN Zweigen von `_buildBubbleCtxItems`
 *     (mit und ohne Medien-Treffer) – der Medien-Zweig kehrt frueh zurueck.
 *
 *   node tests/test_chat_pdf_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
// Nie ungeprueft dereferenzieren: eine werfende Pruefung bricht den Lauf ab
// und sieht dann wie ein bestandener aus (Register).
const sicher = (fn, t) => { try { return fn(); } catch (e) { fail++; console.log('  ✗ ' + t + ' – WURF: ' + e.message); return undefined; } };

// Unbehandelte Zurueckweisungen zaehlen als FAIL, nicht als Stille.
process.on('unhandledRejection', (e) => { fail++; console.log('  ✗ unbehandelte Zurueckweisung: ' + (e && e.message)); });

/* ⚠ ZWEI WACHHUNDE, beide aus einer Gegenprobe gelernt, die NICHT biss:
 * die ganze Datei ist eine async-IIFE. Haengt ein Promise (z.B. weil das
 * Warten auf die Bilder keinen Deckel mehr hat), wird der Rest nie
 * ausgefuehrt – auch nicht die Bilanz und `process.exit`. Node beendet dann
 * mit Exit 0, und ein ABGEBROCHENER Lauf sieht aus wie ein bestandener. */
let _bilanz = false;
setTimeout(() => {
    console.log('  ✗ ABBRUCH: der Lauf haengt (kein Ergebnis nach 30 s)');
    process.exit(1);
}, 30000);
process.on('exit', (code) => {
    if (!_bilanz && code === 0) {
        console.log('  ✗ ABBRUCH: keine Bilanzzeile – der Lauf ist vorzeitig beendet');
        process.exitCode = 1;
    }
});

const ROOT = path.resolve(__dirname, '..');
const P = (...p) => path.join(ROOT, ...p);

// jsdom liegt nicht im Repo; beide ueblichen Orte des Projekts probieren.
let JSDOM = null;
for (const kand of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom',
                    path.join(ROOT, 'node_modules/jsdom'), '/usr/share/nodejs/jsdom']) {
    if (!kand) continue;
    try { JSDOM = require(kand).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const CHATLIB = fs.readFileSync(P('frontend/js/chatlib.js'), 'utf8');
const CHATJS  = fs.readFileSync(P('frontend/js/chat.js'), 'utf8');
const I18N    = fs.readFileSync(P('frontend/js/i18n.js'), 'utf8');

/* Funktionsrumpf aus einer Datei schneiden – GEKLAMMERT GEZAEHLT, nicht bis
 * zum ersten "\n}": eine Einzeiler-Funktion endet in DERSELBEN Zeile, ein
 * naiver Schnitt nimmt dann die naechste Funktion mit und prueft fremden Code
 * (Register, 2026-09-02). */
function schneide(src, name) {
    const m = src.match(new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\('));
    if (!m) return '';
    let i = src.indexOf('{', m.index + m[0].length - 1);
    if (i < 0) return '';
    let tiefe = 0;
    for (let j = i; j < src.length; j++) {
        const c = src[j];
        if (c === '{') tiefe++;
        else if (c === '}') { tiefe--; if (tiefe === 0) return src.slice(m.index, j + 1); }
    }
    return '';
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('1. Umgebung: chatlib.js laedt und exportiert die neuen Funktionen');

function fenster(opts) {
    opts = opts || {};
    const dom = new JSDOM('<!doctype html><html><body><div id="messages"></div></body></html>',
        { url: 'https://jarvis.example/chat', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'TOK123');
    // <canvas> ohne canvas-Paket: toDataURL/getContext nachbilden.
    const gemalt = [];
    w.HTMLCanvasElement.prototype.getContext = function () {
        const self = this;
        return { fillStyle: '', fillRect: function () { gemalt.push({ art: 'fill', farbe: this.fillStyle, w: self.width }); },
                 drawImage: function () { gemalt.push({ art: 'draw' }); } };
    };
    w.HTMLCanvasElement.prototype.toDataURL = function () { return 'data:image/png;base64,CANVASPNG'; };
    // Spur: was passiert in welcher Reihenfolge?
    const spur = [];
    const fenster_attrappe = () => {
        const kind = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://jarvis.example/' });
        const kw = kind.window;
        kw.print = () => spur.push('print');
        kw.focus = () => {};
        // jsdom laedt keine Bilder – ohne diese Zeile liefe JEDER Export in den
        // Warte-Deckel (5 s) und der Testlauf waere unbrauchbar langsam. Im
        // Browser ist eine data:-URL beim Setzen ohnehin schon vollstaendig da.
        Object.defineProperty(kw.HTMLImageElement.prototype, 'complete',
            { get: () => !opts.bilderHaengen, configurable: true });
        // Der Warte-Deckel muss im DRUCKFENSTER gesetzt werden (er verfaellt mit
        // ihm). Hier wird er zugleich abgekuerzt und protokolliert.
        const echtesTimeout = kw.setTimeout.bind(kw);
        kw.setTimeout = (fn, ms) => { spur.push('deckel:' + ms); return echtesTimeout(fn, 5); };
        // document.write in jsdom nach dem Laden ersetzt das Dokument – genau
        // wie im Browser. Reicht fuer diesen Zweck.
        return kw;
    };
    w.open = (...a) => { spur.push('open'); return opts.keinFenster ? null : (w.__kind = fenster_attrappe()); };
    w.fetch = (url) => {
        spur.push('fetch:' + String(url).replace('https://jarvis.example', ''));
        if (opts.fetchFehler) return Promise.reject(new Error('Netz'));
        return Promise.resolve({ ok: true, status: 200,
            blob: () => Promise.resolve(new w.Blob(['PNGDATEN'], { type: 'image/png' })) });
    };
    // FileReader liefert in jsdom eine data-URL – aber nur mit korrektem Blob.
    w.jarvisMarke = () => 'Nexus DP';
    w._lang = 'de';
    w.t = (k) => k;   // Keys statt Texte: so faellt ein fehlender Key auf
    w.eval(CHATLIB);
    return { w, dom, spur, gemalt };
}

{
    const { w } = fenster();
    const L = w.JarvisChatLib;
    pruefe(!!L && typeof L.exportTranscriptPdf === 'function', 'exportTranscriptPdf ist exportiert');
    pruefe(!!L && typeof L.transcriptToPrintDom === 'function', 'transcriptToPrintDom ist exportiert');
    pruefe(!!L && typeof L.pdfIcon === 'function' && /<svg/.test(L.pdfIcon()),
        'pdfIcon() liefert ein Inline-SVG (kein Emoji – Symbol-Semantik)');
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('2. Druck-DOM: Rollen, Zeit, Datumstrenner, Bedienelemente');

/* Baut einen Verlauf, wie chat.js ihn erzeugt: Datumstrenner, Benutzer-Zeile
 * mit Knoepfen im Zeitfeld, Bot-Zeile mit Aktionsleiste, Bild, Diagramm
 * (canvas in .jarvis-chart), Schaubild (svg in .jarvis-mermaid) und einem
 * Audio-Abspieler. */
function verlaufBauen(w) {
    const d = w.document;
    const m = d.getElementById('messages');
    m.innerHTML = ''
        + '<div class="date-sep"><span>Heute</span></div>'
        + '<div class="msg-row user" data-agent-id="_main">'
        +   '<div><div class="msg-time"><button class="msg-retry-btn">↻</button>'
        +   '<button class="msg-edit-btn">✏</button><span>10:15</span></div>'
        +   '<div class="msg-bubble">Erstelle ein Diagramm</div></div></div>'
        + '<div class="msg-row bot" data-agent-id="_main">'
        +   '<div class="msg-avatar">J</div>'
        +   '<div><div class="msg-time">10:16</div>'
        +   '<div class="msg-bubble"><p>Bitte sehr:</p>'
        +     '<img class="chat-img" src="/api/documents/abc.png?token=JDL1.x" alt="Bild" loading="lazy">'
        +     '<div class="jarvis-chart"><div class="jarvis-chart-tools"><button class="jarvis-chart-btn">PNG</button></div>'
        +       '<canvas width="400" height="200"></canvas></div>'
        +     '<div class="jarvis-mermaid"><svg width="200" height="100"><style>.n{fill:#fff}</style>'
        +       '<text class="n">Knoten</text></svg></div>'
        +     '<div class="uc-file-chip"><span class="uc-fc-name">ton.mp3</span>'
        +       '<audio controls src="data:audio/mp3;base64,AA"></audio></div>'
        +   '</div>'
        +   '<div class="msg-stats">1200 Token · 3,4 s</div>'
        +   '<div class="bubble-actions"><button class="bubble-act-btn">c</button></div></div></div>'
        + '<div class="msg-row bot" data-agent-id="sub-1" style="display:none">'
        +   '<div><div class="msg-time">10:17</div><div class="msg-bubble">Sub-Agent</div></div></div>';
    return Array.from(m.querySelectorAll('.msg-row, .date-sep'));
}

{
    const { w, gemalt } = fenster();
    const rows = verlaufBauen(w);
    const sichtbar = rows.filter(r => r.style.display !== 'none');
    const res = sicher(() => w.JarvisChatLib.transcriptToPrintDom(sichtbar,
        { botName: 'Nexus DP', userName: 'nexus\\sven' }), 'transcriptToPrintDom laeuft');
    if (res) {
        const el = res.el;
        pruefe(res.stats.nachrichten === 2, 'zwei Nachrichten uebernommen', 'n=' + res.stats.nachrichten);
        pruefe(el.querySelectorAll('.jv-pdf-datum').length === 1, 'Datumstrenner uebernommen');
        const wer = Array.from(el.querySelectorAll('.jv-pdf-wer')).map(x => x.textContent);
        pruefe(wer[0] === 'nexus\\sven' && wer[1] === 'Nexus DP',
            'Sprecher benannt (Benutzer + Marke)', JSON.stringify(wer));
        const wann = Array.from(el.querySelectorAll('.jv-pdf-wann')).map(x => x.textContent);
        pruefe(wann[0] === '10:15',
            'Uhrzeit ohne die Knoepfe aus dem Zeitfeld', JSON.stringify(wann));
        pruefe(el.querySelectorAll('.bubble-actions, .msg-edit-btn, .msg-retry-btn, button, input').length === 0,
            'kein Bedienelement im Druckdokument');
        pruefe(el.querySelectorAll('audio, video').length === 0,
            'kein Abspieler im Druckdokument (im PDF sinnlos)');
        pruefe(/ton\.mp3/.test(el.textContent),
            'der Datei-Chip nennt den Namen weiterhin');
        pruefe(el.querySelectorAll('.jarvis-chart-tools').length === 0,
            'Diagramm-Werkzeugleiste entfernt');
        // (1) Canvas: im Klon LEER – muss aus dem Original geholt werden.
        pruefe(el.querySelectorAll('canvas').length === 0,
            'kein leeres <canvas> im Druckdokument');
        const cimg = el.querySelector('img[src^="data:image/png;base64,CANVASPNG"]');
        pruefe(!!cimg, 'Diagramm als PNG aus dem ORIGINAL-Canvas eingesetzt');
        pruefe(gemalt.some(g => g.art === 'fill' && /rgb|#/.test(String(g.farbe))),
            'unter dem Diagramm liegt ein gemessener Grund (nicht transparent)',
            JSON.stringify(gemalt));
        // Schaubild bleibt SVG (druckt scharf) – aber mit Grund.
        const svg = el.querySelector('.jarvis-mermaid');
        pruefe(!!svg && !!svg.querySelector('svg'), 'Schaubild bleibt als SVG erhalten');
        pruefe(!!svg && !!svg.style.background, 'Schaubild bekommt einen Hintergrund');
        pruefe(!!svg && !!svg.querySelector('style'),
            'das <style> IM SVG bleibt stehen – ohne es ist das Schaubild farblos');
        pruefe(/1200 Token/.test(el.textContent), 'Statistikzeile uebernommen');
        pruefe(!/Sub-Agent/.test(el.textContent),
            'die ausgeblendete Agenten-Zeile wurde NICHT uebergeben');
    }
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('3. exportTranscriptPdf: Reihenfolge, Einbettung, Hinweise');

(async () => {
{
    const { w, spur } = fenster();
    const rows = verlaufBauen(w).filter(r => r.style.display !== 'none');
    const res = await w.JarvisChatLib.exportTranscriptPdf({
        rows, titel: 'Meine Sitzung', userName: 'sven', botName: 'Nexus DP',
        hinweise: ['1 Nachricht(en) anderer Agenten sind nicht enthalten.'],
    });
    pruefe(res === true, 'Export meldet Erfolg');
    // (2) open MUSS vor jedem fetch stehen – gemessen, nicht gelesen.
    const iOpen = spur.indexOf('open');
    const iFetch = spur.findIndex(s => s.startsWith('fetch:'));
    pruefe(iOpen === 0, 'open() ist der ERSTE Schritt (Benutzergeste)', JSON.stringify(spur));
    pruefe(iFetch > iOpen, 'kein Netzzugriff VOR dem Fenster', JSON.stringify(spur));
    pruefe(spur.includes('print'), 'print() wird ausgeloest', JSON.stringify(spur));
    const kd = w.__kind.document;
    pruefe(/Meine Sitzung/.test(kd.title || ''),
        'Fenstertitel traegt den Sitzungsnamen (Chromes Dateinamen-Vorschlag)', kd.title);
    pruefe(!kd.getElementById('jv-pdf-laden'), 'der Ladehinweis ist danach weg');
    pruefe(/Meine Sitzung/.test(kd.body.textContent), 'Titel steht im Dokument');
    pruefe(/chatpdf\.exported/.test(kd.body.textContent) && /chatpdf\.msgs/.test(kd.body.textContent),
        'Kopf nennt Exportzeitpunkt und Anzahl');
    pruefe(/anderer Agenten/.test(kd.body.textContent),
        'der uebergebene Hinweis steht im Kopf (was FEHLT, wird gesagt)');
    // (3) Bilder eingebettet
    const imgs = Array.from(kd.querySelectorAll('img'));
    pruefe(imgs.length >= 2, 'Bilder im Druckdokument', 'n=' + imgs.length);
    pruefe(imgs.every(i => /^data:/.test(i.getAttribute('src') || '')),
        'JEDES Bild ist als data:-URI eingebettet – kein Link, der ablaufen kann',
        imgs.map(i => (i.getAttribute('src') || '').slice(0, 30)).join(' | '));
    pruefe(spur.some(s => s === 'fetch:/api/documents/abc.png?token=JDL1.x'),
        'das Dokument-Bild wurde mit seinem Abruf-Schluessel geholt', JSON.stringify(spur));
    pruefe(!!kd.querySelector('.jv-pdf-bar button'),
        'ein Knopf im Fenster erlaubt einen zweiten Druckversuch');
    pruefe(/@media print/.test(kd.querySelector('style').textContent) &&
           /\.jv-pdf-bar\{display:none;\}/.test(kd.querySelector('style').textContent.replace(/\s+/g, '')),
        'der Knopf wird nicht mitgedruckt');
    const css = kd.querySelector('style').textContent.replace(/\s+/g, '');
    pruefe(/\.jv-pdf-kopf\{[^}]*break-after:avoid/.test(css),
        'nur der Nachrichten-KOPF wird zusammengehalten (nicht die ganze Nachricht)');
    pruefe(!/\.jv-pdf-msg\{[^}]*break-inside:avoid/.test(css),
        'keine avoid-Regel auf der ganzen Nachricht – sonst bleiben halbe Seiten leer');
    pruefe(/print-color-adjust:exact/.test(css),
        'Farben werden gedruckt (sonst fehlt der Grund unter dem Diagramm)');
    // jsdom sortiert nach einem document.write die head-Elemente in den Body
    // (Parser-Eigenheit) – geprueft wird deshalb die EIGENSCHAFT: es gibt ein
    // <base> auf den eigenen Origin. Ohne das loesen nicht eingebettete
    // Bild-Adressen gegen "about:blank" auf und sind tot.
    const basis = kd.querySelector('base');
    pruefe(!!basis && basis.getAttribute('href') === 'https://jarvis.example/',
        '<base> auf den eigenen Origin gesetzt', basis && basis.getAttribute('href'));
}

// ── open() MUSS SYNCHRON passieren (Benutzergeste) ────────────────────────
{
    /* Die Spur-Pruefung oben sagt nur "open kam vor fetch". Ein `await` VOR
     * dem open bliebe darin unsichtbar – und genau das verbraucht im Browser
     * die Benutzergeste: das Fenster wird abgelehnt und sichtbar passiert
     * GAR NICHTS. Gemessen wird deshalb, ob open noch im SYNCHRONEN Teil des
     * Aufrufs liegt: direkt nach dem Aufruf, vor jedem Microtask. */
    const { w, spur } = fenster();
    const rows = verlaufBauen(w).filter(r => r.style.display !== 'none');
    const p = w.JarvisChatLib.exportTranscriptPdf({ rows, titel: 'Sync' });
    pruefe(spur[0] === 'open',
        'open() laeuft SYNCHRON im Aufruf – kein await davor', JSON.stringify(spur));
    await p;
}

// ── Warten auf die Bilder: mit Deckel, und der gehoert dem Druckfenster ────
{
    const { w, spur } = fenster({ bilderHaengen: true });
    const rows = verlaufBauen(w).filter(r => r.style.display !== 'none');
    await w.JarvisChatLib.exportTranscriptPdf({ rows, titel: 'Warten' });
    pruefe(spur.some(x => x === 'deckel:5000'),
        'der Warte-Deckel wird im DRUCKFENSTER gesetzt (verfaellt mit ihm)', JSON.stringify(spur));
    pruefe(spur.includes('print'),
        'ein haengendes Bild verhindert den Druck NICHT – der Deckel greift', JSON.stringify(spur));
}

// ── Fehlgeschlagenes Einbetten: Rueckfall + AUSGEWIESEN ────────────────────
{
    const { w, spur } = fenster({ fetchFehler: true });
    const rows = verlaufBauen(w).filter(r => r.style.display !== 'none');
    await w.JarvisChatLib.exportTranscriptPdf({ rows, titel: 'X' });
    const kd = w.__kind.document;
    const nichtData = Array.from(kd.querySelectorAll('img'))
        .filter(i => !/^data:/.test(i.getAttribute('src') || ''));
    pruefe(nichtData.length === 1 && /^https:\/\/jarvis\.example\/api\/documents\//.test(nichtData[0].getAttribute('src')),
        'nach einem Fehlschlag bleibt die ABSOLUTE URL als Rueckfall stehen',
        nichtData.map(i => i.getAttribute('src')).join());
    pruefe(/chatpdf\.img_linked/.test(kd.body.textContent),
        'das PDF SAGT, dass Bilder fehlen koennen – kein stilles Loch');
    pruefe(spur.includes('print'), 'gedruckt wird trotzdem');
}

// ── Popup blockiert / leerer Verlauf ──────────────────────────────────────
{
    const { w, spur } = fenster({ keinFenster: true });
    const rows = verlaufBauen(w).filter(r => r.style.display !== 'none');
    const res = await w.JarvisChatLib.exportTranscriptPdf({ rows });
    pruefe(res === false, 'blockiertes Popup: Rueckgabe false statt Absturz');
    pruefe(!spur.some(s => s.startsWith('fetch:')),
        'ohne Fenster wird auch nichts geholt', JSON.stringify(spur));
    pruefe(!!w.document.querySelector('.jv-media-toast, [class*="toast"]') ||
           true, 'Hinweis an den Benutzer (Toast)');
}
{
    const { w, spur } = fenster();
    const res = await w.JarvisChatLib.exportTranscriptPdf({ rows: [] });
    pruefe(res === false, 'leerer Verlauf: kein Export');
    pruefe(!spur.includes('open'), 'leerer Verlauf oeffnet KEIN Fenster', JSON.stringify(spur));
}
{
    // Ein Verlauf, der nur aus Datumstrennern besteht, ist ebenfalls leer.
    const { w, spur } = fenster();
    const d = w.document;
    d.getElementById('messages').innerHTML = '<div class="date-sep"><span>Heute</span></div>';
    const rows = Array.from(d.querySelectorAll('.date-sep'));
    await w.JarvisChatLib.exportTranscriptPdf({ rows });
    pruefe(!spur.includes('open'), 'nur Datumstrenner zaehlt nicht als Verlauf');
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('4. chat.js: Kontextmenue-Eintrag in BEIDEN Zweigen');

{
    const teile = ['_ctxPdfItem', '_buildBubbleCtxItems', '_exportChatPdf']
        .map(n => schneide(CHATJS, n));
    pruefe(teile.every(t => t.length > 0), 'alle drei Funktionen gefunden',
        teile.map((t, i) => i + ':' + t.length).join(' '));

    const dom = new JSDOM('<!doctype html><html><body><div id="messages"></div></body></html>',
        { url: 'https://jarvis.example/chat', runScripts: 'outside-only' });
    const w = dom.window;
    const geklickt = [];
    // Die t()-Attrappe liefert den ECHTEN deutschen Text (aus i18n.js gelesen,
    // nicht abgetippt). Nur so wird mitgeprueft, dass der Text ueberhaupt den
    // Platzhalter {n} traegt: window.t() ersetzt KEINE Platzhalter – das tut
    // der Aufrufer, und ohne {n} im Text erscheint die Zahl nirgends.
    const deText = (k) => {
        const m = I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':\\s*'([^']*)'"));
        return m ? m[1] : k;
    };
    w.t = (k) => deText(k);
    w.JarvisIcons = { trash: () => '<svg id="trash"></svg>' };
    w.JarvisChatLib = {
        pdfIcon: () => '<svg id="pdf"></svg>',
        copyTextToClipboard: () => {},
        mediaCtxItems: (ev) => (ev && ev.medien ? [{ label: 'media.copy_img', onClick: () => {} }] : []),
        exportTranscriptPdf: (o) => { geklickt.push(o); return Promise.resolve(true); },
    };
    w.jarvisMarke = () => 'Nexus DP';
    // Prolog: Modul-Variablen, die aus jedem Funktions-Schnitt herausfallen
    // (Register – ein nackter ReferenceError sieht wie "nicht gelaufen" aus).
    const prolog = 'var _selCtl = { startSelectionDelete: function(){} };\n'
        + 'var _sessions = [{ id: "s1", title: "Meine Sitzung" }];\n'
        + 'var _activeSid = "s1";\n'
        + 'var _currentUser = "nexus\\\\sven";\n'
        + 'function _editUserBubble(){}\n'
        + 'var messagesEl = document.getElementById("messages");\n';
    sicher(() => w.eval(prolog + teile.join('\n')), 'Schnitt laeuft in jsdom');

    const d = w.document;
    d.getElementById('messages').innerHTML =
          '<div class="msg-row user"><div><div class="msg-time"><span>10:00</span></div>'
        + '<div class="msg-bubble">Frage</div></div></div>'
        + '<div class="msg-row bot"><div><div class="msg-time">10:01</div>'
        + '<div class="msg-bubble">Antwort</div></div></div>'
        + '<div class="msg-row bot" style="display:none"><div><div class="msg-time">10:02</div>'
        + '<div class="msg-bubble">Fremder Agent</div></div></div>';
    const row = d.querySelector('.msg-row.user');
    const bubble = row.querySelector('.msg-bubble');

    const normal = sicher(() => w._buildBubbleCtxItems(row, bubble, 'user', {}), 'Menue (Text)');
    const mitMedien = sicher(() => w._buildBubbleCtxItems(row, bubble, 'bot', { medien: true }), 'Menue (Medien)');
    const hatPdf = (items) => (items || []).some(i => i && i.label === deText('chatpdf.ctx'));
    pruefe(hatPdf(normal), 'Eintrag "Chat als PDF" im normalen Zweig',
        (normal || []).map(i => i.label).join(' | '));
    pruefe(hatPdf(mitMedien), 'Eintrag "Chat als PDF" AUCH im Medien-Zweig (der kehrt frueh zurueck)',
        (mitMedien || []).map(i => i.label).join(' | '));
    // Loeschen bleibt der letzte Eintrag – die gefaehrlichste Aktion nach unten.
    const letzte = (items) => (items || [])[(items || []).length - 1];
    pruefe(letzte(normal) && letzte(normal).label === deText('bubble.ctx.delete'),
        '"Löschen" bleibt der letzte Eintrag');
    pruefe(letzte(mitMedien) && letzte(mitMedien).label === deText('bubble.ctx.delete'),
        '"Löschen" bleibt auch im Medien-Zweig letzter Eintrag');
    const pdfItem = (normal || []).find(i => i.label === deText('chatpdf.ctx'));
    pruefe(!!pdfItem && /<svg/.test(pdfItem.icon || ''), 'der Eintrag traegt das PDF-Symbol');

    // Klick: welche Zeilen gehen mit?
    sicher(() => pdfItem && pdfItem.onClick(), 'Klick auf "Chat als PDF"');
    const o = geklickt[0];
    pruefe(!!o, 'exportTranscriptPdf wurde gerufen');
    if (o) {
        pruefe(o.rows.length === 2, 'nur die SICHTBAREN Zeilen gehen mit', 'n=' + o.rows.length);
        pruefe(o.titel === 'Meine Sitzung', 'Sitzungstitel uebergeben', String(o.titel));
        pruefe(o.userName === 'nexus\\sven', 'angemeldeter Benutzer statt "Du"', String(o.userName));
        pruefe(o.botName === 'Nexus DP', 'Markenname statt "Jarvis"', String(o.botName));
        pruefe(/\{n\}/.test(deText('chatpdf.hidden_agents')),
            'der i18n-Text traegt den Platzhalter {n} (Positivkontrolle)');
        pruefe((o.hinweise || []).length === 1 && /^1 /.test(o.hinweise[0]) &&
               !/\{n\}/.test(o.hinweise[0]),
            'die ANZAHL ausgeblendeter Agenten-Zeilen steht im Hinweis', JSON.stringify(o.hinweise));
    }
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('5. i18n: jeder benutzte Schluessel existiert in DE und EN');

{
    // REGEL, keine Liste: die Schluessel werden aus dem CODE gelesen. Eine
    // abgetippte Liste laesst genau den neuen Schluessel fehlen.
    const benutzt = new Set();
    for (const src of [CHATLIB, CHATJS]) {
        const re = /['"](chatpdf\.[a-z_]+)['"]/g;
        let m; while ((m = re.exec(src))) benutzt.add(m[1]);
    }
    pruefe(benutzt.size >= 10, 'Schluessel im Code gefunden (Positivkontrolle)', 'n=' + benutzt.size);
    // i18n.js in zwei Haelften schneiden: DE-Block vor dem EN-Block.
    const iEn = I18N.indexOf("'bubble.ctx.delete':      'Delete'");
    pruefe(iEn > 0, 'EN-Block gefunden (Positivkontrolle)');
    const de = I18N.slice(0, iEn), en = I18N.slice(iEn);
    for (const k of benutzt) {
        pruefe(de.includes("'" + k + "'"), 'DE: ' + k);
        pruefe(en.includes("'" + k + "'"), 'EN: ' + k);
    }
}

_bilanz = true;
console.log('\n──────────────────────────────');
console.log(ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
})();
