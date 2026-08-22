/* UI-Test fuer den Bereich "Claude Subagent" (/claude)
 * ───────────────────────────────────────────────────────────────────────────
 * jsdom gegen die ECHTEN Dateien (claude.html, claude_portal.js, i18n.js).
 *
 * WAS DIESER TEST FESTHAELT, in der Reihenfolge der Wichtigkeit:
 *
 * 1. DIE ANLEITUNG UEBERLEBT DEN SPRACHWECHSEL. Sie enthaelt <h4>, <pre> und
 *    eine <table>; haenge sie an `data-i18n` statt `data-i18n-html`, setzt
 *    applyLang() den textContent und die komplette Auszeichnung ist beim ersten
 *    Sprachwechsel weg. Genau dieser Fehler ist im E-Mail-Reiter am 2026-08-13
 *    passiert – ein reiner Schluessel-Abgleich sieht ihn NICHT.
 * 2. Der Schluessel wird genau einmal gezeigt, mit Warnung, und das Panel
 *    erscheint erst nach dem Erzeugen.
 * 3. Fremdinhalt (Auftragstexte) wird maskiert.
 * 4. `applyLang()` loest KEINE Endlosschleife aus (Vorfall 2026-08-18 im
 *    Short-Tracks-Reiter: ueber 40 Abrufe in 250 ms).
 *
 * WICHTIG (Fallstrick 2026-07-30): am Ende window.close() + process.exit(),
 * sonst halten Timer den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 90 node tests/test_claude_subagent_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) {
    console.error('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH setzen).');
    process.exit(2);
}

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;

function check(cond, label, detail) {
    if (cond) { ok++; console.log('  OK   ' + label); }
    else { fail++; console.log('  FAIL ' + label + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n' + t); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));

// ── Attrappe: die Antwortform stammt aus dem Endpunkt-Quelltext, nicht aus
//    dem Gedaechtnis. Ein Mock mit falscher Form prueft nichts (Lehre 2026-08-12).
function baueFetch(zustand) {
    const rufe = [];
    return {
        rufe,
        fn: function (url, opt) {
            const pfad = String(url).split('?')[0];
            rufe.push({ url: String(url), pfad, methode: (opt && opt.method) || 'GET' });
            if (pfad === '/api/claude/status') {
                if (zustand.status403) {
                    return Promise.resolve({ status: 403, ok: false,
                        json: () => Promise.resolve({ detail: 'kein Zugriff' }) });
                }
                return Promise.resolve({
                    status: 200, ok: true, json: () => Promise.resolve({
                        ok: true, skill_aktiv: true,
                        schluessel: zustand.schluessel,
                        jobs: zustand.jobs || [],
                        grenzen: { gleichzeitig: 2, laufzeit_s: 600, max_dateien: 40,
                                   spec_max: 12000, diff_max: 200000 },
                        werkzeuge: ['filesystem', 'shell_execute'],
                    })
                });
            }
            if (pfad === '/api/claude/key') {
                if ((opt && opt.method) === 'DELETE') {
                    zustand.schluessel = null;
                    return Promise.resolve({ status: 200, ok: true,
                        json: () => Promise.resolve({ ok: true }) });
                }
                zustand.schluessel = { kennung: 'abc123', letzte4: 'WXYZ',
                                       erstellt: 1787000000, zuletzt: 0 };
                return Promise.resolve({
                    status: 200, ok: true, json: () => Promise.resolve({
                        ok: true, schluessel: 'CSA-1.abc123.GEHEIMNISWXYZ',
                        kennung: 'abc123', letzte4: 'WXYZ' })
                });
            }
            return Promise.resolve({ status: 200, ok: true,
                json: () => Promise.resolve({ ok: true }) });
        }
    };
}

async function baueSeite(zustand) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend/claude.html'), 'utf8');
    const dom = new JSDOM(html, { url: 'https://jarvis.test/claude',
                                  runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'test-token');
    const f = baueFetch(zustand);
    w.fetch = f.fn;
    w.confirm = () => true;
    w.navigator.clipboard = { writeText: () => Promise.resolve() };
    // i18n zuerst – claude_portal.js benutzt window.t
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/claude_portal.js'), 'utf8'));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await schlaf(40);
    return { dom, w, d: w.document, fetchInfo: f };
}

(async () => {

    // ══════════════════════════════════════════════════════════════════════
    section('1. Die Anleitung ueberlebt den Sprachwechsel');
    {
        const { dom, w, d } = await baueSeite({ schluessel: null, jobs: [] });
        const kasten = d.querySelector('[data-i18n-html="csub.guide_body"]');
        check(!!kasten, 'Anleitungs-Kasten vorhanden');
        check(!d.querySelector('[data-i18n="csub.guide_body"]'),
              'Sie haengt NICHT an data-i18n (das wuerde die Auszeichnung loeschen)');

        for (const lang of ['de', 'en', 'de']) {
            if (w.setLang) w.setLang(lang);
            else if (w.applyLang) w.applyLang();
            await schlaf(15);
            const k = d.querySelector('[data-i18n-html="csub.guide_body"]');
            check(!!k && k.querySelectorAll('h4').length >= 5,
                  `[${lang}] Ueberschriften erhalten`,
                  k ? String(k.querySelectorAll('h4').length) : 'Kasten weg');
            check(!!k && k.querySelectorAll('pre').length >= 2,
                  `[${lang}] Code-Bloecke erhalten`,
                  k ? String(k.querySelectorAll('pre').length) : '-');
            check(!!k && k.querySelectorAll('table').length === 1,
                  `[${lang}] Token-Tabelle erhalten`);
            check(!!k && /800/.test(k.textContent),
                  `[${lang}] Token-Zahl steht drin`);
        }
        // Die Anleitung startet ZUGEKLAPPT – sie ist Nachschlagewerk.
        const karte = d.querySelector('.cs-card[data-klapp="anleitung"]');
        check(!!karte && karte.getAttribute('data-zu') === '1',
              'Anleitung startet zugeklappt');
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('2. Schluessel: einmalige Anzeige');
    {
        const { dom, w, d, fetchInfo } = await baueSeite({ schluessel: null, jobs: [] });
        const box = d.getElementById('cs-key-box');
        check(box && box.hidden, 'Schluessel-Kasten ist anfangs verborgen');
        check(/keinen Schl/i.test(d.getElementById('cs-key-meta').textContent),
              'Meldung "noch keinen Schluessel"');
        check(/kein Schl/i.test(d.getElementById('cs-key-pill').textContent),
              'Pille sagt "kein Schluessel"');
        check(d.getElementById('cs-key-del').hidden, 'Loeschen-Knopf verborgen');

        d.getElementById('cs-key-new').click();
        await schlaf(60);
        check(!d.getElementById('cs-key-box').hidden, 'Kasten erscheint nach dem Erzeugen');
        check(d.getElementById('cs-key-value').textContent === 'CSA-1.abc123.GEHEIMNISWXYZ',
              'Der Schluessel steht im Klartext da');
        const posts = fetchInfo.rufe.filter(r => r.pfad === '/api/claude/key' && r.methode === 'POST');
        check(posts.length === 1, 'Genau EIN POST auf /api/claude/key', String(posts.length));
        check(!d.getElementById('cs-key-del').hidden, 'Loeschen-Knopf jetzt sichtbar');
        check(/nie wieder/i.test(d.querySelector('.cs-key-warn').textContent),
              'Warnung "wird nie wieder angezeigt"');
        check(/…WXYZ|WXYZ/.test(d.getElementById('cs-key-meta').textContent),
              'Meta nennt nur die letzten 4 Zeichen');
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('3. Auftragsliste: Fremdinhalt wird maskiert');
    {
        const boese = '<img src=x onerror=alert(1)>';
        const { dom, d } = await baueSeite({
            schluessel: { kennung: 'k', letzte4: 'WXYZ', erstellt: 1787000000, zuletzt: 0 },
            jobs: [
                { id: 'j1', status: 'fertig', spec: boese, riegel: 'tests/t.py',
                  dateien: ['a.py'], erstellt: 1787000000 },
                { id: 'j2', status: 'fehler', spec: 'zweiter', riegel: 'tests/t.js',
                  dateien: [], erstellt: 1787000000, fehler: 'kaputt' },
            ]
        });
        const liste = d.getElementById('cs-jobs-list');
        check(liste.querySelectorAll('.cs-job').length === 2, 'Beide Auftraege gerendert');
        check(liste.querySelectorAll('img').length === 0,
              'Kein <img> aus dem Auftragstext (maskiert)');
        check(liste.textContent.indexOf('onerror') >= 0,
              'Der Text erscheint als Text');
        check(/\(2\)/.test(d.getElementById('cs-jobs-count').textContent),
              'Zaehler zeigt die Anzahl');
        check(/kaputt/.test(liste.textContent), 'Fehlergrund wird angezeigt');
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('4. Kein Endlos-Neuladen bei applyLang');
    {
        const { dom, w, fetchInfo } = await baueSeite({ schluessel: null, jobs: [] });
        const vorher = fetchInfo.rufe.filter(r => r.pfad === '/api/claude/status').length;
        for (let i = 0; i < 5; i++) { if (w.applyLang) w.applyLang(); }
        await schlaf(150);
        const nachher = fetchInfo.rufe.filter(r => r.pfad === '/api/claude/status').length;
        check(nachher === vorher,
              'applyLang() loest keinen erneuten Statusabruf aus',
              `${vorher} -> ${nachher}`);
        check(vorher === 1, 'Beim Aufbau genau EIN Statusabruf', String(vorher));
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('5. Ohne Freigabe: Klartext statt leerer Seite');
    {
        const { dom, d } = await baueSeite({ status403: true });
        check(/Kein Zugriff/i.test(d.body.textContent),
              'Meldung nennt die fehlende Freigabe');
        check(/Berechtigungen/i.test(d.body.textContent),
              '... und den Weg dorthin');
        dom.window.close();
    }

    // ══════════════════════════════════════════════════════════════════════
    section('6. Der Einstellungs-Reiter ist VOLLSTAENDIG verdrahtet');
    // Ein Reiter braucht FUENF Eintraege an vier Stellen. Fehlt einer, gibt es
    // ihn stillschweigend nicht – genau das ist hier passiert, obwohl Manifest
    // und Berechtigungs-Hinweis ihn ausdruecklich nennen ("im Reiter Claude
    // Subagent einstellen"). Wieder die Fehlerklasse "eine Zusage, die der Code
    // nicht haelt".
    {
        const settings = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
        const skillcfg = fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8');
        const skillsjs = fs.readFileSync(path.join(ROOT, 'frontend/js/skills.js'), 'utf8');
        const appjs    = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');

        check(/claude_subagent:\s*\{\s*container:\s*'skcfg-claude_subagent'/.test(skillcfg),
              'skillcfg.js TARGETS kennt den Container');
        check(/claude_subagent:\s*'settings-tab-btn-claudesub'/.test(skillcfg),
              'skillcfg.js TAB_BUTTONS kennt den Knopf');
        check(/claude_subagent:\s*'claude_subagent'/.test(skillsjs),
              'skills.js SKILL_TABS kennt den Reiter (Zahnrad springt dorthin)');
        check(/SKILLCFG_TABS[\s\S]{0,240}'claude_subagent'/.test(appjs),
              'app.js SKILLCFG_TABS kennt den Reiter');
        check(settings.indexOf('id="settings-tab-btn-claudesub"') >= 0,
              'settings.html hat den Reiter-Knopf');
        check(settings.indexOf('id="settings-tab-claude_subagent"') >= 0,
              'settings.html hat das Reiter-Panel');
        check(settings.indexOf('id="skcfg-claude_subagent"') >= 0,
              'settings.html hat den Formular-Container');

        // GENERISCH, damit der naechste Skill nicht denselben Weg geht: jede
        // Knopf-ID aus TAB_BUTTONS und jeder Container aus TARGETS muss es im
        // Markup wirklich geben. Eine ID, die nur in einer der beiden Dateien
        // steht, faellt sonst niemandem auf.
        const knopfIds = [...skillcfg.matchAll(/'(settings-tab-btn-[a-z0-9-]+)'/g)].map(m => m[1]);
        const fehlendeKnoepfe = knopfIds.filter(id => settings.indexOf('id="' + id + '"') < 0);
        check(fehlendeKnoepfe.length === 0,
              `Alle ${knopfIds.length} TAB_BUTTONS-Knoepfe existieren im Markup`,
              fehlendeKnoepfe.join(', '));

        const container = [...skillcfg.matchAll(/container:\s*'(skcfg-[a-z0-9_-]+)'/g)].map(m => m[1]);
        const fehlendeCont = container.filter(id => settings.indexOf('id="' + id + '"') < 0);
        check(fehlendeCont.length === 0,
              `Alle ${container.length} TARGETS-Container existieren im Markup`,
              fehlendeCont.join(', '));

        // ── UND ER MUSS AUCH WIRKLICH ERSCHEINEN ──────────────────────────
        // Markup allein beweist nichts: der Knopf steht auf display:none und
        // wird erst von SkillCfg.updateTabs() eingeblendet. Genau diese
        // Pruefung fehlte, als der Reiter gemeldet wurde.
        {
            const dom2 = new JSDOM(settings, { url: 'https://jarvis.test/settings',
                                               runScripts: 'outside-only' });
            const w2 = dom2.window;
            w2.localStorage.setItem('jarvis_token', 't');
            w2.fetch = (u) => {
                u = String(u).split('?')[0];
                if (u === '/api/skills') return Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve({ skills: [{
                        dir_name: 'claude_subagent', name: 'Claude Subagent',
                        enabled: true, installed: true,
                        config_schema: { gleichzeitig: { type: 'number', default: 2 } } }] }) });
                return Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve({ config: {} }) });
            };
            w2.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8'));
            w2.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8'));
            const knopf = w2.document.getElementById('settings-tab-btn-claudesub');
            check(knopf && knopf.style.display === 'none',
                  'Reiter-Knopf startet verborgen');
            if (w2.SkillCfg && w2.SkillCfg.updateTabs) await w2.SkillCfg.updateTabs();
            await schlaf(120);
            check(!!knopf && knopf.style.display !== 'none',
                  'updateTabs() blendet ihn bei AKTIVEM Skill ein',
                  knopf ? knopf.style.display : 'Knopf weg');
            dom2.window.close();
        }

        // Die Beschriftung darf nicht als roher Text festhaengen.
        const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        check((i18n.match(/'settings\.tab\.claude_subagent'/g) || []).length === 2,
              'Reiter-Beschriftung in DE und EN');

        // Und die Zusage im Manifest muss zum Reiter passen.
        const manifest = JSON.parse(fs.readFileSync(
            path.join(ROOT, 'skills/claude_subagent/skill.json'), 'utf8'));
        const nenntReiter = JSON.stringify(manifest).indexOf('Reiter') >= 0;
        check(!nenntReiter || settings.indexOf('id="settings-tab-claude_subagent"') >= 0,
              'Wenn das Manifest einen Reiter nennt, gibt es ihn auch');
    }

    // ══════════════════════════════════════════════════════════════════════
    section('7. Im Branding-Fall steht der Markenname da, nicht "Jarvis"');
    // branding.js ersetzt "Jarvis" nur in .brand-app-name, im Seitentitel und in
    // Platzhalter-Attributen. Text, den applyLang() aus i18n.js setzt, erreicht
    // es NICHT – ein White-Label-System verriete dort das Produkt dahinter.
    // Deshalb schreiben die Texte {marke}; branding.js loest es zentral auf.
    {
        const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        const seite = fs.readFileSync(path.join(ROOT, 'frontend/claude.html'), 'utf8');

        // Kein rohes "Jarvis" mehr in den eigenen Texten – ausser im
        // brand-app-name-Span, den branding.js selbst bedient.
        const eigene = [...i18n.matchAll(
            /'(csub\.[a-z_]+|portal\.card_claudesub[a-z_]*)':\s*'((?:[^'\\]|\\.)*)'/g)];
        check(eigene.length >= 20, 'Eigene i18n-Schluessel gefunden', String(eigene.length));
        const mitJarvis = eigene.filter(m => m[2].indexOf('Jarvis') >= 0).map(m => m[1]);
        check(mitJarvis.length === 0,
              'Kein rohes "Jarvis" in den eigenen i18n-Texten',
              [...new Set(mitJarvis)].join(', '));
        // JS-BEZEICHNER sind kein Anzeigetext: `window.JarvisIssues` ist der
        // globale Name aus issues.js und wird von sechs weiteren Seiten
        // benutzt – ihn umzubenennen waere Unsinn. Geprueft wird der TEXT.
        const ohneSpan = seite
            .replace(/<span class="brand-app-name">Jarvis<\/span>/g, '')
            .replace(/window\.Jarvis[A-Za-z]*/g, '')
            .replace(/jarvis_theme/g, '');
        check(ohneSpan.indexOf('Jarvis') < 0,
              'Kein rohes "Jarvis" im ANZEIGETEXT von claude.html',
              (ohneSpan.match(/.{0,25}Jarvis.{0,25}/) || [''])[0]);

        // Die technischen Kennungen duerfen NICHT gebrandet werden – sie sind
        // Teil des Protokolls bzw. Dateinamen auf dem Rechner des Benutzers.
        // ── DIE KENNUNGEN TRAGEN DEN MARKENNAMEN ──────────────────────────
        // NICHT neutralisieren (das war ein Missverstaendnis meinerseits): der
        // Benutzer LIEST sie in der Anleitung, und der Schluessel selbst faengt
        // damit an. Sie tragen deshalb den Platzhalter, den branding.js mit dem
        // ASSISTENTEN-NAMEN fuellt.
        check(i18n.indexOf('{MARKE}_CSA_KEY') >= 0 && i18n.indexOf('{marke_slug}-csa-url') >= 0,
              'Anleitung nennt die Kennungen mit Marken-Platzhalter');
        const neutral = ['SUBAGENT_KEY', 'SUBAGENT_URL', '.subagent-key', '.subagent-url'];
        const nRest = neutral.filter(k => i18n.indexOf(k) >= 0 || seite.indexOf(k) >= 0);
        check(nRest.length === 0, 'Keine neutralisierten Kennungen mehr', nRest.join(', '));

        // ── VERHALTEN, nicht Schreibweise: loest branding.js den Platzhalter? ──
        for (const fall of [
            { label: 'ohne Branding', b: { active: false }, erwartet: 'Jarvis' },
            // NUR Firmenname -> weiterhin "Jarvis". KEIN Rueckfall auf den
            // Firmennamen (Vorgabe des Nutzers): das Feld heisst "Name des
            // Assistenten" und ist genau dafuer da; der Firmenname ist das
            // Unternehmen, nicht der Assistent.
            { label: 'nur Firmenname', b: { active: true, company_name: 'Nexus AG' },
              erwartet: 'Jarvis' },
            { label: 'mit Assistenten-Name', b: { active: true, company_name: 'Nexus AG',
              assistant_name: 'Nexi' }, erwartet: 'Nexi' },
        ]) {
            const dom3 = new JSDOM(
                '<body><p data-i18n-html="x">Codeaufgaben an {marke} abgeben</p>' +
                '<button title="an {marke} senden">k</button></body>',
                { url: 'https://jarvis.test/claude', runScripts: 'outside-only' });
            const w3 = dom3.window;
            w3.fetch = () => Promise.resolve({ ok: true, status: 200,
                                               json: () => Promise.resolve(fall.b) });
            w3.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/branding.js'), 'utf8'));
            await schlaf(120);
            const p3 = w3.document.querySelector('p');
            check(p3.textContent.indexOf('{marke}') < 0,
                  `[${fall.label}] Platzhalter ist aufgeloest`, p3.textContent);
            check(p3.textContent.indexOf(fall.erwartet) >= 0,
                  `[${fall.label}] "${fall.erwartet}" steht im Text`, p3.textContent);
            const b3 = w3.document.querySelector('button');
            check(b3.getAttribute('title').indexOf(fall.erwartet) >= 0,
                  `[${fall.label}] auch im title-Attribut`, b3.getAttribute('title'));
            check(typeof w3.jarvisMarke === 'function' && w3.jarvisMarke() === fall.erwartet,
                  `[${fall.label}] window.jarvisMarke() liefert den Namen`,
                  typeof w3.jarvisMarke === 'function' ? w3.jarvisMarke() : 'fehlt');
            dom3.window.close();
        }

        // applyLang() bringt den Platzhalter zurueck -> muss erneut greifen.
        {
            const dom4 = new JSDOM('<body><p id="z">an {marke} abgeben</p></body>',
                { url: 'https://jarvis.test/claude', runScripts: 'outside-only' });
            const w4 = dom4.window;
            w4.fetch = () => Promise.resolve({ ok: true, status: 200,
                json: () => Promise.resolve({ active: true, company_name: 'Nexus AG',
                                             assistant_name: 'Nexi' }) });
            w4.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/branding.js'), 'utf8'));
            await schlaf(120);
            // So verhaelt sich applyLang: es setzt den i18n-Text NEU.
            w4.document.getElementById('z').textContent = 'an {marke} abgeben';
            w4.dispatchEvent(new w4.Event('jarvis-lang-changed'));
            await schlaf(60);
            check(w4.document.getElementById('z').textContent.indexOf('Nexi') >= 0,
                  'Nach einem Sprachwechsel wird erneut eingesetzt',
                  w4.document.getElementById('z').textContent);
            dom4.window.close();
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    section('8. Titelleiste ist IDENTISCH zu den uebrigen Bereichsseiten');
    // WARUM DAS EIN EIGENER WAECHTER IST: die Regeln fuer .topbar, .btn-theme
    // und .lang-toggle stehen in JEDER Bereichsseite lokal im <style>-Block –
    // es gibt sie nicht in theme.css. Wer eine neue Seite anlegt und nur das
    // MARKUP kopiert, bekommt unformatierte Knoepfe: ein <svg> ohne
    // `.btn-theme svg { width:20px }` hat keine Groesse. Genau so ist
    // /claude entstanden, und es ist im Projekt nicht das erste Mal.
    // Referenz ist tracks.html (die juengste Bereichsseite; email.html traegt
    // beim Knopf noch ein hartes #888899 statt --text-muted).
    {
        const refQ = fs.readFileSync(path.join(ROOT, 'frontend/tracks.html'), 'utf8');
        const ownQ = fs.readFileSync(path.join(ROOT, 'frontend/claude.html'), 'utf8');

        // Deklarationen eines Selektors einsammeln (Reihenfolge egal,
        // Leerraum normalisiert).
        function regeln(quelle, selektor) {
            const re = new RegExp('(?:^|\\})\\s*' +
                selektor.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') +
                '\\s*\\{([^}]*)\\}', 'm');
            const m = quelle.match(re);
            if (!m) return null;
            return m[1].split(';').map(s => s.replace(/\s+/g, ' ').trim())
                       .filter(Boolean).sort().join('; ');
        }

        const pruefen = ['.topbar', '.topbar-left', '.topbar-right', '.topbar-avatar',
                         '.topbar-title', '.btn-theme', '.btn-theme svg',
                         '.lang-toggle', '.lang-toggle-btn'];
        for (const sel of pruefen) {
            const a = regeln(refQ, sel);
            const b = regeln(ownQ, sel);
            check(a !== null, `Referenz tracks.html definiert ${sel}`);
            check(b !== null, `claude.html definiert ${sel}`);
            if (a && b) {
                check(a === b, `${sel} stimmt mit der Referenz ueberein`,
                      b.length > 90 ? b.slice(0, 90) + '…' : b);
            }
        }

        // Die Knopf-Reihenfolge in der Leiste ist Teil der Wiedererkennung:
        // Sprache, Portal, Thema, Abmelden – wer zwischen den Bereichen
        // wechselt, findet sie am selben Platz.
        function leiste(quelle) {
            const m = quelle.match(/<div class="topbar-right">([\s\S]*?)<\/header>/);
            if (!m) return [];
            return [...m[1].matchAll(/(lang-toggle|btn-theme)"[^>]*id="([a-z-]+)"/g)]
                   .map(x => x[2].replace(/^(st|cs|em)-/, ''));
        }
        const lRef = leiste(refQ), lOwn = leiste(ownQ);
        check(lRef.length >= 3 && lOwn.join(',') === lRef.join(','),
              'Gleiche Knoepfe in gleicher Reihenfolge',
              `${lOwn.join(',')} vs ${lRef.join(',')}`);

        // ── DAS ZAHNRAD, AUF JEDER BEREICHSSEITE ───────────────────────────
        // Fehlte auf /claude, /tracks, /email und /excel, waehrend /chat,
        // /portal, /sap, /support, /userchat und /wissen es hatten. Wer aus
        // einem Bereich in die Einstellungen will, musste dort ueber das
        // Portal – auf jeder zweiten Seite anders. Zweimal vom Nutzer gemeldet.
        //
        // GENERISCH statt Aufzaehlung: JEDE Seite mit Titelleiste UND
        // Abmelden-Knopf ist eine Bereichsseite und braucht das Zahnrad. Damit
        // faellt auch eine KUENFTIGE Seite auf, ohne dass jemand diese Liste
        // pflegt (Doku-Seiten wie api.html haben keine Titelleiste und fallen
        // von selbst heraus).
        {
            const seiten = fs.readdirSync(path.join(ROOT, 'frontend'))
                .filter(f => f.endsWith('.html') && f !== 'settings.html');
            const bereiche = [];
            for (const f of seiten) {
                const q = fs.readFileSync(path.join(ROOT, 'frontend', f), 'utf8');
                const lo = q.match(/id="([a-z-]*logout[a-z-]*)"/);
                if (!/topbar-right/.test(q) || !lo) continue;
                bereiche.push(f);
                check(/id="[a-z-]*settings[a-z-]*"[^>]*data-i18n-title="nav\.settings"/.test(q)
                      || /data-i18n-title="nav\.settings"/.test(q),
                      `${f}: hat ein Zahnrad in der Titelleiste`);
                // Issues/Feedback gehoert genauso auf JEDE Bereichsseite –
                // es fehlte auf denselben vier Seiten wie das Zahnrad.
                check(/data-i18n-title="sup\.issues"/.test(q),
                      `${f}: hat den Issues-Knopf`);
                check(/js\/issues\.js/.test(q),
                      `${f}: bindet issues.js ein (sonst tut der Knopf nichts)`);
                // Gleiche Reihenfolge wie ueberall: Thema -> Issues -> Zahnrad.
                const pIss = q.search(/data-i18n-title="sup\.issues"/);
                const pSet = q.search(/data-i18n-title="nav\.settings"/);
                check(pIss >= 0 && pSet >= 0 && pIss < pSet,
                      `${f}: Issues steht vor den Einstellungen`);
            }
            check(bereiche.length >= 6,
                  `Bereichsseiten erkannt (${bereiche.length})`, bereiche.join(', '));
        }

        for (const [name, quelle, pfx, ret] of [
            ['claude.html', ownQ, 'cs', '/claude'],
            ['tracks.html', refQ, 'st', '/tracks'],
        ]) {
            check(quelle.indexOf(`id="${pfx}-settings-btn"`) >= 0,
                  `${name}: Zahnrad-Knopf vorhanden`);
            // Es MUSS verborgen starten – sichtbar waere es fuer jeden
            // Nicht-Admin ein Knopf, der in einen 403 laeuft.
            const bl = quelle.match(
                new RegExp(`<button[^>]*id="${pfx}-settings-btn"[^>]*>`));
            check(!!bl && /display:\s*none/.test(bl[0]),
                  `${name}: startet verborgen (nur Admins)`);
            check(!!bl && /data-i18n-title="nav\.settings"/.test(bl[0]),
                  `${name}: Beschriftung ueber den vorhandenen i18n-Key`);
            // ... und es muss VOR dem Abmelden stehen, wie auf allen anderen.
            check(quelle.indexOf(`id="${pfx}-settings-btn"`)
                  < quelle.indexOf(`id="${pfx}-logout-btn"`),
                  `${name}: steht vor dem Abmelden-Knopf`);
        }
        // Verdrahtung: eingeblendet nur bei is_admin, Rueckweg gemerkt.
        for (const [js, ret] of [['frontend/js/claude_portal.js', '/claude'],
                                 ['frontend/js/tracks.js', '/tracks'],
                                 ['frontend/js/email_portal.js', '/email'],
                                 ['frontend/js/excel_portal.js', '/excel']]) {
            const q = fs.readFileSync(path.join(ROOT, js), 'utf8');
            check(/settings-btn/.test(q), `${path.basename(js)}: verdrahtet das Zahnrad`);
            check(q.indexOf(`'jarvis_settings_return', '${ret}'`) >= 0,
                  `${path.basename(js)}: merkt den Rueckweg ${ret}`);
            // Zwei Schreibweisen sind richtig: `ist_admin` kommt aus den
            // Bereichs-Endpunkten (/api/claude|tracks/status), `is_admin` aus
            // /api/me. Beides gattert denselben Knopf.
            check(/\bist?_admin\b|_istAdmin\b/.test(q),
                  `${path.basename(js)}: blendet es nur fuer Administratoren ein`);
        }
    }

    console.log('\n' + '='.repeat(62));
    console.log(`  ${ok} OK, ${fail} FAIL`);
    console.log('='.repeat(62));
    process.exit(fail ? 1 : 0);
})();
