/* Waechter: Einstellungen → Jira, Schalter "Persoenliche Zugaenge erlauben"
 * (2026-11-05, analog zur SAP-Kachel-Anmeldung).
 *
 * Laeuft in jsdom gegen die ECHTEN Dateien (frontend/settings.html,
 * frontend/js/jira.js) mit gemockter API. Geprueft wird:
 *   - geladener Stand: Haken und Container "Persoenliche Jira-Zugaenge"
 *   - Abschalten fragt nach; Abbrechen speichert NICHTS
 *   - Bestaetigen speichert persoenliche_zugaenge:false und blendet den
 *     Container aus
 *   - Einschalten (oder schon aus) fragt nicht
 *
 * JIRA_JS=<pfad> legt eine sabotierte KOPIE vor (gegen_jira_nur_lesen.py).
 * Aufruf: node tests/test_jira_persoenlich_ui.js
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const JIRA_JS = process.env.JIRA_JS || path.join(ROOT, 'frontend', 'js', 'jira.js');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function reiter(cfg, confirmAntwort) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
    const posts = [], fragen = [];
    const s = new JSDOM(html, {
        url: 'https://localhost/settings', runScripts: 'outside-only',
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.confirm = (t) => { fragen.push(t); return confirmAntwort; };
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const json = (data) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
                if (u === '/api/skills/jira/config') {
                    if (init && init.method === 'POST') { posts.push(JSON.parse(init.body)); return json({ success: true }); }
                    return json({ config: cfg, geheim_gesetzt: ['api_token'] });
                }
                if (u === '/api/jira/admin/accounts') return json({ ok: true, accounts: [], persoenlich_erlaubt: true });
                return json({ ok: true });
            };
        },
    });
    const sitzung = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');
    s.window.eval(sitzung);
    s.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
    s.window.eval(sitzung);
    s.window.eval(fs.readFileSync(JIRA_JS, 'utf8'));
    s.window.JiraManager.onShow();
    await sleep(150);
    return { s, posts, fragen, $: (id) => s.window.document.getElementById(id) };
}

(async () => {
    console.log('\n1. Geladener Stand');
    {
        const e = await reiter({ base_url: 'https://jira.beispiel.de' }, true);
        if (!e.$('jira-persoenlich') || !e.$('ji-sect-acc')) {
            console.log('ABBRUCH: Schalter oder Container fehlt im Markup');
            process.exit(2);
        }
        check(e.$('jira-persoenlich').checked === true, 'Feld fehlt -> Haken gesetzt (erlaubt)');
        check(e.$('ji-sect-acc').style.display !== 'none', 'Container sichtbar');
        e.s.window.close();
    }
    {
        const e = await reiter({ base_url: 'https://jira.beispiel.de', persoenliche_zugaenge: false }, true);
        check(e.$('jira-persoenlich').checked === false, 'abgeschaltet -> Haken leer');
        check(e.$('ji-sect-acc').style.display === 'none', 'abgeschaltet -> Container ausgeblendet');
        e.$('jira-save').click();
        await sleep(60);
        check(e.fragen.length === 0, 'schon aus: Speichern fragt NICHT erneut', String(e.fragen.length));
        check(e.posts.length === 1 && e.posts[0].persoenliche_zugaenge === false,
              '...und speichert den Stand mit', JSON.stringify(e.posts));
        e.s.window.close();
    }

    console.log('\n2. Abschalten mit Rueckfrage');
    {
        const e = await reiter({ base_url: 'https://jira.beispiel.de' }, false);
        e.$('jira-persoenlich').checked = false;
        e.$('jira-save').click();
        await sleep(60);
        check(e.fragen.length === 1 && /gelöscht/.test(e.fragen[0] || ''), 'Abschalten fragt nach (Warnhinweis)',
              String(e.fragen[0]));
        check(e.posts.length === 0, 'Abbrechen speichert nichts', String(e.posts.length));
        check(e.$('ji-sect-acc').style.display !== 'none', 'Abbrechen: Container bleibt');
        e.s.window.close();
    }
    {
        const e = await reiter({ base_url: 'https://jira.beispiel.de' }, true);
        e.$('jira-persoenlich').checked = false;
        e.$('jira-save').click();
        await sleep(80);
        check(e.posts.length === 1 && e.posts[0].persoenliche_zugaenge === false,
              'Bestaetigen speichert persoenliche_zugaenge:false', JSON.stringify(e.posts));
        check(e.$('ji-sect-acc').style.display === 'none', 'danach ist der Container ausgeblendet');
        e.s.window.close();
    }

    console.log('\n3. Einschalten fragt nicht');
    {
        const e = await reiter({ base_url: 'https://jira.beispiel.de', persoenliche_zugaenge: false }, false);
        e.$('jira-persoenlich').checked = true;
        e.$('jira-save').click();
        await sleep(80);
        check(e.fragen.length === 0 && e.posts.length === 1 && e.posts[0].persoenliche_zugaenge === true,
              'Einschalten speichert ohne Rueckfrage', e.fragen.length + ' / ' + JSON.stringify(e.posts));
        check(e.$('ji-sect-acc').style.display !== 'none', 'Container wieder sichtbar');
        e.s.window.close();
    }

    console.log('\n4. Texte in beiden Sprachen');
    {
        const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        const grenze = i18n.search(/\n\s*en\s*:\s*\{/);
        const bl = { de: i18n.slice(0, grenze), en: i18n.slice(grenze) };
        const fehlt = [];
        ['jira.intro', 'jira.read_only', 'jira.read_only_hint', 'jira.persoenlich',
         'jira.persoenlich_hint', 'jira.persoenlich_confirm'].forEach((k) =>
            ['de', 'en'].forEach((lg) => { if (bl[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k); }));
        check(grenze > 0 && fehlt.length === 0, 'Schluessel in DE und EN', fehlt.join(', '));
    }

    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
