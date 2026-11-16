/* Waechter: Fachprobe im Container "Mein …-Zugang" (2026-11-16).
 *
 * VORGABE: in /jira, /confluence, /SAP und /vemas steht unterhalb des
 * Speichern-Knopfes ein zum Bereich passender Test – sichtbare Tickets,
 * Bereiche, Objekte, Daten.
 *
 * WAS HIER GEMESSEN WIRD, UND WARUM NICHT DER QUELLTEXT:
 *   1. MARKUP je Seite: Knopf und Ausgabekasten liegen IM Zugangs-Container,
 *      der Knopf steht in der DOM-Reihenfolge NACH dem Speichern-Knopf
 *      (die Vorgabe ist eine Position, keine Schreibweise), der Kasten ist im
 *      Grundzustand verborgen, jeder Knopf traegt `data-i18n`.
 *   2. WIRKUNG: der Klick wird AUSGEFUEHRT, und gemessen wird, WELCHER
 *      Endpunkt gefragt wurde und was im Kasten steht. Eine Suche nach
 *      `/api/...` im Quelltext bliebe gruen, wenn der Zweig nie laeuft.
 *   3. NULL TREFFER IST EIN EIGENES ERGEBNIS: der Zugang gilt und sieht
 *      nichts – dann muss ein GRUND dastehen und der Kasten LEER bleiben.
 *      Eine stumme Null ist von einem Fehlschlag nicht zu unterscheiden.
 *   4. SAP liest den Status, NICHT das Pulldown: ohne eigenen Zugang steht
 *      dort "kein eigener Zugang", waehrend der gemeinsame Zugang laeuft –
 *      wer das Pulldown liest, misst den falschen Zugang. Und RFC hat keine
 *      Katalog-Abfrage: dort ist der Knopf GESPERRT MIT GRUND (Projektregel),
 *      und es darf kein Aufruf hinausgehen.
 *   5. i18n als REGEL ueber die im CODE benutzten `*.probe_*`-Schluessel:
 *      jeder muss in DE **und** EN stehen.
 *
 * Die Modulpfade kommen aus Umgebungsvariablen (PROBE_*_JS) – die Gegenprobe
 * legt dort sabotierte Kopien hin, ohne den Arbeitsbaum anzufassen.
 *
 * Aufruf: node tests/test_zugang_probe_ui.js
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const JS = {
    jira: process.env.PROBE_JIRA_JS || path.join(ROOT, 'frontend/js/jira_addon.js'),
    conf: process.env.PROBE_CONF_JS || path.join(ROOT, 'frontend/js/confluence_addon.js'),
    sap: process.env.PROBE_SAP_JS || path.join(ROOT, 'frontend/js/sap_portal.js'),
    vemas: process.env.PROBE_VEMAS_JS || path.join(ROOT, 'frontend/js/vemas_portal.js'),
};
const HTML = {
    jira: process.env.PROBE_JIRA_HTML || path.join(ROOT, 'frontend/jira_addon.html'),
    conf: process.env.PROBE_CONF_HTML || path.join(ROOT, 'frontend/confluence_addon.html'),
    sap: process.env.PROBE_SAP_HTML || path.join(ROOT, 'frontend/sap.html'),
    vemas: process.env.PROBE_VEMAS_HTML || path.join(ROOT, 'frontend/vemas.html'),
};
const I18N_PFAD = process.env.PROBE_I18N || path.join(ROOT, 'frontend/js/i18n.js');
const JA_CSS_PFAD = process.env.PROBE_JA_CSS || path.join(ROOT, 'frontend/css/jira_addon.css');
const I18N_SRC = fs.readFileSync(I18N_PFAD, 'utf8');

let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
function section(t) { console.log('\n' + '═══ ' + t); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Die Bereiche, als DATEN – so gilt jede Pruefung fuer alle vier, und ein
 * fuenfter Bereich waere eine Zeile. `perm` ist die Freigabe, ohne die das
 * Modul auf das Portal umleitet (fail-closed im Produktivcode). */
