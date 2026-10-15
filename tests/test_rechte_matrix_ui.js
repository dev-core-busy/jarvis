/* Waechter: Berechtigungen zuweisen – alle Bereiche in einem Fenster
 * (frontend/js/rechte_matrix.js, Sicherheit -> Berechtigungen).
 *
 * Gemessen an der ECHTEN settings.html mit den ECHTEN Modulen (i18n, icons,
 * ldap_picker, settings_ad, rechte_matrix) – der Speicherweg ist der von
 * window._adSave, geprueft wird der Koerper von POST /api/settings:
 *   1. Bestand: Zeilen = alle Eintraege der SICHTBAREN Bereiche, Spalten =
 *      sichtbare Unter-Container; ausgeblendete Bereiche bleiben unberuehrt.
 *   2. Kaestchen spiegeln den Bestand; Umschalten zaehlt Aenderungen.
 *   3. Uebernehmen schreibt nur Zu-/Abgaenge, Reihenfolge und Schreibweise
 *      vorhandener Eintraege bleiben, Gruppen-DNs mit Komma bleiben ganz.
 *   4. Neue Benutzer ueber den Verzeichnis-Picker.
 *   5. Speichern scheitert -> Fenster bleibt offen, Fehler bleibt stehen.
 *   6. Fail-closed: Bestand nicht geladen -> kein Speichern.
 *   7. Escape bei offenem Picker schliesst nur den Picker.
 *   8. REGEL: jeder rmx.*-Schluessel des Moduls in DE und EN.
 *   9. Geerbte Berechtigungen: Mitglieder einer berechtigten Gruppe zeigen
 *      einen grauen, gesperrten Haken samt Gruppenname; live beim Umschalten
 *      der Gruppe; Mitglieder ohne eigenen Eintrag auf Wunsch; verschachtelte
 *      Gruppen zaehlen nicht (wie beim Login); ohne
 *      Verzeichnis-Zugang wird "nicht ermittelt" genannt statt "nicht
 *      berechtigt" behauptet. Kein zusaetzlicher direkter Eintrag, wo eine
 *      Gruppe den Bereich gibt.
 *  9f. REGEL: der graue Haken ist per CSS gezeichnet.
 *  10. Sortieren: Name und jeder Bereich, Gruppen bleiben oben, gemerkt.
 *
 *   node tests/test_rechte_matrix_ui.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail !== undefined ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function abbruch(g) { console.log('ABBRUCH: ' + g); process.exit(2); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));
const WACH = setTimeout(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 60000);
process.on('exit', (c) => { if (!BILANZ && c === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 2; } });

const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/ldap_picker.js',
                'frontend/js/settings_ad.js', 'frontend/js/rechte_matrix.js'];
const GRP_IT = 'CN=IT\\, Team,OU=Groups,DC=firma,DC=local';   // Komma im CN, wie im AD maskiert
const GRP_ALLE = 'CN=Alle,OU=Groups,DC=firma,DC=local';
const AD = {
    configured: true, reachable: true, server: 'dc.firma.local', domain: 'firma.local',
    access_mode: 'users_group',
    allowed_users: 'Bob, carla', allowed_group: GRP_ALLE + '\n' + GRP_IT,
    knowledge_editors: 'carla', knowledge_editors_group: '',
    sap_users: 'bob', sap_group: GRP_IT,
    vemas_users: 'vera', vemas_group: '',          // Bereich ausgeblendet
    internet_users: '', internet_group: GRP_ALLE,
    admins: 'admin1', admins_group: ''
};
const json = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                          json: () => Promise.resolve(d) });

async function seite(opt) {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const dom = new JSDOM(lies('frontend/settings.html'), {
        url: 'https://localhost/settings', runScripts: 'outside-only', virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    const posts = [], gm = [];
    w.fetch = (u, o) => {
        const p = String(u).split('?')[0];
        if (p === '/api/auth/ad_status') return opt.adStatus ? opt.adStatus() : json(AD);
        if (p === '/api/settings') { posts.push(JSON.parse(o.body)); return json({}, opt.saveStatus || 200); }
        if (p === '/api/ldap/group_members') { const q = JSON.parse(o.body); gm.push(q); return opt.gm ? opt.gm(q) : json({ members: [] }); }
        if (p === '/api/ldap/users') return json({ users: [
            { sam: 'neu.nutzer', display: 'Neu Nutzer', mail: '' },
            { sam: 'bob', display: 'Bob B', mail: '' }] });
        return json({});
    };
    w.alert = () => {}; w.confirm = () => true;
    sitzungLaden(w, { token: 'TOK' });
    if (opt.vorab) opt.vorab(w);
    // SAP sichtbar schalten (wie app.js bei aktivem Skill), VEMAS bleibt aus
    w.document.getElementById('sec-sub-sap').style.display = '';
    for (const m of MODULE) w.eval(lies(m));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
    await schlaf(80);
    return { w, d: w.document, fehler, posts, gm, $: (id) => w.document.getElementById(id) };
}
function zeilen(s) {
    return [...s.d.querySelectorAll('#rmx-tabwrap tbody tr')].filter(tr => tr.querySelector('.rmx-cb'));
}
function zeile(s, name) {
    return zeilen(s).find(tr => tr.querySelector('.rmx-wert').textContent === name) || null;
}
function spaltenIndex(s, label) {
    const ths = [...s.d.querySelectorAll('#rmx-tabwrap thead th')];
    // Sortierpfeil des aktiven Kopfes gehoert nicht zum Namen
    return ths.findIndex(th => th.textContent.replace(/[\u25B2\u25BC]/g, '') === label) - 1;   // erste Spalte = Name
}
function kaestchen(s, name, label) {
    const tr = zeile(s, name); const i = spaltenIndex(s, label);
    if (!tr || i < 0) return null;
    return tr.querySelectorAll('.rmx-cb')[i] || null;
}
// fehlt das Kaestchen, ergibt jede Eigenschaft undefined -> FAIL statt Absturz
function kz(s, name, label) { return kaestchen(s, name, label) || {}; }
// Geerbt = grauer Haken: gesetzt, gesperrt, Zelle mit Klasse rmx-geerbt.
// Direkt = gesetzt und bedienbar. Wirft nie (fehlendes Kaestchen -> false).
function geerbt(c) { return !!(c && c.checked && c.disabled && c.closest && c.closest('td').classList.contains('rmx-geerbt')); }
// wie ein Browser: ein gesperrtes Kaestchen reagiert nicht auf den Klick
function klick(s, cb) { if (!cb) { check('Kaestchen vorhanden', false, 'fehlt'); return; } if (cb.disabled) return; cb.checked = !cb.checked; cb.dispatchEvent(new s.w.Event('change', { bubbles: true })); }

(async () => {
// ── 1. Bestand ─────────────────────────────────────────────────────────────
section('1. Bestand einlesen: Zeilen, Spalten, ausgeblendete Bereiche');
let s = await seite({});
const t = (k) => s.w.t(k);
if (!s.$('rmx-open')) abbruch('settings.html ohne Knopf #rmx-open');
if (!s.w.RechteMatrix) abbruch('rechte_matrix.js nicht geladen');
check('Positivkontrolle: Bestand geladen (_adGeladen, Feld gefuellt)',
      s.w._adGeladen === true && s.$('ad-allowed-users').value === 'Bob, carla', s.$('ad-allowed-users').value);
s.$('rmx-open').click();
check('Fenster offen (.modal.open, nicht nur display)', s.$('rmx-modal').classList.contains('open'));
// Erwartung aus dem DOM gerechnet, nicht abgetippt: sichtbare Unter-Container
const sichtbar = [...s.d.querySelectorAll('details.sec-sub[data-sub]')]
    .filter(d => d.style.display !== 'none').map(d => d.getAttribute('data-sub'))
    .filter(k => ['login','knowledge','sap','vemas','email','tracks','jiraassist','aimouse','claudesub','excel','internet','admins'].includes(k));
const kopf = [...s.d.querySelectorAll('#rmx-tabwrap thead th')].slice(1, -1).map(th => th.textContent.replace(/[\u25B2\u25BC]/g, ''));
check('Spalten = sichtbare Bereiche', kopf.length === sichtbar.length && sichtbar.length >= 5,
      kopf.join('|') + ' gegen ' + sichtbar.join('|'));
check('VEMAS (ausgeblendet) ist keine Spalte', !kopf.includes(t('rmx.col_vemas')));
check('SAP (eingeblendet) ist Spalte', kopf.includes(t('rmx.col_sap')));
const namen = zeilen(s).map(tr => tr.querySelector('.rmx-wert').textContent);
for (const n of ['Bob', 'carla', 'admin1', 'Alle', 'IT, Team'])
    check('Zeile vorhanden: ' + n, namen.includes(n), namen.join('|'));
check('bob/Bob ist EINE Zeile (Gross-/Kleinschreibung)', namen.filter(n => n.toLowerCase() === 'bob').length === 1, namen.join('|'));
check('vera (nur im ausgeblendeten Bereich) ist keine Zeile', !namen.includes('vera'));
check('Gruppen vor Benutzern', namen.indexOf('Alle') < namen.indexOf('Bob') && namen.indexOf('IT, Team') < namen.indexOf('admin1'));

// ── 2. Kaestchen ───────────────────────────────────────────────────────────
section('2. Kaestchen spiegeln den Bestand');
const L = t('rmx.col_login'), K = t('rmx.col_knowledge'), S = t('rmx.col_sap'), A = t('rmx.col_admins'), I = t('rmx.col_internet');
const erwartet = [['Bob', L, true], ['Bob', S, true], ['Bob', A, false], ['carla', K, true], ['carla', S, false],
                  ['IT, Team', L, true], ['IT, Team', S, true], ['Alle', I, true], ['Alle', S, false], ['admin1', A, true]];
for (const [n, sp, v] of erwartet) {
    const cb = kaestchen(s, n, sp);
    check(`${n} / ${sp} = ${v}`, cb && cb.checked === v, cb ? cb.checked : 'fehlt');
}
check('Uebernehmen ohne Aenderung gesperrt', s.$('rmx-apply').disabled === true);

// ── 3. Uebernehmen ─────────────────────────────────────────────────────────
section('3. Uebernehmen: nur Zu-/Abgaenge, Rest unveraendert');
klick(s, kaestchen(s, 'carla', A));        // carla -> Admin
klick(s, kaestchen(s, 'Bob', L));          // Bob raus aus Anmeldung
klick(s, kaestchen(s, 'IT, Team', S));     // Gruppe raus aus SAP
klick(s, kaestchen(s, 'Alle', K));         // Gruppe -> Wissen
klick(s, kaestchen(s, 'Bob', S));          // Zeile heisst 'Bob', SAP-Feld traegt 'bob'
check('Zaehler zeigt 5 Aenderungen', s.$('rmx-apply').textContent === t('rmx.apply_n').replace('{n}', '5'),
      s.$('rmx-apply').textContent);
check('geaenderte Zelle markiert', kaestchen(s, 'carla', A).closest('td').classList.contains('rmx-geaendert'));
s.$('rmx-apply').click();
// vor dem Neuladen messen: die Attrappe liefert danach wieder den Altbestand
check('Chip-Liste im Abschnitt nachgezogen (carla bei Admins)',
      [...s.$('ad-admins').parentNode.querySelectorAll('.token-label')].some(x => x.textContent === 'carla'));
await schlaf(80);
check('genau ein POST /api/settings', s.posts.length === 1, s.posts.length);
const b = s.posts[0] || {};
check('ad_admins = "admin1, carla"', b.ad_admins === 'admin1, carla', b.ad_admins);
check('ad_allowed_users = "carla"', b.ad_allowed_users === 'carla', b.ad_allowed_users);
check('ad_allowed_group unveraendert (DN mit Komma ganz)', b.ad_allowed_group === GRP_ALLE + '\n' + GRP_IT, JSON.stringify(b.ad_allowed_group));
check('sap_allowed_group leer', b.sap_allowed_group === '', JSON.stringify(b.sap_allowed_group));
check('sap_allowed_users: "bob" entfernt, obwohl die Zeile "Bob" heisst', b.sap_allowed_users === '', b.sap_allowed_users);
check('ad_knowledge_editors_group = Alle-DN', b.ad_knowledge_editors_group === GRP_ALLE, JSON.stringify(b.ad_knowledge_editors_group));
check('vemas_allowed_users unberuehrt', b.vemas_allowed_users === 'vera', b.vemas_allowed_users);
check('ad_internet_group unberuehrt', b.ad_internet_group === GRP_ALLE, b.ad_internet_group);
check('Fenster nach Erfolg zu', !s.$('rmx-modal').classList.contains('open'));

// ── 4. Neue Benutzer ueber den Picker ──────────────────────────────────────
section('4. Neue Benutzer ueber den Verzeichnis-Picker');
s = await seite({});
s.$('rmx-open').click();
s.$('rmx-add-users').click();
await schlaf(80);
check('Picker offen ueber dem Fenster', s.$('ldap-picker-modal') && s.$('ldap-picker-modal').classList.contains('open')
      && +s.$('ldap-picker-modal').style.zIndex > +s.$('rmx-modal').style.zIndex);
const pRow = [...s.d.querySelectorAll('#ldap-picker-list .ldap-row')].find(r => r.getAttribute('data-key') === 'neu.nutzer');
if (!pRow) abbruch('Picker-Liste ohne Treffer – Messaufbau');
const pcb = pRow.querySelector('input'); pcb.checked = true; pcb.dispatchEvent(new s.w.Event('change', { bubbles: true }));
const pbob = [...s.d.querySelectorAll('#ldap-picker-list .ldap-row')].find(r => r.getAttribute('data-key') === 'bob').querySelector('input');
pbob.checked = true; pbob.dispatchEvent(new s.w.Event('change', { bubbles: true }));
s.$('ldap-picker-apply').click();
const nz = zeile(s, 'neu.nutzer');
check('neue Zeile da, als neu markiert', nz && !!nz.querySelector('.rmx-neu'));
check('neue Zeile ohne Haken', nz && [...nz.querySelectorAll('.rmx-cb')].every(c => !c.checked));
check('bob nicht doppelt', zeilen(s).filter(tr => tr.querySelector('.rmx-wert').textContent.toLowerCase() === 'bob').length === 1);
check('noch nichts gespeichert', s.posts.length === 0);
klick(s, kaestchen(s, 'neu.nutzer', L));
s.$('rmx-apply').click();
await schlaf(80);
check('neu.nutzer in ad_allowed_users angehaengt', (s.posts[0] || {}).ad_allowed_users === 'Bob, carla, neu.nutzer',
      (s.posts[0] || {}).ad_allowed_users);

// ── 4b. Loeschen (Muelleimer) ──────────────────────────────────────────────
section('4b. Muelleimer nimmt die Zeile aus der Liste');
s = await seite({});
s.$('rmx-open').click();
await schlaf(40);
check('Positivkontrolle: Bob steht in der Liste, mit Muelleimer-Symbol aus icons.js',
      zeile(s, 'Bob') && !!zeile(s, 'Bob').querySelector('.rmx-row-clear svg'));
if (!zeile(s, 'Bob') || !zeile(s, 'Bob').querySelector('.rmx-row-clear svg')) abbruch('Messaufbau: Bob ohne Muelleimer');
zeile(s, 'Bob').querySelector('.rmx-row-clear svg').dispatchEvent(new s.w.MouseEvent('click', { bubbles: true }));
check('Klick (auch aufs Symbol): Bob ist aus der Liste verschwunden', zeile(s, 'Bob') === null,
      zeilen(s).map(tr => tr.querySelector('.rmx-wert').textContent).join('|'));
check('Zaehler: 2 Aenderungen (Anmeldung + SAP)', s.$('rmx-apply').textContent === t('rmx.apply_n').replace('{n}', '2'),
      s.$('rmx-apply').textContent);
check('noch nichts gespeichert', s.posts.length === 0);
s.$('rmx-cancel').click(); s.$('rmx-open').click(); await schlaf(40);
check('Abbrechen + wieder oeffnen: Bob ist zurueck, Haken wie vorher',
      zeile(s, 'Bob') && kz(s, 'Bob', L).checked === true && kz(s, 'Bob', S).checked === true);
{ const x = zeile(s, 'Bob') && zeile(s, 'Bob').querySelector('.rmx-row-clear'); if (x) x.click(); }
// erneut ueber den Picker gewaehlt -> wieder in der Liste (ohne Haken)
s.$('rmx-add-users').click(); await schlaf(80);
const pb = [...s.d.querySelectorAll('#ldap-picker-list .ldap-row')].find(r => r.getAttribute('data-key') === 'bob');
if (!pb) abbruch('Picker-Liste ohne bob – Messaufbau');
pb.querySelector('input').checked = true; pb.querySelector('input').dispatchEvent(new s.w.Event('change', { bubbles: true }));
s.$('ldap-picker-apply').click();
check('erneut gewaehlt: Bob wieder in der Liste, ohne Haken',
      zeile(s, 'Bob') && [...zeile(s, 'Bob').querySelectorAll('.rmx-cb')].every(c => !c.checked));
// fehlt die Zeile, ist das oben schon ein FAIL – hier nicht abstuerzen
const bobX = zeile(s, 'Bob') && zeile(s, 'Bob').querySelector('.rmx-row-clear');
if (bobX) bobX.click();
s.$('rmx-apply').click();
await schlaf(80);
const b4 = s.posts[0] || {};
check('Uebernehmen: Bob aus ad_allowed_users entfernt', b4.ad_allowed_users === 'carla', b4.ad_allowed_users);
check('Uebernehmen: bob aus sap_allowed_users entfernt (Gross/klein)', b4.sap_allowed_users === '', JSON.stringify(b4.sap_allowed_users));
check('Uebernehmen: uebrige Bereiche unberuehrt', b4.ad_admins === 'admin1' && b4.ad_knowledge_editors === 'carla',
      b4.ad_admins + ' / ' + b4.ad_knowledge_editors);
// alle Zeilen weg -> Leer-Hinweis, nicht "passt nicht zum Filter"
s = await seite({});
s.$('rmx-open').click(); await schlaf(40);
let schutz = 50;
while (s.d.querySelector('#rmx-tabwrap .rmx-row-clear') && schutz--) s.d.querySelector('#rmx-tabwrap .rmx-row-clear').click();
check('alle geloescht: Leer-Hinweis statt Filter-Hinweis', s.$('rmx-tabwrap').textContent.includes(t('rmx.empty')),
      s.$('rmx-tabwrap').textContent.slice(0, 80));

// ── 5. Speichern scheitert ─────────────────────────────────────────────────
section('5. Speichern scheitert: Fenster bleibt, Fehler bleibt');
s = await seite({ saveStatus: 500 });
s.$('rmx-open').click();
klick(s, kaestchen(s, 'carla', A));
s.$('rmx-apply').click();
await schlaf(80);
check('Positivkontrolle: POST ging raus', s.posts.length === 1);
check('Fenster bleibt offen', s.$('rmx-modal').classList.contains('open'));
check('Fehlertext steht (Fehlerklasse)', s.$('rmx-status').classList.contains('rmx-status-fehler')
      && s.$('rmx-status').textContent === t('rmx.save_failed'), s.$('rmx-status').textContent);
await schlaf(3200);
check('Fehlertext verschwindet nicht von selbst', s.$('rmx-status').textContent === t('rmx.save_failed'));
check('erneut uebernehmbar', s.$('rmx-apply').disabled === false);

// ── 6. Fail-closed ─────────────────────────────────────────────────────────
section('6. Bestand nicht geladen -> kein Speichern');
s = await seite({ adStatus: () => Promise.reject(new Error('netz')) });
check('Positivkontrolle: _adGeladen nicht gesetzt', !s.w._adGeladen);
s.$('rmx-open').click();
check('Hinweis "nicht geladen" sichtbar', s.$('rmx-status').textContent === t('rmx.not_loaded'));
check('Uebernehmen gesperrt', s.$('rmx-apply').disabled === true);
s.$('rmx-add-users').click(); await schlaf(80);
const p2 = [...s.d.querySelectorAll('#ldap-picker-list .ldap-row')].find(r => r.getAttribute('data-key') === 'neu.nutzer').querySelector('input');
p2.checked = true; p2.dispatchEvent(new s.w.Event('change', { bubbles: true }));
s.$('ldap-picker-apply').click();
klick(s, kaestchen(s, 'neu.nutzer', L));
check('auch nach Aenderung gesperrt', s.$('rmx-apply').disabled === true);
s.$('rmx-apply').disabled = false; s.$('rmx-apply').click();   // Knopf umgangen
await schlaf(80);
check('kein POST, selbst wenn der Knopf umgangen wird', s.posts.length === 0, s.posts.length);

// ── 7. Escape ──────────────────────────────────────────────────────────────
section('7. Escape bei offenem Picker');
s = await seite({});
s.$('rmx-open').click();
s.$('rmx-add-groups').click(); await schlaf(40);
s.d.dispatchEvent(new s.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
check('Picker zu', !s.$('ldap-picker-modal').classList.contains('open'));
check('Zuweisungs-Fenster noch offen', s.$('rmx-modal').classList.contains('open'));
s.d.dispatchEvent(new s.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
check('zweites Escape schliesst das Fenster', !s.$('rmx-modal').classList.contains('open'));
check('keine JS-Fehler', s.fehler.length === 0, s.fehler.join(' | '));

// ── 8. i18n-Regel ──────────────────────────────────────────────────────────
section('8. REGEL: jeder rmx.*-Schluessel in DE und EN');
const SRC = lies('frontend/js/rechte_matrix.js') + lies('frontend/settings.html');
const keys = [...new Set((SRC.match(/rmx\.[a-z_]+/g) || []))];
check('Positivkontrolle: Schluessel gefunden', keys.length >= 20, keys.length);
// _I18N ist ein const und liegt nicht auf window – die Bloecke am Quelltext trennen
const I18N_SRC = lies('frontend/js/i18n.js');
const enAb = I18N_SRC.indexOf('\n    en: {');
if (enAb < 0) abbruch('i18n.js ohne en-Block');
const DE_SRC = I18N_SRC.slice(0, enAb), EN_SRC = I18N_SRC.slice(enAb);
const fehlen = keys.filter(k => !DE_SRC.includes(`'${k}':`) || !EN_SRC.includes(`'${k}':`));
check('alle in DE und EN', fehlen.length === 0, fehlen.join(', '));

// ── 9. Geerbte Berechtigungen ──────────────────────────────────────────────
section('9. Geerbte Berechtigungen ueber Gruppen');
const MITGL = {
    [GRP_ALLE.toLowerCase()]: [{ sam: 'carla', display: 'Carla C', kind: 'user' },
                               { sam: 'dora', display: 'Dora D', kind: 'user' },
                               { sam: 'Unter-Gruppe', display: 'Unter-Gruppe', kind: 'group' }],
    [GRP_IT.toLowerCase()]:   [{ sam: 'BOB', display: 'Bob B', kind: 'user' }],
};
const gmOk = (q) => json({ members: MITGL[String(q.group).toLowerCase()] || [] });
s = await seite({ gm: gmOk });
s.$('rmx-open').click();
await schlaf(80);
check('Positivkontrolle: Mitglieder je Gruppe abgefragt', s.gm.length === 2, s.gm.map(q => q.group).join(' | '));
const td = (n, sp) => { const c = kaestchen(s, n, sp); return c ? c.closest('td') : null; };
let c = kaestchen(s, 'carla', I);
check('carla / Internet: grauer Haken (geerbt ueber Alle)', geerbt(c));
check('carla / Internet: Tooltip nennt die Gruppe', td('carla', I) && td('carla', I).title === t('rmx.inherit_only').replace('{liste}', 'Alle'),
      td('carla', I) && td('carla', I).title);
c = kaestchen(s, 'carla', L);
check('carla / Anmeldung: direkt (Haken) – Tooltip nennt zusaetzlich die Gruppe',
      c && c.checked && !c.disabled && td('carla', L).title === t('rmx.inherit_both').replace('{liste}', 'Alle'));
c = kaestchen(s, 'Bob', S);
check('Bob / SAP: direkt + ueber "IT, Team" (Gross/klein egal)', c && c.checked
      && td('Bob', S).title === t('rmx.inherit_both').replace('{liste}', 'IT, Team'), td('Bob', S) && td('Bob', S).title);
c = kaestchen(s, 'carla', S);
check('carla / SAP: weder direkt noch ueber Gruppe', c && !c.checked && !geerbt(c));
check('admin1 (in keiner Gruppe): nirgends ein grauer Haken',
      [...zeile(s, 'admin1').querySelectorAll('.rmx-cb')].every(x => !geerbt(x)));
// Gezeichnet wird der graue Haken ueber die Klasse (CSS) – Klasse und
// Zustand (gesetzt + gesperrt) muessen an JEDER Zelle uebereinstimmen.
const alleCb = [...s.d.querySelectorAll('#rmx-tabwrap .rmx-cb')];
check('Klasse rmx-geerbt genau dort, wo der graue Haken steht',
      alleCb.some(geerbt) && alleCb.every(x => (x.checked && x.disabled) === x.closest('td').classList.contains('rmx-geerbt')));
check('kein Kaestchen mehr im Strich-Zustand (indeterminate)', alleCb.every(x => !x.indeterminate));
check('grauer Haken zaehlt nicht als Aenderung', s.$('rmx-apply').disabled === true);
check('dora (nur ueber Gruppe) ist ausgeblendet', !zeile(s, 'dora'));
check('Schalter nennt die Zahl (1)', s.$('rmx-mitglieder-lbl').textContent === t('rmx.show_members').replace('{n}', '1'),
      s.$('rmx-mitglieder-lbl').textContent);
check('verschachtelte Gruppe ist keine Benutzerzeile', !zeile(s, 'unter-gruppe') && !zeile(s, 'Unter-Gruppe'));
const sch = s.$('rmx-mitglieder'); sch.checked = true; sch.dispatchEvent(new s.w.Event('change', { bubbles: true }));
check('Schalter an: dora erscheint, markiert "nur ueber Gruppe"', zeile(s, 'dora') && zeile(s, 'dora').textContent.includes(t('rmx.only_group')));
c = kaestchen(s, 'dora', L);
check('dora / Anmeldung: grauer Haken', geerbt(c));
check('dora (nur ueber Gruppe) hat keinen Muelleimer', zeile(s, 'dora') && !zeile(s, 'dora').querySelector('.rmx-row-clear'));
// live: Gruppe "Alle" verliert Internet -> carla verliert den Strich
klick(s, kaestchen(s, 'Alle', I));
c = kaestchen(s, 'carla', I);
check('Gruppe abgehakt: grauer Haken bei carla sofort weg', c && !c.checked && !c.disabled && td('carla', I).title === '');
klick(s, kaestchen(s, 'Alle', I));   // zurueck
check('Gruppe wieder an: grauer Haken zurueck, keine Aenderung offen',
      geerbt(kz(s, 'carla', I)) && s.$('rmx-apply').disabled === true);
// Vorgabe: wo eine Gruppe den Bereich gibt, KEIN zusaetzlicher direkter Eintrag
c = kaestchen(s, 'dora', L);
check('grauer Haken ist gesperrt (kein zusaetzliches Eintragen)', c && c.disabled === true);
klick(s, c);
check('Klick auf den grauen Haken aendert nichts', geerbt(kz(s, 'dora', L))
      && s.$('rmx-apply').disabled === true);
check('direkter Haken ohne Gruppe bleibt bedienbar', kz(s, 'admin1', L).disabled === false);
// NEU gesetzte Freigabe, die durch einen Gruppen-Haken ueberfluessig wird, faellt zurueck
klick(s, kaestchen(s, 'dora', K));
check('Positivkontrolle: dora / Wissen direkt gesetzt', kz(s, 'dora', K).checked === true);
klick(s, kaestchen(s, 'Alle', K));
check('Gruppe bekommt Wissen: doras neuer Haken faellt auf grauen Haken zurueck',
      geerbt(kz(s, 'dora', K)));
check('BESTEHENDER Doppel-Eintrag (carla / Wissen) bleibt abwaehlbar', kz(s, 'carla', K).checked && !kz(s, 'carla', K).disabled);
klick(s, kaestchen(s, 'carla', L));
check('carla / Anmeldung abgewaehlt: jetzt grauer Haken, gesperrt', geerbt(kz(s, 'carla', L)));
check('Zaehler: 2 Aenderungen (Gruppe + carla)', s.$('rmx-apply').textContent === t('rmx.apply_n').replace('{n}', '2'),
      s.$('rmx-apply').textContent);
s.$('rmx-apply').click();
await schlaf(80);
const b9 = s.posts[0] || {};
check('Gruppe Alle in ad_knowledge_editors_group', b9.ad_knowledge_editors_group === GRP_ALLE, JSON.stringify(b9.ad_knowledge_editors_group));
check('dora NICHT direkt eingetragen (Wissen)', b9.ad_knowledge_editors === 'carla', b9.ad_knowledge_editors);
check('carla aus ad_allowed_users entfernt, dora nicht hinein', b9.ad_allowed_users === 'Bob', b9.ad_allowed_users);
check('geerbte graue Haken schreiben nichts (ad_internet_users leer)', b9.ad_internet_users === '', JSON.stringify(b9.ad_internet_users));

// Schreibweisen wie im Backend (_norm_login): FIRMA\carla == carla
section('9b. Schreibweisen: Domain-Praefix und UPN');
s = await seite({ gm: gmOk, adStatus: () => json(Object.assign({}, AD, { allowed_users: 'FIRMA\\carla', sap_users: 'carla@firma.local' })) });
s.$('rmx-open').click();
await schlaf(80);
const cz = zeilen(s).filter(tr => /carla/i.test(tr.querySelector('.rmx-wert').textContent));
check('FIRMA\\carla und carla@firma.local sind EINE Zeile', cz.length === 1, cz.length);
check('... mit beiden Haken', kaestchen(s, 'FIRMA\\carla', L) && kz(s, 'FIRMA\\carla', L).checked && kz(s, 'FIRMA\\carla', S).checked);
check('... und dem grauen Haken ueber Alle (Mitglied "carla")', geerbt(kaestchen(s, 'FIRMA\\carla', I)));
klick(s, kaestchen(s, 'FIRMA\\carla', S));
s.$('rmx-apply').click();
await schlaf(80);
check('Entfernen trifft "carla@firma.local" ueber den normierten Namen', (s.posts[0] || {}).sap_allowed_users === '', (s.posts[0] || {}).sap_allowed_users);

section('9c. Ohne Verzeichnis-Zugang: "nicht ermittelt" statt "nicht berechtigt"');
s = await seite({ gm: () => json({ error: 'NO_CREDENTIALS' }, 428) });
s.$('rmx-open').click();
await schlaf(80);
check('Positivkontrolle: Abfrage lief', s.gm.length === 2);
const info = s.$('rmx-erbe-info');
check('Hinweis nennt beide Gruppen', info.textContent.includes(t('rmx.inherit_no_cred').replace('{liste}', 'Alle, IT, Team')), info.textContent);
check('Hinweis als Warnung markiert', info.classList.contains('rmx-erbe-warn'));
check('kein grauer Haken behauptet', [...s.d.querySelectorAll('.rmx-cb')].every(x => !geerbt(x)));
check('keine JS-Fehler', s.fehler.length === 0, s.fehler.join(' | '));

// ── 10. Sortieren ──────────────────────────────────────────────────────────
section('9f. REGEL: der graue Haken ist gezeichnet (CSS)');
const CSS = lies('frontend/css/style.css');
const regel = (CSS.match(/td\.rmx-geerbt input\.rmx-cb:checked:disabled\s*\{[^}]*\}/) || [''])[0];
check('Regel fuer den grauen Haken vorhanden, Flaeche aus var(--text-muted)', /background:\s*var\(--text-muted\)/.test(regel), regel);
check('... mit dem Hakenzeichen (::after)', /td\.rmx-geerbt input\.rmx-cb:checked:disabled::after\s*\{[^}]*border-width/.test(CSS));
check('alte Strich-Regel ist weg', !/rmx-geerbt input\.rmx-cb:not\(:checked\)/.test(CSS));

section('10. Spalten sortieren, Sortierung gemerkt');
const reihe = (s) => zeilen(s).map(tr => tr.querySelector('.rmx-wert').textContent);
const kopfKnopf = (s, label) => [...s.d.querySelectorAll('#rmx-tabwrap thead .rmx-sort')].find(b => b.textContent.replace(/[▲▼]/g, '') === label) || null;
const sortKlick = (s, label) => { const b = kopfKnopf(s, label); if (!b) { check('Kopf-Knopf ' + label, false, 'fehlt'); return; } b.click(); };
s = await seite({ gm: gmOk });
s.$('rmx-open').click();
await schlaf(80);
check('Vorgabe: nach Name A-Z, Gruppen zuerst', reihe(s).join('|') === 'Alle|IT, Team|admin1|Bob|carla', reihe(s).join('|'));
check('Namensspalte traegt aria-sort=ascending', s.d.querySelector('#rmx-tabwrap thead th.rmx-name-th').getAttribute('aria-sort') === 'ascending');
sortKlick(s, t('rmx.col_principal'));
check('Name erneut: Z-A, Gruppen bleiben oben', reihe(s).join('|') === 'IT, Team|Alle|carla|Bob|admin1', reihe(s).join('|'));
sortKlick(s, I);
check('Internet: direkt, dann ueber Gruppe, dann keine', reihe(s).join('|') === 'Alle|IT, Team|carla|admin1|Bob', reihe(s).join('|'));
check('Internet-Kopf traegt aria-sort, Name nicht mehr',
      kopfKnopf(s, I).closest('th').getAttribute('aria-sort') === 'ascending'
      && s.d.querySelector('#rmx-tabwrap thead th.rmx-name-th').getAttribute('aria-sort') === 'none');
sortKlick(s, I);
check('Internet erneut: umgekehrt (Gleichstand bleibt A-Z)', reihe(s).join('|') === 'IT, Team|Alle|admin1|Bob|carla', reihe(s).join('|'));
let gemerkt = null; try { gemerkt = JSON.parse(s.w.localStorage.getItem('jarvis_rmx_sort')); } catch (e) {}
check('Sortierung gemerkt (Bereich, nicht Spaltenindex)', gemerkt && gemerkt.nach === 'internet' && gemerkt.richtung === -1, JSON.stringify(gemerkt));
// Haken setzen sortiert NICHT um
klick(s, kaestchen(s, 'admin1', I));
check('Haken setzen laesst die Reihenfolge stehen', reihe(s).join('|') === 'IT, Team|Alle|admin1|Bob|carla', reihe(s).join('|'));
// Wiederoeffnen in derselben Seite
s.$('rmx-cancel').click(); s.$('rmx-open').click(); await schlaf(80);
check('Wiederoeffnen: gemerkte Sortierung gilt', reihe(s).join('|') === 'IT, Team|Alle|admin1|Bob|carla', reihe(s).join('|'));
// neue Seite mit gemerktem Wert im Speicher
s = await seite({ gm: gmOk, vorab: (w) => w.localStorage.setItem('jarvis_rmx_sort', JSON.stringify({ nach: 'name', richtung: -1 })) });
s.$('rmx-open').click(); await schlaf(80);
check('frische Seite liest die gemerkte Sortierung', reihe(s).join('|') === 'IT, Team|Alle|carla|Bob|admin1', reihe(s).join('|'));
// gemerkte Spalte gibt es hier nicht (VEMAS ausgeblendet) -> Name A-Z
s = await seite({ gm: gmOk, vorab: (w) => w.localStorage.setItem('jarvis_rmx_sort', JSON.stringify({ nach: 'vemas', richtung: -1 })) });
s.$('rmx-open').click(); await schlaf(80);
check('gemerkte Spalte ausgeblendet: Rueckfall auf Name A-Z', reihe(s).join('|') === 'Alle|IT, Team|admin1|Bob|carla', reihe(s).join('|'));
s = await seite({ gm: gmOk, vorab: (w) => w.localStorage.setItem('jarvis_rmx_sort', '{kaputt') });
s.$('rmx-open').click(); await schlaf(80);
check('kaputter Speicherwert: Vorgabe, kein Fehler', reihe(s).join('|') === 'Alle|IT, Team|admin1|Bob|carla' && s.fehler.length === 0, reihe(s).join('|'));

clearTimeout(WACH);
console.log(`\n${ok} OK, ${fail} FAIL`);
BILANZ = true;
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
