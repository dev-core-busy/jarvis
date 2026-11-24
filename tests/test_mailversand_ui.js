/* UI-Test: E-Mail-Versand (jsdom, Ausschnitt der echten settings.html, echte
 * sitzung.js / i18n.js / mailversand.js).
 *
 * Getrieben ueber den echten Einstieg (MailVersand.onShow), gefragt wird
 * GET /api/broker/mailversand/status (Attrappe mit der Antwortform von
 * mail_meldung.status()).
 *
 * Gemessen:
 *   0. Lage: Container im Reiter KI & System, app.js klappt und ruft ihn auf,
 *      Skript eingebunden, i18n-Schluessel in DE/EN.
 *   1. Status fuellt Felder und Haken; "Testnachricht" nur mit Empfaenger.
 *   2. Ohne Postfix: Hinweis und Knopf "einrichten" sichtbar.
 *   3. KEIN Freigabe-Code (Betreiberentscheid 2026-11-24): weder beim Speichern
 *      noch beim Einrichten; Absender, Name und Betreff gehen mit, die Vorgaben
 *      stehen als Platzhalter.
 *   4. Ein Fehler des Servers bleibt als Meldung am Knopf stehen.
 *   5. Werte vom Server bleiben TEXT (eingeschleustes HTML wirkt nicht).
 *
 * Lauf:  timeout 60 node tests/test_mailversand_ui.js
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

const HTML = lies('frontend/settings.html');
const MV_JS = process.env.JARVIS_MV_PRUEFLING ? fs.readFileSync(process.env.JARVIS_MV_PRUEFLING, 'utf8')
                                              : lies('frontend/js/mailversand.js');
const { ausschnitt } = require('./lib/seite_ausschnitt');
const AUSSCHNITT = ausschnitt(HTML, ['prof-sect-mail-body'], {});
pruefe(AUSSCHNITT.fehlend.length === 0, 'Ausschnitt: #prof-sect-mail-body in der echten settings.html (Positivkontrolle)',
       AUSSCHNITT.fehlend.join(', '));
if (AUSSCHNITT.fehlend.length) bilanz(2);

abschnitt('0. Lage und Einbindung');
{
    const echt = new JSDOM(HTML).window.document;
    const reiter = echt.getElementById('settings-tab-profiles');
    const kopf = echt.getElementById('prof-sect-mail-hdr');
    pruefe(!!reiter && !!kopf && reiter.contains(kopf), 'Container steht im Reiter KI & System');
    const quellen = Array.from(echt.querySelectorAll('#mv-quellen input[data-quelle]')).map((x) => x.getAttribute('data-quelle'));
    pruefe(quellen.join(',') === 'ueberwachung,aide,sicherheit,system', 'vier Meldungsarten als Haken', quellen.join(','));
    const appJs = lies('frontend/js/app.js');
    pruefe(/hdr:\s*'prof-sect-mail-hdr',\s*body:\s*'prof-sect-mail-body'/.test(appJs), 'app.js klappt den Container ueber _collapseInit');
    pruefe((appJs.match(/window\.MailVersand\.onShow\(\)/g) || []).length === 2, 'app.js ruft onShow an beiden Einstiegen des Reiters');
    pruefe(/\/static\/js\/mailversand\.js\?v=\d+/.test(HTML), 'mailversand.js ist in settings.html eingebunden');
    const i18n = lies('frontend/js/i18n.js');
    const schl = Array.from(new Set((HTML.match(/data-i18n(?:-placeholder)?="(mv\.[a-z_]+)"/g) || [])
        .map((m) => m.replace(/.*="/, '').replace('"', ''))));
    const fehlt = schl.filter((k) => (i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length !== 2);
    pruefe(schl.length >= 10 && !fehlt.length, 'jeder mv.-Schluessel des Markups steht in DE und EN (' + schl.length + ')', fehlt.join(', '));
}

const STATUS = {
    ok: true, installiert: true, aktiv: true, konfig_aktuell: true, lauscht: [], warteschlange: { anzahl: 0, grund: '' },
    empfaenger: ['a@beispiel.de'], relay: 'mail.beispiel.de:25', quellen: ['ueberwachung', 'aide'],
    alle_quellen: ['ueberwachung', 'aide', 'sicherheit', 'system'],
    absender: 'meldung@beispiel.de', absender_name: '', betreff: '', sprache: 'de',
    vorgabe: { absender: 'jarvis@probe.beispiel.de', absender_name: 'Jarvis {server}', betreff: '[Jarvis {server}]' },
    letzte: [{ zeit: 1795480000, quelle: 'aide', betreff: '<img src=x onerror="window.__xss=1">', ok: true, fehler: '' }],
    server: 'probe.beispiel.de',
};

function baue(status, postAntwort) {
    const dom = new JSDOM(AUSSCHNITT.html, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    let codes = 0;
    // Der Server-Stand wie beim echten Broker: eine ANGENOMMENE Aenderung der
    // Sprache steht danach im Status (sonst zoege die Oberflaeche zu Recht
    // erneut nach, und die Pruefung mass die Attrappe statt das Verhalten).
    const stand = Object.assign({}, status);
    w.fetch = (url, o) => {
        const pfad = String(url).split('?')[0];
        const rumpf = o && o.body ? JSON.parse(o.body) : null;
        rufe.push({ pfad: pfad, methode: (o && o.method) || 'GET', rumpf: rumpf });
        const antwort = postAntwort || { ok: true, meldung: '' };
        if (rumpf && rumpf.sprache && antwort.ok && ['sprache', 'speichern'].indexOf(rumpf.aktion) >= 0) stand.sprache = rumpf.sprache;
        const daten = pfad === '/api/broker/mailversand/status' ? Object.assign({}, stand) : antwort;
        // Antwort erst im naechsten Zeitgeber-Takt, wie ein echtes Netz: eine
        // Schleife aus Nachziehen und Neuladen haelt sonst als Mikrotask-Kette
        // jeden Zeitgeber an – der Waechter hinge, statt sie als FAIL zu melden.
        return new Promise((res) => setTimeout(() => res({ ok: true, status: 200, json: () => Promise.resolve(daten) }), 0));
    };
    w.confirm = () => true;
    w.authToken = 'T';
    w.eval(lies('frontend/js/sitzung.js'));
    // i18n.js und i18n_fr.js in EINEM Aufruf (wie tests/test_i18n_fr.js): die
    // FR-Datei haengt sich an die const _I18N, die ein zweiter eval nicht sieht.
    // Ohne FR ignoriert setLang('fr') den Wechsel.
    w.eval(lies('frontend/js/i18n.js') + '\n' + lies('frontend/js/i18n_fr.js'));
    // ECHTES tabfill.js: die Vorgaben muessen per TAB uebernehmbar sein
    w.eval(lies('frontend/js/tabfill.js'));
    w.Fernzugang = { _code: () => { codes++; return '123456'; }, _codeText: (g) => 'CODE:' + g };
    w.eval(MV_JS);
    return { w, d: w.document, rufe, codes: () => codes };
}
const warte = (ms) => new Promise((r) => setTimeout(r, ms || 60));

(async () => {
    abschnitt('1. Status fuellt die Felder');
    let { w, d, rufe, codes } = baue(STATUS);
    pruefe(!!w.MailVersand && typeof w.MailVersand.onShow === 'function', 'window.MailVersand.onShow existiert');
    w.MailVersand.onShow();
    await warte();
    pruefe(d.getElementById('mv-empfaenger').value === 'a@beispiel.de', 'Empfaenger eingetragen');
    pruefe(d.getElementById('mv-relay').value === 'mail.beispiel.de:25', 'Relay eingetragen');
    const an = Array.from(d.querySelectorAll('#mv-quellen input:checked')).map((x) => x.getAttribute('data-quelle'));
    pruefe(an.join(',') === 'ueberwachung,aide', 'Haken nach Server-Stand', an.join(','));
    pruefe(/a@beispiel\.de/.test(d.getElementById('mv-status').textContent), 'Statuszeile nennt den Empfaenger');
    pruefe(!d.getElementById('mv-test').disabled, 'Testnachricht moeglich');
    pruefe(d.getElementById('mv-einrichten').style.display === 'none', 'kein Einrichten-Knopf, wenn installiert');
    pruefe(!w.__xss && !d.querySelector('#mv-letzte img') && /onerror/.test(d.getElementById('mv-letzte').textContent),
           'Betreff aus "Zuletzt verschickt" bleibt Text');

    abschnitt('2. Ohne Postfix bzw. ohne Empfaenger');
    ({ w, d } = baue(Object.assign({}, STATUS, { installiert: false, aktiv: false })));
    w.MailVersand.onShow(); await warte();
    pruefe(d.getElementById('mv-einrichten').style.display === '', 'Einrichten-Knopf sichtbar');
    pruefe(d.getElementById('mv-test').disabled, 'Testnachricht aus');
    pruefe(/kein Mailserver/.test(d.getElementById('mv-status').textContent), 'Status sagt: kein Mailserver');
    ({ w, d } = baue(Object.assign({}, STATUS, { empfaenger: [] })));
    w.MailVersand.onShow(); await warte();
    pruefe(d.getElementById('mv-test').disabled, 'ohne Empfaenger keine Testnachricht');
    ({ w, d } = baue(Object.assign({}, STATUS, { lauscht: ['0.0.0.0:25'] })));
    w.MailVersand.onShow(); await warte();
    pruefe(/0\.0\.0\.0:25/.test(d.getElementById('mv-status').textContent), 'ein lauschender Mailserver wird gemeldet');

    abschnitt('3. Speichern ohne Freigabe-Code, mit Absender und Betreff');
    ({ w, d, rufe, codes } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    pruefe(d.getElementById('mv-absender').value === 'meldung@beispiel.de'
           && d.getElementById('mv-absender-name').value === ''
           && d.getElementById('mv-absender-name').getAttribute('placeholder') === 'Jarvis {server}',
           'Absender gefuellt, leerer Name zeigt die Vorgabe als Platzhalter');
    pruefe(d.getElementById('mv-betreff').getAttribute('placeholder') === '[Jarvis {server}]', 'Betreff-Vorgabe als Platzhalter');
    // Gemeldet 2026-11-24: TAB uebernahm die Vorgabe nicht. Gemessen wird die
    // WIRKUNG am echten tabfill.js, nicht das Attribut allein.
    for (const [id, soll] of [['mv-absender-name', 'Jarvis {server}'], ['mv-betreff', '[Jarvis {server}]']]) {
        const el = d.getElementById(id);
        el.value = '';
        el.focus();
        const ev = new w.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
        el.dispatchEvent(ev);
        pruefe(el.value === soll && ev.defaultPrevented, 'TAB im leeren Feld ' + id + ' uebernimmt die Vorgabe', JSON.stringify(el.value));
    }
    pruefe(d.getElementById('mv-absender').hasAttribute('data-tabfill'), 'auch die Absenderadresse ist per TAB uebernehmbar');
    d.getElementById('mv-absender-name').value = '';
    d.getElementById('mv-betreff').value = '';
    let konfirm = 0, prompts = 0;
    w.confirm = () => { konfirm++; return true; };
    w.prompt = () => { prompts++; return '123456'; };
    d.querySelector('#mv-quellen input[data-quelle="aide"]').checked = false;
    d.getElementById('mv-empfaenger').value = 'b@beispiel.de';
    d.getElementById('mv-absender-name').value = 'Alarm {server}';
    d.getElementById('mv-betreff').value = '[DP]';
    d.getElementById('mv-speichern').click(); await warte();
    let post = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(post && post.rumpf.aktion === 'speichern' && !('nachweis' in post.rumpf) && codes() === 0 && prompts === 0,
           'Empfaenger aendern + Quelle aus: keine Code-Abfrage, kein nachweis im Rumpf');
    pruefe(post && post.rumpf.empfaenger === 'b@beispiel.de' && post.rumpf.quellen.join(',') === 'ueberwachung',
           'Empfaenger und Haken gehen mit');
    pruefe(post && post.rumpf.absender === 'meldung@beispiel.de' && post.rumpf.absender_name === 'Alarm {server}'
           && post.rumpf.betreff === '[DP]', 'Absender, Name und Betreff gehen mit');
    d.getElementById('mv-einrichten').click(); await warte();
    post = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(post && post.rumpf.aktion === 'einrichten' && !('nachweis' in post.rumpf) && prompts === 0 && codes() === 0,
           'Einrichten: keine Code-Abfrage');
    pruefe(!/Freigabe-Code/.test(d.getElementById('mv-block').textContent), 'im Bereich ist von keinem Freigabe-Code die Rede');
    abschnitt('3b. Sprache der Mails = Oberflaechensprache');
    ({ w, d, rufe } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    pruefe(/auf Deutsch verschickt/.test(d.getElementById('mv-status').textContent), 'Statuszeile nennt die Mailsprache');
    w._lang = 'en';
    d.getElementById('mv-speichern').click(); await warte();
    let p2 = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(p2 && p2.rumpf.aktion === 'speichern' && p2.rumpf.sprache === 'en', 'Speichern schickt die Oberflaechensprache mit',
           p2 && JSON.stringify(p2.rumpf.sprache));
    ({ w, d, rufe } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    // ECHTER Umschalter aus i18n.js – kein selbst ausgeloestes Ereignis: die
    // erste Fassung loeste es am document aus und bestaetigte damit nur die
    // eigene (falsche) Annahme; i18n.js feuert am window (ECHT 2026-11-24).
    pruefe(typeof w.setLang === 'function', 'Positivkontrolle: window.setLang aus i18n.js geladen');
    w.setLang('fr'); await warte();
    p2 = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(p2 && p2.rumpf.aktion === 'sprache' && p2.rumpf.sprache === 'fr' && !('empfaenger' in p2.rumpf),
           'Sprachwechsel speichert NUR die Sprache (fr)', p2 && JSON.stringify(p2.rumpf));
    // Sprache vorher woanders umgestellt: beim Oeffnen gleich nachziehen
    ({ w, d, rufe } = baue(STATUS));
    w.setLang('fr');
    w.MailVersand.onShow(); await warte(150);
    p2 = rufe.filter((r) => r.methode === 'POST');
    pruefe(p2.length === 1 && p2[0].rumpf.aktion === 'sprache' && p2[0].rumpf.sprache === 'fr',
           'beim Oeffnen mit anderer Sprache: einmal nachgezogen (keine Schleife)', JSON.stringify(p2.map((r) => r.rumpf)));
    // Lehnt der Server ab (z. B. alter Broker ohne Aktion 'sprache'), darf
    // das Oeffnen NICHT in eine Schleife aus Nachziehen und Neuladen laufen.
    ({ w, d, rufe } = baue(STATUS, { ok: false, meldung: 'Unbekannte Aktion: sprache' }));
    w.setLang('fr');
    w.MailVersand.onShow(); await warte(400);
    pruefe(rufe.filter((r) => r.methode === 'POST').length === 1,
           'abgelehnte Sprache: genau EIN Versuch, keine Schleife', String(rufe.filter((r) => r.methode === 'POST').length));
    // Testnachricht: erst Sprache, dann Test
    ({ w, d, rufe } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    w._lang = 'en';
    d.getElementById('mv-test').click(); await warte(150);
    p2 = rufe.filter((r) => r.methode === 'POST').map((r) => r.rumpf.aktion);
    pruefe(p2.join(',') === 'sprache,test', 'Testnachricht: erst die Sprache angleichen, dann senden', p2.join(','));
    ({ w, d, rufe } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    w.setLang('de'); await warte();
    pruefe(!rufe.some((r) => r.methode === 'POST'), 'gleiche Sprache: nichts geschrieben');

    abschnitt('3c. Rueckmeldungen des Servers in der gewaehlten Sprache');
    // Gemeldet 2026-11-24: bei FR stand "Échec : Keine gültige Absenderadresse".
    // Der Server schickt Kennung + Werte, der deutsche Satz ist nur Rueckfall.
    ({ w, d } = baue(STATUS, { ok: false, code: 'absender_ungueltig', werte: { wert: 'kein absender' },
                               meldung: 'Keine gültige Absenderadresse: kein absender' }));
    w.setLang('fr');
    w.MailVersand.onShow(); await warte(150);
    d.getElementById('mv-absender').value = 'kein absender';
    d.getElementById('mv-speichern').click(); await warte(150);
    let res3 = d.getElementById('mv-result').textContent;
    pruefe(/Adresse d'expéditeur non valide : kein absender/.test(res3) && !/Keine gültige/.test(res3),
           'FR: Fehler aus der Kennung französisch, kein deutscher Satz', res3);
    ({ w, d } = baue(STATUS, { ok: false, code: 'steuerzeichen', werte: { feld: 'betreff' }, meldung: 'Betreff darf keine Steuerzeichen enthalten' }));
    w.setLang('en');
    w.MailVersand.onShow(); await warte(150);
    d.getElementById('mv-speichern').click(); await warte(150);
    res3 = d.getElementById('mv-result').textContent;
    pruefe(/Subject must not contain line breaks/.test(res3), 'EN: Feldname in der Meldung mit übersetzt', res3);
    ({ w, d } = baue(Object.assign({}, STATUS), { ok: true, gesendet: false, code: 'kein_empfaenger', werte: {}, meldung: 'Kein Empfänger eingetragen' }));
    w.MailVersand.onShow(); await warte(150);
    d.getElementById('mv-test').click(); await warte(200);
    res3 = d.getElementById('mv-result').textContent;
    pruefe(/kein Empfänger eingetragen – es wurde nichts verschickt/.test(res3) && !/übergeben/.test(res3),
           'Test ohne Versand meldet den Grund, nicht "übergeben"', res3);
    ({ w, d } = baue(STATUS, { ok: false, code: 'gibt_es_nicht', werte: {}, meldung: 'Rückfall-Satz' }));
    w.MailVersand.onShow(); await warte(150);
    d.getElementById('mv-speichern').click(); await warte(150);
    pruefe(/Rückfall-Satz/.test(d.getElementById('mv-result').textContent), 'unbekannte Kennung: Satz des Servers als Rückfall');

    abschnitt('4. Fehler bleibt stehen');
    ({ w, d } = baue(STATUS, { ok: false, meldung: 'Keine gueltige Absenderadresse: x' }));
    w.MailVersand.onShow(); await warte();
    d.getElementById('mv-empfaenger').value = 'c@beispiel.de';
    d.getElementById('mv-absender').value = 'meldung@server';
    d.getElementById('mv-betreff').value = '[Neu]';
    d.querySelector('#mv-quellen input[data-quelle="system"]').checked = true;
    d.getElementById('mv-speichern').click(); await warte(150);
    const res = d.getElementById('mv-result');
    pruefe(res.style.display !== 'none' && /fehler/.test(res.className) && /gueltige Absenderadresse/.test(res.textContent),
           'Fehler des Servers als Meldung am Knopf', res.textContent);
    // Gemeldet 2026-11-24: nach "Fehlgeschlagen" war ALLES geloescht – der
    // Neuladen des Server-Stands ueberschrieb die Eingaben.
    pruefe(d.getElementById('mv-empfaenger').value === 'c@beispiel.de', 'nach dem Fehler bleibt der eingegebene Empfaenger stehen',
           d.getElementById('mv-empfaenger').value);
    pruefe(d.getElementById('mv-absender').value === 'meldung@server' && d.getElementById('mv-betreff').value === '[Neu]',
           'nach dem Fehler bleiben Absender und Betreff stehen');
    pruefe(d.querySelector('#mv-quellen input[data-quelle="system"]').checked, 'nach dem Fehler bleibt der gesetzte Haken');
    pruefe(/Bereit/.test(d.getElementById('mv-status').textContent), 'die Statuszeile wird trotzdem aktualisiert');
    // Gegenkontrolle: nach ERFOLG zeigt das Formular wieder den Server-Stand
    ({ w, d } = baue(STATUS, { ok: true, meldung: '' }));
    w.MailVersand.onShow(); await warte();
    d.getElementById('mv-empfaenger').value = 'neu@beispiel.de';
    d.getElementById('mv-speichern').click(); await warte(150);
    pruefe(d.getElementById('mv-empfaenger').value === 'a@beispiel.de', 'nach Erfolg steht wieder der Server-Stand im Feld');

    w.close();
    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
