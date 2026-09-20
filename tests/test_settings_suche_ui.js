/* ═══════════════════════════════════════════════════════════════════════
   Waechter: Suchfeld im Kopf der Einstellungen (settings_search.js)
   ───────────────────────────────────────────────────────────────────────
   Der ECHTE Renderer laeuft gegen die ECHTE `settings.html`, getippt wird
   ueber das echte `input`-Ereignis, geklickt wird wirklich. Ob ein Treffer
   ENTSTEHT, ob er den richtigen Skill nennt und ob der Klick beim
   Konfigurationspunkt landet, kann eine Quelltext-Suche nicht beantworten.

   ⚠ IN EINEM BLOCKKOMMENTAR DARF KEIN `*` VOR EINEM `/` STEHEN – die Folge
   beendet ihn, und der Rest der Datei wird als Code gelesen (hier beim
   ersten Lauf an `skills/<name>/skill.json` bezahlt).
   Abschnitt 4 nimmt die ECHTEN Manifeste unter skills/ als Korpus: eine
   erfundene Liste belegt nicht, dass die Suche an den Daten dieses Hauses
   funktioniert. Geprueft wird dort die EIGENSCHAFT (jeder Skill ist ueber
   seinen eigenen Namen auffindbar, jedes Konfigurationsfeld ueber seine
   Beschriftung), nicht eine abgetippte Trefferliste.

   Ohne jsdom/acorn gibt es keine Aussage: Exit 2, nicht 0.

   Ausgefuehrt: node tests/test_settings_suche_ui.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM = null;
for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom',
                 path.resolve(__dirname, '../node_modules/jsdom')]) {
    if (!k) continue;
    try { JSDOM = require(k).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const WURZEL = path.resolve(__dirname, '..');
const FE = path.join(WURZEL, 'frontend');
let acorn = null;
for (const p of ['acorn', '/usr/share/nodejs/acorn',
                 path.join(WURZEL, 'node_modules/acorn')]) {
    try { acorn = require(p); break; } catch (e) { /* weiter */ }
}
if (!acorn) { console.log('ABBRUCH: acorn nicht gefunden'); process.exit(2); }

