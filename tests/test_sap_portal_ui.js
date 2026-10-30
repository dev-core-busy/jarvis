/* UI-Test: SAP-Analysebereich (/sap) + SAP-Kachel im Portal.
 *
 * Laeuft in jsdom gegen die ECHTEN Dateien (frontend/sap.html,
 * frontend/js/sap_portal.js, frontend/portal.html) mit gemockter API.
 *
 * Geprueft wird, was sich am Quelltext NICHT ablesen laesst:
 *   1. Berechtigung – ohne permissions.sap fuehrt die Seite zurueck aufs Portal
 *      (und zwar auch dann, wenn das Feld ganz fehlt: fail-closed)
 *   2. Analyse-Pulldown nach Kategorien gruppiert, Beschreibung folgt der Wahl
 *   3. BI-Wahl hebt die passende Schnittstelle in der Anbindungsliste hervor
 *   4. Verlauf: Eintrag nach dem Lauf, Klick UEBERNIMMT nur (startet nicht)
 *   5. Escape schliesst zuerst den Anweisungs-Dialog, dann das Verlaufsfeld
 *   6. Portal: Kachel nur bei permissions.sap
 *   7. "Mein SAP-Zugang": die Aussetzer-Meldung nennt den GRUND
 *  15. Verbindungstest: Bericht fuer den SAP-Administrator (auch im Fehlerfall)
 *  16. Abfrage-Konsole: Auswahllisten fuer Service und EntitySet
 *  17. Nicht direkt abrufbare EntitySets (Hinweis, 404-Erklaerung) und die
 *      Service-Liste unter "Mein SAP-Zugang" -> Standard-Service
 *  18. Mitladen ($expand): Vorschlaege, Uebergabe, verschachtelte Zellen
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst haelt der 30-Sekunden-Timer der LLM-Anzeige den Prozess fuer immer offen.
 *
 * Lauf:  timeout 90 node tests/test_sap_portal_ui.js
 *
 * SAP_PORTAL_JS=<pfad> legt statt frontend/js/sap_portal.js eine KOPIE vor –
 * fuer die Gegenprobe (gegen_sap_verbindungstest.py), die echte Datei wird
 * dabei nie angefasst.
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const PORTAL_JS = process.env.SAP_PORTAL_JS || path.join(ROOT, 'frontend', 'js', 'sap_portal.js');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

// ── Testdaten (Form wie /api/sap/analyses) ──────────────────────────
const CATALOG = {
    lang: 'de',
    categories: [
        { id: 'finance', title: 'Finanzen & Rechnungswesen (FI/CO)' },
        { id: 'sales', title: 'Vertrieb (SD)' },
    ],
    analyses: [
        { id: 'ar_aging', cat: 'finance', title: 'Debitoren-Altersstruktur',
          desc: 'Offene Forderungen nach Faelligkeitsklassen.',
          kpis: ['Offene Forderungen', 'Ueberfaelligenquote', 'Kreditlimit'],
          sources: 'BSID/BSAD, KNA1' },
        { id: 'working_capital', cat: 'finance', title: 'Working Capital',
          desc: 'Kapitalbindung im operativen Geschaeft.',
          kpis: ['DSO', 'DPO', 'DIO'], sources: 'BSID, MBEW' },
        { id: 'order_backlog', cat: 'sales', title: 'Auftragsbestand',
          desc: 'Fruehindikator fuer kommende Quartale.',
          kpis: ['Auftragseingang', 'Book-to-Bill', 'Reichweite'],
          sources: 'VBAK/VBAP' },
    ],
    bi_tools: [
        { id: 'inline', name: 'Jarvis (direkt hier)', iface: null },
        { id: 'powerbi', name: 'Microsoft Power BI', iface: 'OData Feed' },
        { id: 'grafana', name: 'Grafana', iface: 'SAP HANA (SQL/ODBC/JDBC)' },
    ],
};
const ENDPOINTS = {
    ok: true,
    endpoints: [
        { interface: 'OData Feed', url: 'https://sap.example/sap/opu/odata',
          tools: { 'Power BI': 'Daten abrufen → OData-Feed.' } },
        { interface: 'SAP HANA (SQL/ODBC/JDBC)', url: 'hana.example:30015',
          tools: { 'Grafana': 'HANA-Datenquelle.' } },
    ],
};

let askCalls = 0;
let savedInstructions = null;

/** Baut eine jsdom-Umgebung mit gemocktem fetch. `me` steuert /api/me.
 *
 * FALLSTRICK: `window.location` laesst sich in jsdom weder ersetzen noch
 * ueberschreiben (`Cannot redefine property`). Eine Weiterleitung wird
 * stattdessen ueber den jsdomError "Not implemented: navigation" erkannt und in
 * `dom.__navs` gesammelt – die VirtualConsole schluckt dabei gleichzeitig die
 * seitenlangen Stapelspuren. Dass das ZIEL `/portal` ist, prueft ein eigener
 * Quelltext-Test weiter unten; hier zaehlt, DASS navigiert wurde. */
function build(htmlFile, me, opts) {
    opts = opts || {};
    const html = fs.readFileSync(path.join(ROOT, 'frontend', htmlFile), 'utf8');
    const navs = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => {
        if (/Not implemented: navigation/.test(e.message || '')) navs.push(e.message);
    });
    const dom = new JSDOM(html, {
        url: 'https://localhost/' + (htmlFile === 'sap.html' ? 'sap' : 'portal'),
        runScripts: 'dangerously',
        virtualConsole: vc,
        beforeParse(win) {
            // sitzung.js laeuft, bevor die Skripte der SEITE laufen – genau wie im
            // Browser (sie ist dort das erste Skript). Ohne das stirbt das
            // Inline-Skript von portal.html an `window.JarvisSitzung`, und die
            // Seite rendert gar nicht (gemessen: 92/93 statt 93/93).
            win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
            win.localStorage.setItem('jarvis_token', 'testtoken');
            // Der Verlauf liegt im localStorage – zwischen den Abschnitten
            // leeren, sonst schleppt ein Test die Eintraege des vorigen mit.
            if (opts.clearHistory !== false) win.localStorage.removeItem('jarvis_sap_history');
            if (opts.seedHistory) {
                win.localStorage.setItem('jarvis_sap_history', JSON.stringify(opts.seedHistory));
            }
            win.HTMLCanvasElement.prototype.getContext = () => null;  // Chart.js
            win.fetch = function (url, init) {
                const u = String(url);
                const body = (init && init.body) ? JSON.parse(init.body) : null;
                const json = (data, status) => Promise.resolve({
                    ok: (status || 200) < 400, status: status || 200,
                    json: () => Promise.resolve(data),
                    text: () => Promise.resolve(JSON.stringify(data)),
                });
                if (u.startsWith('/api/me')) return json(me);
                if (u.startsWith('/api/sap/analyses')) {
                    const en = /lang=en/.test(u);
                    return json(Object.assign({}, CATALOG, { lang: en ? 'en' : 'de' }));
                }
                if (u.startsWith('/api/sap/reporting-endpoints')) return json(ENDPOINTS);
                if (u.startsWith('/api/sap/status')) {
                    return json(Object.assign({ ok: true, configured: true, connection_type: 'odata',
                                  product: 'S/4HANA', odata: true, hana: false, rfc: false }, opts.status || {}));
                }
                if (u.startsWith('/api/sap/odata/query') && opts.odQuery) {
                    (opts.odCalls || []).push(u);
                    const qq = new URLSearchParams(u.split('?')[1] || '');
                    return json(opts.odQuery(qq.get('entity_set') || '', qq));
                }
                if (u.startsWith('/api/sap/instructions')) {
                    if (init && init.method === 'POST') {
                        savedInstructions = body.instructions;
                        return json({ ok: true });
                    }
                    return json({ ok: true, instructions: 'Vorhandene Anweisung.' });
                }
                if (u.startsWith('/api/sap/ask')) {
                    askCalls++;
                    return json({ ok: true, answer: '## Ergebnis\n\n| A | B |\n|---|---|\n| 1 | 2 |' });
                }
                if (u.startsWith('/api/sap/account')) {
                    return opts.account ? json({ ok: true, account: opts.account })
                                        : json({ ok: true });
                }
                if (u.startsWith('/api/sap/stop')) return json({ ok: true });
                if (u.startsWith('/api/sap/test') && opts.sapTest) return json(opts.sapTest);
                if (u.startsWith('/api/sap/odata/services') && opts.odServices) {
                    (opts.odCalls || []).push(u);
                    return json(opts.odServices);
                }
                if (u.startsWith('/api/sap/odata/entity-sets') && opts.odSets) {
                    (opts.odCalls || []).push(u);
                    const q = new URLSearchParams(u.split('?')[1] || '');
                    const r = opts.odSets(q.get('service') || '');
                    const antwort = new Promise((res) => setTimeout(res, r.delay || 0)).then(() => json(r.data));
                    (opts.odOffen || []).push(antwort);
                    return antwort;
                }
                if (u.startsWith('/api/llm/active-status')) return json({ status: 'ok', profile_name: 'Test' });
                if (u.startsWith('/api/support/status')) return json({ active: false });
                if (u.startsWith('/api/wissen/scope')) return json({ ok: true, groups: [] });
                if (u.startsWith('/api/userchat/unread')) return json({ unread: 0 });
                if (u.startsWith('/api/info_files')) return json({ ok: true, files: [] });
                return json({ ok: true });
            };
        },
    });
    // BSI H4 (CSP ohne Inline-Skript, 2026-10-04): das fruehere Inline-Skript
    // von portal.html steht jetzt in js/portal_seite.js (per src eingebunden).
    // jsdom laedt hier keine src-Skripte - also wie zuvor das Inline-Skript
    // selbst ausfuehren, aber nur, wenn die Seite die Datei auch einbindet.
    if (/<script src="\/static\/js\/portal_seite\.js\?v=\d+"><\/script>/.test(html)) {
        dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'portal_seite.js'), 'utf8'));
    }
    dom.__navs = navs;
    return dom;
}

