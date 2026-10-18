#!/usr/bin/env node
/* Waechter (Code-Review 2026-10-18, /settings): Inhalte als Wert, nicht als
 * Markup – und die auffaelligen fest deutschen Texte uebersetzt.
 *
 * Gemessen am ECHTEN settings.html + app.js (mit sitzung.js, icons.js,
 * i18n.js, theme.js) in jsdom, fetch als Attrappe, Sprache Englisch:
 *   1. Reiter "Anweisungen": der Dateiinhalt steht 1:1 im Textfeld (`value`),
 *      ein `</textarea>` darin schleust kein Markup ein, Entitaeten wie
 *      `&amp;` bleiben unveraendert; der Dateiname erscheint als Text.
 *      Speichern schickt genau diesen Inhalt zurueck.
 *   2. SSL-Zeile (Let's Encrypt): Domain als Text, Satz uebersetzt.
 *   3. Agent-API-Schluessel: Knopf-Titel uebersetzt, "Neu generieren" mit
 *      Symbol aus icons.js statt Emoji.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 * Lauf:  timeout 60 node tests/test_app_anweisungen_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/settings.html');
const SITZUNG = lies('frontend/js/sitzung.js');
const MODULE = ['frontend/js/icons.js', 'frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js'];

let OK = 0, FAIL = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) OK++; else FAIL++;
    console.log((cond ? '  ✓ ' : '  ✗ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const INHALT_BOESE = 'Regel A\n</textarea><img id="instrboese" src="x">\nEnde';
const INHALT_ENTITAET = 'Zeichen: &amp; &lt;b&gt; bleiben so';
const NAME_BOESE = 'x<i id="nameboese">n</i>';
const DOMAIN = 'jarvis.beispiel.de<i id="sslboese">d</i>';

let calls = [];
function j(obj) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(obj), text: () => Promise.resolve(JSON.stringify(obj)) });
}
function appFetch(url, opts) {
    const u = String(url).split('?')[0];
    const method = (opts && opts.method) || 'GET';
    calls.push({ url: u, method, body: opts && opts.body });
    if (u === '/api/instructions') return j({ files: [
        { name: 'boese', content: INHALT_BOESE },
        { name: 'entitaet', content: INHALT_ENTITAET },
        { name: NAME_BOESE, content: 'kurz' },
    ] });
    if (u.startsWith('/api/instructions/')) return j({ ok: true });
    if (u === '/api/settings/ssl') return j({ is_letsencrypt: true, domain: DOMAIN, expiry: '2027-01-01' });
    if (u.startsWith('/api/agent/keys')) return j({ keys: [{ id: 'k1', name: 'probe', key_gesetzt: true, key_ende: 'abcd' }] });
    if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
    if (u.startsWith('/api/settings')) return j({ docs_retention_days: 30 });
    if (u.startsWith('/api/me')) return j({ username: 'jarvis', is_admin: true, permissions: {} });
    if (u.startsWith('/api/skills')) return j({ skills: [] });
    if (u.startsWith('/api/branding')) return j({ enabled: false });
    return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
}

async function main() {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.localStorage.setItem('jarvis_user', 'jarvis');
    w.localStorage.setItem('jarvis_lang', 'en');
    // API-Abschnitt gemerkt aufgeklappt -> Schluessel laden ohne Klick
    w.localStorage.setItem('jarvis_sect_collapse_prof-sect-api-hdr', '0');
    w.confirm = () => true;
    w.alert = () => {};
    w.scrollTo = () => {};
    w.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    w.fetch = appFetch;
    for (const f of MODULE) {
        w.eval(SITZUNG);
        try { w.eval(lies(f)); } catch (e) { console.log('    (Modul ' + f + ': ' + e.message + ')'); }
    }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await sleep(30);
    const d = w.document;

    section('1) Positivkontrolle: Messaufbau');
    check('Modal-Oeffner erreichbar', typeof w._openSettingsModal === 'function');
    check('Sprache ist Englisch', w._lang === 'en' && w.t('common.delete') === 'Delete', w._lang);
    if (FAIL) { bilanz(); w.close(); process.exit(2); }
    await w._openSettingsModal();
    await sleep(120);
    const tabBtn = d.querySelector('.settings-tab-btn[data-settings-tab="instructions"]');
    check('Reiter "Anweisungen" vorhanden', !!tabBtn);
    if (tabBtn) tabBtn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(80);
    const editoren = [...d.querySelectorAll('#instr-list .instr-editor')];
    check('drei Anweisungs-Karten mit Textfeld gezeichnet', editoren.length === 3, String(editoren.length));
    if (editoren.length !== 3) { bilanz(); w.close(); process.exit(2); }

    section('2) Anweisungen: Inhalt als Wert');
    check('kein eingeschleustes Element aus dem Inhalt', !d.getElementById('instrboese'));
    check('der Inhalt mit </textarea> steht 1:1 im Feld', editoren[0].value === INHALT_BOESE, JSON.stringify(editoren[0].value));
    check('Entitaeten bleiben unveraendert (&amp; wird nicht zu &)', editoren[1].value === INHALT_ENTITAET, JSON.stringify(editoren[1].value));
    check('kein eingeschleustes Element aus dem Dateinamen', !d.getElementById('nameboese'));
    const namen = [...d.querySelectorAll('#instr-list .instr-name')].map((e) => e.textContent);
    check('der Dateiname steht als Text da', namen[2] === NAME_BOESE + '.md', JSON.stringify(namen));
    // Speichern der ersten Karte schickt exakt den Inhalt zurueck
    calls = [];
    const save = d.querySelectorAll('#instr-list .btn-instr-save')[0];
    // VOR dem Klick lesen: der Klick setzt style.background, danach liefert jsdom
    // die Deklaration normiert (rgb(...)) zurueck.
    check('der Speichern-Knopf hat keine feste Schriftfarbe mehr',
        !/#fff\b|rgb\(255,\s*255,\s*255\)/i.test(save.getAttribute('style') || ''), save.getAttribute('style'));
    save.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    const post = calls.find((c) => c.method === 'POST' && c.url.startsWith('/api/instructions/'));
    let gesendet = null;
    try { gesendet = post ? JSON.parse(post.body).content : null; } catch (e) { gesendet = null; }
    check('Speichern schickt den unveraenderten Inhalt', gesendet === INHALT_BOESE, JSON.stringify(gesendet));
    check('Speichern geht an die Datei der eigenen Karte', !!post && post.url === '/api/instructions/boese', post ? post.url : '—');
    const save3 = d.querySelectorAll('#instr-list .btn-instr-save')[2];
    calls = [];
    save3.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    const post3 = calls.find((c) => c.method === 'POST');
    check('auch ein Name mit Sonderzeichen findet sein Feld (kein Wurf im Selektor)',
        !!post3 && post3.url === '/api/instructions/' + encodeURIComponent(NAME_BOESE), post3 ? post3.url : 'kein POST');

    section('3) SSL-Zeile');
    const ssl = d.getElementById('ssl-status-text');
    check('kein eingeschleustes Element aus der Domain', !d.getElementById('sslboese'));
    check('die Domain steht als Text da', !!ssl && ssl.textContent.indexOf(DOMAIN) >= 0, ssl ? ssl.textContent : '—');
    check('der Satz ist uebersetzt (EN: "valid until")', !!ssl && /valid until 2027-01-01/.test(ssl.textContent), ssl ? ssl.textContent : '—');

    section('4) Agent-API-Schluessel');
    const zeile = d.querySelector('#agent-keys-list [data-id="k1"]');
    check('Schluesselzeile gezeichnet', !!zeile);
    if (zeile) {
        const t = (sel) => (zeile.querySelector(sel) || { getAttribute: () => null }).getAttribute('title');
        check('Titel "Anzeigen" uebersetzt', t('.ak-show') === w.t('app.key_show') && t('.ak-show') !== 'Anzeigen/Verbergen', t('.ak-show'));
        check('Titel "Kopieren" uebersetzt', t('.ak-copy') === 'Copy', t('.ak-copy'));
        check('Titel "Neu generieren" uebersetzt', t('.ak-regen') === w.t('app.key_regen') && t('.ak-regen') !== 'Neu generieren', t('.ak-regen'));
        check('Titel "Loeschen" uebersetzt', t('.ak-del') === 'Delete', t('.ak-del'));
        const regen = zeile.querySelector('.ak-regen');
        check('"Neu generieren" zeigt das Symbol aus icons.js', !!regen && !!regen.querySelector('svg.jv-ico-refresh'));
        check('"Neu generieren" traegt kein Emoji', !!regen && !/\p{Extended_Pictographic}/u.test(regen.textContent), regen ? regen.textContent : '');
    }

    bilanz();
    w.close();
    process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
