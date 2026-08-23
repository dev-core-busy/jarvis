#!/usr/bin/env node
/**
 * Titelsymbole der Bereichsseiten: CPU-Anzeige + Avatar-Schalter.
 *
 * Gemeldet 2026-08-22: "'Avatar ausblenden' Symbol und CPU Anzeige fehlen in
 * einigen Seiten, SSL-Zertifikat bei allen entfernen ausser 'home'".
 *
 * Die REIHENFOLGE selbst prueft tests/test_claude_subagent_ui.js (dort steht
 * der kanonische Rollen-Vergleich ueber alle Seiten). Hier geht es um die zwei
 * Symbole, die dort nicht auftauchen koennen:
 *   - die CPU-Anzeige (frontend/js/cpubar.js) – sie lag vorher in VIER
 *     Fassungen vor und fehlte deshalb auf der Haelfte der Seiten,
 *   - der Avatar-Schalter, den avatar.js zur Laufzeit einhaengt.
 *
 * Teil 1  Eine Fassung statt vier (Quelltext + CSS)
 * Teil 2  cpubar.js im echten DOM (Token, Wert, 401, Aufbau ohne Markup)
 * Teil 3  Anker des Avatar-Schalters
 *
 *   node tests/test_topbar_symbole_ui.js
 */
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const CPUBAR = lies('frontend/js/cpubar.js');
const AVATAR = lies('frontend/js/avatar.js');
const THEMECSS = lies('frontend/css/theme.css');

