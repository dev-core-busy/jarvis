/* ═══════════════════════════════════════════════════════════════════════
   Waechter: eine FEHLERMELDUNG im Chat verschwindet nicht von selbst
   ───────────────────────────────────────────────────────────────────────
   GEMELDET AUF ECHT (2026-10-06): ein PDF sollte in ein JPEG
   umgewandelt werden. "weder vorschau noch download link gibt er aus".

   Die Datei hiess in Wahrheit `Auftragsnummer_C128-1.jpg` (pdftoppm haengt die
   Seitennummer an) – das ist die Backend-Haelfte, geprueft in
   tests/test_doc_delivery.py. Die FRONTEND-Haelfte ist schlimmer, weil sie
   jede kuenftige Meldung betrifft:

   `_deliver_docs` sendet "⚠️ Konnte nicht zum Download bereitgestellt werden:
   …" mit `highlight=true`, ausdruecklich damit die Zeile dort steht, wo der
   Benutzer den Download erwartet. `handleStatus` entscheidet aber am ERSTEN
   ZEICHEN: steht der Text in `STATUS_PREFIXES` (und `⚠️` steht drin), gilt er
   als laufende Aktivitaet, der highlight-Zweig wird uebersprungen, und die
   Meldung landet in der transienten Spinner-Zeile – die `_clearActivity()` am
   Laufende wieder entfernt. Im Journal auf ECHT steht die Zeile, im Chat stand
   sie nie.

   ⚠ GEMESSEN WIRD DIE WIRKUNG, NICHT DER QUELLTEXT: ueberlebt die Meldung den
   Aufruf, der am Ende jedes Laufs kommt? Eine Suche nach `persist` in der
   Datei waere blind dagegen, dass der Block HINTER der Praefix-Regel steht und
   damit nie greift.

   Die Gegenprobe steckt IM Waechter: dieselbe Meldung OHNE `persist` muss
   weiterhin verschwinden. Verhielten sich beide gleich, waere der Messaufbau
   kaputt – und "sie bleibt stehen" trivial wahr.

   Ausgefuehrt: node tests/test_chat_status_sichtbar.js
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const WURZEL = path.resolve(__dirname, '..');
const FE = path.join(WURZEL, 'frontend');
const lies = (rel) => fs.readFileSync(path.join(FE, rel), 'utf-8');

let ok = 0, fail = 0, bilanz = false;
function pruefe(text, bedingung, zusatz) {
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
// Nur einen STILLEN Abbruch anheben – ein `process.exit(2)` darf nicht zu
// Exit 1 werden, sonst sagt "konnte nicht laufen" dasselbe wie "ich beisse".
process.on('exit', (code) => {
    if (!bilanz && code === 0) process.exitCode = 1;
});

const CHAT_JS = lies('js/chat.js');
const CSS = lies('css/chat.css');

/* ── Eine Funktion aus chat.js schneiden – an der STRUKTUR, nicht an einer
 * Textmarke: ab `function name(` bis zur schliessenden Klammer auf DERSELBEN
 * Einrueckungstiefe. Findet sie sich nicht, ist der Messaufbau hinfaellig
 * (Exit 2), nicht der Code falsch. */
function schneide(name) {
    const zeilen = CHAT_JS.split('\n');
    const start = zeilen.findIndex(z => new RegExp('^\\s*function ' + name + '\\s*\\(').test(z));
    if (start < 0) {
        console.log(`ABBRUCH: function ${name}() in chat.js nicht gefunden – `
                    + 'umbenannt? Dann gehoert dieser Waechter nachgezogen.');
        process.exit(2);
    }
    const tiefe = zeilen[start].length - zeilen[start].trimStart().length;
    const raus = [zeilen[start]];
    for (let i = start + 1; i < zeilen.length; i++) {
        raus.push(zeilen[i]);
        const z = zeilen[i];
        if (z.trim() === '}' && (z.length - z.trimStart().length) === tiefe) break;
    }
    return raus.join('\n');
}

const GESCHNITTEN = ['handleStatus', 'addStatusLine', '_setActivity', '_clearActivity']
    .map(schneide).join('\n\n');

