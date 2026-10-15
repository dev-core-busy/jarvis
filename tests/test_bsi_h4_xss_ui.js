/* UI-Waechter BSI H4-Rest: zwei Stellen, an denen Fremdtext als HTML ins DOM ging.
 *
 * Der H4-Eintrag der BSI-Liste nannte sie seit dem 04.10.2026 als „beim Abbau
 * gefunden, nicht behoben": der Lern-Editor (knowledge.js) und die Vision-
 * Profile (vision.js). Solange die CSP auf „melden" steht, blockiert der
 * Browser einen eingeschleusten Handler NICHT – der Rest war also ausnutzbar.
 *
 *   1. Lern-Editor: `<textarea>${data.content}</textarea>` – eine Lernnotiz mit
 *      `</textarea><img onerror=…>` schloss das Feld und lief als Markup.
 *      Lernnotizen entstehen aus Gespraechen und aus dem Feedback-Endpunkt,
 *      also aus Fremdtext.
 *   2. Vision: Profil-ID (= frei gewaehlter Name) roh in `data-profile="…"`
 *      und `id="…"`; `_esc()` maskierte keine Anfuehrungszeichen, stand aber in
 *      `value="…"`; `_visLog` setzte erkannte Namen und Engine-Fehler als HTML.
 *
 * GEMESSEN WIRD DIE WIRKUNG am echten Renderer (echtes Modul, echtes Markup,
 * jsdom): entsteht ein fremdes Element bzw. ein fremdes Attribut? Und kommt
 * der Wert UNVERAENDERT an (sonst waere „alles weg-escapen" auch gruen)?
 *
 * Lauf:  timeout 120 node tests/test_bsi_h4_xss_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  ✅ ' + name); }
    else { fail++; console.log('  ❌ ' + name + (detail ? ' – ' + detail : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WACHHUND = setTimeout(() => {
    console.log('❌ ABBRUCH: Lauf haengt (Wachhund nach 60 s)');
    process.exit(1);
}, 60000);
process.on('exit', (c) => {
    if (!BILANZ && c === 0) {
        console.log('❌ ABBRUCH: keine Bilanzzeile – der Lauf ist nicht durchgelaufen');
        process.exitCode = 1;
    }
});

// Die Angriffswerte. Jeder traegt ein Markierungs-Attribut, das es im
// echten Markup nirgends gibt – taucht es auf, hat der Wert das Attribut
// bzw. Element verlassen.
const MARKE = 'data-xss-probe';
const NOTIZ = '# Notiz\n</textarea><img src=x ' + MARKE + '="1">\nA &amp; B <b>fett</b>';
const PID = 'x" ' + MARKE + '="1" y="';
const NAME = '<img src=x ' + MARKE + '="1">';
const WERT = 'https://h/?a=1" ' + MARKE + '="1';

function fremde(root) {
    return root.querySelectorAll('[' + MARKE + ']').length;
}

function json(data) {
    return Promise.resolve({
        ok: true, status: 200, clone() { return this; },
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(JSON.stringify(data)),
    });
}

(async () => {
const html = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
const dom = new JSDOM(html, {
    url: 'https://localhost/settings', runScripts: 'outside-only',
    virtualConsole: new VirtualConsole(),
});
const w = dom.window, dc = w.document;
require('./lib/sitzung_laden')(w, { token: 'testtoken' });
for (const f of ['icons.js', 'i18n.js', 'knowledge.js', 'vision.js']) {
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', f), 'utf8'));
}
// jsdom feuert DOMContentLoaded selbst; die Vision-Instanz entsteht dort.
if (dc.readyState === 'loading') {
    await new Promise((r) => dc.addEventListener('DOMContentLoaded', r));
}
await sleep(10);

const km = w.knowledgeManager;
const vm = w.visionManager || new w.eval('JarvisVisionManager')();
if (!km || !vm) {
    console.log('ABBRUCH: Module nicht geladen (knowledgeManager=' + !!km
        + ', visionManager=' + !!vm + ')');
    process.exit(2);
}

console.log('\n1. Lern-Editor: Notizinhalt bleibt TEXT');
{
    const host = dc.createElement('div');
    host.innerHTML = '<div id="lf_7_editor" style="display:none;"></div>';
    dc.body.appendChild(host);
    w.fetch = () => json({ content: NOTIZ });
    await km.toggleLearnedEdit('lf_7', 'data/erfahrung/x.md');
    await sleep(10);
    const ed = dc.getElementById('lf_7_editor');
    const ta = ed && ed.querySelector('textarea');
    // Positivkontrolle: der Editor wurde ueberhaupt gezeichnet – sonst waere
    // „kein fremdes Element" trivial wahr.
    check('Positivkontrolle: Editor mit Textfeld gezeichnet', !!ta,
          ed ? ed.innerHTML.slice(0, 120) : 'kein Editor');
    check('⚠ kein eingeschleustes Element im Editor', fremde(ed || dc) === 0,
          (ed || dc).innerHTML.slice(0, 200));
    check('genau EIN Textfeld (das Feld wurde nicht geschlossen)',
          !!ed && ed.querySelectorAll('textarea').length === 1);
    check('⚠ der Inhalt steht UNVERAENDERT im Feld (auch „&amp;" und „<b>")',
          !!ta && ta.value === NOTIZ, ta ? JSON.stringify(ta.value.slice(0, 80)) : '');
    check('Speichern-Knopf vorhanden (Rest des Editors intakt)',
          !!ed && !!ed.querySelector('[data-kb-aktion="saveLearnedFile"]'));
    host.remove();
}

console.log('\n2. Vision-Profile: ID, Name und Aktionswert bleiben in ihrem Attribut');
{
    const liste = dc.getElementById('vis-profiles-list');
    check('Positivkontrolle: #vis-profiles-list steht im echten Markup', !!liste);
    if (!liste) { console.log('ABBRUCH: Markup fehlt'); process.exit(2); }
    const aktionen = [
        { id: 'webhook', label: 'Webhook', type: 'url' },
        { id: 'greet', label: 'Begrüßung', type: 'prompt' },
    ];
    vm._availableActions = aktionen;
    vm._renderProfilesList([{
        id: PID, name: NAME, action: 'webhook', action_value: WERT,
        greet_target: 'browser', created_at: '', num_images: 3,
    }], aktionen);
    const eintrag = liste.querySelector('.vis-profile-item');
    check('Positivkontrolle: Profilzeile gezeichnet', !!eintrag, liste.innerHTML.slice(0, 120));
    check('⚠ kein eingeschleustes Attribut/Element', fremde(liste) === 0,
          liste.innerHTML.slice(0, 300));
    const sel = liste.querySelector('.vis-action-select');
    check('⚠ data-profile traegt die ID unveraendert',
          !!sel && sel.dataset.profile === PID, sel ? JSON.stringify(sel.dataset.profile) : '');
    const wertFeld = liste.querySelector('input.vis-action-value');
    check('⚠ der Aktionswert steht unveraendert im value', !!wertFeld && wertFeld.value === WERT,
          wertFeld ? JSON.stringify(wertFeld.value) : 'kein Feld');
    const name = liste.querySelector('.vis-profile-info strong');
    check('der Name erscheint als TEXT', !!name && name.textContent === NAME,
          name ? JSON.stringify(name.textContent) : '');
    check('die Wertspalte ist per ID auffindbar (id-Attribut korrekt gebildet)',
          !!dc.getElementById('vis-av-' + PID));

    // Umschalten der Aktion baut das Wertfeld per innerHTML neu – mit der ID
    // aus dataset (dekodiert!), also wieder Rohtext.
    sel.value = 'greet';
    vm._onInlineActionChange(sel);
    check('⚠ auch nach dem Umschalten kein eingeschleustes Attribut', fremde(liste) === 0,
          liste.innerHTML.slice(0, 300));
    const ta = liste.querySelector('textarea.vis-action-value');
    check('Positivkontrolle: Umschalten hat das Textfeld gebaut', !!ta);
    check('… und dessen data-profile ist die ID', !!ta && ta.dataset.profile === PID);
    const gt = liste.querySelector('select.vis-greet-target');
    check('… die Lautsprecher-Auswahl ebenso', !!gt && gt.dataset.profile === PID);
}

console.log('\n3. Vision-Protokoll: Meldung als Text');
{
    const log = dc.getElementById('vis-log');
    check('Positivkontrolle: #vis-log steht im echten Markup', !!log);
    if (log) {
        const vorher = log.children.length;
        vm._visLog('Erkannt: ' + NAME, 'success');
        check('Positivkontrolle: ein Eintrag kam dazu', log.children.length === vorher + 1);
        check('⚠ kein eingeschleustes Element im Protokoll', fremde(log) === 0,
              log.innerHTML.slice(-200));
        const e = log.lastElementChild;
        check('der Text steht woertlich da', !!e && e.textContent.endsWith('Erkannt: ' + NAME),
              e ? JSON.stringify(e.textContent) : '');
        check('Zeitstempel bleibt eigenes Element',
              !!e && !!e.querySelector('.vis-log-time'));
    }
}

console.log('\n4. _esc maskiert Anfuehrungszeichen (steht in value="…")');
check('_esc("a\\"b\'c") → beide maskiert',
      vm._esc('a"b\'c') === 'a&quot;b&#39;c', vm._esc('a"b\'c'));
check('_esc(null) → leer', vm._esc(null) === '');

BILANZ = true;
clearTimeout(WACHHUND);
console.log('\nERGEBNIS: ' + ok + ' OK, ' + fail + ' FAIL');
w.close();
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('❌ ABBRUCH: ' + (e && e.stack || e)); process.exit(1); });
