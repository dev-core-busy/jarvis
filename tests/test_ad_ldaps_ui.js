/* Waechter: Schalter LDAP (StartTLS) / LDAPS am Domain-Controller
 * (Einstellungen -> Sicherheit -> Verbindung, frontend/js/settings_ad.js).
 *
 * Zusagen:
 *   1. Die Verbindungsart steht als Schema in ad_server ("ldaps://…") – es gibt
 *      KEIN zweites Feld, das der Adresse widersprechen koennte. Laden: Schema
 *      -> Schalter, Feld ohne Schema.
 *   2. Speichern ohne Umschalten laesst den gespeicherten Wert einer
 *      Bestandsanlage (ohne Schema = StartTLS) byte-gleich.
 *   3. Umschalten schreibt "ldaps://<host>" bzw. "<host>"; der Standardport der
 *      ANDEREN Art wird nicht mitgenommen, ein eigener Port bleibt.
 *   4. Ein ins Feld getipptes Schema legt den Schalter um und verschwindet aus
 *      dem Feld; ein fremdes Schema bleibt stehen (das Backend nennt es).
 *   5. Verbindungstest und Zertifikatspruefung benutzen die GEWAEHLTE Art.
 *   6. Passt der verankerte Zertifikats-Anker (host:port) nicht mehr zur
 *      gewaehlten Art, steht VOR dem Speichern eine Warnung da.
 *   7. Die Beschriftung wechselt mit dem Zustand; alle neuen Schluessel DE+EN.
 *
 * Die Gegenseite (ldap_tls.ziel versteht ldaps://host[:port], Standard 636)
 * misst tests/test_bsi_ldap_vnc.py Abschnitt 4 gegen eine LDAP-Attrappe.
 *
 *   node tests/test_ad_ldaps_ui.js [<pfad zu einer Kopie von settings_ad.js>]
 * Das Argument ist fuer die Gegenprobe (gegen_ad_ldaps_ui.py): sie legt
 * sabotierte KOPIEN vor, die echte Datei wird nie angefasst.
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.isAbsolute(rel) ? rel : path.join(ROOT, rel), 'utf8');
const AD_JS = process.argv[2] ? path.resolve(process.argv[2]) : 'frontend/js/settings_ad.js';
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

const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/sapcert.js',
                AD_JS];
const FP = 'sha256:' + 'ab'.repeat(32);
const json = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                          json: () => Promise.resolve(d) });

async function seite(opt) {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const dom = new JSDOM(lies('frontend/settings.html'), {
        url: 'https://localhost/settings', runScripts: 'outside-only', virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    const posts = [];
    const status = Object.assign({
        configured: true, reachable: true, server: 'dc.firma.local', domain: 'firma.local',
        access_mode: 'users', allowed_users: 'bob', tls_anker: {}, tls_uebergang: { aktiv: false, bis: '2026-10-13' }
    }, opt.status || {});
    w.fetch = (u, o) => {
        const p = String(u).split('?')[0];
        if (p === '/api/auth/ad_status') return json(status);
        if (o && o.body) posts.push({ pfad: p, rumpf: JSON.parse(o.body) });
        if (p === '/api/auth/ad_test') return json(opt.adTest || { reachable: true, tls_ok: true });
        if (p === '/api/auth/ad_tls/probe') return json({ ok: false, error: 'Attrappe' }, 400);
        return json({});
    };
    w.alert = () => {}; w.confirm = () => true;
    sitzungLaden(w, { token: 'TOK' });
    for (const m of MODULE) w.eval(lies(m));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
    await schlaf(80);
    const $ = (id) => w.document.getElementById(id);
    return {
        w, $, fehler, posts,
        umlegen(an) { const cb = $('ad-ldaps'); cb.checked = an; cb.dispatchEvent(new w.Event('change', { bubbles: true })); },
        tippen(text) {
            const f = $('ad-server'); f.value = text;
            f.dispatchEvent(new w.Event('input', { bubbles: true }));
            f.dispatchEvent(new w.Event('change', { bubbles: true }));
        },
        async speichern() { posts.length = 0; await w._adSave(); const p = posts.find(x => x.pfad === '/api/settings'); return p ? p.rumpf : null; }
    };
}
// Nur sichtbar, wenn weder das Element noch ein Vorfahr hidden traegt
function sichtbar(el) { for (let e = el; e; e = e.parentElement) if (e.hidden) return false; return !!el; }

(async () => {
// ── 0. Positivkontrolle ────────────────────────────────────────────────────
section('0. Messaufbau');
let s = await seite({});
if (!s.$('ad-server')) abbruch('settings.html ohne #ad-server – Messaufbau');
if (typeof s.w._adSave !== 'function') abbruch('settings_ad.js nicht geladen (window._adSave fehlt)');
check('Positivkontrolle: Bestand geladen (Domain-Feld gefuellt)', s.$('ad-domain').value === 'firma.local', s.$('ad-domain').value);
check('settings.html hat den Schalter #ad-ldaps (Checkbox)', !!s.$('ad-ldaps') && s.$('ad-ldaps').type === 'checkbox');
check('settings.html hat die Warnzeile #ad-ldaps-anker', !!s.$('ad-ldaps-anker'));
if (!s.$('ad-ldaps')) { BILANZ = true; console.log(`\n${ok} OK, ${fail} FAIL`); process.exit(1); }
check('keine JS-Fehler beim Laden', s.fehler.length === 0, s.fehler.join(' | '));

// ── 1+2. Laden und unveraendertes Speichern ───────────────────────────────
section('1. Laden: Schema -> Schalter, Feld ohne Schema');
check('ohne Schema: Schalter aus', s.$('ad-ldaps').checked === false);
check('ohne Schema: Feld = Adresse', s.$('ad-server').value === 'dc.firma.local', s.$('ad-server').value);
check('Beschriftung "StartTLS" sichtbar, "LDAPS" nicht',
      sichtbar(s.$('ad-ldaps-aus')) && !sichtbar(s.$('ad-ldaps-an')));
section('2. Speichern ohne Umschalten laesst den Bestand byte-gleich');
let r = await s.speichern();
check('POST /api/settings ging raus', !!r);
check('ad_server unveraendert "dc.firma.local"', r && r.ad_server === 'dc.firma.local', r && r.ad_server);

let s2 = await seite({ status: { server: 'ldaps://dc.firma.local:3269' } });
check('ldaps:// geladen: Schalter an', s2.$('ad-ldaps').checked === true);
check('ldaps:// geladen: Feld ohne Schema, eigener Port bleibt', s2.$('ad-server').value === 'dc.firma.local:3269', s2.$('ad-server').value);
check('Beschriftung "LDAPS" sichtbar, "StartTLS" nicht',
      sichtbar(s2.$('ad-ldaps-an')) && !sichtbar(s2.$('ad-ldaps-aus')));
r = await s2.speichern();
check('ldaps:// ohne Umschalten gespeichert wie geladen', r && r.ad_server === 'ldaps://dc.firma.local:3269', r && r.ad_server);

let s3 = await seite({ status: { server: 'ldap://dc.firma.local' } });
check('ldap:// geladen: Schalter aus', s3.$('ad-ldaps').checked === false);
r = await s3.speichern();
check('ldap:// wird als Adresse ohne Schema gespeichert (gleiche Bedeutung)', r && r.ad_server === 'dc.firma.local', r && r.ad_server);

// ── 3. Umschalten ─────────────────────────────────────────────────────────
section('3. Umschalten schreibt die Art in die Adresse');
s.umlegen(true);
check('Beschriftung wechselt mit dem Zustand', sichtbar(s.$('ad-ldaps-an')) && !sichtbar(s.$('ad-ldaps-aus')));
r = await s.speichern();
check('an: "ldaps://dc.firma.local"', r && r.ad_server === 'ldaps://dc.firma.local', r && r.ad_server);
s.umlegen(false);
r = await s.speichern();
check('wieder aus: "dc.firma.local"', r && r.ad_server === 'dc.firma.local', r && r.ad_server);

const A = s.w.AdLdaps;
if (!A) abbruch('window.AdLdaps fehlt – Messaufbau');
const faelle = [
    ['dc:389', true, 'ldaps://dc'],            // Standardport der anderen Art faellt weg
    ['dc:636', false, 'dc'],
    ['dc:636', true, 'ldaps://dc:636'],        // eigener Standard darf stehen bleiben
    ['dc:3269', true, 'ldaps://dc:3269'],      // eigener Port bleibt
    ['[2001:db8::1]:389', true, 'ldaps://[2001:db8::1]'],
    ['2001:db8::389', true, 'ldaps://2001:db8::389'],   // nackte IPv6: KEIN Port abgeschnitten
    ['dc.firma.local/', true, 'ldaps://dc.firma.local'],
    ['  dc  ', false, 'dc'],
    ['', true, ''],                             // leer bleibt leer (Pflichtfeld-Meldung)
    ['http://dc', true, 'http://dc']            // fremdes Schema: bleibt, Backend nennt es
];
for (const [feld, ldaps, soll] of faelle) {
    const ist = A.adresseAus(feld, ldaps);
    check(`adresseAus(${JSON.stringify(feld)}, ${ldaps}) = ${JSON.stringify(soll)}`, ist === soll, ist);
}
const zf = [['ldaps://DC.Firma.local', 'dc.firma.local', 636], ['dc', 'dc', 389],
            ['ldaps://dc:3269', 'dc', 3269], ['ldaps://[2001:db8::1]', '2001:db8::1', 636]];
for (const [adr, host, port] of zf) {
    const z = A.ziel(adr) || {};
    check(`ziel(${adr}) = ${host}:${port} (Regeln wie ldap_tls.ziel)`, z.host === host && z.port === port, JSON.stringify(z));
}

// ── 4. Schema im Feld ─────────────────────────────────────────────────────
section('4. Getipptes Schema legt den Schalter um');
s.tippen('ldaps://dc2.firma.local');
check('Schalter an', s.$('ad-ldaps').checked === true);
check('Schema aus dem Feld genommen', s.$('ad-server').value === 'dc2.firma.local', s.$('ad-server').value);
r = await s.speichern();
check('gespeichert als ldaps://dc2.firma.local', r && r.ad_server === 'ldaps://dc2.firma.local', r && r.ad_server);
s.tippen('LDAP://dc2.firma.local');
check('ldap:// (gross) schaltet aus', s.$('ad-ldaps').checked === false && s.$('ad-server').value === 'dc2.firma.local',
      s.$('ad-ldaps').checked + ' ' + s.$('ad-server').value);
s.tippen('http://dc2');
check('fremdes Schema bleibt im Feld stehen', s.$('ad-server').value === 'http://dc2');
r = await s.speichern();
check('fremdes Schema geht unveraendert ans Backend', r && r.ad_server === 'http://dc2', r && r.ad_server);
// Schema getippt und OHNE change-Ereignis direkt gespeichert (Enter ohne Blur)
s.$('ad-server').value = 'ldaps://dc3';
r = await s.speichern();
check('auch ohne change-Ereignis gilt das getippte Schema', r && r.ad_server === 'ldaps://dc3', r && r.ad_server);

// ── 5. Test und Zertifikatspruefung ───────────────────────────────────────
section('5. Verbindungstest und Zertifikatspruefung benutzen die gewaehlte Art');
let s5 = await seite({});
s5.umlegen(true);
s5.posts.length = 0;
await s5.w._adTest();
await schlaf(20);
const t5 = s5.posts.find(x => x.pfad === '/api/auth/ad_test');
check('Verbindungstest: ad_server = ldaps://dc.firma.local', t5 && t5.rumpf.ad_server === 'ldaps://dc.firma.local', t5 && JSON.stringify(t5.rumpf));
const knopf = [...s5.$('ad-cert').querySelectorAll('button')]
    .find(b => b.textContent === s5.w.t('sapcert.check'));
check('Zertifikat-Knopf gefunden (Positivkontrolle)', !!knopf);
if (knopf) {
    s5.posts.length = 0;
    knopf.click();
    await schlaf(30);
    const p5 = s5.posts.find(x => x.pfad === '/api/auth/ad_tls/probe');
    check('Zertifikatspruefung: server = ldaps://dc.firma.local', p5 && p5.rumpf.server === 'ldaps://dc.firma.local', p5 && JSON.stringify(p5.rumpf));
}

// ── 5b. Ergebniszeile nennt Art und Port aus der SERVER-Antwort ──────────
// Bis 2026-11-18 stand dort fest "LDAP Port 389" – auch nach dem Umstellen auf
// LDAPS (gemeldet von ECHT). Die Antwortform bildet main.test_ad_connection
// nach: ziel = {host, port, ldaps} aus ldap_tls.ziel.
section('5b. Verbindungstest: Art und Port aus dem gemessenen Ziel');
async function testZeile(antwort, ldaps) {
    const x = await seite({ adTest: antwort });
    if (ldaps) x.umlegen(true);
    await x.w._adTest();
    await schlaf(20);
    const t = x.$('ad-test-result').textContent;
    x.w.close();
    return t;
}
let z5 = await testZeile({ reachable: true, tls_ok: true, ziel: { host: 'dc.firma.local', port: 636, ldaps: true } }, true);
check('LDAPS: Zeile nennt LDAPS und Port 636', z5.includes('LDAPS') && z5.includes('636'), z5);
check('LDAPS: Zeile nennt NICHT 389', !z5.includes('389'), z5);
z5 = await testZeile({ reachable: true, tls_ok: true, ziel: { host: 'dc.firma.local', port: 389, ldaps: false } }, false);
check('StartTLS: Zeile nennt StartTLS und Port 389', z5.includes('StartTLS') && z5.includes('389'), z5);
z5 = await testZeile({ reachable: true, tls_ok: true, ziel: { host: 'dc.firma.local', port: 3269, ldaps: true } }, true);
check('eigener Port: die Zahl des Servers (3269), nicht der Standard', z5.includes('3269') && !z5.includes('636'), z5);
// Formular und Antwort widersprechen sich: es gilt, was der Server gemessen hat
z5 = await testZeile({ reachable: true, tls_ok: true, ziel: { host: 'dc.firma.local', port: 636, ldaps: true } }, false);
check('Anzeige folgt der Messung, nicht dem Formular (Schalter aus, Server meldet LDAPS)',
      z5.includes('LDAPS') && z5.includes('636'), z5);
z5 = await testZeile({ reachable: true, tls_ok: true }, true);
check('ohne Ziel (alter Server): kein erfundener Port', !/\b(389|636)\b/.test(z5) && z5.includes(s.w.t('security.ad_tls_ok')), z5);
const I18N5 = lies('frontend/js/i18n.js');
check('kein fester Port mehr im Text security.ad_reachable (DE+EN)',
      !/'security\.ad_reachable':\s*'[^']*\d/.test(I18N5));
for (const k of ['security.ad_reachable_ldaps', 'security.ad_reachable_starttls']) {
    const n = (I18N5.match(new RegExp("'" + k.replace(/\./g, '\\.') + "'\\s*:[^\\n]*\\{port\\}", 'g')) || []).length;
    check(k + ' in DE und EN mit {port}', n === 2, n);
}

// ── 6. Anker-Warnung ──────────────────────────────────────────────────────
section('6. Warnung, wenn der Anker nicht mehr zur Art passt');
let s6 = await seite({ status: { tls_anker: { host: 'dc.firma.local', port: 389, fingerprint: FP } } });
const warn = s6.$('ad-ldaps-anker');
check('Anker passt (StartTLS, 389): keine Warnung', warn.hidden === true);
s6.umlegen(true);
check('LDAPS gewaehlt: Warnung sichtbar', warn.hidden === false);
check('Warnung nennt alt und neu', warn.textContent.includes('dc.firma.local:389') && warn.textContent.includes('dc.firma.local:636'), warn.textContent);
s6.umlegen(false);
check('zurueck auf StartTLS: Warnung wieder weg', warn.hidden === true);
s6.tippen('dc-neu.firma.local');
check('anderer Server: Warnung (Anker gilt fuer einen anderen Host)', warn.hidden === false);
let s6b = await seite({ status: { server: 'dc.firma.local', tls_anker: {} } });
s6b.umlegen(true);
check('ohne Anker: keine Warnung (nichts, was ungueltig wuerde)', s6b.$('ad-ldaps-anker').hidden === true);
let s6c = await seite({ status: { server: 'ldaps://DC.firma.local', tls_anker: { host: 'dc.firma.local', port: 636, fingerprint: FP } } });
check('LDAPS mit passendem Anker (Gross/Klein egal): keine Warnung', s6c.$('ad-ldaps-anker').hidden === true);

// ── 7. i18n ───────────────────────────────────────────────────────────────
section('7. Texte in DE und EN');
const I18N = lies('frontend/js/i18n.js');
const html = lies('frontend/settings.html');
const schl = ['security.ad_ldaps_an', 'security.ad_ldaps_aus', 'security.ad_ldaps_hint', 'security.ad_ldaps_anker'];
for (const k of schl) {
    const n = (I18N.match(new RegExp("'" + k.replace(/\./g, '\\.') + "'\\s*:", 'g')) || []).length;
    check(k + ' in DE und EN (2x)', n === 2, n);
}
for (const k of schl.slice(0, 3)) check(k + ' im Markup per data-i18n', html.includes('data-i18n="' + k + '"'));
s.w.setLang && s.w.setLang('en');
check('Warntext folgt der Sprache (EN)', s.w.t('security.ad_ldaps_anker').startsWith('The pinned'));

check('keine JS-Fehler in allen Laeufen', [s, s2, s3, s5, s6, s6b, s6c].every(x => x.fehler.length === 0),
      [s, s2, s3, s5, s6, s6b, s6c].map(x => x.fehler.join('|')).join(' / '));

clearTimeout(WACH);
BILANZ = true;
console.log(`\n${ok} OK, ${fail} FAIL`);
for (const x of [s, s2, s3, s5, s6, s6b, s6c]) x.w.close();
process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