// Positivkontrolle des Messwerkzeugs: die Schnitte muessen den Code WIRKLICH
// enthalten, nicht eine leere Huelle (ein zu frueh gefundenes `}` haette das
// zur Folge, und jede Pruefung danach waere trivial).
if (!/msg\.persist/.test(GESCHNITTEN) || !/_activityEl/.test(GESCHNITTEN)
        || !/STATUS_PREFIXES/.test(GESCHNITTEN)) {
    console.log('ABBRUCH: die geschnittenen Funktionen sind unvollstaendig – '
                + 'der Schnitt greift nicht.');
    process.exit(2);
}

/* ── Die Buehne. jsdom rechnet kein Layout, wertet aber Stylesheets aus –
 * mehr braucht dieser Waechter nicht: gemessen wird, WELCHE Knoten nach dem
 * Laufende noch im DOM stehen. */
function buehne() {
    const dom = new JSDOM(
        `<!DOCTYPE html><html><head><style>${CSS}</style></head>`
        + '<body><div id="messages"></div></body></html>',
        { pretendToBeVisual: true });
    const w = dom.window;
    const umgebung = {
        messagesEl: w.document.getElementById('messages'),
        document: w.document,
        // Was die geschnittenen Funktionen sonst noch anfassen. Bewusst als
        // AUFZEICHNENDE Attrappen: landet ein Text hier, ist das selbst eine
        // Aussage (dann ging er NICHT in die Statuszeile).
        scrollToBottom: () => {},
        appendToBotBubble: (t) => { umgebung.blasen.push(t); },
        _appendSubBubble: (a, t) => { umgebung.subblasen.push(t); },
        _agentInfos: {},
        _runSid: null,
        _activeSid: null,
        _ttsBuf: '',
        _lastBotResp: '',
        _chatDebug: false,
        _activityEl: null,
        blasen: [],
        subblasen: [],
    };
    const quelle = `
        let _activityEl = null;
        let _ttsBuf = '', _lastBotResp = '';
        const _chatDebug = ${umgebung._chatDebug};
        const _agentInfos = {}, _runSid = null, _activeSid = null;
        const messagesEl = __u.messagesEl;
        const document = __u.document;
        const scrollToBottom = __u.scrollToBottom;
        const appendToBotBubble = __u.appendToBotBubble;
        const _appendSubBubble = __u._appendSubBubble;
        ${GESCHNITTEN}
        __u.handleStatus = handleStatus;
        __u.clearActivity = _clearActivity;
    `;
    // eslint-disable-next-line no-new-func
    new Function('__u', quelle)(umgebung);
    umgebung.fenster = w;
    umgebung.zeilen = () => Array.from(
        umgebung.messagesEl.querySelectorAll('.msg-status')).map(e => e.textContent);
    umgebung.aktivitaet = () =>
        umgebung.messagesEl.querySelectorAll('.chat-activity').length;
    return umgebung;
}

const WARNUNG = '⚠️ Konnte nicht zum Download bereitgestellt werden: '
              + 'Auftragsnummer_C128.jpg. Ein im Text genannter Link führt ins '
              + 'Leere – bitte die Datei erneut erzeugen lassen.';

// ═══ 1. Der Messaufbau ueberhaupt ════════════════════════════════════════
console.log('\n1. Messaufbau');
{
    const b = buehne();
    pruefe('die Praefixliste in chat.js enthaelt ⚠️ (sonst gaebe es den Fehler nicht)',
           /STATUS_PREFIXES = \[[^\]]*'⚠️'/.test(CHAT_JS));
    b.handleStatus({ message: '🔧 Werkzeug laeuft', state: 's' });
    pruefe('ein gewoehnlicher Status erzeugt eine Aktivitaetszeile',
           b.aktivitaet() === 1, String(b.aktivitaet()));
    b.clearActivity();
    pruefe('und _clearActivity() raeumt sie weg (das Laufende)',
           b.aktivitaet() === 0, String(b.aktivitaet()));
}

