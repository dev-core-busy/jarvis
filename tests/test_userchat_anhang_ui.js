/* ═══════════════════════════════════════════════════════════════════════
   Waechter: HTML-Injection ueber Anhaenge im Benutzer-Chat (Befund B3, 2026-11)
   ───────────────────────────────────────────────────────────────────────
   `_renderFileChip` setzte `<a class="uc-fc-dl" href="${src}" …>` mit
   src = data:${att.mime_type};base64,${att.data} – beide Felder kommen vom
   ABSENDER. Ein `"` in `data` beendete das Attribut, danach stand beliebiges
   Markup (Ereignis-Attribute) im Chat des Empfaengers.

   Gemessen wird die WIRKUNG an den ECHTEN Funktionen aus userchat.js
   (per acorn geschnitten, in jsdom ausgefuehrt): ein boesartiger Anhang wird
   gerendert, danach wird das DOM gezaehlt – kein fremdes Element, kein
   Ereignis-Attribut, kein data:text/html-Link. Dazu die uebrigen Wege
   (Galerie-Bild, Lightbox-/Kontextmenue-Download ueber _downloadUrl).

   Ausgefuehrt: node tests/test_userchat_anhang_ui.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

const QUELLE = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'userchat.js'), 'utf-8');

let ok = 0, fail = 0;
function pruefe(text, bedingung, zusatz) {
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}

// ── Funktionen und Konstanten am Syntaxbaum schneiden ───────────────────
const baum = acorn.parse(QUELLE, { ecmaVersion: 'latest', sourceType: 'script' });
const FUNKTIONEN = ['escHtml', '_sauberesB64', '_dataUrl', '_downloadUrl', '_renderFileChip'];
const KONSTANTEN = ['_MIME_RE', '_B64_RE'];
const stuecke = {};
(function lauf(k) {
    if (!k || typeof k.type !== 'string') return;
    if (k.type === 'FunctionDeclaration' && k.id && FUNKTIONEN.includes(k.id.name))
        stuecke[k.id.name] = QUELLE.slice(k.start, k.end);
    if (k.type === 'VariableDeclaration') {
        for (const d of k.declarations)
            if (d.id && KONSTANTEN.includes(d.id.name))
                stuecke[d.id.name] = QUELLE.slice(k.start, k.end);
    }
    for (const w of Object.values(k)) {
        if (Array.isArray(w)) w.forEach(lauf);
        else if (w && typeof w.type === 'string') lauf(w);
    }
})(baum);
const fehlt = [...FUNKTIONEN, ...KONSTANTEN].filter(n => !stuecke[n]);
if (fehlt.length) {
    console.log('ABBRUCH: in userchat.js nicht gefunden: ' + fehlt.join(', '));
    process.exit(2);
}

const dom = new JSDOM('<!doctype html><body><div id="b"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
w.t = (k) => k;
w.showCtxMenu = () => {};
w.addLongPress = () => {};
w.eval(KONSTANTEN.map(n => stuecke[n]).join('\n') + '\n' +
       FUNKTIONEN.map(n => stuecke[n]).join('\n') + '\n' +
       'window._T = { escHtml, _dataUrl, _downloadUrl, _renderFileChip };');
const T = w._T;

function chip(att) {
    const b = w.document.getElementById('b');
    b.innerHTML = '';
    b.appendChild(T._renderFileChip(att, {}));
    return b;
}
function fremde(b) {
    // Elemente, die das Original-Markup nicht erzeugt
    const erlaubt = new Set(['DIV', 'SPAN', 'A', 'AUDIO', 'VIDEO']);
    const raus = [];
    for (const el of b.querySelectorAll('*')) {
        if (!erlaubt.has(el.tagName)) raus.push(el.tagName);
        for (const a of el.attributes) if (/^on/i.test(a.name)) raus.push(el.tagName + '[' + a.name + ']');
    }
    return raus;
}

// ── Positivkontrolle: ein harmloser Anhang rendert einen Download-Link ──
{
    const b = chip({ name: 'bericht.pdf', mime_type: 'application/pdf', data: 'JVBERi0xLjQK' });
    const a = b.querySelector('a.uc-fc-dl');
    if (!a) { console.log('ABBRUCH: Positivkontrolle – kein Download-Link gerendert'); process.exit(2); }
    pruefe('Positivkontrolle: Link mit Inhalt', a.getAttribute('href').endsWith('JVBERi0xLjQK'));
    pruefe('Positivkontrolle: Dateiname als download', a.getAttribute('download') === 'bericht.pdf');
}

console.log('\n1. Boesartiges data-Feld');
{
    const boese = 'AAAA" onmouseover="window.__x=1" x="';
    const b = chip({ name: 'x.pdf', mime_type: 'application/pdf', data: boese });
    pruefe('kein fremdes Element/Ereignis-Attribut im Chip', fremde(b).length === 0, fremde(b).join(','));
    const a = b.querySelector('a.uc-fc-dl');
    pruefe('Link-Adresse enthaelt den Fremdtext nicht', a && !a.getAttribute('href').includes('onmouseover'));
    const b2 = chip({ name: 'x.pdf', mime_type: 'application/pdf', data: '"><img src=x onerror=alert(1)>' });
    pruefe('kein <img> aus dem data-Feld', b2.querySelectorAll('img').length === 0 && fremde(b2).length === 0,
           fremde(b2).join(','));
}

console.log('\n2. Boesartiger mime_type');
{
    const b = chip({ name: 'x', mime_type: 'text/plain" onclick="alert(1)', data: 'QUJD' });
    pruefe('kein Ereignis-Attribut aus mime_type', fremde(b).length === 0, fremde(b).join(','));
    pruefe('_dataUrl faellt auf octet-stream zurueck',
           T._dataUrl({ mime_type: 'a" b', data: 'QUJD' }) === 'data:application/octet-stream;base64,QUJD');
    pruefe('_dataUrl laesst einen gueltigen Typ stehen',
           T._dataUrl({ mime_type: 'image/png', data: 'QUJD' }) === 'data:image/png;base64,QUJD');
}

console.log('\n3. Download nie als aktives Dokument');
{
    const b = chip({ name: 'x.html', mime_type: 'text/html', data: 'PGI+aGk8L2I+' });
    const a = b.querySelector('a.uc-fc-dl');
    pruefe('Download-Link ist application/octet-stream',
           a && a.getAttribute('href').startsWith('data:application/octet-stream;base64,'),
           a && a.getAttribute('href'));
    pruefe('_downloadUrl (Lightbox/Kontextmenue) ebenfalls neutral',
           T._downloadUrl({ mime_type: 'image/svg+xml', data: 'QUJD' }) === 'data:application/octet-stream;base64,QUJD');
    pruefe('_downloadUrl verwirft ungueltiges base64',
           T._downloadUrl({ data: 'AB"C' }) === 'data:application/octet-stream;base64,');
}

console.log('\n4. Boesartiger Dateiname');
{
    const b = chip({ name: '"><svg onload=alert(1)>.pdf', mime_type: 'application/pdf', data: 'QUJD' });
    pruefe('kein fremdes Element aus dem Namen', fremde(b).length === 0, fremde(b).join(','));
    const a = b.querySelector('a.uc-fc-dl');
    pruefe('Name steht woertlich im download-Attribut', a && a.getAttribute('download') === '"><svg onload=alert(1)>.pdf');
}

console.log('\n5. Alle Download-Wege laufen ueber _downloadUrl');
{
    // Regel am Syntaxbaum: jedes {href: …} bzw. .href = … in userchat.js, das
    // einen Anhang anspricht, benutzt _downloadUrl – nie _dataUrl.
    let hrefDataUrl = 0, hrefDownload = 0;
    (function lauf(k) {
        if (!k || typeof k.type !== 'string') return;
        const istHref = (k.type === 'Property' && k.key && (k.key.name === 'href' || k.key.value === 'href'))
            || (k.type === 'AssignmentExpression' && k.left && k.left.type === 'MemberExpression'
                && k.left.property && k.left.property.name === 'href');
        if (istHref) {
            const wert = k.type === 'Property' ? k.value : k.right;
            const t = QUELLE.slice(wert.start, wert.end);
            if (/_dataUrl\(/.test(t)) hrefDataUrl++;
            if (/_downloadUrl\(/.test(t)) hrefDownload++;
        }
        for (const v of Object.values(k)) {
            if (Array.isArray(v)) v.forEach(lauf);
            else if (v && typeof v.type === 'string') lauf(v);
        }
    })(baum);
    pruefe('kein href aus _dataUrl', hrefDataUrl === 0, hrefDataUrl);
    pruefe('mindestens drei Download-Wege ueber _downloadUrl', hrefDownload >= 3, hrefDownload);
    // (linkify setzt href weiter per Markup – dort ist der Text vorher maskiert
    // und das URL-Muster schliesst `"` aus; kein Anhang-Weg.)
}

console.log('\n' + '='.repeat(60));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(60));
w.close();
process.exit(fail ? 1 : 0);
