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
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst halten Timer den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 60 node tests/test_telemetry_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

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
    area_resets: { spans: { ts: 1785000000, by: 'admin-x' } },
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

    // Nur i18n.js + telemetry.js einspielen – app.js wuerde fremde Poll-Timer
    // starten und den Test unabhaengig vom Prueffall offen halten.
    for (const f of ['frontend/js/i18n.js', 'frontend/js/telemetry.js']) {
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
    check('Bereinigen-Knopf sichtbar bei Frist > 0',
        doc.getElementById('tele-retention-run').style.display !== 'none');

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
        ['tele-tool-clear-btn', '/api/telemetry/tool_stats', 'tele-tool-body'],
        ['tele-llm-clear-btn', '/api/telemetry/llm_stats', 'tele-llm-body'],
        ['tele-errors-clear-btn', '/api/telemetry/errors', 'tele-errors-body'],
        ['tele-spans-clear-btn', '/api/telemetry/spans', 'tele-spans-body'],
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

    // Der globale Zuruecksetzen-Knopf bleibt daneben bestehen
    const before = calls.length;
    doc.getElementById('btn-tele-clear').dispatchEvent(
        new window.MouseEvent('click', { bubbles: true }));
    await sleep(40);
    const globalDel = calls.slice(before).filter(c => c.method === 'DELETE');
    check('Zuruecksetzen sendet DELETE /api/telemetry',
        globalDel.length === 1 && globalDel[0].url === '/api/telemetry',
        JSON.stringify(globalDel));

    // ── 6) Nachweis "zuletzt geleert" ────────────────────────────────────────
    section('6) Hinweis "zuletzt geleert" je Abschnitt');
    doc.getElementById('tele-spans-body').style.display = 'block';
    await mgr._loadSpans();
    await sleep(20);
    check('Span-Abschnitt nennt den Nachweis',
        /admin-x/.test(doc.getElementById('tele-spans-body').textContent),
        doc.getElementById('tele-spans-body').textContent.slice(-160));
    check('Tool-Abschnitt OHNE Nachweis zeigt keinen',
        !/admin-x/.test(doc.getElementById('tele-tool-body').textContent));

    // ── 7) Mehrfaches init() bindet nicht doppelt ────────────────────────────
    section('7) init() ist idempotent (Reiter-Wechsel)');
    await mgr.init();
    await mgr.init();
    await sleep(20);
    const b2 = calls.length;
    doc.getElementById('tele-spans-clear-btn').dispatchEvent(
        new window.MouseEvent('click', { bubbles: true }));
    await sleep(40);
    const n = calls.slice(b2).filter(c => c.method === 'DELETE'
        && c.url === '/api/telemetry/spans').length;
    check('nach dreifachem init() genau EIN DELETE je Klick', n === 1, String(n));

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
