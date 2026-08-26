#!/usr/bin/env node
/**
 * Das Marken-Logo oben links fuehrt aufs Portal (Vorgabe des Nutzers, 2026-08-26).
 *
 * "zusaetzlich zum Klick auf das Home Symbol soll auch durch Klick auf das
 * 'J' / 'nx' Symbol oben links auf die Portalseite gewechselt werden."
 *
 * DER WAECHTER PRUEFT DIE REGEL, NICHT EINE LISTE:
 *
 *   Jede Seite mit einem Logo (`.topbar-avatar`) UND einem Weg zum Portal
 *   (`data-i18n-title="nav.home"`) muss `logo_home.js` laden.
 *   Jede Seite OHNE Weg zum Portal darf am Logo NICHTS bekommen.
 *
 * Damit faellt eine kuenftige Bereichsseite von selbst auf, ohne dass jemand
 * hier eine Liste pflegt - genau der Fehler, der die CPU-Anzeige auf sechs
 * Seiten fehlen liess.
 *
 * Das Modul wird WIRKLICH AUSGEFUEHRT (jsdom gegen die echten Dateien) und der
 * Klick wirklich ausgeloest. Eine Quelltext-Suche wuerde nur bestaetigen, dass
 * die Zeile dasteht.
 *
 *   node tests/test_logo_home_ui.js
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

const MODUL = fs.readFileSync(path.join(ROOT, 'frontend/js/logo_home.js'), 'utf8');
const THEME = fs.readFileSync(path.join(ROOT, 'frontend/css/theme.css'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

/* Alle Seiten mit Marken-Logo einsammeln - Verzeichnis lesen, keine Liste. */
function seiten() {
    const aus = [];
    const gehe = (rel) => {
        for (const e of fs.readdirSync(path.join(ROOT, rel), { withFileTypes: true })) {
            const r = rel + '/' + e.name;
            if (e.isDirectory()) { if (!/vendor|css|js|icons/.test(e.name)) gehe(r); continue; }
            if (!e.name.endsWith('.html')) continue;
            const t = fs.readFileSync(path.join(ROOT, r), 'utf8');
            if (t.indexOf('topbar-avatar') < 0) continue;
            aus.push({ rel: r, text: t,
                       weg: t.indexOf('data-i18n-title="nav.home"') >= 0,
                       modul: t.indexOf('logo_home.js') >= 0 });
        }
    };
    gehe('frontend');
    return aus;
}

// ══════════════════════════════════════════════════════════════════════════
abschnitt('1. Die Regel: Logo + Weg zum Portal => Modul geladen');
// ══════════════════════════════════════════════════════════════════════════
const alle = seiten();
pruefe(alle.length >= 12, alle.length + ' Seiten mit Marken-Logo gefunden');
const mitWeg = alle.filter(s => s.weg);
const ohneWeg = alle.filter(s => !s.weg);
pruefe(mitWeg.length >= 10, mitWeg.length + ' davon haben einen Weg zum Portal');
mitWeg.forEach(s => pruefe(s.modul, s.rel + ': laedt logo_home.js'));

// DIE GEGENRICHTUNG IST DIE WICHTIGERE HAELFTE. Ohne sie waere der Test durch
// "Modul ueberall einbinden" trivial erfuellbar - und in einem
// Office-Aufgabenfenster waere eine Navigation aufs Portal ein Fehler: das
// Fenster laeuft IN Outlook bzw. Excel.
ohneWeg.forEach(s => pruefe(!s.modul,
    s.rel + ': hat KEINEN Weg zum Portal und laedt das Modul deshalb NICHT'));
pruefe(ohneWeg.some(s => /portal\.html$/.test(s.rel)),
    '/portal selbst ist unter den Ausnahmen (ein Link auf sich ist kein Weg)');
pruefe(ohneWeg.filter(s => /addin/.test(s.rel)).length === 2,
    'beide Office-Aufgabenfenster sind unter den Ausnahmen',
    ohneWeg.map(s => s.rel).join(', '));
// Genau EIN Haus-Symbol je Seite - der Selektor des Moduls nimmt das erste.
mitWeg.forEach(s => {
    const n = (s.text.match(/data-i18n-title="nav\.home"/g) || []).length;
    pruefe(n === 1, s.rel + ': genau ein Haus-Symbol (' + n + ')');
});

// ══════════════════════════════════════════════════════════════════════════
abschnitt('2. Das Modul, wirklich ausgefuehrt');
// ══════════════════════════════════════════════════════════════════════════
function baue(html, url) {
    const dom = new JSDOM(html, { url: url || 'https://x/chat', runScripts: 'outside-only' });
    dom.window.eval(MODUL);
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    return dom;
}

