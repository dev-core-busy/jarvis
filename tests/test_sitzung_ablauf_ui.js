/* Waechter: abgelaufene Sitzung wird ANGEZEIGT, und nach der Neuanmeldung
 * geht es auf die Seite von vorher zurueck (frontend/js/sitzung_ablauf.js,
 * frontend/js/sitzung.js: merkeRueckkehr/rueckkehrZiel).
 *
 * GEMELDET 2026-11-24: nach laengerer Pause war man serverseitig abgemeldet,
 * die Seite sagte es nicht – Abrufe verstummten, der Chat merkte es erst beim
 * Absenden.
 *
 * Gemessen wird die WIRKUNG am echten Modul in jsdom (fetch-Attrappe ueber den
 * PFAD geroutet, eigene Uhr, abgefangener Takt):
 *   1. Positivkontrolle: Modul geladen, fetch umwickelt, Attrappe erreichbar
 *   2. 401 + Sitzung ungueltig -> Hinweis (Titel, Text, Knopf, × aus icons.js)
 *   3. 401 ist NICHT immer die Sitzung: gueltig -> kein Hinweis
 *   4. Anmeldeweg / fremder Ursprung / Wurzel / kein Token -> gar keine Pruefung
 *   5. "unbekannt" (5xx, Netzfehler, Unlesbares) -> kein Hinweis
 *   6. Rueckkehr (Tab sichtbar) prueft, gedrosselt; Takt prueft nur nach Sprung
 *   7. × schliesst, Ruhezeit, danach wieder
 *   8. "Neu anmelden" merkt die Adresse und geht auf /
 *   9. rueckkehrZiel: einmalig, nur eigene Pfade, nie die Wurzel
 *  10. Regeln: Einbindung je Seite, Rueckkehr in den Anmeldewegen, CSS, i18n
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const WURZEL = path.resolve(__dirname, '..');
const JS = (n) => fs.readFileSync(path.join(WURZEL, 'frontend/js', n), 'utf8');
const ABLAUF = JS('sitzung_ablauf.js');
const ICONS = JS('icons.js');

let ok = 0, fail = 0;
function check(text, bed, detail) {
    if (typeof text !== 'string' || typeof bed !== 'boolean') {
        console.log('ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht: ' + text);
        process.exit(2);
    }
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (detail ? ' – ' + detail : '')); }
    return bed;
}
function abbruch(grund) { console.log('ABBRUCH (Exit 2): ' + grund); process.exit(2); }
const warte = (ms) => new Promise((r) => setTimeout(r, ms || 15));

/* Ein frisches Fenster je Szenario. `verify`: was /api/verify-token liefert –
 * {valid:true|false} (Status 200 bzw. 401), 'fehler500', 'netz', 'muell'. */
