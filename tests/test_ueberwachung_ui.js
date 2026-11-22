#!/usr/bin/env node
/**
 * Serverueberwachung (Haertung B13) an der CPU-Anzeige – sysload.js.
 *
 * GEMESSEN AM ECHTEN MODUL mit der ECHTEN i18n.js. Die Befunde baut der
 * ERZEUGER (backend/ueberwachung.py ueber python3), nicht dieser Test: jede
 * Platzhalter-Vorlage muss sich aus den Feldern fuellen lassen, die der Server
 * wirklich liefert – ein von Hand getipptes `werte` saehe dem echten nur aehnlich.
 *
 *   1. Administrator + Alarm: Rand-Klasse an #cpu-bar, Tooltip nennt den Alarm
 *   2. Fenster: Abschnitt mit jedem Befund in DE und EN, kein offener {platzhalter}
 *   3. Warnung / ok / nicht eingerichtet: richtige bzw. keine Markierung
 *   4. Nicht-Administrator: KEIN Abruf, keine Markierung
 *   5. Hintergrund-Tab: kein Abruf
 *   6. SSH-Fehlanmeldungen stehen am Zahnrad, NICHT hier (Betreiberentscheid
 *      2026-11-21): keine Markierung, keine Zeile im Fenster
 *
 *   node tests/test_ueberwachung_ui.js
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '..');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => { if (b) { ok++; console.log('  ✓ ' + t); }
                              else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); } };
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
const abbruch = (t) => { console.log('ABBRUCH: ' + t); console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL'); process.exit(2); };
process.on('unhandledRejection', e => { fail++; console.log('  ✗ unbehandelte Zurueckweisung: ' + (e && e.message)); });
let _bilanz = false;
process.on('exit', (c) => { if (!_bilanz && c === 0) {
    console.log('  ✗ ABBRUCH: keine Bilanzzeile – der Lauf ist vorzeitig beendet'); process.exitCode = 1; } });
require('./lib/wachhund')(() => { console.log('  ✗ ABBRUCH: der Lauf haengt (kein Ergebnis nach 40 s)'); process.exit(1); }, 40000);

const { JSDOM } = require('./lib/jsdom_laden')();
const SYSLOAD = process.env.JARVIS_SYSLOAD_PRUEFLING || path.join(ROOT, 'frontend/js/sysload.js');
const I18N = path.join(ROOT, 'frontend/js/i18n.js');
const MOD = process.env.JARVIS_UEBERW_PRUEFLING || path.join(ROOT, 'backend/ueberwachung.py');

// ── Befunde vom Erzeuger: je Art einer, ueber auswerten() ──────────────────
const PY = `
import importlib.util, json, sys
s = importlib.util.spec_from_file_location("u", sys.argv[1]); u = importlib.util.module_from_spec(s); s.loader.exec_module(u)
J = 1_800_000_000.0
def e(**kw):
    d = {"dienste": {}, "fehlgeschlagen": [], "platz": {}, "zert_ablauf": J + 400*86400, "zert_fehler": "",
         "ssh": [], "kern": [], "cursor": {}, "uid_dienst": 1001, "uid_sandbox": [996]}
    d.update(kw); return d
O = "nft-out-drop: IN= OUT=ens192 SRC=192.0.2.1 DST=203.0.113.5 PROTO=TCP SPT=1 DPT=443 UID=%s GID=%s"
I = "nft-in-drop: IN=ens192 OUT= SRC=192.0.2.9 DST=192.0.2.1 PROTO=TCP SPT=1 DPT=8443"
F = "nft-fwd-drop: IN=ens192 OUT=ens193 SRC=192.0.2.9 DST=192.0.2.1 PROTO=TCP SPT=1 DPT=80"
k = lambda *m: [{"zeit": J - 9, "msg": x} for x in m]
faelle = [
    e(dienste={"jarvis.service": {"enabled": "enabled", "active": "failed"}}, fehlgeschlagen=["x.service"]),
    e(platz={"/": {"frei": 3*10**9, "gesamt": 100*10**9, "geraet": 1}, "/var/log": {"fehler": "weg"}}),
    e(zert_ablauf=J + 5*86400), e(zert_ablauf=J - 2*86400), e(zert_ablauf=None, zert_fehler="Datei fehlt"),
    e(ssh=k("Invalid user x from 198.51.100.4 port 7")),
    e(kern=k(O % (1001, 1001), O % (4242, 4242), O % (996, 996), F, *[I]*int(u.VORGABE["IN_WARNUNG"]))),
    e(kern=k(I)),
]
bf = []
for f in faelle:
    z, _ = u.auswerten(f, {}, dict(u.VORGABE, _konf_fehler="x"), J)
    bf += z["befunde"]
seen = {}
for b in bf:
    seen.setdefault((b["art"], b["stufe"]), b)
print(json.dumps({"befunde": list(seen.values()), "arten": sorted({b["art"] for b in bf})}))
`;
let ERZ;
try {
    ERZ = JSON.parse(execFileSync('python3', ['-I', '-c', PY, MOD], { encoding: 'utf8' }));
} catch (e) { abbruch('Befunde vom Erzeuger nicht erhalten: ' + (e.message || e)); }
const ALLE = ERZ.befunde;
const ERWARTETE_ARTEN = ['dienst_aus', 'units_failed', 'platz', 'platz_fehler', 'zert_ablauf', 'zert_fehler',
                         'ssh_fehl', 'out_dienst', 'out_fremd', 'out_sandbox', 'fwd_drop', 'in_drop', 'konf_fehler'];
const fehlende = ERWARTETE_ARTEN.filter(a => ERZ.arten.indexOf(a) < 0);
if (fehlende.length) abbruch('der Erzeuger lieferte nicht jede Art (fehlt: ' + fehlende.join(', ') + ') – Messaufbau unvollstaendig');
// Befunde, die NUR lesen() erzeugt
ALLE.push({ id: 'veraltet', art: 'veraltet', stufe: 'warnung', text: 'x', werte: { minuten: 42 }, seit: 1_800_000_000 });
ALLE.push({ id: 'lesbar', art: 'unlesbar', stufe: 'warnung', text: 'x', werte: {} });

const warte = (ms) => new Promise(r => setTimeout(r, ms));

async function seite({ admin, antwort, sichtbar = true, lang = 'de' }) {
    const dom = new JSDOM('<!doctype html><body><div class="topbar-left"><div id="cpu-bar" class="jv-cpu-bar"></div></div></body>',
                          { url: 'https://h/portal', runScripts: 'outside-only', pretendToBeVisual: sichtbar });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'x');
    w.localStorage.setItem('jarvis_lang', lang);
    const abrufe = [];
    w.fetch = (url) => {
        const pfad = String(url).split('?')[0];
        abrufe.push(pfad);
        const antw = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(d))) });
        if (pfad === '/api/me') return antw({ is_admin: !!admin });
        if (pfad === '/api/system/ueberwachung') return antw(antwort);
        if (pfad === '/api/system/load') return antw({
            fenster_s: 0.5, prozesse_gesamt: 1, cpu: { prozent: 1, kerne: 1, je_kern: [1], last: [0, 0, 0] },
            speicher: { prozent: 1, belegt: 1, gesamt: 2 }, netz: {}, platte: { io: {}, partitionen: [] }, prozesse: [] });
        return Promise.reject(new Error('unerwartet: ' + pfad));
    };
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8'));
    w.eval(fs.readFileSync(I18N, 'utf8'));
    if (w.applyLang) { try { w.applyLang(lang); } catch (e) { /* ohne DOM-Ziele */ } }
    w._lang = lang;
    w.eval(fs.readFileSync(SYSLOAD, 'utf8'));
    await warte(80);
    return { w, abrufe, bar: w.document.getElementById('cpu-bar') };
}

