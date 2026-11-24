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
 *   3. Freigabe-Code: nur eine Quelle EINschalten -> kein Code; Quelle aus oder
 *      anderer Empfaenger -> Code wird abgefragt und mitgeschickt.
 *   4. Ein Fehler (Code falsch) bleibt als Meldung am Knopf stehen.
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
    letzte: [{ zeit: 1795480000, quelle: 'aide', betreff: '<img src=x onerror="window.__xss=1">', ok: true, fehler: '' }],
    server: 'probe.beispiel.de',
};

function baue(status, postAntwort) {
    const dom = new JSDOM(AUSSCHNITT.html, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    let codes = 0;
    w.fetch = (url, o) => {
        const pfad = String(url).split('?')[0];
        rufe.push({ pfad: pfad, methode: (o && o.method) || 'GET', rumpf: o && o.body ? JSON.parse(o.body) : null });
        const daten = pfad === '/api/broker/mailversand/status' ? status : (postAntwort || { ok: true, meldung: '' });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(daten) });
    };
    w.confirm = () => true;
    w.authToken = 'T';
    w.eval(lies('frontend/js/sitzung.js'));
    w.eval(lies('frontend/js/i18n.js'));
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

    abschnitt('3. Freigabe-Code nur bei Lockerung');
    ({ w, d, rufe, codes } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    d.querySelector('#mv-quellen input[data-quelle="sicherheit"]').checked = true;
    d.getElementById('mv-speichern').click(); await warte();
    let post = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(post && post.rumpf.aktion === 'speichern' && !post.rumpf.nachweis && codes() === 0,
           'Quelle einschalten: ohne Code gespeichert');
    pruefe(post && post.rumpf.quellen.join(',') === 'ueberwachung,aide,sicherheit', 'die Haken gehen mit', post && post.rumpf.quellen.join(','));
    ({ w, d, rufe, codes } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    d.querySelector('#mv-quellen input[data-quelle="aide"]').checked = false;
    d.getElementById('mv-speichern').click(); await warte();
    post = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(post && post.rumpf.nachweis === '123456' && codes() === 1, 'Quelle ausschalten: Code abgefragt und mitgeschickt');
    ({ w, d, rufe, codes } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    d.getElementById('mv-empfaenger').value = 'b@beispiel.de';
    d.getElementById('mv-speichern').click(); await warte();
    post = rufe.filter((r) => r.methode === 'POST').pop();
    pruefe(post && post.rumpf.nachweis === '123456' && post.rumpf.empfaenger === 'b@beispiel.de',
           'anderer Empfaenger: Code abgefragt');
    ({ w, d, rufe, codes } = baue(STATUS));
    w.MailVersand.onShow(); await warte();
    d.getElementById('mv-relay').value = 'mail.beispiel.de';
    d.getElementById('mv-speichern').click(); await warte();
    pruefe(codes() === 0, 'Relay ohne Port = gleicher Relay (:25) – kein Code');

    abschnitt('4. Fehler bleibt stehen');
    ({ w, d } = baue(STATUS, { ok: false, grund: 'nachweis_falsch', error: 'x' }));
    w.MailVersand.onShow(); await warte();
    d.getElementById('mv-empfaenger').value = 'c@beispiel.de';
    d.getElementById('mv-speichern').click(); await warte(150);
    const res = d.getElementById('mv-result');
    pruefe(res.style.display !== 'none' && /fehler/.test(res.className) && /CODE:nachweis_falsch/.test(res.textContent),
           'Code-Fehler als Meldung am Knopf (Text aus Fernzugang._codeText)', res.textContent);

    w.close();
    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
