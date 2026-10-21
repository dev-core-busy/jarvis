/* Waechter: Unter-Container "alte Benutzerberechtigungen"
 * (Sicherheit -> Berechtigungen, frontend/settings.html + js/settings_ad.js).
 *
 * Die Einzellisten je Bereich (Anmeldung … Administratoren) liegen seit
 * 2026-10-21 zusammengefasst in EINEM zugeklappten Unter-Container; der
 * Regelweg ist die Tabelle "Berechtigungen zuweisen" darueber (seit demselben
 * Tag direkt auf der Seite statt in einem Popup). Gemessen wird an der ECHTEN
 * settings.html mit den ECHTEN Modulen:
 *   1. Struktur als REGEL: JEDER Bereichs-Container des AD-Abschnitts liegt in
 *      "altrechte" – ausser "Verbindung (Domain-Controller)". Keine Liste.
 *   2. Speichern gibt es ZWEIMAL (Verbindung + altrechte), weil derselbe
 *      Vorgang beide Haelften schreibt und der eine Knopf zugeklappt ist.
 *   3. Beide Knoepfe loesen GENAU EINEN Speichervorgang mit dem GANZEN Koerper
 *      aus, und BEIDE Statuszeilen melden das Ergebnis.
 *   4. "Verbindung testen" und der Zertifikats-Baustein liegen im Container
 *      "Verbindung"; die Gewichtung trennt Regelweg (fett) von Altweg (normal).
 *   5. REGEL im Code: der Status laeuft nicht mehr ueber eine einzelne Id.
 *   6. REGEL: die neuen i18n-Schluessel stehen in DE und EN.
 *
 *   node tests/test_altrechte_ui.js
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

// settings_bedienung.js gehoert dazu: gemessen wird der KLICK, nicht der
// direkte Aufruf von window._adSave – die Bindung ueber data-klick ist genau
// der Teil, der bei einem zweiten Knopf schiefgehen kann.
// ⚠ DAS ECHTE sapcert.js, KEINE ATTRAPPE: "Zertifikat pruefen" und der
// Verankert-Hinweis stehen nicht im Markup, der Baustein erzeugt sie. Eine
// Attrappe wuerde genau das bescheinigen, was zu messen ist.
const MODULE = ['frontend/js/i18n.js', 'frontend/js/icons.js', 'frontend/js/sapcert.js',
                'frontend/js/settings_ad.js', 'frontend/js/settings_bedienung.js'];
const AD = {
    configured: true, reachable: true, server: 'dc.firma.local', domain: 'firma.local',
    access_mode: 'users_group',
    allowed_users: 'bob, carla', allowed_group: 'CN=Alle,OU=Groups,DC=firma,DC=local',
    knowledge_editors: 'carla', knowledge_editors_group: '',
    sap_users: '', sap_group: '', vemas_users: '', vemas_group: '',
    internet_users: '', internet_group: '',
    admins: 'admin1', admins_group: '',
    // Ein gesetzter Anker ist die Voraussetzung dafuer, dass der
    // Verankert-Hinweis ueberhaupt entsteht – ohne ihn waere die Pruefung
    // darauf trivial wahr.
    tls_anker: { host: 'dc.firma.local', port: 636, fingerprint: 'AA'.repeat(32),
                 gebunden_am: '2026-10-21T08:00:00Z' }
};
const json = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                          json: () => Promise.resolve(d) });

async function seite(opt) {
    opt = opt || {};
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (e) => fehler.push(String(e && e.message)));
    const dom = new JSDOM(lies('frontend/settings.html'), {
        url: 'https://localhost/settings', runScripts: 'outside-only',
        virtualConsole: vc, pretendToBeVisual: true });
    const w = dom.window;
    const posts = [];
    w.fetch = (u, o) => {
        const p = String(u).split('?')[0];
        if (p === '/api/auth/ad_status') return json(AD);
        if (p === '/api/settings') {
            posts.push(JSON.parse(o.body));
            // Die Antwort darf bewusst erst spaeter kommen: nur so ist der
            // gesperrte Zustand WAEHREND des Speicherns messbar.
            return new Promise(r => setTimeout(
                () => r({ ok: !opt.fehler, status: opt.fehler || 200,
                          json: () => Promise.resolve({}) }), 30));
        }
        return json({});
    };
    w.alert = () => {}; w.confirm = () => true;
    sitzungLaden(w, { token: 'TOK' });
    for (const m of MODULE) w.eval(lies(m));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
    await schlaf(60);
    return { w, d: w.document, fehler, posts, $: (id) => w.document.getElementById(id) };
}

// Alle Statuszeilen des Speichervorgangs, als Texte.
function statusTexte(s) {
    return [].slice.call(s.d.querySelectorAll('.ad-save-status'))
             .map(x => (x.textContent || '').trim());
}
function speicherKnoepfe(s) {
    return [].slice.call(s.d.querySelectorAll('[data-klick="ad-speichern"]'));
}

(async () => {
// ── 1. Struktur ────────────────────────────────────────────────────────────
section('1. Struktur: die Einzellisten liegen in einem Container');
const s = await seite({});
const alt = s.d.querySelector('details.sec-sub[data-sub="altrechte"]');
const abschnitt = s.$('sec-sect-ad-body');
// ⚠ ABBRUCH NUR, WO WIRKLICH NICHTS MESSBAR IST. Dass es den Container GIBT,
// ist eine Zusage und gehoert als FAIL gemeldet, nicht als Exit 2 – sonst ist
// "die Zusage ist weg" von "der Waechter konnte nicht laufen" nicht zu
// unterscheiden, und jede Gegenprobe darauf bliebe stumm.
if (!abschnitt) abbruch('settings.html ohne #sec-sect-ad-body');
if (!s.w._adSave) abbruch('settings_ad.js nicht geladen (kein window._adSave)');
// Wirft nie: ein fehlender Container heisst "liegt nicht darin".
const inAlt = (el) => !!(alt && el && alt.contains(el));
check('der Container "altrechte" existiert', !!alt);

// Positivkontrolle: ohne Bereichs-Container waere jede Aussage unten trivial.
const alleSubs = [].slice.call(abschnitt.querySelectorAll('details.sec-sub[data-sub]'));
check('Positivkontrolle: der AD-Abschnitt hat Bereichs-Container',
      alleSubs.length >= 8, String(alleSubs.length));
check('Positivkontrolle: Bestand geladen (_adGeladen, Feld gefuellt)',
      s.w._adGeladen === true && s.$('ad-allowed-users').value === 'bob, carla',
      s.$('ad-allowed-users').value);

// ⚠ REGEL, KEINE LISTE: eine abgetippte Aufzaehlung der Bereiche ist an dem Tag
// unvollstaendig, an dem jemand einen Bereich hinzufuegt – und die fehlende
// Zeile meldet sich nicht. Gemessen wird die Eigenschaft: alles ausser
// "connection" liegt drin.
const conn = s.d.querySelector('details.sec-sub[data-sub="connection"]');
const draussen = alleSubs
    .filter(x => x !== alt && !inAlt(x))
    .map(x => x.getAttribute('data-sub'));
check('JEDER Bereichs-Container liegt in "altrechte" – ausser "connection"',
      draussen.length === 1 && draussen[0] === 'connection', draussen.join('|'));
check('"connection" existiert und liegt NICHT darin (DC-Daten ohne Aufklappen)',
      !!conn && !inAlt(conn), conn ? 'drin' : '(fehlt)');
check('der Container startet ZU', !!alt && alt.open === false,
      alt ? String(alt.open) : '(fehlt)');

// ── 2. Speichern zweimal ───────────────────────────────────────────────────
section('2. Speichern gibt es zweimal, Verbindung testen bleibt draussen');
const knoepfe = speicherKnoepfe(s);
check('genau ZWEI Speichern-Knoepfe', knoepfe.length === 2, String(knoepfe.length));
check('einer steht im Container "Verbindung"',
      knoepfe.filter(b => conn && conn.contains(b)).length === 1);
check('einer steht in "altrechte" (das ist #ad-save-btn)',
      knoepfe.filter(b => inAlt(b)).length === 1 && inAlt(s.$('ad-save-btn')));
check('beide tragen eine Knopfklasse der Seite',
      knoepfe.length > 0 && knoepfe.every(b => b.classList.contains('kb-btn-action')),
      knoepfe.map(b => b.className).join(' | '));
const testKnopf = s.d.querySelector('[data-klick="ad-testen"]');
check('"Verbindung testen" liegt im Container "Verbindung"',
      !!testKnopf && !!conn && conn.contains(testKnopf) && !inAlt(testKnopf),
      testKnopf ? (inAlt(testKnopf) ? 'in altrechte' : 'ausserhalb beider') : '(fehlt)');
// Ein Ergebnis gehoert an den Knopf, der es ausloest – nicht in einen anderen
// Container, wo es beim Klicken ausserhalb des Sichtfensters liegt.
const testErg = s.$('ad-test-result');
check('die Ergebniszeile steht beim Knopf (gleicher Container)',
      !!testErg && !!conn && conn.contains(testErg),
      testErg ? 'ausserhalb' : '(fehlt)');

// ── 2c. Der Zertifikats-Baustein gehoert zum Domain-Controller ────────────
section('2c. Zertifikat: Hinweistext, Knopf und Verankert-Zeile');
const tlsText = s.d.querySelector('[data-i18n="security.ad_tls_hint"]');
const tlsUeb = s.$('ad-tls-uebergang');
const certBox = s.$('ad-cert');
check('der TLS-Hinweistext liegt im Container "Verbindung"',
      !!tlsText && !!conn && conn.contains(tlsText),
      tlsText ? 'ausserhalb' : '(fehlt)');
check('die Uebergangs-Warnung liegt im Container "Verbindung"',
      !!tlsUeb && !!conn && conn.contains(tlsUeb), tlsUeb ? 'ausserhalb' : '(fehlt)');
check('der Zertifikats-Baustein liegt im Container "Verbindung"',
      !!certBox && !!conn && conn.contains(certBox), certBox ? 'ausserhalb' : '(fehlt)');
// ⚠ GEMESSEN WIRD DAS ERZEUGTE BEDIENELEMENT, NICHT DER LEERE CONTAINER:
// `#ad-cert` steht im Markup, Knopf und Verankert-Zeile entstehen erst, wenn
// sapcert.js eingehaengt hat. Ein Waechter auf die leere Huelle waere gruen,
// waehrend der Benutzer nichts sieht.
const certKnopf = certBox && certBox.querySelector('button.sapcert-btn');
const certAnker = certBox && certBox.querySelector('.sapcert-pinned');
check('Positivkontrolle: sapcert.js hat eingehaengt',
      !!certBox && certBox.dataset.sapcertReady === '1',
      certBox ? String(certBox.dataset.sapcertReady) : '(fehlt)');
check('"' + s.w.t('sapcert.check') + '" steht im Container "Verbindung"',
      !!certKnopf && !!conn && conn.contains(certKnopf)
      && (certKnopf.textContent || '').trim() === s.w.t('sapcert.check'),
      certKnopf ? (certKnopf.textContent || '').trim() : '(fehlt)');
check('der Verankert-Hinweis steht im Container "Verbindung"',
      !!certAnker && !!conn && conn.contains(certAnker)
      && (certAnker.textContent || '').indexOf('dc.firma.local') >= 0,
      certAnker ? (certAnker.textContent || '').trim().slice(0, 60) : '(fehlt)');
check('nichts davon liegt in "altrechte"',
      ![tlsText, tlsUeb, certBox, certKnopf, certAnker].some(inAlt));
check('zwei Statuszeilen (.ad-save-status)',
      s.d.querySelectorAll('.ad-save-status').length === 2,
      String(s.d.querySelectorAll('.ad-save-status').length));

// ── 2b. Gewichtung: der Regelweg traegt die Betonung ───────────────────────
section('2b. Schriftstaerke: Regelweg fett, Altweg normal');
// ⚠ GEMESSEN WIRD DER BERECHNETE WERT, NICHT DIE SCHREIBWEISE IM MARKUP.
// Die Staerke steht deshalb INLINE: `details.sec-sub > summary` setzt 600, und
// eine Ausnahme per Kaskade waere in jsdom nicht verlaesslich messbar – dort
// gewinnt bei zwei passenden Regeln die SPAETERE, nicht die spezifischere.
// ⚠ DER REGELWEG IST SEIT 2026-10-21 KEIN KNOPF MEHR, sondern die Ueberschrift
// ueber der Tabelle, die an seiner Stelle steht (#rmx-open gibt es nicht mehr).
const rmx = s.$('rmx-titel');
const kopf = alt && alt.querySelector(':scope > summary');
const gewicht = (el) => el ? String(s.w.getComputedStyle(el).fontWeight || '') : '(fehlt)';
// Positivkontrolle: das Stylesheet wird ueberhaupt ausgewertet – sonst liefert
// jeder Vergleich unten denselben Vorgabewert und ist trivial.
const andererKopf = s.d.querySelector('details.sec-sub[data-sub="login"] > summary');
check('Positivkontrolle: eine gewoehnliche Kopfzeile ist fett (600)',
      gewicht(andererKopf) === '600', gewicht(andererKopf));
check('"alte Benutzerberechtigungen" ist NORMAL (400)',
      gewicht(kopf) === '400', gewicht(kopf));
check('die Ueberschrift "' + s.w.t('rmx.title') + '" ist FETT (600)',
      gewicht(rmx) === '600', gewicht(rmx));
check('… und sie steht als <h4> da (damit die Suche sie findet)',
      !!rmx && rmx.tagName === 'H4', rmx ? rmx.tagName : '(fehlt)');
check('der alte Oeffnen-Knopf ist weg', s.$('rmx-open') === null);
check('der Altweg ist leichter als der Regelweg',
      Number(gewicht(kopf)) < Number(gewicht(rmx)),
      gewicht(kopf) + ' gegen ' + gewicht(rmx));

// ── 3. Beide Knoepfe: ein Vorgang, ganzer Koerper, beide Meldungen ─────────
section('3. Jeder Knopf schreibt den GANZEN Koerper, beide Zeilen melden');
for (const [wo, btn] of [['Verbindung', knoepfe.find(b => conn && conn.contains(b))],
                         ['altrechte',  knoepfe.find(b => inAlt(b))]]) {
    // Fehlt der Knopf, ist das ein BEFUND – kein Absturz auf `btn.click()`.
    if (!btn) { check(wo + ': Speichern-Knopf vorhanden', false, 'fehlt'); continue; }
    // ⚠ VOR JEDEM KLICK NEU SETZEN: ein erfolgreiches _adSave ruft _adLoad und
    // fuellt die Felder aus der Attrappe zurueck. Einmal vor der Schleife
    // gesetzt, misst der zweite Durchgang die Vorgabewerte – und das sah wie
    // ein Produktbefund aus ("der Koerper traegt die Verbindungsdaten nicht").
    s.$('ad-server').value = 'dc2.firma.local';
    s.$('ad-admins').value = 'admin2';
    s.posts.length = 0;
    btn.click();
    await schlaf(5);
    check(wo + ': beide Knoepfe sind WAEHREND des Speicherns gesperrt',
          speicherKnoepfe(s).every(b => b.disabled === true),
          speicherKnoepfe(s).map(b => String(b.disabled)).join('|'));
    check(wo + ': beide Zeilen melden den Lauf',
          statusTexte(s).length === 2 && statusTexte(s).every(t => t.length > 0),
          statusTexte(s).join(' | '));
    await schlaf(90);
    check(wo + ': GENAU EIN Speichervorgang', s.posts.length === 1, String(s.posts.length));
    const b = s.posts[0] || {};
    check(wo + ': der Koerper traegt die Verbindungsdaten',
          b.ad_server === 'dc2.firma.local', String(b.ad_server));
    check(wo + ': der Koerper traegt die Berechtigungsdaten',
          b.ad_admins === 'admin2', String(b.ad_admins));
    check(wo + ': beide Zeilen melden den Erfolg',
          statusTexte(s).length === 2
          && statusTexte(s).every(t => t === s.w.t('security.ad_saved')),
          statusTexte(s).join(' | '));
    check(wo + ': beide Knoepfe sind danach wieder frei',
          speicherKnoepfe(s).every(b2 => b2.disabled === false));
}
// Der Erfolg verfaellt (3 s) – das ist die Zusage, nicht eine Nebenwirkung.
await schlaf(3200);
check('die Erfolgsmeldung verschwindet von selbst',
      statusTexte(s).every(t => t === ''), statusTexte(s).join(' | '));

// ── 3b. Ein Fehler bleibt stehen, auf BEIDEN Zeilen ────────────────────────
section('3b. Ein Fehler bleibt lesbar stehen');
const sf = await seite({ fehler: 500 });
const kf = speicherKnoepfe(sf);
check('Positivkontrolle: auch im Fehleraufbau zwei Knoepfe', kf.length === 2, String(kf.length));
if (kf.length) kf[0].click();
await schlaf(120);
check('beide Zeilen tragen den Fehler',
      statusTexte(sf).length === 2
      && statusTexte(sf).every(t => t.indexOf('500') >= 0), statusTexte(sf).join(' | '));
await schlaf(3200);
check('der Fehler verschwindet NICHT von selbst',
      statusTexte(sf).every(t => t.indexOf('500') >= 0), statusTexte(sf).join(' | '));
check('beide Knoepfe sind nach dem Fehler wieder frei',
      speicherKnoepfe(sf).every(b => b.disabled === false));
check('keine jsdom-Fehler in beiden Aufbauten',
      s.fehler.length === 0 && sf.fehler.length === 0,
      s.fehler.concat(sf.fehler).slice(0, 2).join(' | '));

// ── 4. REGEL im Code: der Status laeuft nicht ueber eine einzelne Id ───────
section('4. REGEL: kein Status ueber eine einzelne Id');
const quelle = lies('frontend/js/settings_ad.js');
// ⚠ EIN WAECHTER, DER SEINE EIGENE BEGRUENDUNG LIEST, PRUEFT NICHTS:
// Kommentare raus, bevor nach der Id gesucht wird.
const ohneKomm = quelle.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
check('Positivkontrolle: der Kommentarfilter greift',
      ohneKomm.length < quelle.length && ohneKomm.indexOf('window._adSave') >= 0,
      quelle.length + ' -> ' + ohneKomm.length);
check('kein getElementById(\'ad-save-status\') mehr',
      ohneKomm.indexOf("getElementById('ad-save-status')") < 0);
check('kein getElementById(\'ad-save-btn\') mehr',
      ohneKomm.indexOf("getElementById('ad-save-btn')") < 0);
check('gesammelt wird ueber Klick-Marke und Klasse',
      /querySelectorAll\('\[data-klick="ad-speichern"\]'\)/.test(ohneKomm)
      && /querySelectorAll\('\.ad-save-status'\)/.test(ohneKomm));

// ── 5. REGEL: i18n in DE und EN ────────────────────────────────────────────
section('5. REGEL: jeder neue Schluessel in DE und EN');
const i18n = lies('frontend/js/i18n.js');
const sprachen = (k) => (i18n.match(new RegExp("'" + k + "'\\s*:", 'g')) || []).length;
for (const k of ['security.sub_altrechte', 'security.sub_altrechte_hint']) {
    check(k + ' steht zweimal (DE und EN)', sprachen(k) === 2, String(sprachen(k)));
}
// Der Markup-Rueckfall darf dem i18n-Wert nicht widersprechen.
const html = lies('frontend/settings.html');
const m = html.match(/data-i18n="security\.sub_altrechte">([^<]*)</);
check('Positivkontrolle: der Rueckfall steht im Markup', !!m, m ? m[1] : '(fehlt)');
check('Markup-Rueckfall und DE-Wert sind gleich',
      !!m && i18n.indexOf("'security.sub_altrechte':       '" + m[1] + "'") >= 0,
      m ? m[1] : '(fehlt)');

clearTimeout(WACH);
BILANZ = true;
console.log('\n' + (fail ? '\x1b[31m' : '\x1b[32m') + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
