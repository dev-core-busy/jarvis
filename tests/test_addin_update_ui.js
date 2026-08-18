#!/usr/bin/env node
/**
 * Aufgabenfenster: Hinweis auf ein VERALTETES MANIFEST.
 *
 * Warum es diese Pruefung gibt: Aufgabenfenster, Logik und CSS liegen auf dem
 * Server und erreichen jedes installierte Add-in beim naechsten Oeffnen – das
 * MANIFEST dagegen wird von Microsoft bei einer Installation aus Datei oder URL
 * NIE aktualisiert. Das Band ist der einzige Weg, das sichtbar zu machen.
 *
 * Gepruest wird gegen die ECHTEN Dateien (taskpane.html, addin.js, i18n.js) –
 * ein Test, der sein Markup selbst baut, prueft nur seine eigene Annahme.
 *
 * DIE KERNREGEL, die hier festgeschrieben wird: NICHTS BEHAUPTEN, WAS WIR NICHT
 * WISSEN. Ohne `mv` und ohne Outlook-Kontext ist es ein Browseraufruf, und dann
 * darf kein Band erscheinen.
 *
 *   node tests/test_addin_update_ui.js
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

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/addin/taskpane.html'), 'utf8');
const ADDINJS = fs.readFileSync(path.join(ROOT, 'frontend/addin/addin.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const ADDINPY = fs.readFileSync(path.join(ROOT, 'backend/addin.py'), 'utf8');
const MAIN = fs.readFileSync(path.join(ROOT, 'backend/main.py'), 'utf8');
const DOKU = fs.readFileSync(path.join(ROOT, 'docs/outlook-addin.md'), 'utf8');

/* Kommentare entfernen, bevor der Waechter im Quelltext sucht. Ein Waechter,
   der seine eigene Begruendung liest, prueft nichts – im Projekt schon
   fuenfmal passiert. */
function nurCode(s) {
    return String(s).replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/^\s*\/\/.*$/gm, ' ')
        .replace(/#.*$/gm, ' ');
}

/* ── Umgebung ────────────────────────────────────────────────────────────
   `office`: null   = office.js kommt nie (echte 4-Sekunden-Grenze)
             'leer' = office.js da, aber kein mailbox-Kontext  → _officeDa false
             'box'  = mailbox erreichbar                       → _officeDa true
   Die Variante 'leer' gibt es, damit der Fall "kein Outlook-Kontext" ohne die
   4 Sekunden Wartezeit pruefbar bleibt – fuer die Weiche ist sie gleichwertig. */
function baue(opt) {
    opt = opt || {};
    const url = 'https://x/addin/taskpane.html' + (opt.mv === undefined ? ''
        : ('?mv=' + encodeURIComponent(opt.mv)));
    const dom = new JSDOM(HTML, { url: url, runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    if (opt.token) w.localStorage.setItem('jarvis_token', 'T');

    // FETCH VOR DEM eval: addin.js laeuft sofort los und ruft fetch. Ist es
    // noch undefined, bricht die Funktion ab, bevor irgendetwas passiert –
    // und man sucht den Fehler im Umbau (Lehre aus test_audit_ctx_ui.js).
    w.fetch = (u, o) => {
        o = o || {};
        rufe.push({ url: String(u), kopf: o.headers || {}, methode: o.method || 'GET' });
        const pfad = String(u).split('?')[0];
        const gib = (d, st) => Promise.resolve({
            ok: (st || 200) < 400, status: st || 200,
            json: () => Promise.resolve(d)
        });
        if (pfad === '/api/addin/version') {
            if (opt.verFehler === 'netz') return Promise.reject(new Error('offline'));
            if (opt.verFehler === 'http') return gib({}, 500);
            if (opt.verFehler === 'leer') return gib({ ok: true, version: '' });
            return gib({ ok: true, version: opt.server || '1.2.0.0' });
        }
        if (pfad === '/api/me') {
            return gib({ username: 'a.bender', is_admin: false,
                         permissions: { email: true } });
        }
        if (pfad === '/api/email/status') {
            return gib({ ok: true, konto: { vorhanden: false }, bereiche: [],
                         server: {}, regeln: 0, grenzen: {} });
        }
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [], bereiche: [] });
        if (pfad === '/api/email/log') return gib({ ok: true, eintraege: [] });
        return gib({ ok: true });
    };
    if (opt.office === 'box' || opt.office === 'leer') {
        w.Office = {
            onReady: (cb) => cb({}),
            context: opt.office === 'box' ? { mailbox: {} } : undefined
        };
    }
    w.eval(I18N);
    w.eval(ADDINJS);
    return { dom, w, rufe, band: () => w.document.getElementById('ad-upd') };
}
const warte = (ms) => new Promise(r => setTimeout(r, ms));
const sichtbar = (b) => !!b && !b.classList.contains('hidden');

