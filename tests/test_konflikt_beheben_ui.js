/* Waechter: aus der Gesamtpruefung wird eine OPTIMIERUNG – geklickt, nicht gelesen.
 *
 * Gemeldet 2026-09-07: „‚Widersprüche über alle Anweisungen' liefert nur eine
 * Analyse ohne Möglichkeit zur Optimierung." Der ECHTE Renderer laeuft hier
 * gegen ein echtes DOM: erst die Gesamtpruefung, dann der Klick auf „Diese
 * Konflikte beheben", und danach MUSS der vorhandene Optimier-Weg dastehen
 * (Vorher/Nachher-Karten, Übernehmen-Kaestchen, sichtbarer Sammel-Knopf).
 *
 * Geprueft wird die REGEL, nicht ein Wortlaut:
 *   1. nach der Gesamtpruefung gibt es den Knopf – und er nennt die Anzahl
 *   2. der Klick schickt die KONFLIKTE mit (sonst raeumt der Lauf allgemein auf
 *      und verfehlt womoeglich genau den gemeldeten Fund)
 *   3. er benutzt den VORHANDENEN Weg: es entstehen dieselben Karten, und der
 *      Sammel-Knopf "Übernehmen" wird sichtbar – kein zweiter Schreibpfad
 *   4. was NICHT behebbar ist, steht dabei (nur-BASIS-Konflikte)
 *   5. ohne behebbare Datei erscheint KEIN Knopf, aber eine Auskunft
 *   6. ohne Konflikte bleibt alles wie bisher
 */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
for (const kandidat of [process.env.JSDOM_PATH, 'jsdom',
                        path.resolve(__dirname, '../node_modules/jsdom'),
                        path.resolve(__dirname, '../data/node_modules/jsdom'),
                        '/tmp/node_modules/jsdom',
                        '/usr/share/nodejs/jsdom'].filter(Boolean)) {
    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) {
    console.log('\x1b[31mABBRUCH: jsdom nicht installiert (JSDOM_PATH setzen)\x1b[0m');
    process.exit(2);
}

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, bilanz = false;

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (typeof name !== 'string') {
        console.log('\x1b[31mABBRUCH: check() falsch herum\x1b[0m'); process.exit(2);
    }
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(t) { console.log('\x1b[31mABBRUCH: ' + t + '\x1b[0m'); process.exit(2); }