// ═══ 2. DER GEMELDETE FALL ════════════════════════════════════════════════
console.log('\n2. Die Liefer-Warnung ueberlebt das Laufende');
{
    const b = buehne();
    // ERST die laufende Aktivitaet herstellen – sonst gibt es keinen Spinner,
    // den der persist-Zweig wegraeumen muesste, und "es bleibt keine
    // Aktivitaetszeile" waere trivial wahr. Eine Gegenprobe
    // ("_clearActivity() im persist-Zweig vergessen") blieb genau daran stumm.
    b.handleStatus({ message: '🔧 pdftoppm laeuft', state: 's' });
    pruefe('vor der Warnung laeuft eine Aktivitaetszeile (Messvoraussetzung)',
           b.aktivitaet() === 1, String(b.aktivitaet()));

    b.handleStatus({ message: WARNUNG, state: 's', highlight: true, persist: true });
    const vorher = b.zeilen();
    pruefe('die Warnung raeumt den Spinner selbst weg',
           b.aktivitaet() === 0, String(b.aktivitaet()));

    b.clearActivity();          // genau das passiert am Ende jedes Laufs
    const nachher = b.zeilen();

    pruefe('die Warnung steht als dauerhafte Zeile im Verlauf',
           vorher.length === 1 && vorher[0].indexOf('Konnte nicht zum Download') >= 0,
           JSON.stringify(vorher));
    pruefe('sie ueberlebt _clearActivity()',
           nachher.length === 1, JSON.stringify(nachher));
    pruefe('es bleibt KEINE transiente Aktivitaetszeile uebrig',
           b.aktivitaet() === 0, String(b.aktivitaet()));
    pruefe('der Dateiname steht darin (sonst weiss der Benutzer nicht, was fehlt)',
           nachher[0] && nachher[0].indexOf('Auftragsnummer_C128.jpg') >= 0,
           JSON.stringify(nachher));
    pruefe('und sie landet NICHT als Antworttext in einer Bot-Blase',
           b.blasen.length === 0, JSON.stringify(b.blasen));
}

// ═══ 3. GEGENPROBE: ohne persist verschwindet sie weiter ══════════════════
/* Das ist der Zustand vor dem Fix – und der Beweis, dass dieser Messaufbau den
 * Unterschied SEHEN kann. Ohne diesen Abschnitt waere Abschnitt 2 auch dann
 * gruen, wenn die Buehne jede Nachricht dauerhaft machte. */
console.log('\n3. Gegenprobe: derselbe Text ohne persist');
{
    const b = buehne();
    b.handleStatus({ message: WARNUNG, state: 's', highlight: true });
    pruefe('ohne persist ist es nur eine Aktivitaetszeile',
           b.aktivitaet() === 1 && b.zeilen().length === 0,
           `aktivitaet=${b.aktivitaet()} zeilen=${JSON.stringify(b.zeilen())}`);
    b.clearActivity();
    pruefe('und sie ist nach dem Laufende WEG (der gemeldete Zustand)',
           b.aktivitaet() === 0 && b.zeilen().length === 0,
           JSON.stringify(b.zeilen()));
}

// ═══ 4. persist darf den Normalbetrieb nicht umbauen ═════════════════════
console.log('\n4. Was sich NICHT aendern durfte');
{
    const b = buehne();
    // Der Fortschritts-Hinweis kommt mit highlight=true und MUSS transient
    // bleiben – deshalb wurde die Praefix-Regel nicht einfach umgedreht.
    b.handleStatus({ message: '⏳ Warte auf LLM-Antwort…', state: 's', highlight: true });
    pruefe('"⏳ Warte auf LLM-Antwort…" bleibt transient',
           b.aktivitaet() === 1 && b.zeilen().length === 0,
           `aktivitaet=${b.aktivitaet()} zeilen=${JSON.stringify(b.zeilen())}`);

    const b2 = buehne();
    b2.handleStatus({ message: 'Die Konvertierung war erfolgreich.', state: 's', highlight: true });
    pruefe('echter Antworttext geht weiter in die Bot-Blase',
           b2.blasen.length === 1 && b2.zeilen().length === 0,
           JSON.stringify(b2.blasen));

    const b3 = buehne();
    b3.handleStatus({ message: '⏸ angehalten', state: 's' });
    pruefe('die Pause-Zeile bleibt eine dauerhafte Statuszeile',
           b3.zeilen().length === 1, JSON.stringify(b3.zeilen()));
    pruefe('und zwar OHNE Warn-Aufmachung',
           !b3.messagesEl.querySelector('.msg-status-warn'),
           b3.messagesEl.innerHTML);
}

// ═══ 5. Die Zeile ist auch zu SEHEN ══════════════════════════════════════
/* Eine Meldung, die niemand sieht, ist keine Meldung (Register). `.msg-status`
 * allein ist 12 px, grau und zentriert – fuer "deine Datei fehlt" zu leise.
 * Gemessen wird die kaskadierte Eigenschaft, nicht die CSS-Zeile. */
