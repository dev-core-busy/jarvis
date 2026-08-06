/* UI-Test: PowerPoint-Vorlagen im Branding-Reiter.
 *
 * Gegen die ECHTEN Dateien (frontend/settings.html + js/branding.js), fetch als
 * Attrappe. Geprüft wird die gerenderte Liste – Quelltext-Prüfungen dafür
 * liegen in tests/test_office_vorlage.py.
 *
 * Lauf:  timeout 60 node tests/test_branding_pptx_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

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

/* settings.html wird OHNE app.js geladen (das würde fremde Poll-Timer starten,
 * gleiche Begründung wie im SAP-UI-Test). branding.js allein genügt: der
 * Vorlagen-Abschnitt hängt nur an BrandingAdmin. */
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
    w.eval(I18N);
    w.eval(BRANDING);
    return { dom, w, rufe };
}

const LISTE = {
    success: true,
    default_name: 'standard.pptx',
    default_exists: true,
    accent: '9B59B6',
    templates: [
        { name: 'standard.pptx', size: 27516, mtime: 1786042093, is_default: true },
        { name: 'Nexus_Design_2026.pptx', size: 51200, mtime: 1786043037, is_default: false },
    ],
};

section('1. Markup im Branding-Reiter');
{
    const { w } = fenster({});
    const d = w.document;
    check('Datei-Auswahl vorhanden', !!d.getElementById('br-pptx-file'));
    check('…nimmt nur Vorlagen an',
        /pptx/.test(d.getElementById('br-pptx-file').getAttribute('accept') || ''));
    check('Kästchen „Als Hausvorlage" vorhanden und vorausgewählt',
        d.getElementById('br-pptx-default') && d.getElementById('br-pptx-default').checked);
    check('Knopf „neu erzeugen" vorhanden', !!d.getElementById('br-pptx-regen'));
    check('Listen-Container vorhanden', !!d.getElementById('br-pptx-list'));
    check('Abschnitt liegt IM Branding-Reiter',
        !!d.querySelector('#settings-tab-branding #br-pptx-list'));
    const ueber = d.querySelector('[data-i18n="branding.pptx_heading"]');
    check('Überschrift ist i18n-verdrahtet', !!ueber);
    check('Hinweistext ist i18n-verdrahtet',
        !!d.querySelector('[data-i18n="branding.pptx_hint"]'));
    // Keine harten Farben (Branding-/Theme-Regel des Projekts)
    const block = HTML.slice(HTML.indexOf('branding.pptx_heading'),
                            HTML.indexOf('branding.contact_heading'));
    check('keine harten Farben im neuen Markup', !/#[0-9a-fA-F]{6}/.test(block),
        (block.match(/#[0-9a-fA-F]{6}/) || [''])[0]);
}

section('2. Liste rendern');
{
    const { w } = fenster({ '/api/branding/pptx-templates': LISTE });
    w.brandingAdmin.renderPptxTemplates(LISTE);
    const box = w.document.getElementById('br-pptx-list');
    check('zwei Zeilen', box.children.length === 2, String(box.children.length));
    const t1 = box.children[0].textContent;
    check('Hausvorlage ist als solche gekennzeichnet', /Hausvorlage/.test(t1), t1);
    check('Name steht in der Zeile', /standard\.pptx/.test(t1));
    check('Größe in KB', /27 KB/.test(t1), t1);
    check('Datum vorhanden', /\d{1,4}[./]\d{1,2}[./]\d{1,4}/.test(t1), t1);
    check('zweite Zeile ohne Abzeichen', !/Hausvorlage/.test(box.children[1].textContent));
    check('je Zeile ein Entfernen-Knopf',
        box.querySelectorAll('button').length === 2);

    // Leere Liste
    w.brandingAdmin.renderPptxTemplates({ success: true, templates: [] });
    check('leere Liste zeigt einen Hinweis, keine Tabelle',
        /automatisch erzeugt/.test(box.textContent), box.textContent.slice(0, 60));

    // Fremdinhalt: der Name kommt aus einem Upload
    w.brandingAdmin.renderPptxTemplates({
        success: true,
        templates: [{ name: '<img src=x onerror=alert(1)>.pptx', size: 1024, mtime: 0 }],
    });
    check('Vorlagenname wird NICHT als HTML eingesetzt',
        !box.querySelector('img') && /<img/.test(box.textContent),
        box.innerHTML.slice(0, 80));
}

section('3. Hochladen');
{
    const { w, rufe } = fenster({ '/api/branding/pptx-template': {
        success: true, name: 'standard.pptx', is_default: true,
        layout_count: 11, ratio: '16:9', hints: [],
    } });
    const st = w.document.getElementById('br-status');
    const datei = new w.File(['xx'], 'Nexus Design.pptx', { type: '' });
    const ev = { target: { files: [datei], value: 'x' } };
    w.brandingAdmin.uploadPptxTemplate(ev);
    const post = rufe.find((r) => r.method === 'POST');
    check('POST auf den Vorlagen-Endpunkt', !!post && /pptx-template/.test(post.url),
        post && post.url);
    check('as_default aus dem Kästchen mitgeschickt',
        post && post.body && post.body.get('as_default') === 'true',
        post && post.body && String(post.body.get('as_default')));
    check('Datei im Formular', post && post.body && !!post.body.get('file'));
    return new Promise((r) => setTimeout(r, 30)).then(() => {
        check('Rückmeldung nennt Layout-Anzahl und Format',
            /11 Layouts/.test(st.textContent) && /16:9/.test(st.textContent),
            st.textContent);
        weiter();
    });
}

function weiter() {
    section('4. Entfernen und neu erzeugen');
    {
        const { w, rufe } = fenster({ '/api/branding/pptx-template': { success: true } });
        w.brandingAdmin.deletePptxTemplate('standard.pptx', true);
        check('Entfernen fragt vorher nach', w.__gefragt === 1, String(w.__gefragt));
        const del = rufe.find((r) => r.method === 'DELETE');
        check('DELETE mit kodiertem Namen', !!del && /name=standard\.pptx/.test(del.url),
            del && del.url);
    }
    {
        const { w, rufe } = fenster({ '/api/branding/pptx-template/regenerate': {
            success: true, name: 'standard.pptx', accent: '9B59B6' } });
        w.brandingAdmin.regeneratePptxTemplate();
        check('Neu erzeugen fragt vorher nach (überschreibt eine Firmenvorlage)',
            w.__gefragt === 1, String(w.__gefragt));
        const post = rufe.find((r) => r.method === 'POST');
        check('POST auf /regenerate', !!post && /regenerate/.test(post.url), post && post.url);
    }

    section('5. Sprachumschaltung');
    {
        const { w } = fenster({});
        w.setLang('en');
        const ueber = w.document.querySelector('[data-i18n="branding.pptx_heading"]');
        check('Überschrift folgt der Sprache', /template/i.test(ueber.textContent),
            ueber.textContent);
        w.setLang('de');
        check('…und zurück', /Vorlage/.test(ueber.textContent), ueber.textContent);
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
}
