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

// Hoechstens so lange auf das Ende von openModal() warten (echte Zeit). Nur
// eine Notbremse fuer "kommt nie zu Ende" - das Ergebnis haengt NICHT an ihr.
const NOTBREMSE_MS = 120000;

// Laedt die Einstellungsseite mit vorbelegtem Speicher und wartet, bis
// openModal() durch ist. `gemerkt`/`sprung` = null heisst: nicht setzen.
//
// ⚠ WARUM KEINE FESTE WARTEZEIT (2026-11-22): hier stand `setTimeout(900)`.
// Allein reicht das, im Sammellauf unter Volllast nicht - openModal() war
// noch bei seinen await-Aufrufen, und gemessen wurde der Vorgabe-Reiter
// ("profiles" statt "security"): ein FAIL, der nichts ueber den Code sagt.
// Gewartet wird jetzt auf das ECHTE Ende: app.js legt openModal als
// `window._openSettingsModal` ab und ruft es von dort; die Eigenschaft wird
// vorher abgefangen, und der Lauf wartet auf das Promise genau dieses Aufrufs.
// ⚠ ALLE REITER ALS LEERE HUELLE (2026-11-23): gemessen wird nur, WELCHER
// Knopf und welches Panel `.active` tragen - kein Inhalt eines Reiters. Die
// volle Seite kostete je Aufbau ~0,9 s plus applyLang ueber alle Reiter, bei
// sieben Aufbauten der groesste Teil der Laufzeit. Knoepfe, Rahmen und jedes
// Panel-Element (mit id/class/style) bleiben. GANZ bleibt "KI & System":
// setupSettings() in app.js bindet dort den Anbieter-Schalter OHNE
// Null-Pruefung (tests/lib/seite_ausschnitt.js, ohneReiter).
const { ohneReiter } = require('./lib/seite_ausschnitt');
const SEITE = ohneReiter(lies('frontend/settings.html'), ['settings-tab-profiles'], { huelle: true });
if (SEITE.fehlend.length || SEITE.entfernt.length < 5) {
    console.log('ABBRUCH: settings.html ohne "KI & System" oder ohne erkennbare Reiter ('
                + JSON.stringify(SEITE.fehlend) + ', ' + SEITE.entfernt.length + ') - Messaufbau defekt');
    process.exit(2);
}

async function lade(gemerkt, sprung) {
    const dom = new JSDOM(SEITE.html,
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
    // Fertig-Signal: openModal() abfangen, sobald app.js es ablegt.
    let echt = null, gerufen = 0, fertigMelden;
    const fertig = new Promise((r) => { fertigMelden = r; });
    Object.defineProperty(w, '_openSettingsModal', {
        configurable: true,
        set(f) { echt = f; },
        get() {
            if (typeof echt !== 'function') return echt;
            return function () {
                gerufen++;
                const p = Promise.resolve(echt.apply(this, arguments));
                p.then(() => fertigMelden('ok'), (e) => fertigMelden('Fehler: ' + e));
                return p;
            };
        },
    });
    w.eval(SITZUNG);
    w.eval(ICONS);
    w.eval(I18N);
    w.eval(APPJS);
    let bremse;
    const ende = await Promise.race([fertig, new Promise((r) => {
        bremse = setTimeout(() => r('Notbremse'), NOTBREMSE_MS);
    })]);
    clearTimeout(bremse);
    if (ende !== 'ok' || gerufen !== 1) {
        // Ohne das Ende von openModal() ist kein Reiter deutbar: Messaufbau
        // defekt, nicht der Code (Exit 2, "konnte nicht laufen").
        console.log('  ABBRUCH: openModal() kam nicht sauber zu Ende (' + ende
                    + ', ' + gerufen + ' Aufruf(e)) - Messaufbau defekt');
        process.exit(2);
    }
    // Der Sprung in einen angeforderten Reiter haengt per .then() am Ende von
    // openModal; eine Makroaufgabe spaeter sind alle Mikroaufgaben gelaufen.
    await new Promise((r) => setTimeout(r, 0));
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
