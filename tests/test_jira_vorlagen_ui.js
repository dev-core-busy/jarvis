#!/usr/bin/env node
/* UI-Waechter: Vorlagen des Jira-Assistenten im Einstellungs-Reiter
 * (jsdom, echte settings.html / jira.js / icons.js / i18n.js).
 *
 * GEMELDET 2026-08-27: "es gibt keinen Reiter im Einstellungen Bereich, d.h.
 * Vorlagen koennen nicht vernuenftig gepflegt werden". Zutreffend: die Vorlagen
 * liessen sich ausschliesslich im Fenster der Browser-Erweiterung pflegen –
 * ausgerechnet die GEMEINSAMEN, die einem Administrator gehoeren, in einem
 * schmalen Popup und nur mit installierter Erweiterung.
 *
 * Gemessen wird der Reiter WIRKLICH: jira.js wird ausgefuehrt, die Liste
 * gerendert, geklickt und der abgeschickte Rumpf eingefangen. Ein
 * Quelltext-Test wuerde hier nichts belegen – die haeufigste Ursache fuer einen
 * toten Knopf ist, dass er gar nicht verdrahtet ist.
 *
 * Lauf:  timeout 90 node tests/test_jira_vorlagen_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) { ({ JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom')); }

const ROOT = path.resolve(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const HTML = read('frontend/settings.html');

// Der Bestand des Servers: eine gemeinsame Vorlage und eine eigene.
const START = {
    global: [{ id: 'g1', name: 'Kurz für die Leitung', text: 'Höchstens fünf Sätze.' }],
    eigene: [{ id: 'e1', name: 'Mein Blick', text: 'Nur die offenen Punkte.' }],
};

function mkFetch(state) {
    return function (url, opts) {
        const u = String(url);
        const method = (opts && opts.method) || 'GET';
        let body = null;
        try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
        state.calls.push({ method, url: u, body });
        const j = (data, ok = true, status = 200) => Promise.resolve({
            ok, status, json: () => Promise.resolve(data), text: () => Promise.resolve(''),
        });
        if (u.startsWith('/api/jira/assist/vorlagen')) {
            if (method === 'GET') {
                if (state.listFail) return j({ ok: false, error: 'Vorlagen nicht lesbar' }, false, 500);
                return j({ ok: true, global: state.global, eigene: state.eigene,
                           darf_global: state.darfGlobal });
            }
            if (method === 'POST') {
                // Der Server entscheidet, WOHIN gespeichert wird – hier nur
                // nachgebildet, damit die Liste danach stimmt.
                const ziel = body.global ? state.global : state.eigene;
                const vorhanden = ziel.find((v) => v.id === body.id);
                if (vorhanden) { vorhanden.name = body.name; vorhanden.text = body.text; }
                else ziel.push({ id: 'neu1', name: body.name, text: body.text });
                return j({ ok: true, vorlage: vorhanden || ziel[ziel.length - 1] });
            }
            if (method === 'DELETE') {
                const id = decodeURIComponent(u.split('/').pop());
                state.global = state.global.filter((v) => v.id !== id);
                state.eigene = state.eigene.filter((v) => v.id !== id);
                return j({ ok: true });
            }
        }
        if (u.startsWith('/api/skills/jira/config')) return j({ config: { base_url: 'https://j.test' } });
        return j({ ok: true });
    };
}

function makeDom(state, opts) {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.confirm = () => (state.confirmAntwort !== false);
    w.alert = () => {};
    w.scrollTo = () => {};
    w.fetch = mkFetch(state);
    // icons.js zuerst – jira.js ruft JarvisIcons.trash() beim Rendern auf.
    w.eval(read('frontend/js/icons.js'));
    if (!(opts && opts.ohneI18n)) w.eval(read('frontend/js/i18n.js'));
    w.eval(read('frontend/js/jira.js'));
    return dom;
}

/* Beides FEHLERTOLERANT – ein fehlendes Element muss FEHLSCHLAGEN, nicht
 * werfen: eine Gegenprobe, die mit TypeError abbricht, liefert gar keine Zahl
 * und ist von "nicht gelaufen" nicht zu unterscheiden (Register). */
