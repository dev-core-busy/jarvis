#!/usr/bin/env node
/**
 * Gemeinsame Titelleiste (frontend/js/kopfzeile.js).
 *
 * VORGABE (2026-11-16): "Logo, Branding, LLM Status Pill, Zertifikathinweis,
 * Update-Pill (nur Admin), CPU (nur Admin), 'i' (nur Admin), Logout sollen
 * immer sichtbar sein [Einstellungen muss dazu auch angepasst werden]" – und
 * die Leiste soll beim Seitenwechsel nicht neu aufgebaut WIRKEN.
 *
 * Teil 1  Einbindung je Seite (kopfzeile.js hinter sitzung.js, vor den Modulen,
 *         die ihre Elemente uebernehmen; Update-Widget + CSS ueberall)
 * Teil 2  Jede ECHTE Seite in jsdom: alle Kernelemente da, in der festen
 *         Reihenfolge, je Id genau einmal, Admin-Elemente markiert, und der
 *         gemerkte Stand steht SOFORT da (fetch antwortet absichtlich nie)
 * Teil 3  Der Merker gehoert genau einer Anmeldung; /api/me entscheidet
 * Teil 4  Die Module dahinter: Update-Pille fragt mit frischem Merker NICHT
 *         nach (sonst ein git fetch je Seitenwechsel), CPU ist fuer ALLE
 *         sichtbar (Nachtrag 2026-11-16), ⓘ uebernimmt den vorgebauten Knopf
 * Teil 5  CSS-Regeln (Admin-Sperre, View Transition) als REGEL – jsdom rechnet
 *         keine Kaskade (Register: `getComputedStyle` ignoriert Spezifitaet)
 * Teil 7  Rechte Gruppe: DE/EN, Desktop, Benutzer, Dokumente, Issues,
 *         Hell/Dunkel auf jeder Seite; kein Zertifikat-Download mehr
 * Teil 6  Box „Angemeldet als …“ auf /sap, /vemas, /jira-addon, /confluence-addon,
 *         „Mein …-Zugang“ als oberster Container, einheitliche Abstaende
 *
 *   node tests/test_kopfzeile_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const fertig = require('./lib/bilanz')({ stumm: true });
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
const abbruch = (t) => { console.log('ABBRUCH (konnte nicht messen): ' + t); process.exit(2); };

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const KOPF = lies('frontend/js/kopfzeile.js');
const UPDATE = lies('frontend/js/update_widget.js');
const CPUBAR = lies('frontend/js/cpubar.js');
const PAKETE = lies('frontend/js/syspackages.js');
const THEME = lies('frontend/css/theme.css');

// Seiten: alle HTML-Dateien mit Anmeldung (sitzung.js) – ausser der reinen
// API-Beschreibung fuer Support-Systeme, die keine Titelleiste hat. Die Liste
// wird GEMESSEN, nicht gepflegt: eine neue Seite ist von selbst dabei.
const OHNE_LEISTE = { 'support-api.html': 'Doku-Seite ohne Titelleiste und ohne Anmeldung' };
const SEITEN = fs.readdirSync(path.join(ROOT, 'frontend'))
    .filter((f) => f.endsWith('.html'))
    .filter((f) => /\/static\/js\/sitzung\.js/.test(lies('frontend/' + f)))
    .filter((f) => !OHNE_LEISTE[f])
    .sort();
if (SEITEN.length < 15) abbruch('nur ' + SEITEN.length + ' Seiten gefunden – Suchweg kaputt?');

// Dieselbe Pruefsumme wie kopfzeile.js::summe – aus dem Modul GESCHNITTEN,
// nicht nachgebaut: eine Abschrift prueft die eigene Annahme.
const summeQuelle = (KOPF.match(/function summe\(s\) \{[\s\S]*?\n    \}/) || [])[0];
if (!summeQuelle) abbruch('summe() in kopfzeile.js nicht gefunden');
const summe = new Function(summeQuelle + '; return summe;')();

const nurCode = (s) => s.replace(/<!--[\s\S]*?-->/g, '');
const skriptPos = (q, name) => {
    const m = new RegExp('<script src="/static/js/' + name.replace('.', '\\.') + '\\?v=\\d+"').exec(q);
    return m ? m.index : -1;
};

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Einbindung je Seite');
for (const f of SEITEN) {
    const q = nurCode(lies('frontend/' + f));
    const s = skriptPos(q, 'sitzung.js'), k = skriptPos(q, 'kopfzeile.js');
    pruefe(k > s && s >= 0, `${f}: kopfzeile.js steht hinter sitzung.js`, `sitzung=${s} kopfzeile=${k}`);
    for (const nach of ['cpubar.js', 'syspackages.js']) {
        const n = skriptPos(q, nach);
        if (n >= 0) pruefe(k >= 0 && k < n, `${f}: kopfzeile.js steht vor ${nach}`);
    }
    pruefe(skriptPos(q, 'update_widget.js') >= 0, `${f}: bindet update_widget.js ein`);
    pruefe(/href="\/static\/css\/update_widget\.css\?v=\d+"/.test(q), `${f}: bindet update_widget.css ein`);
}
// /settings war die Seite OHNE Leiste – sie braucht die Module der Admin-Elemente.
{
    const q = nurCode(lies('frontend/settings.html'));
    for (const m of ['cpubar.js', 'syspackages.js', 'sysload.js'])
        pruefe(skriptPos(q, m) >= 0, `settings.html: bindet ${m} ein`);
}

/* ═══════════════════════════════════════════════════════════════════════ */
// Eine Seite in jsdom laden. `fetch` antwortet NIE (Vorgabe): so ist alles,
// was danach im DOM steht, aus dem MERKER – genau die Zusage "sofort".
function seite(f, opt) {
    opt = opt || {};
    const html = lies('frontend/' + f).replace(/<script\b[\s\S]*?<\/script>/g, '');
    const dom = new JSDOM(html, { url: 'https://jarvis.beispiel.de/' + f.replace('.html', ''),
                                  runScripts: 'outside-only', pretendToBeVisual: true });
    const w = dom.window;
    w.__abrufe = [];
    w.fetch = (url) => {
        w.__abrufe.push(String(url).split('?')[0]);
        return opt.fetch ? opt.fetch(String(url).split('?')[0]) : new Promise(() => {});
    };
    sitzungLaden(w, opt.token === null ? undefined : { token: opt.token || 'TOK-A' });
    if (opt.stand !== undefined) {
        w.sessionStorage.setItem('jarvis_kopf', JSON.stringify(opt.stand));
    }
    w.eval(KOPF);
    if (!w.JarvisKopf) abbruch(f + ': kopfzeile.js hat kein window.JarvisKopf gesetzt');
    return dom;
}
function bereit(dom) {
    const d = dom.window.document;
    if (d.readyState !== 'loading') return Promise.resolve();
    return new Promise((ok_) => d.addEventListener('DOMContentLoaded', () => ok_()));
}
const STAND = (tok) => ({ k: summe(tok), admin: true, cpu: 42, version: '9.8.7',
                          llm: { c: 'connected', t: 'LLM erreichbar' } });

