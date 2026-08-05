/* UI-Test: Audit-Log-Filter + Verschiebung der Komprimierungs-Schwelle
 * (jsdom, echte settings.html / audit.js / app.js / i18n.js).
 *
 * Teil 1 – der gemeldete Fall vom 2026-08-05: im Audit-Log stand
 * „andreas.bender" im Benutzer-Feld, die Liste zeigte aber Eintraege von
 * „nexus\rene.pfeiffer". Der Backend-Filter war korrekt (live nachgewiesen);
 * geschrieben hatte den Namen **Chrome per Autofill**, ohne ein Laden
 * auszuloesen. Die Liste gehoerte also noch zum ungefilterten Abruf – und die
 * Anzeige behauptete dazu nichts. Geprueft wird deshalb:
 *   1. die Felder wehren Autofill ab (autocomplete/name)
 *   2. der Zaehler nennt IMMER den wirklich angewandten Filter
 *   3. weicht der Feldinhalt davon ab, sagt die Anzeige es ausdruecklich
 *   4. „Anwenden"/Enter filtern tatsaechlich (URL + gerenderte Zeilen)
 *   5. ein Ladefehler laesst den angewandten Filter unveraendert
 *
 * Teil 2 – „Kontext / History" ist aus dem Telemetrie-Reiter entfernt; die
 * einzige echte Einstellung darin (Komprimierungs-Schwelle) steht jetzt unter
 * „KI & System -> System-Einstellungen". Geprueft wird, dass das Feld dort
 * liegt, aus /api/settings vorbelegt wird und ueber
 * POST /api/context/threshold speichert (NICHT ueber /api/settings – nur der
 * Kontext-Endpunkt setzt auch den laufenden Hauptagenten).
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst halten die Poll-Timer aus app.js den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 90 node tests/test_audit_ctx_ui.js
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
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');

// ── Audit-Eintraege wie auf ECHT: zwei Benutzer, einer davon der gemeldete ──
const AUDIT = [
    { ts: 1786000000, user: 'nexus\\rene.pfeiffer', tool: 'memory_manage',
      args: { action: 'save', key: 'strategie' }, result_len: 851, duration_ms: 0 },
    { ts: 1785999999, user: 'nexus\\rene.pfeiffer', tool: 'shell_execute',
      args: { command: 'grep -i "PLZ" /tmp/KIS_TABLE.yaml' }, result_len: 132, duration_ms: 1 },
    { ts: 1785999998, user: 'nexus\\andreas.bender', tool: 'knowledge_search',
      args: { query: 'Urlaubsantrag' }, result_len: 2048, duration_ms: 40 },
];

let auditCalls = [];
let auditFail = false;

/** Mock mit der Filter-Logik des Backends (audit_log.read_log): Teilstring,
 *  ohne Gross-/Kleinschreibung. Ein Mock, der NICHT filtert, wuerde den Test
 *  gruen faerben, ohne die Filterung zu pruefen. */
function auditFetch(url, opts) {
    const method = (opts && opts.method) || 'GET';
    auditCalls.push({ method, url: String(url) });
    if (auditFail) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const q = new URL('https://x' + url).searchParams;
    const fu = (q.get('user') || '').toLowerCase();
    const ft = (q.get('tool') || '').toLowerCase();
    const out = AUDIT.filter(e =>
        (!fu || e.user.toLowerCase().includes(fu)) &&
        (!ft || e.tool.toLowerCase().includes(ft)));
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(out) });
}

// ── Mock fuer app.js (Teil 2) ────────────────────────────────────────────────
let appCalls = [];
let thresholdStatus = 200;
const SETTINGS = {
    active_profile_id: 'p1',
    profiles: [{ id: 'p1', name: 'Test', provider: 'gemini', model: 'x', api_key: '***' }],
    defaults: {}, tts_enabled: false, tts_voice: '', use_physical_desktop: false,
    llm_timeout: 180, llm_reasoning_effort: '', llm_max_tokens: 8192,
    docs_retention_days: 30, compress_threshold: 42,
    agent_api_key: '***', reasoning_effort_values: ['', 'low', 'high'],
};

