/* UI-Waechter: Fremdtext in Admin-Oberflaechen bleibt TEXT (Pentest-Vorbereitung 2026-11-05).
 *
 * Befund D6: skills.js setzte Name, Beschreibung, Kategorie, Hilfetexte und
 * Werkzeugnamen aus Skill-Manifesten roh in innerHTML – Manifeste kommen auch
 * aus OpenClaw-Importen, also aus Fremdquellen. Ebenso die Treffer der
 * OpenClaw-Suche und die Agenten-Meldungen im Import-Dialog. knowledge.js
 * setzte den Dateinamen im Datei-Ansichtsfenster roh (Quelle: Dateinamen der
 * Wissensdatenbank, kbmatrix.js). cron.js die Ereignisnamen eines Waechters.
 *
 * GEMESSEN WIRD DIE WIRKUNG am echten Renderer (echte settings.html, echte
 * Module, jsdom): entsteht ein fremdes Element (Markierungs-Attribut)? Und
 * steht der Wert unveraendert als TEXT da (sonst waere „alles weglassen" gruen)?
 *
 * Lauf:  timeout 120 node tests/test_admin_xss_ui.js   (Exit 0/1/2)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail ? ' – ' + detail : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WACHHUND = setTimeout(() => { console.log('ABBRUCH: Lauf haengt (60 s)'); process.exit(2); }, 60000);
process.on('exit', (c) => {
    if (!BILANZ && c === 0) { console.log('ABBRUCH: keine Bilanzzeile'); process.exitCode = 1; }
});

const MARKE = 'data-xss-probe';
const BOESE = (feld) => feld + '<img src=x ' + MARKE + '="' + feld + '">';
const fremde = (root) => root.querySelectorAll('[' + MARKE + ']').length;

const SKILL = {
    name: BOESE('name'), dir_name: 'boese', installed: true, enabled: true,
    category: BOESE('kat'), description: BOESE('desc'), tools: [],
    version: BOESE('ver'), author: BOESE('autor'),
    missing: { apt: [BOESE('apt') + '"' + MARKE + '="t'], pip: [], commands: [] },
    help: {
        details: BOESE('details'), setup: BOESE('setup'), notes: BOESE('notes'),
        use_cases: [BOESE('uc')],
        tools: [{ name: BOESE('tn'), label: BOESE('tl'), desc: BOESE('td') }],
    },
    config_schema: { [BOESE('key') + '"' + MARKE + '="k']: { type: 'string', label: BOESE('label') } },
};
const AVAIL = Object.assign({}, SKILL, { dir_name: 'boese2', installed: false, enabled: false });

(async () => {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
    const dom = new JSDOM(html, { url: 'https://localhost/settings', runScripts: 'outside-only',
        virtualConsole: new VirtualConsole() });
    const w = dom.window, dc = w.document;
    global.window = w; global.document = dc;
    require('./lib/sitzung_laden')(w, { token: 'testtoken' });
    global.fetch = w.fetch = async (u) => ({
        ok: true, status: 200,
        json: async () => (String(u).split('?')[0] === '/api/skills' ? { skills: [SKILL, AVAIL] }
            : String(u).indexOf('/api/knowledge/file_read') === 0 ? { ok: true, content: 'inhalt' }
            : String(u).indexOf('/config') > 0 ? { config: {} } : {}),
    });
    for (const f of ['icons.js', 'i18n.js', 'skills.js', 'knowledge.js', 'cron.js']) {
        w.eval(fs.readFileSync(path.join(ROOT, 'frontend', 'js', f), 'utf8'));
        if (w.JarvisIcons) global.JarvisIcons = w.JarvisIcons;
    }
    if (dc.readyState === 'loading') await new Promise((r) => dc.addEventListener('DOMContentLoaded', r));
    await sleep(10);

    if (typeof w.JarvisSkillManager !== 'function' || !w.knowledgeManager) {
        console.log('ABBRUCH: Module nicht geladen'); process.exit(2);
    }
    const mgr = new w.JarvisSkillManager();
    await mgr.loadSkills();
    await sleep(30);
    const inst = dc.querySelector('#sk-installed-list [data-skill="boese"]');
    const avail = dc.querySelector('#sk-available-list [data-skill="boese2"]');
    if (!inst || !avail) { console.log('ABBRUCH: Positivkontrolle – Skill-Zeilen nicht gerendert'); process.exit(2); }

    console.log('\n1. Skill-Listen (skills.js)');
    check('installierte Zeile: kein fremdes Element/Attribut', fremde(inst) === 0, inst.innerHTML.slice(0, 200));
    check('installierte Zeile: Name steht als Text', (inst.querySelector('.sk-item-name') || {}).textContent === SKILL.name);
    check('installierte Zeile: Beschreibung als Text', (inst.querySelector('.sk-item-desc') || {}).textContent === SKILL.description);
    check('installierte Zeile: Kategorie als Text', (inst.querySelector('.sk-item-cat') || {}).textContent === SKILL.category);
    check('moegliche Zeile: kein fremdes Element', fremde(avail) === 0);
    check('moegliche Zeile: Name als Text', (avail.querySelector('.sk-item-name') || {}).textContent === SKILL.name);

    console.log('\n2. Info-Fenster (Hilfe aus dem Manifest)');
    mgr._showInfo(SKILL);
    const info = dc.getElementById('sk-info-overlay');
    check('Info-Fenster geoeffnet (Positivkontrolle)', !!info);
    check('Info-Fenster: kein fremdes Element', !!info && fremde(info) === 0);
    check('Info-Fenster: Details als Text', !!info && info.textContent.indexOf(SKILL.help.details) >= 0);
    check('Info-Fenster: Werkzeugname als Text', !!info && info.textContent.indexOf(SKILL.help.tools[0].name) >= 0);
    if (info) info.remove();

    console.log('\n3. Konfigurationsdialog (Schluessel/Beschriftung aus dem Manifest)');
    mgr._showConfigDialog('boese<b ' + MARKE + '="n">', SKILL.config_schema, {});
    const dlg = dc.querySelector('.skill-config-overlay');
    check('Dialog geoeffnet (Positivkontrolle)', !!dlg);
    check('Dialog: kein fremdes Element/Attribut', !!dlg && fremde(dlg) === 0, dlg ? dlg.innerHTML.slice(0, 300) : '');
    const feld = dlg && dlg.querySelector('input[type="text"]');
    check('Dialog: Feldname = Schluessel unveraendert', !!feld && feld.getAttribute('name') === Object.keys(SKILL.config_schema)[0]);
    if (dlg) dlg.remove();

    console.log('\n4. Dateiansicht (knowledge.js viewFile)');
    await w.knowledgeManager.viewFile('data/rag/x.md', BOESE('datei'));
    await sleep(10);
    const fv = dc.getElementById('kb-file-view-modal');
    check('Dateiansicht geoeffnet (Positivkontrolle)', !!fv);
    check('Dateiansicht: kein fremdes Element', !!fv && fremde(fv) === 0);
    check('Dateiansicht: Dateiname als Text', !!fv && fv.textContent.indexOf(BOESE('datei')) >= 0);
    if (fv) fv.remove();

    BILANZ = true;
    clearTimeout(WACHHUND);
    console.log('\nBilanz: ' + ok + ' OK, ' + fail + ' FAIL');
    w.close();
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
