/* ═══════════════════════════════════════════════════════════════════
   Waechter: Jira-Reiter besteht aus ZWEI Klapp-Containern (2026-08-27)
   ───────────────────────────────────────────────────────────────────
   Vorher stand alles als h4-Ueberschriften untereinander in EINEM
   Block: Zugangsdaten, Vorlagen der Browser-Erweiterung, Ticketsuche.
   Jetzt zwei Container – „Verbindung" (Zugang + Ticketsuche) und
   „Browser Plugin Vorlagen".

   DIE FEHLERKLASSE, die dieser Test abdeckt, ist bekannt und im Projekt
   schon einmal bezahlt worden (Excel-Reiter, gemeldet 2026-08-20): das
   Markup traegt die Klassen `kb-collapse-header`/`-body`, gebunden wird
   aber ausschliesslich in app.js::_collapseInit. Fehlt der Eintrag
   dort, sehen die Container richtig aus und lassen sich NICHT klappen –
   ohne jede Fehlermeldung.

   Aufruf: node tests/test_jira_tab_ui.js
   ═══════════════════════════════════════════════════════════════════ */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.dirname(__dirname);
let ok = 0, fail = 0;
function pruefe(b, t) {
    if (b) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + t); }
    else   { fail++; console.log('  \x1b[31m✗\x1b[0m ' + t); }
}
function abschnitt(t) { console.log('\n── ' + t); }

const html   = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const appJs  = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const i18nJs = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const doc    = new JSDOM(html).window.document;
const tab    = doc.getElementById('settings-tab-jira');

// ── 1 · Die zwei Container stehen im Reiter ───────────────────────────
abschnitt('1 · Struktur');
pruefe(!!tab, 'Reiter settings-tab-jira vorhanden');

const CONT = [
    { id: 'ji-sect-conn', titel: 'Verbindung',              i18n: 'jira.sect_conn' },
    { id: 'ji-sect-vorl', titel: 'Browser Plugin Vorlagen', i18n: 'jvorl.h' },
];
for (const c of CONT) {
    const sect = doc.getElementById(c.id);
    const hdr  = doc.getElementById(c.id + '-hdr');
    const body = doc.getElementById(c.id + '-body');
    const tog  = doc.getElementById(c.id + '-tog');
    pruefe(!!sect && sect.classList.contains('kb-section'), `${c.id}: ist eine .kb-section`);
    pruefe(!!tab && !!sect && tab.contains(sect), `${c.id}: liegt im Jira-Reiter`);
    pruefe(!!hdr && hdr.classList.contains('kb-collapse-header'),
        `${c.id}-hdr: traegt kb-collapse-header`);
    pruefe(!!body && body.classList.contains('kb-collapse-body'),
        `${c.id}-body: traegt kb-collapse-body`);
    pruefe(!!tog, `${c.id}-tog: Umschalt-Zeichen vorhanden`);
    // Vorgabe ist AUFGEKLAPPT: _collapseInit liest ohne gespeicherten
    // Wert den HTML-Zustand, und `display:none` hiesse "zu".
    pruefe(!!body && body.style.display !== 'none', `${c.id}-body: startet aufgeklappt`);
    const h3 = hdr && hdr.querySelector('h3');
    pruefe(!!h3 && h3.textContent.trim() === c.titel, `${c.id}: Titel „${c.titel}"`);
    pruefe(!!h3 && h3.getAttribute('data-i18n') === c.i18n,
        `${c.id}: Titel folgt dem Sprachwechsel (${c.i18n})`);
}

// ── 2 · Jedes Bedienelement liegt im RICHTIGEN Container ──────────────
// Ein Feld, das ausserhalb eines Klapp-Koerpers haengen bleibt, ist beim
// Zuklappen weiter sichtbar – der Container waere dann eine Attrappe.
abschnitt('2 · Zuordnung der Bedienelemente');
const IN_CONN = ['jira-url', 'jira-token', 'jira-token-toggle', 'jira-max-results',
                 'jira-save', 'jira-test', 'jira-status', 'jira-search-q',
                 'jira-search-project', 'jira-search-btn', 'jira-search-jql',
                 'jira-results', 'jira-issue-view', 'jira-issue-title',
                 'jira-issue-link', 'jira-issue-meta', 'jira-issue-text',
                 'jira-issue-comments'];
const IN_VORL = ['jvorl-liste', 'jvorl-name', 'jvorl-text', 'jvorl-global',
                 'jvorl-global-zeile', 'jvorl-save', 'jvorl-new', 'jvorl-status'];
