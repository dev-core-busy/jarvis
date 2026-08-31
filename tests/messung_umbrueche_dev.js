#!/usr/bin/env node
/**
 * MESSUNG (keine Abnahme): gehen Zeilenumbrueche in einer /chat-Nachricht
 * verloren – und WO?
 *
 * Gemeldet auf ECHT: "einen Text mit Zeilenumbrüchen kopiert und abgesendet.
 * In der Anzeige sind dann die Zeilenumbrüche weg."
 *
 * Gemessen wird an drei Stellen getrennt, weil sie verschiedene Antworten
 * braeuchten:
 *   1. EINGABE   – ueberlebt der Umbruch die textarea?
 *   2. ANZEIGE   – was steht in der Blase, und was macht das CSS daraus?
 *   3. SPEICHER  – steht der Umbruch im Transkript auf der Platte?
 * Dazu die Gegenprobe an einer BOT-Blase (renderMarkdown statt escapeHtml).
 *
 * Aufruf: JARVIS_TOKEN=... node tests/messung_umbrueche_dev.js [https://host]
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require(process.env.WS_PATH ||
    path.join(__dirname, '..', 'node_modules', 'ws'));

const BASIS = process.argv[2] || 'https://191.100.144.1';
const TOK = process.env.JARVIS_TOKEN || '';
const PORT = 9351;
const PROFIL = fs.mkdtempSync('/tmp/chromenl-');
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
    await ruf('Page.navigate', { url: BASIS + '/chat' }); await schlaf(2500);
    await js('localStorage.setItem("jarvis_token", ' + JSON.stringify(TOK) + '); 1');
    await ruf('Page.navigate', { url: BASIS + '/chat' }); await schlaf(4500);

    const TEXT = ['Zeile 1 der Messung', 'Zeile 2 der Messung', '', 'Zeile 4 nach Leerzeile'].join('\n');

    // ── 1. EINGABE ────────────────────────────────────────────────────────
    const eingabe = await js(`(function(){
        var i = document.getElementById('msg-input');
        if (!i) return { fehlt: 1 };
        i.value = ${JSON.stringify(TEXT)};
        i.dispatchEvent(new Event('input', { bubbles: true }));
        return { tag: i.tagName, umbrueche: (i.value.match(/\\n/g)||[]).length,
                 laenge: i.value.length, knopfAus: !!document.getElementById('btn-send').disabled };
    })()`);
    console.log('\n1. EINGABE');
    console.log('   Feld: ' + eingabe.tag + ' · Umbrueche im Wert: ' + eingabe.umbrueche
        + ' (erwartet 3) · Senden-Knopf gesperrt: ' + eingabe.knopfAus);

    // ── 2. ANZEIGE ────────────────────────────────────────────────────────
    await js('document.getElementById("btn-send").click(); 1');
    await schlaf(1800);
    const anzeige = await js(`(function(){
        var b = [].slice.call(document.querySelectorAll('.msg-row.user .msg-bubble')).pop();
        if (!b) return { fehlt: 1 };
        var st = getComputedStyle(b);
        // Wie viele SICHTBARE Zeilen? Ueber die Hoehe geteilt durch line-height.
        var lh = parseFloat(st.lineHeight) || 22;
        return {
            html: b.innerHTML,
            text: b.textContent,
            umbrueche_im_text: (b.textContent.match(/\\n/g)||[]).length,
            br_tags: b.querySelectorAll('br').length,
            whiteSpace: st.whiteSpace,
            hoehe: b.offsetHeight, lineHeight: lh,
            zeilen: Math.round(b.offsetHeight / lh),
        };
    })()`);
    console.log('\n2. ANZEIGE (Benutzer-Blase)');
    console.log('   innerHTML      : ' + JSON.stringify(anzeige.html));
    console.log('   <br>-Elemente  : ' + anzeige.br_tags);
    console.log('   CSS white-space: ' + anzeige.whiteSpace);
    console.log('   Hoehe          : ' + anzeige.hoehe + 'px bei line-height '
        + anzeige.lineHeight + ' => ' + anzeige.zeilen + ' sichtbare Zeile(n)');

    // ── 3. Gegenprobe: dieselbe Zeichenkette in einer BOT-Blase ───────────
    const bot = await js(`(function(){
        if (!window.JarvisChatLib || !window.JarvisChatLib.renderMarkdown) return { fehlt: 1 };
        var d = document.createElement('div');
        d.className = 'msg-bubble';
        d.innerHTML = window.JarvisChatLib.renderMarkdown(${JSON.stringify(TEXT)});
        (document.querySelector('.msg-row.user') || document.body).appendChild(d);
        var st = getComputedStyle(d);
        var lh = parseFloat(st.lineHeight) || 22;
        var r = { html: d.innerHTML, br: d.querySelectorAll('br').length,
                  p: d.querySelectorAll('p').length,
                  zeilen: Math.round(d.offsetHeight / lh) };
        d.remove();
        return r;
    })()`);
    console.log('\n3. GEGENPROBE (Bot-Blase, renderMarkdown)');
    console.log('   innerHTML: ' + JSON.stringify(bot.html));
    console.log('   <br>: ' + bot.br + ' · <p>: ' + bot.p + ' · sichtbare Zeilen: ' + bot.zeilen);

    // ── 4. SPEICHER: was steht im Transkript? ─────────────────────────────
    await schlaf(1500);
    const gespeichert = await js(`(async function(){
        var tk = localStorage.getItem('jarvis_token');
        var h = { Authorization: 'Bearer ' + tk };
        var l = await (await fetch('/api/chat/sessions', { headers: h })).json();
        var sid = (l.sessions && l.sessions[0] && l.sessions[0].id) || null;
        if (!sid) return { fehlt: 1, roh: JSON.stringify(l).slice(0, 200) };
        var s = await (await fetch('/api/chat/sessions/' + sid, { headers: h })).json();
        var tr = s.transcript || s.messages || [];
        var u = tr.filter(function(e){ return e.role === 'user'; }).pop();
        return { sid: sid, gefunden: !!u,
                 umbrueche: u ? (String(u.text||'').match(/\\n/g)||[]).length : -1,
                 text: u ? String(u.text||'').slice(0, 120) : '' };
    })()`);
    console.log('\n4. SPEICHER (Transkript auf der Platte)');
    console.log('   Sitzung: ' + gespeichert.sid + ' · Umbrueche im gespeicherten Text: '
        + gespeichert.umbrueche + ' (erwartet 3)');
    console.log('   Text   : ' + JSON.stringify(gespeichert.text));

    // Lauf beenden, damit auf DEV kein Agent weiterlaeuft.
    await js('(function(){var b=document.getElementById("btn-stop");if(b)b.click();return 1;})()');

    const bild = (await ruf('Page.captureScreenshot', { format: 'png' })).result?.data;
    if (bild) {
        const datei = path.join(ABLAGE, 'umbrueche_nachher.png');
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
