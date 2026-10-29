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

const NOETIG = ['esc', 'klasseText', 'einstufungText', 'trackerLink', 'nodsaText', 'anderswoText', 'befundZeilen'];
const fehlt = NOETIG.filter(function (n) { return !funktionen[n]; });
if (fehlt.length || !rang) {
    console.log('ABBRUCH: nicht gefunden: ' + fehlt.concat(rang ? [] : ['CVE_RANG']).join(', '));
    process.exit(2);
}
// T liefert die deutsche Vorgabe; "gesehen" ist leer.
const prolog = 'function T(k, d) { return d; }\nfunction cveGesehen() { return {}; }\nvar CVE_RANG = ' + rang + ';\n';
const api = new Function(prolog + NOETIG.map(function (n) { return funktionen[n]; }).join('\n')
    + '\nreturn { befundZeilen: befundZeilen };')();

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

fertig();
console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
