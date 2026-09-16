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

let JSDOM = null;
for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom',
                 path.join(ROOT, 'node_modules/jsdom'), '/usr/share/nodejs/jsdom']) {
    if (!k) continue;
    try { JSDOM = require(k).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht gefunden'); process.exit(2); }

const CHATJS = fs.readFileSync(path.join(ROOT, 'frontend/js/chat.js'), 'utf8');

function schneide(src, name) {
    const m = src.match(new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\('));
    if (!m) return '';
    let i = src.indexOf('{', m.index + m[0].length - 1);
    let tiefe = 0;
    for (let j = i; j < src.length; j++) {
        if (src[j] === '{') tiefe++;
        else if (src[j] === '}') { tiefe--; if (tiefe === 0) return src.slice(m.index, j + 1); }
    }
    return '';
}
// Modul-Konstanten fallen aus jedem Funktions-Schnitt heraus (Register).
const EXEC = CHATJS.slice(CHATJS.indexOf('const _EXEC_EXT'),
                          CHATJS.indexOf('const _MAX_FILE_BYTES') + 60);

const ADD = schneide(CHATJS, 'addFiles');
const REN = schneide(CHATJS, 'renderPreviews');
// Positivkontrolle des Schnitts: ein leerer Schnitt macht jede Aussage wertlos.
if (!ADD || !REN || !/_EXEC_EXT/.test(EXEC)) {
    console.log('ABBRUCH: Schnitt leer - Messung waere ohne Aussage'); process.exit(2);
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
    ${EXEC}
    ${REN}
    ${ADD}
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

function datei(name, mime, bytes) {
    return new w.File([new Uint8Array(bytes)], name, mime ? { type: mime } : {});
}

(async () => {
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
    console.log('\nBild-Erkennung im Quelltext:');
    console.log('  ' + (CHATJS.match(/if \(mime\.startsWith\('image\/'\).*$/m) || ['(nicht gefunden)'])[0].trim());
})();
