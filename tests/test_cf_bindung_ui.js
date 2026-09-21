#!/usr/bin/env node
/* Waechter fuer die dynamische Confluence-Einbindung – der ECHTE Renderer.
 *
 * Gefahren wird `frontend/js/wissen.js` unveraendert gegen die ECHTE
 * `wissen.html` und das ECHTE `i18n.js`; gestellt sind nur die Endpunkte.
 * Ob der Container ERSCHEINT, ob eine Auswahl WIRKLICH einbindet und was dabei
 * im Rumpf landet, kann eine Quelltext-Pruefung nicht beantworten.
 *
 * ⚠ jsdom fehlt -> Exit 2. "Konnte nicht laufen" darf nie wie "bestanden"
 * aussehen (Register).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try {
    const orte = [process.env.JSDOM_PATH, path.join(ROOT, 'node_modules/jsdom'),
                  path.join(ROOT, 'data/node_modules/jsdom'), '/tmp/node_modules/jsdom',
                  '/usr/share/nodejs/jsdom', '/usr/lib/node_modules/jsdom', 'jsdom'];
    for (const o of orte) {
        if (!o) continue;
        try { JSDOM = require(o).JSDOM; break; } catch (e) { /* weiter */ }
    }
} catch (e) { /* unten */ }
if (!JSDOM) { console.error('jsdom nicht gefunden – NICHT PRUEFBAR'); process.exit(2); }