function appFetch(url, opts) {
    const method = (opts && opts.method) || 'GET';
    const u = String(url);
    let body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = opts.body; }
    appCalls.push({ method, url: u, body });
    const j = (data, ok = true, status = 200) => Promise.resolve({
        ok, status, json: () => Promise.resolve(data), text: () => Promise.resolve(''),
    });
    if (u.startsWith('/api/context/threshold')) {
        if (thresholdStatus !== 200) {
            return j({ detail: 'Administrator-Rechte erforderlich' }, false, thresholdStatus);
        }
        return j({ ok: true, threshold: body && body.threshold });
    }
    if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
    if (u.startsWith('/api/settings')) return j(SETTINGS);
    if (u.startsWith('/api/me')) {
        return j({ username: 'jarvis', is_admin: true, permissions: { sap: false } });
    }
    if (u.startsWith('/api/skills')) return j({ skills: [] });
    if (u.startsWith('/api/branding')) return j({ enabled: false });
    if (u.startsWith('/api/audit_log')) return j([]);
    if (u.startsWith('/api/version')) return j({ version: '0.9' });
    return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
}

function makeDom(url = 'https://localhost/settings') {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url });
    const { window } = dom;
    window.localStorage.setItem('jarvis_token', 'tok');
    window.localStorage.setItem('jarvis_user', 'jarvis');
    window.confirm = () => true;
    window.alert = () => {};
    window.scrollTo = () => {};
    // WebSocket-Stub: app.js verbindet sich beim Start.
    window.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    return dom;
}

