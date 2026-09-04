/* UI-Waechter: "Freigabe verbinden" muss SICHTBAR sagen, was schiefging.
 *
 * GEMELDET AM 2026-09-04: "Einstellungen -> Wissen -> Netzwerk-Freigaben ->
 * Klick auf 'verbinden' liefert kein Informationen wenn etwas nicht klappt".
 *
 * ⚠ DIE MELDUNG GAB ES – SIE WAR NUR NICHT ZU SEHEN. #kb-notification steht in
 * settings.html bei Zeile 2076, die Freigabenliste bei 2270: rund 190
 * Markup-Zeilen und einen eigenen Klapp-Container weiter unten. Wer auf
 * "Verbinden" klickt, schaut auf die Liste – die Meldung erschien ausserhalb
 * seines Sichtfensters und war nach 3,5 s wieder weg. Genau derselbe Fehler
 * wie beim Ansichts-Umschalter, der aus dem 600-px-Popup gedrueckt wurde.
 *
 * GEMESSEN WIRD DESHALB DIE EIGENSCHAFT, nicht das Vorkommen:
 *   1. nach dem Klick liegt die Meldung IM Container der Aktion
 *   2. sie haengt in keinem versteckten Vorfahren
 *   3. ein FEHLER bleibt stehen (er ist der Grund des Klicks) und traegt ein
 *      × zum Schliessen – ein Muelleimer waere hier falsch (Symbol-Semantik)
 *   4. der Text enthaelt die SERVERMELDUNG, nicht nur das Wort "Fehler"
 *   5. auch eine Antwort ohne JSON (Proxy-Fehlerseite) wird verwertbar
 *   6. ein Erfolg verschwindet weiterhin von selbst
 *
 * Lauf:  timeout 120 node tests/test_mount_meldung_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || 'jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

// × = schliessen. Muelleimer = loeschen. Hier wird nichts geloescht.
const KREUZE = /[×✕✖⨯🗙]|&times;|&#215;|&#10005;|jv-ico-close/u;
const MUELL = /jv-ico-trash/u;

function json(data, status) {
    const body = JSON.stringify(data);
    return Promise.resolve({
        ok: (status || 200) < 400, status: status || 200,
        clone() { return this; },
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(body),
    });
}
function text(body, status) {
    return Promise.resolve({
        ok: (status || 200) < 400, status: status || 200,
        clone() { return this; },
        json: () => Promise.reject(new SyntaxError('Unexpected token <')),
        text: () => Promise.resolve(body),
    });
}

/** Verstecke Vorfahren eines Elements (jsdom rechnet kein Layout – die
 *  Elternkette ist das, was sich hier messen laesst). */
function versteckteVorfahren(el) {
    const aus = [];
    for (let p = el; p; p = p.parentElement) {
        const st = (p.getAttribute && p.getAttribute('style')) || '';
        if ((p.hasAttribute && p.hasAttribute('hidden')) || /display\s*:\s*none/.test(st)) {
            aus.push(p);
        }
    }
    return aus;
}

/**
 * DIE EIGENTLICHE FRAGE: "Wer den Knopf sieht, sieht auch die Meldung."
 *
 * Absolut auf "kein versteckter Vorfahr" zu pruefen waere hier FALSCH und
 * haette einen Fehler gemeldet, den es nicht gibt: in jsdom ist der
 * Einstellungs-Reiter nicht aktiv und der Klapp-Container "Netzwerk-Freigaben"
 * zugeklappt – beides Zustaende, in denen der Benutzer den Verbinden-Knopf gar
 * nicht anklicken KANN. Geprueft wird deshalb relativ: jeder versteckte
 * Vorfahr der Meldung muss auch ein Vorfahr des Bedienelements sein.
 */
function sichtbarWieDerKnopf(meldung, knopfBereich) {
    return versteckteVorfahren(meldung).every((v) => v.contains(knopfBereich));
}

let BILANZ = false;
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