process.on('exit', function (code) {
    if (!bilanz && code === 0) {
        console.log('\x1b[31mABBRUCH: Lauf endete ohne Bilanzzeile\x1b[0m');
        process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('\x1b[31mABBRUCH: unbehandelte Zurueckweisung: ' + e + '\x1b[0m');
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
});
const WACHHUND = setTimeout(function () {
    bilanz = true;
    console.log('\x1b[31m✗ Wachhund: der Lauf haengt (>40 s)\x1b[0m');
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
}, 40000);

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const JS_KB = fs.readFileSync(path.join(ROOT, 'frontend/js/knowledge.js'), 'utf8');
const JS_I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const JS_ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

const KONFLIKTE = [
    { art: 'dopplung', quellen: ['agents.md', 'soul.md'],
      regel_a: 'Frage nicht um Erlaubnis fuer Standardoperationen.',
      regel_b: 'Frage nicht nach Erlaubnis fuer offensichtliche Handlungen.',
      was_tun: 'Eine der beiden Stellen entfernen.' },
    { art: 'widerspruch', quellen: ['BASIS'],
      regel_a: 'A', regel_b: 'B', was_tun: 'x' },
];

// Ein Lauf: Seite bauen, Gesamtpruefung fahren, optional den Knopf klicken.
async function lauf(opt) {
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/settings',
        runScripts: 'outside-only',
        pretendToBeVisual: false,
    });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    win.matchMedia = win.matchMedia || (() => ({ matches: false, addListener() {},
        removeListener() {}, addEventListener() {}, removeEventListener() {} }));
    win.confirm = () => true;
    win.alert = () => {};
    win.eval(JS_ICONS);
    win.eval(JS_I18N);        // ECHTE Texte: eine t()-Attrappe verschluckt {n}/{d}

    const gerufen = [];
    function antwort(körper, status) {
        return Promise.resolve({
            ok: (status || 200) < 400, status: status || 200,
            json: () => Promise.resolve(körper),
            text: () => Promise.resolve(JSON.stringify(körper)),
        });
    }
    const attrappe = function (url, o) {
        const p = String(url).split('?')[0];
        let rumpf = null;
        try { rumpf = o && o.body ? JSON.parse(o.body) : null; } catch (e) {}
        gerufen.push({ pfad: p, rumpf });
        if (p === '/api/knowledge/cleanup/quellen') {
            return antwort({ ok: true, quellen: [{ name: 'BASIS', bytes: 100, referenz: true },
                                                 { name: 'agents.md', bytes: 50 },
                                                 { name: 'soul.md', bytes: 50 }] });
        }
        if (p === '/api/knowledge/cleanup/regeln') return antwort({ ok: true, zeilen: ['[a] x'] });
        if (p === '/api/knowledge/cleanup/abgleich') {
            return antwort({ ok: true, regeln: 3, konflikte: opt.konflikte,
                             aehnlich: [], hinweis: 'Hinweis' });
        }
        if (p === '/api/knowledge/cleanup/behebbar') {
            return opt.behebbarFehler ? antwort({}, 500) : antwort({
                ok: true, dateien: opt.dateien, namen: opt.namen, offen: opt.offen });
        }
        if (p === '/api/knowledge/cleanup/analyse') {
            return antwort({ ok: true, modell: 'testmodell', ergebnisse:
                (opt.dateien || []).map(k => ({
                    schluessel: k, ok: true, art: 'anweisung', geaendert: true,
                    alt: 'Zeile A\nZeile B\n', neu: 'Zeile A\n',
                    begruendung: 'Dopplung entfernt', funde: [],
                    bytes_alt: 16, bytes_neu: 8 })) });
        }
        if (p === '/api/knowledge/cleanup/prompt') return antwort({ ok: false });
        return antwort({ ok: true });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;

    win.eval(JS_KB);
    const mgr = win.knowledgeManager;
    if (!mgr) abbruch('window.knowledgeManager fehlt – knowledge.js nicht geladen');

    // Der Dialog wird sonst von cleanupOeffnen() gebaut; hier genuegt der Koerper.
    const body = win.document.getElementById('kb-cleanup-body');
    if (!body) abbruch('#kb-cleanup-body nicht im echten Markup von settings.html');
    const apply = win.document.getElementById('kb-cleanup-apply');
    if (!apply) abbruch('#kb-cleanup-apply nicht im echten Markup');

    await mgr.cleanupKonflikte();
    const nachPruefung = {
        html: body.innerHTML,
        knopf: win.document.getElementById('kb-cl-k-fix'),
        applySichtbar: apply.style.display !== 'none',
    };
    if (opt.klicken && nachPruefung.knopf) {
        await mgr.cleanupKonflikteBeheben();
        for (let i = 0; i < 200; i++) {
            await new Promise(r => setImmediate(r));
            if (body.querySelectorAll('.kb-cl-take').length) break;
        }
    }
    const aus = {
        gerufen, nachPruefung,
        html: body.innerHTML,
        text: (body.textContent || '').replace(/\s+/g, ' '),
        karten: body.querySelectorAll('.kb-cl-karte').length,
        // ⚠ ISOLIERT: die Dateinamen stehen AUCH in den Konflikt-Karten
        // (quellen.join). Ueber body.textContent war "die Dateien werden
        // benannt" trivial wahr – die Gegenprobe blieb stumm.
        fixhint: [...body.querySelectorAll('.kb-cl-fixhint')]
            .map(e => e.textContent).join(' | '),
        nehmen: body.querySelectorAll('.kb-cl-take').length,
        diffs: body.querySelectorAll('.kb-cl-diff').length,
        applySichtbar: apply.style.display !== 'none',
        applyText: apply.textContent || '',
        status: (win.document.getElementById('kb-cl-status') || {}).textContent || '',
    };
    try { win.close(); } catch (e) {}
    return aus;
}

