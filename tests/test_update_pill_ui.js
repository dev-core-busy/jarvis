#!/usr/bin/env node
/**
 * Update-Pill: Aktion und Einstellung stehen FEST, nur die Liste scrollt.
 *
 * GEMELDET 2026-08-23 ("der Button im Popup wieder WIEDER abgeschnitten") und
 * nachgestellt: Knopf und Auto-Update-Zeile standen HINTER der Commit-Liste im
 * selben Scrollbereich (`.update-dropdown-body`, max-height 440px). Bei acht
 * Commits lag der Knopf ausserhalb des Sichtfensters – unerreichbar, ohne dass
 * etwas darauf hinwies.
 *
 * jsdom rechnet KEIN Layout. Geprueft wird deshalb die Eigenschaft, die den
 * Fehler unmoeglich macht: der Knopf ist kein Kind des scrollenden Koerpers.
 * Die Optik ist per Screenshot abgenommen (dunkel, hell, 40 Commits auf 560 px).
 *
 *   node tests/test_update_pill_ui.js
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

const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const CSS = lies('frontend/css/update_widget.css');
const JS  = lies('frontend/js/update_widget.js');
const nurCode = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

/* ===================================================================== */
abschnitt('1. CSS: Popup ist eine Flex-Spalte mit fester Fusszeile');
{
    const dd = (CSS.match(/^\.update-dropdown \{[\s\S]*?\}/m) || [''])[0];
    pruefe(/display:\s*flex/.test(dd) && /flex-direction:\s*column/.test(dd),
           '.update-dropdown ist eine Flex-Spalte');
    pruefe(/max-height:\s*calc\(100vh/.test(dd),
           '... und haengt am SICHTFENSTER, nicht an einer festen Zahl', dd.slice(0, 80));

    const bd = (CSS.match(/^\.update-dropdown-body \{[\s\S]*?\}/m) || [''])[0];
    pruefe(/overflow-y:\s*auto/.test(bd), '.update-dropdown-body scrollt');
    pruefe(/min-height:\s*0/.test(bd),
           '... mit min-height:0 (sonst bleibt overflow wirkungslos)');
    pruefe(!/max-height:\s*\d+px/.test(bd),
           '... und ohne feste max-height (die 440px waren die Ursache)', bd.slice(0, 90));

    const ft = (CSS.match(/^\.update-dropdown-foot \{[\s\S]*?\}/m) || [''])[0];
    pruefe(ft.length > 0, '.update-dropdown-foot existiert');
    pruefe(/flex:\s*0 0 auto/.test(ft), '... schrumpft nicht (flex:0 0 auto)');
    pruefe(!/overflow/.test(ft), '... scrollt nicht');
}

/* ===================================================================== */
abschnitt('2. JS: der Knopf liegt NICHT im scrollenden Koerper');
{
    const code = nurCode(JS);
    // NICHT per Regex bis zum ersten ';' schneiden: die zusammengesetzten
    // Zeichenketten enthalten selbst Semikolons (`font-size:.82rem;`), der
    // Schnitt endet dann mitten im Ausdruck und die Pruefungen sind trivial
    // wahr. Geschnitten wird an der STRUKTUR: alles vor `var f = foot()`
    // gehoert zum Koerper, alles danach zur Fusszeile.
    const fn = (code.match(/function buildBody\([\s\S]*?\n    \}/) || [''])[0];
    pruefe(fn.length > 0, 'buildBody gefunden (Gegenprobe zum Schnitt)');
    const trenn = fn.indexOf('var f = foot()');
    pruefe(trenn > 0, 'die Fusszeile wird in buildBody gefuellt', String(trenn));
    // Ab `body.innerHTML =`, nicht ab Funktionsbeginn: die Variablen (u.a.
    // btnHtml) werden davor DEFINIERT, das ist in Ordnung – es geht darum, was
    // ZUGEWIESEN wird.
    const zuw = fn.indexOf('body.innerHTML');
    pruefe(zuw > 0 && zuw < trenn,
           'der Koerper wird vor der Trennstelle gesetzt (Gegenprobe)');
    const teilKoerper = fn.slice(zuw, trenn);
    const teilFuss = fn.slice(trenn);
    pruefe(/commitsHtml/.test(teilKoerper),
           'die Commit-Liste steht im Koerper (Gegenprobe)');
    pruefe(!/btnHtml/.test(teilKoerper),
           'der Koerper enthaelt den Knopf NICHT');
    pruefe(!/upd-schedule/.test(teilKoerper),
           'und auch die Auto-Update-Zeile nicht');
    pruefe(/btnHtml/.test(teilFuss) && /upd-schedule/.test(teilFuss),
           'beide stehen in der Fusszeile');
}

/* ===================================================================== */
abschnitt('3. Im echten DOM: Struktur nach dem Rendern');

function starte(commits, hasUpdate) {
    const html = lies('frontend/portal.html');
    const vc = new VirtualConsole(); vc.on('jsdomError', () => {});
    const dom = new JSDOM(html, { url: 'https://x/portal',
                                  runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 't:1:x');
    const liste = [];
    for (let i = 0; i < commits; i++) {
        liste.push({ hash: 'h' + i, message: 'nachricht ' + i, date: '2026-08-01' });
    }
    w.fetch = (u) => {
        u = String(u);
        if (u.indexOf('/api/update/status') === 0) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({
                ok: true, has_update: hasUpdate, commits_behind: commits,
                jarvis_version: '0.9', current_hash: 'abc1234', branch: 'master',
                recent_commits: liste }) });
        }
        if (u.indexOf('/api/update/settings') === 0) {
            return Promise.resolve({ ok: true,
                json: () => Promise.resolve({ auto_update_schedule: 'never' }) });
        }
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    };
    w.t = (k) => k;
    w.eval(JS);
    w.JarvisUpdateWidget.init();
    return w;
}
const gleich = () => new Promise((r) => setImmediate(r));

