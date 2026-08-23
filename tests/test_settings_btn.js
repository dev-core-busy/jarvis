#!/usr/bin/env node
/**
 * Waechter: das Einstellungs-Zahnrad haengt an /api/me, NIE am Bereichs-Abruf.
 *
 * VORFALL (dreimal gemeldet, zuletzt 2026-08-23): auf /tracks, /claude und
 * /wissen fehlte das Symbol. Ursache war nicht ein vergessener Knopf – das
 * Markup war da –, sondern die QUELLE des Admin-Signals:
 *     /tracks  ->  ist_admin aus GET /api/tracks/status
 *     /claude  ->  ist_admin aus GET /api/claude/status
 *     /wissen  ->  is_admin  aus GET /api/wissen/scope
 * Scheitert dieser Abruf, laeuft die Einblendung nie. Und er scheitert genau
 * dann, wenn der Bereich nicht freigegeben ist (403) – also wenn ein
 * Administrator den Weg in die Einstellungen am dringendsten braucht, denn dort
 * wird die Freigabe gepflegt. Auf DEV gemessen: dieselben Endpunkte antworten
 * fuer einen Administrator ohne Bereichsfreigabe mit 403, waehrend /api/me fuer
 * ihn `is_admin: true` liefert.
 *
 * DIESER TEST PRUEFT DIE REGEL, NICHT EINE LISTE: jede Seite mit einem
 * Zahnrad-Knopf muss ihn ueber `data-jarvis-settings` deklarieren und
 * `settings_btn.js` einbinden – auch eine Seite, die es heute noch nicht gibt.
 * Und kein Seiten-Skript darf den Knopf mehr selbst anfassen.
 *
 * Aufruf:  node tests/test_settings_btn.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const FE = path.join(ROOT, 'frontend');
let ok = 0, fail = 0;

function abschnitt(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function pruefe(name, bedingung, detail) {
    if (bedingung) { ok++; console.log(`  \x1b[32m✓\x1b[0m ${name}`); }
    else { fail++; console.log(`  \x1b[31m✗\x1b[0m ${name}${detail ? '  →  ' + detail : ''}`); }
}

const lies = p => fs.readFileSync(p, 'utf8');
/* Kommentare entfernen. NOETIG, WEIL EIN WAECHTER SONST SEINE EIGENE
 * BEGRUENDUNG LIEST: die Erklaerungen in den Seiten-Skripten nennen die alten
 * Element-Ids. Ohne diesen Schritt waere die Pruefung "kein Skript fasst den
 * Knopf an" trivial rot – und nach dem Anpassen trivial gruen. (Neunter Fall
 * dieser Klasse in diesem Projekt.) */
