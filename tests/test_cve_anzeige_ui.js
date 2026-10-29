/* Detailzeilen der Sicherheitsluecken (syspackages.js, befundZeilen).
 *
 * Geprueft wird die WIRKUNG: die echten Funktionen werden am Syntaxbaum aus
 * der ausgelieferten Datei geschnitten und ausgefuehrt, das erzeugte Markup
 * wird gelesen. Anlass (2026-10-29): 13 offene 7zip-Eintraege standen nur als
 * "ohne Debian-Update" da – dass 11 davon in forky/sid behoben und 10 fuers
 * naechste Zwischenrelease eingeplant sind, sah niemand. Und bei "ignored"
 * stand "Debian behebt ohne Sicherheitsmeldung: ignored", also das Gegenteil.
 *
 *     node tests/test_cve_anzeige_ui.js     Exit 0 gruen, 1 rot, 2 nicht lauffaehig
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

// Funktionen per Name aus dem Syntaxbaum schneiden (nicht per Text).
const baum = acorn.parse(QUELLE, { ecmaVersion: 'latest', sourceType: 'script' });
const funktionen = {};
let rang = null;
(function lauf(k) {
    if (!k || typeof k.type !== 'string') return;
    if (k.type === 'FunctionDeclaration' && k.id) funktionen[k.id.name] = QUELLE.slice(k.start, k.end);
    if (k.type === 'VariableDeclarator' && k.id && k.id.name === 'CVE_RANG') rang = QUELLE.slice(k.init.start, k.init.end);
    for (const w of Object.values(k)) {
        if (Array.isArray(w)) w.forEach(lauf);
        else if (w && typeof w.type === 'string') lauf(w);
    }
})(baum);

const NOETIG = ['esc', 'klasseText', 'einstufungText', 'trackerLink', 'befundLink', 'nodsaText', 'anderswoText',
                'befundZeilen', 'inPaketliste', 'einzelKnopf', 'quittierbareIds', 'paketGezeigt',
                'andereGezeigt', 'zeichnen', 'cveBlock'];
const fehlt = NOETIG.filter(function (n) { return !funktionen[n]; });
if (fehlt.length || !rang) {
    console.log('ABBRUCH: nicht gefunden: ' + fehlt.concat(rang ? [] : ['CVE_RANG']).join(', '));
    process.exit(2);
}
// T liefert die deutsche Vorgabe; "gesehen" ist leer.
// Filterzustand als Closure-Variablen (nicht als Parameter – eine Zuweisung
// traefe sonst nur die lokale Kopie), gesetzt ueber setze().
const prolog = 'function T(k, d) { return d; }\nvar _gesehen = {}, _nurLuecken = false, _nurUngesehen = false;\n'
    + 'function cveGesehen() { return _gesehen; }\nvar _cve = { laeuft: false };\n'
    + 'var CVE_RANG = ' + rang + ';\n';
const AUSFUEHREN = NOETIG.filter(function (n) { return n !== 'zeichnen' && n !== 'cveBlock'; });
const api = new Function(prolog + AUSFUEHREN.map(function (n) { return funktionen[n]; }).join('\n')
    + '\nreturn { befundZeilen: befundZeilen, inPaketliste: inPaketliste, einzelKnopf: einzelKnopf,'
    + ' paketGezeigt: paketGezeigt, andereGezeigt: andereGezeigt,'
    + ' setze: function (o) { _nurLuecken = !!o.l; _nurUngesehen = !!o.u; _gesehen = o.g || {}; } };')();

function zeile(b) {
    return api.befundZeilen([Object.assign({ id: 'x', bereich: 'debian', cve: 'CVE-2026-1',
                                             klasse: 'offen', einstufung: '' }, b)]);
}
function zusatz(html) {
    const m = /<div class="jv-pkg-cve-z">([^<]*)<\/div>/.exec(html);
    return m ? m[1] : '';
}

// Positivkontrolle: der Schnitt laeuft und rendert eine Zeile mit Kennung.
const basis = zeile({});
if (basis.indexOf('CVE-2026-1') < 0 || basis.indexOf('<li') < 0) {
    console.log('ABBRUCH: befundZeilen rendert keine Zeile: ' + basis.slice(0, 200));
    process.exit(2);
}
check(zusatz(basis) === '', 'ohne Zusatzangaben keine Zusatzzeile', zusatz(basis));

console.log('\n1. Zwischenrelease');
const spu = zusatz(zeile({ zwischenrelease: true }));
check(/Zwischenrelease eingeplant/.test(spu), 'offener Eintrag mit next_point_update nennt das Zwischenrelease', spu);
check(!/Zwischenrelease/.test(zusatz(zeile({ zwischenrelease: false }))), 'ohne Markierung kein Zwischenrelease-Hinweis');

console.log('\n2. In anderen Debian-Versionen behoben');
const aw = zusatz(zeile({ anderswo: [
    { version: '26.03+dfsg-1', releases: ['forky', 'sid'] },
    { version: '22.01+really26.01+dfsg-0+deb12u1', releases: ['bookworm'] }] }));
check(/in anderen Debian-Versionen behoben: forky, sid 26\.03\+dfsg-1/.test(aw),
      'Releases und Version der Behebung stehen da', aw);
check(/bookworm 22\.01\+really26\.01\+dfsg-0\+deb12u1/.test(aw), 'jede Gruppe erscheint', aw);
check(aw.indexOf('26.03') < aw.indexOf('22.01'), 'Reihenfolge wie geliefert (hoechste zuerst)', aw);
check(zusatz(zeile({ anderswo: [] })) === '', 'leere Liste -> kein Hinweis');

console.log('\n3. Art und Begruendung der Nicht-Meldung');
const ign = zusatz(zeile({ nodsa: 'Only affects Windows NTFS', nodsa_grund: 'ignored' }));
check(/Debian behebt das in dieser Version nicht: Only affects Windows NTFS/.test(ign),
      '"ignored" heisst: behebt Debian nicht – samt Begruendung', ign);
check(!/ohne Sicherheitsmeldung/.test(ign), 'und NICHT "behebt ohne Sicherheitsmeldung"', ign);
const post = zusatz(zeile({ nodsa: 'Minor issue', nodsa_grund: 'postponed' }));
check(/Behebung verschoben: Minor issue/.test(post), '"postponed" heisst verschoben', post);
const minor = zusatz(zeile({ nodsa: 'Minor issue', nodsa_grund: '' }));
check(/Debian behebt ohne Sicherheitsmeldung: Minor issue/.test(minor), 'ohne Art: ohne Sicherheitsmeldung + Text', minor);
// Gespeichertes Ergebnis von vor der Umstellung: Art stand im Textfeld.
const alt = zusatz(zeile({ nodsa: 'ignored' }));
check(/Debian behebt das in dieser Version nicht$/.test(alt) && !/: ignored/.test(alt),
      'Altbestand ("ignored" im Textfeld) wird als Art gelesen', alt);

console.log('\n4. Node.js-Laufzeit');
// Anlass (2026-10-29): nodejs aus NodeSource war ungeprueft. Seine Befunde
// stehen an der nodejs-Zeile, verlinken die Meldung von Node.js (nicht den
// Debian-Tracker, der nur Debians nodejs kennt) und tragen ihr Einzel-Update.
const nodeB = { bereich: 'node', quelle: 'nodejs', cve: 'CVE-2026-111497', klasse: 'behebbar',
                pakete: ['nodejs'], beheben_mit: ['nodejs'], aus_fremdquelle: true, fix: '24.22.1',
                einstufung: 'critical', ref: 'https://nodejs.org/en/blog/vulnerability/x' };
const nz = zeile(nodeB);
check(nz.indexOf('href="https://nodejs.org/en/blog/vulnerability/x"') >= 0
      && nz.indexOf('security-tracker.debian.org') < 0,
      'Node-Befund verlinkt die Meldung von Node.js, nicht den Debian-Tracker', nz.slice(0, 200));
check(/Paketquelle außerhalb von Debian/.test(zusatz(nz)) && !/regulären Quelle/.test(zusatz(nz)),
      'behebbar aus Fremdquelle heisst so – nicht "reguläre Quelle"', zusatz(nz));
check(/kritisch/.test(nz), 'Einstufung critical wird als kritisch gezeigt', nz);
const fremdRef = zeile(Object.assign({}, nodeB, { ref: 'javascript:alert(1)' }));
check(fremdRef.indexOf('href=') < 0, 'nur nodejs.org-Verweise werden verlinkt', fremdRef.slice(0, 160));
check(/behoben in anderen Hauptversionen: 26\.12\.1/.test(zusatz(zeile({ bereich: 'node', fix_andere: '26.12.1' }))),
      'Behebung nur in anderen Hauptversionen wird genannt');
check(api.inPaketliste(nodeB) && !api.inPaketliste(Object.assign({}, nodeB, { pakete: [] }))
      && api.inPaketliste({ bereich: 'debian' }) && !api.inPaketliste({ bereich: 'npm', pakete: ['x'] }),
      'Paketzeile: Debian und Node.js als Paket, nicht Node ohne Paket und nicht npm');
check(/data-cve-quelle="nodejs"/.test(api.einzelKnopf([nodeB])),
      'Node.js als Paket bekommt „Jetzt aktualisieren“', api.einzelKnopf([nodeB]));
check(api.einzelKnopf([Object.assign({}, nodeB, { beheben_mit: [] })]) === ''
      && api.einzelKnopf([Object.assign({}, nodeB, { pakete: [], beheben_mit: [] })]) === '',
      'ohne Zielpaket kein Knopf (Node ohne Paketverwaltung)');
// Gegenkontrolle: Debian-Knopf unveraendert.
check(/data-cve-quelle="brotli"/.test(api.einzelKnopf([{ bereich: 'debian', quelle: 'brotli', klasse: 'behebbar',
                                                          beheben_mit: ['libbrotli1'] }])),
      'Debian-Einzelknopf bleibt');

console.log('\n5. Filter "Nur noch nicht gesehene"');
// Wunsch 2026-10-29: "1 noch nicht gesehen" soll sich auch anzeigen lassen.
// "Noch nicht gesehen" heisst dasselbe wie im Zaehler: quittierbar und nicht
// quittiert.
const neu1 = { id: 'a', quittierbar: true, klasse: 'offen' };
const ges1 = { id: 'b', quittierbar: true, klasse: 'offen' };
const beh1 = { id: 'c', quittierbar: false, klasse: 'behebbar' };
const G = { b: true };
api.setze({ g: G });
check(api.paketGezeigt(undefined) && api.paketGezeigt({ befunde: [ges1] }),
      'ohne Filter: jedes Paket sichtbar');
api.setze({ u: true, g: G });
check(api.paketGezeigt({ befunde: [ges1, neu1] }), 'Filter an: Paket mit ungesehenem Befund bleibt');
check(!api.paketGezeigt({ befunde: [ges1] }), 'Filter an: alles gesehen -> Paket faellt weg');
check(!api.paketGezeigt({ befunde: [beh1] }), 'Filter an: nur Behebbares (nicht quittierbar) faellt weg');
check(!api.paketGezeigt(undefined), 'Filter an: Paket ohne Befund faellt weg');
check(JSON.stringify(api.andereGezeigt([neu1, ges1, beh1]).map(function (b) { return b.id; })) === '["a"]',
      'Befunde ohne Paketzeile: nur die ungesehenen', JSON.stringify(api.andereGezeigt([neu1, ges1, beh1])));
api.setze({ l: true, g: G });
check(api.paketGezeigt({ befunde: [ges1] }) && !api.paketGezeigt(undefined), '"Nur betroffene" unveraendert');
check(api.andereGezeigt([ges1]).length === 1, 'ohne den neuen Filter bleiben gesehene Befunde ohne Paket stehen');
api.setze({});
// Regel am Syntaxbaum: Liste und Sammelblock benutzen GENAU diese Filter.
function ruft(fn, name) {
    let ja = false;
    (function lauf(k) {
        if (!k || typeof k.type !== 'string') return;
        if (k.type === 'CallExpression' && k.callee && k.callee.name === name) ja = true;
        for (const w of Object.values(k)) {
            if (Array.isArray(w)) w.forEach(lauf);
            else if (w && typeof w.type === 'string') lauf(w);
        }
    })(acorn.parse(funktionen[fn], { ecmaVersion: 'latest' }));
    return ja;
}
check(ruft('zeichnen', 'paketGezeigt'), 'zeichnen() filtert die Paketliste ueber paketGezeigt');
check(ruft('cveBlock', 'andereGezeigt'), 'cveBlock() filtert die Befunde ohne Paket ueber andereGezeigt');
check(/id="jv-pkg-nurungesehen"/.test(funktionen.cveBlock) && /pkg\.cve_filter_neu/.test(funktionen.cveBlock),
      'cveBlock() bietet das Haekchen an');

fertig();
console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
