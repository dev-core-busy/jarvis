/* UI-Test: Telemetrie-Reiter (jsdom, echte settings.html + telemetry.js).
 *
 * Prueft, was sich am Quelltext NICHT ablesen laesst:
 *   1. Der Verlaufs-Inhalt wird ERST beim Aufklappen geholt (und nur einmal)
 *   2. Der vollstaendige Prompt landet sichtbar im DOM – nicht die Kurzform
 *   3. Ein Klick auf ein Leeren-× klappt den Abschnitt NICHT auf/zu
 *      (das ist der klassische Fehler: der Knopf sitzt IN der Kopfzeile, die
 *      selbst ein Klick-Ziel ist – ohne stopPropagation macht ein Klick beides)
 *   4. Jedes × ruft genau seinen eigenen Endpunkt
 *   5. Alt-Eintraege zeigen die Aufgabe trotz fehlendem task-Feld im Rumpf
 *   8. Kacheln, Tool-/LLM-Statistiken und Spans sind ENTFERNT (Vorgabe
 *      2026-09-28) – und werden auch nicht mehr abgerufen
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst halten Timer den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 60 node tests/test_telemetry_ui.js
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  [32m✓[0m ' : '  [31m✗[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n[1m' + t + '[0m'); }

// Der lange Prompt: genau das, was die alte Fassung auf 200/300 Zeichen kuerzte.
const LONG_TASK = 'Erstelle eine Auswertung: ' + 'FUELLDATEN-4711;'.repeat(400);
const LONG_SYS = 'Du bist Jarvis.\n' + 'Werkzeug: beispiel\n'.repeat(500);

const STATS = {
    agent_runs: 5, tool_calls: 12, llm_calls: 7, errors: 1, total_duration_ms: 9000,
    tool_stats: { shell_execute: { calls: 12, sample: 12, avg_ms: 5, min_ms: 1, max_ms: 9 } },
    llm_stats: { calls: 7, avg_ms: 100, min_ms: 10, max_ms: 300 },
    last_reset_ts: null, last_reset_by: '',
    area_resets: { errors: { ts: 1785000000, by: 'admin-x' } },
    span_count: 2, span_capacity: 1000,
};
const INDEX = [
    { id: 'neu1', ts: 1785858000, task: LONG_TASK, model: 'qwen', username: 'u1',
      client_ip: '10.0.0.1', client_type: 'browser', steps: 2, duration_ms: 500,
      error: null, msg_count: 2, sys_len: LONG_SYS.length },
    { id: 'alt1', ts: 1785000000, task: 'A'.repeat(200), task_truncated: true,
      legacy: true, model: 'gemini', username: 'u2', client_ip: '10.0.0.2',
      client_type: 'browser', steps: 1, duration_ms: 100, error: null, msg_count: 1 },
];
const BODIES = {
    neu1: {
        id: 'neu1', ts: 1785858000, task: LONG_TASK, system_prompt: LONG_SYS,
        messages: [
            { role: 'user', content: LONG_TASK },
            { role: 'tool', tool: 'shell_execute', content: 'X'.repeat(50),
              truncated: true, full_len: 1234567 },
        ],
    },
    // Alt-Rumpf OHNE task-Feld – so sieht ein migrierter Eintrag aus.
    alt1: {
        id: 'alt1', legacy: true, system_prompt: 'S'.repeat(500),
        system_prompt_truncated: true,
        messages: [{ role: 'user', content: 'F'.repeat(300) + '…', truncated: true }],
    },
};

const calls = [];        // jede fetch-Anfrage: {method, url}

function makeFetch() {
    return (url, opts) => {
        const method = (opts && opts.method) || 'GET';
        calls.push({ method, url: String(url) });
        const j = (data) => Promise.resolve({
            ok: true, status: 200, json: () => Promise.resolve(data),
        });
        if (url.startsWith('/api/telemetry/stats')) return j(STATS);
        if (url.startsWith('/api/telemetry/spans')) return j([
            { span_id: '1', name: 'agent:Haupt', kind: 'agent', duration_ms: 20, status: 'ok' },
        ]);
        if (url.startsWith('/api/telemetry/errors')) return j([]);
        if (url.startsWith('/api/logs/retention')) return j({
            days: 90, last_run_ts: 1785858000, removed: {},
            conv_log: { count: 2, oldest_ts: 1785000000, bytes: 4096 },
            audit_log: { lines: 1516, bytes: 664903 },
        });
        if (url.startsWith('/api/conv_log/ips')) return j(['10.0.0.1']);
        if (url.startsWith('/api/conv_log/users')) return j(['u1', 'u2']);
        const m = url.match(/^\/api\/conv_log\/([^?]+)$/);
        if (m) {
            const b = BODIES[decodeURIComponent(m[1])];
            return b ? j(b) : Promise.resolve({ ok: false, status: 404,
                json: () => Promise.resolve({}) });
        }
        if (url.startsWith('/api/conv_log')) return j(INDEX);
        return j({ ok: true, removed: 0 });
    };
}

(async () => {
    const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
    const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const { window } = dom;
    const doc = window.document;

    // Nur i18n.js + die Module des Reiters einspielen – app.js wuerde fremde
    // Poll-Timer starten und den Test unabhaengig vom Prueffall offen halten.
    // audit/sicherheitsprotokoll/protokolle: "Aktualisieren" laedt seit
    // 2026-10-20 auch deren geoeffnete Abschnitte (Abschnitt 9).
    for (const f of ['frontend/js/i18n.js', 'frontend/js/telemetry.js', 'frontend/js/audit.js',
                     'frontend/js/sicherheitsprotokoll.js', 'frontend/js/protokolle.js']) {
        // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
        // seit dem 2026-10-01 aus der gemeinsamen Quelle (frontend/js/sitzung.js)
        // und rufen sie beim LADEN auf. Jede echte Seite laedt sie als erstes
        // Skript. Ohne diese Zeile stirbt der Aufbau still: der Waechter endet mit
        // Exit 0 und MESSEN TUT ER NICHTS MEHR.
        window.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
        window.eval(fs.readFileSync(path.join(ROOT, f), 'utf8'));
    }
    window.fetch = makeFetch();
    window.localStorage.setItem('jarvis_token', 'tok');
    window.confirm = () => true;
    window.alert = () => {};
    if (!window.t) window.t = (k) => k;

    const mgr = window.telemetryManager;
    check('telemetryManager vorhanden', !!mgr);
    await mgr.init();
    await sleep(30);

    // ── 1) Aufbewahrungs-Hinweis ─────────────────────────────────────────────
    section('1) Aufbewahrungsfrist steht im Reiter');
    const ret = doc.getElementById('tele-retention-text');
    check('Frist-Hinweis gefuellt', ret && ret.textContent.length > 10,
        ret ? JSON.stringify(ret.textContent) : 'fehlt');
    check('Frist nennt 90 Tage', /90/.test(ret.textContent), ret.textContent);
    // "Jetzt bereinigen" ist seit 2026-10-20 entfernt (laeuft nach Start und taeglich)
    check('Knopf "Jetzt bereinigen" gibt es nicht mehr', !doc.getElementById('tele-retention-run'));
    check('Frist-Hinweis ohne Kalender-Emoji', !/\u{1F5D3}/u.test(ret.textContent), ret.textContent);
    // Keine Textzeichen als Symbole im Reiter (Regel: Symbole aus icons.js)
    const reiterHtml = doc.getElementById('settings-tab-telemetry').innerHTML;
    check('kein ⟳ / ↻ / 🗓 im Reiter', !/[\u27F3\u21BB]|\u{1F5D3}/u.test(reiterHtml));
    // Seit 2026-10-20 auch keine Emojis vor den Abschnittsnamen (Regel: keine Emojis).
    // Die Klapppfeile (.kb-folder-arrow, "▶") zaehlen laut Unicode ebenfalls als
    // Piktogramm, sind aber das Klappzeichen der ganzen Oberflaeche – erste
    // Fassung der Regel meldete genau sie.
    const kopie = doc.getElementById('settings-tab-telemetry').cloneNode(true);
    kopie.querySelectorAll('.kb-folder-arrow').forEach((el) => el.remove());
    const emo = kopie.textContent.match(/\p{Extended_Pictographic}/gu) || [];
    check('kein Emoji als Abschnittssymbol im Reiter', !emo.length, emo.join(' '));
    check('keine kb-folder-icon-Elemente mehr im Reiter', !kopie.querySelector('.kb-folder-icon'));
    const akt = doc.getElementById('btn-tele-refresh');
    check('Aktualisieren traegt das Symbol aus icons.js', !!(akt && akt.querySelector('svg.jv-ico-refresh')));
    check('… und der Text steht in eigenem span (Sprachwechsel loescht das Symbol nicht)',
        !!(akt && !akt.hasAttribute('data-i18n') && akt.querySelector('span[data-i18n="telemetry.refresh"]')));
    window.applyLang && window.applyLang();
    check('nach applyLang ist das Symbol noch da', !!(akt && akt.querySelector('svg.jv-ico-refresh')));

    // ── 2) Verlauf: Inhalt erst beim Aufklappen ──────────────────────────────
    section('2) Verlaufs-Inhalt wird erst beim Aufklappen geholt');
    await mgr._loadConvLog();
    await sleep(20);
    const bodyCallsBefore = calls.filter(c => /\/api\/conv_log\/(neu1|alt1)/.test(c.url)).length;
    check('Liste geladen, aber KEIN Rumpf abgerufen', bodyCallsBefore === 0,
        String(bodyCallsBefore));
    const rows = doc.querySelectorAll('#tele-convlog-body .conv-log-header');
    check('2 Kopfzeilen gerendert', rows.length === 2, String(rows.length));
    check('Kopfzeile traegt die Id', rows[0].dataset.convId === 'neu1',
        rows[0].dataset.convId);

    // Aufklappen
    rows[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    const wrap = rows[0].nextElementSibling;
    check('Bereich ist offen', wrap.style.display === 'block', wrap.style.display);
    check('genau EIN Rumpf-Abruf',
        calls.filter(c => c.url === '/api/conv_log/neu1').length === 1,
        String(calls.filter(c => c.url === '/api/conv_log/neu1').length));

    // ── 3) Vollstaendiger Prompt sichtbar ────────────────────────────────────
    section('3) Der vollstaendige Prompt steht im DOM');
    const txt = wrap.textContent;
    check('Aufgabe vollstaendig im DOM (nicht 200 Zeichen)',
        txt.includes(LONG_TASK), `DOM-Laenge ${txt.length}, Prompt ${LONG_TASK.length}`);
    check('Zeichenzahl der Aufgabe wird genannt', /6\.4k|6,4k/.test(txt) || /k /.test(txt),
        txt.slice(0, 120));
    check('System-Prompt vorhanden', txt.includes(LONG_SYS.slice(0, 200)));
    const pre = wrap.querySelectorAll('pre');
    check('System-Prompt startet EINGEKLAPPT',
        [...pre].some(p => p.style.display === 'none'),
        [...pre].map(p => p.style.display).join(','));
    const sysToggle = wrap.querySelector('.conv-sys-toggle');
    check('System-Prompt hat einen Umschalter', !!sysToggle);
    sysToggle.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    check('Umschalter klappt den System-Prompt auf',
        sysToggle.nextElementSibling.style.display === 'block',
        sysToggle.nextElementSibling.style.display);
    check('Kuerzung eines Tool-Ergebnisses wird AUSGEWIESEN',
        txt.includes('telemetry.truncated') || /gek(ue|ü)rzt|truncated/i.test(txt),
        'kein Hinweis');
    check('Originallaenge der Kuerzung genannt', /1234\.6k|1\.2M|1234/.test(txt),
        'keine Laenge');

    // Zweites Aufklappen darf nicht erneut abrufen
    rows[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(10);
    rows[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(20);
    check('Zu- und Aufklappen holt den Rumpf NICHT erneut',
        calls.filter(c => c.url === '/api/conv_log/neu1').length === 1,
        String(calls.filter(c => c.url === '/api/conv_log/neu1').length));

    // ── 4) Alt-Eintrag: Aufgabe kommt aus dem Index ──────────────────────────
    section('4) Alt-Eintrag zeigt die Aufgabe trotz fehlendem task im Rumpf');
    check('Alt-Eintrag traegt ein Abzeichen',
        rows[1].textContent.includes('telemetry.legacy_badge')
        || /Altbestand|legacy/i.test(rows[1].textContent), rows[1].textContent.slice(0, 200));
    rows[1].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    const altTxt = rows[1].nextElementSibling.textContent;
    check('Aufgabe des Alt-Eintrags wird angezeigt', altTxt.includes('A'.repeat(200)),
        `Laenge ${altTxt.length}`);
    check('und ist als gekuerzt gekennzeichnet',
        altTxt.includes('telemetry.truncated') || /gek(ue|ü)rzt|truncated/i.test(altTxt));

    // ── 5) Leeren-Knoepfe ────────────────────────────────────────────────────
    section('5) Jedes × leert genau seinen Abschnitt – und klappt nichts um');
    const CASES = [
        ['tele-errors-clear-btn', '/api/telemetry/errors', 'tele-errors-body'],
        ['conv-log-clear-btn', '/api/conv_log', 'tele-convlog-body'],
    ];
    for (const [btnId, url, bodyId] of CASES) {
        const btn = doc.getElementById(btnId);
        const secBody = doc.getElementById(bodyId);
        const displayBefore = secBody.style.display;
        const before = calls.length;
        btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        await sleep(40);
        const fresh = calls.slice(before);
        const del = fresh.filter(c => c.method === 'DELETE');
        check(`${btnId} sendet DELETE ${url}`,
            del.length === 1 && del[0].url === url,
            JSON.stringify(del));
        // Der Knopf sitzt IN der klickbaren Kopfzeile: ohne stopPropagation
        // wuerde derselbe Klick den Abschnitt auf-/zuklappen.
        check(`${btnId} klappt den Abschnitt NICHT um`,
            secBody.style.display === displayBefore,
            `${displayBefore} -> ${secBody.style.display}`);
        // Kein fremder Abschnitt darf mit-geleert werden
        check(`${btnId} loescht nichts anderes`, del.length === 1, JSON.stringify(del));
    }

    // Der globale Zuruecksetzen-Knopf ist ENTFERNT (Vorgabe 2026-10-20): er
    // leerte nur unsichtbare Zaehler und das Fehler-Log, versprach im Reiter
    // "Protokolle" aber, alles zurueckzusetzen. Abschnitt 8 prueft das.

    // ── 6) Nachweis "zuletzt geleert" ────────────────────────────────────────
    section('6) Hinweis "zuletzt geleert" je Abschnitt');
    doc.getElementById('tele-errors-body').style.display = 'block';
    await mgr._loadErrors();
    await sleep(20);
    check('Fehler-Log nennt den Nachweis (Stats werden dafuer weiter geholt)',
        /admin-x/.test(doc.getElementById('tele-errors-body').textContent),
        doc.getElementById('tele-errors-body').textContent.slice(-160));

    // ── 7) Mehrfaches init() bindet nicht doppelt ────────────────────────────
    section('7) init() ist idempotent (Reiter-Wechsel)');
    await mgr.init();
    await mgr.init();
    await sleep(20);
    const b2 = calls.length;
    doc.getElementById('tele-errors-clear-btn').dispatchEvent(
        new window.MouseEvent('click', { bubbles: true }));
    await sleep(40);
    const n = calls.slice(b2).filter(c => c.method === 'DELETE'
        && c.url === '/api/telemetry/errors').length;
    check('nach dreifachem init() genau EIN DELETE je Klick', n === 1, String(n));

    // ── 8) Entfernte Bereiche ────────────────────────────────────────────────
    section('8) Kacheln, Tool-/LLM-Statistiken, Letzte Spans: entfernt (Vorgabe 2026-09-28)');
    const tab = doc.getElementById('settings-tab-telemetry');
    check('(Positivkontrolle) Telemetrie-Reiter da, LLM-Verlauf und Fehler-Log stehen drin',
        !!tab && !!doc.getElementById('tele-convlog-body') && !!doc.getElementById('tele-errors-body'));
    for (const id of ['tele-stat-cards', 'tele-tool-section', 'tele-tool-body', 'tele-tool-clear-btn',
                      'tele-llm-body', 'tele-llm-clear-btn', 'tele-spans-body', 'tele-spans-clear-btn']) {
        check(`#${id} gibt es nicht mehr`, !doc.getElementById(id));
    }
    const tabTxt = tab ? tab.textContent : '';
    for (const w of ['Agent-Runs', 'Tool-Calls', 'LLM-Calls', 'Tool-Statistiken', 'LLM-Statistiken', 'Letzte Spans']) {
        check(`kein sichtbarer Text "${w}"`, tabTxt.indexOf(w) === -1);
    }
    const b3 = calls.length;
    await mgr.refresh();
    await sleep(30);
    const neu = calls.slice(b3).map(c => c.url);
    check('(Positivkontrolle) Aktualisieren holt weiter Stats und Aufbewahrung',
        neu.some(u => u.startsWith('/api/telemetry/stats')) && neu.some(u => u.startsWith('/api/logs/retention')),
        JSON.stringify(neu));
    check('⚠ Aktualisieren holt KEINE Spans mehr', !neu.some(u => u.startsWith('/api/telemetry/spans')),
        JSON.stringify(neu));
    // Bis 2026-10-20 stand hier "der Reset-Nachweis bleibt (Zuruecksetzen gibt
    // es weiter)" – die Festlegung vom 2026-09-28. Neue Vorgabe: beides weg.
    check('Knopf "Zuruecksetzen" gibt es nicht mehr (Vorgabe 2026-10-20)', !doc.getElementById('btn-tele-clear'));
    check('Kopfzeile "Zuletzt zurueckgesetzt" gibt es nicht mehr', !doc.getElementById('tele-reset-info'));
    check('kein sichtbarer Text "Zurücksetzen" / "zurückgesetzt" im Reiter',
        !/Zurücksetzen|zurückgesetzt/.test(tabTxt), tabTxt.match(/.{0,30}(Zurücksetzen|zurückgesetzt).{0,30}/) || '');
    check('Aktualisieren loest kein DELETE /api/telemetry aus',
        !calls.slice(b3).some(c => c.method === 'DELETE'), JSON.stringify(calls.slice(b3)));

    // ── 9) Aktualisieren laedt ALLE geoeffneten Abschnitte ──────────────────
    section('9) Aktualisieren: alle geoeffneten Abschnitte, keine zugeklappten');
    const auf = (id, ja) => { const b = doc.getElementById(id); if (b) b.style.display = ja ? 'block' : 'none'; return !!b; };
    check('(Positivkontrolle) Abschnitte im Markup',
        auf('audit-section-body', true) && auf('sprot-section-body', true)
        && auf('plog-ssh-body', true) && auf('plog-journal-body', false));
    const b4 = calls.length;
    doc.getElementById('btn-tele-refresh').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(80);
    const geholt = calls.slice(b4).map(c => c.url.split('?')[0]);
    for (const [pfad, was] of [['/api/audit_log', 'Tool-Audit-Log'], ['/api/security/log', 'Sicherheitsprotokoll'],
                               ['/api/logs/ssh', 'SSH-Anmeldungen'], ['/api/telemetry/stats', 'Fehler-Log/Stats']]) {
        check('geoeffnet und neu geladen: ' + was, geholt.includes(pfad), JSON.stringify(geholt));
    }
    check('zugeklappt bleibt zu und wird NICHT geladen: Dienst-Journal', !geholt.includes('/api/logs/journal'),
        JSON.stringify(geholt));

    // ── Ergebnis ─────────────────────────────────────────────────────────────
    const bad = results.filter(r => !r.ok);
    console.log(`\n[1mErgebnis: ${results.length - bad.length}/${results.length}[0m`);
    if (bad.length) {
        console.log('[31mFehlgeschlagen:[0m');
        bad.forEach(r => console.log('  - ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    window.close();
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
