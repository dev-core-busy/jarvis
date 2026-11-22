/* UI-Waechter: Auswahllisten als gestaltbare Auswahl (base-select).
 *
 * VORFALL (2026-11-21, DEV und ECHT, Chrome): Protokolle → Sicherheitsprotokoll
 * → "Ereignis" – ein Klick oeffnete die Liste und waehlte SOFORT einen Eintrag.
 * Ursache: 21 Eintraege, Chromes Betriebssystem-Menue passte weder unter noch
 * ueber das Feld und wurde UEBER das Feld geschoben; das Loslassen der
 * Maustaste traf einen Eintrag. Behebung: theme.css stellt alle einfachen
 * Auswahlfelder auf `appearance: base-select` (die Liste wird in der Seite
 * gezeichnet, begrenzt und rollt), `js/auswahlliste.js` haelt die Breite stabil
 * (base-select richtet sie nach dem GEWAEHLTEN Eintrag, nicht nach dem
 * laengsten).
 *
 * Was jsdom NICHT kann: Layout und das Menue selbst. Ob die Liste das Feld
 * ueberdeckt, misst tests/live_auswahlliste_ui_dev.py in Chrome. Hier gemessen:
 *   Teil 1 – das Modul AUSGEFUEHRT, mit einer Layout-Attrappe, die das
 *            base-select-Verhalten nachbildet (Breite = gewaehlter Eintrag)
 *   Teil 2 – die REGELN ueber die Stylesheets, am geparsten CSS-Baum
 *   Teil 3 – die Einbindung je Seite
 *
 * Lauf:  timeout 120 node tests/test_auswahlliste_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const MODUL = fs.readFileSync(path.join(ROOT, 'frontend/js/auswahlliste.js'), 'utf8');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let BILANZ = false;
const WACHHUND = require('./lib/wachhund')(() => {
    console.log('❌ ABBRUCH: Lauf haengt (Wachhund 60 s)');
    process.exit(1);
}, 60000);
process.on('exit', (c) => {
    if (!BILANZ && c === 0) {
        console.log('❌ ABBRUCH: keine Bilanzzeile – der Lauf ist nicht durchgelaufen');
        process.exitCode = 1;
    }
});

function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function abbruch(t) {
    console.log('❌ ABBRUCH: ' + t);
    clearTimeout(WACHHUND);
    process.exit(2);
}

// ── Layout-Attrappe: so verhaelt sich base-select in Chrome ─────────────────
// Breite = Innenteil + 7 px je Zeichen des GEWAEHLTEN Eintrags (gemessen in
// Chrome: 59 px fuer "kurz", 242 px fuer einen langen Eintrag). Ein Feld mit
// `data-fest` hat eine feste Breite (Klassenregel `width: …`), `min-width`
// wirkt wie in CSS als Untergrenze, `data-versteckt` steht fuer display:none.
const BREITE_JE_ZEICHEN = 7, INNEN = 40;
function rohbreite(s) {
    if (s.hasAttribute('data-fest')) return Number(s.getAttribute('data-fest'));
    const o = s.options[s.selectedIndex];
    return INNEN + BREITE_JE_ZEICHEN * (o ? o.textContent.length : 0);
}
function breite(s) {
    if (s.hasAttribute('data-versteckt')) return 0;
    const min = parseFloat(s.style.minWidth) || 0;
    return Math.max(rohbreite(s), min);
}

function baue(html, mitBaseSelect) {
    const dom = new JSDOM(html, { url: 'https://localhost/x', runScripts: 'outside-only',
                                  virtualConsole: new VirtualConsole() });
    const w = dom.window;
    w.CSS = { supports: (p, v) => mitBaseSelect && p === 'appearance' && v === 'base-select' };
    const orig = w.getComputedStyle.bind(w);
    w.getComputedStyle = function (el, pseudo) {
        const cs = orig(el, pseudo);
        return new Proxy(cs, {
            get(t, k) {
                if (k === 'appearance') {
                    return (mitBaseSelect && el.tagName === 'SELECT' && !el.multiple
                            && !el.hasAttribute('size') && !el.classList.contains('nativ'))
                        ? 'base-select' : 'auto';
                }
                const v = t[k];
                return typeof v === 'function' ? v.bind(t) : v;
            },
        });
    };
    const P = w.HTMLSelectElement.prototype;
    Object.defineProperty(P, 'offsetWidth', { configurable: true, get() { return breite(this); } });
    P.getBoundingClientRect = function () {
        const b = breite(this);
        return { width: b, height: b ? 30 : 0, left: 0, top: 0, right: b, bottom: b ? 30 : 0 };
    };
    // Ereignisse, die das Messen NICHT ausloesen darf
    w.__ereignisse = 0;
    ['change', 'input'].forEach((t) => w.document.addEventListener(t, () => { w.__ereignisse++; }, true));
    w.eval(MODUL);
    return dom;
}

const LANG = 'ein deutlich laengerer Eintrag';
const SEITE = `<!doctype html><body>
  <select id="auto"><option>kurz</option><option>${LANG}</option><option>mittel lang</option></select>
  <select id="auto2"><option>a</option><option selected>${LANG}</option><option>bb</option></select>
  <select id="fest" data-fest="90"><option>50</option><option>${LANG}</option></select>
  <select id="autor" style="min-width: 50px"><option>x</option><option>${LANG}</option></select>
  <select id="mehrfach" multiple><option>x</option><option>${LANG}</option></select>
  <select id="liste" size="4"><option>x</option><option>${LANG}</option></select>
  <select id="nativ" class="nativ"><option>x</option><option>${LANG}</option></select>
  <select id="versteckt" data-versteckt><option>x</option><option>${LANG}</option></select>
  <select id="versteckt2" data-versteckt><option>x</option><option>${LANG}</option></select>
  <select id="versteckt3" data-versteckt><option>x</option><option>${LANG}</option></select>
  <select id="dyn"><option>kurz</option><option>kurz2</option></select>
</body>`;
const LANG_BREITE = INNEN + BREITE_JE_ZEICHEN * LANG.length;

(async () => {
    // ═══ Teil 1: das Modul ═════════════════════════════════════════════════
    section('Teil 1 – Breite der gestaltbaren Auswahl (Modul ausgefuehrt)');
    const dom = baue(SEITE, true);
    const w = dom.window, d = w.document, $ = (id) => d.getElementById(id);
    // Positivkontrollen: Modul geladen, Attrappe bildet den Fehler nach
    if (!w.JarvisAuswahlliste) abbruch('Modul nicht geladen (window.JarvisAuswahlliste fehlt)');
    const probe = d.createElement('select');
    probe.innerHTML = `<option>kurz</option><option>${LANG}</option>`;
    probe.setAttribute('data-ohne-modul', '');
    const b0 = rohbreite(probe); probe.selectedIndex = 1; const b1 = rohbreite(probe);
    if (!(b1 > b0)) abbruch('Attrappe bildet "Breite folgt der Auswahl" nicht nach');
    await sleep(50);   // DOMContentLoaded + Mikroaufgaben

    const a = $('auto');
    // Auswahl ZUERST pruefen – bevor dieser Test selbst umschaltet. Der
    // vorgewaehlte Eintrag steht bewusst NICHT an letzter Stelle: dort endet
    // die Messschleife ohnehin, ein fehlendes Zurueckstellen fiele nicht auf
    // (Gegenprobe war damit zuerst stumm).
    check('Auswahl nach dem Messen unveraendert (Eintrag 1)', a.selectedIndex === 0,
          `selectedIndex=${a.selectedIndex}`);
    check('Auswahl nach dem Messen unveraendert (vorgewaehlter Eintrag 2 von 3)', $('auto2').selectedIndex === 1,
          `selectedIndex=${$('auto2').selectedIndex}`);
    check('Feld ohne feste Breite bekommt die Breite des laengsten Eintrags',
          a.style.minWidth === LANG_BREITE + 'px', `min-width=${a.style.minWidth}`);
    const breiten = [0, 1, 2].map((i) => { a.selectedIndex = i; return a.getBoundingClientRect().width; });
    a.selectedIndex = 0;
    check('Breite bleibt beim Durchschalten aller Eintraege gleich (der Kern der Zusage)',
          new Set(breiten).size === 1, breiten.join('/'));
    // Der laengste Eintrag ist VORGEWAEHLT: die erste Fassung setzte hier keine
    // Untergrenze ("aktuelle Breite ist schon die groesste"), und das Feld
    // schrumpfte bei der naechsten Auswahl.
    const a2 = $('auto2');
    a2.selectedIndex = 0;
    const b2 = a2.getBoundingClientRect().width;
    a2.selectedIndex = 1;
    check('laengster Eintrag vorgewaehlt: Feld schrumpft bei kuerzerer Auswahl nicht',
          b2 === LANG_BREITE, `${b2} statt ${LANG_BREITE} px`);
    check('Messen loest kein change/input aus', w.__ereignisse === 0, `${w.__ereignisse} Ereignisse`);
    check('Feld mit fester Breite bleibt ohne Mindestbreite', $('fest').style.minWidth === '',
          $('fest').style.minWidth);
    check('vom Autor gesetzte Mindestbreite bleibt unangetastet', $('autor').style.minWidth === '50px',
          $('autor').style.minWidth);
    check('Mehrfachauswahl bleibt unberuehrt', $('mehrfach').style.minWidth === '');
    check('Listenfeld (size) bleibt unberuehrt', $('liste').style.minWidth === '');
    check('Feld ohne base-select bleibt unberuehrt', $('nativ').style.minWidth === '');
    check('unsichtbares Feld wird (noch) nicht gemessen', $('versteckt').style.minWidth === '');

    // Sichtbar geworden: gemessen wird spaetestens, bevor die Liste aufgeht
    $('versteckt').removeAttribute('data-versteckt');
    $('versteckt').dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    check('sichtbar gewordenes Feld: gemessen beim Fokus (vor dem Oeffnen)',
          $('versteckt').style.minWidth === LANG_BREITE + 'px', $('versteckt').style.minWidth);
    $('versteckt2').removeAttribute('data-versteckt');
    $('versteckt2').dispatchEvent(new w.Event('pointerdown', { bubbles: true }));
    check('sichtbar gewordenes Feld: gemessen beim Druecken der Maustaste',
          $('versteckt2').style.minWidth === LANG_BREITE + 'px', $('versteckt2').style.minWidth);
    $('versteckt3').removeAttribute('data-versteckt');
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed'));
    check('Sprachwechsel misst alle Felder neu',
          $('versteckt3').style.minWidth === LANG_BREITE + 'px', $('versteckt3').style.minWidth);

    // Eintraege aendern sich zur Laufzeit
    const dyn = $('dyn');
    const vorDyn = dyn.style.minWidth;
    const neu = d.createElement('option'); neu.textContent = LANG; dyn.appendChild(neu);
    await sleep(10);
    check('neuer laengerer Eintrag: Mindestbreite waechst mit',
          dyn.style.minWidth === LANG_BREITE + 'px', `${vorDyn} -> ${dyn.style.minWidth}`);
    dyn.removeChild(neu);
    await sleep(10);
    const kurzBreite = INNEN + BREITE_JE_ZEICHEN * 'kurz2'.length;
    check('laengster Eintrag entfernt: eigene Mindestbreite wird neu berechnet (nicht behalten)',
          dyn.style.minWidth === kurzBreite + 'px', dyn.style.minWidth);
    dyn.options[0].textContent = LANG + ' plus';
    await sleep(10);
    check('geaenderter Eintragstext (Uebersetzung) wird nachgemessen',
          dyn.style.minWidth === (LANG_BREITE + 5 * BREITE_JE_ZEICHEN) + 'px', dyn.style.minWidth);
    const spaet = d.createElement('div');
    spaet.innerHTML = `<span><select id="spaet"><option>x</option><option>${LANG}</option></select></span>`;
    d.body.appendChild(spaet);
    await sleep(10);
    check('spaeter eingefuegtes Feld (Dialog) wird gemessen',
          $('spaet').style.minWidth === LANG_BREITE + 'px', $('spaet').style.minWidth);
    check('auch danach kein change/input ausgeloest', w.__ereignisse === 0, `${w.__ereignisse}`);
    w.close();

    // Ohne base-select (Firefox, aeltere Chrome): das Modul tut nichts
    const dom2 = baue(SEITE, false);
    await sleep(50);
    const d2 = dom2.window.document;
    const gesetzt = [...d2.querySelectorAll('select')].filter((s) => s.id !== 'autor' && s.style.minWidth);
    check('ohne base-select: kein Feld bekommt eine Mindestbreite', gesetzt.length === 0,
          gesetzt.map((s) => s.id).join(','));
    dom2.window.close();

    // ═══ Teil 2: Regeln ueber die Stylesheets ══════════════════════════════
    section('Teil 2 – Stylesheets (geparster CSS-Baum)');
    const cssDom = new JSDOM('<style></style>');
    const st = cssDom.window.document.querySelector('style');
    function regeln(text) {
        st.textContent = text;
        const aus = [];
        (function lauf(liste, inSupports) {
            for (const r of liste) {
                const bed = r.conditionText || '';
                const unterBase = inSupports || (r.constructor.name === 'CSSSupportsRule'
                                                 && /appearance\s*:\s*base-select/.test(bed));
                if (r.cssRules) lauf(r.cssRules, unterBase);
                else if (r.selectorText) {
                    aus.push({ sel: r.selectorText.split(',').map((x) => x.trim()),
                               app: (r.style.getPropertyValue('appearance') || '').trim(),
                               wapp: (r.style.getPropertyValue('-webkit-appearance') || '').trim(),
                               disp: (r.style.getPropertyValue('display') || '').trim(),
                               base: unterBase });
                }
            }
        })(st.sheet.cssRules, false);
        return aus;
    }
    // Klassen, die im Markup/Code an einem <select> stehen – damit erkennt die
    // Regel auch `.wa-log-select`, dessen Selektor kein `select` enthaelt.
    function dateien(dir, endungen, aus = []) {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
            const p = path.join(dir, e.name);
            if (e.isDirectory()) { if (e.name !== 'vendor') dateien(p, endungen, aus); }
            else if (endungen.some((x) => e.name.endsWith(x))) aus.push(p);
        }
        return aus;
    }
    const FRONT = path.join(ROOT, 'frontend');
    const selectKlassen = new Set();
    for (const f of dateien(FRONT, ['.html', '.js'])) {
        const t = fs.readFileSync(f, 'utf8');
        for (const m of t.matchAll(/<select\b[^>]*?\bclass\s*=\s*\\?["']([^"'\\]+)/g)) {
            m[1].split(/\s+/).filter(Boolean).forEach((k) => selectKlassen.add(k));
        }
    }
    function zieltSelect(sel) {
        const letzter = sel.split(/[\s>+~]+/).filter(Boolean).pop() || '';
        if (/::/.test(letzter)) return false;
        if (/^select(?![\w-])/.test(letzter)) return true;
        if (/^[a-z]/i.test(letzter)) return false;   // anderes Element (input.cb …)
        return [...letzter.matchAll(/\.([\w-]+)/g)].some((m) => selectKlassen.has(m[1]));
    }
    /** Liefert die Selektoren mit `appearance: none` auf einem <select>, die
     *  KEINE base-select-Rueckstellung samt ausgeblendetem Chrome-Pfeil haben. */
    function ungedeckt(text) {
        const rs = regeln(text);
        const none = [];
        rs.filter((r) => !r.base && (r.app === 'none' || r.wapp === 'none'))
            .forEach((r) => r.sel.filter(zieltSelect).forEach((s) => none.push(s)));
        const zurueck = new Set(), pfeilWeg = new Set();
        rs.filter((r) => r.base).forEach((r) => r.sel.forEach((s) => {
            if (r.app === 'base-select') zurueck.add(s);
            if (r.disp === 'none' && s.endsWith('::picker-icon')) pfeilWeg.add(s.replace(/::picker-icon$/, ''));
        }));
        return [...new Set(none)].filter((s) => !(zurueck.has(s) && pfeilWeg.has(s)));
    }
    // Positivkontrollen der Messvorrichtung
    if (!selectKlassen.has('wa-log-select')) abbruch('Klassen an <select> nicht erkannt (wa-log-select fehlt)');
    const pk1 = ungedeckt('.probe-x select { appearance: none; }');
    const pk2 = ungedeckt('.probe-x select { appearance: none; } @supports (appearance: base-select) {'
                          + ' .probe-x select { appearance: base-select; } .probe-x select::picker-icon { display: none; } }');
    const pk3 = ungedeckt('.wa-log-select { -webkit-appearance: none; }');
    const pk4 = ungedeckt('input.cb { appearance: none; }');
    if (pk1.length !== 1 || pk2.length !== 0 || pk3.length !== 1 || pk4.length !== 0) {
        abbruch(`Regel-Sonde misst falsch (erwartet 1/0/1/0, gemessen ${pk1.length}/${pk2.length}/${pk3.length}/${pk4.length})`);
    }

    const theme = regeln(fs.readFileSync(path.join(FRONT, 'css/theme.css'), 'utf8'));
    const basis = theme.filter((r) => r.base && r.app === 'base-select');
    const feld = basis.flatMap((r) => r.sel).filter((s) => /^select\b/.test(s) && !s.includes('::'));
    const picker = basis.flatMap((r) => r.sel).filter((s) => /::picker\(select\)$/.test(s));
    check('theme.css: einfache Auswahlfelder stehen unter @supports auf base-select', feld.length >= 1,
          JSON.stringify(feld));
    check('theme.css: auch die Liste selbst (::picker(select)) auf base-select', picker.length >= 1);
    // Spezifitaet: ausserhalb von :where() darf nur der Elementname stehen –
    // sonst ueberstimmt die Grundform jede Klassenregel (.kb-input …)
    const ohneWhere = (s) => s.replace(/:where\((?:[^()]|\([^()]*\))*\)/g, '');
    const zuSpezifisch = theme.filter((r) => r.base).flatMap((r) => r.sel)
        .filter((s) => /^select\b/.test(s) && ohneWhere(s).replace(/::[\w-]+(\([^)]*\))?$/, '') !== 'select');
    check('theme.css: Grundform hat Spezifitaet eines Elementnamens (nur :where())', zuSpezifisch.length === 0,
          zuSpezifisch.join(' | '));
    check('theme.css: Mehrfachauswahl und Listenfelder ausgenommen',
          feld.every((s) => s.includes(':not([multiple])') && s.includes(':not([size])')), feld.join(' | '));
    const nicht = theme.filter((r) => !r.base && r.app === 'base-select');
    check('theme.css: base-select nur innerhalb von @supports', nicht.length === 0);

    let alleUngedeckt = [];
    for (const f of dateien(path.join(FRONT, 'css'), ['.css'])) {
        ungedeckt(fs.readFileSync(f, 'utf8')).forEach((s) => alleUngedeckt.push(path.basename(f) + ': ' + s));
    }
    check('jede Auswahl mit appearance:none hat base-select + ausgeblendeten Chrome-Pfeil (sonst wieder Betriebssystem-Menue)',
          alleUngedeckt.length === 0, alleUngedeckt.join(' | '));

    // ═══ Teil 3: Einbindung ════════════════════════════════════════════════
    section('Teil 3 – Einbindung je Seite');
    const seiten = dateien(FRONT, ['.html']).filter((f) => /theme\.css\?v=/.test(fs.readFileSync(f, 'utf8')));
    if (seiten.length < 10) abbruch(`nur ${seiten.length} Seiten mit theme.css gefunden – Suchweg falsch?`);
    const ohne = seiten.filter((f) => !/<script\s+src="\/static\/js\/auswahlliste\.js\?v=\d+"><\/script>/
        .test(fs.readFileSync(f, 'utf8')));
    check(`jede Seite mit theme.css laedt auswahlliste.js (${seiten.length} Seiten)`, ohne.length === 0,
          ohne.map((f) => path.relative(ROOT, f)).join(', '));

    const ok = results.filter((r) => r.ok).length;
    const fail = results.length - ok;
    console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
    BILANZ = true;
    clearTimeout(WACHHUND);
    process.exit(fail ? 1 : 0);
})().catch((e) => {
    console.log('❌ ABBRUCH: ' + (e && e.stack || e));
    clearTimeout(WACHHUND);
    process.exit(2);
});
