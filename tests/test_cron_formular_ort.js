/* UI-Test: Bearbeiten-Formular der Cron-Aufgaben und Watcher (frontend/js/cron.js)
 * – jsdom, echte Datei.
 *
 * DER GEMELDETE FALL (2026-09-27): Einstellungen -> Tasks -> Cron-Aufgaben.
 * Ein Klick auf "Bearbeiten" oeffnete das Formular OBERHALB aller Aufgaben –
 * welcher Eintrag gerade bearbeitet wird, war nicht zu sehen. Das Formular
 * steht jetzt IN der Box des bearbeiteten Eintrags; die Neuanlage bleibt
 * oberhalb der Liste.
 *
 * Geprueft wird der ORT des Formulars im DOM (Elternkette), nicht ein Vorkommen
 * im Quelltext – und dass er ein Neuzeichnen der Liste (Aktualisieren,
 * Websocket-Ereignis) samt Eingaben ueberlebt.
 *
 * Lauf:  timeout 60 node tests/test_cron_formular_ort.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

const SRC = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'cron.js'), 'utf8');

const JOBS = [
    { id: 'a1', label: 'Erste',  cron: '0 7 * * *', task: 'Bericht A', enabled: true },
    { id: 'b2', label: 'Zweite', cron: '0 8 * * *', task: 'Bericht B', enabled: true },
    { id: 'c3', label: 'Dritte', cron: '0 9 * * *', task: 'Bericht C', enabled: false },
];
const WATCHERS = [
    { id: 'w1', label: 'Inbox',  trigger_type: 'file', path: '/x', pattern: '*', events: ['created'], action_type: 'agent_task', task: 't1', enabled: true },
    { id: 'w2', label: 'Archiv', trigger_type: 'file', path: '/y', pattern: '*', events: ['created'], action_type: 'agent_task', task: 't2', enabled: true },
];

function baue() {
    const dom = new JSDOM('<!doctype html><html><body><div id="cron-tab-content"></div></body></html>', {
        url: 'https://localhost/settings',
        runScripts: 'outside-only',
    });
    const { window } = dom;
    const state = { jobs: JOBS.map(j => ({ ...j })), watchers: WATCHERS.map(w => ({ ...w })) };
    window.t = (k) => k;
    /* Das ECHTE icons.js statt einer Attrappe mit nur `trash`. ⚠ Dieser
     * Pruefstand ist seit 8d082990 ohnehin tot (ihm fehlt ein
     * Sitzungstoken-Stub, Exit 2 mit "Liste nicht gerendert") - der Tausch
     * macht ihn NICHT gruen. Er steht hier, damit wer ihn wiederbelebt, nicht
     * dem Stift nachjagt: `_renderJobList` ruft seit 2026-10-06
     * `JarvisIcons.pencil()`, und die alte Attrappe haette genau denselben
     * Abbruch erzeugt - mit einer zweiten, falschen Ursache. */
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'icons.js'), 'utf8'));
    window.confirm = () => true;
    window.fetch = function (url, o) {
        const p = String(url).split('?')[0];
        const m = ((o && o.method) || 'GET').toUpperCase();
        let body = [];
        if (p === '/api/cron' && m === 'GET') body = state.jobs;
        else if (p === '/api/watchers' && m === 'GET') body = state.watchers;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
    // sitzung.js VOR cron.js - genau wie im Browser, wo sie das erste Skript
    // jeder Seite ist. `_authHeaders()` liest den Token seit dem 2026-10-01 aus
    // dieser EINEN Quelle (`window.JarvisSitzung.token()`), und die
    // Abhaengigkeit ist absichtlich hart: ein `window.JarvisSitzung && …` wuerde
    // ein fehlendes Skript wie "nicht angemeldet" aussehen lassen (siehe Kopf
    // von sitzung.js - gemessen, verworfen). Ohne diese Zeile wirft der erste
    // Abruf, `_loadJobs` faengt es, die Liste bleibt LEER und der Lauf endete
    // mit Exit 2 ohne Bilanzzeile. Dieselbe Zeile steht in test_cron_log_ui.js.
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'sitzung.js'), 'utf8'));
    window.eval(SRC);
    return { window, state };
}

function boxVon(doc, listId, id) {
    return [...doc.querySelectorAll('#' + listId + ' .cron-item')].find(el => el.dataset.id === id) || null;
}
function formBox(doc, formId) {
    const f = doc.getElementById(formId);
    return f ? f.closest('.cron-item') : null;
}

