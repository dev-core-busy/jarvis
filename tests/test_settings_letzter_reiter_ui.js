#!/usr/bin/env node
/**
 * Einstellungen oeffnen auf dem ZULETZT benutzten Reiter.
 *
 * Gemeldet 2026-11-02: beim Wechsel zu "Einstellungen" stand immer "KI &
 * System" offen, nie der zuletzt benutzte Reiter. Ursache: `openModal()` in
 * app.js aktiviert an ihrem Ende fest den ersten Reiter, und gemerkt wurde
 * der Reiter nirgends.
 *
 * Gemessen wird im ECHTEN DOM (settings.html + app.js): `openModal()` ist
 * async, und genau die Reihenfolge darin entscheidet, welcher Reiter am Ende
 * steht - per Quelltext nicht pruefbar (siehe test_gear_badge_ui.js, Teil 4).
 *
 *   node tests/test_settings_letzter_reiter_ui.js
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
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const SITZUNG = lies('frontend/js/sitzung.js');
const ICONS   = lies('frontend/js/icons.js');
const I18N    = lies('frontend/js/i18n.js');
const APPJS   = lies('frontend/js/app.js');
const KEY     = 'jarvis_settings_letzter_reiter';

function stilleKonsole() {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (err) => {
        if (!/Not implemented: navigation/.test(String(err && err.message))) {
            console.log('  ! jsdomError: ' + err.message);
        }
    });
    return vc;
}

// Laedt die Einstellungsseite mit vorbelegtem Speicher und wartet, bis
// openModal() durch ist. `gemerkt`/`sprung` = null heisst: nicht setzen.
async function lade(gemerkt, sprung) {
    const dom = new JSDOM(lies('frontend/settings.html'),
        { url: 'https://x/settings', runScripts: 'outside-only',
          virtualConsole: stilleKonsole() });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 't:1:x');
    if (gemerkt !== null) w.localStorage.setItem(KEY, gemerkt);
    if (sprung !== null) w.sessionStorage.setItem('jarvis_settings_tab', sprung);
    // Skills: leer -> skill-gebundene Reiter (SAP) bleiben ausgeblendet
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
    w.eval(SITZUNG);
    w.eval(ICONS);
    w.eval(I18N);
    w.eval(APPJS);
    await new Promise((r) => setTimeout(r, 900));
    const knopf = [...w.document.querySelectorAll('.settings-tab-btn.active')]
        .map((b) => b.dataset.settingsTab);
    const panel = [...w.document.querySelectorAll('[id^=settings-tab-].active')]
        .map((b) => b.id);
    return { w, knopf, panel };
}

const nur = (r, reiter) => r.knopf.length === 1 && r.knopf[0] === reiter &&
    r.panel.length === 1 && r.panel[0] === 'settings-tab-' + reiter;

(async () => {
    abschnitt('0. Positivkontrolle: die Seite laedt und oeffnet ueberhaupt');
    {
        const r = await lade(null, null);
        const sap = r.w.document.getElementById('settings-tab-btn-sap');
        if (!(r.knopf.length >= 1 && sap)) {
            console.log('  ABBRUCH: kein aktiver Reiter bzw. kein SAP-Knopf - Messaufbau defekt '
                        + JSON.stringify(r.knopf));
            process.exit(2);
        }
        if (sap.style.display !== 'none') {
            console.log('  ABBRUCH: der SAP-Reiter ist sichtbar - der Fall "ausgeblendet" waere nicht herstellbar');
            process.exit(2);
        }
        pruefe(nur(r, 'profiles'), 'ohne gemerkten Reiter: "KI & System"',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }

    abschnitt('1. Der gemerkte Reiter steht offen');
    {
        const r = await lade('security', null);
        pruefe(nur(r, 'security'), 'gemerkt "security" -> GENAU Sicherheit, Knopf und Panel',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }
    {
        const r = await lade('cron', null);
        pruefe(nur(r, 'cron'), 'gemerkt "cron" -> GENAU Tasks',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }

    abschnitt('2. Ein Klick merkt den Reiter');
    {
        const r = await lade(null, null);
        const b = r.w.document.querySelector('.settings-tab-btn[data-settings-tab="cron"]');
        b.click();
        pruefe(r.w.localStorage.getItem(KEY) === 'cron', 'Klick auf Tasks wird gemerkt',
               String(r.w.localStorage.getItem(KEY)));
        r.w.close();
    }

    abschnitt('3. Rueckfaelle');
    {
        const r = await lade('sap', null);
        pruefe(nur(r, 'profiles'), 'ausgeblendeter Reiter (Skill aus) -> "KI & System", kein leeres Panel',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }
    {
        const r = await lade('gibtsnicht"]', null);
        pruefe(nur(r, 'profiles'), 'unbrauchbarer Wert -> "KI & System"',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }

    abschnitt('4. Ein ausdruecklicher Sprung hat Vorrang');
    {
        const r = await lade('cron', 'security');
        pruefe(nur(r, 'security'), 'gemerkt "cron", angefordert "security" -> Sicherheit',
               JSON.stringify([r.knopf, r.panel]));
        r.w.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
