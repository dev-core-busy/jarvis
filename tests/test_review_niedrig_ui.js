/* Waechter: Code-Review 2026-10-07, NIEDRIG – Oberflaeche.
 *
 * Gemessen an den ECHTEN Modulen (jsdom bzw. acorn-Schnitt), nicht am Text:
 *   1. settings_ad.js: Status des Firmenverzeichnisses ueber Theme-Klassen und
 *      i18n (vorher feste Hex-Farben, Emojis, deutscher Festtext) – an der
 *      ECHTEN settings.html, DE und EN.
 *   2. security_incidents.js: scheitert das Speichern, springt das Kaestchen
 *      "auch fuer Administratoren" zurueck.
 *   3. sysload.js / settings_kamerabild.js / api_doku.js: kein Abruf im
 *      Hintergrund-Tab.
 *   4. REGEL ueber alle Module: window.t() kennt keine Platzhalter – ein
 *      zweites Argument ist wirkungslos ({e} stand woertlich in cron.js).
 *      Dazu cron.js: Datum nach Oberflaechensprache.
 *   5. wissen_destillat.js: Nicht-JSON-Antwort ergibt den eigenen Text statt
 *      "Unexpected token"; Zuruecksetzen loescht die Beruehrt-Marke.
 *   6. knowledge.js: Titel/Pfad gelernter Dateien maskiert (Auto-Learning).
 *   7. REGEL: kein Emoji in den angefassten Modulen (Kommentare ausgenommen).
 *
 *   node tests/test_review_niedrig_ui.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
const acorn = require('./lib/acorn_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail !== undefined ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function abbruch(g) { console.log('ABBRUCH: ' + g); process.exit(2); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));
const WACH = setTimeout(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 60000);
process.on('exit', (c) => { if (!BILANZ && c === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 2; } });

const EMOJI = /\p{Extended_Pictographic}/u;
// Textzeichen, die Extended_Pictographic heissen, aber ohne Variantenselektor
// als Schrift gesetzt werden und im Projekt ueblich sind: Warndreieck (U+26A0)
// sowie die Dreiecke U+25B6/U+25C0 (Auf-/Zuklappen). JEDE Ausnahme einzeln.
const ERLAUBT = new Set(['⚠', '▶', '◀']);
// Keine Datei-Ausnahmen mehr: die Sanduhr in wissen.js ist seit dem
// Nachtrag 2026-10-11 ein per CSS gezeichneter Laufanzeiger.
const emojiIn = (text) => [...text].filter(c => EMOJI.test(c) && !ERLAUBT.has(c));

function ohneKommentare(src) {
    const kommentare = [];
    acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', onComment: kommentare });
    let out = src.split('');
    for (const k of kommentare) for (let i = k.start; i < k.end; i++) if (out[i] !== '\n') out[i] = ' ';
    return out.join('');
}
function funktion(src, name) {
    const baum = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script' });
    let fund = null;
    (function lauf(n) {
        if (!n || typeof n !== 'object' || fund) return;
        if (n.type === 'FunctionDeclaration' && n.id && n.id.name === name) { fund = n; return; }
        for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v); }
    })(baum);
    return fund ? src.slice(fund.start, fund.end) : null;
}

async function seite(html, opt) {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const dom = new JSDOM(html, { url: 'https://localhost/settings', runScripts: 'outside-only',
                                  virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    if (opt.lang) w.localStorage.setItem('jarvis_lang', opt.lang);
    w.fetch = opt.fetch;
    w.alert = () => {}; w.confirm = () => true;
    sitzungLaden(w, { token: 'TOK' });
    for (const m of opt.module) w.eval(lies(m));
    if (opt.lang) { w._lang = opt.lang; if (w.applyLang) w.applyLang(); }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
    await schlaf(opt.warte || 60);
    return { w, d: w.document, fehler };
}
const json = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                          json: () => Promise.resolve(d) });

(async () => {
const SETTINGS = lies('frontend/settings.html');

// ── 1. settings_ad.js ───────────────────────────────────────────────────────
section('1. Firmenverzeichnis-Status: Theme-Klassen und i18n (echte settings.html)');
const AD = { configured: true, reachable: true, server: 'dc.firma.local', domain: 'firma.local',
             access_mode: 'none', bind_password_set: true,
             knowledge_editors: '', knowledge_editors_group: '',
             sap_users: 'anna', sap_group: '', sap_mode: 'users',
             internet_users: '', internet_group: 'Internet', internet_mode: 'group',
             admins: '', admins_group: '' };
for (const lang of ['de', 'en']) {
    const s = await seite(SETTINGS, {
        lang, module: ['frontend/js/i18n.js', 'frontend/js/settings_ad.js'],
        fetch: (u) => String(u).split('?')[0] === '/api/auth/ad_status' ? json(AD) : json({})
    });
    const t = (k) => s.w.t(k);
    const $ = (id) => s.d.getElementById(id);
    if (!$('ad-mode-hint') || !$('ad-sap-status')) abbruch('settings.html ohne die Status-Kaesten');
    check(`[${lang}] Positivkontrolle: Status geladen (Server im Text)`,
          ($('ad-status-text').textContent || '').includes('dc.firma.local'), $('ad-status-text').textContent);
    const faelle = [
        ['ad-mode-hint', 'jv-hinweis-warn', t('security.ad_warn_none')],
        ['ad-knowledge-status', 'jv-hinweis-warn', t('security.ad_ke_none')],
        ['ad-sap-status', 'jv-hinweis-ok', t('security.ad_sap_users').replace('{liste}', 'anna')],
        ['ad-internet-status', 'jv-hinweis-info', t('security.ad_inet_group').replace('{liste}', 'Internet')],
        ['ad-admins-status', 'jv-hinweis-warn', t('security.ad_adm_none')],
    ];
    for (const [id, klasse, text] of faelle) {
        const el = $(id);
        check(`[${lang}] ⚠ ${id}: Klasse ${klasse}, Text aus i18n`,
              el.classList.contains(klasse) && el.textContent === text, `${el.className} | ${el.textContent}`);
        /* ⚠ `currentcolor` IST KEINE INLINE-FARBE, sondern "erbe die Textfarbe"
         * - also genau das, was diese Zusage sehen will. Das Markup traegt
         * bewusst `border:1px solid` OHNE Farbwert (die Farbe kommt aus der
         * Klasse). jsdom 30 expandiert die Kurzschreibweise spec-treu und
         * setzt dabei `border-color: currentcolor`; jsdom 25 liess das Feld
         * leer. `!el.style.borderColor` hat damit die SERIALISIERUNG gemessen,
         * nicht die Eigenschaft - und kippte, sobald die Fassung wechselt.
         * Gemessen 2026-10-11, Variablen einzeln getrennt:
         *   Node 20 + jsdom 25 -> ""             (bestand)
         *   Node 24 + jsdom 25 -> ""             (bestand)
         *   Node 24 + jsdom 30 -> "currentcolor" (fiel)
         * Die CI installiert jsdom bei jedem Lauf neu und sah deshalb drei
         * Laeufe lang 10 FAIL, waehrend der Waechter lokal gruen war. Das
         * Produkt war die ganze Zeit in Ordnung. */
        const ohneFarbe = (v) => !v || v === 'currentcolor';
        check(`[${lang}] ⚠ ${id}: keine Inline-Farbe`,
              [el.style.color, el.style.borderColor, el.style.background].every(ohneFarbe),
              el.getAttribute('style'));
        check(`[${lang}] ${id}: kein Emoji`, emojiIn(el.textContent).length === 0 && !el.textContent.includes('\uFE0F'),
              el.textContent);
    }
    check(`[${lang}] ⚠ Kennwort-Hinweis aus i18n`, $('ad-bind-pw-hint').textContent === t('security.ad_pw_saved'),
          $('ad-bind-pw-hint').textContent);
    if (lang === 'en') check('[en] ⚠ englischer Text (nicht der deutsche Festtext)',
                             /SAP users: anna/.test($('ad-sap-status').textContent), $('ad-sap-status').textContent);
    s.w.close();
}
const css = lies('frontend/css/theme.css');
for (const k of ['jv-hinweis-warn', 'jv-hinweis-ok', 'jv-hinweis-info', 'jv-hinweis-err', 'jv-punkt-ok', 'jv-punkt-err'])
    check(`theme.css definiert .${k}`, new RegExp('\\.' + k + '\\s*\\{').test(css));