function aufbau(opt) {
    opt = opt || {};
    const navigiert = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => {
        if (/navigation/i.test(String(e && e.message))) navigiert.push(String(e.message));
    });
    const dom = new JSDOM('<!doctype html><html><head></head><body><p>Seite</p></body></html>', {
        url: 'https://seite.beispiel.de' + (opt.pfad || '/chat?sid=7#unten'),
        runScripts: 'outside-only',
        virtualConsole: vc,
        /* Ohne diesen Schalter meldet jsdom `document.hidden === true` – jeder
         * Rueckkehr-Weg waere dann stumm, und das saehe wie ein Produktfehler
         * aus (beim Bau so gemessen: 3 FAIL ohne Produktursache). */
        pretendToBeVisual: true,
    });
    const w = dom.window;
    const aufrufe = [];
    const zustand = { verify: opt.verify || { valid: false } };
    function antwort(status, body, kaputt) {
        return {
            status, ok: status >= 200 && status < 300,
            json: () => kaputt ? Promise.reject(new Error('kein JSON')) : Promise.resolve(body),
        };
    }
    w.fetch = function (eingabe, init) {
        const url = typeof eingabe === 'string' ? eingabe : eingabe.url;
        const pfad = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
        aufrufe.push({ pfad, url, init });
        if (pfad === '/api/verify-token') {
            if (zustand.beimPruefen) zustand.beimPruefen(w);
            const v = zustand.verify;
            if (v === 'fehler500') return Promise.resolve(antwort(500, {}));
            if (v === 'netz') return Promise.reject(new TypeError('Failed to fetch'));
            if (v === 'muell') return Promise.resolve(antwort(200, null, true));
            return Promise.resolve(antwort(v.valid ? 200 : 401, v));
        }
        return Promise.resolve(antwort(opt.status || 401, { detail: 'x' }));
    };
    const roh = w.fetch;
    let uhr = 1000000;
    w.Date.now = () => uhr;
    let takt = null;
    w.setInterval = (fn) => { takt = fn; return 1; };
    sitzungLaden(w, { token: opt.ohneToken ? '' : 'JCS1.probe' });
    w.eval(ICONS);
    w.eval(ABLAUF);
    return {
        w, aufrufe, zustand, navigiert, roh,
        verifies: () => aufrufe.filter((a) => a.pfad === '/api/verify-token').length,
        hinweis: () => w.document.querySelector('.jv-sitzung-ablauf'),
        vor: (ms) => { uhr += ms; },
        takt: () => takt,
    };
}

