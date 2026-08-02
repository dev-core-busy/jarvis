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
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst haelt der 30-Sekunden-Timer der LLM-Anzeige den Prozess fuer immer offen.
 *
 * Lauf:  timeout 90 node tests/test_sap_portal_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
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
            win.localStorage.setItem('jarvis_token', 'testtoken');
            // Der Verlauf liegt im localStorage – zwischen den Abschnitten
            // leeren, sonst schleppt ein Test die Eintraege des vorigen mit.
            if (opts.clearHistory !== false) win.localStorage.removeItem('jarvis_sap_history');
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
                    return json({ ok: true, configured: true, connection_type: 'odata',
                                  product: 'S/4HANA', odata: true, hana: false, rfc: false });
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
                if (u.startsWith('/api/sap/stop')) return json({ ok: true });
                if (u.startsWith('/api/llm/active-status')) return json({ status: 'ok', profile_name: 'Test' });
                if (u.startsWith('/api/support/status')) return json({ active: false });
                if (u.startsWith('/api/wissen/scope')) return json({ ok: true, groups: [] });
                if (u.startsWith('/api/userchat/unread')) return json({ unread: 0 });
                if (u.startsWith('/api/info_files')) return json({ ok: true, files: [] });
                return json({ ok: true });
            };
        },
    });
    dom.__navs = navs;
    return dom;
}

function loadScript(dom, rel) {
    const code = fs.readFileSync(path.join(ROOT, 'frontend', rel), 'utf8');
    dom.window.eval(code);
}

(async () => {
    // ══ 1. Berechtigung ══════════════════════════════════════════════
    section('1. Berechtigung');
    {
        const dom = build('sap.html', { username: 'bob', is_admin: false,
                                        permissions: { sap: false } });
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
    loadScript(dom, 'js/i18n.js');
    loadScript(dom, 'js/chatlib.js');
    loadScript(dom, 'js/sap_portal.js');
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

    // ── Ergebnis ────────────────────────────────────────────────────
    const ok = results.filter((r) => r.ok).length;
    const bad = results.filter((r) => !r.ok);
    console.log('\n' + '═'.repeat(46));
    console.log(`Ergebnis: ${ok}/${results.length} bestanden`);
    if (bad.length) bad.forEach((r) => console.log('  ✗ ' + r.name + ' – ' + r.detail));
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