// ── 2. security_incidents.js ────────────────────────────────────────────────
section('2. Sandbox "auch fuer Administratoren": Fehlschlag stellt das Kaestchen zurueck');
for (const [antwort, soll, name] of [[{ ok: true, auch_admins: true, grenzen: {} }, true, 'Positivkontrolle: Erfolg -> bleibt an'],
                                     [{ ok: false, error: 'nein' }, false, '⚠ Server lehnt ab -> Kaestchen zurueck'],
                                     [null, false, '⚠ Netzfehler -> Kaestchen zurueck']]) {
    const s = await seite(SETTINGS, {
        module: ['frontend/js/icons.js', 'frontend/js/i18n.js', 'frontend/js/security_incidents.js'],
        fetch: (u) => {
            if (String(u).split('?')[0] === '/api/security/sandbox/config')
                return antwort ? json(antwort, antwort.ok ? 200 : 400) : Promise.reject(new Error('offline'));
            return json({});
        }
    });
    const cb = s.d.getElementById('sec-sandbox-admins');
    if (!cb || !s.w.SecurityIncidents) abbruch('Kaestchen oder SecurityIncidents fehlt');
    cb.checked = true;                        // Benutzer hat angehakt
    s.w.SecurityIncidents.saveSandboxCfg({ auch_admins: true });
    await schlaf(40);
    check(name, cb.checked === soll, String(cb.checked));
    s.w.close();
}

