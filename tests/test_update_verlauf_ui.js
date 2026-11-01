#!/usr/bin/env node
/**
 * Update-Pill: Knopf "Aenderungsverlauf" im Popup.
 *
 * Gemeldet 2026-10-31: die Commit-Liste im Popup zeigt nur ausstehende
 * Commits – auf einem aktuellen Server ist sie leer, ein Verlauf war nirgends
 * zu finden. Geprueft im echten Markup von portal.html mit dem echten Modul:
 *   1. Der Knopf steht in der Fusszeile, AUCH wenn kein Update ansteht.
 *   2. Klick zeigt den Verlauf, das Popup bleibt offen.
 *   3. Ausstehende Commits tragen eine TEXT-Marke, eingespielte nicht.
 *   4. Hash verlinkt auf GitHub (neuer Tab), ohne Web-Adresse kein Link.
 *   5. Die periodische Pruefung ueberschreibt den Verlauf nicht.
 *   6. "Zurueck" fuehrt zur Statusansicht.
 *   7. Ein Fehler bleibt mit Grund stehen.
 *
 *   node tests/test_update_verlauf_ui.js
 */
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' - ' + d : '')); }
};
const ROOT = path.resolve(__dirname, '..');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const JS = lies('frontend/js/update_widget.js');

const VERLAUF = {
    ok: true, branch: 'master', ref: 'origin/master', web: 'https://github.com/beispiel/projekt',
    weitere: 0,
    commits: [
        { hash: 'aaaaaaa', hash_voll: 'a'.repeat(40), message: 'neu', beschreibung: 'Ausstehend.',
          date: '2026-10-31 10:00', eingespielt: false },
        { hash: 'bbbbbbb', hash_voll: 'b'.repeat(40), message: 'alt', beschreibung: 'Schon da.',
          date: '2026-10-30 10:00', eingespielt: true },
    ],
};

