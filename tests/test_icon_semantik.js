#!/usr/bin/env node
/**
 * Waechter: Muelleimer = LOESCHEN, × = SCHLIESSEN (Design-Entscheidung 2026-08-19).
 *
 * Vorher stand fuer BEIDES ein × – teils in derselben Zeile derselben
 * Oberflaeche. Wer ein Panel schliessen wollte, konnte damit einen Eintrag
 * loeschen. Dieser Test verhindert den Rueckfall.
 *
 * ER PRUEFT DIE REGEL, NICHT EINE LISTE VON FUNDSTELLEN: jeder Knopf, dessen
 * Beschriftung (title/aria-label/label) ein Loesch-Wort traegt, muss den
 * Muelleimer fuehren – auch ein Knopf, den es heute noch nicht gibt. Eine
 * gepflegte Fundstellen-Liste waere beim naechsten Feature wieder unvollstaendig.
 *
 * Aufruf:  node tests/test_icon_semantik.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;

function abschnitt(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function pruefe(name, bedingung, detail) {
    if (bedingung) { ok++; console.log(`  \x1b[32m✓\x1b[0m ${name}`); }
    else { fail++; console.log(`  \x1b[31m✗\x1b[0m ${name}${detail ? '  →  ' + detail : ''}`); }
}

function dateien(basis, endungen) {
    const out = [];
    (function lauf(d) {
        for (const e of fs.readdirSync(d, { withFileTypes: true })) {
            const p = path.join(d, e.name);
            if (e.isDirectory()) { if (e.name !== 'node_modules' && e.name !== 'vendor') lauf(p); }
            else if (endungen.includes(path.extname(e.name))) out.push(p);
        }
    })(path.join(ROOT, basis));
    return out;
}

const UI = [...dateien('frontend', ['.html', '.js']), ...dateien('skills', ['.html', '.js'])];
const rel = (p) => path.relative(ROOT, p);

// Zeichen, die als LOESCHEN missverstanden werden koennen.
// DAS `u`-FLAG IST PFLICHT: 🗙 liegt ausserhalb der BMP, ohne `u` zerlegt die
// Zeichenklasse es in Surrogate und matcht dann die HALBE Einheit \uD83D –
// also jedes beliebige Emoji, z.B. das 📂 des Verschieben-Knopfes. Genau
// dieser Fehlalarm ist beim ersten Lauf aufgetreten (die Warnung dazu steht in
// CLAUDE.md seit dem Add-in-Umbau).
// Auch die HTML-ENTITIES, nicht nur die Zeichen. GEMELDET 2026-08-19: in
// `tracks.js` stand `&#10005;` am Loeschen-Knopf – der Waechter war blind
// dafuer und meldete nichts, obwohl die Regel verletzt war.
const KREUZE = /[×✕✖⨯🗙]|&times;|&#215;|&#x?2715;?|&#10005;|&#10006;/iu;
// Loesch-Woerter in Beschriftungen. Bewusst ENG: "clear" allein trifft sonst
// CSS-Eigenschaften und "close" enthaelt kein Loeschen.
const LOESCHWORT = /l[oö]sch|entfern|delete|remove|deinstall|uninstall|widerruf|purge|leeren/i;
// Ausdrueckliche, begruendete Ausnahmen – jede einzeln, keine Sammelfreigabe.
const AUSNAHMEN = [
    // Chips/Anhangs-Vorschau: nimmt einen Eintrag aus einer NOCH NICHT
    // gespeicherten Auswahl. Es wird nichts geloescht – der Anhang ist nicht
    // hochgeladen, die Freigabeliste nicht gespeichert. Das ist "verwerfen",
    // nicht "loeschen", und × ist dafuer die uebliche Form.
    /class="token-x"/,
    /attach-chip-remove|uc-attach-chip-rm/,
    // Browsereigenes Leeren eines type=search-Feldes – nicht unser Knopf.
    /natives ×-L/,
];

abschnitt('1 – Zentrales Modul');

const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
pruefe('frontend/js/icons.js vorhanden', ICONS.length > 0);
pruefe('trash() liefert ein SVG (kein Emoji)',
    /trash:\s*function\s*\(\)\s*\{\s*return MUELL;/.test(ICONS) && /<svg class="jv-ico jv-ico-trash"/.test(ICONS));
pruefe('close() liefert ein SVG', /close:\s*function\s*\(\)\s*\{\s*return KREUZ;/.test(ICONS));
// Ein Emoji folgt keiner Theme-Variablen und fehlt auf manchen Systemen.
// GEPRUEFT WIRD DER CODE, NICHT DER KOMMENTAR: die Begruendung im Modulkopf
// nennt 🗑️ ausdruecklich – ein Waechter, der seine eigene Begruendung liest,
// schlaegt falsch an (im Projekt inzwischen der neunte Fall).
const ohneKommentar = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
pruefe('kein Emoji-Muelleimer im Modul', !/🗑/u.test(ohneKommentar(ICONS)));
pruefe('SVG erbt die Farbe (currentColor)', /stroke="currentColor"/.test(ICONS));
pruefe('Symbol ist fuer Screenreader Dekoration', /aria-hidden="true"/.test(ICONS));

const THEME = fs.readFileSync(path.join(ROOT, 'frontend/css/theme.css'), 'utf8');
pruefe('.jv-ico steht in theme.css (jede Seite), nicht in style.css', /\.jv-ico\s*\{/.test(THEME));
const STYLE = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');
pruefe('.jv-ico ist NICHT zusaetzlich in style.css (keine Drift)', !/\.jv-ico\s*\{/.test(STYLE));

abschnitt('2 – icons.js ist auf jeder Seite geladen, und zwar zuerst');

const SEITEN = UI.filter((p) => p.endsWith('.html') && !rel(p).startsWith('skills'));
for (const s of SEITEN) {
    const txt = fs.readFileSync(s, 'utf8');
    if (!/<script src="\/static\/js\//.test(txt)) continue;   // Seite ohne eigene Skripte
    pruefe(`${rel(s)} laedt icons.js`, txt.includes('js/icons.js'));
}
// Reihenfolge: ein Modul, das beim Rendern JarvisIcons.trash() aufruft, darf
// nicht vor dem Modul stehen, das es definiert.
const NUTZER = UI.filter((p) => p.endsWith('.js') && !p.endsWith('icons.js')
    && fs.readFileSync(p, 'utf8').includes('JarvisIcons'));
let reihenfolgeOk = true, wo = '';
for (const s of SEITEN) {
    const txt = fs.readFileSync(s, 'utf8');
    if (!txt.includes('js/icons.js')) continue;
    const pos = txt.indexOf('js/icons.js');
    for (const n of NUTZER) {
        const m = txt.match(new RegExp('src="[^"]*' + path.basename(n).replace('.', '\\.') + '\\?'));
        if (m && m.index < pos) { reihenfolgeOk = false; wo = `${rel(s)} → ${path.basename(n)}`; }
    }
}
pruefe('icons.js steht vor jedem Modul, das es benutzt', reihenfolgeOk, wo);
pruefe('mindestens 15 Module benutzen das zentrale Modul', NUTZER.length >= 15, `${NUTZER.length}`);

abschnitt('3 – DIE REGEL: Loesch-Beschriftung ⇒ Muelleimer, nie ×');

const verstoesse = [];
for (const p of UI) {
    if (p.endsWith('icons.js') || rel(p).startsWith('tests')) continue;
    const zeilen = fs.readFileSync(p, 'utf8').split('\n');
    zeilen.forEach((z, i) => {
        if (!KREUZE.test(z)) return;
        // FENSTER statt Einzelzeile: ein Knopf wird regelmaessig ueber mehrere
        // Zeilen zusammengesetzt ('<button …' + title + '">×</button>'). Die
        // zeilenweise Pruefung sah weder das `<button` noch die Beschriftung
        // und liess `tracks.js` durch (gemeldet 2026-08-19).
        const fenster = zeilen.slice(Math.max(0, i - 3), i + 2).join('\n');
        if (AUSNAHMEN.some((a) => a.test(fenster))) return;
        if (!/<button|textContent|innerHTML|icon:\s*['"]/.test(fenster)) return;
        if (!LOESCHWORT.test(fenster)) return;
        verstoesse.push(`${rel(p)}:${i + 1}  ${z.trim().slice(0, 90)}`);
    });
}
pruefe('kein Bedienelement mit Loesch-Beschriftung fuehrt ein ×',
    verstoesse.length === 0, '\n      ' + verstoesse.join('\n      '));

abschnitt('4 – Die Gegenrichtung: Schliessen bleibt ×, nie Muelleimer');

const falscheMuell = [];
for (const p of UI) {
    if (p.endsWith('icons.js')) continue;
    const zeilen = fs.readFileSync(p, 'utf8').split('\n');
    zeilen.forEach((z, i) => {
        if (!/jv-ico-trash|JarvisIcons\.trash|setTrash/.test(z)) return;
        // "Schliessen"/"Abbrechen" an einem Muelleimer ist genau der
        // umgekehrte Fehler und mindestens so gefaehrlich.
        if (/schlie|close|abbrech|cancel/i.test(z) && !/icons\.js|Design|Entscheidung/i.test(z)) {
            falscheMuell.push(`${rel(p)}:${i + 1}  ${z.trim().slice(0, 90)}`);
        }
    });
}
pruefe('kein Schliessen-/Abbrechen-Knopf fuehrt einen Muelleimer',
    falscheMuell.length === 0, '\n      ' + falscheMuell.join('\n      '));

abschnitt('5 – Kein Emoji-Muelleimer als Bedienelement');

// 🗑️ wird je nach System farbig gerendert, folgt keinem Theme und fehlt auf
// manchen Systemen ganz. In Meldungstexten (Toasts) ist es unkritisch, an
// einem KNOPF nicht.
const emojiKnopf = [];
for (const p of UI) {
    const zeilen = fs.readFileSync(p, 'utf8').split('\n');
    zeilen.forEach((z, i) => {
        if (!/🗑/u.test(z)) return;
        if (/<button|textContent\s*=|icon:/.test(z)) emojiKnopf.push(`${rel(p)}:${i + 1}  ${z.trim().slice(0, 80)}`);
    });
}
pruefe('kein Knopf traegt ein Muelleimer-EMOJI', emojiKnopf.length === 0,
    '\n      ' + emojiKnopf.join('\n      '));

abschnitt('6 – Die eigenstaendige Vision-Oberflaeche fuehrt dasselbe SVG');

// Eigene Flask-App mit eigenem static/ – sie kann das zentrale Modul nicht
// laden und traegt das SVG woertlich. Genau deshalb muss ein Test beide
// vergleichen, sonst laufen sie beim naechsten Feinschliff auseinander.
const VIS = fs.readFileSync(path.join(ROOT, 'skills/jarvis-vision/static/script.js'), 'utf8');
const pfadAus = (t) => (t.match(/<path d="(M19 6v14[^"]*)"/) || [])[1];
pruefe('Vision-Skript enthaelt den Muelleimer', /jv-ico-trash/.test(VIS));
pruefe('Vision-SVG ist identisch zum zentralen', pfadAus(VIS) === pfadAus(ICONS),
    `${pfadAus(VIS)} vs ${pfadAus(ICONS)}`);
const VISCSS = fs.readFileSync(path.join(ROOT, 'skills/jarvis-vision/static/style.css'), 'utf8');
pruefe('Vision-CSS kennt .jv-ico (sonst 24px-Riesensymbol)', /\.jv-ico\s*\{/.test(VISCSS));

abschnitt('7 – Auswahl-Chips: × bleibt, aber die Beschriftung luegt nicht');

// Der dritte Fall neben "loeschen" und "schliessen": ein Chip nimmt einen
// Eintrag aus einer NOCH NICHT GESPEICHERTEN Auswahl. Dort ist × richtig –
// aber solange die Beschriftung "Entfernen" sagt, sieht es wie ein Loeschen
// aus. Live gemessen: genau sieben solcher Knoepfe standen in /settings.
const I18N_ROH = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
pruefe('ldap.remove sagt "Aus Auswahl nehmen", nicht "Entfernen"',
    /'ldap\.remove':\s*'Aus Auswahl nehmen'/.test(I18N_ROH));
pruefe('englische Fassung ebenso',
    /'ldap\.remove':\s*'Remove from selection'/.test(I18N_ROH));
for (const [datei, klasse] of [['frontend/js/chat.js', 'attach-chip-remove'],
                               ['frontend/js/userchat.js', 'uc-attach-chip-rm']]) {
    const t = fs.readFileSync(path.join(ROOT, datei), 'utf8');
    const i = t.indexOf(klasse);
    pruefe(`${path.basename(datei)}: Anhangs-Chip hat eine Beschriftung`,
        i > 0 && /common\.unselect/.test(t.slice(i, i + 400)));
}

abschnitt('8 – Erklaertexte nennen das richtige Symbol');

const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
// Ein Hilfetext, der "× = löschen" sagt, ist nach dem Umbau schlicht falsch.
const falscheTexte = [];
I18N.split('\n').forEach((z, i) => {
    if (/[×✕]\s*=\s*(l[oö]schen|delete)/i.test(z)) falscheTexte.push(`i18n.js:${i + 1}  ${z.trim().slice(0, 90)}`);
});
pruefe('kein i18n-Text behauptet "× = löschen"', falscheTexte.length === 0,
    '\n      ' + falscheTexte.join('\n      '));
pruefe('der Auditier-Hinweis nennt den Muelleimer', /Mülleimer = löschen/.test(I18N));
pruefe('englische Fassung ebenso', /trash = delete/.test(I18N));

console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
process.exit(fail === 0 ? 0 : 1);