// ── 3. Hintergrund-Tab ──────────────────────────────────────────────────────
section('3. Kein Abruf im Hintergrund-Tab');
{
    const src = funktion(lies('frontend/js/sysload.js'), 'planen');
    if (!src) abbruch('sysload.js: planen() nicht gefunden');
    const ctx = { _timer: null, TAKT_MS: 3000, abrufen() {}, gestellt: 0,
                  setTimeout() { ctx.gestellt++; return 1; }, clearTimeout() {},
                  document: { hidden: false } };
    vm.runInNewContext(src + '\nplanen();', ctx);
    check('Positivkontrolle: sichtbarer Tab -> naechster Abruf geplant', ctx.gestellt === 1, ctx.gestellt);
    ctx.gestellt = 0; ctx.document.hidden = true; ctx._timer = null;
    vm.runInNewContext(src + '\nplanen();', ctx);
    check('⚠ sysload: Hintergrund-Tab -> nichts geplant', ctx.gestellt === 0, ctx.gestellt);
    check('sysload: beim Zurueckkehren wird wieder abgefragt (visibilitychange)',
          /addEventListener\(\s*'visibilitychange'/.test(ohneKommentare(lies('frontend/js/sysload.js'))));
}
{
    const vc = new VirtualConsole();
    const dom = new JSDOM('<div id="settings-tab-vision" class="active"></div><img id="vis-feed-img">',
                          { url: 'https://localhost/settings', runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    let cb = null;
    w.setInterval = (f) => { cb = f; return 1; };
    sitzungLaden(w, { token: 'TOK' });
    w.eval(lies('frontend/js/settings_kamerabild.js'));
    let versteckt = false;
    Object.defineProperty(w.document, 'hidden', { get: () => versteckt, configurable: true });
    const img = w.document.getElementById('vis-feed-img');
    cb();
    check('Positivkontrolle: Kamerabild wird geholt (sichtbarer Tab)', /snapshot/.test(img.src || ''), img.src);
    img.removeAttribute('src'); versteckt = true; cb();
    check('⚠ Kamerabild: Hintergrund-Tab -> kein Abruf', !img.getAttribute('src'), img.getAttribute('src'));
    w.close();
}
{
    const src = ohneKommentare(lies('frontend/js/api_doku.js'));
    const baum = acorn.parse(src, { ecmaVersion: 'latest' });
    const iv = [];
    (function lauf(n) {
        if (!n || typeof n !== 'object') return;
        if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && n.callee.name === 'setInterval') iv.push(n);
        for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v); }
    })(baum);
    check('api_doku: Positivkontrolle – ein setInterval gefunden', iv.length >= 1, iv.length);
    check('⚠ api_doku: jeder Takt prueft document.hidden',
          iv.length >= 1 && iv.every(c => /document\.hidden/.test(src.slice(c.start, c.end))));
}