function starte(verlaufAntwort) {
    const vc = new VirtualConsole(); vc.on('jsdomError', () => {});
    const dom = new JSDOM(lies('frontend/portal.html'),
                          { url: 'https://x/portal', runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    sitzungLaden(w);
    w.JarvisSitzung = { token: () => 't:1:x' };
    w.__abrufe = [];
    w.fetch = (u) => {
        u = String(u);
        w.__abrufe.push(u);
        const pfad = u.split('?')[0];
        const antw = (d) => Promise.resolve({ ok: true, json: () => Promise.resolve(d) });
        if (pfad === '/api/update/status') return antw({ ok: true, has_update: false, commits_behind: 0,
            jarvis_version: '0.9', current_hash: 'bbbbbbb', branch: 'master', recent_commits: [] });
        if (pfad === '/api/update/settings') return antw({ auto_update_schedule: 'never' });
        if (pfad === '/api/update/verlauf') return antw(verlaufAntwort);
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    };
    // Den 30-Minuten-Takt abfangen: Probe 5 ruft genau diesen Rueckruf.
    w.__takt = null;
    w.setInterval = (fn) => { w.__takt = fn; return 1; };
    w.t = (k) => k;
    w.eval(JS);
    w.JarvisUpdateWidget.init();
    return w;
}
const warte = () => new Promise((r) => setTimeout(r, 20));

(async () => {
    let w = starte(VERLAUF);
    const d = w.document;
    d.getElementById('version-pill').click();       // Popup oeffnen
    await warte();
    const dd = d.getElementById('update-dropdown');
    if (!dd || dd.classList.contains('hidden')) {
        console.log('ABBRUCH: Popup oeffnet sich im Pruefstand nicht'); process.exit(2);
    }

    const btn = d.getElementById('upd-verlauf-btn');
    pruefe(!!btn, '1. Knopf "Änderungsverlauf" vorhanden, obwohl kein Update ansteht');
    pruefe(btn && d.getElementById('upd-foot').contains(btn), '   ... in der festen Fusszeile');
    pruefe(btn && btn.textContent === 'update.verlauf_btn', '   ... beschriftet über i18n');
    if (!btn) { console.log('\n' + ok + ' OK, ' + fail + ' FAIL'); process.exit(1); }

    btn.click();
    await warte();
    const body = d.getElementById('upd-body');
    pruefe(!dd.classList.contains('hidden'), '2. Popup bleibt nach dem Klick offen');
    pruefe(w.__abrufe.some((u) => u.split('?')[0] === '/api/update/verlauf'), '   Verlauf wird abgerufen');
    const zeilen = body.querySelectorAll('.upd-commit');
    pruefe(zeilen.length === 2, '   beide Commits gelistet', String(zeilen.length));

    const offen = body.querySelectorAll('.upd-commit-offen');
    pruefe(offen.length === 1 && offen[0].textContent === 'update.verlauf_ausstehend',
           '3. genau der ausstehende Commit trägt eine Textmarke', String(offen.length));
    pruefe(zeilen[1] && !zeilen[1].querySelector('.upd-commit-offen'), '   eingespielter ohne Marke');
    pruefe(/update\.verlauf_kopf_offen/.test(body.textContent), '   Kopfzeile nennt ausstehende');

    const link = zeilen[0] && zeilen[0].querySelector('a.upd-commit-hash');
    pruefe(link && link.getAttribute('href') === 'https://github.com/beispiel/projekt/commit/' + 'a'.repeat(40),
           '4. Hash verlinkt auf den Commit auf GitHub', link && link.getAttribute('href'));
    pruefe(link && link.target === '_blank' && /noopener/.test(link.rel), '   neuer Tab, noopener');

    // 5. Periodische Pruefung (wie der 30-min-Takt) darf den Verlauf nicht ersetzen
    const vorher = body.innerHTML;
    w.__abrufe.length = 0;
    if (typeof w.__takt !== 'function') { console.log('ABBRUCH: Takt nicht abgefangen'); process.exit(2); }
    w.__takt();
    await warte();
    pruefe(w.__abrufe.some((u) => u.split('?')[0] === '/api/update/status'),
           '5. Positivkontrolle: der Takt hat den Status wirklich abgerufen');
    pruefe(body.innerHTML === vorher, '   Verlauf bleibt stehen, solange er angezeigt wird');

    const zur = d.getElementById('upd-zurueck-btn');
    pruefe(!!zur && d.getElementById('upd-foot').contains(zur), '6. Zurück-Knopf in der Fusszeile');
    if (zur) { zur.click(); await warte(); }
    pruefe(!dd.classList.contains('hidden'), '   Popup bleibt nach "Zurück" offen');
    pruefe(!!d.getElementById('upd-verlauf-btn') && !body.querySelector('.upd-commit-offen'),
           '   Statusansicht wieder da');

    // 7. Fehler
    w = starte({ ok: false, error: 'git log fehlgeschlagen' });
    w.document.getElementById('version-pill').click(); await warte();
    w.document.getElementById('upd-verlauf-btn').click(); await warte();
    const fb = w.document.getElementById('upd-body').textContent;
    pruefe(/update\.verlauf_fehler/.test(fb), '7. Fehler wird angezeigt', fb.slice(0, 80));

    // Ohne Web-Adresse: kein Link
    w = starte(Object.assign({}, VERLAUF, { web: '' }));
    w.document.getElementById('version-pill').click(); await warte();
    w.document.getElementById('upd-verlauf-btn').click(); await warte();
    pruefe(!w.document.querySelector('#upd-body a.upd-commit-hash')
           && w.document.querySelectorAll('#upd-body span.upd-commit-hash').length === 2,
           '   ohne GitHub-Adresse Hash ohne Link');

    // i18n DE+EN
    const I18N = lies('frontend/js/i18n.js');
    for (const k of ['verlauf_btn', 'verlauf_zurueck', 'verlauf_ausstehend', 'verlauf_kopf',
                     'verlauf_kopf_offen', 'verlauf_fehler', 'verlauf_mehr', 'verlauf_laedt', 'verlauf_github']) {
        const n = (I18N.match(new RegExp("^\\s*'update\\." + k + "':", 'gm')) || []).length;
        pruefe(n === 2, "i18n 'update." + k + "' in DE und EN", String(n));
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
