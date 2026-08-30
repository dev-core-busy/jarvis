#!/usr/bin/env node
/**
 * Oberflaeche des E-Mail-Skills.
 *
 * Geprueft wird gegen die ECHTEN Dateien (email.html, email_portal.js,
 * settings.html, email.js, i18n.js, app.js, portal.html) – ein Test, der sein
 * Markup selbst baut, prueft nur seine eigene Annahme (Lehre aus dem
 * Medien-Kontextmenue, 2026-08-10).
 *
 * Teil 1  Benutzerseite /email: Berechtigungs-Weiche, Konto, Kennwort-Regel
 * Teil 2  Regeln: Liste, wanderndes Formular, Bereichs-Auswahl, Zeilen-Schalter
 * Teil 3  Protokoll
 * Teil 4  Einstellungs-Reiter (email.js): zwei Knoepfe = zwei Teilmengen
 * Teil 5  Verdrahtung und Texte (app.js, portal.html, i18n DE+EN, CSS)
 *
 *   node tests/test_email_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const MAIL_HTML = fs.readFileSync(path.join(ROOT, 'frontend/email.html'), 'utf8');
const PORTAL_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/email_portal.js'), 'utf8');
const SET_HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');

/* Schneidet EIN Reiter-Panel aus settings.html.
 *
 * DIE GRENZE IST DAS NAECHSTE PANEL, nicht ein Kommentar weiter unten.
 * GEMELDET 2026-08-30: der SAP-Schnitt endete an "Tab: E-Mail" – seit
 * zwischendurch die Reiter *Vemas* und *Jira* eingezogen wurden, umfasste er
 * DREI Panels (56.482 statt 22.269 Zeichen) und zaehlte sieben Kaestchen statt
 * vier. Der Test meldete einen Fehler, den es nicht gab. Eine Textmarke in
 * einem fremden Abschnitt ist keine Grenze. */
function reiterPanel(id) {
    const a = SET_HTML.indexOf('id="settings-tab-' + id + '"');
    if (a < 0) return '';
    const rest = SET_HTML.slice(a + 10);
    const m = rest.match(/id="settings-tab-[a-z_]+" class="settings-tab-content"/);
    return m ? SET_HTML.slice(a, a + 10 + m.index) : SET_HTML.slice(a);
}
const ADMIN_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/email.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const SKILLS = fs.readFileSync(path.join(ROOT, 'frontend/js/skills.js'), 'utf8');
const PORTAL_HTML = fs.readFileSync(path.join(ROOT, 'frontend/portal.html'), 'utf8');
const PICKER = fs.readFileSync(path.join(ROOT, 'frontend/js/ldap_picker.js'), 'utf8');
// Symbole (Muelleimer/Kreuz) – im Browser das ERSTE Skript jeder Seite.
// Module wie chat.js/knowledge.js rufen JarvisIcons.trash() beim Rendern auf;
// ohne diese Zeile bricht das Zeichnen mit 'JarvisIcons is not defined' ab.
const ICONS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

// Der Bereichskatalog kommt UEBERSETZT vom Server (Name und Hinweis stehen dort
// neben der Werkzeugliste, damit Text und Wirkung nicht auseinanderlaufen). Die
// Attrappe bildet deshalb BEIDE Sprachen ab – eine Attrappe, die nur Deutsch
// kennt, koennte den gemeldeten Fehler gar nicht zeigen.
const BEREICHE = [
    { id: 'mail', name: 'E-Mail (Pflicht)', hinweis: 'Lesen, antworten…', freigegeben: true, pflicht: true },
    { id: 'wissen', name: 'Wissensdatenbank (lesend)', hinweis: 'Für Antworten…', freigegeben: true, pflicht: false },
    { id: 'fach', name: 'Interne Fachsysteme (lesend)', hinweis: 'Tickets…', freigegeben: false, pflicht: false },
    { id: 'voll', name: 'Voller Werkzeugkasten', hinweis: 'ACHTUNG…', freigegeben: false, pflicht: false }
];
const BEREICHE_EN = [
    { id: 'mail', name: 'Email (required)', hinweis: 'Read, reply…', freigegeben: true, pflicht: true },
    { id: 'wissen', name: 'Knowledge base (read)', hinweis: 'For answers…', freigegeben: true, pflicht: false },
    { id: 'fach', name: 'Internal systems (read)', hinweis: 'Tickets…', freigegeben: false, pflicht: false },
    { id: 'voll', name: 'Full toolset', hinweis: 'CAUTION…', freigegeben: false, pflicht: false }
];
const katalog = (url) => (/[?&]lang=en\b/.test(String(url)) ? BEREICHE_EN : BEREICHE);

// Der Stilname ist FREITEXT des Benutzers – einer der beiden traegt deshalb
// eine XSS-Nutzlast (er landet in einer Liste und in einem <option>).
const STILE = [
    { id: 's1', name: 'Förmlich', text: 'Sie-Form. Mit freundlichen Grüßen', standard: true },
    { id: 's2', name: '<img src=x onerror=alert(1)>', text: 'Du-Form.', standard: false }
];

const KONTO = {
    vorhanden: true, adresse: 'a.bender@nexus.int', benutzer: 'NEXUS\\a.bender',
    kanal: '', aktiv: true, passwort_gesetzt: true, ordner_eingang: 'Posteingang',
    ordner_entwuerfe: '', ordner_gesendet: '', letzter_erfolg: 1754990000,
    letzter_fehler: '', stile: JSON.parse(JSON.stringify(STILE)), max_stile: 12
};

const REGELN = [
    { id: 'r1', owner: 'a.bender', name: 'Rechnungen', enabled: true, ordner: 'INBOX',
      prompt: 'Pruefe auf Rechnung', bereiche: ['mail', 'wissen'], intervall_min: 5,
      max_je_lauf: 3, nur_ungelesen: true, markiere_gelesen: false,
      von_filter: 'rechnung@', betreff_filter: '', letzter_lauf: 1754990500 },
    { id: 'r2', owner: 'a.bender', name: '<img src=x onerror=alert(1)>', enabled: false,
      ordner: 'Archiv', prompt: 'p', bereiche: ['mail'], intervall_min: 60,
      max_je_lauf: 1, letzter_lauf: 0 }
];