// ── 4. window.t() und cron.js ───────────────────────────────────────────────
section('4. REGEL: window.t() mit zweitem Argument ist wirkungslos');
// JEDES zweite Argument ist wirkungslos: ein Platzhalter-Objekt ({e} stand
// woertlich da) ebenso wie ein Rueckfalltext (window.t liefert bei fehlendem
// Schluessel den Schluessel selbst, der Rueckfall griff nie – fuenf Module).
function tMitArg(src) {
    const funde = [];
    const baum = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', locations: true });
    (function lauf(n) {
        if (!n || typeof n !== 'object') return;
        if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
            && n.callee.object.type === 'Identifier' && n.callee.object.name === 'window'
            && !n.callee.computed && n.callee.property.name === 't' && n.arguments.length > 1)
            funde.push(n.loc.start.line);
        for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v); }
    })(baum);
    return funde;
}
check('Positivkontrolle: die Regel erkennt window.t(k, {e: 1})', tMitArg("window.t('x', {e: 1});").length === 1);
check('Positivkontrolle: … und window.t(k, fallback)', tMitArg("window.t('x', 'Rueckfall');").length === 1);
// Wirkung der fuenf Rueckfall-Helfer: echter Helfer aus dem Modul, window.t in
// ECHTER Form (fehlender Schluessel -> Schluessel selbst)
for (const [f, name] of [['ai_mouse.js', 't'], ['ai_mouse_admin.js', 't'], ['feedback.js', 't'],
                         ['feedback_admin.js', 't'], ['claude_portal.js', 'T']]) {
    const src = funktion(lies('frontend/js/' + f), name);
    if (!src) { check(`${f}: Helfer ${name}() gefunden`, false); continue; }
    const da = { 'x.vorhanden': 'Übersetzt' };
    const ctx = { window: { t: (k) => (k in da ? da[k] : k) } };
    vm.runInNewContext(src, ctx);
    check(`⚠ ${f}: fehlender Schluessel -> Rueckfalltext (nicht der rohe Schluessel)`,
          ctx[name]('x.fehlt', 'Rückfall') === 'Rückfall', ctx[name]('x.fehlt', 'Rückfall'));
    check(`${f}: vorhandener Schluessel -> Uebersetzung (Positivkontrolle)`,
          ctx[name]('x.vorhanden', 'Rückfall') === 'Übersetzt');
}
{
    const tSrc = lies('frontend/js/i18n.js');
    const m = /window\.t\s*=\s*function\s*\(([^)]*)\)/.exec(tSrc);
    check('Annahme gilt: window.t nimmt genau EIN Argument', !!m && m[1].split(',').filter(Boolean).length === 1, m && m[1]);
    const verstoesse = [];
    for (const f of fs.readdirSync(path.join(ROOT, 'frontend/js')).filter(f => f.endsWith('.js'))) {
        let funde = [];
        try { funde = tMitArg(lies('frontend/js/' + f)); } catch (e) { continue; }
        funde.forEach(z => verstoesse.push(f + ':' + z));
    }
    check('⚠ kein window.t(…, Platzhalter) in frontend/js', verstoesse.length === 0, verstoesse.join(', '));
    const cron = ohneKommentare(lies('frontend/js/cron.js'));
    check("⚠ cron.js: kein fest verdrahtetes toLocale…('de-DE')",
          !/toLocale(?:Date|Time)?String\(\s*'de-DE'/.test(cron));
    const ort = funktion(lies('frontend/js/cron.js'), '_cronOrt');
    const ctx = { window: { _lang: 'en' } };
    check('cron.js: Englisch -> en-GB', !!ort && vm.runInNewContext(ort + '\n_cronOrt()', ctx) === 'en-GB');
}

