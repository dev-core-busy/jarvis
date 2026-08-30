/* UI-Waechter: der Benutzer loescht EINZELNE Verlaufseintraege (2026-08-30).
 *
 * Vorher liess sich der Verlauf nur GANZ leeren ("Leeren"). Wer einen
 * Tippfehler oder eine einmalige Anfrage loswerden wollte, musste alles
 * wegwerfen – oder es blieb stehen.
 *
 * ES LAEUFT DER ECHTE CODE gegen die ECHTEN Seiten (jsdom): geprueft wird,
 * was sich am Quelltext NICHT ablesen laesst –
 *   1. jeder Eintrag traegt einen MUELLEIMER (SVG aus icons.js, kein x)
 *   2. der Klick loescht GENAU DIESEN Eintrag, die anderen bleiben in Ordnung
 *   3. der Klick loest NICHT die Zeile darunter aus (die uebernaehme die
 *      Analyse ins Formular bzw. startete in /support sofort eine Suche)
 *   4. DAS VERLAUFSFELD BLEIBT OFFEN – der Dokument-Listener schliesst es,
 *      sobald der Klick an ihm ankommt und die geloeschte Zeile nicht mehr im
 *      Panel haengt. Genau dafuer ist das stopPropagation da.
 *   5. ist der letzte Eintrag weg, steht der Leer-Text da
 *   6. /support: der Benutzer steht NICHT im Rumpf (er kommt aus der Anmeldung)
 *
 * WICHTIG (Fallstrick 2026-07-30): am Ende window.close() + process.exit(),
 * sonst haelt der 30-Sekunden-Timer der LLM-Anzeige den Prozess offen.
 *
 * Lauf:  JSDOM_PATH=jsdom timeout 120 node tests/test_verlauf_loeschen_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

// Zeichen, die faelschlich fuer "loeschen" stehen koennten – dieselbe Liste wie
// in test_icon_semantik.js, samt `u`-Flag (ohne das zerlegt die Zeichenklasse
// 🗙 in Surrogate und matcht dann jedes beliebige Emoji).
const KREUZE = /[×✕✖⨯🗙]|&times;|&#215;|&#10005;/u;

function baueDom(htmlFile, url, fetchMock, vorbereiten) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', htmlFile), 'utf8');
    const vc = new VirtualConsole();
    const navs = [];
    vc.on('jsdomError', (e) => {
        if (/Not implemented: navigation/.test(e.message || '')) navs.push(e.message);
    });
    const dom = new JSDOM(html, {
        url: 'https://localhost' + url,
        runScripts: 'dangerously',
        virtualConsole: vc,
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.HTMLCanvasElement.prototype.getContext = () => null;
            if (vorbereiten) vorbereiten(win);
            win.fetch = fetchMock(win);
        },
    });
    dom.__navs = navs;
    return dom;
}
function json(data, status) {
    return Promise.resolve({
        ok: (status || 200) < 400, status: status || 200,
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(JSON.stringify(data)),
    });
}
function ladeSkript(dom, rel) {
    dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend', rel), 'utf8'));
}

// ── Testdaten: drei Eintraege, der MITTLERE wird geloescht ──────────
const TS = [1756500000000, 1756510000000, 1756520000000];

(async () => {

// ════════════════════════════════════════════════════════════════════
// 1. /sap – Verlauf im localStorage
// ════════════════════════════════════════════════════════════════════
section('1. /sap – Muelleimer am Verlaufseintrag');
{
    const KAT = {
        lang: 'de',
        categories: [{ id: 'fi', title: 'Finanzen' }],
        analyses: [{ id: 'a1', cat: 'fi', title: 'Analyse Eins', desc: 'x', kpis: [], sources: '' },
                   { id: 'a2', cat: 'fi', title: 'Analyse Zwei', desc: 'y', kpis: [], sources: '' },
                   { id: 'a3', cat: 'fi', title: 'Analyse Drei', desc: 'z', kpis: [], sources: '' }],
        bi_tools: [{ id: 'inline', name: 'Jarvis', iface: null }],
    };
    let askAufrufe = 0;
    const dom = baueDom('sap.html', '/sap',
        () => (url, init) => {
            const u = String(url);
            if (u.startsWith('/api/me')) return json({ username: 'anna', is_admin: false,
                                                       permissions: { sap: true } });
            if (u.startsWith('/api/sap/analyses')) return json(KAT);
            if (u.startsWith('/api/sap/ask')) { askAufrufe++; return json({ ok: true, answer: 'x' }); }
            if (u.startsWith('/api/sap/status')) return json({ ok: true, configured: true });
            return json({ ok: true });
        },
        (win) => {
            win.localStorage.setItem('jarvis_sap_history', JSON.stringify([
                { id: 'a3', title: 'Analyse Drei', q: 'frage drei', tool: 'inline', ts: TS[2] },
                { id: 'a2', title: 'Analyse Zwei', q: 'frage zwei', tool: 'inline', ts: TS[1] },
                { id: 'a1', title: 'Analyse Eins', q: 'frage eins', tool: 'inline', ts: TS[0] },
            ]));
        });
    ladeSkript(dom, 'js/icons.js');
    ladeSkript(dom, 'js/i18n.js');
    ladeSkript(dom, 'js/chatlib.js');
    ladeSkript(dom, 'js/sap_portal.js');
    await sleep(140);
    const w = dom.window, dc = w.document;
    dc.getElementById('sp-hist-btn').click();
    await sleep(20);

    const zeilen = dc.querySelectorAll('#sp-hist-list .sp-hist-item');
    check('drei Verlaufseintraege gezeichnet', zeilen.length === 3, 'gefunden: ' + zeilen.length);
    const knoepfe = dc.querySelectorAll('#sp-hist-list .sp-hist-del');
    check('jeder Eintrag traegt einen Loeschknopf', knoepfe.length === 3,
          'gefunden: ' + knoepfe.length);
    check('der Knopf traegt den Muelleimer aus icons.js',
          knoepfe.length > 0 && /jv-ico-trash/.test(knoepfe[0].innerHTML));
    check('und KEIN x (Symbol-Semantik)',
          knoepfe.length > 0 && !KREUZE.test(knoepfe[0].innerHTML + knoepfe[0].textContent));
    check('der Knopf ist beschriftet (title + aria-label)',
          knoepfe.length > 0 && !!knoepfe[0].title && !!knoepfe[0].getAttribute('aria-label'));
    check('...und die Beschriftung kommt aus i18n (nicht der Rueckfalltext)',
          knoepfe.length > 0 && knoepfe[0].title === w.t('sup.hist_del'),
          knoepfe.length ? knoepfe[0].title : '');
    check('der Knopf liegt IM Eintrag (eine Zeile, kein zweiter Block)',
          knoepfe.length > 0 && knoepfe[0].parentElement === zeilen[0]);

    // ── der eigentliche Klick ──
    const vorher = dc.getElementById('sp-analysis').value;
    knoepfe[1].click();
    await sleep(40);
    let liste = JSON.parse(w.localStorage.getItem('jarvis_sap_history'));
    check('ein Eintrag weniger im Speicher', liste.length === 2, 'jetzt: ' + liste.length);
    check('geloescht wurde der ANGEKLICKTE Eintrag',
          !liste.some((e) => e.ts === TS[1]));
    check('die anderen beiden stehen unveraendert da',
          liste[0].ts === TS[2] && liste[1].ts === TS[0],
          JSON.stringify(liste.map((e) => e.ts)));
    check('die Liste zeigt nur noch zwei Zeilen',
          dc.querySelectorAll('#sp-hist-list .sp-hist-item').length === 2);
    check('der Klick hat die Analyse NICHT uebernommen',
          dc.getElementById('sp-analysis').value === vorher,
          dc.getElementById('sp-analysis').value);
    check('...und keine Auswertung gestartet', askAufrufe === 0);
    check('DAS VERLAUFSFELD BLEIBT OFFEN',
          !dc.getElementById('sp-hist-panel').classList.contains('hidden'));

    // ── bis zum letzten Eintrag ──
    dc.querySelectorAll('#sp-hist-list .sp-hist-del')[0].click();
    await sleep(30);
    dc.querySelectorAll('#sp-hist-list .sp-hist-del')[0].click();
    await sleep(30);
    liste = JSON.parse(w.localStorage.getItem('jarvis_sap_history'));
    check('alle Eintraege einzeln loeschbar', liste.length === 0, JSON.stringify(liste));
    check('danach steht der Leer-Text da',
          !!dc.querySelector('#sp-hist-list .sp-hist-empty'));
    check('das Verlaufsfeld ist immer noch offen',
          !dc.getElementById('sp-hist-panel').classList.contains('hidden'));
    w.close();
}

// ════════════════════════════════════════════════════════════════════
// 2. /vemas – gleiche Bauart, eigener Speicher
// ════════════════════════════════════════════════════════════════════
section('2. /vemas – Muelleimer am Verlaufseintrag');
{
    const KAT = {
        lang: 'de',
        categories: [{ id: 'c1', title: 'Projekte' }],
        analyses: [{ id: 'p1', cat: 'c1', title: 'Projektliste', desc: 'x' },
                   { id: 'p2', cat: 'c1', title: 'Zeiten', desc: 'y' }],
        tools: [{ id: 'inline', name: 'Jarvis', iface: null }],
    };
    let askAufrufe = 0;
    const dom = baueDom('vemas.html', '/vemas',
        () => (url) => {
            const u = String(url);
            if (u.startsWith('/api/me')) return json({ username: 'anna', is_admin: false,
                                                       permissions: { vemas: true } });
            if (u.startsWith('/api/vemas/analyses')) return json(KAT);
            if (u.startsWith('/api/vemas/ask')) { askAufrufe++; return json({ ok: true, answer: 'x' }); }
            return json({ ok: true });
        },
        (win) => {
            win.localStorage.setItem('jarvis_vemas_history', JSON.stringify([
                { id: 'p2', title: 'Zeiten', q: 'frage zwei', tool: 'inline', ts: TS[2] },
                { id: 'p1', title: 'Projektliste', q: 'frage eins', tool: 'inline', ts: TS[1] },
            ]));
        });
    ladeSkript(dom, 'js/icons.js');
    ladeSkript(dom, 'js/i18n.js');
    ladeSkript(dom, 'js/chatlib.js');
    ladeSkript(dom, 'js/vemas_portal.js');
    await sleep(140);
    const w = dom.window, dc = w.document;
    dc.getElementById('vm-hist-btn').click();
    await sleep(20);

    const knoepfe = dc.querySelectorAll('#vm-hist-list .vm-hist-del');
    check('jeder Eintrag traegt einen Loeschknopf', knoepfe.length === 2,
          'gefunden: ' + knoepfe.length);
    check('der Knopf traegt den Muelleimer aus icons.js',
          knoepfe.length > 0 && /jv-ico-trash/.test(knoepfe[0].innerHTML));
    check('und KEIN x (Symbol-Semantik)',
          knoepfe.length > 0 && !KREUZE.test(knoepfe[0].innerHTML + knoepfe[0].textContent));
    check('der Knopf ist beschriftet', knoepfe.length > 0 && !!knoepfe[0].title);

    const vorher = dc.getElementById('vm-analysis').value;
    knoepfe[1].click();
    await sleep(40);
    const liste = JSON.parse(w.localStorage.getItem('jarvis_vemas_history'));
    check('ein Eintrag weniger im Speicher', liste.length === 1, 'jetzt: ' + liste.length);
    check('geloescht wurde der ANGEKLICKTE Eintrag', liste[0].ts === TS[2]);
    check('der Klick hat die Auswertung NICHT uebernommen',
          dc.getElementById('vm-analysis').value === vorher);
    check('...und keine Auswertung gestartet', askAufrufe === 0);
    check('DAS VERLAUFSFELD BLEIBT OFFEN',
          !dc.getElementById('vm-hist-panel').classList.contains('hidden'));
    w.close();
}

// ════════════════════════════════════════════════════════════════════
// 3. /support – der Verlauf liegt beim SERVER
// ════════════════════════════════════════════════════════════════════
section('3. /support – Muelleimer am Verlaufseintrag');
{
    let eintraege = [
        { query: 'Drucker klemmt', ts: 1756520000, total: 4 },
        { query: 'VPN geht nicht', ts: 1756510000, total: 7 },
        { query: 'Passwort zurücksetzen', ts: 1756500000, total: 2 },
    ];
    const rufe = [];
    let sucheGestartet = 0;
    const dom = baueDom('support.html', '/support',
        () => (url, init) => {
            const u = String(url), m = (init && init.method) || 'GET';
            rufe.push({ url: u, method: m, body: (init && init.body) || null,
                        headers: (init && init.headers) || {} });
            if (u === '/api/support/history' && m === 'GET') return json({ ok: true, entries: eintraege });
            if (u === '/api/support/history/entry' && m === 'DELETE') {
                const b = JSON.parse(init.body);
                const vorher = eintraege.length;
                eintraege = eintraege.filter((e) => e.query.trim().toLowerCase()
                                                    !== String(b.query).trim().toLowerCase());
                return json({ ok: true, removed: vorher - eintraege.length });
            }
            if (u.startsWith('/api/support/query')) { sucheGestartet++; return json({ ok: true, blocks: [] }); }
            if (u.startsWith('/api/me')) return json({ username: 'anna', is_admin: false });
            if (u.startsWith('/api/support/status')) return json({ jira_active: false, confluence_active: false });
            return json({ ok: true });
        });
    ladeSkript(dom, 'js/icons.js');
    ladeSkript(dom, 'js/i18n.js');
    ladeSkript(dom, 'js/chatlib.js');
    ladeSkript(dom, 'js/support.js');
    await sleep(120);
    const w = dom.window, dc = w.document;
    dc.getElementById('sup-hist-btn').click();
    await sleep(60);

    const knoepfe = dc.querySelectorAll('#sup-hist-list .sup-hist-del');
    check('jeder Eintrag traegt einen Loeschknopf', knoepfe.length === 3,
          'gefunden: ' + knoepfe.length);
    check('der Knopf traegt den Muelleimer aus icons.js',
          knoepfe.length > 0 && /jv-ico-trash/.test(knoepfe[0].innerHTML));
    check('und KEIN x (Symbol-Semantik)',
          knoepfe.length > 0 && !KREUZE.test(knoepfe[0].innerHTML + knoepfe[0].textContent));
    check('der Knopf ist beschriftet (title + aria-label)',
          knoepfe.length > 0 && !!knoepfe[0].title && !!knoepfe[0].getAttribute('aria-label'));

    const vorherEingabe = dc.getElementById('sup-input').value;
    knoepfe[1].click();
    await sleep(80);

    const del = rufe.filter((r) => r.method === 'DELETE' && r.url === '/api/support/history/entry');
    check('genau EIN Loeschaufruf', del.length === 1, 'gefunden: ' + del.length);
    const rumpf = del.length ? JSON.parse(del[0].body) : {};
    check('gesendet wird die angeklickte Anfrage', rumpf.query === 'VPN geht nicht',
          JSON.stringify(rumpf));
    // Der Benutzer kommt aus der Anmeldung. Stuende er im Rumpf, waere der
    // Endpunkt ein Weg in fremde Verlaeufe.
    check('KEIN Benutzer im Rumpf', Object.keys(rumpf).length === 1
          && !/user|benutzer|owner/i.test(JSON.stringify(rumpf)));
    check('der Loeschaufruf traegt das Sitzungstoken',
          del.length > 0 && /Bearer /.test(del[0].headers['Authorization'] || ''));
    check('der Klick hat KEINE Suche gestartet', sucheGestartet === 0);
    check('...und die Anfrage nicht ins Eingabefeld uebernommen',
          dc.getElementById('sup-input').value === vorherEingabe,
          dc.getElementById('sup-input').value);
    check('DAS VERLAUFSFELD BLEIBT OFFEN',
          !dc.getElementById('sup-hist-panel').classList.contains('hidden'));
    check('die Liste wurde neu vom Server geholt (er ist die Wahrheit)',
          rufe.filter((r) => r.url === '/api/support/history' && r.method === 'GET').length >= 2);
    await sleep(40);
    check('die geloeschte Zeile ist weg',
          dc.querySelectorAll('#sup-hist-list .sup-hist-item').length === 2,
          String(dc.querySelectorAll('#sup-hist-list .sup-hist-item').length));
    w.close();
}

// ════════════════════════════════════════════════════════════════════
// 4. Sprachwechsel – die Beschriftung gibt es in DE UND EN
// ════════════════════════════════════════════════════════════════════
section('4. Beschriftung in beiden Sprachen');
{
    const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
    for (const key of ['sup.hist_del', 'sup.hist_del_err']) {
        const n = (i18n.match(new RegExp("'" + key.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
        check(key + ' ist in DE und EN belegt', n === 2, 'gefunden: ' + n);
    }
}

// ── Ergebnis ────────────────────────────────────────────────────────
const ok = results.filter((r) => r.ok).length;
const bad = results.length - ok;
console.log('\n══════════════════════════════════════════════');
console.log('Ergebnis: ' + ok + '/' + results.length + ' bestanden'
            + (bad ? '  ·  ' + bad + ' FEHLER' : ''));
process.exit(bad ? 1 : 0);

})().catch((e) => { console.error(e); process.exit(2); });
