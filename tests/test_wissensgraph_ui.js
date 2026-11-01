#!/usr/bin/env node
/**
 * Wissensgraph-Seite (/wissensgraph), Portal-Kachel und Chat-Vorlage – jsdom.
 *
 * Geprueft wird das VERHALTEN an der ECHTEN wissensgraph.html mit den ECHTEN
 * Modulen (sitzung, i18n, icons, graphology, louvain, fa2, sigma,
 * wissensgraph.js) an einer fetch-Attrappe:
 *   1. Portal: die Kachel haengt am Recht ``permissions.wissensgraph`` (jeder
 *      Wissenseditor, Admins fuer die Steuerung) – nicht an is_admin.
 *   2. Seite nach Rolle (Festlegung 2026-10-31): ohne Recht verborgen und ohne
 *      Abruf; Gruppen-Editor sieht Grafik und Auffaelligkeiten seiner Gruppen,
 *      aber weder Steuerung noch Pflege; Admin ALLEIN nur die Steuerung.
 *   3. Ohne WebGL 2 (jsdom hat keines) steht eine Meldung statt einer leeren
 *      Flaeche – Legende und Auffaelligkeiten entstehen trotzdem.
 *   4. Auffaelligkeiten: ueberraschende Verbindung, Brueckenbegriff, Begriffe
 *      ohne Verbindung; Ausblenden ueberlebt ein Neuzeichnen, Zurueckholen geht.
 *   5. Faerbung schaltet um, die Beschriftung wechselt mit; Sprachwechsel
 *      erneuert die selbst gezeichneten Texte.
 *   6. i18n: jeder benutzte Schluessel steht in DE UND EN.
 *   7. Projektregeln als REGEL: kein Inline-Skript/-Handler, Symbole aus
 *      icons.js (× schliesst, Muelleimer entfernt), keine Farbliterale.
 *   8. Chat-Vorlage: belegt das Feld vor, sendet nichts, verfaellt.
 *   9. Phase 6: Rueckkopplung beim Server und Aehnlichkeitsgewichtung,
 *      Widerspruchskarte, Wiki-Abschnitt im Detail (DOM statt innerHTML),
 *      Export als Datei, Schalter, Nachlauf im Status.
 *
 * Layout, Ueberlappung und die WebGL-Grafik selbst sieht jsdom nicht – das
 * misst tests/live_wissensgraph_ui_dev.py im echten Chrome.
 *
 *   node tests/test_wissensgraph_ui.js
 */
require('./lib/bilanz')();

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d !== undefined ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n' + t);

const ROOT = path.resolve(__dirname, '..');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

const HTML = lies('frontend/wissensgraph.html');
const JS = lies('frontend/js/wissensgraph.js');
const CSS = lies('frontend/css/wissensgraph.css');
const I18N = lies('frontend/js/i18n.js');
const THEME = lies('frontend/css/theme.css');
const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js',
                'frontend/js/vendor/graphology.min.js', 'frontend/js/vendor/sigma.min.js',
                'frontend/js/vendor/graphology-fa2.min.js', 'frontend/js/vendor/graphology-louvain.min.js',
                'frontend/js/wissensgraph.js'];
const warte = (ms) => new Promise(r => setTimeout(r, ms));
// jsdom serialisiert SVG anders als der Quelltext (selbstschliessende Tags) –
// verglichen wird deshalb mit einem Element, dem DERSELBE Text gesetzt wurde.
function gleichesMarkup(w, html, erwartet) {
    const t = w.document.createElement('div');
    t.innerHTML = erwartet;
    return html === t.innerHTML;
}

// ── Testgraph: drei klar getrennte Inseln + Bruecke + isolierter Begriff ──
function k(id, name, typ, grad, sources) {
    return { id, name, typ, grad, aliasse: [], zusammenfassung: '', sources: sources || ['data/rag/x/d.md'] };
}
function e(von, nach, art, gewicht) { return { von, nach, art: art || 'nutzt', gewicht: gewicht || 1, sources: [] }; }
function testgraph() {
    const kn = [], ka = [];
    const inseln = { a: 'system', b: 'konzept', c: 'prozess' };
    Object.keys(inseln).forEach(function (p) {
        for (let i = 1; i <= 4; i++) { kn.push(k('e:' + p + i, p.toUpperCase() + i, inseln[p], 4)); }
        for (let i = 1; i <= 4; i++) {
            for (let j = i + 1; j <= 4; j++) { ka.push(e('e:' + p + i, 'e:' + p + j, 'gehoert_zu', 2)); }
        }
    });
    ka.push(e('e:a1', 'e:b1', 'nutzt', 1));                    // ueberraschend: Inseln + Arten
    ka.push(e('e:c1', 'e:b3', 'nutzt', 1));                    // zweite, gleich stark (Rueckkopplung)
    kn.push(k('e:x', 'Brueckenbegriff', 'produkt', 3));
    ka.push(e('e:x', 'e:a2'), e('e:x', 'e:b2'), e('e:x', 'e:c2'));
    kn.push(k('e:iso', 'Einzelgaenger', 'ort', 1));
    kn.push(k('q:data/rag/x/d.md', 'd.md', 'quelle', 2));
    ka.push(e('e:iso', 'q:data/rag/x/d.md', 'erwaehnt_in', 1), e('e:a1', 'q:data/rag/x/d.md', 'erwaehnt_in', 1));
    return { knoten: kn, kanten: ka, treffer: [], gesamt: kn.length, gefiltert: kn.length,
             offset: 0, limit: 500, erzeugt: 1 };
}

// Rechte des Betrachters (/api/wissensgraph/zugang). VOLL = Admin UND globaler
// Wissenseditor – die Abschnitte 3–6 messen damit die volle Seite.
const VOLL = { stufe: 'global', gruppen: [{ id: 'g1', name: 'Gruppe 1' }], pflegen: true, steuern: true };
const WIDERSPRUCH = { id: 'w1', kid: 'e:c1', name: 'C1', a: 'data/rag/x/d.md', b: 'data/rag/x/e.md',
                      name_a: 'd.md', name_b: 'e.md', aussage_a: 'Frist 14 Tage', aussage_b: 'Frist 30 Tage',
                      erklaerung: 'verschiedene Fristen' };