// ── 5. wissen_destillat.js ──────────────────────────────────────────────────
section('5. Destillat: Nicht-JSON-Antwort und Zuruecksetzen');
{
    const SRC = lies('frontend/js/wissen_destillat.js');
    const al = funktion(SRC, 'antwortLesen');
    if (!al) abbruch('antwortLesen fehlt');
    const ctx = {};
    vm.runInNewContext(al, ctx);
    // Ein Wurf ist hier der BEFUND – als eigene Bedingung, nicht als Absturz
    // des Waechters (sonst Exit 2 statt Exit 1, Register).
    let r;
    try { r = await ctx.antwortLesen({ status: 502, json: () => Promise.reject(new SyntaxError("Unexpected token '<'")) }); }
    catch (e) { r = { geworfen: String(e) }; }
    check('⚠ HTML-Antwort (502): kein Wurf, leeres Objekt, Status bleibt',
          !r.geworfen && r.s === 502 && r.d && Object.keys(r.d).length === 0, JSON.stringify(r));
    const r2 = await ctx.antwortLesen({ status: 200, json: () => Promise.resolve({ ok: true }) });
    check('Positivkontrolle: JSON kommt durch', r2.s === 200 && r2.d.ok === true);
    const ohne = ohneKommentare(SRC);
    check('die drei Laeufe lesen ueber antwortLesen', (ohne.match(/\.then\(antwortLesen\)/g) || []).length >= 3);
    check("⚠ kein roher Fehlertext (e.message) in den Statuszeilen",
          !/status\([^;]*\.message/.test(ohne));
    const vs = funktion(SRC, 'vorgabenSetzen');
    const mk = () => ({ value: 'alt', dataset: { beruehrt: '1' } });
    const els = { 'wi-dest-prompt': mk(), 'wi-dest-gruppen': mk() };
    vm.runInNewContext(vs + '\nvorgabenSetzen();', { $: (id) => els[id], t: (k) => 'V:' + k });
    check('⚠ Zuruecksetzen loescht die Beruehrt-Marke (Prompt und Gruppen)',
          !('beruehrt' in els['wi-dest-prompt'].dataset) && !('beruehrt' in els['wi-dest-gruppen'].dataset));
    check('Positivkontrolle: Vorgabe gesetzt', els['wi-dest-prompt'].value === 'V:wissen.dest_prompt_default');
}

// ── 5b. wissen.js: Laufanzeiger ohne Emoji ─────────────────────────────────
section('5b. Import-Fortschritt: Laufanzeiger per CSS, Text ohne Sanduhr');
{
    const src = funktion(lies('frontend/js/wissen.js'), 'setProgress');
    if (!src) abbruch('wissen.js: setProgress fehlt');
    const vc = new VirtualConsole();
    const dom = new JSDOM('<div id="wi-extract-progress"></div>', { url: 'https://localhost/wissen', runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    w.esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    w.$ = (id) => w.document.getElementById(id);
    w.eval(src);
    w.eval(lies('frontend/js/i18n.js'));
    const el = w.document.getElementById('wi-extract-progress');
    w.setProgress(w.t('wissen.cf_starting'), null, true);
    const sp = el.querySelector('.wi-hourglass');
    check('⚠ laufend: Laufanzeiger als leeres Element, Text daneben',
          !!sp && sp.textContent === '' && el.textContent === w.t('wissen.cf_starting'), el.innerHTML);
    check('⚠ kein Emoji in der Zeile', emojiIn(el.textContent).length === 0, el.textContent);
    w.setProgress('fertig');
    check('Positivkontrolle: ohne laeuft kein Anzeiger', !el.querySelector('.wi-hourglass') && el.textContent === 'fertig');
    const i18n = lies('frontend/js/i18n.js');
    check('⚠ i18n: die Fortschrittstexte tragen keine Sanduhr mehr',
          !/'wissen\.(extracting|cf_starting|cf_progress)':\s*'\u23F3/u.test(i18n));
    const html = lies('frontend/wissen.html');
    check('wissen.html: .wi-hourglass ist gezeichnet (Rahmen), kein Zeichen', /\.wi-hourglass\s*\{[^}]*border:/.test(html));
    w.close();
}

// ── 6. knowledge.js ─────────────────────────────────────────────────────────
section('6. Gelerntes Wissen: Titel und Pfad maskiert');
{
    const BOESE = { title: '<img src=x onerror="window.__x=1">', path: 'a"><b id=boese>x</b>', mtime: 1, size_kb: 1 };
    const s = await seite('<div id="kb-learned-list" style="display:none"></div>', {
        module: ['frontend/js/icons.js', 'frontend/js/i18n.js', 'frontend/js/knowledge.js'],
        fetch: (u) => String(u).split('?')[0] === '/api/knowledge/learned' ? json([BOESE]) : json({})
    });
    if (!s.w.knowledgeManager) abbruch('knowledgeManager fehlt');
    await s.w.knowledgeManager.toggleLearnedList();
    const el = s.d.getElementById('kb-learned-list');
    const titel = el.querySelector('.kb-learned-item-title');
    check('Positivkontrolle: Eintrag gezeichnet', !!titel, el.innerHTML.slice(0, 120));
    check('⚠ Titel als Text, kein <img>', !!titel && !el.querySelector('img') && titel.textContent === BOESE.title,
          titel && titel.innerHTML);
    check('⚠ Pfad bleibt im title-Attribut (kein eingeschleustes Element)',
          !!titel && titel.getAttribute('title') === BOESE.path && !s.d.getElementById('boese'));
    s.w.close();
}

// ── 7. kein Emoji ───────────────────────────────────────────────────────────
section('7. REGEL: kein Emoji in den angefassten Modulen (ohne Kommentare)');
check('Positivkontrolle: die Regel sieht ein Emoji', emojiIn('x\u{1F512}y').length === 1 && emojiIn('\u{23F3}').length === 1);
for (const f of ['settings_ad.js', 'api_doku.js', 'security_incidents.js', 'konto_hinweise.js', 'wissen.js']) {
    const src = ohneKommentare(lies('frontend/js/' + f));
    const funde = [];
    src.split('\n').forEach((z, i) => {
        const zeichen = emojiIn(z);
        if (zeichen.length || z.includes('️')) funde.push((i + 1) + ':' + zeichen.join(''));
    });
    check(`⚠ ${f}: kein Emoji`, funde.length === 0, funde.slice(0, 6).join(' '));
}
for (const f of ['settings_ad.js']) {
    const src = ohneKommentare(lies('frontend/js/' + f));
    check(`⚠ ${f}: keine feste Farbe (#hex/rgb(Zahl))`, !/#[0-9a-fA-F]{3,6}\b|rgba?\(\s*\d/.test(src));
}
{
    const src = ohneKommentare(lies('frontend/js/konto_hinweise.js'));
    const ohneFallback = src.replace(/var\(--[a-z-]+,[^()]*(\([^()]*\))?[^()]*\)/g, 'VAR');
    check('⚠ konto_hinweise.js: Farben nur aus Theme-Variablen (Rueckfall in var() erlaubt)',
          !/#[0-9a-fA-F]{3,6}\b|rgba?\(\s*\d/.test(ohneFallback),
          (ohneFallback.match(/.{20}(#[0-9a-fA-F]{3,6}\b|rgba?\(\s*\d).{10}/) || [''])[0]);
    check('⚠ konto_hinweise.js: kein Stueck des Tokens im sessionStorage (kein slice auf dem Token)',
          !/tok\.slice\(/.test(src));
}

clearTimeout(WACH);
BILANZ = true;
console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