const ANTW = (stufe, befunde) => ({ ok: true, eingerichtet: true, stufe, zeit: 1_800_000_000, alter_s: 120,
                                    veraltet: false, takt_s: 300, befunde });

(async () => {
    abschnitt('0. Positivkontrolle');
    const p0 = await seite({ admin: true, antwort: ANTW('ok', []) });
    if (!p0.w.JarvisSysLoad || typeof p0.w.t !== 'function') abbruch('sysload.js oder i18n.js nicht geladen');
    if (p0.w.t('ue.titel') === 'ue.titel') abbruch('i18n kennt ue.titel nicht – Uebersetzungen fehlen ganz');
    pruefe(p0.abrufe.indexOf('/api/system/ueberwachung') >= 0, 'Administrator: Zustand wird abgerufen');

    abschnitt('1. Alarm an der CPU-Anzeige');
    const alarm = ALLE.filter(b => b.stufe === 'alarm');
    const p1 = await seite({ admin: true, antwort: ANTW('alarm', alarm) });
    pruefe(p1.bar.classList.contains('jv-ue-alarm') && !p1.bar.classList.contains('jv-ue-warnung'),
           'Klasse jv-ue-alarm gesetzt', p1.bar.className);
    pruefe(/Alarm/.test(p1.bar.title) && /Alarm/.test(p1.bar.getAttribute('aria-label') || ''),
           'Tooltip und aria-label nennen den Alarm als TEXT', p1.bar.title);

    abschnitt('2. Fenster: jeder Befund, DE und EN');
    for (const lang of ['de', 'en']) {
        // umgekehrt: Hinweise und Warnungen zuerst – die Sortierung muss das Modul leisten
        const p = await seite({ admin: true, antwort: ANTW('alarm', ALLE.slice().reverse()), lang });
        p.w.JarvisSysLoad.oeffnen();
        await warte(120);
        const ab = p.w.document.querySelector('.jv-ue');
        pruefe(!!ab, lang + ': Abschnitt Serverueberwachung im Fenster');
        if (!ab) continue;
        const zeilen = [...ab.querySelectorAll('li')].map(l => l.textContent);
        const HIER = ALLE.filter(b => b.art !== 'ssh_fehl');
        if (HIER.length === ALLE.length) abbruch('der Erzeuger lieferte keinen SSH-Befund – Filter nicht messbar');
        pruefe(zeilen.length === HIER.length, lang + ': eine Zeile je Befund ausser SSH (' + zeilen.length + '/' + HIER.length + ')');
        const offen = zeilen.filter(z => /\{\w+\}/.test(z));
        pruefe(!offen.length, lang + ': kein unaufgeloester {platzhalter}', offen.join(' | '));
        const leer = zeilen.filter(z => /\(\)|: \.|von \.|from \.|UID \)|Ziele \.|targets \./.test(z));
        pruefe(!leer.length, lang + ': kein leer eingesetzter Wert', leer.join(' | '));
        // Jede Art hat eine Vorlage in DIESER Sprache (sonst faellt die Zeile
        // auf den deutschen Servertext zurueck).
        const ohne = ALLE.map(b => b.art === 'zert_ablauf' && b.werte.tage < 0 ? 'zert_abgelaufen'
                                   : b.art === 'in_drop' && b.stufe === 'warnung' ? 'in_drop_voll' : b.art)
                         .filter(a => p.w.t('ue.art_' + a) === 'ue.art_' + a);
        pruefe(!ohne.length, lang + ': jede Befundart hat eine Uebersetzung', ohne.join(', '));
        const erste = ab.querySelector('li b');
        pruefe(erste && erste.textContent === (lang === 'de' ? 'Alarm' : 'Alarm'),
               lang + ': Alarme stehen oben, mit Stufe als Text');
        pruefe(!zeilen.some(z => /198\.51\.100\.4|SSH/.test(z)),
               lang + ': kein SSH-Befund im Fenster (der steht am Zahnrad)', zeilen.filter(z => /SSH/.test(z)).join(' | '));
        const z_platz = zeilen.find(z => /3[.,]0 %/.test(z) && /(frei|free)/.test(z));
        // Positivkontrolle der Sprache: ohne sie waere "EN" ein zweiter DE-Lauf
        pruefe(z_platz && (lang === 'de' ? /nur noch .* frei/ : /Only .* free on/).test(z_platz),
               lang + ': Zeile steht wirklich in dieser Sprache', z_platz || zeilen.join(' | '));
    }

    abschnitt('3. Warnung, ok, nicht eingerichtet');
    const p3 = await seite({ admin: true, antwort: ANTW('warnung', ALLE.filter(b => b.stufe === 'warnung')) });
    pruefe(p3.bar.classList.contains('jv-ue-warnung') && !p3.bar.classList.contains('jv-ue-alarm'), 'Warnung: jv-ue-warnung');
    const p4 = await seite({ admin: true, antwort: ANTW('info', ALLE.filter(b => b.stufe === 'info')) });
    pruefe(!p4.bar.classList.contains('jv-ue-warnung') && !p4.bar.classList.contains('jv-ue-alarm'),
           'nur Hinweise: keine Markierung');
    p4.w.JarvisSysLoad.oeffnen(); await warte(120);
    pruefe(/Alles in Ordnung/.test((p4.w.document.querySelector('.jv-ue') || {}).textContent || ''),
           'nur Hinweise: Fenster sagt "Alles in Ordnung" und listet die Hinweise');
    const p5 = await seite({ admin: true, antwort: { ok: true, eingerichtet: false, stufe: 'ok', befunde: [] } });
    pruefe(!p5.bar.classList.contains('jv-ue-warnung') && !p5.bar.classList.contains('jv-ue-alarm'),
           'nicht eingerichtet: keine Markierung');

    abschnitt('3b. Nur SSH-Fehlanmeldungen');
    const nurSsh = ALLE.filter(b => b.art === 'ssh_fehl');
    for (const st of ['warnung', 'alarm']) {
        const bf = nurSsh.map(b => Object.assign({}, b, { stufe: st }));
        const p = await seite({ admin: true, antwort: ANTW(st, bf) });
        pruefe(!p.bar.classList.contains('jv-ue-warnung') && !p.bar.classList.contains('jv-ue-alarm'),
               'SSH-' + st + ' (Server-Stufe ' + st + '): CPU-Anzeige bleibt unmarkiert', p.bar.className);
        p.w.JarvisSysLoad.oeffnen(); await warte(120);
        const ab = p.w.document.querySelector('.jv-ue');
        pruefe(ab && /Alles in Ordnung/.test(ab.textContent) && !ab.querySelector('li'),
               'SSH-' + st + ': Fenster sagt "Alles in Ordnung", ohne Zeile', ab && ab.textContent.slice(0, 120));
    }

    abschnitt('4. Nicht-Administrator');
    const p6 = await seite({ admin: false, antwort: ANTW('alarm', alarm) });
    pruefe(p6.abrufe.indexOf('/api/system/ueberwachung') < 0, 'kein Abruf des Zustands');
    pruefe(!p6.bar.classList.contains('jv-ue-alarm'), 'keine Markierung');

    abschnitt('5. Hintergrund-Tab');
    const p7 = await seite({ admin: true, antwort: ANTW('alarm', alarm), sichtbar: false });
    if (!p7.w.document.hidden) {
        console.log('  HINWEIS: jsdom meldet das Dokument als sichtbar – Probe nicht messbar');
    } else {
        pruefe(p7.abrufe.indexOf('/api/system/ueberwachung') < 0, 'verborgenes Dokument: kein Abruf');
    }

    _bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => abbruch('Absturz: ' + (e && e.stack || e)));
