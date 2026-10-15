#!/usr/bin/env node
/**
 * Waechter: Spracheingabe im Browser bleibt auf dem eigenen Server.
 *
 * Hintergrund (todo.txt, Datenschutz STT, 2026-09-29): chat.js (Mic-Knopf) und
 * avatar.js nutzten window.SpeechRecognition – Chrome und Edge schicken das
 * Audio dabei an die Cloud von Google bzw. Microsoft. Seit 2026-10-02 nimmt
 * stt.js nur auf (MediaRecorder) und laedt an /api/stt hoch (Whisper lokal).
 *
 *  A  REGEL ueber ALLE Frontend-Module, am Syntaxbaum (acorn): kein Bezeichner,
 *     keine Eigenschaft und kein String-Literal "SpeechRecognition" /
 *     "webkitSpeechRecognition" (auch nicht als `'x' in window`-Probe).
 *     Kommentare zaehlen nicht – die Begruendung darf das Wort nennen.
 *  B  VERHALTEN von stt.js in jsdom mit Attrappen fuer Mikrofon, Recorder,
 *     Pegel und fetch: Upload nur an /api/stt, mit Token, nur wenn Sprache da
 *     war; Fehlercodes; Mikrofon wird freigegeben.
 *  C  EINBINDUNG: jede Seite mit avatar.js/chat.js laedt stt.js – und zwar
 *     VORHER (chat.js prueft window.JarvisSTT beim Laden, sonst verschwindet
 *     der Mic-Knopf ohne jede Meldung).
 *  D  i18n: die stt.*-Texte gibt es in DE und EN.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const JS = path.join(REPO, 'frontend', 'js');

let acorn = null;
for (const p of ['acorn', '/usr/share/nodejs/acorn',
                 path.join(REPO, 'node_modules/acorn'),
                 path.join(REPO, 'data/node_modules/acorn'),
                 '/tmp/node_modules/acorn']) {
    try { acorn = require(p); break; } catch (e) { /* weiter */ }
}
if (!acorn) { console.log('ABBRUCH (Exit 2): acorn nicht gefunden'); process.exit(2); }
const { JSDOM } = require('./lib/jsdom_laden')();

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });

// ── A: Regel am Syntaxbaum ──────────────────────────────────────────────────
const VERBOTEN = new Set(['SpeechRecognition', 'webkitSpeechRecognition']);

function funde(quelle, art) {
    const ast = acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: art || 'script',
                                      allowHashBang: true, locations: true });
    const out = [];
    (function lauf(n) {
        if (!n || typeof n.type !== 'string') return;
        if (n.type === 'Identifier' && VERBOTEN.has(n.name)) out.push(n.loc.start.line);
        if (n.type === 'Literal' && typeof n.value === 'string' && VERBOTEN.has(n.value)) out.push(n.loc.start.line);
        if (n.type === 'TemplateElement' && VERBOTEN.has((n.value && n.value.cooked) || '')) out.push(n.loc.start.line);
        for (const k of Object.keys(n)) {
            if (k === 'loc') continue;
            const v = n[k];
            if (Array.isArray(v)) v.forEach(lauf);
            else if (v && typeof v.type === 'string') lauf(v);
        }
    })(ast);
    return out;
}

console.log('A  Regel: kein Browser-Spracherkenner in frontend/js');
// Positivkontrolle der Sonde: alle drei Gestalten werden erkannt, ein Kommentar nicht
const probe = "// SpeechRecognition im Kommentar\n" +
              "var a = window.SpeechRecognition;\n" +
              "if ('webkitSpeechRecognition' in window) {}\n" +
              "new webkitSpeechRecognition();\n";
const pf = funde(probe);
check('Sonde erkennt Eigenschaft, String-Probe und Konstruktor (3), nicht den Kommentar',
      pf.length === 3 && !pf.includes(1), JSON.stringify(pf));
if (pf.length !== 3) { console.log('ABBRUCH (Exit 2): Sonde blind'); bilanz = true; process.exit(2); }

const dateien = [];
(function sammle(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) { if (e.name !== 'vendor') sammle(p); }
        else if (e.name.endsWith('.js') && !e.name.endsWith('.min.js')) dateien.push(p);
    }
})(JS);
let geparst = 0;
const gefunden = [], unlesbar = [];
for (const p of dateien) {
    let f;
    try { f = funde(fs.readFileSync(p, 'utf8')); geparst++; }
    catch (e) {
        // ES-Module (import/export) sind als Skript nicht parsebar
        try { f = funde(fs.readFileSync(p, 'utf8'), 'module'); geparst++; }
        catch (e2) { unlesbar.push(path.relative(REPO, p) + ': ' + e2.message); continue; }
    }
    for (const z of f) gefunden.push(path.relative(REPO, p) + ':' + z);
}
check('Module geparst (> 30, sonst misst die Regel nichts)', geparst > 30, String(geparst));
check('kein Modul ist fuer acorn unlesbar', unlesbar.length === 0, unlesbar.slice(0, 3).join('; '));
check('stt.js, chat.js und avatar.js sind darunter',
      ['stt.js', 'chat.js', 'avatar.js'].every(n => dateien.some(p => path.basename(p) === n)));
