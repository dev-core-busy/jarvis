#!/usr/bin/env node
/**
 * Waechter: Einstellungen -> Sicherheit -> 2FA des EIGENEN Kontos merkt erst auf
 * Knopfdruck ein neues Secret vor, nicht schon beim Oeffnen des Reiters.
 *
 * DER BEFUND (2026-09-29, umgesetzt 2026-10-14): bei ausgeschalteter 2FA rief
 * settings_totp.js beim blossen Oeffnen des Sicherheits-Reiters
 * POST /api/auth/totp/setup. Jeder Aufruf schreibt ein neues
 * totp_pending_secret nach auth_state.json (bei AD-Konten zusaetzlich einen
 * neuen Eintrag) - also eine Schreibaktion je Reiterwechsel, ohne dass der
 * Benutzer etwas einrichten wollte.
 *
 *  A  EINBINDUNG: Knopf #btn-totp-settings-start mit data-i18n im Markup,
 *     settings_totp.js eingebunden, neue Texte in DE und EN.
 *  B  VERHALTEN (jsdom, echte settings.html + i18n.js + sitzung.js, fetch-
 *     Attrappe nach PFAD geroutet):
 *     - Positivkontrolle: das Oeffnen ruft /totp/status (sonst ist „kein setup"
 *       trivial wahr)
 *     - 2FA aus: Oeffnen ruft /totp/setup NICHT, Knopf sichtbar, QR verborgen
 *     - Klick: genau EIN /totp/setup, QR + Schluessel sichtbar, Knopf weg
 *     - erneutes Oeffnen: wieder kein /totp/setup
 *     - Fehlerantwort: Meldung steht, QR bleibt verborgen
 *     - 2FA an: kein Knopf, Abschalten sichtbar
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SETTINGS = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const MODUL = fs.readFileSync(path.join(REPO, 'frontend/js/settings_totp.js'), 'utf8');
const I18N = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');

// ── A: Einbindung ───────────────────────────────────────────────────────────
console.log('A  Einbindung');
check('settings.html hat #btn-totp-settings-start mit data-i18n',
      /<button[^>]*id="btn-totp-settings-start"[^>]*data-i18n="security\.totp_setup_btn"/.test(SETTINGS));
check('settings.html laedt settings_totp.js',
      /<script src="\/static\/js\/settings_totp\.js\?v=\d+"><\/script>/.test(SETTINGS));
for (const k of ['security.totp_setup_btn', 'security.totp_scan_hint']) {
    const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
    check('i18n-Schluessel ' + k + ' in DE und EN', n === 2, n + ' Vorkommen');
}

// ── B: Verhalten ────────────────────────────────────────────────────────────
function aufbauen(zustand) {
    const dom = new JSDOM(SETTINGS, { runScripts: 'outside-only', url: 'https://jarvis.beispiel.de/settings' });
    const w = dom.window;
    sitzungLaden(w, { token: 'testtoken' });
    w.eval(I18N);
    const aufrufe = [];
    const antwort = (obj, status) => Promise.resolve({
        ok: (status || 200) < 400, status: status || 200,
        json: () => Promise.resolve(obj), text: () => Promise.resolve(JSON.stringify(obj)),
    });
    w.fetch = (url, opt) => {
        const p = String(url).split('?')[0];
        aufrufe.push(p);
        if (p === '/api/auth/totp/status') return antwort({ enabled: zustand.enabled });
        if (p === '/api/auth/totp/setup') {
            if (zustand.setupFehler) return antwort({ success: false, error: 'Gesperrt' }, 403);
            return antwort({ secret: 'ABCDEF234567', qr_code: 'data:image/png;base64,AAAA', uri: 'otpauth://x' });
        }
        return antwort({});
    };
    w.eval(MODUL);
    return { dom, w, aufrufe, $: (id) => w.document.getElementById(id) };
}
const anzahl = (a, p) => a.filter((x) => x === p).length;
const sichtbar = (el) => !!el && el.style.display !== 'none';

(async () => {
    console.log('B  Verhalten');
    // 2FA aus
    let s = aufbauen({ enabled: false });
    const reiter = s.w.document.querySelector('[data-settings-tab="security"]');
    if (!reiter) { console.log('ABBRUCH (Exit 2): Sicherheits-Reiter nicht im Markup'); bilanz = true; process.exit(2); }
    reiter.click();
    await sleep(50);
    if (anzahl(s.aufrufe, '/api/auth/totp/status') !== 1) {
        console.log('ABBRUCH (Exit 2): Positivkontrolle – Oeffnen ruft /totp/status nicht (' + s.aufrufe.join(',') + ')');
        bilanz = true; process.exit(2);
    }
    check('(Positivkontrolle) Oeffnen ruft /totp/status', true);
    check('2FA aus: Oeffnen ruft /totp/setup NICHT', anzahl(s.aufrufe, '/api/auth/totp/setup') === 0, s.aufrufe.join(','));
    check('2FA aus: Knopf „Einrichten" sichtbar', sichtbar(s.$('btn-totp-settings-start')));
    check('2FA aus: QR-Bereich verborgen', !sichtbar(s.$('totp-settings-setup')));
    check('2FA aus: kein QR-Bild im DOM', !s.$('totp-settings-qr').querySelector('img'));

    s.$('btn-totp-settings-start').click();
    await sleep(50);
    check('Klick: genau EIN /totp/setup', anzahl(s.aufrufe, '/api/auth/totp/setup') === 1, s.aufrufe.join(','));
    check('Klick: QR-Bereich sichtbar', sichtbar(s.$('totp-settings-setup')));
    const img = s.$('totp-settings-qr').querySelector('img');
    check('Klick: QR-Bild gesetzt', !!img && img.getAttribute('src') === 'data:image/png;base64,AAAA');
    check('Klick: Schluessel angezeigt', s.$('totp-settings-secret').textContent === 'ABCDEF234567');
    check('Klick: Knopf „Einrichten" verborgen', !sichtbar(s.$('btn-totp-settings-start')));

    reiter.click();
    await sleep(50);
    check('erneutes Oeffnen: kein weiteres /totp/setup', anzahl(s.aufrufe, '/api/auth/totp/setup') === 1, s.aufrufe.join(','));
    check('erneutes Oeffnen: QR wieder verborgen, Knopf wieder da',
          !sichtbar(s.$('totp-settings-setup')) && sichtbar(s.$('btn-totp-settings-start')));
    s.w.close();

    // Fehlerantwort
    s = aufbauen({ enabled: false, setupFehler: true });
    s.w.document.querySelector('[data-settings-tab="security"]').click();
    await sleep(50);
    s.$('btn-totp-settings-start').click();
    await sleep(50);
    check('Fehler: Meldung steht', s.$('totp-settings-error').textContent === 'Gesperrt', s.$('totp-settings-error').textContent);
    check('Fehler: QR-Bereich bleibt verborgen', !sichtbar(s.$('totp-settings-setup')));
    check('Fehler: Knopf wieder bedienbar', !s.$('btn-totp-settings-start').disabled);
    s.w.close();

    // 2FA an
    s = aufbauen({ enabled: true });
    s.w.document.querySelector('[data-settings-tab="security"]').click();
    await sleep(50);
    check('2FA an: kein /totp/setup', anzahl(s.aufrufe, '/api/auth/totp/setup') === 0);
    check('2FA an: Knopf „Einrichten" verborgen', !sichtbar(s.$('btn-totp-settings-start')));
    check('2FA an: Abschalten sichtbar', sichtbar(s.$('totp-settings-disable')));
    s.w.close();

    bilanz = true;
    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