function baueSeite(opt) {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (er) => {
        const m = String(er && er.message || er);
        // Erwartet: jsdom kennt weder Navigation noch Canvas-Kontexte.
        if (!/navigation|getContext|HTMLCanvasElement/.test(m)) { fehler.push(m); }
    });
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissensgraph', runScripts: 'outside-only',
                                   virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');
    Object.keys(opt.vorher || {}).forEach(function (sl) { w.localStorage.setItem(sl, opt.vorher[sl]); });
    const rufe = [];
    const gesendet = [];
    // Kleiner Server-Zustand: was die Seite schreibt, liest sie zurueck – so
    // misst der Pruefstand die Wirkung, nicht nur den Aufruf.
    const server = { verworfen: [], wiki: {}, einstFehler: false, pause: false, pruefAufrufe: 0, zustand: {},
                     einst: { aktiv: true, expansion: false, widersprueche: true, wiki_sammellauf: true } };
    const antwort = (status, body, kopf) => Promise.resolve({
        ok: status >= 200 && status < 300, status,
        json: () => Promise.resolve(body), blob: () => Promise.resolve(new w.Blob(['x'])),
        headers: { get: (n) => (kopf || {})[String(n).toLowerCase()] || null },
    });
    w.URL.createObjectURL = () => 'blob:pruefstand';
    w.URL.revokeObjectURL = () => {};
    w.fetch = function (url, o) {
        const u = String(url).split('?')[0];
        const m = (o && o.method) || 'GET';
        const body = o && o.body ? JSON.parse(o.body) : null;
        rufe.push(u);
        gesendet.push({ u, m, body });
        if (u === '/api/me') { return antwort(200, { username: 'jarvis', is_admin: !!opt.admin, permissions: {} }); }
        if (u === '/api/wissensgraph/zugang') { return antwort(200, opt.zugang || VOLL); }
        if (u === '/api/wissensgraph/graph') { return antwort(200, opt.graph || testgraph()); }
        if (u === '/api/wissensgraph/status') {
            return antwort(200, Object.assign({ aktiv: true, laeuft: false, warteschlange: 0, erledigt: 0, fehler: 0,
                                  zaehler: {}, graph: { quellen: 1, entitaeten: 14, kanten: 22, widersprueche: 1 },
                                  letzte_fehler: [], einstellungen: Object.assign({}, server.einst),
                                  nachlauf: { pause: server.pause, widersprueche_offen: 3, wiki_offen: 5, wiki_seiten: 2 } },
                                server.zustand));
        }
        if (u === '/api/wissensgraph/rueckmeldung') {
            if (m === 'POST') {
                server.verworfen = server.verworfen.filter(x => x.schluessel !== body.schluessel).concat([body]);
            } else if (m === 'DELETE') { server.verworfen = []; }
            return antwort(200, { verworfen: server.verworfen.slice() });
        }
        if (u === '/api/wissensgraph/widersprueche') { return antwort(200, { befunde: [WIDERSPRUCH] }); }
        if (u.indexOf('/api/wissensgraph/wiki/') === 0) {
            const kid = decodeURIComponent(u.slice('/api/wissensgraph/wiki/'.length));
            if (m === 'POST') {
                server.wiki[kid] = { markdown: '## Überblick\nA1 nutzt [[B1]] und ist **wichtig**.\n- Punkt <img src=x>\n',
                                     veraltet: false, erzeugt: 1 };
                return antwort(200, server.wiki[kid]);
            }
            if (opt.wiki403) { return antwort(403, { detail: 'Die Wiki-Seite stützt sich auch auf Dokumente außerhalb deiner Wissensgruppen.' }); }
            return server.wiki[kid] ? antwort(200, server.wiki[kid]) : antwort(404, { detail: 'Keine Wiki-Seite vorhanden' });
        }
        if (u === '/api/wissensgraph/einstellungen' && m === 'POST') {
            if (server.einstFehler) { return antwort(400, { detail: 'abgelehnt' }); }
            Object.assign(server.einst, body);
            return antwort(200, { einstellungen: server.einst });
        }
        if (u === '/api/wissensgraph/pruefliste') {
            const n = server.pruefAufrufe++;
            if (n === 0) { return antwort(200, { paare: [], laeuft: true, veraltet: false, zeit: 0, fehler: '' }); }
            return antwort(200, { paare: [{ aehnlichkeit: 0.93, quelle: { id: 'e:a2', name: 'A2', typ: 'system', quellen: 1 },
                                            ziel: { id: 'e:a1', name: 'A1', typ: 'system', quellen: 3 } }],
                                  laeuft: false, veraltet: false, zeit: 1, fehler: '' });
        }
        if (u === '/api/wissensgraph/export') {
            return antwort(200, {}, { 'content-disposition': 'attachment; filename="wissensgraph-20261031.zip"' });
        }
        if (u === '/api/knowledge/groups') { return antwort(200, { ok: true, groups: [{ id: 'g1', name: 'Gruppe 1' }] }); }
        if (u.indexOf('/api/wissensgraph/knoten/') === 0) {
            return antwort(200, Object.assign(k('e:a1', 'A1', 'system', 4), { ausgehend: [], eingehend: [] }));
        }
        return antwort(200, { ok: true });
    };
    w.open = function () { w.__geoeffnet = Array.from(arguments); };
    // Wie im Browser: ein Skript, das beim Laden wirft, haelt die folgenden
    // NICHT auf. sigma wirft in jsdom (kein WebGL2RenderingContext) – genau
    // der Fall eines alten Browsers, den die Seite ueberstehen muss.
    const ladefehler = {};
    MODULE.forEach(function (m) {
        try { w.eval(lies(m)); } catch (er) { ladefehler[m] = String(er && er.message || er); }
    });
    // Renderer-Attrappe: jsdom hat kein WebGL – ohne sie waere "wann entsteht der
    // Renderer" gar nicht beobachtbar. Gezaehlt werden Aufbau und Groessen-Nachzug.
    const sigmaZaehler = { gebaut: 0, resize: 0 };
    if (opt.sigma) {
        w.HTMLCanvasElement.prototype.getContext = function (art) { return art === 'webgl2' ? {} : null; };
        w.JarvisSigma = { Sigma: function () {
            sigmaZaehler.gebaut++;
            this.on = function () {}; this.refresh = function () {}; this.kill = function () {};
            this.resize = function () { sigmaZaehler.resize++; };
            this.getCamera = function () { return { on: function () {}, animatedReset: function () {}, ratio: 1 }; };
            this.getGraph = function () { return null; };
            this.setSetting = function () {};
            this.viewportToGraph = function (p) { return p; };
            this.graphToViewport = function (p) { return p; };
            this.getNodeDisplayData = function () { return null; };
            this.getContainer = function () { return w.document.getElementById('wg-graph'); };
        } };
    }
    return { w, rufe, gesendet, server, fehler, ladefehler, sigmaZaehler };
}

