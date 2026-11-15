#!/usr/bin/env node
/**
 * Beim Reiterwechsel in den Einstellungen bleibt GENAU EIN Panel sichtbar.
 *
 * Gemeldet 2026-11-15: nach "AI-Maus" -> "Newsfeed" blieben in Chrome die
 * AI-Maus-Container stehen, der Newsfeed haengte sich darunter an. Ursache:
 * `tabAimouse` fehlte in der Handliste `allSettingsTabs` (app.js), die beim
 * Wechsel alle Panels ausblendet.
 *
 * Gemessen im ECHTEN DOM (settings.html + app.js): jeder Reiterknopf wird
 * nacheinander geklickt, und nach JEDEM Klick wird gezaehlt, wie viele
 * `.settings-tab-content` nicht ausgeblendet sind. Die Liste der Panels kommt
 * aus dem Markup, nicht aus einer Liste im Test.
 *
 *   node tests/test_settings_reiter_wechsel_ui.js
 */
require('./lib/bilanz')();

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' - ' + d : '')); }
};

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

(async () => {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (err) => {
        if (!/Not implemented: navigation/.test(String(err && err.message))) {
            console.log('  ! jsdomError: ' + err.message);
        }
    });
    const dom = new JSDOM(lies('frontend/settings.html'),
        { url: 'https://x/settings', runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 't:1:x');
    w.fetch = (url) => {
        const pfad = String(url).split('?')[0];
        const daten = pfad === '/api/skills' ? []
            : { valid: true, success: true, username: 'jarvis', is_admin: true,
                permissions: {}, license_banner: '',
                admin_badge: { root_pending: 0, gesperrt: 0, gesamt: 0 } };
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(daten) });
    };
    w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {},
        removeListener() {}, addEventListener() {}, removeEventListener() {} }));
    w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    w.WebSocket = function () { this.close = () => {}; this.send = () => {}; };
    w.eval(lies('frontend/js/sitzung.js'));
    w.eval(lies('frontend/js/icons.js'));
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(lies('frontend/js/app.js'));
    await new Promise((r) => setTimeout(r, 900));

    const d = w.document;
    const panels = [...d.querySelectorAll('.settings-tab-content')];
    const knoepfe = [...d.querySelectorAll('.settings-tab-btn[data-settings-tab]')]
        .filter((b) => d.getElementById('settings-tab-' + b.dataset.settingsTab));

    console.log('\n=== 0. Positivkontrolle ===');
    if (panels.length < 20 || knoepfe.length < 20
        || !knoepfe.some((b) => b.dataset.settingsTab === 'aimouse')
        || !knoepfe.some((b) => b.dataset.settingsTab === 'newsfeed')) {
        console.log('  ABBRUCH: Messaufbau defekt - Panels ' + panels.length
                    + ', Knoepfe ' + knoepfe.length);
        process.exit(2);
    }
    console.log('  ' + panels.length + ' Panels, ' + knoepfe.length + ' Reiterknoepfe');

    const sichtbar = () => panels.filter((p) => p.style.display !== 'none').map((p) => p.id);
    const klick = (name) => {
        const b = knoepfe.find((k) => k.dataset.settingsTab === name);
        try { b.click(); } catch (e) { /* Reiter-Initialisierung ohne Backend */ }
        // Drei Reiter binden ihre Klapp-Container ueber ihr MODUL (onShow ruft
        // die Bruecke window.init…Collapse aus app.js). Die Module laedt dieser
        // Pruefstand nicht - er ruft die Bruecke deshalb selbst, wie onShow.
        const bruecke = { email: 'initEmailCollapse', tracks: 'initTracksCollapse',
                          excel: 'initExcelCollapse' }[name];
        if (bruecke && typeof w[bruecke] === 'function') w[bruecke]();
    };

    console.log('\n=== 1. Der gemeldete Fall: AI-Maus -> Newsfeed ===');
    klick('aimouse');
    klick('newsfeed');
    const s1 = sichtbar();
    pruefe(s1.length === 1 && s1[0] === 'settings-tab-newsfeed',
           'nach AI-Maus -> Newsfeed steht NUR der Newsfeed', JSON.stringify(s1));

    console.log('\n=== 2. Jeder Reiter blendet JEDEN Vorgaenger aus ===');
    // Zwei Durchgaenge in Gegenrichtung: jedes Panel ist einmal Vorgaenger
    // jedes Nachbarn, also faellt ein vergessenes Panel in jedem Fall auf.
    const namen = knoepfe.map((k) => k.dataset.settingsTab);
    for (const folge of [namen, namen.slice().reverse()]) {
        for (const n of folge) {
            klick(n);
            const s = sichtbar();
            pruefe(s.length === 1 && s[0] === 'settings-tab-' + n,
                   'Klick "' + n + '" -> genau ein Panel', JSON.stringify(s));
        }
    }

    console.log('\n=== 3. Jeder Klapp-Container jedes Reiters laesst sich klappen ===');
    // REGEL statt Liste: jeder .kb-collapse-header im Markup eines Reiters,
    // dessen Rumpf <kenn>-body heisst, muss nach dem Oeffnen des Reiters auf
    // einen Klick reagieren. Ein Container, der in keiner Klapp-Liste steht,
    // bliebe sonst tot (bzw. zugeklappt, wenn er so gemerkt war).
    let geprueft = 0;
    for (const n of namen) {
        klick(n);
        const panel = d.getElementById('settings-tab-' + n);
        for (const kopf of panel.querySelectorAll('.kb-collapse-header[id$="-hdr"]')) {
            const rumpf = d.getElementById(kopf.id.slice(0, -4) + '-body');
            if (!rumpf) continue;
            geprueft++;
            const vorher = rumpf.style.display === 'none';
            kopf.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
            const nachher = rumpf.style.display === 'none';
            kopf.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
            pruefe(vorher !== nachher && (rumpf.style.display === 'none') === vorher,
                   n + ': "' + (kopf.textContent || '').trim().split('\n')[0].slice(0, 40)
                   + '" klappt und klappt zurueck', kopf.id);
        }
    }
    if (geprueft < 40) {
        console.log('  ABBRUCH: nur ' + geprueft + ' Klapp-Koepfe gefunden - Messaufbau defekt');
        process.exit(2);
    }

    w.close();
    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