(async function () {
    // ══ 1. Der Knopf entsteht ═════════════════════════════════════════════
    abschnitt('1 – Nach der Gesamtpruefung gibt es einen Weg zur Optimierung');

    const a = await lauf({ konflikte: KONFLIKTE, dateien: ['anweisung:agents.md', 'anweisung:soul.md'],
                           namen: ['agents.md', 'soul.md'], offen: [KONFLIKTE[1]] });
    check('die Gesamtpruefung lief (Abgleich gerufen)',
          a.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/abgleich'));
    check('Knopf "Konflikte beheben" ist da', !!a.nachPruefung.knopf);
    check('er nennt die Anzahl der Dateien (Platzhalter aufgelöst)',
          !!a.nachPruefung.knopf && /2/.test(a.nachPruefung.knopf.textContent)
          && !/\{n\}/.test(a.nachPruefung.knopf.textContent),
          a.nachPruefung.knopf && a.nachPruefung.knopf.textContent);
    check('die betroffenen Dateien werden im HINWEIS benannt (nicht nur in den Karten)',
          /agents\.md/.test(a.fixhint) && /soul\.md/.test(a.fixhint), a.fixhint);
    check('das Backend entscheidet, was anfassbar ist (/behebbar gerufen)',
          a.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/behebbar'));
    check('und bekommt die Konflikte dafuer',
          a.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/behebbar'
                              && (g.rumpf && (g.rumpf.konflikte || []).length === 2)));

    // ══ 2. Was NICHT geht, steht dabei ════════════════════════════════════
    abschnitt('2 – Der nur-BASIS-Fund wird als offen benannt');
    check('Hinweis auf nicht behebbare Funde – im Hinweisbereich',
          /nicht beheben|Basis-Prompt|cannot be resolved/.test(a.fixhint), a.fixhint);

    // ══ 3. Der Klick fuehrt in den VORHANDENEN Optimier-Weg ═══════════════
    abschnitt('3 – Klick: Vorher/Nachher, Übernehmen – kein zweiter Schreibweg');

    const b = await lauf({ konflikte: KONFLIKTE, dateien: ['anweisung:agents.md', 'anweisung:soul.md'],
                           namen: ['agents.md', 'soul.md'], offen: [KONFLIKTE[1]],
                           klicken: true });
    check('/analyse wurde gerufen', b.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/analyse'));
    const an = b.gerufen.filter(g => g.pfad === '/api/knowledge/cleanup/analyse');
    check('DIE KONFLIKTE GEHEN MIT (sonst raeumt der Lauf am Fund vorbei)',
          an.length > 0 && an.every(g => (g.rumpf.konflikte || []).length === 2),
          an.map(g => (g.rumpf && (g.rumpf.konflikte || []).length)));
    check('und die Dateien, die das Backend genannt hat',
          an.length > 0 && an[0].rumpf.dateien
          && an[0].rumpf.dateien.every(d => String(d).startsWith('anweisung:')),
          an[0] && an[0].rumpf.dateien);
    check('es entstehen Vorher/Nachher-Karten', b.karten >= 2, b.karten);
    check('mit Übernehmen-Kaestchen je Karte', b.nehmen >= 2, b.nehmen);
    check('und einem Zeilenvergleich', b.diffs >= 2, b.diffs);
    check('der Sammel-Knopf "Übernehmen" ist SICHTBAR', b.applySichtbar, b.applyText);
    check('er nennt die Anzahl', /2/.test(b.applyText) && !/\{n\}/.test(b.applyText),
          b.applyText);
    check('vor dem Klick war er versteckt (die Analyse allein schreibt nichts)',
          a.nachPruefung.applySichtbar === false);

    // ══ 4. Nichts behebbar ════════════════════════════════════════════════
    abschnitt('4 – Nur BASIS beteiligt: kein Knopf, aber eine Auskunft');

    const c = await lauf({ konflikte: [KONFLIKTE[1]], dateien: [], namen: [],
                           offen: [KONFLIKTE[1]] });
    check('KEIN Knopf', !c.nachPruefung.knopf);
    check('aber der Grund steht da',
          /nicht beheben|Basis-Prompt|cannot be resolved/.test(c.fixhint), c.fixhint);
    check('kein /analyse-Aufruf', !c.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/analyse'));

    // ══ 5. Keine Konflikte ════════════════════════════════════════════════
    abschnitt('5 – Ohne Funde bleibt alles wie bisher');

    const d = await lauf({ konflikte: [], dateien: [], namen: [], offen: [] });
    check('kein Knopf', !d.nachPruefung.knopf);
    check('kein /behebbar-Aufruf (nichts zu fragen)',
          !d.gerufen.some(g => g.pfad === '/api/knowledge/cleanup/behebbar'));
    check('die Entwarnung steht da', /Keine Widersprüche|No contradictions/.test(d.text),
          d.text.slice(0, 200));
    check('Übernehmen bleibt versteckt', d.applySichtbar === false);

    // ══ 6. Fehlerfall der Auskunft ════════════════════════════════════════
    abschnitt('6 – Antwortet /behebbar nicht, gibt es keinen Knopf (fail-closed)');

    const e = await lauf({ konflikte: KONFLIKTE, behebbarFehler: true,
                           dateien: [], namen: [], offen: [] });
    check('kein Knopf ohne Auskunft', !e.nachPruefung.knopf);
    check('die Konfliktliste steht trotzdem da (die Analyse bleibt nutzbar)',
          /agents\.md/.test(e.text) || /Standardoperationen/.test(e.text),
          e.text.slice(0, 200));

    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail === 0 ? 0 : 1);
})();