async function main() {
    abschnitt('0. Grundlage');
    const bundles = ['graphology', 'sigma', 'graphology-fa2', 'graphology-louvain'];
    bundles.forEach(function (b) {
        pruefe(new RegExp('/static/js/vendor/' + b + '\\.min\\.js\\?v=\\d+').test(HTML), 'Seite bindet vendor/' + b + '.min.js ein');
    });
    pruefe(/\/static\/js\/wissensgraph\.js\?v=\d+/.test(HTML), 'Seite bindet wissensgraph.js ein');

    abschnitt('1. Portal-Kachel nach Recht');
    // Der vierte Fall trennt Recht und Admin: ein Admin OHNE das Recht sieht die
    // Kachel nicht – sie haengt am Server-Urteil, nicht an is_admin.
    for (const fall of [{ n: 'Benutzer', admin: false, recht: false }, { n: 'Gruppen-Editor', admin: false, recht: true },
                        { n: 'Admin', admin: true, recht: true }, { n: 'Admin ohne Recht (Gegenkontrolle)', admin: true, recht: false }]) {
        const vc = new VirtualConsole(); vc.on('jsdomError', () => {});
        const dom = new JSDOM(lies('frontend/portal.html'), { url: 'https://localhost/portal',
                                                               runScripts: 'outside-only', virtualConsole: vc });
        const w = dom.window;
        sitzungLaden(w);
        w.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');
        w.fetch = (url) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(
            String(url).indexOf('/api/me') === 0 ? { username: 'u', is_admin: fall.admin, permissions: { wissensgraph: fall.recht } }
                                                 : { ok: true, groups: [] }) });
        w.eval(lies('frontend/js/i18n.js'));
        w.eval(lies('frontend/js/portal_seite.js'));
        await warte(80);
        const c = w.document.getElementById('pt-card-wissensgraph');
        pruefe(!!c && c.classList.contains('hidden') === !fall.recht,
               '[' + fall.n + '] Kachel ' + (fall.recht ? 'eingeblendet' : 'verborgen'));
        if (fall.n === 'Admin') { pruefe(!!c && c.getAttribute('href') === '/wissensgraph', 'Kachel fuehrt auf /wissensgraph'); }
        w.close();
    }

    abschnitt('2. Seite nach Rolle');
    {
        const s0 = baueSeite({ admin: false, zugang: { stufe: 'keine', gruppen: [], pflegen: false, steuern: false } });
        await warte(150);
        pruefe(s0.w.document.getElementById('wg-app').classList.contains('hidden'), 'ohne Recht: Seite bleibt verborgen');
        pruefe(s0.rufe.indexOf('/api/wissensgraph/graph') < 0 && s0.rufe.indexOf('/api/wissensgraph/status') < 0,
               'ohne Recht: holt weder Graph noch Status', s0.rufe.join(','));
        s0.w.close();

        const sg = baueSeite({ admin: false, wiki403: true,
                               zugang: { stufe: 'gruppen', gruppen: [{ id: 'a', name: 'Gruppe A' }], pflegen: false, steuern: false } });
        await warte(400);
        const dg = sg.w.document;
        const sichtbar = (id) => !!dg.getElementById(id) && !dg.getElementById(id).classList.contains('hidden');
        pruefe(sichtbar('wg-app') && sichtbar('wg-karte-graph') && sichtbar('wg-karte-insights'),
               'Gruppen-Editor: Grafik und Auffaelligkeiten sichtbar');
        pruefe(!sichtbar('wg-karte-pflege'), 'Gruppen-Editor: Aufbau und Pflege verborgen (weder Steuerung noch Pflege)');
        pruefe(sg.rufe.indexOf('/api/wissensgraph/graph') >= 0, 'Gruppen-Editor: holt den Graphen (der Server filtert)');
        pruefe(sg.rufe.indexOf('/api/wissensgraph/status') < 0 && sg.rufe.indexOf('/api/knowledge/groups') < 0,
               'Gruppen-Editor: holt weder Status noch die Liste aller Gruppen', sg.rufe.join(','));
        const opts = Array.from(dg.querySelectorAll('#wg-gruppe option')).map(o => o.value);
        pruefe(opts.join(',') === ',a', 'Gruppen-Editor: Filter bietet nur die eigenen Gruppen', opts.join(','));
        const hw = dg.getElementById('wg-umfang-hinweis');
        pruefe(sichtbar('wg-umfang-hinweis') && /Gruppe A/.test(hw.textContent), 'Gruppen-Editor: Hinweis nennt seine Gruppen',
               hw && hw.textContent);
        sg.w.WissensgraphIntern.detailOeffnen('e:a1');
        await warte(120);
        pruefe(!dg.querySelector('#wg-detail .wg-loeschen'), 'Gruppen-Editor: kein "Begriff entfernen" im Detail');
        const wb = dg.querySelector('#wg-detail .wg-wiki');
        pruefe(!!wb && /außerhalb deiner Wissensgruppen/.test(wb.textContent) && !wb.querySelector('.wg-wiki-knopf'),
               'Gruppen-Editor: gesperrte Wiki-Seite nennt den Grund, kein Erzeugen', wb && wb.textContent);
        pruefe(!!wb && !/fehlgeschlagen/.test(wb.textContent), 'Gruppen-Editor: die Sperre erscheint nicht als Ladefehler',
               wb && wb.textContent);
        sg.w.close();

        // Globaler Wissenseditor OHNE Admin: alle Inhalte und die Pflege, aber
        // keine Steuerung – die Karte ist sichtbar, nur ihr Steuerungsblock nicht.
        const sp = baueSeite({ admin: false, zugang: { stufe: 'global', gruppen: [{ id: 'g1', name: 'Gruppe 1' }],
                                                       pflegen: true, steuern: false } });
        await warte(300);
        const dp = sp.w.document;
        const sichtbarP = (id) => !!dp.getElementById(id) && !dp.getElementById(id).classList.contains('hidden');
        pruefe(sichtbarP('wg-karte-graph') && sichtbarP('wg-karte-pflege') && sichtbarP('wg-block-pruefliste')
               && sichtbarP('wg-block-export'), 'globaler Wissenseditor: Inhalte, Pruefliste und Export sichtbar');
        pruefe(!dp.getElementById('wg-block-steuerung') && !dp.getElementById('wg-start') && !dp.querySelector('[data-wg-einstellung]'),
               'keine Steuerung auf der Seite (liegt in Einstellungen → Wissen)');
        pruefe(sp.rufe.indexOf('/api/wissensgraph/status') < 0, 'globaler Wissenseditor ohne Admin: holt keinen Status',
               sp.rufe.join(','));
        sp.w.close();

        // Admin ohne Editor-Eintrag: seit 2026-11-01 KEINE Seite – gesteuert wird
        // in Einstellungen → Wissen (die Kachel haengt nur an den Wissenseditoren).
        const sa = baueSeite({ admin: true, zugang: { stufe: 'keine', gruppen: [], pflegen: false, steuern: true } });
        await warte(300);
        const da = sa.w.document;
        pruefe(da.getElementById('wg-app').classList.contains('hidden'), 'Admin allein: Seite bleibt verborgen');
        pruefe(sa.rufe.indexOf('/api/wissensgraph/graph') < 0 && sa.rufe.indexOf('/api/wissensgraph/status') < 0,
               'Admin allein: holt weder Inhalt noch Status', sa.rufe.join(','));
        sa.w.close();
    }

    abschnitt('3. Admin, ohne WebGL 2');
    const s = baueSeite({ admin: true });
    await warte(400);
    const d = s.w.document;
    const W = s.w.WissensgraphIntern;
    // ⚠ ZWEI URSACHEN TRENNEN (Register): baut die Seite GAR NICHT auf, kann
    // nichts gemessen werden (Exit 2). Ist sie da, aber ohne Graph, ist das ein
    // BEFUND – dann werden die Graph-Abschnitte uebersprungen, nicht der Lauf.
    if (!W || d.getElementById('wg-app').classList.contains('hidden')) {
        console.log('ABBRUCH – Seite nicht aufgebaut, Folgepruefungen trivial'); process.exit(2);
    }
    const graphDa = !!W.graph() && W.graph().order === testgraph().knoten.length;
    pruefe(graphDa, 'Graph geladen (' + (W.graph() ? W.graph().order : 0) + ' Knoten)',
           d.getElementById('wg-hinweis').textContent);
    if (graphDa) {
    pruefe(!d.getElementById('wg-app').classList.contains('hidden'), 'Seite sichtbar');
    pruefe(W.webgl2() === false, 'Positivkontrolle: jsdom hat kein WebGL 2');
    pruefe(Object.keys(s.ladefehler).join() === 'frontend/js/vendor/sigma.min.js',
           'Positivkontrolle: nur sigma scheitert beim Laden (Lage eines alten Browsers)',
           JSON.stringify(s.ladefehler));
    pruefe(W.grafikMoeglich() === false, 'Grafik gilt als nicht moeglich');
    const h = d.getElementById('wg-hinweis');
    pruefe(!h.classList.contains('hidden') && /WebGL 2/.test(h.textContent),
           'Meldung statt leerer Flaeche', h.textContent);
    pruefe(h.classList.contains('is-err'), 'Meldung ist als Fehler gekennzeichnet');
    pruefe(W.renderer() === null, 'kein Renderer-Versuch ohne WebGL 2');
    const leg = d.getElementById('wg-legende').textContent;
    pruefe(/Systeme · 4/.test(leg) && /Fachbegriffe · 4/.test(leg) && /Abläufe · 4/.test(leg),
           'Legende (Art): Anzahl je Art', leg);
    const N = testgraph().knoten.length;
    pruefe(new RegExp(N + ' von ' + N).test(d.getElementById('wg-zaehler').textContent), 'Zaehler nennt beide Zahlen',
           d.getElementById('wg-zaehler').textContent);
    pruefe(d.getElementById('wg-mehr').classList.contains('hidden'), '"Weitere laden" verborgen, wenn alles da ist');
    pruefe(s.rufe.indexOf('/api/wissensgraph/status') < 0 && !d.getElementById('wg-status'),
           'kein Status auf der Seite (Steuerung in den Einstellungen)', s.rufe.join(','));
    pruefe(/Prüfliste und Export/.test(d.querySelector('#wg-karte-pflege h2').textContent), 'Container heisst „Prüfliste und Export“');
    pruefe(d.querySelectorAll('#wg-gruppe option').length === 2, 'Wissensgruppen im Filter');

    abschnitt('4. Auffaelligkeiten');
    const a = W.auffaelligkeiten();
    const inselnVon = (n) => W.graph().getNodeAttribute(n, 'insel');
    pruefe(W.inseln().length >= 3, 'Positivkontrolle: mindestens drei Themen-Inseln', W.inseln().length);
    pruefe(inselnVon('e:a1') !== inselnVon('e:b1'), 'Positivkontrolle: A1 und B1 liegen auf verschiedenen Inseln');
    pruefe(a.verbindungen.some(v => [v.von, v.nach].sort().join() === 'e:a1,e:b1'),
           'ueberraschende Verbindung A1 ↔ B1 erkannt', JSON.stringify(a.verbindungen));
    // Die EIGENSCHAFT, nicht das Etikett: der Grund 'insel' steht immer dabei.
    pruefe(a.verbindungen.length > 0 && a.verbindungen.every(v => inselnVon(v.von) !== inselnVon(v.nach)),
           'nur ueber Inselgrenzen', JSON.stringify(a.verbindungen.map(v => [v.von, v.nach])));
    pruefe(a.bruecken.some(b => b.knoten === 'e:x'), 'Brueckenbegriff erkannt', JSON.stringify(a.bruecken));
    pruefe(a.isoliert.length === 1 && a.isoliert[0] === 'e:iso', 'Begriff ohne Verbindung erkannt (Dokumentkante zaehlt nicht)',
           JSON.stringify(a.isoliert));
    pruefe(a.bruecken.every(b => b.knoten.indexOf('q:') !== 0) && a.isoliert.every(n => n.indexOf('q:') !== 0),
           'Dokumentknoten sind keine Auffaelligkeit');
    const karten = () => Array.from(d.querySelectorAll('#wg-insights .wg-karte'));
    const n0 = karten().length;
    pruefe(n0 >= 3, 'Karten gezeichnet', n0);
    const kv = karten().find(k2 => /A1 ↔ B1|B1 ↔ A1/.test(k2.textContent));
    pruefe(!!kv, 'Karte zur ueberraschenden Verbindung');
    const ki = karten().find(k2 => /ohne Verbindung/.test(k2.textContent));
    pruefe(!!ki && !!ki.querySelector('.wg-recherche'), 'Luecke bietet "Recherche starten"');
    if (kv) {
        const zu = kv.querySelector('.wg-zu');
        pruefe(!!zu && gleichesMarkup(s.w, zu.innerHTML, s.w.JarvisIcons.close()), 'Ausblenden-Knopf traegt das ×-Symbol');
        zu.click();
        await warte(30);
        pruefe(karten().length === n0 - 1, 'Ausblenden entfernt die Karte');
        const rm = s.gesendet.filter(x => x.u === '/api/wissensgraph/rueckmeldung' && x.m === 'POST');
        pruefe(rm.length === 1 && s.server.verworfen.length === 1, 'Ausblenden wird beim Server gemerkt (fuer alle Admins)',
               JSON.stringify(rm));
        pruefe(rm.length === 1 && rm[0].body.art === 'v' && rm[0].body.knoten.slice().sort().join() === 'e:a1,e:b1'
               && rm[0].body.typen.length === 2, 'Rueckmeldung beschreibt Art, Begriffe und Typen', JSON.stringify(rm[0] && rm[0].body));
        pruefe(s.w.localStorage.getItem('jarvis_wg_insights_weg') === null, 'nichts mehr in localStorage');
        pruefe(!d.getElementById('wg-insights-zurueck').classList.contains('hidden'), '"wieder zeigen" erscheint');
        d.getElementById('wg-faerbung').click();         // zeichnet nichts neu – Sprachwechsel schon:
        s.w.dispatchEvent(new s.w.CustomEvent('jarvis-lang-changed'));
        pruefe(karten().length === n0 - 1, 'die ausgeblendete bleibt nach dem Neuzeichnen weg');
        d.getElementById('wg-faerbung').click();
        d.getElementById('wg-insights-zurueck').click();
        await warte(30);
        pruefe(karten().length === n0, '"wieder zeigen" holt sie zurueck');
        pruefe(s.gesendet.some(x => x.u === '/api/wissensgraph/rueckmeldung' && x.m === 'DELETE') && !s.server.verworfen.length,
               '... und setzt die Rueckmeldungen beim Server zurueck');
    }
    if (ki) {
        ki.querySelector('.wg-recherche').click();
        const v = JSON.parse(s.w.localStorage.getItem('jarvis_chat_vorlage') || 'null');
        pruefe(!!v && /Einzelgaenger/.test(v.text) && typeof v.zeit === 'number', 'Recherche legt den Auftrag als Vorlage ab');
        pruefe(!!s.w.__geoeffnet && s.w.__geoeffnet[0] === '/chat', '... und oeffnet /chat');
    }

    abschnitt('4b. Rueckkopplung und Widersprueche');
    W.verworfenSetzen([{ schluessel: 'v:alt', art: 'v', knoten: ['e:a1'], typen: ['prozess', 'system'] }]);
    pruefe(W.aehnlichkeit('v', ['e:a1', 'e:zz'], []) === 1, 'teilt einen Begriff: Aehnlichkeit 1');
    pruefe(W.aehnlichkeit('v', ['e:q1'], ['system', 'prozess']) === 0.5, 'gleiche Arten (Reihenfolge egal): 0,5');
    pruefe(W.aehnlichkeit('b', ['e:a1'], []) === 0, 'andere Art der Auffaelligkeit: 0');
    pruefe(Math.abs(W.rueckFaktor('v', ['e:a1'], []) - 0.4) < 1e-9, 'Faktor = 1 − 0,6 × Aehnlichkeit');
    W.verworfenSetzen([]);
    const vor = W.auffaelligkeiten().verbindungen.map(v => [v.von, v.nach].sort().join());
    pruefe(vor.length >= 2 && vor[0] === 'e:a1,e:b1', 'Positivkontrolle: ohne Rueckmeldung steht A1–B1 vorn', vor.join(' / '));
    W.verworfenSetzen([{ schluessel: 'v:e:a1|e:anders', art: 'v', knoten: ['e:a1'], typen: [] }]);
    const nach = W.auffaelligkeiten().verbindungen.map(v => [v.von, v.nach].sort().join());
    pruefe(nach[0] !== 'e:a1,e:b1' && nach.indexOf('e:a1,e:b1') > 0,
           'eine verworfene aehnliche Karte stuft A1–B1 zurueck', nach.join(' / '));
    W.verworfenSetzen([]);
    W.insightsZeichnen();
    const kw = karten().find(k2 => /Widerspruch: C1/.test(k2.textContent));
    pruefe(!!kw && /Frist 14 Tage/.test(kw.textContent) && /Frist 30 Tage/.test(kw.textContent),
           'Widerspruchskarte nennt beide Aussagen', kw && kw.textContent.slice(0, 160));
    if (kw) {
        kw.querySelector('.wg-recherche').click();
        const v2 = JSON.parse(s.w.localStorage.getItem('jarvis_chat_vorlage') || 'null');
        pruefe(!!v2 && /14 Tage/.test(v2.text) && /30 Tage/.test(v2.text) && /C1/.test(v2.text),
               'Recherche-Auftrag traegt Begriff und beide Aussagen', v2 && v2.text);
        kw.querySelector('.wg-zu').click();
        await warte(30);
        const rw = s.gesendet.filter(x => x.u === '/api/wissensgraph/rueckmeldung' && x.m === 'POST').pop();
        pruefe(rw && rw.body.art === 'w' && rw.body.knoten.indexOf('q:data/rag/x/d.md') >= 0 && rw.body.knoten.indexOf('e:c1') >= 0,
               'Ausblenden der Widerspruchskarte: Art w mit Begriff und beiden Dokumenten', JSON.stringify(rw && rw.body));
        W.verworfenSetzen([]);
        W.insightsZeichnen();
    }

    abschnitt('4c. Filterwechsel behaelt den Graphen (Grafik haengt an ihm)');
    // Gemeldet 2026-10-31: jeder Filterwechsel endete in "Laden fehlgeschlagen",
    // weil die Seite ein NEUES Graph-Objekt anlegte, waehrend sigma am alten hing.
    // jsdom hat keinen Renderer – gemessen wird die Eigenschaft, an der er haengt.
    const g0 = W.graph();
    const n0g = g0 ? g0.order : 0;
    d.getElementById('wg-gruppe').value = 'g1';
    d.getElementById('wg-gruppe').dispatchEvent(new s.w.Event('change'));
    await warte(150);
    pruefe(!!g0 && n0g > 0, 'Positivkontrolle: Graph vor dem Filterwechsel geladen', n0g);
    pruefe(s.rufe.filter(u => u === '/api/wissensgraph/graph').length >= 2, 'Filterwechsel laedt neu');
    pruefe(W.graph() === g0, 'nach dem Filterwechsel DIESELBE Graph-Instanz');
    pruefe(W.graph().order === n0g, 'neu gefuellt, nicht angehaengt (gleiche Knotenzahl aus derselben Antwort)', W.graph().order);
    d.getElementById('wg-gruppe').value = '';
    d.getElementById('wg-gruppe').dispatchEvent(new s.w.Event('change'));
    await warte(150);

    abschnitt('5. Faerbung und Sprache');
    const fb = d.getElementById('wg-faerbung');
    pruefe(/nach Art/.test(fb.textContent) && fb.getAttribute('aria-pressed') === 'false', 'Start: nach Art');
    fb.click();
    pruefe(/Themen-Inseln/.test(fb.textContent) && fb.getAttribute('aria-pressed') === 'true',
           'Umschalten: Beschriftung und aria-pressed wechseln');
    const legI = d.getElementById('wg-legende').textContent;
    pruefe(/Zusammenhalt/.test(legI) && /Begriffe/.test(legI), 'Legende (Inseln): Mitglieder und Zusammenhalt', legI.slice(0, 160));
    const ersteInsel = d.querySelector('#wg-legende .wg-leg-insel');
    if (ersteInsel) { ersteInsel.click(); }
    const hv = W.hervor();
    pruefe(!!hv && Object.keys(hv.knoten).length >= 4,
           'Klick auf eine Insel hebt ihre Mitglieder hervor', hv ? Object.keys(hv.knoten).length : 'nichts');
    s.w.setLang('en');
    await warte(30);
    pruefe(/topic islands/.test(fb.textContent), 'Sprachwechsel erneuert die Knopfbeschriftung', fb.textContent);
    pruefe(new RegExp('of ' + N + ' terms').test(d.getElementById('wg-zaehler').textContent), 'Sprachwechsel erneuert den Zaehler',
           d.getElementById('wg-zaehler').textContent);
    s.w.setLang('de');
    await warte(30);

    abschnitt('6. Detail, Symbole');
    W.detailOeffnen('e:a1');
    await warte(60);
    pruefe(!d.getElementById('wg-detail').classList.contains('hidden'), 'Detail geoeffnet');
    pruefe(gleichesMarkup(s.w, d.getElementById('wg-detail-zu').innerHTML, s.w.JarvisIcons.close()), 'Schliessen = ×-Symbol');
    const weg = d.querySelector('#wg-detail .wg-loeschen');
    const svg = weg ? weg.querySelector('svg') : null;
    pruefe(!!svg && gleichesMarkup(s.w, svg.outerHTML, s.w.JarvisIcons.trash()), 'Entfernen = Muelleimer');
    d.getElementById('wg-detail-zu').click();
    pruefe(d.getElementById('wg-detail').classList.contains('hidden'), '× schliesst das Detail');

    abschnitt('6a. Wiki-Seite im Detail');
    W.detailOeffnen('e:a1');
    await warte(80);
    const wikiBox = () => d.querySelector('#wg-detail .wg-wiki');
    pruefe(!!wikiBox() && /Noch keine Wiki-Seite/.test(wikiBox().textContent), 'ohne Seite: Hinweis', wikiBox() && wikiBox().textContent);
    const wk = wikiBox() && wikiBox().querySelector('.wg-wiki-knopf');
    pruefe(!!wk && /erzeugen/.test(wk.textContent), 'Knopf "Wiki-Seite erzeugen"');
    if (wk) { wk.click(); }
    await warte(80);
    pruefe(s.gesendet.some(x => x.u === '/api/wissensgraph/wiki/e%3Aa1' && x.m === 'POST'), 'Erzeugen ruft POST');
    const wb = wikiBox();
    pruefe(!!wb && !!wb.querySelector('h5') && /Überblick/.test(wb.querySelector('h5').textContent), 'Abschnitt als Zwischenueberschrift');
    pruefe(!!wb && !!wb.querySelector('strong') && wb.querySelector('strong').textContent === 'wichtig', '**fett**');
    pruefe(!!wb && !wb.querySelector('img') && /<img src=x>/.test(wb.textContent), 'HTML aus der Seite bleibt Text (kein Element)');
    const vl = wb && Array.from(wb.querySelectorAll('button.wg-link')).find(b2 => b2.textContent === 'B1');
    pruefe(!!vl, 'Verweis [[B1]] ist ein Knopf');
    pruefe(!!wb && /Neu erzeugen/.test(wb.textContent), 'mit Seite: "Neu erzeugen"');
    const vorKlick = s.rufe.length;
    if (vl) { vl.click(); }
    await warte(60);
    pruefe(s.rufe.slice(vorKlick).some(u => u === '/api/wissensgraph/knoten/e%3Ab1' || u === '/api/wissensgraph/knoten/e:b1'),
           'Klick auf den Verweis oeffnet den Begriff', s.rufe.slice(vorKlick).join(','));
    s.server.wiki['e:a1'].veraltet = true;
    W.detailOeffnen('e:a1');
    await warte(80);
    pruefe(/Veraltet/.test((wikiBox() || {}).textContent || ''), 'veraltete Seite ist gekennzeichnet');

    abschnitt('6c. Export');
    d.getElementById('wg-export').click();
    await warte(60);
    pruefe(s.gesendet.some(x => x.u === '/api/wissensgraph/export'), 'Export holt die Datei mit Kopfzeile');
    pruefe(/wissensgraph-20261031\.zip/.test(d.getElementById('wg-export-meldung').textContent),
           'Export: Dateiname aus dem Server', d.getElementById('wg-export-meldung').textContent);
    pruefe(s.fehler.length === 0, 'keine unerwarteten Skriptfehler', s.fehler.slice(0, 3).join(' | '));

    abschnitt('6d. Drehender Kreis und Pruefliste im Hintergrund');
    // Gemeldet 2026-10-31: "Pruefliste laden" ohne Ergebnis und ohne Kreis – der
    // Vergleich dauert bei 7.500 Begriffen 19 s; die Seite stand so lange still.
    pruefe(/\.jv-pkg-spin\s*\{[^}]*animation:/.test(THEME) && /href="\/static\/css\/theme\.css/.test(HTML),
           'Positivkontrolle: der Kreis (.jv-pkg-spin) steht in theme.css, und die Seite laedt theme.css');
    W.pruefNachfrageMs(40);
    const pk = d.getElementById('wg-pruef-laden');
    pk.click();
    const pbox = d.getElementById('wg-pruefliste');
    pruefe(!!pbox.querySelector('.jv-pkg-spin') && pk.disabled, 'sofort nach dem Klick: Kreis sichtbar, Knopf gesperrt');
    await warte(20);
    pruefe(!!pbox.querySelector('.jv-pkg-spin') && /verglichen/.test(pbox.textContent),
           'Server rechnet noch: Kreis mit Erklaerung statt "Nichts zu pruefen"', pbox.textContent);
    pruefe(!/Nichts zu prüfen/.test(pbox.textContent), 'waehrend der Rechnung KEIN "Nichts zu pruefen"');
    await warte(150);
    pruefe(s.server.pruefAufrufe >= 2, 'die Seite fragt von selbst nach', s.server.pruefAufrufe);
    pruefe(pbox.querySelectorAll('.wg-paar').length === 1 && !pbox.querySelector('.jv-pkg-spin') && !pk.disabled,
           'fertig: Paar steht da, Kreis weg, Knopf wieder frei', pbox.textContent);
    W.detailOeffnen('e:a2');
    pruefe(!!d.querySelector('#wg-detail-inhalt .jv-pkg-spin'), 'Detail: Kreis waehrend des Ladens');
    await warte(80);
    pruefe(!d.querySelector('#wg-detail-inhalt .jv-pkg-spin'), 'Detail: Kreis nach dem Laden weg');

    const paarKn = d.querySelector('#wg-pruefliste .wg-paar .wg-paar-knoepfe button');
    pruefe(!!paarKn, 'Positivkontrolle: Pruefpaar mit Knopf vorhanden');
    if (paarKn) {
        paarKn.click();
        pruefe(!!paarKn.querySelector('.jv-pkg-spin') && paarKn.disabled && /zusammenführen/.test(paarKn.textContent),
               'Zusammenfuehren: Kreis im geklickten Knopf, Text bleibt', paarKn.innerHTML);
        await warte(60);
        pruefe(!d.querySelector('#wg-pruefliste .wg-paar'), 'Zusammenfuehren erledigt: Paar verschwindet');
    }

    abschnitt('6b. Beschriftungen bei grossen Knoten begrenzt');
    // Ein Knoten mit 30 Nachbarn: beim Ueberfahren lagen sonst 30 erzwungene
    // Beschriftungen und 30 Kantentexte uebereinander (Abnahme 2026-10-30).
    // Gemessen an den ECHTEN Reduzierern mit einem eigenen Graphen.
    const alt = W.graph();
    const H = new s.w.JarvisGraphology.Graph({ type: 'undirected', multi: false });
    H.addNode('hub', { label: 'Hub', size: 20, x: 0, y: 0, typ: 'system' });
    for (let i = 0; i < 30; i++) {
        H.addNode('n' + i, { label: 'N' + i, size: 2 + (i % 5), x: i, y: i, typ: 'konzept' });
        // n7 ist der am staerksten belegte Nachbar, n0..n5 nur ueber die Erwaehnung
        H.addEdge('hub', 'n' + i, { gewicht: i === 7 ? 9 : (i < 6 ? 1 : 2), arten: [i < 6 ? 'erwaehnt_in' : 'nutzt'],
                                     erwaehnt: i < 6 });
    }
    H.addNode('fern', { label: 'Fern', size: 3, x: 50, y: 50, typ: 'ort' });
    W.graphSetzen(H);
    W.hoverSetzen('hub');
    const kn = {};
    H.forEachNode((n, a) => { kn[n] = W.knotenReduzierer(n, {}, a); });
    const sichtbar = Object.keys(kn).filter(n => kn[n].labelVisibility === 'visible');
    pruefe(H.order === 32 && kn.hub && kn.hub.labelVisibility === 'visible', 'Positivkontrolle: Hub beschriftet', sichtbar.length);
    pruefe(sichtbar.length <= W.MAX_BESCHRIFTUNGEN + 1 && sichtbar.length > 1,
           'erzwungene Beschriftungen gedeckelt', sichtbar.length + ' von 31');
    pruefe(sichtbar.indexOf('n7') >= 0, 'der am staerksten belegte Nachbar ist dabei');
    pruefe(kn.n12 && kn.n12.zIndex === 2 && kn.n12.label === 'N12' && kn.n12.color !== kn.fern.color,
           'nicht erzwungene Nachbarn bleiben hell und behalten den Namen (Raster entscheidet)');
    pruefe(kn.fern && kn.fern.label === '', 'Fremdknoten gedimmt ohne Beschriftung');
    const texte = [];
    H.forEachEdge((k, a) => { const r = W.kantenReduzierer(k, {}, a); if (r.label) { texte.push(r.label); } });
    pruefe(texte.length > 0 && texte.length <= W.MAX_KANTENTEXTE, 'Kantentexte gedeckelt', texte.length + ' von 30');
    pruefe(texte.some(x => /9 Dokumente/.test(x)), 'staerkste Kante traegt ihren Text', texte[0]);
    W.hoverSetzen(null);
    const viele = [];
    H.forEachNode(n => viele.push(n));
    W.hervorheben(viele, []);
    const hv2 = W.hervor();
    const besch = Object.keys(hv2.beschriftet || {});
    pruefe(Object.keys(hv2.knoten).length === 32 && besch.length <= W.MAX_BESCHRIFTUNGEN && besch.indexOf('hub') >= 0,
           'Hervorheben vieler Knoten: nur die groessten erzwungen beschriftet', besch.length);
    // Auswahl nach freiem Platz: drei Kandidaten, der zweite schneidet den ersten.
    const kaesten = { a: { x1: 0, y1: 0, x2: 50, y2: 10 }, b: { x1: 40, y1: 5, x2: 90, y2: 15 },
                      c: { x1: 0, y1: 20, x2: 50, y2: 30 }, d: { x1: 100, y1: 0, x2: 140, y2: 10 } };
    const frei = W.freiAuswaehlen(['a', 'b', 'c', 'd'], (n) => kaesten[n], 12, []);
    pruefe(frei.join() === 'a,c,d', 'ueberlappende Beschriftung wird uebersprungen, Reihenfolge bleibt', frei.join());
    pruefe(W.freiAuswaehlen(['a', 'b', 'c', 'd'], (n) => kaesten[n], 2, []).join() === 'a,c', 'Hoechstzahl gilt nach dem Ueberspringen');
    pruefe(W.freiAuswaehlen(['a', 'c'], (n) => kaesten[n], 12, [{ x1: 45, y1: 0, x2: 60, y2: 5 }]).join() === 'c',
           'schon stehender Kasten (ueberfahrener Knoten) zaehlt mit');
    pruefe(W.freiAuswaehlen(['a', 'b'], null, 12, []).join() === 'a,b', 'ohne Positionen: nur die Anzahl');
    // jsdom laedt theme.css nicht – die Themenwerte werden hier gesetzt.
    s.w.document.body.style.setProperty('--bg-secondary', '#101820');
    s.w.document.body.style.setProperty('--text-primary', '#f0f0f0');
    W.farbenLesen();
    const kr = W.knotenReduzierer('hub', {}, H.getNodeAttributes('hub'));
    pruefe(kr.labelColor === '#f0f0f0', 'Positivkontrolle: Themenwerte gelesen', JSON.stringify(kr));
    pruefe(kr.backdropColor === '#101820', 'Hover-Kasten im Grund des Themas (sigma: fest weiss)', JSON.stringify(kr));
    W.graphSetzen(alt);
    } else {
        console.log('    (Abschnitte 3–6 uebersprungen: ohne Graph nicht messbar)');
    }
    s.w.close();

    abschnitt('6e. Container-Zustand wird gemerkt (Bauform /feedback)');
    {
        const SL = 'jarvis_wissensgraph_zu';
        const sa = baueSeite({ admin: true });
        await warte(300);
        const da = sa.w.document;
        const karte = (d, id) => d.querySelector('.ja-card[data-klapp="' + id + '"]');
        const kopf = (d, id) => { const kk = karte(d, id); return kk ? kk.querySelector('.ja-card-head') : null; };
        pruefe(!!kopf(da, 'graph') && !!kopf(da, 'insights') && !!kopf(da, 'pflege'),
               'Positivkontrolle: drei Klapp-Container mit Kopfzeile');
        pruefe(['graph', 'insights', 'pflege'].every(id => karte(da, id) && !karte(da, id).classList.contains('is-zu')),
               'ohne gespeicherten Zustand: alles offen');
        if (kopf(da, 'insights')) { kopf(da, 'insights').dispatchEvent(new sa.w.MouseEvent('click', { bubbles: true })); }
        let gespeichert = null;
        try { gespeichert = JSON.parse(sa.w.localStorage.getItem(SL) || 'null'); } catch (e) { gespeichert = 'kaputt'; }
        pruefe(Array.isArray(gespeichert) && gespeichert.length === 1 && gespeichert[0] === 'insights',
               'Zuklappen merkt die Kennung', JSON.stringify(gespeichert));
        pruefe(kopf(da, 'insights') && kopf(da, 'insights').getAttribute('aria-expanded') === 'false',
               'aria-expanded folgt dem Zuklappen');
        if (kopf(da, 'insights')) { kopf(da, 'insights').dispatchEvent(new sa.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); }
        pruefe(sa.w.localStorage.getItem(SL) === '[]', 'Aufklappen (Tastatur) nimmt sie wieder heraus', sa.w.localStorage.getItem(SL));
        sa.w.close();

        const sb = baueSeite({ admin: true, vorher: { [SL]: JSON.stringify(['pflege', 'insights']) } });
        await warte(300);
        const db = sb.w.document;
        pruefe(karte(db, 'pflege').classList.contains('is-zu') && karte(db, 'insights').classList.contains('is-zu'),
               'gespeicherter Zustand gilt beim Laden');
        pruefe(kopf(db, 'pflege').getAttribute('aria-expanded') === 'false', 'aria-expanded beim Laden gesetzt');
        pruefe(!karte(db, 'graph').classList.contains('is-zu'), 'nicht genannter Container bleibt offen (neuer Container = offen)');
        sb.w.close();

        const sc = baueSeite({ admin: true, vorher: { [SL]: '{kaputt' } });
        await warte(300);
        pruefe(['graph', 'insights', 'pflege'].every(id => !karte(sc.w.document, id).classList.contains('is-zu')),
               'kaputter Speicherstand: alles offen, kein Absturz');
        pruefe(!sc.fehler.length, 'kaputter Speicherstand: keine Skriptfehler', sc.fehler.join(' | '));
        // "alles offen" allein waere trivial wahr, wenn das Binden abbricht (der Wurf
        // landet in einem Promise-catch) – gemessen wird, dass Klappen dann WIRKT.
        kopf(sc.w.document, 'pflege').dispatchEvent(new sc.w.MouseEvent('click', { bubbles: true }));
        pruefe(karte(sc.w.document, 'pflege').classList.contains('is-zu') && sc.w.localStorage.getItem(SL) === '["pflege"]',
               'kaputter Speicherstand: Klappen wirkt und ersetzt ihn durch einen gueltigen', sc.w.localStorage.getItem(SL));
        sc.w.close();

        // Die Grafik: zugeklappt geladen entsteht KEIN Renderer (sigma braucht eine
        // Flaeche), erst das Aufklappen baut ihn.
        const sd = baueSeite({ admin: true, sigma: true, vorher: { [SL]: JSON.stringify(['graph']) } });
        await warte(400);
        const dd = sd.w.document;
        const sz = sd.sigmaZaehler;
        const ok0 = sd.w.WissensgraphIntern && sd.w.WissensgraphIntern.grafikMoeglich();
        pruefe(!!ok0, 'Positivkontrolle: Renderer-Attrappe macht die Grafik moeglich');
        pruefe(karte(dd, 'graph').classList.contains('is-zu') && sz.gebaut === 0,
               'Grafik zugeklappt geladen: kein Renderer gebaut', JSON.stringify(sz));
        kopf(dd, 'graph').dispatchEvent(new sd.w.MouseEvent('click', { bubbles: true }));
        pruefe(sz.gebaut === 1, 'Aufklappen baut den Renderer genau einmal', JSON.stringify(sz));
        kopf(dd, 'graph').dispatchEvent(new sd.w.MouseEvent('click', { bubbles: true }));
        kopf(dd, 'graph').dispatchEvent(new sd.w.MouseEvent('click', { bubbles: true }));
        pruefe(sz.gebaut === 1 && sz.resize >= 1, 'erneutes Aufklappen: nur Groesse nachziehen, kein Neubau', JSON.stringify(sz));
        sd.w.close();

        const se = baueSeite({ admin: true, sigma: true });
        await warte(400);
        pruefe(se.sigmaZaehler.gebaut === 1, 'Gegenkontrolle: offen geladen baut den Renderer sofort', JSON.stringify(se.sigmaZaehler));
        se.w.close();
    }

    abschnitt('7. i18n: jeder Schluessel in DE und EN');
    const trenner = I18N.indexOf('\n    en: {');
    const de = I18N.slice(0, trenner), en = I18N.slice(trenner);
    pruefe(trenner > 0, 'Positivkontrolle: EN-Block gefunden');
    const schl = new Set();
    (HTML.match(/data-i18n(?:-html|-placeholder|-title|-aria)?="([^"]+)"/g) || [])
        .forEach(m => schl.add(m.replace(/^[^"]+"|"$/g, '')));
    // Dynamische Praefixe (t('wissensgraph.type_' + typ)) sind keine Schluessel –
    // ihre Werte stehen ausdruecklich in der Liste darunter.
    (JS.match(/\bt\('((?:wissensgraph|portal)\.[a-z_]+)'/g) || []).map(m => m.slice(3, -1))
        .filter(x => !/_$/.test(x)).forEach(x => schl.add(x));
    ['system', 'konzept', 'prozess', 'produkt', 'organisation', 'person', 'ort', 'quelle']
        .forEach(x => schl.add('wissensgraph.type_' + x));
    ['insel', 'typ', 'rand'].forEach(x => schl.add('wissensgraph.why_' + x));
    ['portal.card_wissensgraph', 'portal.card_wissensgraph_desc'].forEach(x => schl.add(x));
    pruefe(schl.size > 80, 'Positivkontrolle: Schluessel gesammelt', schl.size);
    const fehltDe = [...schl].filter(x => de.indexOf("'" + x + "'") < 0);
    const fehltEn = [...schl].filter(x => en.indexOf("'" + x + "'") < 0);
    pruefe(!fehltDe.length, 'alle in DE', fehltDe.join(', '));
    pruefe(!fehltEn.length, 'alle in EN', fehltEn.join(', '));

    abschnitt('8. Projektregeln');
    pruefe(!/<script(?![^>]*\bsrc=)[^>]*>/.test(HTML), 'kein Inline-Skript in der Seite');
    pruefe(!/\son[a-z]+\s*=/.test(HTML), 'kein Inline-Handler in der Seite');
    pruefe(!/\.on[a-z]+\s*=/.test(JS), 'kein .onXyz = im Skript (nur addEventListener)');
    const inner = (JS.match(/innerHTML\s*=[^;]+;/g) || []);
    pruefe(inner.length > 0 && inner.every(x => /JarvisIcons\.(close|trash)\(\)/.test(x)),
           'innerHTML nur fuer Symbole aus icons.js', inner.join(' | '));
    const farbe = /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/;
    pruefe(!farbe.test(CSS.replace(/\/\*[\s\S]*?\*\//g, '')), 'wissensgraph.css ohne Farbliterale');
    pruefe(!farbe.test(JS.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')), 'wissensgraph.js ohne Farbliterale');
    // .hidden gibt es NICHT global (nur chat.css/feedback.css) – die Seite muss
    // eine eigene Regel laden, sonst stehen verborgene Elemente sichtbar da
    // (optische Abnahme 2026-10-30). Gelesen aus den CSS-Dateien, die die
    // Seite WIRKLICH einbindet.
    const cssDateien = (HTML.match(/href="\/static\/css\/([a-z_]+\.css)\?v=\d+"/g) || [])
        .map(m => m.replace(/^href="\/static\/css\/|\?v=\d+"$/g, ''));
    pruefe(cssDateien.length >= 3, 'Positivkontrolle: eingebundene CSS-Dateien gelesen', cssDateien.join(','));
    // ALLEINSTEHENDE Regel am Zeilenanfang: `.am-q-edit.hidden { display: none }`
    // in jira_addon.css gilt nur fuer EIN Element und machte die Pruefung trivial
    // wahr (Gegenprobe stumm, 2026-10-30).
    pruefe(cssDateien.some(f => /^\.hidden\s*\{\s*display:\s*none/m.test(lies('frontend/css/' + f))),
           'eine eingebundene CSS-Datei definiert .hidden { display: none }');
    // sigma 4 uebergibt die eigenen Attribute erst als DRITTES Argument; mit dem
    // zweiten war jeder Knoten grau (live gesehen). Die Wirkung misst die
    // Chrome-Abnahme, hier die Regel.
    pruefe(/function knotenReduzierer\(\w+, \w+, a\)/.test(JS) && /function kantenReduzierer\(\w+, \w+, a\)/.test(JS),
           'Reduzierer lesen die Attribute aus dem dritten Argument');
    // Felder aus sigma 2/3, die sigma 4 still ignoriert (types.d.ts DisplayData):
    // hidden → visibility, forceLabel → labelVisibility, labelColor-Einstellung →
    // labelColor je Element. Ein ignoriertes Feld meldet sich nicht.
    pruefe(!/\.hidden = true|forceLabel|edgeLabelColor|setSetting\('labelColor'/.test(JS),
           'keine sigma-2/3-Felder, die sigma 4 still ignoriert');
    // sigma 4 hat KEIN animatedZoom/animatedReset mehr (live auf DEV als
    // TypeError gesehen) – jede benutzte Kamera-Methode muss im ausgelieferten
    // Bundle vorkommen.
    const SIGMA = lies('frontend/js/vendor/sigma.min.js');
    const kamera = [...new Set((JS.match(/getCamera\(\)\.([A-Za-z]+)\(/g) || []).map(m => m.split('.')[1].replace('(', '')))];
    pruefe(kamera.length >= 3, 'Positivkontrolle: Kamera-Aufrufe gefunden', kamera.join(','));
    pruefe(kamera.every(m => new RegExp('\\b' + m + '\\b').test(SIGMA)),
           'jede Kamera-Methode gibt es in sigma 4', kamera.filter(m => !new RegExp('\\b' + m + '\\b').test(SIGMA)).join(','));
    ['--graph-c1', '--graph-c12', '--graph-kante-stark', '--graph-kante-schwach', '--graph-gedimmt'].forEach(function (v) {
        const n = (THEME.match(new RegExp(v + ':', 'g')) || []).length;
        pruefe(n === 2, 'theme.css definiert ' + v + ' fuer dunkel UND hell', n);
    });

    abschnitt('9. Chat-Vorlage');
    const CV = lies('frontend/js/chat_vorlage.js');
    pruefe(/chat_vorlage\.js\?v=\d+/.test(lies('frontend/chat.html')), 'chat.html bindet chat_vorlage.js ein');
    function chatSeite(wert) {
        const dom = new JSDOM('<!DOCTYPE html><body><textarea id="msg-input"></textarea></body>',
                              { url: 'https://localhost/chat', runScripts: 'outside-only' });
        const w = dom.window;
        const gesendet = [];
        w.fetch = (u) => { gesendet.push(u); return Promise.resolve({ ok: true, json: () => ({}) }); };
        if (wert !== undefined) { w.localStorage.setItem('jarvis_chat_vorlage', wert); }
        let eingabe = 0;
        w.document.getElementById('msg-input').addEventListener('input', () => { eingabe++; });
        w.eval(CV);
        return { w, gesendet, eingabe: () => eingabe };
    }
    // Direkt nach new JSDOM steht readyState auf 'loading' – das Modul wartet
    // auf DOMContentLoaded (Register). Erst danach messen.
    let c = chatSeite(JSON.stringify({ text: 'Recherchiere X', zeit: Date.now() }));
    await warte(30);
    pruefe(c.w.document.getElementById('msg-input').value === 'Recherchiere X', 'Vorlage steht im Eingabefeld');
    pruefe(c.eingabe() === 1, 'input-Ereignis gefeuert (Feld waechst mit)');
    pruefe(c.gesendet.length === 0, 'nichts abgeschickt');
    pruefe(c.w.localStorage.getItem('jarvis_chat_vorlage') === null, 'Vorlage nach dem Lesen geloescht');
    c = chatSeite(JSON.stringify({ text: 'alt', zeit: Date.now() - 6 * 60 * 1000 }));
    await warte(30);
    pruefe(c.w.document.getElementById('msg-input').value === '', 'aelter als fuenf Minuten: verfallen');
    c = chatSeite('{kaputt');
    await warte(30);
    pruefe(c.w.document.getElementById('msg-input').value === '', 'kaputte Vorlage: nichts, kein Absturz');

    console.log('\nErgebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
}

main().catch(function (er) { console.log('ABBRUCH: ' + (er && er.stack || er)); process.exit(2); });
