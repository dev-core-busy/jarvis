/* Waechter: "Gruppenmitgliedschaften anzeigen" (frontend/js/ldap_picker.js).
 *
 * Gemessen an der ECHTEN settings.html mit den ECHTEN Modulen (i18n, icons,
 * ldap_picker), fetch ueber den Pfad geroutet:
 *   1. Benutzer-Chip in einer Freigabeliste ist ein Knopf und oeffnet das
 *      Popup mit OU-Pfad, direkten, indirekten Gruppen und Primaergruppe.
 *   2. Klick auf eine Gruppe dort oeffnet ihre Mitglieder OBEN drauf; Escape
 *      schliesst nur das oberste Popup.
 *   3. Benutzername im Verzeichnis-Picker oeffnet das Popup, ohne die Auswahl
 *      umzuschalten; Benutzer in der Mitgliederliste ebenso.
 *   4. Fehler bleibt stehen; "indirekt unbekannt" wird genannt, nicht als leer.
 *   5. REGEL: jeder ldap.groups_*-Schluessel des Moduls in DE und EN.
 *
 *   node tests/test_ldap_gruppen_ui.js
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
function abbruch(g) { console.log('ABBRUCH: ' + g); BILANZ = true; process.exit(2); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));
const WACH = setTimeout(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 60000);
process.on('exit', (c) => { if (!BILANZ && c === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 2; } });

const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/ldap_picker.js'];
const G_A = 'CN=Alle Labor,OU=Gruppen,DC=firma,DC=local';
const G_B = 'CN=B\\, Team,OU=Gruppen,DC=firma,DC=local';
const lage = (name, ou) => ({ name: name, ou: ou, container: '', domaene: 'firma.local' });
const ANTWORT = {
    sam: 'erika.muster', display: 'Erika Muster', mail: 'erika.muster@beispiel.de', upn: '',
    dn: 'CN=Muster\\, Erika,OU=Nord,OU=Labor,OU=Benutzer,DC=firma,DC=local',
    lage: lage('Muster, Erika', ['Benutzer', 'Labor', 'Nord']),
    direkt: [{ cn: 'Alle Labor', dn: G_A, lage: lage('Alle Labor', ['Gruppen']) },
             { cn: 'B, Team', dn: G_B, lage: lage('B, Team', ['Gruppen']) }],
    indirekt: [{ cn: 'Ueber Kette', dn: 'CN=Ueber Kette,OU=Gruppen,DC=firma,DC=local', lage: lage('Ueber Kette', ['Gruppen']) }],
    primaer: { cn: 'Domaenen-Benutzer', dn: 'CN=Domaenen-Benutzer,CN=Users,DC=firma,DC=local', lage: lage('Domaenen-Benutzer', ['Users']) }
};
const json = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200, json: () => Promise.resolve(d) });

async function seite(opt) {
    opt = opt || {};
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const dom = new JSDOM(lies('frontend/settings.html'), {
        url: 'https://localhost/settings', runScripts: 'outside-only', virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    const ug = [], gm = [];
    w.fetch = (u, o) => {
        const p = String(u).split('?')[0];
        if (p === '/api/ldap/user_groups') { const q = JSON.parse(o.body); ug.push(q); return opt.ug ? opt.ug(q) : json(ANTWORT); }
        if (p === '/api/ldap/group_members') { const q = JSON.parse(o.body); gm.push(q); return json({ cn: 'x', dn: q.group, count: 1,
            members: [{ sam: 'bob', display: 'Bob B', mail: '', kind: 'user' }, { sam: 'sub', display: 'Sub', mail: '', kind: 'group' }] }); }
        if (p === '/api/ldap/users') return json({ users: [{ sam: 'erika.muster', display: 'Erika Muster', mail: '' }] });
        return json({});
    };
    w.alert = () => {}; w.confirm = () => true;
    sitzungLaden(w, { token: 'TOK' });
    for (const m of MODULE) w.eval(lies(m));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
    await schlaf(50);
    return { w, d: w.document, fehler, ug, gm, $: (id) => w.document.getElementById(id) };
}
const offen = (m) => !!(m && m.classList.contains('open'));
const esc = (s) => s.d.dispatchEvent(new s.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
function chipKnopf(s, feld, wert) {
    const inp = s.$(feld);
    if (!inp) return null;
    inp.value = wert;
    inp.dispatchEvent(new s.w.Event('change', { bubbles: true }));
    const liste = inp.parentNode.querySelector('.token-list');
    return liste ? liste.querySelector('.ldap-groups-btn') : null;
}

(async () => {
// ── Positivkontrolle: Seite und Modul geladen, Feld mit Chip-Liste da ──────
let s = await seite();
if (!s.w.LdapPicker || !s.w.LdapPicker.gruppenVon) {
    // fehlt die Schnittstelle, ist das ein Befund, kein Messaufbau-Problem
    check('LdapPicker.gruppenVon vorhanden', false, 'fehlt');
}
if (!s.$('ad-allowed-users') || !s.$('ad-allowed-users').parentNode.querySelector('.token-list')) {
    abbruch('settings.html hat kein #ad-allowed-users mit Chip-Liste – Messaufbau stimmt nicht');
}

section('1. Chip -> Popup mit Ort und Gruppen');
const k = chipKnopf(s, 'ad-allowed-users', 'erika.muster');
check('Benutzer-Chip ist ein Knopf', !!k && k.tagName === 'BUTTON', k && k.tagName);
check('Knopf nennt die Wirkung im Tooltip', !!k && /Gruppenmitgliedschaften/.test(k.title || ''), k && k.title);
const grpChip = chipKnopf(s, 'ad-allowed-group', G_A);
check('Gruppen-Chip bekommt KEINEN Benutzer-Knopf', grpChip === null);
if (k) k.click();
await schlaf(30);
const gmod = s.$('ldap-groups-modal');
check('Popup offen', offen(gmod));
check('Anfrage mit dem Chip-Wert', s.ug.length === 1 && s.ug[0].user === 'erika.muster', JSON.stringify(s.ug));
const text = gmod ? gmod.textContent : '';
check('Titel = Anzeigename', s.$('ldap-groups-title') && s.$('ldap-groups-title').textContent === 'Erika Muster',
      s.$('ldap-groups-title') && s.$('ldap-groups-title').textContent);
check('OU-Pfad von aussen nach innen samt Domaene', text.includes('firma.local › Benutzer › Labor › Nord'), text.slice(0, 300));
check('voller DN sichtbar', text.includes(ANTWORT.dn));
const kopf = gmod ? [...gmod.querySelectorAll('.ldap-groups-h')].map(h => h.textContent) : [];
check('direkte Gruppen mit Zahl und "zählen"', kopf.some(h => /Direkte Gruppen/.test(h) && /\(2\)/.test(h) && /zählen für/.test(h)), kopf.join(' | '));
check('indirekte Gruppen als "zählen nicht"', kopf.some(h => /verschachtelte/.test(h) && /zählen nicht/.test(h) && /\(1\)/.test(h)), kopf.join(' | '));
check('Primärgruppe als "zählt nicht"', kopf.some(h => /Primärgruppe/.test(h) && /zählt nicht/.test(h)), kopf.join(' | '));
check('Gruppenname mit Komma ganz', text.includes('B, Team'));
check('Schließen-Symbol aus icons.js (kein Emoji)', !!(gmod && gmod.querySelector('#ldap-groups-close .jv-ico-close')));

section('2. Gruppe -> Mitglieder oben drauf, Escape schliesst nur das oberste');
const gb = gmod ? gmod.querySelector('#ldap-groups-body .ldap-members-btn') : null;
if (gb) gb.click();
await schlaf(30);
const mmod = s.$('ldap-members-modal');
check('Mitglieder-Popup offen', offen(mmod));
check('mit der geklickten Gruppe', s.gm.length === 1 && s.gm[0].group === G_A, JSON.stringify(s.gm));
check('liegt ueber den Mitgliedschaften',
      mmod && gmod && parseInt(mmod.style.zIndex, 10) > parseInt(gmod.style.zIndex, 10),
      mmod && gmod && (mmod.style.zIndex + ' vs ' + gmod.style.zIndex));
const mb = mmod ? mmod.querySelector('#ldap-members-list .ldap-groups-btn') : null;
check('Benutzer in der Mitgliederliste ist ein Knopf', !!mb && mb.getAttribute('data-user') === 'bob');
check('verschachtelte Gruppe dort NICHT', mmod && mmod.querySelectorAll('#ldap-members-list .ldap-groups-btn').length === 1);
esc(s);
check('Escape: Mitglieder zu', !offen(mmod));
check('Escape: Mitgliedschaften bleiben offen', offen(gmod));
esc(s);
check('zweites Escape: Mitgliedschaften zu', !offen(gmod));
// Mitgliedschaften aus der Mitgliederliste: wieder oben drauf
if (gb) gb.click();
await schlaf(30);
if (mb && s.$('ldap-members-list').querySelector('.ldap-groups-btn')) s.$('ldap-members-list').querySelector('.ldap-groups-btn').click();
await schlaf(30);
check('aus der Mitgliederliste: Mitgliedschaften von bob', s.ug.length >= 2 && s.ug[s.ug.length - 1].user === 'bob', JSON.stringify(s.ug));
check('... und wieder ganz oben',
      offen(gmod) && parseInt(gmod.style.zIndex, 10) > parseInt(mmod.style.zIndex, 10),
      gmod && mmod && (gmod.style.zIndex + ' vs ' + mmod.style.zIndex));
esc(s); esc(s);

section('3. Verzeichnis-Picker: Name oeffnet, Auswahl bleibt');
s.w.LdapPicker.open({ kind: 'users', multi: true, sep: ',', list: true }, s.$('ad-allowed-users'));
await schlaf(30);
const zeile = s.d.querySelector('#ldap-picker-list .ldap-row');
const cb = zeile ? zeile.querySelector('input[type="checkbox"]') : null;
const nb = zeile ? zeile.querySelector('.ldap-groups-btn') : null;
check('Name im Picker ist ein Knopf', !!nb);
const vorher = cb ? cb.checked : null;
const n0 = s.ug.length;
if (nb) nb.click();
await schlaf(30);
check('Klick oeffnet die Mitgliedschaften', s.ug.length === n0 + 1 && offen(s.$('ldap-groups-modal')));
check('Klick schaltet die Auswahl NICHT um', cb && cb.checked === vorher, cb && (vorher + ' -> ' + cb.checked));
check('Mitgliedschaften ueber dem Picker',
      parseInt(s.$('ldap-groups-modal').style.zIndex, 10) > parseInt(s.$('ldap-picker-modal').style.zIndex, 10));
esc(s);
check('Escape schliesst zuerst die Mitgliedschaften, der Picker bleibt',
      !offen(s.$('ldap-groups-modal')) && offen(s.$('ldap-picker-modal')));
esc(s);
// Einzelauswahl: dort WAEHLT ein Klick auf die Zeile und schliesst den Picker.
// Der Namens-Knopf darf das nicht ausloesen (im Mehrfach-Picker schuetzt schon
// das <label> – ein Knopf darin aktiviert die Checkbox laut HTML nicht).
const ziel = s.d.createElement('input');
ziel.value = 'vorher';
s.d.body.appendChild(ziel);
s.w.LdapPicker.open({ kind: 'users', multi: false }, ziel);
await schlaf(30);
const nb1 = s.d.querySelector('#ldap-picker-list .ldap-groups-btn');
if (nb1) nb1.click();
await schlaf(30);
check('Einzelauswahl: Name-Klick waehlt NICHT aus', ziel.value === 'vorher', ziel.value);
check('Einzelauswahl: Picker bleibt offen', offen(s.$('ldap-picker-modal')));
check('Einzelauswahl: Mitgliedschaften offen', offen(s.$('ldap-groups-modal')));
esc(s); esc(s);

section('4. Fehler und unbekannte Kette');
s = await seite({ ug: () => json({ error: "Benutzer 'x' nicht im Verzeichnis gefunden." }, 400) });
s.w.LdapPicker.gruppenVon('x');
await schlaf(30);
const inf = s.$('ldap-groups-info');
check('Fehlertext steht da', inf && /nicht im Verzeichnis gefunden/.test(inf.textContent), inf && inf.textContent);
check('als Fehler markiert', inf && inf.classList.contains('is-fehler'));
await schlaf(400);
check('Fehler verschwindet nicht von selbst', inf && /nicht im Verzeichnis/.test(inf.textContent));
s = await seite({ ug: () => json(Object.assign({}, ANTWORT, { indirekt: null, primaer: null })) });
s.w.LdapPicker.gruppenVon('erika.muster');
await schlaf(30);
const t2 = s.$('ldap-groups-modal').textContent;
check('indirekt null -> "nicht ermittelt" genannt', /nicht ermittelt/.test(t2), t2.slice(0, 400));
check('Primärgruppe null -> kein Abschnitt', !/Primärgruppe/.test(t2));
s = await seite({ ug: () => json(Object.assign({}, ANTWORT, { direkt: [], indirekt: [] })) });
s.w.LdapPicker.gruppenVon('erika.muster');
await schlaf(30);
const t3 = s.$('ldap-groups-modal').textContent;
check('keine direkten Gruppen -> ausdruecklich gesagt', /Keine direkten Gruppen/.test(t3));
check('leere indirekte Liste -> kein Abschnitt', !/verschachtelte Gruppen/.test(t3));
check('keine JS-Fehler', s.fehler.length === 0, s.fehler.join(' | '));

section('5. REGEL: Schluessel in DE und EN');
const modul = lies('frontend/js/ldap_picker.js');
const i18n = lies('frontend/js/i18n.js');
const keys = [...new Set([...modul.matchAll(/['"](ldap\.(?:groups_[a-z_]+|show_groups_title))['"]/g)].map(m => m[1]))];
check('Modul benutzt Schluessel (Positivkontrolle)', keys.length >= 8, keys.length);
const fehlend = keys.filter(k => (i18n.split("'" + k + "':").length - 1) !== 2);
check('jeder Schluessel genau zweimal (DE+EN)', fehlend.length === 0, fehlend.join(', '));

clearTimeout(WACH);
console.log(`\n${ok} OK, ${fail} FAIL`);
BILANZ = true;
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
