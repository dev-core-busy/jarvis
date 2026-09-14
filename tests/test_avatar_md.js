/* Waechter: `**fett**` im Antwortfenster des Avatars.
 *
 * ⚠ DER KERN IST DIE DRIFT-SCHRANKE. „Fett wie im Browser-Plugin" ist eine
 * Zusage ueber die REGEL, nicht ueber das Ergebnis. Laufen die drei Fassungen
 * (Avatar, Jira-Plugin, AI-Maus) auseinander, deutet DIESELBE Modellantwort an
 * drei Orten verschieden – und niemand koennte erklaeren warum.
 *
 * Der Parser wird AUSGEFUEHRT, nicht gelesen: ob am Ende ein `<strong>` im DOM
 * steht, kann eine Quelltext-Suche nicht beantworten.
 *
 * Aufruf:  node tests/test_avatar_md.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const AV_JS = path.join(ROOT, 'frontend', 'js', 'avatar.js');
const AV_CSS = path.join(ROOT, 'frontend', 'css', 'avatar.css');
const POPUP = path.join(ROOT, 'browser-addon', 'popup.js');
const MD_CS = path.join(ROOT, 'ai-mouse', 'src', 'AiMouse', 'Ui', 'Markdown.cs');

/* jsdom an allen ueblichen Orten suchen – ein Waechter, der nur auf einem
   Rechner laeuft, ist ein halber. Ohne jsdom gibt es keine Aussage: Exit 2,
   damit „konnte nicht laufen" nicht wie „bestanden" aussieht. */
let JSDOM = null;
for (const d of [path.join(ROOT, 'node_modules'), path.join(ROOT, 'data', 'node_modules'),
                 '/tmp/node_modules', '/usr/share/nodejs',
                 process.env.JSDOM_PATH || '']) {
    if (!d) continue;
    try { JSDOM = require(path.join(d, 'jsdom')).JSDOM; break; } catch (e) {}
}
if (!JSDOM) { console.error('jsdom nicht gefunden (JSDOM_PATH setzen) – KEINE AUSSAGE'); process.exit(2); }

let ok = 0, fail = 0, bilanz = false;
/* ⚠ FRUEH REGISTRIERT, nicht am Dateiende: bricht der Lauf vorher ab (ein
   Wurf beim Lesen, ein Schnitt, der nichts trifft), ist das ohne diese Zeile
   von „bestanden" nicht zu unterscheiden. Am Ende registriert kann der
   Handler nie mit `bilanz === false` feuern – belegt mit erzwungenem Wurf. */