(async function () {
    /* ── 1. Positivkontrolle ─────────────────────────────────────────────── */
    console.log('\n\x1b[1m1. Positivkontrolle\x1b[0m');
    const p = aufbau();
    if (!p.w.JarvisSitzungAblauf) abbruch('sitzung_ablauf.js hat kein window.JarvisSitzungAblauf gesetzt');
    check('fetch ist umwickelt', p.w.fetch !== p.roh);
    await p.w.fetch('/api/irgendwas');
    if (!p.aufrufe.some((a) => a.pfad === '/api/irgendwas')) abbruch('die Huelle reicht nicht an die Attrappe durch');
    check('die Huelle reicht den Aufruf an fetch durch', true);
    check('Takt ist angemeldet (eigene Uhr)', typeof p.takt() === 'function');
    check('Seite gilt als angemeldet', p.w.JarvisSitzungAblauf._aktiv() === true);
    if (p.w.document.hidden !== false) abbruch('jsdom meldet die Seite als verborgen – Rueckkehr nicht messbar');
    check('Seite gilt als sichtbar (Voraussetzung fuer Abschnitt 6)', true);

    /* ── 2. 401 + ungueltig → Hinweis ───────────────────────────────────── */
    console.log('\n\x1b[1m2. 401 bei abgelaufener Sitzung\x1b[0m');
    {
        const s = aufbau({ verify: { valid: false } });
        const r = await s.w.fetch('/api/chat/sessions', { headers: { Authorization: 'Bearer JCS1.probe' } });
        await warte();
        check('der Aufrufer bekommt seine Antwort unveraendert (401)', r.status === 401);
        check('genau eine Sitzungspruefung', s.verifies() === 1, String(s.verifies()));
        const vt = s.aufrufe.find((a) => a.pfad === '/api/verify-token');
        let body = {};
        try { body = JSON.parse(vt.init.body); } catch (e) { /* bleibt leer */ }
        check('Pruefung schickt das gespeicherte Token', body.token === 'JCS1.probe', JSON.stringify(body));
        const h = s.hinweis();
        check('Hinweis erscheint', !!h);
        check('Hinweis ist ein Dialog (role/aria-modal)',
            !!h && h.getAttribute('role') === 'alertdialog' && h.getAttribute('aria-modal') === 'true');
        check('Titel mit i18n-Schluessel',
            !!h && !!h.querySelector('[data-i18n="sitzung.ablauf_titel"]'));
        check('Text nennt die Ursache (Inaktivitaet/Hoechstdauer)',
            !!h && /Inaktivität/.test(h.textContent) && /Sitzungsdauer/.test(h.textContent), h && h.textContent);
        const los = h && h.querySelector('.jv-sitzung-ablauf-los');
        check('Knopf "Neu anmelden"', !!los && los.textContent === 'Neu anmelden' && los.getAttribute('data-i18n') === 'sitzung.ablauf_knopf');
        const zu = h && h.querySelector('.jv-sitzung-ablauf-zu');
        check('Schliessen-Knopf traegt das × aus icons.js (kein Emoji, kein Muelleimer)',
            !!zu && !!zu.querySelector('svg.jv-ico-close') && !zu.querySelector('.jv-ico-trash'));
        check('Schliessen-Knopf hat eine Beschriftung (title + aria + i18n)',
            !!zu && zu.title === 'Schließen' && zu.getAttribute('aria-label') === 'Schließen'
            && zu.getAttribute('data-i18n-title') === 'sitzung.ablauf_schliessen');
        await s.w.fetch('/api/chat/sessions');
        await warte();
        check('ein weiterer 401 bei offenem Hinweis: keine zweite Pruefung, kein zweiter Hinweis',
            s.verifies() === 1 && s.w.document.querySelectorAll('.jv-sitzung-ablauf').length === 1);
    }

    /* ── 3. 401 bei gueltiger Sitzung ───────────────────────────────────── */
    console.log('\n\x1b[1m3. 401, aber die Sitzung gilt (z. B. falsche LDAP-Zugangsdaten)\x1b[0m');
    {
        const s = aufbau({ verify: { valid: true, username: 'x' } });
        await s.w.fetch('/api/ldap/users', { method: 'POST' });
        await warte();
        check('es wird geprueft', s.verifies() === 1);
        check('kein Hinweis', !s.hinweis());
    }

    /* ── 4. Gar keine Pruefung ──────────────────────────────────────────── */
    console.log('\n\x1b[1m4. Faelle ohne Pruefung\x1b[0m');
    for (const [name, url] of [['Anmeldung', '/api/login'], ['Abmeldung', '/api/logout'],
                               ['Pruefung selbst', '/api/verify-token'], ['2FA', '/api/auth/totp/verify'],
                               ['fremder Ursprung', 'https://fremd.beispiel.de/api/x'],
                               ['kein /api/', '/static/js/x.js']]) {
        const s = aufbau({ verify: { valid: false } });
        await s.w.fetch(url);
        await warte();
        const n = s.verifies() - (url === '/api/verify-token' ? 1 : 0);
        check(name + ': 401 loest keine Pruefung aus', n === 0 && !s.hinweis(), 'Pruefungen=' + n);
    }
    {
        const s = aufbau({ verify: { valid: false }, status: 200 });
        await s.w.fetch('/api/x');
        await warte();
        check('200 loest keine Pruefung aus', s.verifies() === 0);
        const s2 = aufbau({ verify: { valid: false }, status: 403 });
        await s2.w.fetch('/api/x');
        await warte();
        check('403 loest keine Pruefung aus (Recht, nicht Sitzung)', s2.verifies() === 0);
    }
    {
        const s = aufbau({ verify: { valid: false }, pfad: '/' });
        await s.w.fetch('/api/x');
        s.w.document.dispatchEvent(new s.w.Event('visibilitychange'));
        await warte();
        check('Wurzel / (Anmeldeseite): keine Pruefung', s.verifies() === 0 && !s.hinweis());
    }
    {
        const s = aufbau({ verify: { valid: false }, ohneToken: true });
        await s.w.fetch('/api/x');
        await warte();
        check('ohne gespeichertes Token: keine Pruefung', s.verifies() === 0 && !s.hinweis());
    }

    {
        const s = aufbau({ verify: { valid: false } });
        s.zustand.beimPruefen = (w) => w.localStorage.removeItem('jarvis_token');
        await s.w.fetch('/api/me'); await warte();
        check('Seite raeumt waehrend der Pruefung selbst ab (eigene Maske): kein Hinweis darueber',
            s.verifies() === 1 && !s.hinweis());
        const s2 = aufbau({ verify: { valid: false } });
        s2.zustand.beimPruefen = (w) => w.localStorage.setItem('jarvis_token', 'JCS1.neu');
        await s2.w.fetch('/api/me'); await warte();
        check('Token waehrend der Pruefung ersetzt (anderer Tab): kein Hinweis',
            s2.verifies() === 1 && !s2.hinweis());
    }

    /* ── 5. Unbekannt ist keine Abmeldung ───────────────────────────────── */
    console.log('\n\x1b[1m5. Unbekannter Zustand zeigt nichts\x1b[0m');
    for (const v of ['fehler500', 'netz', 'muell']) {
        const s = aufbau({ verify: v });
        await s.w.fetch('/api/x');
        await warte();
        check('Pruefung ' + v + ': gefragt, aber kein Hinweis', s.verifies() === 1 && !s.hinweis());
    }
    {
        const s = aufbau({ verify: { foo: 1 } });
        await s.w.fetch('/api/x');
        await warte();
        check('Antwort ohne valid-Feld: kein Hinweis', s.verifies() === 1 && !s.hinweis());
    }

    /* ── 6. Rueckkehr ───────────────────────────────────────────────────── */
    console.log('\n\x1b[1m6. Rueckkehr zur Seite\x1b[0m');
    {
        const s = aufbau({ verify: { valid: true } });
        const sichtbar = () => s.w.document.dispatchEvent(new s.w.Event('visibilitychange'));
        sichtbar();
        await warte();
        check('Tab wieder sichtbar: eine Pruefung', s.verifies() === 1, String(s.verifies()));
        sichtbar(); s.w.dispatchEvent(new s.w.Event('focus'));
        await warte();
        check('innerhalb einer Minute: keine weitere Pruefung (Leerlauf nicht dauernd beruehren)',
            s.verifies() === 1, String(s.verifies()));
        s.vor(61000);
        s.w.dispatchEvent(new s.w.Event('focus'));
        await warte();
        check('nach einer Minute: Fenster-Fokus prueft wieder', s.verifies() === 2, String(s.verifies()));
        check('gueltig: kein Hinweis', !s.hinweis());
        s.zustand.verify = { valid: false };
        s.vor(61000);
        sichtbar();
        await warte();
        check('abgelaufen bei Rueckkehr: Hinweis sofort, ohne dass der Benutzer etwas tut', !!s.hinweis());
    }
    {
        const s = aufbau({ verify: { valid: false } });
        const takt = s.takt();
        s.vor(30000); takt(); await warte();
        check('Takt ohne Zeitsprung: KEIN Serverkontakt', s.verifies() === 0, String(s.verifies()));
        s.vor(30000); takt(); await warte();
        check('zweiter regulaerer Takt: weiter kein Serverkontakt', s.verifies() === 0);
        s.vor(2 * 3600 * 1000); takt(); await warte();
        check('Zeitsprung (Ruhezustand): Pruefung + Hinweis', s.verifies() === 1 && !!s.hinweis());
    }
    {
        const s = aufbau({ verify: { valid: false } });
        const ev = new s.w.Event('pageshow'); ev.persisted = true;
        s.w.dispatchEvent(ev);
        await warte();
        check('Seite aus dem bfcache: Pruefung', s.verifies() === 1);
    }

    /* ── 7. Schliessen ──────────────────────────────────────────────────── */
    console.log('\n\x1b[1m7. Schliessen und Ruhezeit\x1b[0m');
    {
        const s = aufbau({ verify: { valid: false } });
        await s.w.fetch('/api/x'); await warte();
        /* KEIN Abbruch: fehlt der Hinweis, ist das ein PRODUKTbefund (Exit 1),
         * kein kaputter Messaufbau (Register: Guard trennt zwei Ursachen). */
        if (check('Hinweis fuer Abschnitt 7 aufgebaut', !!s.hinweis())) {
        s.hinweis().querySelector('.jv-sitzung-ablauf-zu').click();
        check('× schliesst den Hinweis', !s.hinweis());
        const vorher = s.verifies();
        s.vor(10000);
        await s.w.fetch('/api/x'); await warte();
        check('naechster 401 in der Ruhezeit: kein neuer Hinweis, keine Pruefung',
            !s.hinweis() && s.verifies() === vorher);
        s.vor(61000);
        await s.w.fetch('/api/x'); await warte();
        check('nach der Ruhezeit erscheint er wieder', !!s.hinweis());
        }
    }

    /* ── 8. Neu anmelden ────────────────────────────────────────────────── */
    console.log('\n\x1b[1m8. "Neu anmelden"\x1b[0m');
    {
        const s = aufbau({ verify: { valid: false }, pfad: '/chat?sid=7#unten' });
        await s.w.fetch('/api/x'); await warte();
        if (check('Hinweis fuer Abschnitt 8 aufgebaut', !!s.hinweis())) {
        s.hinweis().querySelector('.jv-sitzung-ablauf-los').click();
        let gemerkt = null;
        try { gemerkt = s.w.sessionStorage.getItem('jarvis_rueckkehr'); } catch (e) { /* null */ }
        check('Adresse samt Suche und Anker gemerkt', gemerkt === '/chat?sid=7#unten', String(gemerkt));
        check('Navigation zur Anmeldung ausgeloest', s.navigiert.length === 1, s.navigiert.join(' | '));
        check('Tokens werden hier NICHT abgeraeumt (das macht die Anmeldeseite)',
            s.w.JarvisSitzung.token() === 'JCS1.probe');
        }
    }

    /* ── 9. rueckkehrZiel ───────────────────────────────────────────────── */
    console.log('\n\x1b[1m9. Rueckkehr-Ziel\x1b[0m');
    {
        const s = aufbau();
        const S = s.w.JarvisSitzung;
        check('ohne gemerktes Ziel: Vorgabe', S.rueckkehrZiel('/portal') === '/portal');
        S.merkeRueckkehr('/wissen?q=1');
        check('gemerktes Ziel wird geliefert', S.rueckkehrZiel('/portal') === '/wissen?q=1');
        check('... genau einmal', S.rueckkehrZiel('/portal') === '/portal');
        for (const boes of ['//boese.beispiel.de/x', '/\\boese.beispiel.de', 'https://boese.beispiel.de/',
                            'javascript:alert(1)', '/', '//', '', '/chat\n', 'chat']) {
            s.w.sessionStorage.setItem('jarvis_rueckkehr', boes);
            check('verworfen: ' + JSON.stringify(boes), S.rueckkehrZiel('/portal') === '/portal');
        }
        check('merkeRueckkehr lehnt die Wurzel ab', S.merkeRueckkehr('/') === false);
    }

    /* ── 10. Regeln ─────────────────────────────────────────────────────── */
    console.log('\n\x1b[1m10. Regeln\x1b[0m');
    const seiten = fs.readdirSync(path.join(WURZEL, 'frontend')).filter((f) => f.endsWith('.html'));
    const skriptRe = /<script\b[^>]*\bsrc="\/static\/js\/([A-Za-z0-9_.-]+\.js)(?:\?v=\d+)?"/g;
    let angemeldet = 0;
    for (const f of seiten) {
        const html = fs.readFileSync(path.join(WURZEL, 'frontend', f), 'utf8');
        const reihe = [];
        let m; skriptRe.lastIndex = 0;
        while ((m = skriptRe.exec(html))) reihe.push(m[1]);
        if (!reihe.includes('activity.js')) continue;   // keine angemeldete Seite (z. B. support-api)
        angemeldet++;
        /* Hinter sitzung.js (es braucht JarvisSitzung) und icons.js (Regel aus
         * test_icon_semantik: icons.js vor jedem Nutzer), aber VOR jedem
         * anderen Modul hinter sitzung.js – deren fetch-Aufrufe beim Laden
         * liefen sonst an der Huelle vorbei. */
        const i = reihe.indexOf('sitzung.js');
        const j = reihe.indexOf('sitzung_ablauf.js');
        const ic = reihe.indexOf('icons.js');
        const davor = i >= 0 ? reihe.slice(i + 1, j).filter((x) => x !== 'icons.js') : ['(kein sitzung.js)'];
        check(f + ': sitzung_ablauf.js hinter sitzung.js und icons.js, vor allen anderen Modulen',
            i >= 0 && j > i && ic >= 0 && ic < j && davor.length === 0,
            reihe.slice(Math.max(0, i), j + 1).join(', '));
    }
    if (angemeldet < 10) abbruch('nur ' + angemeldet + ' angemeldete Seiten gefunden – Seitensuche kaputt');

    function aufrufeVon(datei, name) {
        const ast = acorn.parse(JS(datei), { ecmaVersion: 'latest', sourceType: 'script' });
        const treffer = [];
        (function lauf(n) {
            if (!n || typeof n.type !== 'string') return;
            if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
                && n.callee.property && n.callee.property.name === 'replace'
                && n.arguments.length === 1) treffer.push(n.arguments[0]);
            for (const k of Object.keys(n)) {
                const v = n[k];
                if (Array.isArray(v)) v.forEach(lauf);
                else if (v && typeof v.type === 'string') lauf(v);
            }
        })(ast);
        return treffer.filter((a) => a.type === 'CallExpression' && a.callee.type === 'MemberExpression'
            && a.callee.property.name === name).length;
    }
    check('app.js: drei Anmeldewege fuehren ueber rueckkehrZiel (Kennwort, Pflichtwechsel, gueltiges Token)',
        aufrufeVon('app.js', 'rueckkehrZiel') === 3, String(aufrufeVon('app.js', 'rueckkehrZiel')));
    check('idp_anmeldung.js: Firmen-Anmeldung fuehrt ueber rueckkehrZiel',
        aufrufeVon('idp_anmeldung.js', 'rueckkehrZiel') === 1);

    const css = fs.readFileSync(path.join(WURZEL, 'frontend/css/theme.css'), 'utf8');
    const klassen = new Set((ABLAUF.match(/'jv-sitzung-ablauf[a-z-]*'/g) || []).map((k) => k.slice(1, -1)));
    if (klassen.size < 4) abbruch('Klassen in sitzung_ablauf.js nicht gefunden (' + klassen.size + ')');
    for (const k of klassen) {
        check('theme.css definiert .' + k, new RegExp('^\\.' + k + '\\s*[{,:]', 'm').test(css));
    }

    const i18nDom = new JSDOM('<!doctype html><body></body>', { url: 'https://seite.beispiel.de/', runScripts: 'outside-only' });
    i18nDom.window.eval(JS('i18n.js'));
    const tw = i18nDom.window;
    for (const k of ['sitzung.ablauf_titel', 'sitzung.ablauf_text', 'sitzung.ablauf_tipp',
                     'sitzung.ablauf_knopf', 'sitzung.ablauf_schliessen']) {
        tw._lang = 'de'; const de = tw.t(k);
        tw._lang = 'en'; const en = tw.t(k);
        check('i18n ' + k + ' in DE und EN, verschieden', de !== k && en !== k && de !== en, de + ' | ' + en);
        check('Fallback im Modul = deutscher i18n-Wert (' + k + ')', ABLAUF.includes("'" + de + "'"));
    }
    i18nDom.window.close();

    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})();
