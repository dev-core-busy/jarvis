#!/usr/bin/env node
/* Waechter fuer die dynamische Confluence-Einbindung – der ECHTE Renderer,
 * Baum-Fassung (Vorgabe 2026-09-27).
 *
 * Gefahren wird `frontend/js/wissen.js` unveraendert gegen die ECHTE
 * `wissen.html` und das ECHTE `i18n.js`; gestellt sind nur die Endpunkte.
 * Ob [+] wirklich markiert, [-] wirklich zuruecknimmt, der Name NICHTS am
 * Haken aendert und was beim Uebernehmen im Rumpf landet, kann eine
 * Quelltext-Pruefung nicht beantworten – hier wird GEKLICKT.
 *
 * ⚠ jsdom fehlt -> Exit 2. "Konnte nicht laufen" darf nie wie "bestanden"
 * aussehen (Register).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

let OK = 0, FAIL = 0, bilanz = false;
process.on('exit', () => {
    if (!bilanz) { console.error('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); process.exitCode = 1; }
});
const wach = setTimeout(() => {
    console.error('\n\x1b[31mZEITLIMIT – haengt\x1b[0m'); bilanz = true; process.exit(1);
}, 60000);

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

const SPACES = [
    { key: 'CONTOSO', name: 'CONTOSO Dokumentation', type: 'global' },
    { key: 'OPS', name: 'Betrieb', type: 'global' },
    { key: 'LEER', name: 'Leerer Bereich', type: 'global' },
];
/* Seitenbaeume in der ECHTEN Antwortform von /api/wissen/confluence/pages
   ({ok, count, pages:[{id,title,link,parent}]}). CONTOSO:
     1 Handbuch
       2 Kapitel A
         3 Kapitel A.1
       4 Kapitel B            */
const PAGES = {
    CONTOSO: [{ id: '1', title: 'Handbuch', parent: '' }, { id: '2', title: 'Kapitel A', parent: '1' },
            { id: '3', title: 'Kapitel A.1', parent: '2' }, { id: '4', title: 'Kapitel B', parent: '1' }],
    OPS: [{ id: '10', title: 'Start', parent: '' }, { id: '11', title: 'Detail', parent: '10' }],
    LEER: [],
};

