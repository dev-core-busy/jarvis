#!/usr/bin/env node
/**
 * Serverueberwachung (Haertung B13) in der Oberflaeche: ALLES am Zahnrad,
 * NICHTS an der CPU-Anzeige.
 *
 * VORGESCHICHTE: bis 2026-11-25 markierte sysload.js die CPU-Anzeige bei jeder
 * Warnung (Rand, "!", Tooltip "Serverüberwachung: Warnung", Abschnitt im
 * Fenster); nur die SSH-Fehlanmeldungen waren am 2026-11-21 ans Zahnrad
 * umgezogen. Gemeldet 2026-11-25: "stelle ENDLICH ab, dass 'Serverüberwachung
 * Warnung' in der CPU Pill angezeigt wird … das gehört in die Zahnrad Badge".
 *
 * GEMESSEN ALS KETTE, nicht an Attrappen: die Befunde baut der ERZEUGER
 * (backend/ueberwachung.py, auswerten()), die Badge-Daten baut die ECHTE
 * Funktion `_admin_badge_messen` aus backend/main.py (per AST geschnitten,
 * nur Broker/Sperrliste sind Attrappen), und gezeichnet wird mit dem ECHTEN
 * settings_btn.js und der ECHTEN i18n.js. Ein von Hand getipptes `admin_badge`
 * saehe dem echten nur aehnlich (Register: Testmaterial baut der Erzeuger).
 *
 *   0. Positivkontrolle: Erzeuger liefert jede Art, Module laden
 *   1. CPU-Anzeige (sysload.js): kein Abruf der Ueberwachung, keine Markierung,
 *      kein Zusatz im Tooltip, kein Abschnitt im Fenster – auch bei Alarm.
 *      Positivkontrolle: der Administrator ist erkannt (Klick-Ausstattung).
 *   2. Badge-Daten: jede Warnung/jeder Alarm ein Posten, Hinweise nicht, SSH
 *      weiterhin EIN Posten, Alarme zuerst, ue_alarm gesetzt
 *   3. Panel am Zahnrad, DE und EN: eine Zeile je Befund, jede Art uebersetzt,
 *      kein offener {platzhalter}, {marke} gebrandet, Text wirklich in der Sprache
 *   4. Wege: AIDE-Zeilen fuehren in "Paket-Updates und Integritaet", die
 *      uebrigen sind kein Knopf und versprechen keinen Sprung; Alarm faerbt rot
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

const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const SYSLOAD = process.env.JARVIS_SYSLOAD_PRUEFLING || path.join(ROOT, 'frontend/js/sysload.js');
const SBTN = process.env.JARVIS_SBTN_PRUEFLING || path.join(ROOT, 'frontend/js/settings_btn.js');
const MAIN = process.env.JARVIS_MAIN_PRUEFLING || path.join(ROOT, 'backend/main.py');
const I18N = path.join(ROOT, 'frontend/js/i18n.js');
const MOD = process.env.JARVIS_UEBERW_PRUEFLING || path.join(ROOT, 'backend/ueberwachung.py');
const lies = (p) => fs.readFileSync(p, 'utf8');

// ── Befunde vom Erzeuger, Badge-Daten von der echten Funktion ──────────────
const PY = `
import ast, importlib.util, json, sys, types
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
bf = list(seen.values())
# Befunde, die NUR lesen() bzw. der AIDE-Teil erzeugen: ueber lesen() selbst
# (veraltet) – AIDE ueber den Erzeuger des AIDE-Teils, wenn er sich isoliert rufen laesst.
import tempfile, os, time
with tempfile.TemporaryDirectory() as d:
    pf = os.path.join(d, "z.json")
    with open(pf, "w") as fh:
        json.dump({"zeit": J - 3 * 3600, "befunde": []}, fh)
    bf += [b for b in u.lesen(__import__("pathlib").Path(pf), jetzt=J)["befunde"]]
bf.append({"id": "aide", "art": "aide_offen", "stufe": "warnung", "text": "AIDE: 742 nicht erklaert",
           "werte": {"anzahl": 742}, "seit": J - 60})
arten = sorted({b["art"] for b in bf})
befunde = [{k2: b.get(k2) for k2 in ("id", "art", "stufe", "text", "werte", "seit")} for b in bf]

# _admin_badge_messen aus main.py: genau diese Funktion, mit Attrappen fuer
# Broker und Sperrliste; die Ueberwachung liefert die Befunde oben.
src = open(sys.argv[2], encoding="utf-8").read()
fn = next((n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_admin_badge_messen"), None)
if fn is None:
    print(json.dumps({"fehler": "_admin_badge_messen fehlt"})); sys.exit(0)
code = "\\n".join(src.splitlines()[fn.lineno - 1:fn.end_lineno])
pkg = types.ModuleType("backend"); pkg.__path__ = []
bc = types.ModuleType("backend.broker_client"); bc.mode = lambda: "none"
ue = types.ModuleType("backend.ueberwachung"); ue.lesen = lambda: {"ok": True, "eingerichtet": True, "befunde": befunde}
pkg.broker_client = bc; pkg.ueberwachung = ue
sys.modules.update({"backend": pkg, "backend.broker_client": bc, "backend.ueberwachung": ue})
ns = {"security_guard": types.SimpleNamespace(list_blocked=lambda: []), "_display_name": lambda x: x,
      "_ADMIN_BADGE_ITEMS_MAX": 1000, "_ADMIN_BADGE_TIMEOUT": 3.0}
exec(code, ns)
badge = ns["_admin_badge_messen"]("jarvis")
print(json.dumps({"befunde": befunde, "arten": arten, "badge": badge}))
`;
let ERZ;
try {
    ERZ = JSON.parse(execFileSync('python3', ['-I', '-c', PY, MOD, MAIN], { encoding: 'utf8' }));
} catch (e) { abbruch('Befunde vom Erzeuger nicht erhalten: ' + (e.message || e)); }
if (ERZ.fehler) abbruch(ERZ.fehler);
const ALLE = ERZ.befunde;
const BADGE = ERZ.badge;
// Arten aus auswerten(): fehlt eine, ist der MESSAUFBAU unvollstaendig (Exit 2).
const ERWARTETE_ARTEN = ['dienst_aus', 'units_failed', 'platz', 'platz_fehler', 'zert_ablauf', 'zert_fehler',
                         'ssh_fehl', 'out_dienst', 'out_fremd', 'out_sandbox', 'fwd_drop', 'in_drop', 'konf_fehler',
                         'aide_offen'];
const fehlende = ERWARTETE_ARTEN.filter(a => ERZ.arten.indexOf(a) < 0);
if (fehlende.length) abbruch('der Erzeuger lieferte nicht jede Art (fehlt: ' + fehlende.join(', ') + ') – Messaufbau unvollstaendig');
// 'veraltet' erzeugt lesen() aus einem 3 h alten Zustand – fehlt er, ist das ein
// BEFUND des Erzeugers (ein stehender Waechter saehe wie "alles gut" aus), kein
// Aufbaufehler. Exit 2 machte die Gegenproben dazu stumm (2026-11-25).
const VERALTET_DA = ERZ.arten.indexOf('veraltet') >= 0;
const AM_ZAHNRAD = ALLE.filter(b => b.art !== 'ssh_fehl' && (b.stufe === 'warnung' || b.stufe === 'alarm'));
const HINWEISE = ALLE.filter(b => b.stufe === 'info');
if (!HINWEISE.length || !ALLE.some(b => b.stufe === 'alarm') || !ALLE.some(b => b.art === 'ssh_fehl'))
    abbruch('der Erzeuger lieferte nicht Hinweis, Alarm UND SSH – Filter nicht messbar');

const warte = (ms) => new Promise(r => setTimeout(r, ms));
function stilleKonsole() {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (err) => {
        if (!/Not implemented: navigation/.test(String(err && err.message))) console.log('  ! jsdomError: ' + err.message);
    });
    return vc;
}

async function seite({ admin, badge, ueAntwort, lang = 'de', marke = null, sysload = false }) {
    const dom = new JSDOM('<!doctype html><body><div class="topbar-left"><div id="cpu-bar" class="jv-cpu-bar"></div></div>'
                          + '<button data-jarvis-settings="/portal" style="display:none"></button></body>',
                          { url: 'https://h/portal', runScripts: 'outside-only', pretendToBeVisual: true,
                            virtualConsole: stilleKonsole() });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'x');
    w.localStorage.setItem('jarvis_lang', lang);
    const abrufe = [];
    w.fetch = (url) => {
        const pfad = String(url).split('?')[0];
        abrufe.push(pfad);
        const antw = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(d))) });
        if (pfad === '/api/me') return antw({ is_admin: !!admin, admin_konto: !!admin, admin_badge: admin ? badge : undefined });
        if (pfad === '/api/system/ueberwachung') return antw(ueAntwort || {});
        if (pfad === '/api/system/load') return antw({
            fenster_s: 0.5, prozesse_gesamt: 1, cpu: { prozent: 1, kerne: 1, je_kern: [1], last: [0, 0, 0] },
            speicher: { prozent: 1, belegt: 1, gesamt: 2 }, netz: {}, platte: { io: {}, partitionen: [] }, prozesse: [] });
        return Promise.reject(new Error('unerwartet: ' + pfad));
    };
    w.eval(lies(path.join(ROOT, 'frontend/js/sitzung.js')));
    w.eval(lies(path.join(ROOT, 'frontend/js/icons.js')));
    w.eval(lies(I18N));
    if (w.applyLang) { try { w.applyLang(lang); } catch (e) { /* ohne DOM-Ziele */ } }
    w._lang = lang;
    if (marke) w.jarvisMarke = () => marke;   // Schnittstelle von branding.js
    if (sysload) w.eval(lies(SYSLOAD));
    else w.eval(lies(SBTN));
    await warte(80);
    return { w, d: w.document, abrufe, bar: w.document.getElementById('cpu-bar') };
}
const gearBadge = (d) => d.querySelector('[data-jarvis-settings] .jv-gear-badge');
const hover = (w, d) => {
    const b = gearBadge(d);
    if (b) b.dispatchEvent(new w.MouseEvent('mouseenter', { bubbles: false }));
    return d.querySelector('.jv-gear-tip');
};
const ANTW = (stufe, befunde) => ({ ok: true, eingerichtet: true, stufe, zeit: 1_800_000_000, alter_s: 120,
                                    veraltet: false, takt_s: 300, befunde });

