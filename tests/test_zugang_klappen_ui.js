#!/usr/bin/env node
/* Waechter: Auf-/Zuklappen der vier Container "Mein …-Zugang" (2026-11-16).
 *
 * Vorgabe des Betreibers: "wenn keine persoenliche Anmeldung erforderlich ist
 * (weil gemeinsamer Zugang oder schon angemeldet), soll der Container
 * zugeklappt sein". Bis dahin standen VEMAS, Jira und Confluence fest auf
 * `open` im Markup, und nichts klappte sie je zu.
 *
 * jsdom gegen die ECHTEN Dateien (HTML + Seitenmodul, bei Jira/Confluence
 * zusaetzlich zugang_sitzung.js) mit gemockter API. Gemessen wird das
 * `open`-Attribut des <details> NACH dem Laden – je Lage:
 *   SAP/VEMAS  : gemeinsamer Zugang / eigener Zugang -> zu;
 *                kein Zugang, keine Anmeldekarte    -> offen;
 *                kein Zugang, Anmeldekarte darueber -> zu (dort geht es weiter)
 *   Jira/Conf. : gespeicherter Token / gemeinsamer Zugang -> zu;
 *                weder noch                               -> offen;
 *                Sitzungsbetrieb: angemeldet / gemeinsam  -> zu, sonst offen
 * Dazu: ein Klick des Benutzers bleibt stehen, wenn der Zustand neu
 * gezeichnet wird (kein Zurueckschnappen).
 *
 * KLAPPEN_DIR legt sabotierte KOPIEN von frontend/ vor (Gegenprobe:
 * tests/gegen_zugang_klappen.py).
 * Aufruf: node tests/test_zugang_klappen_ui.js   Exit 0 gruen, 1 FAIL, 2 kaputt
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const FRONT = process.env.KLAPPEN_DIR || path.join(ROOT, 'frontend');
const lies = (rel) => fs.readFileSync(path.join(FRONT, rel), 'utf8');
const SITZUNG = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Seiten-Steckbrief: HTML, Module, Container und die Antworten der API. */
const SEITEN = {
    sap:   { html: 'sap.html', module: ['js/sap_portal.js'], sect: 'sp-sect-account',
             perm: 'sap', status: '/api/sap/status' },
    vemas: { html: 'vemas.html', module: ['js/vemas_portal.js'], sect: 'vm-sect-account',
             perm: 'vemas', status: '/api/vemas/status' },
    jira:  { html: 'jira_addon.html', module: ['js/zugang_sitzung.js', 'js/jira_addon.js'],
             sect: 'ja-sect-account', sz: 'ja-sz-sect', perm: 'jira_assist',
             konto: '/api/jira/account' },
    confluence: { html: 'confluence_addon.html',
             module: ['js/zugang_sitzung.js', 'js/confluence_addon.js'],
             sect: 'ca-sect-account', sz: 'ca-sz-sect', perm: 'confluence',
             konto: '/api/confluence/account' },
};

async function laden(name, lage) {
    const s = SEITEN[name];
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const zaehler = { status: 0 };
    const dom = new JSDOM(lies(s.html), {
        url: 'https://localhost/' + name, runScripts: 'outside-only', virtualConsole: vc,
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.fetch = (url) => {
                const u = String(url).split('?')[0];
                const json = (data) => Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve(data),
                    text: () => Promise.resolve(JSON.stringify(data)),
                    blob: () => Promise.resolve(new win.Blob(['x'])) });
                if (u === '/api/me') {
                    const p = {}; p[s.perm] = true;
                    return json({ username: 'anna', permissions: p, is_admin: false });
                }
                if (s.status && u === s.status) {
                    zaehler.status++;
                    const st = typeof lage.status === 'function' ? lage.status(zaehler.status) : lage.status;
                    return json(Object.assign({ ok: true }, st));
                }
                if (s.konto && u === s.konto) return json({ ok: true, account: lage.konto });
                return json({ ok: true });
            };
        },
    });
    const w = dom.window;
    w.eval(SITZUNG);
    w.eval(I18N);
    w.eval(ICONS);
    for (const m of s.module) {
        try { w.eval(lies(m)); } catch (e) { fehler.push('eval ' + m + ': ' + e.message); }
    }
    await sleep(250);
    const $ = (id) => w.document.getElementById(id);
    return { w, $, fehler, sect: $(s.sect), sz: s.sz ? $(s.sz) : null };
}

