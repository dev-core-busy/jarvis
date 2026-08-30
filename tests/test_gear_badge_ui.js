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
        const bl = b && b.getAttribute('aria-label');
        pruefe(/Offene Root-Freigaben: 2/.test(bl || ''),
               'die Beschriftung nennt die offenen Freigaben', bl);
        pruefe(!/Gesperrte/.test(bl || ''),
               'sie nennt NICHT, was es nicht gibt', bl);
        // ⚠ LEERER title ist Absicht: der Knopf darunter traegt einen (aus
        // data-i18n-title). Ohne das leere Attribut sucht der Browser beim
        // Hovern der Badge beim Vorfahren weiter und zeigt SEINEN nativen
        // Tooltip ZUSAETZLICH zum Panel - zwei Kaesten uebereinander.
        pruefe(b && b.getAttribute('title') === '',
               'die Badge traegt einen LEEREN title (kein Doppel-Tooltip)',
               b && JSON.stringify(b.getAttribute('title')));
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
        const bl = (b && b.getAttribute('aria-label')) || '';
        pruefe(/Offene Root-Freigaben: 1/.test(bl) && /Gesperrte Konten: 2/.test(bl),
               'die Beschriftung nennt beide Quellen', bl);
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
    abschnitt('2b. Mouseover am Badge: die Liste hinter der Zahl');
    // WARUM: die Zahl sagt "3" und sonst nichts. Wer wissen wollte, WAS zu tun
    // ist, musste erst /settings oeffnen und zwei getrennte Abschnitte
    // durchsehen. Gebaut nach dem Vorbild des Issues-Badges (2026-08-25).
    const POSTEN = {
        is_admin: true,
        admin_badge: {
            root_pending: 1, gesperrt: 1, gesamt: 2,
            items: [
                { art: 'blocked', titel: 'nexus\\rene.pfeiffer',
                  sub: 'policy:shell-write', ts: 1756000000 },
                { art: 'root', titel: 'apt-get install libreoffice',
                  sub: 'nexus\\anna.klein', ts: 1756000100 },
            ],
        },
    };
    const tip = (d) => d.querySelector('.jv-gear-tip');
    const hover = (w, d) => {
        const b = badge(d);
        b.dispatchEvent(new w.MouseEvent('mouseenter', { bubbles: false }));
        return tip(d);
    };
    {
        const { w, d } = starte('portal.html', POSTEN);
        await gleich(); await gleich();
        pruefe(!tip(d), 'ohne Hover gibt es kein Panel');
        const el = hover(w, d);
        pruefe(!!el, 'Hover ueber der Badge oeffnet das Panel');
        // Es haengt an body und ist fixed - in der Titelleiste eingehaengt
        // bliebe es an deren overflow/Stapelkontext haengen (Register).
        pruefe(el && el.parentNode === d.body,
               'das Panel ist direktes Kind von body');
        pruefe(el && el.style.display === 'block', 'und ist sichtbar');
        const zeilen = el ? el.querySelectorAll('.jv-gear-tip-row') : [];
        pruefe(zeilen.length === 2, 'eine Zeile je Eintrag', String(zeilen.length));
        pruefe(el && /nexus\\rene\.pfeiffer/.test(el.textContent) &&
                     /apt-get install libreoffice/.test(el.textContent),
               'die Zeilen nennen Konto bzw. Befehl');
        pruefe(el && /policy:shell-write/.test(el.textContent),
               'die Sperre nennt ihren Grund');
        pruefe(el && /nexus\\anna\.klein/.test(el.textContent),
               'die Freigabe nennt den Anforderer');
        // Die Zuordnung Zeile -> Abschnitt ist der Gewinn gegenueber dem alten
        // `title`: eine Warnung ohne Weg zur Abhilfe ist nur Laerm.
        const fokus = Array.prototype.map.call(zeilen,
            (b) => b.getAttribute('data-fokus'));
        pruefe(JSON.stringify(fokus) === '["incidents","broker"]',
               'jede Zeile kennt den Abschnitt, der sie erledigt',
               JSON.stringify(fokus));
        pruefe(el && !/und \d+ weitere/.test(el.textContent),
               'ohne Kuerzung steht keine Restzahl da');
        w.close();
    }
    {   // Klick auf eine Zeile: Reiter UND Abschnitt UND Rueckweg
        const { w, d } = starte('portal.html', POSTEN);
        await gleich(); await gleich();
        const el = hover(w, d);
        el.querySelectorAll('.jv-gear-tip-row')[1]
            .dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        pruefe(w.sessionStorage.getItem('jarvis_settings_tab') === 'security',
               'die Zeile fuehrt in den Sicherheits-Reiter');
        pruefe(w.sessionStorage.getItem('jarvis_settings_focus') === 'broker',
               'und in GENAU den Abschnitt der Zeile',
               w.sessionStorage.getItem('jarvis_settings_focus'));
        // Die Zeilen haengen an body und koennen den Klick nicht an den Knopf
        // weiterreichen - der Rueckweg muss deshalb selbst gesetzt werden.
        pruefe(w.sessionStorage.getItem('jarvis_settings_return') === '/portal',
               'der Rueckweg wird trotzdem gesetzt',
               w.sessionStorage.getItem('jarvis_settings_return'));
        w.close();
    }
    {   // Klick auf die Badge selbst setzt KEINEN Abschnitt (nur den Reiter)
        const { w, d } = starte('portal.html', POSTEN);
        await gleich(); await gleich();
        badge(d).dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        pruefe(!w.sessionStorage.getItem('jarvis_settings_focus'),
               'ein Klick auf die Zahl selbst springt in keinen Abschnitt');
        w.close();
    }
    {   // Fremdtext wird maskiert: Befehl und Sperrgrund stammen aus fremden
        // Quellen und landen in einer ADMINISTRATOREN-Oberflaeche, in der das
        // Sitzungstoken im localStorage liegt (Lehre aus mcp.js, 2026-08-14).
        const { w, d } = starte('portal.html', { is_admin: true, admin_badge: {
            root_pending: 1, gesperrt: 0, gesamt: 1,
            items: [{ art: 'root', titel: '<img src=x onerror=alert(1)>',
                      sub: '<b>chef</b>', ts: 0 }] } });
        await gleich(); await gleich();
        const el = hover(w, d);
        pruefe(el && !el.querySelector('img') && !el.querySelector('b'),
               'kein Markup aus Fremdtext im DOM');
        pruefe(el && /<img src=x onerror=alert\(1\)>/.test(el.textContent),
               'der Text steht trotzdem lesbar da');
        w.close();
    }
    {   // Deckel: `gesamt` ist groesser als die uebertragene Liste.
        const items = [];
        for (let i = 0; i < 12; i++) {
            items.push({ art: 'root', titel: 'op ' + i, sub: '', ts: 0 });
        }
        const { w, d } = starte('portal.html', { is_admin: true, admin_badge: {
            root_pending: 30, gesperrt: 0, gesamt: 30, items: items } });
        await gleich(); await gleich();
        const el = hover(w, d);
        pruefe(el && /und 18 weitere/.test(el.textContent),
               'die Restzahl steht da (sonst gilt die Liste als vollstaendig)',
               el && el.textContent.slice(-120));
        w.close();
    }
    {   // Aelteres Backend ohne `items`: KEINE leere Flaeche - eine leere Liste
        // waere die Behauptung, es gaebe nichts (Register).
        const { w, d } = starte('portal.html', { is_admin: true,
            admin_badge: { root_pending: 2, gesperrt: 1, gesamt: 3 } });
        await gleich(); await gleich();
        const el = hover(w, d);
        pruefe(el && /Offene Root-Freigaben: 2/.test(el.textContent) &&
                     /Gesperrte Konten: 1/.test(el.textContent),
               'ohne items faellt das Panel auf die Quellen zurueck',
               el && el.textContent);
        w.close();
    }
    {   // Der Zeiger muss vom Badge INS Panel wandern koennen: sonst waere
        // keine Zeile je anklickbar. Deshalb schliesst es verzoegert, und ein
        // mouseenter AM PANEL haelt es offen.
        const { w, d } = starte('portal.html', POSTEN);
        await gleich(); await gleich();
        const el = hover(w, d);
        badge(d).dispatchEvent(new w.MouseEvent('mouseleave', { bubbles: false }));
        pruefe(el.style.display === 'block',
               'ein mouseleave schliesst nicht sofort');
        el.dispatchEvent(new w.MouseEvent('mouseenter', { bubbles: false }));
        await new Promise((r) => setTimeout(r, 320));
        pruefe(el.style.display === 'block',
               'der Zeiger im Panel haelt es offen');
        el.dispatchEvent(new w.MouseEvent('mouseleave', { bubbles: false }));
        await new Promise((r) => setTimeout(r, 320));
        pruefe(el.style.display === 'none', 'danach schliesst es');
        w.close();
    }
    {   // Takt: wird die letzte Freigabe entschieden, verschwindet mit der
        // Badge auch das offene Panel - sonst zeigt es eine Liste, die es nicht
        // mehr gibt.
        const dom = new JSDOM(lies('frontend/portal.html'),
                              { url: 'https://x/', runScripts: 'outside-only',
                                virtualConsole: stilleKonsole() });
        const w = dom.window;
        w.localStorage.setItem('jarvis_token', 'tok-1');
        let stand = POSTEN;
        w.fetch = () => Promise.resolve({ ok: true, status: 200,
                                          json: () => Promise.resolve(stand) });
        w.t = () => '';
        w.eval(SBTN);
        await gleich(); await gleich();
        const el = hover(w, w.document);
        pruefe(el && el.style.display === 'block',
               'Ausgangslage: Panel offen (Gegenprobe)');
        stand = { is_admin: true,
                  admin_badge: { root_pending: 0, gesperrt: 0, gesamt: 0, items: [] } };
        await w.JarvisSettingsBtn.aktualisiere();
        await gleich();
        pruefe(el.style.display === 'none',
               'nach dem Entscheiden schliesst das Panel mit');
        w.close();
    }
    {   // CSS am richtigen Ort - dieselbe Begruendung wie bei der Badge:
        // theme.css liegt auf allen Seiten mit Zahnrad, style.css nur auf zwei.
        pruefe(/^\.jv-gear-tip \{/m.test(THEMECSS),
               '.jv-gear-tip steht in theme.css');
        pruefe(!/jv-gear-tip/.test(STYLECSS),
               '.jv-gear-tip steht NICHT in style.css');
        // Ein Flex-Kind schrumpft von sich aus nicht unter seine Inhaltsbreite:
        // ohne `min-width: 0` schiebt ein langer Root-Befehl die Pille aus dem
        // Panel, statt dass die Ellipse greift (Register, 2026-08-30).
        const t = (THEMECSS.match(/\.jv-gear-tip-t \{[^}]*\}/) || [''])[0];
        pruefe(/min-width:\s*0/.test(t), '.jv-gear-tip-t traegt min-width: 0', t);
        pruefe(/text-overflow:\s*ellipsis/.test(t),
               'und kuerzt mit Ellipse statt zu ueberlaufen');
        // Das Issues-Panel liegt bei 99990; das Zahnrad-Panel darf nicht
        // darueber und unter kein Modal.
        const box = (THEMECSS.match(/\.jv-gear-tip \{[^}]*\}/) || [''])[0];
        const z = (box.match(/z-index:\s*(\d+)/) || [])[1];
        pruefe(z && Number(z) < 99990, 'z-index unter dem Issues-Panel', z);
        pruefe(/background:\s*var\(--bg-secondary\)/.test(box),
               'DECKENDE Flaeche (darunter liegt Seiteninhalt)');
    }
    {   // i18n in BEIDEN Sprachen - der Panel-Text steht nicht im Markup.
        for (const k of ['security.gear_tip_title', 'security.gear_tip_root',
                         'security.gear_tip_blocked', 'security.gear_tip_by',
                         'security.gear_tip_more', 'security.gear_tip_hint']) {
            const n = (I18N.match(new RegExp("'" + k.replace(/\./g, '\\.') + "'", 'g')) || []).length;
            pruefe(n === 2, k + ' steht in DE und EN', 'gefunden: ' + n);
        }
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

    /* ================================================================= */
    abschnitt('5. Der Abschnitts-Sprung (jarvis_settings_focus)');
    // Auch das laesst sich nicht per Quelltext pruefen: der Abschnitt haengt am
    // Klapp-Handler, den `_initSecCollapse()` erst beim Aktivieren des Reiters
    // bindet - und "Sicherheitsvorfaelle" startet ZU, "Root-Freigaben" AUF.
    // Ein blindes click() wuerde den offenen zuklappen.
    async function settingsMit(fokus) {
        const dom = new JSDOM(lies('frontend/settings.html'),
            { url: 'https://x/settings', runScripts: 'outside-only',
              virtualConsole: stilleKonsole() });
        const w = dom.window;
        w.localStorage.setItem('jarvis_token', 't:1:x');
        // Der gemerkte Klapp-Zustand darf das Ergebnis nicht faelschen.
        w.localStorage.removeItem('jarvis_sect_collapse_sec-sect-incidents-hdr');
        w.localStorage.removeItem('jarvis_sect_collapse_sec-sect-broker-hdr');
        w.sessionStorage.setItem('jarvis_settings_tab', 'security');
        if (fokus !== null) w.sessionStorage.setItem('jarvis_settings_focus', fokus);
        w.fetch = () => Promise.resolve({ ok: true, status: 200,
            json: () => Promise.resolve({ valid: true, success: true,
                username: 'jarvis', is_admin: true, permissions: {},
                license_banner: '',
                admin_badge: { root_pending: 1, gesperrt: 1, gesamt: 2 } }) });
        w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {},
            removeListener() {}, addEventListener() {}, removeEventListener() {} }));
        w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
        w.WebSocket = function () { this.close = () => {}; this.send = () => {}; };
        w.eval(lies('frontend/js/i18n.js'));
        w.eval(lies('frontend/js/app.js'));
        await new Promise((r) => setTimeout(r, 900));
        const sicht = (id) => {
            const el = w.document.getElementById(id);
            return el ? el.style.display !== 'none' : null;
        };
        return { w, sicht };
    }
    {   // Der zugeklappte Abschnitt geht auf.
        const { w, sicht } = await settingsMit('incidents');
        pruefe(sicht('sec-sect-incidents-body') === true,
               '"incidents" klappt den zugeklappten Abschnitt auf');
        pruefe(w.sessionStorage.getItem('jarvis_settings_focus') === null,
               'und der Wert ist verbraucht (kein Dauer-Sprung)');
        w.close();
    }
    {   // Der offene Abschnitt bleibt offen - ein blindes click() haette ihn
        // ZUgeklappt, also genau das Gegenteil bewirkt.
        const { sicht, w } = await settingsMit('broker');
        pruefe(sicht('sec-sect-broker-body') === true,
               '"broker" laesst den bereits offenen Abschnitt offen');
        pruefe(sicht('sec-sect-incidents-body') === false,
               'und fasst den fremden Abschnitt nicht an');
        w.close();
    }
    {   // Ohne Fokus bleibt alles, wie es war (Gegenprobe zu beiden oben).
        const { sicht, w } = await settingsMit(null);
        pruefe(sicht('sec-sect-incidents-body') === false,
               'ohne Fokus bleibt der Abschnitt zu');
        w.close();
    }
    {   // Ein unbekannter Wert wird VERWORFEN, nicht geraten.
        const { sicht, w } = await settingsMit('gibtsnicht');
        pruefe(sicht('sec-sect-incidents-body') === false &&
               sicht('sec-sect-broker-body') === true,
               'ein unbekannter Fokus aendert gar nichts');
        w.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
