#!/usr/bin/env node
/**
 * /portal: Kachelgroesse gross/klein + einseitige Automatik.
 *
 * GEMELDET: "die Zahl der moeglichen Kacheln in /portal ist gestiegen, so dass
 * dort gescrollt werden muss. klein = nur Symbole mit Kurzbeschreibung plus
 * tooltip. (das Fabrikam Video wird dabei nie verkleinert. Ist eine automatische
 * Umschaltung moeglich?)"
 *
 * DIE WICHTIGSTE PRUEFUNG IST DAS NICHT-FLATTERN: eine Automatik, die bei
 * "kein Scrollbalken" wieder vergroessert, baut eine Endlosschleife
 * (gross -> Scrollbalken -> klein -> kein Scrollbalken -> gross -> ...). jsdom
 * rechnet kein Layout, deshalb werden `scrollHeight` und `innerHeight`
 * kontrolliert gesetzt und die Zustandswechsel GEZAEHLT.
 *
 * Aufruf:  node tests/test_portal_tiles.js
 */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const FE = path.join(ROOT, 'frontend');
let ok = 0, fail = 0;

function abschnitt(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function pruefe(name, bed, detail) {
    if (bed) { ok++; console.log(`  \x1b[32m✓\x1b[0m ${name}`); }
    else { fail++; console.log(`  \x1b[31m✗\x1b[0m ${name}${detail ? '  →  ' + detail : ''}`); }
}
const lies = (p) => fs.readFileSync(p, 'utf8');
const warte = (ms) => new Promise(r => setTimeout(r, ms));

const HTML = lies(path.join(FE, 'portal.html'));
const JS = lies(path.join(FE, 'js/portal_tiles.js'));

/* Ein Portal-Fenster mit dem ECHTEN Markup. `hoehe` = gemeldete Dokumenthoehe,
   `fenster` = innerHeight. Beides wird gesetzt, weil jsdom sie sonst mit 0
   meldet und die Automatik nie greifen wuerde – der Test waere gruen, ohne
   etwas zu pruefen. */
function fensterBauen(hoehe, fenster, wahl) {
    const vc = new VirtualConsole();
    const dom = new JSDOM(HTML, { runScripts: 'outside-only',
                                  url: 'https://jarvis.test/portal', virtualConsole: vc });
    const w = dom.window;
    if (wahl !== undefined && wahl !== null) w.localStorage.setItem('jarvis_portal_kompakt', wahl);
    Object.defineProperty(w, 'innerHeight', { value: fenster, writable: true });
    Object.defineProperty(w.document.documentElement, 'scrollHeight',
                          { get: () => hoehe(), configurable: true });
    Object.defineProperty(w.document.body, 'scrollHeight',
                          { get: () => hoehe(), configurable: true });
    w.t = (k) => ({ 'portal.tiles_small': 'Kacheln verkleinern',
                    'portal.tiles_large': 'Kacheln vergrößern' }[k] || '');
    w.eval(JS);
    /* DOMContentLoaded NICHT selbst ausloesen: jsdom feuert es, und ein zweites
       Ereignis liesse `start()` erneut laufen. Genau daran ist die erste Fassung
       gescheitert – zwei Klick-Handler, der Klick schaltete zweimal und damit
       sichtbar gar nicht. Die Idempotenz wird unten ausdruecklich geprueft. */
    return { w, dom };
}

(async () => {

// ══ 1. Markup und Einbindung ═══════════════════════════════════════════════
abschnitt('1. Markup, CSS und Einbindung');
pruefe('Umschalt-Knopf im echten Markup', HTML.indexOf('id="pt-size-btn"') > 0);
pruefe('zwei Symbole (verkleinern / vergroessern)',
       HTML.indexOf('id="pt-size-ico-small"') > 0 && HTML.indexOf('id="pt-size-ico-large"') > 0);
pruefe('Knopf steht vor dem Hell/Dunkel-Schalter',
       HTML.indexOf('id="pt-size-btn"') < HTML.indexOf('id="btn-theme-toggle"'));
pruefe('portal_tiles.js eingebunden', /<script[^>]+js\/portal_tiles\.js/.test(HTML));
pruefe('Beschreibungstext wird im Kompaktmodus verborgen',
       /body\.pt-kompakt \.pt-card-desc\s*\{[^}]*display:\s*none/.test(HTML));
pruefe('Titel bleibt sichtbar (keine display:none-Regel darauf)',
       !/body\.pt-kompakt \.pt-card-title\s*\{[^}]*display:\s*none/.test(HTML));
// VORGABE: das Video wird nie verkleinert.
pruefe('Video-Karte belegt im engen Raster zwei Spalten',
       /body\.pt-kompakt \.pt-card-video\s*\{[^}]*grid-column:\s*span 2/.test(HTML));
pruefe('Video-Karte hat eine Mindestbreite (schmales Fenster)',
       /body\.pt-kompakt \.pt-card-video\s*\{[^}]*min-width/.test(HTML));
pruefe('i18n: beide Schluessel in DE und EN',
       (lies(path.join(FE, 'js/i18n.js')).match(/'portal\.tiles_(small|large)'/g) || []).length === 4);

// ══ 1b. Kein Aufblitzen der grossen Kacheln ════════════════════════════════
/* GEMELDET: "beim Wechsel zu /portal werden zuerst die grossen Kacheln geladen
   und erst dann die kleinen". portal_tiles.js setzt die Klasse erst bei
   DOMContentLoaded – da hat der Browser die Kachelwand schon gross gezeichnet.
   Das Frueh-Skript muss deshalb SYNCHRON vor dem ersten Inhalt stehen. */
abschnitt('1b. Gespeicherte Wahl "klein" gilt vor dem ersten Zeichnen');
{
    const FRUEH = lies(path.join(FE, 'js/portal_tiles_frueh.js'));
    const dom0 = new JSDOM(HTML);
    const body = dom0.window.document.body;
    const tag = [...body.querySelectorAll('script[src]')]
        .find(s => /\/js\/portal_tiles_frueh\.js(\?|$)/.test(s.getAttribute('src')));
    pruefe('portal_tiles_frueh.js im Markup eingebunden', !!tag);
    pruefe('synchron (ohne defer/async)',
           !!tag && !tag.hasAttribute('defer') && !tag.hasAttribute('async'));
    // Vor ihm darf nur Skript stehen (theme_frueh.js), kein sichtbarer Inhalt.
    let davor = [];
    for (let el = body.firstElementChild; el && el !== tag; el = el.nextElementSibling) {
        if (el.tagName !== 'SCRIPT') davor.push(el.tagName + (el.id ? '#' + el.id : ''));
    }
    pruefe('steht vor jedem sichtbaren Inhalt (direkt hinter <body>)',
           !!tag && tag.parentElement === body && davor.length === 0, davor.join(', '));
    pruefe('steht vor der Kachelwand',
           !!tag && HTML.indexOf('portal_tiles_frueh.js') < HTML.indexOf('class="pt-cards'));
    dom0.window.close();

    for (const [wahl, soll] of [['1', true], ['0', false], [null, false]]) {
        const dom = new JSDOM('<!doctype html><body></body>',
                              { runScripts: 'outside-only', url: 'https://jarvis.test/portal' });
        if (wahl !== null) dom.window.localStorage.setItem('jarvis_portal_kompakt', wahl);
        dom.window.eval(FRUEH);
        pruefe(`Wahl ${JSON.stringify(wahl)} → ${soll ? 'sofort klein' : 'bleibt gross'}`,
               dom.window.document.body.classList.contains('pt-kompakt') === soll,
               dom.window.document.body.className);
        dom.window.close();
    }
    {
        // Gesperrter Speicher (z. B. Datenschutzmodus) darf die Seite nicht brechen.
        const dom = new JSDOM('<!doctype html><body></body>',
                              { runScripts: 'outside-only', url: 'https://jarvis.test/portal' });
        Object.defineProperty(dom.window, 'localStorage',
                              { get() { throw new Error('gesperrt'); } });
        let wurf = null;
        try { dom.window.eval(FRUEH); } catch (e) { wurf = e; }
        pruefe('gesperrter Speicher wirft nicht', wurf === null, wurf && wurf.message);
        dom.window.close();
    }
}

// ══ 1c. Gemerktes Ergebnis der Automatik ═══════════════════════════════════
/* GEMELDET (nach dem ersten Fix): "immer noch zuerst die grossen Symbole trotz
   Einstellung kleine Symbole". Im Chrome auf DEV gemessen: OHNE eigene Wahl
   zeichnete jeder Besuch ~750 ms gross – die kleinen Kacheln kamen von der
   Automatik, und die merkte sich nichts. Jetzt gilt ihr Ergebnis vor dem
   ersten Zeichnen, aber nur in einem Fenster, das hoechstens so gross ist. */
abschnitt('1c. Gemerkte Automatik gilt vor dem ersten Zeichnen');
{
    const FRUEH = lies(path.join(FE, 'js/portal_tiles_frueh.js'));
    function frueh(wahl, auto, breite, hoehe) {
        const dom = new JSDOM('<!doctype html><body></body>',
                              { runScripts: 'outside-only', url: 'https://jarvis.test/portal' });
        const w = dom.window;
        if (wahl !== null) w.localStorage.setItem('jarvis_portal_kompakt', wahl);
        if (auto !== null) w.localStorage.setItem('jarvis_portal_auto', auto);
        Object.defineProperty(w, 'innerWidth', { value: breite });
        Object.defineProperty(w, 'innerHeight', { value: hoehe });
        w.eval(FRUEH);
        const k = w.document.body.classList.contains('pt-kompakt');
        w.close();
        return k;
    }
    pruefe('gleiches Fenster → sofort klein', frueh(null, '1400x800', 1400, 800) === true);
    pruefe('kleineres Fenster → sofort klein', frueh(null, '1400x800', 1200, 700) === true);
    pruefe('hoeheres Fenster → gross (Automatik entscheidet neu)',
           frueh(null, '1400x800', 1400, 1000) === false);
    pruefe('breiteres Fenster → gross (Automatik entscheidet neu)',
           frueh(null, '1400x800', 1600, 800) === false);
    pruefe('eigene Wahl "gross" schlaegt die gemerkte Automatik',
           frueh('0', '1400x800', 1000, 600) === false);
    pruefe('kaputter Merker wird ignoriert', frueh(null, 'quatsch', 1000, 600) === false);
}

// ══ 2. Umschalten ══════════════════════════════════════════════════════════
abschnitt('2. Umschalten von Hand');
{
    const { w } = fensterBauen(() => 500, 900, null);
    await warte(20);
    pruefe('ohne Wahl startet es GROSS (wie bisher)',
           !w.document.body.classList.contains('pt-kompakt'));
    const b = w.document.getElementById('pt-size-btn');
    pruefe('Knopf nennt die Aktion "verkleinern"',
           b.getAttribute('title') === 'Kacheln verkleinern', b.getAttribute('title'));
    b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await warte(20);
    pruefe('nach dem Klick ist es kompakt', w.document.body.classList.contains('pt-kompakt'));
    pruefe('Beschriftung folgt dem Zustand',
           b.getAttribute('title') === 'Kacheln vergrößern', b.getAttribute('title'));
    pruefe('Symbol folgt dem Zustand',
           w.document.getElementById('pt-size-ico-small').style.display === 'none'
           && w.document.getElementById('pt-size-ico-large').style.display === '');
    pruefe('aria-pressed gesetzt', b.getAttribute('aria-pressed') === 'true');
    pruefe('die Wahl wird gemerkt',
           w.localStorage.getItem('jarvis_portal_kompakt') === '1');

    // Tooltip: der lange Text wandert, statt verloren zu gehen.
    const karte = w.document.querySelector('.pt-cards .pt-card:not(.pt-card-video)');
    const desc = karte.querySelector('.pt-card-desc');
    pruefe('Beschreibungstext steht im Tooltip',
           karte.getAttribute('title') === (desc.textContent || '').trim(),
           karte.getAttribute('title'));
    // Die Video-Karte hat keinen Text und darf keinen Tooltip bekommen.
    const video = w.document.querySelector('.pt-card-video');
    pruefe('die Video-Karte bekommt keinen Tooltip',
           !video || !video.getAttribute('title'));

    b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await warte(20);
    pruefe('zurueck auf gross', !w.document.body.classList.contains('pt-kompakt'));
    pruefe('der Tooltip verschwindet wieder (in der grossen Ansicht steht der '
           + 'Text sichtbar in der Kachel)', !karte.getAttribute('title'));
    pruefe('die Wahl "gross" wird ebenfalls gemerkt',
           w.localStorage.getItem('jarvis_portal_kompakt') === '0');
    w.close();
}

// ══ 3. Gespeicherte Wahl ═══════════════════════════════════════════════════
abschnitt('3. Die eigene Wahl gilt');
{
    const { w } = fensterBauen(() => 500, 900, '1');
    await warte(20);
    pruefe('gemerkt "klein" wird beim Laden angewandt (auch ohne Ueberlauf)',
           w.document.body.classList.contains('pt-kompakt'));
    w.close();
}
{
    // DER WICHTIGE FALL: der Benutzer will GROSS, obwohl gescrollt werden muss.
    // Eine Automatik, die das ueberstimmt, ist ein Fehler, keine Hilfe.
    const { w } = fensterBauen(() => 4000, 800, '0');
    await warte(20);
    pruefe('gemerkt "gross" bleibt gross, obwohl es ueberlaeuft',
           !w.document.body.classList.contains('pt-kompakt'));
    w.JarvisPortalTiles.pruefeUeberlauf();
    await warte(20);
    pruefe('die Automatik ueberstimmt die eigene Wahl NICHT',
           !w.document.body.classList.contains('pt-kompakt'));
    w.close();
}

// ══ 4. Automatik ═══════════════════════════════════════════════════════════
abschnitt('4. Automatik – nur ohne eigene Wahl, nur in Richtung klein');
{
    const { w } = fensterBauen(() => 4000, 800, null);
    await warte(20);
    pruefe('vor der Messung noch gross', !w.document.body.classList.contains('pt-kompakt'));
    w.JarvisPortalTiles.pruefeUeberlauf();
    await warte(20);
    pruefe('bei Ueberlauf schaltet sie auf klein',
           w.document.body.classList.contains('pt-kompakt'));
    pruefe('sie schreibt die Wahl NICHT fest (es war keine Entscheidung des '
           + 'Benutzers)', w.localStorage.getItem('jarvis_portal_kompakt') === null);
    w.close();
}
{
    const { w } = fensterBauen(() => 810, 800, null);
    await warte(20);
    w.JarvisPortalTiles.pruefeUeberlauf();
    await warte(20);
    pruefe('ein Ueberstand unter der Schwelle (10px) laesst sie in Ruhe',
           !w.document.body.classList.contains('pt-kompakt'));
    w.close();
}
{
    /* KEIN FLATTERN. Nachgestellt wird die Rueckkopplung: solange gross ist,
       laeuft das Dokument ueber; sobald klein ist, passt es. Eine zweiseitige
       Automatik wuerde hier endlos hin- und herschalten. Gezaehlt werden die
       Zustandswechsel ueber viele Messungen. */
    let wechsel = 0, kompakt = false;
    const { w } = fensterBauen(() => (kompakt ? 700 : 4000), 800, null);
    await warte(20);
    const beob = new w.MutationObserver(function () {
        const jetzt = w.document.body.classList.contains('pt-kompakt');
        if (jetzt !== kompakt) { kompakt = jetzt; wechsel++; }
    });
    beob.observe(w.document.body, { attributes: true, attributeFilter: ['class'] });
    for (let i = 0; i < 40; i++) { w.JarvisPortalTiles.pruefeUeberlauf(); await warte(2); }
    pruefe('bei Rueckkopplung genau EIN Zustandswechsel (kein Flattern)',
           wechsel === 1, 'wechsel=' + wechsel);
    pruefe('und der Endzustand ist klein', w.document.body.classList.contains('pt-kompakt'));
    beob.disconnect(); w.close();
}

// ══ 4c. Automatik merkt sich ihr Ergebnis ══════════════════════════════════
abschnitt('4c. Die Automatik merkt sich das Fenster, in dem sie umschaltet');
{
    const { w } = fensterBauen(() => 4000, 800, null);
    Object.defineProperty(w, 'innerWidth', { value: 1400, writable: true });
    await warte(20);
    w.JarvisPortalTiles.pruefeUeberlauf();
    await warte(20);
    pruefe('Umschalten auf klein merkt das Fenster',
           w.localStorage.getItem('jarvis_portal_auto') === '1400x800',
           w.localStorage.getItem('jarvis_portal_auto'));
    w.close();
}
{
    // Ein gemerktes groesseres Fenster deckt das jetzige ab und bleibt stehen.
    const { w } = fensterBauen(() => 4000, 800, null);
    Object.defineProperty(w, 'innerWidth', { value: 1400, writable: true });
    w.localStorage.setItem('jarvis_portal_auto', '1600x900');
    await warte(20);
    w.JarvisPortalTiles.pruefeUeberlauf();
    await warte(20);
    pruefe('ein umfassenderes gemerktes Fenster wird nicht verkleinert',
           w.localStorage.getItem('jarvis_portal_auto') === '1600x900',
           w.localStorage.getItem('jarvis_portal_auto'));
    w.close();
}
{
    // Volle Kette: das Frueh-Skript setzt klein, start() darf es NICHT
    // zuruecknehmen (vorher: setzen(w === '1') machte es wieder gross).
    const vc = new VirtualConsole();
    const dom = new JSDOM(HTML, { runScripts: 'outside-only',
                                  url: 'https://jarvis.test/portal', virtualConsole: vc });
    const w = dom.window;
    w.localStorage.setItem('jarvis_portal_auto', '1400x800');
    Object.defineProperty(w, 'innerWidth', { value: 1400 });
    Object.defineProperty(w, 'innerHeight', { value: 800 });
    w.eval(lies(path.join(FE, 'js/portal_tiles_frueh.js')));
    w.eval(JS);
    await warte(20);
    pruefe('start() behaelt das vom Frueh-Skript gesetzte "klein"',
           w.document.body.classList.contains('pt-kompakt'), w.document.body.className);
    const karte = w.document.querySelector('.pt-cards .pt-card:not(.pt-card-video)');
    pruefe('und die Tooltips sind gesetzt', !!karte && !!karte.getAttribute('title'));
    w.close();
}

// ══ 4b. Doppelter Start ════════════════════════════════════════════════════
abschnitt('4b. Ein zweiter Start bindet keinen zweiten Handler');
{
    const { w } = fensterBauen(() => 500, 900, null);
    await warte(20);
    // Zweiten Start erzwingen – wie ein zweites DOMContentLoaded oder eine
    // doppelte Skript-Einbindung.
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await warte(20);
    const b = w.document.getElementById('pt-size-btn');
    b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await warte(20);
    // Bei zwei Handlern schaltet der Klick zweimal und damit sichtbar gar nicht.
    pruefe('ein Klick schaltet genau einmal um',
           w.document.body.classList.contains('pt-kompakt'),
           'Klasse=' + w.document.body.className);
    w.close();
}

// ══ 5. Waechter im Quelltext ═══════════════════════════════════════════════
abschnitt('5. Regeln im Quelltext');
const CODE = JS.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
pruefe('die Automatik kehrt nie zu gross zurueck (kein setzen(false) darin)',
       !/pruefeUeberlauf[\s\S]{0,400}?setzen\(false\)/.test(CODE));
pruefe('sie prueft die eigene Wahl zuerst',
       CODE.indexOf('gewaehlt() !== null') > 0);
pruefe('die Video-Karte wird in der Tooltip-Schleife ausgenommen',
       /pt-card-video[\s\S]{0,60}return/.test(CODE));
pruefe('nur der SELBST gesetzte Tooltip wird entfernt (ptTip-Merker)',
       CODE.indexOf('ptTip') > 0);
pruefe('Sprachwechsel zieht die Tooltips nach',
       CODE.indexOf('jarvis-lang-changed') > 0);
pruefe('start() ist idempotent (Merker gegen zweiten Handler)',
       /_gestartet/.test(CODE));

// ─────────────────────────────────────────────────────────────────────────────
// Kachel-Beschreibungen: Markup und i18n muessen DECKUNGSGLEICH sein
// ─────────────────────────────────────────────────────────────────────────────
// ⚠ ALS REGEL UEBER ALLE KACHELN, nicht fuer eine: das Markup ist der
// RUECKFALL, der erscheint, bis `applyLang()` gelaufen ist. Weicht er ab,
// blitzt beim Laden der alte Text auf – und beim naechsten Textwechsel zieht
// jemand nur eine der beiden Stellen nach. Damit faellt auch eine kuenftige
// Kachel auf, ohne dass jemand eine Liste pflegt.
{
    const i18nQ = lies(path.join(FE, 'js/i18n.js'));
    const bloecke = i18nQ.split(/\n\s{4}(?:de|en):\s*\{/);
    // Der DEUTSCHE Block ist der erste nach dem Sprachschluessel.
    const deBlock = bloecke.length > 1 ? bloecke[1] : i18nQ;

    const dom = new JSDOM(HTML);
    const karten = [...dom.window.document.querySelectorAll('.pt-card-desc[data-i18n]')];
    pruefe('es gibt ueberhaupt Kachel-Beschreibungen (Positivkontrolle)',
           karten.length > 3, `gefunden: ${karten.length}`);

    let abweichend = [];
    for (const el of karten) {
        const key = el.getAttribute('data-i18n');
        const m = deBlock.match(
            new RegExp(`'${key.replace('.', '\\.')}':\\s*'((?:[^'\\\\]|\\\\.)*)'`));
        if (!m) { abweichend.push(`${key}: kein DE-Text`); continue; }
        const ausI18n = m[1].replace(/\\'/g, "'").replace(/\\\\/g, '\\');
        const ausMarkup = (el.textContent || '').trim();
        if (ausI18n !== ausMarkup) {
            abweichend.push(`${key}: Markup "${ausMarkup.slice(0, 40)}" != i18n "${ausI18n.slice(0, 40)}"`);
        }
    }
    pruefe('jede Kachel-Beschreibung stimmt mit ihrem DE-Text ueberein',
           abweichend.length === 0, abweichend.slice(0, 3).join(' | '));

    // ⚠ UND BEIDE SPRACHEN MUESSEN DEN SCHLUESSEL HABEN: ein nur auf Deutsch
    // nachgezogener Text laesst die englische Oberflaeche etwas anderes
    // behaupten (bei dieser Aenderung genau der Fall gewesen).
    let fehlend = [];
    for (const el of karten) {
        const key = el.getAttribute('data-i18n');
        const treffer = i18nQ.match(
            new RegExp(`'${key.replace('.', '\\.')}':`, 'g')) || [];
        if (treffer.length < 2) { fehlend.push(`${key} (${treffer.length}x)`); }
    }
    pruefe('jede Kachel-Beschreibung gibt es in DE UND EN',
           fehlend.length === 0, fehlend.slice(0, 3).join(', '));
}

console.log(`\n\x1b[1m${ok} bestanden, ${fail} fehlgeschlagen\x1b[0m`);
process.exit(fail ? 1 : 0);
})().catch(e => { console.error('\nABBRUCH:', e && e.stack || e); process.exit(2); });
