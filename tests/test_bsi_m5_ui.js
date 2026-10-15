/* UI-Waechter BSI M5: Geheimnisse erst nach erneuter Anmeldung, Formulare maskiert.
 *
 * Was gemessen wird (AUSGEFUEHRT in jsdom, nicht am Quelltext):
 *   1. pwreveal.js: verlangt der Server eine Bestaetigung (403 + reauth), kommt
 *      der Dialog; nach dem Kennwort wird der Abruf wiederholt und der Wert
 *      steht im Feld.
 *   2. Falsches Kennwort: Fehler bleibt im Dialog stehen, nichts im Feld.
 *   3. Abbrechen (Knopf und Escape): Dialog weg, Feld wieder verborgen und leer.
 *   4. Zwei Augen kurz hintereinander: EIN Dialog, nicht zwei.
 *   5. skillcfg.js: ein Geheimfeld kommt LEER, traegt Quelle/Kennung fuer das
 *      Auge, zeigt Sterne nur, wenn etwas gespeichert ist; Speichern ohne
 *      Aufdecken schickt "" (= unveraendert, Server).
 *   6. REGEL ueber die handgebauten Reiter (acorn): kein Geheimfeld wird mehr
 *      aus der Konfiguration ins Feld geschrieben.
 *
 * Lauf:  timeout 120 node tests/test_bsi_m5_ui.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
const acorn = require('./lib/acorn_laden')();

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let BILANZ = false;
const WACHHUND = setTimeout(() => {
    console.log('❌ ABBRUCH: Lauf haengt (Wachhund 90 s)');
    process.exit(2);
}, 90000);
process.on('exit', (c) => {
    if (!BILANZ && c === 0) {
        console.log('❌ ABBRUCH: keine Bilanzzeile – der Lauf ist nicht durchgelaufen');
        process.exitCode = 2;
    }
});

function check(name, cond, detail) {
    results.push({ name, ok: !!cond });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function lies(rel) { return fs.readFileSync(path.join(ROOT, rel), 'utf8'); }

function baue(html) {
    const dom = new JSDOM(html, { url: 'https://localhost/x', runScripts: 'outside-only',
                                  virtualConsole: new VirtualConsole() });
    const w = dom.window;
    /* Das ECHTE sitzung.js statt `{ token: () => … }`. Eine Attrappe bietet
       WENIGER als das Original und prueft damit die eigene Annahme - genau
       daran sind am 2026-10-05 acht Waechter still gestorben (Begruendung in
       lib/sitzung_laden.js). Der Helfer WIRFT, wenn danach kein benutzbares
       window.JarvisSitzung steht. */
    sitzungLaden(w, { token: 'TOK' });
    w.eval(lies('frontend/js/icons.js'));
    w.eval(lies('frontend/js/pwreveal.js'));
    return dom;
}
function auge(inp) {
    const p = inp && inp.parentElement;
    if (!p) return null;
    for (let k = p.firstElementChild; k; k = k.nextElementSibling) {
        if (k.classList && k.classList.contains('jv-pw-eye')) return k;
    }
    return null;
}
function antwort(status, d) {
    return Promise.resolve({ ok: status >= 200 && status < 300, status,
                             json: () => Promise.resolve(d) });
}

/* Server-Attrappe: reveal verlangt eine Bestaetigung, bis /api/auth/bestaetigen
 * mit dem richtigen Kennwort gerufen wurde. Form der Antworten wie in main.py. */
function server(w, opts) {
    const st = { frisch: false, rufe: [], kennwort: 'Richtig!1' };
    w.fetch = (url, init) => {
        const u = String(url).split('?')[0];
        const methode = (init && init.method) || 'GET';
        const body = init && init.body ? JSON.parse(init.body) : null;
        st.rufe.push({ u, methode, body });
        if (u === '/api/auth/bestaetigen' && methode === 'GET') {
            return antwort(200, { ok: true, restzeit_s: 0, fenster_s: 300,
                                  code_moeglich: !!(opts && opts.code) });
        }
        if (u === '/api/auth/bestaetigen') {
            if (body && body.password === st.kennwort) { st.frisch = true; return antwort(200, { ok: true }); }
            return antwort(403, { ok: false, error: 'Kennwort falsch.' });
        }
        if (u === '/api/secret/reveal') {
            if (!st.frisch) return antwort(403, { ok: false, reauth: true, error: 'bestaetigen' });
            return antwort(200, { ok: true, wert: 'Klar:' + body.bereich + ':' + body.kennung });
        }
        if (opts && opts.weiter) return opts.weiter(u, methode, body);
        return antwort(404, {});
    };
    return st;
}