/* ── Gemeinsame Umgebung fuer die Benutzerseite ──────────────────────────── */
function bauePortal(opt) {
    opt = opt || {};
    const dom = new JSDOM(MAIL_HTML, { url: 'https://x/email', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    let regeln = JSON.parse(JSON.stringify(opt.regeln || REGELN));
    let konto = JSON.parse(JSON.stringify(opt.konto || KONTO));

    w.fetch = (url, o) => {
        o = o || {};
        const body = o.body ? JSON.parse(o.body) : null;
        rufe.push({ url: String(url), methode: o.method || 'GET', body: body,
                    kopf: (o.headers || {}) });
        // FALLSTRICK: geroutet wird ueber den PFAD, nicht ueber die ganze URL.
        // Ein Mock mit `url === '/api/email/status'` verfehlt jeden Aufruf mit
        // Abfrageteil (seit 2026-08-13 haengt dort `?lang=`) – und ein Mock,
        // der die echte Anfrageform verfehlt, prueft nichts (dieselbe Lehre wie
        // bei der verschachtelten Config-Antwort).
        const pfad = String(url).split('?')[0];
        const gib = (d, status) => Promise.resolve({
            ok: (status || 200) < 400, status: status || 200,
            json: () => Promise.resolve(d)
        });
        if (pfad === '/api/me') {
            return gib({ username: 'nexus\\a.bender', is_admin: false,
                         permissions: { email: opt.darf === false ? false : true } });
        }
        if (pfad === '/api/email/status') {
            return gib({ ok: true, konto: konto, bereiche: katalog(url),
                         server: { kanal: 'auto', ews: true, imap: true, smtp: true },
                         kategorie: 'Jarvis', regeln: regeln.length,
                         grenzen: { max_regeln: 50, min_intervall: 1, max_intervall: 1440,
                                    max_je_lauf: 10, prompt_max: 8000,
                                    max_stile: 12, stil_name_max: 60,
                                    stil_text_max: 2000 } });
        }
        if (pfad === '/api/email/rules' && (o.method || 'GET') === 'GET') {
            return gib({ ok: true, regeln: regeln, bereiche: katalog(url) });
        }
        if (pfad === '/api/email/rules' && o.method === 'POST') {
            if (opt.postFehler) return gib({ ok: false, error: opt.postFehler }, 400);
            regeln = regeln.concat([Object.assign({ id: 'neu', owner: 'a.bender' }, body)]);
            return gib({ ok: true, regel: regeln[regeln.length - 1] });
        }
        if (/\/api\/email\/rules\/[^/]+$/.test(url) && o.method === 'PUT') {
            const id = url.split('/').pop();
            regeln = regeln.map(r => r.id === id ? Object.assign({}, r, body) : r);
            return gib({ ok: true, regel: regeln.filter(r => r.id === id)[0] });
        }
        if (/\/api\/email\/rules\/[^/]+$/.test(url) && o.method === 'DELETE') {
            const id = url.split('/').pop();
            regeln = regeln.filter(r => r.id !== id);
            return gib({ ok: true });
        }
        if (/\/run$/.test(url)) {
            return gib({ ok: true, bericht: { verarbeitet: 1, aktionen: [{ ergebnis: 'Entwurf gespeichert.' }] } });
        }
        if (pfad === '/api/email/styles' && o.method === 'POST') {
            if (opt.stilFehler) return gib({ ok: false, error: opt.stilFehler }, 400);
            konto.stile = konto.stile.concat([
                { id: 'neu', name: body.name, text: body.text, standard: !!body.standard }]);
            return gib({ ok: true, stile: konto.stile });
        }
        if (/\/api\/email\/styles\/[^/]+$/.test(pfad) && o.method === 'PUT') {
            const id = pfad.split('/').pop();
            konto.stile = konto.stile.map(e => e.id === id ? Object.assign({}, e, body) : e);
            if (body.standard) {
                konto.stile = konto.stile.map(e => Object.assign({}, e, { standard: e.id === id }));
            }
            return gib({ ok: true, stile: konto.stile });
        }
        if (/\/api\/email\/styles\/[^/]+$/.test(pfad) && o.method === 'DELETE') {
            const id = pfad.split('/').pop();
            konto.stile = konto.stile.filter(e => e.id !== id);
            return gib({ ok: true, stile: konto.stile });
        }
        if (pfad === '/api/email/account' && o.method === 'POST') {
            if (opt.acctFehler) return gib({ ok: false, error: opt.acctFehler }, 400);
            konto = Object.assign({}, konto, body, { passwort_gesetzt: true });
            delete konto.passwort;
            return gib({ ok: true, konto: konto });
        }
        if (pfad === '/api/email/account' && o.method === 'DELETE') {
            return gib({ ok: true, entfernt: true });
        }
        if (pfad === '/api/email/test') {
            if (opt.testFehler) return gib({ ok: false, error: opt.testFehler }, 400);
            return gib({ ok: true, ergebnis: { kanal: 'ews', postfach: konto.adresse,
                                               eingang_gesamt: 12, eingang_ungelesen: 3 } });
        }
        if (pfad === '/api/email/folders') {
            return gib({ ok: true, ordner: [{ name: 'INBOX', pfad: 'INBOX' },
                                            { name: 'Buchhaltung', pfad: 'Archiv/Buchhaltung' }] });
        }
        if (String(url).indexOf('/api/email/log') === 0) {
            return gib({ ok: true, eintraege: opt.log || [
                { ts: 1754990500, regel: 'Rechnungen', ok: true, mail_von: 'k@x.de',
                  mail_betreff: 'Rechnung 1', ergebnis: 'Entwurf gespeichert.' },
                { ts: 1754990000, regel: 'Rechnungen', ok: false, mail_von: 'b@x.de',
                  mail_betreff: '<b>roh</b>', ergebnis: 'Fehlgeschlagen', testlauf: true }
            ] });
        }
        return gib({ ok: true });
    };
    w.confirm = () => (opt.confirm === undefined ? true : opt.confirm);
    w.eval(I18N);
    w.eval(ICONS_JS);
    w.eval(PORTAL_JS);
    return { dom, w, rufe, hatRegeln: () => regeln, hatKonto: () => konto };
}

const warte = (ms) => new Promise(r => setTimeout(r, ms || 40));

(async () => {

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Benutzerseite: Berechtigung, Konto, Kennwort-Regel');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w } = bauePortal({});
    await warte(60);
    pruefe(!w.document.getElementById('em-app').classList.contains('hidden'),
        'Freigegebener Benutzer sieht den Bereich');
    pruefe(w.document.getElementById('em-adresse').value === 'a.bender@nexus.int',
        'Adresse wird vorbelegt');
    pruefe(w.document.getElementById('em-benutzer').value === 'NEXUS\\a.bender',
        'Anmeldename wird vorbelegt');
    pruefe(w.document.getElementById('em-ord-eingang').value === 'Posteingang',
        'Ordner-Vorgabe wird vorbelegt');
    pruefe(w.document.getElementById('em-passwort').value === '',
        'DAS KENNWORT WIRD NIE VORBELEGT');
    pruefe(w.document.getElementById('em-pw-hint').textContent.indexOf('unver') > -1,
        'der Hinweis sagt: leer lassen = unveraendert');
    pruefe(w.document.getElementById('em-aktiv').checked === true,
        'Aktiv-Haken folgt dem Konto');
    const pill = w.document.getElementById('em-acct-pill');
    pruefe(pill.classList.contains('is-ok') && pill.textContent.indexOf('@') > -1,
        'Zustands-Pille zeigt das verbundene Postfach');
}
{
    // Nicht freigegeben -> Weiterleitung, KEIN Inhalt.
    // jsdom kann `location` nicht ersetzen; erkennbar ist die Navigation daran,
    // dass die App versteckt bleibt (das Ziel deckt die Quelltext-Pruefung ab).
    const { w } = bauePortal({ darf: false });
    await warte(60);
    pruefe(w.document.getElementById('em-app').classList.contains('hidden'),
        'Nicht freigegebener Benutzer sieht den Bereich NICHT');
    pruefe(PORTAL_JS.indexOf("window.location.replace('/portal')") > -1,
        'und wird auf das Portal zurueckgeschickt');
    pruefe(/permissions\s*&&\s*me\.permissions\.email/.test(PORTAL_JS)
        || /me\.permissions\s*&&\s*me\.permissions\.email/.test(PORTAL_JS),
        'die Weiche prueft permissions.email (fail-closed bei fehlendem Feld)');
}
{
    // Leeres Kennwortfeld darf NICHT gesendet werden (sonst Kennwort geloescht)
    const { w, rufe } = bauePortal({});
    await warte(60);
    w.document.getElementById('em-adresse').value = 'neu@nexus.int';
    w.document.getElementById('em-save-acct').click();
    await warte(60);
    const post = rufe.filter(r => r.url === '/api/email/account' && r.methode === 'POST');
    pruefe(post.length === 1, 'genau ein POST auf /api/email/account');
    pruefe(post[0].body && !('passwort' in post[0].body),
        'LEERES Kennwortfeld wird NICHT mitgesendet (sonst waere es geloescht)');
    pruefe(post[0].body.adresse === 'neu@nexus.int', 'die geaenderte Adresse geht mit');
}
{
    const { w, rufe } = bauePortal({});
    await warte(60);
    w.document.getElementById('em-passwort').value = '   ';
    w.document.getElementById('em-save-acct').click();
    await warte(60);
    const post = rufe.filter(r => r.url === '/api/email/account' && r.methode === 'POST')[0];
    pruefe(!('passwort' in post.body),
        'ein Feld mit nur Leerzeichen zaehlt ebenfalls als unveraendert');
}
{
    const { w, rufe } = bauePortal({});
    await warte(60);
    w.document.getElementById('em-passwort').value = 'NeuesKennwort';
    w.document.getElementById('em-save-acct').click();
    await warte(60);
    const post = rufe.filter(r => r.url === '/api/email/account' && r.methode === 'POST')[0];
    pruefe(post.body.passwort === 'NeuesKennwort', 'ein eingegebenes Kennwort geht mit');
    pruefe(w.document.getElementById('em-passwort').value === '',
        'nach dem Speichern ist das Feld wieder leer');
}
{
    const { w, rufe } = bauePortal({});
    await warte(60);
    w.document.getElementById('em-test-acct').click();
    await warte(60);
    pruefe(rufe.some(r => r.url === '/api/email/test' && r.methode === 'POST'),
        'Verbindungstest ruft /api/email/test');
    const st = w.document.getElementById('em-acct-status').textContent;
    pruefe(st.indexOf('ews') > -1, 'der benutzte Kanal wird genannt', st);
    pruefe(w.document.getElementById('em-acct-result').innerHTML.indexOf('12') > -1,
        'die Postfach-Zahlen erscheinen');
}
{
    const { w } = bauePortal({ testFehler: 'Anmeldung abgelehnt – Kennwort pruefen.' });
    await warte(60);
    w.document.getElementById('em-test-acct').click();
    await warte(60);
    const st = w.document.getElementById('em-acct-status');
    pruefe(st.textContent.indexOf('Anmeldung abgelehnt') > -1,
        'ein Fehler wird im Klartext gezeigt, nicht verschluckt');
    pruefe(st.style.color.indexOf('danger') > -1, 'und in der Fehlerfarbe');
}
{
    const { w, rufe } = bauePortal({ confirm: false });
    await warte(60);
    w.document.getElementById('em-del-acct').click();
    await warte(60);
    pruefe(!rufe.some(r => r.methode === 'DELETE'),
        'Abbruch der Rueckfrage loescht die Zugangsdaten NICHT');
}
{
    const { w, rufe } = bauePortal({ confirm: true });
    await warte(60);
    w.document.getElementById('em-del-acct').click();
    await warte(60);
    pruefe(rufe.some(r => r.url === '/api/email/account' && r.methode === 'DELETE'),
        'nach Bestaetigung wird geloescht');
}
{
    const { w } = bauePortal({ konto: Object.assign({}, KONTO, { vorhanden: false, adresse: '', passwort_gesetzt: false }) });
    await warte(60);
    const pill = w.document.getElementById('em-acct-pill');
    pruefe(pill.classList.contains('is-off'), 'ohne Postfach ist die Pille im Warnzustand');
    pruefe(w.document.getElementById('em-pw-hint').textContent.indexOf('Noch kein') > -1,
        'und der Hinweis sagt, dass kein Kennwort gespeichert ist');
}
{
    const { w } = bauePortal({ konto: Object.assign({}, KONTO, { aktiv: false, letzter_fehler: 'LOGIN failed' }) });
    await warte(60);
    pruefe(w.document.getElementById('em-aktiv').checked === false,
        'aktiv=false wird als false angezeigt (nicht ueber Falsyness geraten)');
    pruefe(w.document.getElementById('em-acct-result').innerHTML.indexOf('LOGIN failed') > -1,
        'der letzte Fehler steht am Konto');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('2. Regeln: Liste, wanderndes Formular, Bereichs-Auswahl');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w } = bauePortal({});
    await warte(80);
    const karten = w.document.querySelectorAll('#em-rules .em-rule-card');
    pruefe(karten.length === 2, 'beide Regeln werden gezeichnet', String(karten.length));
    pruefe(karten[1].classList.contains('is-off'),
        'die abgeschaltete Regel ist abgeschwaecht (Deckkraft, keine harte Farbe)');
    pruefe(w.document.querySelector('#em-rules').innerHTML.indexOf('<img src=x') === -1,
        'XSS im Regelnamen wird entschaerft');
    pruefe(w.document.querySelector('#em-rules').textContent.indexOf('onerror') > -1,
        'der Name erscheint als TEXT');
    pruefe(karten[0].textContent.indexOf('INBOX') > -1
        && karten[0].textContent.indexOf('5 min') > -1,
        'Ordner und Intervall stehen in der Zeile');
    pruefe(karten[0].textContent.indexOf('Wissensdatenbank') > -1,
        'die Bereiche werden mit ihrem Anzeigenamen genannt');
}
{
    // Bearbeiten: Formular wird KIND der Karte (eine Box, kein Spalt)
    const { w } = bauePortal({});
    await warte(80);
    const karte = w.document.querySelector('.em-rule-card[data-rid="r1"]');
    karte.querySelector('[data-act="edit"]').click();
    await warte(40);
    const box = w.document.getElementById('em-rule-edit');
    pruefe(box.parentNode === karte, 'das Formular wird KIND der Regel-Karte');
    pruefe(!box.classList.contains('hidden'), 'und ist sichtbar');
    pruefe(w.document.getElementById('em-f-name').value === 'Rechnungen',
        'die Werte der Regel werden vorbelegt');
    pruefe(w.document.getElementById('em-f-prompt').value === 'Pruefe auf Rechnung',
        'das Prompt ist editierbar vorbelegt');
    pruefe(w.document.getElementById('em-f-von').value === 'rechnung@',
        'der Absender-Filter wird vorbelegt');
    pruefe(w.document.getElementById('em-f-unread').checked === true,
        'nur_ungelesen wird vorbelegt');

    // Nur FREIGEGEBENE Bereiche sind waehlbar
    const kaesten = box.querySelectorAll('#em-f-areas input[type="checkbox"]');
    const ids = Array.from(kaesten).map(c => c.value);
    pruefe(ids.length === 2 && ids.indexOf('mail') > -1 && ids.indexOf('wissen') > -1,
        'nur die freigegebenen Bereiche erscheinen');
    pruefe(ids.indexOf('voll') === -1,
        'ein NICHT freigegebener Bereich ist gar nicht waehlbar');
    const mailBox = Array.from(kaesten).filter(c => c.value === 'mail')[0];
    pruefe(mailBox.checked && mailBox.disabled,
        "'mail' ist gesetzt und gesperrt (eine Regel ohne Mail koennte nichts tun)");

    // Zweiter Klick auf denselben Knopf schliesst (Umschalter)
    karte.querySelector('[data-act="edit"]').click();
    await warte(40);
    pruefe(w.document.getElementById('em-rule-edit').classList.contains('hidden'),
        '"Bearbeiten" ist ein Umschalter');
}
{
    // Speichern schickt genau ein PUT mit den Formularwerten
    const { w, rufe } = bauePortal({});
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="edit"]').click();
    await warte(40);
    w.document.getElementById('em-f-name').value = 'Rechnungen neu';
    w.document.getElementById('em-f-prompt').value = 'Neues Prompt';
    w.document.getElementById('em-f-save').click();
    await warte(80);
    const put = rufe.filter(r => r.methode === 'PUT');
    pruefe(put.length === 1 && put[0].url === '/api/email/rules/r1',
        'genau ein PUT auf die eigene Regel');
    pruefe(put[0].body.name === 'Rechnungen neu' && put[0].body.prompt === 'Neues Prompt',
        'Name und Prompt gehen mit');
    pruefe(!('owner' in put[0].body) && !('id' in put[0].body),
        'owner/id werden NIE mitgesendet');
    pruefe(w.document.getElementById('em-rule-edit').classList.contains('hidden'),
        'nach dem Speichern ist das Formular zu');
}
{
    // Neue Regel
    const { w, rufe } = bauePortal({});
    await warte(80);
    w.document.getElementById('em-new-rule').click();
    await warte(40);
    pruefe(w.document.getElementById('em-f-name').value === '',
        'das Formular fuer eine neue Regel ist leer');
    pruefe(w.document.getElementById('em-f-intervall').value === '5',
        'das Intervall ist mit der Vorgabe belegt');
    w.document.getElementById('em-f-name').value = 'Neu';
    w.document.getElementById('em-f-prompt').value = 'P';
    w.document.getElementById('em-f-save').click();
    await warte(80);
    const post = rufe.filter(r => r.url === '/api/email/rules' && r.methode === 'POST');
    pruefe(post.length === 1, 'genau ein POST fuer die neue Regel');
    pruefe(post[0].body.bereiche.indexOf('mail') > -1,
        "'mail' ist immer dabei");
    pruefe(w.document.querySelectorAll('#em-rules .em-rule-card').length === 3,
        'die Liste wird nach dem Anlegen neu gezeichnet');
}
{
    // FALLSTRICK: liegt das Formular in der Liste, darf innerHTML='' es nicht
    // mitloeschen. Nach einem Neuaufbau muss es noch existieren.
    const { w } = bauePortal({});
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="edit"]').click();
    await warte(40);
    w.document.querySelector('.em-rule-card[data-rid="r2"] [data-act="toggle"]').click();
    await warte(80);
    pruefe(!!w.document.getElementById('em-rule-edit'),
        'das Formular ueberlebt den Neuaufbau der Liste (nicht mitgeloescht)');
    const karte = w.document.querySelector('.em-rule-card[data-rid="r1"]');
    pruefe(w.document.getElementById('em-rule-edit').parentNode === karte,
        'und sitzt wieder unter seiner Zeile');
}
{
    // Zeilen-Schalter sendet AUSSCHLIESSLICH enabled
    const { w, rufe } = bauePortal({});
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="toggle"]').click();
    await warte(80);
    const put = rufe.filter(r => r.methode === 'PUT')[0];
    pruefe(Object.keys(put.body).length === 1 && put.body.enabled === false,
        'der Schalter sendet NUR {enabled} (sonst schriebe er den Formularstand mit)');
}
{
    const { w, rufe } = bauePortal({ confirm: false });
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="del"]').click();
    await warte(60);
    pruefe(!rufe.some(r => r.methode === 'DELETE'),
        'Abbruch der Rueckfrage loescht die Regel NICHT');
}
{
    const { w, rufe } = bauePortal({ confirm: true });
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="del"]').click();
    await warte(80);
    pruefe(rufe.some(r => r.url === '/api/email/rules/r1' && r.methode === 'DELETE'),
        'nach Bestaetigung wird die Regel geloescht');
    pruefe(w.document.querySelectorAll('#em-rules .em-rule-card').length === 1,
        'und verschwindet aus der Liste');
}
{
    // Testlauf
    const { w, rufe } = bauePortal({});
    await warte(80);
    w.document.querySelector('.em-rule-card[data-rid="r1"] [data-act="run"]').click();
    await warte(80);
    pruefe(rufe.some(r => /\/api\/email\/rules\/r1\/run$/.test(r.url) && r.methode === 'POST'),
        'der Testlauf ruft /run der eigenen Regel');
    pruefe(w.document.getElementById('em-rules-status').textContent.indexOf('Entwurf') > -1,
        'das Ergebnis des Laufs wird gezeigt');
    pruefe(rufe.filter(r => String(r.url).indexOf('/api/email/log') === 0).length >= 2,
        'nach dem Lauf wird das Protokoll nachgeladen');
}
{
    const { w } = bauePortal({ postFehler: 'Die Regel braucht ein Prompt.' });
    await warte(80);
    w.document.getElementById('em-new-rule').click();
    await warte(40);
    w.document.getElementById('em-f-name').value = 'X';
    w.document.getElementById('em-f-prompt').value = 'Y';
    w.document.getElementById('em-f-save').click();
    await warte(80);
    pruefe(w.document.getElementById('em-f-status').textContent.indexOf('Prompt') > -1,
        'ein Serverfehler erscheint am Formular im Klartext');
    pruefe(!w.document.getElementById('em-rule-edit').classList.contains('hidden'),
        'und das Formular bleibt offen (die Eingabe geht nicht verloren)');
}
{
    // Ordnerliste ist nur Bequemlichkeit: das Formular steht auch ohne sie
    const { w } = bauePortal({});
    await warte(80);
    w.document.getElementById('em-new-rule').click();
    await warte(80);
    pruefe(!!w.document.getElementById('em-f-ordner'),
        'das Ordner-Feld ist ein Freitextfeld (kein Warten auf die Abfrage)');
    const dl = w.document.getElementById('em-ordner-liste');
    pruefe(dl && dl.querySelectorAll('option').length === 2,
        'die Ordnerliste wird als Vorschlagsliste nachgetragen');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('3. Protokoll');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w } = bauePortal({});
    await warte(80);
    const zeilen = w.document.querySelectorAll('#em-log .em-log-row');
    pruefe(zeilen.length === 2, 'die Protokolleintraege werden gezeichnet');
    pruefe(zeilen[1].classList.contains('is-bad'),
        'ein fehlgeschlagener Lauf ist gekennzeichnet');
    pruefe(zeilen[1].textContent.indexOf('Test') > -1,
        'ein Testlauf traegt ein Abzeichen');
    pruefe(w.document.getElementById('em-log').innerHTML.indexOf('<b>roh</b>') === -1,
        'Betreffzeilen werden entschaerft (Fremdtext!)');
    pruefe(w.document.getElementById('em-log-status').textContent.indexOf('2') > -1,
        'die Anzahl wird genannt');
}
{
    const { w, rufe } = bauePortal({ log: [] });
    await warte(80);
    pruefe(w.document.querySelector('#em-log .em-empty') !== null,
        'ein leeres Protokoll sagt das im Klartext');
    const vorher = rufe.length;
    w.document.getElementById('em-log-reload').click();
    await warte(60);
    pruefe(rufe.length > vorher, 'der Aktualisieren-Knopf laedt neu');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('4. Einstellungs-Reiter: zwei Knoepfe, zwei Teilmengen');
/* ═══════════════════════════════════════════════════════════════════════ */
function baueReiter(opt) {
    opt = opt || {};
    const dom = new JSDOM(SET_HTML, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    w.fetch = (url, o) => {
        o = o || {};
        rufe.push({ url: String(url), methode: (o.method || 'GET'),
                    body: o.body ? JSON.parse(o.body) : null });
        const pfad = String(url).split('?')[0];   // siehe Mock oben: Abfrageteil abtrennen
        const gib = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
        if (pfad === '/api/skills/email/config') {
            // WICHTIG: der echte Endpunkt antwortet VERSCHACHTELT ({config: …}),
            // siehe main.py::get_skill_config. Die erste Fassung dieses Mocks
            // lieferte die Felder flach – deshalb fiel der Ladefehler im Modul
            // (`c.ews_url` statt `c.config.ews_url`) hier NICHT auf, sondern erst
            // dem Benutzer ("die EWS-URL wird nicht gespeichert", 2026-08-12).
            // EIN MOCK, DER DIE ECHTE ANTWORTFORM VERFEHLT, PRUEFT NICHTS.
            return gib({ config: {
                kanal: 'auto', ews_url: 'https://mail.firma.de/EWS/Exchange.asmx',
                autodiscover: false, auth_typ: 'ntlm', verify_ssl: false,
                imap_host: 'imap.firma.de', imap_port: 993, imap_ssl: true,
                smtp_host: 'smtp.firma.de', smtp_port: 587, smtp_starttls: true,
                ordner_eingang: 'INBOX', zeitlimit: 30, takt_sekunden: 60,
                bereiche: 'mail,wissen' } });
        }
        if (pfad === '/api/email/admin/overview') {
            return gib({ ok: true, skill_aktiv: true, bereiche: katalog(url),
                         freigegeben: ['mail', 'wissen'], kategorie: 'Jarvis',
                         freigabe: { users: 'a.bender', group: '' },
                         regeln_gesamt: 3,
                         konten: opt.konten || [
                             { benutzer: 'nexus\\a.bender', benutzer_norm: 'a.bender',
                               adresse: 'a.bender@nexus.int', aktiv: true,
                               passwort_gesetzt: true, letzter_erfolg: 1754990000,
                               letzter_fehler: '', regeln: 3, regeln_aktiv: 2 },
                             { benutzer: 'nexus\\<script>x</script>', benutzer_norm: 'boese',
                               adresse: 'b@x.de', aktiv: false, passwort_gesetzt: false,
                               letzter_erfolg: 0, letzter_fehler: 'LOGIN failed',
                               regeln: 0, regeln_aktiv: 0 }
                         ] });
        }
        if (pfad === '/api/email/admin/areas') {
            return gib({ ok: true, bereiche: (o.body ? JSON.parse(o.body).bereiche : []) });
        }
        if (pfad === '/api/email/admin/explore') {
            if (opt.expFehler) {
                return Promise.resolve({ ok: false, status: 400,
                    json: () => Promise.resolve({ ok: false, error: opt.expFehler }) });
            }
            return gib({ ok: true, benutzer: 'a.bender', ergebnis: {
                kanal: 'ews',
                test: { postfach: 'a.bender@nexus.int', server_version: 'Exchange 2019',
                        ews_url: 'https://mail.firma.de/EWS/Exchange.asmx',
                        eingang_gesamt: 42, eingang_ungelesen: 5 },
                ordner: [{ name: 'INBOX', pfad: 'INBOX', anzahl: 42, ungelesen: 5 },
                         { name: 'Buchhaltung', pfad: 'Archiv/Buchhaltung', anzahl: 7, ungelesen: 0 }],
                nachrichten: [{ datum: '2026-08-12', von: 'k@x.de', betreff: '<b>x</b>' }]
            } });
        }
        return gib({ ok: true });
    };
    w.eval(I18N);
    w.eval(ADMIN_JS);
    return { w, rufe };
}
{
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    pruefe(w.document.getElementById('em-ews-url').value.indexOf('mail.firma.de') > -1,
        'die Serverdaten werden geladen');
    pruefe(w.document.getElementById('em-autodiscover').checked === false,
        'autodiscover=false erscheint als false (nicht ueber Falsyness geraten)');
    pruefe(w.document.getElementById('em-verify-ssl').checked === false,
        'verify_ssl=false erscheint als false');
    pruefe(w.document.getElementById('em-imap-ssl').checked === true,
        'imap_ssl=true erscheint als true');
    pruefe(w.document.getElementById('em-auth-typ').value === 'ntlm',
        'das Anmeldeverfahren wird uebernommen');

    // Bereichs-Kaesten
    const kaesten = w.document.querySelectorAll('#em-areas input[type="checkbox"]');
    pruefe(kaesten.length === BEREICHE.length, 'ALLE Bereiche erscheinen (auch die gesperrten)');
    const mailBox = Array.from(kaesten).filter(c => c.value === 'mail')[0];
    pruefe(mailBox.checked && mailBox.disabled, "'mail' ist gesetzt und gesperrt");
    pruefe(w.document.getElementById('em-areas').textContent.indexOf('⚠') > -1,
        "der Bereich 'voll' ist als Warnung gekennzeichnet");
}
{
    // REGRESSION 2026-08-12: gemeldet als "die EWS-URL wird nicht gespeichert".
    // Gespeichert WURDE sie – aber `ladeVerbindung` las die Antwort eine Ebene
    // zu hoch (`c.ews_url` statt `c.config.ews_url`), leerte damit jedes Feld,
    // und ein zweites "Speichern" schrieb die Leere fest.
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    pruefe(w.document.getElementById('em-ews-url').value !== '',
        'die geladene EWS-URL steht im Feld (Antwort ist unter .config verschachtelt)');
    pruefe(w.document.getElementById('em-imap-host').value === 'imap.firma.de',
        'auch die uebrigen Textfelder werden belegt');
    pruefe(w.document.getElementById('em-imap-port').value === '993',
        'Zahlenfelder werden belegt');
    // Und der Kreislauf: laden -> speichern -> es geht NICHT verloren
    w.document.getElementById('em-save-conn').click();
    await warte(60);
    const gespeichert = rufe.filter(r => r.url === '/api/skills/email/config'
        && r.methode === 'POST')[0];
    pruefe(gespeichert.body.ews_url === 'https://mail.firma.de/EWS/Exchange.asmx',
        'Laden und direktes Speichern verliert die URL nicht', 
        String(gespeichert.body.ews_url));
    pruefe(gespeichert.body.auth_typ === 'ntlm' && gespeichert.body.autodiscover === false,
        'auch Auswahl und Haken bleiben erhalten');
    pruefe(ADMIN_JS.indexOf('antwort.config') > -1 || /\(antwort && antwort\.config\)/.test(ADMIN_JS),
        'das Modul liest ausdruecklich die verschachtelte Antwort');
}
{
    // Die Hinweistexte duerfen nicht das Gegenteil des Verhaltens versprechen
    // (dieselbe Fehlerklasse wie WA_TASK_PROMPT): eine eingetragene URL GEWINNT
    // jetzt gegen den Autodiscover-Haken.
    const panel2 = reiterPanel('email');
    pruefe(panel2.indexOf('den Haken entfernen und die URL eintragen') === -1,
        'der alte, falsche Hinweis ist weg');
    pruefe(panel2.indexOf('eingetragene Adresse wird immer benutzt') > -1,
        'der Hinweis sagt, dass eine eingetragene URL gewinnt');
    pruefe(panel2.indexOf('Hostname') > -1,
        'und dass der Hostname genuegt');
    const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'skills/email/skill.json'), 'utf8'));
    pruefe(manifest.config_schema.autodiscover.description.indexOf('gewinnt immer') > -1,
        'auch das Manifest beschreibt den Vorrang richtig');
}
{
    // ZWEI KNOEPFE, ZWEI TEILMENGEN
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    w.document.getElementById('em-save-conn').click();
    await warte(60);
    const conn = rufe.filter(r => r.url === '/api/skills/email/config' && r.methode === 'POST')[0];
    pruefe(!!conn, 'Verbindung speichern ruft die Skill-Config');
    pruefe(!('bereiche' in conn.body),
        'der Verbindungs-Knopf sendet NIE bereiche (sonst ueberschriebe er die Freigabe)');
    pruefe(conn.body.ews_url.indexOf('mail.firma.de') > -1, 'die Serverdaten gehen mit');
    pruefe(typeof conn.body.autodiscover === 'boolean',
        'Haken werden als echte Wahrheitswerte gesendet');
    pruefe(typeof conn.body.imap_port === 'number', 'Ports werden als Zahl gesendet');
}
{
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    Array.from(w.document.querySelectorAll('#em-areas input[type="checkbox"]'))
        .filter(c => c.value === 'fach')[0].checked = true;
    w.document.getElementById('em-save-areas').click();
    await warte(60);
    const areas = rufe.filter(r => r.url === '/api/email/admin/areas')[0];
    pruefe(!!areas && areas.methode === 'POST', 'Freigabe speichern ruft den eigenen Endpunkt');
    pruefe(Object.keys(areas.body).length === 1 && Array.isArray(areas.body.bereiche),
        'der Freigabe-Knopf sendet NUR bereiche');
    pruefe(areas.body.bereiche.indexOf('fach') > -1 && areas.body.bereiche.indexOf('mail') > -1,
        'die Auswahl geht samt Pflicht-Bereich mit');
    pruefe(!rufe.some(r => r.url === '/api/skills/email/config' && r.methode === 'POST'),
        'und der Freigabe-Knopf schreibt KEINE Serverdaten');
}
{
    const { w } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    const tab = w.document.getElementById('em-accounts');
    pruefe(tab.textContent.indexOf('a.bender@nexus.int') > -1, 'die Konten werden gelistet');
    pruefe(tab.textContent.indexOf('2 / 3') > -1, 'aktive und gesamte Regelzahl erscheinen');
    pruefe(tab.innerHTML.indexOf('<script>') === -1, 'XSS im Benutzernamen wird entschaerft');
    pruefe(tab.textContent.indexOf('LOGIN failed') > -1, 'ein Konto-Fehler ist sichtbar');
    pruefe(tab.textContent.indexOf('kein Kennwort') > -1,
        'ein Konto ohne Kennwort ist erkennbar');
    pruefe(w.document.getElementById('em-acc-count').textContent.indexOf('2') > -1,
        'die Anzahl steht in der Kopfzeile (der Container kann zu sein)');
    // Der Reiter darf keine Regel-Inhalte zeigen
    pruefe(tab.textContent.indexOf('Pruefe auf Rechnung') === -1,
        'der Reiter zeigt KEINE Regel-Prompts (die gehoeren dem Benutzer)');
    const sel = w.document.getElementById('em-exp-user');
    pruefe(sel.options.length === 2, 'der Explorer bietet die hinterlegten Konten an');
    pruefe(sel.options[0].value === 'a.bender',
        'und benutzt den normalisierten Namen als Wert');
}
{
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(80);
    w.document.getElementById('em-explore').click();
    await warte(80);
    const exp = rufe.filter(r => r.url === '/api/email/admin/explore')[0];
    pruefe(!!exp && exp.methode === 'POST', 'der Explorer ruft seinen Endpunkt');
    pruefe(exp.body.benutzer === 'a.bender', 'mit dem gewaehlten Benutzer');
    pruefe(!('passwort' in exp.body) && !('adresse' in exp.body),
        'der Explorer sendet NIE Zugangsdaten (kein Anmelde-Werkzeug)');
    const res = w.document.getElementById('em-exp-result');
    pruefe(res.textContent.indexOf('Exchange 2019') > -1, 'die Serverangabe erscheint');
    pruefe(res.textContent.indexOf('Archiv/Buchhaltung') > -1,
        'der Ordnerbaum erscheint mit vollem Pfad');
    pruefe(res.innerHTML.indexOf('<b>x</b>') === -1, 'Betreffzeilen werden entschaerft');
    pruefe(w.document.getElementById('em-exp-status').textContent.indexOf('ews') > -1,
        'der benutzte Kanal wird genannt');
}
{
    const { w } = baueReiter({ expFehler: 'Fuer diesen Benutzer ist kein Postfach hinterlegt.' });
    w.EmailAdmin.onShow();
    await warte(80);
    w.document.getElementById('em-explore').click();
    await warte(80);
    pruefe(w.document.getElementById('em-exp-status').textContent.indexOf('kein Postfach') > -1,
        'ein Explorer-Fehler erscheint im Klartext');
    pruefe(w.document.getElementById('em-explore').disabled === false,
        'der Knopf wird danach wieder freigegeben');
}
{
    const { w } = baueReiter({ konten: [] });
    w.EmailAdmin.onShow();
    await warte(80);
    pruefe(w.document.getElementById('em-accounts').textContent.indexOf('Noch kein Postfach') > -1,
        'ohne Konten steht ein erklaerender Text mit dem Weg zur Freigabe');
    pruefe(w.document.getElementById('em-exp-user').options[0].value === '',
        'der Explorer bietet dann kein Konto an');
}
{
    // onShow ist idempotent (Reiter-Klick UND openModal rufen es)
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(60);
    w.EmailAdmin.onShow();
    await warte(60);
    w.document.getElementById('em-save-areas').click();
    await warte(60);
    pruefe(rufe.filter(r => r.url === '/api/email/admin/areas').length === 1,
        'onShow ist idempotent (kein doppelt gebundener Knopf)');
}
{
    // Klapp-Container: PROJEKT-MUSTER (kb-collapse-header + h3 links, Pfeil
    // rechts), verdrahtet ueber app.js::_collapseInit. Die erste Fassung hatte
    // eine eigene Logik mit eigenem Markup – dabei stand der Titel RECHTS, weil
    // `.kb-section-header` `justify-content: space-between` setzt (im Screenshot
    // vom 2026-08-12 gesehen, jsdom rechnet kein Layout).
    ['conn', 'areas', 'explore', 'accounts'].forEach(function (s) {
        const hdr = SET_HTML.indexOf('id="em-sect-' + s + '-hdr"');
        pruefe(hdr > -1, 'Kopfzeile em-sect-' + s + '-hdr existiert');
        pruefe(SET_HTML.indexOf('id="em-sect-' + s + '-body"') > -1,
            'Koerper em-sect-' + s + '-body existiert');
        pruefe(SET_HTML.indexOf('id="em-sect-' + s + '-tog"') > -1,
            'Umschalter em-sect-' + s + '-tog existiert');
    });
    const panel = reiterPanel('email');
    pruefe((panel.match(/kb-collapse-header/g) || []).length === 4,
        'alle vier Container nutzen das Projekt-Muster kb-collapse-header');
    pruefe(panel.indexOf('data-em-sect') === -1,
        'die eigene Klapp-Verdrahtung ist verschwunden');
    // Geprueft wird die POSITION, nicht der Wortlaut des Tags: seit der
    // Uebersetzung traegt jedes <h3> ein data-i18n-Attribut, und ein Test auf
    // '<h3>' schlaegt dann an der eigenen Verbesserung an.
    const kopfzeilen = [...panel.matchAll(/kb-collapse-header[^>]*>\s*<(\w+)/g)]
        .map(m => m[1]);
    pruefe(kopfzeilen.length === 4 && kopfzeilen.every(t => t === 'h3'),
        'der Titel steht als <h3> zuerst (sonst schiebt space-between ihn nach rechts)',
        JSON.stringify(kopfzeilen));
    pruefe(APP.indexOf('_initEmailCollapse') > -1 && APP.indexOf('window.initEmailCollapse') > -1,
        'app.js registriert die vier Container bei _collapseInit');
    pruefe(ADMIN_JS.indexOf('window.initEmailCollapse') > -1,
        'email.js benutzt die zentrale Klapp-Logik statt einer eigenen');

    // Kontrollkaestchen: Projekt-Muster + scoped CSS gegen .form-group label
    pruefe((panel.match(/label class="checkbox-group"/g) || []).length === 4,
        'Kontrollkaestchen nutzen .checkbox-group (Muster des SAP-Reiters)');
    const CSS = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');
    // GLOBAL (Vorgabe des Nutzers 2026-08-12): `.form-group label.checkbox-group`
    // ohne Reiter-Praefix. Der Wirkungsbereich bleibt der Konfliktfall –
    // Kaestchen INNERHALB einer .form-group; ausserhalb war nie etwas kaputt.
    pruefe(/(^|\n)\.form-group label\.checkbox-group \{/.test(CSS),
        'die Regel gilt global fuer .form-group label.checkbox-group');
    pruefe(CSS.indexOf('#settings-tab-email .form-group label.checkbox-group') === -1
        && CSS.indexOf('#settings-tab-sap .form-group label.checkbox-group') === -1,
        'die Reiter-Praefixe sind heraus (keine Doppelpflege)');
    const regel = CSS.slice(CSS.indexOf('.form-group label.checkbox-group {'));
    ['display: flex', 'text-transform: none', 'gap:'].forEach(function (teil) {
        pruefe(regel.slice(0, 260).indexOf(teil) > -1, 'die Regel setzt ' + teil);
    });
    // Der SAP-Reiter war der Anlass fuer die Ausweitung: dort standen dieselben
    // Kaestchen gross geschrieben und ohne Abstand.
    //
    // GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT EINE ZAHL: "es sind genau vier"
    // meldet beim fuenften Kaestchen einen Fehler, den es nicht gibt – eine
    // feste Zahl in einem Test ist eine Zeitbombe (Register). Die Aussage, auf
    // die es ankommt, lautet: JEDES Kaestchen des Reiters folgt dem Muster.
    const SAP_PANEL = reiterPanel('sap');
    // DER SCHNITT WIRD SELBST GEPRUEFT. Ohne das bliebe eine zu weite Grenze
    // unbemerkt, solange die fremden Panels zufaellig demselben Muster folgen –
    // genau so war der alte Schnitt zwei Reiter lang unauffaellig, bis der
    // Kaestchen-Zaehler ploetzlich sieben meldete.
    ['email', 'sap'].forEach(function (id) {
        const teil = reiterPanel(id);
        pruefe(teil.length > 0 && (teil.match(/class="settings-tab-content"/g) || []).length === 1,
            'reiterPanel(' + id + ') schneidet GENAU EIN Panel',
            String((teil.match(/class="settings-tab-content"/g) || []).length));
    });
    pruefe(SAP_PANEL.indexOf('sap-conn-type') > -1
        && SAP_PANEL.indexOf('vemas-verify-ssl') === -1
        && SAP_PANEL.indexOf('jvorl-global') === -1,
        'der SAP-Schnitt enthaelt den SAP-Reiter und keinen fremden');
    const sapAlle = (SAP_PANEL.match(/type="checkbox"/g) || []).length;
    const sapMuster = (SAP_PANEL.match(
        /<label class="checkbox-group"[^>]*>\s*<input[^>]*type="checkbox"/g) || []).length;
    pruefe(sapAlle > 0, 'der SAP-Reiter hat ueberhaupt Kontrollkaestchen', String(sapAlle));
    pruefe(sapAlle === sapMuster,
        'im SAP-Reiter nutzt JEDES Kaestchen .checkbox-group',
        sapMuster + ' von ' + sapAlle);
    // Inline gesetzte Werte muessen weiter gewinnen, sonst rutschen die
    // Branding-Radios untereinander bzw. verlieren die Profil-Kaestchen ihr flex:1.
    pruefe(SET_HTML.indexOf('style="display:inline-flex;gap:6px;margin-right:18px;"') > -1,
        'die Branding-Radios behalten ihr Inline-display:inline-flex');
    pruefe(regel.slice(0, 260).indexOf('!important') === -1,
        'die Regel benutzt KEIN !important (sonst schluege sie die Inline-Styles)');
    pruefe(CSS.indexOf('.em-area-grid') > -1 && panel.indexOf('class="em-area-grid"') > -1,
        'die Bereichs-Kaesten haben eine eigene Klasse (.role-tools ist fuer kurze Namen)');
    pruefe(panel.indexOf('class="role-tools"') === -1,
        'und benutzen NICHT .role-tools (fuenf gequetschte Spalten)');

    // btn-primary hat width:100% – in einer Flex-Zeile braucht es flex:0 0 auto
    pruefe((panel.match(/id="em-save-conn"[^>]*flex:0 0 auto/) || []).length === 1,
        '"Verbindung speichern" hat flex:0 0 auto (sonst ueber die ganze Breite)');
    pruefe((panel.match(/id="em-save-areas"[^>]*flex:0 0 auto/) || []).length === 1,
        '"Freigabe speichern" hat flex:0 0 auto');
}
{
    // Keine Emoji-Icons: sie werden je nach System farbig gerendert und folgen
    // keinem Theme (Regel aus .kb-hdr-btn; im Screenshot fielen ⚡ und 🗑 auf).
    // Geprueft wird auf FARBIG voreingestellte Zeichen (Emoji_Presentation) –
    // NICHT auf den ganzen Symbolbereich: ✓ ✎ ✕ ⚠ sind textuell voreingestellt
    // und genau deshalb erlaubt. Die erste Fassung dieser Pruefung schlug an
    // ihnen falsch an.
    const zeilen = PORTAL_JS.split('\n').filter(z => z.trim().indexOf('//') !== 0);
    const FARBIG = /[\u{1F000}-\u{1FAFF}]|[\u{2600}-\u{26FF}]\u{FE0F}|[⚡✅❌❗⭐⏰⏳⛔]/gu;
    const farbig = zeilen.join('\n').match(FARBIG) || [];
    pruefe(farbig.length === 0,
        'keine farbig voreingestellten Emoji im ausgelieferten Markup', farbig.join(' '));
    ['⏸', '▶', '⟳', '✎'].forEach(function (z) {
        pruefe(PORTAL_JS.indexOf(z) > -1, 'monochromes Zeichen vorhanden: ' + z);
    });
    // Das frueher hier gepruefte ✕ war der LOESCHEN-Knopf. Seit der
    // Symbol-Entscheidung vom 2026-08-19 traegt er den Muelleimer
    // (Muelleimer = loeschen, × = schliessen – frontend/js/icons.js), und ein
    // ✕ gibt es in dieser Datei folgerichtig nicht mehr.
    pruefe(PORTAL_JS.indexOf('JarvisIcons.trash()') > -1,
        'der Loeschen-Knopf holt den Muelleimer aus dem zentralen Modul');
    pruefe(PORTAL_JS.indexOf('✕') === -1,
        'kein ✕ mehr in email_portal.js (es war der Loeschknopf)');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('5. Verdrahtung und Texte');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    pruefe(APP.indexOf('updateEmailTabVisibility') > -1,
        'app.js kennt die Reiter-Sichtbarkeit');
    pruefe((APP.match(/await updateEmailTabVisibility\(\)/g) || []).length === 1,
        'openModal ruft sie auf ("KI & System" ist voreingestellt aktiv – der '
        + 'Klick-Handler allein greift nie)');
    pruefe(APP.indexOf("sec-sub-email") > -1,
        'der Berechtigungsblock wird mit dem Skill ein-/ausgeblendet');
    pruefe(APP.indexOf('window.EmailAdmin') > -1 && APP.indexOf('EmailAdmin.onShow') > -1,
        'der Reiter-Klick startet EmailAdmin.onShow');
    pruefe((SKILLS.match(/window\.updateEmailTabVisibility\(\)/g) || []).length === 3,
        'alle drei Skill-Wechsel-Stellen rufen sie nach');
    pruefe(/email:\s*'email'/.test(SKILLS), 'das Zahnrad des Skills fuehrt in den Reiter');
    pruefe(APP.indexOf('settings-tab-email') > -1, 'das Panel ist in app.js registriert');

    pruefe(SET_HTML.indexOf('id="settings-tab-btn-email"') > -1, 'der Reiter-Knopf existiert');
    pruefe(/id="settings-tab-btn-email"[^>]*display:none/.test(SET_HTML),
        'und startet versteckt (nur bei aktivem Skill sichtbar)');
    pruefe(/id="sec-sub-email"[^>]*display:none/.test(SET_HTML),
        'der Berechtigungsblock startet versteckt');
    pruefe(SET_HTML.indexOf('js/email.js') > -1, 'email.js ist eingebunden');
    pruefe(SET_HTML.indexOf('id="email-allowed-users"') > -1
        && SET_HTML.indexOf('id="email-allowed-group"') > -1,
        'die beiden Freigabefelder existieren');
    pruefe(SET_HTML.indexOf('email_allowed_users:') > -1
        && SET_HTML.indexOf('email_allowed_group:') > -1,
        'sie werden beim Speichern mitgesendet');
    pruefe(SET_HTML.indexOf('d.email_users') > -1 && SET_HTML.indexOf('d.email_group') > -1,
        'und beim Laden vorbelegt');
    pruefe(SET_HTML.indexOf("'email-allowed-users','email-allowed-group'") > -1,
        'die Marken-Listen (Chips) werden fuer beide Felder neu aufgebaut');
    pruefe(PICKER.indexOf("'email-allowed-users'") > -1
        && PICKER.indexOf("'email-allowed-group'") > -1,
        'beide Felder haengen am AD-Picker');
    // Leer = niemand muss dort auch stehen
    const block = SET_HTML.slice(SET_HTML.indexOf('id="sec-sub-email"'),
                                 SET_HTML.indexOf('id="sec-sub-email"') + 3000);
    pruefe(block.indexOf('niemand') > -1, 'der Block sagt "leer = niemand"');
    pruefe(block.indexOf('unprivilegiert') > -1,
        'und dass Regel-Laeufe unprivilegiert sind');

    pruefe(PORTAL_HTML.indexOf('id="pt-card-email"') > -1, 'die Portal-Karte existiert');
    pruefe(/class="pt-card hidden" id="pt-card-email"/.test(PORTAL_HTML),
        'sie startet versteckt');
    pruefe(PORTAL_HTML.indexOf('d.permissions.email') > -1,
        'sie wird ueber permissions.email eingeblendet');

    // role-grid: die Basisklasse ist Pflicht, sonst kein display:grid
    const emailPanel = SET_HTML.slice(SET_HTML.indexOf('id="settings-tab-email"'),
                                      SET_HTML.indexOf('Tab: Kundenverwaltung'));
    pruefe(emailPanel.indexOf('class="role-grid-2"') === -1
        && emailPanel.indexOf('class="role-grid-3"') === -1,
        'role-grid-2/-3 werden nur MIT der Basisklasse role-grid benutzt');
    pruefe(emailPanel.indexOf('class="role-grid role-grid-2"') > -1,
        'die Basisklasse ist gesetzt (sonst fehlt display:grid)');
    pruefe(emailPanel.indexOf('input-group') === -1,
        '.input-group wird nicht benutzt (horizontaler Container, macht Kaestchen unklickbar)');
}
{
    // i18n DE/EN deckungsgleich, keine harten Farben, kein Emoji-Icon
    const deTeil = I18N.slice(0, I18N.indexOf('    en: {'));
    const enTeil = I18N.slice(I18N.indexOf('    en: {'));
    const deKeys = (deTeil.match(/'mail\.[a-z_0-9]+'/g) || []).sort();
    const enKeys = (enTeil.match(/'mail\.[a-z_0-9]+'/g) || []).sort();
    pruefe(deKeys.length > 40, 'es gibt reichlich mail.*-Texte', String(deKeys.length));
    pruefe(deKeys.join() === enKeys.join(), 'alle mail.*-Texte gibt es in DE und EN');
    pruefe(deTeil.indexOf("'portal.card_email'") > -1
        && enTeil.indexOf("'portal.card_email'") > -1,
        'die Kachel-Beschriftung gibt es in beiden Sprachen');

    const css = MAIL_HTML.slice(MAIL_HTML.indexOf('<style>'), MAIL_HTML.indexOf('</style>'));
    const hart = css.match(/#[0-9a-fA-F]{6}/g) || [];
    // #fff ist als Schrift auf dem Akzent-Gradienten zulaessig (wie in sap.html)
    const boese = hart.filter(h => h.toLowerCase() !== '#888899' && h.toLowerCase() !== '#777788');
    pruefe(boese.length === 0,
        'keine harten Farben ausser den uebernommenen Knopf-Grautoenen', boese.join());
    pruefe(css.indexOf('var(--bg-secondary)') > -1 || css.indexOf('var(--bg-glass)') > -1,
        'Flaechen kommen aus Theme-Variablen');
    pruefe(css.indexOf('align-self: flex-start') > -1,
        'die Zustands-Pille wird nicht auf die ganze Breite gezogen');
    pruefe(MAIL_HTML.indexOf('id="btn-theme-toggle"') > -1,
        'der Theme-Knopf traegt die Id, die der Avatar-Schalter erwartet');
    pruefe(MAIL_HTML.indexOf('data-i18n="mail.portal_title"') > -1,
        'der Seitentitel ist uebersetzbar');
    // Alle i18n-Attribute zaehlen, nicht nur `data-i18n=` – Titel und
    // Platzhalter sind genauso benutzersichtbarer Text.
    pruefe((MAIL_HTML.match(/data-i18n[a-z-]*=/g) || []).length >= 28,
        'die Seite ist durchgaengig uebersetzbar (inkl. Titel und Platzhalter)',
        String((MAIL_HTML.match(/data-i18n[a-z-]*=/g) || []).length));
    ['mail.portal_title', 'mail.acct_head', 'mail.rules_head', 'mail.log_head',
     'mail.acct_test', 'mail.rules_new', 'mail.pw_ph'].forEach(function (k) {
        pruefe(MAIL_HTML.indexOf(k) > -1, 'uebersetzbar: ' + k);
    });

    // Reihenfolge der Skripte: email_portal.js NACH i18n.js
    const iP = MAIL_HTML.indexOf('src="/static/js/i18n.js');
    const eP = MAIL_HTML.indexOf('src="/static/js/email_portal.js');
    pruefe(iP > -1 && eP > iP, 'email_portal.js laedt nach i18n.js');
    pruefe(MAIL_HTML.indexOf('js/sessions.js') > -1,
        'sessions.js ist eingebunden (Abmelde-Signal)');
    pruefe(PORTAL_JS.indexOf('JarvisSession') > -1,
        'das Abmelde-Signal geht raus, bevor der Token verworfen wird');
    const lo = PORTAL_JS.slice(PORTAL_JS.indexOf("em-logout-btn"));
    pruefe(lo.indexOf('JarvisSession') < lo.indexOf('removeItem'),
        'und zwar VOR dem Verwerfen des Tokens');

    // Kein optionaler Aufruf auf einen falschen Methodennamen
    const optAufrufe = (PORTAL_JS.match(/\w+\?\.\(\)/g) || []);
    pruefe(optAufrufe.length === 0,
        'keine ?.()-Aufrufe (ein falscher Methodenname waere unsichtbar)');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('6. Sprachwechsel: der Bereichskatalog kommt vom Server');
/* ═══════════════════════════════════════════════════════════════════════ */
// Gemeldet 2026-08-13: die Werkzeug-Bereiche standen auch bei englischer
// Oberflaeche auf Deutsch. Name und Hinweis kommen vom Server, applyLang()
// erreicht sie also nicht – sie muessen NEU GEHOLT werden (Muster aus
// sap_portal.js).
{
    const { w, rufe } = bauePortal({});
    await warte(60);
    pruefe(rufe.some(r => r.url.indexOf('/api/email/status?lang=de') === 0),
        'beim Aufbau wird die Sprache mitgesendet');
    pruefe(rufe.some(r => r.url.indexOf('/api/email/rules?lang=de') === 0),
        'auch beim Abruf der Regeln');

    // Formular oeffnen und Bereichs-Hinweise pruefen
    w.document.getElementById('em-new-rule').dispatchEvent(new w.Event('click'));
    await warte(40);
    const hinweisText = () => w.document.getElementById('em-f-areas').textContent;
    pruefe(hinweisText().indexOf('Für Antworten') > -1,
        'die Bereichs-Hinweise stehen auf Deutsch – MIT Umlaut, nicht "Fuer"');
    pruefe(hinweisText().indexOf('Fuer') === -1,
        'keine ASCII-Umschrift in einem benutzersichtbaren Text');

    // Eingaben machen, dann umschalten
    w.document.getElementById('em-f-name').value = 'Halbfertig';
    w.document.getElementById('em-f-prompt').value = 'Text im Tippen';
    const wissenBox = w.document.querySelectorAll('#em-f-areas input[type=checkbox]')[1];
    wissenBox.checked = true;
    const vorher = rufe.length;

    w._lang = 'en';
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'en' } }));
    await warte(80);

    pruefe(rufe.slice(vorher).some(r => r.url.indexOf('lang=en') > -1),
        'der Katalog wird in der neuen Sprache nachgeholt');
    pruefe(w.document.getElementById('em-f-areas').textContent.indexOf('Knowledge base') > -1,
        'die Bereichsnamen stehen danach auf Englisch');
    pruefe(w.document.getElementById('em-f-name').value === 'Halbfertig'
        && w.document.getElementById('em-f-prompt').value === 'Text im Tippen',
        'ein Sprachwechsel mitten im Tippen verwirft die Eingaben NICHT');
    const nachher = w.document.querySelectorAll('#em-f-areas input[type=checkbox]');
    pruefe(nachher[1] && nachher[1].checked === true,
        'und auch die angehakten Bereiche bleiben stehen');

    // Zweites Ereignis OHNE Sprachwechsel darf nichts nachladen (applyLang
    // feuert es auch beim Seitenaufbau).
    const vor2 = rufe.length;
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'en' } }));
    await warte(60);
    pruefe(rufe.length === vor2,
        'gleiche Sprache = kein zweiter Abruf');
}
{
    // Die Regel-Liste nennt die Bereiche ebenfalls – auch sie muss folgen.
    const { w } = bauePortal({});
    await warte(60);
    pruefe(w.document.getElementById('em-rules').textContent.indexOf('Wissensdatenbank') > -1,
        'die Regelzeile nennt die Bereiche auf Deutsch');
    w._lang = 'en';
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'en' } }));
    await warte(80);
    pruefe(w.document.getElementById('em-rules').textContent.indexOf('Knowledge base') > -1,
        'und nach dem Wechsel auf Englisch');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('7. Einstellungs-Reiter: durchgaengig uebersetzbar');
