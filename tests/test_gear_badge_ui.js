#!/usr/bin/env node
/**
 * Badge am Einstellungs-Zahnrad: offene Root-Freigaben + gesperrte Konten.
 *
 * VORGESCHICHTE (der Grund fuer diesen Waechter): es gab die Badge schon einmal
 * im alten Einzelseiten-Hauptfenster (`gear-broker-badge`, app.js). Sie fiel am
 * 2026-07-15 mit `bc41701` als "toter Code" - zu Recht, denn das Element war
 * beim Umzug des Zahnrads in die Bereichsseiten nicht mitgenommen worden.
 * Zurueck blieben ein Aufruf ins Leere (`window._setBrokerBadge` in
 * security_incidents.js) und zwei unbenutzte i18n-Schluessel; gemerkt hat es
 * fuenf Wochen niemand, weil das vorgeschaltete `if` den toten Haken
 * verschluckt hat. Genau das darf nicht wieder unbemerkt passieren.
 *
 * Teil 1  Struktur: EINE Fassung, kein zweiter Endpunkt, CSS am richtigen Ort
 * Teil 2  Verhalten im echten DOM (portal.html + settings_btn.js)
 * Teil 3  Die Rueckstaende von damals sind weg
 *
 *   node tests/test_gear_badge_ui.js
 */
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' - ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM, VirtualConsole;
try {
    const j = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');
    JSDOM = j.JSDOM; VirtualConsole = j.VirtualConsole;
} catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

// jsdom kann nicht navigieren und schreibt bei `location.href = '/settings'`
// einen mehrzeiligen jsdomError. Der ist hier ERWARTET (der Knopf tut genau
// das) und wuerde die Ausgabe unlesbar machen. Nur DIESE Meldung schweigt.
function stilleKonsole() {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (err) => {
        if (!/Not implemented: navigation/.test(String(err && err.message))) {
            console.log('  ! jsdomError: ' + err.message);
        }
    });
    return vc;
}

const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const SBTN     = lies('frontend/js/settings_btn.js');
const THEMECSS = lies('frontend/css/theme.css');
const STYLECSS = lies('frontend/css/style.css');
const I18N     = lies('frontend/js/i18n.js');
const APPJS    = lies('frontend/js/app.js');
const SECINC   = lies('frontend/js/security_incidents.js');

// Kommentare entfernen. Ein Waechter, der seine eigene Begruendung liest,
// prueft nichts - im Projekt schon mehrfach passiert (Prompt-Waechter
// 2026-08-10, Ordner-Marke 2026-08-11, Antwort-Vorschau 2026-08-17).
const nurCode = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const SBTN_CODE   = nurCode(SBTN);
const SECINC_CODE = nurCode(SECINC);
const APPJS_CODE  = nurCode(APPJS);

// Alle Seiten mit Zahnrad - aus dem Markup ERMITTELT, nicht gepflegt: eine
// Liste im Test waere beim naechsten Bereich wieder unvollstaendig.
const SEITEN = fs.readdirSync(path.join(ROOT, 'frontend'))
    .filter((f) => f.endsWith('.html'))
    .filter((f) => /data-jarvis-settings/.test(lies('frontend/' + f)));

