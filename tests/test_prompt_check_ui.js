/* jsdom-Waechter fuer frontend/js/prompt_check.js.
 *
 * Das Knopf-Markup kommt aus dem PRODUKTIONSCODE (`knopfHtml`), nicht aus dem
 * Test – ein UI-Test, der sein Markup selbst schreibt, prueft seine eigene
 * Annahme (Register). Dass der Knopf im echten Formular ZWISCHEN Speichern und
 * Abbrechen sitzt, prueft tests/test_prompt_check.py am Quelltext beider
 * Formulare; hier geht es um das Verhalten.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;
function check(bed, text) {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text); }
}

const JS = fs.readFileSync(path.join(ROOT, 'frontend/js/prompt_check.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

function neueSeite(antwort, statusOk) {
    const dom = new JSDOM(
        '<!doctype html><html><body>' +
        '<div id="form"></div>' +
        '</body></html>',
        // `url` IST PFLICHT: ohne sie laeuft jsdom auf about:blank mit opaque
        // origin, und `localStorage` ist dort nicht benutzbar – der Test saehe
        // ein fehlendes Sitzungstoken, das im Browser sehr wohl da ist.
        { url: 'https://localhost/tracks', runScripts: 'outside-only',
          pretendToBeVisual: false });
    const w = dom.window;
    w.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    // Sprache und Token wie in den Bereichsseiten.
    w._lang = 'de';
    w.t = function (k) { return k; };          // i18n liefert den Key -> Fallback greift
    try { w.localStorage.setItem('jarvis_token', 'TOK123'); } catch (e) { /* egal */ }

    const gesendet = [];
    w.fetch = function (url, opt) {
        gesendet.push({ url: url, opt: opt || {} });
        return Promise.resolve({
            ok: statusOk !== false,
            json: function () { return Promise.resolve(antwort); }
        });
    };
    w.eval(ICONS);
    w.eval(JS);
    return { dom, w, gesendet };
}

function formular(w, mitText) {
    const f = w.document.getElementById('form');
    f.innerHTML =
        '<textarea id="st-f-prompt"></textarea>' +
        '<button id="st-f-save">Speichern</button>' +
        w.JarvisPromptCheck.knopfHtml('st-f-prompt', 'tracks', 'st-btn') +
        '<button id="st-f-cancel">Abbrechen</button>';
    if (mitText) { w.document.getElementById('st-f-prompt').value = mitText; }
    return f;
}

function klick(w, el) {
    el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
}
const warte = () => new Promise(r => setTimeout(r, 25));