async function seite(opt) {
    const o = Object.assign({ spaces: SPACES, bindung: { ok: true, aktiv: true, bereiche: [] },
                             groups: [{ id: 'g1', name: 'Technik', color: '#888', folders: ['data/rag/x'] }] },
                           opt || {});
    const dom = new JSDOM(HTML, { url: 'https://example.invalid/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    const neuerEintrag = (body, id) => {
        const namen = {}; o.spaces.forEach(s => { namen[s.key] = s.name; });
        const aw = (body.auswahl || []).map(a => Object.assign({}, a, { name: namen[a.key] || a.key }));
        return { id: id, typ: 'auswahl', name: aw.map(a => a.name).join(' · '), auswahl: aw,
                 gruppen: body.groups || [],
                 /* wie der Server (`_tags_pruefen`): klein, ohne fuehrendes # */
                 tags: (body.tags || []).map(x => String(x).replace(/^#+/, '').toLowerCase()).filter(Boolean),
                 gruppen_info: (body.groups || []).map(gid => {
                     const g = o.groups.filter(x => x.id === gid)[0];
                     return { id: gid, name: g ? g.name : gid, color: g ? g.color : '' };
                 }), abgleich: null };
    };
    win.fetch = function (url, init) {
        const pfad = String(url).split('?')[0];
        const q = String(url).split('?')[1] || '';
        const m = ((init && init.method) || 'GET').toUpperCase();
        let body = null;
        try { body = init && init.body ? JSON.parse(init.body) : null; } catch (e) { body = init.body; }
        rufe.push({ pfad, q, m, body });
        const j = (d) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/wissen/scope')
            /* ⚠ VORGABE IST EINE Gruppe – `groupBoxes` hakt sie dann von selbst an.
               Der zweigruppige Fall wird eigens hergestellt. */
            return j({ ok: true, user: 'm.mustermann', is_editor: false, groups: o.groups,
                       folders: [{ path: 'data/rag/x', name: 'x', display: 'x', root: 'data/rag/x', depth: 0 }] });
        if (pfad === '/api/wissen/confluence/spaces')
            return o.spacesFehler ? Promise.reject(new Error('weg'))
                                  : j({ ok: true, configured: true, spaces: o.spaces });
        if (pfad === '/api/wissen/confluence/pages') {
            const key = decodeURIComponent((q.match(/space=([^&]*)/) || [])[1] || '');
            if (o.pagesFehler && o.pagesFehler.indexOf(key) !== -1) return j({ ok: false, error: 'kaputt' });
            const p = (o.pages || PAGES)[key] || [];
            // Langsamer Bereich (Wettlauf-Probe): die Antwort kommt spaeter
            const ms = (o.pagesVerzoegerung || {})[key];
            if (ms) return new Promise(r => setTimeout(r, ms)).then(() => j({ ok: true, count: p.length, pages: p }));
            return j({ ok: true, count: p.length, pages: p });
        }
        if (pfad === '/api/wissen/confluence/bindung') {
            if (m === 'GET') return j(o.bindung);
            if (m === 'POST') {
                if (o.postFehler) return j({ ok: false, error: 'Bereich nicht sichtbar/erlaubt.' });
                const neu = neuerEintrag(body, 'id-' + (o.bindung.bereiche.length + 1));
                o.bindung.bereiche = (o.bindung.bereiche || []).concat([neu]);
                return j({ ok: true, bereich: neu, bereiche: o.bindung.bereiche });
            }
        }
        if (pfad.indexOf('/api/wissen/confluence/bindung/') === 0) {
            const id = decodeURIComponent(pfad.split('/').pop());
            if (m === 'DELETE') {
                o.bindung.bereiche = (o.bindung.bereiche || []).filter(b => b.id !== id);
                return j({ ok: true, bereiche: o.bindung.bereiche });
            }
            if (m === 'PUT') {
                const neu = neuerEintrag(body, id);
                o.bindung.bereiche = o.bindung.bereiche.map(b => b.id === id ? neu : b);
                return j({ ok: true, bereich: neu, bereiche: o.bindung.bereiche });
            }
        }
        if (pfad === '/api/wissen/files')   return j({ ok: true, files: [] });
        if (pfad === '/api/wissen/pending') return j({ ok: true, items: [] });
        return j({ ok: true });
    };
    win.confirm = () => o.confirm !== false;
    win.alert = () => {};
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle und rufen sie beim
    // LADEN auf. Jede echte Seite laedt sie davor.
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(ICO);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(I18N);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(WJS);
    /* ⚠ NICHT SELBST DISPATCHEN – jsdom feuert DOMContentLoaded selbst; ein
       zweiter Dispatch haengt jeden Listener doppelt (Register). */
    if (win.document.readyState === 'loading') {
        await new Promise(r => win.document.addEventListener('DOMContentLoaded', r, { once: true }));
    } else {
        win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    }
    await warten(60);
    const doc = win.document;
    const sp = (key) => doc.querySelector('#wi-cfb-tree li.wi-cfb-sp[data-key="' + key + '"]');
    const pg = (id) => doc.querySelector('#wi-cfb-tree li.wi-cfb-pg[data-id="' + id + '"]');
    const kind = (li, k) => li ? Array.prototype.filter.call(li.children, c => c.classList.contains(k))[0] || null : null;
    const node = (li) => kind(li, 'wi-cf-node');
    const cb = (li) => { const n = node(li); return n ? n.querySelector('.wi-cfb-cb') : null; };
    const tog = (li) => { const n = node(li); return n ? n.querySelector('.wi-cfb-tog') : null; };
    const nm = (li) => { const n = node(li); return n ? n.querySelector('.wi-cfb-nm') : null; };
    const offen = (li) => { const u = kind(li, 'wi-cf-kids'); return !!(u && u.classList.contains('open')); };
    const posts = () => rufe.filter(r => r.pfad.indexOf('/api/wissen/confluence/bindung') === 0 && (r.m === 'POST' || r.m === 'PUT'));
    const klick = async (el) => { if (!el) throw new Error('Element fehlt'); el.click(); await warten(40); };
    return { win, doc, rufe, o, sp, pg, cb, tog, nm, offen, posts, klick, zu: () => win.close() };
}

(async () => {

// ════════════════════════════════════════════════════════════════════════
section('1. Sichtbarkeit – nur bei aktivem UND konfiguriertem Skill');
{
    const s = await seite();
    const sec = s.doc.getElementById('wi-sec-cfbind');
    check('bei aktivem Skill SICHTBAR', sec && sec.style.display !== 'none');
    check('(Positivkontrolle) die App ist geladen', !s.doc.getElementById('wi-app').classList.contains('hidden'));
    check('(Positivkontrolle) init() lief GENAU EINMAL',
          s.rufe.filter(r => r.pfad === '/api/wissen/scope').length === 1);
    s.zu();
}
for (const [was, b] of [
    ['Skill AUS', { ok: true, aktiv: false, skill_aktiv: false, configured: true, bereiche: [] }],
    ['nicht konfiguriert', { ok: true, aktiv: false, skill_aktiv: true, configured: false, bereiche: [] }],
    ['kein Wissensbereich (403)', { ok: false, error: 'x' }],
]) {
    const s = await seite({ bindung: b });
    const sec = s.doc.getElementById('wi-sec-cfbind');
    check(`${was} -> Container VERBORGEN`, sec && sec.style.display === 'none');
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('2. Baum – Grundzustand');
{
    const s = await seite();
    check('⚠ kein Pulldown mehr, kein Kaestchen "inkl. Unterseiten"',
          !s.doc.querySelector('#wi-sec-cfbind select') && !s.doc.getElementById('wi-cfb-sub'));
    check('alle Bereiche stehen im Baum', s.doc.querySelectorAll('#wi-cfb-tree li.wi-cfb-sp').length === 3);
    const t0 = s.tog(s.sp('CONTOSO'));
    check('⚠ hinter dem Namen steht [+]', t0 && t0.textContent === '[+]', t0 ? t0.textContent : 'fehlt');
    const n0 = s.nm(s.sp('CONTOSO'));
    check('[+] steht HINTER dem Namen (im DOM nach ihm)',
          n0 && t0 && (n0.compareDocumentPosition(t0) & s.win.Node.DOCUMENT_POSITION_FOLLOWING));
    check('Name und Schluessel stehen da', /CONTOSO Dokumentation/.test(n0.textContent) && /\(CONTOSO\)/.test(n0.textContent));
    check('nichts markiert, nichts geladen',
          s.doc.querySelectorAll('#wi-cfb-tree .wi-cfb-cb:checked').length === 0
          && s.rufe.filter(r => r.pfad === '/api/wissen/confluence/pages').length === 0);
    const btn = s.doc.getElementById('wi-cfb-add');
    check('⚠ ohne Markierung ist der Knopf GESPERRT mit Grund',
          btn.disabled === true && /markieren|tick/i.test(btn.title), btn.title);
    check('Liste meldet: noch nichts gespeichert', /Noch kein Eintrag/.test(s.doc.getElementById('wi-cfb-list').textContent));
    check('der Hinweis zum Abgleich steht da, die alte Warnung nicht',
          /Wissensabgleich/.test(s.doc.getElementById('wi-sec-cfbind').textContent)
          && !/produktiv/.test(s.doc.getElementById('wi-sec-cfbind').textContent));
    s.zu();
}
{
    const s = await seite({ spaces: [] });
    check('keine Bereiche sichtbar -> Container bleibt da und SAGT es',
          /Keine Confluence-Bereiche/.test(s.doc.getElementById('wi-cfb-tree').textContent));
    s.zu();
}
{
    const s = await seite({ spacesFehler: true });
    check('⚠ Abruf der Bereiche gescheitert -> kein ewiges "Lade…"',
          !/Lade/.test(s.doc.getElementById('wi-cfb-tree').textContent),
          s.doc.getElementById('wi-cfb-tree').textContent);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('3. [+] klappt auf UND markiert samt allem darunter');
{
    const s = await seite();
    const li = s.sp('CONTOSO');
    await s.klick(s.tog(li));
    check('Seitenbaum genau EINMAL geholt',
          s.rufe.filter(r => r.pfad === '/api/wissen/confluence/pages').length === 1);
    check('⚠ der Bereich ist aufgeklappt', s.offen(li));
    check('⚠ aus [+] wird [-]', s.tog(li).textContent === '[-]', s.tog(li).textContent);
    check('⚠ der Bereich SELBST ist markiert', s.cb(li).checked === true);
    const alle = li.querySelectorAll('li.wi-cfb-pg .wi-cfb-cb');
    check('⚠ und ALLE Unterbereiche (auch der Enkel)',
          alle.length === 4 && Array.prototype.every.call(alle, x => x.checked), `${alle.length}`);
    check('Unterbereiche mit eigenen Kindern tragen selbst [+]',
          s.tog(s.pg('1')) && s.tog(s.pg('2')) && !s.tog(s.pg('3')) && !s.tog(s.pg('4')));
    check('⚠ Markieren allein speichert NICHTS', s.posts().length === 0);
    check('der Knopf ist frei (eine Gruppe ist vorbelegt)', s.doc.getElementById('wi-cfb-add').disabled === false);
    check('der Zaehler nennt einen markierten Bereich',
          /1 Bereich/.test(s.doc.getElementById('wi-cfb-marked').textContent));

    section('4. [-] klappt zu UND nimmt die Markierung darunter zurueck');
    await s.klick(s.tog(li));
    check('⚠ zugeklappt', !s.offen(li));
    check('⚠ aus [-] wird wieder [+]', s.tog(li).textContent === '[+]');
    check('⚠ alle Unterbereiche sind NICHT mehr markiert',
          li.querySelectorAll('li.wi-cfb-pg .wi-cfb-cb:checked').length === 0);
    check('⚠ der Bereich selbst BLEIBT markiert', s.cb(li).checked === true);
    check('kein zweiter Abruf des Seitenbaums',
          s.rufe.filter(r => r.pfad === '/api/wissen/confluence/pages').length === 1);

    section('5. Der NAME klappt nur auf/zu – die Haken bleiben');
    await s.klick(s.nm(li));
    check('⚠ Name: aufgeklappt', s.offen(li));
    check('⚠ Name: die Unterbereiche wurden NICHT markiert',
          li.querySelectorAll('li.wi-cfb-pg .wi-cfb-cb:checked').length === 0);
    check('Name: der Bereich bleibt, wie er war (markiert)', s.cb(li).checked === true);
    check('[-] zeigt den offenen Zustand', s.tog(li).textContent === '[-]');
    // Einen Unterbereich einzeln markieren, dann per Name zuklappen
    await s.klick(s.cb(s.pg('4')));
    check('⚠ ein Haken wirkt NUR auf seinen Eintrag',
          s.cb(s.pg('4')).checked && !s.cb(s.pg('1')).checked && !s.cb(s.pg('2')).checked);
    check('ueber dem gewaehlten Unterbereich steht ein HALBER Haken', s.cb(s.pg('1')).indeterminate === true);
    await s.klick(s.nm(li));
    check('⚠ Name: zugeklappt', !s.offen(li));
    check('⚠ Name: die Haken der Unterbereiche wurden dabei NICHT veraendert',
          s.cb(s.pg('4')).checked === true && s.cb(li).checked === true);
    // Unmarkierter Bereich per Name: nichts wird markiert
    await s.klick(s.nm(s.sp('OPS')));
    check('Name an einem unmarkierten Bereich: auf, aber nichts markiert',
          s.offen(s.sp('OPS')) && s.sp('OPS').querySelectorAll('.wi-cfb-cb:checked').length === 0);
    check('⚠ nichts von alledem hat gespeichert', s.posts().length === 0);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('5b. Ein Haken an einem Eintrag MIT Unterbereichen zieht nichts mit');
{
    // ⚠ Mit einem BLATT ist die Zusage nicht messbar – es hat nichts unter
    // sich (Gegenprobe "ein Haken zieht die Unterbereiche mit" blieb stumm).
    const s = await seite();
    await s.klick(s.nm(s.sp('CONTOSO')));
    check('(Positivkontrolle) Kapitel A hat einen Unterbereich', !!s.pg('3') && !!s.tog(s.pg('2')));
    await s.klick(s.cb(s.pg('2')));
    check('⚠ Haken an Kapitel A: nur Kapitel A', s.cb(s.pg('2')).checked && !s.cb(s.pg('3')).checked);
    await s.klick(s.cb(s.sp('CONTOSO')));
    check('⚠ Haken am Bereich: nur der Bereich, keine Unterbereiche dazu',
          s.cb(s.sp('CONTOSO')).checked && !s.cb(s.pg('1')).checked && !s.cb(s.pg('4')).checked);
    await s.klick(s.cb(s.pg('2')));
    check('Haken wieder weg: auch nur Kapitel A', !s.cb(s.pg('2')).checked && !s.cb(s.pg('3')).checked);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('6. [+] an einer Seite markiert nur deren Zweig');
{
    const s = await seite();
    await s.klick(s.nm(s.sp('CONTOSO')));              // nur aufklappen
    await s.klick(s.tog(s.pg('2')));                  // [+] an "Kapitel A"
    check('Kapitel A und A.1 markiert', s.cb(s.pg('2')).checked && s.cb(s.pg('3')).checked);
    check('⚠ Geschwister und Eltern NICHT', !s.cb(s.pg('4')).checked && !s.cb(s.pg('1')).checked
          && !s.cb(s.sp('CONTOSO')).checked);
    await s.klick(s.tog(s.pg('2')));                  // [-]
    check('[-] an der Seite nimmt nur ihren Zweig zurueck',
          s.cb(s.pg('2')).checked && !s.cb(s.pg('3')).checked);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('7. Uebernehmen: EIN Eintrag, die Auswahl im Rumpf');
{
    const s = await seite();
    await s.klick(s.tog(s.sp('CONTOSO')));              // ganzer Bereich
    await s.klick(s.nm(s.sp('OPS')));                 // OPS aufklappen, nichts markieren
    await s.klick(s.cb(s.pg('11')));                  // nur Detail
    await s.klick(s.cb(s.sp('LEER')));                // leerer Bereich, nur der Bereich selbst
    check('drei Bereiche markiert', /3 Bereich/.test(s.doc.getElementById('wi-cfb-marked').textContent),
          s.doc.getElementById('wi-cfb-marked').textContent);
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const p = s.posts();
    check('⚠ genau EIN Aufruf fuer drei Bereiche (ein gemeinsamer Eintrag)', p.length === 1 && p[0].m === 'POST', `${p.length}`);
    const aw = (p[0] && p[0].body.auswahl) || [];
    const a = (k) => aw.filter(x => x.key === k)[0] || {};
    check('alle drei Bereiche in DERSELBEN Auswahl', aw.length === 3, JSON.stringify(aw));
    check('⚠ komplett markierter Bereich geht als ganz', a('CONTOSO').ganz === true && a('CONTOSO').start === true,
          JSON.stringify(a('CONTOSO')));
    check('⚠ komplett markierte Zweige (mit Kindern) stehen in zweige, Blaetter nicht',
          JSON.stringify((a('CONTOSO').zweige || []).slice().sort()) === '["1","2"]', JSON.stringify(a('CONTOSO').zweige));
    check('⚠ einzeln markierte Seite: nur sie, kein Zweig, nicht ganz',
          JSON.stringify(a('OPS').seiten) === '["11"]' && !a('OPS').ganz && !a('OPS').start
          && (a('OPS').zweige || []).length === 0, JSON.stringify(a('OPS')));
    check('nur der Bereich selbst: start ohne Seiten', a('LEER').start === true && (a('LEER').seiten || []).length === 0,
          JSON.stringify(a('LEER')));
    check('⚠ die Wissensgruppe geht mit', p[0] && JSON.stringify(p[0].body.groups) === '["g1"]');
    check('⚠ kein Benutzer- und kein Anzeigename im Rumpf',
          p[0] && !('user' in p[0].body) && !('von' in p[0].body) && !aw.some(x => 'name' in x));
    check('der Eintrag erscheint in der Liste', s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 1);
    check('⚠ danach ist der Baum leer (nicht doppelt uebernehmbar)',
          s.doc.querySelectorAll('#wi-cfb-tree .wi-cfb-cb:checked').length === 0
          && s.doc.getElementById('wi-cfb-add').disabled === true);
    s.zu();
}
{
    const s = await seite();
    await s.klick(s.tog(s.sp('LEER')));
    check('⚠ ein Bereich ohne Unterbereiche verliert sein [+]', !s.tog(s.sp('LEER')));
    check('und sagt es', /keine Unterbereiche/.test(s.sp('LEER').textContent));
    check('bleibt aber als Bereich markiert', s.cb(s.sp('LEER')).checked === true);
    s.zu();
}
{
    // Teilweise markierter Zweig: KEIN Zweig, keine neuen Seiten
    const s = await seite();
    await s.klick(s.tog(s.sp('CONTOSO')));
    await s.klick(s.cb(s.pg('3')));                   // Enkel ab
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const aw = ((s.posts()[0] || {}).body || {}).auswahl || [];
    check('⚠ ein Loch im Zweig: nicht mehr ganz', aw[0] && aw[0].ganz === false, JSON.stringify(aw[0]));
    check('⚠ und die angeschnittenen Zweige sind keine Zweige mehr',
          aw[0] && JSON.stringify(aw[0].zweige) === '[]', JSON.stringify(aw[0] && aw[0].zweige));
    check('die markierten Seiten stehen einzeln da',
          aw[0] && JSON.stringify(aw[0].seiten.slice().sort()) === '["1","2","4"]', JSON.stringify(aw[0] && aw[0].seiten));
    s.zu();
}
{
    const s = await seite({ postFehler: true });
    await s.klick(s.tog(s.sp('OPS')));
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    check('Fehlschlag: der Grund steht da', /nicht sichtbar/.test(s.doc.getElementById('wi-cfb-status').textContent));
    check('⚠ Fehlschlag: die Markierung BLEIBT stehen', s.cb(s.sp('OPS')).checked === true);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('8. Wissensgruppen-Pflicht (zweigruppig)');
{
    const s = await seite({ groups: [{ id: 'g1', name: 'Technik', color: '#888', folders: ['data/rag/x'] },
                                     { id: 'g2', name: 'Vertrieb', color: '#88f', folders: ['data/rag/x'] }] });
    await s.klick(s.tog(s.sp('OPS')));
    const btn = s.doc.getElementById('wi-cfb-add');
    check('(Positivkontrolle) keine Gruppe vorbelegt', s.doc.querySelectorAll('#wi-cfb-groups input:checked').length === 0);
    check('⚠ markiert, aber ohne Gruppe: gesperrt, und der Grund nennt die GRUPPE',
          btn.disabled === true && /Wissensgruppe/.test(btn.title), btn.title);
    const g = s.doc.querySelector('#wi-cfb-groups input[value="g2"]');
    await s.klick(g);
    check('mit Gruppe frei', btn.disabled === false);
    await s.klick(btn);
    check('die gewaehlte Gruppe geht mit', JSON.stringify(s.posts()[0].body.groups) === '["g2"]');
    check('⚠ die Gruppenauswahl ueberlebt das Uebernehmen', s.doc.querySelector('#wi-cfb-groups input[value="g2"]').checked);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('9. Bearbeiten eines gespeicherten Eintrags');
{
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'e1', typ: 'auswahl', name: 'CONTOSO Dokumentation', gruppen: ['g1'],
          gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }],
          auswahl: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', start: false, ganz: false,
                      seiten: ['2', '3'], zweige: ['2'] }],
          abgleich: { zeit: '2026-09-27T10:05:00', seiten: 2, offen: 0, fehler: '' } }] } });
    const zeile = s.doc.querySelector('#wi-cfb-list .wi-item');
    check('die Zeile fasst die Auswahl zusammen', /CONTOSO: 2 Seite/.test(zeile.textContent), zeile.textContent);
    check('⚠ die Zeile nennt das Abgleichsergebnis', /Abgeglichen/.test(zeile.textContent) && /2 Seite/.test(zeile.textContent));
    check('Bearbeiten als Text, Loeschen als Muelleimer',
          zeile.querySelector('.wi-cfb-edit') && /Bearbeiten/.test(zeile.querySelector('.wi-cfb-edit').textContent)
          && zeile.querySelector('.wi-cfb-del .jv-ico-trash'));
    await s.klick(zeile.querySelector('.wi-cfb-edit'));
    await warten(60);
    const li = s.sp('CONTOSO');
    check('⚠ der Bereich steht aufgeklappt da', s.offen(li));
    check('⚠ die gespeicherten Haken stehen im Baum (2, 3), die uebrigen nicht',
          s.cb(s.pg('2')).checked && s.cb(s.pg('3')).checked && !s.cb(s.pg('1')).checked
          && !s.cb(s.pg('4')).checked && !s.cb(li).checked);
    const btn = s.doc.getElementById('wi-cfb-add');
    check('der Knopf heisst jetzt "Speichern"', /Speichern/.test(btn.textContent), btn.textContent);
    check('"Abbrechen" ist sichtbar', s.doc.getElementById('wi-cfb-cancel').style.display !== 'none');
    check('der Hinweis nennt den Eintrag', /CONTOSO Dokumentation/.test(s.doc.getElementById('wi-cfb-editnote').textContent));
    // Unterbereich hinzufuegen (Kapitel B), einen weiteren Bereich dazunehmen
    await s.klick(s.cb(s.pg('4')));
    await s.klick(s.tog(s.sp('OPS')));
    await s.klick(btn);
    const p = s.posts();
    check('⚠ Speichern ist EIN PUT auf den Eintrag (kein neuer Eintrag)',
          p.length === 1 && p[0].m === 'PUT' && p[0].pfad === '/api/wissen/confluence/bindung/e1',
          JSON.stringify(p.map(x => x.m + ' ' + x.pfad)));
    const aw = (p[0] && p[0].body.auswahl) || [];
    const a = (k) => aw.filter(x => x.key === k)[0] || {};
    check('⚠ hinzugefuegter Unterbereich ist dabei',
          JSON.stringify((a('CONTOSO').seiten || []).slice().sort()) === '["2","3","4"]', JSON.stringify(a('CONTOSO')));
    check('hinzugefuegter Bereich ist dabei (ganz)', a('OPS').ganz === true);
    check('nach dem Speichern: zurueck im Anlege-Modus',
          /Übernehmen/.test(btn.textContent) && s.doc.getElementById('wi-cfb-cancel').style.display === 'none');
    check('die Liste hat weiter EINEN Eintrag', s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 1);
    s.zu();
}
{
    // Abbrechen verwirft die Aenderung; Entfernen eines Bereichs im Bearbeiten
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'e1', typ: 'auswahl', name: 'X', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          auswahl: [{ key: 'CONTOSO', start: true, ganz: true, seiten: ['1', '2', '3', '4'], zweige: ['1', '2'] },
                    { key: 'OPS', start: true, ganz: false, seiten: [], zweige: [] }] }] } });
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    check('ganz gespeichert -> alles markiert',
          s.sp('CONTOSO').querySelectorAll('.wi-cfb-cb:checked').length === 5);
    check('start gespeichert -> der Bereich selbst markiert, Unterbereiche nicht',
          s.cb(s.sp('OPS')).checked && !s.cb(s.pg('10')).checked);
    await s.klick(s.cb(s.sp('OPS')));                 // OPS ab
    await s.klick(s.doc.getElementById('wi-cfb-cancel'));
    check('⚠ Abbrechen: nichts gespeichert', s.posts().length === 0);
    check('Abbrechen: Baum leer, Anlege-Modus',
          s.doc.querySelectorAll('#wi-cfb-tree .wi-cfb-cb:checked').length === 0
          && /Übernehmen/.test(s.doc.getElementById('wi-cfb-add').textContent));
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    await s.klick(s.tog(s.sp('CONTOSO')));              // [-] an CONTOSO: Unterbereiche weg
    await s.klick(s.cb(s.sp('CONTOSO')));               // und den Bereich selbst ab
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const aw = ((s.posts()[0] || {}).body || {}).auswahl || [];
    check('⚠ ein abgewaehlter Bereich faellt aus der Auswahl', aw.length === 1 && aw[0].key === 'OPS', JSON.stringify(aw));
    s.zu();
}
{
    // Seitenbaum nicht ladbar: die gespeicherte Auswahl dieses Bereichs bleibt erhalten
    const s = await seite({ pagesFehler: ['CONTOSO'], bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'e1', typ: 'auswahl', name: 'X', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          auswahl: [{ key: 'CONTOSO', start: false, ganz: false, seiten: ['2'], zweige: [] }] }] } });
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    check('der Ladefehler wird genannt (mit Bereich)',
          /nicht geladen/.test(s.doc.getElementById('wi-cfb-status').textContent)
          && /CONTOSO/.test(s.doc.getElementById('wi-cfb-status').textContent),
          s.doc.getElementById('wi-cfb-status').textContent);
    await s.klick(s.tog(s.sp('OPS')));
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const aw = ((s.posts()[0] || {}).body || {}).auswahl || [];
    check('⚠ nicht ladbarer Bereich: seine gespeicherte Auswahl geht UNVERAENDERT mit',
          aw.some(x => x.key === 'CONTOSO' && JSON.stringify(x.seiten) === '["2"]'), JSON.stringify(aw));
    check('genau EIN Speichern', s.posts().length === 1);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('10. Suche, Liste, Loeschen, Altbestand');
{
    const s = await seite();
    await s.klick(s.cb(s.sp('OPS')));
    const such = s.doc.getElementById('wi-cfb-such');
    such.value = 'contoso';
    such.dispatchEvent(new s.win.Event('input', { bubbles: true }));
    check('die Suche blendet nicht passende Bereiche aus', s.sp('LEER').style.display === 'none');
    check('passende bleiben', s.sp('CONTOSO').style.display !== 'none');
    check('⚠ ein markierter Bereich bleibt sichtbar, auch wenn er nicht passt',
          s.sp('OPS').style.display !== 'none');
    such.value = '';
    such.dispatchEvent(new s.win.Event('input', { bubbles: true }));
    check('leere Suche zeigt wieder alle', s.sp('LEER').style.display !== 'none');
    s.zu();
}
{
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'alt1', typ: 'space', key: 'CONTOSO', name: 'Alt', inkl_unter: true,
          auswahl: [{ key: 'CONTOSO', start: true, ganz: true, seiten: [], zweige: [] }],
          abgleich: { zeit: '2026-09-27T10:05:00', seiten: 0, offen: 0, fehler: 'keiner Wissensgruppe zugeordnet' } },
        { id: 'e2', typ: 'auswahl', name: 'Kaputt', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          auswahl: [{ key: 'OPS', start: true }],
          abgleich: { zeit: '2026-09-27T10:05:00', seiten: 3, offen: 2, fehler: 'Bereich OPS nicht erreichbar' } },
        { id: 'e3', typ: 'auswahl', name: 'Neu', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          auswahl: [{ key: 'OPS', start: true }] }] } });
    const z = s.doc.querySelectorAll('#wi-cfb-list .wi-item');
    check('⚠ Altbestand ohne Gruppe wird BENANNT', z[0] && z[0].querySelector('.wi-cfb-nogrp'));
    check('Altbestand: ganzer Bereich steht als Wort da', z[0] && /ganzer Bereich/.test(z[0].textContent));
    check('⚠ ein Abgleichsfehler steht in der Zeile (hervorgehoben)',
          z[1] && z[1].querySelector('.wi-cfb-sync.warn') && /nicht erreichbar/.test(z[1].textContent));
    check('offene Seiten werden genannt', z[1] && /2 folgen/.test(z[1].textContent));
    check('noch nie abgeglichen: das steht da', z[2] && /Noch nicht abgeglichen/.test(z[2].textContent));
    check('⚠ Altbestand mit Fehler und 0 Seiten: KEIN "Abgeglichen", nur der Grund',
          z[0] && !/Abgeglichen/.test(z[0].textContent) && /keiner Wissensgruppe/.test(z[0].querySelector('.wi-cfb-sync').textContent),
          z[0] ? z[0].textContent : '');
    await s.klick(z[2].querySelector('.wi-cfb-del'));
    const del = s.rufe.filter(r => r.m === 'DELETE');
    check('Muelleimer loescht genau diesen Eintrag',
          del.length === 1 && del[0].pfad === '/api/wissen/confluence/bindung/e3');
    check('und er ist aus der Liste', s.doc.querySelectorAll('#wi-cfb-list .wi-item').length === 2);
    s.zu();
}
{
    const s = await seite({ spaces: [{ key: 'Y', name: '<img src=x>', type: 'global' }],
        bindung: { ok: true, aktiv: true, bereiche: [
            { id: 'a', name: '<b>boese</b>', gruppen: [], auswahl: [{ key: 'Y', start: true }] }] } });
    check('⚠ Namen aus Confluence werden maskiert (Liste)',
          s.doc.querySelectorAll('#wi-cfb-list b').length === 0);
    check('⚠ und im Baum', s.doc.querySelectorAll('#wi-cfb-tree img').length === 0);
    s.zu();
}
{
    const s = await seite();
    s.win.setLang ? s.win.setLang('en') : (s.win.applyLang && s.win.applyLang('en'));
    await warten(40);
    const h = s.doc.querySelector('#wi-sec-cfbind h2');
    check('Sprachwechsel erreicht die Ueberschrift', /Dynamic Confluence binding/.test(h.textContent));
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('11. Tags (Vorgabe 2026-09-27)');
{
    const s = await seite();
    const inp = s.doc.getElementById('wi-cfb-tags');
    const baum = s.doc.getElementById('wi-cfb-tree');
    check('(Positivkontrolle) Tag-Feld und Baum sind da', !!inp && !!baum);
    check('das Tag-Feld liegt IN der Einbindung',
          !!inp && !!inp.closest('#wi-sec-cfbind'));
    check('⚠ und VOR dem Baum (alles, was „Übernehmen" mitnimmt, steht davor)',
          !!inp && !!baum && !!(inp.compareDocumentPosition(baum) & s.win.Node.DOCUMENT_POSITION_FOLLOWING));
    const lab = s.doc.querySelector('label[for="wi-cfb-tags"]');
    check('das Feld hat eine Beschriftung mit i18n',
          !!lab && lab.getAttribute('data-i18n') === 'wissen.cfb_tags_label');
    check('der Platzhalter hat i18n', inp && inp.getAttribute('data-i18n-placeholder') === 'wissen.cfb_tags_ph');

    /* ⚠ KEIN \n: ein <input type=text> entfernt Zeilenumbrueche aus `value`
       (Wertbereinigung laut HTML-Standard) - "#intern\nneu" wird "#internneu".
       Ein Tab ist Leerraum und bleibt stehen. */
    inp.value = 'Handbuch, freigegeben;  #intern\tneu';
    await s.klick(s.tog(s.sp('OPS')));
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const b = (s.posts()[0] || {}).body || {};
    check('⚠ die Tags gehen mit dem Rumpf raus – zerlegt an Komma, Semikolon und Leerraum',
          JSON.stringify(b.tags) === JSON.stringify(['Handbuch', 'freigegeben', '#intern', 'neu']),
          JSON.stringify(b.tags));
    check('Auswahl und Gruppen gehen weiterhin mit',
          (b.auswahl || []).length === 1 && JSON.stringify(b.groups) === '["g1"]', JSON.stringify(b));
    check('⚠ nach dem Übernehmen ist das Tag-Feld leer (der nächste Eintrag erbt nichts)',
          inp.value === '', inp.value);
    const z = s.doc.querySelectorAll('#wi-cfb-list .wi-item');
    const sum = z[0] && z[0].querySelector('.wi-cfb-tagsum');
    check('⚠ die Liste nennt die Tags des Eintrags',
          !!sum && /handbuch, freigegeben, intern, neu/.test(sum.textContent), sum ? sum.textContent : '');

    await s.klick(s.tog(s.sp('CONTOSO')));
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const b2 = (s.posts()[1] || {}).body || {};
    check('⚠ leeres Tag-Feld = leere Liste (kein Filter)',
          Array.isArray(b2.tags) && b2.tags.length === 0, JSON.stringify(b2.tags));
    const z2 = s.doc.querySelectorAll('#wi-cfb-list .wi-item');
    check('ein Eintrag ohne Tags zeigt keine Tag-Zeile',
          z2.length === 2 && !z2[1].querySelector('.wi-cfb-tagsum'));
    s.zu();
}
{
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'e1', typ: 'auswahl', name: 'X', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          tags: ['handbuch', 'freigegeben'],
          auswahl: [{ key: 'OPS', start: true, ganz: false, seiten: [], zweige: [] }] }] } });
    const inp = s.doc.getElementById('wi-cfb-tags');
    check('(Positivkontrolle) Feld leer vor dem Bearbeiten', inp.value === '');
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    check('⚠ Bearbeiten füllt die gespeicherten Tags ein', inp.value === 'handbuch, freigegeben', inp.value);
    await s.klick(s.doc.getElementById('wi-cfb-cancel'));
    check('⚠ Abbrechen leert das Tag-Feld wieder', inp.value === '', inp.value);
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    inp.value = 'handbuch';
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const put = s.rufe.filter(r => r.m === 'PUT');
    check('⚠ geänderte Tags gehen per PUT auf den Eintrag',
          put.length === 1 && put[0].pfad === '/api/wissen/confluence/bindung/e1'
          && JSON.stringify(put[0].body.tags) === '["handbuch"]', JSON.stringify(put.map(x => x.body)));
    await s.klick(s.doc.querySelector('#wi-cfb-list .wi-cfb-edit'));
    await warten(60);
    inp.value = '';
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const put2 = s.rufe.filter(r => r.m === 'PUT');
    check('⚠ alle Tags entfernt: PUT schickt die leere Liste (Filter aufgehoben)',
          put2.length === 2 && JSON.stringify(put2[1].body.tags) === '[]', JSON.stringify(put2.map(x => x.body.tags)));
    const z = s.doc.querySelectorAll('#wi-cfb-list .wi-item');
    check('und die Liste zeigt danach keine Tag-Zeile mehr', z.length === 1 && !z[0].querySelector('.wi-cfb-tagsum'));
    s.zu();
}
{
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [
        { id: 'e1', typ: 'auswahl', name: 'X', gruppen: ['g1'], gruppen_info: [{ id: 'g1', name: 'Technik' }],
          tags: ['<img src=x>'], auswahl: [{ key: 'OPS', start: true }] }] } });
    check('⚠ Tags werden in der Liste maskiert', s.doc.querySelectorAll('#wi-cfb-list img').length === 0);
    s.win.setLang ? s.win.setLang('en') : (s.win.applyLang && s.win.applyLang('en'));
    await warten(40);
    check('Sprachwechsel erreicht die Tag-Beschriftung und den Hinweis',
          /Tags \(optional\)/.test(s.doc.querySelector('label[for="wi-cfb-tags"]').textContent)
          && /Only pages carrying/.test(s.doc.querySelector('[data-i18n="wissen.cfb_tags_hint"]').textContent));
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('12. Ort des Editors – beim Bearbeiten IN der Box des Eintrags (Vorgabe 2026-09-27)');
{
    const E = (id, name) => ({ id: id, typ: 'auswahl', name: name, gruppen: ['g1'],
        gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }],
        auswahl: [{ key: id === 'e1' ? 'CONTOSO' : 'OPS', start: true, ganz: false, seiten: [], zweige: [] }] });
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [E('e1', 'Eins'), E('e2', 'Zwei')] } });
    const d = s.doc;
    const ed = () => d.getElementById('wi-cfb-editor');
    const zeile = (id) => d.querySelector('#wi-cfb-list .wi-item[data-id="' + id + '"]');
    const geparkt = () => !!ed() && ed().nextElementSibling === d.getElementById('wi-cfb-list')
        && !ed().closest('.wi-item') && !d.querySelector('.wi-item.wi-cfb-editing');
    const inBox = (id) => !!ed() && ed().parentNode === zeile(id)
        && zeile(id).classList.contains('wi-cfb-editing')
        && d.querySelectorAll('.wi-item.wi-cfb-editing').length === 1;
    // Positivkontrolle: ohne Editor-Huelle waeren alle Ortspruefungen trivial
    // Die Statuszeile gehoert NICHT dazu: sie wandert beim Schliessen unter
    // "Neuer Bereich" (Abschnitt 13) und steht nur im OFFENEN Editor darin.
    check('(Positivkontrolle) Editor-Huelle vorhanden und enthaelt Gruppen, Tags, Baum, Knopf',
          !!ed() && ['wi-cfb-groups', 'wi-cfb-tags', 'wi-cfb-tree', 'wi-cfb-add', 'wi-cfb-cancel']
              .every(id => ed().contains(d.getElementById(id))));
    check('(Positivkontrolle) zwei Eintraege in der Liste', !!zeile('e1') && !!zeile('e2'));
    check('Neuanlage: Editor steht OBERHALB der Liste, in keiner Box', geparkt());

    await s.klick(zeile('e1').querySelector('.wi-cfb-edit'));
    await warten(60);
    check('⚠ Bearbeiten e1: Editor steht IN der Box von e1', inBox('e1'));
    check('... und die Statuszeile steht im offenen Editor', ed().contains(d.getElementById('wi-cfb-status')));
    check('der Baum wandert mit (keine Kopie)', d.querySelectorAll('#wi-cfb-tree').length === 1
          && zeile('e1').contains(d.getElementById('wi-cfb-tree')));
    check('der Editor steht NACH der Kopfzeile der Box',
          zeile('e1').lastElementChild === ed());

    await s.klick(zeile('e2').querySelector('.wi-cfb-edit'));
    await warten(60);
    check('⚠ Wechsel auf e2: Editor wandert in die Box von e2, e1 ist frei', inBox('e2') && !zeile('e1').contains(ed()));
    check('e2: seine Haken stehen (OPS markiert)', s.cb(s.sp('OPS')).checked && !s.cb(s.sp('CONTOSO')).checked);

    // Anderen Eintrag loeschen -> Liste wird neu gezeichnet; Editor + Haken bleiben
    await s.klick(s.cb(s.pg('11')));
    await s.klick(zeile('e1').querySelector('.wi-cfb-del'));
    await warten(40);
    check('⚠ Loeschen eines ANDEREN Eintrags: Editor bleibt in der Box von e2', !zeile('e1') && inBox('e2'));
    check('⚠ ... und die laufende Markierung ueberlebt das Neuzeichnen', s.cb(s.pg('11')) && s.cb(s.pg('11')).checked);
    check('... Bearbeiten laeuft weiter', /Speichern/.test(d.getElementById('wi-cfb-add').textContent));

    await s.klick(d.getElementById('wi-cfb-cancel'));
    check('⚠ Abbrechen: Editor zurueck oberhalb der Liste', geparkt());

    await s.klick(zeile('e2').querySelector('.wi-cfb-edit'));
    await warten(60);
    await s.klick(d.getElementById('wi-cfb-add'));
    await warten(40);
    check('(Positivkontrolle) Speichern lief als PUT', s.posts().some(x => x.m === 'PUT'));
    check('⚠ nach dem Speichern: Editor zurueck oberhalb der Liste, Baum lebt',
          geparkt() && !!d.querySelector('#wi-cfb-tree li.wi-cfb-sp'));

    await s.klick(zeile('e2').querySelector('.wi-cfb-edit'));
    await warten(60);
    await s.klick(zeile('e2').querySelector('.wi-cfb-del'));
    await warten(40);
    check('⚠ bearbeiteten Eintrag geloescht: Editor oberhalb der Liste, Anlege-Modus',
          geparkt() && /Übernehmen/.test(d.getElementById('wi-cfb-add').textContent)
          && !!d.getElementById('wi-cfb-tree'));
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('13. Editor nur bei "Neuer Bereich" oder "Bearbeiten" (Vorgabe 2026-09-28)');
{
    const E = { id: 'e1', typ: 'auswahl', name: 'Eins', gruppen: ['g1'],
        gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }],
        auswahl: [{ key: 'CONTOSO', start: true, ganz: false, seiten: [], zweige: [] }] };
    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: [E] } });
    const d = s.doc;
    // Sichtbar = kein Vorfahr (bis zum Abschnitt) mit display:none. jsdom
    // rechnet kein Layout - gemessen wird die Kette der display-Werte.
    const sichtbar = (el) => {
        for (let x = el; x && x !== d.body; x = x.parentElement) {
            if (x.style && x.style.display === 'none') return false;
        }
        return !!el;
    };
    const ed = d.getElementById('wi-cfb-editor');
    const neu = d.getElementById('wi-cfb-new');
    const st = () => d.getElementById('wi-cfb-status');
    const felder = ['wi-cfb-groups', 'wi-cfb-tags', 'wi-cfb-such', 'wi-cfb-tree', 'wi-cfb-add'];
    const keinesSichtbar = () => felder.every(id => !sichtbar(d.getElementById(id)));
    const alleSichtbar = () => felder.every(id => sichtbar(d.getElementById(id)));
    check('(Positivkontrolle) Abschnitt sichtbar, Editor und Knopf vorhanden',
          sichtbar(d.getElementById('wi-sec-cfbind')) && !!ed && !!neu);
    check('⚠ Grundzustand: Gruppen, Tags, Suche, Baum, Übernehmen NICHT sichtbar', keinesSichtbar());
    check('Grundzustand: "Neuer Bereich" sichtbar, beschriftet',
          sichtbar(neu) && /Neuer Bereich/.test(neu.textContent), neu && neu.textContent);
    check('Grundzustand: die Liste ist sichtbar', sichtbar(d.querySelector('#wi-cfb-list .wi-item')));

    await s.klick(neu);
    check('⚠ "Neuer Bereich": Editor offen, alle Felder sichtbar', alleSichtbar());
    check('"Neuer Bereich": der Knopf selbst ist weg, "Abbrechen" da',
          !sichtbar(neu) && sichtbar(d.getElementById('wi-cfb-cancel')));
    check('"Neuer Bereich": Anlege-Modus ("Übernehmen")', /Übernehmen/.test(d.getElementById('wi-cfb-add').textContent));
    check('"Neuer Bereich": Statuszeile im Editor', ed.contains(st()));

    await s.klick(d.getElementById('wi-cfb-cancel'));
    check('⚠ Abbrechen der Neuanlage: Editor wieder zu', keinesSichtbar() && sichtbar(neu));

    await s.klick(neu);
    await s.klick(s.tog(s.sp('OPS')));
    await s.klick(d.getElementById('wi-cfb-add'));
    await warten(40);
    check('(Positivkontrolle) Übernehmen lief als POST',
          s.posts().some(x => x.m === 'POST' && x.pfad === '/api/wissen/confluence/bindung'));
    check('⚠ nach dem Übernehmen: Editor zu', keinesSichtbar() && sichtbar(neu));
    check('⚠ ... und die Erfolgsmeldung bleibt SICHTBAR (unter "Neuer Bereich")',
          sichtbar(st()) && !ed.contains(st()) && /✓/.test(st().textContent), st().textContent);

    await s.klick(d.querySelector('#wi-cfb-list .wi-item[data-id="e1"] .wi-cfb-edit'));
    await warten(60);
    check('⚠ "Bearbeiten": Editor offen in der Box, alle Felder sichtbar',
          alleSichtbar() && !!ed.closest('.wi-item'));
    check('"Bearbeiten": "Neuer Bereich" bleibt erreichbar', sichtbar(neu));
    await s.klick(d.getElementById('wi-cfb-cancel'));
    check('⚠ Abbrechen des Bearbeitens: Editor wieder zu', keinesSichtbar());

    await s.klick(d.querySelector('#wi-cfb-list .wi-item[data-id="e1"] .wi-cfb-edit'));
    await warten(60);
    await s.klick(neu);
    check('"Neuer Bereich" waehrend des Bearbeitens: Anlege-Modus, Editor oberhalb der Liste',
          alleSichtbar() && !ed.closest('.wi-item') && /Übernehmen/.test(d.getElementById('wi-cfb-add').textContent)
          && d.querySelectorAll('#wi-cfb-tree .wi-cfb-cb:checked').length === 0);
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('Einbindung fremder Wissensgruppen: KEINE Knoepfe (Code-Review 2026-09-28)');
{
    // ⚠ Der Server weist Aendern/Loeschen fremder Einbindungen mit 403 ab und
    // liefert je Eintrag `darf_aendern` (dieselbe Regel). Die Oberflaeche soll
    // keinen Knopf anbieten, der garantiert scheitert. `=== false`: ein
    // aelteres Backend ohne das Feld behaelt die Knoepfe.
    const ein = (id, darf) => Object.assign({
        id: id, typ: 'auswahl', name: 'CONTOSO Dokumentation',
        auswahl: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', start: true, ganz: false, seiten: [], zweige: [] }],
        gruppen: ['g1'], tags: [], gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }], abgleich: null },
        darf === undefined ? {} : { darf_aendern: darf });
    const s = await seite({ bindung: { ok: true, aktiv: true,
        bereiche: [ein('eigen', true), ein('fremd', false), ein('alt')] } });
    const zeile = (id) => s.doc.querySelector('#wi-cfb-list .wi-item[data-id="' + id + '"]');
    check('(Positivkontrolle) alle drei Zeilen stehen da',
          !!zeile('eigen') && !!zeile('fremd') && !!zeile('alt'));
    const hat = (id, sel) => !!(zeile(id) && zeile(id).querySelector(sel));
    check('eigene Einbindung: Bearbeiten und Muelleimer', hat('eigen', '.wi-cfb-edit') && hat('eigen', '.wi-cfb-del'));
    check('⚠ fremde Einbindung: KEIN Bearbeiten', !hat('fremd', '.wi-cfb-edit'));
    check('⚠ fremde Einbindung: KEIN Muelleimer', !hat('fremd', '.wi-cfb-del'));
    const hw = zeile('fremd') && zeile('fremd').querySelector('.wi-cfb-fremd');
    check('…stattdessen ein Hinweis mit Text und Erklaerung',
          !!hw && /andere Wissensgruppe/.test(hw.textContent) && /außerhalb deines Bereichs/.test(hw.getAttribute('title') || ''),
          hw ? hw.outerHTML : 'fehlt');
    check('Feld fehlt (aelteres Backend): Knoepfe bleiben', hat('alt', '.wi-cfb-edit') && hat('alt', '.wi-cfb-del'));
    check('die Knoepfe der eigenen Zeile funktionieren weiter (Loeschen)', await (async () => {
        await s.klick(zeile('eigen').querySelector('.wi-cfb-del'));
        await warten(40);
        return s.rufe.some(r => r.m === 'DELETE' && /\/eigen$/.test(r.pfad));
    })());
    s.zu();
}