(async () => {
    try {
        const { window, state } = baue();
        const doc = window.document;
        const cm = window.cronManager;
        cm.init();
        await sleep(50);

        // Positivkontrolle: ohne gerenderte Liste ist jede Ortsaussage trivial.
        const n = doc.querySelectorAll('#cron-list .cron-item').length;
        const nw = doc.querySelectorAll('#watcher-list .cron-item').length;
        if (n !== JOBS.length || nw !== WATCHERS.length || !doc.getElementById('cron-form-wrap')) {
            console.log(`ABBRUCH: Liste nicht gerendert (Jobs ${n}/${JOBS.length}, Watcher ${nw}/${WATCHERS.length})`);
            window.close(); process.exit(2);
        }

        section('Cron: Bearbeiten steht in der Box des Eintrags');
        boxVon(doc, 'cron-list', 'b2').querySelector('.cron-edit-btn').click();
        let box = formBox(doc, 'cron-form-wrap');
        check('Formular steht in einer Aufgabenbox', !!box);
        check('… und zwar in der des bearbeiteten Eintrags', box && box.dataset.id === 'b2', box ? box.dataset.id : 'keine');
        check('Formular sichtbar', doc.getElementById('cron-form-wrap').style.display !== 'none');
        check('Felder mit dem Eintrag gefuellt', doc.getElementById('cron-label').value === 'Zweite');

        section('Cron: Neuzeichnen der Liste behaelt Ort und Eingaben');
        doc.getElementById('cron-label').value = 'Zweite geaendert';
        await cm._loadJobs();
        box = formBox(doc, 'cron-form-wrap');
        check('nach Neuzeichnen weiter in Box b2', box && box.dataset.id === 'b2', box ? box.dataset.id : 'keine');
        check('Eingabe ueberlebt das Neuzeichnen', doc.getElementById('cron-label').value === 'Zweite geaendert');
        check('genau ein Formular im Dokument', doc.querySelectorAll('#cron-form-wrap').length === 1);

        section('Cron: Wechsel zu anderem Eintrag');
        boxVon(doc, 'cron-list', 'c3').querySelector('.cron-edit-btn').click();
        box = formBox(doc, 'cron-form-wrap');
        check('Formular wandert in Box c3', box && box.dataset.id === 'c3', box ? box.dataset.id : 'keine');
        check('Box b2 ohne Formular', !boxVon(doc, 'cron-list', 'b2').querySelector('#cron-form-wrap'));

        section('Cron: Neuanlage und Abbrechen stehen ueber der Liste');
        doc.getElementById('cron-add-btn').click();
        let f = doc.getElementById('cron-form-wrap');
        check('Neue Aufgabe: nicht in einer Box', !formBox(doc, 'cron-form-wrap'));
        check('Neue Aufgabe: direkt vor der Liste', f.nextElementSibling === doc.getElementById('cron-list'));
        boxVon(doc, 'cron-list', 'a1').querySelector('.cron-edit-btn').click();
        doc.getElementById('cron-cancel-btn').click();
        f = doc.getElementById('cron-form-wrap');
        check('Abbrechen: Formular zu', f.style.display === 'none');
        check('Abbrechen: zurueck vor der Liste', f.nextElementSibling === doc.getElementById('cron-list'));

        section('Cron: bearbeiteter Eintrag verschwindet');
        boxVon(doc, 'cron-list', 'a1').querySelector('.cron-edit-btn').click();
        state.jobs = state.jobs.filter(j => j.id !== 'a1');
        await cm._loadJobs();
        f = doc.getElementById('cron-form-wrap');
        check('Formular existiert weiter', !!f);
        check('Formular geschlossen', f && f.style.display === 'none');
        check('keine Bearbeitung mehr offen', cm._editingJobId === null);

        section('Watcher: Bearbeiten steht in der Box des Eintrags');
        boxVon(doc, 'watcher-list', 'w2').querySelector('.watcher-edit-btn').click();
        box = formBox(doc, 'watcher-form-wrap');
        check('Watcher-Formular in Box w2', box && box.dataset.id === 'w2', box ? box.dataset.id : 'keine');
        await cm._loadWatchers();
        box = formBox(doc, 'watcher-form-wrap');
        check('nach Neuzeichnen weiter in Box w2', box && box.dataset.id === 'w2', box ? box.dataset.id : 'keine');
        doc.getElementById('watcher-add-btn').click();
        check('Neuer Watcher: vor der Liste',
              doc.getElementById('watcher-form-wrap').nextElementSibling === doc.getElementById('watcher-list'));

        window.close();
    } catch (e) {
        console.log('ABBRUCH:', e && e.stack || e);
        process.exit(2);
    }
    const fail = results.filter(r => !r.ok).length;
    console.log(`\n${results.length - fail}/${results.length} OK`);
    process.exit(fail ? 1 : 0);
})();