check('KEIN Modul benutzt (webkit)SpeechRecognition', gefunden.length === 0, gefunden.join(', '));

// ── C: Einbindung ───────────────────────────────────────────────────────────
console.log('\nC  Einbindung auf den Seiten');
const seiten = [];
(function sammle(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) sammle(p);
        else if (e.name.endsWith('.html')) seiten.push(p);
    }
})(path.join(REPO, 'frontend'));
const pos = (html, name) => {
    const m = html.match(new RegExp('<script[^>]+src="/static/js/' + name.replace('.', '\\.') + '\\?v=\\d+"'));
    return m ? m.index : -1;
};
let nutzer = 0;
const fehltSTT = [], zuSpaet = [];
for (const s of seiten) {
    const html = fs.readFileSync(s, 'utf8');
    const verbr = ['avatar.js', 'chat.js'].map(n => pos(html, n)).filter(i => i >= 0);
    if (!verbr.length) continue;
    nutzer++;
    const st = pos(html, 'stt.js');
    if (st < 0) fehltSTT.push(path.relative(REPO, s));
    else if (verbr.some(i => i < st)) zuSpaet.push(path.relative(REPO, s));
}
check('Seiten mit avatar.js/chat.js gefunden (> 5)', nutzer > 5, String(nutzer));
check('jede davon laedt stt.js', fehltSTT.length === 0, fehltSTT.join(', '));
check('stt.js steht jeweils VOR avatar.js/chat.js', zuSpaet.length === 0, zuSpaet.join(', '));

// ── D: i18n ─────────────────────────────────────────────────────────────────
console.log('\nD  Texte DE/EN');
const i18n = fs.readFileSync(path.join(JS, 'i18n.js'), 'utf8');
for (const k of ['stt.no_access', 'stt.no_mic', 'stt.no_speech', 'stt.failed', 'stt.working', 'common.stt_unsupported']) {
    const n = (i18n.match(new RegExp("\\n\\s*'" + k.replace('.', '\\.') + "':", 'g')) || []).length;
    check(k + ' in DE und EN', n === 2, 'gefunden: ' + n);
}
// Der Hinweis verweist nicht mehr auf bestimmte Browser – jeder mit Mikrofon-Aufnahme geht
const hinweis = (i18n.match(/\n\s*'common\.stt_unsupported':[^\n]*/g) || []).join('\n');
check('stt_unsupported nennt keinen Pflicht-Browser mehr', hinweis && !/Chrome|Edge/.test(hinweis), hinweis);

// ── B: Verhalten von stt.js ─────────────────────────────────────────────────
const STT = fs.readFileSync(path.join(JS, 'stt.js'), 'utf8');

