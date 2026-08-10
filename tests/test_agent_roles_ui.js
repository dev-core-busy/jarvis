/* UI-Test: Rollen-Verwaltung (jsdom, echte settings.html + agent_roles.js).
 *
 * Prueft, was man am Quelltext NICHT ablesen kann:
 *   1. Ein Klick auf den TEXT einer Werkzeug-Checkbox schaltet sie GENAU EINMAL.
 *      Das ist die Falle vom 2026-07-29 (AD-Picker): in einem <label> schaltet
 *      der Browser selbst – wer zusaetzlich per JS toggelt, hebt sich auf und
 *      nur ein Treffer aufs 13-px-Kaestchen wirkt. jsdom setzt die
 *      Label-Aktivierung um, ein Test ohne echte Label-Semantik sieht das nicht.
 *   2. Anlegen schickt POST mit id, Bearbeiten PUT OHNE id (Kennung fest).
 *   3. Fremdtext (Name/Beschreibung) landet als TEXT im DOM, nicht als Markup.
 *   4. Der Klartext-Grund eines 400 wird angezeigt, nicht verschluckt.
 *   5. Der Lizenz-Hinweis erscheint nur, wenn das Profil-Limit greift.
 *
 * WICHTIG: am Ende window.close() + process.exit() – sonst halten Timer den
 * Node-Prozess offen (Fallstrick vom 2026-07-30).
 *
 * Lauf:  timeout 90 node tests/test_agent_roles_ui.js
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
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const ROLLEN = [
    {
        id: 'maler', name: 'Bild-Erzeuger', description: 'Erzeugt Bilder',
        prompt: 'DU MALST.', tools: ['generate_image'], profile_id: 'p2',
        reasoning_effort: 'low', max_steps: 6, enabled: true,
    },
    {
        id: 'boese', name: '<img src=x onerror="window.__xss=1">',
        description: '<script>window.__xss2=1</script>', prompt: 'p',
        tools: [], profile_id: 'weg', reasoning_effort: '', max_steps: 0, enabled: false,
    },
];
const ANTWORT = {
    roles: ROLLEN,
    tools: [
        { name: 'generate_image', description: 'erzeugt ein Bild' },
        { name: 'filesystem', description: 'liest/schreibt Dateien' },
        { name: 'shell_execute', description: 'Shell' },
    ],
    profiles: [{ id: 'p1', name: 'Standard' }, { id: 'p2', name: 'Bildmodell' }],
    max_roles: 24,
    efforts: ['', 'off', 'low', 'medium', 'high', 'max'],
    profile_limit: null,
    skill_active: true,
};

const ANTWORT_FRISCH = {
    roles: ['image_builder', 'analyst', 'writer'].map((id, i) => ({
        id, name: id, description: 'Vorgabe ' + i, prompt: 'p',
        tools: ['filesystem'], profile_id: '', reasoning_effort: '', max_steps: 0, enabled: true,
    })),
    tools: [{ name: 'filesystem', description: 'Dateien' }],
    profiles: [{ id: 'p1', name: 'Standard' }],
    max_roles: 24, efforts: [''], profile_limit: null, skill_active: true,
};

(async () => {
    const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
    const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const { window } = dom;
    const { document } = window;

    // ── Markup ──────────────────────────────────────────────────────────
    section('Markup und Verdrahtung');
    // Die Verwaltung liegt im Reiter des SKILLS "Agent Orchestrator" – nicht mehr
    // als Klappabschnitt unter „KI & System". Der Reiter-Knopf startet versteckt
    // und wird von skillcfg.js::updateTabs() nur bei aktivem Skill eingeblendet.
    const reiter = document.getElementById('settings-tab-agent_orchestrator');
    const reiterBtn = document.getElementById('settings-tab-btn-orchestrator');
    check('Reiter-Panel vorhanden', !!reiter);
    check('Reiter-Knopf vorhanden', !!reiterBtn);
    check('Reiter-Knopf startet versteckt (nur bei aktivem Skill sichtbar)',
        !!reiterBtn && reiterBtn.style.display === 'none');
    check('kein Klappabschnitt unter „KI & System" mehr',
        !document.getElementById('prof-sect-roles-hdr'));
    check('die Liste liegt IM Reiter-Panel',
        !!reiter && !!reiter.querySelector('#roles-list'));
    check('Hinweis-Element fuer inaktiven Skill vorhanden',
        !!document.getElementById('roles-skill-warn'));
    ['roles-list', 'btn-role-new', 'role-edit', 'role-f-id', 'role-f-name', 'role-f-desc',
        'role-f-prompt', 'role-f-tools', 'role-f-profile', 'role-f-effort', 'role-f-steps',
        'role-f-enabled', 'btn-role-save', 'btn-role-cancel', 'role-save-status',
        'role-profile-note', 'roles-count'].forEach((id) => {
            check('Element ' + id, !!document.getElementById(id));
        });
    check('Formular startet unsichtbar',
        document.getElementById('role-edit').style.display === 'none');
    check('agent_roles.js ist eingebunden', /agent_roles\.js\?v=/.test(html));

    const appjs = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
    check('app.js laedt die Rollen beim Oeffnen des Orchestrator-Reiters',
        /target === 'agent_orchestrator' && window\.AgentRoles/.test(appjs));
    check('kein Aufruf mehr im KI-Reiter', !appjs.includes('prof-sect-roles-hdr'));
    const skcfg = fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8');
    check('Reiter-Sichtbarkeit bleibt an den Skill gekoppelt',
        skcfg.includes("agent_orchestrator: 'settings-tab-btn-orchestrator'"));
    check('kein generisches Manifest-Formular fuer diesen Skill',
        !skcfg.includes('agent_orchestrator: { container:'));

    // ── Modul laden ─────────────────────────────────────────────────────
    const rufe = [];
    window.fetch = (url, opt) => {
        rufe.push({ url, opt: opt || {} });
        let body = { success: true };
        if (String(url) === '/api/agent_roles' && (!opt || (opt.method || 'GET') === 'GET')) {
            body = ANTWORT;
        } else if (window.__naechsterFehler) {
            const f = window.__naechsterFehler;
            window.__naechsterFehler = null;
            return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve(f) });
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
    window.localStorage.setItem('jarvis_token', 'tok-123');
    window.t = (k) => k;   // i18n neutral: die Vorgabetexte des Moduls greifen

    window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/agent_roles.js'), 'utf8'));
    check('window.AgentRoles existiert', !!window.AgentRoles);

    window.AgentRoles.onShow();
    await sleep(30);

    // ── Liste ───────────────────────────────────────────────────────────
    section('Liste');
    const liste = document.getElementById('roles-list');
    check('GET mit Bearer-Token',
        rufe.some((r) => String(r.url) === '/api/agent_roles'
            && (r.opt.headers || {}).Authorization === 'Bearer tok-123'));
    check('beide Rollen gerendert', liste.textContent.includes('Bild-Erzeuger')
        && liste.querySelectorAll('code').length === 2);
    check('Kennung wird angezeigt', liste.textContent.includes('maler'));
    // window.t liefert hier den Key zurueck; T() erkennt das und nimmt den
    // Vorgabetext des Moduls – geprueft wird also der deutsche Text.
    check('Werkzeug-Anzahl steht dran', /1 Werkzeuge/.test(liste.textContent),
        liste.textContent.slice(0, 120));
    check('zugewiesenes Profil wird benannt', liste.textContent.includes('Bildmodell'));
    check('verwaistes Profil ist kenntlich gemacht',
        liste.textContent.includes('gelöschtes Profil'), liste.textContent.slice(-80));
    check('abgeschaltete Rolle traegt ein Abzeichen',
        liste.textContent.includes('abgeschaltet'));
    check('Zaehler zeigt Anzahl/Deckel',
        document.getElementById('roles-count').textContent.trim() === '2 / 24',
        document.getElementById('roles-count').textContent);

    // XSS
    check('kein Markup aus Fremdtext ausgefuehrt (Name)', window.__xss === undefined);
    check('kein Markup aus Fremdtext ausgefuehrt (Beschreibung)', window.__xss2 === undefined);
    check('kein <img> aus dem Namen im DOM', liste.querySelectorAll('img').length === 0);
    check('der Name steht als Text da',
        liste.textContent.includes('<img src=x onerror='));

    // ── Feld-Layout: NICHT .input-group (die Falle vom 2026-08-10) ──────
    section('Feld-Layout im Formular');
    const css = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');
    const formular = document.getElementById('role-edit');
    check('kein .input-group im Rollen-Formular',
        formular.querySelectorAll('.input-group').length === 0,
        'gefunden: ' + formular.querySelectorAll('.input-group').length);
    check('Felder nutzen .role-field', formular.querySelectorAll('.role-field').length >= 7,
        String(formular.querySelectorAll('.role-field').length));
    check('.role-field stapelt vertikal (Label UEBER dem Feld)',
        /\.role-field\s*\{[^}]*flex-direction:\s*column/.test(css));
    check('das Label darf umbrechen',
        /\.role-field\s*>\s*label\s*\{[^}]*white-space:\s*normal/.test(css));
    check('Werkzeug-Container nutzt .role-tools',
        document.getElementById('role-f-tools').classList.contains('role-tools'));
    // Der eigentliche Fehler: `.input-group input { flex:1; background:transparent;
    // border:none }` traf die Kaestchen und machte sie unsichtbar/unklickbar.
    check('Kaestchen behalten ihre natuerliche Groesse',
        /\.role-tools input\[type="checkbox"\]\s*\{[^}]*width:\s*auto/.test(css));
    check('Kaestchen werden nicht gestreckt (flex:0 0 auto)',
        /\.role-tools input\[type="checkbox"\]\s*\{[^}]*flex:\s*0 0 auto/.test(css));
    check('Kaestchen behalten ihr Aussehen (appearance)',
        /\.role-tools input\[type="checkbox"\]\s*\{[^}]*appearance:\s*auto/.test(css));
    const ta = document.getElementById('role-f-prompt');
    check('Prompt-Feld hat die doppelte Hoehe (rows=10)', ta.getAttribute('rows') === '10',
        ta.getAttribute('rows'));
    check('Prompt-Feld ist vertikal veraenderbar',
        /\.role-field textarea\s*\{[^}]*resize:\s*vertical/.test(css));
    check('Grids brechen auf schmalen Fenstern um',
        /@media[^{]*max-width:\s*720px[^{]*\{[^}]*role-grid-2/.test(css.replace(/\s+/g, ' ')));

    // ── Formular: bearbeiten ────────────────────────────────────────────
    section('Formular – bearbeiten');
    const karte1 = () => liste.querySelector('.role-card[data-role-id="maler"]');
    const zeile1 = karte1;   // die Knoepfe liegen in der Kopfzeile INNERHALB der Karte
    zeile1().querySelector('.role-edit-btn').click();   // ✎ der ersten Rolle
    await sleep(10);
    check('Formular ist sichtbar',
        document.getElementById('role-edit').style.display !== 'none');
    check('Kennung vorbelegt', document.getElementById('role-f-id').value === 'maler');
    check('Kennung ist gesperrt (unveraenderlich)',
        document.getElementById('role-f-id').disabled === true);
    check('Prompt vorbelegt', document.getElementById('role-f-prompt').value === 'DU MALST.');
    check('Profil vorbelegt', document.getElementById('role-f-profile').value === 'p2');
    check('Denktiefe vorbelegt', document.getElementById('role-f-effort').value === 'low');
    check('Schritte vorbelegt', document.getElementById('role-f-steps').value === '6');
    const cbs = () => Array.from(document.querySelectorAll('#role-f-tools .role-tool-cb'));
    check('alle Werkzeuge angeboten', cbs().length === 3);
    check('nur die Werkzeuge der Rolle sind angehakt',
        cbs().filter((c) => c.checked).map((c) => c.value).join(',') === 'generate_image',
        cbs().filter((c) => c.checked).map((c) => c.value).join(','));
    check('kein delegate in der Auswahl (Backend liefert es nicht)',
        !cbs().some((c) => c.value === 'delegate'));

    // DER Test: Klick auf den TEXT schaltet genau einmal
    section('Label-Klick (Doppel-Toggle-Falle)');
    const labFs = cbs().find((c) => c.value === 'filesystem').parentNode;
    const spanFs = labFs.querySelector('span');
    spanFs.click();
    await sleep(5);
    check('Klick auf den Werkzeugnamen HAKT AN',
        cbs().find((c) => c.value === 'filesystem').checked === true);
    spanFs.click();
    await sleep(5);
    check('zweiter Klick haekelt wieder AB',
        cbs().find((c) => c.value === 'filesystem').checked === false);
    labFs.click();
    await sleep(5);
    check('Klick auf das Label selbst schaltet ebenfalls genau einmal',
        cbs().find((c) => c.value === 'filesystem').checked === true);

    // ── (a) Das Formular klappt DIREKT unter der bearbeiteten Zeile auf ──
    section('Formular sitzt in der Zeile, nicht am Listenende');
    const f = document.getElementById('role-edit');
    // EINE Box heisst: das Formular ist KIND der Karte – nicht ihr Geschwister.
    // Zweimal wurde versucht, zwei Nachbarn optisch zu verkleben (Radien,
    // transparente Kanten); der Abstand blieb sichtbar. Struktur schlaegt
    // Kosmetik – dasselbe Muster wie `.kb-section` (Rahmen aussen, Kopf und
    // Koerper innen ohne eigenen Rahmen).
    check('das Formular ist KIND der Rollen-Karte (eine Box)',
        f.parentNode === karte1(), f.parentNode && f.parentNode.className);
    check('es steht NACH der Kopfzeile in der Karte',
        karte1().children.length === 2 && karte1().children[1] === f);
    check('die Karte ist als „in Bearbeitung" markiert',
        karte1().classList.contains('is-editing'));
    const cssTxt = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');
    check('die KARTE traegt Rahmen und Hintergrund',
        /\.role-card\s*\{[^}]*border:\s*1px solid var\(--border\)/.test(cssTxt));
    check('die Kopfzeile hat KEINEN eigenen Rahmen',
        !/\.role-row\s*\{[^}]*border:/.test(cssTxt));
    check('das Formular verliert in der Karte seinen Rahmen',
        /\.role-card\s*>\s*\.role-edit-box\s*\{[^}]*border:\s*none/.test(cssTxt));
    check('und wird durch eine Trennlinie abgesetzt',
        /\.role-card\s*>\s*\.role-edit-box\s*\{[^}]*border-top:\s*1px solid/.test(cssTxt));
    check('das Formular hat keine Inline-Gestaltung im HTML',
        !/id="role-edit"[^>]*style="[^"]*border/.test(html));

    // Zweite Rolle bearbeiten → Formular wandert mit
    const zeile2 = liste.querySelector('.role-card[data-role-id="boese"]');
    zeile2.querySelector('.role-edit-btn').click();
    await sleep(10);
    check('beim Wechsel wandert das Formular in die andere Karte',
        f.parentNode === zeile2, f.parentNode && f.parentNode.dataset
            ? f.parentNode.dataset.roleId : '?');
    check('die vorige Karte ist nicht mehr „offen"',
        !karte1().classList.contains('is-editing'));
    check('nur EINE Karte ist markiert',
        document.querySelectorAll('.role-card.is-editing').length === 1);
    check('das Formular ist jetzt Kind der ANDEREN Karte', f.parentNode === zeile2);
    check('es gibt weiterhin nur EIN Formular',
        document.querySelectorAll('#role-edit').length === 1);

    // Abbrechen holt es zurück an den Heimatplatz (sonst klebt es in der Liste)
    document.getElementById('btn-role-cancel').click();
    await sleep(10);
    check('nach Abbrechen ist es wieder aus der Liste heraus',
        !document.getElementById('roles-list').contains(f));
    check('nach Abbrechen ist keine Karte mehr markiert',
        document.querySelectorAll('.role-card.is-editing').length === 0);
    check('nach Abbrechen ist es wieder eine eigene Box',
        f.classList.contains('role-edit-box') && f.parentNode !== karte1());
    check('Anlegen zeigt es am Heimatplatz, nicht in der Liste',
        (document.getElementById('btn-role-new').click() || true)
        && !document.getElementById('roles-list').contains(f));
    document.getElementById('btn-role-cancel').click();
    await sleep(10);

    // ── (b) Aktiv/Inaktiv direkt in der Zeile + Abschwaechung ────────────
    section('Aktiv-Schalter in der Zeile, deaktivierte Rollen abgeschwaecht');
    const zAus = liste.querySelector('.role-card[data-role-id="boese"]');
    // Die Abschwaechung kommt jetzt aus dem CSS (.role-row.is-off) – Inline-Styles
    // sind absichtlich weg, sonst gewinnen sie gegen .is-editing (Fix 2026-08-10).
    check('deaktivierte Rolle ist abgeschwaecht (CSS .role-card.is-off)',
        /\.role-card\.is-off\s*\{[^}]*opacity:\s*\.?\d/.test(
            fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8')));
    check('die Karte traegt keine Inline-Styles mehr',
        !zAus.getAttribute('style'), zAus.getAttribute('style') || '');
    check('deaktivierte Rolle traegt eine Klasse fuer den Zustand',
        zAus.classList.contains('is-off'));
    check('in der Liste liegen nur Karten',
        Array.prototype.every.call(liste.children, function (c) {
            return c.classList.contains('role-card');
        }));
    check('aktive Rolle ist NICHT abgeschwaecht (keine .is-off)',
        !zeile1().classList.contains('is-off'));
    check('aktive Rolle: Schalter bietet Abschalten an',
        zeile1().querySelector('.role-toggle').textContent === '⏸');
    check('inaktive Rolle: Schalter bietet Einschalten an',
        zAus.querySelector('.role-toggle').textContent === '▶');
    check('der Schalter hat eine Beschriftung fuer Screenreader',
        !!zAus.querySelector('.role-toggle').getAttribute('aria-label'));

    rufe.length = 0;
    zeile1().querySelector('.role-toggle').click();
    await sleep(30);
    const tg = rufe.find((r) => (r.opt.method || '') === 'PUT');
    check('Umschalten schickt PUT auf die Rolle',
        !!tg && String(tg.url) === '/api/agent_roles/maler', tg && String(tg.url));
    const tgBody = tg ? JSON.parse(tg.opt.body) : {};
    check('PUT enthaelt NUR enabled (kein Formularstand)',
        Object.keys(tgBody).length === 1 && tgBody.enabled === false,
        JSON.stringify(tgBody));
    check('Umschalten oeffnet das Formular NICHT',
        document.getElementById('role-edit').style.display === 'none');
    check('die Liste wird nach dem Umschalten neu geladen',
        rufe.some((r) => String(r.url) === '/api/agent_roles' && (r.opt.method || 'GET') === 'GET'));

    // ── Hinweis, wenn der Skill aus ist ─────────────────────────────────
    section('Hinweis bei inaktivem Skill');
    ANTWORT.skill_active = false;
    window.AgentRoles.onShow();
    await sleep(30);
    const warn = document.getElementById('roles-skill-warn');
    check('bei inaktivem Skill erscheint der Hinweis',
        warn.style.display !== 'none' && /Agent Orchestrator/.test(warn.textContent),
        warn.textContent.slice(0, 70));
    ANTWORT.skill_active = true;
    window.AgentRoles.onShow();
    await sleep(30);
    check('bei aktivem Skill ist der Hinweis weg',
        document.getElementById('roles-skill-warn').style.display === 'none');
    zeile1().querySelector('.role-edit-btn').click();
    await sleep(10);

    // ── Speichern: PUT ohne id ──────────────────────────────────────────
    section('Speichern');
    rufe.length = 0;
    // Auswahl erneut setzen: die Abschnitte oben haben das Formular zwischendurch
    // neu geoeffnet, und openForm() belegt die Kaestchen aus der Rolle vor.
    cbs().find((c) => c.value === 'filesystem').parentNode.querySelector('span').click();
    await sleep(5);
    document.getElementById('role-f-name').value = 'Maler neu';
    document.getElementById('btn-role-save').click();
    await sleep(30);
    const put = rufe.find((r) => (r.opt.method || '') === 'PUT');
    check('Bearbeiten schickt PUT auf die eigene Kennung',
        !!put && String(put.url) === '/api/agent_roles/maler', put && String(put.url));
    const putBody = put ? JSON.parse(put.opt.body) : {};
    check('PUT enthaelt KEINE id (Kennung ist fest)', !('id' in putBody));
    check('PUT uebergibt die gewaehlten Werkzeuge',
        Array.isArray(putBody.tools) && putBody.tools.includes('generate_image')
        && putBody.tools.includes('filesystem'), JSON.stringify(putBody.tools));
    check('PUT uebergibt Profil, Denktiefe, Schritte, Aktiv-Zustand',
        putBody.profile_id === 'p2' && putBody.reasoning_effort === 'low'
        && putBody.max_steps === 6 && putBody.enabled === true);
    check('Formular schliesst nach dem Speichern',
        document.getElementById('role-edit').style.display === 'none');
    check('die Liste wird neu geladen',
        rufe.some((r) => String(r.url) === '/api/agent_roles' && (r.opt.method || 'GET') === 'GET'));

    // ── Anlegen: POST mit id ────────────────────────────────────────────
    section('Anlegen');
    document.getElementById('btn-role-new').click();
    await sleep(10);
    check('Kennungsfeld ist beim Anlegen frei',
        document.getElementById('role-f-id').disabled === false);
    check('Felder sind leer', document.getElementById('role-f-name').value === ''
        && document.getElementById('role-f-prompt').value === '');
    check('kein Werkzeug vorausgewaehlt', cbs().filter((c) => c.checked).length === 0);
    check('Aktiv ist die Vorgabe', document.getElementById('role-f-enabled').checked === true);

    rufe.length = 0;
    document.getElementById('role-f-id').value = 'neurolle';
    document.getElementById('role-f-name').value = 'Neu';
    document.getElementById('role-f-desc').value = 'macht neu';
    document.getElementById('role-f-prompt').value = 'Du machst neu.';
    document.getElementById('btn-role-save').click();
    await sleep(30);
    const post = rufe.find((r) => (r.opt.method || '') === 'POST');
    check('Anlegen schickt POST', !!post && String(post.url) === '/api/agent_roles');
    check('POST enthaelt die id', post && JSON.parse(post.opt.body).id === 'neurolle');

    // ── Fehler vom Backend wird gezeigt ─────────────────────────────────
    section('Fehlermeldung');
    document.getElementById('btn-role-new').click();
    await sleep(10);
    window.__naechsterFehler = { success: false, error: 'Eine Beschreibung ist erforderlich.' };
    document.getElementById('btn-role-save').click();
    await sleep(30);
    const st = document.getElementById('role-save-status');
    check('der Klartext-Grund steht im Formular',
        st.textContent.includes('Eine Beschreibung ist erforderlich.'), st.textContent);
    check('das Formular bleibt bei einem Fehler OFFEN',
        document.getElementById('role-edit').style.display !== 'none');

    // ── Abbrechen ───────────────────────────────────────────────────────
    section('Abbrechen und Loeschen');
    rufe.length = 0;
    document.getElementById('btn-role-cancel').click();
    await sleep(10);
    check('× schliesst das Formular',
        document.getElementById('role-edit').style.display === 'none');
    check('Abbrechen speichert NICHT', rufe.length === 0);

    // Loeschen: Rueckfrage Pflicht
    let gefragt = false;
    window.confirm = () => { gefragt = true; return false; };
    rufe.length = 0;
    zeile1().querySelector('.kb-hdr-btn.is-danger').click();   // × der ersten Rolle
    await sleep(20);
    check('Loeschen fragt nach', gefragt);
    check('abgelehnte Rueckfrage loescht NICHT', rufe.length === 0);
    window.confirm = () => true;
    zeile1().querySelector('.kb-hdr-btn.is-danger').click();
    await sleep(20);
    check('bestaetigtes Loeschen schickt DELETE',
        rufe.some((r) => (r.opt.method || '') === 'DELETE'
            && String(r.url) === '/api/agent_roles/maler'));

    // ── Lizenz-Hinweis ──────────────────────────────────────────────────
    section('Lizenz-Hinweis zum Profil');
    check('ohne Limit kein Hinweis',
        document.getElementById('role-profile-note').style.display === 'none');
    ANTWORT.profile_limit = 1;
    ANTWORT.profiles = [{ id: 'p1', name: 'Standard' }];
    window.AgentRoles.onShow();
    await sleep(30);
    document.getElementById('btn-role-new').click();
    await sleep(10);
    const note = document.getElementById('role-profile-note');
    check('bei Profil-Limit erscheint der Hinweis',
        note.style.display !== 'none' && note.textContent.length > 10, note.textContent);

    // ── 403 ─────────────────────────────────────────────────────────────
    section('Kein Admin');
    window.fetch = () => Promise.resolve({ ok: false, status: 403, json: () => Promise.resolve({}) });
    window.AgentRoles.load();
    await sleep(30);
    check('403 wird als Meldung angezeigt, nicht als leere Liste',
        document.getElementById('roles-list').textContent.length > 5,
        document.getElementById('roles-list').textContent);

    // ══════════════════════════════════════════════════════════════════
    // Teil 2: MIT echtem app.js – laedt die Liste beim OEFFNEN der Einstellungen?
    //
    // WARUM DAS EIN EIGENER TEIL IST (der Fehler, den Teil 1 durchgelassen hat):
    // Teil 1 ruft `AgentRoles.onShow()` selbst auf und beweist damit nur, dass die
    // Funktion arbeitet. In der Anwendung hing der Aufruf aber NUR im
    // Reiter-Klick-Handler – und "KI & System" ist der VOREINGESTELLT aktive
    // Reiter: niemand klickt darauf, der Handler feuert nie, die Liste blieb leer.
    // Genau dieselbe Falle wie am 2026-07-28 bei den Update-Knoepfen (die
    // Warnung dazu steht in app.js direkt daneben). Ein UI-Test, der das Modul
    // isoliert antreibt, kann das NICHT finden.
    section('Teil 2: Laden beim Oeffnen der Einstellungen (echtes app.js)');

    const rufe2 = [];
    const dom2 = new JSDOM(html, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w2 = dom2.window;
    // FALLSTRICK: fetch MUSS vor dem eval gesetzt sein – app.js laeuft als IIFE
    // sofort und ruft fetch; sonst bricht es ab, bevor _openSettingsModal existiert.
    w2.fetch = (url, opt) => {
        const u = String(url);
        rufe2.push({ url: u, method: (opt && opt.method) || 'GET' });
        let body = {};
        if (u === '/api/agent_roles') body = ANTWORT_FRISCH;
        else if (u === '/api/me') body = { username: 'jarvis', is_admin: true, permissions: {} };
        else if (u === '/api/settings') body = { compress_threshold: 30 };
        else if (u === '/api/skills') body = { skills: [] };
        else if (u === '/api/profiles') body = { profiles: [], active_profile_id: '', defaults: {} };
        return Promise.resolve({
            ok: true, status: 200, json: () => Promise.resolve(body),
            text: () => Promise.resolve(''), headers: { get: () => 'application/json' },
        });
    };
    w2.localStorage.setItem('jarvis_token', 'tok-2');
    w2.matchMedia = w2.matchMedia || (() => ({ matches: false, addEventListener() {}, addListener() {} }));
    w2.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    w2.confirm = () => true;
    w2.alert = () => {};
    for (const f of ['frontend/js/i18n.js', 'frontend/js/theme.js',
                     'frontend/js/agent_roles.js', 'frontend/js/app.js']) {
        try { w2.eval(fs.readFileSync(path.join(ROOT, f), 'utf8')); }
        catch (e) { console.log('    (Modul ' + f + ': ' + e.message + ')'); }
    }
    check('AgentRoles im zweiten Fenster geladen', !!w2.AgentRoles);
    check('Modal-Oeffner erreichbar', typeof w2._openSettingsModal === 'function');

    if (typeof w2._openSettingsModal === 'function') {
        await w2._openSettingsModal();
        await sleep(150);
        // Der Rollen-Reiter ist beim Oeffnen NICHT aktiv (das ist „KI & System").
        // Er wird per Klick geoeffnet – und GENAU DA muss die Liste laden.
        check('beim Oeffnen wird noch nicht geladen (Reiter ist nicht aktiv)',
            !rufe2.some((r) => r.url === '/api/agent_roles'));

        const tabBtn = Array.from(w2.document.querySelectorAll('[data-settings-tab]'))
            .find((t) => t.dataset.settingsTab === 'agent_orchestrator');
        check('Rollen-Reiter-Knopf existiert', !!tabBtn);
        if (tabBtn) {
            rufe2.length = 0;
            tabBtn.dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
            await sleep(150);
            check('Reiter-Klick ruft /api/agent_roles ab',
                rufe2.some((r) => r.url === '/api/agent_roles' && r.method === 'GET'),
                JSON.stringify(rufe2.map((r) => r.url).slice(0, 10)));
            const l2 = w2.document.getElementById('roles-list');
            check('die drei Vorgabe-Rollen stehen in der Liste',
                !!l2 && ['image_builder', 'analyst', 'writer'].every((id) => l2.textContent.includes(id)),
                l2 ? l2.textContent.slice(0, 140) : '—');
            check('kein "Lädt…" mehr im Container',
                !!l2 && !l2.textContent.includes('Lädt'), l2 && l2.textContent.slice(0, 60));
            check('das Reiter-Panel ist sichtbar',
                w2.document.getElementById('settings-tab-agent_orchestrator').style.display === '');
        }
    }
    w2.close();

    // ── Abschluss ───────────────────────────────────────────────────────
    const ok = results.filter((r) => r.ok).length;
    const bad = results.filter((r) => !r.ok);
    console.log('\n' + '='.repeat(70));
    console.log(`Ergebnis: ${ok} bestanden, ${bad.length} fehlgeschlagen`);
    bad.forEach((b) => console.log('  ✗ ' + b.name + (b.detail ? ' – ' + b.detail : '')));
    window.close();
    process.exit(bad.length === 0 ? 0 : 1);
})().catch((e) => {
    console.error('ABBRUCH:', e);
    process.exit(2);
});
