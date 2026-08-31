#!/usr/bin/env node
/* Waechter: der VORGABE-Produktname darf nicht in Oberflaechen-Texten stehen.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT (2026-08-31): auf ECHT heisst der Assistent
 * `Nexerius`. Trotzdem stand "Jarvis" an dutzenden Stellen sichtbar da – im
 * Pulldown "Aufbereiten fuer", im Kopf der Update-Pille und in 30 i18n-Texten.
 * Aufgefallen ist das erst, als das Handbuch Screenshots bekam: der Text sagte
 * Nexerius, das Bild sagte Jarvis.
 *
 * DER MECHANISMUS, den dieser Waechter durchsetzt:
 *   i18n-Texte schreiben `{marke}`; branding.js setzt den Namen ein.
 *   Fuer Text, der NICHT im DOM landet (confirm/alert/document.title), gibt es
 *   `window.jarvisMarke()` – dort muss der Platzhalter am Aufrufort aufgeloest
 *   werden, sonst liest der Benutzer woertlich "{marke}".
 *
 * Geprueft wird die REGEL ueber alle Schluessel, nicht eine gepflegte Liste.
 * Ausnahmen stehen einzeln und mit Begruendung in AUSNAHMEN – es gibt keine
 * Sammelfreigabe.
 *
 *   node tests/test_marke_i18n.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const I18N = lies('frontend/js/i18n.js');
const BRANDING = lies('frontend/js/branding.js');

let ok = 0, fail = 0;
const pruefe = (bed, text, detail) => {
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (detail ? ' – ' + detail : '')); }
};
const abschnitt = (t) => console.log('\n\x1b[1m' + t + '\x1b[0m');

/* ── Ausnahmen: jede einzeln, jede mit Grund ────────────────────────────────
 * Diese Texte MUESSEN "jarvis" enthalten – es ist dort kein Produktname,
 * sondern eine Kennung, die auf dem Server wirklich so heisst. Ein gebrandeter
 * Name waere hier eine falsche Angabe, kein Fortschritt. */
const AUSNAHMEN = {
    'security.broker_none_hint':        'Dienstname jarvis-broker.service',
    'security.broker_setup_confirm':    'Dienstnamen jarvis-broker*',
    'security.broker_teardown_confirm': 'Dienstnamen jarvis-broker*',
    'security.broker_mode_timeout':     'journalctl -u jarvis-broker-migrate',
    'security.pw_change_hint':          'das Linux-Konto heisst jarvis',
    'security.ad_warn_none':            'der lokale Rueckweg ist das Konto jarvis',
    'knowledge.index_failed_more':      'journalctl -u jarvis.service',
    'cert.download':                    'die Datei heisst jarvis.cer (Content-Disposition)',
    'security.ad_group_ph':             'Beispiel-DN im KUNDEN-AD, kein Produktname',
    'chat.greeting':                    'wird von branding.js::applyAssistantName ueber einen eigenen Selektor gebrandet',
};

