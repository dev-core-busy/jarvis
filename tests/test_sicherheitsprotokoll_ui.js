/* UI-Test: Sicherheitsprotokoll im Telemetrie-Reiter (jsdom, echte settings.html,
 * echte i18n.js / settings_bedienung.js / sicherheitsprotokoll.js).
 *
 * Getrieben wird ueber den ECHTEN Klappkopf (data-klick="sprot-klappen"), nicht
 * ueber einen direkten Modulaufruf – sonst bliebe eine fehlende Verdrahtung im
 * Klick-Verteiler unsichtbar.
 *
 * Gemessen werden Eigenschaften: Kettenaussage in beiden Zustaenden, Auswahl-
 * liste aus den gelieferten Arten, Markierung von Fehlschlaegen, KEIN Loesch-
 * weg, eingeschleustes HTML bleibt Text, ein Ladefehler bleibt stehen, und ein
 * Sprachwechsel zeichnet die Namen neu.
 *
 * Lauf:  timeout 60 node tests/test_sicherheitsprotokoll_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
// Absturz (uncaughtException/unhandledRejection) -> Exit 2, nicht 1: ein
// abbrechender Waechter darf nicht wie ein beissender aussehen.
require('./lib/bilanz')();

const ROOT = path.resolve(__dirname, '..');
const lies = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
let ok = 0, fail = 0;

function pruefe(bed, text, detail) {
    if (bed) { ok++; console.log('  ✓ ' + text); }
    else { fail++; console.log('  ✗ ' + text + (detail ? ' – ' + detail : '')); }
}
function abschnitt(t) { console.log('\n' + t); }
function bilanz(code) {
    console.log('\n' + '='.repeat(62));
    console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
    console.log('='.repeat(62));
    process.exit(code === undefined ? (fail ? 1 : 0) : code);
}

const wachhund = setTimeout(() => { console.log('  ✗ ABBRUCH: Wachhund nach 40 s'); bilanz(2); }, 40000);
wachhund.unref && wachhund.unref();

const HTML = lies('frontend/settings.html');
const I18N = lies('frontend/js/i18n.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const BEDIENUNG = lies('frontend/js/settings_bedienung.js');
const MODUL = lies('frontend/js/sicherheitsprotokoll.js');

const EINTRAEGE = [
    { ts: 1792505727, art: 'anmeldung_fehlgeschlagen', benutzer: '', ip: '127.0.0.1',
      ergebnis: '503', details: { weg: 'windows', grund: '<img src=x onerror="window.__xss=1">' } },
    { ts: 1792505000, art: 'anmeldung', benutzer: 'a.b', benutzer_anzeige: 'FIRMA\\a.b',
      ip: '192.0.2.7', ergebnis: 'erfolg', details: { weg: 'kennwort' } },
    { ts: 1792504000, art: 'admin_aenderung', benutzer: 'jarvis', ip: '192.0.2.8',
      ergebnis: '200', details: {} },
    // Je EIN Markierungsweg: nur ueber die Art (Ergebnis kein Status) bzw. nur
    // ueber den Status (Art an sich unauffaellig). Der erste Eintrag oben ist
    // ueber BEIDE markiert und kann deshalb keinen der Wege allein belegen.
    { ts: 1792503000, art: 'spruehangriff', benutzer: '', ip: '192.0.2.66',
      ergebnis: 'erkannt', details: { konten: 7 } },
    { ts: 1792502000, art: 'geheimnis_bestaetigung', benutzer: 'a.b', ip: '192.0.2.7',
      ergebnis: '403', details: {} },
];
const ANTWORT_OK = {
    ok: true, eintraege: EINTRAEGE,
    arten: ['admin_aenderung', 'anmeldung', 'anmeldung_fehlgeschlagen', 'neue_unbekannte_art'],
    kette: { ok: true, zeilen: 1073, brueche: [], anzahl_brueche: 0 },
    aufbewahrung_tage: 365, syslog: true, schreibfehler: { datei: 0, syslog: 0 },
};
const ANTWORT_BRUCH = Object.assign({}, ANTWORT_OK, {
    kette: { ok: false, zeilen: 1073, anzahl_brueche: 12,
             brueche: [{ zeile: 17, grund: 'Inhalt veraendert' },
                       { zeile: 18, grund: 'Kette unterbrochen' }] },
});
// Anerkannte Stelle (sicherheits_log.anerkennen). Grund und Name sind Freitext:
// "$&" und "{v}" darin pruefen, dass die Ersetzung nichts umschreibt.
const ANERKANNT = [{ zeile: 1322, zeit: '2026-10-21T15:19:42Z', art: 'abhaengigkeiten',
                     grund: 'Wartungslauf $& {v}', von: 'betreiber', am: '2026-10-29T10:00:00Z' }];
const ANTWORT_ANERKANNT = Object.assign({}, ANTWORT_OK, {
    kette: { ok: true, zeilen: 4600, brueche: [], anzahl_brueche: 0,
             anerkannt: ANERKANNT, anzahl_anerkannt: 1 },
});
const ANTWORT_BRUCH_UND_ANERKANNT = Object.assign({}, ANTWORT_OK, {
    kette: { ok: false, zeilen: 4600, anzahl_brueche: 1,
             brueche: [{ zeile: 17, grund: 'Inhalt veraendert' }],
             anerkannt: ANERKANNT, anzahl_anerkannt: 1 },
});

function baue(antwort, status) {
    const dom = new JSDOM(HTML, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    w.fetch = (url, o) => {
        rufe.push({ url: String(url), methode: (o && o.method) || 'GET' });
        const pfad = String(url).split('?')[0];
        if (pfad !== '/api/security/log') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        const s = status || 200;
        return Promise.resolve({ ok: s < 400, status: s, json: () => Promise.resolve(antwort) });
    };
    w.authToken = 'T';
    w.eval(SITZUNG);
    w.eval(I18N);
    w.eval(BEDIENUNG);
    w.eval(MODUL);
    return { w, d: w.document, rufe };
}

const warte = (ms) => new Promise((r) => setTimeout(r, ms || 60));

(async () => {
    abschnitt('0. Positivkontrolle: Abschnitt und Verdrahtung');
    let { w, d, rufe } = baue(ANTWORT_OK);
    const kopf = d.querySelector('[data-klick="sprot-klappen"]');
    const rumpf = d.getElementById('sprot-section-body');
    pruefe(!!kopf && !!rumpf, 'Abschnitt steht in der echten settings.html');
    if (!kopf || !rumpf) bilanz(2);
    pruefe(!!kopf.closest('#settings-tab-telemetry'), 'liegt im Telemetrie-Reiter');
    pruefe(/\/static\/js\/sicherheitsprotokoll\.js\?v=\d+/.test(HTML), 'Modul ist in settings.html eingebunden');
    pruefe(rumpf.style.display === 'none', 'zu Beginn zugeklappt');
    kopf.click();
    await warte(80);
    pruefe(rumpf.style.display !== 'none', 'Klick auf den Kopf klappt auf');
    // Klappt er nicht auf, ist alles Weitere nicht messbar – geordnet mit Bilanz
    // enden (Exit 1 = Befund), statt in einem Folgefehler abzustuerzen (der
    // ergaebe Exit 2 und saehe aus wie "konnte nicht laufen").
    if (rumpf.style.display === 'none') bilanz(1);
    const ruf = rufe.find((r) => r.url.startsWith('/api/security/log'));
    pruefe(!!ruf && /limit=200/.test(ruf.url) && ruf.methode === 'GET', 'laedt GET /api/security/log?limit=200', ruf && ruf.url);

    abschnitt('1. Kette und Tabelle');
    const kette = d.getElementById('sprot-kette');
    pruefe(kette.classList.contains('sprot-kette-ok') && /1073/.test(kette.textContent),
           'intakte Kette wird mit Zeilenzahl genannt', kette.textContent);
    pruefe(/365/.test(kette.textContent), 'Aufbewahrungsfrist steht dabei');
    const zeilen = d.querySelectorAll('#sprot-tbody tr');
    pruefe(zeilen.length === 5, 'fuenf Zeilen', String(zeilen.length));
    pruefe(zeilen[0].textContent.includes('Anmeldung fehlgeschlagen'), 'Art mit lesbarem Namen (DE)');
    pruefe(zeilen[1].textContent.includes('FIRMA\\a.b'), 'Benutzer mit Anzeigenamen');
    pruefe(d.querySelector('#sprot-tbody .sprot-art-warn') && zeilen[0].classList.contains('sprot-zeile-warn'),
           'Fehlschlag ist markiert');
    pruefe(zeilen[1].querySelector('.sprot-art-ok') && !zeilen[1].classList.contains('sprot-zeile-warn'),
           'erfolgreiche Anmeldung ist NICHT als Fehlschlag markiert');
    pruefe(zeilen[3].classList.contains('sprot-zeile-warn'), 'markiert allein ueber die Art (Sprühangriff)');
    pruefe(zeilen[4].classList.contains('sprot-zeile-warn'), 'markiert allein ueber den Status (403)');
    pruefe(!zeilen[2].classList.contains('sprot-zeile-warn'), 'Status 200 ist keine Markierung');
    // Eingeschleustes HTML aus einem Fremdfeld bleibt Text
    pruefe(!d.querySelector('#sprot-tbody img') && !w.__xss, 'HTML in den Details wird NICHT ausgefuehrt');
    pruefe(zeilen[0].textContent.includes('<img src=x'), 'und steht als lesbarer Text da');
    pruefe(/5 Einträge/.test(d.getElementById('sprot-count').textContent), 'Trefferzahl');

    abschnitt('2. Auswahlliste');
    const sel = d.getElementById('sprot-filter-art');
    const werte = Array.from(sel.options).map((o) => o.value);
    pruefe(werte[0] === '' && werte.length === 5, 'Alle + vier gelieferte Arten', werte.join(','));
    pruefe(Array.from(sel.options).some((o) => o.value === 'admin_aenderung' && o.textContent === 'Änderung durch Administrator'),
           'Optionen tragen lesbare Namen');
    pruefe(Array.from(sel.options).some((o) => o.value === 'neue_unbekannte_art' && o.textContent === 'neue_unbekannte_art'),
           'unbekannte Art erscheint mit ihrem Schluessel statt zu fehlen');
    sel.value = 'anmeldung';
    sel.dispatchEvent(new w.Event('change'));
    await warte(80);
    const letzter = rufe.filter((r) => r.url.startsWith('/api/security/log')).pop();
    pruefe(/art=anmeldung(&|$)/.test(letzter.url), 'Auswahl laedt gefiltert', letzter.url);
    pruefe(sel.value === 'anmeldung', 'Auswahl bleibt nach dem Neuzeichnen stehen');

    abschnitt('3. Kein Loeschweg');
    const sektion = kopf.closest('.sk-openclaw-section');
    pruefe(!sektion.querySelector('.jv-ico-trash, .is-danger'), 'kein Muelleimer / kein Gefahrenknopf im Abschnitt');
    pruefe(!rufe.some((r) => r.url.startsWith('/api/security/log') && r.methode !== 'GET'), 'nur GET-Aufrufe');

    abschnitt('4. Filter-Hinweis');
    const nutzer = d.getElementById('sprot-filter-user');
    nutzer.value = 'mueller';
    nutzer.dispatchEvent(new w.Event('input'));
    pruefe(/Anwenden/.test(d.getElementById('sprot-count').textContent),
           'geaenderter, nicht angewandter Filter wird angezeigt');

    abschnitt('5. Sprachwechsel');
    w._lang = 'en';
    d.dispatchEvent(new w.Event('jarvis-lang-changed'));
    await warte(30);
    pruefe(d.querySelector('#sprot-tbody tr').textContent.includes('Sign-in failed'), 'Arten auf Englisch neu gezeichnet');
    pruefe(/intact/.test(d.getElementById('sprot-kette').textContent), 'Kettenaussage auf Englisch');
    w.close();

    abschnitt('6. Gebrochene Kette');
    ({ w, d, rufe } = baue(ANTWORT_BRUCH));
    d.querySelector('[data-klick="sprot-klappen"]').click();
    await warte(80);
    const k2 = d.getElementById('sprot-kette');
    pruefe(k2.classList.contains('sprot-kette-bruch'), 'Bruch wird hervorgehoben');
    pruefe(/12 Stelle/.test(k2.textContent), 'Anzahl der Brueche genannt', k2.textContent);
    pruefe(/Zeile 17: Inhalt verändert/.test(k2.textContent), 'Grund lesbar (mit Umlaut) und Zeile genannt');
    pruefe(/10 weitere/.test(k2.textContent), 'nicht gelieferte Brueche werden beziffert');
    w.close();

    abschnitt('6b. Anerkannte Stelle');
    ({ w, d, rufe } = baue(ANTWORT_ANERKANNT));
    d.querySelector('[data-klick="sprot-klappen"]').click();
    await warte(80);
    const k3 = d.getElementById('sprot-kette');
    pruefe(k3.classList.contains('sprot-kette-ok'), 'anerkannte Stelle: Kette gilt als intakt');
    pruefe(/geklärt und anerkannt/.test(k3.textContent) && /4600/.test(k3.textContent),
           'Kopfzeile nennt die geklaerte Stelle statt nur "intakt"', k3.textContent);
    const la = k3.querySelectorAll('.sprot-anerkannt li');
    const ta = la.length ? la[0].textContent : '';
    pruefe(la.length === 1, 'eine Zeile je anerkannter Stelle', String(la.length));
    pruefe(/Zeile 1322/.test(ta) && ta.includes('Abhängigkeiten geändert') && ta.includes('betreiber'),
           'Zeile, Art (lesbar) und Bearbeiter genannt', ta);
    pruefe(ta.includes('Wartungslauf $& {v}'), 'Grund bleibt woertlich ($& und {v} unveraendert)', ta);
    // der Grund traegt "{v}" absichtlich – ohne ihn darf kein Platzhalter bleiben
    pruefe(!/\{[ztegvd]\}/.test(ta.replace('Wartungslauf $& {v}', '')), 'kein Platzhalter bleibt stehen', ta);
    w.close();
    ({ w, d, rufe } = baue(ANTWORT_BRUCH_UND_ANERKANNT));
    d.querySelector('[data-klick="sprot-klappen"]').click();
    await warte(80);
    const k4 = d.getElementById('sprot-kette');
    pruefe(k4.classList.contains('sprot-kette-bruch') && /Zeile 17/.test(k4.textContent),
           'echter Bruch bleibt hervorgehoben');
    pruefe(k4.querySelectorAll('.sprot-anerkannt li').length === 1,
           'und die anerkannte Stelle steht trotzdem da');
    w.close();
    ({ w, d, rufe } = baue(ANTWORT_OK));
    d.querySelector('[data-klick="sprot-klappen"]').click();
    await warte(80);
    pruefe(!d.querySelector('#sprot-kette .sprot-anerkannt') && !/anerkannt/.test(d.getElementById('sprot-kette').textContent),
           'ohne Anerkennung keine Anerkennungs-Zeile');
    w.close();

    abschnitt('7. Ladefehler bleibt stehen');
    ({ w, d, rufe } = baue({}, 500));
    d.querySelector('[data-klick="sprot-klappen"]').click();
    await warte(80);
    const f = d.getElementById('sprot-fehler');
    pruefe(f.style.display !== 'none' && /HTTP 500/.test(f.textContent), 'Fehler mit Status sichtbar', f.textContent);
    await warte(4500);
    pruefe(f.style.display !== 'none', 'Fehler verschwindet nicht von selbst');
    w.close();

    abschnitt('8. i18n: jeder Schluessel in DE und EN');
    const schl = new Set();
    const sekHtml = HTML.split('data-klick="sprot-klappen"')[1].split('<!-- ──')[0];
    (sekHtml.match(/data-i18n(?:-html|-title|-placeholder)?="([^"]+)"/g) || [])
        .forEach((m) => schl.add(m.split('"')[1]));
    // Praefixe ('sprot.art.' + art) sind keine Schluessel – die vollstaendigen
    // prueft der Block darunter (Arten) bzw. die Gruende-Tabelle im Modul.
    (MODUL.match(/T\('([a-z_.]+)'/g) || []).map((m) => m.slice(3, -1))
        .filter((k) => !k.endsWith('.')).forEach((k) => schl.add(k));
    (MODUL.match(/:\s*'([a-z_]+)'/g) || []).map((m) => m.split("'")[1])
        .filter((g) => /^(kein_json|unterbrochen|inhalt|ohne_schluessel|schluessel_fehlt|letzte)$/.test(g))
        .forEach((g) => schl.add('telemetry.sprot_grund.' + g));
    const fehlt = [];
    schl.forEach((k) => {
        const n = I18N.split("'" + k + "'").length - 1;
        if (n < 2) fehlt.push(k + ' (' + n + 'x)');
    });
    pruefe(schl.size > 10, 'Positivkontrolle: Schluessel gefunden (' + schl.size + ')');
    pruefe(!fehlt.length, 'alle in DE und EN', fehlt.join(', '));
    const arten = (lies('backend/main.py') + lies('backend/abhaengigkeiten.py') + lies('backend/file_watcher.py'))
        .match(/(?:ereignis|_melden)\(\s*"([a-z_]+)"/g) || [];
    const ohne = arten.map((m) => m.split('"')[1])
        .filter((a) => I18N.split("'sprot.art." + a + "'").length - 1 < 2);
    pruefe(arten.length > 8, 'Positivkontrolle: geschriebene Ereignisarten gefunden (' + arten.length + ')');
    pruefe(!ohne.length, 'jede geschriebene Ereignisart hat einen Namen in DE und EN', [...new Set(ohne)].join(', '));

    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
