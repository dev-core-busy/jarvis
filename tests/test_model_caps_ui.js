#!/usr/bin/env node
/**
 * Fähigkeiten-Panel in der Profilzeile: wandern, umschalten, SCROLLEN.
 *
 * GEMELDET (2026-08-11): "ein Container öffnen (durch Klick auf das I-Symbol)
 * erweitert den Container nach unten, aber der geöffnete Container wird nicht
 * gescrollt, so dass der Benutzer nicht direkt sieht, dass etwas geöffnet wurde."
 *
 * Ein Quelltext-Test kann das nicht beweisen – deshalb hier echtes DOM mit
 * gesetzten Geometrien: jsdom rechnet kein Layout, also werden
 * getBoundingClientRect/scrollBy/clientHeight kontrolliert gestellt und geprüft,
 * WIE WEIT gescrollt wird. Die beiden Regeln, die dabei zählen:
 *   1. nur so weit, dass das Panel-Ende sichtbar wird,
 *   2. NIE so weit, dass die Oberkante der angeklickten Karte verschwindet –
 *      sonst sieht man ein Panel, ohne zu wissen, zu welchem Profil es gehört.
 *
 *   node tests/test_model_caps_ui.js
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

const JS = fs.readFileSync(path.join(ROOT, 'frontend/js/model_caps.js'), 'utf8');

/* Baut Liste + Panel, wie settings.html es tut, und stellt die Geometrie.
 * kartenTop / panelHoehe in Pixeln relativ zum Scroll-Container (0..600). */
