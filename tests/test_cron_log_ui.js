/* UI-Test: Protokoll je Cron-Aufgabe (frontend/js/cron.js) – jsdom, echte Datei.
 *
 * DER GEMELDETE FALL (2026-09-28): "bei den Tasks -> Cron-Aufgaben fehlen
 * logs". Jede Aufgabe hat jetzt einen Knopf "Protokoll", der ihre Laeufe
 * aufklappt (GET /api/cron/{id}/log, Antwortform wie backend/main.py:
 * {ok, eintraege:[{ts, ende, dauer_s, ausloeser, von, label, kind, ok,
 * ergebnis, gekuerzt}], mehr}).
 *
 * Geprueft wird GEKLICKT: was aufgeht, was abgerufen wird, was dasteht – und
 * dass ein offenes Protokoll das Neuzeichnen der Liste ueberlebt (das passiert
 * nach JEDEM Lauf, beim Wissensabgleich alle fuenf Minuten).
 *
 * ⚠ jsdom fehlt -> Exit 2.
 * Lauf:  timeout 60 node tests/test_cron_log_ui.js
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const SRC = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'cron.js'), 'utf8');
const JOBS = [
    { id: 'a1', label: 'Erste', cron: '0 7 * * *', task: 'Bericht A', enabled: true },
    { id: 'b2', label: 'Zweite', cron: '0 8 * * *', task: 'Bericht B', enabled: true },
];
const T0 = 1790000000;
const ein = (i, o) => Object.assign({ ts: T0 - i * 3600, ende: T0 - i * 3600 + 3, dauer_s: 3.2,
    ausloeser: 'zeitplan', von: '', label: 'Erste', kind: 'agent', ok: true,
    ergebnis: 'Lauf ' + i + '\nzweite Zeile', gekuerzt: false }, o || {});
// 50 neueste + 5 aeltere
const LOG = { a1: Array.from({ length: 55 }, (_, i) => ein(i)), b2: [] };
LOG.a1[0] = ein(0, { ok: false, ergebnis: 'Fehler: <script>x()</script> kaputt' });
LOG.a1[1] = ein(1, { ausloeser: 'manuell', von: 'm.mustermann', dauer_s: 125 });

// Platzhalter je Schluessel aus dem ECHTEN i18n.js (erste Fundstelle = DE)
const PLATZHALTER = {};
for (const m of fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8')
                   .matchAll(/^\s*'([a-z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)'/gm)) {
    if (!(m[1] in PLATZHALTER)) PLATZHALTER[m[1]] = m[2].match(/\{\w+\}/g) || [];
}

function baue(opt) {
    const o = Object.assign({ logFehler: false }, opt || {});
    const dom = new JSDOM('<!doctype html><html><body><div id="cron-tab-content"></div></body></html>',
                          { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const { window } = dom;
    const rufe = [];
    // window.t in ECHTER Signatur (EIN Argument, Code-Review 2026-10-07): die
    // fruehere Attrappe nahm ein Platzhalter-Objekt an, das das Original
    // ignoriert – so stand "{e}" woertlich in der Oberflaeche, und dieser
    // Test war gruen. Jetzt: der Schluessel plus die Platzhalter des echten
    // deutschen Textes, damit eine Ersetzung messbar ist.
    window.t = (k) => k + (PLATZHALTER[k] || []).map(x => ' ' + x).join('');
    /* Das ECHTE icons.js, keine Attrappe. Vorher stand hier
     * `{ trash: () => '<svg></svg>' }` - eine Attrappe, die WENIGER anbietet
     * als das Original. Als `_renderJobList` am 2026-10-06 auf
     * `JarvisIcons.pencil()` umgestellt wurde, warf sie mitten im Rendern; der
     * Wurf landete im catch, und der Waechter brach mit "Liste nicht
     * gerendert" ab - OHNE Bilanzzeile, also von "nicht gelaufen" nicht zu
     * unterscheiden. Mit der echten Datei kann das nicht wieder passieren. */
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8'));
    window.confirm = () => true;
    window.fetch = function (url, init) {
        const u = String(url), p = u.split('?')[0], q = u.split('?')[1] || '';
        const m = ((init && init.method) || 'GET').toUpperCase();
        rufe.push({ p, q, m });
        const j = (b, st) => Promise.resolve({ ok: (st || 200) < 400, status: st || 200, json: () => Promise.resolve(b) });
        if (p === '/api/cron' && m === 'GET') return j(JOBS);
        if (p === '/api/watchers') return j([]);
        const lm = p.match(/^\/api\/cron\/([^/]+)\/log$/);
        if (lm) {
            if (o.logFehler) return j({ ok: false, error: 'Protokoll nicht lesbar: kaputt' }, 500);
            const alle = LOG[decodeURIComponent(lm[1])] || [];
            const lim = Number((q.match(/limit=(\d+)/) || [])[1] || 50);
            const vor = (q.match(/vor=([\d.]+)/) || [])[1];
            const fil = vor ? alle.filter(e => e.ts < Number(vor)) : alle;
            const teil = fil.slice(0, lim);
            return j({ ok: true, eintraege: teil, mehr: teil.length >= lim });
        }
        return j({ ok: true });
    };
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle (frontend/js/sitzung.js)
    // und rufen sie beim LADEN auf. Jede echte Seite laedt sie als erstes
    // Skript. Ohne diese Zeile stirbt der Aufbau still: der Waechter endet mit
    // Exit 0 und MESSEN TUT ER NICHTS MEHR.
    window.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    window.eval(SRC);
    return { window, doc: window.document, rufe };
}