const BEREICHE = [
    { id: 'jira', seite: 'jira_addon.html', sekt: 'ja-sect-account', perm: 'jira_assist',
      save: 'ja-acc-save', btn: 'ja-acc-probe', note: 'ja-acc-probe-note', out: 'ja-acc-probe-out',
      pfad: '/api/jira/search' },
    { id: 'conf', seite: 'confluence_addon.html', sekt: 'ca-sect-account', perm: 'confluence',
      save: 'ca-acc-save', btn: 'ca-acc-probe', note: 'ca-acc-probe-note', out: 'ca-acc-probe-out',
      pfad: '/api/confluence/spaces' },
    { id: 'sap', seite: 'sap.html', sekt: 'sp-sect-account', perm: 'sap',
      save: 'sp-acc-save', btn: 'sp-acc-probe', note: 'sp-acc-probe-note', out: 'sp-acc-probe-out',
      pfad: '/api/sap/odata/services' },
    { id: 'vemas', seite: 'vemas.html', sekt: 'vm-sect-account', perm: 'vemas',
      save: 'vm-acc-save', btn: 'vm-acc-probe', note: 'vm-acc-probe-note', out: 'vm-acc-probe-out',
      pfad: '/api/vemas/query' },
];

/* ── Antworten, die JEDE der vier Seiten beim Start braucht ────────────────
 * Ohne sie laeuft das Modul in seine `catch`-Zweige und die Verdrahtung
 * unterbleibt – dann waere jede Folgepruefung trivial. */
function grundAntworten(perm, extra) {
    const p = {};
    p[perm] = true;
    const basis = {
        '/api/me': { ok: true, username: 'probe', permissions: p },
        '/api/jira/assist/health': { ok: true },
        '/api/jira/account': { ok: true, account: { vorhanden: true, aktiv: true } },
        '/api/confluence/account': { ok: true, account: { vorhanden: true, aktiv: true } },
        '/api/sap/account': { ok: true, account: {} },
        '/api/vemas/account': { ok: true, account: {} },
        '/api/sap/status': { ok: true, configured: true, odata: true, hana: false, rfc: false,
                             quelle: 'persoenlich', connection_type: 'odata' },
        '/api/vemas/status': { ok: true, configured: true, quelle: 'persoenlich' },
        '/api/sap/analyses/catalog': { ok: true, analyses: [] },
        '/api/vemas/analyses/catalog': { ok: true, analyses: [] },
        '/api/sap/reporting-endpoints': { ok: true },
        '/api/vemas/reporting-endpoints': { ok: true },
        '/api/sap/instructions': { ok: true, text: '' },
        '/api/vemas/instructions': { ok: true, text: '' },
        '/api/llm/active-status': { status: 'ok' },
    };
    return Object.assign(basis, extra || {});
}

/** Seite laden und das Modul ausfuehren. `tabelle` ordnet Pfad -> Antwort zu
 *  (Wert `{__status: n, ...}` setzt den HTTP-Status). */
function seite(b, tabelle) {
    const html = fs.readFileSync(HTML[b.id], 'utf8');
    const rufe = [];
    const dom = new JSDOM(html, {
        url: 'https://localhost/', runScripts: 'outside-only',
        virtualConsole: new VirtualConsole(),
        beforeParse(win) {
            // Ueber den PFAD routen, nie ueber die volle URL: ein spaeter
            // ergaenztes `?limit=` verfehlte sonst jede Route (Register).
            win.fetch = (url, init) => {
                const voll = String(url);
                const u = voll.split('?')[0];
                rufe.push({ u, voll, m: (init && init.method) || 'GET' });
                const a = tabelle[u];
                if (a === undefined) {
                    return Promise.resolve({ ok: true, status: 200,
                        json: () => Promise.resolve({ ok: true }) });
                }
                if (a instanceof Error) return Promise.reject(a);
                const st = a.__status || 200;
                return Promise.resolve({ ok: st < 400, status: st,
                    json: () => Promise.resolve(a) });
            };
            win.confirm = () => true;
        },
    });
    // MIT Token: alle vier Module leiten ohne Sitzung auf "/" um (fail-closed),
    // und danach ist jede Messung darunter trivial wahr (Register: eine Seite,
    // die sich selbst umleitet, macht jede Pruefung bedeutungslos).
    require('./lib/sitzung_laden')(dom.window, { token: 'probetoken' });
    dom.window.eval(I18N_SRC);
    dom.window.eval(fs.readFileSync(JS[b.id], 'utf8'));
    return { dom, rufe, win: dom.window,
             $: (id) => dom.window.document.getElementById(id) };
}