function nurCode(t) {
    return t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const SEITEN = fs.readdirSync(FE).filter(f => f.endsWith('.html'));

// ── 1. Das Modul selbst ─────────────────────────────────────────────────────
abschnitt('1. settings_btn.js – Quelle und Robustheit');
const MODUL_P = path.join(FE, 'js/settings_btn.js');
pruefe('Modul existiert', fs.existsSync(MODUL_P));
const MODUL = fs.existsSync(MODUL_P) ? lies(MODUL_P) : '';
const MCODE = nurCode(MODUL);
pruefe('fragt /api/me', MCODE.includes("'/api/me'") || MCODE.includes('"/api/me"'));
pruefe('liest is_admin', /\bis_admin\b/.test(MCODE));
// DIE KERNZUSAGE: kein bereichsspezifischer Endpunkt darf hier auftauchen.
const BEREICHS_EP = MCODE.match(/\/api\/(?!me\b)[a-z_]+/g) || [];
pruefe('kein anderer API-Endpunkt als /api/me', BEREICHS_EP.length === 0,
       BEREICHS_EP.join(', '));
pruefe('sucht per data-jarvis-settings (Konvention, keine Id-Liste)',
       MCODE.includes('data-jarvis-settings'));
// /wissen versteckt per Klasse `hidden` mit display:none !important – ein
// blosses style.display='' verliert dagegen.
pruefe('entfernt auch die Klasse hidden', /classList\.remove\(\s*['"]hidden['"]/.test(MCODE));
pruefe('bindet idempotent (Merker gegen zweiten Handler)',
       /dataset\.\w+/.test(MCODE) && MCODE.includes('addEventListener'));
pruefe('merkt den Rueckweg (jarvis_settings_return)',
       MCODE.includes('jarvis_settings_return'));
pruefe('Netzfehler blendet NICHTS ein (kein zeige(true) im catch)',
       !/catch\s*\([^)]*\)\s*\{[^}]*zeige\(\s*true/.test(MCODE));

// ── 2. Jede Seite mit Zahnrad deklariert es und bindet das Modul ein ────────
abschnitt('2. Regel: Zahnrad-Seite => data-Attribut + Modul eingebunden');
let mitKnopf = 0;
for (const datei of SEITEN) {
    const s = lies(path.join(FE, datei));
    // Ein Zahnrad-Knopf ist ein <button>, dessen Beschriftung nav.settings ist.
    const hatKnopf = /data-i18n-title\s*=\s*"nav\.settings"/.test(s);
    if (!hatKnopf) continue;
    mitKnopf++;
    pruefe(`${datei}: Knopf traegt data-jarvis-settings`,
           /data-jarvis-settings\s*=/.test(s));
    pruefe(`${datei}: bindet settings_btn.js ein`,
           /<script[^>]+js\/settings_btn\.js/.test(s));
}
pruefe('mindestens 10 Seiten mit Zahnrad gefunden', mitKnopf >= 10, 'gefunden: ' + mitKnopf);

// ── 3. Kein Seiten-Skript fasst den Knopf mehr an ──────────────────────────
abschnitt('3. EINE Meinung: kein Seiten-Skript blendet selbst ein');
// Die Ids aus dem Markup einsammeln – so erwischt die Pruefung auch eine
// kuenftige Seite mit neuer Id, ohne dass jemand diese Liste pflegt.
const IDS = new Set();
for (const datei of SEITEN) {
    const s = lies(path.join(FE, datei));
    const re = /<button[^>]*\bid="([^"]+)"[^>]*data-i18n-title\s*=\s*"nav\.settings"/g;
    let m; while ((m = re.exec(s))) IDS.add(m[1]);
    const re2 = /<button[^>]*data-i18n-title\s*=\s*"nav\.settings"[^>]*\bid="([^"]+)"/g;
    while ((m = re2.exec(s))) IDS.add(m[1]);
}
pruefe('Knopf-Ids aus dem Markup gelesen', IDS.size >= 10, [...IDS].join(', '));

/* Geprueft werden GENAU die Skripte, die auf einer Seite MIT Zahnrad laufen.
 * Das ist die praezise Regel und braucht keine Ausnahmeliste: `app.js` nennt
 * `btn-settings` als optionalen Modal-Oeffner, laeuft aber nur auf
 * settings.html – und die hat kein Zahnrad. Eine Sammelfreigabe fuer app.js
 * waere das Anti-Muster; sie wuerde eine spaetere echte Doppelverdrahtung
 * durchlassen. */
const ZAHNRAD_SKRIPTE = new Set();
for (const datei of SEITEN) {
    const s = lies(path.join(FE, datei));
    if (!/data-i18n-title\s*=\s*"nav\.settings"/.test(s)) continue;
    const re = /<script[^>]+src="\/static\/js\/([\w.-]+\.js)/g;
    let m; while ((m = re.exec(s))) ZAHNRAD_SKRIPTE.add(m[1]);
}
ZAHNRAD_SKRIPTE.delete('settings_btn.js');
pruefe('Skripte der Zahnrad-Seiten eingesammelt', ZAHNRAD_SKRIPTE.size >= 8,
       'gefunden: ' + ZAHNRAD_SKRIPTE.size);
let doppelt = [];
for (const f of ZAHNRAD_SKRIPTE) {
    const pfad = path.join(FE, 'js', f);
    if (!fs.existsSync(pfad)) continue;
    const code = nurCode(lies(pfad));
    const treffer = [...IDS].filter(id => code.includes(`'${id}'`) || code.includes(`"${id}"`));
    if (treffer.length) doppelt.push(`${f}: ${treffer.join('/')}`);
}
pruefe('kein Skript einer Zahnrad-Seite fasst den Knopf an', doppelt.length === 0,
       doppelt.join('  |  '));

