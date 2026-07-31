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
    ok: true, online_window: 120, online: 1, total: 2,
    users: [
        { username: 'anna', display: 'nexus\\anna', online: true, kind: 'user',
          last_login: 1785470000, last_logout: 0, last_seen: Date.now() / 1000 - 5,
          last_ip: '10.0.0.5', logins: 3 },
        { username: 'bob', display: 'bob', online: false, kind: 'user',
          last_login: 1785400000, last_logout: 1785460000, last_seen: 1785460000,
          last_ip: '10.0.0.9', logins: 1 },
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
    check('Liste geladen', doc.querySelectorAll('.pt-usr-item').length === 2,
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
    check('Abmeldezeit sichtbar', /Abmeldung/.test(zeilen[1].textContent), zeilen[1].textContent.slice(0, 60));

    section('5. Rechtsklick meldet ab');
    const vorher = calls.length;
    const ev = new window.MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    zeilen[1].dispatchEvent(ev);
    await sleep(60);
    const kick = calls.slice(vorher).find((c) => c.method === 'POST' && c.url.indexOf('/api/sessions/') === 0);
    check('Standard-Kontextmenue unterdrueckt', ev.defaultPrevented);
    check('Abmelde-Aufruf abgesetzt', !!kick, JSON.stringify(calls.slice(vorher)));
    check('richtiger Benutzer im Pfad', kick && kick.url.indexOf('/api/sessions/bob/logout') === 0,
          kick ? kick.url : '');
    check('Liste danach neu geladen',
          calls.slice(vorher).some((c) => c.method === 'GET' && c.url.indexOf('/api/sessions') === 0));

    section('6. Ohne Bestaetigung kein Abmelden');
    window.confirm = () => false;
    const vorher2 = calls.length;
    doc.querySelectorAll('.pt-usr-item')[0].dispatchEvent(
        new window.MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
    await sleep(60);
    check('kein Aufruf bei Abbruch',
          !calls.slice(vorher2).some((c) => c.method === 'POST'),
          JSON.stringify(calls.slice(vorher2)));

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