(async () => {
    abschnitt('0. Positivkontrolle');
    const p0 = await seite({ admin: true, badge: BADGE, sysload: true, ueAntwort: ANTW('alarm', ALLE) });
    if (!p0.w.JarvisSysLoad || typeof p0.w.t !== 'function') abbruch('sysload.js oder i18n.js nicht geladen');
    if (p0.w.t('ue.titel') === 'ue.titel') abbruch('i18n kennt ue.titel nicht – Uebersetzungen fehlen ganz');
    if (!p0.bar.classList.contains('jv-cpu-klick')) abbruch('sysload.js hat den Administrator nicht erkannt – Teil 1 waere trivial');
    pruefe(true, 'Erzeuger, Badge-Funktion und Module geladen, Administrator erkannt');

    abschnitt('1. CPU-Anzeige: keine Spur der Serverueberwachung');
    for (const [name, bf] of [['Alarm', ALLE.filter(b => b.stufe === 'alarm')], ['Warnung', ALLE.filter(b => b.stufe === 'warnung')]]) {
        const p = await seite({ admin: true, sysload: true, ueAntwort: ANTW(name === 'Alarm' ? 'alarm' : 'warnung', bf) });
        pruefe(p.abrufe.indexOf('/api/system/ueberwachung') < 0,
               name + ': sysload.js fragt die Ueberwachung gar nicht ab', JSON.stringify(p.abrufe));
        const markiert = [...p.bar.classList].filter(c => /^jv-ue/.test(c));
        pruefe(!markiert.length, name + ': keine Markierung an der CPU-Anzeige', markiert.join(' '));
        const txt = (p.bar.title || '') + ' ' + (p.bar.getAttribute('aria-label') || '');
        pruefe(!/überwachung|monitoring|Alarm|Warnung|warning/i.test(txt),
               name + ': Tooltip/aria-label ohne Ueberwachung', txt);
        p.w.JarvisSysLoad.oeffnen();
        await warte(120);
        const fenster = p.d.querySelector('.jv-load-overlay');
        if (!fenster || !/Prozess/.test(fenster.textContent)) abbruch('Fenster der Auslastung nicht gezeichnet – Probe nicht messbar');
        pruefe(!p.d.querySelector('.jv-ue') && !/Serverüberwachung/.test(fenster.textContent),
               name + ': kein Abschnitt Serverueberwachung im Fenster');
        p.w.close();
    }

    abschnitt('2. Badge-Daten aus der echten Funktion');
    pruefe(VERALTET_DA, 'lesen() meldet einen 3 Stunden alten Zustand als "veraltet" (Warnung am Zahnrad)');
    const items = (BADGE.items || []).filter(i => i.art === 'ue');
    pruefe(items.length === AM_ZAHNRAD.length,
           'je Warnung/Alarm (ohne SSH) ein Posten (' + items.length + '/' + AM_ZAHNRAD.length + ')');
    // Arten, die der Erzeuger NUR als Hinweis liefert (Sandbox, Weiterleitung):
    // keine davon darf am Zahnrad stehen.
    const NUR_INFO = [...new Set(HINWEISE.map(h => h.art))].filter(a => !AM_ZAHNRAD.some(b2 => b2.art === a));
    if (!NUR_INFO.length) abbruch('keine Art, die nur als Hinweis vorkommt – Filter nicht messbar');
    pruefe(!items.some(i => NUR_INFO.indexOf(i.ue_art) >= 0),
           'Hinweise (Stufe info) erscheinen NICHT am Zahnrad (' + NUR_INFO.join(', ') + ')',
           items.filter(i => NUR_INFO.indexOf(i.ue_art) >= 0).map(i => i.ue_art).join(','));
    pruefe((BADGE.items || []).filter(i => i.art === 'ssh').length === 1 && BADGE.ssh_fehl > 0,
           'SSH bleibt EIN eigener Posten');
    pruefe(BADGE.ue_warnungen === AM_ZAHNRAD.length && BADGE.gesamt === AM_ZAHNRAD.length + 1,
           'gesamt = Ueberwachung + SSH', JSON.stringify([BADGE.ue_warnungen, BADGE.gesamt]));
    const stufen = items.map(i => i.stufe);
    pruefe(stufen.indexOf('warnung') > stufen.lastIndexOf('alarm') || stufen.indexOf('warnung') < 0,
           'Alarme stehen vor Warnungen', stufen.join(','));
    pruefe(BADGE.ue_alarm === true, 'ue_alarm gesetzt');

    abschnitt('3. Panel am Zahnrad, DE und EN');
    for (const lang of ['de', 'en']) {
        const p = await seite({ admin: true, badge: BADGE, lang, marke: 'Fabrikam' });
        const b = gearBadge(p.d);
        pruefe(b && b.textContent === String(BADGE.gesamt), lang + ': Badge zeigt die Gesamtzahl', b && b.textContent);
        const el = hover(p.w, p.d);
        if (!el) { pruefe(false, lang + ': Panel oeffnet'); continue; }
        const zeilen = [...el.querySelectorAll('.jv-gear-tip-row[data-ue]')].map(z => z.textContent);
        pruefe(zeilen.length === AM_ZAHNRAD.length, lang + ': eine Zeile je Befund (' + zeilen.length + '/' + AM_ZAHNRAD.length + ')');
        const offen = zeilen.filter(z => /\{\w+\}/.test(z));
        pruefe(!offen.length, lang + ': kein unaufgeloester {platzhalter}', offen.join(' | '));
        const leer = zeilen.filter(z => /\(\)|: \.|von \.|from \.|UID \)|Ziele \.|targets \./.test(z));
        pruefe(!leer.length, lang + ': kein leer eingesetzter Wert', leer.join(' | '));
        const ohne = AM_ZAHNRAD.map(b2 => b2.art === 'zert_ablauf' && b2.werte.tage < 0 ? 'zert_abgelaufen'
                                   : b2.art === 'in_drop' && b2.stufe === 'warnung' ? 'in_drop_voll' : b2.art)
                         .filter(a => p.w.t('ue.art_' + a) === 'ue.art_' + a);
        pruefe(!ohne.length, lang + ': jede Befundart hat eine Uebersetzung', ohne.join(', '));
        const z_marke = zeilen.find(z => /(wollte ins Netz|tried to reach the network)/.test(z));
        // Fehlt die Zeile, ist das ein Produktbefund (FAIL), kein Messaufbau-Fehler.
        pruefe(!!z_marke && /Fabrikam (selbst|itself)/.test(z_marke), lang + ': out_dienst nennt den gebrandeten Namen', z_marke || 'Zeile fehlt');
        const z_platz = zeilen.find(z => /3[.,]0 %/.test(z) && /(frei|free)/.test(z));
        pruefe(z_platz && (lang === 'de' ? /nur noch .* frei/ : /Only .* free on/).test(z_platz),
               lang + ': Zeile steht wirklich in dieser Sprache', z_platz || zeilen.join(' | '));
        const erste = el.querySelector('.jv-gear-tip-row[data-ue] .jv-gear-tip-k');
        pruefe(erste && erste.textContent === 'Alarm' && erste.classList.contains('blocked'),
               lang + ': die erste Zeile ist ein Alarm, Stufe als Text', erste && erste.outerHTML);
        p.w.close();
    }

    abschnitt('4. Wege und Farbe');
    {
        const p = await seite({ admin: true, badge: BADGE });
        const b = gearBadge(p.d);
        pruefe(b && b.classList.contains('is-danger'), 'ein Alarm der Ueberwachung faerbt die Badge rot');
        pruefe(b && /Serverüberwachung: \d+/.test(b.getAttribute('aria-label') || ''),
               'aria-label nennt die Warnungen der Ueberwachung', b && b.getAttribute('aria-label'));
        const el = hover(p.w, p.d);
        const aide = el && el.querySelector('.jv-gear-tip-row[data-ue="aide_offen"]');
        pruefe(aide && aide.tagName === 'BUTTON' && aide.getAttribute('data-fokus') === 'pakete'
               && aide.getAttribute('data-reiter') === 'profiles',
               'AIDE-Zeile ist ein Knopf in "Paket-Updates und Integritaet"', aide && aide.outerHTML.slice(0, 140));
        const still = el ? [...el.querySelectorAll('.jv-gear-tip-row[data-ue]')].filter(z => z.getAttribute('data-ue') !== 'aide_offen') : [];
        pruefe(still.length && still.every(z => z.tagName !== 'BUTTON' && !z.hasAttribute('data-fokus')),
               'die uebrigen Befunde sind kein Knopf und versprechen keinen Sprung',
               still.filter(z => z.tagName === 'BUTTON' || z.hasAttribute('data-fokus')).map(z => z.getAttribute('data-ue')).join(','));
        const hinweis = el ? [...el.querySelectorAll('.jv-gear-tip-hint')].map(h => h.textContent).join(' | ') : '';
        pruefe(/verschwinden von selbst/.test(hinweis) && /Integritätsprüfung anklicken/.test(hinweis),
               'Hinweis nennt beide Wirkungen (still / Sprung zur Integritaetspruefung)', hinweis);
        if (still[0]) still[0].dispatchEvent(new p.w.MouseEvent('click', { bubbles: true }));
        pruefe(!p.w.sessionStorage.getItem('jarvis_settings_tab'), 'ein Klick auf eine stille Zeile wechselt nirgendwohin');
        if (aide) aide.dispatchEvent(new p.w.MouseEvent('click', { bubbles: true }));
        pruefe(p.w.sessionStorage.getItem('jarvis_settings_tab') === 'profiles'
               && p.w.sessionStorage.getItem('jarvis_settings_focus') === 'pakete',
               'Klick auf die AIDE-Zeile: Reiter KI & System, Abschnitt Paket-Updates',
               JSON.stringify([p.w.sessionStorage.getItem('jarvis_settings_tab'), p.w.sessionStorage.getItem('jarvis_settings_focus')]));
        p.w.close();
    }
    {   // Fremdtext wird maskiert: unbekannte Art -> Servertext, und der ist roh
        const roh = JSON.parse(JSON.stringify(BADGE));
        roh.items = [{ art: 'ue', ue_art: 'gibt_es_nicht', stufe: 'warnung', titel: '<img src=x id=boese>',
                       werte: {}, ts: 0 }];
        roh.gesamt = 1; roh.ue_warnungen = 1;
        const p = await seite({ admin: true, badge: roh });
        const el = hover(p.w, p.d);
        const z = el && el.querySelector('.jv-gear-tip-row[data-ue]');
        pruefe(z && !p.d.getElementById('boese') && /<img src=x id=boese>/.test(z.textContent),
               'Servertext ohne Vorlage erscheint als TEXT, nicht als Markup', z && z.innerHTML.slice(0, 160));
        p.w.close();
    }
    {   // nur Warnungen: Warnfarbe
        const nurW = JSON.parse(JSON.stringify(BADGE));
        nurW.items = nurW.items.filter(i => i.art === 'ue' && i.stufe === 'warnung');
        nurW.ue_alarm = false; nurW.ssh_alarm = false; nurW.ssh_fehl = 0;
        nurW.ue_warnungen = nurW.items.length; nurW.gesamt = nurW.items.length;
        const p = await seite({ admin: true, badge: nurW });
        const b = gearBadge(p.d);
        pruefe(b && !b.classList.contains('is-danger'), 'nur Warnungen: die Badge bleibt in der Warnfarbe');
        p.w.close();
    }
    {   // Ziel von app.js: der Abschnitt existiert in settings.html
        const app = lies(path.join(ROOT, 'frontend/js/app.js'));
        const html = lies(path.join(ROOT, 'frontend/settings.html'));
        pruefe(/pakete:\s*\{\s*hdr:\s*'prof-sect-pakete-hdr',\s*body:\s*'prof-sect-pakete-body'\s*\}/.test(app)
               && /id="prof-sect-pakete-hdr"/.test(html) && /id="prof-sect-pakete-body"/.test(html),
               'app.js kennt den Abschnitt "pakete", und es gibt ihn in settings.html');
    }

    _bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => abbruch('Absturz: ' + (e && e.stack || e)));