/* Nicht-DOM-Senken: dort wirkt der TreeWalker von branding.js nicht. */
const SENKEN = [
    { name: 'confirm(',      re: /confirm\s*\(/ },
    { name: 'alert(',        re: /alert\s*\(/ },
    { name: 'document.title', re: /document\.title\s*=/ },
];

// ── Woerterbuch je Sprache einlesen ────────────────────────────────────────
function block(lang) {
    const de = I18N.search(/^\s{0,4}de\s*:\s*\{/m);
    const en = I18N.search(/^\s{0,4}en\s*:\s*\{/m);
    if (de < 0 || en < 0) return '';
    return lang === 'de' ? I18N.slice(de, en) : I18N.slice(en);
}
function werte(lang) {
    const out = {};
    const re = /'([a-z_]+\.[a-z_0-9]+)'\s*:\s*'((?:[^'\\]|\\.)*)'/g;
    let m;
    const t = block(lang);
    while ((m = re.exec(t))) out[m[1]] = m[2];
    return out;
}
const DE = werte('de'), EN = werte('en');

// ══════════════════════════════════════════════════════════════════════════
abschnitt('1) Grundlage – das Woerterbuch wird ueberhaupt gelesen');
// ══════════════════════════════════════════════════════════════════════════
pruefe(Object.keys(DE).length > 500, 'der de-Block liefert Werte', String(Object.keys(DE).length));
pruefe(Object.keys(EN).length > 500, 'der en-Block liefert Werte', String(Object.keys(EN).length));
// Positivkontrolle: der Platzhalter ist ueberhaupt in Gebrauch. Ohne diese
// Zeile waere ein leeres Ergebnis unten aus dem falschen Grund gruen.
const mitMarke = Object.keys(DE).filter((k) => /\{marke/.test(DE[k]));
pruefe(mitMarke.length >= 10, 'der Platzhalter {marke} ist in Gebrauch', String(mitMarke.length));

// ══════════════════════════════════════════════════════════════════════════
abschnitt('2) REGEL: kein Vorgabe-Produktname in einem Oberflaechen-Text');
// ══════════════════════════════════════════════════════════════════════════
for (const [lang, tab] of [['de', DE], ['en', EN]]) {
    const schuldig = Object.keys(tab)
        .filter((k) => /jarvis/i.test(tab[k]))
        .filter((k) => !(k in AUSNAHMEN));
    pruefe(schuldig.length === 0,
           `${lang}: kein Text nennt "Jarvis" ohne Eintrag in AUSNAHMEN`,
           schuldig.join(', '));
}
// Eine Ausnahme, die gar nicht mehr zutrifft, ist eine stille Freigabe fuer
// die Zukunft – sie gehoert heraus.
const unnoetig = Object.keys(AUSNAHMEN)
    .filter((k) => !(/jarvis/i.test(DE[k] || '') || /jarvis/i.test(EN[k] || '')));
pruefe(unnoetig.length === 0, 'keine Ausnahme ohne Anlass', unnoetig.join(', '));

// ══════════════════════════════════════════════════════════════════════════
abschnitt('3) Beide Sprachen tragen denselben Platzhalter');
// ══════════════════════════════════════════════════════════════════════════
// Sonst verraet genau eine Sprache das Produkt – und gemeldet wird es von dem
// Benutzer, der die andere eingestellt hat.
const nurDe = mitMarke.filter((k) => !/\{marke/.test(EN[k] || ''));
const nurEn = Object.keys(EN).filter((k) => /\{marke/.test(EN[k]) && !/\{marke/.test(DE[k] || ''));
pruefe(nurDe.length === 0, 'kein Schluessel mit {marke} nur auf Deutsch', nurDe.join(', '));
pruefe(nurEn.length === 0, 'kein Schluessel mit {marke} nur auf Englisch', nurEn.join(', '));

// ══════════════════════════════════════════════════════════════════════════
abschnitt('4) Nicht-DOM-Senken loesen den Platzhalter am Aufrufort auf');
// ══════════════════════════════════════════════════════════════════════════
// branding.js ersetzt {marke} mit einem TreeWalker ueber document.body. Was
// nie im Body landet – confirm(), alert(), document.title – erreicht er nicht;
// dort steht der Platzhalter dann WOERTLICH. Fuer diese Faelle gibt es
// window.jarvisMarke().
const jsDateien = fs.readdirSync(path.join(ROOT, 'frontend/js'))
    .filter((f) => f.endsWith('.js'))
    .map((f) => ['frontend/js/' + f, lies('frontend/js/' + f)]);
const offen = [];
for (const [pfad, quelle] of jsDateien) {
    const zeilen = quelle.split('\n');
    zeilen.forEach((z, i) => {
        for (const senke of SENKEN) {
            if (!senke.re.test(z)) continue;
            // Welche i18n-Schluessel stehen in dieser Zeile?
            for (const m of z.matchAll(/t\(\s*'([a-z_]+\.[a-z_0-9]+)'/g)) {
                const k = m[1];
                if (!/\{marke/.test(DE[k] || '')) continue;
                // Aufgeloest? Entweder direkt in der Zeile oder ueber einen
                // Helfer, der in derselben Datei den Namen einsetzt.
                const umfeld = zeilen.slice(Math.max(0, i - 2), i + 3).join('\n');
                if (!/jarvisMarke|markeText|\{marke\}/.test(umfeld)) {
                    offen.push(`${pfad}:${i + 1} ${k} (${senke.name})`);
                }
            }
        }
    });
}
pruefe(offen.length === 0,
       'jede Nicht-DOM-Senke loest {marke} selbst auf',
       offen.join(' | '));
pruefe(/window\.jarvisMarke\s*=/.test(BRANDING),
       'branding.js stellt window.jarvisMarke bereit');

// ══════════════════════════════════════════════════════════════════════════
abschnitt('5) Der Platzhalter wirkt auch auf SPAETER gerenderten Text');
// ══════════════════════════════════════════════════════════════════════════
// Das ist der Grund, warum die 30 Texte ueberhaupt hart "Jarvis" schrieben:
// bis 2026-08-31 lief markeEinsetzen() nur beim Laden und bei einem
// Sprachwechsel. Ein Hinweis, den ein Modul spaeter rendert, behielt den
// Platzhalter woertlich – die Frage "Markup oder JS?" musste man je Text
// einzeln nachsehen. Der Beobachter nimmt diese Frage weg.
pruefe(/new MutationObserver\([\s\S]{0,400}?document\.body/.test(BRANDING),
       'branding.js beobachtet den Body auf neue Platzhalter');
pruefe(/characterData:\s*true/.test(BRANDING) && /subtree:\s*true/.test(BRANDING),
       'und zwar Struktur UND Textinhalte im ganzen Teilbaum');
// Ohne den Filter schreibt der Durchlauf sich selbst in eine Endlosschleife:
// markeEinsetzen() SETZT Textknoten, und das ist wieder eine Aenderung.
pruefe(/function betrifftUns/.test(BRANDING),
       'ein Filter verhindert die Selbst-Ausloesung (Endlosschleife)');
pruefe(/attributes/.test(BRANDING) === false
       || /attributes:\s*true/.test(BRANDING) === false,
       'Attribute werden NICHT beobachtet (der Durchlauf setzt sie selbst)');

console.log('\n' + '='.repeat(58));
console.log((fail ? '\x1b[31m' : '\x1b[32m') + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
console.log('='.repeat(58));
process.exit(fail ? 1 : 0);
