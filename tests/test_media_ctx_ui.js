#!/usr/bin/env node
/**
 * Kontextmenue fuer Medien im Chat: "Bild kopieren" / "Anhang kopieren".
 *
 * WUNSCH DES NUTZERS (2026-08-10): "im /chat -> rechte Taste 'Bild kopieren'
 * oder 'Anhang kopieren' in die Zwischenablage waere mega".
 *
 * WAS DER BROWSER HERGIBT – und was nicht:
 *   `navigator.clipboard.write()` nimmt nur eine kleine, feste MIME-Liste an
 *   (text/plain, text/html, image/png). Eine .docx/.xlsx/.pdf laesst sich
 *   deshalb NICHT in die Zwischenablage legen – das ist eine Browser-Grenze.
 *   Umgesetzt ist daher:
 *     - Bilder, Chart.js-<canvas> und Mermaid-<svg> → echtes image/png-Kopieren
 *       (beim <canvas> hat das Browser-Menue GAR KEIN "Bild kopieren"),
 *     - Dateien → herunterladen / Link kopieren / Dateiname kopieren, und per
 *       Drag&Drop (`DownloadURL`) direkt in Explorer/Outlook ziehen.
 *
 * Laeuft gegen die ECHTEN Dateien (chatlib.js + chat.html). jsdom rechnet kein
 * Layout – geprueft werden Struktur, Eintraege, Aufrufe und die CSS-REGELN
 * selbst, nicht deren Wirkung.
 *
 *   node tests/test_media_ctx_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
const P = (...p) => path.join(ROOT, ...p);

// Gleicher Pfad wie in den uebrigen UI-Tests des Projekts (jsdom liegt nicht
// im Repo; ueber JSDOM_PATH umstellbar).
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const CHATLIB = fs.readFileSync(P('frontend/js/chatlib.js'), 'utf8');
const CHATJS = fs.readFileSync(P('frontend/js/chat.js'), 'utf8');
const I18N = fs.readFileSync(P('frontend/js/i18n.js'), 'utf8');
const CSS = fs.readFileSync(P('frontend/css/chat-bubbles.css'), 'utf8');
// Symbole (Muelleimer/Kreuz) – im Browser das ERSTE Skript jeder Seite.
// Module wie chat.js/knowledge.js rufen JarvisIcons.trash() beim Rendern auf;
// ohne diese Zeile bricht das Zeichnen mit 'JarvisIcons is not defined' ab.
const ICONS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

// ─── Umgebung: chatlib.js in ein jsdom-Fenster laden ─────────────────────────
function fenster() {
    const dom = new JSDOM('<!doctype html><html><body><div id="messages"></div></body></html>',
        { url: 'https://jarvis.example/chat', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'TOK123');
    // jsdom kennt weder ClipboardItem noch navigator.clipboard.write
    const geschrieben = [];
    w.ClipboardItem = function (obj) { this._obj = obj; };
    Object.defineProperty(w.navigator, 'clipboard', {
        value: {
            write: (items) => { geschrieben.push(items); return Promise.resolve(); },
            writeText: (t) => { geschrieben.push(t); return Promise.resolve(); },
        },
        configurable: true,
    });
    // <canvas> ohne canvas-Paket: toBlob nachbilden
    w.HTMLCanvasElement.prototype.toBlob = function (cb) { cb(new w.Blob(['png'], { type: 'image/png' })); };
    w.eval(CHATLIB);
    return { w, geschrieben, dom };
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('1. mediaCtxItems erkennt, worauf geklickt wurde');

{
    const { w } = fenster();
    const L = w.JarvisChatLib;
    pruefe(typeof L.mediaCtxItems === 'function', 'mediaCtxItems ist exportiert');

    const box = w.document.getElementById('messages');
    box.innerHTML = L.renderMarkdown(
        'Hier das Bild:\n\n![Blume](/api/generated/blume.png)\n\n'
        + 'Und die Datei: [Angebot.docx](/api/documents/aabbccddeeff00112233445566778899__Angebot.docx)\n');

    const img = box.querySelector('img.chat-img');
    const chip = box.querySelector('a.chat-doc-dl');
    pruefe(!!img, 'Bild gerendert');
    pruefe(!!chip, 'Datei-Chip gerendert');

    const iBild = L.mediaCtxItems({ target: img });
    const labels = iBild.map(x => x.label);
    pruefe(labels.some(l => /Bild kopieren/.test(l)), 'Bild: "Bild kopieren" dabei', labels.join(' | '));
    pruefe(labels.some(l => /Bild speichern/.test(l)), 'Bild: "Bild speichern" dabei');
    pruefe(labels.some(l => /neuem Tab/.test(l)), 'Bild: "in neuem Tab" dabei (hat eine src)');
    pruefe(iBild.every(x => typeof x.onClick === 'function'), 'alle Bild-Eintraege haben onClick');

    const iChip = L.mediaCtxItems({ target: chip });
    const cl = iChip.map(x => x.label);
    pruefe(cl.some(l => /herunterladen/.test(l)), 'Datei: "herunterladen" dabei', cl.join(' | '));
    pruefe(cl.some(l => /Link kopieren/.test(l)), 'Datei: "Link kopieren" dabei');
    pruefe(cl.some(l => /Dateinamen kopieren/.test(l)), 'Datei: "Dateinamen kopieren" dabei');
    // Ehrlichkeit: kein Eintrag darf behaupten, die DATEI selbst zu kopieren –
    // das kann der Browser nicht (nur text/plain, text/html, image/png).
    pruefe(!cl.some(l => /^Datei kopieren$/.test(l)),
           'KEIN Eintrag "Datei kopieren" (Browser erlaubt keine beliebigen MIME-Typen)');

    // Klick auf normalen Text → keine Medien-Eintraege
    const p = box.querySelector('p') || box;
    pruefe(L.mediaCtxItems({ target: p }).length === 0 || !box.querySelector('p'),
           'Klick auf Text liefert keine Medien-Eintraege');
    pruefe(L.mediaCtxItems({ target: box }).length === 0,
           'Klick auf den Container liefert keine Medien-Eintraege');
    pruefe(L.mediaCtxItems(null).length === 0, 'ohne Ereignis: leere Liste (kein Absturz)');
    pruefe(L.mediaCtxItems({}).length === 0, 'Ereignis ohne target: leere Liste');
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('2. Diagramme und Schaubilder – dort fehlt dem Browser der Eintrag');

{
    const { w } = fenster();
    const L = w.JarvisChatLib;
    const box = w.document.getElementById('messages');

    /* DIE CONTAINER-KLASSEN KOMMEN AUS DEM ECHTEN RENDERER, nicht aus diesem
     * Test. Erste Fassung baute `<pre class="mermaid">` – das gibt es nirgends,
     * mermaid_blocks.js rendert in `<div class="jarvis-mermaid">`. Der Test war
     * gruen und der Selektor in chatlib.js trotzdem falsch (`.mermaid svg`
     * trifft `jarvis-mermaid` NICHT). Deshalb: Platzhalter von
     * `renderMarkdown()` erzeugen lassen und nur den Inhalt einsetzen, den
     * charts.js/mermaid_blocks.js dort hineinschreiben. */
    box.innerHTML = L.renderMarkdown('```chartjs\n{"type":"bar"}\n```\n\n```mermaid\ngraph TD;\nA-->B;\n```');
    const chartBox = box.querySelector('.jarvis-chart');
    const mermBox = box.querySelector('.jarvis-mermaid');
    pruefe(!!chartBox, 'Chart-Platzhalter kommt aus dem echten Renderer');
    pruefe(!!mermBox, 'Mermaid-Platzhalter heisst .jarvis-mermaid (nicht pre.mermaid)');
    chartBox.innerHTML = '<canvas width="400" height="200"></canvas>'
                       + '<div class="jarvis-chart-tools"><button>PNG</button></div>';
    mermBox.innerHTML = '<svg width="300" height="200"><rect/></svg>';
    const canvas = box.querySelector('canvas');
    const svg = box.querySelector('svg');

    let it = L.mediaCtxItems({ target: canvas }).map(x => x.label);
    pruefe(it.some(l => /Bild kopieren/.test(l)), 'Canvas: "Bild kopieren" dabei', it.join(' | '));
    pruefe(!it.some(l => /neuem Tab/.test(l)), 'Canvas: kein "neuer Tab" (es gibt keine URL)');

    // Klick auf den Rahmen NEBEN dem Canvas trifft den Container – der Chart
    // hat eine Werkzeugleiste, ein Treffer daneben ist der Normalfall.
    it = L.mediaCtxItems({ target: box.querySelector('.jarvis-chart-tools') }).map(x => x.label);
    pruefe(it.some(l => /Bild kopieren/.test(l)),
           'Klick auf den Chart-Rahmen findet das Canvas trotzdem');

    it = L.mediaCtxItems({ target: svg }).map(x => x.label);
    pruefe(it.some(l => /Bild kopieren/.test(l)), 'Mermaid-SVG: "Bild kopieren" dabei');
}