(async () => {

section('1. Bestaetigung verlangt → Dialog → Kennwort → Wert im Feld');
{
    const dom = baue(`<!doctype html><html><body>
        <div><input type="password" id="f" data-pw-quelle="skill" data-pw-kennung="jira:api_token"
                    data-pw-gesetzt="1"></div></body></html>`);
    await sleep(20);
    const w = dom.window, dc = w.document;
    const st = server(w);
    const inp = dc.getElementById('f');
    auge(inp).click();
    await sleep(40);
    const dlg = dc.querySelector('.jv-reauth');
    check('Positivkontrolle: der erste Abruf ging an /api/secret/reveal',
          st.rufe.some((r) => r.u === '/api/secret/reveal'), JSON.stringify(st.rufe));
    check('⚠ der Bestaetigungsdialog erscheint', !!dlg);
    if (!dlg) { console.log('ABBRUCH: ohne Dialog sind die Folgepruefungen sinnlos'); process.exit(2); }
    check('… als modaler Dialog (role=dialog, aria-modal)',
          dlg.getAttribute('role') === 'dialog' && dlg.getAttribute('aria-modal') === 'true');
    const pw = dlg.querySelector('input[type="password"]');
    check('… mit Kennwortfeld (autocomplete=current-password)',
          !!pw && pw.getAttribute('autocomplete') === 'current-password');
    check('… ohne Code-Feld, wenn keine 2FA eingerichtet ist',
          !dlg.querySelector('input[autocomplete="one-time-code"]'));
    check('… Feld noch leer, solange nicht bestaetigt', inp.value === '', inp.value);
    pw.value = 'Richtig!1';
    dlg.querySelector('form').dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true }));
    await sleep(80);
    check('⚠ das Kennwort ging an POST /api/auth/bestaetigen',
          st.rufe.some((r) => r.u === '/api/auth/bestaetigen' && r.methode === 'POST'
                              && r.body && r.body.password === 'Richtig!1'));
    check('⚠ danach steht der gespeicherte Wert im Feld',
          inp.value === 'Klar:skill:jira:api_token', inp.value);
    check('… das Feld ist sichtbar', inp.type === 'text', inp.type);
    check('… und der Dialog ist weg', !dc.querySelector('.jv-reauth'));
    check('reveal wurde genau zweimal gefragt (vorher/nachher)',
          st.rufe.filter((r) => r.u === '/api/secret/reveal').length === 2,
          String(st.rufe.filter((r) => r.u === '/api/secret/reveal').length));
    w.close();
}

section('2. Falsches Kennwort: Fehler bleibt stehen, nichts im Feld');
{
    const dom = baue(`<!doctype html><html><body>
        <div><input type="password" id="f" data-pw-quelle="mail" data-pw-kennung="passwort"></div>
        </body></html>`);
    await sleep(20);
    const w = dom.window, dc = w.document;
    server(w, { code: true });
    const inp = dc.getElementById('f');
    auge(inp).click();
    await sleep(40);
    const dlg = dc.querySelector('.jv-reauth');
    check('mit 2FA: Code-Feld wird angeboten',
          !!dlg && !!dlg.querySelector('input[autocomplete="one-time-code"]'));
    dlg.querySelector('input[type="password"]').value = 'falsch';
    dlg.querySelector('form').dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true }));
    await sleep(80);
    const fehler = dlg.querySelector('.jv-reauth-fehler');
    check('⚠ der Dialog bleibt offen', !!dc.querySelector('.jv-reauth'));
    check('⚠ die Fehlermeldung steht sichtbar darin',
          !!fehler && !fehler.hidden && /falsch/i.test(fehler.textContent), fehler && fehler.textContent);
    check('… das Kennwortfeld ist geleert', dlg.querySelector('input[type="password"]').value === '');
    check('… nichts im Feld der Seite', inp.value === '', inp.value);
    w.close();
}