const connBody = doc.getElementById('ji-sect-conn-body');
const vorlBody = doc.getElementById('ji-sect-vorl-body');
const fehltConn = IN_CONN.filter(id => {
    const el = doc.getElementById(id);
    return !el || !connBody || !connBody.contains(el);
});
const fehltVorl = IN_VORL.filter(id => {
    const el = doc.getElementById(id);
    return !el || !vorlBody || !vorlBody.contains(el);
});
pruefe(fehltConn.length === 0, 'alle Verbindungs-/Such-Elemente im Container „Verbindung"'
    + (fehltConn.length ? ' – fehlt: ' + fehltConn.join(', ') : ''));
pruefe(fehltVorl.length === 0, 'alle Vorlagen-Elemente im Container „Browser Plugin Vorlagen"'
    + (fehltVorl.length ? ' – fehlt: ' + fehltVorl.join(', ') : ''));

// Die alte h4-Ueberschrift "Verbindung" darf nicht daneben stehenbleiben –
// sonst stuende der Titel zweimal untereinander.
const h4s = [...(tab ? tab.querySelectorAll('h4') : [])].map(h => h.textContent.trim());
pruefe(!h4s.includes('Verbindung'), 'keine doppelte h4-Ueberschrift „Verbindung" mehr');
pruefe(!h4s.some(x => x.startsWith('Vorlagen für')),
    'keine alte h4-Ueberschrift „Vorlagen für die Zusammenfassung" mehr');

// ── 3 · app.js bindet die Container wirklich ──────────────────────────
// DAS ist der eigentliche Zweck dieses Waechters (siehe Kopf).
abschnitt('3 · Klapp-Bindung in app.js');
pruefe(/function\s+_initJiraCollapse\s*\(/.test(appJs), '_initJiraCollapse ist definiert');

// Rumpf der Funktion schneiden – NICHT die ganze Datei durchsuchen, sonst
// faende der Test die Ids irgendwo anders und waere trivial wahr.
const iFn = appJs.indexOf('function _initJiraCollapse');
const rumpf = iFn >= 0 ? appJs.slice(iFn, appJs.indexOf('\n        }', iFn) + 10) : '';
for (const c of CONT) {
    pruefe(rumpf.includes(`'${c.id}-hdr'`) && rumpf.includes(`'${c.id}-body'`)
        && rumpf.includes(`'${c.id}-tog'`), `${c.id}: alle drei Ids an _collapseInit uebergeben`);
}

// Der Aufruf muss im Jira-Zweig der Reiter-Umschaltung stehen. Geprueft
// wird der Zweig, nicht die Datei: ein Aufruf an anderer Stelle liefe
// beim Oeffnen des Reiters nicht.
const iZweig = appJs.indexOf("target === 'jira'");
const zweig  = iZweig >= 0 ? appJs.slice(iZweig, iZweig + 500) : '';
const iAufruf = zweig.indexOf('_initJiraCollapse()');
const iNaechster = zweig.indexOf('} else if');
pruefe(iAufruf >= 0, 'Aufruf steht im Zweig target === \'jira\'');
// `iAufruf >= 0` ist hier Pflicht: ohne den Aufruf waere indexOf -1 und der
// Vergleich "-1 < irgendwas" trivial wahr – die Pruefung meldete dann
// Erfolg, obwohl gar nichts gebunden wird.
pruefe(iAufruf >= 0 && iNaechster >= 0 && iAufruf < iNaechster,
    'Aufruf steht VOR dem naechsten Zweig (gehoert also wirklich zu Jira)');

// ── 4 · Beschriftungen in DE und EN ───────────────────────────────────
abschnitt('4 · Uebersetzungen');
for (const key of ['jira.sect_conn', 'jvorl.h']) {
    const treffer = i18nJs.split('\n').filter(z => z.includes(`'${key}'`)).length;
    pruefe(treffer === 2, `${key}: in DE und EN je einmal belegt (gefunden: ${treffer})`);
}
pruefe(!/'jvorl\.h':\s*'Vorlagen für/.test(i18nJs),
    'jvorl.h traegt nicht mehr den alten deutschen Text');
pruefe(/'jvorl\.h':\s*'Browser Plugin Vorlagen'/.test(i18nJs),
    'jvorl.h heisst „Browser Plugin Vorlagen"');

console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
process.exit(fail ? 1 : 0);