// ════════════════════════════════════════════════════════════════════════
section('14. Datum des letzten Imports hinter [+]/[-] bzw. der Zeile (Vorgabe 2026-09-28)');
{
    const IMP = '2026-09-28T20:15:00', IMP3 = '2026-09-27T08:00:00';
    const pages = JSON.parse(JSON.stringify(PAGES));
    pages.CONTOSO[0].importiert = IMP;      // 1 Handbuch (mit Unterseiten)
    pages.CONTOSO[2].importiert = IMP3;     // 3 Kapitel A.1 (Blatt)
    const ein = { id: 'e1', typ: 'auswahl', name: 'CONTOSO Dokumentation',
        auswahl: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', start: false, ganz: false, seiten: ['1', '3'], zweige: [] }],
        gruppen: ['g1'], tags: [], gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }], abgleich: null };
    const s = await seite({ pages: pages, bindung: { ok: true, aktiv: true, bereiche: [ein],
                                                     importe: { CONTOSO: IMP } } });
    const d = s.doc;
    const tag = (iso) => new s.win.Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' });
    const imp = (li) => { const n = li && li.querySelector(':scope > .wi-cf-node'); return n ? n.querySelector(':scope > .wi-cfb-imp') : null; };
    const letztes = (li) => { const n = li && li.querySelector(':scope > .wi-cf-node'); return n ? n.lastElementChild : null; };
    const nx = s.sp('CONTOSO');
    check('(Positivkontrolle) Bereich CONTOSO steht im Baum, mit [+]', !!nx && !!s.tog(nx));
    const i0 = imp(nx);
    check('⚠ importierter Bereich: Datum in Klammern', !!i0 && i0.textContent === '(' + tag(IMP) + ')',
          i0 ? i0.textContent : 'fehlt');
    check('⚠ …HINTER [+] (letztes Element der Zeile)', i0 && letztes(nx) === i0
          && (s.tog(nx).compareDocumentPosition(i0) & s.win.Node.DOCUMENT_POSITION_FOLLOWING));
    check('Tooltip nennt Datum und Uhrzeit', i0 && /Zuletzt ins Wissen übernommen: /.test(i0.getAttribute('title') || '')
          && /2026/.test(i0.getAttribute('title')), i0 ? i0.getAttribute('title') : '');
    check('⚠ nicht importierter Bereich: KEIN Datum', !imp(s.sp('OPS')) && !imp(s.sp('LEER')));

    await s.klick(s.nm(nx));
    await warten(40);
    const p1 = s.pg('1'), p2 = s.pg('2'), p3 = s.pg('3');
    check('(Positivkontrolle) Seiten geladen', !!p1 && !!p2 && !!p3);
    const i1 = imp(p1);
    check('⚠ importierte Seite MIT Unterseiten: Datum hinter [+]',
          !!i1 && i1.textContent === '(' + tag(IMP) + ')' && letztes(p1) === i1
          && (s.tog(p1).compareDocumentPosition(i1) & s.win.Node.DOCUMENT_POSITION_FOLLOWING),
          p1 ? p1.querySelector('.wi-cf-node').innerHTML : 'fehlt');
    const i3 = imp(p3);
    check('⚠ importierte Seite OHNE Unterseiten: Datum am Ende der Zeile (hinter dem Namen)',
          !!i3 && i3.textContent === '(' + tag(IMP3) + ')' && letztes(p3) === i3 && !s.tog(p3),
          p3 ? p3.querySelector('.wi-cf-node').innerHTML : 'fehlt');
    check('⚠ nicht importierte Seite: KEIN Datum', !imp(p2) && !imp(s.pg('4')));

    await s.klick(s.tog(nx));   // [-]? der Bereich ist offen -> zu
    await s.klick(s.tog(nx));   // [+] wieder auf
    check('[+]/[-] umschalten laesst das Datum stehen (genau eines, weiter hinten)',
          nx.querySelectorAll(':scope > .wi-cf-node > .wi-cfb-imp').length === 1 && letztes(nx) === imp(nx)
          && /\[[-+]\]/.test(s.tog(nx).textContent), s.tog(nx).textContent);

    // Nach dem Loeschen zeichnet cfbRender() erneut: das Datum der Bereichszeile
    // darf dabei nicht verdoppelt werden (die Zeile selbst bleibt stehen).
    await s.klick(d.querySelector('#wi-cfb-list .wi-item[data-id="e1"] .wi-cfb-del'));
    await warten(60);
    check('(Positivkontrolle) Loeschen lief, die Liste wurde neu gezeichnet',
          s.rufe.some(r => r.m === 'DELETE') && !d.querySelector('#wi-cfb-list .wi-item[data-id="e1"]'));
    check('⚠ erneutes Zeichnen: das Datum steht GENAU EINMAL da',
          nx.querySelectorAll(':scope > .wi-cf-node > .wi-cfb-imp').length === 1,
          String(nx.querySelectorAll('.wi-cfb-imp').length));
    s.zu();
}