function bauen(opt) {
    opt = opt || {};
    const dom = new JSDOM(`<!doctype html><html><body>
        <div class="modal-body" id="scroller">
          <div id="profiles-container" class="profiles-list"></div>
          <div id="model-caps-box" class="model-caps-box" style="display:none"></div>
        </div></body></html>`,
        { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');

    const gescrollt = [];
    const scroller = w.document.getElementById('scroller');
    // Scroll-Container: overflowY auto + scrollHeight > clientHeight
    Object.defineProperty(scroller, 'clientHeight', { value: 600, configurable: true });
    Object.defineProperty(scroller, 'scrollHeight', { value: 4000, configurable: true });
    scroller.scrollBy = (o) => gescrollt.push(o);
    w.getComputedStyle = (el) => ({ overflowY: el === scroller ? 'auto' : 'visible' });
    w.scrollBy = (o) => gescrollt.push(Object.assign({ fenster: true }, o));
    w.requestAnimationFrame = (fn) => fn();          // synchron messen
    scroller.getBoundingClientRect = () => ({ top: 0, bottom: 600, height: 600 });

    // Eine Profil-Karte
    const karte = w.document.createElement('div');
    karte.className = 'profile-card';
    karte.getBoundingClientRect = () => ({
        top: opt.kartenTop == null ? 500 : opt.kartenTop, bottom: 560, height: 60,
    });
    w.document.getElementById('profiles-container').appendChild(karte);

    const box = w.document.getElementById('model-caps-box');
    // Panel-Höhe je nach Inhalt: der Ladehinweis ist klein, das fertige Panel groß
    // Das Panel sitzt unter der Liste: seine Oberkante ist `panelTop`,
    // die Hoehe haengt am Inhalt (Ladehinweis klein, fertiges Panel gross).
    // Das Panel sitzt IN der Karte, unter deren Zeile: Oberkante = Karte + 60.
    box.getBoundingClientRect = () => {
        const h = (box.innerHTML.length > 200) ? (opt.panelHoehe || 400) : 40;
        const t = (opt.kartenTop == null ? 500 : opt.kartenTop) + 60;
        return { top: t, bottom: t + h, height: h };
    };

    // fetch-Attrappe: liefert eine vollständige Antwort
    const antwort = opt.antwort || {
        ok: true, quelle: 'ollama-show', modell: 'gemma4:31b', anzeige_name: '',
        beschreibung: '', grenzen: { kontext_tokens: 262144, parameter: '31.3B' },
        roh: ['completion', 'tools', 'vision'], hinweise: [],
        jarvis: [{ art: 'info', text: 'Hinweis eins.' }, { art: 'info', text: 'Hinweis zwei.' }],
        faehigkeiten: { text: true, vision: true, tools: true, thinking: true,
                        bild: false, embedding: false, audio: false },
    };
    const geholt = [];
    // Die Probe laeuft automatisch mit – /capabilities/probe braucht deshalb eine
    // EIGENE Antwort, sonst bekaeme sie die Metadaten zurueck.
    w.fetch = (url, o) => {
        geholt.push({ url, body: JSON.parse((o && o.body) || '{}') });
        const d = /probe$/.test(url)
            ? (opt.probeAntwort || { ok: true, faehigkeiten: {}, hinweise: [] })
            : antwort;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
    };
    w.t = (k) => null;                                // Fallbacks der Datei nutzen
    w.eval(JS);
    return { w, karte, box, gescrollt, geholt, scroller };
}

const warten = () => new Promise(r => setTimeout(r, 5));

(async () => {
    // ════════════════════════════════════════════════════════════════════════
    abschnitt('1. Panel wandert IN die Karte und wird gefüllt');
    {
        const u = bauen();
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'openai_compatible',
                                         model: 'gemma4:31b', api_url: 'http://x/v1' }, u.karte);
        await warten();
        pruefe(u.box.parentNode === u.karte,
               'das Panel haengt IM Container des Profils');
        pruefe(!/mc-jarvis[^>]*>[^<]*TTS/.test(u.box.innerHTML),
               'kein immergleicher TTS/STT-Hinweis in der Box');
        pruefe(u.karte.classList.contains('is-caps'), 'die Karte ist als offen markiert');
        pruefe(u.box.style.display !== 'none', 'das Panel ist sichtbar');
        pruefe(/gemma4:31b/.test(u.box.innerHTML), 'Modellname gerendert');
        pruefe((u.box.innerHTML.match(/mc-row/g) || []).length === 7,
               'alle sieben Merkmale als Zeile');
        pruefe(u.geholt.length === 1 && /capabilities$/.test(u.geholt[0].url),
               'genau ein Abruf auf /api/profiles/capabilities');
        pruefe(u.geholt[0].body.profile_id === 'p1' && !('api_key' in u.geholt[0].body),
               'Profil-Id mitgeschickt, KEIN Schlüssel im Browser');
    }

    // ════════════════════════════════════════════════════════════════════════
    abschnitt('2. Das Scrollen – der gemeldete Fehler');
    {
        // Karte am unteren Rand (top 500 von 600 sichtbar), Panel 400 hoch:
        // das Panel endet bei 960, also 360 px unter dem Sichtfenster.
        // Panel-Oberkante bei 560 (Container 0..600), Höhe 400 -> Ende bei 960,
        // also 360 px unter dem Sichtfenster.
        const u = bauen({ kartenTop: 500, panelHoehe: 400 });
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: 'm' }, u.karte);
        await warten();
        pruefe(u.gescrollt.length >= 1, 'es wird überhaupt gescrollt',
               JSON.stringify(u.gescrollt));
        const letzte = u.gescrollt[u.gescrollt.length - 1];
        pruefe(letzte && letzte.top > 0, 'nach UNTEN gescrollt (positives Delta)');
        // Spielraum = kartenTop - containerTop - 12 = 488. Nötig = 960-600+12 = 372.
        // nötig = 560+400-600+12 = 372; Spielraum = 500-0-12 = 488 -> 372
        pruefe(letzte.top === 372,
               'genau so weit, dass das Panel-Ende sichtbar wird (372 px)',
               String(letzte.top));
        pruefe(letzte.behavior === 'smooth',
               'sanft – die Bewegung ist die Rückmeldung an den Benutzer');
        pruefe(!letzte.fenster, 'der Scroll-Container wurde gefunden (nicht das Fenster)');
    }
    {
        // Sehr hohes Panel: das Nötige (900) übersteigt den Spielraum (488) –
        // dann darf NUR bis zur Karten-Oberkante gescrollt werden.
        const u = bauen({ kartenTop: 500, panelHoehe: 940 });
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: 'm' }, u.karte);
        await warten();
        const letzte = u.gescrollt[u.gescrollt.length - 1];
        // nötig = 560+940-600+12 = 912; Spielraum = 488 -> gedeckelt auf 488
        pruefe(letzte.top === 488,
               'gedeckelt: die Karten-Oberkante bleibt im Blick (488 px)',
               String(letzte.top));
    }
    {
        // Karte oben, kleines Panel -> alles sichtbar -> KEIN Scrollen
        const u = bauen({ kartenTop: 20, panelHoehe: 300 });
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: 'm' }, u.karte);
        await warten();
        pruefe(u.gescrollt.length === 0,
               'schon vollständig sichtbar -> gar kein Scrollen (kein Ruckeln)');
    }
    {
        // Ohne scrollbaren Vorfahren (Vollbild-Modus) muss das FENSTER scrollen
        const u = bauen({ kartenTop: 500, panelHoehe: 400 });
        u.w.getComputedStyle = () => ({ overflowY: 'visible' });
        Object.defineProperty(u.w, 'innerHeight', { value: 600, configurable: true });
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: 'm' }, u.karte);
        await warten();
        const letzte = u.gescrollt[u.gescrollt.length - 1];
        pruefe(letzte && letzte.fenster === true,
               'kein Scroll-Container -> window.scrollBy (Vollbild-Modus)');
    }

    // ════════════════════════════════════════════════════════════════════════
    abschnitt('3. Umschalten und Wechseln');
    {
        const u = bauen();
        const p1 = { id: 'p1', provider: 'x', model: 'm' };
        await u.w.ModelCaps.fuerProfil(p1, u.karte);
        await warten();
        await u.w.ModelCaps.fuerProfil(p1, u.karte);       // zweiter Klick
        await warten();
        pruefe(u.box.style.display === 'none' && u.box.innerHTML === '',
               'zweiter Klick auf dasselbe Profil schliesst');
        pruefe(!u.karte.classList.contains('is-caps'), 'Markierung entfernt');
        pruefe(u.box.parentNode.id === 'scroller', 'nach dem Schliessen ist es heimgekehrt');
        pruefe(u.geholt.length === 1, 'kein zweiter Abruf beim Schliessen');

        // Zweite Karte: Panel wandert dorthin und laedt neu
        const k2 = u.w.document.createElement('div');
        k2.className = 'profile-card';
        k2.getBoundingClientRect = () => ({ top: 100, bottom: 160, height: 60 });
        u.w.document.getElementById('profiles-container').appendChild(k2);
        await u.w.ModelCaps.fuerProfil(p1, u.karte);
        await warten();
        await u.w.ModelCaps.fuerProfil({ id: 'p2', provider: 'x', model: 'm2' }, k2);
        await warten();
        pruefe(u.box.parentNode === k2, 'das Panel wandert in die andere Karte');
        pruefe(!u.karte.classList.contains('is-caps') && k2.classList.contains('is-caps'),
               'nur EINE Karte ist markiert');
        pruefe(u.geholt.length === 3, 'für das andere Profil wird neu abgefragt');
    }

    // ════════════════════════════════════════════════════════════════════════
    abschnitt('4. heim(): der Fallstrick beim Neuaufbau der Liste');
    {
        const u = bauen();
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: 'm' }, u.karte);
        await warten();
        pruefe(u.box.parentNode === u.karte, 'Panel liegt in der Karte');
        u.w.ModelCaps.heim();
        pruefe(u.box.parentNode.id === 'scroller' && u.box.innerHTML === '',
               'heim() räumt Inhalt und Markierung ab (Liste wird neu gebaut)');
        pruefe(!u.karte.classList.contains('is-caps'), 'Markierung nach heim() weg');
        // Genau das nachstellen: Liste leeren, Panel muss überleben
        u.w.document.getElementById('profiles-container').innerHTML = '';
        pruefe(!!u.w.document.getElementById('model-caps-box'),
               'nach dem Leeren der Liste existiert das Panel noch');
    }

    // ════════════════════════════════════════════════════════════════════════
    abschnitt('5. Drei Zustände und die Probe');
    {
        const u = bauen({
            probeAntwort: { ok: true, faehigkeiten: { vision: false, tools: null },
                            hinweise: [] },
            antwort: {
                ok: true, quelle: 'openai-models', modell: 'Qwen', faehigkeiten: {
                    text: true, vision: null, tools: null, thinking: null,
                    bild: null, embedding: null, audio: null },
                grenzen: { kontext_tokens: 1010000 }, roh: [], hinweise: ['Server schweigt.'],
                jarvis: [],
            },
        });
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'openai_compatible',
                                         model: 'Qwen', api_url: 'http://x/v1' }, u.karte);
        await warten();
        const h = u.box.innerHTML;
        // vision wurde von der automatischen Probe auf "nein" gesetzt, tools blieb
        // unbekannt (null aus der Probe ueberschreibt nichts) -> 5 x "?"
        pruefe((h.match(/is-unknown/g) || []).length === 5,
               'unbekannte Merkmale bleiben "?" (nicht "nein")',
               String((h.match(/is-unknown/g) || []).length));
        pruefe(/is-yes/.test(h), 'Text=ja bleibt ein Häkchen');
        pruefe(/unknown_hint|\?" hei/.test(h) || /keine Angabe/.test(h),
               'das "?" wird erklärt');
        pruefe(!/id="mc-probe"/.test(h), 'kein Probe-Knopf mehr');

        // Die Probe lief AUTOMATISCH mit – geprüft wird die zweite Anfrage
        pruefe(u.geholt.length === 2 && /probe$/.test(u.geholt[1].url),
               'die Probe wurde ohne Zutun ausgeführt', JSON.stringify(u.geholt.map(x => x.url)));
        pruefe(JSON.stringify(u.geholt[1].body.welche) === '["vision","tools"]',
               'geprobt wird genau das, was unbekannt war');
        pruefe(/is-no/.test(h), 'die automatische Probe setzt vision auf "nein"');
        pruefe((h.match(/mc-probed/g) || []).length === 2,
               'ein Merkmal markiert + die Legende erklaert das Zeichen',
               String((h.match(/mc-probed/g) || []).length));
        pruefe(/mc-legend/.test(h) && /Testanfrage/.test(h),
               'die Legende sagt, was der Punkt bedeutet');
    }
    {
        // Alles aus den Metadaten bekannt (Ollama) -> KEINE Probe, KEINE Legende
        const u = bauen();
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'openai_compatible',
                                         model: 'gemma4:31b' }, u.karte);
        await warten();
        pruefe(u.geholt.length === 1,
               'nichts unbekannt -> keine zweite Anfrage (keine Tokens verbrannt)');
        pruefe(!/mc-legend/.test(u.box.innerHTML),
               'ohne Probe keine Legende (kein Rauschen)');
        pruefe(!/mc-probing/.test(u.box.innerHTML), 'und kein Status-Text');
    }
    {
        // Profil ohne Modell: Klartext statt leerem Kasten
        const u = bauen();
        await u.w.ModelCaps.fuerProfil({ id: 'p1', provider: 'x', model: '' }, u.karte);
        await warten();
        pruefe(/mc-note is-warn/.test(u.box.innerHTML), 'ohne Modell: Warnhinweis');
        pruefe(u.geholt.length === 0, 'ohne Modell wird gar nicht abgefragt');
    }

    console.log('\n' + '='.repeat(70));
    console.log('Ergebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
})();