/* ═══════════════════════════════════════════════════════════════════════ */
// Der Reiter war bis 2026-08-13 fest deutsch. Geprueft wird beides: das
// Markup traegt Schluessel, UND die per JS erzeugten Texte laufen ueber T().
{
    const emailTab = SET_HTML.slice(SET_HTML.indexOf('id="settings-tab-email"'),
                                    SET_HTML.indexOf('id="settings-tab-kundenverwaltung"'));
    // Jeder sichtbare Text steckt in einem Element mit data-i18n(-html) –
    // geprueft ueber die Elemente, nicht ueber Textschnipsel: verschachtelte
    // <b>/<code> gehoeren zum uebersetzten Elterntext.
    const dom = new JSDOM('<div>' + emailTab + '</div>');
    const wurzel = dom.window.document.querySelector('div');
    let ohne = [];
    // Geprueft wird der EIGENE Text eines Elements (direkte Textknoten), nicht
    // sein textContent: ein <label> um ein <span data-i18n> hat selbst keinen
    // Text – wer textContent nimmt, meldet dort einen Fehler, den es nicht gibt
    // (erste Fassung dieses Tests genau so danebengegriffen).
    wurzel.querySelectorAll('*').forEach(el => {
        const eigen = [...el.childNodes]
            .filter(k => k.nodeType === 3).map(k => k.textContent).join('').trim();
        if (!eigen) return;
        if (el.closest('[data-i18n], [data-i18n-html]')) return;   // selbst oder Elternteil
        if (/^[▼▶(){}\[\]·–—&;\s]+$/.test(eigen)) return;           // reine Zeichen
        ohne.push(eigen.slice(0, 40));
    });
    pruefe(ohne.length === 0, 'kein sichtbarer Text ohne i18n-Schluessel im Reiter',
        JSON.stringify(ohne.slice(0, 6)));
    const keys = (emailTab.match(/data-i18n[a-z-]*="(mailadm\.[a-z0-9_]+)"/g) || []).length;
    pruefe(keys >= 45, 'der Reiter ist durchgaengig verschluesselt (' + keys + ' Stellen)');
    pruefe(emailTab.indexOf('data-i18n-placeholder="mailadm.f_sent_ph"') > -1,
        'auch der Platzhalter „leer = keine Kopie" ist uebersetzbar');
    pruefe(SET_HTML.indexOf('data-i18n="settings.tab.email"') > -1,
        'die Reiter-Beschriftung selbst ebenfalls');
    dom.window.close();

    // Alle im Markup benutzten Schluessel muessen in BEIDEN Sprachen stehen
    const benutzt = [...emailTab.matchAll(/data-i18n[a-z-]*="(mailadm\.[a-z0-9_]+)"/g)]
        .map(m => m[1]);
    const deTeil = I18N.slice(0, I18N.indexOf('    en: {'));
    const enTeil = I18N.slice(I18N.indexOf('    en: {'));
    const fehltDe = benutzt.filter(k => deTeil.indexOf("'" + k + "'") < 0);
    const fehltEn = benutzt.filter(k => enTeil.indexOf("'" + k + "'") < 0);
    pruefe(fehltDe.length === 0, 'alle Markup-Schluessel gibt es auf Deutsch', JSON.stringify(fehltDe));
    pruefe(fehltEn.length === 0, 'alle Markup-Schluessel gibt es auf Englisch', JSON.stringify(fehltEn));

    // Und die Schluessel aus email.js ebenso
    const jsKeys = [...ADMIN_JS.matchAll(/T\('([a-z][a-z._0-9]*)'/g)].map(m => m[1]);
    pruefe(jsKeys.length >= 20, 'email.js benutzt T() flaechendeckend (' + jsKeys.length + ')');
    const jsFehlt = jsKeys.filter(k => deTeil.indexOf("'" + k + "'") < 0
                                    || enTeil.indexOf("'" + k + "'") < 0);
    pruefe(jsFehlt.length === 0, 'jeder Schluessel aus email.js ist zweisprachig',
        JSON.stringify([...new Set(jsFehlt)]));
    // Kein Wortlaut mehr DIREKT an melde() – als Rueckfall in T(...) ist er
    // erwuenscht (er ist zugleich die lesbare Vorlage fuer i18n.js), deshalb
    // wird auf das ARGUMENT geprueft, nicht auf das Vorkommen des Textes.
    const direkt = [...ADMIN_JS.matchAll(/melde\([^,]+,\s*'([^']{3,})'/g)].map(m => m[1]);
    pruefe(direkt.length === 0, 'kein fester Text direkt an melde()',
        JSON.stringify(direkt.slice(0, 5)));
}
{
    // ECHTER Sprachwechsel auf dem Markup: applyLang() setzt bei
    // `data-i18n-html` das innerHTML. Fehlt die Auszeichnung in der
    // Uebersetzung, verschwindet der eingebettete <span class="kb-hint"> oder
    // das <code> – ein Schaden, den ein reiner Schluessel-Abgleich NICHT sieht.
    const dom = new JSDOM('<!doctype html><html><body>'
        + SET_HTML.slice(SET_HTML.indexOf('<div id="settings-tab-email"'),
                         SET_HTML.indexOf('id="settings-tab-kundenverwaltung"'))
        + '</body></html>', { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.eval(I18N);
    ['de', 'en'].forEach(lg => {
        w._lang = lg;
        w.applyLang();
        const d = w.document;
        pruefe((d.getElementById('em-ordner-entwuerfe') || {}).placeholder !== undefined,
            '[' + lg + '] Markup steht');
        const drafts = d.querySelector('[data-i18n-html="mailadm.f_drafts"]');
        pruefe(drafts && drafts.querySelector('span.kb-hint'),
            '[' + lg + '] die eingebettete Klammer-Auszeichnung ueberlebt applyLang');
        const url = d.querySelector('[data-i18n-html="mailadm.ews_url_hint"]');
        pruefe(url && url.querySelectorAll('code').length === 2,
            '[' + lg + '] beide <code>-Auszeichnungen im EWS-Hinweis bleiben');
        const intro = d.querySelector('[data-i18n-html="mailadm.intro"]');
        pruefe(intro && intro.querySelectorAll('b').length >= 3 && intro.textContent.length > 120,
            '[' + lg + '] der Einleitungstext bleibt vollstaendig und ausgezeichnet');
        const knopf = d.getElementById('em-save-conn');
        pruefe(knopf && knopf.textContent.trim().length > 3,
            '[' + lg + '] der Speichern-Knopf ist beschriftet: "'
            + (knopf ? knopf.textContent.trim() : '') + '"');
        const ph = d.getElementById('em-ordner-gesendet');
        pruefe(ph && ph.placeholder.length > 3,
            '[' + lg + '] der Platzhalter ist gesetzt: "' + (ph ? ph.placeholder : '') + '"');
    });
    // Und die Sprachen unterscheiden sich wirklich
    w._lang = 'de'; w.applyLang();
    const deTxt = w.document.getElementById('em-save-conn').textContent;
    w._lang = 'en'; w.applyLang();
    const enTxt = w.document.getElementById('em-save-conn').textContent;
    pruefe(deTxt !== enTxt, 'DE und EN liefern verschiedene Texte ("' + deTxt + '" / "' + enTxt + '")');
    w.close();
}
{
    // Der Reiter zeichnet nach einem Sprachwechsel neu (Servertexte!)
    const { w, rufe } = baueReiter({});
    w.EmailAdmin.onShow();
    await warte(60);
    pruefe(rufe.some(r => r.url.indexOf('lang=de') > -1),
        'der Reiter holt die Uebersicht mit Sprache');
    pruefe(w.document.getElementById('em-areas').textContent.indexOf('Wissensdatenbank') > -1,
        'Bereichsnamen auf Deutsch');
    const vorher = rufe.length;
    w._lang = 'en';
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'en' } }));
    await warte(80);
    pruefe(rufe.length > vorher && rufe[rufe.length - 1].url.indexOf('lang=en') > -1,
        'und holt sie bei DE/EN neu');
    pruefe(w.document.getElementById('em-areas').textContent.indexOf('Knowledge base') > -1,
        'danach auf Englisch');
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('6. Stile fuer Antworten (mehrere benannte Vorgaben)');
{
    const { w, rufe } = bauePortal();
    await warte(90);
    const d = w.document;
    const karten = d.querySelectorAll('#em-stile-list .em-stil-card');
    pruefe(karten.length === 2, 'beide Stile stehen in der Liste', String(karten.length));
    pruefe(d.getElementById('em-stile-list').innerHTML.indexOf('<img src=x') < 0,
        'der Stilname wird maskiert (er ist Freitext des Benutzers)');
    pruefe(karten[0].className.indexOf('is-std') > -1 &&
        karten[0].textContent.indexOf('Standard') > -1,
        'der Standard ist an Zeichen UND Text erkennbar, nicht nur an der Farbe');
    pruefe(karten[0].querySelector('[data-act="std"]') === null &&
        karten[1].querySelector('[data-act="std"]') !== null,
        'nur der Nicht-Standard bietet "Als Standard setzen" an');

    // Anlegen: der Knopf oeffnet das Formular, Speichern sendet POST.
    d.getElementById('em-stil-neu').click();
    pruefe(!!d.getElementById('em-s-name'), 'der Knopf oeffnet das Formular');
    d.getElementById('em-s-name').value = 'Kurz & knapp';
    d.getElementById('em-s-text').value = 'Höchstens drei Sätze.';
    d.getElementById('em-s-std').checked = false;
    const vorher = rufe.length;
    d.getElementById('em-s-save').click();
    await warte(60);
    const post = rufe.slice(vorher).filter(r => r.methode === 'POST' &&
        r.url.indexOf('/api/email/styles') === 0)[0];
    pruefe(!!post && post.body.name === 'Kurz & knapp' &&
        post.body.text === 'Höchstens drei Sätze.' && post.body.standard === false,
        'Speichern sendet Name, Text und Standard-Wahl');
    pruefe(d.querySelectorAll('#em-stile-list .em-stil-card').length === 3,
        'die Liste zeigt den neuen Stil sofort');
    pruefe(!d.getElementById('em-s-name'), 'das Formular ist danach zu');

    // Standard umsetzen: NUR das eine Feld senden - ein Merge mit dem
    // Formularstand wuerde sonst offene Eingaben festschreiben.
    const v2 = rufe.length;
    d.querySelector('.em-stil-card[data-stil="s2"] [data-act="std"]').click();
    await warte(60);
    const put = rufe.slice(v2).filter(r => r.methode === 'PUT')[0];
    pruefe(!!put && put.url.indexOf('/api/email/styles/s2') === 0 &&
        Object.keys(put.body).join() === 'standard' && put.body.standard === true,
        'der Standard-Knopf sendet ausschliesslich {standard:true}');

    // Loeschen fragt nach - und nennt die Folge fuer die Regeln.
    const v3 = rufe.length;
    d.querySelector('.em-stil-card[data-stil="s1"] [data-act="del"]').click();
    await warte(60);
    const del = rufe.slice(v3).filter(r => r.methode === 'DELETE')[0];
    pruefe(!!del && del.url.indexOf('/api/email/styles/s1') === 0,
        'Loeschen geht an den eigenen Endpunkt');
    w.close();
}

{
    // Ohne Stile: ein Hinweis statt einer leeren Flaeche.
    const konto = Object.assign({}, KONTO, { stile: [] });
    const { w } = bauePortal({ konto: konto });
    await warte(90);
    pruefe(w.document.querySelector('#em-stile-list .em-empty') !== null,
        'ohne Stile steht ein Hinweis da');
    const dd = w.document;
    dd.querySelector('.em-rule-card [data-act="edit"]').click();
    const s0 = dd.getElementById('em-f-stil');
    // Ohne hinterlegte Stile: "kein Stil" + die automatische Wahl. Der
    // Eintrag "– ohne Stil –" waere hier sinnlos und bleibt weg; die
    // automatische Wahl steht dagegen ueberall zur Verfuegung (Vorgabe des
    // Nutzers 2026-08-19 – keine erfundenen Bedingungen).
    const w0 = s0 && Array.prototype.map.call(s0.options, o => o.value);
    pruefe(!!s0 && s0.options.length === 2 && w0[0] === '' && w0[1] === 'auto',
        'ohne Stile: "kein Stil" + automatische Wahl, aber kein sinnloses "ohne Stil"',
        w0 && w0.join('|'));
    w.close();
}

{
    // DIE TRENNUNG: der Postfach-Knopf darf die Stile nicht anfassen.
    const { w, rufe } = bauePortal();
    await warte(90);
    const d = w.document;
    const vorher = rufe.length;
    d.getElementById('em-save-acct').click();
    await warte(60);
    const post = rufe.slice(vorher).filter(r => r.methode === 'POST' &&
        r.url.indexOf('/api/email/account') === 0)[0];
    pruefe(!!post && !('antwort_vorgabe' in post.body) && !('stile' in post.body),
        'Postfach speichern sendet weder das alte Feld noch die Stilliste',
        JSON.stringify(post && post.body));
    w.close();
}

{
    // Regel-Formular: Auswahlfeld, Vorbelegung, Mitsenden.
    const regeln = JSON.parse(JSON.stringify(REGELN));
    regeln[0].stil = 's2';
    const { w, rufe } = bauePortal({ regeln: regeln });
    await warte(90);
    const d = w.document;
    d.querySelector('.em-rule-card[data-rid="r1"] [data-act="edit"]').click();
    const sel = d.getElementById('em-f-stil');
    pruefe(!!sel, 'das Regel-Formular hat ein Stil-Pulldown');
    const werte = Array.prototype.map.call(sel.options, o => o.value);
    // Der Standard (s1) steht als ERSTE Option mit dem Wert "" – NICHT mit
    // seiner Kennung. Nur so bleibt "nichts ausdruecklich gewaehlt" moeglich,
    // und nur dann greift in einer Regel ein im Prompt genannter Stil.
    pruefe(werte[0] === '' && werte.indexOf('s1') < 0 && werte.indexOf('s2') > 0 &&
        werte[werte.length - 1] === '-',
        'Optionen: Standard (Wert ""), die uebrigen Stile, "ohne Stil"', werte.join('|'));
    pruefe(sel.options[0].textContent === 'Förmlich *',
        'der Standard traegt seinen Namen und ein Sternchen (kein "Standard – Standard")',
        sel.options[0].textContent);
    pruefe(sel.innerHTML.indexOf('<img src=x') < 0, 'auch im Pulldown maskiert');
    pruefe(sel.value === 's2', 'die gespeicherte Wahl ist vorbelegt');

    // Zurueck auf den Standard = "nichts gewaehlt" (leerer Wert).
    sel.value = '';
    let vorher = rufe.length;
    d.getElementById('em-f-save').click();
    await warte(60);
    let put = rufe.slice(vorher).filter(r => r.methode === 'PUT')[0];
    pruefe(!!put && put.body.stil === '',
        'die Standard-Option speichert "" (damit die Prompt-Nennung weiter greift)',
        JSON.stringify(put && put.body.stil));

    // Und eine ausdrueckliche Wahl wird als Kennung gespeichert.
    d.querySelector('.em-rule-card[data-rid="r1"] [data-act="edit"]').click();
    d.getElementById('em-f-stil').value = 's2';
    vorher = rufe.length;
    d.getElementById('em-f-save').click();
    await warte(60);
    put = rufe.slice(vorher).filter(r => r.methode === 'PUT')[0];
    pruefe(!!put && put.body.stil === 's2', 'eine ausdrueckliche Wahl wird mitgespeichert');
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('7. Sicherheits-Erklaerung (was der Bediener tun muss)');
{
    const { w } = bauePortal();
    await warte(90);
    const d = w.document;
    const kasten = d.getElementById('em-help-security');
    const knopf = d.querySelector('[data-help="em-help-security"]');
    pruefe(!!kasten && !!knopf, 'Knopf und Kasten existieren paarweise');
    // data-i18n statt data-i18n-html wuerde die Liste beim ersten Sprachlauf
    // in eine Textwurst verwandeln (applyLang setzt dort textContent).
    pruefe(kasten.hasAttribute('data-i18n-html'),
        'der Kasten traegt data-i18n-html (sonst ist die Auszeichnung nach applyLang weg)');
    pruefe(kasten.parentNode.className.indexOf('em-card-body') > -1,
        'er liegt im Karten-Koerper, nicht verschachtelt in einem Absatz',
        kasten.parentNode.className);
    pruefe(kasten.querySelectorAll('li').length >= 8,
        'die Erklaerung ist eine Liste mit beiden Teilen (tun / System)',
        String(kasten.querySelectorAll('li').length));
    const txt = kasten.textContent;
    // Die vier Aussagen, auf die es fachlich ankommt.
    pruefe(txt.indexOf('Nur von diesen Absendern') > -1,
        'sie nennt das Absender-FELD (nicht das Prompt)');
    pruefe(/Werkzeug/.test(txt), 'sie nennt den Werkzeug-Zuschnitt');
    pruefe(/Protokoll/.test(txt), 'sie verweist aufs Protokoll');
    pruefe(/jede\b/.test(txt) && /Adresse/.test(txt),
        'sie benennt das Restrisiko (Versand an beliebige Adressen)');
    // Aufklappen ueber den vorhandenen ⓘ-Mechanismus.
    knopf.click();
    pruefe(kasten.classList.contains('is-open'), 'ein Klick klappt ihn auf');
    knopf.click();
    pruefe(!kasten.classList.contains('is-open'), 'ein zweiter klappt ihn zu');
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
})();
