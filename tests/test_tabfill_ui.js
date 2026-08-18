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
 *
 *   node tests/test_tabfill_ui.js
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
pruefe(CSS.indexOf('.jv-tabfill-hint') > -1,
    'die Hinweis-Regel steht in theme.css (nicht style.css – das laedt nur /settings und /wissen)');
pruefe(!/\.jv-tabfill-hint[^{]*\{[^}]*#[0-9a-fA-F]{3}/.test(CSS),
    'keine harten Farben im Hinweis');

console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
