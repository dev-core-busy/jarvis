#!/usr/bin/env node
/**
 * Waechter: Anmeldung ueber den IdP auf der Anmeldemaske (idp_anmeldung.js).
 *
 *  A  EINBINDUNG: settings.html laedt idp_anmeldung.js und settings_idp.js,
 *     der Knopf ist ein LINK auf /api/login/oidc/start (kein Formular – CSP
 *     form-action 'self'), Code-Block ausserhalb des Formulars.
 *  B  VERHALTEN in jsdom auf dem ECHTEN Markup von settings.html, mit den
 *     echten Modulen i18n.js, sitzung.js, idp_anmeldung.js:
 *     Knopf nur bei aktiv:true, Fehlerkennung -> uebersetzter Text und
 *     Adresse aufgeraeumt, anmeldung=idp -> POST einloesen mit Sitzungs-Kopf,
 *     requires_totp -> Code-Block statt Formular, 6 Ziffern -> zweiter POST
 *     mit Code, Erfolg -> Token gespeichert + Weiterleitung auf /portal.
 *  C  TEXTE: jeder login.idp_* / security.idp_* / security.sub_idp*-Schluessel
 *     aus Markup und Modulen steht in DE und EN; der Knopf nennt "(SSO)".
 *  D  AUTOMATISCH ANMELDEN (Haken #idp-auto, 2026-11-19): startet die
 *     IdP-Anmeldung ohne Klick – aber nicht ohne Haken, nicht ohne IdP, nicht
 *     von einer Jarvis-Seite aus (Abmelden), nicht bei Rueckkehr vom IdP,
 *     nicht zweimal binnen einer Minute (Schleife), nicht unter /settings,
 *     und bei mitgebrachtem Token erst, wenn app.js es verworfen hat. Dazu
 *     am Syntaxbaum von app.js: das Ereignis kommt NUR aus der gescheiterten
 *     Tokenpruefung, nicht aus showLoginScreen().
 *  E  EIN SERVERNAME (2026-11-19): meldet der Status einen `ursprung` und
 *     steht die Seite unter einem anderen, wechselt "/" vorab dorthin – vor
 *     dem Haken (localStorage gilt je Ursprung) und vor dem IdP-Start. Nicht
 *     bei gleichem Ursprung, nicht unter /settings, nicht bei Rueckkehr vom
 *     IdP, nicht ein zweites Mal (Marke umgeleitet), bei Token erst nach dem
 *     Ereignis. "Kam vom Abmelden" reist als umgeleitet=2 mit.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const lies = (p) => fs.readFileSync(path.join(REPO, p), 'utf8');

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const ALLE_FEHLER = [];
const warte = (ms) => new Promise(r => setTimeout(r, ms || 30));

const SETTINGS = lies('frontend/settings.html');
const MODUL = lies('frontend/js/idp_anmeldung.js');
const MODUL_ADMIN = lies('frontend/js/settings_idp.js');
const I18N = lies('frontend/js/i18n.js');

// ── A: Einbindung ───────────────────────────────────────────────────────────
console.log('A  Einbindung');
check('settings.html laedt idp_anmeldung.js', /<script src="\/static\/js\/idp_anmeldung\.js\?v=\d+"><\/script>/.test(SETTINGS));
check('settings.html laedt settings_idp.js', /<script src="\/static\/js\/settings_idp\.js\?v=\d+"><\/script>/.test(SETTINGS));
const knopf = SETTINGS.match(/<a id="btn-idp-login"[^>]*>/);
check('Knopf ist ein Link auf /api/login/oidc/start', !!knopf && /href="\/api\/login\/oidc\/start"/.test(knopf[0]));
const formStart = SETTINGS.indexOf('<form id="login-form"');
const formEnde = SETTINGS.indexOf('</form>', formStart);
const totpPos = SETTINGS.indexOf('id="idp-totp"');
check('Code-Block steht AUSSERHALB des Anmeldeformulars', totpPos > 0 && (totpPos < formStart || totpPos > formEnde));
check('Knopf-Bereich ist anfangs verborgen', /<div id="idp-login" hidden>/.test(SETTINGS));
{
    // Struktur am DOM, nicht am Text: was gehoert zur Kennwortanmeldung?
    const d0 = new JSDOM(SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '')).window.document;
    const kb = d0.getElementById('kennwort-bereich');
    check('#kennwort-bereich existiert im Anmeldeformular und ist anfangs SICHTBAR',
          !!kb && kb.closest('#login-form') !== null && !kb.hidden);
    check('Benutzername, Kennwort, Code und Anmeldeknopf liegen im Kennwort-Bereich',
          !!kb && ['login-username', 'login-password', 'totp-row', 'totp-setup', 'login-btn']
              .every(id => kb.contains(d0.getElementById(id))));
    check('Fehlerzeile und IdP-Knopf liegen NICHT im Kennwort-Bereich',
          !!kb && !kb.contains(d0.getElementById('login-error')) && !kb.contains(d0.getElementById('idp-login')));
    const z = d0.getElementById('idp-ad-modus-zeile');
    check('Einstellung "AD-Anmeldung zusaetzlich" anfangs verborgen, mit Schalter',
          !!z && z.hidden && !!d0.getElementById('idp-ad-zusaetzlich') && z.contains(d0.getElementById('idp-ad-zusaetzlich')));
}
const THEME = lies('frontend/css/theme.css');
check('theme.css: .idp-trenner[hidden] { display: none } (sonst ueberstimmt display:flex)',
      /\.idp-trenner\[hidden\]\s*\{\s*display:\s*none/.test(THEME));
{
    // Hauptknopf-Aussehen: zwei Klassen (gewinnt gegen .btn-link aus dem spaeter
    // geladenen style.css), Flaeche in der Akzentfarbe, Schrift aus der Variable.
    const m = THEME.match(/\.btn-idp\.btn-idp-haupt\s*\{([^}]*)\}/);
    check('theme.css: .btn-idp.btn-idp-haupt mit Akzentflaeche und --text-on-accent',
          !!m && /background:\s*var\(--accent\)/.test(m[1]) && /color:\s*var\(--text-on-accent\)/.test(m[1]),
          m ? m[1].trim() : 'Regel fehlt');
}

// ── B: Verhalten ────────────────────────────────────────────────────────────
function seite(url, antworten) {
    const html = SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '');
    const vc = new VirtualConsole();
    const z = { posts: [], koepfe: [], nav: [], fehler: [] };
    vc.on('jsdomError', (e) => { if (/navigation/i.test(String(e && e.message))) z.nav.push(e.message); else z.fehler.push(String(e && e.message)); });
    const dom = new JSDOM(html, { runScripts: 'outside-only', url, virtualConsole: vc,
                                  referrer: antworten.referrer || undefined });
    const w = dom.window;
    z.ziele = [];
    w.addEventListener('error', (e) => z.fehler.push(String(e.message)));
    if (antworten.merk) w.localStorage.setItem('jarvis_idp_ad_modus', antworten.merk);
    if (antworten.auto) w.localStorage.setItem('jarvis_idp_auto', '1');
    if (antworten.token) w.localStorage.setItem('jarvis_token', antworten.token);
    if (antworten.autoZeit) w.sessionStorage.setItem('jarvis_idp_auto_zeit', String(antworten.autoZeit));
    if (antworten.ohneSitzungsspeicher) {
        Object.defineProperty(w, 'sessionStorage', { configurable: true, get() { throw new w.DOMException('gesperrt', 'SecurityError'); } });
    }
    w.fetch = (u, init) => {
        const pfad = String(u).split('?')[0];
        let a = { status: 404, body: {} };
        if (pfad === '/api/login/oidc/status') {
            if (antworten.status === 'nie') return new Promise(() => {});
            if (antworten.status === 'fehler') return Promise.reject(new Error('offline'));
            const body = antworten.aktiv ? { aktiv: true, ad_modus: antworten.modus || 'fallback' } : { aktiv: false };
            if (antworten.ohneModus) delete body.ad_modus;
            if (antworten.aktiv && antworten.ursprung) body.ursprung = antworten.ursprung;
            const ant = { ok: true, status: 200, json: () => Promise.resolve(body) };
            // w.setTimeout: verfaellt mit w.close(), sonst traefe die Antwort ein geschlossenes Fenster.
            return antworten.statusMs ? new Promise(r => w.setTimeout(() => r(ant), antworten.statusMs)) : Promise.resolve(ant);
        }
        if (pfad === '/api/login/oidc/einloesen') {
            z.posts.push(JSON.parse((init && init.body) || '{}'));
            z.koepfe.push((init && init.headers) || {});
            a = antworten.einloesen.shift() || { status: 500, body: {} };
        }
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    for (const f of ['i18n.js', 'sitzung.js']) w.eval(lies('frontend/js/' + f));
    w.eval(MODUL);
    if (w.IdpAnmeldung && w.IdpAnmeldung._navigation) w.IdpAnmeldung._navigation((u) => z.ziele.push(u));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    ALLE_FEHLER.push(z.fehler);
    return { w, z, d: w.document, dom };
}

(async () => {
    console.log('B  Verhalten');
    // Positivkontrolle: das Modul ist geladen
    let s = seite('https://jarvis.test/', { aktiv: true, einloesen: [] });
    await warte(60);
    if (!s.w.IdpAnmeldung) { console.log('ABBRUCH (Exit 2): idp_anmeldung.js nicht geladen'); bilanz = true; process.exit(2); }
    check('aktiv:true -> Knopf sichtbar', s.d.getElementById('idp-login').hidden === false);
    check('ohne Kennung kein Einloesen', s.z.posts.length === 0);
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: false, einloesen: [] });
    await warte(60);
    check('aktiv:false -> Knopf bleibt verborgen', s.d.getElementById('idp-login').hidden === true);
    s.w.close();

    s = seite('https://jarvis.test/?idp_fehler=keine_freigabe', { aktiv: true, einloesen: [] });
    await warte(60);
    const err = s.d.getElementById('login-error');
    check('Fehlerkennung -> Text in #login-error', !err.hidden && err.textContent === 'Keine Anmeldeberechtigung.', err.textContent);
    check('Adresse danach aufgeraeumt', s.w.location.search === '', s.w.location.href);
    s.w.close();

    s = seite('https://jarvis.test/?idp_fehler=%3Cimg%20src%3Dx%3E', { aktiv: true, einloesen: [] });
    await warte(60);
    check('unbekannte Kennung: allgemeiner Text, kein Markup', s.d.querySelector('#login-error img') === null
          && s.d.getElementById('login-error').textContent.length > 0);
    s.w.close();

    s = seite('https://jarvis.test/?anmeldung=idp', { aktiv: true, einloesen: [
        { status: 200, body: { success: false, requires_totp: true, error: '2FA-Code erforderlich' } },
        { status: 200, body: { success: true, token: 'CSRF', username: 'm.muster', is_admin: false } }] });
    await warte(80);
    check('anmeldung=idp -> POST einloesen ohne Code', s.z.posts.length === 1 && !('totp_code' in s.z.posts[0]));
    check('Einloesen mit Sitzungs-Kopf (Cookie-Verfahren)', (s.z.koepfe[0] || {})['X-Jarvis-Sitzung'] === 'cookie',
          JSON.stringify(s.z.koepfe[0]));
    check('requires_totp -> Code-Block sichtbar, Formular verborgen',
          s.d.getElementById('idp-totp').hidden === false && s.d.getElementById('login-form').hidden === true);
    const feld = s.d.getElementById('idp-totp-code');
    feld.value = '12 34 56';
    feld.dispatchEvent(new s.w.Event('input'));
    await warte(80);
    check('6 Ziffern -> zweiter POST mit Code', s.z.posts.length === 2 && s.z.posts[1].totp_code === '123456',
          JSON.stringify(s.z.posts));
    check('Erfolg -> Token gespeichert', s.w.localStorage.getItem('jarvis_token') === 'CSRF'
          && s.w.localStorage.getItem('jarvis_user') === 'm.muster');
    check('Erfolg -> Weiterleitung (Navigation) ausgeloest', s.z.nav.length >= 1);
    s.w.close();

    s = seite('https://jarvis.test/?anmeldung=idp', { aktiv: true, einloesen: [
        { status: 401, body: { success: false, abgelaufen: true, error: 'Die Anmeldung über das Firmenkonto ist abgelaufen.' } }] });
    await warte(80);
    check('abgelaufen -> Meldung im Formular, Formular sichtbar',
          s.d.getElementById('login-form').hidden === false
          && /abgelaufen/.test(s.d.getElementById('login-error').textContent));
    check('abgelaufen -> nichts gespeichert, keine Weiterleitung',
          !s.w.localStorage.getItem('jarvis_token') && s.z.nav.length === 0);
    s.w.close();
    // ── Kennwortanmeldung neben dem IdP ──────────────────────────────────
    const sichtbar = (s) => !s.d.getElementById('kennwort-bereich').hidden;
    const trenner = (s) => !s.d.getElementById('idp-trenner').hidden;
    const haupt = (s) => s.d.getElementById('btn-idp-login').classList.contains('btn-idp-haupt');

    s = seite('https://jarvis.test/', { aktiv: true, modus: 'fallback', einloesen: [] });
    await warte(60);
    check('fallback: Kennwort-Bereich und "oder" verborgen, IdP-Knopf sichtbar',
          !sichtbar(s) && !trenner(s) && s.d.getElementById('idp-login').hidden === false);
    check('fallback: Modus im Browser gemerkt', s.w.localStorage.getItem('jarvis_idp_ad_modus') === 'fallback');
    check('fallback: IdP-Knopf traegt das Hauptknopf-Aussehen (btn-idp-haupt)', haupt(s));
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: true, modus: 'zusaetzlich', einloesen: [] });
    await warte(60);
    check('zusaetzlich: Kennwort-Bereich, "oder" und IdP-Knopf sichtbar',
          sichtbar(s) && trenner(s) && s.d.getElementById('idp-login').hidden === false);
    check('zusaetzlich: IdP-Knopf bleibt Nebenknopf (Hauptknopf ist "Anmelden")', !haupt(s));
    s.w.close();

    // Vorgabe seit 2026-11-19 "zusaetzlich": nur ein AUSDRUECKLICHES fallback verbirgt.
    s = seite('https://jarvis.test/', { aktiv: true, ohneModus: true, einloesen: [] });
    await warte(60);
    check('Status ohne ad_modus: Kennwort-Bereich sichtbar (Vorgabe zusaetzlich, fail-open)',
          sichtbar(s) && s.w.localStorage.getItem('jarvis_idp_ad_modus') === 'zusaetzlich');
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: false, merk: 'fallback', einloesen: [] });
    await warte(60);
    check('IdP aus (trotz altem Merker): Kennwort sichtbar, Merker entfernt',
          sichtbar(s) && s.w.localStorage.getItem('jarvis_idp_ad_modus') === null);
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: true, status: 'fehler', merk: 'fallback', einloesen: [] });
    await warte(60);
    check('Status nicht abrufbar: Kennwort sichtbar (fail-open)', sichtbar(s));
    s.w.close();

    s = seite('https://jarvis.test/?idp_fehler=abgebrochen', { aktiv: true, modus: 'fallback', einloesen: [] });
    await warte(60);
    check('fallback + IdP-Anmeldung gescheitert: Kennwort sichtbar, Meldung steht da',
          sichtbar(s) && trenner(s) && !s.d.getElementById('login-error').hidden);
    check('fallback + gescheitert: IdP-Knopf wieder Nebenknopf', !haupt(s));
    s.w.close();

    s = seite('https://jarvis.test/?anmeldung=idp', { aktiv: true, modus: 'fallback', einloesen: [
        { status: 401, body: { success: false, abgelaufen: true, error: 'abgelaufen' } }] });
    await warte(80);
    check('fallback + Einloesen abgelehnt: Kennwort sichtbar', sichtbar(s));
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: true, modus: 'fallback', statusMs: 300, merk: 'fallback', einloesen: [] });
    await warte(40);
    check('gemerkter fallback: schon VOR der Statusantwort verborgen (kein Aufblitzen)', !sichtbar(s));
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: true, modus: 'fallback', statusMs: 300, einloesen: [] });
    await warte(40);
    check('ohne Merker: bis zur Statusantwort sichtbar (kein Aufblitzen ohne IdP)', sichtbar(s));
    await warte(400);
    check('... und nach der Antwort "fallback" verborgen', !sichtbar(s));
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: true, status: 'nie', merk: 'fallback', einloesen: [] });
    await warte(40);
    const vorher = sichtbar(s);
    await warte(4300);
    check('Status antwortet nie: nach der Sicherungsfrist wieder sichtbar', !vorher && sichtbar(s));
    s.w.close();

    // ── Einstellungsmaske: Schalter nur bei eingeschaltetem IdP ─────────
    {
        const html = SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '');
        const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://jarvis.test/settings' });
        const w = dom.window, d = w.document;
        const posts = [];
        w.fetch = (u, init) => {
            if (init && init.method === 'POST') posts.push(JSON.parse(init.body || '{}'));
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, oidc_aktiv: true, oidc_ad_modus: 'zusaetzlich', namensclaims: [] }) });
        };
        // tabfill.js wie in settings.html: settings_idp.js setzt den Vorschlag der
        // Rueckkehradresse ueber JarvisTabfill (2026-11-19).
        for (const f of ['i18n.js', 'sitzung.js', 'tabfill.js', 'settings_idp.js']) w.eval(lies('frontend/js/' + f));
        d.dispatchEvent(new w.Event('DOMContentLoaded'));
        const E = w.IdpEinstellungen, zeile = d.getElementById('idp-ad-modus-zeile');
        const cb = d.getElementById('idp-ad-zusaetzlich'), aktiv = d.getElementById('idp-aktiv');
        if (!E || !E._zeigen) { console.log('ABBRUCH (Exit 2): settings_idp.js nicht geladen'); bilanz = true; process.exit(2); }
        E._zeigen({ oidc_aktiv: true, oidc_ad_modus: 'zusaetzlich', namensclaims: [] });
        check('Einstellung: IdP an -> Schalter sichtbar und gesetzt (zusaetzlich)', !zeile.hidden && cb.checked);
        E._zeigen({ oidc_aktiv: true, oidc_ad_modus: 'fallback', namensclaims: [] });
        check('Einstellung: fallback -> Schalter aus', !zeile.hidden && !cb.checked);
        E._zeigen({ oidc_aktiv: false, oidc_ad_modus: 'fallback', namensclaims: [] });
        check('Einstellung: IdP aus -> Schalter verborgen', zeile.hidden);
        aktiv.checked = true; aktiv.dispatchEvent(new w.Event('change'));
        check('Einstellung: IdP-Haken setzen blendet den Schalter ein', !zeile.hidden);
        aktiv.checked = false; aktiv.dispatchEvent(new w.Event('change'));
        check('Einstellung: IdP-Haken entfernen blendet ihn aus', zeile.hidden);
        aktiv.checked = true; cb.checked = true;
        d.getElementById('idp-speichern').click();
        await warte(30);
        check('Speichern schickt oidc_ad_modus=zusaetzlich', posts.length === 1 && posts[0].oidc_ad_modus === 'zusaetzlich',
              JSON.stringify(posts));
        cb.checked = false;
        d.getElementById('idp-speichern').click();
        await warte(30);
        check('Speichern schickt oidc_ad_modus=fallback', posts.length === 2 && posts[1].oidc_ad_modus === 'fallback');
        w.close();
    }

    const fehlerAlle = [].concat(...ALLE_FEHLER);
    check('keine Skriptfehler in allen Laeufen', fehlerAlle.length === 0, fehlerAlle.join(' | '));

    // ── C: Texte ─────────────────────────────────────────────────────────────
    console.log('C  Texte');
    const schluessel = new Set();
    const quellen = SETTINGS + MODUL + MODUL_ADMIN;
    for (const m of quellen.matchAll(/['"]((?:login\.idp|security\.idp|security\.sub_idp)[a-z_.]*)['"]/g)) {
        // Praefix eines zusammengesetzten Schluessels (T('login.idp_err.' + k)) ist keiner.
        if (!m[1].endsWith('.')) schluessel.add(m[1]);
    }
    for (const k of Object.keys(s.w.IdpAnmeldung ? s.w.IdpAnmeldung._FEHLER : {})) schluessel.add('login.idp_err.' + k);
    const vorkommen = (k) => (I18N.match(new RegExp("'" + k.replace(/\./g, '\\.') + "'\\s*:", 'g')) || []).length;
    check('Positivkontrolle: Schluessel gefunden (' + schluessel.size + ')', schluessel.size >= 40);
    const fehlt = [...schluessel].filter(k => vorkommen(k) !== 2);
    check('jeder Schluessel steht genau zweimal (DE + EN)', fehlt.length === 0, fehlt.join(', '));
    {
        const wert = (k) => [...I18N.matchAll(new RegExp("'" + k.replace(/\./g, '\\.') + "'\\s*:\\s*'([^']*)'", 'g'))].map(m => m[1]);
        const knopfTexte = wert('login.idp_button');
        check('Knopf: DE und EN nennen "(SSO)"', knopfTexte.length === 2 && knopfTexte.every(t => /\(SSO\)$/.test(t)),
              JSON.stringify(knopfTexte));
        const vorgabe = (SETTINGS.match(/data-i18n="login\.idp_button">([^<]*)</) || [])[1];
        check('Knopf: Vorgabetext im Markup = DE-Wert', vorgabe === knopfTexte[0], vorgabe);
        const zitat = wert('security.idp_ad_zusaetzlich_hint');
        check('Einstellungshinweis zitiert den Knopf mit dem neuen Text (DE + EN)',
              zitat.length === 2 && zitat[0].includes('„' + knopfTexte[0] + '“') && zitat[1].includes('“' + knopfTexte[1] + '”'));
    }

    // ── D: Automatisch anmelden ─────────────────────────────────────────────
    console.log('D  Automatisch anmelden');
    const START = '/api/login/oidc/start';
    const lauf = async (url, a, ms) => { const x = seite(url, Object.assign({ aktiv: true, einloesen: [] }, a)); await warte(ms || 60); return x; };

    // Positivkontrolle: der gemeinte Weg fuehrt wirklich zum IdP – sonst sind
    // alle "startet NICHT"-Pruefungen unten trivial wahr.
    s = await lauf('https://jarvis.test/', { auto: true });
    if (!s.w.IdpAnmeldung || !s.w.IdpAnmeldung._autoGrund) {
        console.log('ABBRUCH (Exit 2): Automatik nicht im Modul'); bilanz = true; process.exit(2);
    }
    // Bewusst FAIL statt Exit 2: kein Start ist ein PRODUKTbefund (eine Sabotage
    // der Automatik), kein kaputter Messaufbau – der ist oben schon belegt.
    check('Positivkontrolle: Haken + IdP an + frischer Aufruf -> genau EIN Start zum IdP',
          s.z.ziele.length === 1 && s.z.ziele[0] === START, JSON.stringify(s.z.ziele));
    check('Start merkt die Zeit (Schleifenbremse)', +s.w.sessionStorage.getItem('jarvis_idp_auto_zeit') > Date.now() - 5000);
    check('Haken erscheint gesetzt', s.d.getElementById('idp-auto').checked === true);
    s.w.close();

    s = await lauf('https://jarvis.test/', {});
    check('ohne Haken: kein Start', s.z.ziele.length === 0);
    const cb = s.d.getElementById('idp-auto');
    check('ohne Haken: Kaestchen leer und im IdP-Bereich', !cb.checked && s.d.getElementById('idp-login').contains(cb));
    cb.checked = true; cb.dispatchEvent(new s.w.Event('change'));
    check('Haken setzen speichert ihn im Browser', s.w.localStorage.getItem('jarvis_idp_auto') === '1');
    check('... und startet NICHT sofort', s.z.ziele.length === 0);
    cb.checked = false; cb.dispatchEvent(new s.w.Event('change'));
    check('Haken entfernen loescht ihn', s.w.localStorage.getItem('jarvis_idp_auto') === null);
    s.w.close();

    s = await lauf('https://jarvis.test/', { auto: true, aktiv: false });
    check('IdP aus: kein Start', s.z.ziele.length === 0);
    s.w.close();
    s = await lauf('https://jarvis.test/', { auto: true, status: 'fehler' });
    check('Status nicht abrufbar: kein Start', s.z.ziele.length === 0);
    s.w.close();

    s = await lauf('https://jarvis.test/', { auto: true, referrer: 'https://jarvis.test/portal' });
    check('von einer Jarvis-Seite (Abmelden): kein Start', s.z.ziele.length === 0);
    s.w.close();
    s = await lauf('https://jarvis.test/', { auto: true, referrer: 'https://intranet.beispiel.de/start' });
    check('von einer fremden Seite (Lesezeichen im Intranet): Start', s.z.ziele.length === 1);
    s.w.close();

    s = await lauf('https://jarvis.test/?idp_fehler=abgebrochen', { auto: true });
    check('Rueckkehr mit Fehler: kein Start, Meldung bleibt stehen',
          s.z.ziele.length === 0 && !s.d.getElementById('login-error').hidden);
    s.w.close();
    s = await lauf('https://jarvis.test/?anmeldung=idp', { auto: true, einloesen: [
        { status: 401, body: { success: false, abgelaufen: true, error: 'abgelaufen' } }] }, 80);
    check('Rueckkehr zum Einloesen (abgelehnt): kein erneuter Start', s.z.ziele.length === 0 && s.z.posts.length === 1);
    s.w.close();

    s = await lauf('https://jarvis.test/', { auto: true, autoZeit: Date.now() - 5000 });
    check('vor 5 s schon gestartet: kein Start (Schleife)', s.z.ziele.length === 0);
    s.w.close();
    s = await lauf('https://jarvis.test/', { auto: true, autoZeit: Date.now() - 120000 });
    check('vor 2 min gestartet: Start', s.z.ziele.length === 1);
    s.w.close();

    s = await lauf('https://jarvis.test/settings', { auto: true });
    check('unter /settings: kein Start', s.z.ziele.length === 0);
    s.w.close();

    s = await lauf('https://jarvis.test/', { auto: true, token: 'ALT' });
    check('mit Token: kein Start, solange app.js prueft', s.z.ziele.length === 0);
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('... Token verworfen (Ereignis) -> Start', s.z.ziele.length === 1 && s.z.ziele[0] === START);
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('... ein zweites Ereignis startet nicht noch einmal', s.z.ziele.length === 1);
    s.w.close();

    // Gesperrter Sitzungsspeicher (privater Modus): dann fehlt die Schleifenbremse,
    // und nur die Marke "erledigt" verhindert den zweiten Start.
    s = await lauf('https://jarvis.test/', { auto: true, token: 'ALT', ohneSitzungsspeicher: true });
    let gesperrt = false;
    try { s.w.sessionStorage; } catch (e) { gesperrt = true; }
    if (!gesperrt) { console.log('ABBRUCH (Exit 2): Sitzungsspeicher liess sich nicht sperren'); bilanz = true; process.exit(2); }
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('Speicher gesperrt: trotzdem ein Start', s.z.ziele.length === 1);
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('Speicher gesperrt: ein zweites Ereignis startet nicht noch einmal', s.z.ziele.length === 1, JSON.stringify(s.z.ziele));
    s.w.close();

    s = await lauf('https://jarvis.test/', { auto: true, token: 'ALT', statusMs: 200 });
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('Ereignis VOR der Statusantwort: noch kein Start', s.z.ziele.length === 0);
    await warte(300);
    check('... nach der Antwort: Start', s.z.ziele.length === 1);
    s.w.close();

    // app.js: woher kommt das Ereignis? Am Syntaxbaum, nicht am Text.
    {
        const acorn = require('./lib/acorn_laden')();
        const APP = lies('frontend/js/app.js');
        const baum = acorn.parse(APP, { ecmaVersion: 'latest', sourceType: 'script' });
        const laufe = (n, cb, eltern) => {
            if (!n || typeof n.type !== 'string') return;
            cb(n, eltern || []);
            for (const k of Object.keys(n)) {
                const v = n[k];
                const nx = (eltern || []).concat([n]);
                if (Array.isArray(v)) v.forEach(x => laufe(x, cb, nx));
                else if (v && typeof v.type === 'string') laufe(v, cb, nx);
            }
        };
        const istFn = (n) => /^(FunctionDeclaration|FunctionExpression|ArrowFunctionExpression)$/.test(n.type);
        const ausloeser = [];   // [Name der umschliessenden Funktion]
        const aufrufe = {};     // Name -> Anzahl Aufrufe
        laufe(baum, (n, eltern) => {
            if (n.type !== 'CallExpression') return;
            const c = n.callee;
            if (c.type === 'Identifier') aufrufe[c.name] = (aufrufe[c.name] || 0) + 1;
            if (c.type === 'MemberExpression' && !c.computed && c.property.name === 'dispatchEvent') {
                const arg = n.arguments[0];
                const lit = arg && arg.type === 'NewExpression' && arg.arguments[0] && arg.arguments[0].value;
                if (lit === 'jarvis-anmeldemaske') {
                    const fn = [...eltern].reverse().find(istFn);
                    ausloeser.push(fn && fn.id ? fn.id.name : '(anonym)');
                }
            }
        });
        check('app.js loest das Ereignis an GENAU einer Stelle aus', ausloeser.length === 1, JSON.stringify(ausloeser));
        check('... nicht in showLoginScreen (laeuft auch beim Abbruch der Pflicht-Kennwortaenderung)',
              !ausloeser.includes('showLoginScreen'));
        // Die Funktion wird aus dem .then- UND dem .catch-Zweig der Tokenpruefung gerufen.
        let zweige = 0;
        laufe(baum, (n) => {
            if (n.type !== 'CallExpression' || n.callee.type !== 'MemberExpression') return;
            const m = n.callee.property && n.callee.property.name;
            if (m !== 'then' && m !== 'catch') return;
            let kette = n.callee.object, istPruefung = false;
            while (kette && kette.type === 'CallExpression') {
                const a0 = kette.arguments[0];
                if (kette.callee.type === 'Identifier' && kette.callee.name === 'fetch' && a0 && a0.value === '/api/verify-token') istPruefung = true;
                kette = kette.callee.type === 'MemberExpression' ? kette.callee.object : null;
            }
            if (!istPruefung) return;
            let ruft = false;
            n.arguments.forEach(arg => laufe(arg, (x) => {
                if (x.type === 'CallExpression' && x.callee.type === 'Identifier' && x.callee.name === ausloeser[0]) ruft = true;
            }));
            if (ruft) zweige++;
        });
        check('... gerufen aus .then UND .catch der Tokenpruefung (/api/verify-token)', zweige === 2, 'Zweige: ' + zweige);
    }

    // ── E: Ein Servername ───────────────────────────────────────────────────
    console.log('E  Ein Servername');
    const DORT = 'https://192.0.2.30';
    s = await lauf('https://jarvis.test/', { ursprung: DORT });
    if (!s.w.IdpAnmeldung._wechselGrund) { console.log('ABBRUCH (Exit 2): Wechsel nicht im Modul'); bilanz = true; process.exit(2); }
    // FAIL statt Exit 2 (wie in D): ein fehlender Wechsel ist ein Produktbefund.
    check('Positivkontrolle: anderer Ursprung -> Wechsel auf "/" dort, Marke umgeleitet=1',
          s.z.ziele.length === 1 && s.z.ziele[0] === DORT + '/?umgeleitet=1', JSON.stringify(s.z.ziele));
    check('... Knopf und Haken bleiben verborgen (kein Aufblitzen unter dem falschen Namen)',
          s.d.getElementById('idp-login').hidden === true);
    s.w.close();

    s = await lauf('https://jarvis.test/', { ursprung: DORT, auto: true });
    check('Wechsel geht dem automatischen Start vor (nur EIN Ziel: der Wechsel)',
          s.z.ziele.length === 1 && s.z.ziele[0] === DORT + '/?umgeleitet=1', JSON.stringify(s.z.ziele));
    check('... und merkt keine Startzeit (gestartet wird erst drueben)', s.w.sessionStorage.getItem('jarvis_idp_auto_zeit') === null);
    s.w.close();

    s = await lauf('https://jarvis.test/', { ursprung: DORT, referrer: 'https://jarvis.test/portal' });
    check('vom Abmelden (Jarvis-Seite) -> Marke umgeleitet=2', s.z.ziele[0] === DORT + '/?umgeleitet=2', s.z.ziele[0]);
    s.w.close();

    s = await lauf('https://jarvis.test/', { ursprung: 'https://jarvis.test' });
    check('gleicher Ursprung -> kein Wechsel, Knopf sichtbar',
          s.z.ziele.length === 0 && s.d.getElementById('idp-login').hidden === false);
    s.w.close();
    s = await lauf('https://jarvis.test/', { ursprung: DORT, aktiv: false });
    check('IdP aus -> kein Wechsel', s.z.ziele.length === 0);
    s.w.close();
    s = await lauf('https://jarvis.test/settings', { ursprung: DORT });
    check('unter /settings -> kein Wechsel', s.z.ziele.length === 0);
    s.w.close();
    s = await lauf('https://jarvis.test/?idp_fehler=abgebrochen', { ursprung: DORT });
    check('Rueckkehr mit Fehler -> kein Wechsel, Meldung steht', s.z.ziele.length === 0
          && !s.d.getElementById('login-error').hidden);
    s.w.close();

    s = await lauf('https://jarvis.test/?umgeleitet=1', { ursprung: DORT });
    check('schon umgeleitet und Ursprung passt trotzdem nicht -> kein zweiter Wechsel (Schleife)',
          s.z.ziele.length === 0 && s.d.getElementById('idp-login').hidden === false);
    check('... Marke aus der Adresse genommen', s.w.location.search === '', s.w.location.href);
    s.w.close();

    s = await lauf('https://jarvis.test/?umgeleitet=1', { ursprung: 'https://jarvis.test', auto: true });
    check('angekommen (=1) mit Haken -> automatischer Start', s.z.ziele.length === 1 && s.z.ziele[0] === START,
          JSON.stringify(s.z.ziele));
    s.w.close();
    s = await lauf('https://jarvis.test/?umgeleitet=2', { ursprung: 'https://jarvis.test', auto: true });
    check('angekommen vom Abmelden (=2) mit Haken -> KEIN automatischer Start', s.z.ziele.length === 0);
    check('... Haken steht drueben, wie dort gespeichert', s.d.getElementById('idp-auto').checked === true);
    s.w.close();

    s = await lauf('https://jarvis.test/', { ursprung: DORT, token: 'ALT' });
    check('mit Token: kein Wechsel, solange app.js prueft', s.z.ziele.length === 0);
    s.d.dispatchEvent(new s.w.CustomEvent('jarvis-anmeldemaske'));
    await warte(20);
    check('... Token verworfen (Ereignis) -> Wechsel', s.z.ziele.length === 1 && s.z.ziele[0] === DORT + '/?umgeleitet=1',
          JSON.stringify(s.z.ziele));
    s.w.close();

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
