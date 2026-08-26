#!/usr/bin/env node
/* Waechter: die Agentenliste in /chat nennt den MARKENNAMEN, nicht "Jarvis".
 *
 * Der Vorfall (2026-08-26, zweimal gemeldet): die Hauptagent-Karte trug ein
 * fest verdrahtetes 'Jarvis'. Auf einem White-Label-System nannte damit
 * ausgerechnet die Agentenliste das Produkt dahinter, waehrend Titelleiste,
 * Begruessung und Avatar laengst die Marke zeigen. Beim ersten Fix blieb eine
 * ZWEITE Stelle stehen (`_agentInfos` beim Start des Hauptagenten) - deshalb
 * prueft dieser Waechter die Eigenschaft und nicht die zwei bekannten Zeilen:
 *
 *   In `chat.js` darf das Wort "Jarvis" NIRGENDS als Beschriftung eines
 *   Agenten auftauchen - erlaubt ist es nur dort, wo `jarvisMarke()` selbst
 *   seinen Rueckfall bildet.
 *
 * Der zweite Teil fuehrt `_mainAgentLabel` und `_renderAgentPanel` wirklich
 * aus (per Schnitt aus der echten Datei, mit Minimal-Attrappen) und prueft das
 * erzeugte Markup - eine Quelltext-Pruefung allein saehe nicht, ob die
 * Funktion auch benutzt wird.
 *
 * jsdom ist in dieser Umgebung nicht installiert (weder lokal noch auf DEV),
 * deshalb ohne. Der Klick-Weg im echten Browser liegt in
 * tests/live_agent_panel_dev.py.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const WURZEL = path.resolve(__dirname, '..');
const CHATJS = fs.readFileSync(path.join(WURZEL, 'frontend/js/chat.js'), 'utf8');
const I18N = fs.readFileSync(path.join(WURZEL, 'frontend/js/i18n.js'), 'utf8');
const CHATHTML = fs.readFileSync(path.join(WURZEL, 'frontend/chat.html'), 'utf8');

let ok = 0, fail = 0;
function pruefe(bed, name, zusatz) {
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (zusatz ? '\n      ' + zusatz : '')); }
}
function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

/* Kommentare und Docstrings raus, sonst liest der Waechter seine eigene
   Begruendung mit - die Falle ist in diesem Projekt neunmal aufgetreten. */
