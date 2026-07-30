/* UI-Test des Audit-Formulars auf /wissen (jsdom, echte Dateien).
 *
 * Prueft den Befund D-5 aus dem Code-Review: Zusammenfassung und Kernfakten
 * muessen im Audit BEARBEITBAR sein und beim Uebernehmen auch WIRKLICH gesendet
 * werden. Der Quelltext-Grep im Python-Test beweist nur, dass die Felder im
 * Markup stehen – nicht, dass sie vorbelegt werden und im PATCH landen.
 *
 * Lauf:  node tests/test_wissen_audit_ui.js
 * (jsdom wird unter /tmp/node_modules erwartet: cd /tmp && npm install jsdom)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Der Entwurf, den der Prüfer vor sich hat ────────────────────────────────
const ENTWURF = {
    id: 'a3f9c1d2',
    title: 'Server-Setup v3',
    summary: 'Der Dienst hoert standardmaessig auf Port 8080.',
    facts: ['Der Dienst laeuft auf Port 8080.', 'Die Konfiguration liegt in /etc/dienst.conf.'],
    qa_pairs: [
        { id: 'q1', q: 'Auf welchem Port laeuft der Dienst?', a: 'Auf Port 8080.', approved: true },
        { id: 'q2', q: 'Was kostet das Modul?', a: 'Unbekannt.', approved: true },
    ],
    status: 'pending',
    created_at: 1753876543,
};

const SCOPE = {
    ok: true, user: 'anna', is_editor: true, is_admin: false,
    groups: [{ id: 'ibs', name: 'IBS', color: '#3b82f6', folders: ['data/ibs'] }],
    folders: [{ path: 'data/ibs', name: 'ibs', root: 'data/ibs', depth: 0 }],
};

async function baueSeite() {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'wissen.html'), 'utf8');
    const dom = new JSDOM(html, {
        url: 'https://localhost/wissen',
        runScripts: 'outside-only',       // NUR die Skripte, die wir bewusst laden
        // pretendToBeVisual startet einen requestAnimationFrame-Dauerlauf, der
        // den Node-Event-Loop offen haelt. Wir setzen rAF unten selbst.
    });
    const { window } = dom;

    // Token VOR dem Auswerten von wissen.js setzen: die Datei liest es auf
    // Modulebene (`var token = localStorage.getItem(...)`).
    window.localStorage.setItem('jarvis_token', 'anna:1:deadbeef');

    // Aufgezeichnete Anfragen – daran wird spaeter geprueft, was gesendet wurde.
    const calls = [];
    window.fetch = function (url, opts) {
        opts = opts || {};
        calls.push({ url: String(url), method: (opts.method || 'GET').toUpperCase(), body: opts.body });
        const antwort = (data, ok) => Promise.resolve({
            ok: ok !== false, status: ok === false ? 500 : 200,
            json: () => Promise.resolve(data),
            text: () => Promise.resolve(JSON.stringify(data)),
        });
        const u = String(url);
        if (u.indexOf('/api/wissen/scope') === 0) return antwort(SCOPE);
        if (u.indexOf('/api/wissen/pending') === 0 && (opts.method || 'GET') === 'GET')
            return antwort({ ok: true, pending: [ENTWURF] });
        if (u.indexOf('/api/wissen/pending/') === 0 && opts.method === 'PATCH')
            return antwort({ ok: true });
        if (u.indexOf('/api/wissen/pending/') === 0 && opts.method === 'POST')
            return antwort({ ok: true, file: 'data/ibs/extract_a3f9c1d2_Server-Setup_v3.md', qa_count: 1, fact_count: 2 });
        if (u.indexOf('/api/wissen/files') === 0) return antwort({ ok: true, files: [] });
        return antwort({ ok: true });
    };
    window.requestAnimationFrame = (cb) => setTimeout(cb, 0);

    for (const datei of ['frontend/js/i18n.js', 'frontend/js/wissen.js']) {
        window.eval(fs.readFileSync(path.join(ROOT, datei), 'utf8'));
    }
    window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
    await sleep(60);
    return { dom, window, calls };
}

async function main() {
    console.log('='.repeat(70));
    console.log('UI-Test Audit-Formular /wissen (jsdom, echte Dateien)');
    console.log('='.repeat(70));

    const { dom, window, calls } = await baueSeite();
    globalThis.__dom = dom;   // fuer das Aufraeumen am Ende
    const doc = window.document;
    const $ = (id) => doc.getElementById(id);

    section('Entwurfsliste');
    const zeilen = doc.querySelectorAll('#wi-pending-list .wi-item');
    check('Entwurf wird gelistet', zeilen.length === 1, 'gefunden: ' + zeilen.length);

    section('Vorschau oeffnen');
    const pruefen = zeilen[0] && Array.from(zeilen[0].querySelectorAll('button'))
        .find((b) => b.className.indexOf('danger') === -1);
    check('„Pruefen"-Knopf vorhanden', !!pruefen);
    pruefen.click();
    await sleep(20);

    const titel = $('wi-rev-title');
    const summary = $('wi-rev-summary');
    const facts = $('wi-rev-facts');

    check('Titelfeld vorhanden', !!titel);
    check('Zusammenfassung ist ein EINGABEFELD', !!summary && summary.tagName === 'TEXTAREA',
          summary ? summary.tagName : 'fehlt');
    check('Kernfakten sind ein EINGABEFELD', !!facts && facts.tagName === 'TEXTAREA',
          facts ? facts.tagName : 'fehlt');
    check('Zusammenfassung vorbelegt', summary && summary.value === ENTWURF.summary,
          summary ? JSON.stringify(summary.value) : 'fehlt');
    check('Kernfakten zeilenweise vorbelegt',
          facts && facts.value === ENTWURF.facts.join('\n'),
          facts ? JSON.stringify(facts.value) : 'fehlt');
    check('Q&A-Zeilen vorhanden', doc.querySelectorAll('#wi-rev-qa .wi-qa-row').length === 2,
          String(doc.querySelectorAll('#wi-rev-qa .wi-qa-row').length));

    section('Pruefer korrigiert und uebernimmt');
    // Genau der Fall aus Kapitel 6 der Dokumentation: der Prüfer bemerkt, dass
    // Port 8080 veraltet ist, und korrigiert ihn. Vor dem Fix war das unmöglich.
    summary.value = 'Der Dienst hoert seit Version 3.1 auf Port 8443 (TLS).';
    facts.value = '- Der Dienst laeuft auf Port 8443.\n\n  * Port 8080 ist abgekuendigt.\n   \n';
    // Ein Q&A-Paar abwaehlen
    const kb = doc.querySelectorAll('#wi-rev-qa .wi-qa-keep');
    kb[1].checked = false;
    // Zielgruppe waehlen (Pflicht)
    const grp = doc.querySelector('#wi-rev-groups input[type=checkbox]');
    check('Zielgruppe waehlbar', !!grp);
    grp.checked = true;

    const vorher = calls.length;
    $('wi-rev-approve').click();
    await sleep(60);

    const patch = calls.slice(vorher).find((c) => c.method === 'PATCH');
    const approve = calls.slice(vorher).find((c) => c.method === 'POST' && c.url.indexOf('/approve') !== -1);
    check('PATCH wurde gesendet', !!patch, JSON.stringify(calls.slice(vorher)));
    check('Freigabe wurde gesendet', !!approve);

    let body = {};
    try { body = JSON.parse(patch.body); } catch (e) { /* unten sichtbar */ }

    check('korrigierte Zusammenfassung im PATCH',
          body.summary === 'Der Dienst hoert seit Version 3.1 auf Port 8443 (TLS).',
          JSON.stringify(body.summary));
    check('Kernfakten als Liste im PATCH', Array.isArray(body.facts) && body.facts.length === 2,
          JSON.stringify(body.facts));
    check('Aufzaehlungszeichen entfernt',
          body.facts && body.facts[0] === 'Der Dienst laeuft auf Port 8443.'
          && body.facts[1] === 'Port 8080 ist abgekuendigt.',
          JSON.stringify(body.facts));
    check('Leerzeilen verworfen', body.facts && body.facts.every((f) => f.trim().length > 0),
          JSON.stringify(body.facts));
    check('abgewaehltes Q&A-Paar als nicht freigegeben markiert',
          body.qa_pairs && body.qa_pairs.length === 2
          && body.qa_pairs[0].approved === true && body.qa_pairs[1].approved === false,
          JSON.stringify(body.qa_pairs));
    check('Gruppen gehen an den Freigabe-Endpunkt',
          approve && JSON.parse(approve.body).groups.indexOf('ibs') !== -1,
          approve ? approve.body : '');

    section('Geleertes Feld bleibt leer');
    // `!= null` statt Falsyness: ein absichtlich geleertes Feld MUSS leer
    // gespeichert werden, sonst bliebe der alte Text stehen.
    // WICHTIG: loadPending() baut die Liste nach jeder Freigabe NEU auf – die
    // alte Knopf-Referenz zeigt dann ins Leere. Also frisch suchen.
    async function vorschauOeffnen() {
        const zeile = doc.querySelector('#wi-pending-list .wi-item');
        const btn = zeile && Array.from(zeile.querySelectorAll('button'))
            .find((b) => b.className.indexOf('danger') === -1);
        if (btn) { btn.click(); await sleep(25); }
        return btn;
    }
    check('Liste nach Freigabe neu aufgebaut', !!(await vorschauOeffnen()));
    const s2 = $('wi-rev-summary');
    s2.value = '';
    doc.querySelector('#wi-rev-groups input[type=checkbox]').checked = true;
    const vorher2 = calls.length;
    $('wi-rev-approve').click();
    await sleep(60);
    const patch2 = calls.slice(vorher2).find((c) => c.method === 'PATCH');
    let body2 = {};
    try { body2 = JSON.parse(patch2.body); } catch (e) { /* unten */ }
    check('leere Zusammenfassung wird als leer gesendet',
          patch2 && body2.summary === '', JSON.stringify(body2.summary));

    section('Ohne Zielgruppe keine Freigabe');
    await vorschauOeffnen();
    doc.querySelectorAll('#wi-rev-groups input[type=checkbox]').forEach((c) => { c.checked = false; });
    const vorher3 = calls.length;
    $('wi-rev-approve').click();
    await sleep(40);
    const freigabe3 = calls.slice(vorher3).find((c) => c.url.indexOf('/approve') !== -1);
    check('kein Freigabe-Aufruf ohne Gruppe', !freigabe3, JSON.stringify(calls.slice(vorher3)));
    check('Hinweis im Statusfeld', ($('wi-ext-status').textContent || '').length > 0,
          $('wi-ext-status').textContent);

    const ok = results.filter((r) => r.ok).length;
    console.log('\n' + '='.repeat(70));
    console.log(`ERGEBNIS: ${ok}/${results.length} Pruefungen bestanden`);
    console.log('='.repeat(70));
    if (ok !== results.length) {
        results.filter((r) => !r.ok).forEach((r) => console.log('  FEHLGESCHLAGEN: ' + r.name + ' – ' + r.detail));
    }
    return ok === results.length;
}

// AUFRAEUMEN NICHT VERGESSEN: wissen.js startet Dauer-Abfragen
// (setInterval fuer LLM-Status alle 30 s und CPU alle 3 s). Diese Timer halten
// den Node-Event-Loop offen – ohne window.close() + process.exit() laeuft der
// Test inhaltlich durch, der PROZESS bleibt aber fuer immer stehen. Genau das
// ist am 2026-07-30 passiert: sechs haengende node-Prozesse, jeder mit
// vollstaendiger, gruener Ausgabe.
main()
    .then((ok) => { schliessen(); process.exit(ok ? 0 : 1); })
    .catch((e) => { console.error(e); schliessen(); process.exit(1); });

function schliessen() {
    try { if (globalThis.__dom) globalThis.__dom.window.close(); } catch (e) { /* egal */ }
}
