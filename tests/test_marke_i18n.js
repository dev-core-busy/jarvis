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
    'security.ad_group_warning':        'nennt denselben lokalen Rueckweg: das Konto jarvis',
    'knowledge.index_failed_more':      'journalctl -u jarvis.service',
    'cert.download':                    'die Datei heisst jarvis.cer (Content-Disposition)',
    'security.ad_group_ph':             'Beispiel-DN im KUNDEN-AD, kein Produktname',
    'chat.greeting':                    'wird von branding.js::applyAssistantName ueber einen eigenen Selektor gebrandet',
    // Kein Anzeigename, sondern das DRAHTFORMAT: knowledge_sync.TOKEN_PREFIX
    // ist fest "JARVIS-KBS-1." – der Platzhalter zeigt, wie ein echtes Token
    // aussieht. Gebrandet waere der Hinweis schlicht falsch.
    'kbsync.f_token_ph':                'Token-Praefix JARVIS-KBS-1. (knowledge_sync.TOKEN_PREFIX)',
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

// ══════════════════════════════════════════════════════════════════════════
abschnitt('7) Der Rueckfalltext im Markup sagt dasselbe wie der i18n-Wert');
// ══════════════════════════════════════════════════════════════════════════
// Der Text zwischen den Tags ist der RUECKFALL: er steht da, bis applyLang()
// den i18n-Wert setzt – und dauerhaft, wenn i18n.js nicht laedt. Traegt der
// Wert {marke} und das Markup "Jarvis", zeigt die Seite fuer einen Moment
// (im Fehlerfall fuer immer) den Vorgabenamen. Der Platzhalter funktioniert
// dort genauso: branding.js geht mit einem TreeWalker ueber den Body und
// kennt kein i18n.
const HTML_DATEIEN = (function () {
    const aus = [];
    for (const d of ['frontend', 'frontend/addin', 'frontend/excel-addin']) {
        const voll = path.join(ROOT, d);
        if (!fs.existsSync(voll)) continue;
        for (const f of fs.readdirSync(voll)) {
            if (f.endsWith('.html')) aus.push(d + '/' + f);
        }
    }
    return aus.sort();
})();
const markierteKeys = new Set(mitMarke);
const rueckfaelle = [];
for (const f of HTML_DATEIEN) {
    const q = lies(f);
    // Elementkoerper mit data-i18n / data-i18n-html
    const re = /<([a-z]+)([^>]*\bdata-i18n(?:-html)?="([a-z_]+\.[a-z_0-9]+)"[^>]*)>([\s\S]*?)<\/\1>/g;
    let m;
    while ((m = re.exec(q))) {
        if (markierteKeys.has(m[3]) && /Jarvis/.test(m[4])) {
            rueckfaelle.push(f + ' → ' + m[3]);
        }
    }
}
pruefe(rueckfaelle.length === 0,
       'kein Rueckfalltext nennt "Jarvis", wo der i18n-Wert {marke} sagt',
       rueckfaelle.join(' | '));
// Positivkontrolle: es gibt ueberhaupt Rueckfalltexte zu markierten
// Schluesseln – sonst waere die Null oben aus dem falschen Grund gruen.
let gefunden = 0;
for (const f of HTML_DATEIEN) {
    const q = lies(f);
    const re = /data-i18n(?:-html)?="([a-z_]+\.[a-z_0-9]+)"/g;
    let m;
    while ((m = re.exec(q))) if (markierteKeys.has(m[1])) gefunden++;
}
pruefe(gefunden >= 10, 'markierte Schluessel kommen im Markup wirklich vor',
       String(gefunden));
// `.brand-app-name` ist der Gegenfall und MUSS "Jarvis" behalten: branding.js
// ersetzt dort den Text. Wer das mit {marke} verwechselt, bekommt den Namen
// doppelt gebrandet bzw. gar nicht.
const markenHaken = HTML_DATEIEN
    .filter((f) => /class="brand-app-name"[^>]*>Jarvis</.test(lies(f)));
pruefe(markenHaken.length >= 3,
       '.brand-app-name behaelt "Jarvis" (das ist der Branding-Haken)',
       String(markenHaken.length));