/** Der sichtbare Text des Ausgabekastens – Attribute zaehlen ausdruecklich
 *  nicht: gefragt ist, was ein Mensch LIEST. */
function kastenText(s, b) {
    const el = s.$(b.out);
    return (el && !el.hidden) ? (el.textContent || '').trim() : '';
}

(async () => {
    // ══════════════════════════════════════════════════════════════════════
    section('1) Markup: Knopf und Kasten im Zugangs-Container, UNTER dem Speichern-Knopf');
    for (const b of BEREICHE) {
        const html = fs.readFileSync(HTML[b.id], 'utf8');
        const dom = new JSDOM(html, { virtualConsole: new VirtualConsole() });
        const doc = dom.window.document;
        const btn = doc.getElementById(b.btn);
        const out = doc.getElementById(b.out);
        const note = doc.getElementById(b.note);
        const save = doc.getElementById(b.save);
        const sekt = doc.getElementById(b.sekt);
        check(!!btn, b.id + ': Probe-Knopf #' + b.btn + ' vorhanden');
        check(!!out, b.id + ': Ausgabekasten #' + b.out + ' vorhanden');
        check(!!note, b.id + ': Meldezeile #' + b.note + ' vorhanden');
        check(!!out && out.hasAttribute('hidden'),
              b.id + ': Kasten im Grundzustand verborgen');
        check(!!btn && !!sekt && sekt.contains(btn),
              b.id + ': Knopf liegt IM Container "Mein …-Zugang"');
        check(!!out && !!sekt && sekt.contains(out),
              b.id + ': Kasten liegt IM Container');
        // DOCUMENT_POSITION_FOLLOWING = 4: der Knopf kommt im Dokument SPAETER.
        const danach = !!(btn && save
            && (save.compareDocumentPosition(btn) & 4));
        check(danach, b.id + ': Knopf steht NACH dem Speichern-Knopf');
        check(!!btn && btn.getAttribute('type') === 'button',
              b.id + ': type="button" (sonst sendet er in /sap und /vemas das Formular ab)');
        check(!!btn && !!btn.getAttribute('data-i18n'),
              b.id + ': Knopf traegt data-i18n');
        // Ein `data-i18n-title` wuerde den zugangsabhaengigen Sperrgrund bei
        // jedem Sprachwechsel ueberschreiben (Register, sieben Platzhalter).
        check(!!btn && !btn.hasAttribute('data-i18n-title'),
              b.id + ': kein data-i18n-title am Knopf');
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('2) Wirkung: der Klick fragt den FACHLICHEN Endpunkt und zeigt Treffer');
    {
        const faelle = [
            { b: BEREICHE[0], ant: { '/api/jira/search': { ok: true, total: 42, results: [
                { key: 'PRJA-1', summary: 'Erster Vorgang' },
                { key: 'PRJA-2', summary: 'Zweiter Vorgang' }] } },
              muss: ['PRJA-1', 'Erster Vorgang'], zahl: '42' },
            { b: BEREICHE[1], ant: { '/api/confluence/spaces': { ok: true, count: 7, spaces: [
                { key: 'SONDEA', name: 'Sondenbereich A' }, { key: 'SONDEB', name: 'Sondenbereich B' }] } },
              muss: ['SONDEA', 'Sondenbereich A'], zahl: '7' },
            { b: BEREICHE[2], ant: { '/api/sap/odata/services': { ok: true, count: 3,
                services: ['sap/API_SALES_ORDER_SRV', 'sap/API_BUSINESS_PARTNER'] } },
              muss: ['API_SALES_ORDER_SRV'], zahl: '3' },
            { b: BEREICHE[3], ant: {
                '/api/vemas/resources': { ok: true, resources: [{ name: 'Projekte', pfad: 'projects' }] },
                '/api/vemas/query': { ok: true, columns: ['Nummer', 'Bezeichnung'],
                                      rows: [{ Nummer: 1 }, { Nummer: 2 }] } },
              muss: ['Projekte', 'Nummer'], zahl: '2' },
        ];
        for (const f of faelle) {
            const b = f.b;
            const s = seite(b, grundAntworten(b.perm, f.ant));
            await sleep(60);
            const vorher = s.rufe.length;
            check(!!s.$(b.btn) && s.$(b.btn).disabled === false,
                  b.id + ': Knopf vor dem Klick bedienbar');
            s.$(b.btn).dispatchEvent(new s.win.Event('click'));
            await sleep(80);
            const neu = s.rufe.slice(vorher);
            check(neu.some((r) => r.u === b.pfad),
                  b.id + ': ruft ' + b.pfad,
                  neu.map((r) => r.u).join(', ') || 'kein Aufruf');
            const txt = kastenText(s, b);
            check(txt.length > 0, b.id + ': Kasten ist SICHTBAR und gefuellt');
            for (const m of f.muss) {
                check(txt.indexOf(m) >= 0, b.id + ': Kasten nennt "' + m + '"', txt.slice(0, 120));
            }
            const note = (s.$(b.note).textContent || '');
            check(note.indexOf(f.zahl) >= 0,
                  b.id + ': Meldezeile nennt die Gesamtzahl ' + f.zahl, note);
            check(/is-ok/.test(s.$(b.note).className),
                  b.id + ': Meldezeile als Erfolg gekennzeichnet', s.$(b.note).className);
            check(s.$(b.btn).disabled === false, b.id + ': Knopf danach wieder frei');
            s.win.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('3) Null Treffer: GRUND in der Meldezeile, Kasten bleibt LEER');
    {
        const faelle = [
            { b: BEREICHE[0], ant: { '/api/jira/search': { ok: true, total: 0, results: [] } } },
            { b: BEREICHE[1], ant: { '/api/confluence/spaces': { ok: true, count: 0, spaces: [] } } },
            { b: BEREICHE[2], ant: { '/api/sap/odata/services': { ok: true, count: 0, services: [] } } },
            { b: BEREICHE[3], ant: {
                '/api/vemas/resources': { ok: true, resources: [{ name: 'Projekte', pfad: 'projects' }] },
                '/api/vemas/query': { ok: true, columns: [], rows: [] } } },
        ];
        for (const f of faelle) {
            const b = f.b;
            const s = seite(b, grundAntworten(b.perm, f.ant));
            await sleep(60);
            s.$(b.btn).dispatchEvent(new s.win.Event('click'));
            await sleep(80);
            const note = (s.$(b.note).textContent || '').trim();
            check(note.length > 20, b.id + ': Leerfall nennt einen GRUND', note);
            check(/pr(ü|ue)f/i.test(note), b.id + ': … und den naechsten Schritt', note);
            check(kastenText(s, b) === '', b.id + ': Kasten bleibt leer/verborgen');
            s.win.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('4) Fehlschlag: die Meldung traegt den Grund des SERVERS');
    {
        const faelle = [
            { b: BEREICHE[0], ant: { '/api/jira/search': { __status: 400, ok: false, error: 'JQL kaputt' } }, grund: 'JQL kaputt' },
            { b: BEREICHE[1], ant: { '/api/confluence/spaces': { ok: false, error: 'Token abgelaufen' } }, grund: 'Token abgelaufen' },
            { b: BEREICHE[2], ant: { '/api/sap/odata/services': { ok: false, error: 'Logon abgelehnt' } }, grund: 'Logon abgelehnt' },
            { b: BEREICHE[3], ant: {
                '/api/vemas/resources': { ok: true, resources: [{ name: 'Projekte', pfad: 'projects' }] },
                '/api/vemas/query': { __status: 400, ok: false, error: 'Ressource unbekannt' } }, grund: 'Ressource unbekannt' },
        ];
        for (const f of faelle) {
            const b = f.b;
            const s = seite(b, grundAntworten(b.perm, f.ant));
            await sleep(60);
            s.$(b.btn).dispatchEvent(new s.win.Event('click'));
            await sleep(80);
            const note = (s.$(b.note).textContent || '');
            check(note.indexOf(f.grund) >= 0, b.id + ': Meldung nennt "' + f.grund + '"', note);
            check(/is-error/.test(s.$(b.note).className),
                  b.id + ': als Fehler gekennzeichnet', s.$(b.note).className);
            check(kastenText(s, b) === '', b.id + ': kein Kasten bei einem Fehlschlag');
            check(s.$(b.btn).disabled === false, b.id + ': Knopf danach wieder frei');
            s.win.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('5) Doppelklick loest EINEN Lauf aus (jeder Lauf kostet eine echte Abfrage)');
    for (const b of BEREICHE) {
        const ant = {
            '/api/jira/search': { ok: true, total: 1, results: [{ key: 'PRJA-9', summary: 'x' }] },
            '/api/confluence/spaces': { ok: true, count: 1, spaces: [{ key: 'K', name: 'n' }] },
            '/api/sap/odata/services': { ok: true, count: 1, services: ['sap/X'] },
            '/api/vemas/resources': { ok: true, resources: [{ name: 'Projekte', pfad: 'projects' }] },
            '/api/vemas/query': { ok: true, columns: ['A'], rows: [{ A: 1 }] },
        };
        const s = seite(b, grundAntworten(b.perm, ant));
        await sleep(60);
        const vorher = s.rufe.length;
        s.$(b.btn).dispatchEvent(new s.win.Event('click'));
        s.$(b.btn).dispatchEvent(new s.win.Event('click'));
        await sleep(90);
        const n = s.rufe.slice(vorher).filter((r) => r.u === b.pfad).length;
        check(n === 1, b.id + ': genau ein Aufruf von ' + b.pfad, 'gezaehlt: ' + n);
        s.win.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('6) SAP: der STATUS entscheidet, nicht das Pulldown');
    {
        const b = BEREICHE[2];
        // 6a) HANA-Zugang, Pulldown absichtlich auf "kein eigener Zugang":
        //     gefragt werden muss die Tabellenliste, nicht der OData-Katalog.
        {
            const s = seite(b, grundAntworten(b.perm, {
                '/api/sap/status': { ok: true, configured: true, odata: false, hana: true,
                                     rfc: false, quelle: 'sammel', connection_type: 'hana' },
                '/api/sap/tables': { ok: true, count: 2, rows: [
                    { SCHEMA_NAME: 'SAPHANADB', OBJECT_NAME: 'T000', OBJECT_TYPE: 'TABLE' },
                    { SCHEMA_NAME: 'SAPHANADB', OBJECT_NAME: 'V_USR', OBJECT_TYPE: 'VIEW' }] },
            }));
            await sleep(60);
            const sel = s.$('sp-acc-type');
            check(!!sel, 'Pulldown sp-acc-type vorhanden (Positivkontrolle des Aufbaus)');
            if (sel) sel.value = '';
            const vorher = s.rufe.length;
            s.$(b.btn).dispatchEvent(new s.win.Event('click'));
            await sleep(80);
            const neu = s.rufe.slice(vorher).map((r) => r.u);
            check(neu.indexOf('/api/sap/tables') >= 0,
                  'HANA-Status: fragt /api/sap/tables', neu.join(', ') || 'kein Aufruf');
            check(neu.indexOf('/api/sap/odata/services') < 0,
                  '… und NICHT den OData-Katalog');
            const txt = kastenText(s, b);
            check(txt.indexOf('T000') >= 0 && txt.indexOf('VIEW') >= 0,
                  '… Kasten nennt Objektname und Art', txt.slice(0, 120));
            s.win.close();
        }
        // 6b) RFC: kein Listen-Endpunkt -> gesperrt MIT GRUND, kein Aufruf.
        {
            const s = seite(b, grundAntworten(b.perm, {
                '/api/sap/status': { ok: true, configured: true, odata: false, hana: false,
                                     rfc: true, quelle: 'persoenlich', connection_type: 'rfc' },
            }));
            await sleep(60);
            const btn = s.$(b.btn);
            check(btn.disabled === true, 'RFC: Knopf gesperrt');
            check((btn.title || '').length > 20, 'RFC: … MIT Grund im title', btn.title);
            check(/RFC/.test(btn.title || ''), 'RFC: … der Grund nennt RFC', btn.title);
            const vorher = s.rufe.length;
            btn.disabled = false;   // auch ein erzwungener Klick darf nichts senden
            btn.dispatchEvent(new s.win.Event('click'));
            await sleep(60);
            const neu = s.rufe.slice(vorher).filter((r) => /\/api\/sap\/(tables|odata)/.test(r.u));
            check(neu.length === 0, 'RFC: kein Aufruf, auch bei erzwungenem Klick',
                  neu.map((r) => r.u).join(', '));
            check(s.$(b.btn).disabled === true, 'RFC: Sperre wird wieder hergestellt');
            s.win.close();
        }
        // 6c) gar kein Zugang -> ebenfalls gesperrt mit Grund (fail-closed).
        {
            const s = seite(b, grundAntworten(b.perm, {
                '/api/sap/status': { ok: true, configured: false, odata: false, hana: false,
                                     rfc: false, quelle: 'sammel' },
            }));
            await sleep(60);
            const btn = s.$(b.btn);
            check(btn.disabled === true, 'ohne Zugang: Knopf gesperrt');
            check((btn.title || '').length > 20, 'ohne Zugang: … MIT Grund', btn.title);
            s.win.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('7) VEMAS: keine Ressource hinterlegt ist ein KONFIGURATIONS-Befund');
    {
        const b = BEREICHE[3];
        const s = seite(b, grundAntworten(b.perm, {
            '/api/vemas/resources': { ok: true, resources: [] },
        }));
        await sleep(60);
        const vorher = s.rufe.length;
        s.$(b.btn).dispatchEvent(new s.win.Event('click'));
        await sleep(80);
        const neu = s.rufe.slice(vorher).map((r) => r.u);
        check(neu.indexOf('/api/vemas/query') < 0,
              'keine Ressource: es wird gar nicht abgefragt', neu.join(', '));
        const note = (s.$(b.note).textContent || '');
        check(/Administrator/.test(note), '… die Meldung nennt den Administrator', note);
        check(/Zugang/.test(note), '… und stellt klar, dass es nicht am Zugang liegt', note);
        check(kastenText(s, b) === '', '… Kasten bleibt leer');
        s.win.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('8) Die Abfrage ist billig: ein Deckel steht in der Anfrage');
    {
        // Eine Probe, die den ganzen Bestand holt, ist Last und keine Messung.
        const b0 = BEREICHE[0];
        const s0 = seite(b0, grundAntworten(b0.perm, {
            '/api/jira/search': { ok: true, total: 1, results: [{ key: 'PRJA-1', summary: 'x' }] } }));
        await sleep(60);
        s0.$(b0.btn).dispatchEvent(new s0.win.Event('click'));
        await sleep(80);
        const r0 = s0.rufe.filter((r) => r.u === '/api/jira/search').pop();
        check(!!r0 && /limit=\d+/.test(r0.voll), 'jira: limit= in der Anfrage',
              r0 && r0.voll);
        s0.win.close();

        const b3 = BEREICHE[3];
        const s3 = seite(b3, grundAntworten(b3.perm, {
            '/api/vemas/resources': { ok: true, resources: [{ name: 'Projekte', pfad: 'projects' }] },
            '/api/vemas/query': { ok: true, columns: ['A'], rows: [{ A: 1 }] } }));
        await sleep(60);
        s3.$(b3.btn).dispatchEvent(new s3.win.Event('click'));
        await sleep(80);
        const r3 = s3.rufe.filter((r) => r.u === '/api/vemas/query').pop();
        check(!!r3 && /top=\d+/.test(r3.voll), 'vemas: top= in der Anfrage', r3 && r3.voll);
        check(!!r3 && /resource=Projekte/.test(r3.voll),
              'vemas: fragt die erste hinterlegte Ressource', r3 && r3.voll);
        s3.win.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('9) Fremdtext wird maskiert (Titel und Namen kommen aus Fremdsystemen)');
    {
        const b = BEREICHE[0];
        const s = seite(b, grundAntworten(b.perm, {
            '/api/jira/search': { ok: true, total: 1, results: [
                { key: 'PRJA-1', summary: '<img src=x onerror=alert(1)>' }] } }));
        await sleep(60);
        s.$(b.btn).dispatchEvent(new s.win.Event('click'));
        await sleep(80);
        const el = s.$(b.out);
        check(el.querySelectorAll('img').length === 0,
              'kein eingeschleustes Element im Kasten');
        check((el.textContent || '').indexOf('onerror') >= 0,
              '… der Text steht als Text da (Positivkontrolle)', (el.textContent || '').slice(0, 80));
        s.win.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('10) i18n als REGEL: jeder benutzte probe_-Schluessel in DE und EN');
    {
        const quellen = Object.values(JS).map((p) => fs.readFileSync(p, 'utf8')).join('\n');
        // Nur T()-Aufrufe zaehlen – ein Vorkommen im Kommentar ist keine Benutzung.
        const benutzt = new Set();
        const re = /T\(\s*'([a-z]+\.probe_[a-z0-9_]+)'/g;
        let m;
        while ((m = re.exec(quellen)) !== null) benutzt.add(m[1]);
        check(benutzt.size >= 20, 'Positivkontrolle: Schluessel gefunden',
              'gezaehlt: ' + benutzt.size);
        const i_de = I18N_SRC.indexOf('\n    de: {');
        const i_en = I18N_SRC.indexOf('\n    en: {');
        check(i_de >= 0 && i_en > i_de, 'Positivkontrolle: beide Sprachbloecke gefunden');
        const de = I18N_SRC.slice(i_de, i_en);
        const en = I18N_SRC.slice(i_en);
        let fehlDe = [], fehlEn = [];
        benutzt.forEach((k) => {
            if (de.indexOf("'" + k + "'") < 0) fehlDe.push(k);
            if (en.indexOf("'" + k + "'") < 0) fehlEn.push(k);
        });
        check(fehlDe.length === 0, 'alle Schluessel in DE', fehlDe.join(', '));
        check(fehlEn.length === 0, 'alle Schluessel in EN', fehlEn.join(', '));
        // Auch die Knopf-Schluessel aus dem MARKUP muessen uebersetzt sein.
        for (const b of BEREICHE) {
            const html = fs.readFileSync(HTML[b.id], 'utf8');
            const dom = new JSDOM(html, { virtualConsole: new VirtualConsole() });
            const el = dom.window.document.getElementById(b.btn);
            const k = el && el.getAttribute('data-i18n');
            check(!!k && de.indexOf("'" + k + "'") >= 0 && en.indexOf("'" + k + "'") >= 0,
                  b.id + ': Knopf-Schluessel ' + k + ' in DE und EN');
            dom.window.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('11) CSS: jede benutzte Probe-Klasse ist in dem CSS definiert, das die Seite laedt');
    {
        const JA_CSS = fs.readFileSync(JA_CSS_PFAD, 'utf8');
        const SAP_HTML = fs.readFileSync(HTML.sap, 'utf8');
        const VM_HTML = fs.readFileSync(HTML.vemas, 'utf8');
        const paare = [
            ['ja-probe-zeile', JA_CSS], ['ja-probe-note', JA_CSS], ['ja-probe', JA_CSS],
            ['ja-probe-kopf', JA_CSS], ['ja-probe-rest', JA_CSS], ['ja-probe-key', JA_CSS],
            ['sp-probe-zeile', SAP_HTML], ['sp-probe-note', SAP_HTML], ['sp-probe', SAP_HTML],
            ['sp-probe-kopf', SAP_HTML], ['sp-probe-rest', SAP_HTML],
            ['vm-probe-zeile', VM_HTML], ['vm-probe-note', VM_HTML], ['vm-probe', VM_HTML],
            ['vm-probe-kopf', VM_HTML], ['vm-probe-rest', VM_HTML],
        ];
        for (const [kl, src] of paare) {
            check(src.indexOf('.' + kl + ' ') >= 0 || src.indexOf('.' + kl + '{') >= 0
                  || src.indexOf('.' + kl + ' {') >= 0 || src.indexOf('.' + kl + '[') >= 0
                  || src.indexOf('.' + kl + '.') >= 0,
                  'CSS definiert .' + kl);
        }
        // Der Kasten darf KEIN eigenes `display` tragen, sonst ueberstimmt die
        // Klasse das `hidden`-Attribut (Klassen-Falle von .sp-row/.vm-row).
        for (const [kl, src] of [['sp-probe', SAP_HTML], ['vm-probe', VM_HTML]]) {
            const i = src.indexOf('.' + kl + ' {');
            const block = i >= 0 ? src.slice(i, src.indexOf('}', i)) : '';
            check(i >= 0 && !/display\s*:/.test(block),
                  '.' + kl + ' setzt kein display (hidden bleibt wirksam)', block.slice(0, 80));
        }
        check(/\.ja-probe\[hidden\]/.test(JA_CSS),
              '.ja-probe[hidden] ist ausdruecklich auf display:none gesetzt');
    }

    // ══════════════════════════════════════════════════════════════════════
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