(async function () {

abschnitt('1. Markup und CSS');
pruefe(/id="ad-upd"[^>]*class="ad-upd hidden"/.test(HTML),
    'Band liegt im Markup und startet verborgen');
pruefe(HTML.indexOf('id="ad-upd"') < HTML.indexOf('id="ad-login"'),
    'Band steht VOR beiden Zustaenden – ein Element fuer Anmeldung und Anwendung');
pruefe((HTML.match(/id="ad-upd"/g) || []).length === 1,
    'genau EIN Band (zwei waeren zwei Zustaende)');
pruefe(/\.ad-upd\s*\{[^}]*background:\s*var\(--bg-secondary\)/.test(HTML),
    'Flaeche ist DECKEND – das Band liegt ueber dem klebenden Kopf');
pruefe(/\.ad-upd a\.ad-btn\s*\{[^}]*text-decoration:\s*none/.test(HTML),
    'der Download-Link ist nicht unterstrichen (a mit Knopf-Klasse)');
pruefe(!/\.ad-upd\s*\{[^}]*var\(--danger\)/.test(HTML),
    'Akzent statt --danger: ein altes Manifest ist kein Fehler');

abschnitt('2. Belegt veraltet: mv kleiner als der Server');
{
    const u = baue({ mv: '1.1.0.0', server: '1.2.0.0', office: 'box', token: true });
    await warte(60);
    const b = u.band();
    pruefe(sichtbar(b), 'Band erscheint');
    pruefe(/1\.1\.0\.0/.test(b.textContent) && /1\.2\.0\.0/.test(b.textContent),
        'nennt BEIDE Versionen', b.textContent);
    pruefe(!/\{alt\}|\{neu\}/.test(b.textContent),
        'kein Platzhalter uebrig (global ersetzt)');
    const a = b.querySelector('a');
    pruefe(!!a && a.getAttribute('href') === '/addin/manifest.xml',
        'Download-Link zeigt auf das Manifest');
    pruefe(!!a && a.getAttribute('target') === '_blank'
        && /noopener/.test(a.getAttribute('rel') || ''),
        'oeffnet im Systembrowser, mit noopener');
    pruefe(/funktioniert alles weiter/i.test(b.textContent),
        'sagt ausdruecklich, dass alles weiterlaeuft');
    const ruf = u.rufe.filter(r => r.url.split('?')[0] === '/api/addin/version');
    pruefe(ruf.length === 1, 'genau EIN Abruf der Serverversion');
    pruefe(!ruf[0].kopf.Authorization,
        'ohne Authorization-Kopf – der Hinweis gilt auch vor der Anmeldung');
    u.w.close();
}

abschnitt('3. Kein Anlass: gleich, neuer, oder Server antwortet nicht');
for (const f of [
    { t: 'gleiche Version', o: { mv: '1.2.0.0', server: '1.2.0.0', office: 'box' } },
    { t: 'installiert ist NEUER', o: { mv: '1.3.0.0', server: '1.2.0.0', office: 'box' } },
    { t: 'HTTP-Fehler', o: { mv: '1.0.0.0', verFehler: 'http', office: 'box' } },
    { t: 'Netzfehler', o: { mv: '1.0.0.0', verFehler: 'netz', office: 'box' } },
    { t: 'Antwort ohne Version', o: { mv: '1.0.0.0', verFehler: 'leer', office: 'box' } }
]) {
    const u = baue(Object.assign({ token: true }, f.o));
    await warte(60);
    pruefe(!sichtbar(u.band()), 'kein Band: ' + f.t);
    u.w.close();
}

abschnitt('4. Numerischer Vergleich (ein String-Vergleich liegt hier falsch)');
{
    const u = baue({ mv: '1.9.0.0', server: '1.10.0.0', office: 'box', token: true });
    await warte(60);
    pruefe(sichtbar(u.band()), '1.9.0.0 gilt als kleiner als 1.10.0.0');
    u.w.close();
}
{
    const u = baue({ mv: '1.10.0.0', server: '1.9.0.0', office: 'box', token: true });
    await warte(60);
    pruefe(!sichtbar(u.band()), '1.10.0.0 gilt NICHT als kleiner als 1.9.0.0');
    u.w.close();
}
{
    // Kurzform gegen Langform: 1.2 und 1.2.0.0 sind dieselbe Fassung.
    const u = baue({ mv: '1.2', server: '1.2.0.0', office: 'box', token: true });
    await warte(60);
    pruefe(!sichtbar(u.band()), '1.2 und 1.2.0.0 gelten als gleich');
    u.w.close();
}

abschnitt('5. Ohne mv – die Aussage haengt am Outlook-Kontext');
{
    const u = baue({ server: '1.2.0.0', office: 'box', token: true });
    await warte(60);
    const b = u.band();
    pruefe(sichtbar(b), 'in Outlook: Band erscheint (Manifest ist aelter als die Pruefung)');
    pruefe(/meldet ihre Version nicht/i.test(b.textContent),
        'und behauptet KEINE installierte Versionsnummer', b.textContent);
    pruefe(/1\.2\.0\.0/.test(b.textContent), 'nennt die Serverversion');
    pruefe(!/\{neu\}/.test(b.textContent), 'kein Platzhalter uebrig');
    u.w.close();
}
{
    const u = baue({ server: '1.2.0.0', office: 'leer', token: true });
    await warte(60);
    pruefe(!sichtbar(u.band()),
        'ohne Outlook-Kontext: KEIN Band – das ist ein Browseraufruf');
    pruefe(u.rufe.filter(r => r.url.indexOf('/api/addin/version') === 0).length === 0,
        'und der Server wird dafuer gar nicht gefragt');
    u.w.close();
}
{
    // Der echte Fall "office.js kommt nie" – mit der vollen Zeitgrenze.
    const u = baue({ server: '1.2.0.0', token: true });
    await warte(4400);
    pruefe(!sichtbar(u.band()), 'office.js unerreichbar und kein mv: kein Band');
    u.w.close();
}

abschnitt('6. mv ist Fremdeingabe');
{
    const u = baue({ mv: '<img src=x onerror=alert(1)>', server: '1.2.0.0',
                     office: 'box', token: true });
    await warte(60);
    const b = u.band();
    pruefe(sichtbar(b), 'Muellwert wird als "unbekannt" behandelt, nicht als Version');
    pruefe(!b.querySelector('img'), 'keine Nutzlast im DOM');
    // Geprueft wird die EIGENSCHAFT (kein Ereignis-Attribut im Band), nicht ein
    // Teilstring: escapter Text darf das Wort ruhig enthalten, gefaehrlich ist
    // nur ein echtes Attribut (Lehre aus den Marken-Waechtern).
    const attr = Array.prototype.some.call(b.querySelectorAll('*'),
        el => Array.prototype.some.call(el.attributes, a => /^on/i.test(a.name)));
    pruefe(!attr, 'kein Ereignis-Attribut im Band');
    pruefe(/meldet ihre Version nicht/i.test(b.textContent),
        'Text ist der ehrliche "unbekannt"-Fall');
    u.w.close();
}
{
    const u = baue({ mv: '1.1.0.0-beta', server: '1.2.0.0', office: 'leer', token: true });
    await warte(60);
    pruefe(!sichtbar(u.band()),
        'Wert mit falscher Form gilt nicht als mv (hier ohne Outlook: kein Band)');
    u.w.close();
}

abschnitt('7. Band gilt auch VOR der Anmeldung');
{
    const u = baue({ mv: '1.1.0.0', server: '1.2.0.0', office: 'box' });   // kein Token
    await warte(120);
    const w = u.w;
    pruefe(!w.document.getElementById('ad-login').classList.contains('hidden'),
        'Anmeldebildschirm steht (kein Token)');
    pruefe(sichtbar(u.band()), 'und das Band steht trotzdem da');
    u.w.close();
}

abschnitt('8. Sprachwechsel uebersetzt das Band ohne zweiten Abruf');
{
    const u = baue({ mv: '1.1.0.0', server: '1.2.0.0', office: 'box', token: true });
    await warte(120);
    const w = u.w;
    const vorher = u.band().textContent;
    const knopf = w.document.getElementById('ad-lang');
    pruefe(!!knopf, 'Sprachknopf vorhanden');
    knopf.click();
    await warte(120);
    const nachher = u.band().textContent;
    pruefe(/newer version|Installed is/i.test(nachher),
        'Band ist englisch', nachher);
    pruefe(nachher !== vorher, 'Text hat sich geaendert');
    pruefe(!/\{alt\}|\{neu\}/.test(nachher), 'auch englisch kein Platzhalter uebrig');
    pruefe(u.rufe.filter(r => r.url.split('?')[0] === '/api/addin/version').length === 1,
        'die Serverversion wurde NICHT erneut abgerufen');
    u.w.close();
}

abschnitt('9. i18n: alle Schluessel in DE und EN');
{
    const keys = ['addin.upd_head', 'addin.upd_text', 'addin.upd_unknown',
                  'addin.upd_how', 'addin.upd_get'];
    keys.forEach(k => {
        pruefe((I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length === 2,
            k + ' genau zweimal (DE + EN)');
    });
    pruefe(/'addin\.upd_text':\s*'[^']*\{alt\}[^']*\{neu\}/.test(I18N),
        'DE-Text traegt beide Platzhalter');
    // Wer den Text spaeter mit zwei gleichen Platzhaltern versieht, braucht eine
    // globale Ersetzung – die ist hier schon eingebaut, aber der Grund gehoert
    // festgehalten (Lehre aus sessions.hint).
    pruefe(nurCode(ADDINJS).indexOf(".replace(/\\{neu\\}/g,") !== -1,
        'ersetzt {neu} GLOBAL, nicht nur das erste Vorkommen');
    pruefe(nurCode(ADDINJS).indexOf(".replace(/\\{alt\\}/g,") !== -1,
        'ersetzt {alt} GLOBAL');
}

abschnitt('10. Verdrahtung Server-Seite');
{
    const py = nurCode(ADDINPY);
    pruefe(/ADDIN_VERSION\s*=\s*"1\.2\.0\.0"/.test(py),
        'ADDIN_VERSION wurde erhoeht (das Manifest hat sich geaendert)');
    pruefe(/taskpane\.html\?mv=%s.*ADDIN_VERSION/s.test(py.replace(/\n/g, ' ')),
        'die Taskpane-URL traegt die Manifest-Version');
    const mn = nurCode(MAIN);
    pruefe(mn.indexOf('@app.get("/api/addin/version")') !== -1,
        'Versions-Endpunkt registriert');
    const ep = MAIN.split('@app.get("/api/addin/version")')[1] || '';
    const rumpf = ep.split('@app.')[0];
    pruefe(/async def addin_version\(\s*\)/.test(rumpf),
        'ohne Auth-Dependency – der Hinweis gilt vor der Anmeldung');
    pruefe(/no-store/.test(rumpf),
        'no-store: sonst beantwortet der Cache die Frage von gestern');
    pruefe(/addin\.ADDIN_VERSION/.test(rumpf),
        'liefert genau die Manifest-Version');
}

abschnitt('11. Doku behauptet nicht mehr das Alte');
{
    pruefe(!/an den Aufgabenfenster-Dateien etwas\s*\n?#?\s*aendert, das ein installiertes/
        .test(ADDINPY), 'der irrefuehrende Kommentar an ADDIN_VERSION ist weg');
    pruefe(/Was sich von selbst aktualisiert/.test(DOKU),
        'Doku trennt "aktualisiert sich" von "muss verteilt werden"');
    pruefe(/Update-App/.test(DOKU),
        'nennt den Grund: es gibt kein Update-App');
    pruefe(/taskpane\.html\?mv=/.test(DOKU),
        'beschreibt den mv-Parameter');
}

console.log('\n' + (fail ? '✗ ' : '✓ ') + ok + ' bestanden, ' + fail + ' fehlgeschlagen');
process.exit(fail ? 1 : 0);
})();