// ══════════════════════════════════════════════════════════════════════════
abschnitt('8) Auch Text OHNE data-i18n nennt den Vorgabenamen nicht');
// ══════════════════════════════════════════════════════════════════════════
// Abschnitt 7 deckt nur Elemente MIT data-i18n ab. Am 2026-08-31 stand im
// Sicherheits-Reiter woertlich "– Wer darf Codeaufgaben an Jarvis abgeben?" –
// ein harter Name in einem Hinweis ohne Attribut, den die Regel davor nicht
// sah. Gefunden hat es nicht dieser Waechter, sondern eine Pruefung des
// SICHTBAREN Textes im Browser vor einem Handbuch-Screenshot.
//
// branding.js ersetzt {marke} mit einem TreeWalker ueber den Body – ein
// Attribut braucht es dafuer nicht. Der Platzhalter gehoert also auch hierhin.
const OHNE_I18N_AUSNAHMEN = [
    // Branding-HAKEN: dort MUSS "Jarvis" stehen, branding.js ersetzt den Text
    // (NAME_LABEL_SELECTOR: .login-title, .header-title, .brand-app-name).
    'login-title',
    // Diese zwei Texte BESCHREIBEN den Vorgabenamen – "Ersetzt {marke} nur in
    // den Begruessungen" waere auf einer gebrandeten Installation sinnlos.
    'Ersetzt „Jarvis"',
    'Firmen-Branding',
];
function sichtbareTexte(html) {
    let s = html.replace(/<!--[\s\S]*?-->/g, '');
    s = s.replace(/<script\b[\s\S]*?<\/script>/gi, '<script></script>');
    s = s.replace(/<style\b[\s\S]*?<\/style>/gi, '<style></style>');
    const aus = [];
    // ⚠ `</?` – auch nach einem SCHLIESSENDEN Tag steht Text. Das Muster
    // verlangte ein oeffnendes und uebersah damit fuenf Stellen, darunter
    // "Wissensgruppen sind in Jarvis keine Leseschranke" (settings.html).
    // Aufgefallen ist das nicht beim Lesen, sondern weil ein
    // Playwright-Klick auf genau diesen Text in den Timeout lief.
    const re = /(<\/?[a-zA-Z][^<>]*>)([^<>]*\bJarvis\b[^<>]*)(?=<)/g;
    let m;
    while ((m = re.exec(s))) {
        const tag = m[1], txt = m[2].trim();
        if (!txt) continue;
        if (/brand-app-name|data-i18n|login-title/.test(tag)) continue;
        if (/^<\/?(title|script|style)\b/i.test(tag)) continue;
        if (OHNE_I18N_AUSNAHMEN.some((a) => tag.includes(a) || txt.includes(a))) continue;
        aus.push({ tag, txt });
    }
    return aus;
}
const offenOhne = [];
for (const f of HTML_DATEIEN) {
    for (const t of sichtbareTexte(lies(f))) {
        offenOhne.push(f + ': ' + t.txt.slice(0, 55));
    }
}
pruefe(offenOhne.length === 0,
       'kein sichtbarer Text ohne data-i18n nennt "Jarvis"',
       offenOhne.join(' | '));
// Positivkontrolle: die Ausnahmen greifen wirklich, der Filter ist nicht
// versehentlich blind (sonst waere die Null oben nichts wert).
const hakenDa = HTML_DATEIEN.filter((f) => /class="login-title"[^>]*>\s*Jarvis/.test(lies(f)));
pruefe(hakenDa.length >= 2, '.login-title behaelt "Jarvis" (Branding-Haken)',
       String(hakenDa.length));