function ohneKommentare(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/* ═══ 1. Kein hart verdrahtetes 'Jarvis' als Agenten-Beschriftung ═══════ */
abschnitt('1. Keine Marke im Quelltext');
{
    const code = ohneKommentare(CHATJS);
    // Jede Zeile, die 'Jarvis' als STRING-Literal fuehrt und dabei nach einer
    // Beschriftung aussieht (label:/textContent/Rueckfall mit ||).
    const treffer = code.split('\n').map((z, i) => ({ z: z, nr: i + 1 }))
        .filter(e => /['"]Jarvis['"]/.test(e.z))
        .filter(e => /\blabel\b|textContent|innerHTML|title=/.test(e.z));
    pruefe(treffer.length === 0,
        'kein String-Literal "Jarvis" in einer Beschriftung',
        treffer.map(e => 'Zeile ' + e.nr + ': ' + e.z.trim()).join('\n      '));

    // Positivkontrolle: das Muster wuerde einen Rueckfall finden, wenn es ihn
    // gaebe. Ohne diese Zeile waere die Pruefung oben auch dann gruen, wenn der
    // Filter gar nichts trifft.
    const probe = "            x = { label: agent.label || 'Jarvis', state: 'running' };";
    pruefe(/['"]Jarvis['"]/.test(probe) && /\blabel\b/.test(probe),
        'Positivkontrolle: das Muster erkennt genau so einen Rueckfall');
}

/* ═══ 2. Die Beschriftung kommt aus Branding + i18n ═════════════════════ */
abschnitt('2. Quelle der Beschriftung');
{
    const code = ohneKommentare(CHATJS);
    pruefe(/function\s+_mainAgentLabel\s*\(/.test(code),
        '_mainAgentLabel() existiert');
    pruefe((code.match(/function\s+_mainAgentLabel\s*\(/g) || []).length === 1,
        'genau EINE Definition (nach einem Block-Ersatz standen hier schon zwei)');
    pruefe(/window\.jarvisMarke/.test(code),
        'sie liest den Markennamen ueber jarvisMarke()');
    pruefe(/agent\.main/.test(code),
        'die Rolle kommt aus i18n (agent.main), nicht als fester Text');
    // Jede Stelle, die eine Hauptagent-Karte beschriftet, muss die Funktion
    // benutzen - nicht nur die eine, die zuerst gemeldet wurde.
    const nutzungen = (code.match(/_mainAgentLabel\(\)/g) || []).length;
    pruefe(nutzungen >= 3,
        'sie wird an allen Hauptagent-Stellen benutzt (' + nutzungen + ' Aufrufe)',
        'gefunden: ' + nutzungen);
    pruefe(/'agent\.main':\s*'Hauptagent'/.test(I18N) && /'agent\.main':\s*'Main agent'/.test(I18N),
        'agent.main ist in DE UND EN belegt');
}

/* ═══ 3. Sprachwechsel zeichnet neu ════════════════════════════════════ */
abschnitt('3. Sprachwechsel');
{
    const code = ohneKommentare(CHATJS);
    // Die Karten entstehen aus einem String - applyLang() erreicht sie nicht.
    pruefe(/jarvis-lang-changed[\s\S]{0,200}_renderAgentPanel/.test(code),
        'auf jarvis-lang-changed wird das Panel neu gezeichnet');
    pruefe(CHATHTML.indexOf('branding.js') < CHATHTML.indexOf('js/chat.js'),
        'branding.js wird VOR chat.js geladen (sonst gibt es jarvisMarke nicht)');
}

/* ═══ 4. Das erzeugte Markup - die Funktionen werden WIRKLICH ausgefuehrt ═ */
abschnitt('4. Gerendertes Markup');
{
    function schneide(name) {
        const start = CHATJS.indexOf('    function ' + name + '(');
        if (start < 0) throw new Error('nicht gefunden: ' + name);
        const ende = CHATJS.indexOf('\n    }\n', start);
        if (ende < 0) throw new Error('Ende nicht gefunden: ' + name);
        return CHATJS.slice(start, ende + 6);
    }
    const bau = new Function('$', '_agentInfos', '_isAdmin', '_activeAgentId',
        'agentRunning', 'window',
        schneide('_mainAgentLabel') + '\n' + schneide('_renderAgentPanel')
        + '\nreturn {_mainAgentLabel:_mainAgentLabel,_renderAgentPanel:_renderAgentPanel};');

    function lauf(marke, sprache, subs) {
        const win = {};
        if (marke) win.jarvisMarke = function () { return marke; };
        if (sprache) win.t = function (k) { return k === 'agent.main' ? sprache : k; };
        const list = { innerHTML: '', querySelectorAll: function () { return []; } };
        const panel = { style: {} };
        const infos = subs === false ? {}
            : { sub1: { label: 'Rolle: Bild-Erzeuger', state: 'running', is_sub_agent: true } };
        const f = bau(function (id) { return id === 'agent-panel' ? panel : list; },
            infos, true, '_main', false, win);
        f._renderAgentPanel();
        return { html: list.innerHTML, panel: panel };
    }
    function labels(html) {
        return (html.match(/<span title="[^"]*"[^>]*>([^<]*)<\/span>/g) || [])
            .map(s => s.replace(/^.*?>/, '').replace(/<\/span>$/, ''));
    }

    pruefe(labels(lauf(null, null).html)[0] === 'Jarvis · Hauptagent',
        'ohne Branding und ohne i18n: "Jarvis · Hauptagent" (unveraendertes Verhalten)',
        labels(lauf(null, null).html)[0]);
    pruefe(labels(lauf('Nexerius', 'Hauptagent').html)[0] === 'Nexerius · Hauptagent',
        'mit Branding: der Markenname steht vorn',
        labels(lauf('Nexerius', 'Hauptagent').html)[0]);
    pruefe(labels(lauf('Nexerius', 'Main agent').html)[0] === 'Nexerius · Main agent',
        'englische Oberflaeche: "Main agent"');
    pruefe(/Jarvis/.test(lauf('Nexerius', 'Hauptagent').html) === false,
        'im gebrandeten Markup kommt "Jarvis" NICHT mehr vor');
    pruefe(labels(lauf('Nexerius', 'Hauptagent').html)[1] === 'Rolle: Bild-Erzeuger',
        'die Sub-Agenten-Karte bleibt unveraendert');
    pruefe(/&lt;b&gt;/.test(lauf('<b>X', 'Hauptagent').html),
        'ein Markenname mit spitzen Klammern wird maskiert');
    // title, weil die Karte 220 px breit ist und mit Ellipse abschneidet.
    const lang = lauf('Ein sehr langer Markenname GmbH', 'Hauptagent').html;
    pruefe((lang.match(/title="([^"]*)"/) || [])[1] === 'Ein sehr langer Markenname GmbH · Hauptagent',
        'die volle Beschriftung steht im title-Attribut');
    // Ohne Sub-Agenten bleibt das Panel aus - sonst stuende es dauerhaft im Bild.
    pruefe(lauf('Nexerius', 'Hauptagent', false).panel.style.display === 'none',
        'ohne Sub-Agenten bleibt das Panel versteckt');
}

console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
process.exit(fail ? 1 : 0);
