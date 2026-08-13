/* UI-Test: Aktivitaetsmeldung (frontend/js/activity.js) – jsdom, echte Datei.
 *
 * DER GEMELDETE FALL (2026-08-13): Benutzer druecken F5 und klicken den
 * Info-Ordner an, stehen aber weiter mit "untaetig seit 2 Std. 37 Min." in der
 * Anwesenheitsliste. Ursache: nur POST/PUT/PATCH/DELETE galten als Handlung,
 * beides sind aber GETs. activity.js meldet jetzt, was ein MENSCH getan hat.
 *
 * Geprueft wird das Verhalten, das man am Quelltext NICHT ablesen kann:
 * meldet der Seitenaufbau? drosselt der zweite Klick? schweigt es ohne Token?
 * hoert es nach 401 auf? loesen Mausbewegung/Scrollen nichts aus?
 *
 * WICHTIG (Fallstrick 2026-07-30): am Ende window.close() + process.exit(),
 * sonst haelt jsdom den Node-Prozess offen.
 *
 * Lauf:  timeout 60 node tests/test_activity_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

const SRC = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'activity.js'), 'utf8');

/* Baut eine minimale Seite und laedt activity.js darin.
   `status` ist die Antwort, die die fetch-Attrappe liefert. */
function baue(opts) {
    opts = opts || {};
    const dom = new JSDOM('<!doctype html><html><body><div id="ziel">x</div></body></html>', {
        url: opts.url || 'https://localhost/portal',
        runScripts: 'outside-only',
    });
    const { window } = dom;
    if (opts.token !== null) window.localStorage.setItem('jarvis_token', opts.token || 'tok-123');

    const calls = [];
    let status = opts.status || 200;
    window.fetch = function (url, o) {
        o = o || {};
        calls.push({ url: String(url), method: (o.method || 'GET').toUpperCase(),
                     headers: o.headers || {}, body: o.body || '' });
        if (opts.netzfehler) return Promise.reject(new Error('offline'));
        return Promise.resolve({ ok: status < 400, status: status,
                                 json: () => Promise.resolve({ ok: true }) });
    };
    // Uhr steuerbar machen (Drosselung pruefen, ohne 60 s zu warten).
    let versatz = 0;
    const echt = window.Date.now.bind(window.Date);
    window.Date.now = () => echt() + versatz;

    window.eval(SRC);
    return {
        dom, window, calls,
        meldungen: () => calls.filter((c) => c.url.indexOf('/api/activity') === 0),
        vorspulen: (ms) => { versatz += ms; },
        setStatus: (s) => { status = s; },
        klick: () => window.document.getElementById('ziel')
            .dispatchEvent(new window.Event('pointerdown', { bubbles: true })),
        taste: () => window.document.getElementById('ziel')
            .dispatchEvent(new window.Event('keydown', { bubbles: true })),
        maus: () => window.document.getElementById('ziel')
            .dispatchEvent(new window.Event('mousemove', { bubbles: true })),
        scroll: () => window.document.dispatchEvent(new window.Event('scroll', { bubbles: true })),
    };
}

let offen = [];
function aufraeumen() {
    offen.forEach((d) => { try { d.window.close(); } catch (e) { /* egal */ } });
    offen = [];
}