section('3. Abbrechen: Dialog weg, Feld wieder verborgen');
for (const weg of ['knopf', 'escape']) {
    const dom = baue(`<!doctype html><html><body>
        <div><input type="password" id="f" data-pw-quelle="mount" data-pw-kennung="0"></div>
        </body></html>`);
    await sleep(20);
    const w = dom.window, dc = w.document;
    server(w);
    const inp = dc.getElementById('f');
    auge(inp).click();
    await sleep(40);
    const dlg = dc.querySelector('.jv-reauth');
    if (weg === 'knopf') {
        // ⚠ NICHT "erster button type=button": das ist das Auge, das pwreveal
        // dem Kennwortfeld des Dialogs gibt (so in der ersten Fassung gemessen).
        const k = dlg.querySelector('.jv-reauth-knopf:not(.jv-reauth-haupt)');
        if (!k) { console.log('ABBRUCH: Abbrechen-Knopf nicht gefunden'); process.exit(2); }
        k.click();
    } else {
        dc.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    }
    await sleep(40);
    check('⚠ Abbruch per ' + weg + ': Dialog weg', !dc.querySelector('.jv-reauth'));
    check('⚠ … Feld wieder verborgen (kein "verbergen" ueber nichts)', inp.type === 'password', inp.type);
    check('… und leer', inp.value === '');
    check('… ein zweiter Versuch bleibt moeglich', inp.dataset.pwGeholt !== '1');
    w.close();
}

section('4. Zwei Augen kurz hintereinander: EIN Dialog');
{
    const dom = baue(`<!doctype html><html><body>
        <div><input type="password" id="a" data-pw-quelle="sap" data-pw-kennung="password"></div>
        <div><input type="password" id="b" data-pw-quelle="sap" data-pw-kennung="hana_password"></div>
        </body></html>`);
    await sleep(20);
    const w = dom.window, dc = w.document;
    server(w);
    auge(dc.getElementById('a')).click();
    auge(dc.getElementById('b')).click();
    await sleep(60);
    check('⚠ es steht genau EIN Dialog da', dc.querySelectorAll('.jv-reauth').length === 1,
          String(dc.querySelectorAll('.jv-reauth').length));
    const dlg = dc.querySelector('.jv-reauth');
    dlg.querySelector('input[type="password"]').value = 'Richtig!1';
    dlg.querySelector('form').dispatchEvent(new w.Event('submit', { cancelable: true, bubbles: true }));
    await sleep(100);
    check('⚠ nach EINER Bestaetigung stehen beide Werte da',
          dc.getElementById('a').value === 'Klar:sap:password'
          && dc.getElementById('b').value === 'Klar:sap:hana_password',
          dc.getElementById('a').value + ' / ' + dc.getElementById('b').value);
    w.close();
}

section('5. skillcfg.js: Geheimfeld leer, mit Auge; leer speichern = unveraendert');
{
    const dom = baue(`<!doctype html><html><body><div id="skcfg-telegram"></div></body></html>`);
    const w = dom.window, dc = w.document;
    const gespeichert = [];
    const st = server(w, {
        weiter: (u, methode, body) => {
            if (u === '/api/skills') {
                return antwort(200, { skills: [{ dir_name: 'telegram', enabled: true, config_schema: {
                    bot_token: { type: 'string', label: 'Bot-Token', secret: true },
                    leer_token: { type: 'string', label: 'Leer', secret: true },
                    chat_id: { type: 'string', label: 'Chat' } } }] });
            }
            if (u === '/api/skills/telegram/config' && methode === 'GET') {
                // bot_token MIT Wert, wie ein Server vor M5 ihn schickte: das
                // Formular darf ihn trotzdem nicht ins Feld setzen (sonst haengt
                // die Zusage allein am Server – Gegenprobe "fuellt wieder").
                return antwort(200, { config: { bot_token: 'ALT-SERVER-WERT', leer_token: '',
                                                chat_id: '42' },
                                      geheim_gesetzt: ['bot_token'] });
            }
            if (u === '/api/skills/telegram/config' && methode === 'POST') {
                gespeichert.push(body);
                return antwort(200, { success: true });
            }
            return antwort(404, {});
        },
    });
    w.eval(lies('frontend/js/skillcfg.js'));
    if (!w.SkillCfg || !w.SkillCfg.render) { console.log('ABBRUCH: SkillCfg fehlt'); process.exit(2); }
    await w.SkillCfg.render('telegram');
    await sleep(40);
    const tok = dc.querySelector('[data-key="bot_token"]');
    const leer = dc.querySelector('[data-key="leer_token"]');
    check('Positivkontrolle: das Formular ist gebaut',
          !!tok && !!dc.querySelector('[data-key="chat_id"]') && dc.querySelector('[data-key="chat_id"]').value === '42');
    check('⚠ das Geheimfeld ist LEER', !!tok && tok.value === '', tok && tok.value);
    check('… ist ein Kennwortfeld', tok && tok.type === 'password');
    check('⚠ … mit Quelle und Kennung fuer das Auge',
          tok && tok.dataset.pwQuelle === 'skill' && tok.dataset.pwKennung === 'telegram:bot_token',
          tok && JSON.stringify(tok.dataset));
    check('… Sterne, weil etwas gespeichert ist', tok && /^•+$/.test(tok.placeholder), tok && tok.placeholder);
    check('… ein NICHT gesetztes Geheimfeld zeigt keine Sterne',
          leer && !/•/.test(leer.placeholder || ''), leer && leer.placeholder);
    check('⚠ es hat GENAU EIN Auge (das zentrale, kein eigenes daneben)',
          tok && tok.parentElement.querySelectorAll('.jv-pw-eye').length === 1
          && !dc.querySelector('.skcfg-eye'));

    dc.querySelector('.skcfg-save').click();
    await sleep(60);
    check('⚠ Speichern ohne Aufdecken schickt "" (= unveraendert, Server)',
          gespeichert.length === 1 && gespeichert[0].bot_token === '' && gespeichert[0].chat_id === '42',
          JSON.stringify(gespeichert));
    check('… und hat KEINEN Klartext abgerufen',
          !st.rufe.some((r) => r.u === '/api/secret/reveal'));
    w.close();
}

