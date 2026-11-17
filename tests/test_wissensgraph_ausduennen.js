#!/usr/bin/env node
/**
 * Wissensgraph: Ausduennen nach Platz und Mindestgroesse (jsdom).
 *
 * Gemeldet 2026-11-17: die Grafik war unuebersichtlich, weil alle geladenen
 * Begriffe (bis 500) gleichzeitig als Punkt erschienen. Seitdem zeigt sie
 * einen Punkt nur, wenn auf dem BILDSCHIRM Platz fuer ihn ist (grosse zuerst),
 * und blendet Begriffe unter einer Mindestzahl an Verbindungen aus.
 *
 * Geprueft wird das VERHALTEN an der echten Seite mit dem echten Modul; nur
 * sigma ist eine Attrappe (jsdom hat kein WebGL), die Kamera und die
 * Abbildung Graph -> Bildschirm so nachbildet wie sigma 4:
 *   Bildpunkt = (Graph - Kamera) / ratio * MASS,  Punktradius = size / sqrt(ratio).
 * Gemessen wird, was der Knoten-Reduzierer an sigma zurueckgibt
 * (``visibility: 'hidden'``) – genau das, was sigma zeichnet oder nicht.
 *
 *   1. Weit weg: dichter Haufen wird ausgeduennt, der groesste Begriff und
 *      die freistehenden bleiben; KEINE zwei sichtbaren Punkte beruehren sich.
 *   2. Hineinzoomen bringt die verborgenen zurueck, Herauszoomen nimmt sie
 *      wieder weg (die Kamera loest das Neubemessen aus).
 *   3. Schalter aus: alles sichtbar; wieder an: ausgeduennt.
 *   4. Mindestgroesse: Begriffe darunter verborgen, auch ganz nah; Zeile
 *      darunter nennt die Zahl; der Wert ueberlebt ein Neuladen.
 *   5. Ueberfahren und Suche zeigen verborgene Nachbarn/Treffer trotzdem.
 *
 *   node tests/test_wissensgraph_ausduennen.js
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
const warte = (ms) => new Promise(r => setTimeout(r, ms));

const HTML = lies('frontend/wissensgraph.html');
const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js',
                'frontend/js/vendor/graphology.min.js', 'frontend/js/vendor/graphology-fa2.min.js',
                'frontend/js/vendor/graphology-louvain.min.js', 'frontend/js/wissensgraph.js'];
const MASS = 10;                     // Bildpunkte je Graph-Einheit bei ratio 1
const POS = 'jarvis_wg_pos';
const DICHTE = 'jarvis_wg_dichte';

// ── Testgraph: ein grosser Begriff, ein dichter Haufen kleiner Nachbarn um
// ihn herum, dazu zwei freistehende Begriffe weit draussen. ──────────────
function testgraph() {
    const kn = [], ka = [], pos = {};
    const k = (id, grad, x, y) => {
        kn.push({ id, name: 'Begriff ' + id, typ: 'konzept', grad, aliasse: [], zusammenfassung: '', sources: ['d.md'] });
        pos[id] = [x, y];
    };
    k('gross', 20, 5, 5);
    let i = 0;
    for (let gx = 0; gx < 6; gx++) {
        for (let gy = 0; gy < 6; gy++) {
            const id = 'klein' + (i++);
            // Abstand 0,6 Einheiten: bei ratio 1 nur 6 Bildpunkte – zu eng.
            k(id, 1 + (i % 4), 3.5 + gx * 0.6, 3.5 + gy * 0.6 + (gx === 2 && gy === 2 ? 0.3 : 0));
            ka.push({ von: 'gross', nach: id, art: 'nutzt', gewicht: 1, sources: [] });
        }
    }
    k('frei1', 2, 80, 80);
    k('frei2', 1, -70, 60);
    return { daten: { knoten: kn, kanten: ka, treffer: [], gesamt: kn.length, gefiltert: kn.length,
                      offset: 0, limit: 500, erzeugt: 1 }, pos };
}

function baueSeite(vorher) {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (er) => {
        const m = String(er && er.message || er);
        if (!/navigation|getContext|HTMLCanvasElement/.test(m)) { fehler.push(m); }
    });
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissensgraph', runScripts: 'outside-only',
                                   virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');
    const tg = testgraph();
    w.localStorage.setItem(POS, JSON.stringify(tg.pos));           // keine Neuanordnung
    Object.keys(vorher || {}).forEach((s) => w.localStorage.setItem(s, vorher[s]));
    const antwort = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body),
                                                headers: { get: () => null } });
    w.fetch = function (url) {
        const u = String(url).split('?')[0];
        if (u === '/api/me') { return antwort({ username: 'jarvis', is_admin: true, permissions: {} }); }
        if (u === '/api/wissensgraph/zugang') {
            return antwort({ stufe: 'global', gruppen: [], pflegen: true, steuern: true });
        }
        if (u === '/api/wissensgraph/graph') { return antwort(tg.daten); }
        if (u === '/api/wissensgraph/rueckmeldung') { return antwort({ verworfen: [] }); }
        if (u === '/api/wissensgraph/widersprueche') { return antwort({ befunde: [] }); }
        if (u === '/api/wissensgraph/status') {
            return antwort({ aktiv: true, laeuft: false, warteschlange: 0, erledigt: 0, fehler: 0, zaehler: {},
                             graph: {}, letzte_fehler: [], einstellungen: {}, nachlauf: {} });
        }
        return antwort({ ok: true });
    };
    // sigma-Attrappe mit Kamera, wie sigma 4 rechnet (siehe Kopf).
    const s = { renderer: null };
    w.HTMLCanvasElement.prototype.getContext = function (art) { return art === 'webgl2' ? {} : null; };
    w.JarvisSigma = { Sigma: function (graph, box, einst) {
        const hoerer = {};
        const kamHoerer = [];
        const kam = { x: 0, y: 0, ratio: 1 };
        const kamera = {
            on: (ev, fn) => { if (ev === 'updated') { kamHoerer.push(fn); } },
            setState: (z) => { Object.assign(kam, z); kamHoerer.forEach((fn) => fn(Object.assign({}, kam))); },
            getState: () => Object.assign({}, kam),
            reset: () => {}, animate: () => {}, zoomIn: () => {}, zoomOut: () => {},
        };
        this.graph = graph; this.einst = einst; this.kam = kam; this.kamera = kamera; this.hoerer = hoerer;
        this.refreshs = 0;
        this.on = (ev, fn) => { hoerer[ev] = fn; };
        this.refresh = () => { this.refreshs++; };
        this.kill = () => {}; this.resize = () => {};
        this.getCamera = () => kamera;
        this.getSetting = () => 14;
        this.graphToViewport = (p) => ({ x: (p.x - kam.x) / kam.ratio * MASS, y: (p.y - kam.y) / kam.ratio * MASS });
        this.framedGraphToViewport = this.graphToViewport;
        this.scaleSize = (g) => (g === undefined ? 1 : g) / Math.sqrt(kam.ratio);
        this.getNodeDisplayData = (n) => graph.hasNode(n) ? graph.getNodeAttributes(n) : null;
        s.renderer = this;
    } };
    MODULE.forEach((m) => w.eval(lies(m)));
    return { w, s, fehler };
}

// Was sigma zeichnet: Reduzierer-Ergebnis je Knoten.
function sichtbarkeit(s) {
    const R = s.renderer, G = R.graph, raus = { sichtbar: [], verborgen: [] };
    G.forEachNode((n, a) => {
        const r = R.einst.nodeReducer(n, {}, a);
        (r.visibility === 'hidden' ? raus.verborgen : raus.sichtbar).push(n);
    });
    return raus;
}

// Beruehren sich zwei sichtbare Punkte auf dem Bildschirm?
function beruehrungen(s, sichtbar) {
    const R = s.renderer, G = R.graph, p = sichtbar.map((n) => {
        const a = G.getNodeAttributes(n), v = R.graphToViewport(a);
        return { n, x: v.x, y: v.y, r: R.scaleSize(a.size) };
    });
    const paare = [];
    for (let i = 0; i < p.length; i++) {
        for (let j = i + 1; j < p.length; j++) {
            if (Math.hypot(p[i].x - p[j].x, p[i].y - p[j].y) < p[i].r + p[j].r) { paare.push(p[i].n + '/' + p[j].n); }
        }
    }
    return paare;
}

async function main() {
    const N = testgraph().daten.knoten.length;

    abschnitt('0. Positivkontrolle');
    const a = baueSeite();
    await warte(400);
    const R = a.s.renderer;
    if (!R || !R.einst || typeof R.einst.nodeReducer !== 'function' || R.graph.order !== N) {
        console.log('  ✗ Renderer-Attrappe nicht gebaut oder Graph unvollstaendig – Pruefstand kaputt');
        process.exit(2);
    }
    pruefe(true, 'Renderer mit Knoten-Reduzierer gebaut, ' + N + ' Begriffe geladen');
    pruefe(!!a.w.document.getElementById('wg-ausduennen') && !!a.w.document.getElementById('wg-mindest'),
           'Schalter und Regler stehen auf der Seite');

    abschnitt('1. Weit weg: ausgeduennt, ohne Beruehrung');
    let v = sichtbarkeit(a.s);
    pruefe(v.verborgen.length > 0, 'dichter Haufen wird ausgeduennt', v.verborgen.length + ' verborgen');
    pruefe(v.sichtbar.indexOf('gross') >= 0, 'der groesste Begriff bleibt sichtbar');
    pruefe(v.sichtbar.indexOf('frei1') >= 0 && v.sichtbar.indexOf('frei2') >= 0,
           'freistehende Begriffe bleiben sichtbar, auch die kleinen');
    const ber = beruehrungen(a.s, v.sichtbar);
    pruefe(ber.length === 0, 'keine zwei sichtbaren Punkte beruehren sich', ber.slice(0, 5).join(', '));
    const zeile = a.w.document.getElementById('wg-ausgeduennt');
    pruefe(!zeile.classList.contains('hidden') && zeile.textContent.indexOf(String(v.verborgen.length)) >= 0,
           'Zeile unter der Grafik nennt die Zahl der verborgenen', zeile.textContent);
    const weit = v.verborgen.length;

    abschnitt('2. Zoom bringt sie zurueck – und nimmt sie wieder');
    R.kamera.setState({ x: 5, y: 5, ratio: 0.02 });
    await warte(300);
    v = sichtbarkeit(a.s);
    pruefe(v.verborgen.length === 0, 'ganz nah: alle sichtbar', v.verborgen.join(','));
    pruefe(zeile.classList.contains('hidden'), 'ganz nah: Zeile verschwindet');
    R.kamera.setState({ x: 0, y: 0, ratio: 1 });
    await warte(300);
    pruefe(sichtbarkeit(a.s).verborgen.length === weit, 'zurueck auf weit: wieder ausgeduennt (gleiche Menge)');

    abschnitt('3. Schalter');
    const h = a.w.document.getElementById('wg-ausduennen');
    h.checked = false; h.dispatchEvent(new a.w.Event('change'));
    pruefe(sichtbarkeit(a.s).verborgen.length === 0, 'aus: alle Begriffe sichtbar');
    h.checked = true; h.dispatchEvent(new a.w.Event('change'));
    pruefe(sichtbarkeit(a.s).verborgen.length === weit, 'wieder an: ausgeduennt');

    abschnitt('4. Mindestgroesse');
    const regler = a.w.document.getElementById('wg-mindest');
    pruefe(Number(regler.max) >= 3, 'Regler reicht bis in die geladenen Groessen', 'max=' + regler.max);
    R.kamera.setState({ x: 5, y: 5, ratio: 0.02 });
    await warte(300);
    regler.value = '3'; regler.dispatchEvent(new a.w.Event('input'));
    v = sichtbarkeit(a.s);
    const unter = [];
    R.graph.forEachNode((n, at) => { if (at.grad < 3) { unter.push(n); } });
    pruefe(unter.length > 0 && unter.every((n) => v.verborgen.indexOf(n) >= 0),
           'ganz nah: alle unter 3 Verbindungen verborgen');
    pruefe(v.sichtbar.every((n) => R.graph.getNodeAttribute(n, 'grad') >= 3), 'sichtbar sind nur Begriffe ab 3');
    pruefe(zeile.textContent.indexOf(String(unter.length)) >= 0, 'Zeile nennt die Zahl unter der Mindestgroesse',
           zeile.textContent);
    pruefe(/3/.test(a.w.document.getElementById('wg-mindest-wert').textContent), 'Wert neben dem Regler zeigt 3');
    const gemerkt = a.w.localStorage.getItem(DICHTE);
    a.w.close();

    const b = baueSeite({ [DICHTE]: gemerkt });
    await warte(400);
    pruefe(b.w.document.getElementById('wg-mindest').value === '3', 'Mindestgroesse ueberlebt ein Neuladen');
    b.w.close();

    abschnitt('5. Ueberfahren und Suche zeigen Verborgenes');
    const c = baueSeite();
    await warte(400);
    const vor = sichtbarkeit(c.s).verborgen;
    pruefe(vor.length > 0, 'Vorbedingung: es gibt verborgene Nachbarn');
    c.s.renderer.hoerer.enterNode({ node: 'gross' });
    pruefe(sichtbarkeit(c.s).verborgen.length === 0, 'Ueberfahren des grossen Begriffs zeigt alle seine Nachbarn');
    c.s.renderer.hoerer.leaveNode({});
    pruefe(sichtbarkeit(c.s).verborgen.length === vor.length, 'nach dem Verlassen wieder ausgeduennt');
    const ziel = vor[0];
    const feld = c.w.document.getElementById('wg-suche');
    feld.value = 'Begriff ' + ziel; feld.dispatchEvent(new c.w.Event('input'));
    await warte(450);
    pruefe(sichtbarkeit(c.s).sichtbar.indexOf(ziel) >= 0, 'gesuchter, verborgener Begriff wird gezeigt', ziel);
    c.w.close();

    pruefe(a.fehler.concat(b.fehler, c.fehler).length === 0, 'keine Skriptfehler',
           a.fehler.concat(b.fehler, c.fehler).join(' | '));

    console.log('\nErgebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
}

main();