/* Basisdaten der Lagen */
const SAP_GEMEINSAM = { configured: true, kachel_pflicht: false, quelle: 'sammel', connection_type: 'odata' };
const SAP_EIGEN     = { configured: true, kachel_pflicht: true, quelle: 'persoenlich', connection_type: 'odata' };
const SAP_NICHTS    = { configured: false, kachel_pflicht: false, quelle: 'keine' };
const SAP_KARTE     = { configured: false, kachel_pflicht: true, quelle: 'keine',
                        anmeldung: { feld: 'password', benutzer: 'MUSTER', kanal: 'basic' } };
const SAP_KACHEL_LEER = { configured: false, kachel_pflicht: true, quelle: 'keine',
                          hinweis: 'Anmeldung noetig.' };
const KONTO = { server_konfiguriert: true, basis_url: 'https://jira.beispiel.de',
                persoenlich_erlaubt: true, sitzungs_modus: false, aktiv: true };

(async () => {
    // ── Positivkontrolle: Container existieren und sind <details> ─────────
    for (const n of Object.keys(SEITEN)) {
        const k = await laden(n, { status: SAP_GEMEINSAM,
                                   konto: Object.assign({}, KONTO, { vorhanden: true, sammel_vorhanden: true }) });
        if (!k.sect || k.sect.tagName !== 'DETAILS' || (SEITEN[n].sz && (!k.sz || k.sz.tagName !== 'DETAILS'))) {
            console.log('ABBRUCH: Container fehlt auf ' + n);
            process.exit(2);
        }
        if (k.fehler.length) { console.log('ABBRUCH: Skriptfehler auf ' + n + ': ' + k.fehler.join('; ')); process.exit(2); }
    }

    for (const n of ['sap', 'vemas']) {
        console.log('\n' + n.toUpperCase() + ': Mein ' + n.toUpperCase() + '-Zugang');
        for (const [lage, st, offen] of [
            ['gemeinsamer Zugang', SAP_GEMEINSAM, false],
            ['eigener Zugang / angemeldet', SAP_EIGEN, false],
            ['kein Zugang, nichts zu tun ausser hier', SAP_NICHTS, true],
            ['Kachel-Pflicht ohne Anmeldedaten', SAP_KACHEL_LEER, true],
            ['Anmeldekarte darueber', SAP_KARTE, false],
        ]) {
            const k = await laden(n, { status: st });
            check(k.sect.open === offen, lage + ' -> ' + (offen ? 'offen' : 'zu'),
                  'open=' + k.sect.open);
        }
    }

    for (const n of ['jira', 'confluence']) {
        console.log('\n' + n + ': gespeicherter Token (persoenliche Zugaenge erlaubt)');
        for (const [lage, extra, offen] of [
            ['eigener Token vorhanden', { vorhanden: true, sammel_vorhanden: false }, false],
            ['gemeinsamer Zugang', { vorhanden: false, sammel_vorhanden: true }, false],
            ['weder Token noch gemeinsamer Zugang', { vorhanden: false, sammel_vorhanden: false }, true],
            ['eigener Token abgeschaltet, kein gemeinsamer', { vorhanden: true, aktiv: false, sammel_vorhanden: false }, true],
        ]) {
            const k = await laden(n, { konto: Object.assign({}, KONTO, extra) });
            check(k.sect.open === offen, lage + ' -> ' + (offen ? 'offen' : 'zu'), 'open=' + k.sect.open);
        }

        console.log('\n' + n + ': Anmeldung fuer die Sitzung (persoenliche Zugaenge aus)');
        const SZ = Object.assign({}, KONTO, { persoenlich_erlaubt: false, sitzungs_modus: true, vorhanden: false });
        for (const [lage, extra, offen] of [
            ['angemeldet', { angemeldet: true, sammel_vorhanden: false }, false],
            ['nicht angemeldet, gemeinsamer Zugang', { angemeldet: false, sammel_vorhanden: true }, false],
            ['nicht angemeldet, kein gemeinsamer Zugang', { angemeldet: false, sammel_vorhanden: false }, true],
        ]) {
            const k = await laden(n, { konto: Object.assign({}, SZ, extra) });
            check(k.sz.style.display !== 'none', lage + ': Container sichtbar');
            check(k.sz.open === offen, lage + ' -> ' + (offen ? 'offen' : 'zu'), 'open=' + k.sz.open);
        }

        console.log('\n' + n + ': Klick des Benutzers bleibt beim Neuzeichnen stehen');
        {
            const k = await laden(n, { konto: Object.assign({}, KONTO, { vorhanden: true, sammel_vorhanden: true }) });
            check(k.sect.open === false, 'Ausgangslage zu');
            k.sect.open = true;   // Benutzer klappt auf
            k.w.dispatchEvent(new k.w.Event('jarvis-lang-changed'));   // zeichnet neu
            await sleep(30);
            check(k.sect.open === true, 'nach Neuzeichnen weiter offen');
        }
    }

    console.log('\nERGEBNIS: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