section('6. REGEL: kein Reiter schreibt ein Geheimfeld aus der Konfiguration ins Feld');
{
    const GEHEIM = new Set(['api_token', 'password', 'bearer_token', 'hana_password',
                            'rfc_password', 'ibs_api_key', 'bot_token', 'client_secret']);
    const DATEIEN = ['frontend/js/sap.js', 'frontend/js/vemas.js', 'frontend/js/jira.js',
                     'frontend/js/confluence.js', 'frontend/js/kundenverwaltung.js',
                     'frontend/js/skillcfg.js'];
    let zuweisungen = 0;
    const funde = [];
    const geheimFeldRufe = {};
    for (const rel of DATEIEN) {
        const ast = acorn.parse(lies(rel), { ecmaVersion: 'latest', sourceType: 'script' });
        geheimFeldRufe[rel] = 0;
        (function geh(n) {
            if (!n || typeof n.type !== 'string') return;
            if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression'
                && n.left.property && n.left.property.name === 'value') {
                zuweisungen++;
                // rechte Seite: c.<geheim> (auch in `c.x || ''`)
                (function rechts(r) {
                    if (!r) return;
                    if (r.type === 'MemberExpression' && r.property && GEHEIM.has(r.property.name)) {
                        funde.push(rel + ':' + r.property.name);
                    }
                    if (r.type === 'LogicalExpression' || r.type === 'BinaryExpression') {
                        rechts(r.left); rechts(r.right);
                    }
                })(n.right);
            }
            if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
                && n.callee.name === 'geheimFeld') geheimFeldRufe[rel]++;
            for (const k of Object.keys(n)) {
                const v = n[k];
                if (Array.isArray(v)) v.forEach(geh);
                else if (v && typeof v.type === 'string') geh(v);
            }
        })(ast);
    }
    check('Positivkontrolle: die Regel sieht Feld-Zuweisungen', zuweisungen >= 30, String(zuweisungen));
    check('⚠ keine Zuweisung `.value = c.<Geheimfeld>` mehr', funde.length === 0, funde.join(', '));
    for (const [rel, n] of [['frontend/js/sap.js', 4], ['frontend/js/vemas.js', 2],
                            ['frontend/js/jira.js', 1], ['frontend/js/confluence.js', 1],
                            ['frontend/js/kundenverwaltung.js', 1]]) {
        check(rel + ': ' + n + ' Geheimfeld(er) ueber geheimFeld()', geheimFeldRufe[rel] === n,
              String(geheimFeldRufe[rel]));
    }
    const app = lies('frontend/js/app.js');
    check('⚠ app.js holt den Profil-Key nicht mehr beim Oeffnen des Formulars',
          !/fetch\(`\/api\/profiles\/\$\{id\}\/key`/.test(app));
    check('⚠ app.js holt den Agent-Key nicht mehr beim Laden der Einstellungen',
          !/fetch\('\/api\/settings\/agentkey'/.test(app));
}

section('7. Server lehnt ab (neue Adresse, Geheimnis leer): kein "Gespeichert"');
/* Code-Review 2026-10-07: der Server verweigert seitdem das Speichern einer
   neuen Adresse mit "unveraendertem" Kennwort (400, code geheimnis_neu_eingeben).
   Die Reiter werteten die Antwort aber gar nicht aus – `r.json()` und dann
   "✓ Gespeichert", egal was kam. Gemessen: ECHTES Modul, ECHTES i18n.js,
   Server-Attrappe in der Form von main.py. */
{
    const MODULE = [['frontend/js/confluence.js', 'ConfluenceManager', 'cf-status'],
                    ['frontend/js/jira.js', 'JiraManager', 'jira-status'],
                    ['frontend/js/kundenverwaltung.js', 'KundenverwaltungManager', 'kv-status'],
                    ['frontend/js/vemas.js', 'VemasManager', 'vemas-status'],
                    ['frontend/js/sap.js', 'SapManager', 'sap-status']];
    for (const [rel, glob, sid] of MODULE) {
        for (const ablehnen of [true, false]) {
            const dom = baue(`<!doctype html><html><body><div id="${sid}"></div></body></html>`);
            const w = dom.window;
            w.eval(lies('frontend/js/i18n.js'));
            server(w, { weiter: (u, methode) => {
                if (/^\/api\/skills\/[a-z]+\/config$/.test(u) && methode === 'POST') {
                    return ablehnen
                        ? antwort(400, { success: false, code: 'geheimnis_neu_eingeben', error: 'x' })
                        : antwort(200, { success: true });
                }
                return antwort(200, {});
            } });
            w.eval(lies(rel));
            if (!w[glob] || typeof w[glob].save !== 'function') {
                console.log('ABBRUCH: ' + glob + '.save fehlt'); process.exit(2);
            }
            w[glob].save();
            await sleep(60);
            const txt = w.document.getElementById(sid).textContent;
            if (ablehnen) {
                check('⚠ ' + rel + ': Ablehnung → Hinweis "neu eingeben", kein ✓',
                      txt.indexOf(w.t('common.secret_reenter')) >= 0 && txt.indexOf('✓') === -1, txt);
            } else {
                check('Positivkontrolle ' + rel + ': Erfolg → ✓', txt.indexOf('✓') === 0, txt);
            }
            w.close();
        }
    }
    // skillcfg.js (generische Reiter) mit derselben Ablehnung
    const dom = baue(`<!doctype html><html><body><div id="skcfg-telegram"></div></body></html>`);
    const w = dom.window;
    w.eval(lies('frontend/js/i18n.js'));
    server(w, { weiter: (u, methode) => {
        if (u === '/api/skills') {
            return antwort(200, { skills: [{ dir_name: 'telegram', enabled: true, config_schema: {
                bot_token: { type: 'string', label: 'Bot-Token', secret: true },
                api_url: { type: 'string', label: 'Adresse' } } }] });
        }
        if (u === '/api/skills/telegram/config' && methode === 'GET') {
            return antwort(200, { config: { api_url: 'https://a' }, geheim_gesetzt: ['bot_token'] });
        }
        if (u === '/api/skills/telegram/config') {
            return antwort(400, { success: false, code: 'geheimnis_neu_eingeben', error: 'x' });
        }
        return antwort(404, {});
    } });
    w.eval(lies('frontend/js/skillcfg.js'));
    await w.SkillCfg.render('telegram');
    await sleep(40);
    const knopf = w.document.querySelector('.skcfg-save');
    check('Positivkontrolle: skillcfg-Formular gebaut', !!knopf);
    if (knopf) knopf.click();
    await sleep(60);
    const txt = w.document.getElementById('skcfg-telegram').textContent;
    check('⚠ skillcfg.js: Ablehnung → Hinweis "neu eingeben"',
          txt.indexOf(w.t('common.secret_reenter')) >= 0, txt.slice(-200));
    w.close();
}

const fails = results.filter((r) => !r.ok).length;
BILANZ = true;
clearTimeout(WACHHUND);
console.log(`\nErgebnis: ${results.length - fails} OK, ${fails} FAIL`);
process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
