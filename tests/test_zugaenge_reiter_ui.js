/* Waechter: Einstellungen → Vemas, SAP, Jira und Confluence einheitlich
 * (Vorgabe des Betreibers 2026-11-15).
 *
 *   1. AUFBAU, am DOM der ECHTEN settings.html gemessen – in allen vier Reitern:
 *      - die ersten beiden Klapp-Container sind "Verbindung" und
 *        "Persoenliche …-Zugaenge", in dieser Reihenfolge,
 *      - "Verbindung" traegt denselben Titel-Schluessel (jira.sect_conn),
 *      - der Haken "Persoenliche Zugaenge erlauben" liegt IM Container
 *        "Verbindung" und hat in allen vier denselben Text,
 *      - jede .kb-section des Reiters ist in app.js klappbar gebunden (REGEL –
 *        eine gepflegte Liste vergaesse genau den neuen Container).
 *   2. VERHALTEN des Schalters in Confluence, SAP und VEMAS mit den ECHTEN
 *      Modulen (skillcfg.js + Reiter-Skript) gegen eine API-Attrappe:
 *      geladener Stand, Rueckfrage beim Abschalten (Abbrechen speichert
 *      NICHTS), Rumpf, erneutes Speichern fragt nicht.
 *      Confluence: Feld persoenliche_zugaenge, Container folgt dem
 *      GESPEICHERTEN Stand.
 *      SAP/VEMAS (Betreiber 2026-11-15): der Haken IST die umgekehrte
 *      Kachelpflicht – AUS speichert kachel_anmeldung:true, es gibt KEINEN
 *      zweiten Kachel-Haken, der Container folgt wie bei Confluence dem
 *      gespeicherten Stand (AUS = Zugaenge geloescht, Container weg), und die
 *      Kennwortfelder des gemeinsamen Zugangs bleiben frei (seit 2026-11-15
 *      ist er auch dann der Rueckfall, wie bei Jira/Confluence).
 *
 * Aufruf: node tests/test_zugaenge_reiter_ui.js
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

// Die Gegenprobe gibt eine sabotierte KOPIE von frontend/ ueber ZR_ROOT mit.
const ROOT = process.env.ZR_ROOT || path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const REITER = {
    jira:       { sect: 'ji',    save: 'jira-save',  cb: 'jira-persoenlich',  acc: 'Persönliche Jira-Zugänge',       init: '_initJiraCollapse' },
    confluence: { sect: 'cf',    save: 'cf-save',    cb: 'cf-persoenlich',    acc: 'Persönliche Confluence-Zugänge', init: '_initConfluenceCollapse' },
    sap:        { sect: 'sap',   save: 'sap-save',   cb: 'sap-persoenlich',   acc: 'Persönliche SAP-Zugänge',        init: '_initSapCollapse' },
    vemas:      { sect: 'vemas', save: 'vemas-save', cb: 'vemas-persoenlich', acc: 'Persönliche VEMAS-Zugänge',      init: '_initVemasCollapse' },
};

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n1. Aufbau der vier Reiter (DOM der echten settings.html)');
// ═══════════════════════════════════════════════════════════════════════════
const HTML = lies('frontend/settings.html');
const APP = lies('frontend/js/app.js');
{
    const doc = new JSDOM(HTML).window.document;
    const schalterTexte = new Set();
    for (const [name, r] of Object.entries(REITER)) {
        const tab = doc.getElementById('settings-tab-' + name);
        if (!tab) { console.log('ABBRUCH: Reiter ' + name + ' fehlt'); process.exit(2); }
        // Nur DIREKTE Container des Reiters (keine geschachtelten).
        const sects = [...tab.querySelectorAll('.kb-section')];
        const ids = sects.map((s) => s.id);
        check(ids[0] === r.sect + '-sect-conn' && ids[1] === r.sect + '-sect-acc',
              name + ': erst "Verbindung", dann "Persönliche …-Zugänge"', ids.slice(0, 3).join(', '));
        const conn = doc.getElementById(r.sect + '-sect-conn');
        const acc = doc.getElementById(r.sect + '-sect-acc');
        const h3c = conn && conn.querySelector('.kb-collapse-header h3');
        check(!!h3c && h3c.getAttribute('data-i18n') === 'jira.sect_conn'
              && h3c.textContent.trim() === 'Verbindung',
              name + ': Container-Titel "Verbindung" (gleicher Schluessel)');
        const h3a = acc && acc.querySelector('.kb-collapse-header h3');
        check(!!h3a && h3a.textContent.trim() === r.acc, name + ': Titel "' + r.acc + '"',
              h3a ? h3a.textContent : 'fehlt');
        const cb = doc.getElementById(r.cb);
        const body = doc.getElementById(r.sect + '-sect-conn-body');
        check(!!cb && !!body && body.contains(cb),
              name + ': Haken "Speichern persönlicher Zugänge auf Server erlauben" liegt im Container "Verbindung"');
        // Ort wie bei Jira: der Block des Hakens steht DIREKT ueber der Zeile
        // mit "Speichern" (Betreiber 2026-11-15) – gemessen am naechsten
        // Element-Geschwister, nicht an einer Zeilennummer.
        const block = cb && cb.closest('.form-group');
        const naechstes = block && block.nextElementSibling;
        const saveBtn = doc.getElementById(r.save);
        check(!!saveBtn && !!naechstes && naechstes.contains(saveBtn),
              name + ': Haken steht direkt oberhalb von "Speichern"',
              naechstes ? (naechstes.id || naechstes.className || naechstes.tagName) : 'kein Nachfolger');
        check(!!cb && cb.type === 'checkbox' && cb.hasAttribute('checked'),
              name + ': Haken ist im Markup vorbelegt (Vorgabe = erlaubt)');
        const span = cb && cb.closest('label') && cb.closest('label').querySelector('span');
        if (span) schalterTexte.add(span.textContent.trim());
        // REGEL: jede .kb-section des Reiters ist in app.js gebunden.
        const i = APP.indexOf('function ' + r.init + '(');
        const fn = i >= 0 ? APP.slice(i, APP.indexOf('\n        }', i)) : '';
        check(!!fn, name + ': ' + r.init + ' ist definiert');
        const ungebunden = ids.filter((id) => !fn.includes("'" + id + "-hdr'"));
        check(!!fn && ungebunden.length === 0,
              name + ': JEDE .kb-section ist klappbar gebunden', ungebunden.join(', '));
        check(new RegExp(r.init + '\\(\\);').test(APP.slice(APP.indexOf("target === '" + name + "'"))),
              name + ': die Bindung wird beim Oeffnen des Reiters aufgerufen');
    }
    check(schalterTexte.size === 1 && schalterTexte.has('Speichern persönlicher Zugänge auf Server erlauben'),
          'der Schalter heisst in allen vier Reitern gleich', [...schalterTexte].join(' | '));
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. Verhalten
// ═══════════════════════════════════════════════════════════════════════════
// Wie ist "aus" gespeichert, und woran erkennt man es im Rumpf?
const PERS_FELD = { aus: { persoenliche_zugaenge: false },
                    istAus: (b) => b.persoenliche_zugaenge === false,
                    istAn: (b) => b.persoenliche_zugaenge === true, containerFolgt: true };
const KACHEL = { aus: { kachel_anmeldung: true },
                 istAus: (b) => b.kachel_anmeldung === true,
                 istAn: (b) => b.kachel_anmeldung === false, containerFolgt: true };
const MODUL = {
    confluence: Object.assign({ js: 'frontend/js/confluence.js', mgr: 'ConfluenceManager', save: 'cf-save',
                  admin: '/api/confluence/admin/accounts', bereich: 'Confluence' }, PERS_FELD),
    sap:        Object.assign({ js: 'frontend/js/sap.js', mgr: 'SapManager', save: 'sap-save',
                  admin: '/api/sap/admin/accounts', bereich: 'SAP', pw: 'sap-odata-pass' }, KACHEL),
    vemas:      Object.assign({ js: 'frontend/js/vemas.js', mgr: 'VemasManager', save: 'vemas-save',
                  admin: '/api/vemas/admin/accounts', bereich: 'VEMAS', pw: 'vemas-password' }, KACHEL),
};

async function reiter(name, cfg, confirmAntwort, accounts) {
    const m = MODUL[name];
    const posts = [], fragen = [], adminAbrufe = [];
    const s = new JSDOM(HTML, {
        url: 'https://localhost/settings', runScripts: 'outside-only',
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.confirm = (t) => { fragen.push(t); return confirmAntwort; };
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const json = (data) => Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve(data) });
                if (u === '/api/skills/' + name + '/config') {
                    if (init && init.method === 'POST') {
                        posts.push(JSON.parse(init.body));
                        // Wie der Server: danach liefert GET den gespeicherten Stand
                        // (SAP/VEMAS laden nach dem Speichern neu).
                        cfg = Object.assign({}, cfg, posts[posts.length - 1]);
                        return json({ success: true });
                    }
                    return json({ config: cfg, geheim_gesetzt: [] });
                }
                if (u === m.admin) {
                    adminAbrufe.push(u);
                    return json({ ok: true, accounts: accounts || [], persoenlich_erlaubt: true });
                }
                return json({ ok: true });
            };
        },
    });
    global.fetch = s.window.fetch;
    const sitzung = lies('frontend/js/sitzung.js');
    s.window.eval(sitzung);
    s.window.eval(lies('frontend/js/i18n.js'));
    s.window.eval(sitzung);
    s.window.eval(lies('frontend/js/skillcfg.js'));
    s.window.eval(lies(m.js));
    if (!s.window[m.mgr]) { console.log('ABBRUCH: ' + m.mgr + ' fehlt'); process.exit(2); }
    s.window[m.mgr].onShow();
    await sleep(150);
    const $ = (id) => s.window.document.getElementById(id);
    const klick = async (id) => { $(id).click(); await sleep(150); };
    const umschalten = (id, wert) => {
        $(id).checked = wert;
        $(id).dispatchEvent(new s.window.Event('change', { bubbles: true }));
    };
    return { s, posts, fragen, adminAbrufe, $, klick, umschalten };
}

(async () => {
    for (const name of Object.keys(MODUL)) {
        const r = REITER[name], m = MODUL[name];
        const cb = r.cb, acc = r.sect + '-sect-acc';
        // Fehlt ein Element, ist das ein BEFUND (FAIL), kein Absturz: ein
        // abbrechender Lauf ist von "nicht gelaufen" nicht zu unterscheiden.
        {
            const e = await reiter(name, {}, true);
            const da = !!e.$(cb) && !!e.$(acc) && !!e.$(m.save);
            check(da, name + ': Schalter, Container und Speichern-Knopf vorhanden');
            e.s.window.close();
            if (!da) continue;
        }

        console.log('\n2. ' + name + ': geladener Stand');
        {
            const e = await reiter(name, {}, true);
            check(e.$(cb).checked === true, 'Feld fehlt -> Haken gesetzt (erlaubt)');
            check(e.$(acc).style.display !== 'none', 'Container sichtbar');
            check(e.adminAbrufe.length >= 1, 'die Liste der persoenlichen Zugaenge wird geladen');
            e.s.window.close();
        }
        {
            const e = await reiter(name, m.aus, true);
            check(e.$(cb).checked === false, 'gespeichert AUS -> Haken nicht gesetzt');
            if (m.containerFolgt) check(e.$(acc).style.display === 'none', 'Container ausgeblendet');
            else check(e.$(acc).style.display !== 'none',
                       'Container bleibt sichtbar (Zugaenge ohne Kennwort fuer die Kachel-Anmeldung)');
            e.s.window.close();
        }

        console.log('\n3. ' + name + ': Abschalten');
        {
            const e = await reiter(name, {}, false);
            e.umschalten(cb, false);
            check(e.$(acc).style.display !== 'none',
                  'nur abgewaehlt (nicht gespeichert): Container bleibt – es ist nichts geloescht');
            await e.klick(m.save);
            check(e.fragen.length === 1 && e.fragen[0].includes(m.bereich),
                  'Abschalten fragt nach und nennt den Bereich', JSON.stringify(e.fragen));
            check(e.posts.length === 0, 'Abbrechen speichert NICHTS', JSON.stringify(e.posts));
            e.s.window.close();
        }
        {
            const e = await reiter(name, {}, true);
            e.umschalten(cb, false);
            await e.klick(m.save);
            check(e.posts.length === 1 && m.istAus(e.posts[0]),
                  'Bestaetigen speichert ' + JSON.stringify(m.aus), JSON.stringify(e.posts));
            check(e.$(acc).style.display === 'none', 'danach ist der Container ausgeblendet');
            e.s.window.close();
        }
        {
            const e = await reiter(name, m.aus, false);
            e.umschalten(cb, true);
            await e.klick(m.save);
            check(e.fragen.length === 0 && e.posts.length === 1 && m.istAn(e.posts[0]),
                  'Einschalten fragt nicht und speichert true', JSON.stringify(e.posts));
            e.s.window.close();
        }
        {
            const e = await reiter(name, m.aus, false);
            await e.klick(m.save);
            check(e.fragen.length === 0 && e.posts.length === 1,
                  'schon aus: erneutes Speichern fragt nicht', JSON.stringify(e.fragen));
            e.s.window.close();
        }

        if (name === 'sap' || name === 'vemas') {
            console.log('\n4. ' + name + ': EIN Haken statt zwei (Kachel = persoenlich aus)');
            {
                const e = await reiter(name, {}, true);
                check(!e.$(name + '-kachel-pflicht'), 'kein eigener Haken "Anmeldung über die Portal-Kachel fordern"');
                check(!!e.$(m.pw) && e.$(m.pw).disabled === false,
                      'Positivkontrolle: erlaubt -> Kennwortfeld des gemeinsamen Zugangs frei');
                e.umschalten(cb, false);
                check(!!e.$(m.pw) && e.$(m.pw).disabled === false,
                      'Haken entfernt -> Kennwortfeld des gemeinsamen Zugangs bleibt frei (Rueckfall)');
                e.umschalten(cb, true);
                check(!!e.$(m.pw) && e.$(m.pw).disabled === false, 'wieder angehakt -> Kennwortfeld frei');
                e.s.window.close();
            }
            {
                // Altbestand: ein frueher gespeichertes persoenliche_zugaenge:false
                // darf den Haken nicht kippen – massgeblich ist kachel_anmeldung.
                const e = await reiter(name, { persoenliche_zugaenge: false }, true);
                check(e.$(cb).checked === true, 'persoenliche_zugaenge im Bestand wirkt nicht – nur kachel_anmeldung zaehlt');
                e.s.window.close();
            }
        }
    }

    console.log('\n5. ' + 'confluence: Liste der persoenlichen Zugaenge');
    {
        const e = await reiter('confluence', {}, true, [
            { user: 'anna.beispiel', aktiv: true, anzeigename: 'Anna B.', letzter_fehler: '' },
            { user: '<img src=x onerror=alert(1)>', aktiv: true, anzeigename: '', letzter_fehler: 'abgelehnt' },
        ]);
        const box = e.$('cfacc-liste');
        check(!!box && box.textContent.includes('anna.beispiel') && box.textContent.includes('Anna B.'),
              'Benutzer und Confluence-Name stehen in der Liste');
        check(!!box && !box.querySelector('img'), 'Fremdtext wird nicht als Markup eingesetzt');
        check(!!box && box.textContent.includes('abgelehnt'), 'der letzte Fehler wird genannt');
        e.s.window.close();
    }

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