(async function () {

console.log('\n1) Knopf-Markup aus dem Produktionscode');
{
    const { w } = neueSeite({});
    formular(w);
    const b = w.document.querySelector('.jv-pc-btn');
    check(!!b, 'der Knopf existiert');
    check(b.getAttribute('data-pc-feld') === 'st-f-prompt'
       && b.getAttribute('data-pc-kontext') === 'tracks',
        'Feld und Bereich stehen als data-Attribute am Knopf');
    check(b.classList.contains('st-btn'),
        'er uebernimmt die Klasse der Nachbarknoepfe (reiht sich ein)');
    check(b.getAttribute('data-i18n') === 'promptcheck.btn'
       && b.getAttribute('data-i18n-title') === 'promptcheck.title',
        'i18n-Attribute gesetzt – applyLang() erreicht ihn');
    check(b.getAttribute('type') === 'button',
        'type="button" – sonst wuerde er ein Formular abschicken');
    // Reihenfolge im DOM: Speichern, Knopf, Abbrechen.
    const ids = Array.from(w.document.getElementById('form').children)
        .map(e => e.id || e.className);
    check(ids.indexOf('st-f-save') < ids.findIndex(x => /jv-pc-btn/.test(x))
       && ids.findIndex(x => /jv-pc-btn/.test(x)) < ids.indexOf('st-f-cancel'),
        'im DOM liegt er zwischen Speichern und Abbrechen');
}

console.log('\n2) Leeres Feld: Hinweis, aber KEIN Modellaufruf');
{
    const { w, gesendet } = neueSeite({});
    formular(w);
    klick(w, w.document.querySelector('.jv-pc-btn'));
    await warte();
    check(gesendet.length === 0, 'ohne Text wird nicht gefragt (kostet sonst Tokens)');
    const pop = w.document.getElementById('jv-pc-pop');
    check(pop && !pop.hasAttribute('hidden'), 'das Popup erscheint trotzdem');
    check(/jv-pc-warn/.test(pop.innerHTML), 'und sagt, dass noch kein Text da ist');
    check(pop.parentNode === w.document.body,
        'das Popup ist direktes Kind von <body> (kein fremder Stapelkontext)');
}

console.log('\n3) Mit Text: Anfrage, Popup, Inhalte');
{
    const antwort = {
        ok: true, interpretation: 'Ich fuehre die Tabellen zusammen.',
        annahmen: ['Welches Blatt gemeint ist.'],
        risiken: ['Bei zwei Dateien scheitert der Lauf.'],
        beispiel: 'Fuehre Blatt 2026 der Master-Datei mit der CSV zusammen.',
        modell: 'qwen-test'
    };
    const { w, gesendet } = neueSeite(antwort);
    formular(w, 'Tabellen zusammenfuehren');
    const b = w.document.querySelector('.jv-pc-btn');
    klick(w, b);
    await warte();
    check(gesendet.length === 1 && gesendet[0].url === '/api/prompt/pruefen',
        'genau eine Anfrage an /api/prompt/pruefen');
    const body = JSON.parse(gesendet[0].opt.body);
    check(body.prompt === 'Tabellen zusammenfuehren' && body.kontext === 'tracks'
       && body.lang === 'de', 'Prompt, Bereich und Sprache werden uebergeben');
    check(/Bearer TOK123/.test(gesendet[0].opt.headers.Authorization),
        'das Sitzungstoken reist im Authorization-Kopf');
    const pop = w.document.getElementById('jv-pc-pop');
    const h = pop.innerHTML;
    check(h.indexOf('Ich fuehre die Tabellen zusammen.') >= 0, 'Interpretation steht da');
    check(h.indexOf('Welches Blatt gemeint ist.') >= 0, 'Annahmen stehen da');
    check(h.indexOf('Bei zwei Dateien scheitert der Lauf.') >= 0, 'Risiken stehen da');
    check(h.indexOf('Fuehre Blatt 2026') >= 0, 'der Vorschlag steht da');
    check(/qwen-test/.test(pop.textContent), 'das benutzte Modell wird genannt');
    // NICHT auf "prüf" pruefen: der Ruhetext heisst selbst "Prompt prüfen" –
    // die erste Fassung hat damit ihren eigenen Erfolg als Fehler gemeldet.
    check(!b.disabled && b.textContent.indexOf('…') < 0
       && b.textContent.indexOf('Prompt') >= 0,
        'der Knopf ist danach wieder bedienbar und traegt seinen Ruhetext');

    // Uebernehmen schreibt ins Feld UND feuert input.
    let inputs = 0;
    const ta = w.document.getElementById('st-f-prompt');
    ta.addEventListener('input', function () { inputs++; });
    klick(w, pop.querySelector('.jv-pc-take'));
    await warte();
    check(ta.value === antwort.beispiel, 'der Vorschlag landet im Prompt-Feld');
    check(inputs === 1, 'und ein input-Ereignis feuert (Zaehler/Spiegel haengen daran)');
    check(pop.hasAttribute('hidden'), 'das Popup schliesst nach dem Uebernehmen');
}

console.log('\n4) Schliessen: x, Fussknopf, Escape, Klick daneben');
{
    const { w } = neueSeite({ ok: true, interpretation: 'A', beispiel: '' });
    formular(w, 'text');
    const pop = () => w.document.getElementById('jv-pc-pop');
    for (const [name, wie] of [
        ['das x oben rechts', p => klick(w, p.querySelector('.jv-pc-x'))],
        ['der Schliessen-Knopf', p => klick(w, p.querySelector('.jv-pc-close'))],
        ['Escape', () => w.document.dispatchEvent(
            new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))],
        ['ein Klick daneben', p => klick(w, p)]
    ]) {
        klick(w, w.document.querySelector('.jv-pc-btn'));
        await warte();
        check(!pop().hasAttribute('hidden'), 'Popup offen (vor: ' + name + ')');
        wie(pop());
        check(pop().hasAttribute('hidden'), name + ' schliesst das Popup');
    }
    check(/JarvisIcons|svg/i.test(pop().querySelector('.jv-pc-x').innerHTML)
       || pop().querySelector('.jv-pc-x svg') !== null,
        'das Schliessen-Kreuz ist ein SVG aus icons.js, kein Emoji');
    check(pop().querySelectorAll('.jv-pc-take[hidden]').length === 1,
        'ohne Vorschlag ist "uebernehmen" ausgeblendet');
}

console.log('\n5) Fremdtext wird maskiert (das Modell liefert den Text)');
{
    const boes = '<img src=x onerror="window.__hack=1">';
    const { w } = neueSeite({ ok: true, interpretation: boes, beispiel: boes,
                              annahmen: [boes], risiken: [] });
    formular(w, 'text');
    klick(w, w.document.querySelector('.jv-pc-btn'));
    await warte();
    const pop = w.document.getElementById('jv-pc-pop');
    check(pop.querySelectorAll('img').length === 0,
        'kein Element aus der Modellantwort landet im DOM');
    check(w.__hack === undefined, 'und nichts davon wird ausgefuehrt');
    check(pop.textContent.indexOf('onerror') >= 0,
        'der Text ist als Text sichtbar (maskiert, nicht geloescht)');
}

console.log('\n6) Fehlerfall: der Grund des Servers wird gezeigt');
{
    const { w } = neueSeite({ ok: false, error: 'Für diesen Bereich nicht freigegeben.' },
                            false);
    formular(w, 'text');
    klick(w, w.document.querySelector('.jv-pc-btn'));
    await warte();
    const pop = w.document.getElementById('jv-pc-pop');
    check(pop.textContent.indexOf('nicht freigegeben') >= 0,
        'die Servermeldung steht im Popup (nicht ein generischer Text)');
    check(w.document.querySelector('.jv-pc-btn').disabled === false,
        'der Knopf ist auch nach einem Fehler wieder bedienbar');
}

console.log('\n7) Der Knopf wirkt auch nach NEUAUFBAU des Formulars');
{
    // Das ist der Grund fuer den delegierten Listener: die Formulare werden bei
    // jedem Oeffnen und bei jedem Sprachwechsel neu aus einem HTML-String
    // gebaut. Ein direkt gebundener Handler waere danach weg – und der Knopf
    // saehe funktionsfaehig aus, ohne zu wirken.
    const { w, gesendet } = neueSeite({ ok: true, interpretation: 'A' });
    formular(w, 'erst');
    formular(w, 'danach');          // kompletter Neuaufbau
    klick(w, w.document.querySelector('.jv-pc-btn'));
    await warte();
    check(gesendet.length === 1, 'der neu gebaute Knopf loest die Pruefung aus');
    check(JSON.parse(gesendet[0].opt.body).prompt === 'danach',
        'und liest den aktuellen Feldinhalt');
}

console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
})();