// Inline-Skripte der Seiten ebenso (portal.html hatte seine Logik inline).
for (const datei of SEITEN) {
    const s = lies(path.join(FE, datei));
    const skripte = (s.match(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g) || []).join('\n');
    const code = nurCode(skripte);
    const treffer = [...IDS].filter(id => code.includes(`'${id}'`) || code.includes(`"${id}"`));
    pruefe(`${datei}: Inline-Skript fasst keinen Zahnrad-Knopf an`, treffer.length === 0,
           treffer.join(', '));
}

// ── 4. Rueckweg zeigt auf die eigene Seite ─────────────────────────────────
abschnitt('4. Rueckweg je Seite');
for (const datei of SEITEN) {
    const s = lies(path.join(FE, datei));
    const m = s.match(/data-jarvis-settings="([^"]*)"/);
    if (!m) continue;
    const erwartet = '/' + datei.replace(/\.html$/, '');
    pruefe(`${datei}: Rueckweg ${m[1]}`, m[1] === erwartet, 'erwartet ' + erwartet);
}

// ── 5. /api: Knopfleiste wie die uebrigen Seiten ───────────────────────────
abschnitt('5. /api – Knoepfe optisch und inhaltlich wie die Nachbarseiten');
{
    /* GEMELDET: "Symbole auf /api anpassen an die restlichen Seiten." Der Bruch
     * war doppelt: `.ad-btn` war ein gerahmtes 38x38-Kaestchen mit
     * Glas-Hintergrund (alle anderen Seiten: rahmenloses Symbol), und es fehlten
     * Issues, Einstellungen und Abmelden. api.html laedt chat.css NICHT, wo
     * `.btn-theme` steht – die Werte muessen dort also gepflegt werden, und
     * genau deshalb driftet es ohne Test wieder auseinander. */
    const api = lies(path.join(FE, 'api.html'));
    const regel = (api.match(/\.ad-btn\s*\{[^}]*\}/) || [''])[0];
    pruefe('/api: .ad-btn ohne Rahmen', /border:\s*none/.test(regel), regel.slice(0, 90));
    pruefe('/api: .ad-btn ohne eigene Flaeche', /background:\s*none/.test(regel));
    pruefe('/api: gleiches Innenmass wie .btn-theme (4px 8px)',
           /padding:\s*4px\s+8px/.test(regel));
    pruefe('/api: keine feste 38px-Kachel mehr',
           !/width:\s*38px/.test(regel) && !/height:\s*38px/.test(regel));
    pruefe('/api: SVG 20px wie ueberall', /\.ad-btn svg\s*\{[^}]*width:\s*20px/.test(api));

    // Vollstaendigkeit + Reihenfolge (wie auf den Nachbarseiten:
    // Sprache -> Issues -> Hell/Dunkel -> Startseite -> Einstellungen -> Abmelden)
    const stellen = {
        issues:   api.indexOf('jv-issues-btn'),
        theme:    api.indexOf('id="btn-theme-toggle"'),
        home:     api.indexOf('data-i18n-title="nav.home"'),
        settings: api.indexOf('data-jarvis-settings'),
        logout:   api.indexOf('id="ad-logout-btn"'),
    };
    for (const [name, pos] of Object.entries(stellen))
        pruefe(`/api: Knopf ${name} vorhanden`, pos >= 0);
    pruefe('/api: Reihenfolge Issues < Theme < Home < Einstellungen < Abmelden',
           stellen.issues < stellen.theme && stellen.theme < stellen.home
           && stellen.home < stellen.settings && stellen.settings < stellen.logout,
           JSON.stringify(stellen));
    // Abmelden braucht sessions.js – ohne es wird die Abmeldung nie gemeldet
    // und die Sitzung gilt noch zwei Minuten als online.
    pruefe('/api: bindet sessions.js ein (JarvisSession.logout)',
           /<script[^>]+js\/sessions\.js/.test(api));
    pruefe('/api: Abmelden meldet VOR dem Verwerfen des Tokens',
           api.indexOf('JarvisSession.logout()') < api.indexOf('removeItem'),
           'Reihenfolge im Abmelde-Handler');
}

console.log(`\n\x1b[1m${ok} bestanden, ${fail} fehlgeschlagen\x1b[0m`);
process.exit(fail ? 1 : 0);