const KERN = [
    ['llm', '[data-kopf="llm"]'],
    ['schild', '#security-indicator, #jv-kopf-schild'],
    ['update', '#chat-update-wrap'],
    ['cpu', '#cpu-bar'],
    ['pakete', '#jv-pkg-btn'],
];

(async () => {
    abschnitt('2. Jede Seite: Kernelemente, Reihenfolge, gemerkter Stand');
    for (const f of SEITEN) {
        const dom = seite(f, { stand: STAND('TOK-A') });
        await bereit(dom);
        const d = dom.window.document;
        const wirt = d.querySelector('.jv-kopfzeile');
        pruefe(!!wirt, `${f}: Leiste gefunden und markiert`);
        if (!wirt) { dom.window.close(); continue; }

        pruefe(!!wirt.querySelector('.topbar-avatar, .sa-logo'), `${f}: Logo in der Leiste`);
        pruefe(!!wirt.querySelector('.brand-app-name'), `${f}: Marke in der Leiste`);
        pruefe(!!wirt.querySelector('[id*="logout"], .btn-logout'), `${f}: Abmelden in der Leiste`);

        const els = KERN.map(([n, sel]) => [n, wirt.querySelector(sel)]);
        for (const [n, e] of els) pruefe(!!e, `${f}: ${n} in der Leiste`);
        const da = els.filter(([, e]) => e);
        let reihe = da.length === KERN.length;
        for (let i = 1; i < da.length; i++) {
            const vor = da[i - 1][1], nach = da[i][1];
            if (vor.nextElementSibling !== nach) reihe = false;
        }
        pruefe(reihe, `${f}: LLM · Schild · Update · CPU · ⓘ stehen lueckenlos in dieser Reihenfolge`,
               da.map(([n, e]) => n + '<' + (e.nextElementSibling ? (e.nextElementSibling.id || e.nextElementSibling.className) : '-') + '>').join(' '));

        for (const id of ['cpu-bar', 'jv-pkg-btn', 'chat-update-wrap', 'version-pill', 'update-version'])
            pruefe(d.querySelectorAll('#' + id).length === 1, `${f}: #${id} genau einmal`);

        for (const [n, sel] of [['update', '#chat-update-wrap'], ['pakete', '#jv-pkg-btn']]) {
            const e = wirt.querySelector(sel);
            pruefe(!!e && e.classList.contains('jv-kopf-nuradmin'), `${f}: ${n} ist als Nur-Admin markiert`);
        }
        // Nachtrag 2026-11-16: "CPU sollen wie vorher alle sehen" – nur das
        // Systemauslastungs-Fenster dahinter ist Admins vorbehalten (sysload.js).
        const cpuEl = wirt.querySelector('#cpu-bar');
        pruefe(!!cpuEl && !cpuEl.classList.contains('jv-kopf-nuradmin'), `${f}: CPU ist fuer alle sichtbar (kein Nur-Admin)`);
        pruefe(d.documentElement.classList.contains('jv-kopf-admin'), `${f}: gemerkter Admin sofort auf <html>`);
        const lab = d.getElementById('cpu-bar-label');
        pruefe(!!lab && lab.textContent === 'CPU: 42%', `${f}: CPU zeigt sofort den gemerkten Wert`, lab && lab.textContent);
        const ver = d.getElementById('update-version');
        pruefe(!!ver && ver.textContent === 'v9.8.7', `${f}: Version sofort aus dem Merker`, ver && ver.textContent);
        const llm = wirt.querySelector('[data-kopf="llm"]');
        pruefe(!!llm && llm.classList.contains('connected'), `${f}: LLM-Zustand sofort aus dem Merker`);
        dom.window.close();
    }

    /* ═══════════════════════════════════════════════════════════════════ */
    abschnitt('3. Merker und Rolle');
    // Gegenkontrolle zu den Faellen darunter: mit passendem Merker IST die
    // Rolle da. Faellt sie aus, ist das ein PRODUKTbefund (die Zusage "sofort"
    // fehlt) – also FAIL, nicht Exit 2; die Negativfaelle waeren dann aber
    // trivial wahr und werden uebersprungen.
    let rolleWirkt;
    {
        const dom = seite('tracks.html', { stand: STAND('TOK-A') });
        rolleWirkt = dom.window.document.documentElement.classList.contains('jv-kopf-admin');
        dom.window.close();
        pruefe(rolleWirkt, 'Gegenkontrolle: passender Merker setzt die Rolle');
    }
    if (rolleWirkt) {
        const dom = seite('tracks.html', { token: 'TOK-B', stand: STAND('TOK-A') });
        const d = dom.window.document;
        pruefe(!d.documentElement.classList.contains('jv-kopf-admin'),
               'Merker einer ANDEREN Anmeldung zeigt keine Admin-Elemente');
        const lab = d.getElementById('cpu-bar-label');
        pruefe(!!lab && lab.textContent !== 'CPU: 42%',
               'Merker einer anderen Anmeldung fuellt die CPU nicht vor');
        dom.window.close();
    }
    if (rolleWirkt) {
        const dom = seite('tracks.html', { token: null, stand: STAND('TOK-A') });
        pruefe(!dom.window.document.documentElement.classList.contains('jv-kopf-admin'),
               'ohne Anmeldung keine Admin-Rolle');
        dom.window.close();
    }
    {
        const antwort = (body, status) => Promise.resolve({ ok: status === 200, status: status,
                                                            json: () => Promise.resolve(body) });
        const dom = seite('tracks.html', { stand: STAND('TOK-A'),
            fetch: (u) => u === '/api/me' ? antwort({ is_admin: false }, 200) : new Promise(() => {}) });
        await new Promise((r) => setTimeout(r, 20));
        const w = dom.window;
        pruefe(!w.document.documentElement.classList.contains('jv-kopf-admin'),
               '/api/me "kein Admin" nimmt die gemerkte Rolle zurueck');
        pruefe(w.JarvisKopf.adminBelegt() === false, 'adminBelegt() meldet den belegten Stand');
        const gespeichert = JSON.parse(w.sessionStorage.getItem('jarvis_kopf') || '{}');
        pruefe(gespeichert.admin === false, 'der Merker traegt danach "kein Admin"');
        w.close();
    }
    {
        const antwort = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
        const dom = seite('tracks.html', { stand: { k: summe('TOK-A') },
            fetch: (u) => u === '/api/me' ? antwort({ is_admin: true }) : new Promise(() => {}) });
        await new Promise((r) => setTimeout(r, 20));
        const w = dom.window;
        pruefe(w.document.documentElement.classList.contains('jv-kopf-admin'), '/api/me "Admin" setzt die Rolle');
        pruefe(JSON.parse(w.sessionStorage.getItem('jarvis_kopf')).admin === true, 'und merkt sie fuer die naechste Seite');
        w.close();
    }
    {
        // Abmelden dort, wo die Seite keins mitbringt (/supportagent).
        const dom = seite('supportagent.html', { stand: STAND('TOK-A') });
        const b = dom.window.document.getElementById('jv-kopf-logout');
        pruefe(!!b, '/supportagent bekommt einen Abmelde-Knopf');
        pruefe(!!b && !!b.closest('.sa-top-icons') && !b.nextElementSibling,
               'der Abmelde-Knopf steht als letztes Symbol rechts');
        dom.window.close();
    }

    /* ═══════════════════════════════════════════════════════════════════ */
    abschnitt('4. Module hinter der Leiste');
    {
        // Update-Pille: frischer Merker -> KEIN /api/update/status (git fetch).
        const lauf = (zeit) => {
            const dom = seite('tracks.html', { stand: Object.assign(STAND('TOK-A'),
                { update: { jarvis_version: '9.8.7', has_update: true, commits_behind: 3, ok: true, zeit: zeit } }) });
            const w = dom.window;
            w.eval(UPDATE);
            w.JarvisUpdateWidget.init();
            const n = w.__abrufe.filter((u) => u === '/api/update/status').length;
            const pill = w.document.getElementById('version-pill');
            const rot = !!pill && pill.classList.contains('has-update');
            w.close();
            return { n, rot };
        };
        // Gegenkontrolle: ein ALTER Merker fragt nach (sonst waere "keine
        // Abfrage" unten trivial wahr). Ein Ausfall ist ein Produktbefund.
        const alt = lauf(Date.now() - 60 * 60 * 1000);
        pruefe(alt.n === 1, 'Update-Pille: alter Merker -> fragt neu nach', 'Abrufe ' + alt.n);
        const frisch = lauf(Date.now());
        pruefe(alt.n === 1 && frisch.n === 0, 'Update-Pille: frischer Merker -> kein git fetch beim Seitenwechsel', 'Abrufe ' + frisch.n);
        pruefe(frisch.rot, 'Update-Pille: Farbe kommt sofort aus dem Merker');
    }
    {
        // CPU: fuer ALLE Angemeldeten (Nachtrag 2026-11-16) – auch ein belegter
        // Nicht-Admin bekommt Werte, und die Anzeige ist nicht als Nur-Admin markiert.
        const antwort = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
        const lauf = (admin) => {
            const dom = seite('tracks.html', { stand: { k: summe('TOK-A') },
                fetch: (u) => u === '/api/me' ? antwort({ is_admin: admin }) : new Promise(() => {}) });
            return new Promise((r) => setTimeout(() => {
                const w = dom.window;
                w.__abrufe.length = 0;
                w.eval(CPUBAR);
                const n = w.__abrufe.filter((u) => u === '/api/cpu').length;
                const bar = w.document.getElementById('cpu-bar');
                const markiert = !!bar && bar.classList.contains('jv-kopf-nuradmin');
                w.JarvisCpuBar.stop(); w.close();
                r({ n, markiert });
            }, 20));
        };
        const a = await lauf(true);
        pruefe(a.n === 1, 'CPU: fuer einen Admin wird abgefragt', 'Abrufe ' + a.n);
        const b = await lauf(false);
        pruefe(b.n === 1, 'CPU: auch fuer einen Nicht-Admin wird abgefragt', 'Abrufe ' + b.n);
        pruefe(!b.markiert, 'CPU: cpubar.js markiert die Anzeige nicht als Nur-Admin');
    }
    {
        // ⓘ: den vorgebauten Knopf uebernehmen und SOFORT klickbar machen.
        const dom = seite('tracks.html', { stand: STAND('TOK-A') });
        const w = dom.window;
        w.eval(PAKETE);
        await bereit(dom);   // syspackages.js startet bei DOMContentLoaded
        const b = w.document.getElementById('jv-pkg-btn');
        pruefe(w.document.querySelectorAll('#jv-pkg-btn').length === 1, 'ⓘ: kein zweiter Knopf');
        pruefe(!!b && b.dataset.jvPkgVerdrahtet === '1', 'ⓘ: vorgebauter Knopf ist verdrahtet, bevor /api/me antwortet');
        w.close();
    }

    /* ═══════════════════════════════════════════════════════════════════ */
    abschnitt('5. CSS-Regeln');
    {
        const css = THEME.replace(/\/\*[\s\S]*?\*\//g, '');
        pruefe(/html:not\(\.jv-kopf-admin\)\s+\.jv-kopf-nuradmin\s*\{\s*display:\s*none\s*!important;?\s*\}/.test(css),
               'Nur-Admin-Elemente sind ohne Rolle verborgen (!important gegen Inline-display)');
        pruefe(/@view-transition\s*\{\s*navigation:\s*auto;?\s*\}/.test(css), 'Seitenwechsel mit View Transition');
        const m = css.match(/([^{}]+)\{\s*view-transition-name:\s*jv-kopfzeile;?\s*\}/);
        const sel = m ? m[1] : '';
        for (const s of ['header.topbar', '.pt-topbar', '.wi-topbar', '.ad-top', '.sa-topbar', '#settings-modal .modal-header'])
            pruefe(sel.includes(s), `View-Transition-Name an der Bauform ${s}`);
        pruefe(/::view-transition-group\(jv-kopfzeile\)[\s\S]*?\{\s*animation:\s*none;?\s*\}/.test(css),
               'die Leiste selbst wird nicht animiert');
    }

    /* ═══════════════════════════════════════════════════════════════════ */
    abschnitt('6. „Angemeldet als …“ und Reihenfolge (Vorgabe 2026-11-16)');
    {
        const BOX = [
            { f: 'sap.html', pille: 'sp-conn', zugang: 'sp-sect-account', karte: '.sp-card:not(.sp-login)' },
            { f: 'vemas.html', pille: 'vm-conn', zugang: 'vm-sect-account', karte: '.vm-card:not(.vm-login)' },
            { f: 'jira_addon.html', pille: 'ja-sz-kopf', zugang: 'ja-sz-sect' },
            { f: 'confluence_addon.html', pille: 'ca-sz-kopf', zugang: 'ca-sz-sect' },
        ];
        for (const b of BOX) {
            const st = STAND('TOK-A'); st.benutzer = 'probe.name';
            const dom = seite(b.f, { stand: st });
            await bereit(dom);
            const d = dom.window.document;
            const box = d.querySelector('.jv-max-row > .jv-anmelde-box');
            pruefe(!!box, `${b.f}: Box "Angemeldet als" in der Zeile mit ⛶`);
            const name = box && box.querySelector('[data-kopf-benutzer]');
            pruefe(!!name && name.textContent === 'probe.name', `${b.f}: Name sofort aus dem Merker`, name && name.textContent);
            const pille = d.getElementById(b.pille);
            pruefe(!!pille && !!box && box.contains(pille), `${b.f}: Pille steht in der Box`);
            pruefe(!!pille && !pille.closest('header'), `${b.f}: Pille nicht mehr in der Titelleiste`);
            // Oberster Container = "Mein …-Zugang": in Dokumentreihenfolge vor
            // jedem anderen Container (Box und eine verborgene Anmeldekarte
            // zaehlen nicht).
            const zugang = d.getElementById(b.zugang);
            const andere = [...d.querySelectorAll('details, .sp-card, .vm-card, .ja-card')]
                .filter((e) => e !== zugang && !e.hidden && !e.closest('[hidden]')
                    && !(zugang && zugang.contains(e)) && !e.closest('header'));
            const davor = andere.filter((e) => zugang && (e.compareDocumentPosition(zugang) & 4));
            pruefe(!!zugang && davor.length === 0, `${b.f}: „Mein …-Zugang“ ist der oberste Container`,
                   davor.map((e) => e.id || e.className).join(', '));
            if (b.karte) {
                const k = d.querySelector(b.karte);
                const h = k && k.firstElementChild;
                pruefe(!!h && /^H[23]$/.test(h.tagName) && h.textContent.trim().length > 0,
                       `${b.f}: Analyse-/Abfrage-Container hat eine Ueberschrift`);
            }
            dom.window.close();
        }
    }
    {
        // Abstaende als REGEL (jsdom rechnet kein Layout; gemessen im Chrome).
        const css = THEME.replace(/\/\*[\s\S]*?\*\//g, '');
        pruefe(/--jv-oben:\s*16px/.test(css) && /--jv-abstand:\s*16px/.test(css), 'Masse: 16 px oben und zwischen Containern');
        pruefe(/#settings-modal \.settings-tabs\s*\{\s*margin-bottom:\s*0;?\s*\}/.test(css), '/settings: Reiterleiste ohne 32-px-Rand');
        pruefe(/#settings-modal \.kb-container\s*\{[^}]*gap:\s*var\(--jv-abstand\)/.test(css), '/settings: Container-Abstand = --jv-abstand');
        pruefe(/#settings-modal \.kb-container > \.sk-openclaw-section\s*\{\s*margin-top:\s*0;?\s*\}/.test(css), '/settings: Protokolle ohne Zusatzrand');
        const st = lies('frontend/settings.html');
        // Bis zum NAECHSTEN Reiter schneiden – die Klasse des eigenen Reiters
        // steht in derselben Zeile wie seine Id.
        const tele = (st.split('id="settings-tab-telemetry"')[1] || '').split('id="settings-tab-')[0];
        pruefe(tele.length > 1000 && !/class="sk-openclaw-section"[^>]*style="[^"]*margin/.test(tele),
               'Protokolle: kein Inline-Rand an den Containern');
    }

    /* ═══════════════════════════════════════════════════════════════════ */
    abschnitt('7. Rechte Gruppe auf jeder Seite (Vorgabe 2026-11-16)');
    for (const f of SEITEN) {
        const q = nurCode(lies('frontend/' + f));
        for (const m of ['info_files.js', 'issues.js', 'sessions.js', 'avatar.js', 'i18n.js'])
            pruefe(skriptPos(q, m) > skriptPos(q, 'sitzung.js'), `${f}: bindet ${m} ein`);
        pruefe(/\/static\/js\/avatar\.js[\s\S]*$/.test(q) && skriptPos(q, 'avatar.js') > q.indexOf('clippy.min.js') && q.indexOf('clippy.min.js') > 0,
               `${f}: clippy vor avatar.js`);
        const dom = seite(f, { stand: STAND('TOK-A') });
        await bereit(dom);
        const d = dom.window.document;
        const wirt = d.querySelector('.jv-kopfzeile');
        if (!wirt) { pruefe(false, `${f}: Leiste`); dom.window.close(); continue; }
        const teile = [
            ['DE/EN', '.lang-toggle'],
            ['Desktop', '#pt-vnc-btn, #jv-kopf-desktop'],
            ['Benutzer', '#pt-usr-wrap'],
            ['Dokumente', '#pt-info-wrap'],
            ['Issues', '.jv-issues-btn'],
            ['Hell/Dunkel', '#btn-theme-toggle, .btn-theme-toggle, #btn-theme'],
        ];
        const els = teile.map(([n, sel]) => [n, wirt.querySelector(sel)]);
        for (const [n, e] of els) pruefe(!!e, `${f}: ${n} in der Leiste`);
        const da = els.filter(([, e]) => e).map(([n, e]) => [n, e]);
        let reihe = da.length === teile.length;
        for (let i = 1; i < da.length; i++)
            if (!(da[i - 1][1].compareDocumentPosition(da[i][1]) & 4)) reihe = false;
        pruefe(reihe, `${f}: Reihenfolge DE/EN · Desktop · Benutzer · Dokumente · Issues · Hell/Dunkel`,
               da.map(([n]) => n).join(' '));
        for (const id of ['pt-info-wrap', 'pt-usr-wrap', 'pt-info-btn', 'pt-usr-btn'])
            pruefe(d.querySelectorAll('#' + id).length === 1, `${f}: #${id} genau einmal`);
        const desk = wirt.querySelector('#pt-vnc-btn, #jv-kopf-desktop');
        const usr = wirt.querySelector('#pt-usr-wrap');
        pruefe(!!desk && (desk.id === 'pt-vnc-btn' || desk.classList.contains('jv-kopf-nuradmin')), `${f}: Desktop nur fuer Admins`);
        pruefe(!!usr && (f === 'portal.html' || usr.classList.contains('jv-kopf-nuradmin')), `${f}: Benutzer nur fuer Admins`);
        const schild = wirt.querySelector('#security-indicator, #jv-kopf-schild');
        pruefe(!!schild && !schild.classList.contains('jv-kopf-nuradmin'), `${f}: Schild fuer jeden sichtbar`);
        pruefe(!wirt.querySelector('a[href="/api/cert"]'), `${f}: kein Zertifikat-Download in der Leiste`);
        dom.window.close();
    }

    fertig();
    console.log(`\n${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