process.on('exit', function () {
    if (!bilanz) { console.log('\n⚠ ABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});
function check(text, bed) {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text); }
}
/* Nie ungeprueft dereferenzieren: ein Wurf in einer Pruefung beendet den Lauf
   OHNE Bilanzzeile und ist dann von „nicht gelaufen" nicht zu unterscheiden. */
function sicher(fn, info) {
    try { return fn(); } catch (e) { check((info || 'Aufruf') + ' wirft: ' + e.message, false); return null; }
}

const av = fs.readFileSync(AV_JS, 'utf8');
const css = fs.readFileSync(AV_CSS, 'utf8');
const pop = fs.readFileSync(POPUP, 'utf8');
const mdcs = fs.readFileSync(MD_CS, 'utf8');

/* Klammer-Schnitt: zaehlt Klammern statt am ersten `\n}` zu enden – letzteres
   taugt nur fuer mehrzeilige Funktionen und frisst sonst die naechste mit. */
function schneide(quelle, kopf) {
    const i = quelle.indexOf(kopf);
    if (i < 0) return '';
    let tiefe = 0, j = quelle.indexOf('{', i);
    if (j < 0) return '';
    for (let k = j; k < quelle.length; k++) {
        if (quelle[k] === '{') tiefe++;
        else if (quelle[k] === '}') { tiefe--; if (!tiefe) return quelle.slice(i, k + 1); }
    }
    return '';
}

// ══ 1. Der Parser wird GELADEN und ausgefuehrt Parser wird GELADEN und ausgefuehrt ════════════════════════
console.log('\n--- 1. Bausteine laden ---');

const teile = [
    schneide(av, 'function esc('),
    (av.match(/var _FETT_RE = \(function \(\) \{[\s\S]*?\}\)\(\);/) || [''])[0],
    schneide(av, 'function fett('),
    schneide(av, 'function fmt('),
    schneide(av, 'function addBot(')
];
check('alle fuenf Bausteine geschnitten', teile.every(t => t.length > 0));
check('der Schnitt enthaelt wirklich die Fett-Regel (Positivkontrolle)',
      teile[1].includes('(?<=') && teile[2].includes('<strong>'));

/* ⚠ OHNE `runScripts` IST `window.eval` NODES EVAL – dort gibt es kein
   `document`, und der Waechter scheitert an seinem eigenen Aufbau. */
const dom = new JSDOM('<!doctype html><html><body><div id="log"></div></body></html>',
                      { runScripts: 'outside-only' });
const g = dom.window;
let gebaut = false;
sicher(() => {
    g.eval('var els = { log: document.getElementById("log") };\n'
         + 'function scrollLog() {}\n'
         + 'function T(k, f) { return f; }\n'
         + teile.join('\n') + '\n');
    gebaut = true;
}, 'Bausteine in jsdom laden');
check('die Bausteine laufen in jsdom', gebaut);

function bot(text, md) {
    return sicher(() => { g.eval('els.log.innerHTML = "";'); return g.eval(
        'addBot(' + JSON.stringify(text) + ', ' + (md ? 'true' : 'undefined') + ').innerHTML'); },
        'addBot(' + JSON.stringify(text).slice(0, 40) + ')');
}

// ══ 2. Drift-Schranke ueber alle DREI Fassungen ueber alle DREI Fassungen ═══════════════════════
console.log('\n--- 2. dieselbe Regel an drei Orten ---');

const mPop = pop.match(/const _FETT_RE = \/(.+?)\/;/);
check('die Fett-Regel des Jira-Plugins ist auffindbar', mPop !== null);

const mCs = mdcs.match(/new\(@"(.+?)",/);
check('die Fett-Regel der AI-Maus ist auffindbar', mCs !== null);

/* ⚠ VERGLICHEN WIRD DIE WIRKSAME REGEL, NICHT DER QUELLTEXT. Der Avatar
   schreibt sie als String (`\\S`), das Plugin als Literal (`\S`) – ein
   Textvergleich waere hier trivial falsch. `.source` aus dem GELADENEN Modul
   ist die Eigenschaft, um die es geht: was der Code wirklich anwendet. */
const avSource = sicher(() => g.eval('_FETT_RE && _FETT_RE.source'), 'Avatar-Regel lesen');
check('die Fett-Regel des Avatars ist zur Laufzeit gebaut', typeof avSource === 'string');
check('Avatar == Jira-Plugin (' + (mPop ? mPop[1] : '?') + ')',
      avSource !== null && mPop !== null && avSource === mPop[1]);
check('Avatar == AI-Maus', avSource !== null && mCs !== null && avSource === mCs[1]);

// ══ 3. Parse-Sicherheit im ausgelieferten Frontend kein Lookbehind-LITERAL im Frontend ══════════
console.log('\n--- 3. Parse-Sicherheit im ausgelieferten Frontend ---');

/* ⚠ EIN LOOKBEHIND IM REGEX-LITERAL WIRFT SCHON BEIM PARSEN DER DATEI – auf
   Safari < 16.4 waere damit nicht die Fettschrift weg, sondern das ganze
   Modul. Der Ausweg ist billig und steht in `avatar.js`: den Ausdruck als
   String bauen und den Fehler auffangen. Geprueft wird als REGEL ueber alle
   Module, damit auch ein KUENFTIGES Literal auffaellt. */
const jsDir = path.join(ROOT, 'frontend', 'js');
const module_ = fs.readdirSync(jsDir).filter(f => f.endsWith('.js'));
check('es gibt ueberhaupt Frontend-Module zu pruefen', module_.length > 10);
const mitLiteral = [];
for (const f of module_) {
    const q = fs.readFileSync(path.join(jsDir, f), 'utf8');
    // Nur Regex-LITERALE (`/…(?<=…)…/`), nicht Strings und nicht Kommentare.
    for (const z of q.split('\n')) {
        const ohneKomm = z.replace(/^\s*(\/\/|\*).*$/, '');
        if (/\/[^\/\n]*\(\?<[=!][^\/\n]*\/[gimsuy]*/.test(ohneKomm)) { mitLiteral.push(f + ': ' + z.trim().slice(0, 60)); break; }
    }
}
check('kein Regex-Literal mit Lookbehind in frontend/js/ ' +
      (mitLiteral.length ? '(' + mitLiteral.join(' | ') + ')' : ''), mitLiteral.length === 0);
check('der Avatar baut seine Regel als String und faengt den Fehler auf',
      /new RegExp\(/.test(av) && /catch \(e\) \{ return null; \}/.test(av));

// ══ 4. Die Faelle Faelle ════════════════════════════════════════════════════
console.log('\n--- 4. ausgefuehrt: aus `**x**` wird <strong> ---');

// Der Regelfall.
check('`**Lösung:**` wird fett',
      bot('**Lösung:** neu starten', true) === '<strong>Lösung:</strong> neu starten');
check('mehrere Auszeichnungen in einer Zeile',
      bot('**A** und **B**', true) === '<strong>A</strong> und <strong>B</strong>');
check('ueber mehrere Zeilen hinweg',
      bot('**Eins**\nText\n**Zwei**', true) === '<strong>Eins</strong>\nText\n<strong>Zwei</strong>');

/* ⚠ DIE `\S`-WAECHTER SIND DER UNTERSCHIED ZWISCHEN BRAUCHBAR UND
   GEFAEHRLICH – ohne sie verstuemmelt die Regel gewoehnlichen Text. */
check('`2 * 3 * 4` bleibt unangetastet', bot('2 * 3 * 4', true) === '2 * 3 * 4');
check('`*.txt` bleibt unangetastet', bot('Dateien *.txt und *.md', true) === 'Dateien *.txt und *.md');
check('`** allein **` ist keine Auszeichnung', bot('a ** allein ** b', true) === 'a ** allein ** b');
check('ein einzelnes `**` bleibt stehen', bot('Zwei Sterne ** hier', true) === 'Zwei Sterne ** hier');
check('nicht ueber einen Umbruch hinweg', bot('**oben\nunten**', true) === '**oben\nunten**');

// Vorgabe AUS – fail-safe.
check('ohne den Schalter passiert NICHTS (Vorgabe aus)',
      bot('**Lösung:** neu starten') === '**Lösung:** neu starten');

/* ⚠ DER RUECKFALL WIRD AUSGEFUEHRT, NICHT GELESEN. In node gibt es Lookbehind,
   der Zweig waere sonst unerreichbar – und eine Gegenprobe dazu bliebe stumm.
   Gestellt wird die Lage eines alten Safari: `_FETT_RE` ist null. Dann darf
   NICHTS werfen, und der Text kommt unveraendert an (kein Fett statt totem
   Modul). */
sicher(() => {
    g.eval('var _FETT_RE_SICHER = _FETT_RE; _FETT_RE = null;');
    const r = bot('**Lösung:** neu starten', true);
    check('ohne Lookbehind-Unterstuetzung bleibt der Text unveraendert (kein Wurf)',
          r === '**Lösung:** neu starten');
    const l = bot('**siehe https://x.de**', true);
    check('und der Link funktioniert dort weiter',
          l !== null && l.includes('<a href="https://x.de"'));
    g.eval('_FETT_RE = _FETT_RE_SICHER;');
    check('die Regel ist danach wieder da (Positivkontrolle)',
          bot('**x**', true) === '<strong>x</strong>');
}, 'Rueckfall ohne Lookbehind');

// ══ 5. Die Maskierung bleibt Maskierung bleibt ══════════════════════════════════════════
console.log('\n--- 5. Fremdtext kann kein Markup einschleusen ---');

/* Der Text kommt aus einem Modell, das Quellen aus der Wissensdatenbank
   verarbeitet hat – also Fremdtext. */
const einschleus = bot('**<img src=x onerror=alert(1)>**', true);
check('ein `<img onerror>` wird zu Text, nicht zu Markup',
      einschleus !== null && einschleus.includes('&lt;img') && !einschleus.includes('<img'));
check('und steht trotzdem im fetten Abschnitt',
      einschleus !== null && einschleus.includes('<strong>&lt;img'));
const skript = bot('<script>alert(1)</script>', true);
check('ein `<script>` ebenso', skript !== null && !skript.includes('<script>'));

sicher(() => {
    g.eval('els.log.innerHTML = "";');
    g.eval('addBot("**<b>x</b>**", true);');
    check('im DOM entsteht KEIN fremdes Element',
          g.document.getElementById('log').querySelectorAll('b, img, script').length === 0);
    check('aber ein <strong>',
          g.document.getElementById('log').querySelectorAll('strong').length === 1);
}, 'DOM-Messung');

// ══ 6. URLs ══════════════════════════════════════════════════════════
console.log('\n--- 6. Links und Fett stoeren einander nicht ---');

const linkFett = bot('**siehe https://x.de/a**', true);
check('ein Link INNERHALB eines fetten Abschnitts bleibt ein Link',
      linkFett !== null && linkFett.includes('<strong>siehe <a href="https://x.de/a"'));
const urlStern = bot('https://x.de/**pfad**/y', true);
check('`**` INNERHALB einer Adresse zerreisst sie NICHT',
      urlStern !== null && urlStern.includes('href="https://x.de/**pfad**/y"')
      && !urlStern.includes('<strong>'));
const nurLink = bot('siehe https://x.de', true);
check('ein gewoehnlicher Link funktioniert weiter',
      nurLink !== null && nurLink.includes('<a href="https://x.de"') && nurLink.includes('rel="noopener"'));

/* ⚠ EIN EINZELNES `*` GEHOERT ZUR ADRESSE, ein PAAR ist Markdown. Wer beides
   trimmt, laesst den Link auf ein ANDERES Ziel zeigen als der sichtbare Text
   nennt – und das auch bei `md === false`, also im Begruessungstext und in
   Servermeldungen, wo nie etwas gedeutet wird. */
const echtesStern = bot('Siehe https://server/api/* gesperrt');
check('eine Adresse, die auf EIN `*` endet, bleibt vollstaendig verlinkt',
      echtesStern !== null && echtesStern.includes('href="https://server/api/*"'));
const mitPunkt = bot('**Siehe https://x.de/doku**.', true);
check('`**` und Satzzeichen zusammen werden getrimmt',
      mitPunkt !== null && mitPunkt.includes('href="https://x.de/doku"')
      && mitPunkt.endsWith('.') && mitPunkt.includes('<strong>'));

/* ⚠ DER PLATZHALTER DARF AUS DER ANTWORT NICHT NACHBAUBAR SEIN. `esc()`
   maskiert `@` nicht: mit einer festen Marke wird `@@U0@@` aus dem Modelltext
   beim Zuruecksetzen ersetzt – durch `"undefined"` ohne Link im Text, sonst
   durch eine DUBLETTE des ersten Links. Beides ist stiller Textverlust. */
const roheMarke = bot('Code @@U0@@ pruefen');
check('`@@U0@@` aus der Antwort bleibt stehen (kein "undefined")',
      roheMarke === 'Code @@U0@@ pruefen');
const markeMitLink = bot('Siehe https://a.de und @@U0@@');
check('und erzeugt KEINE Dublette des vorhandenen Links',
      markeMitLink !== null && (markeMitLink.match(/<a /g) || []).length === 1
      && markeMitLink.includes('@@U0@@'));
const zweiLinks = bot('https://a.de und https://b.de');
check('zwei Links werden weiterhin korrekt zugeordnet',
      zweiLinks !== null && zweiLinks.includes('href="https://a.de"')
      && zweiLinks.includes('href="https://b.de"'));
check('die Marke wird je Aufruf neu gezogen',
      /Math\.random\(\)/.test(teile[3]) && !/'@@U'/.test(teile[3]));

// ══ 7. Verdrahtung: NUR Modelltext wird gedeutet NUR Modelltext wird gedeutet ══════════════════════
console.log('\n--- 7. Fehlermeldungen werden nicht gedeutet ---');

/* ⚠ Gemessen wird die EIGENSCHAFT ueber ALLE Aufrufstellen, nicht eine Liste:
   genau die zwei Stellen mit Modelltext (`ans`) deuten, alle uebrigen nicht.
   Damit faellt auch eine KUENFTIGE Meldung auf, die den Schalter mitnimmt. */
const rufe = (av.match(/addBot\([^\n]*\)/g) || []).filter(z => !z.startsWith('addBot(text'));
check('es gibt addBot-Aufrufe zu pruefen (Positivkontrolle)', rufe.length >= 7);
const mitMd = rufe.filter(z => /,\s*true\s*\)/.test(z));
const ohneMd = rufe.filter(z => !/,\s*true\s*\)/.test(z));
check('genau ZWEI Aufrufe deuten Markdown (' + mitMd.length + ')', mitMd.length === 2);
check('und beide uebergeben die Modellantwort `ans`',
      mitMd.every(z => /addBot\(ans,\s*true\)/.test(z)));
check('keine Meldung mit i18n-Text deutet Markdown',
      ohneMd.every(z => !/,\s*true/.test(z)));
for (const m of ['avatar.error', 'avatar.blocked', 'avatar.reauth', 'avatar.stopped', 'avatar.empty'])
    check('  `' + m + '` wird als Text ausgegeben',
          rufe.some(z => z.includes(m)) && !rufe.some(z => z.includes(m) && /,\s*true/.test(z)));
check('die Servermeldung (`res.d.detail`) ebenfalls',
      !rufe.some(z => z.includes('detail') && /,\s*true/.test(z)));

/* Die Sprachausgabe bekommt den ROHEN Text – `stripForSpeech` entfernt die
   Sternchen ohnehin. Wer ihr stattdessen den gedeuteten Text gaebe, liesse
   `<strong>` vorlesen. */
check('vorgelesen wird der Rohtext, nicht das gerenderte Markup',
      /speak\(ans\)/.test(av) && !/speak\(fmt\(/.test(av));
check('und die Sternchen fallen dort weiter heraus',
      /replace\(\/\[\*_`#>\]\/g/.test(av));

// ══ 8. Anzeige ═══════════════════════════════════════════════════════
console.log('\n--- 8. Darstellung ---');

/* `white-space: pre-wrap` traegt die Zeilenumbrueche – `<strong>` ist ein
   Inline-Element und stoert das nicht. Ohne die Regel waere jeder Umbruch der
   Antwort ein Leerzeichen. */
check('die Bot-Blase behaelt ihre Zeilenumbrueche (pre-wrap)',
      /\.jav-msg-bot\s*\{[^}]*white-space:\s*pre-wrap/.test(css));

/* ⚠ GEMESSEN, NICHT GESCHAETZT: `--accent-hover` liegt im HELLEN Thema bei
   2,30:1 auf der Blase – ein Link im Antwortfenster war dort kaum lesbar.
   Dieselbe Stelle wie in `/chat` (2026-09-08). Der Ton wird ABGELEITET, nicht
   festgesetzt: die Akzentfarbe ist brandingabhaengig. */
const linkRegel = (css.match(/body\.light\s+\.jav-msg a\s*\{[^}]*\}/) || [''])[0];
check('im hellen Thema ist der Link abgedunkelt', linkRegel.length > 0);
check('und der Ton ist aus --accent abgeleitet, nicht fest gesetzt',
      /color-mix\([^)]*var\(--accent/.test(linkRegel));
/* ⚠ NICHT auf `body.dark` pruefen – das Projekt kennt nur `body.light`, die
   Bedingung waere trivial wahr (nachgestellt: eine zusaetzliche
   `.jav-msg a`-Regel mit color-mix gilt in BEIDEN Themen und blieb gruen).
   Gemessen wird die Eigenschaft: die Abdunklung steht in genau EINER Regel,
   und das ist die themengebundene. */
const cssOhneKomm = css.replace(/\/\*[\s\S]*?\*\//g, '');
const alleLink = cssOhneKomm.match(/[^}]*\.jav-msg a\s*\{[^}]*\}/g) || [];
const mitMix = alleLink.filter(r => /color-mix/.test(r));
check('genau eine Link-Regel dunkelt ab (' + mitMix.length + ')', mitMix.length === 1);
check('und sie haengt am hellen Thema', mitMix.length === 1 && /body\.light/.test(mitMix[0]));

/* Der Cache-Buster muss an ALLEN Einbindungen gleich stehen – sonst behaelt
   eine Seite die alte Fassung aus dem Cache. */
const seiten = fs.readdirSync(path.join(ROOT, 'frontend')).filter(f => f.endsWith('.html'));
const staende = new Set();
let n = 0;
for (const f of seiten) {
    const q = fs.readFileSync(path.join(ROOT, 'frontend', f), 'utf8');
    const m = q.match(/avatar\.js\?v=(\d+)/);
    if (m) { staende.add(m[1]); n++; }
    else if (q.includes('avatar.js')) { staende.add('OHNE'); n++; }
}
check('avatar.js ist auf mehreren Seiten eingebunden (' + n + ')', n >= 10);
check('und ueberall mit demselben Stand (' + [...staende].join(', ') + ')', staende.size === 1);

// ══ Bilanz ═══════════════════════════════════════════════════════════
bilanz = true;
console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
