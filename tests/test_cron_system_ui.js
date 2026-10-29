/* UI-Test: Eintrag "Automatische Sicherheitsupdates" in der Auftragsliste
 * (frontend/js/cron.js _loadSystem/_renderSystem) – jsdom, echte Datei.
 *
 * DER GEMELDETE FALL (2026-10-29): "wie genau laeuft auf ECHT debian update
 * (unter 'task' finde ich nichts passendes dazu)". Debians unattended-upgrades
 * laeuft ueber einen systemd-Timer und bleibt dort; die Liste ZEIGT ihn nur.
 *
 * Geprueft wird die Wirkung am DOM:
 *   - der Eintrag steht AUSSERHALB von #cron-list (die Auftragszaehlung und
 *     jedes Neuzeichnen bleiben unberuehrt) und hat KEIN Bearbeiten/Loeschen/
 *     Ausfuehren/Schalter – er ist kein Auftrag;
 *   - ein Abruffehler oder fehlende Felder werden NICHT zu "ausgeschaltet";
 *   - "dabei eingespielt" nur fuer Eintraege nach dem letzten Timer-Lauf;
 *   - ein nicht lesbarer Verlauf ist nicht "nichts eingespielt";
 *   - das Neuzeichnen der Liste (nach jedem Lauf) ruft den Status NICHT neu ab.
 * Antwortform wie GET /api/security/unattended (backend/apt_upgrades.status).
 *
 * Lauf:  timeout 60 node tests/test_cron_system_ui.js [pfad/zu/cron.js]
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
 */
'use strict';

