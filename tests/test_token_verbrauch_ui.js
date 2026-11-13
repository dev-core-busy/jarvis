/* UI-Test: Token-Verbrauch-Analyse im Reiter "Protokolle" (jsdom, echte
 * settings.html, echte i18n.js / settings_bedienung.js / token_verbrauch.js).
 *
 * Getrieben ueber den ECHTEN Klappkopf (data-klick="tv-klappen"), nicht ueber
 * einen direkten Modulaufruf – sonst bliebe eine fehlende Verdrahtung im
 * Klick-Verteiler unsichtbar.
 *
 * Gemessen werden Eigenschaften: Anfrage-Parameter (ein LEERER Filterwert ist
 * ein Filter, "*" ist keiner), Kennzahlen, Saeulen = Zahl der Werte ungleich 0,
 * Legende und Tabelle, "ohne Zaehlung" als Strich statt 0, Beschriftung leerer
 * Werte, eingeschleustes HTML bleibt Text, ein Ladefehler bleibt stehen, die
 * Messgroesse zeichnet ohne neue Anfrage, und jeder Dienst-Schluessel, den das
 * Backend erzeugen kann, hat einen Namen in DE und EN.
 *
 * jsdom rechnet kein Layout: Breite, Ueberlappung und Tooltip-Lage misst das
 * hier NICHT (Register) – dafuer die Sichtpruefung im Browser.
 *
 * Lauf:  timeout 60 node tests/test_token_verbrauch_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
require('./lib/bilanz')();

const ROOT = path.resolve(__dirname, '..');
const lies = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
let ok = 0, fail = 0;

function pruefe(bed, text, detail) {
    if (bed) { ok++; console.log('  ✓ ' + text); }
    else { fail++; console.log('  ✗ ' + text + (detail ? ' – ' + detail : '')); }
}
function abschnitt(t) { console.log('\n' + t); }
function bilanz(code) {
    console.log('\n' + '='.repeat(62));
    console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
    console.log('='.repeat(62));
    process.exit(code === undefined ? (fail ? 1 : 0) : code);
}

const wachhund = setTimeout(() => { console.log('  ✗ ABBRUCH: Wachhund nach 40 s'); bilanz(2); }, 40000);
wachhund.unref && wachhund.unref();

const HTML = lies('frontend/settings.html');
const I18N = lies('frontend/js/i18n.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const BEDIENUNG = lies('frontend/js/settings_bedienung.js');
const MODUL = lies('frontend/js/token_verbrauch.js');

const BOESE = '<img src=x onerror="window.__xss=1">';
const T0 = 1794000000;
const ACHSE = [T0, T0 + 86400, T0 + 2 * 86400];
const ANTWORT = {
    von: T0, bis: T0 + 3 * 86400, tage: 7, raster: 'tag', gruppe: 'llm', filter: {},
    zeitachse: ACHSE,
    reihen: [
        { schluessel: 'anthropic · modell-a', ein: [1000, 0, 500], aus: [100, 0, 50], aufrufe: [3, 0, 1] },
        { schluessel: 'probe · ' + BOESE, ein: [0, 200, 0], aus: [0, 20, 0], aufrufe: [0, 2, 0] },
        { schluessel: '__uebrige__', anzahl: 4, ein: [10, 10, 0], aus: [1, 1, 0], aufrufe: [1, 1, 0] },
    ],
    tabelle: [
        { schluessel: 'anthropic · modell-a', aufrufe: 4, ein: 1500, aus: 150, ohne_angabe: 0, fehler: 0, ms: 4000 },
        { schluessel: 'probe · ' + BOESE, aufrufe: 2, ein: 200, aus: 20, ohne_angabe: 0, fehler: 1, ms: 200 },
        { schluessel: 'anthropic_session · ohne', aufrufe: 3, ein: 0, aus: 0, ohne_angabe: 3, fehler: 0, ms: 900 },
    ],
    summe: { aufrufe: 11, ein: 1720, aus: 172, cache_lesen: 900, ohne_angabe: 3, fehler: 1 },
    optionen: {
        llm: ['anthropic · modell-a', 'probe · ' + BOESE],
        benutzer: ['a.nutzer', ''],
        dienst: ['agent', 'wissensgraph_extraktion', 'neuer_dienst'],
        werkzeug: ['', 'knowledge_search'],
        kanal: ['browser', ''],
    },
    erfasst_seit: T0 - 3600, anzeige_benutzer: { 'a.nutzer': 'BEISPIEL\\a.nutzer' }, aufbewahrung_tage: 90,
};

function baue(antwortFn) {
    const dom = new JSDOM(HTML, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    w.fetch = (url) => {
        rufe.push(String(url));
        const pfad = String(url).split('?')[0];
        if (pfad !== '/api/logs/token_verbrauch') {
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        }
        const [status, daten] = antwortFn(String(url));
        return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(daten) });
    };
    w.authToken = 'T';
    w.eval(SITZUNG);
    w.eval(I18N);
    w.eval(BEDIENUNG);
    w.eval(MODUL);
    return { w, d: w.document, rufe };
}

const warte = (ms) => new Promise((r) => setTimeout(r, ms || 60));
const params = (url) => new URLSearchParams(url.split('?')[1] || '');

function waehle(d, w, id, wert) {
    const sel = d.getElementById(id);
    if (!Array.from(sel.options).some((o) => o.value === wert)) {
        // Register: sel.value auf eine fehlende Option verpufft still.
        throw new Error('Option ' + JSON.stringify(wert) + ' fehlt in #' + id);
    }
    sel.value = wert;
    sel.dispatchEvent(new w.Event('change'));
}

(async () => {
    abschnitt('0. Positivkontrolle: Abschnitt und Verdrahtung');
    let { w, d, rufe } = baue(() => [200, ANTWORT]);
    const kopf = d.querySelector('[data-klick="tv-klappen"]');
    const rumpf = d.getElementById('tv-section-body');
    pruefe(!!kopf && !!rumpf, 'Abschnitt steht in der echten settings.html');
    if (!kopf || !rumpf) bilanz(2);
    pruefe(!!kopf.closest('#settings-tab-telemetry'), 'liegt im Reiter Protokolle');
    pruefe(/\/static\/js\/token_verbrauch\.js\?v=\d+/.test(HTML), 'Modul ist in settings.html eingebunden');
    pruefe(rumpf.style.display === 'none', 'zu Beginn zugeklappt');
    kopf.click();
    await warte(80);
    pruefe(rumpf.style.display !== 'none', 'Klick auf den Kopf klappt auf');
    if (rumpf.style.display === 'none') bilanz(1);
    const erster = rufe.find((u) => u.startsWith('/api/logs/token_verbrauch'));
    const p0 = params(erster || '');
    pruefe(!!erster && p0.get('tage') === '7' && p0.get('gruppe') === 'llm',
           'laedt 7 Tage, aufgeteilt nach Sprachmodell', erster);
    pruefe(['llm', 'benutzer', 'dienst', 'werkzeug', 'kanal'].every((k) => !p0.has(k)),
           'ohne Filter: kein Filter-Parameter ("*" = alle)', erster);

    abschnitt('1. Kennzahlen');
    const kacheln = d.querySelectorAll('#tv-kennzahlen .tv-kachel');
    pruefe(kacheln.length === 4, 'vier Kennzahlen', String(kacheln.length));
    pruefe(kacheln[0] && kacheln[0].title.replace(/\D/g, '') === '1892', 'Gesamt = Eingabe + Ausgabe (genauer Wert im Tooltip)',
           kacheln[0] && kacheln[0].title);
    pruefe(kacheln[3] && kacheln[3].textContent.includes('11'), 'Aufrufe');
    const zusatz = d.getElementById('tv-zusatz').textContent;
    pruefe(/3 Aufrufe ohne Zählung/.test(zusatz) && /nicht in den Summen/.test(zusatz),
           'Aufrufe ohne Zaehlung werden genannt und als nicht summiert ausgewiesen', zusatz);
    pruefe(/900/.test(zusatz) && /1 fehlgeschlagen/.test(zusatz), 'Cache-Anteil und Fehlschlaege genannt', zusatz);

    abschnitt('2. Diagramm und Legende');
    const svg = d.querySelector('#tv-diagramm svg.tv-svg');
    pruefe(!!svg, 'SVG gezeichnet');
    const nichtNull = ANTWORT.reihen.reduce((a, r) => a + r.ein.filter((v, i) => v + r.aus[i] > 0).length, 0);
    const segs = d.querySelectorAll('#tv-diagramm rect.tv-seg');
    pruefe(segs.length === nichtNull, 'eine Teilsaeule je Wert ungleich 0', segs.length + ' / ' + nichtNull);
    pruefe(d.querySelectorAll('#tv-diagramm rect.tv-treffer').length === ACHSE.length,
           'je Zeiteimer eine Trefferflaeche (auch fuer leere Eimer)');
    pruefe(d.querySelectorAll('#tv-diagramm rect.tv-seg.tv-f1').length === 2
           && d.querySelectorAll('#tv-diagramm rect.tv-seg.tv-f-rest').length === 2,
           'Farbe je Reihe: groesste = tv-f1, Uebrige = tv-f-rest');
    pruefe(!svg.getAttribute('style') && !Array.from(segs).some((s) => s.getAttribute('fill')),
           'keine Farbwerte im Markup (nur Klassen aus dem Theme)');
    const leg = d.querySelectorAll('#tv-legende .tv-legende-eintrag');
    pruefe(leg.length === 3, 'Legende je Reihe', String(leg.length));
    pruefe(leg[2] && leg[2].textContent === 'Übrige (4)', 'Uebrige mit Anzahl der zusammengefassten Gruppen',
           leg[2] && leg[2].textContent);

    // Y-Achse: runde Marken. Die erste Fassung teilte eine Obergrenze in
    // Viertel (5 Mio. -> Marken bei 1,25 / 3,75 Mio., angezeigt "1,3 Mio.").
    const teil = w.TokenVerbrauch._achsenteilung;
    const proben = [1, 5, 7, 99, 1111, 3055438, 23412345, 0.4];
    const schlecht = proben.filter((m) => {
        const t = teil(m);
        const mant = t.schritt / Math.pow(10, Math.floor(Math.log10(t.schritt) + 1e-9));
        const rund = [1, 2, 2.5, 5].some((x) => Math.abs(mant - x) < 1e-9);
        return !(rund && t.n >= 1 && t.n <= 4 && t.oben >= m && t.oben - t.schritt < m
                 && Math.abs(t.oben - t.n * t.schritt) < 1e-6);
    });
    pruefe(!schlecht.length, 'Achsenteilung: Schritt 1/2/2,5/5 × 10^n, hoechstens 4 Schritte, knapp ueber dem Maximum',
           schlecht.map((m) => m + '->' + JSON.stringify(teil(m))).join(' '));
    const gitter = d.querySelectorAll('#tv-diagramm line').length;
    pruefe(gitter === teil(1111).n + 1, 'eine Gitterlinie je Marke', gitter + ' / ' + (teil(1111).n + 1));

    abschnitt('3. Tabelle');
    const zeilen = d.querySelectorAll('#tv-tbody tr');
    pruefe(zeilen.length === 3, 'eine Zeile je Gruppe (auch ohne eigene Reihe)', String(zeilen.length));
    const z0 = zeilen[0] ? Array.from(zeilen[0].cells).map((c) => c.textContent) : [];
    pruefe(z0[4] === '1.650' && z0[5] === '87,2 %' && z0[6] === '1.000 ms',
           'Summe, Anteil an der Gesamtsumme und mittlere Dauer', z0.join(' | '));
    const z2 = zeilen[2] ? Array.from(zeilen[2].cells).map((c) => c.textContent) : [];
    pruefe(z2[2] === '—' && z2[3] === '—' && z2[4] === '—' && z2[1] === '3',
           'Gruppe ganz ohne Zaehlung: Strich statt 0 bei den Tokens, Aufrufe stehen', z2.join(' | '));
    pruefe(/3 ohne Zählung/.test(z2[0] || ''), 'und nennt den Grund', z2[0]);
    pruefe(!zeilen[2].querySelector('.tv-punkt'), 'Farbmarke nur fuer Gruppen mit eigener Reihe');
    pruefe(d.getElementById('tv-tab-gruppe').textContent === 'Sprachmodell', 'Spaltenkopf nennt die Aufteilung');

    abschnitt('4. Auswahllisten');
    const opt = (id) => Array.from(d.getElementById(id).options).map((o) => [o.value, o.textContent]);
    pruefe(opt('tv-f-benutzer').some(([v, t]) => v === 'a.nutzer' && t === 'BEISPIEL\\a.nutzer'),
           'Benutzer mit Anzeigenamen');
    pruefe(opt('tv-f-benutzer').some(([v, t]) => v === '' && t === 'System (ohne Benutzer)'),
           'leerer Benutzer heisst "System"');
    pruefe(opt('tv-f-kanal').some(([v, t]) => v === '' && t === 'Hintergrund')
           && opt('tv-f-kanal').some(([v, t]) => v === 'browser' && t === 'Browser'),
           'Kanaele lesbar, leerer Kanal = Hintergrund');
    pruefe(opt('tv-f-werkzeug').some(([v, t]) => v === '' && t === 'ohne Werkzeug'), 'leeres Werkzeug lesbar');
    pruefe(opt('tv-f-dienst').some(([v, t]) => v === 'wissensgraph_extraktion' && t === 'Wissensgraph')
           && opt('tv-f-dienst').some(([v, t]) => v === 'neuer_dienst' && t === 'neuer_dienst'),
           'Dienst uebersetzt, unbekannter Schluessel bleibt lesbar stehen');
    pruefe(opt('tv-f-llm')[0][0] === '*', 'erste Option bleibt "Alle"');

    abschnitt('5. Eingeschleustes HTML bleibt Text');
    pruefe(!d.querySelector('#tv-section-body img') && !w.__xss, 'kein Element aus einem Modellnamen');
    pruefe(leg[1] && leg[1].textContent.includes('<img src=x'), 'Name steht als lesbarer Text in der Legende');
    pruefe(opt('tv-f-llm').some(([, t]) => t.includes('<img src=x')), '… und in der Auswahlliste');

    abschnitt('6. Filter und Anfrage');
    rufe.length = 0;
    waehle(d, w, 'tv-f-benutzer', '');
    await warte();
    let p = params(rufe[rufe.length - 1] || '');
    pruefe(p.has('benutzer') && p.get('benutzer') === '', 'leerer Wert wird als Filter geschickt', rufe.join(' '));
    pruefe(d.getElementById('tv-f-benutzer').value === '', 'Auswahl bleibt nach dem Neuladen stehen');
    waehle(d, w, 'tv-gruppe', 'werkzeug');
    await warte();
    p = params(rufe[rufe.length - 1] || '');
    pruefe(p.get('gruppe') === 'werkzeug' && p.has('benutzer'), 'Aufteilung wechselt, Filter bleibt', rufe[rufe.length - 1]);
    d.getElementById('tv-zuruecksetzen').click();
    await warte();
    p = params(rufe[rufe.length - 1] || '');
    pruefe(!p.has('benutzer') && d.getElementById('tv-f-benutzer').value === '*', 'Zuruecksetzen nimmt alle Filter weg');
    waehle(d, w, 'tv-zeitraum', '30');
    await warte();
    pruefe(params(rufe[rufe.length - 1] || '').get('tage') === '30', 'Zeitraum geht als tage mit');

    abschnitt('7. Messgroesse zeichnet ohne neue Anfrage');
    const vorher = rufe.length;
    const hoehe = () => Array.from(d.querySelectorAll('#tv-diagramm rect.tv-seg.tv-f1')).map((r) => r.getAttribute('height')).join(',');
    const hSumme = hoehe();
    waehle(d, w, 'tv-mass', 'aufrufe');
    await warte();
    pruefe(rufe.length === vorher, 'keine neue Anfrage');
    pruefe(hoehe() !== hSumme && hoehe() !== '', 'Saeulen neu gezeichnet', hSumme + ' -> ' + hoehe());

    abschnitt('8. Sprachwechsel');
    w._lang = 'en';
    d.dispatchEvent(new w.Event('jarvis-lang-changed'));
    await warte();
    const legEn = Array.from(d.querySelectorAll('#tv-legende .tv-legende-eintrag')).map((e) => e.textContent);
    pruefe(legEn.includes('Other (4)'), 'Legende neu beschriftet (EN)', legEn.join(' | '));
    pruefe(opt('tv-f-kanal').some(([v, t]) => v === '' && t === 'Background'), 'Auswahllisten neu beschriftet (EN)');
    w._lang = 'de';

    abschnitt('8b. Einzahl und Tausenderpunkt');
    ({ w, d, rufe } = baue(() => [200, Object.assign({}, ANTWORT, {
        summe: { aufrufe: 9, ein: 31273, aus: 1994, cache_lesen: 0, ohne_angabe: 1, fehler: 0 } })]));
    d.querySelector('[data-klick="tv-klappen"]').click();
    await warte(80);
    const z1 = d.getElementById('tv-zusatz').textContent;
    pruefe(/^1 Aufruf ohne Zählung/.test(z1), 'ein Aufruf ohne Zaehlung: Einzahl', z1);
    const kw = Array.from(d.querySelectorAll('#tv-kennzahlen .tv-kachel-wert')).map((e) => e.textContent);
    pruefe(kw[2] === '1.994' && kw[1] === '31.273', 'kleine Zahlen genau, mit Tausenderpunkt', kw.join(' | '));

    abschnitt('9. Leer- und Fehlerfaelle');
    ({ w, d, rufe } = baue(() => [200, Object.assign({}, ANTWORT, { reihen: [], tabelle: [], erfasst_seit: null,
        summe: { aufrufe: 0, ein: 0, aus: 0, cache_lesen: 0, ohne_angabe: 0, fehler: 0 } })]));
    d.querySelector('[data-klick="tv-klappen"]').click();
    await warte(80);
    pruefe(/noch keine Modellaufrufe erfasst/.test(d.getElementById('tv-diagramm').textContent),
           'nie etwas erfasst: sagt das ausdruecklich (statt eines leeren Diagramms)');
    ({ w, d, rufe } = baue(() => [200, Object.assign({}, ANTWORT, { reihen: [], tabelle: [] })]));
    d.querySelector('[data-klick="tv-klappen"]').click();
    await warte(80);
    pruefe(/mit diesen Filtern keine Modellaufrufe/.test(d.getElementById('tv-diagramm').textContent),
           'Zeitraum/Filter leer: andere Aussage als "nie erfasst"');
    ({ w, d, rufe } = baue(() => [500, { detail: 'kaputt' }]));
    d.querySelector('[data-klick="tv-klappen"]').click();
    await warte(80);
    const fe = d.getElementById('tv-fehler');
    pruefe(fe.style.display !== 'none' && /HTTP 500/.test(fe.textContent) && /kaputt/.test(fe.textContent),
           'Ladefehler wird mit Grund angezeigt', fe.textContent);
    await warte(300);
    pruefe(fe.style.display !== 'none', 'und bleibt stehen');

    abschnitt('10. Uebersetzungen vollstaendig');
    const sek = HTML.slice(HTML.indexOf('data-klick="tv-klappen"'), HTML.indexOf('data-klick="tele-convlog-klappen"'));
    pruefe(sek.length > 1000, 'Positivkontrolle: Abschnitt im Markup geschnitten (' + sek.length + ' Zeichen)');
    const schl = new Set();
    (sek.match(/data-i18n(?:-html|-title|-placeholder)?="([^"]+)"/g) || []).forEach((m) => schl.add(m.split('"')[1]));
    (MODUL.match(/T\('([a-z_.]+)'/g) || []).map((m) => m.slice(3, -1)).filter((k) => !k.endsWith('.') && !k.endsWith('_'))
        .forEach((k) => schl.add(k));
    ['llm', 'benutzer', 'dienst', 'werkzeug', 'kanal'].forEach((dim) => {
        schl.add('tv.leer_' + dim);
        schl.add('tv.g_' + dim);
    });
    // Jeder Dienst-Schluessel, den das Backend erzeugen kann: Module mit einem
    // generate_response-Aufruf (main.py ausgenommen – dort benennt die Tabelle
    // _FUNKTIONS_DIENSTE jede Funktion) plus die Werte dieser Tabelle.
    const tvPy = lies('backend/token_verbrauch.py');
    const tabelle = (tvPy.match(/\): "([a-z_]+)",/g) || []).map((m) => m.split('"')[1]);
    const dateien = [];
    (function such(dir) {
        fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true }).forEach((e) => {
            const rel = dir + '/' + e.name;
            if (e.isDirectory() && e.name !== '__pycache__' && e.name !== 'broker') such(rel);
            else if (e.name.endsWith('.py')) dateien.push(rel);
        });
    })('backend');
    const aufrufer = dateien.filter((f) => !/\/(llm|token_verbrauch|main)\.py$/.test(f)
        && /\.generate_response\(/.test(lies(f).replace(/#.*$/gm, '')))
        .map((f) => path.basename(f, '.py'));
    pruefe(aufrufer.length >= 10 && aufrufer.includes('agent'), 'Positivkontrolle: Aufrufer gefunden (' + aufrufer.length + ')');
    pruefe(tabelle.includes('sicherheitspruefung'), 'Positivkontrolle: Funktions-Tabelle gelesen (' + tabelle.length + ')');
    const mainFns = (lies('backend/main.py').match(/\n(?:async )?def (\w+)\([^]*?(?=\n(?:async )?def |\n@)/g) || [])
        .filter((b) => /\.generate_response\(/.test(b)).map((b) => b.match(/def (\w+)/)[1]);
    const ohneDienst = mainFns.filter((f) => !new RegExp('"backend\\.main", "' + f + '"').test(tvPy));
    pruefe(mainFns.length >= 3 && !ohneDienst.length, 'jede Aufrufstelle in main.py hat einen eigenen Dienst',
           'ohne: ' + ohneDienst.join(', '));
    aufrufer.concat(tabelle).forEach((k) => schl.add('tv.d.' + k));
    const fehlt = [];
    schl.forEach((k) => {
        const n = I18N.split("'" + k + "'").length - 1;
        if (n < 2) fehlt.push(k + ' (' + n + 'x)');
    });
    pruefe(schl.size > 40, 'Positivkontrolle: Schluessel gesammelt (' + schl.size + ')');
    pruefe(!fehlt.length, 'alle in DE und EN', fehlt.join(', '));

    w.close();
    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
