/* UI-Waechter: JEDES Kennwortfeld traegt ein Auge – und zeigt Sterne.
 *
 * VORGABE DES BETREIBERS (2026-09-04): "korrigiere im gesamten Kennwort
 * Felder, die nach dem Prinzip 'Passwort (leer = unve...' aufgebaut sind. Ich
 * moechte UEBERALL stattdessen ein Passwortfeld mit Sternen und der Option den
 * Inhalt mit unserem Auge anzuzeigen."
 *
 * GEMESSEN WIRD AUSGEFUEHRT, nicht am Quelltext: das Modul haengt seine Knoepfe
 * zur LAUFZEIT an, und mehr als die Haelfte der Felder entsteht ueberhaupt erst
 * beim Oeffnen eines Dialogs. Eine Suche nach "type=password" im Markup wuerde
 * genau die uebersehen.
 *
 * Lauf:  timeout 120 node tests/test_pwreveal_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || 'jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let BILANZ = false;
const WACHHUND = setTimeout(() => {
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

function baue(html) {
    const vc = new VirtualConsole();
    const dom = new JSDOM(html, { url: 'https://localhost/x', runScripts: 'outside-only',
                                  virtualConsole: vc });
    const w = dom.window;
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8'));
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/pwreveal.js'), 'utf8'));
    return dom;
}
function auge(inp) {
    if (!inp) return null;
    const p = inp.parentElement;
    if (!p) return null;
    for (let k = p.firstElementChild; k; k = k.nextElementSibling) {
        if (k.classList && k.classList.contains('jv-pw-eye')) return k;
    }
    return null;
}

(async () => {

section('1. Ein Feld im Markup bekommt sein Auge');
{
    const dom = baue(`<!doctype html><html><body>
        <div class="form-group"><input type="password" id="a" placeholder="Kennwort"></div>
    </body></html>`);
    await sleep(20);
    const dc = dom.window.document, inp = dc.getElementById('a');
    const knopf = auge(inp);
    check('das Auge ist da', !!knopf);
    check('… als button type=button (nie submit – das Feld steht oft in einem form)',
          !!knopf && knopf.getAttribute('type') === 'button', knopf && knopf.getAttribute('type'));
    check('… mit Beschriftung (title und aria-label)',
          !!knopf && !!knopf.title && !!knopf.getAttribute('aria-label'));
    check('… und einem Augen-Symbol aus icons.js',
          !!knopf && /jv-ico-eye/.test(knopf.innerHTML), knopf && knopf.innerHTML.slice(0, 60));
    check('das Feld ist verborgen (Sterne)', inp.type === 'password', inp.type);

    knopf.click();
    check('⚠ ein Klick macht die Eingabe sichtbar', inp.type === 'text', inp.type);
    check('… das Symbol wechselt auf das durchgestrichene Auge',
          /jv-ico-eye-off/.test(knopf.innerHTML), knopf.innerHTML.slice(0, 60));
    check('… und die Beschriftung sagt jetzt "verbergen"',
          /verberg|hide/i.test(knopf.title), knopf.title);
    knopf.click();
    check('ein zweiter Klick verbirgt wieder', inp.type === 'password', inp.type);
    check('… und das Symbol ist zurueck',
          /jv-ico-eye"/.test(knopf.innerHTML) || !/eye-off/.test(knopf.innerHTML));

    // Ein zweiter Durchlauf darf kein zweites Auge anhaengen.
    dom.window.JarvisPwEye.alle(dc);
    check('kein zweites Auge bei erneutem Durchlauf',
          inp.parentElement.querySelectorAll('.jv-pw-eye').length === 1,
          String(inp.parentElement.querySelectorAll('.jv-pw-eye').length));
    dom.window.close();
}

section('2. Handverdrahtete Augen werden NICHT angefasst');
{
    // settings.html hat fuer den Kennwortwechsel eigene Knoepfe (app.js::
    // _wireEyeBtn) mit Zusatzlogik. Zwei Augen uebereinander waere der Fehler.
    const dom = baue(`<!doctype html><html><body>
        <div style="position:relative;">
            <input type="password" id="cpw-old">
            <button type="button" id="btn-eye-cpw-old"><svg></svg></button>
        </div></body></html>`);
    await sleep(20);
    const dc = dom.window.document;
    check('kein zweites Auge neben dem handverdrahteten',
          dc.querySelectorAll('.jv-pw-eye').length === 0,
          String(dc.querySelectorAll('.jv-pw-eye').length));
    dom.window.close();
}

section('3. DER KERN: dynamisch erzeugte Felder (JS-Templates)');
{
    const dom = baue('<!doctype html><html><body><div id="wirt"></div></body></html>');
    await sleep(20);
    const dc = dom.window.document;
    // So bauen knowledge.js, skillcfg.js, sap.js & Co. ihre Formulare.
    dc.getElementById('wirt').innerHTML =
        '<div class="kb-mount-edit-form">' +
        '<input type="password" class="kb-mount-edit-pass" data-pw-gesetzt="1">' +
        '</div>';
    await sleep(60);   // MutationObserver ist asynchron
    const inp = dc.querySelector('.kb-mount-edit-pass');
    check('⚠ ein erst zur Laufzeit erzeugtes Feld bekommt sein Auge', !!auge(inp),
          inp ? inp.parentElement.innerHTML.slice(0, 120) : 'kein Feld');
    check('… und der Platzhalter sind Sterne (ein Kennwort ist hinterlegt)',
          inp && /^•+$/.test(inp.placeholder), inp && inp.placeholder);
    check('… mit der Aussage "leer lassen = unveraendert" im Titel',
          inp && /unver|keep/i.test(inp.title || ''), inp && inp.title);
    dom.window.close();
}

section('3b. Zwei Felder im SELBEN Container bekommen BEIDE ein Auge');
{
    // Der Fall aus dem echten Bestand: "neues Kennwort" und "bestaetigen"
    // liegen oft im gleichen div. Die erste Fassung von schonVersorgt() suchte
    // per querySelector in NACHFAHREN und uebersprang das zweite Feld.
    const dom = baue(`<!doctype html><html><body><div class="g">
        <input type="password" id="p1"><input type="password" id="p2">
    </div></body></html>`);
    await sleep(30);
    const dc = dom.window.document;
    check('⚠ beide Felder haben ein eigenes Auge',
          !!auge(dc.getElementById('p1')) && !!auge(dc.getElementById('p2')),
          `p1=${!!auge(dc.getElementById('p1'))} p2=${!!auge(dc.getElementById('p2'))}`);
    check('… und zwar genau eines je Feld',
          dc.querySelectorAll('.jv-pw-eye').length === 2,
          String(dc.querySelectorAll('.jv-pw-eye').length));
    // Und sie schalten unabhaengig voneinander.
    auge(dc.getElementById('p1')).click();
    check('… die Augen wirken je Feld getrennt',
          dc.getElementById('p1').type === 'text' && dc.getElementById('p2').type === 'password',
          `${dc.getElementById('p1').type}/${dc.getElementById('p2').type}`);
    dom.window.close();
}

section('4. Sterne nur, wo wirklich etwas hinterlegt ist');
{
    const dom = baue(`<!doctype html><html><body>
        <input type="password" id="leer" placeholder="Passwort (optional)">
        <input type="password" id="gesetzt" data-pw-gesetzt="1" placeholder="Passwort (optional)">
        <input type="password" id="alt" placeholder="Passwort (leer = unverändert)">
    </body></html>`);
    await sleep(20);
    const dc = dom.window.document;
    check('ein leeres Feld behaelt seinen normalen Platzhalter',
          dc.getElementById('leer').placeholder === 'Passwort (optional)',
          dc.getElementById('leer').placeholder);
    check('ein hinterlegtes Kennwort zeigt Sterne',
          /^•+$/.test(dc.getElementById('gesetzt').placeholder),
          dc.getElementById('gesetzt').placeholder);
    // Altbestand: ein Platzhalter, der das Prinzip als SATZ traegt, wird
    // ebenfalls zu Sternen – das war die Vorgabe.
    check('⚠ ein "leer = unveraendert"-Platzhalter wird zu Sternen',
          /^•+$/.test(dc.getElementById('alt').placeholder),
          dc.getElementById('alt').placeholder);
    dom.window.close();
}

section('5. REGEL: das Modul liegt auf JEDER Seite');
{
    const seiten = [];
    for (const d of ['frontend', 'frontend/addin', 'frontend/excel-addin']) {
        for (const f of fs.readdirSync(path.join(ROOT, d))) {
            if (f.endsWith('.html')) seiten.push(path.join(d, f));
        }
    }
    check('Positivkontrolle: es wurden Seiten gefunden', seiten.length >= 15,
          String(seiten.length));
    const ohne = seiten.filter((s) =>
        !fs.readFileSync(path.join(ROOT, s), 'utf8').includes('pwreveal.js'));
    check('⚠ jede Seite bindet pwreveal.js ein (auch kuenftige Felder)',
          ohne.length === 0, ohne.join(', '));
    // Es nutzt JarvisIcons – icons.js muss davor stehen.
    const falsch = seiten.filter((s) => {
        const t = fs.readFileSync(path.join(ROOT, s), 'utf8');
        const i = t.indexOf('icons.js'), pw = t.indexOf('pwreveal.js');
        return i >= 0 && pw >= 0 && pw < i;
    });
    check('… und zwar NACH icons.js (es benutzt JarvisIcons)',
          falsch.length === 0, falsch.join(', '));
}

section('6. Das Auge verspricht nichts Falsches');
{
    // Ein GESPEICHERTES Kennwort gibt kein Endpunkt heraus (mehrfach
    // dokumentierte Zusage). Die Beschriftung darf nichts anderes behaupten.
    const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
    for (const k of ['common.pw_show', 'common.pw_hide', 'common.pw_keep']) {
        const n = (i18n.match(new RegExp("'" + k + "'", 'g')) || []).length;
        check(`i18n-Schluessel in DE und EN: ${k}`, n === 2, String(n));
    }
    const de = i18n.slice(i18n.indexOf("'common.pw_show'"), i18n.indexOf("'common.pw_show'") + 200);
    check('⚠ die Beschriftung sagt, dass nur die EIGENE Eingabe sichtbar wird',
          /tippst|type/i.test(de), de.slice(0, 120));
    const src = fs.readFileSync(path.join(ROOT, 'frontend/js/pwreveal.js'), 'utf8');
    check('das Modul liest nirgends ein gespeichertes Kennwort',
          !/fetch\(|XMLHttpRequest|localStorage/.test(src));
}

const fails = results.filter((r) => !r.ok).length;
BILANZ = true;
clearTimeout(WACHHUND);
console.log(`\nErgebnis: ${results.length - fails}/${results.length}`);
if (fails) console.log(`${fails} Pruefung(en) fehlgeschlagen`);
process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
