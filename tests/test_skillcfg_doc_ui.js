/* UI-Test: Hover-Vorschau fuer Skill-Anleitungen + Kopier-Knopf (jsdom).
 *
 * Kern der Pruefung: der Knopf muss den ROHTEXT der Markdown-Datei in die
 * Zwischenablage legen – nicht den gerenderten HTML-Inhalt und nicht den
 * sichtbaren Text. Die Anleitung enthaelt fertige LLM-Prompts; wer sie
 * weiterreicht, braucht das Original.
 *
 * WICHTIG: am Ende window.close() + process.exit() (siehe CLAUDE.md,
 * "jsdom-Tests beenden sich NICHT von selbst").
 *
 * Lauf:  timeout 60 node tests/test_skillcfg_doc_ui.js
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

// Ein Ausschnitt in der Form der echten Anleitung: Ueberschriften, Tabelle,
// Codeblock mit einem Prompt – genau das, was kopiert werden soll.
const MD = [
    '# Eigenen Avatar gestalten',
    '',
    '| Weg | Aufwand |',
    '|---|---|',
    '| Firmenlogo | gering |',
    '',
    '## Prompt fuer ein Bildmodell',
    '',
    '```',
    'Zeichne eine freundliche Bueroklammer-Figur, seitlich, 124x93 Pixel,',
    'transparenter Hintergrund, acht Einzelbilder fuer eine Winke-Animation.',
    '```',
    '',
    'Fertig.',
].join('\n');

async function baueSeite() {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
    const dom = new JSDOM(html, { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const { window } = dom;
    window.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');

    const calls = [];
    window.fetch = function (url, opts) {
        calls.push(String(url));
        const j = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
        const u = String(url);
        if (u.indexOf('/api/skills/doc') === 0) return j({ ok: true, name: 'AVATAR-DESIGN.md', text: MD });
        if (u.indexOf('/api/skills') === 0) return j({ skills: [] });
        return j({ ok: true });
    };

    // Zwischenablage mitschreiben (jsdom hat keine echte).
    const kopiert = [];
    window.navigator.clipboard = { writeText: (t) => { kopiert.push(t); return Promise.resolve(); } };

    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8'));
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/chatlib.js'), 'utf8'));
    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8'));
    return { dom, window, calls, kopiert };
}

async function main() {
    console.log('='.repeat(70));
    console.log('UI-Test Anleitungs-Vorschau + Kopieren (jsdom)');
    console.log('='.repeat(70));

    const { dom, window, calls, kopiert } = await baueSeite();
    globalThis.__dom = dom;
    const doc = window.document;

    section('Aufbau');
    check('chatlib bereitgestellt',
          !!(window.JarvisChatLib && window.JarvisChatLib.renderMarkdown), 'fehlt');
    check('Zwischenablage-Helfer vorhanden',
          !!(window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard));

    // Beschreibung mit Pfad einsetzen (wie sie aus dem Skill-Manifest kaeme)
    const ziel = doc.createElement('div');
    ziel.innerHTML = '<div class="kb-hint">Anleitung: '
        + '<span class="skcfg-doc" data-skill="avatar" data-file="AVATAR-DESIGN.md">'
        + 'skills/avatar/AVATAR-DESIGN.md</span></div>';
    doc.body.appendChild(ziel);
    const pfad = doc.querySelector('.skcfg-doc');

    section('Vorschau oeffnen');
    // mouseover ist delegiert am document – bindDocPreview() laeuft beim Rendern
    // eines Reiters. Hier direkt anstossen, weil kein Reiter gebaut wird.
    window.SkillCfg && window.SkillCfg.render ? null : null;
    pfad.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    await sleep(120);
    let box = doc.querySelector('.skcfg-docbox');
    check('Vorschau-Container entsteht', !!box);
    if (!box) { return ende(); }
    check('Datei wurde geladen', calls.some((u) => u.indexOf('/api/skills/doc') === 0),
          JSON.stringify(calls));
    check('Kopf nennt den Dateinamen',
          /AVATAR-DESIGN\.md/.test(box.querySelector('.skcfg-doc-head').textContent));
    check('Zeilenzahl angezeigt',
          /14 /.test(box.querySelector('.skcfg-doc-meta').textContent),
          box.querySelector('.skcfg-doc-meta').textContent);
    check('Markdown gerendert (Ueberschrift)',
          box.querySelectorAll('.skcfg-doc-body h1, .skcfg-doc-body h2').length >= 2,
          String(box.querySelectorAll('.skcfg-doc-body h1, .skcfg-doc-body h2').length));
    check('Codeblock gerendert', box.querySelectorAll('.skcfg-doc-body pre').length >= 1);

    section('Kopier-Knopf');
    const btn = box.querySelector('.skcfg-doc-copy');
    check('Knopf vorhanden', !!btn);
    check('Knopf hat Beschriftung fuer Hilfsmittel',
          btn && /kopieren/i.test(btn.getAttribute('aria-label') || ''), btn && btn.getAttribute('aria-label'));
    check('Symbol, kein Text', btn && btn.textContent.trim() === '⧉', btn && btn.textContent);

    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(80);
    check('genau einmal kopiert', kopiert.length === 1, String(kopiert.length));
    // DER KERN: Rohtext, nicht das gerenderte HTML.
    check('kopiert wurde der ROHTEXT', kopiert[0] === MD,
          JSON.stringify((kopiert[0] || '').slice(0, 60)));
    check('enthaelt den Prompt woertlich',
          (kopiert[0] || '').indexOf('Zeichne eine freundliche Bueroklammer-Figur') !== -1);
    check('kein HTML darin', !/<h1|<table|<pre/.test(kopiert[0] || ''));
    check('Rueckmeldung am Knopf', btn.textContent.trim() === '✓' && btn.className.indexOf('is-ok') !== -1,
          btn.textContent + ' / ' + btn.className);

    await sleep(1600);
    check('Knopf faellt zurueck', btn.textContent.trim() === '⧉' && btn.className.indexOf('is-ok') === -1,
          btn.textContent + ' / ' + btn.className);

    section('Fehlerfall');
    window.navigator.clipboard = { writeText: () => Promise.reject(new Error('verweigert')) };
    // execCommand-Rueckfall in jsdom: nicht vorhanden -> false
    window.document.execCommand = () => false;
    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await sleep(80);
    check('Fehler wird am Knopf gezeigt',
          btn.textContent.trim() === '✕' && btn.className.indexOf('is-fail') !== -1,
          btn.textContent + ' / ' + btn.className);
    check('nichts zusaetzlich kopiert', kopiert.length === 1, String(kopiert.length));

    section('Nicht lesbare Datei');
    window.fetch = function (url) {
        if (String(url).indexOf('/api/skills/doc') === 0) {
            return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ ok: false }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    };
    const pfad2 = doc.createElement('span');
    pfad2.className = 'skcfg-doc';
    pfad2.setAttribute('data-skill', 'avatar');
    pfad2.setAttribute('data-file', 'GIBTSNICHT.md');
    doc.body.appendChild(pfad2);
    pfad2.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    await sleep(120);
    box = doc.querySelector('.skcfg-docbox');
    check('Hinweis statt Inhalt', /nicht gefunden|not found/i.test(box.textContent), box.textContent.slice(0, 60));
    check('kein Kopier-Knopf ohne Inhalt', !box.querySelector('.skcfg-doc-copy'));

    return ende();
}

function ende() {
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