let OK = 0, FAIL = 0, bilanz = false;
// Registriert FRUEH: ein Absturz mitten im Lauf darf nicht als Erfolg enden.
process.on('exit', () => {
    if (!bilanz) { console.error('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); process.exitCode = 1; }
});
const wach = setTimeout(() => {
    console.error('\n\x1b[31mZEITLIMIT – haengt\x1b[0m'); bilanz = true; process.exit(1);
}, 40000);

function section(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function check(d, c, i) {
    if (c) { OK++; console.log(`  \x1b[32m✓\x1b[0m ${d}`); }
    else { FAIL++; console.log(`  \x1b[31m✗\x1b[0m ${d}${i ? ' – ' + i : ''}`); }
}
const warten = (ms) => new Promise(r => setTimeout(r, ms));

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const WJS  = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');
const ICO  = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

/* Baut eine Seite mit dem ECHTEN Markup und dem ECHTEN wissen.js.
 * `spaces`  – was /api/wissen/confluence/spaces liefert
 * `bindung` – was /api/wissen/confluence/bindung liefert
 * Gemerkt werden alle Aufrufe, damit die Pruefungen den RUMPF messen koennen. */
async function seite(opt) {
    const o = Object.assign({ spaces: [], bindung: { ok: true, aktiv: true, bereiche: [] } }, opt || {});
    const dom = new JSDOM(HTML, { url: 'https://example.invalid/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    win.fetch = function (url, init) {
        const pfad = String(url).split('?')[0];
        const m = ((init && init.method) || 'GET').toUpperCase();
        let body = null;
        try { body = init && init.body ? JSON.parse(init.body) : null; } catch (e) { body = init.body; }
        rufe.push({ pfad, m, body });
        const j = (d) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/wissen/scope')
            return j({ ok: true, user: 'a.bender', is_editor: false,
                       groups: [{ id: 'g1', name: 'Technik', color: '#888', folders: ['data/rag/x'] }],
                       folders: [{ path: 'data/rag/x', name: 'x', display: 'x', root: 'data/rag/x', depth: 0 }] });
        if (pfad === '/api/wissen/confluence/spaces')
            return o.spacesFehler ? Promise.reject(new Error('weg'))
                                  : j({ ok: true, configured: true, spaces: o.spaces });
        if (pfad === '/api/wissen/confluence/bindung') {
            if (m === 'GET') return j(o.bindung);
            if (m === 'POST') {
                if (o.postFehler) return j({ ok: false, error: 'Bereich nicht sichtbar/erlaubt.' });
                const sp = o.spaces.filter(s => s.key === body.key)[0] || { name: body.key };
                const neu = { id: 'id-' + body.key, typ: 'space', key: body.key,
                              name: sp.name, inkl_unter: body.inkl_unter === true };
                o.bindung.bereiche = (o.bindung.bereiche || []).concat([neu]);
                return j({ ok: true, bereich: neu, bereiche: o.bindung.bereiche });
            }
        }
        if (pfad.indexOf('/api/wissen/confluence/bindung/') === 0 && m === 'DELETE') {
            const id = decodeURIComponent(pfad.split('/').pop());
            o.bindung.bereiche = (o.bindung.bereiche || []).filter(b => b.id !== id);
            return j({ ok: true, bereiche: o.bindung.bereiche });
        }
        if (pfad === '/api/wissen/files')   return j({ ok: true, files: [] });
        if (pfad === '/api/wissen/pending') return j({ ok: true, items: [] });
        return j({ ok: true });
    };
    win.confirm = () => o.confirm !== false;
    win.alert = () => {};
    win.eval(ICO);
    win.eval(I18N);
    win.eval(WJS);
    /* ⚠ NICHT SELBST DISPATCHEN. Direkt nach `new JSDOM` steht `readyState` auf
       'loading' – jsdom feuert DOMContentLoaded gleich darauf SELBST. Ein
       zusaetzlicher Dispatch ist dann der ZWEITE: `init()` laeuft doppelt, jeder
       Listener haengt zweifach, und ein einziger Klick erzeugt zwei Aufrufe.
       Genau das hat hier einen Doppel-POST vorgetaeuscht, den es nicht gibt. */
    if (win.document.readyState === 'loading') {
        await new Promise(r => win.document.addEventListener('DOMContentLoaded', r, { once: true }));
    } else {
        win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    }
    await warten(60);
    return { win, doc: win.document, rufe, o, zu: () => win.close() };
}

const SPACES = [
    { key: 'NEXUS', name: 'NEXUS Dokumentation', type: 'global' },
    { key: 'OPS', name: 'Betrieb', type: 'global' },
];

(async () => {

// ════════════════════════════════════════════════════════════════════════
section('1. Sichtbarkeit – nur bei aktivem UND konfiguriertem Skill');
{
    const s = await seite({ spaces: SPACES });
    const sec = s.doc.getElementById('wi-sec-cfbind');
    check('Container vorhanden', !!sec);
    check('bei aktivem Skill SICHTBAR', sec && sec.style.display !== 'none',
          sec ? `display=${sec.style.display}` : '');
    // Positivkontrolle: die Seite ist ueberhaupt initialisiert
    check('(Positivkontrolle) die App ist geladen',
          !s.doc.getElementById('wi-app').classList.contains('hidden'));
    // ⚠ Messaufbau-Kontrolle: laeuft init() doppelt, haengt JEDER Listener
    // zweifach und ein Klick erzeugt zwei Aufrufe – das saehe wie ein
    // Codefehler aus und ist keiner.
    check('(Positivkontrolle) init() lief GENAU EINMAL',
          s.rufe.filter(r => r.pfad === '/api/wissen/scope').length === 1,
          `${s.rufe.filter(r => r.pfad === '/api/wissen/scope').length}x scope`);
    s.zu();
}
for (const [was, b] of [
    ['Skill AUS', { ok: true, aktiv: false, skill_aktiv: false, configured: true, bereiche: [] }],
    ['nicht konfiguriert', { ok: true, aktiv: false, skill_aktiv: true, configured: false, bereiche: [] }],
    ['kein Wissensbereich (403)', { ok: false, error: 'x' }],
]) {
    const s = await seite({ spaces: SPACES, bindung: b });
    const sec = s.doc.getElementById('wi-sec-cfbind');
    check(`${was} -> Container VERBORGEN`, sec && sec.style.display === 'none',
          sec ? `display=${sec.style.display}` : '');
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('2. Pulldown – Angebot und Grundzustand');
{
    const s = await seite({ spaces: SPACES });
    const sel = s.doc.getElementById('wi-cfb-space');
    check('Pulldown gefuellt', sel && sel.options.length === 3,
          sel ? `${sel.options.length} Eintraege` : 'fehlt');
    check('erste Zeile ist der Platzhalter (leerer Wert)', sel && sel.options[0].value === '');
    check('Bereich steht mit Name UND Schluessel da',
          sel && /NEXUS Dokumentation \(NEXUS\)/.test(sel.options[1].textContent),
          sel ? sel.options[1].textContent : '');
    check('⚠ Kaestchen "inkl. Unterseiten" ist ANGEHAKT',
          s.doc.getElementById('wi-cfb-sub').checked === true);
    check('Liste meldet: noch nichts eingebunden',
          /Noch kein Bereich/.test(s.doc.getElementById('wi-cfb-list').textContent));
    s.zu();
}
{
    // ⚠ Bereits eingebundene fallen aus dem Angebot – sonst laeuft die Auswahl
    // in ein "ist bereits eingebunden", und niemand kann sich das erklaeren.
    const s = await seite({ spaces: SPACES, bindung: { ok: true, aktiv: true,
        bereiche: [{ id: 'a', key: 'NEXUS', name: 'NEXUS Dokumentation', inkl_unter: true }] } });
    const sel = s.doc.getElementById('wi-cfb-space');
    const werte = Array.from(sel.options).map(o => o.value);
    check('⚠ eingebundener Bereich wird NICHT erneut angeboten',
          werte.indexOf('NEXUS') === -1, werte.join(','));
    check('der freie Bereich bleibt im Angebot', werte.indexOf('OPS') !== -1);
    s.zu();
}
{
    const s = await seite({ spaces: SPACES, bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'a', key: 'NEXUS', name: 'N', inkl_unter: true },
        { id: 'b', key: 'OPS', name: 'O', inkl_unter: false }] } });
    const sel = s.doc.getElementById('wi-cfb-space');
    check('alles eingebunden -> Pulldown gesperrt MIT Grund',
          sel.disabled === true && /bereits eingebunden/.test(sel.options[0].textContent),
          sel.options[0].textContent);
    s.zu();
}
{
    const s = await seite({ spaces: [] });
    const sel = s.doc.getElementById('wi-cfb-space');
    check('keine Bereiche sichtbar -> Container bleibt da und SAGT es',
          s.doc.getElementById('wi-sec-cfbind').style.display !== 'none'
          && sel.disabled === true && /Keine Confluence-Bereiche/.test(sel.options[0].textContent),
          sel.options[0].textContent);
    s.zu();
}
{
    const s = await seite({ spaces: SPACES, spacesFehler: true });
    const sel = s.doc.getElementById('wi-cfb-space');
    check('⚠ Abruf der Bereiche gescheitert -> kein ewiges "Lade…"',
          sel.disabled === true && !/Lade/.test(sel.options[0].textContent),
          sel.options[0].textContent);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('3. Die AUSWAHL bindet ein – mit der Reichweite des Moments');
{
    const s = await seite({ spaces: SPACES });
    const sel = s.doc.getElementById('wi-cfb-space');
    sel.value = 'NEXUS';
    sel.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await warten(60);
    const post = s.rufe.filter(r => r.pfad === '/api/wissen/confluence/bindung' && r.m === 'POST');
    check('genau EIN POST', post.length === 1, `${post.length}`);
    check('der gewaehlte Schluessel geht mit', post[0] && post[0].body.key === 'NEXUS');
    check('⚠ inkl_unter faehrt den Haken mit (angehakt -> true)',
          post[0] && post[0].body.inkl_unter === true, JSON.stringify(post[0] && post[0].body));
    check('⚠ kein Benutzername im Rumpf (kommt aus der Anmeldung)',
          post[0] && !('user' in post[0].body) && !('von' in post[0].body));
    check('⚠ kein Anzeigename im Rumpf (kommt vom Server)',
          post[0] && !('name' in post[0].body));
    const liste = s.doc.getElementById('wi-cfb-list');
    check('der Bereich erscheint als konfigurierter Bereich',
          /NEXUS Dokumentation/.test(liste.textContent), liste.textContent.trim());
    check('die Reichweite steht als WORT dabei',
          /mit Untergeordnetem/.test(liste.textContent), liste.textContent.trim());
    check('das Pulldown steht wieder auf dem Platzhalter', sel.value === '');

    // Zweite Auswahl -> zweiter konfigurierter Bereich (so lautet die Vorgabe)
    s.doc.getElementById('wi-cfb-sub').checked = false;
    sel.value = 'OPS';
    sel.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await warten(60);
    const post2 = s.rufe.filter(r => r.pfad === '/api/wissen/confluence/bindung' && r.m === 'POST');
    check('⚠ ein weiterer Bereich wird ZWEITER Eintrag (nicht Ersatz)',
          s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 2,
          `${s.doc.querySelectorAll('#wi-cfb-list .wi-item').length}`);
    check('⚠ Haken AUS -> inkl_unter false', post2[1] && post2[1].body.inkl_unter === false,
          JSON.stringify(post2[1] && post2[1].body));
    check('die engere Reichweite steht ebenfalls als Wort da',
          /nur dieser Eintrag/.test(s.doc.getElementById('wi-cfb-list').textContent));
    s.zu();
}
{
    const s = await seite({ spaces: SPACES });
    const sel = s.doc.getElementById('wi-cfb-space');
    // Der Platzhalter darf NICHTS ausloesen.
    sel.value = '';
    sel.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await warten(40);
    check('Platzhalter loest keinen Serveraufruf aus',
          s.rufe.filter(r => r.m === 'POST').length === 0);
    s.zu();
}
{
    const s = await seite({ spaces: SPACES, postFehler: true });
    const sel = s.doc.getElementById('wi-cfb-space');
    sel.value = 'NEXUS';
    sel.dispatchEvent(new s.win.Event('change', { bubbles: true }));
    await warten(60);
    check('⚠ ein Fehlschlag wird GESAGT',
          /nicht sichtbar|erlaubt/.test(s.doc.getElementById('wi-cfb-status').textContent),
          s.doc.getElementById('wi-cfb-status').textContent);
    check('⚠ und das Pulldown ist danach wieder bedienbar', sel.disabled === false);
    check('nichts landet in der Liste',
          s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 0);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('4. Entfernen – der Rueckweg');
{
    const s = await seite({ spaces: SPACES, bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'a', key: 'NEXUS', name: 'NEXUS Dokumentation', inkl_unter: true }] } });
    const btn = s.doc.querySelector('#wi-cfb-list .wi-cfb-del');
    check('Muelleimer an der Zeile', !!btn);
    check('⚠ Muelleimer als SVG, kein × (Symbol-Semantik)',
          btn && btn.querySelector('svg') && !/[×✕✖]/.test(btn.textContent));
    btn.click();
    await warten(60);
    const del = s.rufe.filter(r => r.m === 'DELETE');
    check('DELETE mit der Kennung', del.length === 1 && /\/bindung\/a$/.test(del[0].pfad),
          JSON.stringify(del));
    check('die Zeile ist weg', s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 0);
    check('der Bereich steht wieder im Angebot',
          Array.from(s.doc.getElementById('wi-cfb-space').options).map(o => o.value).indexOf('NEXUS') !== -1);
    s.zu();
}
{
    const s = await seite({ confirm: false, spaces: SPACES, bindung: { ok: true, aktiv: true,
        bereiche: [{ id: 'a', key: 'NEXUS', name: 'N', inkl_unter: true }] } });
    s.doc.querySelector('#wi-cfb-list .wi-cfb-del').click();
    await warten(50);
    check('⚠ abgelehnte Rueckfrage entfernt NICHTS',
          s.rufe.filter(r => r.m === 'DELETE').length === 0
          && s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 1);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('5. Fremdtext und Sprachwechsel');
{
    const s = await seite({ spaces: [{ key: 'X', name: '<img src=x onerror=alert(1)>' }],
        bindung: { ok: true, aktiv: true, bereiche: [
            { id: 'a', key: 'Y', name: '<b>boese</b>', inkl_unter: true }] } });
    check('⚠ Bereichsname aus Confluence wird maskiert (Liste)',
          s.doc.querySelectorAll('#wi-cfb-list b').length === 0
          && /<b>boese<\/b>/.test(s.doc.getElementById('wi-cfb-list').textContent));
    check('⚠ und im Pulldown',
          s.doc.querySelectorAll('#wi-cfb-space img').length === 0);
    s.zu();
}
{
    const s = await seite({ spaces: SPACES });
    s.win.setLang ? s.win.setLang('en') : (s.win.applyLang && s.win.applyLang('en'));
    await warten(40);
    const h = s.doc.querySelector('#wi-sec-cfbind h2');
    check('Sprachwechsel erreicht die Ueberschrift',
          /Dynamic Confluence binding/.test(h.textContent), h.textContent.trim());
    s.zu();
}

clearTimeout(wach);
bilanz = true;
console.log(`\n\x1b[1mErgebnis: ${OK}/${OK + FAIL}\x1b[0m`);
process.exit(FAIL ? 1 : 0);

})().catch(e => {
    clearTimeout(wach); bilanz = true;
    console.error('\n\x1b[31mABGEBROCHEN:\x1b[0m', e && e.stack || e);
    console.log(`\n\x1b[1mErgebnis: ${OK}/${OK + FAIL + 1} (ABGEBROCHEN)\x1b[0m`);
    process.exit(1);
});
