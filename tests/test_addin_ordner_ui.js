#!/usr/bin/env node
/**
 * Outlook-Add-in Bereitstellung: die Umschaltung wird AUSGEFUEHRT.
 *
 * WARUM DIESER TEST NEBEN dem Python-Waechter noetig ist: dort ist die Zusage
 * "die Kachel ERSETZT den Download, statt ihn zu ergaenzen" nur als Vorkommen
 * pruefbar (`em-addin-dlrow` steht im Quelltext) – eine Gegenprobe, die
 * `dlrow.hidden = false` setzt, blieb damit gruen. Ob eine Zeile SICHTBAR ist,
 * kann nur ein Lauf gegen ein echtes DOM beantworten.
 *
 * Und die Sichtbarkeit wird RELATIV gemessen, nicht per getComputedStyle:
 * jsdom rechnet kein Layout. Geprueft wird "kein versteckter Vorfahr" –
 * inklusive des `hidden`-Attributs UND der CSS-Regel `.em-row[hidden]`, die es
 * ueberhaupt erst wirksam macht (`display: flex` ueberstimmt `hidden`).
 *
 * Teil 1  Kein Pfad  -> Download sichtbar, Pfad-Zeile verborgen
 * Teil 2  Pfad da    -> Pfad sichtbar, Download verborgen, Anleitung getauscht
 * Teil 3  Fremdtext im Pfad landet nicht als Markup in der Seite
 * Teil 4  Kein Feld (aelteres Backend) -> fail-open auf den Download
 * Teil 5  Anleitung: beide Knoepfe schalten dieselbe Box um
 *
 *   node tests/test_addin_ordner_ui.js
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

// jsdom an ALLEN ueblichen Orten suchen – ein Waechter, der nur auf einem
// Rechner laeuft, ist ein halber. Und Exit 2, nicht 0: "konnte nicht laufen"
// darf nie wie "bestanden" aussehen.
let JSDOM = null;
for (const p of [process.env.JSDOM_PATH, path.join(ROOT, 'node_modules/jsdom'),
                 '/tmp/node_modules/jsdom', path.join(ROOT, 'data/node_modules/jsdom'),
                 '/usr/share/nodejs/jsdom', 'jsdom']) {
    if (!p) continue;
    try { JSDOM = require(p).JSDOM; break; } catch (e) { /* weiter */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht gefunden'); process.exit(2); }

// Wachhund: haengt der Lauf (die geladene Seite haelt eigene Poll-Timer), darf
// er nicht mit Exit 0 und ohne Bilanz enden – das waere von "bestanden" nicht
// zu unterscheiden (Register, mehrfach bezahlt).
const wachhund = setTimeout(() => {
    console.log('  ✗ ABBRUCH: Wachhund nach 40 s');
    console.log('\n' + '='.repeat(62));
    console.log('  ' + ok + ' OK, ' + (fail + 1) + ' FAIL');
    console.log('='.repeat(62));
    process.exit(1);
}, 40000);
wachhund.unref && wachhund.unref();

const MAIL_HTML = fs.readFileSync(path.join(ROOT, 'frontend/email.html'), 'utf8');
const PORTAL_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/email_portal.js'), 'utf8');
const I18N_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const ICONS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

/* Sichtbar = kein Vorfahr ist versteckt.
 *
 * RELATIV gemessen und mit den ECHTEN CSS-Regeln der Seite: `hidden` allein
 * genuegt nicht als Aussage, weil `.em-row { display: flex }` es ueberstimmt.
 * Deshalb wird zusaetzlich geprueft, ob die Seite eine `[hidden]`-Regel fuer
 * die Klasse des Elements mitbringt. */
const HIDDEN_REGEL = /\.em-row\[hidden\][^{]*\{[^}]*display:\s*none/.test(MAIL_HTML)
    && /\.em-block\[hidden\]|\.em-steps\[hidden\]/.test(MAIL_HTML);

function sichtbar(el) {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        if (n.hasAttribute && n.hasAttribute('hidden')) return false;
        if (n.classList && n.classList.contains('hidden')) return false;
        const st = (n.getAttribute && n.getAttribute('style')) || '';
        if (/display\s*:\s*none/.test(st)) return false;
    }
    return true;
}

function bauePortal(status) {
    const dom = new JSDOM(MAIL_HTML, { url: 'https://x/email', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));
    w.requestAnimationFrame = w.requestAnimationFrame || (f => setTimeout(f, 0));
    // navigator.clipboard fehlt in jsdom – gestellt, damit der Kopier-Weg
    // messbar ist (und nicht nur sein Fehlerzweig).
    let kopiert = null;
    Object.defineProperty(w.navigator, 'clipboard', {
        value: { writeText: (t) => { kopiert = t; return Promise.resolve(); } },
        configurable: true
    });
    w.fetch = (url, o) => {
        o = o || {};
        rufe.push({ url: String(url), methode: o.method || 'GET' });
        // Geroutet wird ueber den PFAD, nicht die ganze URL: an
        // /api/email/status haengt `?lang=` (Register).
        const pfad = String(url).split('?')[0];
        const gib = (d, s) => Promise.resolve({
            ok: (s || 200) < 400, status: s || 200,
            headers: { get: () => null },
            json: () => Promise.resolve(d)
        });
        if (pfad === '/api/me') {
            return gib({ username: 'nexus\\a.bender', is_admin: false,
                         permissions: { email: true } });
        }
        if (pfad === '/api/email/status') return gib(status);
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [], bereiche: [] });
        if (pfad === '/api/email/log') return gib({ ok: true, eintraege: [] });
        return gib({ ok: true });
    };
    w.eval(I18N_JS);
    w.eval(ICONS_JS);
    w.eval(PORTAL_JS);
    return { w, rufe, dom, kopiert: () => kopiert };
}

