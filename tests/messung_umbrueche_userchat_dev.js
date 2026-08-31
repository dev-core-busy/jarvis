#!/usr/bin/env node
/**
 * MESSUNG: bleiben Zeilenumbrueche in einer /userchat-Nachricht stehen?
 *
 * ⚠ WARUM NICHT DER ECHTE VERSANDWEG: eine Direktnachricht braucht ZWEI
 * angemeldete Menschen. Gemessen wird deshalb, was der Fix wirklich ist – die
 * WIRKUNG des ausgelieferten Inline-CSS auf eine `.uc-bubble` in der ECHTEN
 * Seite, fuer beide Seiten der Unterhaltung, samt Datei-Chip als Kind.
 * Den Renderweg (`linkify` maskiert, baut kein <br>) haelt der jsdom-Waechter.
 *
 * Aufruf: JARVIS_TOKEN=... node tests/messung_umbrueche_userchat_dev.js [https://host]
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require(process.env.WS_PATH ||
    path.join(__dirname, '..', 'node_modules', 'ws'));

const BASIS = process.argv[2] || 'https://191.100.144.1';
const TOK = process.env.JARVIS_TOKEN || '';
const PORT = 9355;
const PROFIL = fs.mkdtempSync('/tmp/chromeuc-');
const ABLAGE = process.env.SCRATCH || '/tmp';
if (!TOK) { console.log('ABBRUCH: JARVIS_TOKEN fehlt'); process.exit(2); }

const chrome = spawn('/usr/bin/google-chrome', [
    '--headless=new', '--remote-debugging-port=' + PORT, '--ignore-certificate-errors',
    '--no-first-run', '--no-sandbox', '--window-size=1280,900',
    '--user-data-dir=' + PROFIL, 'about:blank'], { stdio: 'ignore' });
const hole = (p) => new Promise((res, rej) => {
    http.get({ host: '127.0.0.1', port: PORT, path: p }, (r) => {
        let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
    }).on('error', rej);
});
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));

(async function () {
    let ziel = null;
    for (let i = 0; i < 60 && !ziel; i++) {
        try { ziel = (await hole('/json')).filter(t => t.type === 'page')[0]; }
        catch (e) { await schlaf(250); }
    }
    if (!ziel) { console.log('ABBRUCH: Chrome nicht erreichbar'); chrome.kill(); process.exit(2); }
    const w = new WebSocket(ziel.webSocketDebuggerUrl, { perMessageDeflate: false });
    await new Promise(r => w.on('open', r));
    let id = 0; const offen = new Map();
    w.on('message', (m) => {
        const a = JSON.parse(m);
        if (a.id && offen.has(a.id)) { offen.get(a.id)(a); offen.delete(a.id); }
    });
    const ruf = (method, params) => new Promise(r => {
        id += 1; offen.set(id, r);
        w.send(JSON.stringify({ id, method, params: params || {} }));
    });
    const js = async (e) => (await ruf('Runtime.evaluate',
        { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;

    await ruf('Page.enable'); await ruf('Runtime.enable');
    await ruf('Page.navigate', { url: BASIS + '/userchat' }); await schlaf(2500);
    await js('localStorage.setItem("jarvis_token", ' + JSON.stringify(TOK) + '); 1');
    await ruf('Page.navigate', { url: BASIS + '/userchat' }); await schlaf(4000);

    const TEXT = ['Zeile 1 der Messung', 'Zeile 2 der Messung', '', 'Zeile 4 nach Leerzeile'].join('\n');
    const z = await js(`(function(){
        // Ist die Seite ueberhaupt da (Skill aktiv)?
        if (!document.querySelector('.uc-bubble, #uc-messages, .uc-msgs, body'))
            return { huelle: 1 };
        var raus = {};
        ['mine','theirs'].forEach(function(seite){
            var b = document.createElement('div');
            b.className = 'uc-bubble ' + seite;
            b.textContent = ${JSON.stringify(TEXT)};
            document.body.appendChild(b);
            var st = getComputedStyle(b);
            var lh = parseFloat(st.lineHeight) || 0;
            var pad = parseFloat(st.paddingTop) + parseFloat(st.paddingBottom);
            raus[seite] = { whiteSpace: st.whiteSpace, hoehe: b.offsetHeight,
                            lineHeight: Math.round(lh * 10) / 10,
                            textzeilen: lh ? Math.round((b.offsetHeight - pad) / lh) : -1,
                            zurueck: b.textContent === ${JSON.stringify(TEXT)} };
            // Datei-Chip als Kind: erbt er pre-wrap?
            var c = document.createElement('div');
            c.className = 'uc-file-chip';
            b.appendChild(c);
            raus[seite].chipWhiteSpace = getComputedStyle(c).whiteSpace;
            b.remove();
        });
        return raus;
    })()`);

    if (!z || z.huelle) { console.log('ABBRUCH: /userchat liefert keine Seite'); }
    else {
        for (const seite of ['mine', 'theirs']) {
            const r = z[seite];
            console.log('\n' + (seite === 'mine' ? 'EIGENE' : 'FREMDE') + ' Nachricht (.' + seite + ')');
            console.log('   white-space   : ' + r.whiteSpace);
            console.log('   Hoehe         : ' + r.hoehe + 'px bei line-height ' + r.lineHeight
                + ' => ' + r.textzeilen + ' Textzeile(n) (erwartet 4)');
            console.log('   textContent   : ' + (r.zurueck ? 'vollstaendig zurueck' : 'UNVOLLSTAENDIG'));
            console.log('   Datei-Chip    : white-space ' + r.chipWhiteSpace + ' (erwartet normal)');
        }
    }

    const bild = (await ruf('Page.captureScreenshot', { format: 'png' })).result?.data;
    if (bild) {
        const datei = path.join(ABLAGE, 'umbrueche_userchat.png');
        fs.writeFileSync(datei, Buffer.from(bild, 'base64'));
        console.log('\n   Screenshot: ' + datei);
    }
    try { w.close(); } catch (e) {}
    chrome.kill();
    await schlaf(400);
    try { fs.rmSync(PROFIL, { recursive: true, force: true }); } catch (e) {}
    process.exit(0);
})().catch((e) => {
    console.error('ABBRUCH:', e);
    try { chrome.kill(); } catch (x) {}
    process.exit(2);
});