const item = (doc, id) => [...doc.querySelectorAll('#cron-list .cron-item')].find(e => e.dataset.id === id) || null;
const box = (doc, id) => { const it = item(doc, id); return it ? it.querySelector('.cron-log') : null; };
const knopf = (doc, id) => { const it = item(doc, id); return it ? it.querySelector('.cron-log-btn') : null; };

(async () => {
    try {
        let { window, doc, rufe } = baue();
        const cm = window.cronManager;
        cm.init();
        await sleep(50);
        if (doc.querySelectorAll('#cron-list .cron-item').length !== JOBS.length) {
            console.log('ABBRUCH: Liste nicht gerendert'); window.close(); process.exit(2);
        }

        section('1. Grundzustand');
        check('jede Aufgabe hat einen Knopf "Protokoll"', JOBS.every(j => knopf(doc, j.id)
            && knopf(doc, j.id).textContent === 'cron.log_btn'));
        check('Protokoll ist zu', box(doc, 'a1') && box(doc, 'a1').hidden === true);
        check('und es wurde NICHTS abgerufen', !rufe.some(r => /\/log$/.test(r.p)));

        section('2. Aufklappen');
        knopf(doc, 'a1').click();
        await sleep(40);
        const b = box(doc, 'a1');
        check('⚠ Protokoll ist offen', b && b.hidden === false);
        check('Knopf meldet aria-expanded=true', knopf(doc, 'a1').getAttribute('aria-expanded') === 'true');
        check('⚠ genau der eigene Endpunkt wird abgerufen',
            rufe.filter(r => /\/log$/.test(r.p)).map(r => r.p).join() === '/api/cron/a1/log', JSON.stringify(rufe.filter(r => /log/.test(r.p))));
        const zeilen = b.querySelectorAll('.cron-log-eintrag');
        check('50 Laeufe stehen da (die erste Seite)', zeilen.length === 50, String(zeilen.length));
        check('neueste zuerst (Reihenfolge des Servers)', zeilen[0].dataset.ts === String(T0));
        check('⚠ Fehler als TEXT und Klasse', zeilen[0].classList.contains('fehler')
            && /cron\.log_err/.test(zeilen[0].querySelector('.cron-log-status').textContent));
        check('Erfolg als Text und Klasse', zeilen[2].classList.contains('ok')
            && /cron\.log_ok/.test(zeilen[2].querySelector('.cron-log-status').textContent));
        check('⚠ von Hand gestartet: mit Person', /cron\.log_manual · m\.mustermann/.test(zeilen[1].textContent), zeilen[1].textContent);
        check('Zeitplan-Lauf als solcher benannt', /cron\.log_schedule/.test(zeilen[2].textContent));
        check('Dauer lesbar (125 s -> 2,1 min; 3,2 s)', /2,1 min/.test(zeilen[1].textContent) && /3,2 s/.test(zeilen[2].textContent));
        check('Kurzfassung = erste Zeile', zeilen[2].querySelector('.cron-log-kurz').textContent === 'Lauf 2…',
            zeilen[2].querySelector('.cron-log-kurz').textContent);
        check('⚠ volles Ergebnis mit Zeilenumbruch im <pre>',
            zeilen[2].querySelector('.cron-log-voll').textContent === 'Lauf 2\nzweite Zeile');
        check('⚠ Ergebnistext wird NICHT als Markup eingesetzt',
            !b.querySelector('script') && /<script>/.test(zeilen[0].querySelector('.cron-log-voll').textContent));
        check('Knopf "Ältere" angeboten', !!b.querySelector('.cron-log-mehr'));

        section('3. Ältere nachladen');
        b.querySelector('.cron-log-mehr').click();
        await sleep(40);
        const nach = rufe.filter(r => /\/log$/.test(r.p)).pop();
        check('⚠ Nachladen fragt nach "vor" = Beginn des aeltesten angezeigten Laufs',
            nach && nach.q.indexOf('vor=' + (T0 - 49 * 3600)) !== -1, nach ? nach.q : 'kein Ruf');
        const z2 = box(doc, 'a1').querySelectorAll('.cron-log-eintrag');
        check('alle 55, ohne Doppelte', z2.length === 55
            && new Set([...z2].map(x => x.dataset.ts)).size === 55, String(z2.length));

        section('4. Neuzeichnen der Liste (nach jedem Lauf)');
        z2[2].open = true;
        const vorher = rufe.length;
        await cm._loadJobs();
        await sleep(40);
        check('⚠ Protokoll bleibt offen', box(doc, 'a1') && box(doc, 'a1').hidden === false);
        check('…und wird frisch abgerufen', rufe.slice(vorher).some(r => r.p === '/api/cron/a1/log'));
        const z3 = box(doc, 'a1').querySelectorAll('.cron-log-eintrag');
        check('ein aufgeklappter Eintrag bleibt aufgeklappt',
            [...z3].some(x => x.dataset.ts === z2[2].dataset.ts && x.open));
        check('das andere Protokoll bleibt zu', box(doc, 'b2').hidden === true);

        section('5. Zuklappen, leer');
        knopf(doc, 'a1').click();
        check('zu', box(doc, 'a1').hidden === true && knopf(doc, 'a1').getAttribute('aria-expanded') === 'false');
        knopf(doc, 'b2').click();
        await sleep(40);
        check('Aufgabe ohne Laeufe: "noch kein Lauf"', /cron\.log_none/.test(box(doc, 'b2').textContent));
        check('kein "Ältere"-Knopf ohne weitere', !box(doc, 'b2').querySelector('.cron-log-mehr'));
        window.close();

        section('6. Protokoll nicht lesbar');
        ({ window, doc, rufe } = baue({ logFehler: true }));
        window.cronManager.init();
        await sleep(50);
        knopf(doc, 'a1').click();
        await sleep(40);
        const t = box(doc, 'a1').textContent;
        check('⚠ Fehler wird genannt (mit Grund)', /cron\.log_load_err/.test(t) && /kaputt/.test(t), t);
        check('⚠ und NICHT als "noch kein Lauf" ausgegeben', !/cron\.log_none/.test(t));
        window.close();
    } catch (e) {
        console.error('ABGEBROCHEN:', e && e.stack || e);
        results.push({ name: 'Abbruch', ok: false });
    }
    const bad = results.filter(r => !r.ok);
    console.log(`\n\x1b[1mErgebnis: ${results.length - bad.length}/${results.length}\x1b[0m`);
    process.exit(bad.length ? 1 : 0);
})();