/* ===================================================================== */
abschnitt('1. Struktur');
{
    pruefe(SEITEN.length >= 11, 'mindestens elf Seiten tragen ein Zahnrad',
           SEITEN.length + ': ' + SEITEN.join(', '));

    // Die Badge lebt in settings_btn.js - dort, wo auch der Knopf entsteht.
    pruefe(/jv-gear-badge/.test(SBTN_CODE),
           'settings_btn.js malt die Badge selbst');
    // ... und NUR dort. Eine seiteneigene Fassung ist der Weg zurueck in elf
    // Kopien, von denen die zwoelfte Seite eine vergisst.
    const eigene = SEITEN.filter((f) => /jv-gear-badge|gear-broker-badge/
        .test(nurCode(lies('frontend/' + f))));
    pruefe(eigene.length === 0, 'keine Seite baut die Badge selbst', eigene.join(', '));

    // Kein zweiter Endpunkt: die Zahlen kommen aus /api/me, das der Knopf
    // ohnehin abruft. /api/broker/status hier waere ein Roundtrip je Seite.
    pruefe(/admin_badge/.test(SBTN_CODE),
           'die Zahlen kommen aus dem Feld admin_badge');
    const fremde = (SBTN_CODE.match(/fetch\('([^']+)'/g) || [])
        .map((m) => m.replace(/fetch\('|'/g, ''))
        .filter((u) => u !== '/api/me');
    pruefe(fremde.length === 0, 'settings_btn.js ruft ausschliesslich /api/me',
           fremde.join(', '));

    // CSS gehoert in theme.css: das Zahnrad sitzt auf elf Seiten, style.css
    // laden nur /settings und /wissen (Lehre von `select option`, 2026-07-29).
    pruefe(/^\.jv-gear-badge \{/m.test(THEMECSS),
           '.jv-gear-badge steht in theme.css');
    pruefe(!/jv-gear-badge/.test(STYLECSS),
           '.jv-gear-badge steht NICHT in style.css');
    pruefe(/^\.jv-gear-host \{/m.test(THEMECSS),
           '.jv-gear-host (Positionsbezug) steht in theme.css');

    // Keine harten Farben im Badge-Block - Projektregel: nur CSS-Variablen.
    const block = (THEMECSS.match(/\.jv-gear-badge[\s\S]*?is-danger[^\n]*\n/) || [''])[0];
    pruefe(block.length > 0, 'Badge-Block in theme.css gefunden (Gegenprobe)');
    const harte = block.replace(/\/\*[\s\S]*?\*\//g, '').match(/#[0-9a-fA-F]{3,8}\b|\brgb\(/g);
    pruefe(!harte, 'Badge-Block ohne harte Farbwerte', harte && harte.join(', '));

    // i18n in BEIDEN Sprachen.
    for (const k of ['security.gear_badge_title', 'security.gear_badge_blocked']) {
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length;
        pruefe(n === 2, k + ' steht in DE und EN', 'gefunden: ' + n);
    }
    // Der Tooltip steht nicht im Markup - applyLang() erreicht ihn nicht.
    pruefe(/jarvis-lang-changed/.test(SBTN_CODE),
           'Sprachwechsel malt die Badge neu');
    // ... und loest dabei KEINEN neuen Abruf aus.
    const langZeile = (SBTN_CODE.match(/jarvis-lang-changed[^\n]*/) || [''])[0];
    pruefe(!/fetch|pruefe|aktualisiere/.test(langZeile),
           'der Sprachwechsel ruft nichts ab, er malt nur', langZeile.trim());

    // Der Takt haengt am belegten Admin-Status, nicht am Seitenaufbau.
    pruefe(/if \(an\) starteTakt\(\)/.test(SBTN_CODE),
           'der Takt startet nur fuer Administratoren');
}

/* ===================================================================== */
abschnitt('2. Verhalten im echten DOM');

function starte(seite, me) {
    const dom = new JSDOM(lies('frontend/' + seite),
                          { url: 'https://x/', runScripts: 'outside-only',
                            virtualConsole: stilleKonsole() });
    const w = dom.window;
    const rufe = [];
    w.localStorage.setItem('jarvis_token', 'tok-1');
    w.fetch = (url, opt) => {
        rufe.push(url);
        return Promise.resolve({ ok: true, status: 200,
                                 json: () => Promise.resolve(me) });
    };
    w.t = (k) => ({ 'security.gear_badge_title': 'Offene Root-Freigaben',
                    'security.gear_badge_blocked': 'Gesperrte Konten' })[k] || '';
    w.eval(SBTN);
    return { w, d: w.document, rufe };
}
const gleich = () => new Promise((r) => setImmediate(r));
const badge = (d) => d.querySelector('[data-jarvis-settings] .jv-gear-badge');

(async () => {
    {   // zwei offene Freigaben
        const { d, rufe } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 2, gesperrt: 0, gesamt: 2 } });
        await gleich(); await gleich();
        const b = badge(d);
        pruefe(!!b, 'Badge vorhanden');
        pruefe(b && b.textContent === '2', 'zeigt die Anzahl', b && b.textContent);
        pruefe(b && /Offene Root-Freigaben: 2/.test(b.title),
               'Tooltip nennt die offenen Freigaben', b && b.title);
        pruefe(b && !/Gesperrte/.test(b.title),
               'Tooltip nennt NICHT, was es nicht gibt', b && b.title);
        pruefe(b && !b.classList.contains('is-danger'),
               'ohne Sperre bleibt es die Warnfarbe');
        pruefe(b && b.parentNode.classList.contains('jv-gear-host'),
               'der Knopf bekommt den Positionsbezug');
        pruefe(rufe.length === 1 && rufe[0] === '/api/me',
               'genau EIN Abruf, und zwar /api/me', JSON.stringify(rufe));
    }
    {   // Sperre schlaegt die Freigabe (dringlicher)
        const { d } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 1, gesperrt: 2, gesamt: 3 } });
        await gleich(); await gleich();
        const b = badge(d);
        pruefe(b && b.textContent === '3', 'zaehlt beide Quellen zusammen',
               b && b.textContent);
        pruefe(b && b.classList.contains('is-danger'),
               'eine Sperre setzt die Gefahrenfarbe');
        pruefe(b && /Offene Root-Freigaben: 1/.test(b.title) &&
                    /Gesperrte Konten: 2/.test(b.title),
               'Tooltip nennt beide Quellen', b && b.title);
    }
    {   // nichts zu tun = keine Badge
        const { d } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 0, gesperrt: 0, gesamt: 0 } });
        await gleich(); await gleich();
        pruefe(!badge(d), 'keine Badge, wenn nichts offen ist');
        const btn = d.querySelector('[data-jarvis-settings]');
        pruefe(btn && !btn.classList.contains('jv-gear-host'),
               'und auch kein Positionsbezug am Knopf');
    }
    {   // Feld fehlt (aelteres Backend) - nichts behaupten
        const { d } = starte('portal.html', { is_admin: true });
        await gleich(); await gleich();
        pruefe(!badge(d), 'ohne admin_badge im Antwort-Objekt keine Badge');
    }
    {   // Nicht-Admin: kein Knopf, keine Badge
        const { d } = starte('portal.html',
            { is_admin: false, admin_badge: { root_pending: 9, gesperrt: 9, gesamt: 18 } });
        await gleich(); await gleich();
        pruefe(!badge(d), 'ein Nicht-Admin sieht die Badge nicht');
        const btn = d.querySelector('[data-jarvis-settings]');
        pruefe(btn && btn.style.display === 'none', 'und auch das Zahnrad nicht');
    }
    {   // Deckel
        const { d } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 150, gesperrt: 0, gesamt: 150 } });
        await gleich(); await gleich();
        const b = badge(d);
        pruefe(b && b.textContent === '99+', 'dreistellig wird gedeckelt',
               b && b.textContent);
    }
    {   // Klick: Rueckweg UND Sicherheits-Reiter
        const { w, d } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 1, gesperrt: 0, gesamt: 1 } });
        await gleich(); await gleich();
        const b = badge(d);
        if (b) b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        pruefe(w.sessionStorage.getItem('jarvis_settings_tab') === 'security',
               'ein Klick auf die Badge fuehrt in den Sicherheits-Reiter',
               w.sessionStorage.getItem('jarvis_settings_tab'));
        pruefe(w.sessionStorage.getItem('jarvis_settings_return') === '/portal',
               'und der Klick erreicht weiterhin den Knopf (Rueckweg gesetzt)',
               w.sessionStorage.getItem('jarvis_settings_return'));
    }
    {   // Klick auf das Zahnrad SELBST setzt keinen Reiter
        const { w, d } = starte('portal.html',
            { is_admin: true, admin_badge: { root_pending: 1, gesperrt: 0, gesamt: 1 } });
        await gleich(); await gleich();
        const btn = d.querySelector('[data-jarvis-settings]');
        btn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        pruefe(!w.sessionStorage.getItem('jarvis_settings_tab'),
               'ein Klick neben die Badge oeffnet den Vorgabe-Reiter');
    }
    {   // Aktualisierung: erledigte Freigabe laesst die Badge verschwinden
        const dom = new JSDOM(lies('frontend/portal.html'),
                              { url: 'https://x/', runScripts: 'outside-only',
                                virtualConsole: stilleKonsole() });
        const w = dom.window;
        w.localStorage.setItem('jarvis_token', 'tok-1');
        let stand = { is_admin: true, admin_badge: { root_pending: 2, gesperrt: 0, gesamt: 2 } };
        w.fetch = () => Promise.resolve({ ok: true, status: 200,
                                          json: () => Promise.resolve(stand) });
        w.t = () => '';
        w.eval(SBTN);
        await gleich(); await gleich();
        pruefe(!!badge(w.document), 'Ausgangslage: Badge steht (Gegenprobe)');
        stand = { is_admin: true, admin_badge: { root_pending: 0, gesperrt: 0, gesamt: 0 } };
        await w.JarvisSettingsBtn.aktualisiere();
        await gleich();
        pruefe(!badge(w.document), 'nach dem Entscheiden verschwindet sie');
        w.close();
    }
    {   // 401 im Takt: alter Stand bleibt stehen statt auf 0 zu fallen
        const dom = new JSDOM(lies('frontend/portal.html'),
                              { url: 'https://x/', runScripts: 'outside-only',
                                virtualConsole: stilleKonsole() });
        const w = dom.window;
        w.localStorage.setItem('jarvis_token', 'tok-1');
        let antwort = { ok: true, status: 200, json: () => Promise.resolve(
            { is_admin: true, admin_badge: { root_pending: 2, gesperrt: 0, gesamt: 2 } }) };
        w.fetch = () => Promise.resolve(antwort);
        w.t = () => '';
        w.eval(SBTN);
        await gleich(); await gleich();
        antwort = { ok: false, status: 401, json: () => Promise.resolve({}) };
        await w.JarvisSettingsBtn.aktualisiere();
        await gleich();
        const b = badge(w.document);
        pruefe(b && b.textContent === '2',
               'ein 401 im Takt behauptet nicht "nichts offen"', b && b.textContent);
        w.close();
    }

    /* ================================================================= */
    abschnitt('3. Die Rueckstaende von 2026-07-15 sind weg');
    {
        pruefe(!/_setBrokerBadge/.test(SECINC_CODE),
               'security_incidents.js ruft keinen toten Haken mehr');
        pruefe(!/_setBrokerBadge|gear-broker-badge/.test(APPJS_CODE),
               'app.js hat keine zweite Badge-Fassung');
        // /settings selbst hat kein Zahnrad - dort waere eine Badge sinnlos.
        pruefe(!/data-jarvis-settings/.test(lies('frontend/settings.html')),
               'settings.html traegt kein Zahnrad (Begruendung fuer Teil 3)');
        // Der Sprung in den Reiter wird in app.js ausgewertet, und zwar EINMALIG.
        pruefe(/jarvis_settings_tab/.test(APPJS_CODE),
               'app.js wertet jarvis_settings_tab aus');
        pruefe(/removeItem\('jarvis_settings_tab'\)/.test(APPJS_CODE),
               'und verbraucht den Wert (kein Dauer-Reiter)');
    }

    /* ================================================================= */
    abschnitt('4. Der Reiter-Sprung, LESENDE Seite (settings.html + app.js)');
    {
        // Diese Haelfte laesst sich nicht per Quelltext pruefen: `openModal()`
        // ist async und aktiviert an ihrem ENDE den ersten Reiter. Ein Klick
        // davor wird ueberschrieben - gemessen: Sicherheits-Panel sichtbar,
        // waehrend "KI & System" als ausgewaehlt aussah und dessen Panel
        // ebenfalls stehen blieb (der Reset raeumt Panels nicht ab).
        const dom = new JSDOM(lies('frontend/settings.html'),
            { url: 'https://x/settings', runScripts: 'outside-only',
              virtualConsole: stilleKonsole() });
        const w = dom.window;
        w.localStorage.setItem('jarvis_token', 't:1:x');
        w.sessionStorage.setItem('jarvis_settings_tab', 'security');
        w.fetch = () => Promise.resolve({ ok: true, status: 200,
            json: () => Promise.resolve({ valid: true, success: true,
                username: 'jarvis', is_admin: true, permissions: {},
                license_banner: '',
                admin_badge: { root_pending: 1, gesperrt: 0, gesamt: 1 } }) });
        // jsdom bringt beides nicht mit; `pretendToBeVisual` scheidet aus, es
        // startet einen Dauerlauf und haelt den Prozess offen.
        w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {},
            removeListener() {}, addEventListener() {}, removeEventListener() {} }));
        w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
        w.WebSocket = function () { this.close = () => {}; this.send = () => {}; };
        w.eval(lies('frontend/js/i18n.js'));
        w.eval(lies('frontend/js/app.js'));
        await new Promise((r) => setTimeout(r, 900));
        const knopf = [...w.document.querySelectorAll('.settings-tab-btn.active')]
            .map((b) => b.dataset.settingsTab);
        const panel = [...w.document.querySelectorAll('[id^=settings-tab-].active')]
            .map((b) => b.id);
        pruefe(knopf.length === 1 && knopf[0] === 'security',
               'GENAU der Sicherheits-Knopf ist ausgewaehlt', JSON.stringify(knopf));
        pruefe(panel.length === 1 && panel[0] === 'settings-tab-security',
               'und GENAU sein Panel steht offen', JSON.stringify(panel));
        pruefe(w.sessionStorage.getItem('jarvis_settings_tab') === null,
               'der Wert ist verbraucht');
        w.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