const BASIS = {
    ok: true, skill_aktiv: true,
    konto: { vorhanden: true, adresse: 'a@b.c', benutzer: 'u', aktiv: true,
             stile: [], signaturen: [] },
    bereiche: [], server: { kanal: 'auto', ews: true, imap: false, smtp: false },
    kategorie: 'Jarvis', regeln: 0,
    grenzen: { max_regeln: 50, min_intervall: 1, max_intervall: 1440, max_je_lauf: 10,
               prompt_max: 8000, max_stile: 12, stil_name_max: 60, stil_text_max: 2000,
               max_signaturen: 12, sig_name_max: 60, sig_text_max: 4000, sig_html_max: 20000 }
};

const warte = (ms) => new Promise(r => setTimeout(r, ms || 60));

(async () => {

/* ══ Teil 0: die CSS-Voraussetzung ══════════════════════════════════════ */
abschnitt('Teil 0: hidden wirkt ueberhaupt');
// ⚠ OHNE DIESE REGEL IST DER GANZE TEST WERTLOS: `.em-row { display: flex }`
// ueberstimmt das `hidden`-Attribut, die Pfad-Zeile waere IMMER sichtbar
// (Register: `.sp-row[hidden]` in /sap).
pruefe(HIDDEN_REGEL, 'email.html bringt [hidden]-Regeln fuer .em-row/.em-block mit',
    'ohne sie ueberstimmt display:flex das hidden-Attribut');

/* ══ Teil 1: kein Pfad -> Download ══════════════════════════════════════ */
abschnitt('Teil 1: ohne Pfad bleibt der Download');
{
    const { w } = bauePortal(Object.assign({}, BASIS, { addin_ordner: '' }));
    await warte(120);
    const dl = w.document.getElementById('em-addin-dlrow');
    const pf = w.document.getElementById('em-addin-pfadrow');
    pruefe(!!dl && !!pf, 'beide Zeilen im Markup');
    pruefe(dl && sichtbar(dl), 'Download-Zeile ist SICHTBAR');
    pruefe(pf && !sichtbar(pf), 'Pfad-Zeile ist VERBORGEN');
    const sdl = w.document.getElementById('em-addin-steps-dl');
    const spf = w.document.getElementById('em-addin-steps-pfad');
    // Die Anleitungsbox startet zugeklappt – gemessen wird deshalb das
    // hidden-Attribut der Listen selbst, nicht ihre Sichtbarkeit.
    pruefe(sdl && !sdl.hasAttribute('hidden'), 'Download-Anleitung ist die aktive');
    pruefe(spf && spf.hasAttribute('hidden'), 'Pfad-Anleitung ist abgeschaltet');
    const a = w.document.getElementById('em-addin-dl');
    pruefe(a && a.tagName === 'A' && /\/addin\/manifest\.xml$/.test(a.getAttribute('href')),
        'Download ist ein <a> auf /addin/manifest.xml',
        a ? a.tagName + ' ' + a.getAttribute('href') : 'fehlt');
    w.close();
}

/* ══ Teil 2: Pfad da -> ERSETZT ═════════════════════════════════════════ */
abschnitt('Teil 2: mit Pfad wird der Download ERSETZT');
{
    const PFAD = '\\\\srv01\\Freigabe\\Office Add-ins';
    const { w, kopiert } = bauePortal(Object.assign({}, BASIS, { addin_ordner: PFAD }));
    await warte(120);
    const dl = w.document.getElementById('em-addin-dlrow');
    const pf = w.document.getElementById('em-addin-pfadrow');
    // ⚠ DAS IST DIE PRUEFUNG, DIE DER PYTHON-WAECHTER NICHT LEISTEN KANN:
    // die Gegenprobe `dlrow.hidden = false` blieb dort gruen, weil der
    // Bezeichner im Quelltext trotzdem vorkam.
    pruefe(dl && !sichtbar(dl), 'Download-Zeile ist VERBORGEN (ersetzt, nicht ergaenzt)');
    pruefe(pf && sichtbar(pf), 'Pfad-Zeile ist SICHTBAR');
    const kasten = w.document.getElementById('em-addin-pfad');
    pruefe(kasten && kasten.textContent === PFAD, 'der Pfad steht vollstaendig da',
        kasten ? JSON.stringify(kasten.textContent) : 'fehlt');
    const sdl = w.document.getElementById('em-addin-steps-dl');
    const spf = w.document.getElementById('em-addin-steps-pfad');
    pruefe(sdl && sdl.hasAttribute('hidden'), 'Download-Anleitung ist abgeschaltet');
    pruefe(spf && !spf.hasAttribute('hidden'), 'Pfad-Anleitung ist die aktive');
    const note = w.document.getElementById('em-addin-pfad-note');
    pruefe(note && !note.hasAttribute('hidden'), 'der Hinweis zum Ordner erscheint');
    // Der Ordner wird NICHT in Outlook eingetragen – anders als der
    // Excel-Katalog. Steht das nicht da, trägt jemand ihn dort ein und sucht
    // stundenlang.
    pruefe(spf && /Explorer/i.test(spf.textContent),
        'die Pfad-Anleitung schickt in den Explorer, nicht in Outlook-Optionen',
        spf ? spf.textContent.slice(0, 90) : '');
    // Kopieren: der Knopf muss den ECHTEN Pfad in die Zwischenablage legen.
    const kn = w.document.getElementById('em-addin-copy');
    pruefe(!!kn, 'Kopier-Knopf vorhanden');
    if (kn) {
        kn.click();
        await warte(60);
        pruefe(kopiert() === PFAD, 'ein Klick kopiert genau diesen Pfad',
            JSON.stringify(kopiert()));
        const st = w.document.getElementById('em-addin-copy-status');
        pruefe(st && st.textContent.trim().length > 0, 'und meldet es sichtbar',
            st ? JSON.stringify(st.textContent) : 'fehlt');
    }
    w.close();
}

/* ══ Teil 3: Fremdtext ══════════════════════════════════════════════════ */
abschnitt('Teil 3: der Pfad ist Fremdtext aus dem Reiter');
{
    const BOES = '\\\\srv\\<img src=x onerror=alert(1)>\\a';
    const { w } = bauePortal(Object.assign({}, BASIS, { addin_ordner: BOES }));
    await warte(120);
    const kasten = w.document.getElementById('em-addin-pfad');
    pruefe(kasten && kasten.querySelectorAll('img').length === 0,
        'kein Element aus dem Pfad im DOM (textContent, nicht innerHTML)',
        kasten ? kasten.innerHTML.slice(0, 80) : 'fehlt');
    pruefe(kasten && kasten.textContent === BOES, 'der Text bleibt dabei vollstaendig lesbar');
    w.close();
}

/* ══ Teil 4: fail-open ══════════════════════════════════════════════════ */
abschnitt('Teil 4: fehlt das Feld, bleibt der Download (fail-open)');
{
    // Aelteres Backend / halber Deploy: kein `addin_ordner` in der Antwort.
    // Ein fehlender Pfad kostet einen Download, ein falsch behaupteter schickt
    // den Benutzer in einen leeren Ordner.
    const { w } = bauePortal(BASIS);
    await warte(120);
    const dl = w.document.getElementById('em-addin-dlrow');
    const pf = w.document.getElementById('em-addin-pfadrow');
    pruefe(dl && sichtbar(dl), 'Download-Zeile sichtbar');
    pruefe(pf && !sichtbar(pf), 'Pfad-Zeile verborgen');
    w.close();
}

/* ══ Teil 5: die Anleitung ist aus BEIDEN Zeilen erreichbar ═════════════ */
abschnitt('Teil 5: beide Anleitung-Knoepfe schalten dieselbe Box');
{
    const { w } = bauePortal(Object.assign({}, BASIS, { addin_ordner: '\\\\srv\\f' }));
    await warte(120);
    const box = w.document.getElementById('em-addin-steps');
    const k2 = w.document.getElementById('em-addin-help2');
    pruefe(!!box && !!k2, 'Box und zweiter Knopf vorhanden');
    if (box && k2) {
        // Der zweite Knopf liegt in der Pfad-Zeile. Schaltet nur der erste um,
        // ist die Anleitung im Pfad-Fall UNERREICHBAR – der erste ist dann
        // verborgen.
        pruefe(sichtbar(k2), 'der zweite Knopf ist im Pfad-Fall sichtbar');
        pruefe(box.classList.contains('hidden'), 'die Box startet zugeklappt');
        k2.click();
        pruefe(!box.classList.contains('hidden'), 'ein Klick klappt sie auf');
        pruefe(/aus|hide/i.test(k2.textContent), 'der Knopf wechselt seine Beschriftung',
            JSON.stringify(k2.textContent));
        // Der VERSTECKTE erste Knopf muss mitziehen: sonst steht dort der
        // falsche Text, sobald die Administration den Pfad entfernt.
        const k1 = w.document.getElementById('em-addin-help');
        pruefe(k1 && k1.textContent === k2.textContent,
            'der andere Knopf traegt denselben Text',
            k1 ? JSON.stringify(k1.textContent) + ' / ' + JSON.stringify(k2.textContent) : 'fehlt');
        k2.click();
        pruefe(box.classList.contains('hidden'), 'ein zweiter klappt sie zu');
    }
    w.close();
}

clearTimeout(wachhund);
console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
})();
