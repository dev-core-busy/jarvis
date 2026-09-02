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
                           darf_global: state.darfGlobal,
                           standard: state.standard || '',
                           // Fehlt das Feld, antwortet ein aelterer Server –
                           // genau der Fall, den die uebrigen Abschnitte
                           // messen (Block bleibt weg, keine Marke).
                           bereiche: state.bereiche });
            }
            // Die Standard-Route steht VOR der allgemeinen POST-Behandlung –
            // sonst legte sie eine Vorlage namens "undefined" an.
            if (method === 'POST' && u.endsWith('/vorlagen/standard')) {
                state.standard = (body && body.id) || '';
                return j({ ok: true, standard: state.standard });
            }
            if (method === 'POST') {
                // Der Server entscheidet, WOHIN gespeichert wird – hier nur
                // nachgebildet, damit die Liste danach stimmt.
                const ziel = body.global ? state.global : state.eigene;
                const vorhanden = ziel.find((v) => v.id === body.id);
                if (vorhanden) {
                    vorhanden.name = body.name; vorhanden.text = body.text;
                    if (body.bereiche !== undefined) vorhanden.bereiche = body.bereiche;
                } else {
                    ziel.push({ id: 'neu1', name: body.name, text: body.text,
                                bereiche: body.bereiche || [] });
                }
                return j({ ok: true, vorlage: vorhanden || ziel[ziel.length - 1] });
            }
            if (method === 'DELETE') {
                const id = decodeURIComponent(u.split('/').pop());
                state.global = state.global.filter((v) => v.id !== id);
                state.eigene = state.eigene.filter((v) => v.id !== id);
                return j({ ok: true });
            }
        }
        if (u.startsWith('/api/jira/admin/areas')) {
            state.freigabe = (body && body.bereiche) || [];
            (state.bereiche || []).forEach((b) => {
                b.freigegeben = state.freigabe.indexOf(b.id) >= 0;
            });
            return j({ ok: true, bereiche: state.freigabe });
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
/* Einen Knopf IN EINER ZEILE ueber seine Aufgabe finden – nie ueber die
 * Position.
 *
 * ⚠ HIER STAND EINMAL `'#jvorl-liste button'[0]`. Als der Stern der
 * Standard-Vorlage dazukam, zeigten alle Indizes auf den falschen Knopf und
 * ZEHN Pruefungen schlugen fehl, obwohl an der geprueften Sache nichts kaputt
 * war. Ein Test, der die Reihenfolge von Bedienelementen festschreibt, prueft
 * das Layout und behauptet, die Funktion zu pruefen.
 *
 * `art`: 'stern' | 'edit' | 'trash'.
 */
function zeilenKnopf(d, zeile, art) {
    const box = d.getElementById('jvorl-liste');
    const row = box && box.children[zeile];
    if (!row) return null;
    for (const b of row.querySelectorAll('button')) {
        if (art === 'trash' && b.querySelector('.jv-ico-trash')) return b;
        if (art === 'edit' && b.textContent.trim() === '✎') return b;
        if (art === 'stern' && /^[★☆]$/u.test(b.textContent.trim())) return b;
    }
    return null;
}

function klickKnopf(w, d, zeile, art, was) {
    const el = zeilenKnopf(d, zeile, art);
    if (!el) { check('Bedienelement vorhanden: ' + was, false, art + ' in Zeile ' + zeile); return false; }
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
    klickKnopf(w, d, 0, 'edit', 'Bearbeiten der ersten Zeile');
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
    section('3b) Das Formular steht DIREKT UNTER dem bearbeiteten Eintrag');
    // ══════════════════════════════════════════════════════════════════════
    /* GEMELDET 2026-08-31: "muss wie ansonsten auch ueberall im Projekt DIREKT
     * UNTERHALB des zu bearbeitenden Eintrags erfolgen und nicht irgendwo am
     * Ende der Seite". Zutreffend – das Formular lag statisch unter der Liste,
     * "Bearbeiten" fuellte nur die Felder. Vier andere Module machen es richtig
     * (agent_roles.js, wissen.js, tracks.js, email_portal.js).
     *
     * Gemessen wird die LAGE im DOM, nicht das Vorhandensein einer Funktion:
     * ein Test, der nur `_platziereVorl` im Quelltext sucht, bleibt gruen,
     * wenn der Aufruf fehlt. */
    {
        const st = { calls: [], global: JSON.parse(JSON.stringify(START.global)),
                     eigene: JSON.parse(JSON.stringify(START.eigene)),
                     darfGlobal: true, standard: '' };
        const dm = makeDom(st);
        const wv = dm.window, dv = wv.document;
        wv.JiraManager.onShow();
        await sleep(30);

        const liste = dv.getElementById('jvorl-liste');
        const form0 = dv.getElementById('jvorl-edit');
        check('das Formular ist da und startet AUSSERHALB der Liste',
              !!form0 && !!liste && !liste.contains(form0));
        check('und es ist versteckt, solange nichts bearbeitet wird',
              !!form0 && form0.style.display === 'none', form0 && form0.style.display);

        // ── Bearbeiten: unter die angeklickte Zeile ──────────────────────
        klickKnopf(wv, dv, 1, 'edit', 'Bearbeiten der ZWEITEN Zeile');
        const f = dv.getElementById('jvorl-edit');
        const karte1 = liste.children[1];
        check('das Formular liegt IN der Karte des bearbeiteten Eintrags',
              !!f && !!karte1 && karte1.contains(f),
              f ? (f.parentNode && f.parentNode.className) : 'kein Formular');
        check('und zwar direkt hinter dessen Zeile (nicht davor)',
              !!karte1 && karte1.children.length === 2
              && karte1.children[0].classList.contains('jvorl-row')
              && karte1.children[1] === f,
              karte1 ? Array.from(karte1.children).map((c) => c.className).join(' | ') : '');
        check('es ist sichtbar', !!f && f.style.display !== 'none');
        check('NICHT in der Karte des anderen Eintrags',
              !liste.children[0].contains(f));
        check('die bearbeitete Karte ist markiert',
              !!karte1 && karte1.classList.contains('is-editing'));
        check('der Titel im Formular nennt den Eintrag',
              /Mein Blick/.test(text(dv, 'jvorl-edit-title')), text(dv, 'jvorl-edit-title'));

        // ── Zweiter Eintrag: das Formular wandert MIT, es gibt nur eines ──
        klickKnopf(wv, dv, 0, 'edit', 'Bearbeiten der ERSTEN Zeile');
        check('es gibt immer nur EIN Formular',
              dv.querySelectorAll('#jvorl-edit, .jvorl-edit-box').length === 1,
              String(dv.querySelectorAll('.jvorl-edit-box').length));
        check('es ist zur ersten Karte gewandert', liste.children[0].contains(f));
        check('und die alte Markierung ist weg',
              !liste.children[1].classList.contains('is-editing'));

        // ── Abbrechen holt es heim ───────────────────────────────────────
        klick(wv, dv, '#jvorl-cancel', 0, 'Abbrechen');
        check('Abbrechen versteckt das Formular', f.style.display === 'none');
        check('und holt es aus der Liste heraus', !liste.contains(f));
        check('keine Karte bleibt markiert',
              !liste.querySelector('.jvorl-card.is-editing'));
        check('die Felder sind leer', wert(dv, 'jvorl-name') === ''
              && wert(dv, 'jvorl-text') === '');

        // ── "Neu" oeffnet am Heimatplatz, nicht mitten in der Liste ──────
        klick(wv, dv, '#jvorl-new', 0, 'Neu');
        check('"Neu" oeffnet das Formular', f.style.display !== 'none');
        check('aber AUSSERHALB der Liste – es gehoert zu keinem Eintrag',
              !liste.contains(f));

        // ── DER Fallstrick: der Neuaufbau der Liste darf es nicht fressen ─
        klickKnopf(wv, dv, 1, 'edit', 'Bearbeiten (fuer den Neuaufbau)');
        check('Vorbedingung: Formular steckt in der Liste', liste.contains(f));
        st.calls.length = 0;
        dv.getElementById('jvorl-name').value = 'Neuer Name';
        dv.getElementById('jvorl-text').value = 'Neuer Text';
        klick(wv, dv, '#jvorl-save', 0, 'Speichern aus der Liste heraus');
        await sleep(60);
        check('das Formular existiert nach dem Neuaufbau noch',
              !!dv.getElementById('jvorl-edit'));
        check('es steht wieder am Heimatplatz',
              !liste.contains(dv.getElementById('jvorl-edit')));
        check('und der Erfolg steht in der Leiste (die nicht mitverschwindet)',
              /Gespeichert|Saved/i.test(text(dv, 'jvorl-status')), text(dv, 'jvorl-status'));
        check('der Status-Span liegt AUSSERHALB des Formulars',
              !!dv.getElementById('jvorl-status')
              && !dv.getElementById('jvorl-edit').contains(dv.getElementById('jvorl-status')));

        /* ⚠ DIESE PRUEFUNG FEHLTE ZUERST – und die Gegenprobe hat es gezeigt:
         * das Heimholen in loadVorlagen() liess sich entfernen, ohne dass ein
         * Test anschlug. Grund: auf dem Speichern-Weg holt closeVorlage() das
         * Formular schon heim, die zweite Schranke war also nie entscheidend.
         *
         * Entscheidend ist sie hier: ein Klick auf den STERN einer anderen
         * Zeile laedt die Liste neu, WAEHREND das Formular in einer Karte
         * steckt. Ohne Heimholen raeumt `innerHTML = ''` es mit ab – und
         * `$('jvorl-edit')` ist danach fuer immer null, der Reiter also tot,
         * bis die Seite neu geladen wird. */
        klickKnopf(wv, dv, 0, 'edit', 'Bearbeiten (fuer den Stern-Klick)');
        check('Vorbedingung: Formular steckt wieder in der Liste', liste.contains(f));
        klickKnopf(wv, dv, 1, 'stern', 'Stern der ANDEREN Zeile');
        await sleep(60);
        check('ein Neuaufbau ohne Schliessen frisst das Formular nicht',
              !!dv.getElementById('jvorl-edit'));
        check('und es steht danach am Heimatplatz',
              !!dv.getElementById('jvorl-edit')
              && !liste.contains(dv.getElementById('jvorl-edit')));

        // Die Karte traegt den Rahmen, die Zeile nur Layout – sonst waere das
        // aufgeklappte Formular eine zweite Box unter der ersten.
        const CSS = read('frontend/css/style.css');
        check('.jvorl-card traegt den Rahmen', /\.jvorl-card\s*\{[^}]*border:\s*1px/.test(CSS));
        check('.jvorl-row bringt keinen eigenen Rahmen mit',
              !/\.jvorl-row\s*\{[^}]*border:\s*1px/.test(CSS));
        check('das eingehaengte Formular verliert Rahmen und Radius',
              /\.jvorl-card\s*>\s*\.jvorl-edit-box\s*\{[^}]*border:\s*none/.test(CSS));
        check('die Textspalte darf schrumpfen (min-width: 0)',
              /\.jvorl-row-main\s*\{[^}]*min-width:\s*0/.test(CSS));
        dm.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('4) Löschen fragt nach und trifft die richtige Vorlage');
    // ══════════════════════════════════════════════════════════════════════
    state.calls.length = 0;
    state.confirmAntwort = false;
    w.confirm = () => false;
    klickKnopf(w, d, 0, 'trash', 'Mülleimer der ersten Zeile');
    await sleep(20);
    check('"Abbrechen" löscht NICHTS', state.calls.length === 0,
          JSON.stringify(state.calls));

    w.confirm = () => true;
    klickKnopf(w, d, 1, 'trash', 'Mülleimer der zweiten Zeile');
    await sleep(30);
    const del = state.calls.find((c) => c.method === 'DELETE');
    check('bestätigtes Löschen schickt ein DELETE', !!del);
    check('und zwar auf die angeklickte Vorlage',
          !!del && del.url.endsWith('/e1'), del && del.url);
    await sleep(20);
    check('danach steht nur noch eine Zeile da', zeilenTexte(d).length === 1,
          JSON.stringify(zeilenTexte(d)));

    // ══════════════════════════════════════════════════════════════════════
    section('4b) Der Stern setzt und löst die persönliche Standard-Vorlage');
    // ══════════════════════════════════════════════════════════════════════
    /* GEMELDET 2026-08-28: "der user muss die Möglichkeit haben eine Vorlage
     * als seine 'Standard' Vorlage zu markieren". Geprüft wird der ganze Weg –
     * Klick, abgeschickter Rumpf, und dass die Liste den Stern danach WIRKLICH
     * anders zeichnet. Ein Test, der nur den Aufruf einfängt, ließe einen
     * Stern durchgehen, der sich nie füllt. */
    {
        const st3 = { calls: [], global: JSON.parse(JSON.stringify(START.global)),
                      eigene: JSON.parse(JSON.stringify(START.eigene)),
                      darfGlobal: true, standard: '' };
        const dom3 = makeDom(st3);
        const w3 = dom3.window, d3 = w3.document;
        w3.JiraManager.onShow();
        await sleep(30);

        const vorher = zeilenKnopf(d3, 0, 'stern');
        check('unmarkiert steht ein hohler Stern', !!vorher && vorher.textContent === '☆',
              vorher && vorher.textContent);
        check('und er sagt, was ein Klick tut', !!vorher && /markieren|mark/i.test(vorher.title),
              vorher && vorher.title);

        st3.calls.length = 0;
        klickKnopf(w3, d3, 0, 'stern', 'Stern der ersten Zeile');
        await sleep(40);
        const setz = st3.calls.find((c) => c.method === 'POST');
        check('der Klick schickt einen POST', !!setz);
        check('auf die Standard-Route', !!setz && /\/vorlagen\/standard$/.test(setz.url),
              setz && setz.url);
        check('mit der Kennung der angeklickten Vorlage',
              !!setz && setz.body && setz.body.id === 'g1',
              setz && JSON.stringify(setz.body));
        check('danach wird die Liste neu geholt (der Server ist die Wahrheit)',
              st3.calls.some((c) => c.method === 'GET'));

        const nachher = zeilenKnopf(d3, 0, 'stern');
        check('der Stern ist danach gefüllt', !!nachher && nachher.textContent === '★',
              nachher && nachher.textContent);
        check('und bietet jetzt das Aufheben an',
              !!nachher && /aufheben|remove/i.test(nachher.title), nachher && nachher.title);
        check('die andere Zeile bleibt hohl',
              !!zeilenKnopf(d3, 1, 'stern') && zeilenKnopf(d3, 1, 'stern').textContent === '☆');

        // Ein zweiter Klick hebt auf – sonst ließe sich eine einmal gesetzte
        // Vorauswahl nie wieder loswerden.
        st3.calls.length = 0;
        klickKnopf(w3, d3, 0, 'stern', 'Stern erneut');
        await sleep(40);
        const loes = st3.calls.find((c) => c.method === 'POST');
        check('der zweite Klick hebt auf', !!loes && loes.body && loes.body.id === '',
              loes && JSON.stringify(loes.body));
        check('und der Stern ist wieder hohl',
              !!zeilenKnopf(d3, 0, 'stern') && zeilenKnopf(d3, 0, 'stern').textContent === '☆');
        w3.close();
    }

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
        check('eine fremde (gemeinsame) Vorlage hat kein ✎',
              !zeilenKnopf(d2, 0, 'edit'));
        check('und keinen Mülleimer', !zeilenKnopf(d2, 0, 'trash'));
        /* DEN STERN HAT SIE SEHR WOHL. Markiert wird die EIGENE Wahl, nicht
           die Vorlage: wer eine gemeinsame Vorlage nicht ändern darf, darf sie
           trotzdem zu seinem Standard machen. Hinge der Stern an `darf`,
           könnte ein Nicht-Admin ausgerechnet die vorgegebenen Vorlagen nicht
           vorauswählen – also genau die, die er am häufigsten benutzt. */
        check('den Stern trägt sie trotzdem', !!zeilenKnopf(d2, 0, 'stern'));
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
        /* ⚠ HIER STAND EINMAL `HTML.indexOf('</div>', …'jvorl-status'…)`.
         * Der Status-Span wanderte beim Umbau des Formulars (2026-08-31) VOR
         * die Liste – damit endete der Schnitt gleich hinter der Werkzeugleiste
         * und der Test meldete 4 statt 8 Schluesseln, obwohl nichts kaputt war.
         * Dieselbe Falle wie beim Reiter-Schnitt in test_email_ui.js: eine
         * Grenze gehoert an die STRUKTUR, nicht an die Lage eines Elements. */
        const iStart = HTML.indexOf('id="ji-sect-vorl"');
        const abschnitt = iStart < 0 ? '' : (function () {
            // Vom oeffnenden <div> des Abschnitts bis zu seinem </div> zaehlen.
            const von = HTML.lastIndexOf('<div', iStart);
            let tiefe = 0, i = von;
            const re = /<div\b|<\/div>/g;
            re.lastIndex = von;
            let m;
            while ((m = re.exec(HTML))) {
                tiefe += m[0] === '</div>' ? -1 : 1;
                if (tiefe === 0) { i = m.index + m[0].length; break; }
            }
            return HTML.slice(von, i);
        })();
        check('die Schnittgrenze umfasst den ganzen Abschnitt',
              abschnitt.includes('jvorl-liste') && abschnitt.includes('jvorl-save')
              && abschnitt.includes('jvorl-cancel') && !abschnitt.includes('jira-search-q'),
              String(abschnitt.length));
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

    // ══════════════════════════════════════════════════════════════════════
    section('9) Werkzeug-Bereiche: Freigabe (Admin) und Auswahl je Vorlage');
    // ══════════════════════════════════════════════════════════════════════
    /* Zwei Dinge, zwei Container: WAS ein Benutzer waehlen darf (Freigabe) und
     * WAS eine Vorlage benutzt (Auswahl). Gemessen wird geklickt, nicht
     * gelesen – der haeufigste Grund fuer einen toten Knopf ist, dass er nicht
     * verdrahtet ist. */
    {
        const KAT = () => ([
            { id: 'wissen', name: 'Wissensdatenbank (lesend)',
              hinweis: 'Eigene Unterlagen.', freigegeben: true, werkzeuge: ['knowledge_search'] },
            { id: 'fach', name: 'Interne Fachsysteme (lesend)',
              hinweis: 'Nur lesend.', freigegeben: false, werkzeuge: ['jira_search'] },
        ]);
        const st = { calls: [], global: [], darfGlobal: true, bereiche: KAT(),
                     eigene: [{ id: 'e9', name: 'Mit Wissen', text: 'x',
                                bereiche: ['wissen'] }] };
        const dom = makeDom(st);
        const w = dom.window, d = w.document;
        w.JiraManager.onShow();
        await sleep(30);

        // (a) Die Freigabe-Liste zeigt ALLE Bereiche, angehakt nur die freien.
        const frei = Array.from(d.querySelectorAll('#jtool-areas input[data-area]'));
        check('die Freigabe-Liste zeigt jeden Bereich', frei.length === 2,
              String(frei.length));
        check('angehakt ist genau der freigeschaltete',
              frei.filter((c) => c.checked).map((c) => c.dataset.area).join(',') === 'wissen');
        check('und der Hinweis des Servers steht dabei',
              /Eigene Unterlagen/.test(text(d, 'jtool-areas')));

        // (b) Die Marke in der Zeile – GEMESSEN, BEVOR das Formular in die
        // Karte wandert: danach enthaelt der Zeilentext auch dessen Texte.
        check('die Zeile nennt den wirksamen Bereich',
              /Nachschlagen:\s*Wissensdatenbank/.test(zeilenTexte(d)[0] || ''),
              zeilenTexte(d)[0]);

        // (c) Die AUSWAHL je Vorlage zeigt nur FREIGESCHALTETES.
        klickKnopf(w, d, 0, 'edit', 'Vorlage bearbeiten');
        await sleep(10);
        const vber = Array.from(d.querySelectorAll('#jvorl-bereiche input[data-vber]'));
        check('im Formular erscheinen nur freigeschaltete Bereiche',
              vber.map((c) => c.dataset.vber).join(',') === 'wissen',
              vber.map((c) => c.dataset.vber).join(','));
        check('und der Haken der Vorlage steht',
              vber.length === 1 && vber[0].checked);
        const zeile = d.getElementById('jvorl-ber-zeile');
        check('der Block ist sichtbar, weil etwas freigeschaltet ist',
              !!zeile && zeile.style.display !== 'none');

        // (d) Speichern schickt die Bereiche mit – auch abgewaehlt.
        vber[0].checked = false;
        klick(w, d, '#jvorl-save', 0, 'Vorlage speichern');
        await sleep(30);
        const p = st.calls.filter((c) => c.method === 'POST'
            && c.url.indexOf('/api/jira/assist/vorlagen') === 0
            && c.url.indexOf('standard') < 0).pop();
        check('das Speichern schickt bereiche mit', !!p && Array.isArray(p.body.bereiche),
              JSON.stringify(p && p.body));
        // Nie ungeprueft dereferenzieren: fehlt das Feld, WIRFT `.length` – und
        // die Gegenprobe braeche ab statt fehlzuschlagen (Register).
        check('und die LEERE Liste waehlt wirklich ab',
              !!p && Array.isArray(p.body.bereiche) && p.body.bereiche.length === 0);

        // (e) Die Freigabe speichert NUR ihre eigene Teilmenge.
        st.calls.length = 0;
        const kfach = Array.from(d.querySelectorAll('#jtool-areas input[data-area]'))
            .find((c) => c.dataset.area === 'fach');
        if (kfach) kfach.checked = true;
        klick(w, d, '#jtool-save', 0, 'Freigabe speichern');
        await sleep(40);
        const a = st.calls.find((c) => c.url.indexOf('/api/jira/admin/areas') === 0);
        check('der Knopf ruft /api/jira/admin/areas', !!a);
        check('und schickt beide angehakten Bereiche',
              !!a && (a.body.bereiche || []).slice().sort().join(',') === 'fach,wissen',
              JSON.stringify(a && a.body));
        /* DAS IST DER PUNKT: der Server merged die Skill-Config. Ginge hier der
         * ganze Formularstand mit, waere ein leeres Token-Feld ein geloeschter
         * Jira-Zugang (im Projekt bezahlt, siehe Register). */
        check('und KEIN weiteres Feld', !!a && Object.keys(a.body).join(',') === 'bereiche',
              JSON.stringify(a && a.body));
        check('die Konfiguration wird dabei nicht angefasst',
              !st.calls.some((c) => c.method === 'POST'
                  && c.url.indexOf('/api/skills/jira/config') === 0));
        w.close();
    }

    // Gegenprobe: ein aelterer Server ohne Katalog. Dann bleibt der Block weg –
    // und die Vorlagen sind unveraendert benutzbar.
    {
        const st = { calls: [], global: [], eigene: [{ id: 'e1', name: 'A', text: 'b' }],
                     darfGlobal: false };
        const dom = makeDom(st);
        const w = dom.window, d = w.document;
        w.JiraManager.onShow();
        await sleep(30);
        // Zuerst die Zeile – das Formular wandert beim Bearbeiten hinein.
        check('und in der Zeile steht keine Marke',
              !/Nachschlagen:/.test(zeilenTexte(d)[0] || ''), zeilenTexte(d)[0]);
        klickKnopf(w, d, 0, 'edit', 'Vorlage bearbeiten');
        await sleep(10);
        const zeile = d.getElementById('jvorl-ber-zeile');
        check('ohne Katalog bleibt der Bereichs-Block versteckt',
              !!zeile && zeile.style.display === 'none');
        w.close();
    }

    const bad = results.filter((r) => !r.ok);
    console.log(`\n\x1b[1mErgebnis: ${results.length - bad.length}/${results.length}\x1b[0m`);
    if (bad.length) {
        console.log('\x1b[31mFehlgeschlagen:\x1b[0m');
        bad.forEach((r) => console.log('  - ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
