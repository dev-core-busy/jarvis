/* UI-Test: Schriften im Branding-Reiter.
 *
 * Gegen die ECHTEN Dateien (frontend/settings.html + js/branding.js), fetch als
 * Attrappe mit der Antwortform von GET /api/branding/fonts
 * (backend/branding_schriften.zustand). Die Wirkung auf fontconfig misst
 * tests/test_branding_schriften.py.
 *
 * Lauf:  timeout 60 node tests/test_branding_schriften_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const results = [];
function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const BRANDING = fs.readFileSync(path.join(ROOT, 'frontend/js/branding.js'), 'utf8');
const SITZUNG = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');

/* Ohne app.js, wie im PowerPoint-UI-Test: der Abschnitt haengt nur an
 * BrandingAdmin. sitzung.js zuerst, sonst stirbt der Aufbau still. */
function fenster(antworten) {
    const dom = new JSDOM(HTML, { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    w.localStorage.setItem('jarvis_token', 'testtoken');
    w.fetch = function (url, opt) {
        rufe.push({ url: String(url), method: (opt && opt.method) || 'GET', body: opt && opt.body });
        const treffer = Object.keys(antworten).find((k) => String(url).indexOf(k) >= 0);
        const body = treffer ? antworten[treffer] : {};
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
    w.confirm = function () { w.__gefragt = (w.__gefragt || 0) + 1; return true; };
    w.eval(SITZUNG);
    w.eval(I18N);
    w.eval(BRANDING);
    return { dom, w, rufe };
}

const ZUSTAND = {
    fontconfig: true,
    fonts: [
        { name: 'HelveticaNeueLTStd-Roman.otf', size: 52224, mtime: 1786042093,
          schnitte: [{ familien: ['Helvetica Neue LT Std', 'HelveticaNeue LT 55 Roman'],
                       stil: '55 Roman', name: 'HelveticaNeueLTStd-Roman' }] },
    ],
    vorlagen: [
        { name: 'HelveticaNeue LT 75 Bold', gemessen: true, gefunden: false,
          ersatz: 'Noto Sans', datei: 'NotoSans-Regular.ttf', eigene: false },
        { name: 'HelveticaNeue LT 55 Roman', gemessen: true, gefunden: true,
          ersatz: '', datei: 'HelveticaNeueLTStd-Roman.otf', eigene: true },
    ],
};

const warte = () => new Promise((r) => setTimeout(r, 0));

(async function () {
    section('1. Markup im Branding-Reiter');
    {
        const { w } = fenster({});
        const d = w.document;
        const datei = d.getElementById('br-font-file');
        check('Datei-Auswahl vorhanden', !!datei);
        check('…nimmt nur Schriftdateien an',
            datei && /\.ttf/.test(datei.getAttribute('accept') || '')
                && /\.otf/.test(datei.getAttribute('accept') || ''));
        check('Abschnitt liegt IM Branding-Reiter',
            !!d.querySelector('#settings-tab-branding #br-font-list')
                && !!d.querySelector('#settings-tab-branding #br-font-status'));
        check('Überschrift ist i18n-verdrahtet',
            !!d.querySelector('[data-i18n="branding.font_heading"]'));
        check('Hinweistext nennt die Lizenz',
            /Lizenz/.test((d.querySelector('[data-i18n="branding.font_hint"]') || {}).textContent || ''));
        const von = HTML.indexOf('branding.font_heading');
        const block = HTML.slice(von, HTML.indexOf('branding.contact_heading', von));
        check('keine harten Farben im neuen Markup', !/#[0-9a-fA-F]{3,6}\b/.test(block),
            (block.match(/#[0-9a-fA-F]{3,6}\b/) || [''])[0]);
    }

    section('2. Laden beim Öffnen des Reiters');
    {
        const { w, rufe } = fenster({ '/api/branding/fonts': ZUSTAND });
        w.brandingAdmin.load();
        await warte(); await warte();
        check('GET /api/branding/fonts beim Laden', rufe.some((r) => r.method === 'GET'
            && /\/api\/branding\/fonts$/.test(r.url)), rufe.map((r) => r.url).join(' '));
        const st = w.document.getElementById('br-font-status');
        check('Vorlagen-Schriften werden angezeigt', st.children.length === 2,
            String(st.children.length));
    }

    section('3. Anzeige');
    {
        const { w } = fenster({});
        w.brandingAdmin.renderFonts(ZUSTAND);
        const st = w.document.getElementById('br-font-status');
        const fehlt = st.children[0].textContent;
        const da = st.children[1].textContent;
        check('fehlende Schrift nennt die Ersatzschrift', /fehlt/.test(fehlt) && /Noto Sans/.test(fehlt), fehlt);
        check('gefundene Schrift nennt die Datei', /vorhanden/.test(da)
            && /HelveticaNeueLTStd-Roman\.otf/.test(da), da);
        check('Farben aus Theme-Variablen',
            /var\(--warning\)/.test(st.children[0].lastChild.style.cssText)
                && /var\(--success\)/.test(st.children[1].lastChild.style.cssText),
            st.children[0].lastChild.style.cssText);

        const box = w.document.getElementById('br-font-list');
        check('eine Zeile je Datei', box.children.length === 1, String(box.children.length));
        const zeile = box.children[0].textContent;
        check('Zeile nennt Datei, Schnitt und Größe',
            /HelveticaNeueLTStd-Roman\.otf/.test(zeile)
                && /HelveticaNeueLTStd-Roman(?!\.otf)/.test(zeile) && /51 KB/.test(zeile), zeile);
        check('je Zeile ein Entfernen-Knopf', box.querySelectorAll('button').length === 1);

        w.brandingAdmin.renderFonts({ fonts: [], vorlagen: [] });
        check('leere Liste zeigt einen Hinweis', /Noch keine Schrift/.test(box.textContent),
            box.textContent);

        w.brandingAdmin.renderFonts({
            fonts: [{ name: '<img src=x onerror=alert(1)>.ttf', size: 10,
                      schnitte: [{ familien: ['<b>x</b>'], stil: '', name: '' }] }],
            vorlagen: [{ name: '<img src=y>', gemessen: true, gefunden: false, ersatz: '<i>z</i>' }],
        });
        check('Datei- und Familiennamen werden NICHT als HTML eingesetzt',
            !box.querySelector('img') && !box.querySelector('b') && !st.querySelector('img')
                && !st.querySelector('i') && /<img/.test(box.textContent),
            box.innerHTML.slice(0, 80));

        w.brandingAdmin.renderFonts({ fonts: [], vorlagen: [
            { name: 'X', gemessen: false, gefunden: false, ersatz: '' }] });
        check('ohne fontconfig: „nicht prüfbar" statt „fehlt"',
            /nicht prüfbar/.test(st.textContent) && !/fehlt –/.test(st.textContent), st.textContent);
    }

    section('4. Hochladen');
    {
        const { w, rufe } = fenster({
            '/api/branding/font': { success: true, name: 'HelveticaNeueLTStd-Bd.otf',
                schnitte: [{ name: 'HelveticaNeueLTStd-Bd' }] },
        });
        const datei = new w.File(['OTTO'], 'HelveticaNeueLTStd-Bd.otf', { type: '' });
        const ev = { target: { files: [datei], value: 'x' } };
        w.brandingAdmin.uploadFont(ev);
        await warte(); await warte(); await warte();
        const post = rufe.find((r) => r.method === 'POST');
        check('POST auf /api/branding/font', !!post && /\/api\/branding\/font$/.test(post.url),
            post && post.url);
        check('Datei im Formular', post && post.body && !!post.body.get('file'));
        const st = w.document.getElementById('br-status').textContent;
        check('Rückmeldung nennt den erkannten Schnitt', /HelveticaNeueLTStd-Bd/.test(st), st);
        check('Liste wird danach neu geladen',
            rufe.some((r) => r.method === 'GET' && /\/api\/branding\/fonts$/.test(r.url)));
        check('Datei-Auswahl zurückgesetzt', ev.target.value === '');
    }
    {
        const { w } = fenster({ '/api/branding/font': { success: false,
            error: 'Keine Schriftdatei (TrueType/OpenType-Kennung fehlt)' } });
        w.brandingAdmin.uploadFont({ target: { files: [new w.File(['x'], 'a.ttf')], value: 'x' } });
        await warte(); await warte(); await warte();
        const st = w.document.getElementById('br-status').textContent;
        check('Ablehnung des Servers wird angezeigt', /✗/.test(st) && /Kennung/.test(st), st);
    }

    section('5. Entfernen');
    {
        const { w, rufe } = fenster({ '/api/branding/font': { success: true } });
        w.brandingAdmin.renderFonts(ZUSTAND);
        w.document.querySelector('#br-font-list button').click();
        await warte(); await warte();
        check('fragt vorher nach', w.__gefragt === 1, String(w.__gefragt));
        const del = rufe.find((r) => r.method === 'DELETE');
        check('DELETE mit kodiertem Namen',
            !!del && /name=HelveticaNeueLTStd-Roman\.otf$/.test(del.url), del && del.url);
    }

    section('6. Sprache');
    {
        const { w } = fenster({});
        w.setLang('en');
        const ueber = w.document.querySelector('[data-i18n="branding.font_heading"]');
        check('Überschrift folgt der Sprache', ueber.textContent === 'Fonts', ueber.textContent);
        w.brandingAdmin.renderFonts({ fonts: [], vorlagen: [] });
        check('Hinweis in der Liste folgt der Sprache',
            /No font/.test(w.document.getElementById('br-font-list').textContent));
        w.setLang('de');
        check('…und zurück', ueber.textContent === 'Schriften', ueber.textContent);
    }

    const ok = results.filter((r) => r.ok).length;
    const bad = results.length - ok;
    console.log(`\n${'='.repeat(60)}\nErgebnis: ${ok}/${results.length} Pruefungen bestanden`);
    if (bad) {
        console.log(`\x1b[31mFEHLGESCHLAGEN: ${bad}\x1b[0m`);
        results.filter((r) => !r.ok).forEach((r) =>
            console.log('  ✗ ' + r.name + (r.detail ? ' – ' + r.detail : '')));
    }
    process.exit(bad ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (konnte nicht laufen): ' + (e && e.stack || e)); process.exit(2); });
