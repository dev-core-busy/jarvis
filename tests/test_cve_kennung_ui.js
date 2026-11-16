/* Auskunft zu einer gesuchten Kennung (syspackages.js, kennungBlock).
 *
 * Anlass (2026-11-16): die Suche der Paketliste nach CVE-2026-99270 blieb auf
 * ECHT leer – der laufende Kernel trug die Behebung schon, es gab also keinen
 * Befund. Eine leere Liste sah aus wie „unbekannt". Seitdem fragt der Kasten
 * bei einer VOLLSTAENDIGEN Kennung ohne sichtbaren Befund den Server und zeigt
 * die Antwort als einen Satz.
 *
 * Geprueft wird die WIRKUNG: die echten Funktionen werden am Syntaxbaum aus
 * der ausgelieferten Datei geschnitten und ausgefuehrt (fetch und Zeitgeber
 * sind Attrappen mit der echten Signatur), das Markup wird gelesen.
 *
 *     node tests/test_cve_kennung_ui.js     Exit 0 gruen, 1 rot, 2 nicht lauffaehig
 */
'use strict';
const fs = require('fs');
const path = require('path');
const fertig = require('./lib/bilanz')({ stumm: true });
const acorn = require('./lib/acorn_laden')();

const QUELLE = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'syspackages.js'), 'utf8');
let ok = 0, fail = 0;
function check(cond, label, detail) {
    if (cond) { ok++; console.log('  OK   ' + label); }
    else { fail++; console.log('  FAIL ' + label + (detail ? ' - ' + detail : '')); }
}

const baum = acorn.parse(QUELLE, { ecmaVersion: 'latest', sourceType: 'script' });
const funktionen = {};
let kennRe = null;
(function lauf(k) {
    if (!k || typeof k.type !== 'string') return;
    if (k.type === 'FunctionDeclaration' && k.id) funktionen[k.id.name] = { text: QUELLE.slice(k.start, k.end), knoten: k };
    if (k.type === 'VariableDeclarator' && k.id && k.id.name === 'KENNUNG_RE') kennRe = QUELLE.slice(k.init.start, k.init.end);
    for (const w of Object.values(k)) {
        if (Array.isArray(w)) w.forEach(lauf);
        else if (w && typeof w.type === 'string') lauf(w);
    }
})(baum);

const NOETIG = ['esc', 'klasseText', 'bereichText', 'anderswoText', 'zeitpunkt', 'kennungAusSuche',
                'kennungAnfragen', 'kennZustandText', 'kennBetroffenText', 'kennLinks', 'kennungBlock', 'zeichnen'];
const fehlt = NOETIG.filter(function (n) { return !funktionen[n]; });
if (fehlt.length || !kennRe) {
    console.log('ABBRUCH: nicht gefunden: ' + fehlt.concat(kennRe ? [] : ['KENNUNG_RE']).join(', '));
    process.exit(2);
}

// Prolog: Zustand als Closure-Variablen; fetch/setTimeout als Attrappen, die
// die Aufrufe festhalten (der Test loest sie von Hand aus).
const prolog = [
    'function T(k, d) { return d; }',
    'function token() { return "TOK"; }',
    'var _kennung = {}, _kennungTimer = null, _bericht = {}, _cve = { laeuft: false }, _offen = true, _gezeichnet = 0;',
    'function offen() { return _offen; }',
    'function zeichnen() { _gezeichnet++; }',
    'var _zeitgeber = [], _abrufe = [];',
    'function setTimeout(f, ms) { _zeitgeber.push({ f: f, ms: ms, aus: false }); return _zeitgeber.length; }',
    'function clearTimeout(id) { if (_zeitgeber[id - 1]) _zeitgeber[id - 1].aus = true; }',
    'var _antwort = null;',
    'function fetch(url, opt) { _abrufe.push({ url: url, opt: opt }); var a = _antwort;',
    '  return Promise.resolve({ ok: a.status === 200, status: a.status, json: function () { return Promise.resolve(a.body); } }); }',
    'var KENNUNG_RE = ' + kennRe + ';',
].join('\n');
const AUSFUEHREN = NOETIG.filter(function (n) { return n !== 'zeichnen'; });
const api = new Function(prolog + '\n' + AUSFUEHREN.map(function (n) { return funktionen[n].text; }).join('\n')
    + '\nreturn { kennungAusSuche: kennungAusSuche, kennungBlock: kennungBlock,'
    + ' zeitgeber: function () { return _zeitgeber; }, abrufe: function () { return _abrufe; },'
    + ' gezeichnet: function () { return _gezeichnet; },'
    + ' antwort: function (a) { _antwort = a; },'
    + ' leeren: function () { _kennung = {}; _kennungTimer = null; _zeitgeber = []; _abrufe = []; _gezeichnet = 0; },'
    + ' zustand: function () { return _kennung; },'
    + ' laeuft: function (b) { _cve.laeuft = b; } };')();

