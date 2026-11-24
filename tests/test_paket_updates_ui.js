/* UI-Test: Paket-Updates und AIDE-Abgleich (jsdom, Ausschnitt der echten
 * settings.html, echte i18n.js / icons.js / security_incidents.js).
 *
 * Getrieben ueber den ECHTEN Einstieg des Reiters (SecurityIncidents.onShowUnattended),
 * gefragt wird GET /api/security/updates (Attrappe mit der Antwortform aus main.py).
 *
 * Gemessen werden Eigenschaften:
 *   1. Liste: jedes Paket mit alter/neuer Fassung, Sicherheitsquelle markiert,
 *      "Alle einspielen" nur aktiv, wenn etwas offen ist.
 *   2. Neustart: ein Knopf NUR fuer neustartbare Dienste, mit dem Dienstnamen;
 *      der Klick schickt genau diesen Namen per POST.
 *   3. AIDE offen: Liste mit Grund, Knopf "uebernehmen" sichtbar und mit DER
 *      Kennung, die der Server geliefert hat; der Klick schickt sie.
 *      AIDE uebernommen: kein Knopf.
 *   4. Pfade aus dem Bericht bleiben TEXT (eingeschleustes HTML wirkt nicht).
 *   5. Ein Ladefehler bleibt als Meldung stehen, "Alle einspielen" ist dann aus.
 *
 * Lauf:  timeout 60 node tests/test_paket_updates_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
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
const wachhund = require('./lib/wachhund')(() => { console.log('  ✗ ABBRUCH: Wachhund nach 40 s'); bilanz(2); }, 40000);
wachhund.unref && wachhund.unref();

// Gegenprobe (tests/gegen_paket_updates_ui.py) kann eine sabotierte KOPIE unterschieben
const HTML = process.env.JARVIS_SETTINGS_PRUEFLING ? fs.readFileSync(process.env.JARVIS_SETTINGS_PRUEFLING, 'utf8')
                                                   : lies('frontend/settings.html');
const { ausschnitt } = require('./lib/seite_ausschnitt');
const AUSSCHNITT = ausschnitt(HTML, ['prof-sect-pakete-body'], {});
pruefe(AUSSCHNITT.fehlend.length === 0, 'Ausschnitt: Container #prof-sect-pakete-body in der echten settings.html (Positivkontrolle)',
       AUSSCHNITT.fehlend.join(', '));
if (AUSSCHNITT.fehlend.length) bilanz(2);

// Lage (2026-11-24, Wunsch des Betreibers): eigener Container "Paket-Updates und
// Integritaet" in KI & System, zwischen System-Einstellungen und Agent API Key,
// mit den drei Gruppen darin - gemessen an der ECHTEN Seite, nicht am Ausschnitt.
{
    const echt = new JSDOM(HTML).window.document;
    const reiter = echt.getElementById('settings-tab-profiles');
    const kopf = (id) => { const h = echt.getElementById(id); return h ? h.closest('.kb-section') : null; };
    const tuning = kopf('prof-sect-tuning-hdr'), pakete = kopf('prof-sect-pakete-hdr'), api = kopf('prof-sect-api-hdr');
    pruefe(!!pakete && !!reiter && reiter.contains(pakete), 'Container steht im Reiter KI & System');
    const sektionen = reiter ? Array.from(reiter.querySelectorAll('.kb-section')) : [];
    const i = (x) => sektionen.indexOf(x);
    pruefe(!!tuning && !!api && i(pakete) === i(tuning) + 1 && i(api) === i(pakete) + 1,
           'Container liegt direkt zwischen System-Einstellungen und Agent API Key', [i(tuning), i(pakete), i(api)].join(','));
    const titel = pakete ? pakete.querySelector('.kb-section-header h3') : null;
    pruefe(!!titel && titel.getAttribute('data-i18n') === 'profile.section_pakete'
           && titel.textContent.trim() === 'Paket-Updates und Integrität', 'Titel "Paket-Updates und Integrität" mit i18n-Schluessel');
    const body = echt.getElementById('prof-sect-pakete-body');
    const gruppen = body ? Array.from(body.querySelectorAll(':scope > .tuning-group h4')).map((h) => h.getAttribute('data-i18n')) : [];
    pruefe(gruppen.join(',') === 'security.section_unattended,security.section_updates,security.section_aide',
           'drei Gruppen in dieser Reihenfolge: Sicherheitsupdates, Paket-Updates, Integritaetspruefung', gruppen.join(','));
    const sys = echt.getElementById('prof-sect-tuning-body');
    pruefe(!!sys && !['sec-unatt-status', 'sec-upd-einspielen', 'sec-aide-status'].some((id) => sys.contains(echt.getElementById(id))),
           'nichts davon steht mehr in den System-Einstellungen');
    const appJs = lies('frontend/js/app.js');
    pruefe(/hdr:\s*'prof-sect-pakete-hdr',\s*body:\s*'prof-sect-pakete-body'/.test(appJs),
           'app.js klappt den Container ueber _collapseInit (gemerkter Zustand wie die anderen)');
}
pruefe(/\/static\/js\/security_incidents\.js\?v=\d+/.test(HTML), 'security_incidents.js ist in settings.html eingebunden');

const KENNUNG = 'a1b2c3d4e5f60718';
function antwort(aide) {
    return {
        ok: true, fehler: '', index_alter: 1795480000,
        pakete: [
            { name: 'libssl3t64', von: '3.5.7-1~deb13u3', nach: '3.5.9-1~deb13u1', quelle: 'Debian:13.8/stable, Debian-Security:13/stable-security', sicherheit: true },
            { name: 'base-files', von: '13.8+deb13u7', nach: '13.8+deb13u8', quelle: 'Debian:13.8/stable', sicherheit: false },
        ],
        entfernt: [], zurueckgehalten: ['linux-image-amd64'],
        neustart: { verfuegbar: true, kernel_neustart: true, kernel_aktuell: '6.12.117', kernel_neu: '6.12.118',
                    dienste: [{ name: 'cron.service', neustartbar: true, grund: '' },
                              { name: 'dbus.service', neustartbar: false, grund: 'nur mit einem Neustart des Servers' }] },
        server_neustart: false,
        aide: aide,
    };
}
const AIDE_OFFEN = { eingerichtet: true, laeuft: '', naechste_pruefung: 1795574191, db: true,
    zustand: { zustand: 'offen', zeit: 1795484000, offen_anzahl: 2, kennung: KENNUNG,
               erklaert: { Paket: 120, 'Verzeichnisinhalt': 8 }, quelle: '94acc89dfbce',
               offen: [{ art: 'geaendert', attrs: 'f >b... mc..H.. .', pfad: '/usr/bin/<img src=x onerror="window.__xss=1">', warum: 'Inhalt weicht von Paket foo ab' },
                       { art: 'neu', attrs: 'f+++', pfad: '/usr/local/bin/fremd', warum: 'gehoert keinem Paket' }] } };
const AIDE_GUT = { eingerichtet: true, laeuft: '', db: true,
    zustand: { zustand: 'uebernommen', zeit: 1795484000, offen_anzahl: 0, uebernommen_von: 'automatisch', erklaert: { Paket: 3 } } };

function baue(daten, status) {
    const dom = new JSDOM(AUSSCHNITT.html, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    w.fetch = (url, o) => {
        const pfad = String(url).split('?')[0];
        rufe.push({ pfad: pfad, methode: (o && o.method) || 'GET', rumpf: o && o.body });
        if (pfad === '/api/security/updates') {
            const s = status || 200;
            return Promise.resolve({ ok: s < 400, status: s, json: () => Promise.resolve(daten) });
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    };
    w.confirm = () => true;
    w.authToken = 'T';
    w.eval(lies('frontend/js/sitzung.js'));
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(lies('frontend/js/icons.js'));
    // Gegenprobe (tests/gegen_paket_updates_ui.py) laedt eine sabotierte KOPIE
    w.eval(process.env.JARVIS_SECINC_PRUEFLING ? fs.readFileSync(process.env.JARVIS_SECINC_PRUEFLING, 'utf8')
                                               : lies('frontend/js/security_incidents.js'));
    return { w, d: w.document, rufe };
}
const warte = (ms) => new Promise((r) => setTimeout(r, ms || 80));

(async () => {
    abschnitt('1. Liste der offenen Updates');
    let { w, d, rufe } = baue(antwort(AIDE_OFFEN));
    pruefe(!!w.SecurityIncidents && typeof w.SecurityIncidents.onShowUnattended === 'function',
           'Modul geladen, Einstieg des Reiters vorhanden (Positivkontrolle)');
    if (!w.SecurityIncidents) bilanz(2);
    w.SecurityIncidents.onShowUnattended();
    await warte();
    pruefe(rufe.some((r) => r.pfad === '/api/security/updates' && r.methode === 'GET'), 'laedt GET /api/security/updates');
    const liste = d.getElementById('sec-upd-liste').textContent;
    pruefe(/libssl3t64/.test(liste) && /3\.5\.7-1~deb13u3/.test(liste) && /3\.5\.9-1~deb13u1/.test(liste),
           'Paket mit alter und neuer Fassung gelistet');
    pruefe(/base-files/.test(liste), 'auch das Paket der Punktausgabe');
    pruefe(/Sicherheit/.test(liste), 'Sicherheitsquelle markiert');
    pruefe(/linux-image-amd64/.test(liste), 'zurueckgehaltene Pakete genannt');
    pruefe(/2 offene Updates/.test(d.getElementById('sec-upd-status').textContent), 'Kopf nennt die Zahl');
    pruefe(!d.getElementById('sec-upd-einspielen').disabled, '"Alle einspielen" aktiv, wenn etwas offen ist');

    abschnitt('2. Dienste mit altem Programmstand');
    const ns = d.getElementById('sec-upd-neustart');
    const knoepfe = Array.from(ns.querySelectorAll('button[data-dienst]'));
    pruefe(knoepfe.length === 1 && knoepfe[0].getAttribute('data-dienst') === 'cron.service',
           'genau EIN Neustart-Knopf, nur fuer den neustartbaren Dienst', knoepfe.map((b) => b.getAttribute('data-dienst')).join(','));
    pruefe(/dbus\.service/.test(ns.textContent) && /Neustart des Servers/.test(ns.textContent),
           'gesperrter Dienst steht da, mit dem Grund statt eines Knopfs');
    pruefe(/6\.12\.118/.test(ns.textContent), 'neuer Kernel wird genannt');
    knoepfe[0] && knoepfe[0].click();
    await warte();
    const nsRuf = rufe.find((r) => r.pfad === '/api/security/updates/neustart');
    pruefe(nsRuf && nsRuf.methode === 'POST' && JSON.parse(nsRuf.rumpf || '{}').dienst === 'cron.service',
           'Klick schickt POST mit genau diesem Dienst', nsRuf && nsRuf.rumpf);

    abschnitt('3. AIDE: offener Abgleich');
    const ue = d.getElementById('sec-aide-uebernehmen');
    pruefe(ue.style.display !== 'none', 'Knopf "uebernehmen" sichtbar');
    pruefe(ue.getAttribute('data-kennung') === KENNUNG, 'Knopf traegt die gelieferte Kennung');
    const al = d.getElementById('sec-aide-liste');
    pruefe(/Inhalt weicht von Paket foo ab/.test(al.textContent) && /\/usr\/local\/bin\/fremd/.test(al.textContent),
           'Liste nennt Pfad und Grund');
    pruefe(/2 Änderungen nicht erklärt/.test(d.getElementById('sec-aide-status').textContent), 'Kopf nennt die Zahl');

    abschnitt('4. Eingeschleustes HTML bleibt Text');
    pruefe(!al.querySelector('img') && w.__xss === undefined, 'Pfad aus dem Bericht erzeugt kein Element');
    ue.click();
    await warte();
    const ueRuf = rufe.find((r) => r.pfad === '/api/security/aide/uebernehmen');
    pruefe(ueRuf && JSON.parse(ueRuf.rumpf || '{}').kennung === KENNUNG, 'Klick schickt die gesehene Kennung', ueRuf && ueRuf.rumpf);

    abschnitt('3a. Wechsel offen -> uebernommen im SELBEN Dokument (Weg nach dem Klick)');
    w.SecurityIncidents.renderAide(AIDE_GUT);
    pruefe(d.getElementById('sec-aide-uebernehmen').style.display === 'none',
           'nach der Uebernahme verschwindet der Knopf wieder');
    pruefe(d.getElementById('sec-aide-liste').textContent === '', 'und die Liste der offenen Eintraege');

    abschnitt('3b. AIDE: uebernommen');
    ({ w, d, rufe } = baue(antwort(AIDE_GUT)));
    w.SecurityIncidents.onShowUnattended();
    await warte();
    pruefe(d.getElementById('sec-aide-uebernehmen').style.display === 'none', 'uebernommen: kein Knopf');
    pruefe(/neuer Vergleichsstand übernommen/.test(d.getElementById('sec-aide-status').textContent), 'uebernommen: Zustand genannt');

    abschnitt('4b. Nichts offen');
    ({ w, d, rufe } = baue(Object.assign(antwort(AIDE_GUT), { pakete: [], zurueckgehalten: [] })));
    w.SecurityIncidents.onShowUnattended();
    await warte();
    pruefe(d.getElementById('sec-upd-einspielen').disabled, 'nichts offen: "Alle einspielen" ist aus');
    pruefe(/Keine offenen Updates/.test(d.getElementById('sec-upd-status').textContent), 'nichts offen: so benannt');

    abschnitt('5. Ladefehler');
    ({ w, d, rufe } = baue({ ok: false, fehler: 'Broker nicht erreichbar' }, 502));
    w.SecurityIncidents.onShowUnattended();
    await warte();
    pruefe(/nicht ermittelbar/.test(d.getElementById('sec-upd-status').textContent), 'Fehler bleibt als Meldung stehen');
    pruefe(d.getElementById('sec-upd-einspielen').disabled, '"Alle einspielen" ist dann aus');

    w.close();
    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