console.log('\n5. Aufmachung');
{
    const b = buehne();
    b.handleStatus({ message: WARNUNG, state: 's', highlight: true, persist: true });
    const el = b.messagesEl.querySelector('.msg-status');
    pruefe('die Zeile traegt die Warn-Klasse', !!el && el.classList.contains('msg-status-warn'),
           el ? el.className : 'kein Element');
    const stil = b.fenster.getComputedStyle(el);
    pruefe('sie ist groesser als der gewoehnliche Status (12 px)',
           parseFloat(stil.fontSize) > 12, stil.fontSize);
    pruefe('sie ist linksbuendig, nicht zentriert', stil.textAlign === 'left', stil.textAlign);
    // ⚠ GEMESSEN: jsdom liefert fuer ein Element OHNE Flaeche
    // `background: "rgba(0, 0, 0, 0)"`. Die erste Fassung dieser Pruefung liess
    // `rgb` als Treffer zu und war damit trivial wahr – eine Gegenprobe, die
    // die Flaeche entfernte, blieb stumm. Custom Properties loest jsdom nicht
    // auf, es gibt sie woertlich zurueck: genau darauf wird geprueft (und das
    // ist zugleich die Hausregel "keine hardcoded Farben").
    pruefe('sie hat eine DECKENDE Flaeche (sie liegt ueber dem Verlauf)',
           /var\(--bg-secondary\)/.test(stil.background || ''),
           JSON.stringify(stil.background));

}

// ═══ 6. KONTRAST – gerechnet, nicht geschaetzt ═══════════════════════════
/* ⚠ WARUM GERECHNET: die erste Fassung der Regel pruefte die SCHREIBWEISE
 * ("steht da color-mix?"). Sie war gruen – und die Farbe im DUNKLEN Thema
 * hatte 3,08:1. Die 78%-Abdunklung aus theme.css stammt aus einem Befund auf
 * HELLER Flaeche; auf #111827 ist sie schlechter als das nackte --danger.
 * Geprueft wird deshalb die Eigenschaft: Schrift gegen ihre FLAECHE, in BEIDEN
 * Themen, gegen die Textgrenze 4,5:1. jsdom loest `var()`/`color-mix()` nicht
 * auf – die Werte kommen aus theme.css und werden hier nachgerechnet. */
