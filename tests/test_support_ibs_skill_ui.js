/* UI-Waechter: die IBS-Option unter /support folgt dem Skill 'Kundenverwaltung'.
 *
 * Es laeuft die echte Seite mit dem echten support.js (jsdom). jsdom rechnet kein
 * Layout, gemessen wird deshalb die Klasse 'hidden' an der Huelle, das
 * Vorhandensein des Filtereintrags und der tatsaechlich gesendete Anfragerumpf.
 *
 * Lauf:  node tests/test_support_ibs_skill_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ok = 0, fail = 0;

function check(name, cond, detail) {
    if (cond) ok++; else fail++;
    console.log((cond ? '  ✓ ' : '  ✗ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function json(data) {
    return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(JSON.stringify(data)),
    });
}

function seite(status, pref) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'support.html'), 'utf8');
    const rufe = { status: 0, suche: [] };
    const dom = new JSDOM(html, {
        url: 'https://localhost/support',
        runScripts: 'dangerously',
        virtualConsole: new VirtualConsole(),
        beforeParse(win) {
            win.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8'));
            win.localStorage.setItem('jarvis_token', 'testtoken');
            if (pref !== undefined) win.localStorage.setItem('jarvis_support_ibs', pref);
            win.HTMLCanvasElement.prototype.getContext = () => null;
            win.fetch = (url, init) => {
                const u = String(url);
                if (u.startsWith('/api/me')) return json({ username: 'anna', is_admin: false });
                if (u.startsWith('/api/support/status')) { rufe.status++; return json(status); }
                if (u.startsWith('/api/support/query')) {
                    rufe.suche.push(JSON.parse(init.body));
                    return json({ ok: true, blocks: [] });
                }
                return json({ ok: true });
            };
        },
    });
    for (const rel of ['js/icons.js', 'js/i18n.js', 'js/chatlib.js', 'js/support.js']) {
        dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend', rel), 'utf8'));
    }
    return { dom, rufe };
}

async function pruefe(titel, status, pref, erwartet) {
    console.log('\n' + titel);
    const { dom, rufe } = seite(status, pref);
    await sleep(120);
    const dc = dom.window.document;
    const wrap = dc.getElementById('sup-opt-ibs-wrap');
    const box = dc.getElementById('sup-opt-ibs');
    if (!wrap || !box || !dc.getElementById('sup-f-source') || rufe.status < 1) {
        console.log('ABBRUCH: Seite nicht wie erwartet aufgebaut (Status-Abrufe: ' + rufe.status + ')');
        process.exit(2);
    }
    check('Option ' + (erwartet.sichtbar ? 'sichtbar' : 'verschwunden'),
          wrap.classList.contains('hidden') === !erwartet.sichtbar);
    check('Filtereintrag IBS ' + (erwartet.sichtbar ? 'vorhanden' : 'entfernt'),
          !!dc.querySelector('#sup-f-source option[value="IBS"]') === erwartet.sichtbar);
    check('Kaestchen ' + (erwartet.klickbar ? 'klickbar' : 'gesperrt'), box.disabled === !erwartet.klickbar);
    check('Filter behaelt die uebrigen Quellen',
          !!dc.querySelector('#sup-f-source option[value="JIRA"]'));
    if (pref !== undefined) {
        check('gespeicherte Vorbelegung bleibt erhalten',
              dom.window.localStorage.getItem('jarvis_support_ibs') === pref);
    }
    dc.getElementById('sup-input').value = 'Drucker klemmt';
    dc.getElementById('sup-search-btn').click();
    await sleep(80);
    check('die Suche wird wirklich gesendet (Positivkontrolle)', rufe.suche.length === 1,
          'Anzahl: ' + rufe.suche.length);
    check('gesendet wird ibs=' + erwartet.gesendet,
          rufe.suche.length === 1 && rufe.suche[0].ibs === erwartet.gesendet,
          JSON.stringify(rufe.suche[0] || {}));
    dom.window.close();
}

(async () => {
    console.log('Startzustand im Markup');
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'support.html'), 'utf8');
    check('Huelle startet versteckt (kein Aufblitzen)',
          html.includes('id="sup-opt-ibs-wrap" class="hidden"'));

    await pruefe('Skill aus, Zugang hinterlegt, Vorbelegung an',
                 { ibs_active: false, ibs_configured: true }, '1',
                 { sichtbar: false, klickbar: false, gesendet: false });
    await pruefe('Skill an, Zugang hinterlegt, Vorbelegung an',
                 { ibs_active: true, ibs_configured: true }, '1',
                 { sichtbar: true, klickbar: true, gesendet: true });
    await pruefe('Skill an, kein Zugang, Vorbelegung an',
                 { ibs_active: true, ibs_configured: false }, '1',
                 { sichtbar: true, klickbar: false, gesendet: false });
    await pruefe('Skill an, Zugang hinterlegt, keine Vorbelegung (Vorgabe AUS)',
                 { ibs_active: true, ibs_configured: true }, undefined,
                 { sichtbar: true, klickbar: true, gesendet: false });

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
