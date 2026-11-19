#!/usr/bin/env node
/**
 * "Vorschlag per TAB uebernehmen" (frontend/js/tabfill.js).
 *
 * Gemeldet 2026-08-18: die Beispieltexte in Feldern wie "Hinweis (optional)"
 * sind brauchbar, liessen sich aber nur abtippen.
 *
 * Geprueft wird gegen die ECHTEN Dateien – ein Test, der sein Markup selbst
 * baut, prueft nur seine eigene Annahme.
 *
 * Teil 1  Verhalten der Taste (leer/gefuellt, Shift, Opt-in, input-Ereignis)
 * Teil 2  Hinweis, der das Feature ueberhaupt auffindbar macht
 * Teil 3  Verdrahtung: Einbindung je Seite, markierte Felder, i18n
 * Teil 4  JarvisTabfill.vorschlag – die zentrale Stelle fuer berechnete Vorschlaege
 * Teil 5  Die REGEL darueber: keine rohe placeholder-Zuweisung ohne Entscheidung
 *
 * Teil 4+5 kamen am 2026-11-19 dazu. Gemeldet war EIN Feld (die Rueckkehr-Adresse
 * des Anmelde-Anbieters), gemessen waren es SECHS: im Markup stehen Vorschlag und
 * Markierung nebeneinander, im JavaScript setzt eine Zeile den Platzhalter und die
 * Markierung muss jemand DARAN denken. Teil 5 misst das deshalb als Regel ueber
 * alle Module – eine neue Stelle faellt auf, statt still durchzufallen.
 *
 *   node tests/test_tabfill_ui.js
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
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
JSDOM = require('./lib/jsdom_laden')().JSDOM;

const TABFILL = fs.readFileSync(path.join(ROOT, 'frontend/js/tabfill.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

function baue() {
    const dom = new JSDOM(`<!doctype html><html><body>
        <div class="f"><label>Mit Vorschlag</label>
          <textarea id="a" data-tabfill placeholder="z. B. Antworte knapp."></textarea></div>
        <div class="f"><label>Eigener Text</label>
          <textarea id="b" data-tabfill="Fertiger Text" placeholder="nur Beschriftung"></textarea></div>
        <div class="f"><label>Ohne Opt-in</label>
          <input id="c" placeholder="vorname.nachname@firma.de"></div>
        <div class="f"><label>Gesperrt</label>
          <textarea id="d" data-tabfill placeholder="z. B. etwas" readonly></textarea></div>
        <div class="f"><label>i18n</label>
          <textarea id="e" data-i18n-tabfill="common.tabfill_hint" placeholder="x"></textarea></div>
        </body></html>`, { url: 'https://x/', runScripts: 'outside-only' });
    dom.window.eval(TABFILL);
    return dom;
}

const tab = (w, el, shift) => {
    const ev = new w.KeyboardEvent('keydown', {
        key: 'Tab', shiftKey: !!shift, bubbles: true, cancelable: true });
    el.dispatchEvent(ev);
    return ev;
};

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Verhalten der Taste');
{
    const { window: w } = baue();
    const d = w.document;
    const a = d.getElementById('a');

    let ev = tab(w, a);
    pruefe(a.value === 'z. B. Antworte knapp.', 'TAB im leeren Feld uebernimmt den Platzhalter', a.value);
    pruefe(ev.defaultPrevented, 'der Fokus bleibt (preventDefault) – der Text soll bearbeitbar sein');

    // Zweites TAB muss normal weiterschalten, sonst sitzt man fest.
    ev = tab(w, a);
    pruefe(!ev.defaultPrevented, 'zweites TAB schaltet normal weiter (Feld ist nicht mehr leer)');
    pruefe(a.value === 'z. B. Antworte knapp.', 'und haengt den Text nicht ein zweites Mal an');

    // Rueckwaerts navigieren muss immer moeglich bleiben.
    const b = d.getElementById('b');
    ev = tab(w, b, true);
    pruefe(!ev.defaultPrevented && b.value === '', 'Shift+TAB uebernimmt NICHTS');

    ev = tab(w, b);
    pruefe(b.value === 'Fertiger Text',
        'ein eigener data-tabfill-Text gewinnt gegen den Platzhalter', b.value);

    // Opt-in: Formvorgaben duerfen NIE uebernommen werden.
    const c = d.getElementById('c');
    ev = tab(w, c);
    pruefe(!ev.defaultPrevented && c.value === '',
        'ein Feld ohne data-tabfill bleibt unberuehrt (Formvorgaben!)');

    const dd = d.getElementById('d');
    tab(w, dd);
    pruefe(dd.value === '', 'ein readonly-Feld wird nicht befuellt');

    // Andere Module haengen an `input` (Zeichenzaehler, Formular-Spiegel).
    const a2 = d.getElementById('a');
    a2.value = '';
    let gesehen = 0;
    a2.addEventListener('input', () => gesehen++);
    tab(w, a2);
    pruefe(gesehen === 1, 'die Uebernahme feuert genau EIN input-Ereignis', String(gesehen));
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('2. Auffindbarkeit: der Hinweis');
{
    const { window: w } = baue();
    const d = w.document;
    const a = d.getElementById('a');

    a.dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    let h = d.querySelector('.jv-tabfill-hint');
    pruefe(!!h, 'Fokus auf einem leeren Feld zeigt den Hinweis');
    pruefe(!!h && h.textContent.indexOf('Tab') > -1, 'der Hinweis nennt die Taste', h && h.textContent);
    pruefe(!!h && h.previousSibling === a, 'er steht direkt unter dem Feld');

    tab(w, a);
    pruefe(!d.querySelector('.jv-tabfill-hint'), 'nach der Uebernahme ist er weg');

    // Gefuelltes Feld: kein Hinweis (er waere dort eine falsche Zusage).
    a.dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    pruefe(!d.querySelector('.jv-tabfill-hint'), 'ein gefuelltes Feld zeigt keinen Hinweis');

    // Nicht markiertes Feld ebenfalls nicht.
    d.getElementById('c').dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    pruefe(!d.querySelector('.jv-tabfill-hint'), 'ein Feld ohne data-tabfill zeigt keinen Hinweis');

    // Genau EIN Hinweis, auch nach mehrfachem Fokuswechsel.
    const b = d.getElementById('b');
    b.dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    b.dispatchEvent(new w.FocusEvent('focusin', { bubbles: true }));
    pruefe(d.querySelectorAll('.jv-tabfill-hint').length === 1,
        'nie mehr als ein Hinweis gleichzeitig');
    b.dispatchEvent(new w.FocusEvent('focusout', { bubbles: true }));
    pruefe(!d.querySelector('.jv-tabfill-hint'), 'beim Verlassen verschwindet er');
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('3. Verdrahtung, Felder und Uebersetzung');
{
    // applyLang muss data-i18n-tabfill in data-tabfill uebersetzen – sonst
    // stuende der Vorschlag in einer Sprache fest.
    const { window: w } = baue();
    w.eval(I18N);
    if (w.applyLang) w.applyLang(); else if (w.setLang) w.setLang('de');
    const e = w.document.getElementById('e');
    pruefe((e.getAttribute('data-tabfill') || '').length > 0,
        'applyLang setzt data-tabfill aus data-i18n-tabfill', e.getAttribute('data-tabfill'));
    w.close();
}

const SEITEN = ['frontend/email.html', 'frontend/sap.html', 'frontend/chat.html',
                'frontend/support.html', 'frontend/settings.html',
                'frontend/addin/taskpane.html'];
SEITEN.forEach(f => {
    const s = fs.readFileSync(path.join(ROOT, f), 'utf8');
    const iT = s.indexOf('tabfill.js');
    const iI = s.indexOf('js/i18n.js');
    pruefe(iT > -1, f + ': tabfill.js ist eingebunden');
    // NACH i18n.js: der Hinweistext kommt aus window.t().
    pruefe(iT > iI, f + ': und zwar nach i18n.js');
});

// Die markierten Felder: jedes braucht einen uebernehmbaren Text.
const DATEIEN = SEITEN.concat(['frontend/js/email_portal.js', 'frontend/addin/addin.js']);
let markiert = 0;
DATEIEN.forEach(f => {
    const s = fs.readFileSync(path.join(ROOT, f), 'utf8');
    (s.match(/data-tabfill/g) || []).forEach(() => markiert++);
});
pruefe(markiert >= 8, 'die Vorschlagsfelder sind markiert (' + markiert + ')');

// Formvorgaben duerfen NICHT markiert sein – sie zu uebernehmen hiesse, ein
// Beispiel zu speichern (Adresse, Anmeldename, Ordner, Filter).
const EMAIL_HTML = fs.readFileSync(path.join(ROOT, 'frontend/email.html'), 'utf8');
const PORTAL_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/email_portal.js'), 'utf8');
[['em-adresse', EMAIL_HTML], ['em-benutzer', EMAIL_HTML], ['em-ord-eingang', EMAIL_HTML],
 ['em-f-von', PORTAL_JS], ['em-f-betreff', PORTAL_JS]].forEach(([id, s]) => {
    const i = s.indexOf('id="' + id + '"');
    const stelle = i > -1 ? s.slice(i, i + 220) : '';
    pruefe(i > -1 && stelle.indexOf('data-tabfill') < 0,
        id + ' ist NICHT markiert (Formvorgabe bzw. Filter)');
});

const I18NTXT = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
['common.tabfill_hint', 'mail.style_text_suggest', 'sap.question_suggest'].forEach(k => {
    const n = (I18NTXT.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length;
    pruefe(n === 2, 'i18n ' + k + ' in DE UND EN', String(n));
});

const CSS = fs.readFileSync(path.join(ROOT, 'frontend/css/theme.css'), 'utf8');
// Symbole (Muelleimer/Kreuz) – im Browser das ERSTE Skript jeder Seite.
// Module wie chat.js/knowledge.js rufen JarvisIcons.trash() beim Rendern auf;
// ohne diese Zeile bricht das Zeichnen mit 'JarvisIcons is not defined' ab.
const ICONS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
pruefe(CSS.indexOf('.jv-tabfill-hint') > -1,
    'die Hinweis-Regel steht in theme.css (nicht style.css – das laedt nur /settings und /wissen)');
pruefe(!/\.jv-tabfill-hint[^{]*\{[^}]*#[0-9a-fA-F]{3}/.test(CSS),
    'keine harten Farben im Hinweis');

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('4. JarvisTabfill.vorschlag: Platzhalter UND Markierung in einem Zug');
{
    const { window: w } = baue();
    const d = w.document;
    const da = !!(w.JarvisTabfill && typeof w.JarvisTabfill.vorschlag === 'function');
    pruefe(da, 'tabfill.js stellt JarvisTabfill.vorschlag bereit');
    // Fehlt sie, darf dieser Abschnitt FEHLSCHLAGEN, nicht ABSTUERZEN: ein Lauf
    // ohne Bilanzzeile ist von "nicht gelaufen" nicht zu unterscheiden, und die
    // Gegenprobe "zentrale Funktion nicht ausgestellt" meldete dadurch Exit 2
    // statt eines Bisses (Register).
    const setzen = (el, t) => { if (da) w.JarvisTabfill.vorschlag(el, t); };

    // Ein Feld OHNE Markierung bekommt sie mit dem Vorschlag zusammen – genau
    // der gemeldete Fall (Platzhalter gesetzt, data-tabfill vergessen).
    const c = d.getElementById('c');
    c.value = '';
    c.removeAttribute('data-tabfill');
    setzen(c, 'https://host/auth/callback');
    pruefe(c.placeholder === 'https://host/auth/callback', 'der Platzhalter steht', c.placeholder);
    pruefe(c.hasAttribute('data-tabfill'), 'und das Feld ist markiert');
    const ev = tab(w, c);
    pruefe(ev.defaultPrevented && c.value === 'https://host/auth/callback',
        'TAB uebernimmt den so gesetzten Vorschlag', c.value);

    // EINE Quelle: das Attribut traegt KEINE zweite Kopie des Textes, sonst
    // liefe es auseinander, sobald jemand anders den Platzhalter anfasst
    // (branding.js ersetzt darin den Markennamen).
    c.value = '';
    c.placeholder = 'Marke-ersetzt https://host/x';
    pruefe(tab(w, c) && c.value === 'Marke-ersetzt https://host/x',
        'uebernommen wird der AKTUELLE Platzhalter, keine Kopie im Attribut', c.value);

    // Leerer Text raeumt beides ab – sonst verspraeche der Hinweis etwas, das
    // TAB nicht mehr liefert.
    c.value = '';
    setzen(c, '');
    pruefe(c.placeholder === '' && !c.hasAttribute('data-tabfill'),
        'ein leerer Vorschlag nimmt Platzhalter UND Markierung zurueck');
    pruefe(!tab(w, c).defaultPrevented && c.value === '',
        'danach schaltet TAB wieder normal weiter');

    // null/undefined sind der Regelfall bei einem Serverfeld, das fehlt.
    setzen(c, undefined);
    pruefe(!c.hasAttribute('data-tabfill'), 'undefined wirkt wie ein leerer Vorschlag');
    setzen(c, '   ');
    pruefe(!c.hasAttribute('data-tabfill'), 'reiner Leerraum ebenfalls');

    let warf = false;
    try { setzen(null, 'x'); } catch (e) { warf = true; }
    pruefe(!warf, 'ein fehlendes Element wirft nicht (die Felder sind oft optional)');
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('5. REGEL: jede placeholder-Zuweisung ist eine Entscheidung');
{
    // Gemessen am SYNTAXBAUM, nicht am Text: ein `.placeholder` in einer
    // Zeichenkette oder einem Kommentar ist keine Zuweisung (Register: ein
    // Teilstring ist keine Identitaet).
    const acorn = require('./lib/acorn_laden')();

    // tabfill.js selbst IST die zentrale Funktion; vnc.js setzt eine
    // Objekt-Eigenschaft `this.placeholder` (ein <div>), keinen Feld-Platzhalter –
    // deshalb zaehlen `this.<x> = …`-Ziele grundsaetzlich nicht mit.
    const EIGEN = 'frontend/js/tabfill.js';
    const MARKE = /tabfill:\s*nein/i;

    function jsDateien(dir, out) {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
            const voll = path.join(dir, e.name);
            if (e.isDirectory()) jsDateien(voll, out);
            else if (e.name.endsWith('.js')) out.push(voll);
        }
        return out;
    }

    /** Alle `X.placeholder = …` einer Datei, mit Zeilennummer. */
    function zuweisungen(src) {
        const fund = [];
        let ast;
        try { ast = acorn.parse(src, { ecmaVersion: 2022, locations: true }); }
        catch (e) { return null; }
        (function lauf(n) {
            if (!n || typeof n !== 'object') return;
            if (n.type === 'AssignmentExpression' && n.left &&
                n.left.type === 'MemberExpression' && !n.left.computed &&
                n.left.property && n.left.property.name === 'placeholder' &&
                n.left.object && n.left.object.type !== 'ThisExpression') {
                fund.push(n.loc.start.line);
            }
            for (const k in n) {
                if (k === 'loc') continue;
                const v = n[k];
                if (Array.isArray(v)) v.forEach(lauf);
                else if (v && typeof v.type === 'string') lauf(v);
            }
        })(ast);
        return fund;
    }

    /** Traegt der ZUSAMMENHAENGENDE Kommentar unmittelbar vor `zeile` die Marke?
     *  Ein Fenster fester Groesse waere die bekannte Zeitbombe – es griffe in den
     *  Nachbarblock. Gelesen wird deshalb rueckwaerts, bis eine Zeile kein
     *  Kommentar mehr ist. */
    function markiert(zeilen, zeile) {
        for (let i = zeile - 2; i >= 0; i--) {
            const z = zeilen[i].trim();
            if (z === '') return false;
            if (!z.startsWith('//') && !z.startsWith('*') && !z.startsWith('/*')) return false;
            if (MARKE.test(z)) return true;
        }
        return false;
    }

    // Positivkontrolle der Messvorrichtung, VOR den inhaltlichen Pruefungen:
    // ohne sie waere jede Aussage darunter trivial wahr (Register).
    const probe = [
        'el.placeholder = "a";',            // 1  roh, ohne Marke
        '// tabfill: nein – Grund',          // 2
        'el.placeholder = "b";',            // 3  markiert
        'this.placeholder = x;',            // 4  Objekt-Eigenschaft
        'var s = "el.placeholder = c";',    // 5  Zeichenkette
        'JarvisTabfill.vorschlag(el, "d");' // 6  zentraler Weg
    ].join('\n');
    const pz = zuweisungen(probe);
    const pzeilen = probe.split('\n');
    const pOhne = pz && pz.filter(z => !markiert(pzeilen, z));
    const kontrolleOk = pz && pz.length === 2 && pz[0] === 1 && pz[1] === 3 &&
                        pOhne.length === 1 && pOhne[0] === 1;
    pruefe(kontrolleOk,
        'Positivkontrolle: die Sonde findet genau die rohen Zuweisungen',
        pz ? ('gefunden ' + JSON.stringify(pz) + ', ohne Marke ' + JSON.stringify(pOhne)) : 'Parse-Fehler');
    if (!kontrolleOk) {
        console.log('\n  ABBRUCH: die Messvorrichtung ist unbrauchbar – ' +
                    'ohne sie waere die Regel darunter trivial wahr.');
        console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
        process.exit(2);
    }

    const WURZELN = ['frontend/js', 'frontend/addin'];
    const alle = [];
    WURZELN.forEach(w => {
        const abs = path.join(ROOT, w);
        if (!fs.existsSync(abs)) {
            console.log('\n  ABBRUCH: Wurzel fehlt – ' + w);
            process.exit(2);
        }
        jsDateien(abs, alle);
    });
    pruefe(alle.length >= 50, 'die Regel laeuft ueber alle Frontend-Module (' + alle.length + ')');

    const offen = [];
    let kaputt = 0, gezaehlt = 0;
    alle.forEach(f => {
        const rel = path.relative(ROOT, f).split(path.sep).join('/');
        if (rel === EIGEN) return;
        const src = fs.readFileSync(f, 'utf8');
        const z = zuweisungen(src);
        if (z === null) { kaputt++; return; }
        const zeilen = src.split('\n');
        z.forEach(n => {
            gezaehlt++;
            if (!markiert(zeilen, n)) offen.push(rel + ':' + n + ': ' + zeilen[n - 1].trim());
        });
    });
    pruefe(kaputt === 0, 'jedes Modul laesst sich parsen', String(kaputt) + ' nicht parsebar');
    pruefe(gezaehlt > 0, 'es gibt ueberhaupt markierte Zuweisungen zu pruefen (' + gezaehlt + ')');
    pruefe(offen.length === 0,
        'keine rohe placeholder-Zuweisung ohne Marke "tabfill: nein – <Grund>"',
        offen.join(' | '));

    // Die Gegenrichtung: der zentrale Weg wird wirklich benutzt. Ohne diese
    // Pruefung waere "alles markiert" auch dann erfuellt, wenn jemand JEDE
    // Stelle mit einer Marke stillstellt statt einen Vorschlag zu setzen.
    let nutzer = 0;
    const nutzerDateien = [];
    alle.forEach(f => {
        const rel = path.relative(ROOT, f).split(path.sep).join('/');
        if (rel === EIGEN) return;
        const src = fs.readFileSync(f, 'utf8');
        const n = (src.match(/JarvisTabfill\.vorschlag\s*\(/g) || []).length;
        if (n) { nutzer += n; nutzerDateien.push(rel); }
    });
    pruefe(nutzer >= 6,
        'berechnete Vorschlaege laufen ueber JarvisTabfill.vorschlag (' + nutzer + ')',
        nutzerDateien.join(', '));

    // Der gemeldete Fall namentlich – er darf nicht still zurueckfallen.
    const IDP = fs.readFileSync(path.join(ROOT, 'frontend/js/settings_idp.js'), 'utf8');
    pruefe(/JarvisTabfill\.vorschlag\s*\(\s*ru\s*,/.test(IDP),
        'die Rueckkehr-Adresse (idp-redirect-uri) setzt ihren Vorschlag zentral');

    // Jede Seite, die ein solches Modul einbindet, braucht tabfill.js – sonst
    // ist JarvisTabfill undefined und der Renderer bricht mit TypeError ab.
    const HTML = fs.readdirSync(path.join(ROOT, 'frontend'))
        .filter(n => n.endsWith('.html'))
        .concat(fs.existsSync(path.join(ROOT, 'frontend/addin'))
            ? fs.readdirSync(path.join(ROOT, 'frontend/addin')).filter(n => n.endsWith('.html'))
                .map(n => 'addin/' + n) : []);
    const fehlt = [];
    HTML.forEach(n => {
        const s2 = fs.readFileSync(path.join(ROOT, 'frontend', n), 'utf8');
        const braucht = nutzerDateien.some(m => s2.indexOf(m.replace('frontend/', '')) > -1);
        if (braucht && s2.indexOf('tabfill.js') < 0) fehlt.push(n);
    });
    pruefe(fehlt.length === 0,
        'jede Seite mit einem solchen Modul bindet tabfill.js ein', fehlt.join(', '));
}

console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
