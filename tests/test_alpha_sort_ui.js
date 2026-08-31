/* ═══════════════════════════════════════════════════════════════════════
   Waechter: Einstellungs-Reiter und Portal-Kacheln stehen alphabetisch
   ───────────────────────────────────────────────────────────────────────
   Gemessen wird die EIGENSCHAFT, nicht eine Reihenfolge-Liste: der Waechter
   liest die Beschriftungen aus dem echten Markup, sortiert sie selbst und
   vergleicht. Ein kuenftiger Reiter faellt damit von selbst mit auf – eine
   abgetippte Sollreihenfolge waere beim naechsten Element falsch.

   `alpha_sort.js` wird WIRKLICH AUSGEFUEHRT (gegen die echten HTML-Dateien
   und das echte `i18n.js`). Eine Quelltext-Pruefung waere gruen, wenn jemand
   den Zuhoerer nie registriert oder frueh aussteigt.

   Ausgefuehrt: node tests/test_alpha_sort_ui.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const path = require('path');
// jsdom liegt je Maschine anders (Repo-`node_modules`, `/tmp/node_modules` auf
// DEV, `JSDOM_PATH`). Reihenfolge wie in den uebrigen Waechtern, aber tolerant –
// Exit 2, weil "konnte nicht laufen" nicht wie "bestanden" aussehen darf.
let JSDOM = null;
for (const kandidat of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom']) {
    if (!kandidat) continue;
    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const WURZEL = path.resolve(__dirname, '..');
const FE = path.join(WURZEL, 'frontend');

let ok = 0, fail = 0;
function pruefe(text, bedingung, zusatz) {
    // ⚠ Argumentreihenfolge wie in den uebrigen JS-Waechtern: (Text, Bedingung).
    // Vertauscht waere jede nicht-leere Zeichenkette wahr und der Lauf meldete
    // lauter OK, ohne eine Bedingung ausgewertet zu haben (Vorfall 2026-08-28).
    if (typeof text !== 'string' || typeof bedingung === 'string') {
        console.error('TESTFEHLER: pruefe(Text, Bedingung) vertauscht:', text);
        process.exit(2);
    }
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}

// Unbehandelte Zurueckweisungen sind ein FAIL, kein stiller Abbruch.
process.on('unhandledRejection', (e) => {
    fail++; console.log('  FAIL unbehandelte Zurueckweisung: ' + (e && e.message || e));
});

function lies(rel) { return fs.readFileSync(path.join(FE, rel), 'utf-8'); }

/** Wartet, bis jsdom mit dem Parsen fertig ist.
 *  ⚠ FALLSTRICK: direkt nach `new JSDOM` steht `readyState: 'loading'`.
 *  `i18n.js` verschiebt `applyLang()` dann auf `DOMContentLoaded` – wer sofort
 *  auswertet, prueft den Zustand VOR dem ersten Sortieren und bekommt eine
 *  unsortierte Liste gemeldet, obwohl der Code stimmt (erster Lauf 2026-08-31). */
function bereit(w) {
    return new Promise(res => {
        if (w.document.readyState !== 'loading') return setTimeout(res, 0);
        w.document.addEventListener('DOMContentLoaded', () => setTimeout(res, 0));
    });
}