(async () => {
    // ══════════════════════════════════════════════════════════════════════
    // Teil 1: Audit-Log-Filter
    // ══════════════════════════════════════════════════════════════════════
    const dom1 = makeDom();
    const w1 = dom1.window;
    const d1 = w1.document;
    for (const f of ['frontend/js/i18n.js', 'frontend/js/audit.js']) w1.eval(read(f));
    w1.fetch = auditFetch;
    if (!w1.t) w1.t = (k) => k;

    section('1) Die Filterfelder wehren Browser-Autofill ab');
    const fU = d1.getElementById('audit-filter-user');
    const fT = d1.getElementById('audit-filter-tool');
    check('Benutzer-Feld hat autocomplete="off"', fU && fU.getAttribute('autocomplete') === 'off',
        fU ? String(fU.getAttribute('autocomplete')) : 'Feld fehlt');
    check('Benutzer-Feld hat einen sprechenden name (nicht "user"/"username")',
        fU && /audit/.test(fU.getAttribute('name') || '') && !/^user(name)?$/i.test(fU.getAttribute('name') || ''),
        fU ? String(fU.getAttribute('name')) : '—');
    check('Tool-Feld hat autocomplete="off"', fT && fT.getAttribute('autocomplete') === 'off',
        fT ? String(fT.getAttribute('autocomplete')) : 'Feld fehlt');

    section('2) Erster Aufruf: ungefiltert – und die Anzeige sagt das');
    const mgr = w1.auditManager;
    check('auditManager vorhanden', !!mgr);
    mgr.init();
    await sleep(30);
    const cnt = d1.getElementById('audit-count');
    check('alle 3 Eintraege gerendert',
        d1.querySelectorAll('#audit-tbody tr').length === 3,
        String(d1.querySelectorAll('#audit-tbody tr').length));
    check('Zaehler nennt die Zahl', /3/.test(cnt.textContent), cnt.textContent);
    check('Zaehler sagt ausdruecklich „ohne Filter"',
        /ohne Filter/.test(cnt.textContent), cnt.textContent);
    check('keine Warnung, solange Feld und Filter uebereinstimmen',
        !/⚠/.test(cnt.textContent), cnt.textContent);

    section('3) Autofill-Fall: Feld gefuellt, Liste ungefiltert → Warnung');
    // Genau der gemeldete Zustand: der Browser setzt den Wert, ohne dass ein
    // Laden ausgeloest wird. Ein Autofill loest oft KEIN input-Ereignis aus –
    // deshalb wird der Widerspruch schon beim naechsten Rendern erkannt.
    fU.value = 'andreas.bender';
    mgr._renderCount();
    check('Zaehler warnt „Filter geändert"',
        /⚠/.test(cnt.textContent) && /Anwenden/.test(cnt.textContent), cnt.textContent);
    check('Zaehler nennt weiter den ANGEWANDTEN Zustand (ohne Filter)',
        /ohne Filter/.test(cnt.textContent), cnt.textContent);
    check('die Liste selbst ist unveraendert (nichts heimlich neu geladen)',
        d1.querySelectorAll('#audit-tbody tr').length === 3);
    // Ein Fokus-Ereignis (Nutzer klickt ins Feld) erneuert den Hinweis ebenfalls
    fU.dispatchEvent(new w1.FocusEvent('focus'));
    check('Fokus im Feld erneuert den Hinweis', /⚠/.test(cnt.textContent));

    section('4) „Anwenden" filtert wirklich');
    auditCalls = [];
    d1.getElementById('audit-apply-btn').dispatchEvent(new w1.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    check('genau EIN Abruf', auditCalls.length === 1, JSON.stringify(auditCalls));
    check('URL traegt user=andreas.bender',
        /[?&]user=andreas\.bender/.test(auditCalls[0].url), auditCalls[0].url);
    const txt = d1.getElementById('audit-tbody').textContent;
    check('nur noch 1 Zeile', d1.querySelectorAll('#audit-tbody tr').length === 1,
        String(d1.querySelectorAll('#audit-tbody tr').length));
    check('rene.pfeiffer kommt NICHT mehr vor (der gemeldete Fehler)',
        !/rene\.pfeiffer/.test(txt), txt.slice(0, 120));
    check('andreas.bender steht in der Zeile', /andreas\.bender/.test(txt));
    check('Zaehler nennt den Filter', /Benutzer: andreas\.bender/.test(cnt.textContent),
        cnt.textContent);
    check('Warnung ist weg', !/⚠/.test(cnt.textContent), cnt.textContent);

    section('5) Enter im Feld filtert genauso, Tool-Filter wirkt');
    fU.value = '';
    fT.value = 'shell';
    auditCalls = [];
    fT.dispatchEvent(new w1.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await sleep(30);
    check('Abruf mit tool=shell', auditCalls.length === 1 && /[?&]tool=shell/.test(auditCalls[0].url),
        JSON.stringify(auditCalls));
    check('genau 1 Treffer (shell_execute)',
        d1.querySelectorAll('#audit-tbody tr').length === 1);
    check('Zaehler nennt Tool, nicht Benutzer',
        /Tool: shell/.test(cnt.textContent) && !/Benutzer:/.test(cnt.textContent),
        cnt.textContent);

    section('6) Leeres Ergebnis wird als solches ausgewiesen');
    fT.value = 'gibtsnicht';
    d1.getElementById('audit-apply-btn').dispatchEvent(new w1.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    check('Hinweis „keine Eintraege"', /Keine Einträge/i.test(d1.getElementById('audit-tbody').textContent),
        d1.getElementById('audit-tbody').textContent.trim().slice(0, 60));
    check('Zaehler zeigt 0 samt Filter',
        /0/.test(cnt.textContent) && /Tool: gibtsnicht/.test(cnt.textContent), cnt.textContent);

    section('7) Ladefehler laesst den angewandten Filter stehen');
    auditFail = true;
    fT.value = 'memory';
    d1.getElementById('audit-apply-btn').dispatchEvent(new w1.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    check('Zaehler nennt weiter den ALTEN Filter (Liste gehoert dazu)',
        /Tool: gibtsnicht/.test(cnt.textContent), cnt.textContent);
    check('und warnt, dass das Feld abweicht', /⚠/.test(cnt.textContent), cnt.textContent);
    auditFail = false;

    section('8) Sprachwechsel wirkt auf den Zaehler');
    if (w1.setLang) { w1.setLang('en'); } else if (w1.i18n && w1.i18n.setLang) { w1.i18n.setLang('en'); }
    fT.value = '';
    d1.getElementById('audit-apply-btn').dispatchEvent(new w1.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    check('Zaehler auf Englisch („entries" / „no filter")',
        /entries/.test(cnt.textContent) && /no filter/.test(cnt.textContent), cnt.textContent);
    w1.close();

    // ══════════════════════════════════════════════════════════════════════
    // Teil 2: „Kontext / History" ist weg, Schwellwert unter System-Einstellungen
    // ══════════════════════════════════════════════════════════════════════
    section('9) Der Abschnitt „Kontext / History" existiert nicht mehr');
    const dom2 = makeDom();
    const w2 = dom2.window;
    const d2 = w2.document;
    for (const id of ['ctx-section-body', 'ctx-threshold-input', 'ctx-threshold-save',
        'ctx-compress-btn', 'ctx-clear-btn', 'ctx-fills-bar', 'ctx-stat-grid',
        'ctx-refresh-btn', 'ctx-notification', 'ctx-history-entries']) {
        check(`kein Element #${id}`, d2.getElementById(id) === null);
    }
    check('kein Text „Kontext / History" mehr im Reiter',
        !/Kontext \/ History/.test(d2.body.textContent));
    check('context.js wird nicht mehr eingebunden',
        !/js\/context\.js/.test(HTML));
    check('context.js ist aus dem Repo entfernt',
        !fs.existsSync(path.join(ROOT, 'frontend/js/context.js')));

    section('10) Der Schwellwert steht unter „System-Einstellungen"');
    const inp = d2.getElementById('setting-compress-threshold');
    const btn = d2.getElementById('btn-save-compress-threshold');
    check('Eingabefeld vorhanden', !!inp);
    check('Speichern-Knopf vorhanden', !!btn);
    const tuning = d2.getElementById('prof-sect-tuning-body');
    check('Feld liegt IM Abschnitt System-Einstellungen', !!(tuning && inp && tuning.contains(inp)));
    check('Grenzen 4..200 am Feld', inp && inp.min === '4' && inp.max === '200',
        inp ? `${inp.min}..${inp.max}` : '—');
    check('Beschriftung ueber data-i18n', /profile\.section_ctxthr/.test(HTML));

    section('11) Vorbelegung und Speichern (echtes app.js)');
    // FALLSTRICK: fetch MUSS vor dem eval stehen. app.js laeuft als IIFE sofort
    // los und ruft dabei fetch – ist es dann noch undefined, bricht die Funktion
    // ab, bevor sie `window._openSettingsModal` setzt. Der Test meldet dann
    // „Modal-Oeffner nicht erreichbar" und man sucht den Fehler im Umbau.
    w2.fetch = appFetch;
    for (const f of ['frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js']) {
        try { w2.eval(read(f)); } catch (e) { console.log('    (Modul ' + f + ': ' + e.message + ')'); }
    }
    check('Modal-Oeffner erreichbar', typeof w2._openSettingsModal === 'function');
    if (typeof w2._openSettingsModal === 'function') {
        appCalls = [];
        await w2._openSettingsModal();
        await sleep(80);
        check('Feld mit dem Wert aus /api/settings vorbelegt (42)',
            d2.getElementById('setting-compress-threshold').value === '42',
            d2.getElementById('setting-compress-threshold').value);

        // Speichern
        appCalls = [];
        d2.getElementById('setting-compress-threshold').value = '60';
        d2.getElementById('btn-save-compress-threshold')
            .dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
        await sleep(60);
        const thr = appCalls.filter(c => c.method === 'POST' && c.url === '/api/context/threshold');
        check('genau EIN POST auf /api/context/threshold', thr.length === 1,
            JSON.stringify(appCalls.filter(c => c.method === 'POST')));
        check('Rumpf traegt threshold=60', thr[0] && thr[0].body && thr[0].body.threshold === 60,
            JSON.stringify(thr[0] && thr[0].body));
        check('KEIN POST auf /api/settings mit compress_threshold',
            !appCalls.some(c => c.method === 'POST' && c.url.startsWith('/api/settings')
                && c.body && 'compress_threshold' in c.body));
        check('Erfolg wird angezeigt',
            /✓/.test(d2.getElementById('compress-threshold-status').textContent),
            d2.getElementById('compress-threshold-status').textContent);

        section('12) Werte werden auf 4..200 begrenzt');
        appCalls = [];
        d2.getElementById('setting-compress-threshold').value = '9999';
        d2.getElementById('btn-save-compress-threshold')
            .dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
        await sleep(60);
        let p = appCalls.find(c => c.url === '/api/context/threshold');
        check('9999 wird auf 200 gekappt', p && p.body.threshold === 200,
            JSON.stringify(p && p.body));
        appCalls = [];
        d2.getElementById('setting-compress-threshold').value = '1';
        d2.getElementById('btn-save-compress-threshold')
            .dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
        await sleep(60);
        p = appCalls.find(c => c.url === '/api/context/threshold');
        check('1 wird auf 4 gehoben', p && p.body.threshold === 4, JSON.stringify(p && p.body));

        section('13) Ein 403 gilt NICHT als Erfolg');
        thresholdStatus = 403;
        d2.getElementById('setting-compress-threshold').value = '50';
        d2.getElementById('btn-save-compress-threshold')
            .dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
        await sleep(60);
        const st = d2.getElementById('compress-threshold-status').textContent;
        check('Status zeigt Fehler, nicht ✓', /✗/.test(st) && !/✓/.test(st), st);
        thresholdStatus = 200;
    }
    w2.close();

    // ══════════════════════════════════════════════════════════════════════
    // Teil 3: Quelltext/i18n – was im DOM nicht sichtbar ist
    // ══════════════════════════════════════════════════════════════════════
    section('14) i18n: neue Keys vorhanden, alte entfernt');
    const i18n = read('frontend/js/i18n.js');
    for (const k of ['profile.section_ctxthr', 'profile.ctxthr_label', 'profile.ctxthr_hint',
        'telemetry.audit_count', 'telemetry.audit_filter_off', 'telemetry.audit_filter_stale',
        'telemetry.audit_empty']) {
        const n = (i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length;
        check(`${k} in DE und EN (2x)`, n === 2, `gefunden: ${n}`);
    }
    for (const k of ['telemetry.ctx_threshold_label', 'telemetry.ctx_compress_btn',
        'telemetry.context_history', 'telemetry.ctx_hint']) {
        check(`${k} entfernt`, !i18n.includes("'" + k + "'"));
    }

    section('15) Der Rotations-Satz ist raus (er war ab 2026-08-04 falsch)');
    check('kein „10 MB" im Audit-Hinweis (DE+EN)',
        !/audit_hint[^\n]*10 MB/.test(i18n) && !/audit_hint[^\n]*automatic rotation/.test(i18n));
    check('Hinweis nennt stattdessen das Alter als einziges Kriterium',
        /audit_hint[^\n]*Alter/.test(i18n) && /audit_hint[^\n]*age alone/.test(i18n));
    check('audit_log.py hat wirklich keine Groessen-Rotation',
        !/_MAX_BYTES/.test(read('backend/audit_log.py')));

    section('16) Backend liefert compress_threshold in GET /api/settings');
    const main = read('backend/main.py');
    check('Feld im Settings-Endpunkt', /"compress_threshold":\s*max\(4, min\(200,/.test(main));
    check('gelesen aus settings.json, nicht vom lazy Agenten',
        /"compress_threshold":[^\n]*config\.get_setting\("compress_threshold"\)/.test(main));
    check('POST /api/context/threshold bleibt Admin-geschuetzt',
        /api_context_threshold[\s\S]{0,200}require_local_auth/.test(main)
        || /def api_context_threshold\([^)]*require_local_auth/.test(main));

    section('17) app.js: kein Rest des Kontext-Managers');
    const app = read('frontend/js/app.js');
    check('kein contextManager.stop() mehr', !/contextManager\.stop\(\)/.test(app));
    check('Schwellwert wird aus data.compress_threshold vorbelegt',
        /data\.compress_threshold/.test(app));

    // ── Ergebnis ──────────────────────────────────────────────────────────
    const bad = results.filter(r => !r.ok);
    console.log(`\n\x1b[1mErgebnis: ${results.length - bad.length}/${results.length}\x1b[0m`);
    if (bad.length) {
        console.log('\x1b[31mFehlgeschlagen:\x1b[0m');
        bad.forEach(r => console.log('  - ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
