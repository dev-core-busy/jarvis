#!/usr/bin/env node
/**
 * Live-Abnahme im ECHTEN Chrome (DEV): Einstellungs-Reiter und Portal-Kacheln
 * stehen alphabetisch, das Video bleibt am Ende.
 *
 * WARUM ZUSAETZLICH ZU jsdom: dort laufen die Sichtbarkeits-Abrufe
 * (`/api/me`, `/api/skills`) nicht. Erst im Browser zeigt sich, ob die
 * Reihenfolge auch dann stimmt, wenn Reiter und Kacheln NACHTRAEGLICH
 * eingeblendet werden – und ob nichts umbricht oder ueberlaeuft.
 *
 * Aufruf:  JARVIS_TOKEN=... node tests/live_alpha_sort_dev.js [https://host]
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require(process.env.WS_PATH ||
    path.join(__dirname, '..', 'node_modules', 'ws'));

const BASIS = process.argv[2] || 'https://191.100.144.1';
const TOK = process.env.JARVIS_TOKEN || '';
const PORT = 9347;
const PROFIL = fs.mkdtempSync('/tmp/chromesort-');
const ABLAGE = process.env.SCRATCH || '/tmp';
let ok = 0, bad = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { bad++; console.log('  FAIL ' + t + (d !== undefined ? ' -> ' + JSON.stringify(d) : '')); }
};
if (!TOK) { console.log('ABBRUCH: JARVIS_TOKEN fehlt'); process.exit(2); }

// Sortierung unabhaengig nachgerechnet – nicht aus der Seite uebernommen.
const sortiert = (t, lang) => t.slice().sort(new Intl.Collator(lang,
    { numeric: true, sensitivity: 'base', ignorePunctuation: true }).compare);

const chrome = spawn('/usr/bin/google-chrome', [
    '--headless=new', '--remote-debugging-port=' + PORT, '--ignore-certificate-errors',
    '--no-first-run', '--no-sandbox', '--window-size=1440,1000',
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
    const gehe = async (p) => { await ruf('Page.navigate', { url: BASIS + p }); await schlaf(2600); };

    await ruf('Page.enable'); await ruf('Runtime.enable');
    await gehe('/portal');
    await js('localStorage.setItem("jarvis_token", ' + JSON.stringify(TOK) + '); 1');

    // ═══ 1. Portal-Kacheln ════════════════════════════════════════════════
    console.log('\n1. /portal');
    for (const [lang, name] of [['de', 'Deutsch'], ['en', 'English']]) {
        await gehe('/portal');
        await js('window.setLang && window.setLang("' + lang + '"); 1');
        await schlaf(2600);                          // Sichtbarkeiten aus /api/me
        const z = await js(`(function(){
            var box = document.querySelector('.pt-cards');
            var alle = [].slice.call(box.children).filter(function(e){
                return e.classList.contains('pt-card'); });
            function sicht(e){ var s = getComputedStyle(e);
                return s.display !== 'none' && !e.classList.contains('hidden'); }
            return {
                titel: alle.filter(sicht).map(function(e){
                    var t = e.querySelector('.pt-card-title');
                    return t ? t.textContent.trim() : '(ohne Titel)'; }),
                letzteId: alle[alle.length-1].id,
                letzteSichtbar: alle.filter(sicht).map(function(e){ return e.id; }).pop(),
                video: (function(){ var v = document.getElementById('brand-portal-anim');
                    return v ? getComputedStyle(v).display : 'fehlt'; })(),
                ueberlauf: document.documentElement.scrollWidth
                           > document.documentElement.clientWidth + 2
            };
        })()`);
        pruefe(!!z && z.titel.length > 1, name + ': es sind Kacheln sichtbar',
               z && z.titel.length);
        pruefe(!!z && JSON.stringify(z.titel) === JSON.stringify(sortiert(z.titel, lang)),
               name + ': die SICHTBAREN Kacheln stehen alphabetisch',
               z && z.titel.join(' | '));
        pruefe(!!z && z.letzteId === 'brand-portal-anim',
               name + ': letztes Element im Raster ist die Video-Karte', z && z.letzteId);
        pruefe(!!z && !z.ueberlauf, name + ': kein waagerechter Ueberlauf');
    }

    // ═══ 2. Einstellungs-Reiter ═══════════════════════════════════════════
    console.log('\n2. /settings');
    for (const [lang, name] of [['de', 'Deutsch'], ['en', 'English']]) {
        await gehe('/settings');
        await schlaf(3200);                          // /api/skills + Reiter-Gates
        await js('window.setLang && window.setLang("' + lang + '"); 1');
        await schlaf(900);
        const z = await js(`(function(){
            var box = document.querySelector('.settings-tabs');
            var alle = [].slice.call(box.querySelectorAll('.settings-tab-btn'));
            function sicht(e){ return getComputedStyle(e).display !== 'none'; }
            var aktiv = box.querySelector('.settings-tab-btn.active');
            var panel = [].slice.call(document.querySelectorAll('.settings-tab-content'))
                .filter(function(p){ return getComputedStyle(p).display !== 'none'; })
                .map(function(p){ return p.id; });
            return {
                sichtbar: alle.filter(sicht).map(function(e){ return e.textContent.trim(); }),
                aktivReiter: aktiv ? aktiv.dataset.settingsTab : null,
                offenePanels: panel,
                ueberlauf: document.documentElement.scrollWidth
                           > document.documentElement.clientWidth + 2
            };
        })()`);
        pruefe(!!z && z.sichtbar.length > 8, name + ': es sind Reiter sichtbar',
               z && z.sichtbar.length);
        pruefe(!!z && JSON.stringify(z.sichtbar) === JSON.stringify(sortiert(z.sichtbar, lang)),
               name + ': die SICHTBAREN Reiter stehen alphabetisch',
               z && z.sichtbar.join(' | '));
        /* ⚠ DER EIGENTLICHE RISIKOPUNKT: der hervorgehobene Knopf muss der
         * sein, dessen Panel offen steht. Vorher hing der Rueckfall an
         * `settingsTabs[0]` – mit sortierten Reitern waere das der falsche
         * Knopf, und man saehe "Anweisungen" markiert ueber dem Profil-Panel. */
        pruefe(!!z && z.aktivReiter === 'profiles',
               name + ': hervorgehoben ist "KI & System"', z && z.aktivReiter);
        pruefe(!!z && z.offenePanels.length === 1
               && z.offenePanels[0] === 'settings-tab-profiles',
               name + ': und GENAU dessen Panel steht offen', z && z.offenePanels);
        pruefe(!!z && !z.ueberlauf, name + ': kein waagerechter Ueberlauf');
    }

    // ═══ 3. Sichtproben in hell und dunkel ════════════════════════════════
    console.log('\n3. Screenshots');
    for (const thema of ['dark', 'light']) {
        for (const seite of ['/portal', '/settings']) {
            await gehe(seite);
            await js('localStorage.setItem("jarvis_theme", "' + thema + '"); 1');
            await gehe(seite); await schlaf(3000);
            const bild = (await ruf('Page.captureScreenshot', { format: 'png' })).result?.data;
            if (bild) {
                const datei = path.join(ABLAGE,
                    'sort_' + seite.replace('/', '') + '_' + thema + '.png');
                fs.writeFileSync(datei, Buffer.from(bild, 'base64'));
                console.log('  Screenshot: ' + datei);
            }
        }
    }

    console.log('\n' + (bad === 0 ? 'ALLE ' + ok + ' PRUEFUNGEN OK' : ok + ' OK, ' + bad + ' FAIL'));
    try { w.close(); } catch (e) {}
    chrome.kill();
    /* ⚠ DAS AUFRAEUMEN DARF DAS ERGEBNIS NICHT KIPPEN. Chrome schreibt sein
     * Profil noch, wenn `kill()` zurueckkommt – `rmSync` lief in ENOTEMPTY und
     * der Fehler landete im aeusseren catch: der Lauf meldete erst "ALLE 18 OK"
     * und dann "ABBRUCH" mit Exit 2. Ein bestandener Lauf sah damit aus wie ein
     * nicht gelaufener (Register). */
    await schlaf(400);
    try { fs.rmSync(PROFIL, { recursive: true, force: true }); }
    catch (e) { console.log('  (Profil ' + PROFIL + ' blieb liegen: ' + e.code + ')'); }
    process.exit(bad ? 1 : 0);
})().catch((e) => {
    console.error('ABBRUCH:', e);
    try { chrome.kill(); } catch (x) {}
    process.exit(2);
});
