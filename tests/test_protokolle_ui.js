/* UI-Test: weitere Protokolle im Reiter "Protokolle" (jsdom, echte settings.html,
 * echte i18n.js / settings_bedienung.js / protokolle.js).
 *
 * Getrieben ueber die ECHTEN Klappkoepfe (data-klick="plog-klappen" +
 * data-plog). Gemessen: jede Quelle laedt die richtige Adresse mit den
 * Filtern, zeichnet ihre Daten, markiert Fehlschlaege, zeigt Broker-Fehler als
 * Klartext statt leerer Tabelle, laesst HTML nicht ausfuehren, und alle Texte
 * gibt es in DE und EN. Dazu der neue Reitername.
 *
 * Lauf:  timeout 60 node tests/test_protokolle_ui.js
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
const wachhund = setTimeout(() => { console.log('  ✗ ABBRUCH: Wachhund nach 40 s'); bilanz(2); }, 40000);
wachhund.unref && wachhund.unref();

const HTML = lies('frontend/settings.html');
const I18N = lies('frontend/js/i18n.js');
const MODUL = lies('frontend/js/protokolle.js');

const DATEN = {
    '/api/logs/journal': { ok: true, gekappt: 0, eintraege: [
        { zeit: '2026-10-20T17:28:04+02:00', prozess: 'start_jarvis.sh',
          text: 'Traceback\n  File "x.py"\n<img src=x onerror="window.__xss=1">' },
        { zeit: '2026-10-20T17:28:03+02:00', prozess: 'start_jarvis.sh', text: '[AUTH] ok' }] },
    '/api/security/csp': { modus: 'melden', berichte: [
        { ts: 1792505727, seite: '/settings', direktive: 'script-src', blockiert: 'inline',
          quelle: '/static/js/app.js', zeile: '12', anzahl_seit_start: 3, browser: 'Chrome' }] },
    '/api/logs/updates': { ok: true, stand: { hash: 'df2e800', datum: '2026-10-20T18:00:00+02:00', titel: 'feat: x' },
        eintraege: [
            { ts: 1792505800, art: 'update_knopf', benutzer: 'a.b', benutzer_anzeige: 'FIRMA\\a.b',
              ok: false, vorher: 'aaa1111', nachher: 'aaa1111', fehler: 'Signatur fehlt' },
            { ts: 1792505700, art: 'stand_geaendert', vorher: 'bbb2222', nachher: 'ccc3333', titel: 'feat: y',
              vorgespult: true, anzahl: 2, commits: [{ hash: 'ccc3333', titel: 'feat: y' }, { hash: 'ddd4444', titel: 'fix: z' }] }] },
    '/api/logs/ssh': { ok: true, tage: 7, art: '', gekappt: 0,
        anzahl: { angenommen: 5146, fehlgeschlagen: 6, unbekannt: 1 },
        eintraege: [
            { zeit: '2026-10-08T19:11:28+02:00', art: 'fehlgeschlagen', methode: 'password', konto: 'root', ip: '192.0.2.12', schluessel: '' },
            { zeit: '2026-10-06T19:22:45+02:00', art: 'angenommen', methode: 'publickey', konto: 'root', ip: '192.0.2.10', schluessel: 'RSA SHA256:abc' }] },
    '/api/logs/code_fixes': { ok: true, vorhanden: false, eintraege: [], anzahl: 0 },
    '/api/logs/abhaengigkeiten': { ok: true, vorhanden: true, alter_s: 5 * 86400, zustand: {
        zeit: '2026-10-15T03:00:00', fehler: '', geaendert: ['mcp 1.25.0 -> 1.26.0'],
        offen: [{ paket: 'jinja2', version: '3.1.4', id: 'GHSA-xxxx', behoben_in: '3.1.5' }],
        ausgenommen: ['PYSEC-2026-1'], zurueckgesetzt: [], unerfuellt: [], ueber_grenze: [] } },
};

function baue(daten) {
    const dom = new JSDOM(HTML, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    w.fetch = (url) => {
        rufe.push(String(url));
        const pfad = String(url).split('?')[0];
        const d = daten[pfad];
        if (d === undefined) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        if (typeof d === 'number') return Promise.resolve({ ok: false, status: d, json: () => Promise.resolve({}) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
    };
    w.authToken = 'T';
    w.eval(lies('frontend/js/sitzung.js'));
    w.eval(I18N);
    w.eval(lies('frontend/js/settings_bedienung.js'));
    w.eval(MODUL);
    return { w, d: w.document, rufe };
}
const warte = (ms) => new Promise((r) => setTimeout(r, ms || 60));

async function oeffne(d, name) {
    const k = d.querySelector('[data-klick="plog-klappen"][data-plog="' + name + '"]');
    if (!k) return false;
    k.click();
    await warte(60);
    return d.getElementById('plog-' + name + '-body').style.display !== 'none';
}

(async () => {
    abschnitt('0. Positivkontrolle');
    let { w, d, rufe } = baue(DATEN);
    const namen = ['journal', 'csp', 'updates', 'ssh', 'fixes', 'abh'];
    pruefe(namen.every((n) => d.querySelector('[data-plog="' + n + '"]')), 'sechs Abschnitte im Markup');
    pruefe(namen.every((n) => d.querySelector('[data-plog="' + n + '"]').closest('#settings-tab-telemetry')),
           'alle im Protokolle-Reiter');
    pruefe(/\/static\/js\/protokolle\.js\?v=\d+/.test(HTML), 'Modul eingebunden');
    const tab = d.querySelector('[data-settings-tab="telemetry"]');
    pruefe(tab && tab.textContent.trim() === 'Protokolle', 'Rueckfalltext im Markup: "Protokolle"', tab && tab.textContent);
    // Erst applyLang() setzt den i18n-WERT ein – ohne den Aufruf misst die
    // Pruefung nur das Markup (erste Fassung: Gegenprobe blieb stumm).
    w.applyLang();
    pruefe(tab && tab.textContent.trim() === 'Protokolle', 'nach applyLang (DE): "Protokolle"', tab && tab.textContent);
    const offen = [];
    for (const n of namen) offen.push(await oeffne(d, n));
    pruefe(offen.every(Boolean), 'jeder Kopf klappt seinen Abschnitt auf', JSON.stringify(offen));
    if (!offen.every(Boolean)) bilanz(1);
    await warte(80);

    abschnitt('1. Dienst-Journal');
    const jr = rufe.find((u) => u.startsWith('/api/logs/journal'));
    pruefe(jr && /einheit=jarvis/.test(jr) && /stufe=warnung/.test(jr) && /zeitraum=24h/.test(jr),
           'Vorgaben: Hauptdienst, Warnungen, 24 h', jr);
    const jz = d.querySelectorAll('#plog-journal-tbody tr');
    pruefe(jz.length === 2 && jz[0].querySelector('.plog-text').textContent.includes('File "x.py"'),
           'mehrzeilige Meldung in EINER Zeile');
    pruefe(!d.querySelector('#plog-journal-tbody img') && !w.__xss, 'HTML im Journal wird nicht ausgefuehrt');
    d.getElementById('plog-journal-einheit').value = 'broker';
    d.getElementById('plog-journal-einheit').dispatchEvent(new w.Event('change'));
    await warte(60);
    pruefe(/einheit=broker/.test(rufe.filter((u) => u.startsWith('/api/logs/journal')).pop()), 'Auswahl laedt neu');

    abschnitt('2. CSP');
    const cz = d.querySelectorAll('#plog-csp-tbody tr');
    pruefe(cz.length === 1 && cz[0].textContent.includes('/static/js/app.js:12'), 'Quelle mit Zeile');
    pruefe(/nur melden/.test(d.getElementById('plog-csp-status').textContent), 'Modus lesbar');

    abschnitt('3. Update-Verlauf');
    pruefe(/df2e800/.test(d.getElementById('plog-updates-status').textContent), 'aktueller Stand genannt');
    const uz = d.querySelectorAll('#plog-updates-tbody tr');
    pruefe(uz[0].classList.contains('sprot-zeile-warn') && uz[0].textContent.includes('Signatur fehlt'),
           'Fehlschlag ueber den Knopf markiert, mit Grund');
    pruefe(uz[0].textContent.includes('FIRMA\\a.b'), 'Ausloeser mit Anzeigenamen');
    pruefe(uz[1].querySelectorAll('.plog-commits li').length === 2 && !uz[1].classList.contains('sprot-zeile-warn'),
           'Standwechsel mit Commit-Liste, nicht markiert');

    abschnitt('4. SSH');
    const sz = d.querySelectorAll('#plog-ssh-tbody tr');
    pruefe(sz[0].classList.contains('sprot-zeile-warn') && !sz[1].classList.contains('sprot-zeile-warn'),
           'Fehlschlag markiert, Erfolg nicht');
    pruefe(/6 fehlgeschlagen/.test(d.getElementById('plog-ssh-status').textContent), 'Zahlen des Zeitraums');
    pruefe(/von 5153/.test(d.getElementById('plog-ssh-count').textContent), 'angezeigt X von Gesamt');
    d.getElementById('plog-ssh-art').value = 'fehlgeschlagen';
    d.getElementById('plog-ssh-art').dispatchEvent(new w.Event('change'));
    await warte(60);
    pruefe(/art=fehlgeschlagen/.test(rufe.filter((u) => u.startsWith('/api/logs/ssh')).pop()),
           'Filter geht an den Server (nicht nachtraeglich im Browser)');

    abschnitt('5. Selbstkorrekturen');
    pruefe(/keinen Programmcode korrigiert/.test(d.getElementById('plog-fixes-tbody').textContent),
           'leerer Zustand sagt, was er bedeutet');

    abschnitt('6. Abhaengigkeiten');
    const az = d.querySelectorAll('#plog-abh-tbody tr');
    pruefe(az.length === 3, 'offen + angehoben + ausgenommen', String(az.length));
    pruefe(az[0].textContent.includes('Offene Lücke') && az[0].textContent.includes('behoben in 3.1.5')
           && az[0].classList.contains('sprot-zeile-warn'), 'offene Luecke zuerst und markiert');
    pruefe(/5 Tage alt/.test(d.getElementById('plog-abh-status').textContent), 'veraltete Pruefung wird gesagt');
    const ausg = az[2] ? az[2].querySelectorAll('td') : [];
    pruefe(ausg.length === 3 && ausg[1].textContent === '—' && ausg[2].textContent === 'PYSEC-2026-1',
           'Ausnahme: Kennung unter Details, nicht unter Paket');

    abschnitt('7. Kein Loeschweg');
    pruefe(namen.every((n) => !d.querySelector('[data-plog="' + n + '"]').closest('.sk-openclaw-section')
        .querySelector('.jv-ico-trash, .is-danger')), 'kein Muelleimer in den neuen Abschnitten');

    abschnitt('8. Sprachwechsel');
    w._lang = 'en';
    d.dispatchEvent(new w.Event('jarvis-lang-changed'));
    await warte(30);
    pruefe(/Accepted|Failed/.test(d.getElementById('plog-ssh-tbody').textContent), 'SSH-Ergebnisse auf Englisch');
    pruefe(/Open vulnerability/.test(d.getElementById('plog-abh-tbody').textContent), 'Abhaengigkeiten auf Englisch');
    w.close();

    abschnitt('9. Broker-Fehler und Ladefehler');
    const kaputt = Object.assign({}, DATEN, {
        '/api/logs/journal': { ok: false, error: 'Der Root-Broker kennt diese Abfrage noch nicht. … neu starten.' },
        '/api/logs/ssh': 502 });
    ({ w, d, rufe } = baue(kaputt));
    await oeffne(d, 'journal');
    await oeffne(d, 'ssh');
    await warte(80);
    const fj = d.getElementById('plog-journal-fehler');
    pruefe(fj.style.display !== 'none' && /neu starten/.test(fj.textContent), 'Broker-Meldung als Klartext');
    const fs2 = d.getElementById('plog-ssh-fehler');
    pruefe(fs2.style.display !== 'none' && /HTTP 502/.test(fs2.textContent), 'Ladefehler mit Status');
    await warte(4200);
    pruefe(fj.style.display !== 'none', 'Fehler verschwindet nicht von selbst');
    w.close();

    abschnitt('10. i18n');
    const schl = new Set();
    const sekHtml = HTML.split('Weitere Protokolle (2026-10-20)')[1].split('id="btn-tele-refresh"')[0];
    (sekHtml.match(/data-i18n(?:-html|-title|-placeholder)?="([^"]+)"/g) || []).forEach((m) => schl.add(m.split('"')[1]));
    (MODUL.match(/T\('([a-z_.]+)'/g) || []).map((m) => m.slice(3, -1)).filter((k) => !k.endsWith('.') && !k.endsWith('_'))
        .forEach((k) => schl.add(k));
    ['erfasst', 'stand_geaendert', 'update_knopf'].forEach((a) => schl.add('plog.updates.art_' + a));
    ['melden', 'erzwingen', 'aus'].forEach((m) => schl.add('plog.csp.modus_' + m));
    ['offen', 'zurueckgesetzt', 'unerfuellt', 'geaendert', 'ueber_grenze', 'ausgenommen'].forEach((b) => schl.add('plog.abh.' + b));
    schl.add('settings.tab.telemetry');
    const fehlt = [...schl].filter((k) => I18N.split("'" + k + "'").length - 1 < 2);
    pruefe(schl.size > 60, 'Positivkontrolle: Schluessel gefunden (' + schl.size + ')');
    pruefe(!fehlt.length, 'alle in DE und EN', fehlt.join(', '));
    pruefe(/'settings\.tab\.telemetry':\s*'Logs'/.test(I18N), 'Reiter heisst auf Englisch "Logs"');

    bilanz();
})().catch((e) => { console.log('  ✗ ABBRUCH: ' + (e && e.stack || e)); bilanz(2); });