let ok = 0, fail = 0, bilanz = false;
function pruefe(text, bedingung, zusatz) {
    // ⚠ Argumentreihenfolge (Text, Bedingung). Vertauscht waere jede nicht-leere
    // Zeichenkette wahr und der Lauf meldete lauter OK, ohne eine einzige
    // Bedingung ausgewertet zu haben (Vorfall 2026-08-28).
    if (typeof text !== 'string' || typeof bedingung === 'string') {
        console.error('TESTFEHLER: pruefe(Text, Bedingung) vertauscht:', text);
        process.exit(2);
    }
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}
process.on('unhandledRejection', (e) => {
    fail++; console.log('  FAIL unbehandelte Zurueckweisung: ' + ((e && e.message) || e));
});
// Ein Absturz darf nicht wie ein bestandener Lauf aussehen: die ganze Datei ist
// EINE async-IIFE – wirft etwas darin, wird alles bis zum Ende uebersprungen,
// auch die Bilanz und process.exit.
process.on('exit', (c) => {
    if (!bilanz) { console.log('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); if (!c) process.exitCode = 1; }
});
const wachhund = setTimeout(() => {
    console.log('\n\x1b[31mABGEBROCHEN – Zeitlimit (60 s)\x1b[0m');
    process.exit(1);
}, 60000);
wachhund.unref && wachhund.unref();

function lies(rel) { return fs.readFileSync(path.join(FE, rel), 'utf-8'); }
function liesJs(rel) { return fs.readFileSync(path.join(WURZEL, rel), 'utf-8'); }

/** Entfernt Zeilenkommentare und Blockkommentare.
 *  ⚠ Ohne das liest der Waechter seine eigene Begruendung: die Kommentare in
 *  settings_search.js nennen SKILL_TABS und zumKonfigurationspunkt woertlich
 *  (siebzehnter Fall dieser Klasse im Projekt). */
function ohneKommentare(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^[ \t]*\/\/.*$/gm, ' ');
}

// ── Korpus A: klein und deterministisch ─────────────────────────────────────
// Handgebaut, damit die MECHANIK (UND-Verknuepfung, Faltung, Rangfolge,
// Kuerzung) an bekannten Werten messbar ist. Der echte Bestand kommt in
// Abschnitt 4 dazu.
const KORPUS = [
    {
        name: 'Jira', dir_name: 'jira', category: 'wissen',
        description: 'Verbindung zu Atlassian Jira (Server/Data-Center).',
        installed: true, enabled: true,
        tools: ['jira_search', 'jira_get_issue'],
        config_schema: {
            base_url:  { type: 'string', label: 'Jira-URL', description: 'Basis-URL der Instanz.' },
            api_token: { type: 'string', label: 'Personal Access Token (PAT)',
                         description: 'In Jira unter Profil erzeugen.' },
        },
    },
    {
        name: 'E-Mail', dir_name: 'email', category: 'kommunikation',
        description: 'Postfaecher ueber Exchange.',
        installed: true, enabled: false,
        tools: ['email_senden'],
        config_schema: { ews_url: { type: 'string', label: 'EWS-Adresse' } },
    },
    {
        // ⚠ DER FALL, DER DIE RANGFOLGE PRUEFT: `token_praefix` traegt das
        // gesuchte Wort am ANFANG des SCHLUESSELS, seine Beschriftung aber
        // gar nicht. Mit einem zu grossen Anfangs-Bonus stuende er vor dem
        // Token-Feld von Jira – also vor dem Konfigurationspunkt, den man
        // sucht (am echten Bestand gemessen).
        name: 'Vemas', dir_name: 'vemas', category: 'wissen',
        description: 'Anbindung an VEMAS.NET.',
        installed: true, enabled: true, tools: [],
        config_schema: {
            token_praefix: { type: 'string', label: 'Anmelde-Vorsatz',
                             description: 'Steht vor dem Wert im Kopf.' },
        },
    },
    {
        name: 'Telegram', dir_name: 'telegram', category: 'kommunikation',
        description: 'Telegram-Bot: Nachrichten empfangen und beantworten.',
        installed: false, enabled: false, tools: [],
        config_schema: { bot_token: { type: 'string', label: 'Bot-Token' } },
    },
    {
        name: 'Löschdienst', dir_name: 'loeschdienst', category: 'system',
        description: 'Räumt Grüßes auf.', installed: true, enabled: true, tools: [],
    },
];

function tickCount(n) { let p = Promise.resolve(); for (let i = 0; i < n; i++) p = p.then(() => {}); return p; }

async function seite(korpus, opt) {
    const o = opt || {};
    const dom = new JSDOM(lies('settings.html'), {
        url: 'https://localhost/settings',
        runScripts: 'outside-only',
    });
    const w = dom.window;
    w.matchMedia = w.matchMedia || function () {
        return { matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
    };
    // jsdom kennt window.CSS nicht (skills.js meidet CSS.escape bewusst – die
    // Attrappe belegt, dass es auch ohne geht).
    w.localStorage.setItem('jarvis_token', 'T');
    w.eval(lies('js/icons.js'));
    w.eval(lies('js/i18n.js'));
    w.eval(lies('js/skills.js'));
    w.eval(lies('js/settings_search.js'));
    await new Promise(r => {
        if (w.document.readyState !== 'loading') return setTimeout(r, 0);
        w.document.addEventListener('DOMContentLoaded', () => setTimeout(r, 0));
    });
    // Das, was app.js im Betrieb bereitstellt (Abschnitt 5 prueft, dass es das
    // wirklich tut). Hier gestellt, damit der Lauf nicht die ganze app.js
    // braucht – die startet Poll-Timer und will ein Dutzend Endpunkte.
    w.fetch = o.fetch || (() => Promise.resolve({ ok: true, json: () => Promise.resolve({ skills: korpus }) }));
    w.skillManager = new w.JarvisSkillManager();
    w.skillManager.skills = korpus.slice();
    w.jarvisSkillsOnce = () => Promise.resolve(korpus);
    w.SettingsSearch.init();
    return { dom, w };
}

/** Wie `seite()`, aber mit der Lage des BETRIEBS: alle Reiter eingeblendet
 *  (das tut `SkillCfg.updateTabs()` beim Oeffnen des Modals) und die
 *  Klapp-Handler gebunden.
 *
 *  ⚠ GEBUNDEN WIRD MIT DER ECHTEN `_collapseInit` AUS app.js, nicht mit einem
 *  Nachbau: `zumElement` verlaesst sich darauf, dass ein Klick auf die
 *  Kopfzeile aufklappt UND den gemerkten Zustand mitschreibt. Ein bequemer
 *  Nachbau („setz einfach display") pruefte eine Kette, die es nicht gibt –
 *  und genau der Unterschied (Handler da / nicht da) entscheidet, ob der
 *  Treffer den Abschnitt wirklich oeffnet.
 *
 *  Die Liste der Abschnitte kommt aus dem DOM (`X-hdr` → `X-body`/`X-tog`),
 *  nicht aus den `_initXCollapse()`-Listen: Abschnitt 8 prueft getrennt, dass
 *  app.js jeden davon wirklich bindet. */
async function seiteVoll(korpus, opt) {
    const r = await seite(korpus, opt);
    const w = r.w;
    w.document.querySelectorAll('.settings-tab-btn[data-settings-tab]')
        .forEach(b => { b.style.display = ''; });
    const src = liesJs('frontend/js/app.js');
    const i = src.indexOf('function _collapseInit(');
    if (i < 0) throw new Error('_collapseInit nicht gefunden');
    // Geklammert schneiden – ein Schnitt „bis zum ersten \n}" endet mitten drin.
    let tiefe = 0, j = src.indexOf('{', i), ende = -1;
    for (let k = j; k < src.length; k++) {
        if (src[k] === '{') tiefe++;
        else if (src[k] === '}') { tiefe--; if (tiefe === 0) { ende = k + 1; break; } }
    }
    const fn = src.slice(i, ende);
    const liste = [].slice.call(w.document.querySelectorAll('.kb-collapse-header'))
        .filter(h => h.id && /-hdr$/.test(h.id))
        .map(h => ({ hdr: h.id, body: h.id.replace(/-hdr$/, '-body'), tog: h.id.replace(/-hdr$/, '-tog') }));
    w.eval('(' + fn + ')')(liste);
    r.abschnitte = liste.length;
    return r;
}

function feldVon(w) { return w.document.getElementById('st-such-feld'); }
function panelVon(w) { return w.document.getElementById('st-such-panel'); }
function zeilen(w) {
    return [].slice.call(w.document.querySelectorAll('#st-such-liste .st-such-item'));
}
function titelTexte(w) {
    return zeilen(w).map(z => (z.querySelector('.st-such-titel').textContent || '').trim());
}
function pfadTexte(w) {
    return zeilen(w).map(z => (z.querySelector('.st-such-pfad').textContent || '').trim());
}
async function tippe(w, txt) {
    const f = feldVon(w);
    f.value = txt;
    // ⚠ `new w.Event` und NICHT `new Event`: Node hat ein eigenes globales
    // Event, und jsdom lehnt es mit "parameter 1 is not of type 'Event'" ab.
    f.dispatchEvent(new w.Event('input', { bubbles: true }));
    await tickCount(8);
    await new Promise(r => setTimeout(r, 0));
    await tickCount(8);
}
function taste(w, key) {
    const e = new w.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    feldVon(w).dispatchEvent(e);
    return e;
}
function klick(el, w) {
    if (!el) return;
    el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
}
/** ⚠ NIE UNGEPRUEFT DEREFERENZIEREN: eine Gegenprobe, die alle Treffer
 *  wegnimmt, liesse den Lauf sonst mit einem TypeError abbrechen – ohne
 *  Bilanzzeile, also ununterscheidbar von „nicht gelaufen". */
function zeile(w, i) {
    return zeilen(w)[i] || { classList: { contains: () => false }, textContent: '',
                             querySelector: () => null, dispatchEvent: () => {} };
}

(async () => {

// ═══ 1. Markup und Platz ═══════════════════════════════════════════════════
console.log('\n1. Markup: Feld links vom Haus, im Kopf der Einstellungen');
{
    const { w } = await seite(KORPUS);
    const d = w.document;
    const wrap = d.getElementById('st-such-wrap');
    const haus = d.getElementById('btn-home-settings');
    const gruppe = d.querySelector('#settings-modal .modal-head-actions');

    pruefe('Suchfeld vorhanden', !!feldVon(w));
    pruefe('Wrapper liegt in der Symbolgruppe des Modal-Kopfes',
           !!wrap && !!gruppe && wrap.parentNode === gruppe);
    // LINKS vom Haus = im DOM davor (die Gruppe ist eine Flex-Zeile in
    // Leserichtung).
    pruefe('steht LINKS vom Haus-Symbol',
           !!wrap && !!haus &&
           (wrap.compareDocumentPosition(haus) & 4) === 4,
           'Reihenfolge im Kopf');
    // Chrome-Autofill fuellt Felder OHNE input-Ereignis: die Liste saehe dann
    // wirkungslos aus (im Audit-Log schon einmal bezahlt).
    pruefe('autocomplete="off"', feldVon(w).getAttribute('autocomplete') === 'off');
    pruefe('Platzhalter und aria-label uebersetzbar',
           feldVon(w).hasAttribute('data-i18n-placeholder') &&
           feldVon(w).hasAttribute('data-i18n-aria'));
    pruefe('Panel startet geschlossen', panelVon(w).hasAttribute('hidden'));
    // ⚠ DAS PANEL HAENGT AM KOPF, NICHT AM FELD. Am Feld war sein
    // Bezugsrahmen so breit wie das Feld, und `max-width` konnte es nicht am
    // Modalrand halten: bei 520 px Fensterbreite ragte es links heraus
    // (Screenshot). Die Breitenzusage steht in Abschnitt 7, die STRUKTUR hier.
    const kopf = d.querySelector('#settings-modal .modal-header');
    pruefe('Panel ist Kind des Modal-Kopfes, nicht des Suchfeldes',
           !!kopf && panelVon(w).parentNode === kopf,
           panelVon(w).parentNode && panelVon(w).parentNode.className);
    pruefe('Lupe eingesetzt (kein Emoji)',
           /<svg/i.test(d.getElementById('st-such-lupe').innerHTML));
}

// ═══ 2. Suchen: pro Tastendruck, UND-verknuepft, gefaltet ══════════════════
console.log('\n2. Treffer je Tastendruck');
{
    const { w } = await seite(KORPUS);

    await tippe(w, 'j');
    pruefe('ein einzelner Buchstabe oeffnet nichts', panelVon(w).hasAttribute('hidden'));

    await tippe(w, 'jira');
    pruefe('„jira" oeffnet das Panel', !panelVon(w).hasAttribute('hidden'));
    const t1 = titelTexte(w);
    pruefe('„jira" findet den Skill Jira', t1.indexOf('Jira') >= 0, t1.join(' | '));
    pruefe('„jira" findet auch seine Konfigurationsfelder',
           t1.indexOf('Personal Access Token (PAT)') >= 0, t1.join(' | '));

    await tippe(w, 'token');
    const t2 = titelTexte(w);
    // ⚠ RANGFOLGE: ein Treffer am Anfang eines SCHWAECHEREN Feldes (hier der
    // Schluessel `token_praefix`) darf den Treffer im staerksten Feld (die
    // Beschriftung „Personal Access Token (PAT)") NICHT ueberholen.
    pruefe('die Beschriftung schlaegt den Schluesselnamen',
           t2.indexOf('Personal Access Token (PAT)') >= 0 &&
           t2.indexOf('Anmelde-Vorsatz') >= 0 &&
           t2.indexOf('Personal Access Token (PAT)') < t2.indexOf('Anmelde-Vorsatz'),
           t2.join(' | '));
    pruefe('„token" findet das Feld, nicht nur den Skill',
           t2.indexOf('Personal Access Token (PAT)') >= 0, t2.join(' | '));
    pruefe('„token" findet auch den Bot-Token von Telegram',
           t2.indexOf('Bot-Token') >= 0, t2.join(' | '));

    // ⚠ UND: beide Worte muessen vorkommen. Sonst lieferte „jira token" jeden
    // Eintrag, in dem irgendwo „jira" steht.
    await tippe(w, 'jira token');
    const t3 = titelTexte(w);
    pruefe('„jira token" liefert genau das Token-Feld UNTER Jira',
           t3.length === 1 && t3[0] === 'Personal Access Token (PAT)', t3.join(' | '));
    pruefe('… und nennt in der zweiten Zeile den Pfad zum Skill',
           /Skills\s*›\s*Jira/.test(pfadTexte(w)[0] || ''), pfadTexte(w)[0]);

    // Faltung: Trennzeichen und Umlaute duerfen nicht zwischen Nadel und
    // Heuhaufen stehen.
    await tippe(w, 'email');
    pruefe('„email" findet „E-Mail"', titelTexte(w).indexOf('E-Mail') >= 0,
           titelTexte(w).join(' | '));
    // ⚠ ISOLIERT: „ewsadresse" kann NUR ueber die Beschriftung „EWS-Adresse"
    // treffen – der Schluessel heisst `ews_url`, der Skill „E-Mail". Ohne
    // Trennzeichen-Faltung gibt es keinen Treffer.
    await tippe(w, 'ewsadresse');
    pruefe('Trennzeichen werden gefaltet („ewsadresse" → „EWS-Adresse")',
           titelTexte(w).indexOf('EWS-Adresse') >= 0, titelTexte(w).join(' | '));
    // ⚠ ISOLIERT: der Verzeichnisname ist „loeschdienst" (mit oe) – „loschdienst"
    // trifft nur, wenn „ö" zu „o" gefaltet wird.
    await tippe(w, 'loschdienst');
    pruefe('Akzente werden gefaltet („loschdienst" → „Löschdienst")',
           titelTexte(w).indexOf('Löschdienst') >= 0, titelTexte(w).join(' | '));
    // ⚠ ISOLIERT: „Grüßes" faltet nur MIT der ß-Regel zu „grusses"; ohne sie
    // bliebe „gruße…" stehen und der Treffer entfiele.
    await tippe(w, 'grusses');
    pruefe('ß wird zu ss gefaltet („grusses" → „Grüßes")',
           titelTexte(w).indexOf('Löschdienst') >= 0, titelTexte(w).join(' | '));

    // Hervorhebung: die Fundstelle muss sichtbar sein, sonst ist nicht
    // erklaerbar, warum eine Zeile ein Treffer ist.
    await tippe(w, 'token');
    const marks = w.document.querySelectorAll('#st-such-liste .st-such-mark');
    pruefe('Fundstelle ist hervorgehoben', marks.length > 0);
    pruefe('… und deckt genau das getippte Wort',
           [].slice.call(marks).every(m => m.textContent.toLowerCase() === 'token'),
           [].slice.call(marks).map(m => m.textContent).join('|'));
}

// ═══ 3. Zustand, Rangfolge, Ehrlichkeit ════════════════════════════════════
console.log('\n3. Marken, Rangfolge, Leermeldung, Kuerzung');
{
    const { w } = await seite(KORPUS);

    await tippe(w, 'telegram');
    const z = zeilen(w);
    pruefe('nicht installierter Skill traegt die Marke',
           z.length > 0 && /nicht installiert/i.test(zeile(w, 0).textContent),
           z.map(x => x.textContent).join(' | '));

    await tippe(w, 'e-mail');
    pruefe('abgeschalteter Skill traegt die Marke „Deaktiviert"',
           /Deaktiviert/.test(zeilen(w).map(x => x.textContent).join(' ')),
           zeilen(w).map(x => x.textContent).join(' | '));

    // Ein noch nicht installierter Skill ist ein Konfigurationspunkt, den es
    // gar nicht gibt – er steht hinter den vorhandenen.
    await tippe(w, 'token');
    const reihe = titelTexte(w);
    pruefe('installierte Treffer stehen vor nicht installierten',
           reihe.indexOf('Personal Access Token (PAT)') < reihe.indexOf('Bot-Token'),
           reihe.join(' | '));

    // ⚠ Die Leermeldung nennt den SUCHRAUM. „Kein Treffer" allein liesse den
    // Benutzer glauben, es gaebe die Einstellung nirgends.
    await tippe(w, 'zzzunbekannt');
    const leer = (w.document.querySelector('#st-such-liste .st-such-leer') || {}).textContent || '';
    pruefe('Leermeldung nennt den Suchbegriff', leer.indexOf('zzzunbekannt') >= 0, leer);
    // ⚠ GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT DER WORTLAUT. Diese beiden
    // Pruefungen verlangten bis 2026-09-20 das Wort „Skills" und haetten damit
    // die Erweiterung des Suchraums als Fehler gemeldet – also genau die
    // Behebung der gemeldeten Lage abgelehnt. Die Zusage lautet: der Suchraum
    // wird GENANNT, nicht: er heisst so.
    pruefe('Leermeldung nennt den Suchraum', /Einstellung/i.test(leer), leer);

    const hin = w.document.getElementById('st-such-hinweis').textContent || '';
    pruefe('Fusszeile nennt den Suchraum immer',
           /Reiter|Abschnitt|Skill/i.test(hin) && hin.trim().length > 10, hin);
}
{
    // Kuerzung: mehr Treffer als MAX_TREFFER muessen BEZIFFERT werden – eine
    // gekuerzte Liste, die ihre Kuerzung verschweigt, gilt als vollstaendig.
    const viele = [];
    for (let i = 0; i < 20; i++) {
        viele.push({ name: 'Zielskill ' + i, dir_name: 'ziel' + i, category: 'system',
                     description: '', installed: true, enabled: true, tools: [] });
    }
    const { w } = await seite(viele);
    await tippe(w, 'zielskill');
    const n = zeilen(w).length;
    const hin = w.document.getElementById('st-such-hinweis').textContent || '';
    pruefe('Liste ist gedeckelt', n > 0 && n < 20, String(n));
    pruefe('Kuerzung wird beziffert (gezeigt UND gesamt)',
           hin.indexOf(String(n)) >= 0 && hin.indexOf('20') >= 0, hin);
}

// ═══ 4. Der ECHTE Bestand ══════════════════════════════════════════════════
console.log('\n4. Echte skills/*/skill.json als Korpus');
{
    const dir = path.join(WURZEL, 'skills');
    const echt = fs.readdirSync(dir).filter(n => {
        try { return fs.existsSync(path.join(dir, n, 'skill.json')); } catch (e) { return false; }
    }).map(n => {
        const d = JSON.parse(fs.readFileSync(path.join(dir, n, 'skill.json'), 'utf-8'));
        d.dir_name = n; d.installed = true; d.enabled = true;
        return d;
    });
    // Positivkontrolle: ohne Korpus waere unten jede Aussage trivial wahr.
    pruefe('echter Bestand gelesen (mindestens 20 Skills)', echt.length >= 20, String(echt.length));

    const { w } = await seite(echt);
    const idx = w.SettingsSearch._baueIndex(echt);
    const felder = echt.reduce((n, s) => n + Object.keys(s.config_schema || {}).length, 0);
    pruefe('Index enthaelt je Skill einen Eintrag plus je Konfigurationsfeld einen',
           idx.length === echt.length + felder, idx.length + ' vs ' + (echt.length + felder));
    pruefe('es gibt wirklich Konfigurationsfelder im Bestand', felder > 20, String(felder));

    // EIGENSCHAFT, nicht Trefferliste: jeder Skill ist ueber seinen eigenen
    // Namen auffindbar. Ein abgetippter Erwartungswert waere beim naechsten
    // neuen Skill falsch.
    let nichtGefunden = [];
    for (const s of echt) {
        await tippe(w, s.name);
        if (titelTexte(w).indexOf(s.name) < 0) nichtGefunden.push(s.name);
    }
    pruefe('jeder Skill ist ueber seinen eigenen Namen auffindbar',
           nichtGefunden.length === 0, nichtGefunden.join(', '));

    // Stichprobe ueber die Konfigurationsfelder: die ersten 25 Beschriftungen.
    let feldFehlt = [];
    let geprueft = 0;
    for (const s of echt) {
        for (const k of Object.keys(s.config_schema || {})) {
            if (geprueft >= 25) break;
            const label = (s.config_schema[k] || {}).label || k;
            geprueft++;
            await tippe(w, label);
            if (titelTexte(w).indexOf(label) < 0) feldFehlt.push(s.dir_name + '/' + label);
        }
        if (geprueft >= 25) break;
    }
    pruefe('Konfigurationsfelder sind ueber ihre Beschriftung auffindbar (' + geprueft + ' geprueft)',
           geprueft >= 20 && feldFehlt.length === 0, feldFehlt.join(', '));
}

// ═══ 5. Der Klick landet beim Konfigurationspunkt ══════════════════════════
console.log('\n5. Ein Klick fuehrt zum Konfigurationspunkt');
{
    const { w } = await seite(KORPUS);
    const gerufen = [];
    w.skillManager.zumKonfigurationspunkt = (n) => { gerufen.push(n); return Promise.resolve('reiter'); };

    await tippe(w, 'jira token');
    pruefe('es gibt ueberhaupt einen Treffer zum Klicken', zeilen(w).length >= 1,
           String(zeilen(w).length));
    klick(zeile(w, 0), w);
    pruefe('Klick ruft den Konfigurationspunkt DES SKILLS auf, zu dem das Feld gehoert',
           gerufen.length === 1 && gerufen[0] === 'jira', gerufen.join(','));
    pruefe('danach ist das Feld leer', feldVon(w).value === '');
    pruefe('… und das Panel zu', panelVon(w).hasAttribute('hidden'));

    // ⚠ EIN KLICK INS PANEL DARF ES NICHT SCHLIESSEN. Der Aussenklick-Handler
    // prueft `wrap.contains` – seit das Panel KIND DES KOPFES ist (und nicht
    // mehr des Feldes), waere ein Klick in die Trefferliste damit "daneben":
    // das Panel schloesse sich, bevor die Auswahl greift.
    await tippe(w, 'token');
    klick(w.document.getElementById('st-such-hinweis'), w);
    pruefe('ein Klick INS Panel schliesst es nicht',
           !panelVon(w).hasAttribute('hidden'));
    // Gegenrichtung: daneben schliesst weiterhin.
    klick(w.document.querySelector('#settings-modal .modal-body') ||
          w.document.body, w);
    pruefe('ein Klick DANEBEN schliesst weiterhin',
           panelVon(w).hasAttribute('hidden'));

    // Tastatur: ohne sie ist „schnell" eine halbe Zusage.
    await tippe(w, 'token');
    const n = zeilen(w).length;
    pruefe('mehrere Treffer zum Blaettern vorhanden', n > 1, String(n));
    pruefe('erster Treffer ist vorausgewaehlt', zeile(w, 0).classList.contains('is-aktiv'));
    taste(w, 'ArrowDown');
    pruefe('Pfeil ab bewegt die Auswahl', zeile(w, 1).classList.contains('is-aktiv'));
    taste(w, 'ArrowUp');
    pruefe('Pfeil auf bewegt zurueck', zeile(w, 0).classList.contains('is-aktiv'));
    // ⚠ GEMESSEN WIRD, DASS ENTER DIE AUSWAHL AUSLOEST – nicht, dass dabei
    // `skillManager` gerufen wird: seit der Suchraum die ganze Oberflaeche
    // umfasst, kann der erste Treffer ein Reiter oder ein Abschnitt sein, und
    // der fuehrt ueber `zumElement`. Die alte Fassung haette genau das als
    // Fehler gemeldet. Der Weg ueber `skillManager` wird in Abschnitt 6
    // eigens geprueft.
    gerufen.length = 0;
    taste(w, 'Enter');
    pruefe('Enter waehlt den markierten Treffer',
           panelVon(w).hasAttribute('hidden') && feldVon(w).value === '',
           'panel-zu=' + panelVon(w).hasAttribute('hidden') + ' feld="' + feldVon(w).value + '"');

    // Escape: erst leeren, dann schliessen – und NICHT bis zum Modal
    // durchlaufen, dort schliesst er die ganzen Einstellungen.
    await tippe(w, 'token');
    const e1 = taste(w, 'Escape');
    pruefe('Escape leert zuerst den Begriff', feldVon(w).value === '');
    pruefe('… und wird dabei gestoppt (Modal bleibt offen)', e1.cancelBubble === true || e1.defaultPrevented);
    await tippe(w, 'token');
    taste(w, 'Escape');           // leert
    const e2 = taste(w, 'Escape');// schliesst (Panel ist schon zu → laeuft durch)
    pruefe('zweiter Escape laeuft durch, wenn nichts mehr zu schliessen ist',
           !e2.defaultPrevented);
}

// ═══ 6. Die EINE Regel: wohin ein Skill fuehrt ═════════════════════════════
console.log('\n6. zielFuer / zumKonfigurationspunkt (skills.js)');
{
    const { w } = await seite(KORPUS);
    const sm = w.skillManager;
    const d = w.document;

    // 'reiter' nur, wenn der Reiter auch SICHTBAR ist (Skill aus = Reiter weg).
    const jiraTab = d.querySelector('.settings-tab-btn[data-settings-tab="jira"]');
    pruefe('Jira-Reiter existiert im Markup', !!jiraTab);
    jiraTab.style.display = 'none';
    pruefe('unsichtbarer Reiter zaehlt nicht als Ziel',
           sm.zielFuer('jira').art === 'dialog', sm.zielFuer('jira').art);
    jiraTab.style.display = '';
    pruefe('sichtbarer Reiter hat Vorrang vor dem Dialog',
           sm.zielFuer('jira').art === 'reiter', sm.zielFuer('jira').art);
    pruefe('… und wird beim Namen genannt', sm.zielFuer('jira').reiter === jiraTab.textContent.trim());

    pruefe('Skill ohne Reiter, aber mit config_schema → Dialog',
           sm.zielFuer('email').art === 'dialog', sm.zielFuer('email').art);
    pruefe('Skill ohne beides → nur der Listeneintrag',
           sm.zielFuer('loeschdienst').art === 'liste', sm.zielFuer('loeschdienst').art);
    // Ein nicht installierter Skill hat noch KEINEN Konfigurationspunkt.
    pruefe('nicht installierter Skill → „moegliche"',
           sm.zielFuer('telegram').art === 'moegliche', sm.zielFuer('telegram').art);

    // Und der Weg dorthin wirkt wirklich.
    jiraTab.style.display = '';
    // ⚠ NICHT `.active` messen: die Klasse setzt der Reiter-Handler in app.js,
    // und die laeuft hier nicht (sie startet Poll-Timer und will ein Dutzend
    // Endpunkte). Messbar ist die Eigenschaft, auf die es ankommt: es wird
    // GENAU DER richtige Reiter geklickt.
    let geklickt = 0;
    jiraTab.addEventListener('click', () => { geklickt++; });
    const art = await sm.zumKonfigurationspunkt('jira');
    pruefe('zumKonfigurationspunkt nimmt den Reiter', art === 'reiter', String(art));
    pruefe('… und klickt genau den Jira-Reiter', geklickt === 1, String(geklickt));

    // Kein Konfigurationspunkt → Eintrag in der Liste anspringen. Das geht nur
    // mit einer Adresse an der Zeile (data-skill).
    const art2 = await sm.zumKonfigurationspunkt('loeschdienst');
    pruefe('ohne Konfigurationspunkt fuehrt der Weg in die Liste', art2 === 'liste', String(art2));
    const zeile = [].slice.call(d.querySelectorAll('[data-skill]'))
        .find(n => n.getAttribute('data-skill') === 'loeschdienst');
    pruefe('die Zeile ist adressierbar (data-skill)', !!zeile);
    pruefe('… und wird hervorgehoben', !!zeile && zeile.classList.contains('sk-item-treffer'));
    pruefe('der Abschnitt „Installierte" ist dabei aufgeklappt',
           d.getElementById('sk-installed-body').style.display !== 'none');
    // ⚠ EIN ZWEITER AUFRUF DARF IHN NICHT ZUKLAPPEN: ein blindes click() auf
    // die Kopfzeile ist ein UMSCHALTER. Ohne diesen Fall bliebe die Zusage
    // ungeprueft – beim ersten Aufruf ist der Abschnitt ohnehin zu.
    await sm.zumKonfigurationspunkt('loeschdienst');
    pruefe('… und bleibt beim zweiten Mal offen (kein blindes Umschalten)',
           d.getElementById('sk-installed-body').style.display !== 'none',
           d.getElementById('sk-installed-body').style.display);

    // Nicht installiert: der Eintrag steht in „Moegliche Skills" – und der
    // dortige Filter darf ihn nicht verschlucken.
    const sfeld = d.getElementById('sk-search');
    sfeld.value = 'zzz'; sm.searchVal = 'zzz'; sm.categoryFilter = 'wissen';
    const art3 = await sm.zumKonfigurationspunkt('telegram');
    pruefe('nicht installierter Skill fuehrt zu „Moegliche Skills"', art3 === 'moegliche', String(art3));
    pruefe('… und der Filter wurde dafuer geloest', sfeld.value === '' && sm.categoryFilter === 'all',
           sfeld.value + '/' + sm.categoryFilter);
    const zeile2 = [].slice.call(d.querySelectorAll('[data-skill]'))
        .find(n => n.getAttribute('data-skill') === 'telegram');
    pruefe('… der Eintrag ist da und hervorgehoben',
           !!zeile2 && zeile2.classList.contains('sk-item-treffer'));
}

// ═══ 7. Regeln ueber den Quelltext ═════════════════════════════════════════
console.log('\n7. Regeln (Drift, Verdrahtung, i18n)');
{
    const such = ohneKommentare(liesJs('frontend/js/settings_search.js'));
    const app = ohneKommentare(liesJs('frontend/js/app.js'));
    const skills = liesJs('frontend/js/skills.js');

    // ⚠ DRIFT-SCHRANKE: die Reiterzuordnung (SKILL_TABS) gibt es EINMAL, in
    // skills.js. Baut die Suche sie nach, fuehrt ein Treffer beim naechsten
    // neuen Reiter woandershin als das Zahnrad daneben.
    pruefe('die Suche baut die Reiterzuordnung NICHT nach',
           !/SKILL_TABS|data-settings-tab="\s*\+|settingsTabFor/.test(such) &&
           (such.match(/data-settings-tab=/g) || []).length <= 1,
           (such.match(/data-settings-tab=/g) || []).join(' | '));
    pruefe('die Suche fragt skillManager nach dem Ziel',
           /skillManager[\s\S]{0,80}zumKonfigurationspunkt/.test(such));
    pruefe('sie holt die Liste ueber den gemeinsamen Zwischenspeicher',
           /jarvisSkillsOnce/.test(such));
    pruefe('sie fasst /api/skills NICHT selbst an',
           such.indexOf('/api/skills') < 0);

    // Verdrahtung in app.js – ueber den Syntaxbaum, damit eine Zuweisung in
    // einem toten Zweig nicht als erfuellt zaehlt.
    const baum = acorn.parse(liesJs('frontend/js/app.js'), { ecmaVersion: 2022, sourceType: 'script' });
    let hatMgr = false, hatCache = false, hatInit = false;
    (function lauf(n) {
        if (!n || typeof n !== 'object') return;
        if (n.type === 'AssignmentExpression' && n.left && n.left.type === 'MemberExpression'
            && n.left.object && n.left.object.name === 'window' && n.left.property) {
            if (n.left.property.name === 'skillManager') hatMgr = true;
            if (n.left.property.name === 'jarvisSkillsOnce') hatCache = true;
        }
        if (n.type === 'CallExpression' && n.callee && n.callee.type === 'MemberExpression'
            && n.callee.property && n.callee.property.name === 'init'
            && n.callee.object && n.callee.object.type === 'MemberExpression'
            && n.callee.object.property && n.callee.object.property.name === 'SettingsSearch') hatInit = true;
        for (const k in n) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach(lauf);
            else if (v && typeof v === 'object' && v.type) lauf(v);
        }
    })(baum);
    pruefe('app.js stellt window.skillManager bereit', hatMgr);
    pruefe('app.js stellt window.jarvisSkillsOnce bereit', hatCache);
    pruefe('app.js ruft SettingsSearch.init()', hatInit);
    pruefe('… und zwar beim Oeffnen des Modals (vor classList.add(\'open\'))',
           /SettingsSearch[\s\S]{0,120}classList\.add\('open'\)/.test(app));

    // data-skill an BEIDEN Zeilentypen – sonst ist der Sprung in die Liste
    // fuer eine der beiden Haelften tot.
    pruefe('skills.js adressiert installierte UND moegliche Zeilen',
           (skills.match(/setAttribute\('data-skill'/g) || []).length === 2,
           String((skills.match(/setAttribute\('data-skill'/g) || []).length));

    // i18n: jeder benutzte Schluessel in BEIDEN Sprachen.
    const i18n = liesJs('frontend/js/i18n.js');
    const benutzt = new Set();
    let m; const re = /t\('(stsuche\.[a-z_]+)'/g;
    while ((m = re.exec(such))) benutzt.add(m[1]);
    const html = lies('settings.html');
    const re2 = /data-i18n(?:-placeholder|-aria)?="(stsuche\.[a-z_]+)"/g;
    while ((m = re2.exec(html))) benutzt.add(m[1]);
    pruefe('es werden ueberhaupt stsuche-Schluessel benutzt', benutzt.size >= 6, String(benutzt.size));
    const fehlend = [];
    for (const k of benutzt) {
        if ((i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length !== 2) {
            fehlend.push(k);
        }
    }
    pruefe('jeder stsuche-Schluessel existiert in DE und EN', fehlend.length === 0, fehlend.join(', '));

    // CSS: die Regeln, an denen die Zusagen haengen.
    const css = fs.readFileSync(path.join(FE, 'css/style.css'), 'utf-8')
        .replace(/\/\*[\s\S]*?\*\//g, ' ');
    function regel(sel) {
        const i = css.indexOf(sel + ' {');
        if (i < 0) return '';
        return css.slice(i, css.indexOf('}', i));
    }
    pruefe('Panel hat eine DECKENDE Flaeche', /background:\s*var\(--bg-secondary\)/.test(regel('.st-such-panel')));
    // ⚠ `.modal-content` traegt overflow: hidden – ein nach rechts wachsendes
    // Panel wuerde am Modalrand abgeschnitten.
    pruefe('Panel ist rechtsbuendig verankert', /right:\s*[\d.]+rem|right:\s*0/.test(regel('.st-such-panel')));
    // ⚠ DIE EIGENTLICHE ZUSAGE: das Panel kann NIE breiter werden als der Kopf.
    // Mit dem FELD als Bezug mass `max-width` die Feldbreite – bei 520 px
    // Fensterbreite begann das Panel links AUSSERHALB des Modals und die Titel
    // waren abgeschnitten (im Screenshot gesehen, die Messung bei 1400 px war
    // gruen). Deshalb: Bezugsrahmen positioniert UND max-width relativ dazu.
    pruefe('der Modal-Kopf ist der Bezugsrahmen des Panels',
           /#settings-modal\s+\.modal-header\s*\{[^}]*position:\s*relative/.test(css),
           css.slice(Math.max(0, css.indexOf('#settings-modal .modal-header')), 120));
    pruefe('die Panelbreite ist an den Bezugsrahmen gebunden (nicht an vw)',
           /max-width:\s*calc\(\s*100%/.test(regel('.st-such-panel'))
           && !/\dvw/.test(regel('.st-such-panel')), regel('.st-such-panel'));
    pruefe('Panelhoehe haengt am Sichtfenster, nicht an einer festen Zahl',
           /max-height:\s*min\([^)]*vh/.test(regel('.st-such-liste')), regel('.st-such-liste'));
    pruefe('Titelzeile darf schrumpfen (min-width: 0)',
           /min-width:\s*0/.test(regel('.st-such-titel')));
    // ⚠ ZWEI GETRENNTE AUSSAGEN. Zusammengefasst als `A && B || C` war die
    // Pruefung TRIVIAL WAHR (C traf immer zu) – gefunden von der Gegenprobe.
    const grp = regel('.modal-head-actions');
    pruefe('die Symbolgruppe darf schrumpfen',
           /flex:\s*0 1 auto/.test(grp) && /min-width:\s*0/.test(grp), grp.slice(0, 200));
    const i = css.indexOf('.modal-head-actions > .btn-icon');
    const symb = i < 0 ? '' : css.slice(i, css.indexOf('}', i));
    pruefe('… ihre Symbole aber nicht', /flex:\s*0 0 auto/.test(symb), symb.slice(0, 200));
    pruefe('angesprungener Listeneintrag ist sichtbar hervorgehoben',
           /box-shadow/.test(regel('.sk-item-treffer')));
    // ⚠ `regel()` schneidet AB dem Selektor – der erklaerende Kommentar davor
    // (er nennt `box-shadow` woertlich) liegt also ausserhalb; sonst laese der
    // Waechter seine eigene Begruendung.
    const hv = regel('.st-such-treffer');
    pruefe('angesprungener Punkt der Oberflaeche ist hervorgehoben',
           /box-shadow/.test(hv), hv.slice(0, 120));
}

// ── 8. Die OBERFLAECHE als Suchraum (gemeldet 2026-09-20: „ldap findet nichts")
//
// ⚠ GEMESSEN WIRD GEGEN DIE ECHTE settings.html IN DER LAGE DES BETRIEBS
// (`seiteVoll`): Reiter eingeblendet, Klapp-Handler aus app.js gebunden. Mit
// dem rohen Markup sind 21 von 29 Reitern `display:none`, und der halbe Index
// entstuende gar nicht - die Messung waere gruen und wertlos.
{
    const { dom, w, abschnitte } = await seiteVoll(KORPUS);

    pruefe('es gibt ueberhaupt Klappabschnitte zum Binden', abschnitte > 10, String(abschnitte));

    // Der gemeldete Fall, woertlich.
    await tippe(w, 'ldap');
    const tLdap = titelTexte(w);
    pruefe('„ldap" findet etwas (der gemeldete Fall)', tLdap.length > 0, String(tLdap.length));
    pruefe('… und zwar an erster Stelle den AD-Abschnitt',
           /Active Directory|LDAP/i.test(tLdap[0] || ''), tLdap[0] || '(nichts)');

    // Alle drei Arten sind im Index - sonst ist „Einstellungen" eine halbe Zusage.
    const idx = w.SettingsSearch._index() || [];
    const zaehl = {};
    idx.forEach(e => { zaehl[e.art] = (zaehl[e.art] || 0) + 1; });
    pruefe('Reiter sind indiziert', (zaehl.reiter || 0) > 0, JSON.stringify(zaehl));
    pruefe('Abschnitte sind indiziert', (zaehl.abschnitt || 0) > 0, JSON.stringify(zaehl));
    pruefe('Feldbeschriftungen sind indiziert', (zaehl.einstellung || 0) > 0, JSON.stringify(zaehl));
    pruefe('die Skills sind weiterhin dabei', (zaehl.skill || 0) > 0, JSON.stringify(zaehl));

    // ⚠ EIN VERSTECKTER REITER IST KEIN ZIEL: sein Knopf laesst sich nicht
    // druecken, der Treffer fuehrte ins Leere.
    const btn = w.document.querySelector('.settings-tab-btn[data-settings-tab="telemetry"]');
    if (btn) btn.style.display = 'none';
    w.SettingsSearch._verwerfen();
    await tippe(w, 'telemetry');
    const versteckt = (w.SettingsSearch._index() || [])
        .filter(e => e.art === 'reiter' && e.reiter === 'telemetry').length;
    pruefe('ein versteckter Reiter kommt NICHT in den Index', versteckt === 0, String(versteckt));
    if (btn) btn.style.display = '';
    w.SettingsSearch._verwerfen();

    // Keine Dubletten: ein Reiter, der einem Skill gehoert, steht schon als
    // Skill im Index und fuehrt ueber dieselbe Regel dorthin.
    await tippe(w, 'jira');
    const alsReiter = (w.SettingsSearch._index() || [])
        .filter(e => e.art === 'reiter' && e.reiter === 'jira').length;
    pruefe('ein Skill-Reiter steht nicht zusaetzlich als Reiter im Index',
           alsReiter === 0, String(alsReiter));

    // Beschriftung und Erlaeuterung sind getrennt.
    await tippe(w, 'admin-benutzer');
    const tAdm = titelTexte(w);
    pruefe('Beschriftung ohne angehaengten Hilfetext',
           tAdm.length > 0 && (tAdm[0] || '').length < 40, tAdm[0] || '(nichts)');

    // Der Pfad unterscheidet gleichnamige Beschriftungen.
    const pf = pfadTexte(w);
    pruefe('der Pfad nennt Reiter und Abschnitt',
           (pf[0] || '').indexOf('›') > 0, pf[0] || '(leer)');

    dom.window.close();
}

// ── 8b. Der Sprung zu einem Punkt der Oberflaeche
{
    const { dom, w } = await seiteVoll(KORPUS);
    const geklickt = [];
    w.document.querySelectorAll('.settings-tab-btn[data-settings-tab]').forEach(b => {
        b.addEventListener('click', () => geklickt.push(b.getAttribute('data-settings-tab')));
    });
    await tippe(w, 'ldap');
    const tr = w.SettingsSearch._treffer();
    const ziel = tr[0] && tr[0].e;
    pruefe('Treffer vorhanden zum Anspringen', !!ziel && ziel.art === 'abschnitt',
           ziel ? ziel.art : '(keiner)');

    const hdrId = ziel && ziel.el && ziel.el.id;
    const body = hdrId ? w.document.getElementById(hdrId.replace(/-hdr$/, '-body')) : null;
    pruefe('Abschnitt ist VOR dem Klick zu (sonst misst der Test nichts)',
           !!body && body.style.display === 'none', body ? body.style.display : '?');

    klick(w.document.querySelector('.st-such-item'), w);
    await tickCount(4);

    // ⚠ DEN REITER SCHALTET app.js UM, und die laedt dieser Lauf bewusst nicht
    // (sie startet Poll-Timer und will ein Dutzend Endpunkte). Gemessen wird
    // deshalb, dass der richtige Reiterknopf WIRKLICH GEKLICKT wird; dass an
    // ihm ein Handler haengt, prueft Abschnitt 8d als Regel – dieselbe
    // Aufteilung wie beim Klappabschnitt.
    pruefe('der Klick trifft den richtigen Reiterknopf',
           geklickt.indexOf('security') >= 0, geklickt.join(',') || '(keiner)');
    pruefe('… und klappt den Abschnitt AUF',
           !!body && body.style.display !== 'none', body ? body.style.display : '?');
    pruefe('… und hebt ihn hervor',
           !!ziel && ziel.el.classList.contains('st-such-treffer'));
    pruefe('Feld geleert und Panel zu', feldVon(w).value === ''
           && panelVon(w).hasAttribute('hidden'));

    // ⚠ EIN ZWEITER KLICK DARF NICHT ZUKLAPPEN. Ein blindes click() auf die
    // Kopfzeile kehrt den Zustand um - der Treffer haette den Abschnitt dann
    // geschlossen, also genau das Gegenteil bewirkt.
    await tippe(w, 'ldap');
    klick(w.document.querySelector('.st-such-item'), w);
    await tickCount(4);
    pruefe('ein zweiter Treffer laesst den offenen Abschnitt OFFEN',
           !!body && body.style.display !== 'none', body ? body.style.display : '?');
    dom.window.close();
}

// ── 8c. Fail-open: der Skill-Abruf ist NICHT die Bedingung der Suche
{
    const { dom, w } = await seiteVoll(KORPUS, { fetch: () => Promise.reject(new Error('weg')) });
    w.jarvisSkillsOnce = () => Promise.reject(new Error('weg'));
    w.SettingsSearch._verwerfen();
    await tippe(w, 'ldap');
    const t2 = titelTexte(w);
    pruefe('ohne Skill-Liste bleibt die Oberflaeche durchsuchbar', t2.length > 0, String(t2.length));
    const fuss = (w.document.getElementById('st-such-hinweis').textContent || '');
    pruefe('… und der Fuss sagt, dass ein Teil fehlt',
           /Skill/i.test(fuss) && /nur/i.test(fuss), fuss.slice(0, 90));
    dom.window.close();
}

// ── 8d. Drift: worauf sich der Sprung verlaesst
{
    const app = liesJs('frontend/js/app.js');
    const html = lies('settings.html');
    const gebunden = new Set((app.match(/hdr:\s*'([^']+)'/g) || [])
        .map(x => x.replace(/.*'([^']+)'.*/, '$1')));
    const alle = new Set();
    let m; const re = /class="[^"]*kb-collapse-header[^"]*"[^>]*id="([^"]+)"/g;
    while ((m = re.exec(html))) alle.add(m[1]);
    const ohne = [...alle].filter(x => !gebunden.has(x));
    // ⚠ `zumElement` klickt die Kopfzeile und verlaesst sich darauf, dass
    // app.js dort einen Handler gebunden hat (synchron im Reiter-Klick). Ein
    // Abschnitt ohne Handler liesse den Treffer den Reiter oeffnen und den
    // Abschnitt zu - eine halbe Zusage, die niemand erklaeren koennte.
    pruefe('es gibt ueberhaupt Klappabschnitte im Markup', alle.size > 10, String(alle.size));

    // ⚠ Und der Reiterknopf braucht seinen Handler – sonst aktiviert der
    // Treffer den Reiter nicht, und Abschnitt 8b misst nur den Klick ins
    // Leere. Die Bindung laeuft in app.js SYNCHRON im Klick-Handler der
    // Reiter (dort wird auch `_initXCollapse()` gerufen); waere sie
    // asynchron, kaeme das Aufklappen danach zu frueh.
    pruefe('app.js bindet einen Klick-Handler an die Reiterknoepfe',
           /settingsTabs[\s\S]{0,200}addEventListener\('click'/.test(app),
           app.slice(Math.max(0, app.indexOf('settingsTabs.forEach')), 80));
    pruefe('JEDER Klappabschnitt ist in app.js gebunden', ohne.length === 0,
           ohne.slice(0, 5).join(','));

    // Der Suchraum wird aus dem DOM abgeleitet, nicht aus einer Liste.
    // ⚠ AUF DER KOMMENTARFREIEN FASSUNG: der Modulkopf ERKLAERT, warum
    // `_SETTINGS_SECTIONS` (app.js) nicht benutzt wird – und nennt den Namen
    // dabei. Achtzehnter Fall dieser Klasse im Projekt.
    const qRoh = liesJs('frontend/js/settings_search.js');
    const q = ohneKommentare(qRoh);
    pruefe('Positivkontrolle: Kommentare sind wirklich entfernt',
           /_SETTINGS_SECTIONS/.test(qRoh) && q.indexOf('Achtzehnter') < 0,
           'roh=' + /_SETTINGS_SECTIONS/.test(qRoh));
    pruefe('die Oberflaeche wird aus dem DOM gelesen',
           /querySelectorAll\('\.kb-collapse-header'\)/.test(q)
           && /querySelectorAll\('\.settings-tab-btn/.test(q));
    pruefe('… und NICHT aus einer gepflegten Reiterliste',
           !/_SETTINGS_SECTIONS/.test(q));
}

console.log('\n' + (fail === 0 ? '\x1b[32m' : '\x1b[31m') +
            'Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
bilanz = true;
process.exit(fail === 0 ? 0 : 1);
})();
