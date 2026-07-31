/* UI-Test: Anwesenheits-Panel im Portal (jsdom, echte Dateien).
 *
 * Prueft die drei Verhaltensweisen, die sich nicht am Quelltext ablesen lassen:
 *   1. Hover oeffnet und schliesst – ein per KLICK geoeffnetes Panel aber nicht
 *   2. Rechtsklick auf eine Zeile meldet den Benutzer ab
 *   3. gruene/graue Pille je Zustand
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() + process.exit(),
 * sonst haelt der Poll-Timer des Panels den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 60 node tests/test_portal_sessions_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  ✅ ' : '  ❌ ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

const USERS = {
    ok: true, online_window: 120, online: 3, total: 4, may_block: true,
    users: [
        // anna: anwesend UND gerade taetig
        { username: 'anna', display: 'nexus\\anna', online: true, kind: 'user',
          last_login: 1785470000, last_logout: 0, last_seen: Date.now() / 1000 - 5,
          last_ip: '10.0.0.5', logins: 3,
          last_action: Date.now() / 1000 - 20, last_action_label: 'Chat-Anfrage',
          actions: 12, idle_seconds: 20 },
        // bob: offline
        { username: 'bob', display: 'bob', online: false, kind: 'user',
          last_login: 1785400000, last_logout: 1785460000, last_seen: 1785460000,
          last_ip: '10.0.0.9', logins: 1,
          last_action: 1785459000, last_action_label: 'Wissen', actions: 4,
          idle_seconds: 999999, blocked: true },
        // clara: Tab offen, aber seit 40 Minuten untaetig – der Fall, um den es geht
        { username: 'clara', display: 'clara', online: true, kind: 'user',
          last_login: 1785470000, last_logout: 0, last_seen: Date.now() / 1000 - 3,
          last_ip: '10.0.0.7', logins: 2,
          last_action: Date.now() / 1000 - 2400, last_action_label: 'Support-Suche',
          actions: 1, idle_seconds: 2400 },
        // dora: anwesend, hat aber noch nie etwas getan
        { username: 'dora', display: 'dora', online: true, kind: 'user',
          last_login: 1785470000, last_logout: 0, last_seen: Date.now() / 1000 - 2,
          last_ip: '10.0.0.8', logins: 1,
          last_action: 0, last_action_label: '', actions: 0, idle_seconds: null },
    ],
};

async function baueSeite() {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'portal.html'), 'utf8');
    const dom = new JSDOM(html, { url: 'https://localhost/portal', runScripts: 'outside-only' });
    const { window } = dom;
    window.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');

    const calls = [];
    window.fetch = function (url, opts) {
        opts = opts || {};
        calls.push({ url: String(url), method: (opts.method || 'GET').toUpperCase() });
        const j = (data) => Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(data),
            text: () => Promise.resolve(JSON.stringify(data)),
        });
        const u = String(url);
        if (u.indexOf('/api/sessions/') === 0) return j({ ok: true, user: 'bob' });
        if (u.indexOf('/api/sessions') === 0) return j(USERS);
        return j({ ok: true });
    };
    window.confirm = () => true;
    window.alert = () => {};

    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/sessions.js'), 'utf8'));
    return { dom, window, calls };
}

function hover(window, el, typ) {
    el.dispatchEvent(new window.MouseEvent(typ, { bubbles: false, cancelable: true }));
}

async function main() {
    console.log('='.repeat(70));
    console.log('UI-Test Anwesenheits-Panel (jsdom, echte Dateien)');
    console.log('='.repeat(70));

    const { dom, window, calls } = await baueSeite();
    globalThis.__dom = dom;
    const doc = window.document;
    const $ = (id) => doc.getElementById(id);

    section('Ausgangszustand');
    check('Knopf ist versteckt, bis Admin bestaetigt ist',
          $('pt-usr-wrap').style.display === 'none', $('pt-usr-wrap').style.display);
    window.UserSessions.init();
    check('nach init() sichtbar', $('pt-usr-wrap').style.display === '');
    check('Panel zunaechst zu', $('pt-usr-panel').hasAttribute('hidden'));

    section('1. Hover oeffnet und schliesst');
    hover(window, $('pt-usr-wrap'), 'mouseenter');
    await sleep(30);
    check('mouseenter oeffnet', !$('pt-usr-panel').hasAttribute('hidden'));
    check('Liste geladen', doc.querySelectorAll('.pt-usr-item').length === 4,
          String(doc.querySelectorAll('.pt-usr-item').length));
    hover(window, $('pt-usr-wrap'), 'mouseleave');
    await sleep(80);
    check('kurz nach mouseleave noch offen (Nachlauf)', !$('pt-usr-panel').hasAttribute('hidden'));
    await sleep(400);
    check('nach dem Nachlauf geschlossen', $('pt-usr-panel').hasAttribute('hidden'));

    section('2. Per Klick geoeffnet: Hover schliesst NICHT');
    $('pt-usr-btn').click();
    await sleep(30);
    check('Klick oeffnet', !$('pt-usr-panel').hasAttribute('hidden'));
    hover(window, $('pt-usr-wrap'), 'mouseleave');
    await sleep(500);
    check('bleibt trotz mouseleave offen', !$('pt-usr-panel').hasAttribute('hidden'));
    $('pt-usr-btn').click();
    await sleep(20);
    check('zweiter Klick schliesst', $('pt-usr-panel').hasAttribute('hidden'));

    section('3. Hover-Panel per Klick festhalten');
    hover(window, $('pt-usr-wrap'), 'mouseenter');
    await sleep(30);
    $('pt-usr-btn').click();          // aus Hover wird "festgehalten"
    await sleep(20);
    check('nach dem Klick weiterhin offen', !$('pt-usr-panel').hasAttribute('hidden'));
    hover(window, $('pt-usr-wrap'), 'mouseleave');
    await sleep(500);
    check('mouseleave schliesst es jetzt nicht mehr', !$('pt-usr-panel').hasAttribute('hidden'));
    $('pt-usr-btn').click();
    await sleep(20);
    check('erst der naechste Klick schliesst', $('pt-usr-panel').hasAttribute('hidden'));
    // Und die Gegenprobe: aus dem geschlossenen Zustand oeffnet ein Klick wieder.
    $('pt-usr-btn').click();
    await sleep(20);
    check('Klick oeffnet aus dem geschlossenen Zustand', !$('pt-usr-panel').hasAttribute('hidden'));

    section('4. Pillen und Inhalt');
    const zeilen = doc.querySelectorAll('.pt-usr-item');
    const p0 = zeilen[0].querySelector('.pt-usr-pill');
    const p1 = zeilen[1].querySelector('.pt-usr-pill');
    check('erste Zeile online (gruen)', p0.className.indexOf('is-on') !== -1, p0.className);
    check('zweite Zeile offline (grau)', p1.className.indexOf('is-off') !== -1, p1.className);
    check('Pille traegt auch Text', /online|offline/i.test(p0.textContent), p0.textContent);
    check('Benutzer am Element hinterlegt', zeilen[1].getAttribute('data-user') === 'bob',
          zeilen[1].getAttribute('data-user'));
    // Die Zeitstempel stehen seit dem Kompakt-Umbau im title des Eintrags –
    // sichtbar bleibt nur die eine Aussage, die man beim Ueberfliegen braucht.
    const finde0 = (u) => doc.querySelector('.pt-usr-item[data-user="' + u + '"]');
    const tt = (u) => finde0(u).getAttribute('title') || '';
    check('Abmeldezeit im Tooltip', /Abmeldung/.test(tt('bob')), tt('bob'));
    check('Anmeldezeit im Tooltip', /Anmeldung/.test(tt('bob')), tt('bob'));
    check('Tooltip nennt den Kontonamen', tt('bob').indexOf('bob') === 0, tt('bob'));

    section('5. Anwesenheit vs. Aktivitaet');
    const finde = (u) => doc.querySelector('.pt-usr-item[data-user="' + u + '"]');
    const txt = (u) => finde(u).querySelector('.pt-usr-meta').textContent.replace(/\s+/g, ' ');
    check('taetiger Benutzer: keine Untaetig-Meldung',
          !finde('anna').querySelector('.pt-usr-idle'), txt('anna'));
    check('taetiger Benutzer: Handlung wird benannt', /Chat-Anfrage/.test(txt('anna')), txt('anna'));
    // Der Kern: Tab offen (online), aber seit 40 Minuten nichts getan.
    check('untaetiger Benutzer wird als solcher markiert',
          !!finde('clara').querySelector('.pt-usr-idle'), txt('clara'));
    check('Untaetigkeit mit Dauer', /untätig seit 40 Min/.test(txt('clara')), txt('clara'));
    check('trotzdem online', finde('clara').querySelector('.pt-usr-pill').className.indexOf('is-on') !== -1);
    check('ohne Handlung: ausdruecklicher Hinweis',
          /noch keine Aktion/.test(txt('dora')), txt('dora'));
    check('offline: Dauer statt Untaetigkeit', /offline seit/.test(txt('bob')), txt('bob'));

    section('6. Menue statt Direktaktion');
    check('sichtbarer Menue-Knopf je Zeile',
          doc.querySelectorAll('.pt-usr-menubtn').length === 4,
          String(doc.querySelectorAll('.pt-usr-menubtn').length));
    const ev = new window.MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    finde('anna').dispatchEvent(ev);
    await sleep(40);
    check('Standard-Kontextmenue unterdrueckt', ev.defaultPrevented);
    let menu = doc.querySelector('.pt-usr-menu');
    check('Menue geoeffnet', !!menu);
    // Wichtig: der Rechtsklick loest jetzt NICHTS mehr direkt aus.
    check('noch keine Aktion ausgeloest',
          !calls.some((c) => c.method === 'POST'), JSON.stringify(calls.filter(c => c.method === 'POST')));
    check('Menue nennt den Benutzer',
          /anna/.test(menu.querySelector('.pt-usr-menu-head').textContent));
    let punkte = Array.from(menu.querySelectorAll('.pt-usr-menu-item')).map((b) => b.getAttribute('data-do'));
    check('Punkte: abmelden + sperren', punkte.join(',') === 'kick,block', punkte.join(','));
    check('Sperren ist als gefaehrlich markiert',
          !!menu.querySelector('.pt-usr-menu-item[data-do=block].is-danger'));

    section('7. Menue-Punkt "abmelden"');
    let vorher = calls.length;
    menu.querySelector('.pt-usr-menu-item[data-do=kick]').click();
    await sleep(60);
    const kick = calls.slice(vorher).find((c) => c.method === 'POST' && c.url.indexOf('/api/sessions/') === 0);
    check('Abmelde-Aufruf abgesetzt', !!kick, JSON.stringify(calls.slice(vorher)));
    check('richtiger Benutzer im Pfad', kick && kick.url.indexOf('/api/sessions/anna/logout') === 0,
          kick ? kick.url : '');
    check('Menue danach geschlossen', !doc.querySelector('.pt-usr-menu'));
    check('Liste neu geladen',
          calls.slice(vorher).some((c) => c.method === 'GET' && c.url.indexOf('/api/sessions') === 0));

    section('8. Gesperrter Benutzer: Entsperren statt Sperren');
    check('Sperr-Plakette in der Zeile', !!finde('bob').querySelector('.pt-usr-blocked'));
    doc.querySelector('.pt-usr-item[data-user="bob"] .pt-usr-menubtn').click();
    await sleep(40);
    menu = doc.querySelector('.pt-usr-menu');
    check('Menue ueber den ⋯-Knopf geoeffnet', !!menu);
    punkte = Array.from(menu.querySelectorAll('.pt-usr-menu-item')).map((b) => b.getAttribute('data-do'));
    check('bietet entsperren statt sperren', punkte.join(',') === 'kick,unblock', punkte.join(','));
    vorher = calls.length;
    menu.querySelector('.pt-usr-menu-item[data-do=unblock]').click();
    await sleep(60);
    const unb = calls.slice(vorher).find((c) => c.method === 'POST');
    check('Entsperr-Endpunkt aufgerufen',
          unb && unb.url.indexOf('/api/security/incidents/unblock') === 0, unb ? unb.url : '');

    section('9. Ohne Bestaetigung keine Aktion');
    window.confirm = () => false;
    doc.querySelector('.pt-usr-item[data-user="clara"] .pt-usr-menubtn').click();
    await sleep(40);
    const vorher2 = calls.length;
    doc.querySelector('.pt-usr-menu .pt-usr-menu-item[data-do=block]').click();
    await sleep(60);
    check('kein Aufruf bei Abbruch',
          !calls.slice(vorher2).some((c) => c.method === 'POST'),
          JSON.stringify(calls.slice(vorher2)));
    window.confirm = () => true;

    section('10. Ohne Sperrrecht keine Sperr-Eintraege');
    // Der Server meldet may_block=false fuer AD-Admins – dann darf das Menue
    // die Punkte gar nicht erst anbieten, statt in ein 403 zu laufen.
    window.__nurAbmelden = true;
    const alteFetch = window.fetch;
    window.fetch = function (url, opts) {
        if (String(url).indexOf('/api/sessions') === 0 && (!opts || !opts.method)) {
            return Promise.resolve({ ok: true, status: 200,
                json: () => Promise.resolve(Object.assign({}, USERS, { may_block: false })) });
        }
        return alteFetch(url, opts);
    };
    window.UserSessions.load();
    await sleep(80);
    doc.querySelector('.pt-usr-item[data-user="anna"] .pt-usr-menubtn').click();
    await sleep(40);
    punkte = Array.from(doc.querySelectorAll('.pt-usr-menu .pt-usr-menu-item'))
        .map((b) => b.getAttribute('data-do'));
    check('nur "abmelden" im Menue', punkte.join(',') === 'kick', punkte.join(','));

    // Aufraeumen: Menue zu, Originaldaten zurueck, sauber neu oeffnen.
    window.fetch = alteFetch;
    window.UserSessions.close();
    $('pt-usr-btn').click();
    await sleep(60);

    section('11. Kompakte Zeile');
    // jsdom kennt keine Layout-Hoehen. Pruefbar ist die STRUKTUR, die die Hoehe
    // bestimmt: genau EINE Metazeile je Eintrag, kurz genug fuer eine Zeile,
    // plus die CSS-Regel, die den Umbruch verbietet.
    const metas = doc.querySelectorAll('.pt-usr-item .pt-usr-meta');
    check('genau eine Metazeile je Eintrag', metas.length === 4, String(metas.length));
    const zuLang = Array.from(metas)
        .map((m) => m.textContent.replace(/\s+/g, ' ').trim())
        .filter((s) => s.length > 60);
    check('Metazeile bleibt kurz (<= 60 Zeichen)', zuLang.length === 0, JSON.stringify(zuLang));
    check('keine aufgereihten Schluessel-Wert-Paare mehr',
          doc.querySelectorAll('.pt-usr-sep').length === 0,
          String(doc.querySelectorAll('.pt-usr-sep').length));
    const css = fs.readFileSync(path.join(ROOT, 'frontend', 'portal.html'), 'utf8');
    check('CSS verbietet den Umbruch der Metazeile',
          /\.pt-usr-meta\s*\{[^}]*white-space:\s*nowrap/.test(css));
    check('CSS kuerzt zu langen Text mit Ellipse',
          /\.pt-usr-meta\s*\{[^}]*text-overflow:\s*ellipsis/.test(css));
    // Nicht doppelt: "untätig seit 40 Min." und "zuletzt: 40 Min." waeren
    // derselbe Wert (idle_seconds = jetzt - last_action).
    check('untaetiger Benutzer: keine doppelte Zeitangabe',
          !/zuletzt/i.test(txt('clara')), txt('clara'));
    check('Handlung wird trotzdem benannt', /Support-Suche/.test(txt('clara')), txt('clara'));

    section('12. Suchfilter');
    const feld = $('pt-usr-search');
    check('Filterfeld vorhanden', !!feld);
    check('Platzhalter uebersetzbar', feld.getAttribute('data-i18n-placeholder') === 'sessions.search_ph');
    check('Beschriftung fuer Hilfsmittel', !!feld.getAttribute('aria-label'));
    check('bei gefuellter Liste sichtbar', $('pt-usr-filter').style.display !== 'none',
          $('pt-usr-filter').style.display);

    const tippe = async (wert) => {
        feld.value = wert;
        feld.dispatchEvent(new window.Event('input', { bubbles: true }));
        await sleep(20);
    };
    const namen = () => Array.from(doc.querySelectorAll('.pt-usr-item'))
        .map((e) => e.getAttribute('data-user')).join(',');

    await tippe('cl');
    check('filtert auf den Treffer', namen() === 'clara', namen());
    check('Zaehler nennt Treffer/Gesamt', $('pt-usr-count').textContent === '1/4',
          $('pt-usr-count').textContent);
    // Der Anzeigename kann vom Kontonamen abweichen (nexus\anna) – beides muss greifen.
    await tippe('NEXUS');
    check('Anzeigename wird mitdurchsucht', namen() === 'anna', namen());
    await tippe('AnNa');
    check('Gross-/Kleinschreibung egal', namen() === 'anna', namen());
    await tippe('gibtsnicht');
    check('keine Zeile bei fehlendem Treffer', namen() === '', namen());
    check('Hinweis nennt den Suchbegriff',
          /gibtsnicht/.test(doc.querySelector('.pt-usr-empty').textContent),
          doc.querySelector('.pt-usr-empty').textContent);
    await tippe('');
    check('Leeren zeigt wieder alle', namen() === 'anna,bob,clara,dora', namen());
    check('Zaehler wieder online/gesamt', $('pt-usr-count').textContent === '3/4',
          $('pt-usr-count').textContent);

    section('13. Filter und Panel-Verhalten');
    await tippe('cl');
    // Der Poll darf den Filter nicht zuruecksetzen – sonst springt die Liste
    // spaetestens nach 30 Sekunden auf.
    window.UserSessions.load();
    await sleep(80);
    check('Filter ueberlebt den Abruf', namen() === 'clara', namen());
    // FALLSTRICK: Wer tippt, bewegt die Maus – ein per Hover geoeffnetes Panel
    // wuerde mitten in der Eingabe zufallen.
    hover(window, $('pt-usr-wrap'), 'mouseenter');
    feld.dispatchEvent(new window.FocusEvent('focus', { bubbles: false }));
    hover(window, $('pt-usr-wrap'), 'mouseleave');
    await sleep(500);
    check('Panel bleibt offen, solange das Feld den Fokus hat',
          !$('pt-usr-panel').hasAttribute('hidden'));
    // Escape leert zuerst den Filter …
    const esc = () => feld.dispatchEvent(new window.KeyboardEvent('keydown',
        { key: 'Escape', bubbles: true, cancelable: true }));
    esc();
    await sleep(20);
    check('Escape leert den Filter', feld.value === '' && namen() === 'anna,bob,clara,dora',
          feld.value + ' / ' + namen());
    check('Panel dabei noch offen', !$('pt-usr-panel').hasAttribute('hidden'));
    // … und schliesst erst beim zweiten Mal das Panel.
    esc();
    await sleep(20);
    check('zweites Escape schliesst das Panel', $('pt-usr-panel').hasAttribute('hidden'));

    section('14. Filter wird beim Schliessen zurueckgesetzt');
    $('pt-usr-btn').click();
    await sleep(60);
    await tippe('bob');
    check('gefiltert', namen() === 'bob', namen());
    window.UserSessions.close();
    $('pt-usr-btn').click();
    await sleep(80);
    check('Feld beim Wiederoeffnen leer', feld.value === '', feld.value);
    check('vollstaendige Liste', namen() === 'anna,bob,clara,dora', namen());

    section('15. Leere Liste: kein Filterfeld');
    window.fetch = function (url, opts) {
        if (String(url).indexOf('/api/sessions') === 0 && (!opts || !opts.method)) {
            return Promise.resolve({ ok: true, status: 200,
                json: () => Promise.resolve(Object.assign({}, USERS,
                    { users: [], online: 0, total: 0 })) });
        }
        return alteFetch(url, opts);
    };
    window.UserSessions.load();
    await sleep(80);
    check('Filterfeld ausgeblendet', $('pt-usr-filter').style.display === 'none',
          $('pt-usr-filter').style.display);
    check('Hinweis auf leere Liste', !!doc.querySelector('.pt-usr-empty'));

    section('16. Untaetigkeit: Aussage ab 5 Min., Warnfarbe erst ab 30 Min.');
    // In einer Liste mit zwanzig Anmeldungen ist die Mehrheit fast immer laenger
    // als fuenf Minuten untaetig. Faerbte man ab da, waere die halbe Liste orange
    // und die Warnfarbe saegte sich selbst ab. Die AUSSAGE muss trotzdem stehen.
    const jetzt = Date.now() / 1000;
    const bands = {
        ok: true, online_window: 120, online: 4, total: 4, may_block: true,
        users: [
            // frisch (unter 5 Min.): gar keine Untaetigkeits-Meldung
            { username: 'frisch', display: 'frisch', online: true, kind: 'user',
              last_login: jetzt - 900, last_seen: jetzt - 2, last_action: jetzt - 120,
              last_action_label: 'Chat-Anfrage', idle_seconds: 120 },
            // knapp darueber: Meldung ja, Warnfarbe nein
            { username: 'mittel', display: 'mittel', online: true, kind: 'user',
              last_login: jetzt - 900, last_seen: jetzt - 2, last_action: jetzt - 600,
              last_action_label: 'Wissen', idle_seconds: 600 },
            // genau an der Grenze: gehoert schon zur Warnung (>=, nicht >)
            { username: 'grenze', display: 'grenze', online: true, kind: 'user',
              last_login: jetzt - 3600, last_seen: jetzt - 2, last_action: jetzt - 1800,
              last_action_label: 'Support-Suche', idle_seconds: 1800 },
            // deutlich darueber
            { username: 'lange', display: 'lange', online: true, kind: 'user',
              last_login: jetzt - 9000, last_seen: jetzt - 2, last_action: jetzt - 5400,
              last_action_label: 'Datei gespeichert', idle_seconds: 5400 },
        ],
    };
    window.fetch = function (url, opts) {
        if (String(url).indexOf('/api/sessions') === 0 && (!opts || !opts.method)) {
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(bands) });
        }
        return alteFetch(url, opts);
    };
    window.UserSessions.load();
    await sleep(80);
    const idleEl = (u) => finde0(u).querySelector('.pt-usr-idle');
    const mtxt = (u) => finde0(u).querySelector('.pt-usr-meta').textContent.replace(/\s+/g, ' ');
    check('unter 5 Min.: gar keine Untaetigkeits-Meldung', !idleEl('frisch'), mtxt('frisch'));
    check('unter 5 Min.: stattdessen die Handlung', /zuletzt/.test(mtxt('frisch')), mtxt('frisch'));
    check('10 Min.: Aussage vorhanden', !!idleEl('mittel'), mtxt('mittel'));
    check('10 Min.: NICHT als Warnung gefaerbt',
          idleEl('mittel') && idleEl('mittel').className.indexOf('is-warn') === -1,
          idleEl('mittel') && idleEl('mittel').className);
    check('30 Min. (Grenze): als Warnung gefaerbt',
          idleEl('grenze') && idleEl('grenze').className.indexOf('is-warn') !== -1,
          idleEl('grenze') && idleEl('grenze').className);
    check('90 Min.: als Warnung gefaerbt',
          idleEl('lange') && idleEl('lange').className.indexOf('is-warn') !== -1,
          idleEl('lange') && idleEl('lange').className);
    check('Handlung wird in jedem Band benannt',
          /Wissen/.test(mtxt('mittel')) && /Datei gespeichert/.test(mtxt('lange')));
    // Die Farbe darf nicht die einzige Unterscheidung sein – der Text nennt in
    // beiden Baendern die Dauer.
    check('Dauer steht im Text, nicht nur in der Farbe',
          /untätig seit 10 Min/.test(mtxt('mittel')) && /untätig seit 1 Std\. 30 Min/.test(mtxt('lange')),
          mtxt('mittel') + ' | ' + mtxt('lange'));
    const cssIdle = fs.readFileSync(path.join(ROOT, 'frontend', 'portal.html'), 'utf8');
    check('CSS: Warnfarbe haengt an .is-warn',
          /\.pt-usr-idle\.is-warn\s*\{[^}]*var\(--warning\)/.test(cssIdle));
    check('CSS: Grundfarbe ist NICHT die Warnfarbe',
          /\.pt-usr-idle\s*\{[^}]*var\(--text-secondary\)/.test(cssIdle));

    const ok = results.filter((r) => r.ok).length;
    console.log('\n' + '='.repeat(70));
    console.log(`ERGEBNIS: ${ok}/${results.length} Pruefungen bestanden`);
    console.log('='.repeat(70));
    if (ok !== results.length) {
        results.filter((r) => !r.ok).forEach((r) => console.log('  FEHLGESCHLAGEN: ' + r.name + ' – ' + r.detail));
    }
    return ok === results.length;
}

main()
    .then((ok) => { schliessen(); process.exit(ok ? 0 : 1); })
    .catch((e) => { console.error(e); schliessen(); process.exit(1); });

function schliessen() {
    try { if (globalThis.__dom) globalThis.__dom.window.close(); } catch (e) { /* egal */ }
}