function loadScript(dom, rel) {
    const code = fs.readFileSync(rel === 'js/sap_portal.js' ? PORTAL_JS
                                                           : path.join(ROOT, 'frontend', rel), 'utf8');
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle und rufen sie beim
    // LADEN auf. Jede echte Seite laedt sie davor.
    dom.window.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    dom.window.eval(code);
}

(async () => {
    // ══ 1. Berechtigung ══════════════════════════════════════════════
    section('1. Berechtigung');
    {
        const dom = build('sap.html', { username: 'bob', is_admin: false,
                                        permissions: { sap: false } });
        loadScript(dom, 'js/icons.js');
        loadScript(dom, 'js/sap_portal.js');
        await sleep(60);
        check('ohne Freigabe: Weiterleitung ausgeloest', dom.__navs.length > 0);
        check('ohne Freigabe: App bleibt verborgen',
              dom.window.document.getElementById('sp-app').classList.contains('hidden'));
        dom.window.close();
    }
    {
        // Fail-closed: aelteres Backend ohne permissions-Feld darf NICHT
        // versehentlich als "erlaubt" gelten.
        const dom = build('sap.html', { username: 'bob', is_admin: true });
        loadScript(dom, 'js/icons.js');
        loadScript(dom, 'js/sap_portal.js');
        await sleep(60);
        check('fehlendes permissions-Feld gilt als nicht freigegeben (fail-closed)',
              dom.__navs.length > 0);
        check('fail-closed: App bleibt verborgen',
              dom.window.document.getElementById('sp-app').classList.contains('hidden'));
        dom.window.close();
    }
    {
        // Ergaenzung zur Navigations-Erkennung oben: das ZIEL steht so nur im
        // Quelltext, weil jsdom die Adresse nicht herausgibt.
        const src = fs.readFileSync(path.join(ROOT, 'frontend/js/sap_portal.js'), 'utf8');
        check("Weiterleitungsziel ist /portal",
              /location\.replace\('\/portal'\)/.test(src));
        check('ohne Token geht es zur Anmeldung, nicht ins Portal',
              /if \(!token\(\)\) \{ window\.location\.replace\('\/'\)/.test(src));
    }

    // ══ 2..5 mit Freigabe ════════════════════════════════════════════
    const dom = build('sap.html', { username: 'anna', is_admin: true,
                                    permissions: { sap: true } });
    // icons.js steht auf der echten Seite als ERSTES Skript – der Verlauf
    // zeichnet seinen Muelleimer daraus. Ohne diese Zeile prueft der Test
    // eine Kette, die es so nicht gibt.
    loadScript(dom, 'js/icons.js');
    loadScript(dom, 'js/i18n.js');
    loadScript(dom, 'js/chatlib.js');
    loadScript(dom, 'js/sap_portal.js');
    // Das Zahnrad wird seit 2026-08-23 zentral aus /api/me eingeblendet
    // (js/settings_btn.js). Ohne dieses Skript im Aufbau prueft der Test eine
    // Kette, die die echte Seite nicht mehr hat.
    loadScript(dom, 'js/settings_btn.js');
    await sleep(120);
    const doc = dom.window.document;
    const $ = (id) => doc.getElementById(id);

    section('2. Aufbau der Seite');
    check('App sichtbar', !$('sp-app').classList.contains('hidden'));
    check('mit Freigabe KEINE Weiterleitung', dom.__navs.length === 0,
          String(dom.__navs.length));
    check('Admin sieht den Einstellungen-Knopf', $('sp-settings-btn').style.display === '');
    check('Verbindungs-Pille nennt Schnittstelle und Produkt',
          /OData/.test($('sp-conn').textContent) && /S\/4HANA/.test($('sp-conn').textContent),
          $('sp-conn').textContent);
    check('Verbindungs-Pille nicht als Fehler markiert',
          !$('sp-conn').classList.contains('is-off'));
    {
        // Avatar: die Seite muss dieselben Bausteine einbinden wie /support und
        // /portal. Der Ein/Aus-Schalter baut sich selbst und haengt sich VOR
        // #btn-theme-toggle – fehlt diese Id, landet er als frei schwebender
        // Knopf irgendwo auf der Seite.
        const raw = fs.readFileSync(path.join(ROOT, 'frontend/sap.html'), 'utf8');
        ['vendor/clippy/clippy.css', 'css/avatar.css', 'vendor/clippy/jquery-3.7.1.min.js',
         'vendor/clippy/clippy.min.js', 'js/avatar.js'].forEach((f) => {
            check('Avatar-Baustein eingebunden: ' + f, raw.includes(f));
        });
        check('Anker fuer den Avatar-Schalter vorhanden (#btn-theme-toggle)',
              $('btn-theme-toggle') !== null);
        check('Avatar-Skripte stehen NACH der Seitenlogik',
              raw.indexOf('js/avatar.js') > raw.indexOf('js/sap_portal.js'));
    }

    section('3. Analyse-Pulldown');
    const sel = $('sp-analysis');
    check('nach Kategorien gruppiert', sel.querySelectorAll('optgroup').length === 2,
          String(sel.querySelectorAll('optgroup').length));
    check('Gruppentitel aus dem Katalog',
          sel.querySelectorAll('optgroup')[0].label === 'Finanzen & Rechnungswesen (FI/CO)');
    check('alle Analysen + Freitext-Eintrag',
          sel.querySelectorAll('option').length === 4,
          String(sel.querySelectorAll('option').length));
    check('Vorbelegung ist die freie Frage', sel.value === '');
    check('Beschreibung anfangs verborgen', $('sp-desc').classList.contains('hidden'));

    sel.value = 'ar_aging';
    sel.dispatchEvent(new dom.window.Event('change'));
    await sleep(20);
    check('Wahl blendet die Beschreibung ein', !$('sp-desc').classList.contains('hidden'));
    check('Titel der Analyse steht da', $('sp-desc-title').textContent === 'Debitoren-Altersstruktur');
    check('Beschreibungstext steht da', /Faelligkeitsklassen/.test($('sp-desc-text').textContent));
    check('Kennzahlen als Chips', $('sp-desc-kpis').querySelectorAll('.sp-chip').length === 3);
    check('SAP-Quellen genannt', /BSID\/BSAD/.test($('sp-desc-src').textContent));

    sel.value = '';
    sel.dispatchEvent(new dom.window.Event('change'));
    await sleep(20);
    check('zurueck auf freie Frage verbirgt die Beschreibung wieder',
          $('sp-desc').classList.contains('hidden'));

    section('4. BI-Werkzeug und Anbindung');
    const tool = $('sp-bitool');
    check('alle Werkzeuge im Pulldown', tool.querySelectorAll('option').length === 3);
    check('Anbindungsliste gefuellt',
          doc.querySelectorAll('#sp-bi-list .sp-ep').length === 2);
    tool.value = 'powerbi';
    tool.dispatchEvent(new dom.window.Event('change'));
    await sleep(20);
    let eps = doc.querySelectorAll('#sp-bi-list .sp-ep');
    check('Power BI hebt OData hervor',
          eps[0].classList.contains('is-match') && !eps[1].classList.contains('is-match'));
    tool.value = 'grafana';
    tool.dispatchEvent(new dom.window.Event('change'));
    await sleep(20);
    eps = doc.querySelectorAll('#sp-bi-list .sp-ep');
    check('Grafana hebt HANA hervor',
          !eps[0].classList.contains('is-match') && eps[1].classList.contains('is-match'));
    tool.value = 'inline';
    tool.dispatchEvent(new dom.window.Event('change'));
    await sleep(20);
    eps = doc.querySelectorAll('#sp-bi-list .sp-ep');
    check('Werkzeug ohne Schnittstelle hebt nichts hervor',
          !eps[0].classList.contains('is-match') && !eps[1].classList.contains('is-match'));

    section('5. Analyse ausfuehren');
    check('Verlauf anfangs leer',
          /Noch keine|No analyses/.test($('sp-hist-list').textContent));
    $('sp-analysis').value = 'working_capital';
    $('sp-analysis').dispatchEvent(new dom.window.Event('change'));
    $('sp-question').value = 'nur Buchungskreis 1000';
    const before = askCalls;
    $('sp-run').click();
    await sleep(120);
    check('genau ein Aufruf von /api/sap/ask', askCalls === before + 1,
          String(askCalls - before));
    check('Ergebnis sichtbar', !$('sp-result').classList.contains('hidden'));
    check('Markdown gerendert (Tabelle)',
          $('sp-result-body').querySelector('table') !== null);
    check('Ergebnistitel ist der Analysename',
          $('sp-result-title').textContent === 'Working Capital');
    check('Abbrechen-Knopf nach dem Lauf wieder verborgen',
          $('sp-cancel').classList.contains('hidden'));
    check('Starten-Knopf wieder bedienbar', $('sp-run').disabled === false);

    check('Verlaufseintrag angelegt',
          doc.querySelectorAll('#sp-hist-item, #sp-hist-list .sp-hist-item').length === 1);
    check('Verlauf zeigt den Analysenamen',
          /Working Capital/.test($('sp-hist-list').textContent));
    // Der Verlauf darf NUR die Frage speichern, nie das Ergebnis – sonst
    // liegen Geschaeftszahlen im Browser-Speicher.
    const raw = dom.window.localStorage.getItem('jarvis_sap_history') || '';
    check('Verlauf speichert kein Ergebnis', !/Ergebnis|<table/.test(raw));
    check('Verlauf speichert die Frage', /Buchungskreis 1000/.test(raw));

    section('6. Verlauf: uebernehmen statt starten');
    $('sp-analysis').value = '';
    $('sp-question').value = '';
    $('sp-hist-btn').click();
    await sleep(20);
    check('Verlaufsfeld offen', !$('sp-hist-panel').classList.contains('hidden'));
    const calls2 = askCalls;
    doc.querySelector('#sp-hist-list .sp-hist-item').click();
    await sleep(60);
    check('Klick startet KEINE Analyse', askCalls === calls2, String(askCalls - calls2));
    check('Klick uebernimmt die Analyse', $('sp-analysis').value === 'working_capital');
    check('Klick uebernimmt die Frage', $('sp-question').value === 'nur Buchungskreis 1000');
    check('Klick schliesst das Verlaufsfeld', $('sp-hist-panel').classList.contains('hidden'));
    check('Beschreibung wurde mit uebernommen',
          $('sp-desc-title').textContent === 'Working Capital');

    section('7. Anweisungen');
    $('sp-instr-btn').click();
    await sleep(60);
    check('Dialog offen', !$('sp-instr-overlay').classList.contains('hidden'));
    check('vorhandene Anweisung geladen',
          $('sp-instr-text').value === 'Vorhandene Anweisung.');
    $('sp-instr-text').value = 'Neu: Betraege in TEUR.';
    $('sp-instr-save').click();
    await sleep(60);
    check('Speichern sendet den Text', savedInstructions === 'Neu: Betraege in TEUR.',
          String(savedInstructions));

    section('8. Escape-Reihenfolge');
    // Beide offen: Escape muss ZUERST den Dialog schliessen. Sonst bliebe ein
    // Dialog ueber einem geschlossenen Verlaufsfeld stehen.
    $('sp-instr-overlay').classList.remove('hidden');
    $('sp-hist-panel').classList.remove('hidden');
    doc.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape' }));
    await sleep(20);
    check('Escape schliesst zuerst den Dialog',
          $('sp-instr-overlay').classList.contains('hidden')
          && !$('sp-hist-panel').classList.contains('hidden'));
    doc.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape' }));
    await sleep(20);
    check('zweites Escape schliesst das Verlaufsfeld',
          $('sp-hist-panel').classList.contains('hidden'));

    section('9. Leere Eingabe');
    $('sp-analysis').value = '';
    $('sp-question').value = '';
    const calls3 = askCalls;
    $('sp-run').click();
    await sleep(40);
    check('ohne Analyse und ohne Frage wird nichts gesendet', askCalls === calls3);
    check('Hinweis erscheint', $('sp-note').textContent.length > 0 &&
          $('sp-note').classList.contains('is-error'), $('sp-note').textContent);

    section('10. Sprachumschaltung');
    dom.window.setLang('en');
    await sleep(80);
    check('Katalog wurde in Englisch nachgeladen',
          doc.getElementById('sp-analysis').querySelectorAll('option').length === 4);
    check('Beschriftungen folgen der Sprache',
          /Run analysis|Analyse starten/.test($('sp-run').textContent));
    dom.window.setLang('de');
    await sleep(80);

    section('11. i18n-Schluessel vorhanden (DE und EN)');
    {
        const KEYS = ['sap.portal_title', 'sap.analysis', 'sap.bitool', 'sap.run',
                      'sap.result', 'sap.section_bi', 'sap.section_console',
                      'sap.instr_heading', 'sap.hist_empty', 'sap.not_configured',
                      'portal.card_sap', 'portal.card_sap_desc'];
        const missing = [];
        ['de', 'en'].forEach((lg) => {
            dom.window._lang = lg;
            KEYS.forEach((k) => { if (dom.window.t(k) === k) missing.push(lg + ':' + k); });
        });
        dom.window._lang = 'de';
        check('alle neuen Schluessel in beiden Sprachen', missing.length === 0,
              missing.join(', '));
    }
    dom.window.close();

    // ══ 12. Portal-Kachel ════════════════════════════════════════════
    section('12. SAP-Kachel im Portal');
    {
        const p = build('portal.html', { username: 'anna', is_admin: false,
                                         permissions: { sap: true } });
        await sleep(120);
        const card = p.window.document.getElementById('pt-card-sap');
        check('Kachel im Markup vorhanden', card !== null);
        check('Kachel verweist auf /sap', card && card.getAttribute('href') === '/sap');
        check('mit Freigabe sichtbar', card && !card.classList.contains('hidden'));
        p.window.close();
    }
    {
        const p = build('portal.html', { username: 'bob', is_admin: false,
                                         permissions: { sap: false } });
        await sleep(120);
        const card = p.window.document.getElementById('pt-card-sap');
        check('ohne Freigabe verborgen', card && card.classList.contains('hidden'));
        p.window.close();
    }
    {
        const p = build('portal.html', { username: 'alt', is_admin: true });
        await sleep(120);
        const card = p.window.document.getElementById('pt-card-sap');
        check('ohne permissions-Feld verborgen (fail-closed)',
              card && card.classList.contains('hidden'));
        p.window.close();
    }

    // ══ 13. /sap: Verlauf zeigt auf eine ausgeblendete Analyse ═══════
    section('13. Ausgeblendete Analyse im Verlauf');
    {
        // Der Verlauf liegt im Browser und ueberlebt das Ausblenden. Ohne
        // Behandlung spraenge das Feld wortlos auf "freie Frage".
        const d13 = build('sap.html', { username: 'anna', is_admin: false,
                                        permissions: { sap: true } },
            { seedHistory: [{ id: 'weg_damit', title: 'Fruehere Analyse',
                              q: 'alte Frage', tool: 'powerbi', ts: Date.now() }] });
        loadScript(d13, 'js/icons.js');
        loadScript(d13, 'js/i18n.js');
        loadScript(d13, 'js/chatlib.js');
        loadScript(d13, 'js/sap_portal.js');
        await sleep(120);
        const w = d13.window, dc = w.document;
        dc.getElementById('sp-hist-btn').click();
        await sleep(20);
        const row = dc.querySelector('#sp-hist-list .sp-hist-item');
        check('Verlaufseintrag ist da', row !== null);
        const c13 = askCalls;
        row.click();
        await sleep(60);
        check('ausgeblendete Analyse wird nicht gestartet', askCalls === c13);
        check('Auswahl faellt auf leer zurueck',
              dc.getElementById('sp-analysis').value === '');
        check('Hinweis "vom Administrator ausgeblendet"',
              /ausgeblendet|hidden by the administrator/i
                  .test(dc.getElementById('sp-note').textContent),
              dc.getElementById('sp-note').textContent);
        check('Hinweis ist als Fehler markiert',
              dc.getElementById('sp-note').classList.contains('is-error'));
        w.close();
    }

    // ══ 14. Einstellungen → SAP: Sichtbarkeits-Kaestchen ═════════════
    section('14. Einstellungen → SAP: Sichtbarkeit');
    {
        // settings.html ohne die eigenen Skripte laden ('outside-only'):
        // app.js & Co. wuerden hier nur Zeit kosten und fremde Poll-Timer
        // starten. Geprueft wird allein SapManager.
        const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
        let savedBody = null;
        const s = new JSDOM(html, {
            url: 'https://localhost/settings',
            runScripts: 'outside-only',
            beforeParse(win) {
                win.localStorage.setItem('jarvis_token', 'testtoken');
                win.fetch = (url, init) => {
                    const u = String(url);
                    const json = (data) => Promise.resolve({
                        ok: true, status: 200, json: () => Promise.resolve(data),
                    });
                    if (u.startsWith('/api/sap/analyses/catalog')) {
                        return json({
                            lang: 'de',
                            categories: CATALOG.categories,
                            analyses: [
                                { id: 'ar_aging', cat: 'finance', title: 'Debitoren-Altersstruktur',
                                  desc: 'Offene Forderungen.', visible: true },
                                { id: 'working_capital', cat: 'finance', title: 'Working Capital',
                                  desc: 'Kapitalbindung.', visible: false },
                                { id: 'order_backlog', cat: 'sales', title: 'Auftragsbestand',
                                  desc: 'Fruehindikator.', visible: true },
                            ],
                            hidden: ['working_capital'], total: 3,
                        });
                    }
                    if (u.startsWith('/api/skills/sap/config')) {
                        if (init && init.method === 'POST') {
                            savedBody = JSON.parse(init.body);
                            return json({ success: true });
                        }
                        return json({ config: { connection_type: 'odata', hana_password: 'geheim' } });
                    }
                    return json({ ok: true });
                };
            },
        });
        const sd = s.window.document;
        s.window.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
        s.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
        s.window.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
        s.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/sap.js'), 'utf8'));

        check('Abschnitt im Markup vorhanden', sd.getElementById('sap-vis-list') !== null);
        check('Knoepfe im Markup vorhanden',
              sd.getElementById('sap-vis-all') && sd.getElementById('sap-vis-none')
              && sd.getElementById('sap-vis-save'));

        s.window.SapManager.onShow();
        await sleep(120);

        const cbs = () => sd.querySelectorAll('#sap-vis-list .sap-vis-cb');
        check('ein Kaestchen je Analyse', cbs().length === 3, String(cbs().length));
        check('nach Kategorien gruppiert',
              /Finanzen/.test(sd.getElementById('sap-vis-list').textContent)
              && /Vertrieb/.test(sd.getElementById('sap-vis-list').textContent));
        const byId = (id) => sd.querySelector('#sap-vis-list .sap-vis-cb[data-id="' + id + '"]');
        check('sichtbare Analyse ist angehakt', byId('ar_aging').checked === true);
        check('ausgeblendete Analyse ist NICHT angehakt',
              byId('working_capital').checked === false);
        check('Zaehler zeigt 2 von 3',
              /2\D+3/.test(sd.getElementById('sap-vis-count').textContent),
              sd.getElementById('sap-vis-count').textContent);

        // Speichern schickt die AUSGEBLENDETEN – und NUR dieses Feld, sonst
        // ueberschriebe ein Klick hier die Zugangsdaten mit dem Formularstand.
        byId('ar_aging').checked = false;
        byId('ar_aging').dispatchEvent(new s.window.Event('change', { bubbles: true }));
        await sleep(20);
        check('Zaehler folgt der Aenderung',
              /1\D+3/.test(sd.getElementById('sap-vis-count').textContent),
              sd.getElementById('sap-vis-count').textContent);
        sd.getElementById('sap-vis-save').click();
        await sleep(60);
        check('Speichern sendet die ausgeblendeten Ids',
              savedBody && Array.isArray(savedBody.hidden_analyses)
              && savedBody.hidden_analyses.slice().sort().join(',') === 'ar_aging,working_capital',
              JSON.stringify(savedBody));
        check('Speichern sendet NUR dieses Feld (Zugangsdaten unberuehrt)',
              savedBody && Object.keys(savedBody).length === 1,
              JSON.stringify(savedBody && Object.keys(savedBody)));

        sd.getElementById('sap-vis-all').click();
        await sleep(20);
        check('"Alle auswaehlen" hakt alles an',
              Array.prototype.every.call(cbs(), (c) => c.checked));
        savedBody = null;
        sd.getElementById('sap-vis-save').click();
        await sleep(60);
        check('alles sichtbar speichert eine LEERE Liste (leer = alles)',
              savedBody && savedBody.hidden_analyses.length === 0,
              JSON.stringify(savedBody));

        sd.getElementById('sap-vis-none').click();
        await sleep(20);
        check('"Alle abwaehlen" entfernt alle Haken',
              Array.prototype.every.call(cbs(), (c) => !c.checked));
        savedBody = null;
        sd.getElementById('sap-vis-save').click();
        await sleep(60);
        check('alles abgewaehlt speichert ALLE Ids',
              savedBody && savedBody.hidden_analyses.length === 3);

        // Die Verbindungs-Speicherung darf die Sichtbarkeit nicht mitschicken –
        // der Server merged, aber ein mitgesendetes leeres Feld wuerde sie loeschen.
        savedBody = null;
        sd.getElementById('sap-save').click();
        await sleep(60);
        check('Verbindung speichern enthaelt KEIN hidden_analyses',
              savedBody && !('hidden_analyses' in savedBody),
              JSON.stringify(savedBody && Object.keys(savedBody)));

        {
            const KEYS = ['sap.vis_head', 'sap.vis_hint', 'sap.vis_all', 'sap.vis_none',
                          'sap.vis_count', 'sap.vis_load_fail', 'sap.vis_save_fail',
                          'sap.hidden_by_admin'];
            const missing = [];
            ['de', 'en'].forEach((lg) => {
                s.window._lang = lg;
                KEYS.forEach((k) => { if (s.window.t(k) === k) missing.push(lg + ':' + k); });
            });
            check('Sichtbarkeits-Schluessel in beiden Sprachen', missing.length === 0,
                  missing.join(', '));
        }
        s.window.close();
    }

    // ══ 7. "Mein SAP-Zugang": der Aussetzer muss seinen GRUND nennen ══
    //
    // Vorfall 2026-08-25 (ECHT): der Zugang wurde wiederholt ausgesetzt, weil
    // BERECHTIGUNGS-Fehler als Anmeldefehler gezaehlt wurden. Die Oberflaeche
    // blendete im ausgesetzten Zustand `letzter_fehler` aus und sagte nur
    // "Kennwort pruefen" – der tatsaechliche Fehler war NIRGENDS zu sehen, und
    // der Satz schickte den Benutzer an die falsche Stelle. Deshalb ist der
    // Grund Teil der Meldung. Geprueft wird der gerenderte TEXT, nicht der
    // Quelltext: am Quelltext liesse sich nicht ablesen, ob er ankommt.
    section('7. Mein SAP-Zugang: Aussetzer nennt den Grund');
    {
        const GRUND = 'insufficient privilege: Not authorized';
        const d7 = build('sap.html', { username: 'anna', is_admin: true,
                                       permissions: { sap: true } },
                         { account: { vorhanden: true, connection_type: 'hana',
                                      aktiv: true, hana_port: 30015,
                                      anmeldefehler: 3, ausgesetzt: true,
                                      ausgesetzt_grund: GRUND,
                                      letzter_fehler: GRUND,
                                      erlaubte_hosts: [], host_ok: true, cert: {} } });
        loadScript(d7, 'js/i18n.js');
        loadScript(d7, 'js/chatlib.js');
        loadScript(d7, 'js/sap_portal.js');
        await sleep(140);
        const st = d7.window.document.getElementById('sp-acc-status');
        const txt = (st && st.textContent) || '';
        check('Aussetzer-Meldung erscheint', /[Aa]usgesetzt/.test(txt), txt);
        check('...und nennt den tatsaechlichen Grund', txt.indexOf(GRUND) >= 0, txt);
        check('...als Fehler markiert', !!st && /is-error/.test(st.className), st && st.className);
        d7.window.close();
    }
    {
        // Gegenrichtung: ohne Aussetzer wird der Grund NICHT drangehaengt –
        // sonst stuende an einem gesunden Zugang ein alter Fehlertext.
        const d7b = build('sap.html', { username: 'anna', is_admin: true,
                                        permissions: { sap: true } },
                          { account: { vorhanden: true, connection_type: 'odata',
                                       aktiv: true, hana_port: 443,
                                       anmeldefehler: 0, ausgesetzt: false,
                                       ausgesetzt_grund: 'alter Text von frueher',
                                       letzter_fehler: '',
                                       erlaubte_hosts: [], host_ok: true, cert: {} } });
        loadScript(d7b, 'js/i18n.js');
        loadScript(d7b, 'js/chatlib.js');
        loadScript(d7b, 'js/sap_portal.js');
        await sleep(140);
        const st = d7b.window.document.getElementById('sp-acc-status');
        const txt = (st && st.textContent) || '';
        check('ohne Aussetzer keine Aussetzer-Meldung', !/[Aa]usgesetzt nach/.test(txt), txt);
        check('...und kein alter Grund im Text', txt.indexOf('alter Text von frueher') < 0, txt);
        d7b.window.close();
    }
    {
        // Der neue Schluessel muss in BEIDEN Sprachen existieren, sonst steht
        // im englischen Portal der Schluesselname im Fehlertext.
        const d7c = build('sap.html', { username: 'anna', is_admin: true,
                                        permissions: { sap: true } });
        loadScript(d7c, 'js/i18n.js');
        await sleep(40);
        const fehlt = [];
        ['de', 'en'].forEach((lg) => {
            d7c.window._lang = lg;
            if (d7c.window.t('sap.acc_last_error') === 'sap.acc_last_error') fehlt.push(lg);
        });
        check('sap.acc_last_error in beiden Sprachen', fehlt.length === 0, fehlt.join(', '));
        d7c.window.close();
    }

    // ══ 15. Verbindungstest: Bericht fuer den SAP-Administrator ══════
    // Gemeldet 2026-10-30: "Katalog erreichbar (1+ Services)" bzw. "22
    // EntitySet(s)" – der Administrator konnte nicht ablesen, WAS geprueft
    // wurde. Geprueft wird der GERENDERTE Bericht samt kopiertem Text, im
    // Erfolgs- UND im Fehlerfall (dann fragt der Administrator nach).
    section('15. Verbindungstest: Bericht');
    async function testLauf(antwort) {
        const d = build('sap.html', { username: 'anna', is_admin: true, permissions: { sap: true } },
                        { account: { vorhanden: true, connection_type: 'odata', aktiv: true,
                                     erlaubte_hosts: [], host_ok: true, cert: {} },
                          sapTest: antwort });
        loadScript(d, 'js/i18n.js');
        loadScript(d, 'js/chatlib.js');
        loadScript(d, 'js/sap_portal.js');
        await sleep(140);
        const kopiert = [];
        d.window.JarvisChatLib = Object.assign({}, d.window.JarvisChatLib || {}, {
            copyTextToClipboard: (t) => { kopiert.push(t); return Promise.resolve(); },
        });
        const box = d.window.document.getElementById('sp-acc-testinfo');
        const vorher = !!box && box.hidden === true;
        d.window.document.getElementById('sp-acc-test').click();
        await sleep(120);
        return { d, box, vorher, kopiert, doc: d.window.document };
    }
    function zeilenVon(box) {
        const z = {};
        const dts = box.querySelectorAll('.sp-ti-grid dt');
        dts.forEach((dt) => { z[dt.textContent] = dt.nextElementSibling ? dt.nextElementSibling.textContent : null; });
        return z;
    }
    const SETS15 = ['Artikel', 'Bestellungen', 'Kunden'];
    const ADR15 = 'https://sap.example/sap/opu/odata/ZSVC_SRV/$metadata?sap-client=100';
    {
        const r = await testLauf({
            ok: true, configured: true, type: 'odata', quelle: 'persoenlich',
            detail: 'Service ZSVC_SRV: 3 EntitySet(s) definiert',
            info: { variante: 'service', geschaeftsdaten_gelesen: false,
                    basis: 'https://sap.example/sap/opu/odata', service: 'ZSVC_SRV',
                    mandant: '100', anmeldeart: 'basic', benutzer: 'SAPUSER1',
                    entity_sets: SETS15, adresse: ADR15, http_status: 200, dauer_ms: 87 },
        });
        check('Bericht ist vor dem Test verborgen', r.vorher);
        check('Bericht erscheint nach dem Test', !!r.box && r.box.hidden === false);
        const z = r.box ? zeilenVon(r.box) : {};
        check('Zeile: aufgerufene Adresse', z['Aufgerufene Adresse'] === ADR15, JSON.stringify(z));
        check('Zeile: Standard-Service', z['Standard-Service'] === 'ZSVC_SRV', JSON.stringify(z));
        check('Zeile: Mandant', z['Mandant'] === '100', JSON.stringify(z));
        check('Zeile: SAP-Benutzer', z['SAP-Benutzer'] === 'SAPUSER1', JSON.stringify(z));
        check('Zeile: Anmeldeart in Worten', /Basic/.test(z['Anmeldeart'] || ''), z['Anmeldeart']);
        check('Zeile: HTTP-Status', z['HTTP-Status'] === '200', z['HTTP-Status']);
        check('Zeile: Antwortzeit', z['Antwortzeit'] === '87 ms', z['Antwortzeit']);
        check('Zeile: Zahl der EntitySets', z['EntitySets im Service'] === '3', z['EntitySets im Service']);
        const li = r.box ? [...r.box.querySelectorAll('.sp-ti-sets li')].map((x) => x.textContent) : [];
        check('EntitySet-Namen aufklappbar gelistet', JSON.stringify(li) === JSON.stringify(SETS15), JSON.stringify(li));
        const head = (r.box && r.box.querySelector('.sp-ti-head')) ? r.box.querySelector('.sp-ti-head').textContent : '';
        check('Kopfsatz erklaert die Pruefart ($metadata)', /\$metadata/.test(head) && /keine Datensätze/.test(head), head);
        check('Fusszeile: keine Geschaeftsdaten gelesen',
              /keine Geschäftsdaten/.test(r.box ? r.box.textContent : ''));
        check('Bericht nicht als Fehler markiert', r.box && !r.box.classList.contains('is-error'));
        check('Statuszeile bleibt die Kurzmeldung',
              /3 EntitySet/.test(r.doc.getElementById('sp-acc-status').textContent),
              r.doc.getElementById('sp-acc-status').textContent);

        const knopf = r.doc.getElementById('sp-acc-ti-copy');
        check('Kopierknopf vorhanden', !!knopf);
        if (knopf) knopf.click();
        await sleep(30);
        const txt = r.kopiert[0] || '';
        check('Kopieren liefert Text', txt.length > 0);
        const fehlend = Object.keys(z).filter((k) => txt.indexOf(k + ': ' + z[k]) < 0);
        check('kopierter Text enthaelt JEDE angezeigte Zeile woertlich', fehlend.length === 0 && Object.keys(z).length > 5,
              fehlend.join(', '));
        check('kopierter Text listet alle EntitySets', SETS15.every((n) => txt.indexOf('  ' + n) >= 0), txt);
        check('kopierter Text nennt Ergebnis und Fusszeile',
              /Ergebnis: erfolgreich/.test(txt) && /keine Geschäftsdaten/.test(txt), txt.slice(0, 200));
        check('kein "undefined"/"null" im kopierten Text', !/undefined|null/.test(txt));
        check('Rueckmeldung am Kopierknopf',
              /kopiert/i.test((r.doc.getElementById('sp-acc-ti-note') || {}).textContent || ''));

        // Sprachwechsel: der Bericht wird neu gezeichnet.
        r.d.window.setLang('en');
        await sleep(40);
        const zEn = r.box ? zeilenVon(r.box) : {};
        check('nach Sprachwechsel englische Beschriftung', zEn['Requested address'] === ADR15, JSON.stringify(Object.keys(zEn)));
        r.d.window.close();
    }
    {
        const r = await testLauf({
            ok: false, configured: true, status: 401, type: 'odata', quelle: 'persoenlich',
            error: 'Anmeldung abgelehnt',
            info: { variante: 'katalog', geschaeftsdaten_gelesen: false,
                    basis: 'https://sap.example/sap/opu/odata', service: '', mandant: '',
                    anmeldeart: 'basic', benutzer: 'SAPUSER1',
                    adresse: 'https://sap.example/sap/opu/odata/iwfnd/catalogservice;v=2/ServiceCollection?$top=1',
                    http_status: 401, dauer_ms: 12 },
        });
        check('Fehlerfall: Bericht erscheint trotzdem', !!r.box && r.box.hidden === false);
        check('Fehlerfall: als Fehler markiert', !!r.box && r.box.classList.contains('is-error'));
        const z = r.box ? zeilenVon(r.box) : {};
        check('Fehlerfall: HTTP-Status 401 sichtbar', z['HTTP-Status'] === '401', JSON.stringify(z));
        check('Fehlerfall: leerer Mandant wird erklaert', /Standardmandant/.test(z['Mandant'] || ''), z['Mandant']);
        check('Fehlerfall: kein Service = "keiner"', /keiner/.test(z['Standard-Service'] || ''), z['Standard-Service']);
        check('Fehlerfall: Kopfsatz erklaert den Katalog-Test',
              /CATALOGSERVICE/.test((r.box.querySelector('.sp-ti-head') || {}).textContent || ''));
        check('Fehlerfall: Statuszeile nennt den Fehler',
              /Anmeldung abgelehnt/.test(r.doc.getElementById('sp-acc-status').textContent));
        const knopf = r.doc.getElementById('sp-acc-ti-copy');
        if (knopf) knopf.click();
        await sleep(30);
        check('Fehlerfall: kopierter Bericht sagt "fehlgeschlagen" und nennt den Fehler',
              /Ergebnis: fehlgeschlagen/.test(r.kopiert[0] || '') && /Anmeldung abgelehnt/.test(r.kopiert[0] || ''),
              (r.kopiert[0] || '').slice(0, 200));
        r.d.window.close();
    }
    // ══ 16. Abfrage-Konsole: Auswahllisten ══════════════════════════
    // Gewuenscht 2026-10-30: unter Abfrage-Konsole -> EntitySet sollen Listen
    // abrufbar sein. Geprueft wird die WIRKUNG am DOM: was in den <datalist>
    // steht, wann geladen wird, und dass eine veraltete Antwort die Liste
    // eines inzwischen anderen Service nicht ueberschreibt.
    section('16. Abfrage-Konsole: Auswahllisten');
    const SETS16 = {
        '': { ok: true, service: 'sap/ZDEF_SRV', entity_sets: ['D1', 'D2'], count: 2 },
        'sap/ZA_SRV': { ok: true, service: 'sap/ZA_SRV', entity_sets: ['A1', 'A2', 'A3'], count: 3 },
        'sap/ZB_SRV': { ok: true, service: 'sap/ZB_SRV', entity_sets: ['B1'], count: 1 },
    };
    async function konsole(odServices, odSets, vorher, extra) {
        const calls = [], offen = [];
        const d = build('sap.html', { username: 'anna', is_admin: true, permissions: { sap: true } },
                        Object.assign({ odServices, odSets, odCalls: calls, odOffen: offen }, extra || {}));
        loadScript(d, 'js/i18n.js');
        loadScript(d, 'js/sap_portal.js');
        await sleep(140);
        const doc = d.window.document;
        if (vorher) vorher(doc);
        // jsdom feuert `toggle` beim Setzen von `open` SELBST (nachgemessen) –
        // ein zusaetzliches dispatchEvent waere ein zweites Oeffnen, das es im
        // Browser nicht gibt, und verfaelschte die Zaehlung der Abrufe.
        const con = doc.getElementById('sp-sect-console');
        let toggles = 0;
        con.addEventListener('toggle', () => { toggles++; });
        con.open = true;
        await sleep(60);
        if (toggles !== 1) {
            console.log('  ABBRUCH: erwartet genau ein toggle-Ereignis, gesehen ' + toggles + ' – Messaufbau unbrauchbar.');
            process.exit(2);
        }
        return { d, doc, calls, offen };
    }
    // Vor dem Schliessen auf ALLE noch laufenden Antworten warten: eine
    // verzoegerte Antwort, die nach close() ankommt, trifft ein geschlossenes
    // Dokument – der Absturz machte aus einem Biss ein "konnte nicht laufen"
    // (von der Gegenprobe "kein Gedaechtnis je Service" gefunden).
    async function schliessen(r) {
        await Promise.all(r.offen || []);
        await sleep(10);
        r.d.window.close();
    }
    const werte = (doc, id) => [...doc.querySelectorAll('#' + id + ' option')].map((o) => o.value);
    const zaehle = (calls, teil) => calls.filter((u) => u.indexOf(teil) >= 0).length;
    {
        let callsVorOeffnen = -1;
        const SVC = { ok: true, genau: true, ausgelassen: 2, count: 3, services: [
            { service: 'sap/ZA_SRV', title: 'A-Service' },
            { service: 'sap/ZB_SRV', title: '<img src=x onerror=1>' },
            { service: 'sap/ZC_SRV', title: '' },
        ] };
        const r = await konsole(SVC, (svc) => ({
            data: SETS16[svc] || { ok: false, error: 'unbekannt' },
            delay: svc === 'sap/ZA_SRV' ? 150 : 5,
        }), (doc) => { callsVorOeffnen = 0; });
        const { doc, calls } = r;
        check('Felder haengen an ihren Listen',
              doc.getElementById('sp-od-service').getAttribute('list') === 'sp-od-service-list'
              && doc.getElementById('sp-od-entity').getAttribute('list') === 'sp-od-entity-list'
              && !!doc.getElementById('sp-od-service-list') && !!doc.getElementById('sp-od-entity-list'));
        check('Service-Liste gefuellt (Werte = relative Pfade)',
              JSON.stringify(werte(doc, 'sp-od-service-list')) === JSON.stringify(['sap/ZA_SRV', 'sap/ZB_SRV', 'sap/ZC_SRV']),
              JSON.stringify(werte(doc, 'sp-od-service-list')));
        const opt = doc.querySelector('#sp-od-service-list option[value="sap/ZA_SRV"]');
        check('Titel als Beschriftung', !!opt && opt.getAttribute('label') === 'A-Service');
        check('Titel wird nicht als Markup ausgewertet',
              !doc.querySelector('#sp-od-service-list img')
              && (doc.querySelector('#sp-od-service-list option[value="sap/ZB_SRV"]') || { getAttribute: () => '' })
                  .getAttribute('label') === '<img src=x onerror=1>');
        const sh = doc.getElementById('sp-od-svc-hint').textContent;
        check('Service-Hinweis nennt Zahl und Ausgelassene', /3 Services/.test(sh) && /\(2 weitere/.test(sh), sh);
        check('ohne Service: EntitySets des Standard-Service',
              JSON.stringify(werte(doc, 'sp-od-entity-list')) === '["D1","D2"]', JSON.stringify(werte(doc, 'sp-od-entity-list')));
        const eh = doc.getElementById('sp-od-entity-hint').textContent;
        check('EntitySet-Hinweis nennt Zahl und tatsaechlichen Service', /2 EntitySets/.test(eh) && /sap\/ZDEF_SRV/.test(eh), eh);

        // Langsame Antwort (ZA) darf die Liste des danach gewaehlten ZB nicht ueberschreiben.
        const feld = doc.getElementById('sp-od-service');
        feld.value = 'sap/ZA_SRV'; feld.dispatchEvent(new r.d.window.Event('change'));
        await sleep(10);
        feld.value = 'sap/ZB_SRV'; feld.dispatchEvent(new r.d.window.Event('change'));
        await sleep(260);
        check('veraltete Antwort ueberschreibt die neue Liste nicht',
              JSON.stringify(werte(doc, 'sp-od-entity-list')) === '["B1"]', JSON.stringify(werte(doc, 'sp-od-entity-list')));
        check('...und der Hinweis gehoert zum aktuellen Service',
              /sap\/ZB_SRV/.test(doc.getElementById('sp-od-entity-hint').textContent),
              doc.getElementById('sp-od-entity-hint').textContent);
        const zaVorher = zaehle(calls, 'service=sap%2FZA_SRV');
        feld.value = 'sap/ZA_SRV'; feld.dispatchEvent(new r.d.window.Event('change'));
        await sleep(20);
        check('zurueck auf ZA: aus dem Gedaechtnis, ohne neue Anfrage',
              zaehle(calls, 'service=sap%2FZA_SRV') === zaVorher && zaVorher === 1
              && JSON.stringify(werte(doc, 'sp-od-entity-list')) === '["A1","A2","A3"]',
              zaVorher + ' / ' + JSON.stringify(werte(doc, 'sp-od-entity-list')));
        doc.getElementById('sp-od-service').dispatchEvent(new r.d.window.Event('focus'));
        doc.getElementById('sp-od-entity').dispatchEvent(new r.d.window.Event('focus'));
        await sleep(20);
        check('Katalog wird je Seite nur einmal abgefragt', zaehle(calls, '/odata/services') === 1,
              String(zaehle(calls, '/odata/services')));
        check('Fokus ohne Aenderung fragt nicht neu', zaehle(calls, 'service=sap%2FZA_SRV') === 1);
        await schliessen(r);
    }
    {
        // Geladen wird erst, wenn die OData-Konsole SICHTBAR ist.
        const calls = [];
        const d = build('sap.html', { username: 'anna', is_admin: true, permissions: { sap: true } },
                        { odServices: { ok: true, services: [], count: 0, genau: true, ausgelassen: 0 },
                          odSets: () => ({ data: SETS16[''] }), odCalls: calls });
        loadScript(d, 'js/i18n.js');
        loadScript(d, 'js/sap_portal.js');
        await sleep(140);
        const doc = d.window.document;
        check('Seitenaufbau fragt keine Liste ab', calls.length === 0, calls.join(', '));
        doc.getElementById('sp-tab-sql').click();
        const con = doc.getElementById('sp-sect-console');
        con.open = true;
        await sleep(40);
        check('Konsole auf SQL geoeffnet: keine OData-Liste', calls.length === 0, calls.join(', '));
        doc.getElementById('sp-tab-odata').click();
        await sleep(40);
        check('Wechsel auf OData laedt beide Listen',
              zaehle(calls, '/odata/services') === 1 && zaehle(calls, '/odata/entity-sets') === 1, calls.join(', '));
        d.window.close();
    }
    {
        // Fehlerfaelle: kein Katalog (Dauerzustand, kein Wiederholen) und
        // kein Service (Hinweis, kein Fehler; beim naechsten Fokus neu).
        const r = await konsole({ ok: false, kein_katalog: true, status: 404, error: 'HTTP 404' },
                                () => ({ data: { ok: false, kein_service: true, error: 'Kein Service' } }));
        const { doc, calls } = r;
        const sh = doc.getElementById('sp-od-svc-hint');
        check('kein Katalog: Hinweis als Fehler', /keinen Gateway-Katalog/.test(sh.textContent)
              && sh.classList.contains('is-error'), sh.textContent);
        const eh = doc.getElementById('sp-od-entity-hint');
        check('kein Service: Anleitung, nicht als Fehler', /Standard-Service/.test(eh.textContent)
              && !eh.classList.contains('is-error'), eh.textContent + ' ' + eh.className);
        doc.getElementById('sp-od-service').dispatchEvent(new r.d.window.Event('focus'));
        doc.getElementById('sp-od-entity').dispatchEvent(new r.d.window.Event('focus'));
        await sleep(30);
        check('kein Katalog: kein erneuter Abruf', zaehle(calls, '/odata/services') === 1,
              String(zaehle(calls, '/odata/services')));
        check('kein Service: naechster Fokus fragt erneut', zaehle(calls, '/odata/entity-sets') === 2,
              String(zaehle(calls, '/odata/entity-sets')));
        await schliessen(r);
    }
    {
        const r = await konsole({ ok: false, status: 403, error: 'Keine Berechtigung' },
                                () => ({ data: SETS16[''] }));
        const sh = r.doc.getElementById('sp-od-svc-hint');
        check('anderer Fehler: Grund steht am Feld', /Keine Berechtigung/.test(sh.textContent)
              && sh.classList.contains('is-error'), sh.textContent);
        r.doc.getElementById('sp-od-service').dispatchEvent(new r.d.window.Event('focus'));
        await sleep(30);
        check('anderer Fehler: naechster Fokus versucht es erneut', zaehle(r.calls, '/odata/services') === 2,
              String(zaehle(r.calls, '/odata/services')));
        await schliessen(r);
    }
    // ══ 17. Nicht direkt abrufbare EntitySets / Standard-Service-Liste ═══
    // Gemeldet 2026-10-30: "Ressource fuer Segment 'A_SalesOrderText' nicht
    // gefunden", obwohl das Set in der Liste stand. Die Service-Beschreibung
    // markiert solche Sets (sap:addressable="false") – die Konsole nennt das
    // und den Weg dorthin, aber NUR, wenn es gemessen ist.
    section('17. Nur ueber Navigation / Standard-Service-Liste');
    const SO = {
        ok: true, service: 'sap/API_SALES_ORDER_SRV', count: 4,
        entity_sets: ['A_SalesOrder', 'A_SalesOrderItem', 'A_SalesOrderItemText', 'A_SalesOrderText'],
        details: [
            { name: 'A_SalesOrder', addressable: true, navigation: [] },
            { name: 'A_SalesOrderItem', addressable: true,
              navigation: [{ von: 'A_SalesOrder', property: 'to_Item', schluessel: ['SalesOrder'] }] },
            { name: 'A_SalesOrderItemText', addressable: false,
              navigation: [{ von: 'A_SalesOrderItem', property: 'to_ItemText', schluessel: ['SalesOrder', 'SalesOrderItem'] }] },
            { name: 'A_SalesOrderText', addressable: false,
              navigation: [{ von: 'A_SalesOrder', property: 'to_Text', schluessel: ['SalesOrder'] }] },
        ],
    };
    const WEG_TEXT = "A_SalesOrder('<SalesOrder>')/to_Text";
    const WEG_ITEM = "A_SalesOrderItem(SalesOrder='<SalesOrder>',SalesOrderItem='<SalesOrderItem>')/to_ItemText";
    const FEHLER404 = "Ressource für Segment 'A_SalesOrderText' nicht gefunden";
    {
        const r = await konsole({ ok: true, services: [], count: 0, genau: true, ausgelassen: 0 },
                                () => ({ data: SO }), null,
                                { odQuery: () => ({ ok: false, status: 404, error: FEHLER404 }) });
        const { doc, d } = r;
        const label = (v) => { const o = doc.querySelector('#sp-od-entity-list option[value="' + v + '"]'); return o ? o.getAttribute('label') : '(fehlt)'; };
        check('Liste: nicht abrufbares Set mit Weg beschriftet',
              label('A_SalesOrderText') === 'nur über Navigation: ' + WEG_TEXT, label('A_SalesOrderText'));
        check('Liste: zusammengesetzter Schluessel im Weg', label('A_SalesOrderItemText') === 'nur über Navigation: ' + WEG_ITEM,
              label('A_SalesOrderItemText'));
        check('Liste: abrufbares Set ohne Beschriftung', label('A_SalesOrder') === null, String(label('A_SalesOrder')));
        const eh = () => doc.getElementById('sp-od-entity-hint').textContent;
        check('Zaehl-Hinweis nennt die nur ueber Navigation erreichbaren', /\(davon 2 nur über Navigation/.test(eh()), eh());
        const feld = doc.getElementById('sp-od-entity');
        feld.value = 'A_SalesOrderText'; feld.dispatchEvent(new d.window.Event('input'));
        check('Auswahl: Hinweis mit Weg sofort am Feld', eh().indexOf(WEG_TEXT) >= 0 && /nicht direkt abrufbar/.test(eh()), eh());
        feld.value = 'A_SalesOrder'; feld.dispatchEvent(new d.window.Event('input'));
        check('anderes Set: Zaehl-Hinweis kehrt zurueck', /4 EntitySets/.test(eh()) && eh().indexOf(WEG_TEXT) < 0, eh());

        const out = () => doc.getElementById('sp-console-out').textContent;
        // "nichts geraten" = unter dem Fehler steht KEIN Zusatzhinweis. Erst
        // wurde nach Woertern gesucht ("Navigation") – der Navigationshinweis
        // enthaelt keines davon, zwei Gegenproben blieben deshalb stumm.
        const zusatz = () => doc.querySelector('#sp-console-out .sp-od-hint');
        const abfrage = async (wert) => { feld.value = wert; doc.getElementById('sp-od-run').click(); await sleep(40); };
        await abfrage('A_SalesOrderText');
        check('404 bei nicht abrufbarem Set: Fehler UND Weg (als Zusatzhinweis)',
              out().indexOf(FEHLER404) >= 0 && !!zusatz() && zusatz().textContent.indexOf(WEG_TEXT) >= 0, out());
        await abfrage('A_Salesordertext');
        check('404 bei Set ausserhalb der Liste: Schreibweise/Service pruefen',
              /steht nicht in der EntitySet-Liste von „sap\/API_SALES_ORDER_SRV“/.test(out()), out());
        await abfrage('A_SalesOrder');
        check('404 bei abrufbarem Set: nichts geraten', out().indexOf(FEHLER404) >= 0 && !zusatz(), out());
        await abfrage("A_SalesOrder('1')/to_Text");
        check('404 bei eingegebenem Pfad: nichts geraten', out().indexOf(FEHLER404) >= 0 && !zusatz(), out());

        // Anderer Service eingetragen, fuer den keine Liste geladen ist: nichts behaupten.
        doc.getElementById('sp-od-service').value = 'sap/ANDERER_SRV';
        await abfrage('A_SalesOrderText');
        check('404 ohne geladene Liste fuer diesen Service: nichts behauptet',
              out().indexOf(FEHLER404) >= 0 && !zusatz(), out());
        await schliessen(r);
    }
    {
        // Standard-Service-Liste: nur aus dem gespeicherten EIGENEN Zugang.
        const SVC = { ok: true, genau: true, ausgelassen: 0, count: 2, services: [
            { service: 'sap/API_SALES_ORDER_SRV', title: 'Kundenaufträge' },
            { service: 'sap/ZFI_AR_SRV', title: 'Debitoren' } ] };
        const calls = [], offen = [];
        const d = build('sap.html', { username: 'anna', is_admin: true, permissions: { sap: true } },
                        { status: { quelle: 'persoenlich' }, odServices: SVC, odCalls: calls, odOffen: offen,
                          odSets: (svc) => ({ data: svc ? SO : SO, delay: 120 }),
                          account: { vorhanden: true, connection_type: 'odata', aktiv: true,
                                     erlaubte_hosts: [], host_ok: true, cert: {} } });
        loadScript(d, 'js/i18n.js');
        loadScript(d, 'js/sap_portal.js');
        await sleep(160);
        const doc = d.window.document;
        const acc = doc.getElementById('sp-acc-od-service');
        check('Standard-Service haengt an seiner Liste',
              acc.getAttribute('list') === 'sp-acc-od-service-list' && !!doc.getElementById('sp-acc-od-service-list'));
        check('ohne Fokus kein Abruf', zaehle(calls, '/odata/services') === 0, calls.join(', '));
        acc.dispatchEvent(new d.window.Event('focus'));
        await sleep(40);
        check('eigener Zugang: Liste im Standard-Service-Feld',
              JSON.stringify(werte(doc, 'sp-acc-od-service-list')) === '["sap/API_SALES_ORDER_SRV","sap/ZFI_AR_SRV"]',
              JSON.stringify(werte(doc, 'sp-acc-od-service-list')));
        check('eigener Zugang: Hinweis am Feld', /2 Services im Katalog/.test(doc.getElementById('sp-acc-od-service-hint').textContent),
              doc.getElementById('sp-acc-od-service-hint').textContent);
        const con = doc.getElementById('sp-sect-console');
        con.open = true;
        await sleep(40);
        check('Konsole nutzt dieselbe Antwort (kein zweiter Abruf)', zaehle(calls, '/odata/services') === 1,
              String(zaehle(calls, '/odata/services')));

        // Speichern verwirft gemerkte Listen – auch eine noch laufende Antwort.
        const setsVorher = zaehle(calls, '/odata/entity-sets');
        doc.getElementById('sp-acc-type').value = 'odata';
        doc.getElementById('sp-acc-save').click();
        await sleep(30);
        check('Speichern leert die Listen',
              werte(doc, 'sp-acc-od-service-list').length === 0 && werte(doc, 'sp-od-service-list').length === 0,
              JSON.stringify([werte(doc, 'sp-acc-od-service-list'), werte(doc, 'sp-od-service-list')]));
        await Promise.all(offen); await sleep(20);
        check('...und eine danach eintreffende alte Antwort fuellt nichts',
              werte(doc, 'sp-od-entity-list').length === 0, JSON.stringify(werte(doc, 'sp-od-entity-list')));
        acc.dispatchEvent(new d.window.Event('focus'));
        doc.getElementById('sp-od-entity').dispatchEvent(new d.window.Event('focus'));
        await sleep(40);
        check('nach dem Speichern: Service-Liste neu abgefragt', zaehle(calls, '/odata/services') === 2,
              String(zaehle(calls, '/odata/services')));
        check('nach dem Speichern: EntitySets neu abgefragt (nichts Altes gemerkt)',
              zaehle(calls, '/odata/entity-sets') === setsVorher + 1, zaehle(calls, '/odata/entity-sets') + ' / ' + setsVorher);
        await Promise.all(offen); await sleep(20);
        d.window.close();
    }
    {
        // Ohne eigenen Zugang: keine Liste aus dem Sammelzugang im Feld.
        const calls = [];
        const d = build('sap.html', { username: 'anna', is_admin: true, permissions: { sap: true } },
                        { status: { quelle: 'sammel' }, odCalls: calls,
                          odServices: { ok: true, genau: true, ausgelassen: 0, count: 1,
                                        services: [{ service: 'sap/SAMMEL_SRV', title: 'fremd' }] },
                          odSets: () => ({ data: SO }) });
        loadScript(d, 'js/i18n.js');
        loadScript(d, 'js/sap_portal.js');
        await sleep(160);
        const doc = d.window.document;
        doc.getElementById('sp-acc-od-service').dispatchEvent(new d.window.Event('focus'));
        await sleep(30);
        check('Sammelzugang: Fokus fragt nichts ab', zaehle(calls, '/odata/services') === 0, calls.join(', '));
        check('Sammelzugang: Hinweis "erst speichern"',
              /gespeicherten eigenen Zugang/.test(doc.getElementById('sp-acc-od-service-hint').textContent),
              doc.getElementById('sp-acc-od-service-hint').textContent);
        const con = doc.getElementById('sp-sect-console');
        con.open = true;
        await sleep(40);
        check('Sammelzugang: Konsole bekommt ihre Liste', werte(doc, 'sp-od-service-list').length === 1);
        check('...aber nichts davon landet im Standard-Service-Feld', werte(doc, 'sp-acc-od-service-list').length === 0,
              JSON.stringify(werte(doc, 'sp-acc-od-service-list')));
        d.window.close();
    }
    // ══ 18. Mitladen ($expand) ═══════════════════════════════════════
    // Gewuenscht 2026-10-30: die Texte VIELER Auftraege auf einmal – also
    // A_SalesOrder mit $expand=to_Text. Gemessen wird: welche Navigationen
    // angeboten werden (abgehend, nicht eingehend), dass der Wert in der
    // Abfrage ankommt, und dass mitgeladene Daten als Tabelle in der Zelle
    // stehen statt als "[object Object]".
    section('18. Mitladen ($expand)');
    {
        const abfragen = [];
        const r = await konsole({ ok: true, services: [], count: 0, genau: true, ausgelassen: 0 },
                                () => ({ data: SO }), null,
                                { odQuery: (e, q) => {
                                    abfragen.push(q.get('expand'));
                                    return { ok: true, columns: ['SalesOrder', 'to_Text'], rows: [
                                        { SalesOrder: '1', to_Text: [{ Language: 'DE', LongText: '<b>Hallo</b>' },
                                                                     { Language: 'EN', LongText: 'Hello' }] },
                                        { SalesOrder: '2', to_Text: [] },
                                        { SalesOrder: '3', to_Text: [{ Tief: { A: { B: 1 } } }] },
                                    ] };
                                } });
        const { doc, d } = r;
        const ex = doc.getElementById('sp-od-expand');
        check('Mitladen-Feld haengt an seiner Liste',
              !!ex && ex.getAttribute('list') === 'sp-od-expand-list' && !!doc.getElementById('sp-od-expand-list'));
        const feld = doc.getElementById('sp-od-entity');
        const eh = () => doc.getElementById('sp-od-expand-hint').textContent;
        feld.value = 'A_SalesOrder'; feld.dispatchEvent(new d.window.Event('input'));
        check('A_SalesOrder: abgehende Navigationen angeboten',
              JSON.stringify(werte(doc, 'sp-od-expand-list')) === '["to_Item","to_Text"]', JSON.stringify(werte(doc, 'sp-od-expand-list')));
        const lab = doc.querySelector('#sp-od-expand-list option[value="to_Text"]');
        check('Vorschlag nennt das Ziel', !!lab && lab.getAttribute('label') === '→ A_SalesOrderText');
        check('Hinweis nennt die Mitladbaren', /Mitladbar für „A_SalesOrder“: to_Item, to_Text/.test(eh()), eh());
        feld.value = 'A_SalesOrderText'; feld.dispatchEvent(new d.window.Event('input'));
        check('Set ohne abgehende Navigation: keine Vorschlaege, Hinweis sagt es',
              werte(doc, 'sp-od-expand-list').length === 0 && /keine Navigation zum Mitladen/.test(eh()), eh());
        check('Navigationshinweis nennt den Weg ueber Mitladen',
              /„A_SalesOrder“ abfragen und unter „Mitladen“ to_Text eintragen/.test(doc.getElementById('sp-od-entity-hint').textContent),
              doc.getElementById('sp-od-entity-hint').textContent);
        feld.value = 'Unbekannt'; feld.dispatchEvent(new d.window.Event('input'));
        check('unbekanntes Set: nichts angeboten, nichts behauptet', werte(doc, 'sp-od-expand-list').length === 0 && eh() === '', eh());

        feld.value = 'A_SalesOrder'; ex.value = ' to_Text ';
        doc.getElementById('sp-od-run').click();
        await sleep(40);
        check('Abfrage traegt expand=to_Text', abfragen[abfragen.length - 1] === 'to_Text', JSON.stringify(abfragen));
        const out = doc.getElementById('sp-console-out');
        const innen = out.querySelectorAll('td table');
        check('mitgeladene Texte als Tabelle in der Zelle', innen.length >= 2 && /LongText/.test(innen[0].textContent)
              && /Hello/.test(innen[0].textContent), String(innen.length));
        check('kein "[object Object]" in der Ausgabe', out.textContent.indexOf('[object Object]') < 0);
        check('Inhalt wird nicht als Markup ausgewertet', !out.querySelector('b') && out.textContent.indexOf('<b>Hallo</b>') >= 0);
        check('leere Liste als Strich', /—/.test(out.querySelectorAll('tbody > tr')[1] ? out.querySelector('tbody').children[1].textContent : ''),
              out.querySelector('tbody') ? out.querySelector('tbody').children[1].textContent : '');
        check('dritte Ebene als Text statt weiterer Tabelle', out.textContent.indexOf('{"B":1}') >= 0, out.textContent.slice(-120));
        ex.value = '';
        doc.getElementById('sp-od-run').click();
        await sleep(40);
        check('ohne Mitladen kein expand-Parameter', abfragen[abfragen.length - 1] === null, JSON.stringify(abfragen));
        await schliessen(r);
    }
    {
        // Jeder im Modul benutzte sap.ti_*-Schluessel existiert in BEIDEN
        // Sprachen – gelesen aus dem Quelltext, nicht abgetippt. t() faellt
        // auf Deutsch zurueck und `_I18N` ist im eval-Bereich nicht
        // erreichbar, deshalb wird i18n.js an der Grenze `en: {` geteilt.
        const quelle = fs.readFileSync(PORTAL_JS, 'utf8');
        // JEDES 'sap.ti_…'-Literal, nicht nur T('…'): die Zeilen laufen ueber
        // den Helfer add('sap.ti_…', …) – ein Muster nur auf T( war fuer sie
        // blind (von der Gegenprobe gefunden).
        const keys = [...new Set([...quelle.matchAll(/'(sap\.(?:ti|od|acc_svc)_[a-z_]+)'/g)].map((m) => m[1]))];
        const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        const grenze = i18n.search(/\n\s*en\s*:\s*\{/);
        const bloecke = { de: grenze > 0 ? i18n.slice(0, grenze) : '', en: grenze > 0 ? i18n.slice(grenze) : '' };
        check('Positivkontrolle: sap.ti_*/sap.od_*-Schluessel im Modul gefunden',
              keys.length >= 30 && keys.some((k) => k.indexOf('sap.od_') === 0), String(keys.length));
        check('Positivkontrolle: Sprachgrenze in i18n.js gefunden',
              grenze > 0 && bloecke.de.indexOf("'sap.acc_removed':") >= 0 && bloecke.en.indexOf("'sap.acc_removed':") >= 0);
        const fehlt = [];
        keys.forEach((k) => ['de', 'en'].forEach((lg) => {
            if (bloecke[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k);
        }));
        check('alle sap.ti_*/sap.od_*-Schluessel in DE und EN', fehlt.length === 0, fehlt.join(', '));
    }

    // ── Ergebnis ────────────────────────────────────────────────────
    const ok = results.filter((r) => r.ok).length;
    const bad = results.filter((r) => !r.ok);
    console.log('\n' + '═'.repeat(46));
    console.log(`Ergebnis: ${ok}/${results.length} bestanden`);
    if (bad.length) bad.forEach((r) => console.log('  ✗ ' + r.name + ' – ' + r.detail));
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