/** Zeitgeber feuern und die Promise-Kette ablaufen lassen. */
async function abwarten() {
    api.zeitgeber().forEach(function (z) { if (!z.aus && !z.lief) { z.lief = true; z.f(); } });
    for (let i = 0; i < 10; i++) await Promise.resolve();
}
async function auskunft(k, body, status) {
    api.leeren();
    api.antwort({ status: status || 200, body: body });
    api.kennungBlock(k);
    await abwarten();
    return api.kennungBlock(k);
}
function urteil(html) {
    const m = /<div class="jv-pkg-kenn-urteil">([^<]*)<\/div>/.exec(html);
    return m ? m[1] : '';
}

(async function () {
    // Positivkontrolle: der Schnitt laeuft, die Erkennung trifft die Kennung.
    if (api.kennungAusSuche('cve-2026-99270') !== 'CVE-2026-99270') {
        console.log('ABBRUCH: kennungAusSuche erkennt die Kennung nicht');
        process.exit(2);
    }

    console.log('\n1. Erkennung der Kennung im Suchtext');
    check(api.kennungAusSuche('  CVE-2026-99270 ') === 'CVE-2026-99270', 'Leerraum und Grossschreibung egal');
    check(api.kennungAusSuche('GHSA-Q675-QJ96-32M9') === 'GHSA-q675-qj96-32m9', 'GHSA wird wie bei OSV geschrieben');
    check(api.kennungAusSuche('cve-2026-99') === '', 'unvollstaendige Kennung (zu wenige Ziffern) loest nichts aus');
    check(api.kennungAusSuche('linux cve-2026-99270') === '' && api.kennungAusSuche('xcve-2026-99270') === '',
          'nur die GANZE Suche als Kennung, kein Teilstring');
    check(api.kennungAusSuche('ghsa-aaaa-aaaa-aaaa') === '', 'GHSA mit unzulaessigen Zeichen wird nicht erkannt');

    console.log('\n2. Abruf');
    api.leeren();
    api.antwort({ status: 200, body: { ok: true, kennung: 'CVE-2026-99270', urteil: 'nicht_betroffen', befunde: [], lokal: [] } });
    const vorher = api.kennungBlock('CVE-2026-99270');
    check(/wird nachgesehen/.test(vorher) && /ist-laedt/.test(vorher), 'zuerst „wird nachgesehen"', vorher.slice(0, 160));
    check(api.abrufe().length === 0 && api.zeitgeber().length === 1 && api.zeitgeber()[0].ms >= 300,
          'der Abruf wartet die Tipp-Pause ab', JSON.stringify(api.zeitgeber().map(function (z) { return z.ms; })));
    api.kennungBlock('CVE-2026-99270');
    check(api.zeitgeber().length === 1, 'ein erneutes Zeichnen startet keinen zweiten Abruf');
    await abwarten();
    const a0 = api.abrufe()[0] || { opt: { headers: {} } };
    check(api.abrufe().length === 1 && a0.url === '/api/system/cve/kennung?k=CVE-2026-99270',
          'genau ein Abruf an die Auskunft, Kennung in der Adresse', a0.url);
    check(a0.opt.headers.Authorization === 'Bearer TOK', 'mit Sitzungstoken');
    check(api.gezeichnet() === 1, 'nach der Antwort wird neu gezeichnet', String(api.gezeichnet()));

    // Tippen: „CVE-2026-9927" ist schon gueltig, dann folgt die „0".
    api.leeren();
    api.antwort({ status: 200, body: { ok: true, urteil: 'unbekannt', befunde: [], lokal: [], online: { ok: true, gefunden: false } } });
    api.kennungBlock('CVE-2026-9927');
    api.kennungBlock('CVE-2026-99270');
    await abwarten();
    check(api.abrufe().length === 1 && /99270$/.test(api.abrufe()[0].url),
          'beim Weitertippen fragt nur die letzte Kennung', JSON.stringify(api.abrufe().map(function (a) { return a.url; })));
    check(!api.zustand()['CVE-2026-9927'], 'die nie gesendete Anfrage haengt nicht als „wird nachgesehen" fest');

    console.log('\n3. Eine klare Antwort je Lage');
    const behoben = await auskunft('CVE-2026-99270', { ok: true, kennung: 'CVE-2026-99270', urteil: 'nicht_betroffen',
        befunde: [], lokal: [{ quelle: 'linux', zustand: 'behoben', fix: '6.12.117-1', laufend: '6.12.117-1',
                               installiert: [{ paket: 'linux-image-6.12.117+deb13-amd64', version: '6.12.117-1' }] }] });
    check(urteil(behoben) === 'CVE-2026-99270 ist bekannt und betrifft dieses System nicht (mehr).',
          'behoben: „betrifft dieses System nicht (mehr)"', urteil(behoben));
    check(/linux: behoben · behoben in 6\.12\.117-1 · laufender Kernel 6\.12\.117-1/.test(behoben),
          'Bearbeitungsstand je Quellpaket: Zustand, Behebung, laufender Kernel', behoben);
    check(/ist-ok/.test(behoben) && !/data-cve-aktion/.test(behoben), 'ohne Handlungsbedarf kein Knopf');
    check(/security-tracker\.debian\.org\/tracker\/CVE-2026-99270/.test(behoben)
          && /nvd\.nist\.gov\/vuln\/detail\/CVE-2026-99270/.test(behoben), 'Verweise auf Tracker und NVD');

    const neu = await auskunft('CVE-2026-99270', { ok: true, urteil: 'betroffen', befunde: [],
        ergebnis_stand: '2026-11-15T19:00:09+01:00',
        lokal: [{ quelle: 'openssl', zustand: 'update', fix: '3.5.1-1',
                  installiert: [{ paket: 'libssl3t64', version: '3.5.0-1' }, { paket: 'openssl', version: '3.5.0-1' },
                                { paket: 'a', version: '1' }, { paket: 'b', version: '1' }] }] });
    check(urteil(neu) === 'CVE-2026-99270 betrifft dieses System.' && /ist-betroffen/.test(neu),
          'betroffen laut Tracker: „betrifft dieses System"', urteil(neu));
    check(/hat das noch nicht erfasst/.test(neu) && /data-cve-aktion="pruefen"/.test(neu),
          'ohne Befund im Pruefergebnis: Hinweis + „Jetzt prüfen"', neu);
    check(/installiert libssl3t64 3\.5\.0-1, openssl 3\.5\.0-1, a 1 … \(\+1\)/.test(neu),
          'lange Paketlisten werden gedeckelt und der Rest beziffert', neu);
    api.laeuft(true);
    check(!/data-cve-aktion="pruefen"/.test(api.kennungBlock('CVE-2026-99270')), 'laeuft schon eine Pruefung: kein Knopf');
    api.laeuft(false);

    const gefiltert = await auskunft('CVE-2026-1234', { ok: true, urteil: 'betroffen',
        befunde: [{ bereich: 'debian', quelle: 'linux', klasse: 'neustart', fix: '6.12.117-1' }], lokal: [] });
    check(/durch einen Filter oben ausgeblendet/.test(gefiltert) && /Debian linux: Neustart nötig/.test(gefiltert),
          'Befund vorhanden, aber nicht sichtbar: der Kasten nennt ihn und den Filter', gefiltert);
    check(!/data-cve-aktion/.test(gefiltert), 'mit Befund kein „Jetzt prüfen" (die Pruefung kennt ihn schon)');

    const fehlt = await auskunft('CVE-2026-55555', { ok: true, urteil: 'lokal_fehlt', befunde: [], lokal: [],
        tracker_stand: 'Sun, 15 Nov 2026 16:39:08 GMT',
        online: { ok: true, gefunden: true, veroeffentlicht: '2026-11-03', titel: 'tcp: <b>UAF</b>',
                  debian: [{ paket: 'linux', fix: '6.12.117-1', installiert: '6.12.116-1', betroffen: true }],
                  andere: [{ oekosystem: 'PyPI', paket: 'jinja2', installiert: '3.1.6', betroffen: false }] } });
    check(urteil(fehlt) === 'CVE-2026-55555 fehlt im lokalen Datenbestand, ist online aber bekannt.' && /ist-fehlt/.test(fehlt),
          'lokal unbekannt, online bekannt: genau das steht da', urteil(fehlt));
    check(/Online \(OSV\), veröffentlicht 2026-11-03: tcp: &lt;b&gt;UAF&lt;\/b&gt;/.test(fehlt),
          'Online-Stand mit Datum und Titel – maskiert', fehlt);
    check(/Debian · linux · behoben in 6\.12\.117-1 · hier 6\.12\.116-1: betroffen/.test(fehlt),
          'Abgleich gegen die installierte Version', fehlt);
    check(/PyPI · jinja2 · hier 3\.1\.6: nicht betroffen/.test(fehlt), 'Python-Paket mit Abgleich');
    const go = await auskunft('GHSA-q675-qj96-32m9', { ok: true, urteil: 'lokal_fehlt', befunde: [], lokal: [],
        online: { ok: true, gefunden: true, andere: [{ oekosystem: 'Go', paket: 'golang.org/x/image', installiert: '', betroffen: null }] } });
    check(/Go · golang\.org\/x\/image · hier nicht geprüft/.test(go) && !/nicht entscheidbar/.test(go),
          'nicht gepruefte Oekosysteme heissen so (nicht „nicht entscheidbar")', go);
    const unklar = await auskunft('CVE-2026-55559', { ok: true, urteil: 'lokal_fehlt', befunde: [], lokal: [],
        online: { ok: true, gefunden: true, debian: [{ paket: 'x', fix: '', installiert: '1.0', betroffen: null }] } });
    check(/hier 1\.0: nicht entscheidbar/.test(unklar), 'installiert, aber Bereich unlesbar: „nicht entscheidbar"', unklar);
    check(/Lokaler Stand des Debian-Trackers: Sun, 15 Nov 2026/.test(fehlt) && /data-cve-aktion="pruefen"/.test(fehlt),
          'nennt den lokalen Stand und bietet „Jetzt prüfen"', fehlt);
    check(/osv\.dev\/vulnerability\/CVE-2026-55555/.test(fehlt), 'Verweis auf OSV');

    const unbek = await auskunft('CVE-2099-99999', { ok: true, urteil: 'unbekannt', befunde: [], lokal: [],
        online: { ok: true, gefunden: false } });
    check(/weder lokal noch online \(OSV\) bekannt/.test(urteil(unbek)), 'nirgends bekannt: Schreibweise pruefen', urteil(unbek));

    const onf = await auskunft('CVE-2026-55556', { ok: true, urteil: 'online_fehler', befunde: [], lokal: [],
        online: { ok: false, fehler: 'URLError: timed out' } });
    check(/Online-Abfrage ist gescheitert: URLError: timed out/.test(urteil(onf)) && /ist-fehler/.test(onf),
          'Online-Fehler: mit Grund, nicht als „unbekannt"', urteil(onf));

    const http = await auskunft('CVE-2026-55557', { ok: false, fehler: 'Keine gültige Kennung' }, 400);
    check(/konnte nicht geholt werden: Keine gültige Kennung/.test(http), 'Ablehnung des Servers mit seinem Grund', http);
    const ohneText = await auskunft('CVE-2026-55558', null, 502);
    check(/konnte nicht geholt werden: HTTP 502/.test(ohneText), 'Antwort ohne JSON: HTTP-Status als Grund', ohneText);
    const ghsa = await auskunft('GHSA-q675-qj96-32m9', { ok: true, kennung: 'GHSA-q675-qj96-32m9', urteil: 'bewertet', befunde: [], lokal: [] });
    check(!/security-tracker/.test(ghsa) && /osv\.dev\/vulnerability\/GHSA-q675-qj96-32m9/.test(ghsa),
          'GHSA: kein Tracker-Verweis (der kennt nur CVE), aber OSV');

    console.log('\n4. Einbindung in zeichnen()');
    // Regel am Syntaxbaum: zeichnen() ruft kennungBlock nur hinter der
    // Bedingung „Kennung UND kein Treffer ueber eine Kennung", und das Ergebnis
    // landet im Markup direkt hinter dem Suchfeld.
    const z = funktionen.zeichnen.text;
    check(/kennungAusSuche\(q\)/.test(z) && /kennungBlock\(kennung\)/.test(z), 'zeichnen() erkennt die Kennung und ruft den Kasten');
    check(/Object\.keys\(ueberKennung\)\.length/.test(z) && /befundTrifft\(b, q\)/.test(z),
          'aber nur, wenn weder eine Paketzeile noch ein Python/npm-Befund die Kennung trifft');
    const iSuche = z.indexOf('id="jv-pkg-suche"'), iKenn = z.indexOf('+ kennHtml'), iTab = z.indexOf('jv-pkg-scroll');
    check(iSuche >= 0 && iKenn > iSuche && iKenn < iTab, 'der Kasten steht zwischen Suchfeld und Tabelle');

    fertig();
    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(function (e) { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