/** Laedt eine echte Seite und fuehrt icons/i18n/alpha_sort darin aus. */
async function seite(datei) {
    const dom = new JSDOM(lies(datei), {
        url: 'https://localhost/' + datei.replace('.html', ''),
        runScripts: 'outside-only',
    });
    const w = dom.window;
    w.matchMedia = w.matchMedia || function () {
        return { matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
    };
    w.eval(lies('js/icons.js'));
    w.eval(lies('js/i18n.js'));          // ruft applyLang() sofort (readyState complete)
    w.eval(lies('js/alpha_sort.js'));
    await bereit(w);                     // applyLang() -> jarvis-lang-changed -> sortiert
    return { dom, w };
}

/** Sortierung, wie sie das Modul erzeugen soll – unabhaengig nachgerechnet. */
function sollOrdnung(texte, lang) {
    const cmp = new Intl.Collator(lang, {
        numeric: true, sensitivity: 'base', ignorePunctuation: true
    }).compare;
    return texte.slice().sort(cmp);
}

function beschriftungen(w, behaelter, auswahl, titel) {
    const box = w.document.querySelector(behaelter);
    return [].slice.call(box.querySelectorAll(auswahl))
        .filter(el => el.parentNode === box)
        .map(el => {
            const t = titel ? el.querySelector(titel) : el;
            return ((t ? t.textContent : '') || '').trim();
        });
}

(async () => {

// ═══ 1. Einstellungs-Reiter ═══════════════════════════════════════════════
console.log('\n1. Einstellungs-Reiter (/settings)');
{
    const { w } = await seite('settings.html');
    const roh = lies('settings.html');

    // Vorbedingung: im MARKUP steht "KI & System" noch vorn – sonst prueft der
    // Test unten nichts (er lebt davon, dass sich die Reihenfolge aendern MUSS).
    const ersterImMarkup = /class="settings-tab-btn active" data-settings-tab="([a-z_]+)"/.exec(roh);
    pruefe('im Markup steht der Profil-Reiter als erster/aktiver',
           !!ersterImMarkup && ersterImMarkup[1] === 'profiles',
           ersterImMarkup && ersterImMarkup[1]);

    const ist = beschriftungen(w, '.settings-tabs', '.settings-tab-btn', null);
    pruefe('es gibt ueberhaupt Reiter (>10)', ist.length > 10, ist.length);
    pruefe('die Reiter stehen alphabetisch (DE)',
           JSON.stringify(ist) === JSON.stringify(sollOrdnung(ist, 'de')),
           ist.join(' | '));
    pruefe('kein Reiter ohne Beschriftung', ist.every(t => t.length > 0));

    // Der erste Knopf ist jetzt NICHT mehr der Profil-Knopf – genau deshalb
    // darf app.js den Rueckfall nicht mehr an `settingsTabs[0]` haengen.
    const ersteBtn = w.document.querySelectorAll('.settings-tab-btn')[0];
    pruefe('der erste Knopf ist nach dem Sortieren nicht mehr "KI & System"',
           ersteBtn.dataset.settingsTab !== 'profiles', ersteBtn.dataset.settingsTab);
    pruefe('der Profil-Knopf ist ueber data-settings-tab weiter auffindbar',
           !!w.document.querySelector('.settings-tab-btn[data-settings-tab="profiles"]'));

    // Sprachwechsel: dieselbe Regel, andere Reihenfolge.
    w.setLang('en');
    const istEn = beschriftungen(w, '.settings-tabs', '.settings-tab-btn', null);
    pruefe('nach dem Sprachwechsel alphabetisch (EN)',
           JSON.stringify(istEn) === JSON.stringify(sollOrdnung(istEn, 'en')),
           istEn.join(' | '));
    pruefe('der Sprachwechsel aendert die Reihenfolge wirklich',
           JSON.stringify(istEn) !== JSON.stringify(ist),
           'DE und EN identisch – dann prueft der Fall nichts');
    pruefe('kein Reiter geht beim Sortieren verloren', istEn.length === ist.length,
           ist.length + ' -> ' + istEn.length);

    w.close();
}

// ═══ 2. Portal-Kacheln ════════════════════════════════════════════════════
console.log('\n2. Portal-Kacheln (/portal)');
{
    const { w } = await seite('portal.html');
    const box = w.document.querySelector('.pt-cards');
    const karten = [].slice.call(box.querySelectorAll('.pt-card')).filter(el => el.parentNode === box);

    const mitTitel = karten.filter(el => el.querySelector('.pt-card-title'));
    const titel = mitTitel.map(el => el.querySelector('.pt-card-title').textContent.trim());
    pruefe('es gibt Kacheln (>5)', mitTitel.length > 5, mitTitel.length);
    pruefe('die Kacheln stehen alphabetisch (DE)',
           JSON.stringify(titel) === JSON.stringify(sollOrdnung(titel, 'de')),
           titel.join(' | '));

    // Das Video bleibt am Ende – auch nach dem Sprachwechsel.
    const letzte = karten[karten.length - 1];
    pruefe('die Video-Karte steht am Ende',
           letzte.id === 'brand-portal-anim', letzte.id || letzte.className);
    pruefe('die Video-Karte traegt data-sort-last',
           letzte.hasAttribute('data-sort-last'));

    w.setLang('en');
    const nachher = [].slice.call(box.querySelectorAll('.pt-card')).filter(el => el.parentNode === box);
    const titelEn = nachher.filter(el => el.querySelector('.pt-card-title'))
                           .map(el => el.querySelector('.pt-card-title').textContent.trim());
    pruefe('nach dem Sprachwechsel alphabetisch (EN)',
           JSON.stringify(titelEn) === JSON.stringify(sollOrdnung(titelEn, 'en')),
           titelEn.join(' | '));
    pruefe('das Video bleibt auch nach dem Sprachwechsel letztes Element',
           nachher[nachher.length - 1].id === 'brand-portal-anim',
           nachher[nachher.length - 1].id);
    pruefe('keine Kachel geht verloren', nachher.length === karten.length,
           karten.length + ' -> ' + nachher.length);

    // REGEL statt Liste: jede Kachel braucht einen Titel oder die
    // Ende-Markierung – sonst rutscht sie still ans Ende.
    const ohne = karten.filter(el => !el.querySelector('.pt-card-title')
                                  && !el.hasAttribute('data-sort-last'));
    pruefe('jede Kachel hat einen Titel ODER data-sort-last',
           ohne.length === 0, ohne.map(e => e.id || e.className).join(', '));

    // Versteckte Kacheln werden MIT sortiert: sie werden spaeter per JS
    // eingeblendet, ohne dass noch einmal sortiert wird.
    const versteckt = karten.filter(el => el.classList.contains('hidden'));
    pruefe('auch versteckte Kacheln sind einsortiert (sie werden nachtraeglich eingeblendet)',
           versteckt.length > 0, versteckt.length);

    w.close();
}

// ═══ 3. Das Video wird NICHT angefasst, wenn es schon richtig steht ═══════
console.log('\n3. Es wird so wenig bewegt wie moeglich');
{
    const { w } = await seite('portal.html');
    // Zweiter Lauf in derselben Sprache: nichts darf mehr bewegt werden.
    const bewegt = w.JarvisAlphaSort.jetzt();
    pruefe('ein zweiter Lauf bewegt keinen Reiter/keine Kachel mehr',
           bewegt.kacheln === 0, JSON.stringify(bewegt));

    // Beweis, dass die Zaehlung ueberhaupt zaehlt (Positivkontrolle):
    const box = w.document.querySelector('.pt-cards');
    box.insertBefore(box.lastElementChild, box.firstElementChild);   // Video nach vorn
    const nochmal = w.JarvisAlphaSort.jetzt();
    pruefe('nach einer Stoerung wird wieder bewegt', nochmal.kacheln > 0, nochmal.kacheln);
    pruefe('und das Video steht danach wieder hinten',
           box.lastElementChild.id === 'brand-portal-anim', box.lastElementChild.id);
    w.close();
}

// ═══ 4. Einbindung auf beiden Seiten ══════════════════════════════════════
console.log('\n4. Einbindung');
for (const [datei, nach] of [['portal.html', 'branding.js'], ['settings.html', 'branding.js']]) {
    const s = lies(datei);
    const i = s.indexOf('alpha_sort.js');
    pruefe(datei + ': alpha_sort.js ist eingebunden', i > -1);
    // NACH branding.js: beide hoeren auf `jarvis-lang-changed`, und Branding
    // ersetzt dort `{marke}` – wer vorher sortiert, sortiert alte Texte.
    pruefe(datei + ': steht nach ' + nach, i > s.indexOf(nach),
           'alpha_sort=' + i + ' ' + nach + '=' + s.indexOf(nach));
    pruefe(datei + ': mit Cache-Buster eingebunden', /alpha_sort\.js\?v=\d+/.test(s));
}

// ═══ 5. app.js haengt den Rueckfall nicht mehr an einen Index ═════════════
console.log('\n5. app.js: der Rueckfall nennt den Reiter, statt ihn zu zaehlen');
{
    let src = fs.readFileSync(path.join(FE, 'js/app.js'), 'utf-8');
    // Kommentare entfernen – ein Waechter, der seine eigene Begruendung liest,
    // prueft nichts (Register).
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
    pruefe('kein `settingsTabs[<n>]` mehr im Code',
           !/settingsTabs\s*\[\s*\d+\s*\]/.test(code),
           (code.match(/settingsTabs\s*\[\s*\d+\s*\][^\n]*/g) || []).join(' ; '));
    const treffer = code.match(/btnProfiles\s*\.classList\.add\('active'\)/g) || [];
    pruefe('alle Rueckfaelle heben den Profil-Knopf hervor (11 Stellen)',
           treffer.length === 11, treffer.length);
    pruefe('btnProfiles wird ueber data-settings-tab="profiles" bestimmt',
           /btnProfiles\s*=\s*document\.querySelector\('\.settings-tab-btn\[data-settings-tab="profiles"\]'\)/.test(code));
}

console.log('\n' + (fail === 0 ? 'ALLE ' + ok + ' PRUEFUNGEN OK' : ok + ' OK, ' + fail + ' FAIL'));
process.exit(fail === 0 ? 0 : 1);

})().catch(e => { console.error('ABBRUCH:', e); process.exit(2); });