// (a) Seite MIT Weg zum Portal (die `<a href>`-Bauform)
{
    const dom = baue('<div class="topbar-avatar">J</div>' +
        '<a id="haus" href="/portal" title="Startseite" data-i18n-title="nav.home">H</a>');
    const w = dom.window, d = w.document;
    const logo = d.querySelector('.topbar-avatar');
    pruefe(logo.classList.contains('jv-logo-home'), 'das Logo bekommt die Klasse');
    pruefe(logo.getAttribute('role') === 'button', 'role=button (es ist ein <div>)');
    pruefe(logo.getAttribute('tabindex') === '0', 'mit der Tastatur erreichbar');
    pruefe(logo.getAttribute('title') === 'Startseite',
        'Beschriftung uebernommen', logo.getAttribute('title'));
    pruefe(logo.getAttribute('aria-label') === 'Startseite', 'aria-label ebenso');
    // Kein eigener Text: die vorhandenen i18n-Schluessel muessen benutzt werden,
    // sonst laeuft die Beschriftung beim naechsten Sprachwechsel auseinander.
    pruefe(logo.getAttribute('data-i18n-title') === 'nav.home',
        'Beschriftung haengt am vorhandenen Schluessel nav.home');
    pruefe(logo.getAttribute('data-i18n-aria') === 'nav.home', '... auch fuer aria');
    // DER KLICK: das VORHANDENE Bedienelement wird ausgeloest, nicht selbst
    // navigiert - `/tracks` benutzt bewusst location.replace().
    let geklickt = 0;
    d.getElementById('haus').addEventListener('click', (e) => { e.preventDefault(); geklickt++; });
    logo.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    pruefe(geklickt === 1, 'ein Klick loest das Haus-Symbol aus', String(geklickt));
    // Tastatur
    logo.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    pruefe(geklickt === 2, 'Enter ebenso');
    logo.dispatchEvent(new w.KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    pruefe(geklickt === 3, 'Leertaste ebenso');
    logo.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    pruefe(geklickt === 3, 'eine andere Taste NICHT');
    w.close();
}

// (a2) DIE FALLE, DIE DER TEST GEFUNDEN HAT: das Modul setzt
//      `data-i18n-title="nav.home"` auf das LOGO (damit die Beschriftung dem
//      Sprachwechsel folgt) - und fand damit sein eigenes Werk als
//      "Haus-Symbol" wieder. Steht das Logo im Markup VOR dem Haus-Symbol
//      (und das tut es auf jeder Seite), klickte der Handler auf das Logo und
//      der Klick tat GAR NICHTS.
{
    const dom = baue('<div class="topbar-avatar">J</div>' +
        '<a id="haus" href="/portal" data-i18n-title="nav.home">H</a>');
    const w = dom.window, d = w.document;
    let n = 0;
    d.getElementById('haus').addEventListener('click', (e) => { e.preventDefault(); n++; });
    // Das Logo steht ZUERST im Dokument - genau die Reihenfolge der echten Seiten.
    const erstes = d.querySelector('[data-i18n-title="nav.home"]');
    pruefe(erstes && erstes.classList.contains('topbar-avatar'),
        'im DOM traegt das Logo den Schluessel nav.home ZUERST (die Falle)');
    d.querySelector('.topbar-avatar').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    pruefe(n === 1, '... der Klick trifft trotzdem das echte Haus-Symbol', String(n));
    pruefe(/:not\(\.topbar-avatar\)/.test(MODUL),
        'der Selektor schliesst das Logo ausdruecklich aus');
    w.close();
}

// (b) Die <button>-Bauform (/claude, /tracks, /email) - dort gibt es kein href.
{
    const dom = baue('<div class="topbar-avatar">nx</div>' +
        '<button id="knopf" title="Zum Portal" data-i18n-title="nav.home">H</button>');
    const w = dom.window, d = w.document;
    let n = 0;
    d.getElementById('knopf').addEventListener('click', () => n++);
    d.querySelector('.topbar-avatar').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    pruefe(n === 1, 'auch die Knopf-Bauform wird ausgeloest (kein href noetig)');
    w.close();
}

// (c) OHNE Weg zum Portal: nichts passiert. Das ist die Schranke, die /portal
//     und die Aufgabenfenster ohne Pflege draussen haelt.
{
    const dom = baue('<div class="topbar-avatar">J</div><a href="/chat">anderswo</a>');
    const logo = dom.window.document.querySelector('.topbar-avatar');
    pruefe(!logo.classList.contains('jv-logo-home'),
        'ohne Haus-Symbol bleibt das Logo unangetastet');
    pruefe(!logo.getAttribute('role') && !logo.getAttribute('tabindex'),
        '... und sieht auch nicht wie ein Knopf aus');
    dom.window.close();
}

// (d) Mehrere Logos auf einer Seite (die Aufgabenfenster haben zwei) und
//     doppelte Ausfuehrung: beides darf nichts kaputt machen.
{
    const dom = baue('<div class="topbar-avatar">J</div><div class="topbar-avatar">J</div>' +
        '<a id="haus" href="/portal" data-i18n-title="nav.home">H</a>');
    const w = dom.window, d = w.document;
    pruefe(d.querySelectorAll('.jv-logo-home').length === 2, 'beide Logos verdrahtet');
    // Zweiter Lauf (Sprachwechsel): der Merker muss doppelte Handler verhindern,
    // sonst feuert ein Klick zweimal.
    w.dispatchEvent(new w.Event('jarvis-lang-changed'));
    let n = 0;
    d.getElementById('haus').addEventListener('click', (e) => { e.preventDefault(); n++; });
    d.querySelector('.topbar-avatar').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    pruefe(n === 1, 'ein zweiter Lauf verdoppelt den Handler NICHT', String(n));
    w.close();
}

// (e) Wird die Leiste NACH dem Start neu gebaut, muss der Klick das dann
//     vorhandene Haus-Symbol treffen - deshalb sucht der Handler beim Klick neu.
{
    const dom = baue('<div class="topbar-avatar">J</div>' +
        '<div id="leiste"><a id="alt" href="/portal" data-i18n-title="nav.home">H</a></div>');
    const w = dom.window, d = w.document;
    d.getElementById('leiste').innerHTML =
        '<a id="neu" href="/portal" data-i18n-title="nav.home">H</a>';
    let n = 0;
    d.getElementById('neu').addEventListener('click', (e) => { e.preventDefault(); n++; });
    d.querySelector('.topbar-avatar').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    pruefe(n === 1, 'nach einem Neuaufbau der Leiste trifft der Klick das neue Symbol');
    w.close();
}

// ══════════════════════════════════════════════════════════════════════════
abschnitt('3. Aussehen: theme.css, nicht style.css/chat.css');
// ══════════════════════════════════════════════════════════════════════════
pruefe(/\.jv-logo-home\s*\{/.test(THEME), '.jv-logo-home steht in theme.css');
pruefe(/\.jv-logo-home\s*\{[^}]*cursor:\s*pointer/.test(THEME),
    'der Zeiger sagt, dass es klickbar ist');
pruefe(/\.jv-logo-home:focus-visible/.test(THEME),
    'sichtbarer Fokus fuer die Tastatur');
// `:focus` ohne `-visible` setzte nach JEDEM Mausklick einen Rahmen, der bis
// zum naechsten Klick stehenbleibt.
pruefe(!/\.jv-logo-home:focus\s*[,{]/.test(THEME),
    'und NICHT :focus (sonst Rahmen nach jedem Mausklick)');
['style.css', 'chat.css'].forEach(f => {
    const t = fs.readFileSync(path.join(ROOT, 'frontend/css', f), 'utf8');
    pruefe(t.indexOf('jv-logo-home') < 0,
        f + ' traegt die Regel NICHT (laedt nur auf zwei Seiten)');
});
// Harte Farben sind hier so verboten wie ueberall.
const regel = THEME.split('.jv-logo-home')[1].split('.jv-cpu-bar')[0];
pruefe(!/#[0-9a-fA-F]{3,6}\b/.test(regel), 'keine harten Farben in der Regel', regel);
// Wer die Regel aendert, muss den Cache-Buster mitziehen - sonst behaelt der
// Browser des Melders die alte Fassung.
const chat = fs.readFileSync(path.join(ROOT, 'frontend/chat.html'), 'utf8');
pruefe(/theme\.css\?v=\d+/.test(chat), 'theme.css ist versioniert eingebunden');

// ══════════════════════════════════════════════════════════════════════════
abschnitt('4. Kein neuer Text');
// ══════════════════════════════════════════════════════════════════════════
// Der Schluessel `nav.home` gibt es laengst - ein zweiter Text fuer dieselbe
// Aussage muesste bei jeder Sprachpflege mitgezogen werden.
pruefe((I18N.match(/'nav\.home'/g) || []).length === 2, 'nav.home in DE und EN');
pruefe(!/logo_home|logohome/i.test(I18N), 'das Modul bringt KEINEN eigenen i18n-Schluessel mit');

console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