// Kommentare entfernen. Ein Waechter, der seine eigene Begruendung liest,
// prueft nichts – im Projekt schon mehrfach passiert.
const nurCode = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Eine Fassung statt vier');
{
    // Die Seiten mit Titelleiste. api.html und supportagent.html sind
    // Doku-Seiten ohne Anmeldung – cpubar.js laeuft dort ins Leere (kein
    // Token) und wird trotzdem geladen, damit die Liste keine Ausnahme hat.
    const SEITEN = ['chat.html', 'userchat.html', 'support.html', 'wissen.html',
                    'portal.html', 'sap.html', 'email.html', 'tracks.html',
                    'excel.html', 'claude.html'];
    for (const f of SEITEN) {
        const q = lies('frontend/' + f);
        pruefe(/<script src="\/static\/js\/cpubar\.js/.test(q),
               `${f}: bindet cpubar.js ein`);
    }

    // Die vier alten Fassungen sind weg. Geprueft wird der ZUGRIFF auf die
    // Anzeige, nicht ein Funktionsname – der laesst sich umbenennen.
    for (const js of ['frontend/js/support.js', 'frontend/js/wissen.js',
                      'frontend/js/userchat.js']) {
        const q = nurCode(lies(js));
        pruefe(!/\/api\/cpu/.test(q), `${js}: fragt /api/cpu nicht mehr selbst ab`);
        pruefe(!/cpu-bar-fill/.test(q), `${js}: schreibt die Anzeige nicht mehr selbst`);
    }
    // /chat behaelt seine WS-Quelle, zeichnet aber ueber die gemeinsame Fassung.
    const CHATJS = nurCode(lies('frontend/js/chat.js'));
    pruefe(/JarvisCpuBar\.setzeWert/.test(CHATJS),
           'chat.js: das WS-Ereignis geht durch JarvisCpuBar');
    pruefe(!/cpu-bar-fill/.test(CHATJS),
           'chat.js: fasst die Anzeige nicht mehr direkt an');

    // CSS: genau EINE Deklaration, und die frueheren drei Kopien sind weg.
    const anzahl = (THEMECSS.match(/^\.jv-cpu-bar \{/gm) || []).length;
    pruefe(anzahl === 1, '.jv-cpu-bar steht genau einmal in theme.css', `gefunden: ${anzahl}`);
    let kopien = [];
    for (const f of ['frontend/css/chat.css', 'frontend/css/style.css',
                     'frontend/support.html', 'frontend/wissen.html',
                     'frontend/chat.html', 'frontend/userchat.html']) {
        if (/chat-cpu-bar|sup-cpu-bar|wi-cpu-bar/.test(nurCode(lies(f)))) kopien.push(f);
    }
    pruefe(kopien.length === 0, 'keine seiteneigene CPU-Bar-Klasse mehr',
           kopien.join(', '));
    // Gegenprobe: der Suchbegriff muss ueberhaupt treffen koennen.
    pruefe(/jv-cpu-bar/.test(lies('frontend/chat.html')),
           'chat.html benutzt die gemeinsame Klasse (Gegenprobe zur Suche oben)');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('2. cpubar.js im echten DOM');

// Baut eine Seite auf, spielt cpubar.js ein und liefert Fenster + Aufrufliste.
function starte(seite, token, antwort) {
    const html = lies('frontend/' + seite);
    const dom = new JSDOM(html, { url: 'https://x/', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    if (token) w.localStorage.setItem('jarvis_token', token);
    w.fetch = (url, opt) => {
        rufe.push({ url: url, auth: (opt && opt.headers && opt.headers.Authorization) || '' });
        const r = antwort || { status: 200, ok: true, json: () => Promise.resolve({ cpu: 42.4 }) };
        return Promise.resolve(r);
    };
    w.eval(CPUBAR);
    return { w: w, d: w.document, rufe: rufe };
}
const gleich = () => new Promise((r) => setImmediate(r));

(async () => {
    {   // /chat bringt die Anzeige im Markup mit
        const { w, d, rufe } = starte('chat.html', 'tok-123');
        await gleich(); await gleich();
        const bar = d.getElementById('cpu-bar');
        pruefe(!!bar, 'chat.html: Anzeige vorhanden');
        pruefe(rufe.length === 1 && rufe[0].url === '/api/cpu',
               'genau ein Abruf von /api/cpu', JSON.stringify(rufe));
        pruefe(rufe[0] && rufe[0].auth === 'Bearer tok-123',
               'der Abruf traegt das Sitzungstoken');
        pruefe(d.getElementById('cpu-bar-label').textContent === 'CPU: 42%',
               'der Wert steht in der Anzeige',
               d.getElementById('cpu-bar-label').textContent);
        pruefe(bar.style.display === '', 'die Anzeige wird eingeblendet',
               `display=${bar.style.display}`);
        // Der WS-Weg von /chat schreibt durch dieselbe Fassung.
        w.JarvisCpuBar.setzeWert(7);
        pruefe(d.getElementById('cpu-bar-label').textContent === 'CPU: 7%',
               'setzeWert() schreibt ebenfalls in die Anzeige');
        w.close();
    }

    {   // Ohne Token bleibt sie aus – sonst stuende sie auf der Anmeldemaske
        const { d, rufe } = starte('chat.html', null);
        await gleich(); await gleich();
        pruefe(rufe.length === 0, 'ohne Token wird nicht abgefragt', JSON.stringify(rufe));
        const bar = d.getElementById('cpu-bar');
        pruefe(bar && bar.style.display === 'none', 'ohne Token bleibt sie verborgen');
    }

    {   // /email hat KEIN Markup – die Anzeige wird gebaut
        const { d } = starte('email.html', 'tok');
        await gleich(); await gleich();
        const bar = d.getElementById('cpu-bar');
        pruefe(!!bar, 'email.html: Anzeige wurde aufgebaut');
        pruefe(!!bar && bar.classList.contains('jv-cpu-bar'),
               'sie traegt die gemeinsame Klasse');
        pruefe(!!bar && bar.parentNode && bar.parentNode.classList.contains('topbar-left'),
               'sie sitzt links neben dem Titel, nicht in der Symbolgruppe',
               bar && bar.parentNode ? bar.parentNode.className : '(kein Elternteil)');
        pruefe(d.getElementById('cpu-bar-label').textContent === 'CPU: 42%',
               'und zeigt den Wert');
    }

    {   // /wissen versteckt sie ueber eine Klasse, nicht ueber display
        const { d } = starte('wissen.html', 'tok');
        await gleich(); await gleich();
        const bar = d.getElementById('cpu-bar');
        pruefe(!!bar && !bar.classList.contains('hidden'),
               'wissen.html: die Klasse `hidden` wird beim Anzeigen entfernt');
    }

    {   // 401: einstellen statt weiter klopfen
        const { rufe } = starte('chat.html', 'tok',
            { status: 401, ok: false, json: () => Promise.resolve(null) });
        await gleich(); await gleich(); await gleich();
        pruefe(rufe.length === 1, 'nach 401 wird die Abfrage eingestellt',
               `${rufe.length} Abrufe`);
    }

    /* ═════════════════════════════════════════════════════════════════ */
    abschnitt('3. Anker des Avatar-Schalters');
    {
        const q = nurCode(AVATAR);
        pruefe(/querySelector\('\.jv-issues-btn'\)/.test(q),
               'avatar.js ankert am Issues-Knopf (.jv-issues-btn)');
        pruefe(/getElementById\('btn-theme-toggle'\)/.test(q),
               'der Theme-Knopf bleibt als Rueckfall');
        pruefe(/classList\.remove\('jv-issues-btn'\)/.test(q),
               'die Anker-Klasse wird nicht mitkopiert (sonst waere der Schalter sein eigener Anker)');
        pruefe(/insertBefore\(toggleBtn, anker\)/.test(q),
               'der Schalter steht LINKS vom Anker');

        // Am echten Markup: genau ein Anker je Seite, und er steht links vom
        // Theme-Knopf – daraus folgt die geforderte Folge
        // "Avatar, Issues, Hell/Dunkel".
        const SEITEN = ['chat.html', 'userchat.html', 'support.html', 'wissen.html',
                        'portal.html', 'sap.html', 'email.html', 'tracks.html',
                        'excel.html', 'claude.html'];
        for (const f of SEITEN) {
            const s = lies('frontend/' + f);
            const n = (s.match(/class="[^"]*jv-issues-btn/g) || []).length;
            pruefe(n === 1, `${f}: genau ein Anker .jv-issues-btn`, `gefunden: ${n}`);
            const pAnker = s.search(/class="[^"]*jv-issues-btn/);
            const pTheme = s.search(/id="btn-theme-toggle"|id="btn-theme"/);
            pruefe(pAnker >= 0 && pTheme >= 0 && pAnker < pTheme,
                   `${f}: der Anker steht vor dem Hell/Dunkel-Knopf`);
        }
        for (const f of SEITEN) {
            pruefe(/<script src="\/static\/js\/avatar\.js/.test(lies('frontend/' + f)),
                   `${f}: laedt avatar.js`);
        }

        // ── Das ECHTE avatar.js einhaengen lassen ──────────────────────
        // Der Quelltext-Abgleich oben zeigt nur, dass die Zeilen dastehen.
        // Wo der Knopf LANDET, zeigt erst der Lauf. clippy/jQuery werden
        // dafuer nicht gebraucht: mit gemerktem "Avatar aus" haengt sich der
        // Schalter ein und `build()` wird uebersprungen.
        for (const [f, pfad, issId] of [
            ['chat.html',   '/chat',   'btn-chat-issues'],
            ['wissen.html', '/wissen', 'wi-issues'],
            ['portal.html', '/portal', 'pt-issues-btn'],
        ]) {
            const dom = new JSDOM(lies('frontend/' + f),
                { url: 'https://x' + pfad, runScripts: 'outside-only' });
            const w = dom.window;
            w.localStorage.setItem('jarvis_token', 'tok');
            w.localStorage.setItem('jarvis_avatar_off:' + pfad, '1');
            w.fetch = (url) => Promise.resolve({
                ok: true, status: 200,
                json: () => Promise.resolve(url === '/api/avatar/config'
                                            ? { active: true } : {}) });
            w.eval(AVATAR);
            w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
            await gleich(); await gleich(); await gleich();
            const t = w.document.getElementById('jav-toggle');
            const iss = w.document.getElementById(issId);
            pruefe(!!t, `${f}: avatar.js haengt den Schalter ein`);
            pruefe(!!t && t.nextElementSibling === iss,
                   `${f}: er steht unmittelbar LINKS vom Issues-Knopf`,
                   t ? `naechstes Element: ${t.nextElementSibling && t.nextElementSibling.id}` : '');
            pruefe(!!t && !t.classList.contains('jv-issues-btn'),
                   `${f}: er traegt die Anker-Klasse NICHT`);
            pruefe(!!t && t.className.split(/\s+/).length > 1,
                   `${f}: er uebernimmt den Stil des Ankers`, t ? t.className : '');
            w.close();
        }
    }

    /* ═════════════════════════════════════════════════════════════════ */
    abschnitt('4. Abstand der Symbole: eigene Gruppe mit gap 4px');
    /* Gemeldet 2026-08-22 ("die Symbol Abstaende auf /portal passen wieder
       einmal nicht ... auch das hatten wir schon mehrfach"). Gemessen: auf
       /portal standen ALLE Symbole 10 px auseinander statt 4 – weil die Seite
       ihre Leiste FLACH baut und die Knoepfe damit den Abstand erben, der fuer
       Logo/Titel/Status gedacht ist. Dieselbe Bauform-Frage wie bei /excel.

       Der Waechter prueft deshalb die STRUKTUR, nicht eine Pixelzahl je Seite:
       der Abmelden-Knopf darf kein direktes Kind der Titelleiste sein, und
       seine Gruppe muss `gap: 4px` haben. Damit faellt auch eine KUENFTIGE
       Seite auf, ohne dass jemand eine Liste pflegt. */
    {
        const CHATCSS = lies('frontend/css/chat.css');
        const AUSSEN = ['topbar', 'pt-topbar', 'wi-topbar', 'ad-top', 'sa-topbar'];
        const SEITEN = ['chat.html', 'userchat.html', 'support.html', 'wissen.html',
                        'portal.html', 'sap.html', 'email.html', 'tracks.html',
                        'excel.html', 'claude.html', 'api.html', 'supportagent.html'];
        for (const f of SEITEN) {
            const q = lies('frontend/' + f);
            const dom = new JSDOM(q);
            const d = dom.window.document;
            const knopf = Array.from(d.querySelectorAll('button, a'))
                .find(e => /logout/.test(e.id) || /Abmelden|Startseite/.test(e.getAttribute('title') || ''));
            if (!knopf) { pruefe(false, `${f}: Knopf fuer die Gruppenbestimmung gefunden`); continue; }
            const gruppe = (knopf.parentElement.className || '').split(/\s+/).filter(Boolean);
            pruefe(!gruppe.some(k => AUSSEN.includes(k)),
                   `${f}: die Symbole stehen in einer EIGENEN Gruppe, nicht in der Titelleiste`,
                   `Elternteil: .${gruppe.join('.') || '(ohne Klasse)'}`);
            // gap 4px – entweder in der Seite selbst oder in chat.css
            const css = q + CHATCSS;
            const treffer = gruppe.some(k => {
                const m = css.match(new RegExp('\\.' + k + '\\s*\\{[^}]*\\}', 'g')) || [];
                return m.some(r => /gap:\s*4px/.test(r));
            });
            pruefe(treffer, `${f}: die Gruppe hat gap: 4px`,
                   `.${gruppe.join('.')}`);
            dom.window.close();
        }
        // Ein gemeinsamer Baustein darf seinen Abstand nicht selbst mitbringen:
        // in einem `gap`-Container addiert sich ein `margin` darauf.
        // nurCode() ist hier Pflicht: die Begruendung IM Block nennt `margin`,
        // und ein Waechter, der seine eigene Begruendung liest, prueft nichts.
        const regel = (nurCode(THEMECSS).match(/\.jv-cpu-bar \{[^}]*\}/) || [''])[0];
        pruefe(regel !== '' && !/margin/.test(regel),
               '.jv-cpu-bar bringt keinen eigenen Rand mit', regel.replace(/\s+/g, ' '));
    }

    console.log(`\n\x1b[1m${ok} OK, ${fail} FAIL\x1b[0m`);
    process.exit(fail === 0 ? 0 : 1);
})();