async function main() {
    // ── 1. Der gemeldete Fall: F5 und Klick ──────────────────────────────────
    section('1. Seitenaufbau und Klick werden gemeldet');
    {
        const t = baue({ url: 'https://localhost/portal' });
        offen.push(t.dom);
        await sleep(20);
        const m = t.meldungen();
        check('Seitenaufbau (F5) meldet genau einmal', m.length === 1, JSON.stringify(m.map(x => x.url)));
        check('Meldung ist ein POST', m[0] && m[0].method === 'POST', m[0] && m[0].method);
        check('Bearer-Token mitgeschickt',
              m[0] && String(m[0].headers.Authorization || '').indexOf('Bearer tok-123') === 0,
              m[0] && JSON.stringify(m[0].headers));
        let body = {};
        try { body = JSON.parse(m[0].body); } catch (e) { /* bleibt leer */ }
        check('Seitenkennung aus dem Pfad ("portal")', body.page === 'portal', JSON.stringify(body));

        // Der zweite Teil des gemeldeten Falls: der Klick auf den Ordner.
        // Innerhalb der Drosselung darf er NICHT erneut senden – die Meldung
        // vom Seitenaufbau ist Sekunden alt, die Aussage also schon richtig.
        t.klick();
        await sleep(20);
        check('Klick kurz nach dem Aufbau sendet nicht erneut (Drosselung)',
              t.meldungen().length === 1, String(t.meldungen().length));

        t.vorspulen(61000);
        t.klick();
        await sleep(20);
        check('Klick nach Ablauf der Drosselung meldet erneut',
              t.meldungen().length === 2, String(t.meldungen().length));

        t.vorspulen(61000);
        t.taste();
        await sleep(20);
        check('Tastendruck meldet ebenfalls', t.meldungen().length === 3, String(t.meldungen().length));
    }

    // ── 2. Was NICHT zaehlt ──────────────────────────────────────────────────
    section('2. Kein Rauschen: Maus und Scrollen sind keine Handlung');
    {
        const t = baue({});
        offen.push(t.dom);
        await sleep(20);
        const vorher = t.meldungen().length;
        t.vorspulen(61000);
        t.maus(); t.scroll();
        await sleep(20);
        check('Mausbewegung und Scrollen melden nichts',
              t.meldungen().length === vorher, String(t.meldungen().length));
    }

    // ── 3. Ohne Anmeldung ────────────────────────────────────────────────────
    section('3. Ohne Token wird nichts gemeldet');
    {
        const t = baue({ token: null });
        offen.push(t.dom);
        await sleep(20);
        t.vorspulen(61000);
        t.klick();
        await sleep(20);
        check('kein Aufruf ohne Token', t.meldungen().length === 0,
              JSON.stringify(t.calls.map(c => c.url)));
    }

    // ── 4. Abgemeldet/gesperrt: aufhoeren statt klopfen ──────────────────────
    section('4. Nach 401/403 wird nicht weiter gemeldet');
    for (const code of [401, 403]) {
        const t = baue({ status: code });
        offen.push(t.dom);
        await sleep(20);
        const nachAufbau = t.meldungen().length;
        t.vorspulen(61000);
        t.klick();
        await sleep(20);
        check(`nach ${code} keine weiteren Meldungen`,
              t.meldungen().length === nachAufbau && nachAufbau === 1,
              `${nachAufbau} -> ${t.meldungen().length}`);
    }

    // ── 5. Netzfehler darf nicht dauerhaft abschalten ────────────────────────
    section('5. Netzfehler: beim naechsten Klick erneut versuchen');
    {
        const t = baue({ netzfehler: true });
        offen.push(t.dom);
        await sleep(20);
        const ersteZahl = t.meldungen().length;
        t.klick();                       // OHNE Vorspulen – nach einem Fehler
        await sleep(20);                 // ist die Drosselung zurueckgesetzt
        check('nach Netzfehler wird sofort erneut versucht',
              t.meldungen().length === ersteZahl + 1,
              `${ersteZahl} -> ${t.meldungen().length}`);
    }

    // ── 6. Seitenkennung je Bereich ──────────────────────────────────────────
    section('6. Seitenkennung folgt dem Pfad');
    for (const [url, erwartet] of [['https://localhost/chat', 'chat'],
                                   ['https://localhost/email', 'email'],
                                   ['https://localhost/sap', 'sap'],
                                   ['https://localhost/settings', 'settings']]) {
        const t = baue({ url });
        offen.push(t.dom);
        await sleep(20);
        let body = {};
        try { body = JSON.parse(t.meldungen()[0].body); } catch (e) { /* leer */ }
        check(`${url} -> page="${erwartet}"`, body.page === erwartet, JSON.stringify(body));
    }

    // ── 7. Einbindung auf allen angemeldeten Seiten ──────────────────────────
    section('7. Einbindung in den Seiten');
    const seiten = ['portal.html', 'chat.html', 'wissen.html', 'support.html', 'userchat.html',
                    'settings.html', 'sap.html', 'email.html', 'api.html', 'supportagent.html'];
    seiten.forEach((s) => {
        const html = fs.readFileSync(path.join(ROOT, 'frontend', s), 'utf8');
        const treffer = (html.match(/js\/activity\.js/g) || []).length;
        check(`${s} bindet activity.js genau einmal ein`, treffer === 1, String(treffer));
    });

    // ── 8. Backend-Verdrahtung ───────────────────────────────────────────────
    section('8. Endpunkt im Backend');
    const main_src = fs.readFileSync(path.join(ROOT, 'backend', 'main.py'), 'utf8');
    check('POST /api/activity vorhanden', main_src.indexOf('@app.post("/api/activity")') > -1);
    check('haengt an require_auth (nicht Admin – jeder Benutzer meldet sich selbst)',
          /@app\.post\("\/api\/activity"\)\s*\nasync def [^\n]*\n?[^\n]*require_auth\b/.test(main_src));
    check('steht in _ACTION_IGNORE (sonst schreibt die Buchhaltung doppelt)',
          /_ACTION_IGNORE = \([^)]*\/api\/activity/.test(main_src));
    check('Beschriftung kommt aus der Whitelist, nicht aus dem Rumpf',
          main_src.indexOf('_ACTIVITY_PAGES.get(') > -1);
    // Kein Freitext aus dem Client in eine Admin-Ansicht.
    const rumpf = main_src.split('@app.post("/api/activity")')[1].split('@app.get(')[0];
    check('kein Rohwert als Beschriftung',
          !/label\s*=\s*str\(\s*rumpf\.get\("page"\)/.test(rumpf), rumpf.slice(0, 200));
    check('note_action wird gerufen', rumpf.indexOf('_user_sessions.note_action(') > -1);

    const ok = results.filter((r) => r.ok).length;
    console.log('\n' + '='.repeat(70));
    console.log(`ERGEBNIS: ${ok}/${results.length} Pruefungen bestanden`);
    console.log('='.repeat(70));
    if (ok !== results.length) {
        results.filter((r) => !r.ok).forEach((r) =>
            console.log('  FEHLGESCHLAGEN: ' + r.name + ' – ' + r.detail));
    }
    return ok === results.length;
}

main()
    .then((ok) => { aufraeumen(); process.exit(ok ? 0 : 1); })
    .catch((e) => { console.error(e); aufraeumen(); process.exit(1); });
