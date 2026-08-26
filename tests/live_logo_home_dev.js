#!/usr/bin/env node
/**
 * Live-Abnahme im ECHTEN Chrome (DEV): Klick auf das Marken-Logo fuehrt aufs
 * Portal. Vorgabe des Nutzers vom 2026-08-26.
 *
 * WARUM ZUSAETZLICH ZU jsdom: jsdom rechnet kein Layout und fuehrt keine echte
 * Navigation aus. Ob der Klick am Ende WIRKLICH auf /portal landet - und ob der
 * Zeiger im gerenderten Bild ein Zeigefinger ist - sieht nur ein Browser.
 *
 * Aufruf (Token wird gebraucht, sonst leitet jede Seite auf die Anmeldung um):
 *   JARVIS_TOKEN=... node tests/live_logo_home_dev.js [https://host]
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require(process.env.WS_PATH ||
    path.join(__dirname, '..', 'node_modules', 'ws'));

const BASIS = process.argv[2] || 'https://191.100.144.1';
const TOK = process.env.JARVIS_TOKEN || '';
const PORT = 9333;
const PROFIL = fs.mkdtempSync('/tmp/chromelogo-');
let ok = 0, bad = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { bad++; console.log('  FAIL ' + t + (d !== undefined ? ' -> ' + JSON.stringify(d) : '')); }
};
if (!TOK) { console.log('ABBRUCH: JARVIS_TOKEN fehlt'); process.exit(2); }

const chrome = spawn('/usr/bin/google-chrome', [
    '--headless=new', '--remote-debugging-port=' + PORT, '--ignore-certificate-errors',
    '--no-first-run', '--no-sandbox', '--window-size=1280,860',
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
    let id = 0;
    const offen = new Map();
    w.on('message', (m) => {
        const a = JSON.parse(m);
        if (a.id && offen.has(a.id)) { offen.get(a.id)(a); offen.delete(a.id); }
    });
    const ruf = (method, params) => new Promise(r => {
        id += 1; offen.set(id, r);
        w.send(JSON.stringify({ id, method, params: params || {} }));
    });
    const js = async (e) => (await ruf('Runtime.evaluate',
        { expression: e, returnByValue: true, awaitPromise: true }))
        .result?.result?.value;
    const gehe = async (p) => { await ruf('Page.navigate', { url: BASIS + p }); await schlaf(2300); };

    await ruf('Page.enable'); await ruf('Runtime.enable');
    await gehe('/portal');
    await js('localStorage.setItem("jarvis_token", ' + JSON.stringify(TOK) + '); 1');

    // WARUM `fehlt`/`huelle` unterschieden werden: eine Bereichsseite, die fuer
    // diesen Benutzer nicht freigegeben ist, haelt ihre GANZE Leiste verborgen
    // (z.B. /claude bei "claudesub: false"). Dann ist dort nichts zu messen -
    // und das muss DRANSTEHEN. Ein stiller Uebersprung meldet keinen Fehler, er
    // meldet gar nichts (Register).
    //
    // ⚠ FALLSTRICK IM EIGENEN TEST: in dem browserseitigen Code steht ein
    // Template-Literal. Ein Backtick darin - auch in einem Kommentar - schliesst
    // es und zerlegt die Datei ("missing ) after argument list").
    const SEITEN = (process.env.JARVIS_PAGES ||
        '/chat,/wissen,/tracks,/email,/sap,/support').split(',');
    for (const p of SEITEN) {
        await gehe(p); await schlaf(1300);
        const z = await js(`(function(){
            var l = document.querySelector('.topbar-avatar');
            if (!l) return { fehlt: 1,
                huelle: !document.querySelector('[data-i18n-title="nav.home"]') };
            var st = getComputedStyle(l);
            return { klasse: l.className, rolle: l.getAttribute('role'),
                     tab: l.getAttribute('tabindex'), titel: l.getAttribute('title'),
                     zeiger: st.cursor, text: (l.textContent||'').trim(),
                     haus: !!document.querySelector('[data-i18n-title="nav.home"]:not(.topbar-avatar)') };
        })()`);
        if (z && z.fehlt) {
            // Kein Logo im Dokument. Fehlt AUCH das Haus-Symbol, ist die Seite
            // eine leere Huelle (Bereich nicht freigegeben) - dann gibt es
            // nichts zu pruefen, und das wird BENANNT statt uebersprungen.
            // Fehlt nur das Logo, ist das ein echter Fehlschlag.
            if (z.huelle) {
                console.log('  ---- ' + p + ': NICHT PRUEFBAR - die Seite zeigt keine '
                    + 'Leiste (Bereich fuer diesen Benutzer nicht freigegeben). '
                    + 'Die Abdeckung dieser Seite haelt tests/test_logo_home_ui.js.');
                continue;
            }
            pruefe(false, p + ': Logo im Dokument gefunden', z);
            continue;
        }
        pruefe(!!z && /jv-logo-home/.test(z.klasse || ''),
            p + ': Logo verdrahtet (zeigt "' + (z && z.text) + '")', z);
        pruefe(!!z && z.zeiger === 'pointer', p + ': Zeiger ist pointer', z && z.zeiger);
        pruefe(!!z && z.rolle === 'button' && z.tab === '0',
            p + ': als Knopf bedienbar (role/tabindex)', z);
        pruefe(!!z && !!z.titel, p + ': tragt eine Beschriftung', z && z.titel);
        await js('document.querySelector(".topbar-avatar").click(); 1');
        await schlaf(2300);
        const wo = await js('location.pathname');
        pruefe(wo === '/portal', p + ': der Klick landet WIRKLICH auf /portal', wo);
    }

    // /portal selbst darf nichts bekommen - ein Link auf sich ist kein Weg.
    await gehe('/portal'); await schlaf(900);
    const zp = await js(`(function(){var l=document.querySelector('.topbar-avatar');
        return l ? { klasse: l.className, rolle: l.getAttribute('role'),
                     zeiger: getComputedStyle(l).cursor } : null;})()`);
    pruefe(!!zp && !/jv-logo-home/.test(zp.klasse || ''),
        '/portal: das Logo bleibt unangetastet', zp);
    pruefe(!!zp && zp.zeiger !== 'pointer', '/portal: kein Zeigefinger', zp && zp.zeiger);

    // Sichtprobe in beiden Themen.
    for (const thema of ['dark', 'light']) {
        await gehe('/chat');
        await js('localStorage.setItem("jarvis_theme", "' + thema + '"); 1');
        await gehe('/chat'); await schlaf(1500);
        const bild = (await ruf('Page.captureScreenshot', { format: 'png' })).result?.data;
        if (bild) {
            const datei = path.join(process.env.SCRATCH || '/tmp', 'logo_' + thema + '.png');
            fs.writeFileSync(datei, Buffer.from(bild, 'base64'));
            console.log('  Screenshot: ' + datei);
        }
    }

    console.log('\n  ' + ok + ' OK, ' + bad + ' FAIL');
    w.close(); chrome.kill();
    setTimeout(() => process.exit(bad ? 1 : 0), 300);
})().catch(e => { console.log('ABBRUCH: ' + e.message); chrome.kill(); process.exit(2); });