(async () => {
    {
        const w = starte(8, true);
        for (let i = 0; i < 6; i++) await gleich();
        const d = w.document;
        const body = d.getElementById('upd-body');
        const foot = d.getElementById('upd-foot');
        const btn = d.getElementById('upd-apply-btn');
        const sel = d.getElementById('upd-schedule');
        pruefe(!!foot, 'die Fusszeile entsteht auch ohne Markup in portal.html');
        pruefe(!!btn, 'Aktions-Knopf vorhanden');
        pruefe(btn && !body.contains(btn),
               'der Knopf liegt NICHT im scrollenden Koerper');
        pruefe(btn && foot && foot.contains(btn), '... sondern in der Fusszeile');
        pruefe(sel && foot.contains(sel), 'die Auto-Update-Zeile ebenfalls');
        pruefe(body && body.querySelectorAll('.upd-commit').length === 8,
               'alle acht Commits stehen im scrollenden Teil',
               body && String(body.querySelectorAll('.upd-commit').length));
        pruefe(foot && foot.querySelectorAll('.upd-commit').length === 0,
               'und keiner in der Fusszeile');
        // Die Fusszeile ist ein Geschwister NACH dem Koerper - sonst stuende
        // der Knopf ueber der Liste.
        pruefe(foot && body && foot.previousElementSibling === body,
               'die Fusszeile steht unter dem Koerper');
        w.close();
    }
    {   // Kein Update: statt des Anwenden-Knopfes der Pruef-Knopf, gleiche Stelle
        const w = starte(0, false);
        for (let i = 0; i < 6; i++) await gleich();
        const d = w.document;
        const foot = d.getElementById('upd-foot');
        const chk = d.getElementById('upd-check-btn');
        pruefe(!!chk && foot.contains(chk),
               'ohne Update steht der Pruef-Knopf in der Fusszeile');
        pruefe(!d.getElementById('upd-apply-btn'),
               'und KEIN Anwenden-Knopf');
        w.close();
    }
    {   // Zweimal rendern darf keine zweite Fusszeile erzeugen
        const w = starte(3, true);
        for (let i = 0; i < 6; i++) await gleich();
        w.JarvisUpdateWidget.init();          // idempotent
        const p = w.document.getElementById('version-pill');
        p.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        for (let i = 0; i < 6; i++) await gleich();
        pruefe(w.document.querySelectorAll('.update-dropdown-foot').length === 1,
               'genau EINE Fusszeile, auch nach erneutem Rendern',
               String(w.document.querySelectorAll('.update-dropdown-foot').length));
        w.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
