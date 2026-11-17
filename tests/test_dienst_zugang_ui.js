/* Waechter: eigener Zugang (PAT) fuer Loesungsarchiv und Confluence-Einbindung
 * in den Einstellungen (js/dienst_zugang.js, Betreiber 2026-11-17).
 *
 * Laeuft in jsdom gegen die ECHTEN Dateien (settings.html, sitzung.js,
 * i18n.js, icons.js, pwreveal.js, dienst_zugang.js) mit gemockter API.
 * Geklickt statt gelesen:
 *   - beide Container werden verdrahtet, die Statuszeile nennt den Zugang
 *   - das Feld ist als gespeichertes Geheimnis markiert (Auge, Sterne)
 *   - Speichern sendet NUR den Token an den eigenen Endpunkt, leer nichts
 *   - Muelleimer gesperrt mit Grund, solange kein eigener Token liegt
 *   - Confluence-Container nur bei aktivem Skill
 *   - Verbindungstest nennt, mit welchem Zugang gemessen wurde
 * Aufruf: node tests/test_dienst_zugang_ui.js
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const DZ_JS = process.env.DZ_JS || path.join(ROOT, 'frontend', 'js', 'dienst_zugang.js');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (typeof b === 'string') { console.log('ABBRUCH: check(bedingung, text) vertauscht'); process.exit(2); }
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

function zustand(dienst, quelle, skillAktiv) {
    const skill = dienst === 'loesungsarchiv' ? 'jira' : 'confluence';
    const feld = dienst === 'loesungsarchiv' ? 'loesungsarchiv_api_token' : 'einbindung_api_token';
    return { ok: true, dienst, skill, kennung: skill + ':' + feld, token_gesetzt: quelle === 'dienst',
             adresse_gesetzt: true, sammel_gesetzt: true, quelle, skill_aktiv: skillAktiv };
}

async function seite(opt) {
    const html = lies('frontend/settings.html');
    const aufrufe = [], fragen = [];
    const z = { loesungsarchiv: zustand('loesungsarchiv', opt.larch || 'sammel', true),
                confluence_einbindung: zustand('confluence_einbindung', opt.cfb || 'sammel', opt.cfbAktiv !== false) };
    const s = new JSDOM(html, {
        url: 'https://localhost/settings', runScripts: 'outside-only',
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.confirm = (t) => { fragen.push(t); return opt.confirm !== false; };
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const m = (init && init.method) || 'GET';
                aufrufe.push({ u, m, body: init && init.body });
                const json = (data, status) => Promise.resolve({ ok: (status || 200) < 400, status: status || 200,
                                                                  json: () => Promise.resolve(data) });
                const t = u.match(/^\/api\/dienstzugang\/([a-z_]+)(\/test)?$/);
                if (t) {
                    const d = t[1];
                    if (t[2]) return json({ ok: true, quelle: z[d].quelle, anzeigename: 'Dienstkonto' });
                    if (m === 'POST') { z[d] = zustand(d, 'dienst', z[d].skill_aktiv); return json(z[d]); }
                    if (m === 'DELETE') { z[d] = zustand(d, 'sammel', z[d].skill_aktiv); return json(z[d]); }
                    return json(z[d]);
                }
                return json({ ok: true });
            };
        },
    });
    const w = s.window;
    const sitzung = lies('frontend/js/sitzung.js');
    w.eval(sitzung);
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(sitzung);
    w.eval(lies('frontend/js/icons.js'));
    w.eval(lies('frontend/js/pwreveal.js'));
    w.eval(fs.readFileSync(DZ_JS, 'utf8'));
    // jsdom feuert DOMContentLoaded selbst – NICHT zusaetzlich ausloesen
    // (Register: sonst haengt jeder Zuhoerer doppelt).
    await sleep(200);
    const d = w.document;
    const block = (dienst) => d.querySelector('[data-dienstzugang="' + dienst + '"]');
    return { s, w, d, aufrufe, fragen, block };
}

(async () => {
    console.log('\n1. Verdrahtung und Statuszeile');
    {
        const e = await seite({});
        const la = e.block('loesungsarchiv'), cf = e.block('confluence_einbindung');
        if (!la || !cf) { console.log('ABBRUCH: Container fehlen im Markup'); process.exit(2); }
        const gets = e.aufrufe.filter((a) => a.m === 'GET' && /^\/api\/dienstzugang\//.test(a.u)).map((a) => a.u);
        check(gets.includes('/api/dienstzugang/loesungsarchiv') && gets.includes('/api/dienstzugang/confluence_einbindung'),
              'Positivkontrolle: beide Container haben ihren Zustand geholt', JSON.stringify(gets));
        check(gets.length === 2, 'genau EIN Abruf je Container (keine doppelten Zuhoerer)', String(gets.length));
        check(/gemeinsame Zugang/.test(la.querySelector('.dzg-status').textContent),
              'ohne eigenen Token: Status nennt den gemeinsamen Zugang', la.querySelector('.dzg-status').textContent);
        const inp = la.querySelector('.dzg-token');
        check(inp.type === 'password' && inp.dataset.pwQuelle === 'skill'
              && inp.dataset.pwKennung === 'jira:loesungsarchiv_api_token',
              'Feld ist ein Kennwortfeld mit Auge-Quelle skill:feld', JSON.stringify(inp.dataset));
        check(inp.dataset.pwGesetzt === '0' && inp.value === '', 'ohne Token: nicht als gespeichert markiert, leer');
        const del = la.querySelector('.dzg-del');
        check(del.disabled === true && /kein eigener Token/.test(del.title),
              'Muelleimer ohne Token gesperrt MIT Grund', del.title);
        check(!!del.querySelector('.jv-ico-trash'), 'Muelleimer-Symbol aus icons.js');
        check(e.d.getElementById('kb-sect-cfb-body') && cf.closest('[data-dzg-sektion]').style.display === '',
              'Confluence-Container sichtbar bei aktivem Skill');
        e.s.window.close();
    }
    {
        const e = await seite({ larch: 'dienst', cfbAktiv: false });
        const la = e.block('loesungsarchiv'), cf = e.block('confluence_einbindung');
        check(/eigene Token/.test(la.querySelector('.dzg-status').textContent),
              'mit eigenem Token: Status nennt ihn', la.querySelector('.dzg-status').textContent);
        const inp = la.querySelector('.dzg-token');
        check(inp.dataset.pwGesetzt === '1' && inp.placeholder.length > 0 && inp.value === '',
              'gespeicherter Token: Sterne-Platzhalter, Wert NICHT im Feld', inp.placeholder);
        check(la.querySelector('.dzg-del').disabled === false, 'Muelleimer mit Token frei');
        check(cf.closest('[data-dzg-sektion]').style.display === 'none',
              'Confluence-Container verborgen bei inaktivem Skill');
        e.s.window.close();
    }

    console.log('\n2. Speichern');
    {
        const e = await seite({});
        const la = e.block('loesungsarchiv');
        la.querySelector('.dzg-save').click();
        await sleep(50);
        const posts = () => e.aufrufe.filter((a) => a.m === 'POST' && a.u === '/api/dienstzugang/loesungsarchiv');
        check(posts().length === 0, 'leeres Feld: nichts gesendet');
        const mel = la.querySelector('.dzg-meldung');
        check(!mel.hidden && /Token eingeben/.test(mel.textContent), 'leeres Feld: Meldung am Knopf', mel.textContent);
        la.querySelector('.dzg-token').value = '  ABC_token-123  ';
        la.querySelector('.dzg-save').click();
        await sleep(80);
        check(posts().length === 1, 'Speichern sendet genau EINEN Aufruf', String(posts().length));
        let rumpf = null;
        try { rumpf = JSON.parse(posts()[0].body); } catch (x) { rumpf = null; }
        check(rumpf && Object.keys(rumpf).join() === 'token' && rumpf.token === 'ABC_token-123',
              '⚠ Rumpf traegt NUR den (getrimmten) Token', JSON.stringify(rumpf));
        check(!e.aufrufe.some((a) => a.m === 'POST' && /\/api\/skills\//.test(a.u)),
              '⚠ kein Schreiben ueber die Skill-Config (der Verbindungs-Merge bleibt unberuehrt)');
        check(/eigene Token/.test(la.querySelector('.dzg-status').textContent),
              'danach: Status zeigt den eigenen Token');
        check(la.querySelector('.dzg-token').value === '', 'danach: Feld wieder leer (Wert liegt nur auf dem Server)');
        check(e.aufrufe.filter((a) => /confluence_einbindung/.test(a.u) && a.m === 'POST').length === 0,
              'der andere Container bleibt unberuehrt');
        e.s.window.close();
    }

    console.log('\n3. Entfernen und Verbindungstest');
    {
        const e = await seite({ larch: 'dienst', confirm: false });
        const la = e.block('loesungsarchiv');
        la.querySelector('.dzg-del').click();
        await sleep(50);
        check(e.fragen.length === 1, 'Entfernen fragt nach');
        check(!e.aufrufe.some((a) => a.m === 'DELETE'), 'abgebrochen: nichts entfernt');
        e.s.window.close();
    }
    {
        const e = await seite({ larch: 'dienst' });
        const la = e.block('loesungsarchiv');
        la.querySelector('.dzg-test').click();
        await sleep(60);
        const mel = la.querySelector('.dzg-meldung');
        check(/eigenen Token/.test(mel.textContent) && /Dienstkonto/.test(mel.textContent),
              'Test nennt Zugang und Konto', mel.textContent);
        la.querySelector('.dzg-del').click();
        await sleep(60);
        check(e.aufrufe.some((a) => a.m === 'DELETE' && a.u === '/api/dienstzugang/loesungsarchiv'),
              'bestaetigt: DELETE an den eigenen Endpunkt');
        check(/gemeinsame Zugang/.test(la.querySelector('.dzg-status').textContent), 'danach: gemeinsamer Zugang');
        la.querySelector('.dzg-test').click();
        await sleep(60);
        check(/gemeinsamen Zugang/.test(mel.textContent), 'Test ohne eigenen Token sagt es', mel.textContent);
        e.s.window.close();
    }

    console.log('\n4. Regeln');
    {
        const html = lies('frontend/settings.html');
        const app = lies('frontend/js/app.js');
        const jira = lies('frontend/js/jira.js');
        const i18n = lies('frontend/js/i18n.js');
        const dz = fs.readFileSync(DZ_JS, 'utf8');
        check(/<script src="\/static\/js\/dienst_zugang\.js\?v=\d+"><\/script>/.test(html),
              'settings.html bindet dienst_zugang.js mit Cache-Buster ein');
        check(/hdr: 'kb-sect-cfb-hdr'/.test(app), 'neuer Wissen-Container ist klappbar gebunden (app.js)');
        check(!/dzg-larch-token/.test(jira), 'jira.js liest das Token-Feld nicht (Archiv-Speichern schickt es nicht mit)');
        const schl = new Set();
        (dz.match(/t\('(dzg\.[a-z_]+)'/g) || []).forEach((m) => schl.add(m.slice(3, -1)));
        (html.match(/data-i18n(?:-title)?="(dzg\.[a-z_]+)"/g) || []).forEach((m) => schl.add(m.split('"')[1]));
        check(schl.size >= 15, 'Positivkontrolle: Schluessel gefunden', String(schl.size));
        const fehlt = [...schl].filter((k) => (i18n.split("'" + k + "'").length - 1) !== 2);
        check(fehlt.length === 0, 'jeder dzg-Schluessel genau einmal DE + einmal EN', fehlt.join(', '));
        check(!/#[0-9a-fA-F]{3,6}\b/.test(dz), 'keine harte Farbe im Modul');
        check(!/innerHTML\s*=/.test(dz), 'Modul setzt kein innerHTML (Servertext nur als Text)');
    }

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