const zeilenTexte = (d) => {
    const box = d.getElementById('jvorl-liste');
    return box ? Array.from(box.children).map((e) => e.textContent) : [];
};

function klick(w, d, sel, idx, was) {
    const el = d.querySelectorAll(sel)[idx];
    if (!el) { check('Bedienelement vorhanden: ' + was, false, sel + '[' + idx + ']'); return false; }
    el.dispatchEvent(new w.Event('click', { bubbles: true }));
    return true;
}
function wert(d, id) { const e = d.getElementById(id); return e ? e.value : null; }
function text(d, id) { const e = d.getElementById(id); return e ? e.textContent : ''; }

(async () => {
    // ══════════════════════════════════════════════════════════════════════
    section('1) Das Markup liegt im Jira-Reiter – nicht irgendwo auf der Seite');
    // ══════════════════════════════════════════════════════════════════════
    {
        const dom = new JSDOM(HTML, { runScripts: 'outside-only' });
        const d = dom.window.document;
        const reiter = d.getElementById('settings-tab-jira');
        check('der Jira-Reiter existiert', !!reiter);
        for (const id of ['jvorl-liste', 'jvorl-name', 'jvorl-text', 'jvorl-global',
                          'jvorl-save', 'jvorl-new', 'jvorl-status']) {
            const el = d.getElementById(id);
            check('#' + id + ' liegt IM Jira-Reiter',
                  !!el && !!reiter && reiter.contains(el));
        }
        // Ohne Reiter-Knopf ist der Abschnitt unerreichbar – genau das war die
        // Meldung. Der Knopf blendet sich bei aktivem Skill ein (app.js).
        check('der Reiter hat einen Knopf in der Reiterleiste',
              !!d.querySelector('.settings-tab-btn[data-settings-tab="jira"]'));
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('2) Die Liste wird wirklich geladen und gezeichnet');
    // ══════════════════════════════════════════════════════════════════════
    const state = { calls: [], global: JSON.parse(JSON.stringify(START.global)),
                    eigene: JSON.parse(JSON.stringify(START.eigene)), darfGlobal: true };
    const dom = makeDom(state);
    const w = dom.window, d = w.document;

    check('window.JiraManager existiert', !!w.JiraManager);
    w.JiraManager.onShow();
    await sleep(30);

    const geholt = state.calls.filter((c) => c.method === 'GET'
        && c.url.startsWith('/api/jira/assist/vorlagen'));
    check('onShow() holt die Vorlagen', geholt.length === 1,
          JSON.stringify(state.calls.map((c) => c.method + ' ' + c.url)));
    const texte = zeilenTexte(d);
    check('beide Vorlagen stehen in der Liste', texte.length === 2, String(texte.length));
    check('die gemeinsame ist als solche gekennzeichnet',
          /Kurz für die Leitung/.test(texte[0]) && /Gemeinsam/.test(texte[0]), texte[0]);
    check('die eigene ebenfalls',
          /Mein Blick/.test(texte[1]) && /(Nur für mich|Mine)/.test(texte[1]), texte[1]);
    check('der Anweisungstext ist sichtbar (nicht nur der Name)',
          /Höchstens fünf Sätze/.test(texte[0]));

    // Muelleimer = loeschen. Ein × waere hier die falsche Zusage (Projektregel).
    const muell = d.querySelectorAll('#jvorl-liste .jv-ico-trash');
    check('jede änderbare Zeile trägt einen Mülleimer', muell.length === 2, String(muell.length));
    const listeHtml = d.getElementById('jvorl-liste');
    check('und nirgends ein ×', !!listeHtml && !/[×✕✖]/u.test(listeHtml.innerHTML));

    // ══════════════════════════════════════════════════════════════════════
    section('3) Bearbeiten füllt das Formular, Speichern schickt die Kennung mit');
    // ══════════════════════════════════════════════════════════════════════
    klick(w, d, '#jvorl-liste button', 0, 'Bearbeiten der ersten Zeile');   // ✎
    check('der Name steht im Formular', wert(d, 'jvorl-name') === 'Kurz für die Leitung',
          String(wert(d, 'jvorl-name')));
    check('der Text ebenfalls', wert(d, 'jvorl-text') === 'Höchstens fünf Sätze.');
    check('das Häkchen "für alle" ist gesetzt (es ist eine gemeinsame)',
          !!d.getElementById('jvorl-global') && d.getElementById('jvorl-global').checked === true);

    state.calls.length = 0;
    d.getElementById('jvorl-text').value = 'Höchstens drei Sätze.';
    klick(w, d, '#jvorl-save', 0, 'Speichern');
    await sleep(30);
    const post = state.calls.find((c) => c.method === 'POST');
    check('Speichern schickt einen POST', !!post);
    check('MIT der Kennung – sonst entstünde eine zweite Vorlage',
          !!post && post.body.id === 'g1', post && JSON.stringify(post.body));
    check('und mit global:true', !!post && post.body.global === true);
    check('der geänderte Text kommt an',
          !!post && post.body.text === 'Höchstens drei Sätze.');
    await sleep(30);
    check('die Liste wird danach neu geholt',
          state.calls.filter((c) => c.method === 'GET').length === 1);
    check('das Formular ist danach leer (sonst überschreibt der nächste Klick)',
          wert(d, 'jvorl-name') === '' && wert(d, 'jvorl-text') === '');
    check('und die Liste zeigt den neuen Text',
          /Höchstens drei Sätze/.test(zeilenTexte(d)[0]), zeilenTexte(d)[0]);

    // Ohne Name oder Text darf gar nichts gesendet werden – ein leerer
    // Prompt-Abschnitt in JEDEM Auftrag ist schlimmer als eine Fehlermeldung.
    state.calls.length = 0;
    d.getElementById('jvorl-name').value = '   ';
    d.getElementById('jvorl-text').value = '';
    klick(w, d, '#jvorl-save', 0, 'Speichern (leere Eingabe)');
    await sleep(20);
    check('leere Eingabe wird gar nicht erst gesendet',
          state.calls.length === 0, JSON.stringify(state.calls));
    check('und der Grund steht daneben', /nötig|required/i.test(text(d, 'jvorl-status')),
          text(d, 'jvorl-status'));

    // ══════════════════════════════════════════════════════════════════════
    section('4) Löschen fragt nach und trifft die richtige Vorlage');
    // ══════════════════════════════════════════════════════════════════════
    state.calls.length = 0;
    state.confirmAntwort = false;
    w.confirm = () => false;
    klick(w, d, '#jvorl-liste button', 1, 'Mülleimer der ersten Zeile');
    await sleep(20);
    check('"Abbrechen" löscht NICHTS', state.calls.length === 0,
          JSON.stringify(state.calls));

    w.confirm = () => true;
    klick(w, d, '#jvorl-liste button', 3, 'Mülleimer der zweiten Zeile');
    await sleep(30);
    const del = state.calls.find((c) => c.method === 'DELETE');
    check('bestätigtes Löschen schickt ein DELETE', !!del);
    check('und zwar auf die angeklickte Vorlage',
          !!del && del.url.endsWith('/e1'), del && del.url);
    await sleep(20);
    check('danach steht nur noch eine Zeile da', zeilenTexte(d).length === 1,
          JSON.stringify(zeilenTexte(d)));

    // ══════════════════════════════════════════════════════════════════════
    section('5) Ein Ladefehler bleibt sichtbar – keine leere Liste ohne Grund');
    // ══════════════════════════════════════════════════════════════════════
    state.listFail = true;
    w.JiraManager.loadVorlagen();
    await sleep(30);
    check('der Fehlertext steht in der Liste', /nicht lesbar/.test(text(d, 'jvorl-liste')),
          text(d, 'jvorl-liste').slice(0, 60));
    state.listFail = false;
    w.close();

    // ══════════════════════════════════════════════════════════════════════
    section('6) Ohne Admin-Recht kein Häkchen "für alle"');
    // ══════════════════════════════════════════════════════════════════════
    // Die Schranke selbst sitzt im Backend (jira_vorlagen.speichern) – hier
    // wird sie nur ANGEZEIGT. Ein sichtbares Häkchen, das der Server ablehnt,
    // wäre eine Zusage, die niemand einlöst.
    {
        const st2 = { calls: [], global: JSON.parse(JSON.stringify(START.global)),
                      eigene: [], darfGlobal: false };
        const dom2 = makeDom(st2);
        const w2 = dom2.window, d2 = w2.document;
        w2.JiraManager.onShow();
        await sleep(30);
        const zeile2 = d2.getElementById('jvorl-global-zeile');
        check('die Zeile mit dem Häkchen ist ausgeblendet',
              !!zeile2 && zeile2.style.display === 'none',
              zeile2 ? zeile2.style.display || '(leer)' : 'Zeile fehlt');
        const btns = d2.querySelectorAll('#jvorl-liste button');
        check('eine fremde (gemeinsame) Vorlage hat weder ✎ noch Mülleimer',
              btns.length === 0, String(btns.length));
        check('sie ist trotzdem sichtbar – man soll wissen, was gilt',
              /Kurz für die Leitung/.test(text(d2, 'jvorl-liste')));
        w2.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('7) Übersetzung: jeder Schlüssel hat DE und EN');
    // ══════════════════════════════════════════════════════════════════════
    {
        const I18N = read('frontend/js/i18n.js');
        // Geschnitten wird am CONTAINER, nicht an einem Ueberschriftstext:
        // seit dem Umbau auf zwei Klapp-Container (2026-08-27) steht
        // "Tickets suchen" VOR den Vorlagen – der alte Textanker schnitt den
        // Abschnitt damit komplett weg und der Test meldete 3 statt 8
        // Schluesseln. Eine Id ist die stabilere Grenze.
        const iStart = HTML.indexOf('id="ji-sect-vorl"');
        const abschnitt = iStart < 0 ? ''
            : HTML.slice(iStart, HTML.indexOf('</div>', HTML.indexOf('jvorl-status', iStart)));
        const keys = Array.from(new Set(
            (abschnitt.match(/data-i18n(?:-html|-placeholder)?="([^"]+)"/g) || [])
                .map((m) => m.replace(/.*="([^"]+)"/, '$1'))));
        check('der Abschnitt ist überhaupt übersetzbar', keys.length >= 6,
              String(keys.length));
        const fehlen = keys.filter((k) => (I18N.split("'" + k + "':").length - 1) < 2);
        check('jeder Schlüssel steht in BEIDEN Sprachtabellen', fehlen.length === 0,
              fehlen.join(', '));
        // Die aus dem JS gebauten Texte kommen nicht aus data-i18n – sie
        // brauchen ihre Schlüssel genauso.
        const JS = read('frontend/js/jira.js');
        const jsKeys = Array.from(new Set(
            (JS.match(/t\('(jvorl\.[a-z_]+)'/g) || []).map((m) => m.slice(3, -1))));
        check('auch die im JS erzeugten Texte sind übersetzbar', jsKeys.length >= 6,
              String(jsKeys.length));
        const fehlenJs = jsKeys.filter((k) => (I18N.split("'" + k + "':").length - 1) < 2);
        check('und stehen ebenfalls in beiden Tabellen', fehlenJs.length === 0,
              fehlenJs.join(', '));
    }

    // ══════════════════════════════════════════════════════════════════════
    section('8) Ohne i18n.js bleibt der Reiter benutzbar (deutscher Rückfall)');
    // ══════════════════════════════════════════════════════════════════════
    {
        const st3 = { calls: [], global: [], eigene: [], darfGlobal: true };
        const dom3 = makeDom(st3, { ohneI18n: true });
        const w3 = dom3.window, d3 = w3.document;
        w3.JiraManager.onShow();
        await sleep(30);
        const txt = text(d3, 'jvorl-liste');
        check('kein roher Schlüssel im Text', !/jvorl\./.test(txt), txt);
        check('sondern der deutsche Rückfall', /Noch keine Vorlagen/.test(txt), txt);
        w3.close();
    }

    const bad = results.filter((r) => !r.ok);
    console.log(`\n\x1b[1mErgebnis: ${results.length - bad.length}/${results.length}\x1b[0m`);
    if (bad.length) {
        console.log('\x1b[31mFehlgeschlagen:\x1b[0m');
        bad.forEach((r) => console.log('  - ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