(async () => {

const html = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
const vc = new VirtualConsole();
const dom = new JSDOM(html, {
    url: 'https://localhost/settings',
    runScripts: 'outside-only',
    virtualConsole: vc,
});
const w = dom.window, dc = w.document;
w.localStorage.setItem('jarvis_token', 'testtoken');
w.confirm = () => true;
w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8'));
w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/knowledge.js'), 'utf8'));
const km = w.knowledgeManager;

section('0. Ausgangslage: der gemeldete Abstand ist real');
const notif = dc.getElementById('kb-notification');
const liste = dc.getElementById('kb-mount-list');
check('#kb-notification und #kb-mount-list gibt es', !!notif && !!liste);
if (!notif || !liste) { console.log('ABBRUCH: Markup fehlt'); process.exit(2); }
check('sie liegen NICHT im selben Container (das war der Fehler)',
      notif.parentElement !== liste.parentElement,
      'Markup geaendert? dann ist der Test neu zu schneiden');
const abstandVorher = Math.abs(html.indexOf('id="kb-mount-list"') - html.indexOf('id="kb-notification"'));
check('… und zwar weit auseinander (> 3000 Zeichen Markup)', abstandVorher > 3000,
      String(abstandVorher));

section('1. Der Fehlerfall: 500 mit Servermeldung');
w.fetch = () => json({ error: 'Freigabe konnte nicht verbunden werden: mount error(13): '
                              + 'Permission denied — Zugang verweigert.' }, 500);
await km.toggleMount(0, true);
await sleep(20);
check('⚠ die Meldung liegt jetzt IM Container der Freigabenliste',
      notif.parentElement === liste.parentElement,
      'Elternteil: ' + (notif.parentElement && notif.parentElement.id));
check('… und direkt hinter der Liste (nicht irgendwo im Container)',
      liste.nextElementSibling === notif,
      'nachbar: ' + (liste.nextElementSibling && liste.nextElementSibling.id));
check('⚠ wer den Verbinden-Knopf sieht, sieht auch die Meldung',
      sichtbarWieDerKnopf(notif, liste),
      'zusaetzlich versteckt: ' + versteckteVorfahren(notif)
          .filter((v) => !v.contains(liste)).map((v) => v.id || v.className).join(', '));
check('sie ist eingeblendet', notif.style.display === 'block', notif.style.display);
check('⚠ der Text enthaelt die SERVERMELDUNG, nicht nur "Fehler"',
      /mount error\(13\)/.test(notif.textContent), notif.textContent.slice(0, 120));
check('sie ist als Fehler gekennzeichnet',
      /kb-notification-error/.test(notif.className), notif.className);
const zu = notif.querySelector('.kb-notif-close');
check('sie traegt einen Schliessen-Knopf', !!zu);
check('… mit einem × (kein Muelleimer – es wird nichts geloescht)',
      !!zu && KREUZE.test(zu.innerHTML) && !MUELL.test(zu.innerHTML),
      zu ? zu.innerHTML.slice(0, 80) : '');
check('… und er ist beschriftet (Titel/aria)',
      !!zu && !!zu.getAttribute('title') && !!zu.getAttribute('aria-label'));

// Positivkontrolle DER MESSFUNKTION – sonst waere die Pruefung darueber
// trivial wahr. (Den gemeldeten Zustand selbst kann jsdom nicht nachstellen:
// dort war die Meldung nicht VERSTECKT, sondern rund 190 Markup-Zeilen weiter
// oben und damit ausserhalb des Sichtfensters. Das misst die Pruefung
// "direkt hinter der Liste"; ihre Gegenprobe ist der Altstand.)
{
    const kaefig = dc.createElement('div');
    kaefig.style.display = 'none';
    notif.parentNode.insertBefore(kaefig, notif);
    const merkEltern = notif.parentNode, merkNext = notif.nextSibling;
    kaefig.appendChild(notif);
    check('Positivkontrolle: ein versteckter Behaelter wird erkannt',
          !sichtbarWieDerKnopf(notif, liste));
    merkEltern.insertBefore(notif, merkNext);
    kaefig.remove();
    check('… und danach ist der Zustand wiederhergestellt',
          sichtbarWieDerKnopf(notif, liste) && liste.nextElementSibling === notif);
}

section('2. Ein Fehler verschwindet NICHT von selbst');
await sleep(120);
// Der Erfolgs-Timer laeuft 3,5 s; hier wird geprueft, dass ueberhaupt KEINER
// gesetzt wurde – sonst muesste der Test 3,5 s schlafen und waere zeitabhaengig.
check('⚠ kein Ausblende-Timer fuer Fehler (man muss ihn lesen koennen)',
      !km._notifTimer, String(km._notifTimer));
check('… und die Meldung steht noch', notif.style.display === 'block');
zu.click();
check('der Klick auf × raeumt sie weg', notif.style.display === 'none');

section('3. Antwort ohne JSON (Proxy-Seite, 502) bleibt verwertbar');
w.fetch = () => text('<html><body>502 Bad Gateway</body></html>', 502);
await km.toggleMount(0, true);
await sleep(20);
check('kein "Unexpected token" in der Meldung',
      !/Unexpected token/i.test(notif.textContent), notif.textContent.slice(0, 120));
check('stattdessen etwas Verwertbares (Statuszeile oder Text)',
      /502/.test(notif.textContent), notif.textContent.slice(0, 120));

section('4. FastAPI-Fehler stehen in "detail", nicht in "error"');
w.fetch = () => json({ detail: 'Wissens-Editor-Recht erforderlich' }, 403);
await km.toggleMount(0, true);
await sleep(20);
check('auch ein 403 aus FastAPI wird angezeigt',
      /Wissens-Editor/.test(notif.textContent), notif.textContent.slice(0, 120));
// … und zwar als SATZ, nicht als roher JSON-Klumpen. Ohne diese Pruefung
// bliebe die Gegenprobe "nur err.error lesen" gruen: der Text-Rueckfall
// zeigte dann {"detail":"..."} – lesbar, aber wie ein Programmfehler.
check('… als Satz, nicht als roher JSON-Rumpf',
      !/[{}"]/.test(notif.textContent.replace(/^[^:]*:\s*/, '')),
      notif.textContent.slice(0, 120));

section('5. Waehrend des Verbindens gibt es eine Rueckmeldung');
{
    let aufloesen;
    w.fetch = () => new Promise((r) => { aufloesen = () => r(json({ ok: true })); });
    const p = km.toggleMount(0, true);
    await sleep(10);
    check('⚠ der Klick sagt SOFORT, dass gearbeitet wird',
          notif.style.display === 'block' && notif.textContent.length > 3,
          notif.textContent.slice(0, 80));
    check('… und zwar an der Liste', liste.nextElementSibling === notif);
    // Erst die Attrappe zuruecksetzen, DANN aufloesen: toggleMount ruft
    // danach fetchMounts()/fetchStats(), die sonst am selben haengenden
    // Promise stehenbleiben – der Lauf endete dort ohne Bilanz (Register).
    w.fetch = () => json({ ok: true });
    aufloesen();
    await p.catch(() => {});
}

section('6. Ein Erfolg verschwindet weiterhin von selbst');
w.fetch = () => json({ ok: true });
await km.toggleMount(0, true);
await sleep(20);
check('Erfolgsmeldung ist sichtbar', notif.style.display === 'block');
check('… ohne Schliessen-Knopf (sie geht von selbst)',
      !notif.querySelector('.kb-notif-close'));
check('… und ein Ausblende-Timer laeuft', !!km._notifTimer);

section('7. Loeschen prueft die Antwort (meldete frueher auch bei 500 Erfolg)');
w.fetch = () => json({ detail: 'nope' }, 500);
await km.removeMount(0);
await sleep(20);
check('⚠ ein fehlgeschlagenes Loeschen meldet KEINEN Erfolg',
      /kb-notification-error/.test(notif.className) && /nope/.test(notif.textContent),
      notif.className + ' / ' + notif.textContent.slice(0, 80));

const fails = results.filter((r) => !r.ok).length;
BILANZ = true;
clearTimeout(WACHHUND);
console.log(`\nErgebnis: ${results.length - fails}/${results.length}`);
if (fails) console.log(`${fails} Pruefung(en) fehlgeschlagen`);
dom.window.close();
process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