function umgebung(opt) {
    opt = opt || {};
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only', url: 'https://jarvis.test/chat' });
    const w = dom.window;
    const zustand = { pegel: 0, fetches: [], spurenGestoppt: 0, antwort: opt.antwort || { status: 200, body: { text: 'hallo welt' } } };
    class MediaRecorder {
        constructor(stream, o) { this.stream = stream; this.mimeType = (o && o.mimeType) || 'audio/webm'; this.state = 'inactive'; }
        static isTypeSupported(t) { return t === 'audio/webm;codecs=opus'; }
        start() { this.state = 'recording'; }
        stop() {
            this.state = 'inactive';
            const self = this;
            setTimeout(() => {
                if (self.ondataavailable) self.ondataavailable({ data: new w.Blob(['opus'], { type: 'audio/webm' }) });
                if (self.onstop) self.onstop();
            }, 5);
        }
    }
    w.MediaRecorder = opt.ohneRecorder ? undefined : MediaRecorder;
    const spur = { stop() { zustand.spurenGestoppt++; } };
    Object.defineProperty(w.navigator, 'mediaDevices', { configurable: true, value: {
        getUserMedia() {
            if (opt.verweigert) { const e = new Error('nein'); e.name = 'NotAllowedError'; return Promise.reject(e); }
            return Promise.resolve({ getTracks: () => [spur] });
        } } });
    w.AudioContext = class {
        createAnalyser() { return { fftSize: 1024, getFloatTimeDomainData(b) { b.fill(zustand.pegel); } }; }
        createMediaStreamSource() { return { connect() {} }; }
        close() {}
    };
    w.fetch = (url, init) => {
        zustand.fetches.push({ url, init });
        const a = zustand.antwort;
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    w.eval(STT);
    return { w, zustand, dom };
}

function lauf(u, eingriff) {
    return new Promise((fertig) => {
        const ereignisse = { text: null, fehler: null, ende: 0, start: 0, verarbeitung: null };
        let h = null;
        h = u.w.JarvisSTT.starten({
            token: 'TOK', lang: 'de',
            onStart: () => { ereignisse.start++; eingriff(h, u.zustand); },
            onVerarbeitung: () => { ereignisse.verarbeitung = u.zustand.fetches.length; },
            onText: (t) => { ereignisse.text = t; },
            onFehler: (c) => { ereignisse.fehler = c; },
            onEnde: () => { ereignisse.ende++; setTimeout(() => fertig(ereignisse), 20); },
        });
        setTimeout(() => fertig(Object.assign(ereignisse, { zeitueberschreitung: true })), 6000);
    });
}

(async () => {
    console.log('\nB  Verhalten von stt.js');
    let u = umgebung();
    check('JarvisSTT ist definiert und verfuegbar', !!u.w.JarvisSTT && u.w.JarvisSTT.verfuegbar() === true);

    // 1. Sprechen, dann Pause -> automatisches Ende, Upload, Text
    let e = await lauf(u, (h, z) => { z.pegel = 0.2; setTimeout(() => { z.pegel = 0; }, 400); });
    check('Sprache + Pause: endet von selbst (ohne Zeitueberschreitung)', !e.zeitueberschreitung && e.ende === 1);
    check('genau EIN Upload', u.zustand.fetches.length === 1, String(u.zustand.fetches.length));
    const f = u.zustand.fetches[0] || { url: '', init: { headers: {} } };
    check('Ziel ist /api/stt?lang=de (eigener Server, relativ)', f.url === '/api/stt?lang=de', f.url);
    check('mit Sitzungstoken', (f.init.headers || {}).Authorization === 'Bearer TOK');
    check('Content-Type ohne Codec-Zusatz', (f.init.headers || {})['Content-Type'] === 'audio/webm');
    check('POST mit Blob-Rumpf', f.init.method === 'POST' && f.init.body instanceof u.w.Blob);
    check('erkannter Text kommt an', e.text === 'hallo welt', String(e.text));
    // Zwischen Aufnahme-Ende und Antwort vergehen auf CPU-Servern Sekunden – die
    // Oberflaeche braucht dafuer ein eigenes Signal, VOR dem Upload.
    check('onVerarbeitung kommt vor dem Upload', e.verarbeitung === 0, String(e.verarbeitung));
    check('kein Fehler gemeldet', e.fehler === null, String(e.fehler));
    check('Mikrofon freigegeben', u.zustand.spurenGestoppt >= 1);
    u.w.close();

    // 2. Nur Stille, dann Klick -> KEIN Upload
    u = umgebung();
    e = await lauf(u, (h) => { setTimeout(() => h.stoppen(), 300); });
    check('nur Stille: kein Upload', u.zustand.fetches.length === 0, String(u.zustand.fetches.length));
    check('nur Stille: Fehlercode keine_sprache', e.fehler === 'keine_sprache', String(e.fehler));
    check('nur Stille: Mikrofon freigegeben', u.zustand.spurenGestoppt >= 1);
    check('nur Stille: kein onVerarbeitung', e.verarbeitung === null, String(e.verarbeitung));
    u.w.close();

    // 3. Abbrechen nach Sprache -> kein Upload, kein Fehler
    u = umgebung();
    e = await lauf(u, (h, z) => { z.pegel = 0.2; setTimeout(() => h.abbrechen(), 300); });
    check('abbrechen: kein Upload', u.zustand.fetches.length === 0);
    check('abbrechen: kein Fehler, aber Ende', e.fehler === null && e.ende === 1);
    u.w.close();

    // 4. Zweiter Klick nach Sprache -> sofortiger Upload
    u = umgebung();
    e = await lauf(u, (h, z) => { z.pegel = 0.2; setTimeout(() => h.stoppen(), 300); });
    check('stoppen nach Sprache: Upload und Text', u.zustand.fetches.length === 1 && e.text === 'hallo welt');
    u.w.close();

    // 5. Mikrofon verweigert
    u = umgebung({ verweigert: true });
    e = await lauf(u, () => {});
    check('verweigert: Fehlercode kein_zugriff', e.fehler === 'kein_zugriff', String(e.fehler));
    check('verweigert: kein Upload', u.zustand.fetches.length === 0);
    u.w.close();

    // 6. Serverfehler und leerer Text
    u = umgebung({ antwort: { status: 503, body: { detail: 'x' } } });
    e = await lauf(u, (h, z) => { z.pegel = 0.2; setTimeout(() => h.stoppen(), 300); });
    check('Server 503: Fehlercode server, kein Text', e.fehler === 'server' && e.text === null, String(e.fehler));
    u.w.close();
    u = umgebung({ antwort: { status: 200, body: { text: '   ' } } });
    e = await lauf(u, (h, z) => { z.pegel = 0.2; setTimeout(() => h.stoppen(), 300); });
    check('leerer Text vom Server: keine_sprache, kein onText', e.fehler === 'keine_sprache' && e.text === null);
    u.w.close();

    // 7. Ohne MediaRecorder: nicht verfuegbar, Fehlercode statt Absturz
    u = umgebung({ ohneRecorder: true });
    check('ohne MediaRecorder: verfuegbar() === false', u.w.JarvisSTT.verfuegbar() === false);
    e = await lauf(u, () => {});
    check('ohne MediaRecorder: nicht_unterstuetzt', e.fehler === 'nicht_unterstuetzt', String(e.fehler));
    u.w.close();

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