// ═════════════════════════════════════════════════════════════════════════════
abschnitt('3. Kopieren landet wirklich in der Zwischenablage');

(async () => {
    {
        const { w, geschrieben } = fenster();
        const L = w.JarvisChatLib;
        const box = w.document.getElementById('messages');
        box.innerHTML = '<div class="jarvis-chart"><canvas width="80" height="40"></canvas></div>';
        const canvas = box.querySelector('canvas');

        const erfolg = await L.copyElementAsImage(canvas);
        pruefe(erfolg === true, 'copyElementAsImage(canvas) meldet Erfolg');
        pruefe(geschrieben.length === 1 && Array.isArray(geschrieben[0]),
               'navigator.clipboard.write wurde mit einer Liste gerufen');
        const item = geschrieben[0] && geschrieben[0][0];
        pruefe(item && item._obj && !!item._obj['image/png'],
               'der ClipboardItem traegt image/png (nicht image/webp o.ae.)');
        const toast = w.document.getElementById('jv-media-toast');
        pruefe(toast && /Zwischenablage/.test(toast.textContent) && toast.classList.contains('open'),
               'Rueckmeldung wird angezeigt (sonst ist der Klick unsichtbar)');
        pruefe(!toast.classList.contains('is-error'), 'kein Fehler-Zustand bei Erfolg');
    }

    // Fehlschlag muss SICHTBAR sein und darf nicht werfen
    {
        const { w } = fenster();
        const L = w.JarvisChatLib;
        Object.defineProperty(w.navigator, 'clipboard', {
            value: { write: () => Promise.reject(new Error('NotAllowedError')) },
            configurable: true,
        });
        const box = w.document.getElementById('messages');
        box.innerHTML = '<div class="jarvis-chart"><canvas width="80" height="40"></canvas></div>';
        const erfolg = await L.copyElementAsImage(box.querySelector('canvas'));
        pruefe(erfolg === false, 'abgelehnte Zwischenablage: Rueckgabe false statt Ausnahme');
        const toast = w.document.getElementById('jv-media-toast');
        pruefe(toast && toast.classList.contains('is-error'), 'Fehlschlag wird als Fehler gemeldet');
        pruefe(/Bild speichern/.test(toast.textContent),
               'die Meldung nennt die Alternative ("Bild speichern")');
    }

    // Link/Name kopieren
    {
        const { w, geschrieben } = fenster();
        const L = w.JarvisChatLib;
        const box = w.document.getElementById('messages');
        box.innerHTML = L.renderMarkdown(
            '[Angebot.docx](/api/documents/aabbccddeeff00112233445566778899__Angebot.docx)');
        const chip = box.querySelector('a.chat-doc-dl');
        const items = L.mediaCtxItems({ target: chip });
        await items.find(x => /Link kopieren/.test(x.label)).onClick();
        const link = geschrieben[0];
        pruefe(typeof link === 'string' && link.indexOf('https://jarvis.example') === 0,
               'der kopierte Link ist absolut', String(link));
        pruefe(/token=TOK123/.test(link),
               'das Token bleibt im kopierten Link (ohne waere er unbrauchbar)');
        await items.find(x => /Dateinamen/.test(x.label)).onClick();
        pruefe(geschrieben[1] === 'Angebot.docx',
               'der Dateiname kommt OHNE Capability-Praefix', String(geschrieben[1]));
    }

    // ═════════════════════════════════════════════════════════════════════════
    abschnitt('4. Datei aus dem Chat herausziehen (DownloadURL)');

    {
        const { w } = fenster();
        const L = w.JarvisChatLib;
        const box = w.document.getElementById('messages');
        box.innerHTML = L.renderMarkdown(
            '[Angebot.docx](/api/documents/aabbccddeeff00112233445566778899__Angebot.docx)');
        const chip = box.querySelector('a.chat-doc-dl');
        const daten = {};
        const ev = new w.Event('dragstart', { bubbles: true });
        ev.dataTransfer = { setData: (k, v) => { daten[k] = v; } };
        chip.dispatchEvent(ev);
        pruefe(!!daten['DownloadURL'], 'dragstart setzt DownloadURL', JSON.stringify(daten));
        const teile = (daten['DownloadURL'] || '').split(':');
        pruefe(/wordprocessingml/.test(daten['DownloadURL'] || ''),
               'der MIME-Typ passt zur Endung (.docx)');
        pruefe((daten['DownloadURL'] || '').indexOf(':Angebot.docx:') > 0,
               'der Dateiname steht im DownloadURL-Format');
        pruefe(/token=TOK123/.test(daten['DownloadURL'] || ''),
               'die URL im DownloadURL traegt das Token (sonst 401 beim Ziehen)');
        pruefe(daten['text/uri-list'] && daten['text/plain'],
               'Rueckfall fuer Browser ohne DownloadURL (Firefox) gesetzt');

        // Ein Bild ist KEIN Datei-Chip – dort darf nichts gesetzt werden
        box.innerHTML = L.renderMarkdown('![x](/api/generated/x.png)');
        const daten2 = {};
        const ev2 = new w.Event('dragstart', { bubbles: true });
        ev2.dataTransfer = { setData: (k, v) => { daten2[k] = v; } };
        box.querySelector('img').dispatchEvent(ev2);
        pruefe(Object.keys(daten2).length === 0,
               'beim Ziehen eines Bildes wird kein DownloadURL erzwungen');
    }

    // ═════════════════════════════════════════════════════════════════════════
    abschnitt('5. Das Browser-Menue bleibt erreichbar, Bestand bleibt intakt');

    {
        const { w } = fenster();
        const L = w.JarvisChatLib;
        const row = w.document.createElement('div');
        row.className = 'msg-row bot';
        w.document.body.appendChild(row);
        let gerufen = 0;
        L.setupBubbleContextMenu(row, (ev) => {
            gerufen++;
            // Der Aufrufer MUSS das Ereignis bekommen – sonst kann er nicht
            // unterscheiden, worauf geklickt wurde.
            pruefe(!!ev && 'shiftKey' in ev, 'getItems bekommt das Ereignis');
            return [{ label: 'X', icon: 'x', onClick: () => {} }];
        });

        const rechts = (shift) => {
            const e = new w.MouseEvent('contextmenu', { bubbles: true, cancelable: true });
            Object.defineProperty(e, 'shiftKey', { value: shift });
            row.dispatchEvent(e);
            return e;
        };
        let e1 = rechts(false);
        pruefe(e1.defaultPrevented, 'normaler Rechtsklick: eigenes Menue (preventDefault)');
        pruefe(gerufen === 1, 'getItems genau einmal gerufen');
        const menu = w.document.getElementById('jv-bubble-ctx-menu');
        pruefe(menu && menu.classList.contains('open'), 'Menue ist offen');

        const vorher = gerufen;
        const e2 = rechts(true);
        pruefe(!e2.defaultPrevented,
               'SHIFT+Rechtsklick laesst das BROWSER-Menue durch');
        pruefe(gerufen === vorher, 'bei SHIFT wird getItems nicht gerufen');
    }

    // Der bestehende Aufruf in chat.js reicht das Ereignis durch
    pruefe(/setupBubbleContextMenu\(row, \(ev\) => _buildBubbleCtxItems\(row, bubble, role, ev\)\)/.test(CHATJS),
           'chat.js: Streaming-Pfad gibt das Ereignis weiter');
    pruefe(/setupBubbleContextMenu\(row, \(ev\) => _buildBubbleCtxItems\(row, bubble, entry\.role, ev\)\)/.test(CHATJS),
           'chat.js: Wiederherstellungs-Pfad gibt das Ereignis weiter');
    pruefe(/function _buildBubbleCtxItems\(row, bubble, role, ev\)/.test(CHATJS),
           'chat.js: _buildBubbleCtxItems nimmt das Ereignis');
    // Bei einem Medien-Treffer bleiben Text-Kopieren und Loeschen erreichbar,
    // "Bearbeiten" entfaellt (ein Bild bearbeitet man nicht).
    const _mb = CHATJS.slice(CHATJS.indexOf('const medien = window.JarvisChatLib'));
    const _mbBlock = _mb.slice(0, _mb.indexOf("if (role === 'user')"));
    pruefe(/bubble\.ctx\.copy/.test(_mbBlock) && /bubble\.ctx\.delete/.test(_mbBlock),
           'Medien-Menue behaelt "Text kopieren" und "Loeschen"');
    pruefe(!/bubble\.ctx\.edit/.test(_mbBlock),
           'Medien-Menue zeigt kein "Bearbeiten"');

    // ═════════════════════════════════════════════════════════════════════════
    abschnitt('6. i18n und CSS');

    const keys = ['media.copy_img', 'media.save_img', 'media.open_img', 'media.download',
                  'media.copy_link', 'media.copy_name', 'media.copied_img',
                  'media.copied_link', 'media.copied_name', 'media.copy_failed',
                  'media.copy_img_failed', 'media.save_img_failed', 'media.chip_hint'];
    let fehlend = keys.filter(k => (I18N.split("'" + k + "'").length - 1) !== 2);
    pruefe(fehlend.length === 0, 'alle 13 i18n-Schluessel in DE UND EN', fehlend.join(', '));

    pruefe(/\.jv-media-toast\s*\{/.test(CSS), 'CSS fuer die Rueckmeldung vorhanden');
    // DECKENDE Flaeche: der Hinweis liegt ueber dem Chatverlauf.
    const toastCss = CSS.slice(CSS.indexOf('.jv-media-toast {'), CSS.indexOf('.jv-media-toast.open'));
    pruefe(/background:\s*var\(--bg-secondary\)/.test(toastCss),
           'Rueckmeldung ist DECKEND (var(--bg-secondary)), nicht halbtransparent');
    pruefe(/pointer-events:\s*none/.test(toastCss),
           'Rueckmeldung faengt keine Klicks ab');
    pruefe(!/#[0-9a-fA-F]{6}/.test(toastCss),
           'keine harten Farben – nur CSS-Variablen');
    const tz = /z-index:\s*(\d+)/.exec(toastCss);
    const mz = /z-index:\s*(\d+)/.exec(CSS.slice(CSS.indexOf('.jv-bubble-ctx-menu {')));
    pruefe(tz && mz && Number(tz[1]) > Number(mz[1]),
           'Rueckmeldung liegt ueber dem Kontextmenue', tz && mz ? tz[1] + ' vs ' + mz[1] : '?');
    pruefe(/title="\$\{tip\}"/.test(CHATLIB),
           'der Datei-Chip traegt einen Hinweis-Tooltip (Ziehen/Rechtsklick)');
    pruefe(!/cursor:\s*grab;\s*\}/.test(CSS.slice(CSS.indexOf('.chat-doc-dl:active'))),
           'der Chip behaelt den Klick-Zeiger (Download ist die Hauptaktion)');

    console.log('\n' + '='.repeat(70));
    console.log('Ergebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
})();
