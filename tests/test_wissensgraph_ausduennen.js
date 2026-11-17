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
 *   7. Neu anordnen: waehrend die Anordnung laeuft, gilt die Ausduennung
 *      SOFORT (nicht erst an ihrem Ende) und wird im Takt nachgemessen.
 *   6. Schwache Linien (ein Dokument) fallen weg, solange es IM BILD eng ist:
 *      weit weg verborgen, ganz nah und in einer freien Ecke sichtbar (auch
 *      wenn es ausserhalb des Bildes eng bleibt); starke Linien und
 *      Widersprueche bleiben immer; Ueberfahren und Schalter holen sie zurueck.
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
    // Eine starke Linie (drei Dokumente) und ein Widerspruch, beide vom grossen
    // Begriff aus – sie duerfen nie wegfallen.
    ka.push({ von: 'gross', nach: 'frei1', art: 'nutzt', gewicht: 3, sources: [] });
    ka.push({ von: 'gross', nach: 'frei2', art: 'widerspricht', gewicht: 1, sources: [] });
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
        this.getDimensions = () => ({ width: 800, height: 600 });
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

// Kanten nach dem Kanten-Reduzierer: schwach / stark / Widerspruch, je sichtbar?
function kanten(s) {
    const R = s.renderer, G = R.graph, raus = { schwachSichtbar: 0, schwachVerborgen: 0, starkSichtbar: 0,
                                                 widerspruchSichtbar: 0 };
    G.forEachEdge((k, a) => {
        const r = R.einst.edgeReducer(k, {}, a);
        const sicht = r.visibility !== 'hidden';
        if (a.widerspruch) { if (sicht) { raus.widerspruchSichtbar++; } }
        else if (!a.erwaehnt && a.gewicht > 1) { if (sicht) { raus.starkSichtbar++; } }
        else if (sicht) { raus.schwachSichtbar++; } else { raus.schwachVerborgen++; }
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

    abschnitt('6. Schwache Linien');
    const d = baueSeite();
    await warte(400);
    const RD = d.s.renderer;
    const SCHWACH = 36;              // gross -> klein0..35, je ein Dokument
    let kz = kanten(d.s);
    if (kz.schwachSichtbar + kz.schwachVerborgen !== SCHWACH) {
        console.log('  ✗ Testgraph traegt nicht die erwarteten schwachen Linien – Pruefstand kaputt');
        process.exit(2);
    }
    const zeileD = d.w.document.getElementById('wg-ausgeduennt');
    pruefe(kz.schwachVerborgen === SCHWACH, 'weit weg (eng im Bild): alle schwachen Linien verborgen',
           JSON.stringify(kz));
    pruefe(kz.starkSichtbar === 1 && kz.widerspruchSichtbar === 1, 'starke Linie und Widerspruch bleiben',
           JSON.stringify(kz));
    pruefe(/einem Dokument/.test(zeileD.textContent), 'Zeile unter der Grafik nennt die schwachen Linien',
           zeileD.textContent);
    RD.kamera.setState({ x: 5, y: 5, ratio: 0.02 });
    await warte(300);
    kz = kanten(d.s);
    pruefe(kz.schwachSichtbar === SCHWACH, 'ganz nah: schwache Linien wieder da', JSON.stringify(kz));
    pruefe(!/einem Dokument/.test(zeileD.textContent), 'ganz nah: Hinweis auf schwache Linien weg');
    // Freie Ecke: der Haufen liegt ausserhalb des Bildes und ist dort weiter
    // eng (Positivkontrolle), im Bild aber ist Platz.
    RD.kamera.setState({ x: -73, y: 57, ratio: 0.05 });
    await warte(300);
    const engDraussen = sichtbarkeit(d.s).verborgen.length;
    kz = kanten(d.s);
    pruefe(engDraussen > 0, 'Positivkontrolle: ausserhalb des Bildes bleibt es eng (' + engDraussen + ' verborgen)');
    pruefe(kz.schwachSichtbar === SCHWACH, 'freie Ecke: schwache Linien sichtbar, obwohl es draussen eng ist',
           JSON.stringify(kz));
    RD.kamera.setState({ x: 0, y: 0, ratio: 1 });
    await warte(300);
    pruefe(kanten(d.s).schwachVerborgen === SCHWACH, 'zurueck auf weit: wieder verborgen');
    // Nur verschieben, gleicher Zoom: die Platzmessung haengt nur am Abstand,
    // dieselben Begriffe bleiben verborgen – geaendert hat sich allein, dass
    // die Enge aus dem Bild ist. sigma muss trotzdem neu zeichnen.
    const vorVerborgen = sichtbarkeit(d.s).verborgen.join(',');
    const vorRefresh = RD.refreshs;
    RD.kamera.setState({ x: -200, y: -200, ratio: 1 });
    await warte(300);
    pruefe(sichtbarkeit(d.s).verborgen.join(',') === vorVerborgen,
           'Positivkontrolle: Verschieben aendert die verborgenen Begriffe nicht');
    pruefe(kanten(d.s).schwachSichtbar === SCHWACH && RD.refreshs > vorRefresh,
           'Enge aus dem Bild geschoben: schwache Linien sichtbar UND neu gezeichnet',
           'refresh ' + vorRefresh + ' -> ' + RD.refreshs);
    RD.kamera.setState({ x: 0, y: 0, ratio: 1 });
    await warte(300);
    RD.hoerer.enterNode({ node: 'gross' });
    pruefe(kanten(d.s).schwachSichtbar === SCHWACH, 'Ueberfahren zeigt die schwachen Linien des Begriffs');
    RD.hoerer.leaveNode({});
    const hd = d.w.document.getElementById('wg-ausduennen');
    hd.checked = false; hd.dispatchEvent(new d.w.Event('change'));
    pruefe(kanten(d.s).schwachSichtbar === SCHWACH, 'Schalter aus: schwache Linien sichtbar');
    d.w.close();

    abschnitt('7. Neu anordnen');
    const e = baueSeite();
    await warte(400);
    const RE = e.s.renderer;
    // Anordnungs-Attrappe: laeuft, bis gestoppt wird (wie der Worker), und
    // bewegt selbst nichts – Bewegung stellt der Test her.
    const fa2 = { laeuft: 0 };
    // Die Exporte des Bundles sind nur lesbar (Getter, nicht konfigurierbar) –
    // deshalb das ganze Objekt ersetzen, die echte Einstellungs-Ableitung bleibt.
    const echtFA2 = e.w.JarvisFA2;
    e.w.JarvisFA2 = { forceAtlas2: echtFA2.forceAtlas2, FA2Layout: function () {
        this.start = () => { fa2.laeuft++; };
        this.stop = () => {}; this.kill = () => { fa2.laeuft--; };
    } };
    const weitE = sichtbarkeit(e.s).verborgen.length;
    const reglerE = e.w.document.getElementById('wg-mindest');
    reglerE.value = '3'; reglerE.dispatchEvent(new e.w.Event('input'));
    const mitMin = sichtbarkeit(e.s).verborgen.length;
    e.w.document.getElementById('wg-anordnen').click();
    if (fa2.laeuft !== 1) {
        console.log('  ✗ Anordnungs-Attrappe wurde nicht gestartet – Pruefstand kaputt');
        process.exit(2);
    }
    pruefe(weitE > 0 && sichtbarkeit(e.s).verborgen.length === mitMin,
           'sofort nach "Neu anordnen": Ausduennung und Mindestgroesse gelten weiter',
           sichtbarkeit(e.s).verborgen.length + ' verborgen, erwartet ' + mitMin);
    // Die Anordnung zieht den Haufen weit auseinander: der Takt muss das
    // mitbekommen, solange sie noch laeuft.
    RE.graph.forEachNode((n, at) => { RE.graph.mergeNodeAttributes(n, { x: at.x * 100, y: at.y * 100 }); });
    await warte(600);
    const waehrend = sichtbarkeit(e.s).verborgen;
    pruefe(fa2.laeuft === 1, 'Positivkontrolle: Anordnung laeuft noch');
    pruefe(waehrend.every((n) => RE.graph.getNodeAttribute(n, 'grad') < 3) && waehrend.length < mitMin,
           'waehrend der Anordnung nachgemessen: Platz da, nur die Mindestgroesse verbirgt noch',
           waehrend.length + ' verborgen');
    // Zweiter Klick waehrend der ersten Anordnung: deren Zeitgeber darf den
    // NEUEN Lauf nicht vorzeitig beenden (dann waere der Takt weg und die
    // Punkte blieben halb angeordnet). Dauer aus derselben Formel wie im Modul.
    const dauer = Math.min(8000, 1500 + RE.graph.order * 2);
    e.w.document.getElementById('wg-anordnen').click();          // Lauf 2 startet jetzt
    await warte(Math.round(dauer * 0.6));
    e.w.document.getElementById('wg-anordnen').click();          // Lauf 3
    await warte(Math.round(dauer * 0.6));                        // Ende von Lauf 2 ist vorbei
    pruefe(fa2.laeuft === 1, 'zweiter Klick: der fruehere Zeitgeber beendet den neuen Lauf nicht',
           'laufende Anordnungen: ' + fa2.laeuft);
    e.w.close();

    pruefe(a.fehler.concat(b.fehler, c.fehler, d.fehler, e.fehler).length === 0, 'keine Skriptfehler',
           a.fehler.concat(b.fehler, c.fehler, d.fehler, e.fehler).join(' | '));

    console.log('\nErgebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
}

main();