section('13. Wettlauf: schneller Wechsel zwischen Eintraegen (Code-Review 2026-10-07)');
/* "Bearbeiten" bei A, dessen Seitenbaum langsam laedt, dann sofort bei B: As
   spaete Antwort setzte ihre Haken in Bs Editor, und Bs PUT trug As Seiten. */
{
    const bereiche = () => [
        { id: 'e1', typ: 'auswahl', name: 'CONTOSO Dokumentation', gruppen: ['g1'],
          gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }],
          auswahl: [{ key: 'CONTOSO', name: 'CONTOSO Dokumentation', start: false, ganz: false,
                      seiten: ['2', '3'], zweige: [] }], abgleich: null },
        { id: 'e2', typ: 'auswahl', name: 'Betrieb', gruppen: ['g1'],
          gruppen_info: [{ id: 'g1', name: 'Technik', color: '#888' }],
          auswahl: [{ key: 'OPS', name: 'Betrieb', start: true, ganz: false, seiten: [], zweige: [] }],
          abgleich: null }];
    const knopf = (s, id) => s.doc.querySelector('#wi-cfb-list .wi-item[data-id="' + id + '"] .wi-cfb-edit');

    // Positivkontrolle: OHNE Wechsel kommen die Haken trotz Verzoegerung an
    const k = await seite({ bindung: { ok: true, aktiv: true, bereiche: bereiche() },
                            pagesVerzoegerung: { CONTOSO: 120 } });
    knopf(k, 'e1').click();
    await warten(250);
    check('Positivkontrolle: langsamer Baum ohne Wechsel -> Haken 2, 3 stehen',
          k.pg('2') && k.cb(k.pg('2')).checked && k.cb(k.pg('3')).checked);
    k.zu();

    const s = await seite({ bindung: { ok: true, aktiv: true, bereiche: bereiche() },
                            pagesVerzoegerung: { CONTOSO: 120 } });
    knopf(s, 'e1').click();
    await warten(20);                       // CONTOSO laedt noch
    knopf(s, 'e2').click();
    await warten(250);                      // jetzt kommt die spaete Antwort
    const nx = s.sp('CONTOSO');
    const haken = ['1', '2', '3', '4'].filter(id => s.pg(id) && s.cb(s.pg(id)).checked);
    check('⚠ As spaete Antwort setzt KEINE Haken in Bs Editor', haken.length === 0, haken.join(','));
    check('⚠ … und klappt As Bereich nicht auf', !s.offen(nx));
    check('Positivkontrolle: Bs eigener Haken (OPS) steht', s.cb(s.sp('OPS')).checked);
    await s.klick(s.doc.getElementById('wi-cfb-add'));
    const p = s.posts();
    const keys = ((p[0] && p[0].body.auswahl) || []).map(a => a.key);
    check('⚠ Bs PUT traegt nur OPS, keine CONTOSO-Seiten',
          p.length === 1 && p[0].pfad === '/api/wissen/confluence/bindung/e2'
          && JSON.stringify(keys) === '["OPS"]', JSON.stringify(p.map(x => [x.pfad, x.body && x.body.auswahl])));
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