require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const SRC = fs.readFileSync(process.argv[2] || path.join(ROOT, 'frontend', 'js', 'cron.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'i18n.js'), 'utf8');

const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const PLATZHALTER = {};
for (const m of I18N.matchAll(/^\s*'([a-z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)'/gm)) {
    if (!(m[1] in PLATZHALTER)) PLATZHALTER[m[1]] = m[2].match(/\{\w+\}/g) || [];
}

const JOBS = [{ id: 'a1', label: 'Erste', cron: '0 7 * * *', task: 'Bericht A', enabled: true }];
const LETZTER = 1793250579.98;      // Timer-Lauf
const ST = (o) => Object.assign({
    package_installed: true, update_lists: '1', unattended: '1', limits_ok: true,
    origins: ['origin=Debian,codename=trixie-security,label=Debian-Security'],
    timers: { 'apt-daily.timer': true, 'apt-daily-upgrade.timer': true },
    last_run: '', dry_run: null, security_only: null, enabled: true, ok: true,
    zeitplan: { naechster: LETZTER + 86400, letzter: LETZTER, ergebnis: 'success', exit: 0 },
    eingespielt: [
        { start: LETZTER + 7, ende: LETZTER + 12, fehler: '',
          pakete: [{ name: 'openjdk-21-jre-headless', von: '21.0.12', nach: '21.0.13', neu: false }] },
        { start: LETZTER - 86400, ende: LETZTER - 86390, fehler: '',
          pakete: [{ name: 'thunderbird', von: '1:140', nach: '1:153', neu: false },
                   { name: 'lib<script>x()</script>', von: '1', nach: '2', neu: false }] },
    ],
}, o || {});

function baue(opt) {
    const o = Object.assign({ status: ST(), code: 200, reiter: true }, opt || {});
    const dom = new JSDOM('<!doctype html><html><body>'
        + (o.reiter ? '<button class="settings-tab-btn" data-settings-tab="security">S</button>' : '')
        + '<div id="cron-tab-content"></div></body></html>',
        { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const { window } = dom;
    const rufe = [];
    window.t = (k) => k + (PLATZHALTER[k] || []).map(x => ' ' + x).join('');
    window.jarvisMarke = () => 'Fabrikam';
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8'));
    window.confirm = () => true;
    window.fetch = function (url, init) {
        const p = String(url).split('?')[0];
        const m = ((init && init.method) || 'GET').toUpperCase();
        rufe.push({ p, m });
        const j = (b, st) => Promise.resolve({ ok: (st || 200) < 400, status: st || 200, json: () => Promise.resolve(b) });
        if (p === '/api/cron' && m === 'GET') return j(JOBS);
        if (p === '/api/watchers') return j([]);
        if (p === '/api/security/unattended') return j(o.status, o.code);
        return j({ ok: true });
    };
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8'));
    window.eval(SRC);
    return { window, doc: window.document, rufe };
}

const eintrag = (doc) => doc.querySelector('#cron-system .cron-item');
const meta = (doc) => { const e = eintrag(doc); return e ? e.querySelector('.cron-item-meta').textContent : ''; };
const statusRufe = (rufe) => rufe.filter(r => r.p === '/api/security/unattended').length;

async function aufbau(opt) {
    const b = baue(opt);
    b.window.cronManager.init();
    await sleep(40);
    return b;
}

(async () => {
    try {
        let { window, doc, rufe } = await aufbau();
        // Positivkontrolle: Liste UND Eintrag stehen – sonst ist alles unten trivial.
        if (doc.querySelectorAll('#cron-list .cron-item').length !== JOBS.length || !eintrag(doc)) {
            console.log('ABBRUCH: Liste oder Systemeintrag nicht gerendert'); window.close(); process.exit(2);
        }

        section('1. Kein Auftrag – nur Anzeige');
        check('Eintrag steht AUSSERHALB von #cron-list', !doc.querySelector('#cron-list .cron-item-system'));
        check('Auftragszahl in #cron-list unveraendert', doc.querySelectorAll('#cron-list .cron-item').length === JOBS.length);
        const e = eintrag(doc);
        check('⚠ kein Bearbeiten/Loeschen/Ausfuehren/Schalter/Uebernehmen',
            !e.querySelector('.cron-edit-btn, .cron-del-btn, .cron-run-btn, .cron-toggle, .cron-claim-btn, input'));
        check('Beschriftung und Timer-Kennzeichen', e.querySelector('.cron-item-label').textContent === 'cron.sys_label'
            && e.querySelector('.cron-item-code').textContent === 'cron.sys_timer');
        check('{marke} im Tooltip ersetzt', /Fabrikam/.test(e.querySelector('.cron-item-code').getAttribute('data-tip'))
            && !/\{marke\}/.test(e.innerHTML));

        section('2. Zustand eingeschaltet');
        check('Punkt aktiv', e.querySelector('.cron-item-dot').classList.contains('active'));
        check('kein Warn-Etikett', e.querySelectorAll('.cron-badge-none').length === 0);
        const zeitL = new Date(LETZTER * 1000).toLocaleString('de-DE');
        const zeitN = new Date((LETZTER + 86400) * 1000).toLocaleString('de-DE');
        check('letzter Lauf mit Zeit und Ergebnis', meta(doc).includes('cron.last_run: ' + zeitL + ' · cron.log_ok'), meta(doc));
        check('naechster Lauf', meta(doc).includes('cron.sys_naechster: ' + zeitN), meta(doc));
        check('⚠ "dabei eingespielt" zaehlt NUR Eintraege nach dem Timer-Lauf (1 Paket, openjdk)',
            meta(doc).includes('cron.sys_dabei 1: openjdk-21-jre-headless') && !meta(doc).includes('thunderbird'), meta(doc));

        section('3. Protokoll');
        const lb = e.querySelector('.cron-sys-log-btn');
        const box = () => doc.querySelector('#cron-system .cron-sys-log');
        check('Protokoll zu', box().hidden === true && lb.getAttribute('aria-expanded') === 'false');
        const vorher = rufe.length;
        lb.click();
        await sleep(20);
        check('Protokoll offen', box().hidden === false && doc.querySelector('#cron-system .cron-sys-log-btn').getAttribute('aria-expanded') === 'true');
        check('ein Eintrag je Einspielung', box().querySelectorAll('.cron-log-eintrag').length === 2);
        check('Versionen alt → neu stehen da', /1:140 → 1:153/.test(box().textContent), box().textContent);
        check('⚠ Paketname escaped (kein <script>-Element)', !box().querySelector('script')
            && /lib<script>/.test(box().textContent));
        check('Aufklappen ruft nichts ab (Daten liegen vor)', rufe.length === vorher);
        check('letzter Lauf HAT eingespielt -> keine eigene Laufzeile (steht als Eintrag da)',
            !box().querySelector('.cron-sys-lauf'));

        section('4. Neuzeichnen der Liste');
        const n0 = statusRufe(rufe);
        await window.cronManager._loadJobs();
        await sleep(20);
        check('⚠ _loadJobs (nach jedem Lauf) ruft den Status NICHT neu ab', statusRufe(rufe) === n0, statusRufe(rufe));
        check('Eintrag steht danach noch, Protokoll noch offen', !!eintrag(doc) && box() && box().hidden === false);
        doc.getElementById('cron-refresh-btn').click();
        await sleep(30);
        check('Aktualisieren-Knopf ruft ihn neu ab', statusRufe(rufe) === n0 + 1);

        section('5. Einstellungen-Knopf');
        let geklickt = 0;
        doc.querySelector('.settings-tab-btn[data-settings-tab="security"]').addEventListener('click', () => geklickt++);
        doc.querySelector('#cron-system .cron-sys-einst-btn').click();
        check('oeffnet den Reiter Sicherheit', geklickt === 1);
        window.close();
        ({ window, doc } = await aufbau({ reiter: false }));
        check('ohne Reiter kein toter Knopf', !doc.querySelector('#cron-system .cron-sys-einst-btn'));
        window.close();

        section('6. Abweichende Zustaende');
        ({ window, doc } = await aufbau({ status: { ok: false, error: 'Broker nicht erreichbar' }, code: 502 }));
        check('⚠ Abruffehler -> Fehlertext, NICHT "ausgeschaltet"',
            meta(doc).includes('cron.sys_fehler Broker nicht erreichbar') && !meta(doc).includes('cron.sys_aus'), meta(doc));
        check('Abruffehler: kein "Letzter Lauf" erfunden', !meta(doc).includes('cron.last_run'));
        window.close();

        ({ window, doc } = await aufbau({ status: { ok: true } }));
        check('⚠ fehlende Felder -> "unbekannt", NICHT "ausgeschaltet"',
            meta(doc).includes('cron.sys_unbekannt') && !meta(doc).includes('cron.sys_aus'), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ enabled: false, ok: false, unattended: '0' }) }));
        check('ausgeschaltet: Etikett und inaktiver Punkt', meta(doc).includes('cron.sys_aus')
            && eintrag(doc).querySelector('.cron-item-dot').classList.contains('inactive'), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ ok: false }) }));
        check('eingeschaltet, aber unvollstaendig', meta(doc).includes('cron.sys_unvollstaendig'), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ eingespielt: null }) }));
        check('⚠ Verlauf unlesbar -> eigener Text, NICHT "nichts eingespielt"',
            meta(doc).includes('cron.sys_verlauf_unlesbar') && !meta(doc).includes('cron.sys_nie_eingespielt')
            && !meta(doc).includes('cron.sys_dabei_nichts'), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ eingespielt: ST().eingespielt.slice(1) }) }));
        const zeitA = new Date((LETZTER - 86400) * 1000).toLocaleString('de-DE');
        check('letzter Lauf ohne Einspielung -> "nichts" + wann zuletzt',
            meta(doc).includes('cron.sys_dabei_nichts · cron.sys_zuletzt ' + zeitA), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ eingespielt: [] }) }));
        check('nie etwas eingespielt', meta(doc).includes('cron.sys_nie_eingespielt'), meta(doc));
        window.close();

        ({ window, doc } = await aufbau({ status: ST({ zeitplan: { naechster: null, letzter: null, ergebnis: 'success', exit: 0 } }) }));
        check('unbekannte Zeiten als "—", kein Ergebnis ohne Lauf, kein "dabei"',
            meta(doc).includes('cron.last_run: — · cron.sys_naechster: —') && !meta(doc).includes('cron.log_ok')
            && !meta(doc).includes('cron.sys_dabei'), meta(doc));
        window.close();

        section('7. Letzter Lauf im Protokoll (Vorgabe 2026-10-29)');
        const oeffne = async (st) => {
            const b = await aufbau({ status: st });
            b.doc.querySelector('#cron-system .cron-sys-log-btn').click();
            await sleep(20);
            return b;
        };
        const erste = (d) => d.querySelector('#cron-system .cron-sys-log .cron-log-eintrag');
        ({ window, doc } = await oeffne(ST({ eingespielt: ST().eingespielt.slice(1) })));
        let z = erste(doc);
        check('⚠ Lauf ohne Einspielung steht OBEN im Protokoll',
            z && z.classList.contains('cron-sys-lauf') && z.classList.contains('ok')
            && z.textContent.includes(new Date(LETZTER * 1000).toLocaleString('de-DE'))
            && z.textContent.includes('cron.sys_lauf_nichts'), z && z.textContent);
        check('darunter die Einspielungen', doc.querySelectorAll('#cron-system .cron-log-eintrag').length === 2);
        window.close();
        ({ window, doc } = await oeffne(ST({ eingespielt: [],
            zeitplan: { naechster: LETZTER + 86400, letzter: LETZTER, ergebnis: 'exit-code', exit: 1 } })));
        z = erste(doc);
        check('gescheiterter Lauf: Fehler-Status und Grund', z && z.classList.contains('fehler')
            && z.textContent.includes('exit-code') && z.textContent.includes('Exit 1'), z && z.textContent);
        check('und trotzdem der Hinweis "nie eingespielt"', !!doc.querySelector('#cron-system .cron-sys-log .cron-log-leer'));
        window.close();
        ({ window, doc } = await oeffne(ST({ eingespielt: null })));
        check('Verlauf unlesbar: Laufzeile UND Fehlermeldung', !!doc.querySelector('#cron-system .cron-sys-lauf')
            && !!doc.querySelector('#cron-system .cron-sys-log .cron-log-fehlermeldung'));
        window.close();
        ({ window, doc } = await oeffne(ST({ zeitplan: { naechster: null, letzter: null, ergebnis: 'success', exit: 0 } })));
        check('letzter Lauf unbekannt -> keine erfundene Laufzeile', !doc.querySelector('#cron-system .cron-sys-lauf'));
        window.close();

        section('8. Texte');
        const benutzt = [...new Set([...SRC.matchAll(/'(cron\.sys_[a-z_]+)'/g)].map(m => m[1]))];
        const de = I18N.slice(0, I18N.search(/^\s*en\s*:\s*\{/m) > 0 ? I18N.search(/^\s*en\s*:\s*\{/m) : I18N.length);
        const zaehl = (k) => (I18N.match(new RegExp("^\\s*'" + k.replace(/\./g, '\\.') + "':", 'gm')) || []).length;
        check('Positivkontrolle: Schluessel aus dem Quelltext gelesen', benutzt.length >= 15, benutzt.length);
        const fehlend = benutzt.filter(k => zaehl(k) !== 2);
        check('jeder cron.sys_*-Schluessel steht genau zweimal (DE + EN)', !fehlend.length, fehlend.join(', '));
        check('DE-Texte nennen keine Technik (unattended, systemd, apt)',
            !benutzt.some(k => { const m = de.match(new RegExp("'" + k.replace(/\./g, '\\.') + "':\\s*'([^']*)'"));
                                  return m && /unattended|systemd|\bapt\b/i.test(m[1]); }));
    } catch (e) {
        console.log('ABBRUCH: ' + (e && e.stack || e));
        process.exit(2);
    }
    const ok = results.filter(r => r.ok).length;
    console.log(`\n\x1b[1mErgebnis: ${ok}/${results.length}\x1b[0m`);
    process.exit(ok === results.length ? 0 : 1);
})();