// ══════════════════════════════════════════════════════════════════════════
abschnitt('6) GEMESSEN: der Beobachter setzt spaeter eingefuegten Text nach');
// ══════════════════════════════════════════════════════════════════════════
// Teil 5 liest nur den Quelltext. Ob der Beobachter WIRKT - und ob er nach
// einer eigenen Schreiboperation zur Ruhe kommt - sagt nur ein Lauf.
(async function () {
    let JSDOM;
    try { ({ JSDOM } = require('jsdom')); }
    catch (e) {
        try { ({ JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom')); }
        catch (e2) {
            // ⚠ FEHLENDES WERKZEUG IST KEIN FEHLSCHLAG. Diese Datei ist ein
            // RIEGEL fuer die Delegation: der Server klont das Repo frisch und
            // hat kein jsdom – ein FAIL an dieser Stelle lehnt den Auftrag ab,
            // obwohl an der Aenderung nichts falsch ist. Genau so ist Auftrag
            // be31e4825d52 gescheitert (17 OK, 1 FAIL: "jsdom vorhanden").
            //
            // Die Zusagen aus Abschnitt 5 (Beobachter samt Filter im Quelltext)
            // gelten weiter, sie brauchen kein jsdom. Gemessen wird der
            // Beobachter dort, wo jsdom liegt – lokal.
            console.log('  \x1b[33m–\x1b[0m jsdom nicht vorhanden – Abschnitt 6 '
                        + 'uebersprungen (kein Fehler; Abschnitt 5 prueft den Quelltext)');
            return abschluss();
        }
    }
    const dom = new JSDOM('<!DOCTYPE html><body><p>Alt</p></body>',
                          { url: 'https://dp.test/portal', runScripts: 'outside-only' });
    const w = dom.window;
    w.fetch = (u) => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(String(u).indexOf('/api/branding') >= 0
            ? { active: true, assistant_name: 'Nexerius', company_name: 'Nexus DP',
                colors: {}, colors_light: {}, logo_mode: 'letter', core_letter: 'nx' }
            : {}),
    });
    w.localStorage.setItem('jarvis_theme', 'light');
    // jsdom hat kein Canvas: letterFavicon() wirft sonst und bricht
    // applyBranding ab, BEVOR markeEinsetzen() laeuft - der Beobachter waere
    // nie eingerichtet und der Test gruen aus dem falschen Grund.
    w.HTMLCanvasElement.prototype.getContext = () => null;
    let rafs = 0;
    w.requestAnimationFrame = (f) => { rafs++; return setTimeout(f, 0); };
    w.eval(BRANDING);
    const warte = (ms) => new Promise((r) => setTimeout(r, ms));
    await warte(60);

    pruefe(w.jarvisMarke && w.jarvisMarke() === 'Nexerius',
           'der Markenname kommt an', w.jarvisMarke && w.jarvisMarke());

    // Der eigentliche Fall: Text, der ERST JETZT im DOM landet.
    const p1 = w.document.createElement('p');
    p1.textContent = 'Aufgabe für {marke} eingeben...';
    w.document.body.appendChild(p1);
    const v1 = rafs;
    await warte(80);
    pruefe(p1.textContent === 'Aufgabe für Nexerius eingeben...',
           'spaeter eingefuegter Text wird nachgesetzt', JSON.stringify(p1.textContent));
    pruefe(rafs - v1 === 1, 'und zwar mit EINEM Durchlauf, nicht je Knoten',
           String(rafs - v1));

    // Text OHNE Platzhalter darf gar keinen Durchlauf ausloesen.
    const p2 = w.document.createElement('p');
    p2.textContent = 'Ganz normaler Text';
    w.document.body.appendChild(p2);
    const v2 = rafs;
    await warte(80);
    pruefe(rafs - v2 === 0, 'Text ohne Platzhalter loest keinen Durchlauf aus',
           String(rafs - v2));

    // ⚠ DIE WICHTIGSTE MESSUNG: kommt es zur Ruhe? markeEinsetzen() SCHREIBT
    // Textknoten - ohne den Filter loest jeder eigene Schreibvorgang den
    // naechsten Durchlauf aus, und das laeuft fuer immer.
    const v3 = rafs;
    await warte(400);
    pruefe(rafs - v3 === 0, 'nach 400 ms Ruhe kein weiterer Durchlauf (keine Endlosschleife)',
           String(rafs - v3));
    w.close();
    abschluss();
})();

function abschluss() {
console.log('\n' + '='.repeat(58));
console.log((fail ? '\x1b[31m' : '\x1b[32m') + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
console.log('='.repeat(58));
process.exit(fail ? 1 : 0);
}