console.log('\n6. Kontrast in beiden Themen');
{
    const THEME = lies('css/theme.css');

    // ⚠ Kommentare heraus, BEVOR irgendetwas gesucht wird: die Begruendungen
    // an diesen Regeln NENNEN `--danger`, `color-mix(… 78%, #000)` und die
    // gemessenen Zahlen. Ein Waechter, der seine eigene Erklaerung liest,
    // prueft nichts (Register).
    const ohneKomm = (s) => s.replace(/\/\*[\s\S]*?\*\//g, ' ');
    const THEME_C = ohneKomm(THEME), CSS_C = ohneKomm(CSS);

    // Eine Variable im :root- bzw. body.light-Block – an der STRUKTUR
    // geschnitten, damit nicht der erste Treffer irgendwo in der Datei gilt.
    // Gesucht wird in theme.css UND chat.css: `--surface-variant` (die Flaeche
    // der Herkunfts-Warnung) steht nur in chat.css, und eine Rechnung gegen
    // die falsche Flaeche ist schlimmer als keine (Register: eine
    // Kontrast-Loesung gilt nur fuer DIE Flaeche, fuer die sie gemessen wurde).
    function variable(block, name) {
        for (const quelle of [THEME_C, CSS_C]) {
            const i = quelle.indexOf(block + ' {');
            if (i < 0) continue;
            const ende = quelle.indexOf('\n}', i);
            const m = quelle.slice(i, ende).match(
                new RegExp('--' + name + ':\\s*([^;]+);'));
            if (m) return m[1].trim();
        }
        return '';
    }
    const srgb = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const leucht = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
    // ⚠ BEIDE Kurzformen: `#000` ist in CSS gueltig und ergab mit der naiven
    // Zweier-Schnittweise [0, 0, NaN] – der Kontrast war dann NaN und die
    // Pruefung fiel aus einem Formatfehler durch, nicht aus einem Befund.
    const hx = (s) => {
        s = s.replace('#', '').trim();
        if (s.length === 3) s = s.split('').map(c => c + c).join('');
        if (!/^[0-9a-f]{6}$/i.test(s)) return [];
        return [0, 2, 4].map(i => parseInt(s.substr(i, 2), 16));
    };
    const kontrast = (a, b) => {
        const la = leucht(a), lb = leucht(b);
        return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };
    // color-mix(in srgb, <c1> <p>%, <c2>) nachrechnen
    const mix = (c1, c2, p) => c1.map((v, i) => Math.round(v * p + c2[i] * (1 - p)));

    const danger = hx(variable(':root', 'danger'));
    pruefe('--danger ist aus theme.css gelesen', danger.length === 3 && danger[0] > 0,
           JSON.stringify(danger));

    // Welche Farbe gilt je Thema? Aus chat.css gelesen, nicht angenommen.
    const warnRegel = (praefix, sel) => {
        const i = CSS_C.indexOf(praefix + sel + ' {');
        if (i < 0) return '';
        const m = CSS_C.slice(i, CSS_C.indexOf('}', i)).match(/color:\s*([^;]+);/);
        return m ? m[1].trim() : '';
    };
    const deuten = (ausdruck) => {
        if (/^var\(--danger\)$/.test(ausdruck)) return danger;
        const m = ausdruck.match(/color-mix\(in srgb,\s*var\(--danger\)\s*(\d+)%\s*,\s*(#[0-9a-f]{3,6})\)/i);
        if (!m) return null;
        const zweite = hx(m[2]);
        return zweite.length === 3
            ? mix(danger, zweite, parseInt(m[1], 10) / 100) : null;
    };

    /* Jede Warnschrift mit IHRER Flaeche. ⚠ Die Flaeche gehoert zur Zusage:
     * `.jv-best-herkunft.is-uebernommen` liegt auf `--surface-variant`, nicht
     * auf der Kartenflaeche – und dort haelt im dunklen Thema WEDER das nackte
     * --danger (4,22:1) noch die Abdunklung (2,76:1), waehrend beide auf
     * `--bg-secondary` je in einem Thema richtig sind. Genau diese Verwechslung
     * hat der Code-Review 2026-10-24 gefunden; eine Pruefung ohne Flaeche
     * haette sie nicht sehen koennen. */
    const WARNSCHRIFTEN = [
        ['.msg-status-warn', 'bg-secondary'],
        // Bestaetigungskarte (BSI H9): beide Texte MUESSEN auffaellig sein –
        // der eine sagt, dass der Empfaenger fehlt, der andere, dass die
        // Adresse ungeprueft ist.
        ['.jv-best-pflicht', 'bg-secondary'],
        ['.jv-best-herkunft.is-uebernommen', 'surface-variant'],
    ];
    for (const [sel, flaechenVar] of WARNSCHRIFTEN) {
        for (const [thema, block, praefix] of [['dunkel', ':root', ''],
                                               ['hell', 'body.light', 'body.light ']]) {
            const flaeche = hx(variable(block, flaechenVar));
            pruefe(`[${thema}] Flaeche --${flaechenVar} ist gelesen`,
                   flaeche.length === 3, variable(block, flaechenVar) || 'nicht gefunden');
            if (flaeche.length !== 3) continue;
            // Im hellen Thema gilt die Themenregel, sonst die Basisregel.
            const ausdruck = warnRegel(praefix, sel) || warnRegel('', sel);
            const schrift = deuten(ausdruck);
            pruefe(`[${thema}] ${sel}: Schriftfarbe auswertbar (${ausdruck})`,
                   !!schrift, ausdruck || 'keine color-Angabe gefunden');
            if (!schrift) continue;
            const k = kontrast(schrift, flaeche);
            pruefe(`[${thema}] ${sel}: ${k.toFixed(2)}:1 erreicht die Textgrenze 4,5:1`,
                   k >= 4.5,
                   `Schrift ${JSON.stringify(schrift)} auf --${flaechenVar} `
                   + `${JSON.stringify(flaeche)}`);
        }
    }

    // Positivkontrolle der Rechnung: ein bekannt schlechtes Paar MUSS
    // durchfallen. Ohne sie waere "alles ueber 4,5" auch dann gruen, wenn die
    // Formel Unsinn liefert.
    pruefe('die Kontrastrechnung erkennt ein schlechtes Paar',
           kontrast([239, 68, 68], [255, 255, 255]) < 4.5,
           String(kontrast([239, 68, 68], [255, 255, 255])));
}

console.log(`\n${'═'.repeat(70)}\nErgebnis: ${ok} OK, ${fail} FAIL`);
bilanz = true;
process.exit(fail ? 1 : 0);
